"""Grant & Program Tracker — India farmer schemes (PM-KISAN, PMFBY, KCC, FPO)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine
from typing import Optional
from pydantic import BaseModel
from auth import get_current_user, assert_business_access

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
            (N'PM-KISAN — Pradhan Mantri Kisan Samman Nidhi',N'Ministry of Agriculture',N'Income support',6000,1,
             N'Small and marginal landholding farmer families (subject to scheme exclusions)',
             N'https://pmkisan.gov.in/',
             N'₹6,000 per year in three instalments of ₹2,000 credited to the farmer''s bank account.'),
            (N'PMFBY — Pradhan Mantri Fasal Bima Yojana',N'Ministry of Agriculture',N'Crop insurance',NULL,1,
             N'Farmers growing notified crops in notified areas; loanee farmers typically auto-covered',
             N'https://pmfby.gov.in/',
             N'Crop insurance against yield loss from natural calamities, pests, and diseases. Premiums are subsidised.'),
            (N'Kisan Credit Card (KCC)',N'Ministry of Agriculture / Banks',N'Loans',NULL,1,
             N'Farmers, tenant farmers, sharecroppers, SHGs, and FPOs engaged in agriculture or allied activity',
             N'https://www.nabard.org/content1.aspx?id=572',
             N'Short-term credit for crop inputs, working capital, and allied activities at concessional interest.'),
            (N'Soil Health Card',N'DAC&FW',N'Soil / inputs',NULL,1,
             N'All farmers; apply via state agriculture department / CSC',
             N'https://soilhealth.dac.gov.in/',
             N'Free soil testing and nutrient recommendations. Upload or request a card for your plot.'),
            (N'eNAM — National Agriculture Market',N'MoA / SFAC',N'Market access',NULL,1,
             N'Farmers, FPOs, and traders registered at a linked mandi',
             N'https://www.enam.gov.in/',
             N'Pan-India electronic trading of farm produce with quality assaying and online payment.'),
            (N'PM-KUSUM — Solar pumps & grid',N'Ministry of New and Renewable Energy',N'Energy / irrigation',NULL,1,
             N'Farmers, FPOs, panchayats, and cooperatives installing solar pumps or solarising pumps',
             N'https://pmkusum.mnre.gov.in/',
             N'Subsidy for standalone solar pumps and solarisation of existing grid-connected pumps.'),
            (N'FPO formation & promotion (10,000 FPOs)',N'MoA / NABARD / SFAC / NCDC',N'FPO / cooperative',NULL,1,
             N'Farmer groups forming or operating a Farmer Producer Organisation',
             N'https://www.nabard.org/',
             N'Handholding, equity grant, and credit guarantee support for Farmer Producer Organisations.'),
            (N'RKVY — Rashtriya Krishi Vikas Yojana',N'Ministry of Agriculture',N'State agri development',NULL,1,
             N'State-implemented; farmers access via state agriculture department projects',
             N'https://rkvy.nic.in/',
             N'State-level infrastructure, value-chain, and productivity projects. Check your state window.'),
            (N'National Mission on Natural Farming',N'Ministry of Agriculture',N'Sustainable farming',NULL,1,
             N'Farmers willing to adopt natural / chemical-free practices',
             N'https://naturalfarming.dac.gov.in/',
             N'Support for natural farming clusters, bio-inputs, and training.'),
            (N'NHB / MIDH horticulture assistance',N'National Horticulture Board',N'Horticulture',NULL,1,
             N'Horticulture growers, FPOs, and nurseries meeting scheme guidelines',
             N'https://www.nhb.gov.in/',
             N'Assistance for planting material, protected cultivation, packhouses, and cold chain.')
        END
    """))
    # India fork: hide leftover USDA programs restored from USA backup
    _c.execute(text("""
        UPDATE GrantPrograms SET IsActive = 0
        WHERE IsActive = 1 AND (
            Agency LIKE 'USDA%' OR Agency LIKE '%NRCS%' OR Agency LIKE '%NIFA%'
            OR Title LIKE 'EQIP%' OR Title LIKE 'RCPP%' OR Title LIKE 'FSA%'
            OR Title LIKE 'Value-Added Producer%' OR Title LIKE 'Organic Certification Cost Share%'
            OR Title LIKE 'Beginning Farmer and Rancher%'
        )
    """))
    # Insert India schemes if they were never seeded (table already had USDA rows)
    _c.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM GrantPrograms WHERE Title LIKE N'PM-KISAN%')
        BEGIN
            INSERT INTO GrantPrograms (Title,Agency,ProgramType,MaxAmount,IsRecurring,Eligibility,ExternalUrl,Description) VALUES
            (N'PM-KISAN — Pradhan Mantri Kisan Samman Nidhi',N'Ministry of Agriculture',N'Income support',6000,1,
             N'Small and marginal landholding farmer families (subject to scheme exclusions)',
             N'https://pmkisan.gov.in/',
             N'₹6,000 per year in three instalments of ₹2,000 credited to the farmer''s bank account.'),
            (N'PMFBY — Pradhan Mantri Fasal Bima Yojana',N'Ministry of Agriculture',N'Crop insurance',NULL,1,
             N'Farmers growing notified crops in notified areas; loanee farmers typically auto-covered',
             N'https://pmfby.gov.in/',
             N'Crop insurance against yield loss from natural calamities, pests, and diseases. Premiums are subsidised.'),
            (N'Kisan Credit Card (KCC)',N'Ministry of Agriculture / Banks',N'Loans',NULL,1,
             N'Farmers, tenant farmers, sharecroppers, SHGs, and FPOs engaged in agriculture or allied activity',
             N'https://www.nabard.org/content1.aspx?id=572',
             N'Short-term credit for crop inputs, working capital, and allied activities at concessional interest.'),
            (N'Soil Health Card',N'DAC&FW',N'Soil / inputs',NULL,1,
             N'All farmers; apply via state agriculture department / CSC',
             N'https://soilhealth.dac.gov.in/',
             N'Free soil testing and nutrient recommendations. Upload or request a card for your plot.'),
            (N'eNAM — National Agriculture Market',N'MoA / SFAC',N'Market access',NULL,1,
             N'Farmers, FPOs, and traders registered at a linked mandi',
             N'https://www.enam.gov.in/',
             N'Pan-India electronic trading of farm produce with quality assaying and online payment.'),
            (N'PM-KUSUM — Solar pumps & grid',N'Ministry of New and Renewable Energy',N'Energy / irrigation',NULL,1,
             N'Farmers, FPOs, panchayats, and cooperatives installing solar pumps or solarising pumps',
             N'https://pmkusum.mnre.gov.in/',
             N'Subsidy for standalone solar pumps and solarisation of existing grid-connected pumps.'),
            (N'FPO formation & promotion (10,000 FPOs)',N'MoA / NABARD / SFAC / NCDC',N'FPO / cooperative',NULL,1,
             N'Farmer groups forming or operating a Farmer Producer Organisation',
             N'https://www.nabard.org/',
             N'Handholding, equity grant, and credit guarantee support for Farmer Producer Organisations.'),
            (N'RKVY — Rashtriya Krishi Vikas Yojana',N'Ministry of Agriculture',N'State agri development',NULL,1,
             N'State-implemented; farmers access via state agriculture department projects',
             N'https://rkvy.nic.in/',
             N'State-level infrastructure, value-chain, and productivity projects. Check your state window.'),
            (N'National Mission on Natural Farming',N'Ministry of Agriculture',N'Sustainable farming',NULL,1,
             N'Farmers willing to adopt natural / chemical-free practices',
             N'https://naturalfarming.dac.gov.in/',
             N'Support for natural farming clusters, bio-inputs, and training.'),
            (N'NHB / MIDH horticulture assistance',N'National Horticulture Board',N'Horticulture',NULL,1,
             N'Horticulture growers, FPOs, and nurseries meeting scheme guidelines',
             N'https://www.nhb.gov.in/',
             N'Assistance for planting material, protected cultivation, packhouses, and cold chain.')
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
def my_tracking(business_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    assert_business_access(db, user, business_id)
    rows = db.execute(text("""
        SELECT t.*, g.Title AS GrantTitle, g.Agency, g.MaxAmount, g.Deadline, g.ExternalUrl
        FROM BusinessGrantTracking t
        JOIN GrantPrograms g ON g.GrantID=t.GrantID
        WHERE t.BusinessID=:b
        ORDER BY t.CreatedAt DESC
    """), {"b": business_id}).fetchall()
    return [_ser(r) for r in rows]


@router.post("/business/{business_id}/tracking")
def track_grant(business_id: int, body: dict, db: Session = Depends(get_db), user=Depends(get_current_user)):
    assert_business_access(db, user, business_id)
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
def update_tracking(business_id: int, tracking_id: int, body: dict, db: Session = Depends(get_db), user=Depends(get_current_user)):
    assert_business_access(db, user, business_id)
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
def delete_tracking(business_id: int, tracking_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    assert_business_access(db, user, business_id)
    db.execute(text("DELETE FROM BusinessGrantTracking WHERE TrackingID=:id AND BusinessID=:bid"), {"id": tracking_id, "bid": business_id})
    db.commit()
    return {"ok": True}
