# Changes — February 11, 2026

## 1. Fixed Firestore Chat History Not Storing Data

**Problem:** Chat messages were never saved to Firestore because `chat_history.py` was gated behind `RAG_AVAILABLE`, which requires the full RAG stack (pymssql, VertexAI, etc.). If any dependency was missing, chat history was silently disabled.

**Fix:** Split the single flag into two in `config.py`:
- `FIRESTORE_AVAILABLE` — only needs `google-cloud-firestore` (for chat history)
- `RAG_AVAILABLE` — needs the full stack (for livestock RAG)

Updated `chat_history.py` to use `FIRESTORE_AVAILABLE` instead of `RAG_AVAILABLE`.

**Files changed:** `config.py`, `chat_history.py`

---

## 2. Added Chat History Sidebar

**Problem:** Backend had thread management endpoints but the frontend never called them. Users couldn't see or revisit past conversations.

**What was added:**
- Collapsible left sidebar with thread list, "New Chat" button, and delete on hover
- Each thread shows: preview text, advisory type badge (color-coded), relative timestamp, status dot
- Clicking a past thread loads it as the active conversation
- Sidebar auto-collapses on screens narrower than 768px

**Files created:** `frontend/lib/types.ts`, `frontend/components/sidebar.tsx`, `frontend/components/chat-area.tsx`
**Files modified:** `frontend/components/advisor.tsx`

---

## 3. Added localStorage Persistence

**Problem:** If the backend is unavailable, past conversations are lost on page refresh.

**What was added:**
- `frontend/lib/storage.ts` saves threads and messages to localStorage on every chat update
- Thread list merges API threads with localStorage threads (API takes priority)
- Thread selection tries API first, falls back to localStorage
- Deleting a thread removes it from both sources

**Files created:** `frontend/lib/storage.ts`
**Files modified:** `frontend/components/advisor.tsx`

---

## 4. Enriched Chat History with Latency and Farm Context

**Problem:** Firestore chat documents only had basic message data. No performance metrics or farm context was persisted.

**What was added:**
- `latency_ms` recorded on every assistant message (quiz questions and final responses)
- On conversation completion, `farm_context` (location, crops, farm_size, assessment_summary) is saved to the Firestore document

**Files modified:** `api.py`, `chat_history.py`

---

## 5. Added Analytics API Endpoint

**What was added:**
- `GET /analytics?user_id=anonymous` endpoint
- `get_analytics()` method in `chat_history.py` aggregates across all Firestore threads:
  - Total and completed conversations, completion rate
  - Advisory type distribution (livestock, crops, weather, mixed)
  - Total messages and average messages per thread
  - Average response time (from latency_ms metadata)
  - Daily activity for the last 7 days

**Files modified:** `api.py`, `chat_history.py`

---

## 6. Created SQL Server to Firestore Embedding Sync

**Problem:** The RAG system reads from Firestore's `livestock_knowledge` collection but there was no automated way to populate it from SQL Server.

**What was created:**
- `sync_embeddings.py` — standalone script that:
  1. Reads all rows from all 6 allowed SQL Server tables
  2. Converts each row to text (e.g. `"Table: Speciesbreedlookuptable | BreedID: 5 | BreedName: Holstein"`)
  3. Generates embeddings via VertexAI `text-embedding-004`
  4. Upserts to Firestore `livestock_knowledge` collection
  5. Skips unchanged rows using content hashing
  6. No limit on embeddings — syncs everything
- Added `fetch_all(table)` method to `database.py`
- Added `SYNC_INTERVAL_HOURS` config (defaults to 24)

**Usage:**
```bash
python sync_embeddings.py --once    # one-time sync
python sync_embeddings.py           # continuous polling every 24h
```

**Files created:** `sync_embeddings.py`
**Files modified:** `database.py`, `config.py`
