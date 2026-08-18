"""India-wide address search for Add Field / Crop Detection.

Browser Nominatim is blocked (CORS / User-Agent). This proxy queries Photon,
Nominatim, and Open-Meteo and returns Maps-style name + subtitle rows for
any village, city, or PIN in India.
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/geocode", tags=["geocode"])

_TIMEOUT = 4
_INDIA_BBOX = (68.0, 6.5, 97.5, 35.7)  # minLon, minLat, maxLon, maxLat
_HEADERS = {
    "User-Agent": "OatmealFarmNetwork-IN/1.0 (livestockoftheworld@gmail.com)",
    "Accept": "application/json",
}

# Public farms in three states — quick matches, never a geographic filter.
_EXAMPLE_FARMS = [
    {
        "name": "Somashettihalli",
        "subtitle": "Arodi, Koratagere, Tumakuru, Karnataka 572121",
        "display_name": "Somashettihalli, Arodi, Koratagere, Tumakuru, Karnataka 572121, India",
        "lat": 13.54967,
        "lon": 77.33739,
        "source": "farm",
        "aliases": "somashettihalli somashetti arodi koratagere tumakuru tumkur 572121 karnataka",
    },
    {
        "name": "ICRISAT Patancheru",
        "subtitle": "Patancheru, Hyderabad, Telangana 502324",
        "display_name": "ICRISAT, Patancheru, Hyderabad, Telangana 502324, India",
        "lat": 17.5116,
        "lon": 78.2752,
        "source": "farm",
        "aliases": "icrisat patancheru hyderabad telangana 502324",
    },
    {
        "name": "Punjab Agricultural University",
        "subtitle": "Ludhiana, Punjab 141004",
        "display_name": "Punjab Agricultural University, Ludhiana, Punjab 141004, India",
        "lat": 30.9010,
        "lon": 75.8072,
        "source": "farm",
        "aliases": "pau ludhiana punjab 141004 agricultural university",
    },
]


def _india_stack() -> bool:
    return (os.getenv("VITE_OFN_STACK") or os.getenv("OFN_STACK") or "india").lower() == "india"


def _pin(query: str) -> str | None:
    m = re.search(r"\b(\d{6})\b", query or "")
    return m.group(1) if m else None


def _in_india(lat: float, lon: float) -> bool:
    min_lon, min_lat, max_lon, max_lat = _INDIA_BBOX
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def _shape(row: dict[str, Any]) -> dict[str, Any]:
    display = row.get("display_name") or row.get("name") or ""
    name = row.get("name") or (display.split(",")[0].strip() if display else "")
    subtitle = row.get("subtitle") or ",".join(display.split(",")[1:]).strip()
    out = dict(row)
    out["name"] = name
    out["subtitle"] = subtitle
    out["display_name"] = display or ", ".join(x for x in [name, subtitle] if x)
    return out


def _hay(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(k) or "")
        for k in ("name", "subtitle", "display_name", "aliases")
    ).lower()


def _match_farms(q: str) -> list[dict[str, Any]]:
    token = (q or "").strip().lower()
    if not token:
        return [_shape(f) for f in _EXAMPLE_FARMS]
    return [_shape(f) for f in _EXAMPLE_FARMS if token in _hay(f)]


def _rank(row: dict[str, Any], q: str) -> tuple:
    token = (q or "").strip().lower().split(",")[0].strip()
    name = (row.get("name") or "").lower()
    full = _hay(row)
    pin = _pin(q)
    starts = 0 if token and name.startswith(token) else 1
    contains_name = 0 if token and token in name else 1
    contains_full = 0 if token and token in full else 1
    farm = 0 if row.get("source") == "farm" else 1
    pin_hit = 0 if pin and pin in full else 1
    return (starts, contains_name, contains_full, pin_hit, farm)


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


def _nominatim_row(item: dict[str, Any], fallback: str) -> dict[str, Any]:
    addr = item.get("address") or {}
    name = (
        addr.get("village")
        or addr.get("hamlet")
        or addr.get("suburb")
        or addr.get("neighbourhood")
        or addr.get("town")
        or addr.get("city")
        or addr.get("county")
        or (item.get("display_name") or fallback).split(",")[0]
    )
    subtitle = ", ".join(
        x for x in [
            addr.get("county") if addr.get("county") != name else None,
            addr.get("state_district"),
            addr.get("state"),
            addr.get("postcode"),
            addr.get("country") or "India",
        ]
        if x
    )
    return _shape({
        "name": name,
        "subtitle": subtitle,
        "display_name": item.get("display_name") or f"{name}, {subtitle}",
        "lat": float(item["lat"]),
        "lon": float(item["lon"]),
        "source": "nominatim",
    })


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
        return [
            _nominatim_row(item, q)
            for item in (r.json() or [])
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
        return [
            _nominatim_row(item, pin)
            for item in (r.json() or [])
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
            name = p.get("name") or p.get("street") or q
            subtitle = ", ".join(
                x for x in [
                    p.get("street") if p.get("street") and p.get("street") != name else None,
                    p.get("city") or p.get("district") or p.get("county"),
                    p.get("state"),
                    p.get("postcode"),
                    p.get("country"),
                ]
                if x
            )
            out.append(_shape({
                "name": name,
                "subtitle": subtitle,
                "display_name": ", ".join(x for x in [name, subtitle] if x),
                "lat": float(lat),
                "lon": float(lon),
                "source": "photon",
            }))
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
            _shape({
                "name": item.get("name"),
                "subtitle": ", ".join(
                    x for x in [item.get("admin2"), item.get("admin1"), (item.get("country_code") or "").upper()]
                    if x
                ),
                "display_name": ", ".join(
                    x for x in [item.get("name"), item.get("admin1"), (item.get("country_code") or "").upper()]
                    if x
                ),
                "lat": float(item["latitude"]),
                "lon": float(item["longitude"]),
                "source": "openmeteo",
            })
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
        out.append(_shape(r))
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
def geocode_search(q: str = Query(..., min_length=1), limit: int = Query(8, ge=1, le=12)):
    country = "in" if _india_stack() else "us"
    variants = _variants(q)
    if not variants:
        return {"results": _match_farms("")[:limit]}
    pin = _pin(q)
    merged: list[dict[str, Any]] = _match_farms(q)

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [
            ex.submit(_photon, variants[0], 10),
            ex.submit(_open_meteo, variants[0], 6),
        ]
        if pin:
            futs.append(ex.submit(_nominatim_postal, pin, 6))
        else:
            futs.append(ex.submit(_nominatim, variants[0], country, 6))
        merged.extend(_collect(futs))

    rows = _dedupe(merged)
    if len(rows) < 4 and len(variants) > 1:
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

    rows.sort(key=lambda r: _rank(r, q))
    return {"results": rows[:limit]}
