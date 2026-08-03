print('LOADING JWT_AUTH: ' + r'F:\Oatmeal AI\OatmealFarmNetwork Repo\Backend\jwt_auth.py')
print("LOADING JWT_AUTH FROM BACKEND FOLDER")
# --- jwt_auth.py --- (JWT authentication dependency for FastAPI)
import os
from jose import JWTError, jwt
from fastapi import HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

_bearer = HTTPBearer(auto_error=False)
_bearer_optional = HTTPBearer(auto_error=False)

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    """
    FastAPI dependency — validates the Bearer JWT locally using the shared
    SECRET_KEY. Returns the PeopleID as a string.

    Skips auth for OPTIONS preflight requests (returns 'preflight').
    Raises 401 if the token is missing, expired, or invalid.

    Usage in endpoint:
        @app.post("/chat")
        async def chat(request: ChatRequest, people_id: str = Depends(get_current_user)):
            ...
    """
    # Allow CORS preflight requests through without auth
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
    """
    Same as get_current_user but does NOT raise if the token is absent.
    Returns None for unauthenticated requests.

    Use this on endpoints that support both authenticated and anonymous access.
    """
    if request.method == "OPTIONS":
        return None
    if not credentials or not SECRET_KEY:
        return None
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        people_id = payload.get("sub")
        return str(people_id) if people_id else None
    except JWTError:
        return None
