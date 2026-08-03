"""
Agronomy tools for Saige:

  - planting_calendar_tool(crop, zone, lat, lon): when/how to plant
  - irrigation_schedule_tool(crop, stage, soil_type, days_since_rain): how much
    and how often to water
  - manure_pairing_tool(crop, available_manures): rank manures by how well
    their N-P-K matches the crop, with composted-vs-fresh caveats

Reference datasets are bundled inline (frost dates by USDA zone, crop
planting windows, FAO-56 Kc values, NRCS-typical manure compositions, and
approximate crop nutrient demand). Numbers are approximations meant for
conversational guidance, not prescriptive recommendations.
"""
from __future__ import annotations

from typing import Optional, List, Dict, Any
from langchain_core.tools import tool


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

# USDA-zone-ish average last-spring / first-fall frost (month, day)
FROST_BY_ZONE: Dict[int, Dict[str, str]] = {
    3:  {"last_spring": "Jun 1",  "first_fall": "Sep 1"},
    4:  {"last_spring": "May 15", "first_fall": "Sep 15"},
    5:  {"last_spring": "May 1",  "first_fall": "Oct 1"},
    6:  {"last_spring": "Apr 15", "first_fall": "Oct 15"},
    7:  {"last_spring": "Apr 1",  "first_fall": "Nov 1"},
    8:  {"last_spring": "Mar 15", "first_fall": "Nov 15"},
    9:  {"last_spring": "Feb 15", "first_fall": "Dec 1"},
    10: {"last_spring": "frost-free", "first_fall": "frost-free"},
    11: {"last_spring": "frost-free", "first_fall": "frost-free"},
}

# Planting window per crop. `offset_days` is days from last-spring-frost
# (negative = before, positive = after). `method`: direct_sow / transplant /
# tuber / clove / bare_root / set_or_start.
CROP_CAL: Dict[str, Dict[str, Any]] = {
    "tomato":     {"offset": 14,  "soil_temp_f": 60, "depth_in": 0.25, "method": "transplant", "dtm": 75},
    "pepper":     {"offset": 14,  "soil_temp_f": 65, "depth_in": 0.25, "method": "transplant", "dtm": 80},
    "cucumber":   {"offset": 7,   "soil_temp_f": 65, "depth_in": 1.0,  "method": "direct_sow", "dtm": 55},
    "squash":     {"offset": 7,   "soil_temp_f": 65, "depth_in": 1.0,  "method": "direct_sow", "dtm": 50},
    "zucchini":   {"offset": 7,   "soil_temp_f": 65, "depth_in": 1.0,  "method": "direct_sow", "dtm": 50},
    "melon":      {"offset": 14,  "soil_temp_f": 70, "depth_in": 1.0,  "method": "direct_sow", "dtm": 80},
    "watermelon": {"offset": 14,  "soil_temp_f": 70, "depth_in": 1.0,  "method": "direct_sow", "dtm": 85},
    "bean":       {"offset": 7,   "soil_temp_f": 60, "depth_in": 1.5,  "method": "direct_sow", "dtm": 55},
    "beans":      {"offset": 7,   "soil_temp_f": 60, "depth_in": 1.5,  "method": "direct_sow", "dtm": 55},
    "corn":       {"offset": 7,   "soil_temp_f": 60, "depth_in": 1.5,  "method": "direct_sow", "dtm": 85},
    "okra":       {"offset": 14,  "soil_temp_f": 65, "depth_in": 1.0,  "method": "direct_sow", "dtm": 60},
    "sweet_potato":{"offset": 21, "soil_temp_f": 65, "depth_in": 3.0,  "method": "slip",       "dtm": 110},
    "pea":        {"offset": -28, "soil_temp_f": 40, "depth_in": 1.0,  "method": "direct_sow", "dtm": 65},
    "peas":       {"offset": -28, "soil_temp_f": 40, "depth_in": 1.0,  "method": "direct_sow", "dtm": 65},
    "lettuce":    {"offset": -28, "soil_temp_f": 40, "depth_in": 0.25, "method": "direct_sow", "dtm": 45},
    "spinach":    {"offset": -28, "soil_temp_f": 40, "depth_in": 0.5,  "method": "direct_sow", "dtm": 40},
    "kale":       {"offset": -28, "soil_temp_f": 40, "depth_in": 0.5,  "method": "direct_sow", "dtm": 55},
    "chard":      {"offset": -14, "soil_temp_f": 45, "depth_in": 0.5,  "method": "direct_sow", "dtm": 55},
    "broccoli":   {"offset": -14, "soil_temp_f": 45, "depth_in": 0.5,  "method": "transplant", "dtm": 65},
    "cabbage":    {"offset": -14, "soil_temp_f": 45, "depth_in": 0.5,  "method": "transplant", "dtm": 70},
    "cauliflower":{"offset": -14, "soil_temp_f": 45, "depth_in": 0.5,  "method": "transplant", "dtm": 75},
    "carrot":     {"offset": -14, "soil_temp_f": 45, "depth_in": 0.25, "method": "direct_sow", "dtm": 70},
    "beet":       {"offset": -21, "soil_temp_f": 45, "depth_in": 0.5,  "method": "direct_sow", "dtm": 60},
    "radish":     {"offset": -28, "soil_temp_f": 45, "depth_in": 0.5,  "method": "direct_sow", "dtm": 30},
    "potato":     {"offset": -14, "soil_temp_f": 45, "depth_in": 4.0,  "method": "tuber",      "dtm": 90},
    "onion":      {"offset": -28, "soil_temp_f": 40, "depth_in": 0.5,  "method": "set_or_start", "dtm": 100},
    "garlic":     {"offset": 120, "soil_temp_f": 50, "depth_in": 2.0,  "method": "clove_fall_plant", "dtm": 240,
                    "notes": "Plant in fall ~4-6 weeks before first frost; harvest next summer."},
    "strawberry": {"offset": -30, "soil_temp_f": 45, "depth_in": 0.0,  "method": "bare_root",  "dtm": 365},
    "soybean":    {"offset": 14,  "soil_temp_f": 55, "depth_in": 1.5,  "method": "direct_sow", "dtm": 110},
    "wheat_spring":{"offset": -28,"soil_temp_f": 40, "depth_in": 1.5,  "method": "direct_sow", "dtm": 110},
    "wheat_winter":{"offset": 90, "soil_temp_f": 50, "depth_in": 1.5,  "method": "fall_drill", "dtm": 240,
                    "notes": "Drill in fall ~6 weeks before hard freeze; harvest next summer."},
    "oats":       {"offset": -28, "soil_temp_f": 40, "depth_in": 1.5,  "method": "direct_sow", "dtm": 95},
}

# FAO-56 crop coefficients (Kc) + season length (days)
CROP_KC: Dict[str, Dict[str, Any]] = {
    "tomato":   {"initial": 0.60, "mid": 1.15, "late": 0.80, "season_days": 120},
    "corn":     {"initial": 0.30, "mid": 1.20, "late": 0.60, "season_days": 130},
    "soybean":  {"initial": 0.40, "mid": 1.15, "late": 0.50, "season_days": 120},
    "wheat":    {"initial": 0.70, "mid": 1.15, "late": 0.40, "season_days": 135},
    "potato":   {"initial": 0.50, "mid": 1.15, "late": 0.75, "season_days": 115},
    "lettuce":  {"initial": 0.70, "mid": 1.00, "late": 0.95, "season_days": 45},
    "bean":     {"initial": 0.40, "mid": 1.15, "late": 0.35, "season_days": 95},
    "cucumber": {"initial": 0.60, "mid": 1.00, "late": 0.75, "season_days": 90},
    "pepper":   {"initial": 0.60, "mid": 1.05, "late": 0.90, "season_days": 125},
    "squash":   {"initial": 0.50, "mid": 0.95, "late": 0.75, "season_days": 95},
    "onion":    {"initial": 0.70, "mid": 1.05, "late": 0.75, "season_days": 130},
    "carrot":   {"initial": 0.70, "mid": 1.05, "late": 0.95, "season_days": 100},
    "strawberry":{"initial": 0.40,"mid": 0.85, "late": 0.75, "season_days": 150},
    "grass_hay":{"initial": 0.75, "mid": 1.00, "late": 0.85, "season_days": 365},
}

# NRCS-typical manure compositions (%, as-is) and practical notes
MANURE: Dict[str, Dict[str, Any]] = {
    "chicken":  {"N": 3.8, "P2O5": 3.5, "K2O": 1.8, "moisture_pct": 55,
                 "hot": True, "note": "Hot — compost 3-6 months before applying to sensitive crops.",
                 "lbs_per_animal_year": 110},
    "cow_dairy":{"N": 0.5, "P2O5": 0.2, "K2O": 0.5, "moisture_pct": 85,
                 "hot": False, "note": "Mild; good general amendment.",
                 "lbs_per_animal_year": 15000},
    "cow_beef": {"N": 0.6, "P2O5": 0.4, "K2O": 0.5, "moisture_pct": 80,
                 "hot": False, "note": "Mild; balanced.",
                 "lbs_per_animal_year": 12000},
    "horse":    {"N": 0.7, "P2O5": 0.3, "K2O": 0.6, "moisture_pct": 70,
                 "hot": False, "note": "Often carries weed seeds — hot-compost if possible.",
                 "lbs_per_animal_year": 10000},
    "sheep":    {"N": 0.9, "P2O5": 0.5, "K2O": 0.8, "moisture_pct": 65,
                 "hot": False, "note": "Pelletized; easy to spread; balanced.",
                 "lbs_per_animal_year": 800},
    "goat":     {"N": 1.0, "P2O5": 0.7, "K2O": 0.9, "moisture_pct": 65,
                 "hot": False, "note": "Pelletized; low odor; usable direct for most crops.",
                 "lbs_per_animal_year": 800},
    "pig":      {"N": 0.5, "P2O5": 0.4, "K2O": 0.4, "moisture_pct": 80,
                 "hot": False, "note": "Strong odor; compost thoroughly.",
                 "lbs_per_animal_year": 2000},
    "rabbit":   {"N": 2.4, "P2O5": 1.4, "K2O": 0.6, "moisture_pct": 60,
                 "hot": False, "note": "'Cold' manure — apply direct, no composting needed.",
                 "lbs_per_animal_year": 200},
    "alpaca":   {"N": 1.5, "P2O5": 0.5, "K2O": 1.1, "moisture_pct": 65,
                 "hot": False, "note": "Low odor, near-direct application.",
                 "lbs_per_animal_year": 1300},
    "llama":    {"N": 1.5, "P2O5": 0.5, "K2O": 1.1, "moisture_pct": 65,
                 "hot": False, "note": "Similar to alpaca.",
                 "lbs_per_animal_year": 1500},
    "duck":     {"N": 1.1, "P2O5": 1.4, "K2O": 0.5, "moisture_pct": 65,
                 "hot": True,  "note": "Wet and hot — compost before use.",
                 "lbs_per_animal_year": 140},
}

# Rough crop nutrient demand (lbs/acre, typical yield). Values are for the
# ranking heuristic in manure_pairing_tool, not a fertilizer prescription.
CROP_NEED: Dict[str, Dict[str, Any]] = {
    "corn":       {"N": 180, "P": 70,  "K": 60,
                   "appetite": "heavy", "tags": ["N-heavy"],
                   "avoid": [], "prefers_composted": True},
    "tomato":     {"N": 100, "P": 50,  "K": 120,
                   "appetite": "heavy", "tags": ["K-heavy"],
                   "avoid": [], "prefers_composted": True},
    "pepper":     {"N": 80,  "P": 40,  "K": 80,
                   "appetite": "medium", "tags": [],
                   "avoid": [], "prefers_composted": True},
    "lettuce":    {"N": 60,  "P": 20,  "K": 40,
                   "appetite": "light", "tags": ["leafy"],
                   "avoid": ["chicken_fresh"], "prefers_composted": True},
    "bean":       {"N": 20,  "P": 40,  "K": 60,
                   "appetite": "light-N", "tags": ["N-fixer"],
                   "avoid": [], "prefers_composted": False,
                   "note": "N-fixer — high-N manure wastes your nitrogen."},
    "potato":     {"N": 150, "P": 70,  "K": 220,
                   "appetite": "heavy-K", "tags": ["K-heavy"],
                   "avoid": ["chicken_fresh"], "prefers_composted": True,
                   "note": "Fresh chicken manure can trigger scab."},
    "brassica":   {"N": 150, "P": 60,  "K": 100,
                   "appetite": "heavy", "tags": ["N-heavy"],
                   "avoid": [], "prefers_composted": True},
    "cabbage":    {"N": 150, "P": 60,  "K": 100,
                   "appetite": "heavy", "tags": ["N-heavy"],
                   "avoid": [], "prefers_composted": True},
    "broccoli":   {"N": 150, "P": 60,  "K": 100,
                   "appetite": "heavy", "tags": ["N-heavy"],
                   "avoid": [], "prefers_composted": True},
    "squash":     {"N": 120, "P": 50,  "K": 120,
                   "appetite": "heavy", "tags": [],
                   "avoid": [], "prefers_composted": True},
    "cucumber":   {"N": 90,  "P": 50,  "K": 100,
                   "appetite": "medium", "tags": [],
                   "avoid": [], "prefers_composted": True},
    "berries":    {"N": 60,  "P": 40,  "K": 80,
                   "appetite": "medium-acid-tolerant", "tags": ["fruit"],
                   "avoid": [], "prefers_composted": True,
                   "note": "Too much N encourages leaves over fruit."},
    "strawberry": {"N": 60,  "P": 40,  "K": 80,
                   "appetite": "medium", "tags": ["fruit"],
                   "avoid": [], "prefers_composted": True},
    "grass_hay":  {"N": 100, "P": 30,  "K": 100,
                   "appetite": "N-forage", "tags": ["forage"],
                   "avoid": [], "prefers_composted": False},
    "onion":      {"N": 100, "P": 40,  "K": 70,
                   "appetite": "medium", "tags": [],
                   "avoid": [], "prefers_composted": True},
    "carrot":     {"N": 80,  "P": 40,  "K": 120,
                   "appetite": "medium", "tags": ["root"],
                   "avoid": [], "prefers_composted": True,
                   "note": "Fresh manure causes forked roots — use only composted."},
}

# Default reference evapotranspiration (in/day) by climate — conversational
# shorthand when we can't pull real ET₀ from weather.
CLIMATE_ET0: Dict[str, float] = {
    "arid":          0.30,
    "mediterranean": 0.22,
    "continental":   0.20,
    "temperate":     0.18,
    "subtropical":   0.22,
    "tropical":      0.18,
    "highland":      0.15,
    "boreal":        0.12,
}

SOIL_NOTES: Dict[str, str] = {
    "sandy":      "Drains fast — smaller doses more often (every 2-3 days).",
    "loam":       "Ideal — weekly deep watering works well.",
    "clay":       "Holds water — fewer, deeper soakings (every 7-10 days).",
    "silty":      "Holds water like clay but drains a bit better.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_crop(crop: str) -> str:
    k = (crop or "").strip().lower().replace(" ", "_")
    # aliases
    aliases = {
        "maize": "corn",
        "courgette": "zucchini",
        "aubergine": "eggplant",
        "capsicum": "pepper",
        "sweetcorn": "corn",
        "soybeans": "soybean",
        "soya": "soybean",
        "green_bean": "bean",
        "bush_bean": "bean",
        "pole_bean": "bean",
        "beans": "bean",
        "peas": "pea",
        "snap_pea": "pea",
        "snow_pea": "pea",
        "sweetpotato": "sweet_potato",
        "yam": "sweet_potato",
        "alfalfa": "grass_hay",
        "hay": "grass_hay",
        "strawberries": "strawberry",
        "blueberry": "berries",
        "blueberries": "berries",
        "raspberry": "berries",
        "raspberries": "berries",
    }
    return aliases.get(k, k)


def _zone_from_lat(lat: float) -> Optional[int]:
    """Very rough mid-latitude USDA zone shortcut — only used when the
    caller gives no zone. Not a substitute for a real zone lookup."""
    try:
        lat = abs(float(lat))
    except (TypeError, ValueError):
        return None
    if lat >= 49: return 3
    if lat >= 45: return 4
    if lat >= 41: return 5
    if lat >= 38: return 6
    if lat >= 34: return 7
    if lat >= 30: return 8
    if lat >= 26: return 9
    if lat >= 23: return 10
    return 11


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool
def planting_calendar_tool(
    crop: str = "",
    zone: int = 0,
    lat: float = 0.0,
    lon: float = 0.0,
) -> str:
    """When and how to plant a specific crop. Returns earliest safe outdoor
    plant-out date, soil-temperature prerequisite, seed depth, direct-sow
    vs transplant method, and expected days to maturity. Pass ONE of zone
    (USDA zone 3-11), lat+lon (rough zone), or just crop (zone assumed 6).
    Use whenever the user asks "when should I plant X", "is it too late /
    early for Y", "what's the planting window for Z"."""
    crop_key = _normalize_crop(crop)
    if not crop_key:
        return "Which crop? (tomato, corn, lettuce, potato, etc.)"
    cal = CROP_CAL.get(crop_key)
    if not cal:
        return (f"No planting-window data for '{crop}'. Known crops: "
                f"{', '.join(sorted(CROP_CAL.keys()))}.")

    z = int(zone) if zone else (_zone_from_lat(lat) if lat else 0)
    if z and z in FROST_BY_ZONE:
        frost = FROST_BY_ZONE[z]
    else:
        z = 6  # sensible default
        frost = FROST_BY_ZONE[6]

    offset = int(cal.get("offset", 0))
    method = cal.get("method", "direct_sow")
    depth  = cal.get("depth_in", 0.5)
    soil_t = cal.get("soil_temp_f", 50)
    dtm    = cal.get("dtm", 60)

    if frost["last_spring"] == "frost-free":
        window_line = "Zone is frost-free — plant anytime soil conditions are right."
    else:
        direction = "after" if offset > 0 else ("before" if offset < 0 else "on")
        days = abs(offset)
        if offset == 0:
            window_line = f"Plant around the last-spring-frost date (~{frost['last_spring']}) in zone {z}."
        else:
            window_line = (f"Plant ~{days} days {direction} the last-spring-frost date "
                           f"(~{frost['last_spring']}) in zone {z}.")

    lines = [
        f"Planting — {crop_key.replace('_', ' ')} (zone {z}):",
        f"  • {window_line}",
        f"  • Soil temp at planting: ≥ {soil_t}°F.",
        f"  • Method: {method.replace('_', ' ')}; seed/tuber depth ≈ {depth} in.",
        f"  • Days to maturity: ~{dtm}.",
        f"  • First fall frost (zone {z}): ~{frost['first_fall']}.",
    ]
    if cal.get("notes"):
        lines.append(f"  • Note: {cal['notes']}")
    return "\n".join(lines)


@tool
def irrigation_schedule_tool(
    crop: str = "",
    stage: str = "mid",
    soil_type: str = "loam",
    climate: str = "temperate",
    days_since_rain: int = 0,
) -> str:
    """How much and how often to water a crop. Uses FAO-56 crop coefficients
    (Kc) and a rough reference ET₀ per climate to produce a weekly water
    depth (inches) and an irrigation frequency adjusted for soil type.
    Inputs: crop name; stage='initial'|'mid'|'late' (default mid); soil_type
    sandy/loam/clay/silty; climate tropical/subtropical/temperate/continental/
    mediterranean/arid/highland/boreal; days_since_rain (optional — increases
    recommended depth if >7)."""
    crop_key = _normalize_crop(crop)
    if not crop_key:
        return "Which crop?"
    kc_row = CROP_KC.get(crop_key)
    if not kc_row:
        return (f"No Kc data for '{crop}'. Covered: {', '.join(sorted(CROP_KC.keys()))}.")
    stage_key = stage.strip().lower() if stage else "mid"
    if stage_key not in ("initial", "mid", "late"):
        stage_key = "mid"
    kc = float(kc_row.get(stage_key, kc_row["mid"]))

    climate_key = (climate or "temperate").strip().lower()
    et0 = CLIMATE_ET0.get(climate_key, CLIMATE_ET0["temperate"])
    etc_daily = et0 * kc                          # inches/day
    weekly = etc_daily * 7                        # inches/week

    soil_key = (soil_type or "loam").strip().lower()
    soil_note = SOIL_NOTES.get(soil_key, SOIL_NOTES["loam"])
    if soil_key == "sandy":
        per_event = weekly / 3
        events_per_week = 3
    elif soil_key == "clay":
        per_event = weekly
        events_per_week = 1
    else:
        per_event = weekly / 2
        events_per_week = 2

    dry_bump = ""
    try:
        d = int(days_since_rain or 0)
        if d >= 10:
            per_event *= 1.25
            dry_bump = f" Boost +25 % — {d} days with no rain."
        elif d >= 7:
            per_event *= 1.1
            dry_bump = f" Boost +10 % — {d} dry days."
    except (TypeError, ValueError):
        pass

    lines = [
        f"Irrigation — {crop_key.replace('_', ' ')} ({stage_key} stage, "
        f"{soil_key} soil, {climate_key} climate):",
        f"  • Expected ET_c: ~{etc_daily:.2f} in/day  (ET₀≈{et0:.2f}, Kc={kc:.2f})",
        f"  • Weekly crop water need: ~{weekly:.2f} in.",
        f"  • Apply ~{per_event:.2f} in per event, {events_per_week}× per week.{dry_bump}",
        f"  • Soil note: {soil_note}",
        "  • Rain 'counts' 1:1 — subtract measured rainfall from the weekly target.",
    ]
    return "\n".join(lines)


@tool
def manure_pairing_tool(
    crop: str = "",
    available_manures: str = "",
) -> str:
    """Rank animal manures by how well they pair with a given crop. Ranking
    combines (1) N-P-K fit against the crop's appetite, (2) 'hot' vs 'cold'
    manure safety, and (3) crop-specific cautions (e.g., no fresh chicken
    on potatoes or carrots). Pass crop name. Optionally pass
    available_manures as a comma-separated list (e.g., "goat,chicken,cow_beef")
    to restrict ranking to what the farmer actually has on hand; leave
    empty to rank all known manures."""
    crop_key = _normalize_crop(crop)
    if not crop_key:
        return "Which crop are you fertilizing?"
    need = CROP_NEED.get(crop_key)
    if not need:
        return (f"No crop-need profile for '{crop}'. Covered: "
                f"{', '.join(sorted(CROP_NEED.keys()))}.")

    avail = [m.strip().lower() for m in (available_manures or "").split(",") if m.strip()]
    candidates = list(MANURE.items())
    if avail:
        candidates = [(k, v) for k, v in candidates if k in avail]
        if not candidates:
            return (f"None of those manures are in my reference set. Known: "
                    f"{', '.join(sorted(MANURE.keys()))}.")

    n_need = float(need["N"])
    p_need = float(need["P"])
    k_need = float(need["K"])
    total_need = n_need + p_need + k_need
    tags = set(need.get("tags") or [])
    prefers_composted = bool(need.get("prefers_composted"))

    scored = []
    for mk, m in candidates:
        # Fit score: similarity of manure NPK ratio to crop demand ratio.
        m_total = m["N"] + m["P2O5"] + m["K2O"]
        if m_total <= 0 or total_need <= 0:
            ratio_fit = 0.0
        else:
            m_r = (m["N"]/m_total, m["P2O5"]/m_total, m["K2O"]/m_total)
            n_r = (n_need/total_need, p_need/total_need, k_need/total_need)
            # inverse Manhattan distance, scaled 0..1
            dist = abs(m_r[0]-n_r[0]) + abs(m_r[1]-n_r[1]) + abs(m_r[2]-n_r[2])
            ratio_fit = max(0.0, 1.0 - dist)

        score = ratio_fit * 100.0  # 0..100
        caveats: List[str] = []

        if "N-fixer" in tags and m["N"] >= 2.0:
            score -= 25
            caveats.append("crop fixes its own N; high-N manure is wasted")

        if prefers_composted and m.get("hot"):
            score -= 10
            caveats.append("compost before applying")

        # Crop-specific avoid list
        crop_avoids = set(need.get("avoid") or [])
        if f"{mk}_fresh" in crop_avoids and m.get("hot"):
            score -= 40
            caveats.append(f"fresh {mk} is contraindicated for {crop_key}")

        scored.append({
            "manure":    mk,
            "score":     round(max(0.0, score), 1),
            "npk":       f"{m['N']:.1f}-{m['P2O5']:.1f}-{m['K2O']:.1f}",
            "hot":       bool(m.get("hot")),
            "note":      m.get("note", ""),
            "lbs_yr":    m.get("lbs_per_animal_year"),
            "caveats":   caveats,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    lines = [
        f"Manure pairing — {crop_key.replace('_', ' ')}  "
        f"(target NPK ≈ {int(n_need)}-{int(p_need)}-{int(k_need)} lbs/acre, "
        f"{need.get('appetite', 'medium')}):"
    ]
    for i, row in enumerate(scored[:6], start=1):
        hot = " (hot)" if row["hot"] else ""
        caveat_s = (" — " + "; ".join(row["caveats"])) if row["caveats"] else ""
        lbs = f" · ~{row['lbs_yr']:,} lbs/animal/yr" if row["lbs_yr"] else ""
        lines.append(
            f"  {i}. {row['manure']}{hot}  NPK {row['npk']}  "
            f"score {row['score']:.0f}{lbs}{caveat_s}"
        )
        if row["note"]:
            lines.append(f"       {row['note']}")
    if need.get("note"):
        lines.append(f"\n  Crop note: {need['note']}")
    return "\n".join(lines)


agronomy_tools = [
    planting_calendar_tool,
    irrigation_schedule_tool,
    manure_pairing_tool,
]
