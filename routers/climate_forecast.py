"""
Predictive climate modeling for a single field.

Pulls a 7-day hourly forecast from Open-Meteo (free, no key) and detects
crop-stress events expected in the next 72 hours so the farm can act
*before* the heatwave / frost / wind / saturating rain hits — open the
tunnel side-walls, schedule a pre-cool irrigation, fire up frost
sprinklers, etc.

Design rules:
  • Return real numbers from a real forecast — never invent data.
  • Each detected event has: onset/end (hours from now), peak value,
    severity, a stress reason, and one or more concrete recommended
    actions tailored to the field's crop type and tunnel/irrigation
    profile when known.
  • Returns gracefully when the field has no GPS or the upstream is down.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
from database import get_db


router = APIRouter(prefix="/api", tags=["climate-forecast"])


# ───────────────────────────────────────────────────────────────────────────
# Stress thresholds — published agronomy values, deliberately conservative.
# We surface ranges, not single magic numbers, so the UI can show severity.
# ───────────────────────────────────────────────────────────────────────────
HEAT_F_WARN     = 90.0   # sustained 3+ h
HEAT_F_SEVERE   = 95.0   # any single hour
HEAT_F_CRITICAL = 100.0
COLD_F_WARN     = 38.0   # damaging to flowering berries / strawberries
FROST_F         = 32.0
HARD_FROST_F    = 28.0
VPD_KPA_WARN    = 1.5    # drought stress in most leafy crops
VPD_KPA_SEVERE  = 2.5
WIND_MPH_WARN   = 20.0   # tunnel-secure threshold
WIND_MPH_SEVERE = 35.0
RAIN_IN_24H_WARN   = 1.0
RAIN_IN_24H_SEVERE = 2.0


# Simple, conservative crop sensitivities. Anything not listed falls back to
# a generic "annual crop" profile.
CROP_SENSITIVITY = {
    "blueberry":  {"heat_sensitive": True,  "frost_sensitive": True,  "rain_split_risk": True,  "tunnel_typical": True},
    "strawberry": {"heat_sensitive": True,  "frost_sensitive": True,  "rain_split_risk": True,  "tunnel_typical": True},
    "raspberry":  {"heat_sensitive": True,  "frost_sensitive": True,  "rain_split_risk": True,  "tunnel_typical": True},
    "blackberry": {"heat_sensitive": True,  "frost_sensitive": False, "rain_split_risk": True,  "tunnel_typical": True},
    "cherry":     {"heat_sensitive": False, "frost_sensitive": True,  "rain_split_risk": True,  "tunnel_typical": False},
    "grape":      {"heat_sensitive": False, "frost_sensitive": True,  "rain_split_risk": False, "tunnel_typical": False},
    "tomato":     {"heat_sensitive": True,  "frost_sensitive": True,  "rain_split_risk": True,  "tunnel_typical": True},
    "lettuce":    {"heat_sensitive": True,  "frost_sensitive": False, "rain_split_risk": False, "tunnel_typical": True},
    "spinach":    {"heat_sensitive": True,  "frost_sensitive": False, "rain_split_risk": False, "tunnel_typical": True},
    "corn":       {"heat_sensitive": False, "frost_sensitive": True,  "rain_split_risk": False, "tunnel_typical": False},
    "soybean":    {"heat_sensitive": False, "frost_sensitive": True,  "rain_split_risk": False, "tunnel_typical": False},
    "wheat":      {"heat_sensitive": False, "frost_sensitive": True,  "rain_split_risk": False, "tunnel_typical": False},
}
DEFAULT_PROFILE = {"heat_sensitive": True, "frost_sensitive": True, "rain_split_risk": False, "tunnel_typical": False}


def _profile_for(crop_type: Optional[str]) -> dict:
    if not crop_type:
        return DEFAULT_PROFILE
    needle = crop_type.lower().strip()
    for key, p in CROP_SENSITIVITY.items():
        if key in needle:
            return p
    return DEFAULT_PROFILE


# ───────────────────────────────────────────────────────────────────────────
# Open-Meteo fetch
# ───────────────────────────────────────────────────────────────────────────
def _fetch_hourly_forecast(lat: float, lon: float) -> Optional[dict]:
    """Returns parsed Open-Meteo response or None on failure."""
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude":  lat,
                "longitude": lon,
                "hourly": ",".join([
                    "temperature_2m",
                    "relative_humidity_2m",
                    "precipitation",
                    "wind_speed_10m",
                    "vapour_pressure_deficit",
                    "shortwave_radiation",
                ]),
                "temperature_unit":   "fahrenheit",
                "wind_speed_unit":    "mph",
                "precipitation_unit": "inch",
                "timezone":           "UTC",
                "forecast_days":      7,
            },
            timeout=10,
        )
        if not r.ok:
            return None
        return r.json()
    except Exception as e:
        print(f"[climate_forecast] Open-Meteo fetch failed: {e}")
        return None


def _slice_next_hours(payload: dict, hours: int) -> List[dict]:
    """Slice the next `hours` from the hourly arrays starting at the next full hour."""
    h = payload.get("hourly") or {}
    times = h.get("time") or []
    if not times:
        return []
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    parsed: List[Tuple[datetime, int]] = []
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            parsed.append((dt, i))
        except ValueError:
            continue
    upcoming = [(dt, i) for dt, i in parsed if dt >= now][:hours]
    out = []
    for dt, i in upcoming:
        out.append({
            "time":    dt.isoformat(),
            "hours_out": int((dt - now).total_seconds() / 3600),
            "temp_f":  _at(h, "temperature_2m", i),
            "rh_pct":  _at(h, "relative_humidity_2m", i),
            "precip_in": _at(h, "precipitation", i),
            "wind_mph":  _at(h, "wind_speed_10m", i),
            "vpd_kpa":   _at(h, "vapour_pressure_deficit", i),
            "srad_wm2":  _at(h, "shortwave_radiation", i),
        })
    return out


def _at(hourly: dict, key: str, i: int):
    arr = hourly.get(key) or []
    if 0 <= i < len(arr):
        v = arr[i]
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    return None


# ───────────────────────────────────────────────────────────────────────────
# Event detection — pure functions over the hourly slice
# ───────────────────────────────────────────────────────────────────────────
def _consecutive_runs(rows: List[dict], predicate, min_hours: int = 3) -> List[Tuple[int, int]]:
    """Return list of (start_index, end_index_inclusive) for runs where predicate(row) is True."""
    runs = []
    start = None
    for i, r in enumerate(rows):
        if predicate(r):
            if start is None:
                start = i
        else:
            if start is not None and (i - start) >= min_hours:
                runs.append((start, i - 1))
            start = None
    if start is not None and (len(rows) - start) >= min_hours:
        runs.append((start, len(rows) - 1))
    return runs


def _peak(rows: List[dict], idx_start: int, idx_end: int, key: str, mode: str = "max") -> Optional[float]:
    vals = [r.get(key) for r in rows[idx_start:idx_end + 1] if r.get(key) is not None]
    if not vals:
        return None
    return max(vals) if mode == "max" else min(vals)


def _build_event(rows: List[dict], start_i: int, end_i: int,
                 kind: str, severity: str, peak_value: float, units: str,
                 reason: str, recommended_actions: List[str]) -> dict:
    return {
        "kind":             kind,
        "severity":         severity,
        "onset":            rows[start_i]["time"],
        "onset_hours_out":  rows[start_i]["hours_out"],
        "end":              rows[end_i]["time"],
        "end_hours_out":    rows[end_i]["hours_out"],
        "duration_hours":   end_i - start_i + 1,
        "peak_value":       peak_value,
        "units":            units,
        "reason":           reason,
        "recommended_actions": recommended_actions,
    }


def _detect_events(rows: List[dict], crop_type: Optional[str], profile: dict) -> List[dict]:
    crop_label = (crop_type or "the crop").strip()
    events: List[dict] = []

    # ── HEAT ─────────────────────────────────────────────────────────────
    heat_runs = _consecutive_runs(rows, lambda r: (r.get("temp_f") or 0) >= HEAT_F_WARN, min_hours=3)
    for s, e in heat_runs:
        peak = _peak(rows, s, e, "temp_f", "max") or HEAT_F_WARN
        if peak >= HEAT_F_CRITICAL:
            severity = "critical"
        elif peak >= HEAT_F_SEVERE:
            severity = "severe"
        else:
            severity = "warn"
        actions = [
            f"Open tunnel side-walls and roll up shade cloth ahead of {rows[s]['hours_out']}h-out window (peak {peak:.0f}°F).",
            "Schedule a deep pre-cool irrigation 12h before onset to lower canopy temperature and refresh soil-water reserves.",
        ]
        if profile["tunnel_typical"]:
            actions.append("If exhaust fans/swamp coolers exist, pre-stage them — surge load is highest in the first hour over threshold.")
        if profile["heat_sensitive"] and crop_label.lower() in ("blueberry", "strawberry", "raspberry", "lettuce", "spinach"):
            actions.append(f"{crop_label.capitalize()} is heat-sensitive — consider an early-morning emergency pick if peak hits during the harvest window.")
        events.append(_build_event(
            rows, s, e, "heatwave", severity, peak, "°F",
            f"Sustained heat ≥{HEAT_F_WARN:.0f}°F for {e - s + 1}h drives canopy stress and pollen abortion in many fruit/veg crops.",
            actions,
        ))

    # ── FROST ────────────────────────────────────────────────────────────
    frost_runs = _consecutive_runs(rows, lambda r: (r.get("temp_f") if r.get("temp_f") is not None else 99) <= FROST_F, min_hours=1)
    for s, e in frost_runs:
        peak = _peak(rows, s, e, "temp_f", "min") or FROST_F
        severity = "critical" if peak <= HARD_FROST_F else "severe"
        actions = [
            f"Activate frost-protection irrigation by {max(0, rows[s]['hours_out'] - 2)}h-out so the ice-release latent heat keeps tissue at 32°F.",
            "If overhead irrigation isn't an option, deploy row-covers/floating fabric before sundown the night before.",
        ]
        if profile["tunnel_typical"]:
            actions.append("Close all tunnel vents and side-walls before sunset; consider portable propane heaters for a hard freeze.")
        events.append(_build_event(
            rows, s, e, "frost", severity, peak, "°F",
            f"Air temp expected to drop to {peak:.0f}°F — frost-sensitive crops at risk of flower/young-fruit damage.",
            actions,
        ))

    # ── COLD SNAP (above frost but stress-inducing for warm crops) ──────
    cold_runs = _consecutive_runs(
        rows,
        lambda r: r.get("temp_f") is not None and FROST_F < r["temp_f"] <= COLD_F_WARN,
        min_hours=4,
    )
    for s, e in cold_runs:
        if any(ev["kind"] == "frost" and ev["onset_hours_out"] <= rows[e]["hours_out"] for ev in events):
            continue  # skip if a frost in same window already covers it
        low = _peak(rows, s, e, "temp_f", "min") or COLD_F_WARN
        events.append(_build_event(
            rows, s, e, "cold_snap", "warn", low, "°F",
            f"Cold spell to {low:.0f}°F stalls warm-season growth and can damage flowering berries.",
            ["Delay any planned tunnel ventilation; close end-walls overnight to retain heat.",
             "Hold off on foliar sprays — uptake is slow at this temperature."],
        ))

    # ── HIGH-VPD / DROUGHT STRESS (daytime only — VPD is meaningless at night) ──
    daytime = [(i, r) for i, r in enumerate(rows) if (r.get("srad_wm2") or 0) > 50]
    if daytime:
        idx_map = {i: di for di, (i, _) in enumerate(daytime)}
        day_rows = [r for _, r in daytime]
        vpd_runs = _consecutive_runs(day_rows, lambda r: (r.get("vpd_kpa") or 0) >= VPD_KPA_WARN, min_hours=4)
        for s, e in vpd_runs:
            peak = _peak(day_rows, s, e, "vpd_kpa", "max") or VPD_KPA_WARN
            severity = "severe" if peak >= VPD_KPA_SEVERE else "warn"
            real_s = next(i for i, di in idx_map.items() if di == s)
            real_e = next(i for i, di in idx_map.items() if di == e)
            events.append(_build_event(
                rows, real_s, real_e, "high_vpd", severity, round(peak, 2), "kPa",
                f"Vapor-pressure deficit peaks at {peak:.2f} kPa — plants close stomata, photosynthesis stalls, fruit sizing slows.",
                ["Pre-irrigate the day before to refill the soil profile so plants can keep transpiring through the spike.",
                 "Mulch exposed soil beds; if possible, drop overhead micro-misters during peak VPD hours.",
                 "Skip mid-day foliar applications — leaf surfaces evaporate too fast for absorption."],
            ))

    # ── RAIN — 24-hour rolling total ─────────────────────────────────────
    if rows:
        max24 = 0.0
        max24_idx = 0
        for i in range(len(rows)):
            window = [(rows[j].get("precip_in") or 0) for j in range(i, min(i + 24, len(rows)))]
            tot = sum(window)
            if tot > max24:
                max24 = tot
                max24_idx = i
        if max24 >= RAIN_IN_24H_WARN:
            severity = "severe" if max24 >= RAIN_IN_24H_SEVERE else "warn"
            end_i = min(max24_idx + 23, len(rows) - 1)
            actions = [
                "Pause irrigation 24h before onset — soil saturation amplifies disease pressure.",
                "Check tile drains and field perimeter for clogs.",
            ]
            if profile["rain_split_risk"]:
                actions.append(f"{crop_label.capitalize()} is fruit-split prone in heavy rain — if within ~7 days of harvest, consider an emergency pick before onset.")
            if profile["tunnel_typical"]:
                actions.append("Close tunnel vents and secure plastic; check anchoring against wind gusts that often accompany the front.")
            events.append(_build_event(
                rows, max24_idx, end_i, "heavy_rain", severity, round(max24, 2), "in (24h)",
                f"Rolling 24-hour rainfall peaks at {max24:.2f} in — soil saturation and fruit-split risk.",
                actions,
            ))

    # ── WIND ─────────────────────────────────────────────────────────────
    wind_runs = _consecutive_runs(rows, lambda r: (r.get("wind_mph") or 0) >= WIND_MPH_WARN, min_hours=2)
    for s, e in wind_runs:
        peak = _peak(rows, s, e, "wind_mph", "max") or WIND_MPH_WARN
        severity = "severe" if peak >= WIND_MPH_SEVERE else "warn"
        actions = [
            "Secure tunnel ventilation panels and shade cloth; check trellis/stake ties.",
            "Hold off on spray applications — drift losses and uneven coverage.",
        ]
        if profile["tunnel_typical"]:
            actions.append("Close end-walls and zipper doors; high-tunnel plastic is most likely to tear at peak gust hour.")
        events.append(_build_event(
            rows, s, e, "high_wind", severity, round(peak, 1), "mph",
            f"Wind sustained ≥{WIND_MPH_WARN:.0f} mph (peak {peak:.0f} mph) — structural stress and spray-drift risk.",
            actions,
        ))

    # Prioritize: critical/severe first, then by onset
    severity_rank = {"critical": 0, "severe": 1, "warn": 2}
    events.sort(key=lambda e: (severity_rank.get(e["severity"], 3), e["onset_hours_out"]))
    return events


def _summary_blocks(rows_72: List[dict]) -> dict:
    """Quick summary stats for the next 72 hours so the UI can render headline numbers."""
    if not rows_72:
        return {}
    temps = [r["temp_f"]   for r in rows_72 if r.get("temp_f")   is not None]
    vpds  = [r["vpd_kpa"]  for r in rows_72 if r.get("vpd_kpa")  is not None]
    winds = [r["wind_mph"] for r in rows_72 if r.get("wind_mph") is not None]
    rain_total = sum((r.get("precip_in") or 0) for r in rows_72)
    return {
        "max_temp_f":       round(max(temps), 1) if temps else None,
        "min_temp_f":       round(min(temps), 1) if temps else None,
        "max_vpd_kpa":      round(max(vpds), 2) if vpds else None,
        "max_wind_mph":     round(max(winds), 1) if winds else None,
        "total_precip_in":  round(rain_total, 2),
    }


# ───────────────────────────────────────────────────────────────────────────
# Endpoint
# ───────────────────────────────────────────────────────────────────────────
@router.get("/fields/{field_id}/climate-forecast")
def get_field_climate_forecast(field_id: int, hours: int = 72, db: Session = Depends(get_db)):
    """
    Return predictive climate-stress events for the next `hours` hours
    (clamped to 24–168) at this field's GPS, plus the underlying hourly series
    so the UI can chart it.
    """
    field = db.query(models.Field).filter(models.Field.FieldID == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    if field.Latitude is None or field.Longitude is None:
        raise HTTPException(status_code=400, detail="Field has no GPS coordinates — set lat/lon to enable forecasting")

    hours = max(24, min(int(hours or 72), 168))
    payload = _fetch_hourly_forecast(float(field.Latitude), float(field.Longitude))
    if not payload:
        raise HTTPException(status_code=502, detail="Weather forecast service unavailable — try again in a few minutes")

    rows = _slice_next_hours(payload, hours)
    profile = _profile_for(field.CropType)
    events = _detect_events(rows, field.CropType, profile)

    return {
        "field_id":         field_id,
        "field_name":       field.Name,
        "crop_type":        field.CropType,
        "lat":              float(field.Latitude),
        "lon":              float(field.Longitude),
        "horizon_hours":    hours,
        "generated_at":     datetime.utcnow().isoformat() + "Z",
        "summary":          _summary_blocks(rows[:72]),
        "events":           events,
        "hourly":           rows,
        "crop_profile":     profile,
        "thresholds": {
            "heat_warn_f":      HEAT_F_WARN,
            "heat_severe_f":    HEAT_F_SEVERE,
            "heat_critical_f":  HEAT_F_CRITICAL,
            "frost_f":          FROST_F,
            "hard_frost_f":     HARD_FROST_F,
            "vpd_warn_kpa":     VPD_KPA_WARN,
            "vpd_severe_kpa":   VPD_KPA_SEVERE,
            "wind_warn_mph":    WIND_MPH_WARN,
            "wind_severe_mph":  WIND_MPH_SEVERE,
            "rain_warn_24h_in":   RAIN_IN_24H_WARN,
            "rain_severe_24h_in": RAIN_IN_24H_SEVERE,
        },
        "source": "Open-Meteo (free, hourly, 7-day horizon)",
    }
