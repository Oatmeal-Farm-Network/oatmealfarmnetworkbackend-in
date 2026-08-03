"""
Certificate of Insurance (COI) upload + tracking.

Sponsors and exhibitors upload a PDF/image of their COI naming the event host
as additional insured. Each upload has an effective date + expiry date and a
status (pending / approved / rejected / expired).

Schema
  OFNEventCOI : one row per uploaded document. EntityType + EntityID points at
                either OFNEventSponsor or OFNEventVendorApplications (or any
                other future entity).

Auto-expiry: a NULL expiry never expires; a past-date ExpiryDate flips to
'expired' the next time anyone reads the row (lazy refresh — no scheduled job
needed).
"""
import os, uuid
from database import blank_to_none
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from database import get_db, SessionLocal

router = APIRouter()

GCS_BUCKET = os.getenv("GCS_BUCKET", "ofn-uploads").strip()
ALLOWED_ENTITY_TYPES = {"sponsor", "vendor", "exhibitor", "speaker", "other"}


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OFNEventCOI')
        CREATE TABLE OFNEventCOI (
            COIID           INT IDENTITY(1,1) PRIMARY KEY,
            EventID         INT NOT NULL,
            EntityType      NVARCHAR(40) NOT NULL,    -- sponsor / vendor / exhibitor / speaker / other
            EntityID        INT NOT NULL,             -- → OFNEventSponsor.SponsorID or OFNEventVendorApplications.AppID
            EntityName      NVARCHAR(300),            -- snapshot for fast list rendering
            FileURL         NVARCHAR(1000) NOT NULL,
            FileName        NVARCHAR(300),
            EffectiveDate   DATE,
            ExpiryDate      DATE,
            CarrierName     NVARCHAR(300),
            PolicyNumber    NVARCHAR(100),
            CoverageAmount  DECIMAL(15,2),
            Status          NVARCHAR(40) DEFAULT 'pending', -- pending / approved / rejected / expired
            ReviewerNotes   NVARCHAR(MAX),
            UploadedByPeopleID INT,
            UploadedAt      DATETIME DEFAULT GETDATE(),
            UpdatedAt       DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sys.indexes
                        WHERE name='IX_OFNEventCOI_Event'
                          AND object_id = OBJECT_ID('OFNEventCOI'))
        CREATE INDEX IX_OFNEventCOI_Event
                  ON OFNEventCOI (EventID, EntityType, EntityID, Status)
    """))
    db.commit()


try:
    with SessionLocal() as _db:
        ensure_tables(_db)
except Exception as e:
    print(f"[event_coi] Table ensure warning: {e}")


def _refresh_status_if_expired(db: Session, row: dict) -> dict:
    """Lazy expiry — flip Status to 'expired' if ExpiryDate < today and the
    current status is approved/pending."""
    if not row:
        return row
    expiry = row.get("ExpiryDate")
    if expiry and row.get("Status") in ("approved", "pending"):
        try:
            exp_date = expiry if isinstance(expiry, date) else date.fromisoformat(str(expiry)[:10])
            if exp_date < date.today():
                db.execute(
                    text("UPDATE OFNEventCOI SET Status='expired' WHERE COIID=:cid"),
                    {"cid": row["COIID"]},
                )
                db.commit()
                row = {**row, "Status": "expired"}
        except Exception:
            pass
    return row


def _expiry_warning_days(expiry) -> Optional[int]:
    """Return days-until-expiry; negative = expired. None if no expiry set."""
    if not expiry:
        return None
    try:
        exp = expiry if isinstance(expiry, date) else date.fromisoformat(str(expiry)[:10])
        return (exp - date.today()).days
    except Exception:
        return None


# ── Upload (multipart) ──────────────────────────────────────────────────────

@router.post("/api/events/{event_id}/coi/upload")
async def upload_coi(
    event_id: int,
    file: UploadFile = File(...),
    entity_type: str = Form(...),
    entity_id: int   = Form(...),
    entity_name: Optional[str]   = Form(None),
    effective_date: Optional[str] = Form(None),
    expiry_date: Optional[str]    = Form(None),
    carrier_name: Optional[str]   = Form(None),
    policy_number: Optional[str]  = Form(None),
    coverage_amount: Optional[float] = Form(None),
    uploaded_by: Optional[int]    = Form(None),
    db: Session = Depends(get_db),
):
    if entity_type not in ALLOWED_ENTITY_TYPES:
        raise HTTPException(400, f"entity_type must be one of {sorted(ALLOWED_ENTITY_TYPES)}")
    if not file.content_type:
        raise HTTPException(400, "Missing file content type")
    # COIs are typically PDFs but JPEGs/PNGs also acceptable
    if not (file.content_type.startswith("application/pdf")
            or file.content_type.startswith("image/")):
        raise HTTPException(400, "File must be a PDF or image")

    content = await file.read()
    ext = (file.filename or "coi").rsplit(".", 1)[-1].lower()
    if ext not in {"pdf", "jpg", "jpeg", "png", "webp"}:
        ext = "pdf"
    storage_name = f"{uuid.uuid4().hex}.{ext}"

    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(f"events/coi/{event_id}/{entity_type}/{entity_id}/{storage_name}")
        blob.upload_from_string(content, content_type=file.content_type)
        url = (f"https://storage.googleapis.com/{GCS_BUCKET}"
               f"/events/coi/{event_id}/{entity_type}/{entity_id}/{storage_name}")
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {e}")

    res = db.execute(text("""
        INSERT INTO OFNEventCOI
            (EventID, EntityType, EntityID, EntityName, FileURL, FileName,
             EffectiveDate, ExpiryDate, CarrierName, PolicyNumber,
             CoverageAmount, UploadedByPeopleID, Status)
        OUTPUT INSERTED.COIID
        VALUES (:eid, :et, :eid2, :en, :fu, :fn,
                :ef, :ex, :cn, :pn, :ca, :ub, 'pending')
    """), {
        "eid":  event_id,
        "et":   entity_type,
        "eid2": int(entity_id),
        "en":   entity_name,
        "fu":   url,
        "fn":   file.filename,
        "ef":   effective_date,
        "ex":   expiry_date,
        "cn":   carrier_name,
        "pn":   policy_number,
        "ca":   coverage_amount,
        "ub":   uploaded_by,
    }).fetchone()
    db.commit()
    return {"COIID": int(res.COIID), "FileURL": url}


# ── Read / list / update / delete ───────────────────────────────────────────

@router.get("/api/events/{event_id}/coi")
def list_coi(
    event_id: int,
    entity_type: Optional[str] = Query(None),
    entity_id:   Optional[int] = Query(None),
    status:      Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    where = ["EventID = :eid"]
    params = {"eid": event_id}
    if entity_type:
        where.append("EntityType = :et"); params["et"] = entity_type
    if entity_id is not None:
        where.append("EntityID = :eid2"); params["eid2"] = entity_id
    if status:
        where.append("Status = :st"); params["st"] = status
    rows = db.execute(text(f"""
        SELECT COIID, EventID, EntityType, EntityID, EntityName, FileURL, FileName,
               EffectiveDate, ExpiryDate, CarrierName, PolicyNumber,
               CoverageAmount, Status, ReviewerNotes, UploadedAt
          FROM OFNEventCOI
         WHERE {' AND '.join(where)}
         ORDER BY UploadedAt DESC
    """), params).fetchall()
    out = []
    for r in rows:
        d = dict(r._mapping)
        d = _refresh_status_if_expired(db, d)
        d["days_until_expiry"] = _expiry_warning_days(d.get("ExpiryDate"))
        out.append(d)
    return out


@router.put("/api/events/coi/{coi_id}")
def update_coi(coi_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventCOI SET
            EffectiveDate=:ef, ExpiryDate=:ex,
            CarrierName=:cn, PolicyNumber=:pn, CoverageAmount=:ca,
            Status=:st, ReviewerNotes=:rn, UpdatedAt=GETDATE()
        WHERE COIID=:cid
    """), {
        "cid": coi_id,
        "ef":  body.get("EffectiveDate"),
        "ex":  body.get("ExpiryDate"),
        "cn":  body.get("CarrierName"),
        "pn":  body.get("PolicyNumber"),
        "ca":  body.get("CoverageAmount"),
        "st":  body.get("Status", "pending"),
        "rn":  body.get("ReviewerNotes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/coi/{coi_id}")
def delete_coi(coi_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventCOI WHERE COIID = :cid"), {"cid": coi_id})
    db.commit()
    return {"ok": True}


@router.get("/api/events/{event_id}/coi/summary")
def coi_summary(event_id: int, db: Session = Depends(get_db)):
    """Org dashboard: count by status + count expiring within 30 days."""
    rows = db.execute(text("""
        SELECT Status, COUNT(1) AS n FROM OFNEventCOI
         WHERE EventID = :eid GROUP BY Status
    """), {"eid": event_id}).fetchall()
    expiring = db.execute(text("""
        SELECT COUNT(1) AS n FROM OFNEventCOI
         WHERE EventID = :eid AND Status='approved'
           AND ExpiryDate IS NOT NULL
           AND ExpiryDate BETWEEN CAST(GETDATE() AS DATE)
                              AND DATEADD(day, 30, CAST(GETDATE() AS DATE))
    """), {"eid": event_id}).fetchone()
    return {
        "event_id": event_id,
        "by_status": {r.Status: int(r.n) for r in rows},
        "expiring_in_30_days": int(expiring.n) if expiring else 0,
    }
