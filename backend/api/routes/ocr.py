from __future__ import annotations
import os
import json
import hashlib
import time
from typing import Dict, Any, Tuple
from fastapi import APIRouter, UploadFile, File, HTTPException, Response, status, Query, Form
from fastapi.responses import StreamingResponse, JSONResponse
from backend.ocr.service import OCRAnnotator, get_all_available_subjects
from backend.db.storage import StorageService
import io

router = APIRouter(prefix="/api/ocr", tags=["ocr"])

MAX_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "100"))

# Simple in-memory cache for metadata (with expiration)
# Format: {cache_key: (metadata, timestamp)}
_metadata_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}
CACHE_EXPIRY_SECONDS = 300  # 5 minutes

def _generate_cache_key(user_id: str, filename: str, question: str, subject: str) -> str:
    """Generate a unique cache key for the request."""
    content = f"{user_id}:{filename}:{question}:{subject}"
    return hashlib.md5(content.encode()).hexdigest()

def _store_metadata(cache_key: str, metadata: Dict[str, Any]) -> None:
    """Store metadata in cache with timestamp."""
    _metadata_cache[cache_key] = (metadata, time.time())
    # Clean old entries (keep cache size manageable)
    current_time = time.time()
    expired_keys = [k for k, (_, ts) in _metadata_cache.items() if current_time - ts > CACHE_EXPIRY_SECONDS]
    for k in expired_keys:
        _metadata_cache.pop(k, None)

def _get_cached_metadata(cache_key: str) -> Dict[str, Any] | None:
    """Retrieve metadata from cache if not expired."""
    if cache_key in _metadata_cache:
        metadata, timestamp = _metadata_cache[cache_key]
        if time.time() - timestamp < CACHE_EXPIRY_SECONDS:
            return metadata
        else:
            _metadata_cache.pop(cache_key, None)
    return None

@router.post("/annotate")
async def annotate_pdf(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    question: str = Form(...),
    subject: str = Form(...),
    mode: str = Query("full", pattern="^(full|fast)$"),
):
    """
    Process PDF and return both annotated PDF and metadata in a JSON response.
    This avoids HTTP header size limits and makes the response more reliable.
    """
    # Validate file
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    data = await file.read()
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File size exceeds {MAX_MB} MB")
    question = (question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question text is required")

    subject = (subject or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject selection is required")

    # Generate cache key
    cache_key = _generate_cache_key(user_id, file.filename, question, subject)

    # Annotate
    try:
        annotator = OCRAnnotator(fast_mode=(mode == "fast"))
        annotated_bytes, meta = annotator.annotate_pdf(
            pdf_bytes=data,
            original_filename=file.filename,
            question_text=question,
            subject=subject,
        )

        # Store metadata in cache for later retrieval
        _store_metadata(cache_key, meta)

    except ImportError as e:
        import traceback
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"OCR ImportError: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=503, detail=f"OCR module unavailable: {e}")
    except ValueError as e:
        # Subject validation errors
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        import logging
        logger = logging.getLogger(__name__)
        error_detail = f"OCR/annotation failed: {str(e)}"
        logger.error(f"{error_detail}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=error_detail)

    # Upload to Supabase Storage and get signed URL
    pdf_url = ""
    try:
        storage = StorageService()
        pdf_url = storage.upload_pdf_and_get_signed_url(
            user_id=user_id,
            original_stem=os.path.splitext(file.filename)[0],
            data=annotated_bytes
        )
    except Exception as e:
        # Non-fatal
        pass

    # Return JSON response with both PDF data and metadata
    import base64
    pdf_base64 = base64.b64encode(annotated_bytes).decode('utf-8')

    return JSONResponse(content={
        "pdf_base64": pdf_base64,
        "pdf_url": pdf_url,
        "metadata": meta,
        "cache_key": cache_key,
        "filename": f"{os.path.splitext(file.filename)[0]}_annotated.pdf"
    })


# Optional JSON-only endpoint for dashboards
@router.post("/annotate/json")
async def annotate_pdf_json(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    question: str = Form(...),
    subject: str = Form(...),
    mode: str = Query("full", pattern="^(full|fast)$"),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    data = await file.read()
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File size exceeds {MAX_MB} MB")
    question = (question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question text is required")

    subject = (subject or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject selection is required")

    try:
        annotator = OCRAnnotator(fast_mode=(mode == "fast"))
        _, meta = annotator.annotate_pdf(
            pdf_bytes=data,
            original_filename=file.filename,
            question_text=question,
            subject=subject,
        )
        return {"ok": True, **meta}
    except ImportError as e:
        import traceback
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"OCR ImportError: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=503, detail=f"OCR module unavailable: {e}")
    except ValueError as e:
        # Subject validation errors
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        import logging
        logger = logging.getLogger(__name__)
        error_detail = f"OCR failed: {str(e)}"
        logger.error(f"{error_detail}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=error_detail)


@router.get("/subjects")
async def get_subjects():
    """
    Get all available subjects from rubric folders.
    Returns dynamically based on Rubrics folder contents.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        logger.info("Attempting to load subjects...")
        subjects = get_all_available_subjects()
        logger.info(f"Successfully loaded {len(subjects)} subjects")
        return {
            "subjects": subjects,
            "count": len(subjects)
        }
    except ImportError as e:
        logger.error(f"Import error loading subjects: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Import error: {e}")
    except Exception as e:
        logger.error(f"Failed to load subjects: {e}", exc_info=True)
        # Return detailed error info for debugging
        import traceback
        error_detail = {
            "error": str(e),
            "type": type(e).__name__,
            "traceback": traceback.format_exc()
        }
        raise HTTPException(status_code=500, detail=str(error_detail))

@router.get("/debug/rubrics")
async def debug_rubrics():
    """
    Debug endpoint to check Rubrics folder status.
    Returns information about the Rubrics directory and files.
    """
    from pathlib import Path
    import os

    debug_info = {
        "python_docx_available": False,
        "rubrics_path": None,
        "rubrics_exists": False,
        "rubrics_files": [],
        "cwd": os.getcwd(),
        "file_location": str(Path(__file__).resolve()),
        "error": None
    }

    try:
        # Check python-docx
        try:
            import docx
            debug_info["python_docx_available"] = True
        except ImportError:
            debug_info["error"] = "python-docx not installed"

        # Calculate Rubrics path (same logic as rubric_parser)
        # This file is at: backend/api/routes/ocr.py
        # Rubrics is at: backend/Rubrics/
        # So we need parents[2] to get to 'backend/' directory
        backend_dir = Path(__file__).resolve().parents[2]
        rubrics_dir = backend_dir / "Rubrics"

        debug_info["rubrics_path"] = str(rubrics_dir)
        debug_info["rubrics_exists"] = rubrics_dir.exists()

        if rubrics_dir.exists():
            # List all .docx files
            docx_files = list(rubrics_dir.glob("**/*.docx"))
            debug_info["rubrics_files"] = [str(f.relative_to(rubrics_dir)) for f in docx_files]
            debug_info["rubrics_count"] = len(docx_files)
        else:
            # Try to list what's in the parent directory
            parent_contents = list(backend_dir.parent.iterdir()) if backend_dir.parent.exists() else []
            debug_info["parent_directory_contents"] = [str(p.name) for p in parent_contents]

    except Exception as e:
        import traceback
        debug_info["error"] = str(e)
        debug_info["traceback"] = traceback.format_exc()

    return debug_info
