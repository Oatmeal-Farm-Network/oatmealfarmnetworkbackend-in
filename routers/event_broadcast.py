"""
Attendee broadcast — send one email to every registrant of an event.

Aggregates recipient emails across Simple / Conference / Competition / Dining / Tour
registration tables, de-duplicates, and sends via SendGrid in a single batch.
"""
import os, logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

try:
    import sendgrid
    from sendgrid.helpers.mail import Mail, Personalization, Email as SGEmail, To as SGTo
except Exception:  # pragma: no cover
    sendgrid = None

router = APIRouter()
logger = logging.getLogger(__name__)

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
FROM_EMAIL       = os.getenv("FROM_EMAIL", "john@oatmeal-ai.com")

RECIPIENT_SOURCES = [
    ("OFNEventSimpleRegistrations",     "GuestName",   "GuestEmail"),
    ("OFNEventConferenceRegistrations", "GuestName",   "GuestEmail"),
    ("OFNEventCompetitionEntries",      "EntrantName", "EntrantEmail"),
    ("OFNEventDiningRegistrations",     "GuestName",   "GuestEmail"),
    ("OFNEventTourRegistrations",       "GuestName",   "GuestEmail"),
]


def _collect_recipients(db: Session, event_id: int):
    rx = {}
    for table, name_col, email_col in RECIPIENT_SOURCES:
        try:
            rows = db.execute(text(f"""
                SELECT DISTINCT {name_col} AS N, {email_col} AS E
                  FROM {table}
                 WHERE EventID = :e AND {email_col} IS NOT NULL AND {email_col} <> ''
            """), {"e": event_id}).mappings().all()
            for r in rows:
                em = (r['E'] or '').strip().lower()
                if em and em not in rx:
                    rx[em] = r['N'] or ''
        except Exception:
            db.rollback()
            continue

    # Cart attendees (unified registration wizard)
    try:
        rows = db.execute(text("""
            SELECT DISTINCT (ISNULL(AttendeeFirstName,'') + ' ' + ISNULL(AttendeeLastName,'')) AS N,
                            AttendeeEmail AS E
              FROM OFNEventRegistrationCart
             WHERE EventID = :e AND AttendeeEmail IS NOT NULL AND AttendeeEmail <> ''
        """), {"e": event_id}).mappings().all()
        for r in rows:
            em = (r['E'] or '').strip().lower()
            if em and em not in rx:
                rx[em] = (r['N'] or '').strip()
    except Exception:
        db.rollback()

    # Opt-in mailing list (newsletter subscribers)
    try:
        rows = db.execute(text("""
            SELECT DISTINCT Name AS N, Email AS E
              FROM OFNEventMailingList
             WHERE EventID = :e AND OptedOutDate IS NULL
               AND Email IS NOT NULL AND Email <> ''
        """), {"e": event_id}).mappings().all()
        for r in rows:
            em = (r['E'] or '').strip().lower()
            if em and em not in rx:
                rx[em] = r['N'] or ''
    except Exception:
        db.rollback()

    return rx


@router.get("/api/events/{event_id}/broadcast/recipients")
def list_recipients(event_id: int, db: Session = Depends(get_db)):
    rx = _collect_recipients(db, event_id)
    return {"count": len(rx), "recipients": [{"Email": e, "Name": n} for e, n in rx.items()]}


@router.post("/api/events/{event_id}/broadcast/send")
def send_broadcast(event_id: int, body: dict, db: Session = Depends(get_db)):
    subject = (body.get('Subject') or '').strip()
    html    = (body.get('Body') or '').strip()
    if not subject or not html:
        raise HTTPException(400, "Subject and body required")
    if not SENDGRID_API_KEY or sendgrid is None:
        raise HTTPException(500, "SendGrid not configured")

    ev = db.execute(text("SELECT EventName FROM OFNEvents WHERE EventID=:e"),
                    {"e": event_id}).mappings().first()
    rx = _collect_recipients(db, event_id)
    if not rx:
        return {"sent": 0, "message": "No recipients"}

    sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
    sent, failed = 0, 0
    for em, nm in rx.items():
        try:
            mail = Mail(from_email=FROM_EMAIL, to_emails=em,
                        subject=f"[{ev['EventName'] if ev else 'Event'}] {subject}",
                        html_content=html.replace('{{name}}', nm or ''))
            sg.send(mail)
            sent += 1
        except Exception as ex:
            logger.error("broadcast to %s failed: %s", em, ex)
            failed += 1
    return {"sent": sent, "failed": failed}
