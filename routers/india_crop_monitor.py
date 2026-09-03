"""India crop monitoring: ISRO Bhuvan LULC first, Copernicus Sentinel-2 fallback."""
from __future__ import annotations

import os
from typing import Any, Optional

from sqlalchemy.orm import Session

import models
from routers import sentinel_analysis
from routers.bhuvan import BHUVAN_YEAR, query_lulc_at


def _india_stack() -> bool:
    return (os.getenv("COMMODITY_MARKET") or os.getenv("VITE_OFN_STACK") or "india").lower() == "india"


def _field_centroid(field) -> tuple[Optional[float], Optional[float]]:
    lat = sentinel_analysis._f(getattr(field, "Latitude", None))
    lon = sentinel_analysis._f(getattr(field, "Longitude", None))
    if lat is not None and lon is not None:
        return lat, lon
    bbox = sentinel_analysis.field_bbox(field)
    if bbox:
        west, south, east, north = bbox
        return (south + north) / 2, (west + east) / 2
    return None, None


def health_from_lulc(class_name: Optional[str]) -> tuple[int, str]:
    """Map Bhuvan LULC class to a coarse health score for crop monitoring."""
    if not class_name:
        return 50, "UNKNOWN"
    c = class_name.lower()
    if any(k in c for k in ("agricultur", "crop", "plantation", "orchard", "cropland")):
        return 72, "GOOD"
    if any(k in c for k in ("grass", "grazing")):
        return 58, "FAIR"
    if any(k in c for k in ("forest", "wetland", "water")):
        return 40, "POOR"
    if any(k in c for k in ("built", "wasteland", "barren", "scrub")):
        return 25, "POOR"
    return 55, "FAIR"


def snapshot(db: Session, field_id: int) -> dict[str, Any]:
    """Current monitoring view: Bhuvan LULC + latest saved analysis (any source)."""
    field = (
        db.query(models.Field)
        .filter(models.Field.FieldID == field_id, models.Field.DeletedAt.is_(None))
        .first()
    )
    if not field:
        return {"ok": False, "message": "Field not found."}

    lat, lon = _field_centroid(field)
    bhuvan: Optional[dict] = None
    if lat is not None and lon is not None:
        bhuvan = query_lulc_at(lon, lat)

    latest = None
    from sqlalchemy import text
    row = db.execute(
        text("""
            SELECT TOP 1 AnalysisID AS analysis_id, AnalysisDate AS analysis_date,
                   HealthScore AS health_score, Status AS status,
                   CloudPercent AS cloud_percent,
                   SatelliteAcquiredAt AS satellite_acquired_at
              FROM dbo.Analysis
             WHERE FieldID = :fid
             ORDER BY AnalysisDate DESC
        """),
        {"fid": field_id},
    ).fetchone()
    latest = dict(row._mapping) if row else None

    primary_source = "bhuvan-lulc-250k" if bhuvan and bhuvan.get("class_name") else None
    if not primary_source and latest:
        primary_source = "copernicus-sentinel2"

    hs, st = health_from_lulc(bhuvan.get("class_name") if bhuvan else None)

    return {
        "ok": True,
        "field_id": field_id,
        "primary_source": primary_source,
        "bhuvan": bhuvan,
        "bhuvan_year": BHUVAN_YEAR,
        "lulc_health_score": hs,
        "lulc_status": st,
        "latest_analysis": latest,
        "fallback_note": (
            "ISRO Bhuvan LULC is primary for land-use monitoring. "
            "Sentinel-2 NDVI is used when Bhuvan is unavailable or for vegetation indices."
        ),
    }


def run_analysis(db: Session, field_id: int) -> dict[str, Any]:
    """Run crop monitor: Bhuvan LULC first; Sentinel-2 if Bhuvan fails."""
    if not _india_stack():
        return sentinel_analysis.run_for_field(db, field_id)

    field = (
        db.query(models.Field)
        .filter(models.Field.FieldID == field_id, models.Field.DeletedAt.is_(None))
        .first()
    )
    if not field:
        return {"ok": False, "completed": False, "message": "Field not found."}

    lat, lon = _field_centroid(field)
    if lat is None or lon is None:
        return {
            "ok": False,
            "completed": False,
            "message": "This field has no map location. Search an address and save lat/lon first.",
        }

    bhuvan = query_lulc_at(lon, lat)
    if bhuvan and bhuvan.get("class_name"):
        hs, st = health_from_lulc(bhuvan["class_name"])
        bbox = sentinel_analysis.field_bbox(field)
        sentinel = sentinel_analysis.compute_sentinel_indices(lat, lon, bbox)
        computed: dict[str, Any] = {
            "ok": True,
            "source": "bhuvan-lulc-250k",
            "acquired_at": None,
            "cloud_percent": sentinel.get("cloud_percent") if sentinel.get("ok") else None,
            "health_score": hs,
            "status": st,
            "indices": sentinel.get("indices") if sentinel.get("ok") else {},
            "bhuvan_class": bhuvan["class_name"],
            "note": (
                f"ISRO Bhuvan LULC {BHUVAN_YEAR}: {bhuvan['class_name']}. "
                + (
                    f"Sentinel-2 NDVI supplement (scene {str(sentinel.get('acquired_at') or '')[:10]})."
                    if sentinel.get("ok")
                    else "Sentinel-2 supplement unavailable — Bhuvan LULC only."
                )
            ),
        }
        if sentinel.get("ok"):
            computed["acquired_at"] = sentinel.get("acquired_at")
            if sentinel.get("health_score") is not None:
                # Blend: prefer Sentinel NDVI health when available for active crops
                if any(k in bhuvan["class_name"].lower() for k in ("agricultur", "crop", "plantation")):
                    computed["health_score"] = sentinel["health_score"]
                    computed["status"] = sentinel.get("status") or st
        try:
            analysis = sentinel_analysis.persist_analysis(db, field, computed)
        except Exception as e:
            db.rollback()
            return {
                "ok": False,
                "completed": False,
                "message": f"Bhuvan result could not be saved: {e}",
            }
        return {
            "ok": True,
            "queued": False,
            "completed": True,
            "source": "bhuvan-lulc-250k",
            "message": (
                f"Bhuvan LULC monitoring saved ({bhuvan['class_name']}"
                + (f", NDVI {computed['indices'].get('NDVI', {}).get('mean', '—')}" if computed.get("indices") else "")
                + ")."
            ),
            "analysis": analysis,
            "bhuvan": bhuvan,
            "note": computed.get("note"),
        }

    # Bhuvan unavailable — full Sentinel fallback
    result = sentinel_analysis.run_for_field(db, field_id)
    if result.get("completed"):
        result["source"] = "copernicus-sentinel2"
        result["message"] = (
            result.get("message") or "Sentinel-2 analysis saved."
        ) + " (Bhuvan LULC unavailable — Sentinel-2 fallback.)"
    return result
