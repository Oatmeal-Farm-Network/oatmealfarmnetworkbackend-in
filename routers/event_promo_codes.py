"""
Promo / discount codes for event carts.

Codes can be percent-off or flat-off, optionally scoped to a specific feature
(e.g. 10% off fleece entries only), gated by minimum cart total, date-bounded,
and capped by total uses. Early-bird pricing is just a promo code with an
`auto_apply` flag — the wizard picks it up without the user typing anything.
"""
import random
import string
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventPromoCodes')
        CREATE TABLE OFNEventPromoCodes (
            CodeID        INT IDENTITY(1,1) PRIMARY KEY,
            EventID       INT NOT NULL,
            Code          NVARCHAR(50) NOT NULL,
            Description   NVARCHAR(300),
            DiscountType  NVARCHAR(20) NOT NULL DEFAULT 'percent', -- percent | flat
            DiscountValue DECIMAL(10,2) NOT NULL DEFAULT 0,
            FeatureScope  NVARCHAR(50),     -- NULL = whole cart; else limits to one FeatureKey
            MinCartTotal  DECIMAL(10,2),
            MaxUses       INT,
            UsesSoFar     INT NOT NULL DEFAULT 0,
            ValidFrom     DATETIME,
            ValidUntil    DATETIME,
            AutoApply     BIT NOT NULL DEFAULT 0,
            IsActive      BIT NOT NULL DEFAULT 1,
            CreatedDate   DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_OFNEventPromoCodes_Event_Code')
        CREATE UNIQUE INDEX IX_OFNEventPromoCodes_Event_Code
               ON OFNEventPromoCodes(EventID, Code)
    """))
    for col, ddl in [
        ("PromoCodeID",     "INT NULL"),
        ("PromoCode",       "NVARCHAR(50) NULL"),
        ("DiscountAmount",  "DECIMAL(10,2) NOT NULL DEFAULT 0"),
    ]:
        db.execute(text(f"""
            IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventRegistrationCart')
            AND NOT EXISTS (SELECT 1 FROM sys.columns
                            WHERE object_id = OBJECT_ID('OFNEventRegistrationCart') AND name = '{col}')
            ALTER TABLE OFNEventRegistrationCart ADD {col} {ddl}
        """))
    db.commit()


with SessionLocal() as _db:
    try:
        ensure_tables(_db)
    except Exception as e:
        print(f"Promo codes setup error: {e}")


# ─── Validation + application logic ────────────────────────────────

def _normalize_code(s: str) -> str:
    return (s or "").strip().upper()


def _validate_promo(db: Session, event_id: int, code: str, subtotal: float,
                    feature_keys: set | None = None):
    """Look up a code and verify it can be applied. Returns the row dict or
    raises HTTPException. Does NOT increment usage."""
    code = _normalize_code(code)
    if not code:
        raise HTTPException(400, "No promo code supplied")
    row = db.execute(text("""
        SELECT * FROM OFNEventPromoCodes
         WHERE EventID = :e AND Code = :c AND IsActive = 1
    """), {"e": event_id, "c": code}).mappings().first()
    if not row:
        raise HTTPException(404, "Promo code not found")
    now = datetime.utcnow()
    if row["ValidFrom"] and now < row["ValidFrom"]:
        raise HTTPException(400, "Promo code not active yet")
    if row["ValidUntil"] and now > row["ValidUntil"]:
        raise HTTPException(400, "Promo code has expired")
    if row["MaxUses"] is not None and (row["UsesSoFar"] or 0) >= row["MaxUses"]:
        raise HTTPException(400, "Promo code is fully redeemed")
    if row["MinCartTotal"] and float(subtotal or 0) < float(row["MinCartTotal"]):
        raise HTTPException(400, f"Cart must be at least ${float(row['MinCartTotal']):.2f}")
    if row["FeatureScope"] and feature_keys is not None and row["FeatureScope"] not in feature_keys:
        raise HTTPException(400, "Promo code does not apply to anything in this cart")
    return dict(row)


def compute_discount(promo: dict, subtotal: float, feature_scoped_total: float | None = None) -> float:
    """Return dollar discount for this promo against a cart.
    feature_scoped_total is the sum of line items matching FeatureScope (if set)."""
    if not promo:
        return 0.0
    base = float(feature_scoped_total if promo.get("FeatureScope") else subtotal)
    if promo["DiscountType"] == "percent":
        return round(base * float(promo["DiscountValue"]) / 100, 2)
    return min(float(promo["DiscountValue"]), base)


# ─── Admin CRUD ─────────────────────────────────────────────────────

@router.get("/api/events/{event_id}/promo-codes")
def list_codes(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT * FROM OFNEventPromoCodes WHERE EventID = :e
         ORDER BY IsActive DESC, CreatedDate DESC
    """), {"e": event_id}).mappings().all()
    return [dict(r) for r in rows]


@router.post("/api/events/{event_id}/promo-codes")
def create_code(event_id: int, data: dict, db: Session = Depends(get_db)):
    code = _normalize_code(data.get("Code"))
    if not code:
        raise HTTPException(400, "Code required")
    if data.get("DiscountType") not in ("percent", "flat"):
        raise HTTPException(400, "DiscountType must be 'percent' or 'flat'")
    try:
        res = db.execute(text("""
            INSERT INTO OFNEventPromoCodes
                (EventID, Code, Description, DiscountType, DiscountValue, FeatureScope,
                 MinCartTotal, MaxUses, ValidFrom, ValidUntil, AutoApply, IsActive)
            OUTPUT INSERTED.CodeID AS id
            VALUES (:e, :c, :d, :t, :v, :fs, :min, :max, :from, :until, :auto, :act)
        """), {
            "e": event_id, "c": code,
            "d": data.get("Description"),
            "t": data["DiscountType"],
            "v": float(data.get("DiscountValue") or 0),
            "fs": data.get("FeatureScope") or None,
            "min": data.get("MinCartTotal") or None,
            "max": data.get("MaxUses") or None,
            "from": data.get("ValidFrom") or None,
            "until": data.get("ValidUntil") or None,
            "auto": 1 if data.get("AutoApply") else 0,
            "act": 1 if data.get("IsActive", True) else 0,
        }).mappings().first()
        db.commit()
        return {"CodeID": int(res["id"])}
    except Exception as e:
        db.rollback()
        raise HTTPException(400, f"Could not create code: {e}")


@router.put("/api/events/promo-codes/{code_id}")
def update_code(code_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventPromoCodes SET
            Description   = :d,
            DiscountType  = :t,
            DiscountValue = :v,
            FeatureScope  = :fs,
            MinCartTotal  = :min,
            MaxUses       = :max,
            ValidFrom     = :from,
            ValidUntil    = :until,
            AutoApply     = :auto,
            IsActive      = :act
         WHERE CodeID = :id
    """), {
        "id": code_id,
        "d": data.get("Description"),
        "t": data.get("DiscountType") or "percent",
        "v": float(data.get("DiscountValue") or 0),
        "fs": data.get("FeatureScope") or None,
        "min": data.get("MinCartTotal") or None,
        "max": data.get("MaxUses") or None,
        "from": data.get("ValidFrom") or None,
        "until": data.get("ValidUntil") or None,
        "auto": 1 if data.get("AutoApply") else 0,
        "act": 1 if data.get("IsActive", True) else 0,
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/promo-codes/{code_id}")
def delete_code(code_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE OFNEventPromoCodes SET IsActive = 0 WHERE CodeID = :id"),
               {"id": code_id})
    db.commit()
    return {"ok": True}


# ─── Auto-apply discovery (wizard calls this at cart init) ──────────

# ─── Marketplace purchase → thank-you code trigger ──────────────────

def _random_code(prefix: str = "THANKS", n: int = 6) -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=n))
    return f"{prefix}-{suffix}"


def issue_marketplace_thank_you_codes(db: Session, order_id: int,
                                      percent_off: float = 10.0,
                                      valid_days: int = 60) -> list[dict]:
    """Called after a marketplace order is placed. For each distinct seller
    business on the order, if that business has any upcoming published event,
    create a single-use percent-off code scoped to the buyer. Returns the list
    of created codes so callers can email them to the buyer.

    Idempotent: won't duplicate if already issued for this OrderID + EventID.
    """
    buyer = db.execute(text("""
        SELECT BuyerEmail, BuyerName, BuyerPeopleID
        FROM MarketplaceOrders WHERE OrderID = :oid
    """), {"oid": order_id}).mappings().first()
    if not buyer:
        return []

    seller_rows = db.execute(text("""
        SELECT DISTINCT SellerBusinessID
        FROM MarketplaceOrderItems
        WHERE OrderID = :oid AND SellerBusinessID IS NOT NULL
    """), {"oid": order_id}).fetchall()
    seller_ids = [r[0] for r in seller_rows]
    if not seller_ids:
        return []

    now = datetime.utcnow()
    valid_until = now + timedelta(days=valid_days)
    created: list[dict] = []

    for bid in seller_ids:
        events = db.execute(text("""
            SELECT TOP 1 EventID, EventName
            FROM OFNEvents
            WHERE BusinessID = :bid
              AND (Deleted IS NULL OR Deleted = 0)
              AND IsPublished = 1
              AND (EventEndDate IS NULL OR EventEndDate >= GETDATE())
            ORDER BY EventStartDate ASC
        """), {"bid": bid}).mappings().all()

        for ev in events:
            marker_desc = f"Thank-you for Marketplace Order #{order_id}"
            exists = db.execute(text("""
                SELECT CodeID FROM OFNEventPromoCodes
                WHERE EventID = :e AND Description = :d
            """), {"e": ev["EventID"], "d": marker_desc}).fetchone()
            if exists:
                continue

            code = _random_code()
            for _ in range(4):
                dup = db.execute(text("""
                    SELECT 1 FROM OFNEventPromoCodes WHERE EventID=:e AND Code=:c
                """), {"e": ev["EventID"], "c": code}).fetchone()
                if not dup:
                    break
                code = _random_code()

            db.execute(text("""
                INSERT INTO OFNEventPromoCodes
                    (EventID, Code, Description, DiscountType, DiscountValue,
                     MaxUses, ValidFrom, ValidUntil, AutoApply, IsActive)
                VALUES (:e, :c, :d, 'percent', :v, 1, :from, :until, 0, 1)
            """), {
                "e": ev["EventID"],
                "c": code,
                "d": marker_desc,
                "v": percent_off,
                "from": now,
                "until": valid_until,
            })
            created.append({
                "EventID":    ev["EventID"],
                "EventName":  ev["EventName"],
                "Code":       code,
                "PercentOff": percent_off,
                "ValidUntil": valid_until.isoformat(),
                "BuyerEmail": buyer["BuyerEmail"],
                "BuyerName":  buyer["BuyerName"],
            })

    if created:
        db.commit()
    return created


@router.get("/api/events/{event_id}/promo-codes/auto-apply")
def auto_apply_candidates(event_id: int, db: Session = Depends(get_db)):
    """Return active, currently-valid, auto-apply codes so the wizard can
    prefill the best early-bird discount without the user typing anything."""
    now = datetime.utcnow()
    rows = db.execute(text("""
        SELECT * FROM OFNEventPromoCodes
         WHERE EventID = :e AND IsActive = 1 AND AutoApply = 1
           AND (ValidFrom  IS NULL OR ValidFrom  <= :n)
           AND (ValidUntil IS NULL OR ValidUntil >= :n)
           AND (MaxUses IS NULL OR UsesSoFar < MaxUses)
         ORDER BY DiscountValue DESC
    """), {"e": event_id, "n": now}).mappings().all()
    return [dict(r) for r in rows]
