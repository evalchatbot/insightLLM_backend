"""Current Affairs daily automation: proxy-aware Dawn fetch and the in-process scheduler."""

from __future__ import annotations

import asyncio
from datetime import date, datetime

import pytest
import requests

from backend.ingest import current_affairs_mcq as ca
from backend.ingest import current_affairs_scheduler as sched
from support.fakes import FakeSupabaseClient, supabase_service_with

pytestmark = pytest.mark.unit

PROXY = "https://proxy.test/"
DAWN = "https://www.dawn.com/pakistan"


# ---------------------------------------------------------------- Dawn fetch


class _Resp:
    def __init__(self, status: int, text: str = "<html>ok</html>"):
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


@pytest.fixture
def http(monkeypatch):
    calls = []
    plan = {}

    def fake_get(url, timeout=None, headers=None):
        calls.append((url, dict(headers or {})))
        return plan.get(url, _Resp(200, f"<html>{url}</html>"))

    monkeypatch.setattr(ca.requests, "get", fake_get)
    monkeypatch.setattr(ca.time, "sleep", lambda s: None)
    monkeypatch.setattr(ca, "_throttle_fetch", lambda: None)
    return calls, plan


def test_fetch_goes_through_proxy_first(http, monkeypatch):
    calls, _ = http
    monkeypatch.setattr(ca, "CURRENT_AFFAIRS_FETCH_PROXY_PREFIX", PROXY)
    assert ca._fetch_html(DAWN) == f"<html>{PROXY}{DAWN}</html>"
    (url, headers), = calls
    assert url == PROXY + DAWN
    assert headers["X-Return-Format"] == "html"


def test_fetch_sends_proxy_token_when_configured(http, monkeypatch):
    calls, _ = http
    monkeypatch.setattr(ca, "CURRENT_AFFAIRS_FETCH_PROXY_PREFIX", PROXY)
    monkeypatch.setattr(ca, "FACTBOOK_FETCH_PROXY_TOKEN", "tok-123")
    ca._fetch_html(DAWN)
    assert calls[0][1]["Authorization"] == "Bearer tok-123"


def test_fetch_falls_back_to_direct_when_proxy_keeps_failing(http, monkeypatch):
    calls, plan = http
    monkeypatch.setattr(ca, "CURRENT_AFFAIRS_FETCH_PROXY_PREFIX", PROXY)
    plan[PROXY + DAWN] = _Resp(503)
    assert ca._fetch_html(DAWN) == f"<html>{DAWN}</html>"
    assert [u for u, _ in calls] == [PROXY + DAWN] * 3 + [DAWN]
    assert "X-Return-Format" not in calls[-1][1]


def test_fetch_is_direct_only_when_proxy_disabled(http, monkeypatch):
    calls, _ = http
    monkeypatch.setattr(ca, "CURRENT_AFFAIRS_FETCH_PROXY_PREFIX", "")
    ca._fetch_html(DAWN)
    assert [u for u, _ in calls] == [DAWN]


def test_fetch_raises_when_both_routes_fail(http, monkeypatch):
    _, plan = http
    monkeypatch.setattr(ca, "CURRENT_AFFAIRS_FETCH_PROXY_PREFIX", PROXY)
    plan[PROXY + DAWN] = _Resp(403)
    plan[DAWN] = _Resp(403)
    with pytest.raises(requests.HTTPError):
        ca._fetch_html(DAWN)


# ---------------------------------------------------------------- scheduler decisions


@pytest.mark.parametrize(
    ("clock", "spec", "due"),
    [("09:29", "09:30", False), ("09:30", "09:30", True), ("23:00", "09:30", True), ("12:00", "13:00,09:30", True), ("08:00", "13:00,09:30", False)],
)
def test_startup_run_due(clock, spec, due):
    hh, mm = map(int, clock.split(":"))
    assert sched._startup_run_due(datetime(2026, 9, 21, hh, mm), spec) is due


DAY = date(2026, 9, 21)


def _service_with_mcqs(n: int):
    meta = {"module": "current_affairs_dawn", "source_date": DAY.isoformat()}
    rows = [{"id": f"m{i}", "genre_id": "g-ca", "metadata": dict(meta)} for i in range(n)]
    return supabase_service_with(FakeSupabaseClient(tables={"genres": [{"id": "g-ca", "name": "Current Affairs"}], "mcqs": rows}))


def test_batch_missing_only_while_the_day_has_none():
    # One generation run per day: a partial batch (quality filters keep fewer than
    # CURRENT_AFFAIRS_MCQS_PER_DAY) must not re-trigger Grok on every restart.
    assert sched._batch_missing(_service_with_mcqs(0), DAY) is True
    assert sched._batch_missing(_service_with_mcqs(1), DAY) is False
    assert sched._batch_missing(_service_with_mcqs(5), DAY) is False


@pytest.fixture
def sync_spy(monkeypatch):
    calls = []

    async def fake_sync(supabase_service, target_date, dry_run=False):
        calls.append((target_date, dry_run))
        return {"sections_scanned": 3, "relevant_headlines": 5, "mcqs_saved": 20, "errors": []}

    monkeypatch.setattr(sched.ca, "sync_current_affairs_mcqs_for_date", fake_sync)
    return calls


async def test_run_skips_without_supabase_env(monkeypatch, sync_spy):
    monkeypatch.setattr(sched, "_supabase_service", lambda: None)
    await sched._run_sync_once()
    assert sync_spy == []


async def test_run_skips_a_full_day_before_any_fetch(monkeypatch, sync_spy):
    monkeypatch.setattr(sched, "_supabase_service", lambda: object())
    monkeypatch.setattr(sched, "_batch_missing", lambda service, day: False)
    await sched._run_sync_once()
    assert sync_spy == []


async def test_run_generates_todays_batch_when_missing(monkeypatch, sync_spy):
    monkeypatch.setattr(sched, "_supabase_service", lambda: object())
    monkeypatch.setattr(sched, "_batch_missing", lambda service, day: True)
    await sched._run_sync_once()
    assert len(sync_spy) == 1
    target_date, dry_run = sync_spy[0]
    assert dry_run is False
    assert target_date == datetime.now(sched._timezone()).date()


async def test_run_in_thread_swallows_errors(monkeypatch):
    def boom():
        raise RuntimeError("dawn down")

    monkeypatch.setattr(sched, "_run_sync_blocking", boom)
    await sched._run_in_thread()  # must not raise: the scheduler loop keeps going


# ---------------------------------------------------------------- loop


async def test_loop_does_nothing_when_disabled(monkeypatch):
    monkeypatch.setattr(sched, "CURRENT_AFFAIRS_SCHEDULER_ENABLED", False)

    async def never(*_):
        raise AssertionError("disabled scheduler must not sleep or run")

    monkeypatch.setattr(sched.asyncio, "sleep", never)
    await sched.current_affairs_scheduler_loop()


@pytest.mark.parametrize("due", [True, False])
async def test_loop_catches_up_on_startup_only_when_due(monkeypatch, due):
    monkeypatch.setattr(sched, "CURRENT_AFFAIRS_SCHEDULER_ENABLED", True)
    monkeypatch.setattr(sched, "_startup_run_due", lambda now, spec: due)
    runs = []

    async def fake_run():
        runs.append("run")

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:  # the initial settle delay, then the wait for the next slot
            raise asyncio.CancelledError

    monkeypatch.setattr(sched, "_run_in_thread", fake_run)
    monkeypatch.setattr(sched.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await sched.current_affairs_scheduler_loop()
    assert runs == (["run"] if due else [])
    assert 30 <= sleeps[1] <= 24 * 3600
