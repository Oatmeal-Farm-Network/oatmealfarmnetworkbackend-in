"""
Weather-extreme mitigation advisor.

Rules-based playbook: given a hazard (frost, drought, heat, flood, hail, wind,
wildfire_smoke) and optionally a crop and a phase (planning, imminent, active,
recovery), produce concrete mitigation steps.

Sources: USDA Extension guides, FAO field manuals, Rodale Organic, NDSU Hail
Recovery bulletins, NOAA climate-smart agriculture briefs.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from langchain_core.tools import tool


# ──────────────────────────────────────────────────────────────────
# Hazard playbooks
# ──────────────────────────────────────────────────────────────────
# Structure: hazard → phase → list of concrete steps (string or
# (condition_tag, step) tuple — condition_tag is matched against crop).
HAZARD_PLAYBOOKS: Dict[str, Dict[str, List]] = {
    "frost": {
        "planning": [
            "Identify last-frost date for your location; delay transplanting until 10 days after.",
            "Choose frost-tolerant varieties for shoulder-season plantings.",
            "Site tender crops on south-facing slopes or near thermal mass (walls, ponds).",
            "Plant on raised beds — cold air drains to low spots.",
        ],
        "imminent": [
            "Water soil thoroughly the afternoon before — wet soil retains ~4× more heat than dry.",
            "Cover tender crops with frost blankets (Agribon AG-19 or heavier) by sunset.",
            "For tall crops, drape row cover over hoops — don't let fabric touch leaves.",
            "Run sprinklers through the freeze only if you can sustain irrigation until thaw (latent-heat method).",
            "Harvest anything fully mature that won't survive the forecast.",
            "Light smudge pots / orchard heaters in high-value blocks (permit-dependent).",
            "Turn on a bucket of water with a pond-aeration pump under a covered tomato — 1-2 °F lift.",
        ],
        "active": [
            "Do NOT wash frost off leaves at sunrise — rapid thawing ruptures cells and causes the real damage.",
            "Keep row covers on until ambient temperature rises above 32 °F.",
        ],
        "recovery": [
            "Wait 3-5 days before assessing damage — frost injury takes time to reveal.",
            "Prune out blackened tissue only after new growth shows where live buds remain.",
            "Side-dress with a light nitrogen application to push replacement growth.",
            "Replant frost-killed direct-seeded rows (beans, squash, corn) within 10 days if season allows.",
        ],
    },

    "drought": {
        "planning": [
            "Add 2-4 inches of organic mulch; every 1% OM increase ≈ 20,000 gal/acre water-holding capacity.",
            "Plant drought-tolerant varieties (dryland corn, sorghum, cowpea, tepary bean, heritage dry-farm tomato).",
            "Install drip irrigation — 90% efficiency vs 65% for sprinklers.",
            "Reduce planting density by 20-30% under dryland/deficit conditions.",
            "Build swales on contour; plant cover-crop rotations that add OM.",
        ],
        "imminent": [
            "Shift irrigation to night or early morning to cut evaporation loss.",
            "Mulch bare soil immediately — straw, woodchip, landscape fabric, or living cover.",
            "Thin overcrowded rows so remaining plants get more root zone per drop.",
            "Apply kaolin clay (Surround WP) to reduce leaf transpiration on high-value fruit crops.",
            "Delay optional side-dressing of N — salt drives stress without water to move it.",
        ],
        "active": [
            "Prioritize irrigation water on crops in their most sensitive phase: pollination > fruit-fill > early veg.",
            "Abandon or haying-off the weakest field is sometimes the best ROI — don't spread water too thin.",
            "Switch livestock to drought-reserve pastures; cull lowest-performing animals early.",
            "Monitor wells daily; coordinate with neighbors to avoid aquifer crash.",
        ],
        "recovery": [
            "Soil-test before fall planting — drought leaves salts concentrated in root zone.",
            "Plant a drought-recovery cover crop (winter rye + crimson clover) to rebuild OM.",
            "Budget next year's plan around 60-70% of normal yield assumption until aquifer recharges.",
        ],
    },

    "heat": {
        "planning": [
            "Choose heat-tolerant varieties (Heatmaster tomato, cowpea, okra, amaranth, Jericho lettuce).",
            "Install 30-50% shade cloth over lettuce/brassicas for summer production.",
            "Time plantings so sensitive crops flower outside peak-heat window.",
            "Build agroforestry — alley cropping or wind-break trees drop understory temperature 5-10 °F.",
        ],
        "imminent": [
            "Deep-water 24-48h before forecast heat wave — water cools the root zone for days.",
            "Deploy shade cloth or row cover over sensitive crops.",
            "Reschedule transplanting to after the heat wave passes.",
            "Move livestock to shaded paddocks; fill water troughs to overflow.",
        ],
        "active": [
            "Water early morning AND evening during extreme heat (>95 °F) — split irrigation prevents stress spike.",
            "Do not spray pesticides/herbicides during heat — phytotoxicity risk is 3-5× normal.",
            "Mist livestock with sprinklers (cattle, pigs); add electrolytes to poultry water.",
            "Skip any optional fieldwork — soil compaction and plant handling stress compounds.",
            "Check for blossom drop on tomato/pepper: >92 °F days + >75 °F nights = pollen sterility.",
        ],
        "recovery": [
            "Irrigate deeply once temperatures drop — crops may resume growth within 48h.",
            "Side-dress with compost tea / fish emulsion to push recovery.",
            "Remove aborted fruit to redirect energy.",
        ],
    },

    "flood": {
        "planning": [
            "Install tile drainage in chronically wet fields; design for 100-year event, not 10-year.",
            "Keep 10-25 ft vegetated buffer along waterways to slow runoff and filter sediment.",
            "Raise bed height 8-12 inches in floodplain fields.",
            "Avoid permanent infrastructure (irrigation mains, high tunnels) in the 50-year floodplain.",
        ],
        "imminent": [
            "Harvest any mature crop within 48h if possible — flooded produce is UNFIT for human consumption (FDA).",
            "Move equipment, chemicals, and livestock out of floodplain.",
            "Check and clear culverts / field drains.",
            "Document pre-flood field condition with photos for insurance.",
        ],
        "active": [
            "Do not drive machinery on saturated ground — compaction lasts 5-10 years.",
            "Keep livestock out of flooded pasture (anthrax, Pythium, leptospirosis risk).",
        ],
        "recovery": [
            "FDA rule: any edible crop that CONTACTED floodwater is adulterated and must be destroyed.",
            "Crops >30 days from harvest when floodwater receded may be saleable if no further contact — consult local extension.",
            "Test soil for pathogens (E. coli, heavy metals) before replanting in flooded zones.",
            "Plant a cleanup cover crop (sorghum-sudangrass, buckwheat) to restore aggregation.",
            "Wait 60 days between floodwater recession and replanting edible crops.",
            "File crop insurance claim within 72 hours of loss event.",
        ],
    },

    "hail": {
        "planning": [
            "Install hail netting (15-20 year payback on orchards; 3-5 year on high-tunnel veg).",
            "Diversify crop plantings across multiple fields — hail paths are often narrow (<1 mi wide).",
            "Check crop-hail insurance policies annually — coverage gaps are common.",
        ],
        "imminent": [
            "Deploy any deployable shade/hail cloth.",
            "Move livestock to shelter with solid roof (not just tree cover).",
            "Park equipment in barns.",
        ],
        "recovery": [
            "Wait 3-5 days before fully assessing damage — leaf death takes time to show.",
            "Defoliation assessment: <30% loss typically yields normally; 30-60% loss = reduced yield; >60% = consider replant.",
            "Corn pre-V6 can re-grow from growing point; post-V6 damage to growing point = terminal.",
            "Fungicide application within 7 days of hail reduces secondary infection on stressed crops.",
            "Prune broken branches on tree crops cleanly below the break within 10 days.",
            "File crop-hail insurance claim within 72 hours — most policies have tight windows.",
            "Document every field with photos and GPS tags.",
        ],
    },

    "wind": {
        "planning": [
            "Plant windbreaks perpendicular to prevailing winds — reduces ET 20-40% for 10× tree-height downwind.",
            "Trellis tall crops (tomato, pepper, pole bean) — wind-whip kills more plants than frost in some regions.",
            "Avoid aluminum/plastic row cover in exposed fields — it becomes a projectile.",
        ],
        "imminent": [
            "Stake and tie tall crops; remove or lay flat any loose row cover.",
            "Secure high-tunnel end-walls and close vents before gusts arrive.",
            "Empty or move grain bags and silage piles that can catch wind.",
        ],
        "recovery": [
            "Re-stake leaning plants within 48h; soil settles around roots quickly.",
            "Inspect trellises for broken hardware before next crop cycle.",
        ],
    },

    "wildfire_smoke": {
        "planning": [
            "Register for state smoke-alert and air-quality notifications.",
            "Invest in N95/P100 respirators for farm crew — wildfire-season standard PPE.",
        ],
        "imminent": [
            "If PM2.5 forecast > 150 µg/m³, reschedule outdoor labor to early morning.",
            "Move sensitive livestock (horses, young poultry) indoors with filtered air if available.",
            "Cover water troughs and open grain to reduce ash deposition.",
        ],
        "active": [
            "Grapes and wine: test for smoke taint (guaiacol, 4-methylguaiacol) before harvest.",
            "Wash leafy greens thoroughly if ash-dusted; avoid fruit with heavy ash on broken skin.",
            "Photosynthesis drops 15-30% under heavy smoke — extend maturity expectations.",
            "Monitor livestock for coughing, eye discharge; dusty feed + smoke can trigger pneumonia.",
        ],
        "recovery": [
            "Test soils in ash-fall zones for heavy metals before replanting.",
            "Expect pollinator populations to be depressed for 2-4 weeks post-smoke.",
        ],
    },

    "cold_snap": {
        "planning": [
            "Plant cold-hardy cover crops (winter rye, hairy vetch) for over-winter protection.",
            "Insulate water lines to barn/coop; install tank de-icers.",
            "Stock bedding (straw, shavings) for livestock to 2× estimated need.",
        ],
        "imminent": [
            "Top off all water tanks and stock 3 days of grain indoors.",
            "Install windbreak fabric on exposed barn sides.",
            "Increase feed ration 10-20% the day before cold arrives — digestion generates heat.",
        ],
        "active": [
            "Check livestock water 2-3×/day; frozen water kills faster than cold.",
            "Dry bedding is the #1 insulation — wet straw is worse than none.",
            "Monitor newborn livestock hourly in <20 °F; hypothermia sets in within 30 min of birth.",
        ],
        "recovery": [
            "Let plants warm gradually — no rushing into greenhouses with cold-injured transplants.",
            "Inspect water lines / plumbing at first thaw for freeze breaks.",
        ],
    },
}


HAZARD_ALIASES = {
    "freeze":           "frost",
    "frost":            "frost",
    "cold":             "cold_snap",
    "cold snap":        "cold_snap",
    "cold_snap":        "cold_snap",
    "drought":          "drought",
    "dry":              "drought",
    "water shortage":   "drought",
    "heat":             "heat",
    "heatwave":         "heat",
    "heat wave":        "heat",
    "extreme heat":     "heat",
    "flood":            "flood",
    "flooding":         "flood",
    "high water":       "flood",
    "hail":             "hail",
    "hailstorm":        "hail",
    "wind":             "wind",
    "windstorm":        "wind",
    "high wind":        "wind",
    "smoke":            "wildfire_smoke",
    "wildfire":         "wildfire_smoke",
    "wildfire smoke":   "wildfire_smoke",
    "wildfire_smoke":   "wildfire_smoke",
    "poor air quality": "wildfire_smoke",
}

PHASE_ALIASES = {
    "planning":     "planning",
    "prepare":      "planning",
    "preparation":  "planning",
    "before":       "planning",
    "imminent":     "imminent",
    "incoming":     "imminent",
    "forecast":     "imminent",
    "warning":      "imminent",
    "during":       "active",
    "active":       "active",
    "in progress":  "active",
    "after":        "recovery",
    "recovery":     "recovery",
    "aftermath":    "recovery",
    "damage":       "recovery",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def resolve_hazard(name: str) -> Optional[str]:
    return HAZARD_ALIASES.get(_norm(name))


def resolve_phase(name: str) -> str:
    if not name:
        return "imminent"
    return PHASE_ALIASES.get(_norm(name), "imminent")


def get_plan(hazard: str, phase: str = "imminent") -> Optional[Dict]:
    h = resolve_hazard(hazard)
    if not h:
        return None
    p = resolve_phase(phase)
    book = HAZARD_PLAYBOOKS.get(h, {})
    steps = book.get(p, [])
    return {
        "hazard": h,
        "phase": p,
        "steps": [s if isinstance(s, str) else s[1] for s in steps],
        "all_phases": list(book.keys()),
    }


def list_hazards() -> List[str]:
    return sorted(HAZARD_PLAYBOOKS.keys())


def format_for_llm(hazard: str, phase: str = "imminent") -> str:
    plan = get_plan(hazard, phase)
    if not plan:
        return (
            f"No mitigation plan for '{hazard}'. "
            f"Known hazards: {', '.join(list_hazards())}."
        )
    lines = [f"Mitigation plan — {plan['hazard']} ({plan['phase']} phase):"]
    for i, step in enumerate(plan["steps"], 1):
        lines.append(f"  {i}. {step}")
    lines.append(f"(Other phases available: {', '.join(plan['all_phases'])})")
    return "\n".join(lines)


@tool
def weather_mitigation_tool(hazard: str, phase: str = "imminent") -> str:
    """Produce a concrete mitigation / response plan for a weather hazard.
    hazard: one of frost, drought, heat, flood, hail, wind, wildfire_smoke, cold_snap
        (common synonyms accepted).
    phase: 'planning' (before season), 'imminent' (forecast 0-72h out),
        'active' (happening now), 'recovery' (after event). Defaults to 'imminent'.
    Use whenever the user asks what to do before/during/after extreme weather."""
    return format_for_llm(hazard, phase)


weather_mitigation_tools = [weather_mitigation_tool]
