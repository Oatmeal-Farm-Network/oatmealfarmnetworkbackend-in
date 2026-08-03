"""
Content translation utility for OFN backend.

Two-tier cache:
  L1 — Redis  (TTL 1 hour)   — avoids DB round-trips for hot content
  L2 — SQL Server ContentTranslations table (TTL 30 days) — avoids API calls

Usage:
    from routers.translation import translate_fields, translate_list

    # Translate a single dict's chosen fields
    row = translate_fields(row, ['Title', 'Description'], lang, db)

    # Translate every dict in a list
    rows = translate_list(rows, ['Title', 'Description'], lang, db)
"""

import hashlib
import json
import os
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# ──────────────────────────────────────────────────────────────────────────────
# Optional Redis — silently disabled if unavailable
# ──────────────────────────────────────────────────────────────────────────────
try:
    import redis as _redis_lib
    _REDIS_URL = os.getenv("REDIS_URL")
    _redis: Any = _redis_lib.from_url(_REDIS_URL, decode_responses=True) if _REDIS_URL else None
except Exception:
    _redis = None

_REDIS_TTL = 3600        # 1 hour
_DB_TTL_DAYS = 30


def _redis_get(key: str) -> str | None:
    if not _redis:
        return None
    try:
        return _redis.get(key)
    except Exception:
        return None


def _redis_set(key: str, value: str) -> None:
    if not _redis:
        return
    try:
        _redis.setex(key, _REDIS_TTL, value)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# SQL Server cache table bootstrap (idempotent, runs once per process)
# ──────────────────────────────────────────────────────────────────────────────
_table_ensured = False

_CREATE_TABLE_SQL = """
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ContentTranslations')
CREATE TABLE ContentTranslations (
    ContentHash   CHAR(64)      NOT NULL,
    Lang          VARCHAR(10)   NOT NULL,
    Translated    NVARCHAR(MAX) NOT NULL,
    CreatedAt     DATETIME      NOT NULL DEFAULT GETDATE(),
    ExpiresAt     DATETIME      NOT NULL,
    CONSTRAINT PK_ContentTranslations PRIMARY KEY (ContentHash, Lang)
)
"""


def _ensure_table(db: Session) -> None:
    global _table_ensured
    if _table_ensured:
        return
    try:
        db.execute(text(_CREATE_TABLE_SQL))
        db.commit()
        _table_ensured = True
    except Exception:
        db.rollback()


# ──────────────────────────────────────────────────────────────────────────────
# Core helpers
# ──────────────────────────────────────────────────────────────────────────────

def _hash(src_text: str) -> str:
    return hashlib.sha256(src_text.encode()).hexdigest()


def _db_get(content_hash: str, lang: str, db: Session) -> str | None:
    try:
        row = db.execute(
            text(
                "SELECT Translated FROM ContentTranslations "
                "WHERE ContentHash = :h AND Lang = :l AND ExpiresAt > GETDATE()"
            ),
            {"h": content_hash, "l": lang},
        ).first()
        return row[0] if row else None
    except Exception:
        return None


def _db_set(content_hash: str, lang: str, translated: str, db: Session) -> None:
    expires = datetime.utcnow() + timedelta(days=_DB_TTL_DAYS)
    try:
        db.execute(
            text("""
                MERGE ContentTranslations AS target
                USING (SELECT :h AS ContentHash, :l AS Lang) AS src
                ON (target.ContentHash = src.ContentHash AND target.Lang = src.Lang)
                WHEN MATCHED THEN
                    UPDATE SET Translated = :t, CreatedAt = GETDATE(), ExpiresAt = :e
                WHEN NOT MATCHED THEN
                    INSERT (ContentHash, Lang, Translated, CreatedAt, ExpiresAt)
                    VALUES (:h, :l, :t, GETDATE(), :e);
            """),
            {"h": content_hash, "l": lang, "t": translated, "e": expires},
        )
        db.commit()
    except Exception:
        db.rollback()


def _translate_via_api(text_to_translate: str, lang: str) -> str:
    """Call Google Cloud Translation API v3. Returns original text on any error."""
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project:
        return text_to_translate
    try:
        from google.cloud import translate_v3 as gc_translate
        client = gc_translate.TranslationServiceClient()
        parent = f"projects/{project}/locations/global"
        response = client.translate_text(
            request={
                "parent": parent,
                "contents": [text_to_translate],
                "mime_type": "text/plain",
                "source_language_code": "en",
                "target_language_code": lang,
            }
        )
        return response.translations[0].translated_text
    except Exception:
        return text_to_translate


def _get_translation(src: str, lang: str, db: Session) -> str:
    """Return translated string, pulling from cache layers before calling the API."""
    if not src or not src.strip():
        return src
    content_hash = _hash(f"{lang}:{src}")
    redis_key = f"ofn:tr:{content_hash}"

    cached = _redis_get(redis_key)
    if cached is not None:
        return cached

    db_cached = _db_get(content_hash, lang, db)
    if db_cached is not None:
        _redis_set(redis_key, db_cached)
        return db_cached

    translated = _translate_via_api(src, lang)
    _db_set(content_hash, lang, translated, db)
    _redis_set(redis_key, translated)
    return translated


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def translate_fields(
    record: dict,
    fields: list[str],
    lang: str,
    db: Session,
) -> dict:
    """
    Return a copy of `record` with `fields` translated to `lang`.
    Skips translation when lang == 'en' or field value is not a non-empty string.
    """
    if lang == "en" or not lang:
        return record
    _ensure_table(db)
    result = dict(record)
    for field in fields:
        val = result.get(field)
        if isinstance(val, str) and val.strip():
            result[field] = _get_translation(val, lang, db)
    return result


def translate_list(
    records: list[dict],
    fields: list[str],
    lang: str,
    db: Session,
) -> list[dict]:
    """Translate `fields` across every dict in `records`."""
    if lang == "en" or not lang:
        return records
    _ensure_table(db)
    return [translate_fields(r, fields, lang, db) for r in records]
