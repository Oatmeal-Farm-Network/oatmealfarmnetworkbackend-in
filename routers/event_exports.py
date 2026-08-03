"""
CSV exports for event data — schedules, registrations, entries, leaderboards.

One endpoint per domain. Every response is streamed as text/csv so it opens
natively in Excel and Google Sheets (import → upload CSV). No openpyxl
dependency needed; users who want .xlsx can "Save As" from Excel.

The /api/events/{id}/exports/manifest endpoint returns which exports are
available for a given event, based on its enabled features, so the frontend
can render a feature-aware download list.
"""
import csv, io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

router = APIRouter()


def _csv_response(filename: str, headers: list, rows):
    """Build a StreamingResponse of CSV from (header list, iterable of row dicts/lists)."""
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    w.writerow(headers)
    for r in rows:
        if isinstance(r, dict):
            w.writerow([r.get(h, '') if r.get(h) is not None else '' for h in headers])
        else:
            w.writerow(['' if v is None else v for v in r])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _event_slug(db: Session, event_id: int) -> str:
    r = db.execute(text("SELECT EventName FROM OFNEvents WHERE EventID = :e"),
                   {"e": event_id}).mappings().first()
    if not r or not r.get("EventName"):
        return f"event-{event_id}"
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in r["EventName"]).strip("-").lower()
    return slug or f"event-{event_id}"


def _table_exists(db: Session, name: str) -> bool:
    r = db.execute(text("""
        SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = :n
    """), {"n": name}).first()
    return bool(r)


# ─── Manifest: which exports apply to this event ─────────────────────

EXPORT_DEFINITIONS = [
    ("registrations-carts",    "Registrations & Carts",         "cart",              None),
    ("meal-tickets",           "Meal Tickets",                  "meal_module",       "OFNEventMealTickets"),
    ("halter-entries",         "Halter Entries",                "halter_module",     "OFNEventHalterRegistrations"),
    ("halter-schedule",        "Halter Class Schedule",         "halter_module",     "OFNEventHalterClasses"),
    ("fleece-entries",         "Fleece Show Entries",           "fleece_module",     "OFNEventFleeceEntries"),
    ("spinoff-entries",        "Spin-Off Entries",              "spinoff_module",    "OFNEventSpinOffEntries"),
    ("fiber-arts-entries",     "Fiber Arts Entries",            "fiber_arts_module", "OFNEventFiberArtsEntries"),
    ("competition-entries",    "Competition Entries",           "competition",       "OFNEventCompetitionEntries"),
    ("competition-leaderboard","Competition Leaderboard",       "competition",       "OFNEventCompetitionScores"),
    ("conference-attendees",   "Conference Attendees",          "conference",        "OFNEventConferenceRegistrations"),
    ("conference-schedule",    "Conference Session Schedule",   "conference",        "OFNEventConferenceSessions"),
    ("dining-registrations",   "Dining Registrations",          "dining",            "OFNEventDiningRegistrations"),
    ("tour-registrations",     "Farm Tour Registrations",       "farm_tour",         "OFNEventTourRegistrations"),
    ("vendor-applications",    "Vendor Fair Applications",      "vendor_fair_module","OFNEventVendorApplications"),
    ("simple-registrations",   "Simple Event Registrations",    "simple",            "OFNEventSimpleRegistrations"),
    ("mailing-list",           "Mailing List Subscribers",      None,                "OFNEventMailingList"),
    ("all-emails",             "All Attendee Emails (combined)",None,                None),
]


@router.get("/api/events/{event_id}/exports/manifest")
def exports_manifest(event_id: int, db: Session = Depends(get_db)):
    """Return which CSV exports are available for this event.

    An export is available when:
      - its feature_key is enabled on the event (or it's feature-agnostic), AND
      - its backing table exists (or none is required).
    """
    ev = db.execute(text("SELECT EventID, EventType, EventName FROM OFNEvents WHERE EventID = :e"),
                    {"e": event_id}).mappings().first()
    if not ev:
        raise HTTPException(404, "Event not found")

    enabled_keys = set()
    try:
        feats = db.execute(text("""
            SELECT f.FeatureKey
              FROM OFNEventTypeFeatures m
              JOIN OFNEventFeatures f ON f.FeatureID = m.FeatureID
              JOIN EventTypesLookup tl ON tl.EventTypeID = m.EventTypeID
             WHERE tl.EventType = :t AND f.Deleted = 0
        """), {"t": ev["EventType"]}).mappings().all()
        enabled_keys = {r["FeatureKey"] for r in feats if r.get("FeatureKey")}
    except Exception:
        enabled_keys = set()

    out = []
    for key, label, feature_key, required_table in EXPORT_DEFINITIONS:
        if feature_key and feature_key not in enabled_keys:
            continue
        if required_table and not _table_exists(db, required_table):
            continue
        out.append({
            "key": key,
            "label": label,
            "url": f"/api/events/{event_id}/exports/{key}.csv",
            "feature": feature_key,
        })
    return {"EventID": event_id, "EventName": ev["EventName"], "exports": out}


# ─── Individual CSV endpoints ────────────────────────────────────────

@router.get("/api/events/{event_id}/exports/registrations-carts.csv")
def export_carts(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT c.CartID, c.AttendeeFirstName, c.AttendeeLastName, c.AttendeeEmail, c.AttendeePhone,
               c.Status, c.Subtotal, c.PlatformFeeAmount, c.Total, c.AmountPaid, c.AmountRefunded,
               c.StripePaymentIntentID, c.PaidDate, c.RefundedDate, c.CreatedDate,
               (SELECT COUNT(*) FROM OFNEventCartLineItems l WHERE l.CartID = c.CartID) AS LineCount
          FROM OFNEventRegistrationCart c
         WHERE c.EventID = :e
         ORDER BY c.CreatedDate DESC
    """), {"e": event_id}).mappings().all()
    headers = ["CartID","AttendeeFirstName","AttendeeLastName","AttendeeEmail","AttendeePhone",
               "Status","Subtotal","PlatformFeeAmount","Total","AmountPaid","AmountRefunded",
               "StripePaymentIntentID","PaidDate","RefundedDate","CreatedDate","LineCount"]
    slug = _event_slug(db, event_id)
    return _csv_response(f"{slug}-registrations.csv", headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/meal-tickets.csv")
def export_meal_tickets(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT t.TicketID, s.SessionName, s.SessionDate, s.SessionTime,
               t.AttendeeName, t.DietaryNotes, t.Quantity, t.UnitPrice, t.LineAmount,
               t.PaidStatus, t.CartID, t.CreatedDate
          FROM OFNEventMealTickets t
          LEFT JOIN OFNEventMealSessions s ON s.SessionID = t.SessionID
         WHERE t.EventID = :e
         ORDER BY s.SessionDate, s.SessionTime, t.TicketID
    """), {"e": event_id}).mappings().all()
    headers = ["TicketID","SessionName","SessionDate","SessionTime",
               "AttendeeName","DietaryNotes","Quantity","UnitPrice","LineAmount",
               "PaidStatus","CartID","CreatedDate"]
    return _csv_response(f"{_event_slug(db,event_id)}-meal-tickets.csv", headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/halter-entries.csv")
def export_halter(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT r.RegID, r.AnimalID, a.AnimalName, a.AnimalEarTag, a.AnimalSex,
               p.firstname AS OwnerFirst, p.lastname AS OwnerLast, p.email AS OwnerEmail,
               b.BusinessName, r.IsShorn, r.IsCheckedIn, r.PaidStatus, r.Fee,
               (SELECT STUFF((SELECT ', ' + c.ClassName
                                FROM OFNEventHalterClassEntries e
                                JOIN OFNEventHalterClasses c ON c.ClassID = e.ClassID
                               WHERE e.RegID = r.RegID
                                 FOR XML PATH('')),1,2,'')) AS ClassesEntered,
               r.CreatedDate
          FROM OFNEventHalterRegistrations r
          LEFT JOIN Animals a    ON a.AnimalID = r.AnimalID
          LEFT JOIN People   p   ON p.people_id = r.PeopleID
          LEFT JOIN Business b ON b.BusinessID = r.BusinessID
         WHERE r.EventID = :e
         ORDER BY b.BusinessName, a.AnimalName
    """), {"e": event_id}).mappings().all()
    headers = ["RegID","AnimalID","AnimalName","AnimalEarTag","AnimalSex",
               "OwnerFirst","OwnerLast","OwnerEmail","BusinessName",
               "IsShorn","IsCheckedIn","PaidStatus","Fee","ClassesEntered","CreatedDate"]
    return _csv_response(f"{_event_slug(db,event_id)}-halter-entries.csv", headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/halter-schedule.csv")
def export_halter_schedule(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT c.ClassID, c.ClassCode, c.ShornCode, c.ClassName, c.Breed, c.Gender, c.AgeGroup,
               c.ClassType, c.DisplayOrder,
               (SELECT COUNT(*) FROM OFNEventHalterClassEntries e WHERE e.ClassID = c.ClassID) AS EntryCount
          FROM OFNEventHalterClasses c
         WHERE c.EventID = :e AND c.IsActive = 1
         ORDER BY c.DisplayOrder, c.ClassCode, c.ClassName
    """), {"e": event_id}).mappings().all()
    headers = ["ClassID","ClassCode","ShornCode","ClassName","Breed","Gender","AgeGroup",
               "ClassType","DisplayOrder","EntryCount"]
    return _csv_response(f"{_event_slug(db,event_id)}-halter-schedule.csv", headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/fleece-entries.csv")
def export_fleece(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT f.EntryID, f.FleeceName, f.Breed, f.Color, f.Micron, f.StapleLength,
               d.DivisionName, p.firstname AS OwnerFirst, p.lastname AS OwnerLast,
               p.email AS OwnerEmail, b.BusinessName,
               f.EntryFee, f.PaidStatus, f.Placement, f.Score, f.JudgeNotes, f.CreatedDate
          FROM OFNEventFleeceEntries f
          LEFT JOIN OFNEventFleeceDivisions d ON d.DivisionID = f.DivisionID
          LEFT JOIN People   p ON p.people_id = f.PeopleID
          LEFT JOIN Business b ON b.BusinessID = f.BusinessID
         WHERE f.EventID = :e
         ORDER BY d.DivisionName, f.FleeceName
    """), {"e": event_id}).mappings().all()
    headers = ["EntryID","FleeceName","Breed","Color","Micron","StapleLength",
               "DivisionName","OwnerFirst","OwnerLast","OwnerEmail","BusinessName",
               "EntryFee","PaidStatus","Placement","Score","JudgeNotes","CreatedDate"]
    return _csv_response(f"{_event_slug(db,event_id)}-fleece-entries.csv", headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/spinoff-entries.csv")
def export_spinoff(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT s.EntryID, s.EntryTitle, s.SpinnerName, s.FiberType, s.FiberSource,
               p.firstname AS OwnerFirst, p.lastname AS OwnerLast, p.email AS OwnerEmail,
               b.BusinessName, s.EntryFee, s.PaidStatus, s.Placement, s.Score,
               s.JudgeNotes, s.CreatedDate
          FROM OFNEventSpinOffEntries s
          LEFT JOIN People p     ON p.people_id = s.PeopleID
          LEFT JOIN Business b ON b.BusinessID = s.BusinessID
         WHERE s.EventID = :e
         ORDER BY s.EntryTitle
    """), {"e": event_id}).mappings().all()
    headers = ["EntryID","EntryTitle","SpinnerName","FiberType","FiberSource",
               "OwnerFirst","OwnerLast","OwnerEmail","BusinessName",
               "EntryFee","PaidStatus","Placement","Score","JudgeNotes","CreatedDate"]
    return _csv_response(f"{_event_slug(db,event_id)}-spinoff-entries.csv", headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/fiber-arts-entries.csv")
def export_fiber_arts(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT fa.EntryID, fa.EntryTitle, fa.FiberType, c.CategoryName,
               p.firstname AS OwnerFirst, p.lastname AS OwnerLast, p.email AS OwnerEmail,
               b.BusinessName, fa.EntryFee, fa.PaidStatus, fa.Placement,
               fa.JudgeNotes, fa.CreatedDate
          FROM OFNEventFiberArtsEntries fa
          LEFT JOIN OFNEventFiberArtsCategories c ON c.CategoryID = fa.CategoryID
          LEFT JOIN People p     ON p.people_id = fa.PeopleID
          LEFT JOIN Business b ON b.BusinessID = fa.BusinessID
         WHERE fa.EventID = :e
         ORDER BY c.CategoryName, fa.EntryTitle
    """), {"e": event_id}).mappings().all()
    headers = ["EntryID","EntryTitle","FiberType","CategoryName",
               "OwnerFirst","OwnerLast","OwnerEmail","BusinessName",
               "EntryFee","PaidStatus","Placement","JudgeNotes","CreatedDate"]
    return _csv_response(f"{_event_slug(db,event_id)}-fiber-arts-entries.csv", headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/competition-entries.csv")
def export_competition_entries(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT e.EntryID, e.EntryNumber, cat.CategoryName, e.EntrantName, e.EntrantEmail,
               e.EntrantPhone, e.EntryTitle, e.CheckedIn, e.Disqualified, e.DQReason,
               e.EntryFeePaid, e.CreatedDate
          FROM OFNEventCompetitionEntries e
          LEFT JOIN OFNEventCompetitionCategories cat ON cat.CategoryID = e.CategoryID
         WHERE e.EventID = :e
         ORDER BY cat.CategoryName, e.EntryNumber
    """), {"e": event_id}).mappings().all()
    headers = ["EntryID","EntryNumber","CategoryName","EntrantName","EntrantEmail",
               "EntrantPhone","EntryTitle","CheckedIn","Disqualified","DQReason",
               "EntryFeePaid","CreatedDate"]
    return _csv_response(f"{_event_slug(db,event_id)}-competition-entries.csv", headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/competition-leaderboard.csv")
def export_competition_leaderboard(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT e.EntryID, e.EntryNumber, cat.CategoryName, e.EntrantName, e.EntryTitle,
               ISNULL(SUM(s.Points), 0) AS TotalPoints,
               COUNT(DISTINCT s.JudgeID) AS JudgeCount
          FROM OFNEventCompetitionEntries e
          LEFT JOIN OFNEventCompetitionCategories cat ON cat.CategoryID = e.CategoryID
          LEFT JOIN OFNEventCompetitionScores s ON s.EntryID = e.EntryID
         WHERE e.EventID = :e AND e.Disqualified = 0
         GROUP BY e.EntryID, e.EntryNumber, cat.CategoryName, e.EntrantName, e.EntryTitle
         ORDER BY cat.CategoryName, TotalPoints DESC
    """), {"e": event_id}).mappings().all()
    headers = ["EntryID","EntryNumber","CategoryName","EntrantName","EntryTitle",
               "TotalPoints","JudgeCount"]
    return _csv_response(f"{_event_slug(db,event_id)}-competition-leaderboard.csv",
                         headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/conference-attendees.csv")
def export_conference_attendees(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT r.RegID, r.GuestName, r.GuestEmail, r.GuestPhone, r.Company, r.BadgeTitle,
               r.TicketTier, r.TotalFee, r.PaidStatus, r.Status, r.CheckedIn,
               r.DietaryRestrictions, r.CreatedDate
          FROM OFNEventConferenceRegistrations r
         WHERE r.EventID = :e
         ORDER BY r.GuestName
    """), {"e": event_id}).mappings().all()
    headers = ["RegID","GuestName","GuestEmail","GuestPhone","Company","BadgeTitle",
               "TicketTier","TotalFee","PaidStatus","Status","CheckedIn",
               "DietaryRestrictions","CreatedDate"]
    return _csv_response(f"{_event_slug(db,event_id)}-conference-attendees.csv",
                         headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/conference-schedule.csv")
def export_conference_schedule(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT s.SessionID, s.Title, s.SessionType, s.SessionStart, s.DurationMin,
               t.TrackName, rm.RoomName, s.Capacity,
               (SELECT STUFF((SELECT ', ' + sp.SpeakerName
                                FROM OFNEventConferenceSessionSpeakers lnk
                                JOIN OFNEventConferenceSpeakers sp ON sp.SpeakerID = lnk.SpeakerID
                               WHERE lnk.SessionID = s.SessionID
                                 FOR XML PATH('')),1,2,'')) AS Speakers
          FROM OFNEventConferenceSessions s
          LEFT JOIN OFNEventConferenceTracks t  ON t.TrackID = s.TrackID
          LEFT JOIN OFNEventConferenceRooms  rm ON rm.RoomID = s.RoomID
         WHERE s.EventID = :e
         ORDER BY s.SessionStart
    """), {"e": event_id}).mappings().all()
    headers = ["SessionID","Title","SessionType","SessionStart","DurationMin",
               "TrackName","RoomName","Capacity","Speakers"]
    return _csv_response(f"{_event_slug(db,event_id)}-conference-schedule.csv",
                         headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/dining-registrations.csv")
def export_dining(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT r.RegID, r.GuestName, r.GuestEmail, r.GuestPhone, r.PartySize, r.ChildCount,
               r.DietaryRestrictions, r.SpecialRequests, r.TableID, r.SeatNumbers,
               r.TotalFee, r.PaidStatus, r.Status, r.CreatedDate
          FROM OFNEventDiningRegistrations r
         WHERE r.EventID = :e
         ORDER BY r.GuestName
    """), {"e": event_id}).mappings().all()
    headers = ["RegID","GuestName","GuestEmail","GuestPhone","PartySize","ChildCount",
               "DietaryRestrictions","SpecialRequests","TableID","SeatNumbers",
               "TotalFee","PaidStatus","Status","CreatedDate"]
    return _csv_response(f"{_event_slug(db,event_id)}-dining.csv", headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/tour-registrations.csv")
def export_tours(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT r.RegID, r.SlotID, r.GuestName, r.GuestEmail, r.GuestPhone,
               r.PartySize, r.ChildCount, r.WaiverSignedBy, r.WaiverSignedDate,
               r.TicketFee, r.AddOnsTotal, r.TotalFee, r.PaidStatus, r.Status,
               r.CheckedIn, r.CreatedDate
          FROM OFNEventTourRegistrations r
         WHERE r.EventID = :e
         ORDER BY r.SlotID, r.GuestName
    """), {"e": event_id}).mappings().all()
    headers = ["RegID","SlotID","GuestName","GuestEmail","GuestPhone",
               "PartySize","ChildCount","WaiverSignedBy","WaiverSignedDate",
               "TicketFee","AddOnsTotal","TotalFee","PaidStatus","Status",
               "CheckedIn","CreatedDate"]
    return _csv_response(f"{_event_slug(db,event_id)}-tours.csv", headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/vendor-applications.csv")
def export_vendors(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT a.AppID, a.BusinessName, a.ContactName, a.ContactEmail, a.ContactPhone,
               a.BoothSize, a.ProductCategories, a.WebsiteURL, a.NeedsElectricity, a.NeedsTable,
               a.RequestedLocation, a.Status, a.BoothNumber, a.Fee, a.PaidStatus, a.CreatedDate
          FROM OFNEventVendorApplications a
         WHERE a.EventID = :e
         ORDER BY a.BusinessName
    """), {"e": event_id}).mappings().all()
    headers = ["AppID","BusinessName","ContactName","ContactEmail","ContactPhone",
               "BoothSize","ProductCategories","WebsiteURL","NeedsElectricity","NeedsTable",
               "RequestedLocation","Status","BoothNumber","Fee","PaidStatus","CreatedDate"]
    return _csv_response(f"{_event_slug(db,event_id)}-vendors.csv", headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/simple-registrations.csv")
def export_simple(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT r.RegID, r.GuestName, r.GuestEmail, r.GuestPhone, r.PartySize, r.ChildCount,
               r.NameTagTitle, r.DietaryRestrictions, r.SpecialRequests, r.TicketType,
               r.TotalFee, r.PaidStatus, r.Status, r.CheckedIn, r.CreatedDate
          FROM OFNEventSimpleRegistrations r
         WHERE r.EventID = :e
         ORDER BY r.GuestName
    """), {"e": event_id}).mappings().all()
    headers = ["RegID","GuestName","GuestEmail","GuestPhone","PartySize","ChildCount",
               "NameTagTitle","DietaryRestrictions","SpecialRequests","TicketType",
               "TotalFee","PaidStatus","Status","CheckedIn","CreatedDate"]
    return _csv_response(f"{_event_slug(db,event_id)}-simple-registrations.csv",
                         headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/mailing-list.csv")
def export_mailing_list(event_id: int, db: Session = Depends(get_db)):
    if not _table_exists(db, "OFNEventMailingList"):
        return _csv_response(f"{_event_slug(db,event_id)}-mailing-list.csv",
                             ["Email","Name","Source","OptedOutDate","AddedDate"], [])
    rows = db.execute(text("""
        SELECT Email, Name, Source, OptedOutDate, AddedDate
          FROM OFNEventMailingList
         WHERE EventID = :e
         ORDER BY AddedDate DESC
    """), {"e": event_id}).mappings().all()
    headers = ["Email","Name","Source","OptedOutDate","AddedDate"]
    return _csv_response(f"{_event_slug(db,event_id)}-mailing-list.csv",
                         headers, [dict(r) for r in rows])


@router.get("/api/events/{event_id}/exports/all-emails.csv")
def export_all_emails(event_id: int, db: Session = Depends(get_db)):
    """One-stop email export combining every registrant table + mailing list.
    Deduplicated by lowercase email."""
    sources = [
        ("OFNEventSimpleRegistrations",     "GuestName",    "GuestEmail",   "Simple"),
        ("OFNEventConferenceRegistrations", "GuestName",    "GuestEmail",   "Conference"),
        ("OFNEventCompetitionEntries",      "EntrantName",  "EntrantEmail", "Competition"),
        ("OFNEventDiningRegistrations",     "GuestName",    "GuestEmail",   "Dining"),
        ("OFNEventTourRegistrations",       "GuestName",    "GuestEmail",   "Tour"),
        ("OFNEventVendorApplications",      "ContactName",  "ContactEmail", "Vendor"),
        ("OFNEventRegistrationCart",        "AttendeeFirstName+' '+AttendeeLastName", "AttendeeEmail", "Cart"),
    ]
    seen = {}
    for table, name_expr, email_col, source in sources:
        if not _table_exists(db, table):
            continue
        try:
            rows = db.execute(text(f"""
                SELECT DISTINCT {name_expr} AS N, {email_col} AS E
                  FROM {table}
                 WHERE EventID = :e AND {email_col} IS NOT NULL AND {email_col} <> ''
            """), {"e": event_id}).mappings().all()
            for r in rows:
                em = (r["E"] or "").strip().lower()
                if em and em not in seen:
                    seen[em] = {"Email": em, "Name": r["N"] or "", "Source": source}
        except Exception:
            db.rollback()
            continue
    if _table_exists(db, "OFNEventMailingList"):
        try:
            rows = db.execute(text("""
                SELECT Email AS E, Name AS N FROM OFNEventMailingList
                 WHERE EventID = :e AND (OptedOutDate IS NULL)
                   AND Email IS NOT NULL AND Email <> ''
            """), {"e": event_id}).mappings().all()
            for r in rows:
                em = (r["E"] or "").strip().lower()
                if em and em not in seen:
                    seen[em] = {"Email": em, "Name": r["N"] or "", "Source": "MailingList"}
        except Exception:
            db.rollback()

    headers = ["Email","Name","Source"]
    return _csv_response(f"{_event_slug(db,event_id)}-all-emails.csv",
                         headers, list(seen.values()))
