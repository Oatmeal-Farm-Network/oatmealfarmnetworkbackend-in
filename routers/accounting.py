# routers/accounting.py
# Full accounting API for the Oatmeal Farm Network.
# All routes require a valid JWT (get_current_user) AND an active BusinessAccess
# row for the requested BusinessID (any access level).
# Same tables / logic as oatmeal_main accounting.routes.js — scoped by BusinessID.

from fastapi import APIRouter, Depends, HTTPException, Query
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from auth import get_current_user
import models
import datetime
from routers.rbac import record_audit

router = APIRouter(prefix="/api/accounting", tags=["accounting"])


# ────────────────────────────────────────────────────────────────
# AUTH GUARD
# ────────────────────────────────────────────────────────────────

def require_accounting_access(
    business_id: int = Query(...),
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify the caller has access to the requested business (any access level).

    Accounting is open to anyone with an active BusinessAccess row for this
    business; only non-members are blocked.
    """
    access = db.query(models.BusinessAccess).filter(
        models.BusinessAccess.BusinessID == business_id,
        models.BusinessAccess.PeopleID == current_user.PeopleID,
        models.BusinessAccess.Active == 1,
    ).first()
    if not access:
        raise HTTPException(status_code=403, detail="You do not have access to this business.")
    return {"business_id": business_id, "people_id": current_user.PeopleID, "access_level": access.AccessLevelID}


# ────────────────────────────────────────────────────────────────
# HELPER
# ────────────────────────────────────────────────────────────────

def get_next_number(prefix: str, table: str, column: str, business_id: int, db: Session) -> str:
    row = db.execute(
        text(f"SELECT TOP 1 {column} FROM {table} WHERE BusinessID = :bid ORDER BY {column} DESC"),
        {"bid": business_id},
    ).fetchone()
    if not row or not row[0]:
        return f"{prefix}-00001"
    last = str(row[0])
    num = int(last.split("-")[-1]) + 1
    return f"{prefix}-{str(num).zfill(5)}"


# ────────────────────────────────────────────────────────────────
# BUSINESS INFO & SETUP
# ────────────────────────────────────────────────────────────────

@router.get("/business-info")
def get_business_info(
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    row = db.execute(
        text("""
            SELECT b.BusinessID, b.BusinessName, b.BusinessEmail,
                   b.SubscriptionLevel,
                   bt.BusinessType, bt.BusinessTypeIcon
            FROM Business b
            JOIN businesstypelookup bt ON b.BusinessTypeID = bt.BusinessTypeID
            WHERE b.BusinessID = :bid
        """),
        {"bid": access["business_id"]},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Business not found.")
    return dict(row._mapping)


@router.post("/setup")
def setup_accounting(
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    existing = db.execute(
        text("SELECT COUNT(*) AS cnt FROM Accounts WHERE BusinessID = :bid"),
        {"bid": bid},
    ).fetchone()
    if existing and existing.cnt > 0:
        return {"message": "Chart of accounts already exists.", "alreadySetup": True}

    db.execute(text("EXEC CreateDefaultChartOfAccounts @BusinessID = :bid"), {"bid": bid})

    year = datetime.date.today().year
    db.execute(
        text("INSERT INTO FiscalYears (BusinessID, YearName, StartDate, EndDate) VALUES (:bid, :name, :start, :end)"),
        {"bid": bid, "name": f"FY{year}", "start": f"{year}-01-01", "end": f"{year}-12-31"},
    )
    fy_row = db.execute(
        text("SELECT TOP 1 FiscalYearID FROM FiscalYears WHERE BusinessID = :bid ORDER BY FiscalYearID DESC"),
        {"bid": bid},
    ).fetchone()
    fy_id = fy_row.FiscalYearID

    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    for m in range(12):
        start = datetime.date(year, m + 1, 1)
        if m == 11:
            end = datetime.date(year, 12, 31)
        else:
            end = datetime.date(year, m + 2, 1) - datetime.timedelta(days=1)
        db.execute(
            text("""INSERT INTO FiscalPeriods (FiscalYearID, BusinessID, PeriodNumber, PeriodName, StartDate, EndDate)
                    VALUES (:fy, :bid, :num, :name, :start, :end)"""),
            {"fy": fy_id, "bid": bid, "num": m + 1, "name": f"{months[m]} {year}", "start": start, "end": end},
        )

    db.commit()
    return {"message": "Accounting setup complete.", "alreadySetup": False}


# ────────────────────────────────────────────────────────────────
# CHART OF ACCOUNTS
# ────────────────────────────────────────────────────────────────

@router.get("/accounts")
def list_accounts(
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT a.*, t.Name AS AccountTypeName, t.NormalBalance, t.FinancialStatement
            FROM Accounts a
            JOIN AccountTypes t ON a.AccountTypeID = t.AccountTypeID
            WHERE a.BusinessID = :bid ORDER BY a.AccountNumber
        """),
        {"bid": access["business_id"]},
    ).fetchall()
    return {"accounts": [dict(r._mapping) for r in rows]}


@router.post("/accounts")
def create_account(
    payload: dict,
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    row = db.execute(
        text("""
            INSERT INTO Accounts (BusinessID, AccountTypeID, AccountNumber, AccountName, Description, ParentAccountID)
            OUTPUT INSERTED.*
            VALUES (:bid, :typeId, :num, :name, :desc, :parent)
        """),
        {
            "bid": bid,
            "typeId": payload.get("AccountTypeID"),
            "num": payload.get("AccountNumber"),
            "name": payload.get("AccountName"),
            "desc": payload.get("Description"),
            "parent": payload.get("ParentAccountID"),
        },
    ).fetchone()
    db.commit()
    return dict(row._mapping)


@router.put("/accounts/{account_id}")
def update_account(
    account_id: int,
    payload: dict,
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    db.execute(
        text("""
            UPDATE Accounts SET AccountName=:name, Description=:desc, IsActive=:active, UpdatedAt=GETDATE()
            WHERE AccountID=:id AND BusinessID=:bid AND IsSystem=0
        """),
        {
            "id": account_id,
            "bid": access["business_id"],
            "name": payload.get("AccountName"),
            "desc": payload.get("Description"),
            "active": 1 if payload.get("IsActive", True) else 0,
        },
    )
    db.commit()
    return {"ok": True}


@router.get("/account-types")
def list_account_types(db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT * FROM AccountTypes ORDER BY AccountTypeID")).fetchall()
    return {"accountTypes": [dict(r._mapping) for r in rows]}


# ────────────────────────────────────────────────────────────────
# JOURNAL ENTRIES
# ────────────────────────────────────────────────────────────────

@router.get("/journal-entries")
def list_journal_entries(
    start_date: str = Query(None),
    end_date: str = Query(None),
    page: int = Query(1),
    limit: int = Query(50),
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    offset = (page - 1) * limit
    sql = "SELECT * FROM JournalEntries WHERE BusinessID = :bid"
    params: dict = {"bid": bid}
    if start_date:
        sql += " AND EntryDate >= :start"; params["start"] = start_date
    if end_date:
        sql += " AND EntryDate <= :end"; params["end"] = end_date
    sql += f" ORDER BY EntryDate DESC OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"
    rows = db.execute(text(sql), params).fetchall()
    return {"entries": [dict(r._mapping) for r in rows]}


@router.get("/journal-entries/{entry_id}")
def get_journal_entry(
    entry_id: int,
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    entry = db.execute(
        text("SELECT * FROM JournalEntries WHERE JournalEntryID=:id AND BusinessID=:bid"),
        {"id": entry_id, "bid": access["business_id"]},
    ).fetchone()
    if not entry:
        raise HTTPException(status_code=404, detail="Not found.")
    lines = db.execute(
        text("""
            SELECT l.*, a.AccountName, a.AccountNumber FROM JournalEntryLines l
            JOIN Accounts a ON l.AccountID = a.AccountID
            WHERE l.JournalEntryID = :id ORDER BY l.LineOrder
        """),
        {"id": entry_id},
    ).fetchall()
    result = dict(entry._mapping)
    result["lines"] = [dict(r._mapping) for r in lines]
    return result


@router.post("/journal-entries")
def create_journal_entry(
    payload: dict,
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    lines = payload.get("Lines", [])
    if len(lines) < 2:
        raise HTTPException(status_code=400, detail="At least 2 lines required.")
    total_debits  = sum(float(l.get("DebitAmount",  0) or 0) for l in lines)
    total_credits = sum(float(l.get("CreditAmount", 0) or 0) for l in lines)
    if abs(total_debits - total_credits) > 0.01:
        raise HTTPException(status_code=400, detail=f"Entry not balanced. Debits: {total_debits:.2f}, Credits: {total_credits:.2f}")

    entry_number = get_next_number("JE", "JournalEntries", "EntryNumber", bid, db)
    je_row = db.execute(
        text("""
            INSERT INTO JournalEntries (BusinessID, EntryNumber, EntryDate, Description, Reference, SourceType, SourceID, IsPosted, CreatedBy)
            OUTPUT INSERTED.JournalEntryID
            VALUES (:bid, :num, :date, :desc, :ref, :srcType, :srcId, 1, :by)
        """),
        {
            "bid": bid, "num": entry_number,
            "date": payload.get("EntryDate"), "desc": payload.get("Description"),
            "ref": payload.get("Reference"), "srcType": payload.get("SourceType"),
            "srcId": payload.get("SourceID"), "by": access["people_id"],
        },
    ).fetchone()
    je_id = je_row.JournalEntryID

    for i, l in enumerate(lines):
        db.execute(
            text("""
                INSERT INTO JournalEntryLines (JournalEntryID, BusinessID, AccountID, DebitAmount, CreditAmount, Description, LineOrder)
                VALUES (:je, :bid, :acct, :debit, :credit, :desc, :order)
            """),
            {
                "je": je_id, "bid": bid, "acct": l.get("AccountID"),
                "debit": float(l.get("DebitAmount", 0) or 0),
                "credit": float(l.get("CreditAmount", 0) or 0),
                "desc": l.get("Description"), "order": i,
            },
        )
    db.commit()
    return {"JournalEntryID": je_id, "EntryNumber": entry_number}


# ────────────────────────────────────────────────────────────────
# CUSTOMERS
# ────────────────────────────────────────────────────────────────

@router.get("/customers")
def list_customers(
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT c.*,
              ISNULL((SELECT SUM(BalanceDue) FROM Invoices WHERE CustomerID=c.CustomerID AND Status NOT IN ('Paid','Void')),0) AS OpenBalance
            FROM AccountingCustomers c
            WHERE c.BusinessID=:bid AND c.IsActive=1 ORDER BY c.DisplayName
        """),
        {"bid": access["business_id"]},
    ).fetchall()
    return {"customers": [dict(r._mapping) for r in rows]}


@router.post("/customers")
def create_customer(
    payload: dict,
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    row = db.execute(
        text("""
            INSERT INTO AccountingCustomers
              (BusinessID, DisplayName, CompanyName, FirstName, LastName, Email, Phone,
               BillingAddress1, BillingCity, BillingState, BillingZip, BillingCountry,
               PaymentTerms, Notes, StripeCustomerID)
            OUTPUT INSERTED.*
            VALUES (:bid,:dn,:co,:fn,:ln,:em,:ph,:ba1,:bc,:bs,:bz,:bco,:pt,:no,:sc)
        """),
        {
            "bid": bid, "dn": payload.get("DisplayName"),
            "co": payload.get("CompanyName"), "fn": payload.get("FirstName"),
            "ln": payload.get("LastName"), "em": payload.get("Email"),
            "ph": payload.get("Phone"), "ba1": payload.get("BillingAddress1"),
            "bc": payload.get("BillingCity"), "bs": payload.get("BillingState"),
            "bz": payload.get("BillingZip"), "bco": payload.get("BillingCountry", "US"),
            "pt": payload.get("PaymentTerms", "Net30"),
            "no": payload.get("Notes"), "sc": payload.get("StripeCustomerID"),
        },
    ).fetchone()
    db.commit()
    return dict(row._mapping)


@router.put("/customers/{customer_id}")
def update_customer(
    customer_id: int,
    payload: dict,
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    db.execute(
        text("""
            UPDATE AccountingCustomers
            SET DisplayName=:dn, CompanyName=:co, FirstName=:fn, LastName=:ln,
                Email=:em, Phone=:ph, BillingAddress1=:ba1, BillingCity=:bc,
                BillingState=:bs, BillingZip=:bz, PaymentTerms=:pt, Notes=:no, UpdatedAt=GETDATE()
            WHERE CustomerID=:id AND BusinessID=:bid
        """),
        {
            "id": customer_id, "bid": access["business_id"],
            "dn": payload.get("DisplayName"), "co": payload.get("CompanyName"),
            "fn": payload.get("FirstName"), "ln": payload.get("LastName"),
            "em": payload.get("Email"), "ph": payload.get("Phone"),
            "ba1": payload.get("BillingAddress1"), "bc": payload.get("BillingCity"),
            "bs": payload.get("BillingState"), "bz": payload.get("BillingZip"),
            "pt": payload.get("PaymentTerms", "Net30"), "no": payload.get("Notes"),
        },
    )
    db.commit()
    return {"ok": True}


# ────────────────────────────────────────────────────────────────
# VENDORS
# ────────────────────────────────────────────────────────────────

@router.get("/vendors")
def list_vendors(
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT v.*,
              ISNULL((SELECT SUM(BalanceDue) FROM Bills WHERE VendorID=v.VendorID AND Status NOT IN ('Paid','Void')),0) AS OpenBalance
            FROM AccountingVendors v
            WHERE v.BusinessID=:bid AND v.IsActive=1 ORDER BY v.DisplayName
        """),
        {"bid": access["business_id"]},
    ).fetchall()
    return {"vendors": [dict(r._mapping) for r in rows]}


@router.post("/vendors")
def create_vendor(
    payload: dict,
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    row = db.execute(
        text("""
            INSERT INTO AccountingVendors
              (BusinessID, DisplayName, CompanyName, FirstName, LastName, Email, Phone,
               Address1, City, State, Zip, Country, PaymentTerms, Notes, Is1099)
            OUTPUT INSERTED.*
            VALUES (:bid,:dn,:co,:fn,:ln,:em,:ph,:a1,:ci,:st,:zp,:co2,:pt,:no,:t)
        """),
        {
            "bid": bid, "dn": payload.get("DisplayName"),
            "co": payload.get("CompanyName"), "fn": payload.get("FirstName"),
            "ln": payload.get("LastName"), "em": payload.get("Email"),
            "ph": payload.get("Phone"), "a1": payload.get("Address1"),
            "ci": payload.get("City"), "st": payload.get("State"),
            "zp": payload.get("Zip"), "co2": payload.get("Country", "US"),
            "pt": payload.get("PaymentTerms", "Net30"),
            "no": payload.get("Notes"), "t": 1 if payload.get("Is1099") else 0,
        },
    ).fetchone()
    db.commit()
    return dict(row._mapping)


# ────────────────────────────────────────────────────────────────
# ITEMS (Products & Services)
# ────────────────────────────────────────────────────────────────

@router.get("/items")
def list_items(
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT i.*, sa.AccountName AS SaleAccountName, pa.AccountName AS PurchaseAccountName
            FROM Items i
            LEFT JOIN Accounts sa ON i.SaleAccountID = sa.AccountID
            LEFT JOIN Accounts pa ON i.PurchaseAccountID = pa.AccountID
            WHERE i.BusinessID=:bid AND i.IsActive=1 ORDER BY i.Name
        """),
        {"bid": access["business_id"]},
    ).fetchall()
    return {"items": [dict(r._mapping) for r in rows]}


@router.post("/items")
def create_item(
    payload: dict,
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    row = db.execute(
        text("""
            INSERT INTO Items (BusinessID, ItemType, SKU, Name, Description, SalePrice, PurchasePrice,
              SaleAccountID, PurchaseAccountID, Taxable)
            OUTPUT INSERTED.*
            VALUES (:bid,:type,:sku,:name,:desc,:sp,:pp,:sa,:pa,:tax)
        """),
        {
            "bid": bid, "type": payload.get("ItemType", "Service"),
            "sku": payload.get("SKU"), "name": payload.get("Name"),
            "desc": payload.get("Description"),
            "sp": float(payload.get("SalePrice") or 0),
            "pp": float(payload.get("PurchasePrice") or 0),
            "sa": payload.get("SaleAccountID"), "pa": payload.get("PurchaseAccountID"),
            "tax": 1 if payload.get("Taxable", True) else 0,
        },
    ).fetchone()
    db.commit()
    return dict(row._mapping)


# ────────────────────────────────────────────────────────────────
# INVOICES
# ────────────────────────────────────────────────────────────────

def _create_invoice_journal_entry(invoice_id: int, business_id: int, people_id: int, db: Session):
    """Mirror of createInvoiceJournalEntry from oatmeal_main."""
    inv = db.execute(
        text("""
            SELECT i.*, c.DisplayName AS CustomerName FROM Invoices i
            JOIN AccountingCustomers c ON i.CustomerID=c.CustomerID
            WHERE i.InvoiceID=:id
        """),
        {"id": invoice_id},
    ).fetchone()
    if not inv:
        return

    ar_acct = db.execute(
        text("SELECT TOP 1 AccountID FROM Accounts WHERE BusinessID=:bid AND AccountNumber='1100'"),
        {"bid": business_id},
    ).fetchone()
    rev_acct = db.execute(
        text("SELECT TOP 1 AccountID FROM Accounts WHERE BusinessID=:bid AND AccountNumber='4000'"),
        {"bid": business_id},
    ).fetchone()
    tax_acct = db.execute(
        text("SELECT TOP 1 AccountID FROM Accounts WHERE BusinessID=:bid AND AccountNumber='2100'"),
        {"bid": business_id},
    ).fetchone()

    if not ar_acct:
        return

    je_num = get_next_number("JE", "JournalEntries", "EntryNumber", business_id, db)
    je_row = db.execute(
        text("""
            INSERT INTO JournalEntries (BusinessID, EntryNumber, EntryDate, Description, Reference, SourceType, SourceID, IsPosted, CreatedBy)
            OUTPUT INSERTED.JournalEntryID
            VALUES (:bid,:num,:date,:desc,:ref,'Invoice',:srcId,1,:by)
        """),
        {
            "bid": business_id, "num": je_num,
            "date": inv.InvoiceDate,
            "desc": f"Invoice {inv.InvoiceNumber} - {inv.CustomerName}",
            "ref": inv.InvoiceNumber, "srcId": invoice_id, "by": people_id,
        },
    ).fetchone()
    je_id = je_row.JournalEntryID

    # Debit AR
    db.execute(
        text("""INSERT INTO JournalEntryLines (JournalEntryID, BusinessID, AccountID, DebitAmount, CreditAmount, Description, LineOrder)
                VALUES (:je,:bid,:acct,:amt,0,:desc,0)"""),
        {"je": je_id, "bid": business_id, "acct": ar_acct.AccountID,
         "amt": float(inv.TotalAmount or 0), "desc": f"AR - {inv.InvoiceNumber}"},
    )
    # Credit Revenue
    if rev_acct:
        db.execute(
            text("""INSERT INTO JournalEntryLines (JournalEntryID, BusinessID, AccountID, DebitAmount, CreditAmount, Description, LineOrder)
                    VALUES (:je,:bid,:acct,0,:amt,:desc,1)"""),
            {"je": je_id, "bid": business_id, "acct": rev_acct.AccountID,
             "amt": float(inv.SubTotal or 0), "desc": f"Revenue - {inv.InvoiceNumber}"},
        )
    # Credit Tax
    if inv.TaxAmount and float(inv.TaxAmount) > 0 and tax_acct:
        db.execute(
            text("""INSERT INTO JournalEntryLines (JournalEntryID, BusinessID, AccountID, DebitAmount, CreditAmount, Description, LineOrder)
                    VALUES (:je,:bid,:acct,0,:amt,:desc,2)"""),
            {"je": je_id, "bid": business_id, "acct": tax_acct.AccountID,
             "amt": float(inv.TaxAmount), "desc": f"Sales Tax - {inv.InvoiceNumber}"},
        )
    db.execute(
        text("UPDATE Invoices SET JournalEntryID=:je WHERE InvoiceID=:id"),
        {"je": je_id, "id": invoice_id},
    )


@router.get("/invoices")
def list_invoices(
    status: str = Query(None),
    customer_id: int = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    page: int = Query(1),
    limit: int = Query(50),
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    offset = (page - 1) * limit
    sql = """SELECT i.*, c.DisplayName AS CustomerName FROM Invoices i
             JOIN AccountingCustomers c ON i.CustomerID = c.CustomerID
             WHERE i.BusinessID=:bid"""
    params: dict = {"bid": bid}
    if status:       sql += " AND i.Status=:status"; params["status"] = status
    if customer_id:  sql += " AND i.CustomerID=:cid"; params["cid"] = customer_id
    if start_date:   sql += " AND i.InvoiceDate>=:start"; params["start"] = start_date
    if end_date:     sql += " AND i.InvoiceDate<=:end"; params["end"] = end_date
    sql += f" ORDER BY i.InvoiceDate DESC OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"
    rows = db.execute(text(sql), params).fetchall()
    return {"invoices": [dict(r._mapping) for r in rows]}


@router.get("/invoices/{invoice_id}")
def get_invoice(
    invoice_id: int,
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    inv = db.execute(
        text("""
            SELECT i.*, c.DisplayName AS CustomerName, c.Email AS CustomerEmail,
                   c.BillingAddress1, c.BillingCity, c.BillingState, c.BillingZip
            FROM Invoices i JOIN AccountingCustomers c ON i.CustomerID=c.CustomerID
            WHERE i.InvoiceID=:id AND i.BusinessID=:bid
        """),
        {"id": invoice_id, "bid": access["business_id"]},
    ).fetchone()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    lines = db.execute(
        text("""
            SELECT l.*, it.Name AS ItemName FROM InvoiceLines l
            LEFT JOIN Items it ON l.ItemID=it.ItemID
            WHERE l.InvoiceID=:id ORDER BY l.LineOrder
        """),
        {"id": invoice_id},
    ).fetchall()
    result = dict(inv._mapping)
    result["Lines"] = [dict(r._mapping) for r in lines]
    return result


@router.post("/invoices")
def create_invoice(
    payload: dict,
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    lines = payload.get("Lines", [])
    if not lines:
        raise HTTPException(status_code=400, detail="Invoice must have at least one line.")

    invoice_number = get_next_number("INV", "Invoices", "InvoiceNumber", bid, db)
    sub_total    = sum(float(l.get("Quantity", 0)) * float(l.get("UnitPrice", 0)) for l in lines)
    tax_amount   = sum(float(l.get("TaxAmount", 0) or 0) for l in lines)
    total_amount = sub_total + tax_amount

    inv_row = db.execute(
        text("""
            INSERT INTO Invoices (BusinessID, CustomerID, InvoiceNumber, InvoiceDate, DueDate, Status,
              SubTotal, TaxAmount, TotalAmount, BalanceDue, Notes, TermsAndConditions, PaymentTerms, CreatedBy)
            OUTPUT INSERTED.InvoiceID
            VALUES (:bid,:cid,:num,:date,:due,'Draft',:sub,:tax,:total,:total,:notes,:terms,:pt,:by)
        """),
        {
            "bid": bid, "cid": payload.get("CustomerID"),
            "num": invoice_number, "date": payload.get("InvoiceDate"),
            "due": payload.get("DueDate"), "sub": sub_total,
            "tax": tax_amount, "total": total_amount,
            "notes": payload.get("Notes"), "terms": payload.get("TermsAndConditions"),
            "pt": payload.get("PaymentTerms", "Net30"), "by": access["people_id"],
        },
    ).fetchone()
    invoice_id = inv_row.InvoiceID

    for i, l in enumerate(lines):
        line_total = float(l.get("Quantity", 0)) * float(l.get("UnitPrice", 0)) + float(l.get("TaxAmount", 0) or 0)
        db.execute(
            text("""
                INSERT INTO InvoiceLines (InvoiceID, BusinessID, ItemID, AccountID, Description, Quantity,
                  UnitPrice, TaxRateID, TaxAmount, LineTotal, LineOrder)
                VALUES (:inv,:bid,:item,:acct,:desc,:qty,:price,:taxRate,:tax,:total,:order)
            """),
            {
                "inv": invoice_id, "bid": bid,
                "item": l.get("ItemID"), "acct": l.get("AccountID"),
                "desc": l.get("Description"),
                "qty": float(l.get("Quantity", 0)),
                "price": float(l.get("UnitPrice", 0)),
                "taxRate": l.get("TaxRateID"),
                "tax": float(l.get("TaxAmount", 0) or 0),
                "total": line_total, "order": i,
            },
        )

    _create_invoice_journal_entry(invoice_id, bid, access["people_id"], db)
    record_audit(db, bid, access["people_id"], "CREATE", "Invoice", invoice_id,
                 {"number": invoice_number, "total": total_amount})
    db.commit()
    return {"InvoiceID": invoice_id, "InvoiceNumber": invoice_number, "TotalAmount": total_amount}


@router.put("/invoices/{invoice_id}/status")
def update_invoice_status(
    invoice_id: int,
    payload: dict,
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    valid = ["Draft", "Sent", "Partial", "Paid", "Void"]
    status = payload.get("Status")
    if status not in valid:
        raise HTTPException(status_code=400, detail="Invalid status.")
    db.execute(
        text("UPDATE Invoices SET Status=:status, UpdatedAt=GETDATE() WHERE InvoiceID=:id AND BusinessID=:bid"),
        {"status": status, "id": invoice_id, "bid": access["business_id"]},
    )
    db.commit()
    return {"ok": True}


# ────────────────────────────────────────────────────────────────
# PAYMENTS (Received)
# ────────────────────────────────────────────────────────────────

@router.post("/payments")
def create_payment(
    payload: dict,
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    payment_number = get_next_number("PMT", "Payments", "PaymentNumber", bid, db)
    amount     = float(payload.get("Amount", 0))
    stripe_fee = float(payload.get("StripeFee", 0) or 0)
    net_amount = amount - stripe_fee

    p_row = db.execute(
        text("""
            INSERT INTO Payments (BusinessID, CustomerID, PaymentNumber, PaymentDate, PaymentMethod,
              Amount, UnusedAmount, Reference, StripePaymentIntentID, StripeChargeID, StripeFee, NetAmount,
              DepositAccountID, CreatedBy)
            OUTPUT INSERTED.PaymentID
            VALUES (:bid,:cid,:num,:date,:method,:amt,0,:ref,:spi,:sci,:fee,:net,:deposit,:by)
        """),
        {
            "bid": bid, "cid": payload.get("CustomerID"),
            "num": payment_number, "date": payload.get("PaymentDate"),
            "method": payload.get("PaymentMethod"),
            "amt": amount, "ref": payload.get("Reference"),
            "spi": payload.get("StripePaymentIntentID"),
            "sci": payload.get("StripeChargeID"),
            "fee": stripe_fee, "net": net_amount,
            "deposit": payload.get("DepositAccountID"), "by": access["people_id"],
        },
    ).fetchone()
    payment_id = p_row.PaymentID

    applied_total = 0.0
    for app in (payload.get("Applications") or []):
        app_amount = float(app.get("AmountApplied", 0))
        db.execute(
            text("INSERT INTO PaymentApplications (PaymentID, InvoiceID, BusinessID, AmountApplied) VALUES (:pid,:inv,:bid,:amt)"),
            {"pid": payment_id, "inv": app.get("InvoiceID"), "bid": bid, "amt": app_amount},
        )
        db.execute(
            text("""
                UPDATE Invoices
                SET AmountPaid  = AmountPaid + :amt,
                    BalanceDue  = BalanceDue - :amt,
                    Status      = CASE WHEN (BalanceDue - :amt) <= 0 THEN 'Paid'
                                       WHEN (AmountPaid + :amt) > 0  THEN 'Partial'
                                       ELSE Status END,
                    PaidAt      = CASE WHEN (BalanceDue - :amt) <= 0 THEN GETDATE() ELSE PaidAt END,
                    UpdatedAt   = GETDATE()
                WHERE InvoiceID=:inv AND BusinessID=:bid
            """),
            {"amt": app_amount, "inv": app.get("InvoiceID"), "bid": bid},
        )
        applied_total += app_amount

    unused = amount - applied_total
    if unused != 0:
        db.execute(
            text("UPDATE Payments SET UnusedAmount=:unused WHERE PaymentID=:id"),
            {"unused": unused, "id": payment_id},
        )
    db.commit()
    return {"PaymentID": payment_id, "PaymentNumber": payment_number}


# ────────────────────────────────────────────────────────────────
# BILLS (Payable)
# ────────────────────────────────────────────────────────────────

@router.get("/bills")
def list_bills(
    status: str = Query(None),
    vendor_id: int = Query(None),
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    sql = """SELECT b.*, v.DisplayName AS VendorName FROM Bills b
             JOIN AccountingVendors v ON b.VendorID=v.VendorID WHERE b.BusinessID=:bid"""
    params: dict = {"bid": bid}
    if status:    sql += " AND b.Status=:status"; params["status"] = status
    if vendor_id: sql += " AND b.VendorID=:vid"; params["vid"] = vendor_id
    sql += " ORDER BY b.BillDate DESC"
    rows = db.execute(text(sql), params).fetchall()
    return {"bills": [dict(r._mapping) for r in rows]}


@router.post("/bills")
def create_bill(
    payload: dict,
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    lines = payload.get("Lines", [])
    sub_total    = sum(float(l.get("Quantity", 0)) * float(l.get("UnitPrice", 0)) for l in lines)
    tax_amount   = sum(float(l.get("TaxAmount", 0) or 0) for l in lines)
    total_amount = sub_total + tax_amount

    b_row = db.execute(
        text("""
            INSERT INTO Bills (BusinessID, VendorID, BillNumber, BillDate, DueDate, Status,
              SubTotal, TaxAmount, TotalAmount, BalanceDue, Notes, CreatedBy)
            OUTPUT INSERTED.BillID
            VALUES (:bid,:vid,:num,:date,:due,'Open',:sub,:tax,:total,:total,:notes,:by)
        """),
        {
            "bid": bid, "vid": payload.get("VendorID"),
            "num": payload.get("BillNumber"),
            "date": payload.get("BillDate"), "due": payload.get("DueDate"),
            "sub": sub_total, "tax": tax_amount, "total": total_amount,
            "notes": payload.get("Notes"), "by": access["people_id"],
        },
    ).fetchone()
    bill_id = b_row.BillID

    for i, l in enumerate(lines):
        line_total = float(l.get("Quantity", 0)) * float(l.get("UnitPrice", 0)) + float(l.get("TaxAmount", 0) or 0)
        db.execute(
            text("""
                INSERT INTO BillLines (BillID, BusinessID, ItemID, AccountID, Description, Quantity,
                  UnitPrice, TaxRateID, TaxAmount, LineTotal, LineOrder)
                VALUES (:bill,:bid,:item,:acct,:desc,:qty,:price,:taxRate,:tax,:total,:order)
            """),
            {
                "bill": bill_id, "bid": bid,
                "item": l.get("ItemID"), "acct": l.get("AccountID"),
                "desc": l.get("Description"),
                "qty": float(l.get("Quantity", 0)),
                "price": float(l.get("UnitPrice", 0)),
                "taxRate": l.get("TaxRateID"),
                "tax": float(l.get("TaxAmount", 0) or 0),
                "total": line_total, "order": i,
            },
        )
    db.commit()
    return {"BillID": bill_id, "TotalAmount": total_amount}


# ────────────────────────────────────────────────────────────────
# EXPENSES
# ────────────────────────────────────────────────────────────────

@router.get("/expenses")
def list_expenses(
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT e.*, v.DisplayName AS VendorName FROM Expenses e
            LEFT JOIN AccountingVendors v ON e.VendorID=v.VendorID
            WHERE e.BusinessID=:bid ORDER BY e.ExpenseDate DESC
        """),
        {"bid": access["business_id"]},
    ).fetchall()
    return {"expenses": [dict(r._mapping) for r in rows]}


@router.post("/expenses")
def create_expense(
    payload: dict,
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    lines = payload.get("Lines", [])
    total_amount = sum(float(l.get("Amount", 0)) for l in lines)

    e_row = db.execute(
        text("""
            INSERT INTO Expenses (BusinessID, VendorID, PaymentAccountID, ExpenseDate, PaymentMethod,
              TotalAmount, Reference, Notes, CreatedBy)
            OUTPUT INSERTED.ExpenseID
            VALUES (:bid,:vid,:pacct,:date,:method,:total,:ref,:notes,:by)
        """),
        {
            "bid": bid, "vid": payload.get("VendorID"),
            "pacct": payload.get("PaymentAccountID"),
            "date": payload.get("ExpenseDate"),
            "method": payload.get("PaymentMethod", "Credit Card"),
            "total": total_amount, "ref": payload.get("Reference"),
            "notes": payload.get("Notes"), "by": access["people_id"],
        },
    ).fetchone()
    expense_id = e_row.ExpenseID

    for i, l in enumerate(lines):
        db.execute(
            text("""
                INSERT INTO ExpenseLines (ExpenseID, BusinessID, AccountID, Description, Amount, IsBillable, CustomerID, LineOrder)
                VALUES (:exp,:bid,:acct,:desc,:amt,:bill,:cid,:order)
            """),
            {
                "exp": expense_id, "bid": bid,
                "acct": l.get("AccountID"), "desc": l.get("Description"),
                "amt": float(l.get("Amount", 0)),
                "bill": 1 if l.get("IsBillable") else 0,
                "cid": l.get("CustomerID"), "order": i,
            },
        )
    db.commit()
    return {"ExpenseID": expense_id, "TotalAmount": total_amount}


# ────────────────────────────────────────────────────────────────
# REPORTS
# ────────────────────────────────────────────────────────────────

@router.get("/reports/profit-loss")
def report_profit_loss(
    start_date: str = Query(...),
    end_date: str = Query(...),
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT a.AccountNumber, a.AccountName, at.Name AS AccountType,
              SUM(CASE WHEN at.NormalBalance='Credit' THEN jl.CreditAmount - jl.DebitAmount
                       ELSE jl.DebitAmount - jl.CreditAmount END) AS Balance
            FROM JournalEntryLines jl
            JOIN JournalEntries je ON jl.JournalEntryID = je.JournalEntryID
            JOIN Accounts a        ON jl.AccountID = a.AccountID
            JOIN AccountTypes at   ON a.AccountTypeID = at.AccountTypeID
            WHERE je.BusinessID=:bid AND je.IsPosted=1
              AND je.EntryDate BETWEEN :start AND :end
              AND at.FinancialStatement = 'Income Statement'
            GROUP BY a.AccountNumber, a.AccountName, at.Name, at.AccountTypeID
            ORDER BY at.AccountTypeID, a.AccountNumber
        """),
        {"bid": access["business_id"], "start": start_date, "end": end_date},
    ).fetchall()
    data = [dict(r._mapping) for r in rows]
    revenue  = [r for r in data if r["AccountType"] in ("Revenue", "Other Income")]
    cogs     = [r for r in data if r["AccountType"] == "Cost of Goods"]
    expenses = [r for r in data if r["AccountType"] in ("Expense", "Other Expense")]
    total_revenue  = sum(float(r["Balance"] or 0) for r in revenue)
    total_cogs     = sum(float(r["Balance"] or 0) for r in cogs)
    gross_profit   = total_revenue - total_cogs
    total_expenses = sum(float(r["Balance"] or 0) for r in expenses)
    net_income     = gross_profit - total_expenses
    return {"revenue": revenue, "cogs": cogs, "expenses": expenses,
            "totalRevenue": total_revenue, "totalCOGS": total_cogs,
            "grossProfit": gross_profit, "totalExpenses": total_expenses,
            "netIncome": net_income, "startDate": start_date, "endDate": end_date}


@router.get("/reports/balance-sheet")
def report_balance_sheet(
    as_of_date: str = Query(...),
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT a.AccountNumber, a.AccountName, at.Name AS AccountType,
              SUM(CASE WHEN at.NormalBalance='Debit'  THEN jl.DebitAmount - jl.CreditAmount
                       ELSE jl.CreditAmount - jl.DebitAmount END) AS Balance
            FROM JournalEntryLines jl
            JOIN JournalEntries je ON jl.JournalEntryID = je.JournalEntryID
            JOIN Accounts a        ON jl.AccountID = a.AccountID
            JOIN AccountTypes at   ON a.AccountTypeID = at.AccountTypeID
            WHERE je.BusinessID=:bid AND je.IsPosted=1
              AND je.EntryDate <= :asOf
              AND at.FinancialStatement = 'Balance Sheet'
            GROUP BY a.AccountNumber, a.AccountName, at.Name, at.AccountTypeID
            ORDER BY at.AccountTypeID, a.AccountNumber
        """),
        {"bid": access["business_id"], "asOf": as_of_date},
    ).fetchall()
    data        = [dict(r._mapping) for r in rows]
    assets      = [r for r in data if r["AccountType"] == "Asset"]
    liabilities = [r for r in data if r["AccountType"] == "Liability"]
    equity      = [r for r in data if r["AccountType"] == "Equity"]
    return {"assets": assets, "liabilities": liabilities, "equity": equity,
            "totalAssets":      sum(float(r["Balance"] or 0) for r in assets),
            "totalLiabilities": sum(float(r["Balance"] or 0) for r in liabilities),
            "totalEquity":      sum(float(r["Balance"] or 0) for r in equity),
            "asOfDate": as_of_date}


@router.get("/reports/ar-aging")
def report_ar_aging(
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT c.DisplayName AS CustomerName, i.InvoiceNumber, i.InvoiceDate, i.DueDate,
              i.TotalAmount, i.AmountPaid, i.BalanceDue,
              DATEDIFF(day, i.DueDate, GETDATE()) AS DaysOverdue,
              CASE WHEN DATEDIFF(day, i.DueDate, GETDATE()) <= 0  THEN 'Current'
                   WHEN DATEDIFF(day, i.DueDate, GETDATE()) <= 30 THEN '1-30'
                   WHEN DATEDIFF(day, i.DueDate, GETDATE()) <= 60 THEN '31-60'
                   WHEN DATEDIFF(day, i.DueDate, GETDATE()) <= 90 THEN '61-90'
                   ELSE '90+' END AS AgingBucket
            FROM Invoices i JOIN AccountingCustomers c ON i.CustomerID=c.CustomerID
            WHERE i.BusinessID=:bid AND i.Status NOT IN ('Paid','Void') AND i.BalanceDue > 0
            ORDER BY DaysOverdue DESC
        """),
        {"bid": access["business_id"]},
    ).fetchall()
    return {"aging": [dict(r._mapping) for r in rows]}


@router.get("/reports/ap-aging")
def report_ap_aging(
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT v.DisplayName AS VendorName, b.BillNumber, b.BillDate, b.DueDate,
              b.TotalAmount, b.AmountPaid, b.BalanceDue,
              DATEDIFF(day, b.DueDate, GETDATE()) AS DaysOverdue,
              CASE WHEN DATEDIFF(day, b.DueDate, GETDATE()) <= 0  THEN 'Current'
                   WHEN DATEDIFF(day, b.DueDate, GETDATE()) <= 30 THEN '1-30'
                   WHEN DATEDIFF(day, b.DueDate, GETDATE()) <= 60 THEN '31-60'
                   WHEN DATEDIFF(day, b.DueDate, GETDATE()) <= 90 THEN '61-90'
                   ELSE '90+' END AS AgingBucket
            FROM Bills b JOIN AccountingVendors v ON b.VendorID=v.VendorID
            WHERE b.BusinessID=:bid AND b.Status NOT IN ('Paid','Void') AND b.BalanceDue > 0
            ORDER BY DaysOverdue DESC
        """),
        {"bid": access["business_id"]},
    ).fetchall()
    return {"aging": [dict(r._mapping) for r in rows]}


@router.get("/reports/cash-flow")
def report_cash_flow(
    start_date: str = Query(...),
    end_date: str = Query(...),
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    cash_in = db.execute(
        text("SELECT ISNULL(SUM(Amount),0) AS Total FROM Payments WHERE BusinessID=:bid AND PaymentDate BETWEEN :s AND :e"),
        {"bid": bid, "s": start_date, "e": end_date},
    ).fetchone().Total
    bill_paid = db.execute(
        text("SELECT ISNULL(SUM(Amount),0) AS Total FROM BillPayments WHERE BusinessID=:bid AND PaymentDate BETWEEN :s AND :e"),
        {"bid": bid, "s": start_date, "e": end_date},
    ).fetchone().Total
    exp_paid = db.execute(
        text("SELECT ISNULL(SUM(TotalAmount),0) AS Total FROM Expenses WHERE BusinessID=:bid AND ExpenseDate BETWEEN :s AND :e"),
        {"bid": bid, "s": start_date, "e": end_date},
    ).fetchone().Total
    cash_out = float(bill_paid or 0) + float(exp_paid or 0)
    return {
        "cashIn": float(cash_in or 0), "cashOut": cash_out,
        "netCash": float(cash_in or 0) - cash_out,
        "billPayments": float(bill_paid or 0), "expenses": float(exp_paid or 0),
        "startDate": start_date, "endDate": end_date,
    }


@router.get("/reports/general-ledger")
def report_general_ledger(
    account_id: int = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    sql = """SELECT je.EntryDate, je.EntryNumber, je.Description AS JEDescription, je.Reference,
               a.AccountNumber, a.AccountName, jl.DebitAmount, jl.CreditAmount, jl.Description AS LineDescription
             FROM JournalEntryLines jl
             JOIN JournalEntries je ON jl.JournalEntryID = je.JournalEntryID
             JOIN Accounts a        ON jl.AccountID = a.AccountID
             WHERE je.BusinessID=:bid AND je.IsPosted=1"""
    params: dict = {"bid": bid}
    if account_id: sql += " AND jl.AccountID=:acct"; params["acct"] = account_id
    if start_date: sql += " AND je.EntryDate>=:start"; params["start"] = start_date
    if end_date:   sql += " AND je.EntryDate<=:end"; params["end"] = end_date
    sql += " ORDER BY je.EntryDate, je.EntryNumber"
    rows = db.execute(text(sql), params).fetchall()
    return {"entries": [dict(r._mapping) for r in rows]}


@router.get("/reports/trial-balance")
def report_trial_balance(
    as_of_date: str = Query(...),
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT a.AccountNumber, a.AccountName, at.Name AS AccountType, at.NormalBalance,
              SUM(jl.DebitAmount) AS TotalDebits, SUM(jl.CreditAmount) AS TotalCredits,
              SUM(jl.DebitAmount) - SUM(jl.CreditAmount) AS NetBalance
            FROM JournalEntryLines jl
            JOIN JournalEntries je ON jl.JournalEntryID = je.JournalEntryID
            JOIN Accounts a        ON jl.AccountID = a.AccountID
            JOIN AccountTypes at   ON a.AccountTypeID = at.AccountTypeID
            WHERE je.BusinessID=:bid AND je.IsPosted=1 AND je.EntryDate <= :asOf
            GROUP BY a.AccountNumber, a.AccountName, at.Name, at.NormalBalance, at.AccountTypeID
            HAVING SUM(jl.DebitAmount) <> 0 OR SUM(jl.CreditAmount) <> 0
            ORDER BY at.AccountTypeID, a.AccountNumber
        """),
        {"bid": access["business_id"], "asOf": as_of_date},
    ).fetchall()
    return {"accounts": [dict(r._mapping) for r in rows]}


# ────────────────────────────────────────────────────────────────
# DASHBOARD
# ────────────────────────────────────────────────────────────────

@router.get("/dashboard")
def get_dashboard(
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    bid = access["business_id"]
    p = {"bid": bid}

    # AR: posted invoices + unposted aggregator B2B orders not yet synced
    ar_inv = db.execute(text("""
        SELECT
          ISNULL(SUM(CASE WHEN Status NOT IN ('Paid','Void') THEN BalanceDue ELSE 0 END),0) AS TotalAR,
          ISNULL(SUM(CASE WHEN Status='Overdue'              THEN BalanceDue ELSE 0 END),0) AS OverdueAR,
          COUNT(CASE WHEN Status NOT IN ('Paid','Void') THEN 1 END)                         AS OpenCount
        FROM Invoices WHERE BusinessID=:bid
    """), p).fetchone()
    ar_agg = db.execute(text("""
        SELECT
          ISNULL(SUM(CASE WHEN PaymentStatus != 'paid' THEN TotalValue ELSE 0 END),0) AS TotalAR,
          ISNULL(SUM(CASE WHEN PaymentStatus != 'paid' AND DeliveryDate < CONVERT(DATE,GETDATE()) THEN TotalValue ELSE 0 END),0) AS OverdueAR,
          COUNT(CASE WHEN PaymentStatus != 'paid' THEN 1 END) AS OpenCount
        FROM OFNAggregatorB2BOrder
        WHERE BusinessID=:bid AND AccountingInvoiceID IS NULL AND Status != 'cancelled'
    """), p).fetchone()

    # AP: posted bills + unposted aggregator purchases not yet synced
    ap_bill = db.execute(text("""
        SELECT
          ISNULL(SUM(CASE WHEN Status NOT IN ('Paid','Void') THEN BalanceDue ELSE 0 END),0) AS TotalAP,
          ISNULL(SUM(CASE WHEN Status='Overdue'              THEN BalanceDue ELSE 0 END),0) AS OverdueAP,
          COUNT(CASE WHEN Status NOT IN ('Paid','Void') THEN 1 END)                         AS OpenCount
        FROM Bills WHERE BusinessID=:bid
    """), p).fetchone()
    ap_agg = db.execute(text("""
        SELECT
          ISNULL(SUM(CASE WHEN PaymentStatus != 'paid' THEN TotalPaid ELSE 0 END),0) AS TotalAP,
          ISNULL(SUM(CASE WHEN PaymentStatus != 'paid' AND DATEADD(DAY,30,ReceivedDate) < CONVERT(DATE,GETDATE()) THEN TotalPaid ELSE 0 END),0) AS OverdueAP,
          COUNT(CASE WHEN PaymentStatus != 'paid' THEN 1 END) AS OpenCount
        FROM OFNAggregatorPurchase
        WHERE BusinessID=:bid AND AccountingBillID IS NULL
    """), p).fetchone()

    recent_payments = db.execute(text("""
        SELECT TOP 5 p.*, c.DisplayName AS CustomerName
        FROM Payments p JOIN AccountingCustomers c ON p.CustomerID=c.CustomerID
        WHERE p.BusinessID=:bid ORDER BY p.PaymentDate DESC
    """), p).fetchall()
    overdue_invoices = db.execute(text("""
        SELECT TOP 5 i.*, c.DisplayName AS CustomerName
        FROM Invoices i JOIN AccountingCustomers c ON i.CustomerID=c.CustomerID
        WHERE i.BusinessID=:bid AND i.Status NOT IN ('Paid','Void')
          AND i.DueDate < GETDATE() ORDER BY i.DueDate ASC
    """), p).fetchall()

    # Farmer settlement summary (read-only cross-module view)
    fs_exists = db.execute(text(
        "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='FarmerSettlement'"
    )).scalar()
    if fs_exists:
        fs_summary = db.execute(text("""
            SELECT
              ISNULL(SUM(CASE WHEN Status='Pending'  THEN NetPayment ELSE 0 END), 0) AS PendingTotal,
              COUNT(CASE  WHEN Status='Pending'  THEN 1 END)                          AS PendingCount,
              ISNULL(SUM(CASE WHEN Status='Paid'     THEN NetPayment ELSE 0 END), 0) AS PaidTotal,
              COUNT(CASE  WHEN Status='Paid'     THEN 1 END)                          AS PaidCount
            FROM FarmerSettlement WHERE BusinessID=:bid
        """), p).fetchone()
        recent_settlements = db.execute(text("""
            SELECT TOP 5 SettlementID, FarmerName, GrossSales, CommissionPct,
                         LogisticsCost, OtherDeductions, NetPayment, Status, PaidAt, CreatedAt
            FROM FarmerSettlement WHERE BusinessID=:bid
            ORDER BY CreatedAt DESC
        """), p).fetchall()
        farmer_payouts = {
            "pendingTotal":  float(fs_summary.PendingTotal or 0),
            "pendingCount":  int(fs_summary.PendingCount   or 0),
            "paidTotal":     float(fs_summary.PaidTotal    or 0),
            "paidCount":     int(fs_summary.PaidCount      or 0),
            "recent": [dict(r._mapping) for r in recent_settlements],
        }
    else:
        farmer_payouts = {"pendingTotal": 0, "pendingCount": 0, "paidTotal": 0, "paidCount": 0, "recent": []}

    return {
        "ar": {
            "TotalAR":   float(ar_inv.TotalAR  or 0) + float(ar_agg.TotalAR  or 0),
            "OverdueAR": float(ar_inv.OverdueAR or 0) + float(ar_agg.OverdueAR or 0),
            "OpenCount": int(ar_inv.OpenCount   or 0) + int(ar_agg.OpenCount   or 0),
        },
        "ap": {
            "TotalAP":   float(ap_bill.TotalAP  or 0) + float(ap_agg.TotalAP  or 0),
            "OverdueAP": float(ap_bill.OverdueAP or 0) + float(ap_agg.OverdueAP or 0),
            "OpenCount": int(ap_bill.OpenCount   or 0) + int(ap_agg.OpenCount   or 0),
        },
        "recentPayments":  [dict(r._mapping) for r in recent_payments],
        "overdueInvoices": [dict(r._mapping) for r in overdue_invoices],
        "farmerPayouts":   farmer_payouts,
    }


# ────────────────────────────────────────────────────────────────
# FARMER PAYOUTS — cross-module read-only view of FarmerSettlement
# ────────────────────────────────────────────────────────────────

@router.get("/farmer-payouts")
def get_farmer_payouts(
    status: str = Query(None),
    access=Depends(require_accounting_access),
    db: Session = Depends(get_db),
):
    """Full list of farmer settlements for the business, scoped by accounting auth."""
    bid = access["business_id"]
    fs_exists = db.execute(text(
        "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='FarmerSettlement'"
    )).scalar()
    if not fs_exists:
        return {"settlements": []}

    sql = """
        SELECT SettlementID, FarmerName, FarmerPhone, FarmerUPI,
               CommissionPct, LogisticsCost, OtherDeductions,
               GrossSales, NetPayment, Status, Notes, PaidAt, PaymentRef, CreatedAt
        FROM FarmerSettlement
        WHERE BusinessID = :bid
    """
    params: dict = {"bid": bid}
    if status:
        sql += " AND Status = :status"
        params["status"] = status
    sql += " ORDER BY CreatedAt DESC"
    rows = db.execute(text(sql), params).fetchall()
    cols = ["SettlementID", "FarmerName", "FarmerPhone", "FarmerUPI",
            "CommissionPct", "LogisticsCost", "OtherDeductions",
            "GrossSales", "NetPayment", "Status", "Notes", "PaidAt", "PaymentRef", "CreatedAt"]
    return {"settlements": [dict(zip(cols, r)) for r in rows]}


# ────────────────────────────────────────────────────────────────
# OATMEAL AI BUSINESS SEED
# Creates the Oatmeal AI business account if it doesn't exist.
# POST /api/accounting/seed-oatmeal-ai
# ────────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────────
# JOB COSTING  (per-field / per-crop / per-season cost centres)
# ────────────────────────────────────────────────────────────────

_job_tables_ready = False

def _ensure_job_tables(db: Session):
    global _job_tables_ready
    if _job_tables_ready:
        return
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CostJob')
        CREATE TABLE CostJob (
            JobID        INT IDENTITY PRIMARY KEY,
            BusinessID   INT           NOT NULL,
            JobName      NVARCHAR(300) NOT NULL,
            JobType      NVARCHAR(50)  NOT NULL DEFAULT 'field',
            FieldRef     NVARCHAR(200) NULL,
            CropName     NVARCHAR(200) NULL,
            Season       NVARCHAR(100) NULL,
            StartDate    DATE          NULL,
            EndDate      DATE          NULL,
            BudgetAmount DECIMAL(14,2) NULL,
            Status       NVARCHAR(30)  NOT NULL DEFAULT 'active',
            Notes        NVARCHAR(MAX) NULL,
            CreatedAt    DATETIME2     DEFAULT GETDATE(),
            UpdatedAt    DATETIME2     DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CostAllocation')
        CREATE TABLE CostAllocation (
            AllocationID   INT IDENTITY PRIMARY KEY,
            JobID          INT           NOT NULL,
            BusinessID     INT           NOT NULL,
            CostCategory   NVARCHAR(100) NOT NULL,
            Description    NVARCHAR(500) NULL,
            Amount         DECIMAL(14,2) NOT NULL,
            CostDate       DATE          NOT NULL,
            SourceType     NVARCHAR(50)  NULL,
            SourceID       INT           NULL,
            CreatedAt      DATETIME2     DEFAULT GETDATE()
        )
    """))
    db.commit()
    _job_tables_ready = True


@router.get("/jobs")
def list_jobs(access=Depends(require_accounting_access), db: Session = Depends(get_db)):
    _ensure_job_tables(db)
    bid = access["business_id"]
    rows = db.execute(text("""
        SELECT j.*,
               ISNULL(SUM(a.Amount), 0) AS ActualCost
        FROM CostJob j
        LEFT JOIN CostAllocation a ON a.JobID = j.JobID
        WHERE j.BusinessID = :bid
        GROUP BY j.JobID, j.BusinessID, j.JobName, j.JobType, j.FieldRef, j.CropName,
                 j.Season, j.StartDate, j.EndDate, j.BudgetAmount, j.Status, j.Notes,
                 j.CreatedAt, j.UpdatedAt
        ORDER BY j.StartDate DESC, j.JobID DESC
    """), {"bid": bid}).fetchall()
    result = []
    for r in rows:
        row = dict(r._mapping)
        for f in ["BudgetAmount", "ActualCost"]:
            if row.get(f) is not None:
                row[f] = float(row[f])
        result.append(row)
    return result


@router.post("/jobs")
def create_job(body: dict, access=Depends(require_accounting_access), db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_job_tables(db)
    bid = access["business_id"]
    r = db.execute(text("""
        INSERT INTO CostJob (BusinessID, JobName, JobType, FieldRef, CropName, Season,
                             StartDate, EndDate, BudgetAmount, Status, Notes)
        OUTPUT INSERTED.JobID
        VALUES (:bid, :name, :jtype, :fref, :crop, :season,
                :sd, :ed, :budget, :status, :notes)
    """), {
        "bid": bid, "name": body["JobName"], "jtype": body.get("JobType", "field"),
        "fref": body.get("FieldRef"), "crop": body.get("CropName"), "season": body.get("Season"),
        "sd": body.get("StartDate"), "ed": body.get("EndDate"),
        "budget": body.get("BudgetAmount"), "status": body.get("Status", "active"),
        "notes": body.get("Notes"),
    }).fetchone()
    record_audit(db, bid, access.get("people_id"), "CREATE", "CostJob", r[0],
                 {"name": body["JobName"], "type": body.get("JobType", "field")})
    db.commit()
    return {"JobID": r[0]}


@router.put("/jobs/{job_id}")
def update_job(job_id: int, body: dict, access=Depends(require_accounting_access), db: Session = Depends(get_db)):
    body = blank_to_none(body)
    bid = access["business_id"]
    db.execute(text("""
        UPDATE CostJob SET JobName=:name, JobType=:jtype, FieldRef=:fref, CropName=:crop,
            Season=:season, StartDate=:sd, EndDate=:ed, BudgetAmount=:budget,
            Status=:status, Notes=:notes, UpdatedAt=GETDATE()
        WHERE JobID=:jid AND BusinessID=:bid
    """), {
        "name": body.get("JobName"), "jtype": body.get("JobType", "field"),
        "fref": body.get("FieldRef"), "crop": body.get("CropName"), "season": body.get("Season"),
        "sd": body.get("StartDate"), "ed": body.get("EndDate"), "budget": body.get("BudgetAmount"),
        "status": body.get("Status", "active"), "notes": body.get("Notes"),
        "jid": job_id, "bid": bid,
    })
    db.commit()
    return {"ok": True}


@router.delete("/jobs/{job_id}")
def delete_job(job_id: int, access=Depends(require_accounting_access), db: Session = Depends(get_db)):
    bid = access["business_id"]
    db.execute(text("DELETE FROM CostAllocation WHERE JobID=:jid AND BusinessID=:bid"), {"jid": job_id, "bid": bid})
    db.execute(text("DELETE FROM CostJob WHERE JobID=:jid AND BusinessID=:bid"), {"jid": job_id, "bid": bid})
    db.commit()
    return {"ok": True}


@router.get("/jobs/{job_id}/allocations")
def list_allocations(job_id: int, access=Depends(require_accounting_access), db: Session = Depends(get_db)):
    _ensure_job_tables(db)
    bid = access["business_id"]
    rows = db.execute(text("""
        SELECT * FROM CostAllocation
        WHERE JobID=:jid AND BusinessID=:bid
        ORDER BY CostDate DESC, AllocationID DESC
    """), {"jid": job_id, "bid": bid}).fetchall()
    result = []
    for r in rows:
        row = dict(r._mapping)
        if row.get("Amount") is not None:
            row["Amount"] = float(row["Amount"])
        result.append(row)
    return result


@router.post("/jobs/{job_id}/allocations")
def add_allocation(job_id: int, body: dict, access=Depends(require_accounting_access), db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_job_tables(db)
    bid = access["business_id"]
    r = db.execute(text("""
        INSERT INTO CostAllocation (JobID, BusinessID, CostCategory, Description, Amount,
                                    CostDate, SourceType, SourceID)
        OUTPUT INSERTED.AllocationID
        VALUES (:jid, :bid, :cat, :desc, :amt, :dt, :stype, :sid)
    """), {
        "jid": job_id, "bid": bid, "cat": body["CostCategory"],
        "desc": body.get("Description"), "amt": float(body["Amount"]),
        "dt": body["CostDate"], "stype": body.get("SourceType"), "sid": body.get("SourceID"),
    }).fetchone()
    db.commit()
    return {"AllocationID": r[0]}


@router.delete("/jobs/{job_id}/allocations/{alloc_id}")
def delete_allocation(job_id: int, alloc_id: int, access=Depends(require_accounting_access), db: Session = Depends(get_db)):
    bid = access["business_id"]
    db.execute(text("DELETE FROM CostAllocation WHERE AllocationID=:aid AND JobID=:jid AND BusinessID=:bid"),
               {"aid": alloc_id, "jid": job_id, "bid": bid})
    db.commit()
    return {"ok": True}


@router.get("/jobs/{job_id}/report")
def job_report(job_id: int, access=Depends(require_accounting_access), db: Session = Depends(get_db)):
    """Per-job P&L: budget vs actual, breakdown by cost category."""
    _ensure_job_tables(db)
    bid = access["business_id"]
    job = db.execute(text("SELECT * FROM CostJob WHERE JobID=:jid AND BusinessID=:bid"),
                     {"jid": job_id, "bid": bid}).fetchone()
    if not job:
        raise HTTPException(404, "Job not found")
    by_cat = db.execute(text("""
        SELECT CostCategory, SUM(Amount) AS Total
        FROM CostAllocation
        WHERE JobID=:jid AND BusinessID=:bid
        GROUP BY CostCategory
        ORDER BY Total DESC
    """), {"jid": job_id, "bid": bid}).fetchall()
    total_actual = sum(float(r.Total) for r in by_cat)
    budget = float(job.BudgetAmount or 0)
    return {
        "job": dict(job._mapping),
        "total_actual": total_actual,
        "budget": budget,
        "variance": budget - total_actual,
        "by_category": [{"category": r.CostCategory, "total": float(r.Total)} for r in by_cat],
    }


# ────────────────────────────────────────────────────────────────
# AGRICULTURE CHART OF ACCOUNTS SEEDER
# ────────────────────────────────────────────────────────────────

AG_COA = [
    # (AccountNumber, Name, AccountType, Description)
    ("4100", "Crop Sales Revenue",           "Revenue",         "Sales of harvested crops"),
    ("4110", "Livestock Sales Revenue",      "Revenue",         "Proceeds from livestock sales"),
    ("4120", "Government Grants & Subsidies","Revenue",         "Agricultural subsidies and grant income"),
    ("4130", "Agro-Processing Revenue",      "Revenue",         "Value-added processing and packaging"),
    ("4140", "Contract Farming Income",      "Revenue",         "Outgrower and buy-back income"),
    ("5100", "Seed & Planting Material",     "Cost of Goods Sold","Cost of seeds, seedlings, cuttings"),
    ("5110", "Fertilizer & Soil Amendments", "Cost of Goods Sold","NPK, lime, compost, foliar feeds"),
    ("5120", "Crop Protection (Pesticides)", "Cost of Goods Sold","Herbicides, fungicides, insecticides"),
    ("5130", "Irrigation Costs",             "Cost of Goods Sold","Water abstraction, pumping, drip tape"),
    ("5140", "Harvest & Packaging Costs",    "Cost of Goods Sold","Picking, grading, bins, boxes"),
    ("5150", "Field Labor (Direct)",         "Cost of Goods Sold","Casual and permanent field labor"),
    ("5160", "Machinery Hire & Fuel",        "Cost of Goods Sold","Tractor hire, fuel for field operations"),
    ("5170", "Cold Chain & Transport",       "Cost of Goods Sold","Cold store, refrigerated transport"),
    ("6100", "Farm Management Salaries",     "Expense",         "Permanent staff and management payroll"),
    ("6110", "Land Rent & Lease",            "Expense",         "Lease payments for farmland"),
    ("6120", "Farm Insurance",               "Expense",         "Crop, equipment, and liability insurance"),
    ("6130", "Equipment Depreciation",       "Expense",         "Straight-line depreciation on machinery"),
    ("6140", "Repairs & Maintenance",        "Expense",         "Equipment and infrastructure upkeep"),
    ("6150", "Certification & Compliance",   "Expense",         "GlobalG.A.P., organic, audit fees"),
    ("6160", "Agronomist & Consulting Fees", "Expense",         "Technical advisory and soil testing"),
    ("6170", "Storage & Warehousing",        "Expense",         "On-farm and third-party storage"),
    ("6180", "Export & Customs Fees",        "Expense",         "Phytosanitary certs, customs clearance"),
    ("1300", "Crop Inventory (Growing)",     "Asset",           "Standing crops not yet harvested"),
    ("1310", "Harvested Crop Inventory",     "Asset",           "Harvested produce awaiting sale"),
    ("1320", "Input Inventory (Chemicals)",  "Asset",           "Agrochemicals and fertilizers on hand"),
    ("1500", "Land & Improvements",          "Asset",           "Land at cost plus clearing and drainage"),
    ("1510", "Farm Buildings & Structures",  "Asset",           "Packhouses, stores, irrigation infrastructure"),
    ("1520", "Farm Machinery & Equipment",   "Asset",           "Tractors, implements, irrigation equipment"),
    ("2100", "Input Supplier Payables",      "Liability",       "Amounts owed to seed/chemical suppliers"),
]


@router.post("/seed-ag-accounts")
def seed_ag_accounts(access=Depends(require_accounting_access), db: Session = Depends(get_db)):
    """Idempotently insert agriculture-specific accounts into the chart of accounts."""
    bid = access["business_id"]
    # Get account type ID map
    type_rows = db.execute(text("SELECT AccountTypeID, Name FROM AccountTypes WHERE BusinessID=:bid"),
                            {"bid": bid}).fetchall()
    if not type_rows:
        return {"inserted": 0, "message": "Run /setup first to create chart of accounts."}
    type_map = {r.Name: r.AccountTypeID for r in type_rows}

    existing_nums = {
        r[0] for r in db.execute(
            text("SELECT AccountNumber FROM Accounts WHERE BusinessID=:bid"), {"bid": bid}
        ).fetchall()
    }

    inserted = []
    for num, name, atype, desc in AG_COA:
        if num in existing_nums:
            continue
        type_id = type_map.get(atype)
        if not type_id:
            continue
        db.execute(text("""
            INSERT INTO Accounts (BusinessID, AccountNumber, Name, AccountTypeID, Description, IsActive)
            VALUES (:bid, :num, :name, :tid, :desc, 1)
        """), {"bid": bid, "num": num, "name": name, "tid": type_id, "desc": desc})
        inserted.append(num)

    db.commit()
    return {"inserted": len(inserted), "accounts": inserted,
            "skipped": len(AG_COA) - len(inserted)}


# ────────────────────────────────────────────────────────────────

@router.post("/seed-oatmeal-ai")
def seed_oatmeal_ai(db: Session = Depends(get_db)):
    """
    Idempotent: creates the 'Oatmeal AI' Business row if none with that name exists.
    Returns the BusinessID.
    """
    existing = db.execute(
        text("SELECT BusinessID FROM Business WHERE BusinessName = 'Oatmeal AI'")
    ).fetchone()
    if existing:
        return {"message": "Oatmeal AI business already exists.", "BusinessID": existing.BusinessID}

    # Insert with a placeholder address — BusinessTypeID 35 = Technology / AI (adjust if needed)
    # Use BusinessTypeID 1 (Agricultural Association) as fallback if 35 doesn't exist
    type_row = db.execute(
        text("SELECT TOP 1 BusinessTypeID FROM businesstypelookup ORDER BY BusinessTypeID")
    ).fetchone()
    default_type = type_row.BusinessTypeID if type_row else 1

    new_biz = db.execute(
        text("""
            INSERT INTO Business (BusinessTypeID, BusinessName, BusinessEmail, SubscriptionLevel, AccessLevel)
            OUTPUT INSERTED.BusinessID
            VALUES (:typeId, 'Oatmeal AI', 'info@oatmeal-ai.com', 1, 1)
        """),
        {"typeId": default_type},
    ).fetchone()
    db.commit()
    return {"message": "Oatmeal AI business created.", "BusinessID": new_biz.BusinessID}


# ─── Multi-Currency Exchange Rates ───────────────────────────────────────────

_fx_ready = False

SEED_RATES = [
    ("USD", "US Dollar",          1.0000),
    ("EUR", "Euro",               0.9200),
    ("GBP", "British Pound",      0.7900),
    ("CAD", "Canadian Dollar",    1.3600),
    ("AUD", "Australian Dollar",  1.5300),
    ("MXN", "Mexican Peso",      17.1500),
    ("JPY", "Japanese Yen",     149.5000),
    ("CNY", "Chinese Yuan",       7.2400),
    ("BRL", "Brazilian Real",     4.9700),
    ("ZAR", "South African Rand",18.7000),
    ("INR", "Indian Rupee",      83.1000),
    ("KES", "Kenyan Shilling",   130.000),
    ("GHS", "Ghanaian Cedi",     13.4000),
    ("NGN", "Nigerian Naira",   1580.00),
    ("TZS", "Tanzanian Shilling",2530.0),
    ("UGX", "Ugandan Shilling",  3740.0),
    ("ETB", "Ethiopian Birr",    113.000),
    ("NZD", "New Zealand Dollar", 1.6300),
]


def _ensure_fx(db: Session):
    global _fx_ready
    if _fx_ready:
        return
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ExchangeRate')
        CREATE TABLE ExchangeRate (
            CurrencyCode NVARCHAR(3)   NOT NULL PRIMARY KEY,
            CurrencyName NVARCHAR(100) NOT NULL,
            RateToUSD    DECIMAL(18,6) NOT NULL DEFAULT 1,
            UpdatedAt    DATETIME2     DEFAULT GETDATE()
        )
    """))
    db.commit()
    _fx_ready = True


@router.get("/currencies")
def list_currencies(db: Session = Depends(get_db)):
    """Return all currency codes with their USD exchange rates."""
    _ensure_fx(db)
    rows = db.execute(text("SELECT * FROM ExchangeRate ORDER BY CurrencyCode")).fetchall()
    if not rows:
        # Auto-seed on first call
        for code, name, rate in SEED_RATES:
            db.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM ExchangeRate WHERE CurrencyCode=:c)
                INSERT INTO ExchangeRate (CurrencyCode, CurrencyName, RateToUSD)
                VALUES (:c, :n, :r)
            """), {"c": code, "n": name, "r": rate})
        db.commit()
        rows = db.execute(text("SELECT * FROM ExchangeRate ORDER BY CurrencyCode")).fetchall()
    return [dict(r._mapping) for r in rows]


@router.put("/currencies/{code}")
def update_currency_rate(code: str, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    """Update the exchange rate for a currency code (rate relative to USD)."""
    _ensure_fx(db)
    code = code.upper()
    exists = db.execute(text("SELECT 1 FROM ExchangeRate WHERE CurrencyCode=:c"), {"c": code}).fetchone()
    if exists:
        db.execute(text("""
            UPDATE ExchangeRate SET RateToUSD=:r, CurrencyName=:n, UpdatedAt=GETDATE()
            WHERE CurrencyCode=:c
        """), {"c": code, "r": body["rate_to_usd"], "n": body.get("currency_name", code)})
    else:
        db.execute(text("""
            INSERT INTO ExchangeRate (CurrencyCode, CurrencyName, RateToUSD)
            VALUES (:c, :n, :r)
        """), {"c": code, "n": body.get("currency_name", code), "r": body["rate_to_usd"]})
    db.commit()
    return {"ok": True, "code": code}


@router.post("/currencies/convert")
def convert_currency(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    """Convert an amount between two currencies via USD as pivot.
    body: { amount, from_currency, to_currency }"""
    _ensure_fx(db)
    amount = float(body.get("amount", 0))
    from_c = body.get("from_currency", "USD").upper()
    to_c   = body.get("to_currency", "USD").upper()
    if from_c == to_c:
        return {"result": amount, "from": from_c, "to": to_c, "rate": 1.0}
    rates = {r.CurrencyCode: float(r.RateToUSD)
             for r in db.execute(text(
                 "SELECT CurrencyCode, RateToUSD FROM ExchangeRate WHERE CurrencyCode IN (:f, :t)"
             ), {"f": from_c, "t": to_c}).fetchall()}
    if from_c not in rates or to_c not in rates:
        raise HTTPException(404, "Unknown currency code")
    usd_amount = amount / rates[from_c]
    result = usd_amount * rates[to_c]
    return {
        "result": round(result, 4),
        "from": from_c, "to": to_c,
        "rate": round(rates[to_c] / rates[from_c], 6),
    }
