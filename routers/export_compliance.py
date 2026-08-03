"""
routers/export_compliance.py
Export compliance: customs paperwork, phytosanitary certificates, per-crop margin vs operational cost,
recall management, GlobalG.A.P./USDA Organic compliance docs.
Revenue recognition on delivery confirmation (accounting Invoice).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional
from fastapi.responses import StreamingResponse
import csv
import io
from datetime import date

router = APIRouter(prefix="/api/export-compliance", tags=["export_compliance"])
_ready = False


def _ensure(db: Session):
    global _ready
    if _ready:
        return
    stmts = [
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ExportShipment')
        CREATE TABLE ExportShipment (
            ShipmentID         INT IDENTITY PRIMARY KEY,
            BusinessID         INT NOT NULL,
            ShipmentRef        NVARCHAR(100) NULL,
            ProductName        NVARCHAR(300) NOT NULL,
            HarvestLotID       NVARCHAR(100) NULL,
            DestinationCountry NVARCHAR(200) NOT NULL,
            BuyerName          NVARCHAR(300) NULL,
            QuantityKg         DECIMAL(14,3) NULL,
            PackagedUnits      INT NULL,
            DeclaredValueUSD   DECIMAL(14,2) NULL,
            ShipmentDate       DATE NULL,
            EstimatedArrival   DATE NULL,
            Status             NVARCHAR(50) NOT NULL DEFAULT 'draft',
            Incoterms          NVARCHAR(50) NULL,
            PortOfLoading      NVARCHAR(200) NULL,
            PortOfDischarge    NVARCHAR(200) NULL,
            Notes              NVARCHAR(MAX) NULL,
            CreatedAt          DATETIME2 DEFAULT GETDATE(),
            UpdatedAt          DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('ExportShipment') AND name='ActualArrivalDate')
            ALTER TABLE ExportShipment ADD ActualArrivalDate DATE NULL""",
        """IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('ExportShipment') AND name='VesselRef')
            ALTER TABLE ExportShipment ADD VesselRef NVARCHAR(200) NULL""",
        """IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('ExportShipment') AND name='Currency')
            ALTER TABLE ExportShipment ADD Currency NVARCHAR(10) NULL""",
        """IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('ExportShipment') AND name='UnitPriceUSD')
            ALTER TABLE ExportShipment ADD UnitPriceUSD DECIMAL(12,4) NULL""",
        """IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('ExportShipment') AND name='RevenueInvoiceID')
            ALTER TABLE ExportShipment ADD RevenueInvoiceID INT NULL""",
        """IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('ExportShipment') AND name='PackhouseBatchID')
            ALTER TABLE ExportShipment ADD PackhouseBatchID INT NULL""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='PhytosanitaryCert')
        CREATE TABLE PhytosanitaryCert (
            CertID           INT IDENTITY PRIMARY KEY,
            ShipmentID       INT NOT NULL,
            BusinessID       INT NOT NULL,
            CertNumber       NVARCHAR(200) NOT NULL,
            IssuedDate       DATE NULL,
            IssuedBy         NVARCHAR(300) NULL,
            IssuingAuthority NVARCHAR(300) NULL,
            ExpiryDate       DATE NULL,
            DocumentURL      NVARCHAR(500) NULL,
            Status           NVARCHAR(50) NOT NULL DEFAULT 'active',
            Notes            NVARCHAR(MAX) NULL,
            CreatedAt        DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CustomsDocument')
        CREATE TABLE CustomsDocument (
            DocID          INT IDENTITY PRIMARY KEY,
            ShipmentID     INT NOT NULL,
            BusinessID     INT NOT NULL,
            DocType        NVARCHAR(100) NOT NULL,
            DocNumber      NVARCHAR(200) NULL,
            IssuingCountry NVARCHAR(100) NULL,
            FiledDate      DATE NULL,
            IssuedDate     DATE NULL,
            DocumentURL    NVARCHAR(500) NULL,
            Status         NVARCHAR(50) NOT NULL DEFAULT 'pending',
            Notes          NVARCHAR(MAX) NULL,
            CreatedAt      DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('CustomsDocument') AND name='IssuingCountry')
            ALTER TABLE CustomsDocument ADD IssuingCountry NVARCHAR(100) NULL""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ComplianceCertification')
        CREATE TABLE ComplianceCertification (
            CertID      INT IDENTITY PRIMARY KEY,
            BusinessID  INT NOT NULL,
            CertType    NVARCHAR(100) NOT NULL,
            CertNumber  NVARCHAR(200) NULL,
            IssuingBody NVARCHAR(300) NULL,
            IssueDate   DATE NULL,
            ExpiryDate  DATE NULL,
            ScopeNotes  NVARCHAR(MAX) NULL,
            DocumentURL NVARCHAR(500) NULL,
            Status      NVARCHAR(50) NOT NULL DEFAULT 'active',
            CreatedAt   DATETIME2 DEFAULT GETDATE(),
            UpdatedAt   DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='RecallEvent')
        CREATE TABLE RecallEvent (
            RecallID          INT IDENTITY PRIMARY KEY,
            BusinessID        INT NOT NULL,
            RecallRef         NVARCHAR(100) NULL,
            ProductName       NVARCHAR(300) NOT NULL,
            AffectedLots      NVARCHAR(MAX) NULL,
            RecallReason      NVARCHAR(MAX) NOT NULL,
            Severity          NVARCHAR(50) NOT NULL DEFAULT 'voluntary',
            InitiatedDate     DATE NOT NULL,
            ResolutionDate    DATE NULL,
            Status            NVARCHAR(50) NOT NULL DEFAULT 'active',
            AffectedQtyKg     DECIMAL(14,3) NULL,
            NotifiedParties   NVARCHAR(MAX) NULL,
            CorrectiveActions NVARCHAR(MAX) NULL,
            Notes             NVARCHAR(MAX) NULL,
            CreatedAt         DATETIME2 DEFAULT GETDATE(),
            UpdatedAt         DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CropMarginRecord')
        CREATE TABLE CropMarginRecord (
            MarginID       INT IDENTITY PRIMARY KEY,
            BusinessID     INT NOT NULL,
            FieldID        INT NULL,
            CropName       NVARCHAR(300) NOT NULL,
            Season         NVARCHAR(100) NULL,
            HarvestedKg    DECIMAL(14,3) NULL,
            SoldKg         DECIMAL(14,3) NULL,
            RevenueUSD     DECIMAL(14,2) NULL,
            InputCostUSD   DECIMAL(14,2) NULL,
            LaborCostUSD   DECIMAL(14,2) NULL,
            OtherCostUSD   DECIMAL(14,2) NULL,
            TotalCostUSD   DECIMAL(14,2) NULL,
            GrossMarginUSD DECIMAL(14,2) NULL,
            MarginPct      DECIMAL(6,2)  NULL,
            Notes          NVARCHAR(MAX) NULL,
            CreatedAt      DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('CropMarginRecord') AND name='FieldRef')
            ALTER TABLE CropMarginRecord ADD FieldRef NVARCHAR(100) NULL""",
        """IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('CropMarginRecord') AND name='PricePerKg')
            ALTER TABLE CropMarginRecord ADD PricePerKg DECIMAL(12,4) NULL""",
        """IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('CropMarginRecord') AND name='VariableCostUSD')
            ALTER TABLE CropMarginRecord ADD VariableCostUSD DECIMAL(14,2) NULL""",
        """IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('CropMarginRecord') AND name='FixedCostUSD')
            ALTER TABLE CropMarginRecord ADD FixedCostUSD DECIMAL(14,2) NULL""",
    ]
    for s in stmts:
        db.execute(text(s))
    db.commit()
    _ready = True


# ─── Response normalizers ─────────────────────────────────────────────────────

def _ship_to_dict(r):
    m = dict(r._mapping)
    return {
        "shipment_id": m.get("ShipmentID"),
        "shipment_ref": m.get("ShipmentRef"),
        "commodity": m.get("ProductName"),
        "destination_country": m.get("DestinationCountry"),
        "buyer_name": m.get("BuyerName"),
        "vessel_ref": m.get("VesselRef"),
        "estimated_departure": str(m["ShipmentDate"])[:10] if m.get("ShipmentDate") else None,
        "quantity_kg": float(m["QuantityKg"]) if m.get("QuantityKg") is not None else None,
        "unit_price_usd": float(m["UnitPriceUSD"]) if m.get("UnitPriceUSD") is not None else None,
        "total_value_usd": float(m["DeclaredValueUSD"]) if m.get("DeclaredValueUSD") is not None else None,
        "currency": m.get("Currency") or "USD",
        "status": (m.get("Status") or "").lower(),
        "estimated_arrival": str(m["EstimatedArrival"])[:10] if m.get("EstimatedArrival") else None,
        "actual_arrival_date": str(m["ActualArrivalDate"])[:10] if m.get("ActualArrivalDate") else None,
        "revenue_invoice_id": m.get("RevenueInvoiceID"),
        "notes": m.get("Notes"),
        "created_at": str(m.get("CreatedAt") or ""),
    }


def _cert_to_dict(r):
    m = dict(r._mapping)
    return {
        "cert_id": m.get("CertID"),
        "cert_type": m.get("CertType"),
        "cert_number": m.get("CertNumber"),
        "issuing_body": m.get("IssuingBody"),
        "issue_date": str(m["IssueDate"])[:10] if m.get("IssueDate") else None,
        "expiry_date": str(m["ExpiryDate"])[:10] if m.get("ExpiryDate") else None,
        "notes": m.get("ScopeNotes"),
        "status": (m.get("Status") or "").lower(),
    }


def _recall_to_dict(r):
    m = dict(r._mapping)
    return {
        "recall_id": m.get("RecallID"),
        "recall_ref": m.get("RecallRef"),
        "lot_ref": m.get("AffectedLots"),
        "commodity": m.get("ProductName"),
        "reason": m.get("RecallReason"),
        "units_affected": float(m["AffectedQtyKg"]) if m.get("AffectedQtyKg") is not None else None,
        "recall_date": str(m["InitiatedDate"])[:10] if m.get("InitiatedDate") else None,
        "status": (m.get("Status") or "").lower(),
        "resolution_date": str(m["ResolutionDate"])[:10] if m.get("ResolutionDate") else None,
    }


def _margin_to_dict(r):
    m = dict(r._mapping)
    return {
        "margin_id": m.get("MarginID"),
        "crop": m.get("CropName"),
        "season": m.get("Season"),
        "field_ref": m.get("FieldRef"),
        "yield_kg": float(m["HarvestedKg"]) if m.get("HarvestedKg") is not None else None,
        "price_per_kg": float(m["PricePerKg"]) if m.get("PricePerKg") is not None else None,
        "revenue_usd": float(m["RevenueUSD"]) if m.get("RevenueUSD") is not None else None,
        "total_cost_usd": float(m["TotalCostUSD"]) if m.get("TotalCostUSD") is not None else None,
        "gross_margin_usd": float(m["GrossMarginUSD"]) if m.get("GrossMarginUSD") is not None else None,
        "margin_pct": float(m["MarginPct"]) if m.get("MarginPct") is not None else None,
        "notes": m.get("Notes"),
    }


# ─── Revenue recognition on delivery ─────────────────────────────────────────

def _auto_revenue_invoice(db: Session, shipment_id: int, business_id: int,
                           commodity: str, quantity_kg, total_value_usd):
    try:
        acct_count = db.execute(
            text("SELECT COUNT(*) FROM Accounts WHERE BusinessID=:bid"), {"bid": business_id}
        ).scalar()
        if not acct_count:
            return

        # Dedup — only one invoice per shipment
        existing = db.execute(
            text("SELECT RevenueInvoiceID FROM ExportShipment WHERE ShipmentID=:sid"),
            {"sid": shipment_id}
        ).scalar()
        if existing:
            return

        # Revenue account (4xxx preferred, then any Revenue type)
        rev_acct = db.execute(
            text("SELECT TOP 1 AccountID FROM Accounts WHERE BusinessID=:bid AND AccountCode LIKE '4%'"),
            {"bid": business_id}
        ).fetchone()
        if not rev_acct:
            rev_acct = db.execute(
                text("SELECT TOP 1 AccountID FROM Accounts WHERE BusinessID=:bid AND AccountType='Revenue'"),
                {"bid": business_id}
            ).fetchone()
        if not rev_acct:
            return

        # Find or create generic "Export Revenue" customer
        cust = db.execute(
            text("SELECT TOP 1 CustomerID FROM AccountingCustomers WHERE BusinessID=:bid AND DisplayName='Export Revenue'"),
            {"bid": business_id}
        ).fetchone()
        if cust:
            cust_id = cust[0]
        else:
            cust_id = db.execute(text("""
                INSERT INTO AccountingCustomers (BusinessID, DisplayName, CompanyName, PaymentTerms, BillingCountry)
                OUTPUT INSERTED.CustomerID VALUES (:bid, 'Export Revenue', 'Export', 'Net30', 'US')
            """), {"bid": business_id}).fetchone()[0]

        admin = db.execute(
            text("SELECT TOP 1 PeopleID FROM BusinessAccess WHERE BusinessID=:bid ORDER BY CreatedAt ASC"),
            {"bid": business_id}
        ).fetchone()
        admin_id = admin[0] if admin else None

        count = db.execute(
            text("SELECT COUNT(*)+1 FROM Invoices WHERE BusinessID=:bid"), {"bid": business_id}
        ).scalar()
        inv_num = f"INV-EXP-{business_id}-{count:04d}"
        total = float(total_value_usd or 0)
        qty = float(quantity_kg or 1)
        unit_price = round(total / qty, 4) if qty > 0 else total

        new_inv_id = db.execute(text("""
            INSERT INTO Invoices (BusinessID, CustomerID, InvoiceNumber, InvoiceDate, DueDate, Status,
                SubTotal, TaxAmount, TotalAmount, BalanceDue, Notes, PaymentTerms, CreatedBy)
            OUTPUT INSERTED.InvoiceID
            VALUES (:bid,:cid,:num,CAST(GETDATE() AS DATE),CAST(GETDATE() AS DATE),'Paid',
                    :sub,0,:total,0,:notes,'Net30',:by)
        """), {
            "bid": business_id, "cid": cust_id, "num": inv_num,
            "sub": total, "total": total,
            "notes": f"[export-shipment-{shipment_id}] {commodity}",
            "by": admin_id,
        }).fetchone()[0]

        db.execute(text("""
            INSERT INTO InvoiceLines (InvoiceID, BusinessID, AccountID, Description,
                Quantity, UnitPrice, TaxAmount, LineTotal, LineOrder)
            VALUES (:iid,:bid,:aid,:desc,:qty,:uprice,0,:total,1)
        """), {
            "iid": new_inv_id, "bid": business_id, "aid": rev_acct[0],
            "desc": f"{commodity} ({quantity_kg} kg export)",
            "qty": qty, "uprice": unit_price, "total": total,
        })

        db.execute(
            text("UPDATE ExportShipment SET RevenueInvoiceID=:iid WHERE ShipmentID=:sid"),
            {"iid": new_inv_id, "sid": shipment_id}
        )

        from routers.notifications import notify_business
        notify_business(db, business_id, "revenue_recognized", "Export Revenue Recognized",
                        f"{commodity}: ${total:,.2f} invoice created on delivery",
                        link_path=f"/accounting?BusinessID={business_id}",
                        entity_type="ExportShipment", entity_id=shipment_id)
    except Exception as e:
        print(f"[export] revenue recognition failed: {e}")


# ─── Shipments ────────────────────────────────────────────────────────────────

@router.get("/shipments")
def list_shipments(business_id: int = Query(...), status: Optional[str] = None,
                   db: Session = Depends(get_db)):
    _ensure(db)
    q = "SELECT * FROM ExportShipment WHERE BusinessID=:bid"
    params: dict = {"bid": business_id}
    if status:
        q += " AND Status=:st"; params["st"] = status
    q += " ORDER BY ShipmentDate DESC, CreatedAt DESC"
    rows = db.execute(text(q), params).fetchall()
    return [_ship_to_dict(r) for r in rows]


@router.post("/shipments")
def create_shipment(business_id: int = Query(...), body: dict = Body(...),
                    db: Session = Depends(get_db)):
    _ensure(db)
    commodity = body.get("commodity") or body.get("ProductName") or ""
    dest = body.get("destination_country") or body.get("DestinationCountry") or ""
    buyer = body.get("buyer_name") or body.get("BuyerName")
    vessel = body.get("vessel_ref") or body.get("VesselRef")
    est_dep = body.get("estimated_departure") or body.get("ShipmentDate")
    qty = body.get("quantity_kg") or body.get("QuantityKg")
    unit_price = body.get("unit_price_usd") or body.get("UnitPriceUSD")
    currency = body.get("currency") or body.get("Currency") or "USD"
    total_val = body.get("DeclaredValueUSD")
    if not total_val and qty and unit_price:
        total_val = round(float(qty) * float(unit_price), 2)
    status = body.get("status") or body.get("Status") or "draft"

    count = db.execute(
        text("SELECT COUNT(*)+1 FROM ExportShipment WHERE BusinessID=:bid"), {"bid": business_id}
    ).scalar()
    ref = f"EXP-{business_id}-{count:04d}"
    r = db.execute(text("""
        INSERT INTO ExportShipment (BusinessID,ShipmentRef,ProductName,DestinationCountry,
            BuyerName,VesselRef,QuantityKg,UnitPriceUSD,DeclaredValueUSD,Currency,
            ShipmentDate,EstimatedArrival,Status,Notes)
        OUTPUT INSERTED.ShipmentID
        VALUES (:bid,:ref,:prod,:dest,:buyer,:vessel,:qty,:uprice,:val,:curr,:dep,:arr,:st,:notes)
    """), {
        "bid": business_id, "ref": ref, "prod": commodity, "dest": dest,
        "buyer": buyer, "vessel": vessel, "qty": qty, "uprice": unit_price,
        "val": total_val, "curr": currency, "dep": est_dep,
        "arr": body.get("estimated_arrival") or body.get("EstimatedArrival"),
        "st": status, "notes": body.get("notes") or body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"shipment_id": r[0], "shipment_ref": ref}


@router.put("/shipments/{shipment_id}/status")
def update_shipment_status(shipment_id: int, business_id: int = Query(...),
                           body: dict = Body(...), db: Session = Depends(get_db)):
    new_status = (body.get("status") or body.get("Status") or "").lower()
    actual_arrival = body.get("actual_arrival_date")

    if actual_arrival:
        db.execute(text("""
            UPDATE ExportShipment
            SET Status=:st, ActualArrivalDate=:arr, UpdatedAt=GETDATE()
            WHERE ShipmentID=:sid AND BusinessID=:bid
        """), {"st": new_status, "arr": actual_arrival, "sid": shipment_id, "bid": business_id})
    else:
        db.execute(text("""
            UPDATE ExportShipment SET Status=:st, UpdatedAt=GETDATE()
            WHERE ShipmentID=:sid AND BusinessID=:bid
        """), {"st": new_status, "sid": shipment_id, "bid": business_id})

    if new_status == "delivered":
        ship = db.execute(
            text("SELECT ProductName, QuantityKg, DeclaredValueUSD FROM ExportShipment WHERE ShipmentID=:sid"),
            {"sid": shipment_id}
        ).fetchone()
        if ship:
            db.commit()
            _auto_revenue_invoice(db, shipment_id, business_id, ship[0], ship[1], ship[2])

    db.commit()
    return {"ok": True}


# ─── Phytosanitary Certificates ───────────────────────────────────────────────

@router.get("/shipments/{shipment_id}/phyto-certs")
def get_phyto(shipment_id: int, business_id: int = Query(...),
              db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(
        text("SELECT * FROM PhytosanitaryCert WHERE ShipmentID=:sid ORDER BY IssuedDate DESC"),
        {"sid": shipment_id}
    ).fetchall()
    return [{
        "cert_number": r.CertNumber,
        "issuing_authority": r.IssuingAuthority,
        "issue_date": str(r.IssuedDate)[:10] if r.IssuedDate else None,
        "expiry_date": str(r.ExpiryDate)[:10] if r.ExpiryDate else None,
        "notes": r.Notes,
    } for r in rows]


@router.post("/shipments/{shipment_id}/phyto-certs")
def add_phyto(shipment_id: int, business_id: int = Query(...),
              body: dict = Body(...), db: Session = Depends(get_db)):
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO PhytosanitaryCert (ShipmentID,BusinessID,CertNumber,IssuedDate,
            IssuingAuthority,ExpiryDate,Status,Notes)
        OUTPUT INSERTED.CertID
        VALUES (:sid,:bid,:num,:idt,:auth,:exp,'active',:notes)
    """), {
        "sid": shipment_id, "bid": business_id,
        "num": body.get("cert_number") or body.get("CertNumber"),
        "idt": body.get("issue_date") or body.get("IssuedDate"),
        "auth": body.get("issuing_authority") or body.get("IssuingAuthority"),
        "exp": body.get("expiry_date") or body.get("ExpiryDate"),
        "notes": body.get("notes") or body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"CertID": r[0]}


# ─── Customs Documents ────────────────────────────────────────────────────────

@router.get("/shipments/{shipment_id}/customs-docs")
def get_customs(shipment_id: int, business_id: int = Query(...),
                db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(
        text("SELECT * FROM CustomsDocument WHERE ShipmentID=:sid ORDER BY IssuedDate DESC"),
        {"sid": shipment_id}
    ).fetchall()
    return [{
        "doc_type": r.DocType,
        "doc_number": r.DocNumber,
        "issuing_country": r.IssuingCountry if hasattr(r, 'IssuingCountry') else None,
        "issue_date": str(r.IssuedDate)[:10] if r.IssuedDate else None,
        "notes": r.Notes,
    } for r in rows]


@router.post("/shipments/{shipment_id}/customs-docs")
def add_customs(shipment_id: int, business_id: int = Query(...),
                body: dict = Body(...), db: Session = Depends(get_db)):
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO CustomsDocument (ShipmentID,BusinessID,DocType,DocNumber,
            IssuingCountry,IssuedDate,Status,Notes)
        OUTPUT INSERTED.DocID
        VALUES (:sid,:bid,:dt,:num,:country,:id,'pending',:notes)
    """), {
        "sid": shipment_id, "bid": business_id,
        "dt": body.get("doc_type") or body.get("DocType"),
        "num": body.get("doc_number") or body.get("DocNumber"),
        "country": body.get("issuing_country") or body.get("IssuingCountry"),
        "id": body.get("issue_date") or body.get("IssuedDate"),
        "notes": body.get("notes") or body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"DocID": r[0]}


# ─── Compliance Certifications (GlobalGAP / USDA Organic / etc.) ──────────────

@router.get("/certifications")
@router.get("/compliance-certs")
def list_compliance_certs(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(
        text("SELECT * FROM ComplianceCertification WHERE BusinessID=:bid ORDER BY ExpiryDate ASC"),
        {"bid": business_id}
    ).fetchall()
    return [_cert_to_dict(r) for r in rows]


@router.post("/certifications")
@router.post("/compliance-certs")
def add_compliance_cert(business_id: int = Query(...), body: dict = Body(...),
                        db: Session = Depends(get_db)):
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO ComplianceCertification (BusinessID,CertType,CertNumber,IssuingBody,
            IssueDate,ExpiryDate,ScopeNotes,Status)
        OUTPUT INSERTED.CertID
        VALUES (:bid,:ct,:num,:body,:id,:exp,:scope,'active')
    """), {
        "bid": business_id,
        "ct": body.get("cert_type") or body.get("CertType"),
        "num": body.get("cert_number") or body.get("CertNumber"),
        "body": body.get("issuing_body") or body.get("IssuingBody"),
        "id": body.get("issue_date") or body.get("IssueDate"),
        "exp": body.get("expiry_date") or body.get("ExpiryDate"),
        "scope": body.get("notes") or body.get("ScopeNotes"),
    }).fetchone()
    db.commit()
    return {"cert_id": r[0]}


@router.delete("/certifications/{cert_id}")
@router.delete("/compliance-certs/{cert_id}")
def delete_compliance_cert(cert_id: int, business_id: int = Query(...),
                            db: Session = Depends(get_db)):
    db.execute(
        text("DELETE FROM ComplianceCertification WHERE CertID=:cid AND BusinessID=:bid"),
        {"cid": cert_id, "bid": business_id}
    )
    db.commit()
    return {"ok": True}


# ─── Recall Management ────────────────────────────────────────────────────────

@router.get("/recalls")
def list_recalls(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(
        text("SELECT * FROM RecallEvent WHERE BusinessID=:bid ORDER BY InitiatedDate DESC"),
        {"bid": business_id}
    ).fetchall()
    return [_recall_to_dict(r) for r in rows]


@router.post("/recalls")
def create_recall(business_id: int = Query(...), body: dict = Body(...),
                  db: Session = Depends(get_db)):
    _ensure(db)
    count = db.execute(
        text("SELECT COUNT(*)+1 FROM RecallEvent WHERE BusinessID=:bid"), {"bid": business_id}
    ).scalar()
    ref = f"RCL-{business_id}-{count:04d}"
    r = db.execute(text("""
        INSERT INTO RecallEvent (BusinessID,RecallRef,ProductName,AffectedLots,RecallReason,
            Severity,InitiatedDate,Status,AffectedQtyKg,Notes)
        OUTPUT INSERTED.RecallID
        VALUES (:bid,:ref,:prod,:lots,:reason,:sev,:dt,'active',:qty,:notes)
    """), {
        "bid": business_id, "ref": ref,
        "prod": body.get("commodity") or body.get("ProductName") or "",
        "lots": body.get("lot_ref") or body.get("AffectedLots"),
        "reason": body.get("reason") or body.get("RecallReason") or "",
        "sev": body.get("severity") or "voluntary",
        "dt": body.get("recall_date") or body.get("InitiatedDate") or str(date.today()),
        "qty": body.get("units_affected") or body.get("AffectedQtyKg"),
        "notes": body.get("notes") or body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"recall_id": r[0], "recall_ref": ref}


@router.put("/recalls/{recall_id}/resolve")
def resolve_recall(recall_id: int, business_id: int = Query(...),
                   body: dict = Body(...), db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE RecallEvent
        SET Status='resolved', ResolutionDate=CAST(GETDATE() AS DATE),
            CorrectiveActions=:actions, UpdatedAt=GETDATE()
        WHERE RecallID=:rid AND BusinessID=:bid
    """), {
        "actions": body.get("resolution_notes") or body.get("CorrectiveActions"),
        "rid": recall_id, "bid": business_id,
    })
    db.commit()
    return {"ok": True}


# ─── Crop Margin Records ──────────────────────────────────────────────────────

@router.get("/crop-margins")
def list_margins(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(
        text("SELECT * FROM CropMarginRecord WHERE BusinessID=:bid ORDER BY CreatedAt DESC"),
        {"bid": business_id}
    ).fetchall()
    return [_margin_to_dict(r) for r in rows]


@router.post("/crop-margins")
def create_margin(business_id: int = Query(...), body: dict = Body(...),
                  db: Session = Depends(get_db)):
    _ensure(db)
    yield_kg = float(body.get("yield_kg") or body.get("HarvestedKg") or 0)
    price_kg = float(body.get("price_per_kg") or body.get("PricePerKg") or 0)
    variable = float(body.get("variable_cost_usd") or body.get("InputCostUSD") or 0)
    fixed = float(body.get("fixed_cost_usd") or body.get("LaborCostUSD") or 0)
    other = float(body.get("OtherCostUSD") or 0)
    revenue = round(yield_kg * price_kg, 2) if (yield_kg and price_kg) else float(body.get("RevenueUSD") or 0)
    total_cost = variable + fixed + other
    gross = round(revenue - total_cost, 2)
    margin_pct = round(gross / revenue * 100, 2) if revenue > 0 else None

    r = db.execute(text("""
        INSERT INTO CropMarginRecord (BusinessID,CropName,Season,FieldRef,HarvestedKg,
            PricePerKg,RevenueUSD,VariableCostUSD,FixedCostUSD,InputCostUSD,LaborCostUSD,
            OtherCostUSD,TotalCostUSD,GrossMarginUSD,MarginPct,Notes)
        OUTPUT INSERTED.MarginID
        VALUES (:bid,:crop,:season,:fref,:hkg,:pkg,:rev,:var,:fixed,:var,:fixed,:other,:total,:gm,:pct,:notes)
    """), {
        "bid": business_id,
        "crop": body.get("crop") or body.get("CropName") or "",
        "season": body.get("season") or body.get("Season"),
        "fref": body.get("field_ref") or body.get("FieldRef"),
        "hkg": yield_kg, "pkg": price_kg, "rev": revenue,
        "var": variable, "fixed": fixed, "other": other,
        "total": total_cost, "gm": gross, "pct": margin_pct,
        "notes": body.get("notes") or body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"margin_id": r[0]}


# ─── Summary ─────────────────────────────────────────────────────────────────

@router.get("/summary")
def export_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    ship = db.execute(text("""
        SELECT
            COUNT(*) AS Total,
            SUM(CASE WHEN Status='cleared'      THEN 1 ELSE 0 END) AS Cleared,
            SUM(CASE WHEN Status='pending_docs' THEN 1 ELSE 0 END) AS PendingDocs,
            SUM(CASE WHEN Status='shipped'      THEN 1 ELSE 0 END) AS Shipped,
            SUM(CASE WHEN Status='delivered'    THEN 1 ELSE 0 END) AS Delivered
        FROM ExportShipment WHERE BusinessID=:bid
    """), {"bid": business_id}).fetchone()
    active_recalls = db.execute(
        text("SELECT COUNT(*) FROM RecallEvent WHERE BusinessID=:bid AND Status='active'"),
        {"bid": business_id}
    ).scalar()
    cert_count = db.execute(
        text("SELECT COUNT(*) FROM ComplianceCertification WHERE BusinessID=:bid AND Status='active'"),
        {"bid": business_id}
    ).scalar()
    avg_pct = db.execute(
        text("SELECT AVG(MarginPct) FROM CropMarginRecord WHERE BusinessID=:bid"),
        {"bid": business_id}
    ).scalar()
    return {
        "total_shipments": ship[0] if ship else 0,
        "cleared": ship[1] if ship else 0,
        "pending_docs": ship[2] if ship else 0,
        "shipped": ship[3] if ship else 0,
        "delivered": ship[4] if ship else 0,
        "active_recalls": active_recalls or 0,
        "compliance_certs": cert_count or 0,
        "avg_margin_pct": float(avg_pct) if avg_pct else None,
    }


# ─── CSV Export ───────────────────────────────────────────────────────────────

@router.get("/export")
def export_shipments_csv(business_id: int = Query(...), status: Optional[str] = None,
                         db: Session = Depends(get_db)):
    _ensure(db)
    q = """
        SELECT ShipmentID, ShipmentRef, ProductName, DestinationCountry, BuyerName,
               VesselRef, QuantityKg, UnitPriceUSD, DeclaredValueUSD, Currency,
               ShipmentDate, EstimatedArrival, ActualArrivalDate, Status,
               RevenueInvoiceID, Notes, CreatedAt
        FROM ExportShipment WHERE BusinessID=:bid
    """
    params: dict = {"bid": business_id}
    if status:
        q += " AND Status=:st"; params["st"] = status
    q += " ORDER BY ShipmentDate DESC"
    rows = db.execute(text(q), params).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ShipmentID", "ShipmentRef", "Product", "Destination", "Buyer",
                     "VesselRef", "QuantityKg", "UnitPriceUSD", "TotalValueUSD", "Currency",
                     "ShipmentDate", "EstimatedArrival", "ActualArrivalDate", "Status",
                     "RevenueInvoiceID", "Notes", "CreatedAt"])
    for r in rows:
        writer.writerow([r.ShipmentID, r.ShipmentRef, r.ProductName, r.DestinationCountry,
                         r.BuyerName, r.VesselRef, r.QuantityKg, r.UnitPriceUSD,
                         r.DeclaredValueUSD, r.Currency, r.ShipmentDate, r.EstimatedArrival,
                         r.ActualArrivalDate, r.Status, r.RevenueInvoiceID, r.Notes, r.CreatedAt])
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=shipments_{business_id}.csv"},
    )
