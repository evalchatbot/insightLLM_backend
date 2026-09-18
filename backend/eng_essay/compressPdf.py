# compressPdf.py
#
# PDF Compression Module
#
# COMPRESSION FLOW (Simple Explanation):
# =======================================
#
# Step 1: CHECK FILE SIZE
#   - Read the PDF file and check its size in megabytes (MB)
#   - If the file is smaller than 10MB, do nothing and exit
#   - If the file is 10MB or larger, proceed to compression
#
# Step 2: BACKUP THE ORIGINAL FILE
#   - Rename the original PDF to a temporary backup file (e.g., "output.pdf.tmp")
#   - This keeps the original safe until compression is successful
#   - If anything goes wrong, we can restore the original from this backup
#
# Step 3: COMPRESS EACH PAGE
#   - Open the backup PDF file
#   - For each page in the PDF:
#     a) Convert the page to an image (rasterize it)
#     b) If the image is too large (bigger than 2000 pixels), resize it down
#     c) Compress the image using JPEG format with quality level 75
#     d) Create a new PDF page from the compressed image
#   - Build a new PDF document with all the compressed pages
#
# Step 4: REPLACE THE ORIGINAL FILE
#   - Save the new compressed PDF to the original file path
#   - The original file is now replaced with the smaller compressed version
#
# Step 5: CLEANUP
#   - If compression succeeded: Delete the temporary backup file
#   - If compression failed: Restore the original file from the backup
#
# OPTIONAL RETRY:
#   - If the compressed file is still too large, retry at a LOWER JPEG QUALITY only
#     (90 -> 78 -> 66 -> ... down to a floor). Resolution is NEVER reduced in this
#     loop -- shrinking pixel dimensions is what caused visible pixelation before.
#   - Only if quality alone can't get under the target (extremely long/dense
#     reports) does it fall back to a gentle one-time dimension reduction.
#
# RESULT:
#   - Most reports (cover + a normal answer script) fit under target_size_mb at
#     max_quality untouched -- compression is skipped entirely, so quality stays
#     exactly as rendered.
#   - Oversized reports get a quality-only step-down, still full resolution.
#   - The original file is safely preserved if compression fails.

import os
import tempfile
from typing import Optional
import fitz  # PyMuPDF
from PIL import Image
import io


def _rasterize_pdf_at(
    doc: "fitz.Document", quality: int, max_dimension: int
) -> "fitz.Document":
    """Build a fresh PDF, one JPEG-encoded page per source page, at `quality`.
    Only shrinks a page if it exceeds `max_dimension` (kept high by callers so
    this is normally a no-op -- resolution stays native)."""
    new_doc = fitz.open()
    for page_num in range(len(doc)):
        page = doc[page_num]
        rect = page.rect
        page_width, page_height = rect.width, rect.height

        scale = 1.0
        if page_width > max_dimension or page_height > max_dimension:
            scale = min(max_dimension / page_width, max_dimension / page_height)

        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat)
        pil_image = Image.open(io.BytesIO(pix.tobytes("png")))

        if pil_image.mode in ("RGBA", "LA", "P"):
            rgb_image = Image.new("RGB", pil_image.size, (255, 255, 255))
            if pil_image.mode == "P":
                pil_image = pil_image.convert("RGBA")
            rgb_image.paste(pil_image, mask=pil_image.split()[3] if pil_image.mode == "RGBA" else None)
            pil_image = rgb_image
        elif pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")

        img_buffer = io.BytesIO()
        pil_image.save(img_buffer, format="JPEG", quality=quality, optimize=True)
        img_buffer.seek(0)

        new_page = new_doc.new_page(width=page_width, height=page_height)
        new_page.insert_image(fitz.Rect(0, 0, page_width, page_height), stream=img_buffer.getvalue())

        pix = None
        pil_image = None
        img_buffer.close()
    return new_doc


def compress_pdf_if_needed(
    pdf_path: str,
    target_size_mb: float = 10.0,
    max_quality: int = 90,
    max_dimension: int = 4500,
    quality_floor: int = 40,
    quality_step: int = 12,
    aggressive: bool = False,  # kept for backward compatibility; unused (quality-stepping replaces it)
) -> bool:
    """
    Compress a PDF file only if its size is >= target_size_mb, by stepping the
    JPEG quality DOWN (max_quality -> quality_floor) until it fits -- resolution
    is left untouched (max_dimension is kept above normal page sizes on purpose),
    so a report that fits at max_quality is returned byte-for-byte at that quality,
    and an oversized report gets progressively (but gently) re-compressed rather
    than downscaled and softened.

    Args:
        pdf_path: Path to the PDF file to compress
        target_size_mb: File size threshold in MB to trigger compression (default: 10.0)
        max_quality: JPEG quality to try first (default: 90)
        max_dimension: Max width/height in pixels before any resolution shrink
            (default: 4500, above a typical rendered page -- effectively "never shrink")
        quality_floor: Lowest JPEG quality this will step down to (default: 40)
        quality_step: How much to lower quality per retry (default: 12)

    Returns:
        True if compression was performed (file was rewritten), False otherwise
    """
    if not os.path.exists(pdf_path):
        print(f"  Warning: PDF file not found: {pdf_path}")
        return False

    file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
    print(f"  PDF file size: {file_size_mb:.2f} MB")

    if file_size_mb < target_size_mb:
        print(f"  PDF size ({file_size_mb:.2f} MB) is below threshold ({target_size_mb} MB). No compression needed.")
        return False

    print(f"  PDF size ({file_size_mb:.2f} MB) exceeds threshold ({target_size_mb} MB). Starting compression...")

    temp_backup = pdf_path + ".tmp"
    try:
        os.rename(pdf_path, temp_backup)
        print(f"  Backed up original PDF to: {temp_backup}")

        doc = fitz.open(temp_backup)
        total_pages = len(doc)

        quality = max_quality
        dimension = max_dimension
        new_size_mb = file_size_mb
        while True:
            print(f"  Compressing {total_pages} pages at quality={quality}, max_dimension={dimension}...")
            new_doc = _rasterize_pdf_at(doc, quality=quality, max_dimension=dimension)
            new_doc.save(pdf_path)
            new_doc.close()

            new_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
            print(f"    -> {new_size_mb:.2f} MB")

            if new_size_mb < target_size_mb:
                break
            if quality <= quality_floor:
                # Quality alone couldn't get there (very long/dense report). As a last
                # resort, shrink resolution modestly (not the old hard 2000px cap) and
                # try once more at the floor quality.
                if dimension > 3000:
                    dimension = 3000
                    print(f"  Still over target at floor quality; shrinking resolution once as a last resort.")
                    continue
                print(f"  Reached quality floor ({quality_floor}) and resolution floor; keeping best result ({new_size_mb:.2f} MB).")
                break
            quality = max(quality_floor, quality - quality_step)

        doc.close()

        compression_ratio = (1 - (new_size_mb / file_size_mb)) * 100
        print(f"  Compression complete!")
        print(f"    Original size: {file_size_mb:.2f} MB")
        print(f"    Compressed size: {new_size_mb:.2f} MB")
        print(f"    Compression ratio: {compression_ratio:.1f}%")

        os.remove(temp_backup)
        print(f"  Cleaned up temporary backup file.")
        return True

    except Exception as e:
        print(f"  Error during compression: {e}")
        # Restore original from backup
        if os.path.exists(temp_backup):
            try:
                if os.path.exists(pdf_path):
                    os.remove(pdf_path)
                os.rename(temp_backup, pdf_path)
                print(f"  Restored original PDF from backup.")
            except Exception as restore_error:
                print(f"  Error restoring backup: {restore_error}")
        return False
