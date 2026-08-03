from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime, timedelta
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/trace", tags=["perishable_trace"])

_ddl_done = False

STAGES = [
    "field_harvested",
    "cooling_entry",
    "cooling_exit",
    "packhouse_entry",
    "packhouse_graded",
    "dispatch",
]

STAGE_ORDER = {s: i for i, s in enumerate(STAGES)}

COMPLIANCE_TYPES = {"fertilizer", "pesticide", "water", "harvest", "other"}


def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cursor = db.cursor()
    cursor.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='HarvestLotCheckpoint')
    CREATE TABLE HarvestLotCheckpoint (
        CheckpointID INT IDENTITY PRIMARY KEY,
        LotID INT NOT NULL,
        BusinessID INT NOT NULL,
        Stage NVARCHAR(50) NOT NULL,
        CheckpointTime DATETIME NOT NULL DEFAULT GETDATE(),
        TemperatureC DECIMAL(6,2),
        Location NVARCHAR(200),
        RecordedBy NVARCHAR(200),
        Notes NVARCHAR(1000),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cursor.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ComplianceRecord')
    CREATE TABLE ComplianceRecord (
        RecordID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        LotID INT,
        RecordType NVARCHAR(50) NOT NULL,
        ProductName NVARCHAR(200),
        ApplicationDate DATE NOT NULL,
        ApplicationRate NVARCHAR(100),
        WithholdingDays INT,
        OperatorName NVARCHAR(200),
        FieldBlock NVARCHAR(100),
        Notes NVARCHAR(1000),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    db.commit()
    _ddl_done = True


class CheckpointIn(BaseModel):
    lot_id: int
    stage: str
    checkpoint_time: Optional[datetime] = None
    temperature_c: Optional[float] = None
    location: Optional[str] = None
    recorded_by: Optional[str] = None
    notes: Optional[str] = None


class ComplianceIn(BaseModel):
    lot_id: Optional[int] = None
    record_type: str
    product_name: Optional[str] = None
    application_date: date
    application_rate: Optional[str] = None
    withholding_days: Optional[int] = None
    operator_name: Optional[str] = None
    field_block: Optional[str] = None
    notes: Optional[str] = None


@router.post("/checkpoint", status_code=201)
def record_checkpoint(body: CheckpointIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    if body.stage not in STAGE_ORDER:
        raise HTTPException(400, f"stage must be one of: {', '.join(STAGES)}")
    # verify lot exists (if HarvestLot table exists)
    cursor = db.cursor()
    try:
        cursor.execute("SELECT LotID FROM HarvestLot WHERE LotID=? AND BusinessID=?", [body.lot_id, bid])
        if not cursor.fetchone():
            raise HTTPException(404, "HarvestLot not found")
    except pyodbc.ProgrammingError:
        pass  # HarvestLot table not yet created; allow checkpoint anyway
    ts = body.checkpoint_time or datetime.utcnow()
    cursor.execute("""
        INSERT INTO HarvestLotCheckpoint
            (LotID,BusinessID,Stage,CheckpointTime,TemperatureC,Location,RecordedBy,Notes)
        OUTPUT INSERTED.CheckpointID VALUES (?,?,?,?,?,?,?,?)
    """, [body.lot_id, bid, body.stage, ts, body.temperature_c,
          body.location, body.recorded_by, body.notes])
    cid = cursor.fetchone()[0]
    db.commit()
    return {"checkpoint_id": cid}


@router.get("/lot/{lot_id}")
def lot_timeline(lot_id: int, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    # lot metadata
    lot_meta = None
    try:
        cursor.execute("""
            SELECT l.LotID, l.Variety, l.FieldBlock, l.HarvestDate, l.TotalWeightKg,
                   l.Status, l.CreatedAt
            FROM HarvestLot l
            WHERE l.LotID=? AND l.BusinessID=?
        """, [lot_id, bid])
        row = cursor.fetchone()
        if row:
            cols = [c[0] for c in cursor.description]
            lot_meta = dict(zip(cols, row))
    except pyodbc.ProgrammingError:
        pass

    cursor.execute("""
        SELECT CheckpointID, Stage, CheckpointTime, TemperatureC, Location, RecordedBy, Notes
        FROM HarvestLotCheckpoint
        WHERE LotID=? AND BusinessID=?
        ORDER BY CheckpointTime ASC
    """, [lot_id, bid])
    cols = [c[0] for c in cursor.description]
    checkpoints = [dict(zip(cols, r)) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT RecordID, RecordType, ProductName, ApplicationDate, ApplicationRate,
               WithholdingDays, OperatorName, FieldBlock, Notes
        FROM ComplianceRecord
        WHERE LotID=? AND BusinessID=?
        ORDER BY ApplicationDate ASC
    """, [lot_id, bid])
    cols = [c[0] for c in cursor.description]
    compliance = [dict(zip(cols, r)) for r in cursor.fetchall()]

    # compute stage gaps / delays
    stage_map = {cp["Stage"]: cp for cp in checkpoints}
    gaps = []
    for i in range(len(STAGES) - 1):
        s1, s2 = STAGES[i], STAGES[i + 1]
        if s1 in stage_map and s2 in stage_map:
            t1 = stage_map[s1]["CheckpointTime"]
            t2 = stage_map[s2]["CheckpointTime"]
            if t1 and t2:
                delta_h = round((t2 - t1).total_seconds() / 3600, 2)
                gaps.append({"from_stage": s1, "to_stage": s2, "hours": delta_h})

    completed_stages = [cp["Stage"] for cp in checkpoints]
    missing_stages = [s for s in STAGES if s not in completed_stages]

    return {
        "lot": lot_meta,
        "checkpoints": checkpoints,
        "compliance": compliance,
        "stage_gaps": gaps,
        "missing_stages": missing_stages,
        "is_complete": len(missing_stages) == 0,
    }


@router.get("/compliance-records")
def list_compliance(
    lot_id: Optional[int] = None,
    record_type: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    filters = ["BusinessID=?"]
    params: list = [bid]
    if lot_id:
        filters.append("LotID=?"); params.append(lot_id)
    if record_type:
        filters.append("RecordType=?"); params.append(record_type)
    if from_date:
        filters.append("ApplicationDate>=?"); params.append(str(from_date))
    if to_date:
        filters.append("ApplicationDate<=?"); params.append(str(to_date))
    cursor.execute(f"""
        SELECT * FROM ComplianceRecord
        WHERE {' AND '.join(filters)}
        ORDER BY ApplicationDate DESC
    """, params)
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


@router.post("/compliance-records", status_code=201)
def create_compliance(body: ComplianceIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    if body.record_type not in COMPLIANCE_TYPES:
        raise HTTPException(400, f"record_type must be one of: {', '.join(COMPLIANCE_TYPES)}")
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO ComplianceRecord
            (BusinessID,LotID,RecordType,ProductName,ApplicationDate,ApplicationRate,
             WithholdingDays,OperatorName,FieldBlock,Notes)
        OUTPUT INSERTED.RecordID VALUES (?,?,?,?,?,?,?,?,?,?)
    """, [bid, body.lot_id, body.record_type, body.product_name,
          str(body.application_date), body.application_rate, body.withholding_days,
          body.operator_name, body.field_block, body.notes])
    rid = cursor.fetchone()[0]
    db.commit()
    return {"record_id": rid}


@router.get("/overdue")
def overdue_lots(hours_threshold: int = 4, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    """Lots stuck at cooling_entry or cooling_exit longer than hours_threshold without progression."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    cutoff = datetime.utcnow() - timedelta(hours=hours_threshold)
    cursor.execute("""
        SELECT c.LotID, c.Stage, c.CheckpointTime,
               DATEDIFF(MINUTE, c.CheckpointTime, GETDATE()) AS MinutesStuck,
               c.TemperatureC, c.Location
        FROM HarvestLotCheckpoint c
        WHERE c.BusinessID=? AND c.Stage IN ('cooling_entry','cooling_exit','packhouse_entry')
          AND c.CheckpointTime <= ?
          AND NOT EXISTS (
              SELECT 1 FROM HarvestLotCheckpoint c2
              WHERE c2.LotID=c.LotID AND c2.BusinessID=c.BusinessID
                AND c2.CheckpointTime > c.CheckpointTime
          )
        ORDER BY c.CheckpointTime ASC
    """, [bid, cutoff])
    cols = [c[0] for c in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    for r in rows:
        r["hours_stuck"] = round(r["MinutesStuck"] / 60, 1)
    return rows


@router.post("/report")
def generate_compliance_report(
    lot_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    """Generate a compliance report for a lot or date range."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()

    lots_data = []
    if lot_id:
        lot_ids = [lot_id]
    else:
        # find lots with checkpoints in date range
        date_filter = ""
        params: list = [bid]
        if from_date:
            date_filter += " AND CheckpointTime>=?"; params.append(str(from_date))
        if to_date:
            date_filter += " AND CheckpointTime<=?"; params.append(str(to_date) + " 23:59:59")
        cursor.execute(f"""
            SELECT DISTINCT LotID FROM HarvestLotCheckpoint
            WHERE BusinessID=? {date_filter}
        """, params)
        lot_ids = [r[0] for r in cursor.fetchall()]

    for lid in lot_ids:
        cursor.execute("""
            SELECT Stage, CheckpointTime, TemperatureC
            FROM HarvestLotCheckpoint
            WHERE LotID=? AND BusinessID=?
            ORDER BY CheckpointTime
        """, [lid, bid])
        checkpoints = [{"stage": r[0], "time": r[1], "temp_c": r[2]} for r in cursor.fetchall()]

        cursor.execute("""
            SELECT RecordType, ProductName, ApplicationDate, WithholdingDays, OperatorName
            FROM ComplianceRecord WHERE LotID=? AND BusinessID=?
        """, [lid, bid])
        compliance = [{"type": r[0], "product": r[1], "date": r[2], "wh_days": r[3], "operator": r[4]}
                      for r in cursor.fetchall()]

        # withholding check
        wh_issues = []
        for cr in compliance:
            if cr["wh_days"] and checkpoints:
                harvest_cp = next((c for c in checkpoints if c["stage"] == "field_harvested"), None)
                if harvest_cp and cr["date"]:
                    days_gap = (harvest_cp["time"].date() - cr["date"]).days
                    if days_gap < cr["wh_days"]:
                        wh_issues.append({
                            "product": cr["product"],
                            "required_days": cr["wh_days"],
                            "actual_days": days_gap,
                        })

        completed = [cp["stage"] for cp in checkpoints]
        missing = [s for s in STAGES if s not in completed]

        lots_data.append({
            "lot_id": lid,
            "checkpoints": checkpoints,
            "compliance_records": compliance,
            "withholding_issues": wh_issues,
            "missing_stages": missing,
            "chain_complete": len(missing) == 0,
            "compliant": len(wh_issues) == 0 and len(missing) == 0,
        })

    total = len(lots_data)
    compliant = sum(1 for l in lots_data if l["compliant"])
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "total_lots": total,
        "compliant_lots": compliant,
        "non_compliant_lots": total - compliant,
        "lots": lots_data,
    }
