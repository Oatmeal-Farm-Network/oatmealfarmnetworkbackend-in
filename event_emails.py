"""
Event registration confirmation emails.

Sends a polished confirmation with event details + a QR code that encodes
the registrant's check-in token. The QR is rendered via a hosted QR generator
(api.qrserver.com) so nothing extra needs to be installed and images survive
most email clients.
"""
import os
import urllib.parse

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
FROM_EMAIL       = os.getenv("FROM_EMAIL", "john@oatmeal-ai.com")
FROM_NAME        = os.getenv("FROM_NAME", "Oatmeal Farm Network")
OFN_BASE_URL     = os.getenv("OFN_BASE_URL", "https://oatmealfarmnetwork.com")


def _qr_url(payload: str, size: int = 220) -> str:
    return (
        f"https://api.qrserver.com/v1/create-qr-code/"
        f"?size={size}x{size}&data={urllib.parse.quote(payload)}"
    )


def _send(to: str, subject: str, html: str) -> bool:
    if not SENDGRID_API_KEY or not to:
        return False
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
        response = sg.send(message)
        return response.status_code < 300
    except Exception as ex:
        print(f"[event_email] send to {to} failed: {ex}")
        return False


def _fmt_date(d):
    if not d: return ''
    try:
        return d.strftime('%A, %B %d, %Y')
    except Exception:
        return str(d)


def _event_block(event: dict) -> str:
    addr = ', '.join(x for x in [
        event.get('EventLocationName'), event.get('EventLocationStreet'),
        event.get('EventLocationCity'), event.get('EventLocationState'),
        event.get('EventLocationZip')
    ] if x)
    return f"""
      <tr><td style="padding:6px 0;font-size:13px;color:#555">
        <strong>When:</strong> {_fmt_date(event.get('EventStartDate'))}
      </td></tr>
      {f'<tr><td style="padding:6px 0;font-size:13px;color:#555"><strong>Where:</strong> {addr}</td></tr>' if addr else ''}
    """


def send_cart_receipt(
    to_email: str,
    attendee_name: str,
    event: dict,
    cart: dict,
    items: list,
):
    """Receipt email for a unified registration-cart payment (wizard flow)."""
    if not to_email:
        return False
    name = (attendee_name or '').split()[0] if attendee_name else 'there'
    cart_id = cart.get('CartID')
    subject = f"Receipt — {event.get('EventName', 'Event')}"
    qr = _qr_url(f"cart:{cart_id}")

    rows_html = ""
    for it in items or []:
        qty = it.get('Quantity') or 1
        unit = float(it.get('UnitAmount') or 0)
        line = float(it.get('LineAmount') or (qty * unit))
        label = it.get('Label') or (it.get('FeatureKey') or 'Item')
        rows_html += (
            f'<tr>'
            f'<td style="padding:6px 0;font-size:13px;color:#333">{label}</td>'
            f'<td style="padding:6px 0;font-size:13px;color:#555;text-align:right">{qty}</td>'
            f'<td style="padding:6px 0;font-size:13px;color:#555;text-align:right">${unit:.2f}</td>'
            f'<td style="padding:6px 0;font-size:13px;color:#333;text-align:right">${line:.2f}</td>'
            f'</tr>'
        )

    subtotal = float(cart.get('Subtotal') or 0)
    fee = float(cart.get('PlatformFeeAmount') or 0)
    total = float(cart.get('Total') or 0)
    paid = float(cart.get('AmountPaid') or 0)
    status = cart.get('Status') or 'paid'

    receipt_url = f"{OFN_BASE_URL}/events/cart/{cart_id}/receipt"

    html = f"""
<!DOCTYPE html>
<html><body style="font-family:Georgia,serif;background:#FAF7EE;margin:0;padding:24px">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:0 auto;background:white;border-radius:12px;overflow:hidden">
    <tr><td style="background:#3D6B34;color:white;padding:20px 24px;">
      <div style="font-size:12px;text-transform:uppercase;letter-spacing:0.15em;opacity:0.8">Payment Receipt</div>
      <div style="font-size:22px;font-weight:600;margin-top:4px">{event.get('EventName','Event')}</div>
    </td></tr>
    <tr><td style="padding:20px 24px">
      <p style="font-size:14px;color:#333;margin:0 0 12px">Hi {name},</p>
      <p style="font-size:14px;color:#555;margin:0 0 16px">
        Thanks for registering. Below is a receipt for your records.
      </p>
      <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #eee;border-bottom:1px solid #eee;margin:12px 0">
        {_event_block(event)}
        <tr><td style="padding:6px 0;font-size:13px;color:#555">
          <strong>Order #:</strong> {cart_id} &nbsp; <strong>Status:</strong> {status}
        </td></tr>
      </table>

      <table width="100%" cellpadding="0" cellspacing="0" style="margin:16px 0;border-collapse:collapse">
        <thead>
          <tr style="border-bottom:1px solid #ddd">
            <th style="text-align:left;font-size:11px;color:#888;text-transform:uppercase;padding:6px 0">Item</th>
            <th style="text-align:right;font-size:11px;color:#888;text-transform:uppercase;padding:6px 0">Qty</th>
            <th style="text-align:right;font-size:11px;color:#888;text-transform:uppercase;padding:6px 0">Unit</th>
            <th style="text-align:right;font-size:11px;color:#888;text-transform:uppercase;padding:6px 0">Line</th>
          </tr>
        </thead>
        <tbody>
          {rows_html or '<tr><td colspan="4" style="padding:12px 0;font-size:13px;color:#999;font-style:italic">No line items.</td></tr>'}
        </tbody>
        <tfoot>
          <tr><td colspan="3" style="padding:6px 0;text-align:right;font-size:13px;color:#555">Subtotal</td>
              <td style="padding:6px 0;text-align:right;font-size:13px;color:#333">${subtotal:.2f}</td></tr>
          <tr><td colspan="3" style="padding:6px 0;text-align:right;font-size:13px;color:#555">Platform Fee</td>
              <td style="padding:6px 0;text-align:right;font-size:13px;color:#333">${fee:.2f}</td></tr>
          <tr style="border-top:2px solid #333"><td colspan="3" style="padding:8px 0;text-align:right;font-size:14px;color:#333;font-weight:bold">Total Paid</td>
              <td style="padding:8px 0;text-align:right;font-size:14px;color:#333;font-weight:bold">${paid:.2f}</td></tr>
        </tfoot>
      </table>

      <div style="text-align:center;margin:20px 0">
        <img src="{qr}" alt="Check-in QR" style="border:6px solid #3D6B34;border-radius:8px" />
        <div style="font-size:11px;color:#999;margin-top:6px">Show this code at check-in · Cart {cart_id}</div>
      </div>

      <p style="font-size:13px;color:#555;margin:16px 0 0;text-align:center">
        <a href="{receipt_url}" style="color:#3D6B34;font-weight:bold">View or print full receipt →</a>
      </p>
      <p style="font-size:12px;color:#999;margin:16px 0 0">
        Questions or need a refund? Reply to this email or visit
        <a href="{OFN_BASE_URL}/my-registrations" style="color:#3D6B34">{OFN_BASE_URL}/my-registrations</a>.
      </p>
    </td></tr>
  </table>
</body></html>"""
    return _send(to_email, subject, html)


def send_registration_confirmation(
    to_email: str,
    attendee_name: str,
    event: dict,
    kind: str,
    reg_id: int,
    extra_html: str = "",
):
    """
    Generic confirmation. kind is one of Simple|Conference|Competition|Dining|Tour.
    QR encodes plain reg_id so the unified check-in scanner finds it by exact match.
    """
    if not to_email:
        return False
    qr = _qr_url(str(reg_id))
    event_id = event.get('EventID')
    subject = f"You're registered: {event.get('EventName', 'Event')}"
    name = (attendee_name or '').split()[0] if attendee_name else 'there'
    html = f"""
<!DOCTYPE html>
<html><body style="font-family:Georgia,serif;background:#FAF7EE;margin:0;padding:24px">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:0 auto;background:white;border-radius:12px;overflow:hidden">
    <tr><td style="background:#3D6B34;color:white;padding:20px 24px;">
      <div style="font-size:12px;text-transform:uppercase;letter-spacing:0.15em;opacity:0.8">Registration Confirmed</div>
      <div style="font-size:22px;font-weight:600;margin-top:4px">{event.get('EventName','Event')}</div>
    </td></tr>
    <tr><td style="padding:20px 24px">
      <p style="font-size:14px;color:#333;margin:0 0 12px">Hi {name},</p>
      <p style="font-size:14px;color:#555;margin:0 0 16px">
        Your spot is reserved. Details below — save this email and show the QR code at check-in.
      </p>
      <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #eee;border-bottom:1px solid #eee;margin:12px 0">
        {_event_block(event)}
        <tr><td style="padding:6px 0;font-size:13px;color:#555">
          <strong>Type:</strong> {kind}
        </td></tr>
        <tr><td style="padding:6px 0;font-size:13px;color:#555">
          <strong>Reference #:</strong> {reg_id}
        </td></tr>
      </table>
      {extra_html}
      <div style="text-align:center;margin:20px 0">
        <img src="{qr}" alt="Check-in QR" style="border:6px solid #3D6B34;border-radius:8px" />
        <div style="font-size:11px;color:#999;margin-top:6px">Scan at check-in · Ref {reg_id}</div>
      </div>
      <p style="font-size:12px;color:#999;margin:16px 0 0">
        Questions? Reply to this email. View your registrations any time at
        <a href="{OFN_BASE_URL}/my-registrations" style="color:#3D6B34">{OFN_BASE_URL}/my-registrations</a>.
      </p>
    </td></tr>
  </table>
</body></html>"""
    return _send(to_email, subject, html)


def send_sponsor_confirmation(to_email: str, sponsor_name: str,
                              event: dict, tier_name: str, amount: float | None,
                              benefits_html: str | None = None) -> bool:
    """Welcome email when a sponsor's status flips to confirmed. Confirms tier
    + amount + lists their benefits. Encourages logo upload + COI submission."""
    if not to_email:
        return False
    name    = sponsor_name or "there"
    ev_name = event.get('EventName') or 'the event'
    biz_id  = event.get('BusinessID')
    ev_id   = event.get('EventID')
    sponsor_dash = f"{OFN_BASE_URL}/events/{ev_id}/admin/sponsorship"
    if biz_id:
        sponsor_dash += f"?BusinessID={biz_id}"
    amt = f" (${amount:,.2f})" if amount else ""
    subject = f"You're confirmed as a {tier_name} sponsor of {ev_name}"
    html = f"""<!doctype html><html><body style="margin:0;background:#f5f5f2;font-family:system-ui,-apple-system,Segoe UI,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f5f5f2;padding:20px 0">
<tr><td align="center">
<table role="presentation" width="560" cellspacing="0" cellpadding="0"
       style="background:#fff;border-radius:12px;padding:28px;max-width:92vw">
  <tr><td>
    <h2 style="margin:0 0 8px;color:#3D6B34">Welcome aboard, {name}!</h2>
    <p style="font-size:14px;color:#555;margin:0 0 14px">
      You're confirmed as a <strong>{tier_name} sponsor</strong> of
      <strong>{ev_name}</strong>{amt}. Thank you for supporting the event.
    </p>
    {('<div style="background:#fff7e6;border-left:4px solid #f59e0b;padding:12px 14px;margin:14px 0;border-radius:4px"><strong>Your benefits:</strong>' + benefits_html + '</div>') if benefits_html else ''}
    <p style="font-size:14px;color:#555;margin:14px 0">Next steps:</p>
    <ul style="font-size:14px;color:#555;margin:0 0 18px;padding-left:20px">
      <li>Send us your logo (PNG/SVG, transparent background) for the website + signage</li>
      <li>Submit a Certificate of Insurance naming the event host as additional insured</li>
      <li>Confirm any sponsored sessions or table giveaways</li>
    </ul>
    <div style="text-align:center;margin:22px 0">
      <a href="{sponsor_dash}"
         style="display:inline-block;background:#3D6B34;color:#fff;padding:12px 22px;
                border-radius:6px;text-decoration:none;font-size:14px;font-weight:600">
        Sponsor dashboard →
      </a>
    </div>
    <p style="font-size:12px;color:#999;margin:16px 0 0">
      Questions? Reply to this email and we'll connect you with the organizer.
    </p>
  </td></tr>
</table>
</td></tr>
</table>
</body></html>"""
    return _send(to_email, subject, html)


def send_event_testimonial_request(to_email: str, attendee_name: str,
                                   event: dict) -> bool:
    """Post-event email asking the attendee to share a quick testimonial.
    Links to the public submission page prefilled with the event's host
    BusinessID so the testimonial is attached to the right ranch."""
    if not to_email:
        return False
    name = (attendee_name or '').split()[0] if attendee_name else 'there'
    ev_name = event.get('EventName') or 'the event'
    biz_id = event.get('BusinessID')
    submit_url = f"{OFN_BASE_URL}/testimonials/submit"
    if biz_id:
        submit_url += f"?BusinessID={biz_id}&EventID={event.get('EventID','')}"
    subject = f"Thanks for coming to {ev_name} — would you share a quick testimonial?"
    html = f"""<!doctype html><html><body style="margin:0;background:#f5f5f2;font-family:system-ui,-apple-system,Segoe UI,sans-serif">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f5f5f2;padding:20px 0">
    <tr><td align="center">
    <table role="presentation" width="560" cellspacing="0" cellpadding="0"
           style="background:#fff;border-radius:12px;padding:28px;max-width:92vw">
      <tr><td>
        <h2 style="margin:0 0 8px;color:#3D6B34">Thanks for coming, {name}!</h2>
        <p style="font-size:14px;color:#555;margin:0 0 14px">
          Hope you had a great time at <strong>{ev_name}</strong>. Would you take a
          minute to share what stood out? Testimonials help other guests decide
          to come next year.
        </p>
        <div style="text-align:center;margin:22px 0">
          <a href="{submit_url}"
             style="display:inline-block;background:#3D6B34;color:#fff;padding:12px 22px;
                    border-radius:6px;text-decoration:none;font-size:14px;font-weight:600">
            Share a testimonial →
          </a>
        </div>
        <p style="font-size:12px;color:#999;margin:16px 0 0">
          Takes about 60 seconds. Your words may appear on the event host's ranch page.
        </p>
      </td></tr>
    </table>
    </td></tr>
  </table>
</body></html>"""
    return _send(to_email, subject, html)


def send_marketplace_thank_you_promo(to_email: str, buyer_name: str,
                                     codes: list[dict]) -> bool:
    """After a marketplace purchase, invite the buyer to the seller's upcoming
    event with a one-use percent-off code."""
    if not to_email or not codes:
        return False
    first = (buyer_name or '').split()[0] if buyer_name else 'there'
    rows = ""
    for c in codes:
        valid_until = c.get('ValidUntil') or ''
        try:
            from datetime import datetime as _dt
            vu = _dt.fromisoformat(valid_until).strftime('%B %d, %Y') if valid_until else ''
        except Exception:
            vu = valid_until
        rows += f"""
          <tr><td style="padding:14px;border:1px solid #e0e0e0;border-radius:8px;background:#fafaf8">
            <div style="font-size:15px;font-weight:600;color:#3D6B34;margin-bottom:4px">
              {c.get('EventName','Upcoming event')}
            </div>
            <div style="font-size:13px;color:#555;margin-bottom:10px">
              {int(c.get('PercentOff') or 0)}% off your registration
              {f'· valid through {vu}' if vu else ''}
            </div>
            <div style="font-family:monospace;font-size:18px;background:#fff;border:1px dashed #3D6B34;
                        padding:8px 12px;border-radius:6px;display:inline-block;letter-spacing:1px">
              {c.get('Code','')}
            </div>
            <div style="margin-top:10px">
              <a href="{OFN_BASE_URL}/events/{c.get('EventID')}"
                 style="display:inline-block;background:#3D6B34;color:#fff;padding:8px 16px;
                        border-radius:6px;text-decoration:none;font-size:13px;font-weight:600">
                See event details →
              </a>
            </div>
          </td></tr>
          <tr><td style="height:12px"></td></tr>
        """
    subject = "A thank-you from your farmer — discount for their upcoming event"
    html = f"""<!doctype html><html><body style="margin:0;background:#f5f5f2;font-family:system-ui,-apple-system,Segoe UI,sans-serif">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f5f5f2;padding:20px 0">
    <tr><td align="center">
    <table role="presentation" width="560" cellspacing="0" cellpadding="0"
           style="background:#fff;border-radius:12px;padding:28px;max-width:92vw">
      <tr><td>
        <h2 style="margin:0 0 8px;color:#3D6B34">Thanks for your purchase, {first}!</h2>
        <p style="font-size:14px;color:#555;margin:0 0 18px">
          To say thanks, here's a discount on an upcoming event from your seller.
          Come meet the animals in person.
        </p>
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
          {rows}
        </table>
        <p style="font-size:11px;color:#999;margin:18px 0 0">
          Each code is single-use. Apply it on the wizard's payment step.
        </p>
      </td></tr>
    </table>
    </td></tr>
  </table>
</body></html>"""
    return _send(to_email, subject, html)
