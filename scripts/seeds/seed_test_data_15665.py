"""
Seed test data for BusinessID=15665.
Covers: Equipment Marketplace + Food Wanted Board.
Safe to re-run — skips insert if data already exists for this business.
Run: python seed_test_data_15665.py
"""
import os, sys
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text
from database import SessionLocal

BID = 15665

def run():
    db = SessionLocal()
    try:
        seed_equipment(db)
        seed_food_wanted(db)
        db.commit()
        print("✓ Done — test data committed.")
    except Exception as e:
        db.rollback()
        print(f"✗ Error: {e}")
        raise
    finally:
        db.close()


# ── Equipment Marketplace ──────────────────────────────────────────────────────

def seed_equipment(db):
    existing = db.execute(
        text("SELECT COUNT(*) FROM EquipmentListings WHERE BusinessID=:b"), {"b": BID}
    ).scalar()
    if existing:
        print(f"  Equipment: {existing} listings already exist, skipping.")
        return

    listings = [
        {
            "title": "2016 John Deere 5075E Utility Tractor",
            "desc": "Well-maintained utility tractor, used primarily for loader work and light tillage. New front tires in 2024. All service records available.",
            "cat": "Tractors", "lt": "sale", "price": 38500.00,
            "swap": None, "loan": None,
            "cond": "good", "yr": 2016, "make": "John Deere", "model": "5075E",
            "hrs": 2340, "city": "Ames", "state": "Iowa",
        },
        {
            "title": "Kuhn GA 7301 Tedder / Hay Rake — Trade for Disc Mower",
            "desc": "10-rotor tedder in excellent condition. Only two seasons on it. Looking to trade for a quality disc mower of similar value — open to negotiating.",
            "cat": "Hay & Forage", "lt": "swap",
            "price": None, "swap": "Disc mower (Kuhn, Krone, or New Holland) — willing to add cash for right deal",
            "loan": None, "cond": "excellent", "yr": 2021,
            "make": "Kuhn", "model": "GA 7301", "hrs": None,
            "city": "Ames", "state": "Iowa",
        },
        {
            "title": "Great Plains 3S-3000HDF No-Till Drill — Available to Borrow",
            "desc": "30-foot no-till drill available for neighbor use during our off-season window (typically late August–September). Fuel and wear-part costs covered by borrower. Must haul yourself — within 50 miles.",
            "cat": "Planting & Seeding", "lt": "borrow",
            "price": None, "swap": None,
            "loan": "Available late August–September. Borrower covers fuel and any wear parts. Must be within 50 miles of Ames, IA.",
            "cond": "good", "yr": 2018,
            "make": "Great Plains", "model": "3S-3000HDF", "hrs": None,
            "city": "Ames", "state": "Iowa",
        },
        {
            "title": "J&M 750-18 Grain Cart — 750 Bushel",
            "desc": "Solid grain cart, runs well. Scale and vertical auger both working. Paint faded on the outside but mechanically sound. Good for a first cart or secondary cart.",
            "cat": "Grain Handling", "lt": "sale", "price": 14900.00,
            "swap": None, "loan": None, "cond": "fair",
            "yr": 2010, "make": "J&M", "model": "750-18", "hrs": None,
            "city": "Ames", "state": "Iowa",
        },
        {
            "title": "2019 Kinze 3660 16-Row Planter",
            "desc": "16-row 30-inch planter with liquid fertilizer, row clutches, and Ag Leader monitors. Field-ready, used 4 seasons. Always shedded. Reason for selling: moving to 24-row.",
            "cat": "Planting & Seeding", "lt": "sale", "price": 87000.00,
            "swap": None, "loan": None, "cond": "excellent",
            "yr": 2019, "make": "Kinze", "model": "3660", "hrs": None,
            "city": "Ames", "state": "Iowa",
        },
        {
            "title": "Spray Coupe 220 Field Sprayer — Parts or Repair",
            "desc": "220-gallon self-propelled sprayer. Engine runs but boom needs work — two sections out. Good source of boom parts, pump, and frame. Selling as-is.",
            "cat": "Sprayers", "lt": "sale", "price": 1800.00,
            "swap": None, "loan": None, "cond": "parts",
            "yr": 2004, "make": "Spray Coupe", "model": "220", "hrs": 4100,
            "city": "Ames", "state": "Iowa",
        },
    ]

    ids = []
    for l in listings:
        row = db.execute(text("""
            INSERT INTO EquipmentListings
                (BusinessID, Title, Description, Category, ListingType, AskingPrice,
                 SwapFor, LoanTerms, Condition, YearMade, Make, Model, HoursUsed,
                 City, StateProvince)
            OUTPUT INSERTED.ListingID
            VALUES (:b,:t,:d,:cat,:lt,:price,:swap,:loan,:cond,:yr,:make,:model,:hrs,:city,:state)
        """), {
            "b": BID, "t": l["title"], "d": l["desc"], "cat": l["cat"],
            "lt": l["lt"], "price": l["price"], "swap": l["swap"],
            "loan": l["loan"], "cond": l["cond"], "yr": l["yr"],
            "make": l["make"], "model": l["model"], "hrs": l["hrs"],
            "city": l["city"], "state": l["state"],
        }).fetchone()
        ids.append(row[0])

    # Add a couple of inquiries on the first listing (tractor)
    inquiries = [
        {
            "lid": ids[0], "name": "Cedar Ridge Farm", "email": "info@cedarridgefarm.com",
            "msg": "Hi, is the tractor still available? Any chance you'd do $36,000? We're about 25 miles south of you and could pick up this week.",
            "type": "purchase",
        },
        {
            "lid": ids[0], "name": "Sunrise Acres", "email": "sunrise@gmail.com",
            "msg": "Interested in the 5075E. Does it have a loader? What size are the rear tires?",
            "type": "general",
        },
        {
            "lid": ids[1], "name": "Hilltop Hay Co.", "email": "hilltop@hayco.net",
            "msg": "I have a Krone EasyCut 280 disc mower, 2019, good condition. Would you be interested? I can send photos.",
            "type": "swap",
        },
    ]
    for inq in inquiries:
        db.execute(text("""
            INSERT INTO EquipmentInquiries
                (ListingID, SenderName, SenderEmail, Message, InquiryType)
            VALUES (:lid,:name,:email,:msg,:type)
        """), inq)

    print(f"  Equipment: inserted {len(ids)} listings + {len(inquiries)} inquiries.")


# ── Food Wanted Board ──────────────────────────────────────────────────────────

def seed_food_wanted(db):
    existing = db.execute(
        text("SELECT COUNT(*) FROM FoodWantedAds WHERE BusinessID=:b"), {"b": BID}
    ).scalar()
    if existing:
        print(f"  Food Wanted: {existing} ads already exist, skipping.")
        return

    ads = [
        {
            "title": "Sourcing heirloom tomatoes, sweet peppers & fresh herbs for fall menu",
            "desc": "We run a 60-seat farm-to-table restaurant and source as much as possible locally. Looking for a reliable weekly supplier through September and October. Certified or transitional organic preferred but not required. We pick up every Tuesday morning.",
            "bt": "Restaurant", "deliv": "pickup",
            "city": "Ames", "state": "Iowa", "needed_by": "2026-08-01",
            "items": [
                {"name": "Heirloom Tomatoes", "qty": "40", "unit": "lbs", "notes": "Mixed varieties, blemishes fine"},
                {"name": "Sweet Bell Peppers", "qty": "20", "unit": "lbs", "notes": "Red and yellow preferred"},
                {"name": "Shishito Peppers",   "qty": "5",  "unit": "lbs", "notes": None},
                {"name": "Fresh Basil",         "qty": "3",  "unit": "lbs", "notes": "Large leaf Italian"},
                {"name": "Thyme",               "qty": "1",  "unit": "lbs", "notes": "Fresh cut"},
                {"name": "Rosemary",            "qty": "1",  "unit": "lbs", "notes": "Fresh cut"},
            ],
        },
        {
            "title": "Looking for bulk local berries and raw honey for jam production",
            "desc": "Small-batch jam operation. Need consistent supply through berry season. Buying quantities each week — can work with U-pick operations too. Interested in building a long-term supplier relationship.",
            "bt": "Artisan Producer", "deliv": "either",
            "city": "Ames", "state": "Iowa", "needed_by": "2026-07-01",
            "items": [
                {"name": "Strawberries",  "qty": "50",  "unit": "lbs", "notes": "June bearing, local preferred"},
                {"name": "Blueberries",   "qty": "30",  "unit": "lbs", "notes": "Any variety"},
                {"name": "Raspberries",   "qty": "20",  "unit": "lbs", "notes": "Red or black"},
                {"name": "Raw Honey",     "qty": "10",  "unit": "gallons", "notes": "Unfiltered, local hives"},
                {"name": "Pectin Apples", "qty": "25",  "unit": "lbs", "notes": "Tart varieties like Granny Smith or Haralson"},
            ],
        },
        {
            "title": "Seeking pastured eggs, whole chickens & pork cuts for weekly orders",
            "desc": "Food hub aggregating orders for 80+ households in the Ames area. We place weekly orders and can handle refrigerated delivery or farm pickup. Looking for farms that can supply consistently April–November.",
            "bt": "Food Hub", "deliv": "delivery",
            "city": "Ames", "state": "Iowa", "needed_by": None,
            "items": [
                {"name": "Pastured Eggs",       "qty": "30",  "unit": "dozen", "notes": "Any color, minimum size large"},
                {"name": "Whole Chickens",      "qty": "20",  "unit": "units", "notes": "3–5 lbs, fresh or frozen"},
                {"name": "Ground Pork",         "qty": "15",  "unit": "lbs",   "notes": "Pastured or heritage breed"},
                {"name": "Pork Chops",          "qty": "10",  "unit": "lbs",   "notes": "Bone-in"},
                {"name": "Pork Belly",          "qty": "5",   "unit": "lbs",   "notes": "Uncured"},
                {"name": "Lard",                "qty": "3",   "unit": "lbs",   "notes": "Leaf lard preferred"},
            ],
        },
        {
            "title": "Need sunflower oil, oat flour & specialty grains for artisan bakery",
            "desc": "Artisan bakery looking to source locally-milled flours and cold-pressed oils. We bake 6 days a week and go through significant volume. Open to annual purchase commitments for the right supplier.",
            "bt": "Artisan Producer", "deliv": "delivery",
            "city": "Ames", "state": "Iowa", "needed_by": None,
            "items": [
                {"name": "Cold-Pressed Sunflower Oil", "qty": "5",   "unit": "gallons", "notes": "Unrefined, local press preferred"},
                {"name": "Oat Flour",                  "qty": "50",  "unit": "lbs",     "notes": "Stone-ground, gluten-free facility a plus"},
                {"name": "Whole Wheat Flour",           "qty": "100", "unit": "lbs",     "notes": "Hard red winter wheat"},
                {"name": "Rye Flour",                   "qty": "25",  "unit": "lbs",     "notes": "Dark rye"},
                {"name": "Rolled Oats",                 "qty": "40",  "unit": "lbs",     "notes": "Thick cut"},
            ],
        },
    ]

    ad_ids = []
    for ad in ads:
        row = db.execute(text("""
            INSERT INTO FoodWantedAds
                (BusinessID, Title, Description, BuyerType, DeliveryPreference,
                 LocationCity, LocationState, NeededBy)
            OUTPUT INSERTED.AdID
            VALUES (:b,:t,:d,:bt,:deliv,:city,:state,:nb)
        """), {
            "b": BID, "t": ad["title"], "d": ad["desc"],
            "bt": ad["bt"], "deliv": ad["deliv"],
            "city": ad["city"], "state": ad["state"],
            "nb": ad["needed_by"],
        }).fetchone()
        ad_id = row[0]
        ad_ids.append(ad_id)
        for it in ad["items"]:
            db.execute(text("""
                INSERT INTO FoodWantedItems (AdID, IngredientName, Quantity, Unit, Notes)
                VALUES (:ad,:name,:qty,:unit,:notes)
            """), {
                "ad": ad_id, "name": it["name"], "qty": it["qty"],
                "unit": it["unit"], "notes": it["notes"],
            })

    # Add sample responses on the first two ads
    responses = [
        {
            "ad": ad_ids[0],
            "name": "Sunrise Family Farm",
            "email": "hello@sunrisefamilyfarm.com",
            "msg": "Hi! We grow 8 varieties of heirloom tomatoes and have sweet peppers and shishitos too. We're about 12 miles outside Ames and could easily do Tuesday pickup. Roughly $2.50/lb for tomatoes, $2.00/lb peppers. Want to schedule a farm visit?",
        },
        {
            "ad": ad_ids[0],
            "name": "Prairie Wind Gardens",
            "email": "prairiewind@outlook.com",
            "msg": "We can supply fresh basil and thyme weekly — certified naturally grown. Also have rosemary and other culinary herbs. Can you tell me more about quantities and pricing expectations?",
        },
        {
            "ad": ad_ids[1],
            "name": "Blackwood Berry Farm",
            "email": "orders@blackwoodberry.com",
            "msg": "We have strawberries and blueberries available through the season. U-pick available or we can have them pre-picked. We also partner with a local beekeeper who keeps hives on our property — I can connect you with them for the honey.",
        },
    ]
    for r in responses:
        db.execute(text("""
            INSERT INTO FoodWantedResponses
                (AdID, SenderName, SenderEmail, Message)
            VALUES (:ad,:name,:email,:msg)
        """), r)

    total_items = sum(len(a["items"]) for a in ads)
    print(f"  Food Wanted: inserted {len(ad_ids)} ads + {total_items} items + {len(responses)} responses.")


if __name__ == "__main__":
    run()
