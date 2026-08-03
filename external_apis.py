"""
Free public APIs used to enrich the Maturity Engine without paid services.

Every helper:
  • Has a tight timeout so a slow upstream never hangs the page.
  • Returns None on any failure (the caller treats absence as "no data").
  • Logs but does not raise — these are best-effort context, not contracts.

Sources (all free, no fees):
  • NASA POWER       — daily PAR / shortwave radiation / dew point (no key).
  • OSRM             — road-distance routing via the public demo server.
  • Nominatim (OSM)  — geocoding + reverse geocoding (User-Agent required).
  • USDA NASS        — state-level weekly crop progress (free key required —
                       set USDA_NASS_API_KEY; gracefully no-ops if absent).
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import List, Optional, Tuple

import requests


_HTTP_TIMEOUT = 6
_USER_AGENT = "OatmealFarmNetwork/1.0 (livestockoftheworld@gmail.com)"
_HEADERS = {"User-Agent": _USER_AGENT, "Accept": "application/json"}


# ───────────────────────────────────────────────────────────────────────────
# NASA POWER — daily light/temperature/dew at the field's GPS point
# ───────────────────────────────────────────────────────────────────────────
def nasa_power_daily(lat: float, lon: float, days: int = 30) -> Optional[List[dict]]:
    """Return [{date, par_mj_m2, srad_mj_m2, dew_point_c, t_max_c, t_min_c, diurnal_c}]
    for the last `days` days at (lat, lon). None on any failure."""
    if lat is None or lon is None:
        return None
    end = date.today()
    start = end - timedelta(days=max(7, min(days, 365)))
    url = "https://power.larc.nasa.gov/api/temporal/daily/point"
    params = {
        "parameters": "ALLSKY_SFC_PAR_TOT,ALLSKY_SFC_SW_DWN,T2MDEW,T2M_MAX,T2M_MIN",
        "community":  "AG",
        "longitude":  lon,
        "latitude":   lat,
        "start":      start.strftime("%Y%m%d"),
        "end":        end.strftime("%Y%m%d"),
        "format":     "JSON",
    }
    try:
        r = requests.get(url, params=params, headers=_HEADERS, timeout=_HTTP_TIMEOUT)
        if not r.ok:
            return None
        payload = r.json()
        params_block = (payload.get("properties") or {}).get("parameter") or {}
        par   = params_block.get("ALLSKY_SFC_PAR_TOT") or {}
        srad  = params_block.get("ALLSKY_SFC_SW_DWN") or {}
        dew   = params_block.get("T2MDEW") or {}
        tmax  = params_block.get("T2M_MAX") or {}
        tmin  = params_block.get("T2M_MIN") or {}
        # NASA POWER uses YYYYMMDD keys and returns -999 for fill values.
        out = []
        for ymd in sorted(par.keys()):
            def _v(d):
                v = d.get(ymd)
                if v is None or v == -999 or v == "-999":
                    return None
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
            t_max = _v(tmax)
            t_min = _v(tmin)
            diurnal = (t_max - t_min) if (t_max is not None and t_min is not None) else None
            out.append({
                "date":         f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}",
                "par_mj_m2":    _v(par),
                "srad_mj_m2":   _v(srad),
                "dew_point_c":  _v(dew),
                "t_max_c":      t_max,
                "t_min_c":      t_min,
                "diurnal_c":    diurnal,
            })
        return out or None
    except Exception as e:
        print(f"[external_apis.nasa_power_daily] failed: {e}")
        return None


def nasa_power_summary(lat: float, lon: float, days: int = 30) -> Optional[dict]:
    """Aggregate the daily series into the metrics the maturity engine cares
    about: cumulative PAR, average diurnal range, and average dew point.
    Wide diurnal range + cool nights are known to drive anthocyanin
    accumulation in berries."""
    series = nasa_power_daily(lat, lon, days)
    if not series:
        return None
    par_vals     = [d["par_mj_m2"]    for d in series if d["par_mj_m2"]    is not None]
    diurnal_vals = [d["diurnal_c"]    for d in series if d["diurnal_c"]    is not None]
    dew_vals     = [d["dew_point_c"]  for d in series if d["dew_point_c"]  is not None]
    if not par_vals and not diurnal_vals:
        return None
    return {
        "days":                  len(series),
        "cumulative_par_mj_m2":  round(sum(par_vals), 1) if par_vals else None,
        "avg_par_mj_m2_per_day": round(sum(par_vals) / len(par_vals), 2) if par_vals else None,
        "avg_diurnal_c":         round(sum(diurnal_vals) / len(diurnal_vals), 1) if diurnal_vals else None,
        "avg_dew_point_c":       round(sum(dew_vals) / len(dew_vals), 1) if dew_vals else None,
        "source":                "NASA POWER (daily)",
    }


# ───────────────────────────────────────────────────────────────────────────
# OSRM — road distance between two points (public demo server)
# ───────────────────────────────────────────────────────────────────────────
def osrm_route_miles(
    from_lat: float, from_lon: float,
    to_lat: float, to_lon: float,
) -> Optional[float]:
    """One-way road miles via the OSRM public demo server. None on any failure."""
    if None in (from_lat, from_lon, to_lat, to_lon):
        return None
    base = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
    url = f"{base}/route/v1/driving/{from_lon},{from_lat};{to_lon},{to_lat}"
    try:
        r = requests.get(url, params={"overview": "false"}, headers=_HEADERS, timeout=_HTTP_TIMEOUT)
        if not r.ok:
            return None
        data = r.json()
        routes = data.get("routes") or []
        if not routes:
            return None
        meters = routes[0].get("distance")
        if meters is None:
            return None
        return round(float(meters) / 1609.344, 1)  # meters → miles
    except Exception as e:
        print(f"[external_apis.osrm_route_miles] failed: {e}")
        return None


# ───────────────────────────────────────────────────────────────────────────
# Nominatim — geocode + reverse geocode (OpenStreetMap)
# ───────────────────────────────────────────────────────────────────────────
def nominatim_geocode(query: str) -> Optional[Tuple[float, float, str]]:
    """Return (lat, lon, display_name) for a free-form address, or None.
    Honor Nominatim's TOS: low volume + custom User-Agent (set above)."""
    if not query or not query.strip():
        return None
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query.strip(), "format": "json", "limit": 1, "addressdetails": 0},
            headers=_HEADERS,
            timeout=_HTTP_TIMEOUT,
        )
        if not r.ok:
            return None
        rows = r.json() or []
        if not rows:
            return None
        row = rows[0]
        return (float(row["lat"]), float(row["lon"]), row.get("display_name") or query)
    except Exception as e:
        print(f"[external_apis.nominatim_geocode] failed: {e}")
        return None


def nominatim_reverse_state(lat: float, lon: float) -> Optional[str]:
    """Return the US state name (e.g. 'Texas') for a coordinate, or None.
    Used to scope USDA NASS queries to the right state."""
    if lat is None or lon is None:
        return None
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json", "zoom": 5, "addressdetails": 1},
            headers=_HEADERS,
            timeout=_HTTP_TIMEOUT,
        )
        if not r.ok:
            return None
        row = r.json() or {}
        addr = row.get("address") or {}
        if addr.get("country_code", "").lower() != "us":
            return None
        return addr.get("state")
    except Exception as e:
        print(f"[external_apis.nominatim_reverse_state] failed: {e}")
        return None


# ───────────────────────────────────────────────────────────────────────────
# USDA NASS QuickStats — weekly state-level crop progress
# Free API key required — set USDA_NASS_API_KEY in env. Returns None when
# the key is unset OR when the upstream has nothing for this state/crop.
# ───────────────────────────────────────────────────────────────────────────
_NASS_COMMODITY_ALIASES = {
    "blueberry":   "BLUEBERRIES",
    "blueberries": "BLUEBERRIES",
    "strawberry":  "STRAWBERRIES",
    "strawberries":"STRAWBERRIES",
    "raspberry":   "RASPBERRIES",
    "raspberries": "RASPBERRIES",
    "blackberry":  "BLACKBERRIES",
    "blackberries":"BLACKBERRIES",
    "grape":       "GRAPES",
    "grapes":      "GRAPES",
    "cherry":      "CHERRIES",
    "cherries":    "CHERRIES",
    "apple":       "APPLES",
    "apples":      "APPLES",
    "corn":        "CORN",
    "soybean":     "SOYBEANS",
    "soybeans":    "SOYBEANS",
    "wheat":       "WHEAT",
    "cotton":      "COTTON",
    "rice":        "RICE",
    "peanut":      "PEANUTS",
    "peanuts":     "PEANUTS",
    "tomato":      "TOMATOES",
    "tomatoes":    "TOMATOES",
}


def _nass_commodity_for(crop_type: Optional[str]) -> Optional[str]:
    if not crop_type:
        return None
    t = crop_type.lower().strip()
    for key, val in _NASS_COMMODITY_ALIASES.items():
        if key in t:
            return val
    return None


def usda_nass_crop_progress(state: Optional[str], crop_type: Optional[str]) -> Optional[dict]:
    """Latest weekly progress for the crop in the field's state.
    Returns the most recent observation: {value_pct, statistic_label,
    week_ending, year, source}. None when API key, state, or commodity
    isn't usable."""
    api_key = os.getenv("USDA_NASS_API_KEY")
    if not api_key:
        return None
    commodity = _nass_commodity_for(crop_type)
    if not commodity or not state:
        return None
    try:
        r = requests.get(
            "https://quickstats.nass.usda.gov/api/api_GET/",
            params={
                "key":                api_key,
                "source_desc":        "SURVEY",
                "sector_desc":        "CROPS",
                "statisticcat_desc":  "PROGRESS",
                "commodity_desc":     commodity,
                "agg_level_desc":     "STATE",
                "state_name":         state.upper(),
                "year":               date.today().year,
                "format":             "JSON",
            },
            headers=_HEADERS,
            timeout=_HTTP_TIMEOUT,
        )
        if not r.ok:
            return None
        rows = (r.json() or {}).get("data") or []
        if not rows:
            return None
        # Pick the most recent week_ending row.
        rows_sorted = sorted(rows, key=lambda x: x.get("week_ending") or "", reverse=True)
        top = rows_sorted[0]
        try:
            value = float(str(top.get("Value") or "").replace(",", ""))
        except ValueError:
            value = None
        return {
            "value_pct":       value,
            "statistic_label": top.get("short_desc"),
            "week_ending":     top.get("week_ending"),
            "year":            top.get("year"),
            "state":           top.get("state_name"),
            "commodity":       top.get("commodity_desc"),
            "source":          "USDA NASS QuickStats",
        }
    except Exception as e:
        print(f"[external_apis.usda_nass_crop_progress] failed: {e}")
        return None
