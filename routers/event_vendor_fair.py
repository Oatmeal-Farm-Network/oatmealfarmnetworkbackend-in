"""
Market / Vendor Fair.

Modernized replacement for the classic ASP EventVendors.asp. Organizers configure
available booths and their fees; vendors apply for a booth with their business
details and product categories; organizers approve, reject, or assign booth numbers.
"""
from fastapi import APIRouter, Depends, HTTPException
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal
from datetime import date

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventVendorConfig')
        CREATE TABLE OFNEventVendorConfig (
            ConfigID            INT IDENTITY(1,1) PRIMARY KEY,
            EventID             INT NOT NULL UNIQUE,
            Description         NVARCHAR(MAX),
            BoothFeeSmall       DECIMAL(10,2) DEFAULT 0,
            BoothFeeMedium      DECIMAL(10,2),
            BoothFeeLarge       DECIMAL(10,2),
            ElectricityFee      DECIMAL(10,2) DEFAULT 0,
            TableFee            DECIMAL(10,2) DEFAULT 0,
            MaxBooths           INT,
            ApplicationEndDate  DATE,
            IsActive            BIT DEFAULT 1,
            CreatedDate         DATETIME DEFAULT GETDATE(),
            UpdatedDate         DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventVendorApplications')
        CREATE TABLE OFNEventVendorApplications (
            AppID             INT IDENTITY(1,1) PRIMARY KEY,
            EventID           INT NOT NULL,
            PeopleID          INT,
            BusinessID        INT,
            BusinessName      NVARCHAR(300) NOT NULL,
            ContactName       NVARCHAR(300),
            ContactEmail      NVARCHAR(300),
            ContactPhone      NVARCHAR(50),
            BoothSize         NVARCHAR(50) DEFAULT 'Medium',
            ProductCategories NVARCHAR(500),
            Description       NVARCHAR(MAX),
            WebsiteURL        NVARCHAR(500),
            NeedsElectricity  BIT DEFAULT 0,
            NeedsTable        BIT DEFAULT 0,
            RequestedLocation NVARCHAR(200),
            Status            NVARCHAR(50) DEFAULT 'pending',
            BoothNumber       NVARCHAR(50),
            Fee               DECIMAL(10,2) DEFAULT 0,
            PaidStatus        NVARCHAR(20) DEFAULT 'pending',
            OrganizerNotes    NVARCHAR(MAX),
            CreatedDate       DATETIME DEFAULT GETDATE(),
            UpdatedDate       DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


try:
    with SessionLocal() as _db:
        ensure_tables(_db)
except Exception as e:
    print(f"[event_vendor_fair] Table ensure warning: {e}")


def _calc_fee(cfg: dict, app: dict) -> float:
    size = (app.get("BoothSize") or "Medium").lower()
    fee = 0.0
    if size == "small":
        fee = float(cfg.get("BoothFeeSmall") or 0)
    elif size == "large":
        fee = float(cfg.get("BoothFeeLarge") or cfg.get("BoothFeeMedium") or 0)
    else:
        fee = float(cfg.get("BoothFeeMedium") or cfg.get("BoothFeeSmall") or 0)
    if app.get("NeedsElectricity"):
        fee += float(cfg.get("ElectricityFee") or 0)
    if app.get("NeedsTable"):
        fee += float(cfg.get("TableFee") or 0)
    return fee


# ---------- CONFIG ----------

@router.get("/api/events/{event_id}/vendor-fair/config")
def get_config(event_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT * FROM OFNEventVendorConfig WHERE EventID=:e"),
                    {"e": event_id}).fetchone()
    if not row:
        return {"configured": False, "EventID": event_id}
    cfg = dict(row._mapping)
    cfg["configured"] = True
    return cfg


@router.put("/api/events/{event_id}/vendor-fair/config")
def put_config(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    exists = db.execute(text("SELECT ConfigID FROM OFNEventVendorConfig WHERE EventID=:e"),
                       {"e": event_id}).fetchone()
    params = {
        "e": event_id, "d": body.get("Description"),
        "fs": body.get("BoothFeeSmall") or 0,
        "fm": body.get("BoothFeeMedium"),
        "fl": body.get("BoothFeeLarge"),
        "fe": body.get("ElectricityFee") or 0,
        "ft": body.get("TableFee") or 0,
        "mb": body.get("MaxBooths"),
        "aed": body.get("ApplicationEndDate"),
        "a": 1 if body.get("IsActive", True) else 0,
    }
    if exists:
        db.execute(text("""
            UPDATE OFNEventVendorConfig SET
              Description=:d, BoothFeeSmall=:fs, BoothFeeMedium=:fm, BoothFeeLarge=:fl,
              ElectricityFee=:fe, TableFee=:ft, MaxBooths=:mb,
              ApplicationEndDate=:aed, IsActive=:a, UpdatedDate=GETDATE()
            WHERE EventID=:e
        """), params)
    else:
        db.execute(text("""
            INSERT INTO OFNEventVendorConfig
              (EventID, Description, BoothFeeSmall, BoothFeeMedium, BoothFeeLarge,
               ElectricityFee, TableFee, MaxBooths, ApplicationEndDate, IsActive)
            VALUES (:e, :d, :fs, :fm, :fl, :fe, :ft, :mb, :aed, :a)
        """), params)
    db.commit()
    return {"ok": True}


# ---------- APPLICATIONS ----------

@router.get("/api/events/{event_id}/vendor-fair/applications")
def list_applications(event_id: int, people_id: int | None = None,
                      status: str | None = None, db: Session = Depends(get_db)):
    filters = ["EventID = :e"]
    params = {"e": event_id}
    if people_id:
        filters.append("PeopleID = :p")
        params["p"] = people_id
    if status:
        filters.append("Status = :s")
        params["s"] = status
    where = " AND ".join(filters)
    rows = db.execute(text(f"""
        SELECT * FROM OFNEventVendorApplications
        WHERE {where}
        ORDER BY
          CASE Status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 WHEN 'rejected' THEN 2 ELSE 3 END,
          CreatedDate DESC
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/vendor-fair/applications")
def add_application(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    cfg_row = db.execute(text("SELECT * FROM OFNEventVendorConfig WHERE EventID=:e"),
                        {"e": event_id}).fetchone()
    if not cfg_row:
        raise HTTPException(400, "Vendor fair not configured")
    cfg = dict(cfg_row._mapping)
    if cfg.get("ApplicationEndDate") and cfg["ApplicationEndDate"] < date.today():
        raise HTTPException(400, "Applications have closed")
    if not body.get("BusinessName"):
        raise HTTPException(400, "BusinessName required")
    fee = _calc_fee(cfg, body)
    r = db.execute(text("""
        INSERT INTO OFNEventVendorApplications
          (EventID, PeopleID, BusinessID, BusinessName, ContactName, ContactEmail, ContactPhone,
           BoothSize, ProductCategories, Description, WebsiteURL, NeedsElectricity, NeedsTable,
           RequestedLocation, Fee)
        VALUES (:e, :p, :b, :bn, :cn, :ce, :cp, :bs, :pc, :d, :w, :ne, :nt, :rl, :f);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "e": event_id, "p": body.get("PeopleID"), "b": body.get("BusinessID"),
        "bn": body.get("BusinessName"), "cn": body.get("ContactName"),
        "ce": body.get("ContactEmail"), "cp": body.get("ContactPhone"),
        "bs": body.get("BoothSize") or "Medium",
        "pc": body.get("ProductCategories"),
        "d": body.get("Description"), "w": body.get("WebsiteURL"),
        "ne": 1 if body.get("NeedsElectricity") else 0,
        "nt": 1 if body.get("NeedsTable") else 0,
        "rl": body.get("RequestedLocation"), "f": fee,
    })
    new_id = int(r.fetchone()[0])
    db.commit()
    return {"AppID": new_id, "Fee": fee}


@router.put("/api/events/vendor-fair/applications/{app_id}")
def update_application(app_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventVendorApplications SET
          Status=:s, BoothNumber=:bn, OrganizerNotes=:n, PaidStatus=:pd,
          UpdatedDate=GETDATE()
        WHERE AppID=:a
    """), {
        "a": app_id, "s": body.get("Status") or "pending",
        "bn": body.get("BoothNumber"), "n": body.get("OrganizerNotes"),
        "pd": body.get("PaidStatus") or "pending",
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/vendor-fair/applications/{app_id}")
def delete_application(app_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventVendorApplications WHERE AppID=:a"), {"a": app_id})
    db.commit()
    return {"ok": True}
