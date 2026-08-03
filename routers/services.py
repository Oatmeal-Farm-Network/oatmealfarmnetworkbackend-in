from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
import httpx
import os

router = APIRouter()

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
FROM_EMAIL = "john@oatmeal-ai.com"
TO_EMAIL = "livestockoftheworld@gmail.com"

def send_email(subject: str, body: str):
    payload = {
        "personalizations": [{"to": [{"email": TO_EMAIL}]}],
        "from": {"email": FROM_EMAIL, "name": "Oatmeal Farm Network"},
        "subject": subject,
        "content": [{"type": "text/html", "value": body}],
    }
    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        httpx.post(SENDGRID_URL, json=payload, headers=headers, timeout=10)
    except Exception as e:
        print(f"SendGrid error: {e}")

# -------------------------
# List services for a business
# -------------------------
@router.get("/api/services")
def list_services(BusinessID: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT ServicesID, ServiceTitle, ServiceAvailable, ServicePrice, ServiceContactForPrice
        FROM Services WHERE BusinessID = :bid ORDER BY ServiceTitle
    """), {"bid": BusinessID}).fetchall()
    return [dict(r._mapping) for r in rows]

# -------------------------
# Get categories
# -------------------------
@router.get("/api/services/categories")
def get_categories(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT ServiceCategoryID, ServicesCategory
        FROM servicescategories
        ORDER BY ServicesCategory
    """)).fetchall()
    return [dict(r._mapping) for r in rows]

# -------------------------
# Get subcategories for a category
# -------------------------
@router.get("/api/services/categories/{category_id}/subcategories")
def get_subcategories(category_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT ServiceSubCategoryID, ServiceSubCategoryName
        FROM servicessubcategories
        WHERE ServiceCategoryID = :cid
        ORDER BY ServiceSubCategoryName
    """), {"cid": category_id}).fetchall()
    return [dict(r._mapping) for r in rows]

# -------------------------
# Add a service
# -------------------------
@router.post("/api/services/add")
def add_service(data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        INSERT INTO Services (
            BusinessID, ServiceCategoryID, ServiceSubCategoryID, ServiceTitle,
            ServicePrice, ServiceContactForPrice, ServiceAvailable, ServicesDescription,
            ServicePhone, Servicewebsite, Serviceemail
        ) VALUES (
            :bid, :cat, :subcat, :title,
            :price, :cfp, :avail, :desc,
            :phone, :web, :email
        )
    """), {
        "bid": data.get("BusinessID"),
        "cat": data.get("ServiceCategoryID") or None,
        "subcat": data.get("ServiceSubCategoryID") or None,
        "title": data.get("ServiceTitle"),
        "price": data.get("ServicePrice") or None,
        "cfp": data.get("ServiceContactForPrice", 0),
        "avail": data.get("ServiceAvailable"),
        "desc": data.get("ServicesDescription"),
        "phone": data.get("ServicePhone"),
        "web": data.get("Servicewebsite"),
        "email": data.get("Serviceemail"),
    })
    new_id = db.execute(text("SELECT SCOPE_IDENTITY() AS id")).fetchone()
    db.commit()
    return {"ServicesID": int(new_id.id)}

# -------------------------
# Get single service (for editing)
# NOTE: path uses {services_id:int} so literal segments like "public" or
# "subcategories" fall through to their own specific routes.
# -------------------------
@router.get("/api/services/{services_id:int}")
def get_service(services_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT s.*, sc.ServicesCategory
        FROM Services s
        LEFT JOIN servicescategories sc ON s.ServiceCategoryID = sc.ServiceCategoryID
        WHERE s.ServicesID = :sid
    """), {"sid": services_id}).fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Service not found")
    return dict(row._mapping)

# -------------------------
# Update a service
# -------------------------
@router.post("/api/services/{services_id:int}/update")
def update_service(services_id: int, data: dict, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE Services SET
            ServiceCategoryID    = :cat,
            ServiceSubCategoryID = :subcat,
            ServiceTitle         = :title,
            ServicePrice         = :price,
            ServiceContactForPrice = :cfp,
            ServiceAvailable     = :avail,
            ServicesDescription  = :desc,
            ServicePhone         = :phone,
            Servicewebsite       = :web,
            Serviceemail         = :email
        WHERE ServicesID = :sid
    """), {
        "sid":    services_id,
        "cat":    data.get("ServiceCategoryID") or None,
        "subcat": data.get("ServiceSubCategoryID") or None,
        "title":  data.get("ServiceTitle"),
        "price":  data.get("ServicePrice") or None,
        "cfp":    data.get("ServiceContactForPrice", 0),
        "avail":  data.get("ServiceAvailable"),
        "desc":   data.get("ServicesDescription"),
        "phone":  data.get("ServicePhone"),
        "web":    data.get("Servicewebsite"),
        "email":  data.get("Serviceemail"),
    })
    db.commit()
    return {"ok": True}

# -------------------------
# Delete a service
# -------------------------
@router.delete("/api/services/{services_id:int}")
def delete_service(services_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM Services WHERE ServicesID = :sid"), {"sid": services_id})
    db.commit()
    return {"ok": True}

# -------------------------
# Public: all subcategories across all categories
# -------------------------
@router.get("/api/services/subcategories/all")
def all_subcategories(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT ssc.ServicesSubcategoryID AS ServiceSubCategoryID,
               ssc.ServiceSubCategoryName,
               ssc.ServiceCategoryID, sc.ServicesCategory
        FROM servicessubcategories ssc
        LEFT JOIN servicescategories sc ON ssc.ServiceCategoryID = sc.ServiceCategoryID
        ORDER BY sc.ServicesCategory, ssc.ServiceSubCategoryName
    """)).fetchall()
    return [dict(r._mapping) for r in rows]

# -------------------------
# Public: browse services (optional category / subcategory / search filter)
# -------------------------
@router.get("/api/services/public")
def browse_services(
    category_id: int = None,
    subcategory_id: int = None,
    q: str = None,
    db: Session = Depends(get_db),
):
    where = ["s.ServiceAvailable = 1"]
    params = {}
    if category_id:
        where.append("s.ServiceCategoryID = :cid")
        params["cid"] = category_id
    if q:
        where.append(
            "(s.ServiceTitle LIKE :q OR s.ServicesDescription LIKE :q OR b.BusinessName LIKE :q)"
        )
        params["q"] = f"%{q}%"

    sql = f"""
        SELECT s.ServicesID, s.ServiceTitle, s.ServicesDescription,
               s.ServicePrice, s.ServiceContactForPrice, s.ServiceAvailable,
               s.Photo1, s.BusinessID,
               b.BusinessName,
               sc.ServicesCategory, sc.ServiceCategoryID
        FROM Services s
        JOIN Business b ON s.BusinessID = b.BusinessID
        LEFT JOIN servicescategories sc ON s.ServiceCategoryID = sc.ServiceCategoryID
        WHERE {' AND '.join(where)}
        ORDER BY sc.ServicesCategory, s.ServiceTitle
    """
    rows = db.execute(text(sql), params).fetchall()
    return [dict(r._mapping) for r in rows]

# -------------------------
# Public: single service detail
# -------------------------
@router.get("/api/services/public/{services_id}")
def service_detail(services_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT s.*, b.BusinessName, b.BusinessID AS BizID,
               sc.ServicesCategory,
               a.AddressCity, a.AddressState, a.AddressZip, a.AddressCountry
        FROM Services s
        JOIN Business b ON s.BusinessID = b.BusinessID
        LEFT JOIN servicescategories sc ON s.ServiceCategoryID = sc.ServiceCategoryID
        LEFT JOIN Address a ON b.AddressID = a.AddressID
        WHERE s.ServicesID = :sid
    """), {"sid": services_id}).fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Service not found")
    d = dict(row._mapping)
    # Collect photos
    d["photos"] = [d.get(f"Photo{i}") for i in range(1, 9) if d.get(f"Photo{i}")]
    return d

# -------------------------
# Public: services for a specific business
# -------------------------
@router.get("/api/services/business/{business_id}")
def services_by_business(business_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT s.ServicesID, s.ServiceTitle, s.ServicesDescription,
               s.ServicePrice, s.ServiceContactForPrice, s.ServiceAvailable,
               s.Photo1, sc.ServicesCategory
        FROM Services s
        LEFT JOIN servicescategories sc ON s.ServiceCategoryID = sc.ServiceCategoryID
        WHERE s.BusinessID = :bid AND s.ServiceAvailable = 1
        ORDER BY s.ServiceTitle
    """), {"bid": business_id}).fetchall()
    return [dict(r._mapping) for r in rows]

# -------------------------
# Suggest a new category (sends email via SendGrid)
# -------------------------
@router.post("/api/services/suggest-category")
def suggest_category(data: dict):
    business_name = data.get("BusinessName", "Unknown")
    categories = data.get("Categories", "")
    subcategories = data.get("SubCategories", "")

    body = f"""
    <h2>New Service Category Suggestion</h2>
    <p><b>Business:</b> {business_name}</p>
    <p><b>Suggested Categories:</b><br>{categories}</p>
    <p><b>Suggested Sub-Categories:</b><br>{subcategories or 'None provided'}</p>
    """

    send_email(
        subject=f"Service Category Suggestion from {business_name}",
        body=body,
    )
    return {"message": "Suggestion sent"}
