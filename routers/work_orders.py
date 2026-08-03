"""
routers/work_orders.py
Work Orders for field crews — task dispatching, real-time labor + machinery + materials tracking,
greenhouse environmental controls.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional
from routers.rbac import record_audit
from routers.notifications import notify_business

router = APIRouter(prefix="/api/work-orders", tags=["work_orders"])
_ready = False


def _ensure(db: Session):
    global _ready
    if _ready:
        return
    stmts = [
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='WorkOrder')
        CREATE TABLE WorkOrder (
            WOID             INT IDENTITY PRIMARY KEY,
            BusinessID       INT NOT NULL,
            FieldID          INT NULL,
            Location         NVARCHAR(300) NULL,
            TaskType         NVARCHAR(100) NOT NULL,
            Title            NVARCHAR(300) NOT NULL,
            Description      NVARCHAR(MAX) NULL,
            Priority         NVARCHAR(20) NOT NULL DEFAULT 'normal',
            Status           NVARCHAR(50) NOT NULL DEFAULT 'open',
            AssignedTo       NVARCHAR(300) NULL,
            AssignedDate     DATE NULL,
            DueDate          DATE NULL,
            CompletedDate    DATE NULL,
            EstimatedHours   DECIMAL(8,2) NULL,
            ActualHours      DECIMAL(8,2) NULL,
            EstimatedCost    DECIMAL(12,2) NULL,
            ActualCost       DECIMAL(12,2) NULL,
            Notes            NVARCHAR(MAX) NULL,
            CreatedAt        DATETIME2 DEFAULT GETDATE(),
            UpdatedAt        DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='WorkOrderLabor')
        CREATE TABLE WorkOrderLabor (
            LaborID      INT IDENTITY PRIMARY KEY,
            WOID         INT NOT NULL,
            WorkerName   NVARCHAR(200) NOT NULL,
            EmployeeID   INT NULL,
            WorkDate     DATE NOT NULL,
            HoursWorked  DECIMAL(8,2) NOT NULL,
            HourlyRate   DECIMAL(10,2) NULL,
            TotalCost    DECIMAL(12,2) NULL,
            Notes        NVARCHAR(MAX) NULL,
            CreatedAt    DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='WorkOrderMachinery')
        CREATE TABLE WorkOrderMachinery (
            MachineLogID  INT IDENTITY PRIMARY KEY,
            WOID          INT NOT NULL,
            MachineName   NVARCHAR(200) NOT NULL,
            AssetID       INT NULL,
            UsageDate     DATE NOT NULL,
            HoursUsed     DECIMAL(8,2) NULL,
            FuelUsed      DECIMAL(10,2) NULL,
            FuelUnit      NVARCHAR(20)  NULL DEFAULT 'liters',
            CostPerHour   DECIMAL(10,2) NULL,
            TotalCost     DECIMAL(12,2) NULL,
            Notes         NVARCHAR(MAX) NULL,
            CreatedAt     DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='WorkOrderMaterial')
        CREATE TABLE WorkOrderMaterial (
            MaterialID   INT IDENTITY PRIMARY KEY,
            WOID         INT NOT NULL,
            MaterialName NVARCHAR(300) NOT NULL,
            Category     NVARCHAR(100) NULL,
            Quantity     DECIMAL(12,3) NOT NULL,
            Unit         NVARCHAR(50)  NULL,
            UnitCost     DECIMAL(10,2) NULL,
            TotalCost    DECIMAL(12,2) NULL,
            FarmInputID  INT NULL,
            Notes        NVARCHAR(MAX) NULL,
            CreatedAt    DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='GreenhouseReading')
        CREATE TABLE GreenhouseReading (
            ReadingID        INT IDENTITY PRIMARY KEY,
            BusinessID       INT NOT NULL,
            GreenhouseName   NVARCHAR(200) NOT NULL,
            ReadingTime      DATETIME2 NOT NULL DEFAULT GETDATE(),
            TempCelsius      DECIMAL(6,2) NULL,
            HumidityPct      DECIMAL(5,2) NULL,
            CO2PPM           INT NULL,
            LightLux         INT NULL,
            SoilMoisturePct  DECIMAL(5,2) NULL,
            IrrigationOn     BIT NULL,
            HeatingOn        BIT NULL,
            VentilationOn    BIT NULL,
            Notes            NVARCHAR(MAX) NULL,
            CreatedAt        DATETIME2 DEFAULT GETDATE()
        )""",
    ]
    for s in stmts:
        try:
            db.execute(text(s))
            db.commit()
        except Exception:
            db.rollback()
    _ready = True


def _update_cost(wo_id: int, db: Session):
    labor = db.execute(text("SELECT ISNULL(SUM(TotalCost),0) FROM WorkOrderLabor WHERE WOID=:wid"), {"wid": wo_id}).scalar()
    machinery = db.execute(text("SELECT ISNULL(SUM(TotalCost),0) FROM WorkOrderMachinery WHERE WOID=:wid"), {"wid": wo_id}).scalar()
    materials = db.execute(text("SELECT ISNULL(SUM(TotalCost),0) FROM WorkOrderMaterial WHERE WOID=:wid"), {"wid": wo_id}).scalar()
    db.execute(text("UPDATE WorkOrder SET ActualCost=:c, UpdatedAt=GETDATE() WHERE WOID=:wid"),
               {"c": float(labor)+float(machinery)+float(materials), "wid": wo_id})


# ─── Work Orders ─────────────────────────────────────────────────────────────

@router.get("")
def list_work_orders(business_id: int = Query(...), status: Optional[str] = None,
                     task_type: Optional[str] = None, db: Session = Depends(get_db)):
    _ensure(db)
    q = "SELECT * FROM WorkOrder WHERE BusinessID=:bid"
    params = {"bid": business_id}
    if status:
        q += " AND Status=:st"; params["st"] = status
    if task_type:
        q += " AND TaskType=:tt"; params["tt"] = task_type
    q += " ORDER BY DueDate ASC, Priority DESC"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/{wo_id}")
def get_work_order(wo_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    wo = db.execute(text("SELECT * FROM WorkOrder WHERE WOID=:wid AND BusinessID=:bid"),
                    {"wid": wo_id, "bid": business_id}).fetchone()
    if not wo:
        raise HTTPException(404, "Work order not found")
    labor = db.execute(text("SELECT * FROM WorkOrderLabor WHERE WOID=:wid ORDER BY WorkDate DESC"), {"wid": wo_id}).fetchall()
    machinery = db.execute(text("SELECT * FROM WorkOrderMachinery WHERE WOID=:wid ORDER BY UsageDate DESC"), {"wid": wo_id}).fetchall()
    materials = db.execute(text("SELECT * FROM WorkOrderMaterial WHERE WOID=:wid"), {"wid": wo_id}).fetchall()
    return {
        "work_order": dict(wo._mapping),
        "labor": [dict(r._mapping) for r in labor],
        "machinery": [dict(r._mapping) for r in machinery],
        "materials": [dict(r._mapping) for r in materials],
    }


@router.post("")
def create_work_order(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO WorkOrder (BusinessID,FieldID,Location,TaskType,Title,Description,Priority,
            Status,AssignedTo,AssignedDate,DueDate,EstimatedHours,EstimatedCost,Notes)
        OUTPUT INSERTED.WOID
        VALUES (:bid,:fid,:loc,:tt,:title,:desc,:pri,:st,:at,:ad,:dd,:eh,:ec,:notes)
    """), {
        "bid": body["BusinessID"], "fid": body.get("FieldID"), "loc": body.get("Location"),
        "tt": body["TaskType"], "title": body["Title"], "desc": body.get("Description"),
        "pri": body.get("Priority", "normal"), "st": body.get("Status", "open"),
        "at": body.get("AssignedTo"), "ad": body.get("AssignedDate"), "dd": body.get("DueDate"),
        "eh": body.get("EstimatedHours"), "ec": body.get("EstimatedCost"), "notes": body.get("Notes"),
    }).fetchone()
    wo_id = r[0]
    # If created from a pest observation, link the WO back so the pest shows as "being treated"
    pest_obs_id = body.get("PestObsID")
    if pest_obs_id:
        try:
            db.execute(text("""
                UPDATE FarmPestObservation
                SET WorkOrderID = :wid, Status = 'treatment_started'
                WHERE ObsID = :oid AND BusinessID = :bid
            """), {"wid": wo_id, "oid": pest_obs_id, "bid": body["BusinessID"]})
        except Exception:
            pass
    db.commit()
    record_audit(db, body["BusinessID"], body.get("AssignedTo"),
                 "CREATE", "WorkOrder", wo_id,
                 {"task_type": body["TaskType"], "title": body["Title"]})
    if body.get("AssignedTo"):
        notify_business(
            db, body["BusinessID"],
            type="work_order_assigned",
            title=f"New Work Order: {body['Title']}",
            body=f"Assigned to {body['AssignedTo']}",
            link_path=f"/work-orders?BusinessID={body['BusinessID']}",
            entity_type="WorkOrder",
            entity_id=wo_id,
        )
    db.commit()
    return {"WOID": wo_id}


@router.put("/{wo_id}")
def update_work_order(wo_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE WorkOrder SET FieldID=:fid, Location=:loc, TaskType=:tt, Title=:title,
            Description=:desc, Priority=:pri, Status=:st, AssignedTo=:at,
            AssignedDate=:ad, DueDate=:dd, CompletedDate=:cd, EstimatedHours=:eh,
            ActualHours=:ah, EstimatedCost=:ec, Notes=:notes, UpdatedAt=GETDATE()
        WHERE WOID=:wid AND BusinessID=:bid
    """), {
        "fid": body.get("FieldID"), "loc": body.get("Location"),
        "tt": body.get("TaskType"), "title": body.get("Title"), "desc": body.get("Description"),
        "pri": body.get("Priority", "normal"), "st": body.get("Status", "open"),
        "at": body.get("AssignedTo"), "ad": body.get("AssignedDate"), "dd": body.get("DueDate"),
        "cd": body.get("CompletedDate"), "eh": body.get("EstimatedHours"),
        "ah": body.get("ActualHours"), "ec": body.get("EstimatedCost"), "notes": body.get("Notes"),
        "wid": wo_id, "bid": body["BusinessID"],
    })
    record_audit(db, body["BusinessID"], None,
                 "UPDATE", "WorkOrder", wo_id,
                 {"status": body.get("Status"), "title": body.get("Title")})
    db.commit()
    return {"ok": True}


@router.delete("/{wo_id}")
def delete_work_order(wo_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM WorkOrder WHERE WOID=:wid AND BusinessID=:bid"),
               {"wid": wo_id, "bid": business_id})
    record_audit(db, business_id, None, "DELETE", "WorkOrder", wo_id)
    db.commit()
    return {"ok": True}


# ─── Advisories (weather + pest) ─────────────────────────────────────────────

@router.get("/advisories")
def get_advisories(business_id: int = Query(...), db: Session = Depends(get_db)):
    """Return active weather alerts and untreated pest observations for this business.
    Reads from FarmWeatherAlert and FarmPestObservation (owned by farm_kpi router)."""
    _ensure(db)
    try:
        weather_rows = db.execute(text("""
            SELECT WeatherAlertID, AlertType, Severity, CropName, FieldID, Title,
                   Message, RecommendedAction, IsRead, ValidUntil, CreatedAt
            FROM FarmWeatherAlert
            WHERE BusinessID = :bid
              AND (ValidUntil IS NULL OR ValidUntil > GETDATE())
              AND IsRead = 0
            ORDER BY CreatedAt DESC
        """), {"bid": business_id}).fetchall()
    except Exception:
        weather_rows = []

    try:
        pest_rows = db.execute(text("""
            SELECT ObsID, FieldID, FieldName, CropName, PestName, PestType,
                   SeverityLevel, ObservationDate, AffectedArea, Notes,
                   TreatmentRequired, WorkOrderID, Status, CreatedAt
            FROM FarmPestObservation
            WHERE BusinessID = :bid
              AND Status NOT IN ('treated', 'resolved')
            ORDER BY
                CASE SeverityLevel WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                                   WHEN 'medium' THEN 3 ELSE 4 END,
                ObservationDate DESC
        """), {"bid": business_id}).fetchall()
    except Exception:
        pest_rows = []

    return {
        "weather_alerts": [dict(r._mapping) for r in weather_rows],
        "pest_observations": [dict(r._mapping) for r in pest_rows],
    }


# ─── Labor ───────────────────────────────────────────────────────────────────

@router.post("/{wo_id}/labor")
def add_labor(wo_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    hours = float(body.get("HoursWorked", 0))
    rate = float(body.get("HourlyRate") or 0)
    cost = round(hours * rate, 2)
    r = db.execute(text("""
        INSERT INTO WorkOrderLabor (WOID,WorkerName,EmployeeID,WorkDate,HoursWorked,HourlyRate,TotalCost,Notes)
        OUTPUT INSERTED.LaborID
        VALUES (:wid,:wn,:eid,:dt,:hrs,:rate,:cost,:notes)
    """), {
        "wid": wo_id, "wn": body["WorkerName"], "eid": body.get("EmployeeID"),
        "dt": body["WorkDate"], "hrs": hours, "rate": rate or None, "cost": cost or None,
        "notes": body.get("Notes"),
    }).fetchone()
    _update_cost(wo_id, db)
    db.commit()
    return {"LaborID": r[0]}


@router.delete("/{wo_id}/labor/{labor_id}")
def delete_labor(wo_id: int, labor_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM WorkOrderLabor WHERE LaborID=:lid AND WOID=:wid"),
               {"lid": labor_id, "wid": wo_id})
    _update_cost(wo_id, db)
    db.commit()
    return {"ok": True}


# ─── Machinery ───────────────────────────────────────────────────────────────

@router.post("/{wo_id}/machinery")
def add_machinery(wo_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    hours = float(body.get("HoursUsed") or 0)
    rate = float(body.get("CostPerHour") or 0)
    cost = round(hours * rate, 2)
    r = db.execute(text("""
        INSERT INTO WorkOrderMachinery (WOID,MachineName,AssetID,UsageDate,HoursUsed,FuelUsed,FuelUnit,CostPerHour,TotalCost,Notes)
        OUTPUT INSERTED.MachineLogID
        VALUES (:wid,:mn,:aid,:dt,:hrs,:fuel,:funit,:cph,:cost,:notes)
    """), {
        "wid": wo_id, "mn": body["MachineName"], "aid": body.get("AssetID"),
        "dt": body["UsageDate"], "hrs": hours or None, "fuel": body.get("FuelUsed"),
        "funit": body.get("FuelUnit", "liters"), "cph": rate or None, "cost": cost or None,
        "notes": body.get("Notes"),
    }).fetchone()
    _update_cost(wo_id, db)
    db.commit()
    return {"MachineLogID": r[0]}


# ─── Materials ────────────────────────────────────────────────────────────────

@router.post("/{wo_id}/materials")
def add_material(wo_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    qty = float(body.get("Quantity", 0))
    cost = float(body.get("UnitCost") or 0)
    r = db.execute(text("""
        INSERT INTO WorkOrderMaterial (WOID,MaterialName,Category,Quantity,Unit,UnitCost,TotalCost,FarmInputID,Notes)
        OUTPUT INSERTED.MaterialID
        VALUES (:wid,:name,:cat,:qty,:unit,:uc,:tc,:fiid,:notes)
    """), {
        "wid": wo_id, "name": body["MaterialName"], "cat": body.get("Category"),
        "qty": qty, "unit": body.get("Unit"), "uc": cost or None,
        "tc": round(qty * cost, 2) or None, "fiid": body.get("FarmInputID"),
        "notes": body.get("Notes"),
    }).fetchone()
    _update_cost(wo_id, db)
    db.commit()
    return {"MaterialID": r[0]}


# ─── Greenhouse Controls ──────────────────────────────────────────────────────

@router.get("/greenhouse/readings")
def get_gh_readings(business_id: int = Query(...), greenhouse: Optional[str] = None,
                    limit: int = 50, db: Session = Depends(get_db)):
    _ensure(db)
    q = "SELECT TOP(:lim) * FROM GreenhouseReading WHERE BusinessID=:bid"
    params = {"bid": business_id, "lim": limit}
    if greenhouse:
        q += " AND GreenhouseName=:gh"; params["gh"] = greenhouse
    q += " ORDER BY ReadingTime DESC"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/greenhouse/readings")
def add_gh_reading(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO GreenhouseReading (BusinessID,GreenhouseName,TempCelsius,HumidityPct,CO2PPM,
            LightLux,SoilMoisturePct,IrrigationOn,HeatingOn,VentilationOn,Notes)
        OUTPUT INSERTED.ReadingID
        VALUES (:bid,:gh,:temp,:hum,:co2,:lux,:sm,:irr,:heat,:vent,:notes)
    """), {
        "bid": body["BusinessID"], "gh": body["GreenhouseName"],
        "temp": body.get("TempCelsius"), "hum": body.get("HumidityPct"),
        "co2": body.get("CO2PPM"), "lux": body.get("LightLux"),
        "sm": body.get("SoilMoisturePct"),
        "irr": 1 if body.get("IrrigationOn") else 0,
        "heat": 1 if body.get("HeatingOn") else 0,
        "vent": 1 if body.get("VentilationOn") else 0,
        "notes": body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"ReadingID": r[0]}


# ─── Summary ─────────────────────────────────────────────────────────────────

@router.get("/summary/dashboard")
def wo_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    row = db.execute(text("""
        SELECT
            COUNT(*) AS Total,
            SUM(CASE WHEN Status='open' THEN 1 ELSE 0 END) AS Open,
            SUM(CASE WHEN Status='in_progress' THEN 1 ELSE 0 END) AS InProgress,
            SUM(CASE WHEN Status='completed' THEN 1 ELSE 0 END) AS Completed,
            SUM(CASE WHEN DueDate < CAST(GETDATE() AS DATE) AND Status NOT IN ('completed','cancelled') THEN 1 ELSE 0 END) AS Overdue,
            ISNULL(SUM(ActualCost),0) AS TotalActualCost,
            ISNULL(SUM(EstimatedCost),0) AS TotalEstimatedCost
        FROM WorkOrder WHERE BusinessID=:bid
    """), {"bid": business_id}).fetchone()
    return dict(row._mapping) if row else {}
