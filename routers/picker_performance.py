from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/picker", tags=["picker_performance"])

_ddl_done = False

def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cursor = db.cursor()
    cursor.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='PickerPieceRate')
    CREATE TABLE PickerPieceRate (
        RateID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        Variety NVARCHAR(100) NOT NULL,
        QualityGrade NVARCHAR(20) NOT NULL DEFAULT 'A',
        PricePerKg DECIMAL(10,4) NOT NULL,
        EffectiveDate DATE NOT NULL,
        IsActive BIT NOT NULL DEFAULT 1,
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cursor.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='PickerSession')
    CREATE TABLE PickerSession (
        SessionID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        EmployeeID INT NOT NULL,
        PickingDate DATE NOT NULL,
        BlockID NVARCHAR(50),
        Variety NVARCHAR(100),
        StartTime DATETIME,
        EndTime DATETIME,
        TotalWeightKg DECIMAL(10,3) NOT NULL DEFAULT 0,
        AvgQualityScore DECIMAL(5,2),
        PieceRatePerKg DECIMAL(10,4),
        WageEarned DECIMAL(10,2),
        CycleNumber INT NOT NULL DEFAULT 1,
        Notes NVARCHAR(500),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cursor.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='PickerDropOff')
    CREATE TABLE PickerDropOff (
        DropOffID INT IDENTITY PRIMARY KEY,
        SessionID INT,
        BusinessID INT NOT NULL,
        EmployeeID INT NOT NULL,
        WeightKg DECIMAL(10,3) NOT NULL,
        QualityGrade NVARCHAR(20) NOT NULL DEFAULT 'A',
        QualityScore DECIMAL(5,2),
        BlockID NVARCHAR(50),
        Variety NVARCHAR(100),
        DroppedAt DATETIME NOT NULL DEFAULT GETDATE(),
        LotID INT,
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    db.commit()
    _ddl_done = True


class SessionIn(BaseModel):
    employee_id: int
    picking_date: date
    block_id: Optional[str] = None
    variety: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_weight_kg: float = 0
    avg_quality_score: Optional[float] = None
    piece_rate_per_kg: Optional[float] = None
    cycle_number: int = 1
    notes: Optional[str] = None


class SessionClose(BaseModel):
    end_time: Optional[datetime] = None
    total_weight_kg: Optional[float] = None
    avg_quality_score: Optional[float] = None
    notes: Optional[str] = None


class DropOffIn(BaseModel):
    session_id: Optional[int] = None
    employee_id: int
    weight_kg: float
    quality_grade: str = "A"
    quality_score: Optional[float] = None
    block_id: Optional[str] = None
    variety: Optional[str] = None
    lot_id: Optional[int] = None


class PieceRateIn(BaseModel):
    variety: str
    quality_grade: str = "A"
    price_per_kg: float
    effective_date: date
    is_active: bool = True


@router.get("/sessions")
def list_sessions(
    employee_id: Optional[int] = None,
    picking_date: Optional[date] = None,
    variety: Optional[str] = None,
    limit: int = 50,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    filters = ["BusinessID=?"]
    params: list = [bid]
    if employee_id:
        filters.append("EmployeeID=?"); params.append(employee_id)
    if picking_date:
        filters.append("CAST(PickingDate AS DATE)=?"); params.append(str(picking_date))
    if variety:
        filters.append("Variety=?"); params.append(variety)
    where = " AND ".join(filters)
    cursor.execute(f"""
        SELECT ps.SessionID, ps.EmployeeID,
               ISNULL(e.FirstName+' '+e.LastName, CAST(ps.EmployeeID AS NVARCHAR)) AS EmployeeName,
               ps.PickingDate, ps.BlockID, ps.Variety, ps.StartTime, ps.EndTime,
               ps.TotalWeightKg, ps.AvgQualityScore, ps.PieceRatePerKg, ps.WageEarned,
               ps.CycleNumber, ps.Notes, ps.CreatedAt
        FROM PickerSession ps
        LEFT JOIN HREmployee e ON e.EmployeeID=ps.EmployeeID
        WHERE {where}
        ORDER BY ps.CreatedAt DESC
        OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY
    """, params + [limit])
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


@router.post("/sessions", status_code=201)
def create_session(body: SessionIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    # auto-derive piece rate if not supplied
    piece_rate = body.piece_rate_per_kg
    if piece_rate is None and body.variety:
        cursor.execute("""
            SELECT TOP 1 PricePerKg FROM PickerPieceRate
            WHERE BusinessID=? AND Variety=? AND QualityGrade='A' AND IsActive=1
            ORDER BY EffectiveDate DESC
        """, [bid, body.variety])
        row = cursor.fetchone()
        if row:
            piece_rate = float(row[0])
    wage = None
    if piece_rate and body.total_weight_kg:
        wage = round(body.total_weight_kg * piece_rate, 2)
    cursor.execute("""
        INSERT INTO PickerSession
            (BusinessID,EmployeeID,PickingDate,BlockID,Variety,StartTime,EndTime,
             TotalWeightKg,AvgQualityScore,PieceRatePerKg,WageEarned,CycleNumber,Notes)
        OUTPUT INSERTED.SessionID
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [bid, body.employee_id, str(body.picking_date), body.block_id, body.variety,
          body.start_time, body.end_time, body.total_weight_kg, body.avg_quality_score,
          piece_rate, wage, body.cycle_number, body.notes])
    sid = cursor.fetchone()[0]
    db.commit()
    return {"session_id": sid}


@router.patch("/sessions/{session_id}")
def close_session(session_id: int, body: SessionClose, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    cursor.execute("SELECT TotalWeightKg,PieceRatePerKg FROM PickerSession WHERE SessionID=? AND BusinessID=?", [session_id, bid])
    row = cursor.fetchone()
    if not row:
        raise HTTPException(404, "Session not found")
    weight = body.total_weight_kg if body.total_weight_kg is not None else float(row[0])
    rate = float(row[1]) if row[1] else None
    wage = round(weight * rate, 2) if rate else None
    cursor.execute("""
        UPDATE PickerSession SET
            EndTime=ISNULL(?,EndTime),
            TotalWeightKg=ISNULL(?,TotalWeightKg),
            AvgQualityScore=ISNULL(?,AvgQualityScore),
            WageEarned=ISNULL(?,WageEarned),
            Notes=ISNULL(?,Notes)
        WHERE SessionID=? AND BusinessID=?
    """, [body.end_time, body.total_weight_kg, body.avg_quality_score, wage, body.notes, session_id, bid])
    db.commit()
    return {"ok": True}


@router.post("/dropoff", status_code=201)
def record_dropoff(body: DropOffIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO PickerDropOff
            (SessionID,BusinessID,EmployeeID,WeightKg,QualityGrade,QualityScore,BlockID,Variety,LotID)
        OUTPUT INSERTED.DropOffID
        VALUES (?,?,?,?,?,?,?,?,?)
    """, [body.session_id, bid, body.employee_id, body.weight_kg, body.quality_grade,
          body.quality_score, body.block_id, body.variety, body.lot_id])
    did = cursor.fetchone()[0]
    # accumulate weight onto session
    if body.session_id:
        cursor.execute("""
            UPDATE PickerSession SET TotalWeightKg=TotalWeightKg+?
            WHERE SessionID=? AND BusinessID=?
        """, [body.weight_kg, body.session_id, bid])
    db.commit()
    return {"drop_off_id": did}


@router.get("/performance")
def picker_performance(
    employee_id: Optional[int] = None,
    variety: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    filters = ["ps.BusinessID=?"]
    params: list = [bid]
    if employee_id:
        filters.append("ps.EmployeeID=?"); params.append(employee_id)
    if variety:
        filters.append("ps.Variety=?"); params.append(variety)
    if from_date:
        filters.append("ps.PickingDate>=?"); params.append(str(from_date))
    if to_date:
        filters.append("ps.PickingDate<=?"); params.append(str(to_date))
    where = " AND ".join(filters)
    cursor.execute(f"""
        SELECT ps.EmployeeID,
               ISNULL(e.FirstName+' '+e.LastName, CAST(ps.EmployeeID AS NVARCHAR)) AS EmployeeName,
               ps.Variety,
               COUNT(ps.SessionID) AS Sessions,
               SUM(ps.TotalWeightKg) AS TotalKg,
               AVG(ps.TotalWeightKg) AS AvgKgPerSession,
               AVG(ps.AvgQualityScore) AS AvgQuality,
               SUM(ps.WageEarned) AS TotalWage,
               MAX(ps.PickingDate) AS LastPickDate
        FROM PickerSession ps
        LEFT JOIN HREmployee e ON e.EmployeeID=ps.EmployeeID
        WHERE {where}
        GROUP BY ps.EmployeeID, e.FirstName, e.LastName, ps.Variety
        ORDER BY TotalKg DESC
    """, params)
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


@router.get("/leaderboard")
def leaderboard(
    picking_date: Optional[date] = None,
    variety: Optional[str] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    date_filter = "AND CAST(ps.PickingDate AS DATE)=?" if picking_date else ""
    variety_filter = "AND ps.Variety=?" if variety else ""
    params: list = [bid]
    if picking_date:
        params.append(str(picking_date))
    if variety:
        params.append(variety)
    cursor.execute(f"""
        SELECT TOP 20
               ps.EmployeeID,
               ISNULL(e.FirstName+' '+e.LastName, CAST(ps.EmployeeID AS NVARCHAR)) AS EmployeeName,
               SUM(ps.TotalWeightKg) AS TotalKg,
               AVG(ps.AvgQualityScore) AS AvgQuality,
               SUM(ps.WageEarned) AS TotalWage,
               COUNT(ps.SessionID) AS Sessions
        FROM PickerSession ps
        LEFT JOIN HREmployee e ON e.EmployeeID=ps.EmployeeID
        WHERE ps.BusinessID=? {date_filter} {variety_filter}
        GROUP BY ps.EmployeeID, e.FirstName, e.LastName
        ORDER BY TotalKg DESC
    """, params)
    cols = [c[0] for c in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


@router.get("/piece-rates")
def list_piece_rates(variety: Optional[str] = None, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    if variety:
        cursor.execute("SELECT * FROM PickerPieceRate WHERE BusinessID=? AND Variety=? ORDER BY EffectiveDate DESC", [bid, variety])
    else:
        cursor.execute("SELECT * FROM PickerPieceRate WHERE BusinessID=? ORDER BY Variety, EffectiveDate DESC", [bid])
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


@router.put("/piece-rates")
def upsert_piece_rate(body: PieceRateIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    cursor.execute("""
        SELECT RateID FROM PickerPieceRate
        WHERE BusinessID=? AND Variety=? AND QualityGrade=? AND EffectiveDate=?
    """, [bid, body.variety, body.quality_grade, str(body.effective_date)])
    existing = cursor.fetchone()
    if existing:
        cursor.execute("""
            UPDATE PickerPieceRate SET PricePerKg=?, IsActive=?
            WHERE RateID=?
        """, [body.price_per_kg, 1 if body.is_active else 0, existing[0]])
        rid = existing[0]
    else:
        cursor.execute("""
            INSERT INTO PickerPieceRate (BusinessID,Variety,QualityGrade,PricePerKg,EffectiveDate,IsActive)
            OUTPUT INSERTED.RateID VALUES (?,?,?,?,?,?)
        """, [bid, body.variety, body.quality_grade, body.price_per_kg,
              str(body.effective_date), 1 if body.is_active else 0])
        rid = cursor.fetchone()[0]
    db.commit()
    return {"rate_id": rid}


@router.get("/payroll-summary")
def payroll_summary(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cursor = db.cursor()
    date_filters = ""
    params: list = [bid]
    if from_date:
        date_filters += " AND ps.PickingDate>=?"; params.append(str(from_date))
    if to_date:
        date_filters += " AND ps.PickingDate<=?"; params.append(str(to_date))
    cursor.execute(f"""
        SELECT ps.EmployeeID,
               ISNULL(e.FirstName+' '+e.LastName, CAST(ps.EmployeeID AS NVARCHAR)) AS EmployeeName,
               COUNT(ps.SessionID) AS Sessions,
               SUM(ps.TotalWeightKg) AS TotalKg,
               SUM(ps.WageEarned) AS TotalWage,
               MIN(ps.PickingDate) AS PeriodStart,
               MAX(ps.PickingDate) AS PeriodEnd
        FROM PickerSession ps
        LEFT JOIN HREmployee e ON e.EmployeeID=ps.EmployeeID
        WHERE ps.BusinessID=? {date_filters}
        GROUP BY ps.EmployeeID, e.FirstName, e.LastName
        ORDER BY TotalWage DESC
    """, params)
    cols = [c[0] for c in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    total = sum(r["TotalWage"] or 0 for r in rows)
    return {"summary": rows, "total_payroll": round(total, 2)}
