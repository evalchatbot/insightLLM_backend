"""
In-process daily Fact Book scheduler.

Runs inside the always-on Railway backend so the digest self-populates every day
with no GitHub Actions / secrets setup. Fires at the configured local times, syncs
a rolling catch-up window (today - FACTBOOK_CATCHUP_DAYS .. today), and skips
already-synced articles by source hash so re-runs are cheap.

The actual sync does blocking HTTP, so it runs in a worker thread (its own event
loop) to keep the FastAPI event loop responsive.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, time as dtime, timedelta
from typing import List
from zoneinfo import ZoneInfo

from backend.config import (
    FACTBOOK_CATCHUP_DAYS,
    FACTBOOK_SCHEDULER_ENABLED,
    FACTBOOK_SCHEDULER_TIMES,
    FACTBOOK_TIMEZONE,
)
from backend.db.supabase_service import SupabaseService
from backend.ingest.factbook_editorials import sync_editorials_for_range
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)


def _timezone() -> ZoneInfo:
    try:
        return ZoneInfo(FACTBOOK_TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")


def _parse_times(spec: str) -> List[dtime]:
    out: List[dtime] = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            hh, mm = part.split(":")
            out.append(dtime(int(hh), int(mm)))
        except Exception:
            logger.warning(f"[FACTBOOK] Scheduler: bad time '{part}', ignoring")
    return out or [dtime(8, 30), dtime(14, 0)]


def _next_run(now: datetime, times: List[dtime]) -> datetime:
    tz = now.tzinfo
    candidates = []
    for t in times:
        c = datetime.combine(now.date(), t, tzinfo=tz)
        if c <= now:
            c = c + timedelta(days=1)
        candidates.append(c)
    return min(candidates)


async def _run_sync_once() -> None:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        logger.warning("[FACTBOOK] Scheduler: Supabase env missing; skipping run")
        return

    tz = _timezone()
    today = datetime.now(tz).date()
    start = today - timedelta(days=max(0, FACTBOOK_CATCHUP_DAYS))
    service = SupabaseService(supabase_url, supabase_key)

    logger.info(f"[FACTBOOK] Scheduler run: syncing {start.isoformat()} .. {today.isoformat()}")
    stats = await sync_editorials_for_range(
        supabase_service=service,
        start_date=start,
        end_date=today,
        dry_run=False,
    )
    logger.info(
        "[FACTBOOK] Scheduler run complete: "
        f"days={stats.get('days_processed')} saved={stats.get('editorials_saved')} "
        f"errors={len(stats.get('errors', []))}"
    )


def _run_sync_blocking() -> None:
    # Own event loop in this worker thread; blocking HTTP here does not stall the API loop.
    asyncio.run(_run_sync_once())


async def factbook_scheduler_loop() -> None:
    if not FACTBOOK_SCHEDULER_ENABLED:
        logger.info("[FACTBOOK] Scheduler disabled (FACTBOOK_SCHEDULER_ENABLED=false)")
        return

    tz = _timezone()
    times = _parse_times(FACTBOOK_SCHEDULER_TIMES)
    logger.info(
        "[FACTBOOK] Scheduler started; times="
        f"{[t.strftime('%H:%M') for t in times]} {FACTBOOK_TIMEZONE}, catchup={FACTBOOK_CATCHUP_DAYS}d"
    )

    # Let the app finish starting before the first (potentially long) sync.
    await asyncio.sleep(15)

    while True:
        now = datetime.now(tz)
        nxt = _next_run(now, times)
        sleep_s = max(30.0, (nxt - now).total_seconds())
        logger.info(f"[FACTBOOK] Scheduler next run at {nxt.isoformat()} (in {int(sleep_s)}s)")
        try:
            await asyncio.sleep(sleep_s)
        except asyncio.CancelledError:
            logger.info("[FACTBOOK] Scheduler cancelled")
            raise

        try:
            await asyncio.to_thread(_run_sync_blocking)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[FACTBOOK] Scheduler run failed: {exc}")

        # Guard against firing twice inside the same target minute.
        await asyncio.sleep(65)
