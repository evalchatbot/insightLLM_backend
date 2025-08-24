from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from pydantic import BaseModel
from backend.db.supabase_client import SupabaseDB
from backend.api.routes.auth import get_current_user, AuthUser  # adjust import path

router = APIRouter(prefix="/user", tags=["user"])
db = SupabaseDB()

class UserSessionCreateRequest(BaseModel):
    # Optional: omit user_id from body; take it from token
    user_id: str | None = None

class UserSessionResponse(BaseModel):
    session_id: str
    user_id: str
    created_at: datetime

@router.post("/session/create", response_model=UserSessionResponse)
async def create_session(
    req: UserSessionCreateRequest,
    user: AuthUser = Depends(get_current_user),
):
    user_id = user.user_id  # trust the token, not the body
    session_id = f"sess_{datetime.utcnow().timestamp()}_{user_id}"
    created_at = datetime.utcnow()
    db.insert("sessions", {"id": session_id, "user_id": user_id, "created_at": created_at.isoformat()})
    return UserSessionResponse(session_id=session_id, user_id=user_id, created_at=created_at)

@router.get("/session/{session_id}", response_model=UserSessionResponse)
async def get_session(
    session_id: str,
    user: AuthUser = Depends(get_current_user),  # protect if you want
):
    res = db.select("sessions", {"id": session_id})
    if not res.data:
        raise HTTPException(status_code=404, detail="Session not found")
    s = res.data[0]
    return UserSessionResponse(
        session_id=s["id"],
        user_id=s["user_id"],
        created_at=datetime.fromisoformat(s["created_at"]),
    )
