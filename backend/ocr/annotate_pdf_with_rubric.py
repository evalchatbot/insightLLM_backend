from typing import Any, Dict, List, Tuple, Optional
import io
import gc
import os
import sys

import cv2
import numpy as np
import fitz
from PIL import Image

# Try to import psutil for cross-platform memory monitoring
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    # Fallback to resource module (Unix only)
    try:
        import resource
        RESOURCE_AVAILABLE = True
    except ImportError:
        RESOURCE_AVAILABLE = False


def _get_available_memory_mb() -> Optional[float]:
    """
    Get available system memory in MB.
    Returns None if memory information is not available.
    """
    try:
        if PSUTIL_AVAILABLE:
            # Cross-platform memory info
            mem = psutil.virtual_memory()
            return mem.available / (1024 * 1024)  # Convert to MB
        elif RESOURCE_AVAILABLE and sys.platform != 'win32':
            # Unix-only: get process memory limit
            # Note: This gives process limit, not system available
            # For system memory, we'd need to parse /proc/meminfo
            try:
                with open('/proc/meminfo', 'r') as f:
                    for line in f:
                        if line.startswith('MemAvailable:'):
                            parts = line.split()
                            if len(parts) >= 2:
                                # Value is in KB, convert to MB
                                return float(parts[1]) / 1024.0
            except (IOError, ValueError):
                pass
    except Exception:
        pass
    return None


def _get_process_memory_mb() -> Optional[float]:
    """
    Get current process memory usage in MB.
    Returns None if memory information is not available.
    """
    try:
        if PSUTIL_AVAILABLE:
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            return mem_info.rss / (1024 * 1024)  # Convert to MB
        elif RESOURCE_AVAILABLE and sys.platform != 'win32':
            # Unix-only: get process memory usage
            usage = resource.getrusage(resource.RUSAGE_SELF)
            # maxrss is in KB on Linux, convert to MB
            return usage.ru_maxrss / 1024.0
    except Exception:
        pass
    return None


def _estimate_memory_requirements(
    page_count: int,
    avg_page_size_mb: float = 2.0,
    processing_copies: int = 4,
    safety_margin: float = 2.0,
) -> float:
    """
    Estimate memory requirements for annotation processing.
    
    Args:
        page_count: Number of pages to process
        avg_page_size_mb: Average size of one page image in MB (default: 2.0)
        processing_copies: Number of copies created during processing (default: 4)
        safety_margin: Safety margin multiplier (default: 2.0)
    
    Returns:
        Estimated memory requirement in MB
    """
    # Memory for processing one page at a time
    processing_memory = avg_page_size_mb * processing_copies
    
    # Memory for accumulated annotated pages (output)
    output_memory = page_count * avg_page_size_mb
    
    # Total estimated memory
    total_memory = processing_memory + output_memory
    
    # Apply safety margin
    estimated_memory = total_memory * safety_margin
    
    return estimated_memory


def _check_memory_before_processing(
    page_count: int,
    pdf_size_mb: Optional[float] = None,
    warn_threshold_mb: float = 500.0,
    fail_threshold_mb: float = 200.0,
) -> Tuple[bool, Optional[str]]:
    """
    Check if there's sufficient memory before starting processing.
    
    Args:
        page_count: Number of pages to process
        pdf_size_mb: Size of PDF file in MB (optional, for better estimation)
        warn_threshold_mb: Warn if available memory is below this (MB)
        fail_threshold_mb: Fail if available memory is below this (MB)
    
    Returns:
        Tuple of (should_proceed, warning_message)
        - should_proceed: True if processing should continue, False if should fail
        - warning_message: Optional warning message if memory is low
    """
    available_memory = _get_available_memory_mb()
    process_memory = _get_process_memory_mb()
    
    # Estimate memory requirements
    if pdf_size_mb:
        # Use actual PDF size to estimate page size
        avg_page_size = max(1.0, pdf_size_mb / max(1, page_count))
    else:
        # Use default estimate
        avg_page_size = 2.0
    
    estimated_required = _estimate_memory_requirements(
        page_count=page_count,
        avg_page_size_mb=avg_page_size,
    )
    
    # If we can't get memory info, proceed with warning
    if available_memory is None:
        return True, "Memory information not available - proceeding with caution"
    
    # Check if we have enough memory
    if available_memory < fail_threshold_mb:
        return False, (
            f"Insufficient memory: {available_memory:.1f} MB available, "
            f"estimated {estimated_required:.1f} MB required. "
            f"Processing may fail. Consider processing smaller files or increasing system memory."
        )
    
    if available_memory < estimated_required:
        return False, (
            f"Low memory: {available_memory:.1f} MB available, "
            f"estimated {estimated_required:.1f} MB required. "
            f"Processing may fail."
        )
    
    if available_memory < warn_threshold_mb:
        return True, (
            f"Low available memory: {available_memory:.1f} MB. "
            f"Estimated requirement: {estimated_required:.1f} MB. "
            f"Processing may be slow or fail with very large files."
        )
    
    # Memory looks good
    if process_memory:
        return True, (
            f"Memory check: {available_memory:.1f} MB available, "
            f"process using {process_memory:.1f} MB, "
            f"estimated {estimated_required:.1f} MB required"
        )
    
    return True, f"Memory check: {available_memory:.1f} MB available, estimated {estimated_required:.1f} MB required"


def _get_page_ocr(ocr_data: Dict[str, Any], page_number: int) -> Optional[Dict[str, Any]]:
    for p in ocr_data.get("pages", []):
        if p.get("page_number") == page_number:
            return p
    return None


def _bbox_to_rect(
    bbox: List[Tuple[int, int]],
    pad: int,
    w: int,
    h: int,
) -> Tuple[int, int, int, int]:
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    x1 = max(0, min(xs) - pad)
    y1 = max(0, min(ys) - pad)
    x2 = min(w - 1, max(xs) + pad)
    y2 = min(h - 1, max(ys) + pad)
    return x1, y1, x2, y2


def _wrap_text_cv2(
    text: str,
    max_width_px: int,
    font_face: int,
    font_scale: float,
    thickness: int,
) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = ""
    for w in words:
        trial = (current + " " + w).strip()
        if not trial:
            continue
        size, _ = cv2.getTextSize(trial, font_face, font_scale, thickness)
        if size[0] <= max_width_px or not current:
            current = trial
        else:
            # Check if single word is too long
            word_size, _ = cv2.getTextSize(w, font_face, font_scale, thickness)
            if word_size[0] > max_width_px:
                # Word too long, needs character-level breaking
                if current:
                    lines.append(current)
                # Break word into chunks that fit
                for i in range(0, len(w), max(1, int(len(w) * max_width_px / word_size[0]))):
                    chunk = w[i:i + max(1, int(len(w) * max_width_px / word_size[0]))]
                    chunk_size, _ = cv2.getTextSize(chunk, font_face, font_scale, thickness)
                    if chunk_size[0] <= max_width_px:
                        lines.append(chunk)
                    else:
                        # Even chunk too long, force break with hyphen
                        for j in range(len(chunk)):
                            test = chunk[:j+1]
                            test_size, _ = cv2.getTextSize(test + "-", font_face, font_scale, thickness)
                            if test_size[0] > max_width_px and j > 0:
                                lines.append(chunk[:j] + "-")
                                chunk = chunk[j:]
                                break
                        if chunk:
                            lines.append(chunk)
                current = ""
            else:
                lines.append(current)
                current = w
    if current:
        lines.append(current)
    return lines


def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def _find_heading_bbox_on_page(
    title: str,
    page_ocr: Dict[str, Any],
) -> Optional[List[Tuple[int, int]]]:
    target = _normalize(title)
    if not target:
        return None

    best_bbox = None
    best_score = 0.0

    for line in page_ocr.get("lines", []):
        text = (line.get("text") or "").strip()
        if not text:
            continue

        # Skip very long lines (likely body text, not headings)
        if len(text) > 150:
            continue

        candidate = _normalize(text)

        # Exact match is best
        if candidate == target:
            return line.get("bbox")

        # For OCR variations, check token overlap but with higher threshold
        # Headings should match most of their tokens
        t_tokens = target.split()
        c_tokens = candidate.split()

        if len(t_tokens) == 0:
            continue

        # Only consider if all target tokens are present in candidate
        common = len(set(t_tokens) & set(c_tokens))
        score = common / len(t_tokens)

        # Higher threshold (0.8+) to avoid matching random body text
        if score > best_score and score >= 0.8:
            best_score = score
            best_bbox = line.get("bbox")

    return best_bbox


def _find_word_or_line_rect(
    page_ocr: Dict[str, Any],
    target_text: str,
    w: int,
    h: int,
) -> Optional[Tuple[int, int, int, int]]:
    if not target_text:
        return None

    target_norm = _normalize(target_text)
    if not target_norm:
        return None

    tokens = [t for t in target_norm.split() if t]
    if not tokens:
        return None

    # 1) Try word-level matching for each token and union boxes
    matched_word_boxes: List[List[Tuple[int, int]]] = []
    for line in page_ocr.get("lines", []):
        for w_entry in line.get("words") or []:
            w_text = _normalize(w_entry.get("text") or "")
            if not w_text:
                continue
            if w_text in tokens or w_text == target_norm:
                if w_entry.get("bbox"):
                    matched_word_boxes.append(w_entry["bbox"])

    if matched_word_boxes:
        xs: List[int] = []
        ys: List[int] = []
        for bbox in matched_word_boxes:
            for x, y in bbox:
                xs.append(x)
                ys.append(y)
        if xs and ys:
            x1 = max(0, min(xs) - 2)
            y1 = max(0, min(ys) - 2)
            x2 = min(w - 1, max(xs) + 2)
            y2 = min(h - 1, max(ys) + 2)
            return x1, y1, x2, y2

    # 2) Fallback: line-level fuzzy matching, but reject huge boxes
    best_rect = None
    best_score = 0.0

    for line in page_ocr.get("lines", []):
        text = _normalize(line.get("text") or "")
        if not text:
            continue

        if target_norm in text or text in target_norm:
            score = 1.0
        else:
            t_tokens = set(tokens)
            l_tokens = set(text.split())
            common = len(t_tokens & l_tokens)
            score = common / max(len(tokens), 1)

        if score < 0.5 or score <= best_score:
            continue

        bbox = line.get("bbox")
        if not bbox:
            continue

        x1, y1, x2, y2 = _bbox_to_rect(bbox, pad=2, w=w, h=h)
        box_w = x2 - x1
        box_h = y2 - y1

        # Reject boxes that are 'too big' (heuristic thresholds)
        if box_h > 0.3 * h or box_w > 0.9 * w:
            continue

        best_score = score
        best_rect = (x1, y1, x2, y2)

    return best_rect


def _find_precise_word_rect_with_context(
    page_ocr: Dict[str, Any],
    target_text: str,
    context_before: str,
    context_after: str,
    w: int,
    h: int,
    already_found: Optional[List[Tuple[int, int, int, int]]] = None,
) -> Optional[Tuple[int, int, int, int]]:
    if not target_text:
        return None

    target_norm = _normalize(target_text)
    before_norm = _normalize(context_before)
    after_norm = _normalize(context_after)

    if not target_norm:
        return None

    already_found = already_found or []
    target_tokens = target_norm.split()

    # Build word sequence for the whole page
    all_words: List[Dict[str, Any]] = []
    for line in page_ocr.get("lines", []):
        for w_entry in line.get("words") or []:
            w_text = _normalize(w_entry.get("text") or "")
            if w_text and w_entry.get("bbox"):
                all_words.append({
                    "text": w_text,
                    "bbox": w_entry["bbox"]
                })

    if not all_words:
        return None

    # Find all positions where target appears
    best_rect = None
    best_score = 0.0

    for i in range(len(all_words) - len(target_tokens) + 1):
        # Check if target matches at position i
        matches = True
        for j, target_token in enumerate(target_tokens):
            if target_token != all_words[i + j]["text"]:
                matches = False
                break

        if not matches:
            continue

        # Get bboxes for matched words
        matched_bboxes = [all_words[i + j]["bbox"] for j in range(len(target_tokens))]

        # Union the bboxes
        xs: List[int] = []
        ys: List[int] = []
        for bbox in matched_bboxes:
            for x, y in bbox:
                xs.append(x)
                ys.append(y)

        if not xs or not ys:
            continue

        x1 = max(0, min(xs) - 2)
        y1 = max(0, min(ys) - 2)
        x2 = min(w - 1, max(xs) + 2)
        y2 = min(h - 1, max(ys) + 2)

        # Check if already found
        is_duplicate = False
        for found_rect in already_found:
            fx1, fy1, fx2, fy2 = found_rect
            overlap_x = max(0, min(x2, fx2) - max(x1, fx1))
            overlap_y = max(0, min(y2, fy2) - max(y1, fy1))
            if overlap_x > 0 and overlap_y > 0:
                is_duplicate = True
                break

        if is_duplicate:
            continue

        # Score based on context
        score = 1.0

        # Check context_before (look at previous words)
        if before_norm:
            prev_words = []
            for k in range(max(0, i - 7), i):
                prev_words.append(all_words[k]["text"])
            prev_text = " ".join(prev_words)

            if before_norm in prev_text:
                score += 2.0
            else:
                before_tokens = set(before_norm.split())
                prev_tokens = set(prev_words)
                if before_tokens:
                    overlap_ratio = len(before_tokens & prev_tokens) / len(before_tokens)
                    score += overlap_ratio * 1.0

        # Check context_after (look at next words)
        if after_norm:
            next_words = []
            for k in range(i + len(target_tokens), min(len(all_words), i + len(target_tokens) + 7)):
                next_words.append(all_words[k]["text"])
            next_text = " ".join(next_words)

            if after_norm in next_text:
                score += 2.0
            else:
                after_tokens = set(after_norm.split())
                next_tokens = set(next_words)
                if after_tokens:
                    overlap_ratio = len(after_tokens & next_tokens) / len(after_tokens)
                    score += overlap_ratio * 1.0

        # Update best match
        if score > best_score:
            best_score = score
            best_rect = (x1, y1, x2, y2)

    return best_rect


def _find_annotation_rect_with_context(
    page_ocr: Dict[str, Any],
    target_text: str,
    context_before: str,
    context_after: str,
    w: int,
    h: int,
    already_found: Optional[List[Tuple[int, int, int, int]]] = None,
) -> Optional[Tuple[int, int, int, int]]:
    if not target_text:
        return None

    target_norm = _normalize(target_text)
    before_norm = _normalize(context_before)
    after_norm = _normalize(context_after)

    if not target_norm:
        return None

    already_found = already_found or []

    # Build a full text representation of the page to find context matches
    full_text_parts: List[str] = []
    line_to_bbox: Dict[int, List[Tuple[int, int]]] = {}

    for idx, line in enumerate(page_ocr.get("lines", [])):
        text = line.get("text") or ""
        full_text_parts.append(text)
        line_to_bbox[idx] = line.get("bbox")

    full_text = " ".join(full_text_parts)
    full_text_norm = _normalize(full_text)

    # Strategy: Find all occurrences of target in the full text with context
    # Then map back to line indices

    best_rect: Optional[Tuple[int, int, int, int]] = None
    best_score = 0.0
    best_line_idx = -1

    # Pass 1: Search with context to find the right occurrence
    for line_idx, line in enumerate(page_ocr.get("lines", [])):
        text = _normalize(line.get("text") or "")
        if not text:
            continue

        # Check if target is in this line
        if target_norm not in text:
            continue

        bbox = line.get("bbox")
        if not bbox:
            continue

        x1, y1, x2, y2 = _bbox_to_rect(bbox, pad=3, w=w, h=h)
        box_w = x2 - x1
        box_h = y2 - y1

        # Avoid 'giant' boxes that span too much of the page
        if box_h > 0.35 * h or box_w > 0.95 * w:
            continue

        # Check if this rect was already found (for handling duplicates)
        is_duplicate = False
        for found_rect in already_found:
            fx1, fy1, fx2, fy2 = found_rect
            # Check if rects overlap significantly
            overlap_x = max(0, min(x2, fx2) - max(x1, fx1))
            overlap_y = max(0, min(y2, fy2) - max(y1, fy1))
            if overlap_x > 0 and overlap_y > 0:
                is_duplicate = True
                break

        if is_duplicate:
            continue

        # Score this match based on context
        score = 1.0  # Base score for having the target

        # Check context before
        if before_norm:
            # Look at previous lines
            prev_texts = []
            for i in range(max(0, line_idx - 2), line_idx):
                prev_texts.append(_normalize(page_ocr.get("lines", [])[i].get("text") or ""))
            prev_context = " ".join(prev_texts) + " " + text

            if before_norm in prev_context:
                score += 2.0
            else:
                # Partial match with context_before tokens
                before_tokens = set(before_norm.split())
                context_tokens = set(prev_context.split())
                if before_tokens:
                    overlap = len(before_tokens & context_tokens) / len(before_tokens)
                    score += overlap * 1.0

        # Check context after
        if after_norm:
            # Look at next lines
            next_texts = [text]
            for i in range(line_idx + 1, min(len(page_ocr.get("lines", [])), line_idx + 3)):
                next_texts.append(_normalize(page_ocr.get("lines", [])[i].get("text") or ""))
            next_context = " ".join(next_texts)

            if after_norm in next_context:
                score += 2.0
            else:
                # Partial match with context_after tokens
                after_tokens = set(after_norm.split())
                context_tokens = set(next_context.split())
                if after_tokens:
                    overlap = len(after_tokens & context_tokens) / len(after_tokens)
                    score += overlap * 1.0

        # Update best match
        if score > best_score:
            best_score = score
            best_rect = (x1, y1, x2, y2)
            best_line_idx = line_idx

    if best_rect is not None:
        return best_rect

    # Pass 2: Fallback to word-level matching without context
    return _find_word_or_line_rect(page_ocr, target_text, w=w, h=h)



def _compute_section_region_on_page(
    section: Dict[str, Any],
    page_number: int,
    ocr_data: Dict[str, Any],
    orig_w: int,
    orig_h: int,
    all_sections: List[Dict[str, Any]],
) -> Optional[Tuple[int, int, int, int]]:
    page_ocr = _get_page_ocr(ocr_data, page_number)
    if not page_ocr:
        return None

    title = section.get("title") or ""
    heading_bbox = _find_heading_bbox_on_page(title, page_ocr)

    # Determine y_start
    first_section_page = min(section.get("page_numbers") or [page_number])
    if heading_bbox and page_number == first_section_page:
        xh1, yh1, xh2, yh2 = _bbox_to_rect(heading_bbox, pad=6, w=orig_w, h=orig_h)
        y_start = max(0, yh1 - 4)
    else:
        y_start = 0

    # Determine y_end from next section on this page
    y_end = orig_h - 1
    this_index = None
    for idx, sec in enumerate(all_sections):
        if sec is section:
            this_index = idx
            break

    if this_index is not None:
        for next_sec in all_sections[this_index + 1:]:
            if page_number not in (next_sec.get("page_numbers") or []):
                continue
            next_page_ocr = _get_page_ocr(ocr_data, page_number)
            if not next_page_ocr:
                continue
            next_bbox = _find_heading_bbox_on_page(next_sec.get("title") or "", next_page_ocr)
            if next_bbox:
                _, ny1, _, _ = _bbox_to_rect(next_bbox, pad=4, w=orig_w, h=orig_h)
                if ny1 > y_start:
                    y_end = ny1 - 4
                break

    # Collect all lines between y_start and y_end
    xs: List[int] = []
    ys: List[int] = []
    for line in page_ocr.get("lines", []):
        lbbox = line.get("bbox")
        if not lbbox:
            continue
        lx1, ly1, lx2, ly2 = _bbox_to_rect(lbbox, pad=0, w=orig_w, h=orig_h)
        mid_y = (ly1 + ly2) // 2
        if y_start <= mid_y <= y_end:
            xs.extend([lx1, lx2])
            ys.extend([ly1, ly2])

    if not xs or not ys:
        return None

    x1 = max(0, min(xs))
    x2 = min(orig_w - 1, max(xs))
    y1 = max(0, min(ys))
    y2 = min(orig_h - 1, max(ys))
    return x1, y1, x2, y2


# ---------- MAIN ANNOTATION FUNCTION ----------


def annotate_pdf_answer_pages(
    pdf_path: str,
    ocr_data: Dict[str, Any],
    sections: List[Dict[str, Any]],
    annotations: List[Dict[str, Any]],
    page_suggestions: Optional[List[Dict[str, Any]]] = None,
    refined_summary: Optional[List[Dict[str, Any]]] = None,
) -> List[Image.Image]:
    """
    Create annotated versions of the answer pages.

    NEW LAYOUT:
      - [LEFT MARGIN with improvement suggestions][Original Answer Page]
      - Left margin shows specific, actionable suggestions for each page
      - Annotations still mark errors/issues on the answer itself

    Annotation behaviour:
      - introduction_comment → big red box for whole introduction + red comment in side padding
      - heading_issue (negative) → red box on heading line + red comment in side padding
      - factual_error → red box on sentence line + red comment in side padding
      - grammar_language → small red box on word/sentence + red correction near box (no side comment)
      - repetition → red box on repeated section region, text "repeated on page X" in red near box
      - For each 'correct' section on a page (no negative annotation on that page):
          → draw a red ✓ near the heading and near the section body region.
    """
    page_suggestions = page_suggestions or []
    refined_summary = refined_summary or []
    
    # Get PDF file size for memory estimation
    pdf_size_mb = None
    try:
        pdf_size_bytes = os.path.getsize(pdf_path)
        pdf_size_mb = pdf_size_bytes / (1024 * 1024)
    except Exception:
        pass
    
    # Load PDF pages via PyMuPDF
    doc = fitz.open(pdf_path)
    try:
        page_count = len(doc)
        
        # Check memory before processing
        should_proceed, memory_message = _check_memory_before_processing(
            page_count=page_count,
            pdf_size_mb=pdf_size_mb,
        )
        
        if not should_proceed:
            # Fail gracefully with clear error message
            raise MemoryError(
                f"Cannot process PDF: {memory_message}. "
                f"PDF has {page_count} pages ({pdf_size_mb:.1f} MB if available). "
                f"Please try with a smaller file or increase available system memory."
            )
        
        # Log memory status (warning or info)
        if memory_message:
            print(f"Memory check: {memory_message}")
            if "Low" in memory_message or "caution" in memory_message.lower():
                print(f"WARNING: {memory_message}")
        
        annotated_pages: List[Image.Image] = []

        # Precompute OCR by page
        ocr_pages_by_num: Dict[int, Dict[str, Any]] = {
            p.get("page_number"): p for p in ocr_data.get("pages", [])
        }
        print(f"DEBUG: OCR pages available: {list(ocr_pages_by_num.keys())}")
        for page_num, page_data in ocr_pages_by_num.items():
            line_count = len(page_data.get("lines", []))
            print(f"  Page {page_num}: {line_count} lines")

        # Map sections by id for quick lookup
        sections_by_id: Dict[str, Dict[str, Any]] = {}
        for sec in sections:
            sid = sec.get("id") or sec.get("section_id") or sec.get("title")
            if sid:
                sections_by_id[str(sid)] = sec

        print(f"DEBUG: Sections found: {len(sections)}")
        for idx, sec in enumerate(sections):
            title = sec.get("title", "Untitled")
            pages = sec.get("page_numbers", [])
            print(f"  Section {idx+1}: '{title}' on pages {pages}")

        # Drawing constants
        font_face = cv2.FONT_HERSHEY_SIMPLEX
        RED = (0, 0, 255)

        for page_idx, page in enumerate(doc):
            page_number = page_idx + 1
            
            # Load this page as PIL image (process one at a time to reduce memory)
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            pil_img = Image.open(io.BytesIO(img_bytes))
            
            # Convert PIL to NumPy array (RGB format)
            # Use asarray to avoid copy if possible, then convert BGR to RGB efficiently
            orig_cv_rgb = np.asarray(pil_img)
            if len(orig_cv_rgb.shape) == 3 and orig_cv_rgb.shape[2] == 3:
                # Convert RGB to BGR for OpenCV (creates a view, not a copy)
                orig_cv = orig_cv_rgb[:, :, ::-1]
            else:
                # Handle RGBA or grayscale
                if len(orig_cv_rgb.shape) == 3 and orig_cv_rgb.shape[2] == 4:
                    # RGBA: convert to RGB first
                    pil_img = pil_img.convert('RGB')
                    orig_cv_rgb = np.asarray(pil_img)
                orig_cv = orig_cv_rgb[:, :, ::-1] if len(orig_cv_rgb.shape) == 3 else orig_cv_rgb
            
            orig_h, orig_w, _ = orig_cv.shape
            
            # Explicitly delete pix and img_bytes to free memory immediately
            del pix, img_bytes

            # Extended canvas: [left margin][answer][right margin]
            left_width = int(0.40 * orig_w)
            right_width = int(0.40 * orig_w)
            new_w = left_width + orig_w + right_width
            h = orig_h
            margin = int(0.03 * orig_w)

            cv_img = np.full((h, new_w, 3), 255, dtype=np.uint8)
            # Place answer in the center
            cv_img[:, left_width:left_width + orig_w, :] = orig_cv

            # Left-side padding area for improvement suggestions
            suggestion_x1 = margin
            suggestion_x2 = left_width - margin
            suggestion_y = margin + int(0.05 * h)

            # Right-side padding area for error/issue annotations
            comment_x1 = left_width + orig_w
            comment_x2 = new_w - margin
            comment_x = comment_x1 + margin
            comment_y = margin + int(0.05 * h)

            # Get suggestions for this page
            page_suggestion_data = None
            for ps in page_suggestions:
                if ps.get("page") == page_number:
                    page_suggestion_data = ps
                    break

            page_ocr = ocr_pages_by_num.get(page_number)
            if not page_ocr:
                # Check if image is too large BEFORE color conversion
                max_dimension = 4000
                h_img, w_img = cv_img.shape[:2]
                
                # Downscale BEFORE color conversion to reduce memory pressure
                if max(h_img, w_img) > max_dimension:
                    scale = max_dimension / max(h_img, w_img)
                    new_w = int(w_img * scale)
                    new_h = int(h_img * scale)
                    cv_img = cv2.resize(cv_img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
                
                # Convert BGR to RGB efficiently using cv2.cvtColor (more memory efficient)
                cv_img_rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                
                pil_result = Image.fromarray(cv_img_rgb)
                annotated_pages.append(pil_result)
                # Free memory immediately
                del cv_img_rgb, orig_cv, pil_img, pil_result
                gc.collect()
                continue

            # Draw config based on page size (bigger fonts + thicker lines)
            font_scale = max(0.9, min(orig_w, h) / 1200.0)
            text_thickness = 3
            box_thickness = 5
            line_height = int(32 * font_scale)
            suggestion_max_width = suggestion_x2 - suggestion_x1 - 10
            comment_max_width = comment_x2 - comment_x - 10

            # RENDER IMPROVEMENT SUGGESTIONS ON LEFT MARGIN
            BLUE = (255, 140, 0)  # Deep sky blue color in BGR
            if page_suggestion_data:
                suggestions = page_suggestion_data.get("suggestions", [])

                # Title
                title_text = f"Page {page_number} - Suggestions:"
                cv2.putText(
                    cv_img,
                    title_text,
                    (suggestion_x1, suggestion_y),
                    font_face,
                    font_scale * 0.9,
                    BLUE,
                    text_thickness + 1,
                    cv2.LINE_AA,
                )
                suggestion_y += int(line_height * 1.5)

                # Draw each suggestion as a numbered bullet with blue box
                for idx, suggestion in enumerate(suggestions[:6], 1):  # Max 6 suggestions
                    bullet = f"{idx}. {suggestion}"
                    wrapped_lines = _wrap_text_cv2(
                        bullet, suggestion_max_width, font_face, font_scale * 1.0, text_thickness  # Increased font scale and thickness
                    )

                    # Calculate box height for this suggestion
                    box_start_y = suggestion_y - int(line_height * 0.8)
                    box_height = len(wrapped_lines) * int(line_height * 1.2) + int(line_height * 0.4)

                    # Draw blue box around suggestion
                    cv2.rectangle(
                        cv_img,
                        (suggestion_x1 - 5, box_start_y),
                        (suggestion_x2 + 5, box_start_y + box_height),
                        BLUE,
                        3,  # Box thickness
                    )

                    for line in wrapped_lines:
                        cv2.putText(
                            cv_img,
                            line,
                            (suggestion_x1, suggestion_y),
                            font_face,
                            font_scale * 1.0,  # Increased from 0.75
                            BLUE,
                            text_thickness,  # Increased from text_thickness - 1
                            cv2.LINE_AA,
                        )
                        suggestion_y += int(line_height * 1.2)
                    suggestion_y += int(line_height * 1.2)  # Increased gap between suggestion boxes

            # Filter annotations relevant to this page
            page_anns: List[Dict[str, Any]] = []
            for ann in annotations or []:
                atype = (ann.get("type") or "").lower()

                if atype == "repetition":
                    rep_page = ann.get("repeated_page")
                    if rep_page == page_number:
                        page_anns.append(ann)
                    continue

                apage = ann.get("page")
                if apage == page_number:
                    page_anns.append(ann)

            # Track which sections are problematic on this page
            bad_section_ids: set[str] = set()
            for ann in page_anns:
                atype = (ann.get("type") or "").lower()
                if atype == "heading_issue":
                    sid = ann.get("section_id")
                    if sid:
                        bad_section_ids.add(str(sid))
                elif atype == "repetition":
                    sid = ann.get("section_id")
                    if sid:
                        bad_section_ids.add(str(sid))
                elif atype == "introduction_comment":
                    sid = ann.get("target_section_id")
                    if sid:
                        bad_section_ids.add(str(sid))

            # Helper function to shift coordinates for answer page (now in center)
            def shift_rect(rect: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
                """Shift rectangle coordinates to account for left margin."""
                x1, y1, x2, y2 = rect
                return (x1 + left_width, y1, x2 + left_width, y2)

            def add_side_comment(header: str, text: str):
                nonlocal comment_y
                # Calculate total height needed for this comment block
                box_start_y = comment_y - int(line_height * 1.0)  # Extended top padding
                temp_y = comment_y

                # Calculate header lines
                header_lines = _wrap_text_cv2(
                    header, comment_max_width - 20, font_face, font_scale * 0.95, text_thickness
                )
                temp_y += len(header_lines) * int(line_height * 1.2)

                # Calculate body lines
                if text:
                    bullet = "- " + text
                    body_lines = _wrap_text_cv2(
                        bullet, comment_max_width - 20, font_face, font_scale * 0.85, text_thickness
                    )
                    temp_y += len(body_lines) * int(line_height * 1.0)

                box_end_y = temp_y + int(line_height * 0.6)

                # Draw red box around the entire comment
                cv2.rectangle(
                    cv_img,
                    (comment_x - 10, box_start_y),
                    (comment_x2 - 5, box_end_y),
                    RED,
                    3,  # Box thickness
                )

                # Header (red, bold-ish)
                for line in header_lines:
                    cv2.putText(
                        cv_img,
                        line,
                        (comment_x, comment_y),
                        font_face,
                        font_scale * 0.95,
                        RED,
                        text_thickness,
                        cv2.LINE_AA,
                    )
                    comment_y += int(line_height * 1.2)

                # Body text (red)
                if text:
                    bullet = "- " + text
                    for line in _wrap_text_cv2(
                        bullet, comment_max_width - 20, font_face, font_scale * 0.85, text_thickness
                    ):
                        cv2.putText(
                            cv_img,
                            line,
                            (comment_x, comment_y),
                            font_face,
                            font_scale * 0.85,
                            RED,
                            text_thickness,
                            cv2.LINE_AA,
                        )
                        comment_y += int(line_height * 1.0)

                # Spacer
                comment_y += int(line_height * 0.6)

            def draw_correction_near_box(
                rect: Tuple[int, int, int, int],
                correction: str,
            ):
                if not correction:
                    return
                x1, y1, x2, y2 = rect
                cx = x1
                cy = max(15, y1 - 8)  # Increased minimum to avoid negative coords

                size, _ = cv2.getTextSize(
                    correction, font_face, font_scale * 0.85, text_thickness
                )
                tx, ty = size
                canvas_max_x = left_width + orig_w - 5
                bg_x2 = min(canvas_max_x, cx + tx + 8)
                bg_y2 = max(5, cy - ty - 6)  # Ensure >= 5 instead of 0

                # Background white box for correction
                cv2.rectangle(
                    cv_img,
                    (cx - 2, bg_y2),
                    (bg_x2, cy + 4),
                    (255, 255, 255),
                    thickness=-1,
                )
                cv2.putText(
                    cv_img,
                    correction,
                    (cx, cy),
                    font_face,
                    font_scale * 0.85,
                    RED,
                    text_thickness,
                    cv2.LINE_AA,
                )

            def draw_connector(
                rect: Tuple[int, int, int, int],
                target_y_center: int,
            ):
                """
                Draw a red line from the annotation box to the right-side comment.
                """
                x1, y1, x2, y2 = rect
                rect_center_y = (y1 + y2) // 2
                rect_right_x = min(left_width + orig_w - int(0.02 * orig_w), x2 + 10)
                cv2.line(
                    cv_img,
                    (rect_right_x, rect_center_y),
                    (comment_x, target_y_center),
                    RED,
                    3,
                )


        
            def draw_tick_shape(
                img,
                x: int,
                y: int,
                color: Tuple[int, int, int],
                thickness: int,
            ):
                """
                Draw a simple tick (checkmark) using two anti-aliased lines.
                The size scales with font_scale so it looks consistent.
                (x, y) is the 'start' of the tick.
                """
                # Scale lengths based on font_scale so it looks good on large/small pages
                down_dx = int( 20 * font_scale)
                down_dy = int( 2 * 16 * font_scale)
                up_dx = int(10 * 26 * font_scale)
                up_dy = int(3 * 8 * font_scale)

                # Points of the tick
                p1 = (x, y)  # start
                p2 = (x + down_dx, y + down_dy)  # bottom of the tick
                p3 = (x + up_dx, y - up_dy)      # upper end

                # Draw two lines to make a checkmark
                cv2.line(img, p1, p2, color, thickness, cv2.LINE_AA)
                cv2.line(img, p2, p3, color, thickness, cv2.LINE_AA)



            def draw_tick_at_rect(rect: Tuple[int, int, int, int]):
                """
                Draw a red tick near the top-left of the given rectangle using two lines.
                """
                x1, y1, x2, y2 = rect

                # Choose a base point slightly inside the top-left of the rect
                tick_x = max(5, x1 + 10)
                tick_y = max(35, y1 + int(0.05 * h))  # Increased minimum to 35 to account for upward stroke

                # Use our line-based tick drawer
                draw_tick_shape(
                    img=cv_img,
                    x=tick_x,
                    y=tick_y,
                    color=RED,
                    thickness=text_thickness + 1,
                )


            # Precompute section regions for this page (for intro + repetition + ticks)
            section_regions: Dict[str, Tuple[int, int, int, int]] = {}
            for sec in sections:
                pages = sec.get("page_numbers") or []
                if page_number not in pages:
                    continue
                region = _compute_section_region_on_page(
                    section=sec,
                    page_number=page_number,
                    ocr_data=ocr_data,
                    orig_w=orig_w,
                    orig_h=orig_h,
                    all_sections=sections,
                )
                if region:
                    sid = str(sec.get("id") or sec.get("section_id") or sec.get("title"))
                    if sid:
                        section_regions[sid] = region

            # Track rectangles already found on this page to handle duplicates
            found_rects: List[Tuple[int, int, int, int]] = []

            # Draw all negative/problem annotations in red
            for ann in page_anns:
                atype = (ann.get("type") or "").lower()
                rubric_point = ann.get("rubric_point") or ""
                target_text = ann.get("target_word_or_sentence") or ""
                context_before = ann.get("context_before") or ""
                context_after = ann.get("context_after") or ""
                correction = ann.get("correction") or ""
                comment = ann.get("comment") or ""

                # 1) Introduction comment – big box over intro + right-side comment
                if atype == "introduction_comment":
                    # Try to find intro section region first
                    intro_sections = [s for s in sections if "introduction" in (s.get("title") or "").lower()]
                    if intro_sections:
                        intro_sec = intro_sections[0]
                        sid = str(intro_sec.get("id") or intro_sec.get("section_id") or intro_sec.get("title"))
                        sec_region = section_regions.get(sid)
                        if sec_region:
                            shifted = shift_rect(sec_region)
                            x1, y1, x2, y2 = shifted
                            cv2.rectangle(cv_img, (x1, y1), (x2, y2), RED, box_thickness)

                            header = f"[Introduction] ({rubric_point})".strip()
                            body = comment
                            block_height = int(line_height * 5)
                            if comment_y + block_height > h - margin:
                                comment_y = h - margin - block_height
                            comment_block_center_y = comment_y + block_height // 2
                            draw_connector(shifted, comment_block_center_y)
                            add_side_comment(header, body)
                            found_rects.append(sec_region)  # Store original for duplicate detection

                # 2) Heading issue – box on heading + right-side comment
                elif atype == "heading_issue":
                    sentiment = (ann.get("sentiment") or "").lower()
                    if sentiment not in ("negative", "weak", "problematic"):
                        continue

                    if not target_text:
                        continue

                    # Use precise word-level matching for headings (they're short)
                    rect = _find_precise_word_rect_with_context(
                        page_ocr=page_ocr,
                        target_text=target_text,
                        context_before=context_before,
                        context_after=context_after,
                        w=orig_w,
                        h=orig_h,
                        already_found=found_rects,
                    )
                    if not rect:
                        continue

                    shifted = shift_rect(rect)
                    x1, y1, x2, y2 = shifted
                    cv2.rectangle(cv_img, (x1, y1), (x2, y2), RED, box_thickness)

                    header = f"[Heading Issue] ({rubric_point})".strip()
                    body = comment
                    if correction:
                        body += f"\nSuggestion: {correction}"
                    block_height = int(line_height * 4)
                    if comment_y + block_height > h - margin:
                        comment_y = h - margin - block_height
                    comment_block_center_y = comment_y + block_height // 2
                    draw_connector(shifted, comment_block_center_y)
                    add_side_comment(header, body)
                    found_rects.append(rect)

                # 3) Factual error – precise box on error phrase + right-side comment
                elif atype == "factual_error":
                    if not target_text:
                        continue

                    # ALWAYS use precise word-level matching for factual errors
                    rect = _find_precise_word_rect_with_context(
                        page_ocr=page_ocr,
                        target_text=target_text,
                        context_before=context_before,
                        context_after=context_after,
                        w=orig_w,
                        h=orig_h,
                        already_found=found_rects,
                    )

                    if not rect:
                        continue

                    shifted = shift_rect(rect)
                    x1, y1, x2, y2 = shifted
                    cv2.rectangle(cv_img, (x1, y1), (x2, y2), RED, box_thickness)

                    header = f"[Factual Error] ({rubric_point})".strip()
                    body = comment
                    if correction:
                        body = f"Correction: {correction}\n{body}"
                    block_height = int(line_height * 4)
                    if comment_y + block_height > h - margin:
                        comment_y = h - margin - block_height
                    comment_block_center_y = comment_y + block_height // 2
                    draw_connector(shifted, comment_block_center_y)
                    add_side_comment(header, body)
                    found_rects.append(rect)

                # 4) Grammar & language – small box + inline correction
                elif atype == "grammar_language":
                    if not target_text:
                        continue

                    # ALWAYS use precise word-level matching for spelling errors
                    rect = _find_precise_word_rect_with_context(
                        page_ocr=page_ocr,
                        target_text=target_text,
                        context_before=context_before,
                        context_after=context_after,
                        w=orig_w,
                        h=orig_h,
                        already_found=found_rects,
                    )
                    if not rect:
                        continue

                    shifted = shift_rect(rect)
                    x1, y1, x2, y2 = shifted
                    cv2.rectangle(cv_img, (x1, y1), (x2, y2), RED, box_thickness)
                    draw_correction_near_box(shifted, correction)
                    found_rects.append(rect)

                # 5) Repetition – box on repeated content + text "repeated"
                elif atype == "repetition":
                    if not target_text:
                        continue

                    # Use context-aware matching
                    rect = _find_annotation_rect_with_context(
                        page_ocr=page_ocr,
                        target_text=target_text,
                        context_before=context_before,
                        context_after=context_after,
                        w=orig_w,
                        h=orig_h,
                        already_found=found_rects,
                    )
                    if not rect:
                        continue

                    shifted = shift_rect(rect)
                    x1, y1, x2, y2 = shifted
                    cv2.rectangle(cv_img, (x1, y1), (x2, y2), RED, box_thickness)

                    rep_text = comment if comment else "repeated"
                    size, _ = cv2.getTextSize(
                        rep_text, font_face, font_scale * 0.9, text_thickness
                    )
                    tx, ty = size
                    tx1 = x1
                    ty1 = max(0, y1 - ty - 6)
                    # Keep text within answer area bounds
                    answer_area_right = left_width + orig_w - 5
                    tx2 = min(answer_area_right, x1 + tx + 8)
                    ty2 = y1

                    cv2.rectangle(
                        cv_img,
                        (tx1 - 2, ty1),
                        (tx2, ty2),
                        (255, 255, 255),
                        thickness=-1,
                    )
                    cv2.putText(
                        cv_img,
                        rep_text,
                        (tx1, y1 - 4),
                        font_face,
                        font_scale * 0.9,
                        RED,
                        text_thickness,
                        cv2.LINE_AA,
                    )
                    found_rects.append(rect)

            # After drawing negative annotations, add ticks for ALL headings of good sections
            for sec in sections:
                pages = sec.get("page_numbers") or []
                if page_number not in pages:
                    continue

                sid = str(sec.get("id") or sec.get("section_id") or sec.get("title") or "")
                # Always draw ticks for headings/subheadings regardless of any
                # annotations marking the section as 'bad'. Only skip if we
                # cannot derive an identifier/title for the section.
                if not sid:
                    continue

                tick_drawn = False

                # Try 1: Use exact_ocr_heading if available
                exact_heading = sec.get("exact_ocr_heading") or ""
                if exact_heading:
                    heading_bbox = _find_heading_bbox_on_page(exact_heading, page_ocr)
                    if heading_bbox:
                        hx1, hy1, hx2, hy2 = _bbox_to_rect(heading_bbox, pad=4, w=orig_w, h=orig_h)
                        shifted = shift_rect((hx1, hy1, hx2, hy2))
                        draw_tick_at_rect(shifted)
                        tick_drawn = True

                # Try 2: Fall back to title
                if not tick_drawn:
                    title = sec.get("title") or ""
                    if title and title != exact_heading:
                        heading_bbox = _find_heading_bbox_on_page(title, page_ocr)
                        if heading_bbox:
                            hx1, hy1, hx2, hy2 = _bbox_to_rect(heading_bbox, pad=4, w=orig_w, h=orig_h)
                            shifted = shift_rect((hx1, hy1, hx2, hy2))
                            draw_tick_at_rect(shifted)
                            tick_drawn = True

                # Try 3: If still not found, draw tick on section region (first part of section content)
                if not tick_drawn:
                    sec_region = section_regions.get(sid)
                    if sec_region:
                        # Draw tick at the top-left of the section region
                        shifted = shift_rect(sec_region)
                        draw_tick_at_rect(shifted)
                        tick_drawn = True

                # Try 4: Last resort - search for any line containing key words from title
                if not tick_drawn and page_ocr:
                    title = sec.get("title") or ""
                    title_words = set(title.lower().split()[:3])  # Use first 3 words
                    title_words.discard("introduction")
                    title_words.discard("conclusion")

                    if title_words:
                        for line in page_ocr.get("lines", []):
                            line_text = (line.get("text") or "").lower()
                            line_words = set(line_text.split())

                            # If at least 2 words match and line is short (likely a heading)
                            overlap = len(title_words & line_words)
                            if overlap >= min(2, len(title_words)) and len(line_text) < 100:
                                line_bbox = line.get("bbox")
                                if line_bbox:
                                    hx1, hy1, hx2, hy2 = _bbox_to_rect(line_bbox, pad=4, w=orig_w, h=orig_h)
                                    shifted = shift_rect((hx1, hy1, hx2, hy2))
                                    draw_tick_at_rect(shifted)
                                    tick_drawn = True
                                    break

            # Add refined rubric summary on the last page (render from BOTTOM UP)
            if page_number == len(doc) and refined_summary:
                # Filter to only the 4 required points
                required_ids = ["argumentation_quality", "presentation", "contemporary_relevance", "length_completeness"]
                filtered_summary = [item for item in refined_summary if item.get("id") in required_ids]

                # Ensure we have exactly 4 items in the correct order
                ordered_summary = []
                for req_id in required_ids:
                    found = next((item for item in filtered_summary if item.get("id") == req_id), None)
                    if found:
                        ordered_summary.append(found)

                if ordered_summary:
                    # Start from BOTTOM of page and work upward
                    # Reserve space at bottom for summary annotations
                    bottom_margin = int(0.05 * h)
                    left_summary_y = h - bottom_margin
                    right_summary_y = h - bottom_margin

                    # Render items in REVERSE order (bottom to top)
                    # Items 0,1 on left; items 2,3 on right
                    # But we render them backwards so last item appears at bottom
                    for idx in range(len(ordered_summary) - 1, -1, -1):
                        item = ordered_summary[idx]
                        name = item.get("name", "")
                        rating = (item.get("rating") or "").capitalize()
                        comment = item.get("comment") or ""

                        # Truncate comment to max 80 characters to keep it concise
                        if len(comment) > 80:
                            comment = comment[:77] + "..."

                        header = f"{name} - {rating}"

                        if idx < 2:  # First two on left side
                            current_x1 = suggestion_x1
                            current_x2 = suggestion_x2
                            max_width = suggestion_max_width
                            current_y_base = left_summary_y
                        else:  # Last two on right side
                            current_x1 = comment_x
                            current_x2 = comment_x2 - 5
                            max_width = comment_max_width
                            current_y_base = right_summary_y

                        # Wrap header and comment
                        header_lines = _wrap_text_cv2(
                            header, max_width - 20, font_face, font_scale * 0.9, text_thickness
                        )
                        comment_lines = _wrap_text_cv2(
                            comment, max_width - 20, font_face, font_scale * 0.8, text_thickness
                        )

                        # Calculate total height needed for this box
                        total_lines = len(header_lines) + len(comment_lines)
                        box_height = int(total_lines * line_height * 1.0 + line_height * 1.5)

                        # Calculate box position (from bottom up)
                        box_end_y = current_y_base
                        box_start_y = max(margin, box_end_y - box_height)  # Don't go above top margin

                        # Skip this item if there's no space
                        if box_start_y >= box_end_y - int(line_height * 2):
                            continue

                        # Draw red box with safe coordinates
                        cv2.rectangle(
                            cv_img,
                            (current_x1 - 5, box_start_y),
                            (current_x2 + 5, box_end_y),
                            RED,
                            3,  # Box thickness
                        )

                        # Draw text from top of box, working down
                        text_y = box_start_y + int(line_height * 1.2)

                        # Draw header
                        for line in header_lines:
                            if text_y < box_end_y - int(line_height * 0.5):  # Ensure we don't overflow box
                                cv2.putText(
                                    cv_img,
                                    line,
                                    (current_x1, text_y),
                                    font_face,
                                    font_scale * 0.9,
                                    RED,
                                    text_thickness,
                                    cv2.LINE_AA,
                                )
                                text_y += int(line_height * 1.0)

                        # Draw comment
                        for line in comment_lines:
                            if text_y < box_end_y - int(line_height * 0.5):  # Ensure we don't overflow box
                                cv2.putText(
                                    cv_img,
                                    line,
                                    (current_x1, text_y),
                                    font_face,
                                    font_scale * 0.8,
                                    RED,
                                    text_thickness,
                                    cv2.LINE_AA,
                                )
                                text_y += int(line_height * 0.9)

                        # Update Y position for next item (move UP from current position)
                        if idx < 2:
                            left_summary_y = box_start_y - int(line_height * 1.0)
                        else:
                            right_summary_y = box_start_y - int(line_height * 1.0)

            # Check if image is too large BEFORE color conversion to prevent MemoryError
            # Large images can cause MemoryError when converting colors or to PIL Image
            # 268MB allocation failure suggests image is ~9000x9000 pixels or larger
            max_dimension = 4000  # Maximum dimension before downscaling
            h_img, w_img = cv_img.shape[:2]
            
            # Downscale BEFORE color conversion to reduce memory pressure
            if max(h_img, w_img) > max_dimension:
                # Calculate scale factor
                scale = max_dimension / max(h_img, w_img)
                new_w = int(w_img * scale)
                new_h = int(h_img * scale)
                # Downscale using high-quality interpolation
                cv_img = cv2.resize(cv_img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
                # Update dimensions after resize
                h_img, w_img = cv_img.shape[:2]
            
            # Convert BGR to RGB efficiently using cv2.cvtColor (more memory efficient than slicing)
            # This avoids creating a copy of the entire array
            cv_img_rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
            
            # Convert to PIL Image
            pil_result = Image.fromarray(cv_img_rgb)
            annotated_pages.append(pil_result)
            
            # Explicitly release memory after each page to prevent accumulation
            del pil_img, orig_cv, cv_img, cv_img_rgb, pil_result
            gc.collect()
            
            # Monitor memory usage periodically (every 5 pages)
            if (page_idx + 1) % 5 == 0:
                process_memory = _get_process_memory_mb()
                available_memory = _get_available_memory_mb()
                if process_memory and available_memory:
                    print(f"Memory status after page {page_number}: "
                          f"process={process_memory:.1f} MB, "
                          f"available={available_memory:.1f} MB")
                    # Warn if memory is getting low
                    if available_memory < 200.0:
                        print(f"WARNING: Low available memory ({available_memory:.1f} MB) "
                              f"after processing {page_number} pages")

        return annotated_pages
    finally:
        doc.close()  # Always close the document to release file handle
