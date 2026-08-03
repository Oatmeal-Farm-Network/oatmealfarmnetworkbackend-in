"""
seed_orders_15671.py — Marketplace order test data for BusinessID=15671 (Food World) as seller.
Creates MarketplaceOrders + MarketplaceOrderItems across all status stages.
Idempotent: skips OrderNumbers already in DB.
"""
import sys, datetime, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import get_db
from sqlalchemy import text

BID = 15671
SELLER_NAME = "Food World Farm"
db = next(get_db())

def q(sql, params=None):
    db.execute(text(sql), params or {})

def first(sql, params=None):
    return db.execute(text(sql), params or {}).scalar()

# Find a valid PeopleID to use as buyer (any existing person)
BUYER_PID = first("SELECT TOP 1 PeopleID FROM People ORDER BY PeopleID") or 1

# Listing pool — (ListingID, ProductTitle, ProductType, UnitPrice)
# ListingID is stored as nvarchar in MarketplaceOrderItems (no FK constraint).
listing_pool = [
    ("P9001", "Heirloom Tomatoes — Mixed (3 lb)",   "Produce",  4.50),
    ("P9002", "Alpaca Compost — 25 lb Bag",          "Produce", 18.00),
    ("P9003", "Fresh Basil Bunch",                   "Produce",  3.25),
    ("P9004", "Strawberries — 1 Pint",               "Produce",  5.50),
    ("P9005", "Baby Salad Mix — 5 oz",               "Produce",  4.00),
    ("P9006", "Zucchini — 2 lb Bag",                 "Produce",  3.75),
    ("P9007", "Rainbow Chard — Bunch",               "Produce",  3.00),
    ("P9008", "Cherry Tomatoes — 1 Pint",            "Produce",  4.25),
    ("M9001", "Ground Alpaca — 1 lb",                "Meat",    14.00),
    ("M9002", "Alpaca Stew Cuts — 2 lb",             "Meat",    22.00),
    ("M9003", "Alpaca Roast — 3 lb",                 "Meat",    38.00),
]
print(f"Using {len(listing_pool)} hardcoded listing items")

# ── Buyers  ─────────────────────────────────────────────────────────────────
BUYERS = [
    (BUYER_PID, None, "Elena Kowalski",     "elena.kowalski@harvesttable.com",   "720-555-0191"),
    (BUYER_PID, None, "Marcus Chen",        "marcus@embergrillbar.com",           "720-555-0248"),
    (BUYER_PID, None, "Priya Nair",         "pnair@rootskitchen.com",             "303-555-0312"),
    (BUYER_PID, None, "James Whitfield",    "j.whitfield@boulderlocavore.com",    "720-555-0437"),
    (BUYER_PID, None, "Sofia Ramirez",      "sofia@frontrancheats.com",           "970-555-0158"),
    (BUYER_PID, None, "Garrett Olson",      "garrett@coloradofoodco.com",         "720-555-0524"),
    (BUYER_PID, None, "Avery Brooks",       "avery.brooks@mountainfresh.net",     "303-555-0677"),
    (BUYER_PID, None, "Diana Osei",         "diana@longmontcommunity.org",        "303-555-0789"),
]

DELIVERY_METHODS = ["pickup", "delivery", "pickup", "delivery", "pickup"]
DELIVERY_ADDRS   = [
    None,
    "1420 Pearl St, Boulder CO 80302",
    None,
    "882 Main St, Longmont CO 80501",
    None,
    "3301 Arapahoe Ave, Boulder CO 80303",
    None,
    "555 Kimbark St, Longmont CO 80501",
]

# ── Order definitions  (OrderNumber, status, days_ago, items) ───────────────
# items = [(listing_pool_index, qty, notes)]
ORDERS = [
    # --- PENDING (5 orders)
    ("FW-2026-0101", "pending",    1,  [(0,4,None), (2,6,"Please pack separately")]),
    ("FW-2026-0102", "pending",    1,  [(5,3,"Ground only — no organ")]),
    ("FW-2026-0103", "pending",    2,  [(1,2,None), (3,12,None)]),
    ("FW-2026-0104", "pending",    3,  [(4,8,None)]),
    ("FW-2026-0105", "pending",    3,  [(0,6,None), (6,4,"Vacuum seal please")]),
    # --- CONFIRMED (4 orders)
    ("FW-2026-0091", "confirmed",  5,  [(2,10,None), (3,6,None)]),
    ("FW-2026-0092", "confirmed",  6,  [(5,5,None)]),
    ("FW-2026-0093", "confirmed",  7,  [(0,8,"Heirloom mix if possible"), (4,4,None)]),
    ("FW-2026-0094", "confirmed",  8,  [(1,3,None), (2,8,None)]),
    # --- SHIPPED (3 orders)
    ("FW-2026-0081", "shipped",   12,  [(5,4,None), (6,2,None)]),
    ("FW-2026-0082", "shipped",   14,  [(0,10,None), (3,8,None)]),
    ("FW-2026-0083", "shipped",   15,  [(4,6,None)]),
    # --- DELIVERED (3 orders)
    ("FW-2026-0071", "delivered", 21,  [(0,12,"Bring to side door"), (2,10,None)]),
    ("FW-2026-0072", "delivered", 24,  [(5,6,None), (6,3,None)]),
    ("FW-2026-0073", "delivered", 28,  [(1,4,None), (4,8,None), (3,10,None)]),
]

TRACKING_PREFIXES = ["1Z999AA1", "1Z888BB2", "1Z777CC3", "9400111"]

added_orders = 0
added_items  = 0

for i, (order_num, final_status, days_ago, items_def) in enumerate(ORDERS):
    # Idempotent check
    if first("SELECT OrderID FROM MarketplaceOrders WHERE OrderNumber=:n", {"n": order_num}):
        print(f"  Skip (exists): {order_num}")
        continue

    buyer = BUYERS[i % len(BUYERS)]
    buyer_pid, buyer_bid, buyer_name, buyer_email, buyer_phone = buyer
    d_method = DELIVERY_METHODS[i % len(DELIVERY_METHODS)]
    d_addr   = DELIVERY_ADDRS[i % len(DELIVERY_ADDRS)] if d_method == "delivery" else None
    created_at = datetime.datetime.now() - datetime.timedelta(days=days_ago)

    # Calculate totals
    subtotal = 0.0
    line_items = []
    for (lidx, qty, notes) in items_def:
        listing_id, title, ptype, unit_price = listing_pool[lidx % len(listing_pool)]
        line_total    = round(unit_price * qty, 2)
        platform_fee  = round(line_total * 0.025, 2)
        seller_payout = round(line_total - platform_fee, 2)
        subtotal += line_total
        line_items.append((listing_id, title, ptype, qty, unit_price, line_total, platform_fee, seller_payout, notes))

    subtotal     = round(subtotal, 2)
    platform_fee = round(subtotal * 0.025, 2)
    total_amount = round(subtotal + platform_fee, 2)

    req_date = (created_at + datetime.timedelta(days=random.randint(3, 7))).date()

    # Insert order
    order_id = first("""
        INSERT INTO MarketplaceOrders
            (OrderNumber, BuyerPeopleID, BuyerBusinessID, BuyerName, BuyerEmail, BuyerPhone,
             DeliveryMethod, DeliveryAddress, RequestedDeliveryDate,
             Subtotal, PlatformFee, TotalAmount, PaymentStatus, OrderStatus, CreatedAt, UpdatedAt)
        OUTPUT INSERTED.OrderID
        VALUES
            (:num, :pid, :bid, :name, :email, :phone,
             :dm, :da, :rd,
             :sub, :fee, :tot, 'paid', :ostatus, :cat, :cat)
    """, {
        "num":     order_num,
        "pid":     buyer_pid,
        "bid":     buyer_bid,
        "name":    buyer_name,
        "email":   buyer_email,
        "phone":   buyer_phone,
        "dm":      d_method,
        "da":      d_addr,
        "rd":      req_date,
        "sub":     subtotal,
        "fee":     platform_fee,
        "tot":     total_amount,
        "ostatus": final_status if final_status == "delivered" else "active",
        "cat":     created_at,
    })

    # Insert items
    for (listing_id, title, ptype, qty, unit_price, line_total, pfee, payout, notes) in line_items:
        item_status = final_status

        # Set timestamps based on status
        confirmed_at = None
        shipped_at   = None
        delivered_at = None
        tracking     = None
        est_date     = req_date

        if item_status in ("confirmed", "shipped", "delivered"):
            confirmed_at = created_at + datetime.timedelta(hours=random.randint(4, 12))
        if item_status in ("shipped", "delivered"):
            shipped_at = confirmed_at + datetime.timedelta(days=random.randint(1, 3))
            tracking   = f"{random.choice(TRACKING_PREFIXES)}{random.randint(100000,999999)}"
        if item_status == "delivered":
            delivered_at = shipped_at + datetime.timedelta(days=random.randint(1, 2))

        q("""
            INSERT INTO MarketplaceOrderItems
                (OrderID, ListingID, SellerBusinessID, SellerName, ProductTitle, ProductType,
                 Quantity, UnitPrice, LineTotal, PlatformFee, SellerPayout, Notes,
                 SellerStatus, SellerConfirmedAt, ShippedAt, DeliveredAt,
                 TrackingNumber, EstimatedDeliveryDate, CreatedAt, UpdatedAt)
            VALUES
                (:oid, :lid, :sbid, :sname, :title, :ptype,
                 :qty, :up, :lt, :pf, :sp, :notes,
                 :status, :cat, :sat, :dat,
                 :track, :edate, :created, :created)
        """, {
            "oid":     order_id,
            "lid":     listing_id,
            "sbid":    BID,
            "sname":   SELLER_NAME,
            "title":   title,
            "ptype":   ptype,
            "qty":     qty,
            "up":      unit_price,
            "lt":      line_total,
            "pf":      pfee,
            "sp":      payout,
            "notes":   notes,
            "status":  item_status,
            "cat":     confirmed_at,
            "sat":     shipped_at,
            "dat":     delivered_at,
            "track":   tracking,
            "edate":   est_date,
            "created": created_at,
        })
        added_items += 1

    db.commit()
    added_orders += 1
    print(f"  Created {order_num}  ({final_status})  items={len(line_items)}")

print(f"\nDone. Added {added_orders} orders, {added_items} order items.")
