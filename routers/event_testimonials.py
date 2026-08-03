"""
Post-event testimonial request flow.

After an event wraps, the host can blast a one-click request for a testimonial
to every paid attendee. We dedupe by email, skip anyone who has already been
sent a post-event testimonial request for this event, and generate a prefilled
link into the existing TestimonialsRequest UX (scoped to the host's BusinessID).
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES
                        WHERE TABLE_NAME = 'OFNEventTestimonialRequests')
        CREATE TABLE OFNEventTestimonialRequests (
            RowID        INT IDENTITY(1,1) PRIMARY KEY,
            EventID      INT NOT NULL,
            BusinessID   INT,
            Email        NVARCHAR(200) NOT NULL,
            Name         NVARCHAR(200),
            PeopleID     INT,
            SentDate     DATETIME NOT NULL DEFAULT GETDATE(),
            Status       NVARCHAR(20) DEFAULT 'sent'
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sys.indexes
                        WHERE name = 'IX_OFNEventTestimonialRequests_Event_Email')
        CREATE UNIQUE INDEX IX_OFNEventTestimonialRequests_Event_Email
               ON OFNEventTestimonialRequests(EventID, Email)
    """))
    db.commit()


with SessionLocal() as _db:
    try:
        ensure_tables(_db)
    except Exception as e:
        print(f"Event testimonial requests setup error: {e}")


def _event_header(db: Session, event_id: int) -> dict | None:
    row = db.execute(text("""
        SELECT EventID, EventName, EventStartDate, EventEndDate, BusinessID
        FROM OFNEvents WHERE EventID = :e
    """), {"e": event_id}).mappings().first()
    return dict(row) if row else None


def _paid_attendees(db: Session, event_id: int) -> list[dict]:
    """Unique (email, name) of every paid attendee for this event.

    Primary source: OFNEventAttendees (wizard flow). Fallback to the registration
    cart's payer if an event doesn't use the attendees table."""
    people: dict[str, dict] = {}

    try:
        rows = db.execute(text("""
            SELECT a.AttendeeName AS Name, a.AttendeeEmail AS Email, a.PeopleID
            FROM OFNEventAttendees a
            JOIN OFNEventRegistrationCart c ON c.CartID = a.CartID
            WHERE c.EventID = :e AND c.Status = 'paid'
              AND a.AttendeeEmail IS NOT NULL AND a.AttendeeEmail <> ''
        """), {"e": event_id}).fetchall()
        for r in rows:
            key = (r.Email or "").strip().lower()
            if key and key not in people:
                people[key] = {"Email": r.Email, "Name": r.Name, "PeopleID": r.PeopleID}
    except Exception:
        pass

    try:
        rows = db.execute(text("""
            SELECT AttendeeEmail AS Email,
                   AttendeeFirstName + ' ' + AttendeeLastName AS Name,
                   PeopleID
            FROM OFNEventRegistrationCart
            WHERE EventID = :e AND Status = 'paid'
              AND AttendeeEmail IS NOT NULL AND AttendeeEmail <> ''
        """), {"e": event_id}).fetchall()
        for r in rows:
            key = (r.Email or "").strip().lower()
            if key and key not in people:
                people[key] = {"Email": r.Email, "Name": r.Name, "PeopleID": r.PeopleID}
    except Exception:
        pass

    return list(people.values())


@router.post("/api/events/{event_id}/request-testimonials")
async def send_testimonial_requests(event_id: int, request: Request,
                                    db: Session = Depends(get_db)):
    """Fan out testimonial request emails to every paid attendee who hasn't
    already been sent one for this event. Idempotent — safe to re-run."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    dry_run = bool(body.get("dry_run"))

    ev = _event_header(db, event_id)
    if not ev:
        raise HTTPException(404, "Event not found")

    candidates = _paid_attendees(db, event_id)
    if not candidates:
        return {"sent": 0, "skipped": 0, "attendees": 0, "message": "No paid attendees."}

    already_sent_rows = db.execute(text("""
        SELECT Email FROM OFNEventTestimonialRequests WHERE EventID = :e
    """), {"e": event_id}).fetchall()
    already_sent = {(r[0] or "").strip().lower() for r in already_sent_rows}

    to_send = [c for c in candidates if (c["Email"] or "").strip().lower() not in already_sent]

    if dry_run:
        return {"sent": 0, "skipped": len(candidates) - len(to_send),
                "attendees": len(candidates), "would_send": len(to_send),
                "preview": to_send[:25]}

    try:
        from event_emails import send_event_testimonial_request
    except Exception:
        send_event_testimonial_request = None

    sent = 0
    for c in to_send:
        ok = True
        if send_event_testimonial_request:
            try:
                ok = bool(send_event_testimonial_request(
                    to_email=c["Email"],
                    attendee_name=c.get("Name") or "",
                    event=ev,
                ))
            except Exception as e:
                print(f"[event_testimonials] send failed for {c['Email']}: {e}")
                ok = False

        if ok:
            try:
                db.execute(text("""
                    INSERT INTO OFNEventTestimonialRequests
                        (EventID, BusinessID, Email, Name, PeopleID, SentDate, Status)
                    VALUES (:e, :b, :em, :n, :p, :d, 'sent')
                """), {
                    "e": event_id,
                    "b": ev.get("BusinessID"),
                    "em": c["Email"],
                    "n": c.get("Name"),
                    "p": c.get("PeopleID"),
                    "d": datetime.utcnow(),
                })
                sent += 1
            except Exception as e:
                print(f"[event_testimonials] insert failed for {c['Email']}: {e}")

    db.commit()

    return {
        "sent":      sent,
        "skipped":   len(candidates) - len(to_send),
        "attendees": len(candidates),
    }


@router.get("/api/events/{event_id}/testimonial-requests")
def list_sent(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT RowID, Email, Name, SentDate, Status
        FROM OFNEventTestimonialRequests WHERE EventID = :e
        ORDER BY SentDate DESC
    """), {"e": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]
