from fastapi import APIRouter, Depends, Query
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

router = APIRouter(prefix="/api/agro-consult", tags=["agro_consultations"])

VISIT_TYPES = ['General Assessment','Soil Health','Pest & Disease','Irrigation','Fertilisation',
               'Spray Program','Variety Selection','Yield Analysis','Regulatory','Other']
CONSULT_STATUSES = ['Scheduled','Completed','Cancelled']
REC_PRIORITIES = ['Low','Medium','High','Critical']
REC_STATUSES = ['Open','In Progress','Implemented','Declined']


def _ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='AgroConsultation' AND xtype='U')
        CREATE TABLE AgroConsultation (
            ConsultationID    INT IDENTITY PRIMARY KEY,
            BusinessID        INT NOT NULL,
            ConsultantName    NVARCHAR(150) NOT NULL,
            ConsultantCompany NVARCHAR(150),
            ConsultantEmail   NVARCHAR(150),
            ConsultantPhone   NVARCHAR(50),
            VisitDate         DATE NOT NULL,
            VisitType         NVARCHAR(80) DEFAULT 'General Assessment',
            FieldsVisited     NVARCHAR(500),
            Findings          NVARCHAR(MAX),
            Recommendations   NVARCHAR(MAX),
            FollowUpDate      DATE,
            Status            NVARCHAR(30) DEFAULT 'Scheduled',
            Notes             NVARCHAR(500),
            CreatedAt         DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='AgroRecommendation' AND xtype='U')
        CREATE TABLE AgroRecommendation (
            RecommendationID INT IDENTITY PRIMARY KEY,
            ConsultationID   INT NOT NULL,
            BusinessID       INT NOT NULL,
            Category         NVARCHAR(80),
            Description      NVARCHAR(MAX) NOT NULL,
            Priority         NVARCHAR(20) DEFAULT 'Medium',
            DueDate          DATE,
            Status           NVARCHAR(30) DEFAULT 'Open',
            Notes            NVARCHAR(500),
            CreatedAt        DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


# ── Consultations ─────────────────────────────────────────────────────────────

@router.get("/consultations")
def list_consultations(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT c.ConsultationID, c.ConsultantName, c.ConsultantCompany,
               c.VisitDate, c.VisitType, c.FieldsVisited, c.Status, c.FollowUpDate,
               c.Findings, c.Notes,
               (SELECT COUNT(*) FROM AgroRecommendation WHERE ConsultationID=c.ConsultationID) AS rec_count,
               (SELECT COUNT(*) FROM AgroRecommendation WHERE ConsultationID=c.ConsultationID
                AND Status='Open') AS open_recs
        FROM AgroConsultation c
        WHERE c.BusinessID=:bid
        ORDER BY c.VisitDate DESC
    """), {"bid": business_id}).fetchall()
    return [dict(zip(
        ["consultation_id","consultant_name","consultant_company","visit_date","visit_type",
         "fields_visited","status","follow_up_date","findings","notes","rec_count","open_recs"], r
    )) for r in rows]


@router.post("/consultations")
def create_consultation(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO AgroConsultation
            (BusinessID, ConsultantName, ConsultantCompany, ConsultantEmail, ConsultantPhone,
             VisitDate, VisitType, FieldsVisited, Findings, Recommendations, FollowUpDate, Status, Notes)
        OUTPUT INSERTED.ConsultationID
        VALUES (:bid,:name,:company,:email,:phone,:dt,:type,:fields,:findings,:recs,:followup,:status,:notes)
    """), {
        "bid": business_id, "name": body.get("consultant_name",""),
        "company": body.get("consultant_company"), "email": body.get("consultant_email"),
        "phone": body.get("consultant_phone"), "dt": body.get("visit_date"),
        "type": body.get("visit_type","General Assessment"),
        "fields": body.get("fields_visited"), "findings": body.get("findings"),
        "recs": body.get("recommendations"), "followup": body.get("follow_up_date") or None,
        "status": body.get("status","Scheduled"), "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"consultation_id": row[0]}


@router.put("/consultations/{consultation_id}")
def update_consultation(consultation_id: int, business_id: int = Query(...),
                        db: Session = Depends(get_db), body: dict = None):
    body = body or {}
    db.execute(text("""
        UPDATE AgroConsultation SET
            ConsultantName=:name, ConsultantCompany=:company,
            ConsultantEmail=:email, ConsultantPhone=:phone,
            VisitDate=:dt, VisitType=:type, FieldsVisited=:fields,
            Findings=:findings, Recommendations=:recs,
            FollowUpDate=:followup, Status=:status, Notes=:notes
        WHERE ConsultationID=:cid AND BusinessID=:bid
    """), {
        "cid": consultation_id, "bid": business_id, "name": body.get("consultant_name",""),
        "company": body.get("consultant_company"), "email": body.get("consultant_email"),
        "phone": body.get("consultant_phone"), "dt": body.get("visit_date"),
        "type": body.get("visit_type","General Assessment"),
        "fields": body.get("fields_visited"), "findings": body.get("findings"),
        "recs": body.get("recommendations"), "followup": body.get("follow_up_date") or None,
        "status": body.get("status","Scheduled"), "notes": body.get("notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/consultations/{consultation_id}")
def delete_consultation(consultation_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM AgroRecommendation WHERE ConsultationID=:cid AND BusinessID=:bid"),
               {"cid": consultation_id, "bid": business_id})
    db.execute(text("DELETE FROM AgroConsultation WHERE ConsultationID=:cid AND BusinessID=:bid"),
               {"cid": consultation_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Recommendations ───────────────────────────────────────────────────────────

@router.get("/consultations/{consultation_id}/recommendations")
def list_recommendations(consultation_id: int, business_id: int = Query(...),
                         db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT RecommendationID, Category, Description, Priority, DueDate, Status, Notes
        FROM AgroRecommendation
        WHERE ConsultationID=:cid AND BusinessID=:bid
        ORDER BY CASE Priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2
                               WHEN 'Medium' THEN 3 ELSE 4 END, DueDate
    """), {"cid": consultation_id, "bid": business_id}).fetchall()
    return [dict(zip(
        ["recommendation_id","category","description","priority","due_date","status","notes"], r
    )) for r in rows]


@router.get("/recommendations")
def list_all_recommendations(business_id: int = Query(...),
                              status: Optional[str] = Query(None),
                              db: Session = Depends(get_db)):
    _ensure_tables(db)
    if status:
        rows = db.execute(text("""
            SELECT r.RecommendationID, r.ConsultationID, c.ConsultantName, c.VisitDate,
                   r.Category, r.Description, r.Priority, r.DueDate, r.Status, r.Notes
            FROM AgroRecommendation r
            JOIN AgroConsultation c ON c.ConsultationID = r.ConsultationID
            WHERE r.BusinessID=:bid AND r.Status=:status
            ORDER BY CASE r.Priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2
                                     WHEN 'Medium' THEN 3 ELSE 4 END, r.DueDate
        """), {"bid": business_id, "status": status}).fetchall()
    else:
        rows = db.execute(text("""
            SELECT r.RecommendationID, r.ConsultationID, c.ConsultantName, c.VisitDate,
                   r.Category, r.Description, r.Priority, r.DueDate, r.Status, r.Notes
            FROM AgroRecommendation r
            JOIN AgroConsultation c ON c.ConsultationID = r.ConsultationID
            WHERE r.BusinessID=:bid AND r.Status != 'Declined'
            ORDER BY CASE r.Priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2
                                     WHEN 'Medium' THEN 3 ELSE 4 END, r.DueDate
        """), {"bid": business_id}).fetchall()
    return [dict(zip(
        ["recommendation_id","consultation_id","consultant_name","visit_date",
         "category","description","priority","due_date","status","notes"], r
    )) for r in rows]


@router.post("/recommendations")
def add_recommendation(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO AgroRecommendation
            (ConsultationID, BusinessID, Category, Description, Priority, DueDate, Status, Notes)
        OUTPUT INSERTED.RecommendationID
        VALUES (:cid,:bid,:cat,:desc,:priority,:due,:status,:notes)
    """), {
        "cid": body.get("consultation_id"), "bid": business_id,
        "cat": body.get("category"), "desc": body.get("description",""),
        "priority": body.get("priority","Medium"), "due": body.get("due_date") or None,
        "status": body.get("status","Open"), "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"recommendation_id": row[0]}


@router.patch("/recommendations/{recommendation_id}/status")
def update_recommendation_status(recommendation_id: int, business_id: int = Query(...),
                                  db: Session = Depends(get_db), body: dict = None):
    body = body or {}
    db.execute(text("""
        UPDATE AgroRecommendation SET Status=:status
        WHERE RecommendationID=:rid AND BusinessID=:bid
    """), {"rid": recommendation_id, "bid": business_id, "status": body.get("status","Open")})
    db.commit()
    return {"ok": True}


@router.delete("/recommendations/{recommendation_id}")
def delete_recommendation(recommendation_id: int, business_id: int = Query(...),
                          db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM AgroRecommendation WHERE RecommendationID=:rid AND BusinessID=:bid"),
               {"rid": recommendation_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary")
def get_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    r = db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM AgroConsultation WHERE BusinessID=:bid) AS total_consultations,
            (SELECT COUNT(*) FROM AgroConsultation WHERE BusinessID=:bid
             AND VisitDate >= DATEADD(month,-6,GETDATE())) AS consultations_6m,
            (SELECT COUNT(*) FROM AgroRecommendation WHERE BusinessID=:bid AND Status='Open') AS open_recs,
            (SELECT COUNT(*) FROM AgroRecommendation WHERE BusinessID=:bid
             AND Status='Open' AND DueDate < CAST(GETDATE() AS DATE)) AS overdue_recs,
            (SELECT COUNT(*) FROM AgroConsultation WHERE BusinessID=:bid
             AND FollowUpDate >= CAST(GETDATE() AS DATE)
             AND FollowUpDate < DATEADD(day,14,GETDATE())) AS upcoming_followups
    """), {"bid": business_id}).fetchone()
    return dict(zip(
        ["total_consultations","consultations_6m","open_recs","overdue_recs","upcoming_followups"], r
    ))
