"""
routers/outgrower.py
Contract Farming / Outgrower Management — farmer registration, contract engine,
input distribution to smallholders, buy-back workflows.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional
from datetime import date

router = APIRouter(prefix="/api/outgrower", tags=["outgrower"])
_ready = False


def _ensure(db: Session):
    global _ready
    if _ready:
        return
    stmts = [
        # SettlementBillID added here — idempotent
        """IF NOT EXISTS (
            SELECT 1 FROM sys.columns
            WHERE object_id=OBJECT_ID('OutgrowerDelivery') AND name='SettlementBillID'
        ) ALTER TABLE OutgrowerDelivery ADD SettlementBillID INT NULL""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OutgrowerFarmer')
        CREATE TABLE OutgrowerFarmer (
            FarmerID          INT IDENTITY PRIMARY KEY,
            BusinessID        INT NOT NULL,
            FullName          NVARCHAR(200) NOT NULL,
            Phone             NVARCHAR(50)  NULL,
            Email             NVARCHAR(200) NULL,
            Village           NVARCHAR(200) NULL,
            District          NVARCHAR(200) NULL,
            TotalAcreage      DECIMAL(10,2) NULL,
            NationalID        NVARCHAR(100) NULL,
            BankName          NVARCHAR(200) NULL,
            BankAccount       NVARCHAR(100) NULL,
            MobileMoneyNumber NVARCHAR(100) NULL,
            Status            NVARCHAR(50)  NOT NULL DEFAULT 'active',
            JoinedDate        DATE NULL,
            Notes             NVARCHAR(MAX) NULL,
            CreatedAt         DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OutgrowerContract')
        CREATE TABLE OutgrowerContract (
            ContractID      INT IDENTITY PRIMARY KEY,
            FarmerID        INT NOT NULL,
            BusinessID      INT NOT NULL,
            CropName        NVARCHAR(200) NOT NULL,
            Season          NVARCHAR(100) NULL,
            PlantingArea    DECIMAL(10,2) NULL,
            TargetQtyKg     DECIMAL(12,2) NULL,
            PricePerKg      DECIMAL(10,4) NULL,
            StartDate       DATE NULL,
            EndDate         DATE NULL,
            Status          NVARCHAR(50) NOT NULL DEFAULT 'draft',
            ContractRef     NVARCHAR(100) NULL,
            QualitySpecs    NVARCHAR(MAX) NULL,
            Notes           NVARCHAR(MAX) NULL,
            SignedDate      DATE NULL,
            CreatedAt       DATETIME2 DEFAULT GETDATE(),
            UpdatedAt       DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OutgrowerInputDistribution')
        CREATE TABLE OutgrowerInputDistribution (
            DistID        INT IDENTITY PRIMARY KEY,
            ContractID    INT NOT NULL,
            FarmerID      INT NOT NULL,
            BusinessID    INT NOT NULL,
            InputType     NVARCHAR(100) NOT NULL,
            InputName     NVARCHAR(200) NOT NULL,
            Quantity      DECIMAL(10,2) NULL,
            Unit          NVARCHAR(50)  NULL,
            UnitCost      DECIMAL(10,2) NULL,
            TotalValue    DECIMAL(12,2) NULL,
            DistributedDate DATE NOT NULL,
            RecoveryMethod  NVARCHAR(100) NULL,
            Recovered       BIT DEFAULT 0,
            Notes         NVARCHAR(MAX) NULL,
            CreatedAt     DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OutgrowerDelivery')
        CREATE TABLE OutgrowerDelivery (
            DeliveryID      INT IDENTITY PRIMARY KEY,
            ContractID      INT NOT NULL,
            FarmerID        INT NOT NULL,
            BusinessID      INT NOT NULL,
            DeliveryDate    DATE NOT NULL,
            GrossWeightKg   DECIMAL(12,2) NULL,
            MoistureDeductKg DECIMAL(12,2) NULL,
            NetWeightKg     DECIMAL(12,2) NULL,
            QualityGrade    NVARCHAR(50)  NULL,
            PricePerKg      DECIMAL(10,4) NULL,
            GrossPayment    DECIMAL(12,2) NULL,
            InputDeductions DECIMAL(12,2) NULL,
            NetPayment      DECIMAL(12,2) NULL,
            PaymentStatus   NVARCHAR(50)  NOT NULL DEFAULT 'pending',
            PaymentDate     DATE NULL,
            WeighbridgeTicket NVARCHAR(100) NULL,
            Notes           NVARCHAR(MAX) NULL,
            CreatedAt       DATETIME2 DEFAULT GETDATE()
        )""",
    ]
    for s in stmts:
        db.execute(text(s))
    db.commit()
    _ready = True


# ─── Farmers ─────────────────────────────────────────────────────────────────

@router.get("/farmers")
def list_farmers(business_id: int = Query(...), status: Optional[str] = None, db: Session = Depends(get_db)):
    _ensure(db)
    q = "SELECT * FROM OutgrowerFarmer WHERE BusinessID=:bid"
    params = {"bid": business_id}
    if status:
        q += " AND Status=:st"; params["st"] = status
    q += " ORDER BY FullName"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/farmers")
def create_farmer(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO OutgrowerFarmer (BusinessID,FullName,Phone,Email,Village,District,
            TotalAcreage,NationalID,BankName,BankAccount,MobileMoneyNumber,Status,JoinedDate,Notes)
        OUTPUT INSERTED.FarmerID
        VALUES (:bid,:name,:phone,:email,:vil,:dist,:acres,:nid,:bank,:acct,:mmn,:st,:jd,:notes)
    """), {
        "bid": body["BusinessID"], "name": body["FullName"],
        "phone": body.get("Phone"), "email": body.get("Email"),
        "vil": body.get("Village"), "dist": body.get("District"),
        "acres": body.get("TotalAcreage"), "nid": body.get("NationalID"),
        "bank": body.get("BankName"), "acct": body.get("BankAccount"),
        "mmn": body.get("MobileMoneyNumber"), "st": body.get("Status", "active"),
        "jd": body.get("JoinedDate"), "notes": body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"FarmerID": r[0]}


@router.put("/farmers/{farmer_id}")
def update_farmer(farmer_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OutgrowerFarmer SET FullName=:name,Phone=:phone,Email=:email,Village=:vil,
            District=:dist,TotalAcreage=:acres,NationalID=:nid,BankName=:bank,
            BankAccount=:acct,MobileMoneyNumber=:mmn,Status=:st,JoinedDate=:jd,Notes=:notes
        WHERE FarmerID=:fid AND BusinessID=:bid
    """), {
        "name": body.get("FullName"), "phone": body.get("Phone"), "email": body.get("Email"),
        "vil": body.get("Village"), "dist": body.get("District"), "acres": body.get("TotalAcreage"),
        "nid": body.get("NationalID"), "bank": body.get("BankName"), "acct": body.get("BankAccount"),
        "mmn": body.get("MobileMoneyNumber"), "st": body.get("Status"),
        "jd": body.get("JoinedDate"), "notes": body.get("Notes"),
        "fid": farmer_id, "bid": body["BusinessID"],
    })
    db.commit()
    return {"ok": True}


@router.delete("/farmers/{farmer_id}")
def delete_farmer(farmer_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OutgrowerFarmer WHERE FarmerID=:fid AND BusinessID=:bid"),
               {"fid": farmer_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ─── Contracts ────────────────────────────────────────────────────────────────

@router.get("/contracts")
def list_contracts(business_id: int = Query(...), farmer_id: Optional[int] = None, db: Session = Depends(get_db)):
    _ensure(db)
    q = """
        SELECT c.*, f.FullName AS FarmerName, f.Village
        FROM OutgrowerContract c
        JOIN OutgrowerFarmer f ON f.FarmerID=c.FarmerID
        WHERE c.BusinessID=:bid
    """
    params = {"bid": business_id}
    if farmer_id:
        q += " AND c.FarmerID=:fid"; params["fid"] = farmer_id
    q += " ORDER BY c.CreatedAt DESC"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/contracts")
def create_contract(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO OutgrowerContract (FarmerID,BusinessID,CropName,Season,PlantingArea,
            TargetQtyKg,PricePerKg,StartDate,EndDate,Status,ContractRef,QualitySpecs,Notes,SignedDate)
        OUTPUT INSERTED.ContractID
        VALUES (:fid,:bid,:crop,:season,:area,:qty,:price,:sd,:ed,:st,:ref,:qs,:notes,:signed)
    """), {
        "fid": body["FarmerID"], "bid": body["BusinessID"], "crop": body["CropName"],
        "season": body.get("Season"), "area": body.get("PlantingArea"),
        "qty": body.get("TargetQtyKg"), "price": body.get("PricePerKg"),
        "sd": body.get("StartDate"), "ed": body.get("EndDate"),
        "st": body.get("Status", "draft"), "ref": body.get("ContractRef"),
        "qs": body.get("QualitySpecs"), "notes": body.get("Notes"),
        "signed": body.get("SignedDate"),
    }).fetchone()
    db.commit()
    return {"ContractID": r[0]}


@router.put("/contracts/{contract_id}/status")
def update_contract_status(contract_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OutgrowerContract SET Status=:st, UpdatedAt=GETDATE()
        WHERE ContractID=:cid AND BusinessID=:bid
    """), {"st": body["Status"], "cid": contract_id, "bid": body["BusinessID"]})
    db.commit()
    return {"ok": True}


# ─── Input Distribution ───────────────────────────────────────────────────────

@router.get("/distributions")
def list_distributions(business_id: int = Query(...), contract_id: Optional[int] = None, db: Session = Depends(get_db)):
    _ensure(db)
    q = """
        SELECT d.*, f.FullName AS FarmerName, c.CropName
        FROM OutgrowerInputDistribution d
        JOIN OutgrowerFarmer f ON f.FarmerID=d.FarmerID
        JOIN OutgrowerContract c ON c.ContractID=d.ContractID
        WHERE d.BusinessID=:bid
    """
    params = {"bid": business_id}
    if contract_id:
        q += " AND d.ContractID=:cid"; params["cid"] = contract_id
    q += " ORDER BY d.DistributedDate DESC"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/distributions")
def create_distribution(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    qty = body.get("Quantity") or 0
    unit_cost = body.get("UnitCost") or 0
    total = round(float(qty) * float(unit_cost), 2)
    r = db.execute(text("""
        INSERT INTO OutgrowerInputDistribution (ContractID,FarmerID,BusinessID,InputType,InputName,
            Quantity,Unit,UnitCost,TotalValue,DistributedDate,RecoveryMethod,Notes)
        OUTPUT INSERTED.DistID
        VALUES (:cid,:fid,:bid,:itype,:iname,:qty,:unit,:uc,:tv,:dt,:rm,:notes)
    """), {
        "cid": body["ContractID"], "fid": body["FarmerID"], "bid": body["BusinessID"],
        "itype": body["InputType"], "iname": body["InputName"],
        "qty": qty, "unit": body.get("Unit"), "uc": unit_cost, "tv": total,
        "dt": body["DistributedDate"], "rm": body.get("RecoveryMethod"), "notes": body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"DistID": r[0]}


# ─── Deliveries / Buy-back ────────────────────────────────────────────────────

@router.get("/deliveries")
def list_deliveries(business_id: int = Query(...), contract_id: Optional[int] = None, db: Session = Depends(get_db)):
    _ensure(db)
    q = """
        SELECT d.*, f.FullName AS FarmerName, c.CropName
        FROM OutgrowerDelivery d
        JOIN OutgrowerFarmer f ON f.FarmerID=d.FarmerID
        JOIN OutgrowerContract c ON c.ContractID=d.ContractID
        WHERE d.BusinessID=:bid
    """
    params = {"bid": business_id}
    if contract_id:
        q += " AND d.ContractID=:cid"; params["cid"] = contract_id
    q += " ORDER BY d.DeliveryDate DESC"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/deliveries")
def create_delivery(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO OutgrowerDelivery (ContractID,FarmerID,BusinessID,DeliveryDate,GrossWeightKg,
            MoistureDeductKg,NetWeightKg,QualityGrade,PricePerKg,GrossPayment,
            InputDeductions,NetPayment,PaymentStatus,WeighbridgeTicket,Notes)
        OUTPUT INSERTED.DeliveryID
        VALUES (:cid,:fid,:bid,:dt,:gross,:moist,:net,:grade,:ppk,:gpay,:deduct,:npay,:pst,:wbt,:notes)
    """), {
        "cid": body["ContractID"], "fid": body["FarmerID"], "bid": body["BusinessID"],
        "dt": body["DeliveryDate"],
        "gross": body.get("GrossWeightKg"), "moist": body.get("MoistureDeductKg"),
        "net": body.get("NetWeightKg"), "grade": body.get("QualityGrade"),
        "ppk": body.get("PricePerKg"), "gpay": body.get("GrossPayment"),
        "deduct": body.get("InputDeductions"), "npay": body.get("NetPayment"),
        "pst": body.get("PaymentStatus", "pending"),
        "wbt": body.get("WeighbridgeTicket"), "notes": body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"DeliveryID": r[0]}


def _auto_settle_to_accounting(db: Session, delivery_id: int, business_id: int):
    """Create a paid Bill in Accounting for this outgrower delivery settlement."""
    try:
        # Skip if accounting hasn't been set up for this business
        acct_count = db.execute(
            text("SELECT COUNT(*) FROM Accounts WHERE BusinessID=:bid"), {"bid": business_id}
        ).scalar()
        if not acct_count:
            return

        # Load delivery + farmer + contract
        row = db.execute(text("""
            SELECT d.*, f.FullName AS FarmerName, f.Phone AS FarmerPhone,
                   f.Email AS FarmerEmail, c.CropName, c.Season
            FROM OutgrowerDelivery d
            JOIN OutgrowerFarmer f ON f.FarmerID = d.FarmerID
            JOIN OutgrowerContract c ON c.ContractID = d.ContractID
            WHERE d.DeliveryID=:did AND d.BusinessID=:bid
        """), {"did": delivery_id, "bid": business_id}).fetchone()
        if not row:
            return

        # Skip if bill already linked
        if row.SettlementBillID:
            return

        net_pay   = float(row.NetPayment   or 0)
        gross_pay = float(row.GrossPayment or 0)
        deduct    = float(row.InputDeductions or 0)

        # Find or create AccountingVendor for this farmer
        vendor = db.execute(text("""
            SELECT TOP 1 VendorID FROM AccountingVendors
            WHERE BusinessID=:bid AND DisplayName=:name AND IsActive=1
        """), {"bid": business_id, "name": row.FarmerName}).fetchone()

        if vendor:
            vendor_id = vendor.VendorID
        else:
            v_row = db.execute(text("""
                INSERT INTO AccountingVendors
                    (BusinessID, DisplayName, CompanyName, Phone, Email, PaymentTerms, Notes)
                OUTPUT INSERTED.VendorID
                VALUES (:bid, :name, :name, :phone, :email, 'Immediate', 'Auto-created from outgrower settlement')
            """), {
                "bid": business_id, "name": row.FarmerName,
                "phone": row.FarmerPhone, "email": row.FarmerEmail,
            }).fetchone()
            vendor_id = v_row.VendorID

        # Auto-generate bill number
        count = db.execute(
            text("SELECT COUNT(*)+1 FROM Bills WHERE BusinessID=:bid"), {"bid": business_id}
        ).scalar()
        bill_num = f"SETTLE-{business_id}-{count:04d}"

        # Get a crop-purchases expense account (5xxx range preferred)
        crop_acct = db.execute(text("""
            SELECT TOP 1 AccountID FROM Accounts
            WHERE BusinessID=:bid AND AccountNumber LIKE '5%' AND IsActive=1
            ORDER BY AccountNumber
        """), {"bid": business_id}).fetchone()
        acct_id = crop_acct.AccountID if crop_acct else None

        # Get a responsible user (highest-access member of the business)
        admin = db.execute(text("""
            SELECT TOP 1 PeopleID FROM BusinessAccess
            WHERE BusinessID=:bid AND Active=1
            ORDER BY AccessLevelID DESC
        """), {"bid": business_id}).fetchone()
        created_by = admin.PeopleID if admin else None

        desc_main = (
            f"Outgrower settlement: {row.CropName} delivery {row.DeliveryDate} "
            f"— {row.NetWeightKg or ''} kg net, grade {row.QualityGrade or 'N/A'}"
        )
        notes = f"DeliveryID:{delivery_id} | ContractID:{row.ContractID} | Ticket:{row.WeighbridgeTicket or ''}"

        b_row = db.execute(text("""
            INSERT INTO Bills
                (BusinessID, VendorID, BillNumber, BillDate, DueDate, Status,
                 SubTotal, TaxAmount, TotalAmount, BalanceDue, Notes, CreatedBy)
            OUTPUT INSERTED.BillID
            VALUES (:bid, :vid, :num, CAST(GETDATE() AS DATE), CAST(GETDATE() AS DATE),
                    'Paid', :sub, 0, :total, 0, :notes, :by)
        """), {
            "bid": business_id, "vid": vendor_id, "num": bill_num,
            "sub": net_pay, "total": net_pay, "notes": notes, "by": created_by,
        }).fetchone()
        bill_id = b_row.BillID

        # Line 1: gross crop purchase
        db.execute(text("""
            INSERT INTO BillLines
                (BillID, BusinessID, AccountID, Description, Quantity, UnitPrice, TaxAmount, LineTotal, LineOrder)
            VALUES (:bill, :bid, :acct, :desc, 1, :price, 0, :price, 0)
        """), {"bill": bill_id, "bid": business_id, "acct": acct_id,
               "desc": f"Crop purchase: {row.CropName} {row.NetWeightKg or ''}kg @ {row.PricePerKg or 0}/kg",
               "price": gross_pay})

        # Line 2: input deductions (negative) if any
        if deduct > 0:
            db.execute(text("""
                INSERT INTO BillLines
                    (BillID, BusinessID, AccountID, Description, Quantity, UnitPrice, TaxAmount, LineTotal, LineOrder)
                VALUES (:bill, :bid, :acct, :desc, 1, :price, 0, :price, 1)
            """), {"bill": bill_id, "bid": business_id, "acct": acct_id,
                   "desc": "Less: input cost recovery deduction",
                   "price": -deduct})

        # Link bill back to delivery
        db.execute(text("""
            UPDATE OutgrowerDelivery SET SettlementBillID=:bid2
            WHERE DeliveryID=:did AND BusinessID=:bid
        """), {"bid2": bill_id, "did": delivery_id, "bid": business_id})

        # Notify
        from routers.notifications import notify_business
        notify_business(
            db, business_id, type="outgrower_settlement_posted",
            title=f"Settlement posted: {row.FarmerName}",
            body=f"{row.CropName} delivery settled. Net payment: {net_pay:.2f}. Bill {bill_num} created.",
            link_path=f"/accounting?tab=bills&BusinessID={business_id}",
            entity_type="Bill", entity_id=bill_id,
        )
    except Exception as _e:
        print(f"[outgrower-settle] accounting sync failed: {_e}")


@router.put("/deliveries/{delivery_id}/pay")
def mark_paid(delivery_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OutgrowerDelivery SET PaymentStatus='paid', PaymentDate=:dt
        WHERE DeliveryID=:did AND BusinessID=:bid
    """), {"dt": body.get("PaymentDate"), "did": delivery_id, "bid": body["BusinessID"]})
    db.commit()
    _auto_settle_to_accounting(db, delivery_id, body["BusinessID"])
    db.commit()
    return {"ok": True}


# ─── Dashboard summary ────────────────────────────────────────────────────────

@router.get("/summary")
def outgrower_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    farmers = db.execute(text(
        "SELECT COUNT(*) AS c, SUM(TotalAcreage) AS acres FROM OutgrowerFarmer WHERE BusinessID=:bid AND Status='active'"
    ), {"bid": business_id}).fetchone()
    contracts = db.execute(text(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN Status='active' THEN 1 ELSE 0 END) AS active FROM OutgrowerContract WHERE BusinessID=:bid"
    ), {"bid": business_id}).fetchone()
    deliveries = db.execute(text(
        "SELECT ISNULL(SUM(NetWeightKg),0) AS TotalKg, ISNULL(SUM(NetPayment),0) AS TotalPaid FROM OutgrowerDelivery WHERE BusinessID=:bid"
    ), {"bid": business_id}).fetchone()
    return {
        "ActiveFarmers": farmers[0] if farmers else 0,
        "TotalAcreage": float(farmers[1]) if farmers and farmers[1] else 0,
        "TotalContracts": contracts[0] if contracts else 0,
        "ActiveContracts": contracts[1] if contracts else 0,
        "TotalDeliveredKg": float(deliveries[0]) if deliveries else 0,
        "TotalPaid": float(deliveries[1]) if deliveries else 0,
    }


# ─── Contract dashboard ───────────────────────────────────────────────────────

@router.get("/contract-dashboard")
def contract_dashboard(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    rows = db.execute(text("""
        SELECT oc.ContractID, oc.CropName, oc.Season, oc.TargetQtyKg,
               of2.FullName AS FarmerName, of2.FarmerID,
               ISNULL(SUM(od.NetWeightKg), 0)  AS DeliveredKg,
               COUNT(od.DeliveryID)             AS DeliveryCount,
               oc.Status                        AS ContractStatus,
               CONVERT(varchar(10), oc.StartDate, 120)  AS StartDate,
               CONVERT(varchar(10), oc.EndDate,   120)  AS EndDate,
               ISNULL(SUM(CASE WHEN od.PaymentStatus='pending' THEN od.NetPayment ELSE 0 END), 0) AS PendingPaymentAmt,
               COUNT(CASE WHEN od.PaymentStatus='pending' THEN 1 END) AS PendingDeliveries
        FROM OutgrowerContract oc
        JOIN OutgrowerFarmer of2 ON of2.FarmerID = oc.FarmerID
        LEFT JOIN OutgrowerDelivery od ON od.ContractID = oc.ContractID
        WHERE oc.BusinessID = :bid
        GROUP BY oc.ContractID, oc.CropName, oc.Season, oc.TargetQtyKg,
                 of2.FullName, of2.FarmerID, oc.Status, oc.StartDate, oc.EndDate
        ORDER BY oc.ContractID DESC
    """), {"bid": business_id}).fetchall()

    contracts = []
    total_target = total_delivered = total_pending_amt = 0
    for r in rows:
        m = dict(r._mapping)
        target = float(m.get("TargetQtyKg") or 0)
        delivered = float(m.get("DeliveredKg") or 0)
        utilization = round(delivered / target * 100, 1) if target > 0 else 0
        pending_amt = float(m.get("PendingPaymentAmt") or 0)
        total_target += target
        total_delivered += delivered
        total_pending_amt += pending_amt
        contracts.append({
            "contract_id": m["ContractID"],
            "crop_name": m["CropName"],
            "season": m["Season"],
            "target_kg": target,
            "delivered_kg": delivered,
            "utilization_pct": utilization,
            "delivery_count": m.get("DeliveryCount", 0),
            "contract_status": m["ContractStatus"],
            "start_date": m.get("StartDate"),
            "end_date": m.get("EndDate"),
            "farmer_name": m["FarmerName"],
            "farmer_id": m["FarmerID"],
            "pending_payment_amt": pending_amt,
            "pending_deliveries": m.get("PendingDeliveries", 0) or 0,
        })

    return {
        "contracts": contracts,
        "totals": {
            "total_contracts": len(contracts),
            "total_target_kg": total_target,
            "total_delivered_kg": total_delivered,
            "overall_utilization_pct": round(total_delivered / total_target * 100, 1) if total_target > 0 else 0,
            "total_pending_payment": total_pending_amt,
        },
    }
