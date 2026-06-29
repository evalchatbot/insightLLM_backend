"""
Shared first-page ("cover") report renderer for all evaluation modules
(20-marks rubric, English essay, precis).

The visual design reproduces the Rubric.ai evaluation-report mockup:
a clean IBM Plex / red-accent A4 page with a branded top bar, a score +
question row, a marks-breakdown table and two bullet/summary columns.

This module is intentionally self-contained: it bundles its own fonts and
the real Rubric.ai logo under ``report_assets/`` so the output looks identical
regardless of the host environment. Each evaluation module builds a normalized
``model`` dict (see ``CoverModel`` notes below) and calls one of:

    render_cover_images(model, page_size)  -> List[PIL.Image]   (essay / 20-marks)
    render_cover_pdf(model, out_path)      -> writes a 1-page vector PDF (precis)
    build_cover_doc(model)                 -> fitz.Document      (low level)

Only the first page of each annotated output is affected; nothing else in the
grading / annotation pipeline changes.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import fitz  # PyMuPDF
from PIL import Image

# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_assets")
_FONTS_DIR = os.path.join(_ASSETS_DIR, "fonts")
_LOGO_SVG = os.path.join(_ASSETS_DIR, "rubric_logo.svg")

# Logical font alias -> ttf file name.
_FONT_FILES = {
    "sans-light": "IBMPlexSans-Light.ttf",
    "sans": "IBMPlexSans-Regular.ttf",
    "sans-med": "IBMPlexSans-Medium.ttf",
    "sans-semi": "IBMPlexSans-SemiBold.ttf",
    "mono": "IBMPlexMono-Regular.ttf",
    "mono-med": "IBMPlexMono-Medium.ttf",
}

# ---------------------------------------------------------------------------
# Palette (matches the mockup; red aligned to the real #b22222 brand mark)
# ---------------------------------------------------------------------------

RED = (0.698, 0.133, 0.133)        # #b22222  brand red / accent
INK = (0.102, 0.102, 0.102)        # #1A1A1A  primary text
# All report text is rendered in near-black for maximum readability.
# (Structural rule lines below stay light; red/green accents are kept.)
GREY = INK                         # labels (was #999999)
GREY_DK = INK                      # body text (was #333333)
GREY_MID = INK                     # question text (was #444444)
LINE = (0.910, 0.910, 0.910)       # #E8E8E8  soft rules
LINE_LT = (0.941, 0.941, 0.941)    # #F0F0F0  row rules
LINE_XLT = (0.957, 0.957, 0.957)   # #F4F4F4  list rules
GREEN = (0.176, 0.478, 0.310)      # #2D7A4F  "how to improve"
CREAM = (0.894, 0.886, 0.867)      # #e4e2dd  logo mark
ZERO_GREY = (0.800, 0.800, 0.800)  # #cccccc  zero-score numerals
OK_GREY = (0.333, 0.333, 0.333)    # #555555  full-score numerals

# Page geometry: A4 in points.
PAGE_W = 595.28
PAGE_H = 841.89

# The mockup is authored in CSS px for a 210mm-wide body. 96dpi px -> 72dpi pt.
PX = 0.75


def _px(v: float) -> float:
    return v * PX


# ---------------------------------------------------------------------------
# Font cache (fitz.Font objects, used for both measuring and drawing)
# ---------------------------------------------------------------------------

_FONT_CACHE: Dict[str, fitz.Font] = {}


def _font(alias: str) -> fitz.Font:
    f = _FONT_CACHE.get(alias)
    if f is None:
        f = fitz.Font(fontfile=os.path.join(_FONTS_DIR, _FONT_FILES[alias]))
        _FONT_CACHE[alias] = f
    return f


# ---------------------------------------------------------------------------
# Low-level drawing helpers operating on a single fitz page
# ---------------------------------------------------------------------------


class _Canvas:
    """Thin wrapper over a fitz page providing top-left text + measurement."""

    def __init__(self, page: fitz.Page):
        self.page = page
        self._registered: Dict[str, str] = {}

    def _fontname(self, alias: str) -> str:
        name = self._registered.get(alias)
        if name is None:
            name = "F%d" % len(self._registered)
            self.page.insert_font(fontname=name, fontfile=os.path.join(_FONTS_DIR, _FONT_FILES[alias]))
            self._registered[alias] = name
        return name

    def text_len(self, text: str, alias: str, size: float) -> float:
        return _font(alias).text_length(text, fontsize=size)

    def text(
        self,
        x: float,
        y_top: float,
        text: str,
        alias: str,
        size: float,
        color: Tuple[float, float, float],
        *,
        letter_spacing: float = 0.0,
    ) -> None:
        """Draw a single line; ``y_top`` is the visual top of the glyph box."""
        if not text:
            return
        baseline = y_top + size * 0.80
        if letter_spacing <= 0:
            self.page.insert_text(
                (x, baseline), text, fontname=self._fontname(alias), fontsize=size, color=color
            )
            return
        cx = x
        fnt = self._fontname(alias)
        for ch in text:
            self.page.insert_text((cx, baseline), ch, fontname=fnt, fontsize=size, color=color)
            cx += self.text_len(ch, alias, size) + letter_spacing

    def hline(self, x0: float, x1: float, y: float, color: Tuple[float, float, float], width: float) -> None:
        self.page.draw_line((x0, y), (x1, y), color=color, width=width)

    def vline(self, x: float, y0: float, y1: float, color: Tuple[float, float, float], width: float) -> None:
        self.page.draw_line((x, y0), (x, y1), color=color, width=width)

    def rect(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        *,
        fill: Optional[Tuple[float, float, float]] = None,
        stroke: Optional[Tuple[float, float, float]] = None,
        width: float = 0.6,
        radius: Optional[float] = None,
    ) -> None:
        sh = self.page.new_shape()
        if radius is not None:
            sh.draw_rect(fitz.Rect(x0, y0, x1, y1), radius=radius)
        else:
            sh.draw_rect(fitz.Rect(x0, y0, x1, y1))
        sh.finish(fill=fill, color=stroke, width=width if stroke else 0)
        sh.commit()

    def circle(self, cx: float, cy: float, r: float, fill: Tuple[float, float, float]) -> None:
        sh = self.page.new_shape()
        sh.draw_circle((cx, cy), r)
        sh.finish(fill=fill, color=fill, width=0)
        sh.commit()


def _wrap(canvas: _Canvas, text: str, alias: str, size: float, max_w: float) -> List[str]:
    text = (text or "").strip()
    if not text:
        return [""]
    out: List[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            out.append("")
            continue
        line = ""
        for w in words:
            trial = (line + " " + w).strip()
            if line and canvas.text_len(trial, alias, size) > max_w:
                out.append(line)
                line = w
            else:
                line = trial
        if line:
            out.append(line)
    return out or [""]


def _draw_logo(canvas: _Canvas, bx: float, by: float, s: float) -> None:
    """Draw the real Rubric.ai mark: rounded red square + cream 'r' glyph."""
    # rounded brand square
    canvas.rect(bx, by, bx + s, by + s, fill=RED, radius=_px(3) / s)
    # glyph derived from rubric_logo.svg geometry (stem rect + dot circle)
    gh = s * 0.64
    glyph_scale = gh / 105.23
    gw = 84.3 * glyph_scale
    gleft = bx + (s - gw) / 2.0
    gtop = by + (s - gh) / 2.0
    # stem
    stem_x0 = gleft
    stem_x1 = gleft + 38.16 * glyph_scale
    stem_y0 = gtop + 2.78 * glyph_scale
    stem_y1 = gtop + 105.23 * glyph_scale
    canvas.rect(stem_x0, stem_y0, stem_x1, stem_y1, fill=CREAM)
    # dot
    dot_cx = gleft + 65.68 * glyph_scale
    dot_cy = gtop + 18.63 * glyph_scale
    canvas.circle(dot_cx, dot_cy, 18.6 * glyph_scale, CREAM)


# ---------------------------------------------------------------------------
# Section renderers — each returns the y-cursor after drawing
# ---------------------------------------------------------------------------


def _draw_topbar(canvas: _Canvas, model: Dict[str, Any], x0: float, x1: float, y: float, k: float) -> float:
    mark = _px(22) * k
    _draw_logo(canvas, x0, y, mark)
    tx = x0 + mark + _px(8) * k
    canvas.text(tx, y + _px(1) * k, "Rubric.ai", "sans-semi", _px(12) * k, INK)
    canvas.text(
        tx, y + _px(13) * k, "SMART PREPARATION", "sans-light", _px(8.2) * k, GREY,
        letter_spacing=_px(1) * k,
    )

    # meta block (right aligned, up to 2 lines of "Label: value · Label: value")
    meta_lines: List[List[Tuple[str, str]]] = model.get("meta_lines", [])
    my = y + _px(1) * k
    lab_sz = _px(10) * k
    for line in meta_lines:
        # measure full line width to right-align
        segs: List[Tuple[str, str, str]] = []  # (text, alias, color)
        for i, (label, value) in enumerate(line):
            if i:
                segs.append(("  ·  ", "sans-light", GREY))
            if label:
                segs.append((label + ": ", "sans-med", INK))
            segs.append((value, "sans-light", GREY))
        total = sum(canvas.text_len(t, a, lab_sz) for t, a, _ in segs)
        cx = x1 - total
        for t, a, c in segs:
            canvas.text(cx, my, t, a, lab_sz, c)
            cx += canvas.text_len(t, a, lab_sz)
        my += _px(15) * k

    bar_bottom = y + mark + _px(13) * k
    canvas.hline(x0, x1, bar_bottom, INK, 1.5)
    return bar_bottom + _px(16) * k


def _draw_score_question(canvas: _Canvas, model: Dict[str, Any], x0: float, x1: float, y: float, k: float) -> float:
    score_block_w = _px(132) * k
    top = y

    # --- score block ---
    num = str(model.get("score_value", ""))
    num_sz = _px(48) * k
    # shrink an over-wide score (e.g. a range like "55-60") to fit its column
    while num and canvas.text_len(num, "mono-med", num_sz) > score_block_w and num_sz > _px(22) * k:
        num_sz -= _px(2) * k
    canvas.text(x0, top, num, "mono-med", num_sz, RED)
    ny = top + num_sz + _px(4) * k
    canvas.text(x0, ny, str(model.get("score_denom", "")), "sans-light", _px(10) * k, GREY)
    ny += _px(15) * k
    # bar
    bar_w = _px(100) * k
    bar_h = _px(2.4) * k
    canvas.rect(x0, ny, x0 + bar_w, ny + bar_h, fill=LINE, radius=0.5)
    pct = max(0.0, min(1.0, float(model.get("score_pct", 0.0) or 0.0)))
    if pct > 0:
        canvas.rect(x0, ny, x0 + max(bar_w * pct, bar_h), ny + bar_h, fill=RED, radius=0.5)
    ny += bar_h + _px(5) * k
    canvas.text(x0, ny, str(model.get("score_caption", "")), "sans-light", _px(9) * k, GREY)
    score_bottom = ny + _px(9) * k

    # --- divider ---
    div_x = x0 + score_block_w
    canvas.vline(div_x, top + _px(2) * k, top + _px(54) * k, LINE, 1.0)

    # --- question block ---
    qx = div_x + _px(20) * k
    qy = top
    canvas.text(
        qx, qy, str(model.get("question_label", "Question Statement")).upper(),
        "sans-semi", _px(9) * k, RED, letter_spacing=_px(1.3) * k,
    )
    qy += _px(15) * k
    q_sz = _px(10.5) * k
    q_lines = _wrap(canvas, str(model.get("question", "")), "sans-light", q_sz, x1 - qx)
    line_h = q_sz * 1.55
    for ln in q_lines:
        canvas.text(qx, qy, ln, "sans-light", q_sz, GREY_MID)
        qy += line_h
    block_bottom = max(score_bottom, qy)

    canvas.hline(x0, x1, block_bottom + _px(4) * k, LINE, 0.8)
    return block_bottom + _px(4) * k + _px(16) * k


def _draw_table(canvas: _Canvas, model: Dict[str, Any], x0: float, x1: float, y: float, k: float) -> float:
    columns: List[Dict[str, Any]] = model.get("columns", [])
    rows: List[Dict[str, Any]] = model.get("rows", [])
    if not columns:
        return y

    canvas.text(
        x0, y, str(model.get("table_label", "Marks Breakdown")).upper(),
        "sans-semi", _px(9) * k, GREY, letter_spacing=_px(1.3) * k,
    )
    y += _px(8) * k + _px(11) * k

    table_w = x1 - x0
    widths = [c["w"] * table_w for c in columns]
    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + w)

    pad = _px(8) * k
    head_sz = _px(9) * k
    cell_sz = _px(10.5) * k
    num_sz = _px(12) * k

    # header row
    hy = y
    for i, c in enumerate(columns):
        align = c.get("align", "left")
        txt = str(c.get("title", "")).upper()
        tw = canvas.text_len(txt, "sans-semi", head_sz)
        if align == "center":
            tx = xs[i] + (widths[i] - tw) / 2.0
        else:
            tx = xs[i] + pad
        canvas.text(tx, hy, txt, "sans-semi", head_sz, GREY, letter_spacing=_px(0.8) * k)
    header_bottom = hy + head_sz + _px(7) * k
    canvas.hline(x0, x1, header_bottom, INK, 1.0)

    # body rows
    ry = header_bottom
    line_h = cell_sz * 1.45
    for r in rows:
        # measure tallest wrapped cell
        cell_lines: List[List[str]] = []
        max_lines = 1
        for i, c in enumerate(columns):
            kind = c.get("kind", "text")
            val = str(r.get(c["key"], "") or "")
            if kind in ("mono", "mono_score"):
                cell_lines.append([val])
            else:
                lines = _wrap(canvas, val, "sans-light", cell_sz, widths[i] - 2 * pad)
                cell_lines.append(lines)
                max_lines = max(max_lines, len(lines))
        row_h = max_lines * line_h + _px(11) * k
        ty0 = ry + _px(7) * k
        for i, c in enumerate(columns):
            kind = c.get("kind", "text")
            align = c.get("align", "left")
            if kind in ("mono", "mono_score"):
                val = cell_lines[i][0]
                color = INK
                if kind == "mono_score":
                    color = r.get("obtained_color", RED) or RED
                tw = canvas.text_len(val, "mono", num_sz)
                tx = xs[i] + (widths[i] - tw) / 2.0 if align == "center" else xs[i] + pad
                # vertically center the single numeral within the row
                canvas.text(tx, ry + (row_h - num_sz) / 2.0 - _px(1) * k, val, "mono", num_sz, color)
            else:
                alias = "sans-med" if kind == "cat" else "sans-light"
                color = INK if kind == "cat" else GREY_DK
                ly = ty0
                for ln in cell_lines[i]:
                    canvas.text(xs[i] + pad, ly, ln, alias, cell_sz, color)
                    ly += line_h
        ry += row_h
        canvas.hline(x0, x1, ry, LINE_LT, 0.8)

    return ry + _px(16) * k


def _draw_section_column(
    canvas: _Canvas, sec: Dict[str, Any], x0: float, x1: float, y: float, k: float
) -> float:
    accent = GREEN if sec.get("accent") == "green" else RED
    bullet_accent = GREEN if sec.get("accent") == "green" else GREY
    canvas.text(
        x0, y, str(sec.get("label", "")).upper(), "sans-semi", _px(9) * k, accent,
        letter_spacing=_px(1.3) * k,
    )
    y += _px(9) * k + _px(7) * k
    canvas.hline(x0, x1, y, INK, 1.0)
    y += _px(5) * k

    body = sec.get("body")
    if body is not None:
        # paragraph form (e.g. precis "Ideal Precis"): optional bold title + text
        title = str(sec.get("title", "")).strip()
        if title:
            for ln in _wrap(canvas, title, "sans-semi", _px(10) * k, x1 - x0):
                canvas.text(x0, y, ln, "sans-semi", _px(10) * k, INK)
                y += _px(10) * k * 1.4
            y += _px(2) * k
        for ln in _wrap(canvas, str(body), "sans-light", _px(9.5) * k, x1 - x0):
            canvas.text(x0, y, ln, "sans-light", _px(9.5) * k, GREY_MID)
            y += _px(9.5) * k * 1.5
        return y

    items: List[str] = sec.get("items", []) or []
    it_sz = _px(10) * k
    line_h = it_sz * 1.5
    text_x = x0 + _px(12) * k
    for item in items:
        lines = _wrap(canvas, str(item), "sans-light", it_sz, x1 - text_x)
        canvas.text(x0, y + _px(0.5) * k, "›", "sans", it_sz, bullet_accent)  # ›
        for ln in lines:
            canvas.text(text_x, y, ln, "sans-light", it_sz, GREY_MID)
            y += line_h
        y += _px(7) * k
        canvas.hline(x0, x1, y - _px(3.5) * k, LINE_XLT, 0.6)
    return y


def _draw_two_columns(canvas: _Canvas, model: Dict[str, Any], x0: float, x1: float, y: float, k: float) -> float:
    left = model.get("left_section")
    right = model.get("right_section")
    gap = _px(20) * k
    col_w = (x1 - x0 - gap) / 2.0
    yl = yr = y
    if left:
        yl = _draw_section_column(canvas, left, x0, x0 + col_w, y, k)
    if right:
        yr = _draw_section_column(canvas, right, x0 + col_w + gap, x1, y, k)
    return max(yl, yr)


def _draw_footer(canvas: _Canvas, model: Dict[str, Any], x0: float, x1: float, page_h: float, k: float) -> None:
    fy = page_h - _px(28) * k
    canvas.hline(x0, x1, fy, LINE, 0.8)
    fy += _px(10) * k
    note = str(model.get("footer_note", ""))
    canvas.text(x0, fy, note, "sans-light", _px(9) * k, INK)
    url = str(model.get("footer_url", "rubric.ai"))
    uw = canvas.text_len(url, "mono", _px(9) * k)
    canvas.text(x1 - uw, fy, url, "mono", _px(9) * k, RED)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _render_page(model: Dict[str, Any], k: float) -> fitz.Document:
    """Render the cover at scale factor ``k`` (1.0 = nominal mockup sizes)."""
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    canvas = _Canvas(page)

    side = _px(36) * k
    x0 = side
    x1 = PAGE_W - side
    y = _px(28) * k

    y = _draw_topbar(canvas, model, x0, x1, y, k)
    y = _draw_score_question(canvas, model, x0, x1, y, k)
    y = _draw_table(canvas, model, x0, x1, y, k)
    _draw_two_columns(canvas, model, x0, x1, y, k)
    _draw_footer(canvas, model, x0, x1, PAGE_H, k)
    return doc


def _estimate_overflow(model: Dict[str, Any], k: float) -> float:
    """Return the bottom y after the two-column block (without footer) for fit checks."""
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    canvas = _Canvas(page)
    side = _px(36) * k
    x0, x1 = side, PAGE_W - side
    y = _px(28) * k
    # NOTE: we reuse the real drawing routines on a throwaway page to measure.
    y = _draw_topbar(canvas, model, x0, x1, y, k)
    y = _draw_score_question(canvas, model, x0, x1, y, k)
    y = _draw_table(canvas, model, x0, x1, y, k)
    y = _draw_two_columns(canvas, model, x0, x1, y, k)
    doc.close()
    return y


def build_cover_doc(model: Dict[str, Any]) -> fitz.Document:
    """Build the 1-page cover, auto-shrinking fonts so content fits one A4 page."""
    footer_top = PAGE_H - _px(34)
    k = 1.0
    for _ in range(14):
        bottom = _estimate_overflow(model, k)
        if bottom <= footer_top or k <= 0.62:
            break
        k = max(0.62, k - 0.04)
    return _render_page(model, k)


def render_cover_pdf(model: Dict[str, Any], out_path: str) -> None:
    """Render the cover to a single-page vector PDF (used by the precis module)."""
    doc = build_cover_doc(model)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    doc.save(out_path, garbage=4, deflate=True, clean=True)
    doc.close()


def render_cover_images(
    model: Dict[str, Any],
    page_size: Tuple[int, int] = (2977, 4211),
) -> List[Image.Image]:
    """Render the cover to a list with a single high-resolution PIL image.

    ``page_size`` is the target pixel size (width, height) at the caller's DPI.
    The A4 page is rasterized so the output width matches ``page_size[0]``.
    """
    doc = build_cover_doc(model)
    page = doc[0]
    scale = page_size[0] / PAGE_W
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()
    return [img]


# ---------------------------------------------------------------------------
# Small shared helpers for module adapters
# ---------------------------------------------------------------------------


def fmt_num(v: Any) -> str:
    """Format a mark value: drop trailing .0, keep one decimal otherwise."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v or "")
    return str(int(f)) if f.is_integer() else f"{f:.1f}"


def score_caption(pct: float) -> str:
    """Human band for the score caption, e.g. '45% · needs improvement'."""
    p = max(0.0, min(1.0, pct))
    pc = int(round(p * 100))
    if p >= 0.80:
        band = "excellent"
    elif p >= 0.65:
        band = "strong"
    elif p >= 0.50:
        band = "satisfactory"
    elif p >= 0.40:
        band = "needs improvement"
    else:
        band = "rework needed"
    return f"{pc}% — {band}"


def obtained_color(awarded: Any, allocated: Any) -> Tuple[float, float, float]:
    """Pick the numeral colour for an 'obtained marks' cell."""
    try:
        a = float(awarded)
        m = float(allocated)
    except (TypeError, ValueError):
        return OK_GREY
    if a <= 0:
        return ZERO_GREY
    if m > 0 and a < m:
        return RED
    return OK_GREY
