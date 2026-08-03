"""
Cottage Industry / Fiber Arts Show.

Modernized replacement for the classic ASP FiberArtsHome.asp + FiberManiaRegistration.asp
fiber-entry section. Admin configures the show (description, fees, deadlines, categories);
attendees submit fiber entries (yarn, skeins, finished goods) tied to optional source
animals; organizers judge and award placements.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventFiberArtsConfig')
        CREATE TABLE OFNEventFiberArtsConfig (
            ConfigID                INT IDENTITY(1,1) PRIMARY KEY,
            EventID                 INT NOT NULL UNIQUE,
            Description             NVARCHAR(MAX),
            FeePerEntry             DECIMAL(10,2) DEFAULT 0,
            DiscountFeePerEntry     DECIMAL(10,2),
            DiscountEndDate         DATE,
            MaxEntriesPerRegistrant INT,
            MaxEntriesTotal         INT,
            RegistrationEndDate     DATE,
            IsActive                BIT DEFAULT 1,
            CreatedDate             DATETIME DEFAULT GETDATE(),
            UpdatedDate             DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventFiberArtsCategories')
        CREATE TABLE OFNEventFiberArtsCategories (
            CategoryID           INT IDENTITY(1,1) PRIMARY KEY,
            EventID              INT NOT NULL,
            CategoryName         NVARCHAR(200) NOT NULL,
            CategoryDescription  NVARCHAR(MAX),
            DisplayOrder         INT DEFAULT 0,
            IsActive             BIT DEFAULT 1
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventFiberArtsEntries')
        CREATE TABLE OFNEventFiberArtsEntries (
            EntryID         INT IDENTITY(1,1) PRIMARY KEY,
            EventID         INT NOT NULL,
            PeopleID        INT,
            BusinessID      INT,
            CategoryID      INT,
            EntryTitle      NVARCHAR(200) NOT NULL,
            Description     NVARCHAR(MAX),
            FiberType       NVARCHAR(100),
            SourceAnimalID  INT,
            EntryFee        DECIMAL(10,2) DEFAULT 0,
            PaidStatus      NVARCHAR(50) DEFAULT 'pending',
            Placement       NVARCHAR(50),
            JudgeNotes      NVARCHAR(MAX),
            ScoresheetJSON  NVARCHAR(MAX),
            CreatedDate     DATETIME DEFAULT GETDATE(),
            UpdatedDate     DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


with SessionLocal() as _db:
    try:
        ensure_tables(_db)
    except Exception as e:
        print(f"Fiber arts table setup error: {e}")


def _current_fee(cfg: dict) -> float:
    """Return discount fee if discount window is active, otherwise full fee."""
    full = float(cfg.get("FeePerEntry") or 0)
    disc = cfg.get("DiscountFeePerEntry")
    end = cfg.get("DiscountEndDate")
    if disc is not None and end is not None:
        from datetime import date
        try:
            end_d = end if isinstance(end, date) else date.fromisoformat(str(end)[:10])
            if end_d >= date.today():
                return float(disc)
        except Exception:
            pass
    return full


# ── Config ────────────────────────────────────────────────────────────────────
@router.get("/api/events/{event_id}/fiber-arts/config")
def get_config(event_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT * FROM OFNEventFiberArtsConfig WHERE EventID = :eid
    """), {"eid": event_id}).fetchone()
    if not row:
        return {"EventID": event_id, "configured": False}
    d = dict(row._mapping)
    d["configured"] = True
    d["CurrentFee"] = _current_fee(d)
    return d


@router.put("/api/events/{event_id}/fiber-arts/config")
def upsert_config(event_id: int, data: dict, db: Session = Depends(get_db)):
    existing = db.execute(
        text("SELECT ConfigID FROM OFNEventFiberArtsConfig WHERE EventID = :eid"),
        {"eid": event_id},
    ).fetchone()
    params = {
        "eid": event_id,
        "desc": data.get("Description") or None,
        "fee": data.get("FeePerEntry") or 0,
        "disc": data.get("DiscountFeePerEntry") or None,
        "discend": data.get("DiscountEndDate") or None,
        "maxper": data.get("MaxEntriesPerRegistrant") or None,
        "maxtot": data.get("MaxEntriesTotal") or None,
        "regend": data.get("RegistrationEndDate") or None,
        "active": 1 if data.get("IsActive", True) else 0,
    }
    if existing:
        db.execute(text("""
            UPDATE OFNEventFiberArtsConfig SET
                Description             = :desc,
                FeePerEntry             = :fee,
                DiscountFeePerEntry     = :disc,
                DiscountEndDate         = :discend,
                MaxEntriesPerRegistrant = :maxper,
                MaxEntriesTotal         = :maxtot,
                RegistrationEndDate     = :regend,
                IsActive                = :active,
                UpdatedDate             = GETDATE()
            WHERE EventID = :eid
        """), params)
    else:
        db.execute(text("""
            INSERT INTO OFNEventFiberArtsConfig
                (EventID, Description, FeePerEntry, DiscountFeePerEntry, DiscountEndDate,
                 MaxEntriesPerRegistrant, MaxEntriesTotal, RegistrationEndDate, IsActive)
            VALUES (:eid, :desc, :fee, :disc, :discend, :maxper, :maxtot, :regend, :active)
        """), params)
    db.commit()
    return {"ok": True}


# ── Categories ────────────────────────────────────────────────────────────────
@router.get("/api/events/{event_id}/fiber-arts/categories")
def list_categories(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT CategoryID, EventID, CategoryName, CategoryDescription, DisplayOrder, IsActive
        FROM OFNEventFiberArtsCategories
        WHERE EventID = :eid AND IsActive = 1
        ORDER BY DisplayOrder, CategoryName
    """), {"eid": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/fiber-arts/categories")
def add_category(event_id: int, data: dict, db: Session = Depends(get_db)):
    if not data.get("CategoryName"):
        raise HTTPException(400, "CategoryName required")
    db.execute(text("""
        INSERT INTO OFNEventFiberArtsCategories
            (EventID, CategoryName, CategoryDescription, DisplayOrder, IsActive)
        VALUES (:eid, :name, :desc, :ord, 1)
    """), {
        "eid": event_id,
        "name": data.get("CategoryName"),
        "desc": data.get("CategoryDescription") or None,
        "ord": data.get("DisplayOrder") or 0,
    })
    new_id = db.execute(text("SELECT SCOPE_IDENTITY() AS id")).fetchone()
    db.commit()
    return {"CategoryID": int(new_id.id)}


@router.put("/api/events/fiber-arts/categories/{cat_id}")
def update_category(cat_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventFiberArtsCategories SET
            CategoryName = :name,
            CategoryDescription = :desc,
            DisplayOrder = :ord
        WHERE CategoryID = :cid
    """), {
        "cid": cat_id,
        "name": data.get("CategoryName"),
        "desc": data.get("CategoryDescription") or None,
        "ord": data.get("DisplayOrder") or 0,
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/fiber-arts/categories/{cat_id}")
def delete_category(cat_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE OFNEventFiberArtsCategories SET IsActive = 0 WHERE CategoryID = :cid"),
               {"cid": cat_id})
    db.commit()
    return {"ok": True}


_FIBER_ARTS_DEFAULTS = [
    ("Handspun Yarn",       "Skeins of hand-spun yarn, any fiber."),
    ("Knitted Garment",     "Hand-knit sweaters, shawls, vests, and other wearables."),
    ("Knitted Accessory",   "Hats, scarves, mittens, socks, and other small knits."),
    ("Woven Item",          "Hand-woven scarves, rugs, table runners, fabric."),
    ("Crocheted Item",      "Hand-crocheted garments, accessories, or household items."),
    ("Felted Item",         "Wet-felted or needle-felted pieces, including 3D sculpture."),
    ("Natural-Dyed Fiber",  "Naturally dyed fiber, roving, or finished goods."),
    ("Raw Fiber / Roving",  "Processed or unprocessed fleece, roving, top, or batts."),
    ("Mixed Media / Other", "Combined-technique or novelty entries."),
]


@router.post("/api/events/{event_id}/fiber-arts/categories/bulk-seed")
def bulk_seed_categories(event_id: int, db: Session = Depends(get_db)):
    """Seed a standard cottage-industry category set. Skips categories that already exist."""
    existing = {
        r[0].strip().lower()
        for r in db.execute(
            text("SELECT CategoryName FROM OFNEventFiberArtsCategories WHERE EventID = :eid AND IsActive = 1"),
            {"eid": event_id},
        ).fetchall()
    }
    added = 0
    for order, (name, desc) in enumerate(_FIBER_ARTS_DEFAULTS, start=1):
        if name.strip().lower() in existing:
            continue
        db.execute(text("""
            INSERT INTO OFNEventFiberArtsCategories (EventID, CategoryName, CategoryDescription, DisplayOrder, IsActive)
            VALUES (:eid, :n, :d, :o, 1)
        """), {"eid": event_id, "n": name, "d": desc, "o": order})
        added += 1
    db.commit()
    return {"ok": True, "added": added, "skipped": len(_FIBER_ARTS_DEFAULTS) - added}


# ── Entries ───────────────────────────────────────────────────────────────────
@router.get("/api/events/{event_id}/fiber-arts/entries")
def list_entries(event_id: int, people_id: int | None = None, db: Session = Depends(get_db)):
    """If people_id is supplied, return just that person's entries (attendee view);
    otherwise return all entries for the event (admin view) joined with category + attendee."""
    if people_id is not None:
        rows = db.execute(text("""
            SELECT e.*, c.CategoryName
            FROM OFNEventFiberArtsEntries e
            LEFT JOIN OFNEventFiberArtsCategories c ON e.CategoryID = c.CategoryID
            WHERE e.EventID = :eid AND e.PeopleID = :pid
            ORDER BY e.EntryID DESC
        """), {"eid": event_id, "pid": people_id}).fetchall()
    else:
        rows = db.execute(text("""
            SELECT e.*, c.CategoryName,
                   p.PeopleFirstName, p.PeopleLastName, p.Peopleemail,
                   b.BusinessName
            FROM OFNEventFiberArtsEntries e
            LEFT JOIN OFNEventFiberArtsCategories c ON e.CategoryID = c.CategoryID
            LEFT JOIN People p ON e.PeopleID = p.PeopleID
            LEFT JOIN Business b ON e.BusinessID = b.BusinessID
            WHERE e.EventID = :eid
            ORDER BY c.DisplayOrder, c.CategoryName, e.EntryID
        """), {"eid": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/fiber-arts/entries")
def add_entry(event_id: int, data: dict, db: Session = Depends(get_db)):
    if not data.get("EntryTitle"):
        raise HTTPException(400, "EntryTitle required")

    # Enforce config: registration window, per-registrant cap, total cap.
    cfg_row = db.execute(
        text("SELECT * FROM OFNEventFiberArtsConfig WHERE EventID = :eid AND IsActive = 1"),
        {"eid": event_id},
    ).fetchone()
    if not cfg_row:
        raise HTTPException(400, "Fiber arts show not configured for this event")
    cfg = dict(cfg_row._mapping)

    from datetime import date
    if cfg.get("RegistrationEndDate"):
        end = cfg["RegistrationEndDate"]
        end_d = end if isinstance(end, date) else date.fromisoformat(str(end)[:10])
        if end_d < date.today():
            raise HTTPException(400, "Registration is closed")

    pid = data.get("PeopleID")
    if pid and cfg.get("MaxEntriesPerRegistrant"):
        n = db.execute(
            text("SELECT COUNT(1) AS c FROM OFNEventFiberArtsEntries WHERE EventID = :eid AND PeopleID = :pid"),
            {"eid": event_id, "pid": pid},
        ).fetchone()
        if n.c >= cfg["MaxEntriesPerRegistrant"]:
            raise HTTPException(400, f"Maximum {cfg['MaxEntriesPerRegistrant']} entries per registrant reached")

    if cfg.get("MaxEntriesTotal"):
        n = db.execute(
            text("SELECT COUNT(1) AS c FROM OFNEventFiberArtsEntries WHERE EventID = :eid"),
            {"eid": event_id},
        ).fetchone()
        if n.c >= cfg["MaxEntriesTotal"]:
            raise HTTPException(400, "The show has reached its entry limit")

    fee = _current_fee(cfg)
    db.execute(text("""
        INSERT INTO OFNEventFiberArtsEntries
            (EventID, PeopleID, BusinessID, CategoryID, EntryTitle, Description,
             FiberType, SourceAnimalID, EntryFee, PaidStatus)
        VALUES (:eid, :pid, :bid, :cid, :title, :desc, :fiber, :anim, :fee, 'pending')
    """), {
        "eid": event_id,
        "pid": pid or None,
        "bid": data.get("BusinessID") or None,
        "cid": data.get("CategoryID") or None,
        "title": data.get("EntryTitle"),
        "desc": data.get("Description") or None,
        "fiber": data.get("FiberType") or None,
        "anim": data.get("SourceAnimalID") or None,
        "fee": fee,
    })
    new_id = db.execute(text("SELECT SCOPE_IDENTITY() AS id")).fetchone()
    db.commit()
    return {"EntryID": int(new_id.id), "EntryFee": fee}


@router.put("/api/events/fiber-arts/entries/{entry_id}")
def update_entry(entry_id: int, data: dict, db: Session = Depends(get_db)):
    """Attendee-editable fields only (title, description, category, fiber type, source animal)."""
    db.execute(text("""
        UPDATE OFNEventFiberArtsEntries SET
            CategoryID      = :cid,
            EntryTitle      = :title,
            Description     = :desc,
            FiberType       = :fiber,
            SourceAnimalID  = :anim,
            UpdatedDate     = GETDATE()
        WHERE EntryID = :xid
    """), {
        "xid": entry_id,
        "cid": data.get("CategoryID") or None,
        "title": data.get("EntryTitle"),
        "desc": data.get("Description") or None,
        "fiber": data.get("FiberType") or None,
        "anim": data.get("SourceAnimalID") or None,
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/fiber-arts/entries/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventFiberArtsEntries WHERE EntryID = :xid"),
               {"xid": entry_id})
    db.commit()
    return {"ok": True}


# ── Organizer judging ────────────────────────────────────────────────────────
@router.put("/api/events/fiber-arts/entries/{entry_id}/judge")
def judge_entry(entry_id: int, data: dict, db: Session = Depends(get_db)):
    """Admin endpoint: assign placement, judge notes, scoresheet JSON."""
    db.execute(text("""
        UPDATE OFNEventFiberArtsEntries SET
            Placement       = :place,
            JudgeNotes      = :notes,
            ScoresheetJSON  = :score,
            UpdatedDate     = GETDATE()
        WHERE EntryID = :xid
    """), {
        "xid": entry_id,
        "place": data.get("Placement") or None,
        "notes": data.get("JudgeNotes") or None,
        "score": data.get("ScoresheetJSON") or None,
    })
    db.commit()
    return {"ok": True}


@router.put("/api/events/fiber-arts/entries/{entry_id}/paid")
def mark_paid(entry_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventFiberArtsEntries SET
            PaidStatus  = :status,
            UpdatedDate = GETDATE()
        WHERE EntryID = :xid
    """), {"xid": entry_id, "status": data.get("PaidStatus", "paid")})
    db.commit()
    return {"ok": True}
