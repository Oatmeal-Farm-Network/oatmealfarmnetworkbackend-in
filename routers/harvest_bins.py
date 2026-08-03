from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/harvest-bins", tags=["harvest_bins"])
_ddl_done = False

STAGES = [
    "filled", "weighed", "transported", "dumped", "washed",
    "waxed", "sized", "sorted", "packed", "ca_stored", "dispatched",
]
BIN_TYPES = ["standard", "macro", "lug", "half_bin", "pallet_bin", "field_crate"]


def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cur = db.cursor()
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='HarvestBin')
    CREATE TABLE HarvestBin (
        BinID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        BinBarcode NVARCHAR(100) NOT NULL,
        BinType NVARCHAR(30) NOT NULL DEFAULT 'standard',
        CapacityKg DECIMAL(10,3),
        TareWeightKg DECIMAL(8,3),
        Status NVARCHAR(30) NOT NULL DEFAULT 'in_field',
        LotID INT,
        Variety NVARCHAR(100),
        BlockID NVARCHAR(50),
        PickerID INT,
        FilledAt DATETIME,
        CurrentStage NVARCHAR(30),
        CurrentLocation NVARCHAR(200),
        Notes NVARCHAR(500),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE(),
        CONSTRAINT UQ_HarvestBinBarcode UNIQUE (BusinessID, BinBarcode)
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='HarvestBinStep')
    CREATE TABLE HarvestBinStep (
        StepID INT IDENTITY PRIMARY KEY,
        BinID INT NOT NULL,
        BusinessID INT NOT NULL,
        Stage NVARCHAR(30) NOT NULL,
        StepTime DATETIME NOT NULL DEFAULT GETDATE(),
        OperatorName NVARCHAR(200),
        WeightKg DECIMAL(10,3),
        TemperatureC DECIMAL(6,2),
        Location NVARCHAR(200),
        Notes NVARCHAR(500)
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='HarvestBinPackage')
    CREATE TABLE HarvestBinPackage (
        PackageID INT IDENTITY PRIMARY KEY,
        BinID INT NOT NULL,
        BusinessID INT NOT NULL,
        PackageType NVARCHAR(80),
        LabelCode NVARCHAR(100),
        NetWeightKg DECIMAL(10,3),
        Grade NVARCHAR(20),
        DestinationMarket NVARCHAR(200),
        PackedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    db.commit()
    _ddl_done = True


class BinIn(BaseModel):
    bin_barcode: str
    bin_type: str = "standard"
    capacity_kg: Optional[float] = None
    tare_weight_kg: Optional[float] = None
    lot_id: Optional[int] = None
    variety: Optional[str] = None
    block_id: Optional[str] = None
    picker_id: Optional[int] = None
    notes: Optional[str] = None


class BulkRegisterIn(BaseModel):
    bins: List[BinIn]


class StepIn(BaseModel):
    stage: str
    step_time: Optional[datetime] = None
    operator_name: Optional[str] = None
    weight_kg: Optional[float] = None
    temperature_c: Optional[float] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class PackageIn(BaseModel):
    package_type: Optional[str] = None
    label_code: Optional[str] = None
    net_weight_kg: Optional[float] = None
    grade: Optional[str] = None
    destination_market: Optional[str] = None


@router.get("/bins")
def list_bins(
    status: Optional[str] = None,
    variety: Optional[str] = None,
    lot_id: Optional[int] = None,
    stage: Optional[str] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    filters = ["BusinessID=?"]
    params: list = [bid]
    if status:
        filters.append("Status=?"); params.append(status)
    if variety:
        filters.append("Variety=?"); params.append(variety)
    if lot_id:
        filters.append("LotID=?"); params.append(lot_id)
    if stage:
        filters.append("CurrentStage=?"); params.append(stage)
    cur.execute(f"SELECT * FROM HarvestBin WHERE {' AND '.join(filters)} ORDER BY FilledAt DESC", params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.post("/bins", status_code=201)
def create_bin(body: BinIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        INSERT INTO HarvestBin
            (BusinessID,BinBarcode,BinType,CapacityKg,TareWeightKg,LotID,Variety,BlockID,PickerID,FilledAt,CurrentStage,Notes)
        OUTPUT INSERTED.BinID VALUES (?,?,?,?,?,?,?,?,?,GETDATE(),'filled',?)
    """, [bid, body.bin_barcode, body.bin_type, body.capacity_kg, body.tare_weight_kg,
          body.lot_id, body.variety, body.block_id, body.picker_id, body.notes])
    bin_id = cur.fetchone()[0]
    # auto-log filled step
    cur.execute("INSERT INTO HarvestBinStep (BinID,BusinessID,Stage,Location) VALUES (?,?,'filled',?)",
                [bin_id, bid, body.block_id])
    db.commit()
    return {"bin_id": bin_id}


@router.post("/bins/bulk-register", status_code=201)
def bulk_register(body: BulkRegisterIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    created = 0
    skipped = 0
    for b in body.bins:
        try:
            cur.execute("""
                INSERT INTO HarvestBin (BusinessID,BinBarcode,BinType,CapacityKg,TareWeightKg,
                    LotID,Variety,BlockID,PickerID,FilledAt,CurrentStage,Notes)
                VALUES (?,?,?,?,?,?,?,?,?,GETDATE(),'filled',?)
            """, [bid, b.bin_barcode, b.bin_type, b.capacity_kg, b.tare_weight_kg,
                  b.lot_id, b.variety, b.block_id, b.picker_id, b.notes])
            created += 1
        except pyodbc.IntegrityError:
            skipped += 1
    db.commit()
    return {"created": created, "skipped_duplicates": skipped}


@router.get("/bins/{barcode}")
def get_bin_by_barcode(barcode: str, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT * FROM HarvestBin WHERE BinBarcode=? AND BusinessID=?", [barcode, bid])
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Bin not found")
    cols = [c[0] for c in cur.description]
    bin_data = dict(zip(cols, row))
    bin_id = bin_data["BinID"]
    # chain of custody
    cur.execute("SELECT * FROM HarvestBinStep WHERE BinID=? ORDER BY StepTime ASC", [bin_id])
    cols2 = [c[0] for c in cur.description]
    steps = [dict(zip(cols2, r)) for r in cur.fetchall()]
    # packages
    cur.execute("SELECT * FROM HarvestBinPackage WHERE BinID=?", [bin_id])
    cols3 = [c[0] for c in cur.description]
    packages = [dict(zip(cols3, r)) for r in cur.fetchall()]
    # time-in-stage calculations
    stage_times = []
    for i in range(len(steps) - 1):
        t1 = steps[i]["StepTime"]
        t2 = steps[i + 1]["StepTime"]
        if t1 and t2:
            hours = round((t2 - t1).total_seconds() / 3600, 2)
            stage_times.append({"from": steps[i]["Stage"], "to": steps[i + 1]["Stage"], "hours": hours})
    return {"bin": bin_data, "steps": steps, "packages": packages, "stage_durations": stage_times}


@router.post("/bins/{barcode}/step", status_code=201)
def record_step(barcode: str, body: StepIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    if body.stage not in STAGES:
        raise HTTPException(400, f"stage must be one of: {', '.join(STAGES)}")
    cur = db.cursor()
    cur.execute("SELECT BinID FROM HarvestBin WHERE BinBarcode=? AND BusinessID=?", [barcode, bid])
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Bin not found")
    bin_id = row[0]
    ts = body.step_time or datetime.utcnow()
    cur.execute("""
        INSERT INTO HarvestBinStep (BinID,BusinessID,Stage,StepTime,OperatorName,WeightKg,TemperatureC,Location,Notes)
        OUTPUT INSERTED.StepID VALUES (?,?,?,?,?,?,?,?,?)
    """, [bin_id, bid, body.stage, ts, body.operator_name, body.weight_kg,
          body.temperature_c, body.location, body.notes])
    sid = cur.fetchone()[0]
    cur.execute("UPDATE HarvestBin SET CurrentStage=?, CurrentLocation=ISNULL(?,CurrentLocation) WHERE BinID=?",
                [body.stage, body.location, bin_id])
    db.commit()
    return {"step_id": sid}


@router.post("/bins/{barcode}/package", status_code=201)
def record_package(barcode: str, body: PackageIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT BinID FROM HarvestBin WHERE BinBarcode=? AND BusinessID=?", [barcode, bid])
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Bin not found")
    bin_id = row[0]
    cur.execute("""
        INSERT INTO HarvestBinPackage (BinID,BusinessID,PackageType,LabelCode,NetWeightKg,Grade,DestinationMarket)
        OUTPUT INSERTED.PackageID VALUES (?,?,?,?,?,?,?)
    """, [bin_id, bid, body.package_type, body.label_code, body.net_weight_kg,
          body.grade, body.destination_market])
    pid = cur.fetchone()[0]
    db.commit()
    return {"package_id": pid}


@router.get("/lot/{lot_id}/bins")
def lot_bins(lot_id: int, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT b.*, s.StepCount, s.LastStage
        FROM HarvestBin b
        OUTER APPLY (
            SELECT COUNT(*) AS StepCount, MAX(Stage) AS LastStage
            FROM HarvestBinStep WHERE BinID=b.BinID
        ) s
        WHERE b.LotID=? AND b.BusinessID=?
        ORDER BY b.FilledAt
    """, [lot_id, bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/dashboard")
def dashboard(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT CurrentStage, COUNT(*) AS BinCount, COUNT(DISTINCT LotID) AS Lots,
               COUNT(DISTINCT Variety) AS Varieties
        FROM HarvestBin WHERE BusinessID=?
        GROUP BY CurrentStage
    """, [bid])
    cols = [c[0] for c in cur.description]
    by_stage = [dict(zip(cols, r)) for r in cur.fetchall()]

    cur.execute("""
        SELECT COUNT(*) AS TotalBins,
               SUM(CASE WHEN FilledAt >= DATEADD(day,-1,GETDATE()) THEN 1 ELSE 0 END) AS FilledToday,
               SUM(CASE WHEN CurrentStage='dispatched' THEN 1 ELSE 0 END) AS Dispatched,
               SUM(CASE WHEN CurrentStage='ca_stored' THEN 1 ELSE 0 END) AS InCAStorage
        FROM HarvestBin WHERE BusinessID=?
    """, [bid])
    stats_row = cur.fetchone()
    stats = {"total_bins": stats_row[0], "filled_today": stats_row[1], "dispatched": stats_row[2], "in_ca_storage": stats_row[3]}

    return {"by_stage": by_stage, "stats": stats, "stage_order": STAGES}
