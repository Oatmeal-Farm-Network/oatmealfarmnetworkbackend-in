import time
from fastapi import APIRouter, Depends, Query
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

# Simple in-memory TTL cache: {business_id_or_None: (result, expires_at)}
_features_cache: dict = {}
_FEATURES_TTL = 60  # seconds

router = APIRouter(prefix="/api/company", tags=["company"])

# Canonical feature registry — any key used by the frontend must appear here
# so /app/admin/site-management (which reads CompanySiteManagement) can toggle
# it and subscription packages can reference it. Ordering controls display
# order in the admin UI.
DEFAULT_FEATURES = [
    ("precision_ag",         "Precision Ag",              0.0,   0.0,  1),
    ("blog",                 "Blog",                      0.0,   0.0,  2),
    ("farm_2_table",         "Farm 2 Table",              0.0,   0.0,  3),
    ("livestock",            "Livestock",                 0.0,   0.0,  4),
    ("products",             "Products",                  0.0,   0.0,  5),
    ("services",             "Services",                  0.0,   0.0,  6),
    ("events",               "Events",                    0.0,   0.0,  7),
    ("properties",           "Properties",                0.0,   0.0,  8),
    ("associations",         "Associations",              0.0,   0.0,  9),
    ("my_website",           "My Website",               25.0, 200.0, 10),
    ("audio_settings",       "Audio Settings",            0.0,   0.0, 11),
    ("accounting",           "Accounting",                0.0,   0.0, 12),
    ("testimonials",         "Testimonials",              0.0,   0.0, 13),
    ("provenance",           "Sourced-From Cards",        0.0,   0.0, 14),
    ("chef_dashboard",       "Chef Dashboard",            0.0,   0.0, 15),
    ("pairsley",             "Pairsley AI (Restaurants)", 0.0,   0.0, 16),
    ("rosemarie",            "Rosemarie AI (Artisans)",   0.0,   0.0, 17),
    ("restaurant_sourcing",  "Restaurant Sourcing",       0.0,   0.0, 18),
    ("equipment",            "Equipment",                 0.0,   0.0, 20),
    ("food_wanted",          "Food Wanted",               0.0,   0.0, 21),
    ("job_board",            "Job Board",                 0.0,   0.0, 22),
    ("csa_management",       "CSA Management",            0.0,   0.0, 23),
    ("csa_advanced",         "CSA Advanced",              0.0,   0.0, 24),
    ("land_leasing",         "Land Leasing",              0.0,   0.0, 25),
    ("certifications",       "Certifications",            0.0,   0.0, 26),
    ("supplier_directory",   "Supplier Directory",        0.0,   0.0, 27),
    ("grants_programs",      "Grants & Programs",         0.0,   0.0, 28),
    ("education_center",     "Education Center",          0.0,   0.0, 29),
    ("commodity_prices",     "Commodity Prices",          0.0,   0.0, 30),
    ("forums",               "Forums",                    0.0,   0.0, 31),
    ("meetings",             "Meetings",                  0.0,   0.0, 32),
    ("food_aggregation",     "Food Aggregation Hub",      0.0,   0.0, 33),
    ("cold_chain",               "Cold Chain & Logistics",              29.0, 290.0, 34),
    ("farmer_settlement",        "Farmer Settlement & Pay",             19.0, 190.0, 35),
    ("enterprise_supply_chain",  "Enterprise Supply Chain Intelligence",49.0, 490.0, 36),
    ("hr_management",            "HR & Workforce Management",           19.0, 190.0, 37),
    ("farm_inputs",              "Farm Inputs & Chemical Inventory",     0.0,   0.0, 38),
    ("crop_budgeting",           "Crop Budgeting & Actuals",             0.0,   0.0, 39),
    ("traceability",             "Harvest Lot Traceability",             0.0,   0.0, 40),
    ("farm_infrastructure",      "Farm Infrastructure & Maintenance",    0.0,   0.0, 41),
    ("farm_kpi",                 "Farm KPI Dashboard & Alerts",          0.0,   0.0, 42),
    # ── New AgriERP modules ──────────────────────────────────────────────────
    ("nursery_management",   "Nursery & Early Growth",    0.0,   0.0, 43),
    ("outgrower_management", "Contract Farming / Outgrower", 0.0, 0.0, 44),
    ("procurement",          "Purchase & Procurement",    0.0,   0.0, 45),
    ("work_orders",          "Work Orders & Field Crews", 0.0,   0.0, 46),
    ("packhouse_qc",         "Packhouse & QC Inspection", 0.0,   0.0, 47),
    ("plant_tagging",        "Plant Tagging & Asset Geo", 0.0,   0.0, 48),
    ("export_compliance",    "Export Compliance & Traceability",     0.0, 0.0, 49),
    ("picker_performance",   "Picker Performance Tracking",          0.0, 0.0, 50),
    ("iot_greenhouse",       "IoT Greenhouse Monitoring",            9.0, 90.0, 51),
    ("perishable_traceability", "Perishable Traceability & Compliance", 0.0, 0.0, 52),
    ("chilling_hours",       "Chilling Hour & Bloom Forecast",       0.0, 0.0, 53),
    ("grain_bin_monitoring", "Grain Bin & Silo Monitoring",          9.0, 90.0, 54),
    ("scale_tickets",        "Scale Tickets & Contract Reconciliation", 0.0, 0.0, 55),
    ("harvest_bins",         "Bin-Level Harvest Traceability",       0.0, 0.0, 56),
    ("ca_storage",           "CA Cold Storage Management",           9.0, 90.0, 57),
    ("spray_applications",   "Spray & Chemical Application Log",     0.0,  0.0, 58),
    ("pest_scouting",        "Pest & Disease Scouting Log",          0.0,  0.0, 59),
    ("irrigation_mgmt",      "Irrigation & Water Management",         9.0, 90.0, 60),
    ("equipment_maint",      "Equipment Maintenance Tracker",         0.0,  0.0, 61),
    ("soil_tests",           "Soil Test Records",                     0.0,  0.0, 62),
    ("cash_flow_forecast",   "Cash Flow Forecasting",                 0.0,  0.0, 63),
    ("field_activity_journal", "Field Activity Journal",              0.0,  0.0, 64),
    ("yield_records",        "Yield & Production Records",            0.0,  0.0, 65),
    ("report_center",        "Report & Export Center",                0.0,  0.0, 66),
    ("field_health_dashboard", "Field Health Dashboard",              0.0,  0.0, 67),
    ("nutrient_mgmt",        "Nutrient Management",                   0.0,  0.0, 68),
    ("farm_pl",              "Farm P&L Dashboard",                    0.0,  0.0, 69),
    ("document_vault",       "Document Vault",                        0.0,  0.0, 70),
    ("weather_dashboard",    "Weather & Climate Dashboard",           0.0,  0.0, 71),
    ("crop_planning",        "Crop Planning Calendar",                0.0,  0.0, 72),
    ("seed_varieties",       "Seed & Variety Management",             0.0,  0.0, 73),
    ("farm_safety",          "Farm Safety & Incident Log",            0.0,  0.0, 74),
    ("buyer_crm",            "Buyer & Customer CRM",                  0.0,  0.0, 75),
    ("compliance_audit",     "Compliance & Audit Manager",            0.0,  0.0, 76),
    ("harvest_scheduling",   "Harvest Scheduling & Labor Planner",    0.0,  0.0, 77),
    ("price_list",           "Price List & Quote Builder",            0.0,  0.0, 78),
    ("farm_stand",           "Farm Stand & Market POS",               0.0,  0.0, 79),
    ("delivery_routes",      "Delivery Route Planner",                0.0,  0.0, 80),
    ("agro_consultations",   "Agronomist Consultation Log",           0.0,  0.0, 81),
    ("business_directory",   "Business Directory",        0.0,   0.0, 98),
    ("food_system_newsfeed", "Food System Newsfeed",      0.0,   0.0, 99),
]


# Fallback CategoryName → feature_key for rows seeded before FeatureKey column existed
_CATEGORY_NAME_MAP = {
    'Precision Ag':                  'precision_ag',
    'Livestock & Herd Health':       'livestock',
    'Livestock Marketplace':         'livestock',
    'Farm 2 Table — Seller':         'farm_2_table',
    'Farm 2 Table — Buyer':          'farm_2_table',
    'Products & Storefront':         'products',
    'Equipment Marketplace':         'equipment',
    'Food Wanted Board':             'food_wanted',
    'Services Directory':            'services',
    'CSA':                           'csa_management',
    'Events':                        'events',
    'Job Board':                     'job_board',
    'Land Leasing':                  'land_leasing',
    'Certifications Tracker':        'certifications',
    'Supplier Directory':            'supplier_directory',
    'Grants & Programs':             'grants_programs',
    'Education Center':              'education_center',
    'Commodity Prices':              'commodity_prices',
    'Forums & Community':            'forums',
    'Blog':                          'blog',
    'Website Builder (Lavendir AI)': 'my_website',
    'Accounting':                    'accounting',
    'Testimonials & Social Proof':   'testimonials',
    'Properties Management':         'properties',
    'Food Aggregation Hub':          'food_aggregation',
    'Cold Chain & Logistics':        'cold_chain',
    'Farmer Settlement & Pay':       'farmer_settlement',
    'Meetings':                      'meetings',
}


def _business_service_overrides(business_id: int, db: Session) -> Optional[dict]:
    """Return {feature_key: is_enabled} from BusinessServiceAccess if any rows exist.
    Resolves feature_key via FeatureCategory.FeatureKey first, then CategoryName fallback."""
    try:
        rows = db.execute(
            text("""
                SELECT fc.FeatureKey, fc.CategoryName, bsa.IsEnabled
                FROM BusinessServiceAccess bsa
                JOIN FeatureCategory fc ON fc.CategoryID = bsa.CategoryID
                WHERE bsa.BusinessID = :bid
            """),
            {"bid": business_id},
        ).fetchall()
    except Exception:
        return None
    if not rows:
        return None
    result: dict = {}
    for r in rows:
        fk = r[0] or _CATEGORY_NAME_MAP.get(r[1])
        if fk:
            # IsEnabled=True wins if the same key appears multiple times (e.g. Farm 2 Table Seller+Buyer)
            result[fk] = result.get(fk, False) or bool(r[2])
    return result if result else None


@router.get("/features")
def get_features(
    business_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Return feature flags for a business.

    Priority order (highest first):
    1. Per-business admin overrides in BusinessServiceAccess (if any rows exist for this business).
    2. Subscription package features (if business has a SubscriptionTier set).
    3. Site-wide CompanySiteManagement flags (fallback).
    """
    cache_key = business_id
    now = time.time()
    cached = _features_cache.get(cache_key)
    if cached and now < cached[1]:
        return cached[0]

    result = _get_features_uncached(business_id, db)
    _features_cache[cache_key] = (result, now + _FEATURES_TTL)
    return result


def _get_features_uncached(business_id: Optional[int], db: Session):
    if business_id is not None:
        # 1. Check per-business admin service overrides first
        overrides = _business_service_overrides(business_id, db)
        if overrides is not None:
            # Use DEFAULT_FEATURES for name/price metadata; iterate overrides directly
            # so features don't need to pre-exist in CompanySiteManagement.
            meta = {key: (name, monthly, yearly, sort) for key, name, monthly, yearly, sort in DEFAULT_FEATURES}
            result = []
            for key, is_enabled in overrides.items():
                if is_enabled:
                    m = meta.get(key, (key, 0.0, 0.0, 99))
                    result.append({
                        "feature_key":   key,
                        "feature_name":  m[0],
                        "is_enabled":    True,
                        "monthly_price": float(m[1]),
                        "yearly_price":  float(m[2]),
                        "sort_order":    m[3],
                    })
            return sorted(result, key=lambda x: x["sort_order"])

        # 2. Subscription tier
        tier_row = db.execute(
            text("SELECT SubscriptionTier FROM Business WHERE BusinessID = :bid"),
            {"bid": business_id},
        ).fetchone()

        has_subscription = tier_row and tier_row[0] and str(tier_row[0]).strip()

        if has_subscription:
            rows = db.execute(
                text(
                    """
                    SELECT csm.FeatureKey, csm.FeatureName, csm.IsEnabled,
                           csm.MonthlyPrice, csm.YearlyPrice, csm.SortOrder
                    FROM Business b
                    JOIN SubscriptionPackage sp ON sp.PackageName = b.SubscriptionTier
                    JOIN SubscriptionPackageFeature spf ON spf.PackageID = sp.PackageID
                    JOIN CompanySiteManagement csm ON csm.FeatureID = spf.FeatureID
                    WHERE b.BusinessID = :bid
                      AND sp.IsActive = 1
                    ORDER BY csm.SortOrder
                    """
                ),
                {"bid": business_id},
            ).fetchall()

            return [
                {
                    "feature_key":   r[0],
                    "feature_name":  r[1],
                    "is_enabled":    True,
                    "monthly_price": float(r[3]),
                    "yearly_price":  float(r[4]),
                    "sort_order":    r[5],
                }
                for r in rows
            ]

    # 3. Site-wide fallback
    rows = db.execute(
        text(
            "SELECT FeatureKey, FeatureName, IsEnabled, MonthlyPrice, YearlyPrice, SortOrder "
            "FROM CompanySiteManagement ORDER BY SortOrder"
        )
    ).fetchall()
    return [
        {
            "feature_key":   r[0],
            "feature_name":  r[1],
            "is_enabled":    bool(r[2]),
            "monthly_price": float(r[3]),
            "yearly_price":  float(r[4]),
            "sort_order":    r[5],
        }
        for r in rows
    ]


@router.post("/features/register-defaults")
def register_default_features(db: Session = Depends(get_db)):
    """Idempotently insert any missing DEFAULT_FEATURES into CompanySiteManagement.

    Safe to call repeatedly. Existing rows are left untouched — admins may have
    adjusted names, prices, IsEnabled, or SortOrder via /app/admin/site-management.
    Only brand-new feature keys are inserted.
    """
    existing = {
        r[0] for r in db.execute(text("SELECT FeatureKey FROM CompanySiteManagement")).fetchall()
    }
    inserted = []
    for key, name, monthly, yearly, sort_order in DEFAULT_FEATURES:
        if key in existing:
            continue
        db.execute(
            text(
                """
                INSERT INTO CompanySiteManagement
                    (FeatureKey, FeatureName, IsEnabled, MonthlyPrice, YearlyPrice, SortOrder)
                VALUES (:k, :n, 1, :m, :y, :s)
                """
            ),
            {"k": key, "n": name, "m": monthly, "y": yearly, "s": sort_order},
        )
        inserted.append(key)
    db.commit()
    return {"inserted": inserted, "already_present": sorted(existing)}
