"""
Farm Tour / Open House.

Organizer defines time slots with a capacity cap, optional add-ons (tea, cheese plate,
souvenir), and a liability waiver. Visitors pick a slot, declare party size, sign the
waiver (name + date), and optionally add purchases. Organizer tracks attendance and
payment per registration.
"""
from fastapi import APIRouter, Depends, HTTPException
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal
from datetime import date

try:
    from event_emails import send_registration_confirmation
except Exception:
    send_registration_confirmation = None

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventTourConfig')
        CREATE TABLE OFNEventTourConfig (
            ConfigID              INT IDENTITY(1,1) PRIMARY KEY,
            EventID               INT NOT NULL UNIQUE,
            Description           NVARCHAR(MAX),
            PricePerAdult         DECIMAL(10,2) DEFAULT 0,
            PricePerChild         DECIMAL(10,2),
            ChildAgeLimit         INT DEFAULT 12,
            DefaultSlotCapacity   INT DEFAULT 15,
            RequireWaiver         BIT DEFAULT 1,
            WaiverText            NVARCHAR(MAX),
            ParkingNotes          NVARCHAR(MAX),
            DrivingDirections     NVARCHAR(MAX),
            ThingsToBring         NVARCHAR(MAX),
            RegistrationEndDate   DATE,
            IsActive              BIT DEFAULT 1,
            CreatedDate           DATETIME DEFAULT GETDATE(),
            UpdatedDate           DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventTourSlots')
        CREATE TABLE OFNEventTourSlots (
            SlotID       INT IDENTITY(1,1) PRIMARY KEY,
            EventID      INT NOT NULL,
            SlotStart    DATETIME NOT NULL,
            DurationMin  INT DEFAULT 60,
            Capacity     INT NOT NULL DEFAULT 15,
            Notes        NVARCHAR(MAX),
            IsActive     BIT DEFAULT 1,
            CreatedDate  DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventTourAddOns')
        CREATE TABLE OFNEventTourAddOns (
            AddOnID         INT IDENTITY(1,1) PRIMARY KEY,
            EventID         INT NOT NULL,
            AddOnName       NVARCHAR(300) NOT NULL,
            AddOnDescription NVARCHAR(MAX),
            Price           DECIMAL(10,2) DEFAULT 0,
            MaxQuantity     INT,
            DisplayOrder    INT DEFAULT 0,
            IsActive        BIT DEFAULT 1,
            CreatedDate     DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventTourRegistrations')
        CREATE TABLE OFNEventTourRegistrations (
            RegID               INT IDENTITY(1,1) PRIMARY KEY,
            EventID             INT NOT NULL,
            SlotID              INT NOT NULL,
            PeopleID            INT,
            BusinessID          INT,
            GuestName           NVARCHAR(300) NOT NULL,
            GuestEmail          NVARCHAR(300),
            GuestPhone          NVARCHAR(50),
            PartySize           INT NOT NULL DEFAULT 1,
            ChildCount          INT DEFAULT 0,
            WaiverSignedBy      NVARCHAR(300),
            WaiverSignedDate    DATETIME,
            SpecialRequests     NVARCHAR(MAX),
            TicketFee           DECIMAL(10,2) DEFAULT 0,
            AddOnsTotal         DECIMAL(10,2) DEFAULT 0,
            TotalFee            DECIMAL(10,2) DEFAULT 0,
            PaidStatus          NVARCHAR(20) DEFAULT 'pending',
            Status              NVARCHAR(50) DEFAULT 'confirmed',
            CheckedIn           BIT DEFAULT 0,
            CheckedInAt         DATETIME,
            OrganizerNotes      NVARCHAR(MAX),
            CreatedDate         DATETIME DEFAULT GETDATE(),
            UpdatedDate         DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventTourAddOnSelections')
        CREATE TABLE OFNEventTourAddOnSelections (
            SelectionID   INT IDENTITY(1,1) PRIMARY KEY,
            RegID         INT NOT NULL,
            EventID       INT NOT NULL,
            AddOnID       INT NOT NULL,
            Quantity      INT DEFAULT 1,
            UnitPrice     DECIMAL(10,2) DEFAULT 0,
            CreatedDate   DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


try:
    with SessionLocal() as _db:
        ensure_tables(_db)
except Exception as e:
    print(f"[event_farm_tour] Table ensure warning: {e}")


def _ticket_fee(cfg: dict, party_size: int, child_count: int) -> float:
    party = int(party_size or 0)
    kids = min(int(child_count or 0), party)
    adults = max(0, party - kids)
    adult_price = float(cfg.get("PricePerAdult") or 0)
    child_price = cfg.get("PricePerChild")
    child_price = float(child_price) if child_price is not None else adult_price
    return adults * adult_price + kids * child_price


# ---------- CONFIG ----------

@router.get("/api/events/{event_id}/tour/config")
def get_config(event_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT * FROM OFNEventTourConfig WHERE EventID=:e"),
                    {"e": event_id}).fetchone()
    if not row:
        return {"configured": False, "EventID": event_id}
    cfg = dict(row._mapping)
    cfg["configured"] = True
    return cfg


@router.put("/api/events/{event_id}/tour/config")
def put_config(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    exists = db.execute(text("SELECT ConfigID FROM OFNEventTourConfig WHERE EventID=:e"),
                       {"e": event_id}).fetchone()
    params = {
        "e": event_id,
        "d": body.get("Description"),
        "pa": body.get("PricePerAdult") or 0,
        "pc": body.get("PricePerChild"),
        "cal": body.get("ChildAgeLimit") or 12,
        "dsc": body.get("DefaultSlotCapacity") or 15,
        "rw": 1 if body.get("RequireWaiver", True) else 0,
        "wt": body.get("WaiverText"),
        "pn": body.get("ParkingNotes"),
        "dd": body.get("DrivingDirections"),
        "ttb": body.get("ThingsToBring"),
        "red": body.get("RegistrationEndDate"),
        "a": 1 if body.get("IsActive", True) else 0,
    }
    if exists:
        db.execute(text("""
            UPDATE OFNEventTourConfig SET
              Description=:d, PricePerAdult=:pa, PricePerChild=:pc, ChildAgeLimit=:cal,
              DefaultSlotCapacity=:dsc, RequireWaiver=:rw, WaiverText=:wt,
              ParkingNotes=:pn, DrivingDirections=:dd, ThingsToBring=:ttb,
              RegistrationEndDate=:red, IsActive=:a, UpdatedDate=GETDATE()
            WHERE EventID=:e
        """), params)
    else:
        db.execute(text("""
            INSERT INTO OFNEventTourConfig
              (EventID, Description, PricePerAdult, PricePerChild, ChildAgeLimit,
               DefaultSlotCapacity, RequireWaiver, WaiverText, ParkingNotes,
               DrivingDirections, ThingsToBring, RegistrationEndDate, IsActive)
            VALUES (:e, :d, :pa, :pc, :cal, :dsc, :rw, :wt, :pn, :dd, :ttb, :red, :a)
        """), params)
    db.commit()
    return {"ok": True}


# ---------- SLOTS ----------

@router.get("/api/events/{event_id}/tour/slots")
def list_slots(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT s.*,
          (SELECT COALESCE(SUM(r.PartySize), 0)
           FROM OFNEventTourRegistrations r
           WHERE r.SlotID = s.SlotID AND r.Status <> 'cancelled') AS Booked
        FROM OFNEventTourSlots s
        WHERE s.EventID = :e
        ORDER BY s.SlotStart
    """), {"e": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/tour/slots")
def add_slot(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    if not body.get("SlotStart"):
        raise HTTPException(400, "SlotStart required")
    r = db.execute(text("""
        INSERT INTO OFNEventTourSlots (EventID, SlotStart, DurationMin, Capacity, Notes, IsActive)
        VALUES (:e, :s, :dm, :c, :n, :a);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "e": event_id, "s": body["SlotStart"],
        "dm": body.get("DurationMin") or 60,
        "c": body.get("Capacity") or 15,
        "n": body.get("Notes"),
        "a": 1 if body.get("IsActive", True) else 0,
    })
    new_id = int(r.fetchone()[0])
    db.commit()
    return {"SlotID": new_id}


@router.put("/api/events/tour/slots/{slot_id}")
def update_slot(slot_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventTourSlots SET
          SlotStart=:s, DurationMin=:dm, Capacity=:c, Notes=:n, IsActive=:a
        WHERE SlotID=:sid
    """), {
        "sid": slot_id, "s": body.get("SlotStart"),
        "dm": body.get("DurationMin") or 60,
        "c": body.get("Capacity") or 15,
        "n": body.get("Notes"),
        "a": 1 if body.get("IsActive", True) else 0,
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/tour/slots/{slot_id}")
def delete_slot(slot_id: int, db: Session = Depends(get_db)):
    booked = db.execute(text("""
        SELECT COUNT(*) FROM OFNEventTourRegistrations WHERE SlotID=:s AND Status <> 'cancelled'
    """), {"s": slot_id}).fetchone()[0]
    if booked:
        raise HTTPException(400, f"Cannot delete: {booked} registration(s) on this slot")
    db.execute(text("DELETE FROM OFNEventTourSlots WHERE SlotID=:s"), {"s": slot_id})
    db.commit()
    return {"ok": True}


# ---------- ADD-ONS ----------

@router.get("/api/events/{event_id}/tour/addons")
def list_addons(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT * FROM OFNEventTourAddOns WHERE EventID=:e
        ORDER BY DisplayOrder, AddOnName
    """), {"e": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/tour/addons")
def add_addon(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    if not body.get("AddOnName"):
        raise HTTPException(400, "AddOnName required")
    r = db.execute(text("""
        INSERT INTO OFNEventTourAddOns
          (EventID, AddOnName, AddOnDescription, Price, MaxQuantity, DisplayOrder, IsActive)
        VALUES (:e, :n, :d, :p, :mq, :o, :a);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "e": event_id, "n": body["AddOnName"],
        "d": body.get("AddOnDescription"),
        "p": body.get("Price") or 0,
        "mq": body.get("MaxQuantity"),
        "o": body.get("DisplayOrder") or 0,
        "a": 1 if body.get("IsActive", True) else 0,
    })
    new_id = int(r.fetchone()[0])
    db.commit()
    return {"AddOnID": new_id}


@router.put("/api/events/tour/addons/{addon_id}")
def update_addon(addon_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventTourAddOns SET
          AddOnName=:n, AddOnDescription=:d, Price=:p,
          MaxQuantity=:mq, DisplayOrder=:o, IsActive=:a
        WHERE AddOnID=:aid
    """), {
        "aid": addon_id, "n": body.get("AddOnName"),
        "d": body.get("AddOnDescription"),
        "p": body.get("Price") or 0,
        "mq": body.get("MaxQuantity"),
        "o": body.get("DisplayOrder") or 0,
        "a": 1 if body.get("IsActive", True) else 0,
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/tour/addons/{addon_id}")
def delete_addon(addon_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventTourAddOns WHERE AddOnID=:a"), {"a": addon_id})
    db.commit()
    return {"ok": True}


# ---------- REGISTRATIONS ----------

def _load_selections(db: Session, reg_ids: list[int]) -> dict:
    if not reg_ids:
        return {}
    placeholders = ", ".join(f":r{i}" for i in range(len(reg_ids)))
    params = {f"r{i}": rid for i, rid in enumerate(reg_ids)}
    rows = db.execute(text(f"""
        SELECT s.*, a.AddOnName
        FROM OFNEventTourAddOnSelections s
        LEFT JOIN OFNEventTourAddOns a ON a.AddOnID = s.AddOnID
        WHERE s.RegID IN ({placeholders})
    """), params).fetchall()
    out: dict = {}
    for r in rows:
        d = dict(r._mapping)
        out.setdefault(d["RegID"], []).append(d)
    return out


@router.get("/api/events/{event_id}/tour/registrations")
def list_registrations(event_id: int, people_id: int | None = None,
                       slot_id: int | None = None, db: Session = Depends(get_db)):
    filters = ["r.EventID = :e"]
    params = {"e": event_id}
    if people_id:
        filters.append("r.PeopleID = :p")
        params["p"] = people_id
    if slot_id:
        filters.append("r.SlotID = :s")
        params["s"] = slot_id
    where = " AND ".join(filters)
    rows = db.execute(text(f"""
        SELECT r.*, s.SlotStart, s.DurationMin, s.Capacity
        FROM OFNEventTourRegistrations r
        LEFT JOIN OFNEventTourSlots s ON s.SlotID = r.SlotID
        WHERE {where}
        ORDER BY s.SlotStart, r.GuestName
    """), params).fetchall()
    regs = [dict(r._mapping) for r in rows]
    sel_map = _load_selections(db, [r["RegID"] for r in regs])
    for r in regs:
        r["AddOns"] = sel_map.get(r["RegID"], [])
    return regs


@router.post("/api/events/{event_id}/tour/registrations")
def add_registration(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    cfg_row = db.execute(text("SELECT * FROM OFNEventTourConfig WHERE EventID=:e"),
                        {"e": event_id}).fetchone()
    if not cfg_row:
        raise HTTPException(400, "Tour not configured")
    cfg = dict(cfg_row._mapping)
    if cfg.get("RegistrationEndDate") and cfg["RegistrationEndDate"] < date.today():
        raise HTTPException(400, "Registration has closed")
    if not body.get("GuestName"):
        raise HTTPException(400, "GuestName required")
    slot_id = body.get("SlotID")
    if not slot_id:
        raise HTTPException(400, "SlotID required")

    slot = db.execute(text("SELECT * FROM OFNEventTourSlots WHERE SlotID=:s AND EventID=:e"),
                     {"s": slot_id, "e": event_id}).fetchone()
    if not slot:
        raise HTTPException(400, "Slot not found")
    slot_d = dict(slot._mapping)

    party_size = int(body.get("PartySize") or 1)
    child_count = int(body.get("ChildCount") or 0)

    booked = db.execute(text("""
        SELECT COALESCE(SUM(PartySize), 0) FROM OFNEventTourRegistrations
        WHERE SlotID=:s AND Status <> 'cancelled'
    """), {"s": slot_id}).fetchone()[0] or 0
    if int(booked) + party_size > int(slot_d["Capacity"]):
        raise HTTPException(400, f"Only {int(slot_d['Capacity']) - int(booked)} spots left in that slot")

    if cfg.get("RequireWaiver") and not body.get("WaiverSignedBy"):
        raise HTTPException(400, "Waiver must be signed")

    add_ons = body.get("AddOns") or []
    addon_total = 0.0
    if add_ons:
        ids = [int(a.get("AddOnID")) for a in add_ons if a.get("AddOnID")]
        if ids:
            placeholders = ", ".join(f":a{i}" for i in range(len(ids)))
            params_a = {f"a{i}": aid for i, aid in enumerate(ids)}
            arows = db.execute(text(
                f"SELECT AddOnID, Price FROM OFNEventTourAddOns WHERE AddOnID IN ({placeholders})"
            ), params_a).fetchall()
            price_map = {int(a[0]): float(a[1] or 0) for a in arows}
            for a in add_ons:
                aid = a.get("AddOnID")
                qty = int(a.get("Quantity") or 1)
                if aid:
                    addon_total += price_map.get(int(aid), 0.0) * qty

    ticket_fee = _ticket_fee(cfg, party_size, child_count)
    total = ticket_fee + addon_total

    r = db.execute(text("""
        INSERT INTO OFNEventTourRegistrations
          (EventID, SlotID, PeopleID, BusinessID, GuestName, GuestEmail, GuestPhone,
           PartySize, ChildCount, WaiverSignedBy, WaiverSignedDate, SpecialRequests,
           TicketFee, AddOnsTotal, TotalFee)
        VALUES (:e, :s, :p, :b, :gn, :ge, :gp, :ps, :cc, :ws,
                CASE WHEN :ws IS NULL THEN NULL ELSE GETDATE() END,
                :sr, :tf, :at, :t);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "e": event_id, "s": slot_id, "p": body.get("PeopleID"), "b": body.get("BusinessID"),
        "gn": body.get("GuestName"), "ge": body.get("GuestEmail"), "gp": body.get("GuestPhone"),
        "ps": party_size, "cc": child_count,
        "ws": body.get("WaiverSignedBy"),
        "sr": body.get("SpecialRequests"),
        "tf": ticket_fee, "at": addon_total, "t": total,
    })
    reg_id = int(r.fetchone()[0])
    for a in add_ons:
        aid = a.get("AddOnID")
        if not aid:
            continue
        qty = int(a.get("Quantity") or 1)
        price = 0.0
        price_row = db.execute(text("SELECT Price FROM OFNEventTourAddOns WHERE AddOnID=:a"),
                              {"a": int(aid)}).fetchone()
        if price_row:
            price = float(price_row[0] or 0)
        db.execute(text("""
            INSERT INTO OFNEventTourAddOnSelections (RegID, EventID, AddOnID, Quantity, UnitPrice)
            VALUES (:r, :e, :a, :q, :u)
        """), {"r": reg_id, "e": event_id, "a": int(aid), "q": qty, "u": price})
    db.commit()

    if send_registration_confirmation and body.get("GuestEmail"):
        try:
            ev = db.execute(text("""
                SELECT EventID, EventName, EventStartDate, EventLocationName,
                       EventLocationStreet, EventLocationCity, EventLocationState, EventLocationZip
                  FROM OFNEvents WHERE EventID = :e
            """), {"e": event_id}).mappings().first()
            extra = (
                f'<p style="font-size:13px;color:#555;margin:8px 0 0">'
                f'Party size: <b>{party_size}</b>'
                + (f' (children: {child_count})' if child_count else '')
                + f'<br/>Total: <b>${total:.2f}</b></p>'
            )
            send_registration_confirmation(
                to_email=body["GuestEmail"],
                attendee_name=body.get("GuestName") or "",
                event=dict(ev) if ev else {"EventID": event_id},
                kind="Tour",
                reg_id=reg_id,
                extra_html=extra,
            )
        except Exception as ex:
            print(f"[event_farm_tour] email send failed: {ex}")

    return {"RegID": reg_id, "TotalFee": total}


@router.put("/api/events/tour/registrations/{reg_id}")
def update_registration(reg_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    reg = db.execute(text("SELECT * FROM OFNEventTourRegistrations WHERE RegID=:r"),
                    {"r": reg_id}).fetchone()
    if not reg:
        raise HTTPException(404, "Not found")
    reg_d = dict(reg._mapping)
    db.execute(text("""
        UPDATE OFNEventTourRegistrations SET
          GuestName=:gn, GuestEmail=:ge, GuestPhone=:gp,
          PaidStatus=:pd, Status=:st, OrganizerNotes=:on, UpdatedDate=GETDATE()
        WHERE RegID=:r
    """), {
        "r": reg_id,
        "gn": body.get("GuestName", reg_d.get("GuestName")),
        "ge": body.get("GuestEmail", reg_d.get("GuestEmail")),
        "gp": body.get("GuestPhone", reg_d.get("GuestPhone")),
        "pd": body.get("PaidStatus", reg_d.get("PaidStatus") or "pending"),
        "st": body.get("Status", reg_d.get("Status") or "confirmed"),
        "on": body.get("OrganizerNotes", reg_d.get("OrganizerNotes")),
    })
    db.commit()
    return {"ok": True}


@router.put("/api/events/tour/registrations/{reg_id}/checkin")
def checkin(reg_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    checked = 1 if body.get("CheckedIn", True) else 0
    db.execute(text("""
        UPDATE OFNEventTourRegistrations SET
          CheckedIn=:c,
          CheckedInAt = CASE WHEN :c = 1 THEN GETDATE() ELSE NULL END,
          UpdatedDate=GETDATE()
        WHERE RegID=:r
    """), {"r": reg_id, "c": checked})
    db.commit()
    return {"ok": True}


@router.delete("/api/events/tour/registrations/{reg_id}")
def delete_registration(reg_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventTourAddOnSelections WHERE RegID=:r"), {"r": reg_id})
    db.execute(text("DELETE FROM OFNEventTourRegistrations WHERE RegID=:r"), {"r": reg_id})
    db.commit()
    return {"ok": True}
