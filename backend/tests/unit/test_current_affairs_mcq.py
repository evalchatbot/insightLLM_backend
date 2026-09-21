"""Daily current-affairs MCQ ingestion: scraping heuristics, MCQ validation and the full sync."""

from __future__ import annotations

from datetime import date

import pytest

from backend.ingest import current_affairs_mcq as ca
from support.fakes import FakeSupabaseClient, supabase_service_with

pytestmark = pytest.mark.unit

DAY = date(2026, 3, 5)


# ---------------------------------------------------------------- answer resolution / validation


def mcq(**overrides):
    base = {
        "question": "Which institution approved the latest budget support tranche for Pakistan?",
        "option_a": "IMF",
        "option_b": "World Bank",
        "option_c": "Asian Development Bank",
        "option_d": "State Bank",
        "correct_answer": "IMF",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("IMF", "IMF"), ("  World   Bank ", "World Bank"), ("c", "Asian Development Bank"), ("Option D", "State Bank"), ("2", "World Bank"), ("(B)", "World Bank"), ("Federal Reserve", None), ("", None)],
)
def test_resolve_correct_answer(answer, expected):
    assert ca._resolve_correct_answer(mcq(correct_answer=answer)) == expected


def test_resolve_rejects_duplicate_or_missing_options():
    assert ca._resolve_correct_answer(mcq(option_b="imf")) is None
    assert ca._resolve_correct_answer(mcq(option_d="")) is None


def test_quality_gate_accepts_specific_policy_question():
    assert ca._is_css_pms_quality_mcq(mcq(), {"headline": "IMF approves budget support"}) is True


@pytest.mark.parametrize(
    "override",
    [
        {"question": "Too short?"},
        {"question": "What was the outcome of this development in the national budget debate?"},
        {"option_c": "All of the above"},
        {"correct_answer": "None of these"},
        {"option_a": ""},
        {"question": "Which cricket team won the football and film award match at the stadium?", "option_a": "A", "option_b": "B", "option_c": "C", "option_d": "D", "correct_answer": "A"},
    ],
    ids=["short", "vague-stem", "all-of-above", "none-of-these", "empty-option", "off-topic"],
)
def test_quality_gate_rejects(override):
    assert ca._is_css_pms_quality_mcq(mcq(**override), {"headline": ""}) is False


def test_question_hash_is_normalised():
    a = ca._compute_question_hash("Q  one", "A", "B", "C", "D", "A")
    assert a == ca._compute_question_hash("q one ", "a", "b", "c", "d", "a")
    assert a != ca._compute_question_hash("Q one", "A", "B", "C", "D", "B")


def test_relevance_scores():
    assert ca._headline_relevance_score("", "pakistan") == 0
    policy = ca._headline_relevance_score("National Assembly passes federal budget legislation after long debate", "pakistan")
    sport = ca._headline_relevance_score("Cricket star signs film deal", "latest")
    assert policy >= 4
    assert sport < 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [('{"mcqs": []}', {"mcqs": []}), ('```json\n{"a": 1}\n```', {"a": 1}), ("[1]", None), ("", None)],
)
def test_extract_json_object(raw, expected):
    assert ca._extract_json_object(raw) == expected


# ---------------------------------------------------------------- scraping


SECTION_HTML = {
    "https://www.dawn.com/latest-news": """
        <h2><a href="/news/1001/imf">IMF approves budget support for Pakistan economy</a></h2>
        <a href="/news/1002/star">Cricket star signs new film deal with studio</a>
        <a href="/news/1009/short">Too short</a>
        <a href="https://example.com/news/1">Off-site story about Pakistan economy and budget</a>
    """,
    "https://www.dawn.com/pakistan": """
        <article><a href="/news/1003/na"><h3>National Assembly passes federal budget legislation</h3></a></article>
        <a href="/news/1004/senate">Senate debates constitution amendment on judicial reform</a>
        <a href="/news/1007/water">Supreme Court hears petition on provincial water dispute</a>
        <a href="/news/1001/imf?ref=pk">IMF approves budget support for Pakistan economy</a>
    """,
    "https://www.dawn.com/world": """
        <a href="/news/1005/talks">China and India agree to ceasefire talks at United Nations</a>
        <a href="/news/1006/climate">Climate finance deal reached at World Bank summit</a>
    """,
}


def test_extract_section_candidates_filters_and_dedupes():
    items = ca._extract_section_candidates("latest", "https://www.dawn.com/latest-news", SECTION_HTML["https://www.dawn.com/latest-news"])
    assert [i["source_url"] for i in items] == ["https://www.dawn.com/news/1001/imf", "https://www.dawn.com/news/1002/star"]
    assert all(len(i["id"]) == 12 and i["section"] == "latest" for i in items)


def test_extract_section_candidates_uses_nested_heading_text():
    (item,) = [i for i in ca._extract_section_candidates("pakistan", "https://www.dawn.com/pakistan", SECTION_HTML["https://www.dawn.com/pakistan"]) if "1003" in i["source_url"]]
    assert item["headline"] == "National Assembly passes federal budget legislation"


def test_fallback_mcqs_are_deterministic_per_day():
    cands = [{"id": f"id{i}", "headline": f"Headline number {i} about the federal budget", "section": "pakistan", "source_url": f"u{i}"} for i in range(5)]
    first = ca._fallback_generate_mcqs(cands, DAY, 3)
    assert first == ca._fallback_generate_mcqs(cands, DAY, 3)
    assert len(first) == 3
    for row in first:
        options = [row[k] for k in ("option_a", "option_b", "option_c", "option_d")]
        assert row["correct_answer"] in options and len(set(options)) == 4
        assert row["generation_mode"] == "fallback"
    assert ca._fallback_generate_mcqs(cands[:3], DAY, 3) == []  # need 4 distinct headlines


# ---------------------------------------------------------------- genre + counts


def test_genre_is_found_by_name_or_created():
    fake = FakeSupabaseClient(tables={"genres": [{"id": "g-ca", "name": "current affairs"}]})
    assert ca._ensure_current_affairs_genre_id(supabase_service_with(fake)) == "g-ca"

    empty = FakeSupabaseClient(tables={"genres": []})
    new_id = ca._ensure_current_affairs_genre_id(supabase_service_with(empty))
    assert empty.tables["genres"] == [{"name": "Current Affairs", "id": new_id}]


def test_explicit_genre_id_must_exist(monkeypatch):
    monkeypatch.setattr(ca, "CURRENT_AFFAIRS_GENRE_ID", "g-missing")
    with pytest.raises(RuntimeError, match="no matching row"):
        ca._ensure_current_affairs_genre_id(supabase_service_with(FakeSupabaseClient(tables={"genres": []})))
    monkeypatch.setattr(ca, "CURRENT_AFFAIRS_GENRE_ID", "g-1")
    fake = FakeSupabaseClient(tables={"genres": [{"id": "g-1", "name": "CA"}]})
    assert ca._ensure_current_affairs_genre_id(supabase_service_with(fake)) == "g-1"


def test_existing_count_reads_json_metadata():
    rows = [{"id": i, "genre_id": "g", "metadata": {"module": "current_affairs_dawn", "source_date": "2026-03-05"}} for i in range(3)]
    rows.append({"id": 9, "genre_id": "g", "metadata": {"module": "manual", "source_date": "2026-03-05"}})
    svc = supabase_service_with(FakeSupabaseClient(tables={"mcqs": rows}))
    assert ca._get_existing_mcq_count_for_date(svc, "g", DAY) == 3
    assert ca._get_existing_mcq_count_for_date(svc, "g", date(2026, 3, 6)) == 0


# ---------------------------------------------------------------- full daily sync


@pytest.fixture
def dawn(monkeypatch):
    pages = dict(SECTION_HTML)

    def fake_fetch(url):
        if url not in pages:
            raise RuntimeError(f"503 for {url}")
        return pages[url]

    monkeypatch.setattr(ca, "_fetch_html", fake_fetch)
    monkeypatch.setattr(ca.time, "sleep", lambda s: None)
    monkeypatch.setattr(ca, "GROK_API", None)  # heuristic selection + deterministic fallback MCQs
    return pages


async def test_sync_generates_validates_and_upserts(dawn):
    fake = FakeSupabaseClient(tables={"genres": [{"id": "g-ca", "name": "Current Affairs"}], "mcqs": []})
    stats = await ca.sync_current_affairs_mcqs_for_date(supabase_service_with(fake), DAY)

    assert stats["errors"] == []
    assert stats["sections_scanned"] == 3
    assert stats["candidate_headlines"] == 7  # the IMF story appears twice but is one URL
    assert stats["genre_id"] == "g-ca"
    saved = fake.tables["mcqs"]
    assert 0 < len(saved) == stats["mcqs_saved"] == stats["mcqs_generated"] <= ca.CURRENT_AFFAIRS_MCQS_PER_DAY
    for row in saved:
        assert row["genre_id"] == "g-ca"
        assert row["correct_answer"] in {row["option_a"], row["option_b"], row["option_c"], row["option_d"]}
        assert "Cricket star" not in " ".join([row["option_a"], row["option_b"], row["option_c"], row["option_d"]])
        assert row["metadata"]["module"] == "current_affairs_dawn"
        assert row["metadata"]["source_date"] == "2026-03-05"
    assert len({r["question_hash"] for r in saved}) == len(saved)
    assert fake.queries[-1].on_conflict == "question_hash"


async def test_sync_dry_run_writes_nothing(dawn):
    fake = FakeSupabaseClient(tables={"genres": [], "mcqs": []})
    stats = await ca.sync_current_affairs_mcqs_for_date(supabase_service_with(fake), DAY, dry_run=True)
    assert stats["mcqs_generated"] > 0
    assert stats["mcqs_saved"] == 0
    assert fake.tables == {"genres": [], "mcqs": []}


async def test_sync_skips_days_that_are_already_filled(dawn, monkeypatch):
    monkeypatch.setattr(ca, "CURRENT_AFFAIRS_MCQS_PER_DAY", 2)
    existing = [{"id": i, "genre_id": "g-ca", "metadata": {"module": "current_affairs_dawn", "source_date": "2026-03-05"}} for i in range(2)]
    fake = FakeSupabaseClient(tables={"genres": [{"id": "g-ca", "name": "Current Affairs"}], "mcqs": list(existing)})
    stats = await ca.sync_current_affairs_mcqs_for_date(supabase_service_with(fake), DAY)
    assert stats["existing_mcqs_for_date"] == 2
    assert stats["mcqs_saved"] == 0
    assert fake.tables["mcqs"] == existing


async def test_sync_records_section_failures_and_continues(dawn):
    del dawn["https://www.dawn.com/world"]
    fake = FakeSupabaseClient(tables={"genres": [{"id": "g-ca", "name": "Current Affairs"}], "mcqs": []})
    stats = await ca.sync_current_affairs_mcqs_for_date(supabase_service_with(fake), DAY)
    assert stats["sections_scanned"] == 2
    assert stats["errors"] == ["section=world fetch failed: 503 for https://www.dawn.com/world"]
    assert stats["mcqs_saved"] > 0


async def test_sync_with_nothing_scraped_returns_early(dawn):
    dawn.clear()
    fake = FakeSupabaseClient()
    stats = await ca.sync_current_affairs_mcqs_for_date(supabase_service_with(fake), DAY)
    assert stats["sections_scanned"] == 0 and len(stats["errors"]) == 3
    assert fake.queries == []
