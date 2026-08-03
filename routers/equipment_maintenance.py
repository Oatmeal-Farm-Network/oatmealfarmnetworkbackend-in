from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/equipment-maintenance", tags=["equipment_maintenance"])
_ddl_done = False

FUEL_TYPES = ["diesel", "petrol", "lpg", "electric", "hybrid"]
SERVICE_TYPES = ["oil_change", "filter_change", "grease_service", "tyre_rotation", "brake_service",
                 "hydraulic_service", "belt_replacement", "major_overhaul", "pre_season", "repair", "other"]


def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cur = db.cursor()
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OwnedEquipment')
    CREATE TABLE OwnedEquipment (
        EquipmentID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        EquipmentName NVARCHAR(150) NOT NULL,
        Make NVARCHAR(80),
        Model NVARCHAR(80),
        YearManufactured INT,
        SerialNumber NVARCHAR(80),
        RegistrationNumber NVARCHAR(60),
        FuelType NVARCHAR(20),
        CurrentHours DECIMAL(10,1),
        CurrentKm DECIMAL(10,1),
        PurchaseDate DATE,
        PurchasePrice DECIMAL(14,2),
        CurrentValue DECIMAL(14,2),
        NextServiceHours DECIMAL(10,1),
        NextServiceDate DATE,
        ServiceIntervalHours INT,
        ServiceIntervalDays INT,
        IsActive BIT NOT NULL DEFAULT 1,
        Notes NVARCHAR(500),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='EquipmentServiceRecord')
    CREATE TABLE EquipmentServiceRecord (
        ServiceID INT IDENTITY PRIMARY KEY,
        EquipmentID INT NOT NULL,
        BusinessID INT NOT NULL,
        ServiceDate DATE NOT NULL,
        ServiceType NVARCHAR(60) NOT NULL,
        HoursAtService DECIMAL(10,1),
        KmAtService DECIMAL(10,1),
        Description NVARCHAR(1000),
        PartsUsed NVARCHAR(500),
        PartsCost DECIMAL(12,2),
        LabourHours DECIMAL(6,2),
        LabourCost DECIMAL(12,2),
        TotalCost DECIMAL(12,2),
        PerformedBy NVARCHAR(150),
        NextServiceHours DECIMAL(10,1),
        NextServiceDate DATE,
        Notes NVARCHAR(500),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='EquipmentFuelLog')
    CREATE TABLE EquipmentFuelLog (
        FuelID INT IDENTITY PRIMARY KEY,
        EquipmentID INT NOT NULL,
        BusinessID INT NOT NULL,
        LogDate DATE NOT NULL,
        Litres DECIMAL(8,2) NOT NULL,
        CostPerLitre DECIMAL(8,4),
        TotalCost DECIMAL(10,2),
        HoursAtFill DECIMAL(10,1),
        KmAtFill DECIMAL(10,1),
        FuelType NVARCHAR(20),
        Supplier NVARCHAR(100),
        Notes NVARCHAR(300),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    db.commit()
    _ddl_done = True


class EquipmentIn(BaseModel):
    equipment_name: str
    make: Optional[str] = None
    model: Optional[str] = None
    year_manufactured: Optional[int] = None
    serial_number: Optional[str] = None
    registration_number: Optional[str] = None
    fuel_type: Optional[str] = None
    current_hours: Optional[float] = None
    current_km: Optional[float] = None
    purchase_date: Optional[date] = None
    purchase_price: Optional[float] = None
    current_value: Optional[float] = None
    service_interval_hours: Optional[int] = None
    service_interval_days: Optional[int] = None
    notes: Optional[str] = None


class ServiceIn(BaseModel):
    service_date: date
    service_type: str
    hours_at_service: Optional[float] = None
    km_at_service: Optional[float] = None
    description: Optional[str] = None
    parts_used: Optional[str] = None
    parts_cost: Optional[float] = None
    labour_hours: Optional[float] = None
    labour_cost: Optional[float] = None
    performed_by: Optional[str] = None
    next_service_hours: Optional[float] = None
    next_service_date: Optional[date] = None
    notes: Optional[str] = None


class FuelIn(BaseModel):
    log_date: date
    litres: float
    cost_per_litre: Optional[float] = None
    hours_at_fill: Optional[float] = None
    km_at_fill: Optional[float] = None
    fuel_type: Optional[str] = None
    supplier: Optional[str] = None
    notes: Optional[str] = None


@router.get("/fleet")
def list_fleet(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT e.*,
            (SELECT TOP 1 ServiceDate FROM EquipmentServiceRecord
             WHERE EquipmentID=e.EquipmentID ORDER BY ServiceDate DESC) AS LastServiceDate,
            (SELECT TOP 1 ServiceType FROM EquipmentServiceRecord
             WHERE EquipmentID=e.EquipmentID ORDER BY ServiceDate DESC) AS LastServiceType,
            (SELECT ROUND(SUM(Litres),1) FROM EquipmentFuelLog
             WHERE EquipmentID=e.EquipmentID
               AND LogDate >= DATEADD(day,-30,GETDATE())) AS FuelLitres30d,
            CASE
                WHEN e.NextServiceDate <= CAST(GETDATE() AS DATE) THEN 'overdue'
                WHEN e.NextServiceDate <= DATEADD(day,14,CAST(GETDATE() AS DATE)) THEN 'due_soon'
                WHEN e.NextServiceHours IS NOT NULL AND e.CurrentHours >= e.NextServiceHours - 50 THEN 'due_soon'
                ELSE 'ok'
            END AS ServiceStatus
        FROM OwnedEquipment e
        WHERE e.BusinessID=? ORDER BY e.EquipmentName
    """, [bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.post("/fleet", status_code=201)
def add_equipment(body: EquipmentIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        INSERT INTO OwnedEquipment
            (BusinessID,EquipmentName,Make,Model,YearManufactured,SerialNumber,RegistrationNumber,
             FuelType,CurrentHours,CurrentKm,PurchaseDate,PurchasePrice,CurrentValue,
             ServiceIntervalHours,ServiceIntervalDays,Notes)
        OUTPUT INSERTED.EquipmentID VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [bid, body.equipment_name, body.make, body.model, body.year_manufactured,
          body.serial_number, body.registration_number, body.fuel_type,
          body.current_hours, body.current_km,
          str(body.purchase_date) if body.purchase_date else None,
          body.purchase_price, body.current_value,
          body.service_interval_hours, body.service_interval_days, body.notes])
    eid = cur.fetchone()[0]
    db.commit()
    return {"equipment_id": eid}


@router.post("/fleet/{equipment_id}/service", status_code=201)
def log_service(equipment_id: int, body: ServiceIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT EquipmentID, ServiceIntervalHours, ServiceIntervalDays FROM OwnedEquipment WHERE EquipmentID=? AND BusinessID=?", [equipment_id, bid])
    equip = cur.fetchone()
    if not equip:
        raise HTTPException(404, "Equipment not found")
    total_cost = (body.parts_cost or 0) + (body.labour_cost or 0)
    next_h = body.next_service_hours
    next_d = body.next_service_date
    if next_h is None and body.hours_at_service and equip[1]:
        next_h = body.hours_at_service + equip[1]
    if next_d is None and equip[2]:
        from datetime import timedelta
        next_d = body.service_date + timedelta(days=equip[2])
    cur.execute("""
        INSERT INTO EquipmentServiceRecord
            (EquipmentID,BusinessID,ServiceDate,ServiceType,HoursAtService,KmAtService,
             Description,PartsUsed,PartsCost,LabourHours,LabourCost,TotalCost,
             PerformedBy,NextServiceHours,NextServiceDate,Notes)
        OUTPUT INSERTED.ServiceID VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [equipment_id, bid, str(body.service_date), body.service_type,
          body.hours_at_service, body.km_at_service, body.description, body.parts_used,
          body.parts_cost, body.labour_hours, body.labour_cost, total_cost or None,
          body.performed_by, next_h,
          str(next_d) if next_d else None, body.notes])
    sid = cur.fetchone()[0]
    if body.hours_at_service:
        cur.execute("UPDATE OwnedEquipment SET CurrentHours=ISNULL(?,CurrentHours), NextServiceHours=ISNULL(?,NextServiceHours), NextServiceDate=ISNULL(?,NextServiceDate) WHERE EquipmentID=?",
                    [body.hours_at_service, next_h, str(next_d) if next_d else None, equipment_id])
    db.commit()
    return {"service_id": sid, "next_service_hours": next_h, "next_service_date": str(next_d) if next_d else None}


@router.get("/fleet/{equipment_id}/service")
def equipment_service_history(equipment_id: int, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT * FROM EquipmentServiceRecord WHERE EquipmentID=? AND BusinessID=? ORDER BY ServiceDate DESC", [equipment_id, bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.post("/fleet/{equipment_id}/fuel", status_code=201)
def log_fuel(equipment_id: int, body: FuelIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT EquipmentID FROM OwnedEquipment WHERE EquipmentID=? AND BusinessID=?", [equipment_id, bid])
    if not cur.fetchone():
        raise HTTPException(404, "Equipment not found")
    total = round(body.litres * body.cost_per_litre, 2) if body.cost_per_litre else None
    cur.execute("""
        INSERT INTO EquipmentFuelLog
            (EquipmentID,BusinessID,LogDate,Litres,CostPerLitre,TotalCost,HoursAtFill,KmAtFill,FuelType,Supplier,Notes)
        OUTPUT INSERTED.FuelID VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, [equipment_id, bid, str(body.log_date), body.litres, body.cost_per_litre, total,
          body.hours_at_fill, body.km_at_fill, body.fuel_type, body.supplier, body.notes])
    fid = cur.fetchone()[0]
    if body.hours_at_fill:
        cur.execute("UPDATE OwnedEquipment SET CurrentHours=? WHERE EquipmentID=? AND (CurrentHours IS NULL OR CurrentHours < ?)",
                    [body.hours_at_fill, equipment_id, body.hours_at_fill])
    db.commit()
    return {"fuel_id": fid, "total_cost": total}


@router.get("/fleet/{equipment_id}/fuel")
def equipment_fuel_history(equipment_id: int, days: int = 90, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT * FROM EquipmentFuelLog WHERE EquipmentID=? AND BusinessID=? AND LogDate >= DATEADD(day,-?,GETDATE()) ORDER BY LogDate DESC",
                [equipment_id, bid, days])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/dashboard")
def dashboard(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT COUNT(*) AS TotalEquipment,
               SUM(CASE WHEN NextServiceDate <= CAST(GETDATE() AS DATE) THEN 1 ELSE 0 END) AS Overdue,
               SUM(CASE WHEN NextServiceDate BETWEEN CAST(GETDATE() AS DATE) AND DATEADD(day,14,CAST(GETDATE() AS DATE)) THEN 1 ELSE 0 END) AS DueSoon
        FROM OwnedEquipment WHERE BusinessID=? AND IsActive=1
    """, [bid])
    row = cur.fetchone()
    counts = {"total": row[0], "overdue": row[1], "due_soon": row[2]}
    cur.execute("""
        SELECT ROUND(SUM(TotalCost),2) AS ServiceCost90d FROM EquipmentServiceRecord
        WHERE BusinessID=? AND ServiceDate >= DATEADD(day,-90,GETDATE())
    """, [bid])
    service_cost = cur.fetchone()[0]
    cur.execute("""
        SELECT ROUND(SUM(TotalCost),2) AS FuelCost30d FROM EquipmentFuelLog
        WHERE BusinessID=? AND LogDate >= DATEADD(day,-30,GETDATE())
    """, [bid])
    fuel_cost = cur.fetchone()[0]
    return {"counts": counts, "service_cost_90d": float(service_cost or 0), "fuel_cost_30d": float(fuel_cost or 0)}


@router.get("/due-alerts")
def due_alerts(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    """Equipment overdue or due within 14 days / 50 hours."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT EquipmentID, EquipmentName, Make, Model, CurrentHours, NextServiceHours, NextServiceDate,
               CASE
                   WHEN NextServiceDate <= CAST(GETDATE() AS DATE) THEN 'overdue'
                   WHEN NextServiceDate <= DATEADD(day,14,CAST(GETDATE() AS DATE)) THEN 'due_soon'
                   WHEN NextServiceHours IS NOT NULL AND CurrentHours >= NextServiceHours - 50 THEN 'due_soon'
                   ELSE 'ok'
               END AS Status
        FROM OwnedEquipment
        WHERE BusinessID=? AND IsActive=1
          AND (NextServiceDate <= DATEADD(day,14,CAST(GETDATE() AS DATE))
               OR (NextServiceHours IS NOT NULL AND CurrentHours >= NextServiceHours - 50))
        ORDER BY NextServiceDate ASC
    """, [bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
