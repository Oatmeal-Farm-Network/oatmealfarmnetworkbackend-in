"""
seed_cold_chain_15671.py — Additional cold chain readings for BusinessID=15671
Adds 3 weeks of realistic daily route readings for the 3 existing vehicles.
Idempotent: skips timestamps already in the DB.
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

# Get vehicle IDs for this business
rows = db.execute(text(
    "SELECT VehicleID, VehicleName, MinTempC, MaxTempC FROM ColdChainVehicle WHERE BusinessID=:b ORDER BY VehicleID"
), {"b": BID}).fetchall()

if not rows:
    print("No vehicles found for BusinessID=15671. Run seed_demo_15671d.py first.")
    sys.exit(1)

vehicles = [(r[0], r[1], float(r[2]), float(r[3])) for r in rows]
print(f"Found {len(vehicles)} vehicles: {[v[1] for v in vehicles]}")

# Pre-load existing timestamps to skip
existing = set()
for (vid, _, _, _) in vehicles:
    ts_rows = db.execute(text(
        "SELECT RecordedAt FROM ColdChainReading WHERE VehicleID=:v"
    ), {"v": vid}).fetchall()
    existing.update((vid, r[0]) for r in ts_rows)
print(f"Existing readings: {len(existing)}")

def add_reading(vid, dt, temp_c, humidity, location, notes=""):
    key = (vid, dt)
    if key in existing:
        return False
    q(
        "INSERT INTO ColdChainReading (VehicleID, TempC, Humidity, LocationDesc, RecordedAt, Notes) "
        "VALUES (:v, :t, :h, :loc, :ra, :notes)",
        {"v": vid, "t": round(temp_c, 1), "h": round(humidity, 1),
         "loc": location, "ra": dt, "notes": notes}
    )
    existing.add(key)
    return True


# ── Vehicle 0: Refrigerated Box Truck (fresh produce, target -2..4°C)
# Daily morning restaurant delivery route, Mon–Sat
v0, _, v0_min, v0_max = vehicles[0]
v0_stops = [
    ("Food World Loading Dock",      "Pre-trip temp check"),
    ("I-25 North — Mile 210",        "En route"),
    ("Harvest Table Restaurant",     "Stop 1 — unloading"),
    ("Ember Grill & Bar",            "Stop 2 — unloading"),
    ("Roots Kitchen — Old Town",     "Stop 3 — unloading"),
    ("Whole Foods Market",           "Stop 4 — wholesale drop"),
    ("I-25 South — Return",         "Return leg"),
    ("Food World Loading Dock",      "Return — end of run"),
]

# Generate 3 weeks of weekday runs (Apr 14 – May 2, skipping Sundays)
run_dates_v0 = []
d = datetime.date(2026, 4, 14)
while d <= datetime.date(2026, 5, 2):
    if d.weekday() != 6:  # skip Sundays
        run_dates_v0.append(d)
    d += datetime.timedelta(days=1)

added_v0 = 0
for run_date in run_dates_v0:
    base_temp = random.uniform(v0_min + 0.5, v0_max - 0.5)
    for i, (loc, note) in enumerate(v0_stops):
        dt = datetime.datetime.combine(run_date, datetime.time(6, 0)) + datetime.timedelta(minutes=i*28)
        # Slight temp drift — door opens push it up briefly at unload stops
        drift = 0.0
        if "unloading" in note or "drop" in note:
            drift = random.uniform(0.3, 1.2)
        # One random breach day per week
        if run_date.isoweekday() == 3 and i == 3:
            drift += random.uniform(1.5, 2.5)
        temp = base_temp + drift + random.uniform(-0.2, 0.2)
        hum = random.uniform(82, 92)
        out_of_range = temp > v0_max or temp < v0_min
        extra_note = " ALERT: temp breach" if out_of_range else ""
        added_v0 += add_reading(v0, dt, temp, hum, loc, note + extra_note)

db.commit()
print(f"Box Truck: added {added_v0} readings across {len(run_dates_v0)} run days")


# ── Vehicle 1: Cargo Van (farmers market + CSA, target 0..6°C)
# Tue/Thu/Sat market days + Mon/Wed CSA deliveries
v1, _, v1_min, v1_max = vehicles[1]

market_stops = [
    ("Food World Loading Dock",       "Market load-out"),
    ("US-287 South — Longmont",       "En route"),
    ("Boulder Farmers Market",        "Setup — icing produce"),
    ("Boulder Farmers Market",        "Market open"),
    ("Boulder Farmers Market",        "Mid-market check"),
    ("Boulder Farmers Market",        "Market wind-down"),
    ("US-36 East — Return",           "Return leg"),
    ("Food World Loading Dock",       "Return — unsold to cold storage"),
]
csa_stops = [
    ("Food World Loading Dock",       "CSA box load-out"),
    ("Longmont — Zone A drop",        "Stop 1 — 12 boxes"),
    ("Longmont — Zone B drop",        "Stop 2 — 9 boxes"),
    ("Lafayette — Zone C drop",       "Stop 3 — 11 boxes"),
    ("Boulder — Zone D drop",         "Stop 4 — 14 boxes"),
    ("US-287 North — Return",         "Return leg"),
    ("Food World Loading Dock",       "Return — end of run"),
]

run_dates_v1 = []
d = datetime.date(2026, 4, 14)
while d <= datetime.date(2026, 5, 2):
    if d.weekday() in (1, 3, 5):   # Tue, Thu, Sat = market
        run_dates_v1.append((d, "market"))
    elif d.weekday() in (0, 2):    # Mon, Wed = CSA
        run_dates_v1.append((d, "csa"))
    d += datetime.timedelta(days=1)

added_v1 = 0
for run_date, run_type in run_dates_v1:
    stops = market_stops if run_type == "market" else csa_stops
    base_temp = random.uniform(v1_min + 0.5, v1_max - 1.0)
    for i, (loc, note) in enumerate(stops):
        dt = datetime.datetime.combine(run_date, datetime.time(6, 30)) + datetime.timedelta(minutes=i*40)
        drift = 0.0
        if "Market open" in note:
            drift = random.uniform(0.4, 1.5)  # door open frequently
        if "Mid-market" in note and run_date.isoweekday() == 6:
            drift = random.uniform(1.8, 2.8)  # Saturday breach from heat
        temp = base_temp + drift + random.uniform(-0.3, 0.3)
        hum = random.uniform(75, 87)
        out_of_range = temp > v1_max or temp < v1_min
        extra_note = " ALERT: temp breach" if out_of_range else ""
        added_v1 += add_reading(v1, dt, temp, hum, loc, note + extra_note)

db.commit()
print(f"Cargo Van: added {added_v1} readings across {len(run_dates_v1)} run days")


# ── Vehicle 2: Freezer Trailer (frozen/alpaca fiber, target -20..-15°C)
# Twice-weekly long haul: Mon + Thu
v2, _, v2_min, v2_max = vehicles[2]

freezer_stops = [
    ("Food World Cold Storage",       "Pre-trip inspection — doors sealed"),
    ("I-25 South — Mile 190",        "En route Denver"),
    ("I-70 West — Genesee Summit",   "High altitude check"),
    ("Denver Cold Storage Hub",       "Transfer — partial unload"),
    ("Denver Cold Storage Hub",       "Reload outbound product"),
    ("I-76 East — Commerce City",    "En route Greeley"),
    ("Greeley Distribution Center",  "Main delivery — rear door open 20 min"),
    ("Greeley Distribution Center",  "Unload complete — doors sealed"),
    ("I-76 West — Mile 30",          "Return leg"),
    ("I-25 North — Mile 205",        "Return leg"),
    ("Food World Cold Storage",       "Return — connected to dock cooldown"),
]

run_dates_v2 = []
d = datetime.date(2026, 4, 14)
while d <= datetime.date(2026, 5, 2):
    if d.weekday() in (0, 3):  # Mon, Thu
        run_dates_v2.append(d)
    d += datetime.timedelta(days=1)

added_v2 = 0
for run_date in run_dates_v2:
    base_temp = random.uniform(v2_min + 0.5, v2_max - 0.5)
    for i, (loc, note) in enumerate(freezer_stops):
        dt = datetime.datetime.combine(run_date, datetime.time(5, 0)) + datetime.timedelta(minutes=i*42)
        drift = 0.0
        if "door open" in note.lower():
            drift = random.uniform(0.8, 2.5)
        if "Genesee Summit" in loc:
            drift = random.uniform(-0.5, 0.5)  # stable at altitude
        temp = base_temp + drift + random.uniform(-0.3, 0.3)
        hum = random.uniform(50, 62)
        out_of_range = temp > v2_max or temp < v2_min
        extra_note = " ALERT: temp breach" if out_of_range else ""
        added_v2 += add_reading(v2, dt, temp, hum, loc, note + extra_note)

db.commit()
print(f"Freezer Trailer: added {added_v2} readings across {len(run_dates_v2)} run days")

total = added_v0 + added_v1 + added_v2
print(f"\nTotal new readings added: {total}")
print("Done.")
