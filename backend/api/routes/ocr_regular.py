"""
Temporary OCR endpoints using regular (non-backend) files.
These endpoints are for testing purposes only.

Use these endpoints to test the regular files:
- /api/ocr-regular/annotate
- /api/ocr-regular/annotate/json
- /api/ocr-regular/subjects
"""

from __future__ import annotations

import base64
import json
import os
from typing import Dict, Any

from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import JSONResponse

import time
import logging

# Import regular service
from backend.ocr.service_regular import OCRAnnotatorRegular, get_all_available_subjects

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ocr-regular", tags=["ocr-regular"])

MAX_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))


def _ensure_pdf(file: UploadFile, data: bytes) -> None:
    """Validate PDF file."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File size exceeds {MAX_MB} MB.")


@router.post("/annotate")
async def annotate_pdf_regular(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    subject: str = Form(...),
) -> JSONResponse:
    """
    Annotate PDF using regular (non-backend) files.
    
    This endpoint uses the regular grade_pdf_answer.py and annotate_pdf_with_rubric.py
    files instead of the backend versions. Use this for testing purposes.
    
    **Note**: This endpoint does NOT support:
    - Progress tracking
    - Background job processing
    - Advanced error recovery
    - Memory management
    
    For production use, use /api/ocr/annotate instead.
    """
    data = await file.read()
    _ensure_pdf(file, data)

    subject = (subject or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject selection is required.")

    try:
        annotator = OCRAnnotatorRegular()
        annotated_bytes, meta, request_id = annotator.annotate_pdf(
            pdf_bytes=data,
            original_filename=file.filename,
            subject=subject,
            user_id=user_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Regular OCR evaluation failed: {exc}", exc_info=True)
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
        "request_id": request_id,
        "note": "This endpoint uses regular files (not backend files) for testing purposes.",
    }
    return JSONResponse(content=payload)


@router.post("/annotate/json")
async def annotate_pdf_json_regular(
    file: UploadFile = File(...),
    subject: str = Form(...),
    user_id: str = Form(None),
) -> Dict[str, Any]:
    """
    Get evaluation results as JSON only (no PDF) using regular files.
    
    This endpoint uses the regular grade_pdf_answer.py file.
    Use this for testing purposes only.
    """
    data = await file.read()
    _ensure_pdf(file, data)

    subject = (subject or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject selection is required.")

    try:
        annotator = OCRAnnotatorRegular()
        _, meta, request_id = annotator.annotate_pdf(
            pdf_bytes=data,
            original_filename=file.filename,
            subject=subject,
            user_id=user_id,
        )
        return {
            "ok": True,
            **meta,
            "request_id": request_id,
            "note": "This endpoint uses regular files (not backend files) for testing purposes.",
        }
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Regular OCR evaluation failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {exc}") from exc


@router.get("/subjects")
async def get_subjects_regular() -> Dict[str, Any]:
    """
    Get available subjects using regular file logic.
    
    Returns list of subjects from the rubric directory.
    """
    start = time.perf_counter()
    try:
        subjects = get_all_available_subjects()
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info("[OCR-Regular] /subjects returned %d items in %d ms", len(subjects), duration_ms)
        return {
            "subjects": subjects,
            "count": len(subjects),
            "latency_ms": duration_ms,
            "note": "This endpoint uses regular files (not backend files) for testing purposes.",
        }
    except Exception as exc:  # noqa: BLE001
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.error("[OCR-Regular] /subjects failed after %d ms: %s", duration_ms, exc)
        raise

