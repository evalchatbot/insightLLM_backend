from typing import Any, Dict, List, Tuple, Optional
import re
import io

import cv2
import numpy as np
import fitz  # PyMuPDF
from PIL import Image


# ---------- OCR / GEOMETRY HELPERS ----------



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
    """
    Convert 4-point Vision bbox into (x1, y1, x2, y2) rect with padding.
    Clipped to image bounds.
    """
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
    """
    Naive text wrapping for cv2.putText: break text into lines that fit max_width_px.
    """
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
    """
    Try to find the heading line on this page that matches the given title.
    Uses fuzzy matching on OCR line text.
    Returns bbox (list of 4 (x,y) points) or None.
    """
    target = _normalize(title)
    if not target:
        return None

    best_bbox = None
    best_score = 0.0

    for line in page_ocr.get("lines", []):
        text = (line.get("text") or "").strip()
        if not text:
            continue
        candidate = text.lower()

        # Strong signals first
        if candidate == target:
            return line.get("bbox")

        if target in candidate or candidate in target:
            score = 1.0
        else:
            t_tokens = target.split()
            c_tokens = candidate.split()
            common = len(set(t_tokens) & set(c_tokens))
            score = common / max(len(t_tokens), 1)

        if score > best_score and score >= 0.6:
            best_score = score
            best_bbox = line.get("bbox")

    return best_bbox


def _find_line_bbox_by_sample(
    page_ocr: Dict[str, Any],
    sample_text: str,
) -> Optional[List[Tuple[int, int]]]:
    """
    Find a line bbox whose text best matches sample_text (for intro anchor, factual sentence, etc.)
    """
    target = _normalize(sample_text)
    if not target:
        return None

    best_bbox = None
    best_score = 0.0

    for line in page_ocr.get("lines", []):
        text = (line.get("text") or "").strip()
        if not text:
            continue
        candidate = text.lower()

        if candidate == target:
            return line.get("bbox")

        if target in candidate or candidate in target:
            score = 1.0
        else:
            t_tokens = target.split()
            c_tokens = candidate.split()
            common = len(set(t_tokens) & set(c_tokens))
            score = common / max(len(t_tokens), 1)

        if score > best_score and score >= 0.55:
            best_score = score
            best_bbox = line.get("bbox")

    return best_bbox


def _find_word_or_line_rect(
    page_ocr: Dict[str, Any],
    target_text: str,
    w: int,
    h: int,
) -> Optional[Tuple[int, int, int, int]]:
    """
    Improved:
      - Always try word-level on ALL tokens first.
      - For multi-word phrases, union the matched word boxes if possible.
      - When falling back to line-level, reject lines whose bbox is 'too big'
        (e.g., covers more than ~40% of the page height or width).
    """
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


def _find_factual_error_rect(
    page_ocr: Dict[str, Any],
    ann: Dict[str, Any],
    w: int,
    h: int,
) -> Optional[Tuple[int, int, int, int]]:
    """
    Locate the best bounding box for a factual_error annotation on this page.

    Uses multiple hints from the annotation:
      - target_sentence
      - target_sentence_start
      - context_before
      - context_after

    Strategy:
      1) Score each OCR line based on how well it matches these hints.
      2) Pick the highest-scoring reasonable line box.
      3) If nothing good is found, fall back to the older logic that uses
         _find_line_bbox_by_sample and _find_word_or_line_rect.
    """
    target_sentence = ann.get("target_sentence") or ""
    target_start = ann.get("target_sentence_start") or ""
    ctx_before = ann.get("context_before") or ""
    ctx_after = ann.get("context_after") or ""

    ts_norm = _normalize(target_sentence)
    ts_start_norm = _normalize(target_start)
    before_norm = _normalize(ctx_before)
    after_norm = _normalize(ctx_after)

    best_rect: Optional[Tuple[int, int, int, int]] = None
    best_score = 0.0

    # --- Pass 1: scored line search using all hints we have ---
    for line in page_ocr.get("lines", []):
        text = _normalize(line.get("text") or "")
        if not text:
            continue

        score = 0.0

        # Strong match on the sentence start
        if ts_start_norm and ts_start_norm in text:
            score += 2.0

        # Context before / after present near the sentence
        if before_norm and before_norm in text:
            score += 1.0
        if after_norm and after_norm in text:
            score += 1.0

        # Token overlap with full target sentence
        if ts_norm:
            ts_tokens = set(ts_norm.split())
            line_tokens = set(text.split())
            if ts_tokens:
                overlap = len(ts_tokens & line_tokens) / max(len(ts_tokens), 1)
                score += overlap  # up to +1.0

        if score <= 0.0:
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

        if score > best_score:
            best_score = score
            best_rect = (x1, y1, x2, y2)

    if best_rect is not None:
        return best_rect

    # --- Pass 2: fall back to the existing behaviour (for safety) ---

    rect: Optional[Tuple[int, int, int, int]] = None
    line_bbox = None

    # Old logic: try the full sentence, then a shortened sample
    if target_sentence:
        line_bbox = _find_line_bbox_by_sample(page_ocr, target_sentence)
        if not line_bbox:
            words = target_sentence.split()
            if words:
                short_sample = " ".join(words[: min(len(words), 12)])
                line_bbox = _find_line_bbox_by_sample(page_ocr, short_sample)

    if line_bbox:
        x1, y1, x2, y2 = _bbox_to_rect(line_bbox, pad=3, w=w, h=h)
        rect = (x1, y1, x2, y2)
    else:
        # Fall back to phrase / start-based search using the existing helper
        key_phrase = ""
        if target_sentence:
            words = target_sentence.split()
            if words:
                key_phrase = " ".join(words[: min(len(words), 6)])
        if not key_phrase and target_start:
            key_phrase = target_start

        if key_phrase:
            rect = _find_word_or_line_rect(
                page_ocr,
                key_phrase,
                w=w,
                h=h,
            )

    return rect



def _compute_section_region_on_page(
    section: Dict[str, Any],
    page_number: int,
    ocr_data: Dict[str, Any],
    orig_w: int,
    orig_h: int,
    all_sections: List[Dict[str, Any]],
) -> Optional[Tuple[int, int, int, int]]:
    """
    Compute a bounding rectangle for the *entire section* content on this page:
      - top = heading bbox top (or top of page if not found),
      - bottom = next section's heading top on this page (or page bottom),
      - x-range = min/max x of all lines between those y-bounds.
    """
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
) -> List[Image.Image]:
    """
    Create annotated versions of the answer pages.

    Annotation behaviour:
      - introduction_comment → big red box for whole introduction + red comment in side padding
      - heading_issue (negative) → red box on heading line + red comment in side padding
      - factual_error → red box on sentence line + red comment in side padding
      - grammar_language → small red box on word/sentence + red correction near box (no side comment)
      - repetition → red box on repeated section region, text "repeated on page X" in red near box
      - For each 'correct' section on a page (no negative annotation on that page):
          → draw a red ✓ near the heading and near the section body region.
    """
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

        # Extended canvas: [answer][right margin]
        side_width = int(0.40 * orig_w)
        new_w = orig_w + side_width
        h = orig_h
        margin = int(0.03 * orig_w)

        cv_img = np.full((h, new_w, 3), 255, dtype=np.uint8)
        cv_img[:, 0:orig_w, :] = orig_cv

        # Right-side padding area
        side_x1 = orig_w
        side_x2 = new_w - margin
        comment_x = side_x1 + margin
        comment_y = margin + int(0.05 * h)

        page_ocr = ocr_pages_by_num.get(page_number)
        if not page_ocr:
            annotated_pages.append(Image.fromarray(cv_img[:, :, ::-1]))
            continue

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

        # Draw config based on page size (bigger fonts + thicker lines)
        font_scale = max(0.9, min(orig_w, h) / 1200.0)
        text_thickness = 3
        box_thickness = 5
        line_height = int(32 * font_scale)
        max_text_width = side_x2 - comment_x - 10

        def add_side_comment(header: str, text: str):
            nonlocal comment_y
            # Header (red, bold-ish)
            for line in _wrap_text_cv2(
                header, max_text_width, font_face, font_scale * 0.95, text_thickness
            ):
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
                    bullet, max_text_width, font_face, font_scale * 0.85, text_thickness
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
            cy = max(10, y1 - 8)

            size, _ = cv2.getTextSize(
                correction, font_face, font_scale * 0.85, text_thickness
            )
            tx, ty = size
            bg_x2 = min(orig_w - 5, cx + tx + 8)
            bg_y2 = max(0, cy - ty - 6)

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
            Draw a red line from the annotation box to the side comment.
            """
            x1, y1, x2, y2 = rect
            rect_center_y = (y1 + y2) // 2
            rect_right_x = min(orig_w - int(0.02 * orig_w), x2 + 10)
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
            tick_y = max(20, y1 + int(0.05 * h))

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

        # Draw all negative/problem annotations in red
        for ann in page_anns:
            atype = (ann.get("type") or "").lower()
            rubric_point = ann.get("rubric_point") or ""

            # 1) Introduction comment – big box over intro + side comment
            if atype == "introduction_comment":
                target_sec_id = str(ann.get("target_section_id") or "")
                sec_region = section_regions.get(target_sec_id)
                if not sec_region:
                    continue
                x1, y1, x2, y2 = sec_region
                cv2.rectangle(cv_img, (x1, y1), (x2, y2), RED, box_thickness)

                header = f"[Introduction] ({rubric_point})".strip()
                body = ann.get("comment") or ""
                block_height = int(line_height * 5)
                if comment_y + block_height > h - margin:
                    comment_y = h - margin - block_height
                comment_block_center_y = comment_y + block_height // 2
                draw_connector((x1, y1, x2, y2), comment_block_center_y)
                add_side_comment(header, body)

            # 2) Heading issue – box on heading line (negative only) + side comment
            elif atype == "heading_issue":
                sentiment = (ann.get("sentiment") or "").lower()
                if sentiment not in ("negative", "weak", "problematic"):
                    continue
                section_id = str(ann.get("section_id") or "")
                sec = sections_by_id.get(section_id)
                if not sec:
                    continue
                title = sec.get("title") or ""
                heading_bbox = _find_heading_bbox_on_page(title, page_ocr)
                if not heading_bbox:
                    continue
                x1, y1, x2, y2 = _bbox_to_rect(heading_bbox, pad=4, w=orig_w, h=orig_h)
                cv2.rectangle(cv_img, (x1, y1), (x2, y2), RED, box_thickness)

                header = f"[Heading: {title}] ({rubric_point})".strip()
                body = ann.get("comment") or ""
                block_height = int(line_height * 4)
                if comment_y + block_height > h - margin:
                    comment_y = h - margin - block_height
                comment_block_center_y = comment_y + block_height // 2
                draw_connector((x1, y1, x2, y2), comment_block_center_y)
                add_side_comment(header, body)

            # 3) Factual error – box on sentence + side comment
            elif atype == "factual_error":
                rect = _find_factual_error_rect(
                    page_ocr=page_ocr,
                    ann=ann,
                    w=orig_w,
                    h=orig_h,
                )
                if not rect:
                    continue

                x1, y1, x2, y2 = rect
                cv2.rectangle(cv_img, (x1, y1), (x2, y2), RED, box_thickness)

                header = f"[Factual Accuracy] ({rubric_point})".strip()
                body = ann.get("comment") or ""
                block_height = int(line_height * 4)
                if comment_y + block_height > h - margin:
                    comment_y = h - margin - block_height
                comment_block_center_y = comment_y + block_height // 2
                draw_connector((x1, y1, x2, y2), comment_block_center_y)
                add_side_comment(header, body)

            # 4) Grammar & language – small box + inline correction (no side comment)
            elif atype == "grammar_language":
                target_word_or_sentence = ann.get("target_word_or_sentence") or ""
                if not target_word_or_sentence:
                    continue
                rect = _find_word_or_line_rect(
                    page_ocr,
                    target_word_or_sentence,
                    w=orig_w,
                    h=orig_h,
                )
                if not rect:
                    continue
                x1, y1, x2, y2 = rect
                cv2.rectangle(cv_img, (x1, y1), (x2, y2), RED, box_thickness)
                correction = ann.get("correction") or ""
                draw_correction_near_box(rect, correction)

            # 5) Repetition – box on repeated section region, text "repeated on page X"
            elif atype == "repetition":
                section_id = str(ann.get("section_id") or "")
                original_page = ann.get("original_page")
                sec_region = section_regions.get(section_id)
                if not sec_region:
                    continue
                x1, y1, x2, y2 = sec_region
                cv2.rectangle(cv_img, (x1, y1), (x2, y2), RED, box_thickness)

                rep_text = (
                    f"repeated from page {original_page}"
                    if original_page
                    else "repeated"
                )
                size, _ = cv2.getTextSize(
                    rep_text, font_face, font_scale * 0.9, text_thickness
                )
                tx, ty = size
                tx1 = x1
                ty1 = max(0, y1 - ty - 6)
                tx2 = min(orig_w - 5, x1 + tx + 8)
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

        # After drawing negative annotations, add ticks for "good" sections on this page
        for sec in sections:
            pages = sec.get("page_numbers") or []
            if page_number not in pages:
                continue

            sid = str(sec.get("id") or sec.get("section_id") or sec.get("title") or "")
            if not sid or sid in bad_section_ids:
                continue

            title = sec.get("title") or ""

            # Tick at heading line if we can find it
            heading_bbox = _find_heading_bbox_on_page(title, page_ocr)
            if heading_bbox:
                hx1, hy1, hx2, hy2 = _bbox_to_rect(heading_bbox, pad=4, w=orig_w, h=orig_h)
                draw_tick_at_rect((hx1, hy1, hx2, hy2))

            # Tick at section region if known
            region = section_regions.get(sid)
            if region:
                draw_tick_at_rect(region)

        annotated_pages.append(Image.fromarray(cv_img[:, :, ::-1]))

    return annotated_pages
