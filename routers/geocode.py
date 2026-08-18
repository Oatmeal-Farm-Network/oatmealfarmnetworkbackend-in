"""Address search for Add Field / Crop Detection maps.

Browser Nominatim calls are blocked (CORS / User-Agent). This proxy queries
Nominatim, Photon, and Open-Meteo server-side and returns a unified list.
India stack prefers India results.
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/geocode", tags=["geocode"])

_TIMEOUT = 8
_INDIA_BBOX = (68.0, 6.5, 97.5, 35.7)  # minLon, minLat, maxLon, maxLat
_HEADERS = {
    "User-Agent": "OatmealFarmNetwork-IN/1.0 (livestockoftheworld@gmail.com)",
    "Accept": "application/json",
}


def _india_stack() -> bool:
    return (os.getenv("VITE_OFN_STACK") or os.getenv("OFN_STACK") or "india").lower() == "india"


def _pin(query: str) -> str | None:
    m = re.search(r"\b(\d{6})\b", query or "")
    return m.group(1) if m else None


def _in_india(lat: float, lon: float) -> bool:
    min_lon, min_lat, max_lon, max_lat = _INDIA_BBOX
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def _variants(query: str) -> list[str]:
    q = (query or "").strip()
    if not q:
        return []
    out = [q]
    first = q.split(",")[0].strip()
    if first and first.lower() not in {x.lower() for x in out}:
        out.append(first)
    pin = _pin(q)
    if pin:
        out.append(f"{pin}, India")
        if first:
            out.append(f"{first}, {pin}, India")
    if _india_stack() and "india" not in q.lower():
        out.append(f"{q}, India")
    seen: set[str] = set()
    uniq: list[str] = []
    for item in out:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq[:5]


def _nominatim(q: str, country: str | None, limit: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "q": q,
        "format": "json",
        "limit": limit,
        "addressdetails": 1,
    }
    if country:
        params["countrycodes"] = country
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        if not r.ok:
            return []
        rows = r.json() or []
        return [
            {
                "display_name": item.get("display_name") or q,
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "source": "nominatim",
            }
            for item in rows
            if item.get("lat") is not None and item.get("lon") is not None
        ]
    except Exception:
        return []


def _nominatim_postal(pin: str, limit: int) -> list[dict[str, Any]]:
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "postalcode": pin,
                "country": "India" if _india_stack() else "USA",
                "format": "json",
                "limit": limit,
                "addressdetails": 1,
            },
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        if not r.ok:
            return []
        rows = r.json() or []
        return [
            {
                "display_name": item.get("display_name") or pin,
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "source": "nominatim-pin",
            }
            for item in rows
            if item.get("lat") is not None and item.get("lon") is not None
        ]
    except Exception:
        return []


def _photon(q: str, limit: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"q": q, "limit": limit, "lang": "en"}
    if _india_stack():
        min_lon, min_lat, max_lon, max_lat = _INDIA_BBOX
        params["bbox"] = f"{min_lon},{min_lat},{max_lon},{max_lat}"
    try:
        r = requests.get(
            "https://photon.komoot.io/api/",
            params=params,
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        if not r.ok:
            return []
        features = (r.json() or {}).get("features") or []
        out = []
        for f in features:
            p = f.get("properties") or {}
            coords = (f.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            lon, lat = coords[0], coords[1]
            parts = [
                p.get("name"),
                p.get("street"),
                p.get("city") or p.get("district") or p.get("county"),
                p.get("state"),
                p.get("postcode"),
                p.get("country"),
            ]
            out.append({
                "display_name": ", ".join(x for x in parts if x) or p.get("name") or q,
                "lat": float(lat),
                "lon": float(lon),
                "source": "photon",
            })
        return out
    except Exception:
        return []


def _open_meteo(q: str, limit: int) -> list[dict[str, Any]]:
    name = q.split(",")[0].strip()
    if len(name) < 2:
        return []
    params: dict[str, Any] = {
        "name": name,
        "count": limit,
        "language": "en",
        "format": "json",
    }
    if _india_stack():
        params["countryCode"] = "IN"
    try:
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params=params,
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        if not r.ok:
            return []
        rows = (r.json() or {}).get("results") or []
        return [
            {
                "display_name": ", ".join(
                    x for x in [item.get("name"), item.get("admin1"), (item.get("country_code") or "").upper()]
                    if x
                ),
                "lat": float(item["latitude"]),
                "lon": float(item["longitude"]),
                "source": "openmeteo",
            }
            for item in rows
            if item.get("latitude") is not None
        ]
    except Exception:
        return []


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            lat = float(r["lat"])
            lon = float(r["lon"])
            key = f"{lat:.4f},{lon:.4f}"
        except (TypeError, ValueError, KeyError):
            continue
        if _india_stack() and not _in_india(lat, lon):
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _collect(futs) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fut in as_completed(futs):
        try:
            out.extend(fut.result() or [])
        except Exception:
            pass
    return out


@router.get("/search")
def geocode_search(q: str = Query(..., min_length=2), limit: int = Query(6, ge=1, le=12)):
    country = "in" if _india_stack() else "us"
    variants = _variants(q)
    if not variants:
        return {"results": []}
    pin = _pin(q)
    merged: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [
            ex.submit(_photon, variants[0], 8),
            ex.submit(_open_meteo, variants[0], 5),
        ]
        if pin:
            futs.append(ex.submit(_nominatim_postal, pin, 6))
        else:
            futs.append(ex.submit(_nominatim, variants[0], country, 6))
        merged.extend(_collect(futs))

    rows = _dedupe(merged)
    if len(rows) < 2 and len(variants) > 1:
        with ThreadPoolExecutor(max_workers=3) as ex:
            extra = _collect([
                ex.submit(_photon, variants[1], 8),
                ex.submit(_nominatim, variants[1], country, 6),
                ex.submit(_open_meteo, variants[1], 4),
            ])
        rows = _dedupe(merged + extra)
        merged.extend(extra)

    if len(rows) < 2:
        rows = _dedupe(merged + _nominatim(variants[0], None, 6))

    first = q.lower().split(",")[0].strip()
    rows.sort(key=lambda r: (
        0 if first and first in (r.get("display_name") or "").lower() else 1,
        0 if pin and pin in (r.get("display_name") or "") else 1,
    ))
    return {"results": rows[:limit]}
