"""
Contract tests for the three background-job pipelines that share one shape:
/api/essay, /api/outline and /api/precis (submit -> status -> result -> download).

The real grading functions (OCR + Grok + rendering) are replaced by a fake runner;
everything else -- upload handling, job store, progress file, brand propagation to the
worker thread, temp-dir cleanup, error reporting -- is the real code.
"""

from __future__ import annotations

import importlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

from support.pdfs import page_count, text_pdf

pytestmark = pytest.mark.api

PDF = text_pdf(["handwritten essay page 1", "page 2"])


@dataclass(frozen=True)
class Kind:
    name: str
    module: str
    runner: str
    asset_dir_getter: str
    pipeline: Optional[str]
    subject: str
    stale_folder: str


KINDS = {
    "essay": Kind("essay", "backend.api.routes.essay", "run_essay_grading", "_get_eng_essay_dir", None, "English Essay", "grok_images_essay_old"),
    "outline": Kind("outline", "backend.api.routes.outline", "run_outline_grading", "_get_outline_dir", "outline", "English Essay Outline", "grok_images_outline_old"),
    "precis": Kind("precis", "backend.api.routes.precis", "run_precis_grading", "_get_precis_dir", "precis", "English Precis", "grok_images_precis_old"),
}


class Pipeline:
    def __init__(self, kind: Kind, module, workdir: Path, logs: Path, assets: Path):
        self.kind, self.module, self.workdir, self.logs, self.assets = kind, module, workdir, logs, assets
        self.runner_calls: list = []
        self.runner_behaviour = "ok"

    def form(self, **extra):
        data = {"user_id": "user-42"}
        if self.kind.pipeline:
            data["pipeline"] = self.kind.pipeline
        data.update(extra)
        return data

    def submit(self, client, *, name="script.pdf", content=PDF, headers=None, **extra):
        return client.post(
            f"/api/{self.kind.name}/submit",
            files={"file": (name, content, "application/pdf")},
            data=self.form(**extra),
            headers=headers or {},
        )


def _build_pipeline(kind_name, monkeypatch, tmp_path):
    kind = KINDS[kind_name]
    module = importlib.import_module(kind.module)

    logs = tmp_path / "logs"
    assets = tmp_path / f"{kind.name}_assets"
    workdir = tmp_path / "cwd"
    for d in (logs, assets, workdir):
        d.mkdir()

    from backend.api.routes import ocr as ocr_route
    from backend.ocr.job_manager import OCRJobManager

    # Mirror production layout (logs/<kind>_jobs + logs/<kind>_results), but under tmp.
    monkeypatch.setattr(
        module,
        "_job_manager",
        OCRJobManager(jobs_dir=str(logs / f"{kind.name}_jobs"), results_dir=str(logs / f"{kind.name}_results")),
    )
    monkeypatch.setattr(module, "_get_logs_dir", lambda: str(logs))
    monkeypatch.setattr(ocr_route, "_get_logs_dir", lambda: str(logs))  # /api/ocr/progress reads the same dir
    monkeypatch.setattr(module, kind.asset_dir_getter, lambda: str(assets))
    monkeypatch.chdir(workdir)  # submit() creates temp_<kind>_job_* relative to CWD

    p = Pipeline(kind, module, workdir, logs, assets)

    def fake_runner(**kwargs):
        from backend.utils.report_cover import current_report_brand

        p.runner_calls.append(
            {
                **kwargs,
                "input_bytes": Path(kwargs["pdf_path"]).read_bytes(),
                "brand_on_worker": current_report_brand(),
            }
        )
        cb = kwargs.get("progress_callback")
        if cb:
            cb(50, "Halfway there")
        if p.runner_behaviour == "raise":
            raise RuntimeError("OCR provider timed out")
        if p.runner_behaviour != "no_pdf":
            Path(kwargs["output_pdf_path"]).write_bytes(text_pdf(["cover", "annotated page"]))
        Path(kwargs["output_json_path"]).write_text("{}", encoding="utf-8")
        return {"overall": "Average", "marks_range": "28-32"}

    monkeypatch.setattr(module, kind.runner, fake_runner)
    return p


@pytest.fixture(params=sorted(KINDS))
def pipeline(request, monkeypatch, tmp_path):
    return _build_pipeline(request.param, monkeypatch, tmp_path)


@pytest.fixture(params=["outline", "precis"])
def token_pipeline(request, monkeypatch, tmp_path):
    """Only outline/precis require a `pipeline` form token."""
    return _build_pipeline(request.param, monkeypatch, tmp_path)


def _status(client, p, job_id):
    return client.get(f"/api/{p.kind.name}/status/{job_id}")


# ---------------------------------------------------------------- validation


def test_non_pdf_rejected(client, pipeline):
    resp = pipeline.submit(client, name="script.png", content=b"\x89PNG")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Only PDF files are supported."
    assert pipeline.runner_calls == []


def test_user_id_is_required(client, pipeline):
    resp = client.post(
        f"/api/{pipeline.kind.name}/submit",
        files={"file": ("a.pdf", PDF, "application/pdf")},
        data={k: v for k, v in pipeline.form().items() if k != "user_id"},
    )
    assert resp.status_code == 422


@pytest.mark.parametrize("token", ["", "essay", "precis-v2"])
def test_pipeline_token_guards_outline_and_precis(client, token_pipeline, token):
    resp = token_pipeline.submit(client, pipeline=token)
    assert resp.status_code == 400
    assert f"Expected pipeline='{token_pipeline.kind.pipeline}'" in resp.json()["detail"]
    assert token_pipeline.runner_calls == []


def test_missing_pipeline_token_is_rejected(client, token_pipeline):
    resp = client.post(
        f"/api/{token_pipeline.kind.name}/submit",
        files={"file": ("a.pdf", PDF, "application/pdf")},
        data={"user_id": "u"},
    )
    assert resp.status_code == 400


def test_pipeline_token_is_case_and_space_insensitive(client, token_pipeline):
    resp = token_pipeline.submit(client, pipeline=f"  {token_pipeline.kind.pipeline.upper()} ")
    assert resp.status_code == 200


# ---------------------------------------------------------------- unknown jobs


def test_unknown_job(client, pipeline):
    name = pipeline.kind.name
    assert client.get(f"/api/{name}/status/nope").status_code == 404
    assert client.get(f"/api/{name}/download/nope").status_code == 404
    resp = client.get(f"/api/{name}/result/nope")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Job not completed"


# ---------------------------------------------------------------- happy path


def test_submit_runs_job_and_serves_results(client, pipeline):
    resp = pipeline.submit(client)
    assert resp.status_code == 200
    body = resp.json()
    job_id, request_id = body["jobId"], body["requestId"]

    # TestClient runs BackgroundTasks before returning, so the job is already done.
    status = _status(client, pipeline, job_id).json()
    assert status["status"] == "completed"
    assert status["subject"] == pipeline.kind.subject
    assert status["user_id"] == "user-42"
    assert status["filename"] == "script.pdf"
    assert status["started_at"] <= status["completed_at"]

    (call,) = pipeline.runner_calls
    assert call["input_bytes"] == PDF

    result = client.get(f"/api/{pipeline.kind.name}/result/{job_id}")
    assert result.status_code == 200
    assert result.json() == {
        "result": {"overall": "Average", "marks_range": "28-32"},
        "annotated_pdf_url": f"/api/{pipeline.kind.name}/download/{job_id}",
    }

    download = client.get(f"/api/{pipeline.kind.name}/download/{job_id}")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert f"annotated_{pipeline.kind.name}_{job_id}.pdf" in download.headers["content-disposition"]
    assert page_count(download.content) == 2

    # Progress is shared with /api/ocr/progress (the frontends poll that endpoint).
    progress = client.get(f"/api/ocr/progress/{request_id}").json()
    assert progress["progress_percent"] == 100.0
    assert "Complete" in progress["message"]


def test_temp_upload_dir_removed_after_job(client, pipeline):
    assert pipeline.submit(client).status_code == 200
    leftovers = [p.name for p in pipeline.workdir.iterdir()]
    assert leftovers == []


def test_stale_debug_folders_and_old_results_are_cleaned(client, pipeline):
    stale = pipeline.assets / pipeline.kind.stale_folder
    stale.mkdir()
    (stale / "img.png").write_bytes(b"x")
    keep = pipeline.assets / "rubric.docx"
    keep.write_bytes(b"docx")

    results_dir = pipeline.logs / f"{pipeline.kind.name}_results"
    results_dir.mkdir(parents=True, exist_ok=True)
    old = results_dir / "result_old.json"
    old.write_text("{}")
    two_days_ago = time.time() - 48 * 3600
    os.utime(old, (two_days_ago, two_days_ago))

    assert pipeline.submit(client).status_code == 200
    assert not stale.exists()
    assert keep.exists()
    assert not old.exists()


@pytest.mark.parametrize(
    ("form_brand", "headers", "expected"),
    [
        (None, {}, "rubric"),
        (None, {"Origin": "https://lca-portal.vercel.app"}, "lca"),
        ("lahore-css-academy", {}, "lca"),
        ("rubric.ai", {"Referer": "https://lca-portal.org/x"}, "rubric"),
    ],
)
def test_brand_reaches_worker_thread(client, pipeline, form_brand, headers, expected):
    extra = {"brand": form_brand} if form_brand else {}
    job_id = pipeline.submit(client, headers=headers, **extra).json()["jobId"]
    assert pipeline.runner_calls[-1]["brand_on_worker"] == expected
    assert _status(client, pipeline, job_id).json()["brand"] == expected


# ---------------------------------------------------------------- failures


def test_pipeline_exception_marks_job_failed(client, pipeline):
    pipeline.runner_behaviour = "raise"
    body = pipeline.submit(client).json()
    status = _status(client, pipeline, body["jobId"]).json()
    assert status["status"] == "failed"
    assert status["error"] == "OCR provider timed out"

    resp = client.get(f"/api/{pipeline.kind.name}/result/{body['jobId']}")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "OCR provider timed out"
    assert client.get(f"/api/{pipeline.kind.name}/download/{body['jobId']}").status_code == 404

    progress = client.get(f"/api/ocr/progress/{body['requestId']}").json()
    assert progress["message"] == "Failed: OCR provider timed out"


def test_missing_output_pdf_marks_job_failed(client, pipeline):
    pipeline.runner_behaviour = "no_pdf"
    job_id = pipeline.submit(client).json()["jobId"]
    status = _status(client, pipeline, job_id).json()
    assert status["status"] == "failed"
    assert "PDF output not created" in status["error"]


def test_completed_job_with_deleted_json_is_500(client, pipeline):
    job_id = pipeline.submit(client).json()["jobId"]
    pipeline.module._job_manager._get_result_json_path(job_id).unlink()
    resp = client.get(f"/api/{pipeline.kind.name}/result/{job_id}")
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Result files missing"


@pytest.mark.xfail(
    strict=True,
    reason="BUG: submit writes the upload to os.path.join(temp_dir, file.filename) without sanitising, "
    "so a filename like '../x.pdf' escapes the per-job temp dir (path traversal)",
)
def test_upload_filename_cannot_escape_temp_dir(client, pipeline, monkeypatch):
    # Keep the upload on disk (skip the background job, which would delete temp dirs).
    monkeypatch.setattr(pipeline.module, f"_process_{pipeline.kind.name}_job", lambda *a, **k: None)
    resp = pipeline.submit(client, name="../escaped.pdf")
    assert resp.status_code in (200, 400)
    assert not (pipeline.workdir / "escaped.pdf").exists()
    assert not (pipeline.workdir.parent / "escaped.pdf").exists()


def test_status_payload_is_json_serialisable_job(client, pipeline):
    job_id = pipeline.submit(client).json()["jobId"]
    raw = pipeline.module._job_manager._get_job_file_path(job_id).read_text(encoding="utf-8")
    assert json.loads(raw)["job_id"] == job_id
