"""
seed_full_15665.py  —  Comprehensive seed for BusinessID = 15665
Covers: Blog, Precision Ag, Website, Accounting, Marketplace, Produce,
        Meat, Processed Food, Services, Animals, Food Aggregation (kept from
        previous seed_aggregator.py run)

Run from Backend/:
    ./venv/Scripts/python.exe scripts/seeds/seed_full_15665.py
"""
import os, sys, json, random, calendar
from datetime import datetime, date, timedelta
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parent.parent / ".env")

engine = create_engine(
    f"mssql+pymssql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_SERVER')}/{os.getenv('DB_NAME')}",
    echo=False, pool_pre_ping=True,
)
Session = sessionmaker(bind=engine)
db = Session()

BID = 15665

# ── helpers ──────────────────────────────────────────────────────────────
def run(sql, p=None):
    db.execute(text(sql), p or {})

def scalar(sql, p=None):
    return db.execute(text(sql), p or {}).scalar()

def fetchall(sql, p=None):
    return db.execute(text(sql), p or {}).fetchall()

def fetchone(sql, p=None):
    return db.execute(text(sql), p or {}).fetchone()

def d(days_ago=0):
    return (date.today() - timedelta(days=days_ago)).isoformat()

def dt(days_ago=0):
    return (datetime.utcnow() - timedelta(days=days_ago)).strftime('%Y-%m-%d %H:%M:%S')

def section(label):
    print(f"\n{'='*55}")
    print(f"  {label}")
    print(f"{'='*55}")

def ok(msg): print(f"  [OK] {msg}")
def skip(msg, e): print(f"  [--] {msg}: {e}")

print(f"\nSeeding BusinessID = {BID}  ({datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC)")

# ═══════════════════════════════════════════════════════════════════════════
# 0.  WIPE
# ═══════════════════════════════════════════════════════════════════════════
section("0. Wiping existing data for BID=15665")

wipes = [
    # Blog
    ("blogphotos",          "BlogID IN (SELECT BlogID FROM blog WHERE BusinessID=:b)"),
    ("blog",                "BusinessID=:b"),
    ("blogcategories",      "BusinessID=:b"),
    ("blogauthors",         "BusinessID=:b"),
    # Precision Ag
    ("FieldBiomassAnalysis","BusinessID=:b"),
    ("Field",               "BusinessID=:b"),
    # Website
    ("BusinessWebBlock",    "PageID IN (SELECT PageID FROM BusinessWebPage WHERE BusinessID=:b)"),
    ("BusinessWebPage",     "BusinessID=:b"),
    ("BusinessWebsite",     "BusinessID=:b"),
    # Accounting transactional (keep COA if already set up)
    ("ExpenseLines",        "BusinessID=:b"),
    ("Expenses",            "BusinessID=:b"),
    ("InvoiceLines",        "BusinessID=:b"),
    ("Payments",            "BusinessID=:b"),
    ("Invoices",            "BusinessID=:b"),
    ("BillLines",           "BusinessID=:b"),
    ("Bills",               "BusinessID=:b"),
    ("JournalEntryLines",   "BusinessID=:b"),
    ("JournalEntries",      "BusinessID=:b"),
    ("AccountingItems",     "BusinessID=:b"),
    ("AccountingCustomers", "BusinessID=:b"),
    ("AccountingVendors",   "BusinessID=:b"),
    # Inventory & listings
    ("MarketplaceProducts", "BusinessID=:b"),
    ("Produce",             "BusinessID=:b"),
    ("MeatInventory",       "BusinessID=:b"),
    ("ProcessedFood",       "BusinessID=:b"),
    ("Services",            "BusinessID=:b"),
    # Animals
    ("Colors",  "AnimalID IN (SELECT AnimalID FROM Animals WHERE BusinessID=:b)"),
    ("Pricing", "AnimalID IN (SELECT AnimalID FROM Animals WHERE BusinessID=:b)"),
    ("Animals", "BusinessID=:b"),
]

for table, where in wipes:
    try:
        run(f"DELETE FROM {table} WHERE {where}", {"b": BID})
        db.commit()
    except Exception as e:
        db.rollback()
        skip(f"skip wipe {table}", e)

ok("Wipe complete")

# ═══════════════════════════════════════════════════════════════════════════
# 1.  BLOG
# ═══════════════════════════════════════════════════════════════════════════
section("1. Blog")

try:
    author_id = scalar("""
        INSERT INTO blogauthors (BusinessID, Name, Slug, Bio, CreatedAt, UpdatedAt)
        OUTPUT INSERTED.AuthorID
        VALUES (:b, 'Sarah Mitchell', 'sarah-mitchell-15665',
                'Head of Agronomy at Green Valley Farms. 12 years of sustainable berry cultivation, precision irrigation, and cold-chain logistics.',
                GETDATE(), GETDATE())
    """, {"b": BID})
    db.commit()

    author2_id = scalar("""
        INSERT INTO blogauthors (BusinessID, Name, Slug, Bio, CreatedAt, UpdatedAt)
        OUTPUT INSERTED.AuthorID
        VALUES (:b, 'James Okonkwo', 'james-okonkwo-15665',
                'Logistics Director. Former cold-chain specialist with 15 years managing temperature-controlled freight.',
                GETDATE(), GETDATE())
    """, {"b": BID})
    db.commit()

    cat_ids = {}
    for cname in ['Farm Updates', 'Crop Science', 'Sustainability', 'Market Insights', 'Cold Chain & Logistics']:
        cid = scalar("""
            INSERT INTO blogcategories
              (BusinessID, BlogCategoryName, IsGlobal, IsActive, CreatedAt)
            OUTPUT INSERTED.BlogCatID
            VALUES (:b, :n, 0, 1, GETDATE())
        """, {"b": BID, "n": cname})
        cat_ids[cname] = cid
    db.commit()

    posts = [
        {
            "title":   "Spring Blueberry Harvest Breaks Records — 23% Up on Last Year",
            "slug":    "spring-blueberry-harvest-record-yields-2025",
            "content": (
                "<p>Our 2025 spring blueberry harvest has surpassed all expectations, delivering a 23% increase "
                "over last year across all 15 partner farms. Thanks to our precision irrigation rollout and the "
                "expanded cold-chain network, premium-grade berries are now reaching metro distribution centres "
                "within 6 hours of picking — a 40% improvement on our 2023 baseline.</p>"
                "<p>Brix readings this season have been consistently strong at 14–16 across our main varieties "
                "(O'Neal, Misty, Sharpblue), driven by the mycorrhizal inoculation program trialled across "
                "7 partner farms since January. Average packout of export-grade fruit reached 82%, up from 71%.</p>"
                "<p>We're expanding to 3 new farms in the Hawkesbury region next season and expect total network "
                "capacity to reach 400 MT by Q3 2026.</p>"
            ),
            "cat": "Farm Updates", "featured": 1, "pub": 1, "age": 5, "aid": None,
        },
        {
            "title":   "Understanding NDVI: Reading Your Crops from Space",
            "slug":    "ndvi-satellite-crop-monitoring-guide",
            "content": (
                "<p>NDVI — Normalized Difference Vegetation Index — has become one of the most powerful diagnostic "
                "tools in our precision agriculture toolkit. By measuring the ratio of near-infrared to visible "
                "light reflected off plant canopies, we can detect stress responses weeks before they manifest "
                "as visible symptoms.</p>"
                "<p>Our field monitoring network captures multispectral imagery every 5 days via Sentinel-2 "
                "satellite passes, processed through our in-house analysis pipeline to produce per-field heat maps. "
                "Agronomists review alerts flagged at the 50-point NDVI threshold and dispatch targeted interventions "
                "— typically spot fertigation or foliar spray — within 48 hours.</p>"
                "<p>In the 2024 season, early NDVI detection prevented what would have been an estimated $34,000 "
                "crop loss on three partner farms by identifying iron deficiency chlorosis 18 days before leaf "
                "yellowing appeared.</p>"
            ),
            "cat": "Crop Science", "featured": 1, "pub": 1, "age": 12, "aid": None,
        },
        {
            "title":   "Zero-Waste Initiative: 18 Tonnes Diverted, Revenue Generated",
            "slug":    "zero-waste-crop-residue-revenue-stream",
            "content": (
                "<p>What was once disposed of as agricultural waste is now a meaningful secondary revenue stream. "
                "This season, Green Valley Farm Network partnered with a local biogas facility to convert blueberry "
                "cane prunings and strawberry runners into energy — diverting 18.4 tonnes from landfill and "
                "generating $4,200 in gate fees.</p>"
                "<p>Our composting program, now in its third year, is producing over 200 tonnes of premium soil "
                "amendment annually. Half is sold back to partner farms at subsidised rates as part of our circular "
                "model; the remainder is sold to home garden distributors at $6.50/bag retail equivalent.</p>"
                "<p>Water use across the network fell 19% year-on-year following the drip irrigation upgrade on "
                "340 hectares, reducing our water footprint per kilogram of produce to 0.38 litres — well below "
                "industry average of 0.6 litres.</p>"
            ),
            "cat": "Sustainability", "featured": 0, "pub": 1, "age": 19, "aid": None,
        },
        {
            "title":   "Q2 Market Outlook: Premium Berry Demand Surges in Metro Markets",
            "slug":    "q2-2025-market-outlook-fresh-berry-demand",
            "content": (
                "<p>Consumer demand for premium fresh berries in major metro markets continues to outrun supply. "
                "Our B2B order data shows a 31% increase in weekly volume from retail chain accounts, with QSR "
                "accounts growing fastest at 45% YoY — driven by menu innovations featuring acai bowls, berry "
                "smoothies, and fresh fruit desserts.</p>"
                "<p>D2C channels via instant-commerce platforms (Zepto, Swiggy Instamart, Blinkit) are generating "
                "the most interesting growth story this quarter. Average basket size on our Zepto storefront reached "
                "$28 — driven by 25–34-year-old health-conscious shoppers and repeat purchase rates of 62%.</p>"
                "<p>Price outlook: blueberry spot prices remain firm at $9.50–$10.50/kg due to supply constraints "
                "in Chile. Strawberry markets are softening slightly as tunnel production peaks. Our contracted "
                "pricing model shields network farms from the downside.</p>"
            ),
            "cat": "Market Insights", "featured": 0, "pub": 1, "age": 24, "aid": None,
        },
        {
            "title":   "Cold Storage Expansion: 480MT New Capacity Now Operational",
            "slug":    "cold-storage-sector-7-expansion-operational",
            "content": (
                "<p>Our second cold storage facility at Sector 7 is now fully operational, bringing total "
                "refrigerated capacity to 1,240 MT. The new facility runs four independently controlled chambers "
                "at -1°C to +2°C, each fitted with dual-redundant temperature probes feeding into our IoT "
                "monitoring dashboard with 15-minute breach alerts.</p>"
                "<p>The expansion was driven by an 85% utilisation rate at our original facility during peak "
                "harvest weeks — we were turning down procurement offers due to storage constraints. With "
                "additional capacity, we've brought on two new B2B accounts and increased our average hold "
                "time before distribution from 2.1 to 3.8 days, giving more flexibility for aggregating "
                "smaller farm lots into full pallets.</p>"
            ),
            "cat": "Cold Chain & Logistics", "featured": 1, "pub": 1, "age": 31, "aid": author2_id,
        },
        {
            "title":   "Soil Health Deep Dive: The Mycorrhizal Revolution on Blueberry Farms",
            "slug":    "mycorrhizal-fungi-blueberry-farm-soil-health",
            "content": (
                "<p>Mycorrhizal fungi form symbiotic relationships with plant roots, effectively extending "
                "their nutrient-absorbing reach by up to 100x. Our three-year trial program — run across "
                "7 partner farms with the University of Western Sydney — has demonstrated a 28% reduction "
                "in synthetic fertiliser requirements while maintaining or exceeding yield targets.</p>"
                "<p>Soil organic matter across trial farms increased from an average of 1.8% to 3.2% over "
                "the trial period. Water retention improved significantly — trial farms required 22% fewer "
                "irrigation events during the 2024 dry spell compared to control farms.</p>"
                "<p>We're rolling the inoculation program out to all 15 network farms this season, using "
                "locally propagated Rhizophagus irregularis strains. Input cost is approximately $340/ha "
                "for the initial application, with a projected payback period of 18 months.</p>"
            ),
            "cat": "Crop Science", "featured": 0, "pub": 1, "age": 38, "aid": None,
        },
        {
            "title":   "2024 ESG Report: Carbon Milestones and What Comes Next",
            "slug":    "esg-report-2024-carbon-sequestration-milestones",
            "content": (
                "<p>Our 2024 ESG report is finalised — and the headline numbers are strong. Carbon sequestered "
                "across the farm network reached 847 tonnes CO₂e, against a 2022 baseline of 312 tonnes. "
                "The increase reflects both network growth (new farms) and improved per-hectare sequestration "
                "from cover-cropping and biochar application programs.</p>"
                "<p>On the supply chain side, our refrigeration fleet achieved a 14% reduction in diesel "
                "consumption through route optimisation software and driver eco-driving training. Cold storage "
                "electricity intensity fell 11% following LED and insulation upgrades at both facilities.</p>"
                "<p>For 2025, our focus areas are Scope 3 emissions measurement across the farm network, "
                "packaging transition to compostable materials (targeting 60% by Q4), and formalising our "
                "Fair Farm Charter with minimum wage and housing standards for seasonal labour.</p>"
            ),
            "cat": "Sustainability", "featured": 1, "pub": 1, "age": 45, "aid": None,
        },
        {
            "title":   "Driver Telematics: How Real-Time Data Cuts Cold-Chain Breaches",
            "slug":    "driver-telematics-cold-chain-breach-reduction",
            "content": (
                "<p>Cold-chain breaches cost the fresh produce industry an estimated $1,800 per incident in "
                "writeoffs, redelivery costs, and customer penalties. Last year we trialled in-cab telematics "
                "across 4 refrigerated vehicles — correlating door-open events, driver behaviour, and cargo "
                "temperature logs to identify the highest-risk breach scenarios.</p>"
                "<p>Results: 73% of breaches occurred during loading/unloading at retail DCs where drivers "
                "waited with doors open for more than 8 minutes. Fitting door-open timers with an audible "
                "alert cut loading breaches by 68% in 3 months. We've since rolled out to all 9 vehicles.</p>"
            ),
            "cat": "Cold Chain & Logistics", "featured": 0, "pub": 1, "age": 55, "aid": author2_id,
        },
        {
            "title":   "Partner Farm Spotlight: Sunrise Berry Farm's Tunnel Expansion",
            "slug":    "partner-spotlight-sunrise-berry-farm-tunnel-expansion",
            "content": (
                "<p>Sunrise Berry Farm, one of our founding network partners, has completed a 3.2-hectare "
                "tunnel expansion funded through our input co-investment program. The new tunnels extend "
                "the productive season by 6 weeks at each end, enabling earlier spring harvest and later "
                "autumn crops that command a significant price premium.</p>"
                "<p>Farm owner David Chen: 'The program gave us access to infrastructure we couldn't have "
                "funded alone. The first-right-of-harvest arrangement is fair — Green Valley takes the "
                "crop at a guaranteed floor price, so we carry far less market risk than we did selling "
                "at auction.'</p>"
            ),
            "cat": "Farm Updates", "featured": 0, "pub": 1, "age": 62, "aid": None,
        },
        {
            "title":   "Introducing Our Regenerative Certification Pathway",
            "slug":    "regenerative-certification-pathway-2025",
            "content": (
                "<p>We're launching a formal Regenerative Certification Pathway for network farms in 2025 — "
                "a structured 3-year program covering soil biology, biodiversity corridors, water management, "
                "and animal welfare. Certified farms will carry the Green Valley Regenerative badge and access "
                "a $0.80/kg price premium on qualifying produce.</p>"
                "<p>The first cohort of 5 farms begins audits in March. Full program details available on "
                "request from our agronomy team.</p>"
            ),
            "cat": "Sustainability", "featured": 0, "pub": 0, "age": 1, "aid": None,
        },
    ]

    for p in posts:
        aid = p["aid"] or author_id
        cid = cat_ids.get(p["cat"])
        scalar("""
            INSERT INTO blog
              (BusinessID, Title, Slug, Content, CustomCatID, AuthorID,
               IsPublished, IsFeatured, ShowOnDirectory, ShowOnWebsite,
               CreatedAt, UpdatedAt, PublishedAt)
            OUTPUT INSERTED.BlogID
            VALUES (:b, :title, :slug, :content, :cid, :aid,
                    :pub, :feat, 1, 1, :cat, :cat, :pat)
        """, {
            "b": BID, "title": p["title"], "slug": p["slug"],
            "content": p["content"], "cid": cid, "aid": aid,
            "pub": p["pub"], "feat": p["featured"],
            "cat": dt(p["age"]),
            "pat": dt(p["age"]) if p["pub"] else None,
        })
    db.commit()
    ok(f"10 posts, 5 categories, 2 authors")
except Exception as e:
    db.rollback()
    skip("Blog", e)


# ═══════════════════════════════════════════════════════════════════════════
# 2.  PRECISION AG
# ═══════════════════════════════════════════════════════════════════════════
section("2. Precision Ag")

try:
    fields_data = [
        {"n": "North Paddock — Blueberry Block A",   "crop": "Blueberry",   "ha": 4.2, "lat": -33.8412, "lon": 151.2093},
        {"n": "South Ridge — Strawberry Tunnels",     "crop": "Strawberry",  "ha": 1.8, "lat": -33.8451, "lon": 151.2134},
        {"n": "East Hill — Raspberry Plot",           "crop": "Raspberry",   "ha": 2.6, "lat": -33.8389, "lon": 151.2167},
        {"n": "Orchard Lane — Stone Fruit Block",     "crop": "Peach",       "ha": 3.1, "lat": -33.8467, "lon": 151.2052},
        {"n": "Valley Floor — Mixed Salad Greens",    "crop": "Spinach",     "ha": 1.4, "lat": -33.8502, "lon": 151.2089},
        {"n": "West Block — Blueberry Expansion B",  "crop": "Blueberry",   "ha": 2.9, "lat": -33.8431, "lon": 151.2041},
    ]
    total_analyses = 0
    for f in fields_data:
        fid = scalar("""
            INSERT INTO Field
              (BusinessID, Name, Address, CropType, FieldSizeHectares, Latitude, Longitude,
               MonitoringEnabled, MonitoringIntervalDays, AlertThresholdHealth, CreatedAt)
            OUTPUT INSERTED.FieldID
            VALUES (:b, :n, :addr, :crop, :ha, :lat, :lon, 1, 5, 50, GETDATE())
        """, {"b": BID, "n": f["n"], "addr": "Farm Road, Penrith NSW 2750",
              "crop": f["crop"], "ha": f["ha"], "lat": f["lat"], "lon": f["lon"]})
        # 6 biomass snapshots per field, one per month for 6 months
        base_biomass = random.uniform(4000, 7000)
        for i in range(6):
            # Simulate seasonal trend
            trend = base_biomass * (1 + 0.04 * (3 - abs(i - 3)))
            biomass = round(trend + random.uniform(-300, 300), 1)
            run("""
                INSERT INTO FieldBiomassAnalysis
                  (FieldID, BusinessID, Source, BiomassKgHa, Confidence, CapturedAt, ModelVersion, CreatedAt)
                VALUES (:fid, :b, 'satellite', :bio, :conf, :cap, 'v2.3', GETDATE())
            """, {"fid": fid, "b": BID, "bio": biomass,
                  "conf": round(random.uniform(0.79, 0.97), 2),
                  "cap": dt(30 * i + random.randint(0, 10))})
            total_analyses += 1
    db.commit()
    ok(f"6 fields, {total_analyses} biomass analyses")
except Exception as e:
    db.rollback()
    skip("Precision Ag", e)


# ═══════════════════════════════════════════════════════════════════════════
# 3.  WEBSITE
# ═══════════════════════════════════════════════════════════════════════════
section("3. My Website")

try:
    site_id = scalar("""
        INSERT INTO BusinessWebsite
          (BusinessID, SiteName, Slug, Tagline,
           PrimaryColor, SecondaryColor, AccentColor, BgColor,
           FontFamily, IsPublished, CreatedAt, UpdatedAt)
        OUTPUT INSERTED.WebsiteID
        VALUES (:b, 'Green Valley Farm Network',
                :slug, 'Farm-fresh produce — direct from field to your door.',
                '#3D6B34','#819360','#FFC567','#FFFFFF',
                'Lora, serif', 1, GETDATE(), GETDATE())
    """, {"b": BID, "slug": f"green-valley-{BID}"})
    db.commit()

    pages = [
        {"name": "Home",         "slug": "home",     "home": 1, "order": 0,
         "blocks": [
             ("hero", {"heading": "Farm-Fresh Berries, Direct to You",
                       "subheading": "Premium produce from certified partner farms. Residue-free. Cold-chain guaranteed.",
                       "buttonText": "Shop Our Range", "buttonLink": "/produce",
                       "bgImage": "https://images.unsplash.com/photo-1464965911861-746a04b4bca6?w=1600"}),
             ("features", {"items": [
                 {"icon": "🫐", "title": "Residue-Free Certified", "body": "Every batch tested before leaving the farm."},
                 {"icon": "❄️", "title": "Cold-Chain Guaranteed",  "body": "IoT-monitored from harvest to your door."},
                 {"icon": "🌱", "title": "Regenerative Farms",     "body": "Partner farms meet our strict sustainability charter."},
                 {"icon": "🚚", "title": "6-Hour Farm to Shelf",   "body": "Same-day delivery from farm gate to metro DCs."},
             ]}),
             ("stats", {"items": [
                 {"value": "15+",   "label": "Partner Farms"},
                 {"value": "249 T", "label": "Produce This Season"},
                 {"value": "6 hr",  "label": "Farm to Shelf"},
                 {"value": "100%",  "label": "Residue-Free Certified"},
             ]}),
             ("cta", {"heading": "Ready to stock premium Australian berries?",
                      "body": "Contact our B2B sales team for wholesale pricing and account setup.",
                      "buttonText": "Get in Touch", "buttonLink": "/contact"}),
         ]},
        {"name": "About Us",     "slug": "about",    "home": 0, "order": 1,
         "blocks": [
             ("richtext", {"html": "<h2>Who We Are</h2><p>Green Valley Farm Network is a direct-procurement aggregator connecting premium berry and produce farms with retail chains, restaurants, and health-conscious consumers across eastern Australia. Founded in 2019, we manage the entire supply chain from sapling distribution to last-mile cold-chain delivery.</p><p>Our model is simple: we sign farms onto long-term first-right-of-harvest agreements, often co-investing in infrastructure like tunnel nets and drip irrigation. In return, farms receive guaranteed floor pricing, input support, and access to markets they couldn't reach independently.</p>"}),
             ("team", {"members": [
                 {"name": "Sarah Mitchell",  "role": "Head of Agronomy",         "bio": "12 years in sustainable berry cultivation and precision irrigation design."},
                 {"name": "James Okonkwo",   "role": "Logistics Director",       "bio": "Former cold-chain specialist; 15 years managing temperature-controlled freight."},
                 {"name": "Priya Nair",      "role": "B2B Sales Manager",        "bio": "Manages 8+ retail chain and restaurant accounts across NSW and VIC."},
                 {"name": "Tom Fitzgerald",  "role": "Farm Partnerships Lead",   "bio": "Recruits and onboards new partner farms; manages input co-investment program."},
             ]}),
             ("richtext", {"html": "<h2>Our Certifications</h2><ul><li>Residue-Free — all produce</li><li>HACCP certified cold storage facilities</li><li>GlobalG.A.P. — 9 of 15 partner farms</li><li>Organic — 4 of 15 partner farms (ACO certified)</li></ul>"}),
         ]},
        {"name": "Our Produce",  "slug": "produce",  "home": 0, "order": 2,
         "blocks": [
             ("richtext", {"html": "<h2>What We Grow</h2><p>All produce is harvested to order, residue-tested, and dispatched within 6 hours. Available for B2B wholesale and D2C delivery via our app and instant-commerce partners.</p>"}),
             ("products", {"categoryFilter": "all", "showPrices": True, "columns": 3}),
             ("richtext", {"html": "<h3>B2B Minimum Orders</h3><p>Blueberries: 20kg minimum | Strawberries: 10kg minimum | Mixed berries: 15kg minimum. <a href='/contact'>Contact us</a> for custom pallet pricing on orders over 200kg.</p>"}),
         ]},
        {"name": "Blog",         "slug": "blog",     "home": 0, "order": 3,
         "blocks": [
             ("richtext", {"html": "<h2>Farm Journal</h2><p>Agronomy updates, market insights, sustainability milestones, and stories from our partner farms.</p>"}),
             ("blog_list", {"postsPerPage": 6, "showFeatured": True, "showCategories": True}),
         ]},
        {"name": "Contact",      "slug": "contact",  "home": 0, "order": 4,
         "blocks": [
             ("richtext", {"html": "<h2>Get in Touch</h2><p>For B2B wholesale enquiries, farm partnership opportunities, or press, please use the form or reach us directly.</p><p><strong>Trade enquiries:</strong> <a href='mailto:trade@greenvalleyfarms.com.au'>trade@greenvalleyfarms.com.au</a><br/><strong>Phone:</strong> +61 2 9876 5432<br/><strong>Address:</strong> Suite 4, 88 Farm Road, Penrith NSW 2750</p>"}),
             ("contact_form", {"fields": ["name", "email", "phone", "company", "message"],
                               "submitLabel": "Send Enquiry",
                               "successMessage": "Thanks! Our team will be in touch within one business day."}),
             ("map", {"lat": -33.751, "lon": 150.694, "zoom": 13,
                      "label": "Green Valley Farm Network — Penrith NSW"}),
         ]},
    ]

    total_blocks = 0
    for pg in pages:
        page_id = scalar("""
            INSERT INTO BusinessWebPage
              (WebsiteID, BusinessID, PageName, Slug, PageTitle,
               SortOrder, IsPublished, IsHomePage, CreatedAt, UpdatedAt)
            OUTPUT INSERTED.PageID
            VALUES (:sid, :b, :name, :slug, :title, :order, 1, :home, GETDATE(), GETDATE())
        """, {"sid": site_id, "b": BID, "name": pg["name"], "slug": pg["slug"],
              "title": f"{pg['name']} — Green Valley Farm Network",
              "order": pg["order"], "home": pg["home"]})
        for i, (btype, bdata) in enumerate(pg["blocks"]):
            run("""
                INSERT INTO BusinessWebBlock
                  (PageID, BlockType, BlockData, SortOrder, CreatedAt, UpdatedAt)
                VALUES (:pid, :btype, :bdata, :order, GETDATE(), GETDATE())
            """, {"pid": page_id, "btype": btype,
                  "bdata": json.dumps(bdata), "order": i})
            total_blocks += 1
    db.commit()
    ok(f"1 website, 5 pages, {total_blocks} content blocks")
except Exception as e:
    db.rollback()
    skip("Website", e)


# ═══════════════════════════════════════════════════════════════════════════
# 4.  ACCOUNTING
# ═══════════════════════════════════════════════════════════════════════════
section("4. Accounting")

# 4a. Chart of accounts (idempotent stored procedure)
try:
    run("EXEC CreateDefaultChartOfAccounts @BusinessID = :b", {"b": BID})
    db.commit()
    ok("Chart of accounts initialised")
except Exception as e:
    db.rollback()
    ok(f"COA already exists or SP unavailable: {e}")

# 4b. Fiscal year + periods
try:
    if not scalar("SELECT COUNT(*) FROM FiscalYears WHERE BusinessID=:b", {"b": BID}):
        fy_id = scalar("""
            INSERT INTO FiscalYears (BusinessID, YearName, StartDate, EndDate)
            OUTPUT INSERTED.FiscalYearID
            VALUES (:b, 'FY2025', '2025-01-01', '2025-12-31')
        """, {"b": BID})
        mnames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        for m, mn in enumerate(mnames, 1):
            sd = date(2025, m, 1)
            ed = date(2025, m, calendar.monthrange(2025, m)[1])
            run("""
                INSERT INTO FiscalPeriods
                  (FiscalYearID, BusinessID, PeriodNumber, PeriodName, StartDate, EndDate)
                VALUES (:fy, :b, :num, :name, :s, :e)
            """, {"fy": fy_id, "b": BID, "num": m, "name": f"{mn} 2025",
                  "s": sd.isoformat(), "e": ed.isoformat()})
        db.commit()
        ok("FY2025 + 12 periods created")
    else:
        ok("Fiscal year already exists")
except Exception as e:
    db.rollback()
    skip("Fiscal year", e)

# Fetch account IDs for lines
def get_acct(pattern):
    row = fetchone(
        "SELECT TOP 1 AccountID FROM Accounts WHERE BusinessID=:b "
        f"AND AccountNumber LIKE '{pattern}' AND IsActive=1 ORDER BY AccountNumber",
        {"b": BID})
    return row.AccountID if row else None

rev_id   = get_acct('4%')
cogs_id  = get_acct('5%')
exp_id   = get_acct('6%')
cash_id  = get_acct('1%')  # asset / cash account for expenses

# 4c. Customers
try:
    customers = [
        {"DisplayName": "Reliance Retail Ltd",       "Company": "Reliance Retail Ltd",        "Email": "orders@relianceretail.in",    "Phone": "+91 22 3456 7890", "Terms": "Net30"},
        {"DisplayName": "The Bombay Canteen",         "Company": "The Bombay Canteen Pvt Ltd", "Email": "kitchen@bombaycanteen.com",    "Phone": "+91 22 2634 0000", "Terms": "Net14"},
        {"DisplayName": "Star Bazaar Distribution",   "Company": "Star Bazaar",                "Email": "produce@starbazaar.com",       "Phone": "+91 22 6655 4400", "Terms": "Net30"},
        {"DisplayName": "Blue Apron Fresh Co.",       "Company": "Blue Apron Fresh",           "Email": "buying@blueapronfresh.com",    "Phone": "+1 646 555 0182",  "Terms": "Net21"},
        {"DisplayName": "Metro Supermarkets",         "Company": "Metro Cash & Carry India",   "Email": "trade@metro.in",              "Phone": "+91 80 4567 1234", "Terms": "Net45"},
        {"DisplayName": "Harris Farm Markets",        "Company": "Harris Farm Markets Pty Ltd","Email": "produce@harrisfarm.com.au",    "Phone": "+61 2 9557 4100", "Terms": "Net30"},
        {"DisplayName": "Aldi Buying Group AU",       "Company": "Aldi Stores Australia",      "Email": "fresh@aldi.com.au",           "Phone": "+61 2 8065 0800", "Terms": "Net14"},
    ]
    cust_ids = []
    for c in customers:
        cid = scalar("""
            INSERT INTO AccountingCustomers
              (BusinessID, DisplayName, CompanyName, Email, Phone, PaymentTerms)
            OUTPUT INSERTED.CustomerID
            VALUES (:b, :dn, :co, :em, :ph, :pt)
        """, {"b": BID, "dn": c["DisplayName"], "co": c["Company"],
              "em": c["Email"], "ph": c["Phone"], "pt": c["Terms"]})
        cust_ids.append(cid)
    db.commit()
    ok(f"{len(customers)} customers")
except Exception as e:
    db.rollback()
    cust_ids = []
    skip("Customers", e)

# 4d. Vendors
try:
    vendors = [
        {"DisplayName": "Sunrise Berry Farm",     "Company": "Sunrise Berry Farm",       "Email": "accounts@sunriseberry.com.au",  "Phone": "+61 3 5567 1234", "Is1099": 1},
        {"DisplayName": "Green Hill Orchards",    "Company": "Green Hill Orchards",      "Email": "ops@greenhillorchards.com.au",  "Phone": "+61 3 5678 9012", "Is1099": 1},
        {"DisplayName": "Valley Fresh Farms",     "Company": "Valley Fresh Farms",       "Email": "finance@valleyfresh.com.au",    "Phone": "+61 3 5789 0123", "Is1099": 1},
        {"DisplayName": "Blue Ridge Berry Co.",   "Company": "Blue Ridge Berry Co.",     "Email": "sales@blueridgeberry.com.au",   "Phone": "+61 3 5890 1234", "Is1099": 1},
        {"DisplayName": "Hawkesbury Orchards",    "Company": "Hawkesbury Orchards",      "Email": "billing@hawkesburyorch.com.au", "Phone": "+61 2 4578 9012", "Is1099": 1},
        {"DisplayName": "CoolStore Logistics",    "Company": "CoolStore Logistics",      "Email": "billing@coolstore.com.au",      "Phone": "+61 2 9234 5678", "Is1099": 0},
        {"DisplayName": "AgriSupply Co.",         "Company": "AgriSupply Co Pty Ltd",    "Email": "accounts@agrisupply.com.au",    "Phone": "+61 2 8765 4321", "Is1099": 0},
        {"DisplayName": "Origin Energy Aus",      "Company": "Origin Energy",            "Email": "commercial@originenergy.com.au","Phone": "+61 2 8345 5000", "Is1099": 0},
    ]
    vendor_ids = []
    for v in vendors:
        vid = scalar("""
            INSERT INTO AccountingVendors
              (BusinessID, DisplayName, CompanyName, Email, Phone, PaymentTerms, Is1099)
            OUTPUT INSERTED.VendorID
            VALUES (:b, :dn, :co, :em, :ph, 'Net30', :i1099)
        """, {"b": BID, "dn": v["DisplayName"], "co": v["Company"],
              "em": v["Email"], "ph": v["Phone"], "i1099": v["Is1099"]})
        vendor_ids.append(vid)
    db.commit()
    ok(f"{len(vendors)} vendors")
except Exception as e:
    db.rollback()
    vendor_ids = []
    skip("Vendors", e)

# 4e. Invoices
try:
    invoice_specs = [
        (0, 18450.00, "Paid",    45, 30, "Blueberry",      2050, 9.00),
        (1,  7200.00, "Paid",    38, 14, "Strawberry",      900, 8.00),
        (2, 24600.00, "Sent",    20, 30, "Blueberry",      2460, 10.00),
        (3, 11250.00, "Partial", 15, 21, "Raspberry",      1250, 9.00),
        (4, 31500.00, "Sent",     8, 45, "Mixed Produce",  3500, 9.00),
        (5, 15800.00, "Sent",    12, 30, "Blueberry",      1580, 10.00),
        (6,  9600.00, "Overdue", 50, 30, "Strawberry",     1200, 8.00),
        (0, 22400.00, "Paid",    65, 30, "Blueberry",      2240, 10.00),
    ]
    inv_count = 0
    for i, (ci, total, status, age, terms, crop, qty, ppk) in enumerate(invoice_specs):
        if not cust_ids: break
        cid      = cust_ids[ci % len(cust_ids)]
        inv_date = d(age)
        due_date = d(age - terms)
        inv_num  = f"INV-{25000 + i + 1}"
        bal      = 0 if status == "Paid" else (total * 0.5 if status == "Partial" else total)
        inv_id = scalar("""
            INSERT INTO Invoices
              (BusinessID, CustomerID, InvoiceNumber, InvoiceDate, DueDate,
               Status, SubTotal, TaxAmount, TotalAmount, BalanceDue, PaymentTerms, Notes, CreatedBy)
            OUTPUT INSERTED.InvoiceID
            VALUES (:b, :cid, :num, :id, :dd, :st, :tot, 0, :tot, :bal, :pt, :notes, 1)
        """, {"b": BID, "cid": cid, "num": inv_num, "id": inv_date, "dd": due_date,
              "st": status, "tot": total, "bal": bal,
              "pt": f"Net{terms}", "notes": f"B2B sale — {crop}"})
        if rev_id:
            run("""
                INSERT INTO InvoiceLines
                  (InvoiceID, BusinessID, AccountID, Description,
                   Quantity, UnitPrice, TaxAmount, LineTotal, LineOrder)
                VALUES (:inv, :b, :acct, :desc, :qty, :ppk, 0, :tot, 1)
            """, {"inv": inv_id, "b": BID, "acct": rev_id,
                  "desc": f"{crop} — {qty} kg @ ${ppk:.2f}/kg",
                  "qty": qty, "ppk": ppk, "tot": total})
        inv_count += 1
    db.commit()
    ok(f"{inv_count} invoices with lines")
except Exception as e:
    db.rollback()
    skip("Invoices", e)

# 4f. Bills
try:
    bill_specs = [
        (0, 41200.00, "Paid", 40, "Blueberry",  5150, 8.00),
        (1, 28350.00, "Paid", 32, "Strawberry", 4050, 7.00),
        (2, 19800.00, "Open", 18, "Raspberry",  2475, 8.00),
        (3, 22100.00, "Open", 10, "Blueberry",  2762, 8.00),
        (4, 16900.00, "Open",  5, "Mixed",      2113, 8.00),
        (5,  8400.00, "Open", 12, "Logistics",    84, 100.00),
        (6,  6200.00, "Paid", 45, "Supplies",      1, 6200.00),
        (7,  3800.00, "Open",  8, "Electricity",   1, 3800.00),
    ]
    bill_count = 0
    for i, (vi, total, status, age, category, qty, ppk) in enumerate(bill_specs):
        if not vendor_ids: break
        vid       = vendor_ids[vi % len(vendor_ids)]
        bill_date = d(age)
        due_date  = d(age - 30)
        bill_num  = f"BILL-{25000 + i + 1}"
        bal       = 0 if status == "Paid" else total
        bill_id = scalar("""
            INSERT INTO Bills
              (BusinessID, VendorID, BillNumber, BillDate, DueDate,
               Status, SubTotal, TaxAmount, TotalAmount, BalanceDue, Notes, CreatedBy)
            OUTPUT INSERTED.BillID
            VALUES (:b, :vid, :num, :bd, :dd, :st, :tot, 0, :tot, :bal, :notes, 1)
        """, {"b": BID, "vid": vid, "num": bill_num, "bd": bill_date, "dd": due_date,
              "st": status, "tot": total, "bal": bal,
              "notes": f"Purchase — {category}"})
        acct_line = cogs_id if category not in ("Logistics", "Supplies", "Electricity") else exp_id
        if acct_line:
            run("""
                INSERT INTO BillLines
                  (BillID, BusinessID, AccountID, Description,
                   Quantity, UnitPrice, TaxAmount, LineTotal, LineOrder)
                VALUES (:bill, :b, :acct, :desc, :qty, :ppk, 0, :tot, 1)
            """, {"bill": bill_id, "b": BID, "acct": acct_line,
                  "desc": f"{category} — {qty} units @ ${ppk:.2f}",
                  "qty": qty, "ppk": ppk, "tot": total})
        bill_count += 1
    db.commit()
    ok(f"{bill_count} bills with lines")
except Exception as e:
    db.rollback()
    skip("Bills", e)

# 4g. Expenses
try:
    if exp_id and cash_id and vendor_ids:
        expenses = [
            (vendor_ids[5], 2400.00,  d(35), "bank_transfer",  "Cold storage electricity — March 2025"),
            (vendor_ids[5], 2380.00,  d(5),  "bank_transfer",  "Cold storage electricity — April 2025"),
            (vendor_ids[6], 1850.00,  d(28), "bank_transfer",  "Fleet refrigerated van maintenance — 4 vehicles"),
            (vendor_ids[6],  950.00,  d(15), "credit_card",    "AgriSoft precision ag platform — monthly sub"),
            (vendor_ids[6], 3200.00,  d(22), "bank_transfer",  "Staff food safety certification training"),
            (vendor_ids[6],  620.00,  d(8),  "credit_card",    "Office supplies and administration"),
            (vendor_ids[5], 4100.00,  d(60), "bank_transfer",  "Cold storage electricity — February 2025"),
        ]
        exp_count = 0
        for vid, amt, edate, method, desc in expenses:
            exp_id_row = scalar("""
                INSERT INTO Expenses
                  (BusinessID, VendorID, PaymentAccountID, ExpenseDate, PaymentMethod,
                   TotalAmount, Notes, CreatedBy)
                OUTPUT INSERTED.ExpenseID
                VALUES (:b, :vid, :pacct, :edate, :method, :amt, :desc, 1)
            """, {"b": BID, "vid": vid, "pacct": cash_id, "edate": edate,
                  "method": method, "amt": amt, "desc": desc})
            # Expense line
            run("""
                INSERT INTO ExpenseLines
                  (ExpenseID, BusinessID, AccountID, Description, Amount, IsBillable, LineOrder)
                VALUES (:eid, :b, :acct, :desc, :amt, 0, 1)
            """, {"eid": exp_id_row, "b": BID, "acct": exp_id,
                  "desc": desc, "amt": amt})
            exp_count += 1
        db.commit()
        ok(f"{exp_count} expenses with lines")
    else:
        ok("Expenses skipped (accounts not found)")
except Exception as e:
    db.rollback()
    skip("Expenses", e)


# ═══════════════════════════════════════════════════════════════════════════
# 5.  MARKETPLACE PRODUCTS
# ═══════════════════════════════════════════════════════════════════════════
section("5. Marketplace Products")

try:
    products = [
        ("Premium Blueberries — 1kg Punnet",       "Fresh Berries",  12.50, 8.50,  1, 1, 1),
        ("Fresh Strawberries — 500g",               "Fresh Berries",   6.90, 4.20,  1, 1, 1),
        ("Mixed Berry Box — 2kg Assorted",          "Fresh Berries",  28.00, 18.50, 1, 1, 1),
        ("Raspberries — 250g",                      "Fresh Berries",   7.50, 5.00,  1, 0, 0),
        ("Blueberries — 5kg Wholesale Box",         "Fresh Berries",  52.00, 38.00, 1, 1, 0),
        ("Baby Spinach — 500g",                     "Salad Leaves",    4.50, 2.80,  1, 0, 1),
        ("Rocket Lettuce Mix — 200g",               "Salad Leaves",    3.90, 2.40,  1, 0, 1),
        ("Cherry Tomatoes — 400g",                  "Tomatoes",        4.20, 2.60,  1, 0, 0),
        ("Heirloom Tomato Medley — 600g",           "Tomatoes",        8.90, 5.50,  1, 1, 1),
        ("Peaches — 1kg",                           "Stone Fruit",     7.50, 4.80,  1, 0, 0),
        ("Nectarines — 1kg",                        "Stone Fruit",     7.00, 4.50,  1, 0, 0),
        ("Blueberry Jam — 300g Artisan",            "Preserves",      11.00, 6.80,  1, 0, 1),
        ("Mixed Berry Compote — 250g",              "Preserves",       9.50, 5.90,  0, 0, 1),
        ("Organic Blueberry Powder — 250g",         "Health Foods",   22.00, 14.00, 1, 1, 1),
        ("Freeze-Dried Strawberry Slices — 80g",    "Health Foods",   14.50, 9.00,  1, 0, 1),
    ]
    for title, cat, price, wprice, active, feat, organic in products:
        run("""
            INSERT INTO MarketplaceProducts
              (BusinessID, Title, CategoryName, UnitPrice, WholesalePrice, UnitLabel,
               QuantityAvailable, MinOrderQuantity, IsActive, IsFeatured, IsOrganic,
               DeliveryOptions, CreatedAt, UpdatedAt)
            VALUES (:b, :t, :cat, :p, :wp, 'unit', :qty, 1, :act, :feat, :org,
                    'pickup,delivery', GETDATE(), GETDATE())
        """, {"b": BID, "t": title, "cat": cat, "p": price, "wp": wprice,
              "qty": random.randint(20, 250),
              "act": active, "feat": feat, "org": organic})
    db.commit()
    ok(f"{len(products)} marketplace products")
except Exception as e:
    db.rollback()
    skip("Marketplace", e)


# ═══════════════════════════════════════════════════════════════════════════
# 6.  PRODUCE INVENTORY
# ═══════════════════════════════════════════════════════════════════════════
section("6. Produce Inventory")

try:
    ing_rows = fetchall("""
        SELECT TOP 10 i.IngredientID, i.IngredientName
        FROM Ingredients i
        JOIN IngredientCategoryLookup ic ON ic.IngredientCategoryID = i.IngredientCategoryID
        WHERE ic.IngredientCategory NOT LIKE '%Meat%'
          AND ic.IngredientCategory NOT LIKE '%Poultry%'
          AND ic.IngredientCategory NOT LIKE '%Seafood%'
          AND ic.IngredientCategory NOT LIKE '%Fish%'
        ORDER BY NEWID()
    """)
    meas_rows = fetchall("SELECT TOP 3 MeasurementID FROM MeasurementLookup ORDER BY MeasurementOrder")
    if ing_rows and meas_rows:
        meas_id = meas_rows[0].MeasurementID
        for row in ing_rows[:8]:
            run("""
                INSERT INTO Produce
                  (BusinessID, IngredientID, Quantity, MeasurementID,
                   WholesalePrice, RetailPrice, AvailableDate, ShowProduce)
                VALUES (:b, :iid, :qty, :mid, :wp, :rp, :av, 1)
            """, {"b": BID, "iid": row.IngredientID,
                  "qty": round(random.uniform(40, 600), 1), "mid": meas_id,
                  "wp": round(random.uniform(1.50, 9.00), 2),
                  "rp": round(random.uniform(3.50, 16.00), 2),
                  "av": d(0)})
        db.commit()
        ok(f"{min(8, len(ing_rows))} produce items")
    else:
        ok("Skipped (no ingredient lookup data found)")
except Exception as e:
    db.rollback()
    skip("Produce Inventory", e)


# ═══════════════════════════════════════════════════════════════════════════
# 7.  MEAT INVENTORY
# ═══════════════════════════════════════════════════════════════════════════
section("7. Meat Inventory")

try:
    meat_rows = fetchall("""
        SELECT TOP 6 i.IngredientID, i.IngredientName
        FROM Ingredients i
        JOIN IngredientCategoryLookup ic ON ic.IngredientCategoryID = i.IngredientCategoryID
        WHERE ic.IngredientCategory LIKE '%Meat%'
           OR ic.IngredientCategory LIKE '%Beef%'
           OR ic.IngredientCategory LIKE '%Lamb%'
           OR ic.IngredientCategory LIKE '%Pork%'
           OR ic.IngredientCategory LIKE '%Poultry%'
        ORDER BY NEWID()
    """)
    cut_rows = fetchall("SELECT TOP 6 IngredientCutID FROM Cut ORDER BY NEWID()")
    if meat_rows:
        for i, row in enumerate(meat_rows):
            cut_id = cut_rows[i % len(cut_rows)].IngredientCutID if cut_rows else None
            run("""
                INSERT INTO MeatInventory
                  (BusinessID, IngredientID, IngredientCutID, Weight, WeightUnit,
                   Quantity, WholesalePrice, RetailPrice, AvailableDate, ShowMeat)
                VALUES (:b, :iid, :cid, :wt, 'kg', :qty, :wp, :rp, :av, 1)
            """, {"b": BID, "iid": row.IngredientID, "cid": cut_id,
                  "wt": round(random.uniform(0.8, 4.5), 2),
                  "qty": random.randint(8, 60),
                  "wp": round(random.uniform(8.00, 28.00), 2),
                  "rp": round(random.uniform(16.00, 48.00), 2),
                  "av": d(0)})
        db.commit()
        ok(f"{len(meat_rows)} meat inventory items")
    else:
        ok("Skipped (no meat ingredient lookup data found)")
except Exception as e:
    db.rollback()
    skip("Meat Inventory", e)


# ═══════════════════════════════════════════════════════════════════════════
# 8.  PROCESSED FOOD
# ═══════════════════════════════════════════════════════════════════════════
section("8. Processed Food")

try:
    pf_cat = fetchone(
        "SELECT TOP 1 ProcessedFoodCategoryID FROM ProcessedFoodCategoryLookup ORDER BY ProcessedFoodCategoryID")
    if pf_cat:
        pf_items = [
            ("Blueberry & Chia Granola — 400g",           5.80,  12.50),
            ("Mixed Berry Fruit Leather — 5-pack 120g",   4.20,   9.90),
            ("Freeze-Dried Strawberry Slices — 80g",      6.50,  14.00),
            ("Berry Smoothie Packs — 5x frozen 200g",     8.90,  18.00),
            ("Organic Blueberry Powder — 250g",          13.00,  26.50),
            ("Blueberry Jam — 300g Artisan",              5.20,  11.00),
            ("Strawberry Honey Preserve — 280g",          4.90,  10.50),
        ]
        for name, wp, rp in pf_items:
            run("""
                INSERT INTO ProcessedFood
                  (BusinessID, ProcessedFoodCategoryID, Name, Quantity,
                   WholesalePrice, RetailPrice, AvailableDate, ShowProcessedFood)
                VALUES (:b, :cat, :name, :qty, :wp, :rp, :av, 1)
            """, {"b": BID, "cat": pf_cat.ProcessedFoodCategoryID, "name": name,
                  "qty": random.randint(40, 300), "wp": wp, "rp": rp, "av": d(0)})
        db.commit()
        ok(f"{len(pf_items)} processed food items")
    else:
        ok("Skipped (no ProcessedFoodCategoryLookup data)")
except Exception as e:
    db.rollback()
    skip("Processed Food", e)


# ═══════════════════════════════════════════════════════════════════════════
# 9.  SERVICES
# ═══════════════════════════════════════════════════════════════════════════
section("9. Services")

try:
    svc_cat = fetchone("SELECT TOP 1 ServiceCategoryID FROM servicescategories ORDER BY ServiceCategoryID")
    svc_cat_id = svc_cat.ServiceCategoryID if svc_cat else None

    services = [
        ("On-Farm Agronomist Consultancy", 350.00, False,
         "Full-day on-site crop assessment, soil sampling, and personalised improvement plan from our senior agronomist. Written report and 30-day follow-up call included."),
        ("Blueberry Canopy Management Workshop", 180.00, False,
         "Half-day pruning and training workshop for up to 10 farm staff. Covers summer pruning, winter pruning, tipping, and pest identification. Certification issued."),
        ("Cold-Chain Audit & Certification", 750.00, False,
         "Comprehensive assessment of post-harvest handling, temperature monitoring equipment, and SOPs. Includes written audit report and certification suitable for export documentation."),
        ("Precision Ag Data Analysis — Monthly", 420.00, False,
         "Monthly NDVI, biomass, and soil moisture report with actionable intervention recommendations. Delivered as an interactive PDF with field heat maps. Minimum 3-month engagement."),
        ("Farm ESG Assessment & Report", 600.00, False,
         "On-farm sustainability audit covering carbon footprint, water use, biodiversity, and fair labour practices. Audit-ready PDF report included. Recognized by major retail procurement teams."),
        ("Sapling & Input Co-Investment Program", 0.00, True,
         "Enrol in our co-investment program: receive certified disease-free blueberry and strawberry saplings, polypropylene tunnel nets, and drip irrigation kits — in exchange for a first-right-of-harvest agreement over 3 seasons. Contact us for eligibility and terms."),
        ("Residue Testing Service", 280.00, False,
         "Multi-residue LC-MS/MS analysis covering 500+ pesticide actives. Results within 5 business days. Includes a certificate of analysis and export residue clearance letter if passing."),
        ("Custom Cold-Chain Route Optimisation", 0.00, True,
         "We'll analyse your delivery routes and vehicle temperature logs and recommend schedule, load, and equipment changes to reduce breach events and fuel costs. Pricing based on fleet size — contact us."),
    ]
    for title, price, cfp, desc in services:
        run("""
            INSERT INTO Services
              (BusinessID, ServiceCategoryID, ServiceTitle, ServicesDescription,
               ServicePrice, ServiceContactForPrice, ServiceAvailable)
            VALUES (:b, :cat, :title, :desc, :price, :cfp, 1)
        """, {"b": BID, "cat": svc_cat_id, "title": title, "desc": desc,
              "price": price, "cfp": 1 if cfp else 0})
    db.commit()
    ok(f"{len(services)} services")
except Exception as e:
    db.rollback()
    skip("Services", e)


# ═══════════════════════════════════════════════════════════════════════════
# 10.  ANIMALS
# ═══════════════════════════════════════════════════════════════════════════
section("10. Animals")

try:
    species_rows = fetchall("SELECT TOP 6 SpeciesID, SingularTerm FROM SpeciesAvailable ORDER BY SpeciesID")
    if species_rows:
        animals = [
            ("Green Valley Bella",    "Bella",   14, 3,  2022),
            ("Green Valley Apollo",   "Apollo",  22, 7,  2021),
            ("Green Valley Luna",     "Luna",    5,  11, 2022),
            ("Green Valley Titan",    "Titan",   18, 2,  2020),
            ("Green Valley Daisy",    "Daisy",   30, 6,  2023),
            ("Green Valley Storm",    "Storm",   9,  9,  2021),
            ("Green Valley Rose",     "Rose",    21, 4,  2022),
            ("Green Valley Ranger",   "Ranger",  3,  12, 2020),
            ("Green Valley Pearl",    "Pearl",   15, 1,  2023),
            ("Green Valley Blaze",    "Blaze",   28, 8,  2021),
            ("Green Valley Clover",   "Clover",  7,  5,  2022),
            ("Green Valley Thunder",  "Thunder", 12, 10, 2020),
        ]
        for i, (fn, sn, dd, dm, dy) in enumerate(animals):
            sp = species_rows[i % len(species_rows)]
            breed_row = fetchone(
                "SELECT TOP 1 BreedLookupID FROM SpeciesBreedLookupTable WHERE SpeciesID=:sid "
                "AND (breedavailable=1 OR breedavailable IS NULL) ORDER BY NEWID()",
                {"sid": sp.SpeciesID})
            breed_id = breed_row.BreedLookupID if breed_row else None
            run("""
                INSERT INTO animals
                  (BusinessID, SpeciesID, FullName, ShortName, BreedID,
                   DOBday, DOBMonth, DOBYear, NumberofAnimals, Lastupdated)
                VALUES (:b, :sid, :fn, :sn, :brid, :dd, :dm, :dy, 1, GETDATE())
            """, {"b": BID, "sid": sp.SpeciesID, "fn": fn, "sn": sn,
                  "brid": breed_id, "dd": dd, "dm": dm, "dy": dy})
        db.commit()
        ok(f"{len(animals)} animals")
    else:
        ok("Skipped (no species lookup data)")
except Exception as e:
    db.rollback()
    skip("Animals", e)


# ═══════════════════════════════════════════════════════════════════════════
# DONE
# ═══════════════════════════════════════════════════════════════════════════
db.close()
print(f"\n{'='*55}")
print("  Seed complete for BusinessID = 15665")
print(f"{'='*55}\n")
