"""Grant & Program Tracker — USDA/FSA programs, deadlines, applications."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine
from typing import Optional
from pydantic import BaseModel

router = APIRouter(prefix="/api/grants", tags=["grants"])

with engine.begin() as _c:
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='GrantPrograms')
        CREATE TABLE GrantPrograms (
            GrantID         INT IDENTITY(1,1) PRIMARY KEY,
            Title           NVARCHAR(300) NOT NULL,
            Description     NVARCHAR(MAX) NULL,
            Agency          NVARCHAR(200) NULL,
            ProgramType     VARCHAR(60) NULL,
            MaxAmount       DECIMAL(14,2) NULL,
            Deadline        DATE NULL,
            IsRecurring     BIT NOT NULL DEFAULT 0,
            Eligibility     NVARCHAR(MAX) NULL,
            ExternalUrl     NVARCHAR(500) NULL,
            IsActive        BIT NOT NULL DEFAULT 1,
            CreatedAt       DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='BusinessGrantTracking')
        CREATE TABLE BusinessGrantTracking (
            TrackingID      INT IDENTITY(1,1) PRIMARY KEY,
            GrantID         INT NOT NULL,
            BusinessID      INT NOT NULL,
            Status          VARCHAR(30) NOT NULL DEFAULT 'interested',
            Notes           NVARCHAR(MAX) NULL,
            AppliedDate     DATE NULL,
            ResultDate      DATE NULL,
            AmountReceived  DECIMAL(14,2) NULL,
            CreatedAt       DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))
    # Seed well-known programs if empty
    _c.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM GrantPrograms)
        BEGIN
            INSERT INTO GrantPrograms (Title,Agency,ProgramType,MaxAmount,IsRecurring,Eligibility,ExternalUrl,Description) VALUES
            ('EQIP — Environmental Quality Incentives Program','USDA NRCS','Conservation',450000,1,
             'Agricultural producers, including farmers, ranchers, and forest landowners',
             'https://www.nrcs.usda.gov/programs-initiatives/eqip-environmental-quality-incentives',
             'Provides financial and technical assistance to agricultural producers to address natural resource concerns and deliver environmental benefits.'),
            ('RCPP — Regional Conservation Partnership Program','USDA NRCS','Conservation',NULL,1,
             'Farmers, ranchers, forest landowners, and other agricultural producers',
             'https://www.nrcs.usda.gov/programs-initiatives/rcpp-regional-conservation-partnership-program',
             'Advances conservation of soil, water, wildlife, and related natural resources through partnerships.'),
            ('FSA Farm Loan Programs','USDA FSA','Loans',600000,1,
             'Beginning farmers, minority farmers, family farm operators',
             'https://www.fsa.usda.gov/programs-and-services/farm-loan-programs/index',
             'Provides direct loans and loan guarantees to family farm operators who are temporarily unable to obtain commercial credit.'),
            ('Beginning Farmer and Rancher Development Program','USDA NIFA','Training/Education',250000,1,
             'Organizations that train beginning farmers and ranchers',
             'https://www.nifa.usda.gov/grants/programs/beginning-farmer-rancher-development-program-bfrdp',
             'Supports education, mentoring, and technical assistance initiatives for beginning farmers.'),
            ('Value-Added Producer Grant (VAPG)','USDA Rural Development','Business Development',250000,1,
             'Independent agricultural producers, farmer cooperatives, agricultural producer groups',
             'https://www.rd.usda.gov/programs-services/business-programs/value-added-producer-grants',
             'Helps agricultural producers enter into value-added activities related to the processing and marketing of bio-based products.'),
            ('Organic Certification Cost Share Program','USDA AMS','Certification',500,1,
             'Certified organic producers and handlers',
             'https://www.ams.usda.gov/services/grants/occsp',
             'Provides cost share assistance to producers and handlers of agricultural products who are obtaining or renewing their USDA organic certification.')
        END
    """))


class GrantCreate(BaseModel):
    title: str
    description: Optional[str] = None
    agency: Optional[str] = None
    program_type: Optional[str] = None
    max_amount: Optional[float] = None
    deadline: Optional[str] = None
    is_recurring: bool = False
    eligibility: Optional[str] = None
    external_url: Optional[str] = None


def _ser(r): return dict(r._mapping)


@router.get("")
def browse_grants(
    program_type: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    filters = ["g.IsActive=1"]
    params: dict = {}
    if program_type:
        filters.append("g.ProgramType=:pt"); params["pt"] = program_type
    if q:
        filters.append("(g.Title LIKE :q OR g.Description LIKE :q OR g.Agency LIKE :q)")
        params["q"] = f"%{q}%"
    where = " AND ".join(filters)
    rows = db.execute(text(f"""
        SELECT * FROM GrantPrograms g WHERE {where}
        ORDER BY g.Deadline ASC, g.Title ASC
    """), params).fetchall()
    return [_ser(r) for r in rows]


@router.get("/business/{business_id}/tracking")
def my_tracking(business_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT t.*, g.Title AS GrantTitle, g.Agency, g.MaxAmount, g.Deadline, g.ExternalUrl
        FROM BusinessGrantTracking t
        JOIN GrantPrograms g ON g.GrantID=t.GrantID
        WHERE t.BusinessID=:b
        ORDER BY t.CreatedAt DESC
    """), {"b": business_id}).fetchall()
    return [_ser(r) for r in rows]


@router.post("/business/{business_id}/tracking")
def track_grant(business_id: int, body: dict, db: Session = Depends(get_db)):
    row = db.execute(text("""
        INSERT INTO BusinessGrantTracking (GrantID,BusinessID,Status,Notes,AppliedDate,ResultDate,AmountReceived)
        OUTPUT INSERTED.TrackingID
        VALUES (:gid,:bid,:status,:notes,:applied,:result,:amount)
    """), {
        "gid": body.get("grant_id"), "bid": business_id,
        "status": body.get("status", "interested"), "notes": body.get("notes"),
        "applied": body.get("applied_date"), "result": body.get("result_date"),
        "amount": body.get("amount_received"),
    }).fetchone()
    db.commit()
    return {"tracking_id": row[0]}


@router.patch("/business/{business_id}/tracking/{tracking_id}")
def update_tracking(business_id: int, tracking_id: int, body: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE BusinessGrantTracking SET
            Status=ISNULL(:status,Status),
            Notes=ISNULL(:notes,Notes),
            AppliedDate=ISNULL(:applied,AppliedDate),
            ResultDate=ISNULL(:result,ResultDate),
            AmountReceived=ISNULL(:amount,AmountReceived)
        WHERE TrackingID=:id AND BusinessID=:bid
    """), {
        "status": body.get("status"), "notes": body.get("notes"),
        "applied": body.get("applied_date"), "result": body.get("result_date"),
        "amount": body.get("amount_received"), "id": tracking_id, "bid": business_id,
    })
    db.commit()
    return {"ok": True}


@router.delete("/business/{business_id}/tracking/{tracking_id}")
def delete_tracking(business_id: int, tracking_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM BusinessGrantTracking WHERE TrackingID=:id AND BusinessID=:bid"), {"id": tracking_id, "bid": business_id})
    db.commit()
    return {"ok": True}
