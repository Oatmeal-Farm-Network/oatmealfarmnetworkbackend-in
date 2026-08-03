"""
routers/procurement.py
Purchase & Procurement Automation — purchase orders, approval workflows,
PO-vs-receipt reconciliation.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional
from datetime import date

APPROVAL_THRESHOLD = 1000.0  # POs at or above this total auto-require approval

router = APIRouter(prefix="/api/procurement", tags=["procurement"])
_ready = False


def _ensure(db: Session):
    global _ready
    if _ready:
        return
    stmts = [
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='PurchaseOrder')
        CREATE TABLE PurchaseOrder (
            POID             INT IDENTITY PRIMARY KEY,
            BusinessID       INT NOT NULL,
            PONumber         NVARCHAR(100) NULL,
            SupplierName     NVARCHAR(300) NOT NULL,
            SupplierContact  NVARCHAR(300) NULL,
            SupplierEmail    NVARCHAR(300) NULL,
            Category         NVARCHAR(100) NULL,
            OrderDate        DATE NOT NULL,
            ExpectedDelivery DATE NULL,
            Status           NVARCHAR(50) NOT NULL DEFAULT 'draft',
            TotalAmount      DECIMAL(14,2) NULL,
            Currency         NVARCHAR(10) NOT NULL DEFAULT 'USD',
            Notes            NVARCHAR(MAX) NULL,
            ApprovedBy       NVARCHAR(200) NULL,
            ApprovedAt       DATETIME2 NULL,
            CreatedBy        NVARCHAR(200) NULL,
            CreatedAt        DATETIME2 DEFAULT GETDATE(),
            UpdatedAt        DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='POLineItem')
        CREATE TABLE POLineItem (
            LineID      INT IDENTITY PRIMARY KEY,
            POID        INT NOT NULL,
            ItemName    NVARCHAR(300) NOT NULL,
            Description NVARCHAR(MAX) NULL,
            Category    NVARCHAR(100) NULL,
            Quantity    DECIMAL(12,3) NOT NULL,
            Unit        NVARCHAR(50)  NULL,
            UnitPrice   DECIMAL(12,4) NOT NULL,
            LineTotal   DECIMAL(14,2) NOT NULL,
            ReceivedQty DECIMAL(12,3) NULL DEFAULT 0,
            CreatedAt   DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='POReceipt')
        CREATE TABLE POReceipt (
            ReceiptID       INT IDENTITY PRIMARY KEY,
            POID            INT NOT NULL,
            BusinessID      INT NOT NULL,
            ReceivedDate    DATE NOT NULL,
            ReceivedBy      NVARCHAR(200) NULL,
            DeliveryNote    NVARCHAR(100) NULL,
            Condition       NVARCHAR(100) NULL,
            Notes           NVARCHAR(MAX) NULL,
            CreatedAt       DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='POReceiptLine')
        CREATE TABLE POReceiptLine (
            ReceiptLineID INT IDENTITY PRIMARY KEY,
            ReceiptID     INT NOT NULL,
            LineID        INT NOT NULL,
            ReceivedQty   DECIMAL(12,3) NOT NULL,
            Condition     NVARCHAR(100) NULL,
            Notes         NVARCHAR(MAX) NULL
        )""",
        # auto-generate PO numbers
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='PurchaseOrder' AND COLUMN_NAME='PONumber')
            ALTER TABLE PurchaseOrder ADD PONumber NVARCHAR(100) NULL""",
    ]
    for s in stmts:
        try:
            db.execute(text(s))
        except Exception:
            pass
    db.commit()
    _ready = True


def _recompute_total(po_id: int, db: Session):
    total = db.execute(text("SELECT ISNULL(SUM(LineTotal),0) FROM POLineItem WHERE POID=:pid"),
                       {"pid": po_id}).scalar()
    db.execute(text("UPDATE PurchaseOrder SET TotalAmount=:t, UpdatedAt=GETDATE() WHERE POID=:pid"),
               {"t": total, "pid": po_id})


# ─── Purchase Orders ──────────────────────────────────────────────────────────

@router.get("/orders")
def list_orders(business_id: int = Query(...), status: Optional[str] = None, db: Session = Depends(get_db)):
    _ensure(db)
    q = "SELECT * FROM PurchaseOrder WHERE BusinessID=:bid"
    params = {"bid": business_id}
    if status:
        q += " AND Status=:st"; params["st"] = status
    q += " ORDER BY OrderDate DESC"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/orders/{po_id}")
def get_order(po_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    po = db.execute(text("SELECT * FROM PurchaseOrder WHERE POID=:pid AND BusinessID=:bid"),
                    {"pid": po_id, "bid": business_id}).fetchone()
    if not po:
        raise HTTPException(404, "PO not found")
    lines = db.execute(text("SELECT * FROM POLineItem WHERE POID=:pid ORDER BY LineID"), {"pid": po_id}).fetchall()
    receipts = db.execute(text("SELECT * FROM POReceipt WHERE POID=:pid ORDER BY ReceivedDate DESC"), {"pid": po_id}).fetchall()
    return {
        "order": dict(po._mapping),
        "lines": [dict(r._mapping) for r in lines],
        "receipts": [dict(r._mapping) for r in receipts],
    }


@router.post("/orders")
def create_order(body: dict, db: Session = Depends(get_db)):
    _ensure(db)
    # Auto-generate PO number
    count = db.execute(text("SELECT COUNT(*)+1 FROM PurchaseOrder WHERE BusinessID=:bid"),
                       {"bid": body["BusinessID"]}).scalar()
    po_num = f"PO-{body['BusinessID']}-{count:04d}"
    r = db.execute(text("""
        INSERT INTO PurchaseOrder (BusinessID,PONumber,SupplierName,SupplierContact,SupplierEmail,
            Category,OrderDate,ExpectedDelivery,Status,Currency,Notes,CreatedBy)
        OUTPUT INSERTED.POID
        VALUES (:bid,:pnum,:sup,:supc,:supe,:cat,:od,:ed,:st,:cur,:notes,:by)
    """), {
        "bid": body["BusinessID"], "pnum": po_num,
        "sup": body["SupplierName"], "supc": body.get("SupplierContact"),
        "supe": body.get("SupplierEmail"), "cat": body.get("Category"),
        "od": body["OrderDate"], "ed": body.get("ExpectedDelivery"),
        "st": body.get("Status", "draft"), "cur": body.get("Currency", "USD"),
        "notes": body.get("Notes"), "by": body.get("CreatedBy"),
    }).fetchone()
    po_id = r[0]

    # Insert line items
    for line in body.get("lines", []):
        qty = float(line.get("Quantity", 0))
        price = float(line.get("UnitPrice", 0))
        db.execute(text("""
            INSERT INTO POLineItem (POID,ItemName,Description,Category,Quantity,Unit,UnitPrice,LineTotal)
            VALUES (:pid,:name,:desc,:cat,:qty,:unit,:price,:lt)
        """), {
            "pid": po_id, "name": line["ItemName"], "desc": line.get("Description"),
            "cat": line.get("Category"), "qty": qty, "unit": line.get("Unit"),
            "price": price, "lt": round(qty * price, 2),
        })

    _recompute_total(po_id, db)

    # Auto-escalate to pending_approval if total >= threshold
    total_row = db.execute(text("SELECT TotalAmount FROM PurchaseOrder WHERE POID=:pid"), {"pid": po_id}).fetchone()
    total_val = float(total_row.TotalAmount or 0) if total_row else 0
    if total_val >= APPROVAL_THRESHOLD and body.get("Status", "draft") not in ("approved", "issued"):
        db.execute(text("""
            UPDATE PurchaseOrder SET Status='pending_approval', UpdatedAt=GETDATE() WHERE POID=:pid
        """), {"pid": po_id})
        try:
            from routers.notifications import notify_business
            notify_business(
                db, body["BusinessID"], type="po_approval_required",
                title=f"PO approval required: {po_num}",
                body=f"{body['SupplierName']} — ${total_val:,.2f}. Pending manager approval before issuing.",
                link_path=f"/procurement?BusinessID={body['BusinessID']}&filter=pending_approval",
                entity_type="PurchaseOrder", entity_id=po_id,
            )
        except Exception:
            pass

    db.commit()
    return {"POID": po_id, "PONumber": po_num, "RequiresApproval": total_val >= APPROVAL_THRESHOLD}


@router.put("/orders/{po_id}")
def update_order(po_id: int, body: dict, db: Session = Depends(get_db)):
    _ensure(db)
    db.execute(text("""
        UPDATE PurchaseOrder SET SupplierName=:sup, SupplierContact=:supc, SupplierEmail=:supe,
            Category=:cat, OrderDate=:od, ExpectedDelivery=:ed, Currency=:cur, Notes=:notes, UpdatedAt=GETDATE()
        WHERE POID=:pid AND BusinessID=:bid
    """), {
        "sup": body["SupplierName"], "supc": body.get("SupplierContact"),
        "supe": body.get("SupplierEmail"), "cat": body.get("Category"),
        "od": body["OrderDate"], "ed": body.get("ExpectedDelivery"),
        "cur": body.get("Currency", "USD"), "notes": body.get("Notes"),
        "pid": po_id, "bid": body["BusinessID"],
    })
    db.commit()
    return {"ok": True}


# ─── Approval workflow ────────────────────────────────────────────────────────

@router.post("/orders/{po_id}/approve")
def approve_order(po_id: int, body: dict, db: Session = Depends(get_db)):
    bid = body["BusinessID"]
    db.execute(text("""
        UPDATE PurchaseOrder SET Status='approved', ApprovedBy=:by, ApprovedAt=GETDATE(), UpdatedAt=GETDATE()
        WHERE POID=:pid AND BusinessID=:bid
    """), {"by": body.get("ApprovedBy"), "pid": po_id, "bid": bid})
    db.commit()

    # Post accounting Bill for the PO amount
    _sync_po_to_accounting_bill(db, po_id, bid)
    db.commit()

    try:
        from routers.notifications import notify_business
        po = db.execute(text("SELECT PONumber, SupplierName, TotalAmount FROM PurchaseOrder WHERE POID=:pid"),
                        {"pid": po_id}).fetchone()
        if po:
            notify_business(
                db, bid, type="po_approved",
                title=f"PO approved: {po.PONumber}",
                body=f"{po.SupplierName} — ${float(po.TotalAmount or 0):,.2f} approved by {body.get('ApprovedBy','manager')}. Bill posted to accounting.",
                link_path=f"/procurement?BusinessID={bid}",
                entity_type="PurchaseOrder", entity_id=po_id,
            )
    except Exception:
        pass

    return {"ok": True}


def _sync_po_to_accounting_bill(db: Session, po_id: int, business_id: int):
    """Create an Open Bill in Accounting for an approved PO (find-or-create vendor)."""
    try:
        acct_count = db.execute(text("SELECT COUNT(*) FROM Accounts WHERE BusinessID=:bid"), {"bid": business_id}).scalar()
        if not acct_count:
            return
        # Skip if a bill already links to this PO
        existing = db.execute(text(
            "SELECT COUNT(*) FROM Bills WHERE BusinessID=:bid AND Notes LIKE :tag"
        ), {"bid": business_id, "tag": f"%[PO:{po_id}]%"}).scalar()
        if existing:
            return

        po = db.execute(text("SELECT * FROM PurchaseOrder WHERE POID=:pid AND BusinessID=:bid"),
                        {"pid": po_id, "bid": business_id}).fetchone()
        lines = db.execute(text("SELECT * FROM POLineItem WHERE POID=:pid ORDER BY LineID"), {"pid": po_id}).fetchall()
        if not po:
            return

        # Find or create vendor
        vendor = db.execute(text("""
            SELECT TOP 1 VendorID FROM AccountingVendors
            WHERE BusinessID=:bid AND DisplayName=:name AND IsActive=1
        """), {"bid": business_id, "name": po.SupplierName}).fetchone()
        if vendor:
            vendor_id = vendor.VendorID
        else:
            v = db.execute(text("""
                INSERT INTO AccountingVendors
                    (BusinessID, DisplayName, CompanyName, Email, PaymentTerms, Notes)
                OUTPUT INSERTED.VendorID
                VALUES (:bid, :name, :name, :email, 'Net30', 'Auto-created from PO approval')
            """), {"bid": business_id, "name": po.SupplierName, "email": po.SupplierEmail}).fetchone()
            vendor_id = v.VendorID

        # Get expense account (5xxx)
        exp_acct = db.execute(text("""
            SELECT TOP 1 AccountID FROM Accounts
            WHERE BusinessID=:bid AND AccountNumber LIKE '5%' AND IsActive=1
            ORDER BY AccountNumber
        """), {"bid": business_id}).fetchone()
        acct_id = exp_acct.AccountID if exp_acct else None

        admin = db.execute(text("""
            SELECT TOP 1 PeopleID FROM BusinessAccess WHERE BusinessID=:bid AND Active=1 ORDER BY AccessLevelID DESC
        """), {"bid": business_id}).fetchone()
        created_by = admin.PeopleID if admin else None

        count = db.execute(text("SELECT COUNT(*)+1 FROM Bills WHERE BusinessID=:bid"), {"bid": business_id}).scalar()
        bill_num = f"BILL-PO-{business_id}-{count:04d}"
        total_amt = float(po.TotalAmount or 0)

        b = db.execute(text("""
            INSERT INTO Bills
                (BusinessID, VendorID, BillNumber, BillDate, DueDate, Status,
                 SubTotal, TaxAmount, TotalAmount, BalanceDue, Notes, CreatedBy)
            OUTPUT INSERTED.BillID
            VALUES (:bid, :vid, :num, CAST(GETDATE() AS DATE),
                    DATEADD(day,30,CAST(GETDATE() AS DATE)),
                    'Open', :sub, 0, :total, :total, :notes, :by)
        """), {
            "bid": business_id, "vid": vendor_id, "num": bill_num,
            "sub": total_amt, "total": total_amt,
            "notes": f"[PO:{po_id}] Auto-created on PO approval — {po.PONumber}",
            "by": created_by,
        }).fetchone()
        bill_id = b.BillID

        for i, line in enumerate(lines):
            db.execute(text("""
                INSERT INTO BillLines
                    (BillID, BusinessID, AccountID, Description, Quantity, UnitPrice, TaxAmount, LineTotal, LineOrder)
                VALUES (:bid2, :bid, :acct, :desc, :qty, :price, 0, :lt, :order)
            """), {
                "bid2": bill_id, "bid": business_id, "acct": acct_id,
                "desc": line.ItemName, "qty": float(line.Quantity),
                "price": float(line.UnitPrice), "lt": float(line.LineTotal), "order": i,
            })
    except Exception as _e:
        print(f"[po-approve-bill] {_e}")


@router.post("/orders/{po_id}/reject")
def reject_order(po_id: int, body: dict, db: Session = Depends(get_db)):
    bid = body["BusinessID"]
    db.execute(text("""
        UPDATE PurchaseOrder SET Status='rejected', Notes=ISNULL(Notes,'')+' [Rejected: '+ISNULL(:reason,'')+']', UpdatedAt=GETDATE()
        WHERE POID=:pid AND BusinessID=:bid
    """), {"reason": body.get("Reason"), "pid": po_id, "bid": bid})
    db.commit()
    try:
        from routers.notifications import notify_business
        po = db.execute(text("SELECT PONumber, SupplierName FROM PurchaseOrder WHERE POID=:pid"), {"pid": po_id}).fetchone()
        if po:
            notify_business(
                db, bid, type="po_rejected",
                title=f"PO rejected: {po.PONumber}",
                body=f"{po.SupplierName} PO was rejected. Reason: {body.get('Reason','N/A')}",
                link_path=f"/procurement?BusinessID={bid}",
                entity_type="PurchaseOrder", entity_id=po_id,
            )
    except Exception:
        pass
    return {"ok": True}


@router.post("/orders/{po_id}/issue")
def issue_order(po_id: int, body: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE PurchaseOrder SET Status='issued', UpdatedAt=GETDATE()
        WHERE POID=:pid AND BusinessID=:bid AND Status='approved'
    """), {"pid": po_id, "bid": body["BusinessID"]})
    db.commit()
    return {"ok": True}


# ─── Receipts & Reconciliation ────────────────────────────────────────────────

@router.post("/orders/{po_id}/receipts")
def create_receipt(po_id: int, body: dict, db: Session = Depends(get_db)):
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO POReceipt (POID,BusinessID,ReceivedDate,ReceivedBy,DeliveryNote,Condition,Notes)
        OUTPUT INSERTED.ReceiptID
        VALUES (:pid,:bid,:dt,:by,:dn,:cond,:notes)
    """), {
        "pid": po_id, "bid": body["BusinessID"], "dt": body["ReceivedDate"],
        "by": body.get("ReceivedBy"), "dn": body.get("DeliveryNote"),
        "cond": body.get("Condition"), "notes": body.get("Notes"),
    }).fetchone()
    receipt_id = r[0]

    # Update received quantities per line
    all_received = True
    for line in body.get("lines", []):
        line_id = line["LineID"]
        recv_qty = float(line.get("ReceivedQty", 0))
        db.execute(text("""
            INSERT INTO POReceiptLine (ReceiptID,LineID,ReceivedQty,Condition,Notes)
            VALUES (:rid,:lid,:qty,:cond,:notes)
        """), {"rid": receipt_id, "lid": line_id, "qty": recv_qty,
               "cond": line.get("Condition"), "notes": line.get("Notes")})
        db.execute(text("UPDATE POLineItem SET ReceivedQty=ISNULL(ReceivedQty,0)+:qty WHERE LineID=:lid"),
                   {"qty": recv_qty, "lid": line_id})

    # Check if fully received
    gap = db.execute(text("""
        SELECT SUM(Quantity - ISNULL(ReceivedQty,0)) FROM POLineItem WHERE POID=:pid
    """), {"pid": po_id}).scalar() or 0
    new_status = "received" if float(gap) <= 0 else "partial"
    db.execute(text("UPDATE PurchaseOrder SET Status=:st, UpdatedAt=GETDATE() WHERE POID=:pid"),
               {"st": new_status, "pid": po_id})
    db.commit()
    return {"ReceiptID": receipt_id, "Status": new_status}


# ─── Line items ───────────────────────────────────────────────────────────────

@router.post("/orders/{po_id}/lines")
def add_line(po_id: int, body: dict, db: Session = Depends(get_db)):
    _ensure(db)
    qty = float(body.get("Quantity", 0))
    price = float(body.get("UnitPrice", 0))
    db.execute(text("""
        INSERT INTO POLineItem (POID,ItemName,Description,Category,Quantity,Unit,UnitPrice,LineTotal)
        VALUES (:pid,:name,:desc,:cat,:qty,:unit,:price,:lt)
    """), {
        "pid": po_id, "name": body["ItemName"], "desc": body.get("Description"),
        "cat": body.get("Category"), "qty": qty, "unit": body.get("Unit"),
        "price": price, "lt": round(qty * price, 2),
    })
    _recompute_total(po_id, db)
    db.commit()
    return {"ok": True}


@router.delete("/orders/{po_id}/lines/{line_id}")
def delete_line(po_id: int, line_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM POLineItem WHERE LineID=:lid AND POID=:pid"),
               {"lid": line_id, "pid": po_id})
    _recompute_total(po_id, db)
    db.commit()
    return {"ok": True}


# ─── Summary ─────────────────────────────────────────────────────────────────

@router.get("/summary")
def procurement_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    row = db.execute(text("""
        SELECT
            COUNT(*) AS TotalOrders,
            SUM(CASE WHEN Status='draft' THEN 1 ELSE 0 END) AS Draft,
            SUM(CASE WHEN Status='pending_approval' THEN 1 ELSE 0 END) AS PendingApproval,
            SUM(CASE WHEN Status='approved' THEN 1 ELSE 0 END) AS Approved,
            SUM(CASE WHEN Status='issued' THEN 1 ELSE 0 END) AS Issued,
            SUM(CASE WHEN Status='partial' THEN 1 ELSE 0 END) AS PartialReceipt,
            SUM(CASE WHEN Status='received' THEN 1 ELSE 0 END) AS FullyReceived,
            ISNULL(SUM(TotalAmount),0) AS TotalSpend,
            ISNULL(SUM(CASE WHEN MONTH(OrderDate)=MONTH(GETDATE()) AND YEAR(OrderDate)=YEAR(GETDATE()) THEN TotalAmount ELSE 0 END),0) AS ThisMonthSpend
        FROM PurchaseOrder WHERE BusinessID=:bid
    """), {"bid": business_id}).fetchone()
    return dict(row._mapping) if row else {}
