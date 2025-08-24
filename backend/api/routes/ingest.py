"""
API route for document ingestion and chunk upload.
"""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel
from backend.db.supabase_client import SupabaseDB
import os
import shutil
from backend.db.supabase_service import SupabaseService
from backend.ingest.document_processor import DocumentProcessor
import uuid
import tempfile

router = APIRouter(prefix="/api/documents", tags=["documents"])


# Dependency injection
def get_document_processor():
    return DocumentProcessor()


def get_supabase_service():
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # Use service role for admin operations

    if not all([supabase_url, supabase_key]):
        raise HTTPException(status_code=500, detail="Missing required environment variables")

    return SupabaseService(supabase_url, supabase_key)

class IngestResponse(BaseModel):
    book_id: str
    num_chunks: int
    message: str

@router.post("/upload", response_model=IngestResponse)
async def upload_document(
        file: UploadFile = File(...),
        title: str = None,
        author: str = None,
        genre: str = None,
        document_processor: DocumentProcessor = Depends(get_document_processor),
        supabase_service: SupabaseService = Depends(get_supabase_service)
):
    """
    Ingest a PDF document into the system
    """
    try:
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")

        # Save uploaded file to a temp location
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}_{file.filename}")
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Process document
        chunks = document_processor.process_document(temp_path)

        if not chunks:
            raise HTTPException(status_code=500, detail="Failed to process document")

        # Create book record
        book_data = {
            "title": title or file.filename.replace('.pdf', ''),
            "author": author or "Unknown Author",
            "genre": genre or "other",
            # Remove file_path from book_data if not needed in DB
            "total_pages": max(chunk["page_end"] for chunk in chunks) if chunks else 0
        }

        book = await supabase_service.create_book(book_data)

        if not book:
            raise HTTPException(status_code=500, detail="Failed to create book record")

        # Add book_id to chunks
        for chunk in chunks:
            chunk["book_id"] = book["id"]

        # Store chunks in database
        stored_chunks = await supabase_service.create_chunks(chunks)

        if not stored_chunks:
            raise HTTPException(status_code=500, detail="Failed to store document chunks")

        return {
            "message": "Document ingested successfully",
            "book_id": book["id"],
            "num_chunks": len(stored_chunks),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error ingesting document: {str(e)}")
    finally:
        # Clean up uploaded temp file
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)
