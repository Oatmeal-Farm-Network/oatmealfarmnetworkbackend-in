# marketplace_stripe.py
# Stripe Connect payment processing for the Farm2Restaurant Marketplace
# Mount: app.include_router(stripe_router, prefix="/api/marketplace/payments")
#
# Credentials + platform fee % are read from OFNPlatformSettings (DB) at
# request time — NOT from env — so admins can toggle test/live mode, rotate
# keys, and change the platform fee without a redeploy. See routers.platform_settings
# and the Accounting → Payments tab in the admin UI.

import os
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from jwt_auth import get_current_user
from routers.platform_settings import get_stripe_config


stripe_router = APIRouter()

OFN_BASE_URL = os.getenv("OFN_BASE_URL", "https://oatmealfarmnetwork.com")


def _load_stripe_config():
    """Load Stripe config from OFNPlatformSettings and return (stripe_module, cfg).
    Raises 503 if keys are not configured yet."""
    with SessionLocal() as db:
        cfg = get_stripe_config(db)
    if not cfg.get("StripeSecretKey"):
        raise HTTPException(
            503,
            "Stripe is not configured. Ask an admin to add keys in Accounting → Payments.",
        )
    import stripe  # lazy import keeps cold-start cheap when Stripe unused
    stripe.api_key = cfg["StripeSecretKey"]
    return stripe, cfg


def _require_business_access(db: Session, people_id: str, business_id: int):
    """403 unless the authenticated user has an active BusinessAccess row."""
    try:
        pid = int(people_id)
    except (TypeError, ValueError):
        raise HTTPException(401, "Invalid token")
    row = db.execute(
        text("SELECT 1 FROM BusinessAccess WHERE BusinessID = :b AND PeopleID = :p AND Active = 1"),
        {"b": business_id, "p": pid},
    ).fetchone()
    if not row:
        raise HTTPException(403, "You do not have access to this business.")


# ============================================================
# 1. CREATE PAYMENT INTENT (after sellers confirm)
# ============================================================

@stripe_router.post("/create-intent/{order_id}")
async def create_payment_intent(order_id: int, db: Session = Depends(get_db)):
    """
    Creates a Stripe PaymentIntent for confirmed order items.
    Uses Stripe Connect with transfer_group for multi-seller split.
    Only charges for confirmed items (rejected items excluded).
    """
    stripe, cfg = _load_stripe_config()
    platform_fee_percent = float(cfg.get("PlatformFeePercent") or 0)
    currency = (cfg.get("CurrencyCode") or "USD").lower()

    order = db.execute(
        text("SELECT * FROM MarketplaceOrders WHERE OrderID = :oid"),
        {"oid": order_id},
    ).mappings().fetchone()
    if not order:
        raise HTTPException(404, "Order not found")
    if order["PaymentStatus"] == "paid":
        raise HTTPException(400, "Order already paid")

    confirmed_items = db.execute(
        text("""
            SELECT oi.OrderItemID, oi.SellerBusinessID, oi.LineTotal, oi.SellerPayout,
                   sa.StripeConnectAccountID
            FROM MarketplaceOrderItems oi
            LEFT JOIN StripeAccounts sa ON oi.SellerBusinessID = sa.BusinessID
            WHERE oi.OrderID = :oid AND oi.SellerStatus = 'confirmed'
        """),
        {"oid": order_id},
    ).mappings().all()
    if not confirmed_items:
        raise HTTPException(400, "No confirmed items to charge")

    subtotal = sum(float(i["LineTotal"]) for i in confirmed_items)
    platform_fee = round(subtotal * platform_fee_percent / 100, 2)
    total_cents = int(round((subtotal + platform_fee) * 100))
    transfer_group = f"order_{order_id}"

    transfers_pending = sum(1 for i in confirmed_items if i.get("StripeConnectAccountID"))

    try:
        intent = stripe.PaymentIntent.create(
            amount=total_cents,
            currency=currency,
            transfer_group=transfer_group,
            metadata={
                "order_id": str(order_id),
                "order_number": order["OrderNumber"],
                "buyer_people_id": str(order["BuyerPeopleID"]),
            },
            description=f"Order {order['OrderNumber']} - Oatmeal Farm Network",
        )

        db.execute(
            text("""
                UPDATE MarketplaceOrders
                SET StripePaymentIntentID = :pi, PaymentStatus = 'authorized',
                    Subtotal = :sub, PlatformFee = :fee, TotalAmount = :tot, UpdatedAt = GETDATE()
                WHERE OrderID = :oid
            """),
            {"pi": intent.id, "sub": subtotal, "fee": platform_fee,
             "tot": subtotal + platform_fee, "oid": order_id},
        )
        db.commit()

        return {
            "client_secret": intent.client_secret,
            "payment_intent_id": intent.id,
            "amount": total_cents,
            "transfer_group": transfer_group,
            "transfers_pending": transfers_pending,
        }
    except stripe.error.StripeError as e:
        raise HTTPException(400, str(e))


# ============================================================
# 2. CONFIRM PAYMENT (after buyer pays via Stripe Elements)
# ============================================================

@stripe_router.post("/confirm-payment/{order_id}")
async def confirm_payment(order_id: int, payment_intent_id: str = "", db: Session = Depends(get_db)):
    """Called after frontend confirms payment via Stripe Elements"""
    stripe, _cfg = _load_stripe_config()
    currency = (_cfg.get("CurrencyCode") or "USD").lower()

    row = db.execute(
        text("SELECT StripePaymentIntentID FROM MarketplaceOrders WHERE OrderID = :oid"),
        {"oid": order_id},
    ).fetchone()
    if not row:
        raise HTTPException(404, "Order not found")

    pi_id = payment_intent_id or row[0]
    if not pi_id:
        raise HTTPException(400, "No payment intent found")

    try:
        intent = stripe.PaymentIntent.retrieve(pi_id)

        if intent.status == "succeeded":
            db.execute(
                text("""
                    UPDATE MarketplaceOrders SET PaymentStatus = 'paid', PaidAt = GETDATE(),
                        OrderStatus = 'processing', UpdatedAt = GETDATE()
                    WHERE OrderID = :oid
                """),
                {"oid": order_id},
            )
            db.execute(
                text("""
                    INSERT INTO OrderStatusHistory (OrderID, NewStatus, ChangedByRole, Notes)
                    VALUES (:oid, 'paid', 'system', 'Payment confirmed via Stripe')
                """),
                {"oid": order_id},
            )
            db.execute(
                text("""
                    UPDATE PlatformFees SET Status = 'collected', CollectedAt = GETDATE(),
                        StripeChargeID = :pi
                    WHERE OrderID = :oid
                """),
                {"pi": pi_id, "oid": order_id},
            )

            items_to_transfer = db.execute(
                text("""
                    SELECT oi.OrderItemID, oi.SellerBusinessID, oi.SellerPayout,
                           sa.StripeConnectAccountID
                    FROM MarketplaceOrderItems oi
                    LEFT JOIN StripeAccounts sa ON oi.SellerBusinessID = sa.BusinessID
                    WHERE oi.OrderID = :oid AND oi.SellerStatus = 'confirmed'
                      AND sa.StripeConnectAccountID IS NOT NULL
                """),
                {"oid": order_id},
            ).mappings().all()

            transfer_group = f"order_{order_id}"
            for item in items_to_transfer:
                payout_cents = int(round(float(item["SellerPayout"]) * 100))
                try:
                    transfer = stripe.Transfer.create(
                        amount=payout_cents,
                        currency=currency,
                        destination=item["StripeConnectAccountID"],
                        transfer_group=transfer_group,
                        metadata={"order_item_id": str(item["OrderItemID"]),
                                  "order_id": str(order_id)},
                    )
                    db.execute(
                        text("""
                            UPDATE MarketplaceOrderItems
                            SET StripeTransferID = :tid, TransferStatus = 'paid'
                            WHERE OrderItemID = :iid
                        """),
                        {"tid": transfer.id, "iid": item["OrderItemID"]},
                    )
                except stripe.error.StripeError as e:
                    print(f"[stripe] Transfer failed for item {item['OrderItemID']}: {e}")
                    db.execute(
                        text("UPDATE MarketplaceOrderItems SET TransferStatus = 'failed' WHERE OrderItemID = :iid"),
                        {"iid": item["OrderItemID"]},
                    )

            db.commit()

            try:
                from marketplace_accounting import post_marketplace_order_journal_entries
                with SessionLocal() as accdb:
                    summary = post_marketplace_order_journal_entries(order_id, accdb)
                print(f"[marketplace-accounting] confirm_payment order {order_id}: {summary}")
            except Exception as e:
                print(f"[marketplace-accounting] confirm_payment journal post failed for order {order_id}: {e}")

            return {"status": "paid", "message": "Payment confirmed and transfers initiated."}

        elif intent.status == "requires_action":
            return {"status": "requires_action", "client_secret": intent.client_secret}
        else:
            return {"status": intent.status, "message": f"Payment status: {intent.status}"}

    except stripe.error.StripeError as e:
        raise HTTPException(400, str(e))


# ============================================================
# 3. STRIPE WEBHOOK (for async payment events)
# ============================================================

@stripe_router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events. Don't 503 if Stripe isn't configured —
    Stripe would retry forever; instead skip signature verification (Stripe
    won't actually send events when keys are missing)."""
    with SessionLocal() as db:
        cfg = get_stripe_config(db)
    import stripe
    stripe.api_key = cfg.get("StripeSecretKey") or ""
    webhook_secret = cfg.get("StripeWebhookSecret") or ""

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig, webhook_secret)
        else:
            event = json.loads(payload)
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(400, "Invalid webhook signature")

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {}) or {}

    with SessionLocal() as db:
        if event_type == "payment_intent.succeeded":
            order_id = data.get("metadata", {}).get("order_id")
            if order_id:
                oid = int(order_id)
                db.execute(
                    text("""
                        UPDATE MarketplaceOrders SET PaymentStatus = 'paid',
                            PaidAt = GETDATE(), UpdatedAt = GETDATE()
                        WHERE OrderID = :oid AND PaymentStatus != 'paid'
                    """),
                    {"oid": oid},
                )
                db.commit()

                # Idempotent post — if confirm_payment already ran, the existing
                # JournalEntries row will short-circuit this call.
                try:
                    from marketplace_accounting import post_marketplace_order_journal_entries
                    with SessionLocal() as accdb:
                        summary = post_marketplace_order_journal_entries(oid, accdb)
                    print(f"[marketplace-accounting] webhook order {oid}: {summary}")
                except Exception as e:
                    print(f"[marketplace-accounting] webhook journal post failed for order {oid}: {e}")

        elif event_type == "payment_intent.payment_failed":
            order_id = data.get("metadata", {}).get("order_id")
            if order_id:
                db.execute(
                    text("UPDATE MarketplaceOrders SET PaymentStatus = 'failed', UpdatedAt = GETDATE() WHERE OrderID = :oid"),
                    {"oid": int(order_id)},
                )
                db.commit()

        elif event_type == "account.updated":
            account_id = data.get("id")
            db.execute(
                text("""
                    UPDATE StripeAccounts SET
                        OnboardingComplete = :oc, PayoutsEnabled = :pe,
                        ChargesEnabled = :ce, UpdatedAt = GETDATE()
                    WHERE StripeConnectAccountID = :acct
                """),
                {
                    "oc": 1 if data.get("details_submitted") else 0,
                    "pe": 1 if data.get("payouts_enabled") else 0,
                    "ce": 1 if data.get("charges_enabled") else 0,
                    "acct": account_id,
                },
            )
            db.commit()

    return {"received": True}


# ============================================================
# 4. REFUND
# ============================================================

@stripe_router.post("/refund/{order_item_id}")
async def refund_order_item(order_item_id: int, db: Session = Depends(get_db)):
    """Refund a specific order item (e.g., seller rejected after payment)."""
    stripe, _cfg = _load_stripe_config()

    row = db.execute(
        text("""
            SELECT oi.LineTotal, oi.StripeTransferID, o.StripePaymentIntentID
            FROM MarketplaceOrderItems oi
            JOIN MarketplaceOrders o ON oi.OrderID = o.OrderID
            WHERE oi.OrderItemID = :iid
        """),
        {"iid": order_item_id},
    ).fetchone()
    if not row:
        raise HTTPException(404, "Order item not found")

    line_total, transfer_id, pi_id = row
    refund_cents = int(round(float(line_total) * 100))

    try:
        if transfer_id:
            stripe.Transfer.create_reversal(transfer_id, amount=refund_cents)
        if pi_id:
            stripe.Refund.create(payment_intent=pi_id, amount=refund_cents)

        db.execute(
            text("UPDATE MarketplaceOrderItems SET TransferStatus = 'refunded' WHERE OrderItemID = :iid"),
            {"iid": order_item_id},
        )
        db.execute(
            text("""
                INSERT INTO OrderStatusHistory (OrderID, OrderItemID, NewStatus, ChangedByRole, Notes)
                SELECT OrderID, :iid, 'refunded', 'system', 'Item refunded via Stripe'
                FROM MarketplaceOrderItems WHERE OrderItemID = :iid
            """),
            {"iid": order_item_id},
        )
        db.commit()
        return {"message": "Refund processed.", "amount": refund_cents / 100}

    except stripe.error.StripeError as e:
        raise HTTPException(400, str(e))


# ============================================================
# 5. STRIPE CONNECT — SELLER ONBOARDING
# ============================================================
#
# Flow:
#   1. Seller visits /account/stripe-connect?BusinessID=X
#   2. Frontend GETs /connect-account/{business_id} to read status
#   3. If not connected, POSTs /connect-account/{business_id}/create → receives
#      onboarding URL, redirects to Stripe-hosted onboarding
#   4. On return, GET status again — webhook (account.updated) flips
#      OnboardingComplete/PayoutsEnabled/ChargesEnabled asynchronously
#   5. If user abandoned onboarding, POST /onboarding-link regenerates the URL


def _business_email(db: Session, business_id: int) -> Optional[str]:
    row = db.execute(
        text("SELECT BusinessEmail FROM Business WHERE BusinessID = :b"),
        {"b": business_id},
    ).fetchone()
    return row[0] if row and row[0] else None


def _onboarding_link(stripe, account_id: str, business_id: int) -> str:
    """Create an AccountLink for onboarding. Used by both create + refresh flows."""
    link = stripe.AccountLink.create(
        account=account_id,
        refresh_url=f"{OFN_BASE_URL}/account/stripe-connect?BusinessID={business_id}&refresh=1",
        return_url=f"{OFN_BASE_URL}/account/stripe-connect?BusinessID={business_id}&return=1",
        type="account_onboarding",
    )
    return link.url


@stripe_router.get("/connect-account/{business_id}")
def get_connect_account(
    business_id: int,
    db: Session = Depends(get_db),
    people_id: str = Depends(get_current_user),
):
    """Return Stripe Connect account status for this business."""
    _require_business_access(db, people_id, business_id)
    row = db.execute(
        text("""
            SELECT StripeConnectAccountID, OnboardingComplete, PayoutsEnabled,
                   ChargesEnabled, UpdatedAt
            FROM StripeAccounts WHERE BusinessID = :b
        """),
        {"b": business_id},
    ).fetchone()
    if not row:
        return {
            "connected": False,
            "onboarding_complete": False,
            "payouts_enabled": False,
            "charges_enabled": False,
            "account_id": None,
        }
    return {
        "connected": bool(row[0]),
        "onboarding_complete": bool(row[1]),
        "payouts_enabled": bool(row[2]),
        "charges_enabled": bool(row[3]),
        "account_id": row[0],
        "updated_at": row[4].isoformat() if row[4] else None,
    }


@stripe_router.post("/connect-account/{business_id}/create")
def create_connect_account(
    business_id: int,
    db: Session = Depends(get_db),
    people_id: str = Depends(get_current_user),
):
    """Create a Stripe Express account for this business and return the
    onboarding URL. Idempotent — if an account already exists, returns a
    fresh onboarding link for it instead."""
    _require_business_access(db, people_id, business_id)
    stripe, _cfg = _load_stripe_config()

    existing = db.execute(
        text("SELECT StripeConnectAccountID FROM StripeAccounts WHERE BusinessID = :b"),
        {"b": business_id},
    ).fetchone()

    if existing and existing[0]:
        url = _onboarding_link(stripe, existing[0], business_id)
        return {"account_id": existing[0], "onboarding_url": url, "reused": True}

    email = _business_email(db, business_id)
    try:
        account = stripe.Account.create(
            type="express",
            country="US",
            email=email,
            capabilities={
                "card_payments": {"requested": True},
                "transfers": {"requested": True},
            },
            metadata={"business_id": str(business_id)},
        )
    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Stripe error creating account: {e}")

    db.execute(
        text("""
            INSERT INTO StripeAccounts
                (BusinessID, StripeConnectAccountID, OnboardingComplete, PayoutsEnabled,
                 ChargesEnabled, DefaultCurrency, CreatedAt, UpdatedAt)
            VALUES (:b, :acct, 0, 0, 0, 'usd', GETDATE(), GETDATE())
        """),
        {"b": business_id, "acct": account.id},
    )
    db.commit()

    url = _onboarding_link(stripe, account.id, business_id)
    return {"account_id": account.id, "onboarding_url": url, "reused": False}


@stripe_router.post("/connect-account/{business_id}/onboarding-link")
def refresh_onboarding_link(
    business_id: int,
    db: Session = Depends(get_db),
    people_id: str = Depends(get_current_user),
):
    """Regenerate an onboarding link (the original expires). Used when the
    seller returns to finish setup after abandoning it."""
    _require_business_access(db, people_id, business_id)
    stripe, _cfg = _load_stripe_config()

    row = db.execute(
        text("SELECT StripeConnectAccountID FROM StripeAccounts WHERE BusinessID = :b"),
        {"b": business_id},
    ).fetchone()
    if not row or not row[0]:
        raise HTTPException(404, "No Stripe account for this business — create one first.")

    url = _onboarding_link(stripe, row[0], business_id)
    return {"account_id": row[0], "onboarding_url": url}


@stripe_router.post("/connect-account/{business_id}/sync")
def sync_connect_account(
    business_id: int,
    db: Session = Depends(get_db),
    people_id: str = Depends(get_current_user),
):
    """Pull the latest account state from Stripe and update our row. Useful
    right after the seller returns from onboarding, when the webhook may not
    have arrived yet."""
    _require_business_access(db, people_id, business_id)
    stripe, _cfg = _load_stripe_config()

    row = db.execute(
        text("SELECT StripeConnectAccountID FROM StripeAccounts WHERE BusinessID = :b"),
        {"b": business_id},
    ).fetchone()
    if not row or not row[0]:
        raise HTTPException(404, "No Stripe account for this business.")

    try:
        account = stripe.Account.retrieve(row[0])
    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Stripe error: {e}")

    db.execute(
        text("""
            UPDATE StripeAccounts SET
                OnboardingComplete = :oc, PayoutsEnabled = :pe,
                ChargesEnabled = :ce, UpdatedAt = GETDATE()
            WHERE BusinessID = :b
        """),
        {
            "oc": 1 if account.get("details_submitted") else 0,
            "pe": 1 if account.get("payouts_enabled") else 0,
            "ce": 1 if account.get("charges_enabled") else 0,
            "b": business_id,
        },
    )
    db.commit()

    return {
        "onboarding_complete": bool(account.get("details_submitted")),
        "payouts_enabled": bool(account.get("payouts_enabled")),
        "charges_enabled": bool(account.get("charges_enabled")),
    }
