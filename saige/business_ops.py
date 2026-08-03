"""
Business-ops tools for Saige — mirrors the surface that Thaiyme exposes on the
main backend so Saige can answer accounting + event-hosting questions without
the user having to switch between agents.

Covered:
  - Accounting snapshot (AR/AP, recent invoices, last-30-day rev/spend)
  - List open invoices
  - Find customer (by name/company/email substring)
  - Recent payments (configurable look-back)
  - Event registrations (host-side: who registered, payment status)

Same access-scoping pattern as precision_ag.py: every business_id the user
mentions is verified against dbo.BusinessAccess for the current PeopleID
before any data is returned.
"""
from __future__ import annotations

from typing import List, Optional, Dict, Any
from langchain_core.tools import tool

from config import DB_CONFIG

try:
    import pymssql
    _PMS_AVAILABLE = True
except ImportError:
    _PMS_AVAILABLE = False


# ── DB helpers ──────────────────────────────────────────────────────────────

def _connect():
    if not _PMS_AVAILABLE or not all([DB_CONFIG.get("host"), DB_CONFIG.get("user"), DB_CONFIG.get("database")]):
        return None
    try:
        return pymssql.connect(
            server=DB_CONFIG["host"], user=DB_CONFIG["user"],
            password=DB_CONFIG["password"], database=DB_CONFIG["database"],
            timeout=10, login_timeout=10,
        )
    except Exception:
        return None


def _query(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = _connect()
    if not conn:
        return []
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql, params or ())
        rows = cur.fetchall() or []
        cur.close()
        return rows
    except Exception:
        return []
    finally:
        try: conn.close()
        except Exception: pass


def _business_ids_for_people(people_id: Optional[str]) -> List[int]:
    if not people_id:
        return []
    try:
        pid = int(people_id)
    except Exception:
        return []
    rows = _query(
        "SELECT BusinessID FROM dbo.BusinessAccess WHERE PeopleID = %s AND Active = 1",
        (pid,),
    )
    return [int(r["BusinessID"]) for r in rows if r.get("BusinessID")]


def _business_accessible(business_id: int, allowed: List[int]) -> bool:
    return int(business_id) in (allowed or [])


def _fmt_money(v) -> str:
    if v is None:
        return "—"
    try:
        return f"${float(v):,.2f}"
    except Exception:
        return str(v)


def _fmt_date(v) -> str:
    if not v:
        return "—"
    s = str(v)
    return s[:10] if len(s) >= 10 else s


# ── Tools ───────────────────────────────────────────────────────────────────

@tool
def get_accounting_snapshot_tool(business_id: int, people_id: str = "") -> str:
    """High-level accounting snapshot for a business: open AR (invoices) and
    AP (bills) totals, customer/vendor counts, recent invoice activity, and
    last-30-day invoiced revenue + paid expenses. Use for "how are the books
    looking", "what's outstanding", "give me a money summary"."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch accounting snapshot — account not linked to any business."
    if not _business_accessible(business_id, biz_ids):
        return f"Business {business_id} is not accessible on your account."

    lines = [f"Accounting snapshot — business #{business_id}"]

    ar = _query(
        "SELECT COUNT(1) AS n, ISNULL(SUM(BalanceDue), 0) AS bal "
        "FROM Invoices WHERE BusinessID = %s AND Status NOT IN ('Paid','Void')",
        (business_id,),
    )
    if ar:
        lines.append(f"  Open invoices: {ar[0].get('n', 0)} ({_fmt_money(ar[0].get('bal'))} outstanding)")

    ap = _query(
        "SELECT COUNT(1) AS n, ISNULL(SUM(BalanceDue), 0) AS bal "
        "FROM Bills WHERE BusinessID = %s AND Status NOT IN ('Paid','Void')",
        (business_id,),
    )
    if ap:
        lines.append(f"  Open bills: {ap[0].get('n', 0)} ({_fmt_money(ap[0].get('bal'))} owed)")

    rev = _query(
        "SELECT ISNULL(SUM(TotalAmount), 0) AS rev FROM Invoices "
        "WHERE BusinessID = %s AND InvoiceDate >= DATEADD(day, -30, CAST(GETDATE() AS DATE))",
        (business_id,),
    )
    spend = _query(
        "SELECT ISNULL(SUM(TotalAmount), 0) AS s FROM Expenses "
        "WHERE BusinessID = %s AND ExpenseDate >= DATEADD(day, -30, CAST(GETDATE() AS DATE))",
        (business_id,),
    )
    if rev or spend:
        lines.append(
            f"  Last 30 days: invoiced {_fmt_money(rev[0].get('rev') if rev else 0)}, "
            f"paid out {_fmt_money(spend[0].get('s') if spend else 0)}"
        )

    cc = _query("SELECT COUNT(1) AS n FROM AccountingCustomers WHERE BusinessID = %s AND IsActive = 1", (business_id,))
    vc = _query("SELECT COUNT(1) AS n FROM AccountingVendors  WHERE BusinessID = %s AND IsActive = 1", (business_id,))
    if cc and vc:
        lines.append(f"  Active customers: {cc[0].get('n', 0)} · vendors: {vc[0].get('n', 0)}")

    recent = _query(
        "SELECT TOP 5 InvoiceNumber, InvoiceDate, Status, TotalAmount, BalanceDue "
        "FROM Invoices WHERE BusinessID = %s ORDER BY InvoiceDate DESC",
        (business_id,),
    )
    if recent:
        lines.append("  Recent invoices:")
        for r in recent:
            lines.append(
                f"    {r.get('InvoiceNumber')} · {_fmt_date(r.get('InvoiceDate'))} · "
                f"{r.get('Status')} · {_fmt_money(r.get('TotalAmount'))} (bal {_fmt_money(r.get('BalanceDue'))})"
            )

    return "\n".join(lines)


@tool
def list_open_invoices_tool(business_id: int, limit: int = 25, people_id: str = "") -> str:
    """List up to 25 open (unpaid) invoices for a business, sorted by due date
    ascending so overdue lands first. Use for "what's overdue", "who hasn't
    paid", "show me unpaid invoices"."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids or not _business_accessible(business_id, biz_ids):
        return "Business not accessible on your account."

    n = max(1, min(int(limit or 25), 50))
    rows = _query(
        f"SELECT TOP {n} i.InvoiceNumber, i.InvoiceDate, i.DueDate, i.Status, "
        f"       i.TotalAmount, i.BalanceDue, c.DisplayName AS Customer "
        f"  FROM Invoices i LEFT JOIN AccountingCustomers c ON c.CustomerID = i.CustomerID "
        f" WHERE i.BusinessID = %s AND i.Status NOT IN ('Paid','Void') "
        f" ORDER BY i.DueDate ASC",
        (business_id,),
    )
    if not rows:
        return f"No open invoices for business #{business_id}."

    lines = [f"Open invoices — business #{business_id} ({len(rows)} shown):"]
    for r in rows:
        lines.append(
            f"  {r.get('InvoiceNumber')} · due {_fmt_date(r.get('DueDate'))} · "
            f"{r.get('Customer') or '—'} · {_fmt_money(r.get('BalanceDue'))} of {_fmt_money(r.get('TotalAmount'))}"
        )
    return "\n".join(lines)


@tool
def find_customer_tool(business_id: int, query: str, people_id: str = "") -> str:
    """Search a business's customer list by name, company, or email substring.
    Returns up to 10 matches with masked contact info. Use for "find John",
    "look up Acme Co", "do we have a customer with that email"."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids or not _business_accessible(business_id, biz_ids):
        return "Business not accessible on your account."

    q = f"%{(query or '').strip()}%"
    if q == "%%":
        return "Provide a search term (name, company, or email substring)."
    rows = _query(
        "SELECT TOP 10 DisplayName, CompanyName, Email, Phone, BillingCity, BillingState "
        "  FROM AccountingCustomers WHERE BusinessID = %s "
        "   AND (DisplayName LIKE %s OR CompanyName LIKE %s OR FirstName LIKE %s "
        "        OR LastName LIKE %s OR Email LIKE %s) "
        " ORDER BY DisplayName",
        (business_id, q, q, q, q, q),
    )
    if not rows:
        return f"No customers matching '{query}' on business #{business_id}."

    def mask_email(e: Optional[str]) -> str:
        if not e or "@" not in e: return "—"
        local, dom = e.split("@", 1)
        return f"{local[:1]}***@{dom}"
    def mask_phone(p: Optional[str]) -> str:
        if not p: return "—"
        digits = "".join(c for c in str(p) if c.isdigit())
        return f"***-***-{digits[-4:]}" if len(digits) >= 4 else "***"

    lines = [f"Customer search '{query}' — {len(rows)} match(es):"]
    for r in rows:
        place = ", ".join(filter(None, [r.get("BillingCity"), r.get("BillingState")])) or "—"
        lines.append(
            f"  {r.get('DisplayName')} ({r.get('CompanyName') or '—'}) · "
            f"{mask_email(r.get('Email'))} · {mask_phone(r.get('Phone'))} · {place}"
        )
    return "\n".join(lines)


@tool
def get_recent_payments_tool(business_id: int, days: int = 30, people_id: str = "") -> str:
    """List customer payments received in the last N days for a business.
    Use for "what came in this month", "recent payments", "cash flow last
    week"."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids or not _business_accessible(business_id, biz_ids):
        return "Business not accessible on your account."

    d = max(1, min(int(days or 30), 365))
    rows = _query(
        f"SELECT TOP 25 p.PaymentNumber, p.PaymentDate, p.PaymentMethod, p.Amount, "
        f"       c.DisplayName AS Customer "
        f"  FROM Payments p LEFT JOIN AccountingCustomers c ON c.CustomerID = p.CustomerID "
        f" WHERE p.BusinessID = %s "
        f"   AND p.PaymentDate >= DATEADD(day, -{d}, CAST(GETDATE() AS DATE)) "
        f" ORDER BY p.PaymentDate DESC",
        (business_id,),
    )
    if not rows:
        return f"No payments in the last {d} days for business #{business_id}."

    total = sum((r.get("Amount") or 0) for r in rows)
    lines = [f"Payments in last {d} days — business #{business_id} (total {_fmt_money(total)} across {len(rows)}):"]
    for r in rows:
        lines.append(
            f"  {_fmt_date(r.get('PaymentDate'))} · {r.get('Customer') or '—'} · "
            f"{r.get('PaymentMethod') or '—'} · {_fmt_money(r.get('Amount'))} ({r.get('PaymentNumber') or '—'})"
        )
    return "\n".join(lines)


@tool
def get_event_registrations_tool(event_id: int, people_id: str = "") -> str:
    """List registrations for an event the user is hosting (host-side view).
    Returns up to 50 registrations with payment status + masked attendee
    contact. Use for "who's registered for my event", "how many paid for
    event 42", "show me my event roster"."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch registrations — account not linked to any business."

    ev = _query("SELECT EventID, EventName, BusinessID FROM OFNEvents WHERE EventID = %s", (int(event_id),))
    if not ev:
        return f"Event {event_id} not found."
    if int(ev[0].get("BusinessID") or 0) not in biz_ids:
        return f"Event {event_id} is hosted by a business not linked to your account."

    rows = _query(
        "SELECT TOP 50 RegID, RegDate, TotalAmount, PaymentStatus, "
        "       AttendeeFirstName, AttendeeLastName, AttendeeEmail "
        "  FROM OFNEventRegistrations WHERE EventID = %s ORDER BY RegDate DESC",
        (int(event_id),),
    )
    name = ev[0].get("EventName") or f"event #{event_id}"
    if not rows:
        return f"No registrations yet for {name}."

    paid = sum(1 for r in rows if (r.get("PaymentStatus") or "").lower() == "paid")
    lines = [f"Registrations — {name} ({len(rows)} total, {paid} paid):"]
    for r in rows[:25]:
        first = r.get("AttendeeFirstName") or ""
        last  = (r.get("AttendeeLastName") or "")
        last_init = (last[:1] + ".") if last else ""
        email = r.get("AttendeeEmail") or ""
        masked_email = (email.split("@")[0][:1] + "***@" + email.split("@")[1]) if "@" in email else "—"
        lines.append(
            f"  #{r.get('RegID')} · {_fmt_date(r.get('RegDate'))} · "
            f"{first} {last_init} · {masked_email} · "
            f"{r.get('PaymentStatus') or '—'} · {_fmt_money(r.get('TotalAmount'))}"
        )
    return "\n".join(lines)


# ── Sponsorship (event revenue from sponsors) ───────────────────────────────

@tool
def get_event_sponsorship_summary_tool(event_id: int, people_id: str = "") -> str:
    """Sponsorship revenue + pipeline for an event the user owns. Returns total
    revenue collected, count of confirmed sponsors, total in pipeline, and a
    per-tier breakdown (tier name, price, slots taken vs max, revenue per tier).
    Use for "how much have we raised in sponsorships", "are sponsorship tiers
    selling", "which tier needs attention", "am I close to filling the Gold
    tier"."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch sponsorship — account not linked to any business."
    ev = _query("SELECT EventID, EventName, BusinessID FROM OFNEvents WHERE EventID = %s", (int(event_id),))
    if not ev:
        return f"Event {event_id} not found."
    if int(ev[0].get("BusinessID") or 0) not in biz_ids:
        return f"Event {event_id} is hosted by a business not linked to your account."

    name = ev[0].get("EventName") or f"event #{event_id}"
    tiers = _query("""
        SELECT t.TierID, t.Name, t.Price, t.MaxSlots,
               COUNT(s.SponsorID) AS sponsors,
               SUM(CASE WHEN s.Status='confirmed' THEN 1 ELSE 0 END) AS confirmed,
               ISNULL(SUM(s.AmountPaid), 0) AS revenue
          FROM OFNEventSponsorTier t
          LEFT JOIN OFNEventSponsor s ON s.TierID = t.TierID
         WHERE t.EventID = %s
         GROUP BY t.TierID, t.Name, t.Price, t.MaxSlots, t.SortOrder
         ORDER BY t.SortOrder, t.Price DESC
    """, (int(event_id),))

    if not tiers:
        return f"{name} has no sponsorship tiers configured yet."

    total_rev   = sum(float(t.get("revenue") or 0) for t in tiers)
    total_conf  = sum(int(t.get("confirmed") or 0) for t in tiers)
    total_pipe  = sum(int(t.get("sponsors") or 0) for t in tiers)

    lines = [f"Sponsorship — {name}"]
    lines.append(f"  Revenue: {_fmt_money(total_rev)} · Confirmed: {total_conf} · Pipeline: {total_pipe}")
    lines.append("  By tier:")
    for t in tiers:
        slots = f" ({t.get('confirmed') or 0}/{t.get('MaxSlots')} slots)" if t.get("MaxSlots") else ""
        lines.append(
            f"    {t.get('Name')}: {_fmt_money(t.get('Price') or 0)} list price · "
            f"{int(t.get('sponsors') or 0)} sponsor(s){slots} · "
            f"{_fmt_money(t.get('revenue') or 0)} collected"
        )
    return "\n".join(lines)


@tool
def list_event_sponsors_tool(event_id: int, status: str = "", people_id: str = "") -> str:
    """List sponsors for an event the user owns, with tier, paid status, and
    contact info (masked). Optional `status` filter: 'pending' / 'confirmed' /
    'declined'. Use for "who's sponsoring", "any unpaid sponsors", "show me
    confirmed sponsors"."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch sponsors — account not linked to any business."
    ev = _query("SELECT BusinessID, EventName FROM OFNEvents WHERE EventID = %s", (int(event_id),))
    if not ev or int(ev[0].get("BusinessID") or 0) not in biz_ids:
        return f"Event {event_id} not accessible on your account."

    where = "WHERE s.EventID = %s"
    params = [int(event_id)]
    if status:
        where += " AND s.Status = %s"
        params.append(status)

    rows = _query(f"""
        SELECT TOP 50 s.SponsorID, s.BusinessName, s.ContactEmail, s.ContactName,
               s.Status, s.PaidStatus, s.AmountPaid, s.WebsiteURL,
               t.Name AS TierName, t.Price AS TierPrice
          FROM OFNEventSponsor s
          LEFT JOIN OFNEventSponsorTier t ON t.TierID = s.TierID
          {where}
         ORDER BY t.SortOrder, t.Price DESC, s.BusinessName
    """, tuple(params))

    if not rows:
        return f"No {status or 'matching'} sponsors for {ev[0].get('EventName') or 'event'}."

    def mask_email(e):
        if not e or "@" not in e: return "—"
        local, dom = e.split("@", 1)
        return f"{local[:1]}***@{dom}"

    lines = [f"Sponsors — {ev[0].get('EventName') or 'event'} ({len(rows)} shown):"]
    for r in rows:
        lines.append(
            f"  {r.get('BusinessName')} · {r.get('TierName') or '(no tier)'} · "
            f"{r.get('Status')}/{r.get('PaidStatus')} · paid {_fmt_money(r.get('AmountPaid'))} of "
            f"{_fmt_money(r.get('TierPrice') or 0)} · {mask_email(r.get('ContactEmail'))}"
        )
    return "\n".join(lines)


# ── Lead retrieval (exhibitor scans of attendees) ───────────────────────────

@tool
def get_my_event_leads_summary_tool(event_id: int, business_id: int, people_id: str = "") -> str:
    """How are my exhibitor leads from a specific event looking? Returns total
    scans, breakdown by follow-up status (new / contacted / qualified / won /
    lost) and by rating (1-5 stars). Use for "how many leads did I get",
    "what's my pipeline", "did I follow up on my best leads"."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch leads — account not linked to any business."
    if int(business_id) not in biz_ids:
        return f"Business {business_id} is not accessible on your account."

    total = _query("""
        SELECT COUNT(1) AS n FROM OFNEventLeadScan
         WHERE EventID = %s AND ExhibitorBusinessID = %s
    """, (int(event_id), int(business_id)))
    n = int(total[0].get("n") or 0) if total else 0
    if n == 0:
        return f"No leads captured at event #{event_id} for business #{business_id} yet."

    by_status = _query("""
        SELECT FollowUpStatus, COUNT(1) AS n FROM OFNEventLeadScan
         WHERE EventID = %s AND ExhibitorBusinessID = %s
         GROUP BY FollowUpStatus
    """, (int(event_id), int(business_id)))
    by_rating = _query("""
        SELECT Rating, COUNT(1) AS n FROM OFNEventLeadScan
         WHERE EventID = %s AND ExhibitorBusinessID = %s AND Rating IS NOT NULL
         GROUP BY Rating ORDER BY Rating DESC
    """, (int(event_id), int(business_id)))

    lines = [f"Lead summary — event #{event_id}, business #{business_id}"]
    lines.append(f"  Total leads: {n}")
    if by_status:
        lines.append("  By follow-up status:")
        for r in by_status:
            lines.append(f"    {r.get('FollowUpStatus') or 'new'}: {int(r.get('n') or 0)}")
    if by_rating:
        lines.append("  By rating:")
        for r in by_rating:
            stars = "★" * int(r.get("Rating") or 0)
            lines.append(f"    {stars}: {int(r.get('n') or 0)}")
    return "\n".join(lines)


@tool
def list_my_event_leads_tool(
    event_id: int,
    business_id: int,
    status: str = "",
    rating_min: int = 0,
    people_id: str = "",
) -> str:
    """List my exhibitor lead scans from an event with masked contact info.
    Filter by `status` (new/contacted/qualified/won/lost) or `rating_min`
    (1-5). Use for "show me my hot leads", "who haven't I followed up with",
    "list my qualified leads from event 12"."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch leads — account not linked to any business."
    if int(business_id) not in biz_ids:
        return f"Business {business_id} is not accessible on your account."

    where = ["EventID = %s", "ExhibitorBusinessID = %s"]
    params = [int(event_id), int(business_id)]
    if status:
        where.append("FollowUpStatus = %s"); params.append(status)
    if rating_min and rating_min > 0:
        where.append("Rating >= %s"); params.append(int(rating_min))

    rows = _query(f"""
        SELECT TOP 25 ScanID, ScanDate, AttendeeName, AttendeeBusiness,
               AttendeeEmail, Rating, Interest, FollowUpStatus, Notes
          FROM OFNEventLeadScan
         WHERE {' AND '.join(where)}
         ORDER BY ScanDate DESC
    """, tuple(params))

    if not rows:
        return f"No leads matching those filters for event #{event_id}."

    def mask_email(e):
        if not e or "@" not in e: return "—"
        local, dom = e.split("@", 1)
        return f"{local[:1]}***@{dom}"

    lines = [f"Leads — event #{event_id} · business #{business_id} ({len(rows)} shown):"]
    for r in rows:
        rating = "★" * int(r.get("Rating") or 0)
        lines.append(
            f"  {_fmt_date(r.get('ScanDate'))} · {r.get('AttendeeName') or '(unnamed)'}"
            f"{(' · ' + r.get('AttendeeBusiness')) if r.get('AttendeeBusiness') else ''} · "
            f"{mask_email(r.get('AttendeeEmail'))} · "
            f"{r.get('FollowUpStatus') or 'new'}{(' ' + rating) if rating else ''}"
            f"{(' · ' + r.get('Interest')) if r.get('Interest') else ''}"
        )
    return "\n".join(lines)


# ── Floor plan + booth sales (event organizer) ──────────────────────────────

@tool
def get_event_floor_plan_summary_tool(event_id: int, people_id: str = "") -> str:
    """Booth-sales snapshot for an event the user owns: total booths, breakdown
    by status (available / reserved / sold / blocked) and by tier (premium /
    standard / corner / aisle / blocked). Use for "how many booths sold",
    "is the floor plan filling up", "what's left for vendors"."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch floor plan — account not linked to any business."
    ev = _query("SELECT BusinessID, EventName FROM OFNEvents WHERE EventID = %s", (int(event_id),))
    if not ev or int(ev[0].get("BusinessID") or 0) not in biz_ids:
        return f"Event {event_id} not accessible on your account."
    name = ev[0].get("EventName") or f"event #{event_id}"

    by_status = _query("""
        SELECT Status, COUNT(1) AS n FROM OFNEventBooth
         WHERE EventID = %s GROUP BY Status
    """, (int(event_id),))
    by_tier = _query("""
        SELECT Tier, COUNT(1) AS n FROM OFNEventBooth
         WHERE EventID = %s GROUP BY Tier
    """, (int(event_id),))
    total = sum(int(r.get("n") or 0) for r in by_status)
    if total == 0:
        return f"{name} has no booths configured on the floor plan yet."

    lines = [f"Floor plan — {name}", f"  Total booths: {total}"]
    if by_status:
        avail = next((int(r.get("n") or 0) for r in by_status if (r.get("Status") or "") == "available"), 0)
        lines.append(f"  Available: {avail}  ({100.0 * avail / total:.0f}% of grid)")
        for r in by_status:
            if (r.get("Status") or "") != "available":
                lines.append(f"  {r.get('Status')}: {int(r.get('n') or 0)}")
    if by_tier:
        lines.append("  By tier: " + ", ".join(f"{r.get('Tier')}={int(r.get('n') or 0)}" for r in by_tier))
    return "\n".join(lines)


@tool
def get_event_booth_services_revenue_tool(event_id: int, people_id: str = "") -> str:
    """Booth-services revenue for an event the user owns: total revenue from
    à la carte add-ons (electrical / water / internet / table / AV / drayage)
    plus per-service units sold and dollars. Use for "how much in services
    revenue", "what add-ons are selling", "is anyone ordering electrical"."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch services revenue — account not linked to any business."
    ev = _query("SELECT BusinessID, EventName FROM OFNEvents WHERE EventID = %s", (int(event_id),))
    if not ev or int(ev[0].get("BusinessID") or 0) not in biz_ids:
        return f"Event {event_id} not accessible on your account."

    rows = _query("""
        SELECT s.Name, s.Category, s.Unit,
               COUNT(o.OrderID) AS line_count,
               ISNULL(SUM(o.Quantity), 0)  AS units_sold,
               ISNULL(SUM(ISNULL(o.UnitPrice, 0) * ISNULL(o.Quantity, 0)), 0) AS revenue
          FROM OFNEventBoothService s
          LEFT JOIN OFNEventBoothServiceOrder o ON o.ServiceID = s.ServiceID
         WHERE s.EventID = %s
         GROUP BY s.ServiceID, s.Name, s.Category, s.Unit, s.SortOrder
         ORDER BY s.SortOrder, s.Category, s.Name
    """, (int(event_id),))
    if not rows:
        return f"{ev[0].get('EventName') or 'event'} has no booth services configured."

    total = sum(float(r.get("revenue") or 0) for r in rows)
    lines = [f"Booth services revenue — {ev[0].get('EventName')}: {_fmt_money(total)} total"]
    sold = [r for r in rows if int(r.get("units_sold") or 0) > 0]
    if not sold:
        lines.append("  No services ordered yet.")
    for r in sold:
        lines.append(
            f"  {r.get('Name')} ({r.get('Category')}): {int(r.get('units_sold') or 0)} {r.get('Unit')} · {_fmt_money(r.get('revenue'))}"
        )
    if len(rows) - len(sold) > 0:
        lines.append(f"  ({len(rows) - len(sold)} catalog item(s) with zero orders)")
    return "\n".join(lines)


# ── COI tracking ────────────────────────────────────────────────────────────

@tool
def get_event_coi_summary_tool(event_id: int, people_id: str = "") -> str:
    """Certificate of Insurance status for an event: counts by status
    (pending / approved / rejected / expired) and how many are expiring
    within the next 30 days. Use for "any pending COIs to review", "are
    sponsors compliant", "are any COIs expiring soon"."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch COIs — account not linked to any business."
    ev = _query("SELECT BusinessID, EventName FROM OFNEvents WHERE EventID = %s", (int(event_id),))
    if not ev or int(ev[0].get("BusinessID") or 0) not in biz_ids:
        return f"Event {event_id} not accessible on your account."

    by_status = _query("""
        SELECT Status, COUNT(1) AS n FROM OFNEventCOI
         WHERE EventID = %s GROUP BY Status
    """, (int(event_id),))
    expiring = _query("""
        SELECT COUNT(1) AS n FROM OFNEventCOI
         WHERE EventID = %s AND Status='approved'
           AND ExpiryDate IS NOT NULL
           AND ExpiryDate BETWEEN CAST(GETDATE() AS DATE) AND DATEADD(day, 30, CAST(GETDATE() AS DATE))
    """, (int(event_id),))

    total = sum(int(r.get("n") or 0) for r in by_status)
    if total == 0:
        return f"No COIs uploaded for {ev[0].get('EventName') or 'event'} yet."

    lines = [f"COI status — {ev[0].get('EventName')}: {total} document(s)"]
    for r in by_status:
        lines.append(f"  {r.get('Status')}: {int(r.get('n') or 0)}")
    exp = int(expiring[0].get("n") or 0) if expiring else 0
    if exp:
        lines.append(f"  ⚠ {exp} approved COI(s) expire within 30 days")
    return "\n".join(lines)


@tool
def list_event_pending_cois_tool(event_id: int, people_id: str = "") -> str:
    """List COI uploads needing review — pending or recently expired. Use for
    "what COIs need approval", "show me pending insurance", "review queue"."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch COIs — account not linked to any business."
    ev = _query("SELECT BusinessID, EventName FROM OFNEvents WHERE EventID = %s", (int(event_id),))
    if not ev or int(ev[0].get("BusinessID") or 0) not in biz_ids:
        return f"Event {event_id} not accessible on your account."

    rows = _query("""
        SELECT TOP 20 COIID, EntityType, EntityID, EntityName, CarrierName,
               PolicyNumber, EffectiveDate, ExpiryDate, Status, UploadedAt,
               CoverageAmount
          FROM OFNEventCOI
         WHERE EventID = %s
           AND Status IN ('pending', 'expired')
         ORDER BY UploadedAt DESC
    """, (int(event_id),))
    if not rows:
        return f"No pending or expired COIs for {ev[0].get('EventName') or 'event'}. All caught up!"

    lines = [f"COI review queue — {ev[0].get('EventName')} ({len(rows)} item(s)):"]
    for r in rows:
        lines.append(
            f"  [{r.get('Status')}] {r.get('EntityType')}#{r.get('EntityID')}"
            f"{(' (' + r.get('EntityName') + ')') if r.get('EntityName') else ''} · "
            f"{r.get('CarrierName') or 'no carrier'} · "
            f"expires {_fmt_date(r.get('ExpiryDate'))}"
            f"{(' · ' + _fmt_money(r.get('CoverageAmount')) + ' coverage') if r.get('CoverageAmount') else ''}"
        )
    return "\n".join(lines)


@tool
def get_tracked_grants_tool(business_id: int, people_id: str = "") -> str:
    """Return the grants and programs this business is actively tracking —
    including each grant's title, agency, status (interested / in_progress /
    submitted / awarded / declined / not_eligible), notes, applied date,
    result date, and amount received. Use when the user asks 'what grants am
    I tracking', 'show my grant applications', 'what programs am I applying for',
    or anything about their personal grant tracker."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch grant tracking — account not linked to any business."
    if not _business_accessible(business_id, biz_ids):
        return f"Business {business_id} is not accessible on your account."

    rows = _query(
        """
        SELECT t.Status, t.Notes, t.AppliedDate, t.ResultDate, t.AmountReceived,
               g.Title, g.Agency, g.MaxAmount, g.Deadline, g.ExternalUrl
        FROM BusinessGrantTracking t
        JOIN GrantPrograms g ON g.GrantID = t.GrantID
        WHERE t.BusinessID = %s
        ORDER BY t.CreatedAt DESC
        """,
        (business_id,),
    )
    if not rows:
        return "No grants are currently being tracked for this business."

    lines = [f"Tracked grants for business #{business_id} ({len(rows)} total):"]
    for r in rows:
        line = f"  • {r.get('Title')} ({r.get('Agency') or 'Unknown agency'}) — Status: {r.get('Status')}"
        if r.get("AmountReceived"):
            line += f" · Received: {_fmt_money(r['AmountReceived'])}"
        elif r.get("MaxAmount"):
            line += f" · Max award: {_fmt_money(r['MaxAmount'])}"
        if r.get("Deadline"):
            line += f" · Deadline: {_fmt_date(r['Deadline'])}"
        if r.get("AppliedDate"):
            line += f" · Applied: {_fmt_date(r['AppliedDate'])}"
        if r.get("ResultDate"):
            line += f" · Result: {_fmt_date(r['ResultDate'])}"
        if r.get("Notes"):
            line += f" · Notes: {r['Notes']}"
        lines.append(line)
    return "\n".join(lines)


_SHELF_LIFE_PARAMS = {
    "leafy_greens": {"t_ref": 4.0,  "q10": 2.5, "base_days": 10},
    "berries":      {"t_ref": 2.0,  "q10": 3.0, "base_days":  7},
    "root_veg":     {"t_ref": 2.0,  "q10": 2.0, "base_days": 30},
    "eggs":         {"t_ref": 4.0,  "q10": 2.0, "base_days": 35},
    "dairy_milk":   {"t_ref": 4.0,  "q10": 3.0, "base_days": 14},
    "apples":       {"t_ref": 1.0,  "q10": 2.0, "base_days": 60},
    "tomatoes":     {"t_ref": 13.0, "q10": 2.0, "base_days": 14},
    "bananas":      {"t_ref": 13.0, "q10": 2.5, "base_days": 10},
    "meat_fresh":   {"t_ref": 2.0,  "q10": 3.5, "base_days":  7},
    "poultry":      {"t_ref": 2.0,  "q10": 3.5, "base_days":  5},
    "fish":         {"t_ref": 0.0,  "q10": 4.0, "base_days":  3},
    "general":      {"t_ref": 4.0,  "q10": 2.0, "base_days": 14},
}


@tool
def calculate_shelf_life_tool(
    vehicle_id: int,
    product_type: str = "general",
    original_shelf_life_days: int = 7,
    lookback_hours: int = 48,
    business_id: int = 0,
    people_id: str = "",
) -> str:
    """Calculate the adjusted shelf life for cargo on a cold-chain vehicle using the
    Q10 degradation model applied to actual temperature readings. Returns the remaining
    shelf life in days, degradation percentage, excursion time, and a recommended action
    (Normal / Expedite / Express Sale / Discard). Use when asked about cargo freshness,
    shelf life impact of a temperature excursion, or whether a shipment is still viable.

    product_type options: leafy_greens, berries, root_veg, eggs, dairy_milk, apples,
    tomatoes, bananas, meat_fresh, poultry, fish, general."""
    from datetime import datetime, timezone

    params = _SHELF_LIFE_PARAMS.get(product_type, _SHELF_LIFE_PARAMS["general"])
    t_ref, q10 = params["t_ref"], params["q10"]
    base_minutes = original_shelf_life_days * 24 * 60

    rows = _query(
        f"""
        SELECT TOP 500 TempC, RecordedAt
        FROM ColdChainReading
        WHERE VehicleID = %s
          AND RecordedAt >= DATEADD(HOUR, -{lookback_hours}, GETDATE())
        ORDER BY RecordedAt ASC
        """,
        (vehicle_id,),
    )

    if len(rows) < 2:
        return (
            f"Not enough temperature readings for vehicle {vehicle_id} in the last "
            f"{lookback_hours} hours (found {len(rows)}). Log more readings to run a "
            f"shelf-life calculation."
        )

    fraction_consumed = 0.0
    excursion_minutes = 0
    max_excursion_temp = None

    for i in range(1, len(rows)):
        try:
            t_prev = rows[i - 1]["RecordedAt"]
            t_curr = rows[i]["RecordedAt"]
            if hasattr(t_prev, "timestamp") and hasattr(t_curr, "timestamp"):
                interval_min = abs((t_curr - t_prev).total_seconds()) / 60.0
            else:
                interval_min = 5.0
        except Exception:
            interval_min = 5.0

        temp = float(rows[i]["TempC"])
        rate_factor = q10 ** ((temp - t_ref) / 10.0)
        fraction_consumed += (rate_factor * interval_min) / base_minutes

        if temp > t_ref:
            excursion_minutes += int(interval_min)
            if max_excursion_temp is None or temp > max_excursion_temp:
                max_excursion_temp = temp

    adjusted = max(0.0, original_shelf_life_days * (1.0 - fraction_consumed))
    degradation_pct = round(fraction_consumed * 100, 1)

    if adjusted <= 0:
        action = "DISCARD — shelf life exhausted. Do not distribute."
    elif degradation_pct >= 60:
        action = "EXPRESS SALE — move to priority/clearance immediately."
    elif degradation_pct >= 30:
        action = "EXPEDITE delivery — shelf life significantly reduced."
    else:
        action = "Normal distribution — shelf life within acceptable range."

    lines = [
        f"Shelf-Life SLA for vehicle {vehicle_id} ({product_type.replace('_', ' ')}):",
        f"  Original shelf life:  {original_shelf_life_days} days",
        f"  Adjusted shelf life:  {adjusted:.1f} days ({degradation_pct:.1f}% degraded)",
        f"  Temp excursion:       {excursion_minutes} minutes above {t_ref}°C optimal",
    ]
    if max_excursion_temp is not None:
        lines.append(f"  Peak excursion temp:  {max_excursion_temp:.1f}°C")
    lines.append(f"  Readings analyzed:    {len(rows)}")
    lines.append(f"  Recommended action:   {action}")
    return "\n".join(lines)


# ── Tool registry ───────────────────────────────────────────────────────────

business_ops_tools = [
    get_accounting_snapshot_tool,
    list_open_invoices_tool,
    find_customer_tool,
    get_recent_payments_tool,
    get_event_registrations_tool,
    get_event_sponsorship_summary_tool,
    list_event_sponsors_tool,
    get_my_event_leads_summary_tool,
    list_my_event_leads_tool,
    get_event_floor_plan_summary_tool,
    get_event_booth_services_revenue_tool,
    get_event_coi_summary_tool,
    list_event_pending_cois_tool,
    get_tracked_grants_tool,
    calculate_shelf_life_tool,
]
