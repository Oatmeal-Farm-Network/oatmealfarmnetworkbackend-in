import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db
from sqlalchemy import text
db = next(get_db())

def q(sql, p=None):
    return db.execute(text(sql), p or {}).fetchall()

def scalar(sql, p=None):
    return db.execute(text(sql), p or {}).scalar()

print("=== Table existence & row counts ===")
for tbl in ["ColdChainShockEvent","ColdChainCustodyEvent","ColdChainGeofenceZone","ColdChainGeofenceEvent","ColdChainShelfLife"]:
    exists = scalar("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME=:t", {"t": tbl})
    count = scalar(f"SELECT COUNT(*) FROM {tbl}") if exists else "N/A"
    print(f"  {tbl}: exists={bool(exists)}  rows={count}")

print()
print("=== New columns on ColdChainReading ===")
for col in ["EthyleneGasPPM","CO2PPM","LightLux","DoorOpenFlag","GpsLat","GpsLon","ShockGForce"]:
    exists = scalar("SELECT COUNT(*) FROM sys.columns WHERE object_id=OBJECT_ID('ColdChainReading') AND name=:c", {"c": col})
    print(f"  {col}: {'EXISTS' if exists else 'MISSING'}")

print()
print("=== New columns on ColdChainVehicle ===")
for col in ["ReeferFuelPct","BatteryPct","LastPingAt","PowerAlertSent"]:
    exists = scalar("SELECT COUNT(*) FROM sys.columns WHERE object_id=OBJECT_ID('ColdChainVehicle') AND name=:c", {"c": col})
    print(f"  {col}: {'EXISTS' if exists else 'MISSING'}")

print()
print("=== Sample records ===")
rows = q("SELECT TOP 3 VehicleID, VehicleName, ReeferFuelPct, BatteryPct FROM ColdChainVehicle WHERE BusinessID=15671")
for r in rows:
    print(f"  Vehicle {r[0]} ({r[1]}): fuel={r[2]}%  battery={r[3]}%")

rows = q("SELECT TOP 3 VehicleID, PeakGForce, Axis, LocationDesc FROM ColdChainShockEvent")
print(f"  Shocks: {[(r[0],r[1],r[2],r[3]) for r in rows]}")

rows = q("SELECT TOP 3 VehicleID, HandoverType, FromParty, ToParty FROM ColdChainCustodyEvent")
print(f"  Custody: {[(r[0],r[1],r[2][:20],r[3][:20]) for r in rows]}")

rows = q("SELECT TOP 3 ZoneName, ZoneType FROM ColdChainGeofenceZone WHERE BusinessID=15671")
print(f"  Zones: {[(r[0],r[1]) for r in rows]}")

rows = q("SELECT TOP 3 ProductName, AdjustedShelfLifeDays, DegradationPct FROM ColdChainShelfLife WHERE BusinessID=15671")
print(f"  ShelfLife: {[(r[0],r[1],r[2]) for r in rows]}")
