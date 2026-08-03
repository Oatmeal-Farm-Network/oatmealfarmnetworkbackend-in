"""
Stripe payment + refund endpoints for the event registration cart.

Credentials are read from OFNPlatformSettings (the DB) at request time — NOT
from env — so admins can rotate keys without a redeploy. If no keys are
configured, endpoints return 503 and the frontend falls back to an
"organizer will contact you" confirmation.

Respects the RefundModel setting:
  - 'immediate_charge' — capture at confirm, refund via /refunds endpoint
  - 'manual_capture'   — authorize at confirm, capture endpoint runs after event
"""
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from routers.platform_settings import get_stripe_config

router = APIRouter()


def _send_cart_receipt(db: Session, cart_id: int):
    """Best-effort receipt email. Swallow exceptions so payment isn't blocked by
    email failures."""
    try:
        from event_emails import send_cart_receipt
    except Exception:
        return
    try:
        cart = db.execute(text("""
            SELECT * FROM OFNEventRegistrationCart WHERE CartID = :id
        """), {"id": cart_id}).mappings().first()
        if not cart or not cart.get("AttendeeEmail"):
            return
        items = db.execute(text("""
            SELECT * FROM OFNEventCartLineItems WHERE CartID = :id ORDER BY LineID
        """), {"id": cart_id}).mappings().all()
        event = db.execute(text("""
            SELECT EventID, EventName, EventStartDate, EventEndDate,
                   EventLocationName, EventLocationStreet, EventLocationCity,
                   EventLocationState, EventLocationZip
              FROM OFNEvents WHERE EventID = :eid
        """), {"eid": cart["EventID"]}).mappings().first()
        attendee = f"{cart.get('AttendeeFirstName') or ''} {cart.get('AttendeeLastName') or ''}".strip()
        send_cart_receipt(
            to_email=cart["AttendeeEmail"],
            attendee_name=attendee,
            event=dict(event) if event else {"EventID": cart["EventID"]},
            cart=dict(cart),
            items=[dict(i) for i in items],
        )
    except Exception as e:
        print(f"[stripe_payments] receipt email failed for cart {cart_id}: {e}")


def _stripe(db: Session):
    cfg = get_stripe_config(db)
    if not cfg.get("StripeSecretKey"):
        raise HTTPException(503, "Stripe is not configured. Ask an admin to add keys in Accounting → Payments.")
    import stripe  # noqa: WPS433 -- lazy to avoid import cost when Stripe unused
    stripe.api_key = cfg["StripeSecretKey"]
    return stripe, cfg


def _post_event_cart_accounting(db: Session, cart_id: int, amount_paid: float):
    """Post an income JE for a paid event cart. Wrapped in try/except so accounting
    failures never block payment confirmation."""
    try:
        from herd_health_accounting import post_income_je
        row = db.execute(text("""
            SELECT e.BusinessID, c.EventID, e.EventName
            FROM OFNEventRegistrationCart c
            JOIN OFNEvents e ON c.EventID = e.EventID
            WHERE c.CartID = :id
        """), {"id": cart_id}).mappings().first()
        if row and row["BusinessID"] and amount_paid > 0:
            event_label = row["EventName"] or f"Event #{row['EventID']}"
            desc = f"Event Registration — {event_label}"
            post_income_je(db, row["BusinessID"], amount_paid,
                           date.today().isoformat(), desc,
                           "event_cart", cart_id, prefer_service=True)
            db.commit()
    except Exception as e:
        print(f"[stripe_payments] accounting post failed for cart {cart_id}: {e}")


def _void_event_cart_accounting(db: Session, cart_id: int):
    try:
        from herd_health_accounting import void_je
        void_je(db, "event_cart", cart_id)
    except Exception as e:
        print(f"[stripe_payments] accounting void failed for cart {cart_id}: {e}")


@router.post("/api/events/cart/{cart_id}/payment-intent")
def create_payment_intent(cart_id: int, db: Session = Depends(get_db)):
    """Create a PaymentIntent for this cart. Returns the client_secret
    for Stripe Elements to complete on the frontend."""
    stripe, cfg = _stripe(db)

    cart = db.execute(text("""
        SELECT CartID, EventID, PeopleID, Total, Status,
               AttendeeEmail, AttendeeFirstName, AttendeeLastName,
               StripePaymentIntentID
        FROM OFNEventRegistrationCart WHERE CartID = :id
    """), {"id": cart_id}).mappings().first()
    if not cart:
        raise HTTPException(404, "Cart not found")
    if cart["Status"] == "paid":
        raise HTTPException(400, "Cart already paid")
    if float(cart["Total"] or 0) <= 0:
        # No charge required — mark paid directly.
        db.execute(text("""
            UPDATE OFNEventRegistrationCart
               SET Status = 'paid', PaidDate = GETDATE(), AmountPaid = 0, UpdatedDate = GETDATE()
             WHERE CartID = :id
        """), {"id": cart_id})
        _mark_entries_paid(db, cart_id)
        db.commit()
        return {"zero": True, "Status": "paid"}

    amount_cents = int(round(float(cart["Total"]) * 100))
    currency = (cfg.get("CurrencyCode") or "USD").lower()
    capture_method = "manual" if cfg.get("RefundModel") == "manual_capture" else "automatic"

    # Reuse existing intent if one was already created (e.g. user refreshed payment page).
    if cart["StripePaymentIntentID"]:
        try:
            intent = stripe.PaymentIntent.retrieve(cart["StripePaymentIntentID"])
            if intent.status in ("requires_payment_method", "requires_confirmation", "requires_action", "processing"):
                return {"clientSecret": intent.client_secret, "paymentIntentId": intent.id}
        except Exception:
            pass  # fall through to create a new intent

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency=currency,
            capture_method=capture_method,
            automatic_payment_methods={"enabled": True},
            description=f"OFN event cart #{cart_id}",
            metadata={
                "cart_id": str(cart_id),
                "event_id": str(cart["EventID"]),
                "people_id": str(cart["PeopleID"] or ""),
            },
            receipt_email=cart["AttendeeEmail"] or None,
        )
    except Exception as e:
        raise HTTPException(502, f"Stripe error: {e}")

    db.execute(text("""
        UPDATE OFNEventRegistrationCart
           SET StripePaymentIntentID = :pi,
               Status = CASE WHEN Status IN ('draft','pending_payment') THEN 'pending_payment' ELSE Status END,
               UpdatedDate = GETDATE()
         WHERE CartID = :id
    """), {"pi": intent.id, "id": cart_id})
    db.commit()

    return {"clientSecret": intent.client_secret, "paymentIntentId": intent.id}


@router.post("/api/events/cart/{cart_id}/confirm")
def confirm_payment(cart_id: int, payload: dict, db: Session = Depends(get_db)):
    """Frontend calls this after stripe.confirmPayment returns success.
    Marks the cart paid (capture_method=automatic) or pending_capture
    (capture_method=manual)."""
    stripe, cfg = _stripe(db)
    cart = db.execute(text("""
        SELECT CartID, StripePaymentIntentID, Total FROM OFNEventRegistrationCart WHERE CartID = :id
    """), {"id": cart_id}).mappings().first()
    if not cart:
        raise HTTPException(404, "Cart not found")

    intent_id = payload.get("paymentIntentId") or cart["StripePaymentIntentID"]
    if not intent_id:
        raise HTTPException(400, "No PaymentIntent ID")

    try:
        intent = stripe.PaymentIntent.retrieve(intent_id)
    except Exception as e:
        raise HTTPException(502, f"Stripe error: {e}")

    status_map = {
        "succeeded": "paid",
        "requires_capture": "pending_capture",
        "processing": "pending_payment",
    }
    cart_status = status_map.get(intent.status, "pending_payment")
    charge_id = (intent.latest_charge if hasattr(intent, "latest_charge") else None) or None
    amount_paid = float(intent.amount_received or 0) / 100

    db.execute(text("""
        UPDATE OFNEventRegistrationCart
           SET Status = :s,
               StripeChargeID = :ch,
               AmountPaid = :amt,
               PaidDate = CASE WHEN :s = 'paid' THEN GETDATE() ELSE PaidDate END,
               UpdatedDate = GETDATE()
         WHERE CartID = :id
    """), {"id": cart_id, "s": cart_status, "ch": charge_id, "amt": amount_paid})

    if cart_status == "paid":
        _mark_entries_paid(db, cart_id)
        try:
            from routers.events import _check_and_record_sold_out
            eid = db.execute(text("SELECT EventID FROM OFNEventRegistrationCart WHERE CartID = :id"),
                             {"id": cart_id}).scalar()
            if eid:
                _check_and_record_sold_out(db, int(eid))
        except Exception as e:
            print(f"[stripe_payments] sold-out check failed: {e}")
    db.commit()
    if cart_status == "paid":
        _post_event_cart_accounting(db, cart_id, amount_paid)
        _send_cart_receipt(db, cart_id)
    return {"Status": cart_status, "AmountPaid": amount_paid}


@router.post("/api/events/cart/{cart_id}/capture")
def capture_payment(cart_id: int, db: Session = Depends(get_db)):
    """Organizer-triggered capture for manual-capture mode. Typically called
    on or just before the event start date."""
    stripe, _ = _stripe(db)
    cart = db.execute(text("""
        SELECT StripePaymentIntentID FROM OFNEventRegistrationCart WHERE CartID = :id
    """), {"id": cart_id}).mappings().first()
    if not cart or not cart["StripePaymentIntentID"]:
        raise HTTPException(404, "No intent for this cart")
    try:
        intent = stripe.PaymentIntent.capture(cart["StripePaymentIntentID"])
    except Exception as e:
        raise HTTPException(502, f"Stripe error: {e}")
    amount_paid = float(intent.amount_received or 0) / 100
    db.execute(text("""
        UPDATE OFNEventRegistrationCart
           SET Status = 'paid', AmountPaid = :amt, PaidDate = GETDATE(), UpdatedDate = GETDATE()
         WHERE CartID = :id
    """), {"id": cart_id, "amt": amount_paid})
    _mark_entries_paid(db, cart_id)
    try:
        from routers.events import _check_and_record_sold_out
        eid = db.execute(text("SELECT EventID FROM OFNEventRegistrationCart WHERE CartID = :id"),
                         {"id": cart_id}).scalar()
        if eid:
            _check_and_record_sold_out(db, int(eid))
    except Exception as e:
        print(f"[stripe_payments] sold-out check failed: {e}")
    db.commit()
    _post_event_cart_accounting(db, cart_id, amount_paid)
    _send_cart_receipt(db, cart_id)
    return {"Status": "paid", "AmountPaid": amount_paid}


@router.post("/api/events/cart/{cart_id}/refund")
def refund_cart(cart_id: int, payload: dict | None = None, db: Session = Depends(get_db)):
    """Issue a full or partial refund. Enforces the refund-deadline setting
    from OFNPlatformSettings (RefundDeadlineDays before event start)."""
    payload = payload or {}
    stripe, cfg = _stripe(db)

    cart = db.execute(text("""
        SELECT c.CartID, c.EventID, c.StripePaymentIntentID, c.StripeChargeID,
               c.AmountPaid, c.AmountRefunded, c.Status,
               e.EventStartDate
          FROM OFNEventRegistrationCart c
          LEFT JOIN OFNEvents e ON c.EventID = e.EventID
         WHERE c.CartID = :id
    """), {"id": cart_id}).mappings().first()
    if not cart:
        raise HTTPException(404, "Cart not found")
    if cart["Status"] not in ("paid", "pending_capture", "partially_refunded"):
        raise HTTPException(400, f"Cannot refund cart in status {cart['Status']}")

    # Enforce refund deadline unless caller explicitly overrides.
    if not payload.get("overrideDeadline"):
        deadline_days = int(cfg.get("RefundDeadlineDays") or 0)
        if cart["EventStartDate"]:
            start = cart["EventStartDate"] if isinstance(cart["EventStartDate"], date) \
                else datetime.fromisoformat(str(cart["EventStartDate"])[:10]).date()
            cutoff = start - timedelta(days=deadline_days)
            if date.today() > cutoff:
                raise HTTPException(400, f"Refund deadline passed (must request by {cutoff.isoformat()})")

    # manual_capture + not yet captured → cancel the intent instead of refunding.
    if cart["Status"] == "pending_capture":
        try:
            stripe.PaymentIntent.cancel(cart["StripePaymentIntentID"])
        except Exception as e:
            raise HTTPException(502, f"Stripe error: {e}")
        db.execute(text("""
            UPDATE OFNEventRegistrationCart
               SET Status = 'cancelled', UpdatedDate = GETDATE()
             WHERE CartID = :id
        """), {"id": cart_id})
        db.commit()
        return {"Status": "cancelled", "AmountRefunded": 0}

    requested = payload.get("amount")
    already_refunded = float(cart["AmountRefunded"] or 0)
    paid = float(cart["AmountPaid"] or 0)
    max_refund = paid - already_refunded
    amount = float(requested) if requested is not None else max_refund
    if amount <= 0 or amount > max_refund + 0.001:
        raise HTTPException(400, f"Invalid refund amount (max ${max_refund:.2f})")

    try:
        refund = stripe.Refund.create(
            payment_intent=cart["StripePaymentIntentID"],
            amount=int(round(amount * 100)),
            reason=payload.get("reason") or "requested_by_customer",
        )
    except Exception as e:
        raise HTTPException(502, f"Stripe error: {e}")

    new_refunded = round(already_refunded + amount, 2)
    new_status = "refunded" if abs(new_refunded - paid) < 0.01 else "partially_refunded"
    db.execute(text("""
        UPDATE OFNEventRegistrationCart
           SET AmountRefunded = :ar,
               Status = :s,
               RefundedDate = CASE WHEN :s = 'refunded' THEN GETDATE() ELSE RefundedDate END,
               UpdatedDate = GETDATE()
         WHERE CartID = :id
    """), {"id": cart_id, "ar": new_refunded, "s": new_status})
    if new_status == "refunded":
        _mark_entries_refunded(db, cart_id)
        _void_event_cart_accounting(db, cart_id)
    db.commit()
    return {"Status": new_status, "AmountRefunded": new_refunded, "RefundID": refund.id}


@router.post("/api/events/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    cfg = get_stripe_config(db)
    if not cfg.get("StripeWebhookSecret"):
        # No webhook secret configured — accept but don't trust. Return 200 so
        # Stripe doesn't retry forever.
        return {"ok": True, "skipped": "no webhook secret"}
    import stripe
    stripe.api_key = cfg["StripeSecretKey"]
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, cfg["StripeWebhookSecret"])
    except Exception as e:
        raise HTTPException(400, f"Invalid webhook: {e}")

    typ = event.get("type")
    obj = event.get("data", {}).get("object", {})
    intent_id = obj.get("payment_intent") or obj.get("id")

    if not intent_id:
        return {"ok": True}

    if typ == "payment_intent.succeeded":
        charge_id = obj.get("latest_charge")
        amount_paid = float(obj.get("amount_received") or 0) / 100
        result = db.execute(text("""
            UPDATE OFNEventRegistrationCart
               SET Status = 'paid', StripeChargeID = :ch, AmountPaid = :amt,
                   PaidDate = GETDATE(), UpdatedDate = GETDATE()
             WHERE StripePaymentIntentID = :pi AND Status <> 'paid'
        """), {"pi": intent_id, "ch": charge_id, "amt": amount_paid})
        transitioned = (result.rowcount or 0) > 0
        cart_row = db.execute(text("SELECT CartID FROM OFNEventRegistrationCart WHERE StripePaymentIntentID = :pi"),
                              {"pi": intent_id}).mappings().first()
        if cart_row and transitioned:
            _mark_entries_paid(db, cart_row["CartID"])
        db.commit()
        if cart_row and transitioned:
            _post_event_cart_accounting(db, cart_row["CartID"], amount_paid)
            _send_cart_receipt(db, cart_row["CartID"])
    elif typ == "charge.refunded":
        amt_refunded = float(obj.get("amount_refunded") or 0) / 100
        amt = float(obj.get("amount") or 0) / 100
        new_status = "refunded" if abs(amt_refunded - amt) < 0.01 else "partially_refunded"
        db.execute(text("""
            UPDATE OFNEventRegistrationCart
               SET AmountRefunded = :ar, Status = :s, UpdatedDate = GETDATE()
             WHERE StripeChargeID = :ch
        """), {"ch": obj.get("id"), "ar": amt_refunded, "s": new_status})
        db.commit()

    return {"ok": True}


# ─── helpers ─────────────────────────────────────────────────────

def _mark_entries_paid(db: Session, cart_id: int):
    for tbl in ("OFNEventHalterEntries", "OFNEventFleeceEntries", "OFNEventSpinOffEntries",
                "OFNEventFiberArtsEntries", "OFNEventVendorFairBooths", "OFNEventMealTickets"):
        try:
            db.execute(text(f"""
                IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = '{tbl}')
                UPDATE {tbl} SET PaidStatus = 'paid' WHERE CartID = :cid
            """), {"cid": cart_id})
        except Exception:
            pass
    # Increment promo code usage on first transition to paid
    try:
        db.execute(text("""
            IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventPromoCodes')
            UPDATE p SET UsesSoFar = ISNULL(UsesSoFar, 0) + 1
              FROM OFNEventPromoCodes p
              JOIN OFNEventRegistrationCart c ON c.PromoCodeID = p.CodeID
             WHERE c.CartID = :cid
        """), {"cid": cart_id})
    except Exception:
        pass


def _mark_entries_refunded(db: Session, cart_id: int):
    for tbl in ("OFNEventHalterEntries", "OFNEventFleeceEntries", "OFNEventSpinOffEntries",
                "OFNEventFiberArtsEntries", "OFNEventVendorFairBooths", "OFNEventMealTickets"):
        try:
            db.execute(text(f"""
                IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = '{tbl}')
                UPDATE {tbl} SET PaidStatus = 'refunded' WHERE CartID = :cid
            """), {"cid": cart_id})
        except Exception:
            pass
