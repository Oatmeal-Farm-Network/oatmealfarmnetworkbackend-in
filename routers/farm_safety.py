import json
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from database import get_db

router = APIRouter(prefix="/api/farm-safety", tags=["farm_safety"])

INCIDENT_TYPES = [
    "Near Miss", "First Aid", "Medical Treatment",
    "Lost Time Injury", "Property Damage", "Environmental", "Other",
]
SEVERITIES = ["Low", "Medium", "High", "Critical"]
STATUSES   = ["Open", "Under Investigation", "Closed"]


def _ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'SafetyIncident')
        CREATE TABLE SafetyIncident (
            IncidentID       INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID       INT NOT NULL,
            IncidentDate     DATE NOT NULL,
            IncidentType     NVARCHAR(100),
            Severity         NVARCHAR(50),
            Location         NVARCHAR(200),
            Description      NVARCHAR(MAX),
            InjuredPerson    NVARCHAR(200),
            WitnessNames     NVARCHAR(500),
            ImmediateAction  NVARCHAR(MAX),
            CorrectiveAction NVARCHAR(MAX),
            ReportedBy       NVARCHAR(200),
            InvestigationDue DATE,
            Status           NVARCHAR(50) DEFAULT 'Open',
            CreatedAt        DATETIME2 DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'SafetyChecklist')
        CREATE TABLE SafetyChecklist (
            ChecklistID   INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID    INT NOT NULL,
            ChecklistName NVARCHAR(200) NOT NULL,
            ChecklistType NVARCHAR(100),
            ItemsJSON     NVARCHAR(MAX),
            CreatedAt     DATETIME2 DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'SafetyChecklistRun')
        CREATE TABLE SafetyChecklistRun (
            RunID         INT IDENTITY(1,1) PRIMARY KEY,
            ChecklistID   INT NOT NULL,
            BusinessID    INT NOT NULL,
            RunDate       DATE NOT NULL,
            Operator      NVARCHAR(200),
            ResultsJSON   NVARCHAR(MAX),
            OverallPass   BIT,
            Notes         NVARCHAR(MAX),
            CreatedAt     DATETIME2 DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ChemicalSDS')
        CREATE TABLE ChemicalSDS (
            SDSID              INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID         INT NOT NULL,
            ProductName        NVARCHAR(300) NOT NULL,
            Manufacturer       NVARCHAR(200),
            HazardClass        NVARCHAR(200),
            ActiveIngredient   NVARCHAR(500),
            PPERequired        NVARCHAR(500),
            FirstAid           NVARCHAR(MAX),
            StorageReqs        NVARCHAR(MAX),
            EmergencyContact   NVARCHAR(200),
            CreatedAt          DATETIME2 DEFAULT GETDATE()
        )
    """))
    db.commit()


# ── Incidents ─────────────────────────────────────────────────────────────────

def _inc_row(r) -> dict:
    return {
        "incident_id":       r[0],  "business_id":      r[1],
        "incident_date":     str(r[2]) if r[2] else None,
        "incident_type":     r[3],  "severity":          r[4],
        "location":          r[5],  "description":       r[6],
        "injured_person":    r[7],  "witness_names":     r[8],
        "immediate_action":  r[9],  "corrective_action": r[10],
        "reported_by":       r[11],
        "investigation_due": str(r[12]) if r[12] else None,
        "status":            r[13],
        "created_at":        str(r[14]) if r[14] else None,
    }


@router.get("/incidents")
def list_incidents(
    business_id: int = Query(...),
    status: Optional[str] = None,
    severity: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    sql = """
        SELECT IncidentID, BusinessID, IncidentDate, IncidentType, Severity, Location,
               Description, InjuredPerson, WitnessNames, ImmediateAction, CorrectiveAction,
               ReportedBy, InvestigationDue, Status, CreatedAt
        FROM SafetyIncident WHERE BusinessID = :bid
    """
    params: dict = {"bid": business_id}
    if status:
        sql += " AND Status = :status"; params["status"] = status
    if severity:
        sql += " AND Severity = :sev"; params["sev"] = severity
    sql += " ORDER BY IncidentDate DESC"
    return [_inc_row(r) for r in db.execute(text(sql), params).fetchall()]


@router.post("/incidents")
def create_incident(
    business_id: int,
    incident_date: str,
    incident_type: Optional[str] = "Near Miss",
    severity: Optional[str] = "Low",
    location: Optional[str] = None,
    description: Optional[str] = None,
    injured_person: Optional[str] = None,
    witness_names: Optional[str] = None,
    immediate_action: Optional[str] = None,
    corrective_action: Optional[str] = None,
    reported_by: Optional[str] = None,
    investigation_due: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    db.execute(
        text("""
            INSERT INTO SafetyIncident
                (BusinessID, IncidentDate, IncidentType, Severity, Location, Description,
                 InjuredPerson, WitnessNames, ImmediateAction, CorrectiveAction,
                 ReportedBy, InvestigationDue, Status)
            VALUES (:bid, :dt, :type, :sev, :loc, :desc,
                    :inj, :wit, :imm, :corr, :rep, :due, 'Open')
        """),
        {
            "bid": business_id, "dt": incident_date, "type": incident_type,
            "sev": severity, "loc": location, "desc": description,
            "inj": injured_person, "wit": witness_names,
            "imm": immediate_action, "corr": corrective_action,
            "rep": reported_by, "due": investigation_due or None,
        },
    )
    db.commit()
    return {"ok": True}


@router.patch("/incidents/{incident_id}/status")
def update_incident_status(
    incident_id: int,
    status: str,
    corrective_action: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    params: dict = {"id": incident_id, "status": status}
    sql = "UPDATE SafetyIncident SET Status = :status"
    if corrective_action:
        sql += ", CorrectiveAction = :ca"; params["ca"] = corrective_action
    sql += " WHERE IncidentID = :id"
    db.execute(text(sql), params)
    db.commit()
    return {"ok": True}


@router.delete("/incidents/{incident_id}")
def delete_incident(incident_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM SafetyIncident WHERE IncidentID = :id"), {"id": incident_id})
    db.commit()
    return {"ok": True}


# ── Checklists ────────────────────────────────────────────────────────────────

@router.get("/checklists")
def list_checklists(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(
        text("""
            SELECT ChecklistID, BusinessID, ChecklistName, ChecklistType, ItemsJSON, CreatedAt
            FROM SafetyChecklist WHERE BusinessID = :bid ORDER BY ChecklistName
        """),
        {"bid": business_id},
    ).fetchall()
    result = []
    for r in rows:
        items = json.loads(r[4]) if r[4] else []
        result.append({
            "checklist_id": r[0], "business_id": r[1],
            "checklist_name": r[2], "checklist_type": r[3],
            "items": items, "created_at": str(r[5]) if r[5] else None,
        })
    return result


@router.post("/checklists")
def create_checklist(
    business_id: int,
    checklist_name: str,
    checklist_type: Optional[str] = "General",
    items: str = "[]",  # JSON array of strings
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    try:
        parsed = json.loads(items)
    except Exception:
        parsed = []
    db.execute(
        text("""
            INSERT INTO SafetyChecklist (BusinessID, ChecklistName, ChecklistType, ItemsJSON)
            VALUES (:bid, :name, :type, :items)
        """),
        {"bid": business_id, "name": checklist_name, "type": checklist_type, "items": json.dumps(parsed)},
    )
    db.commit()
    return {"ok": True}


@router.delete("/checklists/{checklist_id}")
def delete_checklist(checklist_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM SafetyChecklistRun WHERE ChecklistID = :id"), {"id": checklist_id})
    db.execute(text("DELETE FROM SafetyChecklist WHERE ChecklistID = :id"), {"id": checklist_id})
    db.commit()
    return {"ok": True}


@router.post("/checklists/{checklist_id}/run")
def run_checklist(
    checklist_id: int,
    business_id: int,
    run_date: str,
    operator: Optional[str] = None,
    results: str = "[]",  # JSON [{item, passed, note}]
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    try:
        parsed = json.loads(results)
    except Exception:
        parsed = []
    overall_pass = all(r.get("passed", False) for r in parsed) if parsed else False
    db.execute(
        text("""
            INSERT INTO SafetyChecklistRun
                (ChecklistID, BusinessID, RunDate, Operator, ResultsJSON, OverallPass, Notes)
            VALUES (:cid, :bid, :dt, :op, :res, :pass, :notes)
        """),
        {
            "cid": checklist_id, "bid": business_id, "dt": run_date,
            "op": operator, "res": json.dumps(parsed),
            "pass": 1 if overall_pass else 0, "notes": notes,
        },
    )
    db.commit()
    return {"ok": True, "overall_pass": overall_pass}


@router.get("/checklists/{checklist_id}/runs")
def checklist_runs(checklist_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(
        text("""
            SELECT RunID, ChecklistID, BusinessID, RunDate, Operator,
                   ResultsJSON, OverallPass, Notes, CreatedAt
            FROM SafetyChecklistRun WHERE ChecklistID = :cid ORDER BY RunDate DESC
        """),
        {"cid": checklist_id},
    ).fetchall()
    return [
        {
            "run_id": r[0], "checklist_id": r[1], "business_id": r[2],
            "run_date": str(r[3]) if r[3] else None, "operator": r[4],
            "results": json.loads(r[5]) if r[5] else [],
            "overall_pass": bool(r[6]), "notes": r[7],
            "created_at": str(r[8]) if r[8] else None,
        }
        for r in rows
    ]


# ── Chemical SDS ──────────────────────────────────────────────────────────────

@router.get("/sds")
def list_sds(
    business_id: int = Query(...),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    sql = """
        SELECT SDSID, BusinessID, ProductName, Manufacturer, HazardClass,
               ActiveIngredient, PPERequired, FirstAid, StorageReqs,
               EmergencyContact, CreatedAt
        FROM ChemicalSDS WHERE BusinessID = :bid
    """
    params: dict = {"bid": business_id}
    if search:
        sql += " AND (ProductName LIKE :s OR ActiveIngredient LIKE :s OR Manufacturer LIKE :s)"
        params["s"] = f"%{search}%"
    sql += " ORDER BY ProductName"
    rows = db.execute(text(sql), params).fetchall()
    return [
        {
            "sds_id": r[0], "business_id": r[1], "product_name": r[2],
            "manufacturer": r[3], "hazard_class": r[4], "active_ingredient": r[5],
            "ppe_required": r[6], "first_aid": r[7], "storage_reqs": r[8],
            "emergency_contact": r[9], "created_at": str(r[10]) if r[10] else None,
        }
        for r in rows
    ]


@router.post("/sds")
def create_sds(
    business_id: int,
    product_name: str,
    manufacturer: Optional[str] = None,
    hazard_class: Optional[str] = None,
    active_ingredient: Optional[str] = None,
    ppe_required: Optional[str] = None,
    first_aid: Optional[str] = None,
    storage_reqs: Optional[str] = None,
    emergency_contact: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    db.execute(
        text("""
            INSERT INTO ChemicalSDS
                (BusinessID, ProductName, Manufacturer, HazardClass, ActiveIngredient,
                 PPERequired, FirstAid, StorageReqs, EmergencyContact)
            VALUES (:bid, :name, :mfr, :haz, :ai, :ppe, :fa, :stor, :ec)
        """),
        {
            "bid": business_id, "name": product_name, "mfr": manufacturer,
            "haz": hazard_class, "ai": active_ingredient, "ppe": ppe_required,
            "fa": first_aid, "stor": storage_reqs, "ec": emergency_contact,
        },
    )
    db.commit()
    return {"ok": True}


@router.delete("/sds/{sds_id}")
def delete_sds(sds_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM ChemicalSDS WHERE SDSID = :id"), {"id": sds_id})
    db.commit()
    return {"ok": True}


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary")
def safety_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)

    def _s(sql, p=None):
        try:
            return db.execute(text(sql), p or {"bid": business_id}).fetchone()
        except Exception:
            return None

    open_inc   = _s("SELECT COUNT(*) FROM SafetyIncident WHERE BusinessID=:bid AND Status='Open'")
    ytd_inc    = _s("SELECT COUNT(*) FROM SafetyIncident WHERE BusinessID=:bid AND YEAR(IncidentDate)=YEAR(GETDATE())")
    lti_ytd    = _s("SELECT COUNT(*) FROM SafetyIncident WHERE BusinessID=:bid AND IncidentType='Lost Time Injury' AND YEAR(IncidentDate)=YEAR(GETDATE())")
    overdue    = _s("SELECT COUNT(*) FROM SafetyIncident WHERE BusinessID=:bid AND Status!='Closed' AND InvestigationDue < CAST(GETDATE() AS DATE)")
    sds_count  = _s("SELECT COUNT(*) FROM ChemicalSDS WHERE BusinessID=:bid")
    cl_count   = _s("SELECT COUNT(*) FROM SafetyChecklist WHERE BusinessID=:bid")
    last_run   = _s("SELECT TOP 1 RunDate, OverallPass FROM SafetyChecklistRun WHERE BusinessID=:bid ORDER BY RunDate DESC")

    return {
        "open_incidents":    open_inc[0]  if open_inc  else 0,
        "ytd_incidents":     ytd_inc[0]   if ytd_inc   else 0,
        "lti_ytd":           lti_ytd[0]   if lti_ytd   else 0,
        "overdue_investigations": overdue[0] if overdue else 0,
        "sds_records":       sds_count[0] if sds_count else 0,
        "checklists":        cl_count[0]  if cl_count  else 0,
        "last_checklist_run": str(last_run[0]) if last_run else None,
        "last_checklist_passed": bool(last_run[1]) if last_run else None,
    }
