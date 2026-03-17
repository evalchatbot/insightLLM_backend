"""
Backfill topic labels and thesis statements for Fact Book editorials.
"""

import argparse
import asyncio
import os
from datetime import date

# Keep script output clean by default (numeric progress lines only).
os.environ.setdefault("ENABLE_LOGGING", "false")
os.environ.setdefault("LOG_LEVEL", "ERROR")

from backend.db.supabase_service import SupabaseService
from backend.ingest.factbook_editorials import build_thesis_statement, classify_editorial_topic_domain


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify Fact Book editorials by topic")
    parser.add_argument("--start-date", default="2026-01-01", help="Start date in YYYY-MM-DD")
    parser.add_argument("--end-date", default=date.today().isoformat(), help="End date in YYYY-MM-DD")
    parser.add_argument("--batch-size", type=int, default=40, help="Rows per classification batch")
    parser.add_argument("--force", action="store_true", help="Reclassify all rows, not only missing labels")
    parser.add_argument("--dry-run", action="store_true", help="Classify but do not write updates")
    return parser.parse_args()


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

    service = SupabaseService(supabase_url, supabase_key)

    if not await service.factbook_topic_columns_available():
        raise RuntimeError(
            "Factbook topic columns are not available. Apply migration 011_add_factbook_topic_columns.sql first."
        )

    offset = 0
    scanned = 0
    labeled = 0
    updated_total = 0

    while True:
        rows = await service.get_factbook_editorials_for_topic_labeling(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            limit=max(1, args.batch_size),
            offset=offset,
            only_unlabeled=not args.force,
        )

        if not rows:
            break

        updates = []
        for row in rows:
            scanned += 1
            summary_payload = {
                "summary_bullets": row.get("summary_bullets") or [],
                "takeaway": row.get("takeaway") or "",
                "summary_paragraph": row.get("summary_paragraph") or "",
            }
            topic_domain = classify_editorial_topic_domain(row.get("headline") or "", summary_payload)
            thesis_statement = build_thesis_statement(row.get("headline") or "", summary_payload)

            updates.append(
                {
                    "id": row["id"],
                    "topic_domain": topic_domain,
                    "thesis_statement": thesis_statement,
                }
            )
            labeled += 1

        if not args.dry_run:
            updated_count = await service.upsert_factbook_topic_labels(updates)
            updated_total += updated_count

        print(
            "FACTBOOK_TOPIC_PROGRESS "
            f"offset={offset} batch={len(rows)} scanned={scanned} "
            f"labeled={labeled} updated={updated_total}"
        )

        offset += max(1, args.batch_size)

    print(
        "FACTBOOK_TOPIC_DONE "
        f"scanned={scanned} labeled={labeled} updated={updated_total} "
        f"dry_run={int(args.dry_run)} force={int(args.force)}"
    )


if __name__ == "__main__":
    asyncio.run(_run())
