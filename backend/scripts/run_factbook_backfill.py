"""
CLI helper to backfill Dawn editorials into Fact Book.
"""

import argparse
import asyncio
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict

from backend.db.supabase_service import SupabaseService
from backend.ingest.factbook_editorials import sync_editorials_for_range


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill Fact Book editorials from Dawn")
    parser.add_argument("--start-date", default="2026-01-01", help="Backfill start date in YYYY-MM-DD")
    parser.add_argument("--end-date", default=date.today().isoformat(), help="Backfill end date in YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Run fetch and summarize without DB upsert")
    parser.add_argument(
        "--progress-log",
        default="",
        help="Optional JSONL path for day-by-day progress logs (default: logs/factbook_backfill_*.jsonl)",
    )
    return parser.parse_args()


def _resolve_progress_log_path(
    provided_path: str,
    start_date: date,
    end_date: date,
    dry_run: bool,
) -> str:
    if provided_path:
        return os.path.abspath(provided_path)

    mode = "dryrun" if dry_run else "write"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    file_name = f"factbook_backfill_{start_date.isoformat()}_{end_date.isoformat()}_{mode}_{timestamp}.jsonl"
    return os.path.abspath(os.path.join("logs", file_name))


def _write_progress_line(file_handle, payload: Dict[str, Any]) -> None:
    file_handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    file_handle.flush()


async def _run() -> None:
    args = _parse_args()

    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)

    if end_date < start_date:
        raise ValueError("end-date must be greater than or equal to start-date")

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_KEY")

    progress_log_path = _resolve_progress_log_path(
        provided_path=args.progress_log,
        start_date=start_date,
        end_date=end_date,
        dry_run=args.dry_run,
    )
    Path(progress_log_path).parent.mkdir(parents=True, exist_ok=True)

    print(
        f"[FACTBOOK] Starting backfill | start={start_date.isoformat()} "
        f"end={end_date.isoformat()} dry_run={args.dry_run}"
    )
    print(f"[FACTBOOK] Progress log: {progress_log_path}")

    service = SupabaseService(supabase_url, supabase_key)
    with open(progress_log_path, "a", encoding="utf-8") as progress_file:
        _write_progress_line(
            progress_file,
            {
                "event": "start",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "dry_run": args.dry_run,
            },
        )

        def progress_callback(day_stats: Dict[str, Any], aggregate_stats: Dict[str, Any]) -> None:
            _write_progress_line(
                progress_file,
                {
                    "event": "day_complete",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "day": day_stats,
                    "totals": {
                        "days_processed": aggregate_stats.get("days_processed", 0),
                        "editorials_collected": aggregate_stats.get("editorials_collected", 0),
                        "editorials_saved": aggregate_stats.get("editorials_saved", 0),
                        "duplicates_skipped": aggregate_stats.get("duplicates_skipped", 0),
                        "summaries_generated": aggregate_stats.get("summaries_generated", 0),
                        "candidate_links_checked": aggregate_stats.get("candidate_links_checked", 0),
                    },
                },
            )

            print(
                "[FACTBOOK] "
                f"{day_stats['date']} "
                f"links={day_stats['candidate_links']} "
                f"scanned={day_stats['articles_scanned']} "
                f"kept={day_stats['editorials_collected']} "
                f"dup={day_stats['duplicates_skipped']} "
                f"saved={day_stats['editorials_saved']} "
                f"errors={len(day_stats['errors'])}"
            )

        stats = await sync_editorials_for_range(
            supabase_service=service,
            start_date=start_date,
            end_date=end_date,
            dry_run=args.dry_run,
            progress_callback=progress_callback,
        )

        _write_progress_line(
            progress_file,
            {
                "event": "complete",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                "stats": stats,
            },
        )

    print(json.dumps({"progress_log": progress_log_path, **stats}, indent=2))


if __name__ == "__main__":
    asyncio.run(_run())
