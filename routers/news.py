"""News feed served from the Charlie Firestore `news_articles` collection.

A scheduled job elsewhere syncs RSS feeds into Firestore; this router only
reads, so the frontend `/app/news` page can hit the same backend as the rest
of the site instead of the production Node service.
"""
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/news", tags=["news"])

_DATABASE = os.getenv("FIRESTORE_DATABASE", "charlie")
_COLLECTION = "news_articles"

_db_client = None
_db_init_failed = False


def _get_db():
    global _db_client, _db_init_failed
    if _db_client is not None or _db_init_failed:
        return _db_client
    try:
        from google.cloud import firestore
        project = os.getenv("GOOGLE_CLOUD_PROJECT") or None
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        credentials = None
        if creds_path and os.path.exists(creds_path):
            from google.oauth2 import service_account
            credentials = service_account.Credentials.from_service_account_file(
                creds_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        _db_client = firestore.Client(
            project=project, database=_DATABASE, credentials=credentials
        )
    except Exception as e:
        _db_init_failed = True
        print(f"[news] Firestore init failed: {e}")
        _db_client = None
    return _db_client


try:
    from ftfy import fix_text as _ftfy_fix
except Exception:
    _ftfy_fix = None


def _unmojibake(value):
    """Repair the UTF-8 → Latin-1 → UTF-8 round-trip mojibake the news sync
    pipeline leaves in titles/descriptions/content (e.g. "USDAâ€™s" →
    "USDA's"). No-op if ftfy isn't installed or value isn't a string."""
    if not isinstance(value, str) or not value or _ftfy_fix is None:
        return value
    try:
        return _ftfy_fix(value)
    except Exception:
        return value


# Fields known to come from third-party RSS/HTML sources where mojibake appears.
_TEXT_FIELDS = ("title", "description", "content", "summary", "source", "author")


def _serialize(doc_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"id": doc_id}
    out = dict(data)
    out.pop("embedding", None)
    pub = out.get("pubDate")
    if isinstance(pub, datetime):
        out["pubDate"] = pub.astimezone(timezone.utc).isoformat()
    synced = out.get("syncedAt")
    if isinstance(synced, datetime):
        out["syncedAt"] = synced.astimezone(timezone.utc).isoformat()
    for f in _TEXT_FIELDS:
        if f in out:
            out[f] = _unmojibake(out[f])
    out.setdefault("id", doc_id)
    return out


def _pub_sort_key(article: Dict[str, Any]) -> str:
    v = article.get("pubDate")
    if isinstance(v, str):
        return v
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat()
    return ""


@router.get("")
@router.get("/")
def list_news(
    limit: int = Query(100, ge=1, le=500),
    category: Optional[str] = Query(None),
):
    db = _get_db()
    if db is None:
        return {"articles": []}
    try:
        col = db.collection(_COLLECTION)
        query = col
        if category:
            query = query.where("category", "==", category)
        # pubDate is stored as ISO 8601 UTC string — lexicographic sort is correct.
        # Some older records may be missing pubDate, so we fetch a generous slice
        # and sort in Python rather than relying on Firestore order_by (which
        # would require an index when combined with the where clause above).
        fetch_n = min(max(limit * 3, limit), 500)
        docs = list(query.limit(fetch_n).get())
        articles = [_serialize(d.id, d.to_dict() or {}) for d in docs]
        articles.sort(key=_pub_sort_key, reverse=True)
        return {"articles": articles[:limit]}
    except Exception as e:
        print(f"[news] list error: {e}")
        return {"articles": []}


@router.get("/sync/status")
def sync_status():
    """Latest sync time across the collection (best-effort)."""
    db = _get_db()
    if db is None:
        return {"lastSync": None, "available": False}
    try:
        from google.cloud import firestore
        snap = list(
            db.collection(_COLLECTION)
            .order_by("syncedAt", direction=firestore.Query.DESCENDING)
            .limit(1)
            .get()
        )
        if not snap:
            return {"lastSync": None, "available": True, "count": 0}
        latest = snap[0].to_dict() or {}
        synced = latest.get("syncedAt")
        if isinstance(synced, datetime):
            synced = synced.astimezone(timezone.utc).isoformat()
        return {"lastSync": synced, "available": True}
    except Exception as e:
        print(f"[news] sync status error: {e}")
        return {"lastSync": None, "available": False, "error": str(e)}


@router.get("/{article_id}")
def get_article(article_id: str):
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="News store unavailable")
    try:
        snap = db.collection(_COLLECTION).document(article_id).get()
        if not snap.exists:
            raise HTTPException(status_code=404, detail="Article not found")
        return _serialize(snap.id, snap.to_dict() or {})
    except HTTPException:
        raise
    except Exception as e:
        print(f"[news] get error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
