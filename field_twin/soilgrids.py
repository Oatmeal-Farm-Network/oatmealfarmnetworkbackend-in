"""ISRIC SoilGrids at field centroid. Cached by callers in FieldExternalDataCache."""
from __future__ import annotations

from typing import Any, Optional

import requests

SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
_PROPERTIES = ("phh2o", "clay", "sand", "soc", "bdod")
_DEPTHS = ("0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm")


def _mean(values: Any) -> Optional[float]:
    if values is None:
        return None
    if isinstance(values, dict):
        for k in ("mean", "Q0.5", "value"):
            if k in values and values[k] is not None:
                try:
                    return float(values[k])
                except (TypeError, ValueError):
                    return None
        return None
    try:
        return float(values)
    except (TypeError, ValueError):
        return None


def _parse_depth(label: str) -> tuple[Optional[float], Optional[float]]:
    cleaned = str(label).lower().replace("cm", "").strip().replace("–", "-")
    parts = cleaned.split("-")
    if len(parts) != 2:
        return None, None
    try:
        return float(parts[0]), float(parts[1])
    except (TypeError, ValueError):
        return None, None


def fetch_soilgrids(lat: float, lon: float) -> dict[str, Any]:
    """Return the Field Twin detection-shaped payload (soil_layers, empty crop history)."""
    params = [("lon", lon), ("lat", lat)]
    for p in _PROPERTIES:
        params.append(("property", p))
    for d in _DEPTHS:
        params.append(("depth", d))
    params.append(("value", "mean"))
    try:
        r = requests.get(
            SOILGRIDS_URL,
            params=params,
            timeout=20,
            headers={"Accept": "application/json", "User-Agent": "OFN-India-FieldTwin/1.0"},
        )
        r.raise_for_status()
        body = r.json()
    except requests.RequestException as e:
        return {
            "available": False,
            "provenance": "none",
            "confidence": "none",
            "note": f"SoilGrids unavailable: {e}",
            "history": [],
            "soil_layers": [],
            "cache": {"hit": False},
        }

    layers_in = ((body.get("properties") or {}).get("layers")) or []
    by_depth: dict[str, dict] = {}
    for layer in layers_in:
        name = (layer.get("name") or "").lower()
        for depth in layer.get("depths") or []:
            label = depth.get("label") or depth.get("range") or ""
            bucket = by_depth.setdefault(label, {})
            bucket[name] = _mean(depth.get("values"))

    soil_layers = []
    for label, props in by_depth.items():
        top_cm, bottom_cm = _parse_depth(label)
        ph_raw = props.get("phh2o")
        # SoilGrids pH is typically ×10
        ph = round(ph_raw / 10.0, 2) if ph_raw is not None and ph_raw > 14 else ph_raw
        clay = props.get("clay")
        sand = props.get("sand")
        # clay/sand often g/kg → %
        if clay is not None and clay > 100:
            clay = clay / 10.0
        if sand is not None and sand > 100:
            sand = sand / 10.0
        soc = props.get("soc")
        silt = None
        if sand is not None and clay is not None:
            silt = max(0.0, 100.0 - sand - clay)
        soil_layers.append({
            "label": label,
            "top_cm": top_cm,
            "bottom_cm": bottom_cm,
            "thickness_m": (
                ((bottom_cm or 0) - (top_cm or 0)) / 100.0
                if top_cm is not None and bottom_cm is not None
                else None
            ),
            "ph": ph,
            "soc_g_per_kg": soc,
            "organic_matter_pct": round(soc * 0.172, 2) if soc is not None else None,
            "sand_pct": sand,
            "clay_pct": clay,
            "silt_pct": silt,
            "bdod": props.get("bdod"),
            "provenance": "derived",
            "source": "soilgrids",
            "confidence": "medium",
        })
    soil_layers.sort(key=lambda x: (x.get("top_cm") is None, x.get("top_cm") or 0))

    return {
        "available": bool(soil_layers),
        "provenance": "derived",
        "confidence": "medium" if soil_layers else "none",
        "source": "soilgrids",
        "coverage": "point_at_field_lat_lon",
        "history": [],
        "latest_year": None,
        "soil_layers": soil_layers,
        "note": (
            "SoilGrids layers are gridded soil estimates at the field centroid — "
            "not a dug profile for this exact parcel. Crop history is grower/rotation only."
        ),
        "limitations": [
            "No USDA CDL on the India stack. Confirm crop on the field record.",
            "SoilGrids is modeled soil properties by depth band, not lab-measured cores.",
        ],
        "cache": {"hit": False},
    }
