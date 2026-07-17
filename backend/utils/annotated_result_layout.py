"""
Shared visual primitives for annotated evaluation result pages.

Matches rubric-annotation-component.html:
  cream #F2EDE3, paper cards, Syne/DM Sans/Cormorant typography,
  elbow connectors, masthead + footer on every page.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Exact palette from HTML (stored as OpenCV BGR)
# ---------------------------------------------------------------------------
CRIMSON_BGR: Tuple[int, int, int] = (45, 39, 193)       # #C1272D
INK_BGR: Tuple[int, int, int] = (26, 26, 26)            # #1A1A1A
INK_SOFT_BGR: Tuple[int, int, int] = (66, 70, 74)       # #4a4642
CREAM_BGR: Tuple[int, int, int] = (227, 237, 242)       # #F2EDE3
PAPER_BGR: Tuple[int, int, int] = (249, 253, 255)       # #FFFDF9
CITE_BGR: Tuple[int, int, int] = (121, 133, 138)        # #8a8579
LINE_BGR: Tuple[int, int, int] = (214, 214, 214)        # ~rgba(26,26,26,.14) on cream
STRENGTH_BGR: Tuple[int, int, int] = (107, 138, 122)    # #7a8a6b
SHADOW_BGR: Tuple[int, int, int] = (200, 205, 210)
WHITE_BGR: Tuple[int, int, int] = (255, 255, 255)

# Back-compat aliases used by older call sites / tests
TEXT_DARK_BGR = INK_BGR
TEXT_MUTED_BGR = INK_SOFT_BGR
RED_ACCENT_BGR = CRIMSON_BGR
RED_SOFT_BGR = CRIMSON_BGR
GREEN_REPHRASE_BGR = STRENGTH_BGR
LEFT_ACCENT_BGR = INK_BGR
CONNECTOR_LEFT_BGR = INK_BGR
CONNECTOR_RIGHT_BGR = CRIMSON_BGR

FONT_FACE = cv2.FONT_HERSHEY_SIMPLEX
Rect = Tuple[int, int, int, int]
Color = Tuple[int, int, int]
Rgb = Tuple[int, int, int]

_FONTS_DIR = os.path.join(os.path.dirname(__file__), "report_assets", "fonts")
_WIN_FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


def _bgr_to_rgb(c: Color) -> Rgb:
    return (int(c[2]), int(c[1]), int(c[0]))


def _find_font(*names: str) -> Optional[str]:
    for name in names:
        for base in (_FONTS_DIR, _WIN_FONTS):
            path = os.path.join(base, name)
            if os.path.isfile(path):
                return path
    return None


@lru_cache(maxsize=64)
def _load_font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    """
    kind: syne | cormorant | cormorant_italic | dm
    """
    size = max(8, int(size))
    mapping = {
        "syne": ("Syne.ttf", "segoeuib.ttf", "arialbd.ttf"),
        "cormorant": ("CormorantGaramond.ttf", "georgia.ttf", "times.ttf"),
        "cormorant_italic": ("CormorantGaramond.ttf", "georgiai.ttf", "timesi.ttf"),
        "dm": ("DMSans.ttf", "segoeui.ttf", "calibri.ttf", "arial.ttf"),
    }
    candidates = mapping.get(kind, mapping["dm"])
    path = _find_font(*candidates)
    if path:
        try:
            font = ImageFont.truetype(path, size)
            # Prefer heavier optical size when variable font supports it
            try:
                if kind == "syne" and hasattr(font, "set_variation_by_axes"):
                    font.set_variation_by_axes({"wght": 800})
                elif kind == "cormorant" and hasattr(font, "set_variation_by_axes"):
                    font.set_variation_by_axes({"wght": 600})
                elif kind == "cormorant_italic" and hasattr(font, "set_variation_by_axes"):
                    font.set_variation_by_axes({"wght": 500})
                elif kind == "dm" and hasattr(font, "set_variation_by_axes"):
                    font.set_variation_by_axes({"wght": 400})
            except Exception:
                pass
            return font
        except Exception:
            pass
    return ImageFont.load_default()


@dataclass
class TextSegment:
    text: str
    color: Color = INK_SOFT_BGR
    is_header: bool = False
    scale_mul: float = 1.0
    thickness_add: int = 0
    is_cite: bool = False


@dataclass
class CardContent:
    """Structured card content without changing source feedback text."""

    category: str
    title: str
    body_segments: List[TextSegment] = field(default_factory=list)
    accent: str = "left"  # left=suggestion, right=issue
    num: int = 0
    cite: str = ""
    card_type: str = "suggestion"  # suggestion | issue | strength


def create_cream_canvas(width: int, height: int) -> np.ndarray:
    return np.full((max(1, int(height)), max(1, int(width)), 3), CREAM_BGR, dtype=np.uint8)


def ensure_canvas_height(
    canvas: np.ndarray,
    required_h: int,
    fill_bgr: Color = CREAM_BGR,
) -> np.ndarray:
    h, w = canvas.shape[:2]
    needed = int(required_h)
    if needed <= h:
        return canvas
    grown = np.full((needed, w, 3), fill_bgr, dtype=np.uint8)
    grown[:h, :, :] = canvas
    return grown


def header_height(canvas_w: int) -> int:
    return max(70, int(0.055 * canvas_w))


def footer_height(canvas_w: int) -> int:
    return max(48, int(0.038 * canvas_w))


def page_label_height(canvas_w: int) -> int:
    return max(36, int(0.028 * canvas_w))


def content_top_offset(canvas_w: int) -> int:
    """Y where script/cards begin (below masthead + page label)."""
    return header_height(canvas_w) + page_label_height(canvas_w) + max(18, int(0.012 * canvas_w))


def content_bottom_reserve(canvas_w: int) -> int:
    return footer_height(canvas_w) + max(16, int(0.01 * canvas_w))


def paste_script_with_shadow(
    canvas: np.ndarray,
    script_bgr: np.ndarray,
    left_width: int,
    y_offset: int,
    shadow_offset: int = 8,
) -> np.ndarray:
    sh, sw = script_bgr.shape[:2]
    shadow = max(2, int(shadow_offset))
    required_h = y_offset + sh + shadow + 4
    canvas = ensure_canvas_height(canvas, required_h)

    # Soft drop shadow (HTML: 0 24px 50px -26px rgba(0,0,0,.35))
    sx1 = left_width + shadow
    sy1 = y_offset + shadow
    sx2 = left_width + sw + shadow
    sy2 = y_offset + sh + shadow
    cv2.rectangle(canvas, (sx1, sy1), (sx2, sy2), SHADOW_BGR, thickness=-1)

    # Paper mat around script edge (subtle)
    pad = max(2, shadow // 2)
    cv2.rectangle(
        canvas,
        (left_width - pad, y_offset - pad),
        (left_width + sw + pad, y_offset + sh + pad),
        PAPER_BGR,
        thickness=-1,
    )
    canvas[y_offset : y_offset + sh, left_width : left_width + sw] = script_bgr
    return canvas


def _pil_text_width(font: ImageFont.ImageFont, text: str) -> int:
    if hasattr(font, "getlength"):
        try:
            return int(font.getlength(text))
        except Exception:
            pass
    bbox = font.getbbox(text or " ")
    return max(1, bbox[2] - bbox[0])


def _pil_text_height(font: ImageFont.ImageFont) -> int:
    bbox = font.getbbox("Ag")
    return max(1, bbox[3] - bbox[1])


def wrap_text_pil(text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    words = (text or "").split()
    if not words:
        return []
    lines: List[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if _pil_text_width(font, trial) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def wrap_text(
    text: str,
    max_width_px: int,
    font_scale: float,
    thickness: int = 1,
    font_face: int = FONT_FACE,
) -> List[str]:
    """Legacy OpenCV wrap kept for tests / callers."""
    words = (text or "").split()
    if not words:
        return []
    lines: List[str] = []
    current = ""
    for word in words:
        trial = (current + " " + word).strip()
        (tw, _), _ = cv2.getTextSize(trial, font_face, font_scale, thickness)
        if tw <= max_width_px or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _line_metrics(font_scale: float, thickness: int) -> Tuple[int, int]:
    (tw, th), baseline = cv2.getTextSize("Ag", FONT_FACE, font_scale, thickness)
    return th, baseline


def _card_fonts(box_width: int, font_scale: float):
    # Scale relative to card width so it reads like the HTML at PDF DPI
    base = max(0.7, min(1.4, font_scale)) * max(0.85, min(1.35, box_width / 320.0))
    kicker = _load_font("syne", int(11 * base))
    num = _load_font("syne", int(10 * base))
    title = _load_font("cormorant", int(22 * base))
    # Body matches left-side card copy size; cite/rephrased uses the same size in black
    body = _load_font("dm", int(16 * base))
    cite = _load_font("dm", int(16 * base))
    return kicker, num, title, body, cite


def measure_card_height(
    content: CardContent,
    box_width: int,
    font_scale: float,
    *,
    pad_x: Optional[int] = None,
    pad_y: Optional[int] = None,
    line_gap: Optional[int] = None,
) -> int:
    pad_x = pad_x if pad_x is not None else max(14, int(16 * font_scale))
    pad_y = pad_y if pad_y is not None else max(14, int(16 * font_scale))
    rail = max(3, int(3 * font_scale))
    inner_w = max(40, box_width - pad_x * 2 - rail)
    kicker_f, num_f, title_f, body_f, cite_f = _card_fonts(box_width, font_scale)

    h = pad_y
    # num + kicker row
    h += max(_pil_text_height(kicker_f), int(20 * font_scale)) + int(9 * font_scale)
    # title
    for _ in wrap_text_pil(content.title or "", title_f, inner_w):
        h += _pil_text_height(title_f) + int(3 * font_scale)
    h += int(7 * font_scale)
    # body
    for seg in content.body_segments:
        if seg.is_cite:
            continue
        for raw in str(seg.text or "").splitlines() or [""]:
            raw = raw.strip()
            if not raw:
                h += int(6 * font_scale)
                continue
            for _ in wrap_text_pil(raw, body_f, inner_w):
                h += int(_pil_text_height(body_f) * 1.55)
    # cite
    cite = (content.cite or "").strip()
    if not cite:
        for seg in content.body_segments:
            if seg.is_cite and seg.text.strip():
                cite = seg.text.strip()
                break
    if cite:
        h += int(10 * font_scale) + 1  # dashed rule
        for _ in wrap_text_pil(cite, cite_f, inner_w):
            h += int(_pil_text_height(cite_f) * 1.55)
    h += pad_y
    return max(int(h), int(72 * font_scale))


def _accent_for_card(content: CardContent) -> Color:
    t = (content.card_type or "").lower()
    if t == "issue" or (content.accent or "").lower() == "right":
        return CRIMSON_BGR
    if t == "strength":
        return STRENGTH_BGR
    return INK_BGR


def draw_feedback_card(
    canvas: np.ndarray,
    box: Rect,
    content: CardContent,
    font_scale: float,
    *,
    pad_x: Optional[int] = None,
    pad_y: Optional[int] = None,
    line_gap: Optional[int] = None,
) -> Rect:
    """HTML .rb-card: paper fill, 1px line border, 3px left accent rail."""
    x1, y1, x2, y2 = [int(v) for v in box]
    pad_x = pad_x if pad_x is not None else max(14, int(16 * font_scale))
    pad_y = pad_y if pad_y is not None else max(14, int(16 * font_scale))
    accent = _accent_for_card(content)
    rail = max(3, int(3 * font_scale))

    # Paper surface + thin border
    cv2.rectangle(canvas, (x1, y1), (x2, y2), PAPER_BGR, thickness=-1)
    cv2.rectangle(canvas, (x1, y1), (x2, y2), LINE_BGR, thickness=1)
    # Left accent rail (overwrites left border)
    cv2.rectangle(canvas, (x1, y1), (x1 + rail, y2), accent, thickness=-1)

    # Draw text via PIL for proper fonts
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    draw = ImageDraw.Draw(pil)

    kicker_f, num_f, title_f, body_f, cite_f = _card_fonts(x2 - x1, font_scale)
    text_x = x1 + rail + pad_x
    inner_w = max(40, x2 - text_x - pad_x)
    y = y1 + pad_y

    # Number badge + kicker
    num_label = f"{int(content.num):02d}" if content.num else "01"
    badge = max(18, int(20 * font_scale))
    cx = text_x + badge // 2
    cy = y + badge // 2
    # Draw circle on PIL
    draw.ellipse(
        [cx - badge // 2, cy - badge // 2, cx + badge // 2, cy + badge // 2],
        outline=_bgr_to_rgb(accent),
        width=max(1, int(font_scale)),
    )
    nw = _pil_text_width(num_f, num_label)
    nh = _pil_text_height(num_f)
    draw.text((cx - nw // 2, cy - nh // 2 - 1), num_label, font=num_f, fill=_bgr_to_rgb(accent))

    kicker = (content.category or "FEEDBACK").strip().upper()
    draw.text(
        (text_x + badge + int(10 * font_scale), cy - _pil_text_height(kicker_f) // 2),
        kicker,
        font=kicker_f,
        fill=_bgr_to_rgb(accent),
    )
    y = cy + badge // 2 + int(9 * font_scale)

    # Title (Cormorant)
    for line in wrap_text_pil(content.title or "", title_f, inner_w):
        draw.text((text_x, y), line, font=title_f, fill=_bgr_to_rgb(INK_BGR))
        y += _pil_text_height(title_f) + int(3 * font_scale)
    y += int(4 * font_scale)

    # Body
    for seg in content.body_segments:
        if seg.is_cite:
            continue
        color = _bgr_to_rgb(seg.color if seg.color else INK_SOFT_BGR)
        for raw in str(seg.text or "").splitlines() or [""]:
            raw = raw.strip()
            if not raw:
                y += int(6 * font_scale)
                continue
            for line in wrap_text_pil(raw, body_f, inner_w):
                if y > y2 - pad_y:
                    break
                draw.text((text_x, y), line, font=body_f, fill=color)
                y += int(_pil_text_height(body_f) * 1.55)

    # Cite block
    cite = (content.cite or "").strip()
    if not cite:
        for seg in content.body_segments:
            if seg.is_cite and seg.text.strip():
                cite = seg.text.strip()
                break
    if cite and y < y2 - pad_y:
        y += int(8 * font_scale)
        # dashed rule
        dash_y = y
        x = text_x
        while x < text_x + inner_w:
            x2d = min(x + 6, text_x + inner_w)
            draw.line([(x, dash_y), (x2d, dash_y)], fill=_bgr_to_rgb(LINE_BGR), width=1)
            x += 10
        y += int(9 * font_scale)
        for line in wrap_text_pil(cite, cite_f, inner_w):
            if y > y2 - 4:
                break
            # Rephrased / Fix lines: black, same size as left-side body copy
            draw.text((text_x, y), line, font=cite_f, fill=_bgr_to_rgb(INK_BGR))
            y += int(_pil_text_height(cite_f) * 1.55)

    canvas[:, :, :] = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return (x1, y1, x2, y2)


def draw_connector(
    canvas: np.ndarray,
    card_box: Rect,
    target_rect: Rect,
    *,
    side: str = "right",
    color: Optional[Color] = None,
    thickness: int = 2,
    anchor_pos: float = 0.5,
) -> None:
    """
    HTML elbow connector: card edge → short horizontal → highlight edge.
    Solid dot at card; hollow ring at highlight.
    """
    cx1, cy1, cx2, cy2 = card_box
    tx1, ty1, tx2, ty2 = target_rect
    is_left = (side or "right").lower() == "left"
    line_color = color or (INK_BGR if is_left else CRIMSON_BGR)
    t = max(1, int(thickness))
    pos = min(1.0, max(0.0, float(anchor_pos)))

    y0 = (cy1 + cy2) // 2
    y1 = int(ty1 + pos * max(1, ty2 - ty1))
    if is_left:
        x0 = cx2
        x1 = tx1
        elbow = x0 + max(12, int(0.012 * canvas.shape[1]))
    else:
        x0 = cx1
        x1 = tx2
        elbow = x0 - max(12, int(0.012 * canvas.shape[1]))

    pts = np.array([[x0, y0], [elbow, y0], [x1, y1]], dtype=np.int32)
    cv2.polylines(canvas, [pts], False, line_color, t, cv2.LINE_AA)

    r = max(3, t + 1)
    # Solid dot at card
    cv2.circle(canvas, (x0, y0), r, line_color, thickness=-1, lineType=cv2.LINE_AA)
    # Ring at highlight
    cv2.circle(canvas, (x1, y1), r, PAPER_BGR, thickness=-1, lineType=cv2.LINE_AA)
    cv2.circle(canvas, (x1, y1), r, line_color, thickness=t, lineType=cv2.LINE_AA)


def draw_masthead(canvas: np.ndarray, meta: str = "") -> np.ndarray:
    """HTML .rb-masthead on every annotated page."""
    h, w = canvas.shape[:2]
    hh = header_height(w)
    pad_x = max(28, int(0.025 * w))
    pad_y = max(16, int(0.018 * w))

    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    draw = ImageDraw.Draw(pil)

    # Bottom hairline
    draw.line([(pad_x, hh - 1), (w - pad_x, hh - 1)], fill=_bgr_to_rgb(LINE_BGR), width=1)

    # Crimson logo tile with "r"
    logo = max(28, int(0.028 * w))
    lx, ly = pad_x, pad_y
    draw.rounded_rectangle([lx, ly, lx + logo, ly + logo], radius=max(4, logo // 5), fill=_bgr_to_rgb(CRIMSON_BGR))
    logo_font = _load_font("cormorant", int(logo * 0.78))
    rw = _pil_text_width(logo_font, "r")
    rh = _pil_text_height(logo_font)
    draw.text((lx + (logo - rw) // 2, ly + (logo - rh) // 2 - 1), "r", font=logo_font, fill=(255, 255, 255))

    # Wordmark + subtitle
    word_font = _load_font("syne", max(12, int(0.012 * w)))
    sub_font = _load_font("syne", max(8, int(0.0075 * w)))
    tx = lx + logo + max(10, int(0.01 * w))
    draw.text((tx, ly + 2), "RUBRIC.AI", font=word_font, fill=_bgr_to_rgb(INK_BGR))
    draw.text(
        (tx, ly + _pil_text_height(word_font) + 4),
        "ANSWER EVALUATION — LINE BY LINE",
        font=sub_font,
        fill=_bgr_to_rgb(INK_SOFT_BGR),
    )

    # Right meta (Q title)
    meta_text = (meta or "").strip().upper()
    if meta_text:
        meta_font = _load_font("syne", max(9, int(0.0085 * w)))
        mw = _pil_text_width(meta_font, meta_text)
        # Truncate if needed
        while mw > w * 0.42 and len(meta_text) > 12:
            meta_text = meta_text[:-2]
            mw = _pil_text_width(meta_font, meta_text + "…")
            if len(meta_text) <= 12:
                meta_text = meta_text + "…"
                break
        if not meta_text.endswith("…") and _pil_text_width(meta_font, meta_text) > w * 0.42:
            meta_text = meta_text[:40] + "…"
            mw = _pil_text_width(meta_font, meta_text)
        draw.text(
            (w - pad_x - mw, ly + (logo - _pil_text_height(meta_font)) // 2),
            meta_text,
            font=meta_font,
            fill=_bgr_to_rgb(CRIMSON_BGR),
        )

    canvas[:, :, :] = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return canvas


def draw_page_label(canvas: np.ndarray, page_number: int) -> np.ndarray:
    """HTML .rb-page-label centered under masthead."""
    h, w = canvas.shape[:2]
    hh = header_height(w)
    label = f"PAGE {int(page_number):02d} — EVALUATED SCRIPT"
    font = _load_font("syne", max(9, int(0.008 * w)))
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    draw = ImageDraw.Draw(pil)
    tw = _pil_text_width(font, label)
    th = _pil_text_height(font)
    y = hh + max(14, int(0.012 * w))
    draw.text(((w - tw) // 2, y), label, font=font, fill=_bgr_to_rgb(INK_SOFT_BGR))
    canvas[:, :, :] = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return canvas


def draw_footer(canvas: np.ndarray) -> np.ndarray:
    """HTML .rb-footer pinned to bottom of the cream page."""
    h, w = canvas.shape[:2]
    fh = footer_height(w)
    pad_x = max(28, int(0.025 * w))
    y0 = h - fh

    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    draw = ImageDraw.Draw(pil)
    draw.line([(pad_x, y0), (w - pad_x, y0)], fill=_bgr_to_rgb(LINE_BGR), width=1)

    font = _load_font("syne", max(8, int(0.0075 * w)))
    left = "GENERATED BY RUBRIC.AI"
    right = "SMART PREPARATION"
    th = _pil_text_height(font)
    ty = y0 + (fh - th) // 2
    draw.text((pad_x, ty), left, font=font, fill=_bgr_to_rgb(INK_SOFT_BGR))
    rw = _pil_text_width(font, right)
    draw.text((w - pad_x - rw, ty), right, font=font, fill=_bgr_to_rgb(CRIMSON_BGR))

    canvas[:, :, :] = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return canvas


def apply_chrome(
    canvas: np.ndarray,
    *,
    page_number: int,
    meta: str = "",
) -> np.ndarray:
    """Draw masthead, page label, and footer. Call after content is placed."""
    canvas = ensure_canvas_height(
        canvas,
        max(canvas.shape[0], content_top_offset(canvas.shape[1]) + content_bottom_reserve(canvas.shape[1]) + 100),
    )
    draw_masthead(canvas, meta=meta)
    draw_page_label(canvas, page_number)
    draw_footer(canvas)
    return canvas


def place_stacked_boxes(
    heights: Sequence[int],
    *,
    x1: int,
    x2: int,
    start_y: int,
    gap: int,
) -> Tuple[List[Rect], int]:
    boxes: List[Rect] = []
    y = int(start_y)
    for h in heights:
        hh = max(1, int(h))
        boxes.append((int(x1), y, int(x2), y + hh))
        y += hh + int(gap)
    bottom = boxes[-1][3] if boxes else int(start_y)
    return boxes, bottom


def compute_page_height(
    script_bottom: int,
    left_bottom: int,
    right_bottom: int,
    *,
    bottom_margin: int,
    min_height: int = 0,
) -> int:
    return max(
        int(min_height),
        int(script_bottom) + int(bottom_margin),
        int(left_bottom) + int(bottom_margin),
        int(right_bottom) + int(bottom_margin),
    )


def split_header_title(header: str) -> Tuple[str, str]:
    text = (header or "").strip()
    if not text:
        return ("FEEDBACK", "")
    for sep in (" — ", " - ", ": ", " – "):
        if sep in text:
            left, right = text.split(sep, 1)
            left, right = left.strip(), right.strip()
            if left and right:
                return (left, right)
    return (text, "")


def body_segments_from_text(
    text: str,
    *,
    default_color: Color = INK_SOFT_BGR,
    rephrase_color: Color = STRENGTH_BGR,
    emphasize_color: Color = CRIMSON_BGR,
) -> List[TextSegment]:
    segments: List[TextSegment] = []
    raw = text or ""
    if not raw.strip():
        return segments
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            segments.append(TextSegment(text="", color=default_color))
            continue
        lower = stripped.lower()
        if lower.startswith("rephrased:"):
            segments.append(TextSegment(text=stripped, color=rephrase_color, is_cite=True))
        elif lower.startswith("correction:") or lower.startswith("fix:"):
            segments.append(TextSegment(text=stripped, color=emphasize_color, is_cite=True))
        else:
            segments.append(TextSegment(text=stripped, color=default_color))
    return segments


def suggestion_card_content(suggestion_text: str, index: Optional[int] = None) -> CardContent:
    text = (suggestion_text or "").strip()
    category = "SUGGESTION"
    title = text
    body: List[TextSegment] = []
    for sep in (". ", "? ", "! "):
        if sep in text and len(text) > 80:
            first, rest = text.split(sep, 1)
            title = (first + sep.strip()).strip()
            body = [TextSegment(text=rest.strip(), color=INK_SOFT_BGR)]
            break
    return CardContent(
        category=category,
        title=title,
        body_segments=body,
        accent="left",
        num=int(index or 1),
        card_type="suggestion",
    )


def annotation_card_content(header: str, body: str, index: Optional[int] = None) -> CardContent:
    category, title = split_header_title(header)
    if not title:
        title = category
        category = "ANNOTATION"
    cite = ""
    body_segs: List[TextSegment] = []
    for seg in body_segments_from_text(body):
        if seg.is_cite and not cite:
            cite = seg.text
        elif not seg.is_cite:
            body_segs.append(seg)
        else:
            # Additional cite-like lines stay in cite block
            if cite:
                cite = cite + " " + seg.text
            else:
                cite = seg.text
    return CardContent(
        category=category,
        title=title,
        body_segments=body_segs,
        accent="right",
        num=int(index or 1),
        cite=cite,
        card_type="issue",
    )


def format_page_meta(
    *,
    kind: str = "subject",
    subject: str = "",
    question: str = "",
    topic: str = "",
    title: str = "",
) -> str:
    """
    Build the crimson masthead meta string from evaluation context.
    Examples:
      Q · Political Science — Separation of powers
      Essay · Role of media in democracy
      Précis · Climate change and cities
    """
    def _clean(s: str, limit: int = 72) -> str:
        t = re.sub(r"\s+", " ", (s or "").strip())
        t = re.sub(r"^(q(uestion)?\s*\d+\s*[\.:\)\-]?\s*)", "", t, flags=re.I)
        if len(t) > limit:
            t = t[: limit - 1].rstrip() + "…"
        return t

    kind_l = (kind or "subject").lower()
    if kind_l in ("essay", "eng_essay", "english"):
        core = _clean(topic or question or title or "English Essay")
        return f"Essay · {core}"
    if kind_l in ("precis", "précis"):
        core = _clean(title or topic or question or "Précis")
        return f"Précis · {core}"
    subj = _clean(subject or "Subject", 36)
    q = _clean(question or topic or title, 48)
    if q and q.lower() != subj.lower():
        return f"Q · {subj} — {q}"
    return f"Q · {subj}"


def rects_overlap(a: Rect, b: Rect, pad: int = 0) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (
        ax2 + pad < bx1
        or ax1 - pad > bx2
        or ay2 + pad < by1
        or ay1 - pad > by2
    )


def find_non_overlapping_y(
    occupied: Sequence[Rect],
    *,
    x1: int,
    x2: int,
    start_y: int,
    height: int,
    gap: int = 8,
    pad: int = 4,
) -> int:
    y = max(0, int(start_y))
    h = max(1, int(height))
    for _ in range(max(50, len(occupied) + 5)):
        candidate = (int(x1), y, int(x2), y + h)
        blockers = [r for r in occupied if rects_overlap(candidate, r, pad=pad)]
        if not blockers:
            return y
        y = max(r[3] for r in blockers) + int(gap)
    return y
