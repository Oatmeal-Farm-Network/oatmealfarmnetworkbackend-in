"""
Booth services à la carte (electrical / water / internet / table / AV / drayage).

Organizers maintain a per-event service catalog. Each vendor application can
order N copies of any service line. Total adds to the application's invoice.

Schema
  OFNEventBoothService       : per-event catalog (Name, Description, Price, Unit, Category)
  OFNEventBoothServiceOrder  : line item linking AppID → ServiceID with Quantity
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List
from database import get_db, SessionLocal

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OFNEventBoothService')
        CREATE TABLE OFNEventBoothService (
            ServiceID    INT IDENTITY(1,1) PRIMARY KEY,
            EventID      INT NOT NULL,
            Name         NVARCHAR(200) NOT NULL,
            Description  NVARCHAR(MAX),
            Category     NVARCHAR(50) DEFAULT 'general',  -- electrical / water / internet / furniture / av / shipping / general
            Price        DECIMAL(10,2) DEFAULT 0,
            Unit         NVARCHAR(40) DEFAULT 'each',     -- each / day / kWh / linear ft / etc.
            MaxPerBooth  INT NULL,                        -- nullable = unlimited
            IsRequired   BIT DEFAULT 0,                   -- vendor MUST order at least 1
            IsActive     BIT DEFAULT 1,
            SortOrder    INT DEFAULT 100,
            CreatedDate  DATETIME DEFAULT GETDATE(),
            UpdatedDate  DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OFNEventBoothServiceOrder')
        CREATE TABLE OFNEventBoothServiceOrder (
            OrderID      INT IDENTITY(1,1) PRIMARY KEY,
            AppID        INT NOT NULL,                    -- → OFNEventVendorApplications.AppID
            ServiceID    INT NOT NULL,
            Quantity     INT DEFAULT 1,
            UnitPrice    DECIMAL(10,2),                   -- snapshot at order time
            Notes        NVARCHAR(500),
            Status       NVARCHAR(40) DEFAULT 'ordered',  -- ordered / fulfilled / cancelled
            CreatedDate  DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sys.indexes
                        WHERE name='IX_OFNEventBoothServiceOrder_App'
                          AND object_id = OBJECT_ID('OFNEventBoothServiceOrder'))
        CREATE INDEX IX_OFNEventBoothServiceOrder_App
                  ON OFNEventBoothServiceOrder (AppID)
    """))
    db.commit()


try:
    with SessionLocal() as _db:
        ensure_tables(_db)
except Exception as e:
    print(f"[event_booth_services] Table ensure warning: {e}")


# ── Service catalog ─────────────────────────────────────────────────────────

@router.get("/api/events/{event_id}/booth-services")
def list_services(event_id: int, active_only: bool = True, db: Session = Depends(get_db)):
    where = "WHERE EventID = :eid"
    if active_only:
        where += " AND IsActive = 1"
    rows = db.execute(text(f"""
        SELECT ServiceID, EventID, Name, Description, Category, Price, Unit,
               MaxPerBooth, IsRequired, IsActive, SortOrder
          FROM OFNEventBoothService
          {where}
         ORDER BY SortOrder, Category, Name
    """), {"eid": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/booth-services")
def create_service(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    if not body.get("Name"):
        raise HTTPException(400, "Name is required")
    res = db.execute(text("""
        INSERT INTO OFNEventBoothService
            (EventID, Name, Description, Category, Price, Unit,
             MaxPerBooth, IsRequired, IsActive, SortOrder)
        OUTPUT INSERTED.ServiceID
        VALUES (:eid, :n, :d, :cat, :p, :u, :mx, :req, :act, :so)
    """), {
        "eid": event_id,
        "n":   body["Name"],
        "d":   body.get("Description"),
        "cat": body.get("Category", "general"),
        "p":   body.get("Price", 0),
        "u":   body.get("Unit", "each"),
        "mx":  body.get("MaxPerBooth"),
        "req": 1 if body.get("IsRequired") else 0,
        "act": 1 if body.get("IsActive", True) else 0,
        "so":  body.get("SortOrder", 100),
    }).fetchone()
    db.commit()
    return {"ServiceID": int(res.ServiceID)}


@router.put("/api/events/booth-services/{service_id}")
def update_service(service_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventBoothService SET
            Name=:n, Description=:d, Category=:cat, Price=:p, Unit=:u,
            MaxPerBooth=:mx, IsRequired=:req, IsActive=:act, SortOrder=:so,
            UpdatedDate=GETDATE()
        WHERE ServiceID=:sid
    """), {
        "sid": service_id,
        "n":   body.get("Name"),
        "d":   body.get("Description"),
        "cat": body.get("Category", "general"),
        "p":   body.get("Price", 0),
        "u":   body.get("Unit", "each"),
        "mx":  body.get("MaxPerBooth"),
        "req": 1 if body.get("IsRequired") else 0,
        "act": 1 if body.get("IsActive", True) else 0,
        "so":  body.get("SortOrder", 100),
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/booth-services/{service_id}")
def delete_service(service_id: int, db: Session = Depends(get_db)):
    in_use = db.execute(text(
        "SELECT COUNT(1) AS n FROM OFNEventBoothServiceOrder WHERE ServiceID = :sid"
    ), {"sid": service_id}).fetchone()
    if in_use and int(in_use.n) > 0:
        # Don't hard-delete if there are orders — just deactivate
        db.execute(text("UPDATE OFNEventBoothService SET IsActive=0 WHERE ServiceID=:sid"), {"sid": service_id})
        db.commit()
        return {"ok": True, "soft_deleted": True,
                "message": f"Deactivated — {in_use.n} order(s) reference this service."}
    db.execute(text("DELETE FROM OFNEventBoothService WHERE ServiceID = :sid"), {"sid": service_id})
    db.commit()
    return {"ok": True, "soft_deleted": False}


# ── Per-application orders ──────────────────────────────────────────────────

@router.get("/api/events/applications/{app_id}/booth-services")
def list_orders(app_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT o.OrderID, o.AppID, o.ServiceID, o.Quantity, o.UnitPrice,
               o.Notes, o.Status, o.CreatedDate,
               s.Name, s.Category, s.Unit
          FROM OFNEventBoothServiceOrder o
          JOIN OFNEventBoothService s ON s.ServiceID = o.ServiceID
         WHERE o.AppID = :aid
         ORDER BY s.Category, s.Name
    """), {"aid": app_id}).fetchall()
    items = [dict(r._mapping) for r in rows]
    total = sum((float(r["UnitPrice"] or 0) * int(r["Quantity"] or 0)) for r in items)
    return {"app_id": app_id, "orders": items, "total": round(total, 2)}


@router.post("/api/events/applications/{app_id}/booth-services")
def add_order(app_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    sid = body.get("ServiceID")
    if not sid:
        raise HTTPException(400, "ServiceID is required")
    qty = max(1, int(body.get("Quantity", 1)))

    svc = db.execute(text(
        "SELECT Price, MaxPerBooth, Name FROM OFNEventBoothService WHERE ServiceID=:sid AND IsActive=1"
    ), {"sid": sid}).fetchone()
    if not svc:
        raise HTTPException(404, "Service not found or inactive.")
    if svc.MaxPerBooth and qty > int(svc.MaxPerBooth):
        raise HTTPException(409, f"{svc.Name} caps at {svc.MaxPerBooth} per booth.")

    unit_price = float(body.get("UnitPrice") if body.get("UnitPrice") is not None else (svc.Price or 0))
    res = db.execute(text("""
        INSERT INTO OFNEventBoothServiceOrder (AppID, ServiceID, Quantity, UnitPrice, Notes, Status)
        OUTPUT INSERTED.OrderID
        VALUES (:aid, :sid, :q, :up, :n, :st)
    """), {
        "aid": app_id, "sid": int(sid), "q": qty,
        "up":  unit_price,
        "n":   body.get("Notes"),
        "st":  body.get("Status", "ordered"),
    }).fetchone()
    db.commit()
    return {"OrderID": int(res.OrderID), "line_total": round(unit_price * qty, 2)}


@router.put("/api/events/booth-service-orders/{order_id}")
def update_order(order_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventBoothServiceOrder SET
            Quantity=:q, UnitPrice=:up, Notes=:n, Status=:st
        WHERE OrderID=:oid
    """), {
        "oid": order_id,
        "q":   max(0, int(body.get("Quantity", 1))),
        "up":  body.get("UnitPrice"),
        "n":   body.get("Notes"),
        "st":  body.get("Status", "ordered"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/booth-service-orders/{order_id}")
def delete_order(order_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventBoothServiceOrder WHERE OrderID=:oid"), {"oid": order_id})
    db.commit()
    return {"ok": True}


@router.get("/api/events/{event_id}/booth-services/revenue")
def services_revenue(event_id: int, db: Session = Depends(get_db)):
    """Organizer dashboard: total revenue from services across all applications,
    plus per-service revenue + units sold."""
    rows = db.execute(text("""
        SELECT s.ServiceID, s.Name, s.Category, s.Unit,
               COUNT(o.OrderID) AS line_count,
               SUM(o.Quantity)  AS units_sold,
               SUM(ISNULL(o.UnitPrice, 0) * ISNULL(o.Quantity, 0)) AS revenue
          FROM OFNEventBoothService s
          LEFT JOIN OFNEventBoothServiceOrder o ON o.ServiceID = s.ServiceID
         WHERE s.EventID = :eid
         GROUP BY s.ServiceID, s.Name, s.Category, s.Unit, s.SortOrder
         ORDER BY s.SortOrder, s.Category, s.Name
    """), {"eid": event_id}).fetchall()
    items = [dict(r._mapping) for r in rows]
    total = sum(float(r.get("revenue") or 0) for r in items)
    return {"event_id": event_id, "total_revenue": round(total, 2), "by_service": items}
