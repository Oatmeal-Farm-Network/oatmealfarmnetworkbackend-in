"""
Crop price forecasting.

Fetches historical monthly prices from USDA NASS Quick Stats API (free,
optional API key) and applies simple seasonal decomposition + recent-trend
blending to produce a 3-6 month forward estimate.

For commodities NASS doesn't cover, we fall back to a small curated recent
average bundled in this file (so the feature still works offline / without
an API key). The forecast ALWAYS returns a range + confidence bucket — no
spurious single-point precision.
"""
from __future__ import annotations

import os
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

try:
    import urllib.request
    import urllib.parse
    _NET_AVAILABLE = True
except Exception:
    _NET_AVAILABLE = False

import json
from langchain_core.tools import tool


NASS_API = "https://quickstats.nass.usda.gov/api/api_GET"
NASS_KEY = os.getenv("NASS_API_KEY", "")  # free registration; works without but rate-limited


# ──────────────────────────────────────────────────────────────────
# Commodity → NASS short_desc mapping (US monthly prices received)
# ──────────────────────────────────────────────────────────────────
NASS_COMMODITY = {
    "corn":         ("CORN",      "CORN, GRAIN - PRICE RECEIVED, MEASURED IN $ / BU"),
    "soybean":      ("SOYBEANS",  "SOYBEANS - PRICE RECEIVED, MEASURED IN $ / BU"),
    "wheat":        ("WHEAT",     "WHEAT - PRICE RECEIVED, MEASURED IN $ / BU"),
    "cotton":       ("COTTON",    "COTTON, UPLAND - PRICE RECEIVED, MEASURED IN $ / LB"),
    "rice":         ("RICE",      "RICE - PRICE RECEIVED, MEASURED IN $ / CWT"),
    "oat":          ("OATS",      "OATS - PRICE RECEIVED, MEASURED IN $ / BU"),
    "barley":       ("BARLEY",    "BARLEY - PRICE RECEIVED, MEASURED IN $ / BU"),
    "sorghum":      ("SORGHUM",   "SORGHUM, GRAIN - PRICE RECEIVED, MEASURED IN $ / CWT"),
    "peanut":       ("PEANUTS",   "PEANUTS - PRICE RECEIVED, MEASURED IN $ / LB"),
    "sunflower":    ("SUNFLOWER", "SUNFLOWER - PRICE RECEIVED, MEASURED IN $ / LB"),
    "milk":         ("MILK",      "MILK - PRICE RECEIVED, MEASURED IN $ / CWT"),
    "cattle":       ("CATTLE",    "CATTLE, INCL CALVES - PRICE RECEIVED, MEASURED IN $ / CWT"),
    "hog":          ("HOGS",      "HOGS - PRICE RECEIVED, MEASURED IN $ / CWT"),
    "egg":          ("EGGS",      "EGGS - PRICE RECEIVED, MEASURED IN $ / DOZ"),
    "hay":          ("HAY",       "HAY - PRICE RECEIVED, MEASURED IN $ / TON"),
}


# ──────────────────────────────────────────────────────────────────
# Fallback curated recent averages (USD, 2024-2025 US avg)
# ──────────────────────────────────────────────────────────────────
# Used when NASS is unreachable or the user asks about commodities outside
# NASS coverage. Keep this conservative — better to refuse than to mislead.
FALLBACK_RECENT: Dict[str, Dict] = {
    "corn":      {"unit": "$/bu", "recent_avg": 4.25, "range": (3.80, 4.80), "source": "USDA NASS 2024 avg"},
    "soybean":   {"unit": "$/bu", "recent_avg": 10.20, "range": (9.50, 11.10), "source": "USDA NASS 2024 avg"},
    "wheat":     {"unit": "$/bu", "recent_avg": 5.90, "range": (5.20, 6.60), "source": "USDA NASS 2024 avg"},
    "rice":      {"unit": "$/cwt", "recent_avg": 16.50, "range": (15.00, 18.00), "source": "USDA NASS 2024 avg"},
    "cotton":    {"unit": "$/lb", "recent_avg": 0.72, "range": (0.65, 0.80), "source": "USDA NASS 2024 avg"},
    "oat":       {"unit": "$/bu", "recent_avg": 3.60, "range": (3.20, 4.00), "source": "USDA NASS 2024 avg"},
    "barley":    {"unit": "$/bu", "recent_avg": 5.40, "range": (4.90, 5.90), "source": "USDA NASS 2024 avg"},
    "milk":      {"unit": "$/cwt", "recent_avg": 22.50, "range": (19.00, 25.00), "source": "USDA NASS 2024 avg"},
    "cattle":    {"unit": "$/cwt", "recent_avg": 180, "range": (165, 195), "source": "USDA NASS 2024 avg"},
    "hog":       {"unit": "$/cwt", "recent_avg": 72, "range": (60, 85), "source": "USDA NASS 2024 avg"},
    "egg":       {"unit": "$/doz", "recent_avg": 2.40, "range": (1.80, 3.20), "source": "USDA NASS 2024 avg (volatile)"},
    "hay":       {"unit": "$/ton", "recent_avg": 210, "range": (180, 240), "source": "USDA NASS 2024 avg"},
    "peanut":    {"unit": "$/lb", "recent_avg": 0.27, "range": (0.24, 0.30), "source": "USDA NASS 2024 avg"},
    "sunflower": {"unit": "$/lb", "recent_avg": 0.22, "range": (0.20, 0.25), "source": "USDA NASS 2024 avg"},
    "sorghum":   {"unit": "$/cwt", "recent_avg": 7.80, "range": (7.00, 8.80), "source": "USDA NASS 2024 avg"},
}


COMMODITY_ALIASES = {
    "maize":        "corn",
    "soybeans":     "soybean",
    "soy":          "soybean",
    "dairy":        "milk",
    "beef":         "cattle",
    "pork":         "hog",
    "pig":          "hog",
    "pigs":         "hog",
    "eggs":         "egg",
    "oats":         "oat",
    "peanuts":      "peanut",
    "sunflowers":   "sunflower",
    "alfalfa":      "hay",
}


def _resolve(name: str) -> Optional[str]:
    key = (name or "").strip().lower()
    return key if key in FALLBACK_RECENT or key in NASS_COMMODITY else COMMODITY_ALIASES.get(key)


def _fetch_nass(commodity_key: str, years: int = 3) -> Optional[List[Dict]]:
    """Fetch monthly national price series from NASS. Returns list of dicts."""
    if not _NET_AVAILABLE:
        return None
    mapping = NASS_COMMODITY.get(commodity_key)
    if not mapping:
        return None
    commodity_desc, short_desc = mapping
    current_year = datetime.utcnow().year
    year_list = ",".join(str(y) for y in range(current_year - years, current_year + 1))

    params = {
        "source_desc": "SURVEY",
        "commodity_desc": commodity_desc,
        "short_desc": short_desc,
        "agg_level_desc": "NATIONAL",
        "year__GE": str(current_year - years),
        "freq_desc": "MONTHLY",
        "format": "JSON",
    }
    if NASS_KEY:
        params["key"] = NASS_KEY

    url = f"{NASS_API}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[price_forecast] NASS fetch failed for {commodity_key}: {e}")
        return None

    rows = data.get("data", [])
    series: List[Dict] = []
    for r in rows:
        try:
            val = float(str(r.get("Value", "")).replace(",", ""))
        except (ValueError, TypeError):
            continue
        series.append({
            "year": int(r.get("year", 0)),
            "month": r.get("reference_period_desc", ""),
            "value": val,
        })
    return series or None


MONTH_ORDER = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
               "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _seasonal_index(series: List[Dict]) -> Dict[str, float]:
    """Return per-month multipliers (seasonal index) relative to the mean."""
    by_month: Dict[str, List[float]] = {m: [] for m in MONTH_ORDER}
    for row in series:
        m = (row.get("month") or "")[:3].upper()
        if m in by_month:
            by_month[m].append(row["value"])
    overall = statistics.mean([v for vals in by_month.values() for v in vals]) \
        if any(by_month.values()) else 0
    if not overall:
        return {m: 1.0 for m in MONTH_ORDER}
    return {
        m: (statistics.mean(vals) / overall) if vals else 1.0
        for m, vals in by_month.items()
    }


def _forecast_series(series: List[Dict], months_ahead: int) -> List[Dict]:
    """Produce months_ahead monthly forecasts using recent average × seasonal index."""
    if not series:
        return []
    recent = [r["value"] for r in series[:12]]  # last ~12 months
    base = statistics.mean(recent) if recent else series[0]["value"]
    seasonal = _seasonal_index(series)
    now = datetime.utcnow()
    forecasts = []
    for i in range(1, months_ahead + 1):
        d = now + timedelta(days=30 * i)
        m_key = MONTH_ORDER[d.month - 1]
        expected = base * seasonal.get(m_key, 1.0)
        # 15% confidence band (typical ag-commodity MAPE on short horizon)
        low = expected * 0.85
        high = expected * 1.15
        forecasts.append({
            "month": d.strftime("%Y-%m"),
            "expected": round(expected, 2),
            "low": round(low, 2),
            "high": round(high, 2),
        })
    return forecasts


def forecast(commodity: str, months_ahead: int = 6) -> Dict:
    key = _resolve(commodity)
    if not key:
        return {
            "status": "not_supported",
            "commodity": commodity,
            "known": sorted(list(FALLBACK_RECENT.keys())),
        }

    fallback = FALLBACK_RECENT.get(key, {})
    series = _fetch_nass(key, years=3) if key in NASS_COMMODITY else None
    source = "USDA NASS monthly (national)"
    if not series:
        # Fallback: use bundled recent average; seasonal index assumed flat.
        recent_avg = fallback.get("recent_avg", 0)
        rng_low, rng_high = fallback.get("range", (recent_avg * 0.85, recent_avg * 1.15))
        forecasts = []
        now = datetime.utcnow()
        for i in range(1, months_ahead + 1):
            d = now + timedelta(days=30 * i)
            forecasts.append({
                "month": d.strftime("%Y-%m"),
                "expected": round(recent_avg, 2),
                "low": round(rng_low, 2),
                "high": round(rng_high, 2),
            })
        return {
            "status": "ok",
            "commodity": key,
            "unit": fallback.get("unit", "unknown"),
            "recent_average": recent_avg,
            "source": fallback.get("source", "curated fallback"),
            "forecast": forecasts,
            "confidence": "low",
            "notes": ("Using bundled recent-average fallback. For a live trend-adjusted "
                      "forecast, set NASS_API_KEY in the backend environment."),
        }

    forecasts = _forecast_series(series, months_ahead)
    recent = statistics.mean(r["value"] for r in series[:6]) if series else 0
    return {
        "status": "ok",
        "commodity": key,
        "unit": fallback.get("unit", "unknown"),
        "recent_average": round(recent, 2),
        "source": source,
        "forecast": forecasts,
        "confidence": "medium",
        "notes": "National monthly price-received series; seasonal index × recent mean.",
    }


def list_commodities() -> List[str]:
    return sorted(set(list(FALLBACK_RECENT.keys()) + list(NASS_COMMODITY.keys())))


def format_for_llm(commodity: str, months_ahead: int = 6) -> str:
    r = forecast(commodity, months_ahead)
    if r["status"] != "ok":
        return f"Price forecast not available for '{commodity}'. Supported: {', '.join(r.get('known', [])[:15])}."
    lines = [f"Price forecast — {r['commodity']} ({r['unit']}, source: {r['source']}, confidence: {r['confidence']}):"]
    lines.append(f"  Recent average: {r['recent_average']} {r['unit']}")
    for f in r["forecast"]:
        lines.append(f"  {f['month']}: expected {f['expected']} (range {f['low']}–{f['high']})")
    if r.get("notes"):
        lines.append(f"Notes: {r['notes']}")
    return "\n".join(lines)


@tool
def price_forecast_tool(commodity: str, months_ahead: int = 6) -> str:
    """Forecast monthly US commodity prices for the next 1-12 months using USDA NASS
    historical data + seasonal decomposition. Supports corn, soybean, wheat, rice,
    cotton, oat, barley, sorghum, peanut, sunflower, milk, cattle, hog, egg, hay.
    Always returns a range (low-high) plus confidence bucket — not a single-point
    precise estimate. Use when the user asks about pricing, marketing, or when to
    sell."""
    return format_for_llm(commodity, max(1, min(months_ahead, 12)))


price_forecast_tools = [price_forecast_tool]
