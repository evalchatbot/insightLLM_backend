from datetime import date, datetime
import os
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from backend.config import (
    FACTBOOK_AUTO_SYNC_COOLDOWN_SECONDS,
    FACTBOOK_AUTO_SYNC_TODAY_ON_EMPTY,
    FACTBOOK_MIN_DATE,
    FACTBOOK_SYNC_TOKEN,
    FACTBOOK_TIMEZONE,
)
from backend.db.supabase_service import SupabaseService
from backend.ingest.factbook_editorials import sync_editorials_for_range
from backend.ingest.factbook_topics import TOPIC_GROUPS
from backend.utils.logging_config import get_logger

router = APIRouter(prefix="/api/factbook", tags=["factbook"])
logger = get_logger(__name__)
_AUTO_SYNC_LAST_ATTEMPTS: Dict[str, datetime] = {}


def _today_in_factbook_tz() -> date:
    try:
        return datetime.now(ZoneInfo(FACTBOOK_TIMEZONE)).date()
    except Exception:
        return datetime.utcnow().date()


def _parse_iso_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}. Use YYYY-MM-DD format.")


def _verify_sync_token(x_factbook_token: Optional[str]) -> None:
    if not FACTBOOK_SYNC_TOKEN:
        raise HTTPException(status_code=500, detail="FACTBOOK_SYNC_TOKEN is not configured")

    if not x_factbook_token or x_factbook_token != FACTBOOK_SYNC_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid sync token")


def _should_trigger_auto_sync(target_date: date) -> bool:
    if not FACTBOOK_AUTO_SYNC_TODAY_ON_EMPTY:
        return False

    key = target_date.isoformat()
    now = datetime.utcnow()
    previous = _AUTO_SYNC_LAST_ATTEMPTS.get(key)

    if previous and (now - previous).total_seconds() < max(60, FACTBOOK_AUTO_SYNC_COOLDOWN_SECONDS):
        return False

    _AUTO_SYNC_LAST_ATTEMPTS[key] = now

    if len(_AUTO_SYNC_LAST_ATTEMPTS) > 14:
        stale_keys = sorted(_AUTO_SYNC_LAST_ATTEMPTS.keys())[:-7]
        for stale_key in stale_keys:
            _AUTO_SYNC_LAST_ATTEMPTS.pop(stale_key, None)

    return True


def get_supabase_service() -> SupabaseService:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        raise HTTPException(status_code=500, detail="Supabase environment variables are missing")

    return SupabaseService(supabase_url, supabase_key)


class EditorialSummary(BaseModel):
    id: Optional[str] = None
    publication_date: str
    headline: str
    summary_bullets: List[str] = Field(default_factory=list)
    takeaway: str
    summary_paragraph: str
    topic_domain: Optional[str] = "Other"
    thesis_statement: Optional[str] = ""


class EditorialListResponse(BaseModel):
    date: str
    count: int
    editorials: List[EditorialSummary]


class EditorialDateListResponse(BaseModel):
    month: Optional[str] = None
    count: int
    dates: List[str]


class TopicGroup(BaseModel):
    title: str
    topics: List[str]


class TopicListResponse(BaseModel):
    count: int
    groups: List[TopicGroup]
    counts: Dict[str, int] = Field(default_factory=dict)


class EditorialTopicListResponse(BaseModel):
    topic: str
    count: int
    editorials: List[EditorialSummary]


class DailySyncRequest(BaseModel):
    date: Optional[str] = None
    dry_run: bool = False


class BackfillSyncRequest(BaseModel):
    start_date: str = FACTBOOK_MIN_DATE
    end_date: Optional[str] = None
    dry_run: bool = False


@router.get("/editorials", response_model=EditorialListResponse)
async def get_editorials(
    background_tasks: BackgroundTasks,
    date_value: Optional[str] = Query(default=None, alias="date"),
    supabase_service: SupabaseService = Depends(get_supabase_service),
):
    target_date = _today_in_factbook_tz() if not date_value else _parse_iso_date(date_value, "date")
    rows = await supabase_service.get_factbook_editorials_by_date(target_date.isoformat())
    resolved_date = target_date

    if not date_value and not rows:
        latest_date = await supabase_service.get_latest_factbook_editorial_date()
        if latest_date:
            fallback_rows = await supabase_service.get_factbook_editorials_by_date(latest_date)
            if fallback_rows:
                rows = fallback_rows
                resolved_date = date.fromisoformat(latest_date)

        if _should_trigger_auto_sync(target_date):
            logger.info(f"[FACTBOOK] Auto-sync queued for {target_date.isoformat()} after empty read")
            background_tasks.add_task(
                sync_editorials_for_range,
                supabase_service=supabase_service,
                start_date=target_date,
                end_date=target_date,
                dry_run=False,
            )

    editorials = [EditorialSummary(**row) for row in rows]
    return EditorialListResponse(date=resolved_date.isoformat(), count=len(editorials), editorials=editorials)


@router.get("/editorial-dates", response_model=EditorialDateListResponse)
async def get_editorial_dates(
    month: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    supabase_service: SupabaseService = Depends(get_supabase_service),
):
    dates = await supabase_service.get_factbook_editorial_dates(month=month, limit=120)
    return EditorialDateListResponse(month=month, count=len(dates), dates=dates)


@router.get("/topics", response_model=TopicListResponse)
async def get_topics(
    supabase_service: SupabaseService = Depends(get_supabase_service),
):
    groups = [TopicGroup(title=title, topics=topics) for title, topics in TOPIC_GROUPS.items()]
    counts = await supabase_service.get_factbook_topic_counts()
    return TopicListResponse(count=sum(len(group.topics) for group in groups), groups=groups, counts=counts)


@router.get("/editorials/by-topic", response_model=EditorialTopicListResponse)
async def get_editorials_by_topic(
    topic: str = Query(..., min_length=2),
    limit: int = Query(120, ge=1, le=500),
    supabase_service: SupabaseService = Depends(get_supabase_service),
):
    rows = await supabase_service.get_factbook_editorials_by_topic(topic_domain=topic, limit=limit)
    editorials = [EditorialSummary(**row) for row in rows]
    return EditorialTopicListResponse(topic=topic, count=len(editorials), editorials=editorials)


@router.post("/sync/daily")
async def run_daily_sync(
    request: DailySyncRequest,
    x_factbook_token: Optional[str] = Header(default=None, alias="x-factbook-token"),
    supabase_service: SupabaseService = Depends(get_supabase_service),
) -> Dict[str, Any]:
    _verify_sync_token(x_factbook_token)

    target_date = _today_in_factbook_tz() if not request.date else _parse_iso_date(request.date, "date")

    logger.info(f"[FACTBOOK] Starting daily sync for {target_date.isoformat()} (dry_run={request.dry_run})")
    stats = await sync_editorials_for_range(
        supabase_service=supabase_service,
        start_date=target_date,
        end_date=target_date,
        dry_run=request.dry_run,
    )

    return {
        "mode": "daily",
        "dry_run": request.dry_run,
        **stats,
    }


@router.post("/sync/backfill")
async def run_backfill_sync(
    request: BackfillSyncRequest,
    x_factbook_token: Optional[str] = Header(default=None, alias="x-factbook-token"),
    supabase_service: SupabaseService = Depends(get_supabase_service),
) -> Dict[str, Any]:
    _verify_sync_token(x_factbook_token)

    start_date = _parse_iso_date(request.start_date, "start_date")
    end_date = _today_in_factbook_tz() if not request.end_date else _parse_iso_date(request.end_date, "end_date")

    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be greater than or equal to start_date")

    if (end_date - start_date).days > 400:
        raise HTTPException(status_code=400, detail="Requested backfill window is too large")

    logger.info(
        "[FACTBOOK] Starting backfill sync "
        f"from {start_date.isoformat()} to {end_date.isoformat()} (dry_run={request.dry_run})"
    )

    stats = await sync_editorials_for_range(
        supabase_service=supabase_service,
        start_date=start_date,
        end_date=end_date,
        dry_run=request.dry_run,
    )

    return {
        "mode": "backfill",
        "dry_run": request.dry_run,
        **stats,
    }
