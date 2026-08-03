"""
Soil challenge assessment.

Given soil-test numbers (pH, nitrogen/phosphorus/potassium, organic matter,
moisture, salinity, CEC, bulk density), diagnose the top challenges and
return specific remediation advice.

Thresholds come from standard US/EU extension agronomy ranges. For very
specialty crops (blueberry, cranberry, rice) some thresholds differ and
are noted in the output.
"""
from __future__ import annotations

from typing import Dict, List, Optional
from langchain_core.tools import tool


# ──────────────────────────────────────────────────────────────────
# Thresholds
# ──────────────────────────────────────────────────────────────────
# Values here are defaults for general row-crop / vegetable production.
# Acidophile crops override in CROP_OVERRIDES.

DEFAULT_THRESHOLDS = {
    "ph": {"low": 6.0, "high": 7.5, "severe_low": 5.0, "severe_high": 8.5},
    "organic_matter_pct": {"low": 2.0, "severe_low": 1.0},     # %
    "nitrogen_ppm": {"low": 20, "severe_low": 10},              # NO3-N ppm
    "phosphorus_ppm": {"low": 25, "severe_low": 10, "high": 100, "severe_high": 200},  # Bray-1 ppm
    "potassium_ppm": {"low": 120, "severe_low": 80, "high": 300, "severe_high": 500},  # ppm
    "cec_meq": {"low": 8, "severe_low": 4},                     # meq/100g
    "salinity_dsm": {"high": 2.0, "severe_high": 4.0},          # EC dS/m
    "moisture_pct": {"low": 15, "severe_low": 8, "high": 35, "severe_high": 45},
    "bulk_density_gcc": {"high": 1.4, "severe_high": 1.6},      # g/cc (compaction)
    "sodium_pct_cec": {"high": 5, "severe_high": 15},           # ESP %
}

CROP_OVERRIDES = {
    "blueberry":  {"ph": {"low": 4.5, "high": 5.5}},
    "cranberry":  {"ph": {"low": 4.0, "high": 5.5}},
    "azalea":     {"ph": {"low": 4.5, "high": 6.0}},
    "rhododendron":{"ph": {"low": 4.5, "high": 6.0}},
    "potato":     {"ph": {"low": 5.0, "high": 6.5}},   # scab suppression
    "alfalfa":    {"ph": {"low": 6.5, "high": 7.5}},
    "asparagus":  {"ph": {"low": 6.5, "high": 7.5}},
    "rice":       {"moisture_pct": {"low": 60, "high": 100}},  # flooded
}


# ──────────────────────────────────────────────────────────────────
# Remediation playbook
# ──────────────────────────────────────────────────────────────────
REMEDIATION = {
    "ph_low": [
        "Apply agricultural lime: 1-3 tons/acre for 0.5-1.0 pH unit lift on loam (less on sand, more on clay).",
        "Dolomitic lime if magnesium is also low; calcitic lime if magnesium is adequate.",
        "Wood ash at 20-40 lb/1000 sqft is a fast-acting alternative for small plots.",
        "Re-test pH 6 months after application; lime is slow (12-18 mo to full effect).",
    ],
    "ph_high": [
        "Apply elemental sulfur: 0.5-2.0 lb/100 sqft to drop 1 pH unit on loam.",
        "Use ammonium-based nitrogen fertilizers (ammonium sulfate) — they acidify over time.",
        "Incorporate acidic mulch (pine needles, peat moss) for sensitive crops.",
        "Do NOT try to drop high-pH alkaline soils below 7.0 quickly — rebounds hard.",
    ],
    "organic_matter_low": [
        "Grow cover crops every off-season (rye, vetch, buckwheat, tillage radish).",
        "Apply 1-2 inches of compost annually — builds OM ~0.1-0.2% per year.",
        "Reduce tillage — every pass oxidizes 5-15% of OM.",
        "Leave crop residue on surface rather than removing or burning.",
        "Consider perennial crops or hay in rotation — root turnover builds OM 3-5× faster.",
    ],
    "nitrogen_low": [
        "Side-dress with urea (46-0-0) at 50-80 lb N/acre for heavy-feeder crops.",
        "For organic systems: blood meal (12-0-0), fish emulsion, feather meal.",
        "Plant a nitrogen-fixing cover crop (crimson clover, hairy vetch, field pea).",
        "Check drainage — saturated soils denitrify even when N is adequate.",
    ],
    "phosphorus_low": [
        "Apply rock phosphate (0-3-0) or bone meal (3-15-0) — slow release, organic-approved.",
        "Mycorrhizal inoculation helps plants access existing soil P.",
        "Note: P moves slowly in soil; surface applications are less effective — incorporate.",
    ],
    "phosphorus_high": [
        "Phosphorus-only runoff from over-fertilized soils causes algal blooms — stop all P application.",
        "Plant cover crops with high P uptake (buckwheat, mustard, corn) to draw down reserves.",
        "Avoid manure with high P content (poultry, swine); compost helps reduce P leaching.",
    ],
    "potassium_low": [
        "Apply potassium sulfate (0-0-50) at 50-100 lb K2O/acre for deficient fields.",
        "For organic: kelp meal, wood ash (careful — raises pH), or greensand (slow).",
        "Potassium leaches on sandy soils — split applications rather than one big dose.",
    ],
    "potassium_high": [
        "High K blocks Mg and Ca uptake; check for induced deficiencies.",
        "Rotate with high-K demand crops (alfalfa, banana) to draw down.",
        "Stop K applications; irrigation will gradually leach surplus on well-drained soils.",
    ],
    "cec_low": [
        "Low CEC (<8) typical of sandy soils — limited nutrient holding.",
        "Build OM aggressively; every 1% OM adds ~2 meq/100g CEC.",
        "Split fertilizer applications — one big dose leaches past roots quickly.",
        "Use drip irrigation to reduce leaching losses.",
    ],
    "salinity_high": [
        "Leach salts with deep irrigation (apply 6+ inches over 1-2 weeks) if drainage allows.",
        "Install tile drainage if leaching water has nowhere to go.",
        "Switch to salt-tolerant crops: barley, quinoa, sugar beet, date palm, some tomato varieties.",
        "Avoid foliar irrigation with saline water — burns leaves directly.",
    ],
    "moisture_low": [
        "Mulch bare soil — 2-4 in reduces evaporation 70%.",
        "Switch to drip irrigation for 90% efficiency vs 65% for sprinkler.",
        "Select drought-tolerant varieties for chronic low-water fields.",
        "Check for hardpan / compaction — roots can't reach deep moisture.",
    ],
    "moisture_high": [
        "Install tile drainage if chronically saturated.",
        "Raise beds 8-12 inches to lift root zone above water table.",
        "Plant cover crops (rye, oats) to transpire excess water between cash-crop seasons.",
        "Avoid working saturated soils — compaction risk is highest.",
    ],
    "bulk_density_high": [
        "Soil is compacted. Deep-rip or sub-soil on 18-24 in centers when moisture is correct.",
        "Plant tap-rooted cover crops (tillage radish, chicory, alfalfa) to biologically loosen.",
        "Reduce traffic — every wheel pass on moist soil adds compaction.",
        "Controlled traffic farming (fixed lanes) prevents new compaction.",
    ],
    "sodium_high": [
        "Apply gypsum (calcium sulfate) at 2-5 tons/acre to displace Na on exchange sites.",
        "After gypsum, leach heavily if drainage allows.",
        "Sodic soils (>15% ESP) have severely degraded structure — reclamation takes 3-5 years.",
        "Plant sodium-tolerant cover crops (sweet clover, alfalfa) during reclamation.",
    ],
}


# ──────────────────────────────────────────────────────────────────
# Core assessment
# ──────────────────────────────────────────────────────────────────
def _get_thresholds(crop: Optional[str]) -> Dict:
    thresh = {k: dict(v) for k, v in DEFAULT_THRESHOLDS.items()}
    if crop:
        override = CROP_OVERRIDES.get(crop.lower().strip())
        if override:
            for k, v in override.items():
                thresh.setdefault(k, {})
                thresh[k].update(v)
    return thresh


def _check(measure: str, value: float, t: Dict) -> Optional[Dict]:
    """Compare one measurement to thresholds; return a challenge dict or None."""
    low = t.get("low")
    high = t.get("high")
    sev_low = t.get("severe_low")
    sev_high = t.get("severe_high")

    if sev_low is not None and value < sev_low:
        return {"severity": "severe", "direction": "low", "value": value}
    if low is not None and value < low:
        return {"severity": "moderate", "direction": "low", "value": value}
    if sev_high is not None and value > sev_high:
        return {"severity": "severe", "direction": "high", "value": value}
    if high is not None and value > high:
        return {"severity": "moderate", "direction": "high", "value": value}
    return None


def assess(
    ph: Optional[float] = None,
    organic_matter_pct: Optional[float] = None,
    nitrogen_ppm: Optional[float] = None,
    phosphorus_ppm: Optional[float] = None,
    potassium_ppm: Optional[float] = None,
    cec_meq: Optional[float] = None,
    salinity_dsm: Optional[float] = None,
    moisture_pct: Optional[float] = None,
    bulk_density_gcc: Optional[float] = None,
    sodium_pct_cec: Optional[float] = None,
    crop: Optional[str] = None,
) -> Dict:
    """Run the full assessment. Any parameter left as None is skipped."""
    thresh = _get_thresholds(crop)
    inputs = {
        "ph": ph,
        "organic_matter_pct": organic_matter_pct,
        "nitrogen_ppm": nitrogen_ppm,
        "phosphorus_ppm": phosphorus_ppm,
        "potassium_ppm": potassium_ppm,
        "cec_meq": cec_meq,
        "salinity_dsm": salinity_dsm,
        "moisture_pct": moisture_pct,
        "bulk_density_gcc": bulk_density_gcc,
        "sodium_pct_cec": sodium_pct_cec,
    }

    challenges: List[Dict] = []

    for measure, value in inputs.items():
        if value is None:
            continue
        t = thresh.get(measure)
        if not t:
            continue
        result = _check(measure, value, t)
        if result:
            # Map to remediation key
            rem_key = {
                ("ph", "low"):                    "ph_low",
                ("ph", "high"):                   "ph_high",
                ("organic_matter_pct", "low"):    "organic_matter_low",
                ("nitrogen_ppm", "low"):          "nitrogen_low",
                ("phosphorus_ppm", "low"):        "phosphorus_low",
                ("phosphorus_ppm", "high"):       "phosphorus_high",
                ("potassium_ppm", "low"):         "potassium_low",
                ("potassium_ppm", "high"):        "potassium_high",
                ("cec_meq", "low"):               "cec_low",
                ("salinity_dsm", "high"):         "salinity_high",
                ("moisture_pct", "low"):          "moisture_low",
                ("moisture_pct", "high"):         "moisture_high",
                ("bulk_density_gcc", "high"):     "bulk_density_high",
                ("sodium_pct_cec", "high"):       "sodium_high",
            }.get((measure, result["direction"]))

            challenges.append({
                "measure": measure,
                "value": result["value"],
                "direction": result["direction"],
                "severity": result["severity"],
                "remediation": REMEDIATION.get(rem_key, []) if rem_key else [],
                "summary": _summary_for(measure, result["direction"], result["severity"]),
            })

    # Sort severe-first
    challenges.sort(key=lambda c: (0 if c["severity"] == "severe" else 1, c["measure"]))

    if not challenges and any(v is not None for v in inputs.values()):
        return {
            "status": "ok",
            "challenges": [],
            "headline": "No significant soil challenges detected — values are in healthy ranges.",
        }
    if not challenges:
        return {
            "status": "no_inputs",
            "headline": "No soil measurements provided.",
            "challenges": [],
        }

    return {
        "status": "challenges_found",
        "headline": f"{len(challenges)} challenge{'s' if len(challenges) != 1 else ''} detected.",
        "challenges": challenges,
    }


def _summary_for(measure: str, direction: str, severity: str) -> str:
    pretty = measure.replace("_", " ").replace(" pct cec", " (% of CEC)") \
                    .replace(" dsm", " (dS/m)") \
                    .replace(" gcc", " (g/cc)") \
                    .replace(" meq", " (meq/100g)") \
                    .replace(" pct", " (%)")
    d = "below healthy range" if direction == "low" else "above healthy range"
    prefix = "SEVERE: " if severity == "severe" else ""
    return f"{prefix}{pretty} is {d}"


def format_for_llm(**kwargs) -> str:
    result = assess(**kwargs)
    if result["status"] == "no_inputs":
        return ("No soil measurements provided. Share values like pH, nitrogen ppm, "
                "phosphorus ppm, potassium ppm, organic matter %, moisture %.")
    if result["status"] == "ok":
        return result["headline"]

    lines = [result["headline"]]
    for c in result["challenges"]:
        lines.append(f"\n• {c['summary']} (value={c['value']}, severity={c['severity']})")
        for step in c["remediation"][:3]:
            lines.append(f"    - {step}")
    return "\n".join(lines)


@tool
def soil_challenge_tool(
    ph: float = -1.0,
    organic_matter_pct: float = -1.0,
    nitrogen_ppm: float = -1.0,
    phosphorus_ppm: float = -1.0,
    potassium_ppm: float = -1.0,
    cec_meq: float = -1.0,
    salinity_dsm: float = -1.0,
    moisture_pct: float = -1.0,
    bulk_density_gcc: float = -1.0,
    sodium_pct_cec: float = -1.0,
    crop: str = "",
) -> str:
    """Diagnose soil challenges from a soil-test report and return remediation steps.
    Pass any subset of: ph, organic_matter_pct, nitrogen_ppm, phosphorus_ppm,
    potassium_ppm, cec_meq, salinity_dsm, moisture_pct, bulk_density_gcc, sodium_pct_cec.
    Use -1 (or omit) for unknown values. Pass `crop` name to apply crop-specific
    thresholds (e.g., blueberry needs pH 4.5-5.5, not 6.0-7.5). Use when a user
    shares soil-test results or asks 'what's wrong with my soil'."""
    def norm(v):
        return None if v is None or v < 0 else v
    return format_for_llm(
        ph=norm(ph),
        organic_matter_pct=norm(organic_matter_pct),
        nitrogen_ppm=norm(nitrogen_ppm),
        phosphorus_ppm=norm(phosphorus_ppm),
        potassium_ppm=norm(potassium_ppm),
        cec_meq=norm(cec_meq),
        salinity_dsm=norm(salinity_dsm),
        moisture_pct=norm(moisture_pct),
        bulk_density_gcc=norm(bulk_density_gcc),
        sodium_pct_cec=norm(sodium_pct_cec),
        crop=crop or None,
    )


soil_challenge_tools = [soil_challenge_tool]
