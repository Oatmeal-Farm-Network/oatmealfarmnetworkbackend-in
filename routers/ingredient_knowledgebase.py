from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from database import get_db
import re
from routers.translation import translate_fields, translate_list

router = APIRouter(prefix="/api/ingredient-knowledgebase", tags=["ingredient-knowledgebase"])

def to_slug(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')

@router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    try:
        sql = text("""
            SELECT IC.IngredientCategoryID, IC.IngredientCategory,
                   COUNT(DISTINCT I.IngredientID) AS IngredientCount,
                   COUNT(DISTINCT IV.IngredientVarietyPK) AS VarietyCount
            FROM IngredientCategoryLookup IC
            LEFT JOIN Ingredients I ON I.IngredientCategoryID = IC.IngredientCategoryID
            LEFT JOIN IngredientsVarieties IV ON IV.IngredientID = I.IngredientID
            GROUP BY IC.IngredientCategoryID, IC.IngredientCategory
            ORDER BY IC.IngredientCategory
        """)
        rows = db.execute(sql).fetchall()

        total_varieties = sum(r.VarietyCount for r in rows)
        total_ingredients = sum(r.IngredientCount for r in rows)

        return {
            "total_varieties": total_varieties,
            "total_ingredients": total_ingredients,
            "categories": [
                {
                    "id": r.IngredientCategoryID,
                    "name": r.IngredientCategory,
                    "description": None,
                    "image": None,
                    "slug": to_slug(r.IngredientCategory),
                    "ingredient_count": r.IngredientCount,
                    "variety_count": r.VarietyCount,
                }
                for r in rows
            ]
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/category/{slug}")
def get_category(slug: str, lang: str = "en", db: Session = Depends(get_db)):
    try:
        # Get all categories and find matching slug
        sql = text("""
            SELECT IC.IngredientCategoryID, IC.IngredientCategory
            FROM IngredientCategoryLookup IC
            ORDER BY IC.IngredientCategory
        """)
        rows = db.execute(sql).fetchall()
        cat_row = next((r for r in rows if to_slug(r.IngredientCategory) == slug), None)
        if not cat_row:
            raise HTTPException(status_code=404, detail="Category not found")

        # Get ingredients for this category
        ing_sql = text("""
            SELECT I.IngredientID, I.IngredientName, I.IngredientDescription,
                   I.IngredientImage, COUNT(IV.IngredientVarietyPK) AS VarietyCount
            FROM Ingredients I
            LEFT JOIN IngredientsVarieties IV ON IV.IngredientID = I.IngredientID
            WHERE I.IngredientCategoryID = :cat_id
            GROUP BY I.IngredientID, I.IngredientName, I.IngredientDescription, I.IngredientImage
            ORDER BY I.IngredientName
        """)
        ing_rows = db.execute(ing_sql, {"cat_id": cat_row.IngredientCategoryID}).fetchall()

        result = {
            "category_id": cat_row.IngredientCategoryID,
            "category_name": cat_row.IngredientCategory,
            "description": None,
            "header_image": None,
            "ingredients": [
                {
                    "id": r.IngredientID,
                    "name": r.IngredientName,
                    "description": r.IngredientDescription,
                    "image": r.IngredientImage,
                    "variety_count": r.VarietyCount,
                }
                for r in ing_rows
            ]
        }
        result["ingredients"] = translate_list(result["ingredients"], ["description"], lang, db)
        return result
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/varieties/{ingredient_id}")
def get_varieties(ingredient_id: int, lang: str = "en", db: Session = Depends(get_db)):
    try:
        # Get ingredient name
        ing_row = db.execute(
            text("SELECT IngredientName, IngredientDescription FROM Ingredients WHERE IngredientID = :id"),
            {"id": ingredient_id}
        ).fetchone()
        if not ing_row:
            raise HTTPException(status_code=404, detail="Ingredient not found")

        sql = text("""
            SELECT IV.IngredientVarietyPK, IV.IngredientName, IV.IngredientDescription,
                   ISNULL(T.NutrientCount, 0) AS NutrientCount
            FROM IngredientsVarieties IV
            LEFT JOIN (
                SELECT IngredientVarietyPK, COUNT(DISTINCT NutrientID) AS NutrientCount
                FROM IngredientNutrient
                WHERE IngredientVarietyPK IS NOT NULL
                GROUP BY IngredientVarietyPK
            ) T ON IV.IngredientVarietyPK = T.IngredientVarietyPK
            WHERE IV.IngredientID = :ing_id
            ORDER BY IV.IngredientName
        """)
        rows = db.execute(sql, {"ing_id": ingredient_id}).fetchall()

        result = {
            "ingredient_name": ing_row.IngredientName,
            "ingredient_description": ing_row.IngredientDescription,
            "varieties": [
                {
                    "id": r.IngredientVarietyPK,
                    "name": r.IngredientName,
                    "description": r.IngredientDescription,
                    "nutrient_count": r.NutrientCount,
                }
                for r in rows
            ]
        }
        result["varieties"] = translate_list(result["varieties"], ["description"], lang, db)
        return translate_fields(result, ["ingredient_description"], lang, db)
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))