#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
v6: "Detailed Issues"
- Issues now include: why_it_matters, how_to_verify, evidence_suggestions[], impact_points_0to3, location_hint.
- Issues page renders these fields with clear subheadings and bullets.
- Preserves v5: dynamic overlay sizing, bold red final score, 'Evaluation — Question N' title, nested outline.

Install:
  pip install azure-ai-documentintelligence==1.0.2 python-dotenv==1.0.1 \
              groq==0.13.0 PyMuPDF==1.26.4

.env:
  AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=...
  AZURE_DOCUMENT_INTELLIGENCE_API_KEY=...
  GROQ_API_KEY=...
"""

import argparse, html, json, os, re, sys, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple, Any

from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError, ServiceRequestError
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import DocumentAnalysisFeature
from groq import Groq
import fitz  # PyMuPDF


# --------------------------- Config & Constants --------------------------- #

SUPPORTED_SCHEMA_MODELS = {
    "openai/gpt-oss-20b","openai/gpt-oss-120b",
    "moonshotai/kimi-k2-instruct","moonshotai/kimi-k2-instruct-0905",
    "meta-llama/llama-4-maverick-17b-128e-instruct","meta-llama/llama-4-scout-17b-16e-instruct",
}

ISSUE_TYPES = ["Spelling","Grammar","Punctuation","Sentence Structure"]

DATE_WORDS = {"january","february","march","april","may","june","july","august",
              "september","october","november","december","jan","feb","mar","apr",
              "jun","jul","aug","sep","sept","oct","nov","dec","bc","ad","ce","bce"}
COMMON_ACRONYMS = {"ID","GDP","UN","EU","USA","UK","PM","FIR","NAB","SC","KP","IMF","UAE","USSR"}
DATE_REGEXES = [
    re.compile(r"\b(?:18|19|20|21)\d{2}\b"),
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"),
    re.compile(r"\b\d{1,2}\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*[.,]?\s*\d{2,4}\b", re.I),
    re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s*\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{2,4})?\b", re.I),
    re.compile(r"\b\d{1,2}\s*(?:January|February|March|April|May|June|July|August|September|October|November|December)\s*\d{2,4}\b", re.I),
    re.compile(r"\b\d{4}\s*[\u2013\-–]\s*\d{4}\b"),
]

QUESTION_STRICT = re.compile(
    r"""^\s*
        (?:
          q(?:uestion)?\s*(?:[#]|no\.?|num(?:ber)?\.?)|
          q
        )
        \s*(?:[:.\-])?\s*
        (?P<num>(?:\d{1,3}|[ivxlcdm]{1,6}))\b
        (?:\s*[:).\-]\s*)?
        (?P<title>.*)$
    """, re.I | re.VERBOSE
)
OUTLINE_LINE = re.compile(r"^\s*outline\b", re.I)
LONE_QUESTION = re.compile(r"^\s*question\s*$", re.I)


# ------------------------------ Data Types -------------------------------- #

@dataclass
class QAItem:
    number: int
    question: str
    answer: str
    start_page: int
    end_page: int

@dataclass
class IssueRow:
    type: str
    issue: str
    suggestion: str
    explanation: str

@dataclass
class QAReportDetailed:
    number: int
    question: str
    answer_full: str
    relevance: int
    coverage: int
    accuracy: int
    analysis: int
    organization: int
    content_score_18: float
    writing_score_2_value: float
    final_score_20: float
    strengths: List[str]
    improvements: List[str]
    # Detailed issues (content rubric)
    issues: List[dict]          # keys include: category, span, problem, fix, severity_1to5, why_it_matters, how_to_verify, evidence_suggestions, impact_points_0to3, location_hint
    missing_points: List[str]
    suggested_outline: List[Union[str, dict]]  # dict: {"heading":str, "bullets":[...]}
    question_summary: str
    answer_summary: str
    content_score_max: float = 18.0
    writing_score_max: float = 2.0
    score_max: float = 20.0
    criterion_labels: Optional[List[Dict[str, Any]]] = field(default_factory=list)


# --------------------------- Env & Utilities --------------------------- #

def eprint(*args, **kwargs): print(*args, file=sys.stderr, **kwargs)

def load_env() -> Tuple[str, str, str]:
    load_dotenv()
    endpoint = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
    key = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    if not endpoint or not key:
        raise RuntimeError("Missing AZURE_DOCUMENT_INTELLIGENCE_* in .env")
    if not groq_key:
        raise RuntimeError("Missing GROQ_API_KEY in .env")
    return endpoint, key, groq_key

def ensure_pdf_output_path(input_pdf: Path, requested: Optional[str]) -> Path:
    if requested:
        out_path = Path(requested).expanduser().resolve()
        if out_path.is_dir():
            return out_path / f"{input_pdf.stem}_annotated.pdf"
        if out_path.suffix.lower() != ".pdf":
            out_path = out_path.with_suffix(".pdf")
        return out_path
    return input_pdf.with_name(f"{input_pdf.stem}_annotated.pdf")


# -------------------------------- OCR ---------------------------------- #

def run_ocr_with_retries(pdf_path: Path, pages: Optional[str], timeout_s: int = 120, max_retries: int = 3) -> List[str]:
    """Azure Document Intelligence 'prebuilt-read' (printed + handwritten)."""
    endpoint, key, _ = load_env()
    client = DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(key))
    features = [DocumentAnalysisFeature.OCR_HIGH_RESOLUTION, DocumentAnalysisFeature.LANGUAGES, DocumentAnalysisFeature.STYLE_FONT]

    attempt = 0
    while True:
        try:
            with open(pdf_path, "rb") as f:
                poller = client.begin_analyze_document(model_id="prebuilt-read", body=f, features=features, pages=pages)
                result = poller.result(timeout=timeout_s)
            break
        except (HttpResponseError, ServiceRequestError, TimeoutError) as ex:
            attempt += 1
            if attempt > max_retries: raise
            backoff = 2 ** attempt
            eprint(f"[Azure OCR] transient: {ex}; retrying in {backoff}s ({attempt}/{max_retries})")
            time.sleep(backoff)

    page_texts: List[str] = []
    if getattr(result, "pages", None):
        lines_by_page: Dict[int, List[str]] = {p.page_number: [] for p in result.pages}
        for p in result.pages:
            if getattr(p, "lines", None):
                for ln in p.lines:
                    if ln and ln.content: lines_by_page[p.page_number].append(ln.content)
            elif getattr(result, "paragraphs", None):
                for para in result.paragraphs:
                    if not getattr(para, "bounding_regions", None): continue
                    if any(reg.page_number == p.page_number for reg in para.bounding_regions):
                        lines_by_page[p.page_number].append(para.content)
        for pnum in sorted(lines_by_page.keys()):
            page_texts.append("\n".join(lines_by_page[pnum]).strip())
    else:
        page_texts = [getattr(result, "content", "") or ""]
    return page_texts


# ------------------------- Question Segmentation ----------------------- #

def _looks_like_question(line: str) -> Optional[re.Match]:
    return QUESTION_STRICT.match(line) if line else None

def _join_q_line(prev: str, nxt: str) -> str:
    if prev.rstrip().endswith('-'):
        return prev.rstrip()[:-1] + nxt.lstrip()
    return prev.rstrip() + " " + nxt.lstrip()

def _capture_full_question(lines: List[str], start_i: int) -> (str, int):
    """
    Capture until:
      - first '?' is seen AND (a second '?' occurs OR blank line occurs),
      - OR another question marker,
      - OR line starting with 'Outline',
      - OR max_lines(20).
    """
    q = lines[start_i].rstrip()
    j = start_i + 1
    max_lines = 20
    used = 1
    qm = q.count("?")
    while j < len(lines) and used < max_lines:
        nxt = lines[j].rstrip()
        if _looks_like_question(nxt): break
        if OUTLINE_LINE.match(nxt): break
        q = _join_q_line(q, nxt)
        used += 1
        qm = q.count("?")
        if qm >= 1:
            if qm >= 2:
                j += 1
                break
            if j + 1 < len(lines) and lines[j + 1].strip() == "":
                j += 2
                break
        j += 1
    return q.strip(), j

def segment_questions(page_texts: List[str]) -> List[QAItem]:
    qas: List[QAItem] = []
    current = None
    qnum = 0

    for p_idx, page_text in enumerate(page_texts, start=1):
        lines = page_text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            if LONE_QUESTION.match(line):
                look = i + 1
                for _ in range(3):
                    if look >= len(lines): break
                    if _looks_like_question(lines[look].rstrip()):
                        i = look
                        break
                    look += 1
                else:
                    i += 1
                continue

            m = _looks_like_question(line)
            if m:
                if current:
                    qnum += 1
                    qas.append(QAItem(
                        number=qnum,
                        question=current["qtext"],
                        answer="\n".join(current["ans"]).strip(),
                        start_page=current["start_page"],
                        end_page=p_idx
                    ))
                q_text, next_i = _capture_full_question(lines, i)
                current = {"qtext": q_text, "ans": [], "start_page": p_idx}
                i = next_i
                continue
            else:
                if current:
                    if OUTLINE_LINE.match(line):
                        i += 1
                        continue
                    current["ans"].append(line)
            i += 1

    if current:
        qnum += 1
        qas.append(QAItem(
            number=qnum,
            question=current["qtext"],
            answer="\n".join(current["ans"]).strip(),
            start_page=current["start_page"],
            end_page=len(page_texts)
        ))
    return qas


# ---------------------- Groq helpers (JSON modes) ---------------------- #

GROQ_SYSTEM_WRITING = (
    "You are an expert proofreader for student quizzes. "
    "Categories: Spelling, Grammar, Punctuation, Sentence Structure. "
    "Rules:\n"
    "1) DO NOT flag dates, years, numeric strings, or month names as spelling mistakes.\n"
    "2) DO NOT flag ALL-CAPS acronyms (2–6 letters) as spelling mistakes (e.g., GDP, UN).\n"
    "3) Quote exact fragment in 'issue', and provide a minimal 'suggestion'.\n"
    "Return ONLY JSON."
)

GROQ_SYSTEM_CSS_DETAILED = (
    "You are a senior examiner for Pakistan's CSS-style answers. Be strict and evidence-based.\n"
    "Score with FULL scale and list concrete problems (quote + why + how to fix).\n"
    "Rubric (max 18): Relevance 0–4; Coverage/Depth 0–4; Factual Accuracy 0–4; Analysis/Argumentation 0–4; Organization 0–2.\n"
    "Penalize: missing key points, tangents, weak comparisons, unsupported claims, factual errors, incoherent flow.\n"
    "For 'issues', return 6–12 high-impact items with this detailed shape:\n"
    "{ \"category\":\"Relevance|Coverage|Accuracy|Analysis|Organization|Style\",\n"
    "  \"span\":\"verbatim quote from answer\",\n"
    "  \"problem\":\"what's wrong\",\n"
    "  \"fix\":\"how to fix concretely\",\n"
    "  \"severity_1to5\":int,\n"
    "  \"why_it_matters\":\"brief rationale / exam criterion\",\n"
    "  \"how_to_verify\":\"what to check to confirm\",\n"
    "  \"evidence_suggestions\":[\"source to consult / example / date\"],\n"
    "  \"impact_points_0to3\":int,\n"
    "  \"location_hint\":\"Intro|Body|Conclusion|Transition|Data|Example\" }\n"
    "For 'suggested_outline', return 8–14 objects {heading, bullets[2–4]} with concrete, exam-grade bullets.\n"
    "Return ONLY JSON."
)

DEFAULT_EVAL_CRITERIA = [
    {
        "json_key": "relevance_0to4",
        "attr": "relevance",
        "label": "Relevance",
        "max": 4,
        "detail_source": "question_summary",
    },
    {
        "json_key": "coverage_0to4",
        "attr": "coverage",
        "label": "Coverage & Depth",
        "max": 4,
        "detail_source": "answer_summary",
    },
    {
        "json_key": "accuracy_0to4",
        "attr": "accuracy",
        "label": "Factual Accuracy",
        "max": 4,
        "detail_text": "Evidence quality, dates, facts, attribution.",
    },
    {
        "json_key": "analysis_0to4",
        "attr": "analysis",
        "label": "Analysis & Argumentation",
        "max": 4,
        "detail_text": "Comparisons, causality, critique.",
    },
    {
        "json_key": "organization_0to2",
        "attr": "organization",
        "label": "Organization",
        "max": 2,
        "detail_text": "Intro→Body→Conclusion, transitions.",
    },
]

JSON_SCHEMA_WRITING = {
    "name": "page_issues_schema",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ISSUE_TYPES},
                        "issue": {"type": "string"},
                        "suggestion": {"type": "string"},
                        "explanation": {"type": "string"},
                    },
                    "required": ["type", "issue", "suggestion"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["issues"],
        "additionalProperties": False
    }
}

JSON_SCHEMA_CSS_DETAILED = {
    "name": "qa_css_detailed_schema",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "question_summary": {"type": "string"},
            "answer_summary": {"type": "string"},
            "scores": {
                "type": "object",
                "properties": {
                    "relevance_0to4": {"type": "integer"},
                    "coverage_0to4": {"type": "integer"},
                    "accuracy_0to4": {"type": "integer"},
                    "analysis_0to4": {"type": "integer"},
                    "organization_0to2": {"type": "integer"}
                },
                "required": ["relevance_0to4","coverage_0to4","accuracy_0to4","analysis_0to4","organization_0to2"],
                "additionalProperties": False
            },
            "content_score_18": {"type": "integer"},
            "strengths": {"type": "array", "items": {"type":"string"}},
            "improvements": {"type": "array", "items": {"type":"string"}},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "span": {"type": "string"},
                        "problem": {"type": "string"},
                        "fix": {"type": "string"},
                        "severity_1to5": {"type": "integer"},
                        "why_it_matters": {"type": "string"},
                        "how_to_verify": {"type": "string"},
                        "evidence_suggestions": {"type": "array", "items": {"type": "string"}},
                        "impact_points_0to3": {"type": "integer"},
                        "location_hint": {"type": "string"}
                    },
                    "required": ["category","span","problem","fix","severity_1to5"],
                    "additionalProperties": False
                }
            },
            "missing_points": {"type": "array", "items": {"type":"string"}},
            "suggested_outline": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "bullets": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["heading","bullets"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["scores","content_score_18","issues","suggested_outline"],
        "additionalProperties": False
    }
}

def _parse_json_loose(text: str) -> Optional[dict]:
    try: return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try: return json.loads(m.group(0))
            except Exception: return None
    return None

def groq_call_json(client: Groq, model: str, system: str, user: str,
                   schema: Optional[dict], timeout_s: int = 60, max_retries: int = 3) -> dict:
    """Prefer JSON Schema when supported; else json_object fallback."""
    use_schema = (model in SUPPORTED_SCHEMA_MODELS) and (schema is not None)
    messages_schema = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    messages_object = [{"role": "system", "content": system + "\nReturn JSON ONLY; match the described shape."},
                       {"role": "user", "content": user}]
    attempt = 0
    while True:
        try:
            if use_schema:
                resp = client.chat.completions.create(
                    model=model, messages=messages_schema,
                    response_format={"type": "json_schema", "json_schema": schema},
                    temperature=0, timeout=timeout_s
                )
            else:
                resp = client.chat.completions.create(
                    model=model, messages=messages_object,
                    response_format={"type": "json_object"},
                    temperature=0, timeout=timeout_s
                )
            raw = resp.choices[0].message.content or "{}"
            return _parse_json_loose(raw) or {}
        except Exception as ex:
            attempt += 1
            if attempt > max_retries:
                eprint(f"[Groq] giving up after {max_retries} attempts: {ex}")
                return {}
            backoff = 2 ** attempt
            eprint(f"[Groq] transient / JSON error: {ex}. retry in {backoff}s ({attempt}/{max_retries})")
            time.sleep(backoff)


# -------------------- Writing QA (page & answer texts) ------------------ #

def drop_ignorable_issues(issues: List[dict]) -> List[dict]:
    cleaned = []
    for it in (issues or []):
        frag = str(it.get("issue", "")).strip()
        t = str(it.get("type", "")).strip()
        if not frag or not t: continue
        if t.lower() == "spelling":
            if frag.isupper() and 2 <= len(frag) <= 6 and frag in COMMON_ACRONYMS: continue
            if any(ch.isdigit() for ch in frag): continue
            if frag.lower() in DATE_WORDS: continue
            if any(r.search(frag) for r in DATE_REGEXES): continue
        cleaned.append(it)
    return cleaned

def writing_issues_for_page(groq_client: Groq, model: str, page_text: str) -> List[IssueRow]:
    payload = (
        "Return JSON matching:\n"
        "{ \"issues\": [ { \"type\": \"Spelling|Grammar|Punctuation|Sentence Structure\", "
        "\"issue\": \"fragment from text\", \"suggestion\": \"corrected fragment\", "
        "\"explanation\": \"optional note\" } ] }\n\n"
        f"TEXT:\n{(page_text or '')[:12000]}"
    )
    data = groq_call_json(groq_client, model, GROQ_SYSTEM_WRITING, payload, JSON_SCHEMA_WRITING)
    issues = drop_ignorable_issues(data.get("issues", []))
    return [IssueRow((it.get("type") or "").strip(),
                     (it.get("issue") or "").strip(),
                     (it.get("suggestion") or "").strip(),
                     (it.get("explanation") or "").strip())
            for it in issues if it.get("type") and it.get("issue")]

def writing_issues_for_text(groq_client: Groq, model: str, text: str) -> List[IssueRow]:
    payload = (
        "Return JSON matching:\n"
        "{ \"issues\": [ { \"type\": \"Spelling|Grammar|Punctuation|Sentence Structure\", "
        "\"issue\": \"fragment from text\", \"suggestion\": \"corrected fragment\", "
        "\"explanation\": \"optional note\" } ] }\n\n"
        f"TEXT:\n{(text or '')[:12000]}"
    )
    data = groq_call_json(groq_client, model, GROQ_SYSTEM_WRITING, payload, JSON_SCHEMA_WRITING)
    issues = drop_ignorable_issues(data.get("issues", []))
    return [IssueRow((it.get("type") or "").strip(),
                     (it.get("issue") or "").strip(),
                     (it.get("suggestion") or "").strip(),
                     (it.get("explanation") or "").strip())
            for it in issues if it.get("type") and it.get("issue")]

def writing_score_bins_value_and_label(answer_issues: List[IssueRow]) -> (float, str):
    s = sum(1 for x in answer_issues if x.type.lower()=="spelling")
    g = sum(1 for x in answer_issues if x.type.lower()=="grammar")
    p = sum(1 for x in answer_issues if x.type.lower()=="punctuation")
    t = s + g + p
    if t == 0:  return 2.0, "2.0 /2 (0 mistakes)"
    if 1 <= t <= 10: return 1.5, "1.5 /2 (1–10 mistakes)"
    if 11 <= t <= 20: return 1.0, "1.0 /2 (11–20 mistakes)"
    if 21 <= t <= 25: return 0.5, "0.5 /2 (21–25 mistakes)"
    return 0.0, "0.0 /2 (>25 mistakes)"


# --------------- CSS-style Question→Answer Evaluation ------------------ #

def _css_user_prompt(qa: QAItem, profile: Optional[Dict[str, Any]] = None) -> str:
    if profile:
        criteria = profile.get("criteria", [])
        if criteria:
            score_entries = ", ".join(f"\"{c['json_key']}\":int" for c in criteria)
        else:
            score_entries = "\"relevance_0to4\":int, \"coverage_0to4\":int, \"accuracy_0to4\":int, \"analysis_0to4\":int, \"organization_0to2\":int"
        issue_categories = profile.get(
            "issue_categories",
            "Relevance|Coverage|Accuracy|Analysis|Organization|Style"
        )
        content_field = profile.get("content_field", "content_score_18")
        guidance = profile.get(
            "user_prompt_guidance",
            "Use strict CSS-style expectations. Quote real lines from the Answer."
        )
        outline_hint = profile.get(
            "user_prompt_outline_hint",
            "  \"suggested_outline\": [ {\"heading\":\"...\",\"bullets\":[\"...\",\"...\"]} ]"
        )
        return (
            "Return JSON exactly like:\n"
            "{\n"
            "  \"question_summary\": \"...\",\n"
            "  \"answer_summary\": \"...\",\n"
            f"  \"scores\": {{{score_entries}}},\n"
            f"  \"{content_field}\": int,\n"
            "  \"strengths\": [\"...\"],\n"
            "  \"improvements\": [\"...\"],\n"
            f"  \"issues\": [ {{\"category\":\"{issue_categories}\",\"span\":\"quote\",\"problem\":\"why wrong\",\"fix\":\"how to fix\",\"severity_1to5\":int, \"why_it_matters\":\"...\",\"how_to_verify\":\"...\",\"evidence_suggestions\":[\"...\"],\"impact_points_0to3\":int,\"location_hint\":\"Intro|Body|Conclusion|Transition|Data|Example\" }} ],\n"
            "  \"missing_points\": [\"...\"],\n"
            f"{outline_hint}\n"
            "}\n\n"
            f"{guidance}\n\n"
            f"Question:\n{qa.question[:8000]}\n\nAnswer:\n{qa.answer[:12000]}"
        )
    return (
        "Return JSON exactly like:\n"
        "{\n"
        "  \"question_summary\": \"...\",\n"
        "  \"answer_summary\": \"...\",\n"
        "  \"scores\": {\"relevance_0to4\":int, \"coverage_0to4\":int, \"accuracy_0to4\":int, \"analysis_0to4\":int, \"organization_0to2\":int},\n"
        "  \"content_score_18\": int,\n"
        "  \"strengths\": [\"...\"],\n"
        "  \"improvements\": [\"...\"],\n"
        "  \"issues\": [ {\"category\":\"Relevance|Coverage|Accuracy|Analysis|Organization|Style\",\"span\":\"quote\",\"problem\":\"why wrong\",\"fix\":\"how to fix\",\"severity_1to5\":int, \"why_it_matters\":\"...\",\"how_to_verify\":\"...\",\"evidence_suggestions\":[\"...\"],\"impact_points_0to3\":int,\"location_hint\":\"Intro|Body|Conclusion|Transition|Data|Example\" } ],\n"
        "  \"missing_points\": [\"...\"],\n"
        "  \"suggested_outline\": [ {\"heading\":\"...\",\"bullets\":[\"...\",\"...\"]} ]\n"
        "}\n\n"
        "Use strict CSS-style expectations. Quote real lines from the Answer.\n\n"
        f"Question:\n{qa.question[:8000]}\n\nAnswer:\n{qa.answer[:12000]}"
    )

def evaluate_qa_detailed(
    groq_client: Groq,
    model: str,
    qa: QAItem,
    writing_value: float,
    writing_label: str,
    subject_profile: Optional[Dict[str, Any]] = None,
):
    profile = subject_profile or {}
    criteria = profile.get("criteria", DEFAULT_EVAL_CRITERIA)
    system_prompt = profile.get("system_prompt", GROQ_SYSTEM_CSS_DETAILED)
    schema = profile.get("schema", JSON_SCHEMA_CSS_DETAILED)
    user_prompt = _css_user_prompt(qa, profile if subject_profile else None)

    data = groq_call_json(groq_client, model, system_prompt, user_prompt, schema)

    def _to_int(x, lo, hi):
        try: v = int(x)
        except Exception: v = 0
        return max(lo, min(hi, v))

    question_summary = str(data.get("question_summary", "")).strip()
    answer_summary = str(data.get("answer_summary", "")).strip()

    scores = data.get("scores", {}) or {}
    attr_values: Dict[str, int] = {}
    criterion_info: List[Dict[str, Any]] = []
    base_content = 0
    total_cap = 0
    for crit in criteria:
        json_key = crit.get("json_key")
        attr = crit.get("attr")
        max_points = int(crit.get("max", 4))
        total_cap += max_points
        raw_val = _to_int(scores.get(json_key, 0), 0, max_points)
        attr_values[attr] = raw_val
        base_content += raw_val
        detail = crit.get("detail_text", "")
        detail_source = crit.get("detail_source")
        if detail_source == "question_summary":
            detail = question_summary
        elif detail_source == "answer_summary":
            detail = answer_summary
        criterion_info.append({
            "attr": attr,
            "label": crit.get("label", attr.title() if attr else json_key),
            "value": raw_val,
            "max": max_points,
            "detail": detail,
        })

    rel = int(attr_values.get("relevance", 0))
    cov = int(attr_values.get("coverage", 0))
    acc = int(attr_values.get("accuracy", 0))
    ana = int(attr_values.get("analysis", 0))
    org = int(attr_values.get("organization", 0))

    # Detailed issues
    detailed_issues = []
    for i in (data.get("issues") or []):
        detailed_issues.append({
            "category": str(i.get("category","")).strip(),
            "span": str(i.get("span","")).strip(),
            "problem": str(i.get("problem","")).strip(),
            "fix": str(i.get("fix","")).strip(),
            "severity_1to5": _to_int(i.get("severity_1to5", 3), 1, 5),
            "why_it_matters": str(i.get("why_it_matters","")).strip(),
            "how_to_verify": str(i.get("how_to_verify","")).strip(),
            "evidence_suggestions": [str(x).strip() for x in (i.get("evidence_suggestions") or []) if str(x).strip()],
            "impact_points_0to3": _to_int(i.get("impact_points_0to3", 0), 0, 3),
            "location_hint": str(i.get("location_hint","")).strip(),
        })

    missing_points = [str(x) for x in (data.get("missing_points") or [])][:18]

    # Stricter deductions based on severity + missing points (like v5)
    severe = sum(1 for it in detailed_issues if it["severity_1to5"] >= 4)
    ded_issues = min(3, severe)
    ded_missing = 1 if len(missing_points)>=1 else 0
    ded_missing += 1 if len(missing_points)>=3 else 0
    ded_missing += 1 if len(missing_points)>=5 else 0

    content_cap = float(profile.get("content_cap", total_cap or 18))
    content_target = float(profile.get("content_target", content_cap))
    raw_content = base_content - ded_issues - ded_missing
    content_clamped = max(0.0, min(content_cap, float(raw_content)))
    if content_cap > 0 and content_target != content_cap:
        content = round((content_clamped / content_cap) * content_target, 1)
    else:
        content = round(content_clamped, 1)

    strengths = [str(s) for s in (data.get("strengths") or [])][:10]
    improvements = [str(s) for s in (data.get("improvements") or [])][:10]

    writing_max = float(profile.get("writing_max", 2.0))
    writing_value = max(0.0, min(writing_max, float(writing_value)))
    final_max = float(profile.get("final_max", content_target + writing_max))
    final = round(max(0.0, min(final_max, content + writing_value)), 1)

    # Outline
    raw_outline = data.get("suggested_outline") or []
    outline: List[Union[str, dict]] = []
    for item in raw_outline:
        if isinstance(item, dict) and "heading" in item:
            heading = str(item.get("heading","")).strip()
            bullets = [str(b).strip() for b in (item.get("bullets") or []) if str(b).strip()]
            outline.append({"heading": heading, "bullets": bullets})
        else:
            outline.append(str(item))

    return QAReportDetailed(
        number=qa.number, question=qa.question, answer_full=qa.answer,
        relevance=rel, coverage=cov, accuracy=acc, analysis=ana, organization=org,
        content_score_18=content, writing_score_2_value=writing_value, final_score_20=final,
        strengths=strengths, improvements=improvements,
        issues=detailed_issues, missing_points=missing_points,
        suggested_outline=outline,
        question_summary=question_summary[:800],
        answer_summary=answer_summary[:800],
        content_score_max=content_target,
        writing_score_max=writing_max,
        score_max=final_max,
        criterion_labels=criterion_info,
    ), writing_label


# ----------------------------- Report Pages ---------------------------- #

def html_escape(s: str) -> str:
    return html.escape((s or "").replace("\u00AD",""))

def build_report_html_pages(rep: QAReportDetailed, writing_label: str) -> List[str]:
    # Summary page — bigger red final score
    score_max = getattr(rep, "score_max", 20.0)
    content_max = getattr(rep, "content_score_max", 18.0)
    writing_max = getattr(rep, "writing_score_max", 2.0)

    def _fmt_num(value: float) -> str:
        try:
            num = float(value)
        except Exception:
            return str(value)
        if abs(num - round(num)) < 1e-6:
            return str(int(round(num)))
        return f"{num:.1f}"

    default_criteria = [
        {
            "label": "Relevance",
            "value": rep.relevance,
            "max": 4,
            "detail": rep.question_summary or "",
        },
        {
            "label": "Coverage & Depth",
            "value": rep.coverage,
            "max": 4,
            "detail": rep.answer_summary or "",
        },
        {
            "label": "Factual Accuracy",
            "value": rep.accuracy,
            "max": 4,
            "detail": "Evidence quality, dates, facts, attribution.",
        },
        {
            "label": "Analysis & Argumentation",
            "value": rep.analysis,
            "max": 4,
            "detail": "Comparisons, causality, critique.",
        },
        {
            "label": "Organization",
            "value": rep.organization,
            "max": 2,
            "detail": "Intro→Body→Conclusion, transitions.",
        },
    ]
    criterion_data = rep.criterion_labels or default_criteria
    criterion_items = []
    for crit in criterion_data:
        label = html_escape(str(crit.get("label", "Criterion")))
        value = _fmt_num(crit.get("value", 0))
        max_points = _fmt_num(crit.get("max", 0))
        detail_raw = str(crit.get("detail", "")).strip()
        detail = f" — {html_escape(detail_raw)}" if detail_raw else ""
        criterion_items.append(f"<li><b>{label}:</b> {value}/{max_points}{detail}</li>")

    page_a = f"""
    <div style="font-family: Helvetica, Arial, sans-serif; line-height:1.35;">
      <h1 style="margin:0 0 6pt 0;">Evaluation — Question {rep.number}</h1>
      <div style="margin:2pt 0 8pt 0; color:#333; font-size:12pt;">
        Final Score:
        <span style="font-weight:900; color:#c00000; font-size:22pt;">{rep.final_score_20:.1f}/{_fmt_num(score_max)}</span>
        <span style="font-weight:500; color:#666;">(Content {_fmt_num(rep.content_score_18)}/{_fmt_num(content_max)} + Writing {html_escape(writing_label)})</span>
      </div>

      <h2 style="margin-top:10pt;">Question</h2>
      <blockquote style="margin:6pt 0; border-left:2pt solid #999; padding-left:6pt; color:#222;">
        {html_escape(rep.question)}
      </blockquote>

      <h2 style="margin-top:10pt;">Criterion Breakdown</h2>
      <ul>
        {''.join(criterion_items)}
      </ul>

      {"<h2>Strengths</h2><ul>" + "".join(f"<li>{html_escape(s)}</li>" for s in rep.strengths) + "</ul>" if rep.strengths else ""}
      {"<h2>Improvements</h2><ul>" + "".join(f"<li>{html_escape(s)}</li>" for s in rep.improvements) + "</ul>" if rep.improvements else ""}

      <p style="margin-top:10pt; color:#555;">Scoring: Content /{_fmt_num(content_max)} + Writing /{_fmt_num(writing_max)} → /{_fmt_num(score_max)} total.</p>
    </div>
    """

    # Detailed issues page
    items = []
    for i, it in enumerate(rep.issues, start=1):
        cat = html_escape(it.get('category','Issue'))
        sev = it.get('severity_1to5', 3)
        imp = it.get('impact_points_0to3', 0)
        why = html_escape(it.get('why_it_matters',''))
        verify = html_escape(it.get('how_to_verify',''))
        loc = html_escape(it.get('location_hint',''))
        ev_list = it.get('evidence_suggestions') or []
        ev_html = "".join(f"<li>{html_escape(x)}</li>" for x in ev_list) if ev_list else ""
        items.append(f"""
        <div style="margin-bottom:12pt;">
          <h3 style="margin:0 0 4pt 0;">Issue {i} — {cat}
            <span style="font-weight:500; color:#555;">(Severity {sev}/5; Est. Impact {imp}/3)</span>
          </h3>
          <div style="font-size:9.5pt; color:#000;">
            <div style="color:#444; margin:2pt 0;">Problem:</div>
            <p style="margin:2pt 0;">{html_escape(it.get('problem',''))}</p>
            <div style="color:#444; margin:6pt 0 2pt 0;">Quoted from answer:</div>
            <blockquote style="margin:0; border-left:2pt solid #c33; padding-left:6pt; color:#222;">{html_escape(it.get('span',''))}</blockquote>
            <div style="color:#444; margin:6pt 0 2pt 0;">Fix:</div>
            <p style="margin:2pt 0;">{html_escape(it.get('fix',''))}</p>
            {"<div style='color:#444; margin:6pt 0 2pt 0;'>Why it matters:</div><p style='margin:2pt 0;'>"+why+"</p>" if why else ""}
            {"<div style='color:#444; margin:6pt 0 2pt 0;'>How to verify:</div><p style='margin:2pt 0;'>"+verify+"</p>" if verify else ""}
            {("<div style='color:#444; margin:6pt 0 2pt 0;'>Evidence to consult:</div><ul>"+ev_html+"</ul>") if ev_html else ""}
            {("<div style='color:#444; margin:6pt 0 2pt 0;'>Location hint:</div><p style='margin:2pt 0;'>"+loc+"</p>") if loc else ""}
          </div>
        </div>""")

    page_b = f"""
    <div style="font-family: Helvetica, Arial, sans-serif; line-height:1.35;">
      <h1 style="margin:0 0 8pt 0;">Key Problems & How to Fix Them</h1>
      {''.join(items) if items else '<p>No critical problems detected.</p>'}
    </div>"""

    # Missing + nested outline
    miss_html = "".join(f"<li>{html_escape(x)}</li>" for x in rep.missing_points) if rep.missing_points else "<li>—</li>"
    def outline_block():
        if not rep.suggested_outline: return "<li>—</li>"
        out = []
        for item in rep.suggested_outline:
            if isinstance(item, dict) and "heading" in item:
                head = html_escape(str(item.get("heading","")))
                bullets = [html_escape(b) for b in (item.get("bullets") or []) if str(b).strip()]
                if bullets:
                    out.append(f"<li><b>{head}</b><ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul></li>")
                else:
                    out.append(f"<li><b>{head}</b></li>")
            else:
                out.append(f"<li>{html_escape(str(item))}</li>")
        return "".join(out)
    page_c = f"""
    <div style="font-family: Helvetica, Arial, sans-serif; line-height:1.35;">
      <h1 style="margin:0 0 8pt 0;">How to Score Higher</h1>
      <h2>Missing Key Points</h2>
      <ul>{miss_html}</ul>
      <h2>Suggested High-Scoring Outline</h2>
      <ol>{outline_block()}</ol>
    </div>"""

    # Full answer
    page_d = f"""
    <div style="font-family: Helvetica, Arial, sans-serif; line-height:1.35;">
      <h1 style="margin:0 0 8pt 0;">Full OCR’d Answer (for reference)</h1>
      <div style="white-space:pre-wrap; font-size:10pt; color:#111;">{html_escape(rep.answer_full)}</div>
    </div>"""

    return [page_a, page_b, page_c, page_d]


# ------------------------- Overlay & Save PDF -------------------------- #

def issues_panel_html(page_no: int, rows: List[IssueRow], max_rows: int) -> str:
    if not rows:
        return f"""
        <div style="font-family: Helvetica, Arial, sans-serif;">
          <div style="font-weight:700; font-size:10pt; margin-bottom:4pt;">Page {page_no} — Writing Issues</div>
          <div style="font-size:8.5pt; color:#333;">No issues detected on this page.</div>
        </div>"""
    head = f"""
    <div style="font-family: Helvetica, Arial, sans-serif;">
      <div style="font-weight:800; font-size:10pt; margin-bottom:6pt;">Page {page_no} — Writing Issues</div>
      <ul style="font-size:9pt; padding-left:14pt; margin-top:4pt; line-height:1.35;">"""
    items = [f"<li><b>{html.escape(r.type)}:</b> {html.escape(r.suggestion or r.issue)}</li>" for r in rows[:max_rows]]
    more = f"<div style='font-size:8pt; color:#333; margin-top:4pt;'>… plus {len(rows) - max_rows} more</div>" if len(rows) > max_rows else ""
    return head + "\n".join(items) + more + "</ul></div>"

def insert_html_page(doc: fitz.Document, html_text: str, base_rect: fitz.Rect):
    page = doc.new_page(pno=0, width=base_rect.width, height=base_rect.height)
    margin = 36
    panel = fitz.Rect(margin, margin, base_rect.width - margin, base_rect.height - margin)
    page.insert_htmlbox(panel, html_text, scale_low=0.8, overlay=True)

def _auto_panel_height(rect: fitz.Rect, rows_count: int, base_header_h: float, row_line_h: float,
                       extras: float, height_max_ratio: float) -> float:
    natural_h = base_header_h + rows_count * row_line_h + extras
    cap = rect.height * height_max_ratio
    min_h = 120.0
    return max(min_h, min(natural_h, cap))

def annotate_pdf_with_report(input_pdf: Path,
                             page_issues: List[List[IssueRow]],
                             qa_reports_with_labels: List[tuple],
                             out_pdf: Path,
                             max_rows_per_page: int = 20,
                             panel_width_ratio: float = 0.30,
                             height_max_ratio: float = 0.60,
                             panel_fill_color=(1.0, 1.0, 0.85),  # soft yellow
                             panel_fill_alpha: float = 0.45,
                             panel_stroke_color=(0.20, 0.20, 0.20),
                             panel_stroke_alpha: float = 0.70,
                             shadow_alpha: float = 0.18):
    doc = fitz.open(input_pdf)
    base_rect = doc[0].rect if len(doc) else fitz.Rect(0, 0, 595, 842)

    # Insert report pages first
    report_pages_html: List[str] = []
    for rep, label in qa_reports_with_labels:
        report_pages_html.extend(build_report_html_pages(rep, label))
    for html_text in reversed(report_pages_html):
        insert_html_page(doc, html_text, base_rect)

    # Overlay per original page (dynamic height)
    shift = len(report_pages_html)
    for i in range(shift, len(doc)):
        page = doc[i]
        rows = page_issues[i - shift] if (i - shift) < len(page_issues) else []
        panel_html = issues_panel_html(i - shift + 1, rows, max_rows=max_rows_per_page)

        margin = 18
        rect = page.rect
        panel_w = max(120, rect.width * max(0.15, min(0.5, panel_width_ratio)))

        shown = min(len(rows), max_rows_per_page)
        base_header_h = 28.0
        row_line_h = 16.0
        extras = 18.0
        panel_h = _auto_panel_height(rect, shown, base_header_h, row_line_h, extras, height_max_ratio)

        x1 = rect.x1 - margin
        x0 = x1 - panel_w
        y0 = margin
        y1 = y0 + panel_h
        box = fitz.Rect(x0, y0, x1, y1)

        # Shadow
        if shadow_alpha > 0:
            shadow_box = fitz.Rect(x0+2, y0+2, x1+2, y1+2)
            shape_shadow = page.new_shape()
            shape_shadow.draw_rect(shadow_box, radius=0.04)
            shape_shadow.finish(width=0, color=(0,0,0), fill=(0,0,0),
                                stroke_opacity=0.0, fill_opacity=max(0.0, min(1.0, shadow_alpha)))
            shape_shadow.commit()

        # Panel
        shape = page.new_shape()
        shape.draw_rect(box, radius=0.04)
        shape.finish(
            width=1.0, color=panel_stroke_color, fill=panel_fill_color,
            stroke_opacity=max(0.0, min(1.0, panel_stroke_alpha)),
            fill_opacity=max(0.0, min(1.0, panel_fill_alpha)),
        )
        shape.commit()

        # HTML
        page.insert_htmlbox(box, panel_html, scale_low=0.80, overlay=True)

    doc.save(str(out_pdf), deflate=True)
    doc.close()


# --------------------------------- Main -------------------------------- #

def main():
    ap = argparse.ArgumentParser(description="OCR + strict content eval + detailed issues + dynamic overlay + nested outline.")
    ap.add_argument("pdf", help="Input PDF path")
    ap.add_argument("-o","--output", help="Output annotated PDF file or directory (default: <stem>_annotated.pdf)")
    ap.add_argument("--pages", default=None, help='Optional page ranges, e.g., "1-3,5"')
    ap.add_argument("--model", default="llama-3.3-70b-versatile", help="Groq model ID")
    ap.add_argument("--timeout", type=int, default=120, help="OCR request timeout (seconds)")
    ap.add_argument("--max-rows", type=int, default=20, help="Max rows in page overlay")
    # overlay tuning
    ap.add_argument("--panel-width", type=float, default=0.30, help="Overlay width ratio (0.15–0.50)")
    ap.add_argument("--height-max", type=float, default=0.60, help="Max overlay height ratio (0.30–0.80)")
    ap.add_argument("--panel-fill-alpha", type=float, default=0.45, help="Panel fill opacity 0..1")
    ap.add_argument("--panel-stroke-alpha", type=float, default=0.70, help="Panel border opacity 0..1")
    ap.add_argument("--shadow-alpha", type=float, default=0.18, help="Drop shadow opacity 0..1")
    args = ap.parse_args()

    in_pdf = Path(args.pdf).expanduser().resolve()
    if not in_pdf.exists(): raise FileNotFoundError(in_pdf)
    out_pdf = ensure_pdf_output_path(in_pdf, args.output)

    # 1) OCR
    page_texts = run_ocr_with_retries(in_pdf, pages=args.pages, timeout_s=args.timeout)

    # 2) Q/A segmentation
    qas = segment_questions(page_texts)
    if not qas:
        eprint("[warn] No strict Question markers found. Report will be empty; overlays still rendered.")

    # 3) Groq
    _, _, groq_key = load_env()
    groq_client = Groq(api_key=groq_key)

    # 4) Page-wise writing issues (overlay)
    page_issues: List[List[IssueRow]] = [writing_issues_for_page(groq_client, args.model, t or "") for t in page_texts]

    # 5) QA evaluation + writing bins
    qa_reports_with_labels = []
    for qa in qas:
        ans_issues = writing_issues_for_text(groq_client, args.model, qa.answer or "")
        w_val, w_label = writing_score_bins_value_and_label(ans_issues)
        rep, label = evaluate_qa_detailed(groq_client, args.model, qa, w_val, w_label)
        qa_reports_with_labels.append((rep, label))

    # 6) Render
    annotate_pdf_with_report(
        in_pdf, page_issues, qa_reports_with_labels, out_pdf,
        max_rows_per_page=args.max_rows,
        panel_width_ratio=args.panel_width,
        height_max_ratio=args.height_max,
        panel_fill_alpha=args.panel_fill_alpha,
        panel_stroke_alpha=args.panel_stroke_alpha,
        shadow_alpha=args.shadow_alpha,
    )
    print(f"✓ Annotated PDF with detailed report written: {out_pdf}")


if __name__ == "__main__":
    main()
