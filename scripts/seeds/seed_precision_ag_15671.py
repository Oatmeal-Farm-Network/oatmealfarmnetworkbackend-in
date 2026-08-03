"""
seed_precision_ag_15671.py — Precision Ag demo data for BusinessID=15671 (Food World)
Creates Fields, Analysis + VegetationIndex history, FieldNotes, FieldActivityLog,
FieldSoilSamples, FieldScout, FieldPrescription, FieldMaturitySample, and Alerts.
Idempotent: skips by Name for fields, by date+field for analyses.
Run from: Backend/oatmealfarmnetworkbackend/
"""
import sys, datetime, math, json, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import get_db
from sqlalchemy import text

BID = 15671
PEOPLE_ID = 5705
db = next(get_db())

def q(sql, params=None):
    db.execute(text(sql), params or {})

def first(sql, params=None):
    return db.execute(text(sql), params or {}).scalar()

def section(name):
    print(f"\n=== {name} ===")

def make_rect_geojson(lat, lon, width_m, height_m):
    """Return a rectangular Polygon GeoJSON string centered on lat/lon."""
    lat_deg = height_m / 111320
    lon_deg = width_m / (111320 * math.cos(math.radians(lat)))
    half_lat, half_lon = lat_deg / 2, lon_deg / 2
    coords = [
        [lon - half_lon, lat - half_lat],
        [lon + half_lon, lat - half_lat],
        [lon + half_lon, lat + half_lat],
        [lon - half_lon, lat + half_lat],
        [lon - half_lon, lat - half_lat],
    ]
    return json.dumps({"type": "Polygon", "coordinates": [coords]})

# ─────────────────────────────────────────────
# 1. FIELDS
# ─────────────────────────────────────────────
section("Fields")

# (Name, CropType, Lat, Lon, size_ha, width_m, height_m, planting_date, description)
FIELDS = [
    (
        "East Pasture — Alpaca Main",
        "Pasture / Alpaca Grazing",
        40.3050, -105.0620, 8.5, 420, 202,
        None,
        "Primary alpaca grazing pasture. Orchard grass + alfalfa blend. "
        "Rotational grazing — 4 paddock system. Herd of 8 adults.",
    ),
    (
        "West Garden Block",
        "Mixed Vegetables",
        40.3075, -105.0725, 2.1, 210, 100,
        "2026-04-01",
        "Main vegetable production block. Heirloom tomatoes, peppers, "
        "zucchini, lettuce, and carrots on raised beds with drip tape.",
    ),
    (
        "Tomato Ridge",
        "Heirloom Tomatoes",
        40.3095, -105.0650, 1.4, 175, 80,
        "2026-04-15",
        "Dedicated heirloom tomato production. 12 varieties including "
        "Cherokee Purple, Brandywine, and Green Zebra. OMRI-certified inputs.",
    ),
    (
        "Herb & Microgreen Block",
        "Herbs / Microgreens",
        40.3115, -105.0710, 0.3, 80, 37,
        "2026-03-15",
        "Intensive herb and microgreen production. Weekly successions of "
        "basil, cilantro, sunflower microgreens, and pea shoots.",
    ),
    (
        "North 40 — Cover Crop & Grain",
        "Cover Crop / Small Grains",
        40.3025, -105.0580, 16.2, 600, 270,
        "2026-03-01",
        "Large rotational block. Winter triticale cover crop followed by "
        "spring oats and field peas. No-till system, third year.",
    ),
    (
        "Berry Row",
        "Strawberries / Blueberries",
        40.3085, -105.0685, 0.8, 130, 62,
        "2026-04-10",
        "Perennial berry operation. June-bearing strawberries (6 varieties) "
        "and rabbiteye blueberries. Third leaf blueberries, peak production 2027.",
    ),
]

field_ids = {}
for (name, crop, lat, lon, size_ha, width_m, height_m, planting, desc) in FIELDS:
    fid = first("SELECT FieldID FROM Field WHERE BusinessID=:b AND Name=:n", {"b": BID, "n": name})
    if not fid:
        geojson = make_rect_geojson(lat, lon, width_m, height_m)
        fid = first(
            "INSERT INTO Field (BusinessID, Name, Address, CropType, Latitude, Longitude, "
            "FieldSizeHectares, PlantingDate, BoundaryGeoJSON, FieldDescription, "
            "MonitoringEnabled, MonitoringIntervalDays, AlertThresholdHealth, "
            "CreatedByPeopleID, CreatedAt) "
            "OUTPUT INSERTED.FieldID "
            "VALUES (:b, :n, :addr, :crop, :lat, :lon, :sz, :pd, :geo, :desc, "
            "1, 5, 50, :pid, GETDATE())",
            {
                "b": BID, "n": name, "addr": "Berthoud, CO 80513",
                "crop": crop, "lat": lat, "lon": lon,
                "sz": size_ha, "pd": planting, "geo": geojson, "desc": desc,
                "pid": PEOPLE_ID,
            }
        )
        print(f"  Created field: {name} (ID={fid})")
    else:
        print(f"  Field exists: {name} (ID={fid})")
    field_ids[name] = fid

db.commit()

# ─────────────────────────────────────────────
# 2. ANALYSES + VEGETATION INDICES
# ─────────────────────────────────────────────
section("Analyses + Vegetation Indices")

# Analysis dates: Jan through early May 2026 (one every ~10 days)
ANALYSIS_DATES = [
    "2026-01-08", "2026-01-18", "2026-01-28",
    "2026-02-07", "2026-02-17", "2026-02-27",
    "2026-03-09", "2026-03-19", "2026-03-29",
    "2026-04-08", "2026-04-18", "2026-04-28",
    "2026-05-03",
]

# Per-field NDVI trajectory: (base_ndvi_jan, peak_ndvi_may)
# Pasture stays green; vegetables emerge mid-season; North 40 shows green then mows
FIELD_NDVI = {
    "East Pasture — Alpaca Main":     (0.42, 0.71),
    "West Garden Block":              (0.18, 0.68),
    "Tomato Ridge":                   (0.14, 0.72),
    "Herb & Microgreen Block":        (0.22, 0.64),
    "North 40 — Cover Crop & Grain":  (0.35, 0.63),
    "Berry Row":                      (0.20, 0.66),
}

def lerp(a, b, t):
    return a + (a - b) * -t

def ndvi_for_date(name, date_str):
    lo, hi = FIELD_NDVI[name]
    d = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    jan1 = datetime.datetime(2026, 1, 1)
    may31 = datetime.datetime(2026, 5, 31)
    t = (d - jan1).days / (may31 - jan1).days
    # slight sinusoidal curve
    ndvi = lo + (hi - lo) * (t ** 0.7 + 0.08 * math.sin(t * math.pi))
    return max(lo, min(hi, ndvi))

def vi_stats(mean, spread=0.12):
    std = spread * mean
    return {
        "mean": round(mean, 4),
        "std":  round(std, 4),
        "min":  round(max(0, mean - 2.5 * std), 4),
        "max":  round(min(1, mean + 2.5 * std), 4),
        "p25":  round(mean - 0.8 * std, 4),
        "p75":  round(mean + 0.8 * std, 4),
    }

INDEX_OFFSETS = {
    # Index: (scale vs NDVI, extra_spread)
    "NDVI":  (1.00, 0.12),
    "NDRE":  (0.72, 0.10),
    "EVI":   (0.78, 0.14),
    "GNDVI": (0.85, 0.11),
    "NDWI":  (-0.40, 0.20),  # negative — water stress inverted
}

total_analyses = 0
for name, fid in field_ids.items():
    field_analyses = 0
    for date_str in ANALYSIS_DATES:
        exists = first(
            "SELECT AnalysisID FROM Analysis WHERE FieldID=:f AND CAST(AnalysisDate AS DATE)=:d",
            {"f": fid, "d": date_str}
        )
        if exists:
            continue

        ndvi_mean = ndvi_for_date(name, date_str)
        health = int(max(20, min(100, ndvi_mean * 130)))
        cloud = round(random.uniform(2, 18), 1)
        status = "HEALTHY" if health >= 65 else ("MODERATE" if health >= 45 else "STRESSED")

        # One analysis every ~10 days means satellite acquired ~1 day before
        sat_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d") - datetime.timedelta(days=1)

        aid = first(
            "INSERT INTO Analysis "
            "(FieldID, BusinessID, AnalysisDate, HealthScore, Status, CloudPercent, "
            "SatelliteAcquiredAt, CreatedAt) "
            "OUTPUT INSERTED.AnalysisID "
            "VALUES (:f, :b, :d, :hs, :st, :cp, :sa, GETDATE())",
            {"f": fid, "b": BID, "d": date_str, "hs": health, "st": status,
             "cp": cloud, "sa": sat_dt}
        )

        # Vegetation indices
        for idx_type, (scale, spread) in INDEX_OFFSETS.items():
            mean = ndvi_mean * scale + random.uniform(-0.02, 0.02)
            s = vi_stats(mean, spread)
            q(
                "INSERT INTO VegetationIndex "
                "(AnalysisID, IndexType, MeanValue, StdDev, MinValue, MaxValue, "
                "MedianValue, Percentile25, Percentile75, CreatedAt) "
                "VALUES (:aid, :idx, :mean, :std, :mn, :mx, :med, :p25, :p75, GETDATE())",
                {"aid": aid, "idx": idx_type, "mean": s["mean"], "std": s["std"],
                 "mn": s["min"], "mx": s["max"], "med": s["mean"],
                 "p25": s["p25"], "p75": s["p75"]}
            )
        field_analyses += 1
        total_analyses += 1

    db.commit()
    if field_analyses:
        print(f"  {name}: {field_analyses} analyses + {field_analyses * 5} indices")
    else:
        print(f"  {name}: all analyses already exist")

# ─────────────────────────────────────────────
# 3. FIELD NOTES
# ─────────────────────────────────────────────
section("Field Notes")

notes_data = [
    ("East Pasture — Alpaca Main",   "2026-03-15", "General",  "Spring Pasture Assessment",
     "Observed good orchard grass emergence after winter dormancy. "
     "Alfalfa stand at ~85% density — acceptable. Planning to overseed thin spots in south paddock by April 1.",
     "Low"),
    ("East Pasture — Alpaca Main",   "2026-04-22", "Grazing",  "Paddock Rotation — Week 17",
     "Moved herd to Paddock 3. Paddock 1 forage height at 6 inches — ready for re-entry in ~18 days. "
     "Paddock 2 showing excellent recovery after April rain. Manure distribution even.",
     "Low"),
    ("West Garden Block",            "2026-04-05", "Planting", "Spring Planting Kick-Off",
     "Transplanted butterhead lettuce (180 heads), rainbow carrots seeded directly (6 beds × 50m). "
     "Drip tape flushed and pressure-tested at 10 PSI. Soil temp at 2in: 52°F.",
     "Low"),
    ("West Garden Block",            "2026-04-28", "Pest",     "Thrips Pressure — Bell Peppers",
     "Moderate thrips (Frankliniella occidentalis) found on pepper transplants in beds 7-9. "
     "Estimated 12-18 adults per leaf. Applied Entrust SC at 4 oz/acre. Re-scout in 5 days.",
     "Medium"),
    ("Tomato Ridge",                 "2026-04-20", "Planting", "Heirloom Tomato Transplant Day",
     "Transplanted 2,400 tomato starts across 12 varieties. 24-inch spacing, planted into pre-formed beds "
     "with black biodegradable mulch. Soil moisture at field capacity. Weather: 68°F / low wind.",
     "Low"),
    ("Tomato Ridge",                 "2026-05-02", "Disease",  "Early Blight Scouting — Negative",
     "Full field walkthrough at 7 days post-transplant. No early blight (Alternaria solani) detected. "
     "All transplants showing vigorous establishment. First foliar calcium spray applied.",
     "Low"),
    ("North 40 — Cover Crop & Grain","2026-03-05", "General",  "Winter Cover Crop Termination",
     "Triticale cover crop at 18-inch height, good biomass. Terminated with roller-crimper on 3/4, "
     "followed by vertical till on 3/5. Residue incorporation at ~60%. Planting zone ready.",
     "Low"),
    ("North 40 — Cover Crop & Grain","2026-03-22", "Planting", "Spring Oats & Field Peas Seeded",
     "Drilled spring oats (150 lb/acre) + field peas (80 lb/acre) at 2-inch depth. "
     "Soil temp 44°F at seeding. Rain forecast next 3 days. Emergence expected by April 5.",
     "Low"),
    ("Berry Row",                    "2026-04-12", "General",  "Berry Row Spring Startup",
     "Removed winter straw mulch from strawberry crowns. Crown condition: 94% viable. "
     "Blueberries showing bud break on 80% of canes — earlier than last year by 6 days. "
     "Applied sulfur spray for mummy berry prevention.",
     "Low"),
    ("Herb & Microgreen Block",      "2026-04-18", "Harvest",  "Sunflower Microgreen Harvest — Week 3",
     "Harvested 38 flats of sunflower microgreens at 8-day growth. Average height 5.5 inches, "
     "color score 9/10. Restaurant delivery to Harvest Table (18 flats) and Ember Grill (12 flats). "
     "Next succession seeded same day.",
     "Low"),
]

notes_added = 0
for (field_name, date_str, cat, title, content, severity) in notes_data:
    fid = field_ids.get(field_name)
    if not fid:
        continue
    exists = first(
        "SELECT NoteID FROM FieldNote WHERE FieldID=:f AND Title=:t",
        {"f": fid, "t": title}
    )
    if not exists:
        q(
            "INSERT INTO FieldNote (FieldID, BusinessID, PeopleID, NoteDate, Category, "
            "Title, Content, Severity, CreatedAt) "
            "VALUES (:f, :b, :p, :d, :cat, :t, :c, :sev, GETDATE())",
            {"f": fid, "b": BID, "p": PEOPLE_ID, "d": date_str,
             "cat": cat, "t": title, "c": content, "sev": severity}
        )
        notes_added += 1

db.commit()
print(f"  Added {notes_added} field notes")

# ─────────────────────────────────────────────
# 4. ACTIVITY LOG
# ─────────────────────────────────────────────
section("Activity Log")

activities = [
    ("East Pasture — Alpaca Main",   "2026-03-20", "Fertilization", "Granular Lime",       2.0, "ton/acre",     "John Medrano", "Fall pH test showed 5.8. Limed to target 6.5."),
    ("East Pasture — Alpaca Main",   "2026-04-10", "Irrigation",    None,                  None, None,           "Diego Mendez", "First irrigation of season — 1 inch applied to all 4 paddocks"),
    ("West Garden Block",            "2026-04-01", "Transplanting", None,                  None, None,           "Maria Santos", "Transplanted lettuce + direct seeded carrots, radishes"),
    ("West Garden Block",            "2026-04-12", "Fertilization", "Fish Emulsion 5-1-1", 3.0, "gal/acre",     "John Medrano", "First fertigation through drip — post-transplant feeding"),
    ("West Garden Block",            "2026-04-29", "Pest Control",  "Entrust SC",          4.0, "oz/acre",      "Priya Nair",   "Thrips treatment on pepper beds 7-9"),
    ("Tomato Ridge",                 "2026-04-15", "Transplanting", None,                  None, None,           "Maria Santos", "2,400 heirloom tomato transplants set — all 12 varieties"),
    ("Tomato Ridge",                 "2026-04-22", "Irrigation",    None,                  None, None,           "Diego Mendez", "Drip tape activated for first time — 45 min / zone"),
    ("Tomato Ridge",                 "2026-05-01", "Foliar Spray",  "Calcium Nitrate",     5.0, "lb/100 gal",   "John Medrano", "First calcium spray to prevent BER. Applied at 7 DAT."),
    ("North 40 — Cover Crop & Grain","2026-03-04", "Tillage",       None,                  None, None,           "Garrett Olson","Roller-crimper pass on triticale cover crop at 18in height"),
    ("North 40 — Cover Crop & Grain","2026-03-05", "Tillage",       None,                  None, None,           "Garrett Olson","Vertical till — 3-inch incorporation of cover crop residue"),
    ("North 40 — Cover Crop & Grain","2026-03-22", "Planting",      None,                  None, None,           "James Whitfield","Drilled oats + field peas at 2in depth"),
    ("North 40 — Cover Crop & Grain","2026-04-02", "Fertilization", "Pelletized Compost",  500.0,"lb/acre",      "John Medrano", "Side-dress compost after oat emergence confirmed"),
    ("Berry Row",                    "2026-03-28", "Fertilization", "Feather Meal 12-0-0", 150.0,"lb/acre",      "Elena Kowalski","Pre-season nitrogen application on strawberry beds"),
    ("Berry Row",                    "2026-04-12", "Foliar Spray",  "Copper Sulfate",      1.5, "lb/100 gal",   "Elena Kowalski","Mummy berry preventative on blueberries"),
    ("Herb & Microgreen Block",      "2026-04-18", "Harvest",       None,                  None, None,           "Priya Nair",   "Harvested 38 microgreen flats — Week 3 succession"),
    ("Herb & Microgreen Block",      "2026-04-25", "Irrigation",    None,                  None, None,           "Priya Nair",   "Adjusted mist timer — 4x/day to 6x/day for warmer temps"),
]

acts_added = 0
for (field_name, date_str, atype, product, rate, unit, operator, notes) in activities:
    fid = field_ids.get(field_name)
    if not fid:
        continue
    exists = first(
        "SELECT ActivityID FROM FieldActivityLog "
        "WHERE FieldID=:f AND ActivityDate=:d AND ActivityType=:t AND ISNULL(CAST(Notes AS NVARCHAR(MAX)),'')=:n",
        {"f": fid, "d": date_str, "t": atype, "n": notes or ""}
    )
    if not exists:
        q(
            "INSERT INTO FieldActivityLog (FieldID, BusinessID, PeopleID, ActivityDate, "
            "ActivityType, Product, Rate, RateUnit, OperatorName, Notes, CreatedAt) "
            "VALUES (:f, :b, :p, :d, :at, :prod, :rate, :unit, :op, :notes, GETDATE())",
            {"f": fid, "b": BID, "p": PEOPLE_ID, "d": date_str,
             "at": atype, "prod": product, "rate": rate, "unit": unit,
             "op": operator, "notes": notes}
        )
        acts_added += 1

db.commit()
print(f"  Added {acts_added} activity log entries")

# ─────────────────────────────────────────────
# 5. SOIL SAMPLES
# ─────────────────────────────────────────────
section("Soil Samples")

soil_samples = [
    # (field, date, label, depth_cm, pH, OM%, N, P, K, S, Ca, Mg, CEC, notes)
    ("East Pasture — Alpaca Main",    "2026-02-15", "Paddock 1 — 0-6in",  15,
     5.8, 3.2, 42.0, 28.0, 185.0, 12.0, 1650.0, 185.0, 14.2,
     "Slightly acidic — liming recommended to 6.2. Potassium adequate for pasture."),
    ("East Pasture — Alpaca Main",    "2026-02-15", "Paddock 3 — 0-6in",  15,
     6.1, 4.1, 55.0, 32.0, 210.0, 14.0, 1820.0, 198.0, 16.8,
     "Best-performing paddock. Higher OM from heavier manure accumulation."),
    ("West Garden Block",             "2026-01-20", "Bed Zone A — 0-8in", 20,
     6.5, 5.8, 68.0, 48.0, 220.0, 18.0, 1980.0, 225.0, 18.4,
     "Well-balanced profile. Phosphorus in high range — no P application needed."),
    ("West Garden Block",             "2026-01-20", "Bed Zone B — 8-18in",45,
     6.4, 3.1, 34.0, 18.0, 145.0, 10.0, 1750.0, 188.0, 14.1,
     "Subsoil sample. Lower OM as expected. Watch for subsoil compaction."),
    ("Tomato Ridge",                  "2026-02-01", "Block A — 0-8in",   20,
     6.8, 6.2, 72.0, 42.0, 195.0, 20.0, 2100.0, 238.0, 19.2,
     "Excellent organic matter from 3 years of compost additions. Slightly high pH for tomatoes."),
    ("North 40 — Cover Crop & Grain", "2026-02-05", "North End — 0-6in", 15,
     6.2, 2.8, 38.0, 22.0, 165.0,  9.0, 1580.0, 172.0, 12.8,
     "Lower OM typical of no-till year 3. Cover crop additions building slowly."),
    ("North 40 — Cover Crop & Grain", "2026-02-05", "South End — 0-6in", 15,
     6.4, 3.5, 45.0, 26.0, 178.0, 11.0, 1680.0, 184.0, 13.9,
     "Higher OM in south — better topsoil retention. Consistent with field history."),
    ("Berry Row",                     "2026-02-10", "Strawberry Zone",   15,
     6.0, 4.4, 52.0, 38.0, 210.0, 14.0, 1880.0, 210.0, 16.2,
     "Good fertility. Strawberries prefer 5.8-6.2 — at high end. Monitor pH trend."),
]

soil_added = 0
for (field_name, date_str, label, depth, pH, OM, N, P, K, S, Ca, Mg, CEC, notes) in soil_samples:
    fid = field_ids.get(field_name)
    if not fid:
        continue
    exists = first(
        "SELECT SampleID FROM FieldSoilSample WHERE FieldID=:f AND SampleDate=:d AND SampleLabel=:l",
        {"f": fid, "d": date_str, "l": label}
    )
    if not exists:
        q(
            "INSERT INTO FieldSoilSample (FieldID, BusinessID, SampleDate, SampleLabel, "
            "Depth_cm, pH, OrganicMatter, Nitrogen, Phosphorus, Potassium, Sulfur, "
            "Calcium, Magnesium, CEC, Notes, CreatedAt) "
            "VALUES (:f, :b, :d, :lbl, :dep, :ph, :om, :n, :p, :k, :s, :ca, :mg, :cec, :notes, GETDATE())",
            {"f": fid, "b": BID, "d": date_str, "lbl": label, "dep": depth,
             "ph": pH, "om": OM, "n": N, "p": P, "k": K, "s": S,
             "ca": Ca, "mg": Mg, "cec": CEC, "notes": notes}
        )
        soil_added += 1

db.commit()
print(f"  Added {soil_added} soil samples")

# ─────────────────────────────────────────────
# 6. SCOUTING OBSERVATIONS
# ─────────────────────────────────────────────
section("Scouting Observations")

scouts = [
    # (field, observed_at, category, severity, notes, lat, lon)
    ("West Garden Block",  "2026-04-28 10:30:00", "Pest",    "Medium",
     "Thrips (Frankliniella occidentalis) on pepper transplants. Beds 7-9, ~12-18 adults/leaf. "
     "Entrust SC applied. Re-scout scheduled 5/3.",
     40.3075, -105.0721),
    ("West Garden Block",  "2026-05-03 09:15:00", "Pest",    "Low",
     "Follow-up thrips scout. Population reduced to 2-4 adults/leaf. Below economic threshold. "
     "Continue monitoring weekly.",
     40.3074, -105.0722),
    ("Tomato Ridge",       "2026-04-25 08:45:00", "Disease", "Low",
     "Scout at 10 DAT — no early blight or septoria detected. "
     "One plant with slight wilting in row 14 — possibly transplant shock. Flagged for follow-up.",
     40.3096, -105.0651),
    ("North 40 — Cover Crop & Grain", "2026-04-05 07:30:00", "General", "Low",
     "Oat + field pea emergence at 85% stand — within acceptable range. "
     "Weed pressure low: scattered pigweed seedlings in west quarter, below threshold.",
     40.3025, -105.0582),
    ("East Pasture — Alpaca Main",    "2026-04-20 15:00:00", "Weed",    "Low",
     "Musk thistle (Carduus nutans) rosettes emerging along Paddock 2 fence line. "
     "Count: ~15 rosettes in 50m stretch. Spot treatment with OMRI-listed herbicide planned.",
     40.3051, -105.0621),
    ("Berry Row",          "2026-04-28 11:00:00", "Disease", "Medium",
     "Suspected mummy berry (Monilinia vaccinii-corymbosi) symptoms on 3 blueberry canes — "
     "shoot blight on 2-3 inch tips. Samples sent to CSU Extension. "
     "Applied additional copper spray as precaution.",
     40.3085, -105.0684),
]

scouts_added = 0
for (field_name, obs_str, cat, sev, notes, lat, lon) in scouts:
    fid = field_ids.get(field_name)
    if not fid:
        continue
    obs_dt = datetime.datetime.strptime(obs_str, "%Y-%m-%d %H:%M:%S")
    exists = first(
        "SELECT ScoutID FROM FieldScout WHERE FieldID=:f AND ObservedAt=:o",
        {"f": fid, "o": obs_dt}
    )
    if not exists:
        q(
            "INSERT INTO FieldScout (FieldID, BusinessID, PeopleID, ObservedAt, "
            "Category, Severity, Notes, Latitude, Longitude, CreatedAt) "
            "VALUES (:f, :b, :p, :o, :cat, :sev, :notes, :lat, :lon, GETDATE())",
            {"f": fid, "b": BID, "p": PEOPLE_ID, "o": obs_dt,
             "cat": cat, "sev": sev, "notes": notes, "lat": lat, "lon": lon}
        )
        scouts_added += 1

db.commit()
print(f"  Added {scouts_added} scouting observations")

# ─────────────────────────────────────────────
# 7. PRESCRIPTIONS
# ─────────────────────────────────────────────
section("Prescriptions")

prescriptions = [
    ("West Garden Block",  "Variable Rate Nitrogen — Spring Vegetables",
     "Fish Emulsion 5-1-1", "gal/acre", "NDVI", "kmeans", 3,
     '[{"zone":1,"rate":2.5},{"zone":2,"rate":4.0},{"zone":3,"rate":5.5}]',
     "2026-04-12",
     "Three-zone variable rate application based on April 8 NDVI scan. "
     "Low-NDVI zones receive higher N to encourage establishment."),
    ("Tomato Ridge",       "Calcium Variable Rate — BER Prevention",
     "Calcium Nitrate 15.5-0-0", "lb/acre", "NDRE", "threshold", 2,
     '[{"zone":1,"rate":25},{"zone":2,"rate":40}]',
     "2026-04-28",
     "Two-zone Ca application targeting low-NDRE areas where BER risk is higher."),
    ("North 40 — Cover Crop & Grain", "Compost Top-Dress — Variable Rate",
     "Pelleted Compost", "lb/acre", "NDVI", "kmeans", 3,
     '[{"zone":1,"rate":300},{"zone":2,"rate":500},{"zone":3,"rate":700}]',
     "2026-04-02",
     "Post-emergence compost application calibrated to NDVI zones from April 8 analysis."),
    ("East Pasture — Alpaca Main", "Lime Variable Application",
     "Granular Lime", "ton/acre", "NDVI", "threshold", 2,
     '[{"zone":1,"rate":1.5},{"zone":2,"rate":2.5}]',
     "2026-03-20",
     "Low pH zones identified from February soil sample — higher lime rate in south paddock."),
]

rx_added = 0
for (field_name, rx_name, product, unit, idx_key, zone_method, num_zones,
     zone_rates, analysis_date, notes) in prescriptions:
    fid = field_ids.get(field_name)
    if not fid:
        continue
    exists = first(
        "SELECT PrescriptionID FROM FieldPrescription WHERE FieldID=:f AND Name=:n",
        {"f": fid, "n": rx_name}
    )
    if not exists:
        q(
            "INSERT INTO FieldPrescription (FieldID, BusinessID, Name, Product, Unit, "
            "IndexKey, ZoneMethod, NumZones, ZoneRatesJSON, AnalysisDate, Notes, CreatedAt) "
            "VALUES (:f, :b, :n, :prod, :unit, :idx, :zm, :nz, :zr, :ad, :notes, GETDATE())",
            {"f": fid, "b": BID, "n": rx_name, "prod": product, "unit": unit,
             "idx": idx_key, "zm": zone_method, "nz": num_zones,
             "zr": zone_rates, "ad": analysis_date, "notes": notes}
        )
        rx_added += 1

db.commit()
print(f"  Added {rx_added} prescriptions")

# ─────────────────────────────────────────────
# 8. MATURITY SAMPLES
# ─────────────────────────────────────────────
section("Maturity Samples")

maturity_samples = [
    # (field, date, cultivar, sample_size, brix, firmness, pH, TA%, dry_matter%, notes)
    ("Tomato Ridge", "2026-05-03", "Cherokee Purple",   20,  4.2, 6.8, 4.85, 0.48, 5.2,
     "First sample at 18 DAT. BRIX low — typical for this stage. Monitoring weekly."),
    ("Tomato Ridge", "2026-05-03", "Brandywine",        20,  4.0, 7.2, 4.90, 0.51, 5.0,
     "Good firmness score. Color break not yet observed. Continue monitoring."),
    ("Berry Row",    "2026-05-01", "Chandler Strawberry",30, 7.8, 5.5, 3.72, 0.85, 8.4,
     "Early-season sample from first-year plants. BRIX building well for this cultivar."),
    ("Berry Row",    "2026-05-01", "Seascape Strawberry",30, 8.4, 5.2, 3.68, 0.88, 8.9,
     "Highest BRIX of season so far. Flavor panel rated 8.5/10. First harvest est. May 20."),
    ("West Garden Block", "2026-04-28", "Butterhead Lettuce", 15, 2.1, None, 6.2, None, 3.8,
     "BRIX measured at harvest maturity. Consistent with expected range for butterhead."),
]

mat_added = 0
for (field_name, date_str, cultivar, sample_size, brix, firmness, pH, TA, DM, notes) in maturity_samples:
    fid = field_ids.get(field_name)
    if not fid:
        continue
    exists = first(
        "SELECT SampleID FROM FieldMaturitySample WHERE FieldID=:f AND SampleDate=:d AND Cultivar=:c",
        {"f": fid, "d": date_str, "c": cultivar}
    )
    if not exists:
        q(
            "INSERT INTO FieldMaturitySample (FieldID, BusinessID, PeopleID, SampleDate, "
            "Cultivar, SampleSize, BrixDegrees, FirmnessKgF, PH, TitratableAcidityPct, "
            "DryMatterPct, Notes, CreatedAt) "
            "VALUES (:f, :b, :p, :d, :cv, :ss, :brix, :firm, :ph, :ta, :dm, :notes, GETDATE())",
            {"f": fid, "b": BID, "p": PEOPLE_ID, "d": date_str,
             "cv": cultivar, "ss": sample_size, "brix": brix,
             "firm": firmness, "ph": pH, "ta": TA, "dm": DM, "notes": notes}
        )
        mat_added += 1

db.commit()
print(f"  Added {mat_added} maturity samples")

# ─────────────────────────────────────────────
# 9. ALERTS
# ─────────────────────────────────────────────
section("Alerts")

# Get one recent AnalysisID per field for alert linkage
alert_data = [
    ("West Garden Block",   "NDVI_DROP", "high",   "open",
     "NDVI declined 0.11 between Apr 8 and Apr 18 scans — possible transplant stress or pest pressure. "
     "Scout beds 7-12 within 48 hours."),
    ("Berry Row",           "NDVI_DROP", "medium", "open",
     "NDVI 0.08 below expected seasonal trajectory for berry establishment stage. "
     "Check for soil moisture or disease pressure."),
    ("North 40 — Cover Crop & Grain", "LOW_HEALTH", "low", "resolved",
     "Health score 44 on Jan 28 scan — cover crop in winter dormancy. Expected seasonal low. "
     "No action needed; score recovering with warming temps."),
    ("East Pasture — Alpaca Main",    "LOW_HEALTH", "low", "acknowledged",
     "Paddock 2 NDVI trailing Paddocks 1, 3, 4 by 0.12 — possible overgrazing pressure. "
     "Extended rest period recommended before next rotation entry."),
    ("Tomato Ridge",        "NO_DATA",   "medium", "resolved",
     "Cloud cover (87%) on Mar 19 satellite pass prevented NDVI extraction. "
     "Analysis skipped — next clear acquisition expected within 5-7 days."),
]

alerts_added = 0
for (field_name, alert_type, severity, status, message) in alert_data:
    fid = field_ids.get(field_name)
    if not fid:
        continue
    # Get latest analysis for this field
    aid = first(
        "SELECT TOP 1 AnalysisID FROM Analysis WHERE FieldID=:f ORDER BY AnalysisDate DESC",
        {"f": fid}
    )
    if not aid:
        continue
    exists = first(
        "SELECT AlertID FROM Alert WHERE FieldID=:f AND AlertType=:t AND Message=:m",
        {"f": fid, "t": alert_type, "m": message}
    )
    if not exists:
        resolved_at = datetime.datetime.now() if status == "resolved" else None
        ack_at = datetime.datetime.now() if status in ("resolved", "acknowledged") else None
        q(
            "INSERT INTO Alert (FieldID, AnalysisID, BusinessID, AlertType, Severity, "
            "Status, Message, CreatedAt, AcknowledgedAt, ResolvedAt) "
            "VALUES (:f, :aid, :b, :at, :sev, :st, :msg, GETDATE(), :ack, :res)",
            {"f": fid, "aid": aid, "b": BID, "at": alert_type, "sev": severity,
             "st": status, "msg": message, "ack": ack_at, "res": resolved_at}
        )
        alerts_added += 1

db.commit()
print(f"  Added {alerts_added} alerts")

# ─────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────
total_fields = len(field_ids)
print(f"\n=== COMPLETE ===")
print(f"  {total_fields} fields")
print(f"  {total_analyses} analyses ({total_analyses * 5} vegetation index rows)")
print(f"  {notes_added} field notes")
print(f"  {acts_added} activity log entries")
print(f"  {soil_added} soil samples")
print(f"  {scouts_added} scouting observations")
print(f"  {rx_added} prescriptions")
print(f"  {mat_added} maturity samples")
print(f"  {alerts_added} alerts")
