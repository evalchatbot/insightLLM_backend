"""
CLI helper to run one-day Current Affairs MCQ sync.
"""

import argparse
import asyncio
import json
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from backend.db.supabase_service import SupabaseService
from backend.ingest.current_affairs_mcq import sync_current_affairs_mcqs_for_date


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run daily Current Affairs MCQ sync")
    parser.add_argument("--date", default=None, help="Single target date in YYYY-MM-DD")
    parser.add_argument("--start-date", default=None, help="Range start date in YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="Range end date in YYYY-MM-DD (default: today in Asia/Karachi)")
    parser.add_argument(
        "--max-days",
        type=int,
        default=int(os.getenv("CURRENT_AFFAIRS_MAX_DAYS_PER_RUN", "120")),
        help="Safety cap for number of days to process in one run",
    )
    parser.add_argument("--dry-run", action="store_true", help="Run scraping + generation without DB upsert")
    return parser.parse_args()


async def _run() -> None:
    args = _parse_args()

    try:
        today_karachi = datetime.now(ZoneInfo("Asia/Karachi")).date()
    except Exception:
        # Keep system local-date fallback if timezone support fails.
        today_karachi = date.today()

    if args.date:
        start_date = date.fromisoformat(args.date)
        end_date = start_date
    else:
        default_start = os.getenv("CURRENT_AFFAIRS_BACKFILL_START_DATE", today_karachi.isoformat())
        start_date = date.fromisoformat(args.start_date or default_start)
        end_date = date.fromisoformat(args.end_date) if args.end_date else today_karachi

    if end_date < start_date:
        raise RuntimeError("end-date must be greater than or equal to start-date")

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_KEY")

    service = SupabaseService(supabase_url, supabase_key)

    aggregate = {
        "mode": "range" if end_date != start_date else "single",
        "dry_run": bool(args.dry_run),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "days_processed": 0,
        "mcqs_generated": 0,
        "mcqs_saved": 0,
        "errors": [],
        "per_day": [],
    }

    current = start_date
    while current <= end_date:
        if aggregate["days_processed"] >= max(1, args.max_days):
            aggregate["errors"].append(
                f"Stopped early at max-days limit ({args.max_days}). Last attempted date: {current.isoformat()}"
            )
            break

        try:
            stats = await sync_current_affairs_mcqs_for_date(
                supabase_service=service,
                target_date=current,
                dry_run=args.dry_run,
            )
            aggregate["per_day"].append(stats)
            aggregate["mcqs_generated"] += int(stats.get("mcqs_generated", 0))
            aggregate["mcqs_saved"] += int(stats.get("mcqs_saved", 0))
        except Exception as exc:
            aggregate["errors"].append(f"{current.isoformat()} | {exc}")

        aggregate["days_processed"] += 1
        current = current + timedelta(days=1)

    print(json.dumps(aggregate, indent=2))

    if aggregate["errors"]:
        # Keep non-zero exit for visibility in automation while still processing as much as possible.
        raise RuntimeError("Current affairs range sync completed with errors")


if __name__ == "__main__":
    asyncio.run(_run())
