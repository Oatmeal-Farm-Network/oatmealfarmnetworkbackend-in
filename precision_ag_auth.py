"""
precision_ag_auth.py — shared BusinessAccess authorization helpers for
routers/precision_ag.py and routers/precision_ag_features.py.

Both routers scope all of their data by Field -> BusinessID -> BusinessAccess,
so this module centralizes the two checks every endpoint needs instead of
duplicating the same SQL/ORM logic in both files.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
import models


def _field_business_id(db: Session, field_id: int) -> int:
    """Look up a field's BusinessID, or raise 404 if the field doesn't exist."""
    field = (
        db.query(models.Field)
        .filter(models.Field.FieldID == field_id, models.Field.DeletedAt.is_(None))
        .first()
    )
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    return field.BusinessID


def _verify_business_access(db: Session, people_id: int, business_id: int) -> None:
    """Raise 403 unless the user has an active BusinessAccess row for this business."""
    row = db.execute(
        text(
            "SELECT TOP 1 1 FROM BusinessAccess "
            "WHERE PeopleID = :pid AND BusinessID = :bid AND (Active IS NULL OR Active = 1)"
        ),
        {"pid": people_id, "bid": business_id},
    ).first()
    if not row:
        raise HTTPException(status_code=403, detail="Not authorized for this business")


def _verify_field_access(db: Session, people_id: int, field_id: int) -> int:
    """Combine the two checks above for the common field_id-keyed endpoints.
    Returns the field's BusinessID for callers that need it anyway."""
    business_id = _field_business_id(db, field_id)
    _verify_business_access(db, people_id, business_id)
    return business_id
