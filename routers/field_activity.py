from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/field-activity", tags=["field_activity"])
_ddl_done = False

ACTIVITY_TYPES = [
    "planting", "cultivation", "fertilising", "spraying", "harvesting",
    "irrigation", "scouting", "mowing", "pruning", "thinning", "spreading",
    "sampling", "fumigation", "pest_control", "maintenance", "other",
]


def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cur = db.cursor()
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='FieldActivity')
    CREATE TABLE FieldActivity (
        ActivityID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        ActivityDate DATE NOT NULL,
        ActivityType NVARCHAR(50) NOT NULL,
        FieldID NVARCHAR(80),
        FieldName NVARCHAR(120),
        CropName NVARCHAR(100),
        Description NVARCHAR(500),
        OperatorName NVARCHAR(150),
        EquipmentUsed NVARCHAR(200),
        AreaHa DECIMAL(10,4),
        UnitsApplied DECIMAL(12,3),
        UnitType NVARCHAR(40),
        RatePerHa DECIMAL(12,4),
        ProductName NVARCHAR(200),
        CostTotal DECIMAL(12,2),
        WeatherConditions NVARCHAR(200),
        StartTime NVARCHAR(10),
        EndTime NVARCHAR(10),
        DurationHours DECIMAL(6,2),
        LinkedSprayID INT,
        LinkedScoutingID INT,
        Notes NVARCHAR(1000),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    db.commit()
    _ddl_done = True


class ActivityIn(BaseModel):
    activity_date: date
    activity_type: str
    field_id: Optional[str] = None
    field_name: Optional[str] = None
    crop_name: Optional[str] = None
    description: Optional[str] = None
    operator_name: Optional[str] = None
    equipment_used: Optional[str] = None
    area_ha: Optional[float] = None
    units_applied: Optional[float] = None
    unit_type: Optional[str] = None
    rate_per_ha: Optional[float] = None
    product_name: Optional[str] = None
    cost_total: Optional[float] = None
    weather_conditions: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_hours: Optional[float] = None
    linked_spray_id: Optional[int] = None
    linked_scouting_id: Optional[int] = None
    notes: Optional[str] = None


@router.post("/activities", status_code=201)
def create_activity(body: ActivityIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        INSERT INTO FieldActivity
            (BusinessID, ActivityDate, ActivityType, FieldID, FieldName, CropName,
             Description, OperatorName, EquipmentUsed, AreaHa, UnitsApplied, UnitType,
             RatePerHa, ProductName, CostTotal, WeatherConditions, StartTime, EndTime,
             DurationHours, LinkedSprayID, LinkedScoutingID, Notes)
        OUTPUT INSERTED.ActivityID VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [bid, str(body.activity_date), body.activity_type, body.field_id, body.field_name,
          body.crop_name, body.description, body.operator_name, body.equipment_used,
          body.area_ha, body.units_applied, body.unit_type, body.rate_per_ha,
          body.product_name, body.cost_total, body.weather_conditions,
          body.start_time, body.end_time, body.duration_hours,
          body.linked_spray_id, body.linked_scouting_id, body.notes])
    aid = cur.fetchone()[0]
    db.commit()
    return {"activity_id": aid}


@router.get("/activities")
def list_activities(
    field_id: Optional[str] = None,
    activity_type: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 200,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    filters = ["BusinessID=?"]
    params: list = [bid]
    if field_id:
        filters.append("FieldID=?"); params.append(field_id)
    if activity_type:
        filters.append("ActivityType=?"); params.append(activity_type)
    if from_date:
        filters.append("ActivityDate>=?"); params.append(str(from_date))
    if to_date:
        filters.append("ActivityDate<=?"); params.append(str(to_date))
    cur.execute(f"""
        SELECT * FROM FieldActivity WHERE {' AND '.join(filters)}
        ORDER BY ActivityDate DESC, ActivityID DESC
        OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY
    """, params + [limit])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.delete("/activities/{activity_id}")
def delete_activity(activity_id: int, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("DELETE FROM FieldActivity WHERE ActivityID=? AND BusinessID=?", [activity_id, bid])
    db.commit()
    return {"ok": True}


@router.get("/by-field")
def by_field(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    """Activity count and latest date per field for the current year."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT FieldID, FieldName,
               COUNT(*) AS TotalActivities,
               MAX(ActivityDate) AS LatestActivity,
               SUM(CASE WHEN ActivityType='planting' THEN 1 ELSE 0 END) AS Plantings,
               SUM(CASE WHEN ActivityType='harvesting' THEN 1 ELSE 0 END) AS Harvests,
               SUM(CASE WHEN ActivityType='spraying' THEN 1 ELSE 0 END) AS Sprays
        FROM FieldActivity
        WHERE BusinessID=? AND YEAR(ActivityDate)=YEAR(GETDATE())
        GROUP BY FieldID, FieldName
        ORDER BY LatestActivity DESC
    """, [bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/timeline")
def timeline(
    days: int = 90,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    """Recent activities grouped by date, most recent first."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT * FROM FieldActivity
        WHERE BusinessID=? AND ActivityDate >= DATEADD(day,-?,GETDATE())
        ORDER BY ActivityDate DESC, ActivityID DESC
    """, [bid, days])
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    grouped: dict = {}
    for r in rows:
        k = str(r["ActivityDate"])[:10]
        grouped.setdefault(k, []).append(r)
    return {"days": days, "dates": [{"date": k, "activities": v} for k, v in grouped.items()]}


@router.get("/summary")
def summary(season: Optional[int] = None, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    year = season or datetime.utcnow().year
    cur = db.cursor()
    cur.execute("""
        SELECT ActivityType, COUNT(*) AS Count,
               SUM(ISNULL(AreaHa,0)) AS TotalAreaHa,
               SUM(ISNULL(CostTotal,0)) AS TotalCost
        FROM FieldActivity WHERE BusinessID=? AND YEAR(ActivityDate)=?
        GROUP BY ActivityType ORDER BY Count DESC
    """, [bid, year])
    cols = [c[0] for c in cur.description]
    by_type = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.execute("""
        SELECT COUNT(*) AS Total, SUM(ISNULL(CostTotal,0)) AS TotalCost
        FROM FieldActivity WHERE BusinessID=? AND YEAR(ActivityDate)=?
    """, [bid, year])
    row = cur.fetchone()
    return {"year": year, "total": row[0], "total_cost": float(row[1] or 0), "by_type": by_type}
