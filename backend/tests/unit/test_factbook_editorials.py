"""Dawn editorial scraping/summarising logic, driven by small inline HTML fixtures."""

from __future__ import annotations

from datetime import date

import pytest
from bs4 import BeautifulSoup

from backend.ingest import factbook_editorials as fe
from support.fakes import RecordingPost, grok_completion, make_requests_response

pytestmark = pytest.mark.unit

LISTING_HTML = """
<html><body>
  <h2><a href="/news/1901/tax-reforms">Tax reforms</a></h2>
  <article><a href="https://www.dawn.com/news/1902/flood-relief?utm_source=x">Flood relief</a></article>
  <a href="/news/1901/tax-reforms#comments">duplicate with fragment</a>
  <a href="https://evil.example/news/1">off-site</a>
  <a href="/authors/2677/editorial">Editorial</a>
  <a href="mailto:letters@dawn.com">mail</a>
  <a class="story__link" href="/news/1903/judiciary">Judiciary</a>
</body></html>
"""

BODY_PARAS = [
    "The government has announced sweeping tax reforms aimed at widening the narrow base.",
    "Critics argue that the burden will again fall on salaried classes and manufacturers.",
    "Unless enforcement improves, the reforms may do little to raise the tax-to-GDP ratio.",
]


def article_html(*, headline="Tax reforms", when='datetime="2026-03-05T02:00:00+05:00"', paras=BODY_PARAS, og=True):
    meta = f'<meta property="og:title" content="{headline} | Editorial - DAWN.COM">' if og else ""
    body = "".join(f"<p>{p}</p>" for p in paras)
    return f"""
    <html><head>{meta}</head><body>
      <h1>{headline} (h1)</h1>
      <a href="/authors/2677/editorial">Editorial</a>
      <time {when}>March 5, 2026</time>
      <div class="story__content">
        <p>Short noise.</p>
        {body}
        <p>Published in Dawn, March 5th, 2026</p>
      </div>
    </body></html>
    """


# ---------------------------------------------------------------- link discovery


def test_candidate_links_are_normalised_deduped_and_dawn_only():
    assert fe._extract_candidate_links(LISTING_HTML) == [
        "https://www.dawn.com/news/1901/tax-reforms",
        "https://www.dawn.com/news/1902/flood-relief",
        "https://www.dawn.com/news/1903/judiciary",
    ]


def test_candidate_links_capped(monkeypatch):
    monkeypatch.setattr(fe, "FACTBOOK_MAX_CANDIDATE_LINKS", 2)
    assert len(fe._extract_candidate_links(LISTING_HTML)) == 2


def test_listing_url():
    assert fe._build_listing_url(date(2026, 3, 5)) == "https://www.dawn.com/newspaper/editorial/2026-03-05"


# ---------------------------------------------------------------- article parsing


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("March 5, 2026", date(2026, 3, 5)),
        ("5 Mar, 2026", date(2026, 3, 5)),
        ("05 March, 2026", date(2026, 3, 5)),
        ("Mar 5, 2026", date(2026, 3, 5)),
        ("  March   5,   2026 ", date(2026, 3, 5)),
        ("2026-03-05", None),
        ("", None),
    ],
)
def test_parse_date_string(raw, expected):
    assert fe._parse_date_string(raw) == expected


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<time datetime="2026-03-05T02:00:00Z">x</time>', date(2026, 3, 5)),
        ("<time>March 4, 2026</time>", date(2026, 3, 4)),
        ("<p>Editorial | Published March 3, 2026 07:10am</p>", date(2026, 3, 3)),
        ("<p>Published 2 March, 2026</p>", date(2026, 3, 2)),
        ("<p>no date anywhere</p>", None),
    ],
)
def test_extract_publication_date(html, expected):
    assert fe._extract_publication_date(BeautifulSoup(html, "html.parser"), html) == expected


def test_headline_prefers_og_title_without_site_suffix():
    soup = BeautifulSoup(article_html(), "html.parser")
    assert fe._extract_headline(soup) == "Tax reforms"


def test_headline_falls_back_to_h1_then_placeholder():
    soup = BeautifulSoup(article_html(og=False), "html.parser")
    assert fe._extract_headline(soup) == "Tax reforms (h1)"
    assert fe._extract_headline(BeautifulSoup("<p>x</p>", "html.parser")) == "Untitled Editorial"


def test_body_text_drops_noise_paragraphs():
    soup = BeautifulSoup(article_html(), "html.parser")
    assert fe._extract_body_text(soup) == "\n\n".join(BODY_PARAS)


def test_body_text_needs_three_real_paragraphs():
    soup = BeautifulSoup(article_html(paras=BODY_PARAS[:2]), "html.parser")
    assert fe._extract_body_text(soup) == ""


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<a href="/authors/2677/editorial">x</a>', True),
        ("<p>Editorial | Published March 3, 2026</p>", True),
        ("<span>Editorial</span>", True),
        ("<p>Opinion column by a guest writer</p>", False),
    ],
)
def test_is_editorial_article(html, expected):
    assert fe._is_editorial_article(BeautifulSoup(html, "html.parser"), html) is expected


def test_editorial_candidate_happy_path():
    cand = fe._extract_editorial_candidate(article_html(), "https://www.dawn.com/news/1901", date(2026, 3, 5))
    assert cand["headline"] == "Tax reforms"
    assert cand["publication_date"] == "2026-03-05"
    assert cand["source_name"] == "dawn"
    assert cand["source_hash"] == fe._hash_source_key(date(2026, 3, 5), "Tax reforms")
    assert cand["body_text"].startswith("The government has announced")


def test_editorial_candidate_rejects_wrong_day_or_thin_body():
    html = article_html()
    assert fe._extract_editorial_candidate(html, "u", date(2026, 3, 6)) is None
    thin = article_html(paras=["x" * 36, "y" * 36, "z" * 36])  # 3 real paragraphs, but < 120 chars
    assert fe._extract_editorial_candidate(thin, "u", date(2026, 3, 5)) is None


def test_source_hash_ignores_case_and_whitespace():
    d = date(2026, 3, 5)
    assert fe._hash_source_key(d, "Tax  Reforms ") == fe._hash_source_key(d, "tax reforms")
    assert fe._hash_source_key(d, "Tax reforms") != fe._hash_source_key(date(2026, 3, 6), "Tax reforms")
    assert len(fe._hash_source_key(d, "x")) == 64


# ---------------------------------------------------------------- summaries


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('Sure! Here it is: {"a": {"b": 2}} Hope that helps', {"a": {"b": 2}}),
        ("[1, 2]", None),
        ("not json", None),
        ("", None),
        (None, None),
    ],
)
def test_extract_json_object(raw, expected):
    assert fe._extract_json_object(raw) == expected


def test_fallback_summary_from_text():
    text = " ".join(BODY_PARAS)
    out = fe._fallback_summary(text, headline="Tax reforms")
    assert out["summary_bullets"] == BODY_PARAS
    assert out["takeaway"] == BODY_PARAS[0]
    assert out["summary_headline"] == BODY_PARAS[0]
    assert out["summary_paragraph"] == text


def test_fallback_summary_without_text():
    out = fe._fallback_summary("", headline="")
    assert out["summary_headline"] == "Editorial context and implications"
    assert out["summary_bullets"] == ["No summary available."] * 3


def test_fallback_summary_pads_to_three_bullets_and_truncates_takeaway():
    long_sentence = "A" * 300 + "."
    out = fe._fallback_summary(long_sentence)
    assert len(out["summary_bullets"]) == 3
    assert all(len(b) <= 200 for b in out["summary_bullets"])
    assert out["takeaway"].endswith("...") and len(out["takeaway"]) == 180


def test_normalize_summary_payload_fills_gaps_from_fallback():
    payload = {"summary_headline": "  Reforms   face test ", "summary_bullets": ["one", "", "  "], "takeaway": ""}
    out = fe._normalize_summary_payload(payload, " ".join(BODY_PARAS))
    assert out["summary_headline"] == "Reforms face test"
    assert out["summary_bullets"] == ["one", BODY_PARAS[0], BODY_PARAS[1]]
    assert out["takeaway"] == BODY_PARAS[0]
    assert out["summary_paragraph"]


def test_normalize_summary_payload_non_dict():
    out = fe._normalize_summary_payload(["junk"], " ".join(BODY_PARAS), headline="H")
    assert out["summary_bullets"] == BODY_PARAS


def test_thesis_prefers_first_bullet_and_truncates():
    assert fe.build_thesis_statement("H", {"summary_bullets": ["First point."], "takeaway": "T"}) == "First point."
    assert fe.build_thesis_statement("H", {"takeaway": "Takeaway."}) == "Takeaway."
    assert fe.build_thesis_statement("H", {"summary_paragraph": "One. Two."}) == "One."
    assert fe.build_thesis_statement("Headline only", {}) == "Headline only"
    long = fe.build_thesis_statement("H", {"summary_bullets": ["x" * 400]})
    assert len(long) == 180 and long.endswith("...")


def test_summarize_without_grok_key_uses_fallback(monkeypatch):
    monkeypatch.setattr(fe, "GROK_API", None)
    out = fe.summarize_editorial_with_grok("Tax reforms", " ".join(BODY_PARAS))
    assert out["summary_bullets"] == BODY_PARAS


def test_summarize_with_grok_normalises_model_output(monkeypatch):
    from backend.utils import grok_client

    model = '{"summary_headline": "Tax base widening", "summary_bullets": ["b1", "b2", "b3", "b4"], "takeaway": "Enforce", "summary_paragraph": "P"}'
    post = RecordingPost(make_requests_response(200, grok_completion(model)))
    monkeypatch.setattr(fe, "GROK_API", "k")
    monkeypatch.setattr(grok_client.requests, "post", post)
    out = fe.summarize_editorial_with_grok("Tax reforms", "x" * 20000)
    assert out == {"summary_headline": "Tax base widening", "summary_bullets": ["b1", "b2", "b3"], "takeaway": "Enforce", "summary_paragraph": "P"}
    import json

    sent = json.loads(post.calls[0]["data"])
    assert len(sent["messages"][-1]["content"]) < 20000  # article text is trimmed before sending


def test_summarize_with_grok_error_falls_back(monkeypatch):
    from backend.utils import grok_client

    monkeypatch.setattr(fe, "GROK_API", "k")
    monkeypatch.setattr(grok_client.requests, "post", RecordingPost(make_requests_response(500, {"error": "down"})))
    out = fe.summarize_editorial_with_grok("Tax reforms", " ".join(BODY_PARAS))
    assert out["summary_bullets"] == BODY_PARAS


# ---------------------------------------------------------------- fetching


class FakeGet:
    def __init__(self, *statuses):
        self.statuses = list(statuses)
        self.calls = []

    def __call__(self, url, timeout=None, headers=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        status = self.statuses.pop(0)
        if isinstance(status, Exception):
            raise status
        return make_requests_response(status, text=f"<html>{status}</html>")


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(fe.time, "sleep", lambda s: slept.append(s))
    return slept


def test_fetch_goes_through_rendering_proxy_with_retry(monkeypatch, no_sleep):
    get = FakeGet(403, 200)
    monkeypatch.setattr(fe.requests, "get", get)
    monkeypatch.setattr(fe, "FACTBOOK_FETCH_PROXY_PREFIX", "https://r.jina.ai/")
    monkeypatch.setattr(fe, "FACTBOOK_FETCH_PROXY_TOKEN", "proxy-token")
    assert fe._fetch_html("https://www.dawn.com/news/1") == "<html>200</html>"
    assert [c["url"] for c in get.calls] == ["https://r.jina.ai/https://www.dawn.com/news/1"] * 2
    assert get.calls[0]["headers"]["X-Return-Format"] == "html"
    assert get.calls[0]["headers"]["Authorization"] == "Bearer proxy-token"
    assert get.calls[0]["headers"]["User-Agent"] != get.calls[1]["headers"]["User-Agent"]  # rotates UA


def test_fetch_direct_when_proxy_disabled(monkeypatch, no_sleep):
    get = FakeGet(200)
    monkeypatch.setattr(fe.requests, "get", get)
    monkeypatch.setattr(fe, "FACTBOOK_FETCH_PROXY_PREFIX", "")
    fe._fetch_html("https://www.dawn.com/news/1")
    assert get.calls[0]["url"] == "https://www.dawn.com/news/1"
    assert "X-Return-Format" not in get.calls[0]["headers"]


def test_fetch_gives_up_after_three_attempts(monkeypatch, no_sleep):
    import requests

    monkeypatch.setattr(fe.requests, "get", FakeGet(503, 503, 503))
    with pytest.raises(requests.HTTPError):
        fe._fetch_html("https://www.dawn.com/news/1")


def test_fetch_retries_network_errors_then_raises(monkeypatch, no_sleep):
    import requests

    get = FakeGet(requests.ConnectionError("reset"), requests.ConnectionError("reset"), requests.ConnectionError("reset"))
    monkeypatch.setattr(fe.requests, "get", get)
    with pytest.raises(requests.ConnectionError):
        fe._fetch_html("https://www.dawn.com/news/1")
    assert len(get.calls) == 3


def test_throttle_spaces_requests(monkeypatch):
    clock = {"now": 100.0}
    slept = []
    monkeypatch.setattr(fe, "FACTBOOK_FETCH_MIN_INTERVAL_SECONDS", 3.0)
    monkeypatch.setattr(fe, "_last_fetch_started_at", 0.0)
    monkeypatch.setattr(fe.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(fe.time, "sleep", lambda s: slept.append(s))
    fe._throttle_fetch()
    clock["now"] = 101.0
    fe._throttle_fetch()
    assert slept == [pytest.approx(2.0)]


# ---------------------------------------------------------------- whole-day sync


class FakeFactbookService:
    def __init__(self, existing_hashes=()):
        self.existing = set(existing_hashes)
        self.upserts = []

    async def get_factbook_source_hashes_by_date(self, publication_date):
        return set(self.existing)

    async def upsert_factbook_editorials(self, records):
        self.upserts.append(records)
        return len(records)


@pytest.fixture
def web(monkeypatch, no_sleep):
    pages = {
        fe._build_listing_url(date(2026, 3, 5)): """
            <a href="/news/1">A</a><a href="/news/2">A again</a><a href="/news/3">B</a>
            <a href="/news/4">broken</a><a href="/news/5">other day</a>""",
        "https://www.dawn.com/news/1": article_html(headline="Tax reforms"),
        "https://www.dawn.com/news/2": article_html(headline="TAX  reforms"),
        "https://www.dawn.com/news/3": article_html(headline="Already stored"),
        "https://www.dawn.com/news/5": article_html(headline="Old", when='datetime="2026-03-04T00:00:00Z"'),
    }

    def fake_fetch(url):
        if url not in pages:
            raise RuntimeError(f"HTTP 404 for {url}")
        return pages[url]

    monkeypatch.setattr(fe, "_fetch_html", fake_fetch)
    monkeypatch.setattr(fe, "GROK_API", None)
    return pages


async def test_sync_day_dedupes_skips_existing_and_isolates_errors(web):
    svc = FakeFactbookService(existing_hashes={fe._hash_source_key(date(2026, 3, 5), "Already stored")})
    progress = []
    stats = await fe.sync_editorials_for_range(
        svc, date(2026, 3, 5), date(2026, 3, 6), progress_callback=lambda day, total: progress.append(day["date"])
    )
    day1, day2 = stats["per_day"]
    assert day1["candidate_links"] == 5
    assert day1["editorials_collected"] == 1
    assert day1["duplicates_skipped"] == 2  # same headline twice + already in DB
    assert len(day1["errors"]) == 1 and "news/4" in day1["errors"][0]
    assert day1["editorials_saved"] == 1
    (records,) = svc.upserts
    rec = records[0]
    assert rec["publication_date"] == "2026-03-05"
    assert rec["topic_domain"] == "Economy"  # keyword fallback without Grok
    assert rec["thesis_statement"]
    # day 2 listing is missing -> recorded as a day-level error, run continues
    assert stats["days_processed"] == 2
    assert stats["errors"] == [day2["errors"][0]]
    assert "listing error" in day2["errors"][0]
    assert progress == ["2026-03-05", "2026-03-06"]


async def test_sync_dry_run_never_writes(web):
    svc = FakeFactbookService()
    stats = await fe.sync_editorials_for_range(svc, date(2026, 3, 5), date(2026, 3, 5), dry_run=True)
    assert stats["editorials_collected"] == 2
    assert stats["editorials_saved"] == 0
    assert svc.upserts == []


async def test_sync_respects_daily_cap_and_survives_bad_callback(web, monkeypatch):
    monkeypatch.setattr(fe, "FACTBOOK_MAX_EDITORIALS_PER_DAY", 1)

    def bad_callback(day, total):
        raise ValueError("callback bug")

    stats = await fe.sync_editorials_for_range(FakeFactbookService(), date(2026, 3, 5), date(2026, 3, 5), progress_callback=bad_callback)
    assert stats["editorials_collected"] == 1
