"""
seed_demo_15671d.py — Farmer Settlement + Cold Chain demo data for BusinessID=15671
Idempotent: skips rows that already exist.
Run: python seed_demo_15671d.py
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

def section(name):
    print(f"\n=== {name} ===")


# ─────────────────────────────────────────────
# 1. FARMER SETTLEMENT
# ─────────────────────────────────────────────
section("Farmer Settlement")

settlements = [
    # (FarmerName, Phone, UPI, CommissionPct, LogisticsCost, OtherDeductions, Status, PaidAt, PaymentRef, Notes, items)
    (
        "Maria Santos", "970-555-0142", "mariasantos@upi",
        8.0, 45.00, 0.00, "paid",
        "2026-04-05", "PAY-2026-0401",
        "April produce run — heirloom tomatoes and peppers",
        [
            ("Heirloom Tomatoes",  320, "lb",  2.80),
            ("Bell Peppers",       180, "lb",  2.50),
            ("Cherry Tomatoes",     60, "pint", 3.50),
        ]
    ),
    (
        "James Whitfield", "303-555-0287", "jwhitfield@upi",
        7.5, 62.00, 15.00, "paid",
        "2026-04-12", "PAY-2026-0408",
        "Spring greens + root veg — weekly CSA contribution",
        [
            ("Butterhead Lettuce", 140, "head", 1.90),
            ("Rainbow Carrots",    200, "lb",   2.20),
            ("Radishes",            80, "bunch", 1.40),
            ("Spinach",            120, "lb",   3.00),
        ]
    ),
    (
        "Priya Nair", "720-555-0391", "priyanair@upi",
        9.0, 38.00, 0.00, "paid",
        "2026-04-20", "PAY-2026-0415",
        "Herb bundles and microgreens — restaurant accounts",
        [
            ("Basil Bunches",      200, "bunch", 1.40),
            ("Cilantro Bunches",   160, "bunch", 1.25),
            ("Sunflower Microgreens", 40, "flat", 12.00),
            ("Pea Shoot Microgreens", 30, "flat", 14.00),
        ]
    ),
    (
        "Garrett Olson", "970-555-0554", "garrett.olson@upi",
        6.0, 120.00, 25.00, "paid",
        "2026-05-01", "PAY-2026-0428",
        "Livestock settlement — Alpaca fiber clip sale",
        [
            ("Raw Alpaca Fleece — Huacaya", 85, "lb",  18.50),
            ("Raw Alpaca Fleece — Suri",    32, "lb",  24.00),
            ("Processed Roving",            18, "lb",  42.00),
        ]
    ),
    (
        "Elena Kowalski", "303-555-0619", "ekowalski@upi",
        8.5, 55.00, 0.00, "pending",
        None, None,
        "May produce — pending payment after market weekend",
        [
            ("Zucchini",           250, "lb",  1.60),
            ("Yellow Squash",      180, "lb",  1.70),
            ("Cucumber",           150, "lb",  1.80),
            ("Sweet Corn",          96, "ear", 0.45),
        ]
    ),
    (
        "Tomás Rivera", "720-555-0773", "tomas.rivera@upi",
        7.0, 85.00, 10.00, "pending",
        None, None,
        "May CSA supplement — berries and stone fruit",
        [
            ("Strawberries",       120, "lb",  4.50),
            ("Blueberries",         60, "pint", 5.00),
            ("Peaches",            200, "lb",  2.75),
        ]
    ),
]

for (fname, phone, upi, comm_pct, logistics, other_ded, status,
     paid_at, pay_ref, notes, items) in settlements:

    exists = first(
        "SELECT SettlementID FROM FarmerSettlement WHERE BusinessID=:b AND FarmerName=:fn",
        {"b": BID, "fn": fname}
    )
    if exists:
        print(f"  Settlement for {fname} already exists")
        continue

    # Calculate gross from items
    gross = sum(qty * price for (_, qty, _, price) in items)
    commission = round(gross * comm_pct / 100, 2)
    net = round(gross - commission - logistics - other_ded, 2)

    sid = first(
        "INSERT INTO FarmerSettlement "
        "(BusinessID, FarmerName, FarmerPhone, FarmerUPI, CommissionPct, "
        "LogisticsCost, OtherDeductions, GrossSales, Status, Notes, PaidAt, PaymentRef) "
        "OUTPUT INSERTED.SettlementID "
        "VALUES (:b, :fn, :ph, :upi, :cp, :lc, :od, :gs, :st, :notes, :pa, :pr)",
        {
            "b": BID, "fn": fname, "ph": phone, "upi": upi,
            "cp": comm_pct, "lc": logistics, "od": other_ded,
            "gs": gross, "st": status,
            "notes": notes,
            "pa": paid_at, "pr": pay_ref,
        }
    )

    for (item_name, qty, unit, unit_price) in items:
        q(
            "INSERT INTO SettlementItem (SettlementID, ItemName, Qty, Unit, UnitPrice) "
            "VALUES (:sid, :nm, :qty, :unit, :up)",
            {"sid": sid, "nm": item_name, "qty": qty, "unit": unit, "up": unit_price}
        )

    print(f"  Created settlement: {fname} - gross ${gross:,.2f}, net ${net:,.2f} ({status})")

db.commit()


# ─────────────────────────────────────────────
# 2. COLD CHAIN — VEHICLES
# ─────────────────────────────────────────────
section("Cold Chain — Vehicles")

vehicles = [
    ("Refrigerated Box Truck #1",  "CO-8821-RT", "Diego Mendez",    "970-555-0101", -2.0,  4.0),
    ("Insulated Cargo Van #2",     "CO-4473-CV", "Aisha Thompson",  "303-555-0202",  0.0,  6.0),
    ("Freezer Trailer Unit #3",    "CO-6650-FT", "Kevin Park",      "720-555-0303", -20.0, -15.0),
]

vehicle_ids = []
for (vname, plate, driver, phone, min_t, max_t) in vehicles:
    vid = first(
        "SELECT VehicleID FROM ColdChainVehicle WHERE BusinessID=:b AND LicensePlate=:lp",
        {"b": BID, "lp": plate}
    )
    if not vid:
        vid = first(
            "INSERT INTO ColdChainVehicle "
            "(BusinessID, VehicleName, LicensePlate, DriverName, DriverPhone, MinTempC, MaxTempC, IsActive) "
            "OUTPUT INSERTED.VehicleID "
            "VALUES (:b, :vn, :lp, :dn, :dp, :mn, :mx, 1)",
            {"b": BID, "vn": vname, "lp": plate, "dn": driver, "dp": phone,
             "mn": min_t, "mx": max_t}
        )
        print(f"  Created vehicle: {vname} (ID={vid})")
    else:
        print(f"  Vehicle exists: {vname} (ID={vid})")
    vehicle_ids.append((vid, vname, driver, min_t, max_t))

db.commit()


# ─────────────────────────────────────────────
# 3. COLD CHAIN — TEMPERATURE READINGS
# ─────────────────────────────────────────────
section("Cold Chain — Temperature Readings")

# Readings per vehicle: simulate a multi-stop delivery run
# Each row: (VehicleID index, recorded_at offset hours from base, tempC, humidity, location, notes)
base = datetime.datetime(2026, 5, 1, 6, 0, 0)

reading_sets = [
    # Vehicle 0 (Box Truck, fresh produce, target -2..4°C)
    [
        (0,  0.0,  3.2, 88, "Food World — Loading Dock",        "Pre-load check"),
        (0,  0.5,  3.5, 86, "I-25 North — Mile 218",            "En route"),
        (0,  1.0,  3.8, 85, "US-34 Exit — Loveland",            "En route"),
        (0,  1.5,  4.1, 84, "Restaurant Row — Fort Collins",     "Door open — unloading stop 1"),
        (0,  2.0,  3.6, 87, "Harmony Rd — Fort Collins",        "En route to stop 2"),
        (0,  2.5,  3.3, 88, "Whole Foods — Fort Collins",       "Unloading stop 2"),
        (0,  3.0,  3.1, 89, "I-25 South — Return",              "Return leg"),
        (0,  3.8,  2.9, 90, "Food World — Loading Dock",        "Return — end of run"),
    ],
    # Vehicle 1 (Cargo Van, farmers market, target 0..6°C)
    [
        (1,  0.0,  5.1, 82, "Food World — Loading Dock",        "Market run load-out"),
        (1,  0.5,  5.4, 80, "US-287 South — Longmont",         "En route"),
        (1,  1.2,  5.8, 79, "Boulder Farmers Market",           "Setup — van open 30 min"),
        (1,  2.5,  6.4, 77, "Boulder Farmers Market",           "ALERT: door left ajar"),
        (1,  3.0,  5.9, 78, "Boulder Farmers Market",           "Corrected — door secured"),
        (1,  5.0,  5.2, 81, "Boulder Farmers Market",           "End of market — breakdown"),
        (1,  5.5,  5.0, 83, "US-36 East — Return",              "Return leg"),
        (1,  6.2,  4.8, 84, "Food World — Loading Dock",        "Return — unloaded"),
    ],
    # Vehicle 2 (Freezer Trailer, frozen meat + alpaca fiber, target -20..-15°C)
    [
        (2,  0.0, -18.2, 55, "Food World — Cold Storage",       "Pre-trip inspection"),
        (2,  1.0, -18.5, 54, "I-70 West — Genesee",            "En route Denver"),
        (2,  2.0, -17.9, 56, "Denver Cold Storage Hub",         "Transfer stop"),
        (2,  2.5, -18.1, 55, "Denver Cold Storage Hub",         "Loaded outbound"),
        (2,  3.5, -17.5, 57, "I-76 East — Commerce City",      "En route"),
        (2,  4.5, -16.8, 59, "Greeley Distribution Center",    "Delivery — rear door open"),
        (2,  5.0, -17.2, 58, "Greeley Distribution Center",    "Unload complete — door sealed"),
        (2,  6.0, -18.0, 55, "I-76 West — Return",             "Return leg"),
        (2,  7.0, -18.3, 54, "Food World — Cold Storage",      "Return — connected to dock"),
    ],
]

for reading_list in reading_sets:
    for (v_idx, hour_offset, temp, humidity, location, notes) in reading_list:
        vid = vehicle_ids[v_idx][0]
        recorded_at = base + datetime.timedelta(hours=hour_offset)
        exists = first(
            "SELECT ReadingID FROM ColdChainReading WHERE VehicleID=:v AND RecordedAt=:ra",
            {"v": vid, "ra": recorded_at}
        )
        if not exists:
            q(
                "INSERT INTO ColdChainReading (VehicleID, TempC, Humidity, LocationDesc, RecordedAt, Notes) "
                "VALUES (:v, :t, :h, :loc, :ra, :notes)",
                {"v": vid, "t": temp, "h": humidity, "loc": location, "ra": recorded_at, "notes": notes}
            )
    vname = vehicle_ids[reading_list[0][0]][1]
    print(f"  Added {len(reading_list)} readings for {vname}")

db.commit()


# ─────────────────────────────────────────────
# 4. OFN AGGREGATOR LOGISTICS DISPATCHES
# ─────────────────────────────────────────────
section("OFN Aggregator Logistics Dispatches")

dispatches = [
    # (OrderType, VehicleID-str, DriverName, DriverPhone, PickupTime, DeliveryTime,
    #  TempC, Breach, RouteNotes, Status)
    ("outbound",  "CO-8821-RT", "Diego Mendez",   "970-555-0101",
     "2026-05-01 06:00", "2026-05-01 09:45",
     3.6, False,
     "Produce delivery — 3 restaurant stops Fort Collins. All temps nominal.",
     "delivered"),
    ("outbound",  "CO-4473-CV", "Aisha Thompson", "303-555-0202",
     "2026-05-01 06:00", "2026-05-01 12:15",
     5.8, True,
     "Boulder Farmers Market run. Brief temp breach 6.4°C at 08:30 — door left ajar, corrected.",
     "delivered"),
    ("outbound",  "CO-6650-FT", "Kevin Park",     "720-555-0303",
     "2026-05-01 06:00", "2026-05-01 13:00",
     -17.5, False,
     "Frozen product transfer to Denver hub + Greeley distribution. All temps within range.",
     "delivered"),
    ("inbound",   "CO-4473-CV", "Aisha Thompson", "303-555-0202",
     "2026-05-05 07:00", "2026-05-05 10:30",
     4.9, False,
     "Inbound — pick up from Maria Santos farm (Berthoud) + James Whitfield (Johnstown).",
     "delivered"),
    ("outbound",  "CO-8821-RT", "Diego Mendez",   "970-555-0101",
     "2026-05-08 06:30", "2026-05-08 11:00",
     3.4, False,
     "Weekly restaurant route — Harvest Table, Ember Grill, Roots Kitchen.",
     "delivered"),
    ("outbound",  "CO-4473-CV", "Aisha Thompson", "303-555-0202",
     "2026-05-10 07:00", None,
     None, False,
     "CSA box delivery day — Longmont, Boulder, Lafayette drop points.",
     "in_transit"),
    ("inbound",   "CO-8821-RT", "Diego Mendez",   "970-555-0101",
     "2026-05-12 08:00", None,
     None, False,
     "Scheduled inbound pick-up — Priya Nair herbs + Tomás Rivera berries.",
     "scheduled"),
]

for (order_type, vehicle_str, driver, phone,
     pickup_str, delivery_str, temp_c, breach, route_notes, status) in dispatches:

    pickup_dt = datetime.datetime.strptime(pickup_str, "%Y-%m-%d %H:%M")
    delivery_dt = datetime.datetime.strptime(delivery_str, "%Y-%m-%d %H:%M") if delivery_str else None

    exists = first(
        "SELECT DispatchID FROM OFNAggregatorLogistics "
        "WHERE BusinessID=:b AND VehicleID=:v AND PickupTime=:pt",
        {"b": BID, "v": vehicle_str, "pt": pickup_dt}
    )
    if exists:
        print(f"  Dispatch {vehicle_str} @ {pickup_str} already exists")
        continue

    q(
        "INSERT INTO OFNAggregatorLogistics "
        "(BusinessID, OrderType, VehicleID, DriverName, DriverPhone, PickupTime, DeliveryTime, "
        "ColdChainTempC, ColdChainBreach, RouteNotes, Status, CreatedDate) "
        "VALUES (:b, :ot, :v, :dn, :dp, :pt, :dt, :tc, :breach, :rn, :st, GETDATE())",
        {
            "b": BID, "ot": order_type, "v": vehicle_str,
            "dn": driver, "dp": phone,
            "pt": pickup_dt, "dt": delivery_dt,
            "tc": temp_c, "breach": 1 if breach else 0,
            "rn": route_notes, "st": status,
        }
    )
    print(f"  Created dispatch: {order_type} {vehicle_str} {pickup_str} - {status}")

db.commit()
print("\n=== seed_demo_15671d.py COMPLETE ===")
