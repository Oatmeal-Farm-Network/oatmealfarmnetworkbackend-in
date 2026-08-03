# routers/equipment_marketplace.py
# Equipment Marketplace — buy, sell, swap, and borrow farm equipment
# Mount: app.include_router(equipment_router, prefix="/api/equipment")

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine
from auth import get_current_user
from pydantic import BaseModel
from typing import Optional
from contextlib import suppress

GCS_BUCKET = "oatmeal-farm-network-images"

equipment_router = APIRouter()

# ── Auto-create tables ─────────────────────────────────────────────────────────
with suppress(Exception), engine.begin() as _conn:
    _conn.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='EquipmentListings')
        BEGIN
            CREATE TABLE EquipmentListings (
                ListingID       INT IDENTITY(1,1) PRIMARY KEY,
                BusinessID      INT NOT NULL,
                Title           VARCHAR(300) NOT NULL,
                Description     NVARCHAR(MAX),
                Category        VARCHAR(100) NOT NULL DEFAULT 'Other',
                ListingType     VARCHAR(20)  NOT NULL DEFAULT 'sale',
                AskingPrice     DECIMAL(12,2),
                SwapFor         VARCHAR(500),
                LoanTerms       VARCHAR(500),
                Condition       VARCHAR(20)  DEFAULT 'good',
                YearMade        INT,
                Make            VARCHAR(100),
                Model           VARCHAR(100),
                HoursUsed       INT,
                City            VARCHAR(100),
                StateProvince   VARCHAR(100),
                ContactEmail    VARCHAR(200),
                ContactPhone    VARCHAR(50),
                IsActive        BIT DEFAULT 1,
                CreatedAt       DATETIME DEFAULT GETDATE(),
                UpdatedAt       DATETIME DEFAULT GETDATE()
            )
        END
    """))
    _conn.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='EquipmentListingImages')
        BEGIN
            CREATE TABLE EquipmentListingImages (
                ImageID     INT IDENTITY(1,1) PRIMARY KEY,
                ListingID   INT NOT NULL,
                ImageURL    VARCHAR(1000) NOT NULL,
                SortOrder   INT DEFAULT 0
            )
        END
    """))
    _conn.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='EquipmentInquiries')
        BEGIN
            CREATE TABLE EquipmentInquiries (
                InquiryID       INT IDENTITY(1,1) PRIMARY KEY,
                ListingID       INT NOT NULL,
                FromBusinessID  INT,
                SenderName      VARCHAR(200),
                SenderEmail     VARCHAR(200),
                Message         NVARCHAR(MAX) NOT NULL,
                InquiryType     VARCHAR(20) DEFAULT 'general',
                Status          VARCHAR(20) DEFAULT 'pending',
                CreatedAt       DATETIME DEFAULT GETDATE()
            )
        END
    """))

CATEGORIES = [
    'Tractors', 'Tillage', 'Planting & Seeding', 'Harvesting',
    'Hay & Forage', 'Irrigation', 'Livestock Equipment',
    'Sprayers', 'Grain Handling', 'Trailers & Transport', 'Other',
]

# ── Pydantic models ────────────────────────────────────────────────────────────

class ListingCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: str = 'Other'
    listing_type: str = 'sale'
    asking_price: Optional[float] = None
    swap_for: Optional[str] = None
    loan_terms: Optional[str] = None
    condition: str = 'good'
    year_made: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    hours_used: Optional[int] = None
    city: Optional[str] = None
    state_province: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None

class InquiryCreate(BaseModel):
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    message: str
    inquiry_type: str = 'general'

class InquiryStatusUpdate(BaseModel):
    status: str

# ── Helpers ────────────────────────────────────────────────────────────────────

def _listing_or_404(db: Session, listing_id: int) -> dict:
    row = db.execute(
        text("SELECT * FROM EquipmentListings WHERE ListingID=:id AND IsActive=1"),
        {"id": listing_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Listing not found")
    return dict(row._mapping)

# ── Browse ─────────────────────────────────────────────────────────────────────

@equipment_router.get("")
def browse_listings(
    listing_type: Optional[str] = Query(None),
    category:     Optional[str] = Query(None),
    state:        Optional[str] = Query(None),
    search:       Optional[str] = Query(None),
    skip:         int = Query(0, ge=0),
    limit:        int = Query(24, ge=1, le=100),
    db: Session = Depends(get_db),
):
    wheres = ["l.IsActive = 1"]
    params: dict = {}

    if listing_type:
        wheres.append("l.ListingType = :lt")
        params["lt"] = listing_type
    if category:
        wheres.append("l.Category = :cat")
        params["cat"] = category
    if state:
        wheres.append("l.StateProvince LIKE :state")
        params["state"] = f"%{state}%"
    if search:
        wheres.append("(l.Title LIKE :q OR l.Make LIKE :q OR l.Model LIKE :q)")
        params["q"] = f"%{search}%"

    where_sql = " AND ".join(wheres)

    rows = db.execute(text(f"""
        SELECT l.*,
               b.BusinessName,
               (SELECT TOP 1 ImageURL FROM EquipmentListingImages
                WHERE ListingID = l.ListingID ORDER BY SortOrder) AS PrimaryImage
        FROM EquipmentListings l
        LEFT JOIN Business b ON b.BusinessID = l.BusinessID
        WHERE {where_sql}
        ORDER BY l.CreatedAt DESC
        OFFSET :skip ROWS FETCH NEXT :lim ROWS ONLY
    """), {**params, "skip": skip, "lim": limit}).mappings().all()

    total = db.execute(text(f"""
        SELECT COUNT(*) FROM EquipmentListings l WHERE {where_sql}
    """), params).scalar()

    return {"total": total, "items": [dict(r) for r in rows]}


@equipment_router.get("/categories")
def get_categories():
    return CATEGORIES


@equipment_router.get("/my")
def my_listings(
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    rows = db.execute(text("""
        SELECT l.*,
               (SELECT TOP 1 ImageURL FROM EquipmentListingImages
                WHERE ListingID = l.ListingID ORDER BY SortOrder) AS PrimaryImage,
               (SELECT COUNT(*) FROM EquipmentListingImages
                WHERE ListingID = l.ListingID) AS ImageCount,
               (SELECT COUNT(*) FROM EquipmentInquiries
                WHERE ListingID = l.ListingID AND Status = 'pending') AS PendingInquiries
        FROM EquipmentListings l
        WHERE l.BusinessID = :bid
        ORDER BY l.CreatedAt DESC
    """), {"bid": business_id}).mappings().all()
    return [dict(r) for r in rows]


@equipment_router.get("/{listing_id}")
def get_listing(listing_id: int, db: Session = Depends(get_db)):
    listing = _listing_or_404(db, listing_id)
    images = db.execute(text("""
        SELECT * FROM EquipmentListingImages WHERE ListingID=:id ORDER BY SortOrder
    """), {"id": listing_id}).mappings().all()
    listing["images"] = [dict(r) for r in images]
    return listing

# ── Create / update / delete ───────────────────────────────────────────────────

@equipment_router.post("")
def create_listing(
    body: ListingCreate,
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = db.execute(text("""
        INSERT INTO EquipmentListings
            (BusinessID, Title, Description, Category, ListingType, AskingPrice,
             SwapFor, LoanTerms, Condition, YearMade, Make, Model, HoursUsed,
             City, StateProvince, ContactEmail, ContactPhone)
        OUTPUT INSERTED.ListingID
        VALUES
            (:bid, :title, :desc, :cat, :lt, :price,
             :swap, :loan, :cond, :yr, :make, :model, :hrs,
             :city, :state, :email, :phone)
    """), {
        "bid": business_id, "title": body.title, "desc": body.description,
        "cat": body.category, "lt": body.listing_type, "price": body.asking_price,
        "swap": body.swap_for, "loan": body.loan_terms, "cond": body.condition,
        "yr": body.year_made, "make": body.make, "model": body.model,
        "hrs": body.hours_used, "city": body.city, "state": body.state_province,
        "email": body.contact_email, "phone": body.contact_phone,
    }).fetchone()
    db.commit()
    return {"listing_id": row[0]}


@equipment_router.put("/{listing_id}")
def update_listing(
    listing_id: int,
    body: ListingCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _listing_or_404(db, listing_id)
    db.execute(text("""
        UPDATE EquipmentListings SET
            Title=:title, Description=:desc, Category=:cat, ListingType=:lt,
            AskingPrice=:price, SwapFor=:swap, LoanTerms=:loan, Condition=:cond,
            YearMade=:yr, Make=:make, Model=:model, HoursUsed=:hrs,
            City=:city, StateProvince=:state, ContactEmail=:email, ContactPhone=:phone,
            UpdatedAt=GETDATE()
        WHERE ListingID=:id
    """), {
        "id": listing_id, "title": body.title, "desc": body.description,
        "cat": body.category, "lt": body.listing_type, "price": body.asking_price,
        "swap": body.swap_for, "loan": body.loan_terms, "cond": body.condition,
        "yr": body.year_made, "make": body.make, "model": body.model,
        "hrs": body.hours_used, "city": body.city, "state": body.state_province,
        "email": body.contact_email, "phone": body.contact_phone,
    })
    db.commit()
    return {"ok": True}


@equipment_router.delete("/{listing_id}")
def deactivate_listing(
    listing_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    db.execute(
        text("UPDATE EquipmentListings SET IsActive=0 WHERE ListingID=:id"),
        {"id": listing_id},
    )
    db.commit()
    return {"ok": True}

# ── Images ─────────────────────────────────────────────────────────────────────

@equipment_router.post("/{listing_id}/images")
def add_image(
    listing_id: int,
    image_url: str = Query(...),
    sort_order: int = Query(0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    db.execute(text("""
        INSERT INTO EquipmentListingImages (ListingID, ImageURL, SortOrder)
        VALUES (:lid, :url, :sort)
    """), {"lid": listing_id, "url": image_url, "sort": sort_order})
    db.commit()
    return {"ok": True}


@equipment_router.post("/{listing_id}/upload-image")
async def upload_equipment_image(
    listing_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = db.execute(
        text("SELECT ListingID FROM EquipmentListings WHERE ListingID=:id"),
        {"id": listing_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")
    content = await file.read()
    ext = (file.filename or "img").rsplit(".", 1)[-1].lower()
    if ext not in {"jpg", "jpeg", "png", "gif", "webp", "avif"}:
        ext = "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(f"equipment/{filename}")
        blob.upload_from_string(content, content_type=file.content_type)
        url = f"https://storage.googleapis.com/{GCS_BUCKET}/equipment/{filename}"
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {e}")
    max_sort = db.execute(text("""
        SELECT COALESCE(MAX(SortOrder), -1) FROM EquipmentListingImages WHERE ListingID=:id
    """), {"id": listing_id}).scalar()
    result = db.execute(text("""
        INSERT INTO EquipmentListingImages (ListingID, ImageURL, SortOrder)
        OUTPUT INSERTED.ImageID
        VALUES (:lid, :url, :sort)
    """), {"lid": listing_id, "url": url, "sort": max_sort + 1}).fetchone()
    db.commit()
    return {"url": url, "image_id": result[0]}


@equipment_router.delete("/images/{image_id}")
def delete_image(
    image_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    db.execute(
        text("DELETE FROM EquipmentListingImages WHERE ImageID=:id"),
        {"id": image_id},
    )
    db.commit()
    return {"ok": True}

# ── Inquiries ──────────────────────────────────────────────────────────────────

@equipment_router.post("/{listing_id}/inquire")
def send_inquiry(
    listing_id: int,
    body: InquiryCreate,
    business_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    _listing_or_404(db, listing_id)
    db.execute(text("""
        INSERT INTO EquipmentInquiries
            (ListingID, FromBusinessID, SenderName, SenderEmail, Message, InquiryType)
        VALUES (:lid, :bid, :name, :email, :msg, :type)
    """), {
        "lid": listing_id, "bid": business_id,
        "name": body.sender_name, "email": body.sender_email,
        "msg": body.message, "type": body.inquiry_type,
    })
    db.commit()
    return {"ok": True}


@equipment_router.get("/{listing_id}/inquiries")
def get_inquiries(
    listing_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    rows = db.execute(text("""
        SELECT i.*, b.BusinessName AS FromBusinessName
        FROM EquipmentInquiries i
        LEFT JOIN Business b ON b.BusinessID = i.FromBusinessID
        WHERE i.ListingID = :id
        ORDER BY i.CreatedAt DESC
    """), {"id": listing_id}).mappings().all()
    return [dict(r) for r in rows]


@equipment_router.put("/inquiry/{inquiry_id}")
def update_inquiry_status(
    inquiry_id: int,
    body: InquiryStatusUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    db.execute(
        text("UPDATE EquipmentInquiries SET Status=:s WHERE InquiryID=:id"),
        {"s": body.status, "id": inquiry_id},
    )
    db.commit()
    return {"ok": True}
