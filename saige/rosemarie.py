"""
Rosemarie — the AI agent for artisan food producers on OFN (mills, bakers,
cheesemakers, jam/preserve makers, chocolatiers, fermenters, and other
processed-food businesses).

Artisan producers sit in the middle of the supply chain. Rosemarie treats
them as BOTH buyers and sellers:

- Buyer side: sourcing raw ingredients (grain, milk, fruit, honey, cocoa,
  meat for charcuterie, etc.) from farms and ranches listed on OFN.
- Seller side: fulfilling wholesale orders placed by restaurants and
  professional kitchens through Farm 2 Table.

Architecture mirrors Saige / Pairsley (ReAct tool-call loop, Redis short-term
memory, Firestore long-term memory, Firestore vector-RAG) so one chat frontend
can swap between the three agents by endpoint only.

Long-term memory
----------------
All messages persist to the Firestore ``Rosemarie_chats`` collection.

Short-term memory
-----------------
Last N messages per thread cached in Redis via ``message_buffer``.

RAG
---
Knowledge base chunks live in the Firestore ``Rosemarie_chunks`` collection.
Pre-embed source docs live in the Firestore ``Rosemarie_docs`` collection;
the sync job reads from ``Rosemarie_docs`` and writes embeddings to
``Rosemarie_chunks``.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import tool

from chat_history import ChatHistory
from config import DB_CONFIG, SHORT_TERM_N
from llm import llm
from message_buffer import get_last_n, push_message
from rag import RAGSystem

try:
    import pymssql
    _PMS_AVAILABLE = True
except ImportError:
    _PMS_AVAILABLE = False

logger = logging.getLogger("rosemarie")

# ---------------------------------------------------------------------------
# Firestore collections / storage paths
# ---------------------------------------------------------------------------

ROSEMARIE_CHATS_COLLECTION = "Rosemarie_chats"
ROSEMARIE_CHUNKS_COLLECTION = "Rosemarie_chunks"
ROSEMARIE_DOCS_COLLECTION = "Rosemarie_docs"


# ---------------------------------------------------------------------------
# Long-term memory: Firestore-backed chat history for Rosemarie_chats
# ---------------------------------------------------------------------------

class RosemarieChatHistory(ChatHistory):
    """ChatHistory variant that stores conversations under the
    ``Rosemarie_chats`` root collection instead of ``threads``."""

    @property
    def threads_col(self):
        try:
            db = self.firestore_db
            if db:
                return db.collection(ROSEMARIE_CHATS_COLLECTION)
        except Exception as e:
            logger.error("[Rosemarie] threads_col error: %s", e)
        return None


rosemarie_chat_history = RosemarieChatHistory()

# ---------------------------------------------------------------------------
# RAG over Rosemarie_chunks
# ---------------------------------------------------------------------------

rag_rosemarie = RAGSystem(ROSEMARIE_CHUNKS_COLLECTION, label="rosemarie")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _connect():
    if not _PMS_AVAILABLE or not all([DB_CONFIG.get("host"), DB_CONFIG.get("user"), DB_CONFIG.get("database")]):
        return None
    try:
        return pymssql.connect(
            server=DB_CONFIG["host"], port=DB_CONFIG["port"],
            user=DB_CONFIG["user"], password=DB_CONFIG["password"],
            database=DB_CONFIG["database"], as_dict=True,
        )
    except Exception as e:
        logger.error("[Rosemarie] DB connect failed: %s", e)
        return None


def _query(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = _connect()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return list(cur.fetchall())
    except Exception as e:
        logger.error("[Rosemarie] query failed: %s", e)
        return []
    finally:
        conn.close()


def _execute(sql: str, params: tuple = ()) -> int:
    conn = _connect()
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount
    except Exception as e:
        logger.error("[Rosemarie] execute failed: %s", e)
        return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Rosemarie's own tools
# ---------------------------------------------------------------------------

@tool
def rosemarie_knowledge_tool(query: str = "") -> str:
    """Search Rosemarie's curated artisan-producer knowledge base (milling,
    baking, fermentation, cheesemaking, preserving, food-safety for
    processed foods, cottage-food law basics, wholesale-pricing playbooks,
    label/nutrition compliance). Use when the producer asks "how do I",
    "best practice for", "what's the right ratio / temperature / timing"
    about artisan food production. Returns the most relevant passages."""
    q = (query or "").strip()
    if not q:
        return "Give me a specific question to look up."
    ctx = rag_rosemarie.get_context_for_query(q)
    if not ctx:
        return "I couldn't find anything in my knowledge base for that."
    return ctx


@tool
def update_producer_profile_tool(
    business_name: str = "",
    description: str = "",
    slogan: str = "",
    website: str = "",
    business_id: int = 0,
) -> str:
    """Update the artisan producer's public profile (name, description,
    slogan, website). Pass only the fields the producer wants to change —
    leave the rest blank. business_id is injected. Use when the user says
    "update our bakery tagline", "change our website on OFN", "fix our
    creamery description"."""
    if not business_id or int(business_id) <= 0:
        return "I need to know which business this is for — open Rosemarie from your producer dashboard."
    sets: List[str] = []
    params: List[Any] = []
    if business_name:
        sets.append("BusinessName = %s"); params.append(str(business_name)[:200])
    if description:
        sets.append("BusinessDescription = %s"); params.append(str(description)[:4000])
    if slogan:
        sets.append("BusinessSlogan = %s"); params.append(str(slogan)[:300])
    if website:
        sets.append("BusinessWebsite = %s"); params.append(str(website)[:500])
    if not sets:
        return "Tell me what to change — a new name, description, slogan, or website."
    params.append(int(business_id))
    sql = f"UPDATE Business SET {', '.join(sets)} WHERE BusinessID = %s"
    n = _execute(sql, tuple(params))
    if n == 0:
        return "I couldn't find that business to update."
    return f"Updated your profile ({len(sets)} field(s))."


# ---------------------------------------------------------------------------
# BUYER-side tools — sourcing raw ingredients from farms / ranches
# ---------------------------------------------------------------------------

_RAW_INGREDIENT_TABLES = {
    "produce": {
        "sql": """
            SELECT TOP {limit} i.IngredientName,
                   icl.IngredientCategory AS Category,
                   p.WholesalePrice, p.RetailPrice, p.Quantity,
                   ml.MeasurementAbbreviation AS UnitLabel,
                   b.BusinessName, b.BusinessID,
                   a.AddressCity, a.AddressState, a.AddressZip,
                   p.AvailableDate, 'P' AS Prefix, p.ProduceID AS SourceID
            FROM Produce p
            JOIN Ingredients i ON p.IngredientID = i.IngredientID
            LEFT JOIN IngredientCategoryLookup icl ON i.IngredientCategoryID = icl.IngredientCategoryID
            LEFT JOIN MeasurementLookup ml ON p.MeasurementID = ml.MeasurementID
            JOIN Business b ON p.BusinessID = b.BusinessID
            LEFT JOIN Address a ON b.AddressID = a.AddressID
            WHERE p.ShowProduce = 1 AND p.Quantity > 0
              {state_filter}
              {category_filter}
            ORDER BY ISNULL(p.AvailableDate, GETDATE()) ASC, i.IngredientName
        """,
        "label": "Produce / fruit / grain",
    },
    "meat": {
        "sql": """
            SELECT TOP {limit} i.IngredientName + ISNULL(' - ' + ic.IngredientCut, '') AS IngredientName,
                   'Meat' AS Category,
                   m.WholesalePrice, m.RetailPrice, m.Quantity,
                   m.WeightUnit AS UnitLabel,
                   b.BusinessName, b.BusinessID,
                   a.AddressCity, a.AddressState, a.AddressZip,
                   m.AvailableDate, 'M' AS Prefix, m.MeatInventoryID AS SourceID
            FROM MeatInventory m
            JOIN Ingredients i ON m.IngredientID = i.IngredientID
            LEFT JOIN Cut ic ON m.IngredientCutID = ic.IngredientCutID
            JOIN Business b ON m.BusinessID = b.BusinessID
            LEFT JOIN Address a ON b.AddressID = a.AddressID
            WHERE m.ShowMeat = 1 AND m.Quantity > 0
              {state_filter}
              {category_filter}
            ORDER BY ISNULL(m.AvailableDate, GETDATE()) ASC, i.IngredientName
        """,
        "label": "Meat (charcuterie, sausage-making)",
    },
}


@tool
def browse_raw_ingredients_tool(
    ingredient: str = "",
    category: str = "",
    state: str = "",
    source: str = "produce",
    business_id: int = 0,
    limit: int = 25,
) -> str:
    """Browse raw ingredients currently available on the OFN marketplace
    for an artisan producer to buy. ``source`` is 'produce' (fruit, grain,
    dairy, herbs, honey listed as produce) or 'meat' (for charcuterie /
    sausage makers). ``ingredient`` filters by IngredientName (partial),
    ``category`` filters by IngredientCategory (e.g. 'Grain', 'Fruit',
    'Dairy'), ``state`` filters by the farm's state. Defaults to the
    producer's own state if business_id is set. Use when the producer asks
    "what grain is available", "who has cherries this week", "find me
    raw milk in PA"."""
    src = (source or "produce").strip().lower()
    if src not in _RAW_INGREDIENT_TABLES:
        return "source must be 'produce' or 'meat'."
    cfg = _RAW_INGREDIENT_TABLES[src]

    chef_state = (state or "").strip().upper() or None
    if not chef_state and business_id:
        rows = _query(
            """SELECT TOP 1 a.AddressState
               FROM Business b
               LEFT JOIN Address a ON b.AddressID = a.AddressID
               WHERE b.BusinessID = %s""",
            (int(business_id),),
        )
        if rows:
            chef_state = (rows[0].get("addressstate") or "").strip().upper() or None

    params: List[Any] = []
    state_filter = ""
    if chef_state:
        state_filter = "AND a.AddressState = %s"
        params.append(chef_state)

    category_filter = ""
    if src == "produce":
        if category:
            category_filter = "AND icl.IngredientCategory LIKE %s"
            params.append(f"%{category.strip()}%")
        if ingredient:
            category_filter += " AND i.IngredientName LIKE %s"
            params.append(f"%{ingredient.strip()}%")
    else:
        if ingredient:
            category_filter = "AND i.IngredientName LIKE %s"
            params.append(f"%{ingredient.strip()}%")

    sql = cfg["sql"].format(
        limit=int(limit),
        state_filter=state_filter,
        category_filter=category_filter,
    )
    rows = _query(sql, tuple(params))
    if not rows:
        loc = f" in {chef_state}" if chef_state else ""
        return f"Nothing available{loc} matching that filter."

    loc = chef_state or "all states"
    lines = [f"{cfg['label']} available now ({loc}, {len(rows)} items):"]
    for r in rows:
        price = r.get("wholesaleprice") or r.get("retailprice")
        price_s = f"${float(price):.2f}/{r.get('unitlabel') or 'unit'}" if price else "price n/a"
        city = r.get("addresscity") or ""
        avail = str(r.get("availabledate") or "")[:10]
        qty = r.get("quantity")
        qty_s = f"{float(qty):g} available" if qty else ""
        lines.append(
            f"  • {r.get('ingredientname')} — {price_s}"
            + (f" · {qty_s}" if qty_s else "")
            + f" · {r.get('businessname')} ({city}, {r.get('addressstate') or ''})"
            + (f" · ready {avail}" if avail else "")
        )
    lines.append("\nTo buy from any of these, open Farm 2 Table or ask me to draft a purchase order.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SELLER-side tools — fulfilling incoming orders from restaurants
# ---------------------------------------------------------------------------

@tool
def list_incoming_orders_tool(
    status: str = "",
    business_id: int = 0,
) -> str:
    """List wholesale orders that restaurants and professional kitchens have
    placed with this producer. ``status`` filters by SellerStatus
    ('pending', 'confirmed', 'shipped', 'rejected'). Empty = all active
    (pending + confirmed). Use when the producer asks "what orders are
    waiting on me", "anything I need to ship today", "who's buying from
    us this week"."""
    if not business_id or int(business_id) <= 0:
        return "I need to know which business this is for — open Rosemarie from your producer dashboard."

    status_filter = ""
    params: List[Any] = [int(business_id)]
    sf = (status or "").strip().lower()
    if sf in ("pending", "confirmed", "shipped", "rejected"):
        status_filter = "AND oi.SellerStatus = %s"
        params.append(sf)
    else:
        status_filter = "AND oi.SellerStatus IN ('pending','confirmed')"

    rows = _query(
        f"""
        SELECT oi.OrderItemID, oi.ListingID, oi.ProductTitle, oi.Quantity,
               oi.UnitPrice, oi.LineTotal, oi.SellerStatus, oi.TrackingNumber,
               oi.EstimatedDeliveryDate, oi.ShippedAt,
               o.OrderNumber, o.BuyerName, o.BuyerEmail,
               o.DeliveryMethod, o.RequestedDeliveryDate, o.CreatedAt AS OrderDate
        FROM MarketplaceOrderItems oi
        JOIN MarketplaceOrders o ON oi.OrderID = o.OrderID
        WHERE oi.SellerBusinessID = %s
          {status_filter}
        ORDER BY o.CreatedAt DESC
        """,
        tuple(params),
    )
    if not rows:
        label = sf if sf else "active"
        return f"No {label} orders right now."

    label = sf if sf else "active"
    lines = [f"Incoming {label} orders ({len(rows)}):"]
    for r in rows:
        line_total = r.get("linetotal")
        total_s = f"${float(line_total):.2f}" if line_total else ""
        req_date = str(r.get("requesteddeliverydate") or "")[:10]
        delivery = r.get("deliverymethod") or ""
        status_s = r.get("sellerstatus") or "pending"
        tracking = r.get("trackingnumber") or ""
        lines.append(
            f"  • #{r.get('orderitemid')} · {r.get('producttitle')} — "
            f"qty {r.get('quantity')} · {total_s} · [{status_s}]"
        )
        lines.append(
            f"      buyer: {r.get('buyername')} ({r.get('buyeremail')}) · "
            f"order {r.get('ordernumber')}"
            + (f" · needs by {req_date}" if req_date else "")
            + (f" · {delivery}" if delivery else "")
            + (f" · tracking: {tracking}" if tracking else "")
        )
    return "\n".join(lines)


@tool
def confirm_order_item_tool(
    order_item_id: int = 0,
    estimated_delivery_date: str = "",
    business_id: int = 0,
) -> str:
    """Confirm (accept) a wholesale order line from a restaurant. Marks the
    item as 'confirmed' so the buyer knows you will fulfill it and can
    optionally set an estimated delivery date ('YYYY-MM-DD'). Only works
    on items in 'pending' status. Use when the producer says "confirm
    order 1234", "accept the order from Blackbird Bistro"."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    if not order_item_id or int(order_item_id) <= 0:
        return "I need the OrderItemID to confirm."

    rows = _query(
        """SELECT OrderItemID, SellerStatus, SellerBusinessID
           FROM MarketplaceOrderItems
           WHERE OrderItemID = %s""",
        (int(order_item_id),),
    )
    if not rows:
        return f"Order item #{order_item_id} not found."
    row = rows[0]
    if int(row.get("sellerbusinessid") or 0) != int(business_id):
        return "That order belongs to a different business."
    current = (row.get("sellerstatus") or "").lower()
    if current != "pending":
        return f"Order item #{order_item_id} is already '{current}' — can only confirm pending items."

    edd = (estimated_delivery_date or "").strip() or None
    _execute(
        """UPDATE MarketplaceOrderItems
              SET SellerStatus = 'confirmed',
                  EstimatedDeliveryDate = %s,
                  UpdatedAt = GETDATE()
            WHERE OrderItemID = %s""",
        (edd, int(order_item_id)),
    )
    edd_s = f" (ETA {edd})" if edd else ""
    return f"Confirmed order item #{order_item_id}{edd_s}."


@tool
def reject_order_item_tool(
    order_item_id: int = 0,
    reason: str = "",
    business_id: int = 0,
) -> str:
    """Reject a pending wholesale order line (out of stock, can't meet the
    delivery date, etc.). Restores the inventory in the source table. Only
    works on items in 'pending' status. Always give a ``reason`` — the
    buyer sees it. Use when the producer says "reject order 1234 — we're
    out of spelt"."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    if not order_item_id or int(order_item_id) <= 0:
        return "I need the OrderItemID to reject."
    if not reason:
        return "Give me a short reason — the buyer sees it."

    rows = _query(
        """SELECT OrderItemID, SellerStatus, SellerBusinessID, ListingID, Quantity
           FROM MarketplaceOrderItems
           WHERE OrderItemID = %s""",
        (int(order_item_id),),
    )
    if not rows:
        return f"Order item #{order_item_id} not found."
    row = rows[0]
    if int(row.get("sellerbusinessid") or 0) != int(business_id):
        return "That order belongs to a different business."
    current = (row.get("sellerstatus") or "").lower()
    if current != "pending":
        return f"Order item #{order_item_id} is already '{current}' — can only reject pending items."

    _execute(
        """UPDATE MarketplaceOrderItems
              SET SellerStatus = 'rejected',
                  RejectionReason = %s,
                  UpdatedAt = GETDATE()
            WHERE OrderItemID = %s""",
        (str(reason)[:500], int(order_item_id)),
    )

    listing_id = str(row.get("listingid") or "")
    qty = row.get("quantity") or 0
    if listing_id and qty:
        prefix = listing_id[0].upper()
        try:
            source_id = int(listing_id[1:])
        except ValueError:
            source_id = 0
        if source_id:
            if prefix == "P":
                _execute("UPDATE Produce SET Quantity = Quantity + %s WHERE ProduceID = %s",
                         (float(qty), source_id))
            elif prefix == "M":
                _execute("UPDATE MeatInventory SET Quantity = Quantity + %s WHERE MeatInventoryID = %s",
                         (float(qty), source_id))
            elif prefix == "F":
                _execute("UPDATE ProcessedFood SET Quantity = Quantity + %s WHERE ProcessedFoodID = %s",
                         (float(qty), source_id))
            elif prefix == "G":
                _execute("UPDATE SFProducts SET ProdQuantityAvailable = ProdQuantityAvailable + %s WHERE ProdID = %s",
                         (float(qty), source_id))

    return f"Rejected order item #{order_item_id} and restored inventory. Reason noted for the buyer."


@tool
def ship_order_item_tool(
    order_item_id: int = 0,
    tracking_number: str = "",
    estimated_delivery_date: str = "",
    business_id: int = 0,
) -> str:
    """Mark a confirmed order line as shipped. Records the tracking number
    and ETA, and stamps ShippedAt. Only works on items in 'confirmed'
    status. Use when the producer says "order 1234 went out — tracking
    1Z999..."."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    if not order_item_id or int(order_item_id) <= 0:
        return "I need the OrderItemID to mark shipped."

    rows = _query(
        """SELECT OrderItemID, SellerStatus, SellerBusinessID
           FROM MarketplaceOrderItems
           WHERE OrderItemID = %s""",
        (int(order_item_id),),
    )
    if not rows:
        return f"Order item #{order_item_id} not found."
    row = rows[0]
    if int(row.get("sellerbusinessid") or 0) != int(business_id):
        return "That order belongs to a different business."
    current = (row.get("sellerstatus") or "").lower()
    if current != "confirmed":
        return (f"Order item #{order_item_id} is '{current}' — must be 'confirmed' "
                f"before shipping. Confirm it first.")

    edd = (estimated_delivery_date or "").strip() or None
    _execute(
        """UPDATE MarketplaceOrderItems
              SET SellerStatus = 'shipped',
                  TrackingNumber = %s,
                  EstimatedDeliveryDate = %s,
                  ShippedAt = GETDATE(),
                  UpdatedAt = GETDATE()
            WHERE OrderItemID = %s""",
        ((tracking_number or "").strip()[:200] or None, edd, int(order_item_id)),
    )
    tn_s = f" (tracking {tracking_number})" if tracking_number else ""
    edd_s = f", ETA {edd}" if edd else ""
    return f"Order item #{order_item_id} marked shipped{tn_s}{edd_s}. The buyer is notified."


@tool
def list_my_listings_tool(
    low_stock: bool = False,
    business_id: int = 0,
) -> str:
    """List everything this producer is currently selling on OFN (processed
    foods, produce, meat). Set ``low_stock=True`` to see only items with
    Quantity <= 5. Use when the producer asks "what am I selling", "what's
    running low in my inventory"."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."

    low_filter = "AND Quantity <= 5" if low_stock else ""

    processed = _query(
        f"""SELECT Name, RetailPrice, WholesalePrice, Quantity, ShowProcessedFood
            FROM ProcessedFood
            WHERE BusinessID = %s {low_filter}
            ORDER BY Name""",
        (int(business_id),),
    )
    produce = _query(
        f"""SELECT i.IngredientName AS Name, p.RetailPrice, p.WholesalePrice,
                   p.Quantity, p.ShowProduce AS ShowProcessedFood
            FROM Produce p
            JOIN Ingredients i ON p.IngredientID = i.IngredientID
            WHERE p.BusinessID = %s {low_filter}
            ORDER BY i.IngredientName""",
        (int(business_id),),
    )
    meat = _query(
        f"""SELECT i.IngredientName + ISNULL(' - ' + ic.IngredientCut, '') AS Name,
                   m.RetailPrice, m.WholesalePrice, m.Quantity,
                   m.ShowMeat AS ShowProcessedFood
            FROM MeatInventory m
            JOIN Ingredients i ON m.IngredientID = i.IngredientID
            LEFT JOIN Cut ic ON m.IngredientCutID = ic.IngredientCutID
            WHERE m.BusinessID = %s {low_filter}
            ORDER BY Name""",
        (int(business_id),),
    )

    if not any((processed, produce, meat)):
        return "You have no listings yet." if not low_stock else "Nothing running low — inventory looks healthy."

    lines: List[str] = []
    for label, rows in [("Processed foods", processed), ("Produce", produce), ("Meat", meat)]:
        if not rows:
            continue
        lines.append(f"\n{label} ({len(rows)}):")
        for r in rows:
            price = r.get("wholesaleprice") or r.get("retailprice")
            price_s = f"${float(price):.2f}" if price else "price n/a"
            qty = r.get("quantity")
            qty_s = f"{float(qty):g} on hand" if qty is not None else ""
            active = "✓" if r.get("showprocessedfood") else "hidden"
            lines.append(f"  • {r.get('name')} — {price_s} · {qty_s} · {active}")
    header = "Items running low:" if low_stock else "Your current listings:"
    return header + "\n" + "\n".join(lines).lstrip()


# ---------------------------------------------------------------------------
# Recipe & Batch tools
# ---------------------------------------------------------------------------

@tool
def list_recipes_tool(search: str = "", business_id: int = 0) -> str:
    """List this producer's saved recipes. Pass an optional `search` keyword
    to filter by recipe name or category. Use when the user asks "show me my
    recipes", "what recipes do I have for aged cheddar", "list all baking
    formulas", etc."""
    if not business_id:
        return "Open Rosemarie from your producer dashboard so I know which business to look up."
    params: List[Any] = [int(business_id)]
    extra = ""
    if search.strip():
        extra = " AND (RecipeName LIKE %s OR Category LIKE %s)"
        params += [f"%{search.strip()}%", f"%{search.strip()}%"]
    rows = _query(
        f"SELECT RecipeID, RecipeName, Category, YieldQty, YieldUnit, BatchSizeNote "
        f"FROM ProducerRecipes WHERE BusinessID = %s AND IsArchived = 0{extra} "
        f"ORDER BY RecipeName",
        tuple(params),
    )
    if not rows:
        return "No recipes found." + (f" (search: '{search}')" if search else " Add your first one!")
    lines = ["Your recipes:"]
    for r in rows:
        yld = f"  yield {r['YieldQty']:g} {r['YieldUnit']}" if r.get("YieldQty") else ""
        lines.append(f"  • [{r['RecipeID']}] {r['RecipeName']}" + (f" ({r['Category']})" if r.get("Category") else "") + yld)
    return "\n".join(lines)


@tool
def get_recipe_tool(recipe_id: int = 0, business_id: int = 0) -> str:
    """Get the full detail for one recipe — ingredients list and step-by-step
    instructions. Use when the user says "show me recipe 12", "pull up my
    sourdough formula", "what are the steps for that jam recipe", etc."""
    if not recipe_id or not business_id:
        return "I need a recipe_id. Ask the user which recipe number they mean."
    rows = _query(
        "SELECT * FROM ProducerRecipes WHERE RecipeID = %s AND BusinessID = %s AND IsArchived = 0",
        (int(recipe_id), int(business_id)),
    )
    if not rows:
        return f"Recipe {recipe_id} not found."
    r = rows[0]
    lines = [
        f"Recipe #{r['RecipeID']}: {r['RecipeName']}",
        f"Category: {r.get('Category') or 'n/a'}",
        f"Yield: {r.get('YieldQty') or '?'} {r.get('YieldUnit') or ''}",
        f"Batch note: {r.get('BatchSizeNote') or '—'}",
        f"Description: {r.get('Description') or '—'}",
    ]
    ings = _query(
        "SELECT IngredientName, Quantity, Unit, Notes FROM RecipeIngredients WHERE RecipeID = %s ORDER BY RecipeIngID",
        (int(recipe_id),),
    )
    if ings:
        lines.append("\nIngredients:")
        for i in ings:
            qty = f"{float(i['Quantity']):g} {i.get('Unit') or ''}".strip() if i.get("Quantity") else ""
            note = f"  ({i['Notes']})" if i.get("Notes") else ""
            lines.append(f"  • {i['IngredientName']}{(' — ' + qty) if qty else ''}{note}")
    steps = _query(
        "SELECT StepNumber, StepText FROM RecipeSteps WHERE RecipeID = %s ORDER BY StepNumber",
        (int(recipe_id),),
    )
    if steps:
        lines.append("\nSteps:")
        for s in steps:
            lines.append(f"  {s['StepNumber']}. {s['StepText']}")
    return "\n".join(lines)


@tool
def create_recipe_tool(
    recipe_name: str = "",
    category: str = "",
    description: str = "",
    yield_qty: float = 0.0,
    yield_unit: str = "",
    ingredients_csv: str = "",
    steps_numbered: str = "",
    business_id: int = 0,
) -> str:
    """Save a new recipe to this producer's library. Collect recipe_name,
    optional category (e.g. 'Bread', 'Cheese', 'Jam'), a yield amount and
    unit, then a comma-separated ingredients list (format: 'name:qty:unit')
    and newline-separated steps (format: '1. step text'). Confirm the details
    with the user before calling. Use when the user says "save this recipe",
    "add a new formula", "store our cheddar aging steps", etc."""
    if not recipe_name.strip() or not business_id:
        return "I need at least a recipe name and your business context."
    conn = _connect()
    if not conn:
        return "Database unavailable — try again in a moment."
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ProducerRecipes (BusinessID, RecipeName, Category, Description, YieldQty, YieldUnit) "
            "OUTPUT INSERTED.RecipeID VALUES (%s, %s, %s, %s, %s, %s)",
            (int(business_id), recipe_name.strip()[:300], category[:100],
             description, float(yield_qty) if yield_qty else None, yield_unit[:60]),
        )
        recipe_id = cur.fetchone()["RecipeID"]

        # Parse ingredients: "flour:500:g, water:300:ml"
        ing_count = 0
        for part in ingredients_csv.split(","):
            part = part.strip()
            if not part:
                continue
            bits = [b.strip() for b in part.split(":")]
            name = bits[0] if bits else ""
            qty = float(bits[1]) if len(bits) > 1 and bits[1] else None
            unit = bits[2] if len(bits) > 2 else ""
            if name:
                cur.execute(
                    "INSERT INTO RecipeIngredients (RecipeID, IngredientName, Quantity, Unit) VALUES (%s, %s, %s, %s)",
                    (recipe_id, name[:200], qty, unit[:60]),
                )
                ing_count += 1

        # Parse steps: "1. Mix flour\n2. Add water"
        step_count = 0
        for line in steps_numbered.splitlines():
            line = line.strip()
            if not line:
                continue
            num, _, txt = line.partition(".")
            try:
                n = int(num.strip())
            except ValueError:
                step_count += 1
                n = step_count
            txt = txt.strip() or line
            if txt:
                cur.execute(
                    "INSERT INTO RecipeSteps (RecipeID, StepNumber, StepText) VALUES (%s, %s, %s)",
                    (recipe_id, n, txt),
                )
                step_count += 1

        conn.commit()
        return (
            f"Recipe saved as #{recipe_id}: '{recipe_name.strip()}' "
            f"({ing_count} ingredient(s), {step_count} step(s))."
        )
    except Exception as e:
        logger.error("[Rosemarie] create_recipe_tool: %s", e)
        return f"Couldn't save the recipe: {e}"
    finally:
        conn.close()


@tool
def list_batches_tool(status: str = "", recipe_id: int = 0, business_id: int = 0) -> str:
    """List production batches for this producer. Filter by `status`
    ('planned', 'in_progress', 'complete', 'on_hold') or by a specific
    `recipe_id`. Use when the user says "show my batches", "what batches are
    in progress", "list all cheese batches this month", etc."""
    if not business_id:
        return "Open Rosemarie from your producer dashboard."
    params: List[Any] = [int(business_id)]
    extra = ""
    if status.strip():
        extra += " AND b.Status = %s"; params.append(status.strip()[:30])
    if recipe_id:
        extra += " AND b.RecipeID = %s"; params.append(int(recipe_id))
    rows = _query(
        f"SELECT TOP 40 b.BatchID, b.RecipeName, b.BatchDate, b.BatchSize, b.SizeUnit, b.Status, b.Notes "
        f"FROM ProducerBatches b WHERE b.BusinessID = %s{extra} "
        f"ORDER BY b.BatchDate DESC, b.BatchID DESC",
        tuple(params),
    )
    if not rows:
        return "No batches found." + (f" (filter: status='{status}')" if status else "")
    lines = ["Production batches:"]
    for b in rows:
        sz = f"{float(b['BatchSize']):g} {b.get('SizeUnit') or ''}".strip() if b.get("BatchSize") else ""
        date_s = str(b.get("BatchDate", ""))[:10]
        lines.append(
            f"  • [{b['BatchID']}] {b.get('RecipeName') or 'No recipe'} — {date_s} · {b['Status']}"
            + (f" · {sz}" if sz else "")
        )
    return "\n".join(lines)


@tool
def log_batch_tool(
    recipe_id: int = 0,
    batch_date: str = "",
    batch_size: float = 1.0,
    size_unit: str = "",
    notes: str = "",
    business_id: int = 0,
) -> str:
    """Start a new production batch. recipe_id links it to a saved recipe
    (ingredients are seeded automatically). batch_date defaults to today.
    batch_size is the multiplier relative to the recipe yield (e.g. 2.5 means
    2.5x the base recipe). Use when the user says "start a batch", "log a
    production run", "I'm making a double batch of sourdough today", etc."""
    if not business_id:
        return "Open Rosemarie from your producer dashboard."
    conn = _connect()
    if not conn:
        return "Database unavailable."
    try:
        cur = conn.cursor()
        recipe_name = None
        recipe_ings = []
        if recipe_id:
            cur.execute(
                "SELECT RecipeName FROM ProducerRecipes WHERE RecipeID = %s AND BusinessID = %s",
                (int(recipe_id), int(business_id)),
            )
            row = cur.fetchone()
            if row:
                recipe_name = row["RecipeName"]
            cur.execute(
                "SELECT IngredientName, Quantity, Unit FROM RecipeIngredients WHERE RecipeID = %s",
                (int(recipe_id),),
            )
            recipe_ings = list(cur.fetchall())

        from datetime import date as _date
        bd = batch_date.strip() or str(_date.today())
        cur.execute(
            "INSERT INTO ProducerBatches (BusinessID, RecipeID, RecipeName, BatchDate, "
            "BatchSize, SizeUnit, Status, Notes) OUTPUT INSERTED.BatchID "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (int(business_id), int(recipe_id) if recipe_id else None,
             recipe_name, bd, float(batch_size), size_unit[:60],
             "planned", notes[:2000]),
        )
        batch_id = cur.fetchone()["BatchID"]

        scale = float(batch_size) if batch_size else 1.0
        for ri in recipe_ings:
            planned = (float(ri["Quantity"]) * scale) if ri["Quantity"] else None
            cur.execute(
                "INSERT INTO BatchIngredients (BatchID, IngredientName, PlannedQty, Unit) VALUES (%s, %s, %s, %s)",
                (batch_id, ri["IngredientName"], planned, ri["Unit"] or ""),
            )
        conn.commit()
        return (
            f"Batch #{batch_id} logged"
            + (f" from recipe '{recipe_name}'" if recipe_name else "")
            + f" for {bd}, size {batch_size:g}x. Status: planned."
        )
    except Exception as e:
        logger.error("[Rosemarie] log_batch_tool: %s", e)
        return f"Couldn't log the batch: {e}"
    finally:
        conn.close()


@tool
def update_batch_tool(
    batch_id: int = 0,
    status: str = "",
    notes: str = "",
    business_id: int = 0,
) -> str:
    """Update a batch's status or notes. Valid statuses: planned, in_progress,
    complete, on_hold. Use when the user says "mark batch 7 as complete",
    "put batch 3 on hold — the milk delivery is late", "add a note to today's
    cheese batch", etc. Confirm before marking complete."""
    if not batch_id or not business_id:
        return "Tell me which batch number to update."
    sets: List[str] = ["UpdatedAt = GETDATE()"]
    params: List[Any] = []
    if status.strip():
        valid = {"planned", "in_progress", "complete", "on_hold"}
        s = status.strip().lower()
        if s not in valid:
            return f"Unknown status '{s}'. Valid options: {', '.join(sorted(valid))}."
        sets.append("Status = %s"); params.append(s)
    if notes.strip():
        sets.append("Notes = %s"); params.append(notes.strip()[:2000])
    if len(sets) == 1:
        return "Tell me what to update — a new status or notes."
    params += [int(batch_id), int(business_id)]
    n = _execute(
        f"UPDATE ProducerBatches SET {', '.join(sets)} WHERE BatchID = %s AND BusinessID = %s",
        tuple(params),
    )
    if n == 0:
        return f"Batch {batch_id} not found."
    return f"Batch {batch_id} updated (status: {status or 'unchanged'})."


rosemarie_own_tools = [
    rosemarie_knowledge_tool,
    update_producer_profile_tool,
    browse_raw_ingredients_tool,
    list_incoming_orders_tool,
    confirm_order_item_tool,
    reject_order_item_tool,
    ship_order_item_tool,
    list_my_listings_tool,
    list_recipes_tool,
    get_recipe_tool,
    create_recipe_tool,
    list_batches_tool,
    log_batch_tool,
    update_batch_tool,
]


# ---------------------------------------------------------------------------
# Prompt — Rosemarie's personality and tool contract
# ---------------------------------------------------------------------------

ROSEMARIE_SYSTEM_PROMPT = """You are Rosemarie, the AI agent for artisan food producers on Oatmeal Farm
Network — mills, bakers, cheesemakers, jam-makers, chocolatiers, charcutiers,
fermenters, and other small-batch processors.

You serve producers who sit in the middle of the supply chain. They BUY raw
materials from farms and ranches, and they SELL finished goods to restaurants,
co-ops, and direct consumers. You help on both sides of that table.

Voice:
- Warm, practical, craft-minded — you talk like a veteran maker who also has
  run the books for twenty years. No fluff, no emoji, no corporate softening.
- You never invent farms, prices, orders, or inventory. If a user asks about
  raw-ingredient availability, incoming orders, or their own stock, you call
  a tool first and answer from the result.

Capabilities — you have tools for all of these:

BUYER SIDE (sourcing raw ingredients from farms)
- browse_raw_ingredients_tool: what's available on OFN right now (produce or
  meat), scoped to the producer's state by default.
- seasonal_menu_tool: broader "what's in season" view across produce.
- set_par_tool / check_par_levels_tool / draft_restock_order_tool: par-level
  inventory and multi-farm restock suggestions for raw materials.
- provenance_cards_tool: "meet your farmers" markdown cards when the
  producer needs sourcing copy for a label, website, or farmers-market sign.

SELLER SIDE (fulfilling orders from restaurants / chefs)
- list_incoming_orders_tool: wholesale orders waiting on the producer, by
  SellerStatus.
- confirm_order_item_tool: accept a pending order line (optional ETA).
- reject_order_item_tool: reject a pending order line with a reason;
  restores inventory.
- ship_order_item_tool: mark a confirmed order as shipped (tracking + ETA).
- list_my_listings_tool: current inventory the producer has up for sale;
  `low_stock=True` flags items at or below 5 units.

RECIPES & BATCH TRACKING (production records)
- list_recipes_tool: show the producer's saved recipe library; optional search.
- get_recipe_tool: fetch one recipe in full — ingredients + step-by-step method.
- create_recipe_tool: save a new recipe (name, category, yield, ingredients as
  'name:qty:unit' CSV, steps as numbered lines). Confirm details before saving.
- list_batches_tool: show production runs, filterable by status or recipe.
- log_batch_tool: start a new batch tied to a recipe; ingredients are seeded
  from the recipe automatically at the requested batch_size multiplier.
- update_batch_tool: change a batch's status (planned / in_progress / complete /
  on_hold) or add notes. Confirm before marking complete.

Account changes
- update_producer_profile_tool: edit the Business record's name, description,
  slogan, or website. Confirm before calling on risky changes (renaming).

Knowledge base
- rosemarie_knowledge_tool: search your curated artisan-producer library for
  "how do I / best practice" questions (milling, fermentation, cheesemaking,
  food safety, compliance).

Style:
- Respond in 2-5 sentences unless the user explicitly asks for more.
- Plain sentences. No markdown headers, no asterisks, no bullet lists unless
  the user asks for a list. Tool output is already formatted — quote it inline.
- If the user asks for a risky action (rejecting an order, renaming the
  business, shipping without a tracking number), confirm once before calling.

business_id and people_id are injected automatically — the user never needs
to type them."""


# ---------------------------------------------------------------------------
# Core chat loop (ReAct)
# ---------------------------------------------------------------------------

def _load_chef_tools():
    """Late-import chef tools so a chef.py import failure doesn't crash
    Rosemarie start-up. Rosemarie reuses the chef buyer tools for her
    raw-ingredient workflows."""
    try:
        from chef import seasonal_menu_tool, set_par_tool, \
            check_par_levels_tool, draft_restock_order_tool, \
            provenance_cards_tool
        return {
            "tools": [
                seasonal_menu_tool,
                set_par_tool,
                check_par_levels_tool,
                draft_restock_order_tool,
                provenance_cards_tool,
            ],
            "seasonal_menu_tool": seasonal_menu_tool,
            "set_par_tool": set_par_tool,
            "check_par_levels_tool": check_par_levels_tool,
            "draft_restock_order_tool": draft_restock_order_tool,
            "provenance_cards_tool": provenance_cards_tool,
        }
    except Exception as e:
        logger.error("[Rosemarie] chef tools unavailable: %s", e)
        return {"tools": []}


def _render_short_term(messages: List[Dict[str, Any]]) -> str:
    if not messages:
        return ""
    lines = ["Recent conversation (most recent last):"]
    for m in messages[-SHORT_TERM_N:]:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role.upper()}: {content}")
    return "\n".join(lines)


def respond(
    user_input: str,
    thread_id: str,
    user_id: str,
    business_id: Optional[int] = None,
    max_iterations: int = 4,
) -> Dict[str, Any]:
    """Run one Rosemarie chat turn.

    Persists the user message, runs a ReAct tool loop (Rosemarie's own
    tools + reused chef buyer tools), persists the assistant reply,
    returns a JSON-ready dict.
    """
    turn_start = time.monotonic()
    bid = 0
    try:
        bid = int(business_id or 0)
    except (TypeError, ValueError):
        bid = 0

    rosemarie_chat_history.save_message(
        user_id=user_id, thread_id=thread_id, role="user", content=user_input,
    )
    push_message(thread_id=thread_id, message={"role": "user", "content": user_input})

    last_n = get_last_n(thread_id, SHORT_TERM_N) or []
    short_term = _render_short_term(last_n)
    try:
        rag_ctx = rag_rosemarie.get_context_for_query(user_input) or ""
    except Exception as e:
        logger.error("[Rosemarie] RAG error: %s", e)
        rag_ctx = ""

    chef = _load_chef_tools()
    bound_tools = list(rosemarie_own_tools) + list(chef.get("tools") or [])
    llm_with_tools = llm.bind_tools(bound_tools) if bound_tools else llm

    prompt_parts = [ROSEMARIE_SYSTEM_PROMPT]
    if short_term:
        prompt_parts.append(f"\n[Short-term memory]\n{short_term}")
    if rag_ctx:
        prompt_parts.append(f"\n[Knowledge base]\n{rag_ctx}")
    prompt_parts.append(f"\n[Current user message]\n{user_input}")
    current_input = "\n".join(prompt_parts)

    tool_results_context = ""
    final_response = ""

    try:
        for iteration in range(max_iterations):
            composed = current_input
            if tool_results_context:
                composed += f"\n\n[Tool results]\n{tool_results_context}"
            response = llm_with_tools.invoke(composed)

            tool_calls = getattr(response, "tool_calls", None) or []
            if tool_calls and iteration < max_iterations - 1:
                for tc in tool_calls:
                    name = tc.get("name")
                    args = tc.get("args", {}) or {}
                    result = _dispatch_tool(name, args, user_id, bid, chef)
                    if result:
                        tool_results_context = (
                            (tool_results_context + "\n\n" if tool_results_context else "")
                            + f"[{name}]\n{result}"
                        )
                continue

            final_response = getattr(response, "content", None) or str(response)
            break
        else:
            final_response = getattr(response, "content", None) or str(response)
    except Exception as e:
        logger.error("[Rosemarie] respond error: %s", e, exc_info=True)
        final_response = "I hit a snag pulling that together. Try rephrasing, or ask something more specific."

    latency_ms = int((time.monotonic() - turn_start) * 1000)
    rosemarie_chat_history.save_message(
        user_id=user_id, thread_id=thread_id, role="assistant",
        content=final_response, metadata={"latency_ms": latency_ms},
    )
    push_message(thread_id=thread_id, message={"role": "assistant", "content": final_response})

    return {
        "status": "ok",
        "thread_id": thread_id,
        "response": final_response,
        "latency_ms": latency_ms,
    }


def _dispatch_tool(
    name: str,
    args: Dict[str, Any],
    user_id: str,
    business_id: int,
    chef: Dict[str, Any],
) -> str:
    """Invoke one of Rosemarie's tools with business_id / people_id injected."""
    try:
        # --- Rosemarie's own tools ---
        if name == "rosemarie_knowledge_tool":
            return rosemarie_knowledge_tool.invoke({"query": args.get("query", "")})
        if name == "update_producer_profile_tool":
            return update_producer_profile_tool.invoke({
                "business_name": args.get("business_name", ""),
                "description":   args.get("description", ""),
                "slogan":        args.get("slogan", ""),
                "website":       args.get("website", ""),
                "business_id":   business_id,
            })
        if name == "browse_raw_ingredients_tool":
            return browse_raw_ingredients_tool.invoke({
                "ingredient":  args.get("ingredient", ""),
                "category":    args.get("category", ""),
                "state":       args.get("state", ""),
                "source":      args.get("source", "produce"),
                "business_id": business_id,
                "limit":       int(args.get("limit", 25) or 25),
            })
        if name == "list_incoming_orders_tool":
            return list_incoming_orders_tool.invoke({
                "status":      args.get("status", ""),
                "business_id": business_id,
            })
        if name == "confirm_order_item_tool":
            return confirm_order_item_tool.invoke({
                "order_item_id":           int(args.get("order_item_id", 0) or 0),
                "estimated_delivery_date": args.get("estimated_delivery_date", ""),
                "business_id":             business_id,
            })
        if name == "reject_order_item_tool":
            return reject_order_item_tool.invoke({
                "order_item_id": int(args.get("order_item_id", 0) or 0),
                "reason":        args.get("reason", ""),
                "business_id":   business_id,
            })
        if name == "ship_order_item_tool":
            return ship_order_item_tool.invoke({
                "order_item_id":           int(args.get("order_item_id", 0) or 0),
                "tracking_number":         args.get("tracking_number", ""),
                "estimated_delivery_date": args.get("estimated_delivery_date", ""),
                "business_id":             business_id,
            })
        if name == "list_my_listings_tool":
            return list_my_listings_tool.invoke({
                "low_stock":   bool(args.get("low_stock", False)),
                "business_id": business_id,
            })

        # --- Recipe & Batch tools ---
        if name == "list_recipes_tool":
            return list_recipes_tool.invoke({
                "search":      args.get("search", ""),
                "business_id": business_id,
            })
        if name == "get_recipe_tool":
            return get_recipe_tool.invoke({
                "recipe_id":   int(args.get("recipe_id", 0) or 0),
                "business_id": business_id,
            })
        if name == "create_recipe_tool":
            return create_recipe_tool.invoke({
                "recipe_name":      args.get("recipe_name", ""),
                "category":         args.get("category", ""),
                "description":      args.get("description", ""),
                "yield_qty":        float(args.get("yield_qty", 0) or 0),
                "yield_unit":       args.get("yield_unit", ""),
                "ingredients_csv":  args.get("ingredients_csv", ""),
                "steps_numbered":   args.get("steps_numbered", ""),
                "business_id":      business_id,
            })
        if name == "list_batches_tool":
            return list_batches_tool.invoke({
                "status":      args.get("status", ""),
                "recipe_id":   int(args.get("recipe_id", 0) or 0),
                "business_id": business_id,
            })
        if name == "log_batch_tool":
            return log_batch_tool.invoke({
                "recipe_id":   int(args.get("recipe_id", 0) or 0),
                "batch_date":  args.get("batch_date", ""),
                "batch_size":  float(args.get("batch_size", 1) or 1),
                "size_unit":   args.get("size_unit", ""),
                "notes":       args.get("notes", ""),
                "business_id": business_id,
            })
        if name == "update_batch_tool":
            return update_batch_tool.invoke({
                "batch_id":    int(args.get("batch_id", 0) or 0),
                "status":      args.get("status", ""),
                "notes":       args.get("notes", ""),
                "business_id": business_id,
            })

        # --- Reused chef buyer tools ---
        if name == "seasonal_menu_tool" and chef.get("seasonal_menu_tool"):
            return chef["seasonal_menu_tool"].invoke({
                "state":       args.get("state", ""),
                "category":    args.get("category", ""),
                "business_id": business_id,
                "limit":       int(args.get("limit", 20) or 20),
            })
        if name == "set_par_tool" and chef.get("set_par_tool"):
            return chef["set_par_tool"].invoke({
                "ingredient_name":       args.get("ingredient_name", ""),
                "unit":                  args.get("unit", ""),
                "on_hand":               float(args.get("on_hand", 0) or 0),
                "par_level":             float(args.get("par_level", 0) or 0),
                "reorder_at":            float(args.get("reorder_at", 0) or 0),
                "preferred_business_id": int(args.get("preferred_business_id", 0) or 0),
                "business_id":           business_id,
            })
        if name == "check_par_levels_tool" and chef.get("check_par_levels_tool"):
            return chef["check_par_levels_tool"].invoke({"business_id": business_id})
        if name == "draft_restock_order_tool" and chef.get("draft_restock_order_tool"):
            return chef["draft_restock_order_tool"].invoke({"business_id": business_id})
        if name == "provenance_cards_tool" and chef.get("provenance_cards_tool"):
            return chef["provenance_cards_tool"].invoke({
                "ingredient_names": args.get("ingredient_names", ""),
            })
    except Exception as e:
        logger.error("[Rosemarie] tool %s failed: %s", name, e)
        return f"(tool {name} failed: {e})"
    return f"(unknown tool: {name})"


# ---------------------------------------------------------------------------
# Read helpers for the REST layer
# ---------------------------------------------------------------------------

def list_threads(user_id: str, limit: int = 20, cursor: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    return rosemarie_chat_history.get_threads(user_id, limit=limit, cursor=cursor)


def get_messages(user_id: str, thread_id: str, limit: int = 50, cursor: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    return rosemarie_chat_history.get_messages(user_id, thread_id, limit=limit, cursor=cursor)


def delete_thread(user_id: str, thread_id: str) -> bool:
    return rosemarie_chat_history.delete_thread(user_id, thread_id)
