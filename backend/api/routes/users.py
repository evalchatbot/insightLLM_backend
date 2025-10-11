from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from pydantic import BaseModel
from backend.db.supabase_client import SupabaseDB
from backend.api.routes.auth import get_current_user, AuthUser  # adjust import path
import os

router = APIRouter(prefix="/user", tags=["user"])
db = SupabaseDB()

class UserSessionCreateRequest(BaseModel):
    # Optional: omit user_id from body; take it from token
    user_id: str | None = None

class UserSessionResponse(BaseModel):
    session_id: str
    user_id: str
    created_at: datetime

# Development-only endpoint for testing
class DevTokenRequest(BaseModel):
    user_id: str

class DevTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

@router.post("/dev-token", response_model=DevTokenResponse)
async def create_dev_token(req: DevTokenRequest):
    """
    Development-only endpoint to create test tokens.
    Remove this in production!
    """
    if os.getenv("ENVIRONMENT", "development") == "production":
        raise HTTPException(status_code=404, detail="Not found")
    
    # Create a simple JWT-like token for development
    # This is a simplified token - in real scenarios, use proper JWT libraries
    import json
    import base64
    
    payload = {
        "sub": req.user_id,
        "email": f"{req.user_id}@test.com",
        "aud": os.getenv("SUPABASE_AUDIENCE", "authenticated"),
        "iss": os.getenv("SUPABASE_ISSUER", "supabase"),
        "exp": 9999999999  # Far future expiry for testing
    }
    
    # This is a mock token for development only
    # In production, you'd get real tokens from Supabase/Clerk
    from jose import jwt
    from backend.config import SUPABASE_JWT_SECRET
    
    token = jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")
    
    return DevTokenResponse(access_token=token)

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
