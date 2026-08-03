"""
Seed script — Food Aggregator test data for BusinessID 15665.

Run from Backend/:
    python scripts/seeds/seed_aggregator.py

Wipes all OFNAggregator* rows for BusinessID 15665 then inserts fresh data.
"""
import os, sys, random
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BID = 15665

engine = create_engine(
    f"mssql+pymssql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_SERVER')}/{os.getenv('DB_NAME')}",
    echo=False, pool_pre_ping=True,
)
Session = sessionmaker(bind=engine)
db = Session()

def d(offset_days=0):
    return (date.today() + timedelta(days=offset_days)).isoformat()

def rand_date(start_offset, end_offset):
    delta = random.randint(start_offset, end_offset)
    return (date.today() + timedelta(days=delta)).isoformat()

# ── Wipe existing data (child tables first) ──────────────────────────────────
print("Wiping existing aggregator data for BusinessID", BID)
for t in [
    "OFNAggregatorLogistics",
    "OFNAggregatorD2COrder",
    "OFNAggregatorB2BOrder",
    "OFNAggregatorB2BAccount",
    "OFNAggregatorInventory",
    "OFNAggregatorPurchase",
    "OFNAggregatorInput",
    "OFNAggregatorContract",
    "OFNAggregatorFarm",
]:
    db.execute(text(f"DELETE FROM {t} WHERE BusinessID = {BID}"))
db.commit()
print("  done.")

# ── Farms ─────────────────────────────────────────────────────────────────────
farms_data = [
    ("Sunridge Blueberry Farm",   "Maria Gonzalez",  "+1-559-401-2233", "maria@sunridgefarm.com",   "14 Orchard Rd",         "Fresno",       "California",     "USA",    8.4,  "blueberry",             "organic",      "active",  d(-400)),
    ("Valley Crest Strawberries", "Tom Nakamura",    "+1-559-307-8812", "tom@valleycrest.com",      "88 Berry Lane",         "Visalia",      "California",     "USA",    5.1,  "strawberry",            "residue-free", "active",  d(-320)),
    ("Blue Ridge Produce",        "Aisha Patel",     "+1-661-210-4455", "aisha@blueridge.com",      "22 Highland Ave",       "Bakersfield",  "California",     "USA",    12.0, "blueberry, raspberry",  "GAP",          "active",  d(-280)),
    ("Maple Creek Orchards",      "James Okonkwo",   "+1-530-882-6600", "james@maplecreek.com",     "7 Maple Dr",            "Chico",        "California",     "USA",    9.8,  "peach, plum",           "organic",      "active",  d(-250)),
    ("Desert Sun Citrus",         "Fatima Al-Rashid","+1-760-334-9900", "fatima@desertsun.com",     "305 Citrus Way",        "Indio",        "California",     "USA",    15.3, "lemon, orange, lime",   "none",         "active",  d(-210)),
    ("Hillside Berry Co",         "Carlos Mendes",   "+1-707-559-1122", "carlos@hillsideberry.com", "99 Hillside Blvd",      "Ukiah",        "California",     "USA",    6.2,  "blackberry, blueberry", "organic",      "active",  d(-190)),
    ("Green Valley Greens",       "Sarah Kim",       "+1-831-445-7700", "sarah@greenvalley.com",    "40 Valley Rd",          "Salinas",      "California",     "USA",    20.0, "spinach, kale, lettuce","residue-free", "active",  d(-170)),
    ("Pacific Herb Gardens",      "David Wong",      "+1-831-680-2244", "david@pacificherb.com",    "12 Garden St",          "Watsonville",  "California",     "USA",    3.5,  "basil, cilantro, mint", "organic",      "active",  d(-150)),
    ("Sunrise Avocado Ranch",     "Elena Vasquez",   "+1-805-237-8833", "elena@sunriseavocado.com", "670 Ranch Rd",          "Temecula",     "California",     "USA",    18.0, "avocado",               "none",         "paused",  d(-130)),
    ("High Plains Wheat",         "Robert Burke",    "+1-806-445-1100", "robert@highplains.com",    "1 Wheat Way",           "Amarillo",     "Texas",          "USA",    95.0, "wheat, oat",            "none",         "active",  d(-120)),
    ("Rio Grande Peppers",        "Lucia Flores",    "+1-956-337-2288", "lucia@riogrande.com",      "88 Pepper Rd",          "McAllen",      "Texas",          "USA",    7.0,  "jalapeño, bell pepper", "GAP",          "active",  d(-100)),
    ("Thunder Basin Grains",      "Mike Pearson",    "+1-307-620-5544", "mike@thunderbasin.com",    "200 Basin Dr",          "Casper",       "Wyoming",        "USA",    80.0, "barley, oat, rye",      "none",         "churned", d(-360)),
    ("Northwest Cherry Co",       "Amy Tanaka",      "+1-509-448-9900", "amy@nwcherry.com",         "15 Cherry Blossom Ln",  "Wenatchee",    "Washington",     "USA",    11.0, "cherry",                "residue-free", "active",  d(-90)),
    ("Bayou Fresh Farms",         "Jerome Thibodaux","+1-225-556-3311", "jerome@bayoufresh.com",    "44 Bayou Lane",         "Baton Rouge",  "Louisiana",      "USA",    4.5,  "okra, sweet potato",    "none",         "active",  d(-80)),
    ("Cascade Berry Works",       "Olivia Fraser",   "+1-503-227-7766", "olivia@cascadeberry.com",  "33 Cascade Ave",        "Salem",        "Oregon",         "USA",    8.8,  "strawberry, blueberry", "organic",      "active",  d(-70)),
]

print(f"Inserting {len(farms_data)} farms…")
farm_ids = []
for row in farms_data:
    (name, contact, phone, email, addr, city, region, country,
     ha, crops, cert, status, joined) = row
    res = db.execute(text("""
        INSERT INTO OFNAggregatorFarm
            (BusinessID, FarmName, ContactName, ContactPhone, ContactEmail,
             AddressLine, City, Region, Country,
             HectaresUnder, PrimaryCrops, Certification, Status, JoinedDate)
        OUTPUT INSERTED.FarmID
        VALUES (:bid,:name,:contact,:phone,:email,:addr,:city,:region,:country,
                :ha,:crops,:cert,:status,:joined)
    """), dict(bid=BID, name=name, contact=contact, phone=phone, email=email,
               addr=addr, city=city, region=region, country=country,
               ha=ha, crops=crops, cert=cert, status=status, joined=joined))
    farm_ids.append(res.fetchone()[0])
db.commit()
print(f"  farms: {farm_ids}")

# ── Contracts ─────────────────────────────────────────────────────────────────
contracts_data = [
    # (farm_idx, crop, type, pricing, price/kg, est_kg, start, end, residue, status)
    (0,  "blueberry",   "first_right", "fixed",           3.80, 12000, d(-365), d(0),   "residue-free", "completed"),
    (0,  "blueberry",   "first_right", "floor_with_share",4.10, 14000, d(1),    d(365), "residue-free", "active"),
    (1,  "strawberry",  "obligation",  "fixed",           2.90, 8000,  d(-300), d(65),  "EU MRL",       "active"),
    (2,  "blueberry",   "first_right", "market_minus",    3.60, 18000, d(-250), d(115), "residue-free", "active"),
    (2,  "raspberry",   "spot",        "fixed",           5.50, 3000,  d(-180), d(-1),  "none",         "completed"),
    (3,  "peach",       "obligation",  "fixed",           1.80, 20000, d(-240), d(125), "GAP",          "active"),
    (3,  "plum",        "first_right", "fixed",           2.20, 9000,  d(-240), d(125), "GAP",          "active"),
    (4,  "lemon",       "obligation",  "fixed",           1.20, 35000, d(-200), d(165), "none",         "active"),
    (4,  "orange",      "first_right", "floor_with_share",1.05, 40000, d(-200), d(165), "none",         "active"),
    (5,  "blackberry",  "first_right", "fixed",           6.20, 5000,  d(-180), d(185), "organic",      "active"),
    (5,  "blueberry",   "obligation",  "fixed",           4.30, 7000,  d(-180), d(185), "organic",      "active"),
    (6,  "spinach",     "obligation",  "fixed",           1.80, 50000, d(-160), d(205), "residue-free", "active"),
    (6,  "kale",        "first_right", "market_minus",    2.10, 30000, d(-160), d(205), "residue-free", "active"),
    (7,  "basil",       "spot",        "fixed",           8.50, 1500,  d(-140), d(-10), "organic",      "completed"),
    (9,  "wheat",       "obligation",  "fixed",           0.28, 500000,d(-110), d(255), "none",         "active"),
    (10, "jalapeño",    "first_right", "fixed",           1.60, 15000, d(-90),  d(275), "GAP",          "active"),
    (12, "cherry",      "obligation",  "fixed",           5.80, 22000, d(-80),  d(285), "residue-free", "active"),
    (13, "okra",        "spot",        "fixed",           2.40, 4000,  d(-70),  d(295), "none",         "active"),
    (14, "strawberry",  "first_right", "floor_with_share",3.10, 9500,  d(-60),  d(305), "organic",      "active"),
    (14, "blueberry",   "obligation",  "fixed",           4.00, 6000,  d(-60),  d(305), "organic",      "active"),
]

print(f"Inserting {len(contracts_data)} contracts…")
contract_ids = []
for row in contracts_data:
    fi, crop, ctype, pricing, ppkg, estkg, start, end, residue, status = row
    fid = farm_ids[fi]
    res = db.execute(text("""
        INSERT INTO OFNAggregatorContract
            (BusinessID, FarmID, CropType, ContractType, PricingModel,
             PricePerKg, EstimatedKgPerSeason, StartDate, EndDate,
             ResidueRequirement, Status)
        OUTPUT INSERTED.ContractID
        VALUES (:bid,:fid,:crop,:ctype,:pricing,:ppkg,:estkg,:start,:end,:residue,:status)
    """), dict(bid=BID, fid=fid, crop=crop, ctype=ctype, pricing=pricing,
               ppkg=ppkg, estkg=estkg, start=start, end=end,
               residue=residue, status=status))
    contract_ids.append(res.fetchone()[0])
db.commit()
print(f"  contracts: {len(contract_ids)}")

# ── Inputs ────────────────────────────────────────────────────────────────────
inputs_data = [
    (0, "sapling",    "Premium Southern Highbush blueberry saplings, 2yr rootstock", 2000, "units", 1.80, "deduct_from_payout", d(-390)),
    (0, "tunnel",     "Low-tunnel kit — galvanised frame + 200-micron UV poly film",  8,    "units", 480,  "deduct_from_payout", d(-385)),
    (1, "sapling",    "Albion strawberry plugs, certified virus-free",                 5000, "units", 0.45, "deduct_from_payout", d(-310)),
    (1, "fertilizer", "Calcium nitrate slow-release granules (25 kg bag)",            40,   "kg",    2.20, "grant",              d(-295)),
    (2, "sapling",    "Duke blueberry — 3yr container plants",                         1500, "units", 2.10, "deduct_from_payout", d(-260)),
    (2, "tunnel",     "High-tunnel aluminium frame kit, 9m × 50m span",               3,    "units", 2800, "loan",               d(-255)),
    (3, "equipment",  "40hp tractor with front loader attachment",                     1,    "units", 18500,"loan",               d(-245)),
    (3, "training",   "Integrated pest management workshop — 2-day on-farm",           1,    "sessions",1200,"grant",             d(-230)),
    (4, "fertilizer", "Potassium sulphate (50 kg bag)",                                80,   "kg",    3.10, "deduct_from_payout", d(-195)),
    (5, "sapling",    "Chester thornless blackberry cuttings, 1yr bare-root",          800,  "units", 1.65, "deduct_from_payout", d(-175)),
    (6, "equipment",  "Seedling transplanter, 2-row, tractor-mount",                  1,    "units", 6400, "loan",               d(-155)),
    (6, "fertilizer", "Fish emulsion concentrate, 20L drum",                           10,   "units", 68,   "grant",              d(-145)),
    (7, "sapling",    "Genovese basil plugs, 128-cell trays",                          200,  "units", 3.20, "deduct_from_payout", d(-135)),
    (9, "equipment",  "Grain auger, 10m, electric motor",                              1,    "units", 3200, "loan",               d(-105)),
    (10,"pesticide",  "Capsaicin-based organic insect repellent concentrate, 5L",       6,    "units", 85,   "grant",              d(-85)),
    (12,"tunnel",     "Bird-exclusion netting kit — 8m × 25m panels × 12",            12,   "units", 320,  "deduct_from_payout", d(-75)),
    (14,"sapling",    "Seascape strawberry plug trays",                                3000, "units", 0.42, "deduct_from_payout", d(-55)),
    (14,"fertilizer", "Organic worm castings (20L bag)",                               20,   "units", 24,   "grant",              d(-50)),
]

print(f"Inserting {len(inputs_data)} inputs…")
for row in inputs_data:
    fi, itype, desc, qty, unit, ucost, recovery, provided = row
    fid = farm_ids[fi]
    db.execute(text("""
        INSERT INTO OFNAggregatorInput
            (BusinessID, FarmID, InputType, Description, Quantity, Unit,
             UnitCost, TotalCost, ProvidedDate, RecoveryModel)
        VALUES (:bid,:fid,:itype,:desc,:qty,:unit,:ucost,:total,:provided,:recovery)
    """), dict(bid=BID, fid=fid, itype=itype, desc=desc, qty=qty, unit=unit,
               ucost=ucost, total=round(qty * ucost, 2),
               provided=provided, recovery=recovery))
db.commit()
print("  done.")

# ── Purchases ─────────────────────────────────────────────────────────────────
purchases_data = [
    # (farm_idx, contract_idx, crop, grade, kg, ppkg, residue_status, harvest, received, payment)
    (0,  0,  "blueberry",   "premium",    4200, 3.80, "passed", d(-60),  d(-58),  "paid"),
    (0,  0,  "blueberry",   "premium",    3800, 3.80, "passed", d(-30),  d(-28),  "paid"),
    (0,  0,  "blueberry",   "standard",   1100, 3.40, "passed", d(-30),  d(-28),  "paid"),
    (1,  2,  "strawberry",  "premium",    2900, 2.90, "passed", d(-50),  d(-48),  "paid"),
    (1,  2,  "strawberry",  "standard",   800,  2.50, "passed", d(-50),  d(-48),  "partial"),
    (2,  3,  "blueberry",   "premium",    6000, 3.60, "passed", d(-45),  d(-43),  "paid"),
    (2,  4,  "raspberry",   "premium",    950,  5.50, "passed", d(-90),  d(-88),  "paid"),
    (3,  5,  "peach",       "premium",    8500, 1.80, "passed", d(-40),  d(-38),  "paid"),
    (3,  6,  "plum",        "premium",    3200, 2.20, "passed", d(-35),  d(-33),  "partial"),
    (4,  7,  "lemon",       "standard",   12000,1.20, "passed", d(-55),  d(-53),  "paid"),
    (4,  8,  "orange",      "premium",    15000,1.05, "passed", d(-55),  d(-53),  "paid"),
    (5,  9,  "blackberry",  "premium",    1800, 6.20, "passed", d(-25),  d(-23),  "unpaid"),
    (6,  11, "spinach",     "premium",    18000,1.80, "passed", d(-20),  d(-18),  "partial"),
    (6,  12, "kale",        "premium",    9000, 2.10, "passed", d(-20),  d(-18),  "unpaid"),
    (9,  14, "wheat",       "standard",   200000,0.28,"passed", d(-15),  d(-13),  "unpaid"),
    (10, 15, "jalapeño",    "premium",    4500, 1.60, "passed", d(-10),  d(-8),   "unpaid"),
    (12, 16, "cherry",      "premium",    7000, 5.80, "passed", d(-8),   d(-6),   "unpaid"),
    (14, 18, "strawberry",  "premium",    3200, 3.10, "passed", d(-5),   d(-3),   "unpaid"),
    (0,  1,  "blueberry",   "processing", 600,  2.80, "failed", d(-15),  d(-13),  "unpaid"),
]

print(f"Inserting {len(purchases_data)} purchases…")
purchase_ids = []
for row in purchases_data:
    fi, ci, crop, grade, kg, ppkg, residue, harvest, received, payment = row
    fid = farm_ids[fi]
    cid = contract_ids[ci] if ci is not None else None
    res = db.execute(text("""
        INSERT INTO OFNAggregatorPurchase
            (BusinessID, FarmID, ContractID, CropType, Grade,
             QuantityKg, PricePerKg, TotalPaid,
             ResidueTestStatus, HarvestDate, ReceivedDate, PaymentStatus)
        OUTPUT INSERTED.PurchaseID
        VALUES (:bid,:fid,:cid,:crop,:grade,:kg,:ppkg,:total,:residue,:harvest,:received,:payment)
    """), dict(bid=BID, fid=fid, cid=cid, crop=crop, grade=grade,
               kg=kg, ppkg=ppkg, total=round(kg * ppkg, 2),
               residue=residue, harvest=harvest, received=received, payment=payment))
    purchase_ids.append(res.fetchone()[0])
db.commit()
print(f"  purchases: {len(purchase_ids)}")

# ── Inventory ─────────────────────────────────────────────────────────────────
inventory_data = [
    # (purchase_idx, crop, current_kg, unit, target_c, current_c, qc, expiry)
    (5,  "blueberry",   3200,  "Cold-Bay-A1",  2.0,  2.3,  "ok",         d(12)),
    (7,  "peach",       5000,  "Cold-Bay-A2",  1.0,  1.1,  "ok",         d(8)),
    (8,  "plum",        2100,  "Cold-Bay-A3",  0.5,  0.6,  "ok",         d(15)),
    (9,  "lemon",       8000,  "Cold-Bay-B1",  8.0,  8.4,  "ok",         d(30)),
    (10, "orange",      10000, "Cold-Bay-B2",  6.0,  6.2,  "ok",         d(25)),
    (11, "blackberry",  1200,  "Cold-Bay-A4",  1.5,  1.5,  "ok",         d(5)),
    (12, "spinach",     9000,  "Cold-Bay-C1",  1.0,  1.8,  "hold",       d(4)),
    (13, "kale",        7500,  "Cold-Bay-C2",  1.0,  1.1,  "ok",         d(7)),
    (14, "wheat",       80000, "Silo-1",       15.0, 14.8, "ok",         d(180)),
    (15, "jalapeño",    3800,  "Cold-Bay-D1",  7.0,  7.2,  "ok",         d(20)),
    (16, "cherry",      5500,  "Cold-Bay-A5",  0.5,  0.5,  "ok",         d(6)),
    (17, "strawberry",  2800,  "Cold-Bay-A6",  1.0,  1.4,  "ok",         d(3)),
    (18, "blueberry",   600,   "Cold-Bay-A7",  2.0,  5.8,  "quarantine", d(2)),
]

print(f"Inserting {len(inventory_data)} inventory items…")
for row in inventory_data:
    pi, crop, cur_kg, unit, target_c, current_c, qc, expiry = row
    pid = purchase_ids[pi]
    db.execute(text("""
        INSERT INTO OFNAggregatorInventory
            (BusinessID, PurchaseID, CropType, CurrentKg,
             ColdStorageUnit, TargetTempC, CurrentTempC, QCStatus, ExpiryDate)
        VALUES (:bid,:pid,:crop,:cur_kg,:unit,:target,:current,:qc,:expiry)
    """), dict(bid=BID, pid=pid, crop=crop, cur_kg=cur_kg, unit=unit,
               target=target_c, current=current_c, qc=qc, expiry=expiry))
db.commit()
print("  done.")

# ── B2B Accounts ──────────────────────────────────────────────────────────────
b2b_data = [
    ("FreshMart Supermarkets",    "retail",       "Paul Steiner",    "+1-213-400-1100", "paul@freshmart.com",      "100 Retail Blvd, Los Angeles, CA", 30, 250000, "active"),
    ("Harvest Table Restaurants", "restaurant",   "Nina Cho",        "+1-415-558-2200", "nina@harvesttable.com",   "55 Dining Row, San Francisco, CA", 14, 80000,  "active"),
    ("GreenLeaf Distributors",    "distributor",  "Omar Khalil",     "+1-714-220-9900", "omar@greenleaf.com",      "200 Warehouse Dr, Anaheim, CA",    45, 500000, "active"),
    ("CityFood Co-op",            "institution",  "Rachel Burns",    "+1-503-667-3300", "rachel@cityfood.com",     "12 Co-op St, Portland, OR",        30, 120000, "active"),
    ("Sunnyside Grocery Chain",   "retail",       "Marco Di Luca",   "+1-702-339-8800", "marco@sunnyside.com",     "77 Strip Ave, Las Vegas, NV",      30, 190000, "active"),
    ("Blue Apron Wholesale",      "distributor",  "Tina Park",       "+1-646-200-5500", "tina@blueapronw.com",     "18 Fulton St, New York, NY",       30, 350000, "on_hold"),
    ("Canyon Creek Bistro Group", "restaurant",   "Luis Herrera",    "+1-602-447-7700", "luis@canyoncreek.com",    "40 Camelback Rd, Phoenix, AZ",     21, 45000,  "active"),
    ("Pacific Rim Foods",         "distributor",  "Helen Yamamoto",  "+1-206-781-4400", "helen@pacificrim.com",    "900 Harbor Ave, Seattle, WA",      45, 420000, "active"),
]

print(f"Inserting {len(b2b_data)} B2B accounts…")
b2b_ids = []
for row in b2b_data:
    name, btype, contact, phone, email, addr, terms, credit, status = row
    res = db.execute(text("""
        INSERT INTO OFNAggregatorB2BAccount
            (BusinessID, BuyerName, BuyerType, ContactName, ContactPhone,
             ContactEmail, DeliveryAddress, NetTermsDays, CreditLimit, Status)
        OUTPUT INSERTED.AccountID
        VALUES (:bid,:name,:btype,:contact,:phone,:email,:addr,:terms,:credit,:status)
    """), dict(bid=BID, name=name, btype=btype, contact=contact, phone=phone,
               email=email, addr=addr, terms=terms, credit=credit, status=status))
    b2b_ids.append(res.fetchone()[0])
db.commit()
print(f"  accounts: {b2b_ids}")

# ── B2B Orders ────────────────────────────────────────────────────────────────
b2b_orders_data = [
    (0, "blueberry",   1200, 4.80, d(-28), "dispatched", f"INV-{BID}-001", "paid"),
    (0, "strawberry",  800,  3.20, d(-21), "delivered",  f"INV-{BID}-002", "paid"),
    (1, "blueberry",   300,  5.20, d(-14), "delivered",  f"INV-{BID}-003", "paid"),
    (1, "raspberry",   150,  7.50, d(-14), "delivered",  f"INV-{BID}-004", "paid"),
    (2, "lemon",       5000, 1.50, d(-20), "delivered",  f"INV-{BID}-005", "partial"),
    (2, "orange",      6000, 1.30, d(-20), "delivered",  f"INV-{BID}-006", "unpaid"),
    (3, "spinach",     4000, 2.20, d(-10), "dispatched", f"INV-{BID}-007", "unpaid"),
    (3, "kale",        2500, 2.60, d(-10), "dispatched", f"INV-{BID}-008", "unpaid"),
    (4, "blueberry",   900,  4.60, d(-7),  "placed",     f"INV-{BID}-009", "unpaid"),
    (4, "cherry",      1500, 7.20, d(-5),  "picking",    f"INV-{BID}-010", "unpaid"),
    (5, "wheat",       50000,0.35, d(-30), "delivered",  f"INV-{BID}-011", "unpaid"),
    (6, "jalapeño",    1800, 2.10, d(-3),  "placed",     f"INV-{BID}-012", "unpaid"),
    (7, "blueberry",   2000, 4.70, d(2),   "placed",     f"INV-{BID}-013", "unpaid"),
    (7, "strawberry",  1200, 3.40, d(2),   "placed",     f"INV-{BID}-014", "unpaid"),
    (0, "peach",       3000, 2.20, d(-15), "delivered",  f"INV-{BID}-015", "paid"),
    (2, "kale",        1800, 2.50, d(-8),  "delivered",  f"INV-{BID}-016", "paid"),
]

print(f"Inserting {len(b2b_orders_data)} B2B orders…")
b2b_order_ids = []
for row in b2b_orders_data:
    ai, crop, kg, ppkg, delivery, status, inv, payment = row
    aid = b2b_ids[ai]
    res = db.execute(text("""
        INSERT INTO OFNAggregatorB2BOrder
            (BusinessID, AccountID, CropType, QuantityKg, PricePerKg,
             TotalValue, DeliveryDate, Status, InvoiceNumber, PaymentStatus)
        OUTPUT INSERTED.OrderID
        VALUES (:bid,:aid,:crop,:kg,:ppkg,:total,:delivery,:status,:inv,:payment)
    """), dict(bid=BID, aid=aid, crop=crop, kg=kg, ppkg=ppkg,
               total=round(kg * ppkg, 2), delivery=delivery,
               status=status, inv=inv, payment=payment))
    b2b_order_ids.append(res.fetchone()[0])
db.commit()
print(f"  orders: {len(b2b_order_ids)}")

# ── D2C Orders ────────────────────────────────────────────────────────────────
d2c_data = [
    ("own_app",  "D2C-10041", "Sophie Martin",    "+1-415-100-0001", "22 Oak St, SF CA",      "blueberry",   1.0,  12.99,  d(-3),  45,  "delivered"),
    ("zepto",    "ZPT-88811", "Raj Patel",         "+1-415-100-0002", "5 Main St, SF CA",      "strawberry",  0.5,  7.49,   d(-2),  30,  "delivered"),
    ("swiggy",   "SWG-55321", "Priya Nair",        "+1-415-100-0003", "80 Park Ave, SF CA",    "raspberry",   0.5,  9.99,   d(-2),  30,  "delivered"),
    ("own_app",  "D2C-10042", "Carlos Rivera",     "+1-310-200-0004", "14 Elm Dr, LA CA",      "blueberry",   2.0,  23.99,  d(-1),  45,  "out_for_delivery"),
    ("own_app",  "D2C-10043", "Lisa Chang",        "+1-310-200-0005", "99 Sunset Blvd, LA CA", "cherry",      1.0,  14.99,  d(-1),  45,  "out_for_delivery"),
    ("blinkit",  "BLK-22201", "Arjun Singh",       "+1-650-300-0006", "7 Tech Way, Palo Alto", "spinach",     0.3,  4.49,   d(0),   20,  "picking"),
    ("zepto",    "ZPT-88812", "Maya Patel",        "+1-650-300-0007", "33 University Ave, PA", "kale",        0.4,  5.99,   d(0),   30,  "picking"),
    ("own_app",  "D2C-10044", "Tom Bradley",       "+1-213-400-0008", "202 Venice Blvd, LA",   "avocado",     1.5,  18.49,  d(0),   60,  "placed"),
    ("swiggy",   "SWG-55322", "Anika Sharma",      "+1-408-500-0009", "45 Willow Ln, SJ CA",   "blueberry",   0.5,  8.99,   d(0),   30,  "placed"),
    ("own_app",  "D2C-10045", "James Wilson",      "+1-619-600-0010", "10 Harbor Dr, SD CA",   "strawberry",  1.0,  10.99,  d(0),   45,  "placed"),
    ("amazon",   "AMZ-99001", "Sandra Hill",       "+1-503-700-0011", "88 Pine St, Portland",  "blueberry",   2.0,  22.00,  d(1),   None,"placed"),
    ("amazon",   "AMZ-99002", "Kevin Moore",       "+1-206-800-0012", "34 Rainier Ave, SEA",   "cherry",      1.0,  16.00,  d(1),   None,"placed"),
    ("own_app",  "D2C-10046", "Grace Lee",         "+1-415-100-0013", "17 Castro St, SF CA",   "raspberry",   0.75, 11.49,  d(1),   45,  "placed"),
    ("zepto",    "ZPT-88813", "Rohan Mehta",       "+1-415-100-0014", "52 Haight St, SF CA",   "lemon",       1.0,  4.99,   d(0),   30,  "delivered"),
    ("own_app",  "D2C-10047", "Isabella Torres",   "+1-310-200-0015", "200 Rodeo Dr, BH CA",   "basil",       0.2,  5.99,   d(-1),  45,  "delivered"),
    ("blinkit",  "BLK-22202", "Daniel Kim",        "+1-650-300-0016", "9 Stanford Ave, PA",    "spinach",     0.5,  6.49,   d(-3),  20,  "delivered"),
    ("own_app",  "D2C-10048", "Natalie Brooks",    "+1-213-400-0017", "7 Grand Ave, LA CA",    "blueberry",   3.0,  33.99,  d(-4),  45,  "delivered"),
    ("swiggy",   "SWG-55323", "Vikram Joshi",      "+1-408-500-0018", "14 Alum Rock, SJ CA",   "jalapeño",    0.3,  3.99,   d(-5),  30,  "delivered"),
]

print(f"Inserting {len(d2c_data)} D2C orders…")
d2c_order_ids = []
for row in d2c_data:
    channel, ext_id, cname, cphone, addr, crop, kg, total, orderdate, sla, status = row
    res = db.execute(text("""
        INSERT INTO OFNAggregatorD2COrder
            (BusinessID, Channel, ExternalOrderID, CustomerName, CustomerPhone,
             DeliveryAddress, CropType, QuantityKg, TotalValue, OrderDate,
             DeliverySLAMinutes, Status)
        OUTPUT INSERTED.OrderID
        VALUES (:bid,:channel,:ext,:cname,:cphone,:addr,:crop,:kg,:total,:orderdate,:sla,:status)
    """), dict(bid=BID, channel=channel, ext=ext_id, cname=cname, cphone=cphone,
               addr=addr, crop=crop, kg=kg, total=total, orderdate=orderdate,
               sla=sla, status=status))
    d2c_order_ids.append(res.fetchone()[0])
db.commit()
print(f"  D2C orders: {len(d2c_order_ids)}")

# ── Logistics ─────────────────────────────────────────────────────────────────
vehicles = ["VAN-CA-101", "VAN-CA-102", "TRK-CA-201", "TRK-CA-202", "VAN-OR-103"]
drivers  = [
    ("Marcus Webb",   "+1-559-901-1111"),
    ("Claudia Reyes", "+1-559-901-2222"),
    ("Anthony Brown", "+1-661-901-3333"),
    ("Yuki Tanaka",   "+1-530-901-4444"),
    ("Ibrahim Hassan","+1-760-901-5555"),
]

def mk_logistics(otype, oid, vehicle_i, driver_i, pickup_offset, delivery_offset,
                 temp_c, breach, status):
    v = vehicles[vehicle_i % len(vehicles)]
    dn, dp = drivers[driver_i % len(drivers)]
    pickup   = (date.today() + timedelta(days=pickup_offset)).isoformat() + " 06:00:00"
    delivery = (date.today() + timedelta(days=delivery_offset)).isoformat() + " 14:00:00"
    db.execute(text("""
        INSERT INTO OFNAggregatorLogistics
            (BusinessID, OrderType, OrderID, VehicleID, DriverName, DriverPhone,
             PickupTime, DeliveryTime, ColdChainTempC, ColdChainBreach,
             RouteNotes, Status)
        VALUES (:bid,:otype,:oid,:v,:dn,:dp,:pickup,:delivery,:temp,:breach,:notes,:status)
    """), dict(bid=BID, otype=otype, oid=oid, v=v, dn=dn, dp=dp,
               pickup=pickup, delivery=delivery, temp=temp_c, breach=1 if breach else 0,
               notes="Auto-generated test route", status=status))

print("Inserting logistics records…")
# Inbound (purchase deliveries to cold store)
for i, pid in enumerate(purchase_ids[:10]):
    breach = (i == 12)   # one breach for the quarantine item
    mk_logistics("inbound", pid, i, i, -purchase_ids.index(pid)-60, -purchase_ids.index(pid)-59,
                 2.5 + random.uniform(0, 1), breach,
                 "delivered" if purchase_ids.index(pid) > 3 else "delivered")

# Outbound B2B
for i, oid in enumerate(b2b_order_ids[:10]):
    mk_logistics("b2b", oid, i, i+1, -3+i, -2+i,
                 3.0 + random.uniform(0, 0.8), False,
                 "delivered" if i < 7 else ("dispatched" if i < 9 else "scheduled"))

# Outbound D2C
for i, oid in enumerate(d2c_order_ids[:8]):
    mk_logistics("d2c", oid, i, i+2, 0, 0,
                 4.0 + random.uniform(0, 0.5), False,
                 "delivered" if i < 5 else "in_transit")

db.commit()
print("  done.")

print()
print("Seed complete for BusinessID", BID)
print(f"  {len(farm_ids)} farms, {len(contract_ids)} contracts, {len(inputs_data)} inputs")
print(f"  {len(purchase_ids)} purchases, {len(inventory_data)} inventory items")
print(f"  {len(b2b_ids)} B2B accounts, {len(b2b_order_ids)} B2B orders")
print(f"  {len(d2c_order_ids)} D2C orders, logistics for inbound+outbound")
db.close()
