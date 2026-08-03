from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import math
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/grain-bin", tags=["grain_bin"])
_ddl_done = False

COMMODITIES = ["wheat", "corn", "soybeans", "sorghum", "barley", "oats", "canola", "rice", "sunflower", "cotton"]
BIN_TYPES = ["steel_flat_bottom", "hopper_bottom", "bunker", "bag_storage", "tile_bin"]

# ── Equilibrium Moisture Content (Chung-Pfost equation) ──────────────────────
# EMC = A - B * ln(-[T+C] * ln[RH])  where A,B,C are commodity-specific
_CPF = {
    "wheat":     (8.2, 1.94, 100),
    "corn":      (8.22, 1.88, 100),
    "soybeans":  (9.65, 2.27, 100),
    "sorghum":   (9.68, 2.46, 200),
    "barley":    (8.22, 2.02, 100),
    "oats":      (8.5,  2.10, 100),
    "canola":    (8.11, 2.03, 100),
    "rice":      (9.37, 2.17, 100),
    "sunflower": (7.44, 2.44, 100),
    "cotton":    (8.00, 2.03, 100),
}

def calc_emc(commodity: str, temp_c: float, rh_pct: float) -> Optional[float]:
    params = _CPF.get(commodity.lower())
    if not params or rh_pct <= 0 or rh_pct >= 100:
        return None
    A, B, C = params
    temp_k = temp_c + 273.15
    try:
        emc = A - B * math.log(-(temp_k + C) * math.log(rh_pct / 100))
        return round(emc, 2)
    except (ValueError, ZeroDivisionError):
        return None


def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cur = db.cursor()
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='GrainBin')
    CREATE TABLE GrainBin (
        BinID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        BinName NVARCHAR(100) NOT NULL,
        BinType NVARCHAR(40) NOT NULL DEFAULT 'steel_flat_bottom',
        CapacityTonnes DECIMAL(10,2),
        LocationDescription NVARCHAR(200),
        CurrentCommodity NVARCHAR(80),
        CurrentFillPct DECIMAL(5,1),
        FanStatus NVARCHAR(10) NOT NULL DEFAULT 'off',
        IsActive BIT NOT NULL DEFAULT 1,
        Notes NVARCHAR(500),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='GrainBin' AND COLUMN_NAME='WebhookToken')
    ALTER TABLE GrainBin ADD WebhookToken NVARCHAR(100)
    """)
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='GrainBinReading')
    CREATE TABLE GrainBinReading (
        ReadingID BIGINT IDENTITY PRIMARY KEY,
        BinID INT NOT NULL,
        BusinessID INT NOT NULL,
        ProbeDepth NVARCHAR(30) NOT NULL DEFAULT 'middle',
        TempC DECIMAL(6,2),
        MoisturePercent DECIMAL(6,2),
        CO2PPM DECIMAL(8,2),
        ReadingTime DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='GrainBinAlert')
    CREATE TABLE GrainBinAlert (
        AlertID INT IDENTITY PRIMARY KEY,
        BinID INT NOT NULL,
        BusinessID INT NOT NULL,
        AlertType NVARCHAR(40) NOT NULL,
        Message NVARCHAR(500) NOT NULL,
        Severity NVARCHAR(20) NOT NULL DEFAULT 'warning',
        TriggerValue DECIMAL(10,3),
        TriggeredAt DATETIME NOT NULL DEFAULT GETDATE(),
        AcknowledgedAt DATETIME,
        AcknowledgedBy NVARCHAR(200)
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='GrainAerationLog')
    CREATE TABLE GrainAerationLog (
        LogID INT IDENTITY PRIMARY KEY,
        BinID INT NOT NULL,
        BusinessID INT NOT NULL,
        StartTime DATETIME NOT NULL DEFAULT GETDATE(),
        EndTime DATETIME,
        AmbientTempC DECIMAL(6,2),
        AmbientHumidityPct DECIMAL(5,1),
        TargetMoisturePercent DECIMAL(5,2),
        Outcome NVARCHAR(80),
        Notes NVARCHAR(500)
    )""")
    db.commit()
    _ddl_done = True


class BinIn(BaseModel):
    bin_name: str
    bin_type: str = "steel_flat_bottom"
    capacity_tonnes: Optional[float] = None
    location_description: Optional[str] = None
    current_commodity: Optional[str] = None
    current_fill_pct: Optional[float] = None
    notes: Optional[str] = None


class ReadingIn(BaseModel):
    bin_id: int
    probe_depth: str = "middle"
    temp_c: Optional[float] = None
    moisture_percent: Optional[float] = None
    co2_ppm: Optional[float] = None
    reading_time: Optional[datetime] = None


class BulkReadingsIn(BaseModel):
    readings: List[ReadingIn]


class AerationLogIn(BaseModel):
    bin_id: int
    ambient_temp_c: Optional[float] = None
    ambient_humidity_pct: Optional[float] = None
    target_moisture_percent: Optional[float] = None
    notes: Optional[str] = None


def _fire_alerts(db, bid: int, bin_id: int):
    cur = db.cursor()
    # get recent readings for this bin (last 2h)
    cur.execute("""
        SELECT TempC, MoisturePercent, CO2PPM FROM GrainBinReading
        WHERE BinID=? AND BusinessID=? AND ReadingTime >= DATEADD(hour,-2,GETDATE())
    """, [bin_id, bid])
    rows = cur.fetchall()
    if not rows:
        return
    temps = [float(r[0]) for r in rows if r[0] is not None]
    moistures = [float(r[1]) for r in rows if r[1] is not None]
    co2s = [float(r[2]) for r in rows if r[2] is not None]

    def _alert(atype, msg, sev, val):
        cur.execute("""
            IF NOT EXISTS (SELECT 1 FROM GrainBinAlert WHERE BinID=? AND AlertType=? AND AcknowledgedAt IS NULL
                           AND TriggeredAt >= DATEADD(hour,-6,GETDATE()))
            INSERT INTO GrainBinAlert (BinID,BusinessID,AlertType,Message,Severity,TriggerValue)
            VALUES (?,?,?,?,?,?)
        """, [bin_id, atype, bin_id, bid, atype, msg, sev, val])

    # Hotspot: any probe ≥ 5°C above mean
    if len(temps) >= 2:
        mean_t = sum(temps) / len(temps)
        if max(temps) - mean_t >= 5:
            _alert("hotspot", f"Temperature hotspot detected: max {max(temps):.1f}°C vs avg {mean_t:.1f}°C", "critical", max(temps))
        elif max(temps) > 30:
            _alert("high_temp", f"Grain temperature high: {max(temps):.1f}°C", "warning", max(temps))

    if moistures and max(moistures) > 15:
        _alert("high_moisture", f"Moisture reading {max(moistures):.1f}% — safe storage limit ~14%", "critical", max(moistures))

    if co2s and max(co2s) > 5000:
        _alert("co2_buildup", f"Elevated CO₂: {max(co2s):.0f} ppm — possible grain respiration", "warning", max(co2s))

    db.commit()


@router.get("/bins")
def list_bins(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT * FROM GrainBin WHERE BusinessID=? ORDER BY BinName", [bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.post("/bins", status_code=201)
def create_bin(body: BinIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        INSERT INTO GrainBin (BusinessID,BinName,BinType,CapacityTonnes,LocationDescription,
            CurrentCommodity,CurrentFillPct,Notes)
        OUTPUT INSERTED.BinID VALUES (?,?,?,?,?,?,?,?)
    """, [bid, body.bin_name, body.bin_type, body.capacity_tonnes, body.location_description,
          body.current_commodity, body.current_fill_pct, body.notes])
    bid_new = cur.fetchone()[0]
    db.commit()
    return {"bin_id": bid_new}


@router.post("/readings", status_code=201)
def ingest_readings(body: BulkReadingsIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    affected_bins = set()
    for r in body.readings:
        ts = r.reading_time or datetime.utcnow()
        cur.execute("""
            INSERT INTO GrainBinReading (BinID,BusinessID,ProbeDepth,TempC,MoisturePercent,CO2PPM,ReadingTime)
            VALUES (?,?,?,?,?,?,?)
        """, [r.bin_id, bid, r.probe_depth, r.temp_c, r.moisture_percent, r.co2_ppm, ts])
        affected_bins.add(r.bin_id)
    db.commit()
    for bin_id in affected_bins:
        _fire_alerts(db, bid, bin_id)
    return {"inserted": len(body.readings)}


@router.get("/readings/{bin_id}")
def bin_readings(bin_id: int, hours: int = 48, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT BinID FROM GrainBin WHERE BinID=? AND BusinessID=?", [bin_id, bid])
    if not cur.fetchone():
        raise HTTPException(404, "Bin not found")
    since = datetime.utcnow() - timedelta(hours=hours)
    cur.execute("""
        SELECT ReadingID, ProbeDepth, TempC, MoisturePercent, CO2PPM, ReadingTime
        FROM GrainBinReading WHERE BinID=? AND BusinessID=? AND ReadingTime>=?
        ORDER BY ReadingTime ASC
    """, [bin_id, bid, since])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/dashboard")
def dashboard(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT b.BinID, b.BinName, b.BinType, b.CurrentCommodity, b.CurrentFillPct,
               b.FanStatus, b.CapacityTonnes, b.IsActive,
               r.TempC AS LatestTempC, r.MoisturePercent AS LatestMoisture,
               r.CO2PPM AS LatestCO2, r.ReadingTime AS LatestReadingTime
        FROM GrainBin b
        OUTER APPLY (
            SELECT TOP 1 TempC, MoisturePercent, CO2PPM, ReadingTime
            FROM GrainBinReading WHERE BinID=b.BinID AND BusinessID=b.BusinessID
            ORDER BY ReadingTime DESC
        ) r
        WHERE b.BusinessID=? ORDER BY b.BinName
    """, [bid])
    cols = [c[0] for c in cur.description]
    bins = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.execute("""
        SELECT COUNT(*) AS OpenAlerts FROM GrainBinAlert
        WHERE BusinessID=? AND AcknowledgedAt IS NULL
    """, [bid])
    open_alerts = cur.fetchone()[0]
    return {"bins": bins, "open_alerts": open_alerts}


@router.get("/alerts")
def list_alerts(acknowledged: Optional[bool] = None, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    filters = ["a.BusinessID=?"]
    params: list = [bid]
    if acknowledged is False:
        filters.append("a.AcknowledgedAt IS NULL")
    elif acknowledged is True:
        filters.append("a.AcknowledgedAt IS NOT NULL")
    cur.execute(f"""
        SELECT a.*, b.BinName FROM GrainBinAlert a
        JOIN GrainBin b ON b.BinID=a.BinID
        WHERE {' AND '.join(filters)} ORDER BY a.TriggeredAt DESC
    """, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.patch("/alerts/{alert_id}/acknowledge")
def ack_alert(alert_id: int, acknowledged_by: Optional[str] = None, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT AlertID FROM GrainBinAlert WHERE AlertID=? AND BusinessID=?", [alert_id, bid])
    if not cur.fetchone():
        raise HTTPException(404, "Alert not found")
    cur.execute("UPDATE GrainBinAlert SET AcknowledgedAt=GETDATE(), AcknowledgedBy=? WHERE AlertID=?",
                [acknowledged_by, alert_id])
    db.commit()
    return {"ok": True}


@router.post("/aeration-log", status_code=201)
def log_aeration(body: AerationLogIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        INSERT INTO GrainAerationLog (BinID,BusinessID,AmbientTempC,AmbientHumidityPct,
            TargetMoisturePercent,Notes)
        OUTPUT INSERTED.LogID VALUES (?,?,?,?,?,?)
    """, [body.bin_id, bid, body.ambient_temp_c, body.ambient_humidity_pct,
          body.target_moisture_percent, body.notes])
    lid = cur.fetchone()[0]
    db.commit()
    return {"log_id": lid}


@router.get("/aeration-log")
def get_aeration_log(bin_id: Optional[int] = None, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    if bin_id:
        cur.execute("SELECT * FROM GrainAerationLog WHERE BusinessID=? AND BinID=? ORDER BY StartTime DESC", [bid, bin_id])
    else:
        cur.execute("SELECT * FROM GrainAerationLog WHERE BusinessID=? ORDER BY StartTime DESC", [bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/equilibrium")
def equilibrium(
    commodity: str,
    temp_c: float,
    humidity_pct: float,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    """Calculate equilibrium moisture content for safe storage."""
    emc = calc_emc(commodity, temp_c, humidity_pct)
    if emc is None:
        raise HTTPException(400, "Cannot calculate EMC for given parameters")
    safe_storage = {
        "wheat": 13.5, "corn": 14.0, "soybeans": 13.0, "sorghum": 13.0,
        "barley": 13.5, "oats": 14.0, "canola": 10.0, "rice": 14.0,
        "sunflower": 10.0, "cotton": 12.0,
    }
    target = safe_storage.get(commodity.lower(), 14.0)
    return {
        "commodity": commodity,
        "temp_c": temp_c,
        "humidity_pct": humidity_pct,
        "equilibrium_moisture_pct": emc,
        "safe_storage_target_pct": target,
        "aeration_recommended": emc < target,
        "note": "Aerate when ambient EMC < target storage moisture to dry grain" if emc < target else "Do not aerate — ambient air is wetter than safe storage target",
    }


class WebhookReadingIn(BaseModel):
    probe_depth: str = "middle"
    temp_c: Optional[float] = None
    moisture_percent: Optional[float] = None
    co2_ppm: Optional[float] = None
    reading_time: Optional[datetime] = None


@router.post("/webhook/readings", status_code=201)
def webhook_readings(bin_id: int, token: str, body: WebhookReadingIn, db=Depends(get_raw_conn)):
    """IoT device endpoint — no JWT needed, authenticates via per-bin webhook token."""
    _ensure_tables(db)
    cur = db.cursor()
    cur.execute("SELECT BinID, BusinessID, WebhookToken FROM GrainBin WHERE BinID=?", [bin_id])
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Bin not found")
    stored_token = row[2]
    if not stored_token or stored_token != token:
        raise HTTPException(403, "Invalid webhook token")
    bid = row[1]
    ts = body.reading_time or datetime.utcnow()
    cur.execute("""
        INSERT INTO GrainBinReading (BinID,BusinessID,ProbeDepth,TempC,MoisturePercent,CO2PPM,ReadingTime)
        VALUES (?,?,?,?,?,?,?)
    """, [bin_id, bid, body.probe_depth, body.temp_c, body.moisture_percent, body.co2_ppm, ts])
    db.commit()
    _fire_alerts(db, bid, bin_id)
    return {"ok": True}


@router.patch("/bins/{bin_id}/webhook-token")
def set_webhook_token(bin_id: int, token: str, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    """Generate or update the webhook token for an IoT-connected bin."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT BinID FROM GrainBin WHERE BinID=? AND BusinessID=?", [bin_id, bid])
    if not cur.fetchone():
        raise HTTPException(404, "Bin not found")
    cur.execute("UPDATE GrainBin SET WebhookToken=? WHERE BinID=?", [token, bin_id])
    db.commit()
    return {"ok": True, "bin_id": bin_id}
