"""
Cross-feature link builder.

Given the output of one Saige feature, build a list of related
suggestions drawn from other Saige features. Pure function, no I/O.

- Pest diagnosis → companion plants that repel / trap that pest
- Soil challenges → subsidy programs that cost-share the remediation
- Price forecast → insurance products that hedge downside below the floor

Each helper returns a list of {title, description, url} dicts that
the frontend can render as CTA chips without any extra API calls.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------
# 1. pest → companion plants
# --------------------------------------------------------------------
# Maps normalized pest/disease tokens → companion-crop slugs that
# are known repellents / trap crops / beneficial-insect hosts.
PEST_COMPANIONS: Dict[str, List[str]] = {
    "aphid":          ["nasturtium", "dill", "fennel", "yarrow", "marigold"],
    "aphids":         ["nasturtium", "dill", "fennel", "yarrow", "marigold"],
    "cabbage worm":   ["thyme", "sage", "rosemary", "nasturtium"],
    "cabbage moth":   ["thyme", "sage", "rosemary", "nasturtium"],
    "cabbage looper": ["thyme", "sage", "rosemary"],
    "flea beetle":    ["radish", "nasturtium", "mint"],
    "colorado potato beetle": ["horseradish", "tansy", "catnip"],
    "potato beetle":  ["horseradish", "tansy", "catnip"],
    "tomato hornworm":["basil", "borage", "dill", "marigold"],
    "hornworm":       ["basil", "borage", "dill", "marigold"],
    "squash bug":     ["nasturtium", "tansy", "catnip", "marigold"],
    "squash vine borer":["nasturtium", "radish"],
    "cucumber beetle":["radish", "nasturtium", "tansy", "catnip"],
    "japanese beetle":["garlic", "chives", "tansy", "catnip"],
    "spider mite":    ["chives", "garlic", "dill", "cilantro"],
    "mites":          ["chives", "garlic", "dill"],
    "whitefly":       ["marigold", "nasturtium", "basil"],
    "thrips":         ["basil", "garlic", "chives"],
    "nematode":       ["marigold", "mustard"],
    "nematodes":      ["marigold", "mustard"],
    "slug":           ["garlic", "chives", "rosemary"],
    "slugs":          ["garlic", "chives", "rosemary"],
    "leaf miner":     ["radish", "columbine", "lamb's quarter"],
    "corn earworm":   ["sunflower", "dill"],
    "earworm":        ["sunflower", "dill"],
    "earwig":         ["tansy", "yarrow"],
    "ant":            ["mint", "tansy"],
    "mexican bean beetle": ["marigold", "savory", "petunia"],
    "bean beetle":    ["marigold", "savory"],
    "corn borer":     ["clover", "sunflower"],
    "carrot fly":     ["leek", "rosemary", "sage", "onion"],
    "onion fly":      ["carrot", "parsley"],
}

# Disease bucket (not "companions" in the classic sense, but still useful —
# we point to Saige chat for deeper IPM follow-up).
DISEASE_KEYWORDS = (
    "blight", "mildew", "rust", "wilt", "rot", "mold", "anthracnose",
    "mosaic", "spot", "canker", "scab", "smut", "virus",
)


def companions_for_pest(diagnosis: str, category: str = "") -> List[Dict[str, str]]:
    """Return companion-plant chips for a pest diagnosis.

    Strategy:
    - tokenize the diagnosis string, try longest-match against PEST_COMPANIONS
    - if nothing matches AND it looks like a disease, return empty (disease
      bucket — caller can still show a Saige-chat link).
    """
    if not diagnosis:
        return []
    d = diagnosis.lower()
    # Longest-match: prefer multi-word keys first
    keys = sorted(PEST_COMPANIONS.keys(), key=lambda k: -len(k))
    companions: List[str] = []
    for k in keys:
        if k in d:
            companions = PEST_COMPANIONS[k]
            break

    # If we only got a generic "pest" category and didn't match, give a
    # best-effort fallback of universally-useful repellents.
    if not companions:
        if (category or "").lower() == "pest":
            companions = ["marigold", "nasturtium", "basil"]
        else:
            return []

    out: List[Dict[str, str]] = []
    for c in companions[:5]:
        out.append({
            "title": c.title(),
            "description": f"Plant near affected crop — known to deter/trap {diagnosis}.",
            "url": f"/saige/companion-planting?crop={c}",
        })
    return out


# --------------------------------------------------------------------
# 2. soil challenge → subsidy programs
# --------------------------------------------------------------------
# Each challenge key maps to a list of program IDs from subsidies.py.
# EQIP and CSP both cost-share conservation practices; keep them at the
# top of most lists.
SOIL_TO_PROGRAMS: Dict[str, List[str]] = {
    "organic_matter_low":  ["eqip", "csp", "sare"],
    "nitrogen_low":        ["eqip", "csp"],
    "phosphorus_low":      ["eqip", "csp"],
    "potassium_low":       ["eqip", "csp"],
    "cec_low":             ["eqip", "csp", "sare"],
    "ph_low":              ["eqip"],
    "ph_high":             ["eqip"],
    "salinity_high":       ["eqip", "crp"],
    "bulk_density_high":   ["eqip", "csp"],
    "sodium_high":         ["eqip"],
    "moisture_low":        ["eqip"],   # drip / irrigation cost-share
    "moisture_high":       ["eqip", "crp"],  # drainage, cover crops
    "phosphorus_high":     ["csp"],    # nutrient-management plan
}

# Short human-readable blurbs keyed by program ID (mirrors the headline
# from subsidies.py so the frontend can render without a second fetch).
PROGRAM_BLURBS: Dict[str, Dict[str, str]] = {
    "eqip":  {"name": "EQIP",  "what": "USDA cost-share for cover crops, nutrient plans, irrigation upgrades."},
    "csp":   {"name": "CSP",   "what": "Annual payments for maintaining & improving conservation on working land."},
    "crp":   {"name": "CRP",   "what": "Rental payments for retiring sensitive acres from production."},
    "sare":  {"name": "SARE",  "what": "On-farm research grants for soil-building experiments."},
}


def subsidies_for_soil(challenges: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Return subsidy chips matching the severe-first list of soil challenges."""
    if not challenges:
        return []
    seen_ids: List[str] = []
    out: List[Dict[str, str]] = []

    for ch in challenges:
        measure = ch.get("measure")
        direction = ch.get("direction")
        key = f"{measure}_{direction}" if measure and direction else None
        if not key:
            continue
        for pid in SOIL_TO_PROGRAMS.get(key, []):
            if pid in seen_ids:
                continue
            seen_ids.append(pid)
            blurb = PROGRAM_BLURBS.get(pid, {"name": pid.upper(), "what": ""})
            out.append({
                "title": blurb["name"],
                "description": blurb["what"],
                "url": f"/saige/subsidies?focus={pid}",
            })
        if len(out) >= 4:
            break
    return out


# --------------------------------------------------------------------
# 3. price forecast → insurance products
# --------------------------------------------------------------------
# For any commodity, suggest the RMA products that address downside risk
# based on commodity type. The frontend already has a full insurance
# lookup at /saige/insurance — this just surfaces a shortcut.
# We map crop buckets → product-ID priorities.
INSURANCE_BY_BUCKET: Dict[str, List[str]] = {
    "row_crop":   ["rp", "yp"],              # corn, soy, wheat: Revenue Protection
    "livestock":  ["lrp", "lgm"],            # cattle, hogs: Livestock Risk Protection
    "dairy":      ["drp"],                   # dairy: Dairy Revenue Protection
    "specialty":  ["aph", "wfrp"],           # fruits/veg: APH + Whole-Farm
    "forage":     ["prf"],                   # hay/pasture: Rainfall Index
    "nap":        ["nap"],                   # uninsurable crops: NAP
}

COMMODITY_BUCKETS: Dict[str, str] = {
    "corn": "row_crop", "soybean": "row_crop", "soybeans": "row_crop",
    "wheat": "row_crop", "cotton": "row_crop", "rice": "row_crop",
    "sorghum": "row_crop", "barley": "row_crop", "oats": "row_crop",
    "cattle": "livestock", "beef": "livestock", "hogs": "livestock",
    "pork": "livestock", "lamb": "livestock", "sheep": "livestock",
    "milk": "dairy", "dairy": "dairy",
    "tomato": "specialty", "tomatoes": "specialty",
    "apple": "specialty", "apples": "specialty",
    "peach": "specialty", "strawberry": "specialty",
    "hay": "forage", "pasture": "forage", "alfalfa": "forage",
}

PRODUCT_BLURBS: Dict[str, Dict[str, str]] = {
    "rp":   {"name": "Revenue Protection (RP)",        "what": "Covers revenue loss from low yield OR low price."},
    "yp":   {"name": "Yield Protection (YP)",          "what": "Pays when yield drops below your historical average."},
    "aph":  {"name": "APH",                             "what": "Yield-only coverage for specialty crops."},
    "wfrp": {"name": "Whole-Farm Revenue Protection",  "what": "One policy covers whole-farm revenue — good for diversified operations."},
    "prf":  {"name": "Pasture, Rangeland, Forage",     "what": "Rainfall-index policy for hay, pasture, grazing land."},
    "lrp":  {"name": "Livestock Risk Protection",      "what": "Price floor on cattle / hogs / lamb."},
    "lgm":  {"name": "Livestock Gross Margin",         "what": "Protects margin between sale price and feed cost."},
    "drp":  {"name": "Dairy Revenue Protection",       "what": "Quarterly price + yield protection for dairy."},
    "nap":  {"name": "NAP",                             "what": "FSA Noninsured Crop Disaster Assistance for crops without RMA coverage."},
}


def insurance_for_commodity(commodity: str, confidence: Optional[str] = None,
                            expected_trend: Optional[str] = None) -> List[Dict[str, str]]:
    """Return insurance chips for a forecasted commodity.

    `expected_trend` can be 'down' / 'flat' / 'up' — when down we bubble
    price-floor products above yield-only ones.
    """
    if not commodity:
        return []
    c = re.sub(r"[^a-z ]", "", commodity.lower()).strip()
    bucket = COMMODITY_BUCKETS.get(c)

    if not bucket:
        # Unknown commodity → WFRP + NAP are the safe defaults
        pids = ["wfrp", "nap"]
    else:
        pids = list(INSURANCE_BY_BUCKET.get(bucket, []))

    # If the forecast trend is down, prioritize revenue/price-floor products
    if expected_trend == "down":
        priority = [p for p in pids if p in ("rp", "lrp", "drp", "wfrp")]
        rest     = [p for p in pids if p not in priority]
        pids = priority + rest

    out: List[Dict[str, str]] = []
    for pid in pids[:3]:
        blurb = PRODUCT_BLURBS.get(pid, {"name": pid.upper(), "what": ""})
        out.append({
            "title": blurb["name"],
            "description": blurb["what"],
            "url": f"/saige/insurance?crop={c}",
        })
    return out
