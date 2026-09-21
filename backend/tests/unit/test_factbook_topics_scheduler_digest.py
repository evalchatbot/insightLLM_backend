"""Fact Book: topic taxonomy/classification, in-process scheduler math, digest normalisation."""

from __future__ import annotations

import json
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.ingest import factbook_digest as fd
from backend.ingest import factbook_editorials as fe
from backend.ingest import factbook_scheduler as fs
from backend.ingest.factbook_topics import (
    ALL_TOPIC_DOMAINS,
    OTHER_TOPIC_DOMAIN,
    TOPIC_GROUPS,
    keyword_fallback_topic_domain,
    normalize_topic_domain,
)
from support.fakes import RecordingPost, grok_completion, make_requests_response

pytestmark = pytest.mark.unit

# ====================================================================== topics


def test_taxonomy_is_consistent():
    flattened = [t for topics in TOPIC_GROUPS.values() for t in topics]
    assert flattened == ALL_TOPIC_DOMAINS
    assert len(set(ALL_TOPIC_DOMAINS)) == len(ALL_TOPIC_DOMAINS)
    assert ALL_TOPIC_DOMAINS[-1] == OTHER_TOPIC_DOMAIN


@pytest.mark.parametrize(
    ("value", "expected"),
    [("economy", "Economy"), ("  GLOBAL SECURITY ", "Global Security"), ("Economics", "Other"), ("", "Other"), (None, "Other")],
)
def test_normalize_topic_domain(value, expected):
    assert normalize_topic_domain(value) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("IMF programme and budget deficit", "Economy"),
        ("Floods displace thousands", "Climate & Environment"),
        ("Polio drive resumes in hospitals", "Health"),
        ("NATO expansion", "Global Security"),
        ("", "Other"),
        ("A quiet week", "Other"),
    ],
)
def test_keyword_fallback_topic(text, expected):
    assert keyword_fallback_topic_domain(text) == expected


@pytest.mark.xfail(
    strict=True,
    reason="BUG: keyword_fallback_topic_domain matches substrings, so 'ai' inside 'said'/'again' classifies "
    "health/other stories as Technology (and 'law' matches 'flaw', 'tax' matches 'taxi', ...)",
)
def test_keyword_fallback_matches_whole_words_only():
    assert keyword_fallback_topic_domain("The minister said hospitals need more doctors") == "Health"


def test_topic_classifier_without_grok_uses_keywords(monkeypatch):
    monkeypatch.setattr(fe, "GROK_API", None)
    assert fe.classify_editorial_topic_domain("Budget woes", {"summary_bullets": []}) == "Economy"


def test_topic_classifier_uses_valid_model_answer(monkeypatch):
    from backend.utils import grok_client

    monkeypatch.setattr(fe, "GROK_API", "k")
    monkeypatch.setattr(
        grok_client.requests, "post", RecordingPost(make_requests_response(200, grok_completion('{"topic_domain": "global economy"}')))
    )
    assert fe.classify_editorial_topic_domain("Budget woes", {}) == "Global Economy"


def test_topic_classifier_falls_back_on_api_error(monkeypatch):
    from backend.utils import grok_client

    monkeypatch.setattr(fe, "GROK_API", "k")
    monkeypatch.setattr(grok_client.requests, "post", RecordingPost(make_requests_response(429, {"error": "rate limited"})))
    assert fe.classify_editorial_topic_domain("Budget woes", {}) == "Economy"


@pytest.mark.xfail(
    strict=True,
    reason="BUG: classify_editorial_topic_domain returns 'Other' for an unknown/empty model label because "
    "normalize_topic_domain never returns '' -> the keyword fallback after `if topic:` is dead code",
)
def test_topic_classifier_falls_back_to_keywords_on_unknown_label(monkeypatch):
    from backend.utils import grok_client

    monkeypatch.setattr(fe, "GROK_API", "k")
    monkeypatch.setattr(
        grok_client.requests, "post", RecordingPost(make_requests_response(200, grok_completion('{"topic_domain": "Economics"}')))
    )
    assert fe.classify_editorial_topic_domain("Budget woes and inflation", {}) == "Economy"


# ====================================================================== scheduler


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("08:30", [dtime(8, 30)]),
        ("08:30, 14:00", [dtime(8, 30), dtime(14, 0)]),
        ("7:5", [dtime(7, 5)]),
        ("08:30,25:00,noon,", [dtime(8, 30)]),  # invalid entries ignored
        ("", [dtime(8, 30), dtime(14, 0)]),  # nothing valid -> built-in defaults
        ("garbage", [dtime(8, 30), dtime(14, 0)]),
        (None, [dtime(8, 30), dtime(14, 0)]),
    ],
)
def test_parse_times(spec, expected):
    assert fs._parse_times(spec) == expected


KHI = ZoneInfo("Asia/Karachi")


@pytest.mark.parametrize(
    ("now", "times", "expected"),
    [
        (datetime(2026, 3, 5, 7, 0, tzinfo=KHI), [dtime(8, 30)], datetime(2026, 3, 5, 8, 30, tzinfo=KHI)),
        (datetime(2026, 3, 5, 8, 30, tzinfo=KHI), [dtime(8, 30)], datetime(2026, 3, 6, 8, 30, tzinfo=KHI)),
        (datetime(2026, 3, 5, 9, 0, tzinfo=KHI), [dtime(8, 30), dtime(14, 0)], datetime(2026, 3, 5, 14, 0, tzinfo=KHI)),
        (datetime(2026, 3, 5, 15, 0, tzinfo=KHI), [dtime(14, 0), dtime(8, 30)], datetime(2026, 3, 6, 8, 30, tzinfo=KHI)),
        (datetime(2026, 12, 31, 23, 59, tzinfo=KHI), [dtime(0, 0)], datetime(2027, 1, 1, 0, 0, tzinfo=KHI)),
    ],
)
def test_next_run(now, times, expected):
    nxt = fs._next_run(now, times)
    assert nxt == expected
    assert nxt > now
    assert nxt - now <= timedelta(days=1)


def test_timezone_falls_back_to_utc(monkeypatch):
    monkeypatch.setattr(fs, "FACTBOOK_TIMEZONE", "Not/AZone")
    assert fs._timezone() == ZoneInfo("UTC")
    monkeypatch.setattr(fs, "FACTBOOK_TIMEZONE", "Asia/Karachi")
    assert fs._timezone() == KHI


async def test_scheduler_loop_returns_immediately_when_disabled(monkeypatch):
    monkeypatch.setattr(fs, "FACTBOOK_SCHEDULER_ENABLED", False)

    async def never(*_):
        raise AssertionError("must not sleep when disabled")

    monkeypatch.setattr(fs.asyncio, "sleep", never)
    assert await fs.factbook_scheduler_loop() is None


async def test_scheduler_loop_runs_sync_after_sleeping_until_next_slot(monkeypatch):
    import asyncio

    sleeps, runs = [], []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 3:  # initial 15s, wait-until-slot, post-run guard -> stop the loop
            raise asyncio.CancelledError

    async def fake_to_thread(fn):
        runs.append(fn)

    monkeypatch.setattr(fs, "FACTBOOK_SCHEDULER_ENABLED", True)
    monkeypatch.setattr(fs.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(fs.asyncio, "to_thread", fake_to_thread)
    with pytest.raises(asyncio.CancelledError):
        await fs.factbook_scheduler_loop()
    assert sleeps[0] == 15
    assert 30 <= sleeps[1] <= 86400
    assert sleeps[2] == 65
    assert runs == [fs._run_sync_blocking]


async def test_run_sync_once_skips_without_supabase_env(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    called = []

    async def fake_sync(**kwargs):
        called.append(kwargs)

    monkeypatch.setattr(fs, "sync_editorials_for_range", fake_sync)
    await fs._run_sync_once()
    assert called == []


async def test_run_sync_once_syncs_catchup_window(monkeypatch):
    calls = []

    async def fake_sync(**kwargs):
        calls.append(kwargs)
        return {"days_processed": 3, "editorials_saved": 5, "errors": []}

    class FakeService:
        def __init__(self, url, key):
            self.url, self.key = url, key

    monkeypatch.setattr(fs, "sync_editorials_for_range", fake_sync)
    monkeypatch.setattr(fs, "SupabaseService", FakeService)
    monkeypatch.setattr(fs, "FACTBOOK_CATCHUP_DAYS", 2)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    await fs._run_sync_once()
    (call,) = calls
    assert (call["end_date"] - call["start_date"]).days == 2
    assert call["dry_run"] is False
    assert call["supabase_service"].key == "service-role"


# ====================================================================== digest


def test_iso_to_display_and_ranges():
    assert fd._iso_to_display("2026-03-05") == "05 Mar 2026"
    assert fd._iso_to_display("2026-03-05T10:00:00") == "05 Mar 2026"
    assert fd._iso_to_display("not a date") == "not a date"
    assert fd._format_date_range(["2026-03-05", "2026-03-01", "", "2026-03-05T09:00:00"]) == "01 Mar 2026 - 05 Mar 2026"
    assert fd._format_date_range(["2026-03-05"]) == "05 Mar 2026"
    assert fd._format_date_range([]) == ""


def test_slim_editorials_fills_defaults():
    (slim,) = fd._slim_editorials([{"publication_date": "2026-03-05T11:00:00", "headline": None, "extra": "dropped"}])
    assert slim == {
        "publication_date": "2026-03-05",
        "headline": "",
        "topic_domain": "Other",
        "summary_bullets": [],
        "takeaway": "",
        "summary_paragraph": "",
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"cards": []}', {"cards": []}),
        ('```json\n{"cards": [1]}\n```', {"cards": [1]}),
        ('```\n{"cards": [2]}\n```', {"cards": [2]}),
        ('Here you go: {"cards": [3]} -- done', {"cards": [3]}),
        ("```json\nnot json at all\n```", None),
        ("", None),
        (None, None),
    ],
)
def test_extract_json(text, expected):
    assert fd._extract_json(text) == expected


def test_coerce_digest_normalises_cards_and_figures():
    parsed = {
        "cards": [
            {"headline": " A ", "bullets": [" one ", "", "two", "three"], "takeaway_label": "recommendation", "takeaway_text": " do it "},
            {"headline": "B", "bullets": ["x"], "takeaway_label": "Summary:"},
            {"headline": "no bullets", "bullets": []},
            {"bullets": ["only bullet"]},
        ],
        "figures": [{"figure": " 8.6% ", "label": "Inflation"}, {"figure": "", "label": "dropped"}, {"label": "no figure"}],
    }
    out = fd._coerce_digest(parsed, date_range="01 Mar 2026", source_name="Dawn Editorials")
    assert out["digest_title"] == "Fact Book Digest"
    assert out["topic"] == "Current Affairs"
    assert out["source_name"] == "Dawn Editorials"
    assert out["date_range"] == "01 Mar 2026"
    assert [c["headline"] for c in out["cards"]] == ["A", "B", "Untitled"]
    assert out["cards"][0]["bullets"] == ["one", "two"]
    assert out["cards"][0]["takeaway_label"] == "Recommendation:"
    assert out["cards"][0]["takeaway_text"] == "do it"
    assert out["cards"][1]["takeaway_label"] == "Takeaway:"
    assert out["figures"] == [{"figure": "8.6%", "label": "Inflation", "context": "", "date": ""}]


def test_coerce_digest_handles_missing_sections():
    out = fd._coerce_digest({}, date_range="", source_name="S")
    assert out["cards"] == [] and out["figures"] == []


@pytest.fixture
def grok_post(monkeypatch):
    from backend.utils import grok_client

    def install(*responses):
        post = RecordingPost(*responses)
        monkeypatch.setattr(fd, "GROK_API", "test-key")
        monkeypatch.setattr(grok_client.requests, "post", post)
        return post

    return install


EDITORIALS = [{"publication_date": "2026-03-01", "headline": "H1"}, {"publication_date": "2026-03-02", "headline": "H2"}]


def test_generate_digest_happy_path(grok_post):
    content = json.dumps({"digest_title": "T", "cards": [{"headline": "C", "bullets": ["b1", "b2"], "date": "01 Mar 2026"}]})
    post = grok_post(make_requests_response(200, grok_completion(content)))
    out = fd.generate_factbook_digest(EDITORIALS, source_name="Dawn")
    assert out["digest_title"] == "T"
    assert out["date_range"] == "01 Mar 2026 - 02 Mar 2026"
    payload = json.loads(post.calls[0]["data"])
    assert payload["model"] == fd.FACTBOOK_GROK_MODEL
    assert payload["max_output_tokens"] == 6000
    assert payload["messages"][0]["content"] == fd.DIGEST_SYSTEM_PROMPT


def test_generate_digest_requires_input_and_key(monkeypatch):
    with pytest.raises(ValueError):
        fd.generate_factbook_digest([])
    monkeypatch.setattr(fd, "GROK_API", None)
    with pytest.raises(RuntimeError, match="GROK_API is not configured"):
        fd.generate_factbook_digest(EDITORIALS)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("I cannot help with that.", "Could not parse digest JSON"),
        ('{"cards": [{"headline": "x", "bullets": []}]}', "produced no cards"),
    ],
)
def test_generate_digest_rejects_unusable_model_output(grok_post, content, message):
    grok_post(make_requests_response(200, grok_completion(content)))
    with pytest.raises(RuntimeError, match=message):
        fd.generate_factbook_digest(EDITORIALS)


def test_generate_digest_surfaces_api_errors(grok_post):
    from backend.utils.grok_client import GrokError

    grok_post(make_requests_response(401, {"error": "bad key"}))
    with pytest.raises(GrokError, match="401"):
        fd.generate_factbook_digest(EDITORIALS)


def test_scheduler_run_blocking_uses_its_own_loop(monkeypatch):
    ran = []

    async def fake_once():
        ran.append(True)

    monkeypatch.setattr(fs, "_run_sync_once", fake_once)
    fs._run_sync_blocking()
    assert ran == [True]


def test_scheduler_today_uses_configured_zone():
    # Sanity check on the zone maths the scheduler relies on (UTC+5, no DST).
    utc = datetime(2026, 3, 5, 20, 0, tzinfo=timezone.utc)
    assert utc.astimezone(KHI).date() == date(2026, 3, 6)
