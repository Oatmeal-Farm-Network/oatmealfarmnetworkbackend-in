from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from database import get_db

router = APIRouter(prefix="/api/processed-food", tags=["processed-food"])


@router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    try:
        rows = db.execute(text(
            "SELECT ProcessedFoodCategoryID, CategoryName FROM ProcessedFoodCategoryLookup ORDER BY ProcessedFoodCategoryOrder"
        )).fetchall()
        return [{"ProcessedFoodCategoryID": r.ProcessedFoodCategoryID, "CategoryName": r.CategoryName} for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/inventory")
def get_inventory(BusinessID: int, db: Session = Depends(get_db)):
    try:
        rows = db.execute(text("""
            SELECT pf.ProcessedFoodID, pf.Name, pf.Quantity,
                   pf.WholesalePrice, pf.RetailPrice,
                   pf.AvailableDate, pf.ShowProcessedFood,
                   pf.ProcessedFoodCategoryID,
                   c.CategoryName
            FROM ProcessedFood pf
            JOIN ProcessedFoodCategoryLookup c ON pf.ProcessedFoodCategoryID = c.ProcessedFoodCategoryID
            WHERE pf.BusinessID = :bid
            ORDER BY pf.Name
        """), {"bid": BusinessID}).fetchall()
        return [
            {
                "ProcessedFoodID":         r.ProcessedFoodID,
                "Name":                    r.Name,
                "Quantity":                r.Quantity,
                "WholesalePrice":          float(r.WholesalePrice) if r.WholesalePrice is not None else None,
                "RetailPrice":             float(r.RetailPrice) if r.RetailPrice is not None else None,
                "AvailableDate":           str(r.AvailableDate) if r.AvailableDate else None,
                "ShowProcessedFood":       r.ShowProcessedFood,
                "ProcessedFoodCategoryID": r.ProcessedFoodCategoryID,
                "CategoryName":            r.CategoryName,
            }
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/add")
def add_processed_food(payload: dict, db: Session = Depends(get_db)):
    try:
        db.execute(text("""
            INSERT INTO ProcessedFood
                (ProcessedFoodCategoryID, Name, Quantity, WholesalePrice, RetailPrice, BusinessID)
            VALUES
                (:cat, :name, :qty, :wholesale, :retail, :bid)
        """), {
            "cat":      payload.get("ProcessedFoodCategoryID") or None,
            "name":     payload.get("Name", "").strip(),
            "qty":      payload.get("Quantity") or None,
            "wholesale":payload.get("WholesalePrice") or None,
            "retail":   payload.get("RetailPrice") or None,
            "bid":      payload.get("BusinessID"),
        })
        db.commit()
        return {"message": "Processed food added successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update/{processed_food_id}")
def update_processed_food(processed_food_id: int, payload: dict, BusinessID: int, db: Session = Depends(get_db)):
    try:
        db.execute(text("""
            UPDATE ProcessedFood SET
                Quantity         = :qty,
                RetailPrice      = :retail,
                WholesalePrice   = :wholesale,
                AvailableDate    = :avail,
                ShowProcessedFood= :show,
                BusinessID       = :bid
            WHERE ProcessedFoodID = :pid
        """), {
            "qty":      payload.get("Quantity") or None,
            "retail":   payload.get("RetailPrice") or None,
            "wholesale":payload.get("WholesalePrice") or None,
            "avail":    payload.get("AvailableDate") or None,
            "show":     1 if payload.get("ShowProcessedFood") else 0,
            "bid":      BusinessID,
            "pid":      processed_food_id,
        })
        db.commit()
        return {"message": "Processed food updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/delete/{processed_food_id}")
def delete_processed_food(processed_food_id: int, BusinessID: int, db: Session = Depends(get_db)):
    try:
        db.execute(text(
            "DELETE FROM ProcessedFood WHERE ProcessedFoodID = :pid AND BusinessID = :bid"
        ), {"pid": processed_food_id, "bid": BusinessID})
        db.commit()
        return {"message": "Deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
