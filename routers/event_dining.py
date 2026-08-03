"""
Event Dining (farm-to-table dinner, banquet, tasting).

Organizer configures seat cap, ticket pricing, and an optional menu with per-course
choices. Guests reserve seats, declare dietary restrictions, and pick one option per
course. Organizer assigns tables for a printable seating chart.
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
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventDiningConfig')
        CREATE TABLE OFNEventDiningConfig (
            ConfigID            INT IDENTITY(1,1) PRIMARY KEY,
            EventID             INT NOT NULL UNIQUE,
            Description         NVARCHAR(MAX),
            PricePerSeat        DECIMAL(10,2) DEFAULT 0,
            ChildPricePerSeat   DECIMAL(10,2),
            ChildAgeLimit       INT DEFAULT 12,
            MaxSeats            INT,
            MealTime            NVARCHAR(100),
            DressCode           NVARCHAR(200),
            MenuIntro           NVARCHAR(MAX),
            RegistrationEndDate DATE,
            IsActive            BIT DEFAULT 1,
            CreatedDate         DATETIME DEFAULT GETDATE(),
            UpdatedDate         DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventDiningMenuItems')
        CREATE TABLE OFNEventDiningMenuItems (
            MenuItemID      INT IDENTITY(1,1) PRIMARY KEY,
            EventID         INT NOT NULL,
            Course          NVARCHAR(50) NOT NULL,
            ItemName        NVARCHAR(300) NOT NULL,
            ItemDescription NVARCHAR(MAX),
            IsVegetarian    BIT DEFAULT 0,
            IsVegan         BIT DEFAULT 0,
            IsGlutenFree    BIT DEFAULT 0,
            UpchargeFee     DECIMAL(10,2) DEFAULT 0,
            DisplayOrder    INT DEFAULT 0,
            IsActive        BIT DEFAULT 1,
            CreatedDate     DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventDiningTables')
        CREATE TABLE OFNEventDiningTables (
            TableID        INT IDENTITY(1,1) PRIMARY KEY,
            EventID        INT NOT NULL,
            TableNumber    NVARCHAR(50) NOT NULL,
            SeatCount      INT NOT NULL DEFAULT 8,
            TableLocation  NVARCHAR(200),
            Notes          NVARCHAR(MAX),
            CreatedDate    DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventDiningRegistrations')
        CREATE TABLE OFNEventDiningRegistrations (
            RegID              INT IDENTITY(1,1) PRIMARY KEY,
            EventID            INT NOT NULL,
            PeopleID           INT,
            BusinessID         INT,
            GuestName          NVARCHAR(300) NOT NULL,
            GuestEmail         NVARCHAR(300),
            GuestPhone         NVARCHAR(50),
            PartySize          INT NOT NULL DEFAULT 1,
            ChildCount         INT DEFAULT 0,
            DietaryRestrictions NVARCHAR(MAX),
            SpecialRequests    NVARCHAR(MAX),
            TableID            INT,
            SeatNumbers        NVARCHAR(200),
            TotalFee           DECIMAL(10,2) DEFAULT 0,
            PaidStatus         NVARCHAR(20) DEFAULT 'pending',
            Status             NVARCHAR(50) DEFAULT 'confirmed',
            OrganizerNotes     NVARCHAR(MAX),
            CreatedDate        DATETIME DEFAULT GETDATE(),
            UpdatedDate        DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventDiningChoices')
        CREATE TABLE OFNEventDiningChoices (
            ChoiceID     INT IDENTITY(1,1) PRIMARY KEY,
            RegID        INT NOT NULL,
            EventID      INT NOT NULL,
            MenuItemID   INT NOT NULL,
            GuestLabel   NVARCHAR(200),
            CreatedDate  DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


try:
    with SessionLocal() as _db:
        ensure_tables(_db)
except Exception as e:
    print(f"[event_dining] Table ensure warning: {e}")


def _calc_fee(cfg: dict, party_size: int, child_count: int, upcharge_total: float) -> float:
    party = int(party_size or 0)
    kids = int(child_count or 0)
    adults = max(0, party - kids)
    adult_price = float(cfg.get("PricePerSeat") or 0)
    child_price = cfg.get("ChildPricePerSeat")
    child_price = float(child_price) if child_price is not None else adult_price
    return (adults * adult_price) + (kids * child_price) + float(upcharge_total or 0)


# ---------- CONFIG ----------

@router.get("/api/events/{event_id}/dining/config")
def get_config(event_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT * FROM OFNEventDiningConfig WHERE EventID=:e"),
                    {"e": event_id}).fetchone()
    if not row:
        return {"configured": False, "EventID": event_id}
    cfg = dict(row._mapping)
    cfg["configured"] = True
    seats_row = db.execute(text("""
        SELECT COALESCE(SUM(PartySize), 0) AS booked
        FROM OFNEventDiningRegistrations WHERE EventID=:e AND Status <> 'cancelled'
    """), {"e": event_id}).fetchone()
    cfg["SeatsBooked"] = int(seats_row[0]) if seats_row else 0
    return cfg


@router.put("/api/events/{event_id}/dining/config")
def put_config(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    exists = db.execute(text("SELECT ConfigID FROM OFNEventDiningConfig WHERE EventID=:e"),
                       {"e": event_id}).fetchone()
    params = {
        "e": event_id,
        "d": body.get("Description"),
        "p": body.get("PricePerSeat") or 0,
        "cp": body.get("ChildPricePerSeat"),
        "cal": body.get("ChildAgeLimit") or 12,
        "ms": body.get("MaxSeats"),
        "mt": body.get("MealTime"),
        "dc": body.get("DressCode"),
        "mi": body.get("MenuIntro"),
        "red": body.get("RegistrationEndDate"),
        "a": 1 if body.get("IsActive", True) else 0,
    }
    if exists:
        db.execute(text("""
            UPDATE OFNEventDiningConfig SET
              Description=:d, PricePerSeat=:p, ChildPricePerSeat=:cp, ChildAgeLimit=:cal,
              MaxSeats=:ms, MealTime=:mt, DressCode=:dc, MenuIntro=:mi,
              RegistrationEndDate=:red, IsActive=:a, UpdatedDate=GETDATE()
            WHERE EventID=:e
        """), params)
    else:
        db.execute(text("""
            INSERT INTO OFNEventDiningConfig
              (EventID, Description, PricePerSeat, ChildPricePerSeat, ChildAgeLimit,
               MaxSeats, MealTime, DressCode, MenuIntro, RegistrationEndDate, IsActive)
            VALUES (:e, :d, :p, :cp, :cal, :ms, :mt, :dc, :mi, :red, :a)
        """), params)
    db.commit()
    return {"ok": True}


# ---------- MENU ITEMS ----------

@router.get("/api/events/{event_id}/dining/menu")
def list_menu(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT * FROM OFNEventDiningMenuItems
        WHERE EventID=:e
        ORDER BY
          CASE Course
            WHEN 'Appetizer' THEN 1 WHEN 'Salad' THEN 2 WHEN 'Soup' THEN 3
            WHEN 'Main' THEN 4 WHEN 'Side' THEN 5 WHEN 'Dessert' THEN 6
            WHEN 'Beverage' THEN 7 ELSE 8 END,
          DisplayOrder, ItemName
    """), {"e": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/dining/menu")
def add_menu_item(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    if not body.get("Course") or not body.get("ItemName"):
        raise HTTPException(400, "Course and ItemName required")
    r = db.execute(text("""
        INSERT INTO OFNEventDiningMenuItems
          (EventID, Course, ItemName, ItemDescription, IsVegetarian, IsVegan, IsGlutenFree,
           UpchargeFee, DisplayOrder, IsActive)
        VALUES (:e, :c, :n, :desc, :vg, :vn, :gf, :u, :o, :a);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "e": event_id, "c": body["Course"], "n": body["ItemName"],
        "desc": body.get("ItemDescription"),
        "vg": 1 if body.get("IsVegetarian") else 0,
        "vn": 1 if body.get("IsVegan") else 0,
        "gf": 1 if body.get("IsGlutenFree") else 0,
        "u": body.get("UpchargeFee") or 0,
        "o": body.get("DisplayOrder") or 0,
        "a": 1 if body.get("IsActive", True) else 0,
    })
    new_id = int(r.fetchone()[0])
    db.commit()
    return {"MenuItemID": new_id}


@router.put("/api/events/dining/menu/{item_id}")
def update_menu_item(item_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventDiningMenuItems SET
          Course=:c, ItemName=:n, ItemDescription=:desc,
          IsVegetarian=:vg, IsVegan=:vn, IsGlutenFree=:gf,
          UpchargeFee=:u, DisplayOrder=:o, IsActive=:a
        WHERE MenuItemID=:m
    """), {
        "m": item_id, "c": body.get("Course"), "n": body.get("ItemName"),
        "desc": body.get("ItemDescription"),
        "vg": 1 if body.get("IsVegetarian") else 0,
        "vn": 1 if body.get("IsVegan") else 0,
        "gf": 1 if body.get("IsGlutenFree") else 0,
        "u": body.get("UpchargeFee") or 0,
        "o": body.get("DisplayOrder") or 0,
        "a": 1 if body.get("IsActive", True) else 0,
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/dining/menu/{item_id}")
def delete_menu_item(item_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventDiningMenuItems WHERE MenuItemID=:m"), {"m": item_id})
    db.commit()
    return {"ok": True}


# ---------- TABLES ----------

@router.get("/api/events/{event_id}/dining/tables")
def list_tables(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT t.*,
          (SELECT COALESCE(SUM(r.PartySize), 0)
           FROM OFNEventDiningRegistrations r
           WHERE r.TableID = t.TableID AND r.Status <> 'cancelled') AS SeatsAssigned
        FROM OFNEventDiningTables t
        WHERE t.EventID=:e
        ORDER BY TRY_CONVERT(INT, t.TableNumber), t.TableNumber
    """), {"e": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/dining/tables")
def add_table(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    if not body.get("TableNumber"):
        raise HTTPException(400, "TableNumber required")
    r = db.execute(text("""
        INSERT INTO OFNEventDiningTables
          (EventID, TableNumber, SeatCount, TableLocation, Notes)
        VALUES (:e, :tn, :sc, :loc, :n);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "e": event_id, "tn": body["TableNumber"],
        "sc": body.get("SeatCount") or 8,
        "loc": body.get("TableLocation"), "n": body.get("Notes"),
    })
    new_id = int(r.fetchone()[0])
    db.commit()
    return {"TableID": new_id}


@router.put("/api/events/dining/tables/{table_id}")
def update_table(table_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventDiningTables SET
          TableNumber=:tn, SeatCount=:sc, TableLocation=:loc, Notes=:n
        WHERE TableID=:t
    """), {
        "t": table_id, "tn": body.get("TableNumber"),
        "sc": body.get("SeatCount") or 8,
        "loc": body.get("TableLocation"), "n": body.get("Notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/dining/tables/{table_id}")
def delete_table(table_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE OFNEventDiningRegistrations SET TableID=NULL WHERE TableID=:t"),
              {"t": table_id})
    db.execute(text("DELETE FROM OFNEventDiningTables WHERE TableID=:t"), {"t": table_id})
    db.commit()
    return {"ok": True}


# ---------- REGISTRATIONS ----------

def _load_choices_for_regs(db: Session, reg_ids: list[int]) -> dict:
    if not reg_ids:
        return {}
    placeholders = ", ".join(f":r{i}" for i in range(len(reg_ids)))
    params = {f"r{i}": rid for i, rid in enumerate(reg_ids)}
    rows = db.execute(text(f"""
        SELECT c.*, m.ItemName, m.Course, m.UpchargeFee
        FROM OFNEventDiningChoices c
        LEFT JOIN OFNEventDiningMenuItems m ON m.MenuItemID = c.MenuItemID
        WHERE c.RegID IN ({placeholders})
    """), params).fetchall()
    out: dict = {}
    for r in rows:
        d = dict(r._mapping)
        out.setdefault(d["RegID"], []).append(d)
    return out


@router.get("/api/events/{event_id}/dining/registrations")
def list_registrations(event_id: int, people_id: int | None = None,
                       db: Session = Depends(get_db)):
    filters = ["EventID = :e"]
    params = {"e": event_id}
    if people_id:
        filters.append("PeopleID = :p")
        params["p"] = people_id
    where = " AND ".join(filters)
    rows = db.execute(text(f"""
        SELECT r.*, t.TableNumber
        FROM OFNEventDiningRegistrations r
        LEFT JOIN OFNEventDiningTables t ON t.TableID = r.TableID
        WHERE {where}
        ORDER BY r.CreatedDate DESC
    """), params).fetchall()
    regs = [dict(r._mapping) for r in rows]
    choice_map = _load_choices_for_regs(db, [r["RegID"] for r in regs])
    for r in regs:
        r["Choices"] = choice_map.get(r["RegID"], [])
    return regs


@router.post("/api/events/{event_id}/dining/registrations")
def add_registration(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    cfg_row = db.execute(text("SELECT * FROM OFNEventDiningConfig WHERE EventID=:e"),
                        {"e": event_id}).fetchone()
    if not cfg_row:
        raise HTTPException(400, "Dining event not configured")
    cfg = dict(cfg_row._mapping)
    if cfg.get("RegistrationEndDate") and cfg["RegistrationEndDate"] < date.today():
        raise HTTPException(400, "Registration has closed")
    if not body.get("GuestName"):
        raise HTTPException(400, "GuestName required")

    party_size = int(body.get("PartySize") or 1)
    child_count = int(body.get("ChildCount") or 0)
    if cfg.get("MaxSeats"):
        booked = db.execute(text("""
            SELECT COALESCE(SUM(PartySize), 0) FROM OFNEventDiningRegistrations
            WHERE EventID=:e AND Status <> 'cancelled'
        """), {"e": event_id}).fetchone()[0] or 0
        if int(booked) + party_size > int(cfg["MaxSeats"]):
            raise HTTPException(400, "Not enough seats available")

    choices = body.get("Choices") or []
    upcharge_total = 0.0
    if choices:
        ids = [int(c.get("MenuItemID")) for c in choices if c.get("MenuItemID")]
        if ids:
            placeholders = ", ".join(f":m{i}" for i in range(len(ids)))
            params_m = {f"m{i}": mid for i, mid in enumerate(ids)}
            mrows = db.execute(text(
                f"SELECT MenuItemID, UpchargeFee FROM OFNEventDiningMenuItems WHERE MenuItemID IN ({placeholders})"
            ), params_m).fetchall()
            fee_map = {int(m[0]): float(m[1] or 0) for m in mrows}
            for c in choices:
                mid = c.get("MenuItemID")
                if mid:
                    upcharge_total += fee_map.get(int(mid), 0.0)

    fee = _calc_fee(cfg, party_size, child_count, upcharge_total)

    r = db.execute(text("""
        INSERT INTO OFNEventDiningRegistrations
          (EventID, PeopleID, BusinessID, GuestName, GuestEmail, GuestPhone,
           PartySize, ChildCount, DietaryRestrictions, SpecialRequests, TotalFee)
        VALUES (:e, :p, :b, :gn, :ge, :gp, :ps, :cc, :dr, :sr, :f);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "e": event_id, "p": body.get("PeopleID"), "b": body.get("BusinessID"),
        "gn": body.get("GuestName"), "ge": body.get("GuestEmail"), "gp": body.get("GuestPhone"),
        "ps": party_size, "cc": child_count,
        "dr": body.get("DietaryRestrictions"), "sr": body.get("SpecialRequests"),
        "f": fee,
    })
    reg_id = int(r.fetchone()[0])
    for c in choices:
        if not c.get("MenuItemID"):
            continue
        db.execute(text("""
            INSERT INTO OFNEventDiningChoices (RegID, EventID, MenuItemID, GuestLabel)
            VALUES (:r, :e, :m, :g)
        """), {"r": reg_id, "e": event_id, "m": int(c["MenuItemID"]), "g": c.get("GuestLabel")})
    db.commit()

    if body.get("GuestEmail"):
        ev = db.execute(text("""
            SELECT EventID, EventName, EventStartDate, EventLocationName,
                   EventLocationStreet, EventLocationCity, EventLocationState, EventLocationZip
              FROM OFNEvents WHERE EventID = :e
        """), {"e": event_id}).mappings().first()
        extra = f'<p style="font-size:13px;color:#555"><strong>Party:</strong> {party_size} · <strong>Total:</strong> ${fee:.2f}</p>'
        try:
            send_registration_confirmation(
                to_email=body["GuestEmail"], attendee_name=body.get("GuestName") or '',
                event=dict(ev) if ev else {"EventID": event_id},
                kind="Dining", reg_id=reg_id, extra_html=extra,
            )
        except Exception as ex:
            print(f"[event_dining] email send failed: {ex}")

    return {"RegID": reg_id, "TotalFee": fee}


@router.put("/api/events/dining/registrations/{reg_id}")
def update_registration(reg_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    reg = db.execute(text("SELECT * FROM OFNEventDiningRegistrations WHERE RegID=:r"),
                    {"r": reg_id}).fetchone()
    if not reg:
        raise HTTPException(404, "Registration not found")
    reg_d = dict(reg._mapping)
    event_id = reg_d["EventID"]

    fields = {
        "GuestName": body.get("GuestName", reg_d.get("GuestName")),
        "GuestEmail": body.get("GuestEmail", reg_d.get("GuestEmail")),
        "GuestPhone": body.get("GuestPhone", reg_d.get("GuestPhone")),
        "PartySize": int(body.get("PartySize", reg_d.get("PartySize") or 1)),
        "ChildCount": int(body.get("ChildCount", reg_d.get("ChildCount") or 0)),
        "DietaryRestrictions": body.get("DietaryRestrictions", reg_d.get("DietaryRestrictions")),
        "SpecialRequests": body.get("SpecialRequests", reg_d.get("SpecialRequests")),
        "TableID": body.get("TableID", reg_d.get("TableID")),
        "SeatNumbers": body.get("SeatNumbers", reg_d.get("SeatNumbers")),
        "PaidStatus": body.get("PaidStatus", reg_d.get("PaidStatus") or "pending"),
        "Status": body.get("Status", reg_d.get("Status") or "confirmed"),
        "OrganizerNotes": body.get("OrganizerNotes", reg_d.get("OrganizerNotes")),
    }

    cfg_row = db.execute(text("SELECT * FROM OFNEventDiningConfig WHERE EventID=:e"),
                        {"e": event_id}).fetchone()
    cfg = dict(cfg_row._mapping) if cfg_row else {}

    if "Choices" in body:
        db.execute(text("DELETE FROM OFNEventDiningChoices WHERE RegID=:r"), {"r": reg_id})
        for c in (body.get("Choices") or []):
            if c.get("MenuItemID"):
                db.execute(text("""
                    INSERT INTO OFNEventDiningChoices (RegID, EventID, MenuItemID, GuestLabel)
                    VALUES (:r, :e, :m, :g)
                """), {"r": reg_id, "e": event_id, "m": int(c["MenuItemID"]), "g": c.get("GuestLabel")})

    upcharge_rows = db.execute(text("""
        SELECT COALESCE(SUM(m.UpchargeFee), 0)
        FROM OFNEventDiningChoices c
        JOIN OFNEventDiningMenuItems m ON m.MenuItemID = c.MenuItemID
        WHERE c.RegID = :r
    """), {"r": reg_id}).fetchone()
    upcharge_total = float(upcharge_rows[0] or 0) if upcharge_rows else 0.0
    fields["TotalFee"] = _calc_fee(cfg, fields["PartySize"], fields["ChildCount"], upcharge_total)

    db.execute(text("""
        UPDATE OFNEventDiningRegistrations SET
          GuestName=:gn, GuestEmail=:ge, GuestPhone=:gp,
          PartySize=:ps, ChildCount=:cc, DietaryRestrictions=:dr, SpecialRequests=:sr,
          TableID=:t, SeatNumbers=:sn, PaidStatus=:pd, Status=:st,
          OrganizerNotes=:on, TotalFee=:f, UpdatedDate=GETDATE()
        WHERE RegID=:r
    """), {
        "r": reg_id, "gn": fields["GuestName"], "ge": fields["GuestEmail"], "gp": fields["GuestPhone"],
        "ps": fields["PartySize"], "cc": fields["ChildCount"],
        "dr": fields["DietaryRestrictions"], "sr": fields["SpecialRequests"],
        "t": fields["TableID"], "sn": fields["SeatNumbers"],
        "pd": fields["PaidStatus"], "st": fields["Status"],
        "on": fields["OrganizerNotes"], "f": fields["TotalFee"],
    })
    db.commit()
    return {"ok": True, "TotalFee": fields["TotalFee"]}


@router.put("/api/events/dining/registrations/{reg_id}/seat")
def assign_seat(reg_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventDiningRegistrations SET
          TableID=:t, SeatNumbers=:sn, UpdatedDate=GETDATE()
        WHERE RegID=:r
    """), {
        "r": reg_id,
        "t": body.get("TableID"),
        "sn": body.get("SeatNumbers"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/dining/registrations/{reg_id}")
def delete_registration(reg_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventDiningChoices WHERE RegID=:r"), {"r": reg_id})
    db.execute(text("DELETE FROM OFNEventDiningRegistrations WHERE RegID=:r"), {"r": reg_id})
    db.commit()
    return {"ok": True}


# ---------- SEATING CHART ----------

@router.get("/api/events/{event_id}/dining/seating-chart")
def seating_chart(event_id: int, db: Session = Depends(get_db)):
    tables = db.execute(text("""
        SELECT TableID, TableNumber, SeatCount, TableLocation, Notes
        FROM OFNEventDiningTables WHERE EventID=:e
        ORDER BY TRY_CONVERT(INT, TableNumber), TableNumber
    """), {"e": event_id}).fetchall()
    regs = db.execute(text("""
        SELECT RegID, GuestName, PartySize, ChildCount, TableID, SeatNumbers,
               DietaryRestrictions
        FROM OFNEventDiningRegistrations
        WHERE EventID=:e AND Status <> 'cancelled'
        ORDER BY GuestName
    """), {"e": event_id}).fetchall()
    regs_by_table: dict = {}
    unassigned = []
    for r in regs:
        d = dict(r._mapping)
        if d["TableID"]:
            regs_by_table.setdefault(d["TableID"], []).append(d)
        else:
            unassigned.append(d)
    return {
        "tables": [dict(t._mapping) for t in tables],
        "byTable": regs_by_table,
        "unassigned": unassigned,
    }
