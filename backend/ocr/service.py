from __future__ import annotations
import io, os, tempfile, uuid, time
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

# Repo-root heuristic: ../../.. from this file points to repo, then `ocr`
_ocr_candidates.append(Path(__file__).resolve().parents[2] / "ocr")
_ocr_candidates.append(Path(__file__).resolve().parents[3] / "ocr")

OCR_AVAILABLE = False
OCR_IMPORT_ERROR = None
ocr_script_path: Optional[Path] = None

for cand in _ocr_candidates:
    try:
        if cand and cand.exists():
            sys.path.insert(0, str(cand))
            from ocr import (
                run_ocr_with_retries,
                segment_questions,
                writing_issues_for_page,
                writing_issues_for_text,
                evaluate_qa_detailed,
                writing_score_bins_value_and_label,
                annotate_pdf_with_report,
                QAReportDetailed,
                IssueRow,
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
    segment_questions = None  # type: ignore
    writing_issues_for_page = None  # type: ignore
    writing_issues_for_text = None  # type: ignore
    evaluate_qa_detailed = None  # type: ignore
    writing_score_bins_value_and_label = None  # type: ignore
    annotate_pdf_with_report = None  # type: ignore
    QAReportDetailed = None  # type: ignore
    IssueRow = None  # type: ignore
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

    def annotate_pdf(self, *, pdf_bytes: bytes, original_filename: str) -> Tuple[bytes, Dict[str, Any]]:
        """
        Process PDF with full OCR analysis pipeline from original script.
        Returns annotated PDF bytes and detailed metadata.
        """
        start_time = time.time()
        
        # Save input PDF to temp file
        temp_input = _bytes_to_temp_pdf(pdf_bytes)
        temp_output = temp_input.with_name(f"{temp_input.stem}_annotated.pdf")
        
        try:
            # 1) OCR - Extract text from PDF using Azure Document Intelligence
            page_texts = run_ocr_with_retries(
                temp_input, 
                pages=None,  # Process all pages
                timeout_s=120, 
                max_retries=3
            )
            
            # 2) Q/A segmentation - Find questions and answers
            qas = segment_questions(page_texts)
            
            # 3) Page-wise writing issues for overlay
            page_issues: List[List[IssueRow]] = []
            for page_text in page_texts:
                issues = writing_issues_for_page(
                    self.groq_client, 
                    "llama-3.3-70b-versatile",  # Use the model from original script
                    page_text or ""
                )
                page_issues.append(issues)
            
            # 4) QA evaluation + writing analysis
            qa_reports_with_labels = []
            all_detailed_issues = []
            total_score = 0.0
            max_possible_score = 0.0
            
            for qa in qas:
                # Get writing issues for this answer
                ans_issues = writing_issues_for_text(
                    self.groq_client, 
                    "llama-3.3-70b-versatile", 
                    qa.answer or ""
                )
                
                # Calculate writing score
                w_val, w_label = writing_score_bins_value_and_label(ans_issues)
                
                # Get detailed evaluation
                rep, label = evaluate_qa_detailed(
                    self.groq_client, 
                    "llama-3.3-70b-versatile", 
                    qa, 
                    w_val, 
                    w_label
                )
                
                qa_reports_with_labels.append((rep, label))
                
                # Collect detailed issues for frontend
                for issue in rep.issues:
                    all_detailed_issues.append({
                        "issue_id": f"q{qa.number}_{len(all_detailed_issues)}",
                        "issue_title": f"{issue.get('category', 'Issue')}: {issue.get('problem', '')}",
                        "why_it_matters": issue.get('why_it_matters', ''),
                        "how_to_verify": issue.get('how_to_verify', ''),
                        "evidence_suggestions": issue.get('evidence_suggestions', []),
                        "impact_points_0to3": issue.get('impact_points_0to3', 0),
                        "location_hint": issue.get('location_hint', ''),
                    })
                
                total_score += rep.final_score_20
                max_possible_score += 20.0
            
            # 5) Generate annotated PDF using original script's function
            annotate_pdf_with_report(
                temp_input,
                page_issues,
                qa_reports_with_labels,
                temp_output,
                max_rows_per_page=20,
                panel_width_ratio=0.30,
                height_max_ratio=0.60
            )
            
            # 6) Read annotated PDF
            with open(temp_output, "rb") as f:
                annotated_bytes = f.read()
            
            processing_time = time.time() - start_time
            
            # 7) Build metadata response for frontend
            meta = {
                "issues": all_detailed_issues,
                "score": {
                    "total_score": round(total_score, 1),
                    "max_possible_score": round(max_possible_score, 1)
                },
                "metadata": {
                    "file_name": original_filename,
                    "page_count": len(page_texts),
                    "processing_time_seconds": round(processing_time, 2),
                    "questions_found": len(qas),
                    "fast_mode": self.fast_mode
                }
            }
            
            return annotated_bytes, meta
            
        finally:
            # Cleanup temp files
            _delete_file_safely(temp_input)
            _delete_file_safely(temp_output)
        """
        Returns (annotated_pdf_bytes, metadata_json)
        """
        # 1) OCR via Azure Doc Intelligence (prebuilt-read) -> page_texts
        #    original uses retries & features (OCR_HIGH_RESOLUTION, LANGUAGES, STYLE_FONT)
        tmp_path = _bytes_to_temp_pdf(pdf_bytes)
        try:
            page_texts: List[str] = run_ocr_with_retries(tmp_path, pages=None)
        finally:
            _delete_file_safely(tmp_path)

        # 2) Build a PyMuPDF doc from original bytes
        src = fitz.open(stream=pdf_bytes, filetype="pdf")

        # 3) Right-side panel per page: brief writing issues (or skip in fast mode)
        #    Your original script offers page-wise writing issues; we'll mirror the call and minimal overlay.
        #    (Full complex 4-page "Detailed Issues" per QA is heavy; kept for parity below.)
        page_level_issues: Dict[int, List[IssueRow]] = {}
        if not self.fast_mode:
            for idx, text in enumerate(page_texts, start=1):
                issues = writing_issues_for_page(self.groq_client, model="llama-3.3-70b-versatile", page_text=text)
                page_level_issues[idx] = issues

        # 4) TODO: Strict Q/A segmentation + detailed CSS evaluation pages
        #    Your original script segments QAs and produces 4 inserted report pages per QA with rubric & issues.
        #    For parity, we will call that same logic from your script if it is exposed (else, skip in fast mode).
        #    NOTE: If those helpers are not exported as functions, we can inline minimal text-only panels here.

        # 5) Draw overlays / panels (minimal viable panel to match look-and-feel; right margin card)
        #    This mirrors your style (sidebars + dynamic overlay sizing).
        for pno in range(1, len(src) + 1):
            page = src[pno - 1]
            rect = page.rect
            panel_w = max(180, rect.width * 0.28)
            panel = fitz.Rect(rect.width - panel_w + 8, 16, rect.width - 8, rect.height - 16)
            # panel bg
            page.draw_rect(panel, color=None, fill=(0.97, 0.97, 0.97), overlay=True, width=0)
            # title
            page.insert_textbox(panel, f"Page {pno} — Writing Issues", fontsize=11, fontname="helv", color=(0,0,0), align=0)
            yoff = 24
            issues = page_level_issues.get(pno, [])
            if issues:
                bullets = []
                for it in issues[:6]:
                    bullets.append(f"• [{it.type}] {it.issue} → {it.suggestion}")
                text = "\n".join(bullets)
            else:
                text = "No issues detected (fast mode or low-confidence)."
            inner = fitz.Rect(panel.x0+8, panel.y0+yoff, panel.x1-8, panel.y1-8)
            page.insert_textbox(inner, text, fontsize=9.5, fontname="helv", color=(0,0,0), align=0)

        # (Optional) If you want to add the 4 "Detailed Issues / Evaluation" report pages per QA,
        # we can extend here by calling the same functions your script uses for CSS rubric + outline.

        # 6) Save to bytes
        out = io.BytesIO()
        src.save(out, deflate=True, garbage=4, clean=True)
        src.close()
        annotated = out.getvalue()

        meta = {
            "issues": [],  # Placeholder for now
            "score": {
                "total_score": 0,  # Placeholder for now
                "max_possible_score": 20  # Based on final_score_20 from OCR script
            },
            "metadata": {
                "file_name": original_filename,
                "page_count": len(page_texts),
                "processing_time_seconds": 0.0  # Could add timing if needed
            }
        }
        return annotated, meta
