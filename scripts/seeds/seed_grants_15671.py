"""
seed_grants_15671.py — Grant & Program Tracker demo data for BusinessID=15671 (Food World).
Adds more GrantPrograms (relevant to an alpaca+produce farm in Colorado) and
BusinessGrantTracking entries for BID=15671 across all status values.
Idempotent: skips grants by Title, skips tracking by GrantID+BusinessID.
"""
import sys, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import get_db
from sqlalchemy import text

BID = 15671
db = next(get_db())

def q(sql, params=None):
    db.execute(text(sql), params or {})

def first(sql, params=None):
    return db.execute(text(sql), params or {}).scalar()

# ─────────────────────────────────────────────
# 1. ADD GRANT PROGRAMS
# ─────────────────────────────────────────────
print("\n=== Grant Programs ===")

# (Title, Agency, ProgramType, MaxAmount, Deadline, IsRecurring, Eligibility, ExternalUrl, Description)
GRANTS = [
    (
        "Livestock Forage Disaster Program (LFP)",
        "USDA FSA", "Disaster Assistance", 125000, None, 1,
        "Livestock producers who suffered grazing losses due to drought or wildfire",
        "https://www.fsa.usda.gov/programs-and-services/disaster-assistance-program/livestock-forage/index",
        "Provides compensation for grazing losses due to drought on privately owned, cash-leased, or tribal land.",
    ),
    (
        "Emergency Livestock Assistance Program (ELAP)",
        "USDA FSA", "Disaster Assistance", 50000, None, 1,
        "Livestock producers who suffered losses not covered by LFP",
        "https://www.fsa.usda.gov/programs-and-services/disaster-assistance-program/emergency-livestock-assistance/index",
        "Provides emergency assistance for losses of livestock, honeybees, and farm-raised fish due to disaster.",
    ),
    (
        "Conservation Reserve Program (CRP)",
        "USDA FSA", "Conservation", None, "2026-11-30", 1,
        "Agricultural producers with cropland meeting soil, water, and air quality criteria",
        "https://www.fsa.usda.gov/programs-and-services/conservation-programs/conservation-reserve-program/index",
        "Long-term rental payments to farmers for converting environmentally sensitive cropland to conservation cover.",
    ),
    (
        "SARE Farmer/Rancher Grant",
        "USDA SARE", "Research & Education", 22500, "2026-08-15", 1,
        "Farmers and ranchers in the North Central region",
        "https://northcentral.sare.org/grants/apply-for-a-grant/farmer-rancher-grant/",
        "Funds innovative on-farm research and demonstration projects that advance sustainable agriculture.",
    ),
    (
        "Farmers Market Promotion Program (FMPP)",
        "USDA AMS", "Marketing", 500000, "2026-09-30", 1,
        "Domestic farmers markets, roadside stands, CSAs, and agritourism operations",
        "https://www.ams.usda.gov/services/grants/fmpp",
        "Helps expand domestic direct producer-to-consumer markets through creation, promotion, and expansion of farmers markets.",
    ),
    (
        "Local Food Promotion Program (LFPP)",
        "USDA AMS", "Marketing", 500000, "2026-09-30", 1,
        "Agricultural businesses, cooperatives, and local food enterprises",
        "https://www.ams.usda.gov/services/grants/lfpp",
        "Supports the development and expansion of local and regional food business enterprises to increase domestic consumption.",
    ),
    (
        "Specialty Crop Block Grant Program (SCBGP)",
        "USDA AMS / Colorado Dept. of Agriculture", "Specialty Crops", 200000, "2026-10-15", 1,
        "Organizations that enhance the competitiveness of specialty crops in Colorado",
        "https://www.ams.usda.gov/services/grants/scbgp",
        "Enhances the competitiveness of specialty crops — including fruits, vegetables, tree nuts, herbs, and nursery crops.",
    ),
    (
        "High Tunnel System Initiative (EQIP Practice 325)",
        "USDA NRCS", "Conservation", 50000, "2026-06-01", 1,
        "Agricultural producers seeking to extend the growing season with season extension structures",
        "https://www.nrcs.usda.gov/programs-initiatives/eqip-environmental-quality-incentives",
        "Covers cost-share for installing high tunnel structures to extend growing season and reduce water use.",
    ),
    (
        "Whole Farm Revenue Protection (WFRP)",
        "USDA RMA", "Crop Insurance", None, None, 1,
        "Farms with diverse commodity portfolios including specialty crops and livestock",
        "https://www.rma.usda.gov/en/Policy-and-Procedure/Insurance-Plans/Whole-Farm-Revenue-Protection",
        "Provides a safety net for all commodities on the farm under one insurance policy — including specialty crops and livestock.",
    ),
    (
        "Colorado Agricultural Value-Added Grant (CAVAG)",
        "Colorado Dept. of Agriculture", "Business Development", 75000, "2026-07-31", 0,
        "Colorado-based agricultural producers adding value to farm products",
        "https://ag.colorado.gov/grants",
        "State-level matching grant for Colorado farms investing in processing, packaging, or new product lines.",
    ),
    (
        "Colorado Ag Innovation Grant — Soil Health",
        "Colorado Dept. of Agriculture", "Soil Health", 30000, "2026-05-31", 0,
        "Colorado farms implementing soil health practices for the first time",
        "https://ag.colorado.gov/grants",
        "Supports adoption of cover cropping, reduced tillage, and compost application on Colorado agricultural operations.",
    ),
    (
        "Agri-Business Child Care Act Grant",
        "USDA Rural Development", "Rural Development", 60000, None, 1,
        "Agricultural employers and associations providing childcare for farmworker families",
        "https://www.rd.usda.gov/programs-services/business-programs",
        "Helps provide childcare services for children of agricultural workers.",
    ),
    (
        "Rural Energy for America Program (REAP)",
        "USDA Rural Development", "Energy", 500000, "2026-10-31", 1,
        "Agricultural producers and rural small businesses in eligible areas",
        "https://www.rd.usda.gov/programs-services/energy-programs/rural-energy-america-program-renewable-energy-systems-energy-efficiency",
        "Grants and loan guarantees for agricultural producers to purchase and install renewable energy systems or make energy efficiency improvements.",
    ),
    (
        "FSA Direct Farm Ownership Loan",
        "USDA FSA", "Loans", 600000, None, 1,
        "Beginning and socially disadvantaged farmers seeking to purchase farmland",
        "https://www.fsa.usda.gov/programs-and-services/farm-loan-programs/farm-ownership-loans/index",
        "Provides 100% financing for purchasing or enlarging a farm, constructing or repairing farm buildings, or paying closing costs.",
    ),
    (
        "Alpaca Fiber Cooperative Development Grant",
        "USDA Rural Development", "Cooperative Development", 200000, "2026-12-01", 0,
        "Agricultural cooperatives including livestock fiber producers",
        "https://www.rd.usda.gov/programs-services/business-programs/rural-cooperative-development-grants",
        "Supports the establishment and operation of centers for rural cooperative development, including fiber-producing livestock cooperatives.",
    ),
    (
        "Colorado State University Extension — Small Farm Grant",
        "Colorado State University Extension", "Training/Education", 10000, "2026-08-31", 1,
        "Small and beginning farmers in Colorado with less than $250K gross revenue",
        "https://extension.colostate.edu/smallfarms",
        "Funds farm planning, sustainability assessment, and technical assistance for small farms in partnership with CSU Extension.",
    ),
    (
        "Socially Disadvantaged Groups Grant (SDGG)",
        "USDA Rural Development", "Technical Assistance", 175000, None, 1,
        "Cooperatives and associations working with socially disadvantaged groups in rural areas",
        "https://www.rd.usda.gov/programs-services/business-programs/socially-disadvantaged-groups-grant",
        "Provides technical assistance to socially disadvantaged groups in rural areas to form and operate cooperatives.",
    ),
    (
        "Watershed and Flood Prevention Operations (WFPO)",
        "USDA NRCS", "Conservation", 5000000, None, 1,
        "Local organizations (city, county, tribal, state, non-profit) working with NRCS",
        "https://www.nrcs.usda.gov/programs-initiatives/watershed-and-flood-prevention-operations",
        "Provides technical and financial assistance to prevent erosion, sedimentation, and flooding on agricultural and non-agricultural lands.",
    ),
]

added_grants = 0
grant_ids = {}

for (title, agency, ptype, max_amt, deadline, recurring, eligibility, url, desc) in GRANTS:
    gid = first("SELECT GrantID FROM GrantPrograms WHERE Title=:t", {"t": title})
    if not gid:
        gid = first("""
            INSERT INTO GrantPrograms
                (Title, Agency, ProgramType, MaxAmount, Deadline, IsRecurring, Eligibility, ExternalUrl, Description)
            OUTPUT INSERTED.GrantID
            VALUES (:title, :agency, :pt, :amt, :dl, :rec, :elig, :url, :desc)
        """, {
            "title": title, "agency": agency, "pt": ptype, "amt": max_amt,
            "dl": deadline, "rec": recurring, "elig": eligibility, "url": url, "desc": desc,
        })
        added_grants += 1
        print(f"  Added: {title[:60]}")
    else:
        print(f"  Exists: {title[:60]}")
    grant_ids[title] = gid

db.commit()
print(f"Grants added: {added_grants}")

# Also grab the pre-seeded grant IDs (from the router seed)
for row in db.execute(text("SELECT GrantID, Title FROM GrantPrograms WHERE GrantID <= 10")).fetchall():
    grant_ids[row[1]] = row[0]

# ─────────────────────────────────────────────
# 2. BUSINESS GRANT TRACKING FOR BID=15671
# ─────────────────────────────────────────────
print("\n=== Business Grant Tracking ===")

today = datetime.date.today()

def days_ago(n): return (today - datetime.timedelta(days=n)).isoformat()
def days_from(n): return (today + datetime.timedelta(days=n)).isoformat()

# (grant_title, status, notes, applied_date, result_date, amount_received)
TRACKING = [
    # AWARDED — 2 entries with amounts received
    (
        "EQIP — Environmental Quality Incentives Program",
        "awarded",
        "Approved for high tunnel installation + cover crop practices. "
        "Assigned NRCS field office contact: Maria Sandoval (970-555-0180). Payment received June 2025.",
        days_ago(280), days_ago(180), 34500.00,
    ),
    (
        "Organic Certification Cost Share Program",
        "awarded",
        "Received full 75% cost share on CCOF certification renewal. "
        "Paid out in two installments. Will reapply next cycle.",
        days_ago(210), days_ago(150), 375.00,
    ),
    # SUBMITTED — 2 entries waiting on result
    (
        "SARE Farmer/Rancher Grant",
        "submitted",
        "Submitted on-farm trial proposal: 'Alpaca Manure Compost vs. Synthetic Fertilizer "
        "on Yield of Heirloom Tomatoes in Northern Colorado.' Waiting on panel review. "
        "Contact: Dr. Anita Rivers at CSU.",
        days_ago(45), None, None,
    ),
    (
        "High Tunnel System Initiative (EQIP Practice 325)",
        "submitted",
        "Applied for 3 additional high tunnel structures (30x96 ft each) to extend tomato "
        "and pepper season. NRCS practice 325. Application ranked in funding window. "
        "Awaiting obligation.",
        days_ago(60), None, None,
    ),
    # IN PROGRESS — 3 entries being worked on
    (
        "Farmers Market Promotion Program (FMPP)",
        "in_progress",
        "Preparing narrative on how Food World's Boulder Farmers Market booth expands "
        "direct-to-consumer access in a low-income census tract. Need letters of support from "
        "Boulder County and the Colorado Farmers Market Association by deadline.",
        None, None, None,
    ),
    (
        "Colorado Agricultural Value-Added Grant (CAVAG)",
        "in_progress",
        "Working with CDA business dev rep on application. Plan: commercial alpaca fiber "
        "processing equipment (drum carder + picker) to move from raw fleece to roving for "
        "wholesale. Budget draft in progress — target $62,000 ask.",
        None, None, None,
    ),
    (
        "Rural Energy for America Program (REAP)",
        "in_progress",
        "Getting quotes for 48-panel solar array on barn roof (approx. 18 kW). "
        "Targeting 25% grant + USDA loan guarantee for remainder. "
        "Solar vendor: Front Range Solar Solutions — meeting scheduled May 20.",
        None, None, None,
    ),
    # INTERESTED — 3 entries on the radar
    (
        "Specialty Crop Block Grant Program (SCBGP)",
        "interested",
        "Colorado Dept. of Agriculture administers. Could apply through Colorado Specialty "
        "Crop Growers Association — they handle the consortium application. "
        "Worth reaching out to association director.",
        None, None, None,
    ),
    (
        "Alpaca Fiber Cooperative Development Grant",
        "interested",
        "Long-shot but relevant — would require partnering with 2-3 other alpaca ranches "
        "to form a cooperative. Have informal conversations with Sunrise Alpacas (Estes Park) "
        "and Rocky Mountain Fiber Arts (Longmont). No formal steps taken yet.",
        None, None, None,
    ),
    (
        "FSA Direct Farm Ownership Loan",
        "interested",
        "Exploring land acquisition adjacent to current lease — roughly 40 acres at "
        "Larimer County Road 15. Direct loan could cover up to $600K. "
        "Need to pull together farm business plan and 3 years of tax returns first.",
        None, None, None,
    ),
    # DECLINED — 1 entry
    (
        "Value-Added Producer Grant (VAPG)",
        "declined",
        "Applied in Sept 2025 for alpaca fiber value-add processing project. "
        "Score: 72/100 — fell below funding cutoff of 78. Feedback: business plan "
        "financial projections lacked detail. Will strengthen and reapply next cycle.",
        days_ago(240), days_ago(120), None,
    ),
    # NOT ELIGIBLE — 1 entry
    (
        "Beginning Farmer and Rancher Development Program",
        "not_eligible",
        "This program funds organizations that train beginning farmers — not individual "
        "farms. Food World does not qualify as a training organization. "
        "Noted for possible future collaboration with Weld County Extension.",
        None, None, None,
    ),
]

added_tracking = 0
for (grant_title, status, notes, applied, result, amount) in TRACKING:
    gid = grant_ids.get(grant_title)
    if not gid:
        print(f"  WARN: grant not found: {grant_title[:50]}")
        continue
    exists = first(
        "SELECT TrackingID FROM BusinessGrantTracking WHERE GrantID=:g AND BusinessID=:b",
        {"g": gid, "b": BID}
    )
    if exists:
        print(f"  Skip (exists): {grant_title[:55]}")
        continue
    q("""
        INSERT INTO BusinessGrantTracking
            (GrantID, BusinessID, Status, Notes, AppliedDate, ResultDate, AmountReceived)
        VALUES (:g, :b, :s, :n, :ap, :rd, :amt)
    """, {
        "g": gid, "b": BID, "s": status, "n": notes,
        "ap": applied, "rd": result, "amt": amount,
    })
    added_tracking += 1
    label = status.upper().ljust(14)
    print(f"  {label}  {grant_title[:50]}")

db.commit()
print(f"\nTracking entries added: {added_tracking}")
print("Done.")
