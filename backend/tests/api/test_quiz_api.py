"""/quiz contract tests (genres, MCQs, current-affairs sync) against a fake Supabase."""

from __future__ import annotations

from datetime import date

import pytest

from support.fakes import FakeSupabaseClient, supabase_service_with

pytestmark = pytest.mark.api

TOKEN = {"x-current-affairs-token": "current-affairs-test-token"}


def mcq(i: int, genre: str = "g-1"):
    return {
        "id": f"m{i}",
        "question": f"Q{i}?",
        "option_a": "a",
        "option_b": "b",
        "option_c": "c",
        "option_d": "d",
        "correct_answer": "a",
        "genre_id": genre,
        "metadata": {},
        "created_at": "2026-03-01T00:00:00",
        "internal_note": "never exposed",
    }


@pytest.fixture
def quiz():
    from backend.api.routes import quiz as route

    return route


@pytest.fixture
def db(app, quiz):
    fake = FakeSupabaseClient(
        tables={
            "genres": [
                {"id": "g-2", "name": "Pakistan Affairs", "description": "PA", "secret": 1},
                {"id": "g-1", "name": "Current Affairs", "description": "CA", "secret": 1},
            ],
            "mcqs": [mcq(i) for i in range(30)] + [mcq(100, genre="g-2")],
        }
    )
    app.dependency_overrides[quiz.get_supabase_service] = lambda: supabase_service_with(fake)
    return fake


def test_genres_sorted_and_projected(client, db):
    resp = client.get("/quiz/genres")
    assert resp.status_code == 200
    assert resp.json() == [
        {"id": "g-1", "name": "Current Affairs", "description": "CA"},
        {"id": "g-2", "name": "Pakistan Affairs", "description": "PA"},
    ]


def test_genres_empty_table_is_empty_list(client, db):
    db.tables["genres"].clear()
    assert client.get("/quiz/genres").json() == []


def test_genres_db_error_is_500(client, db):
    db.fail_when(lambda q: q.table == "genres", RuntimeError("connection reset"))
    resp = client.get("/quiz/genres")
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to fetch genres"


def test_mcqs_random_sample_respects_limit_and_genre(client, db):
    resp = client.get("/quiz/mcqs", params={"genre_id": "g-1", "limit": 5})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 5
    assert len({i["id"] for i in items}) == 5
    assert all(i["genre_id"] == "g-1" for i in items)
    assert "internal_note" not in items[0]
    q = db.queries[-1]
    assert ("genre_id", "eq", "g-1") in q.filters
    assert q.limit == 200  # over-fetches max(200, limit*4) to randomise from


def test_mcqs_without_random_are_first_n_in_db_order(client, db):
    items = client.get("/quiz/mcqs", params={"genre_id": "g-1", "limit": 3, "random": "false"}).json()
    assert [i["id"] for i in items] == ["m0", "m1", "m2"]


def test_mcqs_limit_larger_than_pool_returns_all(client, db):
    assert len(client.get("/quiz/mcqs", params={"genre_id": "g-2", "limit": 50}).json()) == 1


def test_mcqs_unknown_genre_is_404(client, db):
    resp = client.get("/quiz/mcqs", params={"genre_id": "nope"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "No MCQs found for this genre."


@pytest.mark.parametrize("params", [{}, {"genre_id": "g-1", "limit": 0}, {"genre_id": "g-1", "limit": 201}])
def test_mcqs_validation(client, db, params):
    assert client.get("/quiz/mcqs", params=params).status_code == 422


def test_mcqs_db_error_is_500(client, db):
    db.fail_when(lambda q: q.table == "mcqs", RuntimeError("timeout"))
    resp = client.get("/quiz/mcqs", params={"genre_id": "g-1"})
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to fetch MCQs"


# ---------------------------------------------------------------- current-affairs sync


@pytest.fixture
def sync_calls(quiz, monkeypatch):
    calls = []

    async def fake_sync(*, supabase_service, target_date, dry_run):
        calls.append((target_date, dry_run))
        if target_date == date(2026, 3, 2):
            raise RuntimeError("Dawn returned 503")
        return {"date": target_date.isoformat(), "mcqs_generated": 4, "mcqs_saved": 0 if dry_run else 4}

    monkeypatch.setattr(quiz, "sync_current_affairs_mcqs_for_date", fake_sync)
    return calls


@pytest.mark.parametrize("path", ["/quiz/sync/current-affairs/daily", "/quiz/sync/current-affairs/backfill"])
@pytest.mark.parametrize("headers", [{}, {"x-current-affairs-token": "nope"}])
def test_current_affairs_sync_requires_token(client, db, sync_calls, path, headers):
    resp = client.post(path, json={"start_date": "2026-03-01"}, headers=headers)
    assert resp.status_code == 401
    assert sync_calls == []


def test_current_affairs_sync_token_not_configured(client, db, quiz, sync_calls, monkeypatch):
    monkeypatch.setattr(quiz, "CURRENT_AFFAIRS_SYNC_TOKEN", "")
    resp = client.post("/quiz/sync/current-affairs/daily", json={}, headers=TOKEN)
    assert resp.status_code == 500
    assert resp.json()["detail"] == "CURRENT_AFFAIRS_SYNC_TOKEN is not configured"


def test_current_affairs_daily(client, db, sync_calls):
    resp = client.post("/quiz/sync/current-affairs/daily", json={"date": "2026-03-01", "dry_run": True}, headers=TOKEN)
    assert resp.status_code == 200
    assert resp.json() == {"mode": "daily", "dry_run": True, "date": "2026-03-01", "mcqs_generated": 4, "mcqs_saved": 0}
    assert sync_calls == [(date(2026, 3, 1), True)]


def test_current_affairs_daily_bad_date(client, db, sync_calls):
    resp = client.post("/quiz/sync/current-affairs/daily", json={"date": "01/03/2026"}, headers=TOKEN)
    assert resp.status_code == 400


def test_current_affairs_backfill_aggregates_and_isolates_day_errors(client, db, sync_calls):
    resp = client.post(
        "/quiz/sync/current-affairs/backfill",
        json={"start_date": "2026-03-01", "end_date": "2026-03-03"},
        headers=TOKEN,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["days_processed"] == 3
    assert body["mcqs_generated"] == 8
    assert body["mcqs_saved"] == 8
    assert body["errors"] == ["2026-03-02 | Dawn returned 503"]
    assert [d["date"] for d in body["per_day"]] == ["2026-03-01", "2026-03-03"]


@pytest.mark.parametrize(
    "payload",
    [
        {"start_date": "2026-03-05", "end_date": "2026-03-01"},
        {"start_date": "2026-01-01", "end_date": "2026-03-15"},  # > 60 days
    ],
)
def test_current_affairs_backfill_window_validation(client, db, sync_calls, payload):
    assert client.post("/quiz/sync/current-affairs/backfill", json=payload, headers=TOKEN).status_code == 400
    assert sync_calls == []


def test_current_affairs_backfill_requires_start_date(client, db, sync_calls):
    assert client.post("/quiz/sync/current-affairs/backfill", json={}, headers=TOKEN).status_code == 422
