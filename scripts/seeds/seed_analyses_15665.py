"""
seed_analyses_15665.py  -  FieldBiomassAnalysis for BusinessID=15665, FieldID=30
Simulates a full corn-season NDVI arc (planting through harvest).

Run from Backend/:
    ./venv/Scripts/python.exe scripts/seeds/seed_analyses_15665.py
"""
import os, json
from datetime import datetime, timedelta
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

def dt(days_ago):
    return (datetime.utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")

def make_features(ndvi, ndre=None, evi=None, health=None):
    """Build a FeaturesJSON payload compatible with _get_index + _latest_analyses fallback."""
    ndre  = ndre  if ndre  is not None else round(ndvi * 0.72, 4)
    evi   = evi   if evi   is not None else round(ndvi * 0.85, 4)
    gndvi = round(ndvi * 0.91, 4)
    ndwi  = round(ndvi * 0.38, 4)
    msavi = round(ndvi * 0.88, 4)
    health_score = health if health is not None else round(min(100, max(0, ndvi * 130)), 1)
    return json.dumps({
        "health_score": health_score,
        "vegetation_indices": [
            {"index_type": "NDVI",   "mean": ndvi,  "min": round(ndvi*0.78, 4), "max": round(ndvi*1.08, 4), "std": 0.032},
            {"index_type": "NDRE",   "mean": ndre,  "min": round(ndre*0.80, 4), "max": round(ndre*1.06, 4), "std": 0.021},
            {"index_type": "EVI",    "mean": evi,   "min": round(evi*0.79, 4),  "max": round(evi*1.07, 4),  "std": 0.028},
            {"index_type": "GNDVI",  "mean": gndvi, "min": round(gndvi*0.81, 4),"max": round(gndvi*1.05, 4),"std": 0.019},
            {"index_type": "NDWI",   "mean": ndwi,  "min": round(ndwi*0.75, 4), "max": round(ndwi*1.12, 4), "std": 0.015},
            {"index_type": "MSAVI2", "mean": msavi, "min": round(msavi*0.80, 4),"max": round(msavi*1.06, 4),"std": 0.025},
        ],
    })

# Corn-season NDVI arc:
#   days_ago, ndvi,   health note
ANALYSES = [
    # Recent — late-season / grain fill (high NDVI, starting to senesce)
    (2,   0.71, 92),   # R4 dough — near peak
    (8,   0.74, 95),   # R3 milk — peak canopy
    (14,  0.76, 97),   # R2 blister — maximum green
    (20,  0.75, 96),   # VT/R1 pollination
    (27,  0.72, 93),   # V18 approaching tassel
    (34,  0.68, 88),   # V14
    (41,  0.62, 81),   # V10 — rapid growth
    (50,  0.54, 70),   # V6 — canopy filling
    (60,  0.41, 53),   # V4
    (72,  0.28, 36),   # V2 emergence — low NDVI, stressed patch visible
    (85,  0.18, 23),   # Early post-emerge (sparse canopy)
    (100, 0.09, 12),   # Pre-emergence / bare soil
]

print(f"Inserting {len(ANALYSES)} FieldBiomassAnalysis rows for BusinessID={BID}, FieldID={FID}...")
for days_ago, ndvi, health in ANALYSES:
    features = make_features(ndvi, health=health)
    biomass_kgha = round(ndvi * 4200, 1)   # rough green biomass estimate
    db.execute(text("""
        INSERT INTO FieldBiomassAnalysis
            (FieldID, BusinessID, Source, BiomassKgHa, Confidence,
             CapturedAt, ModelVersion, FeaturesJSON, CreatedAt)
        VALUES (:fid, :bid, 'satellite', :bio, :conf,
                :captured, 'local-seed-v1', :features, GETUTCDATE())
    """), {
        "fid": FID, "bid": BID,
        "bio":      biomass_kgha,
        "conf":     round(min(0.95, 0.5 + ndvi * 0.6), 3),
        "captured": dt(days_ago),
        "features": features,
    })
    print(f"  {dt(days_ago)[:10]}  NDVI={ndvi:.2f}  health={health:3d}  biomass={biomass_kgha:.0f} kg/ha")

db.commit()
print(f"\nDone. {len(ANALYSES)} analyses inserted.")
print(f"View at: http://localhost:5173/precision-ag/yield-forecast?BusinessID={BID}&FieldID={FID}")
