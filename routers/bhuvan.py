"""ISRO Bhuvan LULC proxy for India Crop Detection.

Bhuvan WMS has no CORS headers, so the browser cannot fetch tiles or
GetFeatureInfo directly. This router proxies national LULC 250K only —
no API key required.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

router = APIRouter(prefix="/api/bhuvan", tags=["bhuvan"])

BHUVAN_WMS = "https://bhuvan-ras2.nrsc.gov.in/cgi-bin/LULC250K.exe"
BHUVAN_LAYER = "LULC250K_2425"
BHUVAN_YEAR = "2024–25"
ORIGIN_SHIFT = 20037508.342789244
TILE_SIZE = 256
_TIMEOUT = 45
_UA = "OatmealFarmNetwork-IN/1.0 (livestockoftheworld@gmail.com)"

_KNOWN = [
    "Built-Up", "Built Up", "Builtup",
    "Agricultural Land", "Agriculture", "Cropland", "Crop Land",
    "Plantation", "Orchard",
    "Forest", "Deciduous", "Evergreen",
    "Grassland", "Grazing",
    "Wasteland", "Barren", "Scrub",
    "Waterbodies", "Water Bodies", "Water Body", "Water",
    "Wetlands", "Wetland",
    "Snow", "Glacier",
]


def _tile_to_mercator_bbox(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    res = (2 * ORIGIN_SHIFT) / (TILE_SIZE * (2 ** z))
    min_x = x * TILE_SIZE * res - ORIGIN_SHIFT
    max_y = ORIGIN_SHIFT - y * TILE_SIZE * res
    max_x = (x + 1) * TILE_SIZE * res - ORIGIN_SHIFT
    min_y = ORIGIN_SHIFT - (y + 1) * TILE_SIZE * res
    return min_x, min_y, max_x, max_y


def _parse_lulc_class(html_or_text: str) -> str | None:
    raw = re.sub(r"<[^>]+>", " ", html_or_text or "")
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return None
    lower = raw.lower()
    for k in _KNOWN:
        if k.lower() in lower:
            if k.lower().startswith("built"):
                return "Built-Up"
            return k
    m = re.search(r"[A-Za-z][A-Za-z\- /]{2,40}", raw)
    return m.group(0).strip() if m else raw[:40]


def _bhuvan_get(params: dict) -> tuple[int, bytes, str]:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{BHUVAN_WMS}?{qs}",
        headers={"User-Agent": _UA, "Accept": "*/*"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            ctype = resp.headers.get("Content-Type", "application/octet-stream")
            return resp.status, resp.read(), ctype
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b"", ""
    except urllib.error.URLError as e:
        raise HTTPException(status_code=502, detail=f"Bhuvan unreachable: {e}") from e


@router.get("/tile/{z}/{x}/{y}.png")
def lulc_tile(z: int, x: int, y: int):
    """Web Mercator raster tile from Bhuvan national LULC GetMap."""
    if z < 0 or z > 14 or x < 0 or y < 0 or x >= 2**z or y >= 2**z:
        raise HTTPException(status_code=400, detail="Invalid tile coordinates")
    min_x, min_y, max_x, max_y = _tile_to_mercator_bbox(z, x, y)
    status, body, _ = _bhuvan_get({
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetMap",
        "LAYERS": BHUVAN_LAYER,
        "STYLES": "",
        "SRS": "EPSG:3857",
        "BBOX": f"{min_x},{min_y},{max_x},{max_y}",
        "WIDTH": str(TILE_SIZE),
        "HEIGHT": str(TILE_SIZE),
        "FORMAT": "image/png",
        "TRANSPARENT": "TRUE",
    })
    if status != 200 or not body.startswith(b"\x89PNG"):
        raise HTTPException(status_code=502, detail="Bhuvan GetMap failed")
    return Response(
        content=body,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/identify")
def identify(
    lon: float = Query(..., ge=68.0, le=98.0),
    lat: float = Query(..., ge=6.0, le=37.0),
):
    """LULC class at lon/lat via Bhuvan GetFeatureInfo (JSON)."""
    d = 0.12
    status, body, _ = _bhuvan_get({
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": BHUVAN_LAYER,
        "QUERY_LAYERS": BHUVAN_LAYER,
        "STYLES": "",
        "SRS": "EPSG:4326",
        "BBOX": f"{lon - d},{lat - d},{lon + d},{lat + d}",
        "WIDTH": "256",
        "HEIGHT": "256",
        "X": "128",
        "Y": "128",
        "INFO_FORMAT": "text/html",
        "FEATURE_COUNT": "5",
    })
    if status != 200:
        raise HTTPException(status_code=502, detail="Bhuvan GetFeatureInfo failed")
    text = body.decode("utf-8", errors="replace")
    klass = _parse_lulc_class(text)
    return {
        "class_name": klass,
        "layer": BHUVAN_LAYER,
        "year_label": BHUVAN_YEAR,
        "source": "bhuvan-lulc-250k",
    }


@router.get("/legend.png")
def legend():
    """Official Bhuvan GetLegendGraphic PNG."""
    status, body, _ = _bhuvan_get({
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetLegendGraphic",
        "LAYER": BHUVAN_LAYER,
        "FORMAT": "image/png",
    })
    if status != 200:
        raise HTTPException(status_code=502, detail="Bhuvan legend failed")
    return Response(
        content=body,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=604800"},
    )
