"""
Fact Book digest generator.

Takes a set of already-summarized editorials and asks Grok to produce a compact,
exam-focused digest: merged storylines rewritten into short cards (2 fused bullets
+ a takeaway) plus a "Key Figures" table of citable statistics.

The model returns STRUCTURED JSON only (never HTML) so the frontends can render
the shared HTML template deterministically in their own brand colour.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from backend.config import FACTBOOK_GROK_MODEL, GROK_API
from backend.utils.grok_client import GrokClient, GrokMessage, extract_content_text
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

DIGEST_SYSTEM_PROMPT = (
    "You are a content processor for Lahore CSS Academy's Fact Book. Given a set of "
    "already-summarized newspaper editorials for a date range, produce a single compact "
    "digest that lets a CSS/PMS aspirant understand every story's full meaning in under "
    "15 seconds per entry.\n\n"
    "Return STRICT JSON ONLY (no HTML, no markdown, no commentary) with this exact shape:\n"
    "{\n"
    '  "digest_title": string,   // a short title for the whole digest (<= 6 words)\n'
    '  "source_name": string,    // e.g. "Dawn Editorials"\n'
    '  "topic": string,          // overall theme in 1-3 words, or "Current Affairs"\n'
    '  "cards": [\n'
    "    {\n"
    '      "headline": string,          // rephrased, sentence case, < 8 words, names subject + core outcome/tension\n'
    '      "bullets": [string, string], // EXACTLY 2 complete sentences, 20-35 words each\n'
    '      "takeaway_label": string,    // exactly "Recommendation:" or "Takeaway:"\n'
    '      "takeaway_text": string,     // one prescriptive/forward-looking sentence, 15-30 words, no label inside\n'
    '      "date": string               // "DD Mon YYYY", or "DD-DD Mon YYYY" if merged across days\n'
    "    }\n"
    "  ],\n"
    '  "figures": [\n'
    "    {\n"
    '      "figure": string,   // exact as stated, keep unit/currency/symbol e.g. "Rs75bn", "8.62%", "B / B-"\n'
    '      "label": string,    // 3-6 words naming what it measures\n'
    '      "context": string,  // < 15 words on why it matters\n'
    '      "date": string      // "DD Mon YYYY"\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "RULES:\n"
    "1. MERGE duplicate storylines: if several editorials are stages of the same story "
    "(proposed then finalized, etc.), combine them into ONE card covering the full arc; do "
    "not emit separate cards for the same underlying event.\n"
    "2. REPHRASE headlines: never copy or merely truncate the source headline. Rewrite each as "
    "a short sentence-case title (< 8 words) that names the subject and its core outcome or tension. "
    "No all caps, no clickbait, no quotation marks, no trailing punctuation.\n"
    "3. BULLETS: exactly 2 per card, each a COMPLETE sentence (not a phrase or keyword list) that fuses "
    "at least two of: what happened, the number/evidence, why it happened, who it affects. A reader must be "
    "able to explain the story from the 2 bullets alone. Do not drop a causal link, a key figure, or a named "
    "actor/mechanism (e.g. BISP, NHA, SPI, S&P/Fitch) to save space. 20-35 words each.\n"
    "4. TAKEAWAY: one line stating the story's prescriptive conclusion or forward-looking implication. "
    "Use label \"Recommendation:\" when the source argues for an action, else \"Takeaway:\". 15-30 words. "
    "Put the label ONLY in takeaway_label, never inside takeaway_text.\n"
    "5. CUT: repetition across bullets, minor illustrative details that do not change understanding, and "
    "editorializing that adds no information. Err toward comprehensive over terse -- lose no meaning.\n"
    "6. KEY FIGURES: include a row only if the figure is a headline statistic likely cited in a CSS essay / "
    "current-affairs answer / MCQ (a rate, amount, ratio, credit rating, named date/case/article number), is "
    "the core numerical finding of its story, and is citable on its own. Exclude granular sub-statistics that "
    "just break down a figure already captured, vague non-numeric 'data', and duplicates. Roughly 1 row per "
    "story on average; a story with no strong standalone figure contributes none -- never invent one. If fewer "
    "than 3 strong figures exist, keep the list short; if none, return an empty figures array.\n"
    "7. Output ONLY the JSON object. No prose before or after."
)


def _iso_to_display(value: str) -> str:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        return value or ""


def _format_date_range(dates: List[str]) -> str:
    valid = sorted({d[:10] for d in dates if d})
    if not valid:
        return ""
    lo, hi = valid[0], valid[-1]
    if lo == hi:
        return _iso_to_display(lo)
    return f"{_iso_to_display(lo)} - {_iso_to_display(hi)}"


def _slim_editorials(editorials: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    slim = []
    for e in editorials:
        slim.append(
            {
                "publication_date": (e.get("publication_date") or "")[:10],
                "headline": e.get("headline") or "",
                "topic_domain": e.get("topic_domain") or "Other",
                "summary_bullets": e.get("summary_bullets") or [],
                "takeaway": e.get("takeaway") or "",
                "summary_paragraph": e.get("summary_paragraph") or "",
            }
        )
    return slim


def _coerce_digest(parsed: Dict[str, Any], date_range: str, source_name: str) -> Dict[str, Any]:
    cards_in = parsed.get("cards") or []
    cards: List[Dict[str, Any]] = []
    for c in cards_in:
        bullets = [str(b).strip() for b in (c.get("bullets") or []) if str(b).strip()]
        if not bullets:
            continue
        bullets = bullets[:2]
        label = str(c.get("takeaway_label") or "Takeaway:").strip()
        if label not in ("Recommendation:", "Takeaway:"):
            label = "Recommendation:" if label.lower().startswith("recommend") else "Takeaway:"
        cards.append(
            {
                "headline": str(c.get("headline") or "Untitled").strip(),
                "bullets": bullets,
                "takeaway_label": label,
                "takeaway_text": str(c.get("takeaway_text") or "").strip(),
                "date": str(c.get("date") or "").strip(),
            }
        )

    figures: List[Dict[str, Any]] = []
    for f in parsed.get("figures") or []:
        figure = str(f.get("figure") or "").strip()
        if not figure:
            continue
        figures.append(
            {
                "figure": figure,
                "label": str(f.get("label") or "").strip(),
                "context": str(f.get("context") or "").strip(),
                "date": str(f.get("date") or "").strip(),
            }
        )

    return {
        "digest_title": str(parsed.get("digest_title") or "Fact Book Digest").strip(),
        "source_name": str(parsed.get("source_name") or source_name).strip(),
        "topic": str(parsed.get("topic") or "Current Affairs").strip(),
        "date_range": date_range,
        "cards": cards,
        "figures": figures,
    }


def generate_factbook_digest(
    editorials: List[Dict[str, Any]],
    *,
    source_name: str = "Dawn Editorials",
    timeout: int = 150,
) -> Dict[str, Any]:
    """Generate a structured digest from already-summarized editorials.

    Raises RuntimeError if the Grok key is missing or the model output can't be parsed.
    """
    if not editorials:
        raise ValueError("No editorials supplied for digest generation")
    if not GROK_API:
        raise RuntimeError("GROK_API is not configured; cannot generate digest")

    date_range = _format_date_range([e.get("publication_date") or "" for e in editorials])
    slim = _slim_editorials(editorials)

    user_payload = {
        "date_range": date_range,
        "source_name": source_name,
        "editorial_count": len(slim),
        "editorials": slim,
    }

    client = GrokClient(api_key=GROK_API, timeout=timeout)
    messages = [
        GrokMessage(role="system", content=DIGEST_SYSTEM_PROMPT),
        GrokMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
    ]

    logger.info(
        f"[FACTBOOK] Generating digest for {len(slim)} editorials ({date_range or 'no range'})"
    )
    response = client.chat_completion(
        model=FACTBOOK_GROK_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.3,
        max_output_tokens=6000,
    )
    content = extract_content_text(response)
    parsed = _extract_json(content)
    if not parsed:
        raise RuntimeError("Could not parse digest JSON from Grok response")

    digest = _coerce_digest(parsed, date_range=date_range, source_name=source_name)
    if not digest["cards"]:
        raise RuntimeError("Digest generation produced no cards")

    logger.info(
        f"[FACTBOOK] Digest ready: {len(digest['cards'])} cards, {len(digest['figures'])} figures"
    )
    return digest


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = text.strip()
    # Strip ```json fences if the model added them despite instructions.
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1] if "```" in cleaned[3:] else cleaned
        cleaned = cleaned.lstrip("json").strip().strip("`").strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except Exception:
            return None
    return None
