from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

router = APIRouter(prefix="/api/associations", tags=["associations"])


@router.get("/list")
def list_associations(db: Session = Depends(get_db)):
    rows = db.execute(text(
        "SELECT AssociationID, AssociationName "
        "FROM associations "
        "WHERE AssociationName IS NOT NULL AND AssociationName <> '' "
        "ORDER BY AssociationName"
    )).mappings().all()
    return [dict(r) for r in rows]


@router.get("/my-memberships")
def my_memberships(PeopleID: int, BusinessID: Optional[int] = None, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT am.associationmemberID, am.AssociationID, am.BusinessID,
               am.Favorite, am.MemberPosition, a.AssociationName
        FROM associationmembers am
        LEFT JOIN associations a ON a.AssociationID = am.AssociationID
        WHERE am.PeopleID = :pid
    """), {"pid": PeopleID}).mappings().all()

    memberships = [dict(r) for r in rows]

    favorite = None
    if BusinessID is not None:
        for m in memberships:
            if m["BusinessID"] == BusinessID and m["Favorite"] == 1:
                favorite = m
                break
    if favorite is None:
        for m in memberships:
            if m["BusinessID"] is None and m["Favorite"] == 1:
                favorite = m
                break

    return {"memberships": memberships, "favorite": favorite}


class SetFavoriteBody(BaseModel):
    PeopleID: int
    BusinessID: int
    AssociationID: int


@router.post("/set-favorite")
def set_favorite(body: SetFavoriteBody, db: Session = Depends(get_db)):
    # Clear any existing favorite rows scoped to this (PeopleID, BusinessID).
    db.execute(text("""
        UPDATE associationmembers
        SET Favorite = 0
        WHERE PeopleID = :pid AND BusinessID = :bid AND Favorite = 1
    """), {"pid": body.PeopleID, "bid": body.BusinessID})

    existing = db.execute(text("""
        SELECT associationmemberID FROM associationmembers
        WHERE PeopleID = :pid AND BusinessID = :bid AND AssociationID = :aid
    """), {"pid": body.PeopleID, "bid": body.BusinessID, "aid": body.AssociationID}).scalar()

    if existing:
        db.execute(text("""
            UPDATE associationmembers SET Favorite = 1
            WHERE associationmemberID = :id
        """), {"id": existing})
    else:
        db.execute(text("""
            INSERT INTO associationmembers (PeopleID, AssociationID, BusinessID, Favorite, AccessLevel)
            VALUES (:pid, :aid, :bid, 1, 0)
        """), {"pid": body.PeopleID, "aid": body.AssociationID, "bid": body.BusinessID})

    db.commit()

    name = db.execute(text(
        "SELECT AssociationName FROM associations WHERE AssociationID = :aid"
    ), {"aid": body.AssociationID}).scalar()

    return {
        "FavoriteAssociationID": body.AssociationID,
        "FavoriteAssociationName": name,
    }


class ClearFavoriteBody(BaseModel):
    PeopleID: int
    BusinessID: int


@router.post("/clear-favorite")
def clear_favorite(body: ClearFavoriteBody, db: Session = Depends(get_db)):
    db.execute(text("""
        UPDATE associationmembers SET Favorite = 0
        WHERE PeopleID = :pid AND BusinessID = :bid AND Favorite = 1
    """), {"pid": body.PeopleID, "bid": body.BusinessID})
    db.commit()
    return {"FavoriteAssociationID": None, "FavoriteAssociationName": None}
