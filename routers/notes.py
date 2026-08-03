from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine, Base
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel
import models

router = APIRouter(prefix="/api", tags=["notes"])

# Auto-create FieldNote table if it doesn't exist yet.
# Guarded so a DB outage at startup can't crash the whole container (the import
# would otherwise raise and uvicorn would exit(1) before binding the port).
try:
    Base.metadata.create_all(bind=engine, tables=[models.FieldNote.__table__], checkfirst=True)
except Exception as e:
    print(f"[notes] create_all skipped (DB unavailable): {e}")


class NoteCreate(BaseModel):
    field_id:   int
    business_id: int
    people_id:  Optional[int] = None
    note_date:  str           # ISO date string
    category:   str
    title:      str
    content:    str
    severity:   Optional[str]   = None  # Low/Medium/High/Critical (scouting-style)
    latitude:   Optional[float] = None
    longitude:  Optional[float] = None
    image_url:  Optional[str]   = None


class NoteUpdate(BaseModel):
    note_date: str
    category:  str
    title:     str
    content:   str
    severity:  Optional[str]   = None
    latitude:  Optional[float] = None
    longitude: Optional[float] = None
    image_url: Optional[str]   = None


def _serialize(n: models.FieldNote) -> dict:
    return {
        "note_id":    n.NoteID,
        "field_id":   n.FieldID,
        "business_id":n.BusinessID,
        "people_id":  n.PeopleID,
        "note_date":  str(n.NoteDate) if n.NoteDate else None,
        "category":   n.Category,
        "title":      n.Title,
        "content":    n.Content,
        "severity":   n.Severity,
        "latitude":   float(n.Latitude)  if n.Latitude  is not None else None,
        "longitude":  float(n.Longitude) if n.Longitude is not None else None,
        "image_url":  n.ImageUrl,
        "created_at": str(n.CreatedAt) if n.CreatedAt else None,
        "updated_at": str(n.UpdatedAt) if n.UpdatedAt else None,
    }


@router.get("/notes")
def list_notes(business_id: int, field_id: Optional[int] = None,
               category: Optional[str] = None, db: Session = Depends(get_db)):
    try:
        q = db.query(models.FieldNote).filter(models.FieldNote.BusinessID == business_id)
        if field_id:
            q = q.filter(models.FieldNote.FieldID == field_id)
        if category:
            q = q.filter(models.FieldNote.Category == category)
        notes = q.order_by(models.FieldNote.NoteDate.desc(), models.FieldNote.CreatedAt.desc()).all()
        return [_serialize(n) for n in notes]
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notes")
def create_note(note: NoteCreate, db: Session = Depends(get_db)):
    try:
        new_note = models.FieldNote(
            FieldID    = note.field_id,
            BusinessID = note.business_id,
            PeopleID   = note.people_id,
            NoteDate   = date.fromisoformat(note.note_date),
            Category   = note.category,
            Title      = note.title,
            Content    = note.content,
            Severity   = note.severity,
            Latitude   = note.latitude,
            Longitude  = note.longitude,
            ImageUrl   = note.image_url,
            CreatedAt  = datetime.utcnow(),
            UpdatedAt  = datetime.utcnow(),
        )
        db.add(new_note)
        db.commit()
        db.refresh(new_note)
        return _serialize(new_note)
    except Exception as e:
        db.rollback()
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/notes/{note_id}")
def update_note(note_id: int, note: NoteUpdate, db: Session = Depends(get_db)):
    try:
        existing = db.query(models.FieldNote).filter(models.FieldNote.NoteID == note_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Note not found")
        existing.NoteDate  = date.fromisoformat(note.note_date)
        existing.Category  = note.category
        existing.Title     = note.title
        existing.Content   = note.content
        existing.Severity  = note.severity
        existing.Latitude  = note.latitude
        existing.Longitude = note.longitude
        existing.ImageUrl  = note.image_url
        existing.UpdatedAt = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return _serialize(existing)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/notes/{note_id}")
def delete_note(note_id: int, db: Session = Depends(get_db)):
    try:
        note = db.query(models.FieldNote).filter(models.FieldNote.NoteID == note_id).first()
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        db.delete(note)
        db.commit()
        return {"success": True, "deleted_id": note_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
