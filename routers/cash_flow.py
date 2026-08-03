from fastapi import APIRouter, Depends
from typing import Optional
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/cash-flow", tags=["cash_flow"])
_ddl_done = False


def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cur = db.cursor()
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CashFlowEntry')
    CREATE TABLE CashFlowEntry (
        EntryID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        EntryDate DATE NOT NULL,
        Category NVARCHAR(80) NOT NULL,
        Description NVARCHAR(300),
        Amount DECIMAL(14,2) NOT NULL,
        EntryType NVARCHAR(10) NOT NULL DEFAULT 'actual',
        SourceTable NVARCHAR(60),
        SourceID INT,
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    db.commit()
    _ddl_done = True


def _month_key(d) -> str:
    if hasattr(d, 'year'):
        return f"{d.year}-{d.month:02d}"
    return str(d)[:7]


@router.get("/forecast")
def forecast(
    months: int = 12,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    """
    Roll up actuals (last 6m) + projections (next N months) from:
      - Scale tickets (actual revenue)
      - Forward contracts (committed future revenue)
      - Crop budgets (projected expenses)
      - Manual cash flow entries
    Returns month-by-month inflow/outflow/net.
    """
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    months = min(max(months, 3), 24)
    today = date.today()
    start = (today.replace(day=1) - relativedelta(months=6))
    result: dict = {}

    def bucket(month_str, inflow=0.0, outflow=0.0, label="", type_="actual"):
        if month_str not in result:
            result[month_str] = {"month": month_str, "inflow": 0.0, "outflow": 0.0, "items": []}
        result[month_str]["inflow"] += inflow
        result[month_str]["outflow"] += outflow
        if label:
            result[month_str]["items"].append({"label": label, "amount": inflow - outflow, "type": type_})

    # ── Scale tickets (actual revenue) ──────────────────────────────────────
    try:
        cur.execute("""
            SELECT CAST(YEAR(TicketDate) AS NVARCHAR) + '-' + RIGHT('0'+CAST(MONTH(TicketDate) AS NVARCHAR),2) AS Month,
                   SUM(ROUND(FinalNetKg/1000 * ISNULL(PricePerTonne,0),2)) AS Revenue
            FROM ScaleTicket
            WHERE BusinessID=? AND TicketDate >= ?
            GROUP BY YEAR(TicketDate), MONTH(TicketDate)
        """, [bid, str(start)])
        for row in cur.fetchall():
            bucket(row[0], inflow=float(row[1] or 0), label="Grain Sales", type_="actual")
    except Exception:
        pass

    # ── Forward contracts (committed future revenue) ────────────────────────
    try:
        cur.execute("""
            SELECT DeliveryPeriodEnd, ContractQtyTonnes, PricePerTonne, CommodityName,
                   ISNULL((SELECT SUM(QuantityKg)/1000 FROM ContractDelivery WHERE ContractID=fc.ContractID),0) AS DeliveredTonnes
            FROM ForwardContract fc
            WHERE BusinessID=? AND Status NOT IN ('cancelled','filled')
              AND DeliveryPeriodEnd >= ?
        """, [bid, str(today)])
        for row in cur.fetchall():
            end_date, qty, price, commodity, delivered = row
            remaining = max(float(qty or 0) - float(delivered or 0), 0)
            projected_rev = round(remaining * float(price or 0), 2)
            if projected_rev > 0 and end_date:
                m = _month_key(end_date)
                bucket(m, inflow=projected_rev, label=f"{commodity} Contract", type_="projected")
    except Exception:
        pass

    # ── Crop budgets (projected expenses) ───────────────────────────────────
    try:
        cur.execute("""
            SELECT PlannedPlantingDate, TotalVariableCost, TotalFixedCost, CropName
            FROM CropBudget
            WHERE BusinessID=? AND PlannedPlantingDate >= ? AND Status='approved'
        """, [bid, str(start)])
        for row in cur.fetchall():
            planting, var_cost, fix_cost, crop = row
            total_expense = float(var_cost or 0) + float(fix_cost or 0)
            if total_expense > 0 and planting:
                m = _month_key(planting)
                bucket(m, outflow=total_expense, label=f"{crop} Budget", type_="projected")
    except Exception:
        pass

    # ── Manual cash flow entries ─────────────────────────────────────────────
    try:
        cur.execute("""
            SELECT CAST(YEAR(EntryDate) AS NVARCHAR) + '-' + RIGHT('0'+CAST(MONTH(EntryDate) AS NVARCHAR),2) AS Month,
                   Category, Description, Amount, EntryType
            FROM CashFlowEntry WHERE BusinessID=? AND EntryDate >= ?
            ORDER BY EntryDate
        """, [bid, str(start)])
        for row in cur.fetchall():
            m, cat, desc, amount, etype = row
            amt = float(amount or 0)
            if amt >= 0:
                bucket(m, inflow=amt, label=f"{cat}: {desc or ''}", type_=etype)
            else:
                bucket(m, outflow=abs(amt), label=f"{cat}: {desc or ''}", type_=etype)
    except Exception:
        pass

    # Ensure all months in window are present
    for i in range(-6, months + 1):
        m = (today.replace(day=1) + relativedelta(months=i)).strftime("%Y-%m")
        if m not in result:
            result[m] = {"month": m, "inflow": 0.0, "outflow": 0.0, "items": []}

    months_list = sorted(result.values(), key=lambda x: x["month"])
    running = 0.0
    for m in months_list:
        m["net"] = round(m["inflow"] - m["outflow"], 2)
        running += m["net"]
        m["running_balance"] = round(running, 2)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "months": months_list,
        "summary": {
            "total_inflow": round(sum(m["inflow"] for m in months_list), 2),
            "total_outflow": round(sum(m["outflow"] for m in months_list), 2),
            "net": round(sum(m["net"] for m in months_list), 2),
        }
    }


@router.get("/entries")
def list_entries(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    f = from_date or date(date.today().year, 1, 1)
    t = to_date or date.today()
    cur.execute("SELECT * FROM CashFlowEntry WHERE BusinessID=? AND EntryDate BETWEEN ? AND ? ORDER BY EntryDate DESC",
                [bid, str(f), str(t)])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


from pydantic import BaseModel

class EntryIn(BaseModel):
    entry_date: date
    category: str
    description: Optional[str] = None
    amount: float
    entry_type: str = "actual"


@router.post("/entries", status_code=201)
def create_entry(body: EntryIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        INSERT INTO CashFlowEntry (BusinessID,EntryDate,Category,Description,Amount,EntryType)
        OUTPUT INSERTED.EntryID VALUES (?,?,?,?,?,?)
    """, [bid, str(body.entry_date), body.category, body.description, body.amount, body.entry_type])
    eid = cur.fetchone()[0]
    db.commit()
    return {"entry_id": eid}


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("DELETE FROM CashFlowEntry WHERE EntryID=? AND BusinessID=?", [entry_id, bid])
    db.commit()
    return {"ok": True}
