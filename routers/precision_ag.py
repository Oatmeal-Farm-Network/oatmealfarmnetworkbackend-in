from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, text
from database import get_db
from datetime import date, datetime
import json
import os
import uuid
import models
import requests
from pydantic import BaseModel, validator
from typing import Optional
from geo_utils import polygon_area_hectares

router = APIRouter(prefix="/api", tags=["precision-ag"])

# ── FieldProfile table (lazy create) ─────────────────────────────────────────
_field_profile_ready = False

def _ensure_field_profile_table(db: Session):
    global _field_profile_ready
    if _field_profile_ready:
        return
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FieldProfile')
        CREATE TABLE FieldProfile (
            ProfileID        INT IDENTITY(1,1) PRIMARY KEY,
            FieldID          INT NOT NULL,
            BusinessID       INT NOT NULL,
            SoilType         NVARCHAR(100),
            DrainageClass    NVARCHAR(100),
            SlopePercent     DECIMAL(5,2),
            Topography       NVARCHAR(100),
            OrganicMatterPct DECIMAL(5,2),
            PhLevel          DECIMAL(4,2),
            FieldNotes       NVARCHAR(MAX),
            PhotoUrls        NVARCHAR(MAX),
            UpdatedAt        DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()
    _field_profile_ready = True

CROP_MONITOR_URL = os.getenv(
    "CROP_MONITOR_URL",
    "https://oatmealfarmnetworkcropmonitorbackend-git-802455386518.us-central1.run.app"
    if os.getenv("GAE_ENV") or os.getenv("K_SERVICE")
    else "http://127.0.0.1:8002",
)
BIOMASS_GCS_BUCKET = os.getenv("BIOMASS_GCS_BUCKET", "oatmeal-farm-network-images")
BIOMASS_GCS_PREFIX = os.getenv("BIOMASS_GCS_PREFIX", "biomass-uploads")


class FieldCreate(BaseModel):
    business_id: int
    name: str
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    field_size_hectares: Optional[float] = None
    crop_type: Optional[str] = None
    planting_date: Optional[str] = None
    boundary_geojson: Optional[str] = None
    monitoring_interval_days: Optional[int] = 5
    alert_threshold_health: Optional[int] = 50

    @validator('latitude', 'longitude', 'field_size_hectares', pre=True)
    def empty_str_to_none(cls, v):
        if v == '' or v is None:
            return None
        return v

    @validator('planting_date', pre=True)
    def empty_date_to_none(cls, v):
        if v == '' or v is None:
            return None
        return v


@router.get("/fields")
def get_fields(business_id: int, db: Session = Depends(get_db)):
    try:
        # Join each field to its latest row in dbo.Analysis via OUTER APPLY so
        # the dashboard can show the most recent health score without an
        # N+1 fetch per field.
        rows = db.execute(text("""
            SELECT
                F.FieldID, F.BusinessID, F.Name, F.Address,
                F.Latitude, F.Longitude, F.FieldSizeHectares,
                F.CropType, F.PlantingDate, F.BoundaryGeoJSON,
                F.MonitoringEnabled, F.MonitoringIntervalDays, F.AlertThresholdHealth,
                LA.AnalysisDate  AS LatestAnalysisDate,
                LA.HealthScore   AS LatestHealthScore,
                LA.Status        AS LatestStatus
            FROM Field F
            OUTER APPLY (
                SELECT TOP 1 A.AnalysisDate, A.HealthScore, A.Status
                FROM Analysis A
                WHERE A.FieldID = F.FieldID
                ORDER BY A.AnalysisDate DESC
            ) LA
            WHERE F.BusinessID = :bid AND F.DeletedAt IS NULL
            ORDER BY F.Name
        """), {"bid": business_id}).fetchall()

        return [
            {
                "fieldid":                  r.FieldID,
                "id":                       r.FieldID,
                "business_id":              r.BusinessID,
                "name":                     r.Name,
                "address":                  r.Address,
                "latitude":                 float(r.Latitude) if r.Latitude is not None else None,
                "longitude":                float(r.Longitude) if r.Longitude is not None else None,
                "field_size_hectares":      float(r.FieldSizeHectares) if r.FieldSizeHectares is not None else None,
                "crop_type":                r.CropType,
                "planting_date":            str(r.PlantingDate) if r.PlantingDate else None,
                "boundary_geojson":         r.BoundaryGeoJSON,
                "monitoring_enabled":       bool(r.MonitoringEnabled) if r.MonitoringEnabled is not None else True,
                "monitoring_interval_days": r.MonitoringIntervalDays,
                "alert_threshold_health":   r.AlertThresholdHealth,
                "latest_analysis_date":     r.LatestAnalysisDate.isoformat() if r.LatestAnalysisDate else None,
                "latest_health_score":      int(r.LatestHealthScore) if r.LatestHealthScore is not None else None,
                "latest_status":            r.LatestStatus,
            }
            for r in rows
        ]
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fields")
def create_field(field: FieldCreate, db: Session = Depends(get_db)):
    # Address/Latitude/Longitude are NOT NULL columns in dbo.Field — the
    # working add-field flow (Crop Detection) always derives these from a
    # drawn boundary, but guard here too so a bad/direct API call gets a
    # clean 400 instead of a raw SQL IntegrityError.
    if field.latitude is None or field.longitude is None:
        raise HTTPException(status_code=400, detail="latitude and longitude are required")
    if not field.address:
        field.address = field.name

    try:
        planting_date = None
        if field.planting_date:
            try:
                planting_date = date.fromisoformat(field.planting_date)
            except ValueError:
                planting_date = None

        # Derive size from the drawn boundary when one is provided — the
        # polygon is the source of truth, so it overrides any user-entered
        # number. Falls back to the user value when no boundary was drawn.
        computed_size = polygon_area_hectares(field.boundary_geojson)
        size_hectares = computed_size if computed_size is not None else field.field_size_hectares

        new_field = models.Field(
            BusinessID=             field.business_id,
            Name=                   field.name,
            Address=                field.address,
            CropType=               field.crop_type,
            Latitude=               field.latitude,
            Longitude=              field.longitude,
            FieldSizeHectares=      size_hectares,
            PlantingDate=           planting_date,
            BoundaryGeoJSON=        field.boundary_geojson,
            MonitoringIntervalDays= field.monitoring_interval_days,
            AlertThresholdHealth=   field.alert_threshold_health,
            MonitoringEnabled=      1,
            CreatedAt=              datetime.utcnow(),
        )
        db.add(new_field)
        db.commit()
        db.refresh(new_field)
        return {"id": new_field.FieldID, "name": new_field.Name}
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/fields/{field_id}")
def update_field(field_id: int, field: FieldCreate, db: Session = Depends(get_db)):
    try:
        existing = (
            db.query(models.Field)
            .filter(models.Field.FieldID == field_id, models.Field.DeletedAt.is_(None))
            .first()
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Field not found")
        planting_date = None
        if field.planting_date:
            try:
                planting_date = date.fromisoformat(field.planting_date)
            except ValueError:
                planting_date = None
        computed_size = polygon_area_hectares(field.boundary_geojson)
        existing.Name                   = field.name
        existing.Address                = field.address
        existing.CropType               = field.crop_type
        existing.Latitude               = field.latitude
        existing.Longitude              = field.longitude
        existing.FieldSizeHectares      = (
            computed_size if computed_size is not None else field.field_size_hectares
        )
        existing.PlantingDate           = planting_date
        # Only overwrite the saved boundary when the caller actually sent a new
        # one — an empty/omitted value (e.g. the edit form loaded without
        # re-drawing) must never wipe out a previously drawn polygon.
        if field.boundary_geojson:
            existing.BoundaryGeoJSON    = field.boundary_geojson
        existing.MonitoringIntervalDays = field.monitoring_interval_days
        existing.AlertThresholdHealth   = field.alert_threshold_health
        db.commit()
        db.refresh(existing)
        return {"id": existing.FieldID, "name": existing.Name}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/fields/{field_id}")
def delete_field(field_id: int, db: Session = Depends(get_db)):
    try:
        field = (
            db.query(models.Field)
            .filter(models.Field.FieldID == field_id, models.Field.DeletedAt.is_(None))
            .first()
        )
        if not field:
            raise HTTPException(status_code=404, detail="Field not found")
        # Soft delete — permanently deleting the row would cascade-orphan (or
        # foreign-key-fail on) years of Analysis/FieldScout/FieldNote/biomass
        # history tied to this FieldID. get_fields() already filters on
        # DeletedAt, so this is enough to make the field disappear from the UI
        # while keeping the history recoverable/auditable.
        field.DeletedAt = datetime.utcnow()
        db.commit()
        return {"success": True, "deleted_id": field_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class FieldProfileUpsert(BaseModel):
    soil_type:          Optional[str] = None
    drainage_class:     Optional[str] = None
    slope_percent:      Optional[float] = None
    topography:         Optional[str] = None
    organic_matter_pct: Optional[float] = None
    ph_level:           Optional[float] = None
    field_notes:        Optional[str] = None
    photo_urls:         Optional[str] = None


@router.get("/fields/{field_id}/profile")
def get_field_profile(field_id: int, db: Session = Depends(get_db)):
    try:
        _ensure_field_profile_table(db)
        row = db.execute(text("""
            SELECT SoilType, DrainageClass, SlopePercent, Topography,
                   OrganicMatterPct, PhLevel, FieldNotes, PhotoUrls, UpdatedAt
            FROM FieldProfile WHERE FieldID = :fid
        """), {"fid": field_id}).fetchone()
        if not row:
            return {}
        return {
            "soil_type":          row.SoilType,
            "drainage_class":     row.DrainageClass,
            "slope_percent":      float(row.SlopePercent) if row.SlopePercent is not None else None,
            "topography":         row.Topography,
            "organic_matter_pct": float(row.OrganicMatterPct) if row.OrganicMatterPct is not None else None,
            "ph_level":           float(row.PhLevel) if row.PhLevel is not None else None,
            "field_notes":        row.FieldNotes,
            "photo_urls":         row.PhotoUrls,
            "updated_at":         row.UpdatedAt.isoformat() if row.UpdatedAt else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/fields/{field_id}/profile")
def upsert_field_profile(field_id: int, body: FieldProfileUpsert, business_id: int, db: Session = Depends(get_db)):
    try:
        _ensure_field_profile_table(db)
        existing = db.execute(text("SELECT ProfileID FROM FieldProfile WHERE FieldID = :fid"), {"fid": field_id}).fetchone()
        if existing:
            db.execute(text("""
                UPDATE FieldProfile SET
                    SoilType         = :soil_type,
                    DrainageClass    = :drainage_class,
                    SlopePercent     = :slope_percent,
                    Topography       = :topography,
                    OrganicMatterPct = :organic_matter_pct,
                    PhLevel          = :ph_level,
                    FieldNotes       = :field_notes,
                    PhotoUrls        = :photo_urls,
                    UpdatedAt        = GETDATE()
                WHERE FieldID = :fid
            """), {
                "fid":               field_id,
                "soil_type":          body.soil_type,
                "drainage_class":     body.drainage_class,
                "slope_percent":      body.slope_percent,
                "topography":         body.topography,
                "organic_matter_pct": body.organic_matter_pct,
                "ph_level":           body.ph_level,
                "field_notes":        body.field_notes,
                "photo_urls":         body.photo_urls,
            })
        else:
            db.execute(text("""
                INSERT INTO FieldProfile (FieldID, BusinessID, SoilType, DrainageClass, SlopePercent,
                    Topography, OrganicMatterPct, PhLevel, FieldNotes, PhotoUrls)
                VALUES (:fid, :bid, :soil_type, :drainage_class, :slope_percent,
                    :topography, :organic_matter_pct, :ph_level, :field_notes, :photo_urls)
            """), {
                "fid":               field_id,
                "bid":               business_id,
                "soil_type":          body.soil_type,
                "drainage_class":     body.drainage_class,
                "slope_percent":      body.slope_percent,
                "topography":         body.topography,
                "organic_matter_pct": body.organic_matter_pct,
                "ph_level":           body.ph_level,
                "field_notes":        body.field_notes,
                "photo_urls":         body.photo_urls,
            })
        db.commit()
        return {"ok": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/precision-ag/dashboard/summary")
def get_dashboard_summary(business_id: int, db: Session = Depends(get_db)):
    try:
        field_count = (
            db.query(func.count(models.Field.FieldID))
            .filter(models.Field.BusinessID == business_id)
            .scalar() or 0
        )
        return {
            "field_count":    field_count,
            "analysis_count": 0,
            "open_alerts":    0,
            "average_health": None,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ── BIOMASS ANALYSIS ─────────────────────────────────────────────

def _serialize_biomass_row(row: "models.FieldBiomassAnalysis") -> dict:
    return {
        "analysis_id":        row.AnalysisID,
        "field_id":           row.FieldID,
        "source":             row.Source,
        "biomass_kg_per_ha":  float(row.BiomassKgHa) if row.BiomassKgHa is not None else None,
        "confidence":         float(row.Confidence) if row.Confidence is not None else None,
        "image_url":          row.ImageUrl,
        "captured_at":        row.CapturedAt.isoformat() + "Z" if row.CapturedAt else None,
        "model_version":      row.ModelVersion,
        "features":           json.loads(row.FeaturesJSON) if row.FeaturesJSON else None,
        "created_at":         row.CreatedAt.isoformat() + "Z" if row.CreatedAt else None,
    }


def _ndvi_to_biomass(ndvi: float, crop_type: str = None) -> dict:
    """
    Convert NDVI mean to dry-matter biomass estimate.
    Formula: linear ramp from 0 at NDVI=0.1 (bare soil) to 10,000 kg DM/ha at NDVI=1.0.
    Confidence is proportional to how green the canopy is (higher NDVI = more reliable).
    """
    biomass = max(0.0, (ndvi - 0.1) / 0.9 * 10000.0)
    confidence = min(1.0, max(0.1, (ndvi - 0.1) / 0.7))
    return {
        "biomass_kg_per_ha": round(biomass, 1),
        "confidence": round(confidence, 3),
        "model_version": "ndvi-linear-v1",
        "features": {"ndvi": round(ndvi, 4), "formula": "max(0,(ndvi-0.1)/0.9*10000)"},
    }


def _fetch_latest_crop_analysis(field_id: int) -> dict | None:
    """Pull the most recent stored analysis from the crop monitoring backend."""
    try:
        r = requests.get(
            f"{CROP_MONITOR_URL}/api/fields/{field_id}/analyses?limit=1",
            timeout=15,
        )
        if not r.ok:
            return None
        data = r.json()
        analyses = data.get("analyses") or []
        return analyses[0] if analyses else None
    except requests.RequestException:
        return None


def _call_estimator_upload(image_bytes: bytes, filename: str, content_type: str, source: str, field_id: int) -> dict:
    raise HTTPException(status_code=501, detail="Upload-based biomass estimation not yet implemented")


@router.get("/fields/{field_id}/biomass")
def get_biomass(field_id: int, db: Session = Depends(get_db)):
    """Latest satellite + latest upload analysis for a field. Returns empty
    payload (not 500) when the FieldBiomassAnalysis table hasn't been migrated yet."""
    field = (
        db.query(models.Field)
        .filter(models.Field.FieldID == field_id, models.Field.DeletedAt.is_(None))
        .first()
    )
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")

    empty = {"field_id": field_id, "satellite": None, "upload": None, "history": []}
    try:
        def latest(source: str):
            row = (
                db.query(models.FieldBiomassAnalysis)
                .filter(
                    models.FieldBiomassAnalysis.FieldID == field_id,
                    models.FieldBiomassAnalysis.Source == source,
                )
                .order_by(desc(models.FieldBiomassAnalysis.CapturedAt))
                .first()
            )
            return _serialize_biomass_row(row) if row else None

        history = (
            db.query(models.FieldBiomassAnalysis)
            .filter(models.FieldBiomassAnalysis.FieldID == field_id)
            .order_by(desc(models.FieldBiomassAnalysis.CreatedAt))
            .limit(20)
            .all()
        )
        return {
            "field_id":  field_id,
            "satellite": latest("satellite"),
            "upload":    latest("upload"),
            "history":   [_serialize_biomass_row(r) for r in history],
        }
    except Exception as e:
        # Most common cause: FieldBiomassAnalysis table hasn't been created yet.
        # Log and return empty so the UI shows "no analysis yet" instead of an error.
        print(f"[biomass] GET failed, returning empty (table missing?): {e}")
        db.rollback()
        return empty


def _run_satellite_biomass(field_id: int, db: Session) -> "models.FieldBiomassAnalysis":
    """Pull the latest NDVI analysis, convert to biomass, persist, and return the row.
    Shared by the manual-trigger satellite endpoint and the auto-resolver endpoint."""
    field = (
        db.query(models.Field)
        .filter(models.Field.FieldID == field_id, models.Field.DeletedAt.is_(None))
        .first()
    )
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")

    analysis = _fetch_latest_crop_analysis(field_id)
    if not analysis:
        raise HTTPException(
            status_code=503,
            detail="No satellite analysis available yet for this field. "
                   "Run an analysis from the Crop Monitor dashboard first.",
        )

    indices = analysis.get("vegetation_indices") or []
    ndvi_entry = next((i for i in indices if (i.get("index_type") or "").upper() == "NDVI"), None)
    if not ndvi_entry or ndvi_entry.get("mean") is None:
        raise HTTPException(
            status_code=503,
            detail="Latest analysis has no NDVI data. Re-run analysis from Crop Monitor.",
        )

    ndvi_mean = float(ndvi_entry["mean"])
    prediction = _ndvi_to_biomass(ndvi_mean, crop_type=field.CropType)

    try:
        captured = datetime.fromisoformat(
            (analysis.get("satellite_acquired_at") or analysis.get("analysis_date") or "").replace("Z", "")
        )
    except Exception:
        captured = datetime.utcnow()

    image_url = f"{CROP_MONITOR_URL}/api/fields/{field_id}/heatmap/ndvi"

    row = models.FieldBiomassAnalysis(
        FieldID=      field_id,
        BusinessID=   field.BusinessID,
        Source=       "satellite",
        BiomassKgHa=  prediction.get("biomass_kg_per_ha"),
        Confidence=   prediction.get("confidence"),
        ImageUrl=     image_url,
        CapturedAt=   captured,
        ModelVersion= prediction.get("model_version"),
        FeaturesJSON= json.dumps(prediction.get("features") or {}),
        CreatedAt=    datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/fields/{field_id}/biomass/satellite")
def analyze_satellite(field_id: int, db: Session = Depends(get_db)):
    """
    Compute biomass from the latest Sentinel-2 NDVI analysis stored by the
    crop monitoring backend.  No GEE or external ML service required — the
    crop monitoring backend already pulls real satellite data on its own schedule.
    """
    row = _run_satellite_biomass(field_id, db)
    return _serialize_biomass_row(row)


@router.post("/fields/{field_id}/biomass/resolve")
def resolve_biomass(field_id: int, db: Session = Depends(get_db)):
    """
    Improve biomass-estimate confidence by averaging a fresh satellite run
    with up to 4 prior recent satellite runs. Returns the combined estimate
    plus per-sample detail so the caller can show how the average was reached.
    """
    fresh = _run_satellite_biomass(field_id, db)

    samples = (
        db.query(models.FieldBiomassAnalysis)
        .filter(
            models.FieldBiomassAnalysis.FieldID == field_id,
            models.FieldBiomassAnalysis.Source == "satellite",
        )
        .order_by(desc(models.FieldBiomassAnalysis.CapturedAt))
        .limit(5)
        .all()
    )

    biomass_vals   = [float(s.BiomassKgHa) for s in samples if s.BiomassKgHa is not None]
    conf_vals      = [float(s.Confidence)  for s in samples if s.Confidence  is not None]
    avg_biomass    = round(sum(biomass_vals) / len(biomass_vals), 1) if biomass_vals else None
    # Averaging N independent samples reduces noise by ~sqrt(N), so confidence
    # in the combined estimate scales the same way (capped at 0.95).
    if conf_vals:
        n = len(conf_vals)
        boost = min(0.95, (sum(conf_vals) / n) * (n ** 0.5))
        avg_confidence = round(boost, 3)
    else:
        avg_confidence = None

    return {
        "field_id":         field_id,
        "fresh_sample":     _serialize_biomass_row(fresh),
        "samples":          [_serialize_biomass_row(s) for s in samples],
        "n_samples":        len(samples),
        "averaged_biomass_kg_per_ha": avg_biomass,
        "averaged_confidence":        avg_confidence,
    }


@router.post("/fields/{field_id}/biomass/upload")
async def analyze_upload(
    field_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """User-uploaded ground-level image → estimator → stored analysis."""
    field = (
        db.query(models.Field)
        .filter(models.Field.FieldID == field_id, models.Field.DeletedAt.is_(None))
        .first()
    )
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    ext = os.path.splitext(file.filename or "upload.jpg")[1].lower() or ".jpg"
    filename = f"field{field_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"

    image_url = None
    try:
        from google.cloud import storage
        client = storage.Client()
        blob = client.bucket(BIOMASS_GCS_BUCKET).blob(f"{BIOMASS_GCS_PREFIX}/{filename}")
        blob.upload_from_string(raw, content_type=file.content_type or "image/jpeg")
        image_url = f"https://storage.googleapis.com/{BIOMASS_GCS_BUCKET}/{BIOMASS_GCS_PREFIX}/{filename}"
    except Exception as e:
        print(f"[biomass] GCS upload failed (continuing without persistent URL): {e}")

    prediction = _call_estimator_upload(
        raw, filename, file.content_type or "image/jpeg",
        source="upload", field_id=field_id,
    )

    row = models.FieldBiomassAnalysis(
        FieldID=      field_id,
        BusinessID=   field.BusinessID,
        Source=       "upload",
        BiomassKgHa=  prediction.get("biomass_kg_per_ha"),
        Confidence=   prediction.get("confidence"),
        ImageUrl=     image_url,
        CapturedAt=   datetime.utcnow(),
        ModelVersion= prediction.get("model_version"),
        FeaturesJSON= json.dumps(prediction.get("features") or {}),
        CreatedAt=    datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_biomass_row(row)
