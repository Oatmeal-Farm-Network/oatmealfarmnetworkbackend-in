"""Certifications Tracker — organic certs, GAP, USDA, custom."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine
from typing import Optional
from pydantic import BaseModel
from datetime import date, timedelta

router = APIRouter(prefix="/api/certifications", tags=["certifications"])

with engine.begin() as _c:
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='BusinessCertifications')
        CREATE TABLE BusinessCertifications (
            CertID          INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID      INT NOT NULL,
            CertName        NVARCHAR(200) NOT NULL,
            CertType        VARCHAR(60) NULL,
            IssuingBody     NVARCHAR(200) NULL,
            CertNumber      NVARCHAR(100) NULL,
            IssuedDate      DATE NULL,
            ExpiryDate      DATE NULL,
            Status          VARCHAR(30) NOT NULL DEFAULT 'active',
            Notes           NVARCHAR(500) NULL,
            DocumentUrl     NVARCHAR(500) NULL,
            CreatedAt       DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))


CERT_TYPES = [
    "USDA Organic", "Certified Naturally Grown", "GAP / GHP",
    "Non-GMO Project", "Animal Welfare Approved", "Certified Humane",
    "Food Safety Modernization Act (FSMA)", "State Organic",
    "Rainforest Alliance", "Fair Trade", "Other",
]


class CertCreate(BaseModel):
    cert_name: str
    cert_type: Optional[str] = None
    issuing_body: Optional[str] = None
    cert_number: Optional[str] = None
    issued_date: Optional[str] = None
    expiry_date: Optional[str] = None
    notes: Optional[str] = None
    document_url: Optional[str] = None


def _status(expiry_date_str: Optional[str]) -> str:
    if not expiry_date_str:
        return "active"
    try:
        exp = date.fromisoformat(str(expiry_date_str)[:10])
        today = date.today()
        if exp < today:
            return "expired"
        if exp <= today + timedelta(days=60):
            return "expiring_soon"
        return "active"
    except Exception:
        return "active"


def _ser(r) -> dict:
    d = dict(r._mapping)
    d["ComputedStatus"] = _status(d.get("ExpiryDate"))
    return d


@router.get("/types")
def cert_types():
    return CERT_TYPES


@router.get("/business/{business_id}")
def get_certs(business_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT * FROM BusinessCertifications WHERE BusinessID=:b ORDER BY ExpiryDate ASC
    """), {"b": business_id}).fetchall()
    return [_ser(r) for r in rows]


@router.post("/business/{business_id}")
def create_cert(business_id: int, cert: CertCreate, db: Session = Depends(get_db)):
    row = db.execute(text("""
        INSERT INTO BusinessCertifications
            (BusinessID,CertName,CertType,IssuingBody,CertNumber,IssuedDate,ExpiryDate,Notes,DocumentUrl)
        OUTPUT INSERTED.CertID
        VALUES (:b,:name,:type,:body,:num,:issued,:expiry,:notes,:doc)
    """), {
        "b": business_id, "name": cert.cert_name, "type": cert.cert_type,
        "body": cert.issuing_body, "num": cert.cert_number,
        "issued": cert.issued_date, "expiry": cert.expiry_date,
        "notes": cert.notes, "doc": cert.document_url,
    }).fetchone()
    db.commit()
    return {"cert_id": row[0]}


@router.put("/{cert_id}")
def update_cert(cert_id: int, cert: CertCreate, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE BusinessCertifications SET
            CertName=:name,CertType=:type,IssuingBody=:body,CertNumber=:num,
            IssuedDate=:issued,ExpiryDate=:expiry,Notes=:notes,DocumentUrl=:doc
        WHERE CertID=:id
    """), {
        "name": cert.cert_name, "type": cert.cert_type, "body": cert.issuing_body,
        "num": cert.cert_number, "issued": cert.issued_date, "expiry": cert.expiry_date,
        "notes": cert.notes, "doc": cert.document_url, "id": cert_id,
    })
    db.commit()
    return {"ok": True}


@router.delete("/{cert_id}")
def delete_cert(cert_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM BusinessCertifications WHERE CertID=:id"), {"id": cert_id})
    db.commit()
    return {"ok": True}


@router.get("/business/{business_id}/expiring")
def expiring_soon(business_id: int, days: int = 90, db: Session = Depends(get_db)):
    cutoff = (date.today() + timedelta(days=days)).isoformat()
    rows = db.execute(text("""
        SELECT * FROM BusinessCertifications
        WHERE BusinessID=:b AND ExpiryDate IS NOT NULL AND ExpiryDate <= :cutoff
        ORDER BY ExpiryDate ASC
    """), {"b": business_id, "cutoff": cutoff}).fetchall()
    return [_ser(r) for r in rows]
