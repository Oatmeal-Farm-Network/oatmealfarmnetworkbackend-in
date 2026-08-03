"""
Field Assessment Report — Saige's agricultural-consultant-style write-up.

Aggregates everything we know about a field (basic info, climate forecast,
soil samples, maturity readings, scouting/notes, activity log, rotation
history, regional progress, NASA POWER context) and asks the LLM to render
a structured consultant report: where the field stands today, what to do
about the current crop (treatment, harvest timing, burn-down, etc.), and —
when nothing is planted — what to plant next given the location, climate,
and time of year.

Design rules:
  • Every section is grounded in real data we already collected. The prompt
    forbids inventing facts and tells the model to call out blind spots.
  • Returns valid JSON the frontend can render section-by-section and that
    prints cleanly.
  • Never blocks on a single missing data source — each block degrades to
    `null` and the prompt says so.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

import models
from database import get_db
from external_apis import (
    nasa_power_summary,
    nominatim_reverse_state,
    usda_nass_crop_progress,
)
# NOTE: saige.llm initializes a Gemini/Vertex client at import time and
# raises ValueError if GOOGLE_API_KEY/GOOGLE_CLOUD_PROJECT isn't set. That
# would crash the whole backend at startup whenever those env vars aren't
# configured (e.g. on a Cloud Run service that doesn't run Saige). Defer
# the import to call time so the backend starts even without LLM creds —
# the assessment-report endpoint will still 502 if the user hits it without
# creds, which is the correct behavior.

# Reuse the climate forecast helpers so the report uses the same numbers as
# the Climate Forecast tab — never a divergent calculation.
from routers.climate_forecast import (
    _detect_events,
    _fetch_hourly_forecast,
    _profile_for,
    _slice_next_hours,
    _summary_blocks,
)

# Crop-monitor backend hosts the Sentinel-2 vegetation-index pipeline.
_CROP_MONITOR_URL = os.getenv(
    "CROP_MONITOR_URL",
    "https://oatmealfarmnetworkcropmonitorbackend-git-802455386518.us-central1.run.app",
).rstrip("/")


router = APIRouter(prefix="/api", tags=["assessment-report"])


# ───────────────────────────────────────────────────────────────────────────
# Data gathering — every helper returns plain JSON-safe dicts/lists, and
# `None` when the underlying source has nothing useful. Nothing in here
# raises; the assessment prompt is explicit about handling missing data.
# ───────────────────────────────────────────────────────────────────────────
def _serialize_field(field: models.Field) -> dict:
    return {
        "field_id":           field.FieldID,
        "name":               field.Name,
        "address":            field.Address,
        "lat":                float(field.Latitude)  if field.Latitude  is not None else None,
        "lon":                float(field.Longitude) if field.Longitude is not None else None,
        "size_hectares":      float(field.FieldSizeHectares) if field.FieldSizeHectares is not None else None,
        "crop_type":          field.CropType,
        "planting_date":      field.PlantingDate.isoformat() if field.PlantingDate else None,
        "field_description":  field.FieldDescription,
        "monitoring_enabled": bool(field.MonitoringEnabled) if field.MonitoringEnabled is not None else None,
    }


def _recent_soil_samples(db: Session, field_id: int, limit: int = 3) -> list:
    rows = (
        db.query(models.FieldSoilSample)
        .filter(models.FieldSoilSample.FieldID == field_id)
        .order_by(desc(models.FieldSoilSample.SampleDate))
        .limit(limit)
        .all()
    )
    return [{
        "sample_date":    r.SampleDate.isoformat() if r.SampleDate else None,
        "label":          r.SampleLabel,
        "depth_cm":       r.Depth_cm,
        "ph":             float(r.pH)            if r.pH            is not None else None,
        "organic_matter": float(r.OrganicMatter) if r.OrganicMatter is not None else None,
        "nitrogen":       float(r.Nitrogen)      if r.Nitrogen      is not None else None,
        "phosphorus":     float(r.Phosphorus)    if r.Phosphorus    is not None else None,
        "potassium":      float(r.Potassium)     if r.Potassium     is not None else None,
        "sulfur":         float(r.Sulfur)        if r.Sulfur        is not None else None,
        "calcium":        float(r.Calcium)       if r.Calcium       is not None else None,
        "magnesium":      float(r.Magnesium)     if r.Magnesium     is not None else None,
        "cec":            float(r.CEC)           if r.CEC           is not None else None,
        "notes":          r.Notes,
    } for r in rows]


def _recent_maturity_samples(db: Session, field_id: int, limit: int = 5) -> list:
    rows = (
        db.query(models.FieldMaturitySample)
        .filter(models.FieldMaturitySample.FieldID == field_id)
        .order_by(desc(models.FieldMaturitySample.SampleDate))
        .limit(limit)
        .all()
    )
    return [{
        "sample_date":      r.SampleDate.isoformat() if r.SampleDate else None,
        "cultivar":         r.Cultivar,
        "brix":             float(r.BrixDegrees)    if r.BrixDegrees    is not None else None,
        "firmness_kgf":     float(r.FirmnessKgF)    if r.FirmnessKgF    is not None else None,
        "anthocyanin_mg_g": float(r.AnthocyaninMgG) if r.AnthocyaninMgG is not None else None,
        "ph":               float(r.PH)             if r.PH             is not None else None,
        "ta_pct":           float(r.TitratableAcidityPct) if r.TitratableAcidityPct is not None else None,
        "dry_matter_pct":   float(r.DryMatterPct)   if r.DryMatterPct   is not None else None,
        "notes":            r.Notes,
    } for r in rows]


def _recent_notes_and_scouting(db: Session, field_id: int, limit: int = 8) -> list:
    notes = (
        db.query(models.FieldNote)
        .filter(models.FieldNote.FieldID == field_id)
        .order_by(desc(models.FieldNote.NoteDate))
        .limit(limit)
        .all()
    )
    scouts = (
        db.query(models.FieldScout)
        .filter(models.FieldScout.FieldID == field_id)
        .order_by(desc(models.FieldScout.ObservedAt))
        .limit(limit)
        .all()
    )
    out = []
    for n in notes:
        out.append({
            "kind":     "note",
            "date":     n.NoteDate.isoformat() if n.NoteDate else None,
            "category": n.Category,
            "title":    n.Title,
            "severity": n.Severity,
            "content":  (n.Content or "")[:400],
        })
    for s in scouts:
        out.append({
            "kind":     "scout",
            "date":     s.ObservedAt.isoformat() if s.ObservedAt else None,
            "category": s.Category,
            "severity": s.Severity,
            "content":  (s.Notes or "")[:400],
        })
    out.sort(key=lambda r: r.get("date") or "", reverse=True)
    return out[:limit]


def _recent_activity(db: Session, field_id: int, limit: int = 10) -> list:
    rows = (
        db.query(models.FieldActivityLog)
        .filter(models.FieldActivityLog.FieldID == field_id)
        .order_by(desc(models.FieldActivityLog.ActivityDate))
        .limit(limit)
        .all()
    )
    return [{
        "date":     r.ActivityDate.isoformat() if r.ActivityDate else None,
        "type":     r.ActivityType,
        "product":  r.Product,
        "rate":     float(r.Rate) if r.Rate is not None else None,
        "unit":     r.RateUnit,
        "operator": r.OperatorName,
        "notes":    (r.Notes or "")[:300],
    } for r in rows]


def _rotation_history(db: Session, field_id: int, limit: int = 6) -> list:
    rows = (
        db.query(models.CropRotationEntry)
        .filter(models.CropRotationEntry.FieldID == field_id)
        .order_by(desc(models.CropRotationEntry.SeasonYear))
        .limit(limit)
        .all()
    )
    return [{
        "season_year":   r.SeasonYear,
        "crop":          r.CropName,
        "variety":       r.Variety,
        "planting_date": r.PlantingDate.isoformat() if r.PlantingDate else None,
        "harvest_date":  r.HarvestDate.isoformat() if r.HarvestDate else None,
        "yield_amount":  float(r.YieldAmount) if r.YieldAmount is not None else None,
        "yield_unit":    r.YieldUnit,
        "is_cover_crop": bool(r.IsCoverCrop) if r.IsCoverCrop is not None else None,
    } for r in rows]


def _active_prescriptions(db: Session, field_id: int, limit: int = 5) -> list:
    rows = (
        db.query(models.FieldPrescription)
        .filter(models.FieldPrescription.FieldID == field_id)
        .order_by(desc(models.FieldPrescription.AnalysisDate))
        .limit(limit)
        .all()
    )
    return [{
        "name":          r.Name,
        "product":       r.Product,
        "unit":          r.Unit,
        "index_key":     r.IndexKey,
        "zone_method":   r.ZoneMethod,
        "num_zones":     r.NumZones,
        "analysis_date": r.AnalysisDate.isoformat() if r.AnalysisDate else None,
    } for r in rows]


def _climate_block(field: models.Field) -> Optional[dict]:
    if field.Latitude is None or field.Longitude is None:
        return None
    payload = _fetch_hourly_forecast(float(field.Latitude), float(field.Longitude))
    if not payload:
        return None
    rows = _slice_next_hours(payload, 168)  # 7-day horizon
    profile = _profile_for(field.CropType)
    events = _detect_events(rows, field.CropType, profile)
    return {
        "summary":       _summary_blocks(rows[:72]),
        "events":        events[:10],   # cap so the prompt stays focused
        "crop_profile":  profile,
        "horizon_hours": 168,
    }


def _light_context(field: models.Field) -> Optional[dict]:
    if field.Latitude is None or field.Longitude is None:
        return None
    return nasa_power_summary(float(field.Latitude), float(field.Longitude), days=30)


def _regional_progress(field: models.Field) -> Optional[dict]:
    if field.Latitude is None or field.Longitude is None:
        return None
    state = nominatim_reverse_state(float(field.Latitude), float(field.Longitude))
    if not state:
        return None
    return usda_nass_crop_progress(state, field.CropType)


# ───────────────────────────────────────────────────────────────────────────
# Satellite vegetation history — pulls NDVI / NDRE / NDMI series from the
# crop-monitor backend and reduces each to {latest, first, trend}.
# ───────────────────────────────────────────────────────────────────────────
_VI_KEYS = ("NDVI", "NDRE", "NDMI")


def _satellite_vegetation_history(field_id: int, limit: int = 12) -> Optional[dict]:
    try:
        r = requests.get(
            f"{_CROP_MONITOR_URL}/api/fields/{field_id}/analyses",
            params={"limit": limit},
            timeout=10,
        )
        if not r.ok:
            return None
        analyses = (r.json() or {}).get("analyses") or []
    except Exception as e:
        print(f"[assessment] satellite history fetch failed: {e}")
        return None
    if not analyses:
        return None

    by_index: dict = {k: [] for k in _VI_KEYS}
    for a in analyses:
        d = a.get("analysis_date") or a.get("satellite_acquired_at")
        if not d:
            continue
        for idx in (a.get("vegetation_indices") or []):
            key = (idx.get("index_type") or "").upper()
            if key in by_index and idx.get("mean") is not None:
                try:
                    by_index[key].append({"date": d, "mean": float(idx["mean"])})
                except (TypeError, ValueError):
                    pass

    def _summarize(points):
        if not points:
            return None
        points = sorted(points, key=lambda p: p["date"])
        first, last = points[0], points[-1]
        delta = last["mean"] - first["mean"]
        if abs(delta) < 0.02:
            trend = "flat"
        elif delta > 0:
            trend = "rising"
        else:
            trend = "falling"
        return {
            "samples":     len(points),
            "first_date":  first["date"],
            "first_value": round(first["mean"], 3),
            "latest_date": last["date"],
            "latest_value": round(last["mean"], 3),
            "delta":        round(delta, 3),
            "trend":        trend,
        }

    out = {k: _summarize(v) for k, v in by_index.items()}
    if not any(out.values()):
        return None
    out["source"] = "Sentinel-2 (crop-monitor pipeline)"
    out["note"]   = (
        "NDVI tracks total green canopy. NDRE is more sensitive to chlorophyll "
        "and late-season N status. NDMI tracks canopy water content / drought stress."
    )
    return out


# ───────────────────────────────────────────────────────────────────────────
# GDD-to-maturity progress — pulls daily Tmax/Tmin from the Open-Meteo
# archive between PlantingDate and today and compares cumulative GDD to a
# typical heat-units-to-maturity reference for the crop.
#
# Numbers below are conservative published midpoints. Real cultivars vary —
# the prompt is told to treat this as an indicator, not a guarantee.
# ───────────────────────────────────────────────────────────────────────────
_GDD_REFERENCE = {
    # crop keyword → (base °F, GDD to maturity)
    "corn":       (50, 2700),
    "maize":      (50, 2700),
    "soybean":    (50, 2500),
    "soy":        (50, 2500),
    "wheat":      (40, 2100),
    "barley":     (40, 1900),
    "oats":       (40, 1900),
    "cotton":     (60, 2400),
    "rice":       (50, 2200),
    "canola":     (41, 2000),
    "sorghum":    (50, 2400),
    "sunflower":  (44, 2300),
    "tomato":     (50, 1400),
    "lettuce":    (40,  800),
    "spinach":    (40,  600),
    "potato":     (45, 1800),
    "alfalfa":    (41, 1100),  # per cutting
    "strawberry": (50,  600),  # bloom→ripe (approx)
    "blueberry":  (45, 1000),  # bloom→ripe
    "raspberry":  (50,  700),
    "grape":      (50, 2000),
}


def _gdd_reference_for(crop_type: Optional[str]):
    if not crop_type:
        return None
    needle = crop_type.lower().strip()
    for key, val in _GDD_REFERENCE.items():
        if key in needle:
            return val
    return None


def _gdd_progress(field: models.Field) -> Optional[dict]:
    if field.Latitude is None or field.Longitude is None:
        return None
    if not field.PlantingDate:
        return None
    ref = _gdd_reference_for(field.CropType)
    if not ref:
        return None
    base_f, gdd_target = ref

    start = field.PlantingDate
    end = date.today()
    if end <= start:
        return None
    days_since = (end - start).days
    # Open-Meteo archive trails real-time by ~5 days; cap end so we don't
    # request rows that don't exist yet.
    archive_end = end - timedelta(days=5)
    if archive_end <= start:
        return None
    try:
        r = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude":         float(field.Latitude),
                "longitude":        float(field.Longitude),
                "start_date":       start.isoformat(),
                "end_date":         archive_end.isoformat(),
                "daily":            "temperature_2m_max,temperature_2m_min",
                "temperature_unit": "fahrenheit",
                "timezone":         "auto",
            },
            timeout=15,
        )
        if not r.ok:
            return None
        daily = r.json().get("daily", {}) or {}
    except Exception as e:
        print(f"[assessment] GDD fetch failed: {e}")
        return None

    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    n = min(len(tmax), len(tmin))
    if n == 0:
        return None
    cumulative = 0.0
    for i in range(n):
        if tmax[i] is None or tmin[i] is None:
            continue
        cumulative += max(0.0, (tmax[i] + tmin[i]) / 2 - base_f)

    pct = round((cumulative / gdd_target) * 100, 1) if gdd_target else None
    # Project remaining calendar days using average daily GDD so far.
    eta = None
    if cumulative > 0 and pct is not None and pct < 100 and n > 0:
        avg_daily = cumulative / n
        if avg_daily > 0:
            remaining_gdd = max(0.0, gdd_target - cumulative)
            days_remaining = int(round(remaining_gdd / avg_daily))
            eta = (end + timedelta(days=days_remaining)).isoformat()
        else:
            eta = None
    elif pct is not None and pct >= 100:
        eta = "already past typical maturity threshold"

    return {
        "crop_type":         field.CropType,
        "base_temp_f":       base_f,
        "gdd_target":        gdd_target,
        "gdd_accumulated":   round(cumulative, 1),
        "percent_complete":  pct,
        "days_since_planting": days_since,
        "estimated_maturity_date": eta,
        "source": "Open-Meteo archive (daily Tmax/Tmin since planting date)",
        "note":   "Reference GDD targets are conservative published midpoints; cultivar and management shift them ±20%.",
    }


# ───────────────────────────────────────────────────────────────────────────
# Prompt — produces a structured JSON document the UI renders & prints.
# ───────────────────────────────────────────────────────────────────────────
_REPORT_SCHEMA_INSTRUCTIONS = """
Return ONLY a JSON object — no prose, no markdown fences — with this shape:

{
  "executive_summary": "<2-4 sentence headline of the field's current state>",
  "current_status": {
    "growth_stage":  "<best inference of the crop's current stage, or 'no active crop'>",
    "overall_health": "<good | fair | poor | unknown>",
    "highlights":   ["<short bullet>", "..."]
  },
  "soil_and_nutrients": {
    "summary":        "<1-3 sentences on soil chemistry & limitations>",
    "concerns":       ["<bullet>", "..."],
    "recommended_amendments": [
      {"product": "<e.g. lime>", "rate": "<e.g. 1 ton/acre>", "reason": "<why>"}
    ]
  },
  "weather_and_climate": {
    "summary":        "<short paragraph synthesizing the next 7 days + 30-day light/temp context>",
    "key_risks":      ["<bullet>", "..."]
  },
  "plant_status_assessment": {
    "summary":        "<paragraph on crop vigor, maturity progress, scouting findings, NDRE trend>",
    "issues_observed":["<bullet>", "..."]
  },
  "treatment_recommendations": [
    {"action": "<imperative, e.g. Apply foliar potassium>", "timing": "<within X days>",
     "reason": "<grounded in the data>", "priority": "high | medium | low"}
  ],
  "harvest_or_termination_guidance": {
    "applies": <true | false>,
    "summary": "<harvest window or burn-down/termination guidance, or 'not applicable: no active crop'>",
    "specific_dates": ["<YYYY-MM-DD>", "..."]
  },
  "next_crop_recommendations": [
    {"crop": "<species>", "variety_hint": "<optional>", "rationale": "<why this fits the site/season>",
     "best_planting_window": "<e.g. mid-May to early June>"}
  ],
  "data_gaps": ["<things we should collect to make the next report sharper>"],
  "confidence_overall": "<high | medium | low>"
}

Rules:
- ALWAYS refer to the field by its given name (the value provided above). NEVER write "Field <number>" or use the database ID in any prose.
- Use ONLY facts from the supplied data. If a field is missing, say so in `data_gaps` instead of guessing.
- Tailor to the lat/lon, crop type, and current calendar date.
- When `satellite_vegetation` is present, weave NDVI/NDRE/NDMI trends into `plant_status_assessment.summary` (e.g. "NDRE has been falling for 3 weeks — possible nitrogen drawdown"). Treat it as a corroborating signal, not gospel.
- When `gdd_progress` is present, cite the % complete and `estimated_maturity_date` in `harvest_or_termination_guidance` (and copy that date into `specific_dates` when the crop is annual). Always note that GDD targets are approximate.
- If the field has an active crop, fill `treatment_recommendations` and `harvest_or_termination_guidance`.
- If no crop is currently planted (or planting_date is far in the past with no recent activity), focus on `next_crop_recommendations` and put `harvest_or_termination_guidance.applies = false`.
- Keep bullets short, action-oriented, and farmer-readable. No fluff.
- Output VALID JSON. No trailing commas.
"""


def _build_prompt(field_block: dict, context: dict) -> str:
    today = date.today().isoformat()
    field_name = field_block.get("name") or f"Field {field_block.get('field_id')}"
    return (
        "You are Saige, an agricultural consultant generating a printable field-assessment report "
        "for the farm operator. Be precise, kind, and grounded in the data provided.\n\n"
        f"Today's date: {today}\n"
        f"Field name (use this verbatim when referring to the field — never call it "
        f"'Field {field_block.get('field_id')}' or by its database ID):\n"
        f"  {field_name}\n\n"
        "FIELD\n"
        f"{json.dumps(field_block, indent=2, default=str)}\n\n"
        "CONTEXT (each block may be null when the source has no usable data)\n"
        f"{json.dumps(context, indent=2, default=str)}\n\n"
        + _REPORT_SCHEMA_INSTRUCTIONS
    )


_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_llm_json(raw: str) -> dict:
    """Strip ``` fences if the model added them, then parse. If it still fails,
    extract the largest {...} block and try once more."""
    cleaned = _JSON_FENCE.sub("", raw or "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            return json.loads(m.group(0))
        raise


# ───────────────────────────────────────────────────────────────────────────
# Persistence helpers
# ───────────────────────────────────────────────────────────────────────────
def _row_to_payload(row: models.FieldAssessmentReport, field_block: dict) -> dict:
    """Shape a stored row the way the UI expects (matches the live-generate
    response so the frontend can render either path identically)."""
    try:
        report = json.loads(row.ReportJSON) if row.ReportJSON else None
    except Exception:
        report = None
    try:
        context = json.loads(row.ContextJSON) if row.ContextJSON else None
    except Exception:
        context = None
    return {
        "report_id":    row.ReportID,
        "field":        field_block,
        "generated_at": (row.GeneratedAt.isoformat() + "Z") if row.GeneratedAt else None,
        "report":       report,
        "raw_text":     row.RawText if report is None else None,
        "context":      context,
    }


def _summary_row(row: models.FieldAssessmentReport) -> dict:
    """Compact entry for the history list."""
    return {
        "report_id":      row.ReportID,
        "generated_at":   (row.GeneratedAt.isoformat() + "Z") if row.GeneratedAt else None,
        "headline":       row.Headline,
        "overall_health": row.OverallHealth,
        "confidence":     row.Confidence,
    }


# ───────────────────────────────────────────────────────────────────────────
# Endpoints
# ───────────────────────────────────────────────────────────────────────────
@router.post("/fields/{field_id}/assessment-report")
def generate_field_assessment_report(
    field_id: int,
    people_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    Generate a fresh Saige-authored consultant report and persist it. Returns
    the same shape as GET /latest.
    """
    field = db.query(models.Field).filter(models.Field.FieldID == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")

    context = {
        "soil_samples":             _recent_soil_samples(db, field_id),
        "maturity_samples":         _recent_maturity_samples(db, field_id),
        "notes_and_scouting":       _recent_notes_and_scouting(db, field_id),
        "activity_log":             _recent_activity(db, field_id),
        "rotation_history":         _rotation_history(db, field_id),
        "active_prescriptions":     _active_prescriptions(db, field_id),
        "climate_forecast":         _climate_block(field),
        "light_context_30d":        _light_context(field),
        "regional_progress":        _regional_progress(field),
        "satellite_vegetation":     _satellite_vegetation_history(field_id),
        "gdd_progress":             _gdd_progress(field),
    }
    field_block = _serialize_field(field)
    prompt = _build_prompt(field_block, context)

    try:
        from saige.llm import llm  # lazy import — see note at top of file
        result = llm.invoke(prompt)
        raw = getattr(result, "content", None) or str(result)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")

    try:
        report = _parse_llm_json(raw)
    except Exception as e:
        # Persist even when JSON parsing fails — RawText is still useful for
        # the audit log and lets the UI show *something*.
        row = models.FieldAssessmentReport(
            FieldID     = field_id,
            BusinessID  = field.BusinessID,
            PeopleID    = people_id,
            GeneratedAt = datetime.utcnow(),
            Headline    = "(parse error — raw text only)",
            OverallHealth = None,
            Confidence    = None,
            ReportJSON  = None,
            RawText     = raw,
            ContextJSON = json.dumps(context, default=str),
        )
        db.add(row); db.commit(); db.refresh(row)
        return {
            "report_id":    row.ReportID,
            "field":        field_block,
            "generated_at": row.GeneratedAt.isoformat() + "Z",
            "report":       None,
            "raw_text":     raw,
            "parse_error":  str(e),
            "context":      context,
        }

    headline = (report.get("executive_summary") or "")[:500]
    cur_status = report.get("current_status") or {}
    row = models.FieldAssessmentReport(
        FieldID       = field_id,
        BusinessID    = field.BusinessID,
        PeopleID      = people_id,
        GeneratedAt   = datetime.utcnow(),
        Headline      = headline or None,
        OverallHealth = (cur_status.get("overall_health") or None),
        Confidence    = (report.get("confidence_overall") or None),
        ReportJSON    = json.dumps(report, default=str),
        RawText       = raw,
        ContextJSON   = json.dumps(context, default=str),
    )
    db.add(row); db.commit(); db.refresh(row)

    return {
        "report_id":    row.ReportID,
        "field":        field_block,
        "generated_at": row.GeneratedAt.isoformat() + "Z",
        "report":       report,
        "context":      context,
    }


@router.get("/fields/{field_id}/assessment-report/latest")
def get_latest_assessment_report(field_id: int, db: Session = Depends(get_db)):
    """Return the most recent stored assessment report for this field, or a
    204-style empty body when none exists yet."""
    field = db.query(models.Field).filter(models.Field.FieldID == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")

    row = (
        db.query(models.FieldAssessmentReport)
        .filter(models.FieldAssessmentReport.FieldID == field_id,
                models.FieldAssessmentReport.DeletedAt.is_(None))
        .order_by(desc(models.FieldAssessmentReport.GeneratedAt))
        .first()
    )
    if not row:
        return {"report_id": None, "field": _serialize_field(field), "report": None}
    return _row_to_payload(row, _serialize_field(field))


@router.get("/fields/{field_id}/assessment-report/history")
def list_assessment_history(field_id: int, limit: int = 25, db: Session = Depends(get_db)):
    """Compact list of past reports for the field. Used by the UI history
    dropdown and by Saige's RAG tool."""
    rows = (
        db.query(models.FieldAssessmentReport)
        .filter(models.FieldAssessmentReport.FieldID == field_id,
                models.FieldAssessmentReport.DeletedAt.is_(None))
        .order_by(desc(models.FieldAssessmentReport.GeneratedAt))
        .limit(max(1, min(limit, 100)))
        .all()
    )
    return {"items": [_summary_row(r) for r in rows]}


@router.get("/fields/{field_id}/assessment-report/{report_id}")
def get_assessment_by_id(field_id: int, report_id: int, db: Session = Depends(get_db)):
    """Return a specific stored assessment by its ID."""
    field = db.query(models.Field).filter(models.Field.FieldID == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    row = (
        db.query(models.FieldAssessmentReport)
        .filter(models.FieldAssessmentReport.ReportID == report_id,
                models.FieldAssessmentReport.FieldID  == field_id,
                models.FieldAssessmentReport.DeletedAt.is_(None))
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return _row_to_payload(row, _serialize_field(field))
