# routers/sfproducts.py
# SFProducts catalog API
# Mount: app.include_router(sfproducts.router)

from database import get_db, engine
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from pydantic import BaseModel
from decimal import Decimal

router = APIRouter(prefix="/api/sfproducts", tags=["sfproducts"])

# ── Auto-create tables ────────────────────────────────────────────────────────
try:
    with engine.begin() as _conn:
        _conn.execute(text("""
            IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='sfcategories')
            BEGIN
                CREATE TABLE sfcategories (
                    CatID     INT IDENTITY(1,1) PRIMARY KEY,
                    CatName   VARCHAR(200) NOT NULL,
                    SortOrder INT DEFAULT 0
                )
            END
        """))

        _conn.execute(text("""
            IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='sfsubcategories')
            BEGIN
                CREATE TABLE sfsubcategories (
                    SubCatID   INT IDENTITY(1,1) PRIMARY KEY,
                    CatID      INT NOT NULL,
                    SubCatName VARCHAR(200) NOT NULL,
                    SortOrder  INT DEFAULT 0
                )
            END
        """))

    # ── Seed default categories ───────────────────────────────────────────────────
    _SEED_DATA = [
        ("Yarn & Fiber",       ["Yarn", "Roving & Batting", "Raw Fleece", "Fiber Blends", "Spinning Fiber"]),
        ("Clothing",           ["Sweaters & Cardigans", "Hats & Scarves", "Gloves & Mittens", "Socks", "Dresses & Skirts", "Other Clothing"]),
        ("Blankets & Throws",  ["Blankets", "Throws", "Rugs & Weavings"]),
        ("Crafts & Handmade",  ["Felted Items", "Jewelry", "Pottery", "Candles & Soaps", "Other Crafts"]),
        ("Books & Guides",     ["Farming Books", "Craft Books", "Recipe Books"]),
        ("Home Decor",         ["Wall Art", "Decorative Items", "Pillows & Cushions"]),
        ("Outdoor & Equipment",["Farm Equipment", "Outdoor Gear", "Tools"]),
        ("Toys & Games",       ["Children's Toys", "Games & Puzzles"]),
        ("Other",              ["Miscellaneous"]),
    ]

    with engine.begin() as _conn:
        count = _conn.execute(text("SELECT COUNT(*) FROM sfcategories")).scalar()
        if count == 0:
            for sort_idx, (cat_name, subcats) in enumerate(_SEED_DATA):
                _conn.execute(text(
                    "INSERT INTO sfcategories (CatName, SortOrder) VALUES (:name, :sort)"
                ), {"name": cat_name, "sort": sort_idx})
                cat_id = _conn.execute(text("SELECT SCOPE_IDENTITY()")).scalar()
                for sub_idx, sub_name in enumerate(subcats):
                    _conn.execute(text(
                        "INSERT INTO sfsubcategories (CatID, SubCatName, SortOrder) VALUES (:cid, :name, :sort)"
                    ), {"cid": cat_id, "name": sub_name, "sort": sub_idx})
except Exception as e:
    print(f"[sfproducts] Database initialization skipped: {e}")


# ─────────────────────────────────────────────
# PYDANTIC MODELS
# ─────────────────────────────────────────────

class ProductCreate(BaseModel):
    BusinessID: int
    PeopleID: int
    prodName: str
    prodShortDescription: Optional[str] = None
    prodDescription: Optional[str] = None
    prodPrice: float = 0.0
    SalePrice: Optional[float] = None
    prodSaleIsActive: Optional[int] = 0
    prodCallforPrice: Optional[int] = 0
    prodCustomorder: Optional[int] = 0
    prodWeight: Optional[float] = None
    prodShip: Optional[int] = 0
    prodLength: Optional[float] = None
    prodWidth: Optional[float] = None
    prodHeight: Optional[float] = None
    ProdDimensions: Optional[str] = None
    prodMadeIn: Optional[str] = None
    prodCategoryId: Optional[int] = None
    prodSubCategoryId: Optional[int] = None
    ProdQuantityAvailable: Optional[int] = 0
    Materials: Optional[str] = None
    ProdAnimalID: Optional[int] = None
    ProdAnimalID2: Optional[int] = None
    ProdAnimalID3: Optional[int] = None
    FiberType1: Optional[str] = None
    FiberPercent1: Optional[float] = None
    FiberType2: Optional[str] = None
    FiberPercent2: Optional[float] = None
    FiberType3: Optional[str] = None
    FiberPercent3: Optional[float] = None
    FiberType4: Optional[str] = None
    FiberPercent4: Optional[float] = None
    FiberType5: Optional[str] = None
    FiberPercent5: Optional[float] = None
    Publishproduct: Optional[int] = 1
    ProdForSale: Optional[int] = 1


class ProductUpdate(BaseModel):
    prodName: Optional[str] = None
    prodShortDescription: Optional[str] = None
    prodDescription: Optional[str] = None
    prodPrice: Optional[float] = None
    SalePrice: Optional[float] = None
    prodSaleIsActive: Optional[int] = None
    prodCallforPrice: Optional[int] = None
    prodCustomorder: Optional[int] = None
    prodWeight: Optional[float] = None
    prodShip: Optional[int] = None
    prodLength: Optional[float] = None
    prodWidth: Optional[float] = None
    prodHeight: Optional[float] = None
    ProdDimensions: Optional[str] = None
    prodMadeIn: Optional[str] = None
    prodCategoryId: Optional[int] = None
    prodSubCategoryId: Optional[int] = None
    ProdQuantityAvailable: Optional[int] = None
    Materials: Optional[str] = None
    ProdAnimalID: Optional[int] = None
    ProdAnimalID2: Optional[int] = None
    ProdAnimalID3: Optional[int] = None
    FiberType1: Optional[str] = None
    FiberPercent1: Optional[float] = None
    FiberType2: Optional[str] = None
    FiberPercent2: Optional[float] = None
    FiberType3: Optional[str] = None
    FiberPercent3: Optional[float] = None
    FiberType4: Optional[str] = None
    FiberPercent4: Optional[float] = None
    FiberType5: Optional[str] = None
    FiberPercent5: Optional[float] = None
    Publishproduct: Optional[int] = None
    ProdForSale: Optional[int] = None


class PhotosUpdate(BaseModel):
    ProductImage1: Optional[str] = None
    ProductImage2: Optional[str] = None
    ProductImage3: Optional[str] = None
    ProductImage4: Optional[str] = None
    ProductImage5: Optional[str] = None
    ProductImage6: Optional[str] = None
    ProductImage7: Optional[str] = None
    ProductImage8: Optional[str] = None


class SizeCreate(BaseModel):
    Size: str
    ExtraCost: Optional[float] = 0.0
    PeopleID: int


class ColorCreate(BaseModel):
    Color: str
    PeopleID: int


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _ser_product(row: dict) -> dict:
    """Serialize a SFProducts row to a response dict."""
    m = dict(row)

    # Convert Decimal to float
    for key, val in m.items():
        if isinstance(val, Decimal):
            m[key] = float(val)

    # Synthetic ListingID
    m["ListingID"] = f"G{m.get('ProdID', '')}"

    # Build fiber_content list
    fibers = []
    for i in range(1, 6):
        ft = m.get(f"FiberType{i}")
        fp = m.get(f"FiberPercent{i}")
        if ft:
            entry = {"type": ft, "percent": float(fp) if fp is not None else None}
            fibers.append(entry)
    m["fiber_content"] = fibers

    return m


# ─────────────────────────────────────────────
# CATEGORIES
# ─────────────────────────────────────────────

@router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    cats = db.execute(text(
        "SELECT CatID, CatName, SortOrder FROM sfcategories ORDER BY SortOrder, CatName"
    )).fetchall()

    result = []
    for c in cats:
        cat = dict(c._mapping)
        subs = db.execute(text(
            "SELECT SubCatID, SubCatName, SortOrder FROM sfsubcategories WHERE CatID = :cid ORDER BY SortOrder, SubCatName"
        ), {"cid": cat["CatID"]}).fetchall()
        cat["subcategories"] = [dict(s._mapping) for s in subs]
        result.append(cat)
    return result


@router.get("/categories/{cat_id}/subcategories")
def get_subcategories(cat_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text(
        "SELECT SubCatID, SubCatName, SortOrder FROM sfsubcategories WHERE CatID = :cid ORDER BY SortOrder, SubCatName"
    ), {"cid": cat_id}).fetchall()
    return [dict(r._mapping) for r in rows]


# ─────────────────────────────────────────────
# PUBLIC BROWSE
# ─────────────────────────────────────────────

@router.get("/")
def list_products(
    business_id:   Optional[int]  = Query(None),
    cat_id:        Optional[int]  = Query(None),
    subcat_id:     Optional[int]  = Query(None),
    search:        Optional[str]  = Query(None),
    sort:          str            = Query("newest"),
    featured_only: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
):
    where = [
        "pr.Publishproduct = 1",
        "pr.ProdForSale = 1",
        "pr.ProdQuantityAvailable > 0",
    ]
    params = {}

    if business_id is not None:
        where.append("pr.BusinessID = :business_id")
        params["business_id"] = business_id
    if cat_id is not None:
        where.append("pr.prodCategoryId = :cat_id")
        params["cat_id"] = cat_id
    if subcat_id is not None:
        where.append("pr.prodSubCategoryId = :subcat_id")
        params["subcat_id"] = subcat_id
    if featured_only:
        where.append("pr.prodSaleIsActive = 1")
    if search and search.strip():
        sv = f"%{search.strip()}%"
        where.append("(pr.prodName LIKE :search OR pr.prodShortDescription LIKE :search OR sc.CatName LIKE :search)")
        params["search"] = sv

    sort_clause = {
        "price_asc":  "pr.prodPrice ASC",
        "price_desc": "pr.prodPrice DESC",
        "name_asc":   "pr.prodName ASC",
    }.get(sort, "pr.ProdID DESC")

    rows = db.execute(text(f"""
        SELECT pr.ProdID AS SourceID, 'product' AS ProductType, pr.BusinessID,
               NULL AS IngredientID, pr.prodName AS Title,
               pr.prodShortDescription AS Description,
               sc.CatName AS CategoryName,
               pr.prodPrice AS UnitPrice, pr.SalePrice AS WholesalePrice,
               'each' AS UnitLabel,
               CAST(pr.ProdQuantityAvailable AS DECIMAL(10,2)) AS QuantityAvailable,
               0 AS IsOrganic, 1 AS IsLocal, NULL AS AvailableDate, NULL AS ExpirationDate,
               COALESCE(pp.ProductImage1, pr.prodImageSmallPath) AS ImageURL,
               b.BusinessName AS SellerName,
               a.AddressCity AS SellerCity, a.AddressState AS SellerState,
               pr.prodSaleIsActive AS IsFeatured,
               pr.ProdID, pr.prodMadeIn, pr.prodCallforPrice
        FROM SFProducts pr
        JOIN Business b ON pr.BusinessID = b.BusinessID
        LEFT JOIN Address a ON b.AddressID = a.AddressID
        LEFT JOIN productsphotos pp ON pp.ID = pr.ProdID
        LEFT JOIN sfcategories sc ON sc.CatID = pr.prodCategoryId
        WHERE {" AND ".join(where)}
        ORDER BY {sort_clause}
    """), params).fetchall()

    result = []
    for r in rows:
        m = dict(r._mapping)
        m["ListingID"]         = f"G{m['ProdID']}"
        m["UnitPrice"]         = float(m["UnitPrice"]) if m["UnitPrice"] else 0.0
        m["WholesalePrice"]    = float(m["WholesalePrice"]) if m["WholesalePrice"] else None
        m["QuantityAvailable"] = float(m["QuantityAvailable"]) if m["QuantityAvailable"] else 0.0
        m["IsOrganic"]         = False
        m["IsLocal"]           = True
        m["IsFeatured"]        = bool(m.get("IsFeatured"))
        result.append(m)
    return result


@router.get("/seller")
def get_seller_products(business_id: int = Query(...), db: Session = Depends(get_db)):
    """All products for a seller including inactive."""
    rows = db.execute(text("""
        SELECT pr.ProdID, pr.prodName AS Title, pr.prodShortDescription,
               pr.prodPrice AS UnitPrice, pr.SalePrice, pr.prodSaleIsActive,
               pr.prodCallforPrice, pr.ProdQuantityAvailable AS QuantityAvailable,
               pr.Publishproduct, pr.ProdForSale, pr.prodCategoryId, pr.prodSubCategoryId,
               sc.CatName AS CategoryName,
               COALESCE(pp.ProductImage1, pr.prodImageSmallPath) AS ImageURL,
               pr.prodMadeIn, pr.prodCustomorder, pr.Materials
        FROM SFProducts pr
        LEFT JOIN sfcategories sc ON sc.CatID = pr.prodCategoryId
        LEFT JOIN productsphotos pp ON pp.ID = pr.ProdID
        WHERE pr.BusinessID = :bid
        ORDER BY pr.ProdID DESC
    """), {"bid": business_id}).fetchall()

    result = []
    for r in rows:
        m = dict(r._mapping)
        m["ListingID"] = f"G{m['ProdID']}"
        m["UnitPrice"] = float(m["UnitPrice"]) if m["UnitPrice"] else 0.0
        m["SalePrice"] = float(m["SalePrice"]) if m["SalePrice"] else None
        m["QuantityAvailable"] = float(m["QuantityAvailable"]) if m["QuantityAvailable"] else 0.0
        result.append(m)
    return result


@router.get("/{prod_id}")
def get_product(prod_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT pr.*,
               b.BusinessName AS SellerName,
               a.AddressCity AS SellerCity, a.AddressState AS SellerState,
               sc.CatName AS CategoryName, ssc.SubCatName
        FROM SFProducts pr
        JOIN Business b ON pr.BusinessID = b.BusinessID
        LEFT JOIN Address a ON b.AddressID = a.AddressID
        LEFT JOIN sfcategories sc ON sc.CatID = pr.prodCategoryId
        LEFT JOIN sfsubcategories ssc ON ssc.SubCatID = pr.prodSubCategoryId
        WHERE pr.ProdID = :pid AND pr.Publishproduct = 1
    """), {"pid": prod_id}).fetchone()

    if not row:
        raise HTTPException(404, "Product not found")

    m = _ser_product(dict(row._mapping))

    # Photos
    photos_row = db.execute(text(
        "SELECT * FROM productsphotos WHERE ID = :pid"
    ), {"pid": prod_id}).fetchone()
    if photos_row:
        ph = dict(photos_row._mapping)
        m["photos"] = [ph.get(f"ProductImage{i}") for i in range(1, 9)]
        m["photos"] = [p for p in m["photos"] if p]
    else:
        m["photos"] = []

    # Sizes
    sizes = db.execute(text(
        "SELECT * FROM productsizes WHERE ProductID = :pid ORDER BY SizeID"
    ), {"pid": prod_id}).fetchall()
    m["sizes"] = [dict(s._mapping) for s in sizes]

    # Colors
    colors = db.execute(text(
        "SELECT * FROM productcolor WHERE ProductID = :pid ORDER BY ColorID"
    ), {"pid": prod_id}).fetchall()
    m["colors"] = [dict(c._mapping) for c in colors]

    # Animals
    animal_ids = [m.get("ProdAnimalID"), m.get("ProdAnimalID2"), m.get("ProdAnimalID3")]
    animal_ids = [aid for aid in animal_ids if aid]
    if animal_ids:
        placeholders = ", ".join([f":aid{i}" for i in range(len(animal_ids))])
        params = {f"aid{i}": v for i, v in enumerate(animal_ids)}
        animals = db.execute(text(
            f"SELECT * FROM animals WHERE AnimalID IN ({placeholders})"
        ), params).fetchall()
        m["animals"] = [dict(a._mapping) for a in animals]
    else:
        m["animals"] = []

    return m


# ─────────────────────────────────────────────
# SELLER MANAGEMENT
# ─────────────────────────────────────────────

@router.post("/")
def create_product(body: ProductCreate, db: Session = Depends(get_db)):
    db.execute(text("""
        INSERT INTO SFProducts (
            BusinessID, PeopleID, prodName, prodShortDescription, prodDescription,
            prodPrice, SalePrice, prodSaleIsActive, prodCallforPrice, prodCustomorder,
            prodWeight, prodShip, prodLength, prodWidth, prodHeight, ProdDimensions,
            prodMadeIn, prodCategoryId, prodSubCategoryId, ProdQuantityAvailable,
            Materials, ProdAnimalID, ProdAnimalID2, ProdAnimalID3,
            FiberType1, FiberPercent1, FiberType2, FiberPercent2,
            FiberType3, FiberPercent3, FiberType4, FiberPercent4,
            FiberType5, FiberPercent5,
            Publishproduct, ProdForSale
        ) VALUES (
            :BusinessID, :PeopleID, :prodName, :prodShortDescription, :prodDescription,
            :prodPrice, :SalePrice, :prodSaleIsActive, :prodCallforPrice, :prodCustomorder,
            :prodWeight, :prodShip, :prodLength, :prodWidth, :prodHeight, :ProdDimensions,
            :prodMadeIn, :prodCategoryId, :prodSubCategoryId, :ProdQuantityAvailable,
            :Materials, :ProdAnimalID, :ProdAnimalID2, :ProdAnimalID3,
            :FiberType1, :FiberPercent1, :FiberType2, :FiberPercent2,
            :FiberType3, :FiberPercent3, :FiberType4, :FiberPercent4,
            :FiberType5, :FiberPercent5,
            :Publishproduct, :ProdForSale
        )
    """), body.model_dump())
    prod_id = db.execute(text("SELECT SCOPE_IDENTITY()")).scalar()
    db.commit()
    return {"ProdID": prod_id, "message": "Product created"}


@router.put("/{prod_id}")
def update_product(prod_id: int, body: ProductUpdate, db: Session = Depends(get_db)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")

    set_clause = ", ".join([f"{k} = :{k}" for k in updates])
    updates["prod_id"] = prod_id
    db.execute(text(f"UPDATE SFProducts SET {set_clause} WHERE ProdID = :prod_id"), updates)
    db.commit()
    return {"message": "Product updated"}


@router.delete("/{prod_id}")
def delete_product(prod_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM SFProducts WHERE ProdID = :pid"), {"pid": prod_id})
    db.commit()
    return {"message": "Product deleted"}


# ─────────────────────────────────────────────
# PHOTOS
# ─────────────────────────────────────────────

@router.put("/{prod_id}/photos")
def upsert_photos(prod_id: int, body: PhotosUpdate, db: Session = Depends(get_db)):
    existing = db.execute(text(
        "SELECT ID FROM productsphotos WHERE ID = :pid"
    ), {"pid": prod_id}).fetchone()

    data = body.model_dump()

    if existing:
        set_parts = ", ".join([f"{k} = :{k}" for k in data])
        data["prod_id"] = prod_id
        db.execute(text(f"UPDATE productsphotos SET {set_parts} WHERE ID = :prod_id"), data)
    else:
        cols = ", ".join(["ID"] + list(data.keys()))
        vals = ", ".join([":prod_id"] + [f":{k}" for k in data.keys()])
        data["prod_id"] = prod_id
        db.execute(text(f"INSERT INTO productsphotos ({cols}) VALUES ({vals})"), data)

    db.commit()
    return {"message": "Photos saved"}


# ─────────────────────────────────────────────
# SIZES
# ─────────────────────────────────────────────

@router.get("/{prod_id}/sizes")
def get_sizes(prod_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text(
        "SELECT * FROM productsizes WHERE ProductID = :pid ORDER BY SizeID"
    ), {"pid": prod_id}).fetchall()
    result = []
    for r in rows:
        m = dict(r._mapping)
        if m.get("ExtraCost") is not None:
            m["ExtraCost"] = float(m["ExtraCost"])
        result.append(m)
    return result


@router.post("/{prod_id}/sizes")
def add_size(prod_id: int, body: SizeCreate, db: Session = Depends(get_db)):
    db.execute(text("""
        INSERT INTO productsizes (ProductID, Size, ExtraCost, PeopleID)
        VALUES (:pid, :size, :extra, :people_id)
    """), {"pid": prod_id, "size": body.Size, "extra": body.ExtraCost, "people_id": body.PeopleID})
    size_id = db.execute(text("SELECT SCOPE_IDENTITY()")).scalar()
    db.commit()
    return {"SizeID": size_id, "message": "Size added"}


@router.delete("/sizes/{size_id}")
def delete_size(size_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM productsizes WHERE SizeID = :sid"), {"sid": size_id})
    db.commit()
    return {"message": "Size deleted"}


# ─────────────────────────────────────────────
# COLORS
# ─────────────────────────────────────────────

@router.get("/{prod_id}/colors")
def get_colors(prod_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text(
        "SELECT * FROM productcolor WHERE ProductID = :pid ORDER BY ColorID"
    ), {"pid": prod_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/{prod_id}/colors")
def add_color(prod_id: int, body: ColorCreate, db: Session = Depends(get_db)):
    db.execute(text("""
        INSERT INTO productcolor (ProductID, Color, PeopleID)
        VALUES (:pid, :color, :people_id)
    """), {"pid": prod_id, "color": body.Color, "people_id": body.PeopleID})
    color_id = db.execute(text("SELECT SCOPE_IDENTITY()")).scalar()
    db.commit()
    return {"ColorID": color_id, "message": "Color added"}


@router.delete("/colors/{color_id}")
def delete_color(color_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM productcolor WHERE ColorID = :cid"), {"cid": color_id})
    db.commit()
    return {"message": "Color deleted"}
