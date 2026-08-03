"""
seed_cold_chain_recent_15671.py — Extends ColdChainReading data for BusinessID=15671
to cover May 3–6 2026 (the gap since the previous seed ended May 2).
Idempotent: skips timestamps already in DB.
"""
import sys, datetime, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import get_db
from sqlalchemy import text

BID = 15671
db = next(get_db())

def q(sql, params=None):
    db.execute(text(sql), params or {})

def first(sql, params=None):
    return db.execute(text(sql), params or {}).scalar()

# Get vehicle IDs (order: box truck, cargo van, freezer trailer)
rows = db.execute(text(
    "SELECT VehicleID, VehicleName, MinTempC, MaxTempC "
    "FROM ColdChainVehicle WHERE BusinessID=:b ORDER BY VehicleID"
), {"b": BID}).fetchall()

if not rows:
    print("No vehicles found. Run seed_demo_15671d.py first.")
    sys.exit(1)

vehicles = [(r[0], r[1], float(r[2]), float(r[3])) for r in rows]
print(f"Vehicles: {[v[1] for v in vehicles]}")

# Pre-load existing timestamps to skip duplicates
existing = set()
for (vid, _, _, _) in vehicles:
    ts_rows = db.execute(text(
        "SELECT RecordedAt FROM ColdChainReading WHERE VehicleID=:v"
    ), {"v": vid}).fetchall()
    existing.update((vid, r[0]) for r in ts_rows)
print(f"Existing readings in DB: {len(existing)}")

def add_reading(vid, dt, temp_c, humidity, location, notes=""):
    key = (vid, dt)
    if key in existing:
        return False
    q(
        "INSERT INTO ColdChainReading "
        "(VehicleID, TempC, Humidity, LocationDesc, RecordedAt, Notes) "
        "VALUES (:v, :t, :h, :loc, :ra, :notes)",
        {"v": vid, "t": round(temp_c, 1), "h": round(humidity, 1),
         "loc": location, "ra": dt, "notes": notes}
    )
    existing.add(key)
    return True


# ── Dates to fill (May 3–6, 2026) ──────────────────────────────────────────
# May 3 = Saturday   (weekday=5)
# May 4 = Sunday     (weekday=6) — no runs
# May 5 = Monday     (weekday=0)
# May 6 = Tuesday    (weekday=1)

NEW_DATES = [
    datetime.date(2026, 5, 3),
    datetime.date(2026, 5, 5),
    datetime.date(2026, 5, 6),
]

# ── Vehicle 0: Refrigerated Box Truck #1  (target -2..4°C, Mon–Sat) ────────
v0, _, v0_min, v0_max = vehicles[0]

v0_stops = [
    ("Food World Loading Dock",      "Pre-trip temp check"),
    ("I-25 North -- Mile 210",       "En route"),
    ("Harvest Table Restaurant",     "Stop 1 -- unloading"),
    ("Ember Grill & Bar",            "Stop 2 -- unloading"),
    ("Roots Kitchen -- Old Town",    "Stop 3 -- unloading"),
    ("Whole Foods Market",           "Stop 4 -- wholesale drop"),
    ("I-25 South -- Return",         "Return leg"),
    ("Food World Loading Dock",      "Return -- end of run"),
]

added_v0 = 0
for run_date in NEW_DATES:
    if run_date.weekday() == 6:   # skip Sundays
        continue
    base_temp = random.uniform(v0_min + 0.5, v0_max - 0.5)
    for i, (loc, note) in enumerate(v0_stops):
        dt = datetime.datetime.combine(run_date, datetime.time(6, 0)) + datetime.timedelta(minutes=i * 28)
        drift = 0.0
        if "unloading" in note or "drop" in note:
            drift = random.uniform(0.3, 1.2)
        # May 6 (Tuesday) — simulate a minor door-seal issue on stop 3
        if run_date == datetime.date(2026, 5, 6) and i == 3:
            drift += random.uniform(1.8, 2.8)
        temp = base_temp + drift + random.uniform(-0.2, 0.2)
        hum = random.uniform(82, 92)
        out_of_range = temp > v0_max or temp < v0_min
        extra = " ALERT: temp breach" if out_of_range else ""
        added_v0 += add_reading(v0, dt, temp, hum, loc, note + extra)

db.commit()
print(f"Box Truck: added {added_v0} readings")


# ── Vehicle 1: Insulated Cargo Van #2  (target 0..6°C) ─────────────────────
v1, _, v1_min, v1_max = vehicles[1]

market_stops = [
    ("Food World Loading Dock",        "Market load-out"),
    ("US-287 South -- Longmont",       "En route"),
    ("Boulder Farmers Market",         "Setup -- icing produce"),
    ("Boulder Farmers Market",         "Market open"),
    ("Boulder Farmers Market",         "Mid-market check"),
    ("Boulder Farmers Market",         "Market wind-down"),
    ("US-36 East -- Return",           "Return leg"),
    ("Food World Loading Dock",        "Return -- unsold to cold storage"),
]
csa_stops = [
    ("Food World Loading Dock",        "CSA box load-out"),
    ("Longmont -- Zone A drop",        "Stop 1 -- 12 boxes"),
    ("Longmont -- Zone B drop",        "Stop 2 -- 9 boxes"),
    ("Lafayette -- Zone C drop",       "Stop 3 -- 11 boxes"),
    ("Boulder -- Zone D drop",         "Stop 4 -- 14 boxes"),
    ("US-287 North -- Return",         "Return leg"),
    ("Food World Loading Dock",        "Return -- end of run"),
]

added_v1 = 0
for run_date in NEW_DATES:
    dow = run_date.weekday()
    if dow in (1, 3, 5):    # Tue, Thu, Sat = market
        stops, run_type = market_stops, "market"
    elif dow in (0, 2):     # Mon, Wed = CSA
        stops, run_type = csa_stops, "csa"
    else:
        continue            # skip Sun and Fri

    base_temp = random.uniform(v1_min + 0.5, v1_max - 1.0)
    for i, (loc, note) in enumerate(stops):
        dt = datetime.datetime.combine(run_date, datetime.time(6, 30)) + datetime.timedelta(minutes=i * 40)
        drift = 0.0
        if "Market open" in note:
            drift = random.uniform(0.4, 1.5)
        # Saturday May 3 — warm afternoon pushes mid-market temps up
        if run_date == datetime.date(2026, 5, 3) and "Mid-market" in note:
            drift = random.uniform(2.0, 3.2)   # likely breach
        temp = base_temp + drift + random.uniform(-0.3, 0.3)
        hum = random.uniform(75, 87)
        out_of_range = temp > v1_max or temp < v1_min
        extra = " ALERT: temp breach" if out_of_range else ""
        added_v1 += add_reading(v1, dt, temp, hum, loc, note + extra)

db.commit()
print(f"Cargo Van: added {added_v1} readings")


# ── Vehicle 2: Freezer Trailer Unit #3  (target -20..-15°C, Mon + Thu) ─────
v2, _, v2_min, v2_max = vehicles[2]

freezer_stops = [
    ("Food World Cold Storage",        "Pre-trip inspection -- doors sealed"),
    ("I-25 South -- Mile 190",         "En route Denver"),
    ("I-70 West -- Genesee Summit",    "High altitude check"),
    ("Denver Cold Storage Hub",        "Transfer -- partial unload"),
    ("Denver Cold Storage Hub",        "Reload outbound product"),
    ("I-76 East -- Commerce City",     "En route Greeley"),
    ("Greeley Distribution Center",    "Main delivery -- rear door open 20 min"),
    ("Greeley Distribution Center",    "Unload complete -- doors sealed"),
    ("I-76 West -- Mile 30",           "Return leg"),
    ("I-25 North -- Mile 205",         "Return leg"),
    ("Food World Cold Storage",        "Return -- connected to dock cooldown"),
]

added_v2 = 0
for run_date in NEW_DATES:
    if run_date.weekday() not in (0, 3):   # Mon, Thu only
        continue
    base_temp = random.uniform(v2_min + 0.5, v2_max - 0.5)
    for i, (loc, note) in enumerate(freezer_stops):
        dt = datetime.datetime.combine(run_date, datetime.time(5, 0)) + datetime.timedelta(minutes=i * 42)
        drift = 0.0
        if "door open" in note.lower():
            drift = random.uniform(0.8, 2.5)
        if "Genesee Summit" in loc:
            drift = random.uniform(-0.5, 0.5)
        temp = base_temp + drift + random.uniform(-0.3, 0.3)
        hum = random.uniform(50, 62)
        out_of_range = temp > v2_max or temp < v2_min
        extra = " ALERT: temp breach" if out_of_range else ""
        added_v2 += add_reading(v2, dt, temp, hum, loc, note + extra)

db.commit()
print(f"Freezer Trailer: added {added_v2} readings")

total = added_v0 + added_v1 + added_v2
print(f"\nTotal new readings added: {total}")
print("Done.")
