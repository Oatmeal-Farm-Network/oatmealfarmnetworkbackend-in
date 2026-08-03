"""
routers/ranches.py
Ranch/Farm directory endpoints for the Livestock Marketplace.

Mount in main.py:
    from routers import ranches
    app.include_router(ranches.router)
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from database import get_db
import time, re

router = APIRouter(prefix="/api/ranches", tags=["ranches"])

_cache: dict = {}
CACHE_TTL = 300

GCP_BUCKET_URL = "https://storage.googleapis.com/oatmeal-farm-network-images/Animals"

SLUG_TO_SPECIES_ID = {
    'alpacas': 2, 'bison': 9, 'buffalo': 34, 'camels': 18, 'cattle': 8,
    'chickens': 13, 'crocodiles': 25, 'dogs': 3, 'deer': 21, 'donkeys': 7,
    'ducks': 15, 'emus': 19, 'geese': 22, 'goats': 6, 'guinea-fowl': 26,
    'honey-bees': 23, 'horses': 5, 'llamas': 4, 'musk-ox': 27, 'ostriches': 28,
    'pheasants': 29, 'pigs': 12, 'pigeons': 30, 'quails': 31, 'rabbits': 11,
    'sheep': 10, 'snails': 33, 'turkeys': 14, 'yaks': 17,
}

SLUG_TO_LABEL = {
    'alpacas': 'Alpacas', 'bison': 'Bison', 'buffalo': 'Buffalo', 'camels': 'Camels',
    'cattle': 'Cattle', 'chickens': 'Chickens', 'crocodiles': 'Crocodiles & Alligators',
    'deer': 'Deer', 'dogs': 'Working Dogs', 'donkeys': 'Donkeys', 'ducks': 'Ducks',
    'emus': 'Emus', 'geese': 'Geese', 'goats': 'Goats', 'guinea-fowl': 'Guinea Fowl',
    'honey-bees': 'Honey Bees', 'horses': 'Horses', 'llamas': 'Llamas',
    'musk-ox': 'Musk Ox', 'ostriches': 'Ostriches', 'pheasants': 'Pheasants',
    'pigs': 'Pigs', 'pigeons': 'Pigeons', 'quails': 'Quails', 'rabbits': 'Rabbits',
    'sheep': 'Sheep', 'snails': 'Snails', 'turkeys': 'Turkeys', 'yaks': 'Yaks',
}


def cache_get(key):
    e = _cache.get(key)
    return e['v'] if e and time.time() - e['t'] < CACHE_TTL else None


def cache_set(key, value):
    _cache[key] = {'v': value, 't': time.time()}


def _fix_logo(url):
    """Normalize BusinessLogo values to GCP bucket URLs."""
    if not url:
        return None
    url = url.strip()
    if not url or len(url) < 4:
        return None

    # Already a full URL — rewrite old domains to GCP
    if url.lower().startswith('http'):
        url = re.sub(r'^http:', 'https:', url, flags=re.IGNORECASE)
        # Rewrite old domain uploads to GCP
        for old_domain in ['oatmealfarmnetwork.com', 'livestockofamerica.com',
                           'livestockoftheworld.com', 'alpacainfinity.com',
                           'globallivestocksolutions.com']:
            if old_domain in url.lower():
                filename = url.split('/')[-1].strip()
                if filename and len(filename) > 3:
                    return f"{GCP_BUCKET_URL}/{filename}"
        return url

    # Starts with /uploads/ or /Uploads/ — strip the path prefix
    if url.lower().startswith('/uploads/'):
        filename = url[9:].strip()  # len('/uploads/') == 9
        if filename and len(filename) > 3:
            return f"{GCP_BUCKET_URL}/{filename}"
        return None

    # Plain filename with no path — use directly
    if '/' not in url and len(url) > 4:
        return f"{GCP_BUCKET_URL}/{url}"

    # Anything else — extract just the filename
    filename = url.split('/')[-1].strip()
    if filename and len(filename) > 3:
        return f"{GCP_BUCKET_URL}/{filename}"

    return None


def _safe_str(val):
    return str(val).strip() if val else ''


def _row_to_ranch(row):
    return {
        "business_id": row.BusinessID,
        "business_name": _safe_str(getattr(row, 'BusinessName', '')),
        "logo": _fix_logo(getattr(row, 'BusinessLogo', None)),
        "city": _safe_str(getattr(row, 'AddressCity', '')),
        "state": _safe_str(getattr(row, 'AddressState', '')),
        "country": _safe_str(getattr(row, 'AddressCountry', '')),
        "facebook": _safe_str(getattr(row, 'BusinessFacebook', '')),
        "instagram": _safe_str(getattr(row, 'BusinessInstagram', '')),
        "x": _safe_str(getattr(row, 'BusinessX', '')),
        "pinterest": _safe_str(getattr(row, 'BusinessPinterest', '')),
        "youtube": _safe_str(getattr(row, 'BusinessYouTube', '')),
        "blog": _safe_str(getattr(row, 'BusinessBlog', '')),
        "truth_social": _safe_str(getattr(row, 'BusinessTruthSocial', '')),
        "has_animals": bool(getattr(row, 'AnimalCount', 0)),
        "has_studs": bool(getattr(row, 'StudCount', 0)),
    }


# ── Ranch search/listing ──────────────────────────────────────────────────────

@router.get("/list/{slug}")
def get_ranches(
    slug: str,
    page: int = Query(1, ge=1),
    state_index: int = Query(0),
    name: str = Query(''),
    db: Session = Depends(get_db),
):
    PER_PAGE = 10
    try:
        sid = SLUG_TO_SPECIES_ID.get(slug)
        if not sid:
            raise HTTPException(status_code=404, detail="Species not found")

        where = """
            WHERE ba.Active = 1
              AND EXISTS (
                  SELECT 1 FROM Animals a2
                  WHERE a2.PeopleID = ba.PeopleID
                    AND a2.SpeciesID = :sid
                    AND (a2.PublishForSale = 1 OR a2.PublishStud = 1)
              )
        """
        params: dict = {"sid": sid}

        if state_index > 0:
            where += " AND addr.StateIndex = :state_index "
            params["state_index"] = state_index

        if name.strip():
            where += " AND biz.BusinessName LIKE :name "
            params["name"] = f"%{name.strip()}%"

        offset = (page - 1) * PER_PAGE

        count_sql = text(f"""
            SELECT COUNT(DISTINCT biz.BusinessID) AS total
            FROM BusinessAccess ba
            JOIN Business biz ON ba.BusinessID = biz.BusinessID
            LEFT JOIN Address addr ON biz.AddressID = addr.AddressID
            {where}
        """)
        total = db.execute(count_sql, params).scalar() or 0

        params["offset"] = offset
        params["per_page"] = PER_PAGE

        data_sql = text(f"""
            SELECT
                biz.BusinessID, biz.BusinessName, biz.BusinessLogo,
                biz.BusinessFacebook, biz.BusinessX, biz.BusinessInstagram,
                biz.BusinessPinterest, biz.BusinessYouTube, biz.BusinessBlog,
                biz.BusinessTruthSocial,
                addr.AddressCity, addr.AddressState, addr.AddressCountry,
                (SELECT COUNT(*) FROM Animals a3
                 JOIN BusinessAccess ba3 ON a3.PeopleID = ba3.PeopleID
                 WHERE ba3.BusinessID = biz.BusinessID AND a3.SpeciesID = :sid
                   AND a3.PublishForSale = 1) AS AnimalCount,
                (SELECT COUNT(*) FROM Animals a4
                 JOIN BusinessAccess ba4 ON a4.PeopleID = ba4.PeopleID
                 WHERE ba4.BusinessID = biz.BusinessID AND a4.SpeciesID = :sid
                   AND a4.PublishStud = 1) AS StudCount
            FROM BusinessAccess ba
            JOIN Business biz ON ba.BusinessID = biz.BusinessID
            LEFT JOIN Address addr ON biz.AddressID = addr.AddressID
            {where}
            GROUP BY biz.BusinessID, biz.BusinessName, biz.BusinessLogo,
                biz.BusinessFacebook, biz.BusinessX, biz.BusinessInstagram,
                biz.BusinessPinterest, biz.BusinessYouTube, biz.BusinessBlog,
                biz.BusinessTruthSocial,
                addr.AddressCity, addr.AddressState, addr.AddressCountry
            ORDER BY biz.BusinessName
            OFFSET :offset ROWS FETCH NEXT :per_page ROWS ONLY
        """)
        rows = db.execute(data_sql, params).fetchall()

        return {
            "total": total,
            "page": page,
            "per_page": PER_PAGE,
            "total_pages": max(1, -(-total // PER_PAGE)),
            "label": SLUG_TO_LABEL.get(slug, slug),
            "ranches": [_row_to_ranch(r) for r in rows],
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ── Ranch profile ─────────────────────────────────────────────────────────────

@router.get("/profile/{business_id}")
def get_ranch_profile(business_id: int, db: Session = Depends(get_db)):
    try:
        row = db.execute(text("""
            SELECT
                biz.BusinessID, biz.BusinessName,
                COALESCE(biz.Logo, biz.BusinessLogo) AS LogoResolved,
                biz.BusinessFacebook, biz.BusinessX, biz.BusinessInstagram,
                biz.BusinessLinkedIn, biz.BusinessPinterest, biz.BusinessYouTube,
                biz.BusinessBlog, biz.BusinessTruthSocial,
                biz.BusinessOtherSocial1, biz.BusinessOtherSocial2,
                biz.BusinessEmail, biz.BusinessDescription,
                biz.RanchHomeText, biz.RanchHomeHeading,
                biz.RanchHomeText2, biz.BusinessProfileHeader,
                biz.BusinessPhone,
                biz.Cuisine, biz.HeadChef, biz.SeatingCapacity,
                biz.RestaurantHours, biz.YearOpened, biz.SourcingPhilosophy,
                addr.AddressStreet, addr.AddressCity, addr.AddressZip,
                sp.name AS StateName,
                c.name AS CountryName,
                w.Website,
                p.PeopleFirstName, p.PeopleLastName
            FROM Business biz
            LEFT JOIN Address addr ON biz.AddressID = addr.AddressID
            LEFT JOIN state_province sp ON addr.StateIndex = sp.StateIndex
            LEFT JOIN country c ON addr.country_id = c.country_id
            LEFT JOIN Websites w ON biz.WebsitesID = w.WebsitesID
            LEFT JOIN People p ON biz.Contact1PeopleID = p.PeopleID
            WHERE biz.BusinessID = :bid
        """), {"bid": business_id}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Ranch not found")

        return {
            "business_id": row.BusinessID,
            "business_name": _safe_str(row.BusinessName),
            "logo": _fix_logo(row.LogoResolved),
            "header_image": _fix_logo(getattr(row, 'BusinessProfileHeader', None)),
            "home_heading": _safe_str(getattr(row, 'RanchHomeHeading', '')),
            "home_text": _safe_str(getattr(row, 'RanchHomeText', '')),
            "home_text2": _safe_str(getattr(row, 'RanchHomeText2', '')),
            "description": _safe_str(row.BusinessDescription),
            "address_street": _safe_str(row.AddressStreet),
            "address_city": _safe_str(row.AddressCity),
            "address_state": _safe_str(row.StateName),
            "address_zip": _safe_str(row.AddressZip),
            "address_country": _safe_str(row.CountryName),
            "website": _safe_str(row.Website),
            "phone": _safe_str(row.BusinessPhone),
            "contact_first_name": _safe_str(row.PeopleFirstName),
            "contact_last_name": _safe_str(row.PeopleLastName),
            "facebook": _safe_str(row.BusinessFacebook),
            "instagram": _safe_str(row.BusinessInstagram),
            "linkedin": _safe_str(row.BusinessLinkedIn),
            "x": _safe_str(row.BusinessX),
            "pinterest": _safe_str(row.BusinessPinterest),
            "youtube": _safe_str(row.BusinessYouTube),
            "blog": _safe_str(row.BusinessBlog),
            "truth_social": _safe_str(row.BusinessTruthSocial),
            "other_social1": _safe_str(getattr(row, 'BusinessOtherSocial1', '')),
            "other_social2": _safe_str(getattr(row, 'BusinessOtherSocial2', '')),
            "cuisine":              _safe_str(getattr(row, 'Cuisine', '')),
            "head_chef":            _safe_str(getattr(row, 'HeadChef', '')),
            "seating_capacity":     getattr(row, 'SeatingCapacity', None),
            "restaurant_hours":     _safe_str(getattr(row, 'RestaurantHours', '')),
            "year_opened":          getattr(row, 'YearOpened', None),
            "sourcing_philosophy":  _safe_str(getattr(row, 'SourcingPhilosophy', '')),
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ── Ranch animals for sale ────────────────────────────────────────────────────

@router.get("/profile/{business_id}/animals")
def get_ranch_animals(
    business_id: int,
    page: int = Query(1, ge=1),
    studs_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    PER_PAGE = 10
    try:
        flag = "a.PublishStud = 1" if studs_only else "a.PublishForSale = 1"
        offset = (page - 1) * PER_PAGE

        total = db.execute(text(f"""
            SELECT COUNT(*) FROM Animals a
            JOIN BusinessAccess ba ON a.PeopleID = ba.PeopleID
            JOIN Pricing p ON a.AnimalID = p.AnimalID
            WHERE ba.BusinessID = :bid AND ba.Active = 1 AND {flag}
        """), {"bid": business_id}).scalar() or 0

        rows = db.execute(text(f"""
            SELECT
                a.AnimalID, a.FullName, a.DOBYear,
                ph.Photo1, ph.Photo2, ph.ListPageImage,
                b.Breed AS Breed1, b2.Breed AS Breed2,
                p.Price, p.StudFee
            FROM Animals a
            JOIN BusinessAccess ba ON a.PeopleID = ba.PeopleID
            JOIN Pricing p ON a.AnimalID = p.AnimalID
            LEFT JOIN Photos ph ON a.AnimalID = ph.AnimalID
            LEFT JOIN SpeciesBreedLookupTable b  ON a.BreedID  = b.BreedLookupID
            LEFT JOIN SpeciesBreedLookupTable b2 ON a.BreedID2 = b2.BreedLookupID
            WHERE ba.BusinessID = :bid AND ba.Active = 1 AND {flag}
            ORDER BY a.FullName
            OFFSET :offset ROWS FETCH NEXT :per_page ROWS ONLY
        """), {"bid": business_id, "offset": offset, "per_page": PER_PAGE}).fetchall()

        def best_photo(row):
            for f in ['ListPageImage', 'Photo1', 'Photo2']:
                v = getattr(row, f, None)
                if v:
                    url = v.strip()
                    filename = url.split('/')[-1]
                    if filename and len(filename) > 4:
                        return f"{GCP_BUCKET_URL}/{filename}"
            return None

        animals = []
        for r in rows:
            breeds = [b for b in [_safe_str(getattr(r, 'Breed1', '')), _safe_str(getattr(r, 'Breed2', ''))] if b]
            price = None
            try:
                v = float(r.StudFee if studs_only else r.Price)
                if v > 0: price = v
            except Exception:
                pass
            animals.append({
                "animal_id": r.AnimalID,
                "full_name": _safe_str(r.FullName),
                "dob_year": getattr(r, 'DOBYear', None),
                "breeds": breeds,
                "photo": best_photo(r),
                "price": price,
            })

        return {
            "total": total,
            "page": page,
            "per_page": PER_PAGE,
            "total_pages": max(1, -(-total // PER_PAGE)),
            "animals": animals,
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))