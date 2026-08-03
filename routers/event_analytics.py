"""
Event analytics + attendee CSV export.

Endpoints:
  GET  /api/events/{event_id}/attendees.csv       — unified CSV of all registrants
  GET  /api/events/{event_id}/analytics           — per-event rollup (counts, revenue, checked-in)
  GET  /api/businesses/{business_id}/events/analytics  — organizer-wide rollup across all events

Table shapes vary across registration types, so we read what we can with per-source
error tolerance and merge the results.
"""
import csv
import io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

router = APIRouter()


# (kind, table, id_col, name_col, email_col, phone_col, status_col, paid_col, fee_col, has_checkedin, party_col)
ATTENDEE_SOURCES = [
    ('Simple',     'OFNEventSimpleRegistrations',     'RegID',   'GuestName',   'GuestEmail',   'GuestPhone',    'Status', 'PaidStatus', 'TotalFee',   True,  None),
    ('Conference', 'OFNEventConferenceRegistrations', 'RegID',   'GuestName',   'GuestEmail',   'GuestPhone',    'Status', 'PaidStatus', 'TotalFee',   True,  None),
    ('Competition', 'OFNEventCompetitionEntries',     'EntryID', 'EntrantName', 'EntrantEmail', 'EntrantPhone',  None,     None,         None,         True,  None),
    ('Dining',     'OFNEventDiningRegistrations',     'RegID',   'GuestName',   'GuestEmail',   'GuestPhone',    'Status', 'PaidStatus', 'TotalFee',   False, 'PartySize'),
    ('Tour',       'OFNEventTourRegistrations',       'RegID',   'GuestName',   'GuestEmail',   'GuestPhone',    'Status', 'PaidStatus', 'TotalFee',   True,  'PartySize'),
]


def _fetch_attendees(db: Session, event_id: int):
    """Return list of dicts across all registration tables; swallow per-table errors."""
    rows = []
    for src in ATTENDEE_SOURCES:
        (kind, table, id_col, name_col, email_col, phone_col,
         status_col, paid_col, fee_col, has_chk, party_col) = src
        status_sel = f"{status_col} AS Status" if status_col else (
            "CASE WHEN Disqualified = 1 THEN 'Disqualified' ELSE 'Entered' END AS Status"
            if kind == 'Competition' else "CAST(NULL AS NVARCHAR(50)) AS Status"
        )
        paid_sel = f"{paid_col} AS PaidStatus" if paid_col else "CAST(NULL AS NVARCHAR(50)) AS PaidStatus"
        fee_sel = f"{fee_col} AS TotalFee" if fee_col else "CAST(0 AS DECIMAL(10,2)) AS TotalFee"
        chk_sel = "CheckedIn" if has_chk else "CAST(0 AS BIT) AS CheckedIn"
        party_sel = f"{party_col} AS PartySize" if party_col else "CAST(1 AS INT) AS PartySize"
        sql = f"""
            SELECT
              '{kind}' AS Kind,
              r.{id_col}    AS RegID,
              r.{name_col}  AS AttendeeName,
              r.{email_col} AS AttendeeEmail,
              r.{phone_col} AS AttendeePhone,
              {status_sel}, {paid_sel}, {fee_sel}, {chk_sel}, {party_sel},
              r.CreatedDate AS CreatedAt
            FROM {table} r
            WHERE r.EventID = :e
        """
        try:
            for m in db.execute(text(sql), {"e": event_id}).mappings().all():
                d = dict(m)
                if d.get("CreatedAt") and hasattr(d["CreatedAt"], "isoformat"):
                    d["CreatedAt"] = d["CreatedAt"].isoformat()
                if d.get("TotalFee") is not None:
                    d["TotalFee"] = float(d["TotalFee"])
                rows.append(d)
        except Exception:
            db.rollback()
    return rows


@router.get("/api/events/{event_id}/attendees")
def list_attendees_json(event_id: int, db: Session = Depends(get_db)):
    """JSON variant of the attendee roster — used by the admin dashboard."""
    rows = _fetch_attendees(db, event_id)
    rows.sort(key=lambda r: r.get("CreatedAt") or "", reverse=True)
    return rows


@router.get("/api/events/{event_id}/attendees.csv")
def export_attendees_csv(event_id: int, db: Session = Depends(get_db)):
    ev = db.execute(text("SELECT EventName FROM OFNEvents WHERE EventID=:e"),
                    {"e": event_id}).fetchone()
    if not ev:
        raise HTTPException(404, "Event not found")
    rows = _fetch_attendees(db, event_id)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Kind", "RegID", "Name", "Email", "Phone", "PartySize",
        "Status", "PaidStatus", "TotalFee", "CheckedIn", "CreatedAt",
    ])
    for r in rows:
        writer.writerow([
            r.get("Kind") or "",
            r.get("RegID") or "",
            r.get("AttendeeName") or "",
            r.get("AttendeeEmail") or "",
            r.get("AttendeePhone") or "",
            r.get("PartySize") or 1,
            r.get("Status") or "",
            r.get("PaidStatus") or "",
            f"{r.get('TotalFee', 0):.2f}" if r.get("TotalFee") is not None else "",
            "1" if r.get("CheckedIn") else "0",
            r.get("CreatedAt") or "",
        ])
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in (ev[0] or f"event-{event_id}"))
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}-attendees.csv"'},
    )


def _per_event_rollup(db: Session, event_id: int) -> dict:
    rows = _fetch_attendees(db, event_id)
    total_regs = len(rows)
    total_attendees = sum(int(r.get("PartySize") or 1) for r in rows)
    checked_in = sum(1 for r in rows if r.get("CheckedIn"))
    revenue = sum(float(r.get("TotalFee") or 0) for r in rows)
    paid_revenue = sum(
        float(r.get("TotalFee") or 0) for r in rows
        if (r.get("PaidStatus") or "").lower() == "paid"
    )
    by_kind: dict = {}
    for r in rows:
        k = r.get("Kind") or "Unknown"
        b = by_kind.setdefault(k, {"count": 0, "revenue": 0.0, "checkedIn": 0, "attendees": 0})
        b["count"] += 1
        b["attendees"] += int(r.get("PartySize") or 1)
        b["revenue"] += float(r.get("TotalFee") or 0)
        if r.get("CheckedIn"):
            b["checkedIn"] += 1
    return {
        "totalRegistrations": total_regs,
        "totalAttendees": total_attendees,
        "checkedIn": checked_in,
        "checkInRate": (checked_in / total_regs) if total_regs else 0,
        "revenue": round(revenue, 2),
        "paidRevenue": round(paid_revenue, 2),
        "byKind": by_kind,
    }


@router.get("/api/events/{event_id}/analytics")
def event_analytics(event_id: int, db: Session = Depends(get_db)):
    ev = db.execute(text("""
        SELECT EventID, EventName, EventType, EventStartDate, EventEndDate, BusinessID
          FROM OFNEvents WHERE EventID=:e
    """), {"e": event_id}).mappings().first()
    if not ev:
        raise HTTPException(404, "Event not found")
    roll = _per_event_rollup(db, event_id)
    out = dict(ev)
    if out.get("EventStartDate") and hasattr(out["EventStartDate"], "isoformat"):
        out["EventStartDate"] = out["EventStartDate"].isoformat()
    if out.get("EventEndDate") and hasattr(out["EventEndDate"], "isoformat"):
        out["EventEndDate"] = out["EventEndDate"].isoformat()
    out.update(roll)
    return out


@router.get("/api/businesses/{business_id}/events/analytics")
def organizer_analytics(business_id: int, db: Session = Depends(get_db)):
    events = db.execute(text("""
        SELECT EventID, EventName, EventType, EventStartDate
          FROM OFNEvents WHERE BusinessID=:b
         ORDER BY EventStartDate DESC
    """), {"b": business_id}).mappings().all()

    per_event = []
    totals = {
        "totalRegistrations": 0, "totalAttendees": 0,
        "checkedIn": 0, "revenue": 0.0, "paidRevenue": 0.0,
    }
    for e in events:
        roll = _per_event_rollup(db, int(e["EventID"]))
        row = dict(e)
        if row.get("EventStartDate") and hasattr(row["EventStartDate"], "isoformat"):
            row["EventStartDate"] = row["EventStartDate"].isoformat()
        row.update(roll)
        per_event.append(row)
        for k in totals:
            totals[k] += roll.get(k, 0) or 0
    totals["revenue"] = round(totals["revenue"], 2)
    totals["paidRevenue"] = round(totals["paidRevenue"], 2)
    totals["eventCount"] = len(events)
    return {"totals": totals, "events": per_event}
