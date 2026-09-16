"""
Background job runner for the Psychological Assessment pipeline.

Mirrors backend/ocr/service.py's process_ocr_job but calls the dedicated
grade_psych_assessment orchestrator. Results are written under
logs/psych_results so they never mix with the generic OCR results.
"""

from __future__ import annotations

import os
from typing import Optional

from backend.ocr.job_manager import OCRJob, OCRJobManager
from backend.ocr.progress_tracker import OCRProgressTracker
from backend.psych.grade_psych_assessment import grade_psych_assessment

TOTAL_STEPS = 14


class _TrackerAdapter:
    """Adapts OCRProgressTracker to the orchestrator's `.update(step, label)` interface."""

    def __init__(self, tracker: OCRProgressTracker, request_id: str):
        self._t = tracker
        self._rid = request_id

    def update(self, step: int, label: str) -> None:
        try:
            self._t.update_progress(
                request_id=self._rid,
                step=label,
                step_number=int(step),
                total_steps=TOTAL_STEPS,
                progress_percent=min(99.0, (int(step) / TOTAL_STEPS) * 100.0),
                message=label,
            )
        except Exception:
            pass


def process_psych_job(job: OCRJob, job_manager: OCRJobManager, logs_dir: str, input_pdf_path: str) -> None:
    """Run the psychological-assessment evaluation for a submitted job."""
    results_dir = os.path.join(logs_dir, "psych_results")
    os.makedirs(results_dir, exist_ok=True)
    out_pdf = os.path.abspath(os.path.join(results_dir, f"result_{job.job_id}.pdf"))
    out_json = os.path.abspath(os.path.join(results_dir, f"result_{job.job_id}.json"))
    log_path = os.path.join(logs_dir, f"psych_{job.request_id}.log")

    tracker = OCRProgressTracker(logs_dir=logs_dir)
    adapter = _TrackerAdapter(tracker, job.request_id)

    grade_psych_assessment(
        pdf_path=input_pdf_path,
        output_pdf_path=out_pdf,
        output_json_path=out_json,
        log_path=log_path,
        request_id=job.request_id,
        progress_tracker=adapter,
    )

    # Record result paths on the job; the job manager persists them on completion.
    job.result_pdf_path = out_pdf
    job.result_json_path = out_json
    try:
        job_manager._save_job(job)  # persist paths immediately too
    except Exception:
        pass

    try:
        tracker.update_progress(
            request_id=job.request_id,
            step="Complete",
            step_number=TOTAL_STEPS,
            total_steps=TOTAL_STEPS,
            progress_percent=100.0,
            message="Report ready",
        )
    except Exception:
        pass
