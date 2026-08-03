"""
Event mailing list — opt-in newsletter / notification subscribers.

Separate from registration tables so organizers can collect interested parties
who aren't registered yet (e.g. "notify me when tickets open", show season
pass holders, past attendees bulk-imported from a mailchimp CSV, etc.).

Entries here are pulled into the broadcast recipient list alongside actual
registrants, so a single "Send to all" reaches both groups.
"""
import csv, io
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventMailingList')
        CREATE TABLE OFNEventMailingList (
            RowID        INT IDENTITY(1,1) PRIMARY KEY,
            EventID      INT NOT NULL,
            Email        NVARCHAR(300) NOT NULL,
            Name         NVARCHAR(300),
            Source       NVARCHAR(100),
            Tags         NVARCHAR(500),
            OptedOutDate DATETIME NULL,
            AddedDate    DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sys.indexes
                       WHERE name = 'IX_OFNEventMailingList_Event_Email')
        CREATE UNIQUE INDEX IX_OFNEventMailingList_Event_Email
               ON OFNEventMailingList(EventID, Email)
    """))
    db.commit()


with SessionLocal() as _db:
    try:
        ensure_tables(_db)
    except Exception as e:
        print(f"Mailing list table setup error: {e}")


def _norm_email(s: str) -> str:
    return (s or "").strip().lower()


# ─── Read / list ────────────────────────────────────────────────────

@router.get("/api/events/{event_id}/mailing-list")
def list_subscribers(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT RowID, Email, Name, Source, Tags, OptedOutDate, AddedDate
          FROM OFNEventMailingList
         WHERE EventID = :e
         ORDER BY AddedDate DESC
    """), {"e": event_id}).mappings().all()
    return [dict(r) for r in rows]


@router.get("/api/events/{event_id}/mailing-list/stats")
def stats(event_id: int, db: Session = Depends(get_db)):
    r = db.execute(text("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN OptedOutDate IS NULL THEN 1 ELSE 0 END) AS active,
               SUM(CASE WHEN OptedOutDate IS NOT NULL THEN 1 ELSE 0 END) AS opted_out
          FROM OFNEventMailingList WHERE EventID = :e
    """), {"e": event_id}).mappings().first()
    return dict(r) if r else {"total": 0, "active": 0, "opted_out": 0}


# ─── Create / update ────────────────────────────────────────────────

@router.post("/api/events/{event_id}/mailing-list")
def add_subscriber(event_id: int, data: dict, db: Session = Depends(get_db)):
    em = _norm_email(data.get("Email"))
    if "@" not in em:
        raise HTTPException(400, "Invalid email")
    existing = db.execute(text("""
        SELECT RowID FROM OFNEventMailingList WHERE EventID = :e AND Email = :em
    """), {"e": event_id, "em": em}).mappings().first()
    if existing:
        db.execute(text("""
            UPDATE OFNEventMailingList
               SET Name = COALESCE(:nm, Name),
                   Source = COALESCE(:src, Source),
                   Tags = COALESCE(:tg, Tags),
                   OptedOutDate = NULL
             WHERE RowID = :id
        """), {
            "id": existing["RowID"],
            "nm": data.get("Name"),
            "src": data.get("Source") or "manual",
            "tg": data.get("Tags"),
        })
        db.commit()
        return {"RowID": int(existing["RowID"]), "updated": True}
    res = db.execute(text("""
        INSERT INTO OFNEventMailingList (EventID, Email, Name, Source, Tags)
        OUTPUT INSERTED.RowID AS id
        VALUES (:e, :em, :nm, :src, :tg)
    """), {
        "e": event_id, "em": em,
        "nm": data.get("Name"),
        "src": data.get("Source") or "manual",
        "tg": data.get("Tags"),
    }).mappings().first()
    db.commit()
    return {"RowID": int(res["id"]), "updated": False}


@router.put("/api/events/mailing-list/{row_id}")
def update_subscriber(row_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventMailingList
           SET Name = :nm, Source = :src, Tags = :tg
         WHERE RowID = :id
    """), {"id": row_id, "nm": data.get("Name"),
           "src": data.get("Source"), "tg": data.get("Tags")})
    db.commit()
    return {"ok": True}


@router.post("/api/events/mailing-list/{row_id}/opt-out")
def opt_out(row_id: int, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventMailingList SET OptedOutDate = GETDATE() WHERE RowID = :id
    """), {"id": row_id})
    db.commit()
    return {"ok": True}


@router.post("/api/events/mailing-list/{row_id}/re-subscribe")
def re_subscribe(row_id: int, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventMailingList SET OptedOutDate = NULL WHERE RowID = :id
    """), {"id": row_id})
    db.commit()
    return {"ok": True}


@router.delete("/api/events/mailing-list/{row_id}")
def delete_subscriber(row_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventMailingList WHERE RowID = :id"), {"id": row_id})
    db.commit()
    return {"ok": True}


# ─── Bulk import (CSV upload) ───────────────────────────────────────

@router.post("/api/events/{event_id}/mailing-list/import")
async def import_csv(event_id: int,
                     file: UploadFile = File(...),
                     source: str = Form("import"),
                     db: Session = Depends(get_db)):
    """Accept a CSV with an 'email' column (case-insensitive) and optional 'name', 'tags'.

    Existing emails for this event are updated (name/tags filled in if empty); new
    ones are inserted. OptedOutDate is cleared on re-import so they re-subscribe.
    """
    content = await file.read()
    try:
        txt = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        txt = content.decode("latin-1", errors="replace")
    reader = csv.DictReader(io.StringIO(txt))
    if not reader.fieldnames:
        raise HTTPException(400, "Empty or unreadable CSV")
    lowmap = {f.lower().strip(): f for f in reader.fieldnames}
    email_col = lowmap.get("email") or lowmap.get("e-mail") or lowmap.get("emailaddress")
    if not email_col:
        raise HTTPException(400, f"CSV must have an 'email' column (got: {reader.fieldnames})")
    name_col = lowmap.get("name") or lowmap.get("full name") or lowmap.get("fullname")
    tags_col = lowmap.get("tags") or lowmap.get("tag")

    added, updated, skipped = 0, 0, 0
    for row in reader:
        em = _norm_email(row.get(email_col))
        if "@" not in em:
            skipped += 1
            continue
        nm = (row.get(name_col) or "").strip() if name_col else None
        tg = (row.get(tags_col) or "").strip() if tags_col else None
        existing = db.execute(text("""
            SELECT RowID FROM OFNEventMailingList WHERE EventID = :e AND Email = :em
        """), {"e": event_id, "em": em}).mappings().first()
        if existing:
            db.execute(text("""
                UPDATE OFNEventMailingList
                   SET Name = CASE WHEN (Name IS NULL OR Name = '') AND :nm IS NOT NULL
                                   THEN :nm ELSE Name END,
                       Tags = CASE WHEN (Tags IS NULL OR Tags = '') AND :tg IS NOT NULL
                                   THEN :tg ELSE Tags END,
                       OptedOutDate = NULL
                 WHERE RowID = :id
            """), {"id": existing["RowID"], "nm": nm or None, "tg": tg or None})
            updated += 1
        else:
            db.execute(text("""
                INSERT INTO OFNEventMailingList (EventID, Email, Name, Source, Tags)
                VALUES (:e, :em, :nm, :src, :tg)
            """), {"e": event_id, "em": em, "nm": nm or None,
                   "src": source, "tg": tg or None})
            added += 1
    db.commit()
    return {"added": added, "updated": updated, "skipped": skipped}


@router.post("/api/events/{event_id}/mailing-list/import-contacts")
def import_from_contacts(event_id: int, db: Session = Depends(get_db)):
    """One-click import: pulls email addresses from the host business's team,
    from past-event attendees for the same business, and from marketplace
    customers who have bought from this business. Never overwrites opt-outs."""
    ev = db.execute(text("""
        SELECT EventID, BusinessID, EventName FROM OFNEvents WHERE EventID = :e
    """), {"e": event_id}).mappings().first()
    if not ev:
        raise HTTPException(404, "Event not found")
    biz_id = ev.get("BusinessID")
    candidates: dict[str, dict] = {}

    def add(email: str, name: str | None, source: str):
        em = _norm_email(email)
        if "@" not in em:
            return
        if em in candidates:
            return
        candidates[em] = {"email": em, "name": (name or "").strip() or None, "source": source}

    if biz_id:
        for r in db.execute(text("""
            SELECT p.PeopleEmail, p.PeopleFirstName, p.PeopleLastName
              FROM BusinessAccess ba
              JOIN People p ON p.PeopleID = ba.PeopleID
             WHERE ba.BusinessID = :b AND ba.Active = 1
        """), {"b": biz_id}).mappings().all():
            add(r["PeopleEmail"],
                " ".join(filter(None, [r.get("PeopleFirstName"), r.get("PeopleLastName")])),
                "team")
        for r in db.execute(text("""
            SELECT DISTINCT c.AttendeeEmail AS Email,
                   c.AttendeeFirstName AS F, c.AttendeeLastName AS L
              FROM OFNEventRegistrationCart c
              JOIN OFNEvents ev ON ev.EventID = c.EventID
             WHERE ev.BusinessID = :b AND c.Status = 'paid'
        """), {"b": biz_id}).mappings().all():
            add(r["Email"], " ".join(filter(None, [r.get("F"), r.get("L")])), "past_attendee")
    # Marketplace customers — only if the marketplace order has an email
    try:
        for r in db.execute(text("""
            SELECT DISTINCT o.BuyerEmail AS Email, p.PeopleFirstName AS F, p.PeopleLastName AS L
              FROM MarketplaceOrders o
              LEFT JOIN People p ON p.PeopleID = o.BuyerPeopleID
             WHERE o.SellerBusinessID = :b
               AND o.Status IN ('paid', 'fulfilled', 'shipped', 'delivered')
        """), {"b": biz_id}).mappings().all():
            add(r["Email"], " ".join(filter(None, [r.get("F"), r.get("L")])), "marketplace")
    except Exception:
        pass

    added, updated = 0, 0
    for c in candidates.values():
        existing = db.execute(text("""
            SELECT RowID, OptedOutDate FROM OFNEventMailingList
             WHERE EventID = :e AND Email = :em
        """), {"e": event_id, "em": c["email"]}).mappings().first()
        if existing:
            if existing.get("OptedOutDate"):
                continue
            db.execute(text("""
                UPDATE OFNEventMailingList
                   SET Name   = CASE WHEN (Name IS NULL OR Name = '') AND :nm IS NOT NULL THEN :nm ELSE Name END,
                       Source = COALESCE(Source, :src)
                 WHERE RowID = :id
            """), {"id": existing["RowID"], "nm": c["name"], "src": c["source"]})
            updated += 1
        else:
            db.execute(text("""
                INSERT INTO OFNEventMailingList (EventID, Email, Name, Source)
                VALUES (:e, :em, :nm, :src)
            """), {"e": event_id, "em": c["email"], "nm": c["name"], "src": c["source"]})
            added += 1
    db.commit()
    return {"added": added, "updated": updated, "candidates": len(candidates)}
