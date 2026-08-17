"""
Screening-grade terrain stand-ins when CropMonitor has no /terrain/* routes.

Produces the same response shapes the Field Twin expects (metadata, elevation
grid, water-risk PNG + hotspots) using the field's lat/lon / boundary.

Elevation prefers Open-Meteo sampled DEM (real heights, coarse grid, bilinear
upsample). When that fails, uses a gentle bowl around a single pin elevation —
never claims lidar/survey accuracy.
"""
from __future__ import annotations

import base64
import io
import json
import math
from typing import Any, Optional

import requests
from PIL import Image

OPEN_METEO_ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
_ELEV_BATCH = 100
_ELEV_SAMPLE_MAX = 12  # sample up to 12×12 then upsample


DEFAULT_PRESETS = [
    {
        "id": "forecast_storm",
        "label": "Forecast storm (48h)",
        "rainfall_mm": 25,
        "irrigation_mm": 0,
        "duration_hours": 6,
        "infiltration_class": "moderate",
        "antecedent": "normal",
    },
    {
        "id": "heavy_rain",
        "label": "Monsoon burst (~80 mm)",
        "rainfall_mm": 80,
        "irrigation_mm": 0,
        "duration_hours": 6,
        "infiltration_class": "moderate",
        "antecedent": "wet",
    },
    {
        "id": "monsoon_heavy",
        "label": "Heavy monsoon (~150 mm)",
        "rainfall_mm": 150,
        "irrigation_mm": 0,
        "duration_hours": 8,
        "infiltration_class": "moderate",
        "antecedent": "wet",
    },
    {
        "id": "rain_only",
        "label": "Moderate rain (~50 mm)",
        "rainfall_mm": 50,
        "irrigation_mm": 0,
        "duration_hours": 6,
        "infiltration_class": "moderate",
        "antecedent": "wet",
    },
    {
        "id": "after_irrigate",
        "label": "After 40 mm canal/borewell",
        "rainfall_mm": 10,
        "irrigation_mm": 40,
        "duration_hours": 8,
        "infiltration_class": "moderate",
        "antecedent": "normal",
    },
    {
        "id": "light_rain",
        "label": "Light rain",
        "rainfall_mm": 15,
        "irrigation_mm": 0,
        "duration_hours": 4,
        "infiltration_class": "moderate",
        "antecedent": "normal",
    },
]


def _f(v) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _bbox_from_field(field) -> Optional[list[float]]:
    """Return [west, south, east, north] from boundary or a small box around the pin."""
    raw = getattr(field, "BoundaryGeoJSON", None) or getattr(field, "boundary_geojson", None)
    if raw:
        try:
            gj = json.loads(raw) if isinstance(raw, str) else raw
            coords = []
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
    # ~400 m box around pin when boundary missing
    dlat = 0.002
    dlon = 0.002 / max(0.2, math.cos(math.radians(lat)))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def _mulberry(seed: int):
    t = seed & 0xFFFFFFFF

    def rand():
        nonlocal t
        t = (t + 0x6D2B79F5) & 0xFFFFFFFF
        r = ((t ^ (t >> 15)) * (1 | t)) & 0xFFFFFFFF
        r ^= (r + (((r ^ (r >> 7)) * (61 | r)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((r ^ (r >> 14)) & 0xFFFFFFFF) / 4294967296.0

    return rand


def _bilinear(grid: list[list[float]], rows: int, cols: int) -> list[list[float]]:
    """Upsample a coarse height grid to rows×cols with bilinear interpolation."""
    src_r = len(grid)
    src_c = len(grid[0]) if grid else 0
    if src_r < 1 or src_c < 1:
        return [[0.0] * cols for _ in range(rows)]
    if src_r == rows and src_c == cols:
        return grid
    out: list[list[float]] = []
    for y in range(rows):
        row = []
        fy = y * (src_r - 1) / max(1, rows - 1)
        y0 = int(fy)
        y1 = min(src_r - 1, y0 + 1)
        ty = fy - y0
        for x in range(cols):
            fx = x * (src_c - 1) / max(1, cols - 1)
            x0 = int(fx)
            x1 = min(src_c - 1, x0 + 1)
            tx = fx - x0
            v00 = grid[y0][x0]
            v10 = grid[y0][x1]
            v01 = grid[y1][x0]
            v11 = grid[y1][x1]
            v0 = v00 * (1 - tx) + v10 * tx
            v1 = v01 * (1 - tx) + v11 * tx
            row.append(v0 * (1 - ty) + v1 * ty)
        out.append(row)
    return out


def _openmeteo_elevations(lats: list[float], lons: list[float], timeout: float = 20.0) -> Optional[list[float]]:
    """Batch Open-Meteo elevation lookups (≤100 points per request)."""
    if not lats or not lons or len(lats) != len(lons):
        return None
    out: list[float] = []
    try:
        for i in range(0, len(lats), _ELEV_BATCH):
            batch_lat = lats[i : i + _ELEV_BATCH]
            batch_lon = lons[i : i + _ELEV_BATCH]
            r = requests.get(
                OPEN_METEO_ELEVATION_URL,
                params={
                    "latitude": ",".join(f"{v:.6f}" for v in batch_lat),
                    "longitude": ",".join(f"{v:.6f}" for v in batch_lon),
                },
                timeout=timeout,
            )
            if not r.ok:
                return None
            elev = (r.json() or {}).get("elevation")
            if not isinstance(elev, list) or len(elev) != len(batch_lat):
                return None
            out.extend(float(v) for v in elev)
        return out
    except Exception:
        return None


def sample_openmeteo_elevation_grid(
    bbox: list[float],
    grid: int,
    *,
    sample_max: int = _ELEV_SAMPLE_MAX,
    timeout: float = 25.0,
) -> Optional[dict[str, Any]]:
    """
    Build a rows×cols elevation grid from Open-Meteo DEM samples over the bbox.
    Returns None when the API is unreachable.
    """
    if not bbox or len(bbox) != 4:
        return None
    west, south, east, north = bbox
    if east <= west or north <= south:
        return None
    size = max(32, min(int(grid or 64), 256))
    sample_n = max(2, min(sample_max, size))
    lats: list[float] = []
    lons: list[float] = []
    for ry in range(sample_n):
        # row 0 = north (match twin convention used elsewhere)
        lat = north - ((ry + 0.5) / sample_n) * (north - south)
        for cx in range(sample_n):
            lon = west + ((cx + 0.5) / sample_n) * (east - west)
            lats.append(lat)
            lons.append(lon)
    elevs = _openmeteo_elevations(lats, lons, timeout=timeout)
    if elevs is None:
        return None
    coarse = [
        elevs[ry * sample_n : (ry + 1) * sample_n]
        for ry in range(sample_n)
    ]
    values = _bilinear(coarse, size, size)
    flat = [v for row in values for v in row]
    zmin, zmax = min(flat), max(flat)
    zmean = sum(flat) / len(flat)
    return {
        "values": values,
        "rows": size,
        "cols": size,
        "bbox": bbox,
        "units": "meters",
        "summary": {
            "min_m": round(zmin, 2),
            "max_m": round(zmax, 2),
            "mean_m": round(zmean, 2),
            "relief_m": round(zmax - zmin, 2),
        },
        "source": "open_meteo_elevation",
        "provenance": "derived",
        "confidence": "medium",
        "sample_grid": sample_n,
        "limitations": [
            "Heights from Open-Meteo elevation DEM at a coarse sample, bilinear-upsampled — "
            "not survey/lidar. Suitable for relative slope/driveability screening.",
        ],
    }


def build_bowl_elevation(field, grid: int = 64) -> dict[str, Any]:
    """Gentle bowl DEM around pin elevation when Open-Meteo is unavailable."""
    size = max(32, min(int(grid or 64), 256))
    bbox = _bbox_from_field(field)
    lat = _f(getattr(field, "Latitude", None))
    lon = _f(getattr(field, "Longitude", None))
    pin_z = 0.0
    if lat is not None and lon is not None:
        one = _openmeteo_elevations([lat], [lon], timeout=12.0)
        if one:
            pin_z = float(one[0])
    fid = int(getattr(field, "FieldID", 0) or 0)
    rand = _mulberry(fid * 7919 + 17)
    values: list[list[float]] = []
    for y in range(size):
        row = []
        for x in range(size):
            nx = x / size - 0.5
            ny = y / size - 0.5
            bowl = (nx * nx + ny * ny) * 6.0  # meters of relative relief
            micro = (rand() - 0.5) * 0.4
            row.append(pin_z + bowl + micro)
        values.append(row)
    flat = [v for row in values for v in row]
    zmin, zmax = min(flat), max(flat)
    return {
        "values": values,
        "rows": size,
        "cols": size,
        "bbox": bbox,
        "units": "meters",
        "summary": {
            "min_m": round(zmin, 2),
            "max_m": round(zmax, 2),
            "mean_m": round(sum(flat) / len(flat), 2),
            "relief_m": round(zmax - zmin, 2),
        },
        "source": "screening_bowl",
        "provenance": "modeled",
        "confidence": "low",
        "limitations": [
            "Modeled bowl DEM around a single pin height — not a real terrain surface. "
            "Use only until a survey/DEM package is available.",
        ],
    }


def build_screening_elevation(field, grid: int = 64) -> dict[str, Any]:
    """Prefer Open-Meteo DEM; fall back to a labeled bowl stand-in."""
    bbox = _bbox_from_field(field)
    if bbox:
        real = sample_openmeteo_elevation_grid(bbox, grid)
        if real:
            return real
    return build_bowl_elevation(field, grid)


def build_screening_metadata(field, field_id: int, grid: int = 64) -> dict[str, Any]:
    """Terrain package metadata the twin expects when CropMonitor has no /terrain/*."""
    size = max(32, min(int(grid or 64), 256))
    bbox = _bbox_from_field(field)
    lat = _f(getattr(field, "Latitude", None))
    lon = _f(getattr(field, "Longitude", None))
    # Prefer a cheap Open-Meteo summary (coarse sample); fall back to pin height.
    elev_summary = None
    elev_source = "screening_local"
    elev_provenance = "modeled"
    elev_confidence = "low"
    elev_limitations: list[str] = []
    if bbox:
        sampled = sample_openmeteo_elevation_grid(bbox, min(32, size), sample_max=6, timeout=18.0)
        if sampled:
            elev_summary = sampled.get("summary")
            elev_source = sampled.get("source") or elev_source
            elev_provenance = sampled.get("provenance") or "derived"
            elev_confidence = sampled.get("confidence") or "medium"
            elev_limitations = list(sampled.get("limitations") or [])
    if elev_summary is None and lat is not None and lon is not None:
        one = _openmeteo_elevations([lat], [lon], timeout=10.0)
        if one:
            z = float(one[0])
            elev_summary = {"min_m": z, "max_m": z, "mean_m": z, "relief_m": 0.0}
            elev_source = "open_meteo_elevation"
            elev_provenance = "derived"
            elev_confidence = "medium"
            elev_limitations = [
                "Pin-only Open-Meteo elevation in metadata — full grid sampled when elevation asset is fetched.",
            ]
    return {
        "available": True,
        "source": elev_source,
        "grid": {"rows": size, "cols": size, "bbox": bbox},
        "centroid": {"lat": lat, "lon": lon} if lat is not None and lon is not None else None,
        "boundary": {"bbox": bbox} if bbox else None,
        "elevation": {
            "summary": elev_summary,
            "source": elev_source,
            "provenance": elev_provenance,
            "confidence": elev_confidence,
            "limitations": elev_limitations or [
                "Elevation asset uses Open-Meteo DEM (or a labeled bowl stand-in if DEM fails).",
            ],
        },
        "slope": {
            "note": "Slope derived client-side from elevation grid when available.",
            "source": elev_source,
        },
        "texture": {
            "source": "sentinel-2-l2a",
            "note": (
                "Natural-color texture served from CropMonitor Sentinel-2 RGB heatmap "
                "when available; otherwise a solid stand-in."
            ),
        },
        "overlays_available": ["ndvi", "ndwi", "wetness-risk"],
        "notes": [
            "DEM/NDVI served via main-backend screening + CropMonitor raster fallbacks "
            "(CropMonitor has no native /terrain/* routes).",
        ],
        "field_id": field_id,
    }


def build_vegetation_overlay_json(
    field,
    field_id: int,
    layer: str,
    grid: int = 64,
    db=None,
) -> dict[str, Any]:
    """
    NDVI/NDWI JSON grid for Field Twin when CropMonitor raster/overlay is unavailable.
    Uses latest dbo.VegetationIndex mean when present; otherwise a labeled screening grid.
    """
    layer_key = (layer or "ndvi").strip().lower()
    idx_name = layer_key.upper()
    if idx_name not in {"NDVI", "NDWI", "NDRE", "EVI", "GNDVI", "MSAVI"}:
        idx_name = "NDVI"
    size = max(32, min(int(grid or 64), 256))
    bbox = _bbox_from_field(field)

    mean: Optional[float] = None
    vmin: Optional[float] = None
    vmax: Optional[float] = None
    source = "screening_estimated"
    image_date = None

    if db is not None:
        try:
            from sqlalchemy import text as sa_text

            row = db.execute(
                sa_text("""
                    SELECT TOP 1 v.MeanValue, v.MinValue, v.MaxValue, a.AnalysisDate
                      FROM dbo.Analysis a
                      INNER JOIN dbo.VegetationIndex v ON v.AnalysisID = a.AnalysisID
                     WHERE a.FieldID = :fid AND v.IndexType = :idx
                     ORDER BY a.AnalysisDate DESC
                """),
                {"fid": int(field_id), "idx": idx_name},
            ).fetchone()
            if row is not None and row[0] is not None:
                mean = float(row[0])
                vmin = float(row[1]) if row[1] is not None else mean - 0.1
                vmax = float(row[2]) if row[2] is not None else mean + 0.1
                source = "local_analysis"
                ad = row[3]
                if ad is not None:
                    image_date = ad.isoformat() if hasattr(ad, "isoformat") else str(ad)
        except Exception:
            pass

    if mean is None:
        mean = 0.22 if idx_name == "NDVI" else (-0.05 if idx_name == "NDWI" else 0.2)
        vmin = mean - 0.12
        vmax = mean + 0.12

    lo = float(vmin if vmin is not None else mean - 0.1)
    hi = float(vmax if vmax is not None else mean + 0.1)
    span = max(0.02, hi - lo)
    rand = _mulberry(int(field_id) * 9973 + sum(ord(c) for c in idx_name))
    values: list[list[float]] = []
    for ry in range(size):
        row_vals: list[float] = []
        for cx in range(size):
            nx = cx / size - 0.5
            ny = ry / size - 0.5
            noise = (rand() + rand() + rand() - 1.5) * span * 0.12
            patch = math.sin(nx * 8.0 + field_id) * math.cos(ny * 7.0 + field_id) * span * 0.18
            v = mean + noise + patch
            if idx_name == "NDVI":
                v = max(-0.1, min(0.95, v))
            else:
                v = max(-0.8, min(0.8, v))
            row_vals.append(round(v, 4))
        values.append(row_vals)

    limitations = (
        ["Spatial pattern is illustrative screening — not a Sentinel pixel map."]
        if source == "screening_estimated"
        else [
            "Mean index from stored satellite analysis; cell pattern is upsampled for 3D display only.",
        ]
    )

    return {
        "values": values,
        "rows": size,
        "cols": size,
        "bbox": bbox,
        "index": idx_name,
        "image_date": image_date,
        "source": source,
        "provenance": "derived" if source == "local_analysis" else "modeled",
        "confidence": "medium" if source == "local_analysis" else "low",
        "limitations": limitations,
    }


def build_screening_texture_png(size: int = 128) -> bytes:
    """Solid olive PNG so texture requests do not hard-404 the twin."""
    size = max(16, min(int(size or 128), 256))
    img = Image.new("RGB", (size, size), (92, 122, 68))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_screening_presets(forecast_mm: Optional[float] = None) -> dict:
    presets = [dict(p) for p in DEFAULT_PRESETS]
    if forecast_mm is not None:
        for p in presets:
            if p["id"] == "forecast_storm":
                p["rainfall_mm"] = max(0.0, float(forecast_mm))
    return {
        "presets": presets,
        "forecast_precip_mm_48h": forecast_mm,
        "source": "screening_local",
        "note": "CropMonitor terrain presets unavailable — using local screening presets.",
    }


def build_screening_simulate_water(field, body: dict | None = None) -> dict[str, Any]:
    """Build a screening simulate-water payload for Field Twin playback."""
    body = dict(body or {})
    rain = float(body.get("rainfall_mm") or 0)
    irrig = float(body.get("irrigation_mm") or 0)
    duration = float(body.get("duration_hours") or 6)
    size = int(body.get("grid") or 96)
    size = max(32, min(128, size))
    include_png = body.get("include_png", True) is not False

    water = min(1.0, (rain + irrig) / 80.0)
    infil = str(body.get("infiltration_class") or "moderate").lower()
    ante = str(body.get("antecedent") or "normal").lower()
    infil_mul = {
        "very_slow": 1.25, "slow": 1.1, "moderate": 1.0, "fast": 0.85, "very_fast": 0.7,
    }.get(infil, 1.0)
    ante_mul = {"dry": 0.85, "normal": 1.0, "wet": 1.15, "saturated": 1.3}.get(ante, 1.0)
    water = min(1.0, water * infil_mul * ante_mul)

    fid = int(getattr(field, "FieldID", 0) or body.get("field_id") or 0)
    rand = _mulberry(fid * 9973 + int(rain * 10) + int(irrig * 7))
    bbox = _bbox_from_field(field)
    west = south = east = north = None
    if bbox:
        west, south, east, north = bbox

    risk_grid: list[list[float]] = []
    pixels = bytearray(size * size * 4)
    for y in range(size):
        row = []
        for x in range(size):
            nx = x / size - 0.5
            ny = y / size - 0.5
            bowl = max(0.0, 1.0 - math.hypot(nx * 1.6, ny * 1.6))
            noise = rand() * 0.35
            risk = min(1.0, max(0.0, water * 0.55 + bowl * 0.35 + noise * 0.25))
            row.append(risk)
            i = (y * size + x) * 4
            pixels[i] = int(30 + risk * 220)
            pixels[i + 1] = int(80 + (1 - abs(risk - 0.45) * 2) * 140)
            pixels[i + 2] = int(200 - risk * 180)
            pixels[i + 3] = int(90 + risk * 140)
        risk_grid.append(row)

    hotspots = []
    for _ in range(8):
        row_i = int(rand() * size)
        col_i = int(rand() * size)
        risk = risk_grid[row_i][col_i]
        lat = lon = None
        if west is not None:
            lon = west + ((col_i + 0.5) / size) * (east - west)
            lat = north - ((row_i + 0.5) / size) * (north - south)
        band = "severe" if risk > 0.75 else "high" if risk > 0.55 else "moderate"
        hotspots.append({
            "row": row_i,
            "col": col_i,
            "grid_rows": size,
            "grid_cols": size,
            "risk": round(risk, 2),
            "band": band,
            "latitude": lat,
            "longitude": lon,
        })
    hotspots.sort(key=lambda h: h["risk"], reverse=True)
    hotspots = hotspots[:5]

    flat = [v for row in risk_grid for v in row]
    mean = sum(flat) / len(flat) if flat else 0.0
    high_frac = sum(1 for v in flat if v > 0.55) / len(flat) if flat else 0.0
    severe_frac = sum(1 for v in flat if v > 0.75) / len(flat) if flat else 0.0
    hectares = _f(getattr(field, "FieldSizeHectares", None)) or 0.0
    access = "high" if mean > 0.65 else "moderate" if mean > 0.4 else "low"

    overlay_b64 = None
    if include_png:
        img = Image.frombytes("RGBA", (size, size), bytes(pixels))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        overlay_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return {
        "overlay_png_base64": overlay_b64,
        "overlay_mime": "image/png",
        "hotspots": hotspots,
        "summary": {
            "mean_risk": round(mean, 2),
            "access_risk": access,
            "areas_ha": {
                "high": round(hectares * high_frac, 2) if hectares else 0,
                "severe": round(hectares * severe_frac, 2) if hectares else 0,
            },
            "affected_area_ac": {
                "high": round(hectares * high_frac * 2.471, 2) if hectares else 0,
                "severe": round(hectares * severe_frac * 2.471, 2) if hectares else 0,
            },
        },
        "confidence": {"grade": "screening"},
        "accuracy_statement": (
            "Screening-grade relative water/access risk — DEM simulator unavailable. "
            "Not flood depth. Verify on site before changing traffic or irrigation."
        ),
        "fallback": True,
        "fallback_reason": "cropmonitor_terrain_unavailable",
        "source": "screening_local",
        "bbox": bbox,
        "grid": {"rows": size, "cols": size},
        "scenario": {
            "rainfall_mm": rain,
            "irrigation_mm": irrig,
            "duration_hours": duration,
            "infiltration_class": infil,
            "antecedent": ante,
            "preset_id": body.get("preset_id") or "custom",
        },
        "inputs": {
            "rainfall_mm": rain,
            "irrigation_mm": irrig,
            "duration_hours": duration,
            "infiltration_class": infil,
            "antecedent": ante,
        },
    }
