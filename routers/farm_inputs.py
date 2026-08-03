from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from datetime import datetime, date
from typing import Optional
import math
from routers.notifications import notify_business

router = APIRouter(prefix="/api/farm-inputs", tags=["farm_inputs"])

_tables_ready = False


def _ensure_tables(db: Session):
    global _tables_ready
    if _tables_ready:
        return

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FarmInput')
        CREATE TABLE FarmInput (
            InputID          INT IDENTITY PRIMARY KEY,
            BusinessID       INT           NOT NULL,
            InputName        NVARCHAR(200) NOT NULL,
            Category         NVARCHAR(50)  NOT NULL DEFAULT 'other',
            Unit             NVARCHAR(50)  NOT NULL DEFAULT 'unit',
            CurrentStock     DECIMAL(12,3) NOT NULL DEFAULT 0,
            MinStockAlert    DECIMAL(12,3) NULL,
            CostPerUnit      DECIMAL(10,2) NULL,
            Supplier         NVARCHAR(200) NULL,
            StorageLocation  NVARCHAR(200) NULL,
            ExpiryDate       DATE          NULL,
            LotNumber        NVARCHAR(100) NULL,
            REIHours         DECIMAL(6,1)  NULL,
            PHIHours         DECIMAL(6,1)  NULL,
            ActiveIngredient NVARCHAR(300) NULL,
            EPARegNumber     NVARCHAR(100) NULL,
            Notes            NVARCHAR(1000) NULL,
            IsActive         BIT           NOT NULL DEFAULT 1,
            CreatedAt        DATETIME2     DEFAULT GETDATE(),
            UpdatedAt        DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FarmInputTransaction')
        CREATE TABLE FarmInputTransaction (
            TxID          INT IDENTITY PRIMARY KEY,
            InputID       INT           NOT NULL,
            BusinessID    INT           NOT NULL,
            TxType        NVARCHAR(20)  NOT NULL DEFAULT 'use',
            Quantity      DECIMAL(12,3) NOT NULL,
            UnitCost      DECIMAL(10,2) NULL,
            TotalCost     DECIMAL(12,2) NULL,
            ReferenceType NVARCHAR(50)  NULL,
            ReferenceID   INT           NULL,
            FieldID       INT           NULL,
            CropName      NVARCHAR(200) NULL,
            ApplicationDate DATE        NULL,
            Notes         NVARCHAR(500) NULL,
            CreatedAt     DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FarmInputLot')
        CREATE TABLE FarmInputLot (
            LotID       INT IDENTITY PRIMARY KEY,
            InputID     INT           NOT NULL,
            BusinessID  INT           NOT NULL,
            LotNumber   NVARCHAR(100) NOT NULL,
            Quantity    DECIMAL(12,3) NOT NULL,
            ReceivedDate DATE         NOT NULL,
            ExpiryDate  DATE          NULL,
            UnitCost    DECIMAL(10,2) NULL,
            Supplier    NVARCHAR(200) NULL,
            IsExhausted BIT           NOT NULL DEFAULT 0,
            CreatedAt   DATETIME2     DEFAULT GETDATE()
        )
    """))
    # BarcodeID column — safe to run every time (idempotent)
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sys.columns
            WHERE object_id = OBJECT_ID('FarmInput') AND name = 'BarcodeID')
        ALTER TABLE FarmInput ADD BarcodeID NVARCHAR(200) NULL
    """))

    db.commit()
    _tables_ready = True


# ── Inputs CRUD ───────────────────────────────────────────────────────────────

@router.get("/inputs")
def list_inputs(
    business_id: int = Query(...),
    category: Optional[str] = None,
    low_stock: Optional[bool] = None,
    expiring_days: Optional[int] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    q = """
        SELECT InputID, BusinessID, InputName, Category, Unit,
               CurrentStock, MinStockAlert, CostPerUnit, Supplier,
               StorageLocation, ExpiryDate, LotNumber, REIHours, PHIHours,
               ActiveIngredient, EPARegNumber, Notes, IsActive, CreatedAt, UpdatedAt
        FROM FarmInput
        WHERE BusinessID = :bid AND IsActive = 1
    """
    params: dict = {"bid": business_id}
    if category:
        q += " AND Category = :cat"
        params["cat"] = category
    if low_stock:
        q += " AND MinStockAlert IS NOT NULL AND CurrentStock <= MinStockAlert"
    if expiring_days is not None:
        q += " AND ExpiryDate IS NOT NULL AND ExpiryDate <= DATEADD(DAY, :days, GETDATE())"
        params["days"] = expiring_days
    q += " ORDER BY Category, InputName"
    rows = db.execute(text(q), params).fetchall()
    return [_input_row(r) for r in rows]


@router.get("/inputs/{input_id}")
def get_input(input_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    row = db.execute(
        text("SELECT * FROM FarmInput WHERE InputID = :id AND BusinessID = :bid"),
        {"id": input_id, "bid": business_id},
    ).fetchone()
    if not row:
        raise HTTPException(404, "Input not found")
    return _input_row(row)


@router.post("/inputs")
def create_input(payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    if not bid:
        raise HTTPException(400, "business_id required")
    row = db.execute(text("""
        INSERT INTO FarmInput
            (BusinessID, InputName, Category, Unit, CurrentStock, MinStockAlert,
             CostPerUnit, Supplier, StorageLocation, ExpiryDate, LotNumber,
             REIHours, PHIHours, ActiveIngredient, EPARegNumber, Notes, BarcodeID)
        OUTPUT INSERTED.InputID
        VALUES (:bid, :name, :cat, :unit, :stock, :alert, :cost, :supplier,
                :loc, :exp, :lot, :rei, :phi, :ai, :epa, :notes, :barcode)
    """), {
        "bid":      bid,
        "name":     payload.get("input_name", ""),
        "cat":      payload.get("category", "other"),
        "unit":     payload.get("unit", "unit"),
        "stock":    payload.get("current_stock", 0),
        "alert":    payload.get("min_stock_alert"),
        "cost":     payload.get("cost_per_unit"),
        "supplier": payload.get("supplier"),
        "loc":      payload.get("storage_location"),
        "exp":      payload.get("expiry_date"),
        "lot":      payload.get("lot_number"),
        "rei":      payload.get("rei_hours"),
        "phi":      payload.get("phi_hours"),
        "ai":       payload.get("active_ingredient"),
        "epa":      payload.get("epa_reg_number"),
        "notes":    payload.get("notes"),
        "barcode":  payload.get("barcode_id"),
    }).fetchone()
    db.commit()
    return {"input_id": row[0]}


@router.put("/inputs/{input_id}")
def update_input(input_id: int, payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    db.execute(text("""
        UPDATE FarmInput SET
            InputName        = :name,
            Category         = :cat,
            Unit             = :unit,
            MinStockAlert    = :alert,
            CostPerUnit      = :cost,
            Supplier         = :supplier,
            StorageLocation  = :loc,
            ExpiryDate       = :exp,
            LotNumber        = :lot,
            REIHours         = :rei,
            PHIHours         = :phi,
            ActiveIngredient = :ai,
            EPARegNumber     = :epa,
            Notes            = :notes,
            BarcodeID        = :barcode,
            UpdatedAt        = GETDATE()
        WHERE InputID = :id AND BusinessID = :bid
    """), {
        "id":       input_id,
        "bid":      bid,
        "name":     payload.get("input_name"),
        "cat":      payload.get("category"),
        "unit":     payload.get("unit"),
        "alert":    payload.get("min_stock_alert"),
        "cost":     payload.get("cost_per_unit"),
        "supplier": payload.get("supplier"),
        "loc":      payload.get("storage_location"),
        "exp":      payload.get("expiry_date"),
        "lot":      payload.get("lot_number"),
        "rei":      payload.get("rei_hours"),
        "phi":      payload.get("phi_hours"),
        "ai":       payload.get("active_ingredient"),
        "epa":      payload.get("epa_reg_number"),
        "notes":    payload.get("notes"),
        "barcode":  payload.get("barcode_id"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/inputs/{input_id}")
def delete_input(input_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(
        text("UPDATE FarmInput SET IsActive = 0 WHERE InputID = :id AND BusinessID = :bid"),
        {"id": input_id, "bid": business_id},
    )
    db.commit()
    return {"ok": True}


# ── Transactions ──────────────────────────────────────────────────────────────

@router.get("/transactions")
def list_transactions(
    business_id: int = Query(...),
    input_id: Optional[int] = None,
    field_id: Optional[int] = None,
    tx_type: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    q = """
        SELECT t.TxID, t.InputID, t.BusinessID, t.TxType, t.Quantity,
               t.UnitCost, t.TotalCost, t.ReferenceType, t.ReferenceID,
               t.FieldID, t.CropName, t.ApplicationDate, t.Notes, t.CreatedAt,
               i.InputName, i.Unit, i.Category
        FROM FarmInputTransaction t
        JOIN FarmInput i ON i.InputID = t.InputID
        WHERE t.BusinessID = :bid
    """
    params: dict = {"bid": business_id}
    if input_id:
        q += " AND t.InputID = :iid"
        params["iid"] = input_id
    if field_id:
        q += " AND t.FieldID = :fid"
        params["fid"] = field_id
    if tx_type:
        q += " AND t.TxType = :tt"
        params["tt"] = tx_type
    q += f" ORDER BY t.CreatedAt DESC OFFSET 0 ROWS FETCH NEXT {int(limit)} ROWS ONLY"
    rows = db.execute(text(q), params).fetchall()
    return [_tx_row(r) for r in rows]


@router.post("/transactions")
def record_transaction(payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    input_id = payload.get("input_id")
    tx_type = payload.get("tx_type", "use")
    qty = float(payload.get("quantity", 0))
    unit_cost = payload.get("unit_cost")
    total_cost = payload.get("total_cost")

    if not bid or not input_id:
        raise HTTPException(400, "business_id and input_id required")

    # Verify the input belongs to this business
    inp = db.execute(
        text("SELECT CurrentStock, CostPerUnit, MinStockAlert, InputName, Unit FROM FarmInput WHERE InputID = :id AND BusinessID = :bid"),
        {"id": input_id, "bid": bid},
    ).fetchone()
    if not inp:
        raise HTTPException(404, "Input not found")

    if unit_cost is None and inp.CostPerUnit:
        unit_cost = float(inp.CostPerUnit)
    if total_cost is None and unit_cost is not None:
        total_cost = round(unit_cost * qty, 2)

    # Adjust stock
    if tx_type in ("receive", "adjust"):
        new_stock = float(inp.CurrentStock) + qty
    elif tx_type in ("use", "dispose"):
        new_stock = max(0.0, float(inp.CurrentStock) - qty)
    else:
        new_stock = float(inp.CurrentStock)

    db.execute(
        text("UPDATE FarmInput SET CurrentStock = :s, UpdatedAt = GETDATE() WHERE InputID = :id AND BusinessID = :bid"),
        {"s": new_stock, "id": input_id, "bid": bid},
    )

    db.execute(text("""
        INSERT INTO FarmInputTransaction
            (InputID, BusinessID, TxType, Quantity, UnitCost, TotalCost,
             ReferenceType, ReferenceID, FieldID, CropName, ApplicationDate, Notes)
        VALUES (:iid, :bid, :tt, :qty, :uc, :tc, :rt, :rid, :fid, :crop, :appdate, :notes)
    """), {
        "iid":     input_id,
        "bid":     bid,
        "tt":      tx_type,
        "qty":     qty,
        "uc":      unit_cost,
        "tc":      total_cost,
        "rt":      payload.get("reference_type"),
        "rid":     payload.get("reference_id"),
        "fid":     payload.get("field_id"),
        "crop":    payload.get("crop_name"),
        "appdate": payload.get("application_date"),
        "notes":   payload.get("notes"),
    })

    # FEFO lot deduction if lots exist for a 'use' transaction
    if tx_type == "use":
        lots = db.execute(text("""
            SELECT LotID, Quantity FROM FarmInputLot
            WHERE InputID = :iid AND BusinessID = :bid AND IsExhausted = 0
            ORDER BY ExpiryDate ASC, ReceivedDate ASC
        """), {"iid": input_id, "bid": bid}).fetchall()
        remaining = qty
        for lot in lots:
            if remaining <= 0:
                break
            lot_qty = float(lot.Quantity)
            deduct = min(lot_qty, remaining)
            new_lot_qty = lot_qty - deduct
            remaining -= deduct
            db.execute(text("""
                UPDATE FarmInputLot SET
                    Quantity = :q,
                    IsExhausted = :ex
                WHERE LotID = :lid
            """), {"q": new_lot_qty, "lid": lot.LotID, "ex": 1 if new_lot_qty <= 0 else 0})

    db.commit()

    # Sync ActualCost to matching CropBudget on usage transactions
    if tx_type in ("use", "dispose") and payload.get("crop_name") and total_cost:
        try:
            from datetime import date as _date
            app_date = payload.get("application_date", "")
            cost_year = int(str(app_date)[:4]) if app_date and len(str(app_date)) >= 4 else _date.today().year
            db.execute(text("""
                UPDATE CropBudget
                SET ActualCost = ISNULL(ActualCost, 0) + :cost, UpdatedAt = GETDATE()
                WHERE BusinessID = :bid AND CropName = :crop AND CropYear = :yr
            """), {"cost": float(total_cost), "bid": bid, "crop": payload["crop_name"], "yr": cost_year})
            db.commit()
        except Exception as _e:
            print(f"[input-usage] budget cost sync failed: {_e}")

    # Notify + auto-reorder when stock drops at or below the alert threshold
    if tx_type in ("use", "dispose") and inp.MinStockAlert is not None and new_stock <= float(inp.MinStockAlert):
        notify_business(
            db, bid,
            type="low_stock",
            title=f"Low Stock: {inp.InputName}",
            body=f"Stock is {new_stock:.2f} {inp.Unit} (min: {float(inp.MinStockAlert):.2f})",
            link_path=f"/farm-inputs?BusinessID={bid}",
            entity_type="FarmInput",
            entity_id=input_id,
        )
        # Auto-create a draft reorder PO if none exists in the last 14 days
        try:
            tag = f"[auto-reorder-input-{input_id}]"
            existing = db.execute(text("""
                SELECT TOP 1 POID FROM PurchaseOrder
                WHERE BusinessID=:bid AND Status='draft'
                  AND Notes LIKE :tag AND CreatedAt >= DATEADD(day,-14,GETDATE())
            """), {"bid": bid, "tag": f"%{tag}%"}).fetchone()
            if not existing:
                count = db.execute(text("SELECT COUNT(*)+1 FROM PurchaseOrder WHERE BusinessID=:bid"), {"bid": bid}).scalar()
                po_num = f"PO-AUTO-{bid}-{count:04d}"
                reorder_qty = max(float(inp.MinStockAlert) * 2, 1.0)
                unit_cost = float(inp.CostPerUnit) if inp.CostPerUnit else 0.0
                line_total = round(reorder_qty * unit_cost, 2)
                po_row = db.execute(text("""
                    INSERT INTO PurchaseOrder
                        (BusinessID, PONumber, SupplierName, Category, OrderDate, Status, Notes)
                    OUTPUT INSERTED.POID
                    VALUES (:bid, :pnum, :sup, 'farm_inputs', CAST(GETDATE() AS DATE), 'draft', :notes)
                """), {
                    "bid":   bid,
                    "pnum":  po_num,
                    "sup":   inp.Supplier or "Unknown Supplier",
                    "notes": f"{tag} Auto-reorder: {inp.InputName} — stock {new_stock:.2f} {inp.Unit} (min {float(inp.MinStockAlert):.2f})",
                }).fetchone()
                po_id = po_row[0]
                db.execute(text("""
                    INSERT INTO POLineItem (POID, ItemName, Category, Quantity, Unit, UnitPrice, LineTotal)
                    VALUES (:pid, :name, 'farm_inputs', :qty, :unit, :up, :lt)
                """), {"pid": po_id, "name": inp.InputName, "qty": reorder_qty,
                       "unit": inp.Unit, "up": unit_cost, "lt": line_total})
                db.execute(text("UPDATE PurchaseOrder SET TotalAmount=:t WHERE POID=:pid"),
                           {"t": line_total, "pid": po_id})
        except Exception as _e:
            print(f"[auto-reorder] skipped: {_e}")
        db.commit()

    return {"ok": True, "new_stock": new_stock}


# ── Lots ──────────────────────────────────────────────────────────────────────

@router.get("/inputs/{input_id}/lots")
def list_lots(input_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT LotID, InputID, BusinessID, LotNumber, Quantity,
               ReceivedDate, ExpiryDate, UnitCost, Supplier, IsExhausted, CreatedAt
        FROM FarmInputLot
        WHERE InputID = :iid AND BusinessID = :bid
        ORDER BY IsExhausted ASC, ExpiryDate ASC
    """), {"iid": input_id, "bid": business_id}).fetchall()
    return [_lot_row(r) for r in rows]


@router.post("/inputs/{input_id}/lots")
def add_lot(input_id: int, payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    qty = float(payload.get("quantity", 0))
    db.execute(text("""
        INSERT INTO FarmInputLot (InputID, BusinessID, LotNumber, Quantity, ReceivedDate, ExpiryDate, UnitCost, Supplier)
        VALUES (:iid, :bid, :lot, :qty, :rec, :exp, :cost, :sup)
    """), {
        "iid":  input_id,
        "bid":  bid,
        "lot":  payload.get("lot_number", ""),
        "qty":  qty,
        "rec":  payload.get("received_date"),
        "exp":  payload.get("expiry_date"),
        "cost": payload.get("unit_cost"),
        "sup":  payload.get("supplier"),
    })
    # Also add stock via a receive transaction
    inp = db.execute(
        text("SELECT CurrentStock FROM FarmInput WHERE InputID = :id AND BusinessID = :bid"),
        {"id": input_id, "bid": bid},
    ).fetchone()
    if inp:
        db.execute(
            text("UPDATE FarmInput SET CurrentStock = CurrentStock + :q, UpdatedAt = GETDATE() WHERE InputID = :id AND BusinessID = :bid"),
            {"q": qty, "id": input_id, "bid": bid},
        )
    db.commit()
    return {"ok": True}


# ── Barcode / QR scan lookup ──────────────────────────────────────────────────

@router.get("/scan")
def scan_input(barcode: str = Query(...), business_id: int = Query(...), db: Session = Depends(get_db)):
    """Resolve a scanned barcode/QR code to an input + best matching lot (FEFO)."""
    _ensure_tables(db)
    # 1. Try FarmInput.BarcodeID exact match
    row = db.execute(text("""
        SELECT InputID, InputName, Category, Unit, CurrentStock, CostPerUnit,
               StorageLocation, Supplier, BarcodeID
        FROM FarmInput
        WHERE BusinessID = :bid AND BarcodeID = :bc AND IsActive = 1
    """), {"bid": business_id, "bc": barcode}).fetchone()
    if not row:
        # 2. Try lot number match
        lot = db.execute(text("""
            SELECT l.LotID, l.InputID, l.LotNumber, l.Quantity, l.ExpiryDate,
                   l.UnitCost, l.Supplier,
                   i.InputName, i.Category, i.Unit, i.CurrentStock, i.StorageLocation
            FROM FarmInputLot l
            JOIN FarmInput i ON i.InputID = l.InputID
            WHERE l.BusinessID = :bid AND l.LotNumber = :bc AND l.IsExhausted = 0
        """), {"bid": business_id, "bc": barcode}).fetchone()
        if not lot:
            raise HTTPException(404, "No input found for barcode/lot number")
        return {"match_type": "lot", **dict(lot._mapping)}
    # Return input + nearest-expiry open lot for pre-fill
    lot = db.execute(text("""
        SELECT TOP 1 LotID, LotNumber, Quantity, ExpiryDate, UnitCost, Supplier
        FROM FarmInputLot
        WHERE InputID = :iid AND BusinessID = :bid AND IsExhausted = 0
        ORDER BY ExpiryDate ASC
    """), {"iid": row.InputID, "bid": business_id}).fetchone()
    return {
        "match_type": "barcode",
        **dict(row._mapping),
        "lot": dict(lot._mapping) if lot else None,
    }


# ── Summary / Alerts ──────────────────────────────────────────────────────────

@router.get("/summary")
def inputs_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)

    totals = db.execute(text("""
        SELECT
            COUNT(*) AS total_inputs,
            SUM(CASE WHEN MinStockAlert IS NOT NULL AND CurrentStock <= MinStockAlert THEN 1 ELSE 0 END) AS low_stock_count,
            SUM(CASE WHEN ExpiryDate IS NOT NULL AND ExpiryDate <= DATEADD(DAY, 30, GETDATE()) AND ExpiryDate >= GETDATE() THEN 1 ELSE 0 END) AS expiring_soon,
            SUM(CASE WHEN ExpiryDate IS NOT NULL AND ExpiryDate < GETDATE() THEN 1 ELSE 0 END) AS expired_count,
            SUM(CurrentStock * ISNULL(CostPerUnit, 0)) AS total_inventory_value
        FROM FarmInput WHERE BusinessID = :bid AND IsActive = 1
    """), {"bid": business_id}).fetchone()

    by_category = db.execute(text("""
        SELECT Category, COUNT(*) AS cnt,
               SUM(CurrentStock * ISNULL(CostPerUnit, 0)) AS value
        FROM FarmInput WHERE BusinessID = :bid AND IsActive = 1
        GROUP BY Category ORDER BY Category
    """), {"bid": business_id}).fetchall()

    return {
        "total_inputs":        totals.total_inputs or 0,
        "low_stock_count":     totals.low_stock_count or 0,
        "expiring_soon":       totals.expiring_soon or 0,
        "expired_count":       totals.expired_count or 0,
        "total_inventory_value": float(totals.total_inventory_value or 0),
        "by_category": [
            {"category": r.Category, "count": r.cnt, "value": float(r.value or 0)}
            for r in by_category
        ],
    }


@router.get("/alerts")
def low_stock_alerts(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT InputID, InputName, Category, Unit, CurrentStock, MinStockAlert, ExpiryDate,
               CASE
                   WHEN ExpiryDate IS NOT NULL AND ExpiryDate < GETDATE() THEN 'expired'
                   WHEN ExpiryDate IS NOT NULL AND ExpiryDate <= DATEADD(DAY, 30, GETDATE()) THEN 'expiring_soon'
                   WHEN MinStockAlert IS NOT NULL AND CurrentStock <= MinStockAlert THEN 'low_stock'
                   ELSE 'ok'
               END AS alert_type
        FROM FarmInput
        WHERE BusinessID = :bid AND IsActive = 1
          AND (
              (MinStockAlert IS NOT NULL AND CurrentStock <= MinStockAlert)
              OR (ExpiryDate IS NOT NULL AND ExpiryDate <= DATEADD(DAY, 30, GETDATE()))
          )
        ORDER BY
            CASE WHEN ExpiryDate IS NOT NULL AND ExpiryDate < GETDATE() THEN 0 ELSE 1 END,
            ExpiryDate ASC
    """), {"bid": business_id}).fetchall()
    return [_alert_row(r) for r in rows]


# ── Serializers ───────────────────────────────────────────────────────────────

def _input_row(r) -> dict:
    return {
        "input_id":         r.InputID,
        "business_id":      r.BusinessID,
        "input_name":       r.InputName,
        "category":         r.Category,
        "unit":             r.Unit,
        "current_stock":    float(r.CurrentStock),
        "min_stock_alert":  float(r.MinStockAlert) if r.MinStockAlert is not None else None,
        "cost_per_unit":    float(r.CostPerUnit) if r.CostPerUnit is not None else None,
        "supplier":         r.Supplier,
        "storage_location": r.StorageLocation,
        "expiry_date":      r.ExpiryDate.isoformat() if r.ExpiryDate else None,
        "lot_number":       r.LotNumber,
        "rei_hours":        float(r.REIHours) if r.REIHours is not None else None,
        "phi_hours":        float(r.PHIHours) if r.PHIHours is not None else None,
        "active_ingredient": r.ActiveIngredient,
        "epa_reg_number":   r.EPARegNumber,
        "barcode_id":       r.BarcodeID,
        "notes":            r.Notes,
        "is_active":        bool(r.IsActive),
        "created_at":       r.CreatedAt.isoformat() if r.CreatedAt else None,
    }


def _tx_row(r) -> dict:
    return {
        "tx_id":          r.TxID,
        "input_id":       r.InputID,
        "input_name":     r.InputName,
        "category":       r.Category,
        "unit":           r.Unit,
        "tx_type":        r.TxType,
        "quantity":       float(r.Quantity),
        "unit_cost":      float(r.UnitCost) if r.UnitCost is not None else None,
        "total_cost":     float(r.TotalCost) if r.TotalCost is not None else None,
        "reference_type": r.ReferenceType,
        "reference_id":   r.ReferenceID,
        "field_id":       r.FieldID,
        "crop_name":      r.CropName,
        "application_date": r.ApplicationDate.isoformat() if r.ApplicationDate else None,
        "notes":          r.Notes,
        "created_at":     r.CreatedAt.isoformat() if r.CreatedAt else None,
    }


def _lot_row(r) -> dict:
    return {
        "lot_id":       r.LotID,
        "input_id":     r.InputID,
        "lot_number":   r.LotNumber,
        "quantity":     float(r.Quantity),
        "received_date": r.ReceivedDate.isoformat() if r.ReceivedDate else None,
        "expiry_date":  r.ExpiryDate.isoformat() if r.ExpiryDate else None,
        "unit_cost":    float(r.UnitCost) if r.UnitCost is not None else None,
        "supplier":     r.Supplier,
        "is_exhausted": bool(r.IsExhausted),
    }


def _alert_row(r) -> dict:
    return {
        "input_id":      r.InputID,
        "input_name":    r.InputName,
        "category":      r.Category,
        "unit":          r.Unit,
        "current_stock": float(r.CurrentStock),
        "min_stock_alert": float(r.MinStockAlert) if r.MinStockAlert is not None else None,
        "expiry_date":   r.ExpiryDate.isoformat() if r.ExpiryDate else None,
        "alert_type":    r.alert_type,
    }
