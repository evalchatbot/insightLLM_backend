"""
CLI helper to run one-day Current Affairs MCQ sync.
"""

import argparse
import asyncio
import json
import os
from datetime import date

from backend.db.supabase_service import SupabaseService
from backend.ingest.current_affairs_mcq import sync_current_affairs_mcqs_for_date


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run daily Current Affairs MCQ sync")
    parser.add_argument("--date", default=date.today().isoformat(), help="Target date in YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Run scraping + generation without DB upsert")
    return parser.parse_args()


async def _run() -> None:
    args = _parse_args()
    target_date = date.fromisoformat(args.date)

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_KEY")

    service = SupabaseService(supabase_url, supabase_key)
    stats = await sync_current_affairs_mcqs_for_date(
        supabase_service=service,
        target_date=target_date,
        dry_run=args.dry_run,
    )

    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    asyncio.run(_run())
