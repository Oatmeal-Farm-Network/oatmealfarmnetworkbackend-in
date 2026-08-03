"""
Event meal tickets (add-on meal sessions for non-dining events like shows).

An event can define any number of meal sessions (e.g., "Saturday lunch",
"Sunday banquet") with a price and optional max capacity. Attendees purchase
tickets per session during the registration wizard, with optional diet
preference text (vegetarian, gluten-free, etc.).

Distinct from OFNEventDiningConfig which is for sit-down dining *events*.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventMealSessions')
        CREATE TABLE OFNEventMealSessions (
            SessionID    INT IDENTITY(1,1) PRIMARY KEY,
            EventID      INT NOT NULL,
            SessionName  NVARCHAR(200) NOT NULL,
            SessionDate  DATE,
            SessionTime  NVARCHAR(50),
            Price        DECIMAL(10,2) DEFAULT 0,
            MaxTickets   INT,
            Description  NVARCHAR(MAX),
            DisplayOrder INT DEFAULT 0,
            IsActive     BIT DEFAULT 1,
            CreatedDate  DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventMealTickets')
        CREATE TABLE OFNEventMealTickets (
            TicketID       INT IDENTITY(1,1) PRIMARY KEY,
            EventID        INT NOT NULL,
            SessionID      INT NOT NULL,
            CartID         INT,
            PeopleID       INT,
            BusinessID     INT,
            AttendeeName   NVARCHAR(200),
            DietaryNotes   NVARCHAR(500),
            Quantity       INT DEFAULT 1,
            UnitPrice      DECIMAL(10,2) DEFAULT 0,
            LineAmount     DECIMAL(10,2) DEFAULT 0,
            PaidStatus     NVARCHAR(50) DEFAULT 'pending',
            CreatedDate    DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


with SessionLocal() as _db:
    try:
        ensure_tables(_db)
    except Exception as e:
        print(f"Meal tickets setup error: {e}")


# ─── Meal session CRUD (admin) ────────────────────────────────────

@router.get("/api/events/{event_id}/meals/sessions")
def list_sessions(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT s.*,
               (SELECT ISNULL(SUM(Quantity),0) FROM OFNEventMealTickets t
                 WHERE t.SessionID = s.SessionID AND t.PaidStatus <> 'refunded') AS SoldCount
        FROM OFNEventMealSessions s
        WHERE s.EventID = :eid AND s.IsActive = 1
        ORDER BY s.SessionDate, s.DisplayOrder, s.SessionName
    """), {"eid": event_id}).mappings().all()
    return [dict(r) for r in rows]


@router.post("/api/events/{event_id}/meals/sessions")
def add_session(event_id: int, data: dict, db: Session = Depends(get_db)):
    if not data.get("SessionName"):
        raise HTTPException(400, "SessionName required")
    res = db.execute(text("""
        INSERT INTO OFNEventMealSessions
            (EventID, SessionName, SessionDate, SessionTime, Price, MaxTickets, Description, DisplayOrder)
        OUTPUT INSERTED.SessionID AS id
        VALUES (:eid, :name, :date, :time, :price, :max, :desc, :ord)
    """), {
        "eid": event_id,
        "name": data["SessionName"],
        "date": data.get("SessionDate") or None,
        "time": data.get("SessionTime") or None,
        "price": float(data.get("Price") or 0),
        "max": data.get("MaxTickets") or None,
        "desc": data.get("Description") or None,
        "ord": int(data.get("DisplayOrder") or 0),
    }).mappings().first()
    db.commit()
    return {"SessionID": int(res["id"])}


@router.put("/api/events/meals/sessions/{session_id}")
def update_session(session_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventMealSessions SET
            SessionName  = :name,
            SessionDate  = :date,
            SessionTime  = :time,
            Price        = :price,
            MaxTickets   = :max,
            Description  = :desc,
            DisplayOrder = :ord
        WHERE SessionID = :id
    """), {
        "id": session_id,
        "name": data.get("SessionName"),
        "date": data.get("SessionDate") or None,
        "time": data.get("SessionTime") or None,
        "price": float(data.get("Price") or 0),
        "max": data.get("MaxTickets") or None,
        "desc": data.get("Description") or None,
        "ord": int(data.get("DisplayOrder") or 0),
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/meals/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE OFNEventMealSessions SET IsActive = 0 WHERE SessionID = :id"),
               {"id": session_id})
    db.commit()
    return {"ok": True}


DEFAULT_SESSION_PRESETS = [
    {"SessionName": "Saturday Lunch",    "SessionTime": "12:00 PM", "Price": 20.00, "DisplayOrder": 1},
    {"SessionName": "Saturday Banquet",  "SessionTime": "6:30 PM",  "Price": 45.00, "DisplayOrder": 2},
    {"SessionName": "Sunday Brunch",     "SessionTime": "9:00 AM",  "Price": 18.00, "DisplayOrder": 3},
]


@router.post("/api/events/{event_id}/meals/sessions/seed-defaults")
def seed_defaults(event_id: int, db: Session = Depends(get_db)):
    """Insert a standard lunch / banquet / brunch set for quick setup.
    Skips any preset whose name already exists for this event (idempotent)."""
    existing = {
        r["SessionName"] for r in db.execute(
            text("SELECT SessionName FROM OFNEventMealSessions WHERE EventID = :eid AND IsActive = 1"),
            {"eid": event_id}
        ).mappings().all()
    }
    added = 0
    for p in DEFAULT_SESSION_PRESETS:
        if p["SessionName"] in existing:
            continue
        db.execute(text("""
            INSERT INTO OFNEventMealSessions
                (EventID, SessionName, SessionTime, Price, DisplayOrder)
            VALUES (:eid, :name, :time, :price, :ord)
        """), {
            "eid": event_id,
            "name": p["SessionName"],
            "time": p["SessionTime"],
            "price": p["Price"],
            "ord":   p["DisplayOrder"],
        })
        added += 1
    db.commit()
    return {"added": added}


@router.post("/api/events/{event_id}/meals/sessions/copy-from/{source_event_id}")
def copy_sessions(event_id: int, source_event_id: int, db: Session = Depends(get_db)):
    """Copy all active meal sessions from a source event to this event.
    Dates are dropped (caller re-dates), prices/names/descriptions/order carry over."""
    if event_id == source_event_id:
        raise HTTPException(400, "Source and target event are the same")
    src = db.execute(text("""
        SELECT SessionName, SessionTime, Price, MaxTickets, Description, DisplayOrder
          FROM OFNEventMealSessions
         WHERE EventID = :sid AND IsActive = 1
         ORDER BY DisplayOrder, SessionID
    """), {"sid": source_event_id}).mappings().all()
    if not src:
        return {"copied": 0}
    for s in src:
        db.execute(text("""
            INSERT INTO OFNEventMealSessions
                (EventID, SessionName, SessionDate, SessionTime, Price, MaxTickets, Description, DisplayOrder)
            VALUES (:eid, :name, NULL, :time, :price, :max, :desc, :ord)
        """), {
            "eid": event_id,
            "name": s["SessionName"],
            "time": s["SessionTime"],
            "price": s["Price"],
            "max":   s["MaxTickets"],
            "desc":  s["Description"],
            "ord":   s["DisplayOrder"] or 0,
        })
    db.commit()
    return {"copied": len(src)}


# ─── Meal tickets (attendee-side) ────────────────────────────────

@router.post("/api/events/{event_id}/meals/tickets")
def add_ticket(event_id: int, data: dict, db: Session = Depends(get_db)):
    sess = db.execute(text("""
        SELECT SessionID, Price, MaxTickets,
               (SELECT ISNULL(SUM(Quantity),0) FROM OFNEventMealTickets t
                 WHERE t.SessionID = :sid AND t.PaidStatus <> 'refunded') AS Sold
        FROM OFNEventMealSessions WHERE SessionID = :sid AND IsActive = 1
    """), {"sid": int(data.get("SessionID"))}).mappings().first()
    if not sess:
        raise HTTPException(404, "Meal session not found")
    qty = int(data.get("Quantity") or 1)
    if sess["MaxTickets"] and (sess["Sold"] or 0) + qty > sess["MaxTickets"]:
        raise HTTPException(400, "Sold out")
    unit = float(sess["Price"] or 0)
    line = qty * unit
    res = db.execute(text("""
        INSERT INTO OFNEventMealTickets
            (EventID, SessionID, CartID, PeopleID, BusinessID,
             AttendeeName, DietaryNotes, Quantity, UnitPrice, LineAmount, PaidStatus)
        OUTPUT INSERTED.TicketID AS id
        VALUES (:eid, :sid, :cid, :pid, :bid, :nm, :diet, :q, :u, :ln, 'pending')
    """), {
        "eid": event_id,
        "sid": sess["SessionID"],
        "cid": data.get("CartID"),
        "pid": data.get("PeopleID"),
        "bid": data.get("BusinessID"),
        "nm":  data.get("AttendeeName"),
        "diet": data.get("DietaryNotes"),
        "q":   qty, "u": unit, "ln": line,
    }).mappings().first()
    db.commit()
    return {"TicketID": int(res["id"]), "LineAmount": line}


@router.get("/api/events/{event_id}/meals/tickets")
def list_tickets(event_id: int, cart_id: int | None = None, people_id: int | None = None,
                 db: Session = Depends(get_db)):
    """Admin: all tickets for event. Customer: filter by cart_id or people_id."""
    params = {"eid": event_id}
    where = ["t.EventID = :eid"]
    if cart_id:
        where.append("t.CartID = :cid")
        params["cid"] = cart_id
    if people_id:
        where.append("t.PeopleID = :pid")
        params["pid"] = people_id
    sql = f"""
        SELECT t.*, s.SessionName, s.SessionDate, s.SessionTime
          FROM OFNEventMealTickets t
          LEFT JOIN OFNEventMealSessions s ON t.SessionID = s.SessionID
         WHERE {' AND '.join(where)}
         ORDER BY s.SessionDate, t.TicketID
    """
    rows = db.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


@router.delete("/api/events/meals/tickets/{ticket_id}")
def delete_ticket(ticket_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventMealTickets WHERE TicketID = :id AND PaidStatus = 'pending'"),
               {"id": ticket_id})
    db.commit()
    return {"ok": True}
