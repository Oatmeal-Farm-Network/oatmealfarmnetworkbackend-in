# herd_health_accounting.py
# Auto-posts balanced journal entries for herd-health and event-cart financials.
#
# SourceType values (idempotent key for de-duplication):
#   herd_vet_visit        — VetVisit.Cost (expense)
#   herd_treatment        — Treatment.Cost (expense)
#   herd_mortality_ins    — Mortality.InsuranceAmount when InsuranceClaim=True (income)
#   event_cart            — EventRegistrationCart.AmountPaid (income)
#
# Pattern:
#   Expense → Debit 6xxx Expense account  / Credit 1000 Checking
#   Income  → Debit 1000 Checking         / Credit 4xxx Revenue account

from sqlalchemy import text
from sqlalchemy.orm import Session


# ── account lookup helpers ─────────────────────────────────────────────────────

def _acct(db: Session, business_id: int, number: str):
    row = db.execute(
        text("SELECT TOP 1 AccountID FROM Accounts WHERE BusinessID=:b AND AccountNumber=:n AND IsActive=1"),
        {"b": business_id, "n": number},
    ).fetchone()
    return row[0] if row else None


def _find_expense_acct(db: Session, business_id: int):
    """Best-match livestock/veterinary expense account (6xxx)."""
    for kw in ("%veterinar%", "%livestock%", "%animal health%", "%medical%", "%farm%"):
        row = db.execute(
            text("SELECT TOP 1 AccountID FROM Accounts "
                 "WHERE BusinessID=:b AND AccountNumber LIKE '6%' AND LOWER(AccountName) LIKE :kw AND IsActive=1 "
                 "ORDER BY AccountNumber"),
            {"b": business_id, "kw": kw},
        ).fetchone()
        if row:
            return row[0]
    # Fallback: lowest 6xxx account
    row = db.execute(
        text("SELECT TOP 1 AccountID FROM Accounts "
             "WHERE BusinessID=:b AND AccountNumber LIKE '6%' AND IsActive=1 ORDER BY AccountNumber"),
        {"b": business_id},
    ).fetchone()
    return row[0] if row else None


def _find_cash_acct(db: Session, business_id: int):
    """1000 Checking preferred, then any 1xxx cash-like account."""
    acct = _acct(db, business_id, "1000")
    if acct:
        return acct
    row = db.execute(
        text("SELECT TOP 1 AccountID FROM Accounts "
             "WHERE BusinessID=:b AND AccountNumber LIKE '1%' "
             "AND (LOWER(AccountName) LIKE '%check%' OR LOWER(AccountName) LIKE '%cash%') AND IsActive=1 "
             "ORDER BY AccountNumber"),
        {"b": business_id},
    ).fetchone()
    return row[0] if row else None


def _find_revenue_acct(db: Session, business_id: int, prefer_service: bool = False):
    """4000 Sales or 4100 Service Revenue."""
    acct = _acct(db, business_id, "4100" if prefer_service else "4000")
    if acct:
        return acct
    # any 4xxx
    row = db.execute(
        text("SELECT TOP 1 AccountID FROM Accounts "
             "WHERE BusinessID=:b AND AccountNumber LIKE '4%' AND IsActive=1 ORDER BY AccountNumber"),
        {"b": business_id},
    ).fetchone()
    return row[0] if row else None


# ── journal entry helpers ──────────────────────────────────────────────────────

def _next_je_number(db: Session, business_id: int) -> str:
    row = db.execute(
        text("SELECT TOP 1 EntryNumber FROM JournalEntries WHERE BusinessID=:b ORDER BY EntryNumber DESC"),
        {"b": business_id},
    ).fetchone()
    if not row or not row[0]:
        return "JE-00001"
    try:
        n = int(str(row[0]).rsplit("-", 1)[-1]) + 1
    except ValueError:
        n = 1
    return f"JE-{n:05d}"


def _existing_je(db: Session, source_type: str, source_id: int):
    row = db.execute(
        text("SELECT TOP 1 JournalEntryID FROM JournalEntries WHERE SourceType=:st AND SourceID=:sid"),
        {"st": source_type, "sid": source_id},
    ).fetchone()
    return row[0] if row else None


def _delete_je(db: Session, je_id: int):
    db.execute(text("DELETE FROM JournalEntryLines WHERE JournalEntryID=:id"), {"id": je_id})
    db.execute(text("DELETE FROM JournalEntries WHERE JournalEntryID=:id"), {"id": je_id})


def _biz_contact(db: Session, business_id: int) -> int:
    row = db.execute(
        text("SELECT TOP 1 Contact1PeopleID FROM Business WHERE BusinessID=:b"),
        {"b": business_id},
    ).fetchone()
    return row[0] if row and row[0] else 1


def _insert_je(db: Session, business_id: int, entry_date, description: str,
               source_type: str, source_id: int, lines: list,
               created_by: int = None) -> int:
    num = _next_je_number(db, business_id)
    by = created_by or _biz_contact(db, business_id)
    row = db.execute(
        text("""
            INSERT INTO JournalEntries
                (BusinessID, EntryNumber, EntryDate, Description, SourceType, SourceID, IsPosted, CreatedBy)
            OUTPUT INSERTED.JournalEntryID
            VALUES (:b, :num, :dt, :desc, :st, :sid, 1, :by)
        """),
        {"b": business_id, "num": num, "dt": entry_date, "desc": description,
         "st": source_type, "sid": source_id, "by": by},
    ).fetchone()
    je_id = row[0]
    for i, (acct, dr, cr, line_desc) in enumerate(lines):
        db.execute(
            text("""
                INSERT INTO JournalEntryLines
                    (JournalEntryID, BusinessID, AccountID, DebitAmount, CreditAmount, Description, LineOrder)
                VALUES (:je, :b, :acct, :dr, :cr, :desc, :ord)
            """),
            {"je": je_id, "b": business_id, "acct": acct, "dr": dr, "cr": cr,
             "desc": line_desc, "ord": i},
        )
    return je_id


# ── public API ─────────────────────────────────────────────────────────────────

def post_expense_je(db: Session, business_id: int, amount, entry_date,
                    description: str, source_type: str, source_id: int) -> bool:
    """
    Debit Expense (6xxx) / Credit Cash (1000).
    Replaces any prior JE for the same source (idempotent on update).
    Returns True if posted, False if skipped.
    """
    if not amount or float(amount) <= 0:
        return False
    amt = round(float(amount), 2)

    exp_acct  = _find_expense_acct(db, business_id)
    cash_acct = _find_cash_acct(db, business_id)
    if not (exp_acct and cash_acct):
        print(f"[herd_accounting] no CoA for expense {source_type}#{source_id} biz={business_id}")
        return False

    existing = _existing_je(db, source_type, source_id)
    if existing:
        _delete_je(db, existing)

    _insert_je(db, business_id, entry_date, description, source_type, source_id, [
        (exp_acct,  amt, 0.0,  description),
        (cash_acct, 0.0, amt,  "Cash payment"),
    ])
    return True


def post_income_je(db: Session, business_id: int, amount, entry_date,
                   description: str, source_type: str, source_id: int,
                   prefer_service: bool = False) -> bool:
    """
    Debit Cash (1000) / Credit Revenue (4xxx).
    Used for insurance proceeds and event registration income.
    """
    if not amount or float(amount) <= 0:
        return False
    amt = round(float(amount), 2)

    cash_acct = _find_cash_acct(db, business_id)
    rev_acct  = _find_revenue_acct(db, business_id, prefer_service=prefer_service)
    if not (cash_acct and rev_acct):
        print(f"[herd_accounting] no CoA for income {source_type}#{source_id} biz={business_id}")
        return False

    existing = _existing_je(db, source_type, source_id)
    if existing:
        _delete_je(db, existing)

    _insert_je(db, business_id, entry_date, description, source_type, source_id, [
        (cash_acct, amt, 0.0, description),
        (rev_acct,  0.0, amt, "Revenue"),
    ])
    return True


def void_je(db: Session, source_type: str, source_id: int):
    """Remove journal entry when the source record is deleted."""
    existing = _existing_je(db, source_type, source_id)
    if existing:
        _delete_je(db, existing)


def sync_herd_health_to_accounting(db: Session, business_id: int) -> dict:
    """
    Bulk-post all unposted herd health financial records for a business.
    Safe to call repeatedly (idempotent).
    """
    posted = skipped = 0

    # ── Vet Visits ─────────────────────────────────────────────────
    visits = db.execute(
        text("SELECT VisitID, VisitDate, VetName, ClinicName, Cost FROM HerdHealthVetVisit "
             "WHERE BusinessID=:b AND Cost > 0"),
        {"b": business_id},
    ).fetchall()
    for v in visits:
        desc = f"Vet Visit — {v.VetName or v.ClinicName or 'Veterinarian'}"
        ok = post_expense_je(db, business_id, v.Cost, v.VisitDate,
                             desc, "herd_vet_visit", v.VisitID)
        if ok:
            posted += 1
        else:
            skipped += 1

    # ── Treatments ─────────────────────────────────────────────────
    txs = db.execute(
        text("SELECT TreatmentID, TreatmentDate, Diagnosis, Medication, Cost FROM HerdHealthTreatment "
             "WHERE BusinessID=:b AND Cost > 0"),
        {"b": business_id},
    ).fetchall()
    for t in txs:
        desc = f"Treatment — {t.Diagnosis or t.Medication or 'Livestock Treatment'}"
        ok = post_expense_je(db, business_id, t.Cost, t.TreatmentDate,
                             desc, "herd_treatment", t.TreatmentID)
        if ok:
            posted += 1
        else:
            skipped += 1

    # ── Mortality Insurance Proceeds ────────────────────────────────
    morts = db.execute(
        text("SELECT MortalityID, DeathDate, AnimalTag, CauseOfDeath, InsuranceAmount FROM HerdHealthMortality "
             "WHERE BusinessID=:b AND InsuranceClaim=1 AND InsuranceAmount > 0"),
        {"b": business_id},
    ).fetchall()
    for m in morts:
        desc = f"Livestock Insurance Proceeds — {m.AnimalTag or m.CauseOfDeath or 'Animal'}"
        ok = post_income_je(db, business_id, m.InsuranceAmount, m.DeathDate,
                            desc, "herd_mortality_ins", m.MortalityID)
        if ok:
            posted += 1
        else:
            skipped += 1

    db.commit()
    return {"posted": posted, "skipped": skipped}
