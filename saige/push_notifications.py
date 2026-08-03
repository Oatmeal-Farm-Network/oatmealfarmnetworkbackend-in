"""
Web push notifications (PWA).

VAPID-based web-push. Keeps an in-memory + JSON-persisted subscription
registry and exposes send/broadcast helpers. Uses the `pywebpush` library;
if unavailable, module gracefully degrades to a no-op that lets the rest
of Saige keep running.

For production, swap the JSON store for your main SQL tables. The registry
interface is intentionally thin (subscribe / unsubscribe / list / send) so
that swap is a one-file change.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from pywebpush import webpush, WebPushException
    _WP_AVAILABLE = True
except Exception as _e:
    print(f"[push] pywebpush not installed: {_e}. Install with 'pip install pywebpush'.")
    webpush = None
    WebPushException = Exception
    _WP_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────
# VAPID config
# ──────────────────────────────────────────────────────────────────
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY  = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_CONTACT     = os.getenv("VAPID_CONTACT_EMAIL", "mailto:ops@oatmealfarmnetwork.com")

VAPID_CLAIMS = {"sub": VAPID_CONTACT}


def is_configured() -> bool:
    return bool(_WP_AVAILABLE and VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY)


def public_key() -> str:
    return VAPID_PUBLIC_KEY


# ──────────────────────────────────────────────────────────────────
# Subscription store (JSON on disk; simple thread lock)
# ──────────────────────────────────────────────────────────────────
STORE_PATH = Path(os.getenv("PUSH_STORE_PATH", "./push_subscriptions.json"))
_store_lock = threading.Lock()


def _load() -> Dict[str, Dict]:
    if not STORE_PATH.exists():
        return {}
    try:
        with STORE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[push] failed to read store: {e}")
        return {}


def _save(data: Dict[str, Dict]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(STORE_PATH)


def subscribe(user_id: str, subscription: Dict, tags: Optional[List[str]] = None,
              location: Optional[Dict[str, Any]] = None) -> Dict:
    """Register a browser subscription for a user.
    subscription: the full push-subscription JSON from the browser
        (endpoint + keys.p256dh + keys.auth).
    location: optional {label, lat, lon} used by signal-driven alerts
        (frost/heat/hail warnings). Either label or lat+lon is enough."""
    endpoint = (subscription or {}).get("endpoint")
    if not endpoint:
        return {"status": "error", "message": "Subscription missing endpoint."}
    with _store_lock:
        data = _load()
        data[endpoint] = {
            "user_id": user_id,
            "subscription": subscription,
            "tags": tags or [],
            "location": location or None,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "last_success": None,
            "last_error": None,
        }
        _save(data)
    return {"status": "ok", "endpoint": endpoint}


def unsubscribe(endpoint: str) -> Dict:
    with _store_lock:
        data = _load()
        removed = data.pop(endpoint, None)
        if removed:
            _save(data)
    return {"status": "ok" if removed else "not_found"}


def list_subscriptions(user_id: Optional[str] = None, tag: Optional[str] = None) -> List[Dict]:
    with _store_lock:
        data = _load()
    out = []
    for ep, rec in data.items():
        if user_id and rec.get("user_id") != user_id:
            continue
        if tag and tag not in rec.get("tags", []):
            continue
        out.append({"endpoint": ep, **rec})
    return out


# ──────────────────────────────────────────────────────────────────
# Sending
# ──────────────────────────────────────────────────────────────────
def _send_one(subscription: Dict, payload: Dict) -> Dict:
    if not is_configured():
        return {"status": "not_configured"}
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=dict(VAPID_CLAIMS),
        )
        return {"status": "ok"}
    except WebPushException as e:
        # 410 Gone = subscription expired, should be pruned
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        return {"status": "error", "code": status_code, "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def send_to(user_id: str, title: str, body: str,
            url: Optional[str] = None, tag: Optional[str] = None,
            extra: Optional[Dict] = None) -> Dict:
    subs = list_subscriptions(user_id=user_id, tag=tag)
    return _broadcast(subs, title, body, url, extra)


def broadcast(title: str, body: str, url: Optional[str] = None,
              tag: Optional[str] = None, extra: Optional[Dict] = None) -> Dict:
    subs = list_subscriptions(tag=tag)
    return _broadcast(subs, title, body, url, extra)


def _broadcast(subs: List[Dict], title: str, body: str,
               url: Optional[str], extra: Optional[Dict]) -> Dict:
    payload = {
        "title": title,
        "body": body,
        "url": url or "/",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    if extra:
        payload.update(extra)

    results = {"sent": 0, "failed": 0, "pruned": 0, "errors": []}
    to_prune: List[str] = []
    for s in subs:
        r = _send_one(s["subscription"], payload)
        if r.get("status") == "ok":
            results["sent"] += 1
        else:
            results["failed"] += 1
            code = r.get("code")
            if code in (404, 410):
                to_prune.append(s["endpoint"])
            results["errors"].append({"endpoint": s["endpoint"], "error": r.get("message")})

    if to_prune:
        with _store_lock:
            data = _load()
            for ep in to_prune:
                data.pop(ep, None)
            _save(data)
        results["pruned"] = len(to_prune)

    return results


# ──────────────────────────────────────────────────────────────────
# LLM tool (Saige can ask the user to be notified about something)
# ──────────────────────────────────────────────────────────────────
from langchain_core.tools import tool


@tool
def send_push_notification_tool(
    title: str,
    body: str,
    url: str = "/",
    people_id: str = "",
) -> str:
    """Send a web push notification to the current user's subscribed
    browsers / devices. Use ONLY when the user explicitly asks to be
    notified ("ping me when…", "send me a notification when…", "remind
    me about…") or when an immediate, time-sensitive alert clearly
    benefits them (frost overnight, irrigation overdue). Always confirm
    the wording with the user before calling.

    title: short notification title (≤ 60 chars).
    body:  one-line message body (≤ 160 chars).
    url:   path to deep-link the user to when they click (e.g. "/saige").
    people_id is injected from session state — do not guess it."""
    if not is_configured():
        return ("Push notifications aren't configured on this server "
                "(missing VAPID keys), so I can't send one right now.")
    if not people_id:
        return ("I can't send a push without knowing who you are. Sign "
                "in and try again.")
    subs = list_subscriptions(user_id=str(people_id))
    if not subs:
        return ("You haven't enabled push notifications on any device "
                "yet. Open the OFN web app and click 'Enable notifications' "
                "first, then ask me again.")
    title = (title or "Saige").strip()[:60]
    body = (body or "").strip()[:160] or "(no message)"
    url = (url or "/").strip() or "/"
    result = send_to(str(people_id), title=title, body=body, url=url)
    sent = result.get("sent", 0)
    failed = result.get("failed", 0)
    if sent:
        return f"Sent push to {sent} of your device(s). Title: \"{title}\"."
    return (f"Couldn't deliver the push. {failed} delivery attempts failed "
            f"({result.get('errors', [{}])[0].get('error', 'unknown error')}).")


push_notification_tools = [send_push_notification_tool]
