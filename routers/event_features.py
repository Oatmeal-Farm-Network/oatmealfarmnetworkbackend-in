"""
Event features catalog + per-event-type enablement.

Defines which capabilities each EventType turns on (QR check-in, mass email,
certificates, per-type admin modules, public register pages, etc.).

Tables
  OFNEventFeatures      — catalog of available features (admin + public paths)
  OFNEventTypeFeatures  — join: which features each EventType has enabled

Endpoints
  GET    /api/events/features                       — catalog
  POST   /api/events/features                       — create feature
  PUT    /api/events/features/{id}                  — update feature
  DELETE /api/events/features/{id}                  — soft-delete
  GET    /api/events/types/{type_id}/features       — features for one type
  PUT    /api/events/types/{type_id}/features       — set features for one type
  GET    /api/events/types-features                 — matrix (all types × feature keys)
  GET    /api/events/{event_id}/features            — features resolved for a specific event
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal

router = APIRouter()


# ── Seed catalog ──────────────────────────────────────────────────────────────
# (FeatureKey, Name, Description, Icon, AdminPath, PublicPath, IsCoreModule, SortOrder)
# Paths accept {eventId} placeholder.
SEED_FEATURES = [
    # Cross-cutting tools (available to any type when enabled)
    ('qr_checkin',         'QR Code Check-in',       'Scan attendee QR codes at the door to mark check-in.',
        '✅', '/events/{eventId}/checkin', None, 0, 10),
    ('mass_email',         'Mass Email Broadcast',   'Send announcements to all registered attendees.',
        '📣', '/events/{eventId}/broadcast', None, 0, 20),
    ('analytics',          'Analytics Dashboard',    'Registration, revenue, and check-in rollups.',
        '📊', '/events/{eventId}/analytics', None, 0, 30),
    ('attendees_csv',      'Attendees CSV Export',   'Download a unified roster across all registration types.',
        '⬇️', '/api/events/{eventId}/attendees.csv', None, 0, 40),
    ('calendar_ics',       'Calendar Export (.ics)', 'Public "Add to calendar" link for all attendees.',
        '📅', None, '/api/events/{eventId}/calendar.ics', 0, 50),
    ('certificates',       'Printable Certificates', 'Issue attendance/participation certificates.',
        '🏅', '/events/{eventId}/certificate', '/events/{eventId}/certificate', 0, 60),
    ('clone_event',        'Clone Event',            'Duplicate this event (and its config) to seed a new one.',
        '🗐', '/events/{eventId}/clone', None, 0, 70),
    ('waitlist',           'Waitlist',               'When capacity hits, queue new registrants; promote later.',
        '🕑', None, None, 0, 80),
    ('cancel_refund',      'Cancel + Refund',        'Attendees can self-cancel paid registrations.',
        '↩', None, '/my-registrations', 0, 90),
    ('speaker_portal',     'Speaker Portal',         'Invite speakers with a private access-code page.',
        '🎤', '/events/{eventId}/admin/conference?tab=speakers', '/speaker/{accessCode}', 0, 100),

    # Core modules (IsCoreModule=1 — one per event type)
    ('simple_module',      'Basic Registration',     'Simple ticketed registration with optional tiers.',
        '📋', '/events/{eventId}/admin/simple',      '/events/{eventId}/register', 1, 200),
    ('conference_module',  'Conference Agenda',      'Tracks, rooms, speakers, sessions, tiered badges.',
        '🎤', '/events/{eventId}/admin/conference',  '/events/{eventId}/conference', 1, 210),
    ('competition_module', 'Competition + Judging',  'Categories with rubrics, judge assignments, scoring.',
        '🏆', '/events/{eventId}/admin/competition', '/events/{eventId}/compete', 1, 220),
    ('dining_module',      'Dining + Seating',       'Menu, tables, seating chart, per-seat registration.',
        '🍽️', '/events/{eventId}/admin/dining',      '/events/{eventId}/dining', 1, 230),
    ('tour_module',        'Farm Tour Slots',        'Time-slot capacity, waiver, add-ons.',
        '🚜', '/events/{eventId}/admin/tour',        '/events/{eventId}/tour', 1, 240),
    ('halter_module',      'Halter Show',            'Classes, pens, per-class animal entries, judging.',
        '🦙', '/events/{eventId}/admin/halter',      '/events/{eventId}/register/halter', 1, 250),
    ('fiber_arts_module',  'Fiber Arts Show',        'Cottage-industry entries with categories + judging.',
        '🧶', '/events/{eventId}/admin/fiber-arts',  '/events/{eventId}/register/fiber-arts', 1, 260),
    ('fleece_module',      'Fleece Show',            'Per-fleece entries with breed/color/micron, fee window, judging.',
        '🐑', '/events/{eventId}/admin/fleece',      '/events/{eventId}/register/fleece', 1, 262),
    ('spinoff_module',     'Spin-Off',               'Per-entry spinning competition with fee window and judging.',
        '🧵', '/events/{eventId}/admin/spinoff',     '/events/{eventId}/register/spinoff', 1, 264),
    ('auction_module',     'Auction',                'Lots, starting bids, reserve prices, bid history.',
        '💰', '/events/{eventId}/admin/auction',     '/events/{eventId}/auction', 1, 270),
    ('vendor_fair_module', 'Vendor Fair',            'Booth applications with fees and approval workflow.',
        '🛍️', '/events/{eventId}/admin/vendor-fair', '/events/{eventId}/vendor-apply', 1, 280),

    # Per-type extras
    ('leaderboard',        'Public Leaderboard',     'Show competition standings to the public.',
        '🥇', None, '/events/{eventId}/leaderboard', 0, 300),
    ('session_agenda',     'Public Agenda',          'Printable/shareable conference agenda.',
        '🗓', None, '/events/{eventId}/agenda', 0, 310),
]

# Default enablement per EventType.
# Keys match EventTypesLookup.EventType strings.
DEFAULT_TYPE_FEATURES = {
    'Free Event':                          ['simple_module',      'qr_checkin', 'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'certificates', 'clone_event'],
    'Basic Event':                         ['simple_module',      'qr_checkin', 'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'certificates', 'clone_event', 'waitlist', 'cancel_refund'],
    'Seminar':                             ['simple_module',      'qr_checkin', 'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'certificates', 'clone_event', 'waitlist', 'cancel_refund'],
    'Workshop/Clinic':                     ['simple_module',      'qr_checkin', 'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'certificates', 'clone_event', 'waitlist', 'cancel_refund'],
    'Webinar/Online Class':                ['simple_module',      'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'certificates', 'clone_event', 'cancel_refund'],
    'Networking Event':                    ['simple_module',      'qr_checkin', 'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'clone_event', 'waitlist', 'cancel_refund'],
    'Conference':                          ['conference_module',  'qr_checkin', 'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'certificates', 'clone_event', 'waitlist', 'cancel_refund', 'speaker_portal', 'session_agenda'],
    'Dining Event':                        ['dining_module',      'qr_checkin', 'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'clone_event', 'cancel_refund'],
    'Farm Tour/Open House':                ['tour_module',        'qr_checkin', 'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'clone_event', 'cancel_refund'],
    'Competition/Judging':                 ['competition_module', 'qr_checkin', 'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'certificates', 'clone_event', 'leaderboard'],
    'Halter Show':                         ['halter_module',      'qr_checkin', 'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'certificates', 'clone_event'],
    'Basic Animal or Fleece Show':         ['fleece_module',      'qr_checkin', 'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'certificates', 'clone_event'],
    'Spin-Off':                            ['spinoff_module',     'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'certificates', 'clone_event'],
    'Alpaca Cottage Industry Fleece Show': ['fiber_arts_module',  'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'certificates', 'clone_event', 'leaderboard'],
    'Auction':                             ['auction_module',     'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'clone_event'],
    'Market/Vendor Fair':                  ['vendor_fair_module', 'mass_email', 'analytics', 'attendees_csv', 'calendar_ics', 'clone_event'],
}


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventFeatures')
        CREATE TABLE OFNEventFeatures (
            FeatureID          INT IDENTITY(1,1) PRIMARY KEY,
            FeatureKey         NVARCHAR(50)  NOT NULL UNIQUE,
            FeatureName        NVARCHAR(200) NOT NULL,
            FeatureDescription NVARCHAR(1000),
            Icon               NVARCHAR(20),
            AdminPath          NVARCHAR(300),
            PublicPath         NVARCHAR(300),
            IsCoreModule       BIT DEFAULT 0,
            SortOrder          INT DEFAULT 100,
            Deleted            BIT DEFAULT 0,
            CreatedDate        DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventTypeFeatures')
        CREATE TABLE OFNEventTypeFeatures (
            EventTypeID INT NOT NULL,
            FeatureID   INT NOT NULL,
            CONSTRAINT PK_OFNEventTypeFeatures PRIMARY KEY (EventTypeID, FeatureID)
        )
    """))
    db.commit()


def _upsert_seed_features(db: Session):
    for row in SEED_FEATURES:
        (key, name, desc, icon, admin, public, core, sort) = row
        db.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM OFNEventFeatures WHERE FeatureKey = :k)
                INSERT INTO OFNEventFeatures
                  (FeatureKey, FeatureName, FeatureDescription, Icon, AdminPath, PublicPath, IsCoreModule, SortOrder)
                VALUES (:k, :n, :d, :i, :a, :p, :c, :s)
        """), {"k": key, "n": name, "d": desc, "i": icon,
                "a": admin, "p": public, "c": 1 if core else 0, "s": sort})
    # Backfill NULL paths for seed rows that originally shipped with None.
    # Only fills NULLs — respects any admin customization.
    for row in SEED_FEATURES:
        (key, _n, _d, _i, admin, public, _c, _s) = row
        if admin is not None:
            db.execute(text(
                "UPDATE OFNEventFeatures SET AdminPath = :a "
                "WHERE FeatureKey = :k AND AdminPath IS NULL"
            ), {"k": key, "a": admin})
        if public is not None:
            db.execute(text(
                "UPDATE OFNEventFeatures SET PublicPath = :p "
                "WHERE FeatureKey = :k AND PublicPath IS NULL"
            ), {"k": key, "p": public})
    db.commit()


def _seed_default_type_mappings(db: Session):
    """For each EventType in EventTypesLookup, if it has no mappings yet, seed defaults."""
    types = db.execute(text("SELECT EventTypeID, EventType FROM EventTypesLookup")).fetchall()
    for t in types:
        type_id = t[0]
        type_name = t[1]
        existing = db.execute(text(
            "SELECT COUNT(1) FROM OFNEventTypeFeatures WHERE EventTypeID = :t"
        ), {"t": type_id}).scalar()
        if existing and int(existing) > 0:
            continue
        defaults = DEFAULT_TYPE_FEATURES.get(type_name, [])
        for key in defaults:
            db.execute(text("""
                INSERT INTO OFNEventTypeFeatures (EventTypeID, FeatureID)
                SELECT :t, FeatureID FROM OFNEventFeatures
                WHERE FeatureKey = :k AND NOT EXISTS (
                    SELECT 1 FROM OFNEventTypeFeatures m
                    JOIN OFNEventFeatures f ON f.FeatureID = m.FeatureID
                    WHERE m.EventTypeID = :t AND f.FeatureKey = :k
                )
            """), {"t": type_id, "k": key})
    db.commit()


def _migrate_core_module_mappings(db: Session):
    """One-time migration: types that used to share halter_module now own their own
    core module. For existing deployments where 'Spin-Off' and 'Basic Animal or
    Fleece Show' are currently mapped to halter_module, swap to the dedicated
    spinoff_module / fleece_module and drop the halter_module row.
    Idempotent: safe to run on every boot — only acts when the old mapping is
    still present AND the new one isn't.
    """
    migrations = [
        ('Spin-Off', 'halter_module', 'spinoff_module'),
        ('Basic Animal or Fleece Show', 'halter_module', 'fleece_module'),
    ]
    for type_name, old_key, new_key in migrations:
        type_row = db.execute(text(
            "SELECT EventTypeID FROM EventTypesLookup WHERE EventType = :t"
        ), {"t": type_name}).fetchone()
        if not type_row:
            continue
        type_id = int(type_row[0])
        old_id = db.execute(text(
            "SELECT FeatureID FROM OFNEventFeatures WHERE FeatureKey = :k AND Deleted = 0"
        ), {"k": old_key}).fetchone()
        new_id = db.execute(text(
            "SELECT FeatureID FROM OFNEventFeatures WHERE FeatureKey = :k AND Deleted = 0"
        ), {"k": new_key}).fetchone()
        if not (old_id and new_id):
            continue
        has_old = db.execute(text(
            "SELECT 1 FROM OFNEventTypeFeatures WHERE EventTypeID = :t AND FeatureID = :f"
        ), {"t": type_id, "f": int(old_id[0])}).fetchone()
        has_new = db.execute(text(
            "SELECT 1 FROM OFNEventTypeFeatures WHERE EventTypeID = :t AND FeatureID = :f"
        ), {"t": type_id, "f": int(new_id[0])}).fetchone()
        if has_old and not has_new:
            db.execute(text(
                "INSERT INTO OFNEventTypeFeatures (EventTypeID, FeatureID) VALUES (:t, :f)"
            ), {"t": type_id, "f": int(new_id[0])})
            db.execute(text(
                "DELETE FROM OFNEventTypeFeatures WHERE EventTypeID = :t AND FeatureID = :f"
            ), {"t": type_id, "f": int(old_id[0])})
    db.commit()


with SessionLocal() as _db:
    try:
        ensure_tables(_db)
        _upsert_seed_features(_db)
        _seed_default_type_mappings(_db)
        _migrate_core_module_mappings(_db)
    except Exception as e:
        print(f"Event features table setup error: {e}")


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/api/events/features")
def list_features(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT FeatureID, FeatureKey, FeatureName, FeatureDescription, Icon,
               AdminPath, PublicPath, IsCoreModule, SortOrder
          FROM OFNEventFeatures
         WHERE Deleted = 0
         ORDER BY SortOrder, FeatureName
    """)).mappings().all()
    return [dict(r) for r in rows]


@router.post("/api/events/features")
def create_feature(body: dict, db: Session = Depends(get_db)):
    required = ('FeatureKey', 'FeatureName')
    for k in required:
        if not body.get(k):
            raise HTTPException(400, f"{k} is required")
    exists = db.execute(text(
        "SELECT 1 FROM OFNEventFeatures WHERE FeatureKey = :k"
    ), {"k": body['FeatureKey']}).fetchone()
    if exists:
        raise HTTPException(409, "FeatureKey already exists")
    r = db.execute(text("""
        INSERT INTO OFNEventFeatures
          (FeatureKey, FeatureName, FeatureDescription, Icon, AdminPath, PublicPath, IsCoreModule, SortOrder)
        VALUES (:k, :n, :d, :i, :a, :p, :c, :s);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "k": body['FeatureKey'], "n": body['FeatureName'],
        "d": body.get('FeatureDescription'), "i": body.get('Icon'),
        "a": body.get('AdminPath'), "p": body.get('PublicPath'),
        "c": 1 if body.get('IsCoreModule') else 0,
        "s": int(body.get('SortOrder') or 100),
    })
    new_id = int(r.fetchone()[0])
    db.commit()
    return {"FeatureID": new_id}


@router.put("/api/events/features/{feature_id}")
def update_feature(feature_id: int, body: dict, db: Session = Depends(get_db)):
    allowed = ['FeatureName', 'FeatureDescription', 'Icon', 'AdminPath', 'PublicPath', 'IsCoreModule', 'SortOrder']
    sets = []
    params = {"id": feature_id}
    for k in allowed:
        if k in body:
            sets.append(f"{k} = :{k}")
            params[k] = (1 if body[k] else 0) if k == 'IsCoreModule' else body[k]
    if not sets:
        return {"ok": True, "unchanged": True}
    db.execute(text(f"UPDATE OFNEventFeatures SET {', '.join(sets)} WHERE FeatureID = :id"), params)
    db.commit()
    return {"ok": True}


@router.delete("/api/events/features/{feature_id}")
def delete_feature(feature_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE OFNEventFeatures SET Deleted = 1 WHERE FeatureID = :id"),
               {"id": feature_id})
    db.execute(text("DELETE FROM OFNEventTypeFeatures WHERE FeatureID = :id"),
               {"id": feature_id})
    db.commit()
    return {"ok": True}


@router.get("/api/events/types/{type_id}/features")
def get_type_features(type_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT f.FeatureID, f.FeatureKey, f.FeatureName, f.FeatureDescription, f.Icon,
               f.AdminPath, f.PublicPath, f.IsCoreModule, f.SortOrder
          FROM OFNEventTypeFeatures m
          JOIN OFNEventFeatures f ON f.FeatureID = m.FeatureID
         WHERE m.EventTypeID = :t AND f.Deleted = 0
         ORDER BY f.SortOrder, f.FeatureName
    """), {"t": type_id}).mappings().all()
    return [dict(r) for r in rows]


@router.put("/api/events/types/{type_id}/features")
def set_type_features(type_id: int, body: dict, db: Session = Depends(get_db)):
    """Body: { features: ["qr_checkin", ...] } OR { feature_ids: [1,2,3] }"""
    feature_ids = []
    if 'feature_ids' in body and isinstance(body['feature_ids'], list):
        feature_ids = [int(x) for x in body['feature_ids']]
    elif 'features' in body and isinstance(body['features'], list):
        if body['features']:
            placeholders = ",".join([f":k{i}" for i in range(len(body['features']))])
            params = {f"k{i}": k for i, k in enumerate(body['features'])}
            rows = db.execute(text(
                f"SELECT FeatureID FROM OFNEventFeatures WHERE FeatureKey IN ({placeholders}) AND Deleted = 0"
            ), params).fetchall()
            feature_ids = [int(r[0]) for r in rows]
    db.execute(text("DELETE FROM OFNEventTypeFeatures WHERE EventTypeID = :t"), {"t": type_id})
    for fid in feature_ids:
        db.execute(text(
            "INSERT INTO OFNEventTypeFeatures (EventTypeID, FeatureID) VALUES (:t, :f)"
        ), {"t": type_id, "f": fid})
    db.commit()
    return {"ok": True, "count": len(feature_ids)}


@router.get("/api/events/types-features")
def types_features_matrix(db: Session = Depends(get_db)):
    """Returns [{EventTypeID, EventType, features: ["key1", ...]}]"""
    types = db.execute(text("""
        SELECT EventTypeID, EventType, FullPrice, DiscountPrice, DiscountEndDate
          FROM EventTypesLookup
         WHERE IsActive = 1
         ORDER BY EventType
    """)).mappings().all()
    maps = db.execute(text("""
        SELECT m.EventTypeID, f.FeatureKey
          FROM OFNEventTypeFeatures m
          JOIN OFNEventFeatures f ON f.FeatureID = m.FeatureID
         WHERE f.Deleted = 0
    """)).mappings().all()
    by_type = {}
    for m in maps:
        by_type.setdefault(int(m['EventTypeID']), []).append(m['FeatureKey'])
    out = []
    for t in types:
        d = dict(t)
        d['features'] = by_type.get(int(t['EventTypeID']), [])
        out.append(d)
    return out


@router.get("/api/events/{event_id}/features")
def features_for_event(event_id: int, db: Session = Depends(get_db)):
    """Resolve features enabled for a specific event (via its EventType)."""
    ev = db.execute(text("""
        SELECT EventID, EventType FROM OFNEvents WHERE EventID = :e
    """), {"e": event_id}).mappings().first()
    if not ev:
        raise HTTPException(404, "Event not found")
    if not ev.get('EventType'):
        return {"EventID": event_id, "EventType": None, "features": []}
    rows = db.execute(text("""
        SELECT f.FeatureID, f.FeatureKey, f.FeatureName, f.FeatureDescription, f.Icon,
               f.AdminPath, f.PublicPath, f.IsCoreModule, f.SortOrder
          FROM OFNEventTypeFeatures m
          JOIN OFNEventFeatures f ON f.FeatureID = m.FeatureID
          JOIN EventTypesLookup tl ON tl.EventTypeID = m.EventTypeID
         WHERE tl.EventType = :t AND f.Deleted = 0
         ORDER BY f.SortOrder, f.FeatureName
    """), {"t": ev['EventType']}).mappings().all()
    feats = [dict(r) for r in rows]
    for f in feats:
        if f.get('AdminPath'):
            f['AdminPath'] = f['AdminPath'].replace('{eventId}', str(event_id))
        if f.get('PublicPath'):
            f['PublicPath'] = f['PublicPath'].replace('{eventId}', str(event_id))
    return {"EventID": event_id, "EventType": ev['EventType'], "features": feats}
