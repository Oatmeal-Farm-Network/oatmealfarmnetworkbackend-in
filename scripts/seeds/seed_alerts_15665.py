"""
seed_alerts_15665.py  —  Seed FieldScout alert rows for BusinessID=15665, FieldID=30

Run from Backend/:
    ./venv/Scripts/python.exe scripts/seeds/seed_alerts_15665.py
"""
import os, sys
from datetime import datetime, timedelta
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
FID = 30

def dt(days_ago=0, hours_ago=0):
    return (datetime.utcnow() - timedelta(days=days_ago, hours=hours_ago)).strftime('%Y-%m-%d %H:%M:%S')

SCOUTS = [
    # (days_ago, category, severity, notes, lat, lon)
    (
        1, "Disease", "Critical",
        "Late blight confirmed on approximately 30% of canopy in the northwest block. "
        "Dark water-soaked lesions with white sporulation visible on leaf undersides. "
        "Immediate fungicide application recommended — mancozeb or chlorothalonil within 24 hours.",
        44.4280, -93.2580,
    ),
    (
        2, "Pest", "High",
        "Soybean aphid colony detected along field margin rows 1–8. Estimated 400–600 aphids "
        "per plant on several stems — approaching economic threshold of 250 per plant. "
        "Scout adjacent rows before making spray decision. Consider pyrethroid application.",
        44.4275, -93.2571,
    ),
    (
        3, "Irrigation", "High",
        "Visible wilting and leaf rolling observed on corn in the east center zone during "
        "afternoon hours. Soil moisture probe reading 18% — below the 22% trigger point. "
        "Run irrigation cycle as soon as possible. Estimated deficit: 1.2 inches.",
        44.4283, -93.2565,
    ),
    (
        5, "Weed", "High",
        "Waterhemp escapes exceeding 4 inches in height across roughly 6 acres in the south "
        "third of the field. Plants are at competitive size and approaching flowering in some "
        "spots. POST herbicide window is closing — apply glyphosate + dicamba within 3 days.",
        44.4268, -93.2588,
    ),
    (
        7, "Nutrient", "High",
        "Interveinal chlorosis observed on young corn leaves in a 2-acre area near the center "
        "pivot corner. Pattern is consistent with iron deficiency, likely linked to high-pH "
        "soil pocket identified in last season's soil samples. Consider foliar iron chelate spray.",
        44.4291, -93.2559,
    ),
    (
        9, "Disease", "High",
        "Gray leaf spot lesions present on lower and mid canopy leaves in the southeast corner. "
        "Lesion density is moderate — approximately 10% of leaf area affected. "
        "Monitor for progression to upper canopy. If lesions reach ear leaf, apply fungicide.",
        44.4262, -93.2594,
    ),
    (
        11, "Pest", "Critical",
        "Western corn rootworm adult emergence confirmed — trap catches of 14 beetles per trap "
        "per day, well above the 5-per-day threshold. Silk feeding damage observed on 20% of "
        "ears sampled. Node injury score estimated at 1.5. Assess for silk clipping immediately.",
        44.4277, -93.2577,
    ),
    (
        13, "Irrigation", "High",
        "Pressure differential between zones 2 and 4 dropped 18 PSI below baseline during last "
        "irrigation cycle — possible emitter clogging or line break near pivot point 7. "
        "Uniform coverage compromised. Inspect pivot arm and lateral lines before next cycle.",
        44.4286, -93.2563,
    ),
]

print(f"\nSeeding {len(SCOUTS)} FieldScout alert rows for BusinessID={BID}, FieldID={FID}...")

inserted = 0
for days_ago, category, severity, notes, lat, lon in SCOUTS:
    db.execute(text("""
        INSERT INTO FieldScout
            (FieldID, BusinessID, ObservedAt, Category, Severity, Notes, Latitude, Longitude, CreatedAt)
        VALUES
            (:fid, :bid, :observed, :cat, :sev, :notes, :lat, :lon, GETUTCDATE())
    """), {
        "fid":      FID,
        "bid":      BID,
        "observed": dt(days_ago),
        "cat":      category,
        "sev":      severity,
        "notes":    notes,
        "lat":      lat,
        "lon":      lon,
    })
    print(f"  [{severity:8s}] {category:12s}  {days_ago} day(s) ago")
    inserted += 1

db.commit()
print(f"\nDone. {inserted} alert rows inserted.")
print(f"View at: http://localhost:5173/precision-ag/alerts?BusinessID={BID}&FieldID={FID}")
