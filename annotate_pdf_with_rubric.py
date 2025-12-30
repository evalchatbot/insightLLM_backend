from typing import Any, Dict, List, Tuple, Optional
import io
import gc

import cv2
import numpy as np
import fitz
from PIL import Image


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
      - repetition → margin comment only (no box or connector)
      - For each 'correct' section on a page (no negative annotation on that page):
          → draw a red ✓ near the heading and near the section body region.
    """
    page_suggestions = page_suggestions or []
    refined_summary = refined_summary or []
    # Load PDF pages via PyMuPDF
    doc = fitz.open(pdf_path)
    pil_pages: List[Image.Image] = []
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        pil_img = Image.open(io.BytesIO(img_bytes))
        pil_pages.append(pil_img)

    annotated_pages: List[Image.Image] = []

    # Precompute OCR by page
    ocr_pages_by_num: Dict[int, Dict[str, Any]] = {
        p.get("page_number"): p for p in ocr_data.get("pages", [])
    }

    # Map sections by id for quick lookup
    sections_by_id: Dict[str, Dict[str, Any]] = {}
    for sec in sections:
        sid = sec.get("id") or sec.get("section_id") or sec.get("title")
        if sid:
            sections_by_id[str(sid)] = sec

    # Drawing constants
    font_face = cv2.FONT_HERSHEY_SIMPLEX
    RED = (0, 0, 255)

    for page_idx, pil_img in enumerate(pil_pages):
        page_number = page_idx + 1
        orig_cv = np.array(pil_img)[:, :, ::-1].copy()
        orig_h, orig_w, _ = orig_cv.shape
        content_h = orig_h
        min_page_height = 3500

        # Extended canvas: [left margin][answer][right margin]
        left_width = int(0.40 * orig_w)
        right_width = int(0.40 * orig_w)
        new_w = left_width + orig_w + right_width
        h = max(orig_h, min_page_height)
        margin = int(0.03 * orig_w)
        y_offset = (h - content_h) // 2

        cv_img = np.full((h, new_w, 3), 255, dtype=np.uint8)
        # Place answer in the center
        cv_img[
            y_offset:y_offset + content_h,
            left_width:left_width + orig_w,
            :
        ] = orig_cv

        # Left-side padding area for improvement suggestions
        suggestion_x1 = margin
        suggestion_x2 = left_width - margin
        suggestion_y = margin

        # Right-side padding area for error/issue annotations
        comment_x1 = left_width + orig_w
        comment_x2 = new_w - margin
        comment_x = comment_x1 + margin
        comment_y = margin
        comment_boxes: List[Tuple[int, int, int, int]] = []

        # Get suggestions for this page
        page_suggestion_data = None
        for ps in page_suggestions:
            if ps.get("page") == page_number:
                page_suggestion_data = ps
                break

        page_ocr = ocr_pages_by_num.get(page_number)
        if not page_ocr:
            annotated_pages.append(Image.fromarray(cv_img[:, :, ::-1]))
            continue

        # Draw config based on page size (bigger fonts + thicker lines)
        font_scale = max(0.9, min(orig_w, content_h) / 1200.0)
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
                comment_boxes.append(
                    (suggestion_x1 - 5, box_start_y, suggestion_x2 + 5, box_start_y + box_height)
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

        suggestion_end_y = max(suggestion_y, margin)

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
            return (x1 + left_width, y1 + y_offset, x2 + left_width, y2 + y_offset)

        def _rects_overlap(
            a: Tuple[int, int, int, int],
            b: Tuple[int, int, int, int],
            pad: int = 0,
        ) -> bool:
            ax1, ay1, ax2, ay2 = a
            bx1, by1, bx2, by2 = b
            return not (
                ax2 + pad < bx1
                or ax1 - pad > bx2
                or ay2 + pad < by1
                or ay1 - pad > by2
            )

        def _find_box_in_column(
            x1: int,
            x2: int,
            start_y: int,
            min_y: int,
            max_y: int,
            height: int,
        ) -> Optional[Tuple[int, int, int, int]]:
            y = max(start_y, min_y)
            while y + height <= max_y:
                candidate = (x1, y, x2, y + height)
                overlapping = [
                    rect for rect in comment_boxes
                    if _rects_overlap(candidate, rect, pad=4)
                ]
                if not overlapping:
                    return candidate
                y = max(rect[3] for rect in overlapping) + int(line_height * 0.6)
            return None

        def add_side_comment(
            header: str,
            text: str,
            draw_box: bool = True,
        ) -> Tuple[Tuple[int, int, int, int], bool]:
            nonlocal comment_y
            def build_lines(max_width: int) -> Tuple[List[str], List[str], int]:
                header_lines = _wrap_text_cv2(
                    header, max_width - 20, font_face, font_scale * 0.95, text_thickness
                )
                body_lines: List[str] = []
                if text:
                    bullet = "- " + text
                    body_lines = _wrap_text_cv2(
                        bullet, max_width - 20, font_face, font_scale * 0.85, text_thickness
                    )
                height = int(
                    len(header_lines) * line_height * 1.2
                    + len(body_lines) * line_height * 1.0
                    + line_height * 1.4
                )
                return header_lines, body_lines, height

            right_x1 = comment_x - 10
            right_x2 = comment_x2 - 5
            right_min_y = margin
            right_max_y = h - margin
            preferred_y = max(comment_y - int(line_height * 1.0), right_min_y)

            header_lines, body_lines, box_height = build_lines(comment_max_width)
            box = _find_box_in_column(
                right_x1,
                right_x2,
                preferred_y,
                right_min_y,
                right_max_y,
                box_height,
            )
            if not box:
                box = _find_box_in_column(
                    right_x1,
                    right_x2,
                    right_min_y,
                    right_min_y,
                    right_max_y,
                    box_height,
                )

            if not box:
                header_lines, body_lines, box_height = build_lines(suggestion_max_width)
                left_x1 = suggestion_x1 - 5
                left_x2 = suggestion_x2 + 5
                left_min_y = max(suggestion_end_y, margin)
                left_max_y = h - margin
                box = _find_box_in_column(
                    left_x1,
                    left_x2,
                    left_min_y,
                    left_min_y,
                    left_max_y,
                    box_height,
                )

            if not box:
                y1 = max(right_min_y, right_max_y - box_height)
                box = (right_x1, y1, right_x2, min(right_max_y, y1 + box_height))

            comment_boxes.append(box)
            box_x1, box_y1, box_x2, box_y2 = box

            if draw_box:
                # Draw red box around the entire comment
                cv2.rectangle(
                    cv_img,
                    (box_x1, box_y1),
                    (box_x2, box_y2),
                    RED,
                    3,  # Box thickness
                )

            text_x = box_x1 + 10
            text_y = box_y1 + int(line_height * 1.0)

            # Header (red, bold-ish)
            for line in header_lines:
                if text_y > box_y2 - int(line_height * 0.5):
                    break
                cv2.putText(
                    cv_img,
                    line,
                    (text_x, text_y),
                    font_face,
                    font_scale * 0.95,
                    RED,
                    text_thickness,
                    cv2.LINE_AA,
                )
                text_y += int(line_height * 1.2)

            # Body text (red)
            for line in body_lines:
                if text_y > box_y2 - int(line_height * 0.5):
                    break
                cv2.putText(
                    cv_img,
                    line,
                    (text_x, text_y),
                    font_face,
                    font_scale * 0.85,
                    RED,
                    text_thickness,
                    cv2.LINE_AA,
                )
                text_y += int(line_height * 1.0)

            comment_y = max(comment_y, box_y2 + int(line_height * 0.6))
            is_right = box_x1 >= comment_x - 5
            return (box_x1, box_y1, box_x2, box_y2), is_right

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
            target_x: int,
            target_y_center: int,
        ):
            """
            Draw a red line from the annotation box to the comment box.
            """
            x1, y1, x2, y2 = rect
            rect_center_y = (y1 + y2) // 2
            rect_right_x = min(left_width + orig_w - int(0.02 * orig_w), x2 + 10)
            cv2.line(
                cv_img,
                (rect_right_x, rect_center_y),
                (target_x, target_y_center),
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
            tick_y = max(35, y1 + int(0.05 * content_h))  # Increased minimum to 35 to account for upward stroke

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
                intro_rect = None
                if intro_sections:
                    intro_sec = intro_sections[0]
                    sid = str(intro_sec.get("id") or intro_sec.get("section_id") or intro_sec.get("title"))
                    intro_rect = section_regions.get(sid)

                if not intro_rect and target_text:
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
                        rect = _find_word_or_line_rect(
                            page_ocr=page_ocr,
                            target_text=target_text,
                            w=orig_w,
                            h=orig_h,
                        )
                    intro_rect = rect

                if not intro_rect:
                    intro_rect = (0, 0, orig_w - 1, min(orig_h - 1, int(0.22 * content_h)))

                x1, y1, x2, y2 = intro_rect
                x1 = 0
                x2 = orig_w - 1
                pad_top = int(0.03 * content_h)
                pad_bottom = int(0.08 * content_h)
                y1 = max(0, y1 - pad_top)
                y2 = min(content_h - 1, y2 + pad_bottom)

                shifted = shift_rect((x1, y1, x2, y2))
                cv2.rectangle(cv_img, (shifted[0], shifted[1]), (shifted[2], shifted[3]), RED, box_thickness)

                header = f"[Introduction] ({rubric_point})".strip()
                body = comment
                comment_box, comment_on_right = add_side_comment(header, body)
                if comment_on_right:
                    draw_connector(
                        shifted,
                        comment_box[0],
                        (comment_box[1] + comment_box[3]) // 2,
                    )
                found_rects.append((x1, y1, x2, y2))  # Store original for duplicate detection

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
                comment_box, comment_on_right = add_side_comment(header, body)
                if comment_on_right:
                    draw_connector(
                        shifted,
                        comment_box[0],
                        (comment_box[1] + comment_box[3]) // 2,
                    )
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
                comment_box, comment_on_right = add_side_comment(header, body)
                if comment_on_right:
                    draw_connector(
                        shifted,
                        comment_box[0],
                        (comment_box[1] + comment_box[3]) // 2,
                    )
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
                header = f"[Repetition] ({rubric_point})".strip()
                body_parts = []
                if comment:
                    body_parts.append(comment)
                if correction:
                    body_parts.append(f"Suggestion: {correction}")
                body = " ".join(body_parts).strip() or "Repetition detected"
                add_side_comment(header, body, draw_box=False)

        # Add heading comments for every section on this page
        for sec in sections:
            pages = sec.get("page_numbers") or []
            if page_number not in pages:
                continue

            title_text = (sec.get("title") or "").strip()
            exact_heading = sec.get("exact_ocr_heading") or ""
            heading_text = title_text or exact_heading
            if not heading_text:
                continue
            heading_norm = heading_text.strip().lower()
            if "introduction" in heading_norm or "conclusion" in heading_norm:
                continue

            heading_comment = (sec.get("comment") or "").strip()
            if not heading_comment:
                heading_comment = "Heading detected."

            header = f"[Heading] {heading_text}"
            comment_box, comment_on_right = add_side_comment(header, heading_comment)

            heading_bbox = _find_heading_bbox_on_page(exact_heading or heading_text, page_ocr)
            if heading_bbox and comment_on_right:
                hx1, hy1, hx2, hy2 = _bbox_to_rect(heading_bbox, pad=4, w=orig_w, h=orig_h)
                shifted = shift_rect((hx1, hy1, hx2, hy2))
                draw_connector(
                    shifted,
                    comment_box[0],
                    (comment_box[1] + comment_box[3]) // 2,
                )

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
        if page_number == len(pil_pages) and refined_summary:
            # Filter to only the 4 required points
            required_ids = ["argumentation_quality", "presentation", "contemporary_relevance", "length_completeness"]
            id_to_name = {
                "argumentation_quality": "Argumentation Quality",
                "presentation": "Presentation Quality",
                "contemporary_relevance": "Contemporary Relevance",
                "length_completeness": "Length & Completeness",
            }
            filtered_summary = [item for item in refined_summary if item.get("id") in required_ids]

            # Ensure we have exactly 4 items in the correct order
            ordered_summary = []
            for req_id in required_ids:
                found = next((item for item in filtered_summary if item.get("id") == req_id), None)
                if found:
                    ordered_summary.append(found)
                else:
                    ordered_summary.append(
                        {
                            "id": req_id,
                            "name": id_to_name.get(req_id, req_id),
                            "rating": "average",
                            "comment": "Not provided",
                        }
                    )

            if ordered_summary:
                # Start from BOTTOM of page and work upward
                # Reserve space at bottom for summary annotations
                bottom_margin = int(0.07 * h)
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

                    # Keep full comment text for summary annotations

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

                    def build_summary_lines(
                        max_width: int,
                    ) -> Tuple[List[str], List[str], int]:
                        header_lines = _wrap_text_cv2(
                            header, max_width - 20, font_face, font_scale * 0.9, text_thickness
                        )
                        comment_lines = _wrap_text_cv2(
                            comment, max_width - 20, font_face, font_scale * 0.8, text_thickness
                        )
                        total_lines = len(header_lines) + len(comment_lines)
                        box_height = int(total_lines * line_height * 1.15 + line_height * 2.0)
                        return header_lines, comment_lines, box_height

                    def place_summary_box(
                        x1: int,
                        x2: int,
                        start_y: int,
                        box_height: int,
                    ) -> Optional[Tuple[int, int, int, int]]:
                        box_x1 = x1 - 5
                        box_x2 = x2 + 5
                        box_end_y = min(start_y, h - margin)
                        box_start_y = box_end_y - box_height

                        if box_start_y < margin:
                            return None

                        while True:
                            candidate = (box_x1, box_start_y, box_x2, box_end_y)
                            overlaps = [
                                rect for rect in comment_boxes
                                if _rects_overlap(candidate, rect, pad=4)
                            ]
                            if not overlaps:
                                return candidate
                            top_overlap = min(rect[1] for rect in overlaps)
                            box_end_y = top_overlap - int(line_height * 0.6)
                            box_start_y = box_end_y - box_height
                            if box_start_y < margin:
                                return None

                    # Try preferred column, then fallback to the other column
                    preferred_width = current_x2 - current_x1
                    header_lines, comment_lines, box_height = build_summary_lines(preferred_width)
                    candidate = place_summary_box(current_x1, current_x2, current_y_base, box_height)
                    placed_on_left = idx < 2
                    if not candidate:
                        if idx < 2:
                            alt_x1 = comment_x
                            alt_x2 = comment_x2 - 5
                            header_lines, comment_lines, box_height = build_summary_lines(alt_x2 - alt_x1)
                            candidate = place_summary_box(alt_x1, alt_x2, right_summary_y, box_height)
                            placed_on_left = False
                        else:
                            alt_x1 = suggestion_x1
                            alt_x2 = suggestion_x2
                            header_lines, comment_lines, box_height = build_summary_lines(alt_x2 - alt_x1)
                            candidate = place_summary_box(alt_x1, alt_x2, left_summary_y, box_height)
                            placed_on_left = True

                    if not candidate:
                        continue

                    box_x1, box_start_y, box_x2, box_end_y = candidate

                    # Draw red box with safe coordinates
                    cv2.rectangle(
                        cv_img,
                        (box_x1, box_start_y),
                        (box_x2, box_end_y),
                        RED,
                        3,  # Box thickness
                    )
                    comment_boxes.append((box_x1, box_start_y, box_x2, box_end_y))

                    # Draw text from top of box, working down
                    text_x = box_x1 + 10
                    text_y = box_start_y + int(line_height * 1.3)

                    # Draw header
                    for line in header_lines:
                        if text_y < box_end_y - int(line_height * 0.5):  # Ensure we don't overflow box
                            cv2.putText(
                                cv_img,
                                line,
                                (text_x, text_y),
                                font_face,
                                font_scale * 0.9,
                                RED,
                                text_thickness,
                                cv2.LINE_AA,
                            )
                            text_y += int(line_height * 1.1)

                    # Draw comment
                    for line in comment_lines:
                        if text_y < box_end_y - int(line_height * 0.5):  # Ensure we don't overflow box
                            cv2.putText(
                                cv_img,
                                line,
                                (text_x, text_y),
                                font_face,
                                font_scale * 0.8,
                                RED,
                                text_thickness,
                                cv2.LINE_AA,
                            )
                            text_y += int(line_height * 1.0)

                    # Update Y position for next item (move UP from current position)
                    if placed_on_left:
                        left_summary_y = box_start_y - int(line_height * 1.4)
                    else:
                        right_summary_y = box_start_y - int(line_height * 1.4)

        annotated_pages.append(Image.fromarray(cv_img[:, :, ::-1]))

        # Free memory every 10 pages to prevent memory accumulation with large PDFs
        if (page_idx + 1) % 10 == 0:
            del cv_img, orig_cv
            gc.collect()

    return annotated_pages
