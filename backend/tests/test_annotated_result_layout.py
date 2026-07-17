"""
Focused tests for the annotated-result cream layout primitives.

These verify presentation geometry only — no grading / rubric content changes.
Palette/fonts match rubric-annotation-component.html.
"""

from __future__ import annotations

import os
import sys

import numpy as np

# Ensure `backend` package imports resolve when running from repo root or backend/
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from backend.utils import annotated_result_layout as arl  # noqa: E402


def test_cream_canvas_matches_html():
    canvas = arl.create_cream_canvas(100, 80)
    assert canvas.shape == (80, 100, 3)
    # HTML --rb-cream: #F2EDE3
    assert tuple(int(v) for v in canvas[0, 0]) == arl.CREAM_BGR
    assert arl.CREAM_BGR == (227, 237, 242)


def test_ensure_canvas_height_grows_with_cream_fill():
    canvas = arl.create_cream_canvas(50, 40)
    grown = arl.ensure_canvas_height(canvas, 120)
    assert grown.shape[0] == 120
    assert grown.shape[1] == 50
    assert tuple(int(v) for v in grown[100, 10]) == arl.CREAM_BGR
    assert np.array_equal(grown[:40], canvas)


def test_paste_script_centers_with_shadow_and_cream_bg():
    script = np.full((60, 40, 3), (255, 255, 255), dtype=np.uint8)
    canvas = arl.create_cream_canvas(140, 80)
    left = 50
    out = arl.paste_script_with_shadow(canvas, script, left_width=left, y_offset=10, shadow_offset=4)
    assert tuple(int(v) for v in out[20, left + 5]) == (255, 255, 255)
    assert tuple(int(v) for v in out[20, 5]) == arl.CREAM_BGR
    assert tuple(int(v) for v in out[20, left + 40 + 10]) == arl.CREAM_BGR


def test_measure_and_draw_left_and_right_cards_match_html():
    canvas = arl.create_cream_canvas(800, 500)
    font_scale = 1.0

    left = arl.suggestion_card_content("Add a stronger historical context before the claim.", index=1)
    right = arl.annotation_card_content(
        "Introduction - Weak",
        "Biography is not analysis.\nRephrased: Focus on the argument.",
        index=4,
    )

    left_h = arl.measure_card_height(left, 220, font_scale)
    right_h = arl.measure_card_height(right, 220, font_scale)
    assert left_h > 40
    assert right_h > 40

    left_box = (20, 80, 240, 80 + left_h)
    right_box = (540, 80, 760, 80 + right_h)
    arl.draw_feedback_card(canvas, left_box, left, font_scale)
    arl.draw_feedback_card(canvas, right_box, right, font_scale)

    # Paper surfaces
    assert tuple(int(v) for v in canvas[100, 50]) == arl.PAPER_BGR
    assert tuple(int(v) for v in canvas[100, 580]) == arl.PAPER_BGR
    # Right card crimson accent rail
    rail = tuple(int(v) for v in canvas[110, 541])
    assert rail == arl.CRIMSON_BGR
    # Left card ink accent rail
    left_rail = tuple(int(v) for v in canvas[110, 21])
    assert left_rail == arl.INK_BGR
    assert not arl.rects_overlap(left_box, right_box, pad=0)


def test_place_stacked_boxes_and_page_height_expands():
    heights = [80, 120, 90]
    boxes, bottom = arl.place_stacked_boxes(heights, x1=10, x2=200, start_y=15, gap=10)
    assert len(boxes) == 3
    assert boxes[0][1] == 15
    assert boxes[1][1] == 15 + 80 + 10
    assert bottom == boxes[-1][3]

    page_h = arl.compute_page_height(
        script_bottom=300,
        left_bottom=bottom,
        right_bottom=900,
        bottom_margin=20,
        min_height=280,
    )
    assert page_h == 920


def test_find_non_overlapping_y_never_crosses_column():
    occupied = [(10, 10, 200, 100), (10, 120, 200, 200)]
    y = arl.find_non_overlapping_y(
        occupied,
        x1=10,
        x2=200,
        start_y=50,
        height=40,
        gap=8,
    )
    assert y >= 208


def test_connector_elbow_and_dots():
    canvas = arl.create_cream_canvas(600, 300)
    card = (20, 40, 180, 120)
    target = (250, 80, 400, 110)
    arl.draw_connector(canvas, card, target, side="left", thickness=2)
    assert canvas.shape == (300, 600, 3)
    start_x, start_y = card[2], (card[1] + card[3]) // 2
    band = canvas[start_y - 4 : start_y + 5, start_x - 4 : start_x + 5]
    assert not np.all(band == arl.CREAM_BGR)


def test_masthead_and_footer_chrome():
    canvas = arl.create_cream_canvas(1200, 900)
    canvas = arl.apply_chrome(canvas, page_number=1, meta="Q · Political Science — Separation of Powers")
    # Masthead bottom region should still be cream-ish with drawn ink pixels for text
    top_band = canvas[10:60, 40:200]
    assert not np.all(top_band == arl.CREAM_BGR)
    # Footer band has crimson for "SMART PREPARATION"
    footer = canvas[-50:, -300:]
    assert np.any(np.all(footer == arl.CRIMSON_BGR, axis=-1))


def test_format_page_meta_by_kind():
    assert "Q ·" in arl.format_page_meta(kind="subject", subject="Pol Sci", question="Separation of powers")
    assert arl.format_page_meta(kind="essay", topic="Role of media").startswith("Essay ·")
    assert arl.format_page_meta(kind="precis", title="Climate cities").startswith("Précis ·")


def test_long_text_and_missing_title_still_measurable():
    long_body = " ".join(["detailed feedback"] * 40)
    card = arl.annotation_card_content("Factual Error - Accuracy", long_body, index=2)
    h = arl.measure_card_height(card, 180, 0.9)
    assert h > 150

    empty_title = arl.annotation_card_content("PlainHeader", "", index=1)
    assert empty_title.title
    assert arl.measure_card_height(empty_title, 180, 0.9) > 30


def test_dense_page_height_uses_tallest_column():
    h = arl.compute_page_height(500, 700, 1400, bottom_margin=30, min_height=600)
    assert h == 1430


def test_suggestion_content_does_not_invent_new_feedback_words():
    text = "Ground the claim in Locke before citing Montesquieu."
    card = arl.suggestion_card_content(text, index=1)
    assert text in (card.title + " " + " ".join(s.text for s in card.body_segments))
    assert card.accent == "left"
    assert card.card_type == "suggestion"
