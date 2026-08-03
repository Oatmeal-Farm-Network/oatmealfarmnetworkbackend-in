"""
seed_carbon_15665.py  -  FieldSoilSample + CropRotationEntry for BusinessID=15665, FieldID=30

Soil samples span 5 years showing an upward OM trend (2.8 -> 3.4%).
Crop rotation spans 8 years with corn-soy rotation + 4 cover-crop seasons.

Run from Backend/:
    ./venv/Scripts/python.exe scripts/seeds/seed_carbon_15665.py
"""
import os
from datetime import date
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

# ── SOIL SAMPLES ──────────────────────────────────────────────────────────────
# Annual composite grid samples (18-point, 0-8 inch depth) showing organic
# matter trending upward from 2.8% -> 3.4% over five years.
#
# (sample_date, label, lat, lon, depth_cm,
#  pH, OM, N, P, K, S, Ca, Mg, CEC, notes)
SOIL_SAMPLES = [
    ("2020-10-14", "2020 Annual Grid Composite", 44.4280, -93.2575, 20,
     6.4, 2.8, 12.0, 28.0, 185.0,  9.0, 1820.0, 210.0, 16.2,
     "Baseline grid sample. 18 cores composited across 2.5-acre grid. "
     "Low OM consistent with reduced tillage transition beginning this season. "
     "P and K levels adequate. pH slightly low — lime recommended at 1.5 ton/ac."),

    ("2021-10-18", "2021 Annual Grid Composite", 44.4275, -93.2570, 20,
     6.5, 2.9, 14.0, 31.0, 192.0, 10.0, 1850.0, 215.0, 16.4,
     "Second year of no-till and cover crop program. OM showing early upward movement. "
     "Lime application from 2020 raised pH 0.1 unit. P trending up from manure history. "
     "Recommend continuing cereal rye cover crop."),

    ("2022-10-11", "2022 Annual Grid Composite", 44.4283, -93.2565, 20,
     6.6, 3.1, 15.0, 35.0, 198.0, 11.0, 1890.0, 218.0, 16.8,
     "Third year of program. OM gain of 0.2% from 2021 — statistically meaningful. "
     "CEC increasing alongside OM as expected. Phosphorus levels building in zones 2 and 3. "
     "NW compaction zone (identified Apr 2022) shows lower OM — 2.7% vs. field average 3.1%."),

    ("2023-10-09", "2023 Annual Grid Composite", 44.4270, -93.2580, 20,
     6.6, 3.2, 16.0, 38.0, 205.0, 11.0, 1920.0, 224.0, 17.1,
     "Consistent improvement. Cover crop diversity (crimson clover + cereal rye mix) "
     "may be contributing to accelerated OM gain vs. single-species cover. "
     "Potassium levels excellent across all zones. Sulfur adequate but watch for deficiency "
     "on sandier knolls."),

    ("2024-10-15", "2024 Annual Grid Composite", 44.4286, -93.2558, 20,
     6.7, 3.4, 18.0, 42.0, 212.0, 12.0, 1960.0, 229.0, 17.5,
     "Strong OM result — 0.6 percentage point gain over baseline in 4 years. "
     "Field is performing in the top quartile for OM accumulation rate in this region. "
     "Calcium and CEC continue upward trend. P reaching luxury consumption levels in zone 3 — "
     "consider reducing MAP rate in high zone by 20 lb next season."),
]

print("Inserting FieldSoilSample rows...")
for row in SOIL_SAMPLES:
    (sdate, label, lat, lon, depth,
     ph, om, n, p, k, s, ca, mg, cec, notes) = row
    db.execute(text("""
        INSERT INTO FieldSoilSample
            (FieldID, BusinessID, SampleDate, SampleLabel, Latitude, Longitude,
             Depth_cm, pH, OrganicMatter, Nitrogen, Phosphorus, Potassium,
             Sulfur, Calcium, Magnesium, CEC, Notes, CreatedAt)
        VALUES
            (:fid, :bid, :dt, :label, :lat, :lon,
             :depth, :ph, :om, :n, :p, :k,
             :s, :ca, :mg, :cec, :notes, GETUTCDATE())
    """), {
        "fid": FID, "bid": BID, "dt": sdate, "label": label,
        "lat": lat, "lon": lon, "depth": depth,
        "ph": ph, "om": om, "n": n, "p": p, "k": k,
        "s": s, "ca": ca, "mg": mg, "cec": cec, "notes": notes,
    })
    print(f"  {sdate}  OM={om:.1f}%  pH={ph}  CEC={cec}")

# ── CROP ROTATION ─────────────────────────────────────────────────────────────
# 8-season corn-soy rotation with 4 cover-crop seasons. Cover crops are
# listed as separate entries (IsCoverCrop=True) planted fall of the prior year
# and terminated spring of the listed SeasonYear.
#
# (season_year, crop, variety, planting, harvest, yield_amt, yield_unit,
#  is_cover, notes)
ROTATIONS = [
    (2018, "Corn", "DKC 62-08 RIB",
     "2018-05-02", "2018-10-08", 198.4, "bu/ac", False,
     "Strong season. Final population 33,200 plants/ac. Excellent standability — "
     "no lodging despite 70 mph wind event in August. Harvested at 16.2% moisture."),

    (2019, "Cereal Rye", "Aroostook",
     "2018-09-28", "2019-05-10", None, None, True,
     "Cover crop terminated with burndown at 18-inch height prior to soybean planting. "
     "Biomass estimated at 4,200 lb/ac dry weight. Excellent weed suppression in no-till strips. "
     "Nitrogen credit estimated 20 lb/ac from rye biomass."),

    (2019, "Soybean", "Asgrow AG36X8",
     "2019-05-18", "2019-10-02", 55.2, "bu/ac", False,
     "Good yield for field history. No-till into cereal rye residue — some hairpinning "
     "in heavy residue areas but emergence uniform at 96%. IDC manageable with seed treatment."),

    (2020, "Crimson Clover + Oats", "Dixie Crimson / Canmore",
     "2019-08-22", "2020-05-14", None, None, True,
     "Multi-species cover mix. Oats winterkilled as expected, clover overwintered well. "
     "High biomass spring termination at 22 inches. Nitrogen fixation estimated 40-60 lb/ac. "
     "Attracted early beneficial insect populations."),

    (2020, "Corn", "Pioneer P1197AM",
     "2020-05-06", "2020-10-14", 201.5, "bu/ac", False,
     "APH 197 bu/ac — slightly above average. Excellent nitrogen response from clover credit. "
     "Reduced N rate by 20 lb/ac vs. prior year with no yield penalty. "
     "First year with variable-rate seeding — low zone at 30,500, high zone at 34,000 seeds/ac."),

    (2021, "Cereal Rye", "Elbon",
     "2020-09-30", "2021-05-08", None, None, True,
     "Third cover crop in four years. Established after corn harvest in favorable conditions. "
     "Winter survival excellent. Terminated at first hollow stem. Residue breakdown faster than "
     "Aroostook variety — soybean planting conditions improved."),

    (2021, "Soybean", "Dekalb DKB31-51",
     "2021-05-16", "2021-09-28", 58.1, "bu/ac", False,
     "Best soybean yield to date on this field. OM improvements from cover crop program "
     "contributing to improved water holding capacity — field held up well through July dry spell. "
     "No SCN pressure detected in fall soil test."),

    (2022, "Corn", "DKC 64-35",
     "2022-05-03", "2022-10-11", 205.3, "bu/ac", False,
     "Record yield for field. Variable-rate prescription refined with 3-year NDVI composite. "
     "Fungicide at VT delivered estimated 8 bu/ac protection vs. untreated strips. "
     "Gray leaf spot pressure moderate — fungicide timing was correct call."),

    (2023, "Cereal Rye + Hairy Vetch", "Aroostook / Auburn",
     "2022-09-25", "2023-05-12", None, None, True,
     "Legume addition to cover mix. Hairy vetch winterkill was partial — 60% survival. "
     "Where it survived, nitrogen fixation estimated 50 lb/ac. Terminated 10 days before "
     "planting due to forecast rain. Some regrowth required follow-up burndown pass."),

    (2023, "Soybean", "Asgrow AG38X7",
     "2023-05-22", "2023-09-30", 60.4, "bu/ac", False,
     "Second consecutive above-APH year. White mold risk was low due to dry July. "
     "Harvest aid applied Sept 18 — allowed 5-day early harvest. Delivered at 12.8% moisture. "
     "Field ranked in top 20% of county for soybean yield per FSA records."),

    (2024, "Corn", "DKC 62-08 RIB",
     "2024-05-04", "2024-10-15", 208.7, "bu/ac", False,
     "New field record. Excellent early season weather followed by adequate July rainfall. "
     "Harvest was delayed 5 days by wet conditions — final 200 ac completed Oct 15. "
     "Stover managed with high-spread chopper head to maximize residue distribution."),

    (2025, "Soybean", "Asgrow AG40X7",
     "2025-05-12", None, None, "bu/ac", False,
     "Current season. Planted into cereal rye residue terminated May 5. "
     "Emergence count at V1 shows 96.2% of targeted population. Stand is uniform. "
     "Forecast for June looks favorable — watching for SDS early infection window."),
]

print("\nInserting CropRotationEntry rows...")
for row in ROTATIONS:
    (yr, crop, variety, plant, harvest, yld, yunit, is_cover, notes) = row
    db.execute(text("""
        INSERT INTO CropRotationEntry
            (FieldID, BusinessID, SeasonYear, CropName, Variety,
             PlantingDate, HarvestDate, YieldAmount, YieldUnit,
             IsCoverCrop, Notes, CreatedAt)
        VALUES
            (:fid, :bid, :yr, :crop, :variety,
             :plant, :harvest, :yld, :yunit,
             :cover, :notes, GETUTCDATE())
    """), {
        "fid": FID, "bid": BID, "yr": yr, "crop": crop, "variety": variety,
        "plant": plant, "harvest": harvest, "yld": yld, "yunit": yunit,
        "cover": 1 if is_cover else 0, "notes": notes,
    })
    tag = "(cover)" if is_cover else ""
    print(f"  {yr}  {crop:<28s} {tag}  {'-> ' + str(yld) + ' ' + str(yunit) if yld else ''}")

db.commit()
print(f"\nDone. {len(SOIL_SAMPLES)} soil samples + {len(ROTATIONS)} rotation entries inserted.")
print(f"View at: http://localhost:5173/precision-ag/carbon?BusinessID={BID}&FieldID={FID}")
