"""
Google Earth Engine helper — fetch a recent cloud-free Sentinel-2 RGB thumbnail
for a field's bounding geometry and return a URL the biomass estimator can read.

Requires:
  pip install earthengine-api
  env GEE_SERVICE_ACCOUNT=svc@project.iam.gserviceaccount.com
  env GEE_KEY_FILE=/path/to/key.json  (or GOOGLE_APPLICATION_CREDENTIALS)

On any failure (not installed / not configured / no imagery) returns None.
Callers should handle None → HTTP 503 "satellite imagery unavailable".
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Optional


_initialized = False
_last_init_error: Optional[str] = None


def is_available() -> bool:
    """Public check — returns True only if GEE is initialized and callable."""
    return _ensure_initialized()


def last_init_error() -> Optional[str]:
    """Why the last init attempt failed, or None if no attempt / success."""
    return _last_init_error


def _ensure_initialized() -> bool:
    global _initialized, _last_init_error
    if _initialized:
        return True
    try:
        import ee  # type: ignore
    except ImportError as e:
        _last_init_error = f"earthengine-api package not installed: {e}"
        return False

    svc_account = os.getenv("GEE_SERVICE_ACCOUNT")
    key_file = os.getenv("GEE_KEY_FILE") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    project = os.getenv("GEE_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
    # If svc_account wasn't set but the key file is a service-account JSON, pull
    # the email from it so the user only has to configure GOOGLE_APPLICATION_CREDENTIALS.
    if key_file and not svc_account:
        try:
            with open(key_file) as f:
                info = json.load(f)
            svc_account = info.get("client_email")
            if not project:
                project = info.get("project_id")
        except Exception as e:
            print(f"[gee_helper] could not parse key file {key_file}: {e}")
    try:
        init_kwargs = {}
        if svc_account and key_file:
            init_kwargs["credentials"] = ee.ServiceAccountCredentials(svc_account, key_file)
        if project:
            init_kwargs["project"] = project
        ee.Initialize(**init_kwargs)
        _initialized = True
        _last_init_error = None
        return True
    except Exception as e:
        _last_init_error = f"{type(e).__name__}: {e}"
        print(f"[gee_helper] init failed: {_last_init_error}")
        return False


def get_sentinel2_thumbnail_url(
    latitude: Optional[float],
    longitude: Optional[float],
    boundary_geojson: Optional[str] = None,
    days_back: int = 60,
    buffer_meters: int = 250,
    max_cloud_pct: int = 40,
) -> Optional[dict]:
    """
    Returns {"url": str, "captured_at": iso} for the most recent Sentinel-2 L2A
    RGB composite. Tries progressively looser cloud / time filters until hits
    are found, so sites with consistently cloudy weather still get imagery.
    """
    if not _ensure_initialized():
        print("[gee_helper] initialization failed")
        return None
    try:
        import ee  # type: ignore

        geom = None
        if boundary_geojson:
            try:
                geom = ee.Geometry(json.loads(boundary_geojson))
            except Exception as e:
                print(f"[gee_helper] boundary_geojson unparseable ({e}) — falling back to point")

        if geom is None:
            if latitude is None or longitude is None:
                print("[gee_helper] no lat/lon and no usable boundary — aborting")
                return None
            geom = ee.Geometry.Point([float(longitude), float(latitude)]).buffer(buffer_meters)

        # Progressive loosening: (days, cloud_pct)
        attempts = [
            (days_back, max_cloud_pct),
            (days_back * 2, max_cloud_pct + 20),
            (days_back * 3, 90),
        ]
        end = datetime.utcnow()
        image = None
        used = None
        for days, clouds in attempts:
            start = end - timedelta(days=days)
            coll = (
                ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterBounds(geom)
                .filterDate(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", clouds))
                .sort("system:time_start", False)
            )
            size = coll.size().getInfo()
            print(f"[gee_helper] lat={latitude} lon={longitude} window={days}d clouds<{clouds}% → {size} image(s)")
            if size:
                image = ee.Image(coll.first())
                used = {"days": days, "clouds": clouds, "count": size}
                break

        if image is None:
            return None

        captured_ms = image.get("system:time_start").getInfo()
        captured_at = datetime.utcfromtimestamp(captured_ms / 1000).isoformat() + "Z"

        vis = {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000, "gamma": 1.1}
        url = image.clip(geom).getThumbURL({**vis, "region": geom, "dimensions": 512, "format": "png"})
        print(f"[gee_helper] selected image captured_at={captured_at} via {used}")
        return {"url": url, "captured_at": captured_at}
    except Exception as e:
        print(f"[gee_helper] fetch failed: {e}")
        return None
