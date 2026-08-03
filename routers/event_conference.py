"""
Conference (multi-day, multi-track).

Organizer defines tracks (Business, Genetics, Fiber, etc.), rooms, and sessions
scheduled across them. Speakers are managed with bios. Attendees register at a
pricing tier (early-bird / regular / late) and get a badge on check-in.
"""
from fastapi import APIRouter, Depends, HTTPException
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal
from datetime import date, datetime

try:
    from event_emails import send_registration_confirmation
except Exception:  # pragma: no cover
    def send_registration_confirmation(*a, **kw): return False

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventConferenceConfig')
        CREATE TABLE OFNEventConferenceConfig (
            ConfigID              INT IDENTITY(1,1) PRIMARY KEY,
            EventID               INT NOT NULL UNIQUE,
            Description           NVARCHAR(MAX),
            EarlyBirdPrice        DECIMAL(10,2),
            EarlyBirdEndDate      DATE,
            RegularPrice          DECIMAL(10,2) DEFAULT 0,
            LatePrice             DECIMAL(10,2),
            LateStartDate         DATE,
            OneDayPrice           DECIMAL(10,2),
            MaxAttendees          INT,
            RegistrationEndDate   DATE,
            VenueNotes            NVARCHAR(MAX),
            BadgePrintingEnabled  BIT DEFAULT 1,
            IsActive              BIT DEFAULT 1,
            CreatedDate           DATETIME DEFAULT GETDATE(),
            UpdatedDate           DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventConferenceTracks')
        CREATE TABLE OFNEventConferenceTracks (
            TrackID      INT IDENTITY(1,1) PRIMARY KEY,
            EventID      INT NOT NULL,
            TrackName    NVARCHAR(200) NOT NULL,
            TrackColor   NVARCHAR(20) DEFAULT '#3D6B34',
            Description  NVARCHAR(MAX),
            DisplayOrder INT DEFAULT 0,
            CreatedDate  DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventConferenceRooms')
        CREATE TABLE OFNEventConferenceRooms (
            RoomID       INT IDENTITY(1,1) PRIMARY KEY,
            EventID      INT NOT NULL,
            RoomName     NVARCHAR(200) NOT NULL,
            Capacity     INT,
            Notes        NVARCHAR(MAX),
            CreatedDate  DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventConferenceSpeakers')
        CREATE TABLE OFNEventConferenceSpeakers (
            SpeakerID    INT IDENTITY(1,1) PRIMARY KEY,
            EventID      INT NOT NULL,
            SpeakerName  NVARCHAR(300) NOT NULL,
            Title        NVARCHAR(300),
            Company      NVARCHAR(300),
            Bio          NVARCHAR(MAX),
            PhotoURL     NVARCHAR(500),
            Email        NVARCHAR(300),
            CreatedDate  DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventConferenceSessions')
        CREATE TABLE OFNEventConferenceSessions (
            SessionID     INT IDENTITY(1,1) PRIMARY KEY,
            EventID       INT NOT NULL,
            TrackID       INT,
            RoomID        INT,
            Title         NVARCHAR(500) NOT NULL,
            Description   NVARCHAR(MAX),
            SessionStart  DATETIME NOT NULL,
            DurationMin   INT DEFAULT 60,
            SessionType   NVARCHAR(50) DEFAULT 'Breakout',
            Capacity      INT,
            CreatedDate   DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventConferenceSessionSpeakers')
        CREATE TABLE OFNEventConferenceSessionSpeakers (
            LinkID       INT IDENTITY(1,1) PRIMARY KEY,
            SessionID    INT NOT NULL,
            SpeakerID    INT NOT NULL,
            RoleLabel    NVARCHAR(100) DEFAULT 'Speaker'
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventConferenceRegistrations')
        CREATE TABLE OFNEventConferenceRegistrations (
            RegID           INT IDENTITY(1,1) PRIMARY KEY,
            EventID         INT NOT NULL,
            PeopleID        INT,
            BusinessID      INT,
            GuestName       NVARCHAR(300) NOT NULL,
            GuestEmail      NVARCHAR(300),
            GuestPhone      NVARCHAR(50),
            Company         NVARCHAR(300),
            BadgeTitle      NVARCHAR(300),
            TicketTier      NVARCHAR(50) DEFAULT 'regular',
            TotalFee        DECIMAL(10,2) DEFAULT 0,
            PaidStatus      NVARCHAR(20) DEFAULT 'pending',
            Status          NVARCHAR(50) DEFAULT 'confirmed',
            CheckedIn       BIT DEFAULT 0,
            CheckedInAt     DATETIME,
            BadgeCode       NVARCHAR(50),
            DietaryRestrictions NVARCHAR(MAX),
            SpecialRequests NVARCHAR(MAX),
            OrganizerNotes  NVARCHAR(MAX),
            CreatedDate     DATETIME DEFAULT GETDATE(),
            UpdatedDate     DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventConferenceAttendance')
        CREATE TABLE OFNEventConferenceAttendance (
            AttendanceID INT IDENTITY(1,1) PRIMARY KEY,
            SessionID    INT NOT NULL,
            RegID        INT NOT NULL,
            CheckedInAt  DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


try:
    with SessionLocal() as _db:
        ensure_tables(_db)
except Exception as e:
    print(f"[event_conference] Table ensure warning: {e}")


def _current_tier(cfg: dict) -> tuple[str, float]:
    today = date.today()
    if cfg.get("EarlyBirdPrice") is not None and cfg.get("EarlyBirdEndDate") and today <= cfg["EarlyBirdEndDate"]:
        return "early-bird", float(cfg["EarlyBirdPrice"])
    if cfg.get("LatePrice") is not None and cfg.get("LateStartDate") and today >= cfg["LateStartDate"]:
        return "late", float(cfg["LatePrice"])
    return "regular", float(cfg.get("RegularPrice") or 0)


# ---------- CONFIG ----------

@router.get("/api/events/{event_id}/conference/config")
def get_config(event_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT * FROM OFNEventConferenceConfig WHERE EventID=:e"),
                    {"e": event_id}).fetchone()
    if not row:
        return {"configured": False, "EventID": event_id}
    cfg = dict(row._mapping)
    cfg["configured"] = True
    tier, price = _current_tier(cfg)
    cfg["CurrentTier"] = tier
    cfg["CurrentPrice"] = price
    reg_count = db.execute(text("""
        SELECT COUNT(*) FROM OFNEventConferenceRegistrations WHERE EventID=:e AND Status='confirmed'
    """), {"e": event_id}).fetchone()[0] or 0
    cfg["Registered"] = int(reg_count)
    return cfg


@router.put("/api/events/{event_id}/conference/config")
def put_config(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    exists = db.execute(text("SELECT ConfigID FROM OFNEventConferenceConfig WHERE EventID=:e"),
                       {"e": event_id}).fetchone()
    params = {
        "e": event_id, "d": body.get("Description"),
        "ebp": body.get("EarlyBirdPrice"),
        "ebe": body.get("EarlyBirdEndDate"),
        "rp": body.get("RegularPrice") or 0,
        "lp": body.get("LatePrice"),
        "lsd": body.get("LateStartDate"),
        "odp": body.get("OneDayPrice"),
        "ma": body.get("MaxAttendees"),
        "red": body.get("RegistrationEndDate"),
        "vn": body.get("VenueNotes"),
        "bp": 1 if body.get("BadgePrintingEnabled", True) else 0,
        "a": 1 if body.get("IsActive", True) else 0,
    }
    if exists:
        db.execute(text("""
            UPDATE OFNEventConferenceConfig SET
              Description=:d, EarlyBirdPrice=:ebp, EarlyBirdEndDate=:ebe,
              RegularPrice=:rp, LatePrice=:lp, LateStartDate=:lsd, OneDayPrice=:odp,
              MaxAttendees=:ma, RegistrationEndDate=:red, VenueNotes=:vn,
              BadgePrintingEnabled=:bp, IsActive=:a, UpdatedDate=GETDATE()
            WHERE EventID=:e
        """), params)
    else:
        db.execute(text("""
            INSERT INTO OFNEventConferenceConfig
              (EventID, Description, EarlyBirdPrice, EarlyBirdEndDate, RegularPrice,
               LatePrice, LateStartDate, OneDayPrice, MaxAttendees, RegistrationEndDate,
               VenueNotes, BadgePrintingEnabled, IsActive)
            VALUES (:e, :d, :ebp, :ebe, :rp, :lp, :lsd, :odp, :ma, :red, :vn, :bp, :a)
        """), params)
    db.commit()
    return {"ok": True}


# ---------- TRACKS ----------

@router.get("/api/events/{event_id}/conference/tracks")
def list_tracks(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT * FROM OFNEventConferenceTracks WHERE EventID=:e ORDER BY DisplayOrder, TrackName
    """), {"e": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/conference/tracks")
def add_track(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    if not body.get("TrackName"):
        raise HTTPException(400, "TrackName required")
    r = db.execute(text("""
        INSERT INTO OFNEventConferenceTracks (EventID, TrackName, TrackColor, Description, DisplayOrder)
        VALUES (:e, :n, :c, :d, :o);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "e": event_id, "n": body["TrackName"],
        "c": body.get("TrackColor") or "#3D6B34",
        "d": body.get("Description"), "o": body.get("DisplayOrder") or 0,
    })
    db.commit()
    return {"TrackID": int(r.fetchone()[0])}


@router.put("/api/events/conference/tracks/{track_id}")
def update_track(track_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventConferenceTracks SET
          TrackName=:n, TrackColor=:c, Description=:d, DisplayOrder=:o
        WHERE TrackID=:t
    """), {
        "t": track_id, "n": body.get("TrackName"),
        "c": body.get("TrackColor") or "#3D6B34",
        "d": body.get("Description"), "o": body.get("DisplayOrder") or 0,
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/conference/tracks/{track_id}")
def delete_track(track_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE OFNEventConferenceSessions SET TrackID=NULL WHERE TrackID=:t"),
              {"t": track_id})
    db.execute(text("DELETE FROM OFNEventConferenceTracks WHERE TrackID=:t"), {"t": track_id})
    db.commit()
    return {"ok": True}


# ---------- ROOMS ----------

@router.get("/api/events/{event_id}/conference/rooms")
def list_rooms(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT * FROM OFNEventConferenceRooms WHERE EventID=:e ORDER BY RoomName
    """), {"e": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/conference/rooms")
def add_room(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    if not body.get("RoomName"):
        raise HTTPException(400, "RoomName required")
    r = db.execute(text("""
        INSERT INTO OFNEventConferenceRooms (EventID, RoomName, Capacity, Notes)
        VALUES (:e, :n, :c, :no);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {"e": event_id, "n": body["RoomName"], "c": body.get("Capacity"), "no": body.get("Notes")})
    db.commit()
    return {"RoomID": int(r.fetchone()[0])}


@router.put("/api/events/conference/rooms/{room_id}")
def update_room(room_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("UPDATE OFNEventConferenceRooms SET RoomName=:n, Capacity=:c, Notes=:no WHERE RoomID=:r"),
              {"r": room_id, "n": body.get("RoomName"), "c": body.get("Capacity"), "no": body.get("Notes")})
    db.commit()
    return {"ok": True}


@router.delete("/api/events/conference/rooms/{room_id}")
def delete_room(room_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE OFNEventConferenceSessions SET RoomID=NULL WHERE RoomID=:r"), {"r": room_id})
    db.execute(text("DELETE FROM OFNEventConferenceRooms WHERE RoomID=:r"), {"r": room_id})
    db.commit()
    return {"ok": True}


# ---------- SPEAKERS ----------

@router.get("/api/events/{event_id}/conference/speakers")
def list_speakers(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT * FROM OFNEventConferenceSpeakers WHERE EventID=:e ORDER BY SpeakerName
    """), {"e": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/conference/speakers")
def add_speaker(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    if not body.get("SpeakerName"):
        raise HTTPException(400, "SpeakerName required")
    r = db.execute(text("""
        INSERT INTO OFNEventConferenceSpeakers
          (EventID, SpeakerName, Title, Company, Bio, PhotoURL, Email)
        VALUES (:e, :n, :t, :c, :b, :p, :em);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "e": event_id, "n": body["SpeakerName"],
        "t": body.get("Title"), "c": body.get("Company"),
        "b": body.get("Bio"), "p": body.get("PhotoURL"), "em": body.get("Email"),
    })
    db.commit()
    return {"SpeakerID": int(r.fetchone()[0])}


@router.put("/api/events/conference/speakers/{speaker_id}")
def update_speaker(speaker_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventConferenceSpeakers SET
          SpeakerName=:n, Title=:t, Company=:c, Bio=:b, PhotoURL=:p, Email=:em
        WHERE SpeakerID=:s
    """), {
        "s": speaker_id, "n": body.get("SpeakerName"),
        "t": body.get("Title"), "c": body.get("Company"),
        "b": body.get("Bio"), "p": body.get("PhotoURL"), "em": body.get("Email"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/conference/speakers/{speaker_id}")
def delete_speaker(speaker_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventConferenceSessionSpeakers WHERE SpeakerID=:s"), {"s": speaker_id})
    db.execute(text("DELETE FROM OFNEventConferenceSpeakers WHERE SpeakerID=:s"), {"s": speaker_id})
    db.commit()
    return {"ok": True}


# ---------- SESSIONS ----------

@router.get("/api/events/{event_id}/conference/sessions")
def list_sessions(event_id: int, db: Session = Depends(get_db)):
    sess_rows = db.execute(text("""
        SELECT s.*, t.TrackName, t.TrackColor, r.RoomName,
          (SELECT COUNT(*) FROM OFNEventConferenceAttendance a WHERE a.SessionID = s.SessionID) AS AttendeeCount
        FROM OFNEventConferenceSessions s
        LEFT JOIN OFNEventConferenceTracks t ON t.TrackID = s.TrackID
        LEFT JOIN OFNEventConferenceRooms r ON r.RoomID = s.RoomID
        WHERE s.EventID=:e
        ORDER BY s.SessionStart
    """), {"e": event_id}).fetchall()
    sessions = [dict(s._mapping) for s in sess_rows]
    if sessions:
        ids = [s["SessionID"] for s in sessions]
        placeholders = ", ".join(f":s{i}" for i in range(len(ids)))
        params_s = {f"s{i}": sid for i, sid in enumerate(ids)}
        spk_rows = db.execute(text(f"""
            SELECT ss.SessionID, ss.RoleLabel, sp.SpeakerID, sp.SpeakerName, sp.Title, sp.Company
            FROM OFNEventConferenceSessionSpeakers ss
            JOIN OFNEventConferenceSpeakers sp ON sp.SpeakerID = ss.SpeakerID
            WHERE ss.SessionID IN ({placeholders})
        """), params_s).fetchall()
        by_sess: dict = {}
        for r in spk_rows:
            d = dict(r._mapping)
            by_sess.setdefault(d["SessionID"], []).append(d)
        for s in sessions:
            s["Speakers"] = by_sess.get(s["SessionID"], [])
    return sessions


@router.post("/api/events/{event_id}/conference/sessions")
def add_session(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    if not body.get("Title") or not body.get("SessionStart"):
        raise HTTPException(400, "Title and SessionStart required")
    r = db.execute(text("""
        INSERT INTO OFNEventConferenceSessions
          (EventID, TrackID, RoomID, Title, Description, SessionStart, DurationMin, SessionType, Capacity)
        VALUES (:e, :t, :r, :ti, :d, :ss, :dm, :st, :c);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "e": event_id,
        "t": body.get("TrackID") or None,
        "r": body.get("RoomID") or None,
        "ti": body["Title"], "d": body.get("Description"),
        "ss": body["SessionStart"],
        "dm": body.get("DurationMin") or 60,
        "st": body.get("SessionType") or "Breakout",
        "c": body.get("Capacity"),
    })
    new_id = int(r.fetchone()[0])
    for sp in (body.get("SpeakerIDs") or []):
        db.execute(text("""
            INSERT INTO OFNEventConferenceSessionSpeakers (SessionID, SpeakerID, RoleLabel)
            VALUES (:s, :sp, :rl)
        """), {"s": new_id, "sp": int(sp), "rl": "Speaker"})
    db.commit()
    return {"SessionID": new_id}


@router.put("/api/events/conference/sessions/{session_id}")
def update_session(session_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventConferenceSessions SET
          TrackID=:t, RoomID=:r, Title=:ti, Description=:d,
          SessionStart=:ss, DurationMin=:dm, SessionType=:st, Capacity=:c
        WHERE SessionID=:s
    """), {
        "s": session_id,
        "t": body.get("TrackID") or None,
        "r": body.get("RoomID") or None,
        "ti": body.get("Title"), "d": body.get("Description"),
        "ss": body.get("SessionStart"),
        "dm": body.get("DurationMin") or 60,
        "st": body.get("SessionType") or "Breakout",
        "c": body.get("Capacity"),
    })
    if "SpeakerIDs" in body:
        db.execute(text("DELETE FROM OFNEventConferenceSessionSpeakers WHERE SessionID=:s"),
                  {"s": session_id})
        for sp in (body.get("SpeakerIDs") or []):
            db.execute(text("""
                INSERT INTO OFNEventConferenceSessionSpeakers (SessionID, SpeakerID, RoleLabel)
                VALUES (:s, :sp, :rl)
            """), {"s": session_id, "sp": int(sp), "rl": "Speaker"})
    db.commit()
    return {"ok": True}


@router.delete("/api/events/conference/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventConferenceSessionSpeakers WHERE SessionID=:s"), {"s": session_id})
    db.execute(text("DELETE FROM OFNEventConferenceAttendance WHERE SessionID=:s"), {"s": session_id})
    db.execute(text("DELETE FROM OFNEventConferenceSessions WHERE SessionID=:s"), {"s": session_id})
    db.commit()
    return {"ok": True}


# ---------- REGISTRATIONS ----------

@router.get("/api/events/{event_id}/conference/registrations")
def list_registrations(event_id: int, people_id: int | None = None,
                       db: Session = Depends(get_db)):
    filters = ["EventID = :e"]
    params = {"e": event_id}
    if people_id:
        filters.append("PeopleID = :p")
        params["p"] = people_id
    where = " AND ".join(filters)
    rows = db.execute(text(f"""
        SELECT * FROM OFNEventConferenceRegistrations
        WHERE {where}
        ORDER BY CreatedDate DESC
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/conference/registrations")
def add_registration(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    cfg_row = db.execute(text("SELECT * FROM OFNEventConferenceConfig WHERE EventID=:e"),
                        {"e": event_id}).fetchone()
    if not cfg_row:
        raise HTTPException(400, "Conference not configured")
    cfg = dict(cfg_row._mapping)
    if cfg.get("RegistrationEndDate") and cfg["RegistrationEndDate"] < date.today():
        raise HTTPException(400, "Registration has closed")
    if not body.get("GuestName"):
        raise HTTPException(400, "GuestName required")

    if cfg.get("MaxAttendees"):
        count = db.execute(text("""
            SELECT COUNT(*) FROM OFNEventConferenceRegistrations WHERE EventID=:e AND Status='confirmed'
        """), {"e": event_id}).fetchone()[0] or 0
        if int(count) >= int(cfg["MaxAttendees"]):
            raise HTTPException(400, "Conference is sold out")

    requested_tier = body.get("TicketTier")
    tier, price = _current_tier(cfg)
    if requested_tier == "one-day" and cfg.get("OneDayPrice") is not None:
        tier = "one-day"
        price = float(cfg["OneDayPrice"])

    badge_code = f"CONF{event_id}-{int(datetime.now().timestamp())%100000:05d}"

    r = db.execute(text("""
        INSERT INTO OFNEventConferenceRegistrations
          (EventID, PeopleID, BusinessID, GuestName, GuestEmail, GuestPhone, Company,
           BadgeTitle, TicketTier, TotalFee, BadgeCode, DietaryRestrictions, SpecialRequests)
        VALUES (:e, :p, :b, :gn, :ge, :gp, :co, :bt, :tt, :f, :bc, :dr, :sr);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "e": event_id, "p": body.get("PeopleID"), "b": body.get("BusinessID"),
        "gn": body.get("GuestName"), "ge": body.get("GuestEmail"), "gp": body.get("GuestPhone"),
        "co": body.get("Company"), "bt": body.get("BadgeTitle"),
        "tt": tier, "f": price, "bc": badge_code,
        "dr": body.get("DietaryRestrictions"),
        "sr": body.get("SpecialRequests"),
    })
    new_id = int(r.fetchone()[0])
    db.commit()

    if body.get("GuestEmail"):
        ev = db.execute(text("""
            SELECT EventID, EventName, EventStartDate, EventLocationName,
                   EventLocationStreet, EventLocationCity, EventLocationState, EventLocationZip
              FROM OFNEvents WHERE EventID = :e
        """), {"e": event_id}).mappings().first()
        extra = (f'<p style="font-size:13px;color:#555"><strong>Tier:</strong> {tier} · '
                 f'<strong>Fee:</strong> ${price:.2f} · '
                 f'<strong>Badge:</strong> {badge_code}</p>')
        try:
            send_registration_confirmation(
                to_email=body["GuestEmail"], attendee_name=body.get("GuestName") or '',
                event=dict(ev) if ev else {"EventID": event_id},
                kind="Conference", reg_id=new_id, extra_html=extra,
            )
        except Exception as ex:
            print(f"[event_conference] email send failed: {ex}")

    return {"RegID": new_id, "TotalFee": price, "TicketTier": tier, "BadgeCode": badge_code}


@router.put("/api/events/conference/registrations/{reg_id}")
def update_registration(reg_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    reg = db.execute(text("SELECT * FROM OFNEventConferenceRegistrations WHERE RegID=:r"),
                    {"r": reg_id}).fetchone()
    if not reg:
        raise HTTPException(404, "Not found")
    reg_d = dict(reg._mapping)
    db.execute(text("""
        UPDATE OFNEventConferenceRegistrations SET
          GuestName=:gn, GuestEmail=:ge, Company=:co, BadgeTitle=:bt,
          PaidStatus=:pd, Status=:st, OrganizerNotes=:on, UpdatedDate=GETDATE()
        WHERE RegID=:r
    """), {
        "r": reg_id,
        "gn": body.get("GuestName", reg_d.get("GuestName")),
        "ge": body.get("GuestEmail", reg_d.get("GuestEmail")),
        "co": body.get("Company", reg_d.get("Company")),
        "bt": body.get("BadgeTitle", reg_d.get("BadgeTitle")),
        "pd": body.get("PaidStatus", reg_d.get("PaidStatus") or "pending"),
        "st": body.get("Status", reg_d.get("Status") or "confirmed"),
        "on": body.get("OrganizerNotes", reg_d.get("OrganizerNotes")),
    })
    db.commit()
    return {"ok": True}


@router.put("/api/events/conference/registrations/{reg_id}/checkin")
def checkin(reg_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    checked = 1 if body.get("CheckedIn", True) else 0
    db.execute(text("""
        UPDATE OFNEventConferenceRegistrations SET
          CheckedIn=:c,
          CheckedInAt = CASE WHEN :c = 1 THEN GETDATE() ELSE NULL END,
          UpdatedDate=GETDATE()
        WHERE RegID=:r
    """), {"r": reg_id, "c": checked})
    db.commit()
    return {"ok": True}


@router.delete("/api/events/conference/registrations/{reg_id}")
def delete_registration(reg_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventConferenceAttendance WHERE RegID=:r"), {"r": reg_id})
    db.execute(text("DELETE FROM OFNEventConferenceRegistrations WHERE RegID=:r"), {"r": reg_id})
    db.commit()
    return {"ok": True}


# ---------- SESSION ATTENDANCE ----------

@router.post("/api/events/conference/sessions/{session_id}/attendance")
def record_attendance(session_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    reg_id = body.get("RegID")
    if not reg_id:
        raise HTTPException(400, "RegID required")
    exists = db.execute(text("""
        SELECT AttendanceID FROM OFNEventConferenceAttendance WHERE SessionID=:s AND RegID=:r
    """), {"s": session_id, "r": int(reg_id)}).fetchone()
    if exists:
        return {"ok": True, "already": True}
    db.execute(text("""
        INSERT INTO OFNEventConferenceAttendance (SessionID, RegID) VALUES (:s, :r)
    """), {"s": session_id, "r": int(reg_id)})
    db.commit()
    return {"ok": True}


@router.get("/api/events/conference/sessions/{session_id}/attendance")
def list_attendance(session_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT a.*, r.GuestName, r.Company, r.BadgeCode
        FROM OFNEventConferenceAttendance a
        JOIN OFNEventConferenceRegistrations r ON r.RegID = a.RegID
        WHERE a.SessionID=:s
        ORDER BY r.GuestName
    """), {"s": session_id}).fetchall()
    return [dict(r._mapping) for r in rows]


# ── Speaker portal ────────────────────────────────────────────────────────────
import secrets


def _ensure_speaker_accesscode(db: Session):
    row = db.execute(text("""
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME='OFNEventConferenceSpeakers' AND COLUMN_NAME='AccessCode'
    """)).fetchone()
    if not row:
        db.execute(text("ALTER TABLE OFNEventConferenceSpeakers ADD AccessCode NVARCHAR(32)"))
        db.commit()


@router.post("/api/events/conference/speakers/{speaker_id}/issue-code")
def issue_speaker_code(speaker_id: int, db: Session = Depends(get_db)):
    _ensure_speaker_accesscode(db)
    code = secrets.token_hex(6).upper()
    db.execute(text("UPDATE OFNEventConferenceSpeakers SET AccessCode=:c WHERE SpeakerID=:s"),
               {"c": code, "s": speaker_id})
    db.commit()
    return {"AccessCode": code}


@router.get("/api/events/conference/speaker/{access_code}")
def speaker_portal(access_code: str, db: Session = Depends(get_db)):
    _ensure_speaker_accesscode(db)
    sp = db.execute(text("""
        SELECT sp.*, e.EventName, e.EventStartDate, e.EventEndDate, e.EventLocationName
        FROM OFNEventConferenceSpeakers sp
        JOIN OFNEvents e ON e.EventID = sp.EventID
        WHERE sp.AccessCode = :c
    """), {"c": access_code}).mappings().first()
    if not sp:
        raise HTTPException(404, "Invalid access code")

    sessions = db.execute(text("""
        SELECT s.SessionID, s.Title, s.Description, s.SessionType, s.SessionStart,
               s.DurationMin, s.Capacity, ss.RoleLabel,
               t.TrackName, t.TrackColor, r.RoomName
        FROM OFNEventConferenceSessionSpeakers ss
        JOIN OFNEventConferenceSessions s ON s.SessionID = ss.SessionID
        LEFT JOIN OFNEventConferenceTracks t ON t.TrackID = s.TrackID
        LEFT JOIN OFNEventConferenceRooms  r ON r.RoomID  = s.RoomID
        WHERE ss.SpeakerID = :s
        ORDER BY s.SessionStart
    """), {"s": sp["SpeakerID"]}).mappings().all()

    return {
        "Speaker": dict(sp),
        "Event": {
            "EventID": sp["EventID"],
            "EventName": sp["EventName"],
            "EventStartDate": sp["EventStartDate"].isoformat() if sp["EventStartDate"] else None,
            "EventEndDate": sp["EventEndDate"].isoformat() if sp["EventEndDate"] else None,
            "EventLocationName": sp["EventLocationName"],
        },
        "Sessions": [
            {**dict(r), "SessionStart": r["SessionStart"].isoformat() if r["SessionStart"] else None}
            for r in sessions
        ],
    }
