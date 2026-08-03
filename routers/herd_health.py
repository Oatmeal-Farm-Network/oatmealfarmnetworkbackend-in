from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional
from pydantic import BaseModel
from datetime import date, datetime
from decimal import Decimal
from herd_health_accounting import post_expense_je, post_income_je, void_je, sync_herd_health_to_accounting

router = APIRouter(prefix="/api/herd-health", tags=["herd-health"])

# ── helpers ──────────────────────────────────────────────────────────────────

def _row(r):
    return dict(r._mapping) if r else None

def _rows(rs):
    return [dict(r._mapping) for r in rs]

def _bid(business_id, db):
    if not business_id:
        raise HTTPException(400, "business_id required")

# ── DASHBOARD ─────────────────────────────────────────────────────────────────

@router.get("/dashboard")
def dashboard(business_id: int, db: Session = Depends(get_db)):
    _bid(business_id, db)
    def count(table, extra=""):
        return db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE BusinessID=:b {extra}"),
                          {"b": business_id}).scalar() or 0
    today = date.today().isoformat()
    return {
        "open_events":        count("HerdHealthEvent", "AND ResolvedDate IS NULL"),
        "vaccinations_due":   count("HerdHealthVaccination", f"AND NextDueDate <= '{today}'"),
        "active_quarantine":  count("HerdHealthQuarantine", "AND Status='Active'"),
        "active_treatments":  count("HerdHealthTreatment", "AND Outcome IS NULL"),
        "low_medications":    count("HerdHealthMedication", "AND QuantityOnHand IS NOT NULL AND ReorderPoint IS NOT NULL AND QuantityOnHand <= ReorderPoint"),
        "recent_events": _rows(db.execute(text("""
            SELECT TOP 5 EventID, EventDate, EventType, Severity, Title, AnimalTag
            FROM HerdHealthEvent WHERE BusinessID=:b ORDER BY CreatedAt DESC
        """), {"b": business_id}).fetchall()),
        "upcoming_vaccinations": _rows(db.execute(text("""
            SELECT TOP 5 VaccinationID, NextDueDate, VaccineName, AnimalTag, GroupName
            FROM HerdHealthVaccination
            WHERE BusinessID=:b AND NextDueDate IS NOT NULL AND NextDueDate >= CAST(GETUTCDATE() AS DATE)
            ORDER BY NextDueDate
        """), {"b": business_id}).fetchall()),
        "active_quarantine_list": _rows(db.execute(text("""
            SELECT TOP 5 QuarantineID, AnimalTag, Reason, StartDate, PlannedEndDate
            FROM HerdHealthQuarantine WHERE BusinessID=:b AND Status='Active'
            ORDER BY StartDate
        """), {"b": business_id}).fetchall()),
    }

# ── HEALTH EVENTS ─────────────────────────────────────────────────────────────

class EventIn(BaseModel):
    AnimalID: Optional[int] = None
    AnimalTag: Optional[str] = None
    EventDate: Optional[str] = None
    EventType: Optional[str] = None
    Severity: Optional[str] = None
    Title: Optional[str] = None
    Description: Optional[str] = None
    Treatment: Optional[str] = None
    ResolvedDate: Optional[str] = None
    ResolvedNotes: Optional[str] = None
    RecordedBy: Optional[str] = None

@router.get("/events")
def list_events(business_id: int, db: Session = Depends(get_db)):
    return _rows(db.execute(text("""
        SELECT * FROM HerdHealthEvent WHERE BusinessID=:b ORDER BY EventDate DESC, CreatedAt DESC
    """), {"b": business_id}).fetchall())

@router.post("/events")
def create_event(business_id: int, body: EventIn, db: Session = Depends(get_db)):
    r = db.execute(text("""
        INSERT INTO HerdHealthEvent
            (BusinessID,AnimalID,AnimalTag,EventDate,EventType,Severity,Title,
             Description,Treatment,ResolvedDate,ResolvedNotes,RecordedBy)
        OUTPUT inserted.EventID
        VALUES (:b,:aid,:tag,:dt,:type,:sev,:title,:desc,:tx,:res,:resn,:by)
    """), {"b":business_id,"aid":body.AnimalID,"tag":body.AnimalTag,"dt":body.EventDate,
           "type":body.EventType,"sev":body.Severity,"title":body.Title,
           "desc":body.Description,"tx":body.Treatment,"res":body.ResolvedDate,
           "resn":body.ResolvedNotes,"by":body.RecordedBy})
    db.commit()
    return {"event_id": r.scalar()}

@router.put("/events/{event_id}")
def update_event(event_id: int, body: EventIn, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE HerdHealthEvent SET
            AnimalID=:aid,AnimalTag=:tag,EventDate=:dt,EventType=:type,Severity=:sev,
            Title=:title,Description=:desc,Treatment=:tx,ResolvedDate=:res,
            ResolvedNotes=:resn,RecordedBy=:by,UpdatedAt=GETUTCDATE()
        WHERE EventID=:id
    """), {"id":event_id,"aid":body.AnimalID,"tag":body.AnimalTag,"dt":body.EventDate,
           "type":body.EventType,"sev":body.Severity,"title":body.Title,
           "desc":body.Description,"tx":body.Treatment,"res":body.ResolvedDate,
           "resn":body.ResolvedNotes,"by":body.RecordedBy})
    db.commit()
    return {"ok": True}

@router.delete("/events/{event_id}")
def delete_event(event_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM HerdHealthEvent WHERE EventID=:id"), {"id": event_id})
    db.commit()
    return {"ok": True}

# ── VACCINATIONS ──────────────────────────────────────────────────────────────

class VaccineIn(BaseModel):
    AnimalID: Optional[int] = None
    AnimalTag: Optional[str] = None
    GroupName: Optional[str] = None
    VaccineName: Optional[str] = None
    VaccineManufacturer: Optional[str] = None
    VaccineType: Optional[str] = None
    AdministeredDate: Optional[str] = None
    NextDueDate: Optional[str] = None
    Dosage: Optional[str] = None
    Route: Optional[str] = None
    LotNumber: Optional[str] = None
    ExpirationDate: Optional[str] = None
    AdministeredBy: Optional[str] = None
    Notes: Optional[str] = None

@router.get("/vaccinations")
def list_vaccinations(business_id: int, db: Session = Depends(get_db)):
    return _rows(db.execute(text("""
        SELECT * FROM HerdHealthVaccination WHERE BusinessID=:b
        ORDER BY AdministeredDate DESC, CreatedAt DESC
    """), {"b": business_id}).fetchall())

@router.post("/vaccinations")
def create_vaccination(business_id: int, body: VaccineIn, db: Session = Depends(get_db)):
    r = db.execute(text("""
        INSERT INTO HerdHealthVaccination
            (BusinessID,AnimalID,AnimalTag,GroupName,VaccineName,VaccineManufacturer,
             VaccineType,AdministeredDate,NextDueDate,Dosage,Route,LotNumber,
             ExpirationDate,AdministeredBy,Notes)
        OUTPUT inserted.VaccinationID
        VALUES (:b,:aid,:tag,:grp,:vn,:vm,:vt,:adm,:due,:dos,:rt,:lot,:exp,:by,:notes)
    """), {"b":business_id,"aid":body.AnimalID,"tag":body.AnimalTag,"grp":body.GroupName,
           "vn":body.VaccineName,"vm":body.VaccineManufacturer,"vt":body.VaccineType,
           "adm":body.AdministeredDate,"due":body.NextDueDate,"dos":body.Dosage,
           "rt":body.Route,"lot":body.LotNumber,"exp":body.ExpirationDate,
           "by":body.AdministeredBy,"notes":body.Notes})
    db.commit()
    return {"vaccination_id": r.scalar()}

@router.put("/vaccinations/{vid}")
def update_vaccination(vid: int, body: VaccineIn, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE HerdHealthVaccination SET
            AnimalID=:aid,AnimalTag=:tag,GroupName=:grp,VaccineName=:vn,
            VaccineManufacturer=:vm,VaccineType=:vt,AdministeredDate=:adm,
            NextDueDate=:due,Dosage=:dos,Route=:rt,LotNumber=:lot,
            ExpirationDate=:exp,AdministeredBy=:by,Notes=:notes
        WHERE VaccinationID=:id
    """), {"id":vid,"aid":body.AnimalID,"tag":body.AnimalTag,"grp":body.GroupName,
           "vn":body.VaccineName,"vm":body.VaccineManufacturer,"vt":body.VaccineType,
           "adm":body.AdministeredDate,"due":body.NextDueDate,"dos":body.Dosage,
           "rt":body.Route,"lot":body.LotNumber,"exp":body.ExpirationDate,
           "by":body.AdministeredBy,"notes":body.Notes})
    db.commit()
    return {"ok": True}

@router.delete("/vaccinations/{vid}")
def delete_vaccination(vid: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM HerdHealthVaccination WHERE VaccinationID=:id"), {"id": vid})
    db.commit()
    return {"ok": True}

# ── TREATMENTS ────────────────────────────────────────────────────────────────

class TreatmentIn(BaseModel):
    AnimalID: Optional[int] = None
    AnimalTag: Optional[str] = None
    TreatmentDate: Optional[str] = None
    Diagnosis: Optional[str] = None
    Medication: Optional[str] = None
    ActiveIngredient: Optional[str] = None
    Dosage: Optional[str] = None
    Route: Optional[str] = None
    Frequency: Optional[str] = None
    DurationDays: Optional[int] = None
    WithdrawalDate: Optional[str] = None
    WithdrawalMilk: Optional[str] = None
    PrescribedBy: Optional[str] = None
    AdministeredBy: Optional[str] = None
    Cost: Optional[float] = None
    Outcome: Optional[str] = None
    Notes: Optional[str] = None

@router.get("/treatments")
def list_treatments(business_id: int, db: Session = Depends(get_db)):
    return _rows(db.execute(text("""
        SELECT * FROM HerdHealthTreatment WHERE BusinessID=:b
        ORDER BY TreatmentDate DESC, CreatedAt DESC
    """), {"b": business_id}).fetchall())

@router.post("/treatments")
def create_treatment(business_id: int, body: TreatmentIn, db: Session = Depends(get_db)):
    r = db.execute(text("""
        INSERT INTO HerdHealthTreatment
            (BusinessID,AnimalID,AnimalTag,TreatmentDate,Diagnosis,Medication,
             ActiveIngredient,Dosage,Route,Frequency,DurationDays,WithdrawalDate,
             WithdrawalMilk,PrescribedBy,AdministeredBy,Cost,Outcome,Notes)
        OUTPUT inserted.TreatmentID
        VALUES (:b,:aid,:tag,:dt,:diag,:med,:ai,:dos,:rt,:freq,:dur,:wd,:wm,:prx,:by,:cost,:out,:notes)
    """), {"b":business_id,"aid":body.AnimalID,"tag":body.AnimalTag,"dt":body.TreatmentDate,
           "diag":body.Diagnosis,"med":body.Medication,"ai":body.ActiveIngredient,
           "dos":body.Dosage,"rt":body.Route,"freq":body.Frequency,"dur":body.DurationDays,
           "wd":body.WithdrawalDate,"wm":body.WithdrawalMilk,"prx":body.PrescribedBy,
           "by":body.AdministeredBy,"cost":body.Cost,"out":body.Outcome,"notes":body.Notes})
    treatment_id = r.scalar()
    db.commit()
    post_expense_je(db, business_id, body.Cost, body.TreatmentDate,
                    f"Treatment — {body.Diagnosis or body.Medication or 'Livestock Treatment'}",
                    "herd_treatment", treatment_id)
    db.commit()
    return {"treatment_id": treatment_id}

@router.put("/treatments/{tid}")
def update_treatment(tid: int, body: TreatmentIn, db: Session = Depends(get_db)):
    biz = db.execute(text("SELECT BusinessID FROM HerdHealthTreatment WHERE TreatmentID=:id"), {"id": tid}).scalar()
    db.execute(text("""
        UPDATE HerdHealthTreatment SET
            AnimalID=:aid,AnimalTag=:tag,TreatmentDate=:dt,Diagnosis=:diag,
            Medication=:med,ActiveIngredient=:ai,Dosage=:dos,Route=:rt,
            Frequency=:freq,DurationDays=:dur,WithdrawalDate=:wd,WithdrawalMilk=:wm,
            PrescribedBy=:prx,AdministeredBy=:by,Cost=:cost,Outcome=:out,Notes=:notes
        WHERE TreatmentID=:id
    """), {"id":tid,"aid":body.AnimalID,"tag":body.AnimalTag,"dt":body.TreatmentDate,
           "diag":body.Diagnosis,"med":body.Medication,"ai":body.ActiveIngredient,
           "dos":body.Dosage,"rt":body.Route,"freq":body.Frequency,"dur":body.DurationDays,
           "wd":body.WithdrawalDate,"wm":body.WithdrawalMilk,"prx":body.PrescribedBy,
           "by":body.AdministeredBy,"cost":body.Cost,"out":body.Outcome,"notes":body.Notes})
    db.commit()
    if biz:
        post_expense_je(db, biz, body.Cost, body.TreatmentDate,
                        f"Treatment — {body.Diagnosis or body.Medication or 'Livestock Treatment'}",
                        "herd_treatment", tid)
        db.commit()
    return {"ok": True}

@router.delete("/treatments/{tid}")
def delete_treatment(tid: int, db: Session = Depends(get_db)):
    void_je(db, "herd_treatment", tid)
    db.execute(text("DELETE FROM HerdHealthTreatment WHERE TreatmentID=:id"), {"id": tid})
    db.commit()
    return {"ok": True}

# ── VET VISITS ────────────────────────────────────────────────────────────────

class VetVisitIn(BaseModel):
    VisitDate: Optional[str] = None
    VetName: Optional[str] = None
    ClinicName: Optional[str] = None
    VisitType: Optional[str] = None
    AffectedAnimals: Optional[str] = None
    ChiefComplaint: Optional[str] = None
    Findings: Optional[str] = None
    Diagnoses: Optional[str] = None
    ProceduresPerformed: Optional[str] = None
    Prescriptions: Optional[str] = None
    FollowUpDate: Optional[str] = None
    FollowUpNotes: Optional[str] = None
    Cost: Optional[float] = None
    Notes: Optional[str] = None

@router.get("/vet-visits")
def list_vet_visits(business_id: int, db: Session = Depends(get_db)):
    return _rows(db.execute(text("""
        SELECT * FROM HerdHealthVetVisit WHERE BusinessID=:b
        ORDER BY VisitDate DESC, CreatedAt DESC
    """), {"b": business_id}).fetchall())

@router.post("/vet-visits")
def create_vet_visit(business_id: int, body: VetVisitIn, db: Session = Depends(get_db)):
    r = db.execute(text("""
        INSERT INTO HerdHealthVetVisit
            (BusinessID,VisitDate,VetName,ClinicName,VisitType,AffectedAnimals,
             ChiefComplaint,Findings,Diagnoses,ProceduresPerformed,Prescriptions,
             FollowUpDate,FollowUpNotes,Cost,Notes)
        OUTPUT inserted.VisitID
        VALUES (:b,:dt,:vet,:clinic,:type,:animals,:cc,:find,:diag,:proc,:rx,:fu,:fun,:cost,:notes)
    """), {"b":business_id,"dt":body.VisitDate,"vet":body.VetName,"clinic":body.ClinicName,
           "type":body.VisitType,"animals":body.AffectedAnimals,"cc":body.ChiefComplaint,
           "find":body.Findings,"diag":body.Diagnoses,"proc":body.ProceduresPerformed,
           "rx":body.Prescriptions,"fu":body.FollowUpDate,"fun":body.FollowUpNotes,
           "cost":body.Cost,"notes":body.Notes})
    visit_id = r.scalar()
    db.commit()
    post_expense_je(db, business_id, body.Cost, body.VisitDate,
                    f"Vet Visit — {body.VetName or body.ClinicName or 'Veterinarian'}",
                    "herd_vet_visit", visit_id)
    db.commit()
    return {"visit_id": visit_id}

@router.put("/vet-visits/{vid}")
def update_vet_visit(vid: int, body: VetVisitIn, db: Session = Depends(get_db)):
    biz = db.execute(text("SELECT BusinessID FROM HerdHealthVetVisit WHERE VisitID=:id"), {"id": vid}).scalar()
    db.execute(text("""
        UPDATE HerdHealthVetVisit SET
            VisitDate=:dt,VetName=:vet,ClinicName=:clinic,VisitType=:type,
            AffectedAnimals=:animals,ChiefComplaint=:cc,Findings=:find,
            Diagnoses=:diag,ProceduresPerformed=:proc,Prescriptions=:rx,
            FollowUpDate=:fu,FollowUpNotes=:fun,Cost=:cost,Notes=:notes
        WHERE VisitID=:id
    """), {"id":vid,"dt":body.VisitDate,"vet":body.VetName,"clinic":body.ClinicName,
           "type":body.VisitType,"animals":body.AffectedAnimals,"cc":body.ChiefComplaint,
           "find":body.Findings,"diag":body.Diagnoses,"proc":body.ProceduresPerformed,
           "rx":body.Prescriptions,"fu":body.FollowUpDate,"fun":body.FollowUpNotes,
           "cost":body.Cost,"notes":body.Notes})
    db.commit()
    if biz:
        post_expense_je(db, biz, body.Cost, body.VisitDate,
                        f"Vet Visit — {body.VetName or body.ClinicName or 'Veterinarian'}",
                        "herd_vet_visit", vid)
        db.commit()
    return {"ok": True}

@router.delete("/vet-visits/{vid}")
def delete_vet_visit(vid: int, db: Session = Depends(get_db)):
    void_je(db, "herd_vet_visit", vid)
    db.execute(text("DELETE FROM HerdHealthVetVisit WHERE VisitID=:id"), {"id": vid})
    db.commit()
    return {"ok": True}

# ── MEDICATIONS ───────────────────────────────────────────────────────────────

class MedicationIn(BaseModel):
    MedicationName: Optional[str] = None
    ActiveIngredient: Optional[str] = None
    Category: Optional[str] = None
    Manufacturer: Optional[str] = None
    LotNumber: Optional[str] = None
    ExpirationDate: Optional[str] = None
    QuantityOnHand: Optional[float] = None
    Unit: Optional[str] = None
    StorageReq: Optional[str] = None
    WithdrawalMeat: Optional[str] = None
    WithdrawalMilk: Optional[str] = None
    Prescription: Optional[bool] = False
    ReorderPoint: Optional[float] = None
    UnitCost: Optional[float] = None
    Supplier: Optional[str] = None
    Notes: Optional[str] = None

@router.get("/medications")
def list_medications(business_id: int, db: Session = Depends(get_db)):
    return _rows(db.execute(text("""
        SELECT * FROM HerdHealthMedication WHERE BusinessID=:b
        ORDER BY MedicationName
    """), {"b": business_id}).fetchall())

@router.post("/medications")
def create_medication(business_id: int, body: MedicationIn, db: Session = Depends(get_db)):
    r = db.execute(text("""
        INSERT INTO HerdHealthMedication
            (BusinessID,MedicationName,ActiveIngredient,Category,Manufacturer,LotNumber,
             ExpirationDate,QuantityOnHand,Unit,StorageReq,WithdrawalMeat,WithdrawalMilk,
             Prescription,ReorderPoint,UnitCost,Supplier,Notes)
        OUTPUT inserted.MedicationID
        VALUES (:b,:name,:ai,:cat,:mfr,:lot,:exp,:qty,:unit,:store,:wm,:wmilk,:rx,:rp,:uc,:sup,:notes)
    """), {"b":business_id,"name":body.MedicationName,"ai":body.ActiveIngredient,
           "cat":body.Category,"mfr":body.Manufacturer,"lot":body.LotNumber,
           "exp":body.ExpirationDate,"qty":body.QuantityOnHand,"unit":body.Unit,
           "store":body.StorageReq,"wm":body.WithdrawalMeat,"wmilk":body.WithdrawalMilk,
           "rx":1 if body.Prescription else 0,"rp":body.ReorderPoint,
           "uc":body.UnitCost,"sup":body.Supplier,"notes":body.Notes})
    db.commit()
    return {"medication_id": r.scalar()}

@router.put("/medications/{mid}")
def update_medication(mid: int, body: MedicationIn, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE HerdHealthMedication SET
            MedicationName=:name,ActiveIngredient=:ai,Category=:cat,Manufacturer=:mfr,
            LotNumber=:lot,ExpirationDate=:exp,QuantityOnHand=:qty,Unit=:unit,
            StorageReq=:store,WithdrawalMeat=:wm,WithdrawalMilk=:wmilk,
            Prescription=:rx,ReorderPoint=:rp,UnitCost=:uc,Supplier=:sup,
            Notes=:notes,UpdatedAt=GETUTCDATE()
        WHERE MedicationID=:id
    """), {"id":mid,"name":body.MedicationName,"ai":body.ActiveIngredient,
           "cat":body.Category,"mfr":body.Manufacturer,"lot":body.LotNumber,
           "exp":body.ExpirationDate,"qty":body.QuantityOnHand,"unit":body.Unit,
           "store":body.StorageReq,"wm":body.WithdrawalMeat,"wmilk":body.WithdrawalMilk,
           "rx":1 if body.Prescription else 0,"rp":body.ReorderPoint,
           "uc":body.UnitCost,"sup":body.Supplier,"notes":body.Notes})
    db.commit()
    return {"ok": True}

@router.delete("/medications/{mid}")
def delete_medication(mid: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM HerdHealthMedication WHERE MedicationID=:id"), {"id": mid})
    db.commit()
    return {"ok": True}

# ── WEIGHT & BCS ──────────────────────────────────────────────────────────────

class WeightIn(BaseModel):
    AnimalID: Optional[int] = None
    AnimalTag: Optional[str] = None
    RecordDate: Optional[str] = None
    WeightLbs: Optional[float] = None
    WeightKg: Optional[float] = None
    BodyConditionScore: Optional[float] = None
    FrameScore: Optional[int] = None
    RecordedBy: Optional[str] = None
    Method: Optional[str] = None
    Notes: Optional[str] = None

@router.get("/weights")
def list_weights(business_id: int, db: Session = Depends(get_db)):
    return _rows(db.execute(text("""
        SELECT * FROM HerdHealthWeight WHERE BusinessID=:b
        ORDER BY RecordDate DESC, CreatedAt DESC
    """), {"b": business_id}).fetchall())

@router.post("/weights")
def create_weight(business_id: int, body: WeightIn, db: Session = Depends(get_db)):
    r = db.execute(text("""
        INSERT INTO HerdHealthWeight
            (BusinessID,AnimalID,AnimalTag,RecordDate,WeightLbs,WeightKg,
             BodyConditionScore,FrameScore,RecordedBy,Method,Notes)
        OUTPUT inserted.WeightID
        VALUES (:b,:aid,:tag,:dt,:lbs,:kg,:bcs,:fs,:by,:method,:notes)
    """), {"b":business_id,"aid":body.AnimalID,"tag":body.AnimalTag,"dt":body.RecordDate,
           "lbs":body.WeightLbs,"kg":body.WeightKg,"bcs":body.BodyConditionScore,
           "fs":body.FrameScore,"by":body.RecordedBy,"method":body.Method,"notes":body.Notes})
    db.commit()
    return {"weight_id": r.scalar()}

@router.put("/weights/{wid}")
def update_weight(wid: int, body: WeightIn, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE HerdHealthWeight SET
            AnimalID=:aid,AnimalTag=:tag,RecordDate=:dt,WeightLbs=:lbs,WeightKg=:kg,
            BodyConditionScore=:bcs,FrameScore=:fs,RecordedBy=:by,Method=:method,Notes=:notes
        WHERE WeightID=:id
    """), {"id":wid,"aid":body.AnimalID,"tag":body.AnimalTag,"dt":body.RecordDate,
           "lbs":body.WeightLbs,"kg":body.WeightKg,"bcs":body.BodyConditionScore,
           "fs":body.FrameScore,"by":body.RecordedBy,"method":body.Method,"notes":body.Notes})
    db.commit()
    return {"ok": True}

@router.delete("/weights/{wid}")
def delete_weight(wid: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM HerdHealthWeight WHERE WeightID=:id"), {"id": wid})
    db.commit()
    return {"ok": True}

# ── PARASITE CONTROL ──────────────────────────────────────────────────────────

class ParasiteIn(BaseModel):
    AnimalID: Optional[int] = None
    AnimalTag: Optional[str] = None
    TestDate: Optional[str] = None
    TestType: Optional[str] = None
    FAMACHAScore: Optional[int] = None
    EggCount: Optional[int] = None
    ParasiteType: Optional[str] = None
    TreatmentGiven: Optional[str] = None
    Dewormer: Optional[str] = None
    DosageGiven: Optional[str] = None
    NextTestDate: Optional[str] = None
    RecordedBy: Optional[str] = None
    Notes: Optional[str] = None

@router.get("/parasites")
def list_parasites(business_id: int, db: Session = Depends(get_db)):
    return _rows(db.execute(text("""
        SELECT * FROM HerdHealthParasite WHERE BusinessID=:b
        ORDER BY TestDate DESC, CreatedAt DESC
    """), {"b": business_id}).fetchall())

@router.post("/parasites")
def create_parasite(business_id: int, body: ParasiteIn, db: Session = Depends(get_db)):
    r = db.execute(text("""
        INSERT INTO HerdHealthParasite
            (BusinessID,AnimalID,AnimalTag,TestDate,TestType,FAMACHAScore,EggCount,
             ParasiteType,TreatmentGiven,Dewormer,DosageGiven,NextTestDate,RecordedBy,Notes)
        OUTPUT inserted.ParasiteID
        VALUES (:b,:aid,:tag,:dt,:type,:fam,:epg,:ptype,:tx,:dew,:dos,:nxt,:by,:notes)
    """), {"b":business_id,"aid":body.AnimalID,"tag":body.AnimalTag,"dt":body.TestDate,
           "type":body.TestType,"fam":body.FAMACHAScore,"epg":body.EggCount,
           "ptype":body.ParasiteType,"tx":body.TreatmentGiven,"dew":body.Dewormer,
           "dos":body.DosageGiven,"nxt":body.NextTestDate,"by":body.RecordedBy,"notes":body.Notes})
    db.commit()
    return {"parasite_id": r.scalar()}

@router.put("/parasites/{pid}")
def update_parasite(pid: int, body: ParasiteIn, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE HerdHealthParasite SET
            AnimalID=:aid,AnimalTag=:tag,TestDate=:dt,TestType=:type,
            FAMACHAScore=:fam,EggCount=:epg,ParasiteType=:ptype,
            TreatmentGiven=:tx,Dewormer=:dew,DosageGiven=:dos,
            NextTestDate=:nxt,RecordedBy=:by,Notes=:notes
        WHERE ParasiteID=:id
    """), {"id":pid,"aid":body.AnimalID,"tag":body.AnimalTag,"dt":body.TestDate,
           "type":body.TestType,"fam":body.FAMACHAScore,"epg":body.EggCount,
           "ptype":body.ParasiteType,"tx":body.TreatmentGiven,"dew":body.Dewormer,
           "dos":body.DosageGiven,"nxt":body.NextTestDate,"by":body.RecordedBy,"notes":body.Notes})
    db.commit()
    return {"ok": True}

@router.delete("/parasites/{pid}")
def delete_parasite(pid: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM HerdHealthParasite WHERE ParasiteID=:id"), {"id": pid})
    db.commit()
    return {"ok": True}

# ── QUARANTINE ────────────────────────────────────────────────────────────────

class QuarantineIn(BaseModel):
    AnimalID: Optional[int] = None
    AnimalTag: Optional[str] = None
    StartDate: Optional[str] = None
    PlannedEndDate: Optional[str] = None
    ActualEndDate: Optional[str] = None
    Reason: Optional[str] = None
    Location: Optional[str] = None
    Status: Optional[str] = "Active"
    MonitoringFreq: Optional[str] = None
    MonitoringNotes: Optional[str] = None
    ReleasedBy: Optional[str] = None
    ReleaseConditions: Optional[str] = None
    Notes: Optional[str] = None

@router.get("/quarantine")
def list_quarantine(business_id: int, db: Session = Depends(get_db)):
    return _rows(db.execute(text("""
        SELECT * FROM HerdHealthQuarantine WHERE BusinessID=:b
        ORDER BY StartDate DESC, CreatedAt DESC
    """), {"b": business_id}).fetchall())

@router.post("/quarantine")
def create_quarantine(business_id: int, body: QuarantineIn, db: Session = Depends(get_db)):
    r = db.execute(text("""
        INSERT INTO HerdHealthQuarantine
            (BusinessID,AnimalID,AnimalTag,StartDate,PlannedEndDate,ActualEndDate,
             Reason,Location,Status,MonitoringFreq,MonitoringNotes,
             ReleasedBy,ReleaseConditions,Notes)
        OUTPUT inserted.QuarantineID
        VALUES (:b,:aid,:tag,:start,:pend,:aend,:reason,:loc,:status,:freq,:mon,:by,:cond,:notes)
    """), {"b":business_id,"aid":body.AnimalID,"tag":body.AnimalTag,"start":body.StartDate,
           "pend":body.PlannedEndDate,"aend":body.ActualEndDate,"reason":body.Reason,
           "loc":body.Location,"status":body.Status,"freq":body.MonitoringFreq,
           "mon":body.MonitoringNotes,"by":body.ReleasedBy,"cond":body.ReleaseConditions,
           "notes":body.Notes})
    db.commit()
    return {"quarantine_id": r.scalar()}

@router.put("/quarantine/{qid}")
def update_quarantine(qid: int, body: QuarantineIn, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE HerdHealthQuarantine SET
            AnimalID=:aid,AnimalTag=:tag,StartDate=:start,PlannedEndDate=:pend,
            ActualEndDate=:aend,Reason=:reason,Location=:loc,Status=:status,
            MonitoringFreq=:freq,MonitoringNotes=:mon,ReleasedBy=:by,
            ReleaseConditions=:cond,Notes=:notes,UpdatedAt=GETUTCDATE()
        WHERE QuarantineID=:id
    """), {"id":qid,"aid":body.AnimalID,"tag":body.AnimalTag,"start":body.StartDate,
           "pend":body.PlannedEndDate,"aend":body.ActualEndDate,"reason":body.Reason,
           "loc":body.Location,"status":body.Status,"freq":body.MonitoringFreq,
           "mon":body.MonitoringNotes,"by":body.ReleasedBy,"cond":body.ReleaseConditions,
           "notes":body.Notes})
    db.commit()
    return {"ok": True}

@router.delete("/quarantine/{qid}")
def delete_quarantine(qid: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM HerdHealthQuarantine WHERE QuarantineID=:id"), {"id": qid})
    db.commit()
    return {"ok": True}

# ── MORTALITY ─────────────────────────────────────────────────────────────────

class MortalityIn(BaseModel):
    AnimalID: Optional[int] = None
    AnimalTag: Optional[str] = None
    AnimalSpecies: Optional[str] = None
    DeathDate: Optional[str] = None
    CauseOfDeath: Optional[str] = None
    DeathCategory: Optional[str] = None
    Location: Optional[str] = None
    AgeAtDeath: Optional[str] = None
    WeightAtDeath: Optional[float] = None
    PostMortemDone: Optional[bool] = False
    PostMortemDate: Optional[str] = None
    PostMortemFindings: Optional[str] = None
    DisposalMethod: Optional[str] = None
    InsuranceClaim: Optional[bool] = False
    InsuranceAmount: Optional[float] = None
    EstimatedValue: Optional[float] = None
    ReportedTo: Optional[str] = None
    Notes: Optional[str] = None

@router.get("/mortality")
def list_mortality(business_id: int, db: Session = Depends(get_db)):
    return _rows(db.execute(text("""
        SELECT * FROM HerdHealthMortality WHERE BusinessID=:b
        ORDER BY DeathDate DESC, CreatedAt DESC
    """), {"b": business_id}).fetchall())

@router.post("/mortality")
def create_mortality(business_id: int, body: MortalityIn, db: Session = Depends(get_db)):
    r = db.execute(text("""
        INSERT INTO HerdHealthMortality
            (BusinessID,AnimalID,AnimalTag,AnimalSpecies,DeathDate,CauseOfDeath,
             DeathCategory,Location,AgeAtDeath,WeightAtDeath,PostMortemDone,
             PostMortemDate,PostMortemFindings,DisposalMethod,InsuranceClaim,
             InsuranceAmount,EstimatedValue,ReportedTo,Notes)
        OUTPUT inserted.MortalityID
        VALUES (:b,:aid,:tag,:sp,:dt,:cause,:cat,:loc,:age,:wt,:pm,:pmd,:pmf,:disp,:ins,:iamt,:val,:rpt,:notes)
    """), {"b":business_id,"aid":body.AnimalID,"tag":body.AnimalTag,"sp":body.AnimalSpecies,
           "dt":body.DeathDate,"cause":body.CauseOfDeath,"cat":body.DeathCategory,
           "loc":body.Location,"age":body.AgeAtDeath,"wt":body.WeightAtDeath,
           "pm":1 if body.PostMortemDone else 0,"pmd":body.PostMortemDate,
           "pmf":body.PostMortemFindings,"disp":body.DisposalMethod,
           "ins":1 if body.InsuranceClaim else 0,"iamt":body.InsuranceAmount,
           "val":body.EstimatedValue,"rpt":body.ReportedTo,"notes":body.Notes})
    mortality_id = r.scalar()
    db.commit()
    if body.InsuranceClaim and body.InsuranceAmount:
        post_income_je(db, business_id, body.InsuranceAmount, body.DeathDate,
                       f"Livestock Insurance — {body.AnimalTag or body.AnimalSpecies or 'Animal'}",
                       "herd_mortality_ins", mortality_id)
        db.commit()
    return {"mortality_id": mortality_id}

@router.put("/mortality/{mid}")
def update_mortality(mid: int, body: MortalityIn, db: Session = Depends(get_db)):
    biz = db.execute(text("SELECT BusinessID FROM HerdHealthMortality WHERE MortalityID=:id"), {"id": mid}).scalar()
    db.execute(text("""
        UPDATE HerdHealthMortality SET
            AnimalID=:aid,AnimalTag=:tag,AnimalSpecies=:sp,DeathDate=:dt,
            CauseOfDeath=:cause,DeathCategory=:cat,Location=:loc,AgeAtDeath=:age,
            WeightAtDeath=:wt,PostMortemDone=:pm,PostMortemDate=:pmd,
            PostMortemFindings=:pmf,DisposalMethod=:disp,InsuranceClaim=:ins,
            InsuranceAmount=:iamt,EstimatedValue=:val,ReportedTo=:rpt,Notes=:notes
        WHERE MortalityID=:id
    """), {"id":mid,"aid":body.AnimalID,"tag":body.AnimalTag,"sp":body.AnimalSpecies,
           "dt":body.DeathDate,"cause":body.CauseOfDeath,"cat":body.DeathCategory,
           "loc":body.Location,"age":body.AgeAtDeath,"wt":body.WeightAtDeath,
           "pm":1 if body.PostMortemDone else 0,"pmd":body.PostMortemDate,
           "pmf":body.PostMortemFindings,"disp":body.DisposalMethod,
           "ins":1 if body.InsuranceClaim else 0,"iamt":body.InsuranceAmount,
           "val":body.EstimatedValue,"rpt":body.ReportedTo,"notes":body.Notes})
    db.commit()
    if biz:
        if body.InsuranceClaim and body.InsuranceAmount:
            post_income_je(db, biz, body.InsuranceAmount, body.DeathDate,
                           f"Livestock Insurance — {body.AnimalTag or body.AnimalSpecies or 'Animal'}",
                           "herd_mortality_ins", mid)
        else:
            void_je(db, "herd_mortality_ins", mid)
        db.commit()
    return {"ok": True}

@router.delete("/mortality/{mid}")
def delete_mortality(mid: int, db: Session = Depends(get_db)):
    void_je(db, "herd_mortality_ins", mid)
    db.execute(text("DELETE FROM HerdHealthMortality WHERE MortalityID=:id"), {"id": mid})
    db.commit()
    return {"ok": True}

# ── LAB RESULTS ───────────────────────────────────────────────────────────────

class LabResultIn(BaseModel):
    AnimalID: Optional[int] = None
    AnimalTag: Optional[str] = None
    GroupName: Optional[str] = None
    SampleDate: Optional[str] = None
    SampleType: Optional[str] = None
    LabName: Optional[str] = None
    AccessionNumber: Optional[str] = None
    TestType: Optional[str] = None
    ResultDate: Optional[str] = None
    Results: Optional[str] = None
    ReferenceRange: Optional[str] = None
    Interpretation: Optional[str] = None
    OrderedBy: Optional[str] = None
    AttachmentURL: Optional[str] = None
    Notes: Optional[str] = None

@router.get("/lab-results")
def list_lab_results(business_id: int, db: Session = Depends(get_db)):
    return _rows(db.execute(text("""
        SELECT * FROM HerdHealthLabResult WHERE BusinessID=:b
        ORDER BY SampleDate DESC, CreatedAt DESC
    """), {"b": business_id}).fetchall())

@router.post("/lab-results")
def create_lab_result(business_id: int, body: LabResultIn, db: Session = Depends(get_db)):
    r = db.execute(text("""
        INSERT INTO HerdHealthLabResult
            (BusinessID,AnimalID,AnimalTag,GroupName,SampleDate,SampleType,
             LabName,AccessionNumber,TestType,ResultDate,Results,
             ReferenceRange,Interpretation,OrderedBy,AttachmentURL,Notes)
        OUTPUT inserted.LabResultID
        VALUES (:b,:aid,:tag,:grp,:sdt,:stype,:lab,:acc,:ttype,:rdt,:res,:ref,:interp,:by,:url,:notes)
    """), {"b":business_id,"aid":body.AnimalID,"tag":body.AnimalTag,"grp":body.GroupName,
           "sdt":body.SampleDate,"stype":body.SampleType,"lab":body.LabName,
           "acc":body.AccessionNumber,"ttype":body.TestType,"rdt":body.ResultDate,
           "res":body.Results,"ref":body.ReferenceRange,"interp":body.Interpretation,
           "by":body.OrderedBy,"url":body.AttachmentURL,"notes":body.Notes})
    db.commit()
    return {"lab_result_id": r.scalar()}

@router.put("/lab-results/{lid}")
def update_lab_result(lid: int, body: LabResultIn, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE HerdHealthLabResult SET
            AnimalID=:aid,AnimalTag=:tag,GroupName=:grp,SampleDate=:sdt,SampleType=:stype,
            LabName=:lab,AccessionNumber=:acc,TestType=:ttype,ResultDate=:rdt,
            Results=:res,ReferenceRange=:ref,Interpretation=:interp,
            OrderedBy=:by,AttachmentURL=:url,Notes=:notes
        WHERE LabResultID=:id
    """), {"id":lid,"aid":body.AnimalID,"tag":body.AnimalTag,"grp":body.GroupName,
           "sdt":body.SampleDate,"stype":body.SampleType,"lab":body.LabName,
           "acc":body.AccessionNumber,"ttype":body.TestType,"rdt":body.ResultDate,
           "res":body.Results,"ref":body.ReferenceRange,"interp":body.Interpretation,
           "by":body.OrderedBy,"url":body.AttachmentURL,"notes":body.Notes})
    db.commit()
    return {"ok": True}

@router.delete("/lab-results/{lid}")
def delete_lab_result(lid: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM HerdHealthLabResult WHERE LabResultID=:id"), {"id": lid})
    db.commit()
    return {"ok": True}

# ── BIOSECURITY ───────────────────────────────────────────────────────────────

class BiosecurityIn(BaseModel):
    EventDate: Optional[str] = None
    EventType: Optional[str] = None
    PersonOrCompany: Optional[str] = None
    ContactInfo: Optional[str] = None
    Purpose: Optional[str] = None
    AnimalsContact: Optional[bool] = False
    AreasAccessed: Optional[str] = None
    CleaningProtocol: Optional[bool] = False
    PPEUsed: Optional[bool] = False
    ProtocolsFollowed: Optional[str] = None
    OriginLocation: Optional[str] = None
    HealthCertificate: Optional[bool] = False
    Notes: Optional[str] = None

@router.get("/biosecurity")
def list_biosecurity(business_id: int, db: Session = Depends(get_db)):
    return _rows(db.execute(text("""
        SELECT * FROM HerdHealthBiosecurity WHERE BusinessID=:b
        ORDER BY EventDate DESC, CreatedAt DESC
    """), {"b": business_id}).fetchall())

@router.post("/biosecurity")
def create_biosecurity(business_id: int, body: BiosecurityIn, db: Session = Depends(get_db)):
    r = db.execute(text("""
        INSERT INTO HerdHealthBiosecurity
            (BusinessID,EventDate,EventType,PersonOrCompany,ContactInfo,Purpose,
             AnimalsContact,AreasAccessed,CleaningProtocol,PPEUsed,
             ProtocolsFollowed,OriginLocation,HealthCertificate,Notes)
        OUTPUT inserted.BiosecurityID
        VALUES (:b,:dt,:type,:person,:contact,:purpose,:animals,:areas,:clean,:ppe,:protocols,:origin,:hc,:notes)
    """), {"b":business_id,"dt":body.EventDate,"type":body.EventType,
           "person":body.PersonOrCompany,"contact":body.ContactInfo,"purpose":body.Purpose,
           "animals":1 if body.AnimalsContact else 0,"areas":body.AreasAccessed,
           "clean":1 if body.CleaningProtocol else 0,"ppe":1 if body.PPEUsed else 0,
           "protocols":body.ProtocolsFollowed,"origin":body.OriginLocation,
           "hc":1 if body.HealthCertificate else 0,"notes":body.Notes})
    db.commit()
    return {"biosecurity_id": r.scalar()}

@router.put("/biosecurity/{bid}")
def update_biosecurity(bid: int, body: BiosecurityIn, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE HerdHealthBiosecurity SET
            EventDate=:dt,EventType=:type,PersonOrCompany=:person,ContactInfo=:contact,
            Purpose=:purpose,AnimalsContact=:animals,AreasAccessed=:areas,
            CleaningProtocol=:clean,PPEUsed=:ppe,ProtocolsFollowed=:protocols,
            OriginLocation=:origin,HealthCertificate=:hc,Notes=:notes
        WHERE BiosecurityID=:id
    """), {"id":bid,"dt":body.EventDate,"type":body.EventType,
           "person":body.PersonOrCompany,"contact":body.ContactInfo,"purpose":body.Purpose,
           "animals":1 if body.AnimalsContact else 0,"areas":body.AreasAccessed,
           "clean":1 if body.CleaningProtocol else 0,"ppe":1 if body.PPEUsed else 0,
           "protocols":body.ProtocolsFollowed,"origin":body.OriginLocation,
           "hc":1 if body.HealthCertificate else 0,"notes":body.Notes})
    db.commit()
    return {"ok": True}

@router.delete("/biosecurity/{bid}")
def delete_biosecurity(bid: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM HerdHealthBiosecurity WHERE BiosecurityID=:id"), {"id": bid})
    db.commit()
    return {"ok": True}

# ── VET CONTACTS ──────────────────────────────────────────────────────────────

class VetContactIn(BaseModel):
    Name: Optional[str] = None
    ClinicName: Optional[str] = None
    Role: Optional[str] = None
    LicenseNumber: Optional[str] = None
    Phone: Optional[str] = None
    EmergencyPhone: Optional[str] = None
    Email: Optional[str] = None
    Address: Optional[str] = None
    Specialties: Optional[str] = None
    Species: Optional[str] = None
    IsPreferred: Optional[bool] = False
    IsEmergency: Optional[bool] = False
    Notes: Optional[str] = None

@router.get("/vet-contacts")
def list_vet_contacts(business_id: int, db: Session = Depends(get_db)):
    return _rows(db.execute(text("""
        SELECT * FROM HerdHealthVetContact WHERE BusinessID=:b
        ORDER BY IsPreferred DESC, IsEmergency DESC, Name
    """), {"b": business_id}).fetchall())

@router.post("/vet-contacts")
def create_vet_contact(business_id: int, body: VetContactIn, db: Session = Depends(get_db)):
    r = db.execute(text("""
        INSERT INTO HerdHealthVetContact
            (BusinessID,Name,ClinicName,Role,LicenseNumber,Phone,EmergencyPhone,
             Email,Address,Specialties,Species,IsPreferred,IsEmergency,Notes)
        OUTPUT inserted.VetContactID
        VALUES (:b,:name,:clinic,:role,:lic,:phone,:emerg,:email,:addr,:spec,:sp,:pref,:isemerg,:notes)
    """), {"b":business_id,"name":body.Name,"clinic":body.ClinicName,"role":body.Role,
           "lic":body.LicenseNumber,"phone":body.Phone,"emerg":body.EmergencyPhone,
           "email":body.Email,"addr":body.Address,"spec":body.Specialties,"sp":body.Species,
           "pref":1 if body.IsPreferred else 0,"isemerg":1 if body.IsEmergency else 0,
           "notes":body.Notes})
    db.commit()
    return {"vet_contact_id": r.scalar()}

@router.put("/vet-contacts/{cid}")
def update_vet_contact(cid: int, body: VetContactIn, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE HerdHealthVetContact SET
            Name=:name,ClinicName=:clinic,Role=:role,LicenseNumber=:lic,Phone=:phone,
            EmergencyPhone=:emerg,Email=:email,Address=:addr,Specialties=:spec,
            Species=:sp,IsPreferred=:pref,IsEmergency=:isemerg,Notes=:notes,
            UpdatedAt=GETUTCDATE()
        WHERE VetContactID=:id
    """), {"id":cid,"name":body.Name,"clinic":body.ClinicName,"role":body.Role,
           "lic":body.LicenseNumber,"phone":body.Phone,"emerg":body.EmergencyPhone,
           "email":body.Email,"addr":body.Address,"spec":body.Specialties,"sp":body.Species,
           "pref":1 if body.IsPreferred else 0,"isemerg":1 if body.IsEmergency else 0,
           "notes":body.Notes})
    db.commit()
    return {"ok": True}

@router.delete("/vet-contacts/{cid}")
def delete_vet_contact(cid: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM HerdHealthVetContact WHERE VetContactID=:id"), {"id": cid})
    db.commit()
    return {"ok": True}

# ── REPRODUCTION / BREEDING ───────────────────────────────────────────────────

class ReproductionIn(BaseModel):
    AnimalTag: Optional[str] = None
    Species: Optional[str] = None
    EventType: Optional[str] = None
    EventDate: Optional[str] = None
    BreedingMethod: Optional[str] = None
    SireTag: Optional[str] = None
    SireName: Optional[str] = None
    SireBreed: Optional[str] = None
    SireRegNumber: Optional[str] = None
    PregnancyStatus: Optional[str] = None
    PregnancyCheckDate: Optional[str] = None
    PregnancyCheckMethod: Optional[str] = None
    ExpectedDueDate: Optional[str] = None
    ActualBirthDate: Optional[str] = None
    NumberBorn: Optional[int] = None
    NumberBornAlive: Optional[int] = None
    BirthWeightLbs: Optional[float] = None
    BirthEase: Optional[str] = None
    OffspringTags: Optional[str] = None
    WeanDate: Optional[str] = None
    WeanWeightLbs: Optional[float] = None
    PerformedBy: Optional[str] = None
    Notes: Optional[str] = None

@router.get("/reproduction")
def list_reproduction(business_id: int, db: Session = Depends(get_db)):
    return _rows(db.execute(text("""
        SELECT * FROM HerdHealthReproduction WHERE BusinessID=:b
        ORDER BY EventDate DESC, CreatedAt DESC
    """), {"b": business_id}).fetchall())

@router.post("/reproduction")
def create_reproduction(business_id: int, body: ReproductionIn, db: Session = Depends(get_db)):
    r = db.execute(text("""
        INSERT INTO HerdHealthReproduction
            (BusinessID,AnimalTag,Species,EventType,EventDate,BreedingMethod,
             SireTag,SireName,SireBreed,SireRegNumber,PregnancyStatus,
             PregnancyCheckDate,PregnancyCheckMethod,ExpectedDueDate,ActualBirthDate,
             NumberBorn,NumberBornAlive,BirthWeightLbs,BirthEase,OffspringTags,
             WeanDate,WeanWeightLbs,PerformedBy,Notes)
        OUTPUT inserted.ReproductionID
        VALUES (:b,:tag,:sp,:etype,:edt,:method,:siretag,:sirename,:sirebr,:sirereg,
                :pgstatus,:pgchkdt,:pgchkmethod,:duedt,:birthdt,:nborn,:nbalive,
                :bwt,:ease,:offspring,:weandt,:weanwt,:by,:notes)
    """), {"b":business_id,"tag":body.AnimalTag,"sp":body.Species,"etype":body.EventType,
           "edt":body.EventDate,"method":body.BreedingMethod,"siretag":body.SireTag,
           "sirename":body.SireName,"sirebr":body.SireBreed,"sirereg":body.SireRegNumber,
           "pgstatus":body.PregnancyStatus,"pgchkdt":body.PregnancyCheckDate,
           "pgchkmethod":body.PregnancyCheckMethod,"duedt":body.ExpectedDueDate,
           "birthdt":body.ActualBirthDate,"nborn":body.NumberBorn,"nbalive":body.NumberBornAlive,
           "bwt":body.BirthWeightLbs,"ease":body.BirthEase,"offspring":body.OffspringTags,
           "weandt":body.WeanDate,"weanwt":body.WeanWeightLbs,"by":body.PerformedBy,
           "notes":body.Notes})
    db.commit()
    return {"reproduction_id": r.scalar()}

@router.put("/reproduction/{rid}")
def update_reproduction(rid: int, body: ReproductionIn, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE HerdHealthReproduction SET
            AnimalTag=:tag,Species=:sp,EventType=:etype,EventDate=:edt,
            BreedingMethod=:method,SireTag=:siretag,SireName=:sirename,
            SireBreed=:sirebr,SireRegNumber=:sirereg,PregnancyStatus=:pgstatus,
            PregnancyCheckDate=:pgchkdt,PregnancyCheckMethod=:pgchkmethod,
            ExpectedDueDate=:duedt,ActualBirthDate=:birthdt,NumberBorn=:nborn,
            NumberBornAlive=:nbalive,BirthWeightLbs=:bwt,BirthEase=:ease,
            OffspringTags=:offspring,WeanDate=:weandt,WeanWeightLbs=:weanwt,
            PerformedBy=:by,Notes=:notes,UpdatedAt=GETUTCDATE()
        WHERE ReproductionID=:id
    """), {"id":rid,"tag":body.AnimalTag,"sp":body.Species,"etype":body.EventType,
           "edt":body.EventDate,"method":body.BreedingMethod,"siretag":body.SireTag,
           "sirename":body.SireName,"sirebr":body.SireBreed,"sirereg":body.SireRegNumber,
           "pgstatus":body.PregnancyStatus,"pgchkdt":body.PregnancyCheckDate,
           "pgchkmethod":body.PregnancyCheckMethod,"duedt":body.ExpectedDueDate,
           "birthdt":body.ActualBirthDate,"nborn":body.NumberBorn,"nbalive":body.NumberBornAlive,
           "bwt":body.BirthWeightLbs,"ease":body.BirthEase,"offspring":body.OffspringTags,
           "weandt":body.WeanDate,"weanwt":body.WeanWeightLbs,"by":body.PerformedBy,
           "notes":body.Notes})
    db.commit()
    return {"ok": True}

@router.delete("/reproduction/{rid}")
def delete_reproduction(rid: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM HerdHealthReproduction WHERE ReproductionID=:id"), {"id": rid})
    db.commit()
    return {"ok": True}

# ── ACCOUNTING SYNC ───────────────────────────────────────────────────────────

@router.post("/accounting/sync")
def sync_accounting(business_id: int, db: Session = Depends(get_db)):
    """Bulk-post all unposted herd health financial records to accounting."""
    _bid(business_id, db)
    return sync_herd_health_to_accounting(db, business_id)

# ── LIST BUSINESS ANIMALS (animal-picker dropdowns) ───────────────────────────

@router.get("/animals")
def list_business_animals(business_id: int, db: Session = Depends(get_db)):
    _bid(business_id, db)
    rows = db.execute(text("""
        SELECT a.AnimalID, a.FullName, a.SpeciesID,
               COALESCE(sa.SingularTerm, CAST(a.SpeciesID AS NVARCHAR)) AS SpeciesName,
               sc.SpeciesCategory AS Category
        FROM Animals a
        LEFT JOIN SpeciesAvailable sa ON sa.SpeciesID = a.SpeciesID
        LEFT JOIN speciescategory sc ON sc.SpeciesCategoryID = a.SpeciesCategoryID
        WHERE a.BusinessID = :b AND a.FullName IS NOT NULL
        ORDER BY sa.SingularTerm, a.FullName
    """), {"b": business_id}).fetchall()
    return _rows(rows)
