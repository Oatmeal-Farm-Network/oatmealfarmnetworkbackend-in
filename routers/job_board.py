"""Job Board — farm labor listings and applications."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine
from typing import Optional
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/api/jobs", tags=["job-board"])

with engine.begin() as _c:
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='JobListings')
        CREATE TABLE JobListings (
            JobID           INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID      INT NOT NULL,
            Title           NVARCHAR(200) NOT NULL,
            Description     NVARCHAR(MAX) NULL,
            JobType         VARCHAR(40) NOT NULL DEFAULT 'seasonal',
            Category        VARCHAR(60) NULL,
            PayRate         DECIMAL(10,2) NULL,
            PayPeriod       VARCHAR(20) NULL,
            HousingProvided BIT NOT NULL DEFAULT 0,
            MealsProvided   BIT NOT NULL DEFAULT 0,
            SeasonStart     DATE NULL,
            SeasonEnd       DATE NULL,
            ApplyDeadline   DATE NULL,
            HoursPerWeek    INT NULL,
            City            NVARCHAR(100) NULL,
            StateProvince   NVARCHAR(60) NULL,
            ContactEmail    NVARCHAR(200) NULL,
            IsActive        BIT NOT NULL DEFAULT 1,
            CreatedAt       DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='JobApplications')
        CREATE TABLE JobApplications (
            ApplicationID   INT IDENTITY(1,1) PRIMARY KEY,
            JobID           INT NOT NULL,
            PeopleID        INT NULL,
            ApplicantName   NVARCHAR(150) NOT NULL,
            ApplicantEmail  NVARCHAR(200) NOT NULL,
            Phone           NVARCHAR(30) NULL,
            Message         NVARCHAR(MAX) NULL,
            Status          VARCHAR(30) NOT NULL DEFAULT 'pending',
            CreatedAt       DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))


class JobCreate(BaseModel):
    title: str
    description: Optional[str] = None
    job_type: str = 'seasonal'
    category: Optional[str] = None
    pay_rate: Optional[float] = None
    pay_period: Optional[str] = None
    housing_provided: bool = False
    meals_provided: bool = False
    season_start: Optional[str] = None
    season_end: Optional[str] = None
    apply_deadline: Optional[str] = None
    hours_per_week: Optional[int] = None
    city: Optional[str] = None
    state_province: Optional[str] = None
    contact_email: Optional[str] = None


def _ser(r) -> dict:
    return dict(r._mapping)


@router.get("")
def browse_jobs(
    state: Optional[str] = None,
    job_type: Optional[str] = None,
    category: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    filters = ["j.IsActive=1"]
    params: dict = {}
    if state:
        filters.append("j.StateProvince=:state"); params["state"] = state
    if job_type:
        filters.append("j.JobType=:jt"); params["jt"] = job_type
    if category:
        filters.append("j.Category=:cat"); params["cat"] = category
    if q:
        filters.append("(j.Title LIKE :q OR j.Description LIKE :q)"); params["q"] = f"%{q}%"
    where = " AND ".join(filters)
    rows = db.execute(text(f"""
        SELECT j.*, b.BusinessName
        FROM JobListings j
        LEFT JOIN Business b ON b.BusinessID=j.BusinessID
        WHERE {where}
        ORDER BY j.CreatedAt DESC
    """), params).fetchall()
    return [_ser(r) for r in rows]


@router.get("/business/{business_id}")
def my_jobs(business_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT j.*,
               (SELECT COUNT(*) FROM JobApplications a WHERE a.JobID=j.JobID) AS ApplicationCount
        FROM JobListings j WHERE j.BusinessID=:b AND j.IsActive=1 ORDER BY j.CreatedAt DESC
    """), {"b": business_id}).fetchall()
    return [_ser(r) for r in rows]


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT j.*, b.BusinessName FROM JobListings j
        LEFT JOIN Business b ON b.BusinessID=j.BusinessID
        WHERE j.JobID=:id
    """), {"id": job_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return _ser(row)


@router.post("/business/{business_id}")
def create_job(business_id: int, job: JobCreate, db: Session = Depends(get_db)):
    row = db.execute(text("""
        INSERT INTO JobListings
            (BusinessID,Title,Description,JobType,Category,PayRate,PayPeriod,
             HousingProvided,MealsProvided,SeasonStart,SeasonEnd,ApplyDeadline,
             HoursPerWeek,City,StateProvince,ContactEmail)
        OUTPUT INSERTED.JobID
        VALUES (:b,:title,:desc,:jt,:cat,:pay,:pp,:housing,:meals,
                :ss,:se,:ad,:hrs,:city,:state,:email)
    """), {
        "b": business_id, "title": job.title, "desc": job.description,
        "jt": job.job_type, "cat": job.category, "pay": job.pay_rate,
        "pp": job.pay_period, "housing": 1 if job.housing_provided else 0,
        "meals": 1 if job.meals_provided else 0,
        "ss": job.season_start, "se": job.season_end, "ad": job.apply_deadline,
        "hrs": job.hours_per_week, "city": job.city, "state": job.state_province,
        "email": job.contact_email,
    }).fetchone()
    db.commit()
    return {"job_id": row[0]}


@router.put("/{job_id}")
def update_job(job_id: int, job: JobCreate, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE JobListings SET
            Title=:title, Description=:desc, JobType=:jt, Category=:cat,
            PayRate=:pay, PayPeriod=:pp, HousingProvided=:housing, MealsProvided=:meals,
            SeasonStart=:ss, SeasonEnd=:se, ApplyDeadline=:ad,
            HoursPerWeek=:hrs, City=:city, StateProvince=:state, ContactEmail=:email
        WHERE JobID=:id
    """), {
        "title": job.title, "desc": job.description, "jt": job.job_type,
        "cat": job.category, "pay": job.pay_rate, "pp": job.pay_period,
        "housing": 1 if job.housing_provided else 0,
        "meals": 1 if job.meals_provided else 0,
        "ss": job.season_start, "se": job.season_end, "ad": job.apply_deadline,
        "hrs": job.hours_per_week, "city": job.city, "state": job.state_province,
        "email": job.contact_email, "id": job_id,
    })
    db.commit()
    return {"ok": True}


@router.delete("/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE JobListings SET IsActive=0 WHERE JobID=:id"), {"id": job_id})
    db.commit()
    return {"ok": True}


@router.post("/{job_id}/apply")
def apply(job_id: int, body: dict, db: Session = Depends(get_db)):
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip()
    if not name or not email:
        raise HTTPException(status_code=400, detail="Name and email required")
    row = db.execute(text("""
        INSERT INTO JobApplications (JobID, PeopleID, ApplicantName, ApplicantEmail, Phone, Message)
        OUTPUT INSERTED.ApplicationID
        VALUES (:jid, :pid, :name, :email, :phone, :msg)
    """), {
        "jid": job_id, "pid": body.get("people_id"),
        "name": name, "email": email,
        "phone": body.get("phone"), "msg": body.get("message"),
    }).fetchone()
    db.commit()
    return {"application_id": row[0]}


@router.get("/{job_id}/applications")
def get_applications(job_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT * FROM JobApplications WHERE JobID=:jid ORDER BY CreatedAt DESC
    """), {"jid": job_id}).fetchall()
    return [_ser(r) for r in rows]
