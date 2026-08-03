from fastapi import APIRouter, Depends, HTTPException, Query
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
import hashlib
import json
from datetime import datetime, timezone

router = APIRouter(prefix="/api/cold-chain", tags=["cold_chain"])

_tables_ready = False

# ── Shelf-life parameters (Q10 degradation model) ────────────────────────────
# t_ref: optimal storage temp °C; q10: rate doubles per 10°C above ref;
# base_days: expected shelf life at t_ref
SHELF_LIFE_PARAMS = {
    "leafy_greens": {"t_ref": 4.0,  "q10": 2.5, "base_days": 10},
    "berries":      {"t_ref": 2.0,  "q10": 3.0, "base_days":  7},
    "root_veg":     {"t_ref": 2.0,  "q10": 2.0, "base_days": 30},
    "eggs":         {"t_ref": 4.0,  "q10": 2.0, "base_days": 35},
    "dairy_milk":   {"t_ref": 4.0,  "q10": 3.0, "base_days": 14},
    "apples":       {"t_ref": 1.0,  "q10": 2.0, "base_days": 60},
    "tomatoes":     {"t_ref": 13.0, "q10": 2.0, "base_days": 14},
    "bananas":      {"t_ref": 13.0, "q10": 2.5, "base_days": 10},
    "meat_fresh":   {"t_ref": 2.0,  "q10": 3.5, "base_days":  7},
    "poultry":      {"t_ref": 2.0,  "q10": 3.5, "base_days":  5},
    "fish":         {"t_ref": 0.0,  "q10": 4.0, "base_days":  3},
    "general":      {"t_ref": 4.0,  "q10": 2.0, "base_days": 14},
}


def _ensure_tables(db: Session):
    global _tables_ready
    if _tables_ready:
        return

    # ── Core tables (original) ──────────────────────────────────────────────
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ColdChainVehicle')
        CREATE TABLE ColdChainVehicle (
            VehicleID     INT IDENTITY PRIMARY KEY,
            BusinessID    INT NOT NULL,
            VehicleName   NVARCHAR(200) NOT NULL,
            LicensePlate  NVARCHAR(50)  NULL,
            DriverName    NVARCHAR(200) NULL,
            DriverPhone   NVARCHAR(50)  NULL,
            MinTempC      DECIMAL(5,2)  NOT NULL DEFAULT -2.0,
            MaxTempC      DECIMAL(5,2)  NOT NULL DEFAULT 7.0,
            IsActive      BIT           NOT NULL DEFAULT 1,
            CreatedAt     DATETIME2     DEFAULT GETDATE()
        )
    """))

    # Power-status columns on vehicles (added if missing)
    for col, defn in [
        ("ReeferFuelPct",  "DECIMAL(5,2) NULL"),
        ("BatteryPct",     "DECIMAL(5,2) NULL"),
        ("LastPingAt",     "DATETIME2    NULL"),
        ("PowerAlertSent", "BIT NOT NULL DEFAULT 0"),
    ]:
        db.execute(text(f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.columns
                WHERE object_id = OBJECT_ID('ColdChainVehicle') AND name = '{col}'
            )
            ALTER TABLE ColdChainVehicle ADD {col} {defn}
        """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ColdChainReading')
        CREATE TABLE ColdChainReading (
            ReadingID    INT IDENTITY PRIMARY KEY,
            VehicleID    INT           NOT NULL,
            TempC        DECIMAL(5,2)  NOT NULL,
            Humidity     DECIMAL(5,2)  NULL,
            LocationDesc NVARCHAR(500) NULL,
            RecordedAt   DATETIME2     NOT NULL DEFAULT GETDATE(),
            Notes        NVARCHAR(1000) NULL
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (
            SELECT 1 FROM sys.indexes
            WHERE object_id = OBJECT_ID('ColdChainReading')
              AND name = 'IX_ColdChainReading_Vehicle_Time'
        )
        CREATE INDEX IX_ColdChainReading_Vehicle_Time
            ON ColdChainReading (VehicleID, RecordedAt DESC)
    """))

    # Multi-sensor columns on readings (added if missing)
    for col, defn in [
        ("EthyleneGasPPM", "DECIMAL(7,3) NULL"),
        ("CO2PPM",         "INT NULL"),
        ("LightLux",       "DECIMAL(8,2) NULL"),
        ("DoorOpenFlag",   "BIT NOT NULL DEFAULT 0"),
        ("GpsLat",         "DECIMAL(9,6) NULL"),
        ("GpsLon",         "DECIMAL(9,6) NULL"),
        ("ShockGForce",    "DECIMAL(5,2) NULL"),
    ]:
        db.execute(text(f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.columns
                WHERE object_id = OBJECT_ID('ColdChainReading') AND name = '{col}'
            )
            ALTER TABLE ColdChainReading ADD {col} {defn}
        """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ColdChainShipment')
        CREATE TABLE ColdChainShipment (
            ShipmentID   INT IDENTITY PRIMARY KEY,
            VehicleID    INT           NOT NULL,
            BusinessID   INT           NOT NULL,
            RunDate      DATE          NOT NULL,
            RouteLabel   NVARCHAR(200) NULL,
            Status       VARCHAR(30)   NOT NULL DEFAULT 'completed',
            DriverName   NVARCHAR(200) NULL,
            DepartedAt   DATETIME2     NULL,
            ArrivedAt    DATETIME2     NULL,
            TotalMiles   DECIMAL(7,1)  NULL,
            Notes        NVARCHAR(MAX) NULL,
            CreatedAt    DATETIME2     DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ColdChainShipmentItem')
        CREATE TABLE ColdChainShipmentItem (
            ItemID       INT IDENTITY PRIMARY KEY,
            ShipmentID   INT           NOT NULL,
            ProductName  NVARCHAR(200) NOT NULL,
            Quantity     DECIMAL(10,2) NULL,
            Unit         NVARCHAR(50)  NULL,
            Recipient    NVARCHAR(200) NULL,
            TempMinC     DECIMAL(5,2)  NULL,
            TempMaxC     DECIMAL(5,2)  NULL,
            Notes        NVARCHAR(500) NULL
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ColdChainMaintenance')
        CREATE TABLE ColdChainMaintenance (
            MaintenanceID   INT IDENTITY PRIMARY KEY,
            VehicleID       INT           NOT NULL,
            BusinessID      INT           NOT NULL,
            ServiceDate     DATE          NOT NULL,
            ServiceType     NVARCHAR(100) NOT NULL,
            ServiceProvider NVARCHAR(200) NULL,
            Technician      NVARCHAR(200) NULL,
            Cost            DECIMAL(10,2) NULL,
            OdometerMiles   INT           NULL,
            Notes           NVARCHAR(MAX) NULL,
            NextServiceDate DATE          NULL,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    # ── Advanced tables (new) ───────────────────────────────────────────────

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ColdChainShockEvent')
        CREATE TABLE ColdChainShockEvent (
            EventID      INT IDENTITY PRIMARY KEY,
            VehicleID    INT           NOT NULL,
            BusinessID   INT           NOT NULL,
            OccurredAt   DATETIME2     NOT NULL DEFAULT GETDATE(),
            PeakGForce   DECIMAL(5,2)  NOT NULL,
            DurationMs   INT           NULL,
            Axis         NVARCHAR(10)  NULL,
            ShipmentID   INT           NULL,
            LocationDesc NVARCHAR(500) NULL,
            GpsLat       DECIMAL(9,6)  NULL,
            GpsLon       DECIMAL(9,6)  NULL,
            Notes        NVARCHAR(1000) NULL
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ColdChainCustodyEvent')
        CREATE TABLE ColdChainCustodyEvent (
            EventID        INT IDENTITY PRIMARY KEY,
            VehicleID      INT           NOT NULL,
            BusinessID     INT           NOT NULL,
            OccurredAt     DATETIME2     NOT NULL DEFAULT GETDATE(),
            HandoverType   NVARCHAR(40)  NOT NULL,
            FromParty      NVARCHAR(200) NULL,
            ToParty        NVARCHAR(200) NULL,
            SignedBy       NVARCHAR(200) NULL,
            TempCAtHandover DECIMAL(5,2) NULL,
            HumidityAtHandover DECIMAL(5,2) NULL,
            GpsLat         DECIMAL(9,6)  NULL,
            GpsLon         DECIMAL(9,6)  NULL,
            ShipmentID     INT           NULL,
            PrevHash       NVARCHAR(64)  NULL,
            EventHash      NVARCHAR(64)  NULL,
            Notes          NVARCHAR(MAX) NULL
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ColdChainGeofenceZone')
        CREATE TABLE ColdChainGeofenceZone (
            ZoneID        INT IDENTITY PRIMARY KEY,
            BusinessID    INT           NOT NULL,
            ZoneName      NVARCHAR(200) NOT NULL,
            CenterLat     DECIMAL(9,6)  NOT NULL,
            CenterLon     DECIMAL(9,6)  NOT NULL,
            RadiusMeters  INT           NOT NULL DEFAULT 200,
            ZoneType      NVARCHAR(30)  NULL,
            AlertOnEnter  BIT           NOT NULL DEFAULT 1,
            AlertOnExit   BIT           NOT NULL DEFAULT 1,
            CreatedAt     DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ColdChainGeofenceEvent')
        CREATE TABLE ColdChainGeofenceEvent (
            EventID      INT IDENTITY PRIMARY KEY,
            VehicleID    INT           NOT NULL,
            ZoneID       INT           NOT NULL,
            BusinessID   INT           NOT NULL,
            OccurredAt   DATETIME2     NOT NULL DEFAULT GETDATE(),
            EventType    NVARCHAR(10)  NOT NULL,
            GpsLat       DECIMAL(9,6)  NULL,
            GpsLon       DECIMAL(9,6)  NULL,
            AutoCheckIn  BIT           NOT NULL DEFAULT 0,
            Notes        NVARCHAR(500) NULL
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ColdChainShelfLife')
        CREATE TABLE ColdChainShelfLife (
            RecordID              INT IDENTITY PRIMARY KEY,
            VehicleID             INT           NOT NULL,
            BusinessID            INT           NOT NULL,
            ShipmentID            INT           NULL,
            ProductName           NVARCHAR(200) NOT NULL,
            ProductType           NVARCHAR(50)  NULL,
            OriginalShelfLifeDays INT           NOT NULL,
            AdjustedShelfLifeDays DECIMAL(5,1)  NOT NULL,
            DegradationPct        DECIMAL(5,2)  NULL,
            ExcursionMinutes      INT           NULL,
            MaxExcursionTempC     DECIMAL(5,2)  NULL,
            CalculatedAt          DATETIME2     DEFAULT GETDATE(),
            Notes                 NVARCHAR(MAX) NULL
        )
    """))

    db.commit()
    _tables_ready = True


def _ser(row):
    d = dict(row._mapping)
    for k, v in d.items():
        if hasattr(v, '__float__'):
            try:
                d[k] = float(v)
            except Exception:
                pass
    return d


def _compute_custody_hash(event_type, from_party, to_party, temp_c, occurred_at, prev_hash):
    payload = json.dumps({
        "type": event_type,
        "from": from_party or "",
        "to":   to_party or "",
        "temp": str(temp_c or ""),
        "at":   str(occurred_at),
        "prev": prev_hash or "",
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _compute_shelf_life(product_type, original_days, readings):
    """Q10 degradation model. Returns (adjusted_days, excursion_minutes, max_excursion_temp, degradation_pct)."""
    params = SHELF_LIFE_PARAMS.get(product_type, SHELF_LIFE_PARAMS["general"])
    t_ref, q10, base_days = params["t_ref"], params["q10"], params["base_days"]
    base_minutes = original_days * 24 * 60
    fraction_consumed = 0.0
    excursion_minutes = 0
    max_excursion_temp = None

    for i in range(1, len(readings)):
        prev = readings[i - 1]
        curr = readings[i]
        try:
            t_prev = datetime.fromisoformat(str(prev["RecordedAt"]).replace("Z", "+00:00"))
            t_curr = datetime.fromisoformat(str(curr["RecordedAt"]).replace("Z", "+00:00"))
            interval_min = abs((t_curr - t_prev).total_seconds()) / 60.0
        except Exception:
            continue
        temp = float(curr["TempC"])
        rate_factor = q10 ** ((temp - t_ref) / 10.0)
        fraction_consumed += (rate_factor * interval_min) / base_minutes
        if temp > t_ref:
            excursion_minutes += int(interval_min)
            if max_excursion_temp is None or temp > max_excursion_temp:
                max_excursion_temp = temp

    adjusted = max(0.0, original_days * (1.0 - fraction_consumed))
    degradation_pct = round(fraction_consumed * 100, 2)
    return round(adjusted, 1), excursion_minutes, max_excursion_temp, degradation_pct


# ── Vehicles ──────────────────────────────────────────────────────────────────

@router.get("/vehicles")
def list_vehicles(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(
        text("""
            SELECT v.VehicleID, v.BusinessID, v.VehicleName, v.LicensePlate,
                   v.DriverName, v.DriverPhone, v.MinTempC, v.MaxTempC,
                   v.IsActive, v.CreatedAt,
                   v.ReeferFuelPct, v.BatteryPct, v.LastPingAt, v.PowerAlertSent,
                   lr.TempC    AS LatestTempC,
                   lr.RecordedAt AS LatestReadingAt
            FROM ColdChainVehicle v
            OUTER APPLY (
                SELECT TOP 1 TempC, RecordedAt
                FROM ColdChainReading
                WHERE VehicleID = v.VehicleID
                ORDER BY RecordedAt DESC
            ) lr
            WHERE v.BusinessID = :bid
            ORDER BY v.VehicleName
        """),
        {"bid": business_id},
    ).fetchall()
    return [_ser(r) for r in rows]


@router.post("/vehicles")
def create_vehicle(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("VehicleName"):
        raise HTTPException(400, "BusinessID and VehicleName are required")
    row = db.execute(
        text("""
            INSERT INTO ColdChainVehicle
                (BusinessID, VehicleName, LicensePlate, DriverName, DriverPhone, MinTempC, MaxTempC)
            OUTPUT INSERTED.VehicleID
            VALUES (:bid, :name, :plate, :driver, :phone, :min_t, :max_t)
        """),
        {
            "bid":    body["BusinessID"],
            "name":   body["VehicleName"],
            "plate":  body.get("LicensePlate"),
            "driver": body.get("DriverName"),
            "phone":  body.get("DriverPhone"),
            "min_t":  body.get("MinTempC", -2.0),
            "max_t":  body.get("MaxTempC", 7.0),
        },
    ).fetchone()
    db.commit()
    return {"VehicleID": row[0]}


@router.put("/vehicles/{vehicle_id}")
def update_vehicle(vehicle_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    db.execute(
        text("""
            UPDATE ColdChainVehicle SET
                VehicleName  = COALESCE(:name,   VehicleName),
                LicensePlate = COALESCE(:plate,  LicensePlate),
                DriverName   = COALESCE(:driver, DriverName),
                DriverPhone  = COALESCE(:phone,  DriverPhone),
                MinTempC     = COALESCE(:min_t,  MinTempC),
                MaxTempC     = COALESCE(:max_t,  MaxTempC),
                IsActive     = COALESCE(:active, IsActive)
            WHERE VehicleID = :vid
        """),
        {
            "vid":    vehicle_id,
            "name":   body.get("VehicleName"),
            "plate":  body.get("LicensePlate"),
            "driver": body.get("DriverName"),
            "phone":  body.get("DriverPhone"),
            "min_t":  body.get("MinTempC"),
            "max_t":  body.get("MaxTempC"),
            "active": body.get("IsActive"),
        },
    )
    db.commit()
    return {"ok": True}


@router.patch("/vehicles/{vehicle_id}/power")
def update_vehicle_power(vehicle_id: int, body: dict, db: Session = Depends(get_db)):
    """Update reefer fuel %, tracker battery %, and ping timestamp."""
    _ensure_tables(db)
    db.execute(text("""
        UPDATE ColdChainVehicle SET
            ReeferFuelPct  = COALESCE(:fuel,    ReeferFuelPct),
            BatteryPct     = COALESCE(:battery, BatteryPct),
            LastPingAt     = COALESCE(:ping,    LastPingAt),
            PowerAlertSent = COALESCE(:alerted, PowerAlertSent)
        WHERE VehicleID = :vid
    """), {
        "vid":     vehicle_id,
        "fuel":    body.get("ReeferFuelPct"),
        "battery": body.get("BatteryPct"),
        "ping":    body.get("LastPingAt"),
        "alerted": body.get("PowerAlertSent"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/vehicles/{vehicle_id}")
def delete_vehicle(vehicle_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM ColdChainShockEvent   WHERE VehicleID = :vid"), {"vid": vehicle_id})
    db.execute(text("DELETE FROM ColdChainCustodyEvent WHERE VehicleID = :vid"), {"vid": vehicle_id})
    db.execute(text("DELETE FROM ColdChainGeofenceEvent WHERE VehicleID = :vid"), {"vid": vehicle_id})
    db.execute(text("DELETE FROM ColdChainShelfLife    WHERE VehicleID = :vid"), {"vid": vehicle_id})
    db.execute(text("DELETE FROM ColdChainReading      WHERE VehicleID = :vid"), {"vid": vehicle_id})
    db.execute(text("""
        DELETE ci FROM ColdChainShipmentItem ci
        JOIN ColdChainShipment s ON ci.ShipmentID = s.ShipmentID
        WHERE s.VehicleID = :vid
    """), {"vid": vehicle_id})
    db.execute(text("DELETE FROM ColdChainShipment     WHERE VehicleID = :vid"), {"vid": vehicle_id})
    db.execute(text("DELETE FROM ColdChainMaintenance  WHERE VehicleID = :vid"), {"vid": vehicle_id})
    db.execute(text("DELETE FROM ColdChainVehicle      WHERE VehicleID = :vid"), {"vid": vehicle_id})
    db.commit()
    return {"ok": True}


# ── Readings (multi-sensor) ────────────────────────────────────────────────────

@router.get("/vehicles/{vehicle_id}/readings")
def list_readings(
    vehicle_id: int,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    rows = db.execute(
        text(f"""
            SELECT TOP {limit}
                ReadingID, VehicleID, TempC, Humidity,
                EthyleneGasPPM, CO2PPM, LightLux, DoorOpenFlag,
                GpsLat, GpsLon, ShockGForce,
                LocationDesc, RecordedAt, Notes
            FROM ColdChainReading
            WHERE VehicleID = :vid
            ORDER BY RecordedAt DESC
        """),
        {"vid": vehicle_id},
    ).fetchall()
    return [_ser(r) for r in rows]


@router.post("/vehicles/{vehicle_id}/readings")
def add_reading(vehicle_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if body.get("TempC") is None:
        raise HTTPException(400, "TempC is required")
    row = db.execute(
        text("""
            INSERT INTO ColdChainReading
                (VehicleID, TempC, Humidity, EthyleneGasPPM, CO2PPM,
                 LightLux, DoorOpenFlag, GpsLat, GpsLon, ShockGForce,
                 LocationDesc, Notes)
            OUTPUT INSERTED.ReadingID
            VALUES (:vid, :temp, :hum, :ethylene, :co2,
                    :light, :door, :lat, :lon, :shock,
                    :loc, :notes)
        """),
        {
            "vid":      vehicle_id,
            "temp":     body["TempC"],
            "hum":      body.get("Humidity"),
            "ethylene": body.get("EthyleneGasPPM"),
            "co2":      body.get("CO2PPM"),
            "light":    body.get("LightLux"),
            "door":     1 if body.get("DoorOpenFlag") else 0,
            "lat":      body.get("GpsLat"),
            "lon":      body.get("GpsLon"),
            "shock":    body.get("ShockGForce"),
            "loc":      body.get("LocationDesc"),
            "notes":    body.get("Notes"),
        },
    ).fetchone()
    db.commit()
    return {"ReadingID": row[0]}


# ── Shock Events ───────────────────────────────────────────────────────────────

@router.get("/vehicles/{vehicle_id}/shocks")
def list_shocks(
    vehicle_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    rows = db.execute(
        text(f"""
            SELECT TOP {limit} *
            FROM ColdChainShockEvent
            WHERE VehicleID = :vid
            ORDER BY OccurredAt DESC
        """),
        {"vid": vehicle_id},
    ).fetchall()
    return [_ser(r) for r in rows]


@router.post("/vehicles/{vehicle_id}/shocks")
def add_shock(vehicle_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID"):
        raise HTTPException(400, "BusinessID is required")
    if body.get("PeakGForce") is None:
        raise HTTPException(400, "PeakGForce is required")
    row = db.execute(text("""
        INSERT INTO ColdChainShockEvent
            (VehicleID, BusinessID, OccurredAt, PeakGForce, DurationMs,
             Axis, ShipmentID, LocationDesc, GpsLat, GpsLon, Notes)
        OUTPUT INSERTED.EventID
        VALUES (:vid, :bid, COALESCE(:at, GETDATE()), :g, :dur,
                :axis, :sid, :loc, :lat, :lon, :notes)
    """), {
        "vid":   vehicle_id,
        "bid":   body["BusinessID"],
        "at":    body.get("OccurredAt"),
        "g":     body["PeakGForce"],
        "dur":   body.get("DurationMs"),
        "axis":  body.get("Axis"),
        "sid":   body.get("ShipmentID"),
        "loc":   body.get("LocationDesc"),
        "lat":   body.get("GpsLat"),
        "lon":   body.get("GpsLon"),
        "notes": body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"EventID": row[0]}


@router.delete("/shocks/{event_id}")
def delete_shock(event_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM ColdChainShockEvent WHERE EventID = :id"), {"id": event_id})
    db.commit()
    return {"ok": True}


# ── Chain of Custody ──────────────────────────────────────────────────────────

@router.get("/vehicles/{vehicle_id}/custody")
def list_custody(vehicle_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(
        text("""
            SELECT * FROM ColdChainCustodyEvent
            WHERE VehicleID = :vid
            ORDER BY OccurredAt ASC
        """),
        {"vid": vehicle_id},
    ).fetchall()
    return [_ser(r) for r in rows]


@router.post("/vehicles/{vehicle_id}/custody")
def add_custody(vehicle_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID"):
        raise HTTPException(400, "BusinessID is required")
    if not body.get("HandoverType"):
        raise HTTPException(400, "HandoverType is required")

    # Get previous event hash for chain integrity
    prev_row = db.execute(text("""
        SELECT TOP 1 EventHash FROM ColdChainCustodyEvent
        WHERE VehicleID = :vid
        ORDER BY OccurredAt DESC
    """), {"vid": vehicle_id}).fetchone()
    prev_hash = prev_row[0] if prev_row else None

    occurred_at = body.get("OccurredAt") or datetime.now(timezone.utc).isoformat()
    event_hash = _compute_custody_hash(
        body.get("HandoverType"),
        body.get("FromParty"),
        body.get("ToParty"),
        body.get("TempCAtHandover"),
        occurred_at,
        prev_hash,
    )

    row = db.execute(text("""
        INSERT INTO ColdChainCustodyEvent
            (VehicleID, BusinessID, OccurredAt, HandoverType, FromParty, ToParty,
             SignedBy, TempCAtHandover, HumidityAtHandover, GpsLat, GpsLon,
             ShipmentID, PrevHash, EventHash, Notes)
        OUTPUT INSERTED.EventID
        VALUES (:vid, :bid, COALESCE(:at, GETDATE()), :htype, :from_p, :to_p,
                :signed, :temp, :hum, :lat, :lon,
                :sid, :prev, :hash, :notes)
    """), {
        "vid":    vehicle_id,
        "bid":    body["BusinessID"],
        "at":     body.get("OccurredAt"),
        "htype":  body["HandoverType"],
        "from_p": body.get("FromParty"),
        "to_p":   body.get("ToParty"),
        "signed": body.get("SignedBy"),
        "temp":   body.get("TempCAtHandover"),
        "hum":    body.get("HumidityAtHandover"),
        "lat":    body.get("GpsLat"),
        "lon":    body.get("GpsLon"),
        "sid":    body.get("ShipmentID"),
        "prev":   prev_hash,
        "hash":   event_hash,
        "notes":  body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"EventID": row[0], "EventHash": event_hash}


# ── Geofence Zones & Events ───────────────────────────────────────────────────

@router.get("/geofence-zones")
def list_geofence_zones(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(
        text("SELECT * FROM ColdChainGeofenceZone WHERE BusinessID = :bid ORDER BY ZoneName"),
        {"bid": business_id},
    ).fetchall()
    return [_ser(r) for r in rows]


@router.post("/geofence-zones")
def create_geofence_zone(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("ZoneName"):
        raise HTTPException(400, "BusinessID and ZoneName are required")
    row = db.execute(text("""
        INSERT INTO ColdChainGeofenceZone
            (BusinessID, ZoneName, CenterLat, CenterLon, RadiusMeters,
             ZoneType, AlertOnEnter, AlertOnExit)
        OUTPUT INSERTED.ZoneID
        VALUES (:bid, :name, :lat, :lon, :radius, :ztype, :on_enter, :on_exit)
    """), {
        "bid":      body["BusinessID"],
        "name":     body["ZoneName"],
        "lat":      body.get("CenterLat", 0),
        "lon":      body.get("CenterLon", 0),
        "radius":   body.get("RadiusMeters", 200),
        "ztype":    body.get("ZoneType"),
        "on_enter": 1 if body.get("AlertOnEnter", True) else 0,
        "on_exit":  1 if body.get("AlertOnExit", True) else 0,
    }).fetchone()
    db.commit()
    return {"ZoneID": row[0]}


@router.delete("/geofence-zones/{zone_id}")
def delete_geofence_zone(zone_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM ColdChainGeofenceEvent WHERE ZoneID = :id"), {"id": zone_id})
    db.execute(text("DELETE FROM ColdChainGeofenceZone  WHERE ZoneID = :id"), {"id": zone_id})
    db.commit()
    return {"ok": True}


@router.get("/vehicles/{vehicle_id}/geofence-events")
def list_geofence_events(
    vehicle_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    rows = db.execute(
        text(f"""
            SELECT TOP {limit}
                ge.*, gz.ZoneName, gz.ZoneType
            FROM ColdChainGeofenceEvent ge
            JOIN ColdChainGeofenceZone gz ON gz.ZoneID = ge.ZoneID
            WHERE ge.VehicleID = :vid
            ORDER BY ge.OccurredAt DESC
        """),
        {"vid": vehicle_id},
    ).fetchall()
    return [_ser(r) for r in rows]


@router.post("/vehicles/{vehicle_id}/geofence-events")
def add_geofence_event(vehicle_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("ZoneID"):
        raise HTTPException(400, "BusinessID and ZoneID are required")
    if body.get("EventType") not in ("enter", "exit"):
        raise HTTPException(400, "EventType must be 'enter' or 'exit'")
    row = db.execute(text("""
        INSERT INTO ColdChainGeofenceEvent
            (VehicleID, ZoneID, BusinessID, OccurredAt, EventType,
             GpsLat, GpsLon, AutoCheckIn, Notes)
        OUTPUT INSERTED.EventID
        VALUES (:vid, :zid, :bid, COALESCE(:at, GETDATE()), :etype,
                :lat, :lon, :auto, :notes)
    """), {
        "vid":   vehicle_id,
        "zid":   body["ZoneID"],
        "bid":   body["BusinessID"],
        "at":    body.get("OccurredAt"),
        "etype": body["EventType"],
        "lat":   body.get("GpsLat"),
        "lon":   body.get("GpsLon"),
        "auto":  1 if body.get("AutoCheckIn") else 0,
        "notes": body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"EventID": row[0]}


# ── Shelf-Life Calculation ─────────────────────────────────────────────────────

@router.get("/vehicles/{vehicle_id}/shelf-life")
def list_shelf_life(vehicle_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(
        text("""
            SELECT TOP 50 * FROM ColdChainShelfLife
            WHERE VehicleID = :vid
            ORDER BY CalculatedAt DESC
        """),
        {"vid": vehicle_id},
    ).fetchall()
    return [_ser(r) for r in rows]


@router.post("/vehicles/{vehicle_id}/shelf-life")
def calculate_shelf_life(vehicle_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    """
    Calculate adjusted shelf life using the Q10 degradation model.
    Uses actual temperature readings from this vehicle over the last `hours` hours
    (default 48h) or from a specific ShipmentID time window.
    """
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("ProductName"):
        raise HTTPException(400, "BusinessID and ProductName are required")
    if not body.get("OriginalShelfLifeDays"):
        raise HTTPException(400, "OriginalShelfLifeDays is required")

    product_type = body.get("ProductType", "general")
    original_days = int(body["OriginalShelfLifeDays"])
    hours = int(body.get("LookbackHours", 48))

    # Fetch readings for the calculation window
    if body.get("ShipmentID"):
        # Use readings between shipment DepartedAt and ArrivedAt
        shipment = db.execute(
            text("SELECT DepartedAt, ArrivedAt FROM ColdChainShipment WHERE ShipmentID = :sid"),
            {"sid": body["ShipmentID"]},
        ).fetchone()
        if shipment and shipment[0]:
            raw = db.execute(text("""
                SELECT TempC, RecordedAt FROM ColdChainReading
                WHERE VehicleID = :vid
                  AND RecordedAt BETWEEN :dep AND COALESCE(:arr, GETDATE())
                ORDER BY RecordedAt ASC
            """), {"vid": vehicle_id, "dep": shipment[0], "arr": shipment[1]}).fetchall()
        else:
            raw = []
    else:
        raw = db.execute(text(f"""
            SELECT TempC, RecordedAt FROM ColdChainReading
            WHERE VehicleID = :vid
              AND RecordedAt >= DATEADD(HOUR, -{hours}, GETDATE())
            ORDER BY RecordedAt ASC
        """), {"vid": vehicle_id}).fetchall()

    readings = [{"TempC": r[0], "RecordedAt": r[1]} for r in raw]

    if len(readings) < 2:
        adjusted, excursion_min, max_excursion, degradation_pct = float(original_days), 0, None, 0.0
    else:
        adjusted, excursion_min, max_excursion, degradation_pct = _compute_shelf_life(
            product_type, original_days, readings
        )

    row = db.execute(text("""
        INSERT INTO ColdChainShelfLife
            (VehicleID, BusinessID, ShipmentID, ProductName, ProductType,
             OriginalShelfLifeDays, AdjustedShelfLifeDays, DegradationPct,
             ExcursionMinutes, MaxExcursionTempC, Notes)
        OUTPUT INSERTED.RecordID
        VALUES (:vid, :bid, :sid, :prod, :ptype,
                :orig, :adj, :deg,
                :exc, :maxtemp, :notes)
    """), {
        "vid":     vehicle_id,
        "bid":     body["BusinessID"],
        "sid":     body.get("ShipmentID"),
        "prod":    body["ProductName"],
        "ptype":   product_type,
        "orig":    original_days,
        "adj":     adjusted,
        "deg":     degradation_pct,
        "exc":     excursion_min,
        "maxtemp": max_excursion,
        "notes":   body.get("Notes"),
    }).fetchone()
    db.commit()

    action = "Normal distribution"
    if adjusted <= 0:
        action = "Discard — shelf life exhausted"
    elif adjusted < original_days * 0.4:
        action = "Express Sale / Priority dispatch recommended"
    elif adjusted < original_days * 0.7:
        action = "Expedite delivery — shelf life reduced"

    return {
        "RecordID": row[0],
        "OriginalShelfLifeDays": original_days,
        "AdjustedShelfLifeDays": adjusted,
        "DegradationPct": degradation_pct,
        "ExcursionMinutes": excursion_min,
        "MaxExcursionTempC": max_excursion,
        "ReadingsAnalyzed": len(readings),
        "RecommendedAction": action,
    }


# ── Shipments ─────────────────────────────────────────────────────────────────

@router.get("/vehicles/{vehicle_id}/shipments")
def list_shipments(
    vehicle_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    rows = db.execute(
        text(f"""
            SELECT TOP {limit}
                s.ShipmentID, s.VehicleID, s.BusinessID, s.RunDate, s.RouteLabel,
                s.Status, s.DriverName, s.DepartedAt, s.ArrivedAt,
                s.TotalMiles, s.Notes, s.CreatedAt,
                COUNT(i.ItemID) AS ItemCount
            FROM ColdChainShipment s
            LEFT JOIN ColdChainShipmentItem i ON i.ShipmentID = s.ShipmentID
            WHERE s.VehicleID = :vid
            GROUP BY s.ShipmentID, s.VehicleID, s.BusinessID, s.RunDate, s.RouteLabel,
                     s.Status, s.DriverName, s.DepartedAt, s.ArrivedAt,
                     s.TotalMiles, s.Notes, s.CreatedAt
            ORDER BY s.RunDate DESC
        """),
        {"vid": vehicle_id},
    ).fetchall()
    return [_ser(r) for r in rows]


@router.post("/vehicles/{vehicle_id}/shipments")
def create_shipment(vehicle_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("RunDate"):
        raise HTTPException(400, "RunDate is required")
    if not body.get("BusinessID"):
        raise HTTPException(400, "BusinessID is required")
    row = db.execute(
        text("""
            INSERT INTO ColdChainShipment
                (VehicleID, BusinessID, RunDate, RouteLabel, Status,
                 DriverName, DepartedAt, ArrivedAt, TotalMiles, Notes)
            OUTPUT INSERTED.ShipmentID
            VALUES (:vid, :bid, :date, :label, :status,
                    :driver, :dep, :arr, :miles, :notes)
        """),
        {
            "vid":    vehicle_id,
            "bid":    body["BusinessID"],
            "date":   body["RunDate"],
            "label":  body.get("RouteLabel"),
            "status": body.get("Status", "completed"),
            "driver": body.get("DriverName"),
            "dep":    body.get("DepartedAt"),
            "arr":    body.get("ArrivedAt"),
            "miles":  body.get("TotalMiles"),
            "notes":  body.get("Notes"),
        },
    ).fetchone()
    shipment_id = row[0]
    for item in body.get("Items", []):
        db.execute(text("""
            INSERT INTO ColdChainShipmentItem
                (ShipmentID, ProductName, Quantity, Unit, Recipient, TempMinC, TempMaxC, Notes)
            VALUES (:sid, :name, :qty, :unit, :recip, :tmin, :tmax, :notes)
        """), {
            "sid":   shipment_id,
            "name":  item.get("ProductName", ""),
            "qty":   item.get("Quantity"),
            "unit":  item.get("Unit"),
            "recip": item.get("Recipient"),
            "tmin":  item.get("TempMinC"),
            "tmax":  item.get("TempMaxC"),
            "notes": item.get("Notes"),
        })
    db.commit()
    return {"ShipmentID": shipment_id}


@router.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    s = db.execute(
        text("SELECT * FROM ColdChainShipment WHERE ShipmentID = :sid"),
        {"sid": shipment_id},
    ).fetchone()
    if not s:
        raise HTTPException(404, "Shipment not found")
    result = _ser(s)
    items = db.execute(
        text("SELECT * FROM ColdChainShipmentItem WHERE ShipmentID = :sid ORDER BY ItemID"),
        {"sid": shipment_id},
    ).fetchall()
    result["Items"] = [_ser(i) for i in items]
    return result


@router.post("/shipments/{shipment_id}/items")
def add_shipment_item(shipment_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("ProductName"):
        raise HTTPException(400, "ProductName is required")
    row = db.execute(
        text("""
            INSERT INTO ColdChainShipmentItem
                (ShipmentID, ProductName, Quantity, Unit, Recipient, TempMinC, TempMaxC, Notes)
            OUTPUT INSERTED.ItemID
            VALUES (:sid, :name, :qty, :unit, :recip, :tmin, :tmax, :notes)
        """),
        {
            "sid":   shipment_id,
            "name":  body["ProductName"],
            "qty":   body.get("Quantity"),
            "unit":  body.get("Unit"),
            "recip": body.get("Recipient"),
            "tmin":  body.get("TempMinC"),
            "tmax":  body.get("TempMaxC"),
            "notes": body.get("Notes"),
        },
    ).fetchone()
    db.commit()
    return {"ItemID": row[0]}


@router.patch("/shipments/{shipment_id}")
def update_shipment(shipment_id: int, body: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("""
        UPDATE ColdChainShipment SET
            RouteLabel  = COALESCE(:label,  RouteLabel),
            Status      = COALESCE(:status, Status),
            DriverName  = COALESCE(:driver, DriverName),
            DepartedAt  = COALESCE(:dep,    DepartedAt),
            ArrivedAt   = COALESCE(:arr,    ArrivedAt),
            TotalMiles  = COALESCE(:miles,  TotalMiles),
            Notes       = COALESCE(:notes,  Notes)
        WHERE ShipmentID = :sid
    """), {
        "sid":    shipment_id,
        "label":  body.get("RouteLabel"),
        "status": body.get("Status"),
        "driver": body.get("DriverName"),
        "dep":    body.get("DepartedAt"),
        "arr":    body.get("ArrivedAt"),
        "miles":  body.get("TotalMiles"),
        "notes":  body.get("Notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/shipments/{shipment_id}")
def delete_shipment(shipment_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM ColdChainShipmentItem WHERE ShipmentID = :sid"), {"sid": shipment_id})
    db.execute(text("DELETE FROM ColdChainShipment     WHERE ShipmentID = :sid"), {"sid": shipment_id})
    db.commit()
    return {"ok": True}


# ── Maintenance ───────────────────────────────────────────────────────────────

@router.get("/vehicles/{vehicle_id}/maintenance")
def list_maintenance(vehicle_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(
        text("SELECT * FROM ColdChainMaintenance WHERE VehicleID = :vid ORDER BY ServiceDate DESC"),
        {"vid": vehicle_id},
    ).fetchall()
    return [_ser(r) for r in rows]


@router.post("/vehicles/{vehicle_id}/maintenance")
def add_maintenance(vehicle_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("ServiceDate") or not body.get("ServiceType"):
        raise HTTPException(400, "ServiceDate and ServiceType are required")
    if not body.get("BusinessID"):
        raise HTTPException(400, "BusinessID is required")
    row = db.execute(
        text("""
            INSERT INTO ColdChainMaintenance
                (VehicleID, BusinessID, ServiceDate, ServiceType, ServiceProvider,
                 Technician, Cost, OdometerMiles, Notes, NextServiceDate)
            OUTPUT INSERTED.MaintenanceID
            VALUES (:vid, :bid, :date, :stype, :provider,
                    :tech, :cost, :odo, :notes, :next)
        """),
        {
            "vid":      vehicle_id,
            "bid":      body["BusinessID"],
            "date":     body["ServiceDate"],
            "stype":    body["ServiceType"],
            "provider": body.get("ServiceProvider"),
            "tech":     body.get("Technician"),
            "cost":     body.get("Cost"),
            "odo":      body.get("OdometerMiles"),
            "notes":    body.get("Notes"),
            "next":     body.get("NextServiceDate"),
        },
    ).fetchone()
    db.commit()
    return {"MaintenanceID": row[0]}


@router.patch("/maintenance/{maintenance_id}")
def update_maintenance(maintenance_id: int, body: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("""
        UPDATE ColdChainMaintenance SET
            ServiceType     = COALESCE(:stype,    ServiceType),
            ServiceProvider = COALESCE(:provider, ServiceProvider),
            Technician      = COALESCE(:tech,     Technician),
            Cost            = COALESCE(:cost,     Cost),
            OdometerMiles   = COALESCE(:odo,      OdometerMiles),
            Notes           = COALESCE(:notes,    Notes),
            NextServiceDate = COALESCE(:next,     NextServiceDate)
        WHERE MaintenanceID = :mid
    """), {
        "mid":      maintenance_id,
        "stype":    body.get("ServiceType"),
        "provider": body.get("ServiceProvider"),
        "tech":     body.get("Technician"),
        "cost":     body.get("Cost"),
        "odo":      body.get("OdometerMiles"),
        "notes":    body.get("Notes"),
        "next":     body.get("NextServiceDate"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/maintenance/{maintenance_id}")
def delete_maintenance(maintenance_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM ColdChainMaintenance WHERE MaintenanceID = :mid"), {"mid": maintenance_id})
    db.commit()
    return {"ok": True}
