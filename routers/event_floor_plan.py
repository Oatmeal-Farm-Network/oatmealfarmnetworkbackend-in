"""
Interactive event floor plan.

Organizers upload a floor-plan image (PNG/JPG of the venue layout) then paint
booth rectangles over it. Each booth has a number, tier, status, and optional
assignment to a vendor application. Vendors see the same image with available
booths colored green and click one to reserve it.

Schema
  OFNEventFloorPlan : one floor plan per event (image + dimensions).
  OFNEventBooth     : one rectangle per booth (x, y, w, h in image pixels +
                      number, tier, status, assigned vendor app).
"""
import os, uuid
from database import blank_to_none
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List
from database import get_db, SessionLocal

router = APIRouter()

GCS_BUCKET = os.getenv("GCS_BUCKET", "ofn-uploads").strip()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OFNEventFloorPlan')
        CREATE TABLE OFNEventFloorPlan (
            FloorPlanID  INT IDENTITY(1,1) PRIMARY KEY,
            EventID      INT NOT NULL UNIQUE,
            Name         NVARCHAR(200),
            ImageURL     NVARCHAR(1000),
            ImageWidth   INT,
            ImageHeight  INT,
            ScaleHint    NVARCHAR(200),       -- "1 grid square = 10 ft" type free-text
            CreatedDate  DATETIME DEFAULT GETDATE(),
            UpdatedDate  DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OFNEventBooth')
        CREATE TABLE OFNEventBooth (
            BoothID         INT IDENTITY(1,1) PRIMARY KEY,
            EventID         INT NOT NULL,
            FloorPlanID     INT NULL,
            BoothNumber     NVARCHAR(50) NOT NULL,
            X               FLOAT NOT NULL,    -- top-left, in image pixels
            Y               FLOAT NOT NULL,
            Width           FLOAT NOT NULL,
            Height          FLOAT NOT NULL,
            Tier            NVARCHAR(50) DEFAULT 'standard',  -- premium / standard / corner / aisle / blocked
            Status          NVARCHAR(50) DEFAULT 'available', -- available / reserved / sold / blocked
            AssignedAppID   INT NULL,                          -- → OFNEventVendorApplications.AppID
            Color           NVARCHAR(20),                      -- optional explicit color override
            Label           NVARCHAR(100),                     -- optional secondary label
            Price           DECIMAL(10,2),                     -- per-booth override of tier pricing
            CreatedDate     DATETIME DEFAULT GETDATE(),
            UpdatedDate     DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sys.indexes
                        WHERE name='IX_OFNEventBooth_Event'
                          AND object_id = OBJECT_ID('OFNEventBooth'))
        CREATE INDEX IX_OFNEventBooth_Event
                  ON OFNEventBooth (EventID, Status)
    """))
    db.commit()


try:
    with SessionLocal() as _db:
        ensure_tables(_db)
except Exception as e:
    print(f"[event_floor_plan] Table ensure warning: {e}")


# ── Floor plan config + image upload ────────────────────────────────────────

@router.get("/api/events/{event_id}/floor-plan")
def get_floor_plan(event_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT FloorPlanID, EventID, Name, ImageURL, ImageWidth, ImageHeight, ScaleHint
          FROM OFNEventFloorPlan WHERE EventID = :eid
    """), {"eid": event_id}).fetchone()
    if not row:
        return {"event_id": event_id, "floor_plan": None}
    return {"event_id": event_id, "floor_plan": dict(row._mapping)}


@router.put("/api/events/{event_id}/floor-plan")
def upsert_floor_plan(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    existing = db.execute(text(
        "SELECT FloorPlanID FROM OFNEventFloorPlan WHERE EventID = :eid"
    ), {"eid": event_id}).fetchone()
    params = {
        "eid": event_id,
        "n":   body.get("Name"),
        "u":   body.get("ImageURL"),
        "w":   body.get("ImageWidth"),
        "h":   body.get("ImageHeight"),
        "sh":  body.get("ScaleHint"),
    }
    if existing:
        db.execute(text("""
            UPDATE OFNEventFloorPlan SET
                Name=:n, ImageURL=:u, ImageWidth=:w, ImageHeight=:h, ScaleHint=:sh,
                UpdatedDate=GETDATE()
            WHERE EventID=:eid
        """), params)
    else:
        db.execute(text("""
            INSERT INTO OFNEventFloorPlan (EventID, Name, ImageURL, ImageWidth, ImageHeight, ScaleHint)
            VALUES (:eid, :n, :u, :w, :h, :sh)
        """), params)
    db.commit()
    return {"ok": True}


@router.post("/api/events/{event_id}/floor-plan/upload-image")
async def upload_floor_plan_image(event_id: int, file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")
    content = await file.read()
    ext = (file.filename or "img").rsplit(".", 1)[-1].lower()
    if ext not in {"jpg", "jpeg", "png", "gif", "webp", "svg"}:
        ext = "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(f"events/floor-plans/{event_id}/{filename}")
        blob.upload_from_string(content, content_type=file.content_type)
        url = f"https://storage.googleapis.com/{GCS_BUCKET}/events/floor-plans/{event_id}/{filename}"
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {e}")
    return {"url": url}


# ── Booths ──────────────────────────────────────────────────────────────────

@router.get("/api/events/{event_id}/floor-plan/booths")
def list_booths(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT b.BoothID, b.EventID, b.BoothNumber, b.X, b.Y, b.Width, b.Height,
               b.Tier, b.Status, b.AssignedAppID, b.Color, b.Label, b.Price,
               a.BusinessName AS AssignedBusinessName
          FROM OFNEventBooth b
          LEFT JOIN OFNEventVendorApplications a ON a.AppID = b.AssignedAppID
         WHERE b.EventID = :eid
         ORDER BY b.BoothNumber
    """), {"eid": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/floor-plan/booths")
def create_booth(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    if not body.get("BoothNumber"):
        raise HTTPException(400, "BoothNumber is required")
    res = db.execute(text("""
        INSERT INTO OFNEventBooth
            (EventID, FloorPlanID, BoothNumber, X, Y, Width, Height,
             Tier, Status, AssignedAppID, Color, Label, Price)
        OUTPUT INSERTED.BoothID
        VALUES (:eid, :fid, :bn, :x, :y, :w, :h,
                :tier, :st, :appid, :color, :label, :price)
    """), {
        "eid":   event_id,
        "fid":   body.get("FloorPlanID"),
        "bn":    body["BoothNumber"],
        "x":     body.get("X", 0),
        "y":     body.get("Y", 0),
        "w":     body.get("Width", 60),
        "h":     body.get("Height", 60),
        "tier":  body.get("Tier", "standard"),
        "st":    body.get("Status", "available"),
        "appid": body.get("AssignedAppID"),
        "color": body.get("Color"),
        "label": body.get("Label"),
        "price": body.get("Price"),
    }).fetchone()
    db.commit()
    return {"BoothID": int(res.BoothID)}


@router.post("/api/events/{event_id}/floor-plan/booths/bulk")
def bulk_create_booths(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    """Quick-fill from a grid. body = {start_x, start_y, cols, rows, width,
    height, gap, prefix, tier}. Lays out a grid of N×M booths and numbers them
    `<prefix>1, <prefix>2, ...`."""
    cols = max(1, int(body.get("cols", 1)))
    rows = max(1, int(body.get("rows", 1)))
    w    = float(body.get("width",  60))
    h    = float(body.get("height", 60))
    gap  = float(body.get("gap",     8))
    sx   = float(body.get("start_x", 0))
    sy   = float(body.get("start_y", 0))
    prefix = (body.get("prefix") or "B").strip()
    tier   = body.get("tier", "standard")

    # Find next available number suffix
    max_row = db.execute(text("""
        SELECT TOP 1 BoothNumber FROM OFNEventBooth
         WHERE EventID = :eid AND BoothNumber LIKE :pat
         ORDER BY LEN(BoothNumber) DESC, BoothNumber DESC
    """), {"eid": event_id, "pat": f"{prefix}%"}).fetchone()
    start_idx = 1
    if max_row and max_row.BoothNumber:
        suffix = max_row.BoothNumber[len(prefix):]
        if suffix.isdigit():
            start_idx = int(suffix) + 1

    n = 0
    for r in range(rows):
        for c in range(cols):
            x = sx + c * (w + gap)
            y = sy + r * (h + gap)
            booth_no = f"{prefix}{start_idx + n}"
            db.execute(text("""
                INSERT INTO OFNEventBooth
                    (EventID, BoothNumber, X, Y, Width, Height, Tier, Status)
                VALUES (:eid, :bn, :x, :y, :w, :h, :tier, 'available')
            """), {"eid": event_id, "bn": booth_no,
                   "x": x, "y": y, "w": w, "h": h, "tier": tier})
            n += 1
    db.commit()
    return {"ok": True, "created": n, "first_number": f"{prefix}{start_idx}",
            "last_number": f"{prefix}{start_idx + n - 1}"}


@router.put("/api/events/floor-plan/booths/{booth_id}")
def update_booth(booth_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventBooth SET
            BoothNumber=:bn, X=:x, Y=:y, Width=:w, Height=:h,
            Tier=:tier, Status=:st, AssignedAppID=:appid,
            Color=:color, Label=:label, Price=:price, UpdatedDate=GETDATE()
        WHERE BoothID=:bid
    """), {
        "bid":   booth_id,
        "bn":    body.get("BoothNumber"),
        "x":     body.get("X", 0),
        "y":     body.get("Y", 0),
        "w":     body.get("Width", 60),
        "h":     body.get("Height", 60),
        "tier":  body.get("Tier", "standard"),
        "st":    body.get("Status", "available"),
        "appid": body.get("AssignedAppID"),
        "color": body.get("Color"),
        "label": body.get("Label"),
        "price": body.get("Price"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/floor-plan/booths/{booth_id}")
def delete_booth(booth_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventBooth WHERE BoothID = :bid"), {"bid": booth_id})
    db.commit()
    return {"ok": True}


@router.post("/api/events/floor-plan/booths/{booth_id}/reserve")
def reserve_booth(booth_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    """Vendor-side: claim a booth. body = {AppID, expected_status='available'}.
    Atomic — fails if the booth's status no longer matches expectation."""
    app_id = body.get("AppID")
    if not app_id:
        raise HTTPException(400, "AppID required")
    expected = body.get("expected_status", "available")

    booth = db.execute(text(
        "SELECT BoothID, Status FROM OFNEventBooth WHERE BoothID = :bid"
    ), {"bid": booth_id}).fetchone()
    if not booth:
        raise HTTPException(404, "Booth not found")
    if booth.Status != expected:
        raise HTTPException(409,
            f"Booth is no longer {expected} (current: {booth.Status}). Refresh the floor plan and try another.")

    db.execute(text("""
        UPDATE OFNEventBooth SET
            Status='reserved', AssignedAppID=:appid, UpdatedDate=GETDATE()
        WHERE BoothID = :bid
    """), {"bid": booth_id, "appid": int(app_id)})
    # Sync the application's BoothNumber field so existing vendor-fair UI shows it
    booth_row = db.execute(
        text("SELECT BoothNumber FROM OFNEventBooth WHERE BoothID = :bid"),
        {"bid": booth_id},
    ).fetchone()
    if booth_row:
        db.execute(
            text("UPDATE OFNEventVendorApplications SET BoothNumber=:bn WHERE AppID=:aid"),
            {"bn": booth_row.BoothNumber, "aid": int(app_id)},
        )
    db.commit()
    return {"ok": True, "BoothID": booth_id}


@router.get("/api/events/{event_id}/floor-plan/summary")
def floor_plan_summary(event_id: int, db: Session = Depends(get_db)):
    """One-call dashboard: total booths, by status, by tier."""
    by_status = db.execute(text("""
        SELECT Status, COUNT(1) AS n FROM OFNEventBooth
         WHERE EventID = :eid GROUP BY Status
    """), {"eid": event_id}).fetchall()
    by_tier = db.execute(text("""
        SELECT Tier, COUNT(1) AS n FROM OFNEventBooth
         WHERE EventID = :eid GROUP BY Tier
    """), {"eid": event_id}).fetchall()
    return {
        "event_id":   event_id,
        "total":      sum(int(r.n) for r in by_status),
        "by_status":  {r.Status: int(r.n) for r in by_status},
        "by_tier":    {r.Tier:   int(r.n) for r in by_tier},
    }
