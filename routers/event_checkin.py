"""
Unified event check-in for day-of ops.

Works across Simple/Conference/Competition/Dining/Tour registration tables.
Scanner UI calls:
  GET  /api/events/{event_id}/checkin/search?q=<text>
  PUT  /api/events/checkin/{kind}/{reg_id}   body: {"CheckedIn": true|false}
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

router = APIRouter()

# Each tuple: (kind, table, id_col, name_col, email_col, extra_cols_select, has_checkedin, join_people)
# When join_people=True, email_col is ignored and the query LEFT JOINs People (by PeopleID)
# to search by person name/email; name_col still points at the entry's own title/name column.
SEARCH_SOURCES = [
    ('Simple',     'OFNEventSimpleRegistrations',      'RegID',   'GuestName',          'GuestEmail',          'PartySize, Status, PaidStatus', True, False),
    ('Conference', 'OFNEventConferenceRegistrations',  'RegID',   'GuestName',          'GuestEmail',          'BadgeCode, Status, PaidStatus', True, False),
    ('Competition','OFNEventCompetitionEntries',       'EntryID', 'EntrantName',        'EntrantEmail',        'EntryNumber, EntryTitle', True, False),
    ('Dining',     'OFNEventDiningRegistrations',      'RegID',   'GuestName',          'GuestEmail',          'PartySize, Status, PaidStatus', False, False),
    ('Tour',       'OFNEventTourRegistrations',        'RegID',   'GuestName',          'GuestEmail',          'SlotID, PartySize, Status, PaidStatus', True, False),
    ('Fiber Arts', 'OFNEventFiberArtsEntries',         'EntryID', 'EntryTitle',         None,                  'FiberType, Placement, PaidStatus', False, True),
    ('Fleece',     'OFNEventFleeceEntries',            'EntryID', 'FleeceName',         None,                  'Breed, Color, Placement, PaidStatus', False, True),
    ('Spin-Off',   'OFNEventSpinOffEntries',           'EntryID', 'EntryTitle',         None,                  'SpinnerName, FiberType, Placement, PaidStatus', False, True),
]


def _col_exists(db: Session, table: str, col: str) -> bool:
    try:
        r = db.execute(text("""
            SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME=:t AND COLUMN_NAME=:c
        """), {"t": table, "c": col}).fetchone()
        return bool(r)
    except Exception:
        return False


@router.get("/api/events/{event_id}/checkin/search")
def search(event_id: int, q: str = '', db: Session = Depends(get_db)):
    term = f"%{(q or '').strip()}%"
    results = []
    for kind, table, id_col, name_col, email_col, extra, has_chk, join_people in SEARCH_SOURCES:
        try:
            if not _col_exists(db, table, name_col):
                continue
            chk_select = "CheckedIn" if has_chk else "CAST(0 AS BIT) AS CheckedIn"
            if join_people:
                person_name = "ISNULL(p.PeopleFirstName,'') + ' ' + ISNULL(p.PeopleLastName,'')"
                sql = f"""
                    SELECT TOP 20
                      t.{id_col} AS RegID, t.{name_col} AS Name, p.Peopleemail AS Email,
                      {extra}, {chk_select}
                    FROM {table} t
                    LEFT JOIN People p ON p.PeopleID = t.PeopleID
                    WHERE t.EventID = :e AND (
                        t.{name_col} LIKE :q OR p.Peopleemail LIKE :q
                        OR {person_name} LIKE :q
                        OR CAST(t.{id_col} AS NVARCHAR(50)) = :exact
                    )
                    ORDER BY t.{id_col} DESC
                """
            else:
                sql = f"""
                    SELECT TOP 20
                      {id_col} AS RegID, {name_col} AS Name, {email_col} AS Email,
                      {extra}, {chk_select}
                    FROM {table}
                    WHERE EventID = :e AND (
                        {name_col} LIKE :q OR {email_col} LIKE :q OR CAST({id_col} AS NVARCHAR(50)) = :exact
                    )
                    ORDER BY {id_col} DESC
                """
            rows = db.execute(text(sql), {"e": event_id, "q": term, "exact": (q or '').strip()}).mappings().all()
            for r in rows:
                d = dict(r)
                d['Kind'] = kind
                results.append(d)
        except Exception:
            db.rollback()
            continue
    return results


CHECKIN_MAP = {
    'Simple': ("OFNEventSimpleRegistrations", "RegID"),
    'Conference': ("OFNEventConferenceRegistrations", "RegID"),
    'Competition': ("OFNEventCompetitionEntries", "EntryID"),
    'Tour': ("OFNEventTourRegistrations", "RegID"),
    'Dining': ("OFNEventDiningRegistrations", "RegID"),
    'Fiber Arts': ("OFNEventFiberArtsEntries", "EntryID"),
    'Fleece': ("OFNEventFleeceEntries", "EntryID"),
    'Spin-Off': ("OFNEventSpinOffEntries", "EntryID"),
}


@router.put("/api/events/checkin/{kind}/{reg_id}")
def set_checkin(kind: str, reg_id: int, body: dict, db: Session = Depends(get_db)):
    if kind not in CHECKIN_MAP:
        raise HTTPException(400, "Unknown kind")
    table, id_col = CHECKIN_MAP[kind]
    if not _col_exists(db, table, "CheckedIn"):
        db.execute(text(f"ALTER TABLE {table} ADD CheckedIn BIT DEFAULT 0"))
        db.commit()
    if not _col_exists(db, table, "CheckedInAt"):
        db.execute(text(f"ALTER TABLE {table} ADD CheckedInAt DATETIME"))
        db.commit()
    checked = 1 if body.get("CheckedIn", True) else 0
    db.execute(text(f"""
        UPDATE {table} SET
            CheckedIn = :c,
            CheckedInAt = CASE WHEN :c = 1 THEN GETDATE() ELSE NULL END
        WHERE {id_col} = :r
    """), {"c": checked, "r": reg_id})
    db.commit()
    return {"ok": True, "CheckedIn": bool(checked)}
