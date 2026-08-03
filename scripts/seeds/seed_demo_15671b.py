"""Continuation seed — testimonials, accounting, animals, produce, notifications."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import engine
from sqlalchemy import text

BID = 15671

def q(c, sql, params=None):
    return c.execute(text(sql), params or {})

def first(c, sql, params=None):
    row = c.execute(text(sql), params or {}).fetchone()
    return row[0] if row else None

def section(name):
    print(f"\n[{name}]")


with engine.begin() as c:

    # ── TESTIMONIALS ──────────────────────────────────────────────────────────
    section("testimonials")
    existing = first(c, "SELECT COUNT(*) FROM Testimonials WHERE CustID=:b", {"b": BID})
    if existing == 0:
        testimonials = [
            ("Sarah Chen",       "CSA Member",                     5, "Millbrook", "NY",
             "We have been Full Share members for four years and it is one of the best decisions we have made for our family. The quality is incredible and our kids have started eating vegetables they would not touch before. The weekly newsletter with recipes is genuinely helpful."),
            ("Chef Marco Deluca","Restaurant Partner, The Birch",  5, "Rhinebeck", "NY",
             "Green Valley has been one of our primary farm partners for three seasons. Their reliability is what sets them apart — they communicate what is coming, they show up when they say they will, and the product is consistently excellent. We have built several menu items around their produce."),
            ("Tom Bergmann",     "CSA Member & Workshop Attendee", 5, "Millbrook", "NY",
             "I came to the spring planting workshop as a complete beginner and left with a full season plan I actually felt confident about. The instruction was practical and hands-on. I have since started my own half-acre market garden using what I learned that day."),
            ("Rebecca Huang",    "Neighboring Farm Owner",         5, "Amenia",    "NY",
             "I reached out to Green Valley when I was struggling to get our GAP certification paperwork in order. They walked me through their food safety plan and connected me with their certifier. That level of generosity between farms is rare."),
        ]
        for name, org, rating, city, state, text_ in testimonials:
            q(c, """
                INSERT INTO Testimonials (CustID, CustomerName, Testimonial, Rating,
                    City, State, Organization, TestimonialDate)
                VALUES (:b,:n,:t,:r,:city,:state,:org,GETDATE())
            """, {"b":BID,"n":name,"t":text_,"r":rating,"city":city,"state":state,"org":org})
            print(f"  + {name}")
    else:
        print(f"  skipped ({existing} already exist)")

    # ── ACCOUNTING ────────────────────────────────────────────────────────────
    section("accounting")
    existing_fy = first(c, "SELECT COUNT(*) FROM FiscalYears WHERE BusinessID=:b", {"b": BID})
    if existing_fy == 0:
        try:
            for tid, name, nb in [(1,"Asset","debit"),(2,"Liability","credit"),
                                   (3,"Equity","credit"),(4,"Revenue","credit"),(5,"Expense","debit")]:
                try:
                    q(c,"INSERT INTO AccountTypes (AccountTypeID,TypeName,NormalBalance) VALUES (:id,:n,:nb)",
                      {"id":tid,"n":name,"nb":nb})
                except Exception:
                    pass

            fy_id = first(c, """
                INSERT INTO FiscalYears (BusinessID,YearName,StartDate,EndDate)
                OUTPUT INSERTED.FiscalYearID
                VALUES (:b,'FY2026','2026-01-01','2026-12-31')
            """, {"b":BID})

            months = [("Jan 2026","2026-01-01","2026-01-31"),("Feb 2026","2026-02-01","2026-02-28"),
                      ("Mar 2026","2026-03-01","2026-03-31"),("Apr 2026","2026-04-01","2026-04-30"),
                      ("May 2026","2026-05-01","2026-05-31"),("Jun 2026","2026-06-01","2026-06-30"),
                      ("Jul 2026","2026-07-01","2026-07-31"),("Aug 2026","2026-08-01","2026-08-31"),
                      ("Sep 2026","2026-09-01","2026-09-30"),("Oct 2026","2026-10-01","2026-10-31"),
                      ("Nov 2026","2026-11-01","2026-11-30"),("Dec 2026","2026-12-01","2026-12-31")]
            for i,(pname,pstart,pend) in enumerate(months,1):
                q(c, """
                    INSERT INTO FiscalPeriods
                        (FiscalYearID,BusinessID,PeriodNumber,PeriodName,StartDate,EndDate)
                    VALUES (:fy,:b,:pn,:pname,:ps,:pe)
                """, {"fy":fy_id,"b":BID,"pn":i,"pname":pname,"ps":pstart,"pe":pend})

            accounts = [
                ("1000","Cash - Operating",         1),("1010","Cash - Savings",           1),
                ("1200","Accounts Receivable",       1),("1500","Crop Inventory",            1),
                ("1510","Livestock Inventory",       1),("1800","Equipment",                 1),
                ("1810","Accum. Depreciation",       1),("2000","Accounts Payable",          2),
                ("2100","Accrued Expenses",          2),("2500","Operating Line of Credit",  2),
                ("3000","Owner Equity",              3),("3100","Retained Earnings",         3),
                ("4000","CSA Sales",                 4),("4010","Farmers Market Sales",      4),
                ("4020","Restaurant & Wholesale",    4),("4030","Services Revenue",          4),
                ("4040","Grant Income",              4),("5000","Seed & Transplants",        5),
                ("5010","Fertilizers & Amendments",  5),("5020","Pest Management",           5),
                ("5100","Labor - Permanent",         5),("5110","Labor - Seasonal",          5),
                ("5200","Equipment Fuel",            5),("5210","Equipment Repairs",         5),
                ("5300","Land Rent",                 5),("5400","Utilities",                 5),
                ("5500","Insurance",                 5),("5600","Marketing & CSA Admin",     5),
            ]
            acct_map = {}
            for num, name, atype in accounts:
                aid = first(c, """
                    INSERT INTO Accounts (BusinessID,AccountNumber,AccountName,AccountTypeID,IsActive,IsSystem)
                    OUTPUT INSERTED.AccountID
                    VALUES (:b,:num,:name,:at,1,0)
                """, {"b":BID,"num":num,"name":name,"at":atype})
                if aid:
                    acct_map[num] = aid

            print(f"  + FY2026, 12 periods, {len(acct_map)} accounts")

            entries = [
                ("2026-01-15","CSA Pre-Sales Deposit",      "4000",15600.00,"1000",15600.00,1),
                ("2026-02-10","Seed Order",                 "5000", 4280.00,"1000", 4280.00,2),
                ("2026-03-05","Compost delivery",           "5010", 1800.00,"2000", 1800.00,3),
                ("2026-04-15","Seasonal payroll Apr 1-15",  "5110", 3200.00,"1000", 3200.00,4),
                ("2026-05-03","Farmers market wk 1",        "1000", 1840.00,"4010", 1840.00,5),
                ("2026-05-15","Invoice — The Birch",        "1200", 2100.00,"4020", 2100.00,5),
                ("2026-06-01","Payment rec'd — The Birch",  "1000", 2100.00,"1200", 2100.00,6),
                ("2026-06-12","Tractor hydraulic repair",   "5210",  780.00,"1000",  780.00,6),
                ("2026-07-06","Farmers market wk of 7/6",   "1000", 3240.00,"4010", 3240.00,7),
                ("2026-08-01","Farm insurance annual",      "5500", 4200.00,"1000", 4200.00,8),
                ("2026-09-01","Land rent Q3",               "5300", 2850.00,"1000", 2850.00,9),
                ("2026-10-10","Agronomy consulting income", "1000", 1350.00,"4030", 1350.00,10),
            ]
            ok = 0
            for date_,memo,dr_acct,dr_amt,cr_acct,cr_amt,period in entries:
                try:
                    fp_id = first(c,
                        "SELECT FiscalPeriodID FROM FiscalPeriods WHERE FiscalYearID=:fy AND PeriodNumber=:pn AND BusinessID=:b",
                        {"fy":fy_id,"pn":period,"b":BID})
                    je_id = first(c, """
                        INSERT INTO JournalEntries
                            (BusinessID,FiscalYearID,FiscalPeriodID,EntryDate,Description,TotalAmount,IsPosted)
                        OUTPUT INSERTED.EntryID
                        VALUES (:b,:fy,:fp,:d,:m,:amt,1)
                    """, {"b":BID,"fy":fy_id,"fp":fp_id,"d":date_,"m":memo,"amt":dr_amt})
                    if je_id and dr_acct in acct_map and cr_acct in acct_map:
                        q(c, "INSERT INTO JournalEntryLines (EntryID,AccountID,DebitAmount,CreditAmount,Description) VALUES (:je,:acct,:da,0,:m)",
                          {"je":je_id,"acct":acct_map[dr_acct],"da":dr_amt,"m":memo})
                        q(c, "INSERT INTO JournalEntryLines (EntryID,AccountID,DebitAmount,CreditAmount,Description) VALUES (:je,:acct,0,:ca,:m)",
                          {"je":je_id,"acct":acct_map[cr_acct],"ca":cr_amt,"m":memo})
                        ok += 1
                except Exception as e:
                    print(f"  ! entry skip: {e}")
            print(f"  + {ok} journal entries")
        except Exception as e:
            print(f"  ! accounting error: {e}")
    else:
        print(f"  skipped ({existing_fy} fiscal years exist)")

    # ── ANIMALS ───────────────────────────────────────────────────────────────
    section("animals")
    existing_animals = first(c, "SELECT COUNT(*) FROM Animals WHERE BusinessID=:b", {"b": BID})
    if existing_animals == 0:
        spec_rows = c.execute(text("SELECT TOP 3 SpeciesID FROM species")).fetchall()
        spec_id = spec_rows[0][0] if spec_rows else None
        animals = [
            ("GVF-C001","Angus Bull",          "Angus","Male",  "adult_male",  "Black",              "2021-03-12"),
            ("GVF-C002","Rosie",               "Angus","Female","adult_female","Black",              "2020-05-18"),
            ("GVF-C003","Daisy",               "Angus","Female","adult_female","Black",              "2021-08-02"),
            ("GVF-C004","Clover",              "Angus","Female","adult_female","Black",              "2022-04-25"),
            ("GVF-C005","Calf #5",             "Angus","Female","young_female","Black",              "2026-02-14"),
            ("GVF-C006","Calf #6",             "Angus","Male",  "young_male",  "Black",              "2026-03-01"),
            ("GVF-P001","Berkshire Boar",      "Berkshire","Male","adult_male","Black",              "2022-07-10"),
            ("GVF-P002","Sow Maple",           "Berkshire","Female","adult_female","Black",          "2022-09-15"),
            ("GVF-P003","Sow Acorn",           "Berkshire","Female","adult_female","Black",          "2023-01-20"),
            ("GVF-P004","Gilt Birch",          "Berkshire","Female","young_female","Black",          "2025-06-05"),
            ("GVF-H001","Flock 1 - RIR",       "Rhode Island Red","Female","adult_female","Red",    "2025-03-01"),
            ("GVF-H002","Flock 2 - Barred Rock","Barred Rock","Female","adult_female","Black/White","2025-03-01"),
        ]
        ok = 0
        for reg, name, breed, gender, category, color, dob in animals:
            try:
                q(c, """
                    INSERT INTO Animals (BusinessID,FullName,RegistrationNumber,BreedName,
                        Gender,Category,Color1,DOB,SpeciesID)
                    VALUES (:b,:n,:reg,:breed,:gender,:cat,:color,:dob,:spec)
                """, {"b":BID,"n":name,"reg":reg,"breed":breed,"gender":gender,
                      "cat":category,"color":color,"dob":dob,"spec":spec_id})
                ok += 1
            except Exception as e:
                print(f"  ! {name}: {e}")
        print(f"  + {ok} animals")
    else:
        print(f"  skipped ({existing_animals} animals exist)")

    # ── PRODUCE INVENTORY ─────────────────────────────────────────────────────
    section("produce inventory")
    try:
        existing_prod = first(c, "SELECT COUNT(*) FROM Produce WHERE BusinessID=:b", {"b": BID})
        if existing_prod == 0:
            ingredients = c.execute(text(
                "SELECT TOP 12 IngredientID, IngredientName FROM Ingredients ORDER BY IngredientID"
            )).fetchall()
            measure_id = first(c, "SELECT TOP 1 MeasurementID FROM MeasurementLookup")
            if ingredients and measure_id:
                for i, (ing_id, ing_name) in enumerate(ingredients):
                    ws = round(1.50 + i * 0.35, 2)
                    rt = round(ws * 1.6, 2)
                    q(c, """
                        INSERT INTO Produce (BusinessID,IngredientID,Quantity,MeasurementID,
                            WholesalePrice,RetailPrice,ShowProduce,AvailableDate)
                        VALUES (:b,:i,50,:m,:ws,:rt,1,GETDATE())
                    """, {"b":BID,"i":ing_id,"m":measure_id,"ws":ws,"rt":rt})
                print(f"  + {len(ingredients)} produce items")
            else:
                print("  ! no ingredients/measurements found — skipped")
        else:
            print(f"  skipped ({existing_prod} items exist)")
    except Exception as e:
        print(f"  ! produce skip: {e}")

    # ── FOOD WANTED ───────────────────────────────────────────────────────────
    section("food wanted")
    try:
        existing_fw = first(c, "SELECT COUNT(*) FROM FoodWantedAds WHERE BusinessID=:b", {"b": BID})
        if existing_fw == 0:
            for title, desc, cat, price, qty, unit in [
                ("Seeking: Certified Organic Hay - 200 Bales",
                 "Looking for certified organic grass hay for our beef herd. Need 200 square bales, October-November delivery. Dutchess or Columbia County NY preferred. Will consider multi-year purchase agreement.",
                 "Hay & Forage", 8.50, 200, "bale"),
                ("Seeking: Locally Grown Feed Oats - 2,000 lbs",
                 "Looking for locally grown oats, feed grade or better, for pastured pork. We use roughly 500 lbs/month. Interested in a direct annual grain contract with a local farmer.",
                 "Grains", 0.28, 2000, "lb"),
            ]:
                q(c, """
                    INSERT INTO FoodWantedAds (BusinessID,Title,Description,Category,
                        TargetPricePerUnit,QuantityNeeded,UnitLabel,IsActive,ContactEmail)
                    VALUES (:b,:t,:d,:cat,:p,:qty,:unit,1,'gvfarm@email.com')
                """, {"b":BID,"t":title,"d":desc,"cat":cat,"p":price,"qty":qty,"unit":unit})
                print(f"  + {title[:60]}")
        else:
            print(f"  skipped ({existing_fw} ads exist)")
    except Exception as e:
        print(f"  ! food wanted skip: {e}")

    # ── NOTIFICATIONS ─────────────────────────────────────────────────────────
    section("notifications")
    try:
        existing_notif = first(c,
            "SELECT COUNT(*) FROM AppNotifications WHERE BusinessID=:b", {"b": BID})
        if existing_notif == 0:
            for title, body, ntype in [
                ("CSA Season Open - 23 Signups So Far",
                 "Your 2026 Full Share CSA has 23 of 55 spots filled (42%). Half Share has 11 of 30. Consider sending a reminder to your waitlist.",
                 "info"),
                ("GAP Certification Renewal Due in 90 Days",
                 "Your USDA GAP/GHP certificate expires 2026-07-31. Contact USDA AMS to schedule your renewal inspection before it lapses.",
                 "warning"),
                ("New Job Application - Lead Market Garden Grower",
                 "A new application was received from Jordan Morales for Lead Market Garden Grower. Review in the Job Board section.",
                 "info"),
                ("Field Health Alert - North Field NDVI Drop",
                 "North Field (Field 2) NDVI score dropped from 0.71 to 0.54 between your last two satellite passes. Consider scouting for pest pressure or drought stress.",
                 "warning"),
            ]:
                q(c, """
                    INSERT INTO AppNotifications (BusinessID,Title,Body,NotifType,IsRead)
                    VALUES (:b,:t,:body,:nt,0)
                """, {"b":BID,"t":title,"body":body,"nt":ntype})
            print("  + 4 notifications")
        else:
            print(f"  skipped ({existing_notif} notifications exist)")
    except Exception as e:
        print(f"  ! notifications skip: {e}")

print("\nDone — all sections attempted for BusinessID=15671")
