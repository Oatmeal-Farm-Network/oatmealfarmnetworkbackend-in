"""
Draft-action tools for Saige (Slice D).

Saige can PROPOSE creating marketplace listings, events, and blog posts — but
never commits them. Each draft tool stashes a payload in the `SaigeDrafts`
table with Status='pending'. The frontend surfaces pending drafts with
approve/edit/reject buttons; approve routes through the matching committer in
api.py which creates the real resource (Produce / OFNEvents / blog).

Tools:
  - draft_produce_listing_tool(ingredient_name, quantity, measurement,
        retail_price, available_date)
  - draft_event_tool(event_name, description, start_date, end_date, location,
        is_free, registration_required)
  - draft_blog_post_tool(title, content, category)

All tools require people_id + business_id, which are injected from graph
state by nodes.py (the LLM never guesses them).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from langchain_core.tools import tool

from config import DB_CONFIG

try:
    import pymssql
    _PMS_AVAILABLE = True
except ImportError:
    _PMS_AVAILABLE = False


DRAFT_TYPE_PRODUCE        = "produce_listing"
DRAFT_TYPE_MEAT           = "meat_listing"
DRAFT_TYPE_PROCESSED_FOOD = "processed_food_listing"
DRAFT_TYPE_EVENT          = "event"
DRAFT_TYPE_BLOG           = "blog_post"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _connect():
    if not _PMS_AVAILABLE or not all([DB_CONFIG.get("host"), DB_CONFIG.get("user"), DB_CONFIG.get("database")]):
        return None
    try:
        return pymssql.connect(
            server=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
            as_dict=True,
        )
    except Exception as e:
        print(f"[saige.actions] DB connect failed: {e}")
        return None


_ENSURED = False

def _ensure_table() -> bool:
    global _ENSURED
    if _ENSURED:
        return True
    conn = _connect()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'SaigeDrafts')
            CREATE TABLE SaigeDrafts (
                DraftID               INT IDENTITY(1,1) PRIMARY KEY,
                PeopleID              NVARCHAR(50) NULL,
                BusinessID            INT NULL,
                DraftType             NVARCHAR(50) NOT NULL,
                PayloadJSON           NVARCHAR(MAX) NOT NULL,
                Status                NVARCHAR(20) NOT NULL DEFAULT 'pending',
                CommittedResourceID   INT NULL,
                Summary               NVARCHAR(500) NULL,
                CreatedAt             DATETIME NOT NULL DEFAULT GETUTCDATE(),
                UpdatedAt             DATETIME NULL,
                ApprovedAt            DATETIME NULL,
                RejectedAt            DATETIME NULL,
                RejectionReason       NVARCHAR(500) NULL
            )
        """)
        conn.commit()
        _ENSURED = True
        return True
    except Exception as e:
        print(f"[saige.actions] ensure_table failed: {e}")
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _insert_draft(
    people_id: Optional[str],
    business_id: Optional[int],
    draft_type: str,
    payload: Dict[str, Any],
    summary: str,
) -> Optional[int]:
    if not _ensure_table():
        return None
    conn = _connect()
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO SaigeDrafts (PeopleID, BusinessID, DraftType, PayloadJSON, Status, Summary, CreatedAt)
            OUTPUT INSERTED.DraftID
            VALUES (%s, %s, %s, %s, 'pending', %s, GETUTCDATE())
            """,
            (
                str(people_id) if people_id else None,
                int(business_id) if business_id else None,
                str(draft_type),
                json.dumps(payload, default=str),
                (summary or "")[:500],
            ),
        )
        row = cur.fetchone()
        conn.commit()
        if not row:
            return None
        # as_dict returns lowercased keys
        return int(row.get("draftid") or row.get("DraftID"))
    except Exception as e:
        print(f"[saige.actions] insert_draft failed: {e}")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def list_pending_drafts(people_id: Optional[str], business_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Non-tool helper used by REST endpoints — lists this user's pending drafts."""
    if not _ensure_table():
        return []
    conn = _connect()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        if business_id:
            cur.execute(
                """
                SELECT DraftID, PeopleID, BusinessID, DraftType, PayloadJSON, Status,
                       Summary, CreatedAt, UpdatedAt
                FROM SaigeDrafts
                WHERE Status = 'pending'
                  AND (PeopleID = %s OR BusinessID = %s)
                ORDER BY CreatedAt DESC
                """,
                (str(people_id or ""), int(business_id)),
            )
        else:
            cur.execute(
                """
                SELECT DraftID, PeopleID, BusinessID, DraftType, PayloadJSON, Status,
                       Summary, CreatedAt, UpdatedAt
                FROM SaigeDrafts
                WHERE Status = 'pending' AND PeopleID = %s
                ORDER BY CreatedAt DESC
                """,
                (str(people_id or ""),),
            )
        rows = cur.fetchall() or []
        return [_row_to_draft(r) for r in rows]
    except Exception as e:
        print(f"[saige.actions] list_pending_drafts failed: {e}")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_draft(draft_id: int) -> Optional[Dict[str, Any]]:
    if not _ensure_table():
        return None
    conn = _connect()
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DraftID, PeopleID, BusinessID, DraftType, PayloadJSON, Status,
                   Summary, CommittedResourceID, CreatedAt, UpdatedAt, ApprovedAt,
                   RejectedAt, RejectionReason
            FROM SaigeDrafts WHERE DraftID = %s
            """,
            (int(draft_id),),
        )
        row = cur.fetchone()
        return _row_to_draft(row) if row else None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def update_draft_payload(draft_id: int, payload: Dict[str, Any]) -> bool:
    conn = _connect()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE SaigeDrafts
               SET PayloadJSON = %s, UpdatedAt = GETUTCDATE()
             WHERE DraftID = %s AND Status = 'pending'
            """,
            (json.dumps(payload, default=str), int(draft_id)),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        print(f"[saige.actions] update_draft_payload failed: {e}")
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def mark_approved(draft_id: int, committed_resource_id: Optional[int]) -> bool:
    conn = _connect()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE SaigeDrafts
               SET Status = 'approved',
                   CommittedResourceID = %s,
                   ApprovedAt = GETUTCDATE(),
                   UpdatedAt = GETUTCDATE()
             WHERE DraftID = %s AND Status = 'pending'
            """,
            (int(committed_resource_id) if committed_resource_id else None, int(draft_id)),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def mark_rejected(draft_id: int, reason: Optional[str] = None) -> bool:
    conn = _connect()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE SaigeDrafts
               SET Status = 'rejected',
                   RejectedAt = GETUTCDATE(),
                   UpdatedAt = GETUTCDATE(),
                   RejectionReason = %s
             WHERE DraftID = %s AND Status = 'pending'
            """,
            ((reason or "")[:500] or None, int(draft_id)),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _row_to_draft(row) -> Dict[str, Any]:
    if not row:
        return {}
    def g(k):
        return row.get(k) or row.get(k.lower())
    payload_raw = g("PayloadJSON") or "{}"
    try:
        payload = json.loads(payload_raw)
    except Exception:
        payload = {}
    return {
        "DraftID":             g("DraftID"),
        "PeopleID":            g("PeopleID"),
        "BusinessID":          g("BusinessID"),
        "DraftType":           g("DraftType"),
        "Payload":             payload,
        "Status":              g("Status"),
        "Summary":             g("Summary"),
        "CommittedResourceID": g("CommittedResourceID"),
        "CreatedAt":           str(g("CreatedAt")) if g("CreatedAt") else None,
        "UpdatedAt":           str(g("UpdatedAt")) if g("UpdatedAt") else None,
        "ApprovedAt":          str(g("ApprovedAt")) if g("ApprovedAt") else None,
        "RejectedAt":          str(g("RejectedAt")) if g("RejectedAt") else None,
        "RejectionReason":     g("RejectionReason"),
    }


# ---------------------------------------------------------------------------
# @tool functions (LLM-facing)
# ---------------------------------------------------------------------------

@tool
def draft_produce_listing_tool(
    ingredient_name: str = "",
    quantity: float = 0.0,
    measurement: str = "",
    retail_price: float = 0.0,
    wholesale_price: float = 0.0,
    available_date: str = "",
    people_id: str = "",
    business_id: int = 0,
) -> str:
    """Draft a new produce listing for the farmer's marketplace inventory.
    Does NOT publish — it saves a pending draft that the farmer must approve
    from their Saige drafts panel. Use when the user says things like
    "list 3 dozen eggs at $5", "put my tomatoes on the marketplace", "add
    50 lbs of beef to my inventory". Capture: what they're selling
    (ingredient_name), how much (quantity + measurement like "lb", "dozen",
    "bushel"), the retail_price they want, and an available_date if given
    (ISO YYYY-MM-DD). people_id/business_id are injected from session state
    — do not guess them."""
    if not business_id or int(business_id) <= 0:
        return ("I can't draft a listing without knowing which business "
                "this is for. Open Saige from one of your business pages.")
    if not ingredient_name:
        return "Tell me what product you'd like to list (e.g., 'tomatoes')."
    payload = {
        "IngredientName":  str(ingredient_name).strip(),
        "Quantity":        float(quantity or 0),
        "Measurement":     str(measurement or "").strip(),
        "RetailPrice":     float(retail_price or 0),
        "WholesalePrice":  float(wholesale_price or 0) or None,
        "AvailableDate":   str(available_date or "").strip() or None,
        "BusinessID":      int(business_id),
    }
    qty_str = f"{payload['Quantity']:g}" if payload["Quantity"] else "?"
    price_str = f"${payload['RetailPrice']:.2f}" if payload["RetailPrice"] else "?"
    summary = (f"Produce: {qty_str} {payload['Measurement'] or 'unit'} "
               f"of {payload['IngredientName']} @ {price_str}")
    draft_id = _insert_draft(people_id or None, int(business_id), DRAFT_TYPE_PRODUCE, payload, summary)
    if draft_id is None:
        return "I couldn't save that draft. Please try again in a moment."
    return (f"Draft #{draft_id} saved: {summary}. Review and approve it in your "
            f"Saige drafts panel — nothing is published until you approve.")


@tool
def draft_event_tool(
    event_name: str = "",
    description: str = "",
    start_date: str = "",
    end_date: str = "",
    location_name: str = "",
    city: str = "",
    state: str = "",
    is_free: bool = True,
    registration_required: bool = False,
    people_id: str = "",
    business_id: int = 0,
) -> str:
    """Draft a new event (farm tour, fleece show, workshop, open-farm day,
    etc.) for the farmer's Oatmeal Farm Network listing. Does NOT publish —
    a pending draft is saved for the farmer to approve. Use when the user
    says "plan a farm tour next Saturday", "create an open-ranch event",
    "add a shearing workshop". Capture event_name, description, start_date
    / end_date (ISO), location_name + city + state, and whether it's free
    or requires registration. people_id/business_id injected from state."""
    if not business_id or int(business_id) <= 0:
        return "I can't draft an event without knowing which business hosts it."
    if not event_name:
        return "Tell me the event name (e.g., 'Spring Farm Tour')."
    payload = {
        "EventName":             str(event_name).strip(),
        "EventDescription":      str(description or "").strip(),
        "EventStartDate":        str(start_date or "").strip() or None,
        "EventEndDate":          str(end_date or "").strip() or None,
        "EventLocationName":     str(location_name or "").strip() or None,
        "EventLocationCity":     str(city or "").strip() or None,
        "EventLocationState":    str(state or "").strip() or None,
        "IsFree":                1 if bool(is_free) else 0,
        "RegistrationRequired":  1 if bool(registration_required) else 0,
        "IsPublished":           0,
        "BusinessID":            int(business_id),
        "PeopleID":              str(people_id) if people_id else None,
    }
    when = payload["EventStartDate"] or "tbd"
    summary = f"Event: {payload['EventName']} on {when}"
    draft_id = _insert_draft(people_id or None, int(business_id), DRAFT_TYPE_EVENT, payload, summary)
    if draft_id is None:
        return "I couldn't save that event draft."
    return (f"Draft #{draft_id} saved: {summary}. Approve it in your Saige "
            f"drafts panel to publish the event.")


@tool
def draft_blog_post_tool(
    title: str = "",
    content: str = "",
    category: str = "",
    people_id: str = "",
    business_id: int = 0,
) -> str:
    """Draft a blog post for the farmer's business blog. Does NOT publish —
    it's saved as a pending draft. Use when the user says "write a blog
    post about lambing season", "draft an article on cover crops", "post
    an update about the new kid". Capture title, content (the body — can
    be long, include paragraphs), and category if they specify one.
    people_id/business_id injected from state."""
    if not business_id or int(business_id) <= 0:
        return "I can't draft a blog post without knowing which business it's for."
    if not title:
        return "Give me a title for the post."
    if not content or len(content.strip()) < 20:
        return "Share a bit more content for the post (at least a couple sentences)."
    payload = {
        "Title":       str(title).strip(),
        "Content":     str(content).strip(),
        "Category":    str(category or "").strip() or None,
        "BusinessID":  int(business_id),
        "IsPublished": 0,
    }
    summary = f"Blog: {payload['Title'][:120]}"
    draft_id = _insert_draft(people_id or None, int(business_id), DRAFT_TYPE_BLOG, payload, summary)
    if draft_id is None:
        return "I couldn't save that blog draft."
    return (f"Draft #{draft_id} saved: {summary}. Review and publish it from "
            f"your Saige drafts panel when ready.")


@tool
def draft_meat_listing_tool(
    ingredient_name: str = "",
    cut: str = "",
    quantity: float = 0.0,
    weight_unit: str = "lb",
    retail_price: float = 0.0,
    wholesale_price: float = 0.0,
    available_date: str = "",
    people_id: str = "",
    business_id: int = 0,
) -> str:
    """Draft a new meat inventory listing for the farmer's marketplace.
    Does NOT publish — saves a pending draft for the farmer to approve.
    Use when the user says "list 50 lbs of ground beef at $8/lb", "put my
    lamb chops on the marketplace", "add pork loin to my meat inventory".
    Capture: ingredient_name (e.g. 'beef', 'lamb', 'pork'), optional cut
    (e.g. 'ground', 'ribeye', 'whole'), quantity + weight_unit (lb/kg/oz),
    retail_price, optional wholesale_price and available_date (YYYY-MM-DD).
    people_id/business_id injected from session state."""
    if not business_id or int(business_id) <= 0:
        return "I can't draft a listing without knowing which business this is for."
    if not ingredient_name:
        return "Tell me what meat you'd like to list (e.g., 'beef', 'lamb', 'pork')."
    payload = {
        "IngredientName": str(ingredient_name).strip(),
        "Cut":            str(cut or "").strip() or None,
        "Quantity":       float(quantity or 0),
        "WeightUnit":     str(weight_unit or "lb").strip(),
        "RetailPrice":    float(retail_price or 0),
        "WholesalePrice": float(wholesale_price or 0) or None,
        "AvailableDate":  str(available_date or "").strip() or None,
        "BusinessID":     int(business_id),
    }
    cut_str   = f" {payload['Cut']}" if payload["Cut"] else ""
    qty_str   = f"{payload['Quantity']:g} {payload['WeightUnit']} of "
    price_str = f"${payload['RetailPrice']:.2f}/{payload['WeightUnit']}" if payload["RetailPrice"] else "?"
    summary   = f"Meat: {qty_str}{payload['IngredientName']}{cut_str} @ {price_str}"
    draft_id  = _insert_draft(people_id or None, int(business_id), DRAFT_TYPE_MEAT, payload, summary)
    if draft_id is None:
        return "I couldn't save that draft. Please try again in a moment."
    return (f"Draft #{draft_id} saved: {summary}. Review and approve it in your "
            f"Saige drafts panel — nothing is published until you approve.")


@tool
def draft_processed_food_listing_tool(
    name: str = "",
    quantity: float = 0.0,
    retail_price: float = 0.0,
    wholesale_price: float = 0.0,
    is_organic: bool = False,
    is_local: bool = True,
    notes: str = "",
    people_id: str = "",
    business_id: int = 0,
) -> str:
    """Draft a new processed / artisan food product listing for the marketplace.
    Does NOT publish — saves a pending draft for the farmer to approve.
    Use when the user says "list my strawberry jam at $7 a jar", "add our
    sourdough bread to the marketplace", "put my goat cheese on sale".
    Capture: product name, quantity (number of units available), retail_price,
    optional wholesale_price, whether it's certified organic (is_organic) and/or
    locally produced (is_local). people_id/business_id injected from state."""
    if not business_id or int(business_id) <= 0:
        return "I can't draft a listing without knowing which business this is for."
    if not name:
        return "Tell me what product you'd like to list (e.g., 'strawberry jam')."
    payload = {
        "Name":           str(name).strip(),
        "Quantity":       float(quantity or 0),
        "RetailPrice":    float(retail_price or 0),
        "WholesalePrice": float(wholesale_price or 0) or None,
        "IsOrganic":      1 if is_organic else 0,
        "IsLocal":        1 if is_local else 0,
        "Notes":          str(notes or "").strip() or None,
        "BusinessID":     int(business_id),
    }
    qty_str   = f"{payload['Quantity']:g} unit(s) of " if payload["Quantity"] else ""
    price_str = f"${payload['RetailPrice']:.2f}" if payload["RetailPrice"] else "?"
    tags      = (["organic"] if payload["IsOrganic"] else []) + (["local"] if payload["IsLocal"] else [])
    tag_str   = f" [{', '.join(tags)}]" if tags else ""
    summary   = f"Food: {qty_str}{payload['Name']}{tag_str} @ {price_str}"
    draft_id  = _insert_draft(people_id or None, int(business_id), DRAFT_TYPE_PROCESSED_FOOD, payload, summary)
    if draft_id is None:
        return "I couldn't save that draft. Please try again in a moment."
    return (f"Draft #{draft_id} saved: {summary}. Review and approve it in your "
            f"Saige drafts panel — nothing is published until you approve.")


actions_tools = [
    draft_produce_listing_tool,
    draft_meat_listing_tool,
    draft_processed_food_listing_tool,
    draft_event_tool,
    draft_blog_post_tool,
]
