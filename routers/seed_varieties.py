from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from database import get_db

router = APIRouter(prefix="/api/seeds", tags=["seed_varieties"])


def _ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'SeedLot')
        CREATE TABLE SeedLot (
            LotID           INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID      INT NOT NULL,
            CropName        NVARCHAR(200) NOT NULL,
            Variety         NVARCHAR(200),
            Supplier        NVARCHAR(200),
            LotNumber       NVARCHAR(100),
            PurchaseDate    DATE,
            QuantityKg      DECIMAL(10,2),
            RemainingKg     DECIMAL(10,2),
            PricePerKg      DECIMAL(10,2),
            GerminationRate DECIMAL(5,2),
            TestDate        DATE,
            ExpiryDate      DATE,
            StorageLocation NVARCHAR(200),
            Notes           NVARCHAR(MAX),
            CreatedAt       DATETIME2 DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'VarietyTrial')
        CREATE TABLE VarietyTrial (
            TrialID        INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID     INT NOT NULL,
            LotID          INT,
            FieldID        INT,
            FieldName      NVARCHAR(200),
            Season         NVARCHAR(20),
            CropName       NVARCHAR(200) NOT NULL,
            Variety        NVARCHAR(200),
            PlantDate      DATE,
            HarvestDate    DATE,
            AreaHa         DECIMAL(10,2),
            YieldTonnesHa  DECIMAL(10,3),
            GradeAPct      DECIMAL(5,2),
            Notes          NVARCHAR(MAX),
            Rating         INT,
            CreatedAt      DATETIME2 DEFAULT GETDATE()
        )
    """))
    db.commit()


def _lot_row(r) -> dict:
    return {
        "lot_id":           r[0],  "business_id":   r[1],
        "crop_name":        r[2],  "variety":        r[3],
        "supplier":         r[4],  "lot_number":     r[5],
        "purchase_date":    str(r[6])  if r[6]  else None,
        "quantity_kg":      float(r[7]) if r[7] is not None else None,
        "remaining_kg":     float(r[8]) if r[8] is not None else None,
        "price_per_kg":     float(r[9]) if r[9] is not None else None,
        "germination_rate": float(r[10]) if r[10] is not None else None,
        "test_date":        str(r[11]) if r[11] else None,
        "expiry_date":      str(r[12]) if r[12] else None,
        "storage_location": r[13], "notes": r[14],
        "created_at":       str(r[15]) if r[15] else None,
    }


def _trial_row(r) -> dict:
    return {
        "trial_id":       r[0],  "business_id": r[1],
        "lot_id":         r[2],  "field_id":    r[3],
        "field_name":     r[4],  "season":      r[5],
        "crop_name":      r[6],  "variety":     r[7],
        "plant_date":     str(r[8])  if r[8]  else None,
        "harvest_date":   str(r[9])  if r[9]  else None,
        "area_ha":        float(r[10]) if r[10] is not None else None,
        "yield_tonnes_ha":float(r[11]) if r[11] is not None else None,
        "grade_a_pct":    float(r[12]) if r[12] is not None else None,
        "notes":          r[13],
        "rating":         r[14],
        "created_at":     str(r[15]) if r[15] else None,
    }


# ── Seed Lots ─────────────────────────────────────────────────────────────────

@router.get("/lots")
def list_lots(
    business_id: int = Query(...),
    crop_name: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    sql = """
        SELECT LotID, BusinessID, CropName, Variety, Supplier, LotNumber,
               PurchaseDate, QuantityKg, RemainingKg, PricePerKg,
               GerminationRate, TestDate, ExpiryDate, StorageLocation, Notes, CreatedAt
        FROM SeedLot WHERE BusinessID = :bid
    """
    params: dict = {"bid": business_id}
    if crop_name:
        sql += " AND CropName = :crop"
        params["crop"] = crop_name
    sql += " ORDER BY CropName, Variety"
    rows = db.execute(text(sql), params).fetchall()
    return [_lot_row(r) for r in rows]


@router.post("/lots")
def create_lot(
    business_id: int,
    crop_name: str,
    variety: Optional[str] = None,
    supplier: Optional[str] = None,
    lot_number: Optional[str] = None,
    purchase_date: Optional[str] = None,
    quantity_kg: Optional[float] = None,
    price_per_kg: Optional[float] = None,
    germination_rate: Optional[float] = None,
    test_date: Optional[str] = None,
    expiry_date: Optional[str] = None,
    storage_location: Optional[str] = None,
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    db.execute(
        text("""
            INSERT INTO SeedLot
                (BusinessID, CropName, Variety, Supplier, LotNumber, PurchaseDate,
                 QuantityKg, RemainingKg, PricePerKg, GerminationRate, TestDate,
                 ExpiryDate, StorageLocation, Notes)
            VALUES (:bid, :crop, :var, :sup, :lot, :pd,
                    :qty, :qty, :ppk, :germ, :td, :exp, :sl, :notes)
        """),
        {
            "bid": business_id, "crop": crop_name, "var": variety, "sup": supplier,
            "lot": lot_number, "pd": purchase_date or None, "qty": quantity_kg,
            "ppk": price_per_kg, "germ": germination_rate,
            "td": test_date or None, "exp": expiry_date or None,
            "sl": storage_location, "notes": notes,
        },
    )
    db.commit()
    return {"ok": True}


@router.patch("/lots/{lot_id}/remaining")
def update_remaining(lot_id: int, remaining_kg: float, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(
        text("UPDATE SeedLot SET RemainingKg = :r WHERE LotID = :id"),
        {"r": remaining_kg, "id": lot_id},
    )
    db.commit()
    return {"ok": True}


@router.delete("/lots/{lot_id}")
def delete_lot(lot_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM SeedLot WHERE LotID = :id"), {"id": lot_id})
    db.commit()
    return {"ok": True}


# ── Variety Trials ────────────────────────────────────────────────────────────

@router.get("/trials")
def list_trials(
    business_id: int = Query(...),
    season: Optional[str] = None,
    crop_name: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    sql = """
        SELECT TrialID, BusinessID, LotID, FieldID, FieldName, Season,
               CropName, Variety, PlantDate, HarvestDate, AreaHa,
               YieldTonnesHa, GradeAPct, Notes, Rating, CreatedAt
        FROM VarietyTrial WHERE BusinessID = :bid
    """
    params: dict = {"bid": business_id}
    if season:
        sql += " AND Season = :season"
        params["season"] = season
    if crop_name:
        sql += " AND CropName = :crop"
        params["crop"] = crop_name
    sql += " ORDER BY Season DESC, CropName, Variety"
    rows = db.execute(text(sql), params).fetchall()
    return [_trial_row(r) for r in rows]


@router.post("/trials")
def create_trial(
    business_id: int,
    crop_name: str,
    variety: Optional[str] = None,
    lot_id: Optional[int] = None,
    field_id: Optional[int] = None,
    field_name: Optional[str] = None,
    season: Optional[str] = None,
    plant_date: Optional[str] = None,
    harvest_date: Optional[str] = None,
    area_ha: Optional[float] = None,
    yield_tonnes_ha: Optional[float] = None,
    grade_a_pct: Optional[float] = None,
    notes: Optional[str] = None,
    rating: Optional[int] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    db.execute(
        text("""
            INSERT INTO VarietyTrial
                (BusinessID, LotID, FieldID, FieldName, Season, CropName, Variety,
                 PlantDate, HarvestDate, AreaHa, YieldTonnesHa, GradeAPct, Notes, Rating)
            VALUES (:bid, :lot, :fid, :fname, :season, :crop, :var,
                    :pd, :hd, :area, :yield, :grade, :notes, :rating)
        """),
        {
            "bid": business_id, "lot": lot_id, "fid": field_id, "fname": field_name,
            "season": season, "crop": crop_name, "var": variety,
            "pd": plant_date or None, "hd": harvest_date or None,
            "area": area_ha, "yield": yield_tonnes_ha, "grade": grade_a_pct,
            "notes": notes, "rating": rating,
        },
    )
    db.commit()
    return {"ok": True}


@router.delete("/trials/{trial_id}")
def delete_trial(trial_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM VarietyTrial WHERE TrialID = :id"), {"id": trial_id})
    db.commit()
    return {"ok": True}


# ── Performance comparison ────────────────────────────────────────────────────

@router.get("/performance")
def variety_performance(
    business_id: int = Query(...),
    crop_name: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Average yield, grade, and rating per variety across all trials."""
    _ensure_tables(db)
    sql = """
        SELECT CropName, Variety,
               COUNT(*)                    AS trials,
               AVG(YieldTonnesHa)          AS avg_yield,
               AVG(GradeAPct)              AS avg_grade_a,
               AVG(CAST(Rating AS FLOAT))  AS avg_rating,
               MAX(HarvestDate)            AS last_harvest
        FROM VarietyTrial
        WHERE BusinessID = :bid AND YieldTonnesHa IS NOT NULL
    """
    params: dict = {"bid": business_id}
    if crop_name:
        sql += " AND CropName = :crop"
        params["crop"] = crop_name
    sql += " GROUP BY CropName, Variety ORDER BY avg_yield DESC"
    rows = db.execute(text(sql), params).fetchall()
    return [
        {
            "crop_name":    r[0], "variety":    r[1],
            "trials":       r[2],
            "avg_yield":    round(float(r[3]), 3) if r[3] is not None else None,
            "avg_grade_a":  round(float(r[4]), 1) if r[4] is not None else None,
            "avg_rating":   round(float(r[5]), 1) if r[5] is not None else None,
            "last_harvest": str(r[6]) if r[6] else None,
        }
        for r in rows
    ]


@router.get("/crops")
def distinct_crops(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(
        text("SELECT DISTINCT CropName FROM SeedLot WHERE BusinessID = :bid ORDER BY CropName"),
        {"bid": business_id},
    ).fetchall()
    return [r[0] for r in rows]
