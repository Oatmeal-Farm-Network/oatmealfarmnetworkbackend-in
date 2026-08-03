"""
Halter Show (full livestock show).

Modernized replacement for the classic ASP EventHalter.asp, HalterClassList.asp,
EventAddAnimal.asp, and judging pages. Admin configures the show, defines classes
(per breed/gender/age), accepts animal registrations, assigns pens, and awards
placements. Attendees register their animals from the Animals table, pick classes,
reserve pens, and add extras (vet check, electricity, stall mats).
"""
from fastapi import APIRouter, Depends, HTTPException
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal
from datetime import date

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventHalterConfig')
        CREATE TABLE OFNEventHalterConfig (
            ConfigID                INT IDENTITY(1,1) PRIMARY KEY,
            EventID                 INT NOT NULL UNIQUE,
            Description             NVARCHAR(MAX),
            FeePerAnimal            DECIMAL(10,2) DEFAULT 0,
            DiscountFeePerAnimal    DECIMAL(10,2),
            DiscountEndDate         DATE,
            FeePerPen               DECIMAL(10,2) DEFAULT 0,
            FeePerProductionAnimal  DECIMAL(10,2) DEFAULT 0,
            VetCheckFee             DECIMAL(10,2) DEFAULT 0,
            ElectricityFee          DECIMAL(10,2) DEFAULT 0,
            StallMatFee             DECIMAL(10,2) DEFAULT 0,
            MaxPensPerFarm          INT,
            MaxJuvenilesPerPen      INT,
            MaxAdultsPerPen         INT,
            RegistrationEndDate     DATE,
            IsActive                BIT DEFAULT 1,
            CreatedDate             DATETIME DEFAULT GETDATE(),
            UpdatedDate             DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventHalterClasses')
        CREATE TABLE OFNEventHalterClasses (
            ClassID        INT IDENTITY(1,1) PRIMARY KEY,
            EventID        INT NOT NULL,
            ClassName      NVARCHAR(200) NOT NULL,
            ClassCode      NVARCHAR(50),
            ShornCode      NVARCHAR(50),
            Breed          NVARCHAR(100),
            Gender         NVARCHAR(50),
            AgeGroup       NVARCHAR(100),
            ClassType      NVARCHAR(50) DEFAULT 'Halter',
            DisplayOrder   INT DEFAULT 0,
            IsActive       BIT DEFAULT 1
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventHalterRegistrations')
        CREATE TABLE OFNEventHalterRegistrations (
            RegID              INT IDENTITY(1,1) PRIMARY KEY,
            EventID            INT NOT NULL,
            PeopleID           INT NOT NULL,
            BusinessID         INT,
            AnimalID           INT NOT NULL,
            RegistrationType   NVARCHAR(50) DEFAULT 'Halter',
            IsShorn            BIT DEFAULT 0,
            IsCheckedIn        BIT DEFAULT 0,
            CheckInNotes       NVARCHAR(MAX),
            PaidStatus         NVARCHAR(20) DEFAULT 'pending',
            Fee                DECIMAL(10,2) DEFAULT 0,
            CreatedDate        DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventHalterClassEntries')
        CREATE TABLE OFNEventHalterClassEntries (
            EntryID      INT IDENTITY(1,1) PRIMARY KEY,
            RegID        INT NOT NULL,
            ClassID      INT NOT NULL,
            Placement    NVARCHAR(50),
            JudgeNotes   NVARCHAR(MAX),
            ScoresheetJSON NVARCHAR(MAX),
            CreatedDate  DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventHalterPens')
        CREATE TABLE OFNEventHalterPens (
            PenID            INT IDENTITY(1,1) PRIMARY KEY,
            EventID          INT NOT NULL,
            PeopleID         INT NOT NULL,
            BusinessID       INT,
            PenNumber        INT,
            PenType          NVARCHAR(50),
            NeedsElectricity BIT DEFAULT 0,
            NeedsStallMat    BIT DEFAULT 0,
            NeedsVetCheck    BIT DEFAULT 0,
            Notes            NVARCHAR(MAX),
            Fee              DECIMAL(10,2) DEFAULT 0,
            CreatedDate      DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


try:
    with SessionLocal() as _db:
        ensure_tables(_db)
except Exception as e:
    print(f"[event_halter] Table ensure warning: {e}")


def _current_animal_fee(cfg: dict) -> float:
    full = float(cfg.get("FeePerAnimal") or 0)
    disc = cfg.get("DiscountFeePerAnimal")
    end = cfg.get("DiscountEndDate")
    if disc is not None and end:
        try:
            if end >= date.today():
                return float(disc)
        except Exception:
            pass
    return full


# ---------- CONFIG ----------

@router.get("/api/events/{event_id}/halter/config")
def get_halter_config(event_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT * FROM OFNEventHalterConfig WHERE EventID = :eid
    """), {"eid": event_id}).fetchone()
    if not row:
        return {"configured": False, "EventID": event_id}
    cfg = dict(row._mapping)
    cfg["configured"] = True
    cfg["CurrentFeePerAnimal"] = _current_animal_fee(cfg)
    return cfg


@router.put("/api/events/{event_id}/halter/config")
def put_halter_config(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    exists = db.execute(text("SELECT ConfigID FROM OFNEventHalterConfig WHERE EventID = :eid"),
                       {"eid": event_id}).fetchone()
    params = {
        "eid": event_id,
        "desc": body.get("Description"),
        "fee": body.get("FeePerAnimal") or 0,
        "dfee": body.get("DiscountFeePerAnimal"),
        "dend": body.get("DiscountEndDate"),
        "fpen": body.get("FeePerPen") or 0,
        "fprod": body.get("FeePerProductionAnimal") or 0,
        "vet": body.get("VetCheckFee") or 0,
        "elec": body.get("ElectricityFee") or 0,
        "mat": body.get("StallMatFee") or 0,
        "mpens": body.get("MaxPensPerFarm"),
        "mjuv": body.get("MaxJuvenilesPerPen"),
        "madu": body.get("MaxAdultsPerPen"),
        "rend": body.get("RegistrationEndDate"),
        "active": 1 if body.get("IsActive", True) else 0,
    }
    if exists:
        db.execute(text("""
            UPDATE OFNEventHalterConfig SET
              Description=:desc, FeePerAnimal=:fee, DiscountFeePerAnimal=:dfee,
              DiscountEndDate=:dend, FeePerPen=:fpen, FeePerProductionAnimal=:fprod,
              VetCheckFee=:vet, ElectricityFee=:elec, StallMatFee=:mat,
              MaxPensPerFarm=:mpens, MaxJuvenilesPerPen=:mjuv, MaxAdultsPerPen=:madu,
              RegistrationEndDate=:rend, IsActive=:active, UpdatedDate=GETDATE()
            WHERE EventID=:eid
        """), params)
    else:
        db.execute(text("""
            INSERT INTO OFNEventHalterConfig
              (EventID, Description, FeePerAnimal, DiscountFeePerAnimal, DiscountEndDate,
               FeePerPen, FeePerProductionAnimal, VetCheckFee, ElectricityFee, StallMatFee,
               MaxPensPerFarm, MaxJuvenilesPerPen, MaxAdultsPerPen, RegistrationEndDate, IsActive)
            VALUES (:eid, :desc, :fee, :dfee, :dend, :fpen, :fprod, :vet, :elec, :mat,
                    :mpens, :mjuv, :madu, :rend, :active)
        """), params)
    db.commit()
    return {"ok": True}


# ---------- CLASSES ----------

@router.get("/api/events/{event_id}/halter/classes")
def list_classes(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT * FROM OFNEventHalterClasses
        WHERE EventID = :eid AND IsActive = 1
        ORDER BY Breed, DisplayOrder, ClassName
    """), {"eid": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/halter/classes")
def add_class(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    r = db.execute(text("""
        INSERT INTO OFNEventHalterClasses
          (EventID, ClassName, ClassCode, ShornCode, Breed, Gender, AgeGroup, ClassType, DisplayOrder)
        VALUES (:eid, :n, :c, :sc, :b, :g, :a, :t, :o);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "eid": event_id,
        "n": body.get("ClassName"),
        "c": body.get("ClassCode"),
        "sc": body.get("ShornCode"),
        "b": body.get("Breed"),
        "g": body.get("Gender"),
        "a": body.get("AgeGroup"),
        "t": body.get("ClassType") or "Halter",
        "o": body.get("DisplayOrder") or 0,
    })
    new_id = r.fetchone()[0]
    db.commit()
    return {"ClassID": int(new_id)}


@router.put("/api/events/halter/classes/{class_id}")
def edit_class(class_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventHalterClasses SET
          ClassName=:n, ClassCode=:c, ShornCode=:sc, Breed=:b,
          Gender=:g, AgeGroup=:a, ClassType=:t, DisplayOrder=:o
        WHERE ClassID=:cid
    """), {
        "cid": class_id,
        "n": body.get("ClassName"),
        "c": body.get("ClassCode"),
        "sc": body.get("ShornCode"),
        "b": body.get("Breed"),
        "g": body.get("Gender"),
        "a": body.get("AgeGroup"),
        "t": body.get("ClassType") or "Halter",
        "o": body.get("DisplayOrder") or 0,
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/halter/classes/{class_id}")
def delete_class(class_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE OFNEventHalterClasses SET IsActive=0 WHERE ClassID=:cid"),
               {"cid": class_id})
    db.commit()
    return {"ok": True}


def _seed_alpaca(breed: str):
    """Return (class_rows) for the 17×4×2 alpaca halter standard."""
    colors = ["White", "Beige", "Light Fawn", "Medium Fawn", "Dark Fawn",
              "Light Brown", "Medium Brown", "Dark Brown", "Bay Black", "True Black",
              "Light Silver Grey", "Medium Silver Grey", "Dark Silver Grey",
              "Light Rose Grey", "Medium Rose Grey", "Dark Rose Grey", "Multi"]
    ages = [("Juvenile", "6-12 months"), ("Yearling", "12-24 months"),
            ("Two Year Old", "24-36 months"), ("Adult", "36+ months")]
    rows, order = [], 0
    for color in colors:
        for age_name, age_desc in ages:
            for gender in ("Female", "Male"):
                order += 1
                rows.append({
                    "name": f"{color} {age_name} {gender}",
                    "code": f"{breed[:1]}-{color[:2].upper()}-{age_name[:1]}{gender[:1]}",
                    "breed": breed, "gender": gender, "age": age_desc,
                    "class_type": "Halter", "order": order,
                })
    return rows


def _seed_horse(breed: str):
    """Standard horse class set: halter-by-age + common performance disciplines."""
    halter_age_gender = [
        ("Weanling", "0-1 yr"),
        ("Yearling", "1-2 yr"),
        ("Two Year Old", "2-3 yr"),
        ("Three Year Old", "3-4 yr"),
        ("Aged", "4+ yr"),
    ]
    rows, order = [], 0
    for age_name, age_desc in halter_age_gender:
        for gender in ("Mare", "Stallion", "Gelding"):
            order += 1
            rows.append({
                "name": f"{age_name} {gender}",
                "code": f"H-{age_name[:2].upper()}-{gender[:1]}",
                "breed": breed, "gender": gender, "age": age_desc,
                "class_type": "Halter", "order": order,
            })
    disciplines = [
        ("Western Pleasure", "Western Pleasure"),
        ("Reining", "Reining"),
        ("Trail", "Trail"),
        ("Dressage", "Dressage"),
        ("Show Jumping", "Show Jumping"),
        ("Hunters", "Hunters"),
        ("Barrel Racing", "Barrel Racing"),
        ("Pole Bending", "Pole Bending"),
        ("Showmanship", "Showmanship"),
        ("Horsemanship", "Horsemanship"),
    ]
    for name, ctype in disciplines:
        order += 1
        rows.append({
            "name": name, "code": f"D-{name[:3].upper()}",
            "breed": breed, "gender": "Open", "age": "",
            "class_type": ctype, "order": order,
        })
    return rows


def _seed_by_age_gender(breed: str, age_genders):
    """Generic 'Halter by age/gender' seeder for sheep, goats, etc."""
    rows, order = [], 0
    for age_name, age_desc, genders in age_genders:
        for gender in genders:
            order += 1
            rows.append({
                "name": f"{age_name} {gender}",
                "code": f"{breed[:1]}-{age_name[:2].upper()}-{gender[:1]}",
                "breed": breed, "gender": gender, "age": age_desc,
                "class_type": "Halter", "order": order,
            })
    return rows


def _seed_sheep(breed: str):
    return _seed_by_age_gender(breed, [
        ("Ram Lamb",     "under 1 yr",  ["Ram"]),
        ("Yearling Ram", "1-2 yr",      ["Ram"]),
        ("Aged Ram",     "2+ yr",       ["Ram"]),
        ("Ewe Lamb",     "under 1 yr",  ["Ewe"]),
        ("Yearling Ewe", "1-2 yr",      ["Ewe"]),
        ("Aged Ewe",     "2+ yr",       ["Ewe"]),
    ])


def _seed_goat(breed: str):
    return _seed_by_age_gender(breed, [
        ("Buck Kid",      "under 1 yr", ["Buck"]),
        ("Yearling Buck", "1-2 yr",     ["Buck"]),
        ("Aged Buck",     "2+ yr",      ["Buck"]),
        ("Doe Kid",       "under 1 yr", ["Doe"]),
        ("Yearling Doe",  "1-2 yr",     ["Doe"]),
        ("Aged Doe",      "2+ yr",      ["Doe"]),
        ("Wether",        "any age",    ["Wether"]),
    ])


_TEMPLATE_BUILDERS = {
    "alpaca-standard": _seed_alpaca,
    "horse-standard":  _seed_horse,
    "sheep-standard":  _seed_sheep,
    "goat-standard":   _seed_goat,
}


@router.post("/api/events/{event_id}/halter/classes/bulk-seed")
def bulk_seed_classes(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    """Seed a standard halter class set for a breed. Supports multiple templates."""
    breed = body.get("Breed") or "Huacaya"
    template = body.get("Template") or "alpaca-standard"
    builder = _TEMPLATE_BUILDERS.get(template)
    if not builder:
        raise HTTPException(400, f"unknown template: {template}")
    existing = db.execute(text("""
        SELECT COUNT(*) FROM OFNEventHalterClasses WHERE EventID=:eid AND Breed=:b AND IsActive=1
    """), {"eid": event_id, "b": breed}).fetchone()[0]
    if existing:
        raise HTTPException(400, f"{breed} classes already exist for this event")
    rows = builder(breed)
    for r in rows:
        db.execute(text("""
            INSERT INTO OFNEventHalterClasses
              (EventID, ClassName, ClassCode, Breed, Gender, AgeGroup, ClassType, DisplayOrder)
            VALUES (:eid, :n, :c, :b, :g, :a, :t, :o)
        """), {"eid": event_id, "n": r["name"], "c": r["code"], "b": r["breed"],
               "g": r["gender"], "a": r["age"], "t": r["class_type"], "o": r["order"]})
    db.commit()
    return {"ok": True, "count": len(rows)}


# ---------- REGISTRATIONS ----------

@router.get("/api/events/{event_id}/halter/registrations")
def list_registrations(event_id: int, people_id: int | None = None, db: Session = Depends(get_db)):
    filt = "WHERE r.EventID = :eid"
    params = {"eid": event_id}
    if people_id:
        filt += " AND r.PeopleID = :pid"
        params["pid"] = people_id
    rows = db.execute(text(f"""
        SELECT r.*,
               a.AnimalName, a.DateOfBirth, a.Gender AS AnimalGender,
               a.FleeceColorID, a.RegisteredName,
               p.FirstName, p.LastName,
               b.BusinessName
        FROM OFNEventHalterRegistrations r
        LEFT JOIN Animals a ON a.AnimalID = r.AnimalID
        LEFT JOIN People p ON p.PeopleID = r.PeopleID
        LEFT JOIN Business b ON b.BusinessID = r.BusinessID
        {filt}
        ORDER BY r.CreatedDate DESC
    """), params).fetchall()
    regs = [dict(r._mapping) for r in rows]
    if regs:
        reg_ids = [r["RegID"] for r in regs]
        placeholders = ",".join(f":id{i}" for i, _ in enumerate(reg_ids))
        ep = {f"id{i}": rid for i, rid in enumerate(reg_ids)}
        entry_rows = db.execute(text(f"""
            SELECT e.*, c.ClassName, c.ClassCode, c.Breed, c.Gender, c.AgeGroup
            FROM OFNEventHalterClassEntries e
            LEFT JOIN OFNEventHalterClasses c ON c.ClassID = e.ClassID
            WHERE e.RegID IN ({placeholders})
        """), ep).fetchall()
        by_reg = {}
        for e in entry_rows:
            d = dict(e._mapping)
            by_reg.setdefault(d["RegID"], []).append(d)
        for r in regs:
            r["classes"] = by_reg.get(r["RegID"], [])
    return regs


@router.post("/api/events/{event_id}/halter/registrations")
def add_registration(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    cfg_row = db.execute(text("SELECT * FROM OFNEventHalterConfig WHERE EventID=:eid"),
                        {"eid": event_id}).fetchone()
    if not cfg_row:
        raise HTTPException(400, "Show is not configured")
    cfg = dict(cfg_row._mapping)
    if cfg.get("RegistrationEndDate") and cfg["RegistrationEndDate"] < date.today():
        raise HTTPException(400, "Registration has closed")
    if not body.get("PeopleID") or not body.get("AnimalID"):
        raise HTTPException(400, "PeopleID and AnimalID required")
    reg_type = body.get("RegistrationType") or "Halter"
    if reg_type == "Production":
        fee = float(cfg.get("FeePerProductionAnimal") or 0)
    else:
        fee = _current_animal_fee(cfg)
    r = db.execute(text("""
        INSERT INTO OFNEventHalterRegistrations
          (EventID, PeopleID, BusinessID, AnimalID, RegistrationType, IsShorn, Fee)
        VALUES (:eid, :pid, :bid, :aid, :rt, :shorn, :fee);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "eid": event_id,
        "pid": body.get("PeopleID"),
        "bid": body.get("BusinessID"),
        "aid": body.get("AnimalID"),
        "rt": reg_type,
        "shorn": 1 if body.get("IsShorn") else 0,
        "fee": fee,
    })
    reg_id = int(r.fetchone()[0])
    for cid in body.get("ClassIDs") or []:
        db.execute(text("""
            INSERT INTO OFNEventHalterClassEntries (RegID, ClassID) VALUES (:r, :c)
        """), {"r": reg_id, "c": int(cid)})
    db.commit()
    return {"RegID": reg_id, "Fee": fee}


@router.put("/api/events/halter/registrations/{reg_id}")
def update_registration(reg_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventHalterRegistrations SET
          IsShorn=:shorn, IsCheckedIn=:chk, CheckInNotes=:notes, PaidStatus=:paid
        WHERE RegID=:rid
    """), {
        "rid": reg_id,
        "shorn": 1 if body.get("IsShorn") else 0,
        "chk": 1 if body.get("IsCheckedIn") else 0,
        "notes": body.get("CheckInNotes"),
        "paid": body.get("PaidStatus") or "pending",
    })
    if "ClassIDs" in body:
        db.execute(text("DELETE FROM OFNEventHalterClassEntries WHERE RegID=:r"),
                  {"r": reg_id})
        for cid in body.get("ClassIDs") or []:
            db.execute(text("""
                INSERT INTO OFNEventHalterClassEntries (RegID, ClassID) VALUES (:r, :c)
            """), {"r": reg_id, "c": int(cid)})
    db.commit()
    return {"ok": True}


@router.delete("/api/events/halter/registrations/{reg_id}")
def delete_registration(reg_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventHalterClassEntries WHERE RegID=:r"), {"r": reg_id})
    db.execute(text("DELETE FROM OFNEventHalterRegistrations WHERE RegID=:r"), {"r": reg_id})
    db.commit()
    return {"ok": True}


# ---------- JUDGING ----------

@router.get("/api/events/{event_id}/halter/classes/{class_id}/entries")
def class_entries(event_id: int, class_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT e.*, r.AnimalID, r.PeopleID, r.BusinessID, r.IsShorn, r.IsCheckedIn,
               a.AnimalName, a.RegisteredName, a.DateOfBirth,
               b.BusinessName, p.FirstName, p.LastName
        FROM OFNEventHalterClassEntries e
        JOIN OFNEventHalterRegistrations r ON r.RegID = e.RegID
        LEFT JOIN Animals a ON a.AnimalID = r.AnimalID
        LEFT JOIN People p ON p.PeopleID = r.PeopleID
        LEFT JOIN Business b ON b.BusinessID = r.BusinessID
        WHERE r.EventID = :eid AND e.ClassID = :cid
        ORDER BY e.Placement, a.AnimalName
    """), {"eid": event_id, "cid": class_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.put("/api/events/halter/entries/{entry_id}/judge")
def judge_entry(entry_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    placement = body.get("Placement")
    notes = body.get("JudgeNotes")
    db.execute(text("""
        UPDATE OFNEventHalterClassEntries SET
          Placement=:p, JudgeNotes=:n, ScoresheetJSON=:s
        WHERE EntryID=:eid
    """), {
        "eid": entry_id,
        "p": placement,
        "n": notes,
        "s": body.get("ScoresheetJSON"),
    })
    _sync_award_from_entry(db, entry_id)
    db.commit()
    return {"ok": True}


def _sync_award_from_entry(db: Session, entry_id: int) -> None:
    """
    Mirror a halter entry's Placement into the legacy `awards` table so it
    shows up on LivestockAnimalDetail's "Awards & Shows" block and on the
    marketplace sale card. Idempotent: matches on (AnimalID, EventID, ClassID)
    via the AwardsComments marker and updates in place.
    """
    row = db.execute(text("""
        SELECT e.EntryID, e.ClassID, e.Placement, e.JudgeNotes,
               r.AnimalID, r.EventID,
               c.ClassName, c.ClassCode,
               ev.EventName, ev.StartDate
        FROM OFNEventHalterClassEntries e
        JOIN OFNEventHalterRegistrations r ON r.RegID = e.RegID
        LEFT JOIN OFNEventHalterClasses c ON c.ClassID = e.ClassID
        LEFT JOIN OFNEvents ev ON ev.EventID = r.EventID
        WHERE e.EntryID = :eid
    """), {"eid": entry_id}).fetchone()
    if not row:
        return
    r = dict(row._mapping)
    if not r.get("AnimalID"):
        return
    marker = f"[ofn-halter:{r['EventID']}:{r['ClassID']}:{entry_id}]"
    placing = r.get("Placement")
    # If placement was cleared, remove any matching award row (keeps awards tidy)
    if placing in (None, "", 0):
        db.execute(text("""
            DELETE FROM awards
            WHERE AnimalID=:aid AND Awardcomments LIKE :marker
        """), {"aid": r["AnimalID"], "marker": f"%{marker}%"})
        return
    year = None
    if r.get("StartDate"):
        try:
            year = r["StartDate"].year
        except Exception:
            try:
                year = int(str(r["StartDate"])[:4])
            except Exception:
                year = None
    show_name = r.get("EventName") or ""
    class_label = " — ".join(filter(None, [r.get("ClassCode"), r.get("ClassName")]))
    comment_body = r.get("JudgeNotes") or ""
    comments = f"{comment_body}\n{marker}".strip()
    existing = db.execute(text("""
        SELECT AwardsID FROM awards
        WHERE AnimalID=:aid AND Awardcomments LIKE :marker
    """), {"aid": r["AnimalID"], "marker": f"%{marker}%"}).fetchone()
    params = {
        "aid": r["AnimalID"],
        "year": year,
        "show": show_name,
        "aclass": class_label,
        "placing": str(placing),
        "comments": comments,
    }
    if existing:
        params["awid"] = existing[0]
        db.execute(text("""
            UPDATE awards SET
              AwardYear=:year, ShowName=:show, Type=:aclass,
              Placing=:placing, Awardcomments=:comments
            WHERE AwardsID=:awid
        """), params)
    else:
        db.execute(text("""
            INSERT INTO awards (AnimalID, AwardYear, ShowName, Type, Placing, Awardcomments)
            VALUES (:aid, :year, :show, :aclass, :placing, :comments)
        """), params)


# ---------- PENS ----------

@router.get("/api/events/{event_id}/halter/pens")
def list_pens(event_id: int, people_id: int | None = None, db: Session = Depends(get_db)):
    filt = "WHERE p.EventID = :eid"
    params = {"eid": event_id}
    if people_id:
        filt += " AND p.PeopleID = :pid"
        params["pid"] = people_id
    rows = db.execute(text(f"""
        SELECT p.*, b.BusinessName, pe.FirstName, pe.LastName
        FROM OFNEventHalterPens p
        LEFT JOIN Business b ON b.BusinessID = p.BusinessID
        LEFT JOIN People pe ON pe.PeopleID = p.PeopleID
        {filt}
        ORDER BY p.PenNumber, p.CreatedDate
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/halter/pens")
def add_pen(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    cfg_row = db.execute(text("SELECT * FROM OFNEventHalterConfig WHERE EventID=:eid"),
                        {"eid": event_id}).fetchone()
    cfg = dict(cfg_row._mapping) if cfg_row else {}
    fee = float(cfg.get("FeePerPen") or 0)
    if body.get("NeedsElectricity"):
        fee += float(cfg.get("ElectricityFee") or 0)
    if body.get("NeedsStallMat"):
        fee += float(cfg.get("StallMatFee") or 0)
    if body.get("NeedsVetCheck"):
        fee += float(cfg.get("VetCheckFee") or 0)
    r = db.execute(text("""
        INSERT INTO OFNEventHalterPens
          (EventID, PeopleID, BusinessID, PenType, NeedsElectricity, NeedsStallMat, NeedsVetCheck, Notes, Fee)
        VALUES (:eid, :pid, :bid, :t, :e, :m, :v, :n, :f);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "eid": event_id,
        "pid": body.get("PeopleID"),
        "bid": body.get("BusinessID"),
        "t": body.get("PenType") or "Adult",
        "e": 1 if body.get("NeedsElectricity") else 0,
        "m": 1 if body.get("NeedsStallMat") else 0,
        "v": 1 if body.get("NeedsVetCheck") else 0,
        "n": body.get("Notes"),
        "f": fee,
    })
    pen_id = int(r.fetchone()[0])
    db.commit()
    return {"PenID": pen_id, "Fee": fee}


@router.delete("/api/events/halter/pens/{pen_id}")
def delete_pen(pen_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventHalterPens WHERE PenID=:p"), {"p": pen_id})
    db.commit()
    return {"ok": True}
