# marketplace_emails.py
# SendGrid email notifications for the Farm2Restaurant Marketplace

import os
from datetime import datetime

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "john@oatmeal-ai.com")
FROM_NAME = os.getenv("FROM_NAME", "Oatmeal Farm Network")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "john@oatmeal-ai.com")
OFN_BASE_URL = os.getenv("OFN_BASE_URL", "https://oatmealfarmnetwork.com")

from main import get_db_cursor  # Adjust import

def _send(to, subject, html, text=None):
    """Send email via SendGrid and log it"""
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail, Email, To, Content
        sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
        message = Mail(
            from_email=Email(FROM_EMAIL, FROM_NAME),
            to_emails=To(to),
            subject=subject,
            html_content=Content("text/html", html),
        )
        if text:
            message.add_content(Content("text/plain", text))
        response = sg.send(message)
        return response.status_code < 300
    except Exception as e:
        print(f"[email] Failed to send to {to}: {e}")
        return False


def _log_email(order_id, order_item_id, email, role, email_type, subject):
    try:
        cursor = get_db_cursor()
        cursor.execute("""
            INSERT INTO MarketplaceEmails (OrderID, OrderItemID, RecipientEmail, RecipientRole, EmailType, Subject)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [order_id, order_item_id, email, role, email_type, subject])
        cursor.connection.commit()
    except:
        pass


def _header():
    return """
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
    <div style="text-align:center;margin-bottom:24px;">
        <h1 style="color:#819360;margin:0;">Oatmeal Farm Network</h1>
        <p style="color:#6b7280;margin:4px 0 0;font-size:14px;">Farm to Restaurant Marketplace</p>
    </div>"""


def _footer():
    return f"""
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:30px 0;"/>
    <p style="color:#9ca3af;font-size:11px;text-align:center;">
        This email was sent by Oatmeal Farm Network. 
        <a href="{OFN_BASE_URL}" style="color:#819360;">Visit the marketplace</a>
    </p></div>"""


def _status_badge(status, color="#819360"):
    return f'<span style="background:{color};color:#fff;padding:3px 10px;border-radius:4px;font-size:12px;font-weight:bold;">{status.upper()}</span>'


# ============================================================
# ORDER PLACED - sent to buyer and each seller
# ============================================================

def send_order_placed_buyer(order_id):
    cursor = get_db_cursor()
    cursor.execute("SELECT * FROM MarketplaceOrders WHERE OrderID = ?", [order_id])
    cols = [d[0] for d in cursor.description]
    order = dict(zip(cols, cursor.fetchone()))

    cursor.execute("""
        SELECT oi.*, b.BusinessName FROM MarketplaceOrderItems oi
        JOIN Business b ON oi.SellerBusinessID = b.BusinessID WHERE oi.OrderID = ?
    """, [order_id])
    icols = [d[0] for d in cursor.description]
    items = [dict(zip(icols, r)) for r in cursor.fetchall()]

    items_html = ""
    for it in items:
        items_html += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #f3f4f6;">{it['ProductTitle']}</td>
            <td style="padding:8px;border-bottom:1px solid #f3f4f6;">{it['BusinessName']}</td>
            <td style="padding:8px;border-bottom:1px solid #f3f4f6;text-align:right;">{it['Quantity']}</td>
            <td style="padding:8px;border-bottom:1px solid #f3f4f6;text-align:right;">${float(it['LineTotal']):.2f}</td>
        </tr>"""

    html = f"""{_header()}
    <h2 style="color:#111827;">Order Confirmed! 🎉</h2>
    <p>Hi {order['BuyerName']},</p>
    <p>Your order <strong>{order['OrderNumber']}</strong> has been placed. Sellers will review and confirm each item.</p>
    
    <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin:16px 0;">
        <p style="margin:0 0 4px;font-weight:bold;">Order Summary</p>
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
            <tr style="background:#f3f4f6;"><th style="padding:8px;text-align:left;">Item</th><th style="padding:8px;text-align:left;">Seller</th><th style="padding:8px;text-align:right;">Qty</th><th style="padding:8px;text-align:right;">Total</th></tr>
            {items_html}
            <tr style="font-weight:bold;"><td colspan="3" style="padding:8px;">Subtotal</td><td style="padding:8px;text-align:right;">${float(order['Subtotal']):.2f}</td></tr>
            <tr><td colspan="3" style="padding:8px;color:#6b7280;">Service Fee (2.5%)</td><td style="padding:8px;text-align:right;color:#6b7280;">${float(order['PlatformFee']):.2f}</td></tr>
            <tr style="font-weight:bold;font-size:16px;"><td colspan="3" style="padding:8px;">Total</td><td style="padding:8px;text-align:right;color:#819360;">${float(order['TotalAmount']):.2f}</td></tr>
        </table>
    </div>
    
    <p style="color:#6b7280;font-size:13px;">Payment will only be charged after sellers confirm your items. You'll receive an email when items are confirmed.</p>
    
    <div style="text-align:center;margin:24px 0;">
        <a href="{OFN_BASE_URL}/orders/{order_id}" style="background:#819360;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:bold;">View Order</a>
    </div>
    {_footer()}"""

    subject = f"Order {order['OrderNumber']} Placed - Oatmeal Farm Network"
    _send(order['BuyerEmail'], subject, html)
    _log_email(order_id, None, order['BuyerEmail'], 'buyer', 'order_placed', subject)


def send_order_placed_seller(order_id, seller_business_id):
    cursor = get_db_cursor()
    cursor.execute("SELECT OrderNumber, BuyerName, DeliveryMethod, RequestedDeliveryDate FROM MarketplaceOrders WHERE OrderID = ?", [order_id])
    order = cursor.fetchone()

    cursor.execute("""
        SELECT oi.ProductTitle, oi.Quantity, oi.UnitPrice, oi.LineTotal, oi.SellerPayout, oi.OrderItemID
        FROM MarketplaceOrderItems oi WHERE oi.OrderID = ? AND oi.SellerBusinessID = ?
    """, [order_id, seller_business_id])
    items = cursor.fetchall()

    # Get seller email
    cursor.execute("""
        SELECT p.PeopleEmail, p.PeopleFirstName FROM People p
        JOIN Business b ON b.PeopleID = p.PeopleID WHERE b.BusinessID = ?
    """, [seller_business_id])
    seller = cursor.fetchone()
    if not seller or not seller[0]:
        return

    items_html = ""
    total_payout = 0
    for it in items:
        items_html += f"<tr><td style='padding:6px;'>{it[0]}</td><td style='padding:6px;text-align:right;'>{it[1]}</td><td style='padding:6px;text-align:right;'>${float(it[3]):.2f}</td><td style='padding:6px;text-align:right;color:#059669;'>${float(it[4]):.2f}</td></tr>"
        total_payout += float(it[4])

    html = f"""{_header()}
    <h2 style="color:#111827;">New Order! 📦</h2>
    <p>Hi {seller[1]},</p>
    <p>You've received a new order from <strong>{order[1]}</strong> (Order #{order[0]}).</p>
    <p><strong>Please confirm or reject each item within 24 hours.</strong></p>
    
    <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:16px;margin:16px 0;">
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
            <tr style="font-weight:bold;"><td style="padding:6px;">Item</td><td style="padding:6px;text-align:right;">Qty</td><td style="padding:6px;text-align:right;">Sale</td><td style="padding:6px;text-align:right;">Your Payout</td></tr>
            {items_html}
            <tr style="font-weight:bold;font-size:15px;border-top:2px solid #bbf7d0;"><td colspan="3" style="padding:8px;">Total Payout</td><td style="padding:8px;text-align:right;color:#059669;">${total_payout:.2f}</td></tr>
        </table>
    </div>
    
    <p>Delivery: <strong>{order[2] or 'Pickup'}</strong>{f" · Requested: {order[3]}" if order[3] else ""}</p>
    
    <div style="text-align:center;margin:24px 0;">
        <a href="{OFN_BASE_URL}/seller/orders?BusinessID={seller_business_id}" style="background:#059669;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:bold;">Review & Confirm</a>
    </div>
    {_footer()}"""

    subject = f"New Order #{order[0]} - Action Required"
    _send(seller[0], subject, html)
    _log_email(order_id, None, seller[0], 'seller', 'order_placed', subject)


# ============================================================
# ITEM CONFIRMED/REJECTED - sent to buyer
# ============================================================

def send_item_status_buyer(order_id, order_item_id, status):
    cursor = get_db_cursor()
    cursor.execute("SELECT BuyerEmail, BuyerName, OrderNumber FROM MarketplaceOrders WHERE OrderID = ?", [order_id])
    order = cursor.fetchone()
    if not order or not order[0]:
        return

    cursor.execute("""
        SELECT ProductTitle, SellerName, Quantity, LineTotal, RejectionReason
        FROM MarketplaceOrderItems WHERE OrderItemID = ?
    """, [order_item_id])
    item = cursor.fetchone()

    if status == "confirmed":
        badge = _status_badge("Confirmed", "#059669")
        message = f"<strong>{item[1]}</strong> has confirmed your order for <strong>{item[0]}</strong> ({item[2]} units, ${float(item[3]):.2f})."
        action = "You'll be charged once all sellers have responded."
    else:
        badge = _status_badge("Rejected", "#dc2626")
        message = f"<strong>{item[1]}</strong> was unable to fulfill your order for <strong>{item[0]}</strong>."
        if item[4]:
            message += f"<br>Reason: <em>{item[4]}</em>"
        action = "You will NOT be charged for this item."

    html = f"""{_header()}
    <h2 style="color:#111827;">Order Update {badge}</h2>
    <p>Hi {order[1]},</p>
    <p>{message}</p>
    <p style="color:#6b7280;font-size:13px;">{action}</p>
    <div style="text-align:center;margin:24px 0;">
        <a href="{OFN_BASE_URL}/orders/{order_id}" style="background:#819360;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:bold;">View Order</a>
    </div>
    {_footer()}"""

    subject = f"Order {order[2]} - Item {status.title()}"
    _send(order[0], subject, html)
    _log_email(order_id, order_item_id, order[0], 'buyer', f'item_{status}', subject)


# ============================================================
# READY FOR PAYMENT - sent to buyer when all sellers responded
# ============================================================

def send_ready_for_payment(order_id):
    cursor = get_db_cursor()
    cursor.execute("SELECT BuyerEmail, BuyerName, OrderNumber, TotalAmount FROM MarketplaceOrders WHERE OrderID = ?", [order_id])
    order = cursor.fetchone()
    if not order or not order[0]:
        return

    html = f"""{_header()}
    <h2 style="color:#111827;">Ready for Payment 💳</h2>
    <p>Hi {order[1]},</p>
    <p>All sellers have reviewed your order <strong>{order[2]}</strong>. Your total is <strong style="color:#819360;font-size:18px;">${float(order[3]):.2f}</strong>.</p>
    <p>Please complete your payment to proceed.</p>
    <div style="text-align:center;margin:24px 0;">
        <a href="{OFN_BASE_URL}/orders/{order_id}?pay=true" style="background:#819360;color:#fff;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:16px;">Pay Now</a>
    </div>
    {_footer()}"""

    subject = f"Order {order[2]} - Payment Ready"
    _send(order[0], subject, html)
    _log_email(order_id, None, order[0], 'buyer', 'ready_for_payment', subject)


# ============================================================
# SHIPPED - sent to buyer
# ============================================================

def send_item_shipped(order_id, order_item_id):
    cursor = get_db_cursor()
    cursor.execute("SELECT BuyerEmail, BuyerName, OrderNumber FROM MarketplaceOrders WHERE OrderID = ?", [order_id])
    order = cursor.fetchone()

    cursor.execute("SELECT ProductTitle, SellerName, TrackingNumber FROM MarketplaceOrderItems WHERE OrderItemID = ?", [order_item_id])
    item = cursor.fetchone()

    tracking_msg = f"<p>Tracking number: <strong>{item[2]}</strong></p>" if item[2] else ""

    html = f"""{_header()}
    <h2 style="color:#111827;">Item Shipped! 🚛</h2>
    <p>Hi {order[1]},</p>
    <p><strong>{item[0]}</strong> from <strong>{item[1]}</strong> has been shipped!</p>
    {tracking_msg}
    <div style="text-align:center;margin:24px 0;">
        <a href="{OFN_BASE_URL}/orders/{order_id}" style="background:#819360;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:bold;">Track Order</a>
    </div>
    {_footer()}"""

    subject = f"Order {order[2]} - Item Shipped"
    _send(order[0], subject, html)
    _log_email(order_id, order_item_id, order[0], 'buyer', 'item_shipped', subject)


# ============================================================
# DELIVERED - sent to seller
# ============================================================

def send_delivery_confirmed(order_id, order_item_id):
    cursor = get_db_cursor()
    cursor.execute("""
        SELECT oi.SellerBusinessID, oi.ProductTitle, oi.SellerPayout, o.OrderNumber, o.BuyerName
        FROM MarketplaceOrderItems oi
        JOIN MarketplaceOrders o ON oi.OrderID = o.OrderID
        WHERE oi.OrderItemID = ?
    """, [order_item_id])
    row = cursor.fetchone()
    if not row:
        return

    cursor.execute("SELECT p.PeopleEmail, p.PeopleFirstName FROM People p JOIN Business b ON b.PeopleID = p.PeopleID WHERE b.BusinessID = ?", [row[0]])
    seller = cursor.fetchone()
    if not seller or not seller[0]:
        return

    html = f"""{_header()}
    <h2 style="color:#111827;">Delivery Confirmed ✅</h2>
    <p>Hi {seller[1]},</p>
    <p><strong>{row[4]}</strong> has confirmed delivery of <strong>{row[1]}</strong> (Order #{row[3]}).</p>
    <p>Your payout of <strong style="color:#059669;">${float(row[2]):.2f}</strong> has been transferred to your Stripe account.</p>
    {_footer()}"""

    subject = f"Order {row[3]} - Delivery Confirmed, Payout Sent"
    _send(seller[0], subject, html)
    _log_email(order_id, order_item_id, seller[0], 'seller', 'delivery_confirmed', subject)


# ============================================================
# ADMIN NOTIFICATION - daily summary or per-order
# ============================================================

def send_admin_order_notification(order_id):
    cursor = get_db_cursor()
    cursor.execute("SELECT OrderNumber, BuyerName, TotalAmount, PlatformFee FROM MarketplaceOrders WHERE OrderID = ?", [order_id])
    order = cursor.fetchone()

    html = f"""{_header()}
    <h2>New Marketplace Order</h2>
    <p>Order <strong>{order[0]}</strong> from {order[1]}</p>
    <p>Total: ${float(order[2]):.2f} | Platform Fee: <strong style="color:#059669;">${float(order[3]):.2f}</strong></p>
    <a href="{OFN_BASE_URL}/orders/{order_id}">View Order</a>
    {_footer()}"""

    _send(ADMIN_EMAIL, f"New Order {order[0]} - ${float(order[3]):.2f} fee", html)
    _log_email(order_id, None, ADMIN_EMAIL, 'admin', 'admin_notification', f"New Order {order[0]}")
