"""
Thin passthrough to CropMonitoringBackend so the rest of the platform
(frontend pages, Saige tools) can talk to a single backend instead of
having to know about the second service.

Wraps four CropMonitor capabilities the rest of OFN was missing:
  - WaPOR water-content (latest snapshot + time series)
  - LLM/heuristic agronomy recommendations
  - Per-field operational recommendations from current health + weather
  - Email-the-latest-analysis trigger

Each route does access-scoping against the user's BusinessIDs (via
`people_id`) so the proxy can't be used to read data on fields that
don't belong to the caller.
"""
from __future__ import annotations

import os
from typing import List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import text

import models
from auth import get_current_user
from database import get_db
from precision_ag_auth import _verify_field_access
from field_twin.config import crop_monitor_url
from . import terrain_screening as _terrain_screening

router = APIRouter(prefix="/api", tags=["crop-monitor-proxy"])

CROP_MONITOR_URL = crop_monitor_url()
_TIMEOUT_S = 20  # WaPOR + agronomy can be slow


def _business_ids_for_people(people_id: Optional[int], db: Session) -> List[int]:
    if not people_id:
        return []
    rows = (
        db.query(models.BusinessAccess.BusinessID)
        .filter(models.BusinessAccess.PeopleID == people_id)
        .all()
    )
    return [r.BusinessID for r in rows]


def _check_field_access(field_id: int, people_id: Optional[int], db: Session) -> models.Field:
    """Return the field row if the caller may see it; otherwise 403/404. We
    only enforce access when a `people_id` is supplied — this mirrors how
    the rest of the precision-ag endpoints behave today (open by FieldID,
    Saige tools always pass people_id)."""
    field = db.query(models.Field).filter(models.Field.FieldID == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    if people_id is not None:
        biz_ids = _business_ids_for_people(people_id, db)
        if biz_ids and field.BusinessID not in biz_ids:
            raise HTTPException(status_code=403, detail="Field not accessible on this account")
    return field


def _proxy_get(path: str, params: dict | None = None, timeout: int | None = None) -> dict:
    try:
        r = requests.get(f"{CROP_MONITOR_URL}{path}", params=params or {}, timeout=timeout or _TIMEOUT_S)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"CropMonitor unreachable: {e}")
    if not r.ok:
        raise HTTPException(status_code=r.status_code, detail=r.text or r.reason)
    try:
        return r.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="CropMonitor returned non-JSON")


def _proxy_post(path: str, json_body: dict | None = None) -> dict:
    try:
        r = requests.post(f"{CROP_MONITOR_URL}{path}", json=json_body or {}, timeout=_TIMEOUT_S)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"CropMonitor unreachable: {e}")
    if not r.ok:
        raise HTTPException(status_code=r.status_code, detail=r.text or r.reason)
    try:
        return r.json()
    except ValueError:
        return {"ok": True}


# ─── WaPOR water use ────────────────────────────────────────────────────────

@router.get("/fields/{field_id}/water-use")
def get_field_water_use(
    field_id: int,
    mapset: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Latest WaPOR/OpenET water-content snapshot for the field."""
    _verify_field_access(db, user.PeopleID, field_id)
    params = {"mapset": mapset} if mapset else None
    return _proxy_get(f"/api/fields/{field_id}/wapor/water", params)


@router.get("/fields/{field_id}/water-use/series")
def get_field_water_use_series(
    field_id: int,
    mapset: Optional[str] = None,
    limit: int = Query(12, ge=1, le=60),
    model: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Recent WaPOR/OpenET water-content time series for the field."""
    _verify_field_access(db, user.PeopleID, field_id)
    params = {"limit": limit}
    if mapset: params["mapset"] = mapset
    if model:  params["model"]  = model
    return _proxy_get(f"/api/fields/{field_id}/wapor/water-series", params)


# ─── Agronomy + recommendations ─────────────────────────────────────────────

@router.get("/fields/{field_id}/agronomy")
def get_field_agronomy(
    field_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Full agronomy snapshot from CropMonitor: weather + forecast + GDD +
    growth stage + latest indices + irrigation/disease signals. Cached
    server-side."""
    _verify_field_access(db, user.PeopleID, field_id)
    return _proxy_get(f"/api/fields/{field_id}/agronomy")


@router.get("/fields/{field_id}/recommendations")
def get_field_recommendations(
    field_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Operational recommendations driven by CropMonitor's health-score +
    NDVI + current weather."""
    _verify_field_access(db, user.PeopleID, field_id)
    return _proxy_get(f"/api/fields/{field_id}/recommendations")


# ─── Time-series indices + stress zones ─────────────────────────────────────

@router.get("/fields/{field_id}/indices/series")
def get_field_index_series(
    field_id: int,
    index: str = "NDVI",
    days: int = Query(180, ge=7, le=730),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Time series of a vegetation index for the field — used by trend charts."""
    _verify_field_access(db, user.PeopleID, field_id)
    return _proxy_get(
        f"/api/fields/{field_id}/indices/series",
        {"index": index, "days": days, "limit": limit},
    )


@router.get("/fields/{field_id}/zones")
def get_field_zones(
    field_id: int,
    index: str = "NDVI",
    num_zones: int = Query(4, ge=2, le=6),
    grid: int = Query(48, ge=16, le=96),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """K-means stress zones from the latest vegetation-index raster."""
    _verify_field_access(db, user.PeopleID, field_id)
    return _proxy_get(
        f"/api/fields/{field_id}/zones",
        {"index": index, "num_zones": num_zones, "grid": grid},
        timeout=60,  # Sentinel-Hub fetch + clustering can run ~5-30s on cold raster
    )


@router.get("/fields/{field_id}/raster/{index_name}")
def get_field_raster_values(
    field_id: int,
    index_name: str,
    grid: int = Query(48, ge=16, le=96),
    analysis_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Real per-cell vegetation index values (downsampled). Powers map + Rx pages.
    Pass analysis_id to fetch the historical scene for that Analysis row."""
    _verify_field_access(db, user.PeopleID, field_id)
    params = {"grid": grid}
    if analysis_id is not None:
        params["analysis_id"] = analysis_id
    return _proxy_get(
        f"/api/fields/{field_id}/raster/{index_name}",
        params,
        timeout=60,
    )


@router.get("/fields/{field_id}/zones/prescription")
def get_field_zone_prescription(
    field_id: int,
    index: str = "NDVI",
    num_zones: int = Query(4, ge=2, le=6),
    grid: int = Query(48, ge=16, le=96),
    fmt: str = "geojson",
    rates: Optional[str] = None,
    units: str = "kg/ha",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Variable-rate prescription file (GeoJSON or CSV) generated from zones."""
    _verify_field_access(db, user.PeopleID, field_id)
    # Streaming binary content — call CropMonitor and pass through verbatim
    from fastapi.responses import Response
    params = {"index": index, "num_zones": num_zones, "grid": grid, "fmt": fmt, "units": units}
    if rates:
        params["rates"] = rates
    try:
        r = requests.get(
            f"{CROP_MONITOR_URL}/api/fields/{field_id}/zones/prescription",
            params=params, timeout=60,
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"CropMonitor unreachable: {e}")
    if not r.ok:
        raise HTTPException(status_code=r.status_code, detail=r.text or r.reason)
    return Response(
        content=r.content,
        media_type=r.headers.get("Content-Type", "application/octet-stream"),
        headers={"Content-Disposition": r.headers.get("Content-Disposition", "")},
    )


def _proxy_bytes(path: str, params: dict | None = None, timeout: int | None = None) -> Response:
    """Passthrough binary (PNG / float32) responses with selected headers."""
    try:
        r = requests.get(
            f"{CROP_MONITOR_URL}{path}",
            params=params or {},
            timeout=timeout or 90,
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"CropMonitor unreachable: {e}")
    if not r.ok:
        raise HTTPException(status_code=r.status_code, detail=r.text or r.reason)
    pass_headers = {}
    for h in (
        "Content-Disposition", "X-Grid-Width", "X-Grid-Height",
        "X-Elev-Min", "X-Elev-Max", "X-Acquired-At", "X-Encoding", "X-Layer",
    ):
        if h in r.headers:
            pass_headers[h] = r.headers[h]
    return Response(
        content=r.content,
        media_type=r.headers.get("Content-Type", "application/octet-stream"),
        headers=pass_headers,
    )


def _observed_context_for_simulation(db: Session, field_id: int) -> dict:
    """Pull real profile / moisture / irrigation when present — never invent values."""
    ctx: dict = {}
    try:
        row = db.execute(
            text("SELECT DrainageClass FROM FieldProfile WHERE FieldID = :fid"),
            {"fid": field_id},
        ).fetchone()
        if row and getattr(row, "DrainageClass", None):
            ctx["observed_drainage_class"] = row.DrainageClass
    except Exception:
        pass
    try:
        m = db.execute(text("""
            SELECT TOP 1 m.MoisturePct
            FROM SoilMoistureReading m
            INNER JOIN IrrigationZone z ON z.ZoneID = m.ZoneID
            WHERE TRY_CAST(z.FieldID AS INT) = :fid
            ORDER BY m.ReadingTime DESC
        """), {"fid": field_id}).fetchone()
        if m and m[0] is not None:
            ctx["observed_soil_moisture_pct"] = float(m[0])
    except Exception:
        pass
    try:
        irr = db.execute(text("""
            SELECT TOP 1 e.DepthMm
            FROM IrrigationEvent e
            INNER JOIN IrrigationZone z ON z.ZoneID = e.ZoneID
            WHERE TRY_CAST(z.FieldID AS INT) = :fid
              AND e.StartTime >= DATEADD(day, -7, GETDATE())
              AND e.DepthMm IS NOT NULL
            ORDER BY e.StartTime DESC
        """), {"fid": field_id}).fetchone()
        if irr and irr[0] is not None:
            ctx["recent_irrigation_mm"] = float(irr[0])
    except Exception:
        pass
    return ctx


# ─── 3D Terrain (JWT-required) ──────────────────────────────────────────────

@router.get("/fields/{field_id}/terrain/metadata")
def get_terrain_metadata(
    field_id: int,
    grid: int = Query(128, ge=32, le=256),
    include_radar: bool = True,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Authenticated terrain package metadata for the 3D viewer."""
    _verify_field_access(db, user.PeopleID, field_id)
    try:
        return _proxy_get(
            f"/api/fields/{field_id}/terrain/metadata",
            {"grid": grid, "include_radar": include_radar},
            timeout=90,
        )
    except HTTPException as e:
        if e.status_code not in (404, 405, 500, 501, 502):
            raise
        field = db.query(models.Field).filter(models.Field.FieldID == field_id).first()
        if not field:
            raise HTTPException(status_code=404, detail="Field not found")
        return _terrain_screening.build_screening_metadata(field, field_id, grid)


@router.get("/fields/{field_id}/terrain/elevation")
def get_terrain_elevation(
    field_id: int,
    grid: int = Query(128, ge=32, le=256),
    format: str = Query("json", pattern="^(json|f32)$"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _verify_field_access(db, user.PeopleID, field_id)
    try:
        if format == "f32":
            return _proxy_bytes(
                f"/api/fields/{field_id}/terrain/elevation",
                {"grid": grid, "format": "f32"},
            )
        return _proxy_get(
            f"/api/fields/{field_id}/terrain/elevation",
            {"grid": grid, "format": "json"},
            timeout=90,
        )
    except HTTPException as e:
        if e.status_code not in (404, 405, 500, 501, 502):
            raise
        if format == "f32":
            raise HTTPException(
                status_code=501,
                detail="Screening DEM is JSON-only; request format=json",
            )
        field = db.query(models.Field).filter(models.Field.FieldID == field_id).first()
        if not field:
            raise HTTPException(status_code=404, detail="Field not found")
        return _terrain_screening.build_screening_elevation(field, grid)


@router.get("/fields/{field_id}/terrain/texture")
def get_terrain_texture(
    field_id: int,
    grid: int = Query(128, ge=32, le=256),
    analysis_id: Optional[int] = Query(None),
    year: Optional[int] = Query(None, ge=1980, le=2100),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Natural-color terrain texture. Falls back to heatmap RGB or screening PNG."""
    _verify_field_access(db, user.PeopleID, field_id)
    params = {"grid": grid}
    if analysis_id is not None:
        params["analysis_id"] = analysis_id
    if year is not None:
        params["year"] = year
    try:
        return _proxy_bytes(f"/api/fields/{field_id}/terrain/texture", params)
    except HTTPException as e:
        if e.status_code not in (404, 405, 500, 501, 502):
            raise
        rgb_params: dict = {}
        resolved_analysis_id = analysis_id
        if resolved_analysis_id is None and year is not None:
            try:
                analyses = _proxy_get(
                    f"/api/fields/{field_id}/analyses",
                    {"limit": 40},
                    timeout=30,
                )
                for a in (analyses or {}).get("analyses") or []:
                    for key in ("analysis_date", "satellite_acquired_at", "date", "acquired_at"):
                        raw = a.get(key)
                        if not raw:
                            continue
                        try:
                            if int(str(raw)[:4]) == int(year):
                                resolved_analysis_id = a.get("analysis_id") or a.get("id")
                                break
                        except (TypeError, ValueError):
                            continue
                    if resolved_analysis_id is not None:
                        break
            except HTTPException:
                pass
        if resolved_analysis_id is not None:
            rgb_params["analysis_id"] = resolved_analysis_id
        try:
            return _proxy_bytes(
                f"/api/fields/{field_id}/heatmap/rgb",
                rgb_params or None,
                timeout=120,
            )
        except HTTPException as rgb_err:
            if rgb_err.status_code not in (404, 405, 500, 501, 502):
                raise
        png = _terrain_screening.build_screening_texture_png(min(grid, 128))
        return Response(
            content=png,
            media_type="image/png",
            headers={
                "X-Layer": "texture-screening",
                "X-Encoding": "screening_placeholder",
            },
        )


@router.get("/fields/{field_id}/terrain/overlay/{layer}")
def get_terrain_overlay(
    field_id: int,
    layer: str,
    grid: int = Query(128, ge=32, le=256),
    format: str = Query("png"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Prefer Crop Monitor terrain overlays; fall back to heatmap / raster JSON."""
    _verify_field_access(db, user.PeopleID, field_id)
    layer_key = (layer or "").strip().lower()
    fmt = (format or "png").lower()
    veg_indices = {"ndvi", "ndwi", "ndre", "evi", "gndvi", "msavi"}

    if fmt == "json":
        try:
            return _proxy_get(
                f"/api/fields/{field_id}/terrain/overlay/{layer}",
                {"grid": grid, "format": "json"},
                timeout=90,
            )
        except HTTPException as e:
            if layer_key in veg_indices and e.status_code in (404, 500, 502):
                raw = _proxy_get(
                    f"/api/fields/{field_id}/raster/{layer_key}",
                    {"grid": min(grid, 96)},
                    timeout=90,
                )
                g = (raw or {}).get("grid") or {}
                values = g.get("values")
                if values:
                    return {
                        "values": values,
                        "rows": g.get("rows") or len(values),
                        "cols": g.get("cols") or (len(values[0]) if values else 0),
                        "bbox": (raw or {}).get("bbox"),
                        "index": (raw or {}).get("index") or layer_key.upper(),
                        "image_date": (raw or {}).get("image_date"),
                        "source": "cropmonitor_raster",
                        "raster": (raw or {}).get("raster"),
                    }
                raise HTTPException(status_code=404, detail="Raster grid empty")
            raise

    try:
        return _proxy_bytes(
            f"/api/fields/{field_id}/terrain/overlay/{layer}",
            {"grid": grid, "format": "png"},
        )
    except HTTPException as e:
        if layer_key in veg_indices and e.status_code in (404, 500, 502):
            return _proxy_bytes(
                f"/api/fields/{field_id}/heatmap/{layer_key}",
                None,
            )
        raise


@router.get("/fields/{field_id}/terrain/scenario-presets")
def get_terrain_scenario_presets(
    field_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """JWT-protected scenario presets for the water simulator."""
    _verify_field_access(db, user.PeopleID, field_id)
    try:
        return _proxy_get(
            f"/api/fields/{field_id}/terrain/scenario-presets",
            timeout=60,
        )
    except HTTPException as e:
        if e.status_code not in (404, 405, 500, 502):
            raise
        return _terrain_screening.build_screening_presets()


@router.post("/fields/{field_id}/terrain/simulate-water")
def simulate_terrain_water(
    field_id: int,
    body: dict,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Authenticated water-risk screening. Enriches body with observed context when available."""
    _verify_field_access(db, user.PeopleID, field_id)
    field = db.query(models.Field).filter(models.Field.FieldID == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    payload = dict(body or {})
    for k, v in _observed_context_for_simulation(db, field_id).items():
        if payload.get(k) is None:
            payload[k] = v
    try:
        r = requests.post(
            f"{CROP_MONITOR_URL}/api/fields/{field_id}/terrain/simulate-water",
            json=payload,
            timeout=120,
        )
    except requests.RequestException:
        return _terrain_screening.build_screening_simulate_water(field, payload)
    if r.status_code < 400:
        try:
            return r.json()
        except ValueError:
            raise HTTPException(status_code=502, detail="CropMonitor returned non-JSON")
    if r.status_code in (404, 405, 500, 501, 502):
        return _terrain_screening.build_screening_simulate_water(field, payload)
    raise HTTPException(status_code=r.status_code, detail=r.text or r.reason)


# ─── Email the latest analysis to the field owner ───────────────────────────

@router.post("/fields/{field_id}/email-analysis")
def email_latest_analysis(
    field_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Trigger CropMonitor's email-latest-analysis flow for this field. The
    target inbox is configured in CropMonitor; this proxy only enforces
    that the caller may see the field."""
    _verify_field_access(db, user.PeopleID, field_id)
    return _proxy_post(f"/api/fields/{field_id}/email-latest")