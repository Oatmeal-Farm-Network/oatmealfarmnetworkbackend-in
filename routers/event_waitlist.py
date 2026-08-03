"""
Unified waitlist for capacity-limited event resources.

Many per-event resources have a max capacity (meal sessions, conference
sessions, tour slots, dining tables, halter classes). Rather than adding
waitlist columns to each, we keep one table that references resource type +
ID. When capacity frees up (cancellation, refund), `promote_next` moves the
oldest waitlist entry to confirmed and notifies them.

Resource types (ResourceKind):
  meal_session | conference_session | tour_slot | dining_table | halter_class
"""
import os, logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal

try:
    import sendgrid
    from sendgrid.helpers.mail import Mail
except Exception:
    sendgrid = None

router = APIRouter()
logger = logging.getLogger(__name__)

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
FROM_EMAIL       = os.getenv("FROM_EMAIL", "john@oatmeal-ai.com")


# Map ResourceKind → capacity lookup + current count query
CAPACITY_LOOKUPS = {
    "meal_session": {
        "capacity_sql": "SELECT MaxTickets AS cap FROM OFNEventMealSessions WHERE SessionID = :id",
        "count_sql":    ("SELECT ISNULL(SUM(Quantity), 0) AS n FROM OFNEventMealTickets "
                         "WHERE SessionID = :id AND PaidStatus <> 'refunded'"),
        "label_sql":    "SELECT SessionName AS label FROM OFNEventMealSessions WHERE SessionID = :id",
    },
    "conference_session": {
        "capacity_sql": "SELECT Capacity AS cap FROM OFNEventConferenceSessions WHERE SessionID = :id",
        "count_sql":    ("SELECT COUNT(*) AS n FROM OFNEventConferenceAttendance "
                         "WHERE SessionID = :id"),
        "label_sql":    "SELECT Title AS label FROM OFNEventConferenceSessions WHERE SessionID = :id",
    },
    "tour_slot": {
        "capacity_sql": "SELECT Capacity AS cap FROM OFNEventTourSlots WHERE SlotID = :id",
        "count_sql":    ("SELECT ISNULL(SUM(PartySize), 0) AS n FROM OFNEventTourRegistrations "
                         "WHERE SlotID = :id AND Status <> 'cancelled'"),
        "label_sql":    "SELECT SlotLabel AS label FROM OFNEventTourSlots WHERE SlotID = :id",
    },
    "dining_table": {
        "capacity_sql": "SELECT Capacity AS cap FROM OFNEventDiningTables WHERE TableID = :id",
        "count_sql":    ("SELECT ISNULL(SUM(PartySize), 0) AS n FROM OFNEventDiningRegistrations "
                         "WHERE TableID = :id AND Status <> 'cancelled'"),
        "label_sql":    "SELECT TableLabel AS label FROM OFNEventDiningTables WHERE TableID = :id",
    },
}


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventWaitlist')
        CREATE TABLE OFNEventWaitlist (
            WaitID         INT IDENTITY(1,1) PRIMARY KEY,
            EventID        INT NOT NULL,
            ResourceKind   NVARCHAR(50) NOT NULL,
            ResourceID     INT NOT NULL,
            PeopleID       INT,
            BusinessID     INT,
            Name           NVARCHAR(300),
            Email          NVARCHAR(300),
            Phone          NVARCHAR(50),
            PartySize      INT NOT NULL DEFAULT 1,
            Notes          NVARCHAR(500),
            Status         NVARCHAR(30) NOT NULL DEFAULT 'waiting',
            -- waiting | offered | promoted | declined | expired
            OfferedAt      DATETIME,
            PromotedAt     DATETIME,
            CreatedDate    DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


with SessionLocal() as _db:
    try:
        ensure_tables(_db)
    except Exception as e:
        print(f"Waitlist table setup error: {e}")


# ─── Capacity check helper (other routers can call) ────────────────

def capacity_status(db: Session, kind: str, resource_id: int):
    """Return {cap, used, available, label} for a resource. cap=None if unlimited.
    kind must match CAPACITY_LOOKUPS."""
    cfg = CAPACITY_LOOKUPS.get(kind)
    if not cfg:
        return {"cap": None, "used": 0, "available": None, "label": None}
    try:
        cap_row  = db.execute(text(cfg["capacity_sql"]), {"id": resource_id}).mappings().first()
        cnt_row  = db.execute(text(cfg["count_sql"]),    {"id": resource_id}).mappings().first()
        lbl_row  = db.execute(text(cfg["label_sql"]),    {"id": resource_id}).mappings().first()
    except Exception:
        return {"cap": None, "used": 0, "available": None, "label": None}
    cap = cap_row["cap"] if cap_row else None
    used = int(cnt_row["n"] or 0) if cnt_row else 0
    avail = (int(cap) - used) if cap else None
    label = lbl_row["label"] if lbl_row else None
    return {"cap": int(cap) if cap else None, "used": used,
            "available": avail, "label": label}


# ─── CRUD + queue ops ───────────────────────────────────────────────

@router.post("/api/events/{event_id}/waitlist")
def join_waitlist(event_id: int, data: dict, db: Session = Depends(get_db)):
    kind = data.get("ResourceKind")
    rid  = data.get("ResourceID")
    if kind not in CAPACITY_LOOKUPS or not rid:
        raise HTTPException(400, "ResourceKind and ResourceID required (and kind must be recognized)")
    res = db.execute(text("""
        INSERT INTO OFNEventWaitlist
            (EventID, ResourceKind, ResourceID, PeopleID, BusinessID,
             Name, Email, Phone, PartySize, Notes, Status)
        OUTPUT INSERTED.WaitID AS id
        VALUES (:e, :k, :r, :p, :b, :n, :em, :ph, :ps, :nt, 'waiting')
    """), {
        "e": event_id, "k": kind, "r": int(rid),
        "p": data.get("PeopleID"), "b": data.get("BusinessID"),
        "n": data.get("Name"), "em": data.get("Email"),
        "ph": data.get("Phone"),
        "ps": int(data.get("PartySize") or 1),
        "nt": data.get("Notes"),
    }).mappings().first()
    db.commit()
    return {"WaitID": int(res["id"])}


@router.get("/api/events/{event_id}/waitlist")
def list_waitlist(event_id: int, kind: str | None = None, resource_id: int | None = None,
                  db: Session = Depends(get_db)):
    where = ["EventID = :e"]
    params = {"e": event_id}
    if kind:
        where.append("ResourceKind = :k"); params["k"] = kind
    if resource_id:
        where.append("ResourceID = :r"); params["r"] = resource_id
    rows = db.execute(text(f"""
        SELECT * FROM OFNEventWaitlist
         WHERE {' AND '.join(where)}
         ORDER BY CreatedDate
    """), params).mappings().all()
    return [dict(r) for r in rows]


@router.delete("/api/events/waitlist/{wait_id}")
def leave_waitlist(wait_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventWaitlist WHERE WaitID = :id"), {"id": wait_id})
    db.commit()
    return {"ok": True}


@router.post("/api/events/{event_id}/waitlist/promote")
def promote_next(event_id: int, data: dict, db: Session = Depends(get_db)):
    """Called when capacity frees up. Picks the oldest 'waiting' entry for the
    given resource, marks it 'offered', and emails them so they can confirm."""
    kind = data.get("ResourceKind")
    rid  = data.get("ResourceID")
    if kind not in CAPACITY_LOOKUPS or not rid:
        raise HTTPException(400, "Invalid resource")
    row = db.execute(text("""
        SELECT TOP 1 * FROM OFNEventWaitlist
         WHERE EventID = :e AND ResourceKind = :k AND ResourceID = :r AND Status = 'waiting'
         ORDER BY CreatedDate
    """), {"e": event_id, "k": kind, "r": int(rid)}).mappings().first()
    if not row:
        return {"promoted": None, "message": "Empty waitlist"}
    db.execute(text("""
        UPDATE OFNEventWaitlist SET Status = 'offered', OfferedAt = GETDATE()
         WHERE WaitID = :id
    """), {"id": row["WaitID"]})
    db.commit()
    _notify_offered(db, dict(row))
    return {"promoted": int(row["WaitID"]), "email": row["Email"]}


@router.post("/api/events/waitlist/{wait_id}/confirm")
def confirm_offer(wait_id: int, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventWaitlist SET Status = 'promoted', PromotedAt = GETDATE()
         WHERE WaitID = :id
    """), {"id": wait_id})
    db.commit()
    return {"ok": True}


@router.post("/api/events/waitlist/{wait_id}/decline")
def decline_offer(wait_id: int, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventWaitlist SET Status = 'declined' WHERE WaitID = :id
    """), {"id": wait_id})
    db.commit()
    return {"ok": True}


# ─── Notification ──────────────────────────────────────────────────

def _notify_offered(db: Session, row: dict):
    if not SENDGRID_API_KEY or sendgrid is None:
        return
    if not row.get("Email"):
        return
    ev = db.execute(text("SELECT EventName FROM OFNEvents WHERE EventID = :e"),
                    {"e": row["EventID"]}).mappings().first()
    label = "your requested spot"
    try:
        cfg = CAPACITY_LOOKUPS.get(row["ResourceKind"])
        if cfg:
            lbl_row = db.execute(text(cfg["label_sql"]),
                                 {"id": row["ResourceID"]}).mappings().first()
            if lbl_row and lbl_row.get("label"):
                label = lbl_row["label"]
    except Exception:
        pass
    base = os.getenv("OFN_BASE_URL", "https://www.oatmealfarmnetwork.com")
    confirm_url = f"{base}/waitlist/{row['WaitID']}/confirm"
    decline_url = f"{base}/waitlist/{row['WaitID']}/decline"
    event_name = ev["EventName"] if ev else "the event"
    html = f"""
      <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto">
        <h2 style="color:#3D6B34">A spot opened up!</h2>
        <p>Hi {row.get('Name') or ''},</p>
        <p>A spot opened for <strong>{label}</strong> at <strong>{event_name}</strong>.
           You're next on the waitlist.</p>
        <p>
          <a href="{confirm_url}"
             style="background:#3D6B34;color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none">
             Claim my spot
          </a>
          &nbsp;
          <a href="{decline_url}" style="color:#666;text-decoration:none">No thanks</a>
        </p>
        <p style="font-size:12px;color:#888">If you don't respond, we'll offer it to the next
           person. Please reply quickly.</p>
      </div>
    """
    try:
        sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
        sg.send(Mail(
            from_email=FROM_EMAIL, to_emails=row["Email"],
            subject=f"[{event_name}] A waitlist spot is yours",
            html_content=html,
        ))
    except Exception as e:
        logger.error("Waitlist notify failed: %s", e)
