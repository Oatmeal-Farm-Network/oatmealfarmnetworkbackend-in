"""
Field Twin — authenticated snapshot for the immersive 3D field experience.

Returns a versioned JSON contract with real field geometry, crop state,
soil/scout observations, weather, irrigation, and authenticated terrain asset
URLs. Decorative / modeled attributes are explicitly labeled with confidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import asyncio
from datetime import datetime, date, timezone, timedelta
from typing import Any, Literal, Optional

import httpx
import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, text
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db, engine, Base
from precision_ag_auth import _verify_field_access
from . import terrain_screening as _terrain_screening
from field_twin.config import crop_monitor_url
from field_twin import soilgrids as _soilgrids
from field_twin import weather_metric as _weather_metric
from field_twin import crop_source as _crop_source

router = APIRouter(prefix="/api", tags=["field-twin"])

TWIN_CONTRACT_VERSION = "1.4.1"
CACHE_TTL_HOURS = 168  # 7 days — SoilGrids changes slowly
CACHE_DATA_VERSION = "1"
_ANALYZE_RETRY_BACKOFF_S = 0.35


def _india_season(d: Optional[date] = None) -> dict:
    d = d or date.today()
    month = int(d.month)
    if 6 <= month <= 10:
        return {"id": "kharif", "label": "Kharif", "months": "Jun–Oct", "rain_hint_mm": 80}
    if month == 11 or month == 12 or month <= 3:
        return {"id": "rabi", "label": "Rabi", "months": "Nov–Mar", "rain_hint_mm": 25}
    return {"id": "zaid", "label": "Zaid", "months": "Mar–Jun", "rain_hint_mm": 40}

# Guarded bootstrap only creates missing tables. Unique indexes and production
# schema must come from migrations/add_field_twin_crop_cache.sql — do not rely
# on create_all for constraints.
try:
    Base.metadata.create_all(
        bind=engine,
        tables=[
            models.FieldExternalDataCache.__table__,
            models.FieldCropSourceDecision.__table__,
        ],
        checkfirst=True,
    )
except Exception as e:
    print(f"[field_twin] create_all skipped (DB unavailable): {e}")
    print(
        "[field_twin] Apply migrations/add_field_twin_crop_cache.sql for "
        "unique indexes before production use."
    )

CROP_MONITOR_URL = crop_monitor_url()

# Approximate days to maturity by crop (for growth-stage modeling)
_CROP_MATURITY_DAYS = {
    "wheat": 120, "corn": 120, "maize": 120, "soy": 110, "soybean": 110,
    "canola": 110, "cotton": 150, "rice": 130, "barley": 100, "oats": 100,
    "sugarcane": 330, "chickpea": 110, "pigeon_pea": 160, "groundnut": 120,
    "mustard": 110, "millet": 90, "potato": 100, "onion": 120, "tomato": 90,
    "default": 120,
}

_CROP_KC = {
    "wheat": 1.0, "corn": 1.15, "maize": 1.15, "soy": 1.0, "soybean": 1.0,
    "canola": 1.0, "cotton": 1.15, "rice": 1.2, "barley": 1.0, "oats": 1.0,
    "alfalfa": 1.05, "hay": 1.0, "grass": 0.95, "sorghum": 1.05,
    "sugarcane": 1.25, "chickpea": 0.9, "pigeon_pea": 0.95, "groundnut": 1.0,
    "mustard": 1.0, "millet": 0.95, "potato": 1.05, "onion": 1.0, "tomato": 1.05,
    "default": 1.0,
}

# Rough root-zone MAD (mm) — screening thresholds only, not an agronomist schedule.
_CROP_MAD_MM = {
    "wheat": 30, "corn": 38, "maize": 38, "soy": 32, "soybean": 32,
    "canola": 30, "cotton": 38, "rice": 20, "barley": 28, "oats": 28,
    "alfalfa": 36, "hay": 33, "grass": 23, "sorghum": 33,
    "sugarcane": 45, "chickpea": 28, "pigeon_pea": 32, "groundnut": 30,
    "mustard": 28, "millet": 25, "potato": 28, "onion": 25, "tomato": 28,
    "default": 32,
}


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, dict):
        # SoilGrids / analyze-field often nest values as {"mean": …}
        for key in ("mean", "value", "avg", "Median"):
            if key in v:
                return _safe_float(v.get(key))
        return None
    try:
        return float(v)
    except Exception:
        return None


def _parse_boundary(raw: Any) -> Optional[dict]:
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return None
    return None


def _crop_key(crop_type: Optional[str]) -> str:
    """Map recorded crop names onto the twin catalog keys."""
    return _crop_source.crop_key(crop_type)


def _parse_depth_label(label: str) -> tuple[Optional[float], Optional[float]]:
    """Parse SoilGrids labels like '0-5 cm' / '0-5cm' into (top_cm, bottom_cm)."""
    if not label:
        return None, None
    cleaned = str(label).lower().replace("cm", "").strip()
    parts = cleaned.replace("–", "-").split("-")
    if len(parts) != 2:
        return None, None
    try:
        return float(parts[0]), float(parts[1])
    except (TypeError, ValueError):
        return None, None


def _normalize_soilgrids_layer(layer: Optional[dict]) -> Optional[dict]:
    if not layer or not isinstance(layer, dict):
        return None
    ph = layer.get("phh2o", layer.get("ph"))
    soc = layer.get("soc_g_per_kg", layer.get("soc"))
    sand = layer.get("sand_pct", layer.get("sand"))
    clay = layer.get("clay_pct", layer.get("clay"))
    ph_n = _safe_float(ph)
    soc_n = _safe_float(soc)
    sand_n = _safe_float(sand)
    clay_n = _safe_float(clay)
    silt_n = None
    if sand_n is not None and clay_n is not None:
        silt_n = max(0.0, 100.0 - sand_n - clay_n)
    return {
        "ph": ph_n,
        "soc_g_per_kg": soc_n,
        "organic_matter_pct": round(soc_n * 0.172, 2) if soc_n is not None else None,  # rough SOC→OM
        "sand_pct": sand_n,
        "clay_pct": clay_n,
        "silt_pct": silt_n,
        "nitrogen": _safe_float(layer.get("nitrogen")),
    }


def _location_hash(lat: float, lon: float) -> str:
    return hashlib.sha256(f"{round(lat, 5)}:{round(lon, 5)}".encode()).hexdigest()[:32]


def _empty_detection(note: str = "Field lat/lon required for crop-detection history.") -> dict:
    return {
        "available": False,
        "provenance": "none",
        "confidence": "none",
        "note": note,
        "history": [],
        "soil_layers": [],
        "cache": {"hit": False},
    }


def _parse_analyze_field_body(body: dict) -> dict:
    history_raw = body.get("history") or {}
    if not isinstance(history_raw, dict):
        history_raw = {}
    years = []
    for year_key, info in history_raw.items():
        try:
            year = int(year_key)
        except (TypeError, ValueError):
            continue
        if not isinstance(info, dict):
            continue
        crop_name = info.get("crop") or info.get("name")
        years.append({
            "year": year,
            "crop": crop_name,
            "crop_key": _crop_key(crop_name),
            "acres": _safe_float(info.get("acres")),
            "provenance": "recorded",
            "source": info.get("source") or "grower",
        })
    years.sort(key=lambda x: x["year"], reverse=True)

    soil_layers = []
    soil = body.get("soil") or {}
    if not isinstance(soil, dict):
        soil = {}
    depths = soil.get("depths") if soil.get("status") == "ok" else None
    if isinstance(depths, dict):
        for depth_label, layer in depths.items():
            if not isinstance(layer, dict):
                continue
            top_cm, bottom_cm = _parse_depth_label(depth_label)
            norm = _normalize_soilgrids_layer(layer)
            if not norm:
                continue
            soil_layers.append({
                "label": depth_label,
                "top_cm": top_cm,
                "bottom_cm": bottom_cm,
                "thickness_m": (
                    ((bottom_cm or 0) - (top_cm or 0)) / 100.0
                    if top_cm is not None and bottom_cm is not None
                    else None
                ),
                **norm,
                "provenance": "derived",
                "source": "soilgrids",
                "confidence": "medium",
            })
        soil_layers.sort(key=lambda x: (x.get("top_cm") is None, x.get("top_cm") or 0))

    latest = years[0] if years else None
    return {
        "available": bool(years or soil_layers),
        "provenance": "derived",
        "confidence": "medium" if years or soil_layers else "none",
        "source": "soilgrids",
        "coverage": "point_at_field_lat_lon",
        "history": years,
        "latest_year": latest,
        "soil_layers": soil_layers,
        "note": (
            "SoilGrids layers are gridded soil estimates at the field centroid — "
            "not a dug profile for this exact parcel. Crop identity comes from "
            "grower records / rotation, not a national land-cover map."
        ),
        "limitations": [
            "SoilGrids is modeled soil properties by depth band, not lab-measured cores.",
        ],
    }


def _read_detection_cache(
    db: Optional[Session],
    field_id: int,
    loc_hash: str,
    boundary_hash: Optional[str] = None,
) -> Optional[dict]:
    if db is None:
        return None
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        row = (
            db.query(models.FieldExternalDataCache)
            .filter(
                models.FieldExternalDataCache.FieldID == field_id,
                models.FieldExternalDataCache.Provider == "soilgrids",
                models.FieldExternalDataCache.LocationHash == loc_hash,
                models.FieldExternalDataCache.DataVersion == CACHE_DATA_VERSION,
            )
            .first()
        )
        if not row or not row.PayloadJSON:
            return None
        # Invalidate when the field boundary changed since the payload was stored.
        # Also treat legacy NULL BoundaryHash rows as stale once we have a hash —
        # otherwise boundary edits never invalidate pre-hash cache entries.
        if boundary_hash and (
            not row.BoundaryHash or row.BoundaryHash != boundary_hash
        ):
            return None
        if row.ExpiresAt and row.ExpiresAt < now:
            return None
        payload = json.loads(row.PayloadJSON)
        if isinstance(payload, dict):
            payload = dict(payload)
            payload["cache"] = {
                "hit": True,
                "stale": False,
                "fetched_at": row.FetchedAt.isoformat() + "Z" if row.FetchedAt else None,
                "expires_at": row.ExpiresAt.isoformat() + "Z" if row.ExpiresAt else None,
            }
            return payload
    except Exception:
        return None
    return None


def _write_detection_cache(
    db: Optional[Session],
    field_id: int,
    loc_hash: str,
    payload: dict,
    error: Optional[str] = None,
    boundary_hash: Optional[str] = None,
) -> None:
    if db is None:
        return
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        row = (
            db.query(models.FieldExternalDataCache)
            .filter(
                models.FieldExternalDataCache.FieldID == field_id,
                models.FieldExternalDataCache.Provider == "soilgrids",
                models.FieldExternalDataCache.LocationHash == loc_hash,
                models.FieldExternalDataCache.DataVersion == CACHE_DATA_VERSION,
            )
            .first()
        )
        if row is None:
            row = models.FieldExternalDataCache(
                FieldID=field_id,
                Provider="soilgrids",
                LocationHash=loc_hash,
                DataVersion=CACHE_DATA_VERSION,
            )
            db.add(row)
        row.LastAttemptAt = now
        if boundary_hash is not None:
            row.BoundaryHash = boundary_hash
        if error:
            row.LastError = (error or "")[:500]
            db.commit()
            return
        row.PayloadJSON = json.dumps(payload)
        row.FetchedAt = now
        row.ExpiresAt = now + timedelta(hours=CACHE_TTL_HOURS)
        row.LastError = None
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def _stale_cached_detection(
    db: Optional[Session],
    field_id: int,
    loc_hash: str,
    error: str,
    boundary_hash: Optional[str] = None,
) -> Optional[dict]:
    if db is None:
        return None
    try:
        row = (
            db.query(models.FieldExternalDataCache)
            .filter(
                models.FieldExternalDataCache.FieldID == field_id,
                models.FieldExternalDataCache.Provider == "soilgrids",
                models.FieldExternalDataCache.LocationHash == loc_hash,
                models.FieldExternalDataCache.DataVersion == CACHE_DATA_VERSION,
            )
            .first()
        )
        if not row or not row.PayloadJSON:
            return None
        if boundary_hash and (
            not row.BoundaryHash or row.BoundaryHash != boundary_hash
        ):
            return None
        payload = json.loads(row.PayloadJSON)
        if not isinstance(payload, dict):
            return None
        payload = dict(payload)
        payload["cache"] = {
            "hit": True,
            "stale": True,
            "fetched_at": row.FetchedAt.isoformat() + "Z" if row.FetchedAt else None,
        }
        _write_detection_cache(
            db, field_id, loc_hash, payload, error=error, boundary_hash=boundary_hash
        )
        return payload
    except Exception:
        return None


async def _fetch_crop_detection(
    lat: Optional[float],
    lon: Optional[float],
    db: Optional[Session] = None,
    field_id: Optional[int] = None,
    boundary: Optional[dict] = None,
) -> dict:
    """SoilGrids at field centroid. No USDA CDL on the India stack."""
    if lat is None or lon is None:
        return _empty_detection("Field lat/lon required for SoilGrids.")

    loc_hash = _location_hash(lat, lon)
    b_hash = _boundary_hash(boundary)
    if db is not None and field_id is not None:
        cached = _read_detection_cache(db, field_id, loc_hash, boundary_hash=b_hash)
        if cached is not None:
            return cached

    try:
        result = await asyncio.to_thread(_soilgrids.fetch_soilgrids, lat, lon)
        result = dict(result or {})
        result["cache"] = {"hit": False, "stale": False}
        if db is not None and field_id is not None and result.get("available"):
            _write_detection_cache(db, field_id, loc_hash, result, boundary_hash=b_hash)
        elif db is not None and field_id is not None and not result.get("available"):
            err = (result.get("note") or "soilgrids_unavailable")[:500]
            stale = _stale_cached_detection(db, field_id, loc_hash, err, boundary_hash=b_hash)
            if stale:
                return stale
            _write_detection_cache(db, field_id, loc_hash, {}, error=err, boundary_hash=b_hash)
        return result
    except Exception as e:
        stale = (
            _stale_cached_detection(db, field_id, loc_hash, "soilgrids_unreachable", boundary_hash=b_hash)
            if field_id
            else None
        )
        if stale:
            return stale
        return {
            "available": False,
            "error": "soilgrids_unreachable",
            "detail": str(e),
            "provenance": "none",
            "confidence": "none",
            "history": [],
            "soil_layers": [],
            "cache": {"hit": False},
        }


def _rotation_history(db: Session, field_id: int) -> list:
    try:
        rows = (
            db.query(models.CropRotationEntry)
            .filter(models.CropRotationEntry.FieldID == field_id)
            .order_by(desc(models.CropRotationEntry.SeasonYear))
            .limit(12)
            .all()
        )
    except Exception:
        return []
    out = []
    for rot in rows:
        out.append({
            "year": rot.SeasonYear,
            "crop": rot.CropName,
            "crop_key": _crop_key(rot.CropName),
            "variety": rot.Variety,
            "is_cover_crop": bool(rot.IsCoverCrop),
            "planting_date": str(rot.PlantingDate) if rot.PlantingDate else None,
            "harvest_date": str(rot.HarvestDate) if rot.HarvestDate else None,
            "yield_amount": _safe_float(rot.YieldAmount),
            "yield_unit": rot.YieldUnit,
            "provenance": "recorded",
            "source": "crop_rotation",
        })
    return out


def _load_crop_decision(db: Session, field_id: int, season_year: int):
    try:
        return (
            db.query(models.FieldCropSourceDecision)
            .filter(
                models.FieldCropSourceDecision.FieldID == field_id,
                models.FieldCropSourceDecision.SeasonYear == season_year,
            )
            .first()
        )
    except Exception:
        return None


def _cdl_for_year(detection: dict, year: int) -> Optional[dict]:
    for entry in detection.get("history") or []:
        if entry.get("year") == year:
            return entry
    latest = detection.get("latest_year") or {}
    if latest.get("year") == year:
        return latest
    return None


def _cdl_candidate_for_season(
    detection: dict,
    season_year: int,
    *,
    current_year: Optional[int] = None,
) -> Optional[dict]:
    """
    Resolve the CDL candidate the twin should show/confirm for a season.

    Exact-year CDL wins. For the current calendar year only, fall back to the
    latest published CDL year when this year's classification is not yet out —
    used by both snapshot and crop-resolution so they cannot disagree.
    """
    cdl = _cdl_for_year(detection, int(season_year))
    if cdl is not None:
        return cdl
    cy = current_year if current_year is not None else date.today().year
    if int(season_year) == int(cy):
        return detection.get("latest_year") or None
    return None


def _boundary_hash(boundary: Optional[dict]) -> Optional[str]:
    if not boundary:
        return None
    try:
        raw = json.dumps(boundary, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
    except Exception:
        return None


def _rotation_for_year(rotation_history: list, year: int) -> Optional[dict]:
    for entry in rotation_history or []:
        if entry.get("year") == year:
            return entry
    return None


def _candidate_dict(crop: Optional[str], crop_key: Optional[str] = None, **extra) -> Optional[dict]:
    if not crop or crop == "unknown":
        return None
    out = {"crop": crop, "crop_key": crop_key or _crop_key(crop)}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def _resolve_crop_source(
    *,
    decision,
    rotation: Optional[dict],
    field_crop: Optional[str],
    cdl: Optional[dict] = None,
    allow_field_record: bool,
) -> dict:
    """Priority: user decision → rotation → Field.CropType → unknown. No USDA CDL."""
    return _crop_source.resolve_crop_source(
        decision=decision,
        rotation=rotation,
        field_crop=field_crop,
        allow_field_record=allow_field_record,
    )


def _build_timeline(
    *,
    rotation_history: list,
    detection: dict,
    decisions: list,
    analysis: dict,
    current_year: int,
) -> list:
    years = set()
    rot_by_year = {}
    for r in rotation_history or []:
        y = r.get("year")
        if y is not None:
            years.add(int(y))
            rot_by_year[int(y)] = r
    cdl_by_year = {}
    for c in detection.get("history") or []:
        y = c.get("year")
        if y is not None:
            years.add(int(y))
            cdl_by_year[int(y)] = c
    dec_by_year = {}
    for d in decisions or []:
        years.add(int(d.SeasonYear))
        dec_by_year[int(d.SeasonYear)] = d

    analysis_year = None
    acquired = (analysis or {}).get("data") or {}
    for key in ("date", "analysis_date", "acquired_at", "capture_date"):
        raw = acquired.get(key) if isinstance(acquired, dict) else None
        if not raw and isinstance(analysis, dict):
            raw = analysis.get(key)
        if raw:
            try:
                analysis_year = int(str(raw)[:4])
                break
            except (TypeError, ValueError):
                pass

    timeline = []
    for year in sorted(years, reverse=True):
        rot = rot_by_year.get(year)
        dec = dec_by_year.get(year)
        timeline.append({
            "year": year,
            "is_current": year == current_year,
            "recorded": _candidate_dict(
                (rot or {}).get("crop"),
                (rot or {}).get("crop_key"),
                source="crop_rotation",
            ) if rot else None,
            "cdl": None,
            "decision": {
                "selected_source": dec.SelectedSource,
                "selected_crop": dec.SelectedCrop,
                "selected_crop_key": _crop_key(dec.SelectedCrop),
                "decided_at": dec.DecidedAt.isoformat() + "Z" if dec.DecidedAt else None,
            } if dec else None,
            "imagery_match": analysis_year == year if analysis_year is not None else None,
        })
    return timeline


def _load_crop_decisions(db: Session, field_id: int) -> list:
    try:
        return (
            db.query(models.FieldCropSourceDecision)
            .filter(models.FieldCropSourceDecision.FieldID == field_id)
            .order_by(desc(models.FieldCropSourceDecision.SeasonYear))
            .limit(20)
            .all()
        )
    except Exception:
        return []


class CropResolutionRequest(BaseModel):
    season_year: int = Field(..., ge=1980, le=2100)
    choice: Literal["crop_rotation", "field_record"]
    expected_recorded_crop: Optional[str] = None


def _build_soil_cutaway(profile: dict, soil_samples: list, detection: dict) -> dict:
    """
    Prefer measured samples + SoilGrids depth bands for underground mode.
    Never invent fake bedrock geology when data is missing.
    """
    layers = list(detection.get("soil_layers") or [])
    measured_summary = None
    if soil_samples:
        phs = [s["ph"] for s in soil_samples if s.get("ph") is not None]
        oms = [s["organic_matter"] for s in soil_samples if s.get("organic_matter") is not None]
        depths = [s["depth_cm"] for s in soil_samples if s.get("depth_cm") is not None]
        measured_summary = {
            "sample_count": len(soil_samples),
            "ph_mean": round(sum(phs) / len(phs), 2) if phs else None,
            "organic_matter_mean": round(sum(oms) / len(oms), 2) if oms else None,
            "depth_cm_max": max(depths) if depths else None,
            "provenance": "observed",
        }

    profile_data = (profile or {}).get("data") if (profile or {}).get("available") else None
    has_layers = len(layers) > 0
    has_samples = len(soil_samples) > 0
    has_profile = bool(profile_data)

    return {
        "available": has_layers or has_samples or has_profile,
        "mode": (
            "measured_and_grids" if has_layers and has_samples
            else "soilgrids" if has_layers
            else "measured_samples" if has_samples
            else "field_profile" if has_profile
            else "none"
        ),
        "layers": layers,
        "measured_summary": measured_summary,
        "profile": profile_data,
        "provenance": (
            "observed" if has_samples
            else "derived" if has_layers
            else "recorded" if has_profile
            else "none"
        ),
        "confidence": (
            "high" if has_samples
            else "medium" if has_layers or has_profile
            else "none"
        ),
        "note": (
            "Underground view shows SoilGrids depth bands and/or lab soil samples for this field. "
            "It is not a surveyed pedon."
            if (has_layers or has_samples or has_profile)
            else "No soil samples, SoilGrids layers, or field profile yet — underground view stays empty."
        ),
    }


def _estimate_growth_stage(crop_type: Optional[str], planting_date: Optional[date]) -> dict:
    """Modeled growth stage from planting date — never claimed as observed."""
    key = _crop_key(crop_type)
    maturity = _CROP_MATURITY_DAYS.get(key, _CROP_MATURITY_DAYS["default"])
    if not planting_date:
        return {
            "stage": "unknown",
            "progress_pct": None,
            "days_since_planting": None,
            "maturity_days_assumed": maturity,
            "provenance": "modeled",
            "confidence": "low",
            "note": "No planting date on record; growth stage is unknown.",
        }
    today = date.today()
    days = max(0, (today - planting_date).days)
    progress = min(1.0, days / float(maturity))
    if progress < 0.15:
        stage = "emergence"
    elif progress < 0.40:
        stage = "vegetative"
    elif progress < 0.70:
        stage = "reproductive"
    elif progress < 0.95:
        stage = "mature"
    else:
        stage = "senescence"
    return {
        "stage": stage,
        "progress_pct": round(progress * 100, 1),
        "days_since_planting": days,
        "maturity_days_assumed": maturity,
        "provenance": "modeled",
        "confidence": "medium",
        "note": "Estimated from planting date and typical crop maturity; not a field observation.",
    }


def _ser_soil(row) -> dict:
    lat = _safe_float(row.Latitude)
    lon = _safe_float(row.Longitude)
    located = lat is not None and lon is not None
    return {
        "sample_id": row.SampleID,
        "field_id": row.FieldID,
        "business_id": row.BusinessID,
        "sample_date": str(row.SampleDate) if row.SampleDate else None,
        "sample_label": row.SampleLabel,
        "latitude": lat,
        "longitude": lon,
        "location_status": "located" if located else "unlocated",
        "depth_cm": row.Depth_cm,
        "ph": _safe_float(row.pH),
        "organic_matter": _safe_float(row.OrganicMatter),
        "nitrogen": _safe_float(row.Nitrogen),
        "phosphorus": _safe_float(row.Phosphorus),
        "potassium": _safe_float(row.Potassium),
        "sulfur": _safe_float(row.Sulfur),
        "calcium": _safe_float(row.Calcium),
        "magnesium": _safe_float(row.Magnesium),
        "cec": _safe_float(row.CEC),
        "notes": row.Notes,
        "created_at": row.CreatedAt.isoformat() + "Z" if row.CreatedAt else None,
        "provenance": "observed",
        "confidence": "high",
    }


def _ser_scout(row) -> dict:
    return {
        "scout_id": row.ScoutID,
        "field_id": row.FieldID,
        "business_id": row.BusinessID,
        "people_id": row.PeopleID,
        "observed_at": row.ObservedAt.isoformat() + "Z" if row.ObservedAt else None,
        "category": row.Category,
        "severity": row.Severity,
        "notes": row.Notes,
        "latitude": _safe_float(row.Latitude),
        "longitude": _safe_float(row.Longitude),
        "image_url": row.ImageUrl,
        "created_at": row.CreatedAt.isoformat() + "Z" if row.CreatedAt else None,
        "provenance": "observed",
        "confidence": "high",
    }


def _load_profile(db: Session, field_id: int) -> dict:
    try:
        row = db.execute(text("""
            SELECT SoilType, DrainageClass, SlopePercent, Topography,
                   OrganicMatterPct, PhLevel, FieldNotes, PhotoUrls, UpdatedAt
            FROM FieldProfile WHERE FieldID = :fid
        """), {"fid": field_id}).fetchone()
    except Exception:
        return {"available": False, "data": None, "error": "profile_table_unavailable"}
    if not row:
        return {"available": False, "data": None, "provenance": "none"}
    return {
        "available": True,
        "provenance": "observed",
        "confidence": "high",
        "data": {
            "soil_type": row.SoilType,
            "drainage_class": row.DrainageClass,
            "slope_percent": _safe_float(row.SlopePercent),
            "topography": row.Topography,
            "organic_matter_pct": _safe_float(row.OrganicMatterPct),
            "ph_level": _safe_float(row.PhLevel),
            "field_notes": row.FieldNotes,
            "photo_urls": row.PhotoUrls,
            "updated_at": row.UpdatedAt.isoformat() if row.UpdatedAt else None,
        },
    }


def _vegetation_from_terrain(field_id: int, grid: int, terrain: dict) -> dict:
    """Spatial NDVI/NDWI asset contract — grids fetched by client via JWT proxy."""
    overlays = set(terrain.get("overlays_available") or [])
    texture = terrain.get("texture") or {}
    grid_meta = terrain.get("grid") or {}
    assets = terrain.get("assets") or {}
    has_ndvi = "ndvi" in overlays or bool(assets.get("ndvi") or assets.get("ndvi_png"))
    has_ndwi = "ndwi" in overlays or bool(assets.get("ndwi") or assets.get("ndwi_png"))
    # Allow overlay asset URLs even when DEM metadata failed — client probes the proxy.
    if not has_ndvi and not has_ndwi:
        return {
            "available": False,
            "provenance": "none",
            "confidence": "none",
            "note": "No co-registered NDVI/NDWI grid is available for this field yet.",
            "limitations": [
                "Without a vegetation grid, canopy height/color are illustrative only.",
            ],
        }
    acquired = texture.get("acquired_at")
    cloud = texture.get("cloud_percent")
    res_m = grid_meta.get("resolution_m_approx")
    conf = "high" if terrain.get("available") else "low"
    if cloud is not None:
        try:
            if float(cloud) >= 40:
                conf = "low"
            elif float(cloud) >= 20:
                conf = "medium"
        except (TypeError, ValueError):
            pass

    age_days = None
    freshness = "unknown"
    if acquired:
        try:
            acq = str(acquired)[:10]
            age_days = (date.today() - date.fromisoformat(acq)).days
            if age_days > 14:
                freshness = "stale"
                conf = "low"
            elif age_days > 7:
                freshness = "aging"
                if conf == "high":
                    conf = "medium"
            else:
                freshness = "fresh"
        except (TypeError, ValueError):
            pass

    limitations = list(terrain.get("limitations") or []) + (
        []
        if terrain.get("available")
        else ["DEM/terrain metadata failed; index overlays may still load."]
    ) + [
        "NDVI/NDWI are satellite-derived relative indices over the field bbox — not plant counts or measured height.",
        "Cloudy or masked pixels are null; the twin must not invent healthy canopy there.",
        "Canopy geometry driven from NDVI is illustrative/model-driven, not surveyed plant stature.",
    ]
    if freshness == "stale":
        limitations.append(
            f"Vegetation map is {age_days} days old — treat greenness as outdated until a newer scene arrives."
        )

    return {
        "available": True,
        "provenance": "derived",
        "confidence": conf,
        "source": texture.get("source") or "sentinel-2-l2a",
        "acquired_at": acquired,
        "age_days": age_days,
        "freshness": freshness,
        "cloud_percent": cloud,
        "spatial_resolution_m": res_m,
        "native_sensor_resolution_m": 10,
        "coverage": "field_bbox_grid",
        "assets": {
            "ndvi_json": assets.get("ndvi_json")
            or (f"/api/fields/{field_id}/terrain/overlay/ndvi?grid={grid}&format=json" if has_ndvi else None),
            "ndwi_json": assets.get("ndwi_json")
            or (f"/api/fields/{field_id}/terrain/overlay/ndwi?grid={grid}&format=json" if has_ndwi else None),
            "ndvi_png": assets.get("ndvi")
            or (f"/api/fields/{field_id}/terrain/overlay/ndvi?grid={grid}&format=png" if has_ndvi else None),
            "ndwi_png": assets.get("ndwi")
            or (f"/api/fields/{field_id}/terrain/overlay/ndwi?grid={grid}&format=png" if has_ndwi else None),
        },
        "overlays_available": sorted(
            ({"ndvi"} if has_ndvi else set()) | ({"ndwi"} if has_ndwi else set())
        ),
        "note": (
            None
            if terrain.get("available") and freshness != "stale"
            else (
                f"Vegetation map is {age_days} days old — confirm with a field walk."
                if freshness == "stale"
                else "Terrain metadata was unavailable — overlay URLs are best-effort via the proxy."
            )
        ),
        "limitations": limitations,
    }


def _fetch_water_use(field_id: int) -> dict:
    """OpenET/WaPOR ETa via CropMonitor — gridded satellite ET, not an on-field lysimeter."""
    try:
        r = requests.get(
            f"{CROP_MONITOR_URL}/api/fields/{field_id}/wapor/water",
            timeout=25,
        )
        if not r.ok:
            return {
                "available": False,
                "error": f"water_use_{r.status_code}",
                "provenance": "none",
                "confidence": "none",
            }
        body = r.json() or {}
        wapor = body.get("wapor") or body
        if not wapor or wapor.get("error"):
            return {
                "available": False,
                "error": (wapor or {}).get("error") or "no_data",
                "provenance": "none",
                "confidence": "none",
                "note": "OpenET/WaPOR water-use snapshot unavailable for this field.",
            }
        stats = wapor.get("stats") or {}
        return {
            "available": True,
            "provenance": "derived",
            "confidence": "medium",
            "source": wapor.get("source") or "openet",
            "variable": wapor.get("variable"),
            "model": wapor.get("model"),
            "reference_et": wapor.get("reference_et"),
            "eta_mm": stats.get("mean"),
            "period_date": wapor.get("date"),
            "coverage": "satellite_point_at_centroid",
            "note": (
                "Satellite actual ET near the field centroid (OpenET/WaPOR) — "
                "not an on-field water-use measurement."
            ),
            "limitations": [
                "Point/gridded satellite product; spatial support may exceed a small field.",
                "Period date is the product period, not an instantaneous field reading.",
            ],
            "asset_url": f"/api/fields/{field_id}/water-use",
        }
    except requests.RequestException as e:
        return {
            "available": False,
            "error": "water_use_unreachable",
            "detail": str(e),
            "provenance": "none",
            "confidence": "none",
        }


def _terrain_asset_urls(field_id: int, grid: int, texture_qs: Optional[str] = None) -> dict:
    """Authenticated proxy paths the twin client fetches with the user JWT."""
    tex_qs = texture_qs or f"grid={grid}"
    return {
        "elevation": f"/api/fields/{field_id}/terrain/elevation?grid={grid}&format=json",
        "texture": f"/api/fields/{field_id}/terrain/texture?{tex_qs}",
        "overlay_template": f"/api/fields/{field_id}/terrain/overlay/{{layer}}?grid={grid}&format=png",
        "wetness_risk": f"/api/fields/{field_id}/terrain/overlay/wetness-risk?grid={grid}&format=png",
        "ndvi": f"/api/fields/{field_id}/terrain/overlay/ndvi?grid={grid}&format=png",
        "ndwi": f"/api/fields/{field_id}/terrain/overlay/ndwi?grid={grid}&format=png",
        "ndvi_json": f"/api/fields/{field_id}/terrain/overlay/ndvi?grid={grid}&format=json",
        "ndwi_json": f"/api/fields/{field_id}/terrain/overlay/ndwi?grid={grid}&format=json",
    }


def _fetch_terrain_meta(
    field_id: int,
    grid: int,
    season_year: Optional[int] = None,
    field=None,
) -> dict:
    def _screening_payload() -> dict:
        if field is None:
            return {
                "available": False,
                "error": "terrain_metadata_unavailable",
                "assets": _terrain_asset_urls(field_id, grid),
                "overlays_available": ["ndvi", "ndwi", "wetness-risk"],
            }
        meta = _terrain_screening.build_screening_metadata(field, field_id, grid)
        assets = _terrain_asset_urls(field_id, grid)
        return {
            "available": True,
            "provenance": (meta.get("elevation") or {}).get("provenance") or "derived",
            "confidence": (meta.get("elevation") or {}).get("confidence") or "medium",
            "source": meta.get("source") or "screening_local",
            "grid": meta.get("grid"),
            "elevation_summary": (meta.get("elevation") or {}).get("summary"),
            "slope": meta.get("slope"),
            "texture": meta.get("texture"),
            "overlays_available": meta.get("overlays_available"),
            "centroid": meta.get("centroid"),
            "boundary": meta.get("boundary"),
            "assets": assets,
            "notes": meta.get("notes") or [],
            "limitations": (meta.get("elevation") or {}).get("limitations") or [],
        }

    try:
        # Keep this short: callers must run us in a worker thread when
        # CROP_MONITOR_URL points at the same uvicorn process (/cm), or a
        # sync GET deadlocks the event loop and Field Twin never loads.
        r = requests.get(
            f"{CROP_MONITOR_URL}/api/fields/{field_id}/terrain/metadata",
            params={"grid": grid, "include_radar": "true"},
            timeout=20,
        )
        if not r.ok:
            return _screening_payload()
        meta = r.json()
        texture = dict(meta.get("texture") or {})
        texture_acquired = texture.get("acquired_at") or texture.get("date")
        texture_year = None
        if texture_acquired:
            try:
                texture_year = int(str(texture_acquired)[:4])
            except (TypeError, ValueError):
                texture_year = None

        year_matched = (
            season_year is None
            or texture_year == season_year
        )
        matched_analysis_id = None
        if season_year is not None and not year_matched:
            matched = _find_analysis_for_year(field_id, season_year)
            if matched:
                matched_analysis_id = matched.get("analysis_id")
                texture_year = season_year
                year_matched = True
                texture = {
                    **texture,
                    "acquired_at": matched.get("satellite_acquired_at") or matched.get("analysis_date"),
                    "analysis_id": matched_analysis_id,
                    "source": "crop_monitor_analysis",
                }

        tex_qs = f"grid={grid}"
        if matched_analysis_id is not None:
            tex_qs += f"&analysis_id={matched_analysis_id}"
        elif season_year is not None and year_matched and texture_year == season_year:
            tex_qs += f"&year={season_year}"

        texture_meta = {
            **texture,
            "year": texture_year,
            "year_matched": bool(year_matched),
            "requested_year": season_year,
            "note": (
                None
                if year_matched
                else (
                    f"Natural imagery is from {texture_year or 'the latest available scene'}, "
                    f"not season {season_year}. Do not treat it as historical imagery for that year."
                )
            ),
        }

        assets = _terrain_asset_urls(field_id, grid, tex_qs)
        if not (year_matched or season_year is None):
            assets["texture"] = None

        return {
            "available": True,
            "provenance": "derived",
            "confidence": "high" if year_matched else "medium",
            "source": "crop_monitor",
            "grid": meta.get("grid"),
            "elevation_summary": (meta.get("elevation") or {}).get("summary"),
            "slope": meta.get("slope"),
            "texture": texture_meta,
            "overlays_available": meta.get("overlays_available"),
            "centroid": meta.get("centroid"),
            "boundary": meta.get("boundary"),
            "assets": assets,
            "notes": meta.get("notes") or [],
            "limitations": (meta.get("elevation") or {}).get("limitations") or [],
        }
    except requests.RequestException:
        return _screening_payload()

def _find_analysis_for_year(field_id: int, season_year: int) -> Optional[dict]:
    """Best-effort year-matched analysis from CropMonitor for historical texture."""
    try:
        r = requests.get(
            f"{CROP_MONITOR_URL}/api/fields/{field_id}/analyses",
            params={"limit": 40},
            timeout=15,
        )
        if not r.ok:
            return None
        analyses = (r.json() or {}).get("analyses") or []
        for a in analyses:
            for key in ("analysis_date", "satellite_acquired_at", "date", "acquired_at"):
                raw = a.get(key)
                if not raw:
                    continue
                try:
                    if int(str(raw)[:4]) == int(season_year):
                        return {
                            "analysis_id": a.get("analysis_id") or a.get("id"),
                            "analysis_date": a.get("analysis_date"),
                            "satellite_acquired_at": a.get("satellite_acquired_at"),
                        }
                except (TypeError, ValueError):
                    continue
    except Exception:
        return None
    return None


def _fetch_latest_analysis_remote(field_id: int) -> dict:
    """HTTP-only analysis fetch — safe to run via asyncio.to_thread."""
    try:
        r = requests.get(
            f"{CROP_MONITOR_URL}/api/fields/{field_id}/analyses",
            params={"limit": 1},
            timeout=15,
        )
        if r.ok:
            analyses = (r.json() or {}).get("analyses") or []
            if analyses:
                a = analyses[0]
                return {
                    "available": True,
                    "provenance": "derived",
                    "confidence": "high",
                    "data": {
                        "analysis_id": a.get("analysis_id") or a.get("id"),
                        "analysis_date": a.get("analysis_date"),
                        "health_score": a.get("health_score"),
                        "status": a.get("status"),
                        "cloud_percent": a.get("cloud_percent"),
                        "satellite_acquired_at": a.get("satellite_acquired_at"),
                        "vegetation_indices": a.get("vegetation_indices") or [],
                    },
                }
    except Exception:
        pass
    return {"available": False, "data": None}


def _fetch_latest_analysis_local(field_id: int, db: Session) -> dict:
    """Local biomass fallback — keep on the request thread (SQLAlchemy session)."""
    try:
        row = (
            db.query(models.FieldBiomassAnalysis)
            .filter(models.FieldBiomassAnalysis.FieldID == field_id)
            .order_by(desc(models.FieldBiomassAnalysis.CapturedAt))
            .first()
        )
        if row:
            features = {}
            try:
                features = json.loads(row.FeaturesJSON or "{}")
            except Exception:
                pass
            return {
                "available": True,
                "provenance": "derived",
                "confidence": "medium",
                "data": {
                    "analysis_id": None,
                    "analysis_date": row.CapturedAt.isoformat()[:10] if row.CapturedAt else None,
                    "health_score": features.get("health_score"),
                    "status": None,
                    "vegetation_indices": features.get("vegetation_indices") or [],
                    "source": "local",
                },
            }
    except Exception:
        pass
    return {"available": False, "data": None}


def _fetch_latest_analysis(field_id: int, db: Session) -> dict:
    remote = _fetch_latest_analysis_remote(field_id)
    if remote.get("available"):
        return remote
    return _fetch_latest_analysis_local(field_id, db)


def _fetch_weather(lat: float, lon: float, days: int = 14) -> dict:
    return _weather_metric.fetch_weather(lat, lon, days)


def _fetch_field_moisture_probe(db: Session, field_id: int) -> Optional[dict]:
    """Latest SoilMoistureReading for any irrigation zone on this field."""
    try:
        row = db.execute(text("""
            SELECT TOP 1 m.MoisturePct, m.DepthCm, m.ReadingTime, m.Source, m.TempC
            FROM SoilMoistureReading m
            INNER JOIN IrrigationZone z ON z.ZoneID = m.ZoneID
            WHERE TRY_CAST(z.FieldID AS INT) = :fid
              AND m.MoisturePct IS NOT NULL
            ORDER BY m.ReadingTime DESC
        """), {"fid": field_id}).fetchone()
    except Exception:
        return None
    if not row or row[0] is None:
        return None
    return {
        "moisture_pct": float(row[0]),
        "depth_cm": int(row[1]) if row[1] is not None else None,
        "reading_time": row[2].isoformat() + "Z" if row[2] else None,
        "source": row[3] or "probe",
        "temp_c": float(row[4]) if row[4] is not None else None,
        "provenance": "observed",
        "confidence": "high",
    }


def _fetch_irrigation_applied_mm(db: Session, field_id: int, days: int = 21) -> dict:
    """Sum of logged IrrigationEvent depths (millimetres) in the lookback window."""
    try:
        row = db.execute(text("""
            SELECT
                COALESCE(SUM(e.DepthMm), 0) AS depth_mm,
                COUNT(*) AS n_events,
                MAX(e.StartTime) AS last_at
            FROM IrrigationEvent e
            INNER JOIN IrrigationZone z ON z.ZoneID = e.ZoneID
            WHERE TRY_CAST(z.FieldID AS INT) = :fid
              AND e.StartTime >= DATEADD(day, -:days, GETDATE())
              AND e.DepthMm IS NOT NULL
        """), {"fid": field_id, "days": int(days)}).fetchone()
    except Exception:
        return {"available": False, "applied_mm": 0.0, "events": 0}
    depth_mm = float(row[0] or 0.0) if row else 0.0
    return {
        "available": True,
        "applied_mm": round(depth_mm, 2),
        "events": int(row[1] or 0) if row else 0,
        "last_at": row[2].isoformat() + "Z" if row and row[2] else None,
        "provenance": "observed" if (row and int(row[1] or 0) > 0) else "none",
        "confidence": "high" if (row and int(row[1] or 0) > 0) else "none",
        "note": "Sum of IrrigationEvent.DepthMm for field zones in the lookback window.",
    }


def _ensure_precip_log_table(db: Session) -> None:
    try:
        db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='FieldPrecipLog')
        CREATE TABLE FieldPrecipLog (
            LogID INT IDENTITY PRIMARY KEY,
            FieldID INT NOT NULL,
            BusinessID INT NOT NULL,
            ObservedAt DATETIME NOT NULL,
            DepthIn DECIMAL(8,3) NOT NULL,
            DepthMm DECIMAL(8,3) NULL,
            Source NVARCHAR(40) NOT NULL DEFAULT 'gauge',
            Notes NVARCHAR(500) NULL,
            CreatedAt DATETIME NOT NULL DEFAULT GETDATE(),
            CreatedByPeopleID INT NULL
        )
        """))
        db.commit()
        db.execute(text("""
        IF NOT EXISTS (
            SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'FieldPrecipLog' AND COLUMN_NAME = 'DepthMm'
        )
        ALTER TABLE FieldPrecipLog ADD DepthMm DECIMAL(8,3) NULL
        """))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def _fetch_precip_logged_mm(db: Session, field_id: int, days: int = 21) -> dict:
    """Farmer / gauge precip logs (millimetres). Prefer over grid when present."""
    _ensure_precip_log_table(db)
    try:
        row = db.execute(text("""
            SELECT
                COALESCE(SUM(COALESCE(DepthMm, DepthIn)), 0) AS depth_mm,
                COUNT(*) AS n_logs,
                MAX(ObservedAt) AS last_at
            FROM FieldPrecipLog
            WHERE FieldID = :fid
              AND ObservedAt >= DATEADD(day, -:days, GETDATE())
        """), {"fid": field_id, "days": int(days)}).fetchone()
    except Exception:
        return {"available": False, "precip_mm": 0.0, "logs": 0}
    depth_mm = float(row[0] or 0.0) if row else 0.0
    n = int(row[1] or 0) if row else 0
    return {
        "available": n > 0,
        "precip_mm": round(depth_mm, 2),
        "logs": n,
        "last_at": row[2].isoformat() + "Z" if row and row[2] else None,
        "provenance": "observed" if n > 0 else "none",
        "confidence": "high" if n > 0 else "none",
        "note": (
            "Farmer/gauge FieldPrecipLog sum in millimetres — used instead of "
            "weather-grid precip when present. Prefers DepthMm; DepthIn kept for older rows."
        ),
    }


def _fertility_from_samples(located_samples: list) -> dict:
    """Simple field-average fertility from GPS lab cores (no invented map)."""
    if not located_samples:
        return {
            "available": False,
            "provenance": "none",
            "confidence": "none",
            "note": "No GPS soil lab cores yet — add tests to unlock fertility averages.",
        }

    def avg(key):
        vals = [s[key] for s in located_samples if s.get(key) is not None]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 2)

    return {
        "available": True,
        "provenance": "observed",
        "confidence": "high",
        "core_count": len(located_samples),
        "averages": {
            "ph": avg("ph"),
            "organic_matter": avg("organic_matter"),
            "nitrogen": avg("nitrogen"),
            "phosphorus": avg("phosphorus"),
            "potassium": avg("potassium"),
            "cec": avg("cec"),
        },
        "note": (
            f"Average of {len(located_samples)} GPS-located lab core(s) — "
            "field mean only, not a contour map."
        ),
        "limitations": [
            "Unlocated samples are excluded.",
            "Averages do not replace zone maps or agronomist prescription.",
        ],
    }


def _infiltration_from_detection(detection: dict) -> dict:
    """Map SoilGrids clay% → default infiltration_class for water what-ifs."""
    layers = detection.get("soil_layers") or []
    clay_vals = []
    sand_vals = []
    for layer in layers:
        norm = layer if isinstance(layer, dict) and "clay_pct" in layer else _normalize_soilgrids_layer(layer if isinstance(layer, dict) else None)
        if not norm:
            continue
        if norm.get("clay_pct") is not None:
            clay_vals.append(float(norm["clay_pct"]))
        if norm.get("sand_pct") is not None:
            sand_vals.append(float(norm["sand_pct"]))
    if not clay_vals:
        return {
            "available": False,
            "infiltration_class": "moderate",
            "source": "default",
            "note": "No SoilGrids texture — using moderate infiltration default.",
        }
    clay = sum(clay_vals) / len(clay_vals)
    sand = (sum(sand_vals) / len(sand_vals)) if sand_vals else None
    if clay >= 40:
        infil = "very_slow"
    elif clay >= 28:
        infil = "slow"
    elif sand is not None and sand >= 70:
        infil = "fast"
    else:
        infil = "moderate"
    return {
        "available": True,
        "infiltration_class": infil,
        "clay_pct_mean": round(clay, 1),
        "sand_pct_mean": round(sand, 1) if sand is not None else None,
        "source": "soilgrids",
        "provenance": "derived",
        "confidence": "medium",
        "note": "Default water what-if infiltration from SoilGrids texture — confirm on site.",
    }


def _irrigation_summary(
    crop_type: Optional[str],
    weather: dict,
    *,
    water_use: Optional[dict] = None,
    applied_irrig: Optional[dict] = None,
    precip_log: Optional[dict] = None,
) -> dict:
    """Rolling water balance in millimetres.

    Accuracy rules:
    - Past days only for weather (forecast rain does not cancel deficit).
    - Prefer OpenET ETa when available over ET0×Kc.
    - Prefer farmer gauge precip logs over Open-Meteo grid when present.
    - Subtract logged irrigation events.
    """
    if not weather.get("available") and not (water_use or {}).get("available"):
        return {
            "available": False,
            "provenance": "modeled",
            "confidence": "low",
            "units": "mm",
            "note": "Weather / ET unavailable — cannot estimate crop water need.",
        }
    key = _crop_key(crop_type)
    kc = _CROP_KC.get(key, _CROP_KC["default"])
    mad = _CROP_MAD_MM.get(key, _CROP_MAD_MM["default"])
    today = date.today().isoformat()

    precip_sum = 0.0
    etc_sum = 0.0
    days_used = 0
    precip_source = "open_meteo"
    et_source = "open_meteo_et0_kc"

    for day in weather.get("daily") or []:
        d = day.get("date")
        if not d or str(d) > today:
            continue
        precip_sum += float(day.get("precip") or 0.0)
        etc_sum += float(day.get("et0") or 0.0) * kc
        days_used += 1

    # Prefer satellite actual ET (mm) when CropMonitor returns it.
    if water_use and water_use.get("available") and water_use.get("eta_mm") is not None:
        try:
            etc_sum = float(water_use["eta_mm"])
            et_source = "openet"
        except (TypeError, ValueError):
            pass

    # Prefer gauge / farmer precip logs when present (avoid mixing).
    if precip_log and precip_log.get("available") and precip_log.get("precip_mm") is not None:
        precip_sum = float(precip_log["precip_mm"])
        precip_source = "field_gauge"

    applied_mm = float((applied_irrig or {}).get("applied_mm") or 0.0)

    # Rolling day balance when we have daily weather; else bulk deficit.
    if days_used > 0 and precip_source == "open_meteo" and et_source == "open_meteo_et0_kc":
        cumulative = 0.0
        for day in weather.get("daily") or []:
            d = day.get("date")
            if not d or str(d) > today:
                continue
            p = float(day.get("precip") or 0.0)
            etc = float(day.get("et0") or 0.0) * kc
            cumulative = max(0.0, cumulative + max(0.0, etc - p) - max(0.0, p - etc))
        cumulative = max(0.0, cumulative - applied_mm)
    else:
        cumulative = max(0.0, etc_sum - precip_sum - applied_mm)

    apply_mm = round(cumulative, 0) if cumulative >= 4.0 else 0.0
    if cumulative >= mad:
        recommendation = f"Est. ~{apply_mm:.0f} mm canal/borewell irrigate (not a schedule)"
        urgency = "high"
        farmer_status = "short"
    elif cumulative >= mad * 0.55:
        recommendation = f"Watch — about {apply_mm:.0f} mm short (est., not a schedule)"
        urgency = "medium"
        farmer_status = "watch"
    else:
        recommendation = "Soil water OK for now (est., not a schedule)"
        urgency = "low"
        farmer_status = "ok"
        apply_mm = 0.0

    conf = "medium"
    if et_source == "openet" or precip_source == "field_gauge" or applied_mm > 0:
        conf = "medium"
    if days_used < 7 and et_source != "openet":
        conf = "low"
    if (applied_irrig or {}).get("events") or (precip_log or {}).get("logs"):
        conf = "high" if farmer_status != "short" else "medium"

    return {
        "available": True,
        "provenance": "modeled",
        "confidence": conf,
        "units": "mm",
        "note": (
            f"Estimate only — not an irrigation schedule. Canal or borewell sets should "
            f"be confirmed on site. Balance uses ET via {et_source}, precip via {precip_source}, "
            f"minus {applied_mm:.1f} mm logged irrigate "
            f"({days_used} past weather days, MAD ≈ {mad:.0f} mm)."
        ),
        "crop_type": crop_type,
        "crop_key": key,
        "kc": kc,
        "mad_mm": mad,
        "days_used": days_used,
        "precip_sum_mm": round(precip_sum, 2),
        "etc_sum_mm": round(etc_sum, 2),
        "applied_irrig_mm": round(applied_mm, 2),
        "precip_source": precip_source,
        "et_source": et_source,
        "cumulative_deficit_mm": round(cumulative, 2),
        "deficit_mm": round(cumulative, 2),
        "suggested_apply_mm": apply_mm,
        "farmer_status": farmer_status,
        "recommendation": recommendation,
        "urgency": urgency,
    }


def _classify_soil_moisture(
    irrigation: dict,
    profile: dict,
    soil_samples: list,
    probe: Optional[dict] = None,
) -> dict:
    """Moisture class — prefer in-field probe, else water-balance, else OM proxy."""
    if probe and probe.get("moisture_pct") is not None:
        pct = float(probe["moisture_pct"])
        if pct < 18:
            level, farmer_label = "low", "likely dry"
        elif pct < 28:
            level, farmer_label = "moderate", "getting dry"
        else:
            level, farmer_label = "high", "likely OK"
        return {
            "level": level,
            "farmer_label": farmer_label,
            "moisture_pct": pct,
            "depth_cm": probe.get("depth_cm"),
            "reading_time": probe.get("reading_time"),
            "provenance": "observed",
            "confidence": "high",
            "basis": "soil_moisture_probe",
            "source": probe.get("source") or "probe",
            "units": "percent",
            "note": (
                f"In-field probe reading {pct:.1f}% at "
                f"{probe.get('depth_cm') or '?'} cm"
                + (f" · {str(probe.get('reading_time') or '')[:16]}" if probe.get("reading_time") else "")
            ),
        }

    om_vals = [s["organic_matter"] for s in soil_samples if s.get("organic_matter") is not None]
    profile_om = (profile.get("data") or {}).get("organic_matter_pct") if profile.get("available") else None
    deficit = irrigation.get("cumulative_deficit_mm") if irrigation.get("available") else None
    mad = irrigation.get("mad_mm") or _CROP_MAD_MM["default"]

    if deficit is not None:
        if deficit >= mad:
            level, farmer_label = "low", "likely dry"
        elif deficit >= mad * 0.55:
            level, farmer_label = "moderate", "getting dry"
        else:
            level, farmer_label = "high", "likely OK"
        return {
            "level": level,
            "farmer_label": farmer_label,
            "provenance": "modeled",
            "confidence": irrigation.get("confidence") or "medium",
            "basis": "irrigation_water_balance",
            "deficit_mm": deficit,
            "mad_mm": mad,
            "units": "mm",
            "note": (
                f"From weather water balance (~{deficit:.0f} mm short vs MAD {mad:.0f} mm) — "
                "not an in-field moisture probe."
            ),
        }

    om = profile_om if profile_om is not None else (sum(om_vals) / len(om_vals) if om_vals else None)
    if om is not None:
        level = "high" if om >= 4 else ("moderate" if om >= 2 else "low")
        farmer_label = "likely OK" if level == "high" else ("getting dry" if level == "moderate" else "likely dry")
        return {
            "level": level,
            "farmer_label": farmer_label,
            "provenance": "modeled",
            "confidence": "low",
            "basis": "organic_matter_proxy",
            "organic_matter_pct": om,
            "note": "Weak proxy from organic matter only — illustrative, not measured moisture.",
        }

    return {
        "level": "unknown",
        "farmer_label": "unknown",
        "provenance": "none",
        "confidence": "none",
        "note": "Insufficient data to estimate soil moisture.",
    }


def _local_origin(boundary: Optional[dict], lat: Optional[float], lon: Optional[float]) -> dict:
    """Origin for local-meter projection (centroid of bbox or field lat/lon)."""
    if boundary:
        coords = []

        def walk(c):
            if not isinstance(c, list):
                return
            if c and isinstance(c[0], (int, float)) and len(c) >= 2:
                coords.append((float(c[0]), float(c[1])))
                return
            for x in c:
                walk(x)

        geom = boundary
        if boundary.get("type") == "FeatureCollection":
            for f in boundary.get("features") or []:
                g = (f or {}).get("geometry") or {}
                walk(g.get("coordinates"))
        elif boundary.get("type") == "Feature":
            walk((boundary.get("geometry") or {}).get("coordinates"))
        elif boundary.get("type") in ("Polygon", "MultiPolygon"):
            walk(boundary.get("coordinates"))

        if coords:
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            return {
                "longitude": (min(lons) + max(lons)) / 2,
                "latitude": (min(lats) + max(lats)) / 2,
                "crs": "local-meters-from-wgs84",
            }
    if lat is not None and lon is not None:
        return {"longitude": lon, "latitude": lat, "crs": "local-meters-from-wgs84"}
    return {"longitude": None, "latitude": None, "crs": "local-meters-from-wgs84"}


@router.get("/fields/{field_id}/twin-snapshot")
async def get_field_twin_snapshot(
    field_id: int,
    grid: int = 96,
    weather_days: int = 21,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Authenticated field digital-twin snapshot.

    Elevation grid itself is NOT embedded (too large) — clients fetch
    `terrain.assets.elevation` with the same JWT.
    """
    business_id = _verify_field_access(db, user.PeopleID, field_id)
    grid = max(32, min(int(grid or 96), 256))
    weather_days = max(7, min(int(weather_days or 21), 30))
    current_year = date.today().year

    field = (
        db.query(models.Field)
        .filter(models.Field.FieldID == field_id, models.Field.DeletedAt.is_(None))
        .first()
    )
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")

    lat = _safe_float(field.Latitude)
    lon = _safe_float(field.Longitude)
    boundary = _parse_boundary(field.BoundaryGeoJSON)

    soil_rows = (
        db.query(models.FieldSoilSample)
        .filter(models.FieldSoilSample.FieldID == field_id)
        .order_by(desc(models.FieldSoilSample.SampleDate))
        .all()
    )
    soil_samples = [_ser_soil(r) for r in soil_rows]
    located_samples = [s for s in soil_samples if s.get("location_status") == "located"]
    unlocated_samples = [s for s in soil_samples if s.get("location_status") == "unlocated"]

    scout_rows = (
        db.query(models.FieldScout)
        .filter(models.FieldScout.FieldID == field_id)
        .order_by(desc(models.FieldScout.ObservedAt))
        .limit(200)
        .all()
    )
    scouts = [_ser_scout(r) for r in scout_rows]

    profile = _load_profile(db, field_id)

    requested_year = year
    if requested_year is None:
        requested_year = current_year
    effective_year = int(requested_year)
    allow_field_record = effective_year == current_year
    is_historical = effective_year != current_year

    # Year-aware terrain texture: do not advertise current imagery for past seasons.
    # CROP_MONITOR_URL is often this same process (/cm). Sync requests on the
    # event loop deadlock uvicorn — always offload HTTP to a worker thread.
    season_arg = effective_year if is_historical else None

    async def _empty_weather():
        return {"available": False}

    weather_task = (
        asyncio.to_thread(_fetch_weather, lat, lon, weather_days)
        if lat is not None and lon is not None
        else _empty_weather()
    )
    terrain, analysis_remote, weather, water_use = await asyncio.gather(
        asyncio.to_thread(_fetch_terrain_meta, field_id, grid, season_arg, field),
        asyncio.to_thread(_fetch_latest_analysis_remote, field_id),
        weather_task,
        asyncio.to_thread(_fetch_water_use, field_id),
    )
    # Prefer terrain-resolved boundary if field record lacks one
    if not boundary and terrain.get("boundary"):
        boundary = _parse_boundary(terrain.get("boundary"))

    analysis = (
        analysis_remote
        if analysis_remote.get("available")
        else _fetch_latest_analysis_local(field_id, db)
    )
    detection = await _fetch_crop_detection(lat, lon, db=db, field_id=field_id, boundary=boundary)
    rotation_history = _rotation_history(db, field_id)
    decisions = _load_crop_decisions(db, field_id)

    cdl_year = _cdl_candidate_for_season(
        detection, effective_year, current_year=current_year
    )
    rotation_year = _rotation_for_year(rotation_history, effective_year)
    decision = _load_crop_decision(db, field_id, effective_year)
    crop_resolved = _resolve_crop_source(
        decision=decision,
        rotation=rotation_year,
        field_crop=field.CropType if allow_field_record else None,
        cdl=cdl_year,
        allow_field_record=allow_field_record,
    )

    planting_for_growth = field.PlantingDate
    if rotation_year and rotation_year.get("planting_date"):
        try:
            planting_for_growth = date.fromisoformat(rotation_year["planting_date"])
        except (TypeError, ValueError):
            pass

    irrigation = _irrigation_summary(
        crop_resolved["crop_type"],
        weather,
        water_use=water_use,
        applied_irrig=_fetch_irrigation_applied_mm(db, field_id, weather_days),
        precip_log=_fetch_precip_logged_mm(db, field_id, weather_days),
    )
    probe = _fetch_field_moisture_probe(db, field_id)
    soil_moisture = _classify_soil_moisture(irrigation, profile, soil_samples, probe=probe)
    fertility = _fertility_from_samples(located_samples)
    infiltration = _infiltration_from_detection(detection)
    growth = _estimate_growth_stage(crop_resolved["crop_type"], planting_for_growth)
    vegetation = _vegetation_from_terrain(field_id, grid, terrain)
    if is_historical:
        # Current-season vegetation grids must not densify historical canopies.
        vegetation = {
            **vegetation,
            "available": False,
            "year_matched": False,
            "assets": {
                "ndvi_json": None,
                "ndwi_json": None,
                "ndvi_png": None,
                "ndwi_png": None,
            },
            "note": (
                f"Historical season {effective_year}: current NDVI/NDWI grids are withheld "
                "so today's vegetation is not implied for a past season."
            ),
            "limitations": list(vegetation.get("limitations") or []) + [
                "Historical twin canopy uses crop/source for that year, not current NDVI density.",
            ],
        }
    soil_cutaway = _build_soil_cutaway(profile, soil_samples, detection)
    timeline = _build_timeline(
        rotation_history=rotation_history,
        detection=detection,
        decisions=decisions,
        analysis=analysis,
        current_year=current_year,
    )

    origin = _local_origin(boundary, lat, lon)
    if terrain.get("centroid"):
        c = terrain["centroid"]
        if c.get("longitude") is not None and c.get("latitude") is not None:
            origin = {
                "longitude": c["longitude"],
                "latitude": c["latitude"],
                "crs": "local-meters-from-wgs84",
            }

    availability = {
        "boundary": bool(boundary),
        "terrain": bool(terrain.get("available")),
        "dem": bool(terrain.get("available")),
        "texture": bool(
            (terrain.get("texture") or {}).get("available")
            and (terrain.get("texture") or {}).get("year_matched", True)
            and bool((terrain.get("assets") or {}).get("texture"))
        ),
        "vegetation_grid": bool(vegetation.get("available")),
        "vegetation_fresh": vegetation.get("freshness") == "fresh",
        "profile": bool(profile.get("available")),
        "soil_samples": len(soil_samples) > 0,
        "soil_samples_located": len(located_samples) > 0,
        "soil_grids": bool(detection.get("soil_layers")),
        "fertility_lab": bool(fertility.get("available")),
        "moisture_probe": bool(probe),
        "crop_history": bool(detection.get("history") or rotation_history),
        "scouts": len(scouts) > 0,
        "weather": bool(weather.get("available")),
        "analysis": bool(analysis.get("available")),
        "water_use": bool(water_use.get("available")),
        "irrigation_events": bool((irrigation.get("applied_irrig_mm") or 0) > 0),
        "precip_gauge": irrigation.get("precip_source") == "field_gauge",
        "screening_dem": str(terrain.get("source") or "").lower() in (
            "screening_local", "open_meteo", "open_meteo_elevation", "screening_bowl",
        ) or "screening" in str(terrain.get("source") or "").lower(),
    }

    planting_date_str = str(field.PlantingDate) if field.PlantingDate else None
    if rotation_year and rotation_year.get("planting_date"):
        planting_date_str = rotation_year["planting_date"]

    return {
        "contract_version": TWIN_CONTRACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "selection": {
            "requested_year": year,
            "effective_year": effective_year,
            "is_historical": effective_year != current_year,
            "india_season": _india_season(),
        },
        "field": {
            "field_id": field.FieldID,
            "business_id": business_id,
            "name": field.Name,
            "address": field.Address,
            "latitude": lat,
            "longitude": lon,
            "field_size_hectares": _safe_float(field.FieldSizeHectares),
            "crop_type": field.CropType,
            "planting_date": str(field.PlantingDate) if field.PlantingDate else None,
            "boundary": boundary,
            "provenance": "observed",
            "confidence": "high",
        },
        "local_origin": origin,
        "crop": {
            "crop_type": crop_resolved["crop_type"],
            "recorded_crop_type": crop_resolved["recorded_crop_type"],
            "detected_crop_type": crop_resolved["detected_crop_type"],
            "detected_year": crop_resolved["detected_year"],
            "crop_key": crop_resolved["crop_key"],
            "selected_source": crop_resolved["selected_source"],
            "confirmed": crop_resolved["confirmed"],
            "candidates": crop_resolved["candidates"],
            "planting_date": planting_date_str,
            "growth": growth,
            "asset_hint": f"{crop_resolved['crop_key']}_stalk",
            "validation": crop_resolved["validation"],
        },
        "timeline": timeline,
        "crop_history": {
            "available": bool(detection.get("history") or rotation_history),
            "provenance": "derived" if detection.get("history") else ("recorded" if rotation_history else "none"),
            "confidence": "medium" if detection.get("history") or rotation_history else "none",
            "cdl_years": detection.get("history") or [],
            "rotation_years": rotation_history,
            "note": detection.get("note") or (
                "Grower-entered rotation history only — CDL was unavailable."
                if rotation_history else "No crop history available."
            ),
            "limitations": detection.get("limitations") or [],
            "cache": detection.get("cache") or {"hit": False},
        },
        "soil_moisture": soil_moisture,
        "fertility": fertility,
        "infiltration": infiltration,
        "profile": profile,
        "soil_cutaway": soil_cutaway,
        "soil_samples": {
            "available": len(soil_samples) > 0,
            "count": len(soil_samples),
            "located_count": len(located_samples),
            "unlocated_count": len(unlocated_samples),
            "provenance": "observed",
            "confidence": "high" if soil_samples else "none",
            "samples": soil_samples,
            "unlocated_samples": unlocated_samples,
            "note": (
                f"{len(unlocated_samples)} sample(s) lack coordinates and are listed only — "
                "not pinned on the twin."
                if unlocated_samples else None
            ),
        },
        "scouts": {
            "available": len(scouts) > 0,
            "count": len(scouts),
            "provenance": "observed",
            "confidence": "high" if scouts else "none",
            "observations": scouts,
        },
        "weather": weather,
        "irrigation": irrigation,
        "analysis": analysis,
        "vegetation": vegetation,
        "water_use": water_use,
        "terrain": terrain,
        "water_risk": {
            "available": bool(
                (terrain.get("assets") or {}).get("wetness_risk")
                or terrain.get("available")
            ),
            "provenance": "derived",
            "confidence": "medium" if terrain.get("available") else "low",
            "overlay_url": (terrain.get("assets") or {}).get("wetness_risk"),
            "note": "Relative topographic wetness risk from DEM; not a flood forecast.",
        },
        "availability": availability,
        "rendering_hints": {
            "preferred_grid": grid,
            "quality_presets": {
                "high": {"grid": min(128, grid), "plant_spacing_m": 1.5, "max_instances": 18000},
                "medium": {"grid": min(96, grid), "plant_spacing_m": 2.0, "max_instances": 12000},
                "low": {"grid": min(64, grid), "plant_spacing_m": 3.0, "max_instances": 5000},
            },
            "exaggeration_default": 2.5,
            "canopy": {
                "geometry": "illustrative",
                "driven_by": "spatial_ndvi_when_available",
                "crop_source": crop_resolved["selected_source"],
                "instance_label": "visual samples",
                "note": (
                    "Procedural crop-stand samples are for readability — not a plant census. "
                    "Modeled height is not an observed plant stature measurement."
                ),
            },
            "underground": {
                "driven_by": "soilgrids_and_measured_samples",
                "note": soil_cutaway.get("note"),
            },
            "labels": {
                "observed": "Measured / recorded on this field",
                "derived": "Computed from satellite, DEM, SoilGrids, or weather services",
                "modeled": "Illustrative estimate — not a field measurement",
                "recorded": "Taken from the field record; not independently validated here",
            },
        },
    }


@router.get("/fields/{field_id}/precip-logs")
def list_precip_logs(
    field_id: int,
    days: int = 30,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """List farmer / gauge precip logs for a field (millimetres)."""
    business_id = _verify_field_access(db, user.PeopleID, field_id)
    _ensure_precip_log_table(db)
    days = max(1, min(int(days or 30), 365))
    try:
        rows = db.execute(text("""
            SELECT LogID, FieldID, BusinessID, ObservedAt,
                   COALESCE(DepthMm, DepthIn) AS DepthMmOut, Source, Notes, CreatedAt
            FROM FieldPrecipLog
            WHERE FieldID = :fid AND BusinessID = :bid
              AND ObservedAt >= DATEADD(day, -:days, GETDATE())
            ORDER BY ObservedAt DESC
        """), {"fid": field_id, "bid": business_id, "days": days}).fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"precip_log_query_failed: {e}") from e
    return [
        {
            "log_id": r[0],
            "field_id": r[1],
            "business_id": r[2],
            "observed_at": r[3].isoformat() + "Z" if r[3] else None,
            "depth_mm": float(r[4]) if r[4] is not None else None,
            "source": r[5],
            "notes": r[6],
            "created_at": r[7].isoformat() + "Z" if r[7] else None,
            "units": "mm",
            "provenance": "observed",
        }
        for r in rows
    ]


class PrecipLogIn(BaseModel):
    depth_mm: float = Field(..., gt=0, le=500, description="Rain depth in millimetres")
    observed_at: Optional[datetime] = None
    source: str = "gauge"
    notes: Optional[str] = None


@router.post("/fields/{field_id}/precip-logs")
def create_precip_log(
    field_id: int,
    body: PrecipLogIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Log a rain-gauge / farmer precip reading (mm) for water-balance accuracy."""
    business_id = _verify_field_access(db, user.PeopleID, field_id)
    _ensure_precip_log_table(db)
    observed = body.observed_at or datetime.now(timezone.utc).replace(tzinfo=None)
    if observed.tzinfo is not None:
        observed = observed.astimezone(timezone.utc).replace(tzinfo=None)
    try:
        db.execute(text("""
            INSERT INTO FieldPrecipLog (FieldID, BusinessID, ObservedAt, DepthIn, DepthMm, Source, Notes, CreatedByPeopleID)
            VALUES (:fid, :bid, :obs, :depth, :depth, :src, :notes, :pid)
        """), {
            "fid": field_id,
            "bid": business_id,
            "obs": observed,
            "depth": float(body.depth_mm),
            "src": (body.source or "gauge")[:40],
            "notes": (body.notes or None),
            "pid": getattr(user, "PeopleID", None),
        })
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"precip_log_insert_failed: {e}") from e
    return {"ok": True, "field_id": field_id, "depth_mm": float(body.depth_mm), "units": "mm"}


@router.post("/fields/{field_id}/crop-resolution")
async def post_crop_resolution(
    field_id: int,
    body: CropResolutionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Persist grower confirmation of which crop source the twin should use for a season."""
    business_id = _verify_field_access(db, user.PeopleID, field_id)
    field = (
        db.query(models.Field)
        .filter(models.Field.FieldID == field_id, models.Field.DeletedAt.is_(None))
        .first()
    )
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")

    rotation_history = _rotation_history(db, field_id)
    season_year = int(body.season_year)
    current_year = date.today().year
    allow_field_record = season_year == current_year
    rotation = _rotation_for_year(rotation_history, season_year)

    current_recorded = None
    if rotation and rotation.get("crop"):
        current_recorded = rotation["crop"]
    elif allow_field_record and field.CropType:
        current_recorded = field.CropType

    if body.expected_recorded_crop is not None:
        if _crop_key(body.expected_recorded_crop) != _crop_key(current_recorded):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "stale_recorded_crop",
                    "message": "Recorded crop changed since this confirmation was opened.",
                    "current_recorded_crop": current_recorded,
                },
            )

    if body.choice == "crop_rotation":
        if not rotation or not rotation.get("crop"):
            raise HTTPException(status_code=400, detail="No rotation crop for that season year.")
        selected_crop = rotation["crop"]
        selected_source = "crop_rotation"
    elif body.choice == "field_record":
        if not allow_field_record or not field.CropType:
            raise HTTPException(status_code=400, detail="Field record crop is only valid for the current year.")
        selected_crop = field.CropType
        selected_source = "field_record"
    else:
        raise HTTPException(status_code=400, detail="Unsupported crop source.")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = _load_crop_decision(db, field_id, season_year)
    if row is None:
        row = models.FieldCropSourceDecision(
            FieldID=field_id,
            BusinessID=business_id,
            SeasonYear=season_year,
        )
        db.add(row)
    row.BusinessID = business_id
    row.SelectedSource = selected_source
    row.SelectedCrop = selected_crop
    row.RecordedCropAtDecision = current_recorded
    row.DetectedCropAtDecision = None
    row.CDLCode = None
    row.DecidedByPeopleID = user.PeopleID
    row.DecidedAt = now
    db.commit()
    db.refresh(row)

    return {
        "field_id": field_id,
        "season_year": season_year,
        "selected_source": selected_source,
        "selected_crop": selected_crop,
        "selected_crop_key": _crop_key(selected_crop),
        "confirmed": True,
        "decided_at": row.DecidedAt.isoformat() + "Z" if row.DecidedAt else None,
        "decided_by_people_id": user.PeopleID,
    }
