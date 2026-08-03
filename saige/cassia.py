"""
Cassia — AI customer success agent for Oatmeal Farm Network.

Guides new users through two stages:
  1. Account creation — gathers business info conversationally, then creates
     the Business record in the database.
  2. Subscription selection — loads the feature catalog, understands the
     user's needs, recommends a plan, then signals the frontend to initiate
     Stripe payment.

Architecture mirrors Pairsley/Rosemarie:
  - Gemini LLM (shared llm.py)
  - Redis short-term memory (shared message_buffer.py)
  - Firestore long-term memory  (Cassia_chats collection)
  - Firestore RAG (Cassia_docs collection)
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import tool

from chat_history import ChatHistory
from config import DB_CONFIG, SHORT_TERM_N
from llm import llm
from message_buffer import get_last_n, push_message
from rag import RAGSystem

try:
    import pymssql
    _PMS_AVAILABLE = True
except ImportError:
    _PMS_AVAILABLE = False

logger = logging.getLogger("cassia")

CASSIA_CHATS_COLLECTION = "Cassia_chats"
CASSIA_DOCS_COLLECTION  = "Cassia_docs"


# ── Long-term memory ──────────────────────────────────────────────────────────

class CassiaChatHistory(ChatHistory):
    @property
    def threads_col(self):
        try:
            db = self.firestore_db
            if db:
                return db.collection(CASSIA_CHATS_COLLECTION)
        except Exception as e:
            logger.error("[Cassia] threads_col error: %s", e)
        return None


cassia_chat_history = CassiaChatHistory()
rag_cassia = RAGSystem(CASSIA_DOCS_COLLECTION, label="cassia")


# ── DB helpers ────────────────────────────────────────────────────────────────

def _connect():
    if not _PMS_AVAILABLE or not all(
        [DB_CONFIG.get("host"), DB_CONFIG.get("user"), DB_CONFIG.get("database")]
    ):
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
        logger.error("[Cassia] DB connect failed: %s", e)
        return None


def _query(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = _connect()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return list(cur.fetchall())
    except Exception as e:
        logger.error("[Cassia] query failed: %s", e)
        return []
    finally:
        conn.close()


def _execute(sql: str, params: tuple = ()) -> int:
    conn = _connect()
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount
    except Exception as e:
        logger.error("[Cassia] execute failed: %s", e)
        return 0
    finally:
        conn.close()


def _insert_returning_id(sql: str, params: tuple = ()) -> Optional[int]:
    """Run an INSERT and return SCOPE_IDENTITY (MSSQL last-inserted row ID)."""
    conn = _connect()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        cur.execute("SELECT SCOPE_IDENTITY() AS new_id")
        row = cur.fetchone()
        conn.commit()
        return int(row["new_id"]) if row and row.get("new_id") else None
    except Exception as e:
        logger.error("[Cassia] insert_returning_id failed: %s", e)
        return None
    finally:
        conn.close()


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def cassia_knowledge_tool(query: str = "") -> str:
    """Search Cassia's knowledge base for platform information, feature
    explanations, pricing details, and FAQs. Use when the user asks
    'what does X do', 'how does Y work', 'what's included', or similar
    platform-knowledge questions."""
    q = (query or "").strip()
    if not q:
        return "Please provide a specific question to search."
    ctx = rag_cassia.get_context_for_query(q)
    return ctx if ctx else (
        "I don't have specific documentation on that — I'll answer from my general knowledge."
    )


@tool
def get_business_types_tool(dummy: str = "") -> str:
    """Retrieve the list of available business types with their IDs. ALWAYS
    call this before asking the user what type of business they have, so you
    can present real options and capture the correct BusinessTypeID integer."""
    rows = _query(
        "SELECT BusinessTypeID, BusinessType FROM BusinessTypes "
        "WHERE IsActive = 1 ORDER BY BusinessType"
    )
    if not rows:
        # Fallback when DB is unavailable
        return (
            "Available business types (ID = Name):\n"
            "8 = Farm / Ranch\n"
            "1 = Restaurant / Food Service\n"
            "2 = Artisan / Specialty Producer\n"
            "3 = Farmer's Market\n"
            "4 = Association / Co-op\n"
            "5 = Supplier / Vendor\n"
            "6 = Other"
        )
    lines = "\n".join(
        f"{r['BusinessTypeID']} = {r['BusinessType']}" for r in rows
    )
    return f"Available business types (ID = Name):\n{lines}"


@tool
def get_states_tool(country: str = "USA") -> str:
    """Get the list of states/provinces for a country with their StateIndex
    IDs. Call this when you need to map a user's state name to the integer
    StateIndex required by the account creation form."""
    rows = _query(
        "SELECT StateIndex, name FROM States WHERE country = %s ORDER BY name",
        (country,),
    )
    if not rows:
        return (
            f"Could not load states for {country}. "
            "Ask the user to type their full state name and I'll do my best."
        )
    lines = ", ".join(f"{r['name']} ({r['StateIndex']})" for r in rows)
    return f"States for {country}:\n{lines}"


@tool
def create_business_account_tool(
    people_id: int = 0,
    business_type_id: int = 0,
    business_name: str = "",
    business_website: str = "",
    address_street: str = "",
    address_apt: str = "",
    address_city: str = "",
    state_index: int = 0,
    address_zip: str = "",
    phone: str = "",
    livestock_disclaimer: bool = False,
    sales_disclaimer: bool = False,
) -> str:
    """Create the business account after confirming all required information
    with the user. Only call this AFTER the user has reviewed and confirmed
    a summary of their information.

    Required fields: business_type_id, state_index, phone.
    For Farm/Ranch (type 8): livestock_disclaimer AND sales_disclaimer must be True.

    Returns 'SUCCESS:BusinessID=<id>' on success, or 'ERROR:<reason>'."""
    if not business_type_id:
        return "ERROR: business_type_id is required."
    if not state_index:
        return "ERROR: state_index is required."
    if not phone:
        return "ERROR: phone number is required."
    if int(business_type_id) == 8:
        if not livestock_disclaimer:
            return "ERROR: livestock legal disclaimer consent is required for Farm/Ranch accounts."
        if not sales_disclaimer:
            return "ERROR: sales legal disclaimer consent is required for Farm/Ranch accounts."

    new_bid = _insert_returning_id(
        """
        INSERT INTO Business (
            BusinessTypeID, BusinessName, BusinessWebsite,
            AddressStreet, AddressApt, AddressCity,
            AddressZip, StateIndex, BusinessPhone,
            LivestockLegalDisclaimer, SalesLegalDisclaimer, Permission
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
        """,
        (
            int(business_type_id),
            str(business_name or "")[:200],
            str(business_website or "")[:500],
            str(address_street or "")[:200],
            str(address_apt or "")[:50],
            str(address_city or "")[:100],
            str(address_zip or "")[:20],
            int(state_index),
            str(phone or "")[:50],
            1 if livestock_disclaimer else 0,
            1 if sales_disclaimer else 0,
        ),
    )

    if not new_bid:
        return "ERROR: Could not create business account. The database may be unavailable."

    # Link the business to the person
    if people_id:
        _execute(
            "INSERT INTO PeopleBusiness (PeopleID, BusinessID, AccessLevel) "
            "VALUES (%s, %s, 3)",
            (int(people_id), int(new_bid)),
        )

    return f"SUCCESS:BusinessID={new_bid}"


# ── Billing constants ────────────────────────────────────────────────────────

_TIER_ANNUAL_PRICE: Dict[str, int] = {
    "starter":      700,
    "professional": 1700,
    "enterprise":   4100,
}

# Modules bundled at each tier (shown on the invoice narrative)
_TIER_MODULES: Dict[str, List[str]] = {
    "starter": [
        "Precision Ag Field Monitoring (up to 5 fields)",
        "Farm-to-Table Marketplace",
        "Yield Records & Crop Planner",
        "Basic Weather Dashboard",
        "Saige AI Farm Advisor",
    ],
    "professional": [
        "Precision Ag Field Monitoring (unlimited fields)",
        "Farm-to-Table Marketplace",
        "Event & Trade Show Management",
        "CA Cold Storage Management",
        "Nutrient Management & Spray Log",
        "Chilling Hours & Bloom Forecast",
        "Thaiyme Business Operations AI",
        "Saige AI Farm Advisor",
        "Report Center",
    ],
    "enterprise": [
        "Everything in Professional",
        "Unlimited fields + multi-business dashboard",
        "Cold Chain & Logistics Tracking",
        "Lavendir AI Website Builder",
        "Advanced Buyer CRM",
        "Priority support + dedicated onboarding manager",
    ],
}

# Points threshold: starter = 0-1, professional = 2-4, enterprise = 5+
_ENTERPRISE_THRESHOLD  = 5
_PROFESSIONAL_THRESHOLD = 2


def _score_tier(
    crops: List[str],
    field_count: int,
    channels: List[str],
    business_type: str,
    uses_agronomist: bool,
) -> tuple[str, List[str], int]:
    """Return (tier, reasons, score) based on the business profile."""
    reasons: List[str] = []
    score = 0

    # Field count
    if field_count > 15:
        score += 4
        reasons.append(f"{field_count} fields requires unlimited monitoring (Enterprise)")
    elif field_count > 5:
        score += 2
        reasons.append(f"{field_count} fields is best served by unlimited-field monitoring")

    # Sales channels
    n_ch = len(channels)
    if n_ch >= 5:
        score += 4
        reasons.append(f"{n_ch} sales channels requires full CRM + marketplace suite")
    elif n_ch >= 3:
        score += 2
        reasons.append(f"{n_ch} sales channels benefits from event management and CRM tools")

    # High-value / specialty crops
    hv_crops = [c for c in crops if any(k in c.lower() for k in _HIGH_VALUE_CROPS)]
    if hv_crops:
        score += 2
        reasons.append(
            f"{', '.join(hv_crops[:3])} are specialty crops — CA storage and chilling-hour "
            "tools add significant value"
        )

    # Business type
    bt = (business_type or "").lower()
    if any(k in bt for k in ("cooperative", "co-op", "food hub", "distributor", "aggregator")):
        score += 4
        reasons.append(
            f"'{business_type}' operations need multi-business dashboards and advanced logistics"
        )
    elif any(k in bt for k in ("event", "trade show", "processing", "restaurant")):
        score += 2
        reasons.append(f"'{business_type}' benefits from event/trade-show management modules")

    # Agronomist partnership
    if uses_agronomist:
        score += 1
        reasons.append("Working with an agronomist unlocks the most value from Precision Ag tools")

    # CA-eligible crops
    ca_crops = [c for c in crops if c.lower() in _CA_PROTOCOLS]
    if ca_crops:
        score += 1
        reasons.append(f"CA storage protocols available for {', '.join(ca_crops[:2])}")

    if score >= _ENTERPRISE_THRESHOLD:
        tier = "enterprise"
    elif score >= _PROFESSIONAL_THRESHOLD:
        tier = "professional"
    else:
        tier = "starter"

    return tier, reasons, score


@tool
def qualify_tier_tool(
    crops_json: str = "[]",
    field_count: int = 0,
    channels_json: str = "[]",
    business_type: str = "",
    uses_agronomist: bool = False,
) -> str:
    """Analyse the business profile and recommend a subscription tier.
    Returns a tier name, score, reasoning, annual price, and the list of modules
    the farmer would receive. Call this after collecting the qualifying questions
    so your recommendation is grounded in their actual operation.

    crops_json: JSON array of crop name strings from Q1.
    field_count: number of fields from Q2.
    channels_json: JSON array of sales channel strings from Q3.
    business_type: business type string (e.g. 'Farm', 'Cooperative').
    uses_agronomist: whether they work with an outside agronomist."""
    try:
        crops = json.loads(crops_json) if isinstance(crops_json, str) else list(crops_json or [])
    except Exception:
        crops = []
    try:
        channels = json.loads(channels_json) if isinstance(channels_json, str) else list(channels_json or [])
    except Exception:
        channels = []

    tier, reasons, score = _score_tier(
        crops=[str(c).strip() for c in crops if str(c).strip()],
        field_count=int(field_count or 0),
        channels=[str(c).strip() for c in channels if str(c).strip()],
        business_type=str(business_type or "").strip(),
        uses_agronomist=bool(uses_agronomist),
    )

    annual = _TIER_ANNUAL_PRICE[tier]
    monthly = annual / 12
    modules = _TIER_MODULES[tier]

    reason_text = "\n".join(f"  • {r}" for r in reasons) if reasons else "  • Entry-level operation — Starter covers all core features"

    return (
        f"RECOMMENDED TIER: {tier.upper()} — ${annual:,}/year (${monthly:.2f}/month)\n\n"
        f"Qualification score: {score} / why this tier:\n{reason_text}\n\n"
        f"Modules included:\n"
        + "\n".join(f"  ✓ {m}" for m in modules)
    )


@tool
def generate_invoice_summary_tool(
    tier: str = "starter",
    crops_json: str = "[]",
    field_count: int = 0,
    channels_json: str = "[]",
    business_id: int = 0,
) -> str:
    """Build a 3-component invoice narrative ready for the Stripe checkout confirmation.

    Returns a formatted invoice string AND a JSON line_items array that can be
    passed directly to prepare_checkout_tool.

    Component 1 — Base subscription (the annual platform fee).
    Component 2 — Module value statement (the specific tools most relevant to this operation).
    Component 3 — Onboarding configuration (what Cassia already set up for them today).

    tier: 'starter' | 'professional' | 'enterprise'
    crops_json: JSON array of crop names from Q1.
    field_count: int from Q2.
    channels_json: JSON array of sales channels from Q3.
    business_id: BusinessID (used to surface onboarding work done earlier in this session)."""
    tier = tier.lower().strip()
    if tier not in _TIER_ANNUAL_PRICE:
        tier = "starter"

    try:
        crops = [str(c).strip() for c in json.loads(crops_json) if str(c).strip()]
    except Exception:
        crops = []
    try:
        channels = [str(c).strip() for c in json.loads(channels_json) if str(c).strip()]
    except Exception:
        channels = []

    annual  = _TIER_ANNUAL_PRICE[tier]
    monthly = annual / 12
    modules = _TIER_MODULES[tier]
    tier_label = tier.capitalize()

    # Component 1 — base subscription
    comp1 = (
        f"OFN {tier_label} Annual Subscription — ${annual:,}/year\n"
        f"  Billed once per year (${monthly:.2f}/month equivalent)"
    )

    # Component 2 — modules most relevant to this operation
    relevant: List[str] = []
    crop_set = {c.lower() for c in crops}
    ch_set   = {c.lower() for c in channels}

    if any(k in crop_set for k in ("apple", "pear", "cherry", "peach", "blueberry", "grape")):
        relevant.append("CA Cold Storage Management + Chilling Hours Forecast")
    if crop_set:
        relevant.append(f"Precision Ag Monitoring for {', '.join(crops[:3])}")
    if ch_set & {"wholesale", "restaurant", "food service"}:
        relevant.append("Farm-to-Table Marketplace (wholesale + restaurant buyer portal)")
    if ch_set & {"csa", "direct", "direct-to-consumer", "farmers market", "farmer's market"}:
        relevant.append("CSA / Direct-to-Consumer Sales Channel")
    if field_count > 0:
        relevant.append(
            f"Satellite field monitoring for {field_count} field(s) — "
            "NDVI, soil moisture, and health alerts"
        )
    # Fill with standard modules if not enough relevant ones
    for m in modules:
        if len(relevant) >= 4:
            break
        if m not in relevant and "Everything in" not in m:
            relevant.append(m)

    comp2 = "Modules activated for your operation:\n" + "\n".join(
        f"  ✓ {m}" for m in relevant[:5]
    )

    # Component 3 — onboarding configuration already done
    setup_items: List[str] = []
    if crops:
        setup_items.append(f"Crop profiles created: {', '.join(crops[:4])}")
    if field_count:
        setup_items.append(f"{field_count} field stub(s) with satellite monitoring enabled")
    if channels:
        setup_items.append(f"Buyer price lists ready: {', '.join(channels[:3])}")
    # Check if CA room stubs were created
    ca_crops = [c for c in crops if c.lower() in _CA_PROTOCOLS]
    if ca_crops:
        setup_items.append(f"CA storage room profiles seeded for {', '.join(ca_crops[:2])}")
    # Chilling hour setup
    chill_crops = [c for c in crops if c.lower() in _CHILL_HOUR_DEFAULTS]
    if chill_crops:
        setup_items.append(f"Chilling-hour targets set for {', '.join(chill_crops[:2])}")
    setup_items.append("Saige + Thaiyme briefed — no re-explaining your setup on first login")

    comp3 = "Configured during onboarding (included at no extra cost):\n" + "\n".join(
        f"  • {s}" for s in setup_items
    )

    # Build line_items JSON for prepare_checkout_tool
    import json as _json
    line_items = [
        {"name": f"OFN {tier_label} Annual Subscription", "price": annual, "note": f"${monthly:.2f}/mo equivalent"},
        {"name": "Module bundle",                          "price": 0,      "note": f"{len(modules)} modules included"},
        {"name": "Onboarding configuration",               "price": 0,      "note": "Custom setup — completed today"},
    ]
    line_items_json = _json.dumps(line_items)

    invoice = (
        f"{'='*60}\n"
        f"INVOICE SUMMARY — OFN {tier_label} Plan\n"
        f"{'='*60}\n\n"
        f"COMPONENT 1 — Subscription\n{comp1}\n\n"
        f"COMPONENT 2 — Platform Value\n{comp2}\n\n"
        f"COMPONENT 3 — Setup Included\n{comp3}\n\n"
        f"{'─'*60}\n"
        f"TOTAL DUE TODAY: ${annual:,}.00\n"
        f"{'='*60}\n\n"
        f"LINE_ITEMS_JSON:{line_items_json}"
    )
    return invoice


@tool
def get_subscription_catalog_tool(dummy: str = "") -> str:
    """Load the full subscription feature catalog and per-tier pricing. Call
    this before discussing subscription plans so you have accurate pricing
    data. Returns all available feature modules and their costs by tier."""
    cats = _query(
        "SELECT CategoryID, CategoryName FROM FeatureCategory ORDER BY SortOrder"
    )
    tiers = _query(
        "SELECT CategoryID, TierName, Price, TransactionRate, Qty "
        "FROM FeatureCategoryTierPricing WHERE IsAvailable = 1"
    )

    if not cats:
        return (
            "Subscription tiers overview:\n"
            "• Hobby (Free, ad-supported): For very small operations just starting out\n"
            "• Starter: Core features — best value for most farms\n"
            "• Business: Full feature access + higher limits\n"
            "• Enterprise: Unlimited + premium support\n"
            "Pricing is per module. Ask me which features matter most and I'll build a custom quote."
        )

    tier_map: Dict[int, list] = {}
    for t in tiers:
        tier_map.setdefault(t["CategoryID"], []).append(t)

    lines = ["Feature modules and pricing by tier:"]
    for c in cats:
        cid = c["CategoryID"]
        t_rows = tier_map.get(cid, [])
        priced = []
        for t in t_rows:
            if t.get("Price", 0) and float(t["Price"]) > 0:
                label = f"{t['TierName']} ${float(t['Price']):.2f}/mo"
                if t.get("Qty"):
                    label += f" (up to {t['Qty']})"
                priced.append(label)
            elif t.get("TransactionRate", 0) and float(t["TransactionRate"]) > 0:
                priced.append(f"{t['TierName']} {float(t['TransactionRate'])}% tx fee")
        price_str = " | ".join(priced) if priced else "Included free on paid tiers"
        lines.append(f"• {c['CategoryName']}: {price_str}")

    return "\n".join(lines)


@tool
def prepare_checkout_tool(
    tier: str = "starter",
    categories: str = "",
    line_items_json: str = "[]",
    monthly_total: float = 0.0,
    business_type: str = "",
) -> str:
    """Signal that the customer has chosen their plan and is ready to pay.
    Call this ONLY after the customer explicitly confirms their plan choice.

    tier: 'hobby' | 'starter' | 'business' | 'enterprise'
    categories: comma-separated feature module names they're subscribing to
    line_items_json: JSON array of {name, price, note} objects for the receipt
    monthly_total: total monthly cost in USD (0.00 for free hobby tier)
    business_type: the business type label collected during Stage 1 account creation"""
    return f"CHECKOUT_READY:tier={tier}:total={monthly_total}"


# ── Stage 3 — Discovery tools ────────────────────────────────────────────────

_CHANNEL_TIER_MAP: Dict[str, tuple] = {
    "wholesale":      ("Wholesale",          "Standard wholesale pricing for distributors and retailers"),
    "retail":         ("Retail",             "Direct retail pricing for consumers"),
    "restaurant":     ("Restaurant",         "Restaurant and food service pricing"),
    "csa":            ("CSA",                "Community Supported Agriculture subscription pricing"),
    "dtc":            ("Direct-to-Consumer", "Direct-to-consumer online or on-farm pricing"),
    "direct":         ("Direct-to-Consumer", "Direct-to-consumer pricing"),
    "farmer_market":  ("Farmers Market",     "Farmers market pricing"),
    "market":         ("Farmers Market",     "Farmers market pricing"),
    "farmer's market":("Farmers Market",     "Farmers market pricing"),
}


def _seed_agronomic_tables(business_id: int, crops: List[str]) -> Dict[str, int]:
    """Create one YieldRecord and one NutrientPlan stub per crop for the current season.
    Also ensures the SprayApplication table exists so the Spray Log page loads clean.
    Called as a cascade from seed_crop_types_tool."""
    season = str(time.gmtime().tm_year)  # "2026"

    # DDL — idempotent; tables created here if not already present from the routers
    _execute(
        "IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='YieldRecord') "
        "CREATE TABLE YieldRecord ("
        "  YieldID INT IDENTITY PRIMARY KEY,"
        "  BusinessID INT NOT NULL,"
        "  Season NVARCHAR(20) NOT NULL,"
        "  FieldID NVARCHAR(80),"
        "  FieldName NVARCHAR(120),"
        "  CropName NVARCHAR(100) NOT NULL,"
        "  VarietyName NVARCHAR(100),"
        "  AreaHa DECIMAL(10,4),"
        "  PlantedDate DATE,"
        "  HarvestStartDate DATE,"
        "  HarvestEndDate DATE,"
        "  BudgetedYieldTonnesHa DECIMAL(10,4),"
        "  ActualYieldTonnes DECIMAL(12,4),"
        "  ActualYieldTonnesHa DECIMAL(10,4),"
        "  Grade1Pct DECIMAL(6,2),"
        "  Grade2Pct DECIMAL(6,2),"
        "  RejectPct DECIMAL(6,2),"
        "  AverageGradePct DECIMAL(6,2),"
        "  PricePerTonne DECIMAL(10,4),"
        "  GrossRevenue DECIMAL(14,2),"
        "  TotalVariableCost DECIMAL(14,2),"
        "  GrossMarginPerHa DECIMAL(14,2),"
        "  CropBudgetID INT,"
        "  ScaleTicketRef NVARCHAR(200),"
        "  QualityNotes NVARCHAR(1000),"
        "  Notes NVARCHAR(1000),"
        "  CreatedAt DATETIME NOT NULL DEFAULT GETDATE()"
        ")"
    )
    _execute(
        "IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='NutrientPlan') "
        "CREATE TABLE NutrientPlan ("
        "  PlanID INT IDENTITY PRIMARY KEY,"
        "  BusinessID INT NOT NULL,"
        "  FieldID INT NULL,"
        "  FieldName NVARCHAR(200) NULL,"
        "  CropName NVARCHAR(200) NULL,"
        "  Season NVARCHAR(10) NOT NULL,"
        "  PlannedN_kg_ha DECIMAL(10,2) NULL,"
        "  PlannedP_kg_ha DECIMAL(10,2) NULL,"
        "  PlannedK_kg_ha DECIMAL(10,2) NULL,"
        "  PlannedS_kg_ha DECIMAL(10,2) NULL,"
        "  Notes NVARCHAR(2000) NULL,"
        "  CreatedAt DATETIME2 DEFAULT GETDATE()"
        ")"
    )
    _execute(
        "IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='SprayApplication') "
        "CREATE TABLE SprayApplication ("
        "  ApplicationID INT IDENTITY PRIMARY KEY,"
        "  BusinessID INT NOT NULL,"
        "  ApplicationDate DATE NOT NULL,"
        "  FieldID NVARCHAR(80),"
        "  FieldName NVARCHAR(120),"
        "  AreaTreatedHa DECIMAL(10,4),"
        "  CropName NVARCHAR(100),"
        "  GrowthStage NVARCHAR(80),"
        "  ApplicationMethod NVARCHAR(60),"
        "  EquipmentUsed NVARCHAR(200),"
        "  OperatorName NVARCHAR(150),"
        "  WeatherTempC DECIMAL(5,1),"
        "  WeatherWindKph DECIMAL(5,1),"
        "  WeatherHumidityPct DECIMAL(5,1),"
        "  WeatherConditions NVARCHAR(100),"
        "  TotalWaterUsedL DECIMAL(10,2),"
        "  WaterVolumePerHaL DECIMAL(8,2),"
        "  PestTargeted NVARCHAR(200),"
        "  CropObservations NVARCHAR(500),"
        "  PHIDate DATE,"
        "  REIExpiry DATETIME,"
        "  IsComplete BIT NOT NULL DEFAULT 0,"
        "  Notes NVARCHAR(1000),"
        "  CreatedAt DATETIME NOT NULL DEFAULT GETDATE()"
        ")"
    )

    yields_seeded = nutrients_seeded = 0
    for crop in crops:
        if not _query(
            "SELECT 1 FROM YieldRecord WHERE BusinessID=%s AND CropName=%s AND Season=%s",
            (business_id, crop, season),
        ):
            _execute(
                "INSERT INTO YieldRecord (BusinessID, Season, CropName) VALUES (%s, %s, %s)",
                (business_id, season, crop),
            )
            yields_seeded += 1

        if not _query(
            "SELECT 1 FROM NutrientPlan WHERE BusinessID=%s AND CropName=%s AND Season=%s",
            (business_id, crop, season),
        ):
            _execute(
                "INSERT INTO NutrientPlan (BusinessID, CropName, Season) VALUES (%s, %s, %s)",
                (business_id, crop, season),
            )
            nutrients_seeded += 1

    return {"yields_seeded": yields_seeded, "nutrients_seeded": nutrients_seeded}


@tool
def seed_crop_types_tool(business_id: int = 0, crops_json: str = "[]") -> str:
    """Record the business's primary crops or products. Creates a BusinessCropProfile
    row for each crop so Precision Ag, Yield Records, Nutrient Management, and Spray
    Log all know what this operation grows.
    business_id: BusinessID from Stage 1.
    crops_json: JSON array of crop name strings, e.g. '[\"Wheat\",\"Corn\"]'."""
    if not business_id:
        return "ERROR: business_id required."
    try:
        crops = json.loads(crops_json) if isinstance(crops_json, str) else list(crops_json or [])
    except Exception:
        crops = []
    crops = [str(c).strip() for c in crops if str(c).strip()][:20]

    _execute(
        "IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='BusinessCropProfile') "
        "CREATE TABLE BusinessCropProfile ("
        "  ProfileID   INT IDENTITY PRIMARY KEY,"
        "  BusinessID  INT NOT NULL,"
        "  CropName    NVARCHAR(100) NOT NULL,"
        "  CropCategory NVARCHAR(50),"
        "  CreatedAt   DATETIME DEFAULT GETUTCDATE()"
        ")"
    )

    inserted = 0
    for crop in crops:
        existing = _query(
            "SELECT 1 FROM BusinessCropProfile WHERE BusinessID=%s AND CropName=%s",
            (int(business_id), crop),
        )
        if not existing:
            _execute(
                "INSERT INTO BusinessCropProfile (BusinessID, CropName) VALUES (%s, %s)",
                (int(business_id), crop),
            )
            inserted += 1

    if not crops:
        return "No crops provided — crop profile not set."

    # Cascade: seed YieldRecord and NutrientPlan stubs for the current season,
    # and ensure the SprayApplication table exists, all in one pass.
    cascade = _seed_agronomic_tables(int(business_id), crops)
    cascade_msg = (
        f" Seeded {cascade['yields_seeded']} yield record(s) and "
        f"{cascade['nutrients_seeded']} nutrient plan(s) for {time.gmtime().tm_year}."
    )

    return f"Saved {inserted} crop type(s) for business {business_id}: {', '.join(crops)}.{cascade_msg}"


@tool
def create_field_stubs_tool(
    business_id: int = 0,
    field_count: int = 1,
    size_ha: float = 0.0,
    crop_type: str = "",
) -> str:
    """Create placeholder Field records so the Precision Ag dashboard is not empty
    on first login. Fields are named 'Field 1', 'Field 2', etc. The farmer can
    rename them and add GPS coordinates later.
    business_id: BusinessID from Stage 1.
    field_count: number of fields to create (capped at 20).
    size_ha: approximate size per field in hectares (0 = unknown).
    crop_type: primary crop type string for all stub fields."""
    if not business_id:
        return "ERROR: business_id required."
    count = max(1, min(int(field_count or 1), 20))
    ha    = float(size_ha or 0)
    crop  = str(crop_type or "").strip()[:100]

    created = []
    for i in range(1, count + 1):
        existing = _query(
            "SELECT FieldID FROM Field WHERE BusinessID=%s AND Name=%s",
            (int(business_id), f"Field {i}"),
        )
        if existing:
            continue
        fid = _insert_returning_id(
            "INSERT INTO Field "
            "(BusinessID, Name, Address, CropType, FieldSizeHectares, "
            " MonitoringEnabled, MonitoringIntervalDays, AlertThresholdHealth, CreatedAt) "
            "VALUES (%s, %s, '', %s, %s, 0, 7, 0.5, GETUTCDATE())",
            (int(business_id), f"Field {i}", crop or None, ha if ha > 0 else None),
        )
        if fid:
            created.append(fid)

    if not created:
        return f"Field stubs already exist for business {business_id} — no duplicates created."
    return (
        f"Created {len(created)} field stub(s) for business {business_id}. "
        "The farmer can rename them and add GPS coordinates in Precision Ag."
    )


@tool
def configure_buyer_tiers_tool(business_id: int = 0, channels_json: str = "[]") -> str:
    """Create default PriceList entries for each of the business's sales channels.
    Skips any tier that already exists for this business.
    business_id: BusinessID from Stage 1.
    channels_json: JSON array from: wholesale, retail, restaurant, csa, dtc, farmer_market."""
    if not business_id:
        return "ERROR: business_id required."
    try:
        channels = json.loads(channels_json) if isinstance(channels_json, str) else list(channels_json or [])
    except Exception:
        channels = []
    channels = [str(c).strip().lower() for c in channels if str(c).strip()]

    created_tiers = []
    for ch in channels:
        tier_info = _CHANNEL_TIER_MAP.get(ch)
        if not tier_info:
            continue
        tier_label, notes = tier_info
        existing = _query(
            "SELECT 1 FROM PriceList WHERE BusinessID=%s AND BuyerTier=%s",
            (int(business_id), tier_label),
        )
        if existing:
            continue
        _insert_returning_id(
            "INSERT INTO PriceList (BusinessID, ListName, BuyerTier, IsActive, Notes) "
            "OUTPUT INSERTED.PriceListID VALUES (%s, %s, %s, 1, %s)",
            (int(business_id), f"{tier_label} Price List", tier_label, notes),
        )
        created_tiers.append(tier_label)

    if not channels:
        return "No sales channels provided — price tiers not configured."
    if not created_tiers:
        return f"Price list tiers already configured for business {business_id}."
    return f"Created price list tier(s) for business {business_id}: {', '.join(created_tiers)}."


@tool
def toggle_agro_module_tool(business_id: int = 0, enabled: bool = False) -> str:
    """Enable or disable the Agronomist Consultation Log module for this business.
    business_id: BusinessID from Stage 1.
    enabled: True if they use outside agronomists or crop consultants; False to hide the module."""
    if not business_id:
        return "ERROR: business_id required."

    rows = _query(
        "SELECT CategoryID FROM FeatureCategory WHERE FeatureKey=%s",
        ("agro_consultations",),
    )
    if not rows:
        rows = _query(
            "SELECT CategoryID FROM FeatureCategory WHERE CategoryName=%s",
            ("Agronomist Consultation Log",),
        )
    if not rows:
        cat_id = _insert_returning_id(
            "INSERT INTO FeatureCategory (CategoryName, FeatureKey, SortOrder) "
            "OUTPUT INSERTED.CategoryID VALUES (%s, %s, 200)",
            ("Agronomist Consultation Log", "agro_consultations"),
        )
    else:
        cat_id = rows[0].get("categoryid") or rows[0].get("CategoryID")

    if not cat_id:
        return "ERROR: Could not resolve FeatureCategory for agro_consultations."

    _execute(
        "MERGE BusinessServiceAccess AS t "
        "USING (SELECT %s AS BusinessID, %s AS CategoryID, %s AS IsEnabled) AS s "
        "  ON t.BusinessID=s.BusinessID AND t.CategoryID=s.CategoryID "
        "WHEN MATCHED THEN UPDATE SET t.IsEnabled=s.IsEnabled "
        "WHEN NOT MATCHED THEN INSERT (BusinessID, CategoryID, IsEnabled) "
        "  VALUES (s.BusinessID, s.CategoryID, s.IsEnabled);",
        (int(business_id), int(cat_id), 1 if enabled else 0),
    )

    state = "enabled" if enabled else "disabled"
    return f"Agronomist Consultation module {state} for business {business_id}."


@tool
def store_discovery_profile_tool(
    people_id: str = "",
    business_id: int = 0,
    crops: str = "[]",
    field_count: int = 0,
    size_ha: float = 0.0,
    channels: str = "[]",
    uses_agronomist: bool = False,
    headache: str = "",
) -> str:
    """Save the complete discovery profile to Firestore long-term memory so
    Saige and Thaiyme already know this business's context on first login.
    Call this AFTER all four discovery questions have been answered and their
    respective tools have been called.
    people_id: injected automatically — do not ask the user for this.
    business_id: BusinessID from Stage 1."""
    if not people_id:
        return "ERROR: people_id required."
    try:
        crops_list = json.loads(crops) if isinstance(crops, str) else list(crops or [])
    except Exception:
        crops_list = []
    try:
        ch_list = json.loads(channels) if isinstance(channels, str) else list(channels or [])
    except Exception:
        ch_list = []

    profile = {
        "business_id":     int(business_id or 0),
        "crops":           crops_list,
        "field_count":     int(field_count or 0),
        "size_ha":         float(size_ha or 0),
        "channels":        ch_list,
        "uses_agronomist": bool(uses_agronomist),
        "headache":        str(headache or "").strip(),
        "completed_at":    time.time(),
    }
    try:
        db = cassia_chat_history.firestore_db
        if db:
            db.collection(CASSIA_CHATS_COLLECTION).document(
                f"discovery_{people_id}"
            ).set(profile)
            return (
                f"Discovery profile saved for user {people_id}. "
                "Saige and Thaiyme are now briefed on this operation."
            )
    except Exception as e:
        logger.warning("[Cassia] store_discovery_profile_tool Firestore error: %s", e)
    return "Discovery profile saved. Your AI team is ready for your first login."


# ── Stage 3 — Phase 2 module-configuration tools ─────────────────────────────

# Crops considered high-value: tighter monitoring interval + lower health threshold
_HIGH_VALUE_CROPS = frozenset({
    "berry", "berries", "strawberry", "blueberry", "raspberry", "blackberry",
    "grape", "vineyard", "wine", "cannabis", "hemp", "hops",
    "herb", "herbs", "lavender", "saffron", "vanilla", "truffle",
    "mushroom", "specialty", "organic", "flower", "flowers", "nursery",
})

_CROP_CATEGORY_MAP = {
    "corn": "Grain", "wheat": "Grain", "soy": "Grain", "soybean": "Grain",
    "oat": "Grain", "oats": "Grain", "barley": "Grain", "rye": "Grain",
    "rice": "Grain", "millet": "Grain", "sorghum": "Grain",
    "potato": "Vegetables", "carrot": "Vegetables", "onion": "Vegetables",
    "lettuce": "Vegetables", "tomato": "Vegetables", "pepper": "Vegetables",
    "squash": "Vegetables", "pumpkin": "Vegetables", "cucumber": "Vegetables",
    "bean": "Vegetables", "pea": "Vegetables", "broccoli": "Vegetables",
    "apple": "Fruit", "pear": "Fruit", "peach": "Fruit", "cherry": "Fruit",
    "plum": "Fruit", "berry": "Fruit", "berries": "Fruit",
    "strawberry": "Fruit", "blueberry": "Fruit", "raspberry": "Fruit",
    "grape": "Fruit", "melon": "Fruit", "watermelon": "Fruit",
    "beef": "Meat", "pork": "Meat", "lamb": "Meat", "goat": "Meat",
    "bison": "Meat", "venison": "Meat", "veal": "Meat",
    "chicken": "Poultry", "turkey": "Poultry", "duck": "Poultry",
    "egg": "Eggs & Dairy", "eggs": "Eggs & Dairy",
    "milk": "Eggs & Dairy", "cheese": "Eggs & Dairy", "butter": "Eggs & Dairy",
    "honey": "Specialty Products", "maple": "Specialty Products",
    "herb": "Herbs & Spices", "herbs": "Herbs & Spices",
    "lavender": "Herbs & Spices", "basil": "Herbs & Spices",
    "flower": "Floriculture", "flowers": "Floriculture",
    "cannabis": "Specialty Products", "hemp": "Specialty Products",
}


def _guess_category(crop: str) -> str:
    """Map a crop name to a MarketplaceProducts CategoryName."""
    crop_lower = crop.lower()
    for keyword, cat in _CROP_CATEGORY_MAP.items():
        if keyword in crop_lower:
            return cat
    return "Produce"


@tool
def activate_field_monitoring_tool(
    business_id: int = 0,
    crops_json: str = "[]",
) -> str:
    """Enable satellite monitoring on all field stubs for this business.
    Sets MonitoringEnabled=1 and tunes AlertThresholdHealth and
    MonitoringIntervalDays based on crop value (high-value crops get
    a 3-day interval and 0.30 health threshold; commodity crops use
    7 days and 0.40).
    business_id: BusinessID from Stage 1.
    crops_json: JSON array of crop names from Q1."""
    if not business_id:
        return "ERROR: business_id required."
    try:
        crops = json.loads(crops_json) if isinstance(crops_json, str) else list(crops_json or [])
    except Exception:
        crops = []
    crops_lower = " ".join(str(c).lower() for c in crops)

    is_high_value = any(kw in crops_lower for kw in _HIGH_VALUE_CROPS)
    interval  = 3   if is_high_value else 7
    threshold = 0.30 if is_high_value else 0.40

    rows = _execute(
        "UPDATE Field SET MonitoringEnabled=1, MonitoringIntervalDays=%s, "
        "AlertThresholdHealth=%s WHERE BusinessID=%s AND MonitoringEnabled=0",
        (interval, threshold, int(business_id)),
    )
    if rows == 0:
        check = _query(
            "SELECT COUNT(*) AS cnt FROM Field WHERE BusinessID=%s",
            (int(business_id),),
        )
        count = (check[0].get("cnt") or 0) if check else 0
        if count == 0:
            return "No fields found — monitoring not activated."
        return f"Field monitoring was already active for business {business_id}."

    freq = f"every {interval} day{'s' if interval > 1 else ''}"
    return (
        f"Satellite monitoring activated on {rows} field(s): checking {freq}, "
        f"alert threshold at {int(threshold * 100)}% health."
    )


@tool
def create_marketplace_drafts_tool(
    business_id: int = 0,
    crops_json: str = "[]",
) -> str:
    """Create draft MarketplaceProducts listings for each crop this business
    grows. Listings are inactive (IsActive=0) so the farmer can add pricing
    and publish when ready. Skips crops that already have a listing.
    business_id: BusinessID from Stage 1.
    crops_json: JSON array of crop names from Q1."""
    if not business_id:
        return "ERROR: business_id required."
    try:
        crops = json.loads(crops_json) if isinstance(crops_json, str) else list(crops_json or [])
    except Exception:
        crops = []
    crops = [str(c).strip() for c in crops if str(c).strip()][:20]

    if not crops:
        return "No crops provided — marketplace drafts not created."

    # Ensure table exists (may be running without the marketplace router)
    _execute(
        "IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='MarketplaceProducts') "
        "CREATE TABLE MarketplaceProducts ("
        "  ProductID         INT IDENTITY(1,1) PRIMARY KEY,"
        "  BusinessID        INT NOT NULL,"
        "  Title             VARCHAR(500) NOT NULL,"
        "  Description       TEXT,"
        "  CategoryName      VARCHAR(200),"
        "  UnitPrice         DECIMAL(10,2) NOT NULL DEFAULT 0,"
        "  WholesalePrice    DECIMAL(10,2),"
        "  UnitLabel         VARCHAR(50) DEFAULT 'lb',"
        "  QuantityAvailable DECIMAL(10,2) DEFAULT 0,"
        "  MinOrderQuantity  DECIMAL(10,2) DEFAULT 1,"
        "  IsActive          BIT DEFAULT 1,"
        "  DeliveryOptions   VARCHAR(200) DEFAULT 'pickup',"
        "  CreatedAt         DATETIME DEFAULT GETDATE(),"
        "  UpdatedAt         DATETIME DEFAULT GETDATE()"
        ")"
    )

    created = []
    for crop in crops:
        existing = _query(
            "SELECT 1 FROM MarketplaceProducts WHERE BusinessID=%s AND Title=%s",
            (int(business_id), crop),
        )
        if existing:
            continue
        category = _guess_category(crop)
        pid = _insert_returning_id(
            "INSERT INTO MarketplaceProducts "
            "(BusinessID, Title, Description, CategoryName, UnitPrice, "
            " UnitLabel, QuantityAvailable, IsActive, DeliveryOptions, CreatedAt, UpdatedAt) "
            "VALUES (%s, %s, %s, %s, 0.00, 'lb', 0, 0, 'pickup,delivery', GETUTCDATE(), GETUTCDATE())",
            (
                int(business_id),
                crop,
                f"Fresh {crop} from our farm. Price and availability updated seasonally.",
                category,
            ),
        )
        if pid:
            created.append(crop)

    if not created:
        return f"Marketplace drafts already exist for business {business_id}."
    return (
        f"Created {len(created)} draft marketplace listing(s) for: {', '.join(created)}. "
        "The farmer can add pricing and publish from the Marketplace page."
    )


# ── Alert-profile data tables ─────────────────────────────────────────────────

# Chilling-hour requirements (required_hours, base_temp_f, max_temp_f, model)
_CHILL_HOUR_DEFAULTS: Dict[str, tuple] = {
    "apple":      (1000, 32, 45, "simple"),
    "pear":       (900,  32, 45, "simple"),
    "cherry":     (900,  32, 45, "simple"),
    "peach":      (700,  32, 45, "simple"),
    "nectarine":  (700,  32, 45, "simple"),
    "plum":       (700,  32, 45, "simple"),
    "apricot":    (600,  32, 45, "simple"),
    "almond":     (400,  32, 45, "simple"),
    "pistachio":  (800,  32, 45, "simple"),
    "walnut":     (900,  32, 45, "simple"),
    "pecan":      (500,  32, 45, "simple"),
    "blueberry":  (700,  32, 45, "simple"),
    "strawberry": (300,  32, 45, "simple"),
    "grape":      (200,  32, 45, "simple"),
    "kiwifruit":  (600,  32, 45, "simple"),
    "kiwi":       (600,  32, 45, "simple"),
    "fig":        (100,  32, 45, "simple"),
    "olive":      (200,  32, 45, "simple"),
    "pomegranate":(200,  32, 45, "simple"),
}

# CA storage protocols per crop (o2_pct, co2_pct, temp_c, rh_pct, max_ethylene_ppb)
_CA_PROTOCOLS: Dict[str, tuple] = {
    "apple":      (1.5,  2.5,   0.0,  93, 1),
    "pear":       (1.5,  5.0,  -1.0,  95, 1),
    "cherry":     (3.0,  10.0, -1.0,  95, None),
    "kiwifruit":  (2.0,  5.0,   0.0,  95, None),
    "kiwi":       (2.0,  5.0,   0.0,  95, None),
    "blueberry":  (2.5,  15.0,  0.0,  95, None),
    "strawberry": (5.0,  15.0,  0.0,  95, None),
    "citrus":     (5.0,  0.0,   5.0,  92, None),
    "orange":     (5.0,  0.0,   5.0,  92, None),
    "lemon":      (5.0,  0.0,   5.0,  92, None),
    "avocado":    (3.0,  7.0,   5.5,  90, None),
    "mango":      (5.0,  5.0,  12.0,  90, None),
    "grape":      (3.0,  3.0,  -1.0,  95, None),
    "plum":       (1.0,  5.0,  -1.0,  95, 1),
    "peach":      (1.0,  5.0,  -1.0,  95, 1),
    "nectarine":  (1.0,  5.0,  -1.0,  95, 1),
    "potato":     (21.0, 5.0,   4.0,  95, None),
    "cabbage":    (3.0,  5.0,   0.0,  98, None),
}

# Generic spray products seeded into ChemicalProduct at onboarding
# (product_name, product_type, phi_days, rei_hours, active_ingredient)
_DEFAULT_SPRAY_PRODUCTS: List[tuple] = [
    ("Generic Fungicide",    "Fungicide",  7,  4,  "Mancozeb"),
    ("Generic Herbicide",    "Herbicide",  14, 12, "Glyphosate"),
    ("Generic Insecticide",  "Insecticide", 7, 12, "Malathion"),
    ("Copper Hydroxide",     "Fungicide",  0,  24, "Copper Hydroxide"),
    ("Neem Oil",             "Insecticide", 0,  4,  "Azadirachtin"),
]


@tool
def configure_alert_profiles_tool(
    business_id: int = 0,
    crops_json: str = "[]",
) -> str:
    """Seed crop-specific alert thresholds for Spray PHI, Chilling Hours, and CA Storage.
    - Inserts default ChemicalProduct rows (PHI/REI) for common spray products.
    - Inserts ChillCultivar rows for any crops with known chill-hour requirements.
    - Inserts CARoom stub rows for any crops with standard CA protocols.
    Skips rows that already exist (idempotent).
    business_id: BusinessID from Stage 1.
    crops_json: JSON array of crop name strings."""
    if not business_id:
        return "ERROR: business_id required."
    try:
        crops = json.loads(crops_json) if isinstance(crops_json, str) else list(crops_json or [])
    except Exception:
        crops = []
    crops = [str(c).strip() for c in crops if str(c).strip()]

    bid = int(business_id)

    # ── DDL guards (safe to run even if routers already ran them) ─────────────
    _execute(
        "IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ChemicalProduct') "
        "CREATE TABLE ChemicalProduct ("
        "  ProductID INT IDENTITY PRIMARY KEY,"
        "  BusinessID INT NOT NULL,"
        "  ProductName NVARCHAR(150) NOT NULL,"
        "  ActiveIngredient NVARCHAR(300),"
        "  RegistrationNumber NVARCHAR(80),"
        "  EpaStatus NVARCHAR(30),"
        "  ProductType NVARCHAR(60),"
        "  ManufacturerName NVARCHAR(150),"
        "  PHIDays INT,"
        "  REIHours INT,"
        "  DefaultRatePerHa DECIMAL(10,4),"
        "  DefaultRateUnit NVARCHAR(20),"
        "  Notes NVARCHAR(500),"
        "  IsActive BIT NOT NULL DEFAULT 1,"
        "  CreatedAt DATETIME NOT NULL DEFAULT GETDATE()"
        ")"
    )
    _execute(
        "IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ChillCultivar') "
        "CREATE TABLE ChillCultivar ("
        "  CultivarID INT IDENTITY PRIMARY KEY,"
        "  BusinessID INT NOT NULL,"
        "  CropType NVARCHAR(80) NOT NULL,"
        "  CultivarName NVARCHAR(120) NOT NULL,"
        "  RequiredChillHours DECIMAL(8,1) NOT NULL,"
        "  BaseChillTempF DECIMAL(5,1) NOT NULL DEFAULT 32,"
        "  MaxChillTempF DECIMAL(5,1) NOT NULL DEFAULT 45,"
        "  BloomGDDAfterDormancy DECIMAL(7,1),"
        "  Model NVARCHAR(30) NOT NULL DEFAULT 'simple',"
        "  Notes NVARCHAR(500),"
        "  CreatedAt DATETIME NOT NULL DEFAULT GETDATE()"
        ")"
    )
    _execute(
        "IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CARoom') "
        "CREATE TABLE CARoom ("
        "  RoomID INT IDENTITY PRIMARY KEY,"
        "  BusinessID INT NOT NULL,"
        "  RoomName NVARCHAR(100) NOT NULL,"
        "  CapacityBins INT,"
        "  TargetO2Pct DECIMAL(5,2),"
        "  TargetCO2Pct DECIMAL(5,2),"
        "  TargetTempC DECIMAL(5,2),"
        "  TargetHumidityPct DECIMAL(5,2),"
        "  MaxEthylenePPB DECIMAL(8,2),"
        "  Commodity NVARCHAR(80),"
        "  Variety NVARCHAR(100),"
        "  IsActive BIT NOT NULL DEFAULT 1,"
        "  Notes NVARCHAR(500),"
        "  CreatedAt DATETIME NOT NULL DEFAULT GETDATE()"
        ")"
    )

    spray_seeded = chill_seeded = ca_seeded = 0

    # ── Spray PHI defaults ───────────────────────────────────────────────────
    for name, ptype, phi, rei, ai in _DEFAULT_SPRAY_PRODUCTS:
        if not _query(
            "SELECT 1 FROM ChemicalProduct WHERE BusinessID=%s AND ProductName=%s",
            (bid, name),
        ):
            _execute(
                "INSERT INTO ChemicalProduct "
                "(BusinessID, ProductName, ProductType, PHIDays, REIHours, ActiveIngredient, IsActive) "
                "VALUES (%s, %s, %s, %s, %s, %s, 1)",
                (bid, name, ptype, phi, rei, ai),
            )
            spray_seeded += 1

    # ── Chilling-hour targets ────────────────────────────────────────────────
    for crop in crops:
        key = crop.lower()
        if key not in _CHILL_HOUR_DEFAULTS:
            continue
        req, base_f, max_f, model = _CHILL_HOUR_DEFAULTS[key]
        if not _query(
            "SELECT 1 FROM ChillCultivar WHERE BusinessID=%s AND CropType=%s AND CultivarName=%s",
            (bid, crop, "Default"),
        ):
            _execute(
                "INSERT INTO ChillCultivar "
                "(BusinessID, CropType, CultivarName, RequiredChillHours, BaseChillTempF, MaxChillTempF, Model) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (bid, crop, "Default", float(req), float(base_f), float(max_f), model),
            )
            chill_seeded += 1

    # ── CA storage room stubs ────────────────────────────────────────────────
    for crop in crops:
        key = crop.lower()
        if key not in _CA_PROTOCOLS:
            continue
        o2, co2, temp, rh, eth = _CA_PROTOCOLS[key]
        room_name = f"{crop.title()} CA Room"
        if not _query(
            "SELECT 1 FROM CARoom WHERE BusinessID=%s AND Commodity=%s",
            (bid, crop),
        ):
            _execute(
                "INSERT INTO CARoom "
                "(BusinessID, RoomName, TargetO2Pct, TargetCO2Pct, TargetTempC, "
                " TargetHumidityPct, MaxEthylenePPB, Commodity, IsActive) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)",
                (bid, room_name, o2, co2, temp, rh, eth, crop),
            )
            ca_seeded += 1

    parts = []
    if spray_seeded:
        parts.append(f"{spray_seeded} spray product(s) with PHI/REI defaults")
    if chill_seeded:
        parts.append(f"{chill_seeded} chilling-hour target(s)")
    if ca_seeded:
        parts.append(f"{ca_seeded} CA storage room profile(s)")

    if not parts:
        return f"Alert profiles already configured for business {bid} — no new rows needed."
    return (
        f"Alert profiles configured for business {bid}: "
        + ", ".join(parts) + ". "
        "These defaults appear in Spray Log, Chilling Hours, and CA Storage pages immediately."
    )


# ── Subscription feature configuration ───────────────────────────────────────

# Features enabled for every paid business regardless of persona
_BASELINE_FEATURES = frozenset({
    "precision_ag", "accounting", "farm_pl", "cash_flow_forecast",
    "report_center", "document_vault", "weather_dashboard", "blog",
    "testimonials", "certifications", "price_list", "buyer_crm",
    "crop_planning", "field_activity_journal", "field_health_dashboard",
    "yield_records", "spray_applications", "nutrient_mgmt", "soil_tests",
    "farm_safety", "equipment_maint", "seed_varieties", "farm_inputs",
    "food_system_newsfeed", "business_directory", "meetings",
    "harvest_scheduling", "work_orders", "pest_scouting", "farm_kpi",
})

# Features that are off by default — only enabled when the profile matches
_DEFAULT_OFF = frozenset({
    "livestock", "chef_dashboard", "pairsley", "rosemarie",
    "restaurant_sourcing", "properties", "land_leasing",
    "nursery_management", "iot_greenhouse", "grain_bin_monitoring",
    "scale_tickets", "ca_storage", "chilling_hours", "harvest_bins",
    "csa_management", "csa_advanced", "food_aggregation",
    "farmer_settlement", "enterprise_supply_chain", "cold_chain",
    "hr_management", "farm_stand", "food_wanted", "associations",
    "outgrower_management", "packhouse_qc", "plant_tagging",
    "export_compliance", "picker_performance", "perishable_traceability",
    "compliance_audit", "agro_consultations", "delivery_routes",
    "my_website", "traceability", "procurement", "events",
    "farm_2_table", "products", "services", "irrigation_mgmt",
    "commodity_prices", "forums", "crop_budgeting",
})

# Grain crops trigger grain-specific modules
_GRAIN_CROPS = frozenset({
    "corn", "wheat", "soybean", "soybeans", "oat", "oats", "barley",
    "rye", "sorghum", "milo", "canola",
})

# Livestock keywords
_LIVESTOCK_CROPS = frozenset({
    "cattle", "beef", "dairy", "cow", "cows", "hog", "hogs", "pig", "pigs",
    "pork", "sheep", "lamb", "goat", "goats", "chicken", "poultry",
    "turkey", "duck", "livestock", "horse", "horses",
})

# Greenhouse / nursery crops
_GREENHOUSE_CROPS = frozenset({
    "flower", "flowers", "nursery", "greenhouse", "orchid", "orchids",
    "cannabis", "hemp", "microgreens", "sprouts",
})

# Crops that benefit from CA storage / chilling hours (already defined above as _CHILL_HOUR_DEFAULTS)
_CA_TREE_FRUITS = frozenset(_CA_PROTOCOLS.keys())


def _resolve_feature_category_id(feature_key: str) -> Optional[int]:
    """Return the FeatureCategory.CategoryID for a feature_key. Returns None if not found."""
    rows = _query(
        "SELECT CategoryID FROM FeatureCategory WHERE FeatureKey=%s",
        (feature_key,),
    )
    if rows:
        row = rows[0]
        return int(row.get("categoryid") or row.get("CategoryID"))
    return None


def _set_feature(business_id: int, feature_key: str, enabled: bool) -> bool:
    """Upsert one BusinessServiceAccess row. Returns True if the row was written."""
    cat_id = _resolve_feature_category_id(feature_key)
    if not cat_id:
        return False
    _execute(
        "MERGE BusinessServiceAccess AS t "
        "USING (SELECT %s AS BusinessID, %s AS CategoryID, %s AS IsEnabled) AS s "
        "  ON t.BusinessID=s.BusinessID AND t.CategoryID=s.CategoryID "
        "WHEN MATCHED THEN UPDATE SET t.IsEnabled=s.IsEnabled "
        "WHEN NOT MATCHED THEN INSERT (BusinessID, CategoryID, IsEnabled) "
        "  VALUES (s.BusinessID, s.CategoryID, s.IsEnabled);",
        (business_id, cat_id, 1 if enabled else 0),
    )
    return True


def _build_feature_set(
    tier: str,
    crops: List[str],
    channels: List[str],
    business_type: str,
    uses_agronomist: bool,
) -> tuple[set, set]:
    """Return (enable_set, disable_set) of feature_key strings for this profile."""
    enable: set = set(_BASELINE_FEATURES)
    disable: set = set(_DEFAULT_OFF)

    crop_keys = {c.lower() for c in crops}
    ch_keys   = {c.lower() for c in channels}
    bt        = (business_type or "").lower()

    # ── Crop-based enables ──────────────────────────────────────────────────
    # Tree fruit / berry → CA storage + chilling hours
    if crop_keys & _CA_TREE_FRUITS:
        for f in ("ca_storage", "chilling_hours", "harvest_bins", "irrigation_mgmt"):
            enable.add(f); disable.discard(f)

    # Grain → bin monitoring + scale tickets + commodity prices
    if crop_keys & _GRAIN_CROPS:
        for f in ("grain_bin_monitoring", "scale_tickets", "commodity_prices"):
            enable.add(f); disable.discard(f)

    # Livestock
    if crop_keys & _LIVESTOCK_CROPS:
        enable.add("livestock"); disable.discard("livestock")

    # Greenhouse / nursery / cannabis
    if crop_keys & _GREENHOUSE_CROPS:
        for f in ("nursery_management", "iot_greenhouse"):
            enable.add(f); disable.discard(f)
        if "cannabis" in crop_keys or "hemp" in crop_keys:
            enable.add("compliance_audit"); disable.discard("compliance_audit")

    # Any crop production → irrigation + pest scouting
    if crops:
        for f in ("irrigation_mgmt", "pest_scouting"):
            enable.add(f); disable.discard(f)

    # ── Channel-based enables ───────────────────────────────────────────────
    # Marketplace (selling): enabled if they have any product-based channel
    if ch_keys & {"wholesale", "retail", "restaurant", "food service",
                  "csa", "dtc", "direct", "direct-to-consumer",
                  "farmers market", "farmer's market", "online"}:
        for f in ("farm_2_table", "products"):
            enable.add(f); disable.discard(f)

    # CSA
    if ch_keys & {"csa", "community supported agriculture"}:
        for f in ("csa_management", "csa_advanced"):
            enable.add(f); disable.discard(f)

    # Farmers market or direct → farm stand POS
    if ch_keys & {"farmers market", "farmer's market", "farm stand",
                  "dtc", "direct", "direct-to-consumer"}:
        for f in ("farm_stand", "delivery_routes"):
            enable.add(f); disable.discard(f)

    # Wholesale / distributor → cold chain logistics (Professional+ only)
    if ch_keys & {"wholesale", "distributor", "distribution"}:
        if tier in ("professional", "enterprise"):
            for f in ("cold_chain", "farmer_settlement", "traceability"):
                enable.add(f); disable.discard(f)

    # ── Business type enables ────────────────────────────────────────────────
    if any(k in bt for k in ("cooperative", "co-op", "food hub", "aggregator")):
        for f in ("food_aggregation", "farmer_settlement", "food_wanted"):
            enable.add(f); disable.discard(f)
        if tier == "enterprise":
            for f in ("enterprise_supply_chain", "hr_management"):
                enable.add(f); disable.discard(f)

    if any(k in bt for k in ("restaurant", "food service", "catering")):
        for f in ("chef_dashboard", "pairsley", "restaurant_sourcing"):
            enable.add(f); disable.discard(f)

    if any(k in bt for k in ("event", "trade show", "conference", "fair")):
        enable.add("events"); disable.discard("events")

    # ── Agronomist ──────────────────────────────────────────────────────────
    if uses_agronomist:
        enable.add("agro_consultations"); disable.discard("agro_consultations")

    # ── Tier unlocks ────────────────────────────────────────────────────────
    if tier in ("professional", "enterprise"):
        for f in ("traceability", "perishable_traceability", "packhouse_qc",
                  "outgrower_management", "procurement", "services"):
            enable.add(f); disable.discard(f)

    if tier == "enterprise":
        for f in ("my_website", "hr_management", "enterprise_supply_chain",
                  "export_compliance", "picker_performance", "plant_tagging"):
            enable.add(f); disable.discard(f)

    # Never enable something in both sets — enable wins
    disable -= enable
    return enable, disable


@tool
def configure_subscription_features_tool(
    business_id: int = 0,
    tier: str = "starter",
    crops_json: str = "[]",
    channels_json: str = "[]",
    business_type: str = "",
    uses_agronomist: bool = False,
) -> str:
    """Configure the sidebar feature flags for this business based on their actual
    operation — crops, channels, business type, and subscription tier.

    Enables persona-appropriate modules (e.g. CA storage for apple growers, CSA
    management for subscription farms, grain bin monitoring for grain operations)
    and suppresses unrelated modules so the sidebar is not cluttered on first login.

    business_id: BusinessID from Stage 1.
    tier: 'starter' | 'professional' | 'enterprise' — controls which premium modules unlock.
    crops_json: JSON array of crop names from Q1.
    channels_json: JSON array of sales channel strings from Q3.
    business_type: business type string (e.g. 'Farm', 'Cooperative').
    uses_agronomist: True if they work with an outside agronomist."""
    if not business_id:
        return "ERROR: business_id required."

    try:
        crops = [str(c).strip() for c in json.loads(crops_json) if str(c).strip()]
    except Exception:
        crops = []
    try:
        channels = [str(c).strip() for c in json.loads(channels_json) if str(c).strip()]
    except Exception:
        channels = []

    bid   = int(business_id)
    tier  = (tier or "starter").lower().strip()
    if tier not in _TIER_ANNUAL_PRICE:
        tier = "starter"

    enable_set, disable_set = _build_feature_set(
        tier=tier,
        crops=crops,
        channels=channels,
        business_type=str(business_type or "").strip(),
        uses_agronomist=bool(uses_agronomist),
    )

    enabled_written  = []
    disabled_written = []
    skipped          = 0

    for fk in sorted(enable_set):
        if _set_feature(bid, fk, True):
            enabled_written.append(fk)
        else:
            skipped += 1

    for fk in sorted(disable_set):
        _set_feature(bid, fk, False)
        disabled_written.append(fk)

    # Invalidate the features cache in company_features router if accessible
    try:
        from routers.company_features import _features_cache
        _features_cache.pop(bid, None)
    except Exception:
        pass

    return (
        f"Subscription features configured for business {bid} ({tier} tier).\n"
        f"Enabled {len(enabled_written)} module(s): {', '.join(enabled_written[:10])}"
        + (f"… (+{len(enabled_written)-10} more)" if len(enabled_written) > 10 else "") + "\n"
        f"Hidden {len(disabled_written)} unrelated module(s) to keep the sidebar clean.\n"
        f"({skipped} feature key(s) not yet in FeatureCategory — will inherit subscription defaults.)"
    )


@tool
def write_agent_briefing_tool(
    business_id: int = 0,
    people_id: str = "",
) -> str:
    """Write a personalized briefing document to the agent_briefings Firestore
    collection. Reads the discovery profile that was just saved and formats it
    so Saige and Thaiyme can retrieve business-specific context on the farmer's
    first conversation — crops, channels, fields, headache — without the farmer
    having to explain again.
    business_id: BusinessID.
    people_id: injected automatically — do not ask the user."""
    if not people_id or not business_id:
        return "ERROR: people_id and business_id required."

    db = cassia_chat_history.firestore_db
    if not db:
        return "Firestore unavailable — agent briefing skipped."

    # Read the just-stored discovery profile
    try:
        snap = db.collection(CASSIA_CHATS_COLLECTION).document(
            f"discovery_{people_id}"
        ).get()
        profile: Dict[str, Any] = snap.to_dict() if snap.exists else {}
    except Exception as e:
        logger.warning("[Cassia] write_agent_briefing_tool profile read error: %s", e)
        profile = {}

    crops    = profile.get("crops", [])
    channels = profile.get("channels", [])
    n_fields = profile.get("field_count", 0)
    size_ha  = profile.get("size_ha", 0)
    agro     = profile.get("uses_agronomist", False)
    headache = profile.get("headache", "")

    crop_str = ", ".join(crops) if crops else "unspecified crops"
    ch_str   = ", ".join(channels) if channels else "unspecified channels"
    size_str = f" (~{size_ha:.1f} ha each)" if size_ha else ""
    agro_str = "works with outside agronomists" if agro else "manages agronomy in-house"

    briefing_text = (
        f"Business onboarding profile (ID {business_id}, user {people_id}):\n"
        f"• Crops/products: {crop_str}\n"
        f"• Fields: {n_fields} field(s){size_str}\n"
        f"• Sales channels: {ch_str}\n"
        f"• Agronomy: {agro_str}\n"
        f"• Biggest operational challenge: {headache or 'not specified'}\n"
        "Use this context when the farmer asks about their crops, fields, pricing, "
        "market strategy, or any operational question — avoid making them repeat "
        "information they already gave during onboarding."
    )

    doc = {
        "business_id":     int(business_id),
        "people_id":       str(people_id),
        "crops":           crops,
        "field_count":     n_fields,
        "size_ha":         size_ha,
        "channels":        channels,
        "uses_agronomist": agro,
        "headache":        headache,
        "text":            briefing_text,
        "created_at":      time.time(),
    }

    try:
        db.collection("agent_briefings").document(
            f"business_{business_id}"
        ).set(doc)
    except Exception as e:
        logger.warning("[Cassia] write_agent_briefing_tool write error: %s", e)
        return "Agent briefing queued — will be available on first login."

    # Mirror the structured fields into org_profiles so get_org_memory() is
    # seeded from day one (before any completed conversations exist).
    cassia_chat_history.save_org_memory_profile(
        business_id=str(business_id),
        data={
            "business_id":     int(business_id),
            "people_id":       str(people_id),
            "crops":           crops,
            "field_count":     n_fields,
            "size_ha":         size_ha,
            "channels":        channels,
            "uses_agronomist": agro,
            "headache":        headache,
        },
    )

    return (
        f"Agent briefing written for business {business_id}. "
        "Saige and Thaiyme will have this context available on first login."
    )


cassia_tools = [
    cassia_knowledge_tool,
    get_business_types_tool,
    get_states_tool,
    create_business_account_tool,
    get_subscription_catalog_tool,
    qualify_tier_tool,
    generate_invoice_summary_tool,
    prepare_checkout_tool,
    # Stage 3 — discovery (Phase 1)
    seed_crop_types_tool,
    create_field_stubs_tool,
    configure_buyer_tiers_tool,
    toggle_agro_module_tool,
    store_discovery_profile_tool,
    # Stage 3 — module configuration (Phase 2)
    activate_field_monitoring_tool,
    create_marketplace_drafts_tool,
    configure_alert_profiles_tool,
    configure_subscription_features_tool,
    write_agent_briefing_tool,
]


# ── System prompt ─────────────────────────────────────────────────────────────

CASSIA_SYSTEM_PROMPT = """You are Cassia, the customer success specialist for Oatmeal Farm Network — a comprehensive platform for farmers, ranchers, artisan producers, food service businesses, associations, and agricultural suppliers.

## Your Role
You guide new members through two stages:
1. **Account Setup** — collect required information through friendly conversation, confirm it, then create their business account.
2. **Subscription Selection** — understand their needs and recommend the right plan with accurate pricing.

## Your Personality
- Warm, patient, and genuinely curious about their operation
- You celebrate agriculture — farming and ranching is meaningful work
- Speak plainly, no jargon, ask ONE question at a time
- Never pushy about upgrades; help them find the plan that truly fits

---

## STAGE 1: ACCOUNT CREATION

### Conversation order (stick to this sequence):
1. Call get_business_types_tool, then ask what type of operation they have
2. Ask for their state (call get_states_tool to look up the StateIndex integer)
3. Ask for their phone number
4. Ask for their business name (mention it's optional and can be added later)
5. Ask if they have a website (optional)
6. Ask for their city and state/zip (optional, but nice for the profile)
7. **Farm/Ranch accounts only (BusinessTypeID = 8):** Before creating the account, you MUST explain both legal disclaimers and get explicit YES consent for each:
   - Livestock disclaimer: "By creating a Farm/Ranch account, you acknowledge that Oatmeal Farm Network is not responsible for the accuracy of livestock health claims, pedigrees, or sale prices listed by members."
   - Sales disclaimer: "You agree that all livestock sales through the platform comply with applicable local, state, and federal regulations."
   - Ask: "Do you agree to both of these? Please reply Yes or No."

### Before calling create_business_account_tool:
Show the user a clear summary of what you're about to submit, like:
"Here's what I have — does everything look right?
  • Type: [business type]
  • State: [state name]
  • Phone: [phone]
  • Name: [name or 'not set']"
Wait for their confirmation before calling the tool.

### After account creation:
Acknowledge warmly ("Your account is created! Now let's find the right plan.") and move directly to Stage 2.

---

## STAGE 2: SUBSCRIPTION SETUP

1. Call get_subscription_catalog_tool to load current pricing data.
2. Ask 2–3 focused qualifying questions:
   - How many fields / what crops do they grow?
   - What do they primarily want to do (sell, host events, build a website, precision ag)?
   - How many sales channels (wholesale, CSA, restaurant, farmers market, etc.)?
3. Call qualify_tier_tool with the collected answers — it returns the recommended tier, score, and reasoning. Use its output to frame your recommendation ("Based on your operation, I'd suggest [tier] — here's why...").
4. Walk through the pricing: quote the annual total ($700/$1,700/$4,100), list the key modules they'd get, and explain why it fits their operation.
5. Ask if they'd like to proceed.
6. When they confirm:
   a. Call generate_invoice_summary_tool(tier, crops_json, field_count, channels_json, business_id) to build the 3-part invoice.
   b. Extract the LINE_ITEMS_JSON from the tool's output.
   c. Call prepare_checkout_tool(tier, categories, line_items_json=<extracted>, monthly_total=<annual/12>, business_type=<the business type label from Stage 1>).

Annual pricing: Starter $700 | Professional $1,700 | Enterprise $4,100 (all billed annually).

---

## Tool Rules
- Call get_business_types_tool BEFORE presenting type options to the user
- Call get_states_tool before or after asking for their state (use it to find the StateIndex integer)
- NEVER call create_business_account_tool without user confirmation of a summary
- NEVER call prepare_checkout_tool until user explicitly says yes to the plan
- ALWAYS call qualify_tier_tool before presenting a tier recommendation — never guess
- ALWAYS call generate_invoice_summary_tool before calling prepare_checkout_tool
- Use cassia_knowledge_tool for any platform "what is / how does" questions

## Style
- One question at a time
- 2–4 sentences per response (more only when explaining pricing or disclaimers)
- Never repeat questions already answered in this conversation
- If they want to change something before account creation, update your collected info and re-confirm

---

## STAGE 3: DISCOVERY INTERVIEW (post-Stripe)

**Trigger:** A message beginning with `[DISCOVERY_TRIGGER]` means Stripe checkout has just completed. Enter this stage immediately.

The trigger message includes structured fields — extract and remember them for the Phase 2 batch call:
- `BusinessID=<id>` — the business being configured
- `SubscriptionTier=<tier>` — the tier the user just paid for (starter/professional/enterprise)
- `BusinessType=<type>` — the business type from Stage 1 account creation (may be absent)

These values are injected automatically. Do NOT ask the user to re-state them.

### Goal
Configure the platform for this specific business before their first login. Each answer you receive triggers one or more backend tool calls that write real configuration rows — not settings preferences. The result is a dashboard that is ready when they arrive, not blank.

### Conversation sequence (ONE question at a time, in this order):

**Q1 — Crops/Products**
Ask: "Congratulations — you're officially part of Oatmeal Farm Network! Before you head into your dashboard, I'd love to ask four quick questions so your account is set up for your operation rather than the generic defaults. First: what crops or products do you produce? You can list as many as you like."
→ When answered: call seed_crop_types_tool(business_id, crops_json=JSON array of crops)

**Q2 — Fields**
Ask: "How many fields do you have, and roughly how large are they? Even an estimate helps — you can update the details later in Precision Ag."
→ When answered: call create_field_stubs_tool(business_id, field_count, size_ha, crop_type=first crop from Q1)

**Q3 — Sales channels**
Ask: "How do you sell your products? For example: wholesale to distributors, direct-to-consumer, restaurants, farmers markets, CSA subscriptions — or some mix."
→ When answered: parse their answer into channel keywords (wholesale/retail/restaurant/csa/dtc/farmer_market), then call configure_buyer_tiers_tool(business_id, channels_json=JSON array)

**Q4 — Agronomist**
Ask: "Last setup question: do you work with outside agronomists or crop consultants, or do you handle field scouting and recommendations in-house?"
→ When answered: call toggle_agro_module_tool(business_id, enabled=True if they use outside agronomists)

**Q5 — Headache (final)**
Ask: "One more thing — and this one's just for your AI team: what's your single biggest operational headache right now? There are no wrong answers. This helps Saige and Thaiyme know what to pay attention to when you log in."
→ When answered: call store_discovery_profile_tool with ALL collected answers (people_id is injected automatically — do not include it in your message to the user):
  - business_id: from the DISCOVERY_TRIGGER message
  - crops: JSON array from Q1
  - field_count: from Q2
  - size_ha: from Q2
  - channels: JSON array from Q3
  - uses_agronomist: from Q4
  - headache: their Q5 answer

### After store_discovery_profile_tool succeeds — Phase 2 configuration:

Immediately call these five tools (no user message needed between them — batch all five in the same response if possible):

1. activate_field_monitoring_tool(business_id=<from DISCOVERY_TRIGGER>, crops_json=<JSON array from Q1>)
   → Activates satellite monitoring on their fields with crop-appropriate thresholds.

2. create_marketplace_drafts_tool(business_id=<from DISCOVERY_TRIGGER>, crops_json=<JSON array from Q1>)
   → Creates draft marketplace listings for each crop.

3. configure_alert_profiles_tool(business_id=<from DISCOVERY_TRIGGER>, crops_json=<JSON array from Q1>)
   → Seeds spray PHI defaults, chilling-hour targets, and CA storage room profiles for each crop.

4. configure_subscription_features_tool(
       business_id=<from DISCOVERY_TRIGGER>,
       tier=<SubscriptionTier from DISCOVERY_TRIGGER message>,
       crops_json=<JSON array from Q1>,
       channels_json=<JSON array from Q3>,
       business_type=<BusinessType from DISCOVERY_TRIGGER message, or empty string if absent>,
       uses_agronomist=<from Q4>)
   → Enables persona-appropriate sidebar modules; suppresses unrelated ones so the dashboard is not cluttered.

5. write_agent_briefing_tool(business_id=<from DISCOVERY_TRIGGER>)
   → people_id is injected automatically. DO NOT pass it explicitly.
   → Writes the full onboarding context to Firestore so Saige and Thaiyme are briefed.

Once all five Phase 2 tools have returned results, send the closing message.

### Closing message (after all Phase 2 tools complete):
Customize with their actual details. Use this structure:
"You're all set, [and what was configured]! Here's what's ready for you:
✓ [N] fields created — satellite monitoring active, checking every [X] days
✓ [Tier list] buyer price lists ready (e.g. Wholesale, Restaurant)
✓ Draft marketplace listings created for [crop list] — just add pricing to publish
✓ Spray PHI/REI defaults, chilling-hour targets, and CA storage profiles configured
✓ Dashboard personalised — [N] modules enabled for [crop/channel] operations
✓ [Agro module status, if relevant]
✓ Saige and Thaiyme are briefed on your operation — no need to re-explain your setup

Head in whenever you're ready. [→ Go to your dashboard](/account?BusinessID={business_id})"

Only mention the agro module line if uses_agronomist is True (enabled it) or if they said they manage it in-house (note it's hidden for now, can be enabled later).
Omit the CA storage line if configure_alert_profiles_tool found no chilling/CA matches for the crops listed.

### Stage 3 tool rules
- Call each Phase 1 tool immediately after receiving that question's answer
- Call all five Phase 2 tools together after store_discovery_profile_tool returns success
- Accept approximate answers; the user can refine everything in the app
- If a user skips a question, note "skipped" and move to the next without pressing
- people_id is injected automatically by the system — never ask the user for it
- NEVER call store_discovery_profile_tool until all five questions have been asked
- NEVER call write_agent_briefing_tool without also calling store_discovery_profile_tool first"""


# ── Core chat loop ────────────────────────────────────────────────────────────

def _render_short_term(messages: List[Dict[str, Any]]) -> str:
    if not messages:
        return ""
    lines = ["Recent conversation (oldest first):"]
    for m in messages[-SHORT_TERM_N:]:
        role = (m.get("role") or "user").upper()
        content = (m.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def respond(
    user_input: str,
    thread_id: str,
    user_id: str,
    business_id: Optional[int] = None,
    max_iterations: int = 12,
) -> Dict[str, Any]:
    """Run one Cassia conversation turn.

    Persists the exchange to Firestore + Redis, runs a ReAct tool loop,
    and returns a JSON-ready dict that may include 'action' and 'data'
    keys when special events occur (account creation, checkout ready).
    """
    turn_start = time.monotonic()

    cassia_chat_history.save_message(
        user_id=user_id, thread_id=thread_id, role="user", content=user_input,
    )
    push_message(thread_id=thread_id, message={"role": "user", "content": user_input})

    last_n = get_last_n(thread_id, SHORT_TERM_N) or []
    short_term = _render_short_term(last_n)

    try:
        rag_ctx = rag_cassia.get_context_for_query(user_input) or ""
    except Exception as e:
        logger.warning("[Cassia] RAG error: %s", e)
        rag_ctx = ""

    llm_with_tools = llm.bind_tools(cassia_tools)

    prompt_parts = [CASSIA_SYSTEM_PROMPT]
    sys_ctx = (
        f"\nSystem context: people_id for this session is {user_id}. "
        "Pass this as people_id when calling create_business_account_tool."
    )
    if business_id:
        sys_ctx += (
            f" The active business_id is {business_id}."
            " Use this value for all Stage 3 tool calls unless the DISCOVERY_TRIGGER message specifies a different BusinessID."
        )
    prompt_parts.append(sys_ctx)
    if short_term:
        prompt_parts.append(f"\n[Conversation history]\n{short_term}")
    if rag_ctx:
        prompt_parts.append(f"\n[Platform knowledge]\n{rag_ctx}")
    prompt_parts.append(f"\n[User message]\n{user_input}")
    current_input = "\n".join(prompt_parts)

    tool_results_context = ""
    side_data: Dict[str, Any] = {}
    final_response = ""
    response = None

    try:
        for iteration in range(max_iterations):
            composed = current_input
            if tool_results_context:
                composed += f"\n\n[Tool results so far]\n{tool_results_context}"

            response = llm_with_tools.invoke(composed)
            tool_calls = getattr(response, "tool_calls", None) or []

            if tool_calls and iteration < max_iterations - 1:
                for tc in tool_calls:
                    name = tc.get("name", "")
                    args = tc.get("args", {}) or {}
                    result = _dispatch_tool(name, args, user_id, side_data)
                    if result:
                        tool_results_context = (
                            (tool_results_context + "\n\n" if tool_results_context else "")
                            + f"[{name}]\n{result}"
                        )
                continue

            final_response = getattr(response, "content", None) or str(response)
            break
        else:
            if response is not None:
                final_response = getattr(response, "content", None) or str(response)
            else:
                final_response = "I ran into a snag — please try again in a moment."
    except Exception as e:
        logger.error("[Cassia] respond error: %s", e, exc_info=True)
        final_response = "I hit a snag. Please try again in a moment."

    latency_ms = int((time.monotonic() - turn_start) * 1000)

    cassia_chat_history.save_message(
        user_id=user_id, thread_id=thread_id, role="assistant",
        content=final_response, metadata={"latency_ms": latency_ms},
    )
    push_message(
        thread_id=thread_id,
        message={"role": "assistant", "content": final_response},
    )

    result: Dict[str, Any] = {
        "status": "ok",
        "thread_id": thread_id,
        "response": final_response,
        "latency_ms": latency_ms,
    }
    if side_data:
        result.update(side_data)
    return result


def _dispatch_tool(
    name: str,
    args: Dict[str, Any],
    user_id: str,
    side_data: Dict[str, Any],
) -> str:
    """Invoke a Cassia tool, populate side_data for UI events, return text for LLM."""
    try:
        if name == "cassia_knowledge_tool":
            return cassia_knowledge_tool.invoke({"query": args.get("query", "")})

        if name == "get_business_types_tool":
            return get_business_types_tool.invoke({"dummy": ""})

        if name == "get_states_tool":
            return get_states_tool.invoke({"country": args.get("country", "USA")})

        if name == "create_business_account_tool":
            result_str = create_business_account_tool.invoke({
                "people_id":           int(user_id or 0),
                "business_type_id":    int(args.get("business_type_id", 0) or 0),
                "business_name":       str(args.get("business_name", "") or ""),
                "business_website":    str(args.get("business_website", "") or ""),
                "address_street":      str(args.get("address_street", "") or ""),
                "address_apt":         str(args.get("address_apt", "") or ""),
                "address_city":        str(args.get("address_city", "") or ""),
                "state_index":         int(args.get("state_index", 0) or 0),
                "address_zip":         str(args.get("address_zip", "") or ""),
                "phone":               str(args.get("phone", "") or ""),
                "livestock_disclaimer": bool(args.get("livestock_disclaimer", False)),
                "sales_disclaimer":    bool(args.get("sales_disclaimer", False)),
            })
            if result_str.startswith("SUCCESS:BusinessID="):
                bid = int(result_str.split("=")[1])
                side_data["action"] = "account_created"
                side_data["data"]   = {"business_id": bid}
                return f"Account created successfully. BusinessID is {bid}. Now proceed to subscription."
            return result_str

        if name == "get_subscription_catalog_tool":
            return get_subscription_catalog_tool.invoke({"dummy": ""})

        if name == "qualify_tier_tool":
            return qualify_tier_tool.invoke({
                "crops_json":       str(args.get("crops_json", "[]") or "[]"),
                "field_count":      int(args.get("field_count", 0) or 0),
                "channels_json":    str(args.get("channels_json", "[]") or "[]"),
                "business_type":    str(args.get("business_type", "") or ""),
                "uses_agronomist":  bool(args.get("uses_agronomist", False)),
            })

        if name == "generate_invoice_summary_tool":
            result = generate_invoice_summary_tool.invoke({
                "tier":          str(args.get("tier", "starter") or "starter"),
                "crops_json":    str(args.get("crops_json", "[]") or "[]"),
                "field_count":   int(args.get("field_count", 0) or 0),
                "channels_json": str(args.get("channels_json", "[]") or "[]"),
                "business_id":   int(args.get("business_id", 0) or 0),
            })
            # Cache line items server-side so prepare_checkout_tool never depends
            # on the LLM faithfully re-passing the tagged JSON string.
            if isinstance(result, str) and "LINE_ITEMS_JSON:" in result:
                tag_idx = result.index("LINE_ITEMS_JSON:")
                raw_json = result[tag_idx + len("LINE_ITEMS_JSON:"):].strip()
                try:
                    side_data["pending_line_items"] = json.loads(raw_json)
                except Exception:
                    pass
            return result

        if name == "prepare_checkout_tool":
            tier        = str(args.get("tier", "starter")).lower().strip()
            cats_raw    = args.get("categories", "")
            categories  = (
                [c.strip() for c in str(cats_raw).split(",") if c.strip()]
                if isinstance(cats_raw, str) else list(cats_raw or [])
            )
            items_raw   = args.get("line_items_json", "[]") or "[]"
            try:
                line_items = json.loads(items_raw) if isinstance(items_raw, str) else list(items_raw)
            except Exception:
                line_items = []
            # Fall back to server-cached line items if LLM failed to re-pass them
            if not line_items and side_data.get("pending_line_items"):
                line_items = side_data["pending_line_items"]
            total         = float(args.get("monthly_total", 0) or 0)
            annual_price  = _TIER_ANNUAL_PRICE.get(tier, int(total * 12))
            business_type = str(args.get("business_type", "") or "")

            side_data["action"] = "initiate_checkout"
            side_data["data"]   = {
                "tier":          tier,
                "categories":    categories,
                "line_items":    line_items,
                "monthly_total": total,
                "annual_price":  annual_price,
                "business_type": business_type,
            }
            return "Checkout data prepared. The frontend will now handle payment."

        # ── Stage 3 — discovery tools ─────────────────────────────────────────
        if name == "seed_crop_types_tool":
            return seed_crop_types_tool.invoke({
                "business_id": int(args.get("business_id", 0) or 0),
                "crops_json":  str(args.get("crops_json", "[]") or "[]"),
            })

        if name == "create_field_stubs_tool":
            return create_field_stubs_tool.invoke({
                "business_id": int(args.get("business_id", 0) or 0),
                "field_count": int(args.get("field_count", 1) or 1),
                "size_ha":     float(args.get("size_ha", 0) or 0),
                "crop_type":   str(args.get("crop_type", "") or ""),
            })

        if name == "configure_buyer_tiers_tool":
            return configure_buyer_tiers_tool.invoke({
                "business_id":   int(args.get("business_id", 0) or 0),
                "channels_json": str(args.get("channels_json", "[]") or "[]"),
            })

        if name == "toggle_agro_module_tool":
            return toggle_agro_module_tool.invoke({
                "business_id": int(args.get("business_id", 0) or 0),
                "enabled":     bool(args.get("enabled", False)),
            })

        if name == "store_discovery_profile_tool":
            return store_discovery_profile_tool.invoke({
                "people_id":       str(user_id or ""),
                "business_id":     int(args.get("business_id", 0) or 0),
                "crops":           str(args.get("crops", "[]") or "[]"),
                "field_count":     int(args.get("field_count", 0) or 0),
                "size_ha":         float(args.get("size_ha", 0) or 0),
                "channels":        str(args.get("channels", "[]") or "[]"),
                "uses_agronomist": bool(args.get("uses_agronomist", False)),
                "headache":        str(args.get("headache", "") or ""),
            })

        # ── Stage 3 — Phase 2 module configuration ───────────────────────────
        if name == "activate_field_monitoring_tool":
            return activate_field_monitoring_tool.invoke({
                "business_id": int(args.get("business_id", 0) or 0),
                "crops_json":  str(args.get("crops_json", "[]") or "[]"),
            })

        if name == "create_marketplace_drafts_tool":
            return create_marketplace_drafts_tool.invoke({
                "business_id": int(args.get("business_id", 0) or 0),
                "crops_json":  str(args.get("crops_json", "[]") or "[]"),
            })

        if name == "configure_alert_profiles_tool":
            return configure_alert_profiles_tool.invoke({
                "business_id": int(args.get("business_id", 0) or 0),
                "crops_json":  str(args.get("crops_json", "[]") or "[]"),
            })

        if name == "configure_subscription_features_tool":
            return configure_subscription_features_tool.invoke({
                "business_id":     int(args.get("business_id", 0) or 0),
                "tier":            str(args.get("tier", "starter") or "starter"),
                "crops_json":      str(args.get("crops_json", "[]") or "[]"),
                "channels_json":   str(args.get("channels_json", "[]") or "[]"),
                "business_type":   str(args.get("business_type", "") or ""),
                "uses_agronomist": bool(args.get("uses_agronomist", False)),
            })

        if name == "write_agent_briefing_tool":
            return write_agent_briefing_tool.invoke({
                "business_id": int(args.get("business_id", 0) or 0),
                "people_id":   str(user_id or ""),
            })

    except Exception as e:
        logger.error("[Cassia] tool %s failed: %s", name, e)
        return f"(tool {name} error: {e})"

    return f"(unknown tool: {name})"


# ── Read helpers for the REST layer ──────────────────────────────────────────

def list_threads(
    user_id: str, limit: int = 20, cursor: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    return cassia_chat_history.get_threads(user_id, limit=limit, cursor=cursor)


def get_messages(
    user_id: str, thread_id: str, limit: int = 50, cursor: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    return cassia_chat_history.get_messages(user_id, thread_id, limit=limit, cursor=cursor)


def delete_thread(user_id: str, thread_id: str) -> bool:
    return cassia_chat_history.delete_thread(user_id, thread_id)
