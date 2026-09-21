"""
SupabaseService / SupabaseDB query logic against the in-memory PostgREST fake, including the
"topic columns not migrated yet" fallback paths used by the Fact Book.
"""

from __future__ import annotations

import pytest

from support.fakes import FakeSupabaseClient, supabase_db_with, supabase_service_with

pytestmark = pytest.mark.unit

MISSING_TOPIC_COLUMN = Exception('{"code":"42703","message":"column factbook_editorials.topic_domain does not exist"}')


def row(pub, headline, **extra):
    base = {
        "id": f"{pub}-{headline}",
        "publication_date": pub,
        "headline": headline,
        "summary_bullets": ["first bullet"],
        "takeaway": "takeaway",
        "summary_paragraph": "paragraph",
        "source_hash": f"h-{pub}-{headline}",
    }
    base.update(extra)
    return base


def selects_topic_columns(q):
    return q.op == "select" and "topic_domain" in q.columns


@pytest.fixture
def fake():
    return FakeSupabaseClient(
        tables={
            "factbook_editorials": [
                row("2026-03-05", "Inflation eases", topic_domain="Economy", thesis_statement="t"),
                row("2026-03-05", "Court reform", topic_domain="Law & Justice", thesis_statement="t"),
                row("2026-12-31", "Year ender", topic_domain="Other", thesis_statement=""),
                row("2027-01-02", "New year budget", topic_domain="", thesis_statement="x"),
            ]
        }
    )


@pytest.fixture
def svc(fake):
    return supabase_service_with(fake)


# ---------------------------------------------------------------- reads


async def test_editorials_by_date(svc):
    rows = await svc.get_factbook_editorials_by_date("2026-03-05")
    assert [r["headline"] for r in rows] == ["Court reform", "Inflation eases"]


async def test_editorials_by_date_fallback_when_topic_columns_missing(svc, fake):
    fake.fail_when(selects_topic_columns, MISSING_TOPIC_COLUMN)
    rows = await svc.get_factbook_editorials_by_date("2026-03-05")
    by_headline = {r["headline"]: r for r in rows}
    assert by_headline["Inflation eases"]["topic_domain"] == "Economy"  # inferred from keywords
    assert by_headline["Court reform"]["topic_domain"] == "Law & Justice"
    assert by_headline["Court reform"]["thesis_statement"] == "first bullet"


async def test_editorials_by_date_other_errors_return_empty(svc, fake):
    fake.fail_when(lambda q: True, RuntimeError("connection refused"))
    assert await svc.get_factbook_editorials_by_date("2026-03-05") == []


async def test_editorials_by_topic_limit_is_clamped(svc, fake):
    await svc.get_factbook_editorials_by_topic("all", limit=10_000)
    assert fake.queries[-1].limit == 500
    await svc.get_factbook_editorials_by_topic("Economy", limit=0)
    assert fake.queries[-1].limit == 1
    assert ("topic_domain", "eq", "Economy") in fake.queries[-1].filters


async def test_editorials_by_topic_fallback_filters_by_inferred_topic(svc, fake):
    fake.fail_when(selects_topic_columns, MISSING_TOPIC_COLUMN)
    rows = await svc.get_factbook_editorials_by_topic("Economy")
    assert [r["headline"] for r in rows] == ["New year budget", "Inflation eases"]
    assert all(r["topic_domain"] == "Economy" for r in rows)


async def test_topic_counts_and_fallback(svc, fake):
    assert await svc.get_factbook_topic_counts() == {"Economy": 1, "Law & Justice": 1, "Other": 2}
    fake.fail_when(selects_topic_columns, MISSING_TOPIC_COLUMN)
    assert await svc.get_factbook_topic_counts() == {"Economy": 2, "Law & Justice": 1, "Other": 1}


async def test_topic_columns_available(svc, fake):
    assert await svc.factbook_topic_columns_available() is True
    fake.fail_when(selects_topic_columns, MISSING_TOPIC_COLUMN)
    assert await svc.factbook_topic_columns_available() is False


@pytest.mark.parametrize(
    ("month", "lower", "upper"),
    [("2026-03", "2026-03-01", "2026-04-01"), ("2026-12", "2026-12-01", "2027-01-01"), ("2024-02", "2024-02-01", "2024-03-01")],
)
async def test_editorial_dates_month_window(svc, fake, month, lower, upper):
    await svc.get_factbook_editorial_dates(month=month)
    q = fake.queries[-1]
    assert ("publication_date", "gte", lower) in q.filters
    assert ("publication_date", "lt", upper) in q.filters


async def test_editorial_dates_are_unique_desc_and_limited(svc):
    assert await svc.get_factbook_editorial_dates() == ["2027-01-02", "2026-12-31", "2026-03-05"]
    assert await svc.get_factbook_editorial_dates(limit=2) == ["2027-01-02", "2026-12-31"]


async def test_editorial_dates_bad_month_returns_empty(svc):
    assert await svc.get_factbook_editorial_dates(month="2026-13") == []


async def test_latest_date_and_source_hashes(svc, fake):
    assert await svc.get_latest_factbook_editorial_date() == "2027-01-02"
    assert await svc.get_factbook_source_hashes_by_date("2026-03-05") == {"h-2026-03-05-Inflation eases", "h-2026-03-05-Court reform"}
    fake.tables["factbook_editorials"].clear()
    assert await svc.get_latest_factbook_editorial_date() is None


async def test_topic_labeling_selects_unlabelled_rows(svc, fake):
    rows = await svc.get_factbook_editorials_for_topic_labeling("2026-01-01", "2027-12-31", limit=10)
    assert [r["headline"] for r in rows] == ["Year ender", "New year budget"]
    assert fake.queries[-1].range == (0, 9)
    everything = await svc.get_factbook_editorials_for_topic_labeling("2026-01-01", "2027-12-31", only_unlabeled=False)
    assert len(everything) == 4


# ---------------------------------------------------------------- writes


def new_record(headline, **extra):
    rec = {
        "publication_date": "2026-03-06",
        "headline": headline,
        "summary_bullets": ["b"],
        "takeaway": "t",
        "summary_paragraph": "p",
        "topic_domain": "Economy",
        "thesis_statement": "th",
        "source_url": "https://www.dawn.com/news/9",
        "source_hash": f"hash-{headline}",
    }
    rec.update(extra)
    return rec


async def test_upsert_is_idempotent_on_source_hash(svc, fake):
    assert await svc.upsert_factbook_editorials([new_record("A"), new_record("B")]) == 2
    assert await svc.upsert_factbook_editorials([new_record("A", takeaway="updated")]) == 1
    table = fake.tables["factbook_editorials"]
    stored = [r for r in table if r["source_hash"] == "hash-A"]
    assert len(stored) == 1 and stored[0]["takeaway"] == "updated"
    assert fake.queries[-1].on_conflict == "source_hash"
    assert stored[0]["source_name"] == "dawn"


async def test_upsert_retries_without_topic_columns(svc, fake):
    fake.fail_when(lambda q: q.op == "upsert" and "topic_domain" in q.payload[0], MISSING_TOPIC_COLUMN)
    assert await svc.upsert_factbook_editorials([new_record("A")]) == 1
    (stored,) = [r for r in fake.tables["factbook_editorials"] if r["source_hash"] == "hash-A"]
    assert "topic_domain" not in stored and "thesis_statement" not in stored


async def test_upsert_edge_cases(svc, fake):
    assert await svc.upsert_factbook_editorials([]) == 0
    fake.fail_when(lambda q: q.op == "upsert", RuntimeError("503"))
    assert await svc.upsert_factbook_editorials([new_record("A")]) == 0


async def test_topic_label_updates(svc, fake):
    n = await svc.upsert_factbook_topic_labels([{"id": "2026-12-31-Year ender", "topic_domain": "Economy", "thesis_statement": "x"}, {"id": "ghost"}])
    assert n == 2  # an empty representation still counts as updated
    (updated,) = [r for r in fake.tables["factbook_editorials"] if r["id"] == "2026-12-31-Year ender"]
    assert updated["topic_domain"] == "Economy"
    fake.fail_when(lambda q: q.op == "update", MISSING_TOPIC_COLUMN)
    assert await svc.upsert_factbook_topic_labels([{"id": "x"}]) == 0
    assert await svc.upsert_factbook_topic_labels([]) == 0


# ---------------------------------------------------------------- users / books helpers


def test_get_valid_user_id():
    fake = FakeSupabaseClient(tables={"users": [{"id": "alice"}, {"id": "bob"}]})
    svc = supabase_service_with(fake)
    assert svc.get_valid_user_id("bob") == "bob"
    assert svc.get_valid_user_id(None) == "alice"
    fake.tables["users"].clear()
    assert svc.get_valid_user_id("bob") is None
    fake.fail_when(lambda q: True, RuntimeError("down"))
    assert svc.get_valid_user_id("bob") is None


async def test_books_queries():
    fake = FakeSupabaseClient(tables={"books": [{"id": "b1", "genre": "Law"}, {"id": "b2", "genre": "IR"}]})
    svc = supabase_service_with(fake)
    assert await svc.get_book_by_id("b2") == {"id": "b2", "genre": "IR"}
    assert await svc.get_book_by_id("zz") is None
    assert [b["id"] for b in await svc.get_books_by_genre("Law")] == ["b1"]
    assert await svc.get_books_by_ids([]) == []
    assert {b["id"] for b in await svc.get_books_by_ids(["b1", "b2"])} == {"b1", "b2"}


def test_supabase_db_crud_helpers():
    fake = FakeSupabaseClient(tables={"t": [{"id": 1, "g": "a"}, {"id": 2, "g": "b"}, {"id": 3, "g": "a"}]})
    db = supabase_db_with(fake)
    assert [r["id"] for r in db.select("t", {"g": "a"}).data] == [1, 3]
    assert [r["id"] for r in db.select("t", {"id": [2, 3]}).data] == [2, 3]
    db.insert("t", {"id": 4, "g": "c"})
    db.delete("t", {"id": 1})
    assert sorted(r["id"] for r in db.select("t").data) == [2, 3, 4]
    assert db.supabase is fake
