"""
In-process daily Current Affairs MCQ scheduler.

Runs inside the always-on Railway backend (like the Fact Book scheduler) so the
Current Affairs genre gets a fresh batch every day without GitHub Actions secrets.
Fires at the configured local times for that day only, and once on startup when the
scheduled time has already passed but today has no batch yet (Railway restarts the
service on every deploy). A day that already has current-affairs MCQs is skipped before
any Dawn fetch or Grok call, so there is at most one generation run per day even though
the quality filters usually keep fewer than CURRENT_AFFAIRS_MCQS_PER_DAY questions.

The sync does blocking HTTP, so it runs in a worker thread with its own event loop.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime
from typing import Optional

from backend.config import (
    CURRENT_AFFAIRS_SCHEDULER_ENABLED,
    CURRENT_AFFAIRS_SCHEDULER_TIMES,
    FACTBOOK_TIMEZONE,
)
from backend.db.supabase_service import SupabaseService
from backend.ingest import current_affairs_mcq as ca
from backend.ingest.factbook_scheduler import _next_run, _parse_times, _timezone
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)


def _supabase_service() -> Optional[SupabaseService]:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        return None
    return SupabaseService(supabase_url, supabase_key)


def _batch_missing(service: SupabaseService, target_date: date) -> bool:
    genre_id = ca._ensure_current_affairs_genre_id(service)
    existing = ca._get_existing_mcq_count_for_date(
        supabase_service=service, genre_id=genre_id, target_date=target_date
    )
    return existing == 0


def _startup_run_due(now: datetime, times_spec: str) -> bool:
    """True when at least one of today's scheduled times has already passed."""
    return any(now.time() >= t for t in _parse_times(times_spec))


async def _run_sync_once() -> None:
    service = _supabase_service()
    if service is None:
        logger.warning("[CURRENT_AFFAIRS] Scheduler: Supabase env missing; skipping run")
        return

    today = datetime.now(_timezone()).date()
    if not _batch_missing(service, today):
        logger.info(f"[CURRENT_AFFAIRS] Scheduler: {today.isoformat()} already has its batch; skipping")
        return

    logger.info(f"[CURRENT_AFFAIRS] Scheduler run: generating MCQs for {today.isoformat()}")
    stats = await ca.sync_current_affairs_mcqs_for_date(
        supabase_service=service, target_date=today, dry_run=False
    )
    logger.info(
        "[CURRENT_AFFAIRS] Scheduler run complete: "
        f"sections={stats.get('sections_scanned')} headlines={stats.get('relevant_headlines')} "
        f"saved={stats.get('mcqs_saved')} errors={len(stats.get('errors', []))}"
    )


def _run_sync_blocking() -> None:
    # Own event loop in this worker thread; blocking HTTP here does not stall the API loop.
    asyncio.run(_run_sync_once())


async def _run_in_thread() -> None:
    try:
        await asyncio.to_thread(_run_sync_blocking)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[CURRENT_AFFAIRS] Scheduler run failed: {exc}")


async def current_affairs_scheduler_loop() -> None:
    if not CURRENT_AFFAIRS_SCHEDULER_ENABLED:
        logger.info("[CURRENT_AFFAIRS] Scheduler disabled (CURRENT_AFFAIRS_SCHEDULER_ENABLED=false)")
        return

    tz = _timezone()
    times = _parse_times(CURRENT_AFFAIRS_SCHEDULER_TIMES)
    logger.info(
        "[CURRENT_AFFAIRS] Scheduler started; times="
        f"{[t.strftime('%H:%M') for t in times]} {FACTBOOK_TIMEZONE}"
    )

    # Let the app (and the Fact Book scheduler's first tick) settle before any work.
    await asyncio.sleep(45)

    if _startup_run_due(datetime.now(tz), CURRENT_AFFAIRS_SCHEDULER_TIMES):
        await _run_in_thread()

    while True:
        now = datetime.now(tz)
        nxt = _next_run(now, times)
        sleep_s = max(30.0, (nxt - now).total_seconds())
        logger.info(f"[CURRENT_AFFAIRS] Scheduler next run at {nxt.isoformat()} (in {int(sleep_s)}s)")
        try:
            await asyncio.sleep(sleep_s)
        except asyncio.CancelledError:
            logger.info("[CURRENT_AFFAIRS] Scheduler cancelled")
            raise

        await _run_in_thread()

        # Guard against firing twice inside the same target minute.
        await asyncio.sleep(65)
