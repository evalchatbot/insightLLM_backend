from __future__ import annotations
import os
from fastapi import APIRouter, UploadFile, File, HTTPException, Response, status, Query, Form
from backend.ocr.service import OCRAnnotator
from backend.db.storage import StorageService

router = APIRouter(prefix="/api/ocr", tags=["ocr"])

MAX_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "100"))

@router.post("/annotate")
async def annotate_pdf(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    mode: str = Query("full", pattern="^(full|fast)$"),
):
    # Validate file
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    data = await file.read()
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File size exceeds {MAX_MB} MB")

    # Annotate
    try:
        annotator = OCRAnnotator(fast_mode=(mode == "fast"))
        annotated_bytes, meta = annotator.annotate_pdf(pdf_bytes=data, original_filename=file.filename)
    except ImportError as e:
        # OCR module not available/misconfigured
        raise HTTPException(status_code=503, detail=f"OCR module unavailable: {e}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR/annotation failed: {e}")

    # Upload to Supabase Storage and get signed URL
    try:
        storage = StorageService()
        signed_url = storage.upload_pdf_and_get_signed_url(
            user_id=user_id,
            original_stem=os.path.splitext(file.filename)[0],
            data=annotated_bytes
        )
    except Exception as e:
        # Non-fatal; still return the PDF body
        signed_url = ""

    # Stream back PDF with a signed URL header
    headers = {
        "Content-Disposition": f'attachment; filename="{os.path.splitext(file.filename)[0]}_annotated.pdf"',
    }
    if signed_url:
        headers["X-File-URL"] = signed_url

    return Response(content=annotated_bytes, media_type="application/pdf", headers=headers, status_code=status.HTTP_200_OK)


# Optional JSON-only endpoint for dashboards
@router.post("/annotate/json")
async def annotate_pdf_json(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    mode: str = Query("full", pattern="^(full|fast)$"),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    data = await file.read()
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File size exceeds {MAX_MB} MB")

    try:
        annotator = OCRAnnotator(fast_mode=(mode == "fast"))
        _, meta = annotator.annotate_pdf(pdf_bytes=data, original_filename=file.filename)
        return {"ok": True, **meta}
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"OCR module unavailable: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR failed: {e}")
