"""Fills in May 4 (Monday) readings — missed in the previous extension script."""
import sys, datetime, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import get_db
from sqlalchemy import text

BID = 15671
db = next(get_db())

def q(sql, params=None):
    db.execute(text(sql), params or {})

rows = db.execute(text(
    "SELECT VehicleID, VehicleName, MinTempC, MaxTempC "
    "FROM ColdChainVehicle WHERE BusinessID=:b ORDER BY VehicleID"
), {"b": BID}).fetchall()
vehicles = [(r[0], r[1], float(r[2]), float(r[3])) for r in rows]

existing = set()
for (vid, _, _, _) in vehicles:
    ts_rows = db.execute(text(
        "SELECT RecordedAt FROM ColdChainReading WHERE VehicleID=:v"
    ), {"v": vid}).fetchall()
    existing.update((vid, r[0]) for r in ts_rows)

def add(vid, dt, temp_c, humidity, location, notes=""):
    key = (vid, dt)
    if key in existing:
        return False
    q("INSERT INTO ColdChainReading (VehicleID, TempC, Humidity, LocationDesc, RecordedAt, Notes) "
      "VALUES (:v, :t, :h, :loc, :ra, :notes)",
      {"v": vid, "t": round(temp_c, 1), "h": round(humidity, 1),
       "loc": location, "ra": dt, "notes": notes})
    existing.add(key)
    return True

RUN_DATE = datetime.date(2026, 5, 4)   # Monday

# ── Box Truck (Mon–Sat, -2..4°C) ─────────────────────────────────────────
v0, _, v0_min, v0_max = vehicles[0]
v0_stops = [
    ("Food World Loading Dock",    "Pre-trip temp check"),
    ("I-25 North -- Mile 210",     "En route"),
    ("Harvest Table Restaurant",   "Stop 1 -- unloading"),
    ("Ember Grill & Bar",          "Stop 2 -- unloading"),
    ("Roots Kitchen -- Old Town",  "Stop 3 -- unloading"),
    ("Whole Foods Market",         "Stop 4 -- wholesale drop"),
    ("I-25 South -- Return",       "Return leg"),
    ("Food World Loading Dock",    "Return -- end of run"),
]
base = random.uniform(v0_min + 0.5, v0_max - 0.5)
n0 = 0
for i, (loc, note) in enumerate(v0_stops):
    dt = datetime.datetime.combine(RUN_DATE, datetime.time(6, 0)) + datetime.timedelta(minutes=i * 28)
    drift = random.uniform(0.3, 1.2) if ("unloading" in note or "drop" in note) else 0.0
    temp = base + drift + random.uniform(-0.2, 0.2)
    hum = random.uniform(82, 92)
    oor = temp > v0_max or temp < v0_min
    n0 += add(v0, dt, temp, hum, loc, note + (" ALERT: temp breach" if oor else ""))
db.commit()
print(f"Box Truck May 4: {n0} readings")

# ── Cargo Van (Mon = CSA, 0..6°C) ────────────────────────────────────────
v1, _, v1_min, v1_max = vehicles[1]
csa_stops = [
    ("Food World Loading Dock",    "CSA box load-out"),
    ("Longmont -- Zone A drop",    "Stop 1 -- 12 boxes"),
    ("Longmont -- Zone B drop",    "Stop 2 -- 9 boxes"),
    ("Lafayette -- Zone C drop",   "Stop 3 -- 11 boxes"),
    ("Boulder -- Zone D drop",     "Stop 4 -- 14 boxes"),
    ("US-287 North -- Return",     "Return leg"),
    ("Food World Loading Dock",    "Return -- end of run"),
]
base = random.uniform(v1_min + 0.5, v1_max - 1.0)
n1 = 0
for i, (loc, note) in enumerate(csa_stops):
    dt = datetime.datetime.combine(RUN_DATE, datetime.time(6, 30)) + datetime.timedelta(minutes=i * 40)
    temp = base + random.uniform(-0.3, 0.3)
    hum = random.uniform(75, 87)
    oor = temp > v1_max or temp < v1_min
    n1 += add(v1, dt, temp, hum, loc, note + (" ALERT: temp breach" if oor else ""))
db.commit()
print(f"Cargo Van May 4: {n1} readings")

# ── Freezer Trailer (Mon, -20..-15°C) ────────────────────────────────────
v2, _, v2_min, v2_max = vehicles[2]
freezer_stops = [
    ("Food World Cold Storage",     "Pre-trip inspection -- doors sealed"),
    ("I-25 South -- Mile 190",      "En route Denver"),
    ("I-70 West -- Genesee Summit", "High altitude check"),
    ("Denver Cold Storage Hub",     "Transfer -- partial unload"),
    ("Denver Cold Storage Hub",     "Reload outbound product"),
    ("I-76 East -- Commerce City",  "En route Greeley"),
    ("Greeley Distribution Center", "Main delivery -- rear door open 20 min"),
    ("Greeley Distribution Center", "Unload complete -- doors sealed"),
    ("I-76 West -- Mile 30",        "Return leg"),
    ("I-25 North -- Mile 205",      "Return leg"),
    ("Food World Cold Storage",     "Return -- connected to dock cooldown"),
]
base = random.uniform(v2_min + 0.5, v2_max - 0.5)
n2 = 0
for i, (loc, note) in enumerate(freezer_stops):
    dt = datetime.datetime.combine(RUN_DATE, datetime.time(5, 0)) + datetime.timedelta(minutes=i * 42)
    drift = random.uniform(0.8, 2.5) if "door open" in note.lower() else 0.0
    if "Genesee Summit" in loc:
        drift = random.uniform(-0.5, 0.5)
    temp = base + drift + random.uniform(-0.3, 0.3)
    hum = random.uniform(50, 62)
    oor = temp > v2_max or temp < v2_min
    n2 += add(v2, dt, temp, hum, loc, note + (" ALERT: temp breach" if oor else ""))
db.commit()
print(f"Freezer Trailer May 4: {n2} readings")

print(f"\nTotal added: {n0 + n1 + n2}")
