"""
Aggregated registrations feed for a person — all event types in one shape.

Endpoint: GET /api/people/{people_id}/event-registrations
Returns unified rows across:
  - OFNEventSimpleRegistrations      (Seminar/Workshop/Webinar/Networking/etc.)
  - OFNEventConferenceRegistrations  (Conference)
  - OFNEventCompetitionEntries       (Competition/Judging)
  - OFNEventDiningRegistrations      (Dining events)
  - OFNEventTourRegistrations        (Farm Tour slots)
  - OFNEventRegistrations            (generic legacy)

Shape:
{ RegID, EventID, EventName, EventType, EventStartDate, BusinessName,
  RegistrationKind, Status, PaidStatus, TotalFee, CheckedIn, CreatedAt }
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

router = APIRouter()


ENTRY_KINDS = {'Fiber Arts Entry', 'Fleece Entry', 'Spin-Off Entry'}

SOURCES = [
    # (kind, table, id_col, created_col, status_col, paid_col, has_checkedin)
    ('Simple',     'OFNEventSimpleRegistrations',     'RegID',   'CreatedDate', 'Status', 'PaidStatus', True),
    ('Conference', 'OFNEventConferenceRegistrations', 'RegID',   'CreatedDate', 'Status', 'PaidStatus', True),
    ('Competition Entry', 'OFNEventCompetitionEntries', 'EntryID', 'CreatedDate', None,    None,         True),
    ('Dining',     'OFNEventDiningRegistrations',     'RegID',   'CreatedDate', 'Status', 'PaidStatus', False),
    ('Tour',       'OFNEventTourRegistrations',       'RegID',   'CreatedDate', 'Status', 'PaidStatus', True),
    ('Event',      'OFNEventRegistrations',           'RegID',   'CreatedDate', 'Status', 'PaidStatus', False),
    ('Fiber Arts Entry', 'OFNEventFiberArtsEntries',  'EntryID', 'CreatedDate', None,     'PaidStatus', False),
    ('Fleece Entry',     'OFNEventFleeceEntries',     'EntryID', 'CreatedDate', None,     'PaidStatus', False),
    ('Spin-Off Entry',   'OFNEventSpinOffEntries',    'EntryID', 'CreatedDate', None,     'PaidStatus', False),
]


def _safe_fetch_one(db: Session, kind, table, id_col, created_col, status_col, paid_col, has_chk, pid):
    if status_col:
        status_sel = f"{status_col} AS Status"
    elif kind == 'Competition Entry':
        status_sel = "CASE WHEN Disqualified = 1 THEN 'Disqualified' ELSE 'Entered' END AS Status"
    elif kind in ENTRY_KINDS:
        status_sel = "CASE WHEN Placement IS NOT NULL THEN 'Placed: ' + Placement ELSE 'Entered' END AS Status"
    else:
        status_sel = "CAST(NULL AS NVARCHAR(50)) AS Status"
    paid_sel = f"{paid_col} AS PaidStatus" if paid_col else "CAST(NULL AS NVARCHAR(50)) AS PaidStatus"
    if kind == 'Competition Entry':
        fee_sel = "CAST(0 AS DECIMAL(10,2)) AS TotalFee"
    elif kind in ENTRY_KINDS:
        fee_sel = "EntryFee AS TotalFee"
    else:
        fee_sel = "TotalFee"
    chk_sel = "CheckedIn" if has_chk else "CAST(0 AS BIT) AS CheckedIn"
    sql = f"""
        SELECT
          r.{id_col} AS RegID, r.EventID, e.EventName, e.EventType, e.EventStartDate,
          b.BusinessName, '{kind}' AS RegistrationKind,
          {status_sel}, {paid_sel}, {fee_sel}, {chk_sel},
          r.{created_col} AS CreatedAt
        FROM {table} r
        JOIN OFNEvents e ON e.EventID = r.EventID
        LEFT JOIN Business b ON b.BusinessID = e.BusinessID
        WHERE r.PeopleID = :pid
    """
    try:
        return db.execute(text(sql), {"pid": pid}).mappings().all()
    except Exception:
        db.rollback()
        return []


@router.get("/api/people/{people_id}/event-registrations")
def list_my_registrations(people_id: int, db: Session = Depends(get_db)):
    result = []
    for src in SOURCES:
        for r in _safe_fetch_one(db, *src, pid=people_id):
            d = dict(r)
            for k in ('EventStartDate', 'CreatedAt'):
                v = d.get(k)
                if v is not None and hasattr(v, 'isoformat'):
                    d[k] = v.isoformat()
            if d.get('TotalFee') is not None:
                d['TotalFee'] = float(d['TotalFee'])
            result.append(d)
    result.sort(key=lambda x: x.get('EventStartDate') or '', reverse=True)
    return result
