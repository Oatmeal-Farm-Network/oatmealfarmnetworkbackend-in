# routers/provenance.py
# Farm-to-consumer traceability records.
# Links a marketplace listing to the field(s) it came from, the grow method,
# inputs used, and harvest date. A Gemini-powered endpoint drafts a consumer-facing
# "farm story" from the structured data, enabling data-backed traceability narratives.

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine, run_startup_ddl
from auth import get_current_user
from pydantic import BaseModel
from typing import Optional
import os

router = APIRouter(prefix="/api/provenance", tags=["provenance"])

def _ensure_provenance_table():
    with engine.begin() as _conn:
        _conn.execute(text("""
            IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ProvenanceRecords')
            BEGIN
                CREATE TABLE ProvenanceRecords (
                    RecordID              INT IDENTITY(1,1) PRIMARY KEY,
                    BusinessID            INT           NOT NULL,
                    ListingType           VARCHAR(20)   NOT NULL,
                    ListingSourceID       INT           NOT NULL,
                    FieldIDs              NVARCHAR(200) NULL,
                    GrowMethod            NVARCHAR(200) NULL,
                    InputsUsed            NVARCHAR(500) NULL,
                    HarvestDate           DATE          NULL,
                    SustainabilityNotes   NVARCHAR(MAX) NULL,
                    AIGeneratedNarrative  NVARCHAR(MAX) NULL,
                    NarrativeGeneratedAt  DATETIME      NULL,
                    CreatedAt             DATETIME      NOT NULL DEFAULT GETDATE(),
                    UpdatedAt             DATETIME      NOT NULL DEFAULT GETDATE()
                )
                CREATE UNIQUE INDEX IX_Provenance_Listing
                    ON ProvenanceRecords (BusinessID, ListingType, ListingSourceID)
            END
        """))


run_startup_ddl("provenance", _ensure_provenance_table)


class ProvenanceUpsert(BaseModel):
    listing_type: str
    listing_source_id: int
    field_ids: Optional[str] = None
    grow_method: Optional[str] = None
    inputs_used: Optional[str] = None
    harvest_date: Optional[str] = None
    sustainability_notes: Optional[str] = None


@router.get("/{listing_type}/{source_id}")
def get_provenance(listing_type: str, source_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT RecordID, BusinessID, ListingType, ListingSourceID, FieldIDs, GrowMethod,
               InputsUsed, HarvestDate, SustainabilityNotes, AIGeneratedNarrative,
               NarrativeGeneratedAt, CreatedAt
        FROM ProvenanceRecords
        WHERE ListingType = :lt AND ListingSourceID = :sid
    """), {"lt": listing_type, "sid": source_id}).mappings().first()
    return dict(row) if row else None


@router.post("")
def upsert_provenance(
    body: ProvenanceUpsert,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    biz = db.execute(text(
        "SELECT TOP 1 BusinessID FROM BusinessAccess "
        "WHERE PeopleID = :pid AND (Active IS NULL OR Active = 1)"
    ), {"pid": user.PeopleID}).scalar()
    if not biz:
        raise HTTPException(400, "No business linked to account")

    existing = db.execute(text(
        "SELECT RecordID FROM ProvenanceRecords "
        "WHERE BusinessID = :bid AND ListingType = :lt AND ListingSourceID = :sid"
    ), {"bid": biz, "lt": body.listing_type, "sid": body.listing_source_id}).scalar()

    params = {
        "fi": body.field_ids, "gm": body.grow_method, "iu": body.inputs_used,
        "hd": body.harvest_date, "sn": body.sustainability_notes,
    }
    if existing:
        db.execute(text("""
            UPDATE ProvenanceRecords
            SET FieldIDs = :fi, GrowMethod = :gm, InputsUsed = :iu,
                HarvestDate = :hd, SustainabilityNotes = :sn, UpdatedAt = GETDATE()
            WHERE RecordID = :rid
        """), {**params, "rid": existing})
        db.commit()
        return {"ok": True, "record_id": existing}
    else:
        rid = db.execute(text("""
            INSERT INTO ProvenanceRecords
                (BusinessID, ListingType, ListingSourceID, FieldIDs, GrowMethod,
                 InputsUsed, HarvestDate, SustainabilityNotes)
            OUTPUT INSERTED.RecordID
            VALUES (:bid, :lt, :sid, :fi, :gm, :iu, :hd, :sn)
        """), {"bid": biz, "lt": body.listing_type, "sid": body.listing_source_id, **params}).scalar()
        db.commit()
        return {"ok": True, "record_id": rid}


@router.post("/{record_id}/generate-narrative")
def generate_narrative(
    record_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Use Gemini to draft a warm, authentic consumer-facing farm story from the provenance data."""
    row = db.execute(text(
        "SELECT * FROM ProvenanceRecords WHERE RecordID = :rid"
    ), {"rid": record_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Provenance record not found")

    parts = []
    if row["GrowMethod"]:          parts.append(f"Grow method: {row['GrowMethod']}")
    if row["InputsUsed"]:          parts.append(f"Inputs used: {row['InputsUsed']}")
    if row["HarvestDate"]:         parts.append(f"Harvest date: {row['HarvestDate']}")
    if row["SustainabilityNotes"]: parts.append(f"Additional notes: {row['SustainabilityNotes']}")
    context = "\n".join(parts) or "Locally grown, small farm."

    prompt = (
        "Write a short (3-4 sentence) consumer-facing farm story for a marketplace listing. "
        "Be warm, authentic, and specific — emphasize freshness, local sourcing, and sustainable "
        "practices where mentioned. Avoid marketing clichés like 'farm-fresh' or 'artisanal'. "
        "Speak directly to the consumer occasionally. "
        f"\nFarm data:\n{context}"
    )

    narrative = _call_gemini(prompt)
    if not narrative:
        raise HTTPException(503, "Narrative generation unavailable — try again shortly")

    db.execute(text("""
        UPDATE ProvenanceRecords
        SET AIGeneratedNarrative = :n, NarrativeGeneratedAt = GETDATE()
        WHERE RecordID = :rid
    """), {"n": narrative, "rid": record_id})
    db.commit()
    return {"ok": True, "narrative": narrative}


def _call_gemini(prompt: str) -> Optional[str]:
    try:
        import ai_vertex as av
        model = av.make_model("gemini-2.0-flash")
        resp = av.generate_content(model, prompt)
        return resp.text.strip() if resp and resp.text else None
    except Exception as e:
        print(f"[provenance] Gemini error: {e}")
        return None
