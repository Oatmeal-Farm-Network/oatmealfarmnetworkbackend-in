# --- rag.py --- (RAG system using Firestore Vector Search)
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import (
    GCP_PROJECT, GCP_LOCATION, GCP_CREDENTIALS,
    EMBEDDING_MODEL, TOP_K_RESULTS, RAG_PARALLEL_WORKERS,
    FIRESTORE_DATABASE,
    LIVESTOCK_KNOWLEDGE_COLLECTION,
    PLANT_KNOWLEDGE_COLLECTION,
    CROP_KNOWLEDGE_COLLECTION,
    SOIL_KNOWLEDGE_COLLECTION,
    FIELD_KNOWLEDGE_COLLECTION,
    BAKASURA_DOCS_COLLECTION,
    NEWS_ARTICLES_COLLECTION,
    HITL_CHARLIE_COLLECTION,
    RAG_AVAILABLE
)

if RAG_AVAILABLE:
    from google.cloud import firestore
    from google.cloud.firestore_v1.vector import Vector
    from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

_SHARED_EMBEDDINGS = None


def _get_shared_embeddings():
    """Single shared embeddings client for all RAG collections."""
    global _SHARED_EMBEDDINGS
    if _SHARED_EMBEDDINGS is None and GCP_PROJECT and RAG_AVAILABLE:
        try:
            _SHARED_EMBEDDINGS = GoogleGenerativeAIEmbeddings(
                model=EMBEDDING_MODEL,
                project=GCP_PROJECT,
                location=GCP_LOCATION,
            )
            print(f"[RAG] Shared embeddings initialized ({EMBEDDING_MODEL})")
        except Exception as e:
            print(f"[RAG] Shared embeddings init failed: {e}")
    return _SHARED_EMBEDDINGS


def embed_query_text(text: str) -> List[float]:
    """Embed a query once; reuse across all collection searches."""
    embeddings = _get_shared_embeddings()
    if not embeddings or not text:
        return []
    try:
        return embeddings.embed_query(text)
    except Exception as e:
        print(f"[RAG] embed_query failed: {e}")
        return []

class RAGSystem:
    """RAG system using Firestore Vector Search for a single collection."""

    def __init__(self, collection_name: str, label: str = ""):
        self._collection_name = collection_name
        self._label = label or collection_name
        self._db = None
        self._initialized = False
        self._embeddings = None

    def _init_embeddings(self):
        """Initialize embeddings model (uses shared singleton)."""
        if self._embeddings is None:
            self._embeddings = _get_shared_embeddings()

    def _get_embedding(self, text: str) -> List[float]:
        """Generate embedding for text."""
        return embed_query_text(text)

    def search_with_embedding(
        self, query_embedding: List[float], n_results: int = TOP_K_RESULTS
    ) -> List[Dict[str, Any]]:
        """Search using a precomputed embedding vector."""
        if not self._initialized:
            self.initialize()
        if not self.collection or not query_embedding:
            return []
        try:
            vector_query = self.collection.find_nearest(
                vector_field="embedding",
                query_vector=Vector(query_embedding),
                distance_measure=DistanceMeasure.COSINE,
                limit=n_results,
            )
            results = vector_query.get()
            return [
                {
                    "content": doc.to_dict().get("content", ""),
                    "metadata": doc.to_dict().get("metadata", {}),
                }
                for doc in results
            ]
        except Exception as e:
            print(f"[RAG:{self._label}] Search error: {e}")
            return []

    def get_context_with_embedding(self, query_embedding: List[float]) -> str:
        """Get formatted context using a precomputed embedding."""
        results = self.search_with_embedding(query_embedding)
        if not results:
            return ""
        context_parts = [f"Relevant {self._label} information from database:\n"]
        for i, result in enumerate(results, 1):
            context_parts.append(f"{i}. {result['content']}")
        return "\n".join(context_parts)

    @property
    def firestore_db(self):
        """Lazy initialization of Firestore client."""
        if self._db is None and GCP_PROJECT and RAG_AVAILABLE:
            credentials = None
            if GCP_CREDENTIALS:
                try:
                    from google.oauth2 import service_account
                    credentials = service_account.Credentials.from_service_account_file(
                        GCP_CREDENTIALS,
                        scopes=["https://www.googleapis.com/auth/cloud-platform"],
                    )
                except Exception as e:
                    print(f"[RAG:{self._label}] Credentials load failed: {e}")
            try:
                if credentials:
                    self._db = firestore.Client(
                        project=GCP_PROJECT,
                        database=FIRESTORE_DATABASE,
                        credentials=credentials,
                    )
                else:
                    self._db = firestore.Client(
                        project=GCP_PROJECT, database=FIRESTORE_DATABASE
                    )
                print(f"[RAG:{self._label}] Connected to Firestore ({FIRESTORE_DATABASE})")
            except Exception as e:
                print(f"[RAG:{self._label}] Firestore connection failed: {e}")
        return self._db

    @property
    def collection(self):
        """Get the Firestore collection."""
        if self.firestore_db:
            return self.firestore_db.collection(self._collection_name)
        return None

    def initialize(self):
        """Initialize the RAG system."""
        if not self._initialized and self.collection:
            try:
                docs = list(self.collection.limit(1).get())
                self._initialized = len(docs) > 0
                if self._initialized:
                    print(f"[RAG:{self._label}] Index ready")
            except Exception as e:
                print(f"[RAG:{self._label}] Init error: {e}")
        return self._initialized

    def search(self, query: str, n_results: int = TOP_K_RESULTS) -> List[Dict[str, Any]]:
        """Search for relevant documents."""
        embedding = embed_query_text(query)
        return self.search_with_embedding(embedding, n_results=n_results)

    def get_context_for_query(self, query: str) -> str:
        """Get formatted context string for LLM."""
        embedding = embed_query_text(query)
        return self.get_context_with_embedding(embedding)


def gather_rag_context(rag_systems: List["RAGSystem"], query_text: str) -> str:
    """Embed once and search collections in parallel."""
    if not rag_systems or not RAG_AVAILABLE or not query_text:
        return ""
    embedding = embed_query_text(query_text)
    if not embedding:
        return ""

    parts: List[str] = []
    workers = max(1, min(RAG_PARALLEL_WORKERS, len(rag_systems)))

    def _fetch(rag_sys: RAGSystem) -> str:
        try:
            rag_sys.initialize()
            return rag_sys.get_context_with_embedding(embedding) or ""
        except Exception as e:
            print(f"[RAG] Parallel fetch error ({rag_sys._label}): {e}")
            return ""

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_fetch, sys) for sys in rag_systems]
        for fut in as_completed(futures):
            ctx = fut.result()
            if ctx:
                parts.append(ctx)
    return "\n\n".join(parts)


# RAG instances — one per collection
rag_livestock = RAGSystem(LIVESTOCK_KNOWLEDGE_COLLECTION, label="livestock_knowledge")
rag_plant = RAGSystem(PLANT_KNOWLEDGE_COLLECTION, label="plant_knowledge")
rag_crop = RAGSystem(CROP_KNOWLEDGE_COLLECTION, label="crop_knowledge")
rag_soil = RAGSystem(SOIL_KNOWLEDGE_COLLECTION, label="soil_knowledge")
rag_field = RAGSystem(FIELD_KNOWLEDGE_COLLECTION, label="field_knowledge")
rag_bakasura = RAGSystem(BAKASURA_DOCS_COLLECTION, label="bakasura-docs")
rag_news = RAGSystem(NEWS_ARTICLES_COLLECTION, label="news_articles")
rag_hitl_charlie = RAGSystem(HITL_CHARLIE_COLLECTION, label="hitl-charlie")

# Backward-compatible alias
rag = rag_livestock
