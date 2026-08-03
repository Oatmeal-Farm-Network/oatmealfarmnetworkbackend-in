from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional

router = APIRouter(prefix="/api/farm-pl", tags=["farm_pl"])


def _q(db, sql, params):
    try:
        return db.execute(text(sql), params).fetchall()
    except Exception:
        return []


def _s(db, sql, params, default=0.0):
    try:
        v = db.execute(text(sql), params).scalar()
        return float(v) if v is not None else default
    except Exception:
        return default


@router.get("/summary")
def pl_summary(business_id: int, season: Optional[str] = None, db: Session = Depends(get_db)):
    """Whole-farm P&L summary for a season, aggregating all data sources."""
    bid = business_id
    yr = season or str(__import__("datetime").date.today().year)
    yr_int = int(yr)

    # ── Revenue ────────────────────────────────────────────────────────────────
    # YieldRecord actual revenue
    yield_rev = _s(db, """
        SELECT SUM(GrossRevenue) FROM YieldRecord
        WHERE BusinessID = :bid AND Season = :yr AND GrossRevenue IS NOT NULL
    """, {"bid": bid, "yr": yr})

    # CashFlowEntry income
    cf_income = _s(db, """
        SELECT SUM(Amount) FROM CashFlowEntry
        WHERE BusinessID = :bid AND EntryType = 'income'
          AND YEAR(EntryDate) = :yr
    """, {"bid": bid, "yr": yr_int})

    # ScaleTicket net income (if table exists)
    scale_rev = _s(db, """
        SELECT SUM(NetAmount) FROM ScaleTicket
        WHERE BusinessID = :bid AND YEAR(TicketDate) = :yr AND NetAmount IS NOT NULL
    """, {"bid": bid, "yr": yr_int})

    total_revenue = yield_rev + cf_income + scale_rev

    # ── Costs ──────────────────────────────────────────────────────────────────
    # YieldRecord variable cost
    yield_cost = _s(db, """
        SELECT SUM(TotalVariableCost) FROM YieldRecord
        WHERE BusinessID = :bid AND Season = :yr AND TotalVariableCost IS NOT NULL
    """, {"bid": bid, "yr": yr})

    # CashFlowEntry expenses
    cf_expense = _s(db, """
        SELECT SUM(Amount) FROM CashFlowEntry
        WHERE BusinessID = :bid AND EntryType = 'expense'
          AND YEAR(EntryDate) = :yr
    """, {"bid": bid, "yr": yr_int})

    # FieldActivity costs
    activity_cost = _s(db, """
        SELECT SUM(CostTotal) FROM FieldActivity
        WHERE BusinessID = :bid AND YEAR(ActivityDate) = :yr AND CostTotal IS NOT NULL
    """, {"bid": bid, "yr": yr_int})

    # NutrientApplication costs
    nutrient_cost = _s(db, """
        SELECT SUM(TotalCost) FROM NutrientApplication
        WHERE BusinessID = :bid AND YEAR(AppDate) = :yr AND TotalCost IS NOT NULL
    """, {"bid": bid, "yr": yr_int})

    total_cost = yield_cost + cf_expense + activity_cost + nutrient_cost
    gross_margin = total_revenue - total_cost

    # Area (for per-ha calc)
    area_ha = _s(db, """
        SELECT SUM(AreaHa) FROM YieldRecord
        WHERE BusinessID = :bid AND Season = :yr AND AreaHa IS NOT NULL
    """, {"bid": bid, "yr": yr})

    return {
        "season": yr,
        "revenue": {
            "yield_records": yield_rev,
            "cash_flow_income": cf_income,
            "scale_tickets": scale_rev,
            "total": total_revenue,
        },
        "costs": {
            "yield_variable_costs": yield_cost,
            "cash_flow_expenses": cf_expense,
            "field_activity": activity_cost,
            "nutrients": nutrient_cost,
            "total": total_cost,
        },
        "gross_margin": gross_margin,
        "total_area_ha": area_ha,
        "gross_margin_per_ha": round(gross_margin / area_ha, 2) if area_ha else None,
    }


@router.get("/by-crop")
def pl_by_crop(business_id: int, season: Optional[str] = None, db: Session = Depends(get_db)):
    """P&L breakdown per crop for the season."""
    bid = business_id
    yr = season or str(__import__("datetime").date.today().year)

    rows = _q(db, """
        SELECT CropName,
               SUM(AreaHa)          as area_ha,
               SUM(ActualYieldTonnes) as yield_tonnes,
               SUM(GrossRevenue)    as revenue,
               SUM(TotalVariableCost) as variable_cost,
               AVG(GrossMarginPerHa)  as avg_margin_per_ha,
               COUNT(*)             as field_count
        FROM YieldRecord
        WHERE BusinessID = :bid AND Season = :yr
        GROUP BY CropName
        ORDER BY revenue DESC
    """, {"bid": bid, "yr": yr})

    result = []
    for r in rows:
        rev = float(r[3] or 0)
        cost = float(r[4] or 0)
        result.append({
            "crop_name": r[0],
            "area_ha": float(r[1] or 0),
            "yield_tonnes": float(r[2] or 0),
            "revenue": rev,
            "variable_cost": cost,
            "gross_margin": rev - cost,
            "avg_margin_per_ha": float(r[5] or 0),
            "field_count": r[6],
        })
    return result


@router.get("/by-field")
def pl_by_field(business_id: int, season: Optional[str] = None, db: Session = Depends(get_db)):
    """P&L breakdown per field for the season."""
    bid = business_id
    yr = season or str(__import__("datetime").date.today().year)
    yr_int = int(yr)

    yield_rows = _q(db, """
        SELECT FieldID, FieldName, CropName,
               SUM(AreaHa)            as area_ha,
               SUM(GrossRevenue)      as revenue,
               SUM(TotalVariableCost) as variable_cost,
               SUM(ActualYieldTonnes) as yield_tonnes,
               AVG(GrossMarginPerHa)  as margin_per_ha
        FROM YieldRecord
        WHERE BusinessID = :bid AND Season = :yr AND FieldID IS NOT NULL
        GROUP BY FieldID, FieldName, CropName
    """, {"bid": bid, "yr": yr})

    field_map = {}
    for r in yield_rows:
        fid = r[0]
        if fid not in field_map:
            field_map[fid] = {"field_id": fid, "field_name": r[1], "crops": [],
                               "revenue": 0, "variable_cost": 0,
                               "activity_cost": 0, "area_ha": 0}
        rev = float(r[4] or 0)
        vc = float(r[5] or 0)
        field_map[fid]["crops"].append({
            "crop_name": r[2], "area_ha": float(r[3] or 0),
            "revenue": rev, "variable_cost": vc,
            "yield_tonnes": float(r[6] or 0), "margin_per_ha": float(r[7] or 0),
        })
        field_map[fid]["revenue"] += rev
        field_map[fid]["variable_cost"] += vc
        field_map[fid]["area_ha"] += float(r[3] or 0)

    # Overlay field activity costs
    act_rows = _q(db, """
        SELECT FieldID, SUM(CostTotal) FROM FieldActivity
        WHERE BusinessID = :bid AND YEAR(ActivityDate) = :yr
          AND FieldID IS NOT NULL AND CostTotal IS NOT NULL
        GROUP BY FieldID
    """, {"bid": bid, "yr": yr_int})
    for r in act_rows:
        if r[0] in field_map:
            field_map[r[0]]["activity_cost"] = float(r[1] or 0)

    result = []
    for fdata in field_map.values():
        total_cost = fdata["variable_cost"] + fdata["activity_cost"]
        gm = fdata["revenue"] - total_cost
        fdata["total_cost"] = total_cost
        fdata["gross_margin"] = gm
        fdata["gross_margin_per_ha"] = round(gm / fdata["area_ha"], 2) if fdata["area_ha"] else None
        result.append(fdata)

    result.sort(key=lambda x: x["revenue"], reverse=True)
    return result


@router.get("/seasons")
def available_seasons(business_id: int, db: Session = Depends(get_db)):
    """Seasons with yield data."""
    rows = _q(db, """
        SELECT DISTINCT Season FROM YieldRecord WHERE BusinessID = :bid ORDER BY Season DESC
    """, {"bid": business_id})
    return [r[0] for r in rows]
