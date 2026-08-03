"""
Fleece Show.

Modernized replacement for the classic ASP EventFleece.asp + FleeceHome.asp workflow.
Admins configure fleece-show fees, discount window, and registration window; attendees
submit one row per fleece (optionally tied to a source animal); organizers score and
award placements.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventFleeceConfig')
        CREATE TABLE OFNEventFleeceConfig (
            ConfigID                INT IDENTITY(1,1) PRIMARY KEY,
            EventID                 INT NOT NULL UNIQUE,
            Description             NVARCHAR(MAX),
            FeePerFleece            DECIMAL(10,2) DEFAULT 0,
            DiscountFeePerFleece    DECIMAL(10,2),
            DiscountStartDate       DATE,
            DiscountEndDate         DATE,
            RegistrationStartDate   DATE,
            RegistrationEndDate     DATE,
            MaxFleecesPerRegistrant INT,
            IsActive                BIT DEFAULT 1,
            CreatedDate             DATETIME DEFAULT GETDATE(),
            UpdatedDate             DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventFleeceEntries')
        CREATE TABLE OFNEventFleeceEntries (
            EntryID         INT IDENTITY(1,1) PRIMARY KEY,
            EventID         INT NOT NULL,
            PeopleID        INT,
            BusinessID      INT,
            FleeceName      NVARCHAR(200),
            Breed           NVARCHAR(100),
            Color           NVARCHAR(100),
            Micron          NVARCHAR(50),
            StapleLength    NVARCHAR(50),
            SourceAnimalID  INT,
            Description     NVARCHAR(MAX),
            EntryFee        DECIMAL(10,2) DEFAULT 0,
            PaidStatus      NVARCHAR(50) DEFAULT 'pending',
            Placement       NVARCHAR(50),
            Score           DECIMAL(10,2),
            JudgeNotes      NVARCHAR(MAX),
            CreatedDate     DATETIME DEFAULT GETDATE(),
            UpdatedDate     DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventFleeceDivisions')
        CREATE TABLE OFNEventFleeceDivisions (
            DivisionID    INT IDENTITY(1,1) PRIMARY KEY,
            EventID       INT NOT NULL,
            DivisionName  NVARCHAR(200) NOT NULL,
            BreedGroup    NVARCHAR(100),
            AgeGroup      NVARCHAR(100),
            Description   NVARCHAR(MAX),
            DisplayOrder  INT DEFAULT 0,
            IsActive      BIT DEFAULT 1,
            CreatedDate   DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sys.columns
                       WHERE object_id = OBJECT_ID('OFNEventFleeceEntries') AND name = 'DivisionID')
        ALTER TABLE OFNEventFleeceEntries ADD DivisionID INT NULL
    """))
    db.commit()


with SessionLocal() as _db:
    try:
        ensure_tables(_db)
    except Exception as e:
        print(f"Fleece table setup error: {e}")


def _current_fee(cfg: dict) -> float:
    """Return discount fee if today is within the discount window, else full fee."""
    full = float(cfg.get("FeePerFleece") or 0)
    disc = cfg.get("DiscountFeePerFleece")
    if disc is None:
        return full
    from datetime import date
    today = date.today()
    start = cfg.get("DiscountStartDate")
    end = cfg.get("DiscountEndDate")
    try:
        if start is not None:
            start_d = start if isinstance(start, date) else date.fromisoformat(str(start)[:10])
            if start_d > today:
                return full
        if end is not None:
            end_d = end if isinstance(end, date) else date.fromisoformat(str(end)[:10])
            if end_d < today:
                return full
    except Exception:
        return full
    return float(disc)


# ── Config ────────────────────────────────────────────────────────────────────
@router.get("/api/events/{event_id}/fleece/config")
def get_config(event_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT * FROM OFNEventFleeceConfig WHERE EventID = :eid
    """), {"eid": event_id}).fetchone()
    if not row:
        return {"EventID": event_id, "configured": False}
    d = dict(row._mapping)
    d["configured"] = True
    d["CurrentFee"] = _current_fee(d)
    return d


@router.put("/api/events/{event_id}/fleece/config")
def upsert_config(event_id: int, data: dict, db: Session = Depends(get_db)):
    existing = db.execute(
        text("SELECT ConfigID FROM OFNEventFleeceConfig WHERE EventID = :eid"),
        {"eid": event_id},
    ).fetchone()
    params = {
        "eid": event_id,
        "desc": data.get("Description") or None,
        "fee": data.get("FeePerFleece") or 0,
        "disc": data.get("DiscountFeePerFleece") or None,
        "discstart": data.get("DiscountStartDate") or None,
        "discend": data.get("DiscountEndDate") or None,
        "regstart": data.get("RegistrationStartDate") or None,
        "regend": data.get("RegistrationEndDate") or None,
        "maxper": data.get("MaxFleecesPerRegistrant") or None,
        "active": 1 if data.get("IsActive", True) else 0,
    }
    if existing:
        db.execute(text("""
            UPDATE OFNEventFleeceConfig SET
                Description             = :desc,
                FeePerFleece            = :fee,
                DiscountFeePerFleece    = :disc,
                DiscountStartDate       = :discstart,
                DiscountEndDate         = :discend,
                RegistrationStartDate   = :regstart,
                RegistrationEndDate     = :regend,
                MaxFleecesPerRegistrant = :maxper,
                IsActive                = :active,
                UpdatedDate             = GETDATE()
            WHERE EventID = :eid
        """), params)
    else:
        db.execute(text("""
            INSERT INTO OFNEventFleeceConfig
                (EventID, Description, FeePerFleece, DiscountFeePerFleece,
                 DiscountStartDate, DiscountEndDate, RegistrationStartDate,
                 RegistrationEndDate, MaxFleecesPerRegistrant, IsActive)
            VALUES (:eid, :desc, :fee, :disc, :discstart, :discend,
                    :regstart, :regend, :maxper, :active)
        """), params)
    db.commit()
    return {"ok": True}


# ── Divisions ─────────────────────────────────────────────────────────────────
@router.get("/api/events/{event_id}/fleece/divisions")
def list_divisions(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT DivisionID, EventID, DivisionName, BreedGroup, AgeGroup,
               Description, DisplayOrder, IsActive
        FROM OFNEventFleeceDivisions
        WHERE EventID = :eid AND IsActive = 1
        ORDER BY DisplayOrder, DivisionName
    """), {"eid": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/fleece/divisions")
def add_division(event_id: int, data: dict, db: Session = Depends(get_db)):
    if not data.get("DivisionName"):
        raise HTTPException(400, "DivisionName required")
    db.execute(text("""
        INSERT INTO OFNEventFleeceDivisions
            (EventID, DivisionName, BreedGroup, AgeGroup, Description, DisplayOrder, IsActive)
        VALUES (:eid, :name, :breed, :age, :desc, :ord, 1)
    """), {
        "eid": event_id,
        "name": data.get("DivisionName"),
        "breed": data.get("BreedGroup") or None,
        "age": data.get("AgeGroup") or None,
        "desc": data.get("Description") or None,
        "ord": data.get("DisplayOrder") or 0,
    })
    new_id = db.execute(text("SELECT SCOPE_IDENTITY() AS id")).fetchone()
    db.commit()
    return {"DivisionID": int(new_id.id)}


@router.put("/api/events/fleece/divisions/{division_id}")
def update_division(division_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventFleeceDivisions SET
            DivisionName = :name,
            BreedGroup   = :breed,
            AgeGroup     = :age,
            Description  = :desc,
            DisplayOrder = :ord
        WHERE DivisionID = :did
    """), {
        "did": division_id,
        "name": data.get("DivisionName"),
        "breed": data.get("BreedGroup") or None,
        "age": data.get("AgeGroup") or None,
        "desc": data.get("Description") or None,
        "ord": data.get("DisplayOrder") or 0,
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/fleece/divisions/{division_id}")
def delete_division(division_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE OFNEventFleeceDivisions SET IsActive = 0 WHERE DivisionID = :did"),
               {"did": division_id})
    db.commit()
    return {"ok": True}


_FLEECE_DIVISION_DEFAULTS = [
    ("Huacaya Juvenile",  "Huacaya",    "under 2 yr"),
    ("Huacaya Adult",     "Huacaya",    "2+ yr"),
    ("Suri Juvenile",     "Suri",       "under 2 yr"),
    ("Suri Adult",        "Suri",       "2+ yr"),
    ("Sheep - Fine Wool", "Sheep",      "any"),
    ("Sheep - Longwool",  "Sheep",      "any"),
    ("Cashmere / Goat",   "Goat",       "any"),
    ("Exotic / Novelty",  "Other",      "any"),
]


@router.post("/api/events/{event_id}/fleece/divisions/bulk-seed")
def bulk_seed_divisions(event_id: int, db: Session = Depends(get_db)):
    """Seed a standard fleece-show division set. Skips divisions that already exist."""
    existing = {
        r[0].strip().lower()
        for r in db.execute(
            text("SELECT DivisionName FROM OFNEventFleeceDivisions WHERE EventID = :eid AND IsActive = 1"),
            {"eid": event_id},
        ).fetchall()
    }
    added = 0
    for order, (name, breed, age) in enumerate(_FLEECE_DIVISION_DEFAULTS, start=1):
        if name.strip().lower() in existing:
            continue
        db.execute(text("""
            INSERT INTO OFNEventFleeceDivisions (EventID, DivisionName, BreedGroup, AgeGroup, DisplayOrder, IsActive)
            VALUES (:eid, :n, :b, :a, :o, 1)
        """), {"eid": event_id, "n": name, "b": breed, "a": age, "o": order})
        added += 1
    db.commit()
    return {"ok": True, "added": added, "skipped": len(_FLEECE_DIVISION_DEFAULTS) - added}


# ── Entries ───────────────────────────────────────────────────────────────────
@router.get("/api/events/{event_id}/fleece/entries")
def list_entries(event_id: int, people_id: int | None = None, db: Session = Depends(get_db)):
    if people_id is not None:
        rows = db.execute(text("""
            SELECT e.*, a.AnimalName, d.DivisionName
            FROM OFNEventFleeceEntries e
            LEFT JOIN Animals a ON e.SourceAnimalID = a.ID
            LEFT JOIN OFNEventFleeceDivisions d ON e.DivisionID = d.DivisionID
            WHERE e.EventID = :eid AND e.PeopleID = :pid
            ORDER BY e.EntryID DESC
        """), {"eid": event_id, "pid": people_id}).fetchall()
    else:
        rows = db.execute(text("""
            SELECT e.*, a.AnimalName, d.DivisionName,
                   p.PeopleFirstName, p.PeopleLastName, p.Peopleemail,
                   b.BusinessName
            FROM OFNEventFleeceEntries e
            LEFT JOIN Animals a ON e.SourceAnimalID = a.ID
            LEFT JOIN OFNEventFleeceDivisions d ON e.DivisionID = d.DivisionID
            LEFT JOIN People p ON e.PeopleID = p.PeopleID
            LEFT JOIN Business b ON e.BusinessID = b.BusinessID
            WHERE e.EventID = :eid
            ORDER BY e.EntryID
        """), {"eid": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/fleece/entries")
def add_entry(event_id: int, data: dict, db: Session = Depends(get_db)):
    cfg_row = db.execute(
        text("SELECT * FROM OFNEventFleeceConfig WHERE EventID = :eid AND IsActive = 1"),
        {"eid": event_id},
    ).fetchone()
    if not cfg_row:
        raise HTTPException(400, "Fleece show not configured for this event")
    cfg = dict(cfg_row._mapping)

    from datetime import date
    today = date.today()
    if cfg.get("RegistrationStartDate"):
        start = cfg["RegistrationStartDate"]
        start_d = start if isinstance(start, date) else date.fromisoformat(str(start)[:10])
        if start_d > today:
            raise HTTPException(400, f"Registration has not yet opened (opens {start_d})")
    if cfg.get("RegistrationEndDate"):
        end = cfg["RegistrationEndDate"]
        end_d = end if isinstance(end, date) else date.fromisoformat(str(end)[:10])
        if end_d < today:
            raise HTTPException(400, "Registration is closed")

    pid = data.get("PeopleID")
    if pid and cfg.get("MaxFleecesPerRegistrant"):
        n = db.execute(
            text("SELECT COUNT(1) AS c FROM OFNEventFleeceEntries WHERE EventID = :eid AND PeopleID = :pid"),
            {"eid": event_id, "pid": pid},
        ).fetchone()
        if n.c >= cfg["MaxFleecesPerRegistrant"]:
            raise HTTPException(400, f"Maximum {cfg['MaxFleecesPerRegistrant']} fleeces per registrant reached")

    fee = _current_fee(cfg)
    db.execute(text("""
        INSERT INTO OFNEventFleeceEntries
            (EventID, PeopleID, BusinessID, FleeceName, Breed, Color, Micron,
             StapleLength, SourceAnimalID, DivisionID, Description, EntryFee, PaidStatus)
        VALUES (:eid, :pid, :bid, :name, :breed, :color, :micron,
                :staple, :anim, :div, :desc, :fee, 'pending')
    """), {
        "eid": event_id,
        "pid": pid or None,
        "bid": data.get("BusinessID") or None,
        "name": data.get("FleeceName") or None,
        "breed": data.get("Breed") or None,
        "color": data.get("Color") or None,
        "micron": data.get("Micron") or None,
        "staple": data.get("StapleLength") or None,
        "anim": data.get("SourceAnimalID") or None,
        "div": data.get("DivisionID") or None,
        "desc": data.get("Description") or None,
        "fee": fee,
    })
    new_id = db.execute(text("SELECT SCOPE_IDENTITY() AS id")).fetchone()
    db.commit()
    return {"EntryID": int(new_id.id), "EntryFee": fee}


@router.put("/api/events/fleece/entries/{entry_id}")
def update_entry(entry_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventFleeceEntries SET
            FleeceName      = :name,
            Breed           = :breed,
            Color           = :color,
            Micron          = :micron,
            StapleLength    = :staple,
            SourceAnimalID  = :anim,
            DivisionID      = :div,
            Description     = :desc,
            UpdatedDate     = GETDATE()
        WHERE EntryID = :xid
    """), {
        "xid": entry_id,
        "name": data.get("FleeceName") or None,
        "breed": data.get("Breed") or None,
        "color": data.get("Color") or None,
        "micron": data.get("Micron") or None,
        "staple": data.get("StapleLength") or None,
        "anim": data.get("SourceAnimalID") or None,
        "div": data.get("DivisionID") or None,
        "desc": data.get("Description") or None,
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/fleece/entries/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventFleeceEntries WHERE EntryID = :xid"),
               {"xid": entry_id})
    db.commit()
    return {"ok": True}


# ── Organizer judging ────────────────────────────────────────────────────────
@router.put("/api/events/fleece/entries/{entry_id}/judge")
def judge_entry(entry_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventFleeceEntries SET
            Placement   = :place,
            Score       = :score,
            JudgeNotes  = :notes,
            UpdatedDate = GETDATE()
        WHERE EntryID = :xid
    """), {
        "xid": entry_id,
        "place": data.get("Placement") or None,
        "score": data.get("Score"),
        "notes": data.get("JudgeNotes") or None,
    })
    db.commit()
    return {"ok": True}


@router.put("/api/events/fleece/entries/{entry_id}/paid")
def mark_paid(entry_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventFleeceEntries SET
            PaidStatus  = :status,
            UpdatedDate = GETDATE()
        WHERE EntryID = :xid
    """), {"xid": entry_id, "status": data.get("PaidStatus", "paid")})
    db.commit()
    return {"ok": True}
