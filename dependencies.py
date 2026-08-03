"""Compatibility shim — re-exports the most common FastAPI dependencies."""
from database import get_db, get_raw_conn
from jwt_auth import get_current_user

__all__ = ["get_db", "get_raw_conn", "get_current_user"]
