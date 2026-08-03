"""
Unified event-registration cart. One cart per attendee per event collects line
items from every feature they signed up for (halter classes, fleece entries,
spin-off entries, fiber-arts entries, vendor stall, meal tickets, general
registration options) so admin and customer can see a single total + payment.

Feature-specific entry tables carry a nullable CartID FK added by
ensure_cart_columns() at import time.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal

router = APIRouter()

CART_LINKED_TABLES = [
    "OFNEventHalterEntries",
    "OFNEventFleeceEntries",
    "OFNEventSpinOffEntries",
    "OFNEventFiberArtsEntries",
    "OFNEventVendorFairBooths",
    "OFNEventMealTickets",
    "OFNEventRegistrations",
]


def ensure_attendee_table(db: Session):
    """Group registration: a single cart may represent multiple people
    (e.g. a parent paying for two kids, or a farm registering several exhibitors).
    Line items optionally reference an AttendeeID so the admin can see who each
    registration/class entry is for."""
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventCartAttendees')
        CREATE TABLE OFNEventCartAttendees (
            AttendeeID    INT IDENTITY(1,1) PRIMARY KEY,
            CartID        INT NOT NULL,
            PeopleID      INT,
            FirstName     NVARCHAR(100),
            LastName      NVARCHAR(100),
            Email         NVARCHAR(200),
            Phone         NVARCHAR(50),
            Role          NVARCHAR(50),   -- payer | exhibitor | guest | child | youth | other
            DateOfBirth   DATE,
            NameTagTitle  NVARCHAR(200),
            Notes         NVARCHAR(500),
            CreatedDate   DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventCartLineItems')
        AND NOT EXISTS (SELECT 1 FROM sys.columns
                        WHERE object_id = OBJECT_ID('OFNEventCartLineItems') AND name = 'AttendeeID')
        ALTER TABLE OFNEventCartLineItems ADD AttendeeID INT NULL
    """))
    # Last-reminder timestamp for abandoned-cart nudges
    db.execute(text("""
        IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventRegistrationCart')
        AND NOT EXISTS (SELECT 1 FROM sys.columns
                        WHERE object_id = OBJECT_ID('OFNEventRegistrationCart') AND name = 'LastReminderSent')
        ALTER TABLE OFNEventRegistrationCart ADD LastReminderSent DATETIME NULL
    """))
    db.commit()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventRegistrationCart')
        CREATE TABLE OFNEventRegistrationCart (
            CartID               INT IDENTITY(1,1) PRIMARY KEY,
            EventID              INT NOT NULL,
            PeopleID             INT,
            BusinessID           INT,
            AttendeeFirstName    NVARCHAR(100),
            AttendeeLastName     NVARCHAR(100),
            AttendeeEmail        NVARCHAR(200),
            AttendeePhone        NVARCHAR(50),
            Subtotal             DECIMAL(10,2) DEFAULT 0,
            Total                DECIMAL(10,2) DEFAULT 0,
            PlatformFeeAmount    DECIMAL(10,2) DEFAULT 0,
            Status               NVARCHAR(50) DEFAULT 'draft',
            -- draft | pending_payment | paid | refunded | partially_refunded | cancelled
            StripePaymentIntentID NVARCHAR(100),
            StripeChargeID       NVARCHAR(100),
            AmountPaid           DECIMAL(10,2) DEFAULT 0,
            AmountRefunded       DECIMAL(10,2) DEFAULT 0,
            PaidDate             DATETIME,
            RefundedDate         DATETIME,
            Notes                NVARCHAR(MAX),
            CreatedDate          DATETIME DEFAULT GETDATE(),
            UpdatedDate          DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventCartLineItems')
        CREATE TABLE OFNEventCartLineItems (
            LineID       INT IDENTITY(1,1) PRIMARY KEY,
            CartID       INT NOT NULL,
            FeatureKey   NVARCHAR(50) NOT NULL,
            -- halter | fleece | spinoff | fiber-arts | vendor | meal | option | other
            SourceTable  NVARCHAR(100),
            SourceID     INT,
            Label        NVARCHAR(300),
            Quantity     INT DEFAULT 1,
            UnitAmount   DECIMAL(10,2) DEFAULT 0,
            LineAmount   DECIMAL(10,2) DEFAULT 0,
            CreatedDate  DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


def ensure_cart_columns(db: Session):
    for tbl in CART_LINKED_TABLES:
        try:
            db.execute(text(f"""
                IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = '{tbl}')
                AND NOT EXISTS (SELECT 1 FROM sys.columns
                                WHERE object_id = OBJECT_ID('{tbl}') AND name = 'CartID')
                ALTER TABLE {tbl} ADD CartID INT NULL
            """))
        except Exception as e:
            print(f"CartID add for {tbl} failed: {e}")
    db.commit()


with SessionLocal() as _db:
    try:
        ensure_tables(_db)
        ensure_cart_columns(_db)
        ensure_attendee_table(_db)
    except Exception as e:
        print(f"Registration cart setup error: {e}")


@router.post("/api/events/{event_id}/cart")
def create_cart(event_id: int, payload: dict, db: Session = Depends(get_db)):
    """Create a new draft cart for an attendee. Called at wizard start."""
    res = db.execute(text("""
        INSERT INTO OFNEventRegistrationCart
            (EventID, PeopleID, BusinessID,
             AttendeeFirstName, AttendeeLastName, AttendeeEmail, AttendeePhone,
             Status)
        OUTPUT INSERTED.CartID AS id
        VALUES (:eid, :pid, :bid, :fn, :ln, :em, :ph, 'draft')
    """), {
        "eid": event_id,
        "pid": payload.get("PeopleID"),
        "bid": payload.get("BusinessID"),
        "fn":  payload.get("AttendeeFirstName"),
        "ln":  payload.get("AttendeeLastName"),
        "em":  payload.get("AttendeeEmail"),
        "ph":  payload.get("AttendeePhone"),
    }).mappings().first()
    db.commit()
    return {"CartID": int(res["id"])}


@router.get("/api/events/cart/{cart_id}")
def get_cart(cart_id: int, db: Session = Depends(get_db)):
    cart = db.execute(text("""
        SELECT * FROM OFNEventRegistrationCart WHERE CartID = :id
    """), {"id": cart_id}).mappings().first()
    if not cart:
        raise HTTPException(404, "Cart not found")
    items = db.execute(text("""
        SELECT * FROM OFNEventCartLineItems WHERE CartID = :id ORDER BY LineID
    """), {"id": cart_id}).mappings().all()
    return {**dict(cart), "items": [dict(x) for x in items]}


def _recalc_totals(db: Session, cart_id: int):
    """Recompute subtotal / discount / fee / total from line items + promo.
    Writes back to OFNEventRegistrationCart and returns the values."""
    sums = db.execute(text("""
        SELECT ISNULL(SUM(LineAmount), 0) AS sub
          FROM OFNEventCartLineItems WHERE CartID = :c
    """), {"c": cart_id}).mappings().first()
    subtotal = float(sums["sub"] or 0)

    cart = db.execute(text("""
        SELECT EventID, PromoCodeID FROM OFNEventRegistrationCart WHERE CartID = :c
    """), {"c": cart_id}).mappings().first()

    discount = 0.0
    promo_code_str = None
    if cart and cart.get("PromoCodeID"):
        try:
            from routers.event_promo_codes import compute_discount
            promo = db.execute(text("""
                SELECT * FROM OFNEventPromoCodes WHERE CodeID = :id
            """), {"id": cart["PromoCodeID"]}).mappings().first()
            if promo and promo["IsActive"]:
                scoped_total = subtotal
                if promo["FeatureScope"]:
                    fs_row = db.execute(text("""
                        SELECT ISNULL(SUM(LineAmount), 0) AS t
                          FROM OFNEventCartLineItems
                         WHERE CartID = :c AND FeatureKey = :fk
                    """), {"c": cart_id, "fk": promo["FeatureScope"]}).mappings().first()
                    scoped_total = float(fs_row["t"] or 0)
                discount = compute_discount(dict(promo), subtotal, scoped_total)
                promo_code_str = promo["Code"]
        except Exception:
            discount = 0.0

    discount = min(discount, subtotal)
    after_discount = max(0.0, subtotal - discount)

    fee_pct = db.execute(text("""
        SELECT TOP 1 PlatformFeePercent FROM OFNPlatformSettings ORDER BY SettingID
    """)).mappings().first()
    pct = float(fee_pct["PlatformFeePercent"]) if fee_pct and fee_pct["PlatformFeePercent"] is not None else 0.0
    fee_amt = round(after_discount * pct / 100, 2)
    total = round(after_discount + fee_amt, 2)

    db.execute(text("""
        UPDATE OFNEventRegistrationCart
           SET Subtotal = :s,
               DiscountAmount = :d,
               PromoCode = :pc,
               PlatformFeeAmount = :f,
               Total = :t,
               UpdatedDate = GETDATE()
         WHERE CartID = :id
    """), {"id": cart_id, "s": subtotal, "d": discount,
           "pc": promo_code_str, "f": fee_amt, "t": total})

    return {"Subtotal": subtotal, "DiscountAmount": discount,
            "PlatformFeeAmount": fee_amt, "Total": total, "PromoCode": promo_code_str}


@router.post("/api/events/cart/{cart_id}/items")
def add_items(cart_id: int, payload: dict, db: Session = Depends(get_db)):
    """Replace line items for a cart (simpler than diff-patch).
    payload = { items: [ { FeatureKey, SourceTable, SourceID, Label, Quantity, UnitAmount } ] }
    Recalculates totals (including any active promo code on the cart).
    """
    items = payload.get("items") or []
    db.execute(text("DELETE FROM OFNEventCartLineItems WHERE CartID = :id"), {"id": cart_id})
    for it in items:
        qty = int(it.get("Quantity") or 1)
        unit = float(it.get("UnitAmount") or 0)
        line = qty * unit
        db.execute(text("""
            INSERT INTO OFNEventCartLineItems
                (CartID, FeatureKey, SourceTable, SourceID, Label, Quantity, UnitAmount, LineAmount)
            VALUES (:cid, :fk, :st, :sid, :lbl, :q, :u, :ln)
        """), {
            "cid": cart_id,
            "fk":  it.get("FeatureKey") or "other",
            "st":  it.get("SourceTable"),
            "sid": it.get("SourceID"),
            "lbl": it.get("Label"),
            "q":   qty, "u": unit, "ln": line,
        })
    result = _recalc_totals(db, cart_id)
    db.commit()
    return result


@router.post("/api/events/cart/{cart_id}/promo-code")
def apply_promo(cart_id: int, payload: dict, db: Session = Depends(get_db)):
    """Apply a promo code to an existing cart. Validates + recalculates totals."""
    from routers.event_promo_codes import _validate_promo, _normalize_code
    cart = db.execute(text("""
        SELECT EventID, Subtotal FROM OFNEventRegistrationCart WHERE CartID = :c
    """), {"c": cart_id}).mappings().first()
    if not cart:
        raise HTTPException(404, "Cart not found")
    code = _normalize_code(payload.get("Code"))
    feature_keys = {
        r["FeatureKey"] for r in db.execute(text("""
            SELECT DISTINCT FeatureKey FROM OFNEventCartLineItems WHERE CartID = :c
        """), {"c": cart_id}).mappings().all()
    }
    promo = _validate_promo(db, int(cart["EventID"]), code,
                            float(cart["Subtotal"] or 0), feature_keys)
    db.execute(text("""
        UPDATE OFNEventRegistrationCart
           SET PromoCodeID = :pid, PromoCode = :pc
         WHERE CartID = :id
    """), {"id": cart_id, "pid": promo["CodeID"], "pc": promo["Code"]})
    result = _recalc_totals(db, cart_id)
    db.commit()
    return result


@router.delete("/api/events/cart/{cart_id}/promo-code")
def remove_promo(cart_id: int, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventRegistrationCart SET PromoCodeID = NULL, PromoCode = NULL
         WHERE CartID = :id
    """), {"id": cart_id})
    result = _recalc_totals(db, cart_id)
    db.commit()
    return result


@router.put("/api/events/cart/{cart_id}/link")
def link_entry(cart_id: int, payload: dict, db: Session = Depends(get_db)):
    """Link a feature-entry row (already inserted by that feature's POST) to
    this cart by writing CartID into the source table. Validates that the
    source table is whitelisted."""
    table = payload.get("SourceTable")
    source_id = payload.get("SourceID")
    id_col = payload.get("IDColumn") or "EntryID"
    if table not in CART_LINKED_TABLES:
        raise HTTPException(400, "Unsupported source table")
    if source_id is None:
        raise HTTPException(400, "SourceID required")
    db.execute(text(f"""
        UPDATE {table} SET CartID = :cid WHERE {id_col} = :sid
    """), {"cid": cart_id, "sid": int(source_id)})
    db.commit()
    return {"ok": True}


@router.get("/api/events/{event_id}/carts")
def list_carts(event_id: int, db: Session = Depends(get_db)):
    """Admin: list all carts for an event with totals and line-item counts."""
    rows = db.execute(text("""
        SELECT c.*,
               (SELECT COUNT(*) FROM OFNEventCartLineItems li WHERE li.CartID = c.CartID) AS ItemCount
        FROM OFNEventRegistrationCart c
        WHERE c.EventID = :eid
        ORDER BY c.CreatedDate DESC
    """), {"eid": event_id}).mappings().all()
    return [dict(r) for r in rows]


@router.get("/api/events/{event_id}/carts/paid-with-attendees")
def paid_carts_with_attendees(event_id: int, db: Session = Depends(get_db)):
    """Admin: paid carts + their additional attendees, for printing nametags."""
    ensure_attendee_table(db)
    carts = db.execute(text("""
        SELECT c.CartID, c.AttendeeFirstName, c.AttendeeLastName, c.AttendeeEmail,
               c.BusinessID, b.BusinessName AS AttendeeBusinessName
        FROM OFNEventRegistrationCart c
        LEFT JOIN Business b ON b.BusinessID = c.BusinessID
        WHERE c.EventID = :eid AND c.Status = 'paid'
        ORDER BY c.CartID
    """), {"eid": event_id}).mappings().all()
    carts = [dict(r) for r in carts]
    if carts:
        ids = [c["CartID"] for c in carts]
        ph = ",".join(f":id{i}" for i, _ in enumerate(ids))
        params = {f"id{i}": v for i, v in enumerate(ids)}
        att = db.execute(text(f"""
            SELECT CartID, FirstName, LastName, Email, Role, NameTagTitle
            FROM OFNEventCartAttendees
            WHERE CartID IN ({ph})
            ORDER BY AttendeeID
        """), params).mappings().all()
        by_cart = {}
        for a in att:
            by_cart.setdefault(a["CartID"], []).append(dict(a))
        for c in carts:
            c["Attendees"] = by_cart.get(c["CartID"], [])
    return carts


@router.get("/api/events/{event_id}/my-carts")
def my_carts(event_id: int, people_id: int | None = None, db: Session = Depends(get_db)):
    if not people_id:
        return []
    rows = db.execute(text("""
        SELECT * FROM OFNEventRegistrationCart
         WHERE EventID = :eid AND PeopleID = :pid
         ORDER BY CreatedDate DESC
    """), {"eid": event_id, "pid": people_id}).mappings().all()
    return [dict(r) for r in rows]


@router.get("/api/people/{people_id}/event-carts")
def people_carts(people_id: int, db: Session = Depends(get_db)):
    """All carts across all events for one attendee. Used by MyRegistrations."""
    rows = db.execute(text("""
        SELECT c.*,
               e.EventName, e.EventStartDate, e.EventType,
               (SELECT COUNT(*) FROM OFNEventCartLineItems li WHERE li.CartID = c.CartID) AS ItemCount
        FROM OFNEventRegistrationCart c
        LEFT JOIN OFNEvents e ON e.EventID = c.EventID
        WHERE c.PeopleID = :pid
        ORDER BY c.CreatedDate DESC
    """), {"pid": people_id}).mappings().all()
    return [dict(r) for r in rows]


@router.delete("/api/events/cart/{cart_id}")
def delete_cart(cart_id: int, db: Session = Depends(get_db)):
    """Abandon a draft cart (only allowed while in draft status)."""
    cart = db.execute(text("SELECT Status FROM OFNEventRegistrationCart WHERE CartID = :id"),
                      {"id": cart_id}).mappings().first()
    if not cart:
        raise HTTPException(404, "Cart not found")
    if cart["Status"] not in ("draft", "pending_payment"):
        raise HTTPException(400, f"Cannot delete cart in status {cart['Status']}")
    db.execute(text("DELETE FROM OFNEventCartLineItems WHERE CartID = :id"), {"id": cart_id})
    db.execute(text("DELETE FROM OFNEventCartAttendees WHERE CartID = :id"), {"id": cart_id})
    db.execute(text("DELETE FROM OFNEventRegistrationCart WHERE CartID = :id"), {"id": cart_id})
    db.commit()
    return {"ok": True}


# ─── Cart attendees (group registration) ────────────────────────────

@router.get("/api/events/cart/{cart_id}/attendees")
def list_cart_attendees(cart_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT * FROM OFNEventCartAttendees WHERE CartID = :c
         ORDER BY AttendeeID
    """), {"c": cart_id}).mappings().all()
    return [dict(r) for r in rows]


@router.post("/api/events/cart/{cart_id}/attendees")
def add_cart_attendee(cart_id: int, data: dict, db: Session = Depends(get_db)):
    res = db.execute(text("""
        INSERT INTO OFNEventCartAttendees
            (CartID, PeopleID, FirstName, LastName, Email, Phone, Role, DateOfBirth,
             NameTagTitle, Notes)
        OUTPUT INSERTED.AttendeeID AS id
        VALUES (:c, :p, :f, :l, :em, :ph, :r, :dob, :nt, :nts)
    """), {
        "c": cart_id,
        "p": data.get("PeopleID"),
        "f": data.get("FirstName"), "l": data.get("LastName"),
        "em": data.get("Email"), "ph": data.get("Phone"),
        "r": data.get("Role") or "guest",
        "dob": data.get("DateOfBirth") or None,
        "nt": data.get("NameTagTitle"),
        "nts": data.get("Notes"),
    }).mappings().first()
    db.commit()
    return {"AttendeeID": int(res["id"])}


@router.put("/api/events/cart/attendees/{attendee_id}")
def update_cart_attendee(attendee_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE OFNEventCartAttendees SET
          FirstName = :f, LastName = :l, Email = :em, Phone = :ph,
          Role = :r, DateOfBirth = :dob, NameTagTitle = :nt, Notes = :nts
         WHERE AttendeeID = :id
    """), {
        "id": attendee_id,
        "f": data.get("FirstName"), "l": data.get("LastName"),
        "em": data.get("Email"), "ph": data.get("Phone"),
        "r": data.get("Role") or "guest",
        "dob": data.get("DateOfBirth") or None,
        "nt": data.get("NameTagTitle"),
        "nts": data.get("Notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/cart/attendees/{attendee_id}")
def delete_cart_attendee(attendee_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE OFNEventCartLineItems SET AttendeeID = NULL WHERE AttendeeID = :id"),
               {"id": attendee_id})
    db.execute(text("DELETE FROM OFNEventCartAttendees WHERE AttendeeID = :id"),
               {"id": attendee_id})
    db.commit()
    return {"ok": True}


# ─── Abandoned cart recovery ────────────────────────────────────────

@router.get("/api/events/{event_id}/carts/abandoned")
def list_abandoned(event_id: int, hours: int = 24, db: Session = Depends(get_db)):
    """Draft carts older than N hours with a usable email + at least one line item."""
    rows = db.execute(text("""
        SELECT c.CartID, c.AttendeeFirstName, c.AttendeeLastName, c.AttendeeEmail,
               c.Subtotal, c.Total, c.CreatedDate, c.LastReminderSent,
               (SELECT COUNT(*) FROM OFNEventCartLineItems l WHERE l.CartID = c.CartID) AS LineCount
          FROM OFNEventRegistrationCart c
         WHERE c.EventID = :e
           AND c.Status IN ('draft', 'pending_payment')
           AND c.AttendeeEmail IS NOT NULL AND c.AttendeeEmail <> ''
           AND DATEDIFF(hour, c.CreatedDate, GETDATE()) >= :h
         ORDER BY c.CreatedDate
    """), {"e": event_id, "h": int(hours)}).mappings().all()
    return [dict(r) for r in rows if r["LineCount"] > 0]


@router.post("/api/events/cart/{cart_id}/send-reminder")
def send_reminder(cart_id: int, db: Session = Depends(get_db)):
    """Send (or re-send) an abandoned-cart reminder email. Updates LastReminderSent."""
    import os, logging
    log = logging.getLogger(__name__)
    cart = db.execute(text("""
        SELECT c.*, e.EventName
          FROM OFNEventRegistrationCart c
          LEFT JOIN OFNEvents e ON e.EventID = c.EventID
         WHERE c.CartID = :id
    """), {"id": cart_id}).mappings().first()
    if not cart:
        raise HTTPException(404, "Cart not found")
    if not cart["AttendeeEmail"]:
        raise HTTPException(400, "No email on file for this cart")
    if cart["Status"] not in ("draft", "pending_payment"):
        raise HTTPException(400, f"Cart already {cart['Status']}")
    items = db.execute(text("""
        SELECT Label, Quantity, LineAmount FROM OFNEventCartLineItems
         WHERE CartID = :id ORDER BY LineID
    """), {"id": cart_id}).mappings().all()
    base = os.getenv("OFN_BASE_URL", "https://www.oatmealfarmnetwork.com")
    resume_url = f"{base}/events/{cart['EventID']}/register/wizard?cart={cart_id}"

    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail
        api = os.getenv("SENDGRID_API_KEY", "")
        from_email = os.getenv("FROM_EMAIL", "john@oatmeal-ai.com")
        if not api:
            raise RuntimeError("SendGrid not configured")
        items_html = "".join(
            f"<tr><td style='padding:4px 8px'>{i['Label'] or ''}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{i['Quantity']}</td>"
            f"<td style='padding:4px 8px;text-align:right'>${float(i['LineAmount'] or 0):.2f}</td></tr>"
            for i in items
        )
        total = float(cart['Total'] or cart['Subtotal'] or 0)
        html = f"""
          <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto">
            <h2 style="color:#3D6B34">You left something in your cart</h2>
            <p>Hi {cart.get('AttendeeFirstName') or ''},</p>
            <p>Your registration for <strong>{cart['EventName']}</strong> is saved but not
               yet confirmed. Finish checkout to secure your spot.</p>
            <table style="border-collapse:collapse;width:100%;margin:12px 0">
              <tr style="background:#f6f6f6;font-size:12px;text-transform:uppercase">
                <th style="text-align:left;padding:4px 8px">Item</th>
                <th style="text-align:right;padding:4px 8px">Qty</th>
                <th style="text-align:right;padding:4px 8px">Amount</th>
              </tr>
              {items_html}
              <tr style="border-top:1px solid #ccc;font-weight:bold">
                <td style="padding:8px">Total</td><td></td>
                <td style="padding:8px;text-align:right">${total:.2f}</td>
              </tr>
            </table>
            <p>
              <a href="{resume_url}" style="background:#3D6B34;color:#fff;padding:10px 18px;
                    border-radius:6px;text-decoration:none">Finish registration</a>
            </p>
            <p style="color:#888;font-size:12px">If capacity is limited, your spot is
               <em>not</em> reserved until you pay.</p>
          </div>
        """
        sg = sendgrid.SendGridAPIClient(api_key=api)
        sg.send(Mail(
            from_email=from_email,
            to_emails=cart["AttendeeEmail"],
            subject=f"Don't lose your spot at {cart['EventName']}",
            html_content=html,
        ))
    except Exception as e:
        log.error("Abandoned cart email failed: %s", e)
        raise HTTPException(500, f"Email failed: {e}")

    db.execute(text("""
        UPDATE OFNEventRegistrationCart SET LastReminderSent = GETDATE()
         WHERE CartID = :id
    """), {"id": cart_id})
    db.commit()
    return {"ok": True, "sent_to": cart["AttendeeEmail"]}


@router.post("/api/events/{event_id}/carts/send-all-reminders")
def send_all_reminders(event_id: int, hours: int = 24, min_gap_hours: int = 48,
                       db: Session = Depends(get_db)):
    """Send reminder to every abandoned cart older than `hours` that hasn't been
    nudged within the last `min_gap_hours`. Returns counts."""
    rows = db.execute(text("""
        SELECT c.CartID FROM OFNEventRegistrationCart c
         WHERE c.EventID = :e
           AND c.Status IN ('draft', 'pending_payment')
           AND c.AttendeeEmail IS NOT NULL AND c.AttendeeEmail <> ''
           AND DATEDIFF(hour, c.CreatedDate, GETDATE()) >= :h
           AND (c.LastReminderSent IS NULL
                OR DATEDIFF(hour, c.LastReminderSent, GETDATE()) >= :gap)
           AND EXISTS (SELECT 1 FROM OFNEventCartLineItems l WHERE l.CartID = c.CartID)
    """), {"e": event_id, "h": int(hours), "gap": int(min_gap_hours)}).mappings().all()
    sent, failed = 0, 0
    for r in rows:
        try:
            send_reminder(int(r["CartID"]), db)
            sent += 1
        except Exception:
            failed += 1
    return {"sent": sent, "failed": failed, "candidates": len(rows)}
