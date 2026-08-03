from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/yield-records", tags=["yield_records"])
_ddl_done = False


def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cur = db.cursor()
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='YieldRecord')
    CREATE TABLE YieldRecord (
        YieldID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        Season NVARCHAR(20) NOT NULL,
        FieldID NVARCHAR(80),
        FieldName NVARCHAR(120),
        CropName NVARCHAR(100) NOT NULL,
        VarietyName NVARCHAR(100),
        AreaHa DECIMAL(10,4),
        PlantedDate DATE,
        HarvestStartDate DATE,
        HarvestEndDate DATE,
        BudgetedYieldTonnesHa DECIMAL(10,4),
        ActualYieldTonnes DECIMAL(12,4),
        ActualYieldTonnesHa DECIMAL(10,4),
        Grade1Pct DECIMAL(6,2),
        Grade2Pct DECIMAL(6,2),
        RejectPct DECIMAL(6,2),
        AverageGradePct DECIMAL(6,2),
        PricePerTonne DECIMAL(10,4),
        GrossRevenue DECIMAL(14,2),
        TotalVariableCost DECIMAL(14,2),
        GrossMarginPerHa DECIMAL(14,2),
        CropBudgetID INT,
        ScaleTicketRef NVARCHAR(200),
        QualityNotes NVARCHAR(1000),
        Notes NVARCHAR(1000),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    db.commit()
    _ddl_done = True


class YieldIn(BaseModel):
    season: str
    field_id: Optional[str] = None
    field_name: Optional[str] = None
    crop_name: str
    variety_name: Optional[str] = None
    area_ha: Optional[float] = None
    planted_date: Optional[date] = None
    harvest_start_date: Optional[date] = None
    harvest_end_date: Optional[date] = None
    budgeted_yield_tonnes_ha: Optional[float] = None
    actual_yield_tonnes: Optional[float] = None
    actual_yield_tonnes_ha: Optional[float] = None
    grade1_pct: Optional[float] = None
    grade2_pct: Optional[float] = None
    reject_pct: Optional[float] = None
    average_grade_pct: Optional[float] = None
    price_per_tonne: Optional[float] = None
    gross_revenue: Optional[float] = None
    total_variable_cost: Optional[float] = None
    gross_margin_per_ha: Optional[float] = None
    crop_budget_id: Optional[int] = None
    scale_ticket_ref: Optional[str] = None
    quality_notes: Optional[str] = None
    notes: Optional[str] = None


@router.post("/records", status_code=201)
def create_record(body: YieldIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    # Auto-compute tonnes/ha if not provided
    actual_tpha = body.actual_yield_tonnes_ha
    if actual_tpha is None and body.actual_yield_tonnes and body.area_ha:
        actual_tpha = round(body.actual_yield_tonnes / body.area_ha, 4)
    cur.execute("""
        INSERT INTO YieldRecord
            (BusinessID, Season, FieldID, FieldName, CropName, VarietyName, AreaHa,
             PlantedDate, HarvestStartDate, HarvestEndDate, BudgetedYieldTonnesHa,
             ActualYieldTonnes, ActualYieldTonnesHa, Grade1Pct, Grade2Pct, RejectPct,
             AverageGradePct, PricePerTonne, GrossRevenue, TotalVariableCost,
             GrossMarginPerHa, CropBudgetID, ScaleTicketRef, QualityNotes, Notes)
        OUTPUT INSERTED.YieldID VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [bid, body.season, body.field_id, body.field_name, body.crop_name,
          body.variety_name, body.area_ha,
          str(body.planted_date) if body.planted_date else None,
          str(body.harvest_start_date) if body.harvest_start_date else None,
          str(body.harvest_end_date) if body.harvest_end_date else None,
          body.budgeted_yield_tonnes_ha, body.actual_yield_tonnes, actual_tpha,
          body.grade1_pct, body.grade2_pct, body.reject_pct, body.average_grade_pct,
          body.price_per_tonne, body.gross_revenue, body.total_variable_cost,
          body.gross_margin_per_ha, body.crop_budget_id, body.scale_ticket_ref,
          body.quality_notes, body.notes])
    yid = cur.fetchone()[0]
    db.commit()
    return {"yield_id": yid}


@router.get("/records")
def list_records(
    season: Optional[str] = None,
    field_id: Optional[str] = None,
    crop_name: Optional[str] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    filters = ["BusinessID=?"]
    params: list = [bid]
    if season:
        filters.append("Season=?"); params.append(season)
    if field_id:
        filters.append("FieldID=?"); params.append(field_id)
    if crop_name:
        filters.append("CropName=?"); params.append(crop_name)
    cur.execute(f"""
        SELECT * FROM YieldRecord WHERE {' AND '.join(filters)}
        ORDER BY Season DESC, HarvestStartDate DESC
    """, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/vs-budget")
def vs_budget(season: Optional[str] = None, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    """Actual yield vs crop budget target per field/crop."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    year = season or str(datetime.utcnow().year)

    # Yield records for season
    cur.execute("""
        SELECT FieldName, CropName, AreaHa, BudgetedYieldTonnesHa, ActualYieldTonnes,
               ActualYieldTonnesHa, GrossRevenue, TotalVariableCost, GrossMarginPerHa,
               CropBudgetID, Season, HarvestStartDate
        FROM YieldRecord WHERE BusinessID=? AND Season=?
        ORDER BY FieldName, CropName
    """, [bid, year])
    cols = [c[0] for c in cur.description]
    records = [dict(zip(cols, r)) for r in cur.fetchall()]

    # Join in budget data where linked
    for r in records:
        budgeted_tpha = r.get("BudgetedYieldTonnesHa")
        actual_tpha = r.get("ActualYieldTonnesHa")
        # Pull from CropBudget if not on record directly
        if budgeted_tpha is None and r.get("CropBudgetID"):
            try:
                cur.execute("SELECT PlannedYieldTonnesHa, TotalVariableCost FROM CropBudget WHERE BudgetID=?", [r["CropBudgetID"]])
                brow = cur.fetchone()
                if brow:
                    budgeted_tpha = float(brow[0] or 0)
            except Exception:
                pass
        r["budgeted_yield_tonnes_ha"] = float(budgeted_tpha or 0)
        r["actual_yield_tonnes_ha"] = float(actual_tpha or 0)
        if budgeted_tpha and actual_tpha:
            r["variance_pct"] = round((float(actual_tpha) - float(budgeted_tpha)) / float(budgeted_tpha) * 100, 1)
        else:
            r["variance_pct"] = None

    return {"season": year, "records": records}


@router.get("/season-summary")
def season_summary(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    """Totals by crop and season."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT Season, CropName,
               COUNT(*) AS Fields,
               SUM(ISNULL(AreaHa,0)) AS TotalAreaHa,
               SUM(ISNULL(ActualYieldTonnes,0)) AS TotalTonnes,
               CASE WHEN SUM(ISNULL(AreaHa,0))>0
                    THEN ROUND(SUM(ISNULL(ActualYieldTonnes,0))/SUM(ISNULL(AreaHa,0)),3)
                    ELSE NULL END AS AvgTonnesHa,
               SUM(ISNULL(GrossRevenue,0)) AS TotalRevenue,
               SUM(ISNULL(TotalVariableCost,0)) AS TotalVariableCost
        FROM YieldRecord WHERE BusinessID=?
        GROUP BY Season, CropName
        ORDER BY Season DESC, TotalTonnes DESC
    """, [bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.delete("/records/{yield_id}")
def delete_record(yield_id: int, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("DELETE FROM YieldRecord WHERE YieldID=? AND BusinessID=?", [yield_id, bid])
    db.commit()
    return {"ok": True}
