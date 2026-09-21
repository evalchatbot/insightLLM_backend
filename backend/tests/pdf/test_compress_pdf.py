"""
The report size cap (essay + outline pipelines call compress_pdf_if_needed with a 10 MB target):
compression only runs when needed, steps JPEG quality down (never resolution first),
keeps every page and restores the original on failure.
"""

from __future__ import annotations

import fitz
import pytest

from backend.eng_essay import compressPdf as essay_compress
from backend.outline import compressPdf as outline_compress
from support.pdfs import noisy_image_pdf, page_count, text_pdf

pytestmark = pytest.mark.pdf

MB = 1024 * 1024


def _image_widths(path):
    with fitz.open(path) as doc:
        return [doc.extract_image(page.get_images()[0][0])["width"] for page in doc]


def _page_sizes(path):
    with fitz.open(path) as doc:
        return [(round(p.rect.width), round(p.rect.height)) for p in doc]


def test_small_pdf_is_left_byte_identical(tmp_path):
    path = tmp_path / "report.pdf"
    original = text_pdf(["cover", "answer"])
    path.write_bytes(original)
    assert essay_compress.compress_pdf_if_needed(str(path), target_size_mb=10.0) is False
    assert path.read_bytes() == original


def test_missing_file_is_a_noop(tmp_path):
    assert essay_compress.compress_pdf_if_needed(str(tmp_path / "nope.pdf")) is False


def _over_cap_pdf(pages: int = 3, payload_mb: float = 10.5) -> bytes:
    """Text pages plus an incompressible embedded blob: > 10 MB on disk but cheap to rasterise."""
    import numpy as np

    doc = fitz.open(stream=text_pdf([f"Report page {i + 1}" for i in range(pages)]), filetype="pdf")
    blob = np.random.default_rng(3).integers(0, 256, size=int(payload_mb * MB), dtype=np.uint8).tobytes()
    doc.embfile_add("scan-cache.bin", blob)
    data = doc.tobytes()
    doc.close()
    return data


def test_real_10mb_cap_brings_report_under_cap_and_keeps_pages(tmp_path):
    """Default arguments == the production call site (10 MB, start at quality 90)."""
    path = tmp_path / "essay_report.pdf"
    path.write_bytes(_over_cap_pdf())
    assert path.stat().st_size > 10 * MB, "fixture must start above the cap"

    assert essay_compress.compress_pdf_if_needed(str(path)) is True

    assert path.stat().st_size < 10 * MB
    data = path.read_bytes()
    assert page_count(data) == 3
    assert _page_sizes(path) == [(595, 842)] * 3
    assert _image_widths(path) == [595] * 3  # rasterised at native page size, not downscaled
    assert not (tmp_path / "essay_report.pdf.tmp").exists()


def test_quality_steps_down_only_as_far_as_needed(tmp_path):
    path = tmp_path / "r.pdf"
    path.write_bytes(noisy_image_pdf(pages=1, px=(900, 1270)))  # ~1.3 MB; q90 ~0.9, q78 ~0.65, q66 ~0.52 MB
    target = 0.75
    assert essay_compress.compress_pdf_if_needed(str(path), target_size_mb=target, max_quality=90) is True
    size_mb = path.stat().st_size / MB
    assert size_mb < target
    assert size_mb > 0.56, "went further down the quality ladder than necessary"
    assert _image_widths(path) == [900]  # quality-stepped, resolution untouched


def test_unreachable_target_stops_at_floor_and_keeps_best_effort(tmp_path):
    path = tmp_path / "r.pdf"
    path.write_bytes(noisy_image_pdf(pages=1, px=(500, 700)))
    assert essay_compress.compress_pdf_if_needed(str(path), target_size_mb=0.01, quality_floor=60, quality_step=30) is True
    assert page_count(path.read_bytes()) == 1
    assert path.stat().st_size > 0.01 * MB


def test_corrupt_pdf_over_threshold_is_restored(tmp_path):
    path = tmp_path / "broken.pdf"
    junk = b"%PDF-1.4\n" + b"\x00garbage" * 20000
    path.write_bytes(junk)
    assert essay_compress.compress_pdf_if_needed(str(path), target_size_mb=0.05) is False
    assert path.read_bytes() == junk
    assert not (tmp_path / "broken.pdf.tmp").exists()


def test_outline_pipeline_ships_an_equivalent_compressor(tmp_path):
    path = tmp_path / "outline.pdf"
    path.write_bytes(noisy_image_pdf(pages=1, px=(900, 1270)))
    assert outline_compress.compress_pdf_if_needed(str(path), target_size_mb=1.0) is True
    assert path.stat().st_size < 1.0 * MB
    assert page_count(path.read_bytes()) == 1


def test_outline_compressor_caps_raster_dimension(tmp_path):
    path = tmp_path / "outline.pdf"
    path.write_bytes(noisy_image_pdf(pages=1, px=(1700, 1000)))
    assert outline_compress.compress_pdf_if_needed(str(path), target_size_mb=0.5, max_dimension=1200) is True
    assert _page_sizes(path) == [(1700, 1000)]  # page geometry is kept...
    assert _image_widths(path)[0] <= 1200  # ...but the raster is capped at max_dimension


@pytest.mark.xfail(
    strict=True,
    reason="BUG: outline compressPdf's aggressive retry computes a smaller `dimension` but the page loop "
    "still scales by `max_dimension`, so the retry never reduces resolution",
)
def test_outline_aggressive_retry_reduces_resolution(tmp_path):
    path = tmp_path / "outline.pdf"
    path.write_bytes(noisy_image_pdf(pages=1, px=(1700, 1000)))
    outline_compress.compress_pdf_if_needed(str(path), target_size_mb=0.01, max_dimension=2000)
    assert _image_widths(path)[0] <= 1500  # aggressive mode promises max(1500, max_dimension - 500)
