from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime, timedelta
import requests
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/chill", tags=["chilling_hours"])
_ddl_done = False

# ── Chill models ─────────────────────────────────────────────────────────────
def _utah_units(temp_f: float) -> float:
    """Utah model: weighted chill unit per hour."""
    if temp_f <= 34: return -1.0
    if temp_f <= 36: return 0.5
    if temp_f <= 48: return 1.0
    if temp_f <= 54: return 0.5
    if temp_f <= 60: return 0.0
    if temp_f <= 65: return -0.5
    return -1.0

def _simple_units(temp_f: float) -> float:
    """Simple model: 1 unit for each hour between 32–45°F."""
    return 1.0 if 32 <= temp_f <= 45 else 0.0

def calc_daily_chill(min_f: float, max_f: float, model: str) -> float:
    avg = (min_f + max_f) / 2
    if model == "utah":
        return _utah_units(avg) * 24
    return _simple_units(avg) * 24

def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cur = db.cursor()
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ChillCultivar')
    CREATE TABLE ChillCultivar (
        CultivarID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        CropType NVARCHAR(80) NOT NULL,
        CultivarName NVARCHAR(120) NOT NULL,
        RequiredChillHours DECIMAL(8,1) NOT NULL,
        BaseChillTempF DECIMAL(5,1) NOT NULL DEFAULT 32,
        MaxChillTempF DECIMAL(5,1) NOT NULL DEFAULT 45,
        BloomGDDAfterDormancy DECIMAL(7,1),
        Model NVARCHAR(30) NOT NULL DEFAULT 'simple',
        Notes NVARCHAR(500),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ChillHourReading')
    CREATE TABLE ChillHourReading (
        ReadingID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        FieldID NVARCHAR(80),
        ReadingDate DATE NOT NULL,
        MinTempF DECIMAL(6,2) NOT NULL,
        MaxTempF DECIMAL(6,2) NOT NULL,
        AvgTempF AS ((MinTempF+MaxTempF)/2) PERSISTED,
        ChillUnitsDay DECIMAL(8,2) NOT NULL,
        CumulativeUnits DECIMAL(10,2),
        Season NVARCHAR(20),
        Model NVARCHAR(30) NOT NULL DEFAULT 'simple',
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ChillForecast')
    CREATE TABLE ChillForecast (
        ForecastID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        FieldID NVARCHAR(80),
        CultivarID INT,
        Season NVARCHAR(20),
        ProjectedBloomDate DATE,
        DaysToBloom INT,
        ChillDeficit DECIMAL(8,2),
        ConfidenceLevel NVARCHAR(20),
        CalculatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    db.commit()
    _ddl_done = True


class ReadingIn(BaseModel):
    field_id: Optional[str] = None
    reading_date: date
    min_temp_f: float
    max_temp_f: float
    season: Optional[str] = None
    model: str = "simple"

class BulkReadingsIn(BaseModel):
    readings: List[ReadingIn]

class CultivarIn(BaseModel):
    crop_type: str
    cultivar_name: str
    required_chill_hours: float
    base_chill_temp_f: float = 32.0
    max_chill_temp_f: float = 45.0
    bloom_gdd_after_dormancy: Optional[float] = None
    model: str = "simple"
    notes: Optional[str] = None


@router.post("/readings", status_code=201)
def ingest_readings(body: BulkReadingsIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    inserted = 0
    for r in body.readings:
        units = calc_daily_chill(r.min_temp_f, r.max_temp_f, r.model)
        season = r.season or str(r.reading_date.year)
        # running cumulative for this field+season
        cur.execute("""
            SELECT ISNULL(SUM(ChillUnitsDay),0) FROM ChillHourReading
            WHERE BusinessID=? AND ISNULL(FieldID,'')=ISNULL(?,'') AND Season=?
              AND ReadingDate<?
        """, [bid, r.field_id, season, str(r.reading_date)])
        cumulative = float(cur.fetchone()[0]) + units
        cur.execute("""
            MERGE ChillHourReading AS target
            USING (SELECT ? AS BusinessID, ? AS FieldID, ? AS ReadingDate) AS src
            ON target.BusinessID=src.BusinessID AND ISNULL(target.FieldID,'')=ISNULL(src.FieldID,'')
               AND target.ReadingDate=src.ReadingDate AND target.Model=?
            WHEN MATCHED THEN UPDATE SET
                MinTempF=?, MaxTempF=?, ChillUnitsDay=?, CumulativeUnits=?, Season=?
            WHEN NOT MATCHED THEN INSERT
                (BusinessID,FieldID,ReadingDate,MinTempF,MaxTempF,ChillUnitsDay,CumulativeUnits,Season,Model)
                VALUES (?,?,?,?,?,?,?,?,?);
        """, [bid, r.field_id, str(r.reading_date), r.model,
              r.min_temp_f, r.max_temp_f, units, cumulative, season,
              bid, r.field_id, str(r.reading_date), r.min_temp_f, r.max_temp_f, units, cumulative, season, r.model])
        inserted += 1
    db.commit()
    return {"inserted": inserted}


@router.get("/accumulation")
def accumulation(
    field_id: Optional[str] = None,
    season: Optional[str] = None,
    model: str = "simple",
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    season = season or str(date.today().year)
    filters = ["BusinessID=?", "Season=?", "Model=?"]
    params: list = [bid, season, model]
    if field_id:
        filters.append("FieldID=?"); params.append(field_id)
    cur.execute(f"""
        SELECT ReadingDate, MinTempF, MaxTempF, AvgTempF, ChillUnitsDay, CumulativeUnits
        FROM ChillHourReading WHERE {' AND '.join(filters)}
        ORDER BY ReadingDate ASC
    """, params)
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    total = float(rows[-1]["CumulativeUnits"]) if rows else 0
    return {"season": season, "model": model, "total_chill_units": total, "readings": rows}


@router.get("/dashboard")
def dashboard(season: Optional[str] = None, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    season = season or str(date.today().year)
    cur = db.cursor()
    # summary per field
    cur.execute("""
        SELECT ISNULL(FieldID,'(All Fields)') AS FieldID,
               SUM(ChillUnitsDay) AS TotalUnits,
               MIN(ReadingDate) AS FirstDate,
               MAX(ReadingDate) AS LastDate,
               COUNT(*) AS Days
        FROM ChillHourReading
        WHERE BusinessID=? AND Season=?
        GROUP BY FieldID
        ORDER BY TotalUnits DESC
    """, [bid, season])
    cols = [c[0] for c in cur.description]
    fields = [dict(zip(cols, r)) for r in cur.fetchall()]
    # cultivar thresholds for comparison
    cur.execute("SELECT * FROM ChillCultivar WHERE BusinessID=? ORDER BY RequiredChillHours", [bid])
    cols2 = [c[0] for c in cur.description]
    cultivars = [dict(zip(cols2, r)) for r in cur.fetchall()]
    return {"season": season, "fields": fields, "cultivars": cultivars}


@router.get("/cultivars")
def list_cultivars(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT * FROM ChillCultivar WHERE BusinessID=? ORDER BY CropType, RequiredChillHours", [bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

@router.post("/cultivars", status_code=201)
def create_cultivar(body: CultivarIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        INSERT INTO ChillCultivar
            (BusinessID,CropType,CultivarName,RequiredChillHours,BaseChillTempF,MaxChillTempF,
             BloomGDDAfterDormancy,Model,Notes)
        OUTPUT INSERTED.CultivarID VALUES (?,?,?,?,?,?,?,?,?)
    """, [bid, body.crop_type, body.cultivar_name, body.required_chill_hours,
          body.base_chill_temp_f, body.max_chill_temp_f, body.bloom_gdd_after_dormancy,
          body.model, body.notes])
    cid = cur.fetchone()[0]
    db.commit()
    return {"cultivar_id": cid}


@router.get("/forecast")
def forecast(
    field_id: Optional[str] = None,
    cultivar_id: Optional[int] = None,
    season: Optional[str] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    """Predict bloom date: when chill requirement is met + GDD accumulation estimate."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    season = season or str(date.today().year)
    cur = db.cursor()

    # current accumulated units for this field
    filters = ["BusinessID=?", "Season=?"]
    params: list = [bid, season]
    if field_id:
        filters.append("FieldID=?"); params.append(field_id)
    cur.execute(f"SELECT ISNULL(SUM(ChillUnitsDay),0) FROM ChillHourReading WHERE {' AND '.join(filters)}", params)
    current_units = float(cur.fetchone()[0])

    results = []
    if cultivar_id:
        cur.execute("SELECT * FROM ChillCultivar WHERE CultivarID=? AND BusinessID=?", [cultivar_id, bid])
        cultivars = [cur.fetchone()]
        if cultivars[0] is None:
            raise HTTPException(404, "Cultivar not found")
        col_names = [c[0] for c in cur.description]
        cultivars = [dict(zip(col_names, cultivars[0]))]
    else:
        cur.execute("SELECT * FROM ChillCultivar WHERE BusinessID=?", [bid])
        col_names = [c[0] for c in cur.description]
        cultivars = [dict(zip(col_names, r)) for r in cur.fetchall()]

    # estimate remaining chill accumulation based on trailing 30-day rate
    cur.execute(f"""
        SELECT AVG(ChillUnitsDay) FROM ChillHourReading
        WHERE BusinessID=? AND ISNULL(FieldID,'')=ISNULL(?,'')
          AND ReadingDate >= DATEADD(day,-30,GETDATE())
    """, [bid, field_id])
    row = cur.fetchone()
    daily_rate = float(row[0]) if row and row[0] else 1.0

    for c in cultivars:
        deficit = float(c["RequiredChillHours"]) - current_units
        if deficit <= 0:
            days_to_dormancy_break = 0
            confidence = "high"
        elif daily_rate > 0:
            days_to_dormancy_break = int(deficit / daily_rate) + 1
            confidence = "medium" if deficit < 200 else "low"
        else:
            days_to_dormancy_break = None
            confidence = "insufficient_data"

        bloom_date = None
        if days_to_dormancy_break is not None:
            dormancy_break = date.today() + timedelta(days=days_to_dormancy_break)
            # add ~21 days for GDD accumulation post-dormancy as rough estimate
            gdd_days = 21
            if c.get("BloomGDDAfterDormancy"):
                gdd_days = max(7, int(float(c["BloomGDDAfterDormancy"]) / 15))
            bloom_date = dormancy_break + timedelta(days=gdd_days)

        results.append({
            "cultivar_id": c["CultivarID"],
            "cultivar_name": c["CultivarName"],
            "crop_type": c["CropType"],
            "required_chill_units": float(c["RequiredChillHours"]),
            "current_chill_units": current_units,
            "chill_deficit": max(0, float(c["RequiredChillHours"]) - current_units),
            "dormancy_break_in_days": days_to_dormancy_break,
            "projected_bloom_date": bloom_date.isoformat() if bloom_date else None,
            "confidence": confidence,
        })

    return {"field_id": field_id, "season": season, "forecasts": results}


@router.post("/import-from-weather", status_code=201)
def import_from_weather(
    lat: float,
    lon: float,
    field_id: Optional[str] = None,
    season: Optional[str] = None,
    days: int = 7,
    model: str = "simple",
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    """Fetch historical daily min/max temps from Open-Meteo and import as chill readings."""
    _ensure_tables(db)
    days = min(max(days, 1), 90)
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min",
                "temperature_unit": "fahrenheit",
                "timezone": "auto",
                "past_days": days,
                "forecast_days": 0,
            },
            timeout=10,
        )
    except Exception as e:
        raise HTTPException(502, f"Open-Meteo unreachable: {e}")
    if resp.status_code != 200:
        raise HTTPException(502, f"Open-Meteo error {resp.status_code}")

    dly = resp.json().get("daily", {})
    dates = dly.get("time", [])
    highs = dly.get("temperature_2m_max", [])
    lows  = dly.get("temperature_2m_min", [])
    if not dates:
        raise HTTPException(422, "No daily data returned from weather service")

    bid = user["BusinessID"]
    cur = db.cursor()
    imported = 0
    for i, d in enumerate(dates):
        max_f = highs[i] if highs[i] is not None else 0.0
        min_f = lows[i]  if lows[i]  is not None else 0.0
        reading_date = date.fromisoformat(d)
        units = calc_daily_chill(min_f, max_f, model)
        s = season or str(reading_date.year)
        cur.execute("""
            SELECT ISNULL(SUM(ChillUnitsDay),0) FROM ChillHourReading
            WHERE BusinessID=? AND ISNULL(FieldID,'')=ISNULL(?,'') AND Season=? AND ReadingDate<?
        """, [bid, field_id, s, str(reading_date)])
        cumulative = float(cur.fetchone()[0]) + units
        cur.execute("""
            MERGE ChillHourReading AS target
            USING (SELECT ? AS BusinessID, ? AS FieldID, ? AS ReadingDate) AS src
            ON target.BusinessID=src.BusinessID AND ISNULL(target.FieldID,'')=ISNULL(src.FieldID,'')
               AND target.ReadingDate=src.ReadingDate AND target.Model=?
            WHEN MATCHED THEN UPDATE SET
                MinTempF=?, MaxTempF=?, ChillUnitsDay=?, CumulativeUnits=?, Season=?
            WHEN NOT MATCHED THEN INSERT
                (BusinessID,FieldID,ReadingDate,MinTempF,MaxTempF,ChillUnitsDay,CumulativeUnits,Season,Model)
                VALUES (?,?,?,?,?,?,?,?,?);
        """, [bid, field_id, str(reading_date), model,
              min_f, max_f, units, cumulative, s,
              bid, field_id, str(reading_date), min_f, max_f, units, cumulative, s, model])
        imported += 1
    db.commit()
    return {"imported": imported, "lat": lat, "lon": lon, "days": days, "model": model}


@router.get("/season-comparison")
def season_comparison(field_id: Optional[str] = None, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    """Compare chill accumulation across seasons."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    filters = ["BusinessID=?"]
    params: list = [bid]
    if field_id:
        filters.append("ISNULL(FieldID,'')=ISNULL(?,'')"); params.append(field_id)
    cur.execute(f"""
        SELECT Season, SUM(ChillUnitsDay) AS TotalUnits, COUNT(*) AS Days,
               MIN(ReadingDate) AS SeasonStart, MAX(ReadingDate) AS SeasonEnd
        FROM ChillHourReading
        WHERE {' AND '.join(filters)}
        GROUP BY Season ORDER BY Season DESC
    """, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
