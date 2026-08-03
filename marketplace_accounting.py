# marketplace_accounting.py
# Auto-posts a journal entry to each seller's books when a marketplace order
# is paid. Idempotent — SourceType='MarketplaceOrderItem' + SourceID=OrderItemID
# lets us detect prior posts so re-entry from webhook + sync path doesn't
# double-book.
#
# Entry pattern per order item (on the seller's BusinessID books):
#   Debit  1000 Checking Account       SellerPayout
#   Debit  6110 Stripe Fees            PlatformFee
#   Credit 4000 Sales Revenue          LineTotal    (goods)
#   Credit 4100 Service Revenue        LineTotal    (services)
# Debits + Credits balance: SellerPayout + PlatformFee == LineTotal.

from sqlalchemy import text
from sqlalchemy.orm import Session


SERVICE_REVENUE_TYPES = {"service"}


def _get_account_id(db: Session, business_id: int, account_number: str):
    row = db.execute(
        text("SELECT TOP 1 AccountID FROM Accounts WHERE BusinessID = :bid AND AccountNumber = :n AND IsActive = 1"),
        {"bid": business_id, "n": account_number},
    ).fetchone()
    return row[0] if row else None


def _next_entry_number(db: Session, business_id: int) -> str:
    row = db.execute(
        text("SELECT TOP 1 EntryNumber FROM JournalEntries WHERE BusinessID = :bid ORDER BY EntryNumber DESC"),
        {"bid": business_id},
    ).fetchone()
    if not row or not row[0]:
        return "JE-00001"
    try:
        n = int(str(row[0]).rsplit("-", 1)[-1]) + 1
    except ValueError:
        n = 1
    return f"JE-{n:05d}"


def post_marketplace_order_journal_entries(order_id: int, db: Session) -> dict:
    """Post a journal entry to each seller's books for every paid+confirmed
    order item in the given order. Idempotent on OrderItemID.

    Returns a summary dict for logging: {posted, skipped_existing, skipped_missing_coa}.
    """
    order = db.execute(
        text("SELECT OrderID, OrderNumber, BuyerPeopleID, PaidAt FROM MarketplaceOrders WHERE OrderID = :oid"),
        {"oid": order_id},
    ).fetchone()
    if not order:
        return {"error": "order_not_found"}

    items = db.execute(
        text("""
            SELECT OrderItemID, SellerBusinessID, ProductTitle, ProductType,
                   LineTotal, PlatformFee, SellerPayout
            FROM MarketplaceOrderItems
            WHERE OrderID = :oid AND SellerStatus = 'confirmed'
        """),
        {"oid": order_id},
    ).fetchall()

    posted = 0
    skipped_existing = 0
    skipped_missing_coa = 0
    entry_date = order.PaidAt or None

    for it in items:
        existing = db.execute(
            text("SELECT TOP 1 JournalEntryID FROM JournalEntries WHERE SourceType = 'MarketplaceOrderItem' AND SourceID = :id"),
            {"id": it.OrderItemID},
        ).fetchone()
        if existing:
            skipped_existing += 1
            continue

        bid = it.SellerBusinessID
        cash_acct = _get_account_id(db, bid, "1000")
        fee_acct = _get_account_id(db, bid, "6110")
        revenue_num = "4100" if (it.ProductType or "").lower() in SERVICE_REVENUE_TYPES else "4000"
        rev_acct = _get_account_id(db, bid, revenue_num)
        if not (cash_acct and rev_acct and fee_acct):
            skipped_missing_coa += 1
            continue

        line_total = float(it.LineTotal or 0)
        platform_fee = float(it.PlatformFee or 0)
        seller_payout = float(it.SellerPayout or 0)
        # Self-heal rounding drift so debits == credits to the cent.
        drift = round(line_total - (platform_fee + seller_payout), 2)
        if drift:
            seller_payout = round(seller_payout + drift, 2)

        entry_number = _next_entry_number(db, bid)
        je_row = db.execute(
            text("""
                INSERT INTO JournalEntries (BusinessID, EntryNumber, EntryDate, Description, Reference, SourceType, SourceID, IsPosted, CreatedBy)
                OUTPUT INSERTED.JournalEntryID
                VALUES (:bid, :num, COALESCE(:date, CAST(GETDATE() AS DATE)), :desc, :ref, 'MarketplaceOrderItem', :srcId, 1, :by)
            """),
            {
                "bid": bid, "num": entry_number, "date": entry_date,
                "desc": f"Marketplace sale — {it.ProductTitle or 'item'} (Order {order.OrderNumber})",
                "ref": order.OrderNumber, "srcId": it.OrderItemID,
                "by": order.BuyerPeopleID,
            },
        ).fetchone()
        je_id = je_row[0]

        line_params = [
            {"je": je_id, "bid": bid, "acct": cash_acct, "debit": seller_payout,   "credit": 0,          "desc": f"Stripe payout — Order {order.OrderNumber}",     "ord": 0},
            {"je": je_id, "bid": bid, "acct": fee_acct,  "debit": platform_fee,    "credit": 0,          "desc": f"OFN platform fee — Order {order.OrderNumber}",  "ord": 1},
            {"je": je_id, "bid": bid, "acct": rev_acct,  "debit": 0,               "credit": line_total, "desc": f"Revenue — {it.ProductTitle or 'item'}",          "ord": 2},
        ]
        for p in line_params:
            db.execute(
                text("""
                    INSERT INTO JournalEntryLines (JournalEntryID, BusinessID, AccountID, DebitAmount, CreditAmount, Description, LineOrder)
                    VALUES (:je, :bid, :acct, :debit, :credit, :desc, :ord)
                """),
                p,
            )
        posted += 1

    db.commit()
    return {"posted": posted, "skipped_existing": skipped_existing, "skipped_missing_coa": skipped_missing_coa}
