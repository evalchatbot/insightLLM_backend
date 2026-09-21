"""Contract tests for /api/ocr and /api/ocr-regular (grading pipeline mocked out)."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import pytest

from support.pdfs import text_pdf

pytestmark = pytest.mark.api

PDF = text_pdf(["answer page"])


@pytest.fixture
def ocr_route(monkeypatch, tmp_path, job_manager_factory):
    """The /api/ocr router with its job store, logs dir and grader pointed at tmp_path."""
    from backend.api.routes import ocr as route

    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(route, "_job_manager", job_manager_factory("ocr"))
    monkeypatch.setattr(route, "_get_logs_dir", lambda: str(logs))
    return route


@pytest.fixture(autouse=True)
def no_storage(monkeypatch):
    """Supabase Storage is unavailable unless a test installs a fake."""
    from backend.db import storage

    class Unavailable:
        def __init__(self):
            raise RuntimeError("storage disabled in tests")

    monkeypatch.setattr(storage, "StorageService", Unavailable)


@pytest.fixture
def fake_grader(monkeypatch, ocr_route):
    """Replace the heavy OCR+Grok pipeline with one that writes a tiny result."""
    calls = []

    def fake_process(job, job_manager):
        calls.append(job.job_id)
        out_pdf = job_manager.results_dir / f"result_{job.job_id}.pdf"
        out_json = job_manager.results_dir / f"result_{job.job_id}.json"
        out_pdf.write_bytes(text_pdf(["annotated"]))
        out_json.write_text(json.dumps({"score": 12, "subject": job.subject}), encoding="utf-8")
        job.result_pdf_path = str(out_pdf)
        job.result_json_path = str(out_json)
        job_manager._save_job(job)

    monkeypatch.setattr(ocr_route, "process_ocr_job", fake_process)
    return calls


def _wait_for_status(client, job_id, wanted, timeout=15.0):
    deadline = time.monotonic() + timeout
    body = None
    while time.monotonic() < deadline:
        body = client.get(f"/api/ocr/job/{job_id}").json()
        if body.get("status") in wanted:
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached {wanted}; last={body}")


def _submit(client, *, name="answer.pdf", data=PDF, subject="political-science", headers=None, **form):
    return client.post(
        "/api/ocr/submit",
        files={"file": (name, data, "application/pdf")},
        data={"user_id": "user-1", "subject": subject, **form},
        headers=headers or {},
    )


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize("path", ["/api/ocr/submit", "/api/ocr/annotate", "/api/ocr/annotate/json"])
def test_non_pdf_upload_rejected(client, ocr_route, path):
    resp = client.post(
        path,
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"user_id": "u", "subject": "political-science"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Only PDF files are supported."


def test_extension_check_is_case_insensitive(client, ocr_route, fake_grader):
    assert _submit(client, name="ANSWER.PDF").status_code == 200


@pytest.mark.parametrize("path", ["/api/ocr/submit", "/api/ocr/annotate"])
def test_missing_form_fields_are_422(client, ocr_route, path):
    resp = client.post(path, files={"file": ("a.pdf", PDF, "application/pdf")})
    assert resp.status_code == 422
    missing = {tuple(err["loc"]) for err in resp.json()["detail"]}
    assert ("body", "user_id") in missing
    assert ("body", "subject") in missing


def test_missing_file_is_422(client, ocr_route):
    resp = client.post("/api/ocr/submit", data={"user_id": "u", "subject": "x"})
    assert resp.status_code == 422


def test_blank_subject_rejected(client, ocr_route):
    resp = _submit(client, subject="   ")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Subject selection is required."


def test_upload_over_size_limit_is_413(client, ocr_route, monkeypatch):
    monkeypatch.setattr(ocr_route, "MAX_MB", 1)
    resp = _submit(client, data=b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 1))
    assert resp.status_code == 413
    assert "1 MB" in resp.json()["detail"]


# ---------------------------------------------------------------- job lifecycle


def test_unknown_job_is_404_everywhere(client, ocr_route):
    assert client.get("/api/ocr/job/doesnotexist").status_code == 404
    assert client.get("/api/ocr/job/doesnotexist/result").status_code == 404
    assert client.get("/api/ocr/job/doesnotexist").json() == {"error": "Job not found", "job_id": "doesnotexist"}


def test_cancel_unknown_job_is_400(client, ocr_route):
    resp = client.post("/api/ocr/job/nope/cancel")
    assert resp.status_code == 400
    assert resp.json()["job_id"] == "nope"


def test_unknown_progress_is_404(client, ocr_route):
    resp = client.get("/api/ocr/progress/abc123")
    assert resp.status_code == 404
    assert resp.json() == {"error": "Progress not found", "request_id": "abc123"}


def test_submit_complete_and_fetch_result(client, ocr_route, fake_grader):
    resp = _submit(client)
    assert resp.status_code == 200
    body = resp.json()
    # The worker thread shares the job object, so the echoed status is a snapshot.
    assert body["status"] in {"pending", "running", "completed"}
    assert len(body["job_id"]) == 16 and len(body["request_id"]) == 8

    # Input PDF is persisted where the worker expects it, and progress is pollable at once.
    stored = Path(ocr_route._get_logs_dir()) / "results" / f"input_{body['job_id']}.pdf"
    assert stored.read_bytes() == PDF
    progress = client.get(f"/api/ocr/progress/{body['request_id']}")
    assert progress.status_code == 200
    assert progress.json()["step"] == "Job Submitted"

    status = _wait_for_status(client, body["job_id"], {"completed", "failed"})
    assert status["status"] == "completed"
    assert status["result_available"] is True
    assert status["subject"] == "political-science"

    result = client.get(f"/api/ocr/job/{body['job_id']}/result")
    assert result.status_code == 200
    payload = result.json()
    assert payload["metadata"] == {"score": 12, "subject": "political-science"}
    assert payload["filename"] == "answer_annotated.pdf"
    assert payload["pdf_url"] == ""  # storage unavailable -> empty URL, not an error
    assert base64.b64decode(payload["pdf_base64"]).startswith(b"%PDF")


def test_result_includes_signed_url_when_storage_works(client, ocr_route, fake_grader, monkeypatch):
    from backend.db import storage

    uploads = []

    class FakeStorage:
        def upload_pdf_and_get_signed_url(self, *, user_id, original_stem, data):
            uploads.append((user_id, original_stem, data[:4]))
            return "https://storage.example/signed/answer.pdf"

    monkeypatch.setattr(storage, "StorageService", FakeStorage)
    job_id = _submit(client).json()["job_id"]
    _wait_for_status(client, job_id, {"completed"})
    payload = client.get(f"/api/ocr/job/{job_id}/result").json()
    assert payload["pdf_url"] == "https://storage.example/signed/answer.pdf"
    assert uploads == [("user-1", "answer", b"%PDF")]


def test_failed_job_reports_error_and_result_is_400(client, ocr_route, monkeypatch):
    def boom(job, job_manager):
        raise RuntimeError("grok exploded")

    monkeypatch.setattr(ocr_route, "process_ocr_job", boom)
    job_id = _submit(client).json()["job_id"]
    status = _wait_for_status(client, job_id, {"completed", "failed"})
    assert status["status"] == "failed"
    assert status["error"] == "grok exploded"

    resp = client.get(f"/api/ocr/job/{job_id}/result")
    assert resp.status_code == 400
    assert "failed" in resp.json()["error"]


def test_pending_job_can_be_cancelled_once(client, ocr_route):
    job = ocr_route._job_manager.create_job("req00001", "u", "a.pdf", "political-science")
    first = client.post(f"/api/ocr/job/{job.job_id}/cancel")
    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"
    assert client.get(f"/api/ocr/job/{job.job_id}").json()["status"] == "cancelled"
    # already terminal -> cannot cancel again, and the result is not available
    assert client.post(f"/api/ocr/job/{job.job_id}/cancel").status_code == 400
    assert client.get(f"/api/ocr/job/{job.job_id}/result").status_code == 400


def test_completed_job_with_missing_pdf_is_404(client, ocr_route):
    mgr = ocr_route._job_manager
    job = mgr.create_job("req00002", "u", "a.pdf", "s")
    mgr.complete_job(job.job_id)
    resp = client.get(f"/api/ocr/job/{job.job_id}/result")
    assert resp.status_code == 404
    assert resp.json()["error"] == "Result PDF not found"


@pytest.mark.parametrize(
    ("form_brand", "headers", "expected"),
    [
        (None, {}, "rubric"),
        ("lca", {}, "lca"),
        (None, {"Origin": "https://lca-portal.vercel.app"}, "lca"),
        (None, {"Referer": "https://lca-portal.org/evaluate"}, "lca"),
        ("rubric", {"Origin": "https://lca-portal.org"}, "rubric"),  # explicit field wins
    ],
)
def test_submit_resolves_report_brand(client, ocr_route, fake_grader, form_brand, headers, expected):
    form = {"brand": form_brand} if form_brand else {}
    job_id = _submit(client, headers=headers, **form).json()["job_id"]
    _wait_for_status(client, job_id, {"completed"})
    assert ocr_route._job_manager.get_job(job_id).brand == expected


# ---------------------------------------------------------------- synchronous annotate


def test_annotate_returns_pdf_and_metadata(client, ocr_route, monkeypatch):
    seen = {}

    class FakeAnnotator:
        def annotate_pdf(self, *, pdf_bytes, original_filename, subject, user_id):
            seen.update(filename=original_filename, subject=subject, user_id=user_id, size=len(pdf_bytes))
            return b"%PDF-annotated", {"total": 14}, "req12345"

    monkeypatch.setattr(ocr_route, "OCRAnnotator", FakeAnnotator)
    resp = client.post(
        "/api/ocr/annotate",
        files={"file": ("essay.pdf", PDF, "application/pdf")},
        data={"user_id": "u-9", "subject": " political-science "},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert base64.b64decode(body["pdf_base64"]) == b"%PDF-annotated"
    assert body["metadata"] == {"total": 14}
    assert body["request_id"] == "req12345"
    assert body["filename"] == "essay_annotated.pdf"
    assert seen == {"filename": "essay.pdf", "subject": "political-science", "user_id": "u-9", "size": len(PDF)}


def test_annotate_json_merges_metadata(client, ocr_route, monkeypatch):
    class FakeAnnotator:
        def annotate_pdf(self, **kwargs):
            return b"", {"total": 9, "grade": "B"}, "r1"

    monkeypatch.setattr(ocr_route, "OCRAnnotator", FakeAnnotator)
    resp = client.post(
        "/api/ocr/annotate/json",
        files={"file": ("a.pdf", PDF, "application/pdf")},
        data={"subject": "sociology"},
    )
    assert resp.json() == {"ok": True, "total": 9, "grade": "B", "request_id": "r1"}


def test_annotate_pipeline_failure_is_500(client, ocr_route, monkeypatch):
    class Broken:
        def annotate_pdf(self, **kwargs):
            raise ValueError("no pages")

    monkeypatch.setattr(ocr_route, "OCRAnnotator", Broken)
    resp = client.post(
        "/api/ocr/annotate",
        files={"file": ("a.pdf", PDF, "application/pdf")},
        data={"user_id": "u", "subject": "sociology"},
    )
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Evaluation failed: no pages"


# ---------------------------------------------------------------- ocr-regular


def test_regular_non_pdf_rejected(client):
    resp = client.post(
        "/api/ocr-regular/annotate",
        files={"file": ("a.docx", b"x", "application/octet-stream")},
        data={"user_id": "u", "subject": "s"},
    )
    assert resp.status_code == 400


def test_regular_annotate_json_uses_regular_service(client, monkeypatch):
    from backend.api.routes import ocr_regular

    class FakeRegular:
        def annotate_pdf(self, **kwargs):
            return b"", {"total": 3}, "rq"

    monkeypatch.setattr(ocr_regular, "OCRAnnotatorRegular", FakeRegular)
    resp = client.post(
        "/api/ocr-regular/annotate/json",
        files={"file": ("a.pdf", PDF, "application/pdf")},
        data={"subject": "sociology"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["total"] == 3 and body["request_id"] == "rq"
    assert "testing purposes" in body["note"]
