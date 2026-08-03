"""
seed_suppliers_15671.py — Supplier directory demo data for BusinessID=15671
Adds SupplierListings + SupplierReviews.
Idempotent: skips entries that already exist by CompanyName.
"""
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import get_db
from sqlalchemy import text

BID = 15671
db = next(get_db())

def q(sql, params=None):
    db.execute(text(sql), params or {})

def first(sql, params=None):
    return db.execute(text(sql), params or {}).scalar()

def section(name):
    print(f"\n=== {name} ===")

# (CompanyName, Category, Description, ProductsServices,
#  City, State, Website, Phone, Email, ServesRadius, IsVerified, BusinessID)
suppliers = [
    # Seeds & Plants
    (
        "Rocky Mountain Seed Alliance",
        "Seeds & Plants",
        "Non-profit seed library and commercial seed supplier specializing in open-pollinated, "
        "heirloom, and regionally adapted vegetable, herb, and grain varieties for Colorado growers.",
        "Heirloom tomato seed, dry bean varieties, heritage grain seed, cover crop mixes, "
        "herb seed packets, seed saving workshops",
        "Denver", "CO",
        "https://rockymountainseedalliance.org",
        "303-555-0810", "seeds@rmsa.org",
        150, 1, BID
    ),
    (
        "High Plains Nursery & Propagation",
        "Seeds & Plants",
        "Commercial greenhouse and propagation facility offering transplants, bareroot seedlings, "
        "and custom growing for farms and CSA operations across the Front Range.",
        "Vegetable transplants, herb starts, strawberry plugs, garlic seed, onion sets, "
        "cover crop seed mixes, custom propagation services",
        "Greeley", "CO",
        None,
        "970-555-0221", "orders@highplainsnursery.com",
        80, 1, BID
    ),
    (
        "Centennial Wildflower & Native Seed Co.",
        "Seeds & Plants",
        "Colorado-native seed source for pollinator habitat, pasture restoration, and riparian buffers. "
        "Bulk seed for large acreage projects.",
        "Native grass mixes, wildflower seed, riparian restoration blends, erosion control mixes, "
        "pollinator habitat kits",
        "Fort Collins", "CO",
        None,
        "970-555-0374", "info@centennialseed.com",
        200, 0, None
    ),

    # Fertilizers & Soil Amendments
    (
        "Colorado Compost & Soil Works",
        "Fertilizers & Soil Amendments",
        "CDPHE-certified compost facility producing premium blended composts, worm castings, "
        "and custom soil amendment mixes from local organic waste streams.",
        "Finished compost (bulk & bagged), worm castings, biochar blend, humic acid, "
        "custom soil blends, liquid compost tea, delivery service",
        "Longmont", "CO",
        None,
        "303-555-0499", "sales@coloradocompost.com",
        60, 1, BID
    ),
    (
        "Front Range Organic Inputs",
        "Fertilizers & Soil Amendments",
        "Distributor of OMRI-listed organic fertilizers and biological soil amendments serving "
        "certified and transitional organic farms throughout Colorado.",
        "Fish emulsion, kelp meal, feather meal, blood meal, rock phosphate, greensand, "
        "mycorrhizal inoculants, cover crop blends",
        "Boulder", "CO",
        None,
        "720-555-0583", "orders@frontrangeorganic.com",
        120, 1, None
    ),

    # Feed & Supplements
    (
        "Mountain West Livestock Feed",
        "Feed & Supplements",
        "Family-owned feed mill and distributor offering custom milling, bulk grains, "
        "and specialty blends for alpacas, horses, goats, cattle, and poultry.",
        "Alfalfa hay, grass hay, custom alpaca ration, pelleted goat feed, layer hen mash, "
        "mineral supplements, salt blocks, bulk oats and barley",
        "Loveland", "CO",
        None,
        "970-555-0612", "feed@mtnwestfeed.com",
        75, 1, BID
    ),
    (
        "Sunrise Alpaca Nutrition Specialists",
        "Feed & Supplements",
        "Specialist in camelid nutrition — formulating custom mineral mixes, consulting on "
        "pasture management, and supplying supplements specifically for alpaca and llama herds.",
        "Alpaca mineral mix, selenium supplement, Vitamin E/D paste, conditioning pellets, "
        "forage analysis service, nutrition consulting",
        "Windsor", "CO",
        None,
        "970-555-0741", "nutrition@sunrisealpaca.com",
        100, 1, BID
    ),

    # Veterinary Supplies
    (
        "High Country Vet Supply",
        "Veterinary Supplies",
        "Full-service veterinary supply distributor carrying pharmaceuticals, "
        "biologicals, instruments, and husbandry equipment for livestock producers.",
        "Vaccines, dewormers, antibiotics (prescription), IV supplies, syringes, "
        "ear tags, tattoo kits, pregnancy detection equipment, halters and leads",
        "Fort Collins", "CO",
        None,
        "970-555-0856", "orders@highcountryvet.com",
        90, 1, BID
    ),

    # Equipment Dealers
    (
        "Platte Valley Equipment & Implement",
        "Equipment Dealers",
        "Full-line John Deere dealer serving Northern Colorado farmers with new and used "
        "equipment, precision ag technology, and parts.",
        "Tractors, planters, sprayers, hay equipment, GPS guidance systems, "
        "precision ag sensors, parts, certified pre-owned equipment",
        "Greeley", "CO",
        None,
        "970-555-0934", "sales@plattevalleyequip.com",
        150, 1, None
    ),
    (
        "Colorado Agri-Tronics",
        "Equipment Dealers",
        "Specialty dealer for small-farm and specialty crop equipment: bed formers, "
        "row cultivators, walk-behind tractors, and cold-chain refrigeration units.",
        "BCS walk-behind tractors, Farmers Friend toolbars, Jang seeders, "
        "refrigerated van conversion kits, produce washers, packing line equipment",
        "Longmont", "CO",
        None,
        "303-555-1012", "info@coloagritronics.com",
        80, 1, BID
    ),

    # Equipment Repair
    (
        "Front Range Farm Equipment Repair",
        "Equipment Repair",
        "Mobile and in-shop agricultural equipment repair serving farms across Larimer, "
        "Weld, and Boulder counties. Same-week service during planting season.",
        "Tractor engine overhaul, hydraulic repair, welder fabrication, "
        "refrigeration unit service, irrigation pump repair, seasonal tune-ups",
        "Berthoud", "CO",
        None,
        "970-555-1105", "shop@frfarmrepair.com",
        70, 0, None
    ),

    # Irrigation & Water
    (
        "Peak Irrigation & Water Systems",
        "Irrigation & Water",
        "Design, installation, and service of drip, micro-spray, and overhead "
        "irrigation for vegetable farms, orchards, and specialty crops.",
        "Drip tape installation, micro-drip systems, fertigation equipment, "
        "soil moisture sensors, pump stations, winterization, system design consulting",
        "Fort Collins", "CO",
        None,
        "970-555-1230", "design@peakirrigation.com",
        100, 1, BID
    ),
    (
        "Cache la Poudre Water Solutions",
        "Irrigation & Water",
        "Water rights consulting, well permitting, and agricultural water management "
        "for farms transitioning to more efficient irrigation.",
        "Water rights analysis, well permits, flow measurement, water budgeting, "
        "ditch and headgate maintenance, NRCS EQIP application assistance",
        "Fort Collins", "CO",
        None,
        "970-555-1318", "consult@poudrewater.com",
        120, 0, None
    ),

    # Storage & Handling
    (
        "Rocky Ridge Cold Storage & Logistics",
        "Storage & Handling",
        "Shared cold storage and packing facility offering short- and long-term rental, "
        "pre-cooling, hydro-cooling, and distribution services for produce farms.",
        "Pre-cooling rooms, long-term cold storage, hydro-cooler rental, "
        "packing line access, produce grading, distribution coordination",
        "Longmont", "CO",
        None,
        "303-555-1402", "storage@rockyridgecold.com",
        50, 1, BID
    ),
    (
        "Mountain States Bin & Container",
        "Storage & Handling",
        "Supplier of agricultural bins, crates, totes, and reusable harvest containers "
        "for vegetable, fruit, and flower operations.",
        "Plastic harvest bins (16-60 bu), stackable crates, reusable harvest bags, "
        "bin washers, wood and plastic pallets, bin rental program",
        "Denver", "CO",
        None,
        "303-555-1511", "sales@msbincontainer.com",
        100, 0, None
    ),

    # Packaging & Labels
    (
        "Prairie Pack — Farm Packaging Specialists",
        "Packaging & Labels",
        "Custom packaging design and supply for farms, CSA operations, and food businesses. "
        "Specializes in compostable and recycled-content packaging.",
        "Custom-printed CSA bags, compostable produce bags, tamper-evident clamshells, "
        "kraft paper bags, custom stickers and labels, meat wrap, wax boxes",
        "Boulder", "CO",
        None,
        "720-555-1634", "hello@prairiepack.com",
        200, 1, BID
    ),

    # Consulting & Agronomy
    (
        "Summit Ag Consulting Group",
        "Consulting & Agronomy",
        "Team of certified crop advisors (CCA) providing soil health, cover crop, "
        "and integrated pest management consulting for Front Range farms.",
        "Soil sampling and interpretation, precision fertilizer planning, "
        "IPM scouting, cover crop system design, organic transition planning, "
        "USDA NRCS program applications",
        "Loveland", "CO",
        None,
        "970-555-1720", "team@summitagconsulting.com",
        150, 1, BID
    ),
    (
        "Mile High Pasture & Grazing Consulting",
        "Consulting & Agronomy",
        "Holistic planned grazing consultant specializing in rotational grazing design, "
        "pasture improvement, and integration of livestock with crop operations.",
        "Grazing plan development, fencing and water system design, "
        "pasture renovation, mob grazing implementation, alpaca and sheep integration",
        "Estes Park", "CO",
        None,
        "970-555-1815", "graze@milehighpasture.com",
        200, 0, None
    ),

    # Financial Services
    (
        "Colorado AgriBank — Farm Lending Division",
        "Financial Services",
        "Farm Credit institution offering operating loans, equipment financing, "
        "real estate mortgages, and young farmer programs for Colorado agricultural businesses.",
        "Operating lines of credit, equipment loans, farm real estate mortgages, "
        "FSA guaranteed loans, beginning farmer programs, financial planning",
        "Greeley", "CO",
        None,
        "970-555-1903", "farmlending@coloradoagribank.com",
        300, 1, None
    ),

    # Insurance
    (
        "High Country Farm & Ranch Insurance",
        "Insurance",
        "Independent insurance agency specializing in crop, livestock, farm property, "
        "and liability coverage for Colorado farm and ranch operations.",
        "Multi-peril crop insurance, livestock mortality, farm umbrella liability, "
        "farm vehicle, agritourism liability, specialty crop riders",
        "Fort Collins", "CO",
        None,
        "970-555-1998", "farms@highcountryins.com",
        200, 1, BID
    ),
]

# Reviews: (CompanyName, ReviewerName, Rating, Comment)
reviews_by_company = {
    "Rocky Mountain Seed Alliance": [
        ("Maria Santos", 5, "Incredible selection of dry beans and heirloom tomatoes. Their seed-saving workshop was worth every penny."),
        ("James Whitfield", 5, "Ordered the Colorado heritage grain seed pack — germination rates were exceptional. Will order again."),
        ("Elena Kowalski", 4, "Great non-profit mission and solid catalog, though shipping took a bit longer than expected."),
    ],
    "High Plains Nursery & Propagation": [
        ("Priya Nair", 5, "Custom transplant order for 2,000 basil starts. Every tray arrived healthy and on schedule."),
        ("Food World Farm", 5, "Our main transplant supplier for three seasons. Consistent quality, fair wholesale pricing."),
        ("Garrett Olson", 4, "Good selection of onion sets. Would love to see more herb variety options."),
    ],
    "Colorado Compost & Soil Works": [
        ("Food World Farm", 5, "Bulk compost delivery straight to the field. Driver was careful with the tractor paths. Top quality product."),
        ("Maria Santos", 5, "The worm castings are premium grade. My tomato yields improved noticeably after side-dressing."),
        ("James Whitfield", 4, "Excellent product but the liquid compost tea often sells out by May — order early."),
    ],
    "Mountain West Livestock Feed": [
        ("Garrett Olson", 5, "Custom alpaca ration formulated perfectly. Herd condition scores have never been better."),
        ("Food World Farm", 5, "Reliable monthly delivery, competitive pricing on bulk alfalfa. Easy to adjust orders week-to-week."),
        ("Elena Kowalski", 5, "Switched our poultry feed here from the co-op — much fresher mill date, birds prefer it."),
    ],
    "Sunrise Alpaca Nutrition Specialists": [
        ("Food World Farm", 5, "Dr. Reyes reviewed our whole herd and caught a selenium deficiency we'd missed. Professional and thorough."),
        ("Garrett Olson", 5, "The mineral mix is the best we've used. Fiber quality improved within one shearing cycle."),
        ("James Whitfield", 4, "Great consulting service. Wish they had more availability during spring shearing season."),
    ],
    "High Country Vet Supply": [
        ("Food World Farm", 5, "Same-day shipping on vaccines if you order before noon. Has saved us during an emergency more than once."),
        ("Garrett Olson", 4, "Good selection and fair prices. Prescription items require fax from vet which adds a day."),
        ("Priya Nair", 5, "Ordered halters and leads for our small flock — sturdy quality, shipped fast."),
    ],
    "Colorado Agri-Tronics": [
        ("Food World Farm", 5, "Helped us spec out the refrigerated van conversion for our delivery truck. Saved thousands vs. buying new."),
        ("Maria Santos", 4, "Excellent source for the Jang seeder — hard to find locally. Good phone support too."),
        ("Elena Kowalski", 5, "BCS tractor has been running three seasons with zero issues. Staff really know small farm equipment."),
    ],
    "Peak Irrigation & Water Systems": [
        ("Food World Farm", 5, "Designed and installed our drip system for 8 acres of vegetables. On time, on budget, works flawlessly."),
        ("Priya Nair", 5, "The soil moisture sensors integrated with our irrigation timer eliminated over-watering completely."),
        ("James Whitfield", 4, "Solid installer but busy — book them for fall/spring installation well in advance."),
    ],
    "Rocky Ridge Cold Storage & Logistics": [
        ("Food World Farm", 5, "Renting a pre-cooling bay here has let us offer restaurants same-day-harvested quality. Game changer."),
        ("Maria Santos", 5, "Hydro-cooler rental is very affordable and the facility is clean and well-maintained."),
        ("Garrett Olson", 4, "Good cold storage options. Would love 24-hour key-card access instead of staffed hours only."),
    ],
    "Prairie Pack — Farm Packaging Specialists": [
        ("Food World Farm", 5, "Our branded CSA bags look professional and customers love the compostable material. Minimum order is reasonable."),
        ("Priya Nair", 5, "Custom herb labels turned out beautifully. Fast turnaround and the designer was easy to work with."),
        ("Elena Kowalski", 4, "Great quality — just wish the meat wrap came in smaller rolls for smaller operations."),
    ],
    "Summit Ag Consulting Group": [
        ("Food World Farm", 5, "Our CCA, Rachel Torres, has transformed our soil program over two seasons. BRIX scores are up across the board."),
        ("Maria Santos", 5, "They handled our EQIP application for the cover crop program. Approved first submission. Highly recommend."),
        ("James Whitfield", 5, "IPM scouting service caught a thrips pressure early in May. Saved our pepper crop."),
    ],
    "High Country Farm & Ranch Insurance": [
        ("Food World Farm", 5, "Switched our whole farm policy here — saved 15% and got agritourism liability included that our old carrier excluded."),
        ("Garrett Olson", 4, "Good livestock mortality coverage options for alpacas specifically — most agents have no idea how to cover them."),
        ("Maria Santos", 5, "Filed a crop loss claim after the late frost. Payment was fast and the adjuster was knowledgeable about produce operations."),
    ],
    "Platte Valley Equipment & Implement": [
        ("James Whitfield", 4, "Parts department is excellent and usually in stock. Sales team can be pushy on upsells."),
        ("Elena Kowalski", 5, "Bought a used 4040 here — fair price and it was fully reconditioned. No surprises."),
    ],
    "Front Range Organic Inputs": [
        ("Priya Nair", 5, "One-stop shop for all our OMRI inputs. The mycorrhizal inoculant gave our transplants a visible boost."),
        ("Food World Farm", 4, "Great product range for organic operations. Minimum order quantities can be high for small farms."),
    ],
    "Mile High Pasture & Grazing Consulting": [
        ("Garrett Olson", 5, "Worked with Tom to design our rotational system for 12 paddocks. Pasture recovery time dropped by 40%."),
        ("Food World Farm", 4, "Solid grazing plan consultant. Remote sessions available which saves a lot of time."),
    ],
}

section("SupplierListings")
supplier_ids = {}
for row in suppliers:
    (name, cat, desc, prods, city, state, website, phone, email, radius, verified, bid) = row
    exists = first("SELECT SupplierID FROM SupplierListings WHERE CompanyName=:n", {"n": name})
    if exists:
        print(f"  Exists: {name}")
        supplier_ids[name] = exists
        continue
    sid = first(
        "INSERT INTO SupplierListings "
        "(BusinessID, CompanyName, Category, Description, ProductsServices, "
        "City, StateProvince, Website, Phone, Email, ServesRadius, IsVerified, IsActive) "
        "OUTPUT INSERTED.SupplierID "
        "VALUES (:bid, :n, :cat, :desc, :prods, :city, :state, :web, :ph, :em, :rad, :ver, 1)",
        {"bid": bid, "n": name, "cat": cat, "desc": desc, "prods": prods,
         "city": city, "state": state, "web": website, "ph": phone, "em": email,
         "rad": radius, "ver": verified}
    )
    supplier_ids[name] = sid
    print(f"  Created [{cat}]: {name}")

db.commit()

section("SupplierReviews")
total_reviews = 0
for company, rev_list in reviews_by_company.items():
    sid = supplier_ids.get(company)
    if not sid:
        print(f"  Skipping reviews — {company} not found")
        continue
    for (reviewer, rating, comment) in rev_list:
        exists = first(
            "SELECT ReviewID FROM SupplierReviews WHERE SupplierID=:s AND ReviewerName=:n AND Rating=:r",
            {"s": sid, "n": reviewer, "r": rating}
        )
        if not exists:
            q(
                "INSERT INTO SupplierReviews (SupplierID, ReviewerName, Rating, Comment) "
                "VALUES (:s, :n, :r, :c)",
                {"s": sid, "n": reviewer, "r": rating, "c": comment}
            )
            total_reviews += 1

db.commit()
print(f"  Added {total_reviews} reviews across {len(reviews_by_company)} suppliers")

print(f"\n=== COMPLETE — {len(supplier_ids)} suppliers, {total_reviews} reviews ===")
