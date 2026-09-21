"""OCRJobManager lifecycle (file-backed jobs + worker threads) and OCRProgressTracker."""

from __future__ import annotations

import json
import os
import threading
import time

import pytest

from backend.ocr.job_manager import JobStatus, OCRJob
from backend.ocr.progress_tracker import OCRProgressTracker

pytestmark = pytest.mark.unit


def wait_until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


def run_to_end(mgr, job, fn):
    """submit_job() and join the worker thread it starts."""
    before = set(threading.enumerate())
    mgr.submit_job(job, fn)
    for worker in set(threading.enumerate()) - before:
        worker.join(10)
        assert not worker.is_alive()


@pytest.fixture
def mgr(job_manager_factory):
    return job_manager_factory("unit")


# ---------------------------------------------------------------- persistence


def test_create_job_persists_pending_job(mgr):
    job = mgr.create_job("req1", "user-1", "answer.pdf", "sociology", brand="lca")
    assert len(job.job_id) == 16
    assert job.status is JobStatus.PENDING
    on_disk = json.loads(mgr._get_job_file_path(job.job_id).read_text(encoding="utf-8"))
    assert on_disk["status"] == "pending"
    assert on_disk["brand"] == "lca"
    loaded = mgr.get_job(job.job_id)
    assert isinstance(loaded, OCRJob)
    assert loaded == job


def test_job_ids_are_unique(mgr):
    ids = {mgr.create_job("r", None, "a.pdf", "s").job_id for _ in range(50)}
    assert len(ids) == 50


def test_unknown_or_corrupt_job_is_none(mgr):
    assert mgr.get_job("missing") is None
    mgr._get_job_file_path("broken").write_text("{not json", encoding="utf-8")
    assert mgr.get_job("broken") is None


def test_result_paths_live_in_results_dir(mgr):
    assert mgr._get_result_pdf_path("abc").name == "result_abc.pdf"
    assert mgr._get_result_json_path("abc").parent == mgr.results_dir


# ---------------------------------------------------------------- worker lifecycle


def test_successful_job_completes(mgr):
    job = mgr.create_job("r", "u", "a.pdf", "s")
    seen = []
    run_to_end(mgr, job, lambda j: seen.append((j.job_id, j.status)))
    stored = mgr.get_job(job.job_id)
    assert seen == [(job.job_id, JobStatus.RUNNING)]
    assert stored.status is JobStatus.COMPLETED
    assert stored.started_at <= stored.completed_at
    assert stored.error is None
    assert not mgr.is_job_cancelled(job.job_id)


def test_failing_job_records_error(mgr):
    job = mgr.create_job("r", "u", "a.pdf", "s")

    def boom(_):
        raise ValueError("azure OCR quota exceeded")

    run_to_end(mgr, job, boom)
    stored = mgr.get_job(job.job_id)
    assert stored.status is JobStatus.FAILED
    assert stored.error == "azure OCR quota exceeded"


def test_cancel_while_running(mgr):
    job = mgr.create_job("r", "u", "a.pdf", "s")
    started, release = threading.Event(), threading.Event()
    observed = {}

    def slow(j):
        started.set()
        assert release.wait(5)
        observed["flag"] = mgr.is_job_cancelled(j.job_id)

    mgr.submit_job(job, slow)
    assert started.wait(5)
    wait_until(lambda: job.job_id in mgr._active_jobs)
    assert mgr.cancel_job(job.job_id) is True
    assert mgr.get_job(job.job_id).status is JobStatus.CANCELLED
    release.set()
    wait_until(lambda: job.job_id not in mgr._active_jobs)
    stored = mgr.get_job(job.job_id)
    assert observed["flag"] is True
    assert stored.status is JobStatus.CANCELLED
    assert job.job_id not in mgr._job_cancellation_flags  # cleaned up


@pytest.mark.xfail(
    strict=True,
    reason="BUG: OCRJobManager.submit_job's worker resets _job_cancellation_flags[job_id]=False on start, "
    "so a cancel that lands before the thread runs is lost and the job runs to COMPLETED",
)
def test_cancel_before_worker_starts_is_honoured(mgr):
    job = mgr.create_job("r", "u", "a.pdf", "s")
    assert mgr.cancel_job(job.job_id) is True
    ran = threading.Event()
    run_to_end(mgr, job, lambda j: ran.set())
    assert not ran.is_set()
    assert mgr.get_job(job.job_id).status is JobStatus.CANCELLED


@pytest.mark.parametrize("status", [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED])
def test_terminal_jobs_cannot_be_cancelled(mgr, status):
    job = mgr.create_job("r", "u", "a.pdf", "s")
    mgr.update_job_status(job.job_id, status)
    assert mgr.cancel_job(job.job_id) is False
    assert mgr.get_job(job.job_id).status is status


def test_cancel_unknown_job(mgr):
    assert mgr.cancel_job("nope") is False


# ---------------------------------------------------------------- external runners


def test_external_runner_transitions(mgr):
    job = mgr.create_job("r", "u", "a.pdf", "s")
    mgr.update_job_status(job.job_id, JobStatus.RUNNING, started_at=123.0)
    assert mgr.get_job(job.job_id).status is JobStatus.RUNNING
    assert mgr.get_job(job.job_id).started_at == 123.0
    mgr.fail_job(job.job_id, "boom")
    failed = mgr.get_job(job.job_id)
    assert failed.status is JobStatus.FAILED and failed.error == "boom" and failed.completed_at
    mgr.complete_job(job.job_id)
    assert mgr.get_job(job.job_id).status is JobStatus.COMPLETED


def test_external_runner_calls_ignore_unknown_jobs(mgr):
    mgr.update_job_status("ghost", JobStatus.RUNNING)
    mgr.complete_job("ghost")
    mgr.fail_job("ghost", "x")
    assert list(mgr.jobs_dir.iterdir()) == []


# ---------------------------------------------------------------- cleanup


def test_cleanup_removes_only_old_finished_jobs_and_their_results(mgr):
    old = mgr.create_job("r", "u", "old.pdf", "s")
    pdf, js = mgr._get_result_pdf_path(old.job_id), mgr._get_result_json_path(old.job_id)
    pdf.write_bytes(b"%PDF")
    js.write_text("{}")
    old.status, old.completed_at = JobStatus.COMPLETED, time.time() - 2 * 86400
    old.result_pdf_path, old.result_json_path = str(pdf), str(js)
    mgr._save_job(old)

    recent = mgr.create_job("r", "u", "new.pdf", "s")
    mgr.complete_job(recent.job_id)
    pending = mgr.create_job("r", "u", "pending.pdf", "s")

    mgr.cleanup_old_jobs(max_age_seconds=86400)
    assert mgr.get_job(old.job_id) is None
    assert not pdf.exists() and not js.exists()
    assert mgr.get_job(recent.job_id) is not None
    assert mgr.get_job(pending.job_id) is not None


# ---------------------------------------------------------------- progress tracker


def test_progress_roundtrip(tmp_path):
    tracker = OCRProgressTracker(logs_dir=str(tmp_path / "logs"))
    tracker.update_progress("req9", "OCR", 2, 11, 18.18181, message="Reading page 2")
    got = tracker.get_progress("req9")
    assert got["progress_percent"] == 18.18
    assert got["step_number"] == 2 and got["total_steps"] == 11
    assert got["details"] == {}
    assert got["updated_at"].endswith("Z")
    tracker.update_progress("req9", "Grading", 5, 11, 50.0, details={"pages_completed": 3})
    assert tracker.get_progress("req9")["details"] == {"pages_completed": 3}
    tracker.clear_progress("req9")
    assert tracker.get_progress("req9") is None
    tracker.clear_progress("req9")  # idempotent


def test_progress_corrupt_file_reads_as_missing(tmp_path):
    tracker = OCRProgressTracker(logs_dir=str(tmp_path))
    (tmp_path / "progress_bad.json").write_text("{", encoding="utf-8")
    assert tracker.get_progress("bad") is None


def test_progress_cleanup_by_age(tmp_path):
    tracker = OCRProgressTracker(logs_dir=str(tmp_path))
    tracker.update_progress("old", "s", 1, 1, 100)
    tracker.update_progress("new", "s", 1, 1, 100)
    stale = time.time() - 7200
    os.utime(tmp_path / "progress_old.json", (stale, stale))
    tracker.cleanup_old_progress(max_age_seconds=3600)
    assert tracker.get_progress("old") is None
    assert tracker.get_progress("new") is not None
