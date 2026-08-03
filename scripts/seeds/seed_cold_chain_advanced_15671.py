"""
seed_cold_chain_advanced_15671.py
Populates test data for all 6 advanced cold-chain features on BusinessID=15671:
  1. Multi-sensor readings (ethylene, CO2, light/door, GPS, shock G-force)
  2. Shelf-life records
  3. Shock / vibration events
  4. Chain-of-custody events (hash-chained)
  5. Geofence zones + events
  6. Power status on vehicles (reefer fuel, battery)

Run from: f:\\Oatmeal AI\\OatmealFarmNetwork Repo\\Backend\\oatmealfarmnetworkbackend
  python seed_cold_chain_advanced_15671.py
"""
import sys, random, hashlib, json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import get_db
from sqlalchemy import text

BID = 15671
db = next(get_db())
rng = random.Random(42)

def q(sql, params=None):
    db.execute(text(sql), params or {})

def first(sql, params=None):
    return db.execute(text(sql), params or {}).scalar()

def fetchall(sql, params=None):
    return db.execute(text(sql), params or {}).fetchall()

# ── Get vehicles ──────────────────────────────────────────────────────────────
rows = fetchall(
    "SELECT VehicleID, VehicleName, MinTempC, MaxTempC FROM ColdChainVehicle WHERE BusinessID=:b ORDER BY VehicleID",
    {"b": BID},
)
if not rows:
    print("No vehicles found. Run the base seed first.")
    sys.exit(1)

vehicles = [(r[0], r[1], float(r[2]), float(r[3])) for r in rows]
print(f"Vehicles: {[(v[0], v[1]) for v in vehicles]}")

v0_id, v0_name, v0_min, v0_max = vehicles[0]  # Refrigerated Box Truck
v1_id, v1_name, v1_min, v1_max = vehicles[1] if len(vehicles) > 1 else (None, None, -2, 7)
v2_id, v2_name, v2_min, v2_max = vehicles[2] if len(vehicles) > 2 else (None, None, -2, 7)

now = datetime.now()

# ── Helper: SHA-256 chain ─────────────────────────────────────────────────────
def compute_hash(event_type, from_party, to_party, temp_c, occurred_at, prev_hash):
    payload = json.dumps({
        "type": event_type or "",
        "from": from_party or "",
        "to":   to_party or "",
        "temp": str(temp_c or ""),
        "at":   str(occurred_at),
        "prev": prev_hash or "",
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()

# ─────────────────────────────────────────────────────────────────────────────
# 1. MULTI-SENSOR READINGS
# Add enhanced readings with ethylene, CO2, light, GPS, door events
# ─────────────────────────────────────────────────────────────────────────────
print("\n[1] Adding multi-sensor readings …")

# GPS corridor for Vehicle 0 (Albuquerque area delivery route)
gps_stops = [
    (35.0844, -106.6504),  # Albuquerque downtown
    (35.1053, -106.6460),  # North route
    (35.1237, -106.5888),  # NE distribution
    (35.0750, -106.5500),  # East side stop
    (35.0553, -106.6504),  # South restaurant row
    (35.0700, -106.6800),  # West side stop
    (35.0844, -106.6504),  # Return to depot
]

# Simulate last 5 days of enhanced readings for V0
v0_readings = []
for day_offset in range(5):
    base_dt = now - timedelta(days=day_offset, hours=6)  # 6am start
    for i, (lat, lon) in enumerate(gps_stops):
        dt = base_dt + timedelta(minutes=i * 25)
        temp = rng.uniform(v0_min + 0.3, v0_max - 0.5)
        humidity = rng.uniform(88, 95)
        # Simulate realistic ethylene — higher near fruit stops
        ethylene = rng.uniform(0.02, 0.08) if i in (3, 4) else rng.uniform(0.005, 0.025)
        co2 = rng.randint(750, 1100)
        light = 0.0  # dark inside reefer
        door_open = False
        shock_g = None
        notes = ""

        # Door-open event at loading dock and first customer
        if i == 0:
            door_open = True
            light = rng.uniform(800, 1500)
            notes = "Loading dock — door open for loading"
        elif i == 3 and day_offset == 1:
            door_open = True
            light = rng.uniform(200, 600)
            notes = "Customer delivery — door open event"

        # One temp excursion event (reefer cycling issue)
        if day_offset == 2 and i == 4:
            temp = v0_max + rng.uniform(1.5, 3.0)
            notes = "⚠ Temp excursion — reefer cycling lag after long idle"

        # Minor road shock at highway on-ramp
        if i == 1 and day_offset == 0:
            shock_g = round(rng.uniform(0.8, 1.4), 2)
            notes = "On-ramp bump"

        v0_readings.append((dt, temp, humidity, ethylene, co2, light, door_open, lat, lon, shock_g,
                            f"{['Food World Dock','I-25 North','NE Distribution','East Side Stop','Restaurant Row','West Side','Return to Depot'][i]}",
                            notes))

inserted = 0
for (dt, temp, hum, ethylene, co2, light, door, lat, lon, shock, loc, notes) in v0_readings:
    exists = first("SELECT 1 FROM ColdChainReading WHERE VehicleID=:v AND RecordedAt=:dt", {"v": v0_id, "dt": dt})
    if not exists:
        q("""
            INSERT INTO ColdChainReading
                (VehicleID, TempC, Humidity, EthyleneGasPPM, CO2PPM, LightLux, DoorOpenFlag,
                 GpsLat, GpsLon, ShockGForce, LocationDesc, RecordedAt, Notes)
            VALUES
                (:v, :t, :h, :eth, :co2, :lux, :door,
                 :lat, :lon, :shock, :loc, :dt, :notes)
        """, {
            "v": v0_id, "t": round(temp, 2), "h": round(hum, 1),
            "eth": round(ethylene, 4), "co2": co2, "lux": round(light, 1),
            "door": 1 if door else 0,
            "lat": round(lat, 6), "lon": round(lon, 6),
            "shock": shock, "loc": loc, "dt": dt, "notes": notes,
        })
        inserted += 1

# Add a refrigerated van route for V1 (Albuquerque south to Santa Fe corridor)
if v1_id:
    v1_gps = [
        (35.0500, -106.6800),  # South depot
        (35.1000, -106.4500),  # East warehouse
        (35.4000, -106.0500),  # Mountain pass (higher altitude — colder)
        (35.6500, -105.9500),  # Santa Fe cold storage
        (35.6869, -105.9378),  # Santa Fe market
    ]
    for day_offset in range(3):
        base_dt = now - timedelta(days=day_offset, hours=7)
        for i, (lat, lon) in enumerate(v1_gps):
            dt = base_dt + timedelta(minutes=i * 35)
            temp = v1_min + rng.uniform(0.5, 2.5)
            if i == 2:  # mountain pass — slightly colder
                temp = v1_min + rng.uniform(0.0, 0.8)
            humidity = rng.uniform(85, 92)
            ethylene = rng.uniform(0.01, 0.04)
            co2 = rng.randint(700, 900)
            door_open = (i in (0, 4))
            light = rng.uniform(500, 2000) if door_open else 0.0
            loc = ["South Depot Load", "East Warehouse Stop", "Mountain Pass", "Santa Fe Cold Storage", "Santa Fe Farmers Market"][i]
            exists = first("SELECT 1 FROM ColdChainReading WHERE VehicleID=:v AND RecordedAt=:dt", {"v": v1_id, "dt": dt})
            if not exists:
                q("""
                    INSERT INTO ColdChainReading
                        (VehicleID, TempC, Humidity, EthyleneGasPPM, CO2PPM, LightLux, DoorOpenFlag,
                         GpsLat, GpsLon, LocationDesc, RecordedAt)
                    VALUES (:v, :t, :h, :eth, :co2, :lux, :door, :lat, :lon, :loc, :dt)
                """, {
                    "v": v1_id, "t": round(temp, 2), "h": round(humidity, 1),
                    "eth": round(ethylene, 4), "co2": co2, "lux": round(light, 1),
                    "door": 1 if door_open else 0,
                    "lat": round(lat, 6), "lon": round(lon, 6),
                    "loc": loc, "dt": dt,
                })
                inserted += 1

db.commit()
print(f"  Inserted {inserted} enhanced readings.")

# ─────────────────────────────────────────────────────────────────────────────
# 2. POWER STATUS on vehicles
# ─────────────────────────────────────────────────────────────────────────────
print("\n[2] Updating power status …")

power_data = [
    (v0_id, 78.0, 92.0),   # V0 — healthy
    (v1_id, 21.0, 55.0),   # V1 — reefer fuel warning
    (v2_id, 67.0, 18.0),   # V2 — tracker battery low
]
for (vid, fuel, battery) in power_data:
    if vid is None:
        continue
    q("""
        UPDATE ColdChainVehicle
        SET ReeferFuelPct=:fuel, BatteryPct=:battery, LastPingAt=:ping, PowerAlertSent=:alert
        WHERE VehicleID=:v
    """, {
        "v": vid, "fuel": fuel, "battery": battery,
        "ping": now - timedelta(minutes=rng.randint(3, 45)),
        "alert": 1 if fuel <= 20 or battery <= 20 else 0,
    })
db.commit()
print("  Power status updated.")

# ─────────────────────────────────────────────────────────────────────────────
# 3. SHOCK / VIBRATION EVENTS
# ─────────────────────────────────────────────────────────────────────────────
print("\n[3] Adding shock / vibration events …")

# Clear existing for idempotency
q("DELETE FROM ColdChainShockEvent WHERE BusinessID=:b", {"b": BID})
db.commit()

# Get a shipment ID for V0 to link shocks to
shipment_id_v0 = first(
    "SELECT TOP 1 ShipmentID FROM ColdChainShipment WHERE VehicleID=:v ORDER BY CreatedAt DESC", {"v": v0_id}
)

shock_events = [
    # (vehicle_id, occurred_at, peak_g, duration_ms, axis, shipment_id, lat, lon, location, notes)
    (v0_id, now - timedelta(days=4, hours=5, minutes=10), 1.2, 80,   "z",   None,          35.0844, -106.6504, "Food World Loading Dock",      "Minor bump during pallet load — forklift edge hit"),
    (v0_id, now - timedelta(days=3, hours=2, minutes=22), 2.8, 150,  "xyz", shipment_id_v0, 35.1053, -106.6460, "I-25 North on-ramp",           "Road debris / pothole — speed not reduced"),
    (v0_id, now - timedelta(days=2, hours=4, minutes=45), 1.6, 95,   "y",   shipment_id_v0, 35.0750, -106.5500, "East Side Restaurant alley",   "Tight turn over speed bump"),
    (v0_id, now - timedelta(days=1, hours=3, minutes=5),  5.4, 210,  "z",   None,          35.0700, -106.6800, "West Side receiving dock",     "⚠ SEVERE — sudden hard brake / rear-end near miss"),
    (v0_id, now - timedelta(hours=6, minutes=30),         0.9, 60,   "x",   None,          35.0553, -106.6504, "Restaurant Row delivery bay",  "Normal dock approach"),
    # V1 shocks
    (v1_id, now - timedelta(days=2, hours=6, minutes=15), 3.1, 175,  "z",   None,          35.4000, -106.0500, "NM-14 mountain switchback",    "Rough road surface — speed limit posted 35mph"),
    (v1_id, now - timedelta(days=1, hours=1, minutes=50), 1.4, 90,   "xyz", None,          35.6500, -105.9500, "Santa Fe cold storage dock",   "Loading arm contact during unload"),
] if v1_id else [
    (v0_id, now - timedelta(days=4, hours=5, minutes=10), 1.2, 80,   "z",   None,          35.0844, -106.6504, "Food World Loading Dock",      "Minor bump during pallet load"),
    (v0_id, now - timedelta(days=3, hours=2, minutes=22), 2.8, 150,  "xyz", shipment_id_v0, 35.1053, -106.6460, "I-25 North on-ramp",          "Road debris / pothole"),
    (v0_id, now - timedelta(days=1, hours=3, minutes=5),  5.4, 210,  "z",   None,          35.0700, -106.6800, "West Side receiving dock",     "⚠ SEVERE — hard brake"),
    (v0_id, now - timedelta(hours=6, minutes=30),         0.9, 60,   "x",   None,          35.0553, -106.6504, "Restaurant Row delivery bay",  "Normal dock approach"),
]

for (vid, occ, g, dur, axis, sid, lat, lon, loc, notes) in shock_events:
    if vid is None:
        continue
    q("""
        INSERT INTO ColdChainShockEvent
            (VehicleID, BusinessID, OccurredAt, PeakGForce, DurationMs, Axis,
             ShipmentID, GpsLat, GpsLon, LocationDesc, Notes)
        VALUES (:v, :b, :at, :g, :dur, :axis, :sid, :lat, :lon, :loc, :notes)
    """, {
        "v": vid, "b": BID, "at": occ, "g": g, "dur": dur, "axis": axis,
        "sid": sid, "lat": lat, "lon": lon, "loc": loc, "notes": notes,
    })

db.commit()
print(f"  Inserted {len(shock_events)} shock events.")

# ─────────────────────────────────────────────────────────────────────────────
# 4. GEOFENCE ZONES + EVENTS
# ─────────────────────────────────────────────────────────────────────────────
print("\n[4] Adding geofence zones and events …")

q("DELETE FROM ColdChainGeofenceEvent WHERE BusinessID=:b", {"b": BID})
q("DELETE FROM ColdChainGeofenceZone  WHERE BusinessID=:b", {"b": BID})
db.commit()

zones = [
    # (name, lat, lon, radius_m, zone_type)
    ("Food World Main Depot",         35.0844, -106.6504, 150, "depot"),
    ("NE Distribution Center",        35.1237, -106.5888, 200, "cold_storage"),
    ("Restaurant Row Delivery Bay",   35.0553, -106.6504, 100, "customer"),
    ("I-25 / Montgomery Weigh Station", 35.1400, -106.6300, 300, "border_crossing"),
    ("Santa Fe Cold Storage Hub",     35.6500, -105.9500, 250, "cold_storage"),
    ("Albuquerque Airport Cargo",     35.0402, -106.6090, 400, "warehouse"),
    ("West Side Organic Market",      35.0700, -106.6800, 120, "customer"),
]

zone_ids = []
for (name, lat, lon, radius, ztype) in zones:
    row = db.execute(text("""
        INSERT INTO ColdChainGeofenceZone
            (BusinessID, ZoneName, CenterLat, CenterLon, RadiusMeters, ZoneType, AlertOnEnter, AlertOnExit)
        OUTPUT INSERTED.ZoneID
        VALUES (:b, :name, :lat, :lon, :r, :ztype, 1, 1)
    """), {"b": BID, "name": name, "lat": lat, "lon": lon, "r": radius, "ztype": ztype}).fetchone()
    zone_ids.append(row[0])
db.commit()
print(f"  Created {len(zone_ids)} geofence zones.")

# Geofence events for the last 3 days of V0 route
zone_depot, zone_ne_dist, zone_restaurant, zone_weigh, zone_sf, zone_airport, zone_west = zone_ids

geo_events = [
    # Day -2: Full route V0
    (v0_id, now - timedelta(days=2, hours=6, minutes=0),  zone_depot,      "exit",  35.0844, -106.6504, True,  "Departed Food World — 06:00 route start"),
    (v0_id, now - timedelta(days=2, hours=6, minutes=38), zone_ne_dist,    "enter", 35.1237, -106.5888, True,  "Arrived NE Distribution"),
    (v0_id, now - timedelta(days=2, hours=6, minutes=55), zone_ne_dist,    "exit",  35.1237, -106.5888, True,  "Departed NE Distribution — 4 pallets offloaded"),
    (v0_id, now - timedelta(days=2, hours=7, minutes=50), zone_restaurant, "enter", 35.0553, -106.6504, True,  "Restaurant Row — 6 deliveries"),
    (v0_id, now - timedelta(days=2, hours=8, minutes=45), zone_restaurant, "exit",  35.0553, -106.6504, True,  "Restaurant Row complete"),
    (v0_id, now - timedelta(days=2, hours=9, minutes=15), zone_west,       "enter", 35.0700, -106.6800, False, "West Side Organic — manual check-in"),
    (v0_id, now - timedelta(days=2, hours=9, minutes=40), zone_west,       "exit",  35.0700, -106.6800, False, "West Side complete"),
    (v0_id, now - timedelta(days=2, hours=10, minutes=5), zone_depot,      "enter", 35.0844, -106.6504, True,  "Returned to depot — route complete"),
    # Day -1: Partial route V0
    (v0_id, now - timedelta(days=1, hours=6, minutes=5),  zone_depot,      "exit",  35.0844, -106.6504, True,  "Morning departure"),
    (v0_id, now - timedelta(days=1, hours=6, minutes=42), zone_ne_dist,    "enter", 35.1237, -106.5888, True,  "NE Distribution arrival"),
    (v0_id, now - timedelta(days=1, hours=7, minutes=8),  zone_ne_dist,    "exit",  35.1237, -106.5888, True,  "NE Distribution departure"),
    (v0_id, now - timedelta(days=1, hours=10, minutes=0), zone_depot,      "enter", 35.0844, -106.6504, True,  "Return to depot"),
    # Today: V0 in-progress
    (v0_id, now - timedelta(hours=5, minutes=50),         zone_depot,      "exit",  35.0844, -106.6504, True,  "Today route start"),
    (v0_id, now - timedelta(hours=4, minutes=55),         zone_restaurant, "enter", 35.0553, -106.6504, True,  "Restaurant Row — in progress"),
]

# Add V1 events (Santa Fe route)
if v1_id:
    geo_events += [
        (v1_id, now - timedelta(days=1, hours=7, minutes=0),  zone_depot,   "exit",  35.0500, -106.6800, True,  "V1 South Depot departure"),
        (v1_id, now - timedelta(days=1, hours=9, minutes=30), zone_sf,      "enter", 35.6500, -105.9500, True,  "V1 arrived Santa Fe Cold Storage"),
        (v1_id, now - timedelta(days=1, hours=10, minutes=15), zone_sf,     "exit",  35.6500, -105.9500, True,  "V1 departed Santa Fe — unload complete"),
        (v1_id, now - timedelta(days=1, hours=13, minutes=0), zone_depot,   "enter", 35.0500, -106.6800, True,  "V1 return to depot"),
    ]

for (vid, occ, zid, etype, lat, lon, auto, notes) in geo_events:
    if vid is None:
        continue
    q("""
        INSERT INTO ColdChainGeofenceEvent
            (VehicleID, ZoneID, BusinessID, OccurredAt, EventType, GpsLat, GpsLon, AutoCheckIn, Notes)
        VALUES (:v, :z, :b, :at, :etype, :lat, :lon, :auto, :notes)
    """, {
        "v": vid, "z": zid, "b": BID, "at": occ, "etype": etype,
        "lat": lat, "lon": lon, "auto": 1 if auto else 0, "notes": notes,
    })
db.commit()
print(f"  Inserted {len(geo_events)} geofence events.")

# ─────────────────────────────────────────────────────────────────────────────
# 5. CHAIN OF CUSTODY (hash-chained)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[5] Adding chain-of-custody events …")

q("DELETE FROM ColdChainCustodyEvent WHERE BusinessID=:b", {"b": BID})
db.commit()

# V0: 3-day farm-to-restaurant full chain (timestamps in ascending chronological order)
# Larger timedelta = further in the past = earlier event
v0_custody_raw = [
    # (occurred_at, handover_type, from_party, to_party, signed_by, temp_c, humidity, lat, lon, notes)
    (now - timedelta(days=4, hours=12),            "farm_load",         "Sunrise Organic Farm",         "Oatmeal Farm Network Fleet",  "Carlos R.",       3.2, 88.0, 35.1500, -106.4800, "Farm pickup — produce inspected, temp verified at loading"),
    (now - timedelta(days=4, hours=9, minutes=30), "cold_storage_in",   "Oatmeal Farm Network Fleet",   "Albuquerque Cold Hub (Bay 3)", "Maria L.",        2.8, 90.5, 35.0844, -106.6504, "Interim cold storage — overnight hold, power backup verified"),
    (now - timedelta(days=3, hours=14),            "cold_storage_out",  "Albuquerque Cold Hub (Bay 3)", "Oatmeal Farm Network Fleet",  "Carlos R.",       3.0, 91.0, 35.0844, -106.6504, "Morning dispatch — 3 pallets butter lettuce, 2 pallets berries"),
    (now - timedelta(days=3, hours=12),            "truck_transfer",    "Oatmeal Farm Network Fleet",   "NE Distribution Center",      "Dispatcher A.",   3.1, 89.5, 35.1237, -106.5888, "Transfer to distribution partner — 1 pallet berries split off"),
    (now - timedelta(days=3, hours=9),             "delivery",          "Oatmeal Farm Network Fleet",   "El Camino Restaurant Group",  "Chef Rodriguez",  4.2, 87.0, 35.0553, -106.6504, "Restaurant Row delivery — 4 stops completed, receiver signed"),
]

# V1: Farm to Santa Fe full chain
v1_custody_raw = [
    (now - timedelta(days=2, hours=12),            "farm_load",         "Mesa Verde Organics",          "OFN South Fleet",             "Miguel S.",       2.5, 92.0, 35.0500, -106.6800, "South route pickup — eggs, dairy, berries"),
    (now - timedelta(days=2, hours=9, minutes=30), "cold_storage_in",   "OFN South Fleet",              "Santa Fe Cold Storage Hub",   "Ana P.",          2.2, 93.0, 35.6500, -105.9500, "Santa Fe hub intake — temp envelope maintained throughout"),
    (now - timedelta(days=2, hours=7),             "cold_storage_out",  "Santa Fe Cold Storage Hub",    "OFN South Fleet",             "Ana P.",          2.4, 92.5, 35.6500, -105.9500, "Final mile preparation — split load for two market stops"),
    (now - timedelta(days=2, hours=5),             "delivery",          "OFN South Fleet",              "Santa Fe Farmers Market",     "Market Mgr T.",   3.8, 88.0, 35.6869, -105.9378, "Farmers market delivery — all product accepted"),
] if v1_id else []

for vehicle_id, custody_raw in [(v0_id, v0_custody_raw), (v1_id, v1_custody_raw)]:
    if vehicle_id is None:
        continue
    prev_hash = None
    for (occ, htype, from_p, to_p, signed, temp, hum, lat, lon, notes) in custody_raw:
        event_hash = compute_hash(htype, from_p, to_p, temp, occ, prev_hash)
        q("""
            INSERT INTO ColdChainCustodyEvent
                (VehicleID, BusinessID, OccurredAt, HandoverType, FromParty, ToParty,
                 SignedBy, TempCAtHandover, HumidityAtHandover, GpsLat, GpsLon,
                 PrevHash, EventHash, Notes)
            VALUES
                (:v, :b, :at, :htype, :from_p, :to_p,
                 :signed, :temp, :hum, :lat, :lon,
                 :prev, :hash, :notes)
        """, {
            "v": vehicle_id, "b": BID, "at": occ, "htype": htype,
            "from_p": from_p, "to_p": to_p, "signed": signed,
            "temp": temp, "hum": hum, "lat": lat, "lon": lon,
            "prev": prev_hash, "hash": event_hash, "notes": notes,
        })
        prev_hash = event_hash

db.commit()
n_custody = len(v0_custody_raw) + len(v1_custody_raw)
print(f"  Inserted {n_custody} custody events (hash-chained).")

# ─────────────────────────────────────────────────────────────────────────────
# 6. SHELF-LIFE RECORDS
# ─────────────────────────────────────────────────────────────────────────────
print("\n[6] Adding shelf-life SLA records …")

q("DELETE FROM ColdChainShelfLife WHERE BusinessID=:b", {"b": BID})
db.commit()

# Get a recent shipment for linking
s_id_0 = first("SELECT TOP 1 ShipmentID FROM ColdChainShipment WHERE VehicleID=:v ORDER BY RunDate DESC", {"v": v0_id})

shelf_records = [
    # (vid, sid, product, ptype, orig_days, adj_days, deg_pct, exc_min, max_exc_temp, notes)
    (v0_id, s_id_0, "Butter Lettuce",   "leafy_greens", 10,  7.3, 27.0, 85,  6.8,  "Calculated after day-2 excursion — 20-min reefer lag at 6.8°C"),
    (v0_id, s_id_0, "Mixed Berry Pint", "berries",       7,  4.1, 41.4, 120, 7.2,  "Two delivery stops with extended door-open events reduced life"),
    (v0_id, s_id_0, "Roma Tomatoes",    "tomatoes",     14, 13.2,  5.7,  25, 14.3, "Minimal excursion — well within acceptable range"),
    (v0_id, None,   "Cage-Free Eggs",   "eggs",         35, 33.8,  3.4,  10,  5.1, "Excellent maintenance — negligible degradation"),
    (v0_id, None,   "Organic Spinach",  "leafy_greens", 10,  2.8, 72.0, 240,  8.9, "⚠ Express Sale — extended excursion during highway delay (4hrs)"),
]
if v1_id:
    s_id_1 = first("SELECT TOP 1 ShipmentID FROM ColdChainShipment WHERE VehicleID=:v ORDER BY RunDate DESC", {"v": v1_id})
    shelf_records += [
        (v1_id, s_id_1, "Whole Milk (1gal)", "dairy_milk",  14, 12.9,  7.9,  45,  5.3, "Mountain route cold — minimal impact"),
        (v1_id, s_id_1, "Strawberries",      "berries",      7,  5.6, 20.0,  60,  5.8, "Moderate — route within spec but borderline on berries"),
    ]

for (vid, sid, prod, ptype, orig, adj, deg, exc_min, max_exc, notes) in shelf_records:
    action = "Normal distribution"
    if adj <= 0:
        action = "Discard — shelf life exhausted"
    elif deg >= 60:
        action = "Express Sale / Priority dispatch"
    elif deg >= 30:
        action = "Expedite delivery"

    q("""
        INSERT INTO ColdChainShelfLife
            (VehicleID, BusinessID, ShipmentID, ProductName, ProductType,
             OriginalShelfLifeDays, AdjustedShelfLifeDays, DegradationPct,
             ExcursionMinutes, MaxExcursionTempC, Notes)
        VALUES (:v, :b, :sid, :prod, :ptype, :orig, :adj, :deg, :exc, :maxtemp, :notes)
    """, {
        "v": vid, "b": BID, "sid": sid, "prod": prod, "ptype": ptype,
        "orig": orig, "adj": adj, "deg": deg, "exc": exc_min,
        "maxtemp": max_exc, "notes": f"{notes} → {action}",
    })

db.commit()
print(f"  Inserted {len(shelf_records)} shelf-life records.")

# ─────────────────────────────────────────────────────────────────────────────
print("\nDone! Advanced cold-chain seed complete for BusinessID=15671.")
rows2 = fetchall("SELECT VehicleID, VehicleName, ReeferFuelPct, BatteryPct FROM ColdChainVehicle WHERE BusinessID=:b", {"b": BID})
for r in rows2:
    print(f"  Vehicle {r[0]} ({r[1]}): Reefer={r[2]}%  Battery={r[3]}%")
sr = first("SELECT COUNT(*) FROM ColdChainShockEvent WHERE BusinessID=:b", {"b": BID})
cr = first("SELECT COUNT(*) FROM ColdChainCustodyEvent WHERE BusinessID=:b", {"b": BID})
gr = first("SELECT COUNT(*) FROM ColdChainGeofenceEvent WHERE BusinessID=:b", {"b": BID})
slr = first("SELECT COUNT(*) FROM ColdChainShelfLife WHERE BusinessID=:b", {"b": BID})
print(f"  Shock events={sr}  Custody events={cr}  Geofence events={gr}  Shelf-life records={slr}")
