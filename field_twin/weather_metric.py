"""Open-Meteo weather for India Field Twin — °C, mm, km/h."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests


def fetch_weather(lat: float, lon: float, days: int = 14) -> dict[str, Any]:
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": (
                    "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                    "et0_fao_evapotranspiration,windspeed_10m_max,winddirection_10m_dominant"
                ),
                "current": "temperature_2m,precipitation,windspeed_10m,winddirection_10m,weathercode",
                "temperature_unit": "celsius",
                "precipitation_unit": "mm",
                "windspeed_unit": "kmh",
                "timezone": "auto",
                "past_days": min(days, 30),
                "forecast_days": 7,
            },
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        daily = data.get("daily") or {}
        dates = daily.get("time") or []
        tmax = daily.get("temperature_2m_max") or []
        tmin = daily.get("temperature_2m_min") or []
        precip = daily.get("precipitation_sum") or []
        et0 = daily.get("et0_fao_evapotranspiration") or []
        wind = daily.get("windspeed_10m_max") or []
        wdir = daily.get("winddirection_10m_dominant") or []
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                "date": d,
                "temp_max": tmax[i] if i < len(tmax) else None,
                "temp_min": tmin[i] if i < len(tmin) else None,
                "precip": precip[i] if i < len(precip) else None,
                "et0": et0[i] if i < len(et0) else None,
                "wind_max_kmh": wind[i] if i < len(wind) else None,
                "wind_dir_deg": wdir[i] if i < len(wdir) else None,
            })
        current = data.get("current") or {}
        fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "available": True,
            "provenance": "derived",
            "confidence": "high",
            "source": "open-meteo",
            "units": {"temp": "C", "precip": "mm", "wind": "km/h", "et0": "mm"},
            "coverage": "gridded_model_near_coordinates",
            "fetched_at": fetched_at,
            "lat": lat,
            "lon": lon,
            "current": {
                "temp_c": current.get("temperature_2m"),
                "precip_mm": current.get("precipitation"),
                "wind_kmh": current.get("windspeed_10m"),
                "wind_dir_deg": current.get("winddirection_10m"),
                "weather_code": current.get("weathercode"),
                "observed_at": current.get("time"),
            },
            "daily": rows,
            "note": (
                "Open-Meteo gridded forecast/reanalysis near field lat/lon — "
                "not an on-field weather station. Values are metric (°C, mm, km/h)."
            ),
            "limitations": [
                "Values represent a model grid cell near the coordinates, not a sensor on this parcel.",
                "Monsoon microclimate can differ from the grid cell.",
            ],
        }
    except requests.RequestException as e:
        return {"available": False, "error": str(e)}
