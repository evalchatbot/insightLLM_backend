from __future__ import annotations
import io, os, tempfile, uuid, time, re
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

import fitz  # PyMuPDF
import sys
from pathlib import Path

# Add the OCR script directory to Python path (robust detection)
_ocr_candidates: List[Path] = []
env_dir = os.getenv("OCR_MODULE_DIR")
if env_dir:
    _ocr_candidates.append(Path(env_dir))

# Common container layout: /app/ocr
_ocr_candidates.append(Path("/app/ocr"))

# Check backend utils path (common when ocr.py moved into backend/utils)
_ocr_candidates.append(Path(__file__).resolve().parents[1] / "utils")

# Repo-root heuristic: ../../.. from this file points to repo, then `ocr`
_ocr_candidates.append(Path(__file__).resolve().parents[2] / "ocr")
_ocr_candidates.append(Path(__file__).resolve().parents[3] / "ocr")

OCR_AVAILABLE = False
OCR_IMPORT_ERROR = None
ocr_script_path: Optional[Path] = None

import logging
logger = logging.getLogger("ocr_service")
logger.setLevel(logging.INFO)

# Emit candidate checks to stderr/logs for easier deployment debugging
for p in _ocr_candidates:
    try:
        logger.info(f"OCR candidate path: {p} exists={p.exists()}")
    except Exception:
        # best-effort logging
        print(f"OCR candidate path: {p} exists check failed", file=sys.stderr)

for cand in _ocr_candidates:
    try:
        if cand and cand.exists():
            sys.path.insert(0, str(cand))
            from ocr import (
                run_ocr_with_retries,
                writing_issues_for_page,
                writing_issues_for_text,
                evaluate_qa_detailed,
                writing_score_bins_value_and_label,
                annotate_pdf_with_report,
                QAReportDetailed,
                IssueRow,
                QAItem,
                load_env,
            )
            OCR_AVAILABLE = True
            ocr_script_path = cand
            break
    except Exception as e:
        OCR_IMPORT_ERROR = e
        continue

if not OCR_AVAILABLE:
    # Define minimal placeholders to avoid import-time crash; will error at runtime when used
    run_ocr_with_retries = None  # type: ignore
    writing_issues_for_page = None  # type: ignore
    writing_issues_for_text = None  # type: ignore
    evaluate_qa_detailed = None  # type: ignore
    writing_score_bins_value_and_label = None  # type: ignore
    annotate_pdf_with_report = None  # type: ignore
    QAReportDetailed = None  # type: ignore
    IssueRow = None  # type: ignore
    QAItem = None  # type: ignore
    load_env = None  # type: ignore

from groq import Groq

# small util: open pdf from bytes, save to temp file for Azure SDK call (expects path/handle)
def _bytes_to_temp_pdf(data: bytes) -> Path:
    tmp = Path(tempfile.gettempdir()) / f"{uuid.uuid4()}.pdf"
    with open(tmp, "wb") as f:
        f.write(data)
    return tmp

def _delete_file_safely(p: Path) -> None:
    try:
        if p.exists(): p.unlink()
    except Exception:
        pass

def _strip_question_from_text(text: str, question: str) -> Tuple[str, int]:
    if not text or not question:
        return text, 0
    normalized_question = question.strip()
    if not normalized_question:
        return text, 0
    pattern = re.compile(re.escape(normalized_question), re.IGNORECASE)
    matches = list(pattern.finditer(text))
    if not matches:
        return text, 0
    cleaned = pattern.sub("", text)
    # Trim excessive blank space introduced by removal
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(), len(matches)

def _normalize_subject(subject: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", subject.strip().lower())
    return slug.strip("_")

POLI_SCI_SYSTEM_PROMPT = (
    "You are a senior examiner for Pakistan's CSS Political Science paper. Apply rigorous, discipline-informed judgment. "
    "Interrogate how well the response fulfils the question's explicit requirements, the Political Science rubric, and the expectations of analytical depth, theory, and evidence.\n\n"
    "For scoring, use the JSON keys `relevance_0to4`, `coverage_0to4`, `accuracy_0to4`, `analysis_0to4`, and `organization_0to2`, scaling them against this rubric (reported denominator is 20 but the achievable ceiling is 16):\n"
    "• Relevance & Understanding — 0–5: break down the prompt, ensure every part is addressed without tangents, keep structure anchored to the question keywords.\n"
    "• Conceptual Clarity & Knowledge — 0–5: integrate political theory, thinkers, and doctrines accurately; connect classical and contemporary perspectives instead of name-dropping.\n"
    "• Critical Analysis & Argumentation — 0–4: weigh competing schools (liberal vs. Marxist, realist vs. idealist, etc.), surface causal logic, critique assumptions, and synthesise in the conclusion.\n"
    "• Structure & Organization — 0–3: preserve an Introduction–Body–Conclusion architecture, use meaningful headings/subheadings, maintain signposted transitions between arguments.\n"
    "• Examples & References — 0–2: ground claims in precise quotations, historical/contemporary case studies, and Pakistan/global relevance.\n"
    "Always penalise shallow description, uncritical narrative, misuse of thinkers, factual errors, and missing sub-parts. Reward answers that interrogate the question's core demand, compare perspectives, and marshal evidence judiciously.\n"
    "Ensure outputs stay within political science norms and return ONLY JSON."
)

POLITICAL_SCIENCE_PROFILE: Dict[str, Any] = {
    "subject_id": "political_science",
    "display_name": "Political Science",
    "system_prompt": POLI_SCI_SYSTEM_PROMPT,
    "criteria": [
        {
            "json_key": "relevance_0to4",
            "attr": "relevance",
            "label": "Relevance & Understanding",
            "max": 5,
            "detail_source": "question_summary",
            "detail_text": "Measures how directly the response answers every part of the prompt.",
        },
        {
            "json_key": "coverage_0to4",
            "attr": "coverage",
            "label": "Conceptual Clarity & Knowledge",
            "max": 5,
            "detail_source": "answer_summary",
            "detail_text": "Assesses integration of core theorists, doctrines, and definitions.",
        },
        {
            "json_key": "accuracy_0to4",
            "attr": "accuracy",
            "label": "Critical Analysis & Argumentation",
            "max": 4,
            "detail_text": "Rewards comparison of schools, critique, and defensible judgment.",
        },
        {
            "json_key": "analysis_0to4",
            "attr": "analysis",
            "label": "Structure & Organization",
            "max": 3,
            "detail_text": "Looks for Introduction–Body–Conclusion, keyword-driven headings, and smooth transitions.",
        },
        {
            "json_key": "organization_0to2",
            "attr": "organization",
            "label": "Examples & References",
            "max": 2,
            "detail_text": "Credits precise quotations, case studies, and Pakistan/global relevance.",
        },
    ],
    "content_cap": 19.0,
    "content_target": 15.0,
    "achievable_max": 16.0,
    "final_max": 20.0,
    "writing_max": 1.0,
    "issue_categories": "Relevance|Understanding|Knowledge|Analysis|Structure|Evidence|Depth|Style",
    "user_prompt_guidance": (
        "Use the Political Science rubric above; compare the answer to each extracted requirement, evaluate depth, and cite exact lines for every critique. "
        "Keep JSON strict and actionable."
    ),
}

SUBJECT_PROFILES: Dict[str, Dict[str, Any]] = {
    POLITICAL_SCIENCE_PROFILE["subject_id"]: POLITICAL_SCIENCE_PROFILE,
}
SUBJECT_DISPLAY_NAMES: Dict[str, str] = {
    key: prof.get("display_name", key.title()) for key, prof in SUBJECT_PROFILES.items()
}

def get_subject_profile(subject: str) -> Optional[Dict[str, Any]]:
    if not subject:
        return None
    normalized = _normalize_subject(subject)
    profile = SUBJECT_PROFILES.get(normalized)
    if profile:
        return profile
    # Allow matching by display name slug
    for key, prof in SUBJECT_PROFILES.items():
        if _normalize_subject(prof.get("display_name", "")) == normalized:
            return prof
    return None

class OCRAnnotator:
    def __init__(self, *, fast_mode: bool = False):
        self.fast_mode = fast_mode
        if not OCR_AVAILABLE:
            where = f"{ocr_script_path}" if ocr_script_path else "<not found>"
            raise ImportError(
                f"OCR module not available. Set OCR_MODULE_DIR to the folder containing ocr.py. "
                f"Searched: {', '.join(str(p) for p in _ocr_candidates)}. Last error: {OCR_IMPORT_ERROR}"
            )
        # ensure env variables exist (original script enforces this)
        self.endpoint, self.azure_key, self.groq_key = load_env()
        self.groq_client = Groq(api_key=self.groq_key)

    def annotate_pdf(
        self,
        *,
        pdf_bytes: bytes,
        original_filename: str,
        question_text: str,
        subject: str,
    ) -> Tuple[bytes, Dict[str, Any]]:
        """
        Process a PDF alongside a user-provided question, returning an annotated PDF and detailed metadata.
        """
        start_time = time.time()
        clean_question = (question_text or "").strip()
        subject_profile = get_subject_profile(subject)
        if subject and not subject_profile:
            supported = ", ".join(SUBJECT_DISPLAY_NAMES.values())
            raise ValueError(f"Unsupported subject '{subject}'. Supported subjects: {supported}")
        subject_id = subject_profile["subject_id"] if subject_profile else (_normalize_subject(subject) or "general")
        subject_label = subject_profile["display_name"] if subject_profile else (subject.strip() or "General")

        temp_input = _bytes_to_temp_pdf(pdf_bytes)
        temp_output = temp_input.with_name(f"{temp_input.stem}_annotated.pdf")

        page_texts: List[str] = []
        cleaned_page_texts: List[str] = []
        per_page_question_hits: List[int] = []
        combined_answer = ""
        question_occurrences_removed = 0
        qa_reports_with_labels: List[Tuple[QAReportDetailed, str]] = []
        all_detailed_issues: List[Dict[str, Any]] = []
        total_score = 0.0
        max_possible_score = 0.0
        max_achievable_score = 0.0
        scoring_profile_meta: Optional[Dict[str, Any]] = None

        try:
            page_texts = run_ocr_with_retries(
                temp_input,
                pages=None,
                timeout_s=120,
                max_retries=3,
            )

            for raw_text in page_texts:
                cleaned, removed = _strip_question_from_text(raw_text or "", clean_question)
                cleaned_page_texts.append(cleaned)
                per_page_question_hits.append(removed)
                question_occurrences_removed += removed

            combined_answer = "\n\n".join(text for text in cleaned_page_texts if text).strip()

            page_issues: List[List[IssueRow]] = []
            if self.fast_mode:
                page_issues = [[] for _ in cleaned_page_texts]
            else:
                for cleaned_text in cleaned_page_texts:
                    issues = writing_issues_for_page(
                        self.groq_client,
                        "llama-3.3-70b-versatile",
                        cleaned_text or "",
                    )
                    page_issues.append(issues)

            if clean_question and combined_answer:
                qa = QAItem(
                    number=1,
                    question=clean_question,
                    answer=combined_answer,
                    start_page=1,
                    end_page=len(page_texts) or 1,
                )
                ans_issues = writing_issues_for_text(
                    self.groq_client,
                    "llama-3.3-70b-versatile",
                    combined_answer,
                )
                raw_w_val, raw_w_label = writing_score_bins_value_and_label(ans_issues)
                writing_value = raw_w_val
                writing_label = raw_w_label
                if subject_profile:
                    target_writing_max = float(subject_profile.get("writing_max", 2.0))
                    if target_writing_max != 2.0:
                        scaled = round((raw_w_val / 2.0) * target_writing_max, 2)
                        suffix = ""
                        if "(" in raw_w_label:
                            suffix = raw_w_label[raw_w_label.find("("):]
                        writing_label = f"{scaled:.1f} /{target_writing_max:g} {suffix}".strip()
                        writing_value = scaled
                    else:
                        writing_value = raw_w_val
                rep, label = evaluate_qa_detailed(
                    self.groq_client,
                    "llama-3.3-70b-versatile",
                    qa,
                    writing_value,
                    writing_label,
                    subject_profile=subject_profile,
                )
                qa_reports_with_labels.append((rep, label))
                for issue in rep.issues:
                    all_detailed_issues.append(
                        {
                            "issue_id": f"q1_{len(all_detailed_issues)}",
                            "issue_title": f"{issue.get('category', 'Issue')}: {issue.get('problem', '')}",
                            "why_it_matters": issue.get("why_it_matters", ""),
                            "how_to_verify": issue.get("how_to_verify", ""),
                            "evidence_suggestions": issue.get("evidence_suggestions", []),
                            "impact_points_0to3": issue.get("impact_points_0to3", 0),
                            "location_hint": issue.get("location_hint", ""),
                        }
                    )
                total_score += rep.final_score_20
                max_possible_score += rep.score_max
                max_achievable_score += getattr(rep, "final_score_cap", rep.score_max)
                criteria_meta = []
                if subject_profile:
                    for crit in subject_profile.get("criteria", []):
                        criteria_meta.append(
                            {
                                "label": crit.get("label"),
                                "max_points": crit.get("max"),
                            }
                        )
                else:
                    criteria_meta = [
                        {"label": "Relevance", "max_points": 4},
                        {"label": "Coverage & Depth", "max_points": 4},
                        {"label": "Factual Accuracy", "max_points": 4},
                        {"label": "Analysis & Argumentation", "max_points": 4},
                        {"label": "Organization", "max_points": 2},
                    ]
                scoring_profile_meta = {
                    "content_max": rep.content_score_max,
                    "writing_max": rep.writing_score_max,
                    "total_max": rep.score_max,
                    "achievable_max": getattr(rep, "final_score_cap", rep.score_max),
                    "criteria": criteria_meta,
                }
            else:
                if subject_profile and scoring_profile_meta is None:
                    scoring_profile_meta = {
                        "content_max": subject_profile.get("content_target", subject_profile.get("content_cap", 18.0)),
                        "writing_max": subject_profile.get("writing_max", 2.0),
                        "total_max": subject_profile.get("final_max", 20.0),
                        "achievable_max": subject_profile.get("achievable_max", subject_profile.get("final_max", 20.0)),
                        "criteria": [
                            {"label": crit.get("label"), "max_points": crit.get("max")}
                            for crit in subject_profile.get("criteria", [])
                        ],
                    }
                    max_possible_score = max(max_possible_score, subject_profile.get("final_max", 20.0))
                    max_achievable_score = max(max_achievable_score, subject_profile.get("achievable_max", max_achievable_score))
                elif scoring_profile_meta is None:
                    scoring_profile_meta = {
                        "content_max": 18.0,
                        "writing_max": 2.0,
                        "total_max": 20.0,
                        "achievable_max": 20.0,
                        "criteria": [
                            {"label": "Relevance", "max_points": 4},
                            {"label": "Coverage & Depth", "max_points": 4},
                            {"label": "Factual Accuracy", "max_points": 4},
                            {"label": "Analysis & Argumentation", "max_points": 4},
                            {"label": "Organization", "max_points": 2},
                        ],
                    }
                    max_possible_score = max(max_possible_score, 20.0)
                    max_achievable_score = max(max_achievable_score, 20.0)

            annotate_pdf_with_report(
                temp_input,
                page_issues,
                qa_reports_with_labels,
                temp_output,
                max_rows_per_page=20,
                panel_width_ratio=0.30,
                height_max_ratio=0.60,
            )

            with open(temp_output, "rb") as f:
                annotated_bytes = f.read()

            processing_time = time.time() - start_time

            meta: Dict[str, Any] = {
                "issues": all_detailed_issues,
                "score": {
                    "total_score": round(total_score, 1),
                    "max_possible_score": round(max_possible_score, 1),
                    "max_achievable_score": round(max_achievable_score if max_achievable_score else max_possible_score, 1),
                },
                "metadata": {
                    "file_name": original_filename,
                    "page_count": len(page_texts),
                    "processing_time_seconds": round(processing_time, 2),
                    "fast_mode": self.fast_mode,
                    "provided_question": clean_question,
                    "question_occurrences_removed": question_occurrences_removed,
                    "question_occurrences_removed_per_page": per_page_question_hits,
                    "subject": {
                        "id": subject_id,
                        "label": subject_label,
                    },
                },
            }
            if scoring_profile_meta:
                meta["metadata"]["scoring_profile"] = scoring_profile_meta
            if combined_answer:
                meta["metadata"]["answer_char_count"] = len(combined_answer)
            if not qa_reports_with_labels:
                if subject_profile:
                    meta["score"]["max_possible_score"] = round(
                        subject_profile.get("final_max", meta["score"]["max_possible_score"]), 1
                    )
                    meta["score"]["max_achievable_score"] = round(
                        subject_profile.get("achievable_max", meta["score"]["max_achievable_score"]), 1
                    )
                else:
                    meta["score"]["max_possible_score"] = round(max_possible_score or 20.0, 1)
                    if not max_achievable_score:
                        meta["score"]["max_achievable_score"] = meta["score"]["max_possible_score"]

            return annotated_bytes, meta

        finally:
            _delete_file_safely(temp_input)
            _delete_file_safely(temp_output)
