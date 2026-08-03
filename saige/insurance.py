"""
Crop insurance finder (US federal RMA).

Curated reference to the major federal crop-insurance products handled by
the USDA Risk Management Agency (RMA). Answers the common questions:
- Which insurance plans cover my crop in my state?
- What's the difference between RP, YP, AYP, WFRP, LRP, LGM, PRF?
- How do I find an agent?

Not an agent directory — RMA runs the definitive one. We link out to it.
"""
from __future__ import annotations

from typing import Dict, List, Optional
from langchain_core.tools import tool


# ──────────────────────────────────────────────────────────────────
# Insurance products (RMA programs)
# ──────────────────────────────────────────────────────────────────
PRODUCTS: List[Dict] = [
    {
        "id": "rp",
        "name": "Revenue Protection (RP)",
        "covers": "Yield AND price loss — revenue guarantee based on Chicago futures.",
        "best_for": "Row crops with active futures markets: corn, soy, wheat, cotton, rice, sorghum, sunflower, canola.",
        "coverage_range": "50%–85% of revenue.",
        "notes": "Most popular product for program crops. Price is revised up at harvest "
                 "(harvest-price exclusion option available to lower premium).",
    },
    {
        "id": "yp",
        "name": "Yield Protection (YP)",
        "covers": "Yield loss only (no price component).",
        "best_for": "Producers who market independently and don't want price exposure in insurance.",
        "coverage_range": "50%–85% of approved yield.",
        "notes": "Cheaper than RP but leaves you exposed to price drops.",
    },
    {
        "id": "aph",
        "name": "Actual Production History (APH)",
        "covers": "Yield-based coverage using 4-10 year production records.",
        "best_for": "Crops without RP/YP — many specialty crops, pasture, apiculture.",
        "coverage_range": "50%–85% of APH yield.",
        "notes": "Baseline for most specialty-crop policies.",
    },
    {
        "id": "wfrp",
        "name": "Whole-Farm Revenue Protection (WFRP)",
        "covers": "Total farm revenue across ALL commodities, including livestock and specialty crops.",
        "best_for": "Diversified operations, specialty/organic/direct-market farms, beginning farmers.",
        "coverage_range": "50%–85% of approved whole-farm revenue, up to $17M.",
        "notes": "5-year Schedule F tax returns required. Premium subsidy up to 80%.",
    },
    {
        "id": "mp",
        "name": "Micro Farm Insurance",
        "covers": "Simplified whole-farm coverage for very small operations.",
        "best_for": "Farms with ≤$350K annual revenue; direct-market, specialty, beginning.",
        "coverage_range": "50%–85% of farm revenue, capped at $350K.",
        "notes": "One-page application; allows post-production value (wash/bag/deliver).",
    },
    {
        "id": "prf",
        "name": "Pasture, Rangeland, Forage (PRF)",
        "covers": "Rainfall-index protection for hay/grazing.",
        "best_for": "Ranchers, graziers, hay producers — ALL states.",
        "coverage_range": "70%–90% of county rainfall benchmark.",
        "notes": "Pays automatically when 2-month rainfall index comes in below selected trigger. "
                 "No yield records required.",
    },
    {
        "id": "lrp",
        "name": "Livestock Risk Protection (LRP)",
        "covers": "Declining market price on feeder cattle, fed cattle, swine, lamb.",
        "best_for": "Cow-calf, backgrounders, feedlots, hog producers.",
        "coverage_range": "70%–100% of expected end price.",
        "notes": "Functions like a put option — no need to deliver, settled on cash index.",
    },
    {
        "id": "lgm",
        "name": "Livestock Gross Margin (LGM)",
        "covers": "Margin between livestock sale price AND feed cost (corn/soy).",
        "best_for": "Dairy, swine, feeder cattle operations exposed to input-cost swings.",
        "coverage_range": "Dairy LGM: variable by month.",
        "notes": "Smooths income when feed costs rise faster than milk/meat prices.",
    },
    {
        "id": "dairy_drp",
        "name": "Dairy Revenue Protection (DRP)",
        "covers": "Dairy revenue (milk price × milk production).",
        "best_for": "All dairy operations, sold quarterly.",
        "coverage_range": "80%–95% of expected dairy revenue.",
        "notes": "Class III, Class IV, or component-priced options.",
    },
    {
        "id": "nap",
        "name": "Noninsured Crop Disaster Assistance (NAP) — FSA, not RMA",
        "covers": "Catastrophic-level disaster coverage for crops WITHOUT federal crop insurance.",
        "best_for": "Specialty and minor crops (most vegetables in most counties, forage, "
                    "Christmas trees, honey).",
        "coverage_range": "CAT: 50% yield × 55% price (free for beginners/socially disadvantaged); "
                          "buy-up up to 65% × 100% price.",
        "notes": "Apply at FSA, not crop-insurance agents. Catastrophic option is free for "
                 "beginning and historically underserved producers.",
    },
]


# ──────────────────────────────────────────────────────────────────
# Crop → typical products (what RMA offers in most states for this crop)
# ──────────────────────────────────────────────────────────────────
CROP_PRODUCTS = {
    "corn":         ["rp", "yp"],
    "soybean":      ["rp", "yp"],
    "wheat":        ["rp", "yp"],
    "cotton":       ["rp", "yp"],
    "rice":         ["rp", "yp"],
    "sorghum":      ["rp", "yp"],
    "sunflower":    ["rp", "yp"],
    "canola":       ["rp", "yp"],
    "barley":       ["rp", "yp"],
    "oat":          ["rp", "yp", "aph"],
    "peanut":       ["rp", "yp"],
    "apple":        ["aph", "wfrp"],
    "grape":        ["aph", "wfrp"],
    "blueberry":    ["aph", "wfrp"],
    "strawberry":   ["aph", "wfrp"],
    "tomato":       ["aph", "wfrp", "mp"],
    "potato":       ["aph", "rp"],
    "onion":        ["aph", "wfrp"],
    "pumpkin":      ["aph", "wfrp", "mp"],
    "sweet corn":   ["aph", "wfrp"],
    "pasture":      ["prf"],
    "hay":          ["prf"],
    "cattle":       ["lrp", "prf"],
    "feeder cattle":["lrp"],
    "dairy":        ["dairy_drp", "lgm"],
    "milk":         ["dairy_drp", "lgm"],
    "hog":          ["lrp", "lgm"],
    "swine":        ["lrp", "lgm"],
    "lamb":         ["lrp"],
    "honey":        ["nap", "wfrp"],
}

CROP_ALIASES = {
    "maize":        "corn",
    "soy":          "soybean",
    "soybeans":     "soybean",
    "beef":         "cattle",
    "pork":         "hog",
    "bees":         "honey",
    "apiculture":   "honey",
}


def _resolve_crop(name: str) -> Optional[str]:
    k = (name or "").strip().lower()
    if k in CROP_PRODUCTS:
        return k
    return CROP_ALIASES.get(k)


def get_product(pid: str) -> Optional[Dict]:
    for p in PRODUCTS:
        if p["id"] == pid:
            return p
    return None


def for_crop(crop: str) -> Dict:
    canon = _resolve_crop(crop)
    if not canon:
        return {
            "status": "not_supported",
            "crop": crop,
            "message": f"No canonical match for '{crop}'. Try a simpler crop name, or "
                        f"consider WFRP (whole-farm) which covers almost anything.",
        }
    pids = CROP_PRODUCTS.get(canon, [])
    return {
        "status": "ok",
        "crop": canon,
        "products": [get_product(pid) for pid in pids if get_product(pid)],
        "agent_finder_url": "https://www.rma.usda.gov/tools-reports/agent-locator-information-browser",
    }


def list_crops() -> List[str]:
    return sorted(CROP_PRODUCTS.keys())


def format_for_llm(crop: str) -> str:
    r = for_crop(crop)
    if r["status"] != "ok":
        return r.get("message", "No match.")
    lines = [f"Crop insurance options for {r['crop']}:"]
    for p in r["products"]:
        lines.append(f"\n• {p['name']} ({p['id'].upper()})")
        lines.append(f"  Covers: {p['covers']}")
        lines.append(f"  Best for: {p['best_for']}")
        lines.append(f"  Coverage: {p['coverage_range']}")
        if p.get("notes"):
            lines.append(f"  Notes: {p['notes']}")
    lines.append(f"\nFind an RMA-approved agent: {r['agent_finder_url']}")
    return "\n".join(lines)


@tool
def insurance_tool(crop: str) -> str:
    """Find US federal crop-insurance products for a specific crop/livestock.
    Supports row crops (corn, soybean, wheat, cotton, rice, etc.), specialty crops
    (apple, tomato, blueberry, etc.), pasture/forage, livestock (cattle, hog, dairy).
    Returns a list of matching RMA products (RP, YP, APH, WFRP, MP, PRF, LRP, LGM,
    DRP) with coverage ranges and usage notes, plus a link to the official agent
    locator. Use when a user asks about insurance, risk management, or disaster
    protection for a specific crop."""
    return format_for_llm(crop)


insurance_tools = [insurance_tool]
