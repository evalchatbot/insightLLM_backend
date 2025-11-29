# This file is now disabled. All previous OCR API routes are removed.
# The new OCR pipeline is now used instead.

from __future__ import annotations

import base64
import os
from typing import Dict, Any

from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import JSONResponse
from supabase import create_client

from backend.ocr.service import OCRAnnotator, get_all_available_subjects
from backend.config import SUPABASE_URL, SUPABASE_KEY

router = APIRouter(prefix="/api/ocr", tags=["ocr"])

MAX_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))


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

    # Check usage limits BEFORE starting expensive OCR processing
    # Estimate: OCR typically uses ~200k input + 5k output tokens
    estimated_input = 200000
    estimated_output = 5000
    
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Look up user's UUID from users table by id (Clerk user_id stored as id)
        user_result = supabase.table('users').select('id').eq('id', user_id).single().execute()
        
        if not user_result.data or not user_result.data.get('id'):
            raise HTTPException(status_code=404, detail="User not found in database")
        
        actual_uuid = user_result.data['id']
        
        # Check if user can proceed with estimated token usage
        limit_check = supabase.rpc(
            'check_usage_limit',
            {
                'p_user_id': actual_uuid,
                'p_input_tokens': estimated_input,
                'p_output_tokens': estimated_output
            }
        ).execute()
        
        if limit_check.data:
            # If can_proceed is False, block the request
            if not limit_check.data.get('can_proceed', True):
                raise HTTPException(
                    status_code=429,
                    detail=limit_check.data.get('message', 'Monthly token limit exceeded')
                )
    except HTTPException:
        raise
    except Exception as e:
        # Log but don't block on limit check errors
        print(f"Warning: Failed to check usage limit: {e}")

    try:
        annotator = OCRAnnotator()
        annotated_bytes, meta = annotator.annotate_pdf(
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
        _, meta = annotator.annotate_pdf(
            pdf_bytes=data,
            original_filename=file.filename,
            subject=subject,
            user_id=user_id,
        )
        return {"ok": True, **meta}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {exc}") from exc


@router.get("/subjects")
async def get_subjects() -> Dict[str, Any]:
    subjects = get_all_available_subjects()
    return {"subjects": subjects, "count": len(subjects)}
