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
                writing_score_bins_value_and_label,
                annotate_pdf_with_report,
                QAReportDetailed,
                IssueRow,
                QAItem,
                DEFAULT_MIN_WORD_COUNT,
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
    writing_score_bins_value_and_label = None  # type: ignore
    annotate_pdf_with_report = None  # type: ignore
    QAReportDetailed = None  # type: ignore
    IssueRow = None  # type: ignore
    QAItem = None  # type: ignore
    DEFAULT_MIN_WORD_COUNT = 800  # fallback
    load_env = None  # type: ignore

from groq import Groq

# Import rubric-based evaluator (new rubric-driven approach)
try:
    from backend.utils.rubric_evaluator import RubricEvaluator
    from backend.utils.rubric_parser import get_available_subjects, get_rubric_parser
    RUBRIC_EVALUATOR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Rubric evaluator not available: {e}")
    RubricEvaluator = None  # type: ignore
    get_available_subjects = None  # type: ignore
    def get_rubric_parser():  # type: ignore
        raise ImportError("Rubric parser unavailable")
    RUBRIC_EVALUATOR_AVAILABLE = False

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
    """
    Strip question from text with fuzzy matching to handle OCR errors.
    Uses multiple strategies:
    1. Exact match (case-insensitive)
    2. Fuzzy match allowing small character variations
    3. Word-by-word match (for partial OCR errors)
    """
    if not text or not question:
        return text, 0
    normalized_question = question.strip()
    if not normalized_question:
        return text, 0

    # Strategy 1: Exact match (case-insensitive)
    pattern = re.compile(re.escape(normalized_question), re.IGNORECASE)
    matches = list(pattern.finditer(text))
    if matches:
        cleaned = pattern.sub("", text)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip(), len(matches)

    # Strategy 2: Fuzzy match using first and last words
    # This handles cases where OCR misreads some characters in the middle
    question_words = normalized_question.split()
    if len(question_words) >= 5:  # Only for questions with 5+ words
        # Build flexible pattern: match first 3 words + last 2 words
        first_part = ' '.join(question_words[:3])
        last_part = ' '.join(question_words[-2:])
        fuzzy_pattern = re.compile(
            re.escape(first_part) + r'.{0,200}' + re.escape(last_part),
            re.IGNORECASE | re.DOTALL
        )
        fuzzy_matches = list(fuzzy_pattern.finditer(text))
        if fuzzy_matches:
            # Remove matched portions
            cleaned = text
            for match in reversed(fuzzy_matches):  # Reverse to maintain indices
                cleaned = cleaned[:match.start()] + cleaned[match.end():]
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
            return cleaned.strip(), len(fuzzy_matches)

    # Strategy 3: No match found, return original
    return text, 0

def _normalize_subject(subject: str) -> str:
    """
    Normalize subject name to match rubric parser format.
    Uses hyphens, not underscores, to match rubric file normalization.
    """
    normalized = subject.lower().strip()
    normalized = re.sub(r'[_\s]+', '-', normalized)  # Replace spaces/underscores with hyphens
    normalized = re.sub(r'[^a-z0-9\-]', '', normalized)  # Remove non-alphanumeric except hyphens
    normalized = re.sub(r'-+', '-', normalized)  # Collapse multiple hyphens
    return normalized.strip('-')

def get_all_available_subjects() -> List[Dict[str, str]]:
    """
    Get all available subjects from rubric folders.
    Returns list of dicts with 'id' and 'display_name'.
    """
    if not RUBRIC_EVALUATOR_AVAILABLE:
        raise ImportError(
            "Rubric evaluator not available. Please ensure python-docx is installed "
            "and rubric files exist in backend/Rubrics/ directory."
        )

    try:
        from backend.utils.rubric_parser import get_rubric_parser
        parser = get_rubric_parser()
        available = parser.get_available_subjects()

        subjects = []
        for subject_id in available:
            display_name = parser.get_subject_display_name(subject_id)
            subjects.append({
                "id": subject_id,
                "display_name": display_name
            })

        return sorted(subjects, key=lambda x: x["display_name"])
    except Exception as e:
        logger.error(f"Failed to load rubric subjects: {e}")
        raise

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

        # Validate subject using rubric system ONLY
        if not RUBRIC_EVALUATOR_AVAILABLE:
            raise ImportError(
                "Rubric evaluator not available. Please ensure python-docx is installed "
                "and rubric files exist in backend/Rubrics/ directory."
            )

        try:
            from backend.utils.rubric_parser import get_rubric_parser
            parser = get_rubric_parser()
            available_subjects = parser.get_available_subjects()

            # Normalize and check if subject is supported
            normalized_subject = _normalize_subject(subject)
            if normalized_subject not in available_subjects:
                supported = ", ".join(parser.get_subject_display_name(s) for s in available_subjects)
                raise ValueError(f"Unsupported subject '{subject}'. Supported options: {supported}")

            subject_id = normalized_subject
            subject_label = parser.get_subject_display_name(normalized_subject)

        except ImportError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to validate subject: {e}")
            raise ValueError(f"Failed to validate subject '{subject}': {e}")

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

            # Log for debugging
            logger.info(f"OCR extracted {len(page_texts)} pages")
            logger.info(f"Combined answer length: {len(combined_answer)} characters")
            logger.info(f"Question occurrences removed: {question_occurrences_removed}")

            # Validate that we have meaningful content
            if not combined_answer or len(combined_answer) < 50:
                logger.warning(f"Answer too short or empty after question stripping. Length: {len(combined_answer)}")
                # If answer is too short, use the original text (maybe question wasn't in the PDF)
                if not combined_answer:
                    combined_answer = "\n\n".join(text for text in page_texts if text).strip()
                    logger.info(f"Using original text. New length: {len(combined_answer)}")

            answer_word_count = len(re.findall(r"[A-Za-z0-9']+", combined_answer or ""))

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

            if clean_question and combined_answer and len(combined_answer) >= 50:
                qa = QAItem(
                    number=1,
                    question=clean_question,
                    answer=combined_answer,
                    start_page=1,
                    end_page=len(page_texts) or 1,
                )
                # Writing issues analysis (still needed for writing score)
                ans_issues = writing_issues_for_text(
                    self.groq_client,
                    "llama-3.3-70b-versatile",
                    combined_answer,
                )
                raw_w_val, raw_w_label = writing_score_bins_value_and_label(ans_issues)
                writing_value = raw_w_val
                writing_label = raw_w_label

                # Use rubric-based evaluator ONLY
                logger.info(f"Using rubric-based evaluation for {subject}")
                evaluator = RubricEvaluator(
                    groq_client=self.groq_client,
                    subject=subject,
                    model="llama-3.3-70b-versatile"
                )
                rep, label = evaluator.evaluate_answer(qa, writing_value, writing_label)

                # Log evaluation results
                logger.info(f"Evaluation complete: Score {rep.final_score_20}/{rep.score_max}")
                logger.info(f"Issues found: {len(rep.issues)}, Strengths: {len(rep.strengths)}, Improvements: {len(rep.improvements)}")

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

                # Build criteria metadata from report
                criteria_meta = []
                if hasattr(rep, 'criterion_labels') and rep.criterion_labels:
                    for crit in rep.criterion_labels:
                        criteria_meta.append({
                            "label": crit.get("label", "Criterion"),
                            "max_points": crit.get("max", 0),
                        })

                scoring_profile_meta = {
                    "content_max": rep.content_score_max,
                    "writing_max": rep.writing_score_max,
                    "total_max": rep.score_max,
                    "achievable_max": getattr(rep, "final_score_cap", rep.score_max),
                    "criteria": criteria_meta,
                }
            else:
                logger.warning("Evaluation skipped - question or answer insufficient")
                logger.warning(f"Question present: {bool(clean_question)}, Answer length: {len(combined_answer) if combined_answer else 0}")

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

            # For qualitative evaluations, include overall_remark if present
            if qa_reports_with_labels:
                rep, _ = qa_reports_with_labels[0]
                if hasattr(rep, 'overall_remark'):
                    meta["metadata"]["overall_remark"] = rep.overall_remark

            if scoring_profile_meta:
                meta["metadata"]["scoring_profile"] = scoring_profile_meta
            if combined_answer:
                meta["metadata"]["answer_char_count"] = len(combined_answer)
                meta["metadata"]["answer_word_count"] = answer_word_count
            if qa_reports_with_labels:
                first_report = qa_reports_with_labels[0][0]
                meta["metadata"]["answer_word_count"] = getattr(first_report, "answer_word_count", answer_word_count)
                meta["metadata"]["minimum_word_count"] = getattr(first_report, "minimum_word_count", DEFAULT_MIN_WORD_COUNT)
            else:
                meta["metadata"]["minimum_word_count"] = DEFAULT_MIN_WORD_COUNT
            if not qa_reports_with_labels:
                meta["score"]["max_possible_score"] = round(max_possible_score or 20.0, 1)
                if not max_achievable_score:
                    meta["score"]["max_achievable_score"] = meta["score"]["max_possible_score"]

            return annotated_bytes, meta

        finally:
            _delete_file_safely(temp_input)
            _delete_file_safely(temp_output)
