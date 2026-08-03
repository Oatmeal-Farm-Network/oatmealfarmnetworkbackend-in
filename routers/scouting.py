from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/scouting", tags=["scouting"])
_ddl_done = False

CATEGORIES = ["pest", "disease", "weed", "nutrient_deficiency", "other"]
SEVERITIES = {0: "None", 1: "Trace", 2: "Low", 3: "Moderate", 4: "High", 5: "Critical"}


def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cur = db.cursor()
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ScoutingRecord')
    CREATE TABLE ScoutingRecord (
        RecordID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        ScoutingDate DATE NOT NULL,
        FieldID NVARCHAR(80),
        FieldName NVARCHAR(120),
        CropName NVARCHAR(100),
        GrowthStage NVARCHAR(80),
        ScoutName NVARCHAR(150),
        WeatherConditions NVARCHAR(200),
        AreaScouted NVARCHAR(80),
        SprayRecommended BIT NOT NULL DEFAULT 0,
        LinkedSprayID INT,
        IsComplete BIT NOT NULL DEFAULT 0,
        Notes NVARCHAR(2000),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ScoutingObservation')
    CREATE TABLE ScoutingObservation (
        ObsID INT IDENTITY PRIMARY KEY,
        RecordID INT NOT NULL,
        BusinessID INT NOT NULL,
        Category NVARCHAR(40) NOT NULL,
        PestOrDisease NVARCHAR(150) NOT NULL,
        Severity INT NOT NULL DEFAULT 0,
        CountPerUnit DECIMAL(10,3),
        CountUnit NVARCHAR(40),
        PercentAffected DECIMAL(6,2),
        ActionThreshold NVARCHAR(200),
        ActionRecommended NVARCHAR(500),
        RequiresSpray BIT NOT NULL DEFAULT 0
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ScoutingAlert')
    CREATE TABLE ScoutingAlert (
        AlertID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        RecordID INT NOT NULL,
        FieldName NVARCHAR(120),
        PestOrDisease NVARCHAR(150),
        Severity INT,
        AlertedAt DATETIME NOT NULL DEFAULT GETDATE(),
        AcknowledgedAt DATETIME
    )""")
    db.commit()
    _ddl_done = True


class ObservationIn(BaseModel):
    category: str = "pest"
    pest_or_disease: str
    severity: int = 0
    count_per_unit: Optional[float] = None
    count_unit: Optional[str] = None
    percent_affected: Optional[float] = None
    action_threshold: Optional[str] = None
    action_recommended: Optional[str] = None
    requires_spray: bool = False


class RecordIn(BaseModel):
    scouting_date: date
    field_id: Optional[str] = None
    field_name: Optional[str] = None
    crop_name: Optional[str] = None
    growth_stage: Optional[str] = None
    scout_name: Optional[str] = None
    weather_conditions: Optional[str] = None
    area_scouted: Optional[str] = None
    notes: Optional[str] = None
    observations: List[ObservationIn] = []


@router.post("/records", status_code=201)
def create_record(body: RecordIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    spray_recommended = any(o.requires_spray for o in body.observations)
    cur.execute("""
        INSERT INTO ScoutingRecord
            (BusinessID,ScoutingDate,FieldID,FieldName,CropName,GrowthStage,ScoutName,
             WeatherConditions,AreaScouted,SprayRecommended,Notes)
        OUTPUT INSERTED.RecordID VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, [bid, str(body.scouting_date), body.field_id, body.field_name, body.crop_name,
          body.growth_stage, body.scout_name, body.weather_conditions, body.area_scouted,
          1 if spray_recommended else 0, body.notes])
    rec_id = cur.fetchone()[0]
    for o in body.observations:
        cur.execute("""
            INSERT INTO ScoutingObservation
                (RecordID,BusinessID,Category,PestOrDisease,Severity,CountPerUnit,CountUnit,
                 PercentAffected,ActionThreshold,ActionRecommended,RequiresSpray)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, [rec_id, bid, o.category, o.pest_or_disease, o.severity, o.count_per_unit,
              o.count_unit, o.percent_affected, o.action_threshold, o.action_recommended,
              1 if o.requires_spray else 0])
        if o.severity >= 4:
            cur.execute("""
                INSERT INTO ScoutingAlert (BusinessID,RecordID,FieldName,PestOrDisease,Severity)
                VALUES (?,?,?,?,?)
            """, [bid, rec_id, body.field_name, o.pest_or_disease, o.severity])
    db.commit()
    return {"record_id": rec_id, "spray_recommended": spray_recommended}


@router.get("/records")
def list_records(
    field_id: Optional[str] = None,
    crop_name: Optional[str] = None,
    from_date: Optional[date] = None,
    spray_recommended: Optional[bool] = None,
    limit: int = 100,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    filters = ["r.BusinessID=?"]
    params: list = [bid]
    if field_id:
        filters.append("r.FieldID=?"); params.append(field_id)
    if crop_name:
        filters.append("r.CropName=?"); params.append(crop_name)
    if from_date:
        filters.append("r.ScoutingDate>=?"); params.append(str(from_date))
    if spray_recommended is not None:
        filters.append("r.SprayRecommended=?"); params.append(1 if spray_recommended else 0)
    cur.execute(f"""
        SELECT r.*,
            (SELECT COUNT(*) FROM ScoutingObservation WHERE RecordID=r.RecordID) AS ObsCount,
            (SELECT MAX(Severity) FROM ScoutingObservation WHERE RecordID=r.RecordID) AS MaxSeverity
        FROM ScoutingRecord r
        WHERE {' AND '.join(filters)}
        ORDER BY r.ScoutingDate DESC
        OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY
    """, params + [limit])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/records/{record_id}")
def get_record(record_id: int, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT * FROM ScoutingRecord WHERE RecordID=? AND BusinessID=?", [record_id, bid])
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Record not found")
    cols = [c[0] for c in cur.description]
    rec = dict(zip(cols, row))
    cur.execute("SELECT * FROM ScoutingObservation WHERE RecordID=? AND BusinessID=?", [record_id, bid])
    cols2 = [c[0] for c in cur.description]
    rec["observations"] = [dict(zip(cols2, r)) for r in cur.fetchall()]
    return rec


@router.patch("/records/{record_id}/complete")
def complete_record(record_id: int, linked_spray_id: Optional[int] = None, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT RecordID FROM ScoutingRecord WHERE RecordID=? AND BusinessID=?", [record_id, bid])
    if not cur.fetchone():
        raise HTTPException(404, "Record not found")
    cur.execute("UPDATE ScoutingRecord SET IsComplete=1, LinkedSprayID=ISNULL(?,LinkedSprayID) WHERE RecordID=?",
                [linked_spray_id, record_id])
    db.commit()
    return {"ok": True}


@router.get("/active-threats")
def active_threats(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    """Return high/critical severity observations from the last 30 days."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT o.PestOrDisease, o.Category, o.Severity, o.PercentAffected,
               r.FieldName, r.CropName, r.ScoutingDate, r.RecordID
        FROM ScoutingObservation o
        JOIN ScoutingRecord r ON r.RecordID=o.RecordID
        WHERE r.BusinessID=? AND o.Severity >= 3
          AND r.ScoutingDate >= DATEADD(day,-30,GETDATE())
        ORDER BY o.Severity DESC, r.ScoutingDate DESC
    """, [bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/alerts")
def list_alerts(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT * FROM ScoutingAlert WHERE BusinessID=? AND AcknowledgedAt IS NULL
        ORDER BY AlertedAt DESC
    """, [bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.patch("/alerts/{alert_id}/acknowledge")
def ack_alert(alert_id: int, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("UPDATE ScoutingAlert SET AcknowledgedAt=GETDATE() WHERE AlertID=? AND BusinessID=?",
                [alert_id, bid])
    db.commit()
    return {"ok": True}


@router.get("/summary")
def summary(season: Optional[str] = None, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    year = int(season) if season else date.today().year
    cur = db.cursor()
    cur.execute("""
        SELECT COUNT(*) AS TotalRecords,
               SUM(CASE WHEN SprayRecommended=1 THEN 1 ELSE 0 END) AS SprayRecommended,
               SUM(CASE WHEN IsComplete=0 THEN 1 ELSE 0 END) AS Pending
        FROM ScoutingRecord WHERE BusinessID=? AND YEAR(ScoutingDate)=?
    """, [bid, year])
    row = cur.fetchone()
    totals = {"total_records": row[0], "spray_recommended": row[1], "pending": row[2]}
    cur.execute("""
        SELECT o.PestOrDisease, o.Category, COUNT(*) AS Occurrences, MAX(o.Severity) AS MaxSeverity
        FROM ScoutingObservation o
        JOIN ScoutingRecord r ON r.RecordID=o.RecordID
        WHERE r.BusinessID=? AND YEAR(r.ScoutingDate)=?
        GROUP BY o.PestOrDisease, o.Category
        ORDER BY Occurrences DESC
    """, [bid, year])
    cols = [c[0] for c in cur.description]
    top_pests = [dict(zip(cols, r)) for r in cur.fetchall()]
    return {"year": year, "totals": totals, "top_pests": top_pests}
