from fastapi import APIRouter, Depends, HTTPException, Query
from database import blank_to_none
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

router = APIRouter(prefix="/api/farmer-settlement", tags=["farmer_settlement"])


def _ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FarmerSettlement')
        CREATE TABLE FarmerSettlement (
            SettlementID     INT IDENTITY PRIMARY KEY,
            BusinessID       INT            NOT NULL,
            FarmerName       NVARCHAR(200)  NOT NULL,
            FarmerPhone      NVARCHAR(50)   NULL,
            FarmerUPI        NVARCHAR(200)  NULL,
            CommissionPct    DECIMAL(5,2)   NOT NULL DEFAULT 0.0,
            LogisticsCost    DECIMAL(10,2)  NOT NULL DEFAULT 0.0,
            OtherDeductions  DECIMAL(10,2)  NOT NULL DEFAULT 0.0,
            GrossSales       DECIMAL(10,2)  NOT NULL DEFAULT 0.0,
            NetPayment       AS (GrossSales - (GrossSales * CommissionPct / 100) - LogisticsCost - OtherDeductions) PERSISTED,
            Status           NVARCHAR(20)   NOT NULL DEFAULT 'Pending',
            Notes            NVARCHAR(1000) NULL,
            PaidAt           DATETIME2      NULL,
            PaymentRef       NVARCHAR(500)  NULL,
            CreatedAt        DATETIME2      DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'SettlementItem')
        CREATE TABLE SettlementItem (
            ItemID        INT IDENTITY PRIMARY KEY,
            SettlementID  INT            NOT NULL,
            ItemName      NVARCHAR(200)  NOT NULL,
            Qty           DECIMAL(10,3)  NOT NULL DEFAULT 1,
            Unit          NVARCHAR(50)   NULL,
            UnitPrice     DECIMAL(10,2)  NOT NULL DEFAULT 0.0,
            LineTotal     AS (Qty * UnitPrice) PERSISTED
        )
    """))
    db.commit()


def _recalc_gross(settlement_id: int, db: Session):
    """Update GrossSales from sum of SettlementItem.LineTotal."""
    db.execute(
        text("""
            UPDATE FarmerSettlement
            SET GrossSales = (
                SELECT COALESCE(SUM(Qty * UnitPrice), 0)
                FROM SettlementItem WHERE SettlementID = :sid
            )
            WHERE SettlementID = :sid
        """),
        {"sid": settlement_id},
    )


# ── Settlements ───────────────────────────────────────────────────────────────

@router.get("/settlements")
def list_settlements(
    business_id: int = Query(...),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    sql_q = """
        SELECT SettlementID, BusinessID, FarmerName, FarmerPhone, FarmerUPI,
               CommissionPct, LogisticsCost, OtherDeductions,
               GrossSales, NetPayment, Status, Notes, PaidAt, PaymentRef, CreatedAt
        FROM FarmerSettlement
        WHERE BusinessID = :bid
    """
    params: dict = {"bid": business_id}
    if status:
        sql_q += " AND Status = :status"
        params["status"] = status
    sql_q += " ORDER BY CreatedAt DESC"
    rows = db.execute(text(sql_q), params).fetchall()
    cols = ["SettlementID", "BusinessID", "FarmerName", "FarmerPhone", "FarmerUPI",
            "CommissionPct", "LogisticsCost", "OtherDeductions",
            "GrossSales", "NetPayment", "Status", "Notes", "PaidAt", "PaymentRef", "CreatedAt"]
    return [dict(zip(cols, r)) for r in rows]


@router.get("/settlements/{settlement_id}")
def get_settlement(settlement_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    row = db.execute(
        text("""
            SELECT SettlementID, BusinessID, FarmerName, FarmerPhone, FarmerUPI,
                   CommissionPct, LogisticsCost, OtherDeductions,
                   GrossSales, NetPayment, Status, Notes, PaidAt, PaymentRef, CreatedAt
            FROM FarmerSettlement WHERE SettlementID = :sid
        """),
        {"sid": settlement_id},
    ).fetchone()
    if not row:
        raise HTTPException(404, "Settlement not found")
    cols = ["SettlementID", "BusinessID", "FarmerName", "FarmerPhone", "FarmerUPI",
            "CommissionPct", "LogisticsCost", "OtherDeductions",
            "GrossSales", "NetPayment", "Status", "Notes", "PaidAt", "PaymentRef", "CreatedAt"]
    settlement = dict(zip(cols, row))

    items = db.execute(
        text("SELECT ItemID, SettlementID, ItemName, Qty, Unit, UnitPrice, LineTotal FROM SettlementItem WHERE SettlementID = :sid ORDER BY ItemID"),
        {"sid": settlement_id},
    ).fetchall()
    item_cols = ["ItemID", "SettlementID", "ItemName", "Qty", "Unit", "UnitPrice", "LineTotal"]
    settlement["items"] = [dict(zip(item_cols, i)) for i in items]
    return settlement


@router.post("/settlements")
def create_settlement(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("FarmerName"):
        raise HTTPException(400, "BusinessID and FarmerName are required")
    row = db.execute(
        text("""
            INSERT INTO FarmerSettlement
                (BusinessID, FarmerName, FarmerPhone, FarmerUPI,
                 CommissionPct, LogisticsCost, OtherDeductions, GrossSales, Notes)
            OUTPUT INSERTED.SettlementID
            VALUES (:bid, :name, :phone, :upi, :comm, :logi, :other, 0, :notes)
        """),
        {
            "bid":   body["BusinessID"],
            "name":  body["FarmerName"],
            "phone": body.get("FarmerPhone"),
            "upi":   body.get("FarmerUPI"),
            "comm":  body.get("CommissionPct", 0.0),
            "logi":  body.get("LogisticsCost", 0.0),
            "other": body.get("OtherDeductions", 0.0),
            "notes": body.get("Notes"),
        },
    ).fetchone()
    db.commit()
    return {"SettlementID": row[0]}


@router.put("/settlements/{settlement_id}")
def update_settlement(settlement_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    db.execute(
        text("""
            UPDATE FarmerSettlement SET
                FarmerName      = COALESCE(:name,  FarmerName),
                FarmerPhone     = COALESCE(:phone, FarmerPhone),
                FarmerUPI       = COALESCE(:upi,   FarmerUPI),
                CommissionPct   = COALESCE(:comm,  CommissionPct),
                LogisticsCost   = COALESCE(:logi,  LogisticsCost),
                OtherDeductions = COALESCE(:other, OtherDeductions),
                Notes           = COALESCE(:notes, Notes)
            WHERE SettlementID = :sid AND Status = 'Pending'
        """),
        {
            "sid":   settlement_id,
            "name":  body.get("FarmerName"),
            "phone": body.get("FarmerPhone"),
            "upi":   body.get("FarmerUPI"),
            "comm":  body.get("CommissionPct"),
            "logi":  body.get("LogisticsCost"),
            "other": body.get("OtherDeductions"),
            "notes": body.get("Notes"),
        },
    )
    db.commit()
    return {"ok": True}


@router.post("/settlements/{settlement_id}/mark-paid")
def mark_paid(settlement_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    db.execute(
        text("""
            UPDATE FarmerSettlement
            SET Status = 'Paid', PaidAt = GETDATE(), PaymentRef = :ref
            WHERE SettlementID = :sid AND Status = 'Pending'
        """),
        {"sid": settlement_id, "ref": body.get("PaymentRef")},
    )
    db.commit()
    return {"ok": True}


@router.post("/settlements/{settlement_id}/cancel")
def cancel_settlement(settlement_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(
        text("UPDATE FarmerSettlement SET Status = 'Cancelled' WHERE SettlementID = :sid AND Status = 'Pending'"),
        {"sid": settlement_id},
    )
    db.commit()
    return {"ok": True}


@router.delete("/settlements/{settlement_id}")
def delete_settlement(settlement_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM SettlementItem   WHERE SettlementID = :sid"), {"sid": settlement_id})
    db.execute(text("DELETE FROM FarmerSettlement WHERE SettlementID = :sid AND Status != 'Paid'"), {"sid": settlement_id})
    db.commit()
    return {"ok": True}


# ── Line Items ────────────────────────────────────────────────────────────────

@router.post("/settlements/{settlement_id}/items")
def add_item(settlement_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("ItemName"):
        raise HTTPException(400, "ItemName is required")
    row = db.execute(
        text("""
            INSERT INTO SettlementItem (SettlementID, ItemName, Qty, Unit, UnitPrice)
            OUTPUT INSERTED.ItemID
            VALUES (:sid, :name, :qty, :unit, :price)
        """),
        {
            "sid":   settlement_id,
            "name":  body["ItemName"],
            "qty":   body.get("Qty", 1),
            "unit":  body.get("Unit"),
            "price": body.get("UnitPrice", 0.0),
        },
    ).fetchone()
    _recalc_gross(settlement_id, db)
    db.commit()
    return {"ItemID": row[0]}


@router.put("/items/{item_id}")
def update_item(item_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    db.execute(
        text("""
            UPDATE SettlementItem SET
                ItemName  = COALESCE(:name,  ItemName),
                Qty       = COALESCE(:qty,   Qty),
                Unit      = COALESCE(:unit,  Unit),
                UnitPrice = COALESCE(:price, UnitPrice)
            WHERE ItemID = :iid
        """),
        {
            "iid":   item_id,
            "name":  body.get("ItemName"),
            "qty":   body.get("Qty"),
            "unit":  body.get("Unit"),
            "price": body.get("UnitPrice"),
        },
    )
    sid_row = db.execute(text("SELECT SettlementID FROM SettlementItem WHERE ItemID = :iid"), {"iid": item_id}).fetchone()
    if sid_row:
        _recalc_gross(sid_row[0], db)
    db.commit()
    return {"ok": True}


@router.delete("/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    sid_row = db.execute(text("SELECT SettlementID FROM SettlementItem WHERE ItemID = :iid"), {"iid": item_id}).fetchone()
    db.execute(text("DELETE FROM SettlementItem WHERE ItemID = :iid"), {"iid": item_id})
    if sid_row:
        _recalc_gross(sid_row[0], db)
    db.commit()
    return {"ok": True}
