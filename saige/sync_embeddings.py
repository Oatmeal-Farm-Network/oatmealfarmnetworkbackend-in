# --- sync_embeddings.py --- (SQL Server → Embeddings → Firestore sync)
"""
Polls SQL Server tables, converts rows to embeddings, and upserts them
into the Firestore `livestock_knowledge` collection for RAG vector search.

Usage:
    python sync_embeddings.py          # continuous polling (every 24h)
    python sync_embeddings.py --once   # single sync run then exit
"""
import sys
import time
import hashlib
import datetime
from typing import Dict, List, Any

from config import (
    ALLOWED_TABLES, FIRESTORE_COLLECTION,
    SYNC_INTERVAL_HOURS, RAG_AVAILABLE,
)

if not RAG_AVAILABLE:
    print("[Sync] RAG dependencies not available. Install pymssql, "
          "google-cloud-firestore, and langchain-google-vertexai.")
    sys.exit(1)

from google.cloud.firestore_v1.vector import Vector
from database import db
from rag import rag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def row_to_text(table_name: str, row: Dict[str, Any]) -> str:
    """Convert a SQL row dict to a human-readable text string."""
    parts = [f"Table: {table_name}"]
    for key, value in row.items():
        if value is not None:
            parts.append(f"{key}: {value}")
    return " | ".join(parts)


def content_hash(text: str) -> str:
    """SHA-256 hex digest of the text content (for change detection)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_doc_id(table_name: str, row: Dict[str, Any]) -> str:
    """Deterministic Firestore document ID from table + row content.

    Uses the first column value as the primary key hint. Falls back to
    a hash of the full row if no columns are available.
    """
    first_val = next(iter(row.values()), None) if row else None
    if first_val is not None:
        safe = str(first_val).replace("/", "_")
        return f"{table_name}_{safe}"
    return f"{table_name}_{content_hash(str(row))[:16]}"


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------

def sync_table(table_name: str) -> Dict[str, int]:
    """Sync all rows from one SQL Server table into Firestore.

    Returns counts: {"synced": N, "skipped": N, "errors": N}
    """
    collection = rag.collection
    if not collection:
        print(f"[Sync] Firestore collection unavailable, skipping {table_name}")
        return {"synced": 0, "skipped": 0, "errors": 0}

    rows = db.fetch_all(table_name)
    if not rows:
        print(f"[Sync] {table_name}: 0 rows found")
        return {"synced": 0, "skipped": 0, "errors": 0}

    synced = 0
    skipped = 0
    errors = 0
    batch = rag.firestore_db.batch()
    batch_count = 0

    for row in rows:
        try:
            text = row_to_text(table_name, row)
            text_hash = content_hash(text)
            doc_id = make_doc_id(table_name, row)
            doc_ref = collection.document(doc_id)

            # Check if document exists with same content hash
            existing = doc_ref.get()
            if existing.exists:
                existing_hash = (existing.to_dict() or {}).get("metadata", {}).get("content_hash")
                if existing_hash == text_hash:
                    skipped += 1
                    continue

            # Generate embedding
            embedding = rag._get_embedding(text)
            if not embedding:
                print(f"[Sync] Failed to generate embedding for {doc_id}")
                errors += 1
                continue

            now = datetime.datetime.utcnow().isoformat()
            batch.set(doc_ref, {
                "embedding": Vector(embedding),
                "content": text,
                "metadata": {
                    "table": table_name,
                    "source": "sql_server",
                    "content_hash": text_hash,
                    "synced_at": now,
                },
                "source_table": table_name,
                "synced_at": now,
            })
            synced += 1
            batch_count += 1

            # Firestore batch limit is 500 writes
            if batch_count >= 500:
                batch.commit()
                batch = rag.firestore_db.batch()
                batch_count = 0

        except Exception as e:
            print(f"[Sync] Error processing row in {table_name}: {e}")
            errors += 1

    # Commit remaining batch
    if batch_count > 0:
        batch.commit()

    return {"synced": synced, "skipped": skipped, "errors": errors}


def sync_all():
    """Sync all allowed tables from SQL Server to Firestore."""
    print(f"\n[Sync] Starting sync at {datetime.datetime.utcnow().isoformat()}")
    print(f"[Sync] Tables: {', '.join(ALLOWED_TABLES)}")

    total = {"synced": 0, "skipped": 0, "errors": 0}

    for table in ALLOWED_TABLES:
        print(f"[Sync] Processing {table}...")
        counts = sync_table(table)
        print(f"[Sync]   {table}: synced={counts['synced']}, "
              f"skipped={counts['skipped']}, errors={counts['errors']}")
        for key in total:
            total[key] += counts[key]

    print(f"[Sync] Done — total synced={total['synced']}, "
          f"skipped={total['skipped']}, errors={total['errors']}")
    return total


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    once = "--once" in sys.argv

    # Initialize RAG (ensures Firestore + embeddings are ready)
    rag._init_embeddings()
    if not rag.firestore_db:
        print("[Sync] Cannot connect to Firestore. Check GCP credentials.")
        sys.exit(1)
    if not db.connection:
        print("[Sync] Cannot connect to SQL Server. Check DB_* env vars.")
        sys.exit(1)

    print(f"[Sync] Connected to SQL Server and Firestore")
    print(f"[Sync] Mode: {'one-time' if once else f'polling every {SYNC_INTERVAL_HOURS}h'}")

    if once:
        sync_all()
    else:
        while True:
            sync_all()
            print(f"[Sync] Next sync in {SYNC_INTERVAL_HOURS} hours...")
            time.sleep(SYNC_INTERVAL_HOURS * 3600)


if __name__ == "__main__":
    main()
