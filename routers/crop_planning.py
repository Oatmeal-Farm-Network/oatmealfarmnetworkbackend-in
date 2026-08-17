from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import date
from typing import Optional
from database import get_db
from auth import get_current_user, assert_business_access

router = APIRouter(prefix="/api/crop-planning", tags=["crop_planning"])

STATUS_OPTS = ("Planned", "Planted", "Growing", "Harvested", "Failed")


def _ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'CropPlan')
        CREATE TABLE CropPlan (
            PlanID            INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID        INT NOT NULL,
            FieldID           INT,
            FieldName         NVARCHAR(200),
            CropName          NVARCHAR(200) NOT NULL,
            CropVariety       NVARCHAR(200),
            Season            NVARCHAR(20) NOT NULL,
            PlantDate         DATE,
            HarvestDate       DATE,
            ActualPlantDate   DATE,
            ActualHarvestDate DATE,
            AreaHa            DECIMAL(10,2),
            Status            NVARCHAR(50) DEFAULT 'Planned',
            Color             NVARCHAR(20) DEFAULT '#3b82f6',
            Notes             NVARCHAR(MAX),
            CreatedAt         DATETIME2 DEFAULT GETDATE()
        )
    """))
    db.commit()


def _row(r) -> dict:
    return {
        "plan_id":            r[0],
        "business_id":        r[1],
        "field_id":           r[2],
        "field_name":         r[3],
        "crop_name":          r[4],
        "crop_variety":       r[5],
        "season":             r[6],
        "plant_date":         str(r[7])  if r[7]  else None,
        "harvest_date":       str(r[8])  if r[8]  else None,
        "actual_plant_date":  str(r[9])  if r[9]  else None,
        "actual_harvest_date":str(r[10]) if r[10] else None,
        "area_ha":            float(r[11]) if r[11] is not None else None,
        "status":             r[12],
        "color":              r[13],
        "notes":              r[14],
        "created_at":         str(r[15]) if r[15] else None,
    }


@router.get("/plans")
def list_plans(
    business_id: int = Query(...),
    season: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    assert_business_access(db, user, business_id)
    _ensure_tables(db)
    sql = """
        SELECT PlanID, BusinessID, FieldID, FieldName, CropName, CropVariety,
               Season, PlantDate, HarvestDate, ActualPlantDate, ActualHarvestDate,
               AreaHa, Status, Color, Notes, CreatedAt
        FROM CropPlan WHERE BusinessID = :bid
    """
    params: dict = {"bid": business_id}
    if season:
        sql += " AND Season = :season"
        params["season"] = season
    sql += " ORDER BY PlantDate, CropName"
    rows = db.execute(text(sql), params).fetchall()
    return [_row(r) for r in rows]


@router.post("/plans")
def create_plan(
    business_id: int,
    field_id: Optional[int] = None,
    field_name: Optional[str] = None,
    crop_name: str = "",
    crop_variety: Optional[str] = None,
    season: str = "",
    plant_date: Optional[str] = None,
    harvest_date: Optional[str] = None,
    area_ha: Optional[float] = None,
    status: Optional[str] = "Planned",
    color: Optional[str] = "#3b82f6",
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    assert_business_access(db, user, business_id)
    _ensure_tables(db)
    db.execute(
        text("""
            INSERT INTO CropPlan
                (BusinessID, FieldID, FieldName, CropName, CropVariety, Season,
                 PlantDate, HarvestDate, AreaHa, Status, Color, Notes)
            VALUES (:bid, :fid, :fname, :crop, :variety, :season,
                    :pd, :hd, :area, :status, :color, :notes)
        """),
        {
            "bid": business_id, "fid": field_id, "fname": field_name,
            "crop": crop_name, "variety": crop_variety, "season": season,
            "pd": plant_date or None, "hd": harvest_date or None,
            "area": area_ha, "status": status, "color": color, "notes": notes,
        },
    )
    db.commit()
    return {"ok": True}


@router.put("/plans/{plan_id}")
def update_plan(
    plan_id: int,
    field_name: Optional[str] = None,
    crop_name: Optional[str] = None,
    crop_variety: Optional[str] = None,
    season: Optional[str] = None,
    plant_date: Optional[str] = None,
    harvest_date: Optional[str] = None,
    actual_plant_date: Optional[str] = None,
    actual_harvest_date: Optional[str] = None,
    area_ha: Optional[float] = None,
    status: Optional[str] = None,
    color: Optional[str] = None,
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    row = db.execute(text("SELECT BusinessID FROM CropPlan WHERE PlanID = :pid"), {"pid": plan_id}).first()
    if not row:
        raise HTTPException(status_code=404, detail="Plan not found")
    assert_business_access(db, user, row[0])
    sets, params = [], {"pid": plan_id}
    mapping = {
        "FieldName": field_name, "CropName": crop_name, "CropVariety": crop_variety,
        "Season": season, "PlantDate": plant_date, "HarvestDate": harvest_date,
        "ActualPlantDate": actual_plant_date, "ActualHarvestDate": actual_harvest_date,
        "AreaHa": area_ha, "Status": status, "Color": color, "Notes": notes,
    }
    for col, val in mapping.items():
        if val is not None:
            key = col.lower()
            sets.append(f"{col} = :{key}")
            params[key] = val
    if not sets:
        return {"ok": True}
    db.execute(text(f"UPDATE CropPlan SET {', '.join(sets)} WHERE PlanID = :pid"), params)
    db.commit()
    return {"ok": True}


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _ensure_tables(db)
    row = db.execute(text("SELECT BusinessID FROM CropPlan WHERE PlanID = :pid"), {"pid": plan_id}).first()
    if not row:
        raise HTTPException(status_code=404, detail="Plan not found")
    assert_business_access(db, user, row[0])
    db.execute(text("DELETE FROM CropPlan WHERE PlanID = :pid"), {"pid": plan_id})
    db.commit()
    return {"ok": True}


def india_agro_season(today: Optional[date] = None) -> dict:
    """Kharif / Rabi / Zaid window used by Indian crop planning."""
    d = today or date.today()
    m, y = d.month, d.year
    if 6 <= m <= 10:
        return {
            "code": "kharif",
            "label": f"Kharif {y}",
            "window": "June–October (monsoon)",
            "sow": "June–July",
            "harvest": "September–November",
            "crops": [
                "Rice", "Maize", "Cotton", "Soybean", "Groundnut",
                "Bajra", "Jowar", "Tur (Arhar)", "Sugarcane", "Turmeric", "Chilli",
            ],
        }
    if m == 11 or m == 12 or m <= 3:
        start = y if m >= 11 else y - 1
        return {
            "code": "rabi",
            "label": f"Rabi {start}-{str(start + 1)[2:]}",
            "window": "November–March (winter)",
            "sow": "October–December",
            "harvest": "March–April",
            "crops": [
                "Wheat", "Mustard", "Chana", "Masur", "Barley",
                "Potato", "Onion", "Peas", "Cumin",
            ],
        }
    return {
        "code": "zaid",
        "label": f"Zaid {y}",
        "window": "March–June (summer)",
        "sow": "March–April",
        "harvest": "May–June",
        "crops": [
            "Moong", "Muskmelon", "Watermelon", "Cucumber",
            "Fodder maize", "Vegetables",
        ],
    }


@router.get("/india-calendar")
def india_crop_calendar():
    """Current agro-season + recommended staples (no auth — planning reference)."""
    current = india_agro_season()
    return {
        "current": current,
        "seasons": ["Kharif", "Rabi", "Zaid"],
        "notes": "Windows vary by state. Confirm with your KVK / state agri calendar.",
    }


@router.get("/seasons")
def list_seasons(business_id: int = Query(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    assert_business_access(db, user, business_id)
    _ensure_tables(db)
    rows = db.execute(
        text("SELECT DISTINCT Season FROM CropPlan WHERE BusinessID = :bid ORDER BY Season DESC"),
        {"bid": business_id},
    ).fetchall()
    current = india_agro_season()["label"]
    seasons = [r[0] for r in rows]
    for extra in (current, f"Kharif {date.today().year}", f"Rabi {date.today().year}-{str(date.today().year + 1)[2:]}", f"Zaid {date.today().year}"):
        if extra not in seasons:
            seasons.insert(0, extra)
    # de-dupe preserving order
    seen = set()
    out = []
    for s in seasons:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


@router.get("/field-history")
def field_history(
    business_id: int = Query(...),
    field_id: int = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    assert_business_access(db, user, business_id)
    _ensure_tables(db)
    rows = db.execute(
        text("""
            SELECT PlanID, BusinessID, FieldID, FieldName, CropName, CropVariety,
                   Season, PlantDate, HarvestDate, ActualPlantDate, ActualHarvestDate,
                   AreaHa, Status, Color, Notes, CreatedAt
            FROM CropPlan
            WHERE BusinessID = :bid AND FieldID = :fid
            ORDER BY Season DESC, PlantDate DESC
        """),
        {"bid": business_id, "fid": field_id},
    ).fetchall()
    return [_row(r) for r in rows]
