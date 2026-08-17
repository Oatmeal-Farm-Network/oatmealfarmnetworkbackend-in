"""Crop identity for India Field Twin — grower / rotation / field record only. No USDA CDL."""
from __future__ import annotations

from typing import Optional


def crop_key(crop_type: Optional[str]) -> str:
    if not crop_type:
        return "default"
    n = str(crop_type).lower().strip()
    aliases = (
        (("paddy", "rice"), "rice"),
        (("maize", "corn"), "maize"),
        (("soy",), "soybean"),
        (("wheat",), "wheat"),
        (("sugarcane", "cane"), "sugarcane"),
        (("cotton",), "cotton"),
        (("chickpea", "gram", "chana"), "chickpea"),
        (("pigeon", "tur", "arhar"), "pigeon_pea"),
        (("groundnut", "peanut"), "groundnut"),
        (("mustard", "rapeseed"), "mustard"),
        (("bajra", "pearl millet", "millet"), "millet"),
        (("jowar", "sorghum"), "sorghum"),
        (("potato",), "potato"),
        (("onion",), "onion"),
        (("tomato",), "tomato"),
        (("oat",), "oats"),
        (("barley",), "barley"),
        (("alfalfa",), "alfalfa"),
        (("cotton",), "cotton"),
        (("hay",), "hay"),
        (("grass", "pasture"), "grass"),
        (("canola",), "canola"),
    )
    for needles, key in aliases:
        if any(x in n for x in needles):
            return key
    return n.split()[0] if n else "default"


def _candidate(crop: Optional[str], key: Optional[str] = None, **extra) -> Optional[dict]:
    if not crop or crop == "unknown":
        return None
    out = {"crop": crop, "crop_key": key or crop_key(crop)}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def resolve_crop_source(
    *,
    decision,
    rotation: Optional[dict],
    field_crop: Optional[str],
    allow_field_record: bool,
) -> dict:
    """Priority: grower decision → rotation / crop plan → Field.CropType → unknown."""
    candidates = {
        "rotation": _candidate(
            (rotation or {}).get("crop"),
            (rotation or {}).get("crop_key"),
            planting_date=(rotation or {}).get("planting_date"),
        ),
        "field_record": _candidate(field_crop) if allow_field_record and field_crop else None,
        "cdl": None,
        "decision": None,
    }

    recorded_crop = None
    recorded_key = None
    recorded_source = None
    if rotation and rotation.get("crop"):
        recorded_crop = rotation["crop"]
        recorded_key = rotation.get("crop_key") or crop_key(recorded_crop)
        recorded_source = "crop_rotation"
    elif allow_field_record and field_crop:
        recorded_crop = field_crop
        recorded_key = crop_key(field_crop)
        recorded_source = "field_record"

    if decision and getattr(decision, "SelectedCrop", None):
        selected_crop = decision.SelectedCrop
        selected_key = crop_key(selected_crop)
        selected_source = decision.SelectedSource or "user_decision"
        candidates["decision"] = _candidate(
            selected_crop,
            selected_key,
            source=selected_source,
            decided_at=decision.DecidedAt.isoformat() + "Z" if decision.DecidedAt else None,
        )
        confirmed = True
        status = "confirmed"
        note = f"Grower confirmed {selected_crop} for this season (source: {selected_source})."
    elif recorded_crop:
        selected_crop = recorded_crop
        selected_key = recorded_key
        selected_source = recorded_source
        confirmed = False
        status = "unvalidated"
        note = (
            "Crop is recorded but not confirmed. Confirm Kharif/Rabi/Zaid crop "
            "before the twin draws a canopy. India Field Twin does not use USDA crop maps."
        )
    else:
        selected_crop = "unknown"
        selected_key = "default"
        selected_source = "unknown"
        confirmed = False
        status = "unvalidated"
        note = "No crop recorded for this season. Confirm the crop to render a realistic canopy."

    return {
        "crop_type": selected_crop,
        "crop_key": selected_key or "default",
        "selected_source": selected_source,
        "confirmed": confirmed,
        "recorded_crop_type": recorded_crop or "unknown",
        "detected_crop_type": None,
        "detected_year": None,
        "candidates": candidates,
        "validation": {
            "status": status,
            "requires_confirmation": not confirmed,
            "provenance": "recorded" if recorded_crop or confirmed else "none",
            "confidence": "high" if confirmed else ("medium" if recorded_crop else "low"),
            "independent_source": None,
            "detected_crop_type": None,
            "detected_year": None,
            "note": note,
        },
    }
