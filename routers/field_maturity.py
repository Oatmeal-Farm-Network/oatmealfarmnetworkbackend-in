"""
Maturity Engine — predicts the peak-antioxidant harvest day for a field
based on real lab/handheld ripeness samples (Brix, anthocyanin, firmness)
and per-field heat-unit accumulation.

Design rules (per product brief):
  • Never invent a date when there is no calibration data.
  • Show the user what the prediction is built from and how confident it is.
  • Work back from the buyer's shelf-target date when one is set.

Quality > convenience: predictions are skipped (status='no_data') unless we
have at least one real sample. With one sample we extrapolate using a typical
plateau value but mark confidence low. With two or more we fit a linear or
logistic trend to the actual samples.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, validator
from sqlalchemy import desc
from sqlalchemy.orm import Session

import models
from database import get_db
from external_apis import (
    nasa_power_summary,
    nominatim_geocode,
    nominatim_reverse_state,
    osrm_route_miles,
    usda_nass_crop_progress,
)

# Crop-monitor backend hosts the Sentinel-2 NDRE pipeline. NDRE rises with
# anthocyanin accumulation in maturing fruit so we surface it as a free
# satellite proxy to corroborate field samples.
import os as _os
_CROP_MONITOR_URL = _os.getenv(
    "CROP_MONITOR_URL",
    "https://oatmealfarmnetworkcropmonitorbackend-git-802455386518.us-central1.run.app",
).rstrip("/")


router = APIRouter(prefix="/api", tags=["maturity"])


# ───────────────────────────────────────────────────────────────────────────
# Cultivar phenology — a *reference table*, not a prediction.
#
# Each row is the published mean Brix-at-commercial-ripeness and typical
# anthocyanin-at-peak for that cultivar. We use these as ASYMPTOTES against
# which we measure how far a sample is from ripe — never as the prediction
# itself. Sources: USDA, university extension services. Conservative
# midpoints; real-world values vary by site, season, and management.
# ───────────────────────────────────────────────────────────────────────────
CULTIVAR_REFERENCE = {
    # crop_keyword, cultivar_keyword (both lowered, substring match)
    # → { brix_ripe, anthocyanin_peak_mg_g, base_temp_f, gdd_to_first_ripe }
    "blueberry": {
        "brix_ripe": 12.0,
        "anthocyanin_peak_mg_g": 2.5,
        "firmness_ripe_kgf": 1.8,
        "base_temp_f": 45,
    },
    "strawberry": {
        "brix_ripe": 8.5,
        "anthocyanin_peak_mg_g": 0.6,
        "firmness_ripe_kgf": 0.6,
        "base_temp_f": 50,
    },
    "raspberry": {
        "brix_ripe": 11.0,
        "anthocyanin_peak_mg_g": 1.2,
        "firmness_ripe_kgf": 0.5,
        "base_temp_f": 50,
    },
    "blackberry": {
        "brix_ripe": 10.5,
        "anthocyanin_peak_mg_g": 2.0,
        "firmness_ripe_kgf": 0.7,
        "base_temp_f": 50,
    },
    "grape":      {"brix_ripe": 22.0, "anthocyanin_peak_mg_g": 1.5, "firmness_ripe_kgf": 1.2, "base_temp_f": 50},
    "cherry":     {"brix_ripe": 18.0, "anthocyanin_peak_mg_g": 1.0, "firmness_ripe_kgf": 2.5, "base_temp_f": 41},
}


def _reference_for(crop_type: Optional[str]) -> Optional[dict]:
    if not crop_type:
        return None
    needle = crop_type.lower().strip()
    for key, ref in CULTIVAR_REFERENCE.items():
        if key in needle:
            return ref
    return None


# ───────────────────────────────────────────────────────────────────────────
# Pydantic models
# ───────────────────────────────────────────────────────────────────────────
class MaturitySampleCreate(BaseModel):
    field_id: int
    business_id: int
    sample_date: str
    cultivar: Optional[str] = None
    sample_size: Optional[int] = None
    lab_name: Optional[str] = None
    brix_degrees: Optional[float] = None
    firmness_kgf: Optional[float] = None
    anthocyanin_mg_g: Optional[float] = None
    ph: Optional[float] = None
    titratable_acidity_pct: Optional[float] = None
    color_score_l: Optional[float] = None
    color_score_a: Optional[float] = None
    color_score_b: Optional[float] = None
    dry_matter_pct: Optional[float] = None
    notes: Optional[str] = None
    image_url: Optional[str] = None
    people_id: Optional[int] = None

    @validator(
        "brix_degrees", "firmness_kgf", "anthocyanin_mg_g", "ph",
        "titratable_acidity_pct", "color_score_l", "color_score_a",
        "color_score_b", "dry_matter_pct",
        pre=True,
    )
    def empty_to_none(cls, v):
        if v == "" or v is None:
            return None
        return v


class HarvestTargetUpsert(BaseModel):
    field_id: int
    business_id: int
    destination_label: Optional[str] = None
    destination_miles: Optional[float] = None
    receiving_lag_days: Optional[int] = None
    shelf_target_date: Optional[str] = None
    notes: Optional[str] = None
    # Optional: when set, the server geocodes the address and OSRM-routes
    # from the field's GPS to fill destination_miles automatically.
    destination_address: Optional[str] = None


# ───────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────
def _serialize_sample(s: models.FieldMaturitySample) -> dict:
    def _f(v):
        return float(v) if v is not None else None
    return {
        "sample_id":             s.SampleID,
        "field_id":              s.FieldID,
        "business_id":           s.BusinessID,
        "sample_date":           str(s.SampleDate) if s.SampleDate else None,
        "cultivar":              s.Cultivar,
        "sample_size":           s.SampleSize,
        "lab_name":              s.LabName,
        "brix_degrees":          _f(s.BrixDegrees),
        "firmness_kgf":          _f(s.FirmnessKgF),
        "anthocyanin_mg_g":      _f(s.AnthocyaninMgG),
        "ph":                    _f(s.PH),
        "titratable_acidity_pct": _f(s.TitratableAcidityPct),
        "color_score_l":         _f(s.ColorScoreL),
        "color_score_a":         _f(s.ColorScoreA),
        "color_score_b":         _f(s.ColorScoreB),
        "dry_matter_pct":        _f(s.DryMatterPct),
        "notes":                 s.Notes,
        "image_url":             s.ImageUrl,
        "created_at":            s.CreatedAt.isoformat() if s.CreatedAt else None,
    }


def _serialize_target(t: models.FieldHarvestTarget) -> dict:
    return {
        "target_id":           t.TargetID,
        "field_id":            t.FieldID,
        "business_id":         t.BusinessID,
        "destination_label":   t.DestinationLabel,
        "destination_miles":   float(t.DestinationMiles) if t.DestinationMiles is not None else None,
        "receiving_lag_days":  t.ReceivingLagDays,
        "shelf_target_date":   str(t.ShelfTargetDate) if t.ShelfTargetDate else None,
        "notes":               t.Notes,
        "created_at":          t.CreatedAt.isoformat() if t.CreatedAt else None,
    }


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s.split("T")[0])
    except Exception:
        return None


def _transit_days_from_miles(miles: Optional[float]) -> Optional[float]:
    """Real-world reefer trucking: ~500 mi/day with HOS limits + receiving slot.
    Returns whole days rounded up, or None if miles is unset."""
    if miles is None or miles <= 0:
        return None
    return math.ceil(miles / 500.0)


# ───────────────────────────────────────────────────────────────────────────
# Heat-unit data — pulled from the existing /api/fields/{id}/gdd endpoint
# so we use the same Open-Meteo data the rest of the platform trusts.
# ───────────────────────────────────────────────────────────────────────────
_INTERNAL_BASE = "http://127.0.0.1:8000"


def _fetch_recent_gdd(field_id: int, days: int = 365) -> Optional[dict]:
    try:
        r = requests.get(
            f"{_INTERNAL_BASE}/api/fields/{field_id}/gdd",
            params={"days": days},
            timeout=10,
        )
        return r.json() if r.ok else None
    except Exception as e:
        print(f"[maturity] GDD fetch failed: {e}")
        return None


# NDRE rises with chlorophyll/anthocyanin in the fruit canopy as berries
# transition through veraison. We pull the latest few analyses and surface
# the trend — never as the prediction, only as a corroborating signal.
def _satellite_anthocyanin_proxy(field_id: int) -> Optional[dict]:
    try:
        r = requests.get(
            f"{_CROP_MONITOR_URL}/api/fields/{field_id}/analyses",
            params={"limit": 6},
            timeout=10,
        )
        if not r.ok:
            return None
        analyses = (r.json() or {}).get("analyses") or []
    except Exception as e:
        print(f"[maturity] satellite proxy fetch failed: {e}")
        return None

    points = []
    for a in analyses:
        for idx in (a.get("vegetation_indices") or []):
            if (idx.get("index_type") or "").upper() == "NDRE" and idx.get("mean") is not None:
                d = a.get("analysis_date") or a.get("satellite_acquired_at")
                if d:
                    points.append({"date": d, "ndre": float(idx["mean"])})
                break
    if not points:
        return None
    points.sort(key=lambda p: p["date"])
    latest = points[-1]
    earliest = points[0]
    trend = None
    if len(points) >= 2:
        delta = latest["ndre"] - earliest["ndre"]
        if abs(delta) < 0.01:
            trend = "flat"
        elif delta > 0:
            trend = "rising"
        else:
            trend = "falling"
    return {
        "latest_ndre":   round(latest["ndre"], 3),
        "latest_date":   latest["date"],
        "samples_used":  len(points),
        "trend":         trend,
        "first_ndre":    round(earliest["ndre"], 3),
        "first_date":    earliest["date"],
        "source":        "Sentinel-2 (NDRE band, crop-monitor pipeline)",
        "note":          "NDRE is a chlorophyll/canopy proxy — used here only to corroborate fruit samples, not to replace them.",
    }


# ───────────────────────────────────────────────────────────────────────────
# Maturity prediction core
# ───────────────────────────────────────────────────────────────────────────
def _predict_from_samples(
    samples: List[dict],
    reference: Optional[dict],
    today: date,
) -> dict:
    """
    Heart of the engine. Returns a structured prediction or an honest
    'insufficient_data' result.

    Strategy:
      • 0 samples         → status='no_data', no date.
      • 1 sample          → linear extrapolation toward the cultivar reference
                           ripe value, using observed signal level as % progress.
                           Confidence capped at 0.35.
      • 2+ samples        → fit linear regression on (days, brix) (or
                           anthocyanin if brix missing) and project forward to
                           the asymptote. Confidence scales with R² and sample
                           count; capped at 0.85 because biology drifts.
    """
    samples = [s for s in samples if s.get("sample_date")]
    samples.sort(key=lambda s: s["sample_date"])

    if not samples:
        return {
            "status":            "no_data",
            "message":           "No maturity samples logged yet — log your first refractometer "
                                 "or NIR reading to begin prediction.",
            "predicted_peak_date": None,
            "confidence":        0.0,
            "method":            None,
            "sample_count":      0,
        }

    # Pick the metric we have the most data on. Brix is preferred (every
    # refractometer has it); anthocyanin is the gold standard but rare.
    def _series(metric_key: str) -> List[tuple]:
        out = []
        for s in samples:
            v = s.get(metric_key)
            d = _parse_date(s["sample_date"])
            if v is not None and d is not None:
                out.append((d, float(v)))
        return out

    brix    = _series("brix_degrees")
    antho   = _series("anthocyanin_mg_g")
    color_a = _series("color_score_a")

    chosen_metric = None
    series = []
    target = None
    if antho and len(antho) >= 1 and reference:
        chosen_metric, series, target = "anthocyanin_mg_g", antho, reference["anthocyanin_peak_mg_g"]
    elif brix and reference:
        chosen_metric, series, target = "brix_degrees", brix, reference["brix_ripe"]
    elif brix:  # no reference — use the highest sample we have as 'best so far'
        chosen_metric, series, target = "brix_degrees", brix, max(v for _, v in brix) * 1.1
    elif color_a:
        chosen_metric, series, target = "color_score_a", color_a, max(v for _, v in color_a) * 1.1
    else:
        return {
            "status":              "insufficient_metric",
            "message":             "Samples were logged but none include Brix, anthocyanin, or color "
                                   "data — those are the metrics the engine can project.",
            "predicted_peak_date": None,
            "confidence":          0.0,
            "method":              None,
            "sample_count":        len(samples),
        }

    series.sort(key=lambda t: t[0])
    latest_date, latest_val = series[-1]
    progress_pct = max(0.0, min(1.0, latest_val / target)) if target else 0.0

    # ─── Single-sample case ─────────────────────────────────────────────
    if len(series) == 1:
        if not reference:
            return {
                "status":              "single_sample_no_reference",
                "message":             "Only one sample and no cultivar reference for this crop. "
                                       "Log a second sample 4–7 days from now to enable a trend fit.",
                "predicted_peak_date": None,
                "confidence":          0.10,
                "method":              "single_sample",
                "sample_count":        1,
                "metric":              chosen_metric,
                "latest_value":        latest_val,
                "ripe_target":         target,
                "progress_pct":        round(progress_pct * 100, 1),
            }
        # Use a published rough rate: berries gain ~0.6 °Bx / day in the final
        # 2 weeks of ripening. We make this a *floor* on remaining days, not a
        # confident projection.
        gap = max(0.0, target - latest_val)
        days_to_peak = max(1, int(round(gap / 0.6))) if chosen_metric == "brix_degrees" else max(3, int(round(gap * 7)))
        peak = latest_date + timedelta(days=days_to_peak)
        return {
            "status":              "ok",
            "message":             "Projection from a single sample using cultivar reference. "
                                   "Add another sample in 4–7 days to tighten this estimate.",
            "predicted_peak_date": peak.isoformat(),
            "confidence":          0.30,
            "method":              "single_sample_extrapolation",
            "sample_count":        1,
            "metric":              chosen_metric,
            "latest_value":        latest_val,
            "ripe_target":         target,
            "progress_pct":        round(progress_pct * 100, 1),
        }

    # ─── Two-or-more-sample case: linear regression in (day_index, value) ───
    base = series[0][0]
    xs = [(d - base).days for d, _ in series]
    ys = [v for _, v in series]
    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxx = sum(x * x for x in xs)
    denom = n * sxx - sx * sx
    if denom == 0 or target is None:
        return {
            "status":              "flat_trend",
            "message":             "Samples don't show a measurable trend yet — log another in a few days.",
            "predicted_peak_date": None,
            "confidence":          0.15,
            "method":              "linear_regression",
            "sample_count":        n,
            "metric":              chosen_metric,
        }
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n

    # R² for a quick confidence read
    mean_y = sy / n
    ss_tot = sum((y - mean_y) ** 2 for y in ys) or 1e-9
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r2 = max(0.0, 1.0 - ss_res / ss_tot)

    if slope <= 0:
        return {
            "status":              "non_increasing",
            "message":             "Latest samples are flat or decreasing — fruit may already be at "
                                   "or past peak. Inspect a sub-sample today; consider harvesting.",
            "predicted_peak_date": latest_date.isoformat(),
            "confidence":          min(0.6, 0.3 + r2 * 0.3),
            "method":              "linear_regression",
            "sample_count":        n,
            "metric":              chosen_metric,
            "latest_value":        latest_val,
            "ripe_target":         target,
            "progress_pct":        round(progress_pct * 100, 1),
            "slope_per_day":       round(slope, 4),
            "r_squared":           round(r2, 3),
        }

    days_to_peak_from_base = (target - intercept) / slope
    peak_date = base + timedelta(days=max(0, int(round(days_to_peak_from_base))))
    if peak_date < today:
        # Trend says we're past the projected peak — surface that honestly.
        return {
            "status":              "past_projected_peak",
            "message":             "Trend line projects peak was already reached — sample again "
                                   "today to confirm before harvesting.",
            "predicted_peak_date": peak_date.isoformat(),
            "confidence":          min(0.55, 0.25 + r2 * 0.3),
            "method":              "linear_regression",
            "sample_count":        n,
            "metric":              chosen_metric,
            "latest_value":        latest_val,
            "ripe_target":         target,
            "progress_pct":        round(progress_pct * 100, 1),
            "slope_per_day":       round(slope, 4),
            "r_squared":           round(r2, 3),
        }

    confidence = min(0.85, 0.35 + r2 * 0.4 + min(0.10, (n - 2) * 0.025))
    return {
        "status":              "ok",
        "message":             "Trend fit on actual field samples.",
        "predicted_peak_date": peak_date.isoformat(),
        "confidence":          round(confidence, 3),
        "method":              "linear_regression",
        "sample_count":        n,
        "metric":              chosen_metric,
        "latest_value":        latest_val,
        "ripe_target":         target,
        "progress_pct":        round(progress_pct * 100, 1),
        "slope_per_day":       round(slope, 4),
        "r_squared":           round(r2, 3),
    }


def _arrival_plan(
    prediction: dict,
    target: Optional[models.FieldHarvestTarget],
    today: date,
) -> Optional[dict]:
    """
    If the user has set a destination DC, return the "ready-on-shelf" math:
      shelf_date = peak_date + transit_days + receiving_lag_days

    If the user has set a shelf_target_date, return the latest day we can
    pick to hit it. We never invent the lag/miles — both must be user-set.
    """
    peak_str = prediction.get("predicted_peak_date")
    peak = _parse_date(peak_str)
    if not peak or not target:
        return None

    transit_days = _transit_days_from_miles(
        float(target.DestinationMiles) if target.DestinationMiles is not None else None
    )
    lag_days = target.ReceivingLagDays

    plan: dict = {
        "destination_label":  target.DestinationLabel,
        "destination_miles":  float(target.DestinationMiles) if target.DestinationMiles is not None else None,
        "transit_days":       transit_days,
        "receiving_lag_days": lag_days,
        "shelf_target_date":  str(target.ShelfTargetDate) if target.ShelfTargetDate else None,
    }

    if transit_days is None or lag_days is None:
        plan["status"] = "incomplete_destination"
        plan["message"] = "Set destination distance and DC receiving lag to compute a shelf-arrival date."
        return plan

    total_offset = int(transit_days) + int(lag_days)
    projected_shelf = peak + timedelta(days=total_offset)
    plan["projected_shelf_date"] = projected_shelf.isoformat()

    if target.ShelfTargetDate:
        latest_pick = target.ShelfTargetDate - timedelta(days=total_offset)
        plan["latest_pick_date"] = latest_pick.isoformat()
        delta_days = (latest_pick - peak).days
        plan["pick_vs_peak_days"] = delta_days
        if delta_days >= 2:
            plan["alignment"] = "ahead_of_peak"
            plan["alignment_message"] = (
                f"Shelf target requires picking ~{delta_days} day(s) before peak — "
                "consider an earlier-ripening field for this PO, or shift the buyer."
            )
        elif delta_days <= -2:
            plan["alignment"] = "after_peak"
            plan["alignment_message"] = (
                f"Shelf target lands ~{-delta_days} day(s) after projected peak — "
                "fruit risks shipping past the antioxidant peak."
            )
        else:
            plan["alignment"] = "on_target"
            plan["alignment_message"] = "Pick window aligns with projected peak — good match."

    plan["status"] = "ok"
    return plan


# ───────────────────────────────────────────────────────────────────────────
# Endpoints
# ───────────────────────────────────────────────────────────────────────────
@router.get("/fields/{field_id}/maturity")
def get_field_maturity(field_id: int, db: Session = Depends(get_db)):
    field = db.query(models.Field).filter(models.Field.FieldID == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")

    samples_q = (
        db.query(models.FieldMaturitySample)
        .filter(models.FieldMaturitySample.FieldID == field_id)
        .order_by(models.FieldMaturitySample.SampleDate.asc())
        .all()
    )
    samples = [_serialize_sample(s) for s in samples_q]

    target = (
        db.query(models.FieldHarvestTarget)
        .filter(models.FieldHarvestTarget.FieldID == field_id)
        .order_by(desc(models.FieldHarvestTarget.UpdatedAt))
        .first()
    )

    reference = _reference_for(field.CropType)
    today = date.today()
    prediction = _predict_from_samples(samples, reference, today)
    arrival = _arrival_plan(prediction, target, today)

    # Heat-unit context — only included when GDD endpoint actually returns data.
    gdd = _fetch_recent_gdd(field_id, days=120)
    heat_units = None
    if gdd and isinstance(gdd, dict) and gdd.get("total_gdd") is not None:
        heat_units = {
            "total_gdd_period_days": 120,
            "total_gdd":            gdd.get("total_gdd"),
            "base_temp_f":          gdd.get("base_temp_f"),
        }

    # Free public-API context — each block returns None on failure so the UI
    # gracefully omits it without breaking the page.
    lat = float(field.Latitude)  if field.Latitude  is not None else None
    lon = float(field.Longitude) if field.Longitude is not None else None

    light_context = nasa_power_summary(lat, lon, days=30) if (lat is not None and lon is not None) else None

    regional_progress = None
    if lat is not None and lon is not None:
        state = nominatim_reverse_state(lat, lon)
        if state and field.CropType:
            regional_progress = usda_nass_crop_progress(state, field.CropType)

    satellite_proxy = _satellite_anthocyanin_proxy(field_id)

    return {
        "field_id":   field_id,
        "field_name": field.Name,
        "crop_type":  field.CropType,
        "cultivar_reference": reference,    # null = no published reference for this crop
        "samples":    samples,
        "target":     _serialize_target(target) if target else None,
        "prediction": prediction,
        "arrival":    arrival,
        "heat_units": heat_units,
        "light_context":             light_context,        # NASA POWER (PAR / diurnal / dew)
        "regional_progress":         regional_progress,    # USDA NASS state-level progress
        "satellite_anthocyanin_proxy": satellite_proxy,    # NDRE from Sentinel-2 pipeline
        "as_of":      today.isoformat(),
    }


@router.post("/fields/{field_id}/maturity/samples")
def add_maturity_sample(
    field_id: int,
    payload: MaturitySampleCreate,
    db: Session = Depends(get_db),
):
    field = db.query(models.Field).filter(models.Field.FieldID == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    if payload.field_id != field_id:
        raise HTTPException(status_code=400, detail="field_id mismatch between path and body")

    sample_date = _parse_date(payload.sample_date) or date.today()
    now = datetime.utcnow()
    row = models.FieldMaturitySample(
        FieldID=             field_id,
        BusinessID=          payload.business_id,
        PeopleID=            payload.people_id,
        SampleDate=          sample_date,
        Cultivar=            payload.cultivar,
        SampleSize=          payload.sample_size,
        LabName=             payload.lab_name,
        BrixDegrees=         payload.brix_degrees,
        FirmnessKgF=         payload.firmness_kgf,
        AnthocyaninMgG=      payload.anthocyanin_mg_g,
        PH=                  payload.ph,
        TitratableAcidityPct=payload.titratable_acidity_pct,
        ColorScoreL=         payload.color_score_l,
        ColorScoreA=         payload.color_score_a,
        ColorScoreB=         payload.color_score_b,
        DryMatterPct=        payload.dry_matter_pct,
        Notes=               payload.notes,
        ImageUrl=            payload.image_url,
        CreatedAt=           now,
        UpdatedAt=           now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_sample(row)


@router.delete("/fields/{field_id}/maturity/samples/{sample_id}")
def delete_maturity_sample(field_id: int, sample_id: int, db: Session = Depends(get_db)):
    row = (
        db.query(models.FieldMaturitySample)
        .filter(
            models.FieldMaturitySample.SampleID == sample_id,
            models.FieldMaturitySample.FieldID == field_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Sample not found")
    db.delete(row)
    db.commit()
    return {"deleted": sample_id}


@router.put("/fields/{field_id}/maturity/target")
def upsert_harvest_target(
    field_id: int,
    payload: HarvestTargetUpsert,
    db: Session = Depends(get_db),
):
    field = db.query(models.Field).filter(models.Field.FieldID == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")

    # Auto-resolve miles from address when the user supplied one and the
    # field has a GPS pin. We never overwrite an explicit miles entry.
    resolved_miles = payload.destination_miles
    resolved_label = payload.destination_label
    address_lookup: Optional[dict] = None
    if (
        payload.destination_address
        and payload.destination_address.strip()
        and field.Latitude is not None
        and field.Longitude is not None
    ):
        geo = nominatim_geocode(payload.destination_address.strip())
        if geo:
            dest_lat, dest_lon, display_name = geo
            miles = osrm_route_miles(
                float(field.Latitude), float(field.Longitude),
                dest_lat, dest_lon,
            )
            address_lookup = {
                "query":         payload.destination_address,
                "display_name":  display_name,
                "dest_lat":      dest_lat,
                "dest_lon":      dest_lon,
                "miles":         miles,
            }
            if resolved_miles is None and miles is not None:
                resolved_miles = miles
            if not resolved_label:
                resolved_label = display_name

    existing = (
        db.query(models.FieldHarvestTarget)
        .filter(models.FieldHarvestTarget.FieldID == field_id)
        .order_by(desc(models.FieldHarvestTarget.UpdatedAt))
        .first()
    )
    now = datetime.utcnow()
    shelf_target = _parse_date(payload.shelf_target_date)

    if existing:
        existing.DestinationLabel = resolved_label
        existing.DestinationMiles = resolved_miles
        existing.ReceivingLagDays = payload.receiving_lag_days
        existing.ShelfTargetDate  = shelf_target
        existing.Notes            = payload.notes
        existing.UpdatedAt        = now
        db.commit()
        db.refresh(existing)
        out = _serialize_target(existing)
        if address_lookup:
            out["address_lookup"] = address_lookup
        return out

    row = models.FieldHarvestTarget(
        FieldID=          field_id,
        BusinessID=       payload.business_id,
        DestinationLabel= resolved_label,
        DestinationMiles= resolved_miles,
        ReceivingLagDays= payload.receiving_lag_days,
        ShelfTargetDate=  shelf_target,
        Notes=            payload.notes,
        CreatedAt=        now,
        UpdatedAt=        now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    out = _serialize_target(row)
    if address_lookup:
        out["address_lookup"] = address_lookup
    return out
