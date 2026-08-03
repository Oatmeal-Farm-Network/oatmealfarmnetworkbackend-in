"""
farm_digest.py — Phase 4 ongoing farm analysis engine.

Triggered daily by POST /cron/farm-digest (Cloud Scheduler or manual).

For each business with an agent_briefings Firestore document:
  1. Enforces a 20-hour minimum interval to prevent repeat pushes.
  2. Fetches open dbo.Alert rows that are NEW since the last digest run.
  3. If new alerts exist, calls Gemini to craft a 2-3 sentence personalized
     insight framed around the farmer's crops, fields, and stated headache.
  4. Sends a push notification to the farmer's registered devices.
  5. Writes last_digest_at back to the briefing doc.

If there are no new alerts since the last run the business is skipped —
farmers are never pushed a "nothing to report" message.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("farm_digest")

MIN_INTERVAL_HOURS = 20   # minimum hours between digests for any one business
PUSH_CHAR_LIMIT    = 220  # body text cap for push notifications


# ── DB helpers (same MSSQL connection pattern as cassia.py) ─────────────────

try:
    import pymssql as _pymssql
    _PMS = True
except ImportError:
    _pymssql = None  # type: ignore[assignment]
    _PMS = False

from config import DB_CONFIG


def _connect():
    if not _PMS or not all([
        DB_CONFIG.get("host"), DB_CONFIG.get("user"), DB_CONFIG.get("database")
    ]):
        return None
    try:
        return _pymssql.connect(
            server=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
            as_dict=True,
        )
    except Exception as e:
        logger.error("[FarmDigest] DB connect failed: %s", e)
        return None


def _query(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = _connect()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return list(cur.fetchall())
    except Exception as e:
        logger.error("[FarmDigest] query failed: %s", e)
        return []
    finally:
        conn.close()


# ── Alert fetcher ────────────────────────────────────────────────────────────

def _get_new_alerts(
    business_id: int,
    since: Optional[float],
) -> List[Dict[str, Any]]:
    """Return open dbo.Alert rows for all fields of this business that were
    created after `since` (Unix timestamp). If `since` is None, return all
    open alerts regardless of age."""
    base_sql = (
        "SELECT TOP 20 "
        "  a.AlertID, a.AlertType, a.Severity, a.Message, a.CreatedAt, "
        "  f.Name AS FieldName, f.CropType "
        "FROM dbo.Alert a "
        "JOIN dbo.Field f ON f.FieldID = a.FieldID "
        "WHERE f.BusinessID = %s "
        "  AND (a.Status IS NULL OR a.Status NOT IN ('resolved', 'dismissed')) "
    )
    if since:
        since_dt = datetime.fromtimestamp(since, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        return _query(
            base_sql + "  AND a.CreatedAt > %s ORDER BY a.Severity DESC, a.CreatedAt DESC",
            (business_id, since_dt),
        )
    return _query(
        base_sql + "ORDER BY a.Severity DESC, a.CreatedAt DESC",
        (business_id,),
    )


# ── Prompt builder ───────────────────────────────────────────────────────────

def _build_prompt(profile: Dict[str, Any], alerts: List[Dict[str, Any]]) -> str:
    crops    = ", ".join(profile.get("crops") or []) or "unspecified crops"
    channels = ", ".join(profile.get("channels") or []) or "unspecified sales channels"
    n_fields = profile.get("field_count") or 0
    headache = (profile.get("headache") or "").strip()

    alert_lines = []
    for a in alerts[:8]:
        sev   = (a.get("Severity") or a.get("severity") or "info").upper()
        msg   = a.get("Message")   or a.get("message")   or "unspecified alert"
        field = a.get("FieldName") or a.get("fieldname") or "field"
        crop  = a.get("CropType")  or a.get("croptype")  or ""
        label = f"{field} ({crop})" if crop else field
        alert_lines.append(f"  [{sev}] {label}: {msg}")

    alerts_text  = "\n".join(alert_lines)
    headache_str = f'\nTheir biggest operational challenge: "{headache}"' if headache else ""

    return (
        "You are Saige, farm advisor for Oatmeal Farm Network.\n\n"
        "Write a push-notification insight for this farmer based on their open "
        "field alerts. Be specific, warm, and actionable.\n\n"
        f"Farmer profile:\n"
        f"• Crops: {crops}\n"
        f"• {n_fields} satellite-monitored field(s)\n"
        f"• Sales channels: {channels}"
        f"{headache_str}\n\n"
        f"Open field alerts ({len(alerts)} new since last check):\n{alerts_text}\n\n"
        "Rules:\n"
        "- 2-3 sentences maximum — this goes straight to their phone\n"
        "- Start directly with the key finding — no greeting, no 'Hi there'\n"
        "- Name the specific field or crop affected where possible\n"
        "- End with one concrete action they can take today\n"
        "- If the alert relates to their stated challenge, tie the advice to it\n"
        "- Stay under 220 characters total"
    )


# ── Per-business analysis ────────────────────────────────────────────────────

def analyze_business(
    business_id: int,
    people_id: str,
    profile: Dict[str, Any],
    last_digest_at: Optional[float],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run one digest cycle for a single business. Returns a status dict."""
    # Enforce minimum interval
    if last_digest_at:
        hours_since = (time.time() - last_digest_at) / 3600.0
        if hours_since < MIN_INTERVAL_HOURS:
            return {
                "status": "skipped",
                "reason": "too_soon",
                "hours_since": round(hours_since, 1),
            }

    # Fetch new alerts
    alerts = _get_new_alerts(business_id, since=last_digest_at)
    if not alerts:
        return {"status": "skipped", "reason": "no_new_alerts"}

    # Generate insight
    try:
        from llm import llm
        resp    = llm.invoke(_build_prompt(profile, alerts))
        insight = (getattr(resp, "content", None) or str(resp)).strip()
    except Exception as e:
        logger.error("[FarmDigest] LLM error for business %s: %s", business_id, e)
        return {"status": "error", "reason": f"llm_error: {e}"}

    if not insight:
        return {"status": "skipped", "reason": "empty_insight"}

    # Truncate to push-safe length
    if len(insight) > PUSH_CHAR_LIMIT:
        insight = insight[: PUSH_CHAR_LIMIT - 3] + "..."

    # Push
    push_result: Dict[str, Any]
    if dry_run:
        push_result = {"status": "dry_run"}
    else:
        try:
            import push_notifications as push
            push_result = push.send_to(
                user_id=str(people_id),
                title="Saige — Farm Health Update",
                body=insight,
                url=f"/account?BusinessID={business_id}",
                tag="farm_digest",
            )
        except Exception as e:
            logger.error("[FarmDigest] push error for business %s: %s", business_id, e)
            push_result = {"status": "error", "reason": str(e)}

    return {
        "status":      "sent" if not dry_run else "dry_run",
        "business_id": business_id,
        "people_id":   people_id,
        "alert_count": len(alerts),
        "insight":     insight,
        "push_result": push_result,
    }


# ── Full digest run ──────────────────────────────────────────────────────────

def run_digest(
    firestore_db: Any,
    dry_run: bool = False,
    business_id_filter: Optional[int] = None,
) -> Dict[str, Any]:
    """Scan all agent_briefings docs and run a digest for each.
    Called by the /cron/farm-digest endpoint.

    firestore_db: the default-DB Firestore client (from chat_history.firestore_db).
    dry_run: if True, generate insights but skip push and Firestore writes.
    business_id_filter: restrict to one business (useful for testing)."""
    if not firestore_db:
        return {"status": "error", "reason": "firestore_unavailable"}

    col  = firestore_db.collection("agent_briefings")
    docs = list(col.stream())

    results: List[Dict[str, Any]] = []
    sent = skipped = errors = 0

    for doc in docs:
        profile = doc.to_dict() or {}
        bid = profile.get("business_id")
        pid = profile.get("people_id")
        if not bid or not pid:
            continue
        if business_id_filter and int(bid) != int(business_id_filter):
            continue

        raw_ts      = profile.get("last_digest_at")
        last_ts     = float(raw_ts) if raw_ts else None

        result = analyze_business(
            business_id=int(bid),
            people_id=str(pid),
            profile=profile,
            last_digest_at=last_ts,
            dry_run=dry_run,
        )
        results.append({"business_id": bid, **result})

        if result["status"] == "sent":
            sent += 1
            try:
                col.document(doc.id).update({"last_digest_at": time.time()})
            except Exception as e:
                logger.warning(
                    "[FarmDigest] failed to update last_digest_at for %s: %s", bid, e
                )
        elif result["status"] == "error":
            errors += 1
        else:
            skipped += 1

    return {
        "status":  "ok",
        "scanned": len(results),
        "sent":    sent,
        "skipped": skipped,
        "errors":  errors,
        "dry_run": dry_run,
        "results": results,
    }
