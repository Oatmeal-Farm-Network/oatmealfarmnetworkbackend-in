"""
seed_cold_chain_shipments_maint_15671.py
Adds ColdChainShipment + ColdChainShipmentItem + ColdChainMaintenance records
for BusinessID=15671's three vehicles.
Idempotent: skips on RouteLabel+RunDate for shipments, ServiceType+ServiceDate for maintenance.
"""
import sys, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import get_db
from sqlalchemy import text

BID = 15671
db  = next(get_db())

def q(sql, params=None):
    db.execute(text(sql), params or {})

def first(sql, params=None):
    return db.execute(text(sql), params or {}).scalar()

# Fetch vehicle IDs
rows = db.execute(text(
    "SELECT VehicleID, VehicleName, MinTempC, MaxTempC "
    "FROM ColdChainVehicle WHERE BusinessID=:b ORDER BY VehicleID"
), {"b": BID}).fetchall()

if not rows:
    print("No vehicles found. Run seed_demo_15671d.py first.")
    sys.exit(1)

V = {r[1]: r[0] for r in rows}   # name -> id
v0 = rows[0][0]   # Box Truck
v1 = rows[1][0]   # Cargo Van
v2 = rows[2][0]   # Freezer Trailer
print(f"Vehicles: {[(r[1], r[0]) for r in rows]}")

def d(s): return datetime.date.fromisoformat(s) if s else None
def dt(s): return datetime.datetime.fromisoformat(s) if s else None


# ─────────────────────────────────────────────────────────────────────────────
# SHIPMENTS
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Shipments ===")

# (vehicle_id, run_date, route_label, status, driver, departed, arrived, miles, notes, items)
# items = (product_name, qty, unit, recipient, notes)
SHIPMENTS = [

    # ── Box Truck #1 — Restaurant delivery route ─────────────────────────────
    (v0, "2026-04-28", "Restaurant Route A — Monday", "completed",
     "Marcus Rivera", "2026-04-28T06:02", "2026-04-28T11:45", 87.4,
     "Full load of spring produce + alpaca stew cuts. Door seal passed pre-trip. All stops on time.",
     [
         ("Heirloom Tomatoes (mixed)",    18, "cases",   "Harvest Table Restaurant",  "3 varieties, ordered Brandywine heavy"),
         ("Spring Lettuce Mix",           12, "cases",   "Ember Grill & Bar",         None),
         ("Ground Alpaca (1 lb pkgs)",     6, "cases",   "Roots Kitchen -- Old Town", "Vacuum sealed"),
         ("Zucchini & Summer Squash",     10, "cases",   "Whole Foods Market",        "Wholesale — priced per agreement"),
         ("Herb Bundle Assortment",        4, "flats",   "Harvest Table Restaurant",  "Basil, cilantro, dill, thyme"),
     ]),

    (v0, "2026-04-30", "Restaurant Route A — Wednesday", "completed",
     "Marcus Rivera", "2026-04-30T06:00", "2026-04-30T12:10", 89.1,
     "Light load. Wednesday supplement run — top-ups for Harvest Table and Ember.",
     [
         ("Strawberries (1-pint flats)",  24, "flats",  "Ember Grill & Bar",          "Peak berry week"),
         ("Cherry Tomatoes",             16, "cases",   "Harvest Table Restaurant",   None),
         ("Radishes (bunch)",             8, "bunches", "Whole Foods Market",         None),
     ]),

    (v0, "2026-05-02", "Restaurant Route A — Friday", "completed",
     "Marcus Rivera", "2026-05-02T06:05", "2026-05-02T11:55", 86.8,
     "End-of-week push before market weekend. Alpaca roast delivered in insulated liner bags.",
     [
         ("Alpaca Roast (3 lb)",          4, "bags",    "Harvest Table Restaurant",   "Special order — call ahead"),
         ("Heirloom Tomatoes (mixed)",   14, "cases",   "Roots Kitchen -- Old Town",  None),
         ("Baby Salad Mix",              10, "cases",   "Whole Foods Market",         None),
         ("Fresh Basil Bunch",           20, "bunches", "Ember Grill & Bar",          "Peak basil season"),
     ]),

    (v0, "2026-05-05", "Restaurant Route A — Monday", "completed",
     "Marcus Rivera", "2026-05-05T06:01", "2026-05-05T11:50", 88.2,
     "Normal run. Temp breach flag on Ember stop — door left open during long unload. Documented.",
     [
         ("Heirloom Tomatoes (mixed)",   16, "cases",  "Harvest Table Restaurant",   None),
         ("Ground Alpaca (1 lb pkgs)",    8, "cases",  "Ember Grill & Bar",          "Longer unload -- door open 8 min"),
         ("Spring Lettuce Mix",          12, "cases",  "Roots Kitchen -- Old Town",  None),
         ("Zucchini",                     8, "cases",  "Whole Foods Market",         None),
     ]),

    (v0, "2026-05-06", "Restaurant Route A — Tuesday", "in_transit",
     "Marcus Rivera", "2026-05-06T06:00", None, None,
     "Today's run in progress. All stops scheduled before noon.",
     [
         ("Heirloom Tomatoes (mixed)",   14, "cases",  "Harvest Table Restaurant",   None),
         ("Alpaca Stew Cuts (2 lb)",      5, "pkgs",   "Roots Kitchen -- Old Town",  None),
         ("Herb Bundle Assortment",       3, "flats",  "Ember Grill & Bar",          None),
     ]),

    # ── Cargo Van #2 — Farmers market + CSA ──────────────────────────────────
    (v1, "2026-04-26", "Boulder Farmers Market — Saturday", "completed",
     "Elena Kowalski", "2026-04-26T06:28", "2026-04-26T14:45", 52.3,
     "Strong Saturday sales. Strawberries sold out by 10 AM. Mid-market temp rose to 6.8°C — documented breach.",
     [
         ("Strawberries (1-pint flats)",  60, "flats",  "Market -- retail",           "Sold out 10 AM"),
         ("Heirloom Tomatoes (mixed)",    30, "cases",  "Market -- retail",           None),
         ("Baby Salad Mix",              20, "cases",   "Market -- retail",           None),
         ("Alpaca Fiber -- Raw Fleece",   5, "bags",    "Market -- fiber arts table", "2 lb bags, natural colors"),
         ("Alpaca Roving (processed)",    8, "skeins",  "Market -- fiber arts table", "White + fawn"),
     ]),

    (v1, "2026-04-28", "CSA Monday Delivery", "completed",
     "Elena Kowalski", "2026-04-28T06:31", "2026-04-28T11:20", 68.7,
     "Week 4 CSA boxes. All 46 boxes delivered on time. No temp issues.",
     [
         ("CSA Box -- Full Share",       24, "boxes",  "Longmont Zone A + B",        "12+12 split"),
         ("CSA Box -- Half Share",       10, "boxes",  "Lafayette Zone C",           None),
         ("CSA Box -- Full Share",       12, "boxes",  "Boulder Zone D",             None),
     ]),

    (v1, "2026-05-01", "Boulder Farmers Market -- Thursday Early", "completed",
     "Elena Kowalski", "2026-05-01T06:30", "2026-05-01T13:10", 50.9,
     "Thursday specialty market. Slower than Saturday but strong on alpaca fiber sales.",
     [
         ("Strawberries (1-pint flats)",  36, "flats", "Market -- retail",           None),
         ("Cherry Tomatoes",             18, "cases",  "Market -- retail",           None),
         ("Alpaca Roving (processed)",   12, "skeins", "Market -- fiber arts table", "Best seller this week"),
         ("Herb Bundle Assortment",      15, "bunches","Market -- retail",           None),
     ]),

    (v1, "2026-05-03", "Boulder Farmers Market -- Saturday", "completed",
     "Elena Kowalski", "2026-05-03T06:30", "2026-05-03T15:00", 53.1,
     "Busiest Saturday yet. Heat at 11 AM pushed van interior to 7.2°C -- breach logged and reported. Moved to shade.",
     [
         ("Strawberries (1-pint flats)",  72, "flats", "Market -- retail",           "New record -- sold all"),
         ("Heirloom Tomatoes (mixed)",    40, "cases", "Market -- retail",           None),
         ("Baby Salad Mix",              24, "cases",  "Market -- retail",           None),
         ("Alpaca Fiber -- Raw Fleece",   8, "bags",   "Market -- fiber arts table", None),
         ("Alpaca Roving (processed)",   10, "skeins", "Market -- fiber arts table", None),
     ]),

    (v1, "2026-05-05", "CSA Monday Delivery", "completed",
     "Elena Kowalski", "2026-05-05T06:32", "2026-05-05T11:35", 67.4,
     "Week 5 CSA. Added 3 add-on berry boxes to Zone D subscribers.",
     [
         ("CSA Box -- Full Share",       24, "boxes",  "Longmont Zone A + B",        None),
         ("CSA Box -- Half Share",       10, "boxes",  "Lafayette Zone C",           None),
         ("CSA Box -- Full Share + Berry",15,"boxes",  "Boulder Zone D",             "3 add-on berry boxes included"),
     ]),

    # ── Freezer Trailer #3 — Long-haul Denver/Greeley ────────────────────────
    (v2, "2026-04-17", "Denver + Greeley Long-Haul", "completed",
     "Garrett Olson", "2026-04-17T05:02", "2026-04-17T15:30", 214.6,
     "Standard bi-weekly haul. Transferred frozen alpaca meat and CSA frozen add-ons at Denver hub.",
     [
         ("Frozen Ground Alpaca (1 lb)", 120, "pkgs",  "Denver Cold Storage Hub",    "Transferred to partner distributor"),
         ("Frozen Alpaca Stew Cuts",      48, "pkgs",  "Greeley Distribution Center",None),
         ("Frozen Berry Mix (2 lb)",      60, "bags",  "Greeley Distribution Center","Strawberry + blueberry blend"),
         ("Frozen Alpaca Roast (3 lb)",   24, "pkgs",  "Denver Cold Storage Hub",    None),
     ]),

    (v2, "2026-04-24", "Denver + Greeley Long-Haul", "completed",
     "Garrett Olson", "2026-04-24T05:00", "2026-04-24T15:45", 216.2,
     "Larger load than usual. Added 30-min dock wait at Greeley -- rear door open longer, temp rose 1.8°C.",
     [
         ("Frozen Ground Alpaca (1 lb)", 144, "pkgs",  "Denver Cold Storage Hub",    None),
         ("Frozen Alpaca Stew Cuts",      72, "pkgs",  "Greeley Distribution Center","Extended dock -- breach noted"),
         ("Frozen Peas (1 lb)",           48, "bags",  "Greeley Distribution Center","First pea harvest of season"),
         ("Frozen Berry Mix (2 lb)",      48, "bags",  "Denver Cold Storage Hub",    None),
     ]),

    (v2, "2026-05-01", "Denver + Greeley Long-Haul", "completed",
     "Garrett Olson", "2026-05-01T05:01", "2026-05-01T15:20", 213.8,
     "Clean run. No temp excursions. Dropped fiber processing supplies at Denver hub return leg.",
     [
         ("Frozen Ground Alpaca (1 lb)", 132, "pkgs",  "Denver Cold Storage Hub",    None),
         ("Frozen Alpaca Stew Cuts",      60, "pkgs",  "Greeley Distribution Center",None),
         ("Frozen Berry Mix (2 lb)",      72, "bags",  "Greeley Distribution Center",None),
         ("Frozen Peas (1 lb)",           36, "bags",  "Denver Cold Storage Hub",    None),
     ]),

    (v2, "2026-05-04", "Denver + Greeley Long-Haul", "completed",
     "Garrett Olson", "2026-05-04T05:00", "2026-05-04T15:10", 214.0,
     "Monday run. Smooth haul. Added alpaca fiber bags to return load (back to farm from fiber processor).",
     [
         ("Frozen Ground Alpaca (1 lb)", 120, "pkgs",  "Denver Cold Storage Hub",    None),
         ("Frozen Alpaca Roast (3 lb)",   36, "pkgs",  "Greeley Distribution Center",None),
         ("Frozen Berry Mix (2 lb)",      60, "bags",  "Greeley Distribution Center",None),
         ("Processed Alpaca Roving",      20, "skeins","[Return load] Farm",         "Picked up from Denver fiber processor"),
     ]),
]

added_shipments = 0
added_items     = 0

for (vid, run_date, route_label, status, driver, dep, arr, miles, notes, items) in SHIPMENTS:
    exists = first(
        "SELECT ShipmentID FROM ColdChainShipment "
        "WHERE VehicleID=:v AND RunDate=:d AND RouteLabel=:l",
        {"v": vid, "d": run_date, "l": route_label}
    )
    if exists:
        print(f"  Skip: {run_date} {route_label[:40]}")
        continue

    sid = first("""
        INSERT INTO ColdChainShipment
            (VehicleID, BusinessID, RunDate, RouteLabel, Status,
             DriverName, DepartedAt, ArrivedAt, TotalMiles, Notes)
        OUTPUT INSERTED.ShipmentID
        VALUES (:v, :b, :d, :l, :s, :dr, :dep, :arr, :mi, :n)
    """, {
        "v": vid, "b": BID, "d": run_date, "l": route_label, "s": status,
        "dr": driver, "dep": dt(dep), "arr": dt(arr), "mi": miles, "n": notes,
    })

    for (prod, qty, unit, recip, inotes) in items:
        q("""
            INSERT INTO ColdChainShipmentItem
                (ShipmentID, ProductName, Quantity, Unit, Recipient, Notes)
            VALUES (:sid, :name, :qty, :unit, :recip, :notes)
        """, {"sid": sid, "name": prod, "qty": qty, "unit": unit, "recip": recip, "notes": inotes})
        added_items += 1

    db.commit()
    added_shipments += 1
    print(f"  Added: {run_date}  {route_label[:50]}")

print(f"Shipments added: {added_shipments}, items: {added_items}")


# ─────────────────────────────────────────────────────────────────────────────
# MAINTENANCE
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Maintenance ===")

# (vehicle_id, service_date, service_type, provider, technician, cost, odometer, notes, next_date)
MAINTENANCE = [

    # ── Box Truck #1 ─────────────────────────────────────────────────────────
    (v0, "2026-01-15", "Annual Safety Inspection",
     "Larimer County Fleet Services", "Ray Montoya", 185.00, 62480,
     "Passed all safety checks. Brake pads at 45% -- noted for next inspection. Lights and seals OK.",
     "2027-01-15"),

    (v0, "2026-02-10", "Refrigeration Calibration",
     "Front Range Refrigeration LLC", "Dave Kessler", 320.00, 63100,
     "Annual calibration. Thermostat was reading 0.4°C high -- adjusted. New temperature data logger installed. "
     "Verified accuracy against NIST-traceable reference thermometer.",
     "2026-08-10"),

    (v0, "2026-03-22", "Door Seal Replacement",
     "Front Range Refrigeration LLC", "Dave Kessler", 248.00, 64890,
     "Both rear door gaskets replaced. Previous seals showed visible cracking and air infiltration at -2°C test. "
     "Foam tape barrier added as secondary seal. Tested to -5°C -- holding.",
     "2027-03-22"),

    (v0, "2026-04-05", "Oil Change",
     "Jiffy Lube -- Loveland", "Staff", 89.95, 66230,
     "5W-30 synthetic. Filter replaced. Topped off coolant and windshield fluid. Tire pressure normalized to 80 PSI.",
     "2026-07-05"),

    # ── Cargo Van #2 ─────────────────────────────────────────────────────────
    (v1, "2026-01-20", "Annual Safety Inspection",
     "Larimer County Fleet Services", "Ray Montoya", 175.00, 41220,
     "Passed. Noted slight play in steering -- within tolerance but flagged for monitoring. Refrigeration seals OK.",
     "2027-01-20"),

    (v1, "2026-02-28", "Refrigeration Service",
     "Front Range Refrigeration LLC", "Dave Kessler", 410.00, 42080,
     "Full refrigeration unit service. Replaced evaporator fan motor (bearing noise). Recharged R-404A refrigerant -- "
     "was 15% low. Cleaned condenser coils. System now holding 0-6°C target range within 0.3°C.",
     "2026-08-28"),

    (v1, "2026-04-18", "Temperature Sensor Calibration",
     "Front Range Refrigeration LLC", "Dave Kessler", 195.00, 44560,
     "Pre-season calibration before farmers market runs begin. Both interior sensors verified. "
     "Display sensor slightly off -- recalibrated. Door-open alarm tested and functional.",
     "2026-10-18"),

    (v1, "2026-04-25", "Tire Rotation",
     "Discount Tire -- Longmont", "Staff", 60.00, 45120,
     "Four tires rotated front-to-rear. Rear tires showing slightly faster wear from load. "
     "Recommend replacement at 50K miles on rear axle.",
     "2026-10-25"),

    # ── Freezer Trailer #3 ───────────────────────────────────────────────────
    (v2, "2026-01-08", "Refrigeration Calibration",
     "Alpine Refrigeration Solutions", "Sam Trujillo", 485.00, None,
     "Annual deep-freeze unit calibration. -20°C set point verified within 0.5°C. "
     "Defrost cycle timing adjusted -- was running too frequent, causing mild temp spikes. "
     "HACCP temperature log controller reset and tested. Certified for USDA cold storage transport.",
     "2026-07-08"),

    (v2, "2026-02-14", "Compressor Inspection",
     "Alpine Refrigeration Solutions", "Sam Trujillo", 650.00, None,
     "Full compressor teardown inspection. Scroll compressor bearings sound -- no wear. "
     "Replaced high-pressure cutout switch (was sticking intermittently at -18°C). "
     "New switch rated to -30°C. System back to full operation. Refrigerant topped off.",
     "2027-02-14"),

    (v2, "2026-03-30", "Annual Safety Inspection",
     "Larimer County Fleet Services", "Ray Montoya", 220.00, None,
     "Trailer brake system inspected and certified. Landing gear lubricated. "
     "DOT reflective tape refreshed. Rear door hinges greased. Passed all checks.",
     "2027-03-30"),

    (v2, "2026-04-20", "Door Seal Replacement",
     "Alpine Refrigeration Solutions", "Sam Trujillo", 390.00, None,
     "Rear door full gasket replacement -- original seals at end of service life after 4 years. "
     "New 3-layer foam/rubber composite gaskets installed. Pressure test confirms zero air infiltration at -20°C. "
     "Critical for FSMA compliance on frozen product transport.",
     "2028-04-20"),
]

added_maint = 0
for (vid, sdate, stype, provider, tech, cost, odo, notes, next_date) in MAINTENANCE:
    exists = first(
        "SELECT MaintenanceID FROM ColdChainMaintenance "
        "WHERE VehicleID=:v AND ServiceDate=:d AND ServiceType=:t",
        {"v": vid, "d": sdate, "t": stype}
    )
    if exists:
        print(f"  Skip: {sdate} {stype}")
        continue
    q("""
        INSERT INTO ColdChainMaintenance
            (VehicleID, BusinessID, ServiceDate, ServiceType, ServiceProvider,
             Technician, Cost, OdometerMiles, Notes, NextServiceDate)
        VALUES (:v, :b, :d, :t, :prov, :tech, :cost, :odo, :notes, :next)
    """, {
        "v": vid, "b": BID, "d": sdate, "t": stype,
        "prov": provider, "tech": tech, "cost": cost, "odo": odo,
        "notes": notes, "next": next_date,
    })
    db.commit()
    added_maint += 1
    print(f"  Added: {sdate}  {stype}  ({provider})")

print(f"Maintenance records added: {added_maint}")
print("\nDone.")
