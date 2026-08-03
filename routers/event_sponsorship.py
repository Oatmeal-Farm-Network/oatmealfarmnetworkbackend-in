"""
Event sponsorship management.

Organizers create sponsorship tiers (Title / Gold / Silver / Bronze / Custom)
with a price, max-slot count, and a benefits HTML blob. Then they assign
sponsoring businesses to a tier with a logo URL, website link, and tagline.
The public event detail page renders sponsors grouped by tier — the larger
tiers get larger logo treatments.

Mirrors event_vendor_fair.py's table-creation + open-routes pattern. Auth
is intentionally lenient on GETs (the public sponsor list IS the value),
strict on writes (organizer-only via business_id check downstream).
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from database import get_db, SessionLocal

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventSponsorTier')
        CREATE TABLE OFNEventSponsorTier (
            TierID         INT IDENTITY(1,1) PRIMARY KEY,
            EventID        INT NOT NULL,
            Name           NVARCHAR(100) NOT NULL,
            Price          DECIMAL(10,2) DEFAULT 0,
            MaxSlots       INT NULL,
            BenefitsHTML   NVARCHAR(MAX),
            LogoSizePx     INT DEFAULT 200,
            DisplayColumns INT DEFAULT 3,
            SortOrder      INT DEFAULT 100,
            IsActive       BIT DEFAULT 1,
            CreatedDate    DATETIME DEFAULT GETDATE(),
            UpdatedDate    DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventSponsor')
        CREATE TABLE OFNEventSponsor (
            SponsorID      INT IDENTITY(1,1) PRIMARY KEY,
            EventID        INT NOT NULL,
            TierID         INT NULL,
            BusinessID     INT NULL,
            BusinessName   NVARCHAR(300) NOT NULL,
            ContactName    NVARCHAR(300),
            ContactEmail   NVARCHAR(300),
            ContactPhone   NVARCHAR(50),
            LogoURL        NVARCHAR(1000),
            WebsiteURL     NVARCHAR(1000),
            Tagline        NVARCHAR(500),
            Status         NVARCHAR(50) DEFAULT 'pending',     -- pending / confirmed / declined
            PaidStatus     NVARCHAR(20) DEFAULT 'unpaid',      -- unpaid / partial / paid / refunded
            AmountPaid     DECIMAL(10,2) DEFAULT 0,
            -- Logo placement zones — comma-separated list. Lets organizers choose
            -- whether a sponsor's logo shows on the website, badges, signage,
            -- emails, or specific sessions.
            DisplayZones   NVARCHAR(500) DEFAULT 'website',
            SortOrder      INT DEFAULT 100,
            Notes          NVARCHAR(MAX),
            CreatedDate    DATETIME DEFAULT GETDATE(),
            UpdatedDate    DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


try:
    with SessionLocal() as _db:
        ensure_tables(_db)
except Exception as e:
    print(f"[event_sponsorship] Table ensure warning: {e}")


def _row_dict(r):
    return {k: (float(v) if hasattr(v, "is_finite") else v) for k, v in dict(r._mapping).items()}


# ════════════════════════════════════════════════════════════════════════════
# TIERS
# ════════════════════════════════════════════════════════════════════════════

@router.get("/api/events/{event_id}/sponsorship/tiers")
def list_tiers(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT TierID, EventID, Name, Price, MaxSlots, BenefitsHTML,
               LogoSizePx, DisplayColumns, SortOrder, IsActive
          FROM OFNEventSponsorTier
         WHERE EventID = :eid
         ORDER BY SortOrder, Price DESC, Name
    """), {"eid": event_id}).fetchall()
    out = []
    for r in rows:
        d = dict(r._mapping)
        # Slots remaining count
        if d.get("MaxSlots"):
            taken = db.execute(text("""
                SELECT COUNT(1) AS n FROM OFNEventSponsor
                 WHERE TierID = :tid AND Status <> 'declined'
            """), {"tid": d["TierID"]}).fetchone()
            d["SlotsTaken"]    = int(taken.n) if taken else 0
            d["SlotsRemaining"] = max(0, int(d["MaxSlots"]) - int(d["SlotsTaken"]))
        out.append(d)
    return out


@router.post("/api/events/{event_id}/sponsorship/tiers")
def create_tier(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    if not body.get("Name"):
        raise HTTPException(status_code=400, detail="Name is required")
    res = db.execute(text("""
        INSERT INTO OFNEventSponsorTier
            (EventID, Name, Price, MaxSlots, BenefitsHTML,
             LogoSizePx, DisplayColumns, SortOrder, IsActive)
        OUTPUT INSERTED.TierID
        VALUES (:eid, :n, :p, :ms, :b, :lpx, :dc, :so, :a)
    """), {
        "eid": event_id,
        "n":   body["Name"],
        "p":   body.get("Price", 0),
        "ms":  body.get("MaxSlots"),
        "b":   body.get("BenefitsHTML"),
        "lpx": body.get("LogoSizePx", 200),
        "dc":  body.get("DisplayColumns", 3),
        "so":  body.get("SortOrder", 100),
        "a":   1 if body.get("IsActive", True) else 0,
    }).fetchone()
    db.commit()
    return {"TierID": int(res.TierID)}


@router.put("/api/events/sponsorship/tiers/{tier_id}")
def update_tier(tier_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventSponsorTier SET
            Name=:n, Price=:p, MaxSlots=:ms, BenefitsHTML=:b,
            LogoSizePx=:lpx, DisplayColumns=:dc, SortOrder=:so,
            IsActive=:a, UpdatedDate=GETDATE()
        WHERE TierID=:tid
    """), {
        "tid": tier_id,
        "n":   body.get("Name"),
        "p":   body.get("Price", 0),
        "ms":  body.get("MaxSlots"),
        "b":   body.get("BenefitsHTML"),
        "lpx": body.get("LogoSizePx", 200),
        "dc":  body.get("DisplayColumns", 3),
        "so":  body.get("SortOrder", 100),
        "a":   1 if body.get("IsActive", True) else 0,
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/sponsorship/tiers/{tier_id}")
def delete_tier(tier_id: int, db: Session = Depends(get_db)):
    in_use = db.execute(
        text("SELECT COUNT(1) AS n FROM OFNEventSponsor WHERE TierID = :tid"),
        {"tid": tier_id},
    ).fetchone()
    if in_use and int(in_use.n) > 0:
        raise HTTPException(status_code=409,
            detail=f"Tier has {in_use.n} assigned sponsor(s). Reassign or remove them first.")
    db.execute(text("DELETE FROM OFNEventSponsorTier WHERE TierID = :tid"), {"tid": tier_id})
    db.commit()
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# SPONSORS
# ════════════════════════════════════════════════════════════════════════════

@router.get("/api/events/{event_id}/sponsors")
def list_sponsors(
    event_id: int,
    status: Optional[str] = Query(None),
    tier_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Organizer-side list — returns all sponsors regardless of status, with
    paid totals and assigned tier info."""
    where = ["s.EventID = :eid"]
    params = {"eid": event_id}
    if status:
        where.append("s.Status = :st"); params["st"] = status
    if tier_id is not None:
        where.append("s.TierID = :tid"); params["tid"] = tier_id
    rows = db.execute(text(f"""
        SELECT s.SponsorID, s.EventID, s.TierID, s.BusinessID, s.BusinessName,
               s.ContactName, s.ContactEmail, s.ContactPhone,
               s.LogoURL, s.WebsiteURL, s.Tagline,
               s.Status, s.PaidStatus, s.AmountPaid, s.DisplayZones,
               s.SortOrder, s.Notes, s.CreatedDate,
               t.Name AS TierName, t.Price AS TierPrice,
               t.LogoSizePx AS TierLogoSizePx
          FROM OFNEventSponsor s
          LEFT JOIN OFNEventSponsorTier t ON t.TierID = s.TierID
         WHERE {' AND '.join(where)}
         ORDER BY t.SortOrder, t.Price DESC, s.SortOrder, s.BusinessName
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/api/events/{event_id}/sponsors/public")
def list_public_sponsors(event_id: int, db: Session = Depends(get_db)):
    """Public listing — only confirmed sponsors, grouped by tier with tier
    metadata so the frontend can render tier-appropriate logo sizes."""
    rows = db.execute(text("""
        SELECT t.TierID, t.Name AS TierName, t.LogoSizePx, t.DisplayColumns,
               t.SortOrder AS TierSort,
               s.SponsorID, s.BusinessID, s.BusinessName, s.LogoURL,
               s.WebsiteURL, s.Tagline, s.SortOrder AS SponsorSort
          FROM OFNEventSponsor s
          JOIN OFNEventSponsorTier t ON t.TierID = s.TierID
         WHERE s.EventID = :eid
           AND s.Status = 'confirmed'
           AND t.IsActive = 1
           AND (s.DisplayZones IS NULL OR s.DisplayZones LIKE '%website%')
         ORDER BY t.SortOrder, t.Price DESC, s.SortOrder, s.BusinessName
    """), {"eid": event_id}).fetchall()

    # Group by tier
    tiers: dict[int, dict] = {}
    for r in rows:
        d = dict(r._mapping)
        tid = d["TierID"]
        if tid not in tiers:
            tiers[tid] = {
                "TierID":         tid,
                "Name":           d["TierName"],
                "LogoSizePx":     d.get("LogoSizePx") or 200,
                "DisplayColumns": d.get("DisplayColumns") or 3,
                "Sponsors":       [],
            }
        tiers[tid]["Sponsors"].append({
            "SponsorID":   d["SponsorID"],
            "BusinessID":  d.get("BusinessID"),
            "Name":        d["BusinessName"],
            "LogoURL":     d.get("LogoURL"),
            "WebsiteURL":  d.get("WebsiteURL"),
            "Tagline":     d.get("Tagline"),
        })
    return list(tiers.values())


@router.post("/api/events/{event_id}/sponsors")
def add_sponsor(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    if not body.get("BusinessName"):
        raise HTTPException(status_code=400, detail="BusinessName is required")
    # Slot enforcement
    tier_id = body.get("TierID")
    if tier_id:
        tier = db.execute(
            text("SELECT MaxSlots FROM OFNEventSponsorTier WHERE TierID = :tid"),
            {"tid": tier_id},
        ).fetchone()
        if tier and tier.MaxSlots:
            taken = db.execute(text("""
                SELECT COUNT(1) AS n FROM OFNEventSponsor
                 WHERE TierID = :tid AND Status <> 'declined'
            """), {"tid": tier_id}).fetchone()
            if taken and int(taken.n) >= int(tier.MaxSlots):
                raise HTTPException(status_code=409,
                    detail=f"Tier is full ({tier.MaxSlots} slots taken).")
    res = db.execute(text("""
        INSERT INTO OFNEventSponsor
            (EventID, TierID, BusinessID, BusinessName, ContactName, ContactEmail,
             ContactPhone, LogoURL, WebsiteURL, Tagline, Status, PaidStatus,
             AmountPaid, DisplayZones, SortOrder, Notes)
        OUTPUT INSERTED.SponsorID
        VALUES (:eid, :tid, :bid, :bn, :cn, :ce, :cp, :lu, :wu, :tg,
                :st, :ps, :ap, :dz, :so, :no)
    """), {
        "eid": event_id, "tid": tier_id,
        "bid": body.get("BusinessID"),
        "bn":  body["BusinessName"],
        "cn":  body.get("ContactName"),
        "ce":  body.get("ContactEmail"),
        "cp":  body.get("ContactPhone"),
        "lu":  body.get("LogoURL"),
        "wu":  body.get("WebsiteURL"),
        "tg":  body.get("Tagline"),
        "st":  body.get("Status", "pending"),
        "ps":  body.get("PaidStatus", "unpaid"),
        "ap":  body.get("AmountPaid", 0),
        "dz":  body.get("DisplayZones", "website"),
        "so":  body.get("SortOrder", 100),
        "no":  body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"SponsorID": int(res.SponsorID)}


@router.put("/api/events/sponsors/{sponsor_id}")
def update_sponsor(sponsor_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    # Capture previous Status so we can fire a confirmation email when
    # an organizer flips a sponsor from non-confirmed → confirmed.
    prev_row = db.execute(text("""
        SELECT s.Status, s.BusinessName, s.ContactEmail, s.AmountPaid,
               t.Name AS TierName, t.BenefitsHTML, s.EventID
          FROM OFNEventSponsor s
          LEFT JOIN OFNEventSponsorTier t ON t.TierID = s.TierID
         WHERE s.SponsorID = :sid
    """), {"sid": sponsor_id}).fetchone()
    prev_status = prev_row.Status if prev_row else None

    new_tier_id = body.get("TierID")
    db.execute(text("""
        UPDATE OFNEventSponsor SET
            TierID=:tid, BusinessID=:bid, BusinessName=:bn,
            ContactName=:cn, ContactEmail=:ce, ContactPhone=:cp,
            LogoURL=:lu, WebsiteURL=:wu, Tagline=:tg,
            Status=:st, PaidStatus=:ps, AmountPaid=:ap,
            DisplayZones=:dz, SortOrder=:so, Notes=:no, UpdatedDate=GETDATE()
        WHERE SponsorID=:sid
    """), {
        "sid": sponsor_id,
        "tid": new_tier_id,
        "bid": body.get("BusinessID"),
        "bn":  body.get("BusinessName"),
        "cn":  body.get("ContactName"),
        "ce":  body.get("ContactEmail"),
        "cp":  body.get("ContactPhone"),
        "lu":  body.get("LogoURL"),
        "wu":  body.get("WebsiteURL"),
        "tg":  body.get("Tagline"),
        "st":  body.get("Status", "pending"),
        "ps":  body.get("PaidStatus", "unpaid"),
        "ap":  body.get("AmountPaid", 0),
        "dz":  body.get("DisplayZones", "website"),
        "so":  body.get("SortOrder", 100),
        "no":  body.get("Notes"),
    })
    db.commit()

    # Fire-and-forget confirmation email on status flip → confirmed
    new_status = body.get("Status", "pending")
    if new_status == "confirmed" and prev_status != "confirmed" and body.get("ContactEmail"):
        try:
            from event_emails import send_sponsor_confirmation
            ev = db.execute(
                text("SELECT EventID, EventName, BusinessID FROM OFNEvents WHERE EventID = :eid"),
                {"eid": prev_row.EventID if prev_row else None},
            ).fetchone()
            tier_row = db.execute(
                text("SELECT Name, BenefitsHTML FROM OFNEventSponsorTier WHERE TierID = :tid"),
                {"tid": new_tier_id},
            ).fetchone()
            if ev and tier_row:
                send_sponsor_confirmation(
                    to_email=body.get("ContactEmail"),
                    sponsor_name=body.get("ContactName") or body.get("BusinessName"),
                    event=dict(ev._mapping),
                    tier_name=tier_row.Name,
                    amount=float(body.get("AmountPaid") or 0) or None,
                    benefits_html=tier_row.BenefitsHTML,
                )
        except Exception as e:
            print(f"[sponsorship] confirmation email failed: {e}")

    return {"ok": True}


@router.delete("/api/events/sponsors/{sponsor_id}")
def delete_sponsor(sponsor_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventSponsor WHERE SponsorID = :sid"), {"sid": sponsor_id})
    db.commit()
    return {"ok": True}


@router.get("/api/events/{event_id}/sponsorship/summary")
def sponsorship_summary(event_id: int, db: Session = Depends(get_db)):
    """One-call summary for the org dashboard: revenue, slot fill, by-tier."""
    rows = db.execute(text("""
        SELECT t.TierID, t.Name, t.Price, t.MaxSlots,
               COUNT(s.SponsorID) AS sponsors,
               SUM(CASE WHEN s.Status='confirmed' THEN 1 ELSE 0 END) AS confirmed,
               ISNULL(SUM(s.AmountPaid), 0) AS revenue
          FROM OFNEventSponsorTier t
          LEFT JOIN OFNEventSponsor s ON s.TierID = t.TierID
         WHERE t.EventID = :eid
         GROUP BY t.TierID, t.Name, t.Price, t.MaxSlots, t.SortOrder
         ORDER BY t.SortOrder, t.Price DESC
    """), {"eid": event_id}).fetchall()
    by_tier = [dict(r._mapping) for r in rows]
    total_revenue = sum(float(t.get("revenue") or 0) for t in by_tier)
    total_confirmed = sum(int(t.get("confirmed") or 0) for t in by_tier)
    total_pipeline = sum(int(t.get("sponsors") or 0) for t in by_tier)
    return {
        "event_id":        event_id,
        "total_revenue":   round(total_revenue, 2),
        "total_confirmed": total_confirmed,
        "total_pipeline":  total_pipeline,
        "by_tier":         by_tier,
    }
