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

import json
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


def _proxy_get_soft(path: str, params: dict | None = None, timeout: int | None = None) -> Optional[dict]:
    """Best-effort CropMonitor GET — returns None when unreachable or non-2xx."""
    try:
        r = requests.get(
            f"{CROP_MONITOR_URL}{path}",
            params=params or {},
            timeout=timeout or _TIMEOUT_S,
        )
        if not r.ok:
            return None
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def _proxy_post_soft(path: str, json_body: dict | None = None) -> Optional[dict]:
    try:
        r = requests.post(f"{CROP_MONITOR_URL}{path}", json=json_body or {}, timeout=_TIMEOUT_S)
        if not r.ok:
            return None
        try:
            return r.json()
        except ValueError:
            return {"ok": True}
    except requests.RequestException:
        return None


def _iso_out(v) -> Optional[str]:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        s = v.isoformat()
        if "T" in s and not s.endswith("Z") and "+" not in s:
            return s + "Z"
        return s
    return str(v)


def _local_analyses(db: Session, field_id: int, limit: int) -> dict:
    """Read dbo.Analysis directly when CropMonitor Cloud Run is down or stale."""
    lim = max(1, min(int(limit), 200))
    try:
        rows = db.execute(
            text(f"""
                SELECT TOP {lim}
                       a.AnalysisID AS analysis_id,
                       a.AnalysisDate AS analysis_date,
                       a.HealthScore AS health_score,
                       a.Status AS status,
                       a.NDVIUrl AS ndvi_url,
                       a.ImageUrls AS image_urls,
                       a.SatelliteAcquiredAt AS satellite_acquired_at,
                       (SELECT IndexType AS index_type, MeanValue AS mean,
                               MinValue AS min, MaxValue AS max
                          FROM dbo.VegetationIndex vi
                         WHERE vi.AnalysisID = a.AnalysisID
                           FOR JSON PATH) AS vegetation_indices
                  FROM dbo.Analysis a
                 WHERE a.FieldID = :fid
                 ORDER BY a.AnalysisDate DESC
            """),
            {"fid": field_id},
        ).fetchall()
    except Exception:
        return {"analyses": [], "source": "local_db"}
    analyses: list[dict] = []
    for row in rows:
        m = row._mapping
        item = dict(m)
        vi = item.get("vegetation_indices")
        if isinstance(vi, str):
            try:
                item["vegetation_indices"] = json.loads(vi)
            except json.JSONDecodeError:
                item["vegetation_indices"] = []
        if isinstance(item.get("image_urls"), str):
            try:
                item["image_urls"] = json.loads(item["image_urls"])
            except json.JSONDecodeError:
                pass
        item["analysis_date"] = _iso_out(item.get("analysis_date"))
        item["satellite_acquired_at"] = _iso_out(item.get("satellite_acquired_at"))
        analyses.append(item)
    return {"analyses": analyses, "source": "local_db"}


def _local_index_series(db: Session, field_id: int, index: str, days: int, limit: int) -> dict:
    idx = (index or "NDVI").strip().upper()
    days = max(7, min(int(days), 730))
    lim = max(1, min(int(limit), 500))
    series: list[dict] = []
    try:
        rows = db.execute(
            text(f"""
                SELECT TOP {lim}
                       a.AnalysisID AS analysis_id,
                       a.AnalysisDate AS analysis_date,
                       v.MeanValue AS mean,
                       v.MinValue AS min,
                       v.MaxValue AS max,
                       v.StdDev AS std
                  FROM dbo.Analysis a
                  JOIN dbo.VegetationIndex v ON v.AnalysisID = a.AnalysisID
                 WHERE a.FieldID = :fid
                   AND v.IndexType = :idx
                   AND a.AnalysisDate >= DATEADD(day, -:days, CAST(GETUTCDATE() AS DATE))
                 ORDER BY a.AnalysisDate ASC
            """),
            {"fid": field_id, "idx": idx, "days": days},
        ).fetchall()
        for row in rows:
            m = row._mapping
            series.append({
                "analysis_id": m.get("analysis_id"),
                "date": _iso_out(m.get("analysis_date")),
                "mean": float(m["mean"]) if m.get("mean") is not None else None,
                "min": float(m["min"]) if m.get("min") is not None else None,
                "max": float(m["max"]) if m.get("max") is not None else None,
                "std": float(m["std"]) if m.get("std") is not None else None,
            })
    except Exception:
        pass
    return {
        "field_id": field_id,
        "index": idx,
        "days": days,
        "series": series,
        "summary": None,
        "source": "local_db",
    }


def _local_agronomy(db: Session, field_id: int) -> dict:
    field = (
        db.query(models.Field)
        .filter(models.Field.FieldID == field_id, models.Field.DeletedAt.is_(None))
        .first()
    )
    analyses_payload = _local_analyses(db, field_id, 2)
    latest = (analyses_payload.get("analyses") or [None])[0]
    return {
        "field_id": field_id,
        "field_name": getattr(field, "Name", None) if field else None,
        "crop_type": getattr(field, "CropType", None) if field else None,
        "latest_analysis": latest,
        "weather": None,
        "forecast": [],
        "recommendations": [],
        "irrigation": None,
        "disease_alerts": [],
        "source": "local_db",
        "note": "CropMonitor service unavailable — showing stored analysis rows only.",
    }


def _local_recommendations(db: Session, field_id: int) -> dict:
    analyses = _local_analyses(db, field_id, 1).get("analyses") or []
    latest = analyses[0] if analyses else None
    return {
        "field_id": field_id,
        "health_score": latest.get("health_score") if latest else None,
        "recommendations": [],
        "source": "local_db",
    }

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

@router.get("/fields/{field_id}/analyses")
def get_field_analyses(
    field_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Satellite analysis history from CropMonitor (proxied)."""
    _verify_field_access(db, user.PeopleID, field_id)
    data = _proxy_get_soft(f"/api/fields/{field_id}/analyses", {"limit": limit})
    if data is not None:
        return data
    return _local_analyses(db, field_id, limit)


@router.post("/fields/{field_id}/analyze")
def run_field_analysis(
    field_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Trigger a fresh Sentinel analysis on CropMonitor."""
    _verify_field_access(db, user.PeopleID, field_id)
    data = _proxy_post_soft(f"/api/fields/{field_id}/analyze")
    if data is not None:
        return data
    return {
        "message": "CropMonitor is not reachable from India backend yet. "
                   "Analysis was not queued; contact ops to deploy crop-monitor-in.",
        "queued": False,
        "source": "local_fallback",
    }


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
    data = _proxy_get_soft(f"/api/fields/{field_id}/agronomy", timeout=60)
    if data is not None:
        return data
    return _local_agronomy(db, field_id)


@router.get("/fields/{field_id}/recommendations")
def get_field_recommendations(
    field_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Operational recommendations driven by CropMonitor's health-score +
    NDVI + current weather."""
    _verify_field_access(db, user.PeopleID, field_id)
    data = _proxy_get_soft(f"/api/fields/{field_id}/recommendations")
    if data is not None:
        return data
    return _local_recommendations(db, field_id)


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
    params = {"index": index, "days": days, "limit": limit}
    data = _proxy_get_soft(f"/api/fields/{field_id}/indices/series", params)
    if data is not None:
        return data
    return _local_index_series(db, field_id, index, days, limit)


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
    raw = _proxy_get_soft(
        f"/api/fields/{field_id}/raster/{index_name}",
        params,
        timeout=60,
    )
    if raw and ((raw.get("grid") or {}).get("values") or raw.get("values")):
        return raw
    field = (
        db.query(models.Field)
        .filter(models.Field.FieldID == field_id, models.Field.DeletedAt.is_(None))
        .first()
    )
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    overlay = _terrain_screening.build_vegetation_overlay_json(
        field, field_id, index_name, grid, db,
    )
    return {
        "field_id": field_id,
        "index": overlay.get("index") or index_name.upper(),
        "bbox": overlay.get("bbox"),
        "image_date": overlay.get("image_date"),
        "source": overlay.get("source"),
        "grid": {
            "values": overlay.get("values"),
            "rows": overlay.get("rows"),
            "cols": overlay.get("cols"),
        },
    }


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
        data = _proxy_get_soft(
            f"/api/fields/{field_id}/terrain/overlay/{layer}",
            {"grid": grid, "format": "json"},
            timeout=90,
        )
        if data and (data.get("values") or (data.get("grid") or {}).get("values")):
            return data
        if layer_key in veg_indices:
            raw = _proxy_get_soft(
                f"/api/fields/{field_id}/raster/{layer_key}",
                {"grid": min(grid, 96)},
                timeout=90,
            )
            if raw:
                g = (raw or {}).get("grid") or {}
                values = g.get("values") or raw.get("values")
                if values:
                    return {
                        "values": values,
                        "rows": g.get("rows") or len(values),
                        "cols": g.get("cols") or (len(values[0]) if values else 0),
                        "bbox": (raw or {}).get("bbox"),
                        "index": (raw or {}).get("index") or layer_key.upper(),
                        "image_date": (raw or {}).get("image_date"),
                        "source": (raw or {}).get("source") or "cropmonitor_raster",
                        "raster": (raw or {}).get("raster"),
                    }
            field = (
                db.query(models.Field)
                .filter(models.Field.FieldID == field_id, models.Field.DeletedAt.is_(None))
                .first()
            )
            if field:
                return _terrain_screening.build_vegetation_overlay_json(
                    field, field_id, layer_key, grid, db,
                )
        raise HTTPException(status_code=404, detail="Overlay grid unavailable")

    try:
        return _proxy_bytes(
            f"/api/fields/{field_id}/terrain/overlay/{layer}",
            {"grid": grid, "format": "png"},
        )
    except HTTPException as e:
        if layer_key in veg_indices and e.status_code in (404, 500, 502):
            try:
                return _proxy_bytes(
                    f"/api/fields/{field_id}/heatmap/{layer_key}",
                    None,
                )
            except HTTPException:
                raise HTTPException(
                    status_code=404,
                    detail="PNG overlay unavailable — use format=json for grid paint",
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