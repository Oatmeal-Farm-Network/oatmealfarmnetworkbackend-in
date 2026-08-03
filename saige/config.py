# --- config.py --- (Centralized configuration)
import os
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# FEATURE AVAILABILITY FLAGS
# ============================================================================

# Firestore client (needed by chat history; also used by RAG)
try:
    from google.cloud import firestore
    FIRESTORE_AVAILABLE = True
except ImportError:
    print("[Warning] google-cloud-firestore not installed. Chat history will be disabled.")
    FIRESTORE_AVAILABLE = False

# Full RAG stack (needs firestore + pymssql + vector types + vertexai)
RAG_AVAILABLE = False
if FIRESTORE_AVAILABLE:
    try:
        import pymssql
        from google.cloud.firestore_v1.vector import Vector
        from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        RAG_AVAILABLE = True
    except ImportError:
        print("[Warning] RAG dependencies not installed. Livestock RAG will be disabled.")
else:
    print("[Warning] RAG disabled (requires Firestore).")

try:
    import requests
    WEATHER_AVAILABLE = True
except ImportError:
    print("[Warning] requests not installed. Weather service will be disabled.")
    WEATHER_AVAILABLE = False
    requests = None

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    print("[Warning] redis not installed. Redis features will be disabled.")
    REDIS_AVAILABLE = False
    redis = None

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

DB_CONFIG = {
    # Accept either DB_HOST (Saige/prod convention) or DB_SERVER (main-backend
    # convention) so precision-ag field lookups work under the unified local
    # backend, whose .env only defines DB_SERVER.
    "host": (os.getenv("DB_HOST") or os.getenv("DB_SERVER") or "").strip(),
    "port": int(os.getenv("DB_PORT", "1433").strip()) if os.getenv("DB_PORT") else 1433,
    "user": os.getenv("DB_USER", "").strip(),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": (os.getenv("DB_NAME") or os.getenv("DB_DATABASE") or "").strip(),
}

ALLOWED_TABLES = [
    "Speciesavailable", "Speciesbreedlookuptable", "Speciescategory",
    "Speciescolorlookuptable", "Speciespatternlookuptable", "Speciesregistrationtypelookuptable",
]

# ============================================================================
# GCP CONFIGURATION
# ============================================================================

GCP_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
GCP_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1").strip()
GCP_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

# ============================================================================
# RAG CONFIGURATION
# ============================================================================

EMBEDDING_MODEL = "text-embedding-004"
TOP_K_RESULTS = int(os.getenv("RAG_TOP_K", "3"))
RAG_PARALLEL_WORKERS = int(os.getenv("RAG_PARALLEL_WORKERS", "4"))
ADVISORY_MAX_ITERATIONS = int(os.getenv("ADVISORY_MAX_ITERATIONS", "2"))
COMMUNITY_LEARNINGS_ENABLED = os.getenv("COMMUNITY_LEARNINGS_ENABLED", "false").lower() == "true"
FIRESTORE_DATABASE = os.getenv("FIRESTORE_DATABASE", "charlie").strip()
CHAT_HISTORY_DATABASE = os.getenv("CHAT_HISTORY_DATABASE", "chat-history").strip()
LIVESTOCK_KNOWLEDGE_COLLECTION = "livestock_knowledge"
PLANT_KNOWLEDGE_COLLECTION = "plant_knowledge"
CROP_KNOWLEDGE_COLLECTION = "crop_knowledge"
SOIL_KNOWLEDGE_COLLECTION = "soil_knowledge"
FIELD_KNOWLEDGE_COLLECTION = "field_knowledge"
BAKASURA_DOCS_COLLECTION = "bakasura-docs"
NEWS_ARTICLES_COLLECTION = "news_articles"
HITL_CHARLIE_COLLECTION = "hitl-charlie"
SAIGE_LEARNINGS_COLLECTION = "saige_learnings"
# Backward-compatible alias
FIRESTORE_COLLECTION = LIVESTOCK_KNOWLEDGE_COLLECTION

SYNC_INTERVAL_HOURS = int(os.getenv("SYNC_INTERVAL_HOURS", "24"))

# ============================================================================
# ASSESSMENT CONFIGURATION
# ============================================================================

MAX_QUESTIONS = int(os.getenv("MAX_QUESTIONS", "0"))

# ============================================================================
# API CONFIGURATION
# ============================================================================

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
ALLOW_ALL_ORIGINS = os.getenv("ALLOW_ALL_ORIGINS", "false").lower() == "true"
# FRONTEND_URL supports a comma-separated list so multiple trusted origins
# (e.g. production domain + staging + Cloud Run preview URLs) can be
# configured without code changes. Used by api.py's CORS middleware.
ALLOWED_ORIGINS = [o.strip() for o in FRONTEND_URL.split(",") if o.strip()]

# ============================================================================
# CHAT HISTORY CONFIGURATION
# ============================================================================

THREADS_COLLECTION = "threads"

# ============================================================================
# REDIS CONFIGURATION (Environment-agnostic: works for local and GCP Memorystore)
# ============================================================================

REDIS_ENABLED = os.getenv("REDIS_ENABLED", "true").lower() == "true"
REDIS_URL = os.getenv("REDIS_URL", "").strip() or None
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None  # None if empty
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_SSL = os.getenv("REDIS_SSL", "false").lower() == "true"
_redis_ssl_cert_reqs_raw = os.getenv("REDIS_SSL_CERT_REQS", "required").strip().lower()
_valid_redis_ssl_cert_reqs = {"required", "optional", "none"}
if _redis_ssl_cert_reqs_raw not in _valid_redis_ssl_cert_reqs:
    print(f"[Config] [WARN] Invalid REDIS_SSL_CERT_REQS='{_redis_ssl_cert_reqs_raw}', defaulting to 'required'")
    REDIS_SSL_CERT_REQS = "required"
else:
    REDIS_SSL_CERT_REQS = _redis_ssl_cert_reqs_raw

# Keep Redis failures from adding multi-second latency when Redis is down.
REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS = float(
    os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS", "0.25")
)
REDIS_SOCKET_TIMEOUT_SECONDS = float(
    os.getenv("REDIS_SOCKET_TIMEOUT_SECONDS", "0.25")
)

# Bound assessment classifier latency on first-turn routing.
ASSESSMENT_CLASSIFICATION_TIMEOUT_SECONDS = float(
    os.getenv("ASSESSMENT_CLASSIFICATION_TIMEOUT_SECONDS", "3.0")
)
ASSESSMENT_USE_LLM_CLASSIFIER = os.getenv(
    "ASSESSMENT_USE_LLM_CLASSIFIER", "false"
).lower() == "true"

# Message buffer settings (Task 3 names)
SHORT_TERM_N = int(os.getenv("SHORT_TERM_N", os.getenv("MESSAGE_BUFFER_SIZE", "20")))  # Last N messages
SHORT_TERM_TTL_SECONDS = int(
    os.getenv("SHORT_TERM_TTL_SECONDS", os.getenv("MESSAGE_BUFFER_TTL_SECONDS", "86400"))
)  # 24h default

# Backward-compatible aliases
MESSAGE_BUFFER_SIZE = SHORT_TERM_N
MESSAGE_BUFFER_TTL_SECONDS = SHORT_TERM_TTL_SECONDS
REDIS_LAST_MESSAGES_KEY_TEMPLATE = "thread:{thread_id}:last_messages"
REDIS_MESSAGE_BUFFER_PREFIX = "langgraph:buffer:"  # Backward-compat constant 
REDIS_CHECKPOINT_PREFIX = "langgraph:checkpoint:"

# ============================================================================
# SAFETY CONTROLS (Task 5 — Rate Limits, Size Limits)
# ============================================================================

# Max characters allowed in a single user message (server-side hard cap).
MAX_MESSAGE_CHARS = int(os.getenv("MAX_MESSAGE_CHARS", "4000"))

# Max characters for content stored in the Redis message buffer.
# Messages longer than this are truncated before storage.
MAX_STORED_CONTENT_CHARS = int(os.getenv("MAX_STORED_CONTENT_CHARS", "2000"))

# Metadata whitelist — only these keys are kept when storing messages.
METADATA_ALLOWED_KEYS = {"type", "options", "advisory_type", "recommendations"}
# Max serialized size (bytes) for the metadata dict after filtering.
MAX_METADATA_BYTES = int(os.getenv("MAX_METADATA_BYTES", "2048"))

# Basic per-thread rate limiting (Redis INCR + EXPIRE).
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "20"))  # max requests ...
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))  # ... per window
REDIS_RATE_LIMIT_KEY_TEMPLATE = "thread:{thread_id}:rate_limit"


def redis_connection_mode() -> str:
    """Return redis configuration mode for logs/health responses."""
    return "url" if REDIS_URL else "host_port"


def get_redis_url() -> str:
    """
    Return canonical Redis URL used by backend components.
    REDIS_URL takes precedence over host/port/password/db/ssl fallback vars.
    """
    if REDIS_URL:
        return REDIS_URL

    scheme = "rediss" if REDIS_SSL else "redis"
    password_segment = f":{quote(REDIS_PASSWORD, safe='')}@" if REDIS_PASSWORD else ""
    return f"{scheme}://{password_segment}{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"


def get_redis_display_target() -> str:
    """Return non-sensitive Redis endpoint summary for startup logs."""
    if REDIS_URL:
        # Keep credentials out of logs while still showing configured endpoint shape.
        return "REDIS_URL (set)"
    return f"{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

# ============================================================================
# AUTHENTICATION
# ============================================================================

_JWT_SECRET_RAW = (os.getenv("SECRET_KEY") or "").strip()
if _JWT_SECRET_RAW:
    JWT_SECRET = _JWT_SECRET_RAW
elif GCP_PROJECT:
    JWT_SECRET = ""
else:
    JWT_SECRET = "change-me-in-production"
JWT_ALGORITHM = "HS256"

# ============================================================================
# PRODUCTION DETECTION
# ============================================================================

IS_PRODUCTION = bool(GCP_PROJECT)
LOG_FORMAT = "json" if IS_PRODUCTION else "text"

print(f"[Config] GCP Project: {GCP_PROJECT or 'Not set'}")
print(f"[Config] Firestore Available: {FIRESTORE_AVAILABLE}")
print(f"[Config] RAG Available: {RAG_AVAILABLE}")
print(f"[Config] Redis Available: {REDIS_AVAILABLE}")
print(f"[Config] Redis Enabled: {REDIS_ENABLED}")
if REDIS_ENABLED:
    print(f"[Config] Redis Mode: {redis_connection_mode()}")
    print(f"[Config] Redis Target: {get_redis_display_target()}")
    if REDIS_SSL or (REDIS_URL and get_redis_url().startswith("rediss://")):
        print(f"[Config] Redis TLS cert policy: {REDIS_SSL_CERT_REQS}")
print(f"[Config] Production Mode: {IS_PRODUCTION}")