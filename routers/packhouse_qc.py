"""
routers/packhouse_qc.py
Packhouse sorting/grading/packaging workflows and QC inspection templates.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional
from fastapi.responses import StreamingResponse
import csv
import io
import json

router = APIRouter(prefix="/api/packhouse", tags=["packhouse_qc"])
_ready = False


def _ensure(db: Session):
    global _ready
    if _ready:
        return
    stmts = [
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='PackhouseBatch')
        CREATE TABLE PackhouseBatch (
            BatchID         INT IDENTITY PRIMARY KEY,
            BusinessID      INT NOT NULL,
            BatchRef        NVARCHAR(100) NULL,
            ProductName     NVARCHAR(300) NOT NULL,
            SourceLotID     NVARCHAR(100) NULL,
            SupplierName    NVARCHAR(300) NULL,
            IntakeDate      DATE NOT NULL,
            IntakeQty       DECIMAL(12,3) NOT NULL,
            Unit            NVARCHAR(50)  NOT NULL DEFAULT 'kg',
            Status          NVARCHAR(50)  NOT NULL DEFAULT 'intake',
            StorageLocation NVARCHAR(200) NULL,
            Notes           NVARCHAR(MAX) NULL,
            CreatedAt       DATETIME2 DEFAULT GETDATE(),
            UpdatedAt       DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='PackhouseGrading')
        CREATE TABLE PackhouseGrading (
            GradeID         INT IDENTITY PRIMARY KEY,
            BatchID         INT NOT NULL,
            GradeName       NVARCHAR(100) NOT NULL,
            Quantity        DECIMAL(12,3) NOT NULL,
            Unit            NVARCHAR(50)  NULL,
            PriceModifier   DECIMAL(6,4) NULL DEFAULT 1.0,
            PackagingType   NVARCHAR(200) NULL,
            PackagedUnits   INT NULL,
            Notes           NVARCHAR(MAX) NULL,
            CreatedAt       DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='QCTemplate')
        CREATE TABLE QCTemplate (
            TemplateID   INT IDENTITY PRIMARY KEY,
            BusinessID   INT NOT NULL,
            TemplateName NVARCHAR(300) NOT NULL,
            ProductType  NVARCHAR(200) NULL,
            CriteriaJSON NVARCHAR(MAX) NULL,
            IsActive     BIT DEFAULT 1,
            CreatedAt    DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='QCInspection')
        CREATE TABLE QCInspection (
            InspectionID    INT IDENTITY PRIMARY KEY,
            BatchID         INT NOT NULL,
            TemplateID      INT NULL,
            BusinessID      INT NOT NULL,
            InspectionDate  DATE NOT NULL,
            Inspector       NVARCHAR(200) NULL,
            OverallResult   NVARCHAR(20)  NOT NULL DEFAULT 'pass',
            ScoresPct       DECIMAL(5,2) NULL,
            FindingsJSON    NVARCHAR(MAX) NULL,
            ActionRequired  NVARCHAR(MAX) NULL,
            Notes           NVARCHAR(MAX) NULL,
            CreatedAt       DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='PackhousePackaging')
        CREATE TABLE PackhousePackaging (
            PackID          INT IDENTITY PRIMARY KEY,
            BatchID         INT NOT NULL,
            GradeID         INT NULL,
            PackDate        DATE NOT NULL,
            PackagingType   NVARCHAR(200) NOT NULL,
            UnitsPackaged   INT NULL,
            QtyPerUnit      DECIMAL(10,3) NULL,
            Unit            NVARCHAR(50)  NULL,
            LotCode         NVARCHAR(100) NULL,
            ExpiryDate      DATE NULL,
            DestinationMarket NVARCHAR(300) NULL,
            Notes           NVARCHAR(MAX) NULL,
            CreatedAt       DATETIME2 DEFAULT GETDATE()
        )""",
        # Link ExportShipment back to the source packhouse batch
        """IF NOT EXISTS (
            SELECT 1 FROM sys.columns
            WHERE object_id=OBJECT_ID('ExportShipment') AND name='PackhouseBatchID'
        ) ALTER TABLE ExportShipment ADD PackhouseBatchID INT NULL""",
    ]
    for s in stmts:
        db.execute(text(s))
    db.commit()
    _ready = True


def _auto_create_export_shipment(db: Session, batch_id: int, business_id: int):
    """When a packhouse batch is dispatched, create a draft ExportShipment pre-filled with batch data."""
    try:
        # Skip if ExportShipment table doesn't exist yet (export_compliance module not init'd)
        tbl = db.execute(text(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ExportShipment'"
        )).scalar()
        if not tbl:
            return

        # Skip if a shipment already exists for this batch
        existing = db.execute(text(
            "SELECT TOP 1 ShipmentID FROM ExportShipment WHERE PackhouseBatchID=:bid AND BusinessID=:business_id"
        ), {"bid": batch_id, "business_id": business_id}).fetchone()
        if existing:
            return

        # Load batch + grading totals
        batch = db.execute(text("""
            SELECT b.*,
                   ISNULL(SUM(g.Quantity), b.IntakeQty) AS TotalGraded,
                   ISNULL(SUM(g.PackagedUnits), 0)      AS TotalUnits,
                   MAX(g.Unit)                          AS GradeUnit
            FROM PackhouseBatch b
            LEFT JOIN PackhouseGrading g ON g.BatchID = b.BatchID
            WHERE b.BatchID=:bid AND b.BusinessID=:business_id
            GROUP BY b.BatchID, b.BusinessID, b.BatchRef, b.ProductName, b.SourceLotID,
                     b.SupplierName, b.IntakeDate, b.IntakeQty, b.Unit, b.Status,
                     b.StorageLocation, b.Notes, b.CreatedAt, b.UpdatedAt
        """), {"bid": batch_id, "business_id": business_id}).fetchone()

        if not batch:
            return

        # Auto-generate shipment ref
        count = db.execute(
            text("SELECT COUNT(*)+1 FROM ExportShipment WHERE BusinessID=:bid"), {"bid": business_id}
        ).scalar()
        ship_ref = f"SHIP-{business_id}-{count:04d}"

        db.execute(text("""
            INSERT INTO ExportShipment
                (BusinessID, ShipmentRef, ProductName, HarvestLotID, QuantityKg, PackagedUnits,
                 Status, PackhouseBatchID, Notes, DestinationCountry)
            VALUES (:bid, :ref, :product, :lot, :qty, :units,
                    'draft', :batch_id, :notes, 'TBD')
        """), {
            "bid": business_id, "ref": ship_ref,
            "product": batch.ProductName,
            "lot": batch.SourceLotID,
            "qty": float(batch.TotalGraded or batch.IntakeQty or 0),
            "units": int(batch.TotalUnits or 0),
            "batch_id": batch_id,
            "notes": f"Auto-created from packhouse batch {batch.BatchRef or batch_id} on dispatch.",
        })

        from routers.notifications import notify_business
        notify_business(
            db, business_id, type="export_shipment_drafted",
            title=f"Draft export shipment created: {ship_ref}",
            body=f"{batch.ProductName} batch {batch.BatchRef or batch_id} dispatched. Shipment {ship_ref} is ready to fill in.",
            link_path=f"/export-compliance?BusinessID={business_id}",
            entity_type="ExportShipment",
        )
    except Exception as _e:
        print(f"[dispatch-shipment] auto-create failed: {_e}")


# ─── Batches ─────────────────────────────────────────────────────────────────

@router.get("/batches")
def list_batches(business_id: int = Query(...), status: Optional[str] = None, db: Session = Depends(get_db)):
    _ensure(db)
    q = """
        SELECT b.*,
            (SELECT ISNULL(SUM(Quantity),0) FROM PackhouseGrading WHERE BatchID=b.BatchID) AS GradedQty,
            (SELECT COUNT(*) FROM QCInspection WHERE BatchID=b.BatchID) AS InspectionCount
        FROM PackhouseBatch b WHERE b.BusinessID=:bid
    """
    params = {"bid": business_id}
    if status:
        q += " AND b.Status=:st"; params["st"] = status
    q += " ORDER BY b.IntakeDate DESC"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/batches")
def create_batch(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    count = db.execute(text("SELECT COUNT(*)+1 FROM PackhouseBatch WHERE BusinessID=:bid"), {"bid": body["BusinessID"]}).scalar()
    batch_ref = f"PH-{body['BusinessID']}-{count:04d}"
    r = db.execute(text("""
        INSERT INTO PackhouseBatch (BusinessID,BatchRef,ProductName,SourceLotID,SupplierName,
            IntakeDate,IntakeQty,Unit,Status,StorageLocation,Notes)
        OUTPUT INSERTED.BatchID
        VALUES (:bid,:ref,:prod,:lot,:sup,:dt,:qty,:unit,:st,:loc,:notes)
    """), {
        "bid": body["BusinessID"], "ref": batch_ref,
        "prod": body["ProductName"], "lot": body.get("SourceLotID"),
        "sup": body.get("SupplierName"), "dt": body["IntakeDate"],
        "qty": body["IntakeQty"], "unit": body.get("Unit", "kg"),
        "st": body.get("Status", "intake"), "loc": body.get("StorageLocation"),
        "notes": body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"BatchID": r[0], "BatchRef": batch_ref}


@router.put("/batches/{batch_id}/status")
def update_batch_status(batch_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    bid = body["BusinessID"]
    new_status = body["Status"]
    db.execute(text("""
        UPDATE PackhouseBatch SET Status=:st, UpdatedAt=GETDATE()
        WHERE BatchID=:batch_id AND BusinessID=:bid
    """), {"st": new_status, "batch_id": batch_id, "bid": bid})
    db.commit()
    if new_status == "dispatched":
        _auto_create_export_shipment(db, batch_id, bid)
        db.commit()
    return {"ok": True}


# ─── Grading ─────────────────────────────────────────────────────────────────

@router.get("/batches/{batch_id}/grades")
def get_grades(batch_id: int, db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(text("SELECT * FROM PackhouseGrading WHERE BatchID=:bid ORDER BY GradeName"),
                      {"bid": batch_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/batches/{batch_id}/grades")
def add_grade(batch_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO PackhouseGrading (BatchID,GradeName,Quantity,Unit,PriceModifier,PackagingType,PackagedUnits,Notes)
        OUTPUT INSERTED.GradeID
        VALUES (:bid,:grade,:qty,:unit,:pm,:pt,:pu,:notes)
    """), {
        "bid": batch_id, "grade": body["GradeName"], "qty": body["Quantity"],
        "unit": body.get("Unit"), "pm": body.get("PriceModifier", 1.0),
        "pt": body.get("PackagingType"), "pu": body.get("PackagedUnits"),
        "notes": body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"GradeID": r[0]}


# ─── QC Templates ─────────────────────────────────────────────────────────────

@router.get("/templates")
def list_templates(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(text("SELECT * FROM QCTemplate WHERE BusinessID=:bid AND IsActive=1 ORDER BY TemplateName"),
                      {"bid": business_id}).fetchall()
    result = []
    for r in rows:
        d = dict(r._mapping)
        try:
            d["Criteria"] = json.loads(d["CriteriaJSON"]) if d.get("CriteriaJSON") else []
        except Exception:
            d["Criteria"] = []
        result.append(d)
    return result


@router.post("/templates")
def create_template(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    criteria = body.get("Criteria", [])
    r = db.execute(text("""
        INSERT INTO QCTemplate (BusinessID,TemplateName,ProductType,CriteriaJSON)
        OUTPUT INSERTED.TemplateID
        VALUES (:bid,:name,:pt,:crit)
    """), {
        "bid": body["BusinessID"], "name": body["TemplateName"],
        "pt": body.get("ProductType"), "crit": json.dumps(criteria),
    }).fetchone()
    db.commit()
    return {"TemplateID": r[0]}


# ─── Inspections ──────────────────────────────────────────────────────────────

@router.get("/batches/{batch_id}/inspections")
def get_inspections(batch_id: int, db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(text("""
        SELECT i.*, t.TemplateName
        FROM QCInspection i
        LEFT JOIN QCTemplate t ON t.TemplateID=i.TemplateID
        WHERE i.BatchID=:bid ORDER BY i.InspectionDate DESC
    """), {"bid": batch_id}).fetchall()
    result = []
    for r in rows:
        d = dict(r._mapping)
        try:
            d["Findings"] = json.loads(d["FindingsJSON"]) if d.get("FindingsJSON") else []
        except Exception:
            d["Findings"] = []
        result.append(d)
    return result


@router.post("/batches/{batch_id}/inspections")
def add_inspection(batch_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    findings = body.get("Findings", [])
    r = db.execute(text("""
        INSERT INTO QCInspection (BatchID,TemplateID,BusinessID,InspectionDate,Inspector,
            OverallResult,ScoresPct,FindingsJSON,ActionRequired,Notes)
        OUTPUT INSERTED.InspectionID
        VALUES (:bid,:tid,:business_id,:dt,:insp,:result,:score,:findings,:action,:notes)
    """), {
        "bid": batch_id, "tid": body.get("TemplateID"),
        "business_id": body["BusinessID"], "dt": body["InspectionDate"],
        "insp": body.get("Inspector"), "result": body.get("OverallResult", "pass"),
        "score": body.get("ScoresPct"), "findings": json.dumps(findings),
        "action": body.get("ActionRequired"), "notes": body.get("Notes"),
    }).fetchone()
    inspection_id = r[0]
    db.commit()

    # Auto-create FarmAlert + notification on QC failure
    if body.get("OverallResult", "pass") == "fail":
        try:
            batch = db.execute(text(
                "SELECT ProductName, BusinessID, BatchRef FROM PackhouseBatch WHERE BatchID=:bid"
            ), {"bid": batch_id}).fetchone()
            if batch:
                fa_exists = db.execute(text(
                    "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='FarmAlert'"
                )).scalar()
                if fa_exists:
                    db.execute(text("""
                        INSERT INTO FarmAlert
                            (BusinessID, AlertType, Severity, Title, Message, Source, SourceID, IsRead)
                        VALUES (:bid, 'qc_failure', 'critical', :title, :msg, 'packhouse_qc', :sid, 0)
                    """), {
                        "bid":   batch.BusinessID,
                        "title": f"QC Failure: {batch.ProductName}",
                        "msg":   (
                            f"Batch {batch.BatchRef or batch_id} failed QC on {body.get('InspectionDate')}. "
                            f"Score: {body.get('ScoresPct','N/A')}%. "
                            + (f"Action required: {body.get('ActionRequired')}" if body.get('ActionRequired') else "")
                        ),
                        "sid": inspection_id,
                    })
                from routers.notifications import notify_business
                notify_business(
                    db, batch.BusinessID, type="qc_failure",
                    title=f"QC Failure: {batch.ProductName}",
                    body=f"Batch {batch.BatchRef or batch_id} failed inspection. {body.get('ActionRequired','Review required.')}",
                    link_path=f"/packhouse?BusinessID={batch.BusinessID}",
                    entity_type="QCInspection", entity_id=inspection_id,
                )
                db.commit()
        except Exception as _e:
            print(f"[qc-fail-alert] {_e}")

    return {"InspectionID": inspection_id}


# ─── Packaging ────────────────────────────────────────────────────────────────

@router.get("/batches/{batch_id}/packaging")
def get_packaging(batch_id: int, db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(text("SELECT * FROM PackhousePackaging WHERE BatchID=:bid ORDER BY PackDate DESC"),
                      {"bid": batch_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/batches/{batch_id}/packaging")
def add_packaging(batch_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO PackhousePackaging (BatchID,GradeID,PackDate,PackagingType,UnitsPackaged,
            QtyPerUnit,Unit,LotCode,ExpiryDate,DestinationMarket,Notes)
        OUTPUT INSERTED.PackID
        VALUES (:bid,:gid,:dt,:pt,:units,:qpu,:unit,:lot,:exp,:dest,:notes)
    """), {
        "bid": batch_id, "gid": body.get("GradeID"), "dt": body["PackDate"],
        "pt": body["PackagingType"], "units": body.get("UnitsPackaged"),
        "qpu": body.get("QtyPerUnit"), "unit": body.get("Unit"),
        "lot": body.get("LotCode"), "exp": body.get("ExpiryDate"),
        "dest": body.get("DestinationMarket"), "notes": body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"PackID": r[0]}


# ─── Summary ─────────────────────────────────────────────────────────────────

@router.get("/summary")
def packhouse_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    row = db.execute(text("""
        SELECT
            COUNT(*) AS TotalBatches,
            SUM(CASE WHEN Status='intake' THEN 1 ELSE 0 END) AS Intake,
            SUM(CASE WHEN Status='grading' THEN 1 ELSE 0 END) AS Grading,
            SUM(CASE WHEN Status='packaging' THEN 1 ELSE 0 END) AS Packaging,
            SUM(CASE WHEN Status='dispatched' THEN 1 ELSE 0 END) AS Dispatched,
            ISNULL(SUM(IntakeQty),0) AS TotalIntakeKg
        FROM PackhouseBatch WHERE BusinessID=:bid
    """), {"bid": business_id}).fetchone()
    qc = db.execute(text("""
        SELECT
            COUNT(*) AS TotalInspections,
            SUM(CASE WHEN OverallResult='pass' THEN 1 ELSE 0 END) AS Passed,
            SUM(CASE WHEN OverallResult='fail' THEN 1 ELSE 0 END) AS Failed
        FROM QCInspection WHERE BusinessID=:bid
    """), {"bid": business_id}).fetchone()
    return {**dict(row._mapping), **dict(qc._mapping)} if row and qc else {}


# ─── CSV Export ───────────────────────────────────────────────────────────────

@router.get("/export")
def export_batches_csv(business_id: int = Query(...), status: Optional[str] = None,
                       db: Session = Depends(get_db)):
    """Download all packhouse batches with graded qty and inspection count as CSV."""
    _ensure(db)
    q = """
        SELECT b.BatchID, b.BatchRef, b.ProductName, b.SupplierName,
               b.IntakeDate, b.IntakeQty, b.Unit, b.Status, b.StorageLocation,
               b.Notes, b.CreatedAt,
               ISNULL((SELECT SUM(Quantity) FROM PackhouseGrading WHERE BatchID=b.BatchID), 0) AS GradedQty,
               ISNULL((SELECT COUNT(*) FROM QCInspection WHERE BatchID=b.BatchID), 0) AS InspectionCount,
               ISNULL((SELECT SUM(CASE WHEN OverallResult='pass' THEN 1 ELSE 0 END)
                       FROM QCInspection WHERE BatchID=b.BatchID), 0) AS InspectionsPassed
        FROM PackhouseBatch b WHERE b.BusinessID=:bid
    """
    params: dict = {"bid": business_id}
    if status:
        q += " AND b.Status=:st"; params["st"] = status
    q += " ORDER BY b.IntakeDate DESC"
    rows = db.execute(text(q), params).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["BatchID", "BatchRef", "Product", "Supplier", "IntakeDate", "IntakeQty",
                     "Unit", "Status", "StorageLocation", "GradedQty", "InspectionCount",
                     "InspectionsPassed", "Notes", "CreatedAt"])
    for r in rows:
        writer.writerow([r.BatchID, r.BatchRef, r.ProductName, r.SupplierName,
                         r.IntakeDate, r.IntakeQty, r.Unit, r.Status, r.StorageLocation,
                         r.GradedQty, r.InspectionCount, r.InspectionsPassed,
                         r.Notes, r.CreatedAt])
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=packhouse_batches_{business_id}.csv"},
    )
