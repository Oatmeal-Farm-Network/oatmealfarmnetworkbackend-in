"""
Knowledge-base tools for Saige — plant catalog, ingredient catalog, and animal detail.

Covers:
- Plant catalog: Plant, PlantVariety with all growing-condition lookups
  (soil texture, pH, organic matter, salinity, hardiness zone, humidity,
  water requirements) and nutrient requirements via NutrientLookup.
- Ingredient catalog: Ingredients, IngredientsVarieties, IngredientCategoryLookup,
  IngredientNutrient.
- Animal detail: full profile for a specific animal on the user's farm,
  aggregating Animals + Colors + Pricing + AnimalRegistration.

Plant and ingredient data are global (not per-business). Animal detail is
access-controlled: only animals whose BusinessID matches the current user's
businesses are returned.
"""
from __future__ import annotations

import os
from typing import List, Optional, Dict, Any
from langchain_core.tools import tool

from config import DB_CONFIG

try:
    import pymssql
    _PMS_AVAILABLE = True
except ImportError:
    _PMS_AVAILABLE = False

try:
    import requests as _requests
    _REQ_AVAILABLE = True
except ImportError:
    _REQ_AVAILABLE = False

_BACKEND_URL = os.getenv("OFN_BACKEND_URL", "http://localhost:8000").rstrip("/")
_HTTP_TIMEOUT = 10


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _connect():
    if not _PMS_AVAILABLE or not all([DB_CONFIG.get("host"), DB_CONFIG.get("user"), DB_CONFIG.get("database")]):
        return None
    try:
        return pymssql.connect(
            server=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
            as_dict=True,
        )
    except Exception as e:
        print(f"[knowledge_base] DB connect failed: {e}")
        return None


def _query(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = _connect()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        rows = cursor.fetchall() or []
        # pymssql's as_dict=True preserves the exact column-alias casing from
        # the SQL (e.g. "PlantID"), but every tool in this module reads keys
        # in lowercase (e.g. row["plantid"]). Normalize here so callers don't
        # have to worry about casing and every accessor keeps working.
        return [{k.lower(): v for k, v in row.items()} for row in rows]
    except Exception as e:
        print(f"[knowledge_base] query error: {e}")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _business_ids_for_people(people_id: Optional[str]) -> List[int]:
    if not people_id:
        return []
    rows = _query(
        "SELECT BusinessID FROM dbo.BusinessAccess WHERE PeopleID = %s AND (Active IS NULL OR Active = 1)",
        (str(people_id),),
    )
    return [int(r["businessid"]) for r in rows if r.get("businessid") is not None]


def _fmt(v, digits: int = 2) -> str:
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _trunc(s: Optional[str], n: int = 160) -> str:
    if not s:
        return ""
    s = s.strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"


# ---------------------------------------------------------------------------
# TOOL 1 — search_plants_tool
# ---------------------------------------------------------------------------

@tool
def search_plants_tool(query: str = "", plant_type: str = "") -> str:
    """Search the OFN plant catalog by name or type. Returns a list of matching
    plants with their ID, type, variety count, and description. Use when the
    user asks "what plants do you have data on", "find plants named garlic",
    "show me all grain plants", "list herbs in the catalog", "what vegetables
    are in the system". plant_type must be one of: Vegetable, Herb, Fruit,
    Legume, Nut, Grain, Mushroom, Root, Tubers, Leafy Green — or leave blank
    to search all types. Follow up with get_plant_detail_tool using the
    PlantID to get soil/climate/nutrient requirements for a specific plant."""
    conditions = ["PT.Edible = 'True'"]
    params: list = []

    if plant_type:
        conditions.append("PT.PlantType = %s")
        params.append(str(plant_type))
    if query:
        conditions.append("P.PlantName LIKE %s")
        params.append(f"%{query}%")

    where = " AND ".join(conditions)
    rows = _query(
        f"SELECT TOP 50 P.PlantID, P.PlantName, P.PlantDescription, PT.PlantType, "
        f"       COUNT(PV.PlantVarietyID) AS VarietyCount "
        f"FROM Plant P "
        f"JOIN PlantTypeLookup PT ON P.PlantTypeID = PT.PlantTypeID "
        f"LEFT JOIN PlantVariety PV ON PV.PlantID = P.PlantID "
        f"WHERE {where} "
        f"GROUP BY P.PlantID, P.PlantName, P.PlantDescription, PT.PlantType "
        f"ORDER BY PT.PlantType, P.PlantName",
        tuple(params),
    )
    if not rows:
        scope = f'"{query}"' if query else plant_type or "all types"
        return f"No plants found matching {scope}. Try a broader search or check the plant type spelling."

    lines = [f"Plants found ({len(rows)}):"]
    current_type = None
    for r in rows:
        ptype = r.get("planttype") or "Unknown"
        if ptype != current_type:
            lines.append(f"\n  {ptype}:")
            current_type = ptype
        vc = r.get("varietycount") or 0
        desc = _trunc(r.get("plantdescription"), 100)
        desc_part = f" — {desc}" if desc else ""
        lines.append(f"    • #{r['plantid']} {r.get('plantname') or 'Unnamed'} ({vc} {'variety' if vc == 1 else 'varieties'}){desc_part}")

    lines.append(f"\nUse get_plant_detail_tool(plant_id=<ID>) for soil, climate, water, and nutrient requirements.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TOOL 2 — get_plant_detail_tool
# ---------------------------------------------------------------------------

@tool
def get_plant_detail_tool(plant_id: int) -> str:
    """Get the full agronomic profile for a specific plant — all varieties with
    their soil texture requirement, ideal pH range, organic matter level,
    salinity tolerance, USDA hardiness zone, humidity classification, water
    requirements (inches/week), and primary nutrient need. Use when the user
    asks "what soil does kale need", "what's the pH range for tomatoes",
    "water requirements for corn", "what zone does this plant grow in", "what
    nutrient does this crop need most". Requires plant_id from
    search_plants_tool. Also explains each soil/climate condition in plain
    language so the farmer understands what it means for their operation."""
    plant_rows = _query(
        "SELECT P.PlantID, P.PlantName, P.PlantDescription, PT.PlantType "
        "FROM Plant P JOIN PlantTypeLookup PT ON P.PlantTypeID = PT.PlantTypeID "
        "WHERE P.PlantID = %s",
        (int(plant_id),),
    )
    if not plant_rows:
        return f"Plant #{plant_id} not found in the catalog. Use search_plants_tool to find valid plant IDs."

    plant = plant_rows[0]
    varieties = _query(
        "SELECT PV.PlantVarietyID, PV.PlantVarietyName, PV.PlantVarietyDescription, "
        "       ST.SoilTexture, ST.Description AS SoilDesc, "
        "       PH.PHRange, PH.SoilType AS PHType, PH.Description AS PHDesc, "
        "       OM.OrganicMatterContent, OM.ImportanceToSoilAndPlants AS OMImportance, "
        "       SL.SalinityLevel, SL.Classification AS SalinityClass, SL.ImpactOnPlants AS SalinityImpact, "
        "       PHZ.Zone, PHZ.TemperatureStartRange, PHZ.TemperatureEndRange, "
        "       H.Classification AS HumidityClass, H.ImpactOnPlants AS HumidityImpact, "
        "       PV.WaterRequirementMin, PV.WaterRequirementMax, "
        "       NL.Nutrient AS PrimaryNutrient, NL.ImportanceToPlants AS NutrientImportance "
        "FROM PlantVariety PV "
        "LEFT JOIN SoilTextureLookup ST ON PV.SoilTextureID = ST.SoilTextureID "
        "LEFT JOIN PHRangeLookup PH ON PV.PHRangeID = PH.PHRangeID "
        "LEFT JOIN OrganicMatterLookup OM ON PV.OrganicMatterID = OM.OrganicMatterID "
        "LEFT JOIN SalinityLookup SL ON PV.SalinityLevelID = SL.SalinityLevelID "
        "LEFT JOIN PlantHardinessZoneLookup PHZ ON PV.ZoneID = PHZ.ZoneID "
        "LEFT JOIN HumidityLookup H ON PV.HumidityID = H.HumidityID "
        "LEFT JOIN NutrientLookup NL ON PV.PlantNutrientID = NL.NutrientID "
        "WHERE PV.PlantID = %s "
        "ORDER BY PV.PlantVarietyName",
        (int(plant_id),),
    )

    pname = plant.get("plantname") or "Unnamed"
    ptype = plant.get("planttype") or ""
    pdesc = _trunc(plant.get("plantdescription"), 200)

    lines = [
        f"Plant: {pname} ({ptype})",
    ]
    if pdesc:
        lines.append(f"Description: {pdesc}")
    lines.append(f"Varieties: {len(varieties)}")

    if not varieties:
        lines.append("No variety data available yet for this plant.")
        return "\n".join(lines)

    # Group varieties and show requirements
    # If many varieties share the same requirements, summarize
    for v in varieties[:20]:
        vname = v.get("plantvarietyname") or "Unnamed variety"
        vdesc = _trunc(v.get("plantvarietydescription"), 120)
        lines.append(f"\n  ── {vname} (ID #{v['plantvarietyid']})" + (f" — {vdesc}" if vdesc else ""))

        soil = v.get("soiltexture")
        ph = v.get("phrange")
        ph_type = v.get("phtype")
        om = v.get("organicmattercontent")
        sal = v.get("salinitylevel")
        sal_class = v.get("salinityclass")
        zone = v.get("zone")
        t_lo = v.get("temperaturestartrange")
        t_hi = v.get("temperatureendrange")
        humid = v.get("humidityclass")
        w_min = v.get("waterrequirementmin")
        w_max = v.get("waterrequirementmax")
        nutrient = v.get("primarynutrient")

        if soil:
            lines.append(f"     Soil texture:    {soil}")
            sd = _trunc(v.get("soildesc"), 80)
            if sd:
                lines.append(f"                      {sd}")
        if ph:
            ph_str = f"{ph}"
            if ph_type:
                ph_str += f" ({ph_type})"
            lines.append(f"     Soil pH:         {ph_str}")
        if om:
            lines.append(f"     Organic matter:  {om}")
        if sal:
            sal_str = f"{sal} dS/m"
            if sal_class:
                sal_str += f" — {sal_class}"
            lines.append(f"     Salinity:        {sal_str}")
            si = _trunc(v.get("salinityimpact"), 80)
            if si:
                lines.append(f"                      {si}")
        if zone:
            zone_str = f"Zone {zone}"
            if t_lo is not None and t_hi is not None:
                zone_str += f" ({t_lo}°F to {t_hi}°F)"
            lines.append(f"     Hardiness zone:  {zone_str}")
        if humid:
            lines.append(f"     Humidity:        {humid}")
            hi = _trunc(v.get("humidityimpact"), 80)
            if hi:
                lines.append(f"                      {hi}")
        if w_min is not None or w_max is not None:
            w_lo = _fmt(w_min, 2) if w_min is not None else "?"
            w_hi = _fmt(w_max, 2) if w_max is not None else "?"
            lines.append(f"     Water need:      {w_lo}–{w_hi} in/week")
        if nutrient:
            lines.append(f"     Key nutrient:    {nutrient}")
            ni = _trunc(v.get("nutrientimportance"), 100)
            if ni:
                lines.append(f"                      {ni}")

    if len(varieties) > 20:
        lines.append(f"\n  …and {len(varieties) - 20} more varieties. Ask about a specific variety by name for details.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TOOL 3 — search_ingredients_tool
# ---------------------------------------------------------------------------

@tool
def search_ingredients_tool(query: str = "", category: str = "") -> str:
    """Search the OFN ingredient catalog by name or category. Returns matching
    ingredients with their ID, category, variety count, and description. Use
    when the user asks "what vegetables are in the ingredient catalog",
    "find ingredients named garlic", "show me all meat ingredients", "what
    grain ingredients do we carry", "search for herbs in the system". category
    examples: Vegetable, Fruit, Herb, Meat, Grain, Dairy, Legume, Nut,
    Mushroom, Seafood, etc. Follow up with get_ingredient_detail_tool using
    the IngredientID for full variety and nutrient information."""
    conditions: list[str] = []
    params: list = []

    if category:
        conditions.append("ICL.IngredientCategory LIKE %s")
        params.append(f"%{category}%")
    if query:
        conditions.append("I.IngredientName LIKE %s")
        params.append(f"%{query}%")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = _query(
        f"SELECT TOP 60 I.IngredientID, I.IngredientName, I.IngredientDescription, "
        f"       ICL.IngredientCategory, "
        f"       COUNT(IV.IngredientVarietyPK) AS VarietyCount "
        f"FROM Ingredients I "
        f"LEFT JOIN IngredientCategoryLookup ICL ON I.IngredientCategoryID = ICL.IngredientCategoryID "
        f"LEFT JOIN IngredientsVarieties IV ON IV.IngredientID = I.IngredientID "
        f"{where} "
        f"GROUP BY I.IngredientID, I.IngredientName, I.IngredientDescription, ICL.IngredientCategory "
        f"ORDER BY ICL.IngredientCategory, I.IngredientName",
        tuple(params),
    )
    if not rows:
        scope = f'"{query}"' if query else category or "all categories"
        return f"No ingredients found matching {scope}. Try a broader search term."

    lines = [f"Ingredients found ({len(rows)}):"]
    current_cat = None
    for r in rows:
        cat = r.get("ingredientcategory") or "Uncategorized"
        if cat != current_cat:
            lines.append(f"\n  {cat}:")
            current_cat = cat
        vc = r.get("varietycount") or 0
        desc = _trunc(r.get("ingredientdescription"), 80)
        desc_part = f" — {desc}" if desc else ""
        lines.append(f"    • #{r['ingredientid']} {r.get('ingredientname') or 'Unnamed'} ({vc} {'variety' if vc == 1 else 'varieties'}){desc_part}")

    lines.append(f"\nUse get_ingredient_detail_tool(ingredient_id=<ID>) for full variety and nutrient details.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TOOL 4 — get_ingredient_detail_tool
# ---------------------------------------------------------------------------

@tool
def get_ingredient_detail_tool(ingredient_id: int) -> str:
    """Get the full profile of a specific ingredient — all varieties, their
    descriptions, and nutrient data. Use when the user wants deep information
    on a specific ingredient: "what varieties of garlic are there?", "what
    nutrients does this ingredient have?", "tell me more about black angus beef
    as an ingredient", "what are the varieties of heirloom tomatoes?". Requires
    ingredient_id from search_ingredients_tool."""
    ing_rows = _query(
        "SELECT I.IngredientID, I.IngredientName, I.IngredientDescription, "
        "       ICL.IngredientCategory "
        "FROM Ingredients I "
        "LEFT JOIN IngredientCategoryLookup ICL ON I.IngredientCategoryID = ICL.IngredientCategoryID "
        "WHERE I.IngredientID = %s",
        (int(ingredient_id),),
    )
    if not ing_rows:
        return f"Ingredient #{ingredient_id} not found. Use search_ingredients_tool to find valid ingredient IDs."

    ing = ing_rows[0]
    varieties = _query(
        "SELECT IV.IngredientVarietyPK, IV.IngredientName AS VarietyName, "
        "       IV.IngredientDescription AS VarietyDesc "
        "FROM IngredientsVarieties IV "
        "WHERE IV.IngredientID = %s "
        "ORDER BY IV.IngredientName",
        (int(ingredient_id),),
    )

    # Per-variety nutrients
    variety_ids = [v["ingredientvarietypk"] for v in varieties if v.get("ingredientvarietypk") is not None]
    nutrients_by_variety: Dict[int, List[str]] = {}
    if variety_ids:
        placeholders = ",".join(["%s"] * len(variety_ids))
        nut_rows = _query(
            f"SELECT IN2.IngredientVarietyPK, NL.Nutrient "
            f"FROM IngredientNutrient IN2 "
            f"JOIN NutrientLookup NL ON IN2.NutrientID = NL.NutrientID "
            f"WHERE IN2.IngredientVarietyPK IN ({placeholders}) "
            f"ORDER BY NL.Nutrient",
            tuple(variety_ids),
        )
        for nr in nut_rows:
            vid = nr.get("ingredientvarietypk")
            if vid is not None:
                nutrients_by_variety.setdefault(int(vid), []).append(nr.get("nutrient") or "")

    iname = ing.get("ingredientname") or "Unnamed"
    icat = ing.get("ingredientcategory") or ""
    idesc = _trunc(ing.get("ingredientdescription"), 200)

    lines = [
        f"Ingredient: {iname}" + (f" ({icat})" if icat else ""),
    ]
    if idesc:
        lines.append(f"Description: {idesc}")
    lines.append(f"Varieties: {len(varieties)}")

    if not varieties:
        lines.append("No variety data on file for this ingredient.")
        return "\n".join(lines)

    for v in varieties[:25]:
        vid = v.get("ingredientvarietypk")
        vname = v.get("varietyname") or "Unnamed variety"
        vdesc = _trunc(v.get("varietydesc"), 120)
        nuts = nutrients_by_variety.get(int(vid), []) if vid is not None else []
        nut_str = f" | Nutrients: {', '.join(nuts)}" if nuts else ""
        lines.append(f"  • #{vid} {vname}" + (f" — {vdesc}" if vdesc else "") + nut_str)

    if len(varieties) > 25:
        lines.append(f"  …and {len(varieties) - 25} more varieties.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TOOL 5 — get_animal_detail_tool
# ---------------------------------------------------------------------------

@tool
def get_animal_detail_tool(animal_id: int, people_id: str = "") -> str:
    """Get the full profile of a specific animal on the farm — name, sex,
    DOB, breed, colors, pricing (sale price, stud fee, embryo/semen price),
    registration numbers, fiber stats, and co-owner info. Use when the user
    asks about a specific animal by ID or wants richer detail than the list
    provides: "tell me more about animal #42", "what's the price on that
    alpaca?", "what registrations does my ram have?", "show me the fiber data
    for that animal". people_id is injected from session state — do not pass it.
    Returns an error if the animal does not belong to the user's business."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot look up animal — your account is not linked to any business."

    # Fetch base animal row and verify business ownership
    placeholders = ",".join(["%s"] * len(biz_ids))
    rows = _query(
        f"SELECT a.AnimalID, a.FullName, a.Nickname, a.DOB, a.Sex, a.BusinessID, "
        f"       a.SpeciesCategoryID, a.PublishForSale, a.PublishAtStud, "
        f"       a.CoOwnerName1, a.CoOwnerName2, a.Description, "
        f"       c.Color1, c.Color2, c.Color3 "
        f"FROM Animals a "
        f"LEFT JOIN Colors c ON c.AnimalID = a.AnimalID "
        f"WHERE a.AnimalID = %s AND a.BusinessID IN ({placeholders})",
        (int(animal_id), *biz_ids),
    )
    if not rows:
        return (f"Animal #{animal_id} was not found or does not belong to your business. "
                "Use list_my_animals_tool to see your animals and their IDs.")

    a = rows[0]

    # Fetch pricing
    pricing = _query("SELECT Price, StudFee, EmbryoPrice, SemenPrice, PriceComments, Financeterms, Sold, Free "
                     "FROM Pricing WHERE AnimalID = %s", (int(animal_id),))
    p = pricing[0] if pricing else {}

    # Fetch registrations
    regs = _query("SELECT RegType, RegNumber FROM AnimalRegistration WHERE AnimalID = %s ORDER BY RegType",
                  (int(animal_id),))

    # Fetch fiber data
    fiber = _query("SELECT * FROM Fiber WHERE AnimalID = %s", (int(animal_id),))
    f_row = fiber[0] if fiber else {}

    # Fetch breed info via SpeciesCategory
    breed_info = ""
    if a.get("speciescategoryid"):
        bc = _query("SELECT SpeciesCategory FROM speciescategory WHERE SpeciesCategoryID = %s",
                    (int(a["speciescategoryid"]),))
        if bc:
            breed_info = bc[0].get("speciescategory") or ""

    name = a.get("fullname") or f"Animal #{animal_id}"
    nick = a.get("nickname")
    sex = a.get("sex") or "Unknown"
    dob_raw = a.get("dob")
    dob = str(dob_raw).split(" ")[0].split("T")[0] if dob_raw else "—"
    desc = _trunc(a.get("description"), 200)

    lines = [f"Animal #{animal_id} — {name}" + (f' "{nick}"' if nick else "")]

    if breed_info:
        lines.append(f"Breed/Category: {breed_info}")
    lines.append(f"Sex:            {sex}")
    lines.append(f"DOB:            {dob}")

    colors = [c for c in [a.get("color1"), a.get("color2"), a.get("color3")] if c]
    if colors:
        lines.append(f"Colors:         {', '.join(colors)}")

    # Listing status
    for_sale = bool(a.get("publishforsale"))
    at_stud = bool(a.get("publishatstud"))
    status_parts = []
    if for_sale:
        status_parts.append("For Sale")
    if at_stud:
        status_parts.append("At Stud")
    if status_parts:
        lines.append(f"Listed as:      {', '.join(status_parts)}")

    # Pricing
    def _money(v):
        try:
            return f"${float(v):,.2f}"
        except (TypeError, ValueError):
            return None

    price_parts = []
    if _money(p.get("price")):
        price_parts.append(f"Sale {_money(p['price'])}")
    if _money(p.get("studfee")):
        price_parts.append(f"Stud fee {_money(p['studfee'])}")
    if _money(p.get("embryoprice")):
        price_parts.append(f"Embryo {_money(p['embryoprice'])}")
    if _money(p.get("semenprice")):
        price_parts.append(f"Semen {_money(p['semenprice'])}")
    if price_parts:
        lines.append(f"Pricing:        {' · '.join(price_parts)}")
    pc = p.get("pricecomments") or p.get("financeterms")
    if pc:
        lines.append(f"Price notes:    {_trunc(str(pc), 120)}")
    if p.get("sold"):
        lines.append("Status:         SOLD")
    elif p.get("free"):
        lines.append("Status:         FREE / no charge")

    # Registrations
    if regs:
        reg_strs = [f"{r.get('regtype') or '?'}: {r.get('regnumber') or '?'}" for r in regs]
        lines.append(f"Registrations:  {' · '.join(reg_strs)}")

    # Fiber
    fiber_fields = {
        "MicronAvg": ("AFD", "µm"),
        "StandardDeviation": ("SD", "µm"),
        "CoefficientOfVariation": ("CV", "%"),
        "ComfortFactor": ("CF", "%"),
        "SpinFineness": ("SF", "N/tex"),
        "CurvatureAvg": ("Curve", "°/mm"),
    }
    fiber_parts = []
    for col, (label, unit) in fiber_fields.items():
        v = f_row.get(col.lower()) or f_row.get(col)
        if v is not None:
            try:
                fiber_parts.append(f"{label}: {float(v):.2f} {unit}")
            except (TypeError, ValueError):
                pass
    if fiber_parts:
        lines.append(f"Fiber stats:    {' · '.join(fiber_parts)}")

    # Co-owners
    co_owners = [a.get("coownername1"), a.get("coownername2")]
    co_owners = [c for c in co_owners if c]
    if co_owners:
        lines.append(f"Co-owners:      {', '.join(co_owners)}")

    if desc:
        lines.append(f"\nDescription: {desc}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool list (imported by nodes.py)
# ---------------------------------------------------------------------------

knowledge_base_tools = [
    search_plants_tool,
    get_plant_detail_tool,
    search_ingredients_tool,
    get_ingredient_detail_tool,
    get_animal_detail_tool,
]
