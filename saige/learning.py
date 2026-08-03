# --- learning.py --- (Saige data flywheel: cross-user learning extraction + retrieval)
"""
After each completed advisory conversation, a background LLM call extracts an
anonymized agricultural insight (problem + solution). These are embedded and stored
in Firestore (saige_learnings collection) for vector retrieval.

When the next farmer asks a similar question, relevant community learnings surface
alongside standard RAG context, so Saige draws on real problem-solving history
from across the platform — not just curated knowledge.

Privacy: people_id and thread_id are stored for deduplication only. The extracted
problem/solution is written in anonymized, third-person terms (no names, no exact
addresses). Learnings with quality_score < MIN_QUALITY_SCORE are excluded from search.
"""
import datetime
import json
import logging
import threading
import uuid
from typing import Any, Dict, List, Optional

from config import (
    FIRESTORE_AVAILABLE,
    FIRESTORE_DATABASE,
    GCP_CREDENTIALS,
    GCP_LOCATION,
    GCP_PROJECT,
    EMBEDDING_MODEL,
    RAG_AVAILABLE,
)

logger = logging.getLogger("farm_advisory.learning")

SAIGE_LEARNINGS_COLLECTION = "saige_learnings"
MIN_QUALITY_SCORE = -3.0  # learnings downvoted below this are suppressed

_EXTRACT_PROMPT = """You are a farm knowledge extraction system for Oatmeal Farm Network.
Given the conversation below, extract a concise agricultural insight that could help OTHER farmers facing similar challenges.

RULES:
- Write in third-person, general terms. NO specific names, businesses, or identities.
- Location only by climate/region type (e.g. "arid Central Valley", "humid Southeast", "Texas Hill Country"), never an exact address.
- Focus on the agricultural insight: what was the problem, what was the diagnosis, what was recommended.
- Return ONLY valid JSON. No markdown, no explanation, no preamble.

Return this exact JSON structure:
{{
  "category": "livestock" | "crops" | "weather" | "mixed",
  "problem": "1-2 sentence description of the farming problem observed",
  "solution": "1-3 sentence description of the recommended diagnosis and key action steps",
  "crops": ["list of crop names mentioned, empty if none"],
  "animals": ["list of animal types mentioned, empty if none"],
  "location_type": "general climate/region type or empty string",
  "keywords": ["5-10 searchable agricultural keywords"]
}}

If the conversation does NOT contain a clear, resolvable agricultural problem (e.g. it was just a greeting, account question, or vague chat), return exactly:
{{"skip": true}}

Conversation:
{conversation}"""


class LearningStore:
    """Stores and retrieves anonymized agricultural learnings from Saige conversations."""

    def __init__(self):
        self._db = None
        self._embeddings = None

    @property
    def _firestore(self):
        if self._db is None and GCP_PROJECT and FIRESTORE_AVAILABLE:
            credentials = None
            if GCP_CREDENTIALS:
                try:
                    from google.oauth2 import service_account
                    credentials = service_account.Credentials.from_service_account_file(
                        GCP_CREDENTIALS,
                        scopes=["https://www.googleapis.com/auth/cloud-platform"],
                    )
                except Exception as e:
                    logger.error("[LearningStore] Credentials error: %s", e)
            try:
                from google.cloud import firestore
                kwargs: Dict[str, Any] = {"project": GCP_PROJECT, "database": FIRESTORE_DATABASE}
                if credentials:
                    kwargs["credentials"] = credentials
                self._db = firestore.Client(**kwargs)
                logger.info("[LearningStore] Connected to Firestore (%s)", FIRESTORE_DATABASE)
            except Exception as e:
                logger.error("[LearningStore] Firestore connection failed: %s", e)
        return self._db

    def _embed(self, text: str) -> List[float]:
        if self._embeddings is None and RAG_AVAILABLE and GCP_PROJECT:
            try:
                from langchain_google_genai import GoogleGenerativeAIEmbeddings
                self._embeddings = GoogleGenerativeAIEmbeddings(
                    model=EMBEDDING_MODEL, project=GCP_PROJECT, location=GCP_LOCATION
                )
            except Exception as e:
                logger.error("[LearningStore] Embeddings init failed: %s", e)
        if self._embeddings:
            try:
                return self._embeddings.embed_query(text)
            except Exception as e:
                logger.error("[LearningStore] Embedding call failed: %s", e)
        return []

    def save(self, doc: Dict[str, Any]) -> Optional[str]:
        """Embed and persist one learning document. Returns the saved learning_id."""
        db = self._firestore
        if db is None:
            return None
        try:
            from google.cloud.firestore_v1.vector import Vector
            learning_id = doc.get("id") or uuid.uuid4().hex
            embed_text = f"{doc.get('problem', '')} {doc.get('solution', '')}"
            embedding = self._embed(embed_text)
            record: Dict[str, Any] = {
                **doc,
                "id": learning_id,
                "ts": datetime.datetime.utcnow().isoformat(),
                "quality_score": float(doc.get("quality_score", 1.0)),
                "feedback_count": int(doc.get("feedback_count", 0)),
            }
            if embedding:
                record["embedding"] = Vector(embedding)
            db.collection(SAIGE_LEARNINGS_COLLECTION).document(learning_id).set(record)
            logger.info(
                "[LearningStore] Saved learning %s (category=%s, crops=%s)",
                learning_id, doc.get("category"), doc.get("crops"),
            )
            return learning_id
        except Exception as e:
            logger.error("[LearningStore] Save failed: %s", e)
            return None

    def search(self, query: str, n: int = 4) -> List[Dict[str, Any]]:
        """Vector-search learnings most relevant to query. Excludes downvoted entries."""
        if not RAG_AVAILABLE:
            return []
        db = self._firestore
        if db is None:
            return []
        try:
            from google.cloud.firestore_v1.vector import Vector
            from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
            embedding = self._embed(query)
            if not embedding:
                return []
            results = (
                db.collection(SAIGE_LEARNINGS_COLLECTION)
                .find_nearest(
                    vector_field="embedding",
                    query_vector=Vector(embedding),
                    distance_measure=DistanceMeasure.COSINE,
                    limit=n + 3,  # fetch extra to allow filtering
                )
                .get()
            )
            out = []
            for doc in results:
                data = doc.to_dict()
                if float(data.get("quality_score", 1.0)) < MIN_QUALITY_SCORE:
                    continue
                out.append(data)
                if len(out) >= n:
                    break
            return out
        except Exception as e:
            logger.error("[LearningStore] Search failed: %s", e)
            return []

    def record_feedback(self, thread_id: str, rating: int) -> bool:
        """
        Apply a +1 or -1 rating to the most recent learning from this thread.
        Called when a farmer gives thumbs up/down in the widget.
        """
        db = self._firestore
        if db is None:
            return False
        try:
            from google.cloud import firestore as _fs
            query = (
                db.collection(SAIGE_LEARNINGS_COLLECTION)
                .where("thread_id", "==", thread_id)
                .order_by("ts", direction=_fs.Query.DESCENDING)
                .limit(1)
            )
            docs = list(query.stream())
            if not docs:
                return False
            docs[0].reference.update({
                "quality_score": _fs.Increment(rating),
                "feedback_count": _fs.Increment(1),
            })
            logger.info("[LearningStore] Feedback %+d applied to thread %s", rating, thread_id)
            return True
        except Exception as e:
            logger.error("[LearningStore] Feedback failed: %s", e)
            return False


learning_store = LearningStore()


# ── Background extraction ────────────────────────────────────────────────────

def _do_extract(
    people_id: str,
    thread_id: str,
    history: List[str],
    diagnosis: str,
    recommendations: List[str],
    advisory_type: str,
    crops: List[str],
    location: str,
    llm,
) -> None:
    """Runs in a daemon thread. Extracts one learning from this conversation and saves it."""
    try:
        # Build a compact conversation snapshot
        conv_lines = list((history or [])[-12:])
        if diagnosis:
            conv_lines.append(f"Saige: {diagnosis}")
        if recommendations:
            conv_lines.append("Recommendations: " + "; ".join(recommendations[:5]))
        conversation_text = "\n".join(conv_lines).strip()

        if len(conversation_text) < 80:
            return  # too thin to learn from

        prompt = _EXTRACT_PROMPT.format(conversation=conversation_text[:3500])
        resp = llm.invoke(prompt)
        raw = (resp.content if hasattr(resp, "content") else str(resp)).strip()

        # Strip markdown fences if the LLM added them
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)
        if data.get("skip"):
            return

        if not data.get("problem", "").strip() or not data.get("solution", "").strip():
            return

        doc: Dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "thread_id": thread_id,
            "people_id": people_id,  # stored for dedup, never surfaced to other users
            "category": data.get("category") or advisory_type or "mixed",
            "problem": data["problem"],
            "solution": data["solution"],
            "crops": data.get("crops") or crops or [],
            "animals": data.get("animals") or [],
            "location_type": data.get("location_type") or location or "",
            "keywords": data.get("keywords") or [],
            "quality_score": 1.0,
            "feedback_count": 0,
        }
        learning_store.save(doc)
    except json.JSONDecodeError:
        pass  # LLM produced non-JSON — skip silently
    except Exception as e:
        logger.error("[LearningStore] Extraction error: %s", e)


def extract_learning_background(
    people_id: str,
    thread_id: str,
    history: List[str],
    diagnosis: str,
    recommendations: List[str],
    advisory_type: str,
    crops: List[str],
    location: str,
    llm,
) -> None:
    """Fire-and-forget: spawn a daemon thread to extract a learning. Non-blocking."""
    threading.Thread(
        target=_do_extract,
        args=(people_id, thread_id, history, diagnosis, recommendations,
              advisory_type, crops, location, llm),
        daemon=True,
    ).start()


# ── RAG-style retrieval for advisory prompts ─────────────────────────────────

def get_community_context(query: str, n: int = 3) -> str:
    """
    Return a formatted section of community learnings for injection into advisory prompts.
    Empty string if no relevant learnings or RAG unavailable.
    """
    results = learning_store.search(query, n=n)
    if not results:
        return ""
    parts = [
        "COMMUNITY INSIGHTS (anonymized learnings from Saige's past conversations — "
        "use these as additional context, not as authoritative facts):"
    ]
    for r in results:
        problem = (r.get("problem") or "").strip()
        solution = (r.get("solution") or "").strip()
        if problem and solution:
            parts.append(f"• Problem seen: {problem}")
            parts.append(f"  What helped: {solution}")
    if len(parts) == 1:
        return ""  # no valid entries after formatting
    return "\n".join(parts)
