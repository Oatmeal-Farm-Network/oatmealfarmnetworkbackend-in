# routers/notifications.py
# In-app notifications: per-person inbox, polled by the Header bell.
# Other modules emit via `create_notification(db, ...)` — keep that signature stable.

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine
from auth import get_current_user
import models

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


# ── Auto-create AppNotifications table ───────────────────────────────────────
# NOTE: table is named AppNotifications (not Notifications) because an older
# social/follow feature already owns the `Notifications` table with a different
# shape (PeopleID/ActorPeopleID/IsRead/NotificationText).
try:
    with engine.begin() as _conn:
        _conn.execute(text("""
            IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='AppNotifications')
            BEGIN
                CREATE TABLE AppNotifications (
                    NotificationID       INT IDENTITY(1,1) PRIMARY KEY,
                    RecipientPeopleID    INT NOT NULL,
                    RecipientBusinessID  INT NULL,
                    Type                 VARCHAR(80)  NOT NULL,
                    Title                NVARCHAR(200) NOT NULL,
                    Body                 NVARCHAR(1000) NULL,
                    LinkPath             NVARCHAR(500) NULL,
                    RelatedEntityType    VARCHAR(50)  NULL,
                    RelatedEntityID      INT          NULL,
                    ReadAt               DATETIME     NULL,
                    CreatedAt            DATETIME     NOT NULL DEFAULT GETDATE()
                )
                -- EXEC() defers parsing until the CREATE TABLE has executed, so the
                -- filtered-index predicate can reference ReadAt without a parse error.
                EXEC('CREATE INDEX IX_AppNotifications_Recipient_CreatedAt
                       ON AppNotifications (RecipientPeopleID, CreatedAt DESC)')
                EXEC('CREATE INDEX IX_AppNotifications_Recipient_Unread
                       ON AppNotifications (RecipientPeopleID, ReadAt) WHERE ReadAt IS NULL')
            END
        """))
except Exception as e:
    print(f"[notifications] Table setup error: {e}")


# ── Internal helper (imported by other routers) ──────────────────────────────
def _push_to_person(people_id: int, title: str, body: str | None,
                    link_path: str | None, type_: str) -> None:
    """Fire-and-forget web push to all of a user's subscribed devices.
    Silent on failure — push is best-effort, the bell-icon record is the
    durable notification."""
    try:
        from saige.push_notifications import send_to, is_configured
        if not is_configured():
            return
        send_to(
            user_id=str(people_id),
            title=title,
            body=body or "",
            url=link_path or "/",
            tag=f"appnotif-{type_}",
        )
    except Exception as e:
        # Don't let a push failure break the bell-inbox insert
        print(f"[notify] push to person {people_id} failed: {e}")


def create_notification(
    db: Session,
    people_id: int,
    type: str,
    title: str,
    body: str | None = None,
    link_path: str | None = None,
    business_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    push: bool = True,
):
    """Insert one notification row + (default) push to subscribed devices.
    Caller is responsible for commit(). Set push=False to suppress the push
    side-effect (e.g. for batch imports or backfills)."""
    db.execute(text("""
        INSERT INTO AppNotifications
            (RecipientPeopleID, RecipientBusinessID, Type, Title, Body,
             LinkPath, RelatedEntityType, RelatedEntityID)
        VALUES (:pid, :bid, :t, :ti, :b, :lp, :et, :ei)
    """), {
        "pid": people_id, "bid": business_id,
        "t": type, "ti": title, "b": body, "lp": link_path,
        "et": entity_type, "ei": entity_id,
    })
    if push:
        _push_to_person(people_id, title, body, link_path, type)


def notify_business(
    db: Session,
    business_id: int,
    type: str,
    title: str,
    body: str | None = None,
    link_path: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
):
    """Fan a notification out to every active BusinessAccess row for a business."""
    rows = db.execute(text("""
        SELECT PeopleID FROM BusinessAccess
        WHERE BusinessID = :bid AND Active = 1
    """), {"bid": business_id}).fetchall()
    for r in rows:
        create_notification(
            db, people_id=r.PeopleID, type=type, title=title, body=body,
            link_path=link_path, business_id=business_id,
            entity_type=entity_type, entity_id=entity_id,
        )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 200))
    where = "RecipientPeopleID = :pid"
    if unread_only:
        where += " AND ReadAt IS NULL"
    rows = db.execute(text(f"""
        SELECT TOP (:lim)
               NotificationID, Type, Title, Body, LinkPath,
               RelatedEntityType, RelatedEntityID,
               RecipientBusinessID, ReadAt, CreatedAt
        FROM AppNotifications
        WHERE {where}
        ORDER BY CreatedAt DESC
    """), {"pid": current_user.PeopleID, "lim": limit}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/unread-count")
def unread_count(
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = db.execute(text("""
        SELECT COUNT(*) FROM AppNotifications
        WHERE RecipientPeopleID = :pid AND ReadAt IS NULL
    """), {"pid": current_user.PeopleID}).scalar() or 0
    return {"count": int(n)}


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = db.execute(text("""
        UPDATE AppNotifications
        SET ReadAt = GETDATE()
        WHERE NotificationID = :nid
          AND RecipientPeopleID = :pid
          AND ReadAt IS NULL
    """), {"nid": notification_id, "pid": current_user.PeopleID})
    db.commit()
    if result.rowcount == 0:
        # Either not found, wrong recipient, or already read — treat as no-op.
        return {"updated": 0}
    return {"updated": result.rowcount}


@router.post("/read-all")
def mark_all_read(
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = db.execute(text("""
        UPDATE AppNotifications
        SET ReadAt = GETDATE()
        WHERE RecipientPeopleID = :pid AND ReadAt IS NULL
    """), {"pid": current_user.PeopleID})
    db.commit()
    return {"updated": result.rowcount}


# ── Internal cross-process push fan-out ─────────────────────────────────────
# CropMonitoringBackend (port 8002) and any other separately-deployed service
# can POST here to push a notification to one or all members of a business.
# Authed via shared secret in INTERNAL_PUSH_TOKEN env (skip header → reject).

import os as _os
INTERNAL_PUSH_TOKEN = _os.getenv("INTERNAL_PUSH_TOKEN", "")

from fastapi import Header

@router.post("/_internal/push-only")
def internal_push_only(
    body: dict,
    x_internal_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Push-only fan-out (no DB row insert). For services that have already
    written their own AppNotifications rows but need the phone-push side."""
    if INTERNAL_PUSH_TOKEN:
        if x_internal_token != INTERNAL_PUSH_TOKEN:
            raise HTTPException(status_code=403, detail="Bad internal token.")

    business_id = body.get("business_id")
    people_id   = body.get("people_id")
    title       = body.get("title", "Notification")
    msg         = body.get("body")
    link        = body.get("link_path")
    type_       = body.get("type", "Internal")

    pids: list[int] = []
    if people_id:
        pids = [int(people_id)]
    elif business_id:
        rows = db.execute(text("""
            SELECT PeopleID FROM BusinessAccess
            WHERE BusinessID = :bid AND Active = 1
        """), {"bid": int(business_id)}).fetchall()
        pids = [int(r.PeopleID) for r in rows]
    else:
        raise HTTPException(status_code=400, detail="business_id or people_id required.")

    sent = 0
    for pid in pids:
        try:
            _push_to_person(pid, title, msg, link, type_)
            sent += 1
        except Exception:
            pass
    return {"ok": True, "pushed": sent}


@router.post("/_internal/fanout")
def internal_push_fanout(
    body: dict,
    x_internal_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Body: {people_id?, business_id?, type, title, body, link_path}.
    If business_id: push + record bell-inbox row for every active member.
    If people_id:   push + record for that one person.
    Skips push (still records) on header-token mismatch when the token is set."""
    if INTERNAL_PUSH_TOKEN:
        if x_internal_token != INTERNAL_PUSH_TOKEN:
            raise HTTPException(status_code=403, detail="Bad internal token.")

    business_id = body.get("business_id")
    people_id   = body.get("people_id")
    if not (business_id or people_id):
        raise HTTPException(status_code=400, detail="business_id or people_id required.")

    if business_id:
        notify_business(
            db, business_id=int(business_id),
            type=body.get("type", "Internal"),
            title=body.get("title", "Notification"),
            body=body.get("body"),
            link_path=body.get("link_path"),
            entity_type=body.get("entity_type"),
            entity_id=body.get("entity_id"),
        )
    else:
        create_notification(
            db, people_id=int(people_id),
            type=body.get("type", "Internal"),
            title=body.get("title", "Notification"),
            body=body.get("body"),
            link_path=body.get("link_path"),
            business_id=body.get("business_id"),
            entity_type=body.get("entity_type"),
            entity_id=body.get("entity_id"),
        )
    db.commit()
    return {"ok": True}
