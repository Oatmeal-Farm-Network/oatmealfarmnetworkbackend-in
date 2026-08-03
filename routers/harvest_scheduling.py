from fastapi import APIRouter, Depends, Query
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

router = APIRouter(prefix="/api/harvest-schedule", tags=["harvest_schedule"])


def _ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='HarvestSchedule' AND xtype='U')
        CREATE TABLE HarvestSchedule (
            ScheduleID      INT IDENTITY PRIMARY KEY,
            BusinessID      INT NOT NULL,
            FieldID         INT,
            FieldName       NVARCHAR(150),
            CropName        NVARCHAR(100) NOT NULL,
            Variety         NVARCHAR(100),
            PlannedDate     DATE NOT NULL,
            EstimatedTonnes DECIMAL(10,2),
            ActualTonnes    DECIMAL(10,2),
            CrewSize        INT,
            AssignedCrew    NVARCHAR(500),
            Status          NVARCHAR(30) DEFAULT 'Planned',
            Color           NVARCHAR(10) DEFAULT '#3D6B34',
            Notes           NVARCHAR(MAX),
            CreatedAt       DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='HarvestBlock' AND xtype='U')
        CREATE TABLE HarvestBlock (
            BlockID       INT IDENTITY PRIMARY KEY,
            ScheduleID    INT NOT NULL,
            BusinessID    INT NOT NULL,
            BlockName     NVARCHAR(150) NOT NULL,
            AreaHa        DECIMAL(8,2),
            PickersNeeded INT,
            StartTime     NVARCHAR(10),
            EndTime       NVARCHAR(10),
            ActualYieldKg DECIMAL(10,2),
            Notes         NVARCHAR(500),
            CreatedAt     DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


# ── Schedules ─────────────────────────────────────────────────────────────────

@router.get("/schedules")
def list_schedules(business_id: int = Query(...),
                   week_start: Optional[str] = Query(None),
                   db: Session = Depends(get_db)):
    _ensure_tables(db)
    if week_start:
        rows = db.execute(text("""
            SELECT ScheduleID, FieldID, FieldName, CropName, Variety, PlannedDate,
                   EstimatedTonnes, ActualTonnes, CrewSize, AssignedCrew, Status, Color, Notes
            FROM HarvestSchedule
            WHERE BusinessID=:bid
              AND PlannedDate >= :ws AND PlannedDate < DATEADD(day,7,:ws)
            ORDER BY PlannedDate, CropName
        """), {"bid": business_id, "ws": week_start}).fetchall()
    else:
        rows = db.execute(text("""
            SELECT ScheduleID, FieldID, FieldName, CropName, Variety, PlannedDate,
                   EstimatedTonnes, ActualTonnes, CrewSize, AssignedCrew, Status, Color, Notes
            FROM HarvestSchedule
            WHERE BusinessID=:bid AND PlannedDate >= DATEADD(day,-7,GETDATE())
            ORDER BY PlannedDate, CropName
        """), {"bid": business_id}).fetchall()
    return [dict(zip(
        ["schedule_id","field_id","field_name","crop_name","variety","planned_date",
         "estimated_tonnes","actual_tonnes","crew_size","assigned_crew","status","color","notes"], r
    )) for r in rows]


@router.post("/schedules")
def create_schedule(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO HarvestSchedule
            (BusinessID, FieldID, FieldName, CropName, Variety, PlannedDate,
             EstimatedTonnes, CrewSize, AssignedCrew, Status, Color, Notes)
        OUTPUT INSERTED.ScheduleID
        VALUES (:bid,:fid,:fname,:crop,:variety,:dt,:est,:crew,:assigned,:status,:color,:notes)
    """), {
        "bid": business_id, "fid": body.get("field_id") or None,
        "fname": body.get("field_name"), "crop": body.get("crop_name",""),
        "variety": body.get("variety"), "dt": body.get("planned_date"),
        "est": body.get("estimated_tonnes") or None, "crew": body.get("crew_size") or None,
        "assigned": body.get("assigned_crew"), "status": body.get("status","Planned"),
        "color": body.get("color","#3D6B34"), "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"schedule_id": row[0]}


@router.put("/schedules/{schedule_id}")
def update_schedule(schedule_id: int, business_id: int = Query(...),
                    db: Session = Depends(get_db), body: dict = None):
    body = body or {}
    db.execute(text("""
        UPDATE HarvestSchedule SET
            FieldName=:fname, CropName=:crop, Variety=:variety, PlannedDate=:dt,
            EstimatedTonnes=:est, ActualTonnes=:actual, CrewSize=:crew,
            AssignedCrew=:assigned, Status=:status, Color=:color, Notes=:notes
        WHERE ScheduleID=:sid AND BusinessID=:bid
    """), {
        "sid": schedule_id, "bid": business_id,
        "fname": body.get("field_name"), "crop": body.get("crop_name",""),
        "variety": body.get("variety"), "dt": body.get("planned_date"),
        "est": body.get("estimated_tonnes") or None,
        "actual": body.get("actual_tonnes") or None,
        "crew": body.get("crew_size") or None,
        "assigned": body.get("assigned_crew"), "status": body.get("status","Planned"),
        "color": body.get("color","#3D6B34"), "notes": body.get("notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM HarvestBlock WHERE ScheduleID=:sid AND BusinessID=:bid"),
               {"sid": schedule_id, "bid": business_id})
    db.execute(text("DELETE FROM HarvestSchedule WHERE ScheduleID=:sid AND BusinessID=:bid"),
               {"sid": schedule_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Blocks ────────────────────────────────────────────────────────────────────

@router.get("/schedules/{schedule_id}/blocks")
def list_blocks(schedule_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT BlockID, BlockName, AreaHa, PickersNeeded, StartTime, EndTime, ActualYieldKg, Notes
        FROM HarvestBlock WHERE ScheduleID=:sid AND BusinessID=:bid ORDER BY StartTime
    """), {"sid": schedule_id, "bid": business_id}).fetchall()
    return [dict(zip(
        ["block_id","block_name","area_ha","pickers_needed","start_time","end_time","actual_yield_kg","notes"], r
    )) for r in rows]


@router.post("/blocks")
def create_block(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO HarvestBlock
            (ScheduleID, BusinessID, BlockName, AreaHa, PickersNeeded, StartTime, EndTime, ActualYieldKg, Notes)
        OUTPUT INSERTED.BlockID
        VALUES (:sid,:bid,:name,:area,:pickers,:st,:et,:yield,:notes)
    """), {
        "sid": body.get("schedule_id"), "bid": business_id,
        "name": body.get("block_name",""), "area": body.get("area_ha") or None,
        "pickers": body.get("pickers_needed") or None,
        "st": body.get("start_time"), "et": body.get("end_time"),
        "yield": body.get("actual_yield_kg") or None, "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"block_id": row[0]}


@router.delete("/blocks/{block_id}")
def delete_block(block_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM HarvestBlock WHERE BlockID=:bid AND BusinessID=:biz"),
               {"bid": block_id, "biz": business_id})
    db.commit()
    return {"ok": True}


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary")
def get_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    r = db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM HarvestSchedule WHERE BusinessID=:bid
             AND PlannedDate BETWEEN GETDATE() AND DATEADD(day,7,GETDATE())) AS this_week,
            (SELECT ISNULL(SUM(EstimatedTonnes),0) FROM HarvestSchedule WHERE BusinessID=:bid
             AND PlannedDate BETWEEN GETDATE() AND DATEADD(day,7,GETDATE())) AS estimated_tonnes_week,
            (SELECT ISNULL(SUM(ActualTonnes),0) FROM HarvestSchedule WHERE BusinessID=:bid
             AND PlannedDate >= DATEADD(month,-1,GETDATE())) AS actual_tonnes_month,
            (SELECT COUNT(*) FROM HarvestSchedule WHERE BusinessID=:bid
             AND Status='In Progress') AS in_progress
    """), {"bid": business_id}).fetchone()
    return dict(zip(["this_week","estimated_tonnes_week","actual_tonnes_month","in_progress"], r))
