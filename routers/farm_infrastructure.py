from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional

router = APIRouter(prefix="/api/farm-infrastructure", tags=["farm_infrastructure"])

_tables_ready = False


def _ensure_tables(db: Session):
    global _tables_ready
    if _tables_ready:
        return

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FarmAsset')
        CREATE TABLE FarmAsset (
            AssetID         INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL,
            AssetName       NVARCHAR(200) NOT NULL,
            AssetType       NVARCHAR(50)  NOT NULL DEFAULT 'equipment',
            Category        NVARCHAR(100) NULL,
            Make            NVARCHAR(100) NULL,
            Model           NVARCHAR(100) NULL,
            Year            INT           NULL,
            SerialNumber    NVARCHAR(100) NULL,
            PurchaseDate    DATE          NULL,
            PurchasePrice   DECIMAL(14,2) NULL,
            CurrentValue    DECIMAL(14,2) NULL,
            DepreciationRate DECIMAL(5,2) NULL,
            Location        NVARCHAR(200) NULL,
            Status          NVARCHAR(30)  NOT NULL DEFAULT 'active',
            WarrantyExpiry  DATE          NULL,
            InsurancePolicy NVARCHAR(100) NULL,
            InsuranceExpiry DATE          NULL,
            PhotoURL        NVARCHAR(500) NULL,
            Notes           NVARCHAR(1000) NULL,
            IsActive        BIT           NOT NULL DEFAULT 1,
            CreatedAt       DATETIME2     DEFAULT GETDATE(),
            UpdatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FarmMaintenanceLog')
        CREATE TABLE FarmMaintenanceLog (
            LogID           INT IDENTITY PRIMARY KEY,
            AssetID         INT           NOT NULL,
            BusinessID      INT           NOT NULL,
            MaintenanceType NVARCHAR(50)  NOT NULL DEFAULT 'routine',
            Description     NVARCHAR(500) NOT NULL,
            PerformedBy     NVARCHAR(200) NULL,
            PerformedDate   DATE          NOT NULL,
            Cost            DECIMAL(10,2) NULL,
            HoursLogged     DECIMAL(7,2)  NULL,
            OdometerHours   DECIMAL(10,1) NULL,
            NextDueDate     DATE          NULL,
            NextDueHours    DECIMAL(10,1) NULL,
            PartsUsed       NVARCHAR(500) NULL,
            Status          NVARCHAR(20)  NOT NULL DEFAULT 'completed',
            Notes           NVARCHAR(1000) NULL,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FarmMaintenanceSchedule')
        CREATE TABLE FarmMaintenanceSchedule (
            ScheduleID      INT IDENTITY PRIMARY KEY,
            AssetID         INT           NOT NULL,
            BusinessID      INT           NOT NULL,
            TaskName        NVARCHAR(200) NOT NULL,
            FrequencyType   NVARCHAR(20)  NOT NULL DEFAULT 'days',
            FrequencyValue  INT           NOT NULL DEFAULT 90,
            LastCompletedDate DATE        NULL,
            NextDueDate     DATE          NULL,
            EstimatedCost   DECIMAL(10,2) NULL,
            AssignedTo      NVARCHAR(200) NULL,
            IsActive        BIT           NOT NULL DEFAULT 1,
            Notes           NVARCHAR(500) NULL,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FarmStructure')
        CREATE TABLE FarmStructure (
            StructureID     INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL,
            StructureName   NVARCHAR(200) NOT NULL,
            StructureType   NVARCHAR(100) NOT NULL,
            Capacity        DECIMAL(12,2) NULL,
            CapacityUnit    NVARCHAR(50)  NULL,
            SquareFootage   DECIMAL(10,2) NULL,
            BuiltYear       INT           NULL,
            Condition       NVARCHAR(30)  NULL DEFAULT 'good',
            LastInspected   DATE          NULL,
            InsuranceValue  DECIMAL(14,2) NULL,
            Location        NVARCHAR(300) NULL,
            Notes           NVARCHAR(1000) NULL,
            IsActive        BIT           NOT NULL DEFAULT 1,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.commit()
    _tables_ready = True


# ── Assets CRUD ───────────────────────────────────────────────────────────────

@router.get("/assets")
def list_assets(
    business_id: int = Query(...),
    asset_type: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    q = """
        SELECT a.AssetID, a.BusinessID, a.AssetName, a.AssetType, a.Category,
               a.Make, a.Model, a.Year, a.SerialNumber, a.PurchaseDate,
               a.PurchasePrice, a.CurrentValue, a.DepreciationRate, a.Location,
               a.Status, a.WarrantyExpiry, a.InsurancePolicy, a.InsuranceExpiry,
               a.PhotoURL, a.Notes, a.IsActive, a.CreatedAt, a.UpdatedAt,
               (SELECT MAX(PerformedDate) FROM FarmMaintenanceLog
                WHERE AssetID = a.AssetID) AS LastMaintenanceDate,
               (SELECT MIN(NextDueDate) FROM FarmMaintenanceSchedule
                WHERE AssetID = a.AssetID AND IsActive = 1 AND NextDueDate IS NOT NULL) AS NextMaintenanceDue
        FROM FarmAsset a
        WHERE a.BusinessID = :bid AND a.IsActive = 1
    """
    params: dict = {"bid": business_id}
    if asset_type:
        q += " AND a.AssetType = :at"
        params["at"] = asset_type
    if status:
        q += " AND a.Status = :st"
        params["st"] = status
    q += " ORDER BY a.AssetType, a.AssetName"
    rows = db.execute(text(q), params).fetchall()
    return [_asset_row(r) for r in rows]


@router.get("/assets/{asset_id}")
def get_asset(asset_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    row = db.execute(
        text("""
            SELECT a.*,
                   (SELECT MAX(PerformedDate) FROM FarmMaintenanceLog WHERE AssetID = a.AssetID) AS LastMaintenanceDate,
                   (SELECT MIN(NextDueDate) FROM FarmMaintenanceSchedule WHERE AssetID = a.AssetID AND IsActive = 1 AND NextDueDate IS NOT NULL) AS NextMaintenanceDue
            FROM FarmAsset a WHERE a.AssetID = :id AND a.BusinessID = :bid
        """),
        {"id": asset_id, "bid": business_id},
    ).fetchone()
    if not row:
        raise HTTPException(404, "Asset not found")
    logs = db.execute(text("SELECT * FROM FarmMaintenanceLog WHERE AssetID = :id ORDER BY PerformedDate DESC"), {"id": asset_id}).fetchall()
    schedules = db.execute(text("SELECT * FROM FarmMaintenanceSchedule WHERE AssetID = :id AND IsActive = 1 ORDER BY NextDueDate"), {"id": asset_id}).fetchall()
    result = _asset_row(row)
    result["maintenance_logs"]     = [_log_row(l) for l in logs]
    result["maintenance_schedules"] = [_schedule_row(s) for s in schedules]
    return result


@router.post("/assets")
def create_asset(payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    if not bid:
        raise HTTPException(400, "business_id required")
    row = db.execute(text("""
        INSERT INTO FarmAsset
            (BusinessID, AssetName, AssetType, Category, Make, Model, Year,
             SerialNumber, PurchaseDate, PurchasePrice, CurrentValue,
             DepreciationRate, Location, Status, WarrantyExpiry,
             InsurancePolicy, InsuranceExpiry, PhotoURL, Notes)
        OUTPUT INSERTED.AssetID
        VALUES (:bid, :name, :atype, :cat, :make, :model, :yr,
                :serial, :pdate, :pprice, :cval,
                :depr, :loc, :status, :warranty,
                :inspol, :insexp, :photo, :notes)
    """), {
        "bid":     bid,
        "name":    payload.get("asset_name", ""),
        "atype":   payload.get("asset_type", "equipment"),
        "cat":     payload.get("category"),
        "make":    payload.get("make"),
        "model":   payload.get("model"),
        "yr":      payload.get("year"),
        "serial":  payload.get("serial_number"),
        "pdate":   payload.get("purchase_date"),
        "pprice":  payload.get("purchase_price"),
        "cval":    payload.get("current_value"),
        "depr":    payload.get("depreciation_rate"),
        "loc":     payload.get("location"),
        "status":  payload.get("status", "active"),
        "warranty": payload.get("warranty_expiry"),
        "inspol":  payload.get("insurance_policy"),
        "insexp":  payload.get("insurance_expiry"),
        "photo":   payload.get("photo_url"),
        "notes":   payload.get("notes"),
    }).fetchone()
    db.commit()
    return {"asset_id": row[0]}


@router.put("/assets/{asset_id}")
def update_asset(asset_id: int, payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    db.execute(text("""
        UPDATE FarmAsset SET
            AssetName       = :name,
            AssetType       = :atype,
            Category        = :cat,
            Make            = :make,
            Model           = :model,
            Year            = :yr,
            SerialNumber    = :serial,
            PurchaseDate    = :pdate,
            PurchasePrice   = :pprice,
            CurrentValue    = :cval,
            DepreciationRate= :depr,
            Location        = :loc,
            Status          = :status,
            WarrantyExpiry  = :warranty,
            InsurancePolicy = :inspol,
            InsuranceExpiry = :insexp,
            PhotoURL        = :photo,
            Notes           = :notes,
            UpdatedAt       = GETDATE()
        WHERE AssetID = :id AND BusinessID = :bid
    """), {
        "id":     asset_id,
        "bid":    bid,
        "name":   payload.get("asset_name"),
        "atype":  payload.get("asset_type"),
        "cat":    payload.get("category"),
        "make":   payload.get("make"),
        "model":  payload.get("model"),
        "yr":     payload.get("year"),
        "serial": payload.get("serial_number"),
        "pdate":  payload.get("purchase_date"),
        "pprice": payload.get("purchase_price"),
        "cval":   payload.get("current_value"),
        "depr":   payload.get("depreciation_rate"),
        "loc":    payload.get("location"),
        "status": payload.get("status"),
        "warranty": payload.get("warranty_expiry"),
        "inspol": payload.get("insurance_policy"),
        "insexp": payload.get("insurance_expiry"),
        "photo":  payload.get("photo_url"),
        "notes":  payload.get("notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(
        text("UPDATE FarmAsset SET IsActive = 0 WHERE AssetID = :id AND BusinessID = :bid"),
        {"id": asset_id, "bid": business_id},
    )
    db.commit()
    return {"ok": True}


# ── Maintenance Logs ──────────────────────────────────────────────────────────

@router.get("/maintenance")
def list_maintenance(
    business_id: int = Query(...),
    asset_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    q = """
        SELECT l.*, a.AssetName
        FROM FarmMaintenanceLog l
        JOIN FarmAsset a ON a.AssetID = l.AssetID
        WHERE l.BusinessID = :bid
    """
    params: dict = {"bid": business_id}
    if asset_id:
        q += " AND l.AssetID = :aid"
        params["aid"] = asset_id
    q += " ORDER BY l.PerformedDate DESC"
    rows = db.execute(text(q), params).fetchall()
    return [_log_row(r) for r in rows]


@router.post("/maintenance")
def log_maintenance(payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    asset_id = payload.get("asset_id")
    db.execute(text("""
        INSERT INTO FarmMaintenanceLog
            (AssetID, BusinessID, MaintenanceType, Description, PerformedBy,
             PerformedDate, Cost, HoursLogged, OdometerHours, NextDueDate,
             NextDueHours, PartsUsed, Status, Notes)
        VALUES (:aid, :bid, :mtype, :desc, :by,
                :date, :cost, :hours, :odometer, :nextdate,
                :nexthours, :parts, :status, :notes)
    """), {
        "aid":       asset_id,
        "bid":       bid,
        "mtype":     payload.get("maintenance_type", "routine"),
        "desc":      payload.get("description", ""),
        "by":        payload.get("performed_by"),
        "date":      payload.get("performed_date"),
        "cost":      payload.get("cost"),
        "hours":     payload.get("hours_logged"),
        "odometer":  payload.get("odometer_hours"),
        "nextdate":  payload.get("next_due_date"),
        "nexthours": payload.get("next_due_hours"),
        "parts":     payload.get("parts_used"),
        "status":    payload.get("status", "completed"),
        "notes":     payload.get("notes"),
    })
    # Update schedule if there's a matching one
    if payload.get("schedule_id"):
        db.execute(text("""
            UPDATE FarmMaintenanceSchedule SET
                LastCompletedDate = :date,
                NextDueDate = :nextdate
            WHERE ScheduleID = :sid
        """), {
            "date":    payload.get("performed_date"),
            "nextdate": payload.get("next_due_date"),
            "sid":     payload["schedule_id"],
        })
    db.commit()
    return {"ok": True}


# ── Maintenance Schedules ─────────────────────────────────────────────────────

@router.get("/schedules")
def list_schedules(business_id: int = Query(...), overdue_only: bool = False, db: Session = Depends(get_db)):
    _ensure_tables(db)
    q = """
        SELECT s.*, a.AssetName
        FROM FarmMaintenanceSchedule s
        JOIN FarmAsset a ON a.AssetID = s.AssetID
        WHERE s.BusinessID = :bid AND s.IsActive = 1
    """
    params: dict = {"bid": business_id}
    if overdue_only:
        q += " AND s.NextDueDate < GETDATE()"
    q += " ORDER BY s.NextDueDate"
    rows = db.execute(text(q), params).fetchall()
    return [_schedule_row(r) for r in rows]


@router.post("/schedules")
def create_schedule(payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    db.execute(text("""
        INSERT INTO FarmMaintenanceSchedule
            (AssetID, BusinessID, TaskName, FrequencyType, FrequencyValue,
             LastCompletedDate, NextDueDate, EstimatedCost, AssignedTo, Notes)
        VALUES (:aid, :bid, :task, :ftype, :fval, :last, :next, :cost, :assigned, :notes)
    """), {
        "aid":      payload.get("asset_id"),
        "bid":      bid,
        "task":     payload.get("task_name", ""),
        "ftype":    payload.get("frequency_type", "days"),
        "fval":     payload.get("frequency_value", 90),
        "last":     payload.get("last_completed_date"),
        "next":     payload.get("next_due_date"),
        "cost":     payload.get("estimated_cost"),
        "assigned": payload.get("assigned_to"),
        "notes":    payload.get("notes"),
    })
    db.commit()
    return {"ok": True}


# ── Structures ────────────────────────────────────────────────────────────────

@router.get("/structures")
def list_structures(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT * FROM FarmStructure WHERE BusinessID = :bid AND IsActive = 1
        ORDER BY StructureType, StructureName
    """), {"bid": business_id}).fetchall()
    return [_structure_row(r) for r in rows]


@router.post("/structures")
def create_structure(payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    db.execute(text("""
        INSERT INTO FarmStructure
            (BusinessID, StructureName, StructureType, Capacity, CapacityUnit,
             SquareFootage, BuiltYear, Condition, LastInspected,
             InsuranceValue, Location, Notes)
        VALUES (:bid, :name, :stype, :cap, :capunit,
                :sqft, :yr, :cond, :inspected,
                :insval, :loc, :notes)
    """), {
        "bid":      bid,
        "name":     payload.get("structure_name", ""),
        "stype":    payload.get("structure_type", "barn"),
        "cap":      payload.get("capacity"),
        "capunit":  payload.get("capacity_unit"),
        "sqft":     payload.get("square_footage"),
        "yr":       payload.get("built_year"),
        "cond":     payload.get("condition", "good"),
        "inspected": payload.get("last_inspected"),
        "insval":   payload.get("insurance_value"),
        "loc":      payload.get("location"),
        "notes":    payload.get("notes"),
    })
    db.commit()
    return {"ok": True}


@router.put("/structures/{structure_id}")
def update_structure(structure_id: int, payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    db.execute(text("""
        UPDATE FarmStructure SET
            StructureName  = :name,
            StructureType  = :stype,
            Capacity       = :cap,
            CapacityUnit   = :capunit,
            SquareFootage  = :sqft,
            BuiltYear      = :yr,
            Condition      = :cond,
            LastInspected  = :inspected,
            InsuranceValue = :insval,
            Location       = :loc,
            Notes          = :notes
        WHERE StructureID = :id AND BusinessID = :bid
    """), {
        "id":       structure_id,
        "bid":      bid,
        "name":     payload.get("structure_name"),
        "stype":    payload.get("structure_type"),
        "cap":      payload.get("capacity"),
        "capunit":  payload.get("capacity_unit"),
        "sqft":     payload.get("square_footage"),
        "yr":       payload.get("built_year"),
        "cond":     payload.get("condition"),
        "inspected": payload.get("last_inspected"),
        "insval":   payload.get("insurance_value"),
        "loc":      payload.get("location"),
        "notes":    payload.get("notes"),
    })
    db.commit()
    return {"ok": True}


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary")
def infra_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)

    assets = db.execute(text("""
        SELECT
            COUNT(*) AS total_assets,
            SUM(CASE WHEN Status = 'active' THEN 1 ELSE 0 END) AS active_assets,
            SUM(CASE WHEN Status = 'needs_repair' THEN 1 ELSE 0 END) AS needs_repair,
            SUM(ISNULL(CurrentValue, 0)) AS total_asset_value,
            SUM(CASE WHEN WarrantyExpiry IS NOT NULL AND WarrantyExpiry <= DATEADD(DAY, 90, GETDATE()) AND WarrantyExpiry >= GETDATE() THEN 1 ELSE 0 END) AS warranty_expiring
        FROM FarmAsset WHERE BusinessID = :bid AND IsActive = 1
    """), {"bid": business_id}).fetchone()

    overdue_maintenance = db.execute(text("""
        SELECT COUNT(*) FROM FarmMaintenanceSchedule
        WHERE BusinessID = :bid AND IsActive = 1 AND NextDueDate < GETDATE()
    """), {"bid": business_id}).scalar() or 0

    upcoming_maintenance = db.execute(text("""
        SELECT COUNT(*) FROM FarmMaintenanceSchedule
        WHERE BusinessID = :bid AND IsActive = 1
          AND NextDueDate BETWEEN GETDATE() AND DATEADD(DAY, 30, GETDATE())
    """), {"bid": business_id}).scalar() or 0

    structures = db.execute(text("""
        SELECT COUNT(*) AS cnt, SUM(ISNULL(InsuranceValue, 0)) AS ins_value
        FROM FarmStructure WHERE BusinessID = :bid AND IsActive = 1
    """), {"bid": business_id}).fetchone()

    return {
        "total_assets":         assets.total_assets or 0,
        "active_assets":        assets.active_assets or 0,
        "needs_repair":         assets.needs_repair or 0,
        "total_asset_value":    float(assets.total_asset_value or 0),
        "warranty_expiring":    assets.warranty_expiring or 0,
        "overdue_maintenance":  overdue_maintenance,
        "upcoming_maintenance": upcoming_maintenance,
        "total_structures":     structures.cnt or 0,
        "total_insurance_value": float(structures.ins_value or 0),
    }


# ── Serializers ───────────────────────────────────────────────────────────────

def _asset_row(r) -> dict:
    return {
        "asset_id":          r.AssetID,
        "business_id":       r.BusinessID,
        "asset_name":        r.AssetName,
        "asset_type":        r.AssetType,
        "category":          r.Category,
        "make":              r.Make,
        "model":             r.Model,
        "year":              r.Year,
        "serial_number":     r.SerialNumber,
        "purchase_date":     r.PurchaseDate.isoformat() if r.PurchaseDate else None,
        "purchase_price":    float(r.PurchasePrice) if r.PurchasePrice is not None else None,
        "current_value":     float(r.CurrentValue) if r.CurrentValue is not None else None,
        "depreciation_rate": float(r.DepreciationRate) if r.DepreciationRate is not None else None,
        "location":          r.Location,
        "status":            r.Status,
        "warranty_expiry":   r.WarrantyExpiry.isoformat() if r.WarrantyExpiry else None,
        "insurance_policy":  r.InsurancePolicy,
        "insurance_expiry":  r.InsuranceExpiry.isoformat() if r.InsuranceExpiry else None,
        "photo_url":         r.PhotoURL,
        "notes":             r.Notes,
        "last_maintenance_date": getattr(r, "LastMaintenanceDate", None) and r.LastMaintenanceDate.isoformat(),
        "next_maintenance_due":  getattr(r, "NextMaintenanceDue", None) and r.NextMaintenanceDue.isoformat(),
        "created_at":        r.CreatedAt.isoformat() if r.CreatedAt else None,
    }


def _log_row(r) -> dict:
    return {
        "log_id":           r.LogID,
        "asset_id":         r.AssetID,
        "asset_name":       getattr(r, "AssetName", None),
        "maintenance_type": r.MaintenanceType,
        "description":      r.Description,
        "performed_by":     r.PerformedBy,
        "performed_date":   r.PerformedDate.isoformat() if r.PerformedDate else None,
        "cost":             float(r.Cost) if r.Cost is not None else None,
        "hours_logged":     float(r.HoursLogged) if r.HoursLogged is not None else None,
        "odometer_hours":   float(r.OdometerHours) if r.OdometerHours is not None else None,
        "next_due_date":    r.NextDueDate.isoformat() if r.NextDueDate else None,
        "parts_used":       r.PartsUsed,
        "status":           r.Status,
        "notes":            r.Notes,
        "created_at":       r.CreatedAt.isoformat() if r.CreatedAt else None,
    }


def _schedule_row(r) -> dict:
    return {
        "schedule_id":        r.ScheduleID,
        "asset_id":           r.AssetID,
        "asset_name":         getattr(r, "AssetName", None),
        "task_name":          r.TaskName,
        "frequency_type":     r.FrequencyType,
        "frequency_value":    r.FrequencyValue,
        "last_completed_date": r.LastCompletedDate.isoformat() if r.LastCompletedDate else None,
        "next_due_date":      r.NextDueDate.isoformat() if r.NextDueDate else None,
        "estimated_cost":     float(r.EstimatedCost) if r.EstimatedCost is not None else None,
        "assigned_to":        r.AssignedTo,
        "is_overdue":         bool(r.NextDueDate and r.NextDueDate.date() < __import__("datetime").date.today()) if r.NextDueDate else False,
    }


def _structure_row(r) -> dict:
    return {
        "structure_id":    r.StructureID,
        "business_id":     r.BusinessID,
        "structure_name":  r.StructureName,
        "structure_type":  r.StructureType,
        "capacity":        float(r.Capacity) if r.Capacity is not None else None,
        "capacity_unit":   r.CapacityUnit,
        "square_footage":  float(r.SquareFootage) if r.SquareFootage is not None else None,
        "built_year":      r.BuiltYear,
        "condition":       r.Condition,
        "last_inspected":  r.LastInspected.isoformat() if r.LastInspected else None,
        "insurance_value": float(r.InsuranceValue) if r.InsuranceValue is not None else None,
        "location":        r.Location,
        "notes":           r.Notes,
    }
