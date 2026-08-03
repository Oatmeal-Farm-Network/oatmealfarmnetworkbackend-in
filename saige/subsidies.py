"""
Government subsidies / cost-share / grant finder (US federal).

Curated database of the major USDA and federal programs farmers can apply to.
Structured so the frontend can filter by: farm-type, practice category,
enterprise size, or region.

International programs (EU CAP, India PM-KISAN, Canada AgriStability) can
be added later — structure is identical.

Sources (public, 2024-2025):
- USDA Farm Service Agency program pages
- USDA NRCS EQIP/CSP fact sheets
- Rural Development program catalog
- Beginning Farmer & Rancher Development Program (BFRDP)
"""
from __future__ import annotations

from typing import Dict, List, Optional
from langchain_core.tools import tool


# category: conservation, income_support, disaster, beginning, organic, specialty, loans, research
PROGRAMS: List[Dict] = [
    {
        "id": "eqip",
        "name": "Environmental Quality Incentives Program (EQIP)",
        "agency": "USDA NRCS",
        "region": "US (all states + territories)",
        "category": "conservation",
        "who": "All producers — row-crop, livestock, specialty, forestry, beginning farmers.",
        "what": "Cost-share for conservation practices: cover crops, no-till, fencing, "
                "rotational grazing, irrigation efficiency, nutrient management, pollinator "
                "habitat. Typical share: 50-75% of practice cost; 90% for historically "
                "underserved producers. Multi-year contracts (1-10 yr).",
        "typical_award": "$1,500 - $500,000 per contract (most 10K–80K).",
        "how": "Apply at your local USDA Service Center (NRCS desk). Rolling sign-up; "
               "state NRCS batches applications 2-4 times a year.",
        "url": "https://www.nrcs.usda.gov/programs-initiatives/eqip-environmental-quality-incentives",
        "deadline": "Rolling; state batching cutoffs vary.",
    },
    {
        "id": "csp",
        "name": "Conservation Stewardship Program (CSP)",
        "agency": "USDA NRCS",
        "region": "US (all states + territories)",
        "category": "conservation",
        "who": "Producers already doing some conservation who want to take it further. "
                "Whole-farm / whole-operation, not single practices.",
        "what": "5-year contract paying you to maintain current conservation AND add new "
                "'enhancements' (100+ to choose from). Renewable for another 5 years.",
        "typical_award": "$1,500 minimum/yr; average $15–30/acre/yr; max $200K over 5 years.",
        "how": "Apply at local NRCS Service Center. Annual ranking windows.",
        "url": "https://www.nrcs.usda.gov/programs-initiatives/csp-conservation-stewardship-program",
        "deadline": "Annual sign-up period, typically Jan-Mar.",
    },
    {
        "id": "crp",
        "name": "Conservation Reserve Program (CRP)",
        "agency": "USDA FSA",
        "region": "US",
        "category": "conservation",
        "who": "Producers with environmentally sensitive land (erodible, near water, wildlife habitat).",
        "what": "10-15 year rental contracts to take land out of production, establish "
                "cover (grass, trees, pollinator mix, wetland). Annual rental payment + "
                "50% cost-share on establishment. Continuous CRP: smaller, targeted "
                "practices (buffers, wetlands) with no cutoff deadlines.",
        "typical_award": "Rental rates $40–300/acre/yr depending on county.",
        "how": "Apply at local FSA Service Center.",
        "url": "https://www.fsa.usda.gov/programs-and-services/conservation-programs/",
        "deadline": "General CRP signup: periodic. Continuous CRP: rolling.",
    },
    {
        "id": "arc_plc",
        "name": "Agriculture Risk Coverage (ARC) / Price Loss Coverage (PLC)",
        "agency": "USDA FSA",
        "region": "US",
        "category": "income_support",
        "who": "Producers of program crops: corn, soybean, wheat, rice, peanut, sorghum, "
                "barley, oats, cotton, pulses.",
        "what": "Counter-cyclical payments when revenue (ARC) or price (PLC) drops below "
                "benchmark. Elect annually per crop per farm.",
        "typical_award": "Varies widely with market — $0 in high-price years, $100+/acre in bad years.",
        "how": "Elect at FSA Service Center.",
        "url": "https://www.fsa.usda.gov/programs-and-services/arcplc_program/",
        "deadline": "Annual election; typically closes in mid-Mar.",
    },
    {
        "id": "noninsured_nap",
        "name": "Noninsured Crop Disaster Assistance (NAP)",
        "agency": "USDA FSA",
        "region": "US",
        "category": "disaster",
        "who": "Producers of crops NOT covered by federal crop insurance (specialty, minor crops).",
        "what": "Disaster coverage for yield loss >50% at CAT level (free for beginners "
                "and historically underserved); buy-up coverage also available.",
        "typical_award": "Indemnity paid on qualifying yield loss.",
        "how": "Apply at FSA Service Center BEFORE the crop's application closing date.",
        "url": "https://www.fsa.usda.gov/programs-and-services/disaster-assistance-program/noninsured-crop-disaster-assistance/",
        "deadline": "Crop-specific; typically pre-planting.",
    },
    {
        "id": "lfp_lip",
        "name": "Livestock Forage Disaster / Livestock Indemnity Programs (LFP/LIP)",
        "agency": "USDA FSA",
        "region": "US",
        "category": "disaster",
        "who": "Livestock producers with grazing loss (LFP) or animal death loss (LIP) "
                "from weather or predators.",
        "what": "LFP pays grazing-loss based on drought monitor or fire. LIP pays indemnity "
                "for animals killed by eligible adverse weather, disease, or predators.",
        "typical_award": "LIP: 75% fair market value of lost animals.",
        "how": "File a notice of loss and application at FSA within 30 days of loss.",
        "url": "https://www.fsa.usda.gov/programs-and-services/disaster-assistance-program/",
        "deadline": "30 days from loss event.",
    },
    {
        "id": "bfrdp",
        "name": "Beginning Farmer & Rancher Development Program (BFRDP)",
        "agency": "USDA NIFA",
        "region": "US",
        "category": "beginning",
        "who": "Beginning farmers (10 yr or less) AND organizations that serve them.",
        "what": "Funds education, mentoring, technical assistance for new farmers. Most "
                "grants go to nonprofits/extension who then deliver free training — "
                "search for BFRDP programs in your state.",
        "typical_award": "Organizational grants $50K–$600K; services are usually free to farmers.",
        "how": "Find a BFRDP-funded training provider near you via Start2Farm.gov.",
        "url": "https://nifa.usda.gov/program/beginning-farmer-and-rancher-development-program-bfrdp",
        "deadline": "Varies by grantee.",
    },
    {
        "id": "beginning_farmer_loan",
        "name": "Beginning Farmer & Rancher Direct Loans",
        "agency": "USDA FSA",
        "region": "US",
        "category": "loans",
        "who": "Beginning farmers (10 yr or less) + socially disadvantaged farmers.",
        "what": "Direct ownership loans up to $600K (real estate) + direct operating loans "
                "up to $400K. Low interest; below-commercial rates; down-payment program available.",
        "typical_award": "Up to $600K real estate / $400K operating.",
        "how": "Apply at local FSA Service Center.",
        "url": "https://www.fsa.usda.gov/programs-and-services/farm-loan-programs/",
        "deadline": "Rolling.",
    },
    {
        "id": "microloan",
        "name": "FSA Microloans",
        "agency": "USDA FSA",
        "region": "US",
        "category": "loans",
        "who": "Small/new farmers needing <$50K for operating or <$50K for ownership.",
        "what": "Streamlined application (short form), up to $50K for each category. "
                "Ideal for niche/urban/specialty operations.",
        "typical_award": "Up to $50K operating + $50K ownership.",
        "how": "Local FSA Service Center.",
        "url": "https://www.fsa.usda.gov/programs-and-services/farm-loan-programs/microloans/",
        "deadline": "Rolling.",
    },
    {
        "id": "osp",
        "name": "Organic Certification Cost Share Program (OCCSP)",
        "agency": "USDA AMS",
        "region": "US",
        "category": "organic",
        "who": "Producers/handlers who are USDA-certified organic or transitioning.",
        "what": "Reimburses 75% of annual certification cost, up to $750/category.",
        "typical_award": "Up to $750 per certification category per year.",
        "how": "Apply through your state department of agriculture or directly to AMS.",
        "url": "https://www.ams.usda.gov/services/grants/occsp",
        "deadline": "Annual; typically Oct 31.",
    },
    {
        "id": "otecp",
        "name": "Organic Transition Initiative (Transition Practices EQIP pool)",
        "agency": "USDA NRCS",
        "region": "US",
        "category": "organic",
        "who": "Producers transitioning to certified organic.",
        "what": "Dedicated EQIP funding pool for organic transition practices + a new "
                "multi-year Conservation Assistance contract for organic producers.",
        "typical_award": "Up to $140K over 5 years.",
        "how": "Apply at local NRCS Service Center; mention organic transition.",
        "url": "https://www.nrcs.usda.gov/conservation-basics/natural-resource-concerns/organic",
        "deadline": "Rolling; state batches.",
    },
    {
        "id": "vapg",
        "name": "Value-Added Producer Grant (VAPG)",
        "agency": "USDA Rural Development",
        "region": "US rural",
        "category": "specialty",
        "who": "Producers who add value to raw commodities (processing, branding, farm-to-table).",
        "what": "Planning grants up to $75K; working-capital grants up to $250K. 50% match "
                "required. Priority to beginning, socially-disadvantaged, veteran farmers.",
        "typical_award": "$75K planning / $250K working capital.",
        "how": "Apply through USDA Rural Development state office.",
        "url": "https://www.rd.usda.gov/programs-services/business-programs/value-added-producer-grants",
        "deadline": "Annual; typically winter/spring.",
    },
    {
        "id": "reap",
        "name": "Rural Energy for America Program (REAP)",
        "agency": "USDA Rural Development",
        "region": "US rural",
        "category": "specialty",
        "who": "Ag producers + rural small businesses.",
        "what": "Grants (up to 50% of cost, max $1M) and loan guarantees for renewable "
                "energy systems (solar, wind, biomass) and energy-efficiency upgrades.",
        "typical_award": "Grants up to $1M; guarantees up to $25M.",
        "how": "Apply through USDA RD state office.",
        "url": "https://www.rd.usda.gov/programs-services/energy-programs/rural-energy-america-program-renewable-energy-systems-energy-efficiency-improvement-guaranteed-loans",
        "deadline": "Quarterly application windows.",
    },
    {
        "id": "sare",
        "name": "SARE Farmer / Rancher Grants",
        "agency": "USDA NIFA (regional SARE)",
        "region": "US (four SARE regions)",
        "category": "research",
        "who": "Producers wanting to test a sustainable-ag innovation on-farm.",
        "what": "Grants to farmers who run their own research project (cover crop trial, "
                "new grazing system, marketing test). Report-back required.",
        "typical_award": "$10K–$30K depending on region.",
        "how": "Apply through your SARE regional office (Northeast, North Central, South, West).",
        "url": "https://www.sare.org/grants/",
        "deadline": "Annual; varies by region (Nov-Dec typical).",
    },
    {
        "id": "specialty_crop_block_grant",
        "name": "Specialty Crop Block Grant Program (SCBGP)",
        "agency": "USDA AMS (through state departments of ag)",
        "region": "US (all states)",
        "category": "specialty",
        "who": "Specialty crop producers + organizations (fruits, vegetables, nursery, floriculture, herbs).",
        "what": "Block grants to states; states re-grant to projects that enhance "
                "competitiveness of specialty crops.",
        "typical_award": "$25K–$250K.",
        "how": "Apply through your state department of agriculture.",
        "url": "https://www.ams.usda.gov/services/grants/scbgp",
        "deadline": "Annual; varies by state (spring-summer typical).",
    },
    {
        "id": "fdpir_lfpa",
        "name": "Local Food Purchase Assistance / Local Food for Schools",
        "agency": "USDA AMS",
        "region": "US",
        "category": "specialty",
        "who": "Small/mid-scale producers selling into local food systems.",
        "what": "Funds states and tribes to buy from local producers for food banks and schools. "
                "Not a direct-to-farmer grant — check your state AMS page for participating markets.",
        "typical_award": "N/A (sales channel).",
        "how": "Contact your state department of agriculture.",
        "url": "https://www.ams.usda.gov/services/grants/lfpa",
        "deadline": "Rolling through state programs.",
    },
]


CATEGORY_ALIASES = {
    "conservation":         "conservation",
    "conservation practice":"conservation",
    "cover crop":           "conservation",
    "grazing":              "conservation",
    "pollinator":           "conservation",
    "income":               "income_support",
    "income support":       "income_support",
    "price":                "income_support",
    "commodity":            "income_support",
    "disaster":             "disaster",
    "drought":              "disaster",
    "flood":                "disaster",
    "hail":                 "disaster",
    "beginning":            "beginning",
    "new farmer":           "beginning",
    "young farmer":         "beginning",
    "loan":                 "loans",
    "loans":                "loans",
    "credit":               "loans",
    "organic":              "organic",
    "transition":           "organic",
    "specialty":            "specialty",
    "specialty crop":       "specialty",
    "fruit":                "specialty",
    "vegetable":            "specialty",
    "value added":          "specialty",
    "value-added":          "specialty",
    "energy":               "specialty",
    "solar":                "specialty",
    "research":             "research",
    "trial":                "research",
    "on-farm":              "research",
}


try:
    from subsidies_intl import PROGRAMS as _INTL_PROGRAMS
except Exception as _e:
    print(f"[subsidies] international pack unavailable: {_e}")
    _INTL_PROGRAMS = []


# Merge US + international into a single catalog at module load. Give every
# US entry an explicit country='US' so filtering is symmetrical.
for _p in PROGRAMS:
    _p.setdefault("country", "US")
ALL_PROGRAMS: List[Dict] = PROGRAMS + list(_INTL_PROGRAMS)


def list_countries() -> List[str]:
    return sorted({p.get("country", "US") for p in ALL_PROGRAMS})


def list_categories(country: Optional[str] = None) -> List[str]:
    src = ALL_PROGRAMS if not country else [p for p in ALL_PROGRAMS if p.get("country") == country.upper()]
    return sorted({p["category"] for p in src})


def search(
    category: Optional[str] = None,
    keyword: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = 10,
) -> List[Dict]:
    cat = CATEGORY_ALIASES.get((category or "").strip().lower()) if category else None
    cc = (country or "").strip().upper() or None
    results = []
    for p in ALL_PROGRAMS:
        if cc and p.get("country", "US") != cc:
            continue
        if cat and p["category"] != cat:
            continue
        if keyword:
            haystack = " ".join([p["name"], p["who"], p["what"]]).lower()
            if keyword.lower() not in haystack:
                continue
        results.append(p)
        if len(results) >= limit:
            break
    return results


def get(program_id: str) -> Optional[Dict]:
    for p in ALL_PROGRAMS:
        if p["id"] == program_id:
            return p
    return None


def format_for_llm(category: str = "", keyword: str = "") -> str:
    results = search(category=category or None, keyword=keyword or None, limit=6)
    if not results:
        return (f"No matching programs found. Known categories: "
                f"{', '.join(list_categories())}.")
    lines = [f"Found {len(results)} programs:"]
    for p in results:
        lines.append(f"\n• {p['name']} ({p['agency']})")
        lines.append(f"  Category: {p['category']}")
        lines.append(f"  Who: {p['who']}")
        lines.append(f"  What: {p['what'][:180]}…" if len(p['what']) > 180 else f"  What: {p['what']}")
        lines.append(f"  Typical award: {p['typical_award']}")
        lines.append(f"  How: {p['how']}")
        lines.append(f"  More: {p['url']}")
    return "\n".join(lines)


@tool
def subsidies_tool(category: str = "", keyword: str = "") -> str:
    """Find US federal farm subsidy / grant / cost-share programs.
    category: conservation, income_support, disaster, beginning, loans, organic,
        specialty, research (synonyms like 'cover crop', 'new farmer', 'solar' also
        accepted).
    keyword: free-text search in program name/description (e.g., 'pollinator',
        'irrigation', 'beginning farmer').
    Returns a list of matching programs with agency, eligibility, typical award,
    and how to apply. Use when a user asks about government funding, cost-share,
    grants, or low-interest farm loans."""
    return format_for_llm(category, keyword)


subsidies_tools = [subsidies_tool]
