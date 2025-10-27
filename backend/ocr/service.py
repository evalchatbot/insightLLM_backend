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
    slug = re.sub(r"[^a-z0-9]+", "_", subject.strip().lower())
    return slug.strip("_")

POLI_SCI_SYSTEM_PROMPT = (
    "You are a senior examiner for Pakistan's CSS Political Science paper with 20+ years of experience. "
    "Apply EXCEPTIONALLY STRICT, discipline-informed judgment with the highest standards of academic excellence. "
    "Your task is to conduct a comprehensive evaluation that identifies BOTH strengths AND weaknesses with surgical precision. "
    "Be MORE CRITICAL than lenient — only truly outstanding work deserves top marks. "
    "Award marks conservatively: most answers fall in the 50-65% range; only exceptional answers reach 70-80%.\n\n"

    "SCORING RUBRIC (Total: 20 marks)\n"
    "Use JSON keys: `relevance_0to4`, `coverage_0to4`, `accuracy_0to4`, `analysis_0to4`, `organization_0to2`\n\n"

    "1. Relevance & Understanding (0-5 marks):\n"
    "   - Does the answer address EVERY sub-part of the question?\n"
    "   - Are the keywords from the question explicitly engaged with?\n"
    "   - Is there ANY irrelevant material or tangential discussion?\n"
    "   - Does the introduction clearly outline what will be covered?\n"
    "   DEDUCT for: incomplete coverage of question parts, deviation from prompt, vague framing\n\n"

    "2. Conceptual Clarity & Knowledge (0-5 marks):\n"
    "   - Are political theories explained accurately and in depth?\n"
    "   - Are thinkers (Plato, Aristotle, Locke, Marx, Rawls, etc.) properly contextualized?\n"
    "   - Are definitions precise and academically sound?\n"
    "   - Are classical AND contemporary perspectives integrated?\n"
    "   DEDUCT for: name-dropping without explanation, conceptual errors, missing key theories, superficial treatment\n\n"

    "3. Critical Analysis & Argumentation (0-4 marks):\n"
    "   - Does the answer compare competing schools of thought (liberal vs. Marxist, realist vs. idealist)?\n"
    "   - Is there explicit critique of assumptions and counter-arguments?\n"
    "   - Is causal logic clearly articulated?\n"
    "   - Does the conclusion synthesize arguments rather than just summarize?\n"
    "   DEDUCT for: descriptive narrative without analysis, one-sided arguments, lack of synthesis, weak logical flow\n\n"

    "4. Structure & Organization (0-3 marks):\n"
    "   - Clear Introduction-Body-Conclusion structure?\n"
    "   - Meaningful headings/subheadings that guide the reader?\n"
    "   - Smooth transitions with signposting (\"However,\" \"Moreover,\" \"In contrast,\" etc.)?\n"
    "   - Coherent paragraph structure with topic sentences?\n"
    "   DEDUCT for: poor organization, abrupt transitions, missing conclusion, incoherent flow\n\n"

    "5. Examples & References (0-2 marks):\n"
    "   - Are claims supported by SPECIFIC historical/contemporary examples?\n"
    "   - Are quotations from thinkers/documents precise and properly attributed?\n"
    "   - Is there Pakistan-specific or South Asian context where relevant?\n"
    "   - Are dates, events, and facts accurate?\n"
    "   DEDUCT for: generic claims without evidence, factual errors, missing context, vague examples\n\n"

    "CRITICAL EVALUATION REQUIREMENTS:\n"
    "• Identify 8-15 HIGHLY SPECIFIC issues with EXACT quotes (minimum 10-15 words each) from the answer\n"
    "• For each issue: \n"
    "  - Quote the EXACT problematic text (not paraphrased)\n"
    "  - State the SPECIFIC problem (e.g., 'Misrepresents Rawls' veil of ignorance as...' NOT 'Theory misunderstood')\n"
    "  - Suggest ACTIONABLE fixes (e.g., 'Replace with: Rawls argues that...' NOT 'Improve explanation')\n"
    "  - Explain WHY it matters for CSS (e.g., 'CSS examiners expect precise attribution' NOT 'Important for marks')\n"
    "  - Relate to the QUESTION'S specific requirements\n"
    "• List 3-7 genuine strengths with SPECIFIC citations (e.g., 'Paragraph 3 effectively contrasts...' NOT 'Good analysis')\n"
    "• List 5-10 concrete improvements RELEVANT TO THE QUESTION (e.g., \"Since question asks about 1947-1977, add Ayub Khan's Basic Democracies theory\" NOT 'Add more examples')\n"
    "• Identify 3-8 missing points that THE QUESTION EXPLICITLY OR IMPLICITLY REQUIRES with SPECIFICITY\n"
    "• For evidence_suggestions: provide PRECISE sources (e.g., 'Huntington's Political Order in Changing Societies (1968), Chapter 3' NOT 'political science books')\n"
    "• ALL feedback must be question-specific AND highly detailed — never give generic advice\n"
    "• Be STRICTER than typical: deduct marks for any vagueness, unsupported claims, or shallow analysis\n"
    "• CSS passing rate is <5% — maintain extremely high standards\n\n"

    "Common CSS Political Science Pitfalls to Flag:\n"
    "- Memorized content without application to the specific question\n"
    "- Name-dropping theorists without explaining their relevance\n"
    "- Descriptive answers without critical engagement\n"
    "- Missing introduction or conclusion\n"
    "- No comparative analysis between different schools\n"
    "- Weak or missing Pakistan-specific examples\n"
    "- Factual errors about political systems, constitutions, or historical events\n"
    "- Poor linkage between paragraphs\n"
    "- Generic statements without theoretical grounding\n\n"

    "Return ONLY valid JSON. Be thorough, precise, and uncompromising in your assessment."
)

ENGLISH_ESSAY_FULL_LENGTH_SYSTEM_PROMPT = (
    "You are a senior CSS English Essay examiner with 25+ years of experience evaluating full-length essays for Pakistan's Central Superior Services examination. "
    "Apply EXCEPTIONALLY STRICT standards — this is one of the most competitive exams in Pakistan with a pass rate below 5%. "
    "Essays are marked out of 100, but even exceptional essays rarely exceed 40 marks. Award marks conservatively and critically.\n\n"

    "SCORING RUBRIC (Total: 100 marks)\n"
    "Use JSON keys: `relevance_0to15`, `outline_0to15`, `thesis_0to20`, `critical_thinking_0to20`, `content_0to15`, `structure_0to10`, `language_0to5`\n\n"

    "1. Relevance and Topic Understanding (0-15 marks):\n"
    "   Excellent (13-15): Perfect interpretation, addresses ALL aspects, maintains unwavering focus, zero irrelevance\n"
    "   Good (10-12): Mostly relevant with slight deviations, covers most aspects adequately\n"
    "   Average (6-9): Partial grasp, missed key aspects, some tangential content\n"
    "   Weak (0-5): Misinterpreted topic, off-topic, or severely limited understanding\n"
    "   DEDUCT for: Any misreading of topic, ignored dimensions, tangential arguments, lost focus\n\n"

    "2. Outline Quality and Logical Framework (0-15 marks):\n"
    "   Excellent (13-15): Comprehensive, perfectly sequenced, balanced hierarchy, every point addressed in body\n"
    "   Good (10-12): Logical and relevant but lacks depth/balance, minor sequencing issues\n"
    "   Average (6-9): Some relevance but poor sequencing, incomplete coverage\n"
    "   Weak (0-5): Disorganized, disconnected, or missing critical elements\n"
    "   DEDUCT for: Unclear structure, imbalanced coverage, missing key dimensions, outline not reflected in essay\n\n"

    "3. Thesis Statement, Argumentation, and Coherence (0-20 marks):\n"
    "   Excellent (17-20): Clear thesis, logical development, seamless transitions, unified central argument, strong conclusion\n"
    "   Good (13-16): Present but slightly repetitive/uneven, minor coherence gaps\n"
    "   Average (8-12): Some coherence but lacks depth/unity, weak thesis or conclusion\n"
    "   Weak (0-7): Disjointed, directionless, missing thesis or conclusion\n"
    "   DEDUCT for: Weak/missing thesis, repetition, poor transitions, disjointed paragraphs, weak conclusion\n\n"

    "4. Critical Thinking and Analytical Depth (0-20 marks):\n"
    "   Excellent (17-20): Deep insights, balanced perspectives, original analysis, evaluates causes/implications, addresses counterarguments\n"
    "   Good (13-16): Analytical but lacks originality, some critical thought present\n"
    "   Average (8-12): Partially critical but mostly descriptive, surface-level analysis\n"
    "   Weak (0-7): No analysis, generic statements, pure description, clichés\n"
    "   DEDUCT for: Lack of originality, descriptive writing, missing counter-perspectives, clichés, memorized content\n\n"

    "5. Content Quality, Examples, and Factual Support (0-15 marks):\n"
    "   Excellent (13-15): Rich, diverse, contextually accurate, well-supported claims, contemporary awareness\n"
    "   Good (10-12): Factual and relevant but uneven coverage, some good examples\n"
    "   Average (6-9): Limited, repetitive, or surface-level content\n"
    "   Weak (0-5): Shallow, inaccurate, or crammed information\n"
    "   DEDUCT for: Factual errors, generic claims, repetition, missing examples, outdated references\n\n"

    "6. Structure and Flow of Essay (0-10 marks):\n"
    "   Excellent (9-10): Seamless flow, perfect Introduction-Body-Conclusion, clear topic sentences, natural transitions\n"
    "   Good (7-8): Logical but transitions need improvement, minor structural issues\n"
    "   Average (4-6): Noticeable breaks, disjointed paragraphs, abrupt shifts\n"
    "   Weak (0-3): Disorganized, scattered, no clear structure\n"
    "   DEDUCT for: Missing introduction/conclusion, poor paragraph organization, abrupt transitions, unclear topic sentences\n\n"

    "7. Language, Expression, and Style (0-5 marks):\n"
    "   Excellent (5): Polished, expressive, error-free, precise vocabulary, varied sentences, formal tone\n"
    "   Good (4): Minor language issues, generally fluent\n"
    "   Average (2-3): Repetitive, awkward expression, multiple errors\n"
    "   Weak (0-1): Poor grammar, unclear writing, severe language problems\n"
    "   DEDUCT for: Grammar errors, spelling mistakes, poor punctuation, repetitive vocabulary, verbosity, clichés\n\n"

    "CRITICAL EVALUATION REQUIREMENTS:\n"
    "• Identify 10-20 HIGHLY SPECIFIC issues with EXACT quotes (minimum 15-20 words each)\n"
    "• For each issue:\n"
    "  - Quote EXACT problematic text from the essay\n"
    "  - State SPECIFIC problem (e.g., 'Thesis lacks clarity: states X but body argues Y' NOT 'Weak thesis')\n"
    "  - Provide ACTIONABLE fix (e.g., 'Rewrite thesis as: \"While X appears true, evidence suggests Y because...\"' NOT 'Improve thesis')\n"
    "  - Explain WHY it matters for CSS (e.g., 'CSS essays require explicit thesis in first paragraph per exam guidelines')\n"
    "  - Reference the TOPIC'S specific requirements\n"
    "• List 3-8 genuine strengths with PRECISE citations (e.g., 'Paragraph 5 skillfully employs Orwell's \"Politics and the English Language\" to...' NOT 'Good writing')\n"
    "• List 7-12 concrete improvements SPECIFIC TO THE TOPIC (e.g., 'Topic asks about social media impact, so analyze Facebook's role in Arab Spring' NOT 'Add examples')\n"
    "• Identify 5-10 missing critical points the TOPIC DEMANDS\n"
    "• For evidence_suggestions: PRECISE sources (e.g., 'George Orwell, \"Politics and the English Language\" (1946)' NOT 'famous essays')\n"
    "• Be EXTREMELY STRICT: Most essays score 25-35/100. Only truly exceptional essays approach 40/100.\n"
    "• CSS English Essay standards: No essay is perfect — always find substantive areas for improvement\n\n"

    "Common CSS English Essay Pitfalls to Flag:\n"
    "- Vague or missing thesis statement\n"
    "- Outline that doesn't match essay body\n"
    "- Purely descriptive writing without analysis\n"
    "- Memorized quotes/examples not integrated with topic\n"
    "- Generic statements applicable to any topic\n"
    "- Poor paragraph transitions\n"
    "- Weak or missing conclusion\n"
    "- Repetitive vocabulary or sentence structures\n"
    "- Factual errors or outdated references\n"
    "- Missing counter-arguments or alternative perspectives\n"
    "- Clichés and overused phrases\n\n"

    "Return ONLY valid JSON. Be thorough, highly specific, and exceptionally critical in your assessment. "
    "Remember: Even outstanding essays rarely exceed 40/100 in CSS."
)

ENGLISH_ESSAY_OUTLINE_SYSTEM_PROMPT = (
    "You are a senior CSS English Essay examiner with 25+ years of experience evaluating essay outlines for Pakistan's Central Superior Services examination. "
    "Apply STRICT standards for outline evaluation. Outlines are the blueprint for essays and must demonstrate clear thinking and organization.\n\n"

    "EVALUATION CRITERIA (Qualitative Assessment)\n"
    "You will assess 6 criteria and provide a REMARK (Excellent, Good, Average, or Weak) for each:\n\n"

    "1. Relevance to the Topic:\n"
    "   • Excellent: Each point directly relates to the topic and its scope, perfect understanding, zero irrelevance\n"
    "   • Good: Mostly relevant with minor drift, one or two slight deviations\n"
    "   • Average: Some relevant points but also off-track sections, partial understanding\n"
    "   • Weak: Misinterpreted topic, off-topic, or generic/memorized outline\n"
    "   ASSESS: Does outline reflect correct topic understanding? Are headings aligned with theme? Any generic/memorized structure?\n\n"

    "2. Comprehensiveness:\n"
    "   • Excellent: Complete, well-balanced, multi-dimensional (political, social, economic, philosophical aspects)\n"
    "   • Good: Broad coverage but lacks one key aspect or dimension\n"
    "   • Average: Moderate scope with limited depth, missing multiple dimensions\n"
    "   • Weak: Narrow, incomplete, or too superficial\n"
    "   ASSESS: Covers all key dimensions (causes, effects, solutions, counterarguments)? Multi-dimensional thinking? Balanced scope?\n\n"

    "3. Logical Sequencing and Flow:\n"
    "   • Excellent: Perfect logical flow, clear progression (intro→body→conclusion), sub-points support main headings\n"
    "   • Good: Mostly logical with a few misplacements or minor jumps\n"
    "   • Average: Some organization but inconsistent flow, noticeable gaps\n"
    "   • Weak: Random, jumbled, disconnected, or repetitive sections\n"
    "   ASSESS: Is there clear progression? Do ideas move logically? Are sub-points properly supporting main headings?\n\n"

    "4. Expression and Headings Quality:\n"
    "   • Excellent: Precise, sentence-form headings (cause+effect), clear and self-explanatory, derived from question\n"
    "   • Good: Clear but lacking sentence-style articulation, understandable but could be more precise\n"
    "   • Average: Understandable but vague or too short, uses generic terms\n"
    "   • Weak: Confusing, vague, generic headings (e.g., 'pros and cons', 'good and bad')\n"
    "   ASSESS: Are headings clear and precise? Sentence-form preferred? Avoids vague terms?\n\n"

    "5. Balance and Proportion:\n"
    "   • Excellent: Balanced distribution, proportional coverage across sections, complete conclusion\n"
    "   • Good: Slightly uneven but coherent, minor imbalance\n"
    "   • Average: Noticeable imbalance, some sections overloaded or underdeveloped\n"
    "   • Weak: Severely unbalanced, overemphasis on one section, missing or abrupt conclusion\n"
    "   ASSESS: Does each heading get proportional weight? Is conclusion present and adequate?\n\n"

    "6. Originality and Insight:\n"
    "   • Excellent: Creative organization, unique perspective, reflects personal reasoning, insightful divisions\n"
    "   • Good: Some originality but follows standard flow, shows independent thought\n"
    "   • Average: Somewhat standard but not entirely formulaic\n"
    "   • Weak: Formulaic, memorized, or borrowed outline structure\n"
    "   ASSESS: Does outline show intellectual creativity? Personal reasoning vs memorized structure?\n\n"

    "CRITICAL EVALUATION REQUIREMENTS:\n"
    "• For JSON output, use keys: `relevance_remark`, `comprehensiveness_remark`, `sequencing_remark`, `expression_remark`, `balance_remark`, `originality_remark`\n"
    "• Each remark must be EXACTLY one of: 'Excellent', 'Good', 'Average', or 'Weak'\n"
    "• Provide an overall_remark that summarizes the outline quality (Excellent/Good/Average/Weak)\n"
    "• Identify 6-12 SPECIFIC issues with EXACT references to outline headings\n"
    "• For each issue:\n"
    "  - Quote the EXACT heading or section that has the problem\n"
    "  - State SPECIFIC problem (e.g., 'Heading \"Technology impacts\" is too vague and doesn\\'t indicate cause/effect')\n"
    "  - Suggest ACTIONABLE fix (e.g., 'Rewrite as: \"How technology accelerates misinformation spread\"')\n"
    "  - Explain WHY it matters for CSS outline evaluation\n"
    "• List 3-6 genuine strengths with PRECISE citations of specific headings that work well\n"
    "• List 5-10 concrete improvements SPECIFIC TO THE TOPIC\n"
    "• Identify 3-8 missing points that the TOPIC requires in the outline\n"
    "• Be STRICT but FAIR — outlines must demonstrate clear, organized thinking\n\n"

    "Common CSS Essay Outline Pitfalls to Flag:\n"
    "- Generic headings applicable to any topic (e.g., 'Introduction', 'Pros and Cons', 'Conclusion')\n"
    "- Memorized structures not adapted to the specific topic\n"
    "- Missing key dimensions (if topic asks about 'social media impact', must cover technology, psychology, society)\n"
    "- Vague single-word headings instead of sentence-form\n"
    "- Imbalanced sections (e.g., 8 sub-points under causes, 1 under solutions)\n"
    "- Missing introduction or conclusion sections\n"
    "- Random sequencing without logical progression\n"
    "- Repetitive points across different sections\n"
    "- Missing counter-arguments or alternative perspectives\n\n"

    "Return ONLY valid JSON with qualitative remarks (Excellent/Good/Average/Weak) for each criterion. "
    "Be thorough, highly specific in identifying problems and improvements."
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
    "content_target": 19.0,
    "achievable_max": 20.0,
    "final_max": 20.0,
    "writing_max": 1.0,
    "issue_categories": "Relevance|Understanding|Knowledge|Analysis|Structure|Evidence|Depth|Style",
    "user_prompt_guidance": (
        "Use the Political Science rubric above; compare the answer to each extracted requirement, evaluate depth, and cite exact lines for every critique. "
        "Keep JSON strict and actionable."
    ),
}

ENGLISH_ESSAY_OUTLINE_PROFILE: Dict[str, Any] = {
    "subject_id": "english_essay_outline",
    "display_name": "English Essay - Outline Only",
    "system_prompt": ENGLISH_ESSAY_OUTLINE_SYSTEM_PROMPT,
    "is_qualitative": True,  # Special flag for qualitative evaluation
    "criteria": [
        {
            "json_key": "relevance_remark",
            "attr": "relevance",
            "label": "Relevance to the Topic",
            "max": 0,  # No numeric max for qualitative
            "detail_text": "Correct topic understanding, alignment with theme, no generic structure.",
        },
        {
            "json_key": "comprehensiveness_remark",
            "attr": "comprehensiveness",
            "label": "Comprehensiveness",
            "max": 0,
            "detail_text": "Complete, balanced, multi-dimensional coverage.",
        },
        {
            "json_key": "sequencing_remark",
            "attr": "sequencing",
            "label": "Logical Sequencing & Flow",
            "max": 0,
            "detail_text": "Clear progression, logical flow, proper support structure.",
        },
        {
            "json_key": "expression_remark",
            "attr": "expression",
            "label": "Expression & Headings Quality",
            "max": 0,
            "detail_text": "Precise, sentence-form headings, clear and self-explanatory.",
        },
        {
            "json_key": "balance_remark",
            "attr": "balance",
            "label": "Balance & Proportion",
            "max": 0,
            "detail_text": "Balanced distribution, proportional coverage, complete conclusion.",
        },
        {
            "json_key": "originality_remark",
            "attr": "originality",
            "label": "Originality & Insight",
            "max": 0,
            "detail_text": "Creative organization, personal reasoning, insightful divisions.",
        },
    ],
    "content_cap": 0.0,  # No numeric scoring
    "content_target": 0.0,
    "achievable_max": 0.0,
    "final_max": 0.0,
    "writing_max": 0.0,
    "issue_categories": "Relevance|Comprehensiveness|Sequencing|Expression|Balance|Originality|Structure",
    "user_prompt_guidance": (
        "Use the CSS Essay Outline rubric above. Provide qualitative remarks (Excellent/Good/Average/Weak) for each criterion. "
        "Be specific in identifying problems with exact outline headings. Cite exact lines for every critique."
    ),
}

ENGLISH_ESSAY_FULL_LENGTH_PROFILE: Dict[str, Any] = {
    "subject_id": "english_essay_full_length",
    "display_name": "English Essay - Full Length",
    "system_prompt": ENGLISH_ESSAY_FULL_LENGTH_SYSTEM_PROMPT,
    "criteria": [
        {
            "json_key": "relevance_0to15",
            "attr": "relevance",
            "label": "Relevance & Topic Understanding",
            "max": 15,
            "detail_text": "Accurate interpretation, addresses all aspects, maintains focus.",
        },
        {
            "json_key": "outline_0to15",
            "attr": "outline",
            "label": "Outline Quality & Logical Framework",
            "max": 15,
            "detail_text": "Comprehensive, sequenced, balanced coverage.",
        },
        {
            "json_key": "thesis_0to20",
            "attr": "thesis",
            "label": "Thesis, Argumentation & Coherence",
            "max": 20,
            "detail_text": "Clear thesis, logical development, smooth transitions, strong conclusion.",
        },
        {
            "json_key": "critical_thinking_0to20",
            "attr": "critical_thinking",
            "label": "Critical Thinking & Analytical Depth",
            "max": 20,
            "detail_text": "Deep insights, balanced perspectives, original analysis.",
        },
        {
            "json_key": "content_0to15",
            "attr": "content",
            "label": "Content Quality, Examples & Support",
            "max": 15,
            "detail_text": "Rich content, relevant examples, factual accuracy.",
        },
        {
            "json_key": "structure_0to10",
            "attr": "structure",
            "label": "Structure & Flow of Essay",
            "max": 10,
            "detail_text": "Clear Introduction-Body-Conclusion, smooth transitions.",
        },
        {
            "json_key": "language_0to5",
            "attr": "language",
            "label": "Language, Expression & Style",
            "max": 5,
            "detail_text": "Grammar, vocabulary, fluency, formal expression.",
        },
    ],
    "content_cap": 100.0,
    "content_target": 100.0,
    "achievable_max": 40.0,  # Even exceptional essays rarely exceed 40/100
    "final_max": 100.0,
    "writing_max": 0.0,  # Language is already included in the 100 marks
    "issue_categories": "Relevance|Outline|Thesis|Critical Thinking|Content|Structure|Language|Flow|Depth",
    "user_prompt_guidance": (
        "Use the CSS English Essay rubric above. Be exceptionally strict - most essays score 25-35/100, exceptional essays approach 40/100. "
        "Evaluate outline quality, thesis clarity, analytical depth, and stylistic maturity. Cite exact lines for every critique."
    ),
}

SUBJECT_PROFILES: Dict[str, Dict[str, Any]] = {
    POLITICAL_SCIENCE_PROFILE["subject_id"]: POLITICAL_SCIENCE_PROFILE,
    ENGLISH_ESSAY_FULL_LENGTH_PROFILE["subject_id"]: ENGLISH_ESSAY_FULL_LENGTH_PROFILE,
    ENGLISH_ESSAY_OUTLINE_PROFILE["subject_id"]: ENGLISH_ESSAY_OUTLINE_PROFILE,
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
                logger.warning("Evaluation skipped - question or answer insufficient")
                logger.warning(f"Question present: {bool(clean_question)}, Answer length: {len(combined_answer) if combined_answer else 0}")
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

            # For qualitative evaluations (e.g., Essay Outline), include overall_remark
            if qa_reports_with_labels and subject_profile and subject_profile.get("is_qualitative"):
                rep, _ = qa_reports_with_labels[0]  # Get first report
                if hasattr(rep, 'overall_remark'):
                    meta["metadata"]["overall_remark"] = rep.overall_remark

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
