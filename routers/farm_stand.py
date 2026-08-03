from fastapi import APIRouter, Depends, Query
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

router = APIRouter(prefix="/api/farm-stand", tags=["farm_stand"])


def _ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='FarmStandProduct' AND xtype='U')
        CREATE TABLE FarmStandProduct (
            ProductID    INT IDENTITY PRIMARY KEY,
            BusinessID   INT NOT NULL,
            ProductName  NVARCHAR(150) NOT NULL,
            Category     NVARCHAR(80),
            Unit         NVARCHAR(30) DEFAULT 'each',
            DefaultPrice DECIMAL(10,2) NOT NULL DEFAULT 0,
            IsActive     BIT DEFAULT 1,
            CreatedAt    DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='FarmStandSession' AND xtype='U')
        CREATE TABLE FarmStandSession (
            SessionID        INT IDENTITY PRIMARY KEY,
            BusinessID       INT NOT NULL,
            SessionName      NVARCHAR(150) NOT NULL,
            SessionDate      DATE NOT NULL,
            LocationName     NVARCHAR(150),
            OpenTime         NVARCHAR(10),
            CloseTime        NVARCHAR(10),
            CashDrawerStart  DECIMAL(10,2) DEFAULT 0,
            CashDrawerEnd    DECIMAL(10,2),
            Status           NVARCHAR(20) DEFAULT 'Open',
            Notes            NVARCHAR(500),
            CreatedAt        DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='FarmStandSale' AND xtype='U')
        CREATE TABLE FarmStandSale (
            SaleID        INT IDENTITY PRIMARY KEY,
            BusinessID    INT NOT NULL,
            SessionID     INT NOT NULL,
            SaleTime      DATETIME DEFAULT GETDATE(),
            PaymentMethod NVARCHAR(30) DEFAULT 'Cash',
            TotalAmount   DECIMAL(10,2) DEFAULT 0,
            Notes         NVARCHAR(300),
            CreatedAt     DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='FarmStandSaleItem' AND xtype='U')
        CREATE TABLE FarmStandSaleItem (
            ItemID       INT IDENTITY PRIMARY KEY,
            SaleID       INT NOT NULL,
            BusinessID   INT NOT NULL,
            ProductName  NVARCHAR(150) NOT NULL,
            Qty          DECIMAL(10,3) NOT NULL,
            Unit         NVARCHAR(30) DEFAULT 'each',
            PricePerUnit DECIMAL(10,2) NOT NULL,
            LineTotal    DECIMAL(10,2) NOT NULL,
            CreatedAt    DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


# ── Products ──────────────────────────────────────────────────────────────────

@router.get("/products")
def list_products(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT ProductID, ProductName, Category, Unit, DefaultPrice, IsActive
        FROM FarmStandProduct WHERE BusinessID=:bid AND IsActive=1
        ORDER BY Category, ProductName
    """), {"bid": business_id}).fetchall()
    return [dict(zip(["product_id","product_name","category","unit","default_price","is_active"], r)) for r in rows]


@router.post("/products")
def create_product(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO FarmStandProduct (BusinessID, ProductName, Category, Unit, DefaultPrice)
        OUTPUT INSERTED.ProductID
        VALUES (:bid,:name,:cat,:unit,:price)
    """), {
        "bid": business_id, "name": body.get("product_name",""),
        "cat": body.get("category"), "unit": body.get("unit","each"),
        "price": body.get("default_price", 0),
    }).fetchone()
    db.commit()
    return {"product_id": row[0]}


@router.put("/products/{product_id}")
def update_product(product_id: int, business_id: int = Query(...),
                   db: Session = Depends(get_db), body: dict = None):
    body = body or {}
    db.execute(text("""
        UPDATE FarmStandProduct SET ProductName=:name, Category=:cat, Unit=:unit,
            DefaultPrice=:price, IsActive=:active
        WHERE ProductID=:pid AND BusinessID=:bid
    """), {
        "pid": product_id, "bid": business_id, "name": body.get("product_name",""),
        "cat": body.get("category"), "unit": body.get("unit","each"),
        "price": body.get("default_price", 0),
        "active": 1 if body.get("is_active", True) else 0,
    })
    db.commit()
    return {"ok": True}


@router.delete("/products/{product_id}")
def delete_product(product_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("UPDATE FarmStandProduct SET IsActive=0 WHERE ProductID=:pid AND BusinessID=:bid"),
               {"pid": product_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Sessions ──────────────────────────────────────────────────────────────────

@router.get("/sessions")
def list_sessions(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT s.SessionID, s.SessionName, s.SessionDate, s.LocationName,
               s.OpenTime, s.CloseTime, s.CashDrawerStart, s.CashDrawerEnd,
               s.Status, s.Notes,
               (SELECT COUNT(*) FROM FarmStandSale WHERE SessionID=s.SessionID) AS sale_count,
               (SELECT ISNULL(SUM(TotalAmount),0) FROM FarmStandSale WHERE SessionID=s.SessionID) AS total_revenue
        FROM FarmStandSession s
        WHERE s.BusinessID=:bid
        ORDER BY s.SessionDate DESC
    """), {"bid": business_id}).fetchall()
    return [dict(zip(
        ["session_id","session_name","session_date","location_name","open_time","close_time",
         "cash_drawer_start","cash_drawer_end","status","notes","sale_count","total_revenue"], r
    )) for r in rows]


@router.post("/sessions")
def create_session(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO FarmStandSession
            (BusinessID, SessionName, SessionDate, LocationName, OpenTime, CloseTime,
             CashDrawerStart, Status, Notes)
        OUTPUT INSERTED.SessionID
        VALUES (:bid,:name,:dt,:loc,:open,:close,:drawer,:status,:notes)
    """), {
        "bid": business_id, "name": body.get("session_name",""),
        "dt": body.get("session_date"), "loc": body.get("location_name"),
        "open": body.get("open_time"), "close": body.get("close_time"),
        "drawer": body.get("cash_drawer_start", 0),
        "status": body.get("status","Open"), "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"session_id": row[0]}


@router.patch("/sessions/{session_id}/close")
def close_session(session_id: int, business_id: int = Query(...),
                  db: Session = Depends(get_db), body: dict = None):
    body = body or {}
    db.execute(text("""
        UPDATE FarmStandSession SET Status='Closed', CloseTime=:ct, CashDrawerEnd=:end
        WHERE SessionID=:sid AND BusinessID=:bid
    """), {
        "sid": session_id, "bid": business_id,
        "ct": body.get("close_time"), "end": body.get("cash_drawer_end"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM FarmStandSaleItem WHERE BusinessID=:bid AND SaleID IN (SELECT SaleID FROM FarmStandSale WHERE SessionID=:sid)"),
               {"bid": business_id, "sid": session_id})
    db.execute(text("DELETE FROM FarmStandSale WHERE SessionID=:sid AND BusinessID=:bid"),
               {"sid": session_id, "bid": business_id})
    db.execute(text("DELETE FROM FarmStandSession WHERE SessionID=:sid AND BusinessID=:bid"),
               {"sid": session_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Sales ─────────────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/sales")
def list_sales(session_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT SaleID, SaleTime, PaymentMethod, TotalAmount, Notes
        FROM FarmStandSale WHERE SessionID=:sid AND BusinessID=:bid
        ORDER BY SaleTime DESC
    """), {"sid": session_id, "bid": business_id}).fetchall()
    return [dict(zip(["sale_id","sale_time","payment_method","total_amount","notes"], r))
            for r in rows]


@router.post("/sessions/{session_id}/sales")
def create_sale(session_id: int, business_id: int = Query(...),
                db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    items = body.get("items", [])
    total = sum(float(i.get("qty", 0)) * float(i.get("price_per_unit", 0)) for i in items)
    sale_row = db.execute(text("""
        INSERT INTO FarmStandSale (BusinessID, SessionID, PaymentMethod, TotalAmount, Notes)
        OUTPUT INSERTED.SaleID
        VALUES (:bid,:sid,:pm,:total,:notes)
    """), {
        "bid": business_id, "sid": session_id,
        "pm": body.get("payment_method","Cash"),
        "total": total, "notes": body.get("notes"),
    }).fetchone()
    sale_id = sale_row[0]
    for item in items:
        qty = float(item.get("qty", 0))
        price = float(item.get("price_per_unit", 0))
        db.execute(text("""
            INSERT INTO FarmStandSaleItem
                (SaleID, BusinessID, ProductName, Qty, Unit, PricePerUnit, LineTotal)
            VALUES (:sid,:bid,:name,:qty,:unit,:price,:total)
        """), {
            "sid": sale_id, "bid": business_id,
            "name": item.get("product_name",""), "qty": qty,
            "unit": item.get("unit","each"), "price": price,
            "total": round(qty * price, 2),
        })
    db.commit()
    return {"sale_id": sale_id, "total": total}


@router.get("/sales/{sale_id}/items")
def get_sale_items(sale_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT ItemID, ProductName, Qty, Unit, PricePerUnit, LineTotal
        FROM FarmStandSaleItem WHERE SaleID=:sid AND BusinessID=:bid
    """), {"sid": sale_id, "bid": business_id}).fetchall()
    return [dict(zip(["item_id","product_name","qty","unit","price_per_unit","line_total"], r))
            for r in rows]


@router.delete("/sales/{sale_id}")
def void_sale(sale_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM FarmStandSaleItem WHERE SaleID=:sid AND BusinessID=:bid"),
               {"sid": sale_id, "bid": business_id})
    db.execute(text("DELETE FROM FarmStandSale WHERE SaleID=:sid AND BusinessID=:bid"),
               {"sid": sale_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary")
def get_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    r = db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM FarmStandSession WHERE BusinessID=:bid AND Status='Open') AS open_sessions,
            (SELECT COUNT(*) FROM FarmStandSession WHERE BusinessID=:bid
             AND SessionDate >= DATEADD(day,-30,GETDATE())) AS sessions_30d,
            (SELECT ISNULL(SUM(TotalAmount),0) FROM FarmStandSale WHERE BusinessID=:bid
             AND SaleTime >= DATEADD(day,-30,GETDATE())) AS revenue_30d,
            (SELECT COUNT(*) FROM FarmStandProduct WHERE BusinessID=:bid AND IsActive=1) AS active_products
    """), {"bid": business_id}).fetchone()
    return dict(zip(["open_sessions","sessions_30d","revenue_30d","active_products"], r))
