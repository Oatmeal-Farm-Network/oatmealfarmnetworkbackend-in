"""Terrain metadata: India Crop Monitor first, Open-Meteo screening DEM fallback."""
from __future__ import annotations

from typing import Any, Optional

import requests

from field_twin.config import crop_monitor_url
from routers import terrain_screening as _terrain_screening


def fetch_terrain_meta(field_id: int, grid: int, season_year: Optional[int], field) -> dict[str, Any]:
    params = {"grid": grid}
    if season_year:
        params["year"] = season_year
    try:
        r = requests.get(
            f"{crop_monitor_url()}/api/fields/{field_id}/terrain/metadata",
            params=params,
            timeout=20,
        )
        if r.status_code < 400:
            data = r.json()
            if isinstance(data, dict) and data.get("available") is not False:
                data.setdefault("source", "crop_monitor")
                return data
    except Exception:
        pass
    if field is None:
        return {"available": False, "note": "No field row for screening DEM."}
    try:
        meta = _terrain_screening.build_screening_metadata(field, field_id, grid)
        if isinstance(meta, dict):
            meta.setdefault("source", "open_meteo_screening")
        return meta
    except Exception as e:
        return {"available": False, "error": str(e)}
