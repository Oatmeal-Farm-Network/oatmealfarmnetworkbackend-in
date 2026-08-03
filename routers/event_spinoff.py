"""
Spin-Off competition.

Modernized replacement for the classic ASP EventSpin-off.asp + SpinOffHome.asp workflow.
Admins configure the Spin-Off's fees, discount window, and registration window; attendees
submit one row per spun entry (optionally tied to a source animal / fiber origin);
organizers score and award placements.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventSpinOffConfig')
        CREATE TABLE OFNEventSpinOffConfig (
            ConfigID                INT IDENTITY(1,1) PRIMARY KEY,
            EventID                 INT NOT NULL UNIQUE,
            Description             NVARCHAR(MAX),
            FeePerEntry             DECIMAL(10,2) DEFAULT 0,
            DiscountFeePerEntry     DECIMAL(10,2),
            DiscountStartDate       DATE,
            DiscountEndDate         DATE,
            RegistrationStartDate   DATE,
            RegistrationEndDate     DATE,
            MaxEntriesPerRegistrant INT,
            IsActive                BIT DEFAULT 1,
            CreatedDate             DATETIME DEFAULT GETDATE(),
            UpdatedDate             DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventSpinOffEntries')
        CREATE TABLE OFNEventSpinOffEntries (
            EntryID         INT IDENTITY(1,1) PRIMARY KEY,
            EventID         INT NOT NULL,
            PeopleID        INT,
            BusinessID      INT,
            EntryTitle      NVARCHAR(200) NOT NULL,
            SpinnerName     NVARCHAR(200),
            FiberType       NVARCHAR(100),
            FiberSource     NVARCHAR(200),
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
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventSpinOffCategories')
        CREATE TABLE OFNEventSpinOffCategories (
            CategoryID    INT IDENTITY(1,1) PRIMARY KEY,
            EventID       INT NOT NULL,
            CategoryName  NVARCHAR(200) NOT NULL,
            SkillLevel    NVARCHAR(50),
            Description   NVARCHAR(MAX),
            DisplayOrder  INT DEFAULT 0,
            IsActive      BIT DEFAULT 1,
            CreatedDate   DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sys.columns
                       WHERE object_id = OBJECT_ID('OFNEventSpinOffEntries') AND name = 'CategoryID')
        ALTER TABLE OFNEventSpinOffEntries ADD CategoryID INT NULL
    """))
    db.commit()


with SessionLocal() as _db:
    try:
        ensure_tables(_db)
    except Exception as e:
        print(f"Spin-Off table setup error: {e}")


def _current_fee(cfg: dict) -> float:
    full = float(cfg.get("FeePerEntry") or 0)
    disc = cfg.get("DiscountFeePerEntry")
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
@router.get("/api/events/{event_id}/spinoff/config")
def get_config(event_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT * FROM OFNEventSpinOffConfig WHERE EventID = :eid
    """), {"eid": event_id}).fetchone()
    if not row:
        return {"EventID": event_id, "configured": False}
    d = dict(row._mapping)
    d["configured"] = True
    d["CurrentFee"] = _current_fee(d)
    return d


@router.put("/api/events/{event_id}/spinoff/config")
def upsert_config(event_id: int, data: dict, db: Session = Depends(get_db)):
    existing = db.execute(
        text("SELECT ConfigID FROM OFNEventSpinOffConfig WHERE EventID = :eid"),
        {"eid": event_id},
    ).fetchone()
    params = {
        "eid": event_id,
        "desc": data.get("Description") or None,
        "fee": data.get("FeePerEntry") or 0,
        "disc": data.get("DiscountFeePerEntry") or None,
        "discstart": data.get("DiscountStartDate") or None,
        "discend": data.get("DiscountEndDate") or None,
        "regstart": data.get("RegistrationStartDate") or None,
        "regend": data.get("RegistrationEndDate") or None,
        "maxper": data.get("MaxEntriesPerRegistrant") or None,
        "active": 1 if data.get("IsActive", True) else 0,
    }
    if existing:
        db.execute(text("""
            UPDATE OFNEventSpinOffConfig SET
                Description             = :desc,
                FeePerEntry             = :fee,
                DiscountFeePerEntry     = :disc,
                DiscountStartDate       = :discstart,
                DiscountEndDate         = :discend,
                RegistrationStartDate   = :regstart,
                RegistrationEndDate     = :regend,
                MaxEntriesPerRegistrant = :maxper,
                IsActive                = :active,
                UpdatedDate             = GETDATE()
            WHERE EventID = :eid
        """), params)
    else:
        db.execute(text("""
            INSERT INTO OFNEventSpinOffConfig
                (EventID, Description, FeePerEntry, DiscountFeePerEntry,
                 DiscountStartDate, DiscountEndDate, RegistrationStartDate,
                 RegistrationEndDate, MaxEntriesPerRegistrant, IsActive)
            VALUES (:eid, :desc, :fee, :disc, :discstart, :discend,
                    :regstart, :regend, :maxper, :active)
        """), params)
    db.commit()
    return {"ok": True}


# ── Categories ────────────────────────────────────────────────────────────────
@router.get("/api/events/{event_id}/spinoff/categories")
def list_categories(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT CategoryID, EventID, CategoryName, SkillLevel, Description, DisplayOrder, IsActive
        FROM OFNEventSpinOffCategories
        WHERE EventID = :eid AND IsActive = 1
        ORDER BY DisplayOrder, CategoryName
    """), {"eid": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/spinoff/categories")
def add_category(event_id: int, data: dict, db: Session = Depends(get_db)):
    if not data.get("CategoryName"):
        raise HTTPException(400, "CategoryName required")
    db.execute(text("""
        INSERT INTO OFNEventSpinOffCategories
            (EventID, CategoryName, SkillLevel, Description, DisplayOrder, IsActive)
        VALUES (:eid, :name, :skill, :desc, :ord, 1)
    """), {
        "eid": event_id,
        "name": data.get("CategoryName"),
        "skill": data.get("SkillLevel") or None,
        "desc": data.get("Description") or None,
        "ord": data.get("DisplayOrder") or 0,
    })
    new_id = db.execute(text("SELECT SCOPE_IDENTITY() AS id")).fetchone()
    db.commit()
    return {"CategoryID": int(new_id.id)}


@router.put("/api/events/spinoff/categories/{cat_id}")
def update_category(cat_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventSpinOffCategories SET
            CategoryName = :name,
            SkillLevel   = :skill,
            Description  = :desc,
            DisplayOrder = :ord
        WHERE CategoryID = :cid
    """), {
        "cid": cat_id,
        "name": data.get("CategoryName"),
        "skill": data.get("SkillLevel") or None,
        "desc": data.get("Description") or None,
        "ord": data.get("DisplayOrder") or 0,
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/spinoff/categories/{cat_id}")
def delete_category(cat_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE OFNEventSpinOffCategories SET IsActive = 0 WHERE CategoryID = :cid"),
               {"cid": cat_id})
    db.commit()
    return {"ok": True}


_SPINOFF_CATEGORY_DEFAULTS = [
    ("Novice Spinner",   "Novice",       "Less than 1 year of spinning experience."),
    ("Intermediate",     "Intermediate", "1-5 years of spinning experience."),
    ("Advanced",         "Advanced",     "5+ years of experience or professional spinners."),
    ("Youth (under 18)", "Youth",        "Entrants under 18 years of age."),
    ("Camelid Fiber",    "Open",         "Alpaca, llama, or other camelid fiber."),
    ("Sheep / Wool",     "Open",         "Wool from any sheep breed."),
    ("Luxury / Exotic",  "Open",         "Cashmere, mohair, angora, silk blends, etc."),
    ("Art Yarn",         "Open",         "Creative, novelty, or highly textured yarns."),
]


@router.post("/api/events/{event_id}/spinoff/categories/bulk-seed")
def bulk_seed_categories(event_id: int, db: Session = Depends(get_db)):
    """Seed a standard spin-off category set (skill levels + fiber types)."""
    existing = {
        r[0].strip().lower()
        for r in db.execute(
            text("SELECT CategoryName FROM OFNEventSpinOffCategories WHERE EventID = :eid AND IsActive = 1"),
            {"eid": event_id},
        ).fetchall()
    }
    added = 0
    for order, (name, skill, desc) in enumerate(_SPINOFF_CATEGORY_DEFAULTS, start=1):
        if name.strip().lower() in existing:
            continue
        db.execute(text("""
            INSERT INTO OFNEventSpinOffCategories
                (EventID, CategoryName, SkillLevel, Description, DisplayOrder, IsActive)
            VALUES (:eid, :n, :s, :d, :o, 1)
        """), {"eid": event_id, "n": name, "s": skill, "d": desc, "o": order})
        added += 1
    db.commit()
    return {"ok": True, "added": added, "skipped": len(_SPINOFF_CATEGORY_DEFAULTS) - added}


# ── Entries ───────────────────────────────────────────────────────────────────
@router.get("/api/events/{event_id}/spinoff/entries")
def list_entries(event_id: int, people_id: int | None = None, db: Session = Depends(get_db)):
    if people_id is not None:
        rows = db.execute(text("""
            SELECT e.*, a.AnimalName, c.CategoryName
            FROM OFNEventSpinOffEntries e
            LEFT JOIN Animals a ON e.SourceAnimalID = a.ID
            LEFT JOIN OFNEventSpinOffCategories c ON e.CategoryID = c.CategoryID
            WHERE e.EventID = :eid AND e.PeopleID = :pid
            ORDER BY e.EntryID DESC
        """), {"eid": event_id, "pid": people_id}).fetchall()
    else:
        rows = db.execute(text("""
            SELECT e.*, a.AnimalName, c.CategoryName,
                   p.PeopleFirstName, p.PeopleLastName, p.Peopleemail,
                   b.BusinessName
            FROM OFNEventSpinOffEntries e
            LEFT JOIN Animals a ON e.SourceAnimalID = a.ID
            LEFT JOIN OFNEventSpinOffCategories c ON e.CategoryID = c.CategoryID
            LEFT JOIN People p ON e.PeopleID = p.PeopleID
            LEFT JOIN Business b ON e.BusinessID = b.BusinessID
            WHERE e.EventID = :eid
            ORDER BY e.EntryID
        """), {"eid": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/spinoff/entries")
def add_entry(event_id: int, data: dict, db: Session = Depends(get_db)):
    if not data.get("EntryTitle"):
        raise HTTPException(400, "EntryTitle required")

    cfg_row = db.execute(
        text("SELECT * FROM OFNEventSpinOffConfig WHERE EventID = :eid AND IsActive = 1"),
        {"eid": event_id},
    ).fetchone()
    if not cfg_row:
        raise HTTPException(400, "Spin-Off not configured for this event")
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
    if pid and cfg.get("MaxEntriesPerRegistrant"):
        n = db.execute(
            text("SELECT COUNT(1) AS c FROM OFNEventSpinOffEntries WHERE EventID = :eid AND PeopleID = :pid"),
            {"eid": event_id, "pid": pid},
        ).fetchone()
        if n.c >= cfg["MaxEntriesPerRegistrant"]:
            raise HTTPException(400, f"Maximum {cfg['MaxEntriesPerRegistrant']} entries per registrant reached")

    fee = _current_fee(cfg)
    db.execute(text("""
        INSERT INTO OFNEventSpinOffEntries
            (EventID, PeopleID, BusinessID, EntryTitle, SpinnerName, FiberType,
             FiberSource, SourceAnimalID, CategoryID, Description, EntryFee, PaidStatus)
        VALUES (:eid, :pid, :bid, :title, :spinner, :fiber, :source,
                :anim, :cat, :desc, :fee, 'pending')
    """), {
        "eid": event_id,
        "pid": pid or None,
        "bid": data.get("BusinessID") or None,
        "title": data.get("EntryTitle"),
        "spinner": data.get("SpinnerName") or None,
        "fiber": data.get("FiberType") or None,
        "source": data.get("FiberSource") or None,
        "anim": data.get("SourceAnimalID") or None,
        "cat": data.get("CategoryID") or None,
        "desc": data.get("Description") or None,
        "fee": fee,
    })
    new_id = db.execute(text("SELECT SCOPE_IDENTITY() AS id")).fetchone()
    db.commit()
    return {"EntryID": int(new_id.id), "EntryFee": fee}


@router.put("/api/events/spinoff/entries/{entry_id}")
def update_entry(entry_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventSpinOffEntries SET
            EntryTitle      = :title,
            SpinnerName     = :spinner,
            FiberType       = :fiber,
            FiberSource     = :source,
            SourceAnimalID  = :anim,
            CategoryID      = :cat,
            Description     = :desc,
            UpdatedDate     = GETDATE()
        WHERE EntryID = :xid
    """), {
        "xid": entry_id,
        "title": data.get("EntryTitle"),
        "spinner": data.get("SpinnerName") or None,
        "fiber": data.get("FiberType") or None,
        "source": data.get("FiberSource") or None,
        "anim": data.get("SourceAnimalID") or None,
        "cat": data.get("CategoryID") or None,
        "desc": data.get("Description") or None,
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/spinoff/entries/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventSpinOffEntries WHERE EntryID = :xid"),
               {"xid": entry_id})
    db.commit()
    return {"ok": True}


# ── Organizer judging ────────────────────────────────────────────────────────
@router.put("/api/events/spinoff/entries/{entry_id}/judge")
def judge_entry(entry_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventSpinOffEntries SET
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


@router.put("/api/events/spinoff/entries/{entry_id}/paid")
def mark_paid(entry_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventSpinOffEntries SET
            PaidStatus  = :status,
            UpdatedDate = GETDATE()
        WHERE EntryID = :xid
    """), {"xid": entry_id, "status": data.get("PaidStatus", "paid")})
    db.commit()
    return {"ok": True}
