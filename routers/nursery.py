"""
routers/nursery.py
Nursery & Early Growth Tracking — seed batches, germination logs, transplant scheduling, QC checks.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional
from datetime import date

router = APIRouter(prefix="/api/nursery", tags=["nursery"])
_ready = False


def _ensure(db: Session):
    global _ready
    if _ready:
        return
    stmts = [
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='NurseryBatch')
        CREATE TABLE NurseryBatch (
            BatchID              INT IDENTITY PRIMARY KEY,
            BusinessID           INT NOT NULL,
            CropName             NVARCHAR(200) NOT NULL,
            Variety              NVARCHAR(200) NULL,
            PlantingDate         DATE NOT NULL,
            ExpectedTransplantDate DATE NULL,
            Quantity             DECIMAL(10,2) NULL,
            Unit                 NVARCHAR(50)  NULL DEFAULT 'seedlings',
            Substrate            NVARCHAR(200) NULL,
            Location             NVARCHAR(200) NULL,
            Status               NVARCHAR(50)  NOT NULL DEFAULT 'germinating',
            Notes                NVARCHAR(MAX) NULL,
            CreatedAt            DATETIME2 DEFAULT GETDATE(),
            UpdatedAt            DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='NurseryGrowthLog')
        CREATE TABLE NurseryGrowthLog (
            LogID          INT IDENTITY PRIMARY KEY,
            BatchID        INT NOT NULL,
            LoggedDate     DATE NOT NULL,
            HeightCm       DECIMAL(8,2)  NULL,
            GerminationPct DECIMAL(5,2)  NULL,
            HealthScore    INT           NULL,
            Notes          NVARCHAR(MAX) NULL,
            LoggedBy       NVARCHAR(200) NULL,
            CreatedAt      DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='NurseryQCCheck')
        CREATE TABLE NurseryQCCheck (
            CheckID     INT IDENTITY PRIMARY KEY,
            BatchID     INT NOT NULL,
            CheckDate   DATE NOT NULL,
            PassFail    NVARCHAR(10)  NOT NULL DEFAULT 'pass',
            Issues      NVARCHAR(MAX) NULL,
            CheckedBy   NVARCHAR(200) NULL,
            ReadyToTransplant BIT DEFAULT 0,
            CreatedAt   DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='NurseryResourceInput')
        CREATE TABLE NurseryResourceInput (
            InputID      INT IDENTITY PRIMARY KEY,
            BatchID      INT NOT NULL,
            InputDate    DATE NOT NULL,
            InputType    NVARCHAR(100) NOT NULL,
            InputName    NVARCHAR(200) NOT NULL,
            Quantity     DECIMAL(10,2) NULL,
            Unit         NVARCHAR(50)  NULL,
            CostPerUnit  DECIMAL(10,2) NULL,
            Notes        NVARCHAR(MAX) NULL,
            CreatedAt    DATETIME2 DEFAULT GETDATE()
        )""",
    ]
    for s in stmts:
        db.execute(text(s))
    db.commit()
    _ready = True


# ─── Batches ─────────────────────────────────────────────────────────────────

@router.get("/batches")
def list_batches(business_id: int = Query(...), status: Optional[str] = None, db: Session = Depends(get_db)):
    _ensure(db)
    q = "SELECT * FROM NurseryBatch WHERE BusinessID=:bid"
    params = {"bid": business_id}
    if status:
        q += " AND Status=:st"
        params["st"] = status
    q += " ORDER BY PlantingDate DESC"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/batches")
def create_batch(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO NurseryBatch (BusinessID,CropName,Variety,PlantingDate,ExpectedTransplantDate,
            Quantity,Unit,Substrate,Location,Status,Notes)
        OUTPUT INSERTED.BatchID
        VALUES (:bid,:crop,:var,:pd,:etd,:qty,:unit,:sub,:loc,:st,:notes)
    """), {
        "bid":   body["BusinessID"],
        "crop":  body["CropName"],
        "var":   body.get("Variety"),
        "pd":    body["PlantingDate"],
        "etd":   body.get("ExpectedTransplantDate"),
        "qty":   body.get("Quantity"),
        "unit":  body.get("Unit", "seedlings"),
        "sub":   body.get("Substrate"),
        "loc":   body.get("Location"),
        "st":    body.get("Status", "germinating"),
        "notes": body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"BatchID": r[0]}


@router.put("/batches/{batch_id}")
def update_batch(batch_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    db.execute(text("""
        UPDATE NurseryBatch SET
            CropName=:crop, Variety=:var, PlantingDate=:pd,
            ExpectedTransplantDate=:etd, Quantity=:qty, Unit=:unit,
            Substrate=:sub, Location=:loc, Status=:st, Notes=:notes, UpdatedAt=GETDATE()
        WHERE BatchID=:bid AND BusinessID=:business_id
    """), {
        "crop": body.get("CropName"), "var": body.get("Variety"),
        "pd": body.get("PlantingDate"), "etd": body.get("ExpectedTransplantDate"),
        "qty": body.get("Quantity"), "unit": body.get("Unit"),
        "sub": body.get("Substrate"), "loc": body.get("Location"),
        "st": body.get("Status"), "notes": body.get("Notes"),
        "bid": batch_id, "business_id": body["BusinessID"],
    })
    db.commit()
    return {"ok": True}


@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM NurseryBatch WHERE BatchID=:bid AND BusinessID=:business_id"),
               {"bid": batch_id, "business_id": business_id})
    db.commit()
    return {"ok": True}


# ─── Growth Logs ──────────────────────────────────────────────────────────────

@router.get("/batches/{batch_id}/growth-logs")
def get_growth_logs(batch_id: int, db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(text("SELECT * FROM NurseryGrowthLog WHERE BatchID=:bid ORDER BY LoggedDate DESC"),
                      {"bid": batch_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/batches/{batch_id}/growth-logs")
def add_growth_log(batch_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO NurseryGrowthLog (BatchID,LoggedDate,HeightCm,GerminationPct,HealthScore,Notes,LoggedBy)
        OUTPUT INSERTED.LogID
        VALUES (:bid,:dt,:h,:gp,:hs,:notes,:by)
    """), {
        "bid": batch_id, "dt": body.get("LoggedDate"), "h": body.get("HeightCm"),
        "gp": body.get("GerminationPct"), "hs": body.get("HealthScore"),
        "notes": body.get("Notes"), "by": body.get("LoggedBy"),
    }).fetchone()
    db.commit()
    return {"LogID": r[0]}


# ─── QC Checks ───────────────────────────────────────────────────────────────

@router.get("/batches/{batch_id}/qc")
def get_qc(batch_id: int, db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(text("SELECT * FROM NurseryQCCheck WHERE BatchID=:bid ORDER BY CheckDate DESC"),
                      {"bid": batch_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/batches/{batch_id}/qc")
def add_qc(batch_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO NurseryQCCheck (BatchID,CheckDate,PassFail,Issues,CheckedBy,ReadyToTransplant)
        OUTPUT INSERTED.CheckID
        VALUES (:bid,:dt,:pf,:issues,:by,:rtt)
    """), {
        "bid": batch_id, "dt": body.get("CheckDate"), "pf": body.get("PassFail", "pass"),
        "issues": body.get("Issues"), "by": body.get("CheckedBy"),
        "rtt": 1 if body.get("ReadyToTransplant") else 0,
    }).fetchone()
    db.commit()
    return {"CheckID": r[0]}


# ─── Resource Inputs ─────────────────────────────────────────────────────────

@router.get("/batches/{batch_id}/inputs")
def get_inputs(batch_id: int, db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(text("SELECT * FROM NurseryResourceInput WHERE BatchID=:bid ORDER BY InputDate DESC"),
                      {"bid": batch_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/batches/{batch_id}/inputs")
def add_input(batch_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO NurseryResourceInput (BatchID,InputDate,InputType,InputName,Quantity,Unit,CostPerUnit,Notes)
        OUTPUT INSERTED.InputID
        VALUES (:bid,:dt,:itype,:iname,:qty,:unit,:cpu,:notes)
    """), {
        "bid": batch_id, "dt": body.get("InputDate"), "itype": body.get("InputType"),
        "iname": body.get("InputName"), "qty": body.get("Quantity"), "unit": body.get("Unit"),
        "cpu": body.get("CostPerUnit"), "notes": body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"InputID": r[0]}


# ─── Summary stats ────────────────────────────────────────────────────────────

@router.get("/summary")
def nursery_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    row = db.execute(text("""
        SELECT
            COUNT(*) AS TotalBatches,
            SUM(CASE WHEN Status='germinating' THEN 1 ELSE 0 END) AS Germinating,
            SUM(CASE WHEN Status='growing' THEN 1 ELSE 0 END) AS Growing,
            SUM(CASE WHEN Status='ready' THEN 1 ELSE 0 END) AS ReadyToTransplant,
            SUM(CASE WHEN Status='transplanted' THEN 1 ELSE 0 END) AS Transplanted,
            SUM(Quantity) AS TotalSeedlings
        FROM NurseryBatch WHERE BusinessID=:bid
    """), {"bid": business_id}).fetchone()
    return dict(row._mapping) if row else {}
