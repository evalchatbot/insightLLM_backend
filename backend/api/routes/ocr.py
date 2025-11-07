from __future__ import annotations

import base64
import os
from typing import Dict, Any

from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import JSONResponse

from backend.ocr.service import OCRAnnotator, get_all_available_subjects

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

    try:
        annotator = OCRAnnotator()
        annotated_bytes, meta = annotator.annotate_pdf(
            pdf_bytes=data,
            original_filename=file.filename,
            subject=subject,
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
        )
        return {"ok": True, **meta}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {exc}") from exc


@router.get("/subjects")
async def get_subjects() -> Dict[str, Any]:
    subjects = get_all_available_subjects()
    return {"subjects": subjects, "count": len(subjects)}
