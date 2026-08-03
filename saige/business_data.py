"""
Business-account tools for Saige — read and write access to all
business-related tables on OFN (no passwords or payment secrets).

Covers:
  - Business profile (read all fields + update public fields)
  - Animals (list with edit fields + update price/status/description)
  - Produce, Meat, ProcessedFood inventory (list + update/toggle)
  - Services directory (list + add)
  - Blog posts (list + create)
  - Seller marketplace orders (list + confirm/reject/ship)
  - Cold-chain readings (list + log new)
  - Cold-chain shipments (list)
  - Certifications (list + add)

business_id is ALWAYS injected from LangGraph state — never ask the user.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool
from config import DB_CONFIG

try:
    import pymssql
    _PMS_AVAILABLE = True
except ImportError:
    _PMS_AVAILABLE = False

logger = logging.getLogger("business_data")


# ── DB helpers ───────────────────────────────────────────────────────────────

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
        return list(cur.fetchall() or [])
    except Exception as e:
        logger.error("[business_data] query: %s", e)
        return []
    finally:
        try: conn.close()
        except: pass


def _execute(sql: str, params: tuple = ()) -> int:
    conn = _connect()
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        conn.commit()
        return cur.rowcount
    except Exception as e:
        logger.error("[business_data] execute: %s", e)
        return 0
    finally:
        try: conn.close()
        except: pass


def _fmt_money(v) -> str:
    if v is None: return "—"
    try: return f"${float(v):,.2f}"
    except: return str(v)


def _fmt_date(v) -> str:
    if not v: return "—"
    return str(v)[:10]


# ── BUSINESS PROFILE ─────────────────────────────────────────────────────────

@tool
def get_business_profile_tool(business_id: int = 0) -> str:
    """Read the full business profile: name, description, slogan, website,
    phone, email, address, active status, and business type. Use when the
    user asks "show my business profile", "what is my business info", "what
    fields does my account have", or any question about the current state of
    the business. business_id is injected from session."""
    if not business_id or int(business_id) <= 0:
        return "No business context set. Open Saige from your business dashboard."
    rows = _query("""
        SELECT b.BusinessID, b.BusinessName, b.BusinessDescription, b.BusinessSlogan,
               b.BusinessWebsite, b.BusinessPhone, b.BusinessEmail,
               b.IsActive, b.IsClaimed, b.DateCreated,
               bt.BusinessType,
               a.AddressStreet, a.AddressCity, a.AddressState,
               a.AddressZip, a.AddressCountry
        FROM Business b
        LEFT JOIN BusinessTypeLookup bt ON bt.BusinessTypeID = b.BusinessTypeID
        LEFT JOIN Address a ON b.AddressID = a.AddressID
        WHERE b.BusinessID = %s
    """, (int(business_id),))
    if not rows:
        return f"Business {business_id} not found."
    b = rows[0]
    addr_parts = [b.get("AddressStreet"), b.get("AddressCity"),
                  b.get("AddressState"), b.get("AddressZip"), b.get("AddressCountry")]
    address = ", ".join(str(p) for p in addr_parts if p)
    lines = [
        f"Business Profile — #{b.get('BusinessID')}",
        f"  Name:         {b.get('BusinessName') or '—'}",
        f"  Type:         {b.get('BusinessType') or '—'}",
        f"  Active:       {'Yes' if b.get('IsActive') else 'No'} | Claimed: {'Yes' if b.get('IsClaimed') else 'No'}",
        f"  Phone:        {b.get('BusinessPhone') or '—'}",
        f"  Email:        {b.get('BusinessEmail') or '—'}",
        f"  Website:      {b.get('BusinessWebsite') or '—'}",
        f"  Address:      {address or '—'}",
        f"  Slogan:       {b.get('BusinessSlogan') or '—'}",
        f"  Description:  {(str(b.get('BusinessDescription') or ''))[:300] or '—'}",
        f"  Member since: {_fmt_date(b.get('DateCreated'))}",
    ]
    # Try to get social links (columns may vary)
    social_rows = _query("""
        SELECT FacebookURL, InstagramURL, TwitterURL, YouTubeURL, TikTokURL
        FROM Business WHERE BusinessID = %s
    """, (int(business_id),))
    if social_rows:
        s = social_rows[0]
        socials = [(k, s.get(k)) for k in ("FacebookURL","InstagramURL","TwitterURL","YouTubeURL","TikTokURL") if s.get(k)]
        if socials:
            lines.append("  Social: " + " | ".join(f"{k.replace('URL','')}: {v}" for k, v in socials))
    return "\n".join(lines)


@tool
def update_business_profile_tool(
    business_id: int = 0,
    business_name: str = "",
    description: str = "",
    slogan: str = "",
    phone: str = "",
    email: str = "",
    website: str = "",
) -> str:
    """Update the business's public profile fields (name, description, slogan,
    phone, email, website). Leave fields blank to keep them unchanged. Confirm
    with the user before changing the business name. Use when user says "update
    our website link", "change our phone number", "fix the description".
    business_id is injected."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    sets: List[str] = []
    params: List[Any] = []
    if business_name: sets.append("BusinessName = %s"); params.append(str(business_name)[:200])
    if description:   sets.append("BusinessDescription = %s"); params.append(str(description)[:4000])
    if slogan:        sets.append("BusinessSlogan = %s"); params.append(str(slogan)[:300])
    if phone:         sets.append("BusinessPhone = %s"); params.append(str(phone)[:50])
    if email:         sets.append("BusinessEmail = %s"); params.append(str(email)[:200])
    if website:       sets.append("BusinessWebsite = %s"); params.append(str(website)[:500])
    if not sets:
        return "Nothing to update — tell me which field(s) to change."
    params.append(int(business_id))
    n = _execute(f"UPDATE Business SET {', '.join(sets)} WHERE BusinessID = %s", tuple(params))
    if n == 0:
        return f"Could not update business #{business_id}."
    return f"Updated {len(sets)} field(s) on business #{business_id}."


# ── ANIMALS ──────────────────────────────────────────────────────────────────

@tool
def list_my_animals_detail_tool(business_id: int = 0) -> str:
    """List ALL animals on this business with full editable details: name,
    sex, DOB, sale price, stud price, for-sale and for-stud status, and
    whether visible on website. Use when the user asks "show all my animals",
    "what are my animal prices", "which animals are not listed for sale",
    "show animals I can edit". business_id is injected."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    rows = _query("""
        SELECT TOP 50 a.AnimalID, a.FullName, a.Sex, a.DOB,
               a.ForSale, a.ForStud, a.Price, a.StudPrice,
               a.IsActive, a.ShowOnWebsite
        FROM Animals a
        WHERE a.BusinessID = %s AND a.IsActive = 1
        ORDER BY a.FullName
    """, (int(business_id),))
    if not rows:
        return f"No animals found for business #{business_id}."
    lines = [f"Animals — business #{business_id} ({len(rows)} shown):"]
    for a in rows:
        status = []
        if a.get("ForSale"): status.append("for-sale")
        if a.get("ForStud"): status.append("at-stud")
        if not status: status.append("not-listed")
        lines.append(
            f"  #{a.get('AnimalID')} {a.get('FullName') or '—'} · "
            f"{a.get('Sex') or '?'} · DOB {_fmt_date(a.get('DOB'))} · "
            f"price {_fmt_money(a.get('Price'))} · stud {_fmt_money(a.get('StudPrice'))} · "
            f"[{', '.join(status)}]"
            + (" · hidden" if not a.get("ShowOnWebsite") else "")
        )
    return "\n".join(lines)


@tool
def update_animal_tool(
    animal_id: int = 0,
    business_id: int = 0,
    price: float = -1.0,
    stud_price: float = -1.0,
    for_sale: int = -1,
    for_stud: int = -1,
    description: str = "",
    show_on_website: int = -1,
) -> str:
    """Update one animal's editable fields: sale price, stud price, for-sale
    status (for_sale=1 to list / 0 to remove from sale), stud status
    (for_stud=1/0), description, or website visibility (show_on_website=1/0).
    Pass -1 for numeric toggles you don't want to change. Always confirm
    price or status changes with the user first. Use when user says "set
    animal #42 price to $1500", "take my llama off the market", "list my
    new alpaca for stud", "hide animal #7 from the website".
    business_id is injected."""
    if not animal_id or int(animal_id) <= 0:
        return "I need an AnimalID. Use list_my_animals_detail_tool to find it."
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    check = _query(
        "SELECT AnimalID FROM Animals WHERE AnimalID = %s AND BusinessID = %s",
        (int(animal_id), int(business_id)),
    )
    if not check:
        return f"Animal #{animal_id} not found on business #{business_id}."
    sets: List[str] = []
    params: List[Any] = []
    if price >= 0:           sets.append("Price = %s"); params.append(float(price))
    if stud_price >= 0:      sets.append("StudPrice = %s"); params.append(float(stud_price))
    if for_sale >= 0:        sets.append("ForSale = %s"); params.append(1 if for_sale else 0)
    if for_stud >= 0:        sets.append("ForStud = %s"); params.append(1 if for_stud else 0)
    if show_on_website >= 0: sets.append("ShowOnWebsite = %s"); params.append(1 if show_on_website else 0)
    if description:          sets.append("Description = %s"); params.append(str(description)[:4000])
    if not sets:
        return "Nothing to update — tell me what to change."
    params += [int(animal_id), int(business_id)]
    _execute(
        f"UPDATE Animals SET {', '.join(sets)} WHERE AnimalID = %s AND BusinessID = %s",
        tuple(params),
    )
    return f"Updated animal #{animal_id} ({len(sets)} field(s) changed)."


# ── PRODUCE INVENTORY ────────────────────────────────────────────────────────

@tool
def list_produce_inventory_tool(business_id: int = 0) -> str:
    """List all produce/crop inventory for this business with full editable
    details: ingredient name, category, quantity with unit, retail price,
    wholesale price, available date, and active status (ShowProduce).
    Use when the user asks "show my produce", "what crops am I selling",
    "show my produce inventory with prices". business_id is injected."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    rows = _query("""
        SELECT p.ProduceID, i.IngredientName, ic.IngredientCategory,
               p.Quantity, m.MeasurementAbbreviation,
               p.WholesalePrice, p.RetailPrice, p.AvailableDate, p.ShowProduce
        FROM Produce p
        JOIN Ingredients i ON p.IngredientID = i.IngredientID
        LEFT JOIN IngredientCategoryLookup ic ON i.IngredientCategoryID = ic.IngredientCategoryID
        LEFT JOIN MeasurementLookup m ON p.MeasurementID = m.MeasurementID
        WHERE p.BusinessID = %s
        ORDER BY i.IngredientName
    """, (int(business_id),))
    if not rows:
        return f"No produce inventory found for business #{business_id}."
    lines = [f"Produce inventory — business #{business_id} ({len(rows)} items):"]
    for p in rows:
        unit = p.get("MeasurementAbbreviation") or "unit"
        status = "active" if p.get("ShowProduce") else "hidden"
        lines.append(
            f"  ProduceID #{p.get('ProduceID')} · {p.get('IngredientName')}"
            f" ({p.get('IngredientCategory') or 'n/a'}) · "
            f"qty {p.get('Quantity') or 0} {unit} · "
            f"retail {_fmt_money(p.get('RetailPrice'))} · "
            f"wholesale {_fmt_money(p.get('WholesalePrice'))} · "
            f"avail {_fmt_date(p.get('AvailableDate'))} · [{status}]"
        )
    return "\n".join(lines)


@tool
def update_produce_listing_tool(
    produce_id: int = 0,
    business_id: int = 0,
    quantity: float = -1.0,
    retail_price: float = -1.0,
    wholesale_price: float = -1.0,
    show_produce: int = -1,
    available_date: str = "",
) -> str:
    """Update a produce listing: quantity, retail price, wholesale price,
    available date, or visibility (show_produce=1 to make active / 0 to hide).
    Pass -1 for numeric fields you don't want to change. Confirm before
    calling on price changes. Use when user says "change my tomato price to
    $4/lb", "hide the apple listing", "update corn quantity to 500 lbs",
    "set the available date for my pumpkins". business_id is injected."""
    if not produce_id or int(produce_id) <= 0:
        return "I need a ProduceID. Use list_produce_inventory_tool to find it."
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    check = _query(
        "SELECT ProduceID FROM Produce WHERE ProduceID = %s AND BusinessID = %s",
        (int(produce_id), int(business_id)),
    )
    if not check:
        return f"ProduceID #{produce_id} not found on business #{business_id}."
    sets: List[str] = []
    params: List[Any] = []
    if quantity >= 0:        sets.append("Quantity = %s"); params.append(float(quantity))
    if retail_price >= 0:    sets.append("RetailPrice = %s"); params.append(float(retail_price))
    if wholesale_price >= 0: sets.append("WholesalePrice = %s"); params.append(float(wholesale_price))
    if show_produce >= 0:    sets.append("ShowProduce = %s"); params.append(1 if show_produce else 0)
    if available_date:       sets.append("AvailableDate = %s"); params.append(str(available_date)[:20])
    if not sets:
        return "Nothing to update."
    params += [int(produce_id), int(business_id)]
    _execute(
        f"UPDATE Produce SET {', '.join(sets)} WHERE ProduceID = %s AND BusinessID = %s",
        tuple(params),
    )
    return f"Updated produce listing #{produce_id} ({len(sets)} field(s) changed)."


# ── MEAT INVENTORY ───────────────────────────────────────────────────────────

@tool
def list_meat_inventory_tool(business_id: int = 0) -> str:
    """List all meat inventory for this business with full editable details:
    ingredient name, cut, quantity, weight unit, retail and wholesale price,
    available date, and active status. Use when the user asks "show my meat
    inventory", "what cuts am I selling", "show my beef listings with prices".
    business_id is injected."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    rows = _query("""
        SELECT m.MeatInventoryID, i.IngredientName, ic.IngredientCut,
               m.Quantity, m.WeightUnit, m.WholesalePrice, m.RetailPrice,
               m.AvailableDate, m.ShowMeat
        FROM MeatInventory m
        JOIN Ingredients i ON m.IngredientID = i.IngredientID
        LEFT JOIN Cut ic ON m.IngredientCutID = ic.IngredientCutID
        WHERE m.BusinessID = %s
        ORDER BY i.IngredientName
    """, (int(business_id),))
    if not rows:
        return f"No meat inventory found for business #{business_id}."
    lines = [f"Meat inventory — business #{business_id} ({len(rows)} items):"]
    for m in rows:
        name = m.get("IngredientName") or "?"
        cut = m.get("IngredientCut") or ""
        unit = m.get("WeightUnit") or "lb"
        status = "active" if m.get("ShowMeat") else "hidden"
        lines.append(
            f"  MeatID #{m.get('MeatInventoryID')} · {name}"
            f"{(' - ' + cut) if cut else ''} · "
            f"qty {m.get('Quantity') or 0} {unit} · "
            f"retail {_fmt_money(m.get('RetailPrice'))} · "
            f"wholesale {_fmt_money(m.get('WholesalePrice'))} · "
            f"avail {_fmt_date(m.get('AvailableDate'))} · [{status}]"
        )
    return "\n".join(lines)


@tool
def update_meat_listing_tool(
    meat_id: int = 0,
    business_id: int = 0,
    quantity: float = -1.0,
    retail_price: float = -1.0,
    wholesale_price: float = -1.0,
    show_meat: int = -1,
    available_date: str = "",
    notes: str = "",
) -> str:
    """Update a meat inventory listing: quantity, retail price, wholesale price,
    available date, notes, or visibility (show_meat=1/0). Pass -1 for fields
    not being changed. Confirm price changes first. Use when user says "change
    my beef price to $8/lb", "hide the pork listing", "update lamb quantity
    to 200 lbs". business_id is injected."""
    if not meat_id or int(meat_id) <= 0:
        return "I need a MeatInventoryID. Use list_meat_inventory_tool to find it."
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    check = _query(
        "SELECT MeatInventoryID FROM MeatInventory WHERE MeatInventoryID = %s AND BusinessID = %s",
        (int(meat_id), int(business_id)),
    )
    if not check:
        return f"MeatInventoryID #{meat_id} not found on business #{business_id}."
    sets: List[str] = []
    params: List[Any] = []
    if quantity >= 0:        sets.append("Quantity = %s"); params.append(float(quantity))
    if retail_price >= 0:    sets.append("RetailPrice = %s"); params.append(float(retail_price))
    if wholesale_price >= 0: sets.append("WholesalePrice = %s"); params.append(float(wholesale_price))
    if show_meat >= 0:       sets.append("ShowMeat = %s"); params.append(1 if show_meat else 0)
    if available_date:       sets.append("AvailableDate = %s"); params.append(str(available_date)[:20])
    if notes:                sets.append("Notes = %s"); params.append(str(notes)[:2000])
    if not sets:
        return "Nothing to update."
    params += [int(meat_id), int(business_id)]
    _execute(
        f"UPDATE MeatInventory SET {', '.join(sets)} WHERE MeatInventoryID = %s AND BusinessID = %s",
        tuple(params),
    )
    return f"Updated meat listing #{meat_id} ({len(sets)} field(s) changed)."


# ── PROCESSED FOOD ───────────────────────────────────────────────────────────

@tool
def list_processed_food_tool(business_id: int = 0) -> str:
    """List all processed / artisan food products for this business: product
    name, quantity, retail and wholesale price, active status, and organic/local
    flags. Use when user asks "show my processed food", "what artisan products
    do I have", "show my food product listings". business_id is injected."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    rows = _query("""
        SELECT ProcessedFoodID, Name, Quantity, WholesalePrice, RetailPrice,
               ShowProcessedFood, IsOrganic, IsLocal
        FROM ProcessedFood
        WHERE BusinessID = %s
        ORDER BY Name
    """, (int(business_id),))
    if not rows:
        return f"No processed food listings found for business #{business_id}."
    lines = [f"Processed food — business #{business_id} ({len(rows)} items):"]
    for f in rows:
        tags = []
        if f.get("IsOrganic"): tags.append("organic")
        if f.get("IsLocal"):   tags.append("local")
        status = "active" if f.get("ShowProcessedFood") else "hidden"
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(
            f"  FoodID #{f.get('ProcessedFoodID')} · {f.get('Name')} · "
            f"qty {f.get('Quantity') or 0} · "
            f"retail {_fmt_money(f.get('RetailPrice'))} · "
            f"wholesale {_fmt_money(f.get('WholesalePrice'))} · "
            f"[{status}]{tag_str}"
        )
    return "\n".join(lines)


@tool
def update_processed_food_tool(
    food_id: int = 0,
    business_id: int = 0,
    quantity: float = -1.0,
    retail_price: float = -1.0,
    wholesale_price: float = -1.0,
    show_product: int = -1,
    notes: str = "",
) -> str:
    """Update a processed food listing: quantity, prices, notes, or visibility
    (show_product=1 to make active / 0 to hide). Pass -1 for fields not being
    changed. Confirm price changes first. Use when user says "change my jam
    price to $6", "hide the cheese listing", "update bread quantity to 50
    loaves". business_id is injected."""
    if not food_id or int(food_id) <= 0:
        return "I need a ProcessedFoodID. Use list_processed_food_tool to find it."
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    check = _query(
        "SELECT ProcessedFoodID FROM ProcessedFood WHERE ProcessedFoodID = %s AND BusinessID = %s",
        (int(food_id), int(business_id)),
    )
    if not check:
        return f"ProcessedFoodID #{food_id} not found on business #{business_id}."
    sets: List[str] = []
    params: List[Any] = []
    if quantity >= 0:        sets.append("Quantity = %s"); params.append(float(quantity))
    if retail_price >= 0:    sets.append("RetailPrice = %s"); params.append(float(retail_price))
    if wholesale_price >= 0: sets.append("WholesalePrice = %s"); params.append(float(wholesale_price))
    if show_product >= 0:    sets.append("ShowProcessedFood = %s"); params.append(1 if show_product else 0)
    if notes:                sets.append("Notes = %s"); params.append(str(notes)[:2000])
    if not sets:
        return "Nothing to update."
    params += [int(food_id), int(business_id)]
    _execute(
        f"UPDATE ProcessedFood SET {', '.join(sets)} WHERE ProcessedFoodID = %s AND BusinessID = %s",
        tuple(params),
    )
    return f"Updated processed food listing #{food_id} ({len(sets)} field(s) changed)."


# ── BLOG POSTS ───────────────────────────────────────────────────────────────

@tool
def list_my_blog_posts_tool(business_id: int = 0) -> str:
    """List blog posts for this business — title, category, published date,
    and whether each post is published to the directory and/or website. Use
    when user asks "show my blog posts", "what articles have I written",
    "are my posts published". business_id is injected."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    rows = _query("""
        SELECT TOP 30 BlogID, Title, Category, PublishedDate,
               IsPublished, ShowOnDirectory, ShowOnWebsite
        FROM blog
        WHERE BusinessID = %s
        ORDER BY PublishedDate DESC, BlogID DESC
    """, (int(business_id),))
    if not rows:
        return f"No blog posts found for business #{business_id}."
    lines = [f"Blog posts — business #{business_id} ({len(rows)} shown):"]
    for p in rows:
        flags = []
        if p.get("IsPublished"):    flags.append("published")
        if p.get("ShowOnDirectory"): flags.append("directory")
        if p.get("ShowOnWebsite"):  flags.append("website")
        lines.append(
            f"  #{p.get('BlogID')} · {p.get('Title') or '(untitled)'} · "
            f"{p.get('Category') or 'n/a'} · {_fmt_date(p.get('PublishedDate'))} · "
            f"[{', '.join(flags) if flags else 'draft'}]"
        )
    return "\n".join(lines)


@tool
def create_blog_post_tool(
    business_id: int = 0,
    title: str = "",
    content: str = "",
    category: str = "",
    publish: int = 0,
) -> str:
    """Create a new blog post for this business. publish=1 to publish
    immediately (visible on directory + website); publish=0 saves as draft.
    Always confirm the title and content with the user before calling.
    Use when user says "write a blog post about X", "publish an article
    about our farm", "draft a post on regenerative practices".
    business_id is injected."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    if not title.strip():
        return "I need a title for the blog post."
    if not content.strip():
        return "I need content for the blog post."
    is_pub = 1 if publish else 0
    conn = _connect()
    if not conn:
        return "Database unavailable — try again in a moment."
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute("""
            INSERT INTO blog (BusinessID, Title, Content, Category, IsPublished,
                              ShowOnDirectory, ShowOnWebsite, PublishedDate)
            OUTPUT INSERTED.BlogID
            VALUES (%s, %s, %s, %s, %s, %s, %s, GETDATE())
        """, (int(business_id), str(title)[:300], str(content)[:20000],
              str(category)[:100] or "General", is_pub, is_pub, is_pub))
        row = cur.fetchone()
        conn.commit()
        bid = row.get("BlogID") if row else "?"
        status = "published" if is_pub else "saved as draft"
        return f"Blog post #{bid} '{title}' {status}."
    except Exception as e:
        logger.error("[business_data] create_blog_post: %s", e)
        return f"Could not create blog post: {e}"
    finally:
        try: conn.close()
        except: pass


# ── SERVICES ─────────────────────────────────────────────────────────────────

@tool
def list_my_services_tool(business_id: int = 0) -> str:
    """List service listings for this business — service title, category,
    price (or 'contact for price'), availability, phone and website if listed.
    Use when user asks "what services do I offer", "show my service listings",
    "what is my shearing service price". business_id is injected."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    rows = _query("""
        SELECT s.ServicesID, s.ServiceTitle, s.ServicePrice,
               s.ServiceContactForPrice, s.ServiceAvailable,
               s.ServicesDescription, s.ServicePhone, s.Servicewebsite,
               sc.ServicesCategory
        FROM Services s
        LEFT JOIN servicescategories sc ON sc.ServiceCategoryID = s.ServiceCategoryID
        WHERE s.BusinessID = %s
        ORDER BY sc.ServicesCategory, s.ServiceTitle
    """, (int(business_id),))
    if not rows:
        return f"No service listings found for business #{business_id}."
    lines = [f"Services — business #{business_id} ({len(rows)} listings):"]
    for s in rows:
        price = "contact for price" if s.get("ServiceContactForPrice") else _fmt_money(s.get("ServicePrice"))
        avail = "available" if s.get("ServiceAvailable") else "unavailable"
        lines.append(
            f"  #{s.get('ServicesID')} · {s.get('ServiceTitle')} · "
            f"{s.get('ServicesCategory') or 'Uncategorized'} · "
            f"{price} · [{avail}]"
        )
        if s.get("ServicesDescription"):
            lines.append(f"     {str(s.get('ServicesDescription'))[:120]}")
    return "\n".join(lines)


@tool
def add_service_listing_tool(
    business_id: int = 0,
    title: str = "",
    description: str = "",
    price: float = -1.0,
    contact_for_price: int = 0,
    available: int = 1,
    phone: str = "",
    website: str = "",
) -> str:
    """Add a new service listing to this business. price=-1 means no price set;
    set contact_for_price=1 if pricing is by inquiry. Confirm details with the
    user before calling. Use when user says "add a shearing service at $15/head",
    "create a boarding service listing", "list our AI consultation service".
    business_id is injected."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    if not title.strip():
        return "I need a service title."
    price_val = float(price) if price >= 0 else None
    _execute("""
        INSERT INTO Services (BusinessID, ServiceTitle, ServicesDescription,
                              ServicePrice, ServiceContactForPrice, ServiceAvailable,
                              ServicePhone, Servicewebsite)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (int(business_id), str(title)[:300], str(description)[:4000] or None,
          price_val, 1 if contact_for_price else 0, 1 if available else 0,
          str(phone)[:50] or None, str(website)[:500] or None))
    return f"Service '{title}' added to business #{business_id}."


# ── SELLER MARKETPLACE ORDERS ────────────────────────────────────────────────

@tool
def list_seller_orders_tool(business_id: int = 0, status: str = "") -> str:
    """List incoming marketplace orders for this business (items buyers have
    ordered from us). status filters: 'pending', 'confirmed', 'shipped',
    'rejected'. Empty = all active (pending + confirmed). Shows product,
    qty, total, buyer, delivery method, and tracking. Use when user asks
    "what orders do I have", "pending orders", "orders I need to ship",
    "show confirmed orders". business_id is injected."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    sf = (status or "").strip().lower()
    params: List[Any] = [int(business_id)]
    if sf in ("pending", "confirmed", "shipped", "rejected"):
        status_clause = "AND oi.SellerStatus = %s"
        params.append(sf)
    else:
        status_clause = "AND oi.SellerStatus IN ('pending','confirmed')"
    rows = _query(f"""
        SELECT TOP 30 oi.OrderItemID, oi.ProductTitle, oi.Quantity, oi.LineTotal,
               oi.SellerStatus, oi.TrackingNumber, oi.EstimatedDeliveryDate,
               o.OrderNumber, o.BuyerName, o.DeliveryMethod,
               o.RequestedDeliveryDate, o.CreatedAt AS OrderDate
        FROM MarketplaceOrderItems oi
        JOIN MarketplaceOrders o ON oi.OrderID = o.OrderID
        WHERE oi.SellerBusinessID = %s {status_clause}
        ORDER BY o.CreatedAt DESC
    """, tuple(params))
    if not rows:
        return f"No {sf or 'active'} orders for business #{business_id}."
    label = sf if sf else "active"
    lines = [f"Marketplace orders ({label}) — business #{business_id} ({len(rows)} shown):"]
    for r in rows:
        lines.append(
            f"  #{r.get('OrderItemID')} · {r.get('ProductTitle')} · "
            f"qty {r.get('Quantity')} · {_fmt_money(r.get('LineTotal'))} · "
            f"[{r.get('SellerStatus') or 'pending'}] · order {r.get('OrderNumber')}"
        )
        lines.append(
            f"      buyer: {r.get('BuyerName') or '—'} · {r.get('DeliveryMethod') or '—'}"
            + (f" · needs by {_fmt_date(r.get('RequestedDeliveryDate'))}" if r.get('RequestedDeliveryDate') else "")
            + (f" · tracking: {r.get('TrackingNumber')}" if r.get('TrackingNumber') else "")
        )
    return "\n".join(lines)


@tool
def confirm_seller_order_tool(
    order_item_id: int = 0,
    business_id: int = 0,
    estimated_delivery_date: str = "",
) -> str:
    """Confirm (accept) a pending marketplace order line. Optionally set
    estimated_delivery_date as 'YYYY-MM-DD'. Only works on 'pending' items.
    Confirm with the user first. Use when user says "accept order #123",
    "confirm the tomato order". business_id is injected."""
    if not order_item_id or not business_id:
        return "I need an OrderItemID to confirm."
    rows = _query(
        "SELECT SellerStatus, SellerBusinessID FROM MarketplaceOrderItems WHERE OrderItemID = %s",
        (int(order_item_id),),
    )
    if not rows:
        return f"Order item #{order_item_id} not found."
    r = rows[0]
    if int(r.get("SellerBusinessID") or 0) != int(business_id):
        return "That order belongs to a different business."
    if (r.get("SellerStatus") or "").lower() != "pending":
        return f"Order #{order_item_id} is already '{r.get('SellerStatus')}' — can only confirm pending."
    edd = (estimated_delivery_date or "").strip() or None
    _execute("""UPDATE MarketplaceOrderItems
                   SET SellerStatus='confirmed', EstimatedDeliveryDate=%s, UpdatedAt=GETDATE()
                 WHERE OrderItemID=%s""", (edd, int(order_item_id)))
    return f"Confirmed order #{order_item_id}" + (f" (ETA {edd})" if edd else "") + "."


@tool
def reject_seller_order_tool(
    order_item_id: int = 0,
    business_id: int = 0,
    reason: str = "",
) -> str:
    """Reject a pending marketplace order line and restore the inventory.
    A reason is required — the buyer sees it. Only works on 'pending' items.
    Confirm with the user first. Use when user says "reject order #123 —
    out of stock", "decline that lamb order". business_id is injected."""
    if not order_item_id or not business_id:
        return "I need an OrderItemID to reject."
    if not reason:
        return "Please provide a reason — the buyer will see it."
    rows = _query(
        "SELECT SellerStatus, SellerBusinessID, ListingID, Quantity FROM MarketplaceOrderItems WHERE OrderItemID = %s",
        (int(order_item_id),),
    )
    if not rows:
        return f"Order item #{order_item_id} not found."
    r = rows[0]
    if int(r.get("SellerBusinessID") or 0) != int(business_id):
        return "That order belongs to a different business."
    if (r.get("SellerStatus") or "").lower() != "pending":
        return f"Order #{order_item_id} is '{r.get('SellerStatus')}' — can only reject pending."
    _execute("""UPDATE MarketplaceOrderItems
                   SET SellerStatus='rejected', RejectionReason=%s, UpdatedAt=GETDATE()
                 WHERE OrderItemID=%s""", (str(reason)[:500], int(order_item_id)))
    lid = str(r.get("ListingID") or "")
    qty = r.get("Quantity") or 0
    if lid and qty:
        prefix = lid[0].upper()
        try:
            src = int(lid[1:])
        except ValueError:
            src = 0
        if src:
            if prefix == "P":
                _execute("UPDATE Produce SET Quantity=Quantity+%s WHERE ProduceID=%s", (float(qty), src))
            elif prefix == "M":
                _execute("UPDATE MeatInventory SET Quantity=Quantity+%s WHERE MeatInventoryID=%s", (float(qty), src))
            elif prefix == "F":
                _execute("UPDATE ProcessedFood SET Quantity=Quantity+%s WHERE ProcessedFoodID=%s", (float(qty), src))
    return f"Rejected order #{order_item_id} and restored inventory."


@tool
def ship_seller_order_tool(
    order_item_id: int = 0,
    business_id: int = 0,
    tracking_number: str = "",
    estimated_delivery_date: str = "",
) -> str:
    """Mark a confirmed marketplace order as shipped with tracking number and
    ETA. Only works on 'confirmed' items. Use when user says "order #123
    shipped — tracking 1Z999...", "mark the beef order as shipped".
    business_id is injected."""
    if not order_item_id or not business_id:
        return "I need an OrderItemID to mark shipped."
    rows = _query(
        "SELECT SellerStatus, SellerBusinessID FROM MarketplaceOrderItems WHERE OrderItemID = %s",
        (int(order_item_id),),
    )
    if not rows:
        return f"Order item #{order_item_id} not found."
    r = rows[0]
    if int(r.get("SellerBusinessID") or 0) != int(business_id):
        return "That order belongs to a different business."
    if (r.get("SellerStatus") or "").lower() != "confirmed":
        return f"Order #{order_item_id} is '{r.get('SellerStatus')}' — confirm it first, then mark shipped."
    edd = (estimated_delivery_date or "").strip() or None
    tn = (tracking_number or "").strip()[:200] or None
    _execute("""UPDATE MarketplaceOrderItems
                   SET SellerStatus='shipped', TrackingNumber=%s,
                       EstimatedDeliveryDate=%s, ShippedAt=GETDATE(), UpdatedAt=GETDATE()
                 WHERE OrderItemID=%s""", (tn, edd, int(order_item_id)))
    return (f"Order #{order_item_id} marked shipped"
            + (f" (tracking {tn})" if tn else "")
            + (f", ETA {edd}" if edd else "") + ".")


# ── COLD CHAIN READINGS & SHIPMENTS ─────────────────────────────────────────

@tool
def list_cold_chain_readings_tool(business_id: int = 0, vehicle_id: int = 0, limit: int = 20) -> str:
    """List recent temperature readings for this business's cold chain vehicles.
    Set vehicle_id to filter to one vehicle; 0 = all vehicles. Flags readings
    outside the vehicle's allowed range. Use when user asks "show recent temp
    readings", "any temperature violations on my trucks", "what temperatures
    have been logged". business_id is injected."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    n = max(1, min(int(limit), 50))
    where = "WHERE v.BusinessID = %s"
    params: List[Any] = [int(business_id)]
    if vehicle_id and int(vehicle_id) > 0:
        where += " AND r.VehicleID = %s"
        params.append(int(vehicle_id))
    rows = _query(f"""
        SELECT TOP {n} r.ReadingID, r.VehicleID, v.VehicleName,
               r.TempC, r.RecordedAt, v.MinTempC, v.MaxTempC
        FROM ColdChainReadings r
        JOIN ColdChainVehicles v ON v.VehicleID = r.VehicleID
        {where}
        ORDER BY r.RecordedAt DESC
    """, tuple(params))
    if not rows:
        return f"No temperature readings found for business #{business_id}."
    lines = [f"Cold chain readings — business #{business_id} ({len(rows)} shown):"]
    for r in rows:
        t = r.get("TempC")
        mn = r.get("MinTempC"); mx = r.get("MaxTempC")
        flag = ""
        if t is not None and mn is not None and mx is not None:
            flag = " ✓ OK" if mn <= t <= mx else " ⚠ OUT OF RANGE"
        lines.append(
            f"  {str(r.get('RecordedAt') or '')[:19]} · "
            f"{r.get('VehicleName') or 'Vehicle #' + str(r.get('VehicleID'))} · "
            f"{t}°C{flag}"
        )
    return "\n".join(lines)


@tool
def log_cold_chain_reading_tool(
    vehicle_id: int = 0,
    business_id: int = 0,
    temp_c: float = 0.0,
    notes: str = "",
) -> str:
    """Log a new temperature reading for a cold chain vehicle. Confirm the
    vehicle and temperature with the user before calling. Use when user says
    "log a temp of -2°C for truck A", "record reading on vehicle #3".
    business_id is injected."""
    if not vehicle_id or int(vehicle_id) <= 0:
        return "I need a VehicleID. Use list_cold_chain_vehicles_tool to find it."
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    check = _query(
        "SELECT VehicleID FROM ColdChainVehicles WHERE VehicleID = %s AND BusinessID = %s",
        (int(vehicle_id), int(business_id)),
    )
    if not check:
        return f"Vehicle #{vehicle_id} not found on business #{business_id}."
    _execute("""
        INSERT INTO ColdChainReadings (VehicleID, TempC, Notes, RecordedAt)
        VALUES (%s, %s, %s, GETDATE())
    """, (int(vehicle_id), float(temp_c), str(notes)[:500] or None))
    return f"Logged reading: vehicle #{vehicle_id}, {temp_c}°C."


@tool
def list_cold_chain_shipments_tool(business_id: int = 0, status: str = "") -> str:
    """List cold chain shipments for this business — active or completed
    deliveries with origin, destination, vehicle, driver, and status.
    Optional status filter: 'active', 'completed', 'cancelled'. Use when
    user asks "show my shipments", "deliveries in transit", "shipment history".
    business_id is injected."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    where = "WHERE s.BusinessID = %s"
    params: List[Any] = [int(business_id)]
    sf = (status or "").strip().lower()
    if sf in ("active", "completed", "cancelled"):
        where += " AND s.Status = %s"; params.append(sf)
    rows = _query(f"""
        SELECT TOP 25 s.ShipmentID, s.Status, s.OriginName, s.DestinationName,
               s.DepartureTime, s.ArrivalTime,
               v.VehicleName, v.DriverName
        FROM ColdChainShipments s
        LEFT JOIN ColdChainVehicles v ON v.VehicleID = s.VehicleID
        {where}
        ORDER BY s.DepartureTime DESC
    """, tuple(params))
    if not rows:
        return f"No {sf or ''} shipments found for business #{business_id}."
    lines = [f"Cold chain shipments — business #{business_id} ({len(rows)} shown):"]
    for s in rows:
        lines.append(
            f"  #{s.get('ShipmentID')} · [{s.get('Status') or '—'}] · "
            f"{s.get('OriginName') or '—'} → {s.get('DestinationName') or '—'} · "
            f"vehicle: {s.get('VehicleName') or '—'} · driver: {s.get('DriverName') or '—'} · "
            f"departed {str(s.get('DepartureTime') or '')[:16]}"
        )
    return "\n".join(lines)


# ── CERTIFICATIONS ───────────────────────────────────────────────────────────

@tool
def list_my_certifications_tool(business_id: int = 0) -> str:
    """List certifications and credentials for this business: certification
    type, issuing body, cert number, issue and expiry dates, and status.
    Use when user asks "show my certifications", "what certs do I have",
    "when does my organic cert expire", "any certs expiring soon".
    business_id is injected."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    rows = _query("""
        SELECT CertificationID, CertificationType, IssuingBody,
               CertificationNumber, IssueDate, ExpiryDate, IsActive
        FROM Certifications
        WHERE BusinessID = %s
        ORDER BY ExpiryDate ASC
    """, (int(business_id),))
    if not rows:
        return f"No certifications found for business #{business_id}."
    lines = [f"Certifications — business #{business_id} ({len(rows)} total):"]
    for c in rows:
        status = "active" if c.get("IsActive") else "inactive"
        lines.append(
            f"  #{c.get('CertificationID')} · {c.get('CertificationType') or '—'} · "
            f"{c.get('IssuingBody') or '—'} · cert# {c.get('CertificationNumber') or '—'} · "
            f"issued {_fmt_date(c.get('IssueDate'))} · expires {_fmt_date(c.get('ExpiryDate'))} · [{status}]"
        )
    return "\n".join(lines)


@tool
def add_certification_tool(
    business_id: int = 0,
    certification_type: str = "",
    issuing_body: str = "",
    certification_number: str = "",
    issue_date: str = "",
    expiry_date: str = "",
    notes: str = "",
) -> str:
    """Add a new certification record to this business. Confirm details with
    the user before calling. Use when user says "add my USDA organic cert",
    "record my new food safety certification", "log our GAP certification".
    business_id is injected."""
    if not business_id or int(business_id) <= 0:
        return "No business context set."
    if not certification_type.strip():
        return "I need a certification type (e.g., 'USDA Organic', 'Food Safety', 'GAP')."
    _execute("""
        INSERT INTO Certifications (BusinessID, CertificationType, IssuingBody,
                                    CertificationNumber, IssueDate, ExpiryDate, IsActive, Notes)
        VALUES (%s, %s, %s, %s, %s, %s, 1, %s)
    """, (int(business_id),
          str(certification_type)[:200],
          str(issuing_body)[:200] or None,
          str(certification_number)[:100] or None,
          issue_date or None,
          expiry_date or None,
          str(notes)[:2000] or None))
    return f"Certification '{certification_type}' added to business #{business_id}."


# ── TOOL REGISTRY ────────────────────────────────────────────────────────────

business_data_tools = [
    # Profile
    get_business_profile_tool,
    update_business_profile_tool,
    # Animals
    list_my_animals_detail_tool,
    update_animal_tool,
    # Produce
    list_produce_inventory_tool,
    update_produce_listing_tool,
    # Meat
    list_meat_inventory_tool,
    update_meat_listing_tool,
    # Processed food
    list_processed_food_tool,
    update_processed_food_tool,
    # Blog
    list_my_blog_posts_tool,
    create_blog_post_tool,
    # Services
    list_my_services_tool,
    add_service_listing_tool,
    # Orders
    list_seller_orders_tool,
    confirm_seller_order_tool,
    reject_seller_order_tool,
    ship_seller_order_tool,
    # Cold chain
    list_cold_chain_readings_tool,
    log_cold_chain_reading_tool,
    list_cold_chain_shipments_tool,
    # Certifications
    list_my_certifications_tool,
    add_certification_tool,
]
