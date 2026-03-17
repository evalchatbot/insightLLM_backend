"""
CLI helper to run one-day Fact Book editorial sync.
"""

import argparse
import asyncio
import json
import os
from datetime import date

from backend.config import FACTBOOK_TIMEZONE
from backend.db.supabase_service import SupabaseService
from backend.ingest.factbook_editorials import sync_editorials_for_range


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run daily Fact Book sync")
    parser.add_argument("--date", default=date.today().isoformat(), help="Target date in YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Run fetch and summarize without DB upsert")
    return parser.parse_args()


async def _run() -> None:
    args = _parse_args()
    target_date = date.fromisoformat(args.date)

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_KEY")

    service = SupabaseService(supabase_url, supabase_key)
    stats = await sync_editorials_for_range(
        supabase_service=service,
        start_date=target_date,
        end_date=target_date,
        dry_run=args.dry_run,
    )

    print(json.dumps({"timezone": FACTBOOK_TIMEZONE, **stats}, indent=2))


if __name__ == "__main__":
    asyncio.run(_run())
