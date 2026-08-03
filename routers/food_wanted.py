# routers/food_wanted.py
# Food Wanted Board — buyers post ingredient requests, farms respond
# Mount: app.include_router(food_wanted_router, prefix="/api/food-wanted")

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine
from auth import get_current_user
from pydantic import BaseModel
from typing import Optional, List
from contextlib import suppress

food_wanted_router = APIRouter()

# ── Auto-create tables ─────────────────────────────────────────────────────────
with suppress(Exception), engine.begin() as _conn:
    _conn.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='FoodWantedAds')
        BEGIN
            CREATE TABLE FoodWantedAds (
                AdID                INT IDENTITY(1,1) PRIMARY KEY,
                BusinessID          INT NOT NULL,
                Title               VARCHAR(300) NOT NULL,
                Description         NVARCHAR(MAX),
                BuyerType           VARCHAR(100),
                DeliveryPreference  VARCHAR(50) DEFAULT 'either',
                LocationCity        VARCHAR(100),
                LocationState       VARCHAR(100),
                NeededBy            DATE,
                IsActive            BIT DEFAULT 1,
                CreatedAt           DATETIME DEFAULT GETDATE(),
                UpdatedAt           DATETIME DEFAULT GETDATE()
            )
        END
    """))
    _conn.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='FoodWantedItems')
        BEGIN
            CREATE TABLE FoodWantedItems (
                ItemID          INT IDENTITY(1,1) PRIMARY KEY,
                AdID            INT NOT NULL,
                IngredientName  VARCHAR(200) NOT NULL,
                Quantity        VARCHAR(100),
                Unit            VARCHAR(50),
                Notes           VARCHAR(500)
            )
        END
    """))
    _conn.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='FoodWantedResponses')
        BEGIN
            CREATE TABLE FoodWantedResponses (
                ResponseID      INT IDENTITY(1,1) PRIMARY KEY,
                AdID            INT NOT NULL,
                FromBusinessID  INT,
                SenderName      VARCHAR(200),
                SenderEmail     VARCHAR(200),
                Message         NVARCHAR(MAX) NOT NULL,
                Status          VARCHAR(20) DEFAULT 'pending',
                CreatedAt       DATETIME DEFAULT GETDATE()
            )
        END
    """))

# ── Pydantic models ────────────────────────────────────────────────────────────

class WantedItem(BaseModel):
    ingredient_name: str
    quantity: Optional[str] = None
    unit: Optional[str] = None
    notes: Optional[str] = None

class AdCreate(BaseModel):
    title: str
    description: Optional[str] = None
    buyer_type: Optional[str] = None
    delivery_preference: str = 'either'
    location_city: Optional[str] = None
    location_state: Optional[str] = None
    needed_by: Optional[str] = None
    items: List[WantedItem] = []

class ResponseCreate(BaseModel):
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    message: str

class ResponseStatusUpdate(BaseModel):
    status: str

# ── Helpers ────────────────────────────────────────────────────────────────────

def _ad_or_404(db: Session, ad_id: int) -> dict:
    row = db.execute(
        text("SELECT * FROM FoodWantedAds WHERE AdID=:id AND IsActive=1"),
        {"id": ad_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Ad not found")
    return dict(row._mapping)

def _load_items(db: Session, ad_id: int) -> list:
    rows = db.execute(
        text("SELECT * FROM FoodWantedItems WHERE AdID=:id ORDER BY ItemID"),
        {"id": ad_id},
    ).mappings().all()
    return [dict(r) for r in rows]

def _replace_items(db: Session, ad_id: int, items: List[WantedItem]):
    db.execute(text("DELETE FROM FoodWantedItems WHERE AdID=:id"), {"id": ad_id})
    for it in items:
        if not it.ingredient_name.strip():
            continue
        db.execute(text("""
            INSERT INTO FoodWantedItems (AdID, IngredientName, Quantity, Unit, Notes)
            VALUES (:ad, :name, :qty, :unit, :notes)
        """), {
            "ad": ad_id, "name": it.ingredient_name.strip(),
            "qty": it.quantity, "unit": it.unit, "notes": it.notes,
        })

# ── Browse ─────────────────────────────────────────────────────────────────────

@food_wanted_router.get("")
def browse_ads(
    buyer_type:  Optional[str] = Query(None),
    state:       Optional[str] = Query(None),
    search:      Optional[str] = Query(None),
    skip:        int = Query(0, ge=0),
    limit:       int = Query(24, ge=1, le=100),
    db: Session = Depends(get_db),
):
    wheres = ["a.IsActive = 1"]
    params: dict = {}

    if buyer_type:
        wheres.append("a.BuyerType = :bt")
        params["bt"] = buyer_type
    if state:
        wheres.append("a.LocationState = :state")
        params["state"] = state
    if search:
        wheres.append("""(
            a.Title LIKE :q OR
            EXISTS (
                SELECT 1 FROM FoodWantedItems i
                WHERE i.AdID = a.AdID AND i.IngredientName LIKE :q
            )
        )""")
        params["q"] = f"%{search}%"

    where_sql = " AND ".join(wheres)

    rows = db.execute(text(f"""
        SELECT a.*, b.BusinessName,
               (SELECT COUNT(*) FROM FoodWantedItems WHERE AdID = a.AdID) AS ItemCount
        FROM FoodWantedAds a
        LEFT JOIN Business b ON b.BusinessID = a.BusinessID
        WHERE {where_sql}
        ORDER BY a.CreatedAt DESC
        OFFSET :skip ROWS FETCH NEXT :lim ROWS ONLY
    """), {**params, "skip": skip, "lim": limit}).mappings().all()

    total = db.execute(
        text(f"SELECT COUNT(*) FROM FoodWantedAds a WHERE {where_sql}"),
        params,
    ).scalar()

    result = []
    for r in rows:
        ad = dict(r)
        ad["items"] = _load_items(db, ad["AdID"])
        result.append(ad)

    return {"total": total, "items": result}


@food_wanted_router.get("/my")
def my_ads(
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    rows = db.execute(text("""
        SELECT a.*,
               (SELECT COUNT(*) FROM FoodWantedItems WHERE AdID = a.AdID) AS ItemCount,
               (SELECT COUNT(*) FROM FoodWantedResponses WHERE AdID = a.AdID) AS ResponseCount
        FROM FoodWantedAds a
        WHERE a.BusinessID = :bid AND a.IsActive = 1
        ORDER BY a.CreatedAt DESC
    """), {"bid": business_id}).mappings().all()
    result = []
    for r in rows:
        ad = dict(r)
        ad["items"] = _load_items(db, ad["AdID"])
        result.append(ad)
    return result


@food_wanted_router.get("/{ad_id}")
def get_ad(ad_id: int, db: Session = Depends(get_db)):
    ad = _ad_or_404(db, ad_id)
    ad["items"] = _load_items(db, ad_id)
    return ad

# ── Create / update / delete ───────────────────────────────────────────────────

@food_wanted_router.post("")
def create_ad(
    body: AdCreate,
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = db.execute(text("""
        INSERT INTO FoodWantedAds
            (BusinessID, Title, Description, BuyerType, DeliveryPreference,
             LocationCity, LocationState, NeededBy)
        OUTPUT INSERTED.AdID
        VALUES (:bid, :title, :desc, :bt, :deliv, :city, :state, :by)
    """), {
        "bid": business_id, "title": body.title, "desc": body.description,
        "bt": body.buyer_type, "deliv": body.delivery_preference,
        "city": body.location_city, "state": body.location_state,
        "by": body.needed_by or None,
    }).fetchone()
    ad_id = row[0]
    _replace_items(db, ad_id, body.items)
    db.commit()
    return {"ad_id": ad_id}


@food_wanted_router.put("/{ad_id}")
def update_ad(
    ad_id: int,
    body: AdCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _ad_or_404(db, ad_id)
    db.execute(text("""
        UPDATE FoodWantedAds SET
            Title=:title, Description=:desc, BuyerType=:bt,
            DeliveryPreference=:deliv, LocationCity=:city, LocationState=:state,
            NeededBy=:by, UpdatedAt=GETDATE()
        WHERE AdID=:id
    """), {
        "id": ad_id, "title": body.title, "desc": body.description,
        "bt": body.buyer_type, "deliv": body.delivery_preference,
        "city": body.location_city, "state": body.location_state,
        "by": body.needed_by or None,
    })
    _replace_items(db, ad_id, body.items)
    db.commit()
    return {"ok": True}


@food_wanted_router.delete("/{ad_id}")
def deactivate_ad(
    ad_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    db.execute(
        text("UPDATE FoodWantedAds SET IsActive=0 WHERE AdID=:id"),
        {"id": ad_id},
    )
    db.commit()
    return {"ok": True}

# ── Responses ──────────────────────────────────────────────────────────────────

@food_wanted_router.post("/{ad_id}/respond")
def respond_to_ad(
    ad_id: int,
    body: ResponseCreate,
    business_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    _ad_or_404(db, ad_id)
    db.execute(text("""
        INSERT INTO FoodWantedResponses
            (AdID, FromBusinessID, SenderName, SenderEmail, Message)
        VALUES (:ad, :bid, :name, :email, :msg)
    """), {
        "ad": ad_id, "bid": business_id,
        "name": body.sender_name, "email": body.sender_email,
        "msg": body.message,
    })
    db.commit()
    return {"ok": True}


@food_wanted_router.get("/{ad_id}/responses")
def get_responses(
    ad_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    rows = db.execute(text("""
        SELECT r.*, b.BusinessName AS FromBusinessName
        FROM FoodWantedResponses r
        LEFT JOIN Business b ON b.BusinessID = r.FromBusinessID
        WHERE r.AdID = :id
        ORDER BY r.CreatedAt DESC
    """), {"id": ad_id}).mappings().all()
    return [dict(r) for r in rows]


@food_wanted_router.put("/response/{response_id}")
def update_response_status(
    response_id: int,
    body: ResponseStatusUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    db.execute(
        text("UPDATE FoodWantedResponses SET Status=:s WHERE ResponseID=:id"),
        {"s": body.status, "id": response_id},
    )
    db.commit()
    return {"ok": True}
