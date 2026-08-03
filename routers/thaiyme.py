"""
Thaiyme — Business Operations AI Agent
Gemini-powered RAG agent focused on running every business type in the OFN
directory (farm, ranch, restaurant, fiber, services, events). Surfaced on the
Accounting and Event Registration pages.

Memory model mirrors Velarian (Artemis Firestore database):
  - RAG collection:  thaiyme_collection
  - Chat memory:     Thaiyme_chats   (threads/{thread_id} + .../messages)

Sensitive data (account numbers, SSNs, full card PANs, routing #, customer PII
beyond first name + city) is REDACTED before any payload reaches the LLM.

Tool surface (intent-routed):
  - Accounting reads (invoices / customers / vendors / bills / expenses /
    accounts / reports / payments) — values redacted
  - Event registration reads (list + detail)
  - Event registration writes (update payment status, cancel, edit attendee
    contact) — gated by AccessLevelID >= 2 on the host business
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from auth import get_current_user
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os, re, datetime, uuid, logging

import models

router = APIRouter(prefix="/api/thaiyme", tags=["thaiyme-ai"])
logger = logging.getLogger("thaiyme")

AGENT_NAME = "Thaiyme"

# ── Firestore / Artemis config (mirrors Velarian) ────────────────────
GCP_PROJECT          = os.getenv("GOOGLE_CLOUD_PROJECT", "animated-flare-421518").strip()
GCP_CREDS            = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
ARTEMIS_DB           = "artemis"
THAIYME_RAG_COLLECTION   = "thaiyme_collection"
THAIYME_CHATS_COLLECTION = "Thaiyme_chats"

# Memory caps (match Saige / Velarian)
SHORT_TERM_N         = int(os.getenv("THAIYME_SHORT_TERM_N", "20"))
MAX_MESSAGE_CHARS    = int(os.getenv("THAIYME_MAX_MESSAGE_CHARS", "4000"))
RAG_TOP_K            = int(os.getenv("THAIYME_RAG_TOP_K", "8"))


# ── Pydantic ─────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    business_id: Optional[int] = None
    event_id: Optional[int] = None
    page: Optional[str] = None      # "accounting" | "event_register" | etc.
    messages: List[ChatMessage]


# ── Firestore (lazy) ─────────────────────────────────────────────────

_firestore_client = None

def _firestore():
    global _firestore_client
    if _firestore_client:
        return _firestore_client
    try:
        from google.cloud import firestore
        if GCP_CREDS:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(
                GCP_CREDS, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            _firestore_client = firestore.Client(
                project=GCP_PROJECT, database=ARTEMIS_DB, credentials=creds
            )
        else:
            _firestore_client = firestore.Client(project=GCP_PROJECT, database=ARTEMIS_DB)
        logger.info("[Thaiyme] Firestore (Artemis) connected")
    except Exception as e:
        logger.warning("[Thaiyme] Firestore unavailable: %s", e)
    return _firestore_client


# Default Firestore DB — agent_briefings written here by Cassia (separate from Artemis)
_firestore_default_client = None

def _firestore_default():
    global _firestore_default_client
    if _firestore_default_client:
        return _firestore_default_client
    try:
        from google.cloud import firestore
        if GCP_CREDS:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(
                GCP_CREDS, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            _firestore_default_client = firestore.Client(
                project=GCP_PROJECT, credentials=creds
            )
        else:
            _firestore_default_client = firestore.Client(project=GCP_PROJECT)
        logger.info("[Thaiyme] Firestore (default) connected")
    except Exception as e:
        logger.warning("[Thaiyme] Default Firestore unavailable: %s", e)
    return _firestore_default_client


def _get_onboarding_context(business_id: int) -> str:
    """Fetch the Cassia-written onboarding briefing for this business.

    Reads from two Firestore documents in the default database:
    - agent_briefings/business_{id}   — freetext briefing (written by Cassia)
    - org_profiles/{id}               — canonical structured profile (mirrored by Cassia)

    Returns a combined plain-text context string or '' if nothing is found.
    """
    if not business_id:
        return ""
    db = _firestore_default()
    if not db:
        return ""

    text = ""
    structured: dict = {}

    try:
        snap = db.collection("agent_briefings").document(
            f"business_{business_id}"
        ).get()
        if snap.exists:
            text = (snap.to_dict() or {}).get("text", "")
    except Exception as e:
        logger.debug("[Thaiyme] agent_briefings fetch error: %s", e)

    try:
        snap2 = db.collection("org_profiles").document(str(business_id)).get()
        if snap2.exists:
            structured = snap2.to_dict() or {}
    except Exception as e:
        logger.debug("[Thaiyme] org_profiles fetch error: %s", e)

    # Append structured fields not already expressed in the text briefing
    extras: list[str] = []
    if structured.get("plan_tier"):
        extras.append(f"• Subscription tier: {structured['plan_tier']}")
    if structured.get("business_type"):
        extras.append(f"• Business type: {structured['business_type']}")
    if structured.get("revenue_model"):
        extras.append(f"• Revenue model: {structured['revenue_model']}")
    if structured.get("cuisine_type"):
        extras.append(f"• Cuisine type: {structured['cuisine_type']}")
    if structured.get("sourcing_prefs"):
        extras.append(f"• Sourcing preferences: {structured['sourcing_prefs']}")

    if extras:
        supplement = "\n".join(extras)
        text = f"{text}\n{supplement}".strip() if text else supplement

    return text


# ── Redaction layer ──────────────────────────────────────────────────
# Run on every payload built from SQL before it hits the LLM. Velarian-style:
# the LLM never sees full SSNs, PANs, or routing numbers — and customer PII
# beyond a first-name + city is dropped.

_SSN_RE        = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PAN_RE        = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_ROUTING_RE    = re.compile(r"\b\d{9}\b")
_EMAIL_RE      = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Phone: includes optional surrounding parens around the area code so the
# whole token (e.g. "(415) 555-1212") is consumed in one match — otherwise
# \b after `(` left the leading paren behind.
_PHONE_RE      = re.compile(
    r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}"
)

# Field names that should be redacted wholesale (last4 only when present).
_PII_FIELDS = {
    "ssn", "tax_id", "ein", "stripepaymentintentid", "stripechargeid",
    "stripecustomerid", "accountnumber", "routingnumber", "cardnumber", "pan",
    "billingaddress1", "billingaddress2", "address1", "address2",
}
_PARTIAL_PII_FIELDS = {
    # Keep first name + last initial only.
    "firstname": lambda v: str(v).strip(),
    "lastname":  lambda v: (str(v).strip()[:1] + ".") if str(v).strip() else "",
    "email":     lambda v: _mask_email(v),
    "phone":     lambda v: _mask_phone(v),
}


def _mask_email(v: str) -> str:
    if not v: return ""
    s = str(v)
    m = _EMAIL_RE.search(s)
    if not m: return ""
    local, dom = m.group(0).split("@", 1)
    return f"{local[:1]}***@{dom}"


def _mask_phone(v: str) -> str:
    if not v: return ""
    digits = re.sub(r"\D", "", str(v))
    return f"***-***-{digits[-4:]}" if len(digits) >= 4 else "***"


def _redact_str(s: str) -> str:
    if not isinstance(s, str): return s
    s = _SSN_RE.sub("[SSN-REDACTED]", s)
    s = _PAN_RE.sub(lambda m: "****-****-****-" + re.sub(r"\D", "", m.group(0))[-4:], s)
    s = _EMAIL_RE.sub(lambda m: _mask_email(m.group(0)), s)
    s = _PHONE_RE.sub(lambda m: _mask_phone(m.group(0)), s)
    # Routing numbers are bare 9-digit strings — strip after PAN/SSN to avoid stomping.
    s = _ROUTING_RE.sub("[ROUTING-REDACTED]", s)
    return s


def redact_record(rec: Any) -> Any:
    """Deep-redact dict/list of strings before sending to the LLM."""
    if rec is None:
        return None
    if isinstance(rec, list):
        return [redact_record(r) for r in rec]
    if isinstance(rec, dict):
        out = {}
        for k, v in rec.items():
            kl = k.lower()
            if kl in _PII_FIELDS:
                out[k] = "[REDACTED]"
            elif kl in _PARTIAL_PII_FIELDS:
                out[k] = _PARTIAL_PII_FIELDS[kl](v) if v is not None else None
            else:
                out[k] = redact_record(v)
        return out
    if isinstance(rec, str):
        return _redact_str(rec)
    return rec


# ── Access guards ────────────────────────────────────────────────────

def _check_business_access(db: Session, people_id: int, business_id: int, min_level: int = 1):
    row = db.query(models.BusinessAccess).filter(
        models.BusinessAccess.BusinessID == business_id,
        models.BusinessAccess.PeopleID == people_id,
        models.BusinessAccess.Active == 1,
    ).first()
    if not row or row.AccessLevelID < min_level:
        raise HTTPException(403, f"Thaiyme requires AccessLevelID >= {min_level} on business {business_id}.")
    return row.AccessLevelID


def _check_event_access(db: Session, people_id: int, event_id: int, min_level: int = 2):
    """Allow if user has min_level access on the event's host BusinessID."""
    ev = db.execute(
        text("SELECT BusinessID FROM OFNEvents WHERE EventID = :eid"),
        {"eid": event_id},
    ).fetchone()
    if not ev:
        raise HTTPException(404, "Event not found.")
    return _check_business_access(db, people_id, int(ev.BusinessID), min_level=min_level)


# ── Accounting tool reads ────────────────────────────────────────────

def _accounting_snapshot(db: Session, business_id: int) -> Dict[str, Any]:
    """
    Pull a redacted snapshot of the business's books — invoices/bills/expenses
    summary + recent activity. Bounded (TOP rows) to keep prompt size sane.
    """
    out: Dict[str, Any] = {"business_id": business_id}

    try:
        ar = db.execute(text("""
            SELECT COUNT(1) AS n,
                   ISNULL(SUM(BalanceDue), 0) AS open_balance
              FROM Invoices WHERE BusinessID = :bid AND Status NOT IN ('Paid','Void')
        """), {"bid": business_id}).fetchone()
        out["accounts_receivable"] = {
            "open_invoices": int(ar.n or 0),
            "open_balance": float(ar.open_balance or 0),
        }
    except Exception: pass

    try:
        ap = db.execute(text("""
            SELECT COUNT(1) AS n,
                   ISNULL(SUM(BalanceDue), 0) AS open_balance
              FROM Bills WHERE BusinessID = :bid AND Status NOT IN ('Paid','Void')
        """), {"bid": business_id}).fetchone()
        out["accounts_payable"] = {
            "open_bills": int(ap.n or 0),
            "open_balance": float(ap.open_balance or 0),
        }
    except Exception: pass

    try:
        recent_inv = db.execute(text("""
            SELECT TOP 10 InvoiceNumber, InvoiceDate, DueDate, Status,
                   TotalAmount, BalanceDue
              FROM Invoices WHERE BusinessID = :bid
             ORDER BY InvoiceDate DESC
        """), {"bid": business_id}).fetchall()
        out["recent_invoices"] = [
            {
                "number": r.InvoiceNumber,
                "date": str(r.InvoiceDate) if r.InvoiceDate else None,
                "due": str(r.DueDate) if r.DueDate else None,
                "status": r.Status,
                "total": float(r.TotalAmount or 0),
                "balance": float(r.BalanceDue or 0),
            } for r in recent_inv
        ]
    except Exception: pass

    try:
        recent_exp = db.execute(text("""
            SELECT TOP 10 ExpenseDate, PaymentMethod, TotalAmount, Reference
              FROM Expenses WHERE BusinessID = :bid
             ORDER BY ExpenseDate DESC
        """), {"bid": business_id}).fetchall()
        out["recent_expenses"] = [
            {
                "date": str(r.ExpenseDate) if r.ExpenseDate else None,
                "method": r.PaymentMethod,
                "total": float(r.TotalAmount or 0),
                "reference": r.Reference,
            } for r in recent_exp
        ]
    except Exception: pass

    try:
        cust_count = db.execute(text(
            "SELECT COUNT(1) AS n FROM AccountingCustomers WHERE BusinessID = :bid AND IsActive = 1"
        ), {"bid": business_id}).fetchone()
        vend_count = db.execute(text(
            "SELECT COUNT(1) AS n FROM AccountingVendors WHERE BusinessID = :bid AND IsActive = 1"
        ), {"bid": business_id}).fetchone()
        out["customers_active"] = int(cust_count.n or 0)
        out["vendors_active"]   = int(vend_count.n or 0)
    except Exception: pass

    # Last 30d revenue / expense roll-up
    try:
        rev = db.execute(text("""
            SELECT ISNULL(SUM(TotalAmount), 0) AS revenue
              FROM Invoices
             WHERE BusinessID = :bid
               AND InvoiceDate >= DATEADD(day, -30, CAST(GETDATE() AS DATE))
        """), {"bid": business_id}).fetchone()
        exp = db.execute(text("""
            SELECT ISNULL(SUM(TotalAmount), 0) AS spend
              FROM Expenses
             WHERE BusinessID = :bid
               AND ExpenseDate >= DATEADD(day, -30, CAST(GETDATE() AS DATE))
        """), {"bid": business_id}).fetchone()
        out["last_30_days"] = {
            "revenue_invoiced": float(rev.revenue or 0),
            "expenses_paid":    float(exp.spend or 0),
        }
    except Exception: pass

    return redact_record(out)


# ── Event registration tool reads / writes ───────────────────────────

def _event_registrations(db: Session, event_id: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"event_id": event_id}
    try:
        ev = db.execute(text("""
            SELECT EventID, EventName, EventStartDate, EventEndDate,
                   EventType, BusinessID, MaxAttendees, IsFree
              FROM OFNEvents WHERE EventID = :eid
        """), {"eid": event_id}).fetchone()
        if ev:
            out["event"] = {
                "id":        ev.EventID,
                "name":      ev.EventName,
                "start":     str(ev.EventStartDate) if ev.EventStartDate else None,
                "end":       str(ev.EventEndDate) if ev.EventEndDate else None,
                "type":      ev.EventType,
                "max":       ev.MaxAttendees,
                "is_free":   bool(ev.IsFree),
            }
    except Exception: pass

    try:
        regs = db.execute(text("""
            SELECT TOP 50 r.RegID, r.RegDate, r.TotalAmount, r.PaymentStatus,
                   r.AttendeeFirstName, r.AttendeeLastName, r.AttendeeEmail,
                   r.AttendeePhone, r.Notes
              FROM OFNEventRegistrations r
             WHERE r.EventID = :eid
             ORDER BY r.RegDate DESC
        """), {"eid": event_id}).fetchall()
        out["registrations"] = [
            {
                "reg_id":     r.RegID,
                "date":       str(r.RegDate) if r.RegDate else None,
                "total":      float(r.TotalAmount or 0),
                "status":     r.PaymentStatus,
                "first_name": r.AttendeeFirstName,
                "last_name":  r.AttendeeLastName,
                "email":      r.AttendeeEmail,
                "phone":      r.AttendeePhone,
                "notes":      r.Notes,
            } for r in regs
        ]
        out["registration_count"] = len(out["registrations"])
        out["paid_count"] = sum(1 for r in out["registrations"] if (r["status"] or "").lower() == "paid")
    except Exception: pass

    return redact_record(out)


# ── Sponsorship + lead retrieval reads ─────────────────────────────

def _sponsorship_summary(db: Session, event_id: int) -> Dict[str, Any]:
    rows = db.execute(text("""
        SELECT t.TierID, t.Name, t.Price, t.MaxSlots,
               COUNT(s.SponsorID) AS sponsors,
               SUM(CASE WHEN s.Status='confirmed' THEN 1 ELSE 0 END) AS confirmed,
               ISNULL(SUM(s.AmountPaid), 0) AS revenue
          FROM OFNEventSponsorTier t
          LEFT JOIN OFNEventSponsor s ON s.TierID = t.TierID
         WHERE t.EventID = :eid
         GROUP BY t.TierID, t.Name, t.Price, t.MaxSlots, t.SortOrder
         ORDER BY t.SortOrder, t.Price DESC
    """), {"eid": event_id}).fetchall()
    by_tier = []
    total_rev = 0.0; total_conf = 0; total_pipe = 0
    for r in rows:
        d = dict(r._mapping)
        rev = float(d.get("revenue") or 0)
        d["revenue"] = round(rev, 2)
        d["price"]   = float(d.get("Price") or 0)
        total_rev   += rev
        total_conf  += int(d.get("confirmed") or 0)
        total_pipe  += int(d.get("sponsors") or 0)
        by_tier.append(d)
    return {
        "event_id":        event_id,
        "total_revenue":   round(total_rev, 2),
        "total_confirmed": total_conf,
        "total_pipeline":  total_pipe,
        "by_tier":         by_tier,
    }


def _list_sponsors(db: Session, event_id: int, status: Optional[str] = None) -> Dict[str, Any]:
    where = ["s.EventID = :eid"]
    params: Dict[str, Any] = {"eid": event_id}
    if status:
        where.append("s.Status = :st"); params["st"] = status
    rows = db.execute(text(f"""
        SELECT TOP 50 s.SponsorID, s.BusinessName, s.ContactName, s.ContactEmail,
               s.ContactPhone, s.Status, s.PaidStatus, s.AmountPaid,
               s.WebsiteURL, s.Tagline,
               t.Name AS TierName, t.Price AS TierPrice
          FROM OFNEventSponsor s
          LEFT JOIN OFNEventSponsorTier t ON t.TierID = s.TierID
         WHERE {' AND '.join(where)}
         ORDER BY t.SortOrder, t.Price DESC, s.BusinessName
    """), params).fetchall()
    out = {
        "event_id": event_id,
        "status_filter": status,
        "sponsors": [
            {
                "sponsor_id":  r.SponsorID,
                "name":        r.BusinessName,
                "tier":        r.TierName,
                "tier_price":  float(r.TierPrice) if r.TierPrice is not None else None,
                "status":      r.Status,
                "paid_status": r.PaidStatus,
                "amount_paid": float(r.AmountPaid) if r.AmountPaid is not None else 0,
                "contact_name":  r.ContactName,
                "contact_email": r.ContactEmail,
                "contact_phone": r.ContactPhone,
                "website":     r.WebsiteURL,
                "tagline":     r.Tagline,
            } for r in rows
        ],
    }
    return redact_record(out)


def _leads_summary(db: Session, event_id: int, business_id: int) -> Dict[str, Any]:
    total = db.execute(text("""
        SELECT COUNT(1) AS n FROM OFNEventLeadScan
         WHERE EventID = :eid AND ExhibitorBusinessID = :biz
    """), {"eid": event_id, "biz": business_id}).fetchone()
    by_status = db.execute(text("""
        SELECT FollowUpStatus, COUNT(1) AS n FROM OFNEventLeadScan
         WHERE EventID = :eid AND ExhibitorBusinessID = :biz
         GROUP BY FollowUpStatus
    """), {"eid": event_id, "biz": business_id}).fetchall()
    by_rating = db.execute(text("""
        SELECT Rating, COUNT(1) AS n FROM OFNEventLeadScan
         WHERE EventID = :eid AND ExhibitorBusinessID = :biz AND Rating IS NOT NULL
         GROUP BY Rating
    """), {"eid": event_id, "biz": business_id}).fetchall()
    return {
        "event_id":     event_id,
        "business_id":  business_id,
        "total":        int(total.n) if total else 0,
        "by_status":    {r.FollowUpStatus: int(r.n) for r in by_status},
        "by_rating":    {int(r.Rating): int(r.n) for r in by_rating if r.Rating is not None},
    }


# ── Floor plan + booth services + COI reads ───────────────────────

def _floor_plan_summary(db: Session, event_id: int) -> Dict[str, Any]:
    by_status = db.execute(text("""
        SELECT Status, COUNT(1) AS n FROM OFNEventBooth
         WHERE EventID = :eid GROUP BY Status
    """), {"eid": event_id}).fetchall()
    by_tier = db.execute(text("""
        SELECT Tier, COUNT(1) AS n FROM OFNEventBooth
         WHERE EventID = :eid GROUP BY Tier
    """), {"eid": event_id}).fetchall()
    return {
        "event_id":  event_id,
        "total":     sum(int(r.n) for r in by_status),
        "by_status": {r.Status: int(r.n) for r in by_status},
        "by_tier":   {r.Tier:   int(r.n) for r in by_tier},
    }


def _booth_services_revenue(db: Session, event_id: int) -> Dict[str, Any]:
    rows = db.execute(text("""
        SELECT s.ServiceID, s.Name, s.Category, s.Unit,
               COUNT(o.OrderID) AS line_count,
               SUM(o.Quantity)  AS units_sold,
               SUM(ISNULL(o.UnitPrice, 0) * ISNULL(o.Quantity, 0)) AS revenue
          FROM OFNEventBoothService s
          LEFT JOIN OFNEventBoothServiceOrder o ON o.ServiceID = s.ServiceID
         WHERE s.EventID = :eid
         GROUP BY s.ServiceID, s.Name, s.Category, s.Unit, s.SortOrder
         ORDER BY s.SortOrder, s.Category, s.Name
    """), {"eid": event_id}).fetchall()
    items = [dict(r._mapping) for r in rows]
    total = sum(float(r.get("revenue") or 0) for r in items)
    return {"event_id": event_id, "total_revenue": round(total, 2), "by_service": items}


def _order_analytics(db: Session, business_id: int) -> Dict[str, Any]:
    """Aggregate order analytics: standing orders and B2B aggregator activity (last 90 days)."""
    try:
        standing = db.execute(text("""
            SELECT
                COUNT(*)                                             AS total_orders,
                COUNT(DISTINCT BuyerBusinessID)                     AS unique_buyers,
                COUNT(CASE WHEN Status = 'active'    THEN 1 END)   AS active_orders,
                COUNT(CASE WHEN Status = 'paused'    THEN 1 END)   AS paused_orders,
                COUNT(CASE WHEN Status = 'cancelled' THEN 1 END)   AS cancelled_orders
            FROM RestaurantStandingOrders
            WHERE FarmBusinessID = :bid
        """), {"bid": business_id}).mappings().first()

        top_products = db.execute(text("""
            SELECT TOP 5 ProductTitle, COUNT(*) AS order_count, Frequency
            FROM RestaurantStandingOrders
            WHERE FarmBusinessID = :bid AND Status = 'active'
            GROUP BY ProductTitle, Frequency
            ORDER BY order_count DESC
        """), {"bid": business_id}).mappings().all()

        b2b = db.execute(text("""
            SELECT
                COUNT(*)                                                AS total_b2b,
                ISNULL(SUM(TotalValue), 0)                             AS total_revenue,
                ISNULL(AVG(TotalValue), 0)                             AS avg_order_value,
                COUNT(DISTINCT AccountID)                               AS unique_accounts,
                COUNT(CASE WHEN Status = 'delivered'  THEN 1 END)      AS delivered,
                COUNT(CASE WHEN Status = 'cancelled'  THEN 1 END)      AS cancelled
            FROM OFNAggregatorB2BOrder
            WHERE BusinessID = :bid AND OrderDate >= DATEADD(day, -90, GETDATE())
        """), {"bid": business_id}).mappings().first()

        lines = ["Order analytics snapshot:"]
        if standing:
            lines.append(
                f"Standing orders: {standing['total_orders']} total "
                f"({standing['active_orders']} active, {standing['paused_orders']} paused, "
                f"{standing['cancelled_orders']} cancelled) "
                f"from {standing['unique_buyers']} unique buyers."
            )
        if top_products:
            lines.append("Top active products:")
            for p in top_products:
                lines.append(f"  • {p['ProductTitle']} — {p['order_count']} orders ({p['Frequency']})")
        if b2b:
            lines.append(
                f"B2B aggregator (last 90 days): {b2b['total_b2b']} orders, "
                f"${float(b2b['total_revenue']):,.2f} revenue, "
                f"avg ${float(b2b['avg_order_value']):,.2f}/order, "
                f"{b2b['unique_accounts']} accounts, "
                f"{b2b['delivered']} delivered, {b2b['cancelled']} cancelled."
            )
        return {"summary": "\n".join(lines)}
    except Exception as e:
        return {"error": f"Order analytics unavailable: {e}"}


def _esg_status(db: Session, business_id: int) -> Dict[str, Any]:
    """ESG snapshot for the focused business — last 90 days of live numbers
    (sourcing transparency, residue testing pass rate, cold-chain integrity,
    waste, sensors) plus the most recent saved report and recent manual
    metrics. Lets Thaiyme answer questions like 'how are we doing on EU
    compliance' or 'are we ready for an EthiFinance audit'."""
    try:
        # Reuse the live aggregator from the ESG router so the answers Thaiyme
        # gives match what the page shows.
        from routers.esg_reports import _live_metrics, _manual_metrics
        from datetime import date, timedelta
        end = date.today()
        start = end - timedelta(days=90)
        live = _live_metrics(db, business_id, start, end)
        manual = _manual_metrics(db, business_id, start, end)
    except Exception as e:
        return {"error": f"ESG snapshot unavailable: {e}"}

    latest_report = db.execute(text("""
        SELECT TOP 1 ReportID, Title, PeriodStart, PeriodEnd, GeneratedDate, Signatory
          FROM OFNESGReport
         WHERE BusinessID = :bid
         ORDER BY GeneratedDate DESC
    """), {"bid": business_id}).fetchone()

    return {
        "business_id":   business_id,
        "window":        {"start": live["period"]["start"], "end": live["period"]["end"]},
        "sourcing":      live.get("sourcing"),
        "procurement":   live.get("procurement"),
        "cold_chain":    live.get("cold_chain"),
        "waste":         live.get("waste"),
        "inputs":        live.get("inputs_to_farms"),
        "sensors":       live.get("sensors"),
        "manual_metrics_count": len(manual),
        "manual_metrics_recent": [
            {"category": m.get("Category"), "label": m.get("Label"),
             "value": m.get("Value"), "evidence": m.get("EvidenceURL")}
            for m in manual[:8]
        ],
        "latest_saved_report": (
            {
                "report_id":     int(latest_report.ReportID),
                "title":         latest_report.Title,
                "period_start":  str(latest_report.PeriodStart) if latest_report.PeriodStart else None,
                "period_end":    str(latest_report.PeriodEnd)   if latest_report.PeriodEnd   else None,
                "generated":     str(latest_report.GeneratedDate),
                "signatory":     latest_report.Signatory,
            } if latest_report else None
        ),
    }


def _coi_summary(db: Session, event_id: int) -> Dict[str, Any]:
    by_status = db.execute(text("""
        SELECT Status, COUNT(1) AS n FROM OFNEventCOI
         WHERE EventID = :eid GROUP BY Status
    """), {"eid": event_id}).fetchall()
    expiring = db.execute(text("""
        SELECT COUNT(1) AS n FROM OFNEventCOI
         WHERE EventID = :eid AND Status='approved'
           AND ExpiryDate IS NOT NULL
           AND ExpiryDate BETWEEN CAST(GETDATE() AS DATE)
                              AND DATEADD(day, 30, CAST(GETDATE() AS DATE))
    """), {"eid": event_id}).fetchone()
    return {
        "event_id":             event_id,
        "by_status":            {r.Status: int(r.n) for r in by_status},
        "expiring_in_30_days":  int(expiring.n) if expiring else 0,
    }


def _list_leads(
    db: Session,
    event_id: int,
    business_id: int,
    status: Optional[str] = None,
    rating_min: Optional[int] = None,
) -> Dict[str, Any]:
    where = ["EventID = :eid", "ExhibitorBusinessID = :biz"]
    params: Dict[str, Any] = {"eid": event_id, "biz": business_id}
    if status:
        where.append("FollowUpStatus = :st"); params["st"] = status
    if rating_min:
        where.append("Rating >= :rm"); params["rm"] = int(rating_min)
    rows = db.execute(text(f"""
        SELECT TOP 25 ScanID, ScanDate, AttendeeName, AttendeeBusiness,
               AttendeeEmail, AttendeePhone, BadgeCode, Rating, Interest,
               FollowUpStatus, Notes
          FROM OFNEventLeadScan
         WHERE {' AND '.join(where)}
         ORDER BY ScanDate DESC
    """), params).fetchall()
    out = {
        "event_id":    event_id,
        "business_id": business_id,
        "leads": [
            {
                "scan_id":          r.ScanID,
                "scan_date":        str(r.ScanDate) if r.ScanDate else None,
                "name":             r.AttendeeName,
                "business":         r.AttendeeBusiness,
                "email":            r.AttendeeEmail,
                "phone":            r.AttendeePhone,
                "badge_code":       r.BadgeCode,
                "rating":           int(r.Rating) if r.Rating is not None else None,
                "interest":         r.Interest,
                "follow_up_status": r.FollowUpStatus,
                "notes":            r.Notes,
            } for r in rows
        ],
    }
    return redact_record(out)


def _update_registration(db: Session, reg_id: int, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a small whitelist of mutations on OFNEventRegistrations."""
    allowed = {
        "PaymentStatus":      "PaymentStatus",
        "AttendeeFirstName":  "AttendeeFirstName",
        "AttendeeLastName":   "AttendeeLastName",
        "AttendeeEmail":      "AttendeeEmail",
        "AttendeePhone":      "AttendeePhone",
        "Notes":              "Notes",
    }
    sets: List[str] = []
    params: Dict[str, Any] = {"rid": reg_id}
    for k, v in (patch or {}).items():
        col = allowed.get(k)
        if not col: continue
        sets.append(f"{col} = :{col}")
        params[col] = v
    if not sets:
        raise HTTPException(400, "No supported fields in patch.")
    db.execute(text(f"UPDATE OFNEventRegistrations SET {', '.join(sets)} WHERE RegID = :rid"), params)
    db.commit()
    return {"ok": True, "reg_id": reg_id, "updated_fields": list(patch.keys())}


def _cancel_registration(db: Session, reg_id: int) -> Dict[str, Any]:
    db.execute(text("DELETE FROM OFNEventRegistrationItems WHERE RegID = :rid"), {"rid": reg_id})
    db.execute(text("DELETE FROM OFNEventRegistrations WHERE RegID = :rid"), {"rid": reg_id})
    db.commit()
    return {"ok": True, "reg_id": reg_id, "cancelled": True}


# ── RAG over thaiyme_collection ──────────────────────────────────────

def _rag_search(query: str, n: int = RAG_TOP_K) -> str:
    db = _firestore()
    if not db:
        return ""
    try:
        col = db.collection(THAIYME_RAG_COLLECTION)

        # Vector search (if embeddings present)
        try:
            from google.cloud.firestore_v1.vector import Vector
            from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
            import ai_vertex as av
            q_vec = av.embed_query(query)
            vq = col.find_nearest(
                vector_field="embedding",
                query_vector=Vector(q_vec),
                distance_measure=DistanceMeasure.COSINE,
                limit=n,
            )
            parts = []
            for doc in vq.stream():
                d = doc.to_dict() or {}
                t = d.get("content") or d.get("text") or ""
                if t: parts.append(t)
            if parts:
                return "\n---\n".join(parts)
        except Exception:
            pass  # fall through

        # Keyword fallback
        kws = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
        scored = []
        for doc in col.limit(80).stream():
            d = doc.to_dict() or {}
            content = d.get("content") or d.get("text") or " ".join(
                str(v) for v in d.values() if isinstance(v, str)
            )
            if not content.strip(): continue
            score = sum(content.lower().count(k) for k in kws)
            if score > 0: scored.append((score, content))
        scored.sort(reverse=True)
        return "\n---\n".join(c for _, c in scored[:n])
    except Exception as e:
        logger.warning("[Thaiyme] RAG error: %s", e)
        return ""


# ── Chat memory in Firestore (Velarian-style) ────────────────────────

def _thread_id_for(people_id: int, scope: str) -> str:
    return f"{people_id}__{scope}"


def _save_message(people_id: int, scope: str, role: str, content: str) -> None:
    db = _firestore()
    if not db: return
    try:
        from google.cloud import firestore as _fs
        thread_id = _thread_id_for(people_id, scope)
        thread_ref = db.collection(THAIYME_CHATS_COLLECTION).document(thread_id)
        now = datetime.datetime.utcnow().isoformat()
        snap = thread_ref.get()
        if snap.exists:
            thread_ref.update({"updated_at": now, "message_count": _fs.Increment(1)})
        else:
            thread_ref.set({
                "thread_id": thread_id,
                "people_id": people_id,
                "scope": scope,
                "created_at": now,
                "updated_at": now,
                "message_count": 1,
            })
        msg_id = f"{now}_{uuid.uuid4().hex[:8]}"
        thread_ref.collection("messages").document(msg_id).set({
            "role": role,
            "content": (content or "")[:MAX_MESSAGE_CHARS],
            "ts": now,
        })
    except Exception as e:
        logger.warning("[Thaiyme] save_message failed: %s", e)


def _load_recent_messages(people_id: int, scope: str, limit: int = SHORT_TERM_N) -> List[Dict[str, str]]:
    db = _firestore()
    if not db: return []
    try:
        from google.cloud import firestore as _fs
        thread_id = _thread_id_for(people_id, scope)
        msgs_ref = (
            db.collection(THAIYME_CHATS_COLLECTION)
              .document(thread_id)
              .collection("messages")
              .order_by("ts", direction=_fs.Query.DESCENDING)
              .limit(limit)
        )
        rows = [d.to_dict() for d in msgs_ref.stream()]
        rows.reverse()
        return [{"role": r.get("role", "user"), "content": r.get("content", "")} for r in rows]
    except Exception as e:
        logger.warning("[Thaiyme] load_messages failed: %s", e)
        return []


def _delete_thread(people_id: int, scope: str) -> bool:
    db = _firestore()
    if not db: return False
    try:
        thread_id = _thread_id_for(people_id, scope)
        thread_ref = db.collection(THAIYME_CHATS_COLLECTION).document(thread_id)
        msgs = thread_ref.collection("messages")
        while True:
            batch_docs = list(msgs.limit(100).stream())
            if not batch_docs: break
            for d in batch_docs: d.reference.delete()
        thread_ref.delete()
        return True
    except Exception as e:
        logger.warning("[Thaiyme] delete_thread failed: %s", e)
        return False


# ── Additional accounting tool reads ─────────────────────────────────

def _list_open_invoices(db: Session, business_id: int, limit: int = 25) -> Dict[str, Any]:
    rows = db.execute(text("""
        SELECT TOP (:lim) i.InvoiceID, i.InvoiceNumber, i.InvoiceDate, i.DueDate,
               i.Status, i.TotalAmount, i.BalanceDue,
               c.DisplayName AS CustomerName
          FROM Invoices i
          LEFT JOIN AccountingCustomers c ON c.CustomerID = i.CustomerID
         WHERE i.BusinessID = :bid AND i.Status NOT IN ('Paid','Void')
         ORDER BY i.DueDate ASC
    """), {"bid": business_id, "lim": limit}).fetchall()
    out = {
        "business_id": business_id,
        "open_invoices": [
            {
                "invoice_id": r.InvoiceID,
                "number":     r.InvoiceNumber,
                "date":       str(r.InvoiceDate) if r.InvoiceDate else None,
                "due":        str(r.DueDate) if r.DueDate else None,
                "status":     r.Status,
                "total":      float(r.TotalAmount or 0),
                "balance":    float(r.BalanceDue or 0),
                "customer":   r.CustomerName,
            } for r in rows
        ],
    }
    return redact_record(out)


def _find_customer(db: Session, business_id: int, query: str) -> Dict[str, Any]:
    q = f"%{(query or '').strip()}%"
    rows = db.execute(text("""
        SELECT TOP 10 CustomerID, DisplayName, CompanyName, FirstName, LastName,
               Email, Phone, BillingCity, BillingState, IsActive
          FROM AccountingCustomers
         WHERE BusinessID = :bid
           AND (DisplayName LIKE :q OR CompanyName LIKE :q
                OR FirstName LIKE :q OR LastName LIKE :q OR Email LIKE :q)
         ORDER BY DisplayName
    """), {"bid": business_id, "q": q}).fetchall()
    out = {
        "business_id": business_id,
        "query": query,
        "customers": [
            {
                "customer_id": r.CustomerID,
                "name":        r.DisplayName,
                "company":     r.CompanyName,
                "first_name":  r.FirstName,
                "last_name":   r.LastName,
                "email":       r.Email,
                "phone":       r.Phone,
                "city":        r.BillingCity,
                "state":       r.BillingState,
                "active":      bool(r.IsActive),
            } for r in rows
        ],
    }
    return redact_record(out)


def _recent_payments(db: Session, business_id: int, days: int = 30, limit: int = 25) -> Dict[str, Any]:
    rows = db.execute(text("""
        SELECT TOP (:lim) p.PaymentID, p.PaymentNumber, p.PaymentDate,
               p.PaymentMethod, p.Amount, p.Reference,
               c.DisplayName AS CustomerName
          FROM Payments p
          LEFT JOIN AccountingCustomers c ON c.CustomerID = p.CustomerID
         WHERE p.BusinessID = :bid
           AND p.PaymentDate >= DATEADD(day, -:d, CAST(GETDATE() AS DATE))
         ORDER BY p.PaymentDate DESC
    """), {"bid": business_id, "d": days, "lim": limit}).fetchall()
    out = {
        "business_id": business_id,
        "window_days": days,
        "payments": [
            {
                "payment_id": r.PaymentID,
                "number":     r.PaymentNumber,
                "date":       str(r.PaymentDate) if r.PaymentDate else None,
                "method":     r.PaymentMethod,
                "amount":     float(r.Amount or 0),
                "reference":  r.Reference,
                "customer":   r.CustomerName,
            } for r in rows
        ],
    }
    return redact_record(out)


# ── Precision-ag tools (read-only; data lives in CropMonitoringBackend) ─────
# Lets Thaiyme answer "any disease alerts on my fields?", "what's NDVI on
# field 13?", "show me stress zones" — same data Saige uses, surfaced through
# Thaiyme's function-calling registry. Calls the same crop_monitor_proxy
# routes the frontend uses, keeping a single access-control boundary.

import requests as _requests

CROP_MONITOR_URL_INT = os.getenv("CROP_MONITOR_URL", "http://127.0.0.1:8002")


def _list_my_fields(db: Session, people_id: int) -> Dict[str, Any]:
    rows = db.query(models.BusinessAccess).filter(
        models.BusinessAccess.PeopleID == people_id,
        models.BusinessAccess.Active == 1,
    ).all()
    biz_ids = [r.BusinessID for r in rows]
    if not biz_ids:
        return {"fields": [], "note": "No businesses linked to your account."}
    placeholders = ",".join(":b{}".format(i) for i in range(len(biz_ids)))
    params = {"b{}".format(i): bid for i, bid in enumerate(biz_ids)}
    fields = db.execute(
        text(f"""
            SELECT FieldID, BusinessID, Name, CropType, FieldSizeHectares,
                   PlantingDate, Latitude, Longitude
              FROM dbo.Field
             WHERE BusinessID IN ({placeholders})
               AND DeletedAt IS NULL
        """),
        params,
    ).fetchall()
    return {
        "fields": [
            {
                "field_id":     int(f.FieldID),
                "business_id":  int(f.BusinessID),
                "name":         f.Name,
                "crop":         f.CropType,
                "hectares":     float(f.FieldSizeHectares) if f.FieldSizeHectares else None,
                "planting_date": str(f.PlantingDate) if f.PlantingDate else None,
                "lat":          float(f.Latitude) if f.Latitude else None,
                "lon":          float(f.Longitude) if f.Longitude else None,
            } for f in fields
        ],
    }


def _check_field_access(db: Session, people_id: int, field_id: int) -> int:
    """Return the BusinessID for the field if accessible; raise 403 otherwise."""
    row = db.execute(
        text("SELECT BusinessID FROM dbo.Field WHERE FieldID = :fid AND DeletedAt IS NULL"),
        {"fid": field_id},
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Field {field_id} not found.")
    biz_id = int(row.BusinessID)
    _check_business_access(db, people_id, biz_id, min_level=1)
    return biz_id


def _crop_monitor_get(path: str, params: Optional[Dict[str, Any]] = None,
                      timeout: int = 60) -> Dict[str, Any]:
    """Call CropMonitoringBackend directly (we're in the same process as the proxy
    but bypassing it avoids re-running access checks already done at the tool layer)."""
    try:
        r = _requests.get(f"{CROP_MONITOR_URL_INT}{path}", params=params or {}, timeout=timeout)
    except _requests.RequestException as e:
        return {"error": f"crop-monitor unreachable: {e}"}
    if not r.ok:
        try:
            return {"error": r.json().get("detail", r.text[:200])}
        except Exception:
            return {"error": r.text[:200] or r.reason}
    try:
        return r.json()
    except ValueError:
        return {"error": "non-JSON response"}


def _field_agronomy_for_thaiyme(field_id: int) -> Dict[str, Any]:
    return _crop_monitor_get(f"/api/fields/{field_id}/agronomy")


def _field_zones_for_thaiyme(field_id: int, num_zones: int = 4, index: str = "NDVI") -> Dict[str, Any]:
    idx = (index or "NDVI").strip().upper()
    nz = max(2, min(int(num_zones or 4), 6))
    return _crop_monitor_get(
        f"/api/fields/{field_id}/zones",
        {"index": idx, "num_zones": nz, "grid": 48},
    )


def _field_indices_series_for_thaiyme(field_id: int, index: str = "NDVI", days: int = 180) -> Dict[str, Any]:
    idx = (index or "NDVI").strip().upper()
    d = max(7, min(int(days or 180), 730))
    return _crop_monitor_get(
        f"/api/fields/{field_id}/indices/series",
        {"index": idx, "days": d},
    )


# ── AgriERP tool reads / writes ──────────────────────────────────────

def _farm_ops_snapshot(db: Session, business_id: int) -> Dict[str, Any]:
    """Compact farm-operations snapshot for Thaiyme context."""
    out: Dict[str, Any] = {"business_id": business_id}
    try:
        wo = db.execute(text("""
            SELECT COUNT(*) AS Total,
                   SUM(CASE WHEN Status='open' THEN 1 ELSE 0 END) AS Open,
                   SUM(CASE WHEN Status='in_progress' THEN 1 ELSE 0 END) AS InProgress,
                   SUM(CASE WHEN DueDate < CAST(GETDATE() AS DATE)
                            AND Status NOT IN ('completed','cancelled') THEN 1 ELSE 0 END) AS Overdue
            FROM WorkOrder WHERE BusinessID=:bid
        """), {"bid": business_id}).fetchone()
        out["work_orders"] = {
            "open": int(wo.Open or 0),
            "in_progress": int(wo.InProgress or 0),
            "overdue": int(wo.Overdue or 0),
        }
    except Exception: pass
    try:
        recent_wo = db.execute(text("""
            SELECT TOP 5 WOID, Title, TaskType, Status, AssignedTo, DueDate, Priority
            FROM WorkOrder WHERE BusinessID=:bid
            ORDER BY CreatedAt DESC
        """), {"bid": business_id}).fetchall()
        out["recent_work_orders"] = [dict(r._mapping) for r in recent_wo]
    except Exception: pass
    try:
        low = db.execute(text("""
            SELECT TOP 10 InputID, InputName, Category, Unit, CurrentStock, MinStockAlert, Supplier
            FROM FarmInput
            WHERE BusinessID=:bid AND IsActive=1
              AND MinStockAlert IS NOT NULL AND CurrentStock <= MinStockAlert
            ORDER BY (CurrentStock - MinStockAlert) ASC
        """), {"bid": business_id}).fetchall()
        out["low_stock_inputs"] = [dict(r._mapping) for r in low]
    except Exception: pass
    try:
        pests = db.execute(text("""
            SELECT TOP 5 ObsID, FieldName, CropName, PestName, SeverityLevel,
                         TreatmentRequired, Status, ObservationDate
            FROM FarmPestObservation
            WHERE BusinessID=:bid AND Status NOT IN ('treated','resolved')
            ORDER BY CASE SeverityLevel WHEN 'critical' THEN 1 WHEN 'high' THEN 2 ELSE 3 END
        """), {"bid": business_id}).fetchall()
        out["active_pest_observations"] = [dict(r._mapping) for r in pests]
    except Exception: pass
    return out


def _list_farm_inputs_for_thaiyme(db: Session, business_id: int, category: Optional[str] = None) -> Dict[str, Any]:
    q = """
        SELECT TOP 20 InputID, InputName, Category, Unit, CurrentStock,
                      MinStockAlert, Supplier, StorageLocation, BarcodeID
        FROM FarmInput WHERE BusinessID=:bid AND IsActive=1
    """
    params: Dict[str, Any] = {"bid": business_id}
    if category:
        q += " AND Category=:cat"; params["cat"] = category
    q += " ORDER BY Category, InputName"
    rows = db.execute(text(q), params).fetchall()
    return {"business_id": business_id, "inputs": [dict(r._mapping) for r in rows]}


def _query_farmer_balance(db: Session, business_id: int, farmer_name=None) -> dict:
    q = """
        SELECT f.FarmerName,
               COUNT(d.DeliveryID)           AS DeliveryCount,
               ISNULL(SUM(d.NetPayment), 0)  AS TotalPending,
               ISNULL(SUM(d.GrossPayment),0) AS TotalGross,
               ISNULL(SUM(d.InputDeductions),0) AS TotalDeductions
        FROM (
            SELECT d.DeliveryID, d.FarmerID, d.NetPayment, d.GrossPayment, d.InputDeductions
            FROM OutgrowerDelivery d
            WHERE d.BusinessID=:bid AND d.PaymentStatus='pending'
        ) d
        JOIN OutgrowerFarmer f ON f.FarmerID=d.FarmerID AND f.BusinessID=:bid
    """
    params: dict = {"bid": business_id}
    if farmer_name:
        q += " WHERE f.FullName LIKE :name"; params["name"] = f"%{farmer_name}%"
    q += " GROUP BY f.FarmerName ORDER BY TotalPending DESC"
    try:
        rows = db.execute(text(q), params).fetchall()
        return {
            "farmers": [{"farmer": r.FarmerName, "deliveries": r.DeliveryCount,
                         "pending_payment": float(r.TotalPending),
                         "gross": float(r.TotalGross), "deductions": float(r.TotalDeductions)}
                        for r in rows],
            "total_pending": float(sum(float(r.TotalPending) for r in rows)),
        }
    except Exception as _e:
        return {"error": str(_e)}


def _query_contract_summary(db: Session, business_id: int, crop_name=None) -> dict:
    q = """
        SELECT c.CropName, c.Season, c.Status,
               ISNULL(c.TargetQtyKg, 0) AS TargetQty,
               ISNULL(SUM(d.NetWeightKg), 0) AS DeliveredQty,
               COUNT(DISTINCT c.FarmerID) AS FarmerCount,
               ISNULL(SUM(d.NetPayment), 0) AS TotalPaid,
               SUM(CASE WHEN d.PaymentStatus='pending' THEN d.NetPayment ELSE 0 END) AS PendingPayment
        FROM OutgrowerContract c
        LEFT JOIN OutgrowerDelivery d ON d.ContractID=c.ContractID AND d.BusinessID=c.BusinessID
        WHERE c.BusinessID=:bid
    """
    params: dict = {"bid": business_id}
    if crop_name:
        q += " AND c.CropName LIKE :cn"; params["cn"] = f"%{crop_name}%"
    q += " GROUP BY c.CropName, c.Season, c.Status, c.TargetQtyKg ORDER BY c.CropName"
    try:
        rows = db.execute(text(q), params).fetchall()
        return {"contracts": [{"crop": r.CropName, "season": r.Season, "status": r.Status,
                                "target_kg": float(r.TargetQty), "delivered_kg": float(r.DeliveredQty),
                                "pct_complete": round(float(r.DeliveredQty) / max(float(r.TargetQty), 1) * 100, 1),
                                "farmers": int(r.FarmerCount), "total_paid": float(r.TotalPaid),
                                "pending_payment": float(r.PendingPayment)}
                               for r in rows]}
    except Exception as _e:
        return {"error": str(_e)}


def _query_payroll_summary(db: Session, business_id: int, period_start=None, period_end=None) -> dict:
    from datetime import date as _date, timedelta
    today = _date.today()
    start = period_start or str(today - timedelta(days=14))
    end   = period_end   or str(today)
    try:
        rows = db.execute(text("""
            SELECT e.FirstName + ' ' + e.LastName AS EmployeeName,
                   e.PayType, e.HourlyRate, e.SalaryRate,
                   ISNULL(SUM(a.HoursWorked), 0) AS TotalHours,
                   COUNT(a.AttendanceID) AS AttendanceDays
            FROM HREmployee e
            LEFT JOIN HRAttendance a ON a.EmployeeID=e.EmployeeID AND a.BusinessID=e.BusinessID
                AND a.WorkDate >= :start AND a.WorkDate <= :end
            WHERE e.BusinessID=:bid AND e.IsActive=1
            GROUP BY e.EmployeeID, e.FirstName, e.LastName, e.PayType, e.HourlyRate, e.SalaryRate
            ORDER BY e.LastName, e.FirstName
        """), {"bid": business_id, "start": start, "end": end}).fetchall()
        summary = []
        total_gross = 0.0
        for r in rows:
            hrs = float(r.TotalHours or 0)
            gross = hrs * float(r.HourlyRate or 0) if r.PayType == "hourly" else float(r.SalaryRate or 0)
            net = gross * (1 - 0.2495)
            total_gross += gross
            summary.append({"employee": r.EmployeeName, "pay_type": r.PayType,
                             "total_hours": round(hrs, 2), "attendance_days": int(r.AttendanceDays or 0),
                             "gross_pay": round(gross, 2), "est_net_pay": round(net, 2)})
        return {"period": f"{start} → {end}", "employees": len(summary),
                "total_gross": round(total_gross, 2),
                "est_total_net": round(total_gross * 0.7505, 2), "rows": summary}
    except Exception as _e:
        return {"error": str(_e)}


def _query_export_shipments(db: Session, business_id: int, status: Optional[str] = None) -> dict:
    try:
        where = "WHERE BusinessID=:bid"
        params: dict = {"bid": business_id}
        if status:
            where += " AND Status=:st"
            params["st"] = status
        rows = db.execute(text(f"""
            SELECT TOP 20 ShipmentID, ShipmentRef, Commodity, DestinationCountry,
                   QuantityKg, TotalValueUSD, Status, ShipmentDate, ActualArrivalDate
            FROM ExportShipment {where}
            ORDER BY ShipmentDate DESC
        """), params).fetchall()
        return {"shipments": [
            {"shipment_id": r.ShipmentID, "ref": r.ShipmentRef, "commodity": r.Commodity,
             "destination": r.DestinationCountry, "quantity_kg": float(r.QuantityKg or 0),
             "total_value_usd": float(r.TotalValueUSD or 0), "status": r.Status,
             "shipment_date": str(r.ShipmentDate)[:10] if r.ShipmentDate else None,
             "arrival_date": str(r.ActualArrivalDate)[:10] if r.ActualArrivalDate else None}
            for r in rows
        ], "count": len(rows)}
    except Exception as _e:
        return {"error": str(_e)}


def _query_supplier_scorecard(db: Session, business_id: int, limit: int = 10) -> dict:
    try:
        rows = db.execute(text("""
            SELECT TOP (:lim) po.SupplierName,
                   COUNT(DISTINCT po.POID) AS TotalPOs,
                   ISNULL(SUM(po.TotalAmount), 0) AS TotalSpend,
                   SUM(CASE WHEN r.ReceivedDate IS NOT NULL AND po.ExpectedDelivery IS NOT NULL
                                 AND r.ReceivedDate <= po.ExpectedDelivery THEN 1 ELSE 0 END) AS OnTime,
                   SUM(CASE WHEN r.ReceivedDate IS NOT NULL THEN 1 ELSE 0 END) AS TotalRecv
            FROM PurchaseOrder po
            LEFT JOIN POReceipt r ON r.POID = po.POID
            WHERE po.BusinessID = :bid
            GROUP BY po.SupplierName
            ORDER BY TotalSpend DESC
        """), {"bid": business_id, "lim": limit}).fetchall()
        vendors = []
        for r in rows:
            total_recv = r.TotalRecv or 0
            on_time = r.OnTime or 0
            on_time_pct = round(on_time / total_recv * 100, 1) if total_recv > 0 else None
            vendors.append({
                "supplier": r.SupplierName, "total_pos": r.TotalPOs,
                "total_spend": float(r.TotalSpend or 0),
                "on_time_pct": on_time_pct,
            })
        return {"vendors": vendors, "count": len(vendors)}
    except Exception as _e:
        return {"error": str(_e)}


def _query_contract_dashboard_thaiyme(db: Session, business_id: int) -> dict:
    try:
        rows = db.execute(text("""
            SELECT oc.CropName, of2.FullName AS FarmerName,
                   oc.TargetQtyKg,
                   ISNULL(SUM(od.NetWeightKg), 0) AS DeliveredKg,
                   oc.Status
            FROM OutgrowerContract oc
            JOIN OutgrowerFarmer of2 ON of2.FarmerID = oc.FarmerID
            LEFT JOIN OutgrowerDelivery od ON od.ContractID = oc.ContractID
            WHERE oc.BusinessID = :bid
            GROUP BY oc.ContractID, oc.CropName, of2.FullName, oc.TargetQtyKg, oc.Status
            ORDER BY oc.ContractID DESC
        """), {"bid": business_id}).fetchall()
        contracts = []
        total_target = total_delivered = 0
        for r in rows:
            target = float(r.TargetQtyKg or 0)
            delivered = float(r.DeliveredKg or 0)
            total_target += target
            total_delivered += delivered
            contracts.append({
                "farmer": r.FarmerName, "crop": r.CropName,
                "target_kg": target, "delivered_kg": delivered,
                "utilization_pct": round(delivered / target * 100, 1) if target > 0 else 0,
                "status": r.Status,
            })
        return {
            "contracts": contracts[:15],
            "total_target_kg": total_target,
            "total_delivered_kg": total_delivered,
            "overall_utilization_pct": round(total_delivered / total_target * 100, 1) if total_target > 0 else 0,
        }
    except Exception as _e:
        return {"error": str(_e)}


def _list_pending_po_approvals(db: Session, business_id: int) -> dict:
    try:
        rows = db.execute(text("""
            SELECT POID, PONumber, SupplierName, TotalAmount, OrderDate, Category, Notes
            FROM PurchaseOrder
            WHERE BusinessID=:bid AND Status='pending_approval'
            ORDER BY OrderDate DESC
        """), {"bid": business_id}).fetchall()
        return {"pending_approvals": [
            {"po_id": r.POID, "po_number": r.PONumber, "supplier": r.SupplierName,
             "amount": float(r.TotalAmount or 0), "order_date": str(r.OrderDate),
             "category": r.Category}
            for r in rows
        ], "count": len(rows)}
    except Exception as _e:
        return {"error": str(_e)}


# ── Gemini function-calling tool registry ────────────────────────────
# Each entry: { decl: FunctionDeclaration, run: callable, requires: ('biz'|'event'),
#               mutating: bool }. Mutating tools never execute directly — they
#               return a `proposed_action` payload that the frontend must confirm.

def _build_tool_registry(
    business_id: Optional[int],
    event_id: Optional[int],
    db: Session,
    people_id: Optional[int] = None,
):
    """Construct the tool registry filtered by what's available on this surface."""
    registry: Dict[str, Dict[str, Any]] = {}

    if business_id:
        registry["accounting_snapshot"] = {
            "desc": "High-level snapshot of the books — AR/AP totals, recent invoices, recent expenses, customer/vendor counts, last-30-days revenue and spend.",
            "params": {},
            "run": lambda **_: _accounting_snapshot(db, business_id),
            "mutating": False,
        }
        registry["list_open_invoices"] = {
            "desc": "List up to 25 open (unpaid) invoices, ordered by due date ascending. Use when the user asks about overdue, upcoming, or specific unpaid invoices.",
            "params": {"limit": {"type_": "INTEGER", "description": "Max rows (default 25)."}},
            "run": lambda limit=25, **_: _list_open_invoices(db, business_id, int(limit or 25)),
            "mutating": False,
        }
        registry["find_customer"] = {
            "desc": "Search the business's customer list by name, company, or email substring.",
            "params": {"query": {"type_": "STRING", "description": "Substring to match against customer name/company/email."}},
            "run": lambda query="", **_: _find_customer(db, business_id, str(query or "")),
            "mutating": False,
        }
        registry["recent_payments"] = {
            "desc": "Recent customer payments received within the last N days (default 30).",
            "params": {"days": {"type_": "INTEGER", "description": "Look-back window in days (default 30)."}},
            "run": lambda days=30, **_: _recent_payments(db, business_id, int(days or 30)),
            "mutating": False,
        }

        # ESG / sustainability snapshot — Food Aggregator businesses use this
        # for audit prep, regulatory filings (EU CSRD, EthiFinance), and to
        # justify premium pricing to consumers.
        registry["esg_status"] = {
            "desc": "ESG (Environmental, Social, Governance) snapshot for the business — sourcing transparency (% certified farms), residue-test pass rate, cold-chain integrity (% of dispatches with no breach), inputs to farms, IoT sensor data, plus the most recent saved audit report and any manual metrics. Use for 'how are we doing on EU compliance', 'are we audit-ready', 'what's our sustainability story', 'cold chain breaches this quarter', 'is our EthiFinance rating defensible'.",
            "params": {},
            "run": lambda **_: _esg_status(db, business_id),
            "mutating": False,
        }

        registry["order_analytics"] = {
            "desc": "Aggregate order analytics — standing (recurring) orders count and status breakdown by buyer, top active products, and B2B aggregator activity (last 90 days): order count, total revenue, average order value, unique accounts, fulfillment rate. Use for 'how are our orders doing', 'which products sell most', 'what\\'s our B2B revenue', 'how many active buyers do we have'.",
            "params": {},
            "run": lambda **_: _order_analytics(db, business_id),
            "mutating": False,
        }

        # ── AgriERP tools ────────────────────────────────────────────
        registry["farm_ops_snapshot"] = {
            "desc": "Farm operations snapshot — open/overdue work orders, recent work orders, low-stock inputs, and active pest observations needing treatment. Use when asked about field operations status, what's urgent on the farm, what work orders are open, or what's running low.",
            "params": {},
            "run": lambda **_: _farm_ops_snapshot(db, business_id),
            "mutating": False,
        }
        registry["list_farm_inputs"] = {
            "desc": "List farm inputs (seeds, chemicals, fertilizers, equipment consumables) with current stock levels. Optional category filter: seed, fertilizer, chemical, fuel, equipment, livestock_supply, packaging, other.",
            "params": {"category": {"type_": "STRING", "description": "Optional category filter (seed, fertilizer, chemical, fuel, equipment, livestock_supply, packaging, other)."}},
            "run": lambda category=None, **_: _list_farm_inputs_for_thaiyme(db, business_id, category),
            "mutating": False,
        }
        registry["propose_create_work_order"] = {
            "desc": "Propose creating a new work order for a field task. Returns a confirmation card — the user must approve before it's created. Use when asked to 'create a work order', 'schedule a task', 'assign field work', etc.",
            "params": {
                "title":       {"type_": "STRING",  "description": "Short title for the work order (required)."},
                "task_type":   {"type_": "STRING",  "description": "Task type: planting, spraying, irrigation, harvesting, maintenance, scouting, transplanting, other."},
                "assigned_to": {"type_": "STRING",  "description": "Name of the person assigned."},
                "due_date":    {"type_": "STRING",  "description": "Due date in YYYY-MM-DD format."},
                "priority":    {"type_": "STRING",  "description": "Priority: low, normal, high, urgent."},
                "description": {"type_": "STRING",  "description": "Optional detailed description."},
                "location":    {"type_": "STRING",  "description": "Field name or location."},
            },
            "run": None,
            "mutating": True,
        }
        registry["propose_log_input_usage"] = {
            "desc": "Propose recording a farm input usage (consumption) transaction — e.g. 'we used 50kg of Roundup on field 3'. Returns a confirmation card. Use when the user says they applied, used, or consumed an input.",
            "params": {
                "input_id":   {"type_": "INTEGER", "description": "InputID of the farm input being consumed (get from list_farm_inputs if unsure)."},
                "quantity":   {"type_": "NUMBER",  "description": "Amount consumed (in the input's unit)."},
                "field_name": {"type_": "STRING",  "description": "Name of the field where it was applied."},
                "crop_name":  {"type_": "STRING",  "description": "Crop name (optional)."},
                "notes":      {"type_": "STRING",  "description": "Optional notes."},
            },
            "run": None,
            "mutating": True,
        }
        registry["propose_log_attendance"] = {
            "desc": "Propose logging employee attendance / hours worked for a day. Returns a confirmation card. Use when the user says 'log hours for', 'record attendance', 'mark X worked today', etc.",
            "params": {
                "worker_name":   {"type_": "STRING",  "description": "Employee full name."},
                "work_date":     {"type_": "STRING",  "description": "Work date in YYYY-MM-DD format."},
                "hours_worked":  {"type_": "NUMBER",  "description": "Hours worked (decimal, e.g. 7.5)."},
                "task_type":     {"type_": "STRING",  "description": "Task category: field_work, packhouse, maintenance, admin, transport, other."},
                "notes":         {"type_": "STRING",  "description": "Optional notes."},
            },
            "run": None,
            "mutating": True,
        }

        # ── Outgrower tools ──────────────────────────────────────────────────
        registry["query_farmer_balance"] = {
            "desc": "Show pending payment balances for outgrower farmers — total pending NetPayment across all deliveries not yet paid. Optionally filter by farmer name. Use when asked 'how much do we owe farmers', 'farmer payment summary', 'outgrower balances'.",
            "params": {"farmer_name": {"type_": "STRING", "description": "Optional: filter by farmer name (partial match)."}},
            "run": lambda farmer_name=None, **_: _query_farmer_balance(db, business_id, farmer_name),
            "mutating": False,
        }
        registry["query_contract_summary"] = {
            "desc": "Show outgrower contract progress — target vs delivered quantity, payment status, and active farmer count. Use for 'outgrower progress', 'how much crop has been delivered', 'contract status'.",
            "params": {"crop_name": {"type_": "STRING", "description": "Optional: filter by crop name."}},
            "run": lambda crop_name=None, **_: _query_contract_summary(db, business_id, crop_name),
            "mutating": False,
        }
        registry["propose_delivery_settlement"] = {
            "desc": "Propose marking an outgrower delivery as paid and posting the settlement to accounting. Returns a confirmation card — user must approve. Use when asked to 'pay farmer', 'settle delivery', 'mark delivery #X as paid'.",
            "params": {
                "delivery_id":   {"type_": "INTEGER", "description": "DeliveryID of the delivery to settle."},
                "payment_date":  {"type_": "STRING",  "description": "Payment date in YYYY-MM-DD format (defaults to today)."},
            },
            "run": None,
            "mutating": True,
        }

        # ── Payroll tools ────────────────────────────────────────────────────
        registry["query_payroll_summary"] = {
            "desc": "Show estimated payroll for a date range based on attendance records — gross pay, net pay, and per-employee breakdown. Use when asked 'what's the payroll cost this period', 'how much do we owe in wages', 'payroll estimate for week of...'.",
            "params": {
                "period_start": {"type_": "STRING", "description": "Start date YYYY-MM-DD."},
                "period_end":   {"type_": "STRING", "description": "End date YYYY-MM-DD."},
            },
            "run": lambda period_start=None, period_end=None, **_: _query_payroll_summary(db, business_id, period_start, period_end),
            "mutating": False,
        }

        # ── Procurement approval tools ────────────────────────────────────────
        registry["list_pending_po_approvals"] = {
            "desc": "List purchase orders currently awaiting manager approval. Shows PO number, supplier, amount, and date. Use when asked 'any POs to approve', 'pending purchase orders', 'what needs approval'.",
            "params": {},
            "run": lambda **_: _list_pending_po_approvals(db, business_id),
            "mutating": False,
        }
        registry["propose_approve_po"] = {
            "desc": "Propose approving a pending purchase order and posting it as an accounting bill. Returns a confirmation card. Use when the user says 'approve PO #X', 'sign off on purchase order'.",
            "params": {
                "po_id":       {"type_": "INTEGER", "description": "POID of the purchase order to approve."},
                "approved_by": {"type_": "STRING",  "description": "Name of the approver."},
            },
            "run": None,
            "mutating": True,
        }
        registry["propose_reject_po"] = {
            "desc": "Propose rejecting a pending purchase order with a reason. Returns a confirmation card. Use when the user says 'reject PO #X', 'decline this PO'.",
            "params": {
                "po_id":  {"type_": "INTEGER", "description": "POID of the purchase order to reject."},
                "reason": {"type_": "STRING",  "description": "Reason for rejection."},
            },
            "run": None,
            "mutating": True,
        }

        # Lead-retrieval tools (exhibitor side) — scoped to the focused business
        registry["my_event_leads_summary"] = {
            "desc": "Summary of my exhibitor lead-capture scans at a specific event — total scans, breakdown by follow-up status (new/contacted/qualified/won/lost) and by 1-5 star rating. Use for 'how many leads did I get at event X', 'what's my lead pipeline'.",
            "params": {"event_id": {"type_": "INTEGER", "description": "Event ID."}},
            "run": lambda event_id=None, **_: (
                _leads_summary(db, int(event_id), business_id) if event_id
                else {"error": "event_id required"}
            ),
            "mutating": False,
        }
        registry["my_event_leads_list"] = {
            "desc": "List my exhibitor lead scans from an event with masked attendee contact info. Optional status (new/contacted/qualified/won/lost) and rating_min (1-5) filters. Use for 'show me my hot leads', 'qualified leads from event X'.",
            "params": {
                "event_id":   {"type_": "INTEGER", "description": "Event ID."},
                "status":     {"type_": "STRING",  "description": "Optional follow-up status filter."},
                "rating_min": {"type_": "INTEGER", "description": "Optional 1-5 minimum-stars filter."},
            },
            "run": lambda event_id=None, status=None, rating_min=None, **_: (
                _list_leads(db, int(event_id), business_id, status, rating_min) if event_id
                else {"error": "event_id required"}
            ),
            "mutating": False,
        }

    if event_id:
        # Sponsorship reads only become available when an event is in scope
        registry["sponsorship_summary"] = {
            "desc": "Sponsorship revenue + per-tier breakdown for the current event (total revenue collected, confirmed sponsor count, slots taken vs max per tier). Use for 'how are sponsorship tiers selling', 'how much in sponsorship revenue', 'is the Gold tier full'.",
            "params": {},
            "run": lambda **_: _sponsorship_summary(db, event_id),
            "mutating": False,
        }
        registry["list_sponsors"] = {
            "desc": "List sponsors for the current event with tier, paid status, and (redacted) contact info. Optional status filter (pending/confirmed/declined).",
            "params": {"status": {"type_": "STRING", "description": "Optional status filter."}},
            "run": lambda status=None, **_: _list_sponsors(db, event_id, status),
            "mutating": False,
        }
        registry["floor_plan_summary"] = {
            "desc": "Floor plan booth-sales status for the current event: total booths, available count, breakdown by status (available/reserved/sold/blocked) and by tier. Use for 'how many booths sold', 'is the floor plan filling up'.",
            "params": {},
            "run": lambda **_: _floor_plan_summary(db, event_id),
            "mutating": False,
        }
        registry["booth_services_revenue"] = {
            "desc": "Booth services revenue for the current event from à la carte add-ons (electrical/water/internet/AV/etc), with per-service units sold + dollars. Use for 'how much in services revenue', 'what add-ons are selling'.",
            "params": {},
            "run": lambda **_: _booth_services_revenue(db, event_id),
            "mutating": False,
        }
        registry["coi_summary"] = {
            "desc": "Certificate of Insurance status counts (pending/approved/rejected/expired) for the current event + count expiring within 30 days. Use for 'any COIs to review', 'are sponsors compliant', 'any insurance expiring'.",
            "params": {},
            "run": lambda **_: _coi_summary(db, event_id),
            "mutating": False,
        }

    # Precision-ag tools — available to every authenticated user (data is
    # filtered server-side per FieldID → BusinessAccess on call).
    if people_id:
        registry["list_my_fields"] = {
            "desc": "List the user's satellite-monitored fields (field_id, name, crop, size, planting date). Call this first when the user mentions their fields without naming a specific field_id.",
            "params": {},
            "run": lambda **_: _list_my_fields(db, people_id),
            "mutating": False,
        }

    def _agronomy_with_check(field_id: int):
        if not field_id:
            return {"error": "field_id required"}
        _check_field_access(db, people_id, int(field_id))
        return _field_agronomy_for_thaiyme(int(field_id))

    def _zones_with_check(field_id: int, num_zones: int = 4, index: str = "NDVI"):
        if not field_id:
            return {"error": "field_id required"}
        _check_field_access(db, people_id, int(field_id))
        return _field_zones_for_thaiyme(int(field_id), int(num_zones or 4), str(index or "NDVI"))

    def _series_with_check(field_id: int, index: str = "NDVI", days: int = 180):
        if not field_id:
            return {"error": "field_id required"}
        _check_field_access(db, people_id, int(field_id))
        return _field_indices_series_for_thaiyme(int(field_id), str(index or "NDVI"), int(days or 180))

    if people_id:
        registry["field_agronomy_snapshot"] = {
            "desc": "Full agronomy snapshot for a field — current weather, 7-day forecast, GDD, growth stage, latest vegetation indices, irrigation signal, per-product spray decision (herbicide/fungicide/insecticide), and crop-specific named pest/disease alerts (e.g. Gray Leaf Spot, Fusarium Head Blight). Call when asked about a field's status, 'should I spray', or 'any disease pressure'.",
            "params": {"field_id": {"type_": "INTEGER", "description": "The Field ID."}},
            "run": lambda field_id=None, **_: _agronomy_with_check(field_id),
            "mutating": False,
        }
        registry["field_stress_zones"] = {
            "desc": "K-means stress zones for a field — clusters the latest vegetation-index raster into N management zones (default 4) sorted lowest=stress to highest=best. Use for 'where are the stressed parts' or 'should I do variable-rate'.",
            "params": {
                "field_id":  {"type_": "INTEGER", "description": "The Field ID."},
                "num_zones": {"type_": "INTEGER", "description": "Number of zones (2-6, default 4)."},
                "index":     {"type_": "STRING",  "description": "NDVI (default), NDRE, EVI, GNDVI, or NDWI."},
            },
            "run": lambda field_id=None, num_zones=4, index="NDVI", **_: _zones_with_check(field_id, num_zones, index),
            "mutating": False,
        }
        registry["field_indices_series"] = {
            "desc": "Time-series of a vegetation index (NDVI default) for a field over the last N days (default 180), with linear-trend summary (rising/flat/falling). Use for 'NDVI trend' or 'how has the field changed since planting'.",
            "params": {
                "field_id": {"type_": "INTEGER", "description": "The Field ID."},
                "index":    {"type_": "STRING",  "description": "NDVI (default), NDRE, EVI, GNDVI, NDWI."},
                "days":     {"type_": "INTEGER", "description": "Look-back window in days (7-730, default 180)."},
            },
            "run": lambda field_id=None, index="NDVI", days=180, **_: _series_with_check(field_id, index, days),
            "mutating": False,
        }

    if event_id:
        registry["event_registrations"] = {
            "desc": "List up to 50 registrations for the current event with payment status and (redacted) attendee contact.",
            "params": {},
            "run": lambda **_: _event_registrations(db, event_id),
            "mutating": False,
        }
        registry["propose_update_registration"] = {
            "desc": "Propose a change to a single registration (PaymentStatus / contact info / notes). Returns a confirmation request — the user must click YES in the UI before it runs.",
            "params": {
                "reg_id":            {"type_": "INTEGER", "description": "RegID of the registration to update."},
                "PaymentStatus":     {"type_": "STRING",  "description": "New payment status: 'paid', 'pending', 'refunded'."},
                "AttendeeFirstName": {"type_": "STRING",  "description": "Updated attendee first name."},
                "AttendeeLastName":  {"type_": "STRING",  "description": "Updated attendee last name."},
                "AttendeeEmail":     {"type_": "STRING",  "description": "Updated attendee email."},
                "AttendeePhone":     {"type_": "STRING",  "description": "Updated attendee phone."},
                "Notes":             {"type_": "STRING",  "description": "Updated organizer notes."},
            },
            "run": None,  # mutating — see _make_proposal()
            "mutating": True,
        }
        registry["propose_cancel_registration"] = {
            "desc": "Propose cancelling/deleting a registration. Returns a confirmation request — the user must click YES in the UI before it runs.",
            "params": {
                "reg_id": {"type_": "INTEGER", "description": "RegID of the registration to cancel."},
            },
            "run": None,
            "mutating": True,
        }

        # ── Export shipment tools ────────────────────────────────────────────
        registry["query_export_shipments"] = {
            "desc": "List recent export shipments with status, commodity, destination, quantity, and value. Optional status filter (customs_pending/shipped/delivered/recalled). Use when asked 'what's the status of our exports', 'pending shipments', 'what was delivered last month'.",
            "params": {"status": {"type_": "STRING", "description": "Optional status filter: customs_pending, shipped, delivered, recalled."}},
            "run": lambda status=None, **_: _query_export_shipments(db, business_id, status),
            "mutating": False,
        }
        registry["propose_mark_shipment_delivered"] = {
            "desc": "Propose marking an export shipment as delivered with an actual arrival date. This triggers revenue recognition in accounting. Returns a confirmation card — user must approve. Use when asked to 'mark shipment X as arrived', 'confirm delivery of shipment #Y'.",
            "params": {
                "shipment_id":         {"type_": "INTEGER", "description": "ShipmentID to mark as delivered."},
                "actual_arrival_date": {"type_": "STRING",  "description": "Actual arrival date in YYYY-MM-DD format (defaults to today)."},
            },
            "run": None,
            "mutating": True,
        }

        # ── Supplier scorecard tools ─────────────────────────────────────────
        registry["query_supplier_scorecard"] = {
            "desc": "Show vendor performance scorecard — on-time delivery rate and total spend per supplier. Use when asked 'how are our suppliers performing', 'which vendor has the best on-time rate', 'supplier scorecard'.",
            "params": {"limit": {"type_": "INTEGER", "description": "Max vendors to return (default 10)."}},
            "run": lambda limit=10, **_: _query_supplier_scorecard(db, business_id, int(limit or 10)),
            "mutating": False,
        }

        # ── Contract farming dashboard tools ─────────────────────────────────
        registry["query_contract_dashboard"] = {
            "desc": "Show outgrower contract dashboard — per-contract target vs delivered quantity and utilization %, plus overall totals. Use when asked 'contract utilization', 'how much crop has been delivered against contracts', 'outgrower dashboard'.",
            "params": {},
            "run": lambda **_: _query_contract_dashboard_thaiyme(db, business_id),
            "mutating": False,
        }

    return registry


def _make_proposal(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a mutating tool call into a frontend-confirmable proposal."""
    if tool_name == "propose_update_registration":
        rid = args.get("reg_id")
        patch = {k: v for k, v in args.items() if k != "reg_id" and v is not None}
        return {
            "kind": "update_registration",
            "endpoint": f"/api/thaiyme/registrations/{rid}",
            "method": "PUT",
            "body": patch,
            "summary": f"Update registration #{rid}: " + ", ".join(f"{k}={v}" for k, v in patch.items()),
        }
    if tool_name == "propose_cancel_registration":
        rid = args.get("reg_id")
        return {
            "kind": "cancel_registration",
            "endpoint": f"/api/thaiyme/registrations/{rid}",
            "method": "DELETE",
            "body": {},
            "summary": f"Cancel and delete registration #{rid}.",
        }
    if tool_name == "propose_create_work_order":
        return {
            "kind": "create_work_order",
            "endpoint": "/api/thaiyme/agri/work-order",
            "method": "POST",
            "body": {k: v for k, v in args.items() if v is not None},
            "summary": f"Create work order: \"{args.get('title', '(untitled)')}\" — {args.get('task_type','task')}, assigned to {args.get('assigned_to','(unassigned)')}, due {args.get('due_date','TBD')}.",
        }
    if tool_name == "propose_log_input_usage":
        return {
            "kind": "log_input_usage",
            "endpoint": "/api/thaiyme/agri/input-usage",
            "method": "POST",
            "body": {k: v for k, v in args.items() if v is not None},
            "summary": f"Log usage: {args.get('quantity')} units of input #{args.get('input_id')} on {args.get('field_name','field')}.",
        }
    if tool_name == "propose_log_attendance":
        return {
            "kind": "log_attendance",
            "endpoint": "/api/thaiyme/agri/attendance",
            "method": "POST",
            "body": {k: v for k, v in args.items() if v is not None},
            "summary": f"Log attendance: {args.get('worker_name')} — {args.get('hours_worked')}h on {args.get('work_date')}.",
        }
    if tool_name == "propose_delivery_settlement":
        did = args.get("delivery_id")
        pdate = args.get("payment_date") or str(__import__("datetime").date.today())
        return {
            "kind": "delivery_settlement",
            "endpoint": f"/api/thaiyme/agri/outgrower/settle/{did}",
            "method": "POST",
            "body": {"delivery_id": did, "payment_date": pdate},
            "summary": f"Mark outgrower delivery #{did} as paid on {pdate} and post accounting bill.",
        }
    if tool_name == "propose_approve_po":
        po_id = args.get("po_id")
        return {
            "kind": "approve_po",
            "endpoint": f"/api/thaiyme/procurement/approve/{po_id}",
            "method": "POST",
            "body": {"po_id": po_id, "approved_by": args.get("approved_by", "Thaiyme-assisted approval")},
            "summary": f"Approve PO #{po_id} and post accounting bill to vendor.",
        }
    if tool_name == "propose_reject_po":
        po_id = args.get("po_id")
        return {
            "kind": "reject_po",
            "endpoint": f"/api/thaiyme/procurement/reject/{po_id}",
            "method": "POST",
            "body": {"po_id": po_id, "reason": args.get("reason", "")},
            "summary": f"Reject PO #{po_id}. Reason: {args.get('reason','')}",
        }
    if tool_name == "propose_mark_shipment_delivered":
        sid = args.get("shipment_id")
        arrival = args.get("actual_arrival_date") or str(__import__("datetime").date.today())
        return {
            "kind": "mark_shipment_delivered",
            "endpoint": f"/api/export-compliance/shipments/{sid}/status",
            "method": "PUT",
            "body": {"status": "delivered", "actual_arrival_date": arrival},
            "summary": f"Mark export shipment #{sid} as delivered on {arrival}. This will trigger revenue recognition in accounting.",
        }
    return {"kind": "unknown", "summary": f"Proposal for {tool_name}"}


# ── System prompt ────────────────────────────────────────────────────

def _system_prompt(
    rag: str,
    page_context: str,
    tool_names: List[str],
    onboarding_context: str = "",
) -> str:
    tool_help = ", ".join(tool_names) if tool_names else "(no tools available on this surface)"
    onboarding_block = (
        f"\nONBOARDING PROFILE (captured when this operator set up their account — "
        f"treat these facts as already established; do not ask them to re-explain "
        f"their crops, fields, channels, or operational challenge):\n{onboarding_context}\n"
    ) if onboarding_context else ""
    return f"""You are {AGENT_NAME}, a calm, expert business operations advisor for the OatmealFarmNetwork directory. You help operators of any business type — farms, ranches, restaurants, fiber producers, services, event hosts — run their business well.

Tone: warm, concise, and practical. Speak in plain English. Lead with the answer, then back it up with one or two specifics. Never speculate about numbers — call a tool first.
{onboarding_block}
Tool-use rules:
- Available tools this turn: {tool_help}.
- When the user asks anything quantitative or specific to their books / event registrations, CALL THE RELEVANT TOOL FIRST instead of guessing. Then summarize the result in one short paragraph.
- Tools return data that has already been redacted server-side. Sensitive data (account numbers, full card numbers, SSNs, routing numbers, customer email/phone beyond a masked form) is hidden from you. Never ask the user to paste an unmasked version of any of those.
- For destructive event-registration changes (cancel, mark paid, edit attendee), call `propose_update_registration` or `propose_cancel_registration`. These do NOT execute — they show a confirmation card in the UI for the user to approve. After calling one, briefly tell the user what you proposed and ask them to confirm.
- If TOOL RESULTS are missing fields the user is asking about, say so plainly — don't invent numbers.

CURRENT PAGE: {page_context or 'unknown'}

KNOWLEDGE BASE (best-practice references for running directory businesses):
{rag or '(no relevant entries)'}
"""


# ── Gemini function-calling ──────────────────────────────────────────

def _proto_to_py(v: Any) -> Any:
    """Best-effort conversion of proto Struct/Value/MapComposite into plain Python."""
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "items"):
        try:
            return {k: _proto_to_py(val) for k, val in v.items()}
        except Exception:
            pass
    if hasattr(v, "__iter__") and not isinstance(v, (str, bytes, dict)):
        try:
            return [_proto_to_py(x) for x in v]
        except Exception:
            pass
    return v


_JSON_TYPE = {"STRING": "string", "OBJECT": "object", "INTEGER": "integer",
              "NUMBER": "number", "BOOLEAN": "boolean", "ARRAY": "array"}


def _build_gemini_tools(registry: Dict[str, Dict[str, Any]]):
    """Convert internal registry into Gemini tools for the active backend."""
    import ai_vertex as av
    specs = []
    for name, entry in registry.items():
        params_def = entry.get("params") or {}
        properties = {}
        for pname, pdef in params_def.items():
            ptype = (pdef.get("type_") or pdef.get("type") or "STRING").upper()
            properties[pname] = {
                "type": _JSON_TYPE.get(ptype, "string"),
                "description": pdef.get("description", ""),
            }
        spec: Dict[str, Any] = {"name": name, "description": entry["desc"]}
        if properties:
            spec["parameters"] = {"type": "object", "properties": properties}
        specs.append(spec)
    return av.make_tools(specs)


def _call_gemini_with_tools(
    system: str,
    history: List[Dict[str, str]],
    user_msg: str,
    registry: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Run a Gemini turn that may invoke tools from `registry`.
    Returns: {"content": str, "proposals": [...], "tools_called": [...], "error": Optional[str]}
    """
    out_proposals: List[Dict[str, Any]] = []
    tools_called: List[str] = []
    try:
        import ai_vertex as av
        tools = _build_gemini_tools(registry)
        model = av.make_model(
            "gemini-2.5-flash",
            system_instruction=system,
            generation_config={"temperature": 0.4, "max_output_tokens": 4096},
            tools=tools,
        )

        turns = []
        for m in history:
            role = "model" if m.get("role") == "assistant" else "user"
            turns.append((role, m.get("content", "")))
        chat = model.start_chat(history=av.make_history(turns))

        resp = av.send_message(chat, user_msg)
        text_chunks: List[str] = []
        max_loops = 4

        for _ in range(max_loops):
            function_calls: List[tuple] = []
            for cand in (getattr(resp, "candidates", None) or []):
                content = getattr(cand, "content", None)
                for p in (getattr(content, "parts", None) or []):
                    fc = getattr(p, "function_call", None)
                    if fc and getattr(fc, "name", ""):
                        args = _proto_to_py(getattr(fc, "args", {})) or {}
                        function_calls.append((fc.name, args if isinstance(args, dict) else {}))
                    t = getattr(p, "text", None)
                    if t:
                        text_chunks.append(t)

            if not function_calls:
                break

            response_parts = []
            for name, args in function_calls:
                tools_called.append(name)
                entry = registry.get(name)
                if not entry:
                    payload = {"error": f"Unknown tool {name}"}
                elif entry.get("mutating"):
                    proposal = _make_proposal(name, args)
                    out_proposals.append(proposal)
                    payload = {"status": "awaiting_user_confirmation",
                               "summary": proposal.get("summary"),
                               "kind": proposal.get("kind")}
                else:
                    try:
                        payload = entry["run"](**(args or {}))
                    except TypeError:
                        # Be forgiving on extra/missing args
                        try:
                            payload = entry["run"]()
                        except Exception as ex:
                            payload = {"error": str(ex)}
                    except Exception as ex:
                        payload = {"error": str(ex)}
                response_parts.append(av.function_response_part(name, payload))

            resp = av.send_message(chat, response_parts)

        final_text = ("\n".join(text_chunks)).strip()
        if not final_text:
            try:
                final_text = (resp.text or "").strip()
            except Exception:
                pass
        if not final_text:
            final_text = "I'm not sure how to answer that — could you give me a bit more detail?"
        return {"content": final_text, "proposals": out_proposals, "tools_called": tools_called}
    except Exception as e:
        logger.error("[Thaiyme] Gemini error: %s", e, exc_info=True)
        return {"content": f"Thaiyme had a problem reaching the model: {e}",
                "proposals": [], "tools_called": tools_called, "error": str(e)}


# ── Routes ───────────────────────────────────────────────────────────

@router.post("/chat")
def chat(
    body: ChatRequest,
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not body.messages:
        raise HTTPException(400, "messages is required.")
    user_msg = (body.messages[-1].content or "").strip()
    if not user_msg:
        raise HTTPException(400, "Last message is empty.")
    if len(user_msg) > MAX_MESSAGE_CHARS:
        raise HTTPException(413, f"Message too long (max {MAX_MESSAGE_CHARS} chars).")

    # Access checks scoped to the surface that mounted Thaiyme
    biz_access_level = 0
    event_access_level = 0
    if body.business_id:
        biz_access_level = _check_business_access(
            db, current_user.PeopleID, body.business_id, min_level=1
        )
    if body.event_id:
        event_access_level = _check_event_access(
            db, current_user.PeopleID, body.event_id, min_level=1
        )

    # RAG
    rag = _rag_search(user_msg)

    # Onboarding context from Cassia post-checkout discovery (business-scoped only)
    onboarding_ctx = _get_onboarding_context(body.business_id) if body.business_id else ""

    # Tool registry — let Gemini decide what to call
    registry = _build_tool_registry(body.business_id, body.event_id, db, current_user.PeopleID)

    # If user lacks AccessLevelID >= 2 on the host, strip the mutating tools
    if body.event_id and event_access_level < 2:
        registry = {k: v for k, v in registry.items() if not v.get("mutating")}

    # Memory scope
    scope = (
        f"event:{body.event_id}" if body.event_id
        else (f"biz:{body.business_id}" if body.business_id else "global")
    )
    history = _load_recent_messages(current_user.PeopleID, scope)

    system = _system_prompt(rag, body.page or "", list(registry.keys()), onboarding_ctx)
    result = _call_gemini_with_tools(system, history, user_msg, registry)
    reply = result["content"]

    # Persist after the call so a Gemini failure doesn't poison the thread.
    _save_message(current_user.PeopleID, scope, "user", user_msg)
    _save_message(current_user.PeopleID, scope, "assistant", reply)

    return {
        "content": reply,
        "proposals": result.get("proposals", []),
        "tools_called": result.get("tools_called", []),
        "rag_hit": bool(rag),
    }


# ── Confirm a proposed mutation (frontend → backend) ─────────────────

class ProposalConfirm(BaseModel):
    kind: str
    endpoint: str
    method: str
    body: Dict[str, Any] = {}


@router.post("/confirm")
def confirm_proposal(
    proposal: ProposalConfirm,
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Execute a previously-proposed mutation. Re-runs all access checks."""
    method = (proposal.method or "").upper()
    ep = proposal.endpoint or ""

    # Pattern: /api/thaiyme/registrations/{reg_id}
    m = re.match(r"^/api/thaiyme/registrations/(\d+)/?$", ep)
    if m:
        reg_id = int(m.group(1))
        row = db.execute(
            text("SELECT EventID FROM OFNEventRegistrations WHERE RegID = :rid"),
            {"rid": reg_id},
        ).fetchone()
        if not row:
            raise HTTPException(404, "Registration not found.")
        _check_event_access(db, current_user.PeopleID, int(row.EventID), min_level=2)
        if method == "PUT":
            patch = {k: v for k, v in (proposal.body or {}).items() if v is not None}
            if not patch:
                raise HTTPException(400, "No fields to update.")
            return {"ok": True, "executed": _update_registration(db, reg_id, patch)}
        if method == "DELETE":
            return {"ok": True, "executed": _cancel_registration(db, reg_id)}
        raise HTTPException(400, f"Unsupported method {method} for registrations.")

    # ── AgriERP: create work order ────────────────────────────────────
    if ep == "/api/thaiyme/agri/work-order" and method == "POST":
        b = proposal.body
        business_id = b.get("business_id") or b.get("BusinessID")
        if not business_id:
            raise HTTPException(400, "business_id required in proposal body")
        _check_business_access(db, current_user.PeopleID, int(business_id), min_level=2)
        r = db.execute(text("""
            INSERT INTO WorkOrder (BusinessID,TaskType,Title,Description,Priority,
                Status,AssignedTo,DueDate,Location)
            OUTPUT INSERTED.WOID
            VALUES (:bid,:tt,:title,:desc,:pri,'open',:at,:dd,:loc)
        """), {
            "bid":   int(business_id),
            "tt":    b.get("task_type", "other"),
            "title": b.get("title", "Untitled"),
            "desc":  b.get("description"),
            "pri":   b.get("priority", "normal"),
            "at":    b.get("assigned_to"),
            "dd":    b.get("due_date"),
            "loc":   b.get("location"),
        }).fetchone()
        db.commit()
        return {"ok": True, "executed": {"WOID": r[0], "title": b.get("title")}}

    # ── AgriERP: log farm input usage ─────────────────────────────────
    if ep == "/api/thaiyme/agri/input-usage" and method == "POST":
        b = proposal.body
        business_id = b.get("business_id") or b.get("BusinessID")
        if not business_id:
            raise HTTPException(400, "business_id required in proposal body")
        _check_business_access(db, current_user.PeopleID, int(business_id), min_level=2)
        # Delegate to farm_inputs record_transaction logic via direct SQL
        inp = db.execute(text(
            "SELECT CurrentStock, CostPerUnit, MinStockAlert, InputName, Unit FROM FarmInput "
            "WHERE InputID=:iid AND BusinessID=:bid"
        ), {"iid": b.get("input_id"), "bid": int(business_id)}).fetchone()
        if not inp:
            raise HTTPException(404, "Input not found")
        qty = float(b.get("quantity", 0))
        new_stock = max(0.0, float(inp.CurrentStock) - qty)
        db.execute(text("UPDATE FarmInput SET CurrentStock=:s, UpdatedAt=GETDATE() WHERE InputID=:iid AND BusinessID=:bid"),
                   {"s": new_stock, "iid": b.get("input_id"), "bid": int(business_id)})
        db.execute(text("""
            INSERT INTO FarmInputTransaction (InputID,BusinessID,TxType,Quantity,CropName,FieldID,Notes)
            VALUES (:iid,:bid,'use',:qty,:crop,NULL,:notes)
        """), {"iid": b.get("input_id"), "bid": int(business_id), "qty": qty,
               "crop": b.get("crop_name"), "notes": b.get("notes") or f"Logged via Thaiyme on {b.get('field_name','field')}"})
        db.commit()
        return {"ok": True, "executed": {"new_stock": new_stock, "input_id": b.get("input_id")}}

    # ── AgriERP: log attendance ───────────────────────────────────────
    if ep == "/api/thaiyme/agri/attendance" and method == "POST":
        b = proposal.body
        business_id = b.get("business_id") or b.get("BusinessID")
        if not business_id:
            raise HTTPException(400, "business_id required in proposal body")
        _check_business_access(db, current_user.PeopleID, int(business_id), min_level=2)
        db.execute(text("""
            INSERT INTO HRAttendance (BusinessID,WorkerName,WorkDate,HoursWorked,TaskType,Notes,Status)
            VALUES (:bid,:name,:dt,:hrs,:tt,:notes,'present')
        """), {
            "bid":   int(business_id),
            "name":  b.get("worker_name"),
            "dt":    b.get("work_date"),
            "hrs":   float(b.get("hours_worked", 0)),
            "tt":    b.get("task_type", "field_work"),
            "notes": b.get("notes"),
        })
        db.commit()
        return {"ok": True, "executed": {"worker": b.get("worker_name"), "date": b.get("work_date")}}

    # ── Outgrower delivery settlement ────────────────────────────────────
    if ep.startswith("/api/thaiyme/agri/outgrower/settle/") and method == "POST":
        _check_business_access(db, current_user.PeopleID, int(b.get("business_id", business_id or 0)), min_level=2)
        delivery_id = int(ep.split("/")[-1])
        bid = int(b.get("business_id", business_id or 0))
        db.execute(text("""
            UPDATE OutgrowerDelivery SET PaymentStatus='paid', PaymentDate=:dt
            WHERE DeliveryID=:did AND BusinessID=:bid
        """), {"dt": b.get("payment_date"), "did": delivery_id, "bid": bid})
        db.commit()
        # Post accounting bill
        from routers.outgrower import _auto_settle_to_accounting
        _auto_settle_to_accounting(db, delivery_id, bid)
        db.commit()
        return {"ok": True, "executed": {"delivery_id": delivery_id, "payment_date": b.get("payment_date")}}

    # ── Procurement PO approval ──────────────────────────────────────────
    if ep.startswith("/api/thaiyme/procurement/approve/") and method == "POST":
        _check_business_access(db, current_user.PeopleID, int(b.get("business_id", business_id or 0)), min_level=2)
        po_id = int(ep.split("/")[-1])
        bid = int(b.get("business_id", business_id or 0))
        db.execute(text("""
            UPDATE PurchaseOrder SET Status='approved', ApprovedBy=:by, ApprovedAt=GETDATE(), UpdatedAt=GETDATE()
            WHERE POID=:pid AND BusinessID=:bid
        """), {"by": b.get("approved_by", "Thaiyme"), "pid": po_id, "bid": bid})
        db.commit()
        from routers.procurement import _sync_po_to_accounting_bill
        _sync_po_to_accounting_bill(db, po_id, bid)
        db.commit()
        try:
            from routers.notifications import notify_business
            po = db.execute(text("SELECT PONumber, SupplierName, TotalAmount FROM PurchaseOrder WHERE POID=:pid"), {"pid": po_id}).fetchone()
            if po:
                notify_business(db, bid, type="po_approved", title=f"PO approved: {po.PONumber}",
                                body=f"{po.SupplierName} — ${float(po.TotalAmount or 0):,.2f} approved via Thaiyme. Bill posted.",
                                link_path=f"/procurement?BusinessID={bid}", entity_type="PurchaseOrder", entity_id=po_id)
        except Exception:
            pass
        return {"ok": True, "executed": {"po_id": po_id, "status": "approved"}}

    if ep.startswith("/api/thaiyme/procurement/reject/") and method == "POST":
        _check_business_access(db, current_user.PeopleID, int(b.get("business_id", business_id or 0)), min_level=2)
        po_id = int(ep.split("/")[-1])
        bid = int(b.get("business_id", business_id or 0))
        db.execute(text("""
            UPDATE PurchaseOrder SET Status='rejected',
                Notes=ISNULL(Notes,'')+' [Rejected via Thaiyme: '+ISNULL(:reason,'')+']', UpdatedAt=GETDATE()
            WHERE POID=:pid AND BusinessID=:bid
        """), {"reason": b.get("reason"), "pid": po_id, "bid": bid})
        db.commit()
        try:
            from routers.notifications import notify_business
            po = db.execute(text("SELECT PONumber, SupplierName FROM PurchaseOrder WHERE POID=:pid"), {"pid": po_id}).fetchone()
            if po:
                notify_business(db, bid, type="po_rejected", title=f"PO rejected: {po.PONumber}",
                                body=f"{po.SupplierName} PO rejected via Thaiyme. Reason: {b.get('reason','N/A')}",
                                link_path=f"/procurement?BusinessID={bid}", entity_type="PurchaseOrder", entity_id=po_id)
        except Exception:
            pass
        return {"ok": True, "executed": {"po_id": po_id, "status": "rejected"}}

    raise HTTPException(400, f"Proposal endpoint not whitelisted: {ep}")


# ── Health + suggestions ─────────────────────────────────────────────

@router.get("/health")
def health():
    """Quick liveness check — Firestore + Gemini connectivity."""
    out: Dict[str, Any] = {"agent": AGENT_NAME, "ok": True}
    fs = _firestore()
    out["firestore"] = "up" if fs else "down"
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    out["gemini_api_key"] = "set" if api_key else "missing"
    out["rag_collection"] = THAIYME_RAG_COLLECTION
    out["chats_collection"] = THAIYME_CHATS_COLLECTION
    out["short_term_n"] = SHORT_TERM_N
    out["rag_top_k"] = RAG_TOP_K
    return out


@router.get("/suggestions")
def suggestions(
    business_id: Optional[int] = Query(None),
    event_id: Optional[int] = Query(None),
    page: Optional[str] = Query(None),
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Per-page suggested prompts that auto-fill the input."""
    if business_id:
        _check_business_access(db, current_user.PeopleID, business_id, min_level=1)
    if event_id:
        _check_event_access(db, current_user.PeopleID, event_id, min_level=1)

    chips: List[str] = []
    if event_id:
        chips = [
            "How many people are registered, and how many have paid?",
            "Who hasn't paid yet?",
            "Mark registration #__ as paid",
            "Cancel registration #__",
        ]
    elif business_id and (page or "").lower() == "accounting":
        chips = [
            "Give me a snapshot of the books.",
            "Which invoices are overdue?",
            "What payments came in this month?",
            "Find a customer named __",
        ]
    elif business_id and (page or "").lower() in ("work-orders", "work_orders"):
        chips = [
            "What's the farm operations status?",
            "Create a work order: spray field 3 for aphids, due tomorrow",
            "What work orders are overdue?",
            "Log 8 hours for Maria on planting today",
        ]
    elif business_id and (page or "").lower() in ("farm-inputs", "farm_inputs"):
        chips = [
            "What inputs are running low?",
            "Log usage: we used 50kg of Roundup on field 3",
            "Show me all chemical inputs",
            "What's our inventory status?",
        ]
    elif business_id and (page or "").lower() == "hr":
        chips = [
            "Log attendance: 8 hours for John Smith today",
            "How many employees are active?",
            "What tasks are pending?",
            "Log 6 hours for Maria on harvesting, field work",
        ]
    elif business_id and (page or "").lower() in ("farm-kpi", "packhouse-qc", "harvest-lots", "crop-budgets"):
        chips = [
            "What's the farm operations status?",
            "Any active pest observations?",
            "What's running low on inputs?",
            "Show me any urgent work orders",
        ]
    elif business_id and (page or "").lower() in ("outgrower", "outgrower-management"):
        chips = [
            "What's our total pending farmer payment balance?",
            "Show me contract delivery progress for maize",
            "Mark delivery #__ as paid",
            "Which farmers have pending payments?",
        ]
    elif business_id and (page or "").lower() == "procurement":
        chips = [
            "Any purchase orders waiting for approval?",
            "Approve PO #__ — signed off by manager",
            "Reject PO #__ — over budget",
            "What's our total open procurement spend?",
        ]
    elif business_id and (page or "").lower() in ("hr", "payroll"):
        chips = [
            "What's the estimated payroll cost for this week?",
            "Show me attendance hours for the past 14 days",
            "Log 8 hours for John Smith today",
            "How many employees are active?",
        ]
    else:
        chips = [
            "What can you help me with?",
            "Show me a snapshot of my business.",
        ]
    return {"suggestions": chips}


@router.get("/history")
def history(
    business_id: Optional[int] = Query(None),
    event_id: Optional[int] = Query(None),
    current_user: models.People = Depends(get_current_user),
):
    scope = (
        f"event:{event_id}" if event_id
        else (f"biz:{business_id}" if business_id else "global")
    )
    return {"messages": _load_recent_messages(current_user.PeopleID, scope)}


@router.delete("/history")
def clear_history(
    business_id: Optional[int] = Query(None),
    event_id: Optional[int] = Query(None),
    current_user: models.People = Depends(get_current_user),
):
    scope = (
        f"event:{event_id}" if event_id
        else (f"biz:{business_id}" if business_id else "global")
    )
    ok = _delete_thread(current_user.PeopleID, scope)
    return {"ok": ok}


# ── Mutation endpoints (event registration writes) ───────────────────

class RegPatch(BaseModel):
    PaymentStatus:     Optional[str] = None
    AttendeeFirstName: Optional[str] = None
    AttendeeLastName:  Optional[str] = None
    AttendeeEmail:     Optional[str] = None
    AttendeePhone:     Optional[str] = None
    Notes:             Optional[str] = None


@router.put("/registrations/{reg_id}")
def update_registration(
    reg_id: int,
    patch: RegPatch,
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.execute(
        text("SELECT EventID FROM OFNEventRegistrations WHERE RegID = :rid"),
        {"rid": reg_id},
    ).fetchone()
    if not row:
        raise HTTPException(404, "Registration not found.")
    _check_event_access(db, current_user.PeopleID, int(row.EventID), min_level=2)
    return _update_registration(
        db, reg_id, {k: v for k, v in patch.dict().items() if v is not None}
    )


@router.delete("/registrations/{reg_id}")
def cancel_registration(
    reg_id: int,
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.execute(
        text("SELECT EventID FROM OFNEventRegistrations WHERE RegID = :rid"),
        {"rid": reg_id},
    ).fetchone()
    if not row:
        raise HTTPException(404, "Registration not found.")
    _check_event_access(db, current_user.PeopleID, int(row.EventID), min_level=2)
    return _cancel_registration(db, reg_id)
