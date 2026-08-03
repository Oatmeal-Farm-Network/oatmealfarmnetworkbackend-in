from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from pydantic import BaseModel
from typing import Optional
from datetime import date

router = APIRouter(prefix="/api/nutrients", tags=["nutrients"])

CREATE_TABLES = """
IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'NutrientPlan')
CREATE TABLE NutrientPlan (
    PlanID       INT IDENTITY PRIMARY KEY,
    BusinessID   INT NOT NULL,
    FieldID      INT NULL,
    FieldName    NVARCHAR(200) NULL,
    CropName     NVARCHAR(200) NULL,
    Season       NVARCHAR(10) NOT NULL,
    PlannedN_kg_ha  DECIMAL(10,2) NULL,
    PlannedP_kg_ha  DECIMAL(10,2) NULL,
    PlannedK_kg_ha  DECIMAL(10,2) NULL,
    PlannedS_kg_ha  DECIMAL(10,2) NULL,
    Notes        NVARCHAR(2000) NULL,
    CreatedAt    DATETIME2 DEFAULT GETDATE()
);
IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'NutrientApplication')
CREATE TABLE NutrientApplication (
    AppID           INT IDENTITY PRIMARY KEY,
    PlanID          INT NULL,
    BusinessID      INT NOT NULL,
    FieldID         INT NULL,
    FieldName       NVARCHAR(200) NULL,
    AppDate         DATE NOT NULL,
    ProductName     NVARCHAR(300) NOT NULL,
    ProductType     NVARCHAR(100) NULL,
    NRate_kg_ha     DECIMAL(10,3) NULL,
    PRate_kg_ha     DECIMAL(10,3) NULL,
    KRate_kg_ha     DECIMAL(10,3) NULL,
    SRate_kg_ha     DECIMAL(10,3) NULL,
    ApplicationMethod NVARCHAR(100) NULL,
    AreaHa          DECIMAL(10,2) NULL,
    CostPerHa       DECIMAL(10,2) NULL,
    TotalCost       DECIMAL(12,2) NULL,
    Operator        NVARCHAR(200) NULL,
    Notes           NVARCHAR(2000) NULL,
    LinkedActivityID INT NULL,
    CreatedAt       DATETIME2 DEFAULT GETDATE()
);
"""


def _ensure_tables(db):
    try:
        for stmt in CREATE_TABLES.strip().split(";\nIF NOT EXISTS"):
            s = stmt if stmt.startswith("IF") else "IF NOT EXISTS" + stmt
            db.execute(text(s))
        db.commit()
    except Exception:
        db.rollback()


class PlanIn(BaseModel):
    field_id: Optional[int] = None
    field_name: Optional[str] = None
    crop_name: Optional[str] = None
    season: str
    planned_n: Optional[float] = None
    planned_p: Optional[float] = None
    planned_k: Optional[float] = None
    planned_s: Optional[float] = None
    notes: Optional[str] = None


class AppIn(BaseModel):
    plan_id: Optional[int] = None
    field_id: Optional[int] = None
    field_name: Optional[str] = None
    app_date: date
    product_name: str
    product_type: Optional[str] = None
    n_rate: Optional[float] = None
    p_rate: Optional[float] = None
    k_rate: Optional[float] = None
    s_rate: Optional[float] = None
    application_method: Optional[str] = None
    area_ha: Optional[float] = None
    cost_per_ha: Optional[float] = None
    total_cost: Optional[float] = None
    operator: Optional[str] = None
    notes: Optional[str] = None
    linked_activity_id: Optional[int] = None


@router.post("/plans")
def create_plan(body: PlanIn, business_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    row = db.execute(text("""
        INSERT INTO NutrientPlan (BusinessID, FieldID, FieldName, CropName, Season,
            PlannedN_kg_ha, PlannedP_kg_ha, PlannedK_kg_ha, PlannedS_kg_ha, Notes)
        OUTPUT INSERTED.PlanID
        VALUES (:bid, :fid, :fn, :cn, :season, :n, :p, :k, :s, :notes)
    """), {"bid": business_id, "fid": body.field_id, "fn": body.field_name,
           "cn": body.crop_name, "season": body.season,
           "n": body.planned_n, "p": body.planned_p, "k": body.planned_k,
           "s": body.planned_s, "notes": body.notes}).fetchone()
    db.commit()
    return {"plan_id": row[0]}


@router.get("/plans")
def list_plans(business_id: int, season: Optional[str] = None, field_id: Optional[int] = None,
               db: Session = Depends(get_db)):
    _ensure_tables(db)
    where = "WHERE BusinessID = :bid"
    params: dict = {"bid": business_id}
    if season:
        where += " AND Season = :season"; params["season"] = season
    if field_id:
        where += " AND FieldID = :fid"; params["fid"] = field_id
    rows = db.execute(text(f"""
        SELECT PlanID, FieldID, FieldName, CropName, Season,
               PlannedN_kg_ha, PlannedP_kg_ha, PlannedK_kg_ha, PlannedS_kg_ha, Notes, CreatedAt
        FROM NutrientPlan {where} ORDER BY Season DESC, FieldName
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: int, business_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM NutrientPlan WHERE PlanID = :pid AND BusinessID = :bid"),
               {"pid": plan_id, "bid": business_id})
    db.commit()
    return {"ok": True}


@router.post("/applications")
def create_application(body: AppIn, business_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    tc = body.total_cost
    if tc is None and body.cost_per_ha and body.area_ha:
        tc = body.cost_per_ha * body.area_ha
    row = db.execute(text("""
        INSERT INTO NutrientApplication (PlanID, BusinessID, FieldID, FieldName, AppDate,
            ProductName, ProductType, NRate_kg_ha, PRate_kg_ha, KRate_kg_ha, SRate_kg_ha,
            ApplicationMethod, AreaHa, CostPerHa, TotalCost, Operator, Notes, LinkedActivityID)
        OUTPUT INSERTED.AppID
        VALUES (:pid, :bid, :fid, :fn, :dt, :prod, :ptype,
                :n, :p, :k, :s, :method, :area, :cpha, :tc, :op, :notes, :lact)
    """), {"pid": body.plan_id, "bid": business_id, "fid": body.field_id, "fn": body.field_name,
           "dt": body.app_date, "prod": body.product_name, "ptype": body.product_type,
           "n": body.n_rate, "p": body.p_rate, "k": body.k_rate, "s": body.s_rate,
           "method": body.application_method, "area": body.area_ha, "cpha": body.cost_per_ha,
           "tc": tc, "op": body.operator, "notes": body.notes,
           "lact": body.linked_activity_id}).fetchone()
    db.commit()
    return {"app_id": row[0]}


@router.get("/applications")
def list_applications(business_id: int, field_id: Optional[int] = None,
                      season: Optional[str] = None, db: Session = Depends(get_db)):
    _ensure_tables(db)
    where = "WHERE BusinessID = :bid"
    params: dict = {"bid": business_id}
    if field_id:
        where += " AND FieldID = :fid"; params["fid"] = field_id
    if season:
        where += " AND YEAR(AppDate) = :yr"; params["yr"] = int(season)
    rows = db.execute(text(f"""
        SELECT AppID, PlanID, FieldID, FieldName, AppDate, ProductName, ProductType,
               NRate_kg_ha, PRate_kg_ha, KRate_kg_ha, SRate_kg_ha,
               ApplicationMethod, AreaHa, CostPerHa, TotalCost, Operator, Notes, CreatedAt
        FROM NutrientApplication {where} ORDER BY AppDate DESC
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.delete("/applications/{app_id}")
def delete_application(app_id: int, business_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM NutrientApplication WHERE AppID = :aid AND BusinessID = :bid"),
               {"aid": app_id, "bid": business_id})
    db.commit()
    return {"ok": True}


@router.get("/budget")
def nutrient_budget(business_id: int, field_id: int, season: Optional[str] = None,
                    db: Session = Depends(get_db)):
    """Applied vs planned N/P/K/S for a field, with soil test recommendations layered in."""
    _ensure_tables(db)
    yr = season or str(__import__("datetime").date.today().year)

    # Plan for this field/season
    plan = db.execute(text("""
        SELECT TOP 1 PlanID, PlannedN_kg_ha, PlannedP_kg_ha, PlannedK_kg_ha, PlannedS_kg_ha, CropName
        FROM NutrientPlan
        WHERE BusinessID = :bid AND FieldID = :fid AND Season = :yr
        ORDER BY PlanID DESC
    """), {"bid": business_id, "fid": field_id, "yr": yr}).fetchone()

    # Applied totals
    app_row = db.execute(text("""
        SELECT SUM(NRate_kg_ha), SUM(PRate_kg_ha), SUM(KRate_kg_ha), SUM(SRate_kg_ha), COUNT(*)
        FROM NutrientApplication
        WHERE BusinessID = :bid AND FieldID = :fid AND YEAR(AppDate) = :yr
    """), {"bid": business_id, "fid": field_id, "yr": int(yr)}).fetchone()

    # Latest soil test recommendations (low-rated nutrients)
    try:
        soil_row = db.execute(text("""
            SELECT TOP 1 TestID FROM SoilTest
            WHERE BusinessID = :bid AND FieldID = :fid
            ORDER BY TestDate DESC
        """), {"bid": business_id, "fid": field_id}).fetchone()
        if soil_row:
            deficient = db.execute(text("""
                SELECT Nutrient, Value, Unit, Rating FROM SoilTestResult
                WHERE TestID = :tid AND Rating IN ('Low','Very Low')
            """), {"tid": soil_row[0]}).fetchall()
            recommendations = [{"nutrient": r[0], "value": r[1], "unit": r[2], "rating": r[3]}
                                for r in deficient]
        else:
            recommendations = []
    except Exception:
        recommendations = []

    return {
        "field_id": field_id,
        "season": yr,
        "plan": dict(plan._mapping) if plan else None,
        "applied": {
            "N_kg_ha": float(app_row[0] or 0), "P_kg_ha": float(app_row[1] or 0),
            "K_kg_ha": float(app_row[2] or 0), "S_kg_ha": float(app_row[3] or 0),
            "application_count": app_row[4] or 0,
        } if app_row else None,
        "soil_deficiencies": recommendations,
    }
