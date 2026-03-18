"""
Daily Current Affairs MCQ ingestion from Dawn sections.

This module intentionally keeps all scrape and generation artifacts in memory
and does not write temporary JSON/files to disk.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from backend.config import (
    CURRENT_AFFAIRS_DAWN_LATEST_URL,
    CURRENT_AFFAIRS_DAWN_PAKISTAN_URL,
    CURRENT_AFFAIRS_DAWN_WORLD_URL,
    CURRENT_AFFAIRS_GENRE_ID,
    CURRENT_AFFAIRS_GROK_MODEL,
    CURRENT_AFFAIRS_MAX_CANDIDATE_LINKS_PER_SECTION,
    CURRENT_AFFAIRS_MAX_SELECTED_HEADLINES,
    CURRENT_AFFAIRS_MCQS_PER_DAY,
    CURRENT_AFFAIRS_MIN_LLM_SCORE,
    CURRENT_AFFAIRS_MIN_RELEVANCE_SCORE,
    CURRENT_AFFAIRS_REQUEST_TIMEOUT_SECONDS,
    GROK_API,
)
from backend.db.supabase_service import SupabaseService
from backend.utils.grok_client import GrokClient, GrokMessage, extract_content_text
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

DAWN_SECTIONS: List[Dict[str, str]] = [
    {"name": "latest", "url": CURRENT_AFFAIRS_DAWN_LATEST_URL},
    {"name": "pakistan", "url": CURRENT_AFFAIRS_DAWN_PAKISTAN_URL},
    {"name": "world", "url": CURRENT_AFFAIRS_DAWN_WORLD_URL},
]

_POSITIVE_RELEVANCE_PATTERNS = [
    r"\bbudget\b",
    r"\beconom(y|ic|ics)\b",
    r"\binflation\b",
    r"\bfiscal\b",
    r"\btax\b",
    r"\bimf\b",
    r"\bpolicy\b",
    r"\bparliament\b",
    r"\bsenate\b",
    r"\bnational assembly\b",
    r"\bcabinet\b",
    r"\bministry\b",
    r"\belection\b",
    r"\bconstitution\b",
    r"\bsupreme court\b",
    r"\bforeign\b",
    r"\bdiplomatic\b",
    r"\bgeopolitic",
    r"\bpakistan\b",
    r"\bindia\b",
    r"\bchina\b",
    r"\bus\b",
    r"\bunited nations\b",
    r"\bsecurity\b",
    r"\bterror\b",
    r"\bceasefire\b",
    r"\bclimate\b",
    r"\benergy\b",
    r"\bwater\b",
    r"\btrade\b",
    r"\bcpec\b",
    r"\bdebt\b",
    r"\bcurrent account\b",
    r"\bforeign exchange\b",
    r"\bmonetary\b",
    r"\bstate bank\b",
    r"\bfatf\b",
    r"\bwho\b",
    r"\bworld bank\b",
    r"\bdevelopment bank\b",
    r"\bfederal\b",
    r"\bprovincial\b",
    r"\blegislation\b",
    r"\bjudicial\b",
]

_NEGATIVE_RELEVANCE_PATTERNS = [
    r"\bsport(s)?\b",
    r"\bcricket\b",
    r"\bfootball\b",
    r"\bmovie\b",
    r"\bfilm\b",
    r"\bcelebrity\b",
    r"\bshowbiz\b",
    r"\bentertainment\b",
    r"\bfashion\b",
    r"\blifestyle\b",
    r"\brecipe\b",
    r"\bhoroscope\b",
    r"\bweather\b",
    r"\bmatch report\b",
    r"\bphoto\b",
    r"\bvideo\b",
    r"\blive updates\b",
    r"\bviral\b",
    r"\baccident\b",
    r"\bkilled\b",
    r"\binjured\b",
    r"\barrested\b",
    r"\braid\b",
    r"\btraffic\b",
    r"\bfire\b",
    r"\bpolice\b",
    r"\bcrime\b",
    r"\bmurder\b",
    r"\brobbery\b",
    r"\bshooting\b",
]

_VAGUE_QUESTION_PATTERNS = [
    r"\bthis development\b",
    r"\bthis issue\b",
    r"\bthis event\b",
    r"\brecently reported\b",
    r"\bas per reports?\b",
    r"\bwhich statement is correct\b",
    r"\bwhich statement is true\b",
]

_LOW_QUALITY_OPTION_PATTERNS = [
    r"\bnone of (the|these)\b",
    r"\ball of the above\b",
    r"\bnot given\b",
    r"\bcan(?:not|'t) be determined\b",
]


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _score_text_for_exam_relevance(text: str) -> int:
    normalized = _normalize_whitespace(text).lower()
    if not normalized:
        return 0

    score = 0
    for pattern in _POSITIVE_RELEVANCE_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            score += 1
    for pattern in _NEGATIVE_RELEVANCE_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            score -= 2
    return score


def _is_css_pms_quality_mcq(mcq: Dict[str, Any], source_row: Dict[str, Any]) -> bool:
    question = _normalize_whitespace(str(mcq.get("question", "")))
    if len(question) < 28 or len(question) > 220:
        return False

    question_l = question.lower()
    for pattern in _VAGUE_QUESTION_PATTERNS:
        if re.search(pattern, question_l, flags=re.IGNORECASE):
            return False

    options = [
        _normalize_whitespace(str(mcq.get("option_a", ""))),
        _normalize_whitespace(str(mcq.get("option_b", ""))),
        _normalize_whitespace(str(mcq.get("option_c", ""))),
        _normalize_whitespace(str(mcq.get("option_d", ""))),
    ]
    if any(not option for option in options):
        return False

    for option in options:
        for pattern in _LOW_QUALITY_OPTION_PATTERNS:
            if re.search(pattern, option.lower(), flags=re.IGNORECASE):
                return False

    correct_answer = _normalize_whitespace(str(mcq.get("correct_answer", ""))).lower()
    if not correct_answer:
        return False
    for pattern in _LOW_QUALITY_OPTION_PATTERNS:
        if re.search(pattern, correct_answer, flags=re.IGNORECASE):
            return False

    source_headline = _normalize_whitespace(str(source_row.get("headline", "")))
    relevance_text = " ".join([question, *options, source_headline])
    return _score_text_for_exam_relevance(relevance_text) >= 2


def _llm_filter_mcqs_for_css_pms(mcqs: List[Dict[str, Any]], target_date: date) -> List[Dict[str, Any]]:
    if not GROK_API or not mcqs:
        return mcqs

    payload_items = []
    for idx, row in enumerate(mcqs):
        source = row.get("source", {}) if isinstance(row, dict) else {}
        payload_items.append(
            {
                "idx": idx,
                "question": row.get("question"),
                "option_a": row.get("option_a"),
                "option_b": row.get("option_b"),
                "option_c": row.get("option_c"),
                "option_d": row.get("option_d"),
                "correct_answer": row.get("correct_answer"),
                "topic": row.get("topic"),
                "source_section": source.get("section"),
                "source_headline": source.get("headline"),
            }
        )

    system_prompt = (
        "You are a strict CSS/PMS examiner quality gate for current-affairs MCQs. "
        "Keep only MCQs that are specific, objective, policy/institution/geopolitics relevant, and non-vague. "
        "Reject MCQs that are generic, entertainment/crime focused, ambiguous, or weakly exam-relevant. "
        "Return strict JSON only."
    )
    user_payload = {
        "target_date": target_date.isoformat(),
        "instruction": "Return JSON {selected_indexes:[int,...]} using only provided idx values.",
        "items": payload_items,
    }

    try:
        client = GrokClient(api_key=GROK_API, timeout=90)
        response = client.chat_completion(
            model=CURRENT_AFFAIRS_GROK_MODEL,
            messages=[
                GrokMessage(role="system", content=system_prompt),
                GrokMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
            ],
            temperature=0.0,
            max_output_tokens=1200,
        )
        content = extract_content_text(response)
        parsed = _extract_json_object(content) or {}
        selected_indexes = parsed.get("selected_indexes") if isinstance(parsed, dict) else None
        if not isinstance(selected_indexes, list):
            return mcqs

        selected_set = {
            int(index) for index in selected_indexes if isinstance(index, int) and 0 <= index < len(mcqs)
        }
        if not selected_set:
            return []

        return [row for idx, row in enumerate(mcqs) if idx in selected_set]
    except Exception as exc:
        logger.warning(f"[CURRENT_AFFAIRS] LLM MCQ quality filter failed, using heuristic-only result. Error: {exc}")
        return mcqs


def _extract_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    candidate = (raw_text or "").strip()
    if not candidate:
        return None

    candidate = re.sub(r"^```(?:json)?", "", candidate, flags=re.IGNORECASE).strip()
    candidate = re.sub(r"```$", "", candidate).strip()

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        candidate = candidate[start : end + 1]

    try:
        parsed = json.loads(candidate)
    except Exception:
        return None

    if isinstance(parsed, dict):
        return parsed

    return None


def _is_valid_news_link(resolved_url: str) -> bool:
    parsed = urlparse(resolved_url)
    if not parsed.scheme.startswith("http"):
        return False
    if parsed.netloc and "dawn.com" not in parsed.netloc.lower():
        return False
    return "/news/" in parsed.path


def _fetch_html(url: str) -> str:
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (compatible; rubric-ai-current-affairs/1.0)",
    ]

    last_error: Optional[Exception] = None
    for attempt in range(3):
        headers = {
            "User-Agent": user_agents[attempt % len(user_agents)],
            "Accept-Language": "en-US,en;q=0.8",
            "Referer": "https://www.dawn.com",
        }
        try:
            response = requests.get(
                url,
                timeout=max(8, CURRENT_AFFAIRS_REQUEST_TIMEOUT_SECONDS),
                headers=headers,
            )
            if response.status_code in (403, 429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.0 + attempt * 1.2)
                continue

            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.0 + attempt * 1.2)
                continue
            break

    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to fetch url: {url}")


def _extract_section_candidates(section_name: str, section_url: str, listing_html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(listing_html, "html.parser")
    seen_urls: set[str] = set()
    candidates: List[Dict[str, Any]] = []

    def _add_candidate(raw_href: str, raw_headline: str) -> None:
        href = (raw_href or "").strip()
        headline = _normalize_whitespace(raw_headline)
        if not href or len(headline) < 24:
            return

        resolved_url = urljoin(section_url, href)
        if not _is_valid_news_link(resolved_url):
            return

        normalized_url = resolved_url.split("?", 1)[0].rstrip("/")
        if normalized_url in seen_urls:
            return

        seen_urls.add(normalized_url)
        candidates.append(
            {
                "id": hashlib.sha256(f"{section_name}|{normalized_url}".encode("utf-8")).hexdigest()[:12],
                "section": section_name,
                "headline": headline,
                "source_url": normalized_url,
            }
        )

    selectors = [
        "h1 a[href*='/news/']",
        "h2 a[href*='/news/']",
        "h3 a[href*='/news/']",
        "article a[href*='/news/']",
        "a.story__link[href*='/news/']",
        "a[href*='/news/']",
    ]

    for selector in selectors:
        for anchor in soup.select(selector):
            anchor_text = _normalize_whitespace(anchor.get_text(" "))
            if not anchor_text:
                heading = anchor.find(["h1", "h2", "h3", "h4"])
                if heading:
                    anchor_text = _normalize_whitespace(heading.get_text(" "))

            _add_candidate(anchor.get("href", ""), anchor_text)

            if len(candidates) >= max(1, CURRENT_AFFAIRS_MAX_CANDIDATE_LINKS_PER_SECTION):
                return candidates

    return candidates


def _headline_relevance_score(headline: str, section_name: str) -> int:
    text = _normalize_whitespace(headline).lower()
    if not text:
        return 0

    score = 0

    if section_name in {"pakistan", "world"}:
        score += 1

    if len(text.split()) >= 8:
        score += 1

    for pattern in _POSITIVE_RELEVANCE_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            score += 1

    for pattern in _NEGATIVE_RELEVANCE_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            score -= 2

    return score


def _select_candidates_with_grok(
    ranked_candidates: List[Dict[str, Any]],
    target_date: date,
) -> List[Dict[str, Any]]:
    if not GROK_API:
        return ranked_candidates[: max(1, CURRENT_AFFAIRS_MAX_SELECTED_HEADLINES)]

    client = GrokClient(api_key=GROK_API, timeout=90)
    trimmed = ranked_candidates[: max(8, min(80, len(ranked_candidates)))]

    system_prompt = (
        "You are selecting exam-relevant current-affairs headlines for CSS/PMS practice. "
        "Select only high-value policy, governance, economy, law, geopolitics, security, climate, energy, "
        "institutional, constitutional, parliamentary, judicial, and international relations developments. "
        "Reject crime blotter, celebrity, sports, entertainment, accidents, or vague clickbait. "
        "Return strict JSON only."
    )

    user_payload = {
        "target_date": target_date.isoformat(),
        "instruction": (
            "Select up to max_selected headlines most useful for objective current-affairs prep. "
            "Prefer factual headlines with named institutions, policies, treaties, legal/judicial or economic signals. "
            "Return JSON: {selected:[{id,score,reason,topic}]}. score must be 0-100."
        ),
        "max_selected": max(1, CURRENT_AFFAIRS_MAX_SELECTED_HEADLINES),
        "items": [
            {
                "id": item["id"],
                "section": item["section"],
                "headline": item["headline"],
                "source_url": item["source_url"],
                "heuristic_score": item["heuristic_score"],
            }
            for item in trimmed
        ],
    }

    try:
        response = client.chat_completion(
            model=CURRENT_AFFAIRS_GROK_MODEL,
            messages=[
                GrokMessage(role="system", content=system_prompt),
                GrokMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
            ],
            temperature=0.0,
            max_output_tokens=1800,
        )
        content = extract_content_text(response)
        parsed = _extract_json_object(content) or {}

        id_to_item = {item["id"]: dict(item) for item in trimmed}
        selected_rows = parsed.get("selected") if isinstance(parsed, dict) else None
        if not isinstance(selected_rows, list):
            return trimmed[: max(1, CURRENT_AFFAIRS_MAX_SELECTED_HEADLINES)]

        picked: List[Dict[str, Any]] = []
        for row in selected_rows:
            if not isinstance(row, dict):
                continue
            item_id = str(row.get("id", "")).strip()
            if not item_id or item_id not in id_to_item:
                continue

            base = dict(id_to_item[item_id])
            llm_score = row.get("score", 0)
            try:
                llm_score = int(llm_score)
            except Exception:
                llm_score = 0
            llm_score = max(0, min(100, llm_score))
            base["llm_score"] = llm_score
            base["llm_reason"] = _normalize_whitespace(str(row.get("reason", "")))
            base["topic"] = _normalize_whitespace(str(row.get("topic", "")))
            picked.append(base)

        if not picked:
            return trimmed[: max(1, CURRENT_AFFAIRS_MAX_SELECTED_HEADLINES)]

        picked.sort(key=lambda item: item.get("llm_score", 0), reverse=True)
        thresholded = [item for item in picked if int(item.get("llm_score", 0)) >= CURRENT_AFFAIRS_MIN_LLM_SCORE]
        if thresholded:
            picked = thresholded
        return picked[: max(1, CURRENT_AFFAIRS_MAX_SELECTED_HEADLINES)]
    except Exception as exc:
        logger.warning(f"[CURRENT_AFFAIRS] LLM relevance selection failed, using heuristic fallback. Error: {exc}")
        return trimmed[: max(1, CURRENT_AFFAIRS_MAX_SELECTED_HEADLINES)]


def _fallback_generate_mcqs(
    selected_candidates: List[Dict[str, Any]],
    target_date: date,
    target_count: int,
) -> List[Dict[str, Any]]:
    if not selected_candidates:
        return []

    rng = random.Random(target_date.toordinal())
    pool = list(dict.fromkeys(item["headline"] for item in selected_candidates))
    if len(pool) < 4:
        return []

    headline_to_source: Dict[str, Dict[str, Any]] = {}
    for item in selected_candidates:
        headline_to_source.setdefault(item["headline"], item)

    fallback_mcqs: List[Dict[str, Any]] = []

    while len(fallback_mcqs) < target_count and pool:
        sampled = rng.sample(pool, 4)
        correct = sampled[0]
        source = headline_to_source.get(correct, selected_candidates[0])
        options = sampled[:]
        rng.shuffle(options)

        fallback_mcqs.append(
            {
                "question": (
                    f"Which one of the following Dawn headlines reflects a high-priority current-affairs "
                    f"development relevant for CSS/PMS preparation on {target_date.isoformat()}?"
                ),
                "option_a": options[0],
                "option_b": options[1],
                "option_c": options[2],
                "option_d": options[3],
                "correct_answer": correct,
                "difficulty": 1,
                "source_id": source["id"],
                "topic": "Current Affairs",
                "generation_mode": "fallback",
            }
        )

    return fallback_mcqs


def _generate_mcqs_with_grok(
    selected_candidates: List[Dict[str, Any]],
    target_date: date,
    target_count: int,
) -> List[Dict[str, Any]]:
    if not selected_candidates:
        return []

    if not GROK_API:
        return _fallback_generate_mcqs(selected_candidates, target_date, target_count)

    client = GrokClient(api_key=GROK_API, timeout=120)

    system_prompt = (
        "You create high-quality CSS/PMS current affairs MCQs. "
        "Use only explicitly available information from provided Dawn headlines. "
        "Do not invent facts not inferable from headline text. "
        "Questions must be specific, objective, and exam-style; avoid vague wording. "
        "Return strict JSON only."
    )

    user_payload = {
        "target_date": target_date.isoformat(),
        "instruction": (
            "Generate objective MCQs from selected headlines. "
            "Each MCQ must have: question, option_a, option_b, option_c, option_d, correct_answer, difficulty, source_id, topic. "
            "correct_answer must exactly match one option text. "
            "difficulty must be integer 1..3. "
            "Do not use 'all of the above', 'none of the above', or vague stems like 'this development'. "
            "Prefer policy, governance, economy, law, geopolitics, security, and international affairs framing."
        ),
        "target_count": max(1, target_count),
        "headlines": [
            {
                "id": item["id"],
                "section": item["section"],
                "headline": item["headline"],
                "source_url": item["source_url"],
                "topic_hint": item.get("topic", ""),
            }
            for item in selected_candidates
        ],
        "output_schema": {
            "mcqs": [
                {
                    "question": "string",
                    "option_a": "string",
                    "option_b": "string",
                    "option_c": "string",
                    "option_d": "string",
                    "correct_answer": "string",
                    "difficulty": 1,
                    "source_id": "string",
                    "topic": "string",
                }
            ]
        },
    }

    try:
        response = client.chat_completion(
            model=CURRENT_AFFAIRS_GROK_MODEL,
            messages=[
                GrokMessage(role="system", content=system_prompt),
                GrokMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
            ],
            temperature=0.15,
            max_output_tokens=3000,
        )
        content = extract_content_text(response)
        parsed = _extract_json_object(content) or {}
        rows = parsed.get("mcqs") if isinstance(parsed, dict) else None
        if not isinstance(rows, list) or not rows:
            raise ValueError("Missing mcqs array in Grok response")

        result_rows = [row for row in rows if isinstance(row, dict)]
        if not result_rows:
            raise ValueError("No valid MCQ objects in Grok response")
        return result_rows
    except Exception as exc:
        logger.warning(f"[CURRENT_AFFAIRS] LLM MCQ generation failed, using fallback. Error: {exc}")
        return _fallback_generate_mcqs(selected_candidates, target_date, target_count)


def _resolve_correct_answer(mcq: Dict[str, Any]) -> Optional[str]:
    option_a = _normalize_whitespace(str(mcq.get("option_a", "")))
    option_b = _normalize_whitespace(str(mcq.get("option_b", "")))
    option_c = _normalize_whitespace(str(mcq.get("option_c", "")))
    option_d = _normalize_whitespace(str(mcq.get("option_d", "")))
    options = [option_a, option_b, option_c, option_d]
    if any(not item for item in options):
        return None

    # Ensure options are distinct to avoid ambiguous MCQs.
    if len({_normalize_whitespace(item).lower() for item in options}) < 4:
        return None

    raw_correct = _normalize_whitespace(str(mcq.get("correct_answer", "")))
    if not raw_correct:
        return None

    for value in options:
        if raw_correct == value:
            return value

    normalized = re.sub(r"[^a-z0-9]", "", raw_correct.lower())
    mapping = {
        "a": option_a,
        "optiona": option_a,
        "1": option_a,
        "b": option_b,
        "optionb": option_b,
        "2": option_b,
        "c": option_c,
        "optionc": option_c,
        "3": option_c,
        "d": option_d,
        "optiond": option_d,
        "4": option_d,
    }
    return mapping.get(normalized)


def _compute_question_hash(question: str, option_a: str, option_b: str, option_c: str, option_d: str, correct_answer: str) -> str:
    normalized = "|".join(
        [
            _normalize_whitespace(question).lower(),
            _normalize_whitespace(option_a).lower(),
            _normalize_whitespace(option_b).lower(),
            _normalize_whitespace(option_c).lower(),
            _normalize_whitespace(option_d).lower(),
            _normalize_whitespace(correct_answer).lower(),
        ]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _ensure_current_affairs_genre_id(supabase_service: SupabaseService) -> str:
    explicit_id = (CURRENT_AFFAIRS_GENRE_ID or "").strip()
    if explicit_id:
        result = (
            supabase_service.supabase
            .table("genres")
            .select("id,name")
            .eq("id", explicit_id)
            .limit(1)
            .execute()
        )
        rows = result.data if result.data else []
        if rows:
            return explicit_id
        raise RuntimeError("CURRENT_AFFAIRS_GENRE_ID is set but no matching row exists in genres table")

    # Prefer existing row by name first.
    try:
        existing = (
            supabase_service.supabase
            .table("genres")
            .select("id,name")
            .ilike("name", "Current Affairs")
            .limit(1)
            .execute()
        )
        rows = existing.data if existing.data else []
        if rows and rows[0].get("id"):
            return str(rows[0]["id"])
    except Exception:
        # If ilike is not available because of schema quirks, continue with insert attempts.
        pass

    insert_candidates = [
        {"name": "Current Affairs"},
        {"name": "Current Affairs", "slug": "current-affairs"},
        {"name": "Current Affairs", "description": "Daily Dawn current affairs MCQs for CSS/PMS"},
    ]

    last_error: Optional[Exception] = None
    for payload in insert_candidates:
        try:
            inserted = (
                supabase_service.supabase
                .table("genres")
                .insert(payload)
                .execute()
            )
            rows = inserted.data if inserted.data else []
            if rows and rows[0].get("id"):
                return str(rows[0]["id"])
        except Exception as exc:
            last_error = exc

    # Final lookup in case insert succeeded under race in another worker.
    result = (
        supabase_service.supabase
        .table("genres")
        .select("id,name")
        .limit(500)
        .execute()
    )
    rows = result.data if result.data else []
    for row in rows:
        name = _normalize_whitespace(str(row.get("name", ""))).lower()
        if name == "current affairs" and row.get("id"):
            return str(row["id"])

    raise RuntimeError(f"Could not resolve Current Affairs genre id. Last error: {last_error}")


async def sync_current_affairs_mcqs_for_date(
    supabase_service: SupabaseService,
    target_date: date,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Scrape Dawn sections, filter exam-relevant headlines, generate MCQs, and upsert.

    This function keeps all intermediate scrape and JSON payloads in memory only.
    """

    stats: Dict[str, Any] = {
        "date": target_date.isoformat(),
        "sections_scanned": 0,
        "candidate_headlines": 0,
        "relevant_headlines": 0,
        "mcqs_after_quality_filter": 0,
        "mcqs_generated": 0,
        "mcqs_saved": 0,
        "genre_id": None,
        "errors": [],
    }

    candidates: List[Dict[str, Any]] = []
    selected_candidates: List[Dict[str, Any]] = []
    generated_mcqs: List[Dict[str, Any]] = []
    upsert_rows: List[Dict[str, Any]] = []

    try:
        for section in DAWN_SECTIONS:
            listing_html = _fetch_html(section["url"])
            section_candidates = _extract_section_candidates(section["name"], section["url"], listing_html)

            for item in section_candidates:
                item["heuristic_score"] = _headline_relevance_score(item["headline"], item["section"])
                candidates.append(item)

            stats["sections_scanned"] += 1
            time.sleep(0.1)

        # Dedupe by URL and keep highest heuristic score version if repeated across sections.
        deduped: Dict[str, Dict[str, Any]] = {}
        for item in candidates:
            existing = deduped.get(item["source_url"])
            if not existing or item.get("heuristic_score", 0) > existing.get("heuristic_score", 0):
                deduped[item["source_url"]] = item

        ranked_candidates = list(deduped.values())
        ranked_candidates.sort(key=lambda row: row.get("heuristic_score", 0), reverse=True)
        stats["candidate_headlines"] = len(ranked_candidates)

        heuristically_relevant = [
            row for row in ranked_candidates if int(row.get("heuristic_score", 0)) >= CURRENT_AFFAIRS_MIN_RELEVANCE_SCORE
        ]
        if not heuristically_relevant:
            heuristically_relevant = ranked_candidates[: max(4, CURRENT_AFFAIRS_MAX_SELECTED_HEADLINES)]

        selected_candidates = _select_candidates_with_grok(heuristically_relevant, target_date)
        stats["relevant_headlines"] = len(selected_candidates)

        if not selected_candidates:
            return stats

        generated_mcqs = _generate_mcqs_with_grok(
            selected_candidates=selected_candidates,
            target_date=target_date,
            target_count=max(1, CURRENT_AFFAIRS_MCQS_PER_DAY),
        )

        source_lookup = {item["id"]: item for item in selected_candidates}
        normalized_mcqs: List[Dict[str, Any]] = []
        for mcq in generated_mcqs:
            question = _normalize_whitespace(str(mcq.get("question", "")))
            if len(question) < 20:
                continue

            option_a = _normalize_whitespace(str(mcq.get("option_a", "")))
            option_b = _normalize_whitespace(str(mcq.get("option_b", "")))
            option_c = _normalize_whitespace(str(mcq.get("option_c", "")))
            option_d = _normalize_whitespace(str(mcq.get("option_d", "")))

            resolved_correct = _resolve_correct_answer(
                {
                    "option_a": option_a,
                    "option_b": option_b,
                    "option_c": option_c,
                    "option_d": option_d,
                    "correct_answer": mcq.get("correct_answer", ""),
                }
            )
            if not resolved_correct:
                continue

            difficulty_raw = mcq.get("difficulty", 1)
            try:
                difficulty = int(difficulty_raw)
            except Exception:
                difficulty = 1
            difficulty = max(1, min(3, difficulty))

            source_id = _normalize_whitespace(str(mcq.get("source_id", "")))
            source_row = source_lookup.get(source_id)
            if not source_row:
                # Fallback to first relevant source when model omits source_id.
                source_row = selected_candidates[0]

            normalized_row = {
                "question": question,
                "option_a": option_a,
                "option_b": option_b,
                "option_c": option_c,
                "option_d": option_d,
                "correct_answer": resolved_correct,
                "difficulty": difficulty,
                "topic": _normalize_whitespace(str(mcq.get("topic", "Current Affairs"))) or "Current Affairs",
                "source": source_row,
                "source_id": source_row.get("id"),
                "generation_mode": _normalize_whitespace(str(mcq.get("generation_mode", "grok"))) or "grok",
            }

            if not _is_css_pms_quality_mcq(normalized_row, source_row):
                continue

            normalized_mcqs.append(normalized_row)

        # Deduplicate within the generated set.
        seen_hashes: set[str] = set()
        deduped_mcqs: List[Dict[str, Any]] = []
        for row in normalized_mcqs:
            question_hash = _compute_question_hash(
                row["question"],
                row["option_a"],
                row["option_b"],
                row["option_c"],
                row["option_d"],
                row["correct_answer"],
            )
            if question_hash in seen_hashes:
                continue
            seen_hashes.add(question_hash)
            row["question_hash"] = question_hash
            deduped_mcqs.append(row)

        deduped_mcqs = _llm_filter_mcqs_for_css_pms(deduped_mcqs, target_date)
        stats["mcqs_after_quality_filter"] = len(deduped_mcqs)

        if len(deduped_mcqs) > CURRENT_AFFAIRS_MCQS_PER_DAY:
            deduped_mcqs = deduped_mcqs[:CURRENT_AFFAIRS_MCQS_PER_DAY]

        stats["mcqs_generated"] = len(deduped_mcqs)

        if dry_run or not deduped_mcqs:
            return stats

        genre_id = _ensure_current_affairs_genre_id(supabase_service)
        stats["genre_id"] = genre_id
        generated_at = datetime.utcnow().isoformat()

        for row in deduped_mcqs:
            source = row["source"]
            upsert_rows.append(
                {
                    "genre_id": genre_id,
                    "question": row["question"],
                    "option_a": row["option_a"],
                    "option_b": row["option_b"],
                    "option_c": row["option_c"],
                    "option_d": row["option_d"],
                    "correct_answer": row["correct_answer"],
                    "difficulty": row["difficulty"],
                    "question_hash": row["question_hash"],
                    "metadata": {
                        "module": "current_affairs_dawn",
                        "source_name": "dawn",
                        "source_section": source.get("section"),
                        "source_url": source.get("source_url"),
                        "source_headline": source.get("headline"),
                        "source_date": target_date.isoformat(),
                        "topic": row.get("topic", "Current Affairs"),
                        "generation_mode": row.get("generation_mode", "grok"),
                        "generated_at": generated_at,
                    },
                }
            )

        result = (
            supabase_service.supabase
            .table("mcqs")
            .upsert(upsert_rows, on_conflict="question_hash")
            .execute()
        )

        stats["mcqs_saved"] = len(result.data) if result.data else len(upsert_rows)
        return stats
    except Exception as exc:
        logger.error(f"[CURRENT_AFFAIRS] Sync failed for {target_date.isoformat()}: {exc}")
        stats["errors"].append(str(exc))
        raise
    finally:
        # Explicitly clear transient in-memory scrape + generation payloads.
        candidates.clear()
        selected_candidates.clear()
        generated_mcqs.clear()
        upsert_rows.clear()
