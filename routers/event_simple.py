"""
Simple event types (shared admin).

Handles Seminar, Free Event, Basic Event, Workshop/Clinic, Webinar/Online Class,
and Networking Event. These all share a registration/capacity/payment model; the
organizer admin UI shows / hides fields based on the event's EventType.

Per-type differentiators stored on OFNEventSimpleConfig:
  - Seminar / Workshop / Webinar: Speaker + recording + handouts
  - Workshop: MaterialsList, SkillLevel, CertificateEnabled
  - Webinar: StreamingLink, TimezoneNote
  - Networking: IcebreakerPrompts, DirectoryVisible
  - Free Event: IsFree toggled, no payment processing
"""
from fastapi import APIRouter, Depends, HTTPException
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal
from datetime import date

try:
    from event_emails import send_registration_confirmation
except Exception:  # pragma: no cover
    def send_registration_confirmation(*a, **kw): return False

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventSimpleConfig')
        CREATE TABLE OFNEventSimpleConfig (
            ConfigID             INT IDENTITY(1,1) PRIMARY KEY,
            EventID              INT NOT NULL UNIQUE,
            Description          NVARCHAR(MAX),
            IsFree               BIT DEFAULT 0,
            PriceAdult           DECIMAL(10,2) DEFAULT 0,
            PriceChild           DECIMAL(10,2),
            EarlyBirdPrice       DECIMAL(10,2),
            EarlyBirdEndDate     DATE,
            MaxAttendees         INT,
            WaitlistEnabled      BIT DEFAULT 1,
            RegistrationEndDate  DATE,
            SpeakerName          NVARCHAR(300),
            SpeakerBio           NVARCHAR(MAX),
            SpeakerPhoto         NVARCHAR(500),
            MaterialsList        NVARCHAR(MAX),
            SkillLevel           NVARCHAR(100),
            CertificateEnabled   BIT DEFAULT 0,
            StreamingLink        NVARCHAR(500),
            StreamingPlatform    NVARCHAR(100),
            RecordingLink        NVARCHAR(500),
            HandoutLink          NVARCHAR(500),
            TimezoneNote         NVARCHAR(200),
            IcebreakerPrompts    NVARCHAR(MAX),
            DirectoryVisible     BIT DEFAULT 0,
            PrepEmailSubject     NVARCHAR(300),
            PrepEmailBody        NVARCHAR(MAX),
            IsActive             BIT DEFAULT 1,
            CreatedDate          DATETIME DEFAULT GETDATE(),
            UpdatedDate          DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventSimpleRegistrations')
        CREATE TABLE OFNEventSimpleRegistrations (
            RegID               INT IDENTITY(1,1) PRIMARY KEY,
            EventID             INT NOT NULL,
            PeopleID            INT,
            BusinessID          INT,
            GuestName           NVARCHAR(300) NOT NULL,
            GuestEmail          NVARCHAR(300),
            GuestPhone          NVARCHAR(50),
            PartySize           INT DEFAULT 1,
            ChildCount          INT DEFAULT 0,
            NameTagTitle        NVARCHAR(300),
            DietaryRestrictions NVARCHAR(MAX),
            SpecialRequests     NVARCHAR(MAX),
            TicketType          NVARCHAR(100),
            TotalFee            DECIMAL(10,2) DEFAULT 0,
            PaidStatus          NVARCHAR(20) DEFAULT 'pending',
            Status              NVARCHAR(50) DEFAULT 'confirmed',
            CheckedIn           BIT DEFAULT 0,
            CheckedInAt         DATETIME,
            CertificateIssued   BIT DEFAULT 0,
            OrganizerNotes      NVARCHAR(MAX),
            CreatedDate         DATETIME DEFAULT GETDATE(),
            UpdatedDate         DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


try:
    with SessionLocal() as _db:
        ensure_tables(_db)
except Exception as e:
    print(f"[event_simple] Table ensure warning: {e}")


def _fee(cfg: dict, party_size: int, child_count: int) -> float:
    if cfg.get("IsFree"):
        return 0.0
    party = int(party_size or 0)
    kids = min(int(child_count or 0), party)
    adults = max(0, party - kids)

    adult_price = float(cfg.get("PriceAdult") or 0)
    eb_price = cfg.get("EarlyBirdPrice")
    eb_end = cfg.get("EarlyBirdEndDate")
    if eb_price is not None and eb_end and date.today() <= eb_end:
        adult_price = float(eb_price)

    child_price = cfg.get("PriceChild")
    child_price = float(child_price) if child_price is not None else adult_price
    return adults * adult_price + kids * child_price


# ---------- CONFIG ----------

@router.get("/api/events/{event_id}/simple/config")
def get_config(event_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT * FROM OFNEventSimpleConfig WHERE EventID=:e"),
                    {"e": event_id}).fetchone()
    booked = db.execute(text("""
        SELECT COALESCE(SUM(PartySize), 0) FROM OFNEventSimpleRegistrations
        WHERE EventID=:e AND Status='confirmed'
    """), {"e": event_id}).fetchone()[0] or 0
    waitlist = db.execute(text("""
        SELECT COUNT(*) FROM OFNEventSimpleRegistrations WHERE EventID=:e AND Status='waitlist'
    """), {"e": event_id}).fetchone()[0] or 0
    if not row:
        return {"configured": False, "EventID": event_id,
                "AttendeesBooked": int(booked), "WaitlistCount": int(waitlist)}
    cfg = dict(row._mapping)
    cfg["configured"] = True
    cfg["AttendeesBooked"] = int(booked)
    cfg["WaitlistCount"] = int(waitlist)
    return cfg


@router.put("/api/events/{event_id}/simple/config")
def put_config(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    exists = db.execute(text("SELECT ConfigID FROM OFNEventSimpleConfig WHERE EventID=:e"),
                       {"e": event_id}).fetchone()
    params = {
        "e": event_id,
        "d": body.get("Description"),
        "f": 1 if body.get("IsFree") else 0,
        "pa": body.get("PriceAdult") or 0,
        "pc": body.get("PriceChild"),
        "eb": body.get("EarlyBirdPrice"),
        "ebe": body.get("EarlyBirdEndDate"),
        "ma": body.get("MaxAttendees"),
        "wl": 1 if body.get("WaitlistEnabled", True) else 0,
        "red": body.get("RegistrationEndDate"),
        "sn": body.get("SpeakerName"),
        "sb": body.get("SpeakerBio"),
        "sp": body.get("SpeakerPhoto"),
        "ml": body.get("MaterialsList"),
        "sl": body.get("SkillLevel"),
        "ce": 1 if body.get("CertificateEnabled") else 0,
        "stl": body.get("StreamingLink"),
        "stp": body.get("StreamingPlatform"),
        "rl": body.get("RecordingLink"),
        "hl": body.get("HandoutLink"),
        "tz": body.get("TimezoneNote"),
        "ibp": body.get("IcebreakerPrompts"),
        "dv": 1 if body.get("DirectoryVisible") else 0,
        "pes": body.get("PrepEmailSubject"),
        "peb": body.get("PrepEmailBody"),
        "a": 1 if body.get("IsActive", True) else 0,
    }
    if exists:
        db.execute(text("""
            UPDATE OFNEventSimpleConfig SET
              Description=:d, IsFree=:f, PriceAdult=:pa, PriceChild=:pc,
              EarlyBirdPrice=:eb, EarlyBirdEndDate=:ebe, MaxAttendees=:ma,
              WaitlistEnabled=:wl, RegistrationEndDate=:red,
              SpeakerName=:sn, SpeakerBio=:sb, SpeakerPhoto=:sp,
              MaterialsList=:ml, SkillLevel=:sl, CertificateEnabled=:ce,
              StreamingLink=:stl, StreamingPlatform=:stp,
              RecordingLink=:rl, HandoutLink=:hl, TimezoneNote=:tz,
              IcebreakerPrompts=:ibp, DirectoryVisible=:dv,
              PrepEmailSubject=:pes, PrepEmailBody=:peb,
              IsActive=:a, UpdatedDate=GETDATE()
            WHERE EventID=:e
        """), params)
    else:
        db.execute(text("""
            INSERT INTO OFNEventSimpleConfig
              (EventID, Description, IsFree, PriceAdult, PriceChild,
               EarlyBirdPrice, EarlyBirdEndDate, MaxAttendees, WaitlistEnabled,
               RegistrationEndDate, SpeakerName, SpeakerBio, SpeakerPhoto,
               MaterialsList, SkillLevel, CertificateEnabled,
               StreamingLink, StreamingPlatform, RecordingLink, HandoutLink, TimezoneNote,
               IcebreakerPrompts, DirectoryVisible,
               PrepEmailSubject, PrepEmailBody, IsActive)
            VALUES (:e, :d, :f, :pa, :pc, :eb, :ebe, :ma, :wl, :red,
                    :sn, :sb, :sp, :ml, :sl, :ce, :stl, :stp, :rl, :hl, :tz,
                    :ibp, :dv, :pes, :peb, :a)
        """), params)
    db.commit()
    return {"ok": True}


# ---------- REGISTRATIONS ----------

@router.get("/api/events/{event_id}/simple/registrations")
def list_registrations(event_id: int, people_id: int | None = None,
                       db: Session = Depends(get_db)):
    filters = ["EventID = :e"]
    params = {"e": event_id}
    if people_id:
        filters.append("PeopleID = :p")
        params["p"] = people_id
    where = " AND ".join(filters)
    rows = db.execute(text(f"""
        SELECT * FROM OFNEventSimpleRegistrations
        WHERE {where}
        ORDER BY
          CASE Status WHEN 'confirmed' THEN 0 WHEN 'waitlist' THEN 1 ELSE 2 END,
          CreatedDate DESC
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/api/events/{event_id}/simple/directory")
def directory(event_id: int, db: Session = Depends(get_db)):
    """Attendee directory for Networking Event (only if DirectoryVisible)."""
    cfg_row = db.execute(text("SELECT DirectoryVisible FROM OFNEventSimpleConfig WHERE EventID=:e"),
                        {"e": event_id}).fetchone()
    if not cfg_row or not cfg_row[0]:
        return []
    rows = db.execute(text("""
        SELECT RegID, GuestName, NameTagTitle, BusinessID
        FROM OFNEventSimpleRegistrations
        WHERE EventID=:e AND Status='confirmed'
        ORDER BY GuestName
    """), {"e": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/simple/registrations")
def add_registration(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    cfg_row = db.execute(text("SELECT * FROM OFNEventSimpleConfig WHERE EventID=:e"),
                        {"e": event_id}).fetchone()
    if not cfg_row:
        raise HTTPException(400, "Event not configured")
    cfg = dict(cfg_row._mapping)
    if cfg.get("RegistrationEndDate") and cfg["RegistrationEndDate"] < date.today():
        raise HTTPException(400, "Registration has closed")
    if not body.get("GuestName"):
        raise HTTPException(400, "GuestName required")

    party = int(body.get("PartySize") or 1)
    kids = int(body.get("ChildCount") or 0)

    status = "confirmed"
    if cfg.get("MaxAttendees"):
        booked = db.execute(text("""
            SELECT COALESCE(SUM(PartySize), 0) FROM OFNEventSimpleRegistrations
            WHERE EventID=:e AND Status='confirmed'
        """), {"e": event_id}).fetchone()[0] or 0
        if int(booked) + party > int(cfg["MaxAttendees"]):
            if cfg.get("WaitlistEnabled"):
                status = "waitlist"
            else:
                raise HTTPException(400, "Event is full")

    fee = _fee(cfg, party, kids)

    ticket_type = "general"
    if cfg.get("EarlyBirdPrice") is not None and cfg.get("EarlyBirdEndDate") and date.today() <= cfg["EarlyBirdEndDate"]:
        ticket_type = "early-bird"

    r = db.execute(text("""
        INSERT INTO OFNEventSimpleRegistrations
          (EventID, PeopleID, BusinessID, GuestName, GuestEmail, GuestPhone,
           PartySize, ChildCount, NameTagTitle, DietaryRestrictions, SpecialRequests,
           TicketType, TotalFee, Status)
        VALUES (:e, :p, :b, :gn, :ge, :gp, :ps, :cc, :nt, :dr, :sr, :tt, :f, :s);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "e": event_id, "p": body.get("PeopleID"), "b": body.get("BusinessID"),
        "gn": body.get("GuestName"), "ge": body.get("GuestEmail"), "gp": body.get("GuestPhone"),
        "ps": party, "cc": kids,
        "nt": body.get("NameTagTitle"),
        "dr": body.get("DietaryRestrictions"),
        "sr": body.get("SpecialRequests"),
        "tt": ticket_type, "f": fee, "s": status,
    })
    new_id = int(r.fetchone()[0])
    db.commit()

    if body.get("GuestEmail"):
        ev = db.execute(text("""
            SELECT EventID, EventName, EventStartDate, EventLocationName,
                   EventLocationStreet, EventLocationCity, EventLocationState, EventLocationZip
              FROM OFNEvents WHERE EventID = :e
        """), {"e": event_id}).mappings().first()
        extra = f'<p style="font-size:13px;color:#555"><strong>Fee:</strong> ${fee:.2f} · <strong>Status:</strong> {status}</p>' if fee else ''
        try:
            send_registration_confirmation(
                to_email=body["GuestEmail"], attendee_name=body.get("GuestName") or '',
                event=dict(ev) if ev else {"EventID": event_id},
                kind="Simple", reg_id=new_id, extra_html=extra,
            )
        except Exception as ex:
            print(f"[event_simple] email send failed: {ex}")

    return {"RegID": new_id, "TotalFee": fee, "Status": status}


@router.put("/api/events/simple/registrations/{reg_id}")
def update_registration(reg_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    reg = db.execute(text("SELECT * FROM OFNEventSimpleRegistrations WHERE RegID=:r"),
                    {"r": reg_id}).fetchone()
    if not reg:
        raise HTTPException(404, "Not found")
    reg_d = dict(reg._mapping)
    db.execute(text("""
        UPDATE OFNEventSimpleRegistrations SET
          GuestName=:gn, GuestEmail=:ge, GuestPhone=:gp,
          PaidStatus=:pd, Status=:st, OrganizerNotes=:on,
          CertificateIssued=:ci, UpdatedDate=GETDATE()
        WHERE RegID=:r
    """), {
        "r": reg_id,
        "gn": body.get("GuestName", reg_d.get("GuestName")),
        "ge": body.get("GuestEmail", reg_d.get("GuestEmail")),
        "gp": body.get("GuestPhone", reg_d.get("GuestPhone")),
        "pd": body.get("PaidStatus", reg_d.get("PaidStatus") or "pending"),
        "st": body.get("Status", reg_d.get("Status") or "confirmed"),
        "on": body.get("OrganizerNotes", reg_d.get("OrganizerNotes")),
        "ci": 1 if body.get("CertificateIssued", reg_d.get("CertificateIssued")) else 0,
    })
    db.commit()
    return {"ok": True}


@router.put("/api/events/simple/registrations/{reg_id}/checkin")
def checkin(reg_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    checked = 1 if body.get("CheckedIn", True) else 0
    db.execute(text("""
        UPDATE OFNEventSimpleRegistrations SET
          CheckedIn=:c,
          CheckedInAt = CASE WHEN :c = 1 THEN GETDATE() ELSE NULL END,
          UpdatedDate=GETDATE()
        WHERE RegID=:r
    """), {"r": reg_id, "c": checked})
    db.commit()
    return {"ok": True}


@router.delete("/api/events/simple/registrations/{reg_id}")
def delete_registration(reg_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventSimpleRegistrations WHERE RegID=:r"), {"r": reg_id})
    db.commit()
    return {"ok": True}
