"""
Geometry helpers — pure-Python, no GIS dependencies.

`polygon_area_hectares()` consumes the same GeoJSON shapes the precision-ag
front-end stores in Field.BoundaryGeoJSON (Feature, FeatureCollection,
Polygon, or MultiPolygon — and accepts either a JSON string or a parsed
dict) and returns the WGS84 surface area in hectares.

We use the spherical-excess approximation on a sphere of WGS84 equatorial
radius. For typical farm-field polygons (a few hundred meters on a side)
this matches geodesic libraries within ~0.1%, which is well below the
positional accuracy of a hand-drawn boundary.
"""
from __future__ import annotations

import json
import math
from typing import Any, Iterable, List, Optional, Tuple

_R_EARTH_M = 6378137.0        # WGS84 equatorial radius
_M2_PER_HECTARE = 10_000.0


def _ring_area_m2(ring: Iterable[Tuple[float, float]]) -> float:
    """Spherical-excess area of one closed [lon, lat] ring, in m²."""
    pts = [(float(lon), float(lat)) for lon, lat in ring]
    if len(pts) < 3:
        return 0.0
    if pts[0] != pts[-1]:
        pts.append(pts[0])

    total = 0.0
    for i in range(len(pts) - 1):
        lon1, lat1 = pts[i]
        lon2, lat2 = pts[i + 1]
        total += math.radians(lon2 - lon1) * (
            2.0 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2))
        )
    return abs(total * _R_EARTH_M * _R_EARTH_M / 2.0)


def _polygon_area_m2(polygon_coords: List[List[List[float]]]) -> float:
    """A GeoJSON Polygon: outer ring then zero or more holes."""
    if not polygon_coords:
        return 0.0
    outer = _ring_area_m2(polygon_coords[0])
    holes = sum(_ring_area_m2(r) for r in polygon_coords[1:])
    return max(outer - holes, 0.0)


def _geometry_area_m2(geom: dict) -> float:
    if not isinstance(geom, dict):
        return 0.0
    gtype = (geom.get("type") or "").lower()
    coords = geom.get("coordinates")
    if not coords:
        return 0.0
    if gtype == "polygon":
        return _polygon_area_m2(coords)
    if gtype == "multipolygon":
        return sum(_polygon_area_m2(p) for p in coords)
    return 0.0


def polygon_area_hectares(geojson: Any) -> Optional[float]:
    """Convert any GeoJSON-shaped input into hectares. Returns `None` when the
    input is missing/invalid so the caller can fall back to user input."""
    if geojson is None or geojson == "":
        return None

    data = geojson
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            return None
    if not isinstance(data, dict):
        return None

    dtype = (data.get("type") or "").lower()
    geometries: List[dict] = []
    if dtype == "featurecollection":
        for feat in data.get("features") or []:
            if isinstance(feat, dict) and isinstance(feat.get("geometry"), dict):
                geometries.append(feat["geometry"])
    elif dtype == "feature":
        if isinstance(data.get("geometry"), dict):
            geometries.append(data["geometry"])
    elif dtype in ("polygon", "multipolygon"):
        geometries.append(data)
    else:
        return None

    total_m2 = sum(_geometry_area_m2(g) for g in geometries)
    if total_m2 <= 0:
        return None
    return round(total_m2 / _M2_PER_HECTARE, 2)
