"""
Seed script — livestock + herd health data for BusinessID=15665
Run from the Backend/oatmealfarmnetworkbackend directory:
    ..\venv\Scripts\python.exe seed_livestock_15665.py
"""
import os
import sys
from dotenv import load_dotenv
import pymssql

load_dotenv()

conn = pymssql.connect(
    server=os.getenv("DB_SERVER"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME"),
    timeout=30,
    login_timeout=15,
)
cur = conn.cursor(as_dict=True)

BID = 15665

# ── helper ────────────────────────────────────────────────────────────────────
def exec(sql, params=None):
    cur.execute(sql, params or {})

def fetchone(sql, params=None):
    cur.execute(sql, params or {})
    return cur.fetchone()

def scalar(sql, params=None):
    row = fetchone(sql, params)
    if row:
        return list(row.values())[0]
    return None

# ── look up PeopleID for the business ─────────────────────────────────────────
people_row = fetchone(
    "SELECT TOP 1 PeopleID FROM BusinessAccess WHERE BusinessID=%d AND Active=1", (BID,)
)
if not people_row:
    print("ERROR: No active BusinessAccess row found for BusinessID", BID)
    sys.exit(1)
PID = people_row["PeopleID"]
print(f"Using PeopleID={PID} for BusinessID={BID}")

# ── animals ───────────────────────────────────────────────────────────────────
# SpeciesID: Cattle=8, Sheep=10, Goats=6
# We insert with FullName as the identifier; herd health records reference same name as AnimalTag

ANIMALS = [
    # (FullName, SpeciesID, dob_year, dob_month, dob_day, weight_lbs, description)
    ("Midnight",   8, 2022, 3, 15, 1650, "Black Angus bull, registered. Excellent conformation."),
    ("Lady Belle", 8, 2020, 5, 10, 1180, "Black Angus cow. Dam of Ranger and Biscuit."),
    ("Rosie",      8, 2019, 7, 22, 1150, "Hereford cow. Excellent milk production."),
    ("Clover",     8, 2024, 2,  8,  820, "Angus-Hereford crossbred heifer. First calf expected 2026."),
    ("Ranger",     8, 2023, 4,  1,  950, "Black Angus steer, finishing pasture."),
    ("Biscuit",    8, 2026, 1, 15,  280, "Black Angus bull calf, born Jan 2026."),
    ("Big D",     10, 2021, 9,  5,  210, "Dorper ram, registered. High libido, good wool."),
    ("Woolly",    10, 2021,11, 20,  145, "Dorper ewe. Good mother. Twins last spring."),
    ("Patches",   10, 2022, 3, 18,  138, "Dorper ewe. White with brown spots."),
    ("Daisy",     10, 2020, 8, 12,  160, "Suffolk ewe. Champion at county fair 2023."),
    ("June",      10, 2026, 2, 25,   55, "Suffolk ewe lamb, born Feb 2026. Dam: Daisy."),
    ("Billy",      6, 2022, 6, 10,  185, "Boer buck, registered."),
    ("Nanny",      6, 2022, 8, 30,  120, "Boer doe. Excellent milker."),
    ("Long Ears",  6, 2021,12, 14,  130, "Nubian doe. High butterfat milk."),
    ("Junior",     6, 2025,11,  1,   65, "Nubian doeling, born Nov 2025. Dam: Long Ears."),
]

animal_ids = {}  # name -> AnimalID
for (name, sid, yr, mo, dy, wt, desc) in ANIMALS:
    existing = fetchone(
        "SELECT AnimalID FROM Animals WHERE BusinessID=%d AND FullName=%s",
        (BID, name)
    )
    if existing:
        animal_ids[name] = existing["AnimalID"]
        print(f"  Animal '{name}' already exists (ID={animal_ids[name]})")
        continue
    exec(
        """INSERT INTO Animals (BusinessID, PeopleID, FullName, SpeciesID,
                DOBYear, DOBMonth, DOBDay, Weight, Description, PublishForSale, NumberofAnimals)
           VALUES (%d, %d, %s, %d, %d, %d, %d, %s, %s, 0, 1)""",
        (BID, PID, name, sid, yr, mo, dy, float(wt), desc)
    )
    conn.commit()
    aid_row = fetchone("SELECT SCOPE_IDENTITY() AS id")
    aid = int(aid_row["id"])
    # Insert default Pricing row
    exec("INSERT INTO Pricing (AnimalID, Sold, Free) VALUES (%d, 0, 0)", (aid,))
    conn.commit()
    animal_ids[name] = aid
    print(f"  Created animal '{name}' -> AnimalID={aid}")

# ── helper to get AnimalID ────────────────────────────────────────────────────
def aid(name):
    return animal_ids.get(name)

# ── health events ─────────────────────────────────────────────────────────────
print("\nSeeding health events...")
EVENTS = [
    ("Rosie",     "2026-04-22", "Illness",      "High",   "Respiratory symptoms",   "Coughing, labored breathing, elevated temp 104.2°F",  "Penicillin 10cc IM, isolate 48hrs", "2026-04-26", "Responded well to treatment", "J. Smith"),
    ("Woolly",    "2026-04-15", "Injury",        "Medium", "Foot rot",               "Lameness left front hoof, foul odor, swollen interdigital",  "Hoof trim, foot bath ZnSO4, oxytetracycline 5cc IM", "2026-04-20", "Healed, walking normally", "J. Smith"),
    ("Biscuit",   "2026-04-10", "Illness",      "High",   "Scours in calf",         "Profuse yellow-gray diarrhea, mild dehydration, born 75 days ago", "Electrolytes oral x3d, Probios, monitor hydration", None, None, "J. Smith"),
    ("Long Ears", "2026-04-28", "Observation",  "Low",    "Slightly off feed",      "Noticed eating less hay than normal, otherwise normal vitals", "Monitoring, offered fresh hay and water", None, None, "J. Smith"),
    ("Clover",    "2026-03-30", "Reproductive", "Medium", "Pregnancy check",        "Rectal palpation confirms pregnancy, approx 5 months along", "Next check scheduled mid-May", None, None, "Dr. Rodriguez"),
    ("Patches",   "2026-04-05", "Illness",      "Low",    "Pink eye",               "Watery discharge right eye, corneal cloudiness beginning", "Oxytetracycline ophthalmic ointment 2x daily x5d", "2026-04-12", "Cleared, eye normal", "J. Smith"),
    ("Billy",     "2026-02-14", "Injury",       "Medium", "Laceration on left flank","3-inch laceration from fence wire, moderate bleeding",    "Cleaned, sutured 4 stitches, antibiotics 5d", "2026-02-21", "Healed without infection", "Dr. Rodriguez"),
    ("Lady Belle","2026-01-20", "Illness",      "Critical","Milk fever (hypocalcemia)","Down cow, unable to stand, cold extremities, calved 2d ago", "IV calcium borogluconate 500mL slow drip, oral Cal-Mag bolus", "2026-01-21", "Up and nursing within 12hrs", "Dr. Rodriguez"),
]

for (tag, dt, etype, sev, title, desc, tx, res_dt, res_note, by) in EVENTS:
    existing = fetchone(
        "SELECT EventID FROM HerdHealthEvent WHERE BusinessID=%d AND AnimalTag=%s AND EventDate=%s AND Title=%s",
        (BID, tag, dt, title)
    )
    if existing:
        print(f"  Event '{title}' for {tag} already exists")
        continue
    exec("""INSERT INTO HerdHealthEvent
            (BusinessID,AnimalID,AnimalTag,EventDate,EventType,Severity,Title,Description,Treatment,ResolvedDate,ResolvedNotes,RecordedBy)
            VALUES (%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
         (BID, aid(tag), tag, dt, etype, sev, title, desc, tx, res_dt, res_note, by))
    conn.commit()
print("  Done")

# ── vaccinations ──────────────────────────────────────────────────────────────
print("\nSeeding vaccinations...")
VACCINES = [
    # (tag, group, vaccine, mfr, type, admin_date, next_due, dose, route, lot, by, notes)
    ("Midnight",   None, "IBR/BVD/PI3/BRSV (Bovi-Shield Gold)",  "Zoetis",   "MLV",    "2025-10-15", "2026-10-15", "2mL", "SQ",  "ZT2024A", "J. Smith", "Annual booster"),
    ("Lady Belle", None, "IBR/BVD/PI3/BRSV (Bovi-Shield Gold)",  "Zoetis",   "MLV",    "2025-10-15", "2026-10-15", "2mL", "SQ",  "ZT2024A", "J. Smith", "Annual booster"),
    ("Rosie",      None, "IBR/BVD/PI3/BRSV (Bovi-Shield Gold)",  "Zoetis",   "MLV",    "2025-10-15", "2026-10-15", "2mL", "SQ",  "ZT2024A", "J. Smith", "Annual booster"),
    ("Clover",     None, "Clostridial 8-way (Covexin 8)",         "Merck",    "Killed", "2025-09-20", "2026-09-20", "5mL", "SQ",  "MK4421",  "J. Smith", None),
    ("Ranger",     None, "Clostridial 8-way (Covexin 8)",         "Merck",    "Killed", "2025-09-20", "2026-09-20", "5mL", "SQ",  "MK4421",  "J. Smith", None),
    ("Biscuit",    None, "Clostridial 8-way (Covexin 8)",         "Merck",    "Killed", "2026-02-15", "2026-08-15", "2mL", "SQ",  "MK4421",  "J. Smith", "Initial series, booster due"),
    ("Big D",      None, "CDT Toxoid (Bar-Vac CDT)",              "Boehringer","Toxoid", "2025-11-10", "2026-11-10", "2mL", "SQ",  "BH1122",  "J. Smith", "Annual CDT"),
    ("Woolly",     None, "CDT Toxoid (Bar-Vac CDT)",              "Boehringer","Toxoid", "2025-11-10", "2026-11-10", "2mL", "SQ",  "BH1122",  "J. Smith", None),
    ("Patches",    None, "CDT Toxoid (Bar-Vac CDT)",              "Boehringer","Toxoid", "2025-11-10", "2026-11-10", "2mL", "SQ",  "BH1122",  "J. Smith", None),
    ("Daisy",      None, "CDT Toxoid (Bar-Vac CDT)",              "Boehringer","Toxoid", "2025-11-10", "2026-11-10", "2mL", "SQ",  "BH1122",  "J. Smith", None),
    ("June",       None, "CDT Toxoid (Bar-Vac CDT)",              "Boehringer","Toxoid", "2026-03-25", "2026-04-25", "1mL", "SQ",  "BH1122",  "J. Smith", "Initial, booster OVERDUE"),
    ("Billy",      None, "CDT Toxoid (Bar-Vac CDT)",              "Boehringer","Toxoid", "2025-11-10", "2026-11-10", "2mL", "SQ",  "BH1122",  "J. Smith", None),
    ("Nanny",      None, "CDT Toxoid (Bar-Vac CDT)",              "Boehringer","Toxoid", "2025-11-10", "2026-11-10", "2mL", "SQ",  "BH1122",  "J. Smith", None),
    ("Long Ears",  None, "CDT Toxoid (Bar-Vac CDT)",              "Boehringer","Toxoid", "2025-11-10", "2026-11-10", "2mL", "SQ",  "BH1122",  "J. Smith", None),
    (None, "All Cattle", "Brucellosis (Bangs) - Calfhood",        "USDA",     "MLV",    "2025-08-01", "2026-08-01", "2mL", "SQ",  "USDA25",  "Dr. Rodriguez", "State required"),
    (None, "Sheep & Goats", "Overeating/Tetanus (CD&T)",          "Boehringer","Toxoid", "2025-11-10", "2026-05-10", "2mL", "SQ",  "BH1122",  "J. Smith", "Spring booster DUE SOON"),
]

for (tag, grp, vname, mfr, vtype, adm, due, dose, route, lot, by, notes) in VACCINES:
    existing = fetchone(
        "SELECT VaccinationID FROM HerdHealthVaccination WHERE BusinessID=%d AND AnimalTag=%s AND VaccineName=%s AND AdministeredDate=%s",
        (BID, tag, vname, adm)
    )
    if existing:
        continue
    exec("""INSERT INTO HerdHealthVaccination
            (BusinessID,AnimalID,AnimalTag,GroupName,VaccineName,VaccineManufacturer,VaccineType,
             AdministeredDate,NextDueDate,Dosage,Route,LotNumber,AdministeredBy,Notes)
            VALUES (%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
         (BID, aid(tag) if tag else None, tag, grp, vname, mfr, vtype, adm, due, dose, route, lot, by, notes))
    conn.commit()
print("  Done")

# ── treatments ────────────────────────────────────────────────────────────────
print("\nSeeding treatments...")
TREATMENTS = [
    ("Rosie",     "2026-04-22", "Bovine Respiratory Disease",   "Penicillin G Procaine", "Penicillin", "6mL SQ",       "SQ",  "Once daily", 5, "2026-05-02", None, "Dr. Rodriguez", "J. Smith", 28.50,  "Recovered",  "Per vet guidance after exam"),
    ("Woolly",    "2026-04-15", "Foot Rot",                     "Oxytetracycline",        "Tetracycline","5mL IM",      "IM",  "Once daily", 3, "2026-04-25", None, "J. Smith",      "J. Smith", 12.00,  "Recovered",  "Combined with hoof trimming"),
    ("Biscuit",   "2026-04-10", "Neonatal Scours",              "Oral Electrolytes",      "Electrolytes","500mL oral",  "Oral","3x daily",   3, None,         None, None,            "J. Smith", 8.00,   None,         "Ongoing monitoring; no withdrawal for electrolytes"),
    ("Lady Belle","2026-01-20", "Hypocalcemia",                 "Calcium Borogluconate",  "Calcium",    "500mL IV",     "IV",  "Single dose",1, None,         None, "Dr. Rodriguez", "Dr. Rodriguez", 85.00, "Recovered", "Emergency treatment, down cow"),
    ("Patches",   "2026-04-05", "Infectious Keratoconjunctivitis","Oxytetracycline Eye Ointment","Tetracycline","0.5g topical","Topical","2x daily",5, None,  None, None,            "J. Smith", 6.50,   "Recovered",  None),
    ("Long Ears", "2026-01-05", "Internal Parasites - Haemonchus","Ivermectin",            "Avermectin", "1.5mL oral",  "Oral","Single dose",1, "2026-01-20", None, None,            "J. Smith", 4.00,   "Recovered",  "FAMACHA score 4, treated per protocol"),
    ("Billy",     "2026-02-14", "Laceration",                   "Penicillin G Procaine",  "Penicillin", "4mL SQ",       "SQ",  "Once daily", 5, "2026-02-24", None, "Dr. Rodriguez", "Dr. Rodriguez", 22.00, "Recovered", "Post-wound closure antibiotic course"),
]

for (tag, dt, diag, med, ai, dose, route, freq, dur, wd, wm, prx, by, cost, outcome, notes) in TREATMENTS:
    existing = fetchone(
        "SELECT TreatmentID FROM HerdHealthTreatment WHERE BusinessID=%d AND AnimalTag=%s AND TreatmentDate=%s AND Medication=%s",
        (BID, tag, dt, med)
    )
    if existing:
        continue
    exec("""INSERT INTO HerdHealthTreatment
            (BusinessID,AnimalID,AnimalTag,TreatmentDate,Diagnosis,Medication,ActiveIngredient,
             Dosage,Route,Frequency,DurationDays,WithdrawalDate,WithdrawalMilk,
             PrescribedBy,AdministeredBy,Cost,Outcome,Notes)
            VALUES (%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
         (BID, aid(tag), tag, dt, diag, med, ai, dose, route, freq, dur, wd, wm, prx, by, cost, outcome, notes))
    conn.commit()
print("  Done")

# ── vet visits ────────────────────────────────────────────────────────────────
print("\nSeeding vet visits...")
VET_VISITS = [
    ("2026-04-22", "Dr. Maria Rodriguez", "Valley Large Animal Clinic", "Emergency",
     "Rosie (T-003)", "Respiratory distress, coughing, fever",
     "Temp 104.2°F, bilateral lung crackles on auscultation, nasal discharge",
     "Bovine Respiratory Disease (BRD)", "Chest auscultation, nasal swab",
     "Penicillin G Procaine 6mL SQ q24h x5d", "2026-04-29", "Recheck if not improved",
     145.00, "Emergency farm call for respiratory case in Rosie. Collected nasal swab for culture."),
    ("2026-03-30", "Dr. Maria Rodriguez", "Valley Large Animal Clinic", "Routine",
     "Clover (T-004)", "Annual pregnancy check and health assessment",
     "BCS 5.5, approx 5 months pregnant, good body condition",
     "Confirmed pregnancy", "Rectal palpation, BCS assessment",
     "None prescribed", "2026-06-01", "Recheck near due date",
     85.00, "Routine annual visit. All cattle looked at. Updated herd health protocols."),
    ("2026-01-20", "Dr. Maria Rodriguez", "Valley Large Animal Clinic", "Emergency",
     "Lady Belle (T-002)", "Down cow, suspected milk fever",
     "Unable to stand, cold extremities, calved 48hrs prior, hypocalcemia confirmed",
     "Puerperal hypocalcemia (Milk Fever)", "Blood calcium, physical exam",
     "Calcium borogluconate 500mL IV slow drip, Cal-Mag oral bolus", "2026-01-25", "Monitor for relapse",
     185.00, "Emergency call - Lady Belle down after calving. Responded well to IV calcium within 12hrs."),
    ("2025-11-15", "Dr. James Whitfield", "Western Ranchland Veterinary", "Routine",
     "All livestock", "Annual herd health check, vaccinations, parasite assessment",
     "Overall herd in good condition. Identified foot rot risk in sheep pen.",
     "Good herd health. Minor parasite pressure.", "FAMACHA scoring, BCS, hoof inspection",
     "CDT toxoids for sheep/goats, IBR/BVD for cattle. Recommend ZnSO4 foot bath weekly.",
     None, None,
     620.00, "Annual fall herd check. 15 animals assessed. Administered all fall vaccines."),
]

for (dt, vet, clinic, vtype, animals, cc, findings, diag, proc, rx, fu_dt, fu_notes, cost, notes) in VET_VISITS:
    existing = fetchone(
        "SELECT VisitID FROM HerdHealthVetVisit WHERE BusinessID=%d AND VisitDate=%s AND VetName=%s",
        (BID, dt, vet)
    )
    if existing:
        continue
    exec("""INSERT INTO HerdHealthVetVisit
            (BusinessID,VisitDate,VetName,ClinicName,VisitType,AffectedAnimals,ChiefComplaint,
             Findings,Diagnoses,ProceduresPerformed,Prescriptions,FollowUpDate,FollowUpNotes,Cost,Notes)
            VALUES (%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
         (BID, dt, vet, clinic, vtype, animals, cc, findings, diag, proc, rx, fu_dt, fu_notes, cost, notes))
    conn.commit()
print("  Done")

# ── medications ───────────────────────────────────────────────────────────────
print("\nSeeding medications...")
MEDS = [
    # (name, ai, category, mfr, lot, exp, qty, unit, storage, w_meat, w_milk, rx, reorder, unit_cost, supplier, notes)
    ("Penicillin G Procaine 300,000 IU/mL", "Penicillin G", "Antibiotic", "Aspen Vet",    "AP2024B", "2026-12-01", 240.0, "mL",     "Refrigerate 35-46°F",  "21 days", "48 hours", 0, 50.0,  1.85, "Farm & Ranch Supply", "500mL multi-dose vial"),
    ("Oxytetracycline 200mg/mL (LA-200)",    "Oxytetracycline","Antibiotic","Zoetis",       "ZT5521",  "2026-08-01",  80.0, "mL",     "Room temp, protect light","28 days","96 hours",0, 20.0, 3.20, "Farm & Ranch Supply", "250mL bottle"),
    ("Ivermectin 1% Injectable",             "Ivermectin",   "Antiparasitic","Durvet",      "DV3312",  "2027-03-01",  50.0, "mL",     "Room temp <77°F",       "35 days", "Not for dairy",0, 10.0, 2.75, "Farm & Ranch Supply", None),
    ("Ivermectin Oral Drench (sheep/goats)", "Ivermectin",   "Antiparasitic","Durvet",      "DV3890",  "2026-10-01", 120.0, "mL",     "Room temp",             "11 days", "Not labeled", 0, 30.0,  1.40, "Farm & Ranch Supply", "Use weight-based dosing"),
    ("Calcium Borogluconate 23%",            "Calcium",      "Supplement",   "Vedco",       "VD0124",  "2026-06-01",   6.0, "bottles","Room temp",             "None",    "None",        0, 2.0,  18.50,"Valley Large Animal Clinic","500mL bottles for IV use"),
    ("CDT Toxoid (Covexin 8)",               "Clostridium/Tetanus","Vaccine","Merck",       "MK6612",  "2026-09-01",  40.0, "doses",  "Refrigerate 35-46°F",   "None",    "None",        0, 10.0,  1.20, "Farm & Ranch Supply", "8-way clostridial for sheep/goats"),
    ("Bovi-Shield Gold 5",                   "MLV BVD/IBR/PI3/BRSV","Vaccine","Zoetis",    "ZT2024A", "2026-05-01",  25.0, "doses",  "Refrigerate 35-46°F",   "None",    "None",        0, 5.0,   4.80, "Farm & Ranch Supply", "Keep refrigerated, use within 1hr of mixing"),
    ("Meloxicam 20mg/mL",                    "Meloxicam",    "NSAID",        "Norbrook",    "NB8834",  "2026-11-01",  20.0, "mL",     "Room temp",             "None",    "Not for dairy",1, 5.0,  8.20, "Valley Large Animal Clinic","Prescription — anti-inflammatory/pain"),
    ("Oral Electrolytes (ReHydration)",      "Electrolytes", "Supplement",   "Boehringer",  "BH2201",  "2027-01-01",  24.0, "packets","Room temp",             "None",    "None",        0, 6.0,   2.10, "Farm & Ranch Supply", "Calf scours/dehydration"),
    ("Oxytocin 20 IU/mL",                    "Oxytocin",     "Hormone",      "Vetone",      "VO3310",  "2026-07-01",  10.0, "mL",     "Refrigerate",           "None",    "72 hours",    1, 2.0,  12.50,"Valley Large Animal Clinic","Prescription — calving/freshening"),
]

for (name, ai, cat, mfr, lot, exp, qty, unit, stor, wm, wmilk, rx, reord, ucost, supp, notes) in MEDS:
    existing = fetchone(
        "SELECT MedicationID FROM HerdHealthMedication WHERE BusinessID=%d AND MedicationName=%s",
        (BID, name)
    )
    if existing:
        continue
    exec("""INSERT INTO HerdHealthMedication
            (BusinessID,MedicationName,ActiveIngredient,Category,Manufacturer,LotNumber,
             ExpirationDate,QuantityOnHand,Unit,StorageReq,WithdrawalMeat,WithdrawalMilk,
             Prescription,ReorderPoint,UnitCost,Supplier,Notes)
            VALUES (%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%d,%s,%s,%s,%s)""",
         (BID, name, ai, cat, mfr, lot, exp, qty, unit, stor, wm, wmilk, int(rx), reord, ucost, supp, notes))
    conn.commit()
print("  Done")

# ── weights ───────────────────────────────────────────────────────────────────
print("\nSeeding weight records...")
WEIGHTS = [
    # (tag, date, lbs, bcs, method, by)
    ("Midnight",  "2026-04-01", 1670, 6.0, "Scale",  "J. Smith"),
    ("Lady Belle","2026-04-01", 1190, 5.5, "Scale",  "J. Smith"),
    ("Rosie",     "2026-04-01", 1145, 5.0, "Scale",  "J. Smith"),
    ("Clover",    "2026-04-01",  855, 5.5, "Scale",  "J. Smith"),
    ("Ranger",    "2026-04-01",  985, 5.5, "Scale",  "J. Smith"),
    ("Biscuit",   "2026-04-01",  295, 4.5, "Scale",  "J. Smith"),
    ("Big D",     "2026-04-01",  215, 3.5, "Scale",  "J. Smith"),
    ("Woolly",    "2026-04-01",  148, 3.5, "Scale",  "J. Smith"),
    ("Patches",   "2026-04-01",  140, 4.0, "Scale",  "J. Smith"),
    ("Daisy",     "2026-04-01",  162, 4.0, "Scale",  "J. Smith"),
    ("June",      "2026-04-01",   58, 4.0, "Scale",  "J. Smith"),
    ("Billy",     "2026-04-01",  190, 4.0, "Scale",  "J. Smith"),
    ("Nanny",     "2026-04-01",  124, 4.0, "Scale",  "J. Smith"),
    ("Long Ears", "2026-04-01",  134, 4.5, "Scale",  "J. Smith"),
    ("Junior",    "2026-04-01",   70, 4.5, "Scale",  "J. Smith"),
    # earlier record for trend
    ("Midnight",  "2026-01-15", 1640, 5.5, "Scale",  "J. Smith"),
    ("Lady Belle","2026-01-15", 1175, 6.0, "Scale",  "J. Smith"),
    ("Big D",     "2026-01-15",  210, 3.0, "Scale",  "J. Smith"),
    ("Woolly",    "2026-01-15",  142, 3.0, "Scale",  "J. Smith"),
]

for (tag, dt, lbs, bcs, method, by) in WEIGHTS:
    existing = fetchone(
        "SELECT WeightID FROM HerdHealthWeight WHERE BusinessID=%d AND AnimalTag=%s AND RecordDate=%s",
        (BID, tag, dt)
    )
    if existing:
        continue
    kg = round(lbs * 0.453592, 1)
    exec("""INSERT INTO HerdHealthWeight
            (BusinessID,AnimalID,AnimalTag,RecordDate,WeightLbs,WeightKg,
             BodyConditionScore,RecordedBy,Method)
            VALUES (%d,%s,%s,%s,%s,%s,%s,%s,%s)""",
         (BID, aid(tag), tag, dt, float(lbs), kg, bcs, by, method))
    conn.commit()
print("  Done")

# ── parasites ─────────────────────────────────────────────────────────────────
print("\nSeeding parasite records...")
PARASITES = [
    # (tag, date, test_type, famacha, epg, parasite_type, treatment, dewormer, dose, next_test, by, notes)
    ("Woolly",   "2026-04-10", "FAMACHA",    2, None,  "Haemonchus contortus", None,          None,         None,         "2026-06-10", "J. Smith", "Score 2, no treatment needed"),
    ("Patches",  "2026-04-10", "FAMACHA",    3, None,  "Haemonchus contortus", None,          None,         None,         "2026-05-10", "J. Smith", "Score 3, monitor closely"),
    ("Big D",    "2026-04-10", "FAMACHA",    2, None,  "Haemonchus contortus", None,          None,         None,         "2026-06-10", "J. Smith", "Score 2, good condition"),
    ("Daisy",    "2026-04-10", "FAMACHA",    2, None,  "Haemonchus contortus", None,          None,         None,         "2026-06-10", "J. Smith", None),
    ("June",     "2026-04-10", "FAMACHA",    3, None,  "Haemonchus contortus", None,          None,         None,         "2026-05-10", "J. Smith", "Young animal, monitor"),
    ("Long Ears","2026-01-05", "FAMACHA",    4, 1200,  "Haemonchus contortus", "Treated",     "Ivermectin", "1.5mL oral", "2026-02-05", "J. Smith", "Score 4, treated with Ivermectin"),
    ("Nanny",    "2026-04-10", "FAMACHA",    2, None,  "Haemonchus contortus", None,          None,         None,         "2026-06-10", "J. Smith", None),
    ("Billy",    "2026-04-10", "FAMACHA",    2, None,  "Haemonchus contortus", None,          None,         None,         "2026-06-10", "J. Smith", None),
    ("Lady Belle","2026-03-15","Fecal Float", None, 120,"Mixed Strongyles",   None,           None,         None,         "2026-09-15", "J. Smith", "Low EPG, no treatment"),
    ("Rosie",    "2026-03-15", "Fecal Float", None, 95, "Mixed Strongyles",   None,           None,         None,         "2026-09-15", "J. Smith", None),
    ("Biscuit",  "2026-03-15", "Fecal Float", None, 0,  "Coccidia",           "Treated",     "Amprolium",  "1.25mL oral","2026-04-15", "Dr. Rodriguez","Low-level coccidiosis, treated prophylactically"),
]

for (tag, dt, ttype, fam, epg, ptype, tx_given, dewormer, dose, next_dt, by, notes) in PARASITES:
    existing = fetchone(
        "SELECT ParasiteID FROM HerdHealthParasite WHERE BusinessID=%d AND AnimalTag=%s AND TestDate=%s",
        (BID, tag, dt)
    )
    if existing:
        continue
    exec("""INSERT INTO HerdHealthParasite
            (BusinessID,AnimalID,AnimalTag,TestDate,TestType,FAMACHAScore,EggCount,
             ParasiteType,TreatmentGiven,Dewormer,DosageGiven,NextTestDate,RecordedBy,Notes)
            VALUES (%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
         (BID, aid(tag), tag, dt, ttype, fam, epg, ptype, tx_given, dewormer, dose, next_dt, by, notes))
    conn.commit()
print("  Done")

# ── quarantine ────────────────────────────────────────────────────────────────
print("\nSeeding quarantine records...")
QUARANTINE = [
    # (tag, start, planned_end, actual_end, reason, location, status, monitoring_freq, notes)
    ("Clover", "2026-04-20", "2026-05-04", None, "New Arrival - Purchase from Green Acres Farm",
     "Isolation Pen #2", "Active", "Twice daily",
     "Purchased Clover at auction. Standard 14-day quarantine per biosecurity protocol. All vitals normal."),
    ("Rosie",  "2026-04-22", "2026-04-29", "2026-04-26", "Illness - Respiratory Disease",
     "Sick Pen #1", "Released", "3x daily",
     "Quarantined during BRD treatment. Released after 5d antibiotic course and normal temp x48hrs."),
    ("Long Ears","2026-01-05","2026-01-19", "2026-01-19", "Illness - High Parasite Load",
     "Goat Isolation Area", "Released", "Once daily",
     "FAMACHA score 4, treated and monitored. Released when score improved to 2."),
]

for (tag, start, planned, actual, reason, loc, status, freq, notes) in QUARANTINE:
    existing = fetchone(
        "SELECT QuarantineID FROM HerdHealthQuarantine WHERE BusinessID=%d AND AnimalTag=%s AND StartDate=%s",
        (BID, tag, start)
    )
    if existing:
        continue
    exec("""INSERT INTO HerdHealthQuarantine
            (BusinessID,AnimalID,AnimalTag,StartDate,PlannedEndDate,ActualEndDate,
             Reason,Location,Status,MonitoringFreq,Notes)
            VALUES (%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
         (BID, aid(tag), tag, start, planned, actual, reason, loc, status, freq, notes))
    conn.commit()
print("  Done")

# ── mortality ─────────────────────────────────────────────────────────────────
print("\nSeeding mortality records...")
MORTALITY = [
    ("Daisy Jr", 10, "2026-02-12", "Hypothermia/Exposure", "Disease",
     "South pasture", "3 days old", 8.5, 0, None, None, "Composting",
     0, None, 85.0, None,
     "Ewe lamb born during unexpected ice storm. Found unresponsive despite warming attempts. Dam: Daisy."),
    ("T-007",    8,  "2025-09-08", "Bloat (Frothy)",       "Disease",
     "North pasture", "18 months", 680.0, 1, "2025-09-09",
     "Frothy bloat confirmed. Rumen contents typical. No plant toxins found.",
     "Rendering Plant", 1, "CLM-2025-0041", 820.0, "Farm & Ranch Mutual",
     "Steer found dead in pasture after heavy alfalfa grazing. Insurance claim filed and paid."),
]

for (tag, sid, dt, cause, cat, loc, age, wt, pm, pm_date, pm_findings, disposal, ins, ins_num, est_val, ins_co, notes) in MORTALITY:
    existing = fetchone(
        "SELECT MortalityID FROM HerdHealthMortality WHERE BusinessID=%d AND AnimalTag=%s AND DeathDate=%s",
        (BID, tag, dt)
    )
    if existing:
        continue
    exec("""INSERT INTO HerdHealthMortality
            (BusinessID,AnimalTag,AnimalSpecies,DeathDate,CauseOfDeath,DeathCategory,
             Location,AgeAtDeath,WeightAtDeath,PostMortemDone,PostMortemDate,PostMortemFindings,
             DisposalMethod,InsuranceClaim,InsuranceAmount,EstimatedValue,ReportedTo,Notes)
            VALUES (%d,%s,%d,%s,%s,%s,%s,%s,%s,%d,%s,%s,%s,%d,%s,%s,%s,%s)""",
         (BID, tag, sid, dt, cause, cat, loc, age, wt, int(pm), pm_date, pm_findings,
          disposal, int(ins), None, est_val, ins_co, notes))
    conn.commit()
print("  Done")

# ── lab results ───────────────────────────────────────────────────────────────
print("\nSeeding lab results...")
LAB_RESULTS = [
    # (tag, grp, sample_dt, sample_type, lab, accession, test_type, result_dt, results, ref_range, interpretation, ordered_by, notes)
    ("Rosie", None, "2026-04-22", "Nasal Swab", "State Vet Diagnostic Lab", "SVDL-26-4291",
     "Bacterial Culture & Sensitivity", "2026-04-27",
     "Mannheimia haemolytica isolated. Sensitive to penicillin, florfenicol. Resistant to tetracycline.",
     "No growth (normal)", "Abnormal — Mannheimia haemolytica confirmed. Continue penicillin treatment.",
     "Dr. Rodriguez", "Culture confirms BRD diagnosis. Penicillin remains appropriate."),
    ("Lady Belle", None, "2026-01-20", "Blood", "Valley Animal Health Lab", "VAHL-26-0189",
     "Serum Calcium", None,
     "Pending — sample submitted 1/20/26, awaiting results",
     "8.4-10.4 mg/dL", "Pending",
     "Dr. Rodriguez", "Submitted alongside emergency treatment — results may confirm hypocalcemia retroactively."),
    (None, "All Cattle", "2025-10-15", "Blood", "National Vet Labs", "NVL-25-8821",
     "Brucellosis (Bangs) - Official Test",
     "2025-10-22", "All animals negative. Herd negative status confirmed.",
     "Negative", "Normal — herd Brucellosis-free status maintained",
     "Dr. Rodriguez", "Annual state-required Brucellosis testing for interstate movement. 6 cattle tested."),
    ("Biscuit", None, "2026-03-15", "Feces", "State Vet Diagnostic Lab", "SVDL-26-1045",
     "Fecal Parasite Exam - McMaster",
     "2026-03-20",
     "Cryptosporidium parvum oocysts present (moderate). Eimeria spp. also detected (low level).",
     "<100 OPG (Eimeria)", "Abnormal — Cryptosporidium detected. Clinical signs correlate with scours.",
     "J. Smith", "Explains neonatal scours episode. Electrolyte and Amprolium treatment appropriate."),
    ("Woolly", None, "2026-04-10", "Blood", "Valley Animal Health Lab", "VAHL-26-0892",
     "Complete Blood Count (CBC)",
     "2026-04-15",
     "WBC 8.2 K/uL, RBC 9.1 M/uL, Hgb 11.4 g/dL, PCV 35%, Platelets 320 K/uL",
     "WBC 4-12, RBC 8-14, Hgb 10-16, PCV 30-45%", "Normal — no evidence of infection or anemia",
     "Dr. Rodriguez", "Annual wellness panel. All values within reference range."),
]

for (tag, grp, samp_dt, samp_type, lab, acc, test, res_dt, results, ref, interp, ordered, notes) in LAB_RESULTS:
    existing = fetchone(
        "SELECT LabResultID FROM HerdHealthLabResult WHERE BusinessID=%d AND COALESCE(AnimalTag,'')=%s AND SampleDate=%s AND TestType=%s",
        (BID, tag or '', samp_dt, test)
    )
    if existing:
        continue
    exec("""INSERT INTO HerdHealthLabResult
            (BusinessID,AnimalID,AnimalTag,GroupName,SampleDate,SampleType,LabName,AccessionNumber,
             TestType,ResultDate,Results,ReferenceRange,Interpretation,OrderedBy,Notes)
            VALUES (%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
         (BID, aid(tag) if tag else None, tag, grp, samp_dt, samp_type, lab, acc,
          test, res_dt, results, ref, interp, ordered, notes))
    conn.commit()
print("  Done")

# ── biosecurity ───────────────────────────────────────────────────────────────
print("\nSeeding biosecurity log...")
BIOSEC = [
    # (date, type, person, contact, purpose, animals, areas, clean, ppe, protocols, origin, hc, notes)
    ("2026-04-20","Animal Delivery",  "Green Acres Farm",  "(555) 234-5678", "Delivery of purchased heifer (Clover)",
     1, "Intake Area, Scale", 1, 1, "Animal inspected, health cert verified, isolation pen assigned", "Weld County, CO", 1,
     "Clover arrived with clean health certificate. Placed in 14-day quarantine per protocol."),
    ("2026-04-15","Visitor Entry",    "Dr. Maria Rodriguez","(555) 301-9900","Veterinary farm call — Woolly foot rot exam",
     1, "Sheep Barn, Treatment Area", 1, 1, "Vet entered via sanitized boots, all equipment disinfected post-visit", "Valley Large Animal Clinic", 0,
     None),
    ("2026-04-01","Facility Cleaning","Ranch Staff",       None,             "Monthly deep clean — sheep barn",
     0, "Sheep Barn", 1, 1, "Power wash walls/floors, fresh lime applied, feeder sanitized", None, 0,
     "Used 10% bleach solution on surfaces. Dried fully before restocking with animals."),
    ("2026-03-20","Feed Delivery",    "Rancher's Feed Co", "(555) 887-3210", "Delivery of 2 tons alfalfa/grass mix hay",
     0, "Hay Storage Barn", 0, 0, "Driver stayed in truck, contactless delivery. Hay inspected for mold.", "Local — within 50mi", 0,
     "Hay tested visually, no mold. Lot tag kept for records."),
    ("2026-02-28","Employee Entry",   "New Hire - Mike T.", None,             "First day, orientation",
     1, "All barns, pastures", 1, 1, "Biosecurity orientation completed, signed protocol acknowledgment", None, 0,
     "New hand oriented on footbath use, visitor log, not feeding protocols."),
    ("2025-11-15","Animal Delivery",  "Western Ranchland Veterinary","(555) 200-4411","Annual vet visit and vaccines",
     1, "All livestock areas", 1, 1, "Dr. Whitfield — annual herd health. Clean coveralls and boots provided.", None, 0,
     None),
    ("2026-04-22","Visitor Entry",    "Dr. Maria Rodriguez","(555) 301-9900","Emergency farm call — Rosie respiratory",
     1, "Cattle Barn, Sick Pen", 1, 1, "All PPE worn, equipment disinfected. Sick pen quarantine maintained.", "Valley Large Animal Clinic", 0,
     "Emergency visit. Separate entry used from healthy animals. Full disinfection after."),
]

for (dt, etype, person, contact, purpose, animals, areas, clean, ppe, protocols, origin, hc, notes) in BIOSEC:
    existing = fetchone(
        "SELECT BiosecurityID FROM HerdHealthBiosecurity WHERE BusinessID=%d AND EventDate=%s AND PersonOrCompany=%s",
        (BID, dt, person)
    )
    if existing:
        continue
    exec("""INSERT INTO HerdHealthBiosecurity
            (BusinessID,EventDate,EventType,PersonOrCompany,ContactInfo,Purpose,
             AnimalsContact,AreasAccessed,CleaningProtocol,PPEUsed,
             ProtocolsFollowed,OriginLocation,HealthCertificate,Notes)
            VALUES (%d,%s,%s,%s,%s,%s,%d,%s,%d,%d,%s,%s,%d,%s)""",
         (BID, dt, etype, person, contact, purpose, int(animals), areas,
          int(clean), int(ppe), protocols, origin, int(hc), notes))
    conn.commit()
print("  Done")

# ── vet contacts ──────────────────────────────────────────────────────────────
print("\nSeeding vet contacts...")
VET_CONTACTS = [
    ("Dr. Maria Rodriguez", "Valley Large Animal Clinic", "Large Animal Vet",
     "CO-LA-04892", "(970) 555-3001", "(970) 555-3099",
     "mrodriguez@valleylargeanimals.com", "4812 Hwy 14, Fort Collins, CO 80524",
     "Cattle, Sheep, Goats, Emergency Medicine", "Cattle, Sheep, Goats",
     1, 1, "Primary vet for this operation. 24/7 emergency line available. Accepts farm calls."),
    ("Dr. James Whitfield", "Western Ranchland Veterinary", "Mixed Practice",
     "CO-MP-01234", "(970) 555-8800", "(970) 555-8899",
     "jwhitfield@westernranchvet.com", "1200 Elm St, Greeley, CO 80631",
     "Cattle, Sheep, Goats, Horses, Routine Wellness", "All livestock",
     0, 0, "Annual herd health visits. Good availability for scheduled calls."),
    ("Dr. Lisa Patel", "Colorado State Vet Office", "State Vet / USDA",
     "USDA-CO-009912", "(970) 555-0100", None,
     "lpatel@coag.gov", "700 Kipling St, Lakewood, CO 80215",
     "Official Health Certificates, Brucellosis Testing, Interstate Movement", "All livestock",
     0, 0, "State vet for official health certificates and regulatory compliance."),
    ("Tom Hendricks", "Tri-County Farrier Services", "Farrier",
     None, "(970) 555-2201", None,
     "tomhfarrier@gmail.com", "Loveland, CO",
     "Hoof Trimming, Shoeing, Foot Rot Consultation", "Cattle, Horses, Goats",
     0, 0, "Available Tues/Thurs. 3-week trim cycle for goats, 6-week for horses."),
    ("Sarah Kim", "Front Range Livestock Nutrition", "Nutritionist",
     "CNS-CO-4421", "(970) 555-7760", None,
     "skim@frontrangenutri.com", "Windsor, CO",
     "Feed Formulation, Ration Balancing, Mineral Programs", "Cattle, Sheep, Goats",
     0, 0, "Annual nutrition consult, call ahead for spring/fall ration changes."),
]

for (name, clinic, role, lic, phone, emerg, email, addr, spec, species, pref, isemerg, notes) in VET_CONTACTS:
    existing = fetchone(
        "SELECT VetContactID FROM HerdHealthVetContact WHERE BusinessID=%d AND Name=%s",
        (BID, name)
    )
    if existing:
        continue
    exec("""INSERT INTO HerdHealthVetContact
            (BusinessID,Name,ClinicName,Role,LicenseNumber,Phone,EmergencyPhone,
             Email,Address,Specialties,Species,IsPreferred,IsEmergency,Notes)
            VALUES (%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%d,%d,%s)""",
         (BID, name, clinic, role, lic, phone, emerg, email, addr, spec, species,
          int(pref), int(isemerg), notes))
    conn.commit()
print("  Done")

# ── reproduction ──────────────────────────────────────────────────────────────
print("\nSeeding reproduction records...")
REPRO = [
    # Clover — confirmed pregnant, due mid-June
    ("Clover",     "Cattle",  "Pregnancy Check", "2026-03-30", None,
     None, None, None, None,
     "Confirmed Pregnant", "2026-03-30", "Rectal Palpation", "2026-06-10",
     None, None, None, None, None, None, None, None, "Dr. Rodriguez",
     "Approx 5 months, single calf expected. Good BCS 5.5."),
    # Clover — original breeding
    ("Clover",     "Cattle",  "Breeding",        "2025-12-10", "Natural Service",
     "Midnight", "Midnight", "Black Angus", None,
     "Confirmed Pregnant", None, None, "2026-06-10",
     None, None, None, None, None, None, None, None, "J. Smith",
     "Clover bred to Midnight 12/10/25. Heat observed AM, bred PM."),
    # Lady Belle — calving (Biscuit)
    ("Lady Belle", "Cattle",  "Birth/Parturition","2026-01-15", "Natural Service",
     None, None, None, None,
     "Open", None, None, None,
     "2026-01-15", 1, 1, 82.0, "Minor Assist", "Biscuit",
     None, None, "J. Smith",
     "Heifer pulled slightly, but no vet required. Biscuit nursing well within 2hrs."),
    # Lady Belle — rebred after calving
    ("Lady Belle", "Cattle",  "Breeding",        "2026-04-05", "Natural Service",
     "Midnight", "Midnight", "Black Angus", None,
     "Bred", None, None, "2027-01-14",
     None, None, None, None, None, None, None, None, "J. Smith",
     "Lady Belle rebred 85 days post-partum. Heat observed, confirmed mount. Next preg check May."),
    # Woolly — weaned twin lambs
    ("Woolly",     "Sheep",   "Birth/Parturition","2025-12-01", "Natural Service",
     "Big D", "Big D", "Dorper", None,
     "Open", None, None, None,
     "2025-12-01", 2, 2, 9.2, "Unassisted", "Lamb1, Lamb2",
     "2026-03-01", 48.5, "J. Smith",
     "Unassisted twin birth, both lambs nursing within 30min. Weaned at 90 days."),
    # Nanny — goat breeding
    ("Nanny",      "Goat",    "Breeding",        "2026-01-20", "Natural Service",
     "Billy", "Billy", "Boer", None,
     "Bred", None, None, "2026-06-12",
     None, None, None, None, None, None, None, None, "J. Smith",
     "Nanny in standing heat 1/20. Bred to Billy. 5-month gestation, kid(s) expected mid-June."),
    # Long Ears — Nubian kidding
    ("Long Ears",  "Goat",    "Birth/Parturition","2025-11-01", "Natural Service",
     "Billy", "Billy", "Boer x Nubian", None,
     "Open", None, None, None,
     "2025-11-01", 1, 1, 7.8, "Unassisted", "Junior",
     "2026-02-01", 38.0, "J. Smith",
     "Single doeling born. Junior weaned at 90 days. Nubian x Boer cross."),
]

for (tag, sp, etype, edt, method,
     siretag, sirename, sirebr, sirereg,
     pg_status, pg_chk_dt, pg_chk_method, due_dt,
     birth_dt, n_born, n_alive, bwt, ease, offspring,
     wean_dt, wean_wt, by, notes) in REPRO:
    existing = fetchone(
        "SELECT ReproductionID FROM HerdHealthReproduction WHERE BusinessID=%d AND AnimalTag=%s AND EventType=%s AND EventDate=%s",
        (BID, tag, etype, edt)
    )
    if existing:
        continue
    exec("""INSERT INTO HerdHealthReproduction
            (BusinessID,AnimalTag,Species,EventType,EventDate,BreedingMethod,
             SireTag,SireName,SireBreed,SireRegNumber,PregnancyStatus,
             PregnancyCheckDate,PregnancyCheckMethod,ExpectedDueDate,ActualBirthDate,
             NumberBorn,NumberBornAlive,BirthWeightLbs,BirthEase,OffspringTags,
             WeanDate,WeanWeightLbs,PerformedBy,Notes)
            VALUES (%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
         (BID, tag, sp, etype, edt, method,
          siretag, sirename, sirebr, sirereg, pg_status,
          pg_chk_dt, pg_chk_method, due_dt, birth_dt,
          n_born, n_alive, bwt, ease, offspring,
          wean_dt, wean_wt, by, notes))
    conn.commit()
print("  Done")

print(f"\nSeed complete for BusinessID={BID}.")
print(f"Animals created: {list(animal_ids.keys())}")
conn.close()
