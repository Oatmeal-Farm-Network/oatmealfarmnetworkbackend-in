from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
import requests
from database import get_db

router = APIRouter(prefix="/api", tags=["weather"])


def _ensure_location_table(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'BusinessLocation')
        CREATE TABLE BusinessLocation (
            LocationID   INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID   INT NOT NULL,
            Latitude     DECIMAL(9,6) NOT NULL,
            Longitude    DECIMAL(9,6) NOT NULL,
            LocationName NVARCHAR(200),
            Timezone     NVARCHAR(100) DEFAULT 'auto',
            UpdatedAt    DATETIME2 DEFAULT GETDATE()
        )
    """))
    db.commit()


@router.get("/weather/location")
def get_weather_location(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_location_table(db)
    row = db.execute(
        text("SELECT Latitude, Longitude, LocationName, Timezone FROM BusinessLocation WHERE BusinessID = :bid"),
        {"bid": business_id},
    ).fetchone()
    if not row:
        return None
    return {"latitude": float(row[0]), "longitude": float(row[1]),
            "location_name": row[2], "timezone": row[3] or "auto"}


@router.post("/weather/location")
def save_weather_location(
    business_id: int,
    latitude: float,
    longitude: float,
    location_name: Optional[str] = None,
    timezone: Optional[str] = "auto",
    db: Session = Depends(get_db),
):
    _ensure_location_table(db)
    existing = db.execute(
        text("SELECT LocationID FROM BusinessLocation WHERE BusinessID = :bid"),
        {"bid": business_id},
    ).fetchone()
    if existing:
        db.execute(
            text("""
                UPDATE BusinessLocation
                SET Latitude = :lat, Longitude = :lon, LocationName = :name,
                    Timezone = :tz, UpdatedAt = GETDATE()
                WHERE BusinessID = :bid
            """),
            {"lat": latitude, "lon": longitude, "name": location_name, "tz": timezone, "bid": business_id},
        )
    else:
        db.execute(
            text("""
                INSERT INTO BusinessLocation (BusinessID, Latitude, Longitude, LocationName, Timezone)
                VALUES (:bid, :lat, :lon, :name, :tz)
            """),
            {"bid": business_id, "lat": latitude, "lon": longitude, "name": location_name, "tz": timezone},
        )
    db.commit()
    return {"ok": True}

_WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Freezing drizzle", 57: "Heavy freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Thunderstorm w/ heavy hail",
}

_DIRS = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]


def _wmo_label(code: int) -> str:
    return _WMO.get(code, "Unknown")


def _deg_to_compass(deg: float) -> str:
    if deg is None:
        return ""
    return _DIRS[round(deg / 22.5) % 16]


def _city_state(lat: float, lon: float) -> tuple[str, str]:
    """Best-effort reverse geocode. Returns ("", "") on any failure."""
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json"},
            headers={"User-Agent": "OatmealFarmNetwork/1.0"},
            timeout=5,
        )
        if r.status_code == 200:
            addr = r.json().get("address", {})
            city  = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("county", "")
            state = addr.get("state", "")
            return city, state
    except Exception:
        pass
    return "", ""


@router.get("/weather")
def get_weather(lat: float, lon: float):
    """
    Fetch current conditions + hourly + 7-day forecast using Open-Meteo.
    No API key required. Covers global locations.
    """
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude":  lat,
                "longitude": lon,
                "current": (
                    "temperature_2m,apparent_temperature,"
                    "relative_humidity_2m,weather_code,"
                    "wind_speed_10m,wind_direction_10m"
                ),
                "hourly": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit":  "mph",
                "timezone": "auto",
                "forecast_days": 7,
            },
            timeout=10,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Open-Meteo unreachable: {e}")

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Open-Meteo error {resp.status_code}")

    data = resp.json()
    cur  = data.get("current", {})
    hrly = data.get("hourly", {})
    dly  = data.get("daily", {})

    current = {
        "temp_f":      cur.get("temperature_2m"),
        "feelslike_f": cur.get("apparent_temperature"),
        "wind_mph":    cur.get("wind_speed_10m"),
        "wind_dir":    _deg_to_compass(cur.get("wind_direction_10m")),
        "humidity":    cur.get("relative_humidity_2m"),
        "condition":   _wmo_label(cur.get("weather_code", 0)),
        "icon":        None,
    }

    times  = hrly.get("time", [])
    temps  = hrly.get("temperature_2m", [])
    wcodes = hrly.get("weather_code", [])
    hourly = [
        {"time": times[i], "temp_f": temps[i], "icon": None, "condition": _wmo_label(wcodes[i])}
        for i in range(min(24, len(times)))
    ]

    dates  = dly.get("time", [])
    highs  = dly.get("temperature_2m_max", [])
    lows   = dly.get("temperature_2m_min", [])
    dcodes = dly.get("weather_code", [])
    daily  = [
        {
            "date":      dates[i],
            "high_f":    highs[i],
            "low_f":     lows[i],
            "condition": _wmo_label(dcodes[i]),
            "icon":      None,
        }
        for i in range(min(7, len(dates)))
    ]

    today = {"high_f": daily[0]["high_f"], "low_f": daily[0]["low_f"]} if daily else {}

    city, state = _city_state(lat, lon)

    return {
        "location": {"city": city, "state": state},
        "current":  current,
        "today":    today,
        "hourly":   hourly,
        "daily":    daily,
    }
