from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/ca-storage", tags=["ca_storage"])
_ddl_done = False

# Reference CA protocols per commodity (O2%, CO2%, TempC, RH%, max ethylene PPB)
CA_PROTOCOLS = {
    "apple":       {"o2": 1.5,  "co2": 2.5,  "temp_c": 0.0,  "rh": 93, "ethylene_ppb": 1},
    "pear":        {"o2": 1.5,  "co2": 5.0,  "temp_c": -1.0, "rh": 95, "ethylene_ppb": 1},
    "cherry":      {"o2": 3.0,  "co2": 10.0, "temp_c": -1.0, "rh": 95, "ethylene_ppb": None},
    "kiwifruit":   {"o2": 2.0,  "co2": 5.0,  "temp_c": 0.0,  "rh": 95, "ethylene_ppb": None},
    "blueberry":   {"o2": 2.5,  "co2": 15.0, "temp_c": 0.0,  "rh": 95, "ethylene_ppb": None},
    "strawberry":  {"o2": 5.0,  "co2": 15.0, "temp_c": 0.0,  "rh": 95, "ethylene_ppb": None},
    "citrus":      {"o2": 5.0,  "co2": 0.0,  "temp_c": 5.0,  "rh": 92, "ethylene_ppb": None},
    "avocado":     {"o2": 3.0,  "co2": 7.0,  "temp_c": 5.5,  "rh": 90, "ethylene_ppb": None},
    "mango":       {"o2": 5.0,  "co2": 5.0,  "temp_c": 12.0, "rh": 90, "ethylene_ppb": None},
    "grape":       {"o2": 3.0,  "co2": 3.0,  "temp_c": -1.0, "rh": 95, "ethylene_ppb": None},
    "plum":        {"o2": 1.0,  "co2": 5.0,  "temp_c": -1.0, "rh": 95, "ethylene_ppb": 1},
    "peach":       {"o2": 1.0,  "co2": 5.0,  "temp_c": -1.0, "rh": 95, "ethylene_ppb": 1},
    "nectarine":   {"o2": 1.0,  "co2": 5.0,  "temp_c": -1.0, "rh": 95, "ethylene_ppb": 1},
    "potato":      {"o2": 21.0, "co2": 5.0,  "temp_c": 4.0,  "rh": 95, "ethylene_ppb": None},
    "cabbage":     {"o2": 3.0,  "co2": 5.0,  "temp_c": 0.0,  "rh": 98, "ethylene_ppb": None},
}

ALERT_TYPES = ["o2_drift", "co2_drift", "temp_drift", "humidity_drift", "ethylene_high", "seal_breach"]


def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cur = db.cursor()
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CARoom')
    CREATE TABLE CARoom (
        RoomID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        RoomName NVARCHAR(100) NOT NULL,
        CapacityBins INT,
        TargetO2Pct DECIMAL(5,2),
        TargetCO2Pct DECIMAL(5,2),
        TargetTempC DECIMAL(5,2),
        TargetHumidityPct DECIMAL(5,2),
        MaxEthylenePPB DECIMAL(8,2),
        Commodity NVARCHAR(80),
        Variety NVARCHAR(100),
        IsActive BIT NOT NULL DEFAULT 1,
        Notes NVARCHAR(500),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='CARoom' AND COLUMN_NAME='WebhookToken')
    ALTER TABLE CARoom ADD WebhookToken NVARCHAR(100)
    """)
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CARoomReading')
    CREATE TABLE CARoomReading (
        ReadingID INT IDENTITY PRIMARY KEY,
        RoomID INT NOT NULL,
        BusinessID INT NOT NULL,
        O2Pct DECIMAL(6,3),
        CO2Pct DECIMAL(6,3),
        TempC DECIMAL(6,2),
        HumidityPct DECIMAL(6,2),
        EthylenePPB DECIMAL(8,2),
        Source NVARCHAR(20) NOT NULL DEFAULT 'manual',
        ReadingTime DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CARoomLot')
    CREATE TABLE CARoomLot (
        AssignmentID INT IDENTITY PRIMARY KEY,
        RoomID INT NOT NULL,
        BusinessID INT NOT NULL,
        LotID INT,
        BinBarcodesJSON NVARCHAR(MAX),
        BinsCount INT DEFAULT 0,
        EntryDate DATE NOT NULL DEFAULT CAST(GETDATE() AS DATE),
        TargetExitDate DATE,
        ActualExitDate DATE,
        EntryWeightKg DECIMAL(12,3),
        ExitWeightKg DECIMAL(12,3),
        QualityNotes NVARCHAR(1000),
        Status NVARCHAR(20) NOT NULL DEFAULT 'in_storage',
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CAAlert')
    CREATE TABLE CAAlert (
        AlertID INT IDENTITY PRIMARY KEY,
        RoomID INT NOT NULL,
        BusinessID INT NOT NULL,
        AlertType NVARCHAR(40) NOT NULL,
        Message NVARCHAR(500) NOT NULL,
        Severity NVARCHAR(20) NOT NULL DEFAULT 'warning',
        CurrentValue DECIMAL(10,4),
        TargetValue DECIMAL(10,4),
        TriggeredAt DATETIME NOT NULL DEFAULT GETDATE(),
        AcknowledgedAt DATETIME,
        AcknowledgedBy NVARCHAR(200)
    )""")
    db.commit()
    _ddl_done = True


class RoomIn(BaseModel):
    room_name: str
    capacity_bins: Optional[int] = None
    target_o2_pct: Optional[float] = None
    target_co2_pct: Optional[float] = None
    target_temp_c: Optional[float] = None
    target_humidity_pct: Optional[float] = None
    max_ethylene_ppb: Optional[float] = None
    commodity: Optional[str] = None
    variety: Optional[str] = None
    notes: Optional[str] = None


class RoomUpdate(BaseModel):
    target_o2_pct: Optional[float] = None
    target_co2_pct: Optional[float] = None
    target_temp_c: Optional[float] = None
    target_humidity_pct: Optional[float] = None
    max_ethylene_ppb: Optional[float] = None
    commodity: Optional[str] = None
    variety: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class ReadingIn(BaseModel):
    o2_pct: Optional[float] = None
    co2_pct: Optional[float] = None
    temp_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    ethylene_ppb: Optional[float] = None
    source: str = "manual"
    reading_time: Optional[datetime] = None


class LotAssignIn(BaseModel):
    lot_id: Optional[int] = None
    bin_barcodes: Optional[List[str]] = None
    bins_count: int = 0
    entry_date: Optional[date] = None
    target_exit_date: Optional[date] = None
    entry_weight_kg: Optional[float] = None
    quality_notes: Optional[str] = None


def _check_ca_alerts(db, bid: int, room_id: int, reading: ReadingIn):
    cur = db.cursor()
    cur.execute("""
        SELECT TargetO2Pct, TargetCO2Pct, TargetTempC, TargetHumidityPct, MaxEthylenePPB
        FROM CARoom WHERE RoomID=? AND BusinessID=?
    """, [room_id, bid])
    row = cur.fetchone()
    if not row:
        return
    t_o2, t_co2, t_temp, t_rh, t_eth = row

    def _alert(atype, msg, sev, cur_val, tgt_val):
        cur.execute("""
            IF NOT EXISTS (SELECT 1 FROM CAAlert WHERE RoomID=? AND AlertType=? AND AcknowledgedAt IS NULL
                           AND TriggeredAt >= DATEADD(hour,-4,GETDATE()))
            INSERT INTO CAAlert (RoomID,BusinessID,AlertType,Message,Severity,CurrentValue,TargetValue)
            VALUES (?,?,?,?,?,?,?)
        """, [room_id, atype, room_id, bid, atype, msg, sev, cur_val, tgt_val])

    TOLERANCE = 0.5  # pct units
    TEMP_TOL = 0.5   # °C
    RH_TOL = 3.0

    if t_o2 and reading.o2_pct is not None:
        diff = abs(reading.o2_pct - float(t_o2))
        if diff > TOLERANCE * 2:
            _alert("o2_drift", f"O₂ {reading.o2_pct}% vs target {t_o2}% (Δ{diff:.1f})", "critical", reading.o2_pct, float(t_o2))
        elif diff > TOLERANCE:
            _alert("o2_drift", f"O₂ {reading.o2_pct}% vs target {t_o2}%", "warning", reading.o2_pct, float(t_o2))

    if t_co2 and reading.co2_pct is not None:
        diff = abs(reading.co2_pct - float(t_co2))
        if diff > TOLERANCE * 2:
            _alert("co2_drift", f"CO₂ {reading.co2_pct}% vs target {t_co2}% (Δ{diff:.1f})", "critical", reading.co2_pct, float(t_co2))

    if t_temp and reading.temp_c is not None:
        diff = abs(reading.temp_c - float(t_temp))
        if diff > TEMP_TOL * 2:
            _alert("temp_drift", f"Temp {reading.temp_c}°C vs target {t_temp}°C", "critical", reading.temp_c, float(t_temp))
        elif diff > TEMP_TOL:
            _alert("temp_drift", f"Temp {reading.temp_c}°C vs target {t_temp}°C", "warning", reading.temp_c, float(t_temp))

    if t_rh and reading.humidity_pct is not None and abs(reading.humidity_pct - float(t_rh)) > RH_TOL:
        _alert("humidity_drift", f"RH {reading.humidity_pct}% vs target {t_rh}%", "warning", reading.humidity_pct, float(t_rh))

    if t_eth and reading.ethylene_ppb is not None and reading.ethylene_ppb > float(t_eth):
        _alert("ethylene_high", f"Ethylene {reading.ethylene_ppb} ppb exceeds max {t_eth} ppb", "critical", reading.ethylene_ppb, float(t_eth))

    db.commit()


@router.get("/rooms")
def list_rooms(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT * FROM CARoom WHERE BusinessID=? ORDER BY RoomName", [bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.post("/rooms", status_code=201)
def create_room(body: RoomIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        INSERT INTO CARoom (BusinessID,RoomName,CapacityBins,TargetO2Pct,TargetCO2Pct,
            TargetTempC,TargetHumidityPct,MaxEthylenePPB,Commodity,Variety,Notes)
        OUTPUT INSERTED.RoomID VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, [bid, body.room_name, body.capacity_bins, body.target_o2_pct, body.target_co2_pct,
          body.target_temp_c, body.target_humidity_pct, body.max_ethylene_ppb,
          body.commodity, body.variety, body.notes])
    rid = cur.fetchone()[0]
    db.commit()
    return {"room_id": rid}


@router.patch("/rooms/{room_id}")
def update_room(room_id: int, body: RoomUpdate, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT RoomID FROM CARoom WHERE RoomID=? AND BusinessID=?", [room_id, bid])
    if not cur.fetchone():
        raise HTTPException(404, "Room not found")
    cur.execute("""
        UPDATE CARoom SET
            TargetO2Pct=ISNULL(?,TargetO2Pct), TargetCO2Pct=ISNULL(?,TargetCO2Pct),
            TargetTempC=ISNULL(?,TargetTempC), TargetHumidityPct=ISNULL(?,TargetHumidityPct),
            MaxEthylenePPB=ISNULL(?,MaxEthylenePPB), Commodity=ISNULL(?,Commodity),
            Variety=ISNULL(?,Variety), IsActive=ISNULL(?,IsActive), Notes=ISNULL(?,Notes)
        WHERE RoomID=? AND BusinessID=?
    """, [body.target_o2_pct, body.target_co2_pct, body.target_temp_c, body.target_humidity_pct,
          body.max_ethylene_ppb, body.commodity, body.variety,
          (1 if body.is_active else 0) if body.is_active is not None else None,
          body.notes, room_id, bid])
    db.commit()
    return {"ok": True}


@router.post("/rooms/{room_id}/readings", status_code=201)
def ingest_readings(room_id: int, body: ReadingIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT RoomID FROM CARoom WHERE RoomID=? AND BusinessID=?", [room_id, bid])
    if not cur.fetchone():
        raise HTTPException(404, "Room not found")
    ts = body.reading_time or datetime.utcnow()
    cur.execute("""
        INSERT INTO CARoomReading (RoomID,BusinessID,O2Pct,CO2Pct,TempC,HumidityPct,EthylenePPB,Source,ReadingTime)
        OUTPUT INSERTED.ReadingID VALUES (?,?,?,?,?,?,?,?,?)
    """, [room_id, bid, body.o2_pct, body.co2_pct, body.temp_c, body.humidity_pct,
          body.ethylene_ppb, body.source, ts])
    rid = cur.fetchone()[0]
    db.commit()
    _check_ca_alerts(db, bid, room_id, body)
    return {"reading_id": rid}


@router.get("/rooms/{room_id}/readings")
def room_readings(room_id: int, hours: int = 48, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT * FROM CARoomReading
        WHERE RoomID=? AND BusinessID=? AND ReadingTime >= DATEADD(hour,-?,GETDATE())
        ORDER BY ReadingTime ASC
    """, [room_id, bid, hours])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/dashboard")
def dashboard(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT r.RoomID, r.RoomName, r.Commodity, r.Variety, r.CapacityBins,
               r.TargetO2Pct, r.TargetCO2Pct, r.TargetTempC, r.TargetHumidityPct,
               r.MaxEthylenePPB, r.IsActive,
               rd.O2Pct, rd.CO2Pct, rd.TempC, rd.HumidityPct, rd.EthylenePPB, rd.ReadingTime,
               la.ActiveLots, la.TotalBins
        FROM CARoom r
        OUTER APPLY (
            SELECT TOP 1 O2Pct, CO2Pct, TempC, HumidityPct, EthylenePPB, ReadingTime
            FROM CARoomReading WHERE RoomID=r.RoomID AND BusinessID=r.BusinessID
            ORDER BY ReadingTime DESC
        ) rd
        OUTER APPLY (
            SELECT COUNT(*) AS ActiveLots, SUM(BinsCount) AS TotalBins
            FROM CARoomLot WHERE RoomID=r.RoomID AND BusinessID=r.BusinessID AND Status='in_storage'
        ) la
        WHERE r.BusinessID=? ORDER BY r.RoomName
    """, [bid])
    cols = [c[0] for c in cur.description]
    rooms = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.execute("SELECT COUNT(*) FROM CAAlert WHERE BusinessID=? AND AcknowledgedAt IS NULL", [bid])
    open_alerts = cur.fetchone()[0]
    return {"rooms": rooms, "open_alerts": open_alerts}


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
        SELECT a.*, r.RoomName FROM CAAlert a
        JOIN CARoom r ON r.RoomID=a.RoomID
        WHERE {' AND '.join(filters)} ORDER BY a.TriggeredAt DESC
    """, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.patch("/alerts/{alert_id}/acknowledge")
def ack_alert(alert_id: int, acknowledged_by: Optional[str] = None, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT AlertID FROM CAAlert WHERE AlertID=? AND BusinessID=?", [alert_id, bid])
    if not cur.fetchone():
        raise HTTPException(404, "Alert not found")
    cur.execute("UPDATE CAAlert SET AcknowledgedAt=GETDATE(), AcknowledgedBy=? WHERE AlertID=?", [acknowledged_by, alert_id])
    db.commit()
    return {"ok": True}


@router.post("/rooms/{room_id}/lots", status_code=201)
def assign_lot(room_id: int, body: LotAssignIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT RoomID FROM CARoom WHERE RoomID=? AND BusinessID=?", [room_id, bid])
    if not cur.fetchone():
        raise HTTPException(404, "Room not found")
    import json
    barcodes_json = json.dumps(body.bin_barcodes) if body.bin_barcodes else None
    bins_count = len(body.bin_barcodes) if body.bin_barcodes else body.bins_count
    cur.execute("""
        INSERT INTO CARoomLot (RoomID,BusinessID,LotID,BinBarcodesJSON,BinsCount,EntryDate,TargetExitDate,EntryWeightKg,QualityNotes)
        OUTPUT INSERTED.AssignmentID VALUES (?,?,?,?,?,?,?,?,?)
    """, [room_id, bid, body.lot_id, barcodes_json, bins_count,
          str(body.entry_date or date.today()),
          str(body.target_exit_date) if body.target_exit_date else None,
          body.entry_weight_kg, body.quality_notes])
    aid = cur.fetchone()[0]
    db.commit()
    return {"assignment_id": aid}


@router.patch("/rooms/{room_id}/lots/{assignment_id}")
def update_lot_assignment(
    room_id: int, assignment_id: int,
    exit_date: Optional[date] = None,
    exit_weight_kg: Optional[float] = None,
    quality_notes: Optional[str] = None,
    status: Optional[str] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT AssignmentID FROM CARoomLot WHERE AssignmentID=? AND BusinessID=?", [assignment_id, bid])
    if not cur.fetchone():
        raise HTTPException(404, "Assignment not found")
    cur.execute("""
        UPDATE CARoomLot SET
            ActualExitDate=ISNULL(?,ActualExitDate),
            ExitWeightKg=ISNULL(?,ExitWeightKg),
            QualityNotes=ISNULL(?,QualityNotes),
            Status=ISNULL(?,Status)
        WHERE AssignmentID=?
    """, [str(exit_date) if exit_date else None, exit_weight_kg, quality_notes, status, assignment_id])
    db.commit()
    return {"ok": True}


@router.get("/rooms/{room_id}/lots")
def room_lots(room_id: int, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT * FROM CARoomLot WHERE RoomID=? AND BusinessID=?
        ORDER BY EntryDate DESC
    """, [room_id, bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/protocol")
def get_protocol(commodity: str):
    """Return recommended CA protocol for a commodity."""
    proto = CA_PROTOCOLS.get(commodity.lower())
    if not proto:
        available = list(CA_PROTOCOLS.keys())
        raise HTTPException(404, f"No protocol for '{commodity}'. Available: {', '.join(available)}")
    return {"commodity": commodity, "protocol": proto,
            "note": "Tolerances: O₂/CO₂ ±0.5%, Temp ±0.5°C, RH ±3%"}


@router.post("/webhook/rooms/{room_id}/readings", status_code=201)
def webhook_room_reading(room_id: int, token: str, body: ReadingIn, db=Depends(get_raw_conn)):
    """IoT sensor endpoint — no JWT, authenticates via per-room webhook token."""
    _ensure_tables(db)
    cur = db.cursor()
    cur.execute("SELECT RoomID, BusinessID, WebhookToken FROM CARoom WHERE RoomID=?", [room_id])
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Room not found")
    stored_token = row[2]
    if not stored_token or stored_token != token:
        raise HTTPException(403, "Invalid webhook token")
    bid = row[1]
    ts = body.reading_time or datetime.utcnow()
    cur.execute("""
        INSERT INTO CARoomReading (RoomID,BusinessID,O2Pct,CO2Pct,TempC,HumidityPct,EthylenePPB,Source,ReadingTime)
        OUTPUT INSERTED.ReadingID VALUES (?,?,?,?,?,?,?,?,?)
    """, [room_id, bid, body.o2_pct, body.co2_pct, body.temp_c, body.humidity_pct,
          body.ethylene_ppb, "iot", ts])
    rid = cur.fetchone()[0]
    db.commit()
    _check_ca_alerts(db, bid, room_id, body)
    return {"reading_id": rid, "ok": True}


@router.patch("/rooms/{room_id}/webhook-token")
def set_room_webhook_token(room_id: int, token: str, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    """Set or rotate the IoT webhook token for a CA room."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT RoomID FROM CARoom WHERE RoomID=? AND BusinessID=?", [room_id, bid])
    if not cur.fetchone():
        raise HTTPException(404, "Room not found")
    cur.execute("UPDATE CARoom SET WebhookToken=? WHERE RoomID=?", [token, room_id])
    db.commit()
    return {"ok": True, "room_id": room_id}
