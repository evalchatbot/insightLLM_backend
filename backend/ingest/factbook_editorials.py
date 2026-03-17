"""
Dawn editorial ingestion + summarization for the Fact Book feature.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from backend.config import (
    FACTBOOK_DAWN_BASE_URL,
    FACTBOOK_GROK_MODEL,
    FACTBOOK_MAX_CANDIDATE_LINKS,
    FACTBOOK_MAX_EDITORIALS_PER_DAY,
    FACTBOOK_REQUEST_TIMEOUT_SECONDS,
    FACTBOOK_TOPIC_MODEL,
    GROK_API,
)
from backend.db.supabase_service import SupabaseService
from backend.ingest.factbook_topics import ALL_TOPIC_DOMAINS, keyword_fallback_topic_domain, normalize_topic_domain
from backend.utils.grok_client import GrokClient, GrokMessage, extract_content_text
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

_NOISE_PATTERNS = [
    r"^Most Popular$",
    r"^Latest Stories$",
    r"^Read more$",
    r"^Comments$",
    r"^Published in Dawn",
    r"^DAWN NEWS ENGLISH",
]


def _iter_dates(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current = current + timedelta(days=1)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _hash_source_key(publication_date: date, headline: str, source_name: str = "dawn") -> str:
    key = f"{source_name}|{publication_date.isoformat()}|{_normalize_whitespace(headline).lower()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _build_listing_url(target_date: date) -> str:
    base = FACTBOOK_DAWN_BASE_URL.rstrip("/")
    return f"{base}/newspaper/editorial/{target_date.isoformat()}"


def _is_noise_paragraph(text: str) -> bool:
    cleaned = _normalize_whitespace(text)
    if len(cleaned) < 35:
        return True
    for pattern in _NOISE_PATTERNS:
        if re.search(pattern, cleaned, flags=re.IGNORECASE):
            return True
    return False


def _extract_candidate_links(listing_html: str) -> List[str]:
    soup = BeautifulSoup(listing_html, "html.parser")
    base = FACTBOOK_DAWN_BASE_URL.rstrip("/")
    seen = set()
    links: List[str] = []

    def add_link(raw_href: str):
        href = (raw_href or "").strip()
        if not href:
            return

        resolved = urljoin(f"{base}/", href)
        parsed = urlparse(resolved)
        if not parsed.scheme.startswith("http"):
            return
        if parsed.netloc and "dawn.com" not in parsed.netloc.lower():
            return
        if "/news/" not in parsed.path:
            return

        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if normalized in seen:
            return
        seen.add(normalized)
        links.append(normalized)

    # Combine multiple selectors so we do not miss editorials due layout changes.
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
            add_link(anchor.get("href", ""))

    return links[: max(FACTBOOK_MAX_CANDIDATE_LINKS, 1)]


def _parse_date_string(raw_date: str) -> Optional[date]:
    value = _normalize_whitespace(raw_date)
    if not value:
        return None

    for fmt in ("%B %d, %Y", "%d %b, %Y", "%d %B, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    return None


def _extract_publication_date(soup: BeautifulSoup, raw_html: str) -> Optional[date]:
    for tag in soup.select("time"):
        datetime_attr = (tag.get("datetime") or "").strip()
        if datetime_attr:
            try:
                return datetime.fromisoformat(datetime_attr.replace("Z", "+00:00")).date()
            except ValueError:
                pass
        tag_text = _normalize_whitespace(tag.get_text(" "))
        parsed = _parse_date_string(tag_text)
        if parsed:
            return parsed

    text_blob = soup.get_text(" ", strip=True)
    match = re.search(r"Published\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", text_blob, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"Published\s+(\d{1,2}\s+[A-Za-z]+,\s+\d{4})", text_blob, flags=re.IGNORECASE)
    if match:
        parsed = _parse_date_string(match.group(1))
        if parsed:
            return parsed

    # Final fallback from raw html.
    html_match = re.search(r"Published\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", raw_html, flags=re.IGNORECASE)
    if html_match:
        return _parse_date_string(html_match.group(1))

    return None


def _extract_headline(soup: BeautifulSoup) -> str:
    og_title = soup.select_one("meta[property='og:title']")
    if og_title and og_title.get("content"):
        title = _normalize_whitespace(og_title["content"])
        if "|" in title:
            title = title.split("|", 1)[0].strip()
        if title:
            return title

    for selector in ("h1", "h2"):
        tag = soup.select_one(selector)
        if tag:
            title = _normalize_whitespace(tag.get_text(" "))
            if title:
                return title

    return "Untitled Editorial"


def _is_editorial_article(soup: BeautifulSoup, raw_html: str) -> bool:
    if soup.select_one("a[href*='/authors/2677/editorial']"):
        return True

    text_blob = _normalize_whitespace(soup.get_text(" ", strip=True))
    if re.search(r"\bEditorial\b\s*\|\s*Published", text_blob, flags=re.IGNORECASE):
        return True

    return bool(re.search(r">\s*Editorial\s*<", raw_html, flags=re.IGNORECASE))


def _extract_body_text(soup: BeautifulSoup) -> str:
    selectors = [
        "div.story__content",
        ".story__content",
        "article.story",
        "article",
        "[itemprop='articleBody']",
    ]

    for selector in selectors:
        container = soup.select_one(selector)
        if not container:
            continue

        paragraphs: List[str] = []
        for paragraph in container.select("p"):
            text = _normalize_whitespace(paragraph.get_text(" "))
            if _is_noise_paragraph(text):
                continue
            paragraphs.append(text)

        if len(paragraphs) >= 3:
            return "\n\n".join(paragraphs)

    fallback_paragraphs: List[str] = []
    for paragraph in soup.select("p"):
        text = _normalize_whitespace(paragraph.get_text(" "))
        if _is_noise_paragraph(text):
            continue
        fallback_paragraphs.append(text)

    if len(fallback_paragraphs) >= 3:
        return "\n\n".join(fallback_paragraphs[:14])

    return ""


def _extract_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    candidate = (raw_text or "").strip()
    if not candidate:
        return None

    # Remove markdown fences if present.
    candidate = re.sub(r"^```(?:json)?", "", candidate, flags=re.IGNORECASE).strip()
    candidate = re.sub(r"```$", "", candidate).strip()

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        candidate = candidate[start : end + 1]

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None

    return None


def _split_sentences(text: str) -> List[str]:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if not normalized:
        return []
    return [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", normalized) if segment.strip()]


def _fallback_summary(article_text: str) -> Dict[str, Any]:
    sentences = _split_sentences(article_text)
    if not sentences:
        return {
            "summary_bullets": ["No summary available.", "No summary available.", "No summary available."],
            "takeaway": "No takeaway available.",
            "summary_paragraph": "No detailed summary available.",
        }

    bullets = [sentence[:200].strip() for sentence in sentences[:3]]
    while len(bullets) < 3:
        bullets.append(bullets[-1] if bullets else "No summary available.")

    paragraph_sentences = []
    total_words = 0
    for sentence in sentences:
        words = sentence.split()
        paragraph_sentences.append(sentence)
        total_words += len(words)
        if total_words >= 95:
            break

    paragraph = " ".join(paragraph_sentences).strip()
    if not paragraph:
        paragraph = bullets[0]

    takeaway = bullets[0]
    if len(takeaway) > 180:
        takeaway = takeaway[:177].rstrip() + "..."

    return {
        "summary_bullets": bullets[:3],
        "takeaway": takeaway,
        "summary_paragraph": paragraph,
    }


def _normalize_summary_payload(payload: Dict[str, Any], article_text: str) -> Dict[str, Any]:
    fallback = _fallback_summary(article_text)

    bullets_raw = payload.get("summary_bullets", []) if isinstance(payload, dict) else []
    bullets = [
        _normalize_whitespace(str(item))
        for item in bullets_raw
        if _normalize_whitespace(str(item))
    ]

    if len(bullets) < 3:
        for item in fallback["summary_bullets"]:
            if len(bullets) >= 3:
                break
            bullets.append(item)

    takeaway = _normalize_whitespace(str(payload.get("takeaway", ""))) if isinstance(payload, dict) else ""
    if not takeaway:
        takeaway = fallback["takeaway"]

    paragraph = _normalize_whitespace(str(payload.get("summary_paragraph", ""))) if isinstance(payload, dict) else ""
    if not paragraph:
        paragraph = fallback["summary_paragraph"]

    return {
        "summary_bullets": bullets[:3],
        "takeaway": takeaway,
        "summary_paragraph": paragraph,
    }


def _truncate_text(value: str, limit: int = 220) -> str:
    text = _normalize_whitespace(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def build_thesis_statement(headline: str, summary_payload: Dict[str, Any]) -> str:
    bullets = summary_payload.get("summary_bullets") or []
    paragraph = summary_payload.get("summary_paragraph") or ""
    takeaway = summary_payload.get("takeaway") or ""

    candidates = []
    if bullets:
        candidates.append(str(bullets[0]))
    if takeaway:
        candidates.append(str(takeaway))
    if paragraph:
        first_sentence = re.split(r"(?<=[.!?])\s+", paragraph.strip())[0]
        if first_sentence:
            candidates.append(first_sentence)
    candidates.append(headline)

    for candidate in candidates:
        cleaned = _normalize_whitespace(str(candidate))
        if cleaned:
            return _truncate_text(cleaned, limit=180)

    return ""


def classify_editorial_topic_domain(headline: str, summary_payload: Dict[str, Any]) -> str:
    context_text = " ".join(
        [
            headline,
            " ".join(summary_payload.get("summary_bullets") or []),
            summary_payload.get("takeaway", ""),
            summary_payload.get("summary_paragraph", ""),
        ]
    )

    if not GROK_API:
        return keyword_fallback_topic_domain(context_text)

    prompt = (
        "Classify the editorial into exactly one topic_domain from this list only: "
        + ", ".join(ALL_TOPIC_DOMAINS)
        + ". Return strict JSON with one key: topic_domain."
    )

    client = GrokClient(api_key=GROK_API, timeout=90)
    messages = [
        GrokMessage(role="system", content="You are a strict topic classifier."),
        GrokMessage(
            role="user",
            content=json.dumps(
                {
                    "instruction": prompt,
                    "headline": headline,
                    "summary_bullets": summary_payload.get("summary_bullets", []),
                    "takeaway": summary_payload.get("takeaway", ""),
                    "summary_paragraph": summary_payload.get("summary_paragraph", ""),
                    "allowed_topics": ALL_TOPIC_DOMAINS,
                },
                ensure_ascii=False,
            ),
        ),
    ]

    try:
        response = client.chat_completion(
            model=FACTBOOK_TOPIC_MODEL,
            messages=messages,
            temperature=0.0,
            max_output_tokens=200,
        )
        content = extract_content_text(response)
        parsed = _extract_json_object(content) or {}
        topic = normalize_topic_domain(str(parsed.get("topic_domain", "")))
        if topic:
            return topic
    except Exception as exc:
        logger.debug(f"[FACTBOOK] Topic classification failed, falling back to keywords. Error: {exc}")

    return keyword_fallback_topic_domain(context_text)


def summarize_editorial_with_grok(headline: str, article_text: str) -> Dict[str, Any]:
    if not GROK_API:
        logger.warning("[FACTBOOK] Grok API key missing, using fallback summarizer")
        return _fallback_summary(article_text)

    client = GrokClient(api_key=GROK_API, timeout=120)
    max_input_chars = 9000
    trimmed_text = article_text[:max_input_chars]

    system_prompt = (
        "You are a precise editorial summarizer. Return strict JSON only with keys: "
        "summary_bullets, takeaway, summary_paragraph. "
        "summary_bullets must be exactly 3 concise bullets. "
        "takeaway must be a single sentence. "
        "summary_paragraph must be one paragraph, around 90 to 130 words."
    )

    user_payload = {
        "headline": headline,
        "article_text": trimmed_text,
        "output_schema": {
            "summary_bullets": ["string", "string", "string"],
            "takeaway": "string",
            "summary_paragraph": "string",
        },
    }

    messages = [
        GrokMessage(role="system", content=system_prompt),
        GrokMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
    ]

    try:
        response = client.chat_completion(
            model=FACTBOOK_GROK_MODEL,
            messages=messages,
            temperature=0.2,
            max_output_tokens=1200,
        )
        content = extract_content_text(response)
        parsed = _extract_json_object(content)
        if not parsed:
            raise ValueError("Could not parse Grok summary JSON")
        return _normalize_summary_payload(parsed, article_text)
    except Exception as exc:
        logger.warning(f"[FACTBOOK] Grok summary failed, falling back. Error: {exc}")
        return _fallback_summary(article_text)


def _fetch_html(url: str) -> str:
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (compatible; rubric-ai-factbook/1.0)",
    ]

    last_error: Optional[Exception] = None
    for attempt in range(3):
        headers = {
            "User-Agent": user_agents[attempt % len(user_agents)],
            "Accept-Language": "en-US,en;q=0.8",
            "Referer": FACTBOOK_DAWN_BASE_URL,
        }
        try:
            response = requests.get(
                url,
                timeout=FACTBOOK_REQUEST_TIMEOUT_SECONDS,
                headers=headers,
            )

            if response.status_code in (403, 429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.0 + attempt * 1.5)
                continue

            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.0 + attempt * 1.5)
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to fetch URL: {url}")


def _extract_editorial_candidate(article_html: str, article_url: str, target_date: date) -> Optional[Dict[str, Any]]:
    soup = BeautifulSoup(article_html, "html.parser")

    publication_date = _extract_publication_date(soup, article_html)
    if publication_date != target_date:
        return None

    # Listing URL is editorial-scoped; markers can be inconsistent, so keep only date/content checks.
    headline = _extract_headline(soup)
    body_text = _extract_body_text(soup)
    if len(body_text) < 120:
        return None

    source_name = "dawn"
    source_hash = _hash_source_key(publication_date=publication_date, headline=headline, source_name=source_name)

    return {
        "publication_date": publication_date.isoformat(),
        "headline": headline,
        "body_text": body_text,
        "source_url": article_url,
        "source_hash": source_hash,
        "source_name": source_name,
        "last_synced_at": datetime.utcnow().isoformat(),
    }


def _finalize_editorial_record(candidate: Dict[str, Any]) -> Dict[str, Any]:
    summary_payload = summarize_editorial_with_grok(
        headline=candidate["headline"],
        article_text=candidate["body_text"],
    )
    topic_domain = classify_editorial_topic_domain(candidate["headline"], summary_payload)
    thesis_statement = build_thesis_statement(candidate["headline"], summary_payload)

    return {
        "publication_date": candidate["publication_date"],
        "headline": candidate["headline"],
        "summary_bullets": summary_payload["summary_bullets"],
        "takeaway": summary_payload["takeaway"],
        "summary_paragraph": summary_payload["summary_paragraph"],
        "topic_domain": topic_domain,
        "thesis_statement": thesis_statement,
        "source_url": candidate["source_url"],
        "source_hash": candidate["source_hash"],
        "source_name": candidate["source_name"],
        "last_synced_at": candidate["last_synced_at"],
    }


async def sync_editorials_for_range(
    supabase_service: SupabaseService,
    start_date: date,
    end_date: date,
    dry_run: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any], Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "days_processed": 0,
        "editorials_saved": 0,
        "editorials_collected": 0,
        "summaries_generated": 0,
        "duplicates_skipped": 0,
        "candidate_links_checked": 0,
        "errors": [],
        "per_day": [],
    }

    for target_date in _iter_dates(start_date, end_date):
        logger.info(f"[FACTBOOK] Day start {target_date.isoformat()} | dry_run={dry_run}")

        day_stats = {
            "date": target_date.isoformat(),
            "candidate_links": 0,
            "articles_scanned": 0,
            "editorials_collected": 0,
            "summaries_generated": 0,
            "duplicates_skipped": 0,
            "existing_records": 0,
            "editorials_saved": 0,
            "errors": [],
        }

        try:
            listing_url = _build_listing_url(target_date)
            listing_html = _fetch_html(listing_url)
            candidate_links = _extract_candidate_links(listing_html)

            day_stats["candidate_links"] = len(candidate_links)
            stats["candidate_links_checked"] += len(candidate_links)

            existing_hashes = await supabase_service.get_factbook_source_hashes_by_date(target_date.isoformat())
            day_stats["existing_records"] = len(existing_hashes)

            records: List[Dict[str, Any]] = []
            seen_hashes: set[str] = set()
            for link in candidate_links:
                if len(records) >= FACTBOOK_MAX_EDITORIALS_PER_DAY:
                    break

                try:
                    day_stats["articles_scanned"] += 1
                    article_html = _fetch_html(link)
                    candidate = _extract_editorial_candidate(article_html, link, target_date)
                    if not candidate:
                        continue

                    source_hash = candidate["source_hash"]
                    if source_hash in seen_hashes or source_hash in existing_hashes:
                        day_stats["duplicates_skipped"] += 1
                        continue

                    seen_hashes.add(source_hash)
                    record = _finalize_editorial_record(candidate)
                    day_stats["summaries_generated"] += 1
                    records.append(record)
                except Exception as article_error:
                    err_msg = f"{target_date.isoformat()} | {link} | {article_error}"
                    day_stats["errors"].append(err_msg)
                    logger.warning(f"[FACTBOOK] Failed article parse: {err_msg}")

                # Keep requests gentle for origin stability.
                time.sleep(0.15)

            day_stats["editorials_collected"] = len(records)
            stats["editorials_collected"] += len(records)
            stats["summaries_generated"] += day_stats["summaries_generated"]
            stats["duplicates_skipped"] += day_stats["duplicates_skipped"]

            if records and not dry_run:
                saved_count = await supabase_service.upsert_factbook_editorials(records)
                day_stats["editorials_saved"] = saved_count
                stats["editorials_saved"] += saved_count

        except Exception as day_error:
            err_msg = f"{target_date.isoformat()} | listing error | {day_error}"
            day_stats["errors"].append(err_msg)
            stats["errors"].append(err_msg)
            logger.warning(f"[FACTBOOK] Failed day ingestion: {err_msg}")

        stats["days_processed"] += 1
        stats["per_day"].append(day_stats)

        logger.info(
            "[FACTBOOK] Day complete "
            f"{day_stats['date']} | links={day_stats['candidate_links']} "
            f"scanned={day_stats['articles_scanned']} kept={day_stats['editorials_collected']} "
            f"dup_skipped={day_stats['duplicates_skipped']} saved={day_stats['editorials_saved']} "
            f"errors={len(day_stats['errors'])}"
        )

        if progress_callback:
            try:
                progress_callback(day_stats, stats)
            except Exception as callback_error:
                logger.warning(f"[FACTBOOK] Progress callback failed: {callback_error}")

    return stats
