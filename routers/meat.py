from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from database import get_db

router = APIRouter(prefix="/api/meat", tags=["meat"])


@router.get("/items")
def get_meat_items(db: Session = Depends(get_db)):
    """Return all Ingredients where IngredientCategoryID = 10 (Meats)."""
    try:
        rows = db.execute(text(
            "SELECT IngredientID, IngredientName FROM Ingredients WHERE IngredientCategoryID = 10 ORDER BY IngredientName"
        )).fetchall()
        return [{"IngredientID": r.IngredientID, "IngredientName": r.IngredientName} for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cuts")
def get_cuts(IngredientID: int = None, db: Session = Depends(get_db)):
    """Return cuts filtered by IngredientID. Includes universal cuts (IngredientID IS NULL) plus meat-specific cuts."""
    try:
        if IngredientID:
            rows = db.execute(text(
                "SELECT IngredientCutID, IngredientCut FROM Cut "
                "WHERE IngredientID = :iid OR IngredientID IS NULL "
                "ORDER BY IngredientCut"
            ), {"iid": IngredientID}).fetchall()
        else:
            rows = db.execute(text(
                "SELECT IngredientCutID, IngredientCut FROM Cut ORDER BY IngredientCut"
            )).fetchall()
        return [{"IngredientCutID": r.IngredientCutID, "IngredientCut": r.IngredientCut} for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/inventory")
def get_inventory(BusinessID: int, db: Session = Depends(get_db)):
    try:
        rows = db.execute(text("""
            SELECT mi.MeatInventoryID, mi.IngredientID, mi.IngredientCutID,
                   mi.Weight, mi.WeightUnit, mi.Quantity,
                   mi.WholesalePrice, mi.RetailPrice,
                   mi.AvailableDate, mi.ShowMeat,
                   i.IngredientName,
                   c.IngredientCut AS CutName
            FROM MeatInventory mi
            JOIN Ingredients i ON mi.IngredientID = i.IngredientID
            LEFT JOIN Cut c ON mi.IngredientCutID = c.IngredientCutID
            WHERE mi.BusinessID = :bid
            ORDER BY i.IngredientName
        """), {"bid": BusinessID}).fetchall()
        return [
            {
                "MeatInventoryID":  r.MeatInventoryID,
                "IngredientID":     r.IngredientID,
                "IngredientName":   r.IngredientName,
                "IngredientCutID":  r.IngredientCutID,
                "CutName":          r.CutName,
                "Weight":           float(r.Weight) if r.Weight is not None else None,
                "WeightUnit":       r.WeightUnit,
                "Quantity":         r.Quantity,
                "WholesalePrice":   float(r.WholesalePrice) if r.WholesalePrice is not None else None,
                "RetailPrice":      float(r.RetailPrice) if r.RetailPrice is not None else None,
                "AvailableDate":    str(r.AvailableDate) if r.AvailableDate else None,
                "ShowMeat":         r.ShowMeat,
            }
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/add")
def add_meat(payload: dict, db: Session = Depends(get_db)):
    try:
        db.execute(text("""
            INSERT INTO MeatInventory
                (BusinessID, IngredientID, IngredientCutID, Weight, WeightUnit,
                 Quantity, WholesalePrice, RetailPrice)
            VALUES
                (:bid, :iid, :cid, :weight, :wunit, :qty, :wholesale, :retail)
        """), {
            "bid":       payload.get("BusinessID"),
            "iid":       payload.get("IngredientID") or None,
            "cid":       payload.get("IngredientCutID") or None,
            "weight":    payload.get("Weight") or None,
            "wunit":     payload.get("WeightUnit", "lb"),
            "qty":       payload.get("Quantity") or None,
            "wholesale": payload.get("WholesalePrice") or None,
            "retail":    payload.get("RetailPrice") or None,
        })
        db.commit()
        return {"message": "Meat item added successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update/{meat_inventory_id}")
def update_meat(meat_inventory_id: int, payload: dict, BusinessID: int, db: Session = Depends(get_db)):
    try:
        db.execute(text("""
            UPDATE MeatInventory SET
                IngredientCutID  = :cid,
                Weight           = :weight,
                WeightUnit       = :wunit,
                Quantity         = :qty,
                WholesalePrice   = :wholesale,
                RetailPrice      = :retail,
                AvailableDate    = :avail,
                ShowMeat         = :show
            WHERE MeatInventoryID = :mid AND BusinessID = :bid
        """), {
            "cid":       payload.get("IngredientCutID") or None,
            "weight":    payload.get("Weight") or None,
            "wunit":     payload.get("WeightUnit", "lb"),
            "qty":       payload.get("Quantity") or None,
            "wholesale": payload.get("WholesalePrice") or None,
            "retail":    payload.get("RetailPrice") or None,
            "avail":     payload.get("AvailableDate") or None,
            "show":      1 if payload.get("ShowMeat") else 0,
            "mid":       meat_inventory_id,
            "bid":       BusinessID,
        })
        db.commit()
        return {"message": "Meat item updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/delete/{meat_inventory_id}")
def delete_meat(meat_inventory_id: int, BusinessID: int, db: Session = Depends(get_db)):
    try:
        db.execute(text(
            "DELETE FROM MeatInventory WHERE MeatInventoryID = :mid AND BusinessID = :bid"
        ), {"mid": meat_inventory_id, "bid": BusinessID})
        db.commit()
        return {"message": "Deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
