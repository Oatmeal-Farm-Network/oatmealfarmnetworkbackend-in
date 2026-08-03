# --- chat_history.py --- (Firestore-backed chat persistence)
"""
Persists chat conversations to Firestore so users can retrieve past sessions.

Schema (nested subcollections):

  threads/{thread_id}                          — thread metadata
    Fields:
      thread_id   : str
      user_id     : str
      created_at  : str (ISO-8601)
      updated_at  : str (ISO-8601)
      status      : str ("active" | "complete")
      advisory_type : str | None
      message_count : int
      preview     : str  (first user message, truncated to 100 chars)
      farm_context : dict | None  (set on completion)

  threads/{thread_id}/messages/{message_id}    — individual messages
    Fields:
      role     : str ("user" | "assistant" | "system" | "tool")
      content  : str
      ts       : str (ISO-8601)
      metadata : dict | None  (latency_ms, advisory_type, options, …)
"""
import datetime
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from config import (
    FIRESTORE_AVAILABLE,
    CHAT_HISTORY_DATABASE,
    GCP_CREDENTIALS,
    GCP_PROJECT,
    THREADS_COLLECTION,
)

# ── Org-profile collection ────────────────────────────────────────────────────
# Formal schema for the Cassia-seeded onboarding profile. Written once at
# account setup, merged into get_org_memory() so all agents inherit it.
ORG_PROFILES_COLLECTION = "org_profiles"

# Canonical field names — all agents read these keys from get_org_memory().
# Validate writes against this to avoid drift across agents.
_ORG_PROFILE_FIELDS = frozenset({
    # identity
    "business_id", "people_id", "business_type", "plan_tier",
    # agronomic
    "crops", "field_count", "size_ha", "uses_agronomist", "location",
    # commercial
    "channels", "revenue_model",
    # operational
    "headache",
    # agent-specific
    "brand_context",   # Lavendir website builder
    "cuisine_type",    # Pairsley — restaurants only
    "sourcing_prefs",  # Pairsley — restaurants only
    # meta
    "seeded_at", "updated_at",
})

if FIRESTORE_AVAILABLE:
    from google.cloud import firestore

logger = logging.getLogger("farm_advisory.chat_history")

# ---------------------------------------------------------------------------
# Observability counters (in-process; swap for Prometheus / OpenTelemetry
# counters when a metrics library is added).
# ---------------------------------------------------------------------------

_metrics: Dict[str, int] = {
    "write_ok": 0,
    "write_fail": 0,
    "messages_logged": 0,
}


def get_metrics() -> Dict[str, int]:
    """Return a snapshot of the in-process counters."""
    return dict(_metrics)


class ChatHistory:
    """Manages chat session persistence in Firestore using nested subcollections."""

    def __init__(self) -> None:
        self._db = None

    # ------------------------------------------------------------------
    # Firestore client (lazy)
    # ------------------------------------------------------------------

    @property
    def firestore_db(self):
        """Lazy initialization of Firestore client."""
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
                    logger.error("[ChatHistory] Credentials error: %s", e)
            try:
                kwargs: Dict[str, Any] = {
                    "project": GCP_PROJECT,
                    "database": CHAT_HISTORY_DATABASE,
                }
                if credentials:
                    kwargs["credentials"] = credentials
                self._db = firestore.Client(**kwargs)
                logger.info(
                    "[ChatHistory] Connected to Firestore (%s)", CHAT_HISTORY_DATABASE
                )
            except Exception as e:
                logger.error("[ChatHistory] Firestore connection failed: %s", e)
        return self._db

    # ------------------------------------------------------------------
    # Collection helpers
    # ------------------------------------------------------------------

    @property
    def threads_col(self):
        """Top-level threads collection reference."""
        try:
            db = self.firestore_db
            if db:
                return db.collection(THREADS_COLLECTION)
        except Exception:
            pass
        return None

    def _messages_col(self, thread_id: str):
        """Messages subcollection for a given thread."""
        col = self.threads_col
        if col is not None:
            return col.document(thread_id).collection("messages")
        return None

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def save_message(
        self,
        user_id: str,
        thread_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        business_id: Optional[str] = None,
    ) -> bool:
        """Persist a single message and ensure the parent thread doc exists.

        Creates the thread document on the first message.
        business_id is stored on the thread so org-wide memory queries can
        aggregate across all team members' conversations for the same org.
        """
        if self.threads_col is None:
            return False

        t0 = time.monotonic()
        try:
            now = datetime.datetime.utcnow().isoformat()
            thread_ref = self.threads_col.document(thread_id)

            # --- upsert thread doc ---
            thread_snap = thread_ref.get()
            if thread_snap.exists:
                update_doc: Dict[str, Any] = {
                    "updated_at": now,
                    "message_count": firestore.Increment(1),
                }
                # Backfill business_id if missing from an older thread doc
                existing = thread_snap.to_dict() or {}
                if business_id and not existing.get("business_id"):
                    update_doc["business_id"] = str(business_id)
                thread_ref.update(update_doc)
            else:
                preview = content[:100] if role == "user" else ""
                thread_doc: Dict[str, Any] = {
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "created_at": now,
                    "updated_at": now,
                    "status": "active",
                    "advisory_type": None,
                    "message_count": 1,
                    "preview": preview,
                    "farm_context": None,
                }
                if business_id:
                    thread_doc["business_id"] = str(business_id)
                thread_ref.set(thread_doc)

            # --- add message to subcollection ---
            message_id = f"{now}_{uuid.uuid4().hex[:8]}"
            msg_doc: Dict[str, Any] = {
                "role": role,
                "content": content,
                "ts": now,
            }
            if metadata:
                msg_doc["metadata"] = metadata

            self._messages_col(thread_id).document(message_id).set(msg_doc)

            # Update preview if this is the first user message
            if role == "user" and not thread_snap.exists:
                # preview was already set above during creation
                pass
            elif role == "user":
                # Check if preview is still empty (e.g. thread started with assistant)
                data = thread_snap.to_dict() or {}
                if not data.get("preview"):
                    thread_ref.update({"preview": content[:100]})

            elapsed_ms = int((time.monotonic() - t0) * 1000)
            _metrics["write_ok"] += 1
            _metrics["messages_logged"] += 1
            logger.info(
                "[ChatHistory] Saved %s message to thread %s (%d ms)",
                role,
                thread_id,
                elapsed_ms,
            )
            return True

        except Exception as e:
            _metrics["write_fail"] += 1
            logger.error("[ChatHistory] Save error: %s", e, exc_info=True)
            return False

    def mark_complete(
        self,
        user_id: str,
        thread_id: str,
        advisory_type: Optional[str] = None,
        farm_context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Mark a conversation as complete with optional metadata."""
        if self.threads_col is None:
            return False
        try:
            update: Dict[str, Any] = {
                "status": "complete",
                "updated_at": datetime.datetime.utcnow().isoformat(),
            }
            if advisory_type:
                update["advisory_type"] = advisory_type
            if farm_context:
                update["farm_context"] = farm_context
            self.threads_col.document(thread_id).update(update)
            logger.info("[ChatHistory] Thread %s marked complete", thread_id)
            return True
        except Exception as e:
            logger.error("[ChatHistory] Mark complete error: %s", e)
            return False

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def get_threads(
        self,
        user_id: str,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """List threads for a user, ordered by ``updated_at`` DESC.

        Returns ``(threads_list, next_cursor)``.  ``next_cursor`` is the
        ``updated_at`` value of the last returned thread (use it as
        ``cursor`` for the next page) or ``None`` when there are no more.
        """
        if self.threads_col is None:
            return [], None
        try:
            query = (
                self.threads_col.where("user_id", "==", user_id)
                .order_by("updated_at", direction=firestore.Query.DESCENDING)
            )
            if cursor:
                query = query.start_after({"updated_at": cursor})
            query = query.limit(limit)

            docs = list(query.stream())
            threads: List[Dict[str, Any]] = []
            for doc in docs:
                data = doc.to_dict()
                threads.append(
                    {
                        "thread_id": data.get("thread_id"),
                        "status": data.get("status"),
                        "message_count": data.get("message_count", 0),
                        "advisory_type": data.get("advisory_type"),
                        "created_at": data.get("created_at"),
                        "updated_at": data.get("updated_at"),
                        "preview": data.get("preview", ""),
                    }
                )

            next_cursor = threads[-1]["updated_at"] if threads else None
            return threads, next_cursor

        except Exception as e:
            logger.error("[ChatHistory] Get threads error: %s", e)
            return [], None

    def get_user_memory(self, user_id: str, max_threads: int = 10) -> Dict[str, Any]:
        """Aggregate farm_context from this user's recent completed threads.

        Returns a profile Saige injects into prompts so she remembers locations,
        crops/livestock, farm size, recurring concerns, and past recommendations
        across conversations. Safe to call on every turn — bounded query.
        """
        if self.threads_col is None:
            return {}
        try:
            query = (
                self.threads_col.where("user_id", "==", user_id)
                .where("status", "==", "complete")
                .order_by("updated_at", direction=firestore.Query.DESCENDING)
                .limit(max_threads)
            )
            locations: List[str] = []
            crops: List[str] = []
            farm_sizes: List[str] = []
            recent_topics: List[str] = []
            recent_solutions: List[str] = []  # past recommendations Saige gave
            known_issues: List[str] = []       # recurring problems this farmer raises
            seen_loc, seen_crop, seen_size = set(), set(), set()
            seen_issues: set = set()
            for doc in query.stream():
                ctx = (doc.to_dict() or {}).get("farm_context") or {}
                loc = ctx.get("location")
                if loc and loc not in seen_loc:
                    locations.append(loc); seen_loc.add(loc)
                for c in (ctx.get("crops") or []):
                    if c not in seen_crop:
                        crops.append(c); seen_crop.add(c)
                fs = ctx.get("farm_size")
                if fs and fs not in seen_size:
                    farm_sizes.append(fs); seen_size.add(fs)
                summary = ctx.get("assessment_summary")
                if summary:
                    recent_topics.append(summary)
                # Collect past recommendations (top 2 per thread, deduped)
                for rec in (ctx.get("recommendations") or [])[:2]:
                    if rec and len(recent_solutions) < 8:
                        recent_solutions.append(rec)
                # Collect recurring issues this farmer has raised
                for issue in (ctx.get("current_issues") or []):
                    if issue and issue not in seen_issues:
                        known_issues.append(issue)
                        seen_issues.add(issue)
            return {
                "locations": locations,
                "crops": crops,
                "farm_sizes": farm_sizes,
                "recent_topics": recent_topics[:5],
                "recent_solutions": recent_solutions[:6],
                "known_issues": list(known_issues)[:8],
            }
        except Exception as e:
            logger.error("[ChatHistory] get_user_memory error: %s", e)
            return {}

    def get_org_memory(
        self,
        business_id: str,
        exclude_user_id: Optional[str] = None,
        max_threads: int = 30,
    ) -> Dict[str, Any]:
        """Aggregate farm_context from ALL team members' completed threads for this org.

        Returns shared org-level facts: locations, crops, animals, recurring issues,
        and solutions that any team member has received. Personal user details are not
        included — only agricultural/operational facts about the organisation.

        exclude_user_id: skip this user's own threads (their personal memory is loaded
        separately via get_user_memory and we don't want to double-count it here).
        """
        if not business_id:
            return {}

        # Load Cassia-seeded onboarding profile first so conversation-derived
        # facts augment (rather than replace) the structured baseline.
        seeded_profile: Dict[str, Any] = self.get_org_profile(business_id)

        if self.threads_col is None:
            # Return the seeded profile alone when Firestore threads are offline.
            return {
                "locations": [],
                "crops": list(seeded_profile.get("crops") or []),
                "farm_sizes": [],
                "recent_topics": [],
                "org_solutions": [],
                "known_org_issues": [],
                "seeded_profile": seeded_profile,
                "channels": seeded_profile.get("channels") or [],
                "plan_tier": seeded_profile.get("plan_tier") or "",
                "revenue_model": seeded_profile.get("revenue_model") or "",
                "uses_agronomist": seeded_profile.get("uses_agronomist"),
                "headache": seeded_profile.get("headache") or "",
                "business_type": seeded_profile.get("business_type") or "",
            }
        try:
            # Single equality filter on business_id — no composite index needed.
            # Filter status and sort in Python to avoid Firestore index requirements.
            query = (
                self.threads_col
                .where("business_id", "==", str(business_id))
                .limit(max_threads)
            )
            # Pre-seed crops from the structured profile so the list is populated
            # even for businesses with no completed conversations yet.
            locations: List[str] = []
            seed_crops: List[str] = list(seeded_profile.get("crops") or [])
            crops: List[str] = list(seed_crops)
            farm_sizes: List[str] = []
            recent_topics: List[str] = []
            org_solutions: List[str] = []
            known_org_issues: List[str] = []
            seen_loc, seen_crop, seen_size = set(), set(), set()
            seen_crop = set(c.lower() for c in seed_crops)
            seen_issues: set = set()

            docs = sorted(
                [d for d in query.stream() if (d.to_dict() or {}).get("status") == "complete"],
                key=lambda d: (d.to_dict() or {}).get("updated_at", ""),
                reverse=True,
            )[:max_threads]

            for doc in docs:
                data = doc.to_dict() or {}
                # Optionally skip the requesting user's own threads (loaded in personal memory)
                if exclude_user_id and data.get("user_id") == exclude_user_id:
                    continue
                ctx = data.get("farm_context") or {}
                loc = ctx.get("location")
                if loc and loc not in seen_loc:
                    locations.append(loc); seen_loc.add(loc)
                for c in (ctx.get("crops") or []):
                    if c.lower() not in seen_crop:
                        crops.append(c); seen_crop.add(c.lower())
                fs = ctx.get("farm_size")
                if fs and fs not in seen_size:
                    farm_sizes.append(fs); seen_size.add(fs)
                summary = ctx.get("assessment_summary")
                if summary and len(recent_topics) < 8:
                    recent_topics.append(summary)
                for rec in (ctx.get("recommendations") or [])[:2]:
                    if rec and len(org_solutions) < 8:
                        org_solutions.append(rec)
                for issue in (ctx.get("current_issues") or []):
                    if issue and issue not in seen_issues:
                        known_org_issues.append(issue)
                        seen_issues.add(issue)

            return {
                "locations": locations[:5],
                "crops": crops[:15],
                "farm_sizes": farm_sizes[:3],
                "recent_topics": recent_topics[:6],
                "org_solutions": org_solutions[:6],
                "known_org_issues": list(known_org_issues)[:10],
                # Structured fields from Cassia onboarding (if seeded)
                "seeded_profile": seeded_profile,
                "channels": seeded_profile.get("channels") or [],
                "plan_tier": seeded_profile.get("plan_tier") or "",
                "revenue_model": seeded_profile.get("revenue_model") or "",
                "uses_agronomist": seeded_profile.get("uses_agronomist"),
                "headache": seeded_profile.get("headache") or "",
                "business_type": seeded_profile.get("business_type") or "",
            }
        except Exception as e:
            logger.error("[ChatHistory] get_org_memory error: %s", e)
            return {}

    # ------------------------------------------------------------------
    # Org profile (Cassia-seeded structured onboarding data)
    # ------------------------------------------------------------------

    def save_org_memory_profile(
        self, business_id: str, data: Dict[str, Any]
    ) -> bool:
        """Write Cassia's structured onboarding profile for this business.

        Seeds get_org_memory() before any conversations have happened so Saige,
        Thaiyme, Lavendir, and Pairsley all inherit the farmer's stated crops,
        channels, headache, and plan tier from day one.
        """
        db = self.firestore_db
        if not db or not business_id:
            return False
        try:
            profile: Dict[str, Any] = {
                k: v for k, v in data.items() if k in _ORG_PROFILE_FIELDS
            }
            profile["business_id"] = int(business_id)
            profile["updated_at"] = time.time()
            if "seeded_at" not in profile:
                profile["seeded_at"] = time.time()
            db.collection(ORG_PROFILES_COLLECTION).document(str(business_id)).set(
                profile, merge=True
            )
            logger.info(
                "[ChatHistory] Saved org_profile for business %s", business_id
            )
            return True
        except Exception as e:
            logger.error("[ChatHistory] save_org_memory_profile error: %s", e)
            return False

    def get_org_profile(self, business_id: str) -> Dict[str, Any]:
        """Read the Cassia-seeded onboarding profile for a business.

        Returns an empty dict if no profile has been written yet.
        """
        db = self.firestore_db
        if not db or not business_id:
            return {}
        try:
            snap = (
                db.collection(ORG_PROFILES_COLLECTION)
                .document(str(business_id))
                .get()
            )
            return snap.to_dict() or {} if snap.exists else {}
        except Exception as e:
            logger.error("[ChatHistory] get_org_profile error: %s", e)
            return {}

    def get_messages(
        self,
        user_id: str,
        thread_id: str,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Fetch messages for a thread ordered by ``ts``.

        Returns ``(messages_list, next_cursor)``.
        """
        if self.threads_col is None:
            return [], None
        try:
            # Verify ownership
            thread_snap = self.threads_col.document(thread_id).get()
            if not thread_snap.exists:
                return [], None
            if (thread_snap.to_dict() or {}).get("user_id") != user_id:
                return [], None

            msg_col = self._messages_col(thread_id)
            query = msg_col.order_by("ts")
            if cursor:
                query = query.start_after({"ts": cursor})
            query = query.limit(limit)

            docs = list(query.stream())
            messages: List[Dict[str, Any]] = []
            for doc in docs:
                data = doc.to_dict()
                messages.append(
                    {
                        "message_id": doc.id,
                        "role": data.get("role"),
                        "content": data.get("content"),
                        "ts": data.get("ts"),
                        "metadata": data.get("metadata"),
                    }
                )

            next_cursor = messages[-1]["ts"] if messages else None
            return messages, next_cursor

        except Exception as e:
            logger.error("[ChatHistory] Get messages error: %s", e)
            return [], None

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_analytics(self, user_id: str, limit: int = 100) -> Dict[str, Any]:
        """Aggregate analytics across all threads for a user."""
        if self.threads_col is None:
            return {}
        try:
            query = (
                self.threads_col.where("user_id", "==", user_id)
                .order_by("updated_at", direction=firestore.Query.DESCENDING)
                .limit(limit)
            )
            docs = list(query.stream())

            total = len(docs)
            completed = 0
            type_counts: Dict[str, int] = {}
            total_messages = 0
            latencies: List[int] = []
            daily_counts: Dict[str, int] = {}

            for doc in docs:
                data = doc.to_dict()
                msg_count = data.get("message_count", 0)
                total_messages += msg_count

                if data.get("status") == "complete":
                    completed += 1

                atype = data.get("advisory_type")
                if atype:
                    type_counts[atype] = type_counts.get(atype, 0) + 1

                # Daily activity (by created_at date)
                created = data.get("created_at", "")
                if created:
                    day = created[:10]  # "YYYY-MM-DD"
                    daily_counts[day] = daily_counts.get(day, 0) + 1

                # Latencies require reading the messages subcollection
                try:
                    msg_docs = (
                        self._messages_col(doc.id)
                        .where("metadata.latency_ms", ">", 0)
                        .stream()
                    )
                    for mdoc in msg_docs:
                        mdata = mdoc.to_dict()
                        meta = mdata.get("metadata") or {}
                        if "latency_ms" in meta:
                            latencies.append(meta["latency_ms"])
                except Exception:
                    pass  # latency collection is best-effort

            # Build recent activity (last 7 days)
            today = datetime.date.today()
            recent_activity = []
            for i in range(6, -1, -1):
                d = (today - datetime.timedelta(days=i)).isoformat()
                recent_activity.append({"date": d, "count": daily_counts.get(d, 0)})

            return {
                "total_conversations": total,
                "completed_conversations": completed,
                "completion_rate": round(completed / total, 2) if total else 0,
                "advisory_type_distribution": type_counts,
                "total_messages": total_messages,
                "avg_messages_per_thread": round(total_messages / total, 1) if total else 0,
                "avg_response_time_ms": (
                    round(sum(latencies) / len(latencies)) if latencies else 0
                ),
                "recent_activity": recent_activity,
            }
        except Exception as e:
            logger.error("[ChatHistory] Analytics error: %s", e)
            return {}

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_thread(self, user_id: str, thread_id: str) -> bool:
        """Delete a thread and all its messages."""
        if self.threads_col is None:
            return False
        try:
            thread_ref = self.threads_col.document(thread_id)
            thread_snap = thread_ref.get()
            if not thread_snap.exists:
                return False
            if (thread_snap.to_dict() or {}).get("user_id") != user_id:
                return False

            # Delete all messages in the subcollection first
            msg_col = self._messages_col(thread_id)
            batch_size = 100
            while True:
                docs = list(msg_col.limit(batch_size).stream())
                if not docs:
                    break
                batch = self.firestore_db.batch()
                for doc in docs:
                    batch.delete(doc.reference)
                batch.commit()

            # Delete the thread document itself
            thread_ref.delete()
            logger.info("[ChatHistory] Deleted thread %s", thread_id)
            return True
        except Exception as e:
            logger.error("[ChatHistory] Delete error: %s", e)
            return False

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Write, read, and delete a test document to verify Firestore access."""
        if self.firestore_db is None:
            return False
        try:
            test_ref = self.firestore_db.collection("_health_check").document("test")
            test_ref.set({"ts": datetime.datetime.utcnow().isoformat(), "ok": True})
            snap = test_ref.get()
            if not snap.exists:
                return False
            test_ref.delete()
            return True
        except Exception as e:
            logger.error("[ChatHistory] Health check failed: %s", e)
            return False


# Module-level singleton
chat_history = ChatHistory()
