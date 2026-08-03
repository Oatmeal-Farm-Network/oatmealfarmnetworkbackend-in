import base64
import io
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional

router = APIRouter(prefix="/api/documents", tags=["document_vault"])

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB

CREATE_TABLE = """
IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'BusinessDocument')
CREATE TABLE BusinessDocument (
    DocumentID   INT IDENTITY PRIMARY KEY,
    BusinessID   INT NOT NULL,
    Title        NVARCHAR(300) NOT NULL,
    Category     NVARCHAR(100) NOT NULL DEFAULT 'Other',
    FileName     NVARCHAR(500) NULL,
    FileContent  NVARCHAR(MAX) NULL,
    MimeType     NVARCHAR(100) NULL,
    FileSizeKB   INT NULL,
    ExpiryDate   DATE NULL,
    Tags         NVARCHAR(500) NULL,
    Notes        NVARCHAR(2000) NULL,
    UploadedBy   NVARCHAR(255) NULL,
    CreatedAt    DATETIME2 DEFAULT GETDATE()
)
"""

ALLOWED_MIME = {
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/png", "image/jpeg", "image/webp",
    "text/plain", "text/csv",
}


def _ensure_table(db):
    try:
        db.execute(text(CREATE_TABLE))
        db.commit()
    except Exception:
        db.rollback()


@router.post("/upload")
async def upload_document(
    business_id: int = Form(...),
    title: str = Form(...),
    category: str = Form("Other"),
    expiry_date: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    uploaded_by: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    _ensure_table(db)
    content = await file.read()
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit.")

    mime = file.content_type or "application/octet-stream"
    if mime not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail=f"File type '{mime}' not allowed.")

    b64 = base64.b64encode(content).decode("ascii")
    size_kb = len(content) // 1024

    exp = expiry_date if expiry_date else None

    row = db.execute(text("""
        INSERT INTO BusinessDocument
            (BusinessID, Title, Category, FileName, FileContent, MimeType,
             FileSizeKB, ExpiryDate, Tags, Notes, UploadedBy)
        OUTPUT INSERTED.DocumentID
        VALUES (:bid, :title, :cat, :fname, :content, :mime,
                :kb, :exp, :tags, :notes, :by)
    """), {
        "bid": business_id, "title": title, "cat": category,
        "fname": file.filename, "content": b64, "mime": mime,
        "kb": size_kb, "exp": exp, "tags": tags, "notes": notes, "by": uploaded_by,
    }).fetchone()
    db.commit()
    return {"document_id": row[0]}


@router.get("/list")
def list_documents(
    business_id: int,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _ensure_table(db)
    where = "WHERE BusinessID = :bid"
    params: dict = {"bid": business_id}
    if category and category != "All":
        where += " AND Category = :cat"
        params["cat"] = category

    rows = db.execute(text(f"""
        SELECT DocumentID, Title, Category, FileName, MimeType, FileSizeKB,
               ExpiryDate, Tags, Notes, UploadedBy, CreatedAt
        FROM BusinessDocument {where}
        ORDER BY CreatedAt DESC
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/{doc_id}/download")
def download_document(doc_id: int, business_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT FileName, FileContent, MimeType FROM BusinessDocument
        WHERE DocumentID = :did AND BusinessID = :bid
    """), {"did": doc_id, "bid": business_id}).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Document not found.")

    fname, b64, mime = row
    content = base64.b64decode(b64)
    return StreamingResponse(
        io.BytesIO(content),
        media_type=mime or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{fname or "document"}"'},
    )


@router.delete("/{doc_id}")
def delete_document(doc_id: int, business_id: int, db: Session = Depends(get_db)):
    result = db.execute(text("""
        DELETE FROM BusinessDocument WHERE DocumentID = :did AND BusinessID = :bid
    """), {"did": doc_id, "bid": business_id})
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"ok": True}


@router.get("/expiring")
def expiring_documents(
    business_id: int,
    days: int = 60,
    db: Session = Depends(get_db),
):
    _ensure_table(db)
    rows = db.execute(text("""
        SELECT DocumentID, Title, Category, FileName, ExpiryDate, Tags
        FROM BusinessDocument
        WHERE BusinessID = :bid
          AND ExpiryDate IS NOT NULL
          AND ExpiryDate > CAST(GETDATE() AS DATE)
          AND ExpiryDate <= DATEADD(day, :days, CAST(GETDATE() AS DATE))
        ORDER BY ExpiryDate ASC
    """), {"bid": business_id, "days": days}).fetchall()
    return [dict(r._mapping) for r in rows]
