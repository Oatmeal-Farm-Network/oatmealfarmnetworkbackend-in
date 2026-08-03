from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional

router = APIRouter(prefix="/api/harvest-lots", tags=["harvest_lots"])

_tables_ready = False


def _ensure_tables(db: Session):
    global _tables_ready
    if _tables_ready:
        return

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'HarvestLot')
        CREATE TABLE HarvestLot (
            LotID           INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL,
            LotNumber       NVARCHAR(100) NOT NULL,
            CropName        NVARCHAR(200) NOT NULL,
            Variety         NVARCHAR(200) NULL,
            FieldID         INT           NULL,
            FieldName       NVARCHAR(200) NULL,
            HarvestDate     DATE          NOT NULL,
            Quantity        DECIMAL(12,3) NOT NULL,
            Unit            NVARCHAR(50)  NOT NULL DEFAULT 'lb',
            GradeQuality    NVARCHAR(100) NULL,
            StorageLocation NVARCHAR(200) NULL,
            StorageCondition NVARCHAR(200) NULL,
            ExpiryDate      DATE          NULL,
            CertificationStatus NVARCHAR(50) NULL,
            CertificateNumber NVARCHAR(100) NULL,
            MoistureContent DECIMAL(5,2)  NULL,
            TestWeight      DECIMAL(8,3)  NULL,
            Notes           NVARCHAR(1000) NULL,
            Status          NVARCHAR(20)  NOT NULL DEFAULT 'in_storage',
            CreatedAt       DATETIME2     DEFAULT GETDATE(),
            UpdatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'HarvestLotInput')
        CREATE TABLE HarvestLotInput (
            LinkID      INT IDENTITY PRIMARY KEY,
            LotID       INT           NOT NULL,
            BusinessID  INT           NOT NULL,
            InputID     INT           NULL,
            InputName   NVARCHAR(200) NOT NULL,
            InputCategory NVARCHAR(100) NULL,
            Quantity    DECIMAL(12,3) NULL,
            Unit        NVARCHAR(50)  NULL,
            ApplicationDate DATE      NULL,
            PreHarvestInterval INT    NULL,
            Notes       NVARCHAR(500) NULL,
            CreatedAt   DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'HarvestLotMovement')
        CREATE TABLE HarvestLotMovement (
            MovementID   INT IDENTITY PRIMARY KEY,
            LotID        INT           NOT NULL,
            BusinessID   INT           NOT NULL,
            MovementType NVARCHAR(50)  NOT NULL,
            Quantity     DECIMAL(12,3) NOT NULL,
            FromLocation NVARCHAR(200) NULL,
            ToLocation   NVARCHAR(200) NULL,
            ReferenceType NVARCHAR(50) NULL,
            ReferenceID  INT           NULL,
            Recipient    NVARCHAR(200) NULL,
            MovementDate DATE          NOT NULL,
            Notes        NVARCHAR(500) NULL,
            CreatedAt    DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'HarvestLotQC')
        CREATE TABLE HarvestLotQC (
            QCID        INT IDENTITY PRIMARY KEY,
            LotID       INT           NOT NULL,
            BusinessID  INT           NOT NULL,
            InspectedBy NVARCHAR(200) NULL,
            InspectionDate DATE       NOT NULL,
            Result      NVARCHAR(20)  NOT NULL DEFAULT 'pass',
            Grade       NVARCHAR(50)  NULL,
            Notes       NVARCHAR(1000) NULL,
            CreatedAt   DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.commit()
    _tables_ready = True


# ── Lots CRUD ─────────────────────────────────────────────────────────────────

@router.get("/lots")
def list_lots(
    business_id: int = Query(...),
    crop_name: Optional[str] = None,
    field_id: Optional[int] = None,
    status: Optional[str] = None,
    expiring_days: Optional[int] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    q = """
        SELECT l.LotID, l.BusinessID, l.LotNumber, l.CropName, l.Variety,
               l.FieldID, l.FieldName, l.HarvestDate, l.Quantity, l.Unit,
               l.GradeQuality, l.StorageLocation, l.StorageCondition, l.ExpiryDate,
               l.CertificationStatus, l.CertificateNumber, l.MoistureContent,
               l.TestWeight, l.Notes, l.Status, l.CreatedAt, l.UpdatedAt,
               (SELECT COUNT(*) FROM HarvestLotInput WHERE LotID = l.LotID) AS InputCount
        FROM HarvestLot l
        WHERE l.BusinessID = :bid
    """
    params: dict = {"bid": business_id}
    if crop_name:
        q += " AND l.CropName LIKE :crop"
        params["crop"] = f"%{crop_name}%"
    if field_id:
        q += " AND l.FieldID = :fid"
        params["fid"] = field_id
    if status:
        q += " AND l.Status = :st"
        params["st"] = status
    if expiring_days is not None:
        q += " AND l.ExpiryDate IS NOT NULL AND l.ExpiryDate <= DATEADD(DAY, :days, GETDATE())"
        params["days"] = expiring_days
    q += " ORDER BY l.HarvestDate DESC, l.LotNumber"
    rows = db.execute(text(q), params).fetchall()
    return [_lot_row(r) for r in rows]


@router.get("/lots/{lot_id}")
def get_lot(lot_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    row = db.execute(
        text("""
            SELECT l.*,
                   (SELECT COUNT(*) FROM HarvestLotInput WHERE LotID = l.LotID) AS InputCount
            FROM HarvestLot l
            WHERE l.LotID = :id AND l.BusinessID = :bid
        """),
        {"id": lot_id, "bid": business_id},
    ).fetchone()
    if not row:
        raise HTTPException(404, "Lot not found")

    inputs = db.execute(text("SELECT * FROM HarvestLotInput WHERE LotID = :id ORDER BY ApplicationDate"), {"id": lot_id}).fetchall()
    movements = db.execute(text("SELECT * FROM HarvestLotMovement WHERE LotID = :id ORDER BY MovementDate DESC"), {"id": lot_id}).fetchall()
    qc_records = db.execute(text("SELECT * FROM HarvestLotQC WHERE LotID = :id ORDER BY InspectionDate DESC"), {"id": lot_id}).fetchall()

    result = _lot_row(row)
    result["inputs"]     = [_input_link_row(r) for r in inputs]
    result["movements"]  = [_movement_row(r) for r in movements]
    result["qc_records"] = [_qc_row(r) for r in qc_records]
    return result


@router.post("/lots")
def create_lot(payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    if not bid:
        raise HTTPException(400, "business_id required")

    # Auto-generate lot number if not provided
    lot_number = payload.get("lot_number")
    if not lot_number:
        crop = payload.get("crop_name", "CROP")[:4].upper()
        harvest = (payload.get("harvest_date") or "")[:7].replace("-", "")
        count = db.execute(
            text("SELECT COUNT(*) FROM HarvestLot WHERE BusinessID = :bid"),
            {"bid": bid},
        ).scalar() or 0
        lot_number = f"{crop}-{harvest}-{count + 1:04d}"

    row = db.execute(text("""
        INSERT INTO HarvestLot
            (BusinessID, LotNumber, CropName, Variety, FieldID, FieldName,
             HarvestDate, Quantity, Unit, GradeQuality, StorageLocation,
             StorageCondition, ExpiryDate, CertificationStatus, CertificateNumber,
             MoistureContent, TestWeight, Notes, Status)
        OUTPUT INSERTED.LotID
        VALUES (:bid, :lot, :crop, :variety, :fid, :fname,
                :hdate, :qty, :unit, :grade, :loc,
                :cond, :exp, :certstatus, :certnum,
                :moisture, :testw, :notes, :status)
    """), {
        "bid":        bid,
        "lot":        lot_number,
        "crop":       payload.get("crop_name", ""),
        "variety":    payload.get("variety"),
        "fid":        payload.get("field_id"),
        "fname":      payload.get("field_name"),
        "hdate":      payload.get("harvest_date"),
        "qty":        payload.get("quantity", 0),
        "unit":       payload.get("unit", "lb"),
        "grade":      payload.get("grade_quality"),
        "loc":        payload.get("storage_location"),
        "cond":       payload.get("storage_condition"),
        "exp":        payload.get("expiry_date"),
        "certstatus": payload.get("certification_status"),
        "certnum":    payload.get("certificate_number"),
        "moisture":   payload.get("moisture_content"),
        "testw":      payload.get("test_weight"),
        "notes":      payload.get("notes"),
        "status":     payload.get("status", "in_storage"),
    }).fetchone()
    lot_id = row[0]

    for inp in payload.get("inputs", []):
        _insert_input_link(db, lot_id, bid, inp)

    db.commit()

    # Sync ActualYield to matching CropBudget
    try:
        harvest_year = int(str(payload.get("harvest_date", ""))[:4]) if payload.get("harvest_date") else date.today().year
        qty = float(payload.get("quantity", 0) or 0)
        crop = payload.get("crop_name", "")
        if qty > 0 and crop:
            db.execute(text("""
                UPDATE CropBudget
                SET ActualYield = ISNULL(ActualYield, 0) + :qty, UpdatedAt = GETDATE()
                WHERE BusinessID = :bid AND CropName = :crop AND CropYear = :yr
            """), {"qty": qty, "bid": bid, "crop": crop, "yr": harvest_year})
            db.commit()
    except Exception as _e:
        print(f"[harvest-lot] budget yield sync failed: {_e}")

    return {"lot_id": lot_id, "lot_number": lot_number}


@router.put("/lots/{lot_id}")
def update_lot(lot_id: int, payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    db.execute(text("""
        UPDATE HarvestLot SET
            CropName        = :crop,
            Variety         = :variety,
            FieldID         = :fid,
            FieldName       = :fname,
            HarvestDate     = :hdate,
            Quantity        = :qty,
            Unit            = :unit,
            GradeQuality    = :grade,
            StorageLocation = :loc,
            StorageCondition= :cond,
            ExpiryDate      = :exp,
            CertificationStatus = :certstatus,
            CertificateNumber   = :certnum,
            MoistureContent = :moisture,
            TestWeight      = :testw,
            Notes           = :notes,
            Status          = :status,
            UpdatedAt       = GETDATE()
        WHERE LotID = :id AND BusinessID = :bid
    """), {
        "id":       lot_id,
        "bid":      bid,
        "crop":     payload.get("crop_name"),
        "variety":  payload.get("variety"),
        "fid":      payload.get("field_id"),
        "fname":    payload.get("field_name"),
        "hdate":    payload.get("harvest_date"),
        "qty":      payload.get("quantity"),
        "unit":     payload.get("unit"),
        "grade":    payload.get("grade_quality"),
        "loc":      payload.get("storage_location"),
        "cond":     payload.get("storage_condition"),
        "exp":      payload.get("expiry_date"),
        "certstatus": payload.get("certification_status"),
        "certnum":  payload.get("certificate_number"),
        "moisture": payload.get("moisture_content"),
        "testw":    payload.get("test_weight"),
        "notes":    payload.get("notes"),
        "status":   payload.get("status"),
    })
    db.commit()
    return {"ok": True}


# ── Input Links (traceability) ────────────────────────────────────────────────

@router.post("/lots/{lot_id}/inputs")
def add_input_link(lot_id: int, payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    _insert_input_link(db, lot_id, bid, payload)
    db.commit()
    return {"ok": True}


@router.delete("/lots/{lot_id}/inputs/{link_id}")
def remove_input_link(lot_id: int, link_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM HarvestLotInput WHERE LinkID = :id AND LotID = :lid"), {"id": link_id, "lid": lot_id})
    db.commit()
    return {"ok": True}


# ── Movements ─────────────────────────────────────────────────────────────────

@router.post("/lots/{lot_id}/movements")
def record_movement(lot_id: int, payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    db.execute(text("""
        INSERT INTO HarvestLotMovement
            (LotID, BusinessID, MovementType, Quantity, FromLocation, ToLocation,
             ReferenceType, ReferenceID, Recipient, MovementDate, Notes)
        VALUES (:lid, :bid, :mtype, :qty, :from_, :to_, :rtype, :rid, :recip, :mdate, :notes)
    """), {
        "lid":   lot_id,
        "bid":   bid,
        "mtype": payload.get("movement_type", "transfer"),
        "qty":   payload.get("quantity", 0),
        "from_": payload.get("from_location"),
        "to_":   payload.get("to_location"),
        "rtype": payload.get("reference_type"),
        "rid":   payload.get("reference_id"),
        "recip": payload.get("recipient"),
        "mdate": payload.get("movement_date"),
        "notes": payload.get("notes"),
    })
    # Update storage location if transfer
    if payload.get("movement_type") == "transfer" and payload.get("to_location"):
        db.execute(
            text("UPDATE HarvestLot SET StorageLocation = :loc, UpdatedAt = GETDATE() WHERE LotID = :id"),
            {"loc": payload["to_location"], "id": lot_id},
        )
    # Update status if shipped
    if payload.get("movement_type") == "ship":
        db.execute(
            text("UPDATE HarvestLot SET Status = 'shipped', UpdatedAt = GETDATE() WHERE LotID = :id"),
            {"id": lot_id},
        )
    db.commit()
    return {"ok": True}


# ── QC ────────────────────────────────────────────────────────────────────────

@router.post("/lots/{lot_id}/qc")
def add_qc(lot_id: int, payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    db.execute(text("""
        INSERT INTO HarvestLotQC (LotID, BusinessID, InspectedBy, InspectionDate, Result, Grade, Notes)
        VALUES (:lid, :bid, :by, :date, :result, :grade, :notes)
    """), {
        "lid":    lot_id,
        "bid":    bid,
        "by":     payload.get("inspected_by"),
        "date":   payload.get("inspection_date"),
        "result": payload.get("result", "pass"),
        "grade":  payload.get("grade"),
        "notes":  payload.get("notes"),
    })
    if payload.get("grade"):
        db.execute(
            text("UPDATE HarvestLot SET GradeQuality = :grade, UpdatedAt = GETDATE() WHERE LotID = :id"),
            {"grade": payload["grade"], "id": lot_id},
        )
    db.commit()
    return {"ok": True}


# ── Trace Report ──────────────────────────────────────────────────────────────

@router.get("/lots/{lot_id}/trace")
def trace_report(lot_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    lot = db.execute(
        text("SELECT * FROM HarvestLot WHERE LotID = :id AND BusinessID = :bid"),
        {"id": lot_id, "bid": business_id},
    ).fetchone()
    if not lot:
        raise HTTPException(404, "Lot not found")

    inputs    = db.execute(text("SELECT * FROM HarvestLotInput WHERE LotID = :id ORDER BY ApplicationDate"), {"id": lot_id}).fetchall()
    movements = db.execute(text("SELECT * FROM HarvestLotMovement WHERE LotID = :id ORDER BY MovementDate"), {"id": lot_id}).fetchall()
    qc_records = db.execute(text("SELECT * FROM HarvestLotQC WHERE LotID = :id ORDER BY InspectionDate"), {"id": lot_id}).fetchall()

    return {
        "lot": _lot_row(lot),
        "inputs_applied": [_input_link_row(r) for r in inputs],
        "movements":      [_movement_row(r) for r in movements],
        "qc_inspections": [_qc_row(r) for r in qc_records],
        "trace_summary": {
            "total_inputs":    len(inputs),
            "total_movements": len(movements),
            "qc_pass":         sum(1 for r in qc_records if r.Result == "pass"),
            "qc_fail":         sum(1 for r in qc_records if r.Result == "fail"),
        },
    }


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary")
def lots_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    totals = db.execute(text("""
        SELECT
            COUNT(*) AS total_lots,
            SUM(CASE WHEN Status = 'in_storage' THEN 1 ELSE 0 END) AS in_storage,
            SUM(CASE WHEN Status = 'shipped' THEN 1 ELSE 0 END) AS shipped,
            SUM(CASE WHEN ExpiryDate IS NOT NULL AND ExpiryDate <= DATEADD(DAY, 30, GETDATE()) AND ExpiryDate >= GETDATE() THEN 1 ELSE 0 END) AS expiring_soon
        FROM HarvestLot WHERE BusinessID = :bid
    """), {"bid": business_id}).fetchone()

    by_crop = db.execute(text("""
        SELECT CropName, COUNT(*) AS lot_count, SUM(Quantity) AS total_qty, Unit
        FROM HarvestLot WHERE BusinessID = :bid AND Status = 'in_storage'
        GROUP BY CropName, Unit ORDER BY total_qty DESC
    """), {"bid": business_id}).fetchall()

    return {
        "total_lots":    totals.total_lots or 0,
        "in_storage":    totals.in_storage or 0,
        "shipped":       totals.shipped or 0,
        "expiring_soon": totals.expiring_soon or 0,
        "by_crop": [{"crop_name": r.CropName, "lot_count": r.lot_count,
                     "total_qty": float(r.total_qty or 0), "unit": r.Unit} for r in by_crop],
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _insert_input_link(db, lot_id, bid, inp: dict):
    db.execute(text("""
        INSERT INTO HarvestLotInput
            (LotID, BusinessID, InputID, InputName, InputCategory, Quantity,
             Unit, ApplicationDate, PreHarvestInterval, Notes)
        VALUES (:lid, :bid, :iid, :iname, :icat, :qty, :unit, :appdate, :phi, :notes)
    """), {
        "lid":     lot_id,
        "bid":     bid,
        "iid":     inp.get("input_id"),
        "iname":   inp.get("input_name", ""),
        "icat":    inp.get("input_category"),
        "qty":     inp.get("quantity"),
        "unit":    inp.get("unit"),
        "appdate": inp.get("application_date"),
        "phi":     inp.get("pre_harvest_interval"),
        "notes":   inp.get("notes"),
    })


def _lot_row(r) -> dict:
    return {
        "lot_id":               r.LotID,
        "business_id":          r.BusinessID,
        "lot_number":           r.LotNumber,
        "crop_name":            r.CropName,
        "variety":              r.Variety,
        "field_id":             r.FieldID,
        "field_name":           r.FieldName,
        "harvest_date":         r.HarvestDate.isoformat() if r.HarvestDate else None,
        "quantity":             float(r.Quantity),
        "unit":                 r.Unit,
        "grade_quality":        r.GradeQuality,
        "storage_location":     r.StorageLocation,
        "storage_condition":    r.StorageCondition,
        "expiry_date":          r.ExpiryDate.isoformat() if r.ExpiryDate else None,
        "certification_status": r.CertificationStatus,
        "certificate_number":   r.CertificateNumber,
        "moisture_content":     float(r.MoistureContent) if r.MoistureContent is not None else None,
        "test_weight":          float(r.TestWeight) if r.TestWeight is not None else None,
        "notes":                r.Notes,
        "status":               r.Status,
        "input_count":          getattr(r, "InputCount", 0),
        "created_at":           r.CreatedAt.isoformat() if r.CreatedAt else None,
    }


def _input_link_row(r) -> dict:
    return {
        "link_id":             r.LinkID,
        "input_id":            r.InputID,
        "input_name":          r.InputName,
        "input_category":      r.InputCategory,
        "quantity":            float(r.Quantity) if r.Quantity else None,
        "unit":                r.Unit,
        "application_date":    r.ApplicationDate.isoformat() if r.ApplicationDate else None,
        "pre_harvest_interval": r.PreHarvestInterval,
        "notes":               r.Notes,
    }


def _movement_row(r) -> dict:
    return {
        "movement_id":   r.MovementID,
        "movement_type": r.MovementType,
        "quantity":      float(r.Quantity),
        "from_location": r.FromLocation,
        "to_location":   r.ToLocation,
        "reference_type": r.ReferenceType,
        "reference_id":  r.ReferenceID,
        "recipient":     r.Recipient,
        "movement_date": r.MovementDate.isoformat() if r.MovementDate else None,
        "notes":         r.Notes,
        "created_at":    r.CreatedAt.isoformat() if r.CreatedAt else None,
    }


def _qc_row(r) -> dict:
    return {
        "qc_id":          r.QCID,
        "inspected_by":   r.InspectedBy,
        "inspection_date": r.InspectionDate.isoformat() if r.InspectionDate else None,
        "result":         r.Result,
        "grade":          r.Grade,
        "notes":          r.Notes,
        "created_at":     r.CreatedAt.isoformat() if r.CreatedAt else None,
    }
