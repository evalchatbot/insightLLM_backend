"""The background worker behind /api/ocr/submit (process_ocr_job) with the grader mocked."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from backend.ocr import service
from backend.utils.report_cover import current_report_brand
from support.pdfs import text_pdf

pytestmark = pytest.mark.unit

INPUT = text_pdf(["student answer"])


@pytest.fixture
def env(monkeypatch, tmp_path, job_manager_factory):
    logs = tmp_path / "logs"
    (logs / "results").mkdir(parents=True)
    scratch = tmp_path / "tmpfiles"
    scratch.mkdir()
    monkeypatch.setattr(service, "_get_logs_dir", lambda: str(logs))
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))  # NamedTemporaryFile lands here

    mgr = job_manager_factory("svc")
    job = mgr.create_job("req00042", "user-7", "answer.pdf", "political-science", brand="lca")
    (logs / "results" / f"input_{job.job_id}.pdf").write_bytes(INPUT)

    calls = []

    def fake_grader(**kwargs):
        calls.append({**kwargs, "input": open(kwargs["pdf_path"], "rb").read(), "brand": current_report_brand()})
        with open(kwargs["output_pdf_path"], "wb") as fh:
            fh.write(text_pdf(["annotated"]))
        with open(kwargs["output_json_path"], "w", encoding="utf-8") as fh:
            json.dump({"total": 13}, fh)

    monkeypatch.setattr(service, "grade_pdf_answer", fake_grader)
    return type("Env", (), {"logs": logs, "scratch": scratch, "mgr": mgr, "job": job, "calls": calls})


def test_successful_job_moves_results_and_records_paths(env):
    service.process_ocr_job(env.job, env.mgr)

    (call,) = env.calls
    assert call["input"] == INPUT
    assert call["subject"] == "political-science"
    assert call["user_id"] == "user-7"
    assert call["request_id"] == "req00042"
    assert call["brand"] == "lca"  # brand set on the worker thread for the cover page
    assert current_report_brand() == "rubric"  # ...and reset afterwards

    results = env.logs / "results"
    assert (results / f"result_{env.job.job_id}.pdf").read_bytes().startswith(b"%PDF")
    assert json.loads((results / f"result_{env.job.job_id}.json").read_text()) == {"total": 13}
    stored = env.mgr.get_job(env.job.job_id)
    assert stored.result_pdf_path == str(results / f"result_{env.job.job_id}.pdf")
    assert stored.result_json_path == str(results / f"result_{env.job.job_id}.json")

    log = (env.logs / "log.txt").read_text(encoding="utf-8")
    assert "job_complete" in log
    assert "job_start" in log
    assert list(env.scratch.iterdir()) == []  # temp copies cleaned / moved


def test_cancelled_job_is_not_graded(env):
    env.mgr._job_cancellation_flags[env.job.job_id] = True
    service.process_ocr_job(env.job, env.mgr)
    assert env.calls == []


def test_missing_input_pdf_fails_after_retries(env, monkeypatch):
    os.remove(env.logs / "results" / f"input_{env.job.job_id}.pdf")
    naps = []
    monkeypatch.setattr(service.time, "sleep", lambda s: naps.append(s))
    with pytest.raises(FileNotFoundError, match="Input PDF not found"):
        service.process_ocr_job(env.job, env.mgr)
    assert naps == [0.2] * 4
    assert "input_pdf_not_found_after_retries" in (env.logs / "errors_log.txt").read_text(encoding="utf-8")
    assert env.calls == []


def test_missing_results_dir_fails_fast(env):
    import shutil

    shutil.rmtree(env.logs / "results")
    with pytest.raises(FileNotFoundError, match="Results directory not found"):
        service.process_ocr_job(env.job, env.mgr)


@pytest.mark.xfail(
    strict=True,
    reason="BUG: process_ocr_job only deletes the temp *input* copy in `finally`; the two NamedTemporaryFile "
    "outputs (delete=False) leak in the system temp dir every time grading fails",
)
def test_failed_job_leaves_no_temp_files(env, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("grok 500")

    monkeypatch.setattr(service, "grade_pdf_answer", boom)
    with pytest.raises(RuntimeError):
        service.process_ocr_job(env.job, env.mgr)
    assert list(env.scratch.iterdir()) == []


def test_subjects_come_from_rubric_loader():
    subjects = service.get_all_available_subjects()
    assert subjects and {"id", "display_name"} <= set(subjects[0])


def test_append_log_routes_lines_by_kind(tmp_path):
    log = tmp_path / "log.txt"
    service._append_log(str(log), "INFO", "request=r1 upload_start filename=a.pdf")
    service._append_log(str(log), "INFO", "unrelated housekeeping")
    service._append_log(str(log), "ERROR", "request=r1 job_failed error=x")
    assert len(log.read_text(encoding="utf-8").splitlines()) == 3
    assert (tmp_path / "ocr_log.txt").read_text(encoding="utf-8").count("\n") == 1
    assert "job_failed" in (tmp_path / "errors_log.txt").read_text(encoding="utf-8")
    service._append_log(str(tmp_path / "missing" / "log.txt"), "INFO", "never raises")
