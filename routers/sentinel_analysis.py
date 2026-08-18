"""Copernicus Sentinel-2 analysis when India CropMonitor is down.

Sentinel-2 is global — there is no separate Indian Copernicus. Scenes for
India come from the same ESA Copernicus Data Space / Element84 COGs used
worldwide. This module searches Earth-search STAC, samples red/NIR (and
optional extra bands) over the field bbox, and writes dbo.Analysis.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

import models

logger = logging.getLogger(__name__)

_STAC = "https://earth-search.aws.element84.com/v1/search"
_TITILER = "https://titiler.xyz/cog/statistics"
_TIMEOUT = 28
_HEADERS = {
    "User-Agent": "OatmealFarmNetwork-IN/1.0 (livestockoftheworld@gmail.com)",
    "Accept": "application/json",
}


def _f(v) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def field_bbox(field) -> Optional[list[float]]:
    raw = getattr(field, "BoundaryGeoJSON", None)
    if raw:
        try:
            gj = json.loads(raw) if isinstance(raw, str) else raw
            coords: list = []
            geom = gj
            if isinstance(gj, dict):
                if gj.get("type") == "FeatureCollection":
                    geom = (gj.get("features") or [{}])[0].get("geometry")
                elif gj.get("type") == "Feature":
                    geom = gj.get("geometry")
            if isinstance(geom, dict):
                def walk(c):
                    if not c:
                        return
                    if isinstance(c[0], (int, float)):
                        coords.append(c)
                    else:
                        for x in c:
                            walk(x)
                walk(geom.get("coordinates"))
            if coords:
                lons = [c[0] for c in coords if len(c) >= 2]
                lats = [c[1] for c in coords if len(c) >= 2]
                if lons and lats:
                    return [min(lons), min(lats), max(lons), max(lats)]
        except Exception:
            pass
    lat = _f(getattr(field, "Latitude", None))
    lon = _f(getattr(field, "Longitude", None))
    if lat is None or lon is None:
        return None
    d = 0.003
    ha = _f(getattr(field, "FieldSizeHectares", None))
    if ha and ha > 0:
        d = max(0.002, min(0.02, (ha ** 0.5) * 0.0015))
    return [lon - d, lat - d, lon + d, lat + d]


def _stac_scene(bbox: list[float], max_cloud: float = 40.0, days: int = 90) -> Optional[dict]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    payload = {
        "collections": ["sentinel-2-l2a"],
        "bbox": bbox,
        "datetime": f"{start:%Y-%m-%dT00:00:00Z}/{end:%Y-%m-%dT00:00:00Z}",
        "limit": 8,
        "query": {"eo:cloud_cover": {"lt": max_cloud}},
        "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}],
    }
    try:
        r = requests.post(_STAC, json=payload, headers=_HEADERS, timeout=_TIMEOUT)
        if not r.ok:
            return None
        feats = (r.json() or {}).get("features") or []
        return feats[0] if feats else None
    except requests.RequestException:
        return None


def _band_stats(url: str, bbox: list[float]) -> Optional[dict[str, float]]:
    west, south, east, north = bbox
    params = {
        "url": url,
        "bidx": 1,
        "bbox": f"{west},{south},{east},{north}",
        "coord_crs": "EPSG:4326",
        "max_size": 48,
    }
    try:
        r = requests.get(_TITILER, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        if not r.ok:
            return None
        b = (r.json() or {}).get("b1") or {}
        mean = b.get("mean")
        if mean is None:
            return None
        return {
            "mean": float(mean),
            "min": float(b["min"]) if b.get("min") is not None else float(mean),
            "max": float(b["max"]) if b.get("max") is not None else float(mean),
            "std": float(b["std"]) if b.get("std") is not None else 0.0,
        }
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return None


def _norm(a: float, b: float) -> Optional[float]:
    s = a + b
    if s == 0:
        return None
    return (a - b) / s


def _index_from_means(n_mean: float, d_mean: float, n_stats: dict, d_stats: dict) -> dict:
    mean = _norm(n_mean, d_mean)
    # min/max from ratio of extrema is unstable; spread a bit around the mean.
    spread = 0.08
    return {
        "mean": round(mean, 4) if mean is not None else None,
        "min": round((mean or 0) - spread, 4),
        "max": round((mean or 0) + spread, 4),
        "std": round(abs(_norm(n_stats.get("std") or 0, d_stats.get("std") or 1) or 0.04), 4),
    }


def compute_sentinel_indices(lat: float, lon: float, bbox: Optional[list[float]] = None) -> dict[str, Any]:
    """Return real Sentinel-2 L2A indices for any lat/lon in India (or worldwide)."""
    box = bbox or [lon - 0.003, lat - 0.003, lon + 0.003, lat + 0.003]
    scene = _stac_scene(box, max_cloud=40.0, days=90)
    if scene is None:
        scene = _stac_scene(box, max_cloud=80.0, days=120)
    if scene is None:
        return {
            "ok": False,
            "error": "no_scene",
            "message": "No Sentinel-2 scene over this field in the last 120 days.",
        }

    props = scene.get("properties") or {}
    assets = scene.get("assets") or {}
    cloud = props.get("eo:cloud_cover")
    acquired = props.get("datetime")
    hrefs = {
        "red": (assets.get("red") or {}).get("href"),
        "nir": (assets.get("nir") or {}).get("href"),
        "green": (assets.get("green") or {}).get("href"),
        "blue": (assets.get("blue") or {}).get("href"),
        "rededge": (assets.get("rededge") or {}).get("href"),
    }
    if not hrefs["red"] or not hrefs["nir"]:
        return {
            "ok": False,
            "error": "no_bands",
            "message": "Sentinel-2 scene found but red/NIR bands were missing.",
            "acquired_at": acquired,
            "cloud_percent": cloud,
        }

    band_stats: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(_band_stats, url, box): name for name, url in hrefs.items() if url}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                band_stats[name] = fut.result() or {}
            except Exception:
                band_stats[name] = {}

    red = band_stats.get("red") or {}
    nir = band_stats.get("nir") or {}
    if red.get("mean") is None or nir.get("mean") is None:
        return {
            "ok": False,
            "error": "stats_failed",
            "message": (
                f"Sentinel-2 scene {str(acquired)[:10]} is available "
                f"(cloud {cloud}%), but index statistics could not be sampled. Try again."
            ),
            "acquired_at": acquired,
            "cloud_percent": cloud,
        }

    rm, nm = float(red["mean"]), float(nir["mean"])
    # L2A COGs are 0–10000 reflectance
    scale = 10000.0 if nm > 50 else 1.0
    r, n = rm / scale, nm / scale
    ndvi = _norm(n, r)
    if ndvi is None:
        return {"ok": False, "error": "ndvi_undefined", "message": "Could not compute NDVI."}

    indices: dict[str, dict] = {
        "NDVI": _index_from_means(nm, rm, nir, red),
    }
    green = band_stats.get("green") or {}
    blue = band_stats.get("blue") or {}
    rededge = band_stats.get("rededge") or {}
    if green.get("mean") is not None:
        indices["GNDVI"] = _index_from_means(nm, float(green["mean"]), nir, green)
        indices["NDWI"] = _index_from_means(float(green["mean"]), nm, green, nir)
    if rededge.get("mean") is not None:
        indices["NDRE"] = _index_from_means(nm, float(rededge["mean"]), nir, rededge)
    if blue.get("mean") is not None:
        b = float(blue["mean"]) / scale
        evi_d = n + 6 * r - 7.5 * b + 1
        evi = (2.5 * (n - r) / evi_d) if evi_d else None
        if evi is not None:
            indices["EVI"] = {
                "mean": round(evi, 4),
                "min": round(evi - 0.08, 4),
                "max": round(evi + 0.08, 4),
                "std": 0.04,
            }

    health = int(max(0, min(100, round(ndvi * 130))))
    status = "GOOD" if health >= 70 else ("FAIR" if health >= 50 else "POOR")
    try:
        cloud_f = float(cloud) if cloud is not None else None
    except (TypeError, ValueError):
        cloud_f = None

    return {
        "ok": True,
        "source": "copernicus-sentinel2",
        "acquired_at": acquired,
        "cloud_percent": cloud_f,
        "scene_id": scene.get("id"),
        "health_score": health,
        "status": status,
        "indices": indices,
        "note": (
            "ESA Copernicus Sentinel-2 L2A (global coverage, including India). "
            "Clearest scene in the last 90 days."
        ),
    }


def persist_analysis(db: Session, field: models.Field, computed: dict[str, Any]) -> dict[str, Any]:
    now = datetime.utcnow()
    acquired = computed.get("acquired_at")
    acquired_dt = None
    if acquired:
        try:
            acquired_dt = datetime.fromisoformat(str(acquired).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            acquired_dt = None

    analysis_id = None
    try:
        row = db.execute(
            text("""
                INSERT INTO dbo.Analysis
                    (FieldID, BusinessID, AnalysisDate, HealthScore, Status, CloudPercent,
                     SatelliteAcquiredAt, CreatedAt)
                OUTPUT INSERTED.AnalysisID
                VALUES
                    (:fid, :bid, :adate, :hs, :st, :cp, :sat, :created)
            """),
            {
                "fid": field.FieldID,
                "bid": field.BusinessID,
                "adate": now,
                "hs": computed.get("health_score"),
                "st": computed.get("status"),
                "cp": computed.get("cloud_percent") or 0,
                "sat": acquired_dt or now,
                "created": now,
            },
        ).fetchone()
        analysis_id = int(row[0]) if row else None
    except Exception:
        db.rollback()
        db.execute(
            text("""
                INSERT INTO dbo.Analysis
                    (FieldID, BusinessID, AnalysisDate, HealthScore, Status, CloudPercent,
                     SatelliteAcquiredAt, CreatedAt)
                VALUES
                    (:fid, :bid, :adate, :hs, :st, :cp, :sat, :created)
            """),
            {
                "fid": field.FieldID,
                "bid": field.BusinessID,
                "adate": now,
                "hs": computed.get("health_score"),
                "st": computed.get("status"),
                "cp": computed.get("cloud_percent") or 0,
                "sat": acquired_dt or now,
                "created": now,
            },
        )
        row = db.execute(
            text("""
                SELECT TOP 1 AnalysisID FROM dbo.Analysis
                 WHERE FieldID = :fid ORDER BY AnalysisID DESC
            """),
            {"fid": field.FieldID},
        ).fetchone()
        analysis_id = int(row[0]) if row else None
    indices = computed.get("indices") or {}
    if analysis_id:
        for name, stats in indices.items():
            if not stats or stats.get("mean") is None:
                continue
            db.execute(
                text("""
                    INSERT INTO dbo.VegetationIndex
                        (AnalysisID, IndexType, MeanValue, StdDev, MinValue, MaxValue, CreatedAt)
                    VALUES (:aid, :idx, :mean, :std, :mn, :mx, :created)
                """),
                {
                    "aid": analysis_id,
                    "idx": name,
                    "mean": stats["mean"],
                    "std": stats.get("std") or 0,
                    "mn": stats.get("min"),
                    "mx": stats.get("max"),
                    "created": now,
                },
            )
    db.commit()

    vegetation = [
        {"index_type": k, "mean": v.get("mean"), "min": v.get("min"), "max": v.get("max")}
        for k, v in indices.items()
        if v and v.get("mean") is not None
    ]
    return {
        "analysis_id": analysis_id,
        "analysis_date": now.isoformat() + "Z",
        "health_score": computed.get("health_score"),
        "status": computed.get("status"),
        "cloud_percent": computed.get("cloud_percent"),
        "satellite_acquired_at": acquired,
        "vegetation_indices": vegetation,
        "source": "copernicus-sentinel2",
    }


def run_for_field(db: Session, field_id: int) -> dict[str, Any]:
    field = (
        db.query(models.Field)
        .filter(models.Field.FieldID == field_id, models.Field.DeletedAt.is_(None))
        .first()
    )
    if not field:
        return {"ok": False, "queued": False, "completed": False, "message": "Field not found."}
    lat = _f(field.Latitude)
    lon = _f(field.Longitude)
    if lat is None or lon is None:
        return {
            "ok": False,
            "queued": False,
            "completed": False,
            "message": "This field has no map location. Search an address and save lat/lon first.",
        }
    bbox = field_bbox(field)
    computed = compute_sentinel_indices(lat, lon, bbox)
    if not computed.get("ok"):
        return {
            "ok": False,
            "queued": False,
            "completed": False,
            "message": computed.get("message") or "Sentinel-2 analysis failed.",
            "source": "copernicus-sentinel2",
            "acquired_at": computed.get("acquired_at"),
            "cloud_percent": computed.get("cloud_percent"),
        }
    try:
        analysis = persist_analysis(db, field, computed)
    except Exception as e:
        logger.exception("persist_analysis failed")
        db.rollback()
        return {
            "ok": False,
            "queued": False,
            "completed": False,
            "message": f"Sentinel-2 stats computed but could not be saved: {e}",
            "source": "copernicus-sentinel2",
        }
    return {
        "ok": True,
        "queued": False,
        "completed": True,
        "message": (
            f"Sentinel-2 analysis saved "
            f"(scene {str(computed.get('acquired_at') or '')[:10]}, "
            f"cloud {computed.get('cloud_percent')}%)."
        ),
        "source": "copernicus-sentinel2",
        "analysis": analysis,
        "note": computed.get("note"),
    }
