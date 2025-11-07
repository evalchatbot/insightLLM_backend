#!/usr/bin/env python3
"""
Utility helpers for PDF processing used by the Grok pipeline.
"""

from __future__ import annotations

import io
import base64
from dataclasses import dataclass
from typing import List


@dataclass
class PageText:
    page_number: int
    text: str


def extract_text_per_page(pdf_bytes: bytes) -> List[PageText]:
    """
    Extract textual content from each page in the PDF using PyMuPDF.
    """

    try:
        import fitz  # PyMuPDF  (local import so module consumers not requiring PyMuPDF can still load)
    except ImportError as exc:  # pragma: no cover - runtime guard
        raise ImportError(
            "PyMuPDF (fitz) is required for PDF processing. Install it via 'pip install PyMuPDF==1.26.4'."
        ) from exc

    if not pdf_bytes:
        return []

    results: List[PageText] = []
    with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
        for idx, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            results.append(PageText(page_number=idx, text=text.strip()))

    return results


def pdf_pages_to_base64_images(pdf_bytes: bytes, *, dpi: int = 150) -> List[dict]:
    """
    Render each PDF page to a PNG and return as data URLs for multimodal models.
    """

    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - runtime guard
        raise ImportError(
            "PyMuPDF (fitz) is required for PDF processing. Install it via 'pip install PyMuPDF==1.26.4'."
        ) from exc

    if not pdf_bytes:
        return []

    images: List[dict] = []
    with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
        for idx, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            png_bytes = pix.tobytes("png")
            data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
            images.append({"page": idx, "data_url": data_url})

    return images


def pdf_pages_to_base64_images(pdf_bytes: bytes, *, dpi: int = 150) -> List[dict]:
    """
    Convert each PDF page into a PNG image encoded as base64 for vision-capable models.

    Returns:
        List of dicts with keys: {"page": int, "data_url": str}
    """

    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - runtime guard
        raise ImportError(
            "PyMuPDF (fitz) is required for PDF processing. Install it via 'pip install PyMuPDF==1.26.4'."
        ) from exc

    if not pdf_bytes:
        return []

    images: List[dict] = []
    with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
        for idx, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            png_bytes = pix.tobytes("png")
            data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
            images.append({"page": idx, "data_url": data_url})

    return images
