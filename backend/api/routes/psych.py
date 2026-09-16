"""
API routes for the Psychological Assessment evaluation (its own top-level flow).

Mirrors the OCR async job contract so the frontend can reuse the same
submit -> poll -> result pattern, but the subject is fixed and results live
under logs/psych_results.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse

from backend.ocr.job_manager import OCRJobManager, OCRJob, JobStatus
from backend.ocr.progress_tracker import OCRProgressTracker
from backend.psych.service import process_psych_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/psych", tags=["psych"])

MAX_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
SUBJECT = "Psychological Assessment"

_job_manager: Optional[OCRJobManager] = None


def _get_logs_dir() -> str:
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_file_dir, "..", "..", ".."))
    return os.path.abspath(os.path.join(project_root, "logs"))


def get_job_manager() -> OCRJobManager:
    global _job_manager
    if _job_manager is None:
        logs_dir = _get_logs_dir()
        _job_manager = OCRJobManager(
            jobs_dir=os.path.join(logs_dir, "psych_jobs"),
            results_dir=os.path.join(logs_dir, "psych_results"),
        )
    return _job_manager


def _ensure_pdf(file: UploadFile, data: bytes) -> None:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File size exceeds {MAX_MB} MB.")


@router.post("/submit")
async def submit_job(
    file: UploadFile = File(...),
    user_id: str = Form(...),
) -> JSONResponse:
    """Submit a Psychological Assessment PDF for background evaluation."""
    data = await file.read()
    _ensure_pdf(file, data)

    request_id = uuid.uuid4().hex[:8]
    job_manager = get_job_manager()
    job = job_manager.create_job(
        request_id=request_id,
        user_id=user_id,
        filename=file.filename,
        subject=SUBJECT,
    )

    logs_dir = _get_logs_dir()
    inputs_dir = os.path.join(logs_dir, "psych_results")
    os.makedirs(inputs_dir, exist_ok=True)
    input_pdf_path = os.path.abspath(os.path.join(inputs_dir, f"input_{job.job_id}.pdf"))
    try:
        with open(input_pdf_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if not os.path.exists(input_pdf_path) or os.path.getsize(input_pdf_path) != len(data):
            raise HTTPException(status_code=500, detail="Failed to save input PDF.")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to save input PDF: {e}")

    tracker = OCRProgressTracker(logs_dir=logs_dir)
    tracker.update_progress(
        request_id=request_id, step="Job Submitted", step_number=0, total_steps=14,
        progress_percent=0.0, message="Job submitted. Starting evaluation...",
    )

    def process_job(j: OCRJob) -> None:
        process_psych_job(j, job_manager, logs_dir, input_pdf_path)

    job_manager.submit_job(job, process_job)

    return JSONResponse(content={
        "job_id": job.job_id,
        "request_id": job.request_id,
        "status": job.status.value,
        "message": "Job submitted. Use /api/psych/job/{job_id} to check status.",
    })


@router.get("/job/{job_id}")
async def get_job_status(job_id: str) -> JSONResponse:
    job = get_job_manager().get_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "Job not found", "job_id": job_id})
    response = {
        "job_id": job.job_id,
        "request_id": job.request_id,
        "status": job.status.value,
        "filename": job.filename,
        "subject": job.subject,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }
    if job.error:
        response["error"] = job.error
    if job.status == JobStatus.COMPLETED:
        response["result_available"] = True
    return JSONResponse(content=response)


@router.get("/job/{job_id}/result")
async def get_job_result(job_id: str) -> JSONResponse:
    job = get_job_manager().get_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "Job not found", "job_id": job_id})
    if job.status != JobStatus.COMPLETED:
        return JSONResponse(status_code=400, content={"error": f"Job not completed (status: {job.status.value})"})
    if not job.result_pdf_path or not os.path.exists(job.result_pdf_path):
        return JSONResponse(status_code=404, content={"error": "Result PDF not found", "job_id": job_id})

    with open(job.result_pdf_path, "rb") as f:
        pdf_bytes = f.read()
    metadata = {}
    if job.result_json_path and os.path.exists(job.result_json_path):
        try:
            with open(job.result_json_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception:
            metadata = {}

    encoded = base64.b64encode(pdf_bytes).decode("utf-8")
    return JSONResponse(content={
        "job_id": job.job_id,
        "request_id": job.request_id,
        "pdf_base64": encoded,
        "metadata": metadata,
        "filename": f"{os.path.splitext(job.filename)[0]}_psych_report.pdf",
    })


@router.get("/progress/{request_id}")
async def get_progress(request_id: str) -> JSONResponse:
    tracker = OCRProgressTracker(logs_dir=_get_logs_dir())
    progress = tracker.get_progress(request_id)
    if progress is None:
        return JSONResponse(status_code=404, content={"error": "Progress not found", "request_id": request_id})
    return JSONResponse(content=progress)
