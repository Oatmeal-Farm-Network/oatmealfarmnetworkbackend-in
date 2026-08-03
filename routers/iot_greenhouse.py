from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/iot", tags=["iot_greenhouse"])

_ddl_done = False

SENSOR_TYPES = {"temperature", "humidity", "light", "moisture", "co2", "ph"}


def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cursor = db.cursor()
    cursor.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='IoTSensor')
    CREATE TABLE IoTSensor (
        SensorID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        SensorName NVARCHAR(100) NOT NULL,
        SensorType NVARCHAR(30) NOT NULL,
        Location NVARCHAR(200),
        GreenhouseZone NVARCHAR(100),
        Units NVARCHAR(20),
        IsActive BIT NOT NULL DEFAULT 1,
        LastSeenAt DATETIME,
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cursor.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='IoTReading')
    CREATE TABLE IoTReading (
        ReadingID BIGINT IDENTITY PRIMARY KEY,
        SensorID INT NOT NULL,
        BusinessID INT NOT NULL,
        Value DECIMAL(12,4) NOT NULL,
        Unit NVARCHAR(20),
        ReadingTime DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cursor.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='IoTThreshold')
    CREATE TABLE IoTThreshold (
        ThresholdID INT IDENTITY PRIMARY KEY,
        SensorID INT NOT NULL,
        BusinessID INT NOT NULL,
        VarietyName NVARCHAR(100),
        MinValue DECIMAL(12,4),
        MaxValue DECIMAL(12,4),
        AlertSeverity NVARCHAR(20) NOT NULL DEFAULT 'warning',
        IsActive BIT NOT NULL DEFAULT 1,
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cursor.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='IoTAlert')
    CREATE TABLE IoTAlert (
        AlertID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        SensorID INT NOT NULL,
        AlertType NVARCHAR(50) NOT NULL,
        Message NVARCHAR(500) NOT NULL,
        Value DECIMAL(12,4),
        Severity NVARCHAR(20) NOT NULL DEFAULT 'warning',
        TriggeredAt DATETIME NOT NULL DEFAULT GETDATE(),
        AcknowledgedAt DATETIME,
        AcknowledgedBy NVARCHAR(200)
    )""")
    db.commit()
    _ddl_done = True


class SensorIn(BaseModel):
    sensor_name: str
    sensor_type: str
    location: Optional[str] = None
    greenhouse_zone: Optional[str] = None
    units: Optional[str] = None
    is_active: bool = True


class SensorUpdate(BaseModel):
    sensor_name: Optional[str] = None
    location: Optional[str] = None
    greenhouse_zone: Optional[str] = None
    units: Optional[str] = None
    is_active: Optional[bool] = None


class ReadingIn(BaseModel):
    sensor_id: int
    value: float
    unit: Optional[str] = None
    reading_time: Optional[datetime] = None


class BulkReadingsIn(BaseModel):
    readings: List[ReadingIn]


class ThresholdIn(BaseModel):
    sensor_id: int
    variety_name: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    alert_severity: str = "warning"
    is_active: bool = True


class AlertAck(BaseModel):
    acknowledged_by: Optional[str] = None


def _check_thresholds(db, bid: int, sensor_id: int, value: float, unit: Optional[str]):
    cursor = db.cursor()
    cursor.execute("""
        SELECT ThresholdID, MinValue, MaxValue, AlertSeverity, VarietyName
        FROM IoTThreshold
        WHERE SensorID=? AND BusinessID=? AND IsActive=1
    """, [sensor_id, bid])
    for row in cursor.fetchall():
        _, mn, mx, sev, variety = row
        breached = (mn is not None and value < float(mn)) or (mx is not None and value > float(mx))
        if breached:
            direction = "below minimum" if (mn is not None and value < float(mn)) else "above maximum"
            limit = float(mn) if direction == "below minimum" else float(mx)
            variety_part = f" for {variety}" if variety else ""
            msg = f"Sensor reading {value}{unit or ''} {direction} {limit}{unit or ''}{variety_part}"
            cursor.execute("""
                INSERT INTO IoTAlert (BusinessID,SensorID,AlertType,Message,Value,Severity)
                VALUES (?,?,'threshold_breach',?,?,?)
            """, [bid, sensor_id, msg, value, sev])
    db.commit()


@router.get("/sensors")
def list_sensors(zone: Optional[str] = None, sensor_type: Optional[str] = None, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    filters = ["BusinessID=?"]
    params: list = [bid]
    if zone:
        filters.append("GreenhouseZone=?"); params.append(zone)
    if sensor_type:
        filters.append("SensorType=?"); params.append(sensor_type)
    cursor.execute(f"SELECT * FROM IoTSensor WHERE {' AND '.join(filters)} ORDER BY SensorName", params)
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


@router.post("/sensors", status_code=201)
def create_sensor(body: SensorIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    if body.sensor_type not in SENSOR_TYPES:
        raise HTTPException(400, f"sensor_type must be one of: {', '.join(SENSOR_TYPES)}")
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO IoTSensor (BusinessID,SensorName,SensorType,Location,GreenhouseZone,Units,IsActive)
        OUTPUT INSERTED.SensorID VALUES (?,?,?,?,?,?,?)
    """, [bid, body.sensor_name, body.sensor_type, body.location,
          body.greenhouse_zone, body.units, 1 if body.is_active else 0])
    sid = cursor.fetchone()[0]
    db.commit()
    return {"sensor_id": sid}


@router.patch("/sensors/{sensor_id}")
def update_sensor(sensor_id: int, body: SensorUpdate, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    cursor.execute("SELECT SensorID FROM IoTSensor WHERE SensorID=? AND BusinessID=?", [sensor_id, bid])
    if not cursor.fetchone():
        raise HTTPException(404, "Sensor not found")
    cursor.execute("""
        UPDATE IoTSensor SET
            SensorName=ISNULL(?,SensorName),
            Location=ISNULL(?,Location),
            GreenhouseZone=ISNULL(?,GreenhouseZone),
            Units=ISNULL(?,Units),
            IsActive=ISNULL(?,IsActive)
        WHERE SensorID=? AND BusinessID=?
    """, [body.sensor_name, body.location, body.greenhouse_zone, body.units,
          (1 if body.is_active else 0) if body.is_active is not None else None,
          sensor_id, bid])
    db.commit()
    return {"ok": True}


@router.post("/readings", status_code=201)
def ingest_readings(body: BulkReadingsIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    inserted = 0
    for r in body.readings:
        ts = r.reading_time or datetime.utcnow()
        cursor.execute("""
            INSERT INTO IoTReading (SensorID,BusinessID,Value,Unit,ReadingTime) VALUES (?,?,?,?,?)
        """, [r.sensor_id, bid, r.value, r.unit, ts])
        cursor.execute("UPDATE IoTSensor SET LastSeenAt=? WHERE SensorID=? AND BusinessID=?", [ts, r.sensor_id, bid])
        _check_thresholds(db, bid, r.sensor_id, r.value, r.unit)
        inserted += 1
    db.commit()
    return {"inserted": inserted}


@router.get("/readings/{sensor_id}")
def sensor_readings(
    sensor_id: int,
    hours: int = 24,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    cursor.execute("SELECT SensorID FROM IoTSensor WHERE SensorID=? AND BusinessID=?", [sensor_id, bid])
    if not cursor.fetchone():
        raise HTTPException(404, "Sensor not found")
    since = datetime.utcnow() - timedelta(hours=hours)
    cursor.execute("""
        SELECT ReadingID, Value, Unit, ReadingTime
        FROM IoTReading
        WHERE SensorID=? AND BusinessID=? AND ReadingTime>=?
        ORDER BY ReadingTime ASC
    """, [sensor_id, bid, since])
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


@router.get("/dashboard")
def dashboard(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    # latest reading per sensor
    cursor.execute("""
        SELECT s.SensorID, s.SensorName, s.SensorType, s.GreenhouseZone, s.Units, s.IsActive, s.LastSeenAt,
               r.Value AS LatestValue, r.ReadingTime AS LatestTime
        FROM IoTSensor s
        OUTER APPLY (
            SELECT TOP 1 Value, ReadingTime FROM IoTReading
            WHERE SensorID=s.SensorID AND BusinessID=s.BusinessID
            ORDER BY ReadingTime DESC
        ) r
        WHERE s.BusinessID=?
        ORDER BY s.GreenhouseZone, s.SensorName
    """, [bid])
    cols = [c[0] for c in cursor.description]
    sensors = [dict(zip(cols, row)) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT COUNT(*) AS TotalSensors,
               SUM(CASE WHEN IsActive=1 THEN 1 ELSE 0 END) AS ActiveSensors
        FROM IoTSensor WHERE BusinessID=?
    """, [bid])
    stats = cursor.fetchone()

    cursor.execute("""
        SELECT COUNT(*) FROM IoTAlert
        WHERE BusinessID=? AND AcknowledgedAt IS NULL
    """, [bid])
    open_alerts = cursor.fetchone()[0]

    return {
        "sensors": sensors,
        "total_sensors": stats[0],
        "active_sensors": stats[1],
        "open_alerts": open_alerts,
    }


@router.get("/trends")
def sensor_trends(
    sensor_type: Optional[str] = None,
    zone: Optional[str] = None,
    hours: int = 48,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    since = datetime.utcnow() - timedelta(hours=hours)
    filters = ["r.BusinessID=?", "r.ReadingTime>=?"]
    params: list = [bid, since]
    if sensor_type:
        filters.append("s.SensorType=?"); params.append(sensor_type)
    if zone:
        filters.append("s.GreenhouseZone=?"); params.append(zone)
    where = " AND ".join(filters)
    cursor.execute(f"""
        SELECT s.SensorID, s.SensorName, s.SensorType, s.GreenhouseZone, s.Units,
               r.Value, r.ReadingTime
        FROM IoTReading r
        JOIN IoTSensor s ON s.SensorID=r.SensorID
        WHERE {where}
        ORDER BY s.SensorID, r.ReadingTime ASC
    """, params)
    cols = [c[0] for c in cursor.description]
    rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
    # group by sensor
    from collections import defaultdict
    grouped: dict = defaultdict(list)
    meta: dict = {}
    for row in rows:
        sid = row["SensorID"]
        meta[sid] = {k: row[k] for k in ("SensorName", "SensorType", "GreenhouseZone", "Units")}
        grouped[sid].append({"value": row["Value"], "time": row["ReadingTime"]})
    return [{"sensor_id": sid, **meta[sid], "readings": grouped[sid]} for sid in meta]


@router.get("/alerts")
def list_alerts(
    acknowledged: Optional[bool] = None,
    severity: Optional[str] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    filters = ["a.BusinessID=?"]
    params: list = [bid]
    if acknowledged is False:
        filters.append("a.AcknowledgedAt IS NULL")
    elif acknowledged is True:
        filters.append("a.AcknowledgedAt IS NOT NULL")
    if severity:
        filters.append("a.Severity=?"); params.append(severity)
    where = " AND ".join(filters)
    cursor.execute(f"""
        SELECT a.AlertID, a.SensorID, s.SensorName, s.GreenhouseZone,
               a.AlertType, a.Message, a.Value, a.Severity,
               a.TriggeredAt, a.AcknowledgedAt, a.AcknowledgedBy
        FROM IoTAlert a
        JOIN IoTSensor s ON s.SensorID=a.SensorID
        WHERE {where}
        ORDER BY a.TriggeredAt DESC
    """, params)
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


@router.patch("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int, body: AlertAck, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    cursor.execute("SELECT AlertID FROM IoTAlert WHERE AlertID=? AND BusinessID=?", [alert_id, bid])
    if not cursor.fetchone():
        raise HTTPException(404, "Alert not found")
    cursor.execute("""
        UPDATE IoTAlert SET AcknowledgedAt=GETDATE(), AcknowledgedBy=?
        WHERE AlertID=? AND BusinessID=?
    """, [body.acknowledged_by, alert_id, bid])
    db.commit()
    return {"ok": True}


@router.get("/thresholds")
def list_thresholds(sensor_id: Optional[int] = None, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    if sensor_id:
        cursor.execute("""
            SELECT t.*, s.SensorName FROM IoTThreshold t
            JOIN IoTSensor s ON s.SensorID=t.SensorID
            WHERE t.BusinessID=? AND t.SensorID=?
        """, [bid, sensor_id])
    else:
        cursor.execute("""
            SELECT t.*, s.SensorName FROM IoTThreshold t
            JOIN IoTSensor s ON s.SensorID=t.SensorID
            WHERE t.BusinessID=? ORDER BY s.SensorName
        """, [bid])
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


@router.put("/thresholds")
def upsert_threshold(body: ThresholdIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    cursor.execute("""
        SELECT ThresholdID FROM IoTThreshold
        WHERE SensorID=? AND BusinessID=? AND ISNULL(VarietyName,'')=ISNULL(?,'')
    """, [body.sensor_id, bid, body.variety_name])
    existing = cursor.fetchone()
    if existing:
        cursor.execute("""
            UPDATE IoTThreshold SET MinValue=?,MaxValue=?,AlertSeverity=?,IsActive=?
            WHERE ThresholdID=?
        """, [body.min_value, body.max_value, body.alert_severity,
              1 if body.is_active else 0, existing[0]])
        tid = existing[0]
    else:
        cursor.execute("""
            INSERT INTO IoTThreshold (SensorID,BusinessID,VarietyName,MinValue,MaxValue,AlertSeverity,IsActive)
            OUTPUT INSERTED.ThresholdID VALUES (?,?,?,?,?,?,?)
        """, [body.sensor_id, bid, body.variety_name, body.min_value, body.max_value,
              body.alert_severity, 1 if body.is_active else 0])
        tid = cursor.fetchone()[0]
    db.commit()
    return {"threshold_id": tid}
