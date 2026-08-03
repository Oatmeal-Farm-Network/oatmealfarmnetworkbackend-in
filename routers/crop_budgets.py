from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional

router = APIRouter(prefix="/api/crop-budgets", tags=["crop_budgets"])

_tables_ready = False


def _ensure_tables(db: Session):
    global _tables_ready
    if _tables_ready:
        return

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'CropBudget')
        CREATE TABLE CropBudget (
            BudgetID        INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL,
            FieldID         INT           NULL,
            FieldName       NVARCHAR(200) NULL,
            CropName        NVARCHAR(200) NOT NULL,
            CropYear        INT           NOT NULL,
            Season          NVARCHAR(50)  NULL,
            PlantedAcres    DECIMAL(10,2) NULL,
            ExpectedYield   DECIMAL(12,2) NULL,
            YieldUnit       NVARCHAR(50)  NULL DEFAULT 'bu',
            ExpectedPrice   DECIMAL(10,4) NULL,
            BudgetedRevenue DECIMAL(14,2) NULL,
            ActualRevenue   DECIMAL(14,2) NULL,
            BudgetedCost    DECIMAL(14,2) NULL,
            ActualCost      DECIMAL(14,2) NULL,
            ActualYield     DECIMAL(12,2) NULL,
            Status          NVARCHAR(20)  NOT NULL DEFAULT 'draft',
            Notes           NVARCHAR(1000) NULL,
            CreatedAt       DATETIME2     DEFAULT GETDATE(),
            UpdatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'CropBudgetLine')
        CREATE TABLE CropBudgetLine (
            LineID      INT IDENTITY PRIMARY KEY,
            BudgetID    INT           NOT NULL,
            BusinessID  INT           NOT NULL,
            Category    NVARCHAR(100) NOT NULL,
            Description NVARCHAR(300) NOT NULL,
            LineType    NVARCHAR(20)  NOT NULL DEFAULT 'expense',
            BudgetedQty DECIMAL(12,3) NULL,
            BudgetedUnit NVARCHAR(50) NULL,
            BudgetedRate DECIMAL(10,4) NULL,
            BudgetedAmt DECIMAL(14,2) NULL,
            ActualQty   DECIMAL(12,3) NULL,
            ActualRate  DECIMAL(10,4) NULL,
            ActualAmt   DECIMAL(14,2) NULL,
            SortOrder   INT           NOT NULL DEFAULT 0,
            CreatedAt   DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'CropBudgetTemplate')
        CREATE TABLE CropBudgetTemplate (
            TemplateID   INT IDENTITY PRIMARY KEY,
            BusinessID   INT           NOT NULL,
            TemplateName NVARCHAR(200) NOT NULL,
            CropName     NVARCHAR(200) NULL,
            Lines        NVARCHAR(MAX) NULL,
            IsShared     BIT           NOT NULL DEFAULT 0,
            CreatedAt    DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.commit()
    _tables_ready = True


# ── Budgets CRUD ──────────────────────────────────────────────────────────────

@router.get("/budgets")
def list_budgets(
    business_id: int = Query(...),
    crop_year: Optional[int] = None,
    field_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    q = """
        SELECT b.BudgetID, b.BusinessID, b.FieldID, b.FieldName, b.CropName,
               b.CropYear, b.Season, b.PlantedAcres, b.ExpectedYield, b.YieldUnit,
               b.ExpectedPrice, b.BudgetedRevenue, b.ActualRevenue,
               b.BudgetedCost, b.ActualCost, b.ActualYield, b.Status, b.Notes,
               b.CreatedAt, b.UpdatedAt,
               (SELECT COUNT(*) FROM CropBudgetLine WHERE BudgetID = b.BudgetID) AS LineCount
        FROM CropBudget b
        WHERE b.BusinessID = :bid
    """
    params: dict = {"bid": business_id}
    if crop_year:
        q += " AND b.CropYear = :yr"
        params["yr"] = crop_year
    if field_id:
        q += " AND b.FieldID = :fid"
        params["fid"] = field_id
    if status:
        q += " AND b.Status = :st"
        params["st"] = status
    q += " ORDER BY b.CropYear DESC, b.CropName"
    rows = db.execute(text(q), params).fetchall()
    return [_budget_row(r) for r in rows]


@router.get("/budgets/{budget_id}")
def get_budget(budget_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    row = db.execute(
        text("""
            SELECT *, (SELECT COUNT(*) FROM CropBudgetLine WHERE BudgetID = b.BudgetID) AS LineCount
            FROM CropBudget b
            WHERE BudgetID = :id AND BusinessID = :bid
        """),
        {"id": budget_id, "bid": business_id},
    ).fetchone()
    if not row:
        raise HTTPException(404, "Budget not found")
    lines = db.execute(
        text("SELECT * FROM CropBudgetLine WHERE BudgetID = :id ORDER BY SortOrder, LineID"),
        {"id": budget_id},
    ).fetchall()
    result = _budget_row(row)
    result["lines"] = [_line_row(l) for l in lines]
    return result


@router.post("/budgets")
def create_budget(payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    if not bid:
        raise HTTPException(400, "business_id required")

    row = db.execute(text("""
        INSERT INTO CropBudget
            (BusinessID, FieldID, FieldName, CropName, CropYear, Season,
             PlantedAcres, ExpectedYield, YieldUnit, ExpectedPrice,
             BudgetedRevenue, BudgetedCost, Status, Notes)
        OUTPUT INSERTED.BudgetID
        VALUES (:bid, :fid, :fname, :crop, :yr, :season,
                :acres, :yield_, :yunit, :price,
                :brev, :bcost, :status, :notes)
    """), {
        "bid":    bid,
        "fid":    payload.get("field_id"),
        "fname":  payload.get("field_name"),
        "crop":   payload.get("crop_name", ""),
        "yr":     payload.get("crop_year"),
        "season": payload.get("season"),
        "acres":  payload.get("planted_acres"),
        "yield_": payload.get("expected_yield"),
        "yunit":  payload.get("yield_unit", "bu"),
        "price":  payload.get("expected_price"),
        "brev":   payload.get("budgeted_revenue"),
        "bcost":  payload.get("budgeted_cost"),
        "status": payload.get("status", "draft"),
        "notes":  payload.get("notes"),
    }).fetchone()
    budget_id = row[0]

    # Insert budget lines if provided
    lines = payload.get("lines", [])
    for i, line in enumerate(lines):
        _insert_line(db, budget_id, bid, line, i)

    db.commit()
    return {"budget_id": budget_id}


@router.put("/budgets/{budget_id}")
def update_budget(budget_id: int, payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    db.execute(text("""
        UPDATE CropBudget SET
            FieldID         = :fid,
            FieldName       = :fname,
            CropName        = :crop,
            CropYear        = :yr,
            Season          = :season,
            PlantedAcres    = :acres,
            ExpectedYield   = :yield_,
            YieldUnit       = :yunit,
            ExpectedPrice   = :price,
            BudgetedRevenue = :brev,
            ActualRevenue   = :arev,
            BudgetedCost    = :bcost,
            ActualCost      = :acost,
            ActualYield     = :ayield,
            Status          = :status,
            Notes           = :notes,
            UpdatedAt       = GETDATE()
        WHERE BudgetID = :id AND BusinessID = :bid
    """), {
        "id":     budget_id,
        "bid":    bid,
        "fid":    payload.get("field_id"),
        "fname":  payload.get("field_name"),
        "crop":   payload.get("crop_name"),
        "yr":     payload.get("crop_year"),
        "season": payload.get("season"),
        "acres":  payload.get("planted_acres"),
        "yield_": payload.get("expected_yield"),
        "yunit":  payload.get("yield_unit"),
        "price":  payload.get("expected_price"),
        "brev":   payload.get("budgeted_revenue"),
        "arev":   payload.get("actual_revenue"),
        "bcost":  payload.get("budgeted_cost"),
        "acost":  payload.get("actual_cost"),
        "ayield": payload.get("actual_yield"),
        "status": payload.get("status"),
        "notes":  payload.get("notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/budgets/{budget_id}")
def delete_budget(budget_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM CropBudgetLine WHERE BudgetID = :id"), {"id": budget_id})
    db.execute(text("DELETE FROM CropBudget WHERE BudgetID = :id AND BusinessID = :bid"),
               {"id": budget_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Budget Lines ──────────────────────────────────────────────────────────────

@router.post("/budgets/{budget_id}/lines")
def add_line(budget_id: int, payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    sort = db.execute(
        text("SELECT ISNULL(MAX(SortOrder), 0) + 1 FROM CropBudgetLine WHERE BudgetID = :id"),
        {"id": budget_id},
    ).scalar()
    _insert_line(db, budget_id, bid, payload, sort)
    _recalc_totals(db, budget_id, bid)
    db.commit()
    return {"ok": True}


@router.put("/lines/{line_id}")
def update_line(line_id: int, payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    budgeted_amt = payload.get("budgeted_amt")
    if budgeted_amt is None and payload.get("budgeted_qty") and payload.get("budgeted_rate"):
        budgeted_amt = float(payload["budgeted_qty"]) * float(payload["budgeted_rate"])
    actual_amt = payload.get("actual_amt")
    if actual_amt is None and payload.get("actual_qty") and payload.get("actual_rate"):
        actual_amt = float(payload["actual_qty"]) * float(payload["actual_rate"])

    db.execute(text("""
        UPDATE CropBudgetLine SET
            Category     = :cat,
            Description  = :desc,
            LineType     = :ltype,
            BudgetedQty  = :bqty,
            BudgetedUnit = :bunit,
            BudgetedRate = :brate,
            BudgetedAmt  = :bamt,
            ActualQty    = :aqty,
            ActualRate   = :arate,
            ActualAmt    = :aamt,
            SortOrder    = :sort
        WHERE LineID = :id
    """), {
        "id":    line_id,
        "cat":   payload.get("category"),
        "desc":  payload.get("description"),
        "ltype": payload.get("line_type", "expense"),
        "bqty":  payload.get("budgeted_qty"),
        "bunit": payload.get("budgeted_unit"),
        "brate": payload.get("budgeted_rate"),
        "bamt":  budgeted_amt,
        "aqty":  payload.get("actual_qty"),
        "arate": payload.get("actual_rate"),
        "aamt":  actual_amt,
        "sort":  payload.get("sort_order", 0),
    })
    line = db.execute(text("SELECT BudgetID, BusinessID FROM CropBudgetLine WHERE LineID = :id"), {"id": line_id}).fetchone()
    if line:
        _recalc_totals(db, line.BudgetID, line.BusinessID)
    db.commit()
    return {"ok": True}


@router.delete("/lines/{line_id}")
def delete_line(line_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    line = db.execute(text("SELECT BudgetID, BusinessID FROM CropBudgetLine WHERE LineID = :id"), {"id": line_id}).fetchone()
    db.execute(text("DELETE FROM CropBudgetLine WHERE LineID = :id"), {"id": line_id})
    if line:
        _recalc_totals(db, line.BudgetID, line.BusinessID)
    db.commit()
    return {"ok": True}


# ── Templates ─────────────────────────────────────────────────────────────────

@router.get("/templates")
def list_templates(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT TemplateID, TemplateName, CropName, IsShared, CreatedAt
        FROM CropBudgetTemplate
        WHERE BusinessID = :bid OR IsShared = 1
        ORDER BY TemplateName
    """), {"bid": business_id}).fetchall()
    return [{"template_id": r.TemplateID, "name": r.TemplateName, "crop_name": r.CropName,
             "is_shared": bool(r.IsShared)} for r in rows]


@router.post("/templates")
def save_template(payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    import json
    bid = payload.get("business_id") or payload.get("BusinessID")
    db.execute(text("""
        INSERT INTO CropBudgetTemplate (BusinessID, TemplateName, CropName, Lines, IsShared)
        VALUES (:bid, :name, :crop, :lines, :shared)
    """), {
        "bid":    bid,
        "name":   payload.get("template_name", ""),
        "crop":   payload.get("crop_name"),
        "lines":  json.dumps(payload.get("lines", [])),
        "shared": 1 if payload.get("is_shared") else 0,
    })
    db.commit()
    return {"ok": True}


# ── Variance Summary ──────────────────────────────────────────────────────────

@router.get("/budgets/{budget_id}/variance")
def budget_variance(budget_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    bud = db.execute(
        text("SELECT * FROM CropBudget WHERE BudgetID = :id AND BusinessID = :bid"),
        {"id": budget_id, "bid": business_id},
    ).fetchone()
    if not bud:
        raise HTTPException(404, "Budget not found")

    lines = db.execute(
        text("SELECT * FROM CropBudgetLine WHERE BudgetID = :id ORDER BY SortOrder"),
        {"id": budget_id},
    ).fetchall()

    budgeted_cost = sum(float(l.BudgetedAmt or 0) for l in lines if l.LineType == "expense")
    actual_cost   = sum(float(l.ActualAmt or 0)   for l in lines if l.LineType == "expense")
    budgeted_rev  = float(bud.BudgetedRevenue or 0)
    actual_rev    = float(bud.ActualRevenue or 0)

    return {
        "budget_id":          budget_id,
        "crop_name":          bud.CropName,
        "crop_year":          bud.CropYear,
        "budgeted_revenue":   budgeted_rev,
        "actual_revenue":     actual_rev,
        "revenue_variance":   actual_rev - budgeted_rev,
        "budgeted_cost":      budgeted_cost,
        "actual_cost":        actual_cost,
        "cost_variance":      actual_cost - budgeted_cost,
        "budgeted_margin":    budgeted_rev - budgeted_cost,
        "actual_margin":      actual_rev - actual_cost,
        "margin_variance":    (actual_rev - actual_cost) - (budgeted_rev - budgeted_cost),
        "by_category": _variance_by_category(lines),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _insert_line(db, budget_id, bid, line: dict, sort: int):
    budgeted_amt = line.get("budgeted_amt")
    if budgeted_amt is None and line.get("budgeted_qty") and line.get("budgeted_rate"):
        budgeted_amt = float(line["budgeted_qty"]) * float(line["budgeted_rate"])
    actual_amt = line.get("actual_amt")
    if actual_amt is None and line.get("actual_qty") and line.get("actual_rate"):
        actual_amt = float(line["actual_qty"]) * float(line["actual_rate"])

    db.execute(text("""
        INSERT INTO CropBudgetLine
            (BudgetID, BusinessID, Category, Description, LineType,
             BudgetedQty, BudgetedUnit, BudgetedRate, BudgetedAmt,
             ActualQty, ActualRate, ActualAmt, SortOrder)
        VALUES (:bid_id, :biz, :cat, :desc, :ltype,
                :bqty, :bunit, :brate, :bamt,
                :aqty, :arate, :aamt, :sort)
    """), {
        "bid_id": budget_id,
        "biz":   bid,
        "cat":   line.get("category", "Other"),
        "desc":  line.get("description", ""),
        "ltype": line.get("line_type", "expense"),
        "bqty":  line.get("budgeted_qty"),
        "bunit": line.get("budgeted_unit"),
        "brate": line.get("budgeted_rate"),
        "bamt":  budgeted_amt,
        "aqty":  line.get("actual_qty"),
        "arate": line.get("actual_rate"),
        "aamt":  actual_amt,
        "sort":  sort,
    })


def _recalc_totals(db, budget_id, bid):
    db.execute(text("""
        UPDATE CropBudget SET
            BudgetedCost = (SELECT ISNULL(SUM(BudgetedAmt), 0) FROM CropBudgetLine
                            WHERE BudgetID = :id AND LineType = 'expense'),
            ActualCost   = (SELECT ISNULL(SUM(ActualAmt), 0) FROM CropBudgetLine
                            WHERE BudgetID = :id AND LineType = 'expense'),
            UpdatedAt    = GETDATE()
        WHERE BudgetID = :id AND BusinessID = :bid
    """), {"id": budget_id, "bid": bid})


def _variance_by_category(lines) -> list:
    cats: dict = {}
    for l in lines:
        cat = l.Category
        if cat not in cats:
            cats[cat] = {"category": cat, "budgeted": 0.0, "actual": 0.0}
        cats[cat]["budgeted"] += float(l.BudgetedAmt or 0)
        cats[cat]["actual"]   += float(l.ActualAmt or 0)
    for c in cats.values():
        c["variance"] = c["actual"] - c["budgeted"]
    return list(cats.values())


def _budget_row(r) -> dict:
    budgeted_rev  = float(r.BudgetedRevenue or 0)
    actual_rev    = float(r.ActualRevenue or 0)
    budgeted_cost = float(r.BudgetedCost or 0)
    actual_cost   = float(r.ActualCost or 0)
    return {
        "budget_id":        r.BudgetID,
        "business_id":      r.BusinessID,
        "field_id":         r.FieldID,
        "field_name":       r.FieldName,
        "crop_name":        r.CropName,
        "crop_year":        r.CropYear,
        "season":           r.Season,
        "planted_acres":    float(r.PlantedAcres) if r.PlantedAcres else None,
        "expected_yield":   float(r.ExpectedYield) if r.ExpectedYield else None,
        "yield_unit":       r.YieldUnit,
        "expected_price":   float(r.ExpectedPrice) if r.ExpectedPrice else None,
        "budgeted_revenue": budgeted_rev,
        "actual_revenue":   actual_rev,
        "budgeted_cost":    budgeted_cost,
        "actual_cost":      actual_cost,
        "actual_yield":     float(r.ActualYield) if r.ActualYield else None,
        "budgeted_margin":  budgeted_rev - budgeted_cost,
        "actual_margin":    actual_rev - actual_cost,
        "status":           r.Status,
        "notes":            r.Notes,
        "line_count":       getattr(r, "LineCount", 0),
        "created_at":       r.CreatedAt.isoformat() if r.CreatedAt else None,
        "updated_at":       r.UpdatedAt.isoformat() if r.UpdatedAt else None,
    }


def _line_row(r) -> dict:
    return {
        "line_id":      r.LineID,
        "budget_id":    r.BudgetID,
        "category":     r.Category,
        "description":  r.Description,
        "line_type":    r.LineType,
        "budgeted_qty":  float(r.BudgetedQty) if r.BudgetedQty is not None else None,
        "budgeted_unit": r.BudgetedUnit,
        "budgeted_rate": float(r.BudgetedRate) if r.BudgetedRate is not None else None,
        "budgeted_amt":  float(r.BudgetedAmt) if r.BudgetedAmt is not None else None,
        "actual_qty":   float(r.ActualQty) if r.ActualQty is not None else None,
        "actual_rate":  float(r.ActualRate) if r.ActualRate is not None else None,
        "actual_amt":   float(r.ActualAmt) if r.ActualAmt is not None else None,
        "sort_order":   r.SortOrder,
    }
