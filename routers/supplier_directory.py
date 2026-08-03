"""Input & Supplier Directory — seeds, feed, fertilizer, equipment dealers, etc."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine
from typing import Optional
from pydantic import BaseModel

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])

with engine.begin() as _c:
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='SupplierListings')
        CREATE TABLE SupplierListings (
            SupplierID      INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID      INT NULL,
            CompanyName     NVARCHAR(200) NOT NULL,
            Category        VARCHAR(60) NOT NULL,
            Description     NVARCHAR(MAX) NULL,
            ProductsServices NVARCHAR(MAX) NULL,
            City            NVARCHAR(100) NULL,
            StateProvince   NVARCHAR(60) NULL,
            Website         NVARCHAR(300) NULL,
            Phone           NVARCHAR(30) NULL,
            Email           NVARCHAR(200) NULL,
            ServesRadius    INT NULL,
            IsVerified      BIT NOT NULL DEFAULT 0,
            IsActive        BIT NOT NULL DEFAULT 1,
            CreatedAt       DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='SupplierReviews')
        CREATE TABLE SupplierReviews (
            ReviewID        INT IDENTITY(1,1) PRIMARY KEY,
            SupplierID      INT NOT NULL,
            PeopleID        INT NULL,
            ReviewerName    NVARCHAR(150) NOT NULL,
            Rating          INT NOT NULL,
            Comment         NVARCHAR(MAX) NULL,
            CreatedAt       DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))

CATEGORIES = [
    "Seeds & Plants", "Fertilizers & Soil Amendments", "Pesticides & Herbicides",
    "Feed & Supplements", "Veterinary Supplies", "Equipment Dealers",
    "Equipment Repair", "Irrigation & Water", "Storage & Handling",
    "Packaging & Labels", "Fuel & Energy", "Financial Services",
    "Insurance", "Consulting & Agronomy", "Other",
]


class SupplierCreate(BaseModel):
    company_name: str
    category: str
    description: Optional[str] = None
    products_services: Optional[str] = None
    city: Optional[str] = None
    state_province: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    serves_radius: Optional[int] = None


def _ser(r): return dict(r._mapping)


@router.get("/categories")
def get_categories():
    return CATEGORIES


@router.get("")
def browse(
    category: Optional[str] = None,
    state: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    filters = ["s.IsActive=1"]
    params: dict = {}
    if category:
        filters.append("s.Category=:cat"); params["cat"] = category
    if state:
        filters.append("s.StateProvince=:state"); params["state"] = state
    if q:
        filters.append("(s.CompanyName LIKE :q OR s.Description LIKE :q OR s.ProductsServices LIKE :q)")
        params["q"] = f"%{q}%"
    where = " AND ".join(filters)
    rows = db.execute(text(f"""
        SELECT s.*,
               (SELECT AVG(CAST(r.Rating AS FLOAT)) FROM SupplierReviews r WHERE r.SupplierID=s.SupplierID) AS AvgRating,
               (SELECT COUNT(*) FROM SupplierReviews r WHERE r.SupplierID=s.SupplierID) AS ReviewCount
        FROM SupplierListings s
        WHERE {where} ORDER BY s.IsVerified DESC, s.CompanyName ASC
    """), params).fetchall()
    return [_ser(r) for r in rows]


@router.get("/{supplier_id}")
def get_supplier(supplier_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT * FROM SupplierListings WHERE SupplierID=:id"), {"id": supplier_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Supplier not found")
    reviews = db.execute(text("SELECT * FROM SupplierReviews WHERE SupplierID=:id ORDER BY CreatedAt DESC"), {"id": supplier_id}).fetchall()
    d = _ser(row)
    d["reviews"] = [_ser(r) for r in reviews]
    return d


@router.post("")
def create_supplier(supplier: SupplierCreate, business_id: Optional[int] = None, db: Session = Depends(get_db)):
    row = db.execute(text("""
        INSERT INTO SupplierListings
            (BusinessID,CompanyName,Category,Description,ProductsServices,City,StateProvince,
             Website,Phone,Email,ServesRadius)
        OUTPUT INSERTED.SupplierID
        VALUES (:bid,:name,:cat,:desc,:prods,:city,:state,:web,:phone,:email,:radius)
    """), {
        "bid": business_id, "name": supplier.company_name, "cat": supplier.category,
        "desc": supplier.description, "prods": supplier.products_services,
        "city": supplier.city, "state": supplier.state_province,
        "web": supplier.website, "phone": supplier.phone, "email": supplier.email,
        "radius": supplier.serves_radius,
    }).fetchone()
    db.commit()
    return {"supplier_id": row[0]}


@router.put("/{supplier_id}")
def update_supplier(supplier_id: int, supplier: SupplierCreate, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE SupplierListings SET CompanyName=:name,Category=:cat,Description=:desc,
            ProductsServices=:prods,City=:city,StateProvince=:state,Website=:web,
            Phone=:phone,Email=:email,ServesRadius=:radius
        WHERE SupplierID=:id
    """), {
        "name": supplier.company_name, "cat": supplier.category, "desc": supplier.description,
        "prods": supplier.products_services, "city": supplier.city, "state": supplier.state_province,
        "web": supplier.website, "phone": supplier.phone, "email": supplier.email,
        "radius": supplier.serves_radius, "id": supplier_id,
    })
    db.commit()
    return {"ok": True}


@router.post("/{supplier_id}/reviews")
def add_review(supplier_id: int, body: dict, db: Session = Depends(get_db)):
    rating = int(body.get("rating") or 0)
    if not (1 <= rating <= 5):
        raise HTTPException(status_code=400, detail="Rating must be 1–5")
    db.execute(text("""
        INSERT INTO SupplierReviews (SupplierID,PeopleID,ReviewerName,Rating,Comment)
        VALUES (:sid,:pid,:name,:rating,:comment)
    """), {
        "sid": supplier_id, "pid": body.get("people_id"),
        "name": body.get("reviewer_name", "Anonymous"),
        "rating": rating, "comment": body.get("comment"),
    })
    db.commit()
    return {"ok": True}
