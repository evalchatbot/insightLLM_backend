#!/usr/bin/env python3
"""
Grok-powered evaluation pipeline that reads handwritten CSS exam pages directly from scans
and produces the formatted report PDF.
"""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from .grok_client import GrokClient, GrokError, GrokMessage, extract_content_text
from .pdf_renderer import render_annotated_pdf
from .pdf_utils import PageText, extract_text_per_page, pdf_pages_to_base64_images
from .rubric_loader import (
    get_subject_display_name,
    list_available_subjects,
    load_feedback_template_text,
    load_rubric_text,
)

logger = logging.getLogger(__name__)

MODEL_NAME = "grok-4-fast-reasoning"
MAX_CHAR_PER_PAGE = 80_000


@dataclass
class EvaluationResult:
    annotated_pdf: bytes
    metadata: Dict[str, Any]


def _prepare_page_bundle(pages: List[PageText]) -> List[Dict[str, Any]]:
    bundle: List[Dict[str, Any]] = []
    for page in pages:
        text = page.text
        if len(text) > MAX_CHAR_PER_PAGE:
            logger.info(
                "Truncating page %s from %s to %s characters for Grok payload.",
                page.page_number,
                len(text),
                MAX_CHAR_PER_PAGE,
            )
            text = text[:MAX_CHAR_PER_PAGE]
        bundle.append({"page": page.page_number, "text": text})
    return bundle


def _build_system_prompt() -> str:
    return (
        "You are an expert CSS examiner and professional report writer.\n"
        "You will receive scanned images of handwritten answers, along with approximate OCR text. "
        "Always prioritise what you see in the images to detect the question, extract content, and evaluate quality.\n\n"
        "Required steps:\n"
        "1. Detect the exact question the student attempted (quote it verbatim).\n"
        "2. Evaluate the answer strictly using the provided rubric and feedback template.\n"
        "3. Produce rich strengths/improvements that cite exact phrasing or lines (include page/paragraph hints).\n"
        "4. Return JSON exactly matching the schema described below.\n"
        "5. Generate HTML report pages that follow the formatting of the provided template.\n\n"
        "Output JSON schema:\n"
        "{\n"
        '  "detected_question": "<string>",\n'
        '  "answer_summary": "<string>",\n'
        '  "score": {\n'
        '     "total": {"value": <float>, "max": 20},\n'
        '     "grade_band": "<string>",\n'
        '     "score_explanation": "<string>"\n'
        "  },\n"
        '  "criteria": [\n'
        '     {\n'
        '        "name": "<string>",\n'
        '        "score": <float>,\n'
        '        "max": <float>,\n'
        '        "strengths": ["<string>", "..."],\n'
        '        "weaknesses": ["<string>", "..."],\n'
        '        "verdict": "<string>"\n'
        "     }\n"
        "  ],\n"
        '  "question_breakdown": {\n'
        '     "overview": "<string>",\n'
        '     "requirements": [ {"title": "<string>", "details": ["<string>", "..."]} ]\n'
        "  },\n"
        '  "ideal_outline": {\n'
        '     "question": "<string>",\n'
        '     "sections": [ {"heading": "<string>", "bullets": ["<string>", "..."]} ]\n'
        "  },\n"
        '  "recommendations": ["<string>", "..."],\n'
        '  "report_pages": [ "<HTML string>", ... ],\n'
        '  "metadata": {\n'
        '     "page_count": <int>,\n'
        '     "answer_word_count": <int>,\n'
        '     "answer_char_count": <int>,\n'
        '     "answer_language": "<string>"\n'
        "  }\n"
        "}\n\n"
        "Your tone must feel like an experienced mentor: precise, supportive, and evidence-backed."
    )


def _build_user_message_content(
    *,
    subject_id: str,
    subject_display_name: str,
    page_bundle: List[Dict[str, Any]],
    page_images: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    rubric_text = load_rubric_text(subject_id)
    template_text = load_feedback_template_text()
    bundle_json = json.dumps(page_bundle, ensure_ascii=False, indent=2)

    intro = (
        f"Subject: {subject_display_name}\n"
        f"Subject ID: {subject_id}\n\n"
        "Rubric:\n"
        f"{rubric_text}\n\n"
        "Feedback template:\n"
        f"{template_text}\n\n"
        "Approximate OCR text (for reference only; rely on the images for accuracy):\n"
        f"{bundle_json}\n"
    )

    content: List[Dict[str, Any]] = [{"type": "text", "text": intro}]
    for page in page_images:
        content.append({"type": "text", "text": f"Scan of page {page['page']}:"})
        content.append(
            {"type": "image_url", "image_url": {"url": page["data_url"], "detail": "high"}}
        )
    return content


def _parse_writing_issues(data: Dict[str, Any]) -> List[IssueRow]:
    issues_raw = data.get("writing_issues") or []
    parsed: List[IssueRow] = []
    for issue in issues_raw:
        try:
            parsed.append(
                IssueRow(
                    page=int(issue.get("page", 0) or 0),
                    issue_type=str(issue.get("type") or "Issue"),
                    original_text=str(issue.get("original") or ""),
                    correction=str(issue.get("correction") or ""),
                    rewrite=str(issue.get("rewrite") or ""),
                    reason=str(issue.get("reason") or ""),
                    location_hint=str(issue.get("location_hint") or ""),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping malformed writing issue entry %s: %s", issue, exc)
    return parsed


def _fallback_report_page() -> List[str]:
    return [
        """
        <html>
          <body style="font-family:Times New Roman,serif;padding:36px;">
            <h1>Evaluation Report</h1>
            <p>Report generation failed.</p>
          </body>
        </html>
        """
    ]


def _format_list(items: List[str]) -> str:
    if not items:
        return "<ul class='bullet-list'><li>Not provided.</li></ul>"
    bullet_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in items)
    return f"<ul class='bullet-list'>{bullet_html}</ul>"


def _format_requirements(requirements: List[Dict[str, Any]]) -> str:
    if not requirements:
        return "<ul class='bullet-list'><li>No requirements extracted.</li></ul>"
    blocks = []
    for idx, requirement in enumerate(requirements[:4], start=1):
        title = html.escape(str(requirement.get("title") or f"Requirement {idx}"))
        details = requirement.get("details") or []
        detail_items = "".join(
            f"<li>{html.escape(str(item))}</li>" for item in details[:3]
        )
        blocks.append(
            f"<div class='requirement-block'><div class='req-title'>{title}</div>"
            f"<ul class='req-bullets'>{detail_items}</ul></div>"
        )
    return "".join(blocks)


def _format_criteria(criteria: List[Dict[str, Any]]) -> List[str]:
    if not criteria:
        return ["<p>No criterion-level evaluation supplied.</p>"]

    rendered: List[str] = []
    for idx, crit in enumerate(criteria, start=1):
        name = html.escape(str(crit.get("name") or f"Criterion {idx}"))
        score = crit.get("score")
        max_score = crit.get("max")
        score_display = f"{score}/{max_score}" if score is not None and max_score is not None else ""
        verdict = html.escape(str(crit.get("verdict") or ""))
        strengths = _format_list(crit.get("strengths") or [])
        weaknesses = _format_list(crit.get("weaknesses") or [])

        rendered.append(
            f"""
            <div class='section-card criterion-block'>
              <h3>{idx}. {name} – <span class='score'>{score_display}</span></h3>
              <div class='subsection'>
                <h4>Strengths</h4>
                {strengths}
              </div>
              <div class='subsection'>
                <h4>Areas to Improve</h4>
                {weaknesses}
              </div>
              <p><strong>Verdict:</strong> {verdict}</p>
            </div>
            """
        )
    return rendered


def _chunk_list(items: List[Any], chunk_size: int) -> List[List[Any]]:
    if chunk_size <= 0:
        return [items]
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


REPORT_STYLE = """
<style>
  body {
    font-family: 'Times New Roman', serif;
    font-size: 12pt;
    color: #0f172a;
    margin: 54pt;
    line-height: 1.55;
  }
  h2 {
    font-family: 'Franklin Gothic Heavy', sans-serif;
    font-size: 14pt;
    font-weight: 400;
    text-transform: uppercase;
    margin-bottom: 6pt;
  }
  .report-title {
    font-family: 'Franklin Gothic Heavy', sans-serif;
    font-size: 14pt;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    margin-bottom: 8pt;
  }
  .score-line {
    font-family: 'Franklin Gothic Heavy', sans-serif;
    font-size: 22pt;
    color: #b91c1c;
    letter-spacing: 0.1em;
    margin-bottom: 12pt;
  }
  .subject-line {
    margin-bottom: 10pt;
  }
  .question-highlight {
    background: #fff3b3;
    border: 1px solid #efd86b;
    border-radius: 8pt;
    padding: 12pt 16pt;
    margin-bottom: 12pt;
  }
  .section-card {
    background: #ffffff;
    border: 1px solid #dfe3ee;
    border-radius: 10pt;
    padding: 16pt 18pt;
    margin-bottom: 14pt;
  }
  .bullet-list {
    margin: 10pt 0 10pt 24pt;
  }
  .criterion-block {
    margin-bottom: 18pt;
  }
</style>
"""


def _wrap_report_page(content: str, subtitle: str) -> str:
    return (
        "<html><head><meta charset='utf-8'/>"
        f"{REPORT_STYLE}</head><body>"
        f"<div class='report-title'>{html.escape(subtitle)}</div>"
        f"{content}"
        "</body></html>"
    )


def _build_report_pages(data: Dict[str, Any], subject_display_name: str) -> List[str]:
    score_block = data.get("score") or {}
    total_info = score_block.get("total") or {}
    score_text = total_info.get("value")
    max_score = total_info.get("max", 20)
    score_display = f"{score_text}/{max_score}" if score_text is not None else f"N/A/{max_score}"

    question_breakdown = data.get("question_breakdown") or {}
    question_text = question_breakdown.get("question") or data.get("detected_question") or ""
    overview = question_breakdown.get("overview") or ""
    requirements = question_breakdown.get("requirements") or []

    criteria = data.get("criteria") or []
    ideal_outline = data.get("ideal_outline") or {}
    outline_question = ideal_outline.get("question") or ""
    outline_sections = ideal_outline.get("sections") or []
    recommendations = data.get("recommendations") or []
    score_explanation = score_block.get("score_explanation") or ""

    page1 = f"""
      <div class="score-line">TOTAL SCORE: {html.escape(score_display)}</div>
      <p class="subject-line"><strong>Subject:</strong> {html.escape(subject_display_name)}</p>
      <div class="question-highlight">
        <strong>Detected Question:</strong><br/>
        {html.escape(question_text)}
      </div>
      <div class="section-card">
        <h2>Breakdown of the Question</h2>
        <p>{html.escape(overview)}</p>
        {_format_requirements(requirements)}
      </div>
    """

    pages: List[str] = [_wrap_report_page(page1, "Evaluation Report")]

    criterion_blocks = _format_criteria(criteria)
    for idx, chunk in enumerate(_chunk_list(criterion_blocks, 2), start=1):
        body = "<h2>Evaluation of the Submitted Answer</h2>" + "".join(chunk)
        pages.append(_wrap_report_page(body, f"Evaluation – Criteria (Page {idx})"))

    summary_body = ""
    if score_explanation:
        summary_body += f"<div class='section-card'><h2>Overall Comments</h2><p>{html.escape(score_explanation)}</p></div>"
    if recommendations:
        summary_body += (
            "<div class='section-card'><h2>Actionable Recommendations</h2>"
            f"{_format_list(recommendations)}</div>"
        )
    if summary_body:
        pages.append(_wrap_report_page(summary_body, "Evaluation – Summary"))

    outline_body = f"""
      <div class="section-card">
        <h2>High-Scoring Ideal Outline</h2>
        <p><strong>Question:</strong> {html.escape(outline_question)}</p>
        {_format_list(outline_sections)}
      </div>
    """
    pages.append(_wrap_report_page(outline_body, "Evaluation – Ideal Outline"))

    return pages


def run_grok_pipeline(
    *,
    pdf_bytes: bytes,
    subject_id: str,
    original_filename: str | None = None,
) -> EvaluationResult:
    pages = extract_text_per_page(pdf_bytes)
    page_images = pdf_pages_to_base64_images(pdf_bytes)
    if not page_images:
        raise ValueError("Unable to render PDF pages for analysis.")

    page_bundle = _prepare_page_bundle(pages)
    subject_display_name = get_subject_display_name(subject_id)

    client = GrokClient()
    system_prompt = _build_system_prompt()
    messages = [
        GrokMessage(role="system", content=system_prompt),
        GrokMessage(
            role="user",
            content=_build_user_message_content(
                subject_id=subject_id,
                subject_display_name=subject_display_name,
                page_bundle=page_bundle,
                page_images=page_images,
            ),
        ),
    ]

    response = client.chat_completion(
        model=MODEL_NAME,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.0,
        max_output_tokens=4096,
    )
    content = extract_content_text(response)
    
    # Extract token usage from Grok API response
    token_usage = response.get("_token_usage", {})
    prompt_tokens = token_usage.get("prompt_tokens", 0)
    completion_tokens = token_usage.get("completion_tokens", 0)
    
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse Grok JSON response: %s", content)
        raise GrokError(f"Grok returned invalid JSON: {exc}") from exc

    report_pages = _build_report_pages(data, subject_display_name)
    annotated_pdf = render_annotated_pdf(
        original_pdf=pdf_bytes,
        report_pages_html=report_pages,
        issue_rows=[],
    )

    detected_question = data.get("detected_question") or ""
    answer_summary = data.get("answer_summary") or ""
    strengths = data.get("strengths") or []
    improvements = data.get("improvements") or []
    final_comments = data.get("final_comments") or ""
    score_block = data.get("score") or {}
    total_score = score_block.get("total", {}).get("value")
    dimension_scores = score_block.get("dimensions") or []

    combined_answer = "\n\n".join(page.text for page in pages if page.text)
    char_count = len(combined_answer)
    word_count = len(combined_answer.split())

    metadata: Dict[str, Any] = {
        "detected_question": detected_question,
        "answer_summary": answer_summary,
        "strengths": strengths,
        "improvements": improvements,
        "final_comments": final_comments,
        "score": {
            "total_score": float(total_score) if total_score is not None else None,
            "max_score": score_block.get("total", {}).get("max", 20),
            "dimensions": dimension_scores,
        },
        "metadata": {
            "page_count": len(pages),
            "answer_char_count": char_count,
            "answer_word_count": word_count,
            "subject": subject_id,
            "subject_display_name": subject_display_name,
        },
        "token_usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
    if original_filename:
        metadata["metadata"]["file_name"] = original_filename

    return EvaluationResult(annotated_pdf=annotated_pdf, metadata=metadata)


def get_subjects_for_dropdown() -> List[Dict[str, str]]:
    return list_available_subjects()
