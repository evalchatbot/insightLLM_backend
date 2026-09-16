"""
grade_psych_assessment.py
==========================

Dedicated evaluation pipeline for the CSS/PMS **Psychological Assessment** paper.

Unlike the generic 20-mark essay grader (`backend/ocr/grade_pdf_answer.py`), this
paper is multi-section (IQ MCQs, English/Urdu sentence completion, projective
drawings, story completion, self-description, word association, picture/TAT story)
and each section needs its own kind of feedback. The objective IQ section is kept
strictly separate from the projective/personality sections in the report.

Design:
  * Reuse the heavy primitives from the OCR package:
      - load_environment()          -> (grok_key, google vision client)
      - run_ocr_on_pdf()            -> word/line boxes (200 DPI pixels)
      - annotate_pdf_answer_pages() -> renders [left suggestions][page][right issues]
        with boxes + connector lines, given annotations + page_suggestions.
  * Add psych-specific logic here: section detection, AI MCQ solving, per-section
    annotation generation, scoring, and an IQ-vs-projective separated cover.

Nothing in this module touches the other 24 subjects.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image

# Reused primitives from the OCR package.
from backend.ocr.grade_pdf_answer import load_environment
from backend.ocr.ocr_vision import run_ocr_on_pdf
from backend.ocr.annotate_pdf_with_rubric import annotate_pdf_answer_pages
from backend.ocr.grok_client import call_grok_api, GROK_MODEL, GrokAPIError


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------

def _log(log_path: Optional[str], level: str, msg: str) -> None:
    line = f"[{level}] {msg}"
    print(line)
    if not log_path:
        return
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _progress(tracker: Optional[Any], step: int, label: str) -> None:
    if tracker is None:
        return
    try:
        # Mirror the OCR progress tracker's interface loosely; never fail on it.
        if hasattr(tracker, "update"):
            tracker.update(step, label)
        elif callable(tracker):
            tracker(step, label)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# The Psychological Assessment sections
# ---------------------------------------------------------------------------
# key             -> human label + how we annotate it
#   "objective"   -> IQ MCQs: AI solves, marks wrong ones (right-side notes)
#   "detailed"    -> per-error boxes over the handwriting (right mistake / left fix)
#   "aggregate"   -> one right "overall mistakes" + one left "suggestions" per section
#   "image"       -> same as aggregate but the section is drawing/picture based

SECTION_DEFS: List[Dict[str, str]] = [
    {"key": "autobiography", "label": "Autobiography", "mode": "detailed"},
    {"key": "iq_mcq", "label": "IQ / Ability (Objective)", "mode": "objective"},
    {"key": "english_sentences", "label": "English Sentence Completion", "mode": "aggregate"},
    {"key": "urdu_sentences", "label": "Urdu Sentence Completion", "mode": "aggregate"},
    {"key": "drawings", "label": "Projective Drawings", "mode": "image"},
    {"key": "story_completion", "label": "Story Completion", "mode": "detailed"},
    {"key": "self_description", "label": "Self-Description", "mode": "aggregate"},
    {"key": "word_association", "label": "Word Association", "mode": "aggregate"},
    {"key": "picture_story", "label": "Picture / TAT Story", "mode": "image"},
]
SECTION_BY_KEY = {s["key"]: s for s in SECTION_DEFS}

# Verbatim design principle the client asked to keep as its own block in the report.
DESIGN_NOTE = (
    "Keep the objective (IQ) and projective (personality) sections clearly "
    "separated in the output. Merging them into one score would misrepresent "
    "what's actually a right/wrong test vs. a pattern-based psychological screen."
)

# rubric.ai brand accent (matches the main app's red).
ACCENT = (0.757, 0.153, 0.176)  # #C1272D
INK = (0.10, 0.10, 0.10)
MUTED = (0.42, 0.38, 0.34)
CREAM = (0.949, 0.929, 0.890)


# ---------------------------------------------------------------------------
# Image + OCR helpers
# ---------------------------------------------------------------------------

def _page_images_b64(
    pdf_path: str,
    pages: Optional[List[int]] = None,
    dpi: int = 150,
    max_dim: int = 1500,
    quality: int = 82,
) -> Dict[int, str]:
    """Render selected pages to base64 JPEG (readable resolution for Grok vision)."""
    doc = fitz.open(pdf_path)
    out: Dict[int, str] = {}
    try:
        for i, page in enumerate(doc):
            pnum = i + 1
            if pages and pnum not in pages:
                continue
            pix = page.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            if max(img.size) > max_dim:
                r = max_dim / max(img.size)
                img = img.resize((int(img.width * r), int(img.height * r)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            out[pnum] = base64.b64encode(buf.getvalue()).decode("ascii")
    finally:
        doc.close()
    return out


def _ocr_text_by_page(ocr_data: Dict[str, Any]) -> Dict[int, str]:
    res: Dict[int, str] = {}
    for p in ocr_data.get("pages", []):
        lines = [str(l.get("text", "")) for l in p.get("lines", [])]
        res[int(p.get("page_number", 0))] = "\n".join(lines)
    return res


# ---------------------------------------------------------------------------
# Grok call helpers
# ---------------------------------------------------------------------------

def _grok_json(
    grok_key: str,
    system: str,
    user_text: str,
    images_b64: Optional[List[str]] = None,
    *,
    max_tokens: int = 6000,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    """One Grok chat call that must return a JSON object. Vision-capable."""
    content: List[Dict[str, Any]] = [{"type": "text", "text": user_text}]
    for b in images_b64 or []:
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}}
        )
    payload = {
        "model": GROK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    parsed, _usage = call_grok_api(grok_key, payload, max_retries=3, retry_backoff=True)
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Step 1 — Section detection (text-based; the paper has printed headers)
# ---------------------------------------------------------------------------

_SECTION_SYSTEM = (
    "You are segmenting a scanned CSS Psychological Assessment answer booklet into "
    "its printed sections. Use the printed headings/instructions on each page. "
    "Return STRICT JSON only."
)


def _detect_sections(grok_key: str, ocr_by_page: Dict[int, str], page_count: int, log_path) -> Dict[str, List[int]]:
    keys = ", ".join(s["key"] for s in SECTION_DEFS)
    joined = "\n\n".join(f"=== PAGE {p} ===\n{ocr_by_page.get(p, '')[:1500]}" for p in range(1, page_count + 1))
    user = (
        f"The booklet has {page_count} pages. For EACH section that is present, list the page "
        "numbers it appears on.\n"
        "IMPORTANT: a single page may belong to TWO sections when it contains the END of one "
        "section and the START of the next (e.g. the last IQ MCQs at the top and the first "
        "sentence-completion items below on the same page). In that case include that page in "
        "BOTH sections' page lists.\n"
        f"Allowed section keys: {keys}.\n"
        "Guidance on printed markers:\n"
        "- autobiography: 'Write a brief autobiography'\n"
        "- iq_mcq: 'Part-1 (IQ)', numbered questions with (a)(b)(c)(d) options, letter/number series, coding\n"
        "- english_sentences: 'Sentence Completion' / 'Complete the sentences' in ENGLISH (Roman script)\n"
        "- urdu_sentences: sentence completion in URDU (Urdu script)\n"
        "- drawings: 'Draw a person...', 'Draw the Future You' (a sketch, little text)\n"
        "- story_completion: 'Story Completion Test', 'Complete the story', Story 1 / Story 2\n"
        "- self_description: 'Self Description' structured questionnaire\n"
        "- word_association: 60 single words with one-word responses, 'Write the first thing'\n"
        "- picture_story: 'Picture 1'/'Picture 2', TAT-style write a story about the picture\n\n"
        f"OCR TEXT PER PAGE:\n{joined}\n\n"
        'Return JSON: {"sections":[{"section":"iq_mcq","pages":[2,3]}, ...]} - list only sections '
        "that are actually present."
    )
    data = _grok_json(grok_key, _SECTION_SYSTEM, user, max_tokens=2000, temperature=0.0)
    mapping: Dict[str, List[int]] = {}
    for row in data.get("sections", []) or []:
        key = str(row.get("section", "")).strip().lower()
        if key not in SECTION_BY_KEY:
            continue
        for p in row.get("pages", []) or []:
            try:
                pi = int(p)
            except Exception:
                continue
            if 1 <= pi <= page_count:
                mapping.setdefault(key, []).append(pi)
    for k in mapping:
        mapping[k] = sorted(set(mapping[k]))
    _log(log_path, "INFO", f"section map: {mapping}")
    return mapping


# ---------------------------------------------------------------------------
# Step 2 — IQ MCQs (AI solves, marks wrong)
# ---------------------------------------------------------------------------

_IQ_SYSTEM = (
    "You are a meticulous CSS IQ/ability test grader. You are given page images of a "
    "printed MCQ section where the candidate has hand-marked ONE option per question "
    "(a tick, circle, slash or underline on an option). For EACH question: \n"
    "1. Derive the EXACT rule and verify it holds for ALL the given terms before answering.\n"
    "2. Compute the answer the rule produces, then match it to the printed options.\n"
    "3. Separately read which option the candidate hand-marked from the image.\n"
    "4. Mark correct only if the candidate's option equals your computed answer.\n"
    "Be especially careful with number series (check differences AND ratios), letter "
    "series (consistent step patterns), coding-decoding (letter shifts), and analogies. "
    "Do not guess; if unsure, re-derive. Return STRICT JSON only."
)


def _evaluate_iq(grok_key: str, pdf_path: str, pages: List[int], ocr_by_page, log_path) -> Dict[str, Any]:
    imgs = _page_images_b64(pdf_path, pages=pages, dpi=170, max_dim=1700)
    ordered = [imgs[p] for p in pages if p in imgs]
    ocr_ctx = "\n\n".join(f"=== PAGE {p} OCR ===\n{ocr_by_page.get(p, '')[:2500]}" for p in pages)
    user = (
        "Grade the IQ / ability MCQ section shown in the images. "
        "The OCR text (printed questions) is provided to help you read option letters "
        "exactly; the IMAGES are the source of truth for which option the candidate marked.\n\n"
        f"{ocr_ctx}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "questions": [\n'
        '    {"number": 1, "page": 2, "question": "<short question text>",\n'
        '     "student_option": "b", "correct_option": "c",\n'
        '     "correct_value": "<the correct answer value e.g. 81>",\n'
        '     "is_correct": false, "why": "<one short sentence why the correct answer is correct>",\n'
        '     "anchor": "<exact printed phrase copied from the question line, <=8 words>"}\n'
        "  ],\n"
        '  "subskills": [{"name": "Number series", "correct": 3, "total": 5, "note": "<gap note>"}],\n'
        '  "weakest_subskill": "<name>"\n'
        "}\n"
        "Rules: student_option/correct_option are single letters a-d. 'anchor' MUST be the "
        "DISTINCTIVE content of the question (the specific numbers, letters or words being tested, "
        "e.g. '2, 6, 12, 20, 30' or 'AZ, CX, FU' or \"WATER is XBUFS\"), copied verbatim from the "
        "printed line - NEVER a generic lead-in like 'Complete the series' or 'Find the next number' "
        "(those repeat across questions and cannot be located). Include EVERY question."
    )
    data = _grok_json(grok_key, _IQ_SYSTEM, user, ordered, max_tokens=8000, temperature=0.0)
    qs = data.get("questions", []) or []
    correct = sum(1 for q in qs if q.get("is_correct") is True)
    _log(log_path, "INFO", f"IQ: {correct}/{len(qs)} correct")
    data["_correct"] = correct
    data["_total"] = len(qs)
    return data


def _iq_annotations(iq: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Right-side note on each WRONG MCQ: correct answer + one-line why. Nothing extra."""
    anns: List[Dict[str, Any]] = []
    for q in iq.get("questions", []) or []:
        if q.get("is_correct") is True:
            continue
        page = q.get("page")
        anchor = (q.get("anchor") or q.get("question") or "").strip()
        if not page or not anchor:
            continue
        co = str(q.get("correct_option", "")).strip()
        cv = str(q.get("correct_value", "")).strip()
        so = str(q.get("student_option", "")).strip()
        correct_label = f"({co}) {cv}".strip() if co or cv else "see key"
        comment = f"Q{q.get('number')}: marked ({so}) — wrong. Correct: {correct_label}. {q.get('why','')}".strip()
        anns.append({
            "type": "factual_error",
            "rubric_point": "iq_objective",
            "page": int(page),
            "target_word_or_sentence": anchor,
            "context_before": "",
            "context_after": "",
            "anchor_quote": anchor,
            "correction": correct_label,
            "comment": comment,
        })
    return anns


# ---------------------------------------------------------------------------
# Step 3 — Detailed sections (per-error boxes): autobiography, story_completion
# ---------------------------------------------------------------------------

_DETAILED_SYSTEM = (
    "You are a CSS evaluator marking a HANDWRITTEN answer. Point out concrete mistakes "
    "(spelling, grammar, word choice, unclear/weak content) by quoting the EXACT words as "
    "written by the candidate, and give a short fix for each. Return STRICT JSON only."
)


def _evaluate_detailed(grok_key, pdf_path, section_key, label, pages, ocr_by_page, log_path) -> Dict[str, Any]:
    imgs = _page_images_b64(pdf_path, pages=pages, dpi=170, max_dim=1700)
    ordered = [imgs[p] for p in pages if p in imgs]
    ocr_ctx = "\n\n".join(f"=== PAGE {p} OCR ===\n{ocr_by_page.get(p, '')[:3000]}" for p in pages)
    user = (
        f"Section: {label}. Pages: {pages}.\n"
        "Mark the candidate's handwritten answer. Identify up to 8 of the most important "
        "concrete mistakes across these pages. For each mistake quote the candidate's EXACT "
        "words (as they appear in the OCR text below) so it can be located and boxed.\n\n"
        f"{ocr_ctx}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "errors": [\n'
        '    {"page": 9, "target": "<exact wrong words copied from OCR>",\n'
        '     "context_before": "<up to 4 exact words before>",\n'
        '     "context_after": "<up to 4 exact words after>",\n'
        '     "mistake": "<what is wrong, short>", "fix": "<the correction/suggestion, short>"}\n'
        "  ],\n"
        '  "scores": [{"dimension": "<rubric dimension>", "score": 3, "max": 5, "note": "<short>"}],\n'
        '  "overall": "<2-sentence overall judgement of this section>"\n'
        "}\n"
        "Rules: 'target' and the contexts MUST be copied verbatim from the OCR so they match the page. "
        "Prefer short targets (1-6 words). If handwriting is unreadable, skip that item."
    )
    data = _grok_json(grok_key, _DETAILED_SYSTEM, user, ordered, max_tokens=7000, temperature=0.2)
    _log(log_path, "INFO", f"{section_key}: {len(data.get('errors', []) or [])} errors")
    return data


def _detailed_to_annotations(section_key, data) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (right-side annotations = mistakes, left-side page_suggestions = fixes)."""
    anns: List[Dict[str, Any]] = []
    sugg_by_page: Dict[int, List[Dict[str, str]]] = {}
    for e in data.get("errors", []) or []:
        page = e.get("page")
        target = (e.get("target") or "").strip()
        if not page or not target:
            continue
        page = int(page)
        cb = (e.get("context_before") or "").strip()
        ca = (e.get("context_after") or "").strip()
        anchor = " ".join(x for x in [cb, target, ca] if x).strip()
        anns.append({
            "type": "factual_error",
            "rubric_point": section_key,
            "page": page,
            "target_word_or_sentence": target,
            "context_before": cb,
            "context_after": ca,
            "anchor_quote": anchor,
            "correction": (e.get("fix") or "").strip(),
            "comment": (e.get("mistake") or "").strip(),
        })
        fix = (e.get("fix") or "").strip()
        if fix:
            sugg_by_page.setdefault(page, []).append({"suggestion": fix, "anchor_quote": anchor})
    page_suggestions = [{"page": p, "suggestions": s} for p, s in sugg_by_page.items()]
    return anns, page_suggestions


# ---------------------------------------------------------------------------
# Step 4 — Aggregate / image sections: one right "overall mistakes" + left "suggestions"
# ---------------------------------------------------------------------------

_AGG_SYSTEM = (
    "You are a CSS evaluator. For a whole section you give ONE overall list of mistakes and "
    "ONE overall list of suggestions, written in complete sentences and general terms (do NOT "
    "quote or number individual items). Return STRICT JSON only."
)


def _evaluate_aggregate(grok_key, pdf_path, section_key, label, mode, pages, ocr_by_page, log_path) -> Dict[str, Any]:
    imgs = _page_images_b64(pdf_path, pages=pages, dpi=160, max_dim=1600)
    ordered = [imgs[p] for p in pages if p in imgs]
    ocr_ctx = "\n\n".join(f"=== PAGE {p} OCR ===\n{ocr_by_page.get(p, '')[:2500]}" for p in pages)
    image_hint = (
        "This is a drawing/picture-based section; judge task compliance, effort, and what the "
        "content signals — do NOT clinically diagnose."
        if mode == "image" else
        "Judge the section against its rubric dimensions."
    )
    user = (
        f"Section: {label}. Pages: {pages}. {image_hint}\n"
        "Give an overall assessment of the WHOLE section. Do not mention specific item numbers "
        "or quote specific answers; speak generally in complete sentences.\n\n"
        f"{ocr_ctx}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "overall_mistakes": "<complete-sentence paragraph of the overall weaknesses>",\n'
        '  "suggestions": "<complete-sentence paragraph of how to improve>",\n'
        '  "anchor": "<an exact printed phrase copied from page '
        f"{pages[0] if pages else 1}, <=8 words; prefer the section's main heading or task "
        "prompt, NOT a time/marks note>\",\n"
        f'  "anchor_page": {pages[0] if pages else 1},\n'
        '  "scores": [{"dimension": "<rubric dimension>", "score": 3, "max": 5, "note": "<short>"}]\n'
        "}\n"
        "The 'anchor' MUST be copied verbatim from a PRINTED line so it can be located."
    )
    data = _grok_json(grok_key, _AGG_SYSTEM, user, ordered, max_tokens=3500, temperature=0.2)
    _log(log_path, "INFO", f"{section_key}: aggregate assessed")
    return data


def _aggregate_to_annotations(section_key, label, data, fallback_page, ocr_by_page) -> Tuple[List, List]:
    anchor = (data.get("anchor") or "").strip()
    page = int(data.get("anchor_page") or fallback_page or 1)
    # Fallback: pick the first substantial printed line from the page's OCR.
    if not anchor:
        for ln in (ocr_by_page.get(page, "") or "").split("\n"):
            if len(ln.strip()) >= 8:
                anchor = ln.strip()[:60]
                break
    anns: List[Dict[str, Any]] = []
    suggs: List[Dict[str, Any]] = []
    mistakes = (data.get("overall_mistakes") or "").strip()
    suggestion = (data.get("suggestions") or "").strip()
    if anchor and mistakes:
        anns.append({
            "type": "factual_error",
            "rubric_point": section_key,
            "page": page,
            "target_word_or_sentence": anchor,
            "context_before": "",
            "context_after": "",
            "anchor_quote": anchor,
            "correction": "",
            "comment": f"{label} — overall issues: {mistakes}",
        })
    if anchor and suggestion:
        suggs.append({"page": page, "suggestions": [{"suggestion": f"{label}: {suggestion}", "anchor_quote": anchor}]})
    return anns, suggs


# ---------------------------------------------------------------------------
# Report cover (IQ objective vs projective/personality — kept separate)
# ---------------------------------------------------------------------------

def _merge_page_suggestions(target: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> None:
    by_page = {ps["page"]: ps for ps in target}
    for ps in new:
        p = ps["page"]
        if p in by_page:
            by_page[p]["suggestions"].extend(ps.get("suggestions", []))
        else:
            target.append(ps)
            by_page[p] = ps


def _draw_cover(doc: fitz.Document, model: Dict[str, Any]) -> None:
    """Render the cover + IQ/projective-separated summary as the first PDF page(s)."""
    W, H = fitz.paper_size("a4")
    page = doc.new_page(width=W, height=H)
    mx, y = 44, 54
    page.draw_rect(fitz.Rect(0, 0, W, H), color=None, fill=CREAM)

    def text(s, x, yy, size=10, font="helv", color=INK, maxw=None):
        if maxw:
            page.insert_textbox(fitz.Rect(x, yy - size, x + maxw, yy + size * 6),
                                s, fontsize=size, fontname=font, color=color)
        else:
            page.insert_text((x, yy), s, fontsize=size, fontname=font, color=color)

    # Header
    text("Psychological Assessment", mx, y, size=22, font="hebo", color=INK)
    y += 22
    text("CSS Screening Evaluation Report", mx, y, size=10, font="helv", color=MUTED)
    cand = model.get("candidate_name") or ""
    if cand:
        text(f"Candidate: {cand}", W - 260, 54, size=9, font="helv", color=MUTED)
    page.draw_line(fitz.Point(mx, y + 10), fitz.Point(W - mx, y + 10), color=ACCENT, width=2)
    y += 34

    # Overall suitability (clearly labelled as a screening aid)
    suit = model.get("suitability", {})
    box = fitz.Rect(mx, y, W - mx, y + 74)
    page.draw_rect(box, color=(0.85, 0.82, 0.78), fill=(1, 1, 1), width=0.8)
    text("Overall Suitability Indicator (screening aid - not a clinical or final verdict)",
         mx + 12, y + 18, size=8.5, font="helv", color=MUTED)
    text(str(suit.get("label", "-")), mx + 12, y + 42, size=15, font="hebo", color=ACCENT)
    text(str(suit.get("note", ""))[:200], mx + 12, y + 62, size=8.5, font="helv", color=MUTED, maxw=W - 2 * mx - 24)
    y += 92

    # ---- Section A: IQ (Objective) ----
    text("A.  IQ / Ability — Objective", mx, y, size=13, font="hebo", color=INK)
    y += 8
    page.draw_line(fitz.Point(mx, y), fitz.Point(W - mx, y), color=(0.8, 0.77, 0.72), width=1)
    y += 20
    iq = model.get("iq", {})
    text(f"Score: {iq.get('correct', 0)} / {iq.get('total', 0)} correct", mx, y, size=11, font="hebo", color=INK)
    weakest = iq.get("weakest")
    if weakest:
        text(f"Weakest sub-skill: {weakest}", mx + 200, y, size=10, font="helv", color=ACCENT)
    y += 18
    for ss in (iq.get("subskills") or [])[:6]:
        line = f"-  {ss.get('name','')}: {ss.get('correct','?')}/{ss.get('total','?')}"
        note = ss.get("note") or ""
        text(line, mx + 8, y, size=9, font="helv", color=INK)
        if note:
            text(str(note)[:80], mx + 240, y, size=8.5, font="helv", color=MUTED, maxw=W - mx - 240 - 12)
        y += 14
    y += 10

    # ---- Design principle note (verbatim, its own block) ----
    note_box = fitz.Rect(mx, y, W - mx, y + 52)
    page.draw_rect(note_box, color=ACCENT, fill=(0.98, 0.94, 0.94), width=0.8)
    page.insert_textbox(fitz.Rect(mx + 12, y + 8, W - mx - 12, y + 50),
                        f"( {DESIGN_NOTE} )", fontsize=8.6, fontname="helv", color=(0.5, 0.12, 0.14))
    y += 70

    # ---- Section B: Personality (Projective) ----
    text("B.  Personality Profile — Projective", mx, y, size=13, font="hebo", color=INK)
    y += 8
    page.draw_line(fitz.Point(mx, y), fitz.Point(W - mx, y), color=(0.8, 0.77, 0.72), width=1)
    y += 20
    for dim in (model.get("personality") or [])[:12]:
        name = dim.get("name", "")
        sc = dim.get("score")
        mx_ = dim.get("max", 5)
        label = f"-  {name}"
        if sc is not None:
            label += f": {sc}/{mx_}"
        text(label, mx + 8, y, size=9.5, font="helv", color=INK, maxw=W - 2 * mx - 16)
        y += 15
    y += 8

    flags = model.get("flags") or []
    if flags:
        text("Flags for human review:", mx, y, size=10, font="hebo", color=ACCENT)
        y += 15
        for f in flags[:6]:
            text(f"-  {f}", mx + 8, y, size=9, font="helv", color=INK, maxw=W - 2 * mx - 16)
            y += 14

    # Footer
    page.insert_text((mx, H - 30),
                     "Generated by rubric.ai — Psychological Assessment. Objective (IQ) and projective (personality) "
                     "results are reported separately by design.",
                     fontsize=7.5, fontname="helv", color=MUTED)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def grade_psych_assessment(
    pdf_path: str,
    output_pdf_path: str,
    output_json_path: Optional[str] = None,
    log_path: Optional[str] = None,
    request_id: Optional[str] = None,
    progress_tracker: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Full Psychological Assessment evaluation:
      OCR -> section map -> IQ solve -> per-section annotations -> render -> report.

    Writes the annotated report PDF to `output_pdf_path` and returns the result metadata
    dict (also written to `output_json_path` if given).
    """
    _log(log_path, "INFO", f"psych start request={request_id} pdf={pdf_path}")
    grok_key, vision_client = load_environment()

    # 1) OCR (word boxes for anchoring)
    _progress(progress_tracker, 1, "Reading pages (OCR)")
    ocr_data = run_ocr_on_pdf(vision_client, pdf_path, log_path=log_path, request_id=request_id)
    ocr_by_page = _ocr_text_by_page(ocr_data)
    page_count = len(ocr_data.get("pages", []))
    _log(log_path, "INFO", f"OCR done: {page_count} pages")

    # 2) Section detection
    _progress(progress_tracker, 2, "Detecting sections")
    section_pages = _detect_sections(grok_key, ocr_by_page, page_count, log_path)

    annotations: List[Dict[str, Any]] = []
    page_suggestions: List[Dict[str, Any]] = []
    report: Dict[str, Any] = {
        "iq": {"correct": 0, "total": 0, "subskills": [], "weakest": None},
        "personality": [],
        "flags": [],
        "sections": {},
        "candidate_name": None,
    }

    step = 3
    for sdef in SECTION_DEFS:
        key, label, mode = sdef["key"], sdef["label"], sdef["mode"]
        pages = section_pages.get(key, [])
        if not pages:
            continue
        _progress(progress_tracker, step, f"Evaluating {label}")
        step += 1
        try:
            if mode == "objective":
                iq = _evaluate_iq(grok_key, pdf_path, pages, ocr_by_page, log_path)
                annotations.extend(_iq_annotations(iq))
                report["iq"] = {
                    "correct": iq.get("_correct", 0),
                    "total": iq.get("_total", 0),
                    "subskills": iq.get("subskills", []),
                    "weakest": iq.get("weakest_subskill"),
                }
            elif mode == "detailed":
                data = _evaluate_detailed(grok_key, pdf_path, key, label, pages, ocr_by_page, log_path)
                anns, suggs = _detailed_to_annotations(key, data)
                annotations.extend(anns)
                _merge_page_suggestions(page_suggestions, suggs)
                report["sections"][key] = {"label": label, "scores": data.get("scores", []),
                                           "overall": data.get("overall", "")}
                for sc in data.get("scores", []) or []:
                    report["personality"].append({"name": f"{label}: {sc.get('dimension','')}",
                                                   "score": sc.get("score"), "max": sc.get("max", 5),
                                                   "note": sc.get("note")})
                if key == "autobiography":
                    # try to pull just the candidate's name from the first OCR page
                    first = (ocr_by_page.get(pages[0], "") or "")
                    m = re.search(r"(?:I am|My name is|I'm)\s+(.+)", first, re.IGNORECASE)
                    if m:
                        picked: List[str] = []
                        for w in m.group(1).split():
                            wc = w.strip(".,")
                            if wc[:1].isupper() and wc.isalpha():
                                picked.append(wc)
                                if len(picked) >= 3:
                                    break
                            else:
                                break
                        if picked:
                            report["candidate_name"] = " ".join(picked)
            else:  # aggregate / image
                data = _evaluate_aggregate(grok_key, pdf_path, key, label, mode, pages, ocr_by_page, log_path)
                anns, suggs = _aggregate_to_annotations(key, label, data, pages[0] if pages else 1, ocr_by_page)
                annotations.extend(anns)
                _merge_page_suggestions(page_suggestions, suggs)
                report["sections"][key] = {"label": label, "scores": data.get("scores", [])}
                for sc in data.get("scores", []) or []:
                    report["personality"].append({"name": f"{label}: {sc.get('dimension','')}",
                                                   "score": sc.get("score"), "max": sc.get("max", 5),
                                                   "note": sc.get("note")})
        except (GrokAPIError, Exception) as e:  # never let one section kill the run
            _log(log_path, "WARNING", f"section {key} failed: {e}")

    # Flags for human review (rubric: evasiveness, unusual drawings, blank/trivial answers)
    if "drawings" in section_pages:
        report["flags"].append("Projective drawings present - route symbolic content to a psychologist reviewer.")

    # Overall suitability (composite, clearly a screening aid)
    iq_total = report["iq"].get("total") or 0
    iq_pct = (report["iq"].get("correct", 0) / iq_total) if iq_total else 0.0
    pscores = [d for d in report["personality"] if isinstance(d.get("score"), (int, float))]
    pers_pct = (sum(d["score"] / (d.get("max") or 5) for d in pscores) / len(pscores)) if pscores else 0.0
    composite = 0.5 * iq_pct + 0.5 * pers_pct
    band = ("Strong screening signal" if composite >= 0.75 else
            "Moderate screening signal" if composite >= 0.5 else
            "Needs closer review")
    report["suitability"] = {
        "label": band,
        "note": f"Composite of IQ ({iq_pct*100:.0f}%) and personality dimensions ({pers_pct*100:.0f}%). "
                "Screening aid only.",
    }

    # 3) Render annotated answer pages (reuse the OCR annotation engine)
    _progress(progress_tracker, step, "Drawing annotations")
    step += 1
    _log(log_path, "INFO", f"rendering: {len(annotations)} annotations, "
                           f"{sum(len(ps.get('suggestions', [])) for ps in page_suggestions)} suggestions")
    annotated_pages: List[Image.Image] = annotate_pdf_answer_pages(
        pdf_path=pdf_path,
        ocr_data=ocr_data,
        sections=[],  # we anchor via anchor_quote; no section ticks
        annotations=annotations,
        page_suggestions=page_suggestions,
        log_path=log_path,
        request_id=request_id,
        page_meta="Psychological Assessment",
    )

    # 4) Assemble final PDF: cover page(s) + annotated answer pages
    _progress(progress_tracker, step, "Building report")
    out_doc = fitz.open()
    _draw_cover(out_doc, report)
    for im in annotated_pages:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        rect = fitz.Rect(0, 0, im.width, im.height)
        pg = out_doc.new_page(width=im.width, height=im.height)
        pg.insert_image(rect, stream=buf.getvalue())
    os.makedirs(os.path.dirname(output_pdf_path) or ".", exist_ok=True)
    out_doc.save(output_pdf_path, deflate=True)
    out_doc.close()
    _log(log_path, "INFO", f"psych done -> {output_pdf_path}")

    result = {
        "subject": "Psychological Assessment",
        "request_id": request_id,
        "page_count": page_count,
        "section_pages": section_pages,
        "report": report,
        "annotation_count": len(annotations),
        "output_pdf_path": output_pdf_path,
    }
    if output_json_path:
        try:
            os.makedirs(os.path.dirname(output_json_path) or ".", exist_ok=True)
            with open(output_json_path, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            _log(log_path, "WARNING", f"could not write json: {e}")
    return result
