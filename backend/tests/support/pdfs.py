"""Tiny PDFs generated in-test with PyMuPDF (no binary fixtures in the repo)."""

from __future__ import annotations

import io
from typing import Sequence, Tuple

import fitz  # PyMuPDF
import numpy as np
from PIL import Image


def text_pdf(pages: Sequence[str] = ("Page one text",), size: Tuple[float, float] = (595, 842)) -> bytes:
    """A vector PDF with one line of text per page."""
    doc = fitz.open()
    for text in pages:
        page = doc.new_page(width=size[0], height=size[1])
        page.insert_text((72, 72), text, fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()
    return data


def noisy_image_pdf(pages: int, px: Tuple[int, int] = (900, 1270), seed: int = 7, quality: int = 95) -> bytes:
    """
    A "scanned" PDF: every page is one high-entropy JPEG whose pixel size equals the
    page size in points (how the essay pipeline builds its PDFs via PIL), so it is
    large and compresses poorly -- ideal for exercising the size-cap compressor.
    """
    rng = np.random.default_rng(seed)
    doc = fitz.open()
    for _ in range(pages):
        arr = rng.integers(0, 256, size=(px[1], px[0], 3), dtype=np.uint8)
        buf = io.BytesIO()
        Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=quality)
        page = doc.new_page(width=px[0], height=px[1])
        page.insert_image(fitz.Rect(0, 0, px[0], px[1]), stream=buf.getvalue())
    data = doc.tobytes()
    doc.close()
    return data


def page_count(pdf_bytes: bytes) -> int:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return len(doc)


def page_text(pdf_bytes: bytes, index: int = 0) -> str:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return doc[index].get_text()
