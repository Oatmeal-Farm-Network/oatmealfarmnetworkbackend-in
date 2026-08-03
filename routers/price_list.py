from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

router = APIRouter(prefix="/api/price-list", tags=["price_list"])


def _ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='PriceList' AND xtype='U')
        CREATE TABLE PriceList (
            PriceListID  INT IDENTITY PRIMARY KEY,
            BusinessID   INT NOT NULL,
            ListName     NVARCHAR(200) NOT NULL,
            BuyerTier    NVARCHAR(50) DEFAULT 'Wholesale',
            ValidFrom    DATE,
            ValidTo      DATE,
            IsActive     BIT DEFAULT 1,
            Notes        NVARCHAR(500),
            CreatedAt    DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='PriceListItem' AND xtype='U')
        CREATE TABLE PriceListItem (
            ItemID       INT IDENTITY PRIMARY KEY,
            PriceListID  INT NOT NULL,
            BusinessID   INT NOT NULL,
            CropName     NVARCHAR(100) NOT NULL,
            Variety      NVARCHAR(100),
            Unit         NVARCHAR(30) DEFAULT 'kg',
            PricePerUnit DECIMAL(10,2) NOT NULL,
            MinQty       DECIMAL(10,2),
            Notes        NVARCHAR(300),
            CreatedAt    DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='SalesQuote' AND xtype='U')
        CREATE TABLE SalesQuote (
            QuoteID     INT IDENTITY PRIMARY KEY,
            BusinessID  INT NOT NULL,
            ContactID   INT,
            BuyerName   NVARCHAR(200),
            QuoteDate   DATE NOT NULL,
            ExpiryDate  DATE,
            Status      NVARCHAR(30) DEFAULT 'Draft',
            Notes       NVARCHAR(MAX),
            TotalValue  DECIMAL(12,2) DEFAULT 0,
            CreatedAt   DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='SalesQuoteItem' AND xtype='U')
        CREATE TABLE SalesQuoteItem (
            LineItemID   INT IDENTITY PRIMARY KEY,
            QuoteID      INT NOT NULL,
            BusinessID   INT NOT NULL,
            CropName     NVARCHAR(100) NOT NULL,
            Variety      NVARCHAR(100),
            Qty          DECIMAL(10,2) NOT NULL,
            Unit         NVARCHAR(30) DEFAULT 'kg',
            PricePerUnit DECIMAL(10,2) NOT NULL,
            LineTotal    DECIMAL(12,2),
            Notes        NVARCHAR(300),
            CreatedAt    DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


# ── Price Lists ───────────────────────────────────────────────────────────────

@router.get("/lists")
def list_price_lists(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT pl.PriceListID, pl.ListName, pl.BuyerTier, pl.ValidFrom, pl.ValidTo,
               pl.IsActive, pl.Notes, pl.CreatedAt,
               (SELECT COUNT(*) FROM PriceListItem WHERE PriceListID=pl.PriceListID) AS item_count
        FROM PriceList pl
        WHERE pl.BusinessID=:bid
        ORDER BY pl.IsActive DESC, pl.ListName
    """), {"bid": business_id}).fetchall()
    return [dict(zip(
        ["price_list_id","list_name","buyer_tier","valid_from","valid_to",
         "is_active","notes","created_at","item_count"], r
    )) for r in rows]


@router.post("/lists")
def create_price_list(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO PriceList (BusinessID, ListName, BuyerTier, ValidFrom, ValidTo, IsActive, Notes)
        OUTPUT INSERTED.PriceListID
        VALUES (:bid,:name,:tier,:vf,:vt,:active,:notes)
    """), {
        "bid": business_id, "name": body.get("list_name",""),
        "tier": body.get("buyer_tier","Wholesale"),
        "vf": body.get("valid_from") or None, "vt": body.get("valid_to") or None,
        "active": 1 if body.get("is_active", True) else 0,
        "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"price_list_id": row[0]}


@router.put("/lists/{list_id}")
def update_price_list(list_id: int, business_id: int = Query(...),
                      db: Session = Depends(get_db), body: dict = None):
    body = body or {}
    db.execute(text("""
        UPDATE PriceList SET ListName=:name, BuyerTier=:tier, ValidFrom=:vf,
            ValidTo=:vt, IsActive=:active, Notes=:notes
        WHERE PriceListID=:lid AND BusinessID=:bid
    """), {
        "lid": list_id, "bid": business_id, "name": body.get("list_name",""),
        "tier": body.get("buyer_tier","Wholesale"),
        "vf": body.get("valid_from") or None, "vt": body.get("valid_to") or None,
        "active": 1 if body.get("is_active", True) else 0,
        "notes": body.get("notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/lists/{list_id}")
def delete_price_list(list_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM PriceListItem WHERE PriceListID=:lid AND BusinessID=:bid"),
               {"lid": list_id, "bid": business_id})
    db.execute(text("DELETE FROM PriceList WHERE PriceListID=:lid AND BusinessID=:bid"),
               {"lid": list_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Price List Items ──────────────────────────────────────────────────────────

@router.get("/lists/{list_id}/items")
def list_items(list_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT ItemID, CropName, Variety, Unit, PricePerUnit, MinQty, Notes
        FROM PriceListItem WHERE PriceListID=:lid AND BusinessID=:bid ORDER BY CropName
    """), {"lid": list_id, "bid": business_id}).fetchall()
    return [dict(zip(["item_id","crop_name","variety","unit","price_per_unit","min_qty","notes"], r))
            for r in rows]


@router.post("/items")
def add_item(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO PriceListItem (PriceListID, BusinessID, CropName, Variety, Unit, PricePerUnit, MinQty, Notes)
        OUTPUT INSERTED.ItemID
        VALUES (:lid,:bid,:crop,:variety,:unit,:price,:minqty,:notes)
    """), {
        "lid": body.get("price_list_id"), "bid": business_id,
        "crop": body.get("crop_name",""), "variety": body.get("variety"),
        "unit": body.get("unit","kg"), "price": body.get("price_per_unit",0),
        "minqty": body.get("min_qty") or None, "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"item_id": row[0]}


@router.delete("/items/{item_id}")
def delete_item(item_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM PriceListItem WHERE ItemID=:iid AND BusinessID=:bid"),
               {"iid": item_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Quotes ────────────────────────────────────────────────────────────────────

@router.get("/quotes")
def list_quotes(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT QuoteID, ContactID, BuyerName, QuoteDate, ExpiryDate, Status, TotalValue, Notes, CreatedAt
        FROM SalesQuote WHERE BusinessID=:bid ORDER BY QuoteDate DESC
    """), {"bid": business_id}).fetchall()
    return [dict(zip(
        ["quote_id","contact_id","buyer_name","quote_date","expiry_date",
         "status","total_value","notes","created_at"], r
    )) for r in rows]


@router.post("/quotes")
def create_quote(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO SalesQuote (BusinessID, ContactID, BuyerName, QuoteDate, ExpiryDate, Status, Notes)
        OUTPUT INSERTED.QuoteID
        VALUES (:bid,:cid,:buyer,:dt,:exp,:status,:notes)
    """), {
        "bid": business_id, "cid": body.get("contact_id") or None,
        "buyer": body.get("buyer_name",""),
        "dt": body.get("quote_date", __import__("datetime").date.today().isoformat()),
        "exp": body.get("expiry_date") or None,
        "status": body.get("status","Draft"), "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"quote_id": row[0]}


@router.patch("/quotes/{quote_id}/status")
def update_quote_status(quote_id: int, business_id: int = Query(...),
                        db: Session = Depends(get_db), body: dict = None):
    body = body or {}
    db.execute(text("""
        UPDATE SalesQuote SET Status=:status WHERE QuoteID=:qid AND BusinessID=:bid
    """), {"qid": quote_id, "bid": business_id, "status": body.get("status")})
    db.commit()
    return {"ok": True}


@router.delete("/quotes/{quote_id}")
def delete_quote(quote_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM SalesQuoteItem WHERE QuoteID=:qid AND BusinessID=:bid"),
               {"qid": quote_id, "bid": business_id})
    db.execute(text("DELETE FROM SalesQuote WHERE QuoteID=:qid AND BusinessID=:bid"),
               {"qid": quote_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Quote Line Items ──────────────────────────────────────────────────────────

@router.get("/quotes/{quote_id}/items")
def list_quote_items(quote_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT LineItemID, CropName, Variety, Qty, Unit, PricePerUnit, LineTotal, Notes
        FROM SalesQuoteItem WHERE QuoteID=:qid AND BusinessID=:bid ORDER BY CropName
    """), {"qid": quote_id, "bid": business_id}).fetchall()
    return [dict(zip(
        ["line_item_id","crop_name","variety","qty","unit","price_per_unit","line_total","notes"], r
    )) for r in rows]


@router.post("/quotes/{quote_id}/items")
def add_quote_item(quote_id: int, business_id: int = Query(...),
                   db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    qty = float(body.get("qty", 0) or 0)
    price = float(body.get("price_per_unit", 0) or 0)
    line_total = round(qty * price, 2)
    row = db.execute(text("""
        INSERT INTO SalesQuoteItem
            (QuoteID, BusinessID, CropName, Variety, Qty, Unit, PricePerUnit, LineTotal, Notes)
        OUTPUT INSERTED.LineItemID
        VALUES (:qid,:bid,:crop,:variety,:qty,:unit,:price,:total,:notes)
    """), {
        "qid": quote_id, "bid": business_id,
        "crop": body.get("crop_name",""), "variety": body.get("variety"),
        "qty": qty, "unit": body.get("unit","kg"),
        "price": price, "total": line_total, "notes": body.get("notes"),
    }).fetchone()
    # Update quote total
    db.execute(text("""
        UPDATE SalesQuote SET TotalValue =
            (SELECT ISNULL(SUM(LineTotal),0) FROM SalesQuoteItem WHERE QuoteID=:qid AND BusinessID=:bid)
        WHERE QuoteID=:qid AND BusinessID=:bid
    """), {"qid": quote_id, "bid": business_id})
    db.commit()
    return {"line_item_id": row[0], "line_total": line_total}


@router.delete("/quote-items/{line_item_id}")
def delete_quote_item(line_item_id: int, business_id: int = Query(...),
                      db: Session = Depends(get_db)):
    # Get quote_id before deleting
    r = db.execute(text("SELECT QuoteID FROM SalesQuoteItem WHERE LineItemID=:lid AND BusinessID=:bid"),
                   {"lid": line_item_id, "bid": business_id}).fetchone()
    db.execute(text("DELETE FROM SalesQuoteItem WHERE LineItemID=:lid AND BusinessID=:bid"),
               {"lid": line_item_id, "bid": business_id})
    if r:
        db.execute(text("""
            UPDATE SalesQuote SET TotalValue =
                (SELECT ISNULL(SUM(LineTotal),0) FROM SalesQuoteItem WHERE QuoteID=:qid AND BusinessID=:bid)
            WHERE QuoteID=:qid AND BusinessID=:bid
        """), {"qid": r[0], "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary")
def get_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    r = db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM PriceList WHERE BusinessID=:bid AND IsActive=1) AS active_lists,
            (SELECT COUNT(*) FROM SalesQuote WHERE BusinessID=:bid AND Status='Draft') AS draft_quotes,
            (SELECT COUNT(*) FROM SalesQuote WHERE BusinessID=:bid AND Status='Sent') AS sent_quotes,
            (SELECT ISNULL(SUM(TotalValue),0) FROM SalesQuote WHERE BusinessID=:bid
             AND Status='Accepted' AND QuoteDate >= DATEADD(month,-1,GETDATE())) AS accepted_value_month
    """), {"bid": business_id}).fetchone()
    return dict(zip(["active_lists","draft_quotes","sent_quotes","accepted_value_month"], r))
