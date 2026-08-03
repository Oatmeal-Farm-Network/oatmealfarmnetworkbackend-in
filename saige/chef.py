"""
Chef/restaurant tools for Saige.

Four differentiators for farm-to-table operators buying through OFN:

  - save_recipe_tool(name, items): saves a recipe (name + list of
    ingredient lines) for later costing.
  - cost_recipe_tool(recipe_name): live plate-cost calculation — looks up
    each ingredient in the marketplace and returns per-line cost + total.
  - seasonal_menu_tool(state, category): what's actively listed in the OFN
    marketplace right now in a given state (optionally filtered by
    category). Drives "what's in season nearby" menu ideation.
  - set_par_tool / check_par_levels_tool / draft_restock_order_tool: chef
    inventory with par levels; below-threshold items roll up into a
    suggested multi-farm restock list with cheapest-match pricing.
  - provenance_cards_tool(ingredient_names): "meet your farmers" cards
    ready to drop into a menu or social post — pulls the farm profile for
    whichever OFN business currently supplies each ingredient.

Both the LLM and a Chef Dashboard frontend call these (the frontend hits
REST wrappers in api.py). All data is scoped to the chef's BusinessID,
injected from graph state — the LLM never guesses it.
"""
from __future__ import annotations

import json
from typing import Optional, List, Dict, Any
from langchain_core.tools import tool

from config import DB_CONFIG

try:
    import pymssql
    _PMS_AVAILABLE = True
except ImportError:
    _PMS_AVAILABLE = False


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
        print(f"[saige.chef] connect failed: {e}")
        return None


def _query(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = _connect()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall() or []
    except Exception as e:
        print(f"[saige.chef] query error: {e}")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _execute(sql: str, params: tuple = ()) -> int:
    """Execute INSERT/UPDATE/DELETE; returns rowcount or -1 on error."""
    conn = _connect()
    if conn is None:
        return -1
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount
    except Exception as e:
        print(f"[saige.chef] execute error: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return -1
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _insert_returning(sql: str, params: tuple = ()) -> Optional[int]:
    """Execute INSERT ... OUTPUT INSERTED.<PK> and return the PK."""
    conn = _connect()
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        conn.commit()
        if not row:
            return None
        for v in row.values():
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
        return None
    except Exception as e:
        print(f"[saige.chef] insert_returning error: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


_ENSURED = False

def _ensure_tables() -> bool:
    global _ENSURED
    if _ENSURED:
        return True
    conn = _connect()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ChefRecipes')
            CREATE TABLE ChefRecipes (
                RecipeID      INT IDENTITY(1,1) PRIMARY KEY,
                BusinessID    INT NOT NULL,
                Name          NVARCHAR(300) NOT NULL,
                PortionYield  INT NULL,
                ServingSize   NVARCHAR(100) NULL,
                MenuPrice     DECIMAL(10,2) NULL,
                Notes         NVARCHAR(MAX) NULL,
                CreatedAt     DATETIME NOT NULL DEFAULT GETUTCDATE(),
                UpdatedAt     DATETIME NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ChefRecipeItems')
            CREATE TABLE ChefRecipeItems (
                ItemID             INT IDENTITY(1,1) PRIMARY KEY,
                RecipeID           INT NOT NULL,
                IngredientName     NVARCHAR(200) NOT NULL,
                Quantity           DECIMAL(10,3) NULL,
                Unit               NVARCHAR(50) NULL,
                PreferredBusinessID INT NULL,
                Notes              NVARCHAR(500) NULL,
                SortOrder          INT NULL
            )
        """)
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ChefPar')
            CREATE TABLE ChefPar (
                ParID              INT IDENTITY(1,1) PRIMARY KEY,
                BusinessID         INT NOT NULL,
                IngredientName     NVARCHAR(200) NOT NULL,
                Unit               NVARCHAR(50) NULL,
                OnHand             DECIMAL(10,3) NULL,
                ParLevel           DECIMAL(10,3) NULL,
                ReorderAt          DECIMAL(10,3) NULL,
                PreferredBusinessID INT NULL,
                UpdatedAt          DATETIME NOT NULL DEFAULT GETUTCDATE()
            )
        """)
        conn.commit()
        _ENSURED = True
        return True
    except Exception as e:
        print(f"[saige.chef] ensure_tables failed: {e}")
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Marketplace price lookup
# ---------------------------------------------------------------------------

def _find_marketplace_match(
    ingredient_name: str,
    preferred_business_id: Optional[int] = None,
    state_filter: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return the best current listing for an ingredient string, preferring
    the chef's preferred farm (if set) else the lowest wholesale price.
    Pulls only from Produce + MeatInventory tables (the main farm outputs);
    ProcessedFood rarely has wholesale."""
    if not ingredient_name:
        return None
    like = f"%{ingredient_name.strip()}%"
    candidates: List[Dict[str, Any]] = []

    # Produce
    try:
        params: List[Any] = [like]
        sql = """
            SELECT TOP 10 'produce' AS ProductType, p.ProduceID AS SourceID,
                   p.BusinessID, i.IngredientName AS Title, p.WholesalePrice,
                   p.RetailPrice, p.Quantity, ml.MeasurementAbbreviation AS UnitLabel,
                   p.AvailableDate, b.BusinessName, a.AddressCity, a.AddressState
            FROM Produce p
            JOIN Ingredients i ON p.IngredientID = i.IngredientID
            LEFT JOIN MeasurementLookup ml ON p.MeasurementID = ml.MeasurementID
            JOIN Business b ON p.BusinessID = b.BusinessID
            LEFT JOIN Address a ON b.AddressID = a.AddressID
            WHERE p.ShowProduce = 1 AND p.Quantity > 0
              AND i.IngredientName LIKE %s
        """
        if state_filter:
            sql += " AND a.AddressState = %s"
            params.append(state_filter)
        sql += " ORDER BY ISNULL(p.WholesalePrice, p.RetailPrice) ASC"
        candidates.extend(_query(sql, tuple(params)))
    except Exception as e:
        print(f"[saige.chef] produce match failed: {e}")

    # Meat
    try:
        params = [like]
        sql = """
            SELECT TOP 10 'meat' AS ProductType, m.MeatID AS SourceID,
                   m.BusinessID, i.IngredientName + ISNULL(' ' + ic.IngredientCut, '') AS Title,
                   m.WholesalePrice, m.RetailPrice, m.Quantity,
                   ml.MeasurementAbbreviation AS UnitLabel,
                   m.AvailableDate, b.BusinessName, a.AddressCity, a.AddressState
            FROM MeatInventory m
            JOIN Ingredients i ON m.IngredientID = i.IngredientID
            LEFT JOIN IngredientCuts ic ON m.IngredientCutID = ic.IngredientCutID
            LEFT JOIN MeasurementLookup ml ON m.MeasurementID = ml.MeasurementID
            JOIN Business b ON m.BusinessID = b.BusinessID
            LEFT JOIN Address a ON b.AddressID = a.AddressID
            WHERE m.ShowMeat = 1 AND m.Quantity > 0
              AND (i.IngredientName LIKE %s OR ic.IngredientCut LIKE %s)
        """
        params.append(like)
        if state_filter:
            sql += " AND a.AddressState = %s"
            params.append(state_filter)
        sql += " ORDER BY ISNULL(m.WholesalePrice, m.RetailPrice) ASC"
        candidates.extend(_query(sql, tuple(params)))
    except Exception as e:
        print(f"[saige.chef] meat match failed: {e}")

    if not candidates:
        return None

    if preferred_business_id:
        preferred = [c for c in candidates if int(c.get("businessid") or 0) == int(preferred_business_id)]
        if preferred:
            return preferred[0]
    return candidates[0]


def _unit_price(row: Dict[str, Any]) -> Optional[float]:
    """Prefer wholesale; fall back to retail."""
    for k in ("wholesaleprice", "WholesalePrice", "retailprice", "RetailPrice"):
        v = row.get(k)
        if v is not None:
            try:
                f = float(v)
                if f > 0:
                    return f
            except (TypeError, ValueError):
                continue
    return None


# ---------------------------------------------------------------------------
# @tool: save_recipe_tool
# ---------------------------------------------------------------------------

@tool
def save_recipe_tool(
    name: str = "",
    items_json: str = "",
    portion_yield: int = 1,
    menu_price: float = 0.0,
    business_id: int = 0,
) -> str:
    """Save a recipe so it can be costed later. Pass the recipe name and a
    JSON-encoded list of ingredient lines as items_json, e.g.:
      '[{"ingredient":"ground beef","qty":0.33,"unit":"lb"},
        {"ingredient":"brioche bun","qty":1,"unit":"each"}]'
    portion_yield is how many plates this recipe makes (default 1).
    menu_price is the sale price per plate (for margin calculations).
    business_id is injected from session state."""
    if not business_id or int(business_id) <= 0:
        return "Open Saige from a restaurant business page so I know which kitchen this recipe is for."
    if not name:
        return "Give the recipe a name."
    try:
        items = json.loads(items_json) if items_json else []
    except json.JSONDecodeError:
        return "items_json must be a JSON array of {ingredient, qty, unit} objects."
    if not isinstance(items, list) or not items:
        return "Pass at least one ingredient line in items_json."
    if not _ensure_tables():
        return "Database not available."

    recipe_id = _insert_returning(
        """
        INSERT INTO ChefRecipes (BusinessID, Name, PortionYield, MenuPrice, CreatedAt)
        OUTPUT INSERTED.RecipeID
        VALUES (%s, %s, %s, %s, GETUTCDATE())
        """,
        (int(business_id), str(name)[:300], int(portion_yield or 1),
         float(menu_price) if menu_price else None),
    )
    if not recipe_id:
        return "Could not save the recipe."

    saved = 0
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        ing = str(item.get("ingredient") or item.get("name") or "").strip()
        if not ing:
            continue
        qty = item.get("qty") or item.get("quantity") or 0
        unit = str(item.get("unit") or "").strip()[:50]
        pref = item.get("preferred_business_id") or item.get("preferred_business") or None
        try:
            pref = int(pref) if pref else None
        except (TypeError, ValueError):
            pref = None
        _execute(
            """
            INSERT INTO ChefRecipeItems
                (RecipeID, IngredientName, Quantity, Unit, PreferredBusinessID, SortOrder)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (int(recipe_id), ing[:200], float(qty or 0) or None, unit, pref, i),
        )
        saved += 1

    return f"Saved recipe '{name}' (#{recipe_id}) with {saved} ingredient lines. Ask me to cost it any time."


# ---------------------------------------------------------------------------
# @tool: cost_recipe_tool
# ---------------------------------------------------------------------------

@tool
def cost_recipe_tool(recipe_name: str = "", business_id: int = 0) -> str:
    """Calculate the current live plate cost for a saved recipe. Looks up
    each ingredient in the OFN marketplace, prefers the line's preferred
    farm if set (otherwise cheapest wholesale), and returns a per-line
    breakdown plus total plate cost and margin vs the recipe's menu price.
    Use when the user asks "cost my burger", "what does the summer salad
    run now", "check my plate costs"."""
    if not business_id or int(business_id) <= 0:
        return "No restaurant business context set."
    if not recipe_name:
        return "Which recipe should I cost?"
    if not _ensure_tables():
        return "Database not available."
    recipes = _query(
        """
        SELECT TOP 1 RecipeID, Name, PortionYield, MenuPrice
        FROM ChefRecipes
        WHERE BusinessID = %s AND Name LIKE %s
        ORDER BY UpdatedAt DESC, CreatedAt DESC
        """,
        (int(business_id), f"%{recipe_name.strip()}%"),
    )
    if not recipes:
        return f"No saved recipe matching '{recipe_name}'."
    rec = recipes[0]
    rid = int(rec.get("recipeid"))
    pname = rec.get("name") or recipe_name
    pyield = int(rec.get("portionyield") or 1)
    menu_price = rec.get("menuprice")

    items = _query(
        """
        SELECT IngredientName, Quantity, Unit, PreferredBusinessID
        FROM ChefRecipeItems
        WHERE RecipeID = %s
        ORDER BY SortOrder, ItemID
        """,
        (rid,),
    )
    if not items:
        return f"Recipe '{pname}' has no ingredient lines."

    lines = [f"Plate cost — {pname} (#{rid}, yields {pyield}):"]
    total_batch = 0.0
    missing: List[str] = []
    for it in items:
        ing = it.get("ingredientname") or ""
        qty = it.get("quantity") or 0
        unit = it.get("unit") or ""
        pref = it.get("preferredbusinessid")
        match = _find_marketplace_match(ing, int(pref) if pref else None)
        if not match:
            missing.append(ing)
            lines.append(f"  • {qty or '?'} {unit} {ing} — no current listing found")
            continue
        up = _unit_price(match) or 0.0
        line_cost = float(qty or 0) * up
        total_batch += line_cost
        src = match.get("businessname") or "OFN"
        lines.append(
            f"  • {qty or '?'} {unit} {ing} — ${up:.2f}/{match.get('unitlabel') or 'unit'} "
            f"via {src} = ${line_cost:.2f}"
        )

    per_plate = total_batch / max(1, pyield)
    lines.append(f"\n  Batch cost: ${total_batch:.2f}")
    lines.append(f"  Per plate (yield {pyield}): ${per_plate:.2f}")
    if menu_price:
        try:
            mp = float(menu_price)
            margin = mp - per_plate
            pct = (margin / mp * 100.0) if mp > 0 else 0.0
            lines.append(f"  Menu price: ${mp:.2f}   Gross margin: ${margin:.2f} ({pct:.0f}%)")
            if pct < 65:
                lines.append("  (Target for restaurants is usually 65–75% gross margin — this is running lean.)")
        except (TypeError, ValueError):
            pass
    if missing:
        lines.append(f"\n  Missing listings: {', '.join(missing)}. "
                     f"These ingredients aren't currently on OFN — treat their cost as $0 in the math above.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# @tool: seasonal_menu_tool
# ---------------------------------------------------------------------------

@tool
def seasonal_menu_tool(
    state: str = "",
    category: str = "",
    business_id: int = 0,
    limit: int = 20,
) -> str:
    """List what's actively in season in the OFN marketplace, scoped to the
    chef's state (optional — defaults to the chef's own state). Optionally
    filter by IngredientCategory ('Vegetable', 'Fruit', 'Herb', 'Meat',
    etc.). Use when the chef asks "what's local right now", "what should
    I put on the summer menu", "what's in season near me"."""
    chef_state = (state or "").strip().upper() or None
    if not chef_state and business_id:
        rows = _query(
            """
            SELECT TOP 1 a.AddressState
            FROM Business b
            LEFT JOIN Address a ON b.AddressID = a.AddressID
            WHERE b.BusinessID = %s
            """,
            (int(business_id),),
        )
        if rows:
            chef_state = (rows[0].get("addressstate") or "").strip().upper() or None

    where = ["p.ShowProduce = 1", "p.Quantity > 0",
             "(p.AvailableDate IS NULL OR p.AvailableDate <= DATEADD(day, 14, GETDATE()))"]
    params: List[Any] = []
    if chef_state:
        where.append("a.AddressState = %s")
        params.append(chef_state)
    if category:
        where.append("icl.IngredientCategory LIKE %s")
        params.append(f"%{category.strip()}%")
    sql = f"""
        SELECT TOP {int(limit)} i.IngredientName, icl.IngredientCategory AS Category,
               p.WholesalePrice, p.RetailPrice, p.Quantity,
               ml.MeasurementAbbreviation AS UnitLabel,
               b.BusinessName, a.AddressCity, a.AddressState,
               p.AvailableDate
        FROM Produce p
        JOIN Ingredients i ON p.IngredientID = i.IngredientID
        LEFT JOIN IngredientCategoryLookup icl ON i.IngredientCategoryID = icl.IngredientCategoryID
        LEFT JOIN MeasurementLookup ml ON p.MeasurementID = ml.MeasurementID
        JOIN Business b ON p.BusinessID = b.BusinessID
        LEFT JOIN Address a ON b.AddressID = a.AddressID
        WHERE {" AND ".join(where)}
        ORDER BY ISNULL(p.AvailableDate, GETDATE()) ASC, i.IngredientName
    """
    rows = _query(sql, tuple(params))
    if not rows:
        where_s = f" in {chef_state}" if chef_state else ""
        return f"Nothing currently listed in season{where_s}."

    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        cat = (r.get("category") or "Uncategorized").strip() or "Uncategorized"
        by_cat.setdefault(cat, []).append(r)

    loc = chef_state or "all states"
    lines = [f"In season now on OFN ({loc}, top {len(rows)} items):"]
    for cat in sorted(by_cat.keys()):
        lines.append(f"\n  {cat}:")
        for r in by_cat[cat]:
            price = r.get("wholesaleprice") or r.get("retailprice")
            price_s = f"${float(price):.2f}/{r.get('unitlabel') or 'unit'}" if price else "price n/a"
            city = r.get("addresscity") or ""
            avail = str(r.get("availabledate") or "")[:10]
            lines.append(
                f"    • {r.get('ingredientname')} — {price_s} · "
                f"{r.get('businessname')} ({city}, {r.get('addressstate') or ''})"
                + (f" · ready {avail}" if avail else "")
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# @tool: set_par_tool / check_par_levels_tool / draft_restock_order_tool
# ---------------------------------------------------------------------------

@tool
def set_par_tool(
    ingredient_name: str = "",
    unit: str = "",
    on_hand: float = 0.0,
    par_level: float = 0.0,
    reorder_at: float = 0.0,
    preferred_business_id: int = 0,
    business_id: int = 0,
) -> str:
    """Set or update a par level for an ingredient in the chef's inventory.
    par_level is the target stock; reorder_at is the threshold at which
    we flag it for restock. Updates the existing row (matched by
    IngredientName + Unit) or inserts a new one. business_id injected."""
    if not business_id or int(business_id) <= 0:
        return "No restaurant context set."
    if not ingredient_name:
        return "Which ingredient?"
    if not _ensure_tables():
        return "Database not available."

    existing = _query(
        """
        SELECT TOP 1 ParID FROM ChefPar
        WHERE BusinessID = %s AND IngredientName = %s AND ISNULL(Unit,'') = %s
        """,
        (int(business_id), ingredient_name.strip(), (unit or "").strip()),
    )
    if existing:
        pid = int(existing[0].get("parid"))
        _execute(
            """
            UPDATE ChefPar
               SET OnHand = %s, ParLevel = %s, ReorderAt = %s,
                   PreferredBusinessID = %s, UpdatedAt = GETUTCDATE()
             WHERE ParID = %s
            """,
            (
                float(on_hand or 0) or None,
                float(par_level or 0) or None,
                float(reorder_at or 0) or None,
                int(preferred_business_id) if preferred_business_id else None,
                pid,
            ),
        )
        return (f"Updated par for {ingredient_name}: on_hand={on_hand}, "
                f"par={par_level}, reorder_at={reorder_at}.")
    _execute(
        """
        INSERT INTO ChefPar
            (BusinessID, IngredientName, Unit, OnHand, ParLevel, ReorderAt,
             PreferredBusinessID, UpdatedAt)
        VALUES (%s, %s, %s, %s, %s, %s, %s, GETUTCDATE())
        """,
        (
            int(business_id),
            ingredient_name.strip()[:200],
            (unit or "").strip()[:50],
            float(on_hand or 0) or None,
            float(par_level or 0) or None,
            float(reorder_at or 0) or None,
            int(preferred_business_id) if preferred_business_id else None,
        ),
    )
    return (f"Set par for {ingredient_name}: target={par_level}{' ' + unit if unit else ''}, "
            f"reorder at {reorder_at}.")


@tool
def check_par_levels_tool(business_id: int = 0) -> str:
    """List ingredients in the chef's inventory that are at or below their
    reorder threshold. Each row shows on-hand, par target, and how much
    to restock to get back to par. Use when the chef asks "what do I need
    to order", "anything running low"."""
    if not business_id or int(business_id) <= 0:
        return "No restaurant context set."
    if not _ensure_tables():
        return "Database not available."
    rows = _query(
        """
        SELECT ParID, IngredientName, Unit, OnHand, ParLevel, ReorderAt, PreferredBusinessID
        FROM ChefPar
        WHERE BusinessID = %s
          AND OnHand IS NOT NULL AND ReorderAt IS NOT NULL
          AND OnHand <= ReorderAt
        ORDER BY IngredientName
        """,
        (int(business_id),),
    )
    if not rows:
        return "Nothing below reorder threshold — inventory is healthy."
    lines = [f"At or below reorder ({len(rows)} items):"]
    for r in rows:
        on_hand = float(r.get("onhand") or 0)
        par = float(r.get("parlevel") or 0)
        need = max(0.0, par - on_hand)
        unit = r.get("unit") or "unit"
        lines.append(
            f"  • {r.get('ingredientname')} — have {on_hand:g} {unit}, "
            f"par {par:g} → restock {need:g} {unit}"
        )
    return "\n".join(lines)


@tool
def draft_restock_order_tool(business_id: int = 0) -> str:
    """For each par item below its reorder threshold, find the best current
    OFN listing (preferred farm if the chef has one set, else cheapest
    wholesale) and compose a suggested multi-farm restock cart with
    quantities and line costs. Use when the chef says "draft my order",
    "restock what's low", "what should I buy this week"."""
    if not business_id or int(business_id) <= 0:
        return "No restaurant context set."
    if not _ensure_tables():
        return "Database not available."
    pars = _query(
        """
        SELECT IngredientName, Unit, OnHand, ParLevel, ReorderAt, PreferredBusinessID
        FROM ChefPar
        WHERE BusinessID = %s
          AND OnHand IS NOT NULL AND ReorderAt IS NOT NULL
          AND OnHand <= ReorderAt
        ORDER BY IngredientName
        """,
        (int(business_id),),
    )
    if not pars:
        return "Nothing needs restocking."
    lines = ["Suggested restock order:"]
    total = 0.0
    by_farm: Dict[str, List[str]] = {}
    for p in pars:
        ing = p.get("ingredientname") or ""
        unit = p.get("unit") or ""
        need = max(0.0, float(p.get("parlevel") or 0) - float(p.get("onhand") or 0))
        pref = p.get("preferredbusinessid")
        match = _find_marketplace_match(ing, int(pref) if pref else None)
        if not match:
            lines.append(f"  • {ing}: need {need:g} {unit} — no current listing")
            continue
        up = _unit_price(match) or 0.0
        line_cost = up * need
        total += line_cost
        farm = match.get("businessname") or "OFN"
        line = (f"    - {need:g} {unit} {ing} @ ${up:.2f}/{match.get('unitlabel') or 'unit'} "
                f"= ${line_cost:.2f}")
        by_farm.setdefault(farm, []).append(line)
    for farm in sorted(by_farm.keys()):
        lines.append(f"\n  From {farm}:")
        lines.extend(by_farm[farm])
    lines.append(f"\n  Estimated total: ${total:.2f}")
    lines.append("  (Approve as a cart draft from your Chef Dashboard to send it to the marketplace.)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# @tool: provenance_cards_tool
# ---------------------------------------------------------------------------

@tool
def provenance_cards_tool(ingredient_names: str = "") -> str:
    """Build "meet your farmers" provenance cards for a comma-separated list
    of ingredient names. For each ingredient, finds the top farm currently
    supplying it on OFN and returns a markdown card with farm name, city,
    state, and description ready to drop into a menu, table tent, or
    social post. Use when the chef asks "who grew these tomatoes",
    "make provenance cards for my summer menu", "tell me about the farms
    I source from"."""
    names = [n.strip() for n in (ingredient_names or "").split(",") if n.strip()]
    if not names:
        return "Pass a comma-separated list of ingredient names."
    cards: List[str] = []
    for name in names:
        match = _find_marketplace_match(name)
        if not match:
            cards.append(f"### {name}\n_No OFN farm currently listing this ingredient._")
            continue
        bid = match.get("businessid")
        rows = _query(
            """
            SELECT TOP 1 b.BusinessID, b.BusinessName, b.BusinessDescription,
                   b.BusinessSlogan, b.BusinessWebsite,
                   a.AddressCity, a.AddressState
            FROM Business b
            LEFT JOIN Address a ON b.AddressID = a.AddressID
            WHERE b.BusinessID = %s
            """,
            (int(bid),) if bid else (0,),
        )
        info = rows[0] if rows else {}
        farm_name = info.get("businessname") or match.get("businessname") or "Unknown farm"
        city = info.get("addresscity") or match.get("addresscity") or ""
        state = info.get("addressstate") or match.get("addressstate") or ""
        slogan = (info.get("businessslogan") or "").strip()
        desc = (info.get("businessdescription") or "").strip()
        website = (info.get("businesswebsite") or "").strip()
        card_lines = [f"### {name.title()} — {farm_name}"]
        if city or state:
            card_lines.append(f"*{city}{', ' if city and state else ''}{state}*")
        if slogan:
            card_lines.append(f"> {slogan}")
        if desc:
            short = desc if len(desc) <= 300 else desc[:297] + "…"
            card_lines.append(short)
        if website:
            card_lines.append(f"[{website}]({website})")
        cards.append("\n".join(card_lines))
    return "\n\n---\n\n".join(cards)


chef_tools = [
    save_recipe_tool,
    cost_recipe_tool,
    seasonal_menu_tool,
    set_par_tool,
    check_par_levels_tool,
    draft_restock_order_tool,
    provenance_cards_tool,
]


# ---------------------------------------------------------------------------
# Non-tool helpers for REST endpoints
# ---------------------------------------------------------------------------

def list_recipes_for_business(business_id: int) -> List[Dict[str, Any]]:
    if not _ensure_tables():
        return []
    return _query(
        """
        SELECT RecipeID, Name, PortionYield, ServingSize, MenuPrice,
               Notes, CreatedAt, UpdatedAt
        FROM ChefRecipes
        WHERE BusinessID = %s
        ORDER BY ISNULL(UpdatedAt, CreatedAt) DESC
        """,
        (int(business_id),),
    )


def list_recipe_items(recipe_id: int) -> List[Dict[str, Any]]:
    return _query(
        """
        SELECT ItemID, IngredientName, Quantity, Unit, PreferredBusinessID, Notes, SortOrder
        FROM ChefRecipeItems
        WHERE RecipeID = %s
        ORDER BY SortOrder, ItemID
        """,
        (int(recipe_id),),
    )


def list_par_for_business(business_id: int) -> List[Dict[str, Any]]:
    if not _ensure_tables():
        return []
    return _query(
        """
        SELECT ParID, IngredientName, Unit, OnHand, ParLevel, ReorderAt,
               PreferredBusinessID, UpdatedAt
        FROM ChefPar
        WHERE BusinessID = %s
        ORDER BY IngredientName
        """,
        (int(business_id),),
    )


def delete_recipe(recipe_id: int, business_id: int) -> bool:
    """Delete a recipe and its items, scoped to business."""
    owned = _query(
        "SELECT RecipeID FROM ChefRecipes WHERE RecipeID = %s AND BusinessID = %s",
        (int(recipe_id), int(business_id)),
    )
    if not owned:
        return False
    _execute("DELETE FROM ChefRecipeItems WHERE RecipeID = %s", (int(recipe_id),))
    _execute("DELETE FROM ChefRecipes WHERE RecipeID = %s", (int(recipe_id),))
    return True


def delete_par(par_id: int, business_id: int) -> bool:
    owned = _query(
        "SELECT ParID FROM ChefPar WHERE ParID = %s AND BusinessID = %s",
        (int(par_id), int(business_id)),
    )
    if not owned:
        return False
    _execute("DELETE FROM ChefPar WHERE ParID = %s", (int(par_id),))
    return True
