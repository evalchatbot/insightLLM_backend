"""
CSS English Essay outline grading pipeline (plan).

This pipeline reads a scanned PDF that contains only the outline (no full essay pages) and produces outline grades, annotations, and an annotated PDF.

Step 0 – Setup and configuration.
Read the required API keys from the environment and check that the input PDF and output paths are valid.

Step 1 – OCR of the outline.
Run Azure OCR on each PDF page to get text and basic positions for the outline content.

Step 2 – Page images for Grok.
Render each PDF page to an image and encode it so Grok can see handwriting and layout.

Step 3 – Detect outline span and structure.
Ask Grok how the outline is structured across the pages and what main sections exist.

Step 4 – Outline grading with the CSS outline rubric.
Give Grok the outline rubric and structure and ask it to assign strict mark ranges and an overall outline score.

Step 5 – Outline‑focused annotations.
For each outline page, ask Grok for a few short comments and suggestions pointing to specific parts of the outline.

Step 6 – Outline evaluation report page.
Use the outline grading result to render a single report page with topic, marks, weaknesses, and key suggestions.

Step 7 – Draw annotations on outline pages.
Use OCR locations and annotation text to highlight outline bullets or lines and place short comments near them.

Step 8 – Merge report and annotated pages.
Combine the report page and annotated outline pages into one final PDF and compress it if needed.

Step 9 – JSON output for the backend.
Save a JSON object with outline structure, grading, annotations, and page suggestions for the API and UI.
"""

import os
import io
import json
import base64
import time
import random
import re
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
import numpy as np
import fitz  # PyMuPDF
from PIL import Image
from docx import Document

# Import PDF compression function (optional)
try:
    from backend.outline.compressPdf import compress_pdf_if_needed  # type: ignore
except (ImportError, ModuleNotFoundError):
    try:
        from backend.eng_essay.compressPdf import compress_pdf_if_needed  # type: ignore
    except (ImportError, ModuleNotFoundError):
        try:
            from compressPdf import compress_pdf_if_needed  # type: ignore
        except (ImportError, ModuleNotFoundError):
            def compress_pdf_if_needed(*args, **kwargs):  # type: ignore
                print("  Warning: PDF compression module not available. Skipping compression.")
                return False

# Import annotation drawing function
try:
    from backend.outline.annotate_pdf_with_essay_outline_rubric import annotate_pdf_outline_pages  # type: ignore
except (ImportError, ModuleNotFoundError):
    try:
        from annotate_pdf_with_essay_outline_rubric import annotate_pdf_outline_pages  # type: ignore
    except (ImportError, ModuleNotFoundError):
        raise ImportError(
            "Cannot import 'annotate_pdf_outline_pages'. "
            "Ensure 'annotate_pdf_with_essay_outline_rubric.py' exists in backend/outline/ directory."
        )

# Import spell correction functions from ocr-spell-correction.py
try:
    import sys
    import importlib.util
    current_dir = os.path.dirname(os.path.abspath(__file__))
    spell_correction_path = os.path.join(current_dir, "ocr-spell-correction.py")
    spec = importlib.util.spec_from_file_location("ocr_spell_correction", spell_correction_path)
    if spec and spec.loader:
        ocr_spell_module = importlib.util.module_from_spec(spec)
        sys.modules["ocr_spell_correction"] = ocr_spell_module
        spec.loader.exec_module(ocr_spell_module)
        detect_spelling_grammar_errors = ocr_spell_module.detect_spelling_grammar_errors
        _filter_errors = ocr_spell_module._filter_errors
        print(f"✓ OCR Spell Correction Module: ENABLED")
    else:
        def detect_spelling_grammar_errors(grok_key, ocr_data):
            return []
        def _filter_errors(errors):
            return errors
except Exception as e:
    print(f"Warning: Could not import spell correction module: {e}")
    def detect_spelling_grammar_errors(grok_key, ocr_data):
        return []
    def _filter_errors(errors):
        return errors


@dataclass
class OutlinePipelineConfig:
    """
    Central configuration for the outline grading pipeline.

    Change values here to update environment variable names, rubric filenames, or default debug paths.
    """

    grok_env_key: str = "Grok_API"
    azure_endpoint_env_key: str = "AZURE_ENDPOINT"
    azure_key_env_key: str = "AZURE_KEY"

    outline_rubric_docx: str = "CSS English Essay Outline Evaluation Rubric Based on FPSC Examiners.docx"
    # Outline annotations & suggestions rubric (single source of truth for both)
    outline_annotations_rubric_docx: str = "ANNOTATIONS FOR ESSAY OUTLINE.docx"

    # Debug output locations (set to empty strings to disable).
    debug_ocr_pages_dir: str = "debug/outline/ocr/pages_outline"
    debug_structure_json: str = "debug/outline/ocr/outline_structure_raw.json"
    debug_ocr_json: str = "debug/outline/ocr/outline_ocr_full.json"
    debug_ocr_text: str = "debug/outline/ocr/outline_ocr_full.txt"
    debug_annotations_partial_json: str = "debug/outline/ocr/outline_annotations_partial.json"

    ocr_model_name: str = "prebuilt-read"
    ocr_render_dpi: int = 220
    ocr_workers: int = 3

    # Grok page image settings.
    grok_image_format: str = "JPEG"
    grok_images_dir: str = "debug/grok_images_outline"
    grok_max_dim: int = 800
    grok_max_total_base64_chars: int = 240_000

    # Grok model settings.
    grok_model_outline_structure: str = "grok-4-1-fast-reasoning"
    # Separate configs for outline grading, suggestions, and annotations so they
    # can be tuned independently if needed.
    grok_model_outline_grading: str = "grok-4-1-fast-reasoning"
    grok_model_outline_suggestions: str = "grok-4-1-fast-reasoning"
    grok_model_outline_annotations: str = "grok-4-1-fast-reasoning"

    grok_temperature_outline_grading: float = 0.12
    grok_temperature_outline_suggestions: float = 0.18
    grok_temperature_outline_annotations: float = 0.12

    grok_request_timeout_seconds: int = 180

    # Report page settings.
    report_dpi: int = 200
    report_min_width: int = 2977
    report_min_height: int = 4211
    report_margin_ratio: float = 0.055
    report_title_font_size: int = 28
    report_header_font_size: int = 16
    report_cell_font_size: int = 13


# Single shared config instance for this pipeline.
OUTLINE_CONFIG = OutlinePipelineConfig()


def _load_docx_text(path: str) -> str:
    """
    Load a DOCX file and return its non‑empty paragraphs as a single plain‑text string.
    """
    doc = Document(path)
    parts: List[str] = []
    for p in doc.paragraphs:
        txt = (p.text or "").strip()
        if txt:
            parts.append(txt)
    return "\n".join(parts)


def load_outline_rubric_text(path: str | None = None) -> str:
    """
    Load the outline evaluation rubric text from DOCX and return it as plain text.
    """
    if not path:
        path = OUTLINE_CONFIG.outline_rubric_docx
    if not os.path.isabs(path):
        # Resolve relative to this file's directory (eng_essay folder).
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, path)
    return _load_docx_text(path)


def load_outline_annotations_rubric_text(path: str | None = None) -> str:
    """
    Load the outline annotations rubric text from DOCX and return it as plain text.
    """
    if not path:
        path = OUTLINE_CONFIG.outline_annotations_rubric_docx
    if not os.path.isabs(path):
        # Resolve relative to this file's directory (eng_essay folder).
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, path)
    return _load_docx_text(path)


def get_outline_report_page_size(
    pdf_path: str,
    *,
    dpi: Optional[int] = None,
    min_width: Optional[int] = None,
    min_height: Optional[int] = None,
) -> Tuple[int, int]:
    """
    Calculate report page size matching annotated outline page dimensions.
    """
    if dpi is None:
        dpi = OUTLINE_CONFIG.report_dpi
    if min_width is None:
        min_width = OUTLINE_CONFIG.report_min_width
    if min_height is None:
        min_height = OUTLINE_CONFIG.report_min_height

    doc = fitz.open(pdf_path)
    try:
        if doc.page_count == 0:
            return (min_width, min_height)

        page = doc[0]
        page_rect = page.rect
        page_width_pts = page_rect.width
        page_height_pts = page_rect.height

        # Calculate expected size at target DPI.
        expected_width = int(page_width_pts * (dpi / 72.0))
        expected_height = int(page_height_pts * (dpi / 72.0))

        # Use minimum dimensions to ensure readability.
        report_width = max(expected_width, min_width)
        report_height = max(expected_height, min_height)

        return (report_width, report_height)
    except Exception:
        return (min_width, min_height)
    finally:
        doc.close()


@dataclass
class OutlineReportLayout:
    """
    Layout settings for the outline evaluation report page.
    """

    page_width_pt: float
    page_height_pt: float
    margin: float
    title_font_size: int
    header_font_size: int
    cell_font_size: int
    col_criterion: float
    col_alloc: float
    col_award: float
    col_comments: float
    row_height: float


def setup_outline_report_layout(
    page_size: Tuple[int, int],
    *,
    margin_ratio: Optional[float] = None,
    title_font_size: Optional[int] = None,
    header_font_size: Optional[int] = None,
    cell_font_size: Optional[int] = None,
) -> OutlineReportLayout:
    """
    Set up margins, font sizes, and column widths for the outline report table.
    """
    if margin_ratio is None:
        margin_ratio = OUTLINE_CONFIG.report_margin_ratio
    if title_font_size is None:
        title_font_size = OUTLINE_CONFIG.report_title_font_size
    if header_font_size is None:
        header_font_size = OUTLINE_CONFIG.report_header_font_size
    if cell_font_size is None:
        cell_font_size = OUTLINE_CONFIG.report_cell_font_size

    # Convert pixel size to points (PyMuPDF uses points).
    dpi_ratio = 72.0 / OUTLINE_CONFIG.report_dpi
    page_width_pt = page_size[0] * dpi_ratio
    page_height_pt = page_size[1] * dpi_ratio

    margin = page_width_pt * margin_ratio

    # Column widths (proportional to page width).
    col_criterion = page_width_pt * 0.27
    col_alloc = page_width_pt * 0.085
    col_award = page_width_pt * 0.10
    col_comments = page_width_pt - margin * 2 - (col_criterion + col_alloc + col_award)

    row_height = 36.0

    return OutlineReportLayout(
        page_width_pt=page_width_pt,
        page_height_pt=page_height_pt,
        margin=margin,
        title_font_size=title_font_size,
        header_font_size=header_font_size,
        cell_font_size=cell_font_size,
        col_criterion=col_criterion,
        col_alloc=col_alloc,
        col_award=col_award,
        col_comments=col_comments,
        row_height=row_height,
    )


def draw_outline_report_header(
    page: fitz.Page,
    layout: OutlineReportLayout,
    grading: Dict[str, Any],
) -> float:
    """
    Draw the report header: title, topic line, and total marks range.
    Returns the Y position after the header (for table start).
    """
    topic = grading.get("topic", "")
    total_range = grading.get("total_awarded_range", "0-0")
    total_marks = grading.get("total_outline_marks", 30)

    y = layout.margin

    # Title: "Outline Evaluation Report"
    page.insert_text(
        (layout.margin, y),
        "Outline Evaluation Report",
        fontname="hebo",  # Helvetica Bold
        fontsize=layout.title_font_size,
        color=(0, 0, 0),
    )
    y += layout.title_font_size * 1.5

    # Topic line (wrap if needed)
    topic_text = f"Topic: {topic}"
    topic_words = topic_text.split()
    topic_line = ""
    for word in topic_words:
        test_line = topic_line + word + " "
        text_width = fitz.get_text_length(test_line, fontname="hebo", fontsize=layout.header_font_size)
        if text_width > layout.page_width_pt - 2 * layout.margin:
            if topic_line:
                page.insert_text(
                    (layout.margin, y),
                    topic_line.strip(),
                    fontname="hebo",
                    fontsize=layout.header_font_size,
                    color=(0, 0, 0),
                )
                y += layout.header_font_size * 1.4
            topic_line = word + " "
        else:
            topic_line = test_line
    if topic_line:
        page.insert_text(
            (layout.margin, y),
            topic_line.strip(),
            fontname="hebo",
            fontsize=layout.header_font_size,
            color=(0, 0, 0),
        )
        y += layout.header_font_size * 1.4

    # Total marks range (e.g., "18-22/30")
    marks_text = f"Total Outline Marks (Range): {total_range}/{total_marks}"
    page.insert_text(
        (layout.margin, y),
        marks_text,
        fontname="hebo",
        fontsize=layout.header_font_size,
        color=(0, 0, 0),
    )
    y += layout.header_font_size * 1.8

    return y


def draw_outline_grading_table(
    page: fitz.Page,
    layout: OutlineReportLayout,
    grading: Dict[str, Any],
    start_y: float,
) -> float:
    """
    Draw the grading criteria table with header and rows.
    Handles text wrapping in Criterion and Comments columns.
    Uses alternating row colors for readability.
    Returns the Y position after the table.
    """
    criteria_list = grading.get("criteria", [])
    if not criteria_list:
        return start_y

    table_x = layout.margin
    table_w = layout.page_width_pt - 2 * layout.margin

    # Table header
    headers = ["Criterion", "Total Marks", "Marks Awarded", "Key Comments"]
    header_rect = fitz.Rect(table_x, start_y, table_x + table_w, start_y + layout.row_height)
    page.draw_rect(header_rect, color=(0, 0, 0), fill=(0.4, 0.4, 0.4), width=2)

    x = table_x
    splits = [layout.col_criterion, layout.col_alloc, layout.col_award, layout.col_comments]
    for i, htxt in enumerate(headers):
        page.insert_text(
            (x + 5, start_y + 23),
            htxt,
            fontname="hebo",
            fontsize=layout.header_font_size,
            color=(0, 0, 0),
        )
        x += splits[i]
        if i < len(headers) - 1:
            page.draw_line((x, start_y), (x, start_y + layout.row_height), color=(0, 0, 0), width=2)
    y = start_y + layout.row_height

    # Table rows
    for idx, c in enumerate(criteria_list):
        crit = str(c.get("criterion", ""))
        alloc = str(c.get("marks_allocated", ""))
        # Display marks_awarded_range or marks_awarded
        marks_awarded = c.get("marks_awarded")
        if marks_awarded is not None:
            award_display = str(marks_awarded)
        else:
            rng = c.get("marks_awarded_range", "0-0")
            award_display = rng
        comments = str(c.get("key_comments", ""))

        # Estimate row height based on text wrapping
        comment_chars_per_line = int((layout.col_comments - 10) / (layout.cell_font_size * 0.5))
        comment_lines = max(1, (len(comments) + comment_chars_per_line - 1) // comment_chars_per_line)

        crit_chars_per_line = int((layout.col_criterion - 10) / (layout.cell_font_size * 0.5))
        crit_lines = max(1, (len(crit) + crit_chars_per_line - 1) // crit_chars_per_line)

        row_h = max(35, max(comment_lines, crit_lines) * layout.cell_font_size * 1.55)

        # Alternating row color
        fill_color = (0.8, 0.8, 0.8) if idx % 2 == 0 else (1, 1, 1)
        row_rect = fitz.Rect(table_x, y, table_x + table_w, y + row_h)
        page.draw_rect(row_rect, color=(0, 0, 0), fill=fill_color, width=1)

        # Draw cell content
        x = table_x

        # Criterion (with wrapping)
        crit_y = y + 18
        crit_words = crit.split()
        crit_line = ""
        for word in crit_words:
            test_line = crit_line + word + " "
            text_width = fitz.get_text_length(test_line, fontname="helv", fontsize=layout.cell_font_size)
            if text_width > layout.col_criterion - 10:
                if crit_line:
                    page.insert_text(
                        (x + 5, crit_y),
                        crit_line.strip(),
                        fontname="helv",
                        fontsize=layout.cell_font_size,
                        color=(0, 0, 0),
                    )
                    crit_y += layout.cell_font_size * 1.35
                crit_line = word + " "
            else:
                crit_line = test_line
        if crit_line:
            page.insert_text(
                (x + 5, crit_y),
                crit_line.strip(),
                fontname="helv",
                fontsize=layout.cell_font_size,
                color=(0, 0, 0),
            )

        x += layout.col_criterion
        page.draw_line((x, y), (x, y + row_h), color=(0, 0, 0), width=1)

        # Total Marks
        page.insert_text(
            (x + 5, y + 18),
            alloc,
            fontname="helv",
            fontsize=layout.cell_font_size,
            color=(0, 0, 0),
        )
        x += layout.col_alloc
        page.draw_line((x, y), (x, y + row_h), color=(0, 0, 0), width=1)

        # Marks Awarded
        page.insert_text(
            (x + 5, y + 18),
            award_display,
            fontname="helv",
            fontsize=layout.cell_font_size,
            color=(0, 0, 0),
        )
        x += layout.col_award
        page.draw_line((x, y), (x, y + row_h), color=(0, 0, 0), width=1)

        # Key Comments (with wrapping)
        comment_y = y + 18
        comment_words = comments.split()
        comment_line = ""
        for word in comment_words:
            test_line = comment_line + word + " "
            text_width = fitz.get_text_length(test_line, fontname="helv", fontsize=layout.cell_font_size)
            if text_width > layout.col_comments - 10:
                if comment_line:
                    page.insert_text(
                        (x + 5, comment_y),
                        comment_line.strip(),
                        fontname="helv",
                        fontsize=layout.cell_font_size,
                        color=(0, 0, 0),
                    )
                    comment_y += layout.cell_font_size * 1.35
                comment_line = word + " "
            else:
                comment_line = test_line
        if comment_line:
            page.insert_text(
                (x + 5, comment_y),
                comment_line.strip(),
                fontname="helv",
                fontsize=layout.cell_font_size,
                color=(0, 0, 0),
            )

        y += row_h

    return y


def draw_outline_reasons_section(
    page: fitz.Page,
    layout: OutlineReportLayout,
    grading: Dict[str, Any],
    start_y: float,
) -> float:
    """
    Draw the "Reasons for Low Outline Score" section as a bullet list.
    Returns the Y position after the section.
    """
    y = start_y + 28  # Add spacing before section

    # Section title
    title = "Reasons for Low Outline Score"
    page.insert_text(
        (layout.margin, y),
        title,
        fontname="hebo",
        fontsize=layout.title_font_size,
        color=(0, 0, 0),
    )
    y += layout.title_font_size * 1.5

    # Bullet list
    reasons = grading.get("reasons_for_low_score", [])
    if not reasons:
        reasons = ["(Not provided)"]

    for bullet in reasons:
        bullet_text = f"- {bullet}"
        bullet_words = bullet_text.split()
        bullet_line = ""
        first_line = True
        for word in bullet_words:
            test_line = bullet_line + word + " "
            text_width = fitz.get_text_length(test_line, fontname="helv", fontsize=layout.header_font_size)
            max_width = layout.page_width_pt - 2 * layout.margin - 30 if first_line else layout.page_width_pt - 2 * layout.margin - 50
            if text_width > max_width:
                if bullet_line:
                    page.insert_text(
                        (layout.margin + 20, y),
                        bullet_line.strip(),
                        fontname="helv",
                        fontsize=layout.header_font_size,
                        color=(0, 0, 0),
                    )
                    y += layout.header_font_size * 1.35
                    first_line = False
                bullet_line = word + " "
            else:
                bullet_line = test_line
        if bullet_line:
            page.insert_text(
                (layout.margin + 20, y),
                bullet_line.strip(),
                fontname="helv",
                fontsize=layout.header_font_size,
                color=(0, 0, 0),
            )
            y += layout.header_font_size * 1.35
        y += 10  # Spacing between bullets

    y += 18  # Final spacing after section

    return y


def draw_outline_suggested_improvements_section(
    page: fitz.Page,
    layout: OutlineReportLayout,
    grading: Dict[str, Any],
    start_y: float,
) -> float:
    """
    Draw the "Suggested Improvements" section as a bullet list.
    Returns the Y position after the section.
    """
    y = start_y + 28  # Add spacing before section

    # Section title
    title = "Suggested Improvements"
    page.insert_text(
        (layout.margin, y),
        title,
        fontname="hebo",
        fontsize=layout.title_font_size,
        color=(0, 0, 0),
    )
    y += layout.title_font_size * 1.5

    # Bullet list
    improvements = grading.get("suggested_improvements_for_higher_score", [])
    if not improvements:
        improvements = ["(Not provided)"]

    for bullet in improvements:
        bullet_text = f"- {bullet}"
        bullet_words = bullet_text.split()
        bullet_line = ""
        first_line = True
        for word in bullet_words:
            test_line = bullet_line + word + " "
            text_width = fitz.get_text_length(test_line, fontname="helv", fontsize=layout.header_font_size)
            max_width = layout.page_width_pt - 2 * layout.margin - 30 if first_line else layout.page_width_pt - 2 * layout.margin - 50
            if text_width > max_width:
                if bullet_line:
                    page.insert_text(
                        (layout.margin + 20, y),
                        bullet_line.strip(),
                        fontname="helv",
                        fontsize=layout.header_font_size,
                        color=(0, 0, 0),
                    )
                    y += layout.header_font_size * 1.35
                    first_line = False
                bullet_line = word + " "
            else:
                bullet_line = test_line
        if bullet_line:
            page.insert_text(
                (layout.margin + 20, y),
                bullet_line.strip(),
                fontname="helv",
                fontsize=layout.header_font_size,
                color=(0, 0, 0),
            )
            y += layout.header_font_size * 1.35
        y += 10  # Spacing between bullets

    y += 18  # Final spacing after section

    return y


def convert_outline_report_page_to_pil_image(
    page: fitz.Page,
    dpi: Optional[int] = None,
) -> Image.Image:
    """
    Convert the PyMuPDF report page to a PIL image at the target DPI.
    Returns the image ready for merging with annotated outline pages.
    """
    if dpi is None:
        dpi = OUTLINE_CONFIG.report_dpi

    # PyMuPDF works in points (72 DPI), convert to target DPI
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    return img


def get_outline_grading_schema_hint() -> Dict[str, Any]:
    """
    JSON schema hint for Grok outlining how to grade the outline.

    All criteria and weights are centralized here so changes are in one place.
    """
    return {
        "topic": "",
        "total_outline_marks": 30,
        "overall_rating": "Weak",
        "criteria": [
            {
                "id": "outline_topic_interpretation",
                "criterion": "Topic interpretation and clarity in outline",
                "marks_allocated": 6,
                "marks_awarded_range": "0-0",
                "rating": "Weak",
                "key_comments": "string",
            },
            {
                "id": "outline_coverage",
                "criterion": "Coverage of major dimensions and sub-points",
                "marks_allocated": 8,
                "marks_awarded_range": "0-0",
                "rating": "Weak",
                "key_comments": "string",
            },
            {
                "id": "outline_ordering",
                "criterion": "Logical ordering and hierarchy of points",
                "marks_allocated": 6,
                "marks_awarded_range": "0-0",
                "rating": "Weak",
                "key_comments": "string",
            },
            {
                "id": "outline_balance",
                "criterion": "Balance and proportion across sections",
                "marks_allocated": 5,
                "marks_awarded_range": "0-0",
                "rating": "Weak",
                "key_comments": "string",
            },
            {
                "id": "outline_relevance",
                "criterion": "Relevance of outline points to the given topic",
                "marks_allocated": 5,
                "marks_awarded_range": "0-0",
                "rating": "Weak",
                "key_comments": "string",
            },
        ],
        "total_awarded_range": "0-0",
        "reasons_for_low_score": ["..."],
        "suggested_improvements_for_higher_score": ["..."],
        "overall_comment": "string",
    }


def get_outline_grading_instructions() -> str:
    """
    Build the instruction block for Grok for strict range-based outline grading.
    """
    return (
        "You are a strict FPSC-style CSS English Essay OUTLINE examiner.\n"
        "Grade ONLY the outline, not the full essay paragraphs.\n"
        "Use the provided outline rubric text and schema to assign marks.\n"
        "\n"
        "Marking rules:\n"
        "- For each criterion, output marks_awarded_range as a small integer range like \"6-8\".\n"
        "- Do NOT give a single number; always a range, width at most 3 points.\n"
        "- total_outline_marks is 30; keep totals conservative and exam realistic.\n"
        "- overall_rating must be one of: Excellent, Good, Average, Weak.\n"
        "\n"
        "Reasoning rules:\n"
        "- For each criterion, key_comments must list concrete, exam-style reasons why marks were lost.\n"
        "- Avoid vague phrases like 'needs improvement' or 'lacks depth'; specify EXACT problems in the outline.\n"
        "- Examples: 'missing any points about X', 'points under Y are repeated', "
        "'no clear thesis branch stated at the top', 'sections are out of logical order'.\n"
        "- reasons_for_low_score should summarize the main structural weaknesses that kept the outline score low.\n"
        "- suggested_improvements_for_higher_score must be specific actions the candidate could take to fix the outline.\n"
        "\n"
        "Constraints:\n"
        "- Judge only what is written in the outline; do not imagine missing points.\n"
        "- Do not mention OCR, handwriting, or scanning quality.\n"
        "- Return VALID JSON only matching the schema; no markdown or explanations outside JSON."
    )


def get_outline_annotations_schema_hint() -> Dict[str, Any]:
    """
    JSON schema hint for Grok outlining how to generate outline annotations.
    """
    return {
        "page": 1,
        "annotations": [
            {
                "page": 1,
                "type": "outline_coverage",
                "rubric_point": "Coverage of major dimensions",
                "anchor_quote": "exact substring from OCR_PAGE_TEXT",
                "correction": "what a stronger outline bullet could say",
                "comment": "one-line explanation of what to fix",
            }
        ],
    }


def get_outline_suggestions_schema_hint() -> Dict[str, Any]:
    """
    JSON schema hint for Grok outlining how to generate outline page-level suggestions.
    """
    return {
        "page": 1,
        "page_suggestions": [
            "2-5 short, actionable suggestions focusing on this page's outline only"
        ],
    }


def get_outline_annotations_instructions() -> str:
    """
    Build the instruction block for Grok for outline-focused annotations.
    """
    return (
        "You are an expert CSS English Essay OUTLINE examiner generating pinpoint annotations.\n"
        "You are annotating ONE outline page only (not full essay paragraphs).\n"
        "Primary truth is the page image; OCR text is a helper and may contain errors.\n"
        "\n"
        "Annotation rules:\n"
        "- Generate 2-5 annotations per page.\n"
        "- Every annotation MUST be locatable on the page.\n"
        "- Use these types exactly:\n"
        "  outline_coverage, outline_ordering, outline_balance, outline_relevance, outline_topic_clarity.\n"
        "\n"
        "Anchor quote rule (CRITICAL):\n"
        "- You are given OCR_PAGE_TEXT below.\n"
        "- anchor_quote MUST be an EXACT contiguous substring copied from OCR_PAGE_TEXT.\n"
        "- Use the full relevant sentence/phrase; do NOT paraphrase or correct spelling inside anchor_quote.\n"
        "- If you cannot find a suitable quote in OCR_PAGE_TEXT, set anchor_quote to empty and SKIP that annotation.\n"
        "- For pages with very sparse OCR text (<10 lines), generate fewer annotations (1-2) and only if you can find clear anchor quotes. Skip annotations if anchor_quote cannot be found.\n"
        "\n"
        "Comment rules:\n"
        "- Each comment must be ONE concise line that states the problem and suggests a concrete fix.\n"
        "- Be specific and exam-oriented (e.g., 'add sub-points covering dimension X', "
        "'reorder sections so Y comes before Z', 'remove repeated point about W').\n"
        "- Avoid generic phrases like 'needs improvement' or 'could be better'.\n"
        "\n"
        "Constraints:\n"
        "- Never mention OCR, scanning, handwriting, or legibility.\n"
        "- Focus only on outline structure, coverage, ordering, and relevance.\n"
        "- Return JSON only matching the schema."
    )


def get_outline_suggestions_instructions() -> str:
    """
    Build the instruction block for Grok for outline page-level suggestions only.
    """
    return (
        "You are an expert CSS English Essay OUTLINE examiner generating high-impact suggestions.\n"
        "You are evaluating ONE outline page at a time (no full essay paragraphs).\n"
        "Primary truth is the page image; OCR text is a helper and may contain errors.\n"
        "\n"
        "Suggestion rules:\n"
        "- Generate 2-5 short, exam-style suggestions for THIS PAGE only.\n"
        "- Focus on structural quality of the outline: coverage of dimensions, logical ordering, balance, and relevance.\n"
        "- Each suggestion must be concrete and actionable (e.g., 'add a separate branch for X', "
        "'merge repeated bullets about Y', 'reorder sections so Z comes before W').\n"
        "- Do not reference specific line numbers; talk in terms of outline sections/bullets.\n"
        "\n"
        "Rubric usage:\n"
        "- Use the provided OUTLINE ANNOTATIONS RUBRIC to anchor what counts as strong vs weak outline practice.\n"
        "- Map your suggestions to rubric ideas (coverage, ordering, balance, relevance, topic clarity).\n"
        "\n"
        "Constraints:\n"
        "- Never mention OCR, scanning, handwriting, or legibility.\n"
        "- Do not repeat the same suggestion in different words.\n"
        "- Return JSON only with page_suggestions as described in the schema."
    )


def build_outline_annotation_page_payload(
    *,
    page_number: int,
    ocr_data: Dict[str, Any],
    annotations_rubric_text: str,
    grading_summary: Dict[str, Any],
    structure: Dict[str, Any],
    page_images: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build a per-page annotation payload for Grok.
    """
    # Find the OCR page data for this page number.
    ocr_page_data = None
    for p in ocr_data.get("pages", []):
        if p.get("page_number") == page_number:
            ocr_page_data = p
            break

    if not ocr_page_data:
        raise ValueError(f"OCR data not found for page {page_number}")

    # Build compact OCR page object.
    ocr_page_text = ocr_page_data.get("ocr_page_text") or ""
    lines = []
    for ln in ocr_page_data.get("lines", []):
        line_text = (ln.get("text") or "").strip()
        if line_text:
            lines.append({"text": line_text})

    compact_ocr_page = {
        "page_number": page_number,
        "ocr_page_text": ocr_page_text,
        "lines": lines,
    }

    # Find the page image for this page.
    page_image = None
    for img in page_images:
        if img.get("page") == page_number:
            page_image = img
            break

    # Build grading summary (where marks were lost).
    grading_summary_compact = {
        "overall_rating": grading_summary.get("overall_rating"),
        "total_awarded_range": grading_summary.get("total_awarded_range"),
        "criteria": grading_summary.get("criteria", []),
    }

    # Build structure summary.
    structure_summary = {
        "outline": structure.get("outline", {}),
        "sections": structure.get("sections", []),
    }

    schema_hint = get_outline_annotations_schema_hint()

    return {
        "annotations_rubric_text": annotations_rubric_text or "",
        "grading_summary": grading_summary_compact,
        "structure_detected": structure_summary,
        "ocr_page": compact_ocr_page,
        "ocr_full_text": ocr_data.get("full_text") or "",
        "page_image": page_image,
        "output_schema": schema_hint,
    }


def call_grok_for_outline_page_annotations(
    grok_key: str,
    page_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Call Grok for a single outline page and parse the annotation JSON response.
    """
    instructions = get_outline_annotations_instructions()

    data = _grok_chat(
        grok_api_key=grok_key,
        messages=[
            {"role": "system", "content": "Return VALID JSON only."},
            {"role": "user", "content": instructions + "\n\nDATA:\n" + json.dumps(page_payload, ensure_ascii=False)},
        ],
        model=OUTLINE_CONFIG.grok_model_outline_annotations,
        temperature=OUTLINE_CONFIG.grok_temperature_outline_annotations,
    )

    content = data["choices"][0]["message"]["content"]
    cleaned = clean_json_from_llm(content)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse Grok outline annotations JSON: {exc}") from exc

    # Extract and normalize annotations only (page_suggestions are handled separately).
    annotations = parsed.get("annotations") or []
    if not isinstance(annotations, list):
        annotations = []

    # Ensure each annotation has a page number.
    page_number = page_payload.get("ocr_page", {}).get("page_number")
    for ann in annotations:
        if not isinstance(ann, dict):
            continue
        if "page" not in ann or ann.get("page") is None:
            ann["page"] = page_number

    return {
        "annotations": annotations,
    }


def _norm_ws(s: str) -> str:
    """
    Normalize whitespace for substring matching.
    """
    return re.sub(r"\s+", " ", (s or "").strip())


def _anchor_is_valid(anchor: str, ocr_page_text: str) -> bool:
    """
    Check if anchor_quote is a valid substring of OCR page text.
    """
    a = _norm_ws(anchor)
    t = _norm_ws(ocr_page_text)
    if not a or len(a.split()) < 3:
        return False
    # Exact substring check (whitespace-normalized).
    return a in t


def validate_and_filter_outline_annotations(
    annotations: List[Dict[str, Any]],
    ocr_page_text: str,
    *,
    strict_mode: bool = False,
    sparse_page: bool = False,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Validate anchor quotes and filter invalid annotations.

    When sparse_page=True (e.g. <10 OCR lines), use lenient validation:
    keep all annotations even without exact anchor match, since OCR is often
    unreliable on sparse pages.

    Returns:
        (valid_annotations, invalid_count)
    """
    valid_annotations: List[Dict[str, Any]] = []
    invalid_count = 0

    for ann in annotations:
        if not isinstance(ann, dict):
            invalid_count += 1
            continue

        anchor_quote = ann.get("anchor_quote", "")
        if not anchor_quote:
            if not sparse_page:
                invalid_count += 1
            if not strict_mode or sparse_page:
                ann["anchor_missing"] = True
                valid_annotations.append(ann)
            continue

        if _anchor_is_valid(anchor_quote, ocr_page_text):
            valid_annotations.append(ann)
        else:
            if not sparse_page:
                invalid_count += 1
            if not strict_mode or sparse_page:
                ann["anchor_invalid"] = True
                valid_annotations.append(ann)

    return valid_annotations, invalid_count


def _load_partial_outline_annotations(path: str) -> Dict[str, Any]:
    """
    Load partial annotations from disk if they exist.
    """
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_partial_outline_annotations(path: str, data: Dict[str, Any]) -> None:
    """
    Save partial annotations to disk for recovery.
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _clear_partial_outline_annotations() -> None:
    """
    Clear partial annotation and suggestion JSON files at the start of a new pipeline run.
    This prevents results from one essay from being reused for another essay.
    """
    partial_ann_path = OUTLINE_CONFIG.debug_annotations_partial_json
    partial_sugg_path = OUTLINE_CONFIG.debug_annotations_partial_json.replace(".json", "_suggestions.json")
    
    for path in [partial_ann_path, partial_sugg_path]:
        if os.path.isfile(path):
            try:
                os.remove(path)
            except Exception:
                pass  # Ignore errors if file is locked or doesn't exist


def _process_single_page_annotations(
    args_tuple: Tuple[int, str, Dict[str, Any], str, int, bool, int]
) -> Tuple[int, Optional[Dict[str, Any]], Optional[str]]:
    """
    Process annotations for a single page. Returns (page_number, result_dict, error_message).
    Used for parallel processing.
    """
    page_number, grok_key, page_payload, ocr_page_text, max_page_attempts, strict_anchor_validation, ocr_line_count = args_tuple
    
    # Retry loop for this page.
    last_err: Exception | None = None
    parsed: Dict[str, Any] | None = None

    for attempt in range(1, max_page_attempts + 1):
        try:
            result = call_grok_for_outline_page_annotations(grok_key=grok_key, page_payload=page_payload)
            parsed = result
            break
        except Exception as exc:
            last_err = exc
            if attempt < max_page_attempts:
                continue

    if parsed is None:
        error_msg = str(last_err) if last_err else "Unknown error"
        return (page_number, None, error_msg)

    # Validate anchor quotes. Use lenient validation for sparse pages (<10 lines).
    page_annotations = parsed.get("annotations") or []
    sparse_page = ocr_line_count < 10
    valid_ann, invalid_count = validate_and_filter_outline_annotations(
        page_annotations, ocr_page_text, strict_mode=strict_anchor_validation, sparse_page=sparse_page
    )

    # For sparse pages (<10 OCR lines), anchor matching is often unreliable - suppress warning
    if invalid_count > 0 and ocr_line_count >= 10:
        print(f"  [Page {page_number}] Warning: {invalid_count}/{len(page_annotations)} annotations have invalid/missing anchor_quote")

    # Normalize annotation fields.
    cleaned_ann = []
    for ann in valid_ann:
        if not isinstance(ann, dict):
            continue
        if ann.get("page") is None:
            ann["page"] = page_number
        # Ensure required fields exist.
        for key in ["type", "rubric_point", "anchor_quote", "correction", "comment"]:
            if key not in ann:
                ann[key] = ""
        cleaned_ann.append(ann)

    return (page_number, {"annotations": cleaned_ann}, None)


def generate_outline_annotations(
    grok_key: str,
    annotations_rubric_text: str,
    ocr_data: Dict[str, Any],
    structure: Dict[str, Any],
    grading: Dict[str, Any],
    page_images: List[Dict[str, Any]],
    *,
    max_page_attempts: int = 2,
    strict_anchor_validation: bool = False,
) -> Dict[str, Any]:
    """
    Generate inline outline annotations for all outline pages with retries and
    partial result saving. This function is focused on anchor-based annotations
    only; page-level suggestions are handled by a separate generator.
    Uses parallel processing for improved performance.
    """
    partial_path = OUTLINE_CONFIG.debug_annotations_partial_json
    partial = _load_partial_outline_annotations(partial_path)

    annotations: List[Dict[str, Any]] = partial.get("annotations") or []
    errors: List[Dict[str, Any]] = partial.get("errors") or []
    completed_pages = set(partial.get("completed_pages") or [])

    outline = structure.get("outline") or {}
    outline_pages = outline.get("pages") or []
    if not outline_pages:
        # If no pages detected, use all pages from OCR.
        outline_pages = [p.get("page_number") for p in ocr_data.get("pages", []) if p.get("page_number")]

    # Build grading summary for context.
    grading_summary = {
        "overall_rating": grading.get("overall_rating"),
        "total_awarded_range": grading.get("total_awarded_range"),
        "criteria": grading.get("criteria", []),
    }

    # Prepare pages for parallel processing
    pages_to_process: List[Tuple[int, str, Dict[str, Any], str, int, bool]] = []
    
    for page_number in outline_pages:
        if not isinstance(page_number, int):
            continue
        if page_number in completed_pages:
            continue

        # Build page payload.
        try:
            page_payload = build_outline_annotation_page_payload(
                page_number=page_number,
                ocr_data=ocr_data,
                annotations_rubric_text=annotations_rubric_text,
                grading_summary=grading_summary,
                structure=structure,
                page_images=page_images,
            )
        except Exception as exc:
            errors.append({"page": page_number, "error": f"Failed to build page payload: {exc}"})
            continue

        ocr_page_text = page_payload.get("ocr_page", {}).get("ocr_page_text", "")
        ocr_line_count = len(page_payload.get("ocr_page", {}).get("lines", []))
        # Skip empty pages early to avoid expensive Grok API calls
        if not ocr_page_text or len(ocr_page_text.strip()) < 10:
            completed_pages.add(page_number)
            continue
        # Skip very sparse pages (<5 lines) - too little content to annotate meaningfully
        if ocr_line_count < 5:
            completed_pages.add(page_number)
            continue

        # Add to processing queue (include ocr_line_count for lenient validation)
        pages_to_process.append((page_number, grok_key, page_payload, ocr_page_text, max_page_attempts, strict_anchor_validation, ocr_line_count))

    # Process pages in parallel
    if pages_to_process:
        print(f"  Processing {len(pages_to_process)} pages in parallel...")
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_process_single_page_annotations, args): args[0] for args in pages_to_process}
            
            for future in as_completed(futures):
                page_number = futures[future]
                try:
                    result_page_num, result_dict, error_msg = future.result()
                    
                    if error_msg:
                        errors.append({"page": result_page_num, "error": error_msg})
                        completed_pages.add(result_page_num)
                    elif result_dict:
                        page_annotations = result_dict.get("annotations", [])
                        annotations.extend(page_annotations)
                        completed_pages.add(result_page_num)
                    
                    # Save partial results periodically (every page)
                    _save_partial_outline_annotations(
                        partial_path,
                        {
                            "annotations": annotations,
                            "errors": errors,
                            "completed_pages": sorted(completed_pages),
                        },
                    )
                except Exception as exc:
                    errors.append({"page": page_number, "error": f"Unexpected error: {exc}"})
                    completed_pages.add(page_number)
                    _save_partial_outline_annotations(
                        partial_path,
                        {
                            "annotations": annotations,
                            "errors": errors,
                            "completed_pages": sorted(completed_pages),
                        },
                    )

    if not annotations and errors:
        raise RuntimeError(f"All outline annotation requests failed. See {partial_path} for details.")

    return {
        "annotations": annotations,
        "errors": errors,
    }


def _process_single_page_suggestions(
    args_tuple: Tuple[int, str, Dict[str, Any], str, int]
) -> Tuple[int, Optional[List[str]], Optional[str]]:
    """
    Process suggestions for a single page. Returns (page_number, suggestions_list, error_message).
    Used for parallel processing.
    """
    page_number, grok_key, payload, instructions, max_page_attempts = args_tuple
    
    # Retry loop for this page.
    last_err: Exception | None = None
    parsed: Dict[str, Any] | None = None

    for attempt in range(1, max_page_attempts + 1):
        try:
            data = _grok_chat(
                grok_api_key=grok_key,
                messages=[
                    {"role": "system", "content": "Return VALID JSON only."},
                    {"role": "user", "content": instructions + "\n\nDATA:\n" + json.dumps(payload, ensure_ascii=False)},
                ],
                model=OUTLINE_CONFIG.grok_model_outline_suggestions,
                temperature=OUTLINE_CONFIG.grok_temperature_outline_suggestions,
            )
            content = data["choices"][0]["message"]["content"]
            cleaned = clean_json_from_llm(content)
            parsed = json.loads(cleaned)
            break
        except Exception as exc:
            last_err = exc
            if attempt < max_page_attempts:
                continue

    if parsed is None:
        error_msg = str(last_err) if last_err else "Unknown error"
        return (page_number, None, error_msg)

    sugg = parsed.get("page_suggestions") or []
    if not isinstance(sugg, list):
        sugg = []

    return (page_number, sugg, None)


def generate_outline_suggestions(
    grok_key: str,
    annotations_rubric_text: str,
    ocr_data: Dict[str, Any],
    structure: Dict[str, Any],
    grading: Dict[str, Any],
    page_images: List[Dict[str, Any]],
    *,
    max_page_attempts: int = 2,
) -> Dict[str, Any]:
    """
    Generate page-level outline suggestions for all outline pages.
    Uses parallel processing for improved performance.

    Returns:
        {
            "page_suggestions": [...],
            "errors": [...]
        }
    """
    partial_path = OUTLINE_CONFIG.debug_annotations_partial_json.replace(
        ".json", "_suggestions.json"
    )
    partial = _load_partial_outline_annotations(partial_path)

    page_suggestions: List[Dict[str, Any]] = partial.get("page_suggestions") or []
    errors: List[Dict[str, Any]] = partial.get("errors") or []
    completed_pages = set(partial.get("completed_pages") or [])

    outline = structure.get("outline") or {}
    outline_pages = outline.get("pages") or []
    if not outline_pages:
        outline_pages = [p.get("page_number") for p in ocr_data.get("pages", []) if p.get("page_number")]

    # Build grading summary for context (where marks were lost).
    grading_summary = {
        "overall_rating": grading.get("overall_rating"),
        "total_awarded_range": grading.get("total_awarded_range"),
        "criteria": grading.get("criteria", []),
    }

    schema_hint = get_outline_suggestions_schema_hint()
    instructions = get_outline_suggestions_instructions()

    # Prepare pages for parallel processing
    pages_to_process: List[Tuple[int, str, Dict[str, Any], str, int]] = []

    for page_number in outline_pages:
        if not isinstance(page_number, int):
            continue
        if page_number in completed_pages:
            continue

        # Find the OCR page data for this page number.
        ocr_page_data = None
        for p in ocr_data.get("pages", []):
            if p.get("page_number") == page_number:
                ocr_page_data = p
                break

        if not ocr_page_data:
            errors.append({"page": page_number, "error": "Missing OCR data for suggestions"})
            continue

        # Find the page image for this page.
        page_image = None
        for img in page_images:
            if img.get("page") == page_number:
                page_image = img
                break

        ocr_page_text = ocr_page_data.get("ocr_page_text") or ""
        # Skip empty pages early to avoid expensive Grok API calls
        if not ocr_page_text or len(ocr_page_text.strip()) < 10:
            # Mark as completed without error (empty pages don't need suggestions)
            completed_pages.add(page_number)
            continue

        # Compact payload for suggestions on this page.
        compact_ocr_page = {
            "page_number": page_number,
            "ocr_page_text": ocr_page_text,
        }
        structure_summary = {
            "outline": structure.get("outline", {}),
            "sections": structure.get("sections", []),
        }

        payload = {
            "annotations_rubric_text": annotations_rubric_text or "",
            "grading_summary": grading_summary,
            "structure_detected": structure_summary,
            "ocr_page": compact_ocr_page,
            "ocr_full_text": ocr_data.get("full_text") or "",
            "page_image": page_image,
            "output_schema": schema_hint,
        }

        # Add to processing queue
        pages_to_process.append((page_number, grok_key, payload, instructions, max_page_attempts))

    # Process pages in parallel
    if pages_to_process:
        print(f"  Processing {len(pages_to_process)} pages in parallel...")
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_process_single_page_suggestions, args): args[0] for args in pages_to_process}
            
            for future in as_completed(futures):
                page_number = futures[future]
                try:
                    result_page_num, sugg_list, error_msg = future.result()
                    
                    if error_msg:
                        errors.append({"page": result_page_num, "error": error_msg})
                        completed_pages.add(result_page_num)
                    elif sugg_list is not None:
                        page_suggestions.append({"page": result_page_num, "suggestions": sugg_list})
                        completed_pages.add(result_page_num)
                    
                    # Save partial results periodically (every page)
                    _save_partial_outline_annotations(
                        partial_path,
                        {
                            "page_suggestions": page_suggestions,
                            "errors": errors,
                            "completed_pages": sorted(completed_pages),
                        },
                    )
                except Exception as exc:
                    errors.append({"page": page_number, "error": f"Unexpected error: {exc}"})
                    completed_pages.add(page_number)
                    _save_partial_outline_annotations(
                        partial_path,
                        {
                            "page_suggestions": page_suggestions,
                            "errors": errors,
                            "completed_pages": sorted(completed_pages),
                        },
                    )

    return {
        "page_suggestions": page_suggestions,
        "errors": errors,
    }


def draw_annotations_on_outline_pages(
    pdf_path: str,
    ocr_data: Dict[str, Any],
    structure: Dict[str, Any],
    grading: Dict[str, Any],
    annotations: List[Dict[str, Any]],
    page_suggestions: List[Dict[str, Any]],
    *,
    dpi: Optional[int] = None,
    spelling_errors: Optional[List[Dict[str, Any]]] = None,
) -> List[Image.Image]:
    """
    Step 7: Draw annotations on outline pages.
    
    Uses OCR locations and annotation text to highlight outline bullets or lines
    and place short comments near them. Also draws spelling/grammar error annotations
    with red boxes and corrections.
    
    Returns a list of PIL images, one for each annotated outline page.
    """
    if dpi is None:
        dpi = OUTLINE_CONFIG.ocr_render_dpi

    print("Drawing annotations on outline pages...")
    
    annotated_pages = annotate_pdf_outline_pages(
        pdf_path=pdf_path,
        ocr_data=ocr_data,
        structure=structure,
        grading=grading,
        annotations=annotations,
        page_suggestions=page_suggestions,
        dpi=dpi,
        spelling_errors=spelling_errors or [],
    )
    
    print(f"✓ Annotated {len(annotated_pages)} outline pages")
    
    return annotated_pages


def build_outline_grading_payload(
    *,
    outline_rubric_text: str,
    ocr_data: Dict[str, Any],
    structure: Dict[str, Any],
    page_images: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build the grading payload from OCR + detected outline structure.
    """
    outline = structure.get("outline") or {}
    sections = structure.get("sections") or []
    overall_comment = structure.get("overall_comment") or ""

    outline_pages = outline.get("pages") or []
    outline_pages_set = {p for p in outline_pages if isinstance(p, int)}

    # Outline-only pipeline: usually all pages are outline pages.
    # If Grok detected a subset, filter images to those pages.
    if outline_pages_set:
        grading_page_images = [p for p in page_images if p.get("page") in outline_pages_set]
    else:
        grading_page_images = page_images

    # Lightweight preview helps Grok connect text to images without sending full OCR geometry.
    ocr_pages_preview: List[Dict[str, Any]] = []
    for p in ocr_data.get("pages", []):
        page_num = p.get("page_number")
        if outline_pages_set and page_num not in outline_pages_set:
            continue
        lines = [ln.get("text", "") for ln in p.get("lines", []) if (ln.get("text") or "").strip()]
        ocr_pages_preview.append({"page_number": page_num, "lines_preview": lines})

    schema_hint = get_outline_grading_schema_hint()

    return {
        "outline_rubric_text": outline_rubric_text or "",
        "structure_detected": {
            "outline": outline,
            "sections": sections,
            "overall_comment": overall_comment,
        },
        "ocr_full_text": (ocr_data.get("full_text") or ""),
        "ocr_pages_preview": ocr_pages_preview,
        "page_images": grading_page_images,
        "output_schema": schema_hint,
    }


def call_grok_for_outline_grading(
    grok_key: str,
    outline_rubric_text: str,
    ocr_data: Dict[str, Any],
    structure: Dict[str, Any],
    page_images: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Call Grok with the outline grading prompt and payload and parse the JSON response.
    """
    instructions = get_outline_grading_instructions()
    payload = build_outline_grading_payload(
        outline_rubric_text=outline_rubric_text,
        ocr_data=ocr_data,
        structure=structure,
        page_images=page_images,
    )

    data = _grok_chat(
        grok_api_key=grok_key,
        messages=[
            {"role": "system", "content": "Return VALID JSON only."},
            {"role": "user", "content": instructions + "\n\nDATA:\n" + json.dumps(payload, ensure_ascii=False)},
        ],
        model=OUTLINE_CONFIG.grok_model_outline_grading,
        temperature=OUTLINE_CONFIG.grok_temperature_outline_grading,
    )
    content = data["choices"][0]["message"]["content"]
    cleaned = clean_json_from_llm(content)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse Grok outline grading JSON: {exc}") from exc

    return parsed


def _parse_range(rng: str) -> Tuple[int, int]:
    """
    Parse a mark range string like "6-8" into (lo, hi).
    Handles various separators: "-", "–", "—", "to".
    """
    s = str(rng or "").strip()
    if not s:
        return 0, 0

    # Normalize separators.
    s = s.replace("–", "-").replace("—", "-")
    s = s.replace(" to ", "-").replace(" TO ", "-")
    s = "".join(s.split())

    parts = s.split("-")
    if len(parts) != 2:
        return 0, 0

    try:
        lo = int(parts[0])
        hi = int(parts[1])
    except ValueError:
        return 0, 0

    if hi < lo:
        lo, hi = hi, lo

    return lo, hi


def _normalize_outline_grading_ranges(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize mark ranges, pick single values, compute total, and derive total range.
    """
    criteria = parsed.get("criteria") or []
    if not criteria:
        return parsed

    # Process each criterion: parse range, clamp width, pick single value.
    for c in criteria:
        rng = c.get("marks_awarded_range", "0-0")
        lo, hi = _parse_range(rng)

        # Clamp range width to max 3.
        if hi - lo > 3:
            hi = lo + 3
        lo = max(0, lo)
        hi = max(lo, hi)

        c["marks_awarded_range"] = f"{lo}-{hi}"

        # Pick single value: 50% chance of minimum, 50% chance of maximum.
        if random.random() < 0.5:
            marks_awarded = lo
        else:
            marks_awarded = hi

        c["marks_awarded"] = marks_awarded

    # Calculate total from single values.
    total = sum(c.get("marks_awarded", 0) for c in criteria)

    # Optional cap: if total exceeds 30, scale down proportionally.
    max_total = parsed.get("total_outline_marks", 30)
    if total > max_total and criteria:
        scale = float(max_total) / float(total)
        for c in criteria:
            original = c.get("marks_awarded", 0)
            scaled = max(0, int(round(original * scale)))
            c["marks_awarded"] = scaled
        total = sum(c.get("marks_awarded", 0) for c in criteria)

    # Derive total range as (total-2) to (total+2) - 4-point range.
    total_lo = max(0, total - 2)
    total_hi = min(max_total, total + 2)
    parsed["total_awarded_range"] = f"{total_lo}-{total_hi}"

    return parsed


def _validate_outline_grading(data: Dict[str, Any]) -> bool:
    """
    Check that all required fields exist and grading is valid.
    """
    criteria = data.get("criteria")
    if not isinstance(criteria, list) or len(criteria) < 3:
        return False

    if not isinstance(data.get("total_awarded_range"), str):
        return False

    if data.get("topic") is None:
        return False

    rating = data.get("overall_rating")
    if rating not in ("Excellent", "Good", "Average", "Weak"):
        return False

    # Check that at least some criteria have non-zero marks.
    all_zero = True
    for crit in criteria:
        rng = crit.get("marks_awarded_range", "0-0")
        lo, hi = _parse_range(rng)
        if lo > 0 or hi > 0:
            all_zero = False
            break

    if all_zero:
        return False

    return True


def grade_outline_with_rubric(
    grok_key: str,
    outline_rubric_text: str,
    ocr_data: Dict[str, Any],
    structure: Dict[str, Any],
    page_images: List[Dict[str, Any]],
    *,
    max_attempts: int = 4,
) -> Dict[str, Any]:
    """
    Grade the outline using Grok, normalize ranges, validate, and retry if needed.
    """
    last_error: Exception | None = None
    parsed: Dict[str, Any] | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            parsed = call_grok_for_outline_grading(
                grok_key=grok_key,
                outline_rubric_text=outline_rubric_text,
                ocr_data=ocr_data,
                structure=structure,
                page_images=page_images,
            )
            parsed = _normalize_outline_grading_ranges(parsed)
            if _validate_outline_grading(parsed):
                return parsed
            last_error = ValueError("Invalid grading JSON: missing required fields or all zero marks")
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                continue

    if parsed is None:
        raise RuntimeError(f"Grok outline grading failed after {max_attempts} attempts: {last_error}")

    raise RuntimeError(
        f"Grok outline grading output invalid after {max_attempts} attempts. "
        f"Last error: {last_error}. Last parsed data: {json.dumps(parsed, indent=2)[:500]}"
    )


def load_environment() -> Tuple[str, DocumentAnalysisClient]:
    """
    Load Grok and Azure keys from the environment and create the Azure OCR client.
    """
    load_dotenv()
    grok_key = os.getenv(OUTLINE_CONFIG.grok_env_key)
    azure_endpoint = os.getenv(OUTLINE_CONFIG.azure_endpoint_env_key)
    azure_key = os.getenv(OUTLINE_CONFIG.azure_key_env_key)

    missing = []
    if not grok_key:
        missing.append(OUTLINE_CONFIG.grok_env_key)
    if not azure_endpoint:
        missing.append(OUTLINE_CONFIG.azure_endpoint_env_key)
    if not azure_key:
        missing.append(OUTLINE_CONFIG.azure_key_env_key)

    if missing:
        joined = ", ".join(missing)
        raise EnvironmentError(f"Missing environment variable(s): {joined}. Please set them in your .env file.")

    doc_client = DocumentAnalysisClient(endpoint=azure_endpoint, credential=AzureKeyCredential(azure_key))
    return grok_key, doc_client


@dataclass
class OcrContext:
    """
    Prepared OCR settings and client for the outline pipeline.
    """

    grok_key: str
    client: DocumentAnalysisClient
    model_name: str
    render_dpi: int
    workers: int
    debug_pages_dir: str
    debug_ocr_json: str
    debug_ocr_text: str


def prepare_ocr_context() -> OcrContext:
    """
    Prepare OCR configuration and a single Azure client instance for all pages.
    """
    grok_key, client = load_environment()
    return OcrContext(
        grok_key=grok_key,
        client=client,
        model_name=OUTLINE_CONFIG.ocr_model_name,
        render_dpi=OUTLINE_CONFIG.ocr_render_dpi,
        workers=OUTLINE_CONFIG.ocr_workers,
        debug_pages_dir=OUTLINE_CONFIG.debug_ocr_pages_dir,
        debug_ocr_json=OUTLINE_CONFIG.debug_ocr_json,
        debug_ocr_text=OUTLINE_CONFIG.debug_ocr_text,
    )


def render_pdf_to_pil_pages(pdf_path: str, dpi: int | None = None) -> List[Tuple[int, Image.Image]]:
    """
    Open the input PDF once and render each page as a PIL image at the given DPI.
    """
    if dpi is None:
        dpi = OUTLINE_CONFIG.ocr_render_dpi

    doc = fitz.open(pdf_path)
    pages: List[Tuple[int, Image.Image]] = []
    try:
        for idx in range(doc.page_count):
            page = doc[idx]
            pix = page.get_pixmap(dpi=dpi)
            pil_image = Image.open(io.BytesIO(pix.tobytes("png")))
            pages.append((idx + 1, pil_image))
    finally:
        doc.close()

    return pages


def encode_pil_page_for_grok(pil_img: Image.Image, max_dim: int | None = None, quality: int = 70) -> bytes:
    """
    Convert a PIL page image to compressed JPEG bytes for Grok, downscaling if needed.
    """
    if max_dim is None:
        max_dim = OUTLINE_CONFIG.grok_max_dim

    img = pil_img.copy()
    # Downscale so that neither width nor height exceeds max_dim.
    img.thumbnail((max_dim, max_dim), Image.LANCZOS)

    if img.mode != "RGB":
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format=OUTLINE_CONFIG.grok_image_format, quality=quality, optimize=True)
    return buf.getvalue()


def build_grok_page_images_for_outline(pdf_path: str) -> List[Dict[str, Any]]:
    """
    Render outline pages, encode them to base64, and enforce Grok payload limits.
    """
    pil_pages = render_pdf_to_pil_pages(pdf_path)
    if not pil_pages:
        return []

    max_total = OUTLINE_CONFIG.grok_max_total_base64_chars
    images_dir = OUTLINE_CONFIG.grok_images_dir
    if images_dir:
        os.makedirs(images_dir, exist_ok=True)

    dim_candidates = [OUTLINE_CONFIG.grok_max_dim, 640, 560, 512, 448, 384, 320]
    # Keep first unique and sorted descending by size.
    seen_dims = set()
    dim_candidates = [d for d in dim_candidates if not (d in seen_dims or seen_dims.add(d))]
    quality_candidates = [70, 60, 50, 40]

    def _encode_all(dim: int, quality: int, save_files: bool) -> Tuple[List[Dict[str, Any]], int]:
        page_entries: List[Dict[str, Any]] = []
        total_chars = 0
        for page_number, pil_img in pil_pages:
            jpeg_bytes = encode_pil_page_for_grok(pil_img, max_dim=dim, quality=quality)
            b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
            total_chars += len(b64)

            file_path = None
            if save_files and images_dir:
                file_path = os.path.join(images_dir, f"page_{page_number:03d}.jpg")
                with open(file_path, "wb") as f:
                    f.write(jpeg_bytes)

            page_entries.append(
                {
                    "page": page_number,
                    "image_base64": b64,
                    "file_path": file_path,
                    "truncated": False,
                }
            )
        return page_entries, total_chars

    chosen: Tuple[List[Dict[str, Any]], int, int, int] | None = None
    for dim in dim_candidates:
        for quality in quality_candidates:
            entries, total_chars = _encode_all(dim, quality, save_files=False)
            chosen = (entries, total_chars, dim, quality)
            if max_total and total_chars > max_total:
                continue
            # Within budget: re‑encode with files and return.
            final_entries, final_total = _encode_all(dim, quality, save_files=True)
            return final_entries

    # If nothing fit within the budget, use the smallest settings and truncate base64 strings.
    if chosen is None:
        return []

    entries, total_chars, dim, quality = chosen
    final_entries, _ = _encode_all(dim, quality, save_files=True)

    if max_total and total_chars > max_total and final_entries:
        # Truncate proportionally across pages to respect the global budget.
        scale = max_total / float(total_chars)
        new_total = 0
        for entry in final_entries:
            b64 = entry["image_base64"]
            new_len = max(1, int(len(b64) * scale))
            if new_len < len(b64):
                entry["image_base64"] = b64[:new_len]
                entry["truncated"] = True
            new_total += len(entry["image_base64"])

    return final_entries


def clean_json_from_llm(text: str) -> str:
    """
    Remove simple markdown code fences around JSON produced by the LLM.
    """
    s = (text or "").strip()
    if not s:
        return ""
    if s.startswith("```"):
        # Strip opening ``` or ```json
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()


def _grok_chat(
    grok_api_key: str,
    messages: List[Dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.15,
    timeout: int | None = None,
    max_retries: int = 5,
    backoff_base: float = 2.0,
    backoff_max: float = 30.0,
) -> Dict[str, Any]:
    """
    Call the Grok chat completions API with basic retry handling.
    """
    if model is None:
        model = OUTLINE_CONFIG.grok_model_outline_structure
    if timeout is None:
        timeout = OUTLINE_CONFIG.grok_request_timeout_seconds

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {grok_api_key}",
    }
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                "https://api.x.ai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=(30, timeout),
            )
            if resp.status_code >= 300:
                err = RuntimeError(f"Grok API error {resp.status_code}: {resp.text}")
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    last_error = err
                    delay = min(backoff_max, backoff_base ** attempt)
                    time.sleep(delay)
                    continue
                raise err
            return resp.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_error = exc
            if attempt >= max_retries:
                raise
            delay = min(backoff_max, backoff_base ** attempt)
            time.sleep(delay)

    raise RuntimeError(f"Grok request failed after retries: {last_error}")


def detect_outline_structure_with_grok(
    grok_key: str,
    ocr_data: Dict[str, Any],
    page_images: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Ask Grok how the outline is structured across the pages and what main sections exist.
    """
    system = {
        "role": "system",
        "content": (
            "You are an expert CSS English Essay OUTLINE examiner.\n"
            "You only see the outline pages (no full essay paragraphs).\n"
            "Primary truth is the page images; OCR text is a helper and may contain errors.\n"
            "Do not mention OCR quality or scanning; talk only about the outline itself.\n"
            "Return JSON only."
        ),
    }

    # Lightweight OCR preview for each page: just the list of line texts.
    sanitized_pages: List[Dict[str, Any]] = []
    for p in ocr_data.get("pages", []):
        lines = [line.get("text", "") for line in p.get("lines", []) if (line.get("text") or "").strip()]
        sanitized_pages.append(
            {
                "page_number": p.get("page_number"),
                "lines_preview": lines,
            }
        )

    payload = {
        "task": (
            "Analyze the outline only (no full essay). "
            "Identify which pages contain the outline, how it is broken into sections, "
            "and give a short comment on overall outline structure and coverage."
        ),
        "rules": [
            "Assume all provided pages are part of the outline unless clearly blank.",
            "Do not invent sections that are not visible in the images.",
            "Use the exact wording from the outline for section titles when possible.",
            "If parts are unreadable, say 'content unclear' instead of blaming OCR or scan quality.",
        ],
        "ocr_pages_preview": sanitized_pages,
        "ocr_full_text": ocr_data.get("full_text") or "",
        "page_images": page_images,
        "output_schema": {
            "outline": {
                "present": True,
                "pages": [1],
                "quality": "Weak",
                "issues": ["..."],
                "strengths": ["..."],
            },
            "sections": [
                {
                    "title": "Section title as written",
                    "page": 1,
                    "order_index": 1,
                    "notes": "short remark about this section",
                }
            ],
            "overall_comment": "short summary comment on the outline as a whole",
        },
    }

    data = _grok_chat(
        grok_api_key=grok_key,
        messages=[
            system,
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=OUTLINE_CONFIG.grok_model_outline_structure,
        temperature=0.12,
    )
    content = data["choices"][0]["message"]["content"]
    cleaned = clean_json_from_llm(content)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse Grok outline structure JSON: {exc}") from exc

    # Basic normalization and defaults.
    outline = parsed.get("outline") or {}
    if "pages" not in outline or not outline.get("pages"):
        all_pages = sorted({p.get("page") for p in page_images if p.get("page") is not None})
        if all_pages:
            outline["pages"] = all_pages
    if "present" not in outline:
        outline["present"] = bool(outline.get("pages"))

    parsed["outline"] = outline
    if "sections" not in parsed or not isinstance(parsed["sections"], list):
        parsed["sections"] = []
    if "overall_comment" not in parsed:
        parsed["overall_comment"] = ""

    return parsed


def _encode_pil_image_for_ocr(pil_img: Image.Image, scale: float, quality: int) -> bytes:
    """
    Compress a PIL image to JPEG bytes for Azure OCR.
    """
    img = pil_img.copy()
    if scale != 1.0:
        new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        img = img.resize(new_size, Image.LANCZOS)
    if img.mode != "RGB":
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def analyze_outline_page_with_azure(context: OcrContext, pil_img: Image.Image):
    """
    Encode a page image and call Azure OCR with retries using stronger compression if needed.
    """
    attempts = [(1.0, 75), (0.85, 70), (0.7, 60)]
    last_error: Exception | None = None

    for scale, quality in attempts:
        try:
            img_bytes = _encode_pil_image_for_ocr(pil_img, scale=scale, quality=quality)
            poller = context.client.begin_analyze_document(context.model_name, document=img_bytes)
            return poller.result()
        except HttpResponseError as exc:
            last_error = exc
            # If the error suggests the image is too large, try the next compression level.
            if "InvalidContentLength" in str(exc) or "RequestBodyTooLarge" in str(exc):
                continue
            raise

    if last_error is not None:
        raise RuntimeError(f"Azure OCR failed after retries: {last_error}") from last_error
    raise RuntimeError("Azure OCR failed after retries for unknown reasons.")


def pil_images_to_pdf_bytes_outline(pages: List[Image.Image]) -> bytes:
    """
    Convert a list of PIL images into PDF bytes for the outline pipeline.
    """
    out = io.BytesIO()
    # Filter out None values (empty pages that were skipped during rendering)
    pages = [p for p in pages if p is not None]
    if not pages:
        return b""
    pages_rgb = [p.convert("RGB") for p in pages]
    pages_rgb[0].save(out, format="PDF", save_all=True, append_images=pages_rgb[1:])
    return out.getvalue()


def merge_outline_report_and_annotated_pages(
    report_pages: List[Image.Image],
    annotated_pages: List[Image.Image],
    output_pdf_path: str,
) -> None:
    """
    Step 8: Merge report page(s) and annotated outline pages into a final PDF.

    Creates a new PDF, inserts the report pages first, then the annotated outline pages,
    and saves it to output_pdf_path. Callers can optionally run compress_pdf_if_needed
    afterwards to keep file size under a chosen limit.
    """
    report_pdf = pil_images_to_pdf_bytes_outline(report_pages)
    answer_pdf = pil_images_to_pdf_bytes_outline(annotated_pages)

    out_doc = fitz.open()
    if report_pdf:
        rdoc = fitz.open("pdf", report_pdf)
        out_doc.insert_pdf(rdoc)
        rdoc.close()

    if answer_pdf:
        adoc = fitz.open("pdf", answer_pdf)
        out_doc.insert_pdf(adoc)
        adoc.close()

    out_doc.save(output_pdf_path)
    out_doc.close()


def _is_page_likely_empty(pil_img: Image.Image, threshold_pixels: int = 1000) -> bool:
    """
    Quick check if page is likely empty (mostly white space).
    Returns True if page appears to have minimal content.
    Skips expensive Azure OCR for empty pages.
    """
    try:
        gray = pil_img.convert("L")
        arr = np.array(gray)
        non_white = int(np.sum(arr < 240))  # Pixels darker than light gray
        return non_white < threshold_pixels
    except Exception:
        return False


def _is_noise_text(text: str, bbox: List[Tuple[int, int]], page_w: float, page_h: float) -> bool:
    """
    Filter out very short or very tiny text fragments that are likely noise.
    """
    if not text:
        return True
    if len(text.strip()) <= 2:
        return True
    if not bbox or not page_w or not page_h:
        return False

    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    if not xs or not ys:
        return False

    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    rel_w = w / max(1.0, page_w)
    rel_h = h / max(1.0, page_h)
    if rel_w < 0.002 or rel_h < 0.002:
        return True
    return False


def _process_single_page_ocr(
    args: Tuple[int, Image.Image, OcrContext]
) -> Dict[str, Any]:
    """
    Process OCR for a single page. Returns page payload dict.
    Used for parallel OCR processing.
    """
    page_number, pil_img, context = args

    # Quick empty check before expensive Azure OCR
    if _is_page_likely_empty(pil_img):
        empty_payload = {
            "page_number": page_number,
            "page_width": pil_img.width,
            "page_height": pil_img.height,
            "unit": "pixel",
            "ocr_page_text": "",
            "lines": [],
            "words": [],
        }
        if context.debug_pages_dir:
            debug_path = os.path.join(context.debug_pages_dir, f"page_{page_number:03d}.json")
            with open(debug_path, "w", encoding="utf-8") as f:
                json.dump({"page_number": page_number, "ocr_page_text": "", "lines": [], "words": []}, f, ensure_ascii=False, indent=2)
        return empty_payload

    result = analyze_outline_page_with_azure(context, pil_img)

    first_page = result.pages[0] if result.pages else None
    page_w = float(getattr(first_page, "width", pil_img.width) or pil_img.width)
    page_h = float(getattr(first_page, "height", pil_img.height) or pil_img.height)

    page_lines: List[Dict[str, Any]] = []
    page_words_flat: List[Dict[str, Any]] = []
    page_text_parts: List[str] = []

    for p in result.pages:
        for w in (p.words or []):
            txt = (w.content or "").strip()
            if not txt:
                continue
            poly: List[Tuple[int, int]] = []
            if w.polygon:
                poly = [(int(pt.x), int(pt.y)) for pt in w.polygon]
            page_words_flat.append(
                {
                    "text": txt,
                    "bbox": poly,
                    "confidence": float(getattr(w, "confidence", 1.0) or 1.0),
                }
            )

        for line in p.lines or []:
            text = (line.content or "").strip()
            if not text:
                continue
            line_bbox: List[Tuple[int, int]] = []
            if line.polygon:
                line_bbox = [(int(pt.x), int(pt.y)) for pt in line.polygon]
            if _is_noise_text(text, line_bbox, page_w, page_h):
                continue
            page_lines.append({"text": text, "bbox": line_bbox})
            page_text_parts.append(text)

    page_text = " ".join(page_text_parts).strip()

    page_payload = {
        "page_number": page_number,
        "page_width": page_w,
        "page_height": page_h,
        "unit": "pixel",
        "ocr_page_text": page_text,
        "lines": page_lines,
        "words": page_words_flat,
    }

    if context.debug_pages_dir:
        debug_path = os.path.join(context.debug_pages_dir, f"page_{page_number:03d}.json")
        with open(debug_path, "w", encoding="utf-8") as f:
            json.dump(page_payload, f, ensure_ascii=False, indent=2)

    return page_payload


def build_outline_ocr_data(context: OcrContext, pdf_path: str) -> Dict[str, Any]:
    """
    Run Azure OCR on each outline page and extract text, lines, and words with bounding boxes.
    Uses parallel processing for improved performance; skips empty pages to save Azure API calls.
    """
    pil_pages = render_pdf_to_pil_pages(pdf_path, dpi=context.render_dpi)

    if context.debug_pages_dir:
        os.makedirs(context.debug_pages_dir, exist_ok=True)

    worker_count = max(1, context.workers or 3)
    pages_to_process = [(pn, img, context) for pn, img in pil_pages]

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(_process_single_page_ocr, args): args[0] for args in pages_to_process}
        results: Dict[int, Dict[str, Any]] = {}
        for future in as_completed(futures):
            page_payload = future.result()
            results[page_payload["page_number"]] = page_payload

    pages_output = [results[pn] for pn in sorted(results.keys())]
    full_text_parts = [p.get("ocr_page_text", "") for p in pages_output]
    full_text = "\n".join(t for t in full_text_parts if t).strip()

    if context.debug_ocr_json:
        directory = os.path.dirname(context.debug_ocr_json)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(context.debug_ocr_json, "w", encoding="utf-8") as f:
            json.dump({"pages": pages_output, "full_text": full_text}, f, ensure_ascii=False, indent=2)

    if context.debug_ocr_text:
        directory = os.path.dirname(context.debug_ocr_text)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(context.debug_ocr_text, "w", encoding="utf-8") as f:
            f.write(full_text or "")

    return {"pages": pages_output, "full_text": full_text}


def validate_input_paths(pdf_path: str, output_json_path: str, output_pdf_path: str) -> None:
    """
    Make sure the input PDF exists and the JSON and PDF output paths are writable.
    """
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    with open(pdf_path, "rb") as f:
        header = f.read(4)
    if header != b"%PDF":
        raise ValueError(f"Not a valid PDF: {pdf_path}")

    for outp in (output_json_path, output_pdf_path):
        directory = os.path.dirname(outp)
        if directory:
            os.makedirs(directory, exist_ok=True)
        try:
            with open(outp, "w", encoding="utf-8") as test_file:
                test_file.write("")
            os.remove(outp)
        except Exception as exc:
            raise ValueError(f"Cannot write to output path {outp}: {exc}") from exc


def build_outline_result_json(
    *,
    structure: Dict[str, Any],
    grading: Dict[str, Any],
    annotations: List[Dict[str, Any]],
    page_suggestions: List[Dict[str, Any]],
    annotation_errors: List[Dict[str, Any]] | None = None,
    spelling_errors: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """
    Step 9: Build the JSON object returned to the backend.
    
    Packs outline structure, grading, annotations, page‑level suggestions,
    and spelling/grammar errors into a single JSON‑serializable dictionary.

    For backward compatibility, the legacy key 'annotations' is kept as an
    alias of 'inline_annotations'.
    """
    return {
        "structure": structure,
        "grading": grading,
        # Backward‑compatible alias:
        "annotations": annotations,
        # New explicit field for clarity:
        "inline_annotations": annotations,
        "page_suggestions": page_suggestions,
        "annotation_errors": annotation_errors or [],
        "spelling_grammar_errors": spelling_errors or [],
    }


def save_outline_result_json(result: Dict[str, Any], output_json_path: str) -> None:
    """
    Save the outline grading result JSON to disk for the API and UI.
    """
    directory = os.path.dirname(output_json_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Saved outline grading JSON → {output_json_path}")


def run_outline_grading(
    pdf_path: str,
    output_json_path: str,
    output_pdf_path: str,
    *,
    outline_rubric_docx: str | None = None,
    annotations_rubric_docx: str | None = None,
    input_type: str = "auto",
) -> Dict[str, Any]:
    """
    Programmatic entry point for the outline grading pipeline.

    Runs OCR, detects outline structure, grades the outline, generates annotations
    and page-level suggestions, renders the outline evaluation report page, saves
    an annotated outline-only PDF (no report page merged), and saves a JSON summary
    for the backend.
    """
    # 0) Validate paths and environment
    validate_input_paths(pdf_path, output_json_path, output_pdf_path)
    context = prepare_ocr_context()
    grok_key = context.grok_key

    # Load rubric texts (allow overriding filenames if provided).
    outline_rubric_text = load_outline_rubric_text(outline_rubric_docx)
    annotations_rubric_text = load_outline_annotations_rubric_text(annotations_rubric_docx)

    # Clear any partial results from previous runs to prevent cross-contamination
    _clear_partial_outline_annotations()

    timings: Dict[str, float] = {}
    total_start = time.perf_counter()

    # 1) OCR
    print("Running outline OCR (Azure Document Intelligence)...")
    t0 = time.perf_counter()
    ocr_data_all = build_outline_ocr_data(context, pdf_path)
    timings["OCR"] = time.perf_counter() - t0

    # 2) Page images for Grok (all pages)
    print("Preparing outline page images for Grok...")
    t0 = time.perf_counter()
    page_images_all = build_grok_page_images_for_outline(pdf_path)
    timings["Grok Images"] = time.perf_counter() - t0

    # 3) Detect outline structure (using all OCR + all images)
    print("Detecting outline structure with Grok...")
    t0 = time.perf_counter()
    structure = detect_outline_structure_with_grok(grok_key, ocr_data_all, page_images_all)
    timings["Structure Detection"] = time.perf_counter() - t0

    # 3b) Compute canonical outline_pages
    print("Computing canonical outline pages...")
    outline_meta = structure.get("outline") or {}
    raw_pages = outline_meta.get("pages") or []

    # Determine total pages from OCR result (page_number in ocr_data_all)
    all_page_numbers = sorted(
        {p.get("page_number") for p in (ocr_data_all.get("pages") or []) if p.get("page_number") is not None}
    )
    total_pages = all_page_numbers[-1] if all_page_numbers else 0

    canonical_pages = []
    for p in raw_pages:
        try:
            pn = int(p)
        except (TypeError, ValueError):
            continue
        if 1 <= pn <= max(1, total_pages):
            canonical_pages.append(pn)

    if not canonical_pages:
        if input_type == "outline":
            canonical_pages = list(range(1, total_pages + 1))
        elif input_type == "essay":
            raise RuntimeError("No outline pages detected for essay input; outline.pages is empty.")
        else:  # auto
            canonical_pages = list(range(1, total_pages + 1))

    outline_pages = sorted(set(canonical_pages))
    outline_meta["pages"] = outline_pages
    structure["outline"] = outline_meta

    # Build filtered OCR data & page images, restricted to outline_pages
    ocr_pages_outline = [
        p for p in (ocr_data_all.get("pages") or []) if p.get("page_number") in outline_pages
    ]
    full_text_outline = "\n".join((p.get("ocr_page_text") or "").strip() for p in ocr_pages_outline if p.get("ocr_page_text"))
    ocr_data = {"pages": ocr_pages_outline, "full_text": full_text_outline}

    page_images = [p for p in page_images_all if p.get("page") in outline_pages]

    # 3b) Detect spelling and grammar errors (outline pages only)
    print("Detecting spelling/grammar errors on outline pages...")
    t0 = time.perf_counter()
    spelling_errors = detect_spelling_grammar_errors(grok_key, ocr_data)
    spelling_errors = _filter_errors(spelling_errors)
    timings["Spelling Detection"] = time.perf_counter() - t0
    print(f"Found {len(spelling_errors)} spelling/grammar errors on outline pages.")

    # 4) Grade outline with rubric (outline-only views)
    print("Grading outline with rubric...")
    t0 = time.perf_counter()
    grading = grade_outline_with_rubric(grok_key, outline_rubric_text, ocr_data, structure, page_images)
    timings["Grading"] = time.perf_counter() - t0

    # 5) Generate outline‑focused annotations
    print("Generating outline annotations...")
    t0 = time.perf_counter()
    ann_pack = generate_outline_annotations(
        grok_key=grok_key,
        annotations_rubric_text=annotations_rubric_text,
        ocr_data=ocr_data,
        structure=structure,
        grading=grading,
        page_images=page_images,
    )
    timings["Annotations"] = time.perf_counter() - t0

    annotations = ann_pack.get("annotations") or []
    annotation_errors = ann_pack.get("errors") or []

    # 5b) Generate outline‑focused page suggestions (separate Grok call)
    print("Generating outline page suggestions...")
    t0 = time.perf_counter()
    sugg_pack = generate_outline_suggestions(
        grok_key=grok_key,
        annotations_rubric_text=annotations_rubric_text,
        ocr_data=ocr_data,
        structure=structure,
        grading=grading,
        page_images=page_images,
    )
    timings["Suggestions"] = time.perf_counter() - t0

    page_suggestions = sugg_pack.get("page_suggestions") or []

    # 6) Render outline evaluation report page
    print("Rendering outline evaluation report page...")
    t0 = time.perf_counter()
    page_size = get_outline_report_page_size(pdf_path)

    # Create a temporary PDF page with PyMuPDF and draw the report using our helpers.
    dpi_ratio = 72.0 / OUTLINE_CONFIG.report_dpi
    W_pt = page_size[0] * dpi_ratio
    H_pt = page_size[1] * dpi_ratio

    report_doc = fitz.open()
    report_page = report_doc.new_page(width=W_pt, height=H_pt)

    layout = setup_outline_report_layout(page_size)
    y = draw_outline_report_header(report_page, layout, grading)
    y = draw_outline_grading_table(report_page, layout, grading, y)
    y = draw_outline_reasons_section(report_page, layout, grading, y)
    _ = draw_outline_suggested_improvements_section(report_page, layout, grading, y)

    # Convert the report PDF page to a PIL image at target DPI.
    report_image = convert_outline_report_page_to_pil_image(report_page, dpi=OUTLINE_CONFIG.report_dpi)
    report_doc.close()
    report_pages = [report_image]
    timings["Report Rendering"] = time.perf_counter() - t0

    # 7) Draw annotations on outline pages (returns annotated page images)
    t0 = time.perf_counter()
    annotated_pages = draw_annotations_on_outline_pages(
        pdf_path=pdf_path,
        ocr_data=ocr_data,
        structure=structure,
        grading=grading,
        annotations=annotations,
        page_suggestions=page_suggestions,
        dpi=OUTLINE_CONFIG.ocr_render_dpi,
        spelling_errors=spelling_errors,
    )
    timings["Annotation Drawing"] = time.perf_counter() - t0

    # 8) Save annotated outline pages into final PDF (outline-only, no report page)
    print("Saving annotated outline pages into final PDF (outline only)...")
    t0 = time.perf_counter()
    # When the input is a full essay, draw_annotations_on_outline_pages will
    # render all pages. Filter down to outline_pages so only outline pages are
    # included in the final PDF.
    # Note: Empty pages (without content) are skipped during rendering and will be None
    annotated_pages_outline = [
        img for idx, img in enumerate(annotated_pages, start=1) 
        if idx in outline_pages and img is not None
    ]
    annotated_pdf_bytes = pil_images_to_pdf_bytes_outline(annotated_pages_outline)
    with open(output_pdf_path, "wb") as f_out:
        f_out.write(annotated_pdf_bytes)
    timings["Save Annotated PDF"] = time.perf_counter() - t0

    # Optionally compress the final outline PDF if the compression helper is available.
    print("Checking outline PDF file size for compression...")
    t0 = time.perf_counter()
    _ = compress_pdf_if_needed(
        pdf_path=output_pdf_path,
        target_size_mb=10.0,
        max_quality=75,
        max_dimension=2000,
    )
    timings["PDF Compression"] = time.perf_counter() - t0

    # 9) Save JSON result for backend
    print("Saving outline grading JSON result...")
    result_json = build_outline_result_json(
        structure=structure,
        grading=grading,
        annotations=annotations,
        page_suggestions=page_suggestions,
        annotation_errors=annotation_errors,
        spelling_errors=spelling_errors,
    )
    save_outline_result_json(result_json, output_json_path)

    total_elapsed = time.perf_counter() - total_start
    print("")
    print("=" * 60)
    print("OUTLINE GRADING TIMING SUMMARY")
    print("=" * 60)
    for phase, elapsed in timings.items():
        print(f"  {phase}: {elapsed:.2f}s")
    print("-" * 60)
    print(f"  Total outline grading time: {total_elapsed:.2f}s")
    print("=" * 60)

    return {
        "status": "success",
        "json_path": output_json_path,
        "pdf_path": output_pdf_path,
        "grading": grading,
        "timings": timings,
        "total_time": total_elapsed,
    }


def main() -> None:
    """
    CLI entry point for standalone outline grading.

    Example:
        python backend/eng_essay/grade_pdf_outline.py ^
            --pdf input_outline.pdf ^
            --output-json outline_result.json ^
            --output-pdf outline_annotated.pdf
    """
    parser = argparse.ArgumentParser(description="CSS English Essay OUTLINE grading pipeline")
    parser.add_argument("--pdf", required=True, help="Input outline PDF path")
    parser.add_argument("--output-json", default="outline_result.json", help="Path to save outline grading JSON")
    parser.add_argument("--output-pdf", default="outline_annotated.pdf", help="Path to save annotated outline PDF")
    parser.add_argument(
        "--input-type",
        choices=["auto", "essay", "outline"],
        default="auto",
        help="Type of input PDF: 'auto' (default, detect outline pages), 'essay' (full essay with outline pages), or 'outline' (outline-only PDF).",
    )
    parser.add_argument(
        "--outline-rubric-docx",
        default=OUTLINE_CONFIG.outline_rubric_docx,
        help="Path to CSS Outline Evaluation Rubric DOCX",
    )
    parser.add_argument(
        "--annotations-rubric-docx",
        default=OUTLINE_CONFIG.outline_annotations_rubric_docx,
        help="Path to Outline Annotations Rubric DOCX",
    )

    args = parser.parse_args()

    run_outline_grading(
        pdf_path=args.pdf,
        output_json_path=args.output_json,
        output_pdf_path=args.output_pdf,
        outline_rubric_docx=args.outline_rubric_docx,
        annotations_rubric_docx=args.annotations_rubric_docx,
        input_type=args.input_type,
    )


if __name__ == "__main__":
    main()