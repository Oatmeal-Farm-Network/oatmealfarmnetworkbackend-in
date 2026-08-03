from fastapi import APIRouter, Depends, Query
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

router = APIRouter(prefix="/api/delivery", tags=["delivery_routes"])

STOP_STATUSES = ['Pending','In Transit','Delivered','Attempted','Skipped']


def _ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='DeliveryRoute' AND xtype='U')
        CREATE TABLE DeliveryRoute (
            RouteID      INT IDENTITY PRIMARY KEY,
            BusinessID   INT NOT NULL,
            RouteName    NVARCHAR(150) NOT NULL,
            RouteDate    DATE NOT NULL,
            DriverName   NVARCHAR(150),
            VehicleInfo  NVARCHAR(150),
            Status       NVARCHAR(30) DEFAULT 'Planned',
            Notes        NVARCHAR(500),
            CreatedAt    DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='DeliveryStop' AND xtype='U')
        CREATE TABLE DeliveryStop (
            StopID           INT IDENTITY PRIMARY KEY,
            RouteID          INT NOT NULL,
            BusinessID       INT NOT NULL,
            ContactName      NVARCHAR(150) NOT NULL,
            Address          NVARCHAR(300),
            StopOrder        INT NOT NULL DEFAULT 1,
            ExpectedTime     NVARCHAR(10),
            ActualTime       NVARCHAR(10),
            Status           NVARCHAR(30) DEFAULT 'Pending',
            Notes            NVARCHAR(500),
            ProofOfDelivery  NVARCHAR(500),
            CreatedAt        DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='DeliveryItem' AND xtype='U')
        CREATE TABLE DeliveryItem (
            ItemID      INT IDENTITY PRIMARY KEY,
            StopID      INT NOT NULL,
            BusinessID  INT NOT NULL,
            ProductName NVARCHAR(150) NOT NULL,
            Qty         DECIMAL(10,2) NOT NULL,
            Unit        NVARCHAR(30) DEFAULT 'kg',
            Notes       NVARCHAR(300),
            CreatedAt   DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/routes")
def list_routes(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT r.RouteID, r.RouteName, r.RouteDate, r.DriverName, r.VehicleInfo,
               r.Status, r.Notes, r.CreatedAt,
               (SELECT COUNT(*) FROM DeliveryStop WHERE RouteID=r.RouteID) AS stop_count,
               (SELECT COUNT(*) FROM DeliveryStop WHERE RouteID=r.RouteID AND Status='Delivered') AS delivered_count
        FROM DeliveryRoute r
        WHERE r.BusinessID=:bid
        ORDER BY r.RouteDate DESC
    """), {"bid": business_id}).fetchall()
    return [dict(zip(
        ["route_id","route_name","route_date","driver_name","vehicle_info",
         "status","notes","created_at","stop_count","delivered_count"], r
    )) for r in rows]


@router.post("/routes")
def create_route(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO DeliveryRoute (BusinessID, RouteName, RouteDate, DriverName, VehicleInfo, Status, Notes)
        OUTPUT INSERTED.RouteID
        VALUES (:bid,:name,:dt,:driver,:vehicle,:status,:notes)
    """), {
        "bid": business_id, "name": body.get("route_name",""),
        "dt": body.get("route_date"), "driver": body.get("driver_name"),
        "vehicle": body.get("vehicle_info"), "status": body.get("status","Planned"),
        "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"route_id": row[0]}


@router.put("/routes/{route_id}")
def update_route(route_id: int, business_id: int = Query(...),
                 db: Session = Depends(get_db), body: dict = None):
    body = body or {}
    db.execute(text("""
        UPDATE DeliveryRoute SET RouteName=:name, RouteDate=:dt, DriverName=:driver,
            VehicleInfo=:vehicle, Status=:status, Notes=:notes
        WHERE RouteID=:rid AND BusinessID=:bid
    """), {
        "rid": route_id, "bid": business_id, "name": body.get("route_name",""),
        "dt": body.get("route_date"), "driver": body.get("driver_name"),
        "vehicle": body.get("vehicle_info"), "status": body.get("status","Planned"),
        "notes": body.get("notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/routes/{route_id}")
def delete_route(route_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    stops = db.execute(text("SELECT StopID FROM DeliveryStop WHERE RouteID=:rid AND BusinessID=:bid"),
                       {"rid": route_id, "bid": business_id}).fetchall()
    for s in stops:
        db.execute(text("DELETE FROM DeliveryItem WHERE StopID=:sid AND BusinessID=:bid"),
                   {"sid": s[0], "bid": business_id})
    db.execute(text("DELETE FROM DeliveryStop WHERE RouteID=:rid AND BusinessID=:bid"),
               {"rid": route_id, "bid": business_id})
    db.execute(text("DELETE FROM DeliveryRoute WHERE RouteID=:rid AND BusinessID=:bid"),
               {"rid": route_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Stops ─────────────────────────────────────────────────────────────────────

@router.get("/routes/{route_id}/stops")
def list_stops(route_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT StopID, ContactName, Address, StopOrder, ExpectedTime, ActualTime,
               Status, Notes, ProofOfDelivery
        FROM DeliveryStop WHERE RouteID=:rid AND BusinessID=:bid
        ORDER BY StopOrder
    """), {"rid": route_id, "bid": business_id}).fetchall()
    return [dict(zip(
        ["stop_id","contact_name","address","stop_order","expected_time",
         "actual_time","status","notes","proof_of_delivery"], r
    )) for r in rows]


@router.post("/stops")
def create_stop(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    # Auto-assign stop order if not provided
    if not body.get("stop_order"):
        count_row = db.execute(text(
            "SELECT COUNT(*) FROM DeliveryStop WHERE RouteID=:rid AND BusinessID=:bid"
        ), {"rid": body.get("route_id"), "bid": business_id}).fetchone()
        body["stop_order"] = (count_row[0] if count_row else 0) + 1
    row = db.execute(text("""
        INSERT INTO DeliveryStop
            (RouteID, BusinessID, ContactName, Address, StopOrder, ExpectedTime, Notes)
        OUTPUT INSERTED.StopID
        VALUES (:rid,:bid,:contact,:addr,:order,:time,:notes)
    """), {
        "rid": body.get("route_id"), "bid": business_id,
        "contact": body.get("contact_name",""), "addr": body.get("address"),
        "order": body.get("stop_order", 1), "time": body.get("expected_time"),
        "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"stop_id": row[0]}


@router.patch("/stops/{stop_id}/status")
def update_stop_status(stop_id: int, business_id: int = Query(...),
                       db: Session = Depends(get_db), body: dict = None):
    body = body or {}
    db.execute(text("""
        UPDATE DeliveryStop SET Status=:status, ActualTime=:actual, ProofOfDelivery=:pod
        WHERE StopID=:sid AND BusinessID=:bid
    """), {
        "sid": stop_id, "bid": business_id,
        "status": body.get("status","Delivered"),
        "actual": body.get("actual_time"), "pod": body.get("proof_of_delivery"),
    })
    db.commit()
    return {"ok": True}


@router.put("/stops/{stop_id}")
def update_stop(stop_id: int, business_id: int = Query(...),
                db: Session = Depends(get_db), body: dict = None):
    body = body or {}
    db.execute(text("""
        UPDATE DeliveryStop SET ContactName=:contact, Address=:addr, StopOrder=:order,
            ExpectedTime=:time, Notes=:notes
        WHERE StopID=:sid AND BusinessID=:bid
    """), {
        "sid": stop_id, "bid": business_id,
        "contact": body.get("contact_name",""), "addr": body.get("address"),
        "order": body.get("stop_order", 1), "time": body.get("expected_time"),
        "notes": body.get("notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/stops/{stop_id}")
def delete_stop(stop_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM DeliveryItem WHERE StopID=:sid AND BusinessID=:bid"),
               {"sid": stop_id, "bid": business_id})
    db.execute(text("DELETE FROM DeliveryStop WHERE StopID=:sid AND BusinessID=:bid"),
               {"sid": stop_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Stop Items ────────────────────────────────────────────────────────────────

@router.get("/stops/{stop_id}/items")
def list_stop_items(stop_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT ItemID, ProductName, Qty, Unit, Notes
        FROM DeliveryItem WHERE StopID=:sid AND BusinessID=:bid ORDER BY ProductName
    """), {"sid": stop_id, "bid": business_id}).fetchall()
    return [dict(zip(["item_id","product_name","qty","unit","notes"], r)) for r in rows]


@router.post("/stop-items")
def add_stop_item(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO DeliveryItem (StopID, BusinessID, ProductName, Qty, Unit, Notes)
        OUTPUT INSERTED.ItemID
        VALUES (:sid,:bid,:name,:qty,:unit,:notes)
    """), {
        "sid": body.get("stop_id"), "bid": business_id,
        "name": body.get("product_name",""), "qty": body.get("qty", 0),
        "unit": body.get("unit","kg"), "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"item_id": row[0]}


@router.delete("/stop-items/{item_id}")
def delete_stop_item(item_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM DeliveryItem WHERE ItemID=:iid AND BusinessID=:bid"),
               {"iid": item_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary")
def get_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    r = db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM DeliveryRoute WHERE BusinessID=:bid AND Status='In Progress') AS active_routes,
            (SELECT COUNT(*) FROM DeliveryRoute WHERE BusinessID=:bid
             AND RouteDate BETWEEN GETDATE() AND DATEADD(day,7,GETDATE())) AS upcoming_routes,
            (SELECT COUNT(*) FROM DeliveryStop ds
             JOIN DeliveryRoute dr ON dr.RouteID=ds.RouteID
             WHERE ds.BusinessID=:bid AND ds.Status='Pending'
               AND dr.RouteDate=CAST(GETDATE() AS DATE)) AS stops_today,
            (SELECT COUNT(*) FROM DeliveryStop ds
             JOIN DeliveryRoute dr ON dr.RouteID=ds.RouteID
             WHERE ds.BusinessID=:bid AND ds.Status='Delivered'
               AND dr.RouteDate >= DATEADD(day,-7,GETDATE())) AS delivered_7d
    """), {"bid": business_id}).fetchone()
    return dict(zip(["active_routes","upcoming_routes","stops_today","delivered_7d"], r))
