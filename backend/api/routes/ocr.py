# This file is now disabled. All previous OCR API routes are removed.
# The new OCR pipeline is now used instead.

from __future__ import annotations

import base64
import json
import os
from typing import Dict, Any, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import JSONResponse
from supabase import create_client

from backend.ocr.service import OCRAnnotator, get_all_available_subjects, process_ocr_job
from backend.ocr.progress_tracker import OCRProgressTracker
from backend.ocr.job_manager import OCRJobManager, JobStatus
from backend.config import SUPABASE_URL, SUPABASE_KEY

router = APIRouter(prefix="/api/ocr", tags=["ocr"])

MAX_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))

# Initialize job manager (singleton)
_job_manager: Optional[OCRJobManager] = None

def get_job_manager() -> OCRJobManager:
    """Get or create job manager instance."""
    global _job_manager
    if _job_manager is None:
        _job_manager = OCRJobManager()
    return _job_manager


def _get_logs_dir() -> str:
    """
    Get the logs directory path consistently.
    This ensures both routes/ocr.py and service.py use the same path.
    """
    # Calculate from this file: backend/api/routes/ocr.py
    # Go up 3 levels: routes -> api -> backend -> project root
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_file_dir, "..", "..", ".."))
    logs_dir = os.path.join(project_root, "logs")
    return os.path.abspath(logs_dir)


def _ensure_pdf(file: UploadFile, data: bytes) -> None:
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File size exceeds {MAX_MB} MB.")


@router.post("/annotate")
async def annotate_pdf(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    subject: str = Form(...),
) -> JSONResponse:
    data = await file.read()
    _ensure_pdf(file, data)

    subject = (subject or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject selection is required.")

    # Note: OCR limit checking is now handled by the frontend API route /api/ocr/check-limit
    # This prevents double-checking and ensures consistent count-based tracking
    # The frontend checks BEFORE calling this endpoint, and records AFTER successful completion

    try:
        annotator = OCRAnnotator()
        annotated_bytes, meta, request_id = annotator.annotate_pdf(
            pdf_bytes=data,
            original_filename=file.filename,
            subject=subject,
            user_id=user_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {exc}") from exc

    pdf_url = ""
    try:
        from backend.db.storage import StorageService

        storage = StorageService()
        pdf_url = storage.upload_pdf_and_get_signed_url(
            user_id=user_id,
            original_stem=os.path.splitext(file.filename)[0],
            data=annotated_bytes,
        )
    except Exception:
        pdf_url = ""

    encoded = base64.b64encode(annotated_bytes).decode("utf-8")
    payload: Dict[str, Any] = {
        "pdf_base64": encoded,
        "pdf_url": pdf_url,
        "metadata": meta,
        "filename": f"{os.path.splitext(file.filename)[0]}_annotated.pdf",
        "request_id": request_id,  # Include request_id for progress polling
    }
    return JSONResponse(content=payload)


@router.post("/annotate/json")
async def annotate_pdf_json(
    file: UploadFile = File(...),
    subject: str = Form(...),
    user_id: str = Form(None),
) -> Dict[str, Any]:
    data = await file.read()
    _ensure_pdf(file, data)

    subject = (subject or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject selection is required.")

    try:
        annotator = OCRAnnotator()
        _, meta, request_id = annotator.annotate_pdf(
            pdf_bytes=data,
            original_filename=file.filename,
            subject=subject,
            user_id=user_id,
        )
        return {"ok": True, **meta, "request_id": request_id}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {exc}") from exc


@router.get("/subjects")
async def get_subjects() -> Dict[str, Any]:
    subjects = get_all_available_subjects()
    return {"subjects": subjects, "count": len(subjects)}


@router.get("/progress/{request_id}")
async def get_progress(request_id: str) -> JSONResponse:
    """
    Get progress for an OCR processing request.
    
    Args:
        request_id: Unique request identifier
    
    Returns:
        JSON response with progress data or 404 if not found
    """
    # Use the same helper function to ensure consistent path calculation
    logs_dir = _get_logs_dir()
    progress_tracker = OCRProgressTracker(logs_dir=logs_dir)
    progress = progress_tracker.get_progress(request_id)
    
    if progress is None:
        return JSONResponse(
            status_code=404,
            content={"error": "Progress not found", "request_id": request_id}
        )
    
    return JSONResponse(content=progress)


@router.post("/submit")
async def submit_job(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    subject: str = Form(...),
) -> JSONResponse:
    """
    Submit an OCR job for background processing.
    
    Returns job ID immediately, processing happens in background.
    """
    data = await file.read()
    _ensure_pdf(file, data)
    
    subject = (subject or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject selection is required.")
    
    # Note: OCR limit checking should be done before calling this endpoint
    
    import uuid
    import time
    request_id = uuid.uuid4().hex[:8]
    
    # Get job manager
    job_manager = get_job_manager()
    
    # Create job
    job = job_manager.create_job(
        request_id=request_id,
        user_id=user_id,
        filename=file.filename,
        subject=subject,
    )
    
    # Store input PDF in results directory
    # Use helper function to ensure consistent path calculation
    logs_dir = _get_logs_dir()
    results_dir = os.path.join(logs_dir, "results")
    os.makedirs(results_dir, exist_ok=True)
    input_pdf_path = os.path.abspath(os.path.join(results_dir, f"input_{job.job_id}.pdf"))
    
    # Log the paths being used for debugging
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Job {job.job_id}: Writing input PDF to {input_pdf_path}")
    logger.info(f"Job {job.job_id}: Logs dir = {logs_dir}, Results dir = {results_dir}")
    
    # Write file and ensure it's flushed and closed before continuing
    try:
        with open(input_pdf_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())  # Force write to disk
        
        # Verify file exists and has correct size
        if not os.path.exists(input_pdf_path):
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save input PDF for job {job.job_id}: File does not exist after write"
            )
        
        # Verify file size matches
        file_size = os.path.getsize(input_pdf_path)
        if file_size != len(data):
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save input PDF for job {job.job_id}: File size mismatch (expected {len(data)}, got {file_size})"
            )
        
        # Log successful write
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Successfully saved input PDF for job {job.job_id} at {input_pdf_path} ({file_size} bytes)")
        
    except OSError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save input PDF for job {job.job_id}: {str(e)}"
        )
    
    # Initialize progress tracker immediately (before background processing starts)
    # This ensures progress is available for polling right away
    from backend.ocr.progress_tracker import OCRProgressTracker
    progress_tracker = OCRProgressTracker(logs_dir=logs_dir)
    progress_tracker.update_progress(
        request_id=request_id,
        step="Job Submitted",
        step_number=0,
        total_steps=11,
        progress_percent=0.0,
        message="Job submitted successfully. Starting processing...",
    )
    
    # Verify progress file was created (for debugging)
    progress_file_path = os.path.join(logs_dir, f"progress_{request_id}.json")
    if not os.path.exists(progress_file_path):
        logger.warning(f"Job {job.job_id}: Progress file not created at {progress_file_path}")
    else:
        logger.info(f"Job {job.job_id}: Progress file created at {progress_file_path}")
    
    # Submit job for background processing
    # No delay needed - file is already flushed and synced
    
    def process_job(job: OCRJob) -> None:
        process_ocr_job(job, job_manager)
    
    job_manager.submit_job(job, process_job)
    
    return JSONResponse(content={
        "job_id": job.job_id,
        "request_id": job.request_id,
        "status": job.status.value,
        "message": "Job submitted successfully. Use /api/ocr/job/{job_id} to check status.",
    })


@router.get("/job/{job_id}")
async def get_job_status(job_id: str) -> JSONResponse:
    """
    Get status of an OCR job.
    
    Args:
        job_id: Job identifier
    
    Returns:
        JSON response with job status
    """
    job_manager = get_job_manager()
    job = job_manager.get_job(job_id)
    
    if not job:
        return JSONResponse(
            status_code=404,
            content={"error": "Job not found", "job_id": job_id}
        )
    
    # Build response
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
        response["result_pdf_path"] = job.result_pdf_path
        response["result_json_path"] = job.result_json_path
    
    return JSONResponse(content=response)


@router.post("/job/{job_id}/cancel")
async def cancel_job(job_id: str) -> JSONResponse:
    """
    Cancel a running OCR job.
    
    Args:
        job_id: Job identifier
    
    Returns:
        JSON response indicating success or failure
    """
    job_manager = get_job_manager()
    cancelled = job_manager.cancel_job(job_id)
    
    if not cancelled:
        return JSONResponse(
            status_code=400,
            content={"error": "Job cannot be cancelled (not found or already completed)", "job_id": job_id}
        )
    
    return JSONResponse(content={
        "job_id": job_id,
        "status": "cancelled",
        "message": "Job cancelled successfully",
    })


@router.get("/job/{job_id}/result")
async def get_job_result(job_id: str) -> JSONResponse:
    """
    Get result of a completed OCR job.
    
    Args:
        job_id: Job identifier
    
    Returns:
        JSON response with PDF base64 and metadata, or error if not completed
    """
    job_manager = get_job_manager()
    job = job_manager.get_job(job_id)
    
    if not job:
        return JSONResponse(
            status_code=404,
            content={"error": "Job not found", "job_id": job_id}
        )
    
    if job.status != JobStatus.COMPLETED:
        return JSONResponse(
            status_code=400,
            content={"error": f"Job not completed (status: {job.status.value})", "job_id": job_id}
        )
    
    # Read result PDF
    if not job.result_pdf_path or not os.path.exists(job.result_pdf_path):
        return JSONResponse(
            status_code=404,
            content={"error": "Result PDF not found", "job_id": job_id}
        )
    
    with open(job.result_pdf_path, "rb") as f:
        pdf_bytes = f.read()
    
    # Read metadata
    metadata = {}
    if job.result_json_path and os.path.exists(job.result_json_path):
        with open(job.result_json_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    
    # Upload to storage (optional)
    pdf_url = ""
    try:
        from backend.db.storage import StorageService
        storage = StorageService()
        pdf_url = storage.upload_pdf_and_get_signed_url(
            user_id=job.user_id or "",
            original_stem=os.path.splitext(job.filename)[0],
            data=pdf_bytes,
        )
    except Exception:
        pdf_url = ""
    
    encoded = base64.b64encode(pdf_bytes).decode("utf-8")
    return JSONResponse(content={
        "job_id": job.job_id,
        "request_id": job.request_id,
        "pdf_base64": encoded,
        "pdf_url": pdf_url,
        "metadata": metadata,
        "filename": f"{os.path.splitext(job.filename)[0]}_annotated.pdf",
    })
