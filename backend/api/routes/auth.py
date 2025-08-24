from dataclasses import dataclass
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from backend.config import SUPABASE_JWT_SECRET, SUPABASE_ISSUER, SUPABASE_AUDIENCE

bearer = HTTPBearer(auto_error=False)

@dataclass
class AuthUser:
    user_id: str
    email: str | None = None

async def get_current_user(credentials: HTTPAuthorizationCredentials = Security(bearer)) -> AuthUser:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience=SUPABASE_AUDIENCE,
            issuer=SUPABASE_ISSUER,
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token missing subject")
    return AuthUser(user_id=sub, email=payload.get("email"))
