"""
International subsidy programs (non-US).

Currently covers Canada (federal + provincial-aggregate) and the EU
Common Agricultural Policy. Extended exactly like subsidies.py so the
two datasets merge cleanly at module load.

Sources (public, 2024-2025):
- Agriculture and Agri-Food Canada (AAFC) program catalog
- Canadian Agricultural Partnership / Sustainable CAP
- European Commission CAP 2023-2027 fact sheets
- individual national CAP strategic plans
"""
from __future__ import annotations

from typing import Dict, List


PROGRAMS: List[Dict] = [
    # ──────────────────────────── CANADA ────────────────────────────
    {
        "id": "ca_agristability",
        "country": "CA",
        "name": "AgriStability",
        "agency": "Agriculture and Agri-Food Canada (AAFC)",
        "region": "Canada (all provinces & territories)",
        "category": "income_support",
        "who": "Producers of any commodity (crops, livestock, horticulture).",
        "what": "Margin-based income support. Pays when your program margin "
                "drops more than 30% below your reference margin (average of "
                "prior years).",
        "typical_award": "Variable — based on your margin loss; caps per farm apply.",
        "how": "Enrol through the provincial delivery agent (varies by province). "
               "Annual enrolment deadline typically April 30.",
        "url": "https://agriculture.canada.ca/en/programs/agristability",
        "deadline": "Enrolment by April 30 each year.",
    },
    {
        "id": "ca_agriinvest",
        "country": "CA",
        "name": "AgriInvest",
        "agency": "AAFC",
        "region": "Canada",
        "category": "income_support",
        "who": "All farmers with allowable net sales.",
        "what": "Matched savings account. Deposit up to 100% of your allowable net "
                "sales; government matches the first 1% up to C$10,000/yr. Use funds "
                "for small income declines or on-farm investment.",
        "typical_award": "Max C$10,000/yr in matching contributions.",
        "how": "File through CRA / AAFC once your taxes are filed.",
        "url": "https://agriculture.canada.ca/en/programs/agriinvest",
        "deadline": "Ongoing — tied to tax filing.",
    },
    {
        "id": "ca_agriinsurance",
        "country": "CA",
        "name": "AgriInsurance (production insurance)",
        "agency": "Provinces (delivered under AAFC framework)",
        "region": "Canada",
        "category": "disaster",
        "who": "Crop, horticulture, and (in some provinces) livestock producers.",
        "what": "Province-administered crop insurance covering weather & disease "
                "production losses. Product names vary (AFSC in AB, SCIC in SK, MASC in MB).",
        "typical_award": "Premium-subsidized; payouts when yields fall below insured thresholds.",
        "how": "Apply via provincial crown corp — deadlines are pre-planting.",
        "url": "https://agriculture.canada.ca/en/programs/agriinsurance",
        "deadline": "Pre-planting, typically March 31 (varies by province).",
    },
    {
        "id": "ca_agrirecovery",
        "country": "CA",
        "name": "AgriRecovery",
        "agency": "AAFC (federal-provincial)",
        "region": "Canada",
        "category": "disaster",
        "who": "Producers in declared disaster areas.",
        "what": "Ad-hoc disaster payments when losses exceed the other BRM programs — "
                "triggered by drought, flood, wildfire, disease outbreaks.",
        "typical_award": "Event-specific.",
        "how": "No pre-enrolment — payment delivered after government assessment.",
        "url": "https://agriculture.canada.ca/en/programs/agrirecovery",
        "deadline": "Event-driven.",
    },
    {
        "id": "ca_scap",
        "country": "CA",
        "name": "Sustainable Canadian Agricultural Partnership (Sustainable CAP)",
        "agency": "AAFC + provinces",
        "region": "Canada",
        "category": "conservation",
        "who": "Varies by provincial program menu.",
        "what": "Cost-share for on-farm climate / environmental projects, business "
                "risk management add-ons, market development. Funds are delivered "
                "through ~20 provincially-designed programs.",
        "typical_award": "$5,000 – $500,000 depending on stream.",
        "how": "Look up your province's Sustainable CAP portal.",
        "url": "https://agriculture.canada.ca/en/department/initiatives/sustainable-canadian-agricultural-partnership",
        "deadline": "Rolling / provincial deadlines.",
    },
    {
        "id": "ca_ocaaf",
        "country": "CA",
        "name": "On-Farm Climate Action Fund",
        "agency": "AAFC",
        "region": "Canada",
        "category": "conservation",
        "who": "Producers adopting cover crops, rotational grazing, or nitrogen management.",
        "what": "Cost-share for BMPs that reduce GHG emissions — cover cropping, "
                "nutrient-management planning, rotational grazing infrastructure.",
        "typical_award": "Up to C$75,000 per producer.",
        "how": "Delivered via regional recipient organizations (ag producer groups).",
        "url": "https://agriculture.canada.ca/en/agricultural-programs-and-services/farm-climate-action-fund",
        "deadline": "Call-based.",
    },
    {
        "id": "ca_youngfarmers",
        "country": "CA",
        "name": "Canadian Agricultural Loans Act (CALA) — Young Farmers",
        "agency": "AAFC / FCC / partner lenders",
        "region": "Canada",
        "category": "beginning",
        "who": "Farmers under 40 or taking over an operation.",
        "what": "Government loan guarantee on up to C$500K of financing for land, "
                "equipment, and operating needs.",
        "typical_award": "Guarantee on loans up to C$500,000.",
        "how": "Apply through a participating lender (banks, credit unions, FCC).",
        "url": "https://agriculture.canada.ca/en/programs/canadian-agricultural-loans-act-program",
        "deadline": "Ongoing.",
    },

    # ───────────────────── EUROPEAN UNION (CAP) ─────────────────────
    {
        "id": "eu_bisscs",
        "country": "EU",
        "name": "Basic Income Support for Sustainability (BISS)",
        "agency": "European Commission / National Paying Agencies",
        "region": "EU27",
        "category": "income_support",
        "who": "Active farmers in EU member states.",
        "what": "Core Pillar-1 direct payment. Per-hectare income support with "
                "conditionality (crop rotation, permanent grassland, "
                "non-productive features).",
        "typical_award": "€150 – €350 per hectare, varying by member state.",
        "how": "Apply through the national / regional paying agency. Annual "
               "single application in spring.",
        "url": "https://agriculture.ec.europa.eu/common-agricultural-policy/income-support/basic-income-support_en",
        "deadline": "Annual — typically May 15 in most member states.",
    },
    {
        "id": "eu_ecoscheme",
        "country": "EU",
        "name": "CAP Eco-Scheme",
        "agency": "European Commission / National Paying Agencies",
        "region": "EU27",
        "category": "conservation",
        "who": "Farmers receiving BISS who adopt eligible climate / environment practices.",
        "what": "Voluntary Pillar-1 top-up for going beyond conditionality — organic, "
                "agroforestry, precision nutrient management, pollinator strips.",
        "typical_award": "€40 – €200 per hectare, per practice, varies by country.",
        "how": "Declared in the annual single application alongside BISS.",
        "url": "https://agriculture.ec.europa.eu/common-agricultural-policy/income-support/eco-schemes_en",
        "deadline": "Annual single application.",
    },
    {
        "id": "eu_capsr_ym",
        "country": "EU",
        "name": "CAP — Young Farmer Top-Up & Setup Grant",
        "agency": "National Paying Agencies (CAP Strategic Plans)",
        "region": "EU27",
        "category": "beginning",
        "who": "New entrants under 40 taking over or starting a farm.",
        "what": "Per-hectare top-up for up to 5 years + lump-sum setup aid for "
                "first-time farmers (amount set by each member state).",
        "typical_award": "€30-€100/ha top-up + setup grants €25K-€100K.",
        "how": "National / regional rural development office.",
        "url": "https://agriculture.ec.europa.eu/common-agricultural-policy/income-support/additional-income-support/young-farmers_en",
        "deadline": "Call-based + annual SA window.",
    },
    {
        "id": "eu_organic_conv",
        "country": "EU",
        "name": "CAP Organic Farming Support",
        "agency": "National Paying Agencies",
        "region": "EU27",
        "category": "organic",
        "who": "Farmers converting to or maintaining certified organic production.",
        "what": "Per-hectare payment for conversion (higher, 3-5 yrs) and "
                "maintenance phases. Combined with eco-scheme in many MS.",
        "typical_award": "€200 – €900 per hectare depending on crop and phase.",
        "how": "Rural development paying agency — multi-year contract.",
        "url": "https://agriculture.ec.europa.eu/farming/organic-farming/organic-action-plan_en",
        "deadline": "Annual.",
    },
    {
        "id": "eu_ania",
        "country": "EU",
        "name": "ANC — Areas with Natural Constraints payment",
        "agency": "National Paying Agencies",
        "region": "EU27",
        "category": "income_support",
        "who": "Farmers in mountain / less-favoured / biophysically-constrained areas.",
        "what": "Per-hectare payment compensating for production handicap (altitude, "
                "slope, poor soils, cold climate).",
        "typical_award": "€25 – €250/ha.",
        "how": "Automatic if your parcels are classified as ANC; declared annually.",
        "url": "https://agriculture.ec.europa.eu/common-agricultural-policy/rural-development_en",
        "deadline": "Annual.",
    },
    {
        "id": "eu_leader",
        "country": "EU",
        "name": "LEADER / Community-Led Local Development",
        "agency": "Local Action Groups under CAP Pillar 2",
        "region": "EU27 rural areas",
        "category": "research",
        "who": "Farm diversification, rural business, food-chain, agritourism.",
        "what": "Bottom-up grants administered by Local Action Groups (LAGs) for "
                "rural-development projects. ~€50K–€300K typical.",
        "typical_award": "€20K – €500K depending on LAG.",
        "how": "Apply to your region's LAG; calls recurring.",
        "url": "https://agriculture.ec.europa.eu/common-agricultural-policy/rural-development/leader-clld_en",
        "deadline": "LAG-specific rolling calls.",
    },
]
