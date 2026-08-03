"""
seed_activity_journal_15665.py  -  FieldActivityLog + FieldNote for BusinessID=15665, FieldID=30

Run from Backend/:
    ./venv/Scripts/python.exe scripts/seeds/seed_activity_journal_15665.py
"""
import os
from datetime import datetime, timedelta, date
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
engine = create_engine(
    f"mssql+pymssql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_SERVER')}/{os.getenv('DB_NAME')}",
    echo=False, pool_pre_ping=True,
)
db = sessionmaker(bind=engine)()

BID, FID = 15665, 30

def d(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat()

# ── ACTIVITY LOG ─────────────────────────────────────────────────────────────
# (days_ago, type, product, rate, unit, operator, notes)
ACTIVITIES = [
    (2, "Fungicide", "Headline AMP", 8.0, "fl oz/ac", "J. Kowalski",
     "Broadcast application targeting gray leaf spot and northern corn leaf blight. "
     "Nozzle pressure 40 PSI, travel speed 12 mph. Full canopy coverage achieved."),

    (5, "Irrigation", None, 1.2, "in", "Auto pivot",
     "Pivot cycle runtime 6.5 hours covering full field. Soil moisture deficit at trigger point. "
     "Post-run probe reading returned to 26% in zone 3."),

    (8, "Herbicide", "Roundup PowerMAX", 32.0, "fl oz/ac", "T. Brennan",
     "POST application targeting waterhemp and volunteer corn. Added ammonium sulfate at 17 lb/100 gal. "
     "Wind 4 mph NW, temp 74 F - good spray conditions."),

    (12, "Fertilizer", "28% UAN", 60.0, "lb N/ac", "J. Kowalski",
     "Side-dress nitrogen application via coulter injection at V5 growth stage. Applied at 8-inch depth, "
     "30-inch row spacing. Rate based on pre-side-dress nitrate test result of 14 ppm."),

    (18, "Irrigation", None, 0.9, "in", "Auto pivot",
     "Supplemental irrigation cycle. Forecast showed 10-day dry period. "
     "Soil deficit estimated at 0.8 inches before application."),

    (22, "Scouting", None, None, None, "T. Brennan",
     "Full field walk at V6. Noted strong stand uniformity - final plant population estimated at 33,400 plants/ac. "
     "No disease or insect pressure observed. Weed escapes flagged in south block."),

    (28, "Herbicide", "Acuron", 3.0, "qt/ac", "T. Brennan",
     "Pre-emerge pass applied within 3 days of planting. Incorporated with 0.5 inch rain event the following day. "
     "Excellent activation conditions."),

    (31, "Planting", "DKC 62-08 RIB", 32500.0, "seeds/ac", "J. Kowalski",
     "Planting completed in 2 days. Avg soil temp 56 F at 2-inch depth. Seeding depth 2.0 inches. "
     "Population monitor showed consistent spacing - CV under 18% across all rows."),

    (36, "Tillage", None, None, None, "J. Kowalski",
     "Field cultivator pass at 4-inch depth for seedbed prep. Residue from last season soybean incorporated. "
     "Two passes required in northwest corner due to compaction zone."),

    (40, "Soil Sample", None, None, None, "AgVantage Lab",
     "Grid sampling completed - 2.5-acre grid, 0-8 inch depth. 14 cores composited per sample, 18 samples total. "
     "Results received and loaded into prescription software."),

    (48, "Fertilizer", "MAP 11-52-0", 120.0, "lb/ac", "T. Brennan",
     "Fall phosphorus and potassium application based on soil test recommendations. Dry broadcast, "
     "incorporated with field cultivator pass. Rate variable by zone: high zone 90 lb, low zone 150 lb."),

    (55, "Harvest", "Previous crop - soy", 58.2, "bu/ac", "J. Kowalski",
     "Soybean harvest completed. Final yield 58.2 bu/ac - 3.1 bu above APH. Moisture at bin 13.4%. "
     "Combine header height 3 inches. Straw spread width 22 feet for residue management."),
]

print("Inserting FieldActivityLog rows...")
for days_ago, atype, product, rate, unit, operator, notes in ACTIVITIES:
    db.execute(text("""
        INSERT INTO FieldActivityLog
            (FieldID, BusinessID, ActivityDate, ActivityType, Product, Rate, RateUnit, OperatorName, Notes, CreatedAt)
        VALUES (:fid, :bid, :dt, :type, :prod, :rate, :unit, :op, :notes, GETUTCDATE())
    """), {
        "fid": FID, "bid": BID, "dt": d(days_ago), "type": atype,
        "prod": product, "rate": rate, "unit": unit, "op": operator, "notes": notes,
    })
    print(f"  {atype:<14s}  {d(days_ago)}")

# ── FIELD JOURNAL (FieldNote) ─────────────────────────────────────────────────
# (days_ago, category, title, content, severity, lat, lon)
NOTES = [
    (1, "Observation", "Canopy closure reached - disease pressure window opening",
     "Walked the field this afternoon. Canopy has closed between rows - humidity will be trapping in the lower "
     "leaf layers from here through pollination. With gray leaf spot already present in the lower canopy, this is "
     "the highest-risk window for disease progression. Fungicide applied yesterday should provide 14-21 days of "
     "protection. Will re-scout at day 10 to assess residual efficacy.",
     "Medium", 44.4282, -93.2575),

    (3, "Decision", "Confirmed fungicide timing - did not wait for silk",
     "Called agronomist James Prieto at AgVantage this morning to discuss whether to hold on fungicide until VT/R1. "
     "Given the early gray leaf spot pressure already visible and the 7-day forecast showing 70%+ humidity, we agreed "
     "not to wait. Applied Headline AMP at VT. Cost per acre: $14.80 product + $8 application = $22.80. "
     "Break-even is roughly 5 bu/ac yield protection.",
     "Low", 44.4275, -93.2568),

    (6, "Weather", "Hail event - minor canopy damage, no yield impact expected",
     "Hail storm moved through at 9:40 PM. Stones roughly dime-sized. Walked the north third of the field at 7 AM - "
     "some leaf shredding on upper canopy, no stalk bruising visible. Ear shanks intact. At R2 stage, hail damage of "
     "this level is unlikely to affect final yield unless infection follows bruising. Will monitor for stalk rots "
     "over next 2 weeks.",
     "Medium", 44.4291, -93.2560),

    (10, "Scouting", "Pollination complete - silks brown, good tip fill observed",
     "Pollination window closed approximately 3 days ago based on silk browning. Checked 20 random ears - silk pull "
     "shows complete kernel set to within 0.5 inch of tip on most ears. One ear in the southeast corner showed "
     "8-row tip abortion - likely related to heat stress event on July 14. Estimated 3% of field affected. "
     "No action - within normal range.",
     "Low", 44.4266, -93.2591),

    (14, "Equipment", "Pivot bearing replaced - zone 2 coverage restored",
     "Pivot arm segment 4 developed a grinding noise on Monday. Shut down immediately. Found worn center-drive bearing. "
     "Part ordered same day, arrived Wednesday morning. Contractor replaced bearing and realigned arm. "
     "Total downtime 38 hours. Missed one irrigation cycle in zone 2 - soil moisture dropped to 19% before repair "
     "completed. No visible crop stress.",
     "High", 44.4284, -93.2563),

    (19, "Planning", "V5 stand count complete - evaluating final population",
     "Stand count conducted at 10 random locations, 17.5-foot row segments. Average final population: 33,420 plants/acre. "
     "Target was 33,000. Emergence was 98.4% of seeded population - excellent for field conditions. "
     "No replanting needed. Noted 2 skips in row 14 near headland - likely compaction from previous year tire tracks. "
     "Will note GPS coordinates for potential zone adjustment next year.",
     "Low", 44.4278, -93.2579),

    (25, "Observation", "Compaction zone confirmed in NW corner - tillage planned",
     "Probed the northwest corner following the field cultivator pass. Resistance at 7-9 inches suggests compaction pan - "
     "penetrometer reading 280 PSI at 8 inches. Rest of field reads 150-200 PSI at same depth. This is the third "
     "consecutive year this corner has been difficult to work. Recommend subsoil tillage (Paratill or ripper) at "
     "14-inch depth this fall when soil is at field capacity. Will flag zone in prescription map.",
     "High", 44.4296, -93.2556),

    (33, "Market", "Locked in fall delivery contract - $4.82 net",
     "Signed 5,000-bushel fall delivery contract this morning at elevator. Dec futures at $5.14, basis -$0.32 = "
     "$4.82 net. APH is 197 bu/ac - this contract covers roughly 25% of projected production. "
     "Will watch for basis improvement in September/October before locking in remainder. "
     "Current on-farm storage capacity is 18,000 bushels.",
     "Low", None, None),

    (42, "Planning", "Pre-plant variable-rate fertilizer application review",
     "Reviewed imagery from variable-rate P/K application spread. Zones tracked closely to the management zone map "
     "generated from 3-year NDVI composite. High-performing zones received 90 lb MAP vs. 150 lb in low-performing zones. "
     "Total product use was 11% lower than flat-rate application would have been. Soil test follow-up in fall will "
     "verify whether differential rates are moving zone averages in the right direction.",
     "Low", None, None),

    (50, "Observation", "Pre-plant soil conditions - good moisture, slight surface crust",
     "Field conditions assessed one week before target planting date. Soil temperature at 2 inches: 51 F - slightly "
     "below ideal 55 F threshold for this hybrid. Surface has a light crust from April rain events but breaks easily "
     "with light tillage. Subsoil moisture is excellent - profile to 3 feet is at field capacity from snowmelt and "
     "spring rains. Plan to delay planting 5-7 days to let soil warm. Neighbor fields with early-planted corn "
     "showing uneven emergence.",
     "Low", 44.4280, -93.2572),
]

print("\nInserting FieldNote (journal) rows...")
for days_ago, category, title, content, severity, lat, lon in NOTES:
    db.execute(text("""
        INSERT INTO FieldNote
            (FieldID, BusinessID, NoteDate, Category, Title, Content, Severity,
             Latitude, Longitude, CreatedAt, UpdatedAt)
        VALUES (:fid, :bid, :dt, :cat, :title, :content, :sev,
                :lat, :lon, GETUTCDATE(), GETUTCDATE())
    """), {
        "fid": FID, "bid": BID, "dt": d(days_ago), "cat": category,
        "title": title, "content": content, "sev": severity,
        "lat": lat, "lon": lon,
    })
    print(f"  [{severity:<6s}] {category:<12s}  {d(days_ago)}  {title[:50]}")

db.commit()
print(f"\nDone. {len(ACTIVITIES)} activity log rows + {len(NOTES)} journal rows inserted.")
