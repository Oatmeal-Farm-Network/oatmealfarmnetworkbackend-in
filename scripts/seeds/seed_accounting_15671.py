"""
Seed accounting test data for BusinessID=15671.
Idempotent: deletes existing accounting data for this business before re-inserting.
Run from Backend/oatmealfarmnetworkbackend/:
    ..\venv\Scripts\python.exe seed_accounting_15671.py
"""
import sys, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import get_db, engine
from sqlalchemy import text

BID = 15671
TODAY = datetime.date.today()

def d(offset_days=0):
    return (TODAY + datetime.timedelta(days=offset_days)).strftime("%Y-%m-%d")

def q(db, sql, p=None):
    return db.execute(text(sql), p or {}).fetchall()

def s(db, sql, p=None):
    return db.execute(text(sql), p or {}).scalar()

def r1(db, sql, p=None):
    return db.execute(text(sql), p or {}).fetchone()

db = next(get_db())

# ── 1. Chart of accounts setup ────────────────────────────────────────────────
print("[1] Setting up chart of accounts...")
existing_accts = s(db, "SELECT COUNT(*) FROM Accounts WHERE BusinessID=:bid", {"bid": BID})
if not existing_accts:
    db.execute(text("EXEC CreateDefaultChartOfAccounts @BusinessID=:bid"), {"bid": BID})
    db.commit()
    print("  Chart of accounts created.")
else:
    print(f"  Already exists ({existing_accts} accounts).")

# Ensure fiscal year 2025 + 2026
for yr in [2025, 2026]:
    fy_exists = s(db, "SELECT COUNT(*) FROM FiscalYears WHERE BusinessID=:bid AND YearName=:y",
                  {"bid": BID, "y": f"FY{yr}"})
    if not fy_exists:
        db.execute(text("""
            INSERT INTO FiscalYears (BusinessID, YearName, StartDate, EndDate)
            VALUES (:bid, :name, :start, :end)
        """), {"bid": BID, "name": f"FY{yr}", "start": f"{yr}-01-01", "end": f"{yr}-12-31"})
        db.commit()
        fy_id = s(db, "SELECT TOP 1 FiscalYearID FROM FiscalYears WHERE BusinessID=:bid AND YearName=:y",
                  {"bid": BID, "y": f"FY{yr}"})
        months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        for m in range(12):
            start = datetime.date(yr, m+1, 1)
            end   = datetime.date(yr, 12, 31) if m == 11 else datetime.date(yr, m+2, 1) - datetime.timedelta(days=1)
            db.execute(text("""
                INSERT INTO FiscalPeriods (FiscalYearID, BusinessID, PeriodNumber, PeriodName, StartDate, EndDate)
                VALUES (:fy,:bid,:num,:name,:start,:end)
            """), {"fy": fy_id, "bid": BID, "num": m+1, "name": f"{months[m]} {yr}",
                  "start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")})
        db.commit()
        print(f"  FY{yr} created.")

# Look up key account IDs
def acct(num):
    row = r1(db, "SELECT AccountID FROM Accounts WHERE BusinessID=:bid AND AccountNumber=:n",
             {"bid": BID, "n": str(num)})
    return row[0] if row else None

AR    = acct("1100")   # Accounts Receivable
CASH  = acct("1000")   # Cash/Checking
AP    = acct("2000")   # Accounts Payable
TAX   = acct("2100")   # Sales Tax Payable
REV   = acct("4000")   # Sales Revenue
COGS  = acct("5000")   # Cost of Goods
EXP   = acct("6000")   # Operating Expenses — fallback
FUEL  = acct("6100") or EXP
UTIL  = acct("6200") or EXP
WAGES = acct("6300") or EXP
INS   = acct("6400") or EXP
MKTG  = acct("6500") or EXP
SUPP  = acct("6600") or EXP

print(f"  AR={AR}, CASH={CASH}, AP={AP}, REV={REV}, COGS={COGS}")

# ── 2. Clear previous seed data ───────────────────────────────────────────────
print("\n[2] Clearing previous accounting seed data...")
for tbl in ["PaymentApplications","Payments","ExpenseLines","Expenses",
            "BillLines","Bills","InvoiceLines","JournalEntryLines",
            "JournalEntries","Invoices","Items",
            "AccountingVendors","AccountingCustomers"]:
    db.execute(text(f"DELETE FROM {tbl} WHERE BusinessID=:bid"), {"bid": BID})
db.commit()
print("  Done.")

# ── 3. Customers ──────────────────────────────────────────────────────────────
print("\n[3] Adding customers...")

def add_customer(dn, co, fn, ln, email, phone, addr, city, state, zp, terms="Net30"):
    row = r1(db, """
        INSERT INTO AccountingCustomers
          (BusinessID,DisplayName,CompanyName,FirstName,LastName,Email,Phone,
           BillingAddress1,BillingCity,BillingState,BillingZip,BillingCountry,PaymentTerms)
        OUTPUT INSERTED.CustomerID
        VALUES (:bid,:dn,:co,:fn,:ln,:em,:ph,:a,:ci,:st,:zp,'US',:pt)
    """, {"bid":BID,"dn":dn,"co":co,"fn":fn,"ln":ln,"em":email,"ph":phone,
          "a":addr,"ci":city,"st":state,"zp":zp,"pt":terms})
    return row[0]

c1 = add_customer("La Montanita Co-op","La Montanita Co-op","",   "",    "buyers@lamontanita.coop","505-217-2090","3601 Old Airport Rd","Albuquerque","NM","87114")
c2 = add_customer("Farm Table Restaurant","Farm Table","Chef","Maria","orders@farmtableabq.com","505-400-1122","2400 Central Ave SE","Albuquerque","NM","87106","Net15")
c3 = add_customer("Santa Fe Farmers Market","Santa Fe Farmers Market","","","info@sfmarketplace.org","505-983-4098","1607 Paseo de Peralta","Santa Fe","NM","87501")
c4 = add_customer("Green Sprouts Grocery","Green Sprouts","Tom","Harker","tom@greensprouts.com","505-555-0182","820 Lomas Blvd NW","Albuquerque","NM","87102","Net30")
c5 = add_customer("Blue Corn Cafe","Blue Corn Cafe","","","orders@bluecorn.com","505-984-1800","133 Water St","Santa Fe","NM","87501","Due on Receipt")
db.commit()
print(f"  Created 5 customers (IDs {c1}-{c5}).")

# ── 4. Vendors ────────────────────────────────────────────────────────────────
print("\n[4] Adding vendors...")

def add_vendor(dn, co, fn, ln, email, phone, addr, city, state, zp, is1099=0):
    row = r1(db, """
        INSERT INTO AccountingVendors
          (BusinessID,DisplayName,CompanyName,FirstName,LastName,Email,Phone,
           Address1,City,State,Zip,Country,PaymentTerms,Is1099)
        OUTPUT INSERTED.VendorID
        VALUES (:bid,:dn,:co,:fn,:ln,:em,:ph,:a,:ci,:st,:zp,'US','Net30',:t)
    """, {"bid":BID,"dn":dn,"co":co,"fn":fn,"ln":ln,"em":email,"ph":phone,
          "a":addr,"ci":city,"st":state,"zp":zp,"t":is1099})
    return row[0]

v1 = add_vendor("High Desert Seeds","High Desert Seeds Inc","","","orders@highdesertseeds.com","505-200-4400","PO Box 772","Espanola","NM","87532")
v2 = add_vendor("Southwest Ag Supply","Southwest Ag Supply","","","billing@swag.com","505-555-0300","4200 Second St SW","Albuquerque","NM","87105")
v3 = add_vendor("RioGrande Fuel Co","RioGrande Fuel","","","billing@riograndefuel.com","505-555-0401","8800 Rio Grande Blvd","Albuquerque","NM","87114")
v4 = add_vendor("NM Labor Contractor","NM Labor LLC","Jorge","Reyes","jorge@nmlabor.com","505-555-0502","1200 Fourth St NW","Albuquerque","NM","87102",1)
v5 = add_vendor("State Farm Insurance","State Farm","","","nm.farm@statefarm.com","505-555-0601","6001 Montgomery Blvd NE","Albuquerque","NM","87109")
db.commit()
print(f"  Created 5 vendors (IDs {v1}-{v5}).")

# ── 5. Items ──────────────────────────────────────────────────────────────────
print("\n[5] Adding items...")

def add_item(itype, sku, name, desc, sale_price, purch_price, sale_acct, purch_acct, taxable=1):
    row = r1(db, """
        INSERT INTO Items (BusinessID,ItemType,SKU,Name,Description,SalePrice,PurchasePrice,
          SaleAccountID,PurchaseAccountID,Taxable)
        OUTPUT INSERTED.ItemID
        VALUES (:bid,:t,:sku,:name,:desc,:sp,:pp,:sa,:pa,:tax)
    """, {"bid":BID,"t":itype,"sku":sku,"name":name,"desc":desc,
          "sp":sale_price,"pp":purch_price,"sa":sale_acct,"pa":purch_acct,"tax":taxable})
    return row[0]

i_org_veg = add_item("Inventory","ORG-VEG","Organic Mixed Vegetables","Seasonal organic vegetable mix",4.50,1.80,REV,COGS)
i_tomatoes = add_item("Inventory","TOM-HEIR","Heirloom Tomatoes","Assorted heirloom tomatoes per lb",3.75,1.20,REV,COGS)
i_greens   = add_item("Inventory","MIX-GRN","Mixed Greens","Fresh salad greens per lb",5.00,1.50,REV,COGS)
i_eggs     = add_item("Inventory","EGGS-DZ","Free-Range Eggs","Dozen free-range eggs",7.00,2.50,REV,COGS)
i_honey    = add_item("Inventory","HONEY-PT","Raw Wildflower Honey","1 pint raw honey",14.00,4.00,REV,COGS)
i_delivery = add_item("Service","DELIV","Delivery Service","Farm delivery fee",25.00,0,REV,None,0)
db.commit()
print(f"  Created 6 items.")

# ── 6. Journal entry helper ───────────────────────────────────────────────────

_je_counter = [s(db,"SELECT ISNULL(MAX(CAST(SUBSTRING(EntryNumber,4,10) AS INT)),0) FROM JournalEntries WHERE BusinessID=:bid",{"bid":BID}) or 0]

def next_je_num():
    _je_counter[0] += 1
    return f"JE-{str(_je_counter[0]).zfill(5)}"

def create_je(date, desc, ref, src_type, src_id, lines):
    """lines: list of (account_id, debit, credit, description)"""
    je_id = r1(db, """
        INSERT INTO JournalEntries (BusinessID,EntryNumber,EntryDate,Description,Reference,SourceType,SourceID,IsPosted,CreatedBy)
        OUTPUT INSERTED.JournalEntryID
        VALUES (:bid,:num,:date,:desc,:ref,:st,:si,1,1)
    """, {"bid":BID,"num":next_je_num(),"date":date,"desc":desc,"ref":ref,"st":src_type,"si":src_id})[0]
    for i,(acct_id,debit,credit,ldesc) in enumerate(l for l in lines if l is not None):
        if acct_id:
            db.execute(text("""
                INSERT INTO JournalEntryLines (JournalEntryID,BusinessID,AccountID,DebitAmount,CreditAmount,Description,LineOrder)
                VALUES (:je,:bid,:acct,:dr,:cr,:desc,:ord)
            """), {"je":je_id,"bid":BID,"acct":acct_id,"dr":debit,"cr":credit,"desc":ldesc,"ord":i})
    return je_id

# ── 7. Invoices ───────────────────────────────────────────────────────────────
print("\n[6] Adding invoices...")

_inv_counter = [0]
def next_inv_num():
    _inv_counter[0] += 1
    return f"INV-{str(_inv_counter[0]).zfill(5)}"

def add_invoice(cust_id, inv_date, due_date, status, lines, notes=""):
    """lines: list of (item_id, desc, qty, unit_price, tax_amount)"""
    sub   = sum(l[2]*l[3] for l in lines)
    tax   = sum(l[4] for l in lines)
    total = sub + tax
    amt_paid = total if status == "Paid" else 0
    bal  = total - amt_paid

    num = next_inv_num()
    inv_id = r1(db, """
        INSERT INTO Invoices (BusinessID,CustomerID,InvoiceNumber,InvoiceDate,DueDate,Status,
          SubTotal,TaxAmount,TotalAmount,AmountPaid,BalanceDue,Notes,PaymentTerms,CreatedBy)
        OUTPUT INSERTED.InvoiceID
        VALUES (:bid,:cid,:num,:date,:due,:status,:sub,:tax,:total,:paid,:bal,:notes,'Net30',1)
    """, {"bid":BID,"cid":cust_id,"num":num,"date":inv_date,"due":due_date,
          "status":status,"sub":sub,"tax":tax,"total":total,"paid":amt_paid,"bal":bal,"notes":notes})[0]

    for i,(item_id,desc,qty,price,tax_amt) in enumerate(lines):
        lt = qty*price + tax_amt
        db.execute(text("""
            INSERT INTO InvoiceLines (InvoiceID,BusinessID,ItemID,AccountID,Description,
              Quantity,UnitPrice,TaxAmount,LineTotal,LineOrder)
            VALUES (:inv,:bid,:item,:acct,:desc,:qty,:price,:tax,:lt,:ord)
        """), {"inv":inv_id,"bid":BID,"item":item_id,"acct":REV,"desc":desc,
              "qty":qty,"price":price,"tax":tax_amt,"lt":lt,"ord":i})

    je_id = create_je(inv_date, f"Invoice {num}", num, "Invoice", inv_id, [
        (AR,  total, 0,   f"AR - {num}"),
        (REV, 0,     sub, f"Revenue - {num}"),
        (TAX, 0,     tax, f"Sales Tax - {num}") if tax else None,
    ])
    db.execute(text("UPDATE Invoices SET JournalEntryID=:je WHERE InvoiceID=:id"), {"je":je_id,"id":inv_id})
    return inv_id, num, total

# 10 invoices spanning last 5 months
invoices = [
    # (cust, inv_date, due_date, status, [(item_id,desc,qty,price,tax)])
    (c1, d(-120), d(-90), "Paid",   [(i_org_veg,"Organic Mixed Veg - Jan delivery",80,4.50,0),(i_greens,"Mixed Greens",40,5.00,0),(i_delivery,"Delivery",1,25.00,0)]),
    (c2, d(-105), d(-90), "Paid",   [(i_tomatoes,"Heirloom Tomatoes",60,3.75,0),(i_eggs,"Free-Range Eggs",24,7.00,0)]),
    (c3, d(-90),  d(-60), "Paid",   [(i_honey,"Raw Wildflower Honey",30,14.00,0),(i_org_veg,"Organic Veg Mix",50,4.50,0)]),
    (c4, d(-75),  d(-45), "Paid",   [(i_greens,"Mixed Greens",35,5.00,0),(i_tomatoes,"Heirloom Tomatoes",25,3.75,0),(i_delivery,"Delivery",1,25.00,0)]),
    (c5, d(-60),  d(-45), "Paid",   [(i_eggs,"Free-Range Eggs",36,7.00,0),(i_honey,"Honey",10,14.00,0)]),
    (c1, d(-45),  d(-15), "Paid",   [(i_org_veg,"Organic Veg Mix - Apr",100,4.50,0),(i_greens,"Mixed Greens",60,5.00,0),(i_delivery,"Delivery",1,25.00,0)]),
    (c2, d(-30),  d(0),   "Sent",   [(i_tomatoes,"Heirloom Tomatoes",80,3.75,0),(i_eggs,"Free-Range Eggs",48,7.00,0)]),
    (c3, d(-20),  d(10),  "Sent",   [(i_honey,"Honey - May market",20,14.00,0),(i_org_veg,"Org Veg",70,4.50,0),(i_delivery,"Delivery",1,25.00,0)]),
    (c4, d(-50),  d(-20), "Overdue",[(i_greens,"Mixed Greens",45,5.00,0),(i_tomatoes,"Tomatoes",30,3.75,0)]),
    (c5, d(-10),  d(20),  "Draft",  [(i_eggs,"Free-Range Eggs",60,7.00,0),(i_honey,"Honey",15,14.00,0)]),
]

inv_ids = []
for args in invoices:
    inv_id, num, total = add_invoice(*args[:4], args[4])
    inv_ids.append((inv_id, num, total, args[3]))  # id, num, total, status
db.commit()
print(f"  Created {len(inv_ids)} invoices.")

# ── 8. Payments for paid invoices ─────────────────────────────────────────────
print("\n[7] Adding customer payments...")

_pmt_counter = [0]
def next_pmt_num():
    _pmt_counter[0] += 1
    return f"PMT-{str(_pmt_counter[0]).zfill(5)}"

paid_methods = ["ACH","ACH","Check","ACH","Cash","ACH"]
for i,(inv_id, num, total, status) in enumerate(inv_ids):
    if status != "Paid":
        continue
    method = paid_methods[i % len(paid_methods)]
    pmt_date = (TODAY + datetime.timedelta(days=-max(5, inv_ids.index((inv_id,num,total,status))*15+5))).strftime("%Y-%m-%d")
    pmt_num = next_pmt_num()
    cust_id = invoices[i][0]
    pmt_id = r1(db, """
        INSERT INTO Payments (BusinessID,CustomerID,PaymentNumber,PaymentDate,PaymentMethod,
          Amount,UnusedAmount,DepositAccountID,CreatedBy)
        OUTPUT INSERTED.PaymentID
        VALUES (:bid,:cid,:num,:date,:method,:amt,0,:dep,1)
    """, {"bid":BID,"cid":cust_id,"num":pmt_num,"date":pmt_date,
          "method":method,"amt":total,"dep":CASH})[0]
    db.execute(text("""
        INSERT INTO PaymentApplications (PaymentID,InvoiceID,BusinessID,AmountApplied)
        VALUES (:pid,:inv,:bid,:amt)
    """), {"pid":pmt_id,"inv":inv_id,"bid":BID,"amt":total})
    # Journal: DR Cash, CR AR
    create_je(pmt_date, f"Payment {pmt_num} - {num}", pmt_num, "Payment", pmt_id, [
        (CASH, total, 0,     f"Cash received - {num}"),
        (AR,   0,     total, f"AR cleared - {num}"),
    ])
db.commit()
print(f"  Payments created for all Paid invoices.")

# ── 9. Bills ──────────────────────────────────────────────────────────────────
print("\n[8] Adding vendor bills...")

_bill_counter = [0]
def next_bill_num():
    _bill_counter[0] += 1
    return f"BILL-{str(_bill_counter[0]).zfill(5)}"

def add_bill(vendor_id, bill_date, due_date, status, lines, notes=""):
    """lines: list of (account_id, desc, qty, unit_price)"""
    sub   = sum(l[2]*l[3] for l in lines)
    num   = next_bill_num()
    bal   = 0 if status == "Paid" else sub
    bill_id = r1(db, """
        INSERT INTO Bills (BusinessID,VendorID,BillNumber,BillDate,DueDate,Status,
          SubTotal,TaxAmount,TotalAmount,BalanceDue,Notes,CreatedBy)
        OUTPUT INSERTED.BillID
        VALUES (:bid,:vid,:num,:date,:due,:status,:sub,0,:sub,:bal,:notes,1)
    """, {"bid":BID,"vid":vendor_id,"num":num,"date":bill_date,"due":due_date,
          "status":status,"sub":sub,"bal":bal,"notes":notes})[0]
    for i,(acct_id,desc,qty,price) in enumerate(lines):
        db.execute(text("""
            INSERT INTO BillLines (BillID,BusinessID,AccountID,Description,Quantity,
              UnitPrice,TaxAmount,LineTotal,LineOrder)
            VALUES (:bid2,:bid,:acct,:desc,:qty,:price,0,:lt,:ord)
        """), {"bid2":bill_id,"bid":BID,"acct":acct_id,"desc":desc,
              "qty":qty,"price":price,"lt":qty*price,"ord":i})
    return bill_id, num, sub

bills_data = [
    (v1, d(-110), d(-80), "Paid",   [(COGS,"Spring seed order - tomatoes/peppers/squash",1,850.00)]),
    (v2, d(-95),  d(-65), "Paid",   [(SUPP,"Irrigation supplies & drip tape",1,620.00),(SUPP,"Row cover material",1,180.00)]),
    (v3, d(-75),  d(-45), "Paid",   [(FUEL,"Diesel fuel - tractor & delivery van",1,395.00)]),
    (v4, d(-55),  d(-25), "Paid",   [(WAGES,"Seasonal harvest labor - March",1,2400.00)]),
    (v1, d(-30),  d(0),   "Open",   [(COGS,"Summer seed order - squash/beans/corn",1,1100.00)]),
    (v2, d(-20),  d(10),  "Open",   [(SUPP,"Potting soil & containers",1,340.00),(SUPP,"Pest control supplies",1,95.00)]),
    (v3, d(-10),  d(20),  "Open",   [(FUEL,"Diesel fuel - May",1,420.00)]),
    (v5, d(-85),  d(-55), "Paid",   [(INS,"Farm liability insurance - Q2",1,875.00)]),
]

for args in bills_data:
    add_bill(*args)
db.commit()
print(f"  Created {len(bills_data)} bills.")

# ── 10. Expenses ──────────────────────────────────────────────────────────────
print("\n[9] Adding expenses...")

def add_expense(vendor_id, date, method, pay_acct, lines, notes=""):
    """lines: list of (account_id, desc, amount)"""
    total = sum(l[2] for l in lines)
    exp_id = r1(db, """
        INSERT INTO Expenses (BusinessID,VendorID,PaymentAccountID,ExpenseDate,PaymentMethod,
          TotalAmount,Notes,CreatedBy)
        OUTPUT INSERTED.ExpenseID
        VALUES (:bid,:vid,:pacct,:date,:method,:total,:notes,1)
    """, {"bid":BID,"vid":vendor_id,"pacct":pay_acct,"date":date,"method":method,
          "total":total,"notes":notes})[0]
    for i,(acct_id,desc,amt) in enumerate(lines):
        db.execute(text("""
            INSERT INTO ExpenseLines (ExpenseID,BusinessID,AccountID,Description,Amount,IsBillable,LineOrder)
            VALUES (:eid,:bid,:acct,:desc,:amt,0,:ord)
        """), {"eid":exp_id,"bid":BID,"acct":acct_id,"desc":desc,"amt":amt,"ord":i})
    create_je(date, f"Expense - {notes or 'operating'}", None, "Expense", exp_id, [
        (EXP,  total, 0,     f"Expense - {notes}"),
        (CASH, 0,     total, "Cash/Card payment"),
    ])
    return exp_id

expenses_data = [
    (v3,  d(-115), "Credit Card", CASH, [(FUEL,  "Fuel - farm truck",   210.00)],  "Feb fuel"),
    (None,d(-100), "Credit Card", CASH, [(UTIL,  "Electric - pump house",148.50),(UTIL,"Water service",62.00)], "Utilities Feb"),
    (v2,  d(-80),  "Check",       CASH, [(SUPP,  "Hand tools & supplies",185.00)], "Tools purchase"),
    (None,d(-65),  "Credit Card", CASH, [(MKTG,  "Farmers market booth fee",75.00),(MKTG,"Online listings",30.00)], "Marketing Mar"),
    (None,d(-50),  "Credit Card", CASH, [(UTIL,  "Electric - irrigation pump",162.75),(UTIL,"Cell phone",85.00)], "Utilities Mar"),
    (v3,  d(-40),  "Credit Card", CASH, [(FUEL,  "Diesel - tractor",    245.00)],  "Apr fuel"),
    (None,d(-25),  "Credit Card", CASH, [(MKTG,  "Santa Fe market booth",75.00),(MKTG,"Social media ads",55.00)], "Marketing Apr"),
    (None,d(-15),  "Credit Card", CASH, [(UTIL,  "Electric bill",       170.50),(UTIL,"Internet",79.99)], "Utilities Apr"),
    (v2,  d(-8),   "Check",       CASH, [(SUPP,  "Packaging & labels",  135.00),(SUPP,"Plastic clamshells",90.00)], "Packaging May"),
    (None,d(-3),   "Credit Card", CASH, [(MKTG,  "Farmers market fee",  75.00)],  "Market fee May"),
]

for args in expenses_data:
    add_expense(*args)
db.commit()
print(f"  Created {len(expenses_data)} expenses.")

# ── 11. Summary ───────────────────────────────────────────────────────────────
print("\n=== Accounting seed complete for BusinessID=15671 ===")
inv_total   = s(db,"SELECT ISNULL(SUM(TotalAmount),0) FROM Invoices WHERE BusinessID=:bid",{"bid":BID})
inv_paid    = s(db,"SELECT COUNT(*) FROM Invoices WHERE BusinessID=:bid AND Status='Paid'",{"bid":BID})
inv_open    = s(db,"SELECT COUNT(*) FROM Invoices WHERE BusinessID=:bid AND Status NOT IN ('Paid','Void','Draft')",{"bid":BID})
bill_total  = s(db,"SELECT ISNULL(SUM(TotalAmount),0) FROM Bills WHERE BusinessID=:bid",{"bid":BID})
bill_open   = s(db,"SELECT COUNT(*) FROM Bills WHERE BusinessID=:bid AND Status='Open'",{"bid":BID})
exp_total   = s(db,"SELECT ISNULL(SUM(TotalAmount),0) FROM Expenses WHERE BusinessID=:bid",{"bid":BID})
je_count    = s(db,"SELECT COUNT(*) FROM JournalEntries WHERE BusinessID=:bid",{"bid":BID})
cust_count  = s(db,"SELECT COUNT(*) FROM AccountingCustomers WHERE BusinessID=:bid",{"bid":BID})
vend_count  = s(db,"SELECT COUNT(*) FROM AccountingVendors WHERE BusinessID=:bid",{"bid":BID})

print(f"  Customers:        {cust_count}")
print(f"  Vendors:          {vend_count}")
print(f"  Invoices:         {len(inv_ids)} total | {inv_paid} paid | {inv_open} open/overdue")
print(f"  Invoice value:    ${float(inv_total):,.2f}")
print(f"  Bills:            {len(bills_data)} total | {bill_open} open")
print(f"  Bill value:       ${float(bill_total):,.2f}")
print(f"  Expenses:         {len(expenses_data)} | total ${float(exp_total):,.2f}")
print(f"  Journal entries:  {je_count}")
