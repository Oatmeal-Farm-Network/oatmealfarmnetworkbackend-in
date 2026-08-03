"""
Saige history store.

Persists pest diagnoses, soil assessments, and price forecasts per user
so we can show trends on the dashboard and power "your last 3 alerts"
cards. JSON-backed for zero-migration deployment; swap to a SQL table
by replacing `_load` / `_save` / `_file_for`.

Each entry is an append-only record with a type, timestamp, user_id,
and the raw feature output.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

STORE_DIR = Path(os.getenv("HISTORY_STORE_DIR", "./saige_history"))
_lock = threading.Lock()

# Cap how many rows we keep per (user, type) bucket. Anything older is
# dropped — this store is for UX trend cards, not an audit log.
MAX_PER_USER_TYPE = 100

# Strip big blobs from records we persist (don't want to keep base64
# images forever).
def _strip_heavy(record: Dict) -> Dict:
    clean = dict(record)
    clean.pop("image_base64", None)
    clean.pop("raw", None)
    return clean


def _file_for(user_id: str) -> Path:
    safe = "".join(c for c in str(user_id) if c.isalnum() or c in "-_") or "anon"
    return STORE_DIR / f"{safe}.json"


def _load(user_id: str) -> Dict[str, List[Dict]]:
    path = _file_for(user_id)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[history] read error for {user_id}: {e}")
        return {}


def _save(user_id: str, data: Dict[str, List[Dict]]) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    path = _file_for(user_id)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)


def record(user_id: str, entry_type: str, payload: Dict[str, Any]) -> Dict:
    """Append a record. Returns the saved record (with id + timestamp)."""
    if not user_id:
        user_id = "anon"
    entry = {
        "id": uuid.uuid4().hex,
        "type": entry_type,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "payload": _strip_heavy(payload or {}),
    }
    with _lock:
        data = _load(user_id)
        bucket = data.setdefault(entry_type, [])
        bucket.insert(0, entry)
        if len(bucket) > MAX_PER_USER_TYPE:
            del bucket[MAX_PER_USER_TYPE:]
        _save(user_id, data)
    return entry


def list_for_user(user_id: str, entry_type: Optional[str] = None,
                  limit: int = 20) -> List[Dict]:
    with _lock:
        data = _load(user_id or "anon")
    if entry_type:
        return (data.get(entry_type, []) or [])[:limit]
    merged: List[Dict] = []
    for rows in data.values():
        merged.extend(rows)
    merged.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return merged[:limit]


def delete_entry(user_id: str, entry_id: str) -> bool:
    with _lock:
        data = _load(user_id or "anon")
        hit = False
        for t, rows in data.items():
            before = len(rows)
            data[t] = [r for r in rows if r.get("id") != entry_id]
            if len(data[t]) != before:
                hit = True
        if hit:
            _save(user_id or "anon", data)
        return hit


# ──────────────────────────────────────────────────────────────────
# LLM tool — recall a user's past Saige feature outputs (soil, price,
# pest, etc.). Pest detection already has its own dedicated tool with
# nicer formatting; this one is the catch-all for "what did the AI tell
# me last week about my soil / prices / etc.".
# ──────────────────────────────────────────────────────────────────
from langchain_core.tools import tool


def _format_one(rec: Dict) -> str:
    p = rec.get("payload") or {}
    when = (rec.get("created_at") or "")[:10]
    t = rec.get("type") or "entry"
    if t == "soil":
        crop = p.get("crop") or p.get("crop_identified") or ""
        recs = p.get("recommendations") or p.get("summary") or ""
        head = f"{when} — soil assessment"
        if crop:
            head += f" ({crop})"
        line = head
        if recs:
            line += f": {str(recs)[:160]}"
        return line
    if t == "price":
        commodity = p.get("commodity") or p.get("crop") or ""
        forecast = p.get("forecast") or p.get("trend") or p.get("summary") or ""
        head = f"{when} — price forecast"
        if commodity:
            head += f" ({commodity})"
        if forecast:
            head += f": {str(forecast)[:160]}"
        return head
    if t == "pest":
        diag = p.get("diagnosis") or "unknown"
        conf = p.get("confidence") or "uncertain"
        return f"{when} — pest detection: {diag} ({conf} confidence)"
    summary = p.get("summary") or p.get("notes") or ""
    head = f"{when} — {t}"
    if summary:
        head += f": {str(summary)[:160]}"
    return head


@tool
def get_my_recent_history_tool(entry_type: str = "", limit: int = 5,
                                people_id: str = "") -> str:
    """Look up the user's recent Saige feature history (soil assessments,
    price forecasts, etc.). Use when the user asks "what did Saige tell
    me last time about my soil / prices?", "what was my last forecast",
    "show me my past assessments". For pest-photo follow-ups prefer
    `get_recent_pest_detections_tool` instead — it has richer formatting.
    entry_type: optional filter — "soil", "price", "pest", or empty for
    all types interleaved.
    limit: 1 to 20 (default 5).
    people_id is injected from session state — do not guess it."""
    if not people_id:
        return ("I can't pull your history without knowing who you are. "
                "Sign in and try again.")
    n = max(1, min(int(limit or 5), 20))
    et = (entry_type or "").strip().lower() or None
    rows = list_for_user(str(people_id), entry_type=et, limit=n)
    if not rows:
        if et:
            return (f"No {et} history yet. Use the {et} feature in the "
                    f"OFN app and Saige can read back past results.")
        return ("No saved Saige history yet. Run a feature like soil "
                "assessment, price forecast, or pest detection and I "
                "can recall results later.")
    label = f"your {et}" if et else "your Saige"
    out = [f"Your {len(rows)} most recent {label} record(s):"]
    for r in rows:
        out.append(f"  • {_format_one(r)}")
    return "\n".join(out)


history_tools = [get_my_recent_history_tool]
