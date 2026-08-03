# --- jwt_auth.py --- (JWT authentication dependency for FastAPI)
import os
from dotenv import load_dotenv
from jose import JWTError, jwt
from fastapi import HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

load_dotenv()

_bearer = HTTPBearer(auto_error=False)
_bearer_optional = HTTPBearer(auto_error=False)

# Must match the main OFN backend SECRET_KEY (auth.py). Treat blank env as unset.
_SECRET_RAW = (os.getenv("SECRET_KEY") or "").strip()
if _SECRET_RAW:
    SECRET_KEY = _SECRET_RAW
elif os.getenv("GOOGLE_CLOUD_PROJECT"):
    # Production must have SECRET_KEY set — never fall back to a dev default.
    SECRET_KEY = ""
else:
    SECRET_KEY = "change-me-in-production"
ALGORITHM = "HS256"


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    if request.method == "OPTIONS":
        return "preflight"
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header missing.")
    if not SECRET_KEY:
        raise HTTPException(status_code=500, detail="Auth not configured.")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        people_id = payload.get("sub")
        if people_id is None:
            raise HTTPException(status_code=401, detail="Token missing PeopleID.")
        return str(people_id)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")


def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(_bearer_optional),
) -> str | None:
    if request.method == "OPTIONS":
        return None
    if not credentials or not SECRET_KEY:
        return None
    try:
        payload = jwt.decode(
            credentials.credentials,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"verify_sub": False},
        )
        people_id = payload.get("sub")
        return str(people_id) if people_id else None
    except JWTError:
        return None