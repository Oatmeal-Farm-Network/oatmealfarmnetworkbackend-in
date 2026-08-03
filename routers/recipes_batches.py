"""
Recipes & Batches — artisan-producer production records.

Tables created on first request (IF NOT EXISTS):
  ProducerRecipes, RecipeIngredients, RecipeSteps
  ProducerBatches, BatchIngredients
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional, List
from datetime import date, datetime
from pydantic import BaseModel

router = APIRouter(prefix="/api/recipes-batches", tags=["recipes-batches"])


# ── Table creation ────────────────────────────────────────────────────────────

def _ensure_tables(db: Session):
    stmts = [
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ProducerRecipes')
        CREATE TABLE ProducerRecipes (
            RecipeID      INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID    INT NOT NULL,
            RecipeName    NVARCHAR(300) NOT NULL,
            Category      NVARCHAR(100),
            Description   NVARCHAR(MAX),
            YieldQty      DECIMAL(10,3),
            YieldUnit     NVARCHAR(60),
            BatchSizeNote NVARCHAR(300),
            IsArchived    BIT DEFAULT 0,
            CreatedAt     DATETIME DEFAULT GETDATE(),
            UpdatedAt     DATETIME DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='RecipeIngredients')
        CREATE TABLE RecipeIngredients (
            RecipeIngID   INT IDENTITY(1,1) PRIMARY KEY,
            RecipeID      INT NOT NULL,
            IngredientName NVARCHAR(200) NOT NULL,
            Quantity      DECIMAL(12,4),
            Unit          NVARCHAR(60),
            Notes         NVARCHAR(300)
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='RecipeSteps')
        CREATE TABLE RecipeSteps (
            StepID        INT IDENTITY(1,1) PRIMARY KEY,
            RecipeID      INT NOT NULL,
            StepNumber    INT NOT NULL,
            StepText      NVARCHAR(MAX) NOT NULL
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ProducerBatches')
        CREATE TABLE ProducerBatches (
            BatchID       INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID    INT NOT NULL,
            RecipeID      INT,
            RecipeName    NVARCHAR(300),
            BatchDate     DATE DEFAULT CAST(GETDATE() AS DATE),
            BatchSize     DECIMAL(10,3) DEFAULT 1,
            SizeUnit      NVARCHAR(60),
            Status        NVARCHAR(30) DEFAULT 'planned',
            Notes         NVARCHAR(MAX),
            CreatedAt     DATETIME DEFAULT GETDATE(),
            UpdatedAt     DATETIME DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='BatchIngredients')
        CREATE TABLE BatchIngredients (
            BatchIngID      INT IDENTITY(1,1) PRIMARY KEY,
            BatchID         INT NOT NULL,
            IngredientName  NVARCHAR(200) NOT NULL,
            PlannedQty      DECIMAL(12,4),
            ActualQty       DECIMAL(12,4),
            Unit            NVARCHAR(60),
            Notes           NVARCHAR(300)
        )""",
    ]
    for stmt in stmts:
        try:
            db.execute(text(stmt))
        except Exception:
            pass
    try:
        db.commit()
    except Exception:
        pass


# ── Pydantic models ───────────────────────────────────────────────────────────

class IngredientIn(BaseModel):
    ingredient_name: str
    quantity: Optional[float] = None
    unit: Optional[str] = None
    notes: Optional[str] = None

class StepIn(BaseModel):
    step_number: int
    step_text: str

class RecipeIn(BaseModel):
    business_id: int
    recipe_name: str
    category: Optional[str] = None
    description: Optional[str] = None
    yield_qty: Optional[float] = None
    yield_unit: Optional[str] = None
    batch_size_note: Optional[str] = None
    ingredients: Optional[List[IngredientIn]] = []
    steps: Optional[List[StepIn]] = []

class RecipeUpdate(BaseModel):
    recipe_name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    yield_qty: Optional[float] = None
    yield_unit: Optional[str] = None
    batch_size_note: Optional[str] = None
    is_archived: Optional[bool] = None
    ingredients: Optional[List[IngredientIn]] = None
    steps: Optional[List[StepIn]] = None

class BatchIngIn(BaseModel):
    ingredient_name: str
    planned_qty: Optional[float] = None
    actual_qty: Optional[float] = None
    unit: Optional[str] = None
    notes: Optional[str] = None

class BatchIn(BaseModel):
    business_id: int
    recipe_id: Optional[int] = None
    batch_date: Optional[str] = None
    batch_size: Optional[float] = 1.0
    size_unit: Optional[str] = None
    status: Optional[str] = "planned"
    notes: Optional[str] = None
    ingredients: Optional[List[BatchIngIn]] = []

class BatchUpdate(BaseModel):
    batch_date: Optional[str] = None
    batch_size: Optional[float] = None
    size_unit: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    ingredients: Optional[List[BatchIngIn]] = None


# ── Recipes ───────────────────────────────────────────────────────────────────

@router.get("/recipes")
def list_recipes(business_id: int, q: Optional[str] = None, db: Session = Depends(get_db)):
    _ensure_tables(db)
    where = "WHERE r.BusinessID = :bid AND r.IsArchived = 0"
    params: dict = {"bid": business_id}
    if q:
        where += " AND (r.RecipeName LIKE :q OR r.Category LIKE :q)"
        params["q"] = f"%{q}%"
    rows = db.execute(text(
        f"SELECT r.RecipeID, r.RecipeName, r.Category, r.YieldQty, r.YieldUnit, "
        f"r.BatchSizeNote, r.CreatedAt, r.UpdatedAt "
        f"FROM ProducerRecipes r {where} ORDER BY r.RecipeName"
    ), params).mappings().all()
    return [dict(r) for r in rows]


@router.post("/recipes", status_code=201)
def create_recipe(body: RecipeIn, db: Session = Depends(get_db)):
    _ensure_tables(db)
    result = db.execute(text(
        "INSERT INTO ProducerRecipes (BusinessID, RecipeName, Category, Description, "
        "YieldQty, YieldUnit, BatchSizeNote) "
        "OUTPUT INSERTED.RecipeID "
        "VALUES (:bid, :name, :cat, :desc, :yq, :yu, :bsn)"
    ), {
        "bid": body.business_id, "name": body.recipe_name[:300],
        "cat": (body.category or "")[:100], "desc": body.description or "",
        "yq": body.yield_qty, "yu": (body.yield_unit or "")[:60],
        "bsn": (body.batch_size_note or "")[:300],
    })
    recipe_id = result.scalar()
    db.commit()

    _upsert_recipe_children(db, recipe_id, body.ingredients or [], body.steps or [])
    return {"recipe_id": recipe_id}


@router.get("/recipes/{recipe_id}")
def get_recipe(recipe_id: int, business_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    row = db.execute(text(
        "SELECT * FROM ProducerRecipes WHERE RecipeID = :rid AND BusinessID = :bid"
    ), {"rid": recipe_id, "bid": business_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Recipe not found")
    recipe = dict(row)
    recipe["ingredients"] = [dict(r) for r in db.execute(text(
        "SELECT * FROM RecipeIngredients WHERE RecipeID = :rid ORDER BY RecipeIngID"
    ), {"rid": recipe_id}).mappings().all()]
    recipe["steps"] = [dict(r) for r in db.execute(text(
        "SELECT * FROM RecipeSteps WHERE RecipeID = :rid ORDER BY StepNumber"
    ), {"rid": recipe_id}).mappings().all()]
    return recipe


@router.put("/recipes/{recipe_id}")
def update_recipe(recipe_id: int, business_id: int, body: RecipeUpdate, db: Session = Depends(get_db)):
    _ensure_tables(db)
    sets, params = [], {"rid": recipe_id, "bid": business_id}
    if body.recipe_name is not None:
        sets.append("RecipeName = :name"); params["name"] = body.recipe_name[:300]
    if body.category is not None:
        sets.append("Category = :cat"); params["cat"] = body.category[:100]
    if body.description is not None:
        sets.append("Description = :desc"); params["desc"] = body.description
    if body.yield_qty is not None:
        sets.append("YieldQty = :yq"); params["yq"] = body.yield_qty
    if body.yield_unit is not None:
        sets.append("YieldUnit = :yu"); params["yu"] = body.yield_unit[:60]
    if body.batch_size_note is not None:
        sets.append("BatchSizeNote = :bsn"); params["bsn"] = body.batch_size_note[:300]
    if body.is_archived is not None:
        sets.append("IsArchived = :arch"); params["arch"] = int(body.is_archived)
    if sets:
        sets.append("UpdatedAt = GETDATE()")
        db.execute(text(
            f"UPDATE ProducerRecipes SET {', '.join(sets)} WHERE RecipeID = :rid AND BusinessID = :bid"
        ), params)
        db.commit()
    if body.ingredients is not None or body.steps is not None:
        _upsert_recipe_children(
            db, recipe_id,
            body.ingredients if body.ingredients is not None else [],
            body.steps if body.steps is not None else [],
        )
    return {"ok": True}


@router.delete("/recipes/{recipe_id}")
def archive_recipe(recipe_id: int, business_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text(
        "UPDATE ProducerRecipes SET IsArchived = 1, UpdatedAt = GETDATE() "
        "WHERE RecipeID = :rid AND BusinessID = :bid"
    ), {"rid": recipe_id, "bid": business_id})
    db.commit()
    return {"ok": True}


def _upsert_recipe_children(db, recipe_id, ingredients, steps):
    db.execute(text("DELETE FROM RecipeIngredients WHERE RecipeID = :rid"), {"rid": recipe_id})
    db.execute(text("DELETE FROM RecipeSteps WHERE RecipeID = :rid"), {"rid": recipe_id})
    for ing in ingredients:
        db.execute(text(
            "INSERT INTO RecipeIngredients (RecipeID, IngredientName, Quantity, Unit, Notes) "
            "VALUES (:rid, :name, :qty, :unit, :notes)"
        ), {"rid": recipe_id, "name": ing.ingredient_name[:200],
            "qty": ing.quantity, "unit": (ing.unit or "")[:60],
            "notes": (ing.notes or "")[:300]})
    for step in steps:
        db.execute(text(
            "INSERT INTO RecipeSteps (RecipeID, StepNumber, StepText) VALUES (:rid, :num, :txt)"
        ), {"rid": recipe_id, "num": step.step_number, "txt": step.step_text})
    db.commit()


# ── Batches ───────────────────────────────────────────────────────────────────

@router.get("/batches")
def list_batches(
    business_id: int,
    recipe_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    where = "WHERE b.BusinessID = :bid"
    params: dict = {"bid": business_id}
    if recipe_id:
        where += " AND b.RecipeID = :rid"; params["rid"] = recipe_id
    if status:
        where += " AND b.Status = :status"; params["status"] = status
    rows = db.execute(text(
        f"SELECT b.BatchID, b.RecipeID, b.RecipeName, b.BatchDate, b.BatchSize, "
        f"b.SizeUnit, b.Status, b.Notes, b.CreatedAt, b.UpdatedAt "
        f"FROM ProducerBatches b {where} ORDER BY b.BatchDate DESC, b.BatchID DESC"
    ), params).mappings().all()
    return [dict(r) for r in rows]


@router.post("/batches", status_code=201)
def log_batch(body: BatchIn, db: Session = Depends(get_db)):
    _ensure_tables(db)

    recipe_name = None
    recipe_ingredients = []
    if body.recipe_id:
        r = db.execute(text(
            "SELECT RecipeName FROM ProducerRecipes WHERE RecipeID = :rid AND BusinessID = :bid"
        ), {"rid": body.recipe_id, "bid": body.business_id}).mappings().first()
        if r:
            recipe_name = r["RecipeName"]
        recipe_ingredients = db.execute(text(
            "SELECT IngredientName, Quantity, Unit FROM RecipeIngredients WHERE RecipeID = :rid"
        ), {"rid": body.recipe_id}).mappings().all()

    result = db.execute(text(
        "INSERT INTO ProducerBatches (BusinessID, RecipeID, RecipeName, BatchDate, "
        "BatchSize, SizeUnit, Status, Notes) "
        "OUTPUT INSERTED.BatchID "
        "VALUES (:bid, :rid, :rname, :bdate, :bsz, :sunit, :status, :notes)"
    ), {
        "bid": body.business_id, "rid": body.recipe_id,
        "rname": recipe_name, "bdate": body.batch_date or str(date.today()),
        "bsz": body.batch_size or 1.0, "sunit": (body.size_unit or "")[:60],
        "status": (body.status or "planned")[:30], "notes": body.notes or "",
    })
    batch_id = result.scalar()
    db.commit()

    # Seed BatchIngredients from recipe, then overlay any caller-supplied overrides
    caller_map = {i.ingredient_name.lower(): i for i in (body.ingredients or [])}
    if recipe_ingredients and not body.ingredients:
        scale = float(body.batch_size or 1.0)
        for ri in recipe_ingredients:
            planned = (float(ri["Quantity"]) * scale) if ri["Quantity"] else None
            db.execute(text(
                "INSERT INTO BatchIngredients (BatchID, IngredientName, PlannedQty, Unit) "
                "VALUES (:bid, :name, :pq, :unit)"
            ), {"bid": batch_id, "name": ri["IngredientName"], "pq": planned, "unit": ri["Unit"] or ""})
    else:
        for ing in (body.ingredients or []):
            db.execute(text(
                "INSERT INTO BatchIngredients (BatchID, IngredientName, PlannedQty, ActualQty, Unit, Notes) "
                "VALUES (:bid, :name, :pq, :aq, :unit, :notes)"
            ), {"bid": batch_id, "name": ing.ingredient_name[:200],
                "pq": ing.planned_qty, "aq": ing.actual_qty,
                "unit": (ing.unit or "")[:60], "notes": (ing.notes or "")[:300]})
    db.commit()
    return {"batch_id": batch_id}


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int, business_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    row = db.execute(text(
        "SELECT * FROM ProducerBatches WHERE BatchID = :bid AND BusinessID = :biz"
    ), {"bid": batch_id, "biz": business_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Batch not found")
    batch = dict(row)
    batch["ingredients"] = [dict(r) for r in db.execute(text(
        "SELECT * FROM BatchIngredients WHERE BatchID = :bid ORDER BY BatchIngID"
    ), {"bid": batch_id}).mappings().all()]
    return batch


@router.put("/batches/{batch_id}")
def update_batch(batch_id: int, business_id: int, body: BatchUpdate, db: Session = Depends(get_db)):
    _ensure_tables(db)
    sets, params = [], {"bid": batch_id, "biz": business_id}
    if body.batch_date is not None:
        sets.append("BatchDate = :bdate"); params["bdate"] = body.batch_date
    if body.batch_size is not None:
        sets.append("BatchSize = :bsz"); params["bsz"] = body.batch_size
    if body.size_unit is not None:
        sets.append("SizeUnit = :sunit"); params["sunit"] = body.size_unit[:60]
    if body.status is not None:
        sets.append("Status = :status"); params["status"] = body.status[:30]
    if body.notes is not None:
        sets.append("Notes = :notes"); params["notes"] = body.notes
    if sets:
        sets.append("UpdatedAt = GETDATE()")
        db.execute(text(
            f"UPDATE ProducerBatches SET {', '.join(sets)} WHERE BatchID = :bid AND BusinessID = :biz"
        ), params)
        db.commit()
    if body.ingredients is not None:
        db.execute(text("DELETE FROM BatchIngredients WHERE BatchID = :bid"), {"bid": batch_id})
        for ing in body.ingredients:
            db.execute(text(
                "INSERT INTO BatchIngredients (BatchID, IngredientName, PlannedQty, ActualQty, Unit, Notes) "
                "VALUES (:bid, :name, :pq, :aq, :unit, :notes)"
            ), {"bid": batch_id, "name": ing.ingredient_name[:200],
                "pq": ing.planned_qty, "aq": ing.actual_qty,
                "unit": (ing.unit or "")[:60], "notes": (ing.notes or "")[:300]})
        db.commit()
    return {"ok": True}


@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: int, business_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM BatchIngredients WHERE BatchID = :bid"), {"bid": batch_id})
    db.execute(text(
        "DELETE FROM ProducerBatches WHERE BatchID = :bid AND BusinessID = :biz"
    ), {"bid": batch_id, "biz": business_id})
    db.commit()
    return {"ok": True}
