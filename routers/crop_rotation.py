from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db, engine, Base
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel
import models

router = APIRouter(prefix="/api", tags=["crop-rotation"])

# Guarded so a DB outage at startup can't crash the whole container.
try:
    Base.metadata.create_all(
        bind=engine, tables=[models.CropRotationEntry.__table__], checkfirst=True
    )
except Exception as e:
    print(f"[crop_rotation] create_all skipped (DB unavailable): {e}")


class RotationCreate(BaseModel):
    field_id:     int
    business_id:  int
    season_year:  int
    crop_name:    str
    variety:      Optional[str] = None
    planting_date:Optional[str] = None
    harvest_date: Optional[str] = None
    yield_amount: Optional[float] = None
    yield_unit:   Optional[str] = None
    is_cover_crop:Optional[bool] = False
    notes:        Optional[str] = None


class RotationUpdate(BaseModel):
    season_year:  int
    crop_name:    str
    variety:      Optional[str] = None
    planting_date:Optional[str] = None
    harvest_date: Optional[str] = None
    yield_amount: Optional[float] = None
    yield_unit:   Optional[str] = None
    is_cover_crop:Optional[bool] = False
    notes:        Optional[str] = None


def _parse_date(s):
    try:
        return date.fromisoformat(s) if s else None
    except Exception:
        return None


def _serialize(r: models.CropRotationEntry) -> dict:
    return {
        "rotation_id":  r.RotationID,
        "field_id":     r.FieldID,
        "business_id":  r.BusinessID,
        "season_year":  r.SeasonYear,
        "crop_name":    r.CropName,
        "variety":      r.Variety,
        "planting_date":str(r.PlantingDate)  if r.PlantingDate  else None,
        "harvest_date": str(r.HarvestDate)   if r.HarvestDate   else None,
        "yield_amount": float(r.YieldAmount) if r.YieldAmount   else None,
        "yield_unit":   r.YieldUnit,
        "is_cover_crop":bool(r.IsCoverCrop),
        "notes":        r.Notes,
        "created_at":   str(r.CreatedAt)     if r.CreatedAt     else None,
    }


@router.get("/crop-rotation")
def list_rotation(business_id: int, field_id: Optional[int] = None,
                  db: Session = Depends(get_db)):
    try:
        q = db.query(models.CropRotationEntry)\
              .filter(models.CropRotationEntry.BusinessID == business_id)
        if field_id:
            q = q.filter(models.CropRotationEntry.FieldID == field_id)
        entries = q.order_by(
            models.CropRotationEntry.FieldID,
            models.CropRotationEntry.SeasonYear.desc()
        ).all()
        return [_serialize(e) for e in entries]
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/crop-rotation")
def create_rotation(entry: RotationCreate, db: Session = Depends(get_db)):
    try:
        new = models.CropRotationEntry(
            FieldID      = entry.field_id,
            BusinessID   = entry.business_id,
            SeasonYear   = entry.season_year,
            CropName     = entry.crop_name,
            Variety      = entry.variety,
            PlantingDate = _parse_date(entry.planting_date),
            HarvestDate  = _parse_date(entry.harvest_date),
            YieldAmount  = entry.yield_amount,
            YieldUnit    = entry.yield_unit,
            IsCoverCrop  = entry.is_cover_crop or False,
            Notes        = entry.notes,
            CreatedAt    = datetime.utcnow(),
            UpdatedAt    = datetime.utcnow(),
        )
        db.add(new); db.commit(); db.refresh(new)
        return _serialize(new)
    except Exception as e:
        db.rollback()
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/crop-rotation/{rotation_id}")
def update_rotation(rotation_id: int, entry: RotationUpdate,
                    db: Session = Depends(get_db)):
    try:
        existing = db.query(models.CropRotationEntry)\
                     .filter(models.CropRotationEntry.RotationID == rotation_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Entry not found")
        existing.SeasonYear   = entry.season_year
        existing.CropName     = entry.crop_name
        existing.Variety      = entry.variety
        existing.PlantingDate = _parse_date(entry.planting_date)
        existing.HarvestDate  = _parse_date(entry.harvest_date)
        existing.YieldAmount  = entry.yield_amount
        existing.YieldUnit    = entry.yield_unit
        existing.IsCoverCrop  = entry.is_cover_crop or False
        existing.Notes        = entry.notes
        existing.UpdatedAt    = datetime.utcnow()
        db.commit(); db.refresh(existing)
        return _serialize(existing)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/crop-rotation/{rotation_id}")
def delete_rotation(rotation_id: int, db: Session = Depends(get_db)):
    try:
        entry = db.query(models.CropRotationEntry)\
                  .filter(models.CropRotationEntry.RotationID == rotation_id).first()
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        db.delete(entry); db.commit()
        return {"success": True, "deleted_id": rotation_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
