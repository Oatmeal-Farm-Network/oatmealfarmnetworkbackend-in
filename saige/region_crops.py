"""
Region-specific crop recommendations.

Given a latitude/longitude OR a USDA zone OR a climate descriptor
(tropical, subtropical, temperate, arid, mediterranean, continental,
boreal, highland), return a ranked list of crops well-suited to that
region, with a short reason.

Data is intentionally conservative — these are crops with strong
performance history in the given zone, not an exhaustive list of what
*could* grow there.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional
from langchain_core.tools import tool


# ──────────────────────────────────────────────────────────────────
# USDA zone → rough min-temp range (°F)
# ──────────────────────────────────────────────────────────────────
USDA_ZONE_TEMPS = {
    "3": (-40, -30), "4": (-30, -20), "5": (-20, -10), "6": (-10, 0),
    "7": (0, 10), "8": (10, 20), "9": (20, 30), "10": (30, 40),
    "11": (40, 50), "12": (50, 60), "13": (60, 70),
}

# ──────────────────────────────────────────────────────────────────
# Climate-zone → recommended crop set
# ──────────────────────────────────────────────────────────────────
# Each crop entry is (name, reason).
CLIMATE_CROPS: Dict[str, List] = {
    "tropical": [
        ("cassava",       "staple carb, drought-tolerant once established, 9-12 mo to harvest"),
        ("taro",          "thrives in wet tropics, staple across Pacific/West Africa/Caribbean"),
        ("yam",           "high yields, stores well in tropical climates"),
        ("plantain",      "perennial staple, year-round production"),
        ("banana",        "tropical cash crop, 10-15 mo to first harvest"),
        ("coconut",       "coastal tropical palm, 60-80 year productive life"),
        ("mango",         "heat-loving tree crop, major global export"),
        ("papaya",        "fast — fruits in 9-12 months"),
        ("pineapple",     "tolerates poor soil, 18-24 mo first crop"),
        ("sugarcane",     "major tropical cash crop"),
        ("rice",          "paddy or upland rice both suitable"),
        ("sweet potato",  "reliable tropical staple"),
        ("pigeon pea",    "drought-tolerant legume, nitrogen fixation"),
        ("cowpea",        "short-season legume, heat-tolerant"),
        ("okra",          "heat-loving vegetable"),
        ("amaranth",      "heat-tolerant leafy green + grain"),
        ("moringa",       "nutrient powerhouse tree, drought-tolerant"),
        ("chili pepper",  "tropical origin, year-round production"),
    ],
    "subtropical": [
        ("citrus",        "oranges/lemons/grapefruit thrive in frost-free subtropics"),
        ("avocado",       "subtropical tree crop, high value"),
        ("sweet potato",  "long warm season"),
        ("peanut",        "warm-season legume, 100-130 day cycle"),
        ("cotton",        "classic subtropical row crop"),
        ("rice",          "irrigated paddy suitable in warmer subtropics"),
        ("tomato",        "long production window"),
        ("pepper",        "long season favors pepper production"),
        ("eggplant",      "heat-loving solanaceous crop"),
        ("okra",          "staple subtropical vegetable"),
        ("sugarcane",     "grown from Florida/Gulf Coast through N. India"),
        ("pecan",         "subtropical nut tree, 8-12 yr to bearing"),
        ("pomegranate",   "drought-tolerant subtropical fruit"),
        ("fig",           "mediterranean-subtropical fruit tree"),
    ],
    "temperate": [
        ("corn",          "backbone of temperate agriculture"),
        ("soybean",       "temperate legume, rotation staple"),
        ("wheat",         "winter/spring wheat both suitable"),
        ("oat",           "cool-season cereal"),
        ("barley",        "short-season cereal, tolerant of cool"),
        ("potato",        "cool-season tuber"),
        ("tomato",        "summer staple in gardens/greenhouses"),
        ("pepper",        "warm-season vegetable"),
        ("squash",        "winter + summer squash both thrive"),
        ("cabbage",       "cool-season brassica, fall/spring"),
        ("broccoli",      "cool-season brassica"),
        ("kale",          "cold-hardy leafy green, overwinters"),
        ("carrot",        "cool-season root"),
        ("onion",         "day-length sensitive — pick intermediate-day cultivars"),
        ("lettuce",       "cool-season — bolts in summer heat"),
        ("strawberry",    "temperate perennial fruit"),
        ("apple",         "classic temperate fruit tree"),
        ("pear",          "temperate fruit tree"),
        ("grape",         "wine + table grapes both suitable"),
        ("blueberry",     "needs acidic soil, cold hours for fruit set"),
    ],
    "continental": [
        ("wheat",         "hard red winter/spring — Great Plains, Ukraine, Canada"),
        ("corn",          "field/sweet corn — summer heat, winter dormancy"),
        ("soybean",       "rotation partner with corn"),
        ("sunflower",     "drought-tolerant oilseed, loves continental summer"),
        ("canola",        "cool-season oilseed, short rotation"),
        ("oat",           "cool-season, widely grown"),
        ("sugar beet",    "cool-temperate row crop"),
        ("potato",        "prefers cool nights, long summer days"),
        ("alfalfa",       "deep-rooted forage, 4-10 yr stand life"),
        ("cabbage",       "cool-season brassica, overwinters in cellar"),
        ("apple",         "cold-hardy cultivars — Honeycrisp, McIntosh, Haralson"),
        ("sour cherry",   "cold-hardy stone fruit"),
    ],
    "mediterranean": [
        ("olive",         "signature Mediterranean tree crop"),
        ("grape",         "wine grape heartland"),
        ("almond",        "dry Mediterranean nut tree"),
        ("fig",           "ancient Mediterranean fruit"),
        ("pomegranate",   "drought-tolerant fruit"),
        ("citrus",        "Valencia/navel orange, lemon"),
        ("wheat",         "winter wheat on rainfed ground"),
        ("chickpea",      "Mediterranean pulse crop"),
        ("lentil",        "cool dry-season legume"),
        ("tomato",        "Mediterranean cuisine staple, long dry season favors production"),
        ("artichoke",     "perennial Mediterranean crop"),
        ("rosemary",      "perennial herb, drought-tolerant"),
        ("thyme",         "perennial herb, drought-tolerant"),
        ("lavender",      "drought-tolerant perennial"),
    ],
    "arid": [
        ("sorghum",       "drought-tolerant C4 grain, 30-40% less water than corn"),
        ("millet",        "pearl/finger millet — dryland cereal"),
        ("tepary bean",   "native-American desert legume, extremely drought-tolerant"),
        ("cowpea",        "drought + heat tolerant legume"),
        ("chickpea",      "cool-season dryland pulse"),
        ("sesame",        "drought-tolerant oilseed"),
        ("date palm",     "classic desert tree crop, tolerates salinity"),
        ("pistachio",     "drought-tolerant nut tree"),
        ("pomegranate",   "drought + salinity tolerant"),
        ("fig",           "drought-tolerant fruit tree"),
        ("Armenian cucumber", "heat-tolerant specialty crop"),
        ("amaranth",      "drought-tolerant grain + leafy green"),
        ("quinoa",        "arid-adapted pseudocereal, salt-tolerant"),
        ("aloe",          "CAM-pathway perennial, very low water"),
        ("agave",         "extreme drought tolerance, 6-8 yr to harvest"),
    ],
    "highland": [
        ("quinoa",        "Andean highland pseudocereal, thrives 2,500-4,000 m"),
        ("potato",        "originated in Andean highlands — 4000+ varieties"),
        ("oca",           "Andean tuber, frost-tolerant"),
        ("ulluco",        "Andean tuber, high-elevation staple"),
        ("mashua",        "Andean tuber, pest-repellent"),
        ("amaranth",      "Andean + Aztec grain, tolerates altitude"),
        ("barley",        "hardy cereal for cold highlands"),
        ("fava bean",     "cool-weather legume, frost-tolerant"),
        ("tarwi",         "Andean lupin, soil-building legume"),
        ("tree tomato",   "perennial for mid-elevation tropics"),
        ("alpaca / llama",     "livestock adapted to altitude (not a crop, but staple)"),
        ("coffee",        "arabica requires 1,200-1,800 m tropical highland"),
    ],
    "boreal": [
        ("oat",           "short-season cereal, cold tolerant"),
        ("barley",        "shortest-season cereal option"),
        ("canola",        "75-100 day oilseed"),
        ("potato",        "reliable cool-summer tuber"),
        ("turnip",        "root crop, 50-70 day"),
        ("rutabaga",      "cold-hardy root"),
        ("cabbage",       "long storage crop, tolerates frost"),
        ("cloudberry",    "boreal specialty berry"),
        ("lingonberry",   "boreal low-bush berry"),
        ("haskap",        "Siberian honeyberry, extreme cold tolerance"),
    ],
}


CLIMATE_ALIASES = {
    "tropical":         "tropical",
    "humid tropical":   "tropical",
    "equatorial":       "tropical",
    "subtropical":      "subtropical",
    "sub-tropical":     "subtropical",
    "humid subtropical":"subtropical",
    "temperate":        "temperate",
    "humid temperate":  "temperate",
    "oceanic":          "temperate",
    "maritime":         "temperate",
    "continental":      "continental",
    "humid continental":"continental",
    "cold continental": "continental",
    "mediterranean":    "mediterranean",
    "dry summer":       "mediterranean",
    "arid":             "arid",
    "desert":           "arid",
    "semi-arid":        "arid",
    "semiarid":         "arid",
    "steppe":           "arid",
    "highland":         "highland",
    "mountain":         "highland",
    "alpine":           "highland",
    "high-altitude":    "highland",
    "boreal":           "boreal",
    "subarctic":        "boreal",
    "sub-arctic":       "boreal",
    "taiga":            "boreal",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def resolve_climate(descriptor: str) -> Optional[str]:
    return CLIMATE_ALIASES.get(_norm(descriptor))


def zone_to_climate(zone: str) -> Optional[str]:
    """Roughly map a USDA zone number (3-13) to a climate bucket."""
    if not zone:
        return None
    z = re.sub(r"[^0-9]", "", str(zone))
    if not z:
        return None
    try:
        zn = int(z)
    except ValueError:
        return None
    if zn <= 3: return "boreal"
    if zn <= 5: return "continental"
    if zn <= 7: return "temperate"
    if zn <= 9: return "subtropical"
    return "tropical"


def latlon_to_climate(lat: float, lon: float) -> str:
    """Rough lat-band climate classification. Not meant to replace Köppen.
    Used only when the user hasn't given us anything better."""
    abs_lat = abs(lat)
    if abs_lat < 15:
        return "tropical"
    if abs_lat < 25:
        return "subtropical"
    if abs_lat < 45:
        return "temperate"
    if abs_lat < 60:
        return "continental"
    return "boreal"


def recommend(
    climate: Optional[str] = None,
    zone: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    limit: int = 20,
) -> Dict:
    """Resolve whatever the caller gave us and return crop recommendations."""
    resolved = None
    source = None
    if climate:
        resolved = resolve_climate(climate)
        source = f"climate='{climate}'"
    if not resolved and zone:
        resolved = zone_to_climate(zone)
        source = f"zone='{zone}'"
    if not resolved and lat is not None and lon is not None:
        resolved = latlon_to_climate(lat, lon)
        source = f"lat={lat:.2f}, lon={lon:.2f}"
    if not resolved:
        return {
            "status": "not_resolved",
            "message": "Could not determine climate from inputs.",
            "known_climates": list(CLIMATE_CROPS.keys()),
        }
    crops = CLIMATE_CROPS.get(resolved, [])[:limit]
    return {
        "status": "ok",
        "climate": resolved,
        "source": source,
        "crops": [{"name": n, "reason": r} for n, r in crops],
    }


def list_climates() -> List[str]:
    return sorted(CLIMATE_CROPS.keys())


def format_for_llm(
    climate: Optional[str] = None,
    zone: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> str:
    rec = recommend(climate, zone, lat, lon)
    if rec["status"] != "ok":
        return rec.get("message", "Could not resolve climate.")
    lines = [f"Climate: {rec['climate']} (from {rec['source']})"]
    lines.append("Recommended crops:")
    for c in rec["crops"]:
        lines.append(f"  • {c['name']}: {c['reason']}")
    return "\n".join(lines)


@tool
def region_crops_tool(climate: str = "", zone: str = "", lat: float = 0.0, lon: float = 0.0) -> str:
    """Recommend crops well-suited to a region. Provide ONE of:
        climate — tropical, subtropical, temperate, continental, mediterranean,
            arid, highland, boreal (common synonyms accepted); OR
        zone — USDA hardiness zone as '3' through '13'; OR
        lat + lon — latitude/longitude in decimal degrees.
    Returns a ranked list of crops with a short reason each. Use when the user
    asks "what should I grow here" or "what grows well in [place]"."""
    return format_for_llm(climate or None, zone or None,
                          lat if lat else None, lon if lon else None)


region_crops_tools = [region_crops_tool]
