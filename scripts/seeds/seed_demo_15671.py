"""
Comprehensive demo seed for BusinessID=15671 — Green Valley Farm.
Run from the oatmealfarmnetworkbackend directory:
  ..\venv\Scripts\python.exe seed_demo_15671.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

from database import engine
from sqlalchemy import text
from datetime import date, timedelta

BID = 15671
TODAY = date.today()

def q(conn, sql, params=None):
    return conn.execute(text(sql), params or {})

def section(name):
    print(f"\n[{name}]")

# ── helpers ───────────────────────────────────────────────────────────────────

def ids(conn, sql, params=None):
    """Return list of first-column values."""
    return [r[0] for r in conn.execute(text(sql), params or {}).fetchall()]

def first(conn, sql, params=None):
    row = conn.execute(text(sql), params or {}).fetchone()
    return row[0] if row else None


with engine.begin() as c:

    # ── 1. BLOG ───────────────────────────────────────────────────────────────
    section("blog")
    existing_posts = first(c, "SELECT COUNT(*) FROM blog WHERE BusinessID=:b", {"b": BID})
    if existing_posts == 0:
        posts = [
            ("Preparing Your Fields for Spring: A Step-by-Step Guide",
             "spring-fields-prep",
             "Early spring is the most critical window for soil preparation. At Green Valley Farm we begin our season with a thorough soil test on every field, then work through a disciplined five-step prep sequence before the first seed goes in.\n\n"
             "Step one is drainage inspection. Walk every field perimeter and look for standing water or poorly draining low spots. A wet spring compounds quickly — water-logged soil destroys soil structure, delays planting, and sets you back four to six weeks.\n\n"
             "Step two is cover crop termination. We planted cereal rye at 60 lbs/acre last October. By early April it's at 12–18 inches and we roll-crimp it flat. Thirty days later the residue has broken down enough to transplant into without nitrogen tie-up.\n\n"
             "Step three is lime application. Our sandy loam soils drift acid over winter. We target pH 6.4 for brassicas and 6.8 for corn ground. Apply now so three months of rain can work it into the profile before planting.\n\n"
             "Step four is pre-plant fertilizer. We inject 4 gallons per acre of fish emulsion (4-2-2) at transplanting. For our heavier feeders — brassicas, squash — we band compost at 2 tons/acre before bedding.\n\n"
             "Step five is bed formation. We use a BCS walk-behind with a bed former for our market garden and a three-point power ridger for field-scale rows. Consistent 30-inch centers keep our cultivation tractor straddling without guesswork."),

            ("Why We Switched to Regenerative Grazing — And What Changed",
             "regenerative-grazing-results",
             "Three years ago our pastures looked like every other farm in the county: overgrazed, weedy, with bare patches spreading every dry summer. We made the decision to move to a full rotational system and the results have been dramatic enough that we want to share the numbers.\n\n"
             "Year one: We divided our 80 acres of pasture into 12 paddocks using temporary electric fence. Rest periods averaged 42 days. Forage dry matter yield measured by rising plate meter increased 18% over the prior year's same-period estimate.\n\n"
             "Year two: We added a water system with a central pump and frost-free nose pumps in each paddock. Cattle no longer had to walk to a single corner waterer — animal performance improved and soil compaction near the old waterer began recovering. Soil organic matter readings (sent to a lab at the same time of year) went from 2.1% to 2.7%.\n\n"
             "Year three (current): We're running 12% more animal units on the same acreage with better body condition scores going into winter. We've eliminated 100% of our herbicide applications — the rest periods and dense sward simply outcompete the weeds. Our vet bill dropped 22% compared to our three-year average before the transition.\n\n"
             "The hardest part was the discipline of moving cattle every 4–6 days instead of letting them stay until the paddock was eaten down to dirt. That muscle memory took one full season to build."),

            ("Our CSA Model: How We Price Shares and What Members Actually Get",
             "csa-model-pricing",
             "We run two CSA tracks: a Full Share designed for families of four, and a Half Share for couples or single-person households. Both run 22 weeks from May through October.\n\n"
             "Full Share pricing: $620 for the season, paid upfront, or $290 per half-season. Members receive a box averaging 12–14 items each week. In peak summer that means corn, tomatoes, zucchini, cucumbers, basil, peppers, green beans, eggplant, and whatever specialty items are at their peak. Early and late season the box shifts to storage crops, greens, and root vegetables.\n\n"
             "Half Share: $340 for the season. Same diversity but roughly 60% of the volume — good for households that supplement at the farmers market or don't cook every night.\n\n"
             "Add-ons: Members can add a flower share ($8/week), an egg share (one dozen per week, $7), or a honey jar bi-weekly ($12 per jar). About 40% of our members take at least one add-on.\n\n"
             "How we plan the box: Every Thursday we walk every field and measure what's ready. On Friday morning we build the box list based on availability, trying to hit a balanced mix of items most members will use immediately versus items that store for a week. We write the week's growing notes in our member newsletter — what pest pressure we're seeing, what's coming in two weeks, recipe suggestions for the harder-to-use items like kohlrabi.\n\n"
             "Member retention: We currently retain 81% of members season over season. The most common reason for not returning is moving out of the area, not dissatisfaction with the product."),

            ("Soil Testing on a Budget: What to Order, When, and How to Read It",
             "soil-testing-budget",
             "We get asked constantly how much we spend on soil testing and whether it's worth it for a smaller operation. Here's our honest answer: we spend $340 per year on soil tests across 14 fields and every dollar of that comes back multiplied in fertilizer we didn't have to buy.\n\n"
             "Our testing calendar: We pull samples in early October after fall harvest and before we apply any amendments. October samples reflect the season's depletion and give us the full winter to plan amendments without the spring rush.\n\n"
             "What we order: A standard panel (pH, organic matter, P, K, Ca, Mg, S, CEC) at $18/sample from our state extension lab. We add the micronutrient panel ($28 extra) on fields that have shown deficiency symptoms in the past three years — currently five fields.\n\n"
             "Reading the results: The most important number is pH. Everything else responds to pH. If your pH is below 6.0, fix that first before spending anything on nutrients. Second priority is organic matter — below 2% means your soil biology is struggling and any synthetic fertilizer you apply will perform below label rate.\n\n"
             "Phosphorus: Most extension labs use the Mehlich-3 extraction method. If your P is above 100 ppm Mehlich-3, you have enough for most crops and should focus on other nutrients. Below 20 ppm you're likely seeing yield drag.\n\n"
             "Cation ratios: We've moved away from the base saturation ratio approach that was popular 20 years ago. The research since then shows that getting the individual elements into the sufficiency range matters more than hitting specific ratios. Keep Ca above 70% saturation, Mg 10–20%, K 2–5%, and Na below 3%."),

            ("Our Farm's Food Safety Plan: What We Do and Why",
             "food-safety-plan",
             "When we started selling to restaurants and a regional co-op, food safety documentation became non-negotiable. Here's the core of our plan — not the legal boilerplate, but the actual practices we've built into daily farm life.\n\n"
             "Water testing: We test our irrigation water source quarterly. The test goes to a state-certified lab and checks total coliform, E. coli, and nitrate. We've had clean results every test, but the documentation is what our buyers require. If we ever fail a coliform test, our protocol is to switch to overhead irrigation only (not drip on edible portions), notify buyers, and retest before resuming normal practice.\n\n"
             "Worker health and hygiene: Every person who harvests, packs, or handles produce has completed our food safety training, which includes hand washing protocol, what to do if they're sick, and not to work with open wounds in harvest areas. Training is documented with a signed acknowledgment sheet.\n\n"
             "Harvest containers: All harvest totes are washed with a quaternary ammonium sanitizer at the end of every day and allowed to air dry. We don't stack wet totes.\n\n"
             "Temperature management: Leafy greens and basil go into the cooler within 30 minutes of harvest. We target cooler temperature of 34-36 degrees F. We log the cooler temperature twice daily.\n\n"
             "Traceability: Every harvest lot gets a date, field ID, and crop label. If a buyer ever needs to trace a product back, we can identify the field, the harvest date, who harvested it, and what went into which box within 20 minutes.\n\n"
             "Wildlife management: We've installed bird exclusion netting over our wash station and checked our field perimeter for evidence of large animal intrusion (deer breaks in fencing, feral pig activity). We document field inspections before harvest.")
        ]
        for title, slug, content in posts:
            q(c, """
                INSERT INTO blog (BusinessID, Title, Slug, Author, Content,
                                  IsPublished, ShowOnDirectory, ShowOnWebsite, PublishedAt)
                VALUES (:b, :t, :s, 'Green Valley Farm', :content, 1, 1, 1, GETDATE())
            """, {"b": BID, "t": title, "s": slug, "content": content})
            print(f"  + post: {title[:60]}")
    else:
        print(f"  skipped ({existing_posts} posts already exist)")

    # ── 2. EVENTS ─────────────────────────────────────────────────────────────
    section("events")
    existing_events = first(c, "SELECT COUNT(*) FROM OFNEvents WHERE BusinessID=:b", {"b": BID})
    if existing_events == 0:
        events = [
            ("Spring Planting Workshop", "workshop",
             "2026-04-12", "2026-04-12",
             "Hands-on workshop covering cover crop termination, bed preparation, and transplant production for vegetable growers. Includes a field walk and Q&A with our head grower. Breakfast and lunch provided.",
             "Green Valley Farm — 1450 Valley Road", "Millbrook", "NY", "12545", 40, 0, 45.00),
            ("Summer Farm Tour & Potluck", "farm_tour",
             "2026-07-18", "2026-07-18",
             "Open farm tour from 10am–2pm followed by a community potluck. See our rotational grazing system, vegetable fields, and cooler facility. Bring a dish to share. Free and open to all.",
             "Green Valley Farm — 1450 Valley Road", "Millbrook", "NY", "12545", 120, 1, 0.00),
            ("Harvest Festival & CSA Celebration", "festival",
             "2026-10-03", "2026-10-03",
             "Annual end-of-season celebration for CSA members and the community. Live music, farm games, apple pressing, and a farm-to-table dinner sourced entirely from the 2026 season. Tickets required for dinner.",
             "Green Valley Farm — 1450 Valley Road", "Millbrook", "NY", "12545", 200, 0, 35.00),
            ("Regenerative Grazing Field Day", "workshop",
             "2026-05-22", "2026-05-22",
             "Join us for a full-day field day focused on rotational grazing systems, paddock design, and forage management. Led by our farm manager with 15 years of intensive grazing experience. RSVP required — space limited to 30 participants.",
             "Green Valley Farm — 1450 Valley Road", "Millbrook", "NY", "12545", 30, 0, 25.00),
            ("Winter Farm Planning Workshop", "workshop",
             "2026-12-05", "2026-12-05",
             "Annual planning workshop: crop planning, cash flow projections, seed ordering, and cover crop decisions for the coming season. Free for CSA members, $15 for others. Coffee and pastries provided.",
             "Green Valley Farm — 1450 Valley Road", "Millbrook", "NY", "12545", 60, 0, 15.00),
        ]
        for name, etype, start, end, desc, loc, city, state, zip_, cap, is_free, price in events:
            q(c, """
                INSERT INTO OFNEvents (BusinessID, EventName, EventType, EventDescription,
                    EventStartDate, EventEndDate, EventLocationName, EventLocationCity,
                    EventLocationState, EventLocationZip, MaxAttendees, IsFree,
                    IsPublished, RegistrationRequired)
                VALUES (:b,:n,:et,:desc,:s,:e,:loc,:city,:state,:zip,:cap,:free,1,1)
            """, {"b":BID,"n":name,"et":etype,"desc":desc,"s":start,"e":end,
                  "loc":loc,"city":city,"state":state,"zip":zip_,"cap":cap,"free":is_free})
            print(f"  + event: {name}")
    else:
        print(f"  skipped ({existing_events} events already exist)")

    # ── 3. JOB BOARD ─────────────────────────────────────────────────────────
    section("job board")
    existing_jobs = first(c, "SELECT COUNT(*) FROM JobListings WHERE BusinessID=:b", {"b": BID})
    if existing_jobs == 0:
        jobs = [
            ("Lead Market Garden Grower", "full_time", "Crop Management",
             28.00, "hourly", "2026-04-01", "2026-11-15", "2026-03-15", 45,
             True, False,
             "We are looking for an experienced vegetable grower to manage our 4-acre market garden serving CSA members, farmers markets, and restaurant accounts. Responsibilities include transplant production, field scheduling, crew supervision (2-3 seasonal workers), and harvest logistics. Minimum 3 seasons of direct-market vegetable experience required. Knowledge of season extension, drip irrigation, and integrated pest management preferred. Housing available on-farm.",
             "gvfarm@email.com"),
            ("Seasonal Harvest & Pack Crew", "seasonal", "Crop Management",
             18.00, "hourly", "2026-05-15", "2026-10-31", "2026-04-30", 50,
             True, True,
             "Two to three seasonal positions for harvest and packing work in our market garden. Work includes harvesting leafy greens, tomatoes, cucumbers, and other vegetables; washing and packing produce; and loading delivery vehicles. Physical work outdoors in all weather. No prior farm experience required — we train. Housing and daily meals provided on-farm. Strong work ethic and ability to work as a team are the most important qualities we look for.",
             "gvfarm@email.com"),
            ("Farm Operations Manager", "full_time", "Business",
             65000.00, "yearly", None, None, "2026-04-01", 50,
             False, False,
             "Year-round position overseeing day-to-day operations of a 200-acre diversified farm including vegetable production, beef cattle, and pastured pork. Responsibilities: crew management (8 FTE + seasonal), equipment maintenance oversight, delivery logistics, CSA administration, and vendor relationships. Ideal candidate has 5+ years of farm management experience, strong mechanical aptitude, and experience with QuickBooks or farm accounting software. Salary commensurate with experience.",
             "gvfarm@email.com"),
        ]
        for title, jtype, cat, pay, period, start, end, deadline, hours, housing, meals, desc, email in jobs:
            q(c, """
                INSERT INTO JobListings (BusinessID, Title, JobType, Category, PayRate, PayPeriod,
                    SeasonStart, SeasonEnd, ApplyDeadline, HoursPerWeek,
                    HousingProvided, MealsProvided, Description, ContactEmail,
                    City, StateProvince, IsActive)
                VALUES (:b,:t,:jt,:cat,:pay,:per,:ss,:se,:dl,:hrs,:hs,:ms,:desc,:email,
                        'Millbrook','NY',1)
            """, {"b":BID,"t":title,"jt":jtype,"cat":cat,"pay":pay,"per":period,
                  "ss":start,"se":end,"dl":deadline,"hrs":hours,"hs":housing,"ms":meals,
                  "desc":desc,"email":email})
            print(f"  + job: {title}")
    else:
        print(f"  skipped ({existing_jobs} jobs already exist)")

    # ── 4. EQUIPMENT ─────────────────────────────────────────────────────────
    section("equipment")
    existing_eq = first(c, "SELECT COUNT(*) FROM EquipmentListings WHERE BusinessID=:b", {"b": BID})
    if existing_eq == 0:
        equipment = [
            ("2018 John Deere 5075E Utility Tractor", "Tractors", "sale",
             42500.00, None, None, "good", 2018, "John Deere", "5075E", 1840,
             "Well-maintained 75 HP utility tractor. 4WD, cab with heat and AC, 540/1000 PTO. Recent service: new hydraulic filters, front axle seals replaced, tires at 70%. All records available. Selling due to upgrade.",),
            ("6-Row Mechanical Transplanter", "Planting Equipment", "sale",
             8200.00, None, None, "excellent", 2020, "Mechanical Transplanter", "MT-600", 0,
             "Paper pot transplanter system, 6-row, used three seasons in raised bed vegetable production. Includes all paper pot chains for tomato, lettuce, brassica sizes. Clean condition, stored inside.",),
            ("2015 Kubota BX2380 Sub-Compact Tractor", "Tractors", "swap",
             None, "Looking for a walk-behind tractor (BCS or Grillo) plus cash", None, "good", 2015, "Kubota", "BX2380", 420,
             "Sub-compact with loader, belly mower, and rear tiller. 23 HP diesel. Good for market garden scale work. We're scaling up and need a walk-behind more than a sub-compact now.",),
            ("Roper Whitney 4-Bed Plastic Mulch Layer", "Other", "sale",
             2800.00, None, None, "fair", 2012, "Roper Whitney", "ML-4", 0,
             "3-point hitch mulch layer for 4-foot beds. Lays film and drip tape simultaneously. Some wear on the film tensioner but mechanically sound. Comes with a partial roll of black IRT film.",),
            ("Chest Freezer — True GDM-49 Commercial", "Processing & Storage", "sale",
             1400.00, None, None, "good", 2019, "True", "GDM-49", 0,
             "49 cubic foot commercial glass door reach-in. Was used in our farm stand. Sold our stand building and have no place for it. Tested and working, compressor in good shape. Pick up only.",),
        ]
        for title, cat, ltype, price, swap, loan, cond, year, make, model, hours, desc in equipment:
            q(c, """
                INSERT INTO EquipmentListings (BusinessID, Title, Category, ListingType,
                    AskingPrice, SwapFor, LoanTerms, Condition, YearMade, Make, Model,
                    HoursUsed, Description, City, StateProvince, ContactEmail, IsActive)
                VALUES (:b,:t,:cat,:lt,:price,:swap,:loan,:cond,:yr,:make,:model,:hrs,:desc,
                        'Millbrook','NY','gvfarm@email.com',1)
            """, {"b":BID,"t":title,"cat":cat,"lt":ltype,"price":price,"swap":swap,"loan":loan,
                  "cond":cond,"yr":year,"make":make,"model":model,"hrs":hours,"desc":desc})
            print(f"  + equipment: {title[:60]}")
    else:
        print(f"  skipped ({existing_eq} listings already exist)")

    # ── 5. SERVICES ───────────────────────────────────────────────────────────
    section("services")
    existing_svc = first(c, "SELECT COUNT(*) FROM Services WHERE BusinessID=:b", {"b": BID})
    if existing_svc == 0:
        services = [
            ("Custom Field Scouting & IPM Reports",
             "Weekly crop scouting service for vegetable and grain operations within 25 miles. Includes written report with pest pressure maps, economic threshold assessments, and treatment recommendations. Available May–October.",
             85.00, 0, 1),
            ("Soil Health Consultation",
             "Full soil health assessment including review of your most recent soil test results, physical soil health indicators (aggregate stability, infiltration rate, earthworm counts), and a written amendment plan with prioritized recommendations and product sourcing options.",
             150.00, 0, 1),
            ("On-Farm Agronomy Consulting (Half Day)",
             "Half-day on-farm consultation covering any combination of field issues: variety selection, fertility program review, cover crop planning, irrigation design, or crop rotation development. We prepare a written summary after the visit.",
             None, 1, 1),  # contact for price
            ("Pastured Livestock Custom Processing Coordination",
             "We coordinate with our USDA-inspected custom processor for small and mid-scale beef and pork producers who lack the volume or relationships to schedule efficiently. We batch orders quarterly to secure kill dates and handle paperwork. Fee charged per animal.",
             75.00, 0, 1),
            ("CSA Setup & Management Consulting",
             "One-time consulting service for farms launching a CSA program. Includes share structure design, pricing model development, member communication templates, box planning spreadsheet, and one follow-up call after your first delivery month.",
             None, 1, 1),
            ("Farm Food Safety Plan Development",
             "We help farms prepare written food safety plans compliant with FSMA Produce Safety Rule requirements, including standard operating procedures, water testing protocols, worker training documentation, and recordkeeping templates. Includes one on-site audit prep review.",
             None, 1, 1),
        ]
        for title, desc, price, contact_for_price, avail in services:
            q(c, """
                INSERT INTO Services (BusinessID, ServiceTitle, ServicesDescription,
                    ServicePrice, ServiceContactForPrice, ServiceAvailable,
                    Serviceemail)
                VALUES (:b,:t,:desc,:price,:cfp,:avail,'gvfarm@email.com')
            """, {"b":BID,"t":title,"desc":desc,"price":price,"cfp":contact_for_price,"avail":avail})
            print(f"  + service: {title[:60]}")
    else:
        print(f"  skipped ({existing_svc} services already exist)")

    # ── 6. CSA PLANS ─────────────────────────────────────────────────────────
    section("CSA plans")
    existing_csa = first(c, "SELECT COUNT(*) FROM CSAPlans WHERE BusinessID=:b", {"b": BID})
    if existing_csa == 0:
        plans = [
            ("Full Share — Summer 2026",
             "22-week vegetable CSA running May 15 through October 17. A Full Share is designed for a family of four and includes 12–14 items per week at peak season. Pickup every Saturday at the farm stand (9am–12pm) or Thursday in Millbrook Village (4–6pm).",
             "Full", 620.00, "weekly", "2026-05-15", "2026-10-17", "Saturday", "Farm Stand — 1450 Valley Rd, Millbrook NY", 55),
            ("Half Share — Summer 2026",
             "22-week vegetable CSA, Half Share size. Perfect for one- or two-person households or families who supplement at the market. Approximately 60% of Full Share volume with the same diversity of items.",
             "Half", 340.00, "weekly", "2026-05-15", "2026-10-17", "Saturday", "Farm Stand — 1450 Valley Rd, Millbrook NY", 30),
            ("Winter Storage Share 2026",
             "8-week winter storage share running November through December. Each box includes root vegetables (carrots, beets, turnips, parsnips, celeriac), storage squash, potatoes, onions, garlic, and dried herbs. Pick up every other Saturday at the farm.",
             "Full", 195.00, "biweekly", "2026-11-07", "2026-12-19", "Saturday", "Farm Stand — 1450 Valley Rd, Millbrook NY", 40),
        ]
        plan_ids = []
        for name, desc, size, price, freq, start, end, pickup_day, pickup_loc, cap in plans:
            pid = first(c, """
                INSERT INTO CSAPlans (BusinessID, Name, Description, ShareSize,
                    PricePerShare, Frequency, SeasonStart, SeasonEnd,
                    PickupDay, PickupLocation, Capacity, IsActive)
                OUTPUT INSERTED.PlanID
                VALUES (:b,:n,:d,:sz,:p,:fr,:ss,:se,:pd,:pl,:cap,1)
            """, {"b":BID,"n":name,"d":desc,"sz":size,"p":price,"fr":freq,
                  "ss":start,"se":end,"pd":pickup_day,"pl":pickup_loc,"cap":cap})
            plan_ids.append(pid)
            print(f"  + CSA plan: {name}")

        # CSA subscribers
        members = [
            ("Sarah Chen",       "sarah.chen@email.com",    "845-555-0101"),
            ("Mike Harrington",  "mharrington@email.com",   "845-555-0102"),
            ("Linda Park",       "lpark@email.com",         "845-555-0103"),
            ("David Okonkwo",    "dokonkwo@email.com",      "845-555-0104"),
            ("Rachel Torres",    "ratorres@email.com",      "845-555-0105"),
            ("James Whitfield",  "jwhitfield@email.com",    "845-555-0106"),
            ("Amy Nguyen",       "anguyen@email.com",       "845-555-0107"),
            ("Tom Bergmann",     "tbergmann@email.com",     "845-555-0108"),
            ("Priya Sharma",     "psharma@email.com",       "845-555-0109"),
            ("Carlos Rivera",    "crivera@email.com",       "845-555-0110"),
        ]
        if plan_ids:
            full_id = plan_ids[0]
            half_id = plan_ids[1] if len(plan_ids) > 1 else plan_ids[0]
            for i, (name, email, phone) in enumerate(members):
                pid = full_id if i < 7 else half_id
                q(c, """
                    INSERT INTO CSASubscriptions (PlanID, BusinessID, MemberName, MemberEmail,
                        MemberPhone, Status, StartDate, PickupPreference)
                    VALUES (:pid,:b,:n,:e,:ph,'active','2026-05-15','Saturday')
                """, {"pid":pid,"b":BID,"n":name,"e":email,"ph":phone})
            print(f"  + {len(members)} CSA subscribers")

        # A few share log entries
        if plan_ids:
            for i, box_date in enumerate(["2026-05-16","2026-05-23","2026-05-30"]):
                q(c, """
                    INSERT INTO CSAShareLog (PlanID, BusinessID, ShareDate, Contents, PickupCount)
                    VALUES (:pid,:b,:d,:contents,:cnt)
                """, {"pid":plan_ids[0],"b":BID,"d":box_date,
                      "contents": ["Spring mix, spinach, radishes, scallions, arugula, kohlrabi, turnips, chives",
                                   "Lettuce mix, kale, bok choy, snap peas, scallions, hakurei turnips, cilantro, basil starts",
                                   "Head lettuce, kale, chard, zucchini (first of season!), scallions, beets, dill, basil"][i],
                      "cnt": [42, 45, 47][i]})
    else:
        print(f"  skipped ({existing_csa} plans already exist)")

    # ── 7. CERTIFICATIONS ────────────────────────────────────────────────────
    section("certifications")
    existing_cert = first(c, "SELECT COUNT(*) FROM BusinessCertifications WHERE BusinessID=:b", {"b": BID})
    if existing_cert == 0:
        certs = [
            ("USDA Certified Organic", "USDA Organic", "NOFA-NY Certified Organic, LLC",
             "NY-O-2019-0847", "2019-03-15", "2027-03-14", "active",
             "Covers all vegetable fields (14.2 acres) and pastures (80 acres). Annual renewal with NOFA-NY. Transition completed 2019."),
            ("USDA GAP/GHP Certification", "GAP / GHP", "USDA Agricultural Marketing Service",
             "GAP-2023-NY-4471", "2023-08-01", "2026-07-31", "active",
             "Good Agricultural Practices certification required by wholesale and institutional buyers. Covers harvest, packing, and cooler operations."),
            ("Certified Naturally Grown", "CNG", "Certified Naturally Grown",
             "CNG-NY-2021-0392", "2021-06-01", "2026-05-31", "active",
             "Peer-review certification aligned with USDA organic standards. Used for farmers market sales and direct consumer marketing."),
            ("NYS Department of Ag & Markets — Food Processing License", "State License",
             "NYS Department of Agriculture & Markets",
             "FPL-2022-47891", "2022-01-15", "2026-12-31", "active",
             "Covers our on-farm processing of jams, pickles, and dried herbs sold at retail."),
        ]
        for name, ctype, issuer, num, issued, expiry, status, notes in certs:
            q(c, """
                INSERT INTO BusinessCertifications (BusinessID, CertName, CertType, IssuingBody,
                    CertNumber, IssuedDate, ExpiryDate, Status, Notes)
                VALUES (:b,:n,:ct,:iss,:num,:iss_d,:exp,:st,:notes)
            """, {"b":BID,"n":name,"ct":ctype,"iss":issuer,"num":num,
                  "iss_d":issued,"exp":expiry,"st":status,"notes":notes})
            print(f"  + cert: {name}")
    else:
        print(f"  skipped ({existing_cert} certs already exist)")

    # ── 8. LAND LEASING ───────────────────────────────────────────────────────
    section("land leasing")
    existing_land = first(c, "SELECT COUNT(*) FROM LandListings WHERE BusinessID=:b", {"b": BID})
    if existing_land == 0:
        land_listings = [
            ("28 Acres Tillable — Available Spring 2026",
             "lease",
             28.00, "Silt loam, Dutchess series", True, 28.00,
             "Well-drained silt loam field, flat to gently rolling. 28 acres tillable, currently in cereal rye cover crop. 3-phase electric at field road. Municipal water available at road. No buildings included — field-only lease. Suitable for vegetables, row crops, or small grains. Will consider 3-year lease with option to renew.",
             95.00, None, "3-year with option to renew", "2026-04-01",
             "Millbrook", "NY", 41.7851, -73.6820),
            ("7 Acres Certified Organic Pasture — Available Immediately",
             "lease",
             7.00, "Sandy loam, Hoosic series", False, 0.0,
             "Seven acres of certified organic pasture adjacent to our main operation. Currently vacant — previous tenant's lease ended. Electric fence infrastructure in place (4 paddocks). Water access via gravity-fed spring box. Organic certificate available. Ideal for livestock grazing operation. Short-term (1-year) or long-term lease considered.",
             65.00, None, "1 or 3 year", "2026-01-01",
             "Millbrook", "NY", 41.7901, -73.6750),
        ]
        for title, ltype, acres, soil, irrig, tillable, desc, ppa, total, term, avail, city, state, lat, lon in land_listings:
            q(c, """
                INSERT INTO LandListings (BusinessID, Title, ListingType, Acreage, SoilType,
                    Irrigation, Tillable, Description, PricePerAcre, TotalPrice, LeaseTerm,
                    AvailableDate, City, StateProvince, Latitude, Longitude,
                    ContactEmail, IsActive)
                VALUES (:b,:t,:lt,:acres,:soil,:irr,:till,:desc,:ppa,:tot,:term,:avail,
                        :city,:state,:lat,:lon,'gvfarm@email.com',1)
            """, {"b":BID,"t":title,"lt":ltype,"acres":acres,"soil":soil,"irr":irrig,"till":tillable,
                  "desc":desc,"ppa":ppa,"tot":total,"term":term,"avail":avail,
                  "city":city,"state":state,"lat":lat,"lon":lon})
            print(f"  + land: {title[:60]}")
    else:
        print(f"  skipped ({existing_land} listings already exist)")

    # ── 9. TESTIMONIALS ───────────────────────────────────────────────────────
    section("testimonials")
    existing_test = first(c, "SELECT COUNT(*) FROM Testimonials WHERE BusinessID=:b", {"b": BID})
    if existing_test == 0:
        testimonials = [
            ("Sarah Chen", "CSA Member", 5,
             "We've been Full Share members for four years now and it's one of the best decisions we've made for our family. The quality is incredible — we're getting things we'd never find at the grocery store and our kids have actually started eating vegetables they wouldn't touch before. The weekly newsletter with recipes is genuinely helpful."),
            ("Chef Marco Deluca", "Restaurant Partner, The Birch", 5,
             "Green Valley has been one of our primary farm partners for three seasons. Their reliability is what sets them apart — they communicate what's coming, they show up when they say they will, and the product is consistently excellent. We've built several menu items around their produce knowing it will be there week after week."),
            ("Tom Bergmann", "CSA Member & Workshop Attendee", 5,
             "I came to the spring planting workshop as a complete beginner and left with a full season plan I actually felt confident about. The instruction was practical and hands-on — not just theory. I've since started my own half-acre market garden and lean on a lot of what I learned that day."),
            ("Rebecca Huang", "Neighboring Farm", 5,
             "I reached out to Green Valley when I was struggling to get our GAP certification paperwork in order. They walked me through their food safety plan documents and connected me with their certifier. That level of generosity between farms is rare and I won't forget it."),
        ]
        for name, role, stars, content in testimonials:
            try:
                q(c, """
                    INSERT INTO Testimonials (BusinessID, AuthorName, AuthorRole, StarRating,
                        Content, IsApproved, IsPublished)
                    VALUES (:b,:n,:role,:stars,:content,1,1)
                """, {"b":BID,"n":name,"role":role,"stars":stars,"content":content})
                print(f"  + testimonial: {name}")
            except Exception as e:
                print(f"  ! testimonials skip ({e})")
                break
    else:
        print(f"  skipped ({existing_test} testimonials already exist)")

    # ── 10. ACCOUNTING ────────────────────────────────────────────────────────
    section("accounting")
    existing_fy = first(c, "SELECT COUNT(*) FROM FiscalYears WHERE BusinessID=:b", {"b": BID})
    if existing_fy == 0:
        try:
            # Account types (shared table — insert if missing)
            for tid, name, normal in [(1,"Asset","debit"),(2,"Liability","credit"),
                                       (3,"Equity","credit"),(4,"Revenue","credit"),(5,"Expense","debit")]:
                try:
                    q(c, "INSERT INTO AccountTypes (AccountTypeID,TypeName,NormalBalance) VALUES (:id,:n,:nb)",
                      {"id":tid,"n":name,"nb":normal})
                except Exception:
                    pass  # already exists

            # Fiscal year
            fy_id = first(c, """
                INSERT INTO FiscalYears (BusinessID, YearName, StartDate, EndDate)
                OUTPUT INSERTED.FiscalYearID
                VALUES (:b,'FY2026','2026-01-01','2026-12-31')
            """, {"b":BID})

            # Periods
            months = [("Jan 2026","2026-01-01","2026-01-31"),("Feb 2026","2026-02-01","2026-02-28"),
                      ("Mar 2026","2026-03-01","2026-03-31"),("Apr 2026","2026-04-01","2026-04-30"),
                      ("May 2026","2026-05-01","2026-05-31"),("Jun 2026","2026-06-01","2026-06-30"),
                      ("Jul 2026","2026-07-01","2026-07-31"),("Aug 2026","2026-08-01","2026-08-31"),
                      ("Sep 2026","2026-09-01","2026-09-30"),("Oct 2026","2026-10-01","2026-10-31"),
                      ("Nov 2026","2026-11-01","2026-11-30"),("Dec 2026","2026-12-01","2026-12-31")]
            for i,(pname,pstart,pend) in enumerate(months, 1):
                q(c, """
                    INSERT INTO FiscalPeriods (FiscalYearID,BusinessID,PeriodNumber,PeriodName,StartDate,EndDate)
                    VALUES (:fy,:b,:pn,:pname,:ps,:pe)
                """, {"fy":fy_id,"b":BID,"pn":i,"pname":pname,"ps":pstart,"pe":pend})

            # Chart of accounts
            accounts = [
                ("1000","Cash — Operating","checking",        1, None),
                ("1010","Cash — Savings",  "savings",         1, None),
                ("1200","Accounts Receivable","",             1, None),
                ("1500","Crop Inventory",  "current asset",   1, None),
                ("1510","Livestock Inventory","",             1, None),
                ("1800","Equipment",       "fixed asset",     1, None),
                ("1810","Accumulated Depreciation","",        1, None),
                ("2000","Accounts Payable","",                2, None),
                ("2100","Accrued Expenses","",                2, None),
                ("2500","Operating Line of Credit","",        2, None),
                ("3000","Owner Equity",    "",                3, None),
                ("3100","Retained Earnings","",               3, None),
                ("4000","CSA Sales",       "",                4, None),
                ("4010","Farmers Market Sales","",            4, None),
                ("4020","Restaurant & Wholesale","",          4, None),
                ("4030","Services Revenue","",                4, None),
                ("4040","Grant Income",    "",                4, None),
                ("5000","Seed & Transplants","",              5, None),
                ("5010","Fertilizers & Amendments","",        5, None),
                ("5020","Pest Management","",                 5, None),
                ("5030","Irrigation Supplies","",             5, None),
                ("5100","Labor — Permanent","",               5, None),
                ("5110","Labor — Seasonal","",                5, None),
                ("5200","Equipment Fuel","",                  5, None),
                ("5210","Equipment Repairs","",               5, None),
                ("5300","Land Rent",       "",                5, None),
                ("5400","Utilities",       "",                5, None),
                ("5500","Insurance",       "",                5, None),
                ("5600","Marketing & CSA Admin","",           5, None),
                ("5700","Professional Fees","",               5, None),
            ]
            acct_map = {}
            for num, name, desc, atype, parent in accounts:
                aid = first(c, """
                    INSERT INTO Accounts (BusinessID,AccountNumber,AccountName,Description,
                        AccountTypeID,IsActive,IsSystem)
                    OUTPUT INSERTED.AccountID
                    VALUES (:b,:num,:name,:desc,:at,1,0)
                """, {"b":BID,"num":num,"name":name,"desc":desc,"at":atype})
                acct_map[num] = aid
            print(f"  + fiscal year FY2026 + 12 periods + {len(accounts)} accounts")

            # Journal entries — representative transactions
            entries = [
                # Jan: CSA pre-sale deposits
                ("2026-01-15","CSA Season Pre-Sales Deposit","4000",15600.00,"1000",15600.00,fy_id,1),
                # Feb: seed order
                ("2026-02-10","Seed Order — Johnny's + Fedco","5000",4280.00,"1000",4280.00,fy_id,2),
                # Mar: fertilizer/amendments
                ("2026-03-05","Compost delivery 20 yards","5010",1800.00,"2000",1800.00,fy_id,3),
                # Apr: seasonal labor start
                ("2026-04-15","Seasonal payroll Apr 1-15","5110",3200.00,"1000",3200.00,fy_id,4),
                # May: farmers market sales
                ("2026-05-03","Farmers market sales week 1","1000",1840.00,"4010",1840.00,fy_id,5),
                # May: restaurant invoice
                ("2026-05-15","Restaurant invoice — The Birch","1200",2100.00,"4020",2100.00,fy_id,5),
                # Jun: restaurant payment received
                ("2026-06-01","Restaurant payment — The Birch","1000",2100.00,"1200",2100.00,fy_id,6),
                # Jun: equipment repair
                ("2026-06-12","Tractor hydraulic pump repair","5210",780.00,"1000",780.00,fy_id,6),
                # Jul: peak season market
                ("2026-07-06","Farmers market sales week of 7/6","1000",3240.00,"4010",3240.00,fy_id,7),
                # Aug: insurance annual premium
                ("2026-08-01","Farm liability insurance annual","5500",4200.00,"1000",4200.00,fy_id,8),
                # Sep: land rent
                ("2026-09-01","Land rent Q3 payment","5300",2850.00,"1000",2850.00,fy_id,9),
                # Oct: consulting income
                ("2026-10-10","Agronomy consulting — 3 farms","1000",1350.00,"4030",1350.00,fy_id,10),
            ]
            for date_,memo,debit_acct,debit_amt,credit_acct,credit_amt,fy,period in entries:
                try:
                    je_id = first(c, """
                        INSERT INTO JournalEntries (BusinessID,FiscalYearID,FiscalPeriodID,
                            EntryDate,Description,TotalAmount,IsPosted)
                        OUTPUT INSERTED.EntryID
                        VALUES (:b,:fy,(SELECT FiscalPeriodID FROM FiscalPeriods
                                       WHERE FiscalYearID=:fy AND PeriodNumber=:pn AND BusinessID=:b),
                                :d,:memo,:amt,1)
                    """, {"b":BID,"fy":fy,"pn":period,"d":date_,"memo":memo,"amt":debit_amt})
                    if je_id and debit_acct in acct_map and credit_acct in acct_map:
                        q(c, """
                            INSERT INTO JournalEntryLines (EntryID,AccountID,DebitAmount,CreditAmount,Description)
                            VALUES (:je,:acct,:da,0,:memo)
                        """, {"je":je_id,"acct":acct_map[debit_acct],"da":debit_amt,"memo":memo})
                        q(c, """
                            INSERT INTO JournalEntryLines (EntryID,AccountID,DebitAmount,CreditAmount,Description)
                            VALUES (:je,:acct,0,:ca,:memo)
                        """, {"je":je_id,"acct":acct_map[credit_acct],"ca":credit_amt,"memo":memo})
                except Exception as e:
                    print(f"  ! journal entry skip: {e}")
            print(f"  + {len(entries)} journal entries")

        except Exception as e:
            print(f"  ! accounting skip: {e}")
    else:
        print(f"  skipped ({existing_fy} fiscal years already exist)")

    # ── 11. LIVESTOCK (Animals) ───────────────────────────────────────────────
    section("animals")
    existing_animals = first(c, "SELECT COUNT(*) FROM Animals WHERE BusinessID=:b", {"b": BID})
    if existing_animals == 0:
        # Get a valid SpeciesID if possible
        species_rows = c.execute(text("SELECT TOP 5 SpeciesID FROM species")).fetchall()
        spec_id = species_rows[0][0] if species_rows else None

        animals = [
            # Beef cattle
            ("GVF-C001","Angus Bull","Angus","Male",   "adult_male",  "Black",  "2021-03-12"),
            ("GVF-C002","Rosie",    "Angus","Female",  "adult_female","Black",  "2020-05-18"),
            ("GVF-C003","Daisy",    "Angus","Female",  "adult_female","Black",  "2021-08-02"),
            ("GVF-C004","Clover",   "Angus","Female",  "adult_female","Black",  "2022-04-25"),
            ("GVF-C005","Calf #5",  "Angus","Female",  "young_female","Black",  "2026-02-14"),
            ("GVF-C006","Calf #6",  "Angus","Male",    "young_male",  "Black",  "2026-03-01"),
            # Pastured pork
            ("GVF-P001","Berkshire Boar","Berkshire","Male","adult_male","Black w/ white points","2022-07-10"),
            ("GVF-P002","Sow Maple","Berkshire","Female","adult_female","Black w/ white points","2022-09-15"),
            ("GVF-P003","Sow Acorn","Berkshire","Female","adult_female","Black w/ white points","2023-01-20"),
            ("GVF-P004","Gilt Birch","Berkshire","Female","young_female","Black w/ white points","2025-06-05"),
            # Laying hens (track as flock)
            ("GVF-H001","Flock 1 — Rhode Island Red","Rhode Island Red","Female","adult_female","Red",  "2025-03-01"),
            ("GVF-H002","Flock 2 — Barred Rock","Barred Rock","Female","adult_female","Black/White","2025-03-01"),
        ]
        for reg, name, breed, gender, category, color, dob in animals:
            try:
                q(c, """
                    INSERT INTO Animals (BusinessID, FullName, RegistrationNumber, BreedName,
                        Gender, Category, Color1, DOB, SpeciesID)
                    VALUES (:b,:n,:reg,:breed,:gender,:cat,:color,:dob,:spec)
                """, {"b":BID,"n":name,"reg":reg,"breed":breed,"gender":gender,
                      "cat":category,"color":color,"dob":dob,"spec":spec_id})
                print(f"  + animal: {name}")
            except Exception as e:
                print(f"  ! animal error ({name}): {e}")
                break
    else:
        print(f"  skipped ({existing_animals} animals already exist)")

    # ── 12. PRODUCE INVENTORY ─────────────────────────────────────────────────
    section("produce inventory")
    try:
        existing_prod = first(c, "SELECT COUNT(*) FROM Produce WHERE BusinessID=:b", {"b": BID})
        if existing_prod == 0:
            # Look up some ingredient IDs
            ingredients = c.execute(text(
                "SELECT TOP 20 IngredientID, IngredientName FROM Ingredients ORDER BY IngredientID"
            )).fetchall()
            measure_id = first(c, "SELECT TOP 1 MeasurementID FROM MeasurementLookup")

            if ingredients and measure_id:
                for ing_id, ing_name in ingredients[:8]:
                    q(c, """
                        INSERT INTO Produce (BusinessID, IngredientID, Quantity, MeasurementID,
                            WholesalePrice, RetailPrice, ShowProduce, AvailableDate)
                        VALUES (:b,:i,50,:m,:ws,:rt,1,GETDATE())
                    """, {"b":BID,"i":ing_id,"m":measure_id,
                          "ws":round(1.50 + ing_id*0.1 % 3, 2),
                          "rt":round(2.50 + ing_id*0.15 % 4, 2)})
                print(f"  + {min(8,len(ingredients))} produce items")
            else:
                print("  ! no ingredients/measurements in lookup tables — skipped")
        else:
            print(f"  skipped ({existing_prod} items already exist)")
    except Exception as e:
        print(f"  ! produce skip: {e}")

    # ── 13. FOOD WANTED ADS ───────────────────────────────────────────────────
    section("food wanted")
    try:
        existing_fw = first(c, "SELECT COUNT(*) FROM FoodWantedAds WHERE BusinessID=:b", {"b": BID})
        if existing_fw == 0:
            wanted = [
                ("Seeking: Certified Organic Grain Hay — 200 Bales",
                 "Looking for certified organic grass or mixed-grass hay for our beef herd. Need 200 square bales or equivalent, to be delivered October–November. Prefer Dutchess or Columbia County NY origin. Will consider multi-year purchase agreement.",
                 "Hay & Forage", 8.50, 200, "bale"),
                ("Seeking: Locally Grown Oats — Feed Grade, 2,000 lbs",
                 "Looking for locally grown oats, feed grade or better, for our pastured pork operation. We use roughly 500 lbs/month supplemental grain. Interested in connecting with a grain farmer for a direct annual contract.",
                 "Grains", 0.28, 2000, "lb"),
            ]
            for title, desc, cat, price, qty, unit in wanted:
                try:
                    q(c, """
                        INSERT INTO FoodWantedAds (BusinessID, Title, Description, Category,
                            TargetPricePerUnit, QuantityNeeded, UnitLabel, IsActive, ContactEmail)
                        VALUES (:b,:t,:d,:cat,:p,:qty,:unit,1,'gvfarm@email.com')
                    """, {"b":BID,"t":title,"d":desc,"cat":cat,"p":price,"qty":qty,"unit":unit})
                    print(f"  + food wanted: {title[:60]}")
                except Exception as e:
                    print(f"  ! food wanted error: {e}"); break
        else:
            print(f"  skipped ({existing_fw} ads already exist)")
    except Exception as e:
        print(f"  ! food wanted skip: {e}")

    # ── 14. METRICS SNAPSHOT ─────────────────────────────────────────────────
    section("appnotifications")
    try:
        q(c, """
            INSERT INTO AppNotifications (BusinessID, Title, Body, NotifType, IsRead)
            VALUES (:b,'CSA Season Open — 23 Signups So Far',
                    'Your 2026 Full Share CSA has received 23 signups out of 55 capacity (42%%). The Half Share has 11 of 30 filled. Consider sending a reminder to your waitlist.',
                    'info',0)
        """, {"b":BID})
        q(c, """
            INSERT INTO AppNotifications (BusinessID, Title, Body, NotifType, IsRead)
            VALUES (:b,'GAP Certification Renewal Due in 90 Days',
                    'Your USDA GAP/GHP certificate expires 2026-07-31. Contact USDA AMS to schedule your renewal inspection.',
                    'warning',0)
        """, {"b":BID})
        q(c, """
            INSERT INTO AppNotifications (BusinessID, Title, Body, NotifType, IsRead)
            VALUES (:b,'New Job Application — Lead Market Garden Grower',
                    'A new application was received for Lead Market Garden Grower from applicant Jordan Morales. Review in the Job Board section.',
                    'info',0)
        """, {"b":BID})
        print("  + 3 notifications")
    except Exception as e:
        print(f"  ! notifications skip: {e}")

print("\n✓ Demo seed complete for BusinessID=15671")
print("  Blog, Events, Jobs, Equipment, Services, CSA, Certifications,")
print("  Land Leasing, Testimonials, Accounting, Animals, Produce, Notifications")
