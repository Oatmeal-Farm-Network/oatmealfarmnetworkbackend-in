from fastapi import APIRouter, Depends, Query
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

router = APIRouter(prefix="/api/buyer-crm", tags=["buyer_crm"])


def _ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='BuyerContact' AND xtype='U')
        CREATE TABLE BuyerContact (
            ContactID     INT IDENTITY PRIMARY KEY,
            BusinessID    INT NOT NULL,
            ContactName   NVARCHAR(150) NOT NULL,
            Company       NVARCHAR(150),
            Email         NVARCHAR(200),
            Phone         NVARCHAR(50),
            BuyerType     NVARCHAR(50) DEFAULT 'Wholesale',
            PreferredCrops NVARCHAR(500),
            Notes         NVARCHAR(MAX),
            CreatedAt     DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='BuyerInteraction' AND xtype='U')
        CREATE TABLE BuyerInteraction (
            InteractionID   INT IDENTITY PRIMARY KEY,
            BusinessID      INT NOT NULL,
            ContactID       INT NOT NULL,
            InteractionDate DATE NOT NULL,
            InteractionType NVARCHAR(50) DEFAULT 'Note',
            Notes           NVARCHAR(MAX),
            FollowUpDate    DATE,
            CreatedAt       DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name='BuyerPricingAgreement' AND xtype='U')
        CREATE TABLE BuyerPricingAgreement (
            AgreementID  INT IDENTITY PRIMARY KEY,
            BusinessID   INT NOT NULL,
            ContactID    INT NOT NULL,
            CropName     NVARCHAR(100) NOT NULL,
            Variety      NVARCHAR(100),
            PricePerUnit DECIMAL(10,2),
            Unit         NVARCHAR(30) DEFAULT 'kg',
            Season       NVARCHAR(50),
            ValidFrom    DATE,
            ValidTo      DATE,
            Notes        NVARCHAR(500),
            CreatedAt    DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


# ── Contacts ──────────────────────────────────────────────────────────────────

@router.get("/contacts")
def list_contacts(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT ContactID, ContactName, Company, Email, Phone, BuyerType,
               PreferredCrops, Notes, CreatedAt
        FROM BuyerContact
        WHERE BusinessID = :bid
        ORDER BY ContactName
    """), {"bid": business_id}).fetchall()
    return [dict(zip(
        ["contact_id","contact_name","company","email","phone","buyer_type",
         "preferred_crops","notes","created_at"], r
    )) for r in rows]


@router.post("/contacts")
def create_contact(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO BuyerContact
            (BusinessID, ContactName, Company, Email, Phone, BuyerType, PreferredCrops, Notes)
        OUTPUT INSERTED.ContactID
        VALUES (:bid, :name, :company, :email, :phone, :btype, :crops, :notes)
    """), {
        "bid": business_id, "name": body.get("contact_name",""),
        "company": body.get("company"), "email": body.get("email"),
        "phone": body.get("phone"), "btype": body.get("buyer_type","Wholesale"),
        "crops": body.get("preferred_crops"), "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"contact_id": row[0]}


@router.put("/contacts/{contact_id}")
def update_contact(contact_id: int, business_id: int = Query(...),
                   db: Session = Depends(get_db), body: dict = None):
    body = body or {}
    db.execute(text("""
        UPDATE BuyerContact SET
            ContactName=:name, Company=:company, Email=:email, Phone=:phone,
            BuyerType=:btype, PreferredCrops=:crops, Notes=:notes
        WHERE ContactID=:cid AND BusinessID=:bid
    """), {
        "cid": contact_id, "bid": business_id,
        "name": body.get("contact_name",""), "company": body.get("company"),
        "email": body.get("email"), "phone": body.get("phone"),
        "btype": body.get("buyer_type","Wholesale"),
        "crops": body.get("preferred_crops"), "notes": body.get("notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/contacts/{contact_id}")
def delete_contact(contact_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM BuyerInteraction WHERE ContactID=:cid AND BusinessID=:bid"),
               {"cid": contact_id, "bid": business_id})
    db.execute(text("DELETE FROM BuyerPricingAgreement WHERE ContactID=:cid AND BusinessID=:bid"),
               {"cid": contact_id, "bid": business_id})
    db.execute(text("DELETE FROM BuyerContact WHERE ContactID=:cid AND BusinessID=:bid"),
               {"cid": contact_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Interactions ──────────────────────────────────────────────────────────────

@router.get("/interactions")
def list_interactions(business_id: int = Query(...),
                      contact_id: Optional[int] = Query(None),
                      db: Session = Depends(get_db)):
    _ensure_tables(db)
    if contact_id:
        rows = db.execute(text("""
            SELECT i.InteractionID, i.ContactID, c.ContactName, c.Company,
                   i.InteractionDate, i.InteractionType, i.Notes, i.FollowUpDate, i.CreatedAt
            FROM BuyerInteraction i
            JOIN BuyerContact c ON c.ContactID = i.ContactID
            WHERE i.BusinessID=:bid AND i.ContactID=:cid
            ORDER BY i.InteractionDate DESC
        """), {"bid": business_id, "cid": contact_id}).fetchall()
    else:
        rows = db.execute(text("""
            SELECT TOP 100 i.InteractionID, i.ContactID, c.ContactName, c.Company,
                   i.InteractionDate, i.InteractionType, i.Notes, i.FollowUpDate, i.CreatedAt
            FROM BuyerInteraction i
            JOIN BuyerContact c ON c.ContactID = i.ContactID
            WHERE i.BusinessID=:bid
            ORDER BY i.InteractionDate DESC
        """), {"bid": business_id}).fetchall()
    return [dict(zip(
        ["interaction_id","contact_id","contact_name","company",
         "interaction_date","interaction_type","notes","follow_up_date","created_at"], r
    )) for r in rows]


@router.post("/interactions")
def create_interaction(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO BuyerInteraction
            (BusinessID, ContactID, InteractionDate, InteractionType, Notes, FollowUpDate)
        OUTPUT INSERTED.InteractionID
        VALUES (:bid, :cid, :dt, :itype, :notes, :fup)
    """), {
        "bid": business_id, "cid": body.get("contact_id"),
        "dt": body.get("interaction_date"), "itype": body.get("interaction_type","Note"),
        "notes": body.get("notes"), "fup": body.get("follow_up_date") or None,
    }).fetchone()
    db.commit()
    return {"interaction_id": row[0]}


@router.delete("/interactions/{interaction_id}")
def delete_interaction(interaction_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM BuyerInteraction WHERE InteractionID=:iid AND BusinessID=:bid"),
               {"iid": interaction_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Pricing Agreements ────────────────────────────────────────────────────────

@router.get("/pricing")
def list_pricing(business_id: int = Query(...),
                 contact_id: Optional[int] = Query(None),
                 db: Session = Depends(get_db)):
    _ensure_tables(db)
    clause = "AND p.ContactID=:cid" if contact_id else ""
    rows = db.execute(text(f"""
        SELECT p.AgreementID, p.ContactID, c.ContactName, c.Company,
               p.CropName, p.Variety, p.PricePerUnit, p.Unit, p.Season,
               p.ValidFrom, p.ValidTo, p.Notes
        FROM BuyerPricingAgreement p
        JOIN BuyerContact c ON c.ContactID = p.ContactID
        WHERE p.BusinessID=:bid {clause}
        ORDER BY p.CropName
    """), {"bid": business_id, "cid": contact_id}).fetchall()
    return [dict(zip(
        ["agreement_id","contact_id","contact_name","company","crop_name","variety",
         "price_per_unit","unit","season","valid_from","valid_to","notes"], r
    )) for r in rows]


@router.post("/pricing")
def create_pricing(business_id: int = Query(...), db: Session = Depends(get_db), body: dict = None):
    _ensure_tables(db)
    body = body or {}
    row = db.execute(text("""
        INSERT INTO BuyerPricingAgreement
            (BusinessID, ContactID, CropName, Variety, PricePerUnit, Unit, Season, ValidFrom, ValidTo, Notes)
        OUTPUT INSERTED.AgreementID
        VALUES (:bid,:cid,:crop,:variety,:price,:unit,:season,:vf,:vt,:notes)
    """), {
        "bid": business_id, "cid": body.get("contact_id"),
        "crop": body.get("crop_name",""), "variety": body.get("variety"),
        "price": body.get("price_per_unit"), "unit": body.get("unit","kg"),
        "season": body.get("season"), "vf": body.get("valid_from") or None,
        "vt": body.get("valid_to") or None, "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"agreement_id": row[0]}


@router.delete("/pricing/{agreement_id}")
def delete_pricing(agreement_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM BuyerPricingAgreement WHERE AgreementID=:aid AND BusinessID=:bid"),
               {"aid": agreement_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary")
def get_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    r = db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM BuyerContact WHERE BusinessID=:bid) AS total_contacts,
            (SELECT COUNT(*) FROM BuyerInteraction WHERE BusinessID=:bid
             AND InteractionDate >= DATEADD(day,-30,GETDATE())) AS interactions_30d,
            (SELECT COUNT(*) FROM BuyerInteraction WHERE BusinessID=:bid
             AND FollowUpDate BETWEEN GETDATE() AND DATEADD(day,7,GETDATE())) AS follow_ups_due,
            (SELECT COUNT(*) FROM BuyerPricingAgreement WHERE BusinessID=:bid
             AND (ValidTo IS NULL OR ValidTo >= GETDATE())) AS active_agreements
    """), {"bid": business_id}).fetchone()
    return dict(zip(["total_contacts","interactions_30d","follow_ups_due","active_agreements"], r))
