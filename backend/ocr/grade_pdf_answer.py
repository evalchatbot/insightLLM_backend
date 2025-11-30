# grade_pdf_answer.py
#
# Simplified pipeline:
#   1) Google Vision OCR for text + bounding boxes.
#   2) Grok Prompt 1: Headings & structure detection (with PDF images).
#   3) Grok Prompt 2: Subject-wise marking (with PDF images + subject rubric DOCX).
#   4) Grok Prompt 3: Refined rubric annotations (with PDF images + refined rubric DOCX).
#   5) Render subject-wise report pages.
#   6) Render refined-rubric summary page.
#   7) Annotate answer pages according to simplified rules.
#   8) Merge all pages into final PDF.

import argparse
import base64
import io
import json
import os
import re
import sys
from functools import lru_cache
from typing import Any, Dict, List, Tuple, Optional, Set

import requests
from dotenv import load_dotenv
from google.api_core.client_options import ClientOptions
from google.cloud import vision
import fitz  # PyMuPDF
from docx import Document
from PIL import Image, ImageDraw, ImageFont

try:
    from backend.ocr.annotate_pdf_with_rubric import annotate_pdf_answer_pages
except ImportError:
    from annotate_pdf_with_rubric import annotate_pdf_answer_pages


# -----------------------------
# UTILS & ENV
# -----------------------------




def debug_dump_sections(
    sections: List[Dict[str, Any]],
    output_path: str = "debug_sections.json",
) -> None:
    """
    Save detected headings/sections to a JSON file and print a clean summary.

    Each section includes:
      - title
      - level (1 = main heading, 2 = subheading)
      - page_numbers
      - first 200 chars of content (for quick checking)
    """
    light_sections = []
    for idx, sec in enumerate(sections):
        light_sections.append(
            {
                "index": idx,
                "title": sec.get("title"),
                "level": sec.get("level"),
                "page_numbers": sec.get("page_numbers"),
                "content_preview": (sec.get("content") or "")[:200],
            }
        )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(light_sections, f, ensure_ascii=False, indent=2)

    print("\n==== DETECTED HEADINGS / SECTIONS (from Grok) ====")
    for sec in light_sections:
        print(
            f"[{sec['index']}] "
            f"Title: {sec['title']!r} | "
            f"Level: {sec['level']} | "
            f"Pages: {sec['page_numbers']}"
        )
    print(f"Saved detailed section info to {output_path}")
    print("=================================================\n")






def clean_json_from_llm(text: str) -> str:
    """
    Remove markdown code fences like ```json ... ``` or ``` ... ```.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def load_environment() -> Tuple[str, vision.ImageAnnotatorClient]:
    """
    Load environment variables for Grok and Google Vision.

    .env must contain:
      Grok_API=YOUR_GROK_KEY
      Google_cloud_key=YOUR_GOOGLE_CLOUD_API_KEY
    """
    load_dotenv()
    grok_key = os.getenv("Grok_API")
    google_key = os.getenv("Google_cloud_key")
    missing = []
    if not grok_key:
        missing.append("Grok_API")
    if not google_key:
        missing.append("Google_cloud_key")
    if missing:
        raise EnvironmentError(
            f"Missing environment variable(s): {', '.join(missing)}. "
            "Please set them in your .env file."
        )

    client_options = ClientOptions(api_key=google_key)
    vision_client = vision.ImageAnnotatorClient(client_options=client_options)
    return grok_key, vision_client


# -----------------------------
# PDF → PAGE IMAGES (for Grok)
# -----------------------------


def pdf_to_page_images_for_grok(
    pdf_path: str,
    max_pages: int = 50,
    max_dim: int = 1200,
    base64_cap: int = 12000,
) -> List[Dict[str, Any]]:
    """
    Convert up to `max_pages` pages of the PDF into resized PNG images (for Grok).
    Returns a list: [{"page": 1, "image_base64": "...", "truncated": bool}, ...]
    """
    doc = fitz.open(pdf_path)
    images = []
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        pil_img = Image.open(io.BytesIO(img_bytes))
        images.append(pil_img)

    page_images: List[Dict[str, Any]] = []

    for idx, img in enumerate(images):
        if idx >= max_pages:
            break
        resized = img.copy()
        resized.thumbnail((max_dim, max_dim))
        buffer = io.BytesIO()
        resized.save(buffer, format="PNG", optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        truncated = False
        if len(encoded) > base64_cap:
            encoded = encoded[:base64_cap]
            truncated = True
        page_images.append(
            {"page": idx + 1, "image_base64": encoded, "truncated": truncated}
        )
    return page_images


# -----------------------------
# OCR WITH GOOGLE VISION
# -----------------------------


def _bbox_to_tuples(bbox) -> List[Tuple[int, int]]:
    return [(v.x, v.y) for v in bbox.vertices]


def _paragraph_text(paragraph) -> str:
    words = []
    for word in paragraph.words:
        symbols = "".join(symbol.text for symbol in word.symbols)
        words.append(symbols)
    return " ".join(words).strip()


def run_ocr_on_pdf(
    vision_client: vision.ImageAnnotatorClient, pdf_path: str
) -> Dict[str, Any]:
    """
    Run Google Cloud Vision DOCUMENT_TEXT_DETECTION on each page of the PDF.
    Returns a structured dict with pages, lines, and bounding boxes:

      {
        "pages": [
          {
            "page_number": 1,
            "lines": [
              {
                "text": str,
                "bbox": [ (x,y), ... ],
                "words": [
                  { "text": str, "bbox": [ (x,y), ... ] },
                  ...
                ]
              },
              ...
            ]
          },
          ...
        ],
        "full_text": "..."
      }
    """
    doc = fitz.open(pdf_path)
    images = []
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        pil_img = Image.open(io.BytesIO(img_bytes))
        images.append(pil_img)

    pages_output: List[Dict[str, Any]] = []
    full_text_parts: List[str] = []

    for idx, img in enumerate(images):
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        vision_image = vision.Image(content=buffer.getvalue())
        response = vision_client.document_text_detection(image=vision_image)
        if response.error.message:
            raise RuntimeError(
                f"OCR failed on page {idx + 1}: {response.error.message}"
            )

        page_lines: List[Dict[str, Any]] = []
        annotation = response.full_text_annotation
        if annotation:
            full_text_parts.append(annotation.text.strip())
            for page in annotation.pages:
                for block in page.blocks:
                    for paragraph in block.paragraphs:
                        text = _paragraph_text(paragraph)
                        if not text:
                            continue
                        word_entries: List[Dict[str, Any]] = []
                        for word in paragraph.words:
                            w_text = "".join(
                                symbol.text for symbol in word.symbols
                            ).strip()
                            if not w_text:
                                continue
                            word_entries.append(
                                {
                                    "text": w_text,
                                    "bbox": _bbox_to_tuples(word.bounding_box),
                                }
                            )
                        page_lines.append(
                            {
                                "text": text,
                                "bbox": _bbox_to_tuples(paragraph.bounding_box),
                                "words": word_entries,
                            }
                        )
        else:
            text_annotations = response.text_annotations
            if text_annotations:
                full_text_parts.append(text_annotations[0].description.strip())
                for ta in text_annotations[1:]:
                    page_lines.append(
                        {
                            "text": ta.description,
                            "bbox": _bbox_to_tuples(ta.bounding_poly),
                            "words": [],
                        }
                    )

        pages_output.append({"page_number": idx + 1, "lines": page_lines})

    return {"pages": pages_output, "full_text": "\n".join(full_text_parts).strip()}


# -----------------------------
# RUBRIC DOCX HELPERS
# -----------------------------


def _load_docx_text(path: str) -> str:
    try:
        doc = Document(path)
    except Exception as exc:
        return f"[Error reading DOCX at {path}: {exc}]"
    parts: List[str] = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            parts.append(t)
    return "\n".join(parts)


def _normalize_subject_key(value: str) -> str:
    """
    Convert any subject identifier (dropdown id, folder name, filename) into a
    comparable slug so "Political Science Rubric" and "political-science" match.
    """
    if not value:
        return ""
    key = value.lower().strip()
    key = re.sub(r"[\s_]+", "-", key)
    key = re.sub(r"[^a-z0-9-]", "", key)
    key = re.sub(r"-{2,}", "-", key)
    return key.strip("-")


def _subject_key_variants(value: str) -> Set[str]:
    """
    Generate slug variants for matching; we also accept subjects without the
    trailing "-rubric" suffix because some folders include that word.
    """
    base = _normalize_subject_key(value)
    variants: Set[str] = set()
    if base:
        variants.add(base)
        if base.endswith("-rubric"):
            trimmed = base[: -len("-rubric")].strip("-")
            if trimmed:
                variants.add(trimmed)
    return variants


def _subject_keys_match(candidate: str, target_variants: Set[str]) -> bool:
    candidate_variants = _subject_key_variants(candidate)
    return any(var in target_variants for var in candidate_variants)


def find_subject_rubric_path(subject: str) -> Optional[str]:
    """
    Search under ./20marks_Rubrics for a .docx whose folder or filename matches
    the provided subject id (case/spacing insensitive).
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    rubrics_root = os.path.join(base_dir, "20marks_Rubrics")
    if not os.path.isdir(rubrics_root):
        return None

    target_variants = _subject_key_variants(subject)
    if not target_variants:
        return None

    # Prefer matches where the directory name (subject folder) aligns with the
    # requested id; fall back to filename matches if needed.
    for entry in sorted(os.listdir(rubrics_root)):
        entry_path = os.path.join(rubrics_root, entry)
        if not os.path.isdir(entry_path):
            continue

        docx_files = sorted(
            f for f in os.listdir(entry_path) if f.lower().endswith(".docx")
        )
        if not docx_files:
            continue

        dir_matches = _subject_keys_match(entry, target_variants)
        for fname in docx_files:
            stem = os.path.splitext(fname)[0]
            if dir_matches or _subject_keys_match(stem, target_variants):
                return os.path.join(entry_path, fname)

    # Handle DOCX files that might live directly under the root.
    for fname in sorted(os.listdir(rubrics_root)):
        if not fname.lower().endswith(".docx"):
            continue
        stem = os.path.splitext(fname)[0]
        if _subject_keys_match(stem, target_variants):
            return os.path.join(rubrics_root, fname)

    return None


def load_subject_rubric_text(subject: str) -> Tuple[str, Optional[str]]:
    docx_path = find_subject_rubric_path(subject)
    if not docx_path:
        print(f"WARNING: No subject rubric DOCX found for '{subject}'.")
        return "", None
    text = _load_docx_text(docx_path)
    return text, docx_path


def load_refined_rubric_text() -> Tuple[str, Optional[str]]:
    """
    Load the refined generic rubric DOCX (REFINED RUBRIC (1).docx).
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    refined_path = os.path.join(base_dir, "REFINED RUBRIC.docx")
    if not os.path.isfile(refined_path):
        print("WARNING: Refined rubric DOCX not found.")
        return "", None
    text = _load_docx_text(refined_path)
    return text, refined_path


# -----------------------------
# GROK CALL 1: SECTION DETECTION
# -----------------------------

def call_grok_for_section_detection(
    grok_api_key: str,
    ocr_data: Dict[str, Any],
    page_images: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Use Grok to detect headings, subheadings and content sections
    from the full OCR text + ALL page images.

    Returns a list of sections in the shape:
      {
        "title": str,
        "level": int,            # 1 = main heading, 2 = subheading
        "page_numbers": [int],
        "content": str,
        "line_indices": []       # kept for compatibility (not used)
      }

    IMPORTANT:
      - Grok is explicitly told to trust the PAGE IMAGES as the primary source
        and only use OCR as a helper.
    """
    system_msg = {
        "role": "system",
        "content": (
            "You are an expert at visually and logically segmenting handwritten exam answers.\n"
            "You receive:\n"
            "- OCR text (approximate),\n"
            "- per-page OCR structure (lines with bounding boxes),\n"
            "- base64-encoded page images of the handwritten script.\n\n"
            "PRIMARY GROUND TRUTH:\n"
            "- The PAGE IMAGES are the primary source of truth.\n"
            "- OCR text is only a helper for searching or clarifying words.\n"
            "- If OCR and the image disagree, ALWAYS follow the handwritten image.\n\n"
            "YOUR GOAL:\n"
            "Segment the answer into logical sections:\n"
            "- an INTRODUCTION section,\n"
            "- zero or more main body sections and sub-sections,\n"
            "- a CONCLUSION section.\n\n"
            "DEFINITION OF SECTIONS:\n"
            "- A section is a continuous block of content that belongs together under a heading,\n"
            "  subheading, or implicit role (introduction / conclusion).\n"
            "- Sections must appear in the same order as the student writes them.\n"
            "- Sections must not overlap. A line of content should belong to at most one section.\n"
            "- If some small lines cannot be confidently assigned, you may leave them out, but avoid\n"
            "  inventing sections that do not clearly exist.\n\n"
            "VISUAL CUES FOR HEADINGS:\n"
            "- larger or bolder handwriting,\n"
            "- underlined words or phrases,\n"
            "- lines with extra spacing above and/or below,\n"
            "- numbered headings (1., 2., 3., i., ii., iii., etc.),\n"
            "- short phrases at the start of a line that clearly label the following content.\n"
            "Use these visual cues from the IMAGES first. Use OCR only to approximate the text.\n\n"
            "STRICT OUTPUT FORMAT (IMPORTANT):\n"
            "- You MUST return ONLY valid JSON.\n"
            "- The JSON MUST have a top-level key 'sections' with an array of section objects.\n"
            "- The JSON must have NO extra keys at the top-level.\n"
            "- Do NOT include markdown, comments, or any explanation.\n"
            "- The result must be valid JSON parseable by a strict JSON parser.\n\n"
            "EACH section OBJECT MUST HAVE THE FIELDS:\n"
            "- 'title' (string):\n"
            "    - For explicit headings, use the exact or very close handwritten text.\n"
            "    - For implicit parts, use labels like 'Introduction' or 'Conclusion'.\n"
            "- 'level' (integer):\n"
            "    - 1 for main heading (top-level section),\n"
            "    - 2 for subheading under the previous level-1 section,\n"
            "    - If unsure, use 1.\n"
            "- 'page_numbers' (array of integers):\n"
            "    - All page numbers (1-based) where this section's content appears.\n"
            "    - If content continues onto multiple pages, include all of them.\n"
            "- 'content_text' (string):\n"
            "    - A concise reconstruction or summary of the student's content in this section,\n"
            "      written in clear prose.\n"
            "    - Use your own words, but stay faithful to what is actually written.\n\n"
            "ORDERING CONSTRAINTS:\n"
            "- Sections MUST be in strict reading order: from the first page to the last, top to bottom.\n"
            "- There MUST be exactly one 'Introduction' section (first),\n"
            "  and exactly one 'Conclusion' section (last).\n"
            "- All other sections must appear between them, in the order they appear in the script.\n\n"
            "STABILITY REQUIREMENT:\n"
            "- For the same input, your segmentation should be as consistent as possible.\n"
            "- Avoid random or arbitrary splits.\n"
            "- Prefer fewer, well-justified sections over many small, uncertain sections.\n\n"
            "REASONING STYLE:\n"
            "- Do your reasoning internally.\n"
            "- DO NOT include any intermediate reasoning or notes in the output.\n"
            "- Output ONLY the final JSON object with the 'sections' array.\n"
        ),
    }


    user_payload = {
        "task": (
            "Segment the handwritten exam answer into logical sections using BOTH the page images and OCR.\n\n"
            "INSTRUCTIONS:\n"
            "1) Identify an explicit INTRODUCTION section:\n"
            "   - If there is a heading like 'Introduction', use that as the section title.\n"
            "   - If there is no such heading, treat the first paragraph or group of lines that introduce\n"
            "     the topic as a section titled 'Introduction'.\n"
            "   - This section must always be the first section in the 'sections' array.\n\n"
            "2) Identify an explicit CONCLUSION section:\n"
            "   - If there is a heading like 'Conclusion', 'In conclusion', or similar, use that text as\n"
            "     the section title.\n"
            "   - If there is no such heading, treat the final summarising paragraph or lines that wrap up\n"
            "     the answer as a section titled 'Conclusion'.\n"
            "   - This section must always be the last section in the 'sections' array.\n\n"
            "3) Identify all major body sections between Introduction and Conclusion:\n"
            "   - Look for headings and subheadings using VISUAL CUES from the images:\n"
            "       • underlined or larger/bolder text,\n"
            "       • numbered headings (1., 2., 3.; i., ii., iii.),\n"
            "       • phrases at the start of lines followed by clearly related content,\n"
            "       • extra spacing above/below a short phrase.\n"
            "   - For each such heading:\n"
            "       • create a section with that title,\n"
            "       • assign level = 1 for main topics, level = 2 for clear subtopics under the\n"
            "         most recent main heading (use level = 1 if unsure).\n"
            "   - Include all pages where that section's content continues in 'page_numbers'.\n\n"
            "4) For each section's 'content_text':\n"
            "   - Provide a concise summary of the student's content for that section.\n"
            "   - Do NOT invent new arguments or facts that are not implied by the script.\n"
            "   - If handwriting is partially unclear, infer only what is reasonably supported.\n\n"
            "5) Global constraints for the output:\n"
            "   - The 'sections' array must:\n"
            "       • start with the Introduction section,\n"
            "       • list all body sections and sub-sections in the order they appear across pages,\n"
            "       • end with the Conclusion section.\n"
            "   - Each section must have: 'title', 'level', 'page_numbers', 'content_text'.\n"
            "   - Do NOT include any keys other than these four in each section.\n"
            "   - Do NOT include any top-level keys other than 'sections'.\n\n"
            "6) Output:\n"
            "   - Return ONLY a single JSON object of the form:\n"
            "     {\"sections\": [ {\"title\": ..., \"level\": ..., \"page_numbers\": [...], \"content_text\": ...}, ... ]}\n"
            "   - Do not wrap the JSON in markdown.\n"
            "   - Do not add explanations, comments, or any extra text.\n"
        ),
        "ocr_full_text": ocr_data.get("full_text", "")[:20000],
        "ocr_pages": ocr_data.get("pages", []),
        "page_images_base64_png": page_images,
        "output_schema": {
            "sections": [
                {
                    "title": "string",
                    "level": 1,
                    "page_numbers": [1],
                    "content_text": "string",
                }
            ]
        },
    }

    user_msg = {
        "role": "user",
        "content": json.dumps(user_payload, ensure_ascii=False),
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {grok_api_key}",
    }

    resp = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers=headers,
        json={
            "model": "grok-4-fast-reasoning",
            "messages": [system_msg, user_msg],
            "temperature": 0.1,
        },
        timeout=120,
    )

    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"Failed to parse Grok section detection JSON: {exc}") from exc

    # Extract token usage from response
    usage = data.get("usage", {})
    token_usage = {
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }

    try:
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"Unexpected Grok section response shape: {data}") from exc

    try:
        cleaned = clean_json_from_llm(content)
        parsed = json.loads(cleaned)
    except Exception as e:
        # Fallback – expose what came back for debugging
        return [
            {
                "title": "Section Detection Error",
                "level": 1,
                "page_numbers": [1],
                "content": f"Grok section detection failed: {e}\nRaw: {content[:400]}",
                "line_indices": [],
            }
        ], token_usage

    raw_sections = parsed.get("sections", []) or []

    sections: List[Dict[str, Any]] = []
    for sec in raw_sections:
        title = (sec.get("title") or "UNSPECIFIED").strip()
        level = sec.get("level") or 1
        pages = sec.get("page_numbers") or []
        content_text = sec.get("content_text") or sec.get("content") or ""

        sections.append(
            {
                "title": title,
                "level": int(level) if isinstance(level, (int, float)) else 1,
                "page_numbers": sorted(
                    set(int(p) for p in pages if isinstance(p, (int, float)))
                ),
                "content": content_text,
                "line_indices": [],  # not used downstream, kept for compatibility
            }
        )

    return sections, token_usage


# -----------------------------
# GROK CALL 2: SUBJECT-WISE MARKING
# -----------------------------


def build_grok_payload_for_grading(
    subject: str,
    subject_rubric_text: str,
    ocr_data: Dict[str, Any],
    sections: List[Dict[str, Any]],
    page_images: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build payload for Grok subject-wise grading.

    We send:
      - subject,
      - subject rubric text (DOCX),
      - OCR full text,
      - sections structure,
      - page images.
    """
    schema_hint = {
        "subject": subject,
        "max_marks": 20,
        "total_marks_awarded": 0,
        "question_statement": "",
        "question_expectation": "",
        "criteria": [
            {
                "id": "knowledge_accuracy",
                "name": "Knowledge & Accuracy",
                "max": 8,
                "awarded": 5,
                "strengths": ["..."],
                "weaknesses": ["..."],
            }
        ],
        "high_scoring_outline": {
            "title": "High-Scoring Ideal Outline",
            "outline_points": [
                "Key Concept Introduction: Clear explanation of the main theme or argument with foundational details and context",
                "Central Argument or Main Point: Detailed development of the primary thesis with supporting evidence, specific examples, and historical/factual details",
                "Supporting Evidence and Examples: Concrete examples, data, quotes, or case studies that substantiate the main argument with clear connections",
                "Critical Analysis and Interpretation: Deeper analysis showing how evidence supports the argument and what it means in broader context",
                "Conclusion and Synthesis: Summary of how all elements connect to answer the question comprehensively"
            ],
        },
        "overall_comment": "",
    }

    instructions = (
        "You are an experienced strict CSS examiner. "
        "Using ONLY the provided subject-wise rubric text, you must grade the student's answer with STRICT marking. "
        "IMPORTANT: Maximum marks awarded should NOT exceed 14 out of 20. "
        "Average/acceptable answers should score LESS than 10 marks. "
        "Only exceptional answers should approach 14 marks. "
        "Derive criteria and marks from the rubric text. Return STRICT JSON.\n\n"
        "Required fields:\n"
        "  - subject\n"
        "  - max_marks: always 20\n"
        "  - total_marks_awarded (cap at 14 maximum)\n"
        "  - question_statement: the exam question as written by the student\n"
        "  - question_expectation: what an excellent answer should cover as a single paragraph (no bullet points)\n"
        "  - criteria[]: each criterion with id, name, max, awarded, strengths[], weaknesses[]\n"
        "  - high_scoring_outline: ALWAYS use title as 'High-Scoring Ideal Outline' + array of detailed outline_points with structured headings\n"
        "      * Do NOT modify or extend the title - it must be exactly: 'High-Scoring Ideal Outline'\n"
        "      * Format each outline point as: 'Heading/Section Title: Detailed explanation with examples, evidence, and analysis'\n"
        "      * Each outline point should be comprehensive (1-4 sentences) with specific examples or detailed content\n"
        "      * Points should cover: key arguments, evidence, analysis, and how they connect to the question\n"
        "      * Include concrete details, dates, names, or specific examples where relevant\n"
        "      * Organize into logical sections with clear headings (e.g., 'Introduction to Key Concept:', 'Main Argument:',\n"
        "        'Supporting Evidence:', 'Critical Analysis:', etc.)\n"
        "  - overall_comment: 3–5 sentence holistic evaluation.\n"
    )

    content_payload = {
        "subject": subject,
        "rubric_text": subject_rubric_text,
        "ocr_full_text": ocr_data.get("full_text", "")[:15000],
        "sections": sections,
        "page_images_base64_png": page_images,
        "output_schema": schema_hint,
    }

    return {
        "model": "grok-4-fast-reasoning",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert CSS examiner. "
                    "You produce detailed, rubric-based marking reports and respond in JSON only."
                ),
            },
            {
                "role": "user",
                "content": instructions
                + "\n\nDATA:\n"
                + json.dumps(content_payload, ensure_ascii=False),
            },
        ],
        "temperature": 0.15,
    }


def call_grok_for_grading(
    grok_api_key: str,
    subject: str,
    subject_rubric_text: str,
    ocr_data: Dict[str, Any],
    sections: List[Dict[str, Any]],
    page_images: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    payload = build_grok_payload_for_grading(
        subject, subject_rubric_text, ocr_data, sections, page_images
    )
    headers = {
        "Authorization": f"Bearer {grok_api_key}",
        "Content-Type": "application/json",
    }

    resp = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=150,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Grok grading error {resp.status_code}: {resp.text}")

    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"Grok grading JSON parse error: {exc}") from exc

    # Extract token usage from response
    usage = data.get("usage", {})
    token_usage = {
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }

    try:
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"Unexpected Grok grading response: {data}") from exc

    try:
        cleaned = clean_json_from_llm(content)
        parsed = json.loads(cleaned)
    except Exception as exc:
        snippet = content[:600]
        raise RuntimeError(
            f"Grok grading returned non-JSON or malformed JSON. Snippet:\n{snippet}"
        ) from exc

    return parsed, token_usage


# -----------------------------
# GROK CALL 3: REFINED RUBRIC ANNOTATIONS
# -----------------------------


def call_grok_for_refined_rubric_annotations(
    grok_api_key: str,
    refined_rubric_text: str,
    ocr_data: Dict[str, Any],
    sections: List[Dict[str, Any]],
    page_images: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    """
    Ask Grok to apply the refined generic rubric and produce:
      - annotations[] (for drawing boxes / comments),
      - refined_rubric_summary[] (one entry per rubric point).

    Output shape:

      {
        "annotations": [
          { ... see annotate_pdf_with_rubric.py docstring ... }
        ],
        "refined_rubric_summary": [
          {
            "id": "introduction_quality",
            "name": "Introduction Quality",
            "rating": "weak/average/good/excellent",
            "comment": "..."
          },
          ...
        ]
      }
    """
    system_msg = {
        "role": "system",
        "content": (
            "You are an expert examiner and annotation assistant.\n"
            "You apply a refined generic rubric to handwritten exam answers and output:\n"
            "- concrete annotations (where to draw boxes and what feedback to write), and\n"
            "- a short summary for each rubric point.\n\n"
            "PRIMARY INPUTS YOU RECEIVE:\n"
            "- refined_rubric_text: the generic rubric you must apply;\n"
            "- ocr_full_text + ocr_pages: approximate OCR text and per-page structure;\n"
            "- sections: JSON from a previous step that segments the answer into logical sections;\n"
            "- page_images_base64_png: base64 PNG page images (the handwritten script).\n\n"
            "GROUND TRUTH PRIORITY:\n"
            "- The PAGE IMAGES are the ultimate source of truth.\n"
            "- OCR is only a helper for locating text; if OCR and image disagree, trust the image.\n"
            "- The SECTIONS JSON gives you stable titles and page ranges. Use it whenever you need\n"
            "  to refer to headings or sections (via section_id or target_section_id).\n\n"
            "YOUR GOAL:\n"
            "- Produce a JSON object with:\n"
            "    annotations[]: ALL important issues and observations you can detect,\n"
            "    refined_rubric_summary[]: one item per rubric point with rating + comment.\n"
            "- Be especially thorough for:\n"
            "    * incorrect or weak headings (missing clarity / relevance), and\n"
            "    * factual inaccuracies (wrong dates, wrong names, wrong causal claims, etc.).\n"
            "- It is acceptable to be conservative for spelling/grammar due to OCR noise.\n\n"
            "STRICT OUTPUT FORMAT (IMPORTANT):\n"
            "- Return ONLY valid JSON (no markdown, no commentary).\n"
            "- Top-level keys allowed: 'annotations' and 'refined_rubric_summary'.\n"
            "- annotations[] entries can have additional fields, but MUST include the fields\n"
            "  required in the provided output_schema examples for each type.\n"
            "- The JSON must be parseable by a strict JSON parser.\n"
        ),
    }

    instructions = (
        "Use the refined generic rubric text to evaluate this answer strictly. "
        "You must obey these annotation rules:\n\n"
        "1) Introduction:\n"
        "   - Decide if introduction is weak/average/good/excellent and be strict about it.\n"
        "   - Create ONE annotation of type 'introduction_comment' with:\n"
        "       rubric_point = 'introduction_quality',\n"
        "       target_section_id = the section.id that is the introduction,\n"
        "       page = first page where introduction appears,\n"
        "       comment = a detailed 3–5 sentence evaluation of ONLY the introduction using the refined generic rubric\n\n"
        "2) Headings and subheadings:\n"
        "   - Evaluate ALL headings and subheadings (not just negative ones) .\n"
        "   - For CORRECT headings (self-explanatory, relevant, clear), add annotation type 'heading_issue' with:\n"
        "       section_id = that heading's section.id,\n"
        "       page = page number of that heading,\n"
        "       sentiment = 'positive',\n"
        "       comment = 'Correct heading' or 'Good heading - clear and relevant'.\n"
        "   - For INCORRECT/PROBLEMATIC headings, create type 'heading_issue' with:\n"
        "       section_id = that heading's section.id,\n"
        "       page = page number of that heading,\n"
        "       sentiment = 'negative',\n"
        "       comment = short explanation of the issue,\n"
        "       suggestion = a better alternate heading that would be more self-explanatory and relevant.\n"
        "   - Focus on issues such as: not being self-explanatory, not directly relevant, vague, unclear.\n"
        "   - Do NOT flag spelling mistakes in headings here (handle in grammar_language).\n"
        "   - Use the refined generic rubric text to evaluate.\n\n"
        "3) Factual inaccuracies:\n"
        "   - IMPORTANT: Do NOT mark spelling mistakes as factual errors.\n"
        "   - Only flag actual factual mistakes (wrong dates, wrong facts, incorrect information).\n"
        "   - For each sentence with a factual mistake, create type 'factual_error' with:\n"
        "       page = page where the sentence appears,\n"
        "       target_sentence = THE EXACT SENTENCE TEXT AS WRITTEN (copy verbatim from OCR text),\n"
        "                        Do NOT paraphrase or reword - use the exact wording from the student's script,\n"
        "       target_sentence_start = the exact first 6-8 words of the sentence for precise matching,\n"
        "       context_before = 3-5 words that appear immediately before this sentence,\n"
        "       context_after = 3-5 words that appear immediately after this sentence,\n"
        "       correction = a short correct version or correct fact,\n"
        "       comment = short explanation (e.g., 'Year should be 1945 not 1944').\n"
        "   - CRITICAL: Copy target_sentence EXACTLY from the OCR text. Preserve spelling, punctuation, and wording.\n"
        "   - Provide context_before and context_after to help locate the sentence when similar phrases exist elsewhere.\n"
        "   - Make sure to go through all the facts using the images and the ocr text provided.\n"
        "   - Use the refined generic rubric text to evaluate.\n\n"
        "4) Spelling only (no grammar):\n"
        "   - Focus ONLY on clear spelling mistakes (wrongly spelled words).\n"
        "   - Do NOT correct grammar, sentence structure, style, or phrasing.\n"
        "   - For each spelling issue, create type 'grammar_language' with:\n"
        "       page = page where the misspelled word appears,\n"
        "       target_word_or_sentence = ONLY the misspelled word or a very short span (1–3 words),\n"
        "                                never a full paragraph and never more than one full line,\n"
        "       correction = the correctly spelled word or very short corrected phrase,\n"
        "       rubric_point = 'grammar_language'.\n"
        "   - Always cross-check using BOTH OCR text AND the page image:\n"
        "       * Use ocr_full_text to roughly locate the word,\n"
        "       * Then visually verify the spelling directly on the page image.\n"
        "       * If OCR and the image disagree, TRUST THE IMAGE and do NOT flag a spelling error\n"
        "         if the handwritten word is actually correct.\n"
        "   - Do not send entire paragraphs or long sentences as target_word_or_sentence.\n"
        "   - Prefer single words (e.g., 'recieve') or very short phrases around the error.\n"
        "   - Keep these brief and only for clear, unambiguous spelling mistakes.\n\n"
        "Additionally, build refined_rubric_summary[]:\n"
        "   - One entry per rubric point (e.g., introduction_quality, headings_subheadings, argumentation_quality,\n"
        "     factual_accuracy, grammar_language, presentation, contemporary_relevance,\n"
        "     length_completeness, repetitiveness).\n"
        "   - Each entry: id, name, rating (weak/average/good/excellent), comment (2–3 sentences max).\n"
    )


    user_payload = {
        "refined_rubric_text": refined_rubric_text,
        "ocr_full_text": ocr_data.get("full_text", "")[:15000],
        "ocr_pages": ocr_data.get("pages", []),
        "sections": sections,
        "page_images_base64_png": page_images,
        "output_schema": {
            "annotations": [
                {
                    "type": "introduction_comment/heading_issue/factual_error/grammar_language/repetition",
                    "rubric_point": "string",
                    "page": 1,
                    "target_section_id": "string",
                    "section_id": "string",
                    "sentiment": "negative",
                    "comment": "string",
                    "target_sentence": "string",
                    "target_word_or_sentence": "string",
                    "correction": "string",
                    "original_page": 2,
                    "repeated_page": 4,
                }
            ],
            "refined_rubric_summary": [
                {
                    "id": "introduction_quality",
                    "name": "Introduction Quality",
                    "rating": "weak/average/good/excellent",
                    "comment": "string",
                }
            ],
        },
    }

    user_msg = {
        "role": "user",
        "content": instructions + "\n\nDATA:\n" + json.dumps(user_payload, ensure_ascii=False),
    }

    headers = {
        "Authorization": f"Bearer {grok_api_key}",
        "Content-Type": "application/json",
    }

    resp = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers=headers,
        json={
            "model": "grok-4-fast-reasoning",
            "messages": [system_msg, user_msg],
            "temperature": 0.1,
        },
        timeout=150,
    )

    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"Grok refined rubric JSON parse error: {exc}") from exc

    # Extract token usage from response
    usage = data.get("usage", {})
    token_usage = {
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }

    try:
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"Unexpected Grok refined rubric response: {data}") from exc

    try:
        cleaned = clean_json_from_llm(content)
        parsed = json.loads(cleaned)
    except Exception as exc:
        # Fallback shape
        return {
            "annotations": [
                {
                    "type": "introduction_comment",
                    "rubric_point": "introduction_quality",
                    "page": 1,
                    "target_section_id": "introduction",
                    "comment": f"Error parsing refined rubric response: {exc}",
                }
            ],
            "refined_rubric_summary": [],
        }, token_usage

    # Normalize keys
    parsed.setdefault("annotations", [])
    parsed.setdefault("refined_rubric_summary", [])

    # Save debug
    with open("debug_refined_annotations.json", "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)

    return parsed, token_usage

# -----------------------------
# REPORT RENDERING (SUBJECT MARKING)
# -----------------------------


_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_FONTS_DIR = os.path.join(_MODULE_DIR, "fonts")
_FONT_CANDIDATES = [
    os.environ.get("OCR_FONT_PATH"),
    os.path.join(_FONTS_DIR, "ReportFont.ttf"),
    os.path.join(_FONTS_DIR, "NotoSans-Regular.ttf"),
    os.path.join(_FONTS_DIR, "DejaVuSans.ttf"),
    "arial.ttf",
    "Arial.ttf",
    "LiberationSans-Regular.ttf",
    "DejaVuSans.ttf",
]


def _iter_font_candidates() -> List[str]:
    seen: Set[str] = set()
    ordered: List[str] = []
    for candidate in _FONT_CANDIDATES:
        if not candidate:
            continue
        norm = os.path.normpath(candidate) if os.path.isabs(candidate) else candidate
        if norm in seen:
            continue
        seen.add(norm)
        ordered.append(candidate)
    return ordered


@lru_cache(maxsize=32)
def _get_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in _iter_font_candidates():
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = ""
    for w in words:
        trial = (current + " " + w).strip()
        if not trial:
            continue
        width = draw.textlength(trial, font=font)
        if width <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines

def render_subject_report_pages(
    grading_result: Dict[str, Any],
    page_size: Tuple[int, int] = (2480, 3508),
) -> List[Image.Image]:
    """
    Render the subject-wise marking report:
      - SUBJECT NAME (at top)
      - TOTAL MARKS
      - QUESTION STATEMENT
      - WHAT QUESTION EXPECTS (right after question statement, as single paragraph)
      - CRITERIA breakdown (with strengths & weaknesses)
      (Note: high-scoring outline is on a separate dedicated page)
    """
    W, H = page_size
    margin = int(W * 0.07)
    line_spacing = 1.4

    title_font = _get_font(80)  # Increased from 64
    subject_font = _get_font(64)  # Increased from 48
    h2_font = _get_font(60)  # Increased from 48
    h3_font = _get_font(52)  # Increased from 40
    body_font = _get_font(44)  # Increased from 34

    pages: List[Image.Image] = []

    def new_page() -> Tuple[Image.Image, ImageDraw.ImageDraw, int]:
        img = Image.new("RGB", (W, H), "white")
        draw = ImageDraw.Draw(img)
        return img, draw, margin

    img, draw, y = new_page()

    def ensure_space(font_obj: ImageFont.FreeTypeFont, needed_lines: int):
        nonlocal img, draw, y
        line_h = font_obj.getbbox("Ag")[3] - font_obj.getbbox("Ag")[1]
        if y + line_h * needed_lines * line_spacing > H - margin:
            pages.append(img)
            img, draw, y = new_page()

    max_text_width = W - 2 * margin

    # SUBJECT NAME (at top)
    subject = grading_result.get("subject", "")
    if subject:
        ensure_space(subject_font, 2)
        draw.text((margin, y), f"Subject: {subject}", font=subject_font, fill="black")
        line_h_subj = subject_font.getbbox("Ag")[3] - subject_font.getbbox("Ag")[1]
        y += int(line_h_subj * line_spacing * 1.5)

    # TOTAL MARKS
    total = grading_result.get("total_marks_awarded", 0)
    maximum = grading_result.get("max_marks", 20)

    ensure_space(title_font, 2)
    draw.text((margin, y), "TOTAL MARKS", font=title_font, fill="black")
    line_h = title_font.getbbox("Ag")[3] - title_font.getbbox("Ag")[1]
    y += int(line_h * line_spacing)
    draw.text((margin, y), f"{total} / {maximum}", font=h2_font, fill="black")
    line_h2 = h2_font.getbbox("Ag")[3] - h2_font.getbbox("Ag")[1]
    y += int(line_h2 * line_spacing * 2)

    # QUESTION STATEMENT
    question = grading_result.get("question_statement", "")
    ensure_space(h2_font, 3)
    draw.text((margin, y), "QUESTION STATEMENT", font=h2_font, fill="black")
    y += int(line_h2 * line_spacing)
    for line in _wrap_text(draw, question, body_font, max_text_width):
        ensure_space(body_font, 1)
        line_hb = body_font.getbbox("Ag")[3] - body_font.getbbox("Ag")[1]
        draw.text((margin, y), line, font=body_font, fill="black")
        y += int(line_hb * line_spacing)
    y += int(body_font.getbbox("Ag")[3] - body_font.getbbox("Ag")[1])

    # WHAT QUESTION EXPECTS (right after question statement, as a single paragraph)
    expectation = grading_result.get("question_expectation", "")
    if expectation:
        ensure_space(h3_font, 2)
        draw.text((margin, y), "What the Question Expects", font=h3_font, fill="black")
        line_h3 = h3_font.getbbox("Ag")[3] - h3_font.getbbox("Ag")[1]
        y += int(line_h3 * line_spacing)
        for line in _wrap_text(draw, expectation, body_font, max_text_width):
            ensure_space(body_font, 1)
            line_hb = body_font.getbbox("Ag")[3] - body_font.getbbox("Ag")[1]
            draw.text((margin, y), line, font=body_font, fill="black")
            y += int(line_hb * line_spacing)
        y += int(body_font.getbbox("Ag")[3] - body_font.getbbox("Ag")[1])

    # CRITERIA BREAKDOWN
    ensure_space(h2_font, 2)
    draw.text((margin, y), "MARKS BREAKDOWN", font=h2_font, fill="black")
    line_h2 = h2_font.getbbox("Ag")[3] - h2_font.getbbox("Ag")[1]
    y += int(line_h2 * line_spacing * 1.5)

    for crit in grading_result.get("criteria", []):
        name = crit.get("name", "")
        awarded = crit.get("awarded", 0)
        max_marks = crit.get("max", 0)
        header = f"{name}  —  {awarded}/{max_marks}"

        ensure_space(h3_font, 2)
        line_h3 = h3_font.getbbox("Ag")[3] - h3_font.getbbox("Ag")[1]
        draw.text((margin, y), header, font=h3_font, fill="black")
        y += int(line_h3 * line_spacing)

        # Strengths
        strengths = crit.get("strengths") or []
        if strengths:
            ensure_space(body_font, len(strengths) + 1)
            line_hb = body_font.getbbox("Ag")[3] - body_font.getbbox("Ag")[1]
            draw.text((margin, y), "Strengths:", font=body_font, fill="darkgreen")
            y += int(line_hb * line_spacing)
            for s in strengths:
                for line in _wrap_text(draw, f"• {s}", body_font, max_text_width):
                    ensure_space(body_font, 1)
                    draw.text((margin, y), line, font=body_font, fill="black")
                    y += int(line_hb * line_spacing)

        # Weaknesses
        weaknesses = crit.get("weaknesses") or []
        if weaknesses:
            ensure_space(body_font, len(weaknesses) + 1)
            line_hb = body_font.getbbox("Ag")[3] - body_font.getbbox("Ag")[1]
            draw.text((margin, y), "Weaknesses:", font=body_font, fill="darkred")
            y += int(line_hb * line_spacing)
            for wtxt in weaknesses:
                for line in _wrap_text(draw, f"• {wtxt}", body_font, max_text_width):
                    ensure_space(body_font, 1)
                    draw.text((margin, y), line, font=body_font, fill="black")
                    y += int(line_hb * line_spacing)

        y += int(body_font.getbbox("Ag")[3] - body_font.getbbox("Ag")[1])

    pages.append(img)
    return pages




# -----------------------------------------
# PAGE: WHAT THE QUESTION EXPECTS (BULLETS)
# -----------------------------------------

def render_question_expectations_page(
    expectation_text: Any,
    page_size: Tuple[int, int] = (2480, 3508),
) -> Image.Image:
    """
    Render a dedicated page for "What the Question Expects" broken into bullets.

    The expectation_text can be a string or list; it will be converted to bullet points.
    """
    W, H = page_size
    margin = int(W * 0.07)
    line_spacing = 1.4

    title_font = _get_font(72)  # Increased from 60
    body_font = _get_font(48)  # Increased from 36

    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    y = margin

    max_text_width = W - 2 * margin

    # Title
    draw.text((margin, y), "WHAT THE QUESTION EXPECTS", font=title_font, fill="black")
    line_h_title = title_font.getbbox("Ag")[3] - title_font.getbbox("Ag")[1]
    y += int(line_h_title * line_spacing * 1.5)

    # Convert expectation text to bullet points
    # Handle both string and list inputs
    bullet_points = []

    if isinstance(expectation_text, list):
        # Already a list of points
        bullet_points = [str(p).strip() for p in expectation_text if p]
    elif expectation_text:
        # String input: split by periods followed by space (sentences)
        import re
        expectation_str = str(expectation_text).strip()
        sentences = re.split(r'(?<=[.!?])\s+', expectation_str)

        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                # Remove trailing period if present (we'll add bullet format)
                if sentence.endswith(('.', '!', '?')):
                    sentence = sentence[:-1].strip()
                bullet_points.append(sentence)

        # If no sentences found, try splitting by commas
        if not bullet_points:
            comma_parts = [p.strip() for p in expectation_str.split(',')]
            bullet_points = [p for p in comma_parts if p]

    # If still no points, use default
    if not bullet_points:
        bullet_points = ["No specific expectations provided"]

    # Render bullet points
    line_h_body = body_font.getbbox("Ag")[3] - body_font.getbbox("Ag")[1]

    for point in bullet_points:
        if not point:
            continue

        # Wrap the bullet point text
        wrapped_lines = _wrap_text(draw, point, body_font, max_text_width - int(0.08 * W))

        # Check if we need a new page
        needed_lines = len(wrapped_lines)
        if y + line_h_body * needed_lines * line_spacing > H - margin:
            break  # Just stop if we overflow; could add multi-page support here

        # Draw bullet point
        for idx, line in enumerate(wrapped_lines):
            if idx == 0:
                # First line gets the bullet
                draw.text((margin, y), f"• {line}", font=body_font, fill="black")
            else:
                # Subsequent lines are indented
                draw.text((margin + int(0.04 * W), y), line, font=body_font, fill="black")
            y += int(line_h_body * line_spacing)

        y += int(line_h_body * 0.5)  # Space between bullets

    return img

# -----------------------------
# REFINED RUBRIC SUMMARY PAGE
# -----------------------------


def render_refined_rubric_summary_page(
    refined_summary: List[Dict[str, Any]],
    page_size: Tuple[int, int] = (2480, 3508),
) -> Image.Image:
    """
    Render a single page summarizing each refined rubric point:

      - Introduction Quality – rating + comment
      - Headings & Subheadings – rating + comment
      - etc.
    """
    W, H = page_size
    margin = int(W * 0.07)
    line_spacing = 1.4

    title_font = _get_font(72)
    h2_font = _get_font(56)
    body_font = _get_font(44)

    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    y = margin

    max_text_width = W - 2 * margin

    # Title
    draw.text((margin, y), "Refined Rubric Feedback", font=title_font, fill="black")
    y += int((title_font.getbbox("Ag")[3] - title_font.getbbox("Ag")[1]) * line_spacing * 1.5)

    # For each rubric point
    for item in refined_summary:
        rid = item.get("id", "")
        name = item.get("name", rid)
        rating = (item.get("rating") or "").capitalize()
        comment = item.get("comment") or ""

        header = f"{name} — {rating}"
        header_height = h2_font.getbbox("Ag")[3] - h2_font.getbbox("Ag")[1]
        if y + header_height * 4 > H - margin:
            # if page overflow ever needed, here we could create more pages
            # but for now, just stop rendering
            break

        draw.text((margin, y), header, font=h2_font, fill="black")
        y += int(header_height * line_spacing)

        line_hb = body_font.getbbox("Ag")[3] - body_font.getbbox("Ag")[1]
        for line in _wrap_text(draw, comment, body_font, max_text_width):
            draw.text((margin, y), line, font=body_font, fill="black")
            y += int(line_hb * line_spacing)

        y += int(line_hb * 0.8)

    return img


# -----------------------------------------
# PAGE: HIGH-SCORING IDEAL OUTLINE
# -----------------------------------------

def render_high_scoring_outline_page(
    high_scoring_outline: Dict[str, Any],
    page_size: Tuple[int, int] = (2480, 3508),
) -> Image.Image:
    """
    Render a dedicated page for the "High-Scoring Ideal Outline" with structured headings and detailed content.

    The outline supports:
    - Section headings with descriptions (Format: "Heading: Description")
    - Regular bullet points for additional content
    - Proper indentation and visual hierarchy
    - Multi-line text wrapping with appropriate spacing
    """
    W, H = page_size
    margin = int(W * 0.07)
    line_spacing = 1.5

    title_font = _get_font(72)
    h3_font = _get_font(52)
    body_font = _get_font(44)

    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    y = margin

    max_text_width = W - 2 * margin

    # Title (always use fixed title, never extend it)
    outline_title = "High-Scoring Ideal Outline"
    draw.text((margin, y), outline_title, font=title_font, fill="black")
    line_h_title = title_font.getbbox("Ag")[3] - title_font.getbbox("Ag")[1]
    y += int(line_h_title * line_spacing * 1.5)

    # Get outline points
    outline_points = high_scoring_outline.get("outline_points", [])

    if not outline_points:
        # Fallback if no points
        line_hb = body_font.getbbox("Ag")[3] - body_font.getbbox("Ag")[1]
        draw.text((margin, y), "No outline provided", font=body_font, fill="gray")
        return img

    # Render each outline point with proper formatting and structure
    line_hb = body_font.getbbox("Ag")[3] - body_font.getbbox("Ag")[1]
    h2_font = _get_font(56)
    line_h2 = h2_font.getbbox("Ag")[3] - h2_font.getbbox("Ag")[1]

    for idx, point in enumerate(outline_points, 1):
        if not point:
            continue

        point_str = str(point).strip()

        # Check if this is a section header (starts with a number or special format)
        # Format: "1. Section Title" or "Main Topic: Description"
        is_main_heading = False
        heading_text = None
        body_text = None

        # Try to extract heading if it contains a colon or number pattern
        if ":" in point_str:
            parts = point_str.split(":", 1)
            heading_text = parts[0].strip()
            body_text = parts[1].strip() if len(parts) > 1 else ""
            is_main_heading = len(heading_text) < 80  # Reasonable heading length

        # Render heading if identified
        if is_main_heading and heading_text:
            if y + line_h2 * 2 > H - margin:
                break
            draw.text((margin, y), heading_text, font=h2_font, fill="darkblue")
            y += int(line_h2 * line_spacing)

            # Render body text if present
            if body_text:
                wrapped_lines = _wrap_text(draw, body_text, body_font, max_text_width - int(0.08 * W))
                for line in wrapped_lines:
                    if y + line_hb > H - margin:
                        break
                    draw.text((margin + int(0.05 * W), y), f"• {line}", font=body_font, fill="black")
                    y += int(line_hb * line_spacing)
        else:
            # Regular bullet point with text wrapping
            wrapped_lines = _wrap_text(draw, point_str, body_font, max_text_width - int(0.1 * W))

            for line_idx, line in enumerate(wrapped_lines):
                if y + line_hb > H - margin:
                    break
                if line_idx == 0:
                    # First line gets the bullet
                    draw.text((margin, y), f"• {line}", font=body_font, fill="black")
                else:
                    # Subsequent lines are indented
                    indent = margin + int(0.04 * W)
                    draw.text((indent, y), line, font=body_font, fill="black")
                y += int(line_hb * line_spacing)

        # Add spacing between outline sections
        y += int(line_hb * 0.5)

    return img


# -----------------------------
# MAIN PIPELINE
# -----------------------------


def grade_pdf_answer(
    pdf_path: str,
    subject: str,
    output_json_path: str,
    output_pdf_path: str,
    user_id: Optional[str] = None,
) -> None:
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF not found at path: {pdf_path}")

    grok_key, vision_client = load_environment()

    print("Step 1: Converting PDF pages to images (for Grok)...")
    page_images = pdf_to_page_images_for_grok(pdf_path)

    print("Step 2: Running OCR on PDF (Google Vision)...")
    ocr_data = run_ocr_on_pdf(vision_client, pdf_path)

    print("Step 3: Detecting sections/headings with Grok...")
    sections, section_token_usage = call_grok_for_section_detection(
        grok_api_key=grok_key,
        ocr_data=ocr_data,
        page_images=page_images,
    )

    debug_dump_sections(sections, output_path="debug_sections.json")
    
    # Track total token usage
    total_input_tokens = section_token_usage.get("input_tokens", 0)
    total_output_tokens = section_token_usage.get("output_tokens", 0)




    print("Step 4: Loading subject-wise rubric DOCX...")
    subject_rubric_text, subject_rubric_path = load_subject_rubric_text(subject)
    if subject_rubric_path:
        print(f"Using subject rubric file: {subject_rubric_path}")
    else:
        print("Warning: No subject rubric file found; grading will be weaker.")

    print("Step 5: Calling Grok for subject-wise grading...")
    grading_result, grading_token_usage = call_grok_for_grading(
        grok_api_key=grok_key,
        subject=subject,
        subject_rubric_text=subject_rubric_text,
        ocr_data=ocr_data,
        sections=sections,
        page_images=page_images,
    )
    
    # Accumulate token usage
    total_input_tokens += grading_token_usage.get("input_tokens", 0)
    total_output_tokens += grading_token_usage.get("output_tokens", 0)

    grading_result.setdefault("subject", subject)
    if not grading_result.get("max_marks"):
        grading_result["max_marks"] = 20

    print("Saving grading JSON...")
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(grading_result, f, ensure_ascii=False, indent=2)

    print("Step 6: Rendering subject-wise report pages...")
    subject_report_pages = render_subject_report_pages(grading_result)

    print("Step 7: Loading refined rubric DOCX...")
    refined_rubric_text, refined_rubric_path = load_refined_rubric_text()
    if refined_rubric_path:
        print(f"Using refined rubric file: {refined_rubric_path}")
    else:
        print("Warning: No refined rubric file found; annotations will be weaker.")

    print("Step 8: Calling Grok for refined rubric annotations...")
    refined_result, refined_token_usage = call_grok_for_refined_rubric_annotations(
        grok_api_key=grok_key,
        refined_rubric_text=refined_rubric_text,
        ocr_data=ocr_data,
        sections=sections,
        page_images=page_images,
    )
    
    # Accumulate token usage
    total_input_tokens += refined_token_usage.get("input_tokens", 0)
    total_output_tokens += refined_token_usage.get("output_tokens", 0)
    
    annotations = refined_result.get("annotations", []) or []
    refined_summary = refined_result.get("refined_rubric_summary", []) or []

    print("Step 9: Annotating answer pages...")
    annotated_answer_pages = annotate_pdf_answer_pages(
        pdf_path=pdf_path,
        ocr_data=ocr_data,
        sections=sections,
        annotations=annotations,
    )

    print("Step 10: Rendering high-scoring ideal outline page...")
    high_scoring_outline = grading_result.get("high_scoring_outline", {}) or {}
    high_scoring_outline_page = render_high_scoring_outline_page(high_scoring_outline)

    print("Step 11: Rendering refined rubric summary page...")
    refined_summary_page = render_refined_rubric_summary_page(refined_summary)

    # Assemble final PDF:
    #   1) Subject report pages (includes what question expects in single paragraph)
    #   2) High-scoring ideal outline page (detailed with structured sections)
    #   3) Annotated answer pages
    #   4) Refined rubric summary page
    all_pages: List[Image.Image] = []
    all_pages.extend(subject_report_pages)
    all_pages.append(high_scoring_outline_page)
    all_pages.extend(annotated_answer_pages)
    all_pages.append(refined_summary_page)

    first = all_pages[0]
    rest = all_pages[1:]

    print(f"Step 12: Writing final PDF to {output_pdf_path} ...")
    first.save(
        output_pdf_path,
        "PDF",
        resolution=300.0,
        save_all=True,
        append_images=rest,
    )
    print("Done.")
    
    # Add token usage to the grading result JSON so frontend can record it
    print(f"OCR completed. Token usage: Input: {total_input_tokens}, Output: {total_output_tokens}")
    
    # Update the JSON file with token usage information
    try:
        with open(output_json_path, "r", encoding="utf-8") as f:
            grading_data = json.load(f)
        
        grading_data["token_usage"] = {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens
        }
        
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(grading_data, f, ensure_ascii=False, indent=2)
        
        print(f"Token usage added to grading result for user {user_id[:8] if user_id else 'unknown'}...")
    except Exception as e:
        print(f"Warning: Failed to add token usage to JSON: {e}")


# -----------------------------
# CLI
# -----------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Grade a handwritten PDF answer using Grok + Google Vision OCR, "
        "generate a subject-wise report, annotate the answer pages, "
        "and add a refined-rubric summary page."
    )
    parser.add_argument("--pdf_path", required=True, help="Path to the PDF file to grade.")
    parser.add_argument("--subject", required=True, help="Subject name, e.g., 'British History'.")
    parser.add_argument(
        "--output_json",
        default="grading_result.json",
        help="Path to write the grading JSON output.",
    )
    parser.add_argument(
        "--output_pdf",
        default="result.pdf",
        help="Path to write the final PDF (report + annotated pages + rubric summary).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        args = parse_args()
        grade_pdf_answer(
            pdf_path=args.pdf_path,
            subject=args.subject,
            output_json_path=args.output_json,
            output_pdf_path=args.output_pdf,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
