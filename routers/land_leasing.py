"""Land Leasing — cash rent, lease, and land-for-sale listings."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine
from typing import Optional
from pydantic import BaseModel

router = APIRouter(prefix="/api/land", tags=["land-leasing"])

with engine.begin() as _c:
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='LandListings')
        CREATE TABLE LandListings (
            ListingID       INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID      INT NOT NULL,
            Title           NVARCHAR(200) NOT NULL,
            Description     NVARCHAR(MAX) NULL,
            ListingType     VARCHAR(30) NOT NULL DEFAULT 'lease',
            Acreage         DECIMAL(10,2) NULL,
            SoilType        NVARCHAR(200) NULL,
            Irrigation      BIT NOT NULL DEFAULT 0,
            Tillable        DECIMAL(10,2) NULL,
            Infrastructure  NVARCHAR(500) NULL,
            PricePerAcre    DECIMAL(10,2) NULL,
            TotalPrice      DECIMAL(12,2) NULL,
            LeaseTerm       NVARCHAR(100) NULL,
            AvailableDate   DATE NULL,
            City            NVARCHAR(100) NULL,
            StateProvince   NVARCHAR(60) NULL,
            Latitude        DECIMAL(10,7) NULL,
            Longitude       DECIMAL(10,7) NULL,
            ContactEmail    NVARCHAR(200) NULL,
            ContactPhone    NVARCHAR(30) NULL,
            IsActive        BIT NOT NULL DEFAULT 1,
            CreatedAt       DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='LandInquiries')
        CREATE TABLE LandInquiries (
            InquiryID       INT IDENTITY(1,1) PRIMARY KEY,
            ListingID       INT NOT NULL,
            SenderName      NVARCHAR(150) NOT NULL,
            SenderEmail     NVARCHAR(200) NOT NULL,
            SenderPhone     NVARCHAR(30) NULL,
            Message         NVARCHAR(MAX) NULL,
            CreatedAt       DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))


class LandCreate(BaseModel):
    title: str
    description: Optional[str] = None
    listing_type: str = 'lease'
    acreage: Optional[float] = None
    soil_type: Optional[str] = None
    irrigation: bool = False
    tillable: Optional[float] = None
    infrastructure: Optional[str] = None
    price_per_acre: Optional[float] = None
    total_price: Optional[float] = None
    lease_term: Optional[str] = None
    available_date: Optional[str] = None
    city: Optional[str] = None
    state_province: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None


def _ser(r): return dict(r._mapping)


@router.get("")
def browse(
    state: Optional[str] = None,
    listing_type: Optional[str] = None,
    min_acres: Optional[float] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    filters = ["l.IsActive=1"]
    params: dict = {}
    if state:
        filters.append("l.StateProvince=:state"); params["state"] = state
    if listing_type:
        filters.append("l.ListingType=:lt"); params["lt"] = listing_type
    if min_acres:
        filters.append("l.Acreage>=:acres"); params["acres"] = min_acres
    if q:
        filters.append("(l.Title LIKE :q OR l.Description LIKE :q)"); params["q"] = f"%{q}%"
    where = " AND ".join(filters)
    rows = db.execute(text(f"""
        SELECT l.*, b.BusinessName FROM LandListings l
        LEFT JOIN Business b ON b.BusinessID=l.BusinessID
        WHERE {where} ORDER BY l.CreatedAt DESC
    """), params).fetchall()
    return [_ser(r) for r in rows]


@router.get("/business/{business_id}")
def my_listings(business_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT l.*,
               (SELECT COUNT(*) FROM LandInquiries i WHERE i.ListingID=l.ListingID) AS InquiryCount
        FROM LandListings l WHERE l.BusinessID=:b ORDER BY l.CreatedAt DESC
    """), {"b": business_id}).fetchall()
    return [_ser(r) for r in rows]


@router.get("/{listing_id}")
def get_listing(listing_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT l.*, b.BusinessName FROM LandListings l
        LEFT JOIN Business b ON b.BusinessID=l.BusinessID
        WHERE l.ListingID=:id
    """), {"id": listing_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Listing not found")
    return _ser(row)


@router.post("/business/{business_id}")
def create_listing(business_id: int, listing: LandCreate, db: Session = Depends(get_db)):
    row = db.execute(text("""
        INSERT INTO LandListings
            (BusinessID,Title,Description,ListingType,Acreage,SoilType,Irrigation,Tillable,
             Infrastructure,PricePerAcre,TotalPrice,LeaseTerm,AvailableDate,City,StateProvince,
             Latitude,Longitude,ContactEmail,ContactPhone)
        OUTPUT INSERTED.ListingID
        VALUES (:b,:title,:desc,:lt,:acres,:soil,:irr,:till,:infra,:ppa,:tp,:term,:avail,
                :city,:state,:lat,:lon,:email,:phone)
    """), {
        "b": business_id, "title": listing.title, "desc": listing.description,
        "lt": listing.listing_type, "acres": listing.acreage, "soil": listing.soil_type,
        "irr": 1 if listing.irrigation else 0, "till": listing.tillable,
        "infra": listing.infrastructure, "ppa": listing.price_per_acre,
        "tp": listing.total_price, "term": listing.lease_term, "avail": listing.available_date,
        "city": listing.city, "state": listing.state_province,
        "lat": listing.latitude, "lon": listing.longitude,
        "email": listing.contact_email, "phone": listing.contact_phone,
    }).fetchone()
    db.commit()
    return {"listing_id": row[0]}


@router.put("/{listing_id}")
def update_listing(listing_id: int, listing: LandCreate, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE LandListings SET Title=:title,Description=:desc,ListingType=:lt,Acreage=:acres,
            SoilType=:soil,Irrigation=:irr,Tillable=:till,Infrastructure=:infra,
            PricePerAcre=:ppa,TotalPrice=:tp,LeaseTerm=:term,AvailableDate=:avail,
            City=:city,StateProvince=:state,Latitude=:lat,Longitude=:lon,
            ContactEmail=:email,ContactPhone=:phone
        WHERE ListingID=:id
    """), {
        "title": listing.title, "desc": listing.description, "lt": listing.listing_type,
        "acres": listing.acreage, "soil": listing.soil_type,
        "irr": 1 if listing.irrigation else 0, "till": listing.tillable,
        "infra": listing.infrastructure, "ppa": listing.price_per_acre,
        "tp": listing.total_price, "term": listing.lease_term, "avail": listing.available_date,
        "city": listing.city, "state": listing.state_province,
        "lat": listing.latitude, "lon": listing.longitude,
        "email": listing.contact_email, "phone": listing.contact_phone, "id": listing_id,
    })
    db.commit()
    return {"ok": True}


@router.delete("/{listing_id}")
def delete_listing(listing_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE LandListings SET IsActive=0 WHERE ListingID=:id"), {"id": listing_id})
    db.commit()
    return {"ok": True}


@router.post("/{listing_id}/inquire")
def inquire(listing_id: int, body: dict, db: Session = Depends(get_db)):
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip()
    if not name or not email:
        raise HTTPException(status_code=400, detail="Name and email required")
    db.execute(text("""
        INSERT INTO LandInquiries (ListingID,SenderName,SenderEmail,SenderPhone,Message)
        VALUES (:lid,:name,:email,:phone,:msg)
    """), {"lid": listing_id, "name": name, "email": email, "phone": body.get("phone"), "msg": body.get("message")})
    db.commit()
    return {"ok": True}


@router.get("/{listing_id}/inquiries")
def get_inquiries(listing_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT * FROM LandInquiries WHERE ListingID=:id ORDER BY CreatedAt DESC"), {"id": listing_id}).fetchall()
    return [_ser(r) for r in rows]
