"""
seed_demo_15671c.py — Demo seed continuation for BusinessID=15671 (Food World)
Covers: Accounting, Animals, Produce, FoodWantedAds, AppNotifications

Idempotent: checks for existing data before inserting.
Run: python seed_demo_15671c.py
"""
import sys, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import get_db
from sqlalchemy import text

BID = 15671
PEOPLE_ID = 5705  # Owner of BusinessID=15671 (from BusinessAccess)

db = next(get_db())

def q(sql, params=None):
    db.execute(text(sql), params or {})

def first(sql, params=None):
    return db.execute(text(sql), params or {}).scalar()

def section(name):
    print(f"\n=== {name} ===")

# ─────────────────────────────────────────────
# 1. ACCOUNTING
# ─────────────────────────────────────────────
section("Accounting — FiscalYear + FiscalPeriods")

fy_id = first("SELECT FiscalYearID FROM FiscalYears WHERE BusinessID=:b AND YearName='FY2026'", {"b": BID})
if not fy_id:
    fy_id = first(
        "INSERT INTO FiscalYears (BusinessID, YearName, StartDate, EndDate, IsClosed) "
        "OUTPUT INSERTED.FiscalYearID "
        "VALUES (:b, 'FY2026', '2026-01-01', '2026-12-31', 0)",
        {"b": BID}
    )
    print(f"  Created FiscalYear FY2026 (ID={fy_id})")
else:
    print(f"  FiscalYear FY2026 already exists (ID={fy_id})")

month_names = [
    "Jan 2026","Feb 2026","Mar 2026","Apr 2026","May 2026","Jun 2026",
    "Jul 2026","Aug 2026","Sep 2026","Oct 2026","Nov 2026","Dec 2026",
]
month_ranges = [
    ("2026-01-01","2026-01-31"),("2026-02-01","2026-02-28"),("2026-03-01","2026-03-31"),
    ("2026-04-01","2026-04-30"),("2026-05-01","2026-05-31"),("2026-06-01","2026-06-30"),
    ("2026-07-01","2026-07-31"),("2026-08-01","2026-08-31"),("2026-09-01","2026-09-30"),
    ("2026-10-01","2026-10-31"),("2026-11-01","2026-11-30"),("2026-12-01","2026-12-31"),
]
period_ids = []
for i, (name, (s, e)) in enumerate(zip(month_names, month_ranges), 1):
    pid = first("SELECT FiscalPeriodID FROM FiscalPeriods WHERE BusinessID=:b AND PeriodName=:n", {"b": BID, "n": name})
    if not pid:
        pid = first(
            "INSERT INTO FiscalPeriods (FiscalYearID, BusinessID, PeriodNumber, PeriodName, StartDate, EndDate, IsClosed) "
            "OUTPUT INSERTED.FiscalPeriodID "
            "VALUES (:fy, :b, :num, :n, :s, :e, 0)",
            {"fy": fy_id, "b": BID, "num": i, "n": name, "s": s, "e": e}
        )
        print(f"  Created period {name} (ID={pid})")
    else:
        print(f"  Period {name} exists (ID={pid})")
    period_ids.append(pid)

db.commit()

section("Accounting — Chart of Accounts")

# AccountTypeID: 1=Asset 2=Liability 3=Equity 4=Revenue 5=COGS 6=Expense 7=OtherIncome 8=OtherExpense
accounts_data = [
    # (AccountNumber, AccountName, AccountTypeID)
    ("1000", "Checking Account",          1),
    ("1010", "Savings Account",           1),
    ("1100", "Accounts Receivable",       1),
    ("1200", "Inventory — Produce",       1),
    ("1210", "Inventory — Livestock",     1),
    ("1500", "Equipment",                 1),
    ("1510", "Accumulated Depreciation",  2),
    ("2000", "Accounts Payable",          2),
    ("2100", "Accrued Expenses",          2),
    ("2200", "Short-Term Loan",           2),
    ("2500", "Long-Term Loan",            2),
    ("3000", "Owner Equity",              3),
    ("3100", "Retained Earnings",         3),
    ("4000", "Produce Sales",             4),
    ("4100", "Livestock Sales",           4),
    ("4200", "CSA Revenue",               4),
    ("4300", "Service Revenue",           4),
    ("4400", "Market Stand Revenue",      4),
    ("5000", "Cost of Produce Sold",      5),
    ("5100", "Cost of Livestock Sold",    5),
    ("6000", "Labor — Field",             6),
    ("6010", "Labor — Packing",           6),
    ("6100", "Feed & Supplies",           6),
    ("6200", "Fuel & Transportation",     6),
    ("6300", "Utilities",                 6),
    ("6400", "Insurance",                 6),
    ("6500", "Marketing",                 6),
    ("6600", "Depreciation Expense",      6),
]

acct_ids = {}
for num, name, atype in accounts_data:
    aid = first("SELECT AccountID FROM Accounts WHERE BusinessID=:b AND AccountNumber=:n", {"b": BID, "n": num})
    if not aid:
        aid = first(
            "INSERT INTO Accounts (BusinessID, AccountTypeID, AccountNumber, AccountName, IsActive, IsSystem) "
            "OUTPUT INSERTED.AccountID VALUES (:b, :at, :n, :nm, 1, 0)",
            {"b": BID, "at": atype, "n": num, "nm": name}
        )
        print(f"  Created account {num} {name}")
    acct_ids[num] = aid

db.commit()

section("Accounting — Journal Entries")

entries = [
    # (period_idx 0-based, date, desc, ref, lines: [(acct_num, debit, credit, desc)])
    (0, "2026-01-15", "CSA subscription payments received", "CSA-JAN",
        [("1000", 2400.00, 0, "Cash deposit"), ("4200", 0, 2400.00, "CSA revenue Jan")]),
    (1, "2026-02-01", "Seed and supply purchase", "PO-2026-001",
        [("6100", 1850.00, 0, "Seeds, fertilizer, supplies"), ("2000", 0, 1850.00, "AP — AgriSupply Co")]),
    (1, "2026-02-10", "AP payment — AgriSupply Co", "CHK-1001",
        [("2000", 1850.00, 0, "AP cleared"), ("1000", 0, 1850.00, "Checking payment")]),
    (2, "2026-03-20", "Farmers market produce sales", "MKT-MAR",
        [("1000", 3100.00, 0, "Cash from market stand"), ("4000", 0, 3100.00, "Produce sales March")]),
    (2, "2026-03-31", "March payroll — field labor", "PAY-MAR",
        [("6000", 4200.00, 0, "Field labor"), ("6010", 800.00, 0, "Packing labor"),
         ("1000", 0, 5000.00, "Payroll disbursement")]),
    (3, "2026-04-05", "Alpaca livestock sale", "LS-2026-001",
        [("1000", 5500.00, 0, "Alpaca sale proceeds"), ("4100", 0, 5500.00, "Livestock sales")]),
    (3, "2026-04-15", "Fuel and transportation", "EXP-APR-FUEL",
        [("6200", 620.00, 0, "Fuel — truck and tractor"), ("1000", 0, 620.00, "Checking payment")]),
    (4, "2026-05-01", "Restaurant produce order — Harvest Table", "INV-2026-045",
        [("1100", 1740.00, 0, "AR — Harvest Table Restaurant"), ("4000", 0, 1740.00, "Produce revenue")]),
    (4, "2026-05-15", "Insurance premium", "INS-2026-Q2",
        [("6400", 1200.00, 0, "Quarterly insurance"), ("1000", 0, 1200.00, "Checking payment")]),
    (5, "2026-06-30", "AR collection — Harvest Table", "PMT-HT-045",
        [("1000", 1740.00, 0, "Payment received"), ("1100", 0, 1740.00, "AR cleared")]),
]

for (pidx, edate, desc, ref, lines) in entries:
    exists = first(
        "SELECT JournalEntryID FROM JournalEntries WHERE BusinessID=:b AND Reference=:r",
        {"b": BID, "r": ref}
    )
    if exists:
        print(f"  Entry {ref} already exists")
        continue
    je_id = first(
        "INSERT INTO JournalEntries (BusinessID, FiscalPeriodID, EntryNumber, EntryDate, Description, "
        "Reference, SourceType, IsPosted, CreatedBy) OUTPUT INSERTED.JournalEntryID "
        "VALUES (:b, :fp, :en, :d, :desc, :ref, 'manual', 1, :cb)",
        {"b": BID, "fp": period_ids[pidx], "en": ref, "d": edate, "desc": desc, "ref": ref, "cb": PEOPLE_ID}
    )
    for order, (acct_num, debit, credit, ldesc) in enumerate(lines, 1):
        q(
            "INSERT INTO JournalEntryLines (JournalEntryID, BusinessID, AccountID, DebitAmount, CreditAmount, Description, LineOrder) "
            "VALUES (:je, :b, :acct, :da, :ca, :ld, :lo)",
            {"je": je_id, "b": BID, "acct": acct_ids[acct_num], "da": debit, "ca": credit, "ld": ldesc, "lo": order}
        )
    print(f"  Created journal entry {ref}")

db.commit()

# ─────────────────────────────────────────────
# 2. ANIMALS (Alpacas for BusinessID=15671)
# ─────────────────────────────────────────────
section("Animals — Alpacas")

# SpeciesID=2 (Alpacas), SpeciesCategoryID: 1=Maiden, 2=Dam, 4=Herdsire
alpacas = [
    ("Sundance Golden Glory",   "Sundance",  4,  "M", "Huacaya", "Golden Fawn",  "2020-03-15", 32000.00, "Champion bloodlines, 22-micron fleece, gentle temperament"),
    ("Meadowbrook Bella Luna",  "Bella",     2,  "F", "Huacaya", "White",        "2019-07-22", 18500.00, "Proven dam, 3 healthy crias, award-winning fiber"),
    ("Coppercrest Andean Dawn", "Dawn",      2,  "F", "Suri",    "Rose Grey",    "2021-01-10", 22000.00, "Silky Suri fleece, exceptional luster, first-cria dam"),
    ("Highpeak Rio Verde",      "Rio",       4,  "M", "Huacaya", "Medium Brown", "2018-09-05", 45000.00, "Herdsire, 28 offspring, EPD-tested, AOBA Top 10"),
    ("Willowbrook Zara",        "Zara",      1,  "F", "Huacaya", "Light Fawn",   "2023-04-18",  8500.00, "Young maiden, exceptional conformation, promising fleece"),
    ("Ferndale Cosmo",          "Cosmo",     4,  "M", "Suri",    "Bay Black",    "2019-11-30", 38000.00, "Suri herdsire, 5-digit EPDs, multiple champion sashes"),
    ("Oatmeal Hill Luna Star",  "Luna Star", 1,  "F", "Huacaya", "Silver Grey",  "2024-02-01",  6500.00, "2024 cria, exceptional genetics, maiden in training"),
    ("Prairie Song Delilah",    "Delilah",   2,  "F", "Huacaya", "Dark Brown",   "2020-06-14", 19500.00, "5-year dam, consistent 18-micron fleece, top producer"),
]

for (full_name, short_name, spec_cat_id, sex_label, breed, color, dob_str, price, desc) in alpacas:
    exists = first("SELECT AnimalID FROM animals WHERE BusinessID=:b AND FullName=:fn", {"b": BID, "fn": full_name})
    if exists:
        print(f"  {full_name} already exists")
        continue
    dob = datetime.datetime.strptime(dob_str, "%Y-%m-%d")
    sex_id = 1 if sex_label == "M" else 2
    q(
        "INSERT INTO animals (PeopleID, BusinessID, SpeciesID, SpeciesCategoryID, FullName, ShortName, "
        "Breed, Markings, DOBday, DOBMonth, DOBYear, PublishForSale, PublishStud, "
        "Description, Financeterms, SexID, ShowOnOurHerdPage) "
        "VALUES (:p, :b, 2, :sc, :fn, :sn, :br, :col, :dd, :dm, :dy, 1, :stud, :desc, :price, :sex, 1)",
        {
            "p": PEOPLE_ID, "b": BID, "sc": spec_cat_id,
            "fn": full_name, "sn": short_name,
            "br": breed, "col": color,
            "dd": dob.day, "dm": dob.month, "dy": dob.year,
            "stud": 1 if spec_cat_id == 4 else 0,
            "desc": desc, "price": f"${price:,.0f}",
            "sex": sex_id,
        }
    )
    print(f"  Added alpaca: {full_name}")

db.commit()

# ─────────────────────────────────────────────
# 3. PRODUCE
# ─────────────────────────────────────────────
section("Produce listings")

produce_items = [
    # (Notes/name, Quantity, Measurement, RetailPrice, WholesalePrice, HarvestDate, AvailDate, ExpDate, IsOrganic, IsLocal)
    ("Heirloom Tomatoes — Mixed Variety Pack (5 lb)",    240, "lb",   4.50, 2.80, "2026-04-28", "2026-05-01", "2026-05-10", 1, 1),
    ("Butterhead Lettuce — Head",                        180, "each", 3.25, 1.90, "2026-05-01", "2026-05-02", "2026-05-08", 1, 1),
    ("Rainbow Carrots — 2 lb Bunch",                     320, "lb",   3.75, 2.20, "2026-04-25", "2026-04-27", "2026-05-15", 1, 1),
    ("Sugar Snap Peas — 1 lb Bag",                       150, "lb",   5.00, 3.10, "2026-05-03", "2026-05-04", "2026-05-12", 1, 1),
    ("Zucchini — Green & Yellow Mixed (3 lb)",           200, "lb",   2.75, 1.60, "2026-05-02", "2026-05-03", "2026-05-14", 1, 1),
    ("Russet Potatoes — 10 lb Bag",                      500, "lb",   5.50, 3.25, "2026-04-20", "2026-04-22", "2026-06-01", 0, 1),
    ("Sweet Corn — Dozen Ears",                           96, "each", 6.00, 3.75, "2026-05-05", "2026-05-06", "2026-05-10", 0, 1),
    ("Watermelon — Seedless (avg 18 lb)",                 30, "each", 8.00, 5.00, "2026-05-04", "2026-05-05", "2026-05-20", 0, 1),
    ("Basil — Fresh Bunch",                              120, "bunch",2.50, 1.40, "2026-05-01", "2026-05-01", "2026-05-07", 1, 1),
    ("Garlic — Hardneck (1 lb Braid)",                    80, "lb",   7.50, 4.50, "2026-04-15", "2026-04-18", "2026-07-01", 1, 1),
    ("Kale — Curly, 1 lb Bunch",                         160, "bunch",3.00, 1.75, "2026-05-02", "2026-05-03", "2026-05-12", 1, 1),
    ("Bell Peppers — Red/Yellow/Orange Mix (3 ct)",      140, "each", 4.00, 2.50, "2026-05-03", "2026-05-04", "2026-05-15", 1, 1),
]

for (notes, qty, meas, retail, wholesale, harvest, avail, exp, organic, local) in produce_items:
    exists = first("SELECT ProduceID FROM Produce WHERE BusinessID=:b AND Notes=:n", {"b": BID, "n": notes})
    if exists:
        print(f"  Produce '{notes[:40]}' already exists")
        continue
    q(
        "INSERT INTO Produce (BusinessID, Quantity, QuantityMeasurement, RetailPrice, WholesalePrice, "
        "HarvestDate, AvailableDate, ExpirationDate, IsOrganic, IsLocal, Notes, ShowProduce) "
        "VALUES (:b, :qty, :meas, :rp, :wp, :hd, :ad, :ed, :org, :loc, :notes, 1)",
        {"b": BID, "qty": qty, "meas": meas, "rp": retail, "wp": wholesale,
         "hd": harvest, "ad": avail, "ed": exp, "org": organic, "loc": local, "notes": notes}
    )
    print(f"  Added produce: {notes[:50]}")

db.commit()

# ─────────────────────────────────────────────
# 4. FOOD WANTED ADS
# ─────────────────────────────────────────────
section("Food Wanted Ads")

wanted_ads = [
    ("Organic Salad Mix — Weekly Restaurant Supply",
     "Established farm-to-table restaurant seeking consistent weekly supply of mixed organic salad greens. "
     "Minimum 40 lb per week, must be harvested within 24 hours of delivery.",
     "Restaurant", "Delivery", "Denver", "CO", "2026-08-01",
     [("Mixed salad greens", 40, "lb", "Baby arugula, spinach, radicchio mix preferred"),
      ("Edible flowers", 2, "lb", "Nasturtiums, borage, violas")]),
    ("Grass-Fed Beef — Wholesale Buyer",
     "Butcher shop looking for consistent source of grass-fed, pasture-raised beef. "
     "Interested in whole and half carcasses. USDA inspected processing required.",
     "Retail", "Farm Pickup", "Fort Collins", "CO", "2026-07-01",
     [("Grass-fed beef — whole carcass", 2, "each", "Min 600 lb hanging weight each"),
      ("Grass-fed beef — half carcass", 4, "each", "Alternate months OK")]),
    ("Heritage Breed Pork — Specialty Market",
     "Specialty food market seeking locally raised heritage breed pork for charcuterie program. "
     "Berkshire, Mangalitsa, or similar preferred.",
     "Retail", "Delivery", "Boulder", "CO", "2026-09-15",
     [("Heritage pork — shoulders", 80, "lb", "For house-made salami program"),
      ("Heritage pork — belly", 60, "lb", "Pancetta and bacon curing")]),
    ("Seasonal Vegetables — CSA Supplement",
     "Community kitchen supplementing CSA boxes with additional local produce. "
     "Need reliable source for high-volume weeks May–October.",
     "Community", "Delivery", "Longmont", "CO", "2026-10-31",
     [("Zucchini", 100, "lb", "Summer glut pricing preferred"),
      ("Tomatoes — field grade", 200, "lb", "For canning program — cosmetic blemishes OK"),
      ("Winter squash", 150, "lb", "Butternut, acorn, delicata")]),
    ("Raw Honey — Wholesale",
     "Artisan bakery looking for local raw honey for year-round production. "
     "Unfiltered preferred, varietal honeys a plus.",
     "Restaurant", "Farm Pickup", "Greeley", "CO", "2026-12-31",
     [("Raw wildflower honey", 50, "lb", "Unfiltered, in 5-gallon buckets preferred"),
      ("Crystallized honey", 20, "lb", "For specialty bread glazes")]),
]

for (title, desc, btype, deliver, city, state, needed_by, items) in wanted_ads:
    ad_id = first("SELECT AdID FROM FoodWantedAds WHERE BusinessID=:b AND Title=:t", {"b": BID, "t": title})
    if not ad_id:
        ad_id = first(
            "INSERT INTO FoodWantedAds (BusinessID, Title, Description, BuyerType, DeliveryPreference, "
            "LocationCity, LocationState, NeededBy, IsActive) OUTPUT INSERTED.AdID "
            "VALUES (:b, :t, :desc, :bt, :del, :city, :st, :nb, 1)",
            {"b": BID, "t": title, "desc": desc, "bt": btype, "del": deliver,
             "city": city, "st": state, "nb": needed_by}
        )
        print(f"  Created FoodWantedAd: {title[:50]}")
    else:
        print(f"  FoodWantedAd exists: {title[:50]}")
        continue

    for (ing, qty, unit, notes) in items:
        q(
            "INSERT INTO FoodWantedItems (AdID, IngredientName, Quantity, Unit, Notes) "
            "VALUES (:ad, :ing, :qty, :unit, :notes)",
            {"ad": ad_id, "ing": ing, "qty": qty, "unit": unit, "notes": notes}
        )
        print(f"    Item: {ing}")

db.commit()

# ─────────────────────────────────────────────
# 5. APP NOTIFICATIONS
# ─────────────────────────────────────────────
section("AppNotifications")

notifications = [
    ("csa_signup",       "New CSA Member",          "Sarah Johnson signed up for the Full Share CSA plan.",
     "/app/csa", "CSASubscription", None),
    ("marketplace_order","New Marketplace Order",    "Order #ORD-2026-0412 for 20 lb heirloom tomatoes from Harvest Table Restaurant.",
     "/app/orders", "Order", None),
    ("food_wanted",      "New Food Wanted Match",   "Your produce listing matches a buyer request for organic salad mix in Denver.",
     "/app/food-wanted", "FoodWantedAd", None),
    ("event_reg",        "Event Registration",      "3 new attendees registered for the Spring Alpaca Open Farm Day.",
     "/app/events", "Event", None),
    ("blog_comment",     "New Blog Comment",        "A visitor commented on your post 'Heirloom Tomato Season Opens at Food World'.",
     "/app/blog", "Blog", None),
    ("csa_payment",      "CSA Payment Received",    "Monthly CSA payment of $120.00 received from Michael Torres.",
     "/app/accounting", "Payment", None),
    ("land_lease",       "Land Lease Inquiry",      "New inquiry on your 45-acre organic crop land lease listing.",
     "/app/land-leasing", "LandLease", None),
    ("livestock_inquiry","Livestock Inquiry",        "Someone inquired about Sundance Golden Glory (Alpaca Herdsire).",
     "/app/livestock", "Animal", None),
]

for (ntype, title, body, link, entity_type, entity_id) in notifications:
    exists = first(
        "SELECT NotificationID FROM AppNotifications WHERE RecipientBusinessID=:b AND Title=:t",
        {"b": BID, "t": title}
    )
    if exists:
        print(f"  Notification '{title}' already exists")
        continue
    q(
        "INSERT INTO AppNotifications (RecipientPeopleID, RecipientBusinessID, Type, Title, Body, "
        "LinkPath, RelatedEntityType, RelatedEntityID) "
        "VALUES (:p, :b, :type, :title, :body, :link, :etype, :eid)",
        {"p": PEOPLE_ID, "b": BID, "type": ntype, "title": title, "body": body,
         "link": link, "etype": entity_type, "eid": entity_id}
    )
    print(f"  Created notification: {title}")

db.commit()
print("\n=== seed_demo_15671c.py COMPLETE ===")
