"""
/api/factbook contract tests.

The router runs against the REAL ``SupabaseService`` whose PostgREST client is an
in-memory fake, so query shapes (filters, ordering, month windows) are exercised too.
Dawn scraping (`sync_editorials_for_range`) and Grok are mocked at their boundaries.
"""

from __future__ import annotations

from datetime import date

import pytest

from support.fakes import FakeSupabaseClient, RecordingPost, grok_completion, make_requests_response, supabase_service_with

pytestmark = pytest.mark.api

TODAY = date(2026, 3, 10)


def editorial(pub: str, headline: str, topic: str = "Economy", **extra):
    row = {
        "id": f"id-{pub}-{headline[:5]}",
        "publication_date": pub,
        "headline": headline,
        "summary_bullets": ["b1", "b2", "b3"],
        "takeaway": "t",
        "summary_paragraph": "p",
        "topic_domain": topic,
        "thesis_statement": "thesis",
        "source_hash": f"hash-{pub}-{headline}",
        "source_url": "https://www.dawn.com/news/1",
    }
    row.update(extra)
    return row


@pytest.fixture
def factbook():
    from backend.api.routes import factbook as route

    return route


@pytest.fixture
def db(app, factbook, monkeypatch):
    fake = FakeSupabaseClient(
        tables={
            "factbook_editorials": [
                editorial("2026-03-05", "Zeta tax reforms"),
                editorial("2026-03-05", "Alpha IMF review"),
                editorial("2026-03-01", "Flood relief", topic="Climate & Environment"),
                editorial("2026-02-27", "Court backlog", topic="Law & Justice"),
            ]
        }
    )
    app.dependency_overrides[factbook.get_supabase_service] = lambda: supabase_service_with(fake)
    monkeypatch.setattr(factbook, "_today_in_factbook_tz", lambda: TODAY)
    monkeypatch.setattr(factbook, "_AUTO_SYNC_LAST_ATTEMPTS", {})
    return fake


@pytest.fixture
def sync_calls(factbook, monkeypatch):
    calls = []

    async def fake_sync(*, supabase_service, start_date, end_date, dry_run, **_):
        calls.append({"start": start_date, "end": end_date, "dry_run": dry_run})
        return {"days_processed": (end_date - start_date).days + 1, "editorials_saved": 0, "errors": []}

    monkeypatch.setattr(factbook, "sync_editorials_for_range", fake_sync)
    return calls


# ---------------------------------------------------------------- dependency


def test_missing_supabase_env_is_500(client, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    resp = client.get("/api/factbook/topics")
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Supabase environment variables are missing"


# ---------------------------------------------------------------- editorials by date


def test_editorials_for_explicit_date_sorted_by_headline(client, db, sync_calls):
    resp = client.get("/api/factbook/editorials", params={"date": "2026-03-05"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == "2026-03-05"
    assert body["count"] == 2
    assert [e["headline"] for e in body["editorials"]] == ["Alpha IMF review", "Zeta tax reforms"]
    assert set(body["editorials"][0]) == {
        "id", "publication_date", "headline", "summary_bullets", "takeaway",
        "summary_paragraph", "topic_domain", "thesis_statement",
    }
    assert sync_calls == []


def test_explicit_date_with_no_rows_does_not_fall_back_or_sync(client, db, sync_calls):
    body = client.get("/api/factbook/editorials", params={"date": "2026-01-02"}).json()
    assert body == {"date": "2026-01-02", "count": 0, "editorials": []}
    assert sync_calls == []


@pytest.mark.parametrize("bad", ["05-03-2026", "2026-13-01", "yesterday"])
def test_invalid_date_is_400(client, db, bad):
    resp = client.get("/api/factbook/editorials", params={"date": bad})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid date. Use YYYY-MM-DD format."


def test_today_empty_triggers_one_auto_sync_then_falls_back_to_latest(client, db, sync_calls):
    body = client.get("/api/factbook/editorials").json()
    assert sync_calls == [{"start": TODAY, "end": TODAY, "dry_run": False}]
    # nothing was synced for today -> newest available day is served instead
    assert body["date"] == "2026-03-05"
    assert body["count"] == 2

    # a second read inside the cooldown window must not hammer Dawn again
    client.get("/api/factbook/editorials")
    assert len(sync_calls) == 1


def test_auto_sync_results_are_served_when_it_finds_editorials(client, db, factbook, monkeypatch):
    async def sync_that_saves(*, supabase_service, start_date, end_date, dry_run, **_):
        db.tables["factbook_editorials"].append(editorial(start_date.isoformat(), "Fresh today"))
        return {"days_processed": 1}

    monkeypatch.setattr(factbook, "sync_editorials_for_range", sync_that_saves)
    body = client.get("/api/factbook/editorials").json()
    assert body["date"] == TODAY.isoformat()
    assert [e["headline"] for e in body["editorials"]] == ["Fresh today"]


def test_auto_sync_can_be_disabled(client, db, factbook, sync_calls, monkeypatch):
    monkeypatch.setattr(factbook, "FACTBOOK_AUTO_SYNC_TODAY_ON_EMPTY", False)
    body = client.get("/api/factbook/editorials").json()
    assert sync_calls == []
    assert body["date"] == "2026-03-05"


def test_empty_database_returns_today_with_no_editorials(client, db, sync_calls):
    db.tables["factbook_editorials"].clear()
    assert client.get("/api/factbook/editorials").json() == {"date": TODAY.isoformat(), "count": 0, "editorials": []}


# ---------------------------------------------------------------- dates / topics


def test_editorial_dates_for_month_are_unique_and_descending(client, db):
    body = client.get("/api/factbook/editorial-dates", params={"month": "2026-03"}).json()
    assert body == {"month": "2026-03", "count": 2, "dates": ["2026-03-05", "2026-03-01"]}
    q = db.queries[-1]
    assert ("publication_date", "gte", "2026-03-01") in q.filters
    assert ("publication_date", "lt", "2026-04-01") in q.filters


def test_editorial_dates_without_month(client, db):
    body = client.get("/api/factbook/editorial-dates").json()
    assert body["month"] is None
    assert body["dates"] == ["2026-03-05", "2026-03-01", "2026-02-27"]


@pytest.mark.parametrize("month", ["2026-3", "March", "2026-03-01"])
def test_editorial_dates_month_format_validated(client, db, month):
    assert client.get("/api/factbook/editorial-dates", params={"month": month}).status_code == 422


def test_topics_lists_taxonomy_with_counts(client, db):
    from backend.ingest.factbook_topics import ALL_TOPIC_DOMAINS

    body = client.get("/api/factbook/topics").json()
    assert [g["title"] for g in body["groups"]] == ["Pakistan Domains", "Global Domains", "Other"]
    assert body["count"] == len(ALL_TOPIC_DOMAINS)
    assert body["counts"] == {"Economy": 2, "Climate & Environment": 1, "Law & Justice": 1}


def test_editorials_by_topic_filters_and_limits(client, db):
    body = client.get("/api/factbook/editorials/by-topic", params={"topic": "Economy", "limit": 1}).json()
    assert body["topic"] == "Economy"
    assert body["count"] == 1
    assert body["editorials"][0]["topic_domain"] == "Economy"
    q = db.queries[-1]
    assert ("topic_domain", "eq", "Economy") in q.filters
    assert q.limit == 1


def test_editorials_by_topic_all_is_unfiltered(client, db):
    body = client.get("/api/factbook/editorials/by-topic", params={"topic": "all"}).json()
    assert body["count"] == 4
    assert [e["publication_date"] for e in body["editorials"]] == sorted(
        (e["publication_date"] for e in body["editorials"]), reverse=True
    )


@pytest.mark.parametrize("params", [{}, {"topic": "E"}, {"topic": "Economy", "limit": 0}, {"topic": "Economy", "limit": 501}])
def test_editorials_by_topic_validation(client, db, params):
    assert client.get("/api/factbook/editorials/by-topic", params=params).status_code == 422


# ---------------------------------------------------------------- digest


DIGEST_BODY = {
    "editorials": [
        {
            "publication_date": "2026-03-01",
            "headline": "IMF review",
            "summary_bullets": ["Pakistan clears review."],
            "takeaway": "Keep reforms",
            "summary_paragraph": "Longer text",
        },
        {
            "publication_date": "2026-03-04",
            "headline": "Flood levy",
            "summary_bullets": [],
            "takeaway": "Tax fairly",
            "summary_paragraph": "More text",
        },
    ]
}


def test_digest_requires_editorials(client):
    resp = client.post("/api/factbook/digest", json={"editorials": []})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "No editorials supplied for digest generation"


def test_digest_validates_editorial_shape(client):
    resp = client.post("/api/factbook/digest", json={"editorials": [{"headline": "missing fields"}]})
    assert resp.status_code == 422


def test_digest_end_to_end_with_mocked_grok(client, monkeypatch):
    import json

    from backend.ingest import factbook_digest
    from backend.utils import grok_client

    model_json = {
        "digest_title": "Economy under pressure",
        "topic": "Economy",
        "cards": [
            {
                "headline": "IMF review cleared",
                "bullets": ["One.", "Two.", "Three is dropped."],
                "takeaway_label": "recommendation",
                "takeaway_text": "Stay the course.",
                "date": "01 Mar 2026",
            },
            {"headline": "No bullets -> dropped", "bullets": []},
        ],
        "figures": [{"figure": "Rs75bn", "label": "Levy size", "context": "why", "date": "04 Mar 2026"}, {"figure": ""}],
    }
    post = RecordingPost(make_requests_response(200, grok_completion("```json\n" + json.dumps(model_json) + "\n```")))
    monkeypatch.setattr(factbook_digest, "GROK_API", "test-grok-key")
    monkeypatch.setattr(grok_client.requests, "post", post)

    resp = client.post("/api/factbook/digest", json={**DIGEST_BODY, "source_name": "Dawn Editorials"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["digest_title"] == "Economy under pressure"
    assert body["date_range"] == "01 Mar 2026 - 04 Mar 2026"
    assert body["source_name"] == "Dawn Editorials"
    assert len(body["cards"]) == 1
    assert body["cards"][0]["bullets"] == ["One.", "Two."]
    assert body["cards"][0]["takeaway_label"] == "Recommendation:"
    assert body["figures"] == [{"figure": "Rs75bn", "label": "Levy size", "context": "why", "date": "04 Mar 2026"}]

    (call,) = post.calls
    assert call["url"].endswith("/chat/completions")
    assert call["headers"]["Authorization"] == "Bearer test-grok-key"
    sent = json.loads(call["data"])
    assert sent["response_format"] == {"type": "json_object"}
    user_payload = json.loads(sent["messages"][1]["content"])
    assert user_payload["editorial_count"] == 2


@pytest.mark.parametrize(
    ("exc", "status"),
    [(ValueError("bad input"), 400), (RuntimeError("Could not parse digest JSON"), 502)],
)
def test_digest_error_mapping(client, factbook, monkeypatch, exc, status):
    def boom(*args, **kwargs):
        raise exc

    monkeypatch.setattr(factbook, "generate_factbook_digest", boom)
    resp = client.post("/api/factbook/digest", json=DIGEST_BODY)
    assert resp.status_code == status
    assert str(exc) in resp.json()["detail"]


def test_digest_without_grok_key_is_502(client, monkeypatch):
    from backend.ingest import factbook_digest

    monkeypatch.setattr(factbook_digest, "GROK_API", None)
    resp = client.post("/api/factbook/digest", json=DIGEST_BODY)
    assert resp.status_code == 502
    assert "GROK_API is not configured" in resp.json()["detail"]


# ---------------------------------------------------------------- token-guarded sync


SYNC_ENDPOINTS = [
    ("/api/factbook/sync/daily", {"date": "2026-03-01"}),
    ("/api/factbook/sync/backfill", {"start_date": "2026-03-01", "end_date": "2026-03-03"}),
]


@pytest.mark.parametrize(("path", "payload"), SYNC_ENDPOINTS)
@pytest.mark.parametrize("headers", [{}, {"x-factbook-token": "wrong"}, {"x-factbook-token": ""}])
def test_sync_rejects_missing_or_wrong_token(client, db, sync_calls, path, payload, headers):
    resp = client.post(path, json=payload, headers=headers)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid sync token"
    assert sync_calls == []


@pytest.mark.parametrize(("path", "payload"), SYNC_ENDPOINTS)
def test_sync_refuses_when_token_not_configured(client, db, factbook, sync_calls, monkeypatch, path, payload):
    monkeypatch.setattr(factbook, "FACTBOOK_SYNC_TOKEN", None)
    resp = client.post(path, json=payload, headers={"x-factbook-token": "anything"})
    assert resp.status_code == 500
    assert resp.json()["detail"] == "FACTBOOK_SYNC_TOKEN is not configured"
    assert sync_calls == []


def test_daily_sync_with_valid_token(client, db, sync_calls):
    resp = client.post(
        "/api/factbook/sync/daily",
        json={"date": "2026-03-01", "dry_run": True},
        headers={"x-factbook-token": "factbook-test-token"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"mode": "daily", "dry_run": True, "days_processed": 1, "editorials_saved": 0, "errors": []}
    assert sync_calls == [{"start": date(2026, 3, 1), "end": date(2026, 3, 1), "dry_run": True}]


def test_daily_sync_defaults_to_today(client, db, sync_calls):
    client.post("/api/factbook/sync/daily", json={}, headers={"x-factbook-token": "factbook-test-token"})
    assert sync_calls == [{"start": TODAY, "end": TODAY, "dry_run": False}]


def test_backfill_sync_range(client, db, sync_calls):
    resp = client.post(
        "/api/factbook/sync/backfill",
        json={"start_date": "2026-03-01", "end_date": "2026-03-03"},
        headers={"x-factbook-token": "factbook-test-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "backfill"
    assert resp.json()["days_processed"] == 3


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"start_date": "2026-03-05", "end_date": "2026-03-01"}, "end_date must be greater than or equal to start_date"),
        ({"start_date": "2024-01-01", "end_date": "2026-03-01"}, "Requested backfill window is too large"),
        ({"start_date": "2026/03/01"}, "Invalid start_date. Use YYYY-MM-DD format."),
        ({"start_date": "2026-03-01", "end_date": "soon"}, "Invalid end_date. Use YYYY-MM-DD format."),
    ],
)
def test_backfill_validation(client, db, sync_calls, payload, detail):
    resp = client.post("/api/factbook/sync/backfill", json=payload, headers={"x-factbook-token": "factbook-test-token"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == detail
    assert sync_calls == []
