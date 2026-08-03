import os
import re
import base64
import urllib.parse
from datetime import datetime, timedelta
import sendgrid
from sendgrid.helpers.mail import (
    Mail, Email, To, Content,
    Attachment, FileContent, FileName, FileType, Disposition,
)

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL", "john@oatmeal-ai.com")
FROM_NAME  = os.getenv("FROM_NAME",  "Oatmeal Farm Network")
OFN_BASE_URL = os.getenv("OFN_BASE_URL", "https://oatmealfarmnetwork.com")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "").strip()


def _send(to: str, subject: str, html: str, ics: str | None = None) -> bool:
    try:
        sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
        msg = Mail(
            from_email=Email(FROM_EMAIL, FROM_NAME),
            to_emails=To(to),
            subject=subject,
            html_content=Content("text/html", html),
        )
        if ics:
            msg.add_attachment(Attachment(
                FileContent(base64.b64encode(ics.encode("utf-8")).decode()),
                FileName("meeting.ics"),
                FileType("text/calendar; method=REQUEST"),
                Disposition("attachment"),
            ))
        r = sg.send(msg)
        return r.status_code < 300
    except Exception as e:
        print(f"[meeting_emails] send error: {e}")
        return False


def _parse_dt(d) -> datetime | None:
    if not d:
        return None
    if isinstance(d, datetime):
        return d
    try:
        return datetime.fromisoformat(str(d).replace("Z", "+00:00"))
    except Exception:
        return None


def _fmt_date(d) -> str:
    dt = _parse_dt(d)
    if not dt:
        return "TBD"
    try:
        return dt.strftime("%A, %B %d, %Y")
    except Exception:
        return str(d)


def _fmt_time(d) -> str:
    dt = _parse_dt(d)
    if not dt:
        return ""
    try:
        return dt.strftime("%-I:%M %p")
    except Exception:
        try:
            return dt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            return ""


def _gcal_url(meeting: dict) -> str:
    title    = meeting.get("title", "Meeting")
    desc     = _strip_html(meeting.get("description") or "")
    location = meeting.get("location") or ""
    meet_link = meeting.get("google_meet_link") or ""
    if meet_link:
        desc = f"{desc}\n\nGoogle Meet: {meet_link}".strip()

    dt = _parse_dt(meeting.get("meeting_date"))
    if dt:
        start = dt.strftime("%Y%m%dT%H%M%SZ")
        end   = (dt + timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")
        dates = f"{start}/{end}"
    else:
        dates = ""

    params = urllib.parse.urlencode({
        "action":   "TEMPLATE",
        "text":     title,
        "dates":    dates,
        "details":  desc,
        "location": location,
    })
    return f"https://www.google.com/calendar/render?{params}"


def _ics_content(meeting: dict) -> str:
    def esc(s):
        return (s or "").replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")

    title     = esc(meeting.get("title", "Meeting"))
    desc      = esc(_strip_html(meeting.get("description") or ""))
    location  = esc(meeting.get("location") or "")
    meet_link = (meeting.get("google_meet_link") or "").strip()
    uid       = f"meeting-{meeting.get('meeting_id', '000')}@oatmealfarmnetwork.com"

    dt = _parse_dt(meeting.get("meeting_date"))
    if dt:
        start = dt.strftime("%Y%m%dT%H%M%SZ")
        end   = (dt + timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")
    else:
        now   = datetime.utcnow()
        start = now.strftime("%Y%m%dT%H%M%SZ")
        end   = (now + timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")

    url_line = f"URL:{meet_link}\r\n" if meet_link else ""

    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//OatmealFarmNetwork//Meetings//EN\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "METHOD:REQUEST\r\n"
        "BEGIN:VEVENT\r\n"
        f"DTSTART:{start}\r\n"
        f"DTEND:{end}\r\n"
        f"SUMMARY:{title}\r\n"
        f"DESCRIPTION:{desc}\r\n"
        f"LOCATION:{location}\r\n"
        f"{url_line}"
        f"UID:{uid}\r\n"
        "STATUS:CONFIRMED\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


def _calendar_block_html(meeting: dict) -> str:
    gcal = _gcal_url(meeting)
    return f"""
    <div style="margin:16px 0;padding:12px 14px;background:#f0f7ee;
                border-radius:6px;border:1px solid #c7dfc2;">
      <p style="margin:0 0 8px;font-size:12px;color:#374151;font-weight:600;">
        📅 Add this meeting to your calendar:
      </p>
      <a href="{gcal}" target="_blank"
         style="display:inline-block;background:#3D6B34;color:#fff;
                padding:7px 16px;border-radius:6px;font-size:13px;
                text-decoration:none;font-weight:600;">
        + Add to Google Calendar
      </a>
      <span style="margin-left:10px;font-size:11px;color:#6b7280;">
        (or open the attached .ics file for Outlook / Apple Calendar)
      </span>
    </div>"""


def _project_badge(name: str) -> str:
    if not name:
        return ""
    return (f"<span style='background:#3D6B34;color:#fff;border-radius:4px;"
            f"padding:2px 8px;font-size:11px;margin-left:8px;'>{name}</span>")


def _agenda_section_html(section: dict) -> str:
    items = section.get("items", [])
    rows_html = ""
    for item in items:
        dur   = f" ({item['duration_minutes']} min)" if item.get("duration_minutes") else ""
        pres  = f" — {item['presenter']}" if item.get("presenter") else ""
        notes_raw = item.get("notes_template") or ""
        notes = (f"<div style='margin:4px 0 0;color:#555;font-size:13px;'>"
                 f"{notes_raw}</div>") if notes_raw else ""
        rows_html += f"""
        <tr>
          <td style='padding:8px 12px;border-bottom:1px solid #eee;'>
            <strong style='font-size:14px;'>{item.get('title','')}</strong>
            <span style='color:#777;font-size:12px;'>{dur}{pres}</span>
            {notes}
          </td>
        </tr>"""
    badge = _project_badge(section.get("project_name", ""))
    return f"""
    <div style='margin-bottom:18px;'>
      <h3 style='margin:0 0 6px;font-size:15px;color:#3D6B34;
                 border-bottom:2px solid #3D6B34;padding-bottom:4px;'>
        {section.get('title','Section')}{badge}
      </h3>
      <table style='width:100%;border-collapse:collapse;'>{rows_html}</table>
    </div>"""


def _minutes_section_html(section: dict) -> str:
    items = section.get("items", [])
    rows_html = ""
    for item in items:
        m         = item.get("minutes") or {}
        notes     = m.get("notes", "") or ""
        decisions = m.get("decisions", "") or ""
        actions   = m.get("action_items", "") or ""
        assigned  = m.get("assigned_to", "") or ""
        due       = m.get("due_date", "") or ""

        detail_rows = ""
        if notes:
            detail_rows += (f"<tr><td style='padding:3px 12px;color:#333;font-size:13px;'>"
                            f"<strong>Discussion:</strong> {notes}</td></tr>")
        if decisions:
            detail_rows += (f"<tr><td style='padding:3px 12px;color:#333;font-size:13px;'>"
                            f"<strong>Decisions:</strong> {decisions}</td></tr>")
        if actions:
            suffix = f" — {assigned}" if assigned else ""
            suffix += f" (Due: {due})" if due else ""
            detail_rows += (f"<tr><td style='padding:3px 12px;color:#333;font-size:13px;'>"
                            f"<strong>Action Items:</strong> {actions}{suffix}</td></tr>")

        body = (f"<table style='width:100%;margin-top:6px;'>{detail_rows}</table>"
                if detail_rows
                else "<p style='color:#999;font-size:12px;margin:4px 0 0;'>No notes recorded.</p>")

        rows_html += f"""
        <tr>
          <td style='padding:8px 12px;border-bottom:1px solid #eee;'>
            <strong style='font-size:14px;color:#2d5a27;'>{item.get('title','')}</strong>
            {body}
          </td>
        </tr>"""

    badge = _project_badge(section.get("project_name", ""))
    return f"""
    <div style='margin-bottom:18px;'>
      <h3 style='margin:0 0 6px;font-size:15px;color:#3D6B34;
                 border-bottom:2px solid #3D6B34;padding-bottom:4px;'>
        {section.get('title','Section')}{badge}
      </h3>
      <table style='width:100%;border-collapse:collapse;'>{rows_html}</table>
    </div>"""


def _accounting_html(snap: dict) -> str:
    if not snap:
        return ""
    label    = snap.get("label", "Financial Summary")
    period   = snap.get("period", "")
    revenue  = float(snap.get("revenue") or 0)
    expenses = float(snap.get("expenses") or 0)
    net      = revenue - expenses
    out_inv  = float(snap.get("outstanding_invoices") or 0)
    out_bill = float(snap.get("outstanding_bills") or 0)
    color    = "#166534" if net >= 0 else "#b91c1c"

    inv_row  = (f"<tr><td style='padding:3px 0;color:#555;font-size:12px;'>Outstanding Invoices</td>"
                f"<td style='padding:3px 0;text-align:right;color:#92400e;font-size:12px;'>${out_inv:,.2f}</td></tr>"
                if out_inv else "")
    bill_row = (f"<tr><td style='padding:3px 0;color:#555;font-size:12px;'>Outstanding Bills</td>"
                f"<td style='padding:3px 0;text-align:right;color:#92400e;font-size:12px;'>${out_bill:,.2f}</td></tr>"
                if out_bill else "")

    return f"""
    <div style='margin-top:20px;background:#f9fafb;border:1px solid #d1d5db;border-radius:6px;padding:14px;'>
      <h3 style='margin:0 0 10px;font-size:14px;color:#374151;'>
        {label}{f" — {period}" if period else ""}
      </h3>
      <table style='width:100%;border-collapse:collapse;'>
        <tr>
          <td style='padding:4px 0;color:#555;font-size:13px;'>Revenue</td>
          <td style='padding:4px 0;text-align:right;font-weight:bold;color:#166534;font-size:13px;'>${revenue:,.2f}</td>
        </tr>
        <tr>
          <td style='padding:4px 0;color:#555;font-size:13px;'>Expenses</td>
          <td style='padding:4px 0;text-align:right;font-weight:bold;color:#991b1b;font-size:13px;'>${expenses:,.2f}</td>
        </tr>
        <tr style='border-top:1px solid #d1d5db;'>
          <td style='padding:6px 0;font-weight:bold;font-size:13px;'>Net Income</td>
          <td style='padding:6px 0;text-align:right;font-weight:bold;color:{color};font-size:14px;'>${net:,.2f}</td>
        </tr>
        {inv_row}{bill_row}
      </table>
    </div>"""


def _base_template(header_title: str, business_name: str, content_html: str) -> str:
    biz_line = (f"<p style='margin:4px 0 0;color:#c8e6b3;font-size:13px;'>{business_name}</p>"
                if business_name else "")
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"/></head>
<body style="font-family:sans-serif;max-width:640px;margin:0 auto;padding:20px;color:#111;">
  <div style="background:#3D6B34;padding:18px 24px;border-radius:8px 8px 0 0;">
    <h1 style="margin:0;color:#fff;font-size:20px;">{header_title}</h1>
    {biz_line}
  </div>
  <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;
              border-radius:0 0 8px 8px;padding:24px;">
    {content_html}
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0;"/>
    <p style="color:#9ca3af;font-size:11px;margin:0;">
      Sent via <a href="{OFN_BASE_URL}" style="color:#3D6B34;">Oatmeal Farm Network</a>
    </p>
  </div>
</body>
</html>"""


# ── Public senders ────────────────────────────────────────────────────────────

def send_meeting_agenda(
    to_email: str,
    attendee_name: str,
    meeting: dict,
    sections: list,
    accounting_snapshot: dict = None,
) -> bool:
    date_str   = _fmt_date(meeting.get("meeting_date"))
    time_str   = _fmt_time(meeting.get("meeting_date"))
    location   = meeting.get("location") or "To be confirmed"
    biz_name   = meeting.get("business_name", "")
    desc       = meeting.get("description", "")
    meet_link  = (meeting.get("google_meet_link") or "").strip()

    total_min = sum(
        (item.get("duration_minutes") or 0)
        for s in sections for item in s.get("items", [])
    )
    dur_note = (f"<p style='color:#6b7280;font-size:12px;margin:0 0 16px;'>"
                f"Estimated total: {total_min} minutes</p>") if total_min > 0 else ""

    sections_html = "".join(_agenda_section_html(s) for s in sections)
    acct_html     = _accounting_html(accounting_snapshot) if accounting_snapshot else ""
    cal_html      = _calendar_block_html(meeting)

    time_clause = f" at <strong>{time_str}</strong>" if time_str else ""
    desc_block  = (f"<p style='margin:8px 0 16px;color:#374151;font-size:13px;'>{desc}</p>"
                   if desc else "")
    meet_line   = (f"<p style='margin:0 0 4px;color:#4b5563;font-size:14px;'>"
                   f"📹 <a href='{meet_link}' style='color:#3D6B34;font-weight:bold;'>Join Google Meet</a></p>"
                   if meet_link else "")

    body = f"""
    <h2 style="margin:0 0 6px;font-size:18px;color:#1f2937;">{meeting.get('title','Meeting')}</h2>
    <p style="margin:0 0 4px;color:#4b5563;font-size:14px;">
      📅 <strong>{date_str}</strong>{time_clause}
    </p>
    <p style="margin:0 0 4px;color:#4b5563;font-size:14px;">📍 <strong>{location}</strong></p>
    {meet_line}
    {cal_html}
    {desc_block}
    <p style="margin:0 0 16px;color:#6b7280;font-size:13px;">
      Dear {attendee_name},<br/>You are invited to attend the above meeting.
      Please find the agenda below.
    </p>
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0;"/>
    {dur_note}
    {sections_html}
    {acct_html}"""

    html = _base_template("Meeting Agenda", biz_name, body)
    ics  = _ics_content(meeting)
    return _send(to_email, f"Agenda: {meeting.get('title','Meeting')} — {date_str}", html, ics)


def send_meeting_minutes(
    to_email: str,
    attendee_name: str,
    meeting: dict,
    sections: list,
    accounting_snapshot: dict = None,
) -> bool:
    date_str  = _fmt_date(meeting.get("meeting_date"))
    biz_name  = meeting.get("business_name", "")
    meet_link = (meeting.get("google_meet_link") or "").strip()

    sections_html = "".join(_minutes_section_html(s) for s in sections)
    acct_html     = _accounting_html(accounting_snapshot) if accounting_snapshot else ""
    meet_line     = (f"<p style='margin:0 0 8px;color:#4b5563;font-size:14px;'>"
                     f"📹 <a href='{meet_link}' style='color:#3D6B34;font-weight:bold;'>Google Meet recording/link</a></p>"
                     if meet_link else "")

    body = f"""
    <h2 style="margin:0 0 6px;font-size:18px;color:#1f2937;">{meeting.get('title','Meeting')}</h2>
    <p style="margin:0 0 4px;color:#4b5563;font-size:14px;">📅 <strong>{date_str}</strong></p>
    {meet_line}
    <p style="margin:0 0 16px;color:#6b7280;font-size:13px;">
      Dear {attendee_name},<br/>Please find the meeting minutes below.
    </p>
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0;"/>
    {sections_html}
    {acct_html}"""

    html = _base_template("Meeting Minutes", biz_name, body)
    return _send(to_email, f"Minutes: {meeting.get('title','Meeting')} — {date_str}", html)
