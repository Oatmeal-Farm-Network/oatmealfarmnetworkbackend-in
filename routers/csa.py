"""CSA Management — subscription share plans and member management."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine
from typing import Optional
from pydantic import BaseModel

router = APIRouter(prefix="/api/csa", tags=["csa"])

with engine.begin() as _c:
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSAPlans')
        CREATE TABLE CSAPlans (
            PlanID          INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID      INT NOT NULL,
            Name            NVARCHAR(150) NOT NULL,
            Description     NVARCHAR(MAX) NULL,
            ShareSize       VARCHAR(40) NULL,
            PricePerShare   DECIMAL(10,2) NULL,
            Frequency       VARCHAR(30) NULL,
            SeasonStart     DATE NULL,
            SeasonEnd       DATE NULL,
            PickupDay       VARCHAR(20) NULL,
            PickupLocation  NVARCHAR(300) NULL,
            Capacity        INT NULL,
            IsActive        BIT NOT NULL DEFAULT 1,
            ImageUrl        NVARCHAR(500) NULL,
            CreatedAt       DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSASubscriptions')
        CREATE TABLE CSASubscriptions (
            SubscriptionID  INT IDENTITY(1,1) PRIMARY KEY,
            PlanID          INT NOT NULL,
            BusinessID      INT NOT NULL,
            PeopleID        INT NULL,
            MemberName      NVARCHAR(150) NOT NULL,
            MemberEmail     NVARCHAR(200) NOT NULL,
            MemberPhone     NVARCHAR(30) NULL,
            PickupPreference NVARCHAR(200) NULL,
            StartDate       DATE NULL,
            Status          VARCHAR(30) NOT NULL DEFAULT 'active',
            Notes           NVARCHAR(500) NULL,
            CreatedAt       DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSAShareLog')
        CREATE TABLE CSAShareLog (
            LogID           INT IDENTITY(1,1) PRIMARY KEY,
            PlanID          INT NOT NULL,
            BusinessID      INT NOT NULL,
            ShareDate       DATE NOT NULL,
            Contents        NVARCHAR(MAX) NULL,
            PickupCount     INT NULL,
            Notes           NVARCHAR(500) NULL,
            CreatedAt       DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))


class PlanCreate(BaseModel):
    name: str
    description: Optional[str] = None
    share_size: Optional[str] = None
    price_per_share: Optional[float] = None
    frequency: Optional[str] = None
    season_start: Optional[str] = None
    season_end: Optional[str] = None
    pickup_day: Optional[str] = None
    pickup_location: Optional[str] = None
    capacity: Optional[int] = None
    image_url: Optional[str] = None


def _ser(r): return dict(r._mapping)


@router.get("/public")
def browse_csa(state: Optional[str] = None, db: Session = Depends(get_db)):
    params: dict = {}
    extra = ""
    if state:
        extra = "AND b.State=:state"; params["state"] = state
    rows = db.execute(text(f"""
        SELECT p.*, b.BusinessName, b.City, b.State,
               (SELECT COUNT(*) FROM CSASubscriptions s WHERE s.PlanID=p.PlanID AND s.Status='active') AS SubscriberCount
        FROM CSAPlans p
        LEFT JOIN Business b ON b.BusinessID=p.BusinessID
        WHERE p.IsActive=1 {extra}
        ORDER BY p.CreatedAt DESC
    """), params).fetchall()
    return [_ser(r) for r in rows]


@router.get("/business/{business_id}/plans")
def my_plans(business_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT p.*,
               (SELECT COUNT(*) FROM CSASubscriptions s WHERE s.PlanID=p.PlanID AND s.Status='active') AS ActiveSubs
        FROM CSAPlans p WHERE p.BusinessID=:b ORDER BY p.CreatedAt DESC
    """), {"b": business_id}).fetchall()
    return [_ser(r) for r in rows]


@router.post("/business/{business_id}/plans")
def create_plan(business_id: int, plan: PlanCreate, db: Session = Depends(get_db)):
    row = db.execute(text("""
        INSERT INTO CSAPlans
            (BusinessID,Name,Description,ShareSize,PricePerShare,Frequency,
             SeasonStart,SeasonEnd,PickupDay,PickupLocation,Capacity,ImageUrl)
        OUTPUT INSERTED.PlanID
        VALUES (:b,:name,:desc,:size,:price,:freq,:ss,:se,:day,:loc,:cap,:img)
    """), {
        "b": business_id, "name": plan.name, "desc": plan.description,
        "size": plan.share_size, "price": plan.price_per_share, "freq": plan.frequency,
        "ss": plan.season_start, "se": plan.season_end, "day": plan.pickup_day,
        "loc": plan.pickup_location, "cap": plan.capacity, "img": plan.image_url,
    }).fetchone()
    db.commit()
    return {"plan_id": row[0]}


@router.put("/plans/{plan_id}")
def update_plan(plan_id: int, plan: PlanCreate, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE CSAPlans SET Name=:name,Description=:desc,ShareSize=:size,PricePerShare=:price,
            Frequency=:freq,SeasonStart=:ss,SeasonEnd=:se,PickupDay=:day,
            PickupLocation=:loc,Capacity=:cap,ImageUrl=:img
        WHERE PlanID=:id
    """), {
        "name": plan.name, "desc": plan.description, "size": plan.share_size,
        "price": plan.price_per_share, "freq": plan.frequency,
        "ss": plan.season_start, "se": plan.season_end, "day": plan.pickup_day,
        "loc": plan.pickup_location, "cap": plan.capacity, "img": plan.image_url, "id": plan_id,
    })
    db.commit()
    return {"ok": True}


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE CSAPlans SET IsActive=0 WHERE PlanID=:id"), {"id": plan_id})
    db.commit()
    return {"ok": True}


@router.post("/plans/{plan_id}/subscribe")
def subscribe(plan_id: int, body: dict, db: Session = Depends(get_db)):
    plan = db.execute(text("SELECT BusinessID, Capacity FROM CSAPlans WHERE PlanID=:id AND IsActive=1"), {"id": plan_id}).fetchone()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if plan.Capacity:
        count = db.execute(text("SELECT COUNT(*) FROM CSASubscriptions WHERE PlanID=:id AND Status='active'"), {"id": plan_id}).scalar()
        if count >= plan.Capacity:
            raise HTTPException(status_code=409, detail="Plan is full")
    row = db.execute(text("""
        INSERT INTO CSASubscriptions
            (PlanID,BusinessID,PeopleID,MemberName,MemberEmail,MemberPhone,PickupPreference,StartDate,Notes)
        OUTPUT INSERTED.SubscriptionID
        VALUES (:pid,:bid,:people,:name,:email,:phone,:pickup,:start,:notes)
    """), {
        "pid": plan_id, "bid": plan.BusinessID, "people": body.get("people_id"),
        "name": body.get("name", ""), "email": body.get("email", ""),
        "phone": body.get("phone"), "pickup": body.get("pickup_preference"),
        "start": body.get("start_date"), "notes": body.get("notes"),
    }).fetchone()
    db.commit()
    return {"subscription_id": row[0]}


@router.get("/plans/{plan_id}/subscribers")
def get_subscribers(plan_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT * FROM CSASubscriptions WHERE PlanID=:id ORDER BY MemberName
    """), {"id": plan_id}).fetchall()
    return [_ser(r) for r in rows]


@router.patch("/subscriptions/{sub_id}/status")
def update_status(sub_id: int, body: dict, db: Session = Depends(get_db)):
    db.execute(text("UPDATE CSASubscriptions SET Status=:s WHERE SubscriptionID=:id"), {"s": body.get("status"), "id": sub_id})
    db.commit()
    return {"ok": True}


@router.get("/plans/{plan_id}/share-log")
def get_share_log(plan_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT * FROM CSAShareLog WHERE PlanID=:id ORDER BY ShareDate DESC"), {"id": plan_id}).fetchall()
    return [_ser(r) for r in rows]


@router.post("/plans/{plan_id}/share-log")
def add_share_log(plan_id: int, body: dict, db: Session = Depends(get_db)):
    plan = db.execute(text("SELECT BusinessID FROM CSAPlans WHERE PlanID=:id"), {"id": plan_id}).fetchone()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    db.execute(text("""
        INSERT INTO CSAShareLog (PlanID,BusinessID,ShareDate,Contents,PickupCount,Notes)
        VALUES (:pid,:bid,:date,:contents,:count,:notes)
    """), {
        "pid": plan_id, "bid": plan.BusinessID, "date": body.get("share_date"),
        "contents": body.get("contents"), "count": body.get("pickup_count"), "notes": body.get("notes"),
    })
    db.commit()
    return {"ok": True}
