"""Farm-record helpers for India Field Twin (rotation, profile)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import desc, text
from sqlalchemy.orm import Session

import models
from field_twin.crop_source import crop_key


def rotation_history(db: Session, field_id: int) -> list:
    try:
        rows = (
            db.query(models.CropRotationEntry)
            .filter(models.CropRotationEntry.FieldID == field_id)
            .order_by(desc(models.CropRotationEntry.SeasonYear))
            .all()
        )
    except Exception:
        return []
    out = []
    for r in rows:
        crop = r.CropName
        out.append({
            "year": r.SeasonYear,
            "crop": crop,
            "crop_key": crop_key(crop),
            "variety": r.Variety,
            "planting_date": str(r.PlantingDate) if r.PlantingDate else None,
            "harvest_date": str(r.HarvestDate) if r.HarvestDate else None,
            "source": "crop_rotation",
        })
    return out


def rotation_for_year(history: list, year: int) -> Optional[dict]:
    for r in history or []:
        if r.get("year") == year:
            return r
    return None


def load_profile(db: Session, field_id: int) -> dict:
    try:
        row = db.execute(text("""
            SELECT SoilType, DrainageClass, SlopePercent, Topography,
                   OrganicMatterPct, PhLevel, FieldNotes, PhotoUrls, UpdatedAt
            FROM FieldProfile WHERE FieldID = :fid
        """), {"fid": field_id}).fetchone()
    except Exception:
        return {"available": False, "data": None, "error": "profile_table_unavailable"}
    if not row:
        return {"available": False, "data": None, "provenance": "none"}
    return {
        "available": True,
        "provenance": "observed",
        "confidence": "high",
        "data": {
            "soil_type": row[0],
            "drainage_class": row[1],
            "slope_percent": float(row[2]) if row[2] is not None else None,
            "topography": row[3],
            "organic_matter_pct": float(row[4]) if row[4] is not None else None,
            "ph_level": float(row[5]) if row[5] is not None else None,
            "field_notes": row[6],
            "photo_urls": row[7],
            "updated_at": row[8].isoformat() if row[8] else None,
        },
    }
