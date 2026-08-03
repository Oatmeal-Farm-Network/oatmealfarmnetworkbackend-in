# Saige — AI Agricultural Advisory Assistant

> Part of the [oatmealfarmnetworkbackend](https://github.com/Oatmeal-Farm-Network/oatmealfarmnetworkbackend) repo. For backend setup and how to run the full OFN stack locally, see the [backend README](../README.md) and [docs/SYSTEM.md](../docs/SYSTEM.md).

A conversational AI system that provides farm-specific advice across livestock, crops, weather, and mixed topics. Built with LangGraph, FastAPI, and Google Gemini AI, backed by Firestore RAG and Redis for short-term memory.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Graph & Node Design](#graph--node-design)
- [Data Models](#data-models)
- [RAG Collections](#rag-collections)
- [Chat History & Message Buffer](#chat-history--message-buffer)
- [API Reference](#api-reference)
- [API Usage Examples](#api-usage-examples)
- [Configuration](#configuration)
- [Prerequisites & Installation](#prerequisites--installation)
- [Running the Application](#running-the-application)
- [Workflow & Conversation Flow](#workflow--conversation-flow)
- [Advanced Routing Logic](#advanced-routing-logic)
- [Best Practices](#best-practices)
- [Performance Tuning](#performance-tuning)
- [Monitoring & Debugging](#monitoring--debugging)
- [Extending Saige](#extending-saige)
- [Testing](#testing)
- [Deployment](#deployment)
- [Setup](#setup)
- [Running Saige](#running-saige)
- [Technologies Used](#technologies-used)
- [Security Notes](#security-notes)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)

---

## Overview

Saige guides farmers through a structured diagnostic conversation:

1. **Assessment** — open-ended questions build a farm context (location, crops/animals, issues)
2. **Routing** — hybrid keyword + LLM classifier picks the right advisory node
3. **Advisory** — the selected node generates advice, optionally augmented by RAG knowledge and live weather data

Supported advisory domains:
- **Livestock** — breed recommendations, health, husbandry (RAG: `rag_livestock`)
- **Crops / Plants** — disease, soil, agronomy (RAG: `rag_plant`)
- **Weather** — current conditions and forecasts via Open-Meteo
- **Bakasura** — product/service knowledge base (RAG: `rag_bakasura`)
- **News** — agricultural news and market updates (RAG: `rag_news`)
- **Mixed** — any query spanning multiple domains (uses all RAG collections)

---

## Architecture

```
Frontend (React/Vite)
        │
        ▼
FastAPI REST API  (api.py)
        │
        ├── Redis  ── short-term message buffer (last N messages)
        │              rate limiter (per-thread INCR/EXPIRE)
        │              LangGraph checkpoints (RedisSaver)
        │
        ├── Firestore ── chat history persistence (chat-history DB)
        │                RAG knowledge collections (charlie DB)
        │
        └── LangGraph Workflow  (graph.py)
                │
                ├── assessment_node
                ├── routing_node
                ├── weather_advisory_node
                ├── livestock_advisory_node
                ├── crop_advisory_node
                ├── mixed_advisory_node
                ├── bakasura_advisory_node
                └── news_advisory_node
                        │
                        └── Google Gemini AI  (llm.py)
```

---

## Project Structure

```
saige/
├── api.py                  # FastAPI app, endpoints, rate limiting, middleware
├── graph.py                # LangGraph StateGraph construction and compilation
├── nodes.py                # All node functions, routing logic, advisory engine
├── models.py               # FarmState TypedDict and Pydantic models
├── config.py               # Centralized env-var configuration and feature flags
├── llm.py                  # Google Gemini LLM initialization
├── rag.py                  # Firestore vector search (livestock, plant, bakasura, news)
├── chat_history.py         # Firestore-backed conversation persistence
├── message_buffer.py       # Redis short-term message buffer (last N messages)
├── jwt_auth.py             # JWT Bearer token verification (FastAPI dependency)
├── redis_client.py         # RedisClientManager (connection pooling, health checks)
├── weather.py              # Open-Meteo weather service and LangChain tool wrapper
├── database.py             # Azure SQL (pymssql) query helpers
├── Data_Contract.py        # Pydantic data contracts for external integrations
├── main.py                 # Application entry point / server startup
├── sync_embeddings.py      # Script to sync embeddings into Firestore RAG collections
├── seed_firestore.py       # Script to seed initial knowledge data into Firestore
├── test_api_flow.py        # Integration tests for the full API flow
├── test_main.py            # Unit tests for core logic
└── test_redis.py           # Redis connectivity and buffer tests
```

---

## Graph & Node Design

### State: `FarmState`

| Field | Type | Purpose |
|---|---|---|
| `location` | `str` | Farmer's location (used for weather queries) |
| `farm_size` | `str` | Farm area |
| `crops` | `List[str]` | Crops or animals being raised |
| `current_issues` | `List[str]` | Reported problems or goals |
| `history` | `List[str]` | Conversation turns (`"User: ..."`, `"AI: ..."`) |
| `assessment_summary` | `str` | Compact summary produced at assessment completion |
| `advisory_type` | `str` | Final routed type: `weather`/`livestock`/`crops`/`mixed` |
| `diagnosis` | `str` | Final advisory text |
| `recommendations` | `List[str]` | Structured recommendations |
| `weather_conditions` | `dict` | Fetched weather data |
| `soil_info` | `dict` | Parsed soil test metrics |

### Graph Flow

```
START → assessment_node ──(complete?)──▶ routing_node
             ▲                                │
             │ (more questions)               ▼
             └──────────────────── weather / livestock / crop /
                                   mixed / bakasura / news → END
```

- `assessment_node` uses LLM-structured output (`AssessmentDecision`) to decide whether to ask another question or mark the assessment complete. It respects `MAX_QUESTIONS = 8`.
- `routing_node` classifies the `assessment_summary` using keyword scoring + LLM fallback (`QueryClassification`) to select one of six advisory routes.
- Each advisory node fetches relevant RAG context and/or weather data, then generates a final response via Gemini.

---

## RAG Collections

All RAG retrieval uses Firestore vector search with `text-embedding-004` embeddings (top-K = 10).

| Collection constant | Firestore collection | Used by | Purpose |
|---|---|---|---|
| `LIVESTOCK_KNOWLEDGE_COLLECTION` | `livestock_knowledge` | `livestock_advisory_node` | Breed info, health, husbandry |
| `PLANT_KNOWLEDGE_COLLECTION` | `plant_knowledge` | `crop_advisory_node` | Disease ID, soil, agronomy |
| `BAKASURA_DOCS_COLLECTION` | `bakasura-docs` | `bakasura_advisory_node` | Products, services, equipment |
| `NEWS_ARTICLES_COLLECTION` | `news_articles` | `news_advisory_node` | Market prices, agricultural news |

**Mixed Advisory:** `mixed_advisory_node` queries **all advisory collections** (`livestock_knowledge`, `plant_knowledge`, `bakasura-docs`) to synthesize advice across multiple domains. Example: "My cattle are losing weight and I think it's the new corn I planted" triggers mixed routing to search both livestock and crop knowledge bases.

RAG is enabled only when `FIRESTORE_AVAILABLE` and the full RAG dependency stack (pymssql, VertexAI embeddings) is installed. Both degrade gracefully when unavailable.

---

## Chat History & Message Buffer

### Firestore Chat History (`chat_history.py`)

Persists every conversation to the `chat-history` Firestore database under:

```
threads/{thread_id}               ← thread metadata (user_id, status, preview, …)
  └── messages/{message_id}       ← individual messages (role, content, ts, metadata)
```

Key operations:
- `save_message()` — upserts thread doc, writes message subcollection entry
- `mark_complete()` — sets `status: complete`, records `advisory_type` and `farm_context`
- `get_threads()` / `get_messages()` — paginated reads (cursor-based)
- `get_analytics()` — aggregate stats (completion rate, type distribution, response latency)
- `delete_thread()` — batch-deletes messages then the thread doc

### Redis Message Buffer (`message_buffer.py`)

Keeps the last `SHORT_TERM_N` (default 20) messages per thread in Redis for fast in-context history injection. TTL defaults to 24 hours (`SHORT_TERM_TTL_SECONDS`).

Key format: `thread:{thread_id}:last_messages`

---

## API Reference

Base URL: `http://localhost:8000`

### Authentication

All non-health endpoints require a valid JWT in the `Authorization` header:

```
Authorization: Bearer <token>
```

Tokens are issued by the Oatmeal Farm Network auth backend and verified against `SECRET_KEY` using HS256. The `sub` claim is used as the `user_id`. A missing, expired, or invalid token returns `401`.

### `POST /chat`

Main advisory endpoint. Requires JWT.

**Request:**
```json
{
  "user_input": "my cattle have been losing weight",
  "thread_id": "thread_abc123"
}
```

**Response — assessment question:**
```json
{
  "status": "requires_input",
  "ui": {
    "type": "quiz",
    "question": "What type of cattle are you raising?",
    "options": ["Beef cattle", "Dairy cattle", "Mixed herd", "Not sure"]
  }
}
```

**Response — advisory complete:**
```json
{
  "status": "complete",
  "advice": "Based on the symptoms described, your cattle may be experiencing …",
  "advisory_type": "livestock"
}
```

**Rate limiting:** 20 requests per 60-second window per `thread_id` (Redis-backed, fail-open).

### `GET /`

Health check. Returns API version and feature list.

### `GET /health`

Shallow liveness probe.

### `GET /health/redis`

Redis connectivity check. Returns latency and connection mode.
- `200 disabled` — Redis off by config
- `200 healthy` — reachable
- `503 unhealthy` — enabled but unreachable

### `GET /health/firestore`

Deep Firestore health check (write/read/delete cycle).

### `GET /ready`

Readiness probe. Checks graph, Redis, and Firestore. Returns `503` if any critical service is down.

### `GET /threads` *(if enabled)*

List conversation threads for the authenticated user (paginated). Requires JWT.

### `GET /threads/{thread_id}/messages` *(if enabled)*

Fetch messages for a thread (paginated). Requires JWT.

### `DELETE /threads/{thread_id}` *(if enabled)*

Delete a thread and all its messages. Requires JWT.

### `GET /analytics` *(if enabled)*

Aggregate conversation stats for the authenticated user. Requires JWT.

---

## Configuration

### Environment Variables

Create a `.env` file in the `saige/` directory (or project root):

```env
# --- Authentication ---
SECRET_KEY=your_jwt_secret_key               # HS256 signing secret (required)

# --- GCP / Gemini ---
GOOGLE_API_KEY=your_gemini_api_key           # Developer API (simplest)
GEMINI_MODEL=gemini-2.5-flash-lite

# --- OR Vertex AI ---
GOOGLE_CLOUD_PROJECT=your-gcp-project
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=./credentials/service-account.json

# --- Firestore ---
FIRESTORE_DATABASE=charlie                   # RAG knowledge database
CHAT_HISTORY_DATABASE=chat-history           # Conversation persistence database

# --- Redis ---
REDIS_ENABLED=true
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=                              # Leave blank for no auth
REDIS_DB=0
REDIS_SSL=false
# Or use a full URL (takes precedence):
# REDIS_URL=redis://localhost:6379/0

# --- Azure SQL (optional, for database.py) ---
DB_HOST=
DB_PORT=1433
DB_USER=
DB_PASSWORD=
DB_NAME=

# --- API ---
# Supports a comma-separated list for production origins.
FRONTEND_URL=http://localhost:5173
ALLOW_ALL_ORIGINS=false

# --- Safety controls ---
MAX_MESSAGE_CHARS=4000
MAX_STORED_CONTENT_CHARS=2000
RATE_LIMIT_ENABLED=true
RATE_LIMIT_MAX_REQUESTS=20
RATE_LIMIT_WINDOW_SECONDS=60

# --- Tuning ---
SHORT_TERM_N=20                              # Last N messages kept in Redis buffer
SHORT_TERM_TTL_SECONDS=86400                 # 24h default
SYNC_INTERVAL_HOURS=24
```

### Full Variable Reference

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | — | HS256 JWT signing secret (required for all protected endpoints) |
| `GOOGLE_API_KEY` | — | Gemini Developer API key |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` | LLM model (Developer API) |
| `GOOGLE_CLOUD_PROJECT` | — | GCP project (Vertex AI) |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | GCP region |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | Service account JSON path |
| `FIRESTORE_DATABASE` | `charlie` | RAG knowledge Firestore DB |
| `CHAT_HISTORY_DATABASE` | `chat-history` | Chat persistence Firestore DB |
| `REDIS_ENABLED` | `true` | Enable/disable Redis entirely |
| `REDIS_URL` | — | Full Redis URL (overrides host/port) |
| `REDIS_HOST` | `localhost` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_PASSWORD` | — | Redis auth password |
| `REDIS_SSL` | `false` | Enable TLS for Redis |
| `REDIS_SSL_CERT_REQS` | `required` | TLS cert policy (`required`/`optional`/`none`) |
| `SHORT_TERM_N` | `20` | Messages kept in Redis buffer per thread |
| `SHORT_TERM_TTL_SECONDS` | `86400` | Buffer TTL in seconds |
| `MAX_MESSAGE_CHARS` | `4000` | Max chars per user message |
| `RATE_LIMIT_MAX_REQUESTS` | `20` | Rate limit — max requests per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate limit — window size in seconds |
| `FRONTEND_URL` | `http://localhost:5173` | Allowed CORS origin |
| `ALLOW_ALL_ORIGINS` | `false` | Allow all CORS origins |

---

## Setup

### Prerequisites

- Python 3.11+
- Redis 7+ (or GCP Memorystore) — `docker compose up -d redis` in this directory
- Google Cloud project with Firestore and Vertex AI enabled (for RAG), or `GOOGLE_API_KEY` for the Developer API

### Install

Dependencies are installed from the **repo root** (`pip install -r requirements.txt`). Create a `.env` file in this directory (see [Configuration](#configuration) below).

---

## Running Saige

### Standalone

```bash
# From the saige/ directory
uvicorn api:app --reload --port 8000
```

API available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Mounted under the unified backend

When running `server_all.py` from the repo root, Saige is served at `/saige/*` (e.g. `http://localhost:8000/saige/health`). See [docs/SYSTEM.md](../docs/SYSTEM.md).

### Utility Scripts

```bash
# Seed initial knowledge data into Firestore
python seed_firestore.py

# Sync/refresh embeddings in RAG collections
python sync_embeddings.py
```

---

## Technologies Used

| Layer | Technology |
|---|---|
| LLM | Google Gemini 2.5 Flash Lite (via `langchain-google-genai` or Vertex AI) |
| Orchestration | LangGraph (StateGraph, interrupts, checkpointing) |
| API | FastAPI 0.100+ / Uvicorn |
| Vector search | Firestore vector search + `text-embedding-004` |
| Short-term memory | Redis (message buffer + LangGraph RedisSaver checkpoints) |
| Long-term persistence | Google Cloud Firestore |
| Weather data | Open-Meteo (via `requests`) |
| Database | Azure SQL / pymssql |
| Authentication | `python-jose` (JWT HS256 Bearer tokens) |
| Validation | Pydantic v2 |
| Frontend | React 19, Vite, Tailwind CSS ([frontend repo](https://github.com/Oatmeal-Farm-Network/oatmealfarmnetwork)) |

---

## Security Notes

**Never commit:**
- `.env` files (API keys, database credentials)
- `credentials/` directory (GCP service account JSON files)
- Any file containing secrets or tokens

The `.gitignore` excludes `.env`, `credentials/`, virtual environments, `__pycache__`, and `node_modules`.

**Production checklist:**
- Set a strong, randomly generated `SECRET_KEY` (minimum 32 characters)
- Set `ALLOW_ALL_ORIGINS=false` and configure `FRONTEND_URL` explicitly
- Enable `REDIS_SSL=true` with `REDIS_SSL_CERT_REQS=required` when using managed Redis
- Rotate API keys, JWT secrets, and service account credentials periodically
- Review `git status` before pushing to confirm no secrets are staged

---

---

## Data Models

### FarmState TypedDict

The core state object passed through the LangGraph workflow:

```python
class FarmState(TypedDict, total=False):
    location: str                      # Farm location (e.g., "Iowa, USA")
    farm_size: str                     # Farm area (e.g., "500 acres")
    crops: List[str]                   # Crops/animals (e.g., ["Corn", "Cattle"])
    current_issues: List[str]          # Problems reported (e.g., ["crop disease"])
    history: List[str]                 # Conversation history
    assessment_summary: str            # Assessment completed summary
    advisory_type: str                 # Final routed type (livestock/crops/weather/mixed/bakasura/news)
    diagnosis: str                     # Final advisory response
    recommendations: List[str]         # Structured recommendations
    weather_conditions: dict           # Fetched weather data
    soil_info: dict                    # Soil test metrics
    user_id: str                       # Authenticated user ID
    thread_id: str                     # Conversation thread identifier
```

### Pydantic Models

Key request/response models (`models.py`):

```python
class ChatRequest(BaseModel):
    user_input: str                    # User's message or answer
    thread_id: str                     # Conversation thread identifier
    
class ChatResponse(BaseModel):
    status: Literal["requires_input", "complete", "error"]
    ui: Optional[dict]                 # Quiz/UI state if requires_input
    advice: Optional[str]              # Final advice if complete
    advisory_type: Optional[str]       # Type of advisory (livestock/crops/etc.)
    recommendations: Optional[List[str]]
    metadata: Optional[dict]           # Additional context
    
class AssessmentDecision(BaseModel):
    next_question: Optional[str]       # Question to ask, or None if complete
    summary: Optional[str]             # Assessment summary if complete
    
class QueryClassification(BaseModel):
    advisory_type: str                 # weather/livestock/crops/mixed/bakasura/news
    confidence: float                  # 0.0-1.0 confidence score
    keywords_matched: List[str]        # Keywords that triggered classification
```

---

## API Usage Examples

### Complete Conversation Flow

**1. Start a new conversation:**

```bash
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "I have cattle and they are losing weight. I am concerned about their health.",
    "thread_id": "user_123_thread_001"
  }'
```

**Response (Assessment question):**
```json
{
  "status": "requires_input",
  "ui": {
    "type": "quiz",
    "question": "How long have you noticed this weight loss?",
    "options": ["Less than 1 week", "1-2 weeks", "2-4 weeks", "More than a month"]
  }
}
```

**2. Answer assessment questions (repeat until status = "complete"):**

```bash
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "More than a month",
    "thread_id": "user_123_thread_001"
  }'
```

**Response (More questions or completion):**
```json
{
  "status": "requires_input",
  "ui": {
    "type": "quiz",
    "question": "Have you noticed any changes in their appetite or water intake?",
    "options": ["Decreased appetite", "Increased appetite", "No change", "Not sure"]
  }
}
```

**3. Final advisory response:**

After 2-8 assessment questions, the system provides advisory:

```json
{
  "status": "complete",
  "advice": "Based on the symptoms you described (progressive weight loss over a month in cattle with unchanged appetite), your cattle may be experiencing: 1) Internal parasites, 2) Nutritional deficiency, or 3) Wasting disease. I recommend:\n\n1. Have a veterinarian perform a fecal exam for parasites\n2. Check your mineral supplementation program\n3. Ensure adequate forage quality and quantity\n4. Consider isolating affected animals for observation\n\nImmediate action recommended given the duration and progression.",
  "advisory_type": "livestock",
  "recommendations": [
    "Get veterinary fecal exam",
    "Review mineral supplement program",
    "Audit forage quality",
    "Isolate affected animals",
    "Monitor for additional symptoms"
  ],
  "metadata": {
    "rag_documents_used": 3,
    "response_latency_ms": 1240,
    "model": "gemini-2.5-flash-lite"
  }
}
```

### Retrieving Chat History

```bash
# Get all threads for authenticated user
curl -X GET http://localhost:8000/threads?limit=10 \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"

# Response
{
  "threads": [
    {
      "thread_id": "user_123_thread_001",
      "user_id": "user_123",
      "created_at": "2025-06-17T10:30:00Z",
      "updated_at": "2025-06-17T11:45:00Z",
      "status": "complete",
      "advisory_type": "livestock",
      "preview": "My cattle have been losing weight...",
      "message_count": 7
    }
  ],
  "next_cursor": "next_page_token"
}

# Get messages in a thread
curl -X GET http://localhost:8000/threads/user_123_thread_001/messages \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"

# Response
{
  "messages": [
    {
      "id": "msg_001",
      "role": "user",
      "content": "I have cattle and they are losing weight...",
      "timestamp": "2025-06-17T10:30:00Z"
    },
    {
      "id": "msg_002",
      "role": "assistant",
      "content": "How long have you noticed this weight loss?",
      "metadata": {"type": "assessment_question"}
    }
    // ... more messages
  ]
}
```

### Analytics

```bash
curl -X GET http://localhost:8000/analytics \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"

# Response
{
  "total_conversations": 42,
  "completed_conversations": 38,
  "completion_rate": 0.905,
  "average_messages_per_conversation": 5.2,
  "advisory_type_distribution": {
    "livestock": 0.45,
    "crops": 0.35,
    "mixed": 0.15,
    "weather": 0.05
  },
  "average_response_latency_ms": 1180,
  "most_common_issues": [
    "disease identification",
    "yield improvement",
    "pest management"
  ]
}
```

---

## Workflow & Conversation Flow

### Assessment Phase

The `assessment_node` conducts a structured interview:

1. **Initial Assessment** — User describes their issue
2. **Iterative Questioning** — LLM determines if more context is needed
3. **Max Questions** — Stops after 8 questions to prevent long conversations
4. **Summary Generation** — Creates a concise summary of the farm context

**Assessment Decision Logic:**
```python
# From nodes.py - AssessmentDecision structure
{
    "next_question": "What type of cattle are you raising?",  # or None
    "summary": "Farm context: 500-acre dairy operation in Iowa..."  # or None
}
```

When `next_question` is None and `summary` is populated, assessment is complete.

### Routing Phase

The `routing_node` classifies the assessment summary into one of six advisory types:

| Type | Keywords | RAG Collections | External Data |
|---|---|---|---|
| **livestock** | cattle, cow, pig, poultry, animal health | `livestock_knowledge` | — |
| **crops** | corn, wheat, soy, disease, pest, yield | `plant_knowledge` | — |
| **weather** | frost, rain, drought, forecast, season | — | Open-Meteo |
| **mixed** | multiple domains mentioned | All advisory collections | — |
| **bakasura** | products, services, suppliers | `bakasura-docs` | — |
| **news** | market, prices, trends, news | `news_articles` | — |

**Classification Method:**
1. Keyword scoring (fast, fail-open)
2. LLM fallback if keywords are ambiguous (structured output)
3. Confidence threshold to prefer safe defaults

### Advisory Phase

Each advisory node:

1. **Fetches RAG Context** — Vector search for relevant documents
2. **Augments Data** — Adds weather if livestock/crop advice
3. **Generates Response** — LLM creates personalized advice via Gemini
4. **Structures Output** — Breaks into recommendations + explanatory text

---

## Advanced Routing Logic

### Keyword Scoring

From `nodes.py`, the router maintains a keyword dictionary:

```python
ADVISORY_KEYWORDS = {
    "livestock": ["cattle", "cow", "pig", "poultry", "herd", "feed", "vaccine", ...],
    "crops": ["corn", "wheat", "soy", "disease", "pest", "yield", "nitrogen", ...],
    "weather": ["frost", "rain", "drought", "forecast", "temperature", ...],
    "bakasura": ["product", "supplier", "service", "tools", "equipment", ...],
    "news": ["market", "price", "trend", "news", "export", "import", ...],
}

# Scoring example
user_summary = "My corn crop has fungal disease. I need to know treatment options."

scores = {
    "crops": 2,          # "corn" (1) + "disease" (1)
    "bakasura": 0,
    "livestock": 0,
    "weather": 0,
    "news": 0,
}
# Result: "crops" wins
```

### LLM Fallback

If keyword scores are tied or ambiguous, the router calls Gemini:

```python
query_classification_prompt = """
Classify this farm query into ONE category:
- livestock: animal health, breeding, nutrition, husbandry
- crops: plant disease, pest management, soil, yields, crop varieties
- weather: current conditions, forecasting, seasonal planning
- mixed: multiple categories equally relevant
- bakasura: products, services, suppliers
- news: market prices, agricultural trends, industry news

Query: {assessment_summary}

Return JSON with 'advisory_type' and 'confidence' (0.0-1.0).
"""
```

---

## Best Practices

### 1. JWT Token Management

```python
# Token generation (from auth backend)
from datetime import datetime, timedelta
from jose import jwt

payload = {
    "sub": "user_123",           # user_id
    "exp": datetime.utcnow() + timedelta(hours=24),
    "iat": datetime.utcnow(),
}
token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

# Every request must include
headers = {
    "Authorization": f"Bearer {token}"
}
```

### 2. Thread ID Strategy

Use a consistent, non-guessable thread ID per conversation:

```python
# Good: UUIDs or domain-specific IDs
thread_id = f"user_123_session_{uuid.uuid4()}"
thread_id = f"user_123_topic_livestock_{date_today}"

# Avoid: Sequential or predictable IDs
thread_id = f"user_123_thread_001"  # Predictable
```

### 3. Handling Assessment Loops

The frontend should loop on `status: "requires_input"`:

```javascript
// Frontend pseudo-code
while (response.status === "requires_input") {
    userAnswer = await getUserInput(response.ui.question, response.ui.options);
    response = await fetch("/chat", {
        headers: { Authorization: `Bearer ${token}` },
        body: JSON.stringify({
            user_input: userAnswer,
            thread_id: threadId,
        }),
    }).then(r => r.json());
}
// Now response.status === "complete"
showAdvice(response.advice, response.recommendations);
```

### 4. Error Handling

```python
# Always check for errors
try:
    response = await client.post(
        "http://localhost:8000/chat",
        json={"user_input": "...", "thread_id": "..."},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,  # LLM calls can take 5-20 seconds
    )
    response.raise_for_status()
    data = response.json()
    
    if data.get("status") == "error":
        print(f"Saige error: {data.get('error_message')}")
    else:
        # Process data.status, data.advice, etc.
except httpx.HTTPError as e:
    # Handle network/auth errors
    if e.response.status_code == 401:
        # Token expired or invalid
        refresh_token()
    elif e.response.status_code == 429:
        # Rate limited
        wait_before_retry()
```

### 5. RAG Optimization

For best RAG results:

- **Clear assessment summary** — Saige extracts keywords; provide context
- **Specific domain queries** — "My wheat has brown spots" gets better results than "My crops aren't growing"
- **Location information** — Helps with weather and region-specific advice

---

## Performance Tuning

### 1. LLM Model Selection

| Model | Speed | Quality | Cost | Use Case |
|---|---|---|---|---|
| **gemini-2.5-flash-lite** | ⚡⚡⚡ | ✓✓ | $ | Default; fast advisory |
| **gemini-2.0-flash** | ⚡⚡ | ✓✓✓ | $$ | Better reasoning |
| **gemini-1.5-pro** | ⚡ | ✓✓✓✓ | $$$ | Complex analysis |

Change in `config.py`:
```python
GEMINI_MODEL = "gemini-2.5-flash-lite"  # Fast (default)
# or
GEMINI_MODEL = "gemini-2.0-flash"       # Slower but higher quality
```

### 2. RAG Optimization

Tune in `config.py`:

```python
RAG_TOP_K = 10          # Number of documents to retrieve (default 10)
                        # Lower = faster, higher = more context

SHORT_TERM_N = 20       # Messages kept in Redis (default 20)
                        # Higher = more context, more memory

# In rag.py, vector search parameters
docs = vector_search(
    query_embedding,
    collection="livestock_knowledge",
    top_k=10,           # Adjust here too
    distance_threshold=0.6,  # Min similarity score
)
```

### 3. Redis Configuration

For production, use connection pooling:

```python
# redis_client.py
REDIS_POOL_SIZE = 20       # Concurrent connections
REDIS_MAX_IDLE_TIME = 300  # Close idle connections after 5 min

# Health check optimization
REDIS_HEALTH_CHECK_INTERVAL = 60  # Check every 60 sec
```

### 4. Firestore Indexes

Create composite indexes for common queries:

```
Collection: chat-history
Indexes:
  - user_id (Ascending)
  - status (Ascending)
  - created_at (Descending)
  
  - user_id (Ascending) + created_at (Descending)
  - user_id (Ascending) + status (Ascending)
```

---

## Monitoring & Debugging

### 1. Logging

Enable structured logging in `api.py`:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("saige")

# In endpoints
@app.post("/chat")
async def chat(req: ChatRequest, user_id: str = Depends(verify_jwt)):
    logger.info(f"Chat request from user={user_id}, thread={req.thread_id}")
    
    try:
        response = await graph.ainvoke(...)
        logger.info(f"Chat completed. type={response['advisory_type']}")
        return response
    except Exception as e:
        logger.error(f"Chat failed: {e}", exc_info=True)
        raise
```

### 2. Performance Metrics

Track latency per node:

```python
import time

async def assessment_node(state: FarmState) -> FarmState:
    start = time.time()
    
    # ... assessment logic ...
    
    duration = time.time() - start
    logger.info(f"assessment_node took {duration:.2f}s")
    
    return state
```

### 3. Redis Health Monitoring

```bash
# Check Redis connection
redis-cli ping  # Should respond: PONG

# Monitor message buffer size
redis-cli --stat

# Check specific thread buffer
redis-cli LLEN "thread:user_123_thread_001:last_messages"

# Check rate limiter counter
redis-cli GET "thread:user_123_thread_001:rate_limit"
```

### 4. Firestore Query Monitoring

Use GCP Console or query logs:

```python
# Example: Check chat history
from google.cloud import firestore

db = firestore.Client(database="chat-history")
threads = db.collection("threads").where("user_id", "==", "user_123").stream()

for thread in threads:
    print(f"Thread {thread.id}: {thread.get('status')}")
    
    messages = thread.reference.collection("messages").stream()
    print(f"  Messages: {len(list(messages))}")
```

---

## Extending Saige

### 1. Adding a New Advisory Node

**Step 1: Create node function in `nodes.py`:**

```python
async def my_advisory_node(state: FarmState) -> FarmState:
    """Custom advisory for my domain."""
    
    # Fetch RAG context
    rag_context = await rag_search(
        state["assessment_summary"],
        collection="my_knowledge_collection"
    )
    
    # Fetch external data (optional)
    external_data = await fetch_my_external_api(state["location"])
    
    # Generate response
    prompt = f"""
    You are an expert in my domain. Provide advice based on:
    - Farm context: {state['assessment_summary']}
    - Knowledge base: {rag_context}
    - External data: {external_data}
    
    Provide structured advice with clear recommendations.
    """
    
    response = await llm.generate(prompt)
    
    state["diagnosis"] = response["advice"]
    state["recommendations"] = response["recommendations"]
    state["advisory_type"] = "my_domain"
    
    return state

# Step 2: Register in graph (graph.py)
graph.add_node("my_advisory_node", my_advisory_node)
graph.add_edge("routing_node", "my_advisory_node")
graph.add_edge("my_advisory_node", END)

# Step 3: Update routing logic (nodes.py)
# Add to ADVISORY_KEYWORDS and classify logic
```

### 2. Custom RAG Collection

```python
# In rag.py

class CustomRAG:
    def __init__(self, db_name: str):
        self.db = firestore.Client(database=db_name)
        self.collection = "my_custom_docs"
    
    async def search(self, query: str, top_k: int = 10):
        # Generate embedding
        embedding = await generate_embedding(query)
        
        # Vector search
        docs = self.db.collection(self.collection).where(
            "vector", "array-contains", embedding
        ).limit(top_k).stream()
        
        return [doc.to_dict() for doc in docs]

# Usage
custom_rag = CustomRAG("my_database")
results = await custom_rag.search("my query")
```

### 3. Custom LLM Provider

Replace Gemini with another provider in `llm.py`:

```python
# Example: OpenAI instead of Gemini
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def generate_response(prompt: str) -> str:
    response = await client.chat.completions.create(
        model="gpt-4-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=500,
    )
    return response.choices[0].message.content
```

---

## Testing

### Unit Tests

```python
# test_main.py
import pytest
from fastapi.testclient import TestClient
from api import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_chat_requires_auth():
    response = client.post("/chat", json={
        "user_input": "test",
        "thread_id": "test_123"
    })
    assert response.status_code == 401  # Unauthorized
```

### Integration Tests

```python
# test_api_flow.py
@pytest.mark.asyncio
async def test_full_conversation_flow():
    """Test complete assessment → routing → advisory flow."""
    
    token = generate_test_jwt("test_user")
    headers = {"Authorization": f"Bearer {token}"}
    
    # Start conversation
    resp1 = client.post("/chat", 
        json={"user_input": "My cattle are sick", "thread_id": "test_123"},
        headers=headers
    )
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "requires_input"
    
    # Answer question
    resp2 = client.post("/chat",
        json={"user_input": "Dairy cattle", "thread_id": "test_123"},
        headers=headers
    )
    assert resp2.status_code == 200
    
    # Continue until complete...
    while resp2.json()["status"] == "requires_input":
        resp2 = client.post("/chat", ...)
    
    # Final response
    final = resp2.json()
    assert final["status"] == "complete"
    assert "advice" in final
    assert final["advisory_type"] in ["livestock", "crops", "weather", "mixed"]
```

### Run Tests

```bash
# All tests
pytest

# Specific file
pytest test_api_flow.py -v

# With coverage
pytest --cov=saige --cov-report=html
```

---

## Deployment

### Production deployment notes

Saige is now set up for production-style deployments with the following expectations:

- The container must bind to the runtime port provided by the platform. On Cloud Run this is `PORT`; the service should not hardcode `8000` when deployed there.
- `FRONTEND_URL` should be set to the real production origin(s) for CORS. It supports a comma-separated list when multiple origins are needed.
- `ALLOW_ALL_ORIGINS` should normally stay `false` in production.
- `SECRET_KEY` should be injected via environment variables or a platform secret store; do not hardcode it into source-controlled deployment scripts.
- The weather path now defaults to a free, keyless fallback path for U.S. locations (NWS/Open-Meteo), so no paid weather API key is required for the common case.

### Docker

```bash
# Build image
docker build -t saige:latest .

# Run locally
docker run -p 8000:8000 \
  -e SECRET_KEY="your_key" \
  -e GOOGLE_API_KEY="your_api_key" \
  saige:latest

# Run on Google Cloud Run
gcloud run deploy saige \
  --source . \
  --platform managed \
  --region us-central1 \
  --set-env-vars SECRET_KEY="...",GOOGLE_API_KEY="...",FRONTEND_URL="https://your-domain.com",ALLOW_ALL_ORIGINS=false
```

### Kubernetes

```yaml
# saige-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: saige
spec:
  replicas: 3
  selector:
    matchLabels:
      app: saige
  template:
    metadata:
      labels:
        app: saige
    spec:
      containers:
      - name: saige
        image: gcr.io/my-project/saige:latest
        ports:
        - containerPort: 8000
        env:
        - name: SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: saige-secrets
              key: secret-key
        - name: REDIS_URL
          value: "redis://redis-service:6379"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
```

---

## Troubleshooting

| Error | Solution |
|---|---|
| `401 Invalid or expired token` | Ensure a valid JWT is sent in the `Authorization: Bearer <token>` header |
| `500 JWT_SECRET is not configured` | Set `SECRET_KEY` in your `.env` file |
| `GOOGLE_API_KEY not set` | Create `.env` with `GOOGLE_API_KEY=...` |
| `RAG disabled (requires Firestore)` | Install `google-cloud-firestore` and set `GOOGLE_CLOUD_PROJECT` |
| `Redis checkpoint indexes missing` | API falls back to `MemorySaver` automatically; restart Redis and re-run |
| `401 UNAUTHENTICATED` | Verify API key or service account credentials file path |
| CORS errors | Ensure backend is on port 8000 and `FRONTEND_URL` matches |
| `No such index` in Redis logs | Redis checkpoint index not initialized; the fallback handler in `api.py` covers this automatically |
| Slow response times (>5s) | Check LLM model (switch to flash-lite), reduce RAG_TOP_K, verify Redis/Firestore latency |
| `Connection refused` on Redis | Verify Redis is running: `redis-cli ping` should return `PONG` |
| Firestore quota exceeded | Check daily write quota in GCP console; increase quota if needed |
| Assessment never completes | Check `MAX_QUESTIONS` (default 8); LLM may keep asking; try clearer initial input |

---

## FAQ

### Q: How long does a typical conversation take?

**A:** 
- Assessment phase: 2-3 seconds per question (LLM + storage)
- Total conversation (5-8 questions): 10-25 seconds
- Advisory generation: 2-5 seconds
- **Total: 15-35 seconds** for a complete flow

Bottlenecks: LLM latency (50-70%), RAG search (10-20%), Redis/Firestore writes (10-20%)

### Q: Can I use Saige without Redis?

**A:** Yes, but with limitations:
- Set `REDIS_ENABLED=false` in `.env`
- Message buffer disabled (in-memory only per request)
- No rate limiting (relies on FastAPI defaults)
- No LangGraph checkpoint persistence (falls back to `MemorySaver`)

Recommended: At least use Redis for better production experience.

### Q: Can I customize the assessment questions?

**A:** Currently hardcoded in `assessment_node`. To customize:

1. Modify the system prompt in `nodes.py`
2. Or implement a custom question database in Firestore
3. Update `assessment_node` to fetch questions from DB

Example:
```python
async def assessment_node(state):
    questions = await fetch_assessment_questions(state["advisory_type"])
    # Use questions instead of LLM-generated ones
```

### Q: How do I add a new language?

**A:** Saige uses LLM for content generation, which supports 100+ languages. To add:

1. Set `GEMINI_MODEL` to one with multilingual support
2. Add language to frontend locale files
3. Update system prompts to accept language preference:

```python
prompt = f"""
Respond in {user_language}. [rest of prompt]
"""
```

### Q: What's the difference between mixed_advisory_node and other nodes?

**A:** 
- **Dedicated nodes** (livestock, crops, weather): Search ONE RAG collection + specialized prompt
- **mixed_advisory_node**: Searches ALL advisory collections + synthesizes across domains

Example: "My cattle are losing weight and I think it's the new corn I planted" → mixed node searches both livestock_knowledge and plant_knowledge

### Q: How do I monitor Saige in production?

**A:**
1. **Health checks**: `/health`, `/health/redis`, `/health/firestore`, `/ready`
2. **Metrics endpoint**: `/analytics` (aggregated stats)
3. **Logging**: Enable in `api.py`, ship logs to GCP Cloud Logging
4. **Tracing**: Add OpenTelemetry instrumentation
5. **Alerts**: Set up alerts on `/ready` (if returns 503, something is down)

```python
# Add to api.py
import logging
from pythonopentelemetry import ...

logging.basicConfig(level=logging.INFO)
# Ship logs to Google Cloud Logging via handler
```

### Q: Can I A/B test different routing strategies?

**A:** Yes, implement feature flags:

```python
# config.py
USE_LLM_ROUTING = os.getenv("USE_LLM_ROUTING", "true").lower() == "true"

# nodes.py
async def routing_node(state):
    if USE_LLM_ROUTING:
        return await llm_based_routing(state)
    else:
        return await keyword_based_routing(state)
```

Then toggle `USE_LLM_ROUTING=false` to compare strategies.

---

## Additional Resources

- **LangGraph Docs**: https://langchain-ai.github.io/langgraph/
- **FastAPI Docs**: https://fastapi.tiangolo.com/
- **Google Gemini API**: https://ai.google.dev/
- **Firestore Docs**: https://cloud.google.com/firestore/docs
- **Redis Docs**: https://redis.io/docs/
- **Open-Meteo Weather API**: https://open-meteo.com/
