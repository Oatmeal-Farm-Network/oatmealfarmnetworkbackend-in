"""
CSA Advanced — Membership, BoxBot, Vacation Holds, Pickup Sites,
Newsletters, Crop Progress, Box Labels, Harvest Allocation.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional
import json
from datetime import date, datetime

router = APIRouter(prefix="/api/csa-advanced", tags=["csa-advanced"])


# ── Table creation ────────────────────────────────────────────────────────────

def _ensure_tables(db: Session):
    statements = [
        # Shared-risk contracts
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSAContracts')
        CREATE TABLE CSAContracts (
            ContractID   INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID   INT NOT NULL,
            SubscriptionID INT,
            PeopleID     INT,
            SeasonYear   INT,
            TermsText    NVARCHAR(MAX),
            SignedAt      DATETIME,
            SignatureData NVARCHAR(MAX),
            IsActive     BIT DEFAULT 1,
            CreatedAt    DATETIME DEFAULT GETDATE()
        )""",
        # Payment plans
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSAPaymentPlans')
        CREATE TABLE CSAPaymentPlans (
            PlanID         INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID     INT NOT NULL,
            SubscriptionID INT,
            PeopleID       INT,
            PlanType       NVARCHAR(20) DEFAULT 'installment',
            TotalAmount    DECIMAL(10,2),
            PaidAmount     DECIMAL(10,2) DEFAULT 0,
            SeasonYear     INT,
            StartDate      DATE,
            Status         NVARCHAR(20) DEFAULT 'active',
            Notes          NVARCHAR(500),
            CreatedAt      DATETIME DEFAULT GETDATE()
        )""",
        # Installment schedule rows
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSAPaymentInstallments')
        CREATE TABLE CSAPaymentInstallments (
            InstallmentID  INT IDENTITY(1,1) PRIMARY KEY,
            PlanID         INT NOT NULL,
            DueDate        DATE,
            Amount         DECIMAL(10,2),
            PaidAt         DATETIME,
            PaidAmount     DECIMAL(10,2),
            Notes          NVARCHAR(300)
        )""",
        # Work-share registrations
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSAWorkShares')
        CREATE TABLE CSAWorkShares (
            WorkShareID    INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID     INT NOT NULL,
            SubscriptionID INT,
            PeopleID       INT,
            MemberName     NVARCHAR(200),
            SeasonYear     INT,
            RequiredHours  DECIMAL(6,1) DEFAULT 0,
            LoggedHours    DECIMAL(6,1) DEFAULT 0,
            DiscountPct    DECIMAL(5,2) DEFAULT 0,
            Notes          NVARCHAR(500),
            CreatedAt      DATETIME DEFAULT GETDATE()
        )""",
        # Work-share hour logs
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSAWorkShareLogs')
        CREATE TABLE CSAWorkShareLogs (
            LogID          INT IDENTITY(1,1) PRIMARY KEY,
            WorkShareID    INT NOT NULL,
            LogDate        DATE,
            HoursWorked    DECIMAL(4,1),
            TaskDescription NVARCHAR(300),
            ApprovedBy     NVARCHAR(200),
            Notes          NVARCHAR(300),
            CreatedAt      DATETIME DEFAULT GETDATE()
        )""",
        # Member produce preferences (for BoxBot)
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSASharePreferences')
        CREATE TABLE CSASharePreferences (
            PrefID         INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID     INT NOT NULL,
            SubscriptionID INT,
            PeopleID       INT,
            MemberName     NVARCHAR(200),
            ItemName       NVARCHAR(200),
            Preference     NVARCHAR(20) DEFAULT 'neutral',
            Notes          NVARCHAR(300),
            UpdatedAt      DATETIME DEFAULT GETDATE()
        )""",
        # BoxBot allocation runs
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSABoxBotRuns')
        CREATE TABLE CSABoxBotRuns (
            RunID          INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID     INT NOT NULL,
            WeekOf         DATE,
            HarvestJSON    NVARCHAR(MAX),
            AllocationsJSON NVARCHAR(MAX),
            Status         NVARCHAR(20) DEFAULT 'draft',
            Notes          NVARCHAR(500),
            CreatedAt      DATETIME DEFAULT GETDATE(),
            ConfirmedAt    DATETIME
        )""",
        # Vacation holds
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSAVacationHolds')
        CREATE TABLE CSAVacationHolds (
            HoldID         INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID     INT NOT NULL,
            SubscriptionID INT,
            PeopleID       INT,
            MemberName     NVARCHAR(200),
            HoldWeek       DATE,
            Disposition    NVARCHAR(30) DEFAULT 'donate',
            CreditValue    DECIMAL(8,2),
            AppliedAt      DATETIME,
            Notes          NVARCHAR(300),
            CreatedAt      DATETIME DEFAULT GETDATE()
        )""",
        # Pickup / drop sites
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSAPickupSites')
        CREATE TABLE CSAPickupSites (
            SiteID         INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID     INT NOT NULL,
            SiteName       NVARCHAR(200),
            Address        NVARCHAR(300),
            City           NVARCHAR(100),
            StateProvince  NVARCHAR(50),
            ContactName    NVARCHAR(200),
            ContactPhone   NVARCHAR(30),
            ContactEmail   NVARCHAR(200),
            SpecialInstructions NVARCHAR(MAX),
            IsActive       BIT DEFAULT 1,
            CreatedAt      DATETIME DEFAULT GETDATE()
        )""",
        # Member-to-site assignments
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSASiteAssignments')
        CREATE TABLE CSASiteAssignments (
            AssignmentID   INT IDENTITY(1,1) PRIMARY KEY,
            SiteID         INT NOT NULL,
            BusinessID     INT NOT NULL,
            SubscriptionID INT,
            PeopleID       INT,
            MemberName     NVARCHAR(200),
            SeasonYear     INT,
            CreatedAt      DATETIME DEFAULT GETDATE()
        )""",
        # Sign-in log per delivery
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSASigninLog')
        CREATE TABLE CSASigninLog (
            SigninID       INT IDENTITY(1,1) PRIMARY KEY,
            SiteID         INT NOT NULL,
            BusinessID     INT NOT NULL,
            SubscriptionID INT,
            PeopleID       INT,
            MemberName     NVARCHAR(200),
            DeliveryDate   DATE,
            SignedIn       BIT DEFAULT 0,
            SignInTime     DATETIME,
            Notes          NVARCHAR(300)
        )""",
        # Crop progress posts
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSACropProgress')
        CREATE TABLE CSACropProgress (
            ProgressID     INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID     INT NOT NULL,
            CropName       NVARCHAR(200),
            Caption        NVARCHAR(MAX),
            PhotoURL       NVARCHAR(500),
            PostedAt       DATETIME DEFAULT GETDATE(),
            IsPublic       BIT DEFAULT 1,
            PostedByAgent  NVARCHAR(100)
        )""",
        # Newsletter sends
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSANewsletterSends')
        CREATE TABLE CSANewsletterSends (
            SendID         INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID     INT NOT NULL,
            Subject        NVARCHAR(300),
            Body           NVARCHAR(MAX),
            HarvestJSON    NVARCHAR(MAX),
            RecipientCount INT DEFAULT 0,
            SentAt         DATETIME DEFAULT GETDATE(),
            WeekOf         DATE
        )""",
        # Harvest allocation plans
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSAHarvestAllocations')
        CREATE TABLE CSAHarvestAllocations (
            AllocationID   INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID     INT NOT NULL,
            WeekOf         DATE,
            CropName       NVARCHAR(200),
            EstimatedYield DECIMAL(10,2),
            YieldUnit      NVARCHAR(50),
            FullShareQty   DECIMAL(8,2),
            HalfShareQty   DECIMAL(8,2),
            AddOnQty       DECIMAL(8,2),
            TotalFullShares INT,
            TotalHalfShares INT,
            Notes          NVARCHAR(300),
            ConfirmedAt    DATETIME,
            CreatedAt      DATETIME DEFAULT GETDATE()
        )""",
        # Box label runs
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CSABoxLabelRuns')
        CREATE TABLE CSABoxLabelRuns (
            LabelRunID     INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID     INT NOT NULL,
            WeekOf         DATE,
            LabelsJSON     NVARCHAR(MAX),
            LabelCount     INT DEFAULT 0,
            GeneratedAt    DATETIME DEFAULT GETDATE()
        )""",
    ]
    for sql in statements:
        try:
            db.execute(text(sql))
        except Exception:
            pass
    db.commit()


# ── Auth helper ───────────────────────────────────────────────────────────────

def _require_business(business_id: int, db: Session):
    row = db.execute(text("SELECT TOP 1 BusinessID FROM Business WHERE BusinessID=:b"), {"b": business_id}).first()
    if not row:
        raise HTTPException(status_code=404, detail="Business not found")


# ── Startup ───────────────────────────────────────────────────────────────────

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

_tables_created = False

def _lazy_ensure(db: Session):
    global _tables_created
    if not _tables_created:
        _ensure_tables(db)
        _tables_created = True


# ═══════════════════════════════════════════════════════════════════════════════
# CONTRACTS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{business_id}/contracts")
def list_contracts(business_id: int, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    rows = db.execute(text("""
        SELECT c.*, p.FirstName + ' ' + p.LastName AS MemberFullName
        FROM CSAContracts c
        LEFT JOIN People p ON p.PeopleID = c.PeopleID
        WHERE c.BusinessID = :b
        ORDER BY c.CreatedAt DESC
    """), {"b": business_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/{business_id}/contracts")
def create_contract(business_id: int, body: dict, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    row = db.execute(text("""
        INSERT INTO CSAContracts (BusinessID, SubscriptionID, PeopleID, SeasonYear, TermsText)
        OUTPUT INSERTED.ContractID
        VALUES (:b, :sub, :p, :yr, :terms)
    """), {
        "b": business_id,
        "sub": body.get("subscription_id"),
        "p":   body.get("people_id"),
        "yr":  body.get("season_year"),
        "terms": body.get("terms_text", ""),
    }).first()
    db.commit()
    return {"ContractID": row[0]}


@router.patch("/contracts/{contract_id}/sign")
def sign_contract(contract_id: int, body: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE CSAContracts SET SignedAt=GETDATE(), SignatureData=:sig
        WHERE ContractID=:id
    """), {"sig": body.get("signature_data", ""), "id": contract_id})
    db.commit()
    return {"ok": True}


@router.delete("/contracts/{contract_id}")
def delete_contract(contract_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE CSAContracts SET IsActive=0 WHERE ContractID=:id"), {"id": contract_id})
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# PAYMENT PLANS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{business_id}/payment-plans")
def list_payment_plans(business_id: int, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    plans = db.execute(text("""
        SELECT pp.*, p.FirstName + ' ' + p.LastName AS MemberFullName
        FROM CSAPaymentPlans pp
        LEFT JOIN People p ON p.PeopleID = pp.PeopleID
        WHERE pp.BusinessID = :b
        ORDER BY pp.CreatedAt DESC
    """), {"b": business_id}).fetchall()
    result = []
    for plan in plans:
        d = dict(plan._mapping)
        installments = db.execute(text(
            "SELECT * FROM CSAPaymentInstallments WHERE PlanID=:pid ORDER BY DueDate"
        ), {"pid": d["PlanID"]}).fetchall()
        d["installments"] = [dict(i._mapping) for i in installments]
        result.append(d)
    return result


@router.post("/{business_id}/payment-plans")
def create_payment_plan(business_id: int, body: dict, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    row = db.execute(text("""
        INSERT INTO CSAPaymentPlans
            (BusinessID, SubscriptionID, PeopleID, PlanType, TotalAmount, SeasonYear, StartDate, Notes)
        OUTPUT INSERTED.PlanID
        VALUES (:b, :sub, :p, :pt, :amt, :yr, :sd, :notes)
    """), {
        "b":     business_id,
        "sub":   body.get("subscription_id"),
        "p":     body.get("people_id"),
        "pt":    body.get("plan_type", "installment"),
        "amt":   body.get("total_amount", 0),
        "yr":    body.get("season_year"),
        "sd":    body.get("start_date"),
        "notes": body.get("notes", ""),
    }).first()
    plan_id = row[0]
    # Create installment rows if provided
    for inst in body.get("installments", []):
        db.execute(text("""
            INSERT INTO CSAPaymentInstallments (PlanID, DueDate, Amount)
            VALUES (:pid, :dd, :amt)
        """), {"pid": plan_id, "dd": inst.get("due_date"), "amt": inst.get("amount", 0)})
    db.commit()
    return {"PlanID": plan_id}


@router.patch("/payment-plans/{plan_id}")
def update_payment_plan(plan_id: int, body: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE CSAPaymentPlans
        SET Status=ISNULL(:status, Status),
            PaidAmount=ISNULL(:paid, PaidAmount),
            Notes=ISNULL(:notes, Notes)
        WHERE PlanID=:id
    """), {
        "status": body.get("status"),
        "paid":   body.get("paid_amount"),
        "notes":  body.get("notes"),
        "id":     plan_id,
    })
    db.commit()
    return {"ok": True}


@router.post("/payment-plans/{plan_id}/installments/{inst_id}/pay")
def pay_installment(plan_id: int, inst_id: int, body: dict, db: Session = Depends(get_db)):
    amt = body.get("paid_amount", 0)
    db.execute(text("""
        UPDATE CSAPaymentInstallments
        SET PaidAt=GETDATE(), PaidAmount=:amt
        WHERE InstallmentID=:id AND PlanID=:pid
    """), {"amt": amt, "id": inst_id, "pid": plan_id})
    # Update plan's running total
    db.execute(text("""
        UPDATE CSAPaymentPlans
        SET PaidAmount = (SELECT ISNULL(SUM(PaidAmount),0) FROM CSAPaymentInstallments WHERE PlanID=:pid)
        WHERE PlanID=:pid
    """), {"pid": plan_id})
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# WORK SHARES
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{business_id}/work-shares")
def list_work_shares(business_id: int, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    rows = db.execute(text("""
        SELECT * FROM CSAWorkShares WHERE BusinessID=:b ORDER BY MemberName
    """), {"b": business_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/{business_id}/work-shares")
def create_work_share(business_id: int, body: dict, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    row = db.execute(text("""
        INSERT INTO CSAWorkShares
            (BusinessID, SubscriptionID, PeopleID, MemberName, SeasonYear, RequiredHours, DiscountPct, Notes)
        OUTPUT INSERTED.WorkShareID
        VALUES (:b, :sub, :p, :name, :yr, :req, :disc, :notes)
    """), {
        "b":    business_id,
        "sub":  body.get("subscription_id"),
        "p":    body.get("people_id"),
        "name": body.get("member_name", ""),
        "yr":   body.get("season_year"),
        "req":  body.get("required_hours", 0),
        "disc": body.get("discount_pct", 0),
        "notes": body.get("notes", ""),
    }).first()
    db.commit()
    return {"WorkShareID": row[0]}


@router.post("/work-shares/{ws_id}/logs")
def log_hours(ws_id: int, body: dict, db: Session = Depends(get_db)):
    hrs = float(body.get("hours_worked", 0))
    db.execute(text("""
        INSERT INTO CSAWorkShareLogs (WorkShareID, LogDate, HoursWorked, TaskDescription, ApprovedBy, Notes)
        VALUES (:ws, :ld, :hrs, :task, :appr, :notes)
    """), {
        "ws":   ws_id,
        "ld":   body.get("log_date"),
        "hrs":  hrs,
        "task": body.get("task_description", ""),
        "appr": body.get("approved_by", ""),
        "notes": body.get("notes", ""),
    })
    db.execute(text("""
        UPDATE CSAWorkShares SET LoggedHours = LoggedHours + :hrs WHERE WorkShareID=:ws
    """), {"hrs": hrs, "ws": ws_id})
    db.commit()
    return {"ok": True}


@router.get("/work-shares/{ws_id}/logs")
def get_work_logs(ws_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text(
        "SELECT * FROM CSAWorkShareLogs WHERE WorkShareID=:ws ORDER BY LogDate DESC"
    ), {"ws": ws_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.delete("/work-shares/{ws_id}")
def delete_work_share(ws_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM CSAWorkShareLogs WHERE WorkShareID=:ws"), {"ws": ws_id})
    db.execute(text("DELETE FROM CSAWorkShares WHERE WorkShareID=:ws"), {"ws": ws_id})
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# SHARE PREFERENCES
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{business_id}/preferences")
def list_all_preferences(business_id: int, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    rows = db.execute(text("""
        SELECT * FROM CSASharePreferences WHERE BusinessID=:b ORDER BY MemberName, ItemName
    """), {"b": business_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/preferences/{subscription_id}")
def get_member_preferences(subscription_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT * FROM CSASharePreferences WHERE SubscriptionID=:sub ORDER BY ItemName
    """), {"sub": subscription_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/{business_id}/preferences")
def upsert_preference(business_id: int, body: dict, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    existing = db.execute(text("""
        SELECT PrefID FROM CSASharePreferences
        WHERE BusinessID=:b AND SubscriptionID=:sub AND ItemName=:item
    """), {"b": business_id, "sub": body.get("subscription_id"), "item": body.get("item_name", "")}).first()
    if existing:
        db.execute(text("""
            UPDATE CSASharePreferences SET Preference=:pref, Notes=:notes, UpdatedAt=GETDATE()
            WHERE PrefID=:id
        """), {"pref": body.get("preference", "neutral"), "notes": body.get("notes", ""), "id": existing[0]})
    else:
        db.execute(text("""
            INSERT INTO CSASharePreferences
                (BusinessID, SubscriptionID, PeopleID, MemberName, ItemName, Preference, Notes)
            VALUES (:b, :sub, :p, :name, :item, :pref, :notes)
        """), {
            "b":    business_id,
            "sub":  body.get("subscription_id"),
            "p":    body.get("people_id"),
            "name": body.get("member_name", ""),
            "item": body.get("item_name", ""),
            "pref": body.get("preference", "neutral"),
            "notes": body.get("notes", ""),
        })
    db.commit()
    return {"ok": True}


@router.delete("/preferences/{pref_id}")
def delete_preference(pref_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM CSASharePreferences WHERE PrefID=:id"), {"id": pref_id})
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# BOXBOT — Automated Share Balancing
# ═══════════════════════════════════════════════════════════════════════════════

def _run_boxbot(business_id: int, harvest: list, db: Session) -> list:
    """
    Distribute available produce among active subscriptions respecting preferences.
    harvest: [{"crop": str, "qty": float, "unit": str}, ...]
    Returns: [{"subscription_id", "member_name", "share_type", "items": [...]}, ...]
    """
    subs = db.execute(text("""
        SELECT s.SubscriptionID, s.MemberName, s.ShareType
        FROM CSASubscriptions s
        WHERE s.BusinessID=:b AND s.Status='active'
    """), {"b": business_id}).fetchall()
    if not subs:
        return []

    # Load all preferences for this business keyed by subscription_id -> {item_lower: pref}
    prefs_rows = db.execute(text("""
        SELECT SubscriptionID, LOWER(ItemName) AS item, Preference
        FROM CSASharePreferences WHERE BusinessID=:b
    """), {"b": business_id}).fetchall()
    prefs: dict = {}
    for r in prefs_rows:
        prefs.setdefault(r[0], {})[r[1]] = r[2]

    full_subs = [s for s in subs if (s[2] or "").lower() != "half"]
    half_subs = [s for s in subs if (s[2] or "").lower() == "half"]

    allocations = {s[0]: {"subscription_id": s[0], "member_name": s[1],
                           "share_type": s[2] or "full", "items": []} for s in subs}

    for crop_row in harvest:
        crop_name = crop_row.get("crop", "")
        total_qty = float(crop_row.get("qty", 0))
        unit = crop_row.get("unit", "")
        crop_key = crop_name.lower()

        # Split who is willing vs not
        willing_full = [s for s in full_subs
                        if prefs.get(s[0], {}).get(crop_key, "neutral") not in ("dislike", "allergic")]
        willing_half = [s for s in half_subs
                        if prefs.get(s[0], {}).get(crop_key, "neutral") not in ("dislike", "allergic")]

        # Half-share members get 0.5 weight
        full_weight = len(willing_full) * 1.0
        half_weight = len(willing_half) * 0.5
        total_weight = full_weight + half_weight
        if total_weight == 0:
            continue

        per_unit = total_qty / total_weight
        for s in willing_full:
            qty = round(per_unit * 1.0, 2)
            if qty > 0:
                allocations[s[0]]["items"].append({"crop": crop_name, "qty": qty, "unit": unit})
        for s in willing_half:
            qty = round(per_unit * 0.5, 2)
            if qty > 0:
                allocations[s[0]]["items"].append({"crop": crop_name, "qty": qty, "unit": unit})

    return list(allocations.values())


@router.get("/{business_id}/boxbot/runs")
def list_boxbot_runs(business_id: int, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    rows = db.execute(text("""
        SELECT RunID, BusinessID, WeekOf, Status, LabelCount=LEN(AllocationsJSON),
               Notes, CreatedAt, ConfirmedAt
        FROM CSABoxBotRuns WHERE BusinessID=:b ORDER BY CreatedAt DESC
    """), {"b": business_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/{business_id}/boxbot/run")
def run_boxbot(business_id: int, body: dict, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    harvest = body.get("harvest", [])
    week_of = body.get("week_of")
    allocs = _run_boxbot(business_id, harvest, db)
    row = db.execute(text("""
        INSERT INTO CSABoxBotRuns (BusinessID, WeekOf, HarvestJSON, AllocationsJSON, Notes)
        OUTPUT INSERTED.RunID
        VALUES (:b, :wo, :hj, :aj, :notes)
    """), {
        "b":     business_id,
        "wo":    week_of,
        "hj":    json.dumps(harvest),
        "aj":    json.dumps(allocs),
        "notes": body.get("notes", ""),
    }).first()
    db.commit()
    return {"RunID": row[0], "allocations": allocs}


@router.get("/{business_id}/boxbot/runs/{run_id}")
def get_boxbot_run(business_id: int, run_id: int, db: Session = Depends(get_db)):
    row = db.execute(text(
        "SELECT * FROM CSABoxBotRuns WHERE RunID=:id AND BusinessID=:b"
    ), {"id": run_id, "b": business_id}).first()
    if not row:
        raise HTTPException(404, "Run not found")
    d = dict(row._mapping)
    d["harvest"] = json.loads(d.get("HarvestJSON") or "[]")
    d["allocations"] = json.loads(d.get("AllocationsJSON") or "[]")
    return d


@router.patch("/{business_id}/boxbot/runs/{run_id}/confirm")
def confirm_boxbot_run(business_id: int, run_id: int, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE CSABoxBotRuns SET Status='confirmed', ConfirmedAt=GETDATE()
        WHERE RunID=:id AND BusinessID=:b
    """), {"id": run_id, "b": business_id})
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# VACATION HOLDS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{business_id}/vacation-holds")
def list_vacation_holds(business_id: int, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    rows = db.execute(text("""
        SELECT * FROM CSAVacationHolds WHERE BusinessID=:b ORDER BY HoldWeek DESC
    """), {"b": business_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/{business_id}/vacation-holds")
def create_vacation_hold(business_id: int, body: dict, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    row = db.execute(text("""
        INSERT INTO CSAVacationHolds
            (BusinessID, SubscriptionID, PeopleID, MemberName, HoldWeek, Disposition, CreditValue, Notes)
        OUTPUT INSERTED.HoldID
        VALUES (:b, :sub, :p, :name, :hw, :disp, :cv, :notes)
    """), {
        "b":    business_id,
        "sub":  body.get("subscription_id"),
        "p":    body.get("people_id"),
        "name": body.get("member_name", ""),
        "hw":   body.get("hold_week"),
        "disp": body.get("disposition", "donate"),
        "cv":   body.get("credit_value"),
        "notes": body.get("notes", ""),
    }).first()
    db.commit()
    return {"HoldID": row[0]}


@router.patch("/vacation-holds/{hold_id}")
def update_vacation_hold(hold_id: int, body: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE CSAVacationHolds
        SET Disposition=ISNULL(:disp, Disposition),
            AppliedAt=ISNULL(:applied, AppliedAt),
            Notes=ISNULL(:notes, Notes)
        WHERE HoldID=:id
    """), {
        "disp":    body.get("disposition"),
        "applied": body.get("applied_at"),
        "notes":   body.get("notes"),
        "id":      hold_id,
    })
    db.commit()
    return {"ok": True}


@router.delete("/vacation-holds/{hold_id}")
def delete_vacation_hold(hold_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM CSAVacationHolds WHERE HoldID=:id"), {"id": hold_id})
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# PICKUP SITES
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{business_id}/pickup-sites")
def list_pickup_sites(business_id: int, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    sites = db.execute(text("""
        SELECT s.*,
               (SELECT COUNT(*) FROM CSASiteAssignments a WHERE a.SiteID=s.SiteID) AS MemberCount
        FROM CSAPickupSites s
        WHERE s.BusinessID=:b AND s.IsActive=1
        ORDER BY s.SiteName
    """), {"b": business_id}).fetchall()
    return [dict(r._mapping) for r in sites]


@router.post("/{business_id}/pickup-sites")
def create_pickup_site(business_id: int, body: dict, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    row = db.execute(text("""
        INSERT INTO CSAPickupSites
            (BusinessID, SiteName, Address, City, StateProvince,
             ContactName, ContactPhone, ContactEmail, SpecialInstructions)
        OUTPUT INSERTED.SiteID
        VALUES (:b, :nm, :addr, :city, :st, :cn, :cp, :ce, :si)
    """), {
        "b":    business_id,
        "nm":   body.get("site_name", ""),
        "addr": body.get("address", ""),
        "city": body.get("city", ""),
        "st":   body.get("state_province", ""),
        "cn":   body.get("contact_name", ""),
        "cp":   body.get("contact_phone", ""),
        "ce":   body.get("contact_email", ""),
        "si":   body.get("special_instructions", ""),
    }).first()
    db.commit()
    return {"SiteID": row[0]}


@router.patch("/pickup-sites/{site_id}")
def update_pickup_site(site_id: int, body: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE CSAPickupSites SET
            SiteName=ISNULL(:nm, SiteName), Address=ISNULL(:addr, Address),
            City=ISNULL(:city, City), StateProvince=ISNULL(:st, StateProvince),
            ContactName=ISNULL(:cn, ContactName), ContactPhone=ISNULL(:cp, ContactPhone),
            ContactEmail=ISNULL(:ce, ContactEmail),
            SpecialInstructions=ISNULL(:si, SpecialInstructions),
            IsActive=ISNULL(:active, IsActive)
        WHERE SiteID=:id
    """), {
        "nm":   body.get("site_name"),   "addr": body.get("address"),
        "city": body.get("city"),         "st":   body.get("state_province"),
        "cn":   body.get("contact_name"), "cp":   body.get("contact_phone"),
        "ce":   body.get("contact_email"),"si":   body.get("special_instructions"),
        "active": body.get("is_active"),   "id":   site_id,
    })
    db.commit()
    return {"ok": True}


@router.delete("/pickup-sites/{site_id}")
def delete_pickup_site(site_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE CSAPickupSites SET IsActive=0 WHERE SiteID=:id"), {"id": site_id})
    db.commit()
    return {"ok": True}


@router.get("/{business_id}/pickup-sites/{site_id}/assignments")
def list_site_assignments(business_id: int, site_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT * FROM CSASiteAssignments WHERE SiteID=:s AND BusinessID=:b ORDER BY MemberName
    """), {"s": site_id, "b": business_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/{business_id}/pickup-sites/{site_id}/assignments")
def assign_member_to_site(business_id: int, site_id: int, body: dict, db: Session = Depends(get_db)):
    row = db.execute(text("""
        INSERT INTO CSASiteAssignments (SiteID, BusinessID, SubscriptionID, PeopleID, MemberName, SeasonYear)
        OUTPUT INSERTED.AssignmentID
        VALUES (:s, :b, :sub, :p, :name, :yr)
    """), {
        "s": site_id, "b": business_id,
        "sub": body.get("subscription_id"), "p": body.get("people_id"),
        "name": body.get("member_name", ""), "yr": body.get("season_year"),
    }).first()
    db.commit()
    return {"AssignmentID": row[0]}


@router.delete("/pickup-sites/assignments/{assignment_id}")
def remove_site_assignment(assignment_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM CSASiteAssignments WHERE AssignmentID=:id"), {"id": assignment_id})
    db.commit()
    return {"ok": True}


@router.get("/{business_id}/pickup-sites/{site_id}/signin")
def get_signin_sheet(business_id: int, site_id: int, delivery_date: Optional[str] = None, db: Session = Depends(get_db)):
    where = "SiteID=:s AND BusinessID=:b"
    params: dict = {"s": site_id, "b": business_id}
    if delivery_date:
        where += " AND DeliveryDate=:dd"
        params["dd"] = delivery_date
    rows = db.execute(text(f"SELECT * FROM CSASigninLog WHERE {where} ORDER BY MemberName"), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/{business_id}/pickup-sites/{site_id}/signin")
def record_signin(business_id: int, site_id: int, body: dict, db: Session = Depends(get_db)):
    existing = db.execute(text("""
        SELECT SigninID FROM CSASigninLog
        WHERE SiteID=:s AND BusinessID=:b AND SubscriptionID=:sub AND DeliveryDate=:dd
    """), {"s": site_id, "b": business_id,
           "sub": body.get("subscription_id"), "dd": body.get("delivery_date")}).first()
    if existing:
        db.execute(text("""
            UPDATE CSASigninLog SET SignedIn=1, SignInTime=GETDATE(), Notes=ISNULL(:notes, Notes)
            WHERE SigninID=:id
        """), {"notes": body.get("notes"), "id": existing[0]})
    else:
        db.execute(text("""
            INSERT INTO CSASigninLog
                (SiteID, BusinessID, SubscriptionID, PeopleID, MemberName, DeliveryDate, SignedIn, SignInTime, Notes)
            VALUES (:s, :b, :sub, :p, :name, :dd, 1, GETDATE(), :notes)
        """), {
            "s": site_id, "b": business_id,
            "sub": body.get("subscription_id"), "p": body.get("people_id"),
            "name": body.get("member_name", ""), "dd": body.get("delivery_date"),
            "notes": body.get("notes", ""),
        })
    db.commit()
    return {"ok": True}


@router.post("/{business_id}/pickup-sites/{site_id}/signin/seed")
def seed_signin_sheet(business_id: int, site_id: int, body: dict, db: Session = Depends(get_db)):
    """Pre-populate sign-in sheet from site assignments for a delivery date."""
    delivery_date = body.get("delivery_date")
    members = db.execute(text("""
        SELECT SubscriptionID, PeopleID, MemberName FROM CSASiteAssignments
        WHERE SiteID=:s AND BusinessID=:b
    """), {"s": site_id, "b": business_id}).fetchall()
    count = 0
    for m in members:
        exists = db.execute(text("""
            SELECT 1 FROM CSASigninLog WHERE SiteID=:s AND SubscriptionID=:sub AND DeliveryDate=:dd
        """), {"s": site_id, "sub": m[0], "dd": delivery_date}).first()
        if not exists:
            db.execute(text("""
                INSERT INTO CSASigninLog (SiteID, BusinessID, SubscriptionID, PeopleID, MemberName, DeliveryDate, SignedIn)
                VALUES (:s, :b, :sub, :p, :name, :dd, 0)
            """), {"s": site_id, "b": business_id, "sub": m[0], "p": m[1],
                   "name": m[2], "dd": delivery_date})
            count += 1
    db.commit()
    return {"seeded": count}


# ═══════════════════════════════════════════════════════════════════════════════
# CROP PROGRESS FEED
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{business_id}/crop-progress")
def list_crop_progress(business_id: int, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    rows = db.execute(text("""
        SELECT * FROM CSACropProgress WHERE BusinessID=:b ORDER BY PostedAt DESC
    """), {"b": business_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/{business_id}/crop-progress")
def create_crop_progress(business_id: int, body: dict, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    row = db.execute(text("""
        INSERT INTO CSACropProgress (BusinessID, CropName, Caption, PhotoURL, IsPublic, PostedByAgent)
        OUTPUT INSERTED.ProgressID
        VALUES (:b, :crop, :cap, :url, :pub, :agent)
    """), {
        "b":     business_id,
        "crop":  body.get("crop_name", ""),
        "cap":   body.get("caption", ""),
        "url":   body.get("photo_url", ""),
        "pub":   1 if body.get("is_public", True) else 0,
        "agent": body.get("posted_by_agent", ""),
    }).first()
    db.commit()
    return {"ProgressID": row[0]}


@router.delete("/crop-progress/{progress_id}")
def delete_crop_progress(progress_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM CSACropProgress WHERE ProgressID=:id"), {"id": progress_id})
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# NEWSLETTERS — "What's In The Box"
# ═══════════════════════════════════════════════════════════════════════════════

def _build_newsletter_body(harvest: list, business_name: str) -> str:
    items_html = "".join(
        f"<li><strong>{h['crop']}</strong> — {h.get('qty','')} {h.get('unit','')}</li>"
        for h in harvest
    )
    return f"""<h2>What's In Your Box This Week — {business_name}</h2>
<p>Here's what's coming in your share:</p>
<ul>{items_html}</ul>
<p>As always, thank you for being a part of our farm community.
We hope you enjoy this week's harvest!</p>"""


@router.post("/{business_id}/newsletters/preview")
def preview_newsletter(business_id: int, body: dict, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    harvest = body.get("harvest", [])
    biz = db.execute(text("SELECT TOP 1 BusinessName FROM Business WHERE BusinessID=:b"), {"b": business_id}).first()
    biz_name = biz[0] if biz else "Your Farm"
    subject = body.get("subject") or f"What's In Your Box — {biz_name}"
    html_body = body.get("body") or _build_newsletter_body(harvest, biz_name)
    # Count active subscribers
    count = db.execute(text(
        "SELECT COUNT(*) FROM CSASubscriptions WHERE BusinessID=:b AND Status='active'"
    ), {"b": business_id}).scalar() or 0
    return {"subject": subject, "body": html_body, "recipient_count": count, "harvest": harvest}


@router.post("/{business_id}/newsletters/send")
def send_newsletter(business_id: int, body: dict, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    harvest = body.get("harvest", [])
    biz = db.execute(text("SELECT TOP 1 BusinessName FROM Business WHERE BusinessID=:b"), {"b": business_id}).first()
    biz_name = biz[0] if biz else "Your Farm"
    subject = body.get("subject") or f"What's In Your Box — {biz_name}"
    html_body = body.get("body") or _build_newsletter_body(harvest, biz_name)
    count = db.execute(text(
        "SELECT COUNT(*) FROM CSASubscriptions WHERE BusinessID=:b AND Status='active'"
    ), {"b": business_id}).scalar() or 0
    row = db.execute(text("""
        INSERT INTO CSANewsletterSends (BusinessID, Subject, Body, HarvestJSON, RecipientCount, WeekOf)
        OUTPUT INSERTED.SendID
        VALUES (:b, :sub, :body, :hj, :cnt, :wo)
    """), {
        "b":   business_id, "sub":  subject, "body": html_body,
        "hj":  json.dumps(harvest), "cnt":  count, "wo":   body.get("week_of"),
    }).first()
    db.commit()
    return {"SendID": row[0], "recipient_count": count, "subject": subject}


@router.get("/{business_id}/newsletters")
def list_newsletters(business_id: int, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    rows = db.execute(text("""
        SELECT SendID, BusinessID, Subject, RecipientCount, SentAt, WeekOf
        FROM CSANewsletterSends WHERE BusinessID=:b ORDER BY SentAt DESC
    """), {"b": business_id}).fetchall()
    return [dict(r._mapping) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# HARVEST ALLOCATION (Maturity Engine → member counts)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{business_id}/harvest-allocations")
def list_harvest_allocations(business_id: int, week_of: Optional[str] = None, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    where = "BusinessID=:b"
    params: dict = {"b": business_id}
    if week_of:
        where += " AND WeekOf=:wo"
        params["wo"] = week_of
    rows = db.execute(text(
        f"SELECT * FROM CSAHarvestAllocations WHERE {where} ORDER BY WeekOf DESC, CropName"
    ), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/{business_id}/harvest-allocations")
def create_harvest_allocation(business_id: int, body: dict, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    # Auto-compute per-share quantities if not supplied
    estimated = float(body.get("estimated_yield", 0))
    full_count = body.get("total_full_shares") or db.execute(text(
        "SELECT COUNT(*) FROM CSASubscriptions WHERE BusinessID=:b AND Status='active' AND (ShareType IS NULL OR ShareType='full')"
    ), {"b": business_id}).scalar() or 1
    half_count = body.get("total_half_shares") or db.execute(text(
        "SELECT COUNT(*) FROM CSASubscriptions WHERE BusinessID=:b AND Status='active' AND ShareType='half'"
    ), {"b": business_id}).scalar() or 0

    full_qty = body.get("full_share_qty")
    half_qty = body.get("half_share_qty")
    if full_qty is None and estimated > 0:
        total_units = full_count + half_count * 0.5
        per_unit = estimated / total_units if total_units else 0
        full_qty = round(per_unit, 2)
        half_qty = round(per_unit * 0.5, 2)

    row = db.execute(text("""
        INSERT INTO CSAHarvestAllocations
            (BusinessID, WeekOf, CropName, EstimatedYield, YieldUnit,
             FullShareQty, HalfShareQty, AddOnQty,
             TotalFullShares, TotalHalfShares, Notes)
        OUTPUT INSERTED.AllocationID
        VALUES (:b, :wo, :crop, :est, :unit,
                :fq, :hq, :aq,
                :fc, :hc, :notes)
    """), {
        "b":     business_id,
        "wo":    body.get("week_of"),
        "crop":  body.get("crop_name", ""),
        "est":   estimated,
        "unit":  body.get("yield_unit", "lbs"),
        "fq":    full_qty,
        "hq":    half_qty,
        "aq":    body.get("addon_qty", 0),
        "fc":    full_count,
        "hc":    half_count,
        "notes": body.get("notes", ""),
    }).first()
    db.commit()
    return {"AllocationID": row[0], "full_share_qty": full_qty, "half_share_qty": half_qty}


@router.patch("/harvest-allocations/{allocation_id}")
def update_harvest_allocation(allocation_id: int, body: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE CSAHarvestAllocations SET
            EstimatedYield=ISNULL(:est, EstimatedYield),
            FullShareQty=ISNULL(:fq, FullShareQty),
            HalfShareQty=ISNULL(:hq, HalfShareQty),
            AddOnQty=ISNULL(:aq, AddOnQty),
            Notes=ISNULL(:notes, Notes),
            ConfirmedAt=ISNULL(:conf, ConfirmedAt)
        WHERE AllocationID=:id
    """), {
        "est":  body.get("estimated_yield"), "fq": body.get("full_share_qty"),
        "hq":   body.get("half_share_qty"),  "aq": body.get("addon_qty"),
        "notes":body.get("notes"), "conf": body.get("confirmed_at"), "id": allocation_id,
    })
    db.commit()
    return {"ok": True}


@router.delete("/harvest-allocations/{allocation_id}")
def delete_harvest_allocation(allocation_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM CSAHarvestAllocations WHERE AllocationID=:id"), {"id": allocation_id})
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# BOX LABELS
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/{business_id}/box-labels/generate")
def generate_box_labels(business_id: int, body: dict, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    week_of = body.get("week_of")
    # Pull confirmed BoxBot run for this week, or use supplied allocations
    allocs = body.get("allocations")
    if not allocs:
        run = db.execute(text("""
            SELECT TOP 1 AllocationsJSON FROM CSABoxBotRuns
            WHERE BusinessID=:b AND WeekOf=:wo AND Status='confirmed'
            ORDER BY CreatedAt DESC
        """), {"b": business_id, "wo": week_of}).first()
        allocs = json.loads(run[0]) if run else []

    # Pull member add-ons (vacation hold credits, etc.)
    labels = []
    for alloc in allocs:
        sub_id = alloc.get("subscription_id")
        # Get member address from People/Business
        addr_row = db.execute(text("""
            SELECT TOP 1 p.FirstName, p.LastName, p.Address1, p.City, p.StateProvince, p.PostalCode
            FROM People p
            JOIN CSASubscriptions s ON s.PeopleID = p.PeopleID
            WHERE s.SubscriptionID = :sub
        """), {"sub": sub_id}).first()

        label = {
            "subscription_id": sub_id,
            "member_name":     alloc.get("member_name", ""),
            "share_type":      alloc.get("share_type", "full"),
            "items":           alloc.get("items", []),
            "addons":          [],
            "week_of":         week_of,
        }
        if addr_row:
            label["address"] = {
                "line1": addr_row[2] or "",
                "city":  addr_row[3] or "",
                "state": addr_row[4] or "",
                "zip":   addr_row[5] or "",
            }
        labels.append(label)

    row = db.execute(text("""
        INSERT INTO CSABoxLabelRuns (BusinessID, WeekOf, LabelsJSON, LabelCount)
        OUTPUT INSERTED.LabelRunID
        VALUES (:b, :wo, :lj, :cnt)
    """), {
        "b":   business_id, "wo": week_of,
        "lj":  json.dumps(labels), "cnt": len(labels),
    }).first()
    db.commit()
    return {"LabelRunID": row[0], "label_count": len(labels), "labels": labels}


@router.get("/{business_id}/box-labels")
def list_box_label_runs(business_id: int, db: Session = Depends(get_db)):
    _lazy_ensure(db)
    rows = db.execute(text("""
        SELECT LabelRunID, BusinessID, WeekOf, LabelCount, GeneratedAt
        FROM CSABoxLabelRuns WHERE BusinessID=:b ORDER BY GeneratedAt DESC
    """), {"b": business_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/{business_id}/box-labels/{run_id}")
def get_box_label_run(business_id: int, run_id: int, db: Session = Depends(get_db)):
    row = db.execute(text(
        "SELECT * FROM CSABoxLabelRuns WHERE LabelRunID=:id AND BusinessID=:b"
    ), {"id": run_id, "b": business_id}).first()
    if not row:
        raise HTTPException(404, "Label run not found")
    d = dict(row._mapping)
    d["labels"] = json.loads(d.get("LabelsJSON") or "[]")
    return d
