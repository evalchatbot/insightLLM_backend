"""
API routes for the OCR agent (stub).
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any
from backend.agents.ocr_agent import OCRAgent

router = APIRouter(prefix="/ocr", tags=["ocr"])

agent = OCRAgent()

class OCRParseRequest(BaseModel):
    image: Any  # Placeholder; in real use, would be UploadFile or bytes

class OCRParseResponse(BaseModel):
    text: str

@router.post("/parse", response_model=OCRParseResponse)
def parse_ocr(req: OCRParseRequest) -> OCRParseResponse:
    """Stub: Parse image and return extracted text."""
    text = agent.parse_image(req.image)
    return OCRParseResponse(text=text)
