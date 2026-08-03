from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal
from auth import get_current_user
import models
import datetime

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


# ── One-time table creation ──────────────────────────────────────────────────

def _ensure_tables():
    ddl = [
        """IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name='MeetingProject')
           CREATE TABLE MeetingProject (
             ProjectID   INT IDENTITY(1,1) PRIMARY KEY,
             BusinessID  INT NOT NULL,
             Name        NVARCHAR(200) NOT NULL,
             Description NVARCHAR(MAX) NULL,
             Color       NVARCHAR(20)  DEFAULT '#3D6B34',
             Status      NVARCHAR(20)  DEFAULT 'active',
             CreatedAt   DATETIME2     DEFAULT SYSDATETIME()
           )""",
        """IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name='Meeting')
           CREATE TABLE Meeting (
             MeetingID       INT IDENTITY(1,1) PRIMARY KEY,
             BusinessID      INT           NOT NULL,
             ProjectID       INT           NULL,
             Title           NVARCHAR(300) NOT NULL,
             Description     NVARCHAR(MAX) NULL,
             MeetingDate     DATETIME2     NULL,
             Location        NVARCHAR(300) NULL,
             GoogleMeetLink  NVARCHAR(500) NULL,
             Status          NVARCHAR(30)  DEFAULT 'draft',
             AccountingScope NVARCHAR(20)  DEFAULT 'none',
             CreatedBy       INT           NULL,
             CreatedAt       DATETIME2     DEFAULT SYSDATETIME(),
             UpdatedAt       DATETIME2     DEFAULT SYSDATETIME()
           )""",
        """IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('Meeting') AND name='GoogleMeetLink')
           ALTER TABLE Meeting ADD GoogleMeetLink NVARCHAR(500) NULL""",
        """IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name='MeetingAttendee')
           CREATE TABLE MeetingAttendee (
             AttendeeID INT IDENTITY(1,1) PRIMARY KEY,
             MeetingID  INT           NOT NULL,
             Name       NVARCHAR(200) NOT NULL,
             Email      NVARCHAR(300) NOT NULL
           )""",
        """IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name='MeetingSection')
           CREATE TABLE MeetingSection (
             SectionID       INT IDENTITY(1,1) PRIMARY KEY,
             MeetingID       INT           NOT NULL,
             Title           NVARCHAR(300) NOT NULL,
             OrderIndex      INT           DEFAULT 0,
             ProjectID       INT           NULL,
             AccountingScope NVARCHAR(20)  DEFAULT 'none'
           )""",
        """IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name='MeetingAgendaItem')
           CREATE TABLE MeetingAgendaItem (
             ItemID          INT IDENTITY(1,1) PRIMARY KEY,
             MeetingID       INT           NOT NULL,
             SectionID       INT           NULL,
             Title           NVARCHAR(300) NOT NULL,
             NotesTemplate   NVARCHAR(MAX) NULL,
             DurationMinutes INT           NULL,
             Presenter       NVARCHAR(200) NULL,
             OrderIndex      INT           DEFAULT 0
           )""",
        """IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name='MeetingMinuteEntry')
           CREATE TABLE MeetingMinuteEntry (
             EntryID     INT IDENTITY(1,1) PRIMARY KEY,
             ItemID      INT           NOT NULL,
             Notes       NVARCHAR(MAX) NULL,
             Decisions   NVARCHAR(MAX) NULL,
             ActionItems NVARCHAR(MAX) NULL,
             AssignedTo  NVARCHAR(200) NULL,
             DueDate     NVARCHAR(50)  NULL
           )""",
    ]
    try:
        with SessionLocal() as db:
            for stmt in ddl:
                db.execute(text(stmt))
            db.commit()
    except Exception as e:
        print(f"[meetings] table-ensure error: {e}")


_ensure_tables()


# ── Auth helper ──────────────────────────────────────────────────────────────

def require_access(
    business_id: int = Query(...),
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    access = db.query(models.BusinessAccess).filter(
        models.BusinessAccess.BusinessID == business_id,
        models.BusinessAccess.PeopleID   == current_user.PeopleID,
        models.BusinessAccess.Active     == 1,
    ).first()
    if not access:
        raise HTTPException(status_code=403, detail="Business access required.")
    return {"business_id": business_id, "people_id": current_user.PeopleID,
            "access_level": access.AccessLevelID}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _meeting_detail(meeting_id: int, db: Session) -> dict:
    """Return a meeting with its sections, items, minutes, and attendees."""
    m = db.execute(
        text("""
            SELECT m.*, b.BusinessName,
                   p.Name AS ProjectName, p.Color AS ProjectColor
            FROM Meeting m
            JOIN Business b ON b.BusinessID = m.BusinessID
            LEFT JOIN MeetingProject p ON p.ProjectID = m.ProjectID
            WHERE m.MeetingID = :id
        """),
        {"id": meeting_id},
    ).mappings().first()
    if not m:
        return None

    sections = db.execute(
        text("""
            SELECT s.*, p.Name AS ProjectName
            FROM MeetingSection s
            LEFT JOIN MeetingProject p ON p.ProjectID = s.ProjectID
            WHERE s.MeetingID = :id ORDER BY s.OrderIndex
        """),
        {"id": meeting_id},
    ).mappings().all()

    items_all = db.execute(
        text("""
            SELECT i.*, e.Notes, e.Decisions, e.ActionItems, e.AssignedTo, e.DueDate,
                   e.EntryID
            FROM MeetingAgendaItem i
            LEFT JOIN MeetingMinuteEntry e ON e.ItemID = i.ItemID
            WHERE i.MeetingID = :id ORDER BY i.SectionID, i.OrderIndex
        """),
        {"id": meeting_id},
    ).mappings().all()

    attendees = db.execute(
        text("SELECT * FROM MeetingAttendee WHERE MeetingID = :id ORDER BY AttendeeID"),
        {"id": meeting_id},
    ).mappings().all()

    section_list = []
    for s in sections:
        section_items = [
            {
                "item_id":          i["ItemID"],
                "title":            i["Title"],
                "notes_template":   i["NotesTemplate"],
                "duration_minutes": i["DurationMinutes"],
                "presenter":        i["Presenter"],
                "order_index":      i["OrderIndex"],
                "minutes": {
                    "entry_id":     i["EntryID"],
                    "notes":        i["Notes"],
                    "decisions":    i["Decisions"],
                    "action_items": i["ActionItems"],
                    "assigned_to":  i["AssignedTo"],
                    "due_date":     i["DueDate"],
                } if i["EntryID"] else None,
            }
            for i in items_all if i["SectionID"] == s["SectionID"]
        ]
        section_list.append({
            "section_id":       s["SectionID"],
            "title":            s["Title"],
            "order_index":      s["OrderIndex"],
            "project_id":       s["ProjectID"],
            "project_name":     s["ProjectName"],
            "accounting_scope": s["AccountingScope"],
            "items":            section_items,
        })

    unsectioned = [
        {
            "item_id":          i["ItemID"],
            "title":            i["Title"],
            "notes_template":   i["NotesTemplate"],
            "duration_minutes": i["DurationMinutes"],
            "presenter":        i["Presenter"],
            "order_index":      i["OrderIndex"],
            "minutes": {
                "entry_id":     i["EntryID"],
                "notes":        i["Notes"],
                "decisions":    i["Decisions"],
                "action_items": i["ActionItems"],
                "assigned_to":  i["AssignedTo"],
                "due_date":     i["DueDate"],
            } if i["EntryID"] else None,
        }
        for i in items_all if not i["SectionID"]
    ]

    return {
        "meeting_id":       m["MeetingID"],
        "business_id":      m["BusinessID"],
        "business_name":    m["BusinessName"],
        "project_id":       m["ProjectID"],
        "project_name":     m["ProjectName"],
        "title":            m["Title"],
        "description":      m["Description"],
        "meeting_date":     m["MeetingDate"].isoformat() if m["MeetingDate"] else None,
        "location":         m["Location"],
        "google_meet_link": m["GoogleMeetLink"],
        "status":           m["Status"],
        "accounting_scope": m["AccountingScope"],
        "created_at":       m["CreatedAt"].isoformat() if m["CreatedAt"] else None,
        "sections":         section_list,
        "unsectioned_items": unsectioned,
        "attendees": [
            {"attendee_id": a["AttendeeID"], "name": a["Name"], "email": a["Email"]}
            for a in attendees
        ],
    }


def _accounting_snapshot(business_id: int, scope: str, project_id: int | None,
                          db: Session) -> dict | None:
    if scope == "none" or not scope:
        return None

    now = datetime.datetime.utcnow()
    year_start = datetime.date(now.year, 1, 1).isoformat()
    year_end   = datetime.date(now.year, 12, 31).isoformat()

    try:
        rev_row = db.execute(
            text("""
                SELECT ISNULL(SUM(TotalAmount), 0) AS Revenue
                FROM Invoices
                WHERE BusinessID = :bid AND Status = 'Paid'
                  AND CAST(InvoiceDate AS DATE) BETWEEN :s AND :e
            """),
            {"bid": business_id, "s": year_start, "e": year_end},
        ).first()

        bill_row = db.execute(
            text("""
                SELECT ISNULL(SUM(TotalAmount), 0) AS Bills
                FROM Bills
                WHERE BusinessID = :bid AND Status = 'Paid'
                  AND CAST(BillDate AS DATE) BETWEEN :s AND :e
            """),
            {"bid": business_id, "s": year_start, "e": year_end},
        ).first()

        exp_row = db.execute(
            text("""
                SELECT ISNULL(SUM(TotalAmount), 0) AS Expenses
                FROM Expenses
                WHERE BusinessID = :bid
                  AND CAST(ExpenseDate AS DATE) BETWEEN :s AND :e
            """),
            {"bid": business_id, "s": year_start, "e": year_end},
        ).first()

        out_inv = db.execute(
            text("""
                SELECT ISNULL(SUM(BalanceDue), 0) AS Outstanding
                FROM Invoices WHERE BusinessID = :bid AND Status NOT IN ('Paid','Void')
            """),
            {"bid": business_id},
        ).first()

        out_bill = db.execute(
            text("""
                SELECT ISNULL(SUM(BalanceDue), 0) AS Outstanding
                FROM Bills WHERE BusinessID = :bid AND Status NOT IN ('Paid','Void')
            """),
            {"bid": business_id},
        ).first()

        expenses = float(bill_row.Bills or 0) + float(exp_row.Expenses or 0)
        label = "Company-Wide Financial Summary" if scope == "company" else "Project Financial Summary"

        return {
            "label":                 label,
            "period":                f"YTD {now.year}",
            "revenue":               float(rev_row.Revenue or 0),
            "expenses":              expenses,
            "outstanding_invoices":  float(out_inv.Outstanding or 0),
            "outstanding_bills":     float(out_bill.Outstanding or 0),
        }
    except Exception as e:
        print(f"[meetings] accounting_snapshot error: {e}")
        return None


# ── Projects CRUD ────────────────────────────────────────────────────────────

@router.get("/projects")
def list_projects(access=Depends(require_access), db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT * FROM MeetingProject WHERE BusinessID=:bid AND Status!='deleted' ORDER BY Name"),
        {"bid": access["business_id"]},
    ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/projects")
def create_project(payload: dict, access=Depends(require_access), db: Session = Depends(get_db)):
    result = db.execute(
        text("""
            INSERT INTO MeetingProject (BusinessID, Name, Description, Color, Status)
            OUTPUT INSERTED.ProjectID
            VALUES (:bid, :name, :desc, :color, 'active')
        """),
        {
            "bid":   access["business_id"],
            "name":  payload.get("name", "New Project"),
            "desc":  payload.get("description"),
            "color": payload.get("color", "#3D6B34"),
        },
    )
    db.commit()
    return {"project_id": result.scalar()}


@router.put("/projects/{project_id}")
def update_project(project_id: int, payload: dict,
                   access=Depends(require_access), db: Session = Depends(get_db)):
    db.execute(
        text("""
            UPDATE MeetingProject SET Name=:name, Description=:desc,
              Color=:color, Status=:status
            WHERE ProjectID=:id AND BusinessID=:bid
        """),
        {
            "id":     project_id,
            "bid":    access["business_id"],
            "name":   payload.get("name"),
            "desc":   payload.get("description"),
            "color":  payload.get("color", "#3D6B34"),
            "status": payload.get("status", "active"),
        },
    )
    db.commit()
    return {"ok": True}


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, access=Depends(require_access), db: Session = Depends(get_db)):
    db.execute(
        text("UPDATE MeetingProject SET Status='deleted' WHERE ProjectID=:id AND BusinessID=:bid"),
        {"id": project_id, "bid": access["business_id"]},
    )
    db.commit()
    return {"ok": True}


# ── Meetings CRUD ────────────────────────────────────────────────────────────

@router.get("")
def list_meetings(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    access=Depends(require_access),
    db: Session = Depends(get_db),
):
    bid    = access["business_id"]
    offset = (page - 1) * limit
    where  = "WHERE m.BusinessID=:bid"
    params = {"bid": bid, "limit": limit, "offset": offset}
    if status:
        where += " AND m.Status=:status"
        params["status"] = status

    rows = db.execute(
        text(f"""
            SELECT m.MeetingID, m.Title, m.MeetingDate, m.Location, m.Status,
                   m.AccountingScope, m.CreatedAt,
                   p.Name AS ProjectName, p.Color AS ProjectColor,
                   (SELECT COUNT(*) FROM MeetingAttendee WHERE MeetingID=m.MeetingID) AS AttendeeCount,
                   (SELECT COUNT(*) FROM MeetingAgendaItem WHERE MeetingID=m.MeetingID) AS ItemCount
            FROM Meeting m
            LEFT JOIN MeetingProject p ON p.ProjectID = m.ProjectID
            {where}
            ORDER BY m.MeetingDate DESC, m.CreatedAt DESC
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
        """),
        params,
    ).mappings().all()

    total = db.execute(
        text(f"SELECT COUNT(*) FROM Meeting m {where}"),
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    ).scalar()

    return {
        "meetings": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "pages": -(-total // limit),
    }


@router.post("")
def create_meeting(payload: dict, access=Depends(require_access), db: Session = Depends(get_db)):
    result = db.execute(
        text("""
            INSERT INTO Meeting
              (BusinessID, ProjectID, Title, Description, MeetingDate,
               Location, GoogleMeetLink, Status, AccountingScope, CreatedBy)
            OUTPUT INSERTED.MeetingID
            VALUES (:bid, :proj, :title, :desc, :date,
                    :loc, :meet_link, 'draft', :acct_scope, :creator)
        """),
        {
            "bid":        access["business_id"],
            "proj":       payload.get("project_id"),
            "title":      payload.get("title", "New Meeting"),
            "desc":       payload.get("description"),
            "date":       payload.get("meeting_date"),
            "loc":        payload.get("location"),
            "meet_link":  payload.get("google_meet_link"),
            "acct_scope": payload.get("accounting_scope", "none"),
            "creator":    access["people_id"],
        },
    )
    db.commit()
    mid = result.scalar()
    return {"meeting_id": mid}


@router.get("/{meeting_id}")
def get_meeting(meeting_id: int, business_id: int = Query(...),
                current_user: models.People = Depends(get_current_user),
                db: Session = Depends(get_db)):
    detail = _meeting_detail(meeting_id, db)
    if not detail or detail["business_id"] != business_id:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    return detail


@router.put("/{meeting_id}")
def update_meeting(meeting_id: int, payload: dict,
                   access=Depends(require_access), db: Session = Depends(get_db)):
    db.execute(
        text("""
            UPDATE Meeting SET Title=:title, Description=:desc, MeetingDate=:date,
              Location=:loc, GoogleMeetLink=:meet_link, ProjectID=:proj,
              AccountingScope=:acct_scope, UpdatedAt=SYSDATETIME()
            WHERE MeetingID=:id AND BusinessID=:bid
        """),
        {
            "id":         meeting_id,
            "bid":        access["business_id"],
            "title":      payload.get("title"),
            "desc":       payload.get("description"),
            "date":       payload.get("meeting_date"),
            "loc":        payload.get("location"),
            "meet_link":  payload.get("google_meet_link"),
            "proj":       payload.get("project_id"),
            "acct_scope": payload.get("accounting_scope", "none"),
        },
    )
    db.commit()
    return {"ok": True}


@router.delete("/{meeting_id}")
def delete_meeting(meeting_id: int, access=Depends(require_access), db: Session = Depends(get_db)):
    bid = access["business_id"]
    db.execute(text("DELETE FROM MeetingMinuteEntry WHERE ItemID IN (SELECT ItemID FROM MeetingAgendaItem WHERE MeetingID=:id)"), {"id": meeting_id})
    db.execute(text("DELETE FROM MeetingAgendaItem WHERE MeetingID=:id"), {"id": meeting_id})
    db.execute(text("DELETE FROM MeetingSection WHERE MeetingID=:id"), {"id": meeting_id})
    db.execute(text("DELETE FROM MeetingAttendee WHERE MeetingID=:id"), {"id": meeting_id})
    db.execute(text("DELETE FROM Meeting WHERE MeetingID=:id AND BusinessID=:bid"), {"id": meeting_id, "bid": bid})
    db.commit()
    return {"ok": True}


# ── Attendees ────────────────────────────────────────────────────────────────

@router.post("/{meeting_id}/attendees")
def add_attendee(meeting_id: int, payload: dict,
                 access=Depends(require_access), db: Session = Depends(get_db)):
    result = db.execute(
        text("""
            INSERT INTO MeetingAttendee (MeetingID, Name, Email)
            OUTPUT INSERTED.AttendeeID VALUES (:mid, :name, :email)
        """),
        {"mid": meeting_id, "name": payload.get("name"), "email": payload.get("email")},
    )
    db.commit()
    return {"attendee_id": result.scalar()}


@router.delete("/{meeting_id}/attendees/{attendee_id}")
def remove_attendee(meeting_id: int, attendee_id: int,
                    access=Depends(require_access), db: Session = Depends(get_db)):
    db.execute(
        text("DELETE FROM MeetingAttendee WHERE AttendeeID=:id AND MeetingID=:mid"),
        {"id": attendee_id, "mid": meeting_id},
    )
    db.commit()
    return {"ok": True}


# ── Sections ─────────────────────────────────────────────────────────────────

@router.post("/{meeting_id}/sections")
def add_section(meeting_id: int, payload: dict,
                access=Depends(require_access), db: Session = Depends(get_db)):
    max_order = db.execute(
        text("SELECT ISNULL(MAX(OrderIndex),0)+1 FROM MeetingSection WHERE MeetingID=:mid"),
        {"mid": meeting_id},
    ).scalar()
    result = db.execute(
        text("""
            INSERT INTO MeetingSection (MeetingID, Title, OrderIndex, ProjectID, AccountingScope)
            OUTPUT INSERTED.SectionID
            VALUES (:mid, :title, :order, :proj, :scope)
        """),
        {
            "mid":   meeting_id,
            "title": payload.get("title", "New Section"),
            "order": payload.get("order_index", max_order),
            "proj":  payload.get("project_id"),
            "scope": payload.get("accounting_scope", "none"),
        },
    )
    db.commit()
    return {"section_id": result.scalar()}


@router.put("/{meeting_id}/sections/{section_id}")
def update_section(meeting_id: int, section_id: int, payload: dict,
                   access=Depends(require_access), db: Session = Depends(get_db)):
    db.execute(
        text("""
            UPDATE MeetingSection SET Title=:title, OrderIndex=:order,
              ProjectID=:proj, AccountingScope=:scope
            WHERE SectionID=:id AND MeetingID=:mid
        """),
        {
            "id":    section_id,
            "mid":   meeting_id,
            "title": payload.get("title"),
            "order": payload.get("order_index", 0),
            "proj":  payload.get("project_id"),
            "scope": payload.get("accounting_scope", "none"),
        },
    )
    db.commit()
    return {"ok": True}


@router.delete("/{meeting_id}/sections/{section_id}")
def delete_section(meeting_id: int, section_id: int,
                   access=Depends(require_access), db: Session = Depends(get_db)):
    db.execute(
        text("DELETE FROM MeetingMinuteEntry WHERE ItemID IN (SELECT ItemID FROM MeetingAgendaItem WHERE SectionID=:id)"),
        {"id": section_id},
    )
    db.execute(text("DELETE FROM MeetingAgendaItem WHERE SectionID=:id"), {"id": section_id})
    db.execute(text("DELETE FROM MeetingSection WHERE SectionID=:id AND MeetingID=:mid"),
               {"id": section_id, "mid": meeting_id})
    db.commit()
    return {"ok": True}


# ── Agenda items ─────────────────────────────────────────────────────────────

@router.post("/{meeting_id}/sections/{section_id}/items")
def add_item(meeting_id: int, section_id: int, payload: dict,
             access=Depends(require_access), db: Session = Depends(get_db)):
    max_order = db.execute(
        text("SELECT ISNULL(MAX(OrderIndex),0)+1 FROM MeetingAgendaItem WHERE SectionID=:sid"),
        {"sid": section_id},
    ).scalar()
    result = db.execute(
        text("""
            INSERT INTO MeetingAgendaItem
              (MeetingID, SectionID, Title, NotesTemplate, DurationMinutes, Presenter, OrderIndex)
            OUTPUT INSERTED.ItemID
            VALUES (:mid, :sid, :title, :notes, :dur, :pres, :order)
        """),
        {
            "mid":   meeting_id,
            "sid":   section_id,
            "title": payload.get("title", "New Item"),
            "notes": payload.get("notes_template"),
            "dur":   payload.get("duration_minutes"),
            "pres":  payload.get("presenter"),
            "order": payload.get("order_index", max_order),
        },
    )
    db.commit()
    return {"item_id": result.scalar()}


@router.put("/{meeting_id}/items/{item_id}")
def update_item(meeting_id: int, item_id: int, payload: dict,
                access=Depends(require_access), db: Session = Depends(get_db)):
    db.execute(
        text("""
            UPDATE MeetingAgendaItem SET Title=:title, NotesTemplate=:notes,
              DurationMinutes=:dur, Presenter=:pres, OrderIndex=:order
            WHERE ItemID=:id AND MeetingID=:mid
        """),
        {
            "id":    item_id,
            "mid":   meeting_id,
            "title": payload.get("title"),
            "notes": payload.get("notes_template"),
            "dur":   payload.get("duration_minutes"),
            "pres":  payload.get("presenter"),
            "order": payload.get("order_index", 0),
        },
    )
    db.commit()
    return {"ok": True}


@router.delete("/{meeting_id}/items/{item_id}")
def delete_item(meeting_id: int, item_id: int,
                access=Depends(require_access), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM MeetingMinuteEntry WHERE ItemID=:id"), {"id": item_id})
    db.execute(text("DELETE FROM MeetingAgendaItem WHERE ItemID=:id AND MeetingID=:mid"),
               {"id": item_id, "mid": meeting_id})
    db.commit()
    return {"ok": True}


# ── Minutes ──────────────────────────────────────────────────────────────────

@router.post("/{meeting_id}/to-minutes")
def convert_to_minutes(meeting_id: int, access=Depends(require_access), db: Session = Depends(get_db)):
    """Flip status to 'minutes' — agenda items become editable minute entries."""
    db.execute(
        text("UPDATE Meeting SET Status='minutes', UpdatedAt=SYSDATETIME() WHERE MeetingID=:id AND BusinessID=:bid"),
        {"id": meeting_id, "bid": access["business_id"]},
    )
    db.commit()
    return {"ok": True}


@router.put("/{meeting_id}/items/{item_id}/minutes")
def upsert_minute_entry(meeting_id: int, item_id: int, payload: dict,
                        access=Depends(require_access), db: Session = Depends(get_db)):
    existing = db.execute(
        text("SELECT EntryID FROM MeetingMinuteEntry WHERE ItemID=:id"),
        {"id": item_id},
    ).scalar()

    if existing:
        db.execute(
            text("""
                UPDATE MeetingMinuteEntry SET Notes=:notes, Decisions=:dec,
                  ActionItems=:actions, AssignedTo=:assigned, DueDate=:due
                WHERE EntryID=:eid
            """),
            {
                "eid":      existing,
                "notes":    payload.get("notes"),
                "dec":      payload.get("decisions"),
                "actions":  payload.get("action_items"),
                "assigned": payload.get("assigned_to"),
                "due":      payload.get("due_date"),
            },
        )
    else:
        db.execute(
            text("""
                INSERT INTO MeetingMinuteEntry
                  (ItemID, Notes, Decisions, ActionItems, AssignedTo, DueDate)
                VALUES (:id, :notes, :dec, :actions, :assigned, :due)
            """),
            {
                "id":       item_id,
                "notes":    payload.get("notes"),
                "dec":      payload.get("decisions"),
                "actions":  payload.get("action_items"),
                "assigned": payload.get("assigned_to"),
                "due":      payload.get("due_date"),
            },
        )
    db.commit()
    return {"ok": True}


# ── Email actions ────────────────────────────────────────────────────────────

@router.post("/{meeting_id}/send-agenda")
def send_agenda(meeting_id: int, access=Depends(require_access), db: Session = Depends(get_db)):
    from meeting_emails import send_meeting_agenda

    detail = _meeting_detail(meeting_id, db)
    if not detail or detail["business_id"] != access["business_id"]:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    snap = _accounting_snapshot(
        access["business_id"],
        detail.get("accounting_scope", "none"),
        detail.get("project_id"),
        db,
    )

    sent, failed = 0, []
    for att in detail["attendees"]:
        ok = send_meeting_agenda(
            att["email"], att["name"], detail, detail["sections"], snap
        )
        if ok:
            sent += 1
        else:
            failed.append(att["email"])

    db.execute(
        text("UPDATE Meeting SET Status='agenda_sent', UpdatedAt=SYSDATETIME() WHERE MeetingID=:id"),
        {"id": meeting_id},
    )
    db.commit()
    return {"sent": sent, "failed": failed}


@router.post("/{meeting_id}/send-minutes")
def send_minutes(meeting_id: int, access=Depends(require_access), db: Session = Depends(get_db)):
    from meeting_emails import send_meeting_minutes

    detail = _meeting_detail(meeting_id, db)
    if not detail or detail["business_id"] != access["business_id"]:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    snap = _accounting_snapshot(
        access["business_id"],
        detail.get("accounting_scope", "none"),
        detail.get("project_id"),
        db,
    )

    sent, failed = 0, []
    for att in detail["attendees"]:
        ok = send_meeting_minutes(
            att["email"], att["name"], detail, detail["sections"], snap
        )
        if ok:
            sent += 1
        else:
            failed.append(att["email"])

    db.execute(
        text("UPDATE Meeting SET Status='minutes_sent', UpdatedAt=SYSDATETIME() WHERE MeetingID=:id"),
        {"id": meeting_id},
    )
    db.commit()
    return {"sent": sent, "failed": failed}


# ── Accounting snapshot (standalone for live preview) ────────────────────────

@router.get("/{meeting_id}/accounting")
def get_accounting(meeting_id: int, business_id: int = Query(...),
                   scope: str = Query("company"),
                   current_user: models.People = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    snap = _accounting_snapshot(business_id, scope, None, db)
    return snap or {}
