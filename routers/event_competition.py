"""
Competition / Judging event.

Organizer defines categories (e.g., Market Lamb, Breeding Ewe, Fleece).
Each category has a rubric — criteria with max-points and weights.
Judges are registered (multiple judges per category OK).
Entrants submit entries; judges score each entry on each criterion.
Final score per entry = sum(criterion_score * weight) averaged across judges
(optionally dropping the highest and lowest when 3+ judges score an entry).
Leaderboard ranks entries per category.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal
from datetime import datetime

try:
    from event_emails import send_registration_confirmation
except Exception:  # pragma: no cover
    def send_registration_confirmation(*a, **kw): return False

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventCompetitionConfig')
        CREATE TABLE OFNEventCompetitionConfig (
            ConfigID             INT IDENTITY(1,1) PRIMARY KEY,
            EventID              INT NOT NULL UNIQUE,
            Description          NVARCHAR(MAX),
            EntryFee             DECIMAL(10,2) DEFAULT 0,
            SpectatorFee         DECIMAL(10,2) DEFAULT 0,
            EntryDeadline        DATE,
            MaxEntriesPerPerson  INT,
            JudgingStyle         NVARCHAR(50) DEFAULT 'rubric',
            DropHighLow          BIT DEFAULT 0,
            PublishLeaderboard   BIT DEFAULT 1,
            AwardTiers           NVARCHAR(MAX),
            RulesText            NVARCHAR(MAX),
            IsActive             BIT DEFAULT 1,
            CreatedDate          DATETIME DEFAULT GETDATE(),
            UpdatedDate          DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventCompetitionCategories')
        CREATE TABLE OFNEventCompetitionCategories (
            CategoryID   INT IDENTITY(1,1) PRIMARY KEY,
            EventID      INT NOT NULL,
            CategoryName NVARCHAR(300) NOT NULL,
            Description  NVARCHAR(MAX),
            DisplayOrder INT DEFAULT 0,
            MaxEntries   INT,
            CreatedDate  DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventCompetitionCriteria')
        CREATE TABLE OFNEventCompetitionCriteria (
            CriterionID   INT IDENTITY(1,1) PRIMARY KEY,
            CategoryID    INT NOT NULL,
            CriterionName NVARCHAR(300) NOT NULL,
            Description   NVARCHAR(MAX),
            MaxPoints     DECIMAL(10,2) DEFAULT 10,
            Weight        DECIMAL(10,4) DEFAULT 1,
            DisplayOrder  INT DEFAULT 0,
            CreatedDate   DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventCompetitionJudges')
        CREATE TABLE OFNEventCompetitionJudges (
            JudgeID      INT IDENTITY(1,1) PRIMARY KEY,
            EventID      INT NOT NULL,
            CategoryID   INT,
            JudgeName    NVARCHAR(300) NOT NULL,
            Email        NVARCHAR(300),
            Credentials  NVARCHAR(500),
            PeopleID     INT,
            AccessCode   NVARCHAR(32),
            CreatedDate  DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventCompetitionEntries')
        CREATE TABLE OFNEventCompetitionEntries (
            EntryID        INT IDENTITY(1,1) PRIMARY KEY,
            EventID        INT NOT NULL,
            CategoryID     INT NOT NULL,
            EntryNumber    NVARCHAR(50),
            EntrantName    NVARCHAR(300) NOT NULL,
            EntrantEmail   NVARCHAR(300),
            EntrantPhone   NVARCHAR(50),
            EntrantPeopleID INT,
            AnimalID       INT,
            EntryTitle     NVARCHAR(500),
            EntryNotes     NVARCHAR(MAX),
            PhotoURL       NVARCHAR(500),
            CheckedIn      BIT DEFAULT 0,
            Disqualified   BIT DEFAULT 0,
            DQReason       NVARCHAR(MAX),
            EntryFeePaid   DECIMAL(10,2) DEFAULT 0,
            CreatedDate    DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventCompetitionScores')
        CREATE TABLE OFNEventCompetitionScores (
            ScoreID      INT IDENTITY(1,1) PRIMARY KEY,
            EntryID      INT NOT NULL,
            JudgeID      INT NOT NULL,
            CriterionID  INT NOT NULL,
            Points       DECIMAL(10,2) NOT NULL,
            Comment      NVARCHAR(MAX),
            CreatedDate  DATETIME DEFAULT GETDATE(),
            UpdatedDate  DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()


# ---------- config ----------

@router.get("/api/events/{event_id}/competition/config")
def get_config(event_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    row = db.execute(text("""
        SELECT ConfigID, EventID, Description, EntryFee, SpectatorFee, EntryDeadline,
               MaxEntriesPerPerson, JudgingStyle, DropHighLow, PublishLeaderboard,
               AwardTiers, RulesText, IsActive
          FROM OFNEventCompetitionConfig WHERE EventID = :e
    """), {"e": event_id}).fetchone()
    if not row:
        return {"EventID": event_id, "EntryFee": 0, "SpectatorFee": 0,
                "JudgingStyle": "rubric", "DropHighLow": False,
                "PublishLeaderboard": True, "IsActive": True}
    return {
        "ConfigID": row[0], "EventID": row[1], "Description": row[2],
        "EntryFee": float(row[3] or 0), "SpectatorFee": float(row[4] or 0),
        "EntryDeadline": row[5].isoformat() if row[5] else None,
        "MaxEntriesPerPerson": row[6], "JudgingStyle": row[7],
        "DropHighLow": bool(row[8]), "PublishLeaderboard": bool(row[9]),
        "AwardTiers": row[10], "RulesText": row[11], "IsActive": bool(row[12]),
    }


@router.put("/api/events/{event_id}/competition/config")
def put_config(event_id: int, payload: dict, db: Session = Depends(get_db)):
    ensure_tables(db)
    exists = db.execute(text("SELECT 1 FROM OFNEventCompetitionConfig WHERE EventID=:e"),
                       {"e": event_id}).fetchone()
    params = {
        "e": event_id,
        "desc": payload.get("Description"),
        "ef": payload.get("EntryFee", 0),
        "sf": payload.get("SpectatorFee", 0),
        "ed": payload.get("EntryDeadline"),
        "mx": payload.get("MaxEntriesPerPerson"),
        "js": payload.get("JudgingStyle", "rubric"),
        "dh": 1 if payload.get("DropHighLow") else 0,
        "pl": 0 if payload.get("PublishLeaderboard") is False else 1,
        "at": payload.get("AwardTiers"),
        "rt": payload.get("RulesText"),
    }
    if exists:
        db.execute(text("""
            UPDATE OFNEventCompetitionConfig
               SET Description=:desc, EntryFee=:ef, SpectatorFee=:sf, EntryDeadline=:ed,
                   MaxEntriesPerPerson=:mx, JudgingStyle=:js, DropHighLow=:dh,
                   PublishLeaderboard=:pl, AwardTiers=:at, RulesText=:rt,
                   UpdatedDate=GETDATE()
             WHERE EventID=:e
        """), params)
    else:
        db.execute(text("""
            INSERT INTO OFNEventCompetitionConfig
              (EventID, Description, EntryFee, SpectatorFee, EntryDeadline,
               MaxEntriesPerPerson, JudgingStyle, DropHighLow, PublishLeaderboard,
               AwardTiers, RulesText)
            VALUES (:e, :desc, :ef, :sf, :ed, :mx, :js, :dh, :pl, :at, :rt)
        """), params)
    db.commit()
    return {"success": True}


# ---------- categories ----------

@router.get("/api/events/{event_id}/competition/categories")
def list_categories(event_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    rows = db.execute(text("""
        SELECT CategoryID, EventID, CategoryName, Description, DisplayOrder, MaxEntries
          FROM OFNEventCompetitionCategories WHERE EventID=:e
         ORDER BY DisplayOrder, CategoryID
    """), {"e": event_id}).fetchall()
    return [{"CategoryID": r[0], "EventID": r[1], "CategoryName": r[2],
             "Description": r[3], "DisplayOrder": r[4], "MaxEntries": r[5]} for r in rows]


@router.post("/api/events/{event_id}/competition/categories")
def create_category(event_id: int, payload: dict, db: Session = Depends(get_db)):
    ensure_tables(db)
    r = db.execute(text("""
        INSERT INTO OFNEventCompetitionCategories
          (EventID, CategoryName, Description, DisplayOrder, MaxEntries)
        VALUES (:e, :n, :d, :o, :m);
        SELECT SCOPE_IDENTITY();
    """), {"e": event_id, "n": payload.get("CategoryName"),
           "d": payload.get("Description"), "o": payload.get("DisplayOrder", 0),
           "m": payload.get("MaxEntries")}).fetchone()
    db.commit()
    return {"CategoryID": int(r[0]) if r and r[0] else None}


@router.put("/api/events/competition/categories/{category_id}")
def update_category(category_id: int, payload: dict, db: Session = Depends(get_db)):
    ensure_tables(db)
    db.execute(text("""
        UPDATE OFNEventCompetitionCategories
           SET CategoryName=:n, Description=:d, DisplayOrder=:o, MaxEntries=:m
         WHERE CategoryID=:c
    """), {"c": category_id, "n": payload.get("CategoryName"),
           "d": payload.get("Description"), "o": payload.get("DisplayOrder", 0),
           "m": payload.get("MaxEntries")})
    db.commit()
    return {"success": True}


@router.delete("/api/events/competition/categories/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    db.execute(text("DELETE FROM OFNEventCompetitionCriteria WHERE CategoryID=:c"),
               {"c": category_id})
    db.execute(text("DELETE FROM OFNEventCompetitionCategories WHERE CategoryID=:c"),
               {"c": category_id})
    db.commit()
    return {"success": True}


# ---------- criteria (rubric) ----------

@router.get("/api/events/competition/categories/{category_id}/criteria")
def list_criteria(category_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    rows = db.execute(text("""
        SELECT CriterionID, CategoryID, CriterionName, Description, MaxPoints, Weight, DisplayOrder
          FROM OFNEventCompetitionCriteria WHERE CategoryID=:c
         ORDER BY DisplayOrder, CriterionID
    """), {"c": category_id}).fetchall()
    return [{"CriterionID": r[0], "CategoryID": r[1], "CriterionName": r[2],
             "Description": r[3], "MaxPoints": float(r[4] or 0),
             "Weight": float(r[5] or 1), "DisplayOrder": r[6]} for r in rows]


@router.post("/api/events/competition/categories/{category_id}/criteria")
def create_criterion(category_id: int, payload: dict, db: Session = Depends(get_db)):
    ensure_tables(db)
    r = db.execute(text("""
        INSERT INTO OFNEventCompetitionCriteria
          (CategoryID, CriterionName, Description, MaxPoints, Weight, DisplayOrder)
        VALUES (:c, :n, :d, :mp, :w, :o);
        SELECT SCOPE_IDENTITY();
    """), {"c": category_id, "n": payload.get("CriterionName"),
           "d": payload.get("Description"), "mp": payload.get("MaxPoints", 10),
           "w": payload.get("Weight", 1), "o": payload.get("DisplayOrder", 0)}).fetchone()
    db.commit()
    return {"CriterionID": int(r[0]) if r and r[0] else None}


@router.put("/api/events/competition/criteria/{criterion_id}")
def update_criterion(criterion_id: int, payload: dict, db: Session = Depends(get_db)):
    ensure_tables(db)
    db.execute(text("""
        UPDATE OFNEventCompetitionCriteria
           SET CriterionName=:n, Description=:d, MaxPoints=:mp, Weight=:w, DisplayOrder=:o
         WHERE CriterionID=:i
    """), {"i": criterion_id, "n": payload.get("CriterionName"),
           "d": payload.get("Description"), "mp": payload.get("MaxPoints", 10),
           "w": payload.get("Weight", 1), "o": payload.get("DisplayOrder", 0)})
    db.commit()
    return {"success": True}


@router.delete("/api/events/competition/criteria/{criterion_id}")
def delete_criterion(criterion_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    db.execute(text("DELETE FROM OFNEventCompetitionScores WHERE CriterionID=:i"),
               {"i": criterion_id})
    db.execute(text("DELETE FROM OFNEventCompetitionCriteria WHERE CriterionID=:i"),
               {"i": criterion_id})
    db.commit()
    return {"success": True}


# ---------- judges ----------

@router.get("/api/events/{event_id}/competition/judges")
def list_judges(event_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    rows = db.execute(text("""
        SELECT JudgeID, EventID, CategoryID, JudgeName, Email, Credentials, PeopleID, AccessCode
          FROM OFNEventCompetitionJudges WHERE EventID=:e
         ORDER BY JudgeID
    """), {"e": event_id}).fetchall()
    return [{"JudgeID": r[0], "EventID": r[1], "CategoryID": r[2], "JudgeName": r[3],
             "Email": r[4], "Credentials": r[5], "PeopleID": r[6],
             "AccessCode": r[7]} for r in rows]


@router.post("/api/events/{event_id}/competition/judges")
def create_judge(event_id: int, payload: dict, db: Session = Depends(get_db)):
    ensure_tables(db)
    import secrets
    access_code = secrets.token_hex(6).upper()
    r = db.execute(text("""
        INSERT INTO OFNEventCompetitionJudges
          (EventID, CategoryID, JudgeName, Email, Credentials, PeopleID, AccessCode)
        VALUES (:e, :c, :n, :em, :cr, :p, :ac);
        SELECT SCOPE_IDENTITY();
    """), {"e": event_id, "c": payload.get("CategoryID"),
           "n": payload.get("JudgeName"), "em": payload.get("Email"),
           "cr": payload.get("Credentials"), "p": payload.get("PeopleID"),
           "ac": access_code}).fetchone()
    db.commit()
    return {"JudgeID": int(r[0]) if r and r[0] else None, "AccessCode": access_code}


@router.put("/api/events/competition/judges/{judge_id}")
def update_judge(judge_id: int, payload: dict, db: Session = Depends(get_db)):
    ensure_tables(db)
    db.execute(text("""
        UPDATE OFNEventCompetitionJudges
           SET CategoryID=:c, JudgeName=:n, Email=:em, Credentials=:cr, PeopleID=:p
         WHERE JudgeID=:i
    """), {"i": judge_id, "c": payload.get("CategoryID"),
           "n": payload.get("JudgeName"), "em": payload.get("Email"),
           "cr": payload.get("Credentials"), "p": payload.get("PeopleID")})
    db.commit()
    return {"success": True}


@router.delete("/api/events/competition/judges/{judge_id}")
def delete_judge(judge_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    db.execute(text("DELETE FROM OFNEventCompetitionScores WHERE JudgeID=:i"),
               {"i": judge_id})
    db.execute(text("DELETE FROM OFNEventCompetitionJudges WHERE JudgeID=:i"),
               {"i": judge_id})
    db.commit()
    return {"success": True}


# ---------- entries ----------

@router.get("/api/events/{event_id}/competition/entries")
def list_entries(event_id: int, category_id: int = None, db: Session = Depends(get_db)):
    ensure_tables(db)
    sql = """
        SELECT EntryID, EventID, CategoryID, EntryNumber, EntrantName, EntrantEmail,
               EntrantPhone, EntrantPeopleID, AnimalID, EntryTitle, EntryNotes, PhotoURL,
               CheckedIn, Disqualified, DQReason, EntryFeePaid
          FROM OFNEventCompetitionEntries WHERE EventID=:e
    """
    params = {"e": event_id}
    if category_id is not None:
        sql += " AND CategoryID=:c"
        params["c"] = category_id
    sql += " ORDER BY EntryID"
    rows = db.execute(text(sql), params).fetchall()
    return [{"EntryID": r[0], "EventID": r[1], "CategoryID": r[2],
             "EntryNumber": r[3], "EntrantName": r[4], "EntrantEmail": r[5],
             "EntrantPhone": r[6], "EntrantPeopleID": r[7], "AnimalID": r[8],
             "EntryTitle": r[9], "EntryNotes": r[10], "PhotoURL": r[11],
             "CheckedIn": bool(r[12]), "Disqualified": bool(r[13]),
             "DQReason": r[14], "EntryFeePaid": float(r[15] or 0)} for r in rows]


@router.post("/api/events/{event_id}/competition/entries")
def create_entry(event_id: int, payload: dict, db: Session = Depends(get_db)):
    ensure_tables(db)
    cfg = db.execute(text("SELECT EntryFee FROM OFNEventCompetitionConfig WHERE EventID=:e"),
                     {"e": event_id}).fetchone()
    fee = float(cfg[0]) if cfg and cfg[0] is not None else 0.0
    r = db.execute(text("""
        INSERT INTO OFNEventCompetitionEntries
          (EventID, CategoryID, EntryNumber, EntrantName, EntrantEmail, EntrantPhone,
           EntrantPeopleID, AnimalID, EntryTitle, EntryNotes, PhotoURL, EntryFeePaid)
        VALUES (:e, :c, :en, :nm, :em, :ph, :p, :a, :t, :no, :pu, :fe);
        SELECT SCOPE_IDENTITY();
    """), {"e": event_id, "c": payload.get("CategoryID"),
           "en": payload.get("EntryNumber"), "nm": payload.get("EntrantName"),
           "em": payload.get("EntrantEmail"), "ph": payload.get("EntrantPhone"),
           "p": payload.get("EntrantPeopleID"), "a": payload.get("AnimalID"),
           "t": payload.get("EntryTitle"), "no": payload.get("EntryNotes"),
           "pu": payload.get("PhotoURL"), "fe": fee}).fetchone()
    db.commit()
    new_id = int(r[0]) if r and r[0] else None

    if new_id and payload.get("EntrantEmail"):
        ev = db.execute(text("""
            SELECT EventID, EventName, EventStartDate, EventLocationName,
                   EventLocationStreet, EventLocationCity, EventLocationState, EventLocationZip
              FROM OFNEvents WHERE EventID = :e
        """), {"e": event_id}).mappings().first()
        extra = f'<p style="font-size:13px;color:#555"><strong>Entry fee:</strong> ${fee:.2f}</p>' if fee else ''
        try:
            send_registration_confirmation(
                to_email=payload["EntrantEmail"],
                attendee_name=payload.get("EntrantName") or '',
                event=dict(ev) if ev else {"EventID": event_id},
                kind="Competition Entry", reg_id=new_id, extra_html=extra,
            )
        except Exception as ex:
            print(f"[event_competition] email send failed: {ex}")

    return {"EntryID": new_id, "EntryFeePaid": fee}


@router.put("/api/events/competition/entries/{entry_id}")
def update_entry(entry_id: int, payload: dict, db: Session = Depends(get_db)):
    ensure_tables(db)
    db.execute(text("""
        UPDATE OFNEventCompetitionEntries
           SET CategoryID=:c, EntryNumber=:en, EntrantName=:nm, EntrantEmail=:em,
               EntrantPhone=:ph, AnimalID=:a, EntryTitle=:t, EntryNotes=:no,
               PhotoURL=:pu, Disqualified=:dq, DQReason=:dr
         WHERE EntryID=:i
    """), {"i": entry_id, "c": payload.get("CategoryID"),
           "en": payload.get("EntryNumber"), "nm": payload.get("EntrantName"),
           "em": payload.get("EntrantEmail"), "ph": payload.get("EntrantPhone"),
           "a": payload.get("AnimalID"), "t": payload.get("EntryTitle"),
           "no": payload.get("EntryNotes"), "pu": payload.get("PhotoURL"),
           "dq": 1 if payload.get("Disqualified") else 0,
           "dr": payload.get("DQReason")})
    db.commit()
    return {"success": True}


@router.put("/api/events/competition/entries/{entry_id}/checkin")
def checkin_entry(entry_id: int, payload: dict, db: Session = Depends(get_db)):
    ensure_tables(db)
    db.execute(text("UPDATE OFNEventCompetitionEntries SET CheckedIn=:v WHERE EntryID=:i"),
               {"i": entry_id, "v": 1 if payload.get("CheckedIn") else 0})
    db.commit()
    return {"success": True}


@router.delete("/api/events/competition/entries/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    db.execute(text("DELETE FROM OFNEventCompetitionScores WHERE EntryID=:i"),
               {"i": entry_id})
    db.execute(text("DELETE FROM OFNEventCompetitionEntries WHERE EntryID=:i"),
               {"i": entry_id})
    db.commit()
    return {"success": True}


# ---------- judge portal (public, access-code auth) ----------

@router.get("/api/events/competition/judge/{access_code}")
def judge_view(access_code: str, db: Session = Depends(get_db)):
    """Public scoring view. Judge visits /judge/{AccessCode} and gets their
    assigned categories, rubric, entries, and any scores they've already saved."""
    ensure_tables(db)
    judge = db.execute(text("""
        SELECT JudgeID, EventID, CategoryID, JudgeName, Credentials
          FROM OFNEventCompetitionJudges WHERE AccessCode=:c
    """), {"c": access_code}).fetchone()
    if not judge:
        raise HTTPException(404, "Invalid access code")
    judge_id, event_id, assigned_cat, judge_name, creds = judge

    event = db.execute(text("""
        SELECT EventID, EventName FROM OFNEvents WHERE EventID=:e
    """), {"e": event_id}).fetchone()
    event_d = {"EventID": event[0], "EventName": event[1]} if event else {"EventID": event_id}

    cat_sql = """
        SELECT CategoryID, CategoryName, Description, DisplayOrder
          FROM OFNEventCompetitionCategories WHERE EventID=:e
    """
    cat_params = {"e": event_id}
    if assigned_cat:
        cat_sql += " AND CategoryID=:c"
        cat_params["c"] = assigned_cat
    cat_sql += " ORDER BY DisplayOrder, CategoryID"
    cat_rows = db.execute(text(cat_sql), cat_params).fetchall()

    categories = []
    for cr in cat_rows:
        cat_id = cr[0]
        criteria = db.execute(text("""
            SELECT CriterionID, CriterionName, Description, MaxPoints, Weight, DisplayOrder
              FROM OFNEventCompetitionCriteria WHERE CategoryID=:c
             ORDER BY DisplayOrder, CriterionID
        """), {"c": cat_id}).fetchall()
        entries = db.execute(text("""
            SELECT EntryID, EntryNumber, EntrantName, EntryTitle, EntryNotes, PhotoURL,
                   CheckedIn, Disqualified
              FROM OFNEventCompetitionEntries
             WHERE CategoryID=:c AND ISNULL(Disqualified, 0) = 0
             ORDER BY EntryID
        """), {"c": cat_id}).fetchall()
        entry_ids = [e[0] for e in entries]
        my_scores = {}
        if entry_ids:
            placeholders = ", ".join(f":e{i}" for i in range(len(entry_ids)))
            s_params = {f"e{i}": eid for i, eid in enumerate(entry_ids)}
            s_params["j"] = judge_id
            score_rows = db.execute(text(f"""
                SELECT EntryID, CriterionID, Points, Comment
                  FROM OFNEventCompetitionScores
                 WHERE JudgeID=:j AND EntryID IN ({placeholders})
            """), s_params).fetchall()
            for sr in score_rows:
                my_scores[f"{sr[0]}:{sr[1]}"] = {"Points": float(sr[2] or 0),
                                                  "Comment": sr[3]}
        categories.append({
            "CategoryID": cat_id,
            "CategoryName": cr[1],
            "Description": cr[2],
            "Criteria": [{"CriterionID": cx[0], "CriterionName": cx[1],
                          "Description": cx[2], "MaxPoints": float(cx[3] or 0),
                          "Weight": float(cx[4] or 1)} for cx in criteria],
            "Entries": [{"EntryID": e[0], "EntryNumber": e[1], "EntrantName": e[2],
                         "EntryTitle": e[3], "EntryNotes": e[4], "PhotoURL": e[5],
                         "CheckedIn": bool(e[6])} for e in entries],
            "MyScores": my_scores,
        })
    return {"Judge": {"JudgeID": judge_id, "JudgeName": judge_name,
                      "Credentials": creds, "AccessCode": access_code},
            "Event": event_d, "Categories": categories}


# ---------- scores ----------

@router.get("/api/events/competition/entries/{entry_id}/scores")
def list_scores(entry_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    rows = db.execute(text("""
        SELECT s.ScoreID, s.EntryID, s.JudgeID, s.CriterionID, s.Points, s.Comment,
               j.JudgeName, c.CriterionName, c.MaxPoints, c.Weight
          FROM OFNEventCompetitionScores s
          LEFT JOIN OFNEventCompetitionJudges j ON j.JudgeID = s.JudgeID
          LEFT JOIN OFNEventCompetitionCriteria c ON c.CriterionID = s.CriterionID
         WHERE s.EntryID=:i
         ORDER BY j.JudgeName, c.DisplayOrder
    """), {"i": entry_id}).fetchall()
    return [{"ScoreID": r[0], "EntryID": r[1], "JudgeID": r[2], "CriterionID": r[3],
             "Points": float(r[4] or 0), "Comment": r[5], "JudgeName": r[6],
             "CriterionName": r[7], "MaxPoints": float(r[8] or 0),
             "Weight": float(r[9] or 1)} for r in rows]


@router.post("/api/events/competition/entries/{entry_id}/scores")
def save_score(entry_id: int, payload: dict, db: Session = Depends(get_db)):
    """Upsert a score for (entry, judge, criterion)."""
    ensure_tables(db)
    judge_id = payload.get("JudgeID")
    criterion_id = payload.get("CriterionID")
    existing = db.execute(text("""
        SELECT ScoreID FROM OFNEventCompetitionScores
         WHERE EntryID=:e AND JudgeID=:j AND CriterionID=:c
    """), {"e": entry_id, "j": judge_id, "c": criterion_id}).fetchone()
    if existing:
        db.execute(text("""
            UPDATE OFNEventCompetitionScores
               SET Points=:p, Comment=:cm, UpdatedDate=GETDATE()
             WHERE ScoreID=:i
        """), {"i": existing[0], "p": payload.get("Points", 0),
               "cm": payload.get("Comment")})
        db.commit()
        return {"ScoreID": existing[0], "updated": True}
    r = db.execute(text("""
        INSERT INTO OFNEventCompetitionScores (EntryID, JudgeID, CriterionID, Points, Comment)
        VALUES (:e, :j, :c, :p, :cm);
        SELECT SCOPE_IDENTITY();
    """), {"e": entry_id, "j": judge_id, "c": criterion_id,
           "p": payload.get("Points", 0), "cm": payload.get("Comment")}).fetchone()
    db.commit()
    return {"ScoreID": int(r[0]) if r and r[0] else None, "created": True}


# ---------- leaderboard ----------

@router.get("/api/events/{event_id}/competition/leaderboard")
def leaderboard(event_id: int, category_id: int = None, db: Session = Depends(get_db)):
    """
    Compute final scores per entry.
    For each judge who scored an entry: total = sum(points * weight) across that
    judge's scored criteria for the entry's category. Entry final = average across
    judges (optionally dropping high+low if DropHighLow and >=3 judges).
    """
    ensure_tables(db)
    cfg = db.execute(text("SELECT DropHighLow FROM OFNEventCompetitionConfig WHERE EventID=:e"),
                     {"e": event_id}).fetchone()
    drop_hl = bool(cfg[0]) if cfg else False

    cat_sql = "SELECT CategoryID, CategoryName FROM OFNEventCompetitionCategories WHERE EventID=:e"
    cat_params = {"e": event_id}
    if category_id is not None:
        cat_sql += " AND CategoryID=:c"
        cat_params["c"] = category_id
    cat_sql += " ORDER BY DisplayOrder, CategoryID"
    categories = db.execute(text(cat_sql), cat_params).fetchall()

    result = []
    for cat in categories:
        cid, cname = cat[0], cat[1]
        entries = db.execute(text("""
            SELECT EntryID, EntryNumber, EntrantName, EntryTitle, Disqualified
              FROM OFNEventCompetitionEntries
             WHERE EventID=:e AND CategoryID=:c
        """), {"e": event_id, "c": cid}).fetchall()

        entry_scores = []
        for e in entries:
            eid = e[0]
            if e[4]:
                entry_scores.append({"EntryID": eid, "EntryNumber": e[1],
                                     "EntrantName": e[2], "EntryTitle": e[3],
                                     "FinalScore": None, "Disqualified": True,
                                     "JudgeCount": 0})
                continue
            judge_rows = db.execute(text("""
                SELECT s.JudgeID, SUM(s.Points * ISNULL(cr.Weight,1))
                  FROM OFNEventCompetitionScores s
                  JOIN OFNEventCompetitionCriteria cr ON cr.CriterionID = s.CriterionID
                 WHERE s.EntryID=:i
                 GROUP BY s.JudgeID
            """), {"i": eid}).fetchall()
            totals = [float(jr[1] or 0) for jr in judge_rows]
            count = len(totals)
            if count == 0:
                final = None
            elif drop_hl and count >= 3:
                trimmed = sorted(totals)[1:-1]
                final = sum(trimmed) / len(trimmed) if trimmed else None
            else:
                final = sum(totals) / count
            entry_scores.append({"EntryID": eid, "EntryNumber": e[1],
                                 "EntrantName": e[2], "EntryTitle": e[3],
                                 "FinalScore": final, "Disqualified": False,
                                 "JudgeCount": count})
        entry_scores.sort(key=lambda x: (x["FinalScore"] is None, -(x["FinalScore"] or 0)))
        for idx, es in enumerate(entry_scores):
            es["Rank"] = idx + 1 if es["FinalScore"] is not None and not es["Disqualified"] else None
        result.append({"CategoryID": cid, "CategoryName": cname, "Entries": entry_scores})
    return {"Leaderboard": result, "DropHighLow": drop_hl}
