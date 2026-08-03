from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

router = APIRouter(prefix="/api/compliance", tags=["compliance_audit"])


def _ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='ComplianceAudit' AND xtype='U')
        CREATE TABLE ComplianceAudit (
            AuditID       INT IDENTITY PRIMARY KEY,
            BusinessID    INT NOT NULL,
            StandardName  NVARCHAR(100) NOT NULL,
            AuditName     NVARCHAR(200),
            AuditDate     DATE,
            AuditorName   NVARCHAR(150),
            Status        NVARCHAR(50) DEFAULT 'Scheduled',
            Score         DECIMAL(5,1),
            Notes         NVARCHAR(MAX),
            CreatedAt     DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='ComplianceChecklist' AND xtype='U')
        CREATE TABLE ComplianceChecklist (
            ChecklistID   INT IDENTITY PRIMARY KEY,
            BusinessID    INT NOT NULL,
            StandardName  NVARCHAR(100),
            ChecklistName NVARCHAR(200) NOT NULL,
            ItemsJSON     NVARCHAR(MAX),
            CreatedAt     DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='ComplianceChecklistRun' AND xtype='U')
        CREATE TABLE ComplianceChecklistRun (
            RunID            INT IDENTITY PRIMARY KEY,
            ChecklistID      INT NOT NULL,
            BusinessID       INT NOT NULL,
            AuditID          INT,
            RunDate          DATE NOT NULL,
            Operator         NVARCHAR(150),
            ResultsJSON      NVARCHAR(MAX),
            OverallPass      BIT DEFAULT 0,
            NonConformances  INT DEFAULT 0,
            Notes            NVARCHAR(MAX),
            CreatedAt        DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='CorrectiveAction' AND xtype='U')
        CREATE TABLE CorrectiveAction (
            CARID        INT IDENTITY PRIMARY KEY,
            BusinessID   INT NOT NULL,
            AuditID      INT,
            Finding      NVARCHAR(MAX) NOT NULL,
            Severity     NVARCHAR(30) DEFAULT 'Minor',
            AssignedTo   NVARCHAR(150),
            DueDate      DATE,
            Status       NVARCHAR(30) DEFAULT 'Open',
            Resolution   NVARCHAR(MAX),
            CreatedAt    DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


# ── Audits ────────────────────────────────────────────────────────────────────

@router.get("/audits")
def list_audits(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT AuditID, StandardName, AuditName, AuditDate, AuditorName,
               Status, Score, Notes, CreatedAt
        FROM ComplianceAudit
        WHERE BusinessID=:bid
        ORDER BY AuditDate DESC
    """), {"bid": business_id}).fetchall()
    return [dict(zip(
        ["audit_id","standard_name","audit_name","audit_date","auditor_name",
         "status","score","notes","created_at"], r
    )) for r in rows]


@router.post("/audits")
def create_audit(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO ComplianceAudit
            (BusinessID, StandardName, AuditName, AuditDate, AuditorName, Status, Score, Notes)
        OUTPUT INSERTED.AuditID
        VALUES (:bid,:std,:name,:dt,:auditor,:status,:score,:notes)
    """), {
        "bid": business_id, "std": body.get("standard_name","Other"),
        "name": body.get("audit_name"), "dt": body.get("audit_date") or None,
        "auditor": body.get("auditor_name"), "status": body.get("status","Scheduled"),
        "score": body.get("score") or None, "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"audit_id": row[0]}


@router.patch("/audits/{audit_id}/status")
def update_audit_status(audit_id: int, business_id: int = Query(...),
                        db: Session = Depends(get_db), body: dict = None):
    body = body or {}
    db.execute(text("""
        UPDATE ComplianceAudit SET Status=:status, Score=:score, Notes=:notes
        WHERE AuditID=:aid AND BusinessID=:bid
    """), {
        "aid": audit_id, "bid": business_id,
        "status": body.get("status"), "score": body.get("score") or None,
        "notes": body.get("notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/audits/{audit_id}")
def delete_audit(audit_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM CorrectiveAction WHERE AuditID=:aid AND BusinessID=:bid"),
               {"aid": audit_id, "bid": business_id})
    db.execute(text("DELETE FROM ComplianceAudit WHERE AuditID=:aid AND BusinessID=:bid"),
               {"aid": audit_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Checklists ────────────────────────────────────────────────────────────────

@router.get("/checklists")
def list_checklists(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT ChecklistID, StandardName, ChecklistName, ItemsJSON, CreatedAt
        FROM ComplianceChecklist WHERE BusinessID=:bid ORDER BY StandardName, ChecklistName
    """), {"bid": business_id}).fetchall()
    return [dict(zip(["checklist_id","standard_name","checklist_name","items_json","created_at"], r))
            for r in rows]


@router.post("/checklists")
def create_checklist(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO ComplianceChecklist (BusinessID, StandardName, ChecklistName, ItemsJSON)
        OUTPUT INSERTED.ChecklistID
        VALUES (:bid,:std,:name,:items)
    """), {
        "bid": business_id, "std": body.get("standard_name"),
        "name": body.get("checklist_name",""), "items": body.get("items_json","[]"),
    }).fetchone()
    db.commit()
    return {"checklist_id": row[0]}


@router.delete("/checklists/{checklist_id}")
def delete_checklist(checklist_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM ComplianceChecklistRun WHERE ChecklistID=:cid AND BusinessID=:bid"),
               {"cid": checklist_id, "bid": business_id})
    db.execute(text("DELETE FROM ComplianceChecklist WHERE ChecklistID=:cid AND BusinessID=:bid"),
               {"cid": checklist_id, "bid": business_id})
    db.commit()
    return {"ok": True}


@router.post("/checklists/{checklist_id}/run")
def run_checklist(checklist_id: int, business_id: int = Query(...),
                  db: Session = Depends(get_db), body: dict = None):
    body = body or {}
    nc = sum(1 for r in __import__("json").loads(body.get("results_json","[]"))
             if r.get("pass") is False)
    row = db.execute(text("""
        INSERT INTO ComplianceChecklistRun
            (ChecklistID, BusinessID, AuditID, RunDate, Operator, ResultsJSON, OverallPass, NonConformances, Notes)
        OUTPUT INSERTED.RunID
        VALUES (:cid,:bid,:aid,:dt,:op,:res,:pass,:nc,:notes)
    """), {
        "cid": checklist_id, "bid": business_id,
        "aid": body.get("audit_id") or None,
        "dt": body.get("run_date", __import__("datetime").date.today().isoformat()),
        "op": body.get("operator"), "res": body.get("results_json","[]"),
        "pass": 1 if body.get("overall_pass") else 0,
        "nc": nc, "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"run_id": row[0]}


@router.get("/checklists/{checklist_id}/runs")
def list_runs(checklist_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT RunID, AuditID, RunDate, Operator, OverallPass, NonConformances, Notes, CreatedAt
        FROM ComplianceChecklistRun
        WHERE ChecklistID=:cid AND BusinessID=:bid
        ORDER BY RunDate DESC
    """), {"cid": checklist_id, "bid": business_id}).fetchall()
    return [dict(zip(["run_id","audit_id","run_date","operator","overall_pass",
                      "non_conformances","notes","created_at"], r)) for r in rows]


# ── Corrective Actions ────────────────────────────────────────────────────────

@router.get("/corrective-actions")
def list_cars(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT ca.CARID, ca.AuditID, a.StandardName, ca.Finding, ca.Severity,
               ca.AssignedTo, ca.DueDate, ca.Status, ca.Resolution, ca.CreatedAt
        FROM CorrectiveAction ca
        LEFT JOIN ComplianceAudit a ON a.AuditID = ca.AuditID
        WHERE ca.BusinessID=:bid
        ORDER BY ca.DueDate ASC
    """), {"bid": business_id}).fetchall()
    return [dict(zip(
        ["car_id","audit_id","standard_name","finding","severity",
         "assigned_to","due_date","status","resolution","created_at"], r
    )) for r in rows]


@router.post("/corrective-actions")
def create_car(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO CorrectiveAction
            (BusinessID, AuditID, Finding, Severity, AssignedTo, DueDate, Status, Resolution)
        OUTPUT INSERTED.CARID
        VALUES (:bid,:aid,:finding,:sev,:assignee,:due,:status,:res)
    """), {
        "bid": business_id, "aid": body.get("audit_id") or None,
        "finding": body.get("finding",""), "sev": body.get("severity","Minor"),
        "assignee": body.get("assigned_to"), "due": body.get("due_date") or None,
        "status": body.get("status","Open"), "res": body.get("resolution"),
    }).fetchone()
    db.commit()
    return {"car_id": row[0]}


@router.patch("/corrective-actions/{car_id}/status")
def update_car(car_id: int, business_id: int = Query(...),
               db: Session = Depends(get_db), body: dict = None):
    body = body or {}
    db.execute(text("""
        UPDATE CorrectiveAction SET Status=:status, Resolution=:res
        WHERE CARID=:cid AND BusinessID=:bid
    """), {"cid": car_id, "bid": business_id,
           "status": body.get("status"), "res": body.get("resolution")})
    db.commit()
    return {"ok": True}


@router.delete("/corrective-actions/{car_id}")
def delete_car(car_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM CorrectiveAction WHERE CARID=:cid AND BusinessID=:bid"),
               {"cid": car_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary")
def get_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    r = db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM ComplianceAudit WHERE BusinessID=:bid AND Status='Scheduled') AS scheduled,
            (SELECT COUNT(*) FROM ComplianceAudit WHERE BusinessID=:bid AND Status='Passed') AS passed,
            (SELECT COUNT(*) FROM ComplianceAudit WHERE BusinessID=:bid AND Status='Failed') AS failed,
            (SELECT COUNT(*) FROM CorrectiveAction WHERE BusinessID=:bid AND Status='Open') AS open_cars,
            (SELECT COUNT(*) FROM CorrectiveAction WHERE BusinessID=:bid
             AND Status='Open' AND DueDate < GETDATE()) AS overdue_cars
    """), {"bid": business_id}).fetchone()
    return dict(zip(["scheduled","passed","failed","open_cars","overdue_cars"], r))
