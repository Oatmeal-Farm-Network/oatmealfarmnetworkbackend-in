# marketplace.py
# FastAPI routes for the Farm2Restaurant Marketplace (SQLAlchemy version)
# Mount: app.include_router(marketplace_router, prefix="/api/marketplace")

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
import os

marketplace_router = APIRouter()

PLATFORM_FEE_PERCENT = 2.5


# ============================================================
# MODELS
# ============================================================

class ListingCreate(BaseModel):
    BusinessID: int
    ProductType: str
    SourceID: int = 0
    Title: str
    Description: Optional[str] = None
    CategoryName: Optional[str] = None
    UnitPrice: float
    WholesalePrice: Optional[float] = None
    UnitLabel: Optional[str] = 'each'
    QuantityAvailable: float = 0
    MinOrderQuantity: float = 1
    MaxOrderQuantity: Optional[float] = None
    ImageURL: Optional[str] = None
    IsOrganic: bool = False
    Weight: Optional[float] = None
    WeightUnit: Optional[str] = None
    Tags: Optional[str] = None
    DeliveryOptions: Optional[str] = 'pickup'
    AvailableDate: Optional[str] = None

class CartItemAdd(BaseModel):
    BuyerPeopleID: int
    BuyerBusinessID: Optional[int] = None
    ListingID: int
    Quantity: float
    Notes: Optional[str] = None

class CartItemUpdate(BaseModel):
    Quantity: float
    Notes: Optional[str] = None

class CheckoutRequest(BaseModel):
    BuyerPeopleID: int
    BuyerBusinessID: Optional[int] = None
    DeliveryMethod: str = 'pickup'
    DeliveryAddressID: Optional[int] = None
    DeliveryAddress: Optional[str] = None
    DeliveryNotes: Optional[str] = None
    RequestedDeliveryDate: Optional[str] = None

class SellerConfirmation(BaseModel):
    OrderItemID: int
    Status: str
    RejectionReason: Optional[str] = None
    EstimatedDeliveryDate: Optional[str] = None

class ShipmentUpdate(BaseModel):
    OrderItemID: int
    TrackingNumber: Optional[str] = None


def rows_to_dicts(result):
    """Convert SQLAlchemy result rows to list of dicts"""
    if hasattr(result, 'mappings'):
        return [dict(r) for r in result.mappings()]
    return [dict(r._mapping) for r in result]


def row_to_dict(row):
    """Convert a single row to dict"""
    if row is None:
        return None
    if hasattr(row, '_mapping'):
        return dict(row._mapping)
    return dict(row)


# ============================================================
# 1. PRODUCT CATALOG - PUBLIC
# ============================================================

@marketplace_router.get("/catalog")
def get_catalog(
    search: str = "",
    category: str = "",
    product_type: str = "",
    seller_id: Optional[int] = None,
    is_organic: Optional[bool] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    sort_by: str = "newest",
    page: int = 1,
    per_page: int = 24,
    db: Session = Depends(get_db),
):
    conditions = ["ml.IsActive = 1", "ml.QuantityAvailable > 0"]
    params = {}

    if search:
        conditions.append("(ml.Title LIKE :search OR ml.Description LIKE :search OR ml.Tags LIKE :search OR ml.CategoryName LIKE :search)")
        params["search"] = f"%{search}%"
    if category:
        conditions.append("ml.CategoryName = :category")
        params["category"] = category
    if product_type:
        conditions.append("ml.ProductType = :product_type")
        params["product_type"] = product_type
    if seller_id:
        conditions.append("ml.BusinessID = :seller_id")
        params["seller_id"] = seller_id
    if is_organic is not None:
        conditions.append("ml.IsOrganic = :is_organic")
        params["is_organic"] = 1 if is_organic else 0
    if min_price is not None:
        conditions.append("ml.UnitPrice >= :min_price")
        params["min_price"] = min_price
    if max_price is not None:
        conditions.append("ml.UnitPrice <= :max_price")
        params["max_price"] = max_price

    where = " AND ".join(conditions)
    order_map = {"newest": "ml.CreatedAt DESC", "price_low": "ml.UnitPrice ASC", "price_high": "ml.UnitPrice DESC", "name": "ml.Title ASC"}
    order_by = order_map.get(sort_by, "ml.CreatedAt DESC")

    total = db.execute(text(f"SELECT COUNT(*) FROM MarketplaceListings ml WHERE {where}"), params).scalar()

    offset = (page - 1) * per_page
    params["offset"] = offset
    params["per_page"] = per_page

    rows = db.execute(text(f"""
        SELECT ml.*, b.BusinessName AS SellerName, b.PickupAvailable, b.ShippingAvailable, b.DeliveryRadius,
               a.City AS SellerCity, a.State AS SellerState
        FROM MarketplaceListings ml
        JOIN Business b ON ml.BusinessID = b.BusinessID
        LEFT JOIN Address a ON b.AddressID = a.AddressID
        WHERE {where}
        ORDER BY {order_by}
        OFFSET :offset ROWS FETCH NEXT :per_page ROWS ONLY
    """), params)
    listings = rows_to_dicts(rows)

    cats = db.execute(text("SELECT DISTINCT CategoryName FROM MarketplaceListings WHERE IsActive = 1 AND CategoryName IS NOT NULL ORDER BY CategoryName"))
    categories = [r[0] for r in cats]

    return {
        "listings": listings, "total": total, "page": page, "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page, "categories": categories,
    }


@marketplace_router.get("/catalog/{listing_id}")
def get_listing_detail(listing_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT ml.*, b.BusinessName AS SellerName, b.PickupAvailable, b.ShippingAvailable, b.DeliveryRadius,
               a.City AS SellerCity, a.State AS SellerState, a.Zip AS SellerZip,
               p.PeopleFirstName AS SellerFirstName
        FROM MarketplaceListings ml
        JOIN Business b ON ml.BusinessID = b.BusinessID
        LEFT JOIN Address a ON b.AddressID = a.AddressID
        LEFT JOIN People p ON b.PeopleID = p.PeopleID
        WHERE ml.ListingID = :id
    """), {"id": listing_id}).fetchone()
    if not row:
        raise HTTPException(404, "Listing not found")
    listing = row_to_dict(row)

    related = db.execute(text("""
        SELECT TOP 6 ListingID, Title, UnitPrice, UnitLabel, ImageURL, CategoryName
        FROM MarketplaceListings WHERE BusinessID = :bid AND ListingID != :lid AND IsActive = 1 ORDER BY NEWID()
    """), {"bid": listing["BusinessID"], "lid": listing_id})
    listing["relatedListings"] = rows_to_dicts(related)

    reviews = db.execute(text("""
        SELECT r.Rating, r.ReviewText, r.CreatedAt, p.PeopleFirstName AS ReviewerName
        FROM MarketplaceReviews r JOIN People p ON r.ReviewerPeopleID = p.PeopleID
        WHERE r.ListingID = :lid AND r.IsPublic = 1 ORDER BY r.CreatedAt DESC
    """), {"lid": listing_id})
    listing["reviews"] = rows_to_dicts(reviews)

    return listing


@marketplace_router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT CategoryName, ProductType, COUNT(*) AS Count
        FROM MarketplaceListings WHERE IsActive = 1 AND QuantityAvailable > 0
        GROUP BY CategoryName, ProductType ORDER BY CategoryName
    """))
    return {"categories": rows_to_dicts(rows)}


@marketplace_router.get("/sellers")
def get_sellers(search: str = "", db: Session = Depends(get_db)):
    params = {}
    where_extra = ""
    if search:
        where_extra = "AND (b.BusinessName LIKE :search OR a.City LIKE :search OR a.State LIKE :search)"
        params["search"] = f"%{search}%"

    rows = db.execute(text(f"""
        SELECT b.BusinessID, b.BusinessName, b.PickupAvailable, b.ShippingAvailable, b.DeliveryRadius,
               a.City, a.State, COUNT(DISTINCT ml.ListingID) AS ListingCount
        FROM Business b
        JOIN MarketplaceListings ml ON b.BusinessID = ml.BusinessID
        LEFT JOIN Address a ON b.AddressID = a.AddressID
        WHERE ml.IsActive = 1 {where_extra}
        GROUP BY b.BusinessID, b.BusinessName, b.PickupAvailable, b.ShippingAvailable, b.DeliveryRadius, a.City, a.State
        ORDER BY ListingCount DESC
    """), params)
    return {"sellers": rows_to_dicts(rows)}


# ============================================================
# 2. LISTING MANAGEMENT
# ============================================================

@marketplace_router.post("/listings")
def create_listing(data: ListingCreate, db: Session = Depends(get_db)):
    db.execute(text("""
        INSERT INTO MarketplaceListings (BusinessID, ProductType, SourceID, Title, Description,
            CategoryName, UnitPrice, WholesalePrice, UnitLabel, QuantityAvailable,
            MinOrderQuantity, MaxOrderQuantity, ImageURL, IsOrganic, Weight, WeightUnit,
            Tags, DeliveryOptions, AvailableDate, IsActive)
        VALUES (:bid, :pt, :sid, :title, :desc, :cat, :price, :wprice, :unit, :qty,
            :minq, :maxq, :img, :org, :wt, :wu, :tags, :dopt, :avail, 1)
    """), {
        "bid": data.BusinessID, "pt": data.ProductType, "sid": data.SourceID,
        "title": data.Title, "desc": data.Description, "cat": data.CategoryName,
        "price": data.UnitPrice, "wprice": data.WholesalePrice, "unit": data.UnitLabel,
        "qty": data.QuantityAvailable, "minq": data.MinOrderQuantity, "maxq": data.MaxOrderQuantity,
        "img": data.ImageURL, "org": 1 if data.IsOrganic else 0, "wt": data.Weight,
        "wu": data.WeightUnit, "tags": data.Tags, "dopt": data.DeliveryOptions, "avail": data.AvailableDate,
    })
    db.commit()
    lid = db.execute(text("SELECT TOP 1 ListingID FROM MarketplaceListings ORDER BY ListingID DESC")).scalar()
    return {"ListingID": lid, "message": "Listing created."}


@marketplace_router.get("/listings/seller/{business_id}")
def get_seller_listings(business_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT * FROM MarketplaceListings WHERE BusinessID = :bid ORDER BY CreatedAt DESC"), {"bid": business_id})
    return {"listings": rows_to_dicts(rows)}


@marketplace_router.put("/listings/{listing_id}")
def update_listing(listing_id: int, data: dict, db: Session = Depends(get_db)):
    allowed = {'Title', 'Description', 'CategoryName', 'UnitPrice', 'WholesalePrice', 'UnitLabel',
               'QuantityAvailable', 'MinOrderQuantity', 'MaxOrderQuantity', 'ImageURL', 'IsOrganic',
               'Weight', 'WeightUnit', 'Tags', 'DeliveryOptions', 'AvailableDate', 'IsActive', 'IsFeatured'}
    sets = []
    params = {"lid": listing_id}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k} = :{k}")
            params[k] = v
    if not sets:
        raise HTTPException(400, "No valid fields")
    sets.append("UpdatedAt = GETDATE()")
    db.execute(text(f"UPDATE MarketplaceListings SET {', '.join(sets)} WHERE ListingID = :lid"), params)
    db.commit()
    return {"message": "Listing updated."}


@marketplace_router.delete("/listings/{listing_id}")
def delete_listing(listing_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE MarketplaceListings SET IsActive = 0 WHERE ListingID = :lid"), {"lid": listing_id})
    db.commit()
    return {"message": "Listing deactivated."}


# ============================================================
# 3. SHOPPING CART
# ============================================================

@marketplace_router.get("/cart/{people_id}")
def get_cart(people_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT ci.*, ml.Title, ml.ProductType, ml.UnitLabel, ml.ImageURL, ml.QuantityAvailable,
               b.BusinessName AS SellerName, b.BusinessID AS SellerBusinessID
        FROM CartItems ci
        JOIN MarketplaceListings ml ON ci.ListingID = ml.ListingID
        JOIN Business b ON ci.SellerBusinessID = b.BusinessID
        WHERE ci.BuyerPeopleID = :pid ORDER BY b.BusinessName, ci.AddedAt
    """), {"pid": people_id})
    items = rows_to_dicts(rows)

    sellers = {}
    for item in items:
        sid = item["SellerBusinessID"]
        if sid not in sellers:
            sellers[sid] = {"SellerBusinessID": sid, "SellerName": item["SellerName"], "items": [], "subtotal": 0}
        item["lineTotal"] = round(float(item["Quantity"]) * float(item["UnitPrice"]), 2)
        sellers[sid]["items"].append(item)
        sellers[sid]["subtotal"] += item["lineTotal"]

    seller_list = list(sellers.values())
    subtotal = sum(s["subtotal"] for s in seller_list)
    fee = round(subtotal * PLATFORM_FEE_PERCENT / 100, 2)

    return {"sellers": seller_list, "itemCount": len(items), "subtotal": subtotal, "platformFee": fee, "total": round(subtotal + fee, 2)}


@marketplace_router.post("/cart")
def add_to_cart(data: CartItemAdd, db: Session = Depends(get_db)):
    listing = db.execute(text("SELECT BusinessID, UnitPrice, QuantityAvailable FROM MarketplaceListings WHERE ListingID = :lid AND IsActive = 1"), {"lid": data.ListingID}).fetchone()
    if not listing:
        raise HTTPException(404, "Listing not found or inactive")

    seller_bid, unit_price, qty_avail = listing
    if data.Quantity > qty_avail:
        raise HTTPException(400, f"Only {qty_avail} available")

    existing = db.execute(text("SELECT CartItemID, Quantity FROM CartItems WHERE BuyerPeopleID = :pid AND ListingID = :lid"), {"pid": data.BuyerPeopleID, "lid": data.ListingID}).fetchone()
    if existing:
        new_qty = float(existing[1]) + data.Quantity
        if new_qty > qty_avail:
            raise HTTPException(400, f"Only {qty_avail} available (you have {existing[1]} in cart)")
        db.execute(text("UPDATE CartItems SET Quantity = :qty, UpdatedAt = GETDATE() WHERE CartItemID = :cid"), {"qty": new_qty, "cid": existing[0]})
    else:
        db.execute(text("""
            INSERT INTO CartItems (BuyerPeopleID, BuyerBusinessID, ListingID, SellerBusinessID, Quantity, UnitPrice, Notes)
            VALUES (:pid, :bid, :lid, :sbid, :qty, :price, :notes)
        """), {"pid": data.BuyerPeopleID, "bid": data.BuyerBusinessID, "lid": data.ListingID,
               "sbid": seller_bid, "qty": data.Quantity, "price": float(unit_price), "notes": data.Notes})
    db.commit()
    return {"message": "Added to cart."}


@marketplace_router.put("/cart/{cart_item_id}")
def update_cart_item(cart_item_id: int, data: CartItemUpdate, db: Session = Depends(get_db)):
    if data.Quantity <= 0:
        db.execute(text("DELETE FROM CartItems WHERE CartItemID = :cid"), {"cid": cart_item_id})
    else:
        db.execute(text("UPDATE CartItems SET Quantity = :qty, Notes = :notes, UpdatedAt = GETDATE() WHERE CartItemID = :cid"),
                   {"qty": data.Quantity, "notes": data.Notes, "cid": cart_item_id})
    db.commit()
    return {"message": "Cart updated."}


@marketplace_router.delete("/cart/{cart_item_id}")
def remove_from_cart(cart_item_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM CartItems WHERE CartItemID = :cid"), {"cid": cart_item_id})
    db.commit()
    return {"message": "Removed from cart."}


@marketplace_router.delete("/cart/clear/{people_id}")
def clear_cart(people_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM CartItems WHERE BuyerPeopleID = :pid"), {"pid": people_id})
    db.commit()
    return {"message": "Cart cleared."}


# ============================================================
# 4. CHECKOUT & ORDERS
# ============================================================

@marketplace_router.post("/checkout")
def checkout(data: CheckoutRequest, db: Session = Depends(get_db)):
    cart_rows = db.execute(text("""
        SELECT ci.*, ml.Title, ml.ProductType, ml.QuantityAvailable, b.BusinessName AS SellerName
        FROM CartItems ci
        JOIN MarketplaceListings ml ON ci.ListingID = ml.ListingID
        JOIN Business b ON ci.SellerBusinessID = b.BusinessID
        WHERE ci.BuyerPeopleID = :pid
    """), {"pid": data.BuyerPeopleID})
    cart_items = rows_to_dicts(cart_rows)

    if not cart_items:
        raise HTTPException(400, "Cart is empty")

    for item in cart_items:
        if float(item["Quantity"]) > float(item["QuantityAvailable"]):
            raise HTTPException(400, f"'{item['Title']}' only has {item['QuantityAvailable']} available")

    buyer = db.execute(text("SELECT PeopleFirstName, PeopleLastName, PeopleEmail, PeoplePhone FROM People WHERE PeopleID = :pid"),
                       {"pid": data.BuyerPeopleID}).fetchone()
    if not buyer:
        raise HTTPException(404, "Buyer not found")

    buyer_name = f"{buyer[0]} {buyer[1]}"
    subtotal = sum(round(float(i["Quantity"]) * float(i["UnitPrice"]), 2) for i in cart_items)
    fee = round(subtotal * PLATFORM_FEE_PERCENT / 100, 2)
    total = round(subtotal + fee, 2)

    # Generate order number
    now = datetime.now()
    prefix = f"OFN-{now.strftime('%Y%m%d')}"
    count = db.execute(text("SELECT COUNT(*) FROM MarketplaceOrders WHERE OrderNumber LIKE :prefix"), {"prefix": f"{prefix}%"}).scalar() + 1
    order_number = f"{prefix}-{count:03d}"

    db.execute(text("""
        INSERT INTO MarketplaceOrders (OrderNumber, BuyerPeopleID, BuyerBusinessID, BuyerName, BuyerEmail, BuyerPhone,
            DeliveryMethod, DeliveryAddressID, DeliveryAddress, DeliveryNotes, RequestedDeliveryDate,
            Subtotal, PlatformFee, TotalAmount, PaymentStatus, OrderStatus)
        VALUES (:onum, :pid, :bid, :bname, :bemail, :bphone, :dm, :daid, :daddr, :dnotes, :ddate,
            :sub, :fee, :total, 'pending', 'pending')
    """), {"onum": order_number, "pid": data.BuyerPeopleID, "bid": data.BuyerBusinessID,
           "bname": buyer_name, "bemail": buyer[2], "bphone": buyer[3],
           "dm": data.DeliveryMethod, "daid": data.DeliveryAddressID, "daddr": data.DeliveryAddress,
           "dnotes": data.DeliveryNotes, "ddate": data.RequestedDeliveryDate,
           "sub": subtotal, "fee": fee, "total": total})
    db.commit()

    order_id = db.execute(text("SELECT TOP 1 OrderID FROM MarketplaceOrders ORDER BY OrderID DESC")).scalar()

    for item in cart_items:
        line_total = round(float(item["Quantity"]) * float(item["UnitPrice"]), 2)
        item_fee = round(line_total * PLATFORM_FEE_PERCENT / 100, 2)
        seller_payout = round(line_total - item_fee, 2)

        db.execute(text("""
            INSERT INTO MarketplaceOrderItems (OrderID, ListingID, SellerBusinessID, SellerName,
                ProductTitle, ProductType, Quantity, UnitPrice, LineTotal, PlatformFee, SellerPayout,
                Notes, SellerStatus)
            VALUES (:oid, :lid, :sbid, :sname, :title, :ptype, :qty, :price, :lt, :fee, :payout, :notes, 'pending')
        """), {"oid": order_id, "lid": item["ListingID"], "sbid": item["SellerBusinessID"],
               "sname": item["SellerName"], "title": item["Title"], "ptype": item["ProductType"],
               "qty": float(item["Quantity"]), "price": float(item["UnitPrice"]),
               "lt": line_total, "fee": item_fee, "payout": seller_payout, "notes": item.get("Notes")})

        db.execute(text("UPDATE MarketplaceListings SET QuantityAvailable = QuantityAvailable - :qty WHERE ListingID = :lid"),
                   {"qty": float(item["Quantity"]), "lid": item["ListingID"]})

    db.execute(text("INSERT INTO OrderStatusHistory (OrderID, NewStatus, ChangedByPeopleID, ChangedByRole, Notes) VALUES (:oid, 'pending', :pid, 'buyer', 'Order placed')"),
               {"oid": order_id, "pid": data.BuyerPeopleID})
    db.execute(text("INSERT INTO PlatformFees (OrderID, FeeAmount, FeePercent, Status) VALUES (:oid, :fee, :pct, 'pending')"),
               {"oid": order_id, "fee": fee, "pct": PLATFORM_FEE_PERCENT})
    db.execute(text("DELETE FROM CartItems WHERE BuyerPeopleID = :pid"), {"pid": data.BuyerPeopleID})
    db.commit()

    # Send emails (non-blocking)
    try:
        from marketplace_emails import send_order_placed_buyer, send_order_placed_seller, send_admin_order_notification
        send_order_placed_buyer(order_id, db)
        seller_ids = set(i["SellerBusinessID"] for i in cart_items)
        for sid in seller_ids:
            send_order_placed_seller(order_id, sid, db)
        send_admin_order_notification(order_id, db)
    except Exception as e:
        print(f"[marketplace] Email error: {e}")

    return {"OrderID": order_id, "OrderNumber": order_number, "Total": total, "Subtotal": subtotal,
            "PlatformFee": fee, "ItemCount": len(cart_items), "message": "Order placed successfully."}


# ============================================================
# 5. SELLER ORDER MANAGEMENT
# ============================================================

@marketplace_router.get("/orders/seller/{business_id}")
def get_seller_orders(business_id: int, status: str = "", db: Session = Depends(get_db)):
    params = {"bid": business_id}
    where_extra = ""
    if status:
        where_extra = "AND oi.SellerStatus = :status"
        params["status"] = status

    rows = db.execute(text(f"""
        SELECT oi.*, o.OrderNumber, o.BuyerName, o.BuyerEmail, o.BuyerPhone,
               o.DeliveryMethod, o.DeliveryAddress, o.RequestedDeliveryDate, o.OrderStatus
        FROM MarketplaceOrderItems oi
        JOIN MarketplaceOrders o ON oi.OrderID = o.OrderID
        WHERE oi.SellerBusinessID = :bid {where_extra}
        ORDER BY oi.CreatedAt DESC
    """), params)
    return {"orders": rows_to_dicts(rows)}


@marketplace_router.post("/orders/seller/confirm")
def seller_confirm(data: SellerConfirmation, db: Session = Depends(get_db)):
    if data.Status == "confirmed":
        db.execute(text("UPDATE MarketplaceOrderItems SET SellerStatus = 'confirmed', SellerConfirmedAt = GETDATE(), EstimatedDeliveryDate = :edd WHERE OrderItemID = :oiid"),
                   {"edd": data.EstimatedDeliveryDate, "oiid": data.OrderItemID})
    elif data.Status == "rejected":
        db.execute(text("UPDATE MarketplaceOrderItems SET SellerStatus = 'rejected', SellerRejectedAt = GETDATE(), RejectionReason = :reason WHERE OrderItemID = :oiid"),
                   {"reason": data.RejectionReason, "oiid": data.OrderItemID})
        item = db.execute(text("SELECT ListingID, Quantity FROM MarketplaceOrderItems WHERE OrderItemID = :oiid"), {"oiid": data.OrderItemID}).fetchone()
        if item:
            db.execute(text("UPDATE MarketplaceListings SET QuantityAvailable = QuantityAvailable + :qty WHERE ListingID = :lid"), {"qty": float(item[1]), "lid": item[0]})

    order_id = db.execute(text("SELECT OrderID FROM MarketplaceOrderItems WHERE OrderItemID = :oiid"), {"oiid": data.OrderItemID}).scalar()
    counts = db.execute(text("""
        SELECT COUNT(*) AS Total, SUM(CASE WHEN SellerStatus='confirmed' THEN 1 ELSE 0 END) AS Confirmed,
               SUM(CASE WHEN SellerStatus='rejected' THEN 1 ELSE 0 END) AS Rejected,
               SUM(CASE WHEN SellerStatus='pending' THEN 1 ELSE 0 END) AS Pending
        FROM MarketplaceOrderItems WHERE OrderID = :oid
    """), {"oid": order_id}).fetchone()

    if counts[3] == 0:  # no pending
        if counts[1] > 0 and counts[2] > 0:
            new_status = "partially_confirmed"
        elif counts[1] > 0:
            new_status = "confirmed"
        else:
            new_status = "cancelled"
        db.execute(text("UPDATE MarketplaceOrders SET OrderStatus = :st, UpdatedAt = GETDATE() WHERE OrderID = :oid"), {"st": new_status, "oid": order_id})

        if counts[1] > 0:
            totals = db.execute(text("SELECT SUM(LineTotal), SUM(PlatformFee) FROM MarketplaceOrderItems WHERE OrderID = :oid AND SellerStatus = 'confirmed'"), {"oid": order_id}).fetchone()
            new_sub = float(totals[0] or 0)
            new_fee = float(totals[1] or 0)
            db.execute(text("UPDATE MarketplaceOrders SET Subtotal = :sub, PlatformFee = :fee, TotalAmount = :total, PaymentStatus = 'authorized' WHERE OrderID = :oid"),
                       {"sub": new_sub, "fee": new_fee, "total": round(new_sub + new_fee, 2), "oid": order_id})

    db.execute(text("INSERT INTO OrderStatusHistory (OrderID, OrderItemID, NewStatus, ChangedByRole, Notes) VALUES (:oid, :oiid, :st, 'seller', :notes)"),
               {"oid": order_id, "oiid": data.OrderItemID, "st": data.Status, "notes": data.RejectionReason or f"Item {data.Status}"})
    db.commit()

    # Send emails
    try:
        from marketplace_emails import send_item_status_buyer, send_ready_for_payment
        send_item_status_buyer(order_id, data.OrderItemID, data.Status, db)
        if counts[3] == 0 and counts[1] > 0:
            send_ready_for_payment(order_id, db)
    except Exception as e:
        print(f"[marketplace] Email error: {e}")

    return {"message": f"Order item {data.Status}.", "OrderID": order_id}


@marketplace_router.post("/orders/seller/ship")
def seller_ship(data: ShipmentUpdate, db: Session = Depends(get_db)):
    db.execute(text("UPDATE MarketplaceOrderItems SET SellerStatus = 'shipped', ShippedAt = GETDATE(), TrackingNumber = :tn WHERE OrderItemID = :oiid"),
               {"tn": data.TrackingNumber, "oiid": data.OrderItemID})
    order_id = db.execute(text("SELECT OrderID FROM MarketplaceOrderItems WHERE OrderItemID = :oiid"), {"oiid": data.OrderItemID}).scalar()
    db.execute(text("INSERT INTO OrderStatusHistory (OrderID, OrderItemID, NewStatus, ChangedByRole, Notes) VALUES (:oid, :oiid, 'shipped', 'seller', :notes)"),
               {"oid": order_id, "oiid": data.OrderItemID, "notes": f"Tracking: {data.TrackingNumber or 'N/A'}"})
    db.commit()

    try:
        from marketplace_emails import send_item_shipped
        send_item_shipped(order_id, data.OrderItemID, db)
    except Exception as e:
        print(f"[marketplace] Email error: {e}")

    return {"message": "Item marked as shipped."}


# ============================================================
# 6. BUYER ORDER MANAGEMENT
# ============================================================

@marketplace_router.get("/orders/buyer/{people_id}")
def get_buyer_orders(people_id: int, status: str = "", db: Session = Depends(get_db)):
    params = {"pid": people_id}
    where_extra = ""
    if status:
        where_extra = "AND o.OrderStatus = :status"
        params["status"] = status

    orders = rows_to_dicts(db.execute(text(f"SELECT o.* FROM MarketplaceOrders o WHERE o.BuyerPeopleID = :pid {where_extra} ORDER BY o.CreatedAt DESC"), params))
    for order in orders:
        items = db.execute(text("""
            SELECT oi.*, b.BusinessName AS SellerName FROM MarketplaceOrderItems oi
            JOIN Business b ON oi.SellerBusinessID = b.BusinessID WHERE oi.OrderID = :oid
        """), {"oid": order["OrderID"]})
        order["items"] = rows_to_dicts(items)

    return {"orders": orders}


@marketplace_router.get("/orders/{order_id}")
def get_order_detail(order_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT * FROM MarketplaceOrders WHERE OrderID = :oid"), {"oid": order_id}).fetchone()
    if not row:
        raise HTTPException(404, "Order not found")
    order = row_to_dict(row)

    items = db.execute(text("SELECT oi.*, b.BusinessName FROM MarketplaceOrderItems oi JOIN Business b ON oi.SellerBusinessID = b.BusinessID WHERE oi.OrderID = :oid"), {"oid": order_id})
    order["items"] = rows_to_dicts(items)

    history = db.execute(text("SELECT * FROM OrderStatusHistory WHERE OrderID = :oid ORDER BY CreatedAt DESC"), {"oid": order_id})
    order["history"] = rows_to_dicts(history)

    return order


@marketplace_router.post("/orders/{order_id}/deliver")
def mark_delivered(order_id: int, order_item_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE MarketplaceOrderItems SET SellerStatus = 'delivered', DeliveredAt = GETDATE() WHERE OrderItemID = :oiid AND OrderID = :oid"),
               {"oiid": order_item_id, "oid": order_id})
    counts = db.execute(text("""
        SELECT COUNT(*), SUM(CASE WHEN SellerStatus = 'delivered' THEN 1 ELSE 0 END)
        FROM MarketplaceOrderItems WHERE OrderID = :oid AND SellerStatus != 'rejected'
    """), {"oid": order_id}).fetchone()
    if counts[0] > 0 and counts[0] == counts[1]:
        db.execute(text("UPDATE MarketplaceOrders SET OrderStatus = 'delivered', UpdatedAt = GETDATE() WHERE OrderID = :oid"), {"oid": order_id})
    db.commit()

    try:
        from marketplace_emails import send_delivery_confirmed
        send_delivery_confirmed(order_id, order_item_id, db)
    except Exception as e:
        print(f"[marketplace] Email error: {e}")

    return {"message": "Delivery confirmed."}


# ============================================================
# 7. STRIPE CONNECT ONBOARDING
# ============================================================

@marketplace_router.post("/stripe/onboard/{business_id}")
def stripe_onboard(business_id: int, db: Session = Depends(get_db)):
    try:
        import stripe
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        ofn_url = os.getenv("OFN_BASE_URL", "https://oatmealfarmnetwork.com")

        account = stripe.Account.create(type="express", metadata={"business_id": str(business_id)})

        db.execute(text("INSERT INTO StripeAccounts (BusinessID, StripeConnectAccountID) VALUES (:bid, :sid)"), {"bid": business_id, "sid": account.id})
        db.execute(text("UPDATE Business SET StripeConnectAccountID = :sid WHERE BusinessID = :bid"), {"sid": account.id, "bid": business_id})
        db.commit()

        link = stripe.AccountLink.create(
            account=account.id,
            refresh_url=f"{ofn_url}/account?BusinessID={business_id}&stripe=retry",
            return_url=f"{ofn_url}/account?BusinessID={business_id}&stripe=success",
            type="account_onboarding",
        )
        return {"url": link.url, "stripe_account_id": account.id}
    except Exception as e:
        raise HTTPException(500, str(e))


@marketplace_router.get("/stripe/status/{business_id}")
def stripe_status(business_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT StripeConnectAccountID FROM StripeAccounts WHERE BusinessID = :bid"), {"bid": business_id}).fetchone()
    if not row or not row[0]:
        return {"connected": False, "onboarding_complete": False}
    try:
        import stripe
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        account = stripe.Account.retrieve(row[0])
        db.execute(text("UPDATE StripeAccounts SET OnboardingComplete = :oc, PayoutsEnabled = :pe, ChargesEnabled = :ce, UpdatedAt = GETDATE() WHERE BusinessID = :bid"),
                   {"oc": 1 if account.details_submitted else 0, "pe": 1 if account.payouts_enabled else 0, "ce": 1 if account.charges_enabled else 0, "bid": business_id})
        db.commit()
        return {"connected": True, "onboarding_complete": account.details_submitted, "payouts_enabled": account.payouts_enabled, "charges_enabled": account.charges_enabled, "stripe_account_id": row[0]}
    except Exception as e:
        return {"connected": False, "error": str(e)}
