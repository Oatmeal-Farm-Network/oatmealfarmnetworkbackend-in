from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/irrigation", tags=["irrigation"])
_ddl_done = False

IRRIGATION_TYPES = ["drip", "sprinkler", "pivot", "flood", "furrow", "subsurface", "micro_spray"]
WATER_SOURCES = ["bore", "dam", "river", "canal", "municipal", "recycled", "rainwater"]


def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cur = db.cursor()
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='IrrigationZone')
    CREATE TABLE IrrigationZone (
        ZoneID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        ZoneName NVARCHAR(100) NOT NULL,
        FieldID NVARCHAR(80),
        FieldName NVARCHAR(120),
        AreaHa DECIMAL(10,4),
        IrrigationType NVARCHAR(40),
        WaterSource NVARCHAR(40),
        FlowRateLps DECIMAL(8,3),
        DesignCapacityLph DECIMAL(12,2),
        CropName NVARCHAR(100),
        SoilType NVARCHAR(80),
        WebhookToken NVARCHAR(100),
        IsActive BIT NOT NULL DEFAULT 1,
        Notes NVARCHAR(500),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='IrrigationEvent')
    CREATE TABLE IrrigationEvent (
        EventID INT IDENTITY PRIMARY KEY,
        ZoneID INT NOT NULL,
        BusinessID INT NOT NULL,
        StartTime DATETIME NOT NULL,
        EndTime DATETIME,
        DurationMinutes INT,
        VolumeAppliedL DECIMAL(12,2),
        DepthMm DECIMAL(8,2),
        CostPerKl DECIMAL(8,4),
        TotalCost DECIMAL(12,2),
        TriggerType NVARCHAR(30) NOT NULL DEFAULT 'manual',
        Notes NVARCHAR(500),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='SoilMoistureReading')
    CREATE TABLE SoilMoistureReading (
        ReadingID BIGINT IDENTITY PRIMARY KEY,
        ZoneID INT NOT NULL,
        BusinessID INT NOT NULL,
        DepthCm INT NOT NULL DEFAULT 30,
        MoisturePct DECIMAL(6,2),
        TempC DECIMAL(6,2),
        ECdSm DECIMAL(8,4),
        Source NVARCHAR(20) NOT NULL DEFAULT 'manual',
        ReadingTime DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='IrrigationSchedule')
    CREATE TABLE IrrigationSchedule (
        ScheduleID INT IDENTITY PRIMARY KEY,
        ZoneID INT NOT NULL,
        BusinessID INT NOT NULL,
        DayOfWeek NVARCHAR(60),
        StartTimeOfDay NVARCHAR(10),
        DurationMinutes INT NOT NULL,
        IsActive BIT NOT NULL DEFAULT 1,
        TargetDepthMm DECIMAL(6,2),
        Notes NVARCHAR(300)
    )""")
    db.commit()
    _ddl_done = True


class ZoneIn(BaseModel):
    zone_name: str
    field_id: Optional[str] = None
    field_name: Optional[str] = None
    area_ha: Optional[float] = None
    irrigation_type: Optional[str] = None
    water_source: Optional[str] = None
    flow_rate_lps: Optional[float] = None
    design_capacity_lph: Optional[float] = None
    crop_name: Optional[str] = None
    soil_type: Optional[str] = None
    notes: Optional[str] = None


class EventIn(BaseModel):
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    volume_applied_l: Optional[float] = None
    depth_mm: Optional[float] = None
    cost_per_kl: Optional[float] = None
    trigger_type: str = "manual"
    notes: Optional[str] = None


class MoistureIn(BaseModel):
    depth_cm: int = 30
    moisture_pct: Optional[float] = None
    temp_c: Optional[float] = None
    ec_ds_m: Optional[float] = None
    source: str = "manual"
    reading_time: Optional[datetime] = None


class ScheduleIn(BaseModel):
    day_of_week: Optional[str] = None
    start_time_of_day: Optional[str] = None
    duration_minutes: int
    target_depth_mm: Optional[float] = None
    notes: Optional[str] = None


@router.get("/zones")
def list_zones(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT z.*,
            (SELECT TOP 1 MoisturePct FROM SoilMoistureReading WHERE ZoneID=z.ZoneID
             ORDER BY ReadingTime DESC) AS LatestMoisture,
            (SELECT TOP 1 ReadingTime FROM SoilMoistureReading WHERE ZoneID=z.ZoneID
             ORDER BY ReadingTime DESC) AS LatestMoistureTime,
            (SELECT ROUND(SUM(VolumeAppliedL)/1000,2) FROM IrrigationEvent
             WHERE ZoneID=z.ZoneID AND StartTime >= DATEADD(day,-30,GETDATE())) AS VolumeKl30d
        FROM IrrigationZone z
        WHERE z.BusinessID=? ORDER BY z.ZoneName
    """, [bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.post("/zones", status_code=201)
def create_zone(body: ZoneIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        INSERT INTO IrrigationZone
            (BusinessID,ZoneName,FieldID,FieldName,AreaHa,IrrigationType,WaterSource,
             FlowRateLps,DesignCapacityLph,CropName,SoilType,Notes)
        OUTPUT INSERTED.ZoneID VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, [bid, body.zone_name, body.field_id, body.field_name, body.area_ha,
          body.irrigation_type, body.water_source, body.flow_rate_lps,
          body.design_capacity_lph, body.crop_name, body.soil_type, body.notes])
    zid = cur.fetchone()[0]
    db.commit()
    return {"zone_id": zid}


@router.post("/zones/{zone_id}/events", status_code=201)
def log_event(zone_id: int, body: EventIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT ZoneID, AreaHa, FlowRateLps FROM IrrigationZone WHERE ZoneID=? AND BusinessID=?", [zone_id, bid])
    zone = cur.fetchone()
    if not zone:
        raise HTTPException(404, "Zone not found")
    duration = body.duration_minutes
    if duration is None and body.end_time and body.start_time:
        duration = int((body.end_time - body.start_time).total_seconds() / 60)
    volume = body.volume_applied_l
    if volume is None and duration and zone[2]:
        volume = round(float(zone[2]) * duration * 60, 2)
    depth = body.depth_mm
    if depth is None and volume and zone[1]:
        depth = round(volume / (float(zone[1]) * 10000) * 1000, 2)
    cost = None
    if volume and body.cost_per_kl:
        cost = round(volume / 1000 * body.cost_per_kl, 4)
    cur.execute("""
        INSERT INTO IrrigationEvent
            (ZoneID,BusinessID,StartTime,EndTime,DurationMinutes,VolumeAppliedL,DepthMm,
             CostPerKl,TotalCost,TriggerType,Notes)
        OUTPUT INSERTED.EventID VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, [zone_id, bid, body.start_time, body.end_time, duration, volume, depth,
          body.cost_per_kl, cost, body.trigger_type, body.notes])
    eid = cur.fetchone()[0]
    db.commit()
    return {"event_id": eid, "volume_applied_l": volume, "depth_mm": depth, "total_cost": cost}


@router.get("/zones/{zone_id}/events")
def zone_events(zone_id: int, days: int = 30, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT * FROM IrrigationEvent WHERE ZoneID=? AND BusinessID=?
          AND StartTime >= DATEADD(day,-?,GETDATE())
        ORDER BY StartTime DESC
    """, [zone_id, bid, days])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.post("/zones/{zone_id}/moisture", status_code=201)
def log_moisture(zone_id: int, body: MoistureIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT ZoneID FROM IrrigationZone WHERE ZoneID=? AND BusinessID=?", [zone_id, bid])
    if not cur.fetchone():
        raise HTTPException(404, "Zone not found")
    ts = body.reading_time or datetime.utcnow()
    cur.execute("""
        INSERT INTO SoilMoistureReading (ZoneID,BusinessID,DepthCm,MoisturePct,TempC,ECdSm,Source,ReadingTime)
        OUTPUT INSERTED.ReadingID VALUES (?,?,?,?,?,?,?,?)
    """, [zone_id, bid, body.depth_cm, body.moisture_pct, body.temp_c, body.ec_ds_m, body.source, ts])
    rid = cur.fetchone()[0]
    db.commit()
    return {"reading_id": rid}


@router.post("/webhook/zones/{zone_id}/moisture", status_code=201)
def webhook_moisture(zone_id: int, token: str, body: MoistureIn, db=Depends(get_raw_conn)):
    """IoT soil moisture sensor endpoint — token auth, no JWT."""
    _ensure_tables(db)
    cur = db.cursor()
    cur.execute("SELECT ZoneID, BusinessID, WebhookToken FROM IrrigationZone WHERE ZoneID=?", [zone_id])
    row = cur.fetchone()
    if not row or not row[2] or row[2] != token:
        raise HTTPException(403, "Invalid token")
    bid = row[1]
    ts = body.reading_time or datetime.utcnow()
    cur.execute("""
        INSERT INTO SoilMoistureReading (ZoneID,BusinessID,DepthCm,MoisturePct,TempC,ECdSm,Source,ReadingTime)
        OUTPUT INSERTED.ReadingID VALUES (?,?,?,?,?,?,?,?)
    """, [zone_id, bid, body.depth_cm, body.moisture_pct, body.temp_c, body.ec_ds_m, "iot", ts])
    rid = cur.fetchone()[0]
    db.commit()
    return {"reading_id": rid, "ok": True}


@router.patch("/zones/{zone_id}/webhook-token")
def set_webhook_token(zone_id: int, token: str, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT ZoneID FROM IrrigationZone WHERE ZoneID=? AND BusinessID=?", [zone_id, bid])
    if not cur.fetchone():
        raise HTTPException(404, "Zone not found")
    cur.execute("UPDATE IrrigationZone SET WebhookToken=? WHERE ZoneID=?", [token, zone_id])
    db.commit()
    return {"ok": True}


@router.get("/dashboard")
def dashboard(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT
            COUNT(DISTINCT z.ZoneID) AS TotalZones,
            ROUND(SUM(ISNULL(e30.VolumeKl,0)),2) AS TotalKl30d,
            ROUND(SUM(ISNULL(e30.CostSum,0)),2) AS TotalCost30d,
            COUNT(DISTINCT CASE WHEN m.MoisturePct IS NOT NULL THEN z.ZoneID END) AS ZonesWithMoisture
        FROM IrrigationZone z
        LEFT JOIN (
            SELECT ZoneID, SUM(VolumeAppliedL)/1000.0 AS VolumeKl, SUM(TotalCost) AS CostSum
            FROM IrrigationEvent WHERE BusinessID=? AND StartTime >= DATEADD(day,-30,GETDATE())
            GROUP BY ZoneID
        ) e30 ON e30.ZoneID=z.ZoneID
        LEFT JOIN (
            SELECT ZoneID, MAX(ReadingTime) AS LastRead, AVG(MoisturePct) AS MoisturePct
            FROM SoilMoistureReading WHERE BusinessID=? AND ReadingTime >= DATEADD(hour,-24,GETDATE())
            GROUP BY ZoneID
        ) m ON m.ZoneID=z.ZoneID
        WHERE z.BusinessID=? AND z.IsActive=1
    """, [bid, bid, bid])
    cols = [c[0] for c in cur.description]
    totals = dict(zip(cols, cur.fetchone() or [0]*4))
    cur.execute("""
        SELECT CAST(StartTime AS DATE) AS Day,
               ROUND(SUM(VolumeAppliedL)/1000,3) AS VolumeKl,
               ROUND(SUM(TotalCost),2) AS Cost,
               COUNT(*) AS Events
        FROM IrrigationEvent WHERE BusinessID=? AND StartTime >= DATEADD(day,-30,GETDATE())
        GROUP BY CAST(StartTime AS DATE) ORDER BY Day ASC
    """, [bid])
    cols2 = [c[0] for c in cur.description]
    daily = [dict(zip(cols2, r)) for r in cur.fetchall()]
    return {"totals": totals, "daily": daily}


@router.get("/water-budget")
def water_budget(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    f = from_date or date(date.today().year, 1, 1)
    t = to_date or date.today()
    cur.execute("""
        SELECT z.ZoneName, z.CropName, z.AreaHa,
               ROUND(SUM(e.VolumeAppliedL)/1000,3) AS TotalKl,
               ROUND(SUM(e.VolumeAppliedL)/(NULLIF(z.AreaHa,0)*10000)*1000,1) AS AvgDepthMm,
               ROUND(SUM(e.TotalCost),2) AS TotalCost,
               COUNT(e.EventID) AS Events
        FROM IrrigationZone z
        LEFT JOIN IrrigationEvent e ON e.ZoneID=z.ZoneID
            AND e.StartTime BETWEEN ? AND DATEADD(day,1,?)
        WHERE z.BusinessID=?
        GROUP BY z.ZoneID, z.ZoneName, z.CropName, z.AreaHa
        ORDER BY TotalKl DESC
    """, [str(f), str(t), bid])
    cols = [c[0] for c in cur.description]
    zones = [dict(zip(cols, r)) for r in cur.fetchall()]
    total_kl = sum(float(z["TotalKl"] or 0) for z in zones)
    total_cost = sum(float(z["TotalCost"] or 0) for z in zones)
    return {"from_date": str(f), "to_date": str(t), "zones": zones,
            "total_kl": round(total_kl, 3), "total_cost": round(total_cost, 2)}
