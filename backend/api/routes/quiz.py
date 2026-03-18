from datetime import date, timedelta
import os
import random
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from backend.config import CURRENT_AFFAIRS_SYNC_TOKEN
from backend.db.supabase_service import SupabaseService
from backend.ingest.current_affairs_mcq import sync_current_affairs_mcqs_for_date
from backend.utils.logging_config import get_logger

router = APIRouter(prefix="/quiz", tags=["quiz"])
logger = get_logger(__name__)


def _parse_iso_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}. Use YYYY-MM-DD format.") from exc


def _verify_current_affairs_sync_token(token: Optional[str]) -> None:
    if not CURRENT_AFFAIRS_SYNC_TOKEN:
        raise HTTPException(status_code=500, detail="CURRENT_AFFAIRS_SYNC_TOKEN is not configured")
    if not token or token != CURRENT_AFFAIRS_SYNC_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid sync token")


def get_supabase_service() -> SupabaseService:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        raise HTTPException(status_code=500, detail="Supabase environment variables are missing")

    return SupabaseService(supabase_url, supabase_key)


class DailyCurrentAffairsSyncRequest(BaseModel):
    date: Optional[str] = None
    dry_run: bool = False


class BackfillCurrentAffairsSyncRequest(BaseModel):
    start_date: str
    end_date: Optional[str] = None
    dry_run: bool = False


@router.get("/genres", response_model=List[Dict[str, Any]])
def get_quiz_genres(
    supabase_service: SupabaseService = Depends(get_supabase_service),
):
    """Fetch available quiz genres/subjects."""
    try:
        result = (
            supabase_service.supabase
            .table("genres")
            .select("id,name,description")
            .order("name", desc=False)
            .execute()
        )

        if hasattr(result, "error") and result.error:
            raise RuntimeError(f"Supabase query error: {result.error}")

        return result.data if result.data else []
    except Exception as exc:
        logger.error(f"[QUIZ] Failed to fetch genres: {exc}")
        raise HTTPException(status_code=500, detail="Failed to fetch genres") from exc


@router.get("/mcqs", response_model=List[Dict[str, Any]])
def get_random_mcqs(
    genre_id: str = Query(..., description="Genre ID"),
    limit: int = Query(20, ge=1, le=200),
    randomize: bool = Query(True, alias="random"),
    supabase_service: SupabaseService = Depends(get_supabase_service),
):
    """Fetch MCQs for a genre and return up to `limit` items."""
    try:
        result = (
            supabase_service.supabase
            .table("mcqs")
            .select("id,question,option_a,option_b,option_c,option_d,correct_answer,genre_id,metadata,created_at")
            .eq("genre_id", genre_id)
            .limit(max(200, limit * 4))
            .execute()
        )

        if hasattr(result, "error") and result.error:
            raise RuntimeError(f"Supabase query error: {result.error}")

        mcqs = result.data if result.data else []
        if not mcqs:
            raise HTTPException(status_code=404, detail="No MCQs found for this genre.")

        if randomize:
            return random.sample(mcqs, min(limit, len(mcqs)))

        return mcqs[:limit]
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[QUIZ] Failed to fetch MCQs for genre {genre_id}: {exc}")
        raise HTTPException(status_code=500, detail="Failed to fetch MCQs") from exc


@router.post("/sync/current-affairs/daily")
async def run_current_affairs_daily_sync(
    request: DailyCurrentAffairsSyncRequest,
    x_current_affairs_token: Optional[str] = Header(default=None, alias="x-current-affairs-token"),
    supabase_service: SupabaseService = Depends(get_supabase_service),
) -> Dict[str, Any]:
    _verify_current_affairs_sync_token(x_current_affairs_token)
    target_date = date.today() if not request.date else _parse_iso_date(request.date, "date")

    logger.info(
        f"[CURRENT_AFFAIRS] Starting daily MCQ sync for {target_date.isoformat()} (dry_run={request.dry_run})"
    )
    stats = await sync_current_affairs_mcqs_for_date(
        supabase_service=supabase_service,
        target_date=target_date,
        dry_run=request.dry_run,
    )

    return {
        "mode": "daily",
        "dry_run": request.dry_run,
        **stats,
    }


@router.post("/sync/current-affairs/backfill")
async def run_current_affairs_backfill_sync(
    request: BackfillCurrentAffairsSyncRequest,
    x_current_affairs_token: Optional[str] = Header(default=None, alias="x-current-affairs-token"),
    supabase_service: SupabaseService = Depends(get_supabase_service),
) -> Dict[str, Any]:
    _verify_current_affairs_sync_token(x_current_affairs_token)

    start_date = _parse_iso_date(request.start_date, "start_date")
    end_date = date.today() if not request.end_date else _parse_iso_date(request.end_date, "end_date")

    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be greater than or equal to start_date")

    if (end_date - start_date).days > 60:
        raise HTTPException(status_code=400, detail="Requested backfill window is too large")

    aggregate: Dict[str, Any] = {
        "mode": "backfill",
        "dry_run": request.dry_run,
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
        try:
            stats = await sync_current_affairs_mcqs_for_date(
                supabase_service=supabase_service,
                target_date=current,
                dry_run=request.dry_run,
            )
            aggregate["per_day"].append(stats)
            aggregate["mcqs_generated"] += int(stats.get("mcqs_generated", 0))
            aggregate["mcqs_saved"] += int(stats.get("mcqs_saved", 0))
        except Exception as exc:
            aggregate["errors"].append(f"{current.isoformat()} | {exc}")

        aggregate["days_processed"] += 1
        current = current + timedelta(days=1)

    return aggregate
