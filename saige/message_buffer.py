# --- message_buffer.py --- (Last-N message buffer using Redis)
"""
Fast, reliable short-term context per conversation (thread_id) using Redis.
Implements helpers:
  - push_message(thread_id, message)
  - get_last_n(thread_id, n)
  - clear_thread(thread_id)

Task 6 observability: per-op latency logging, error counters, buffer-length debug.
"""
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from config import (
    SHORT_TERM_N,
    SHORT_TERM_TTL_SECONDS,
    REDIS_ENABLED,
    REDIS_LAST_MESSAGES_KEY_TEMPLATE,
    MAX_STORED_CONTENT_CHARS,
    METADATA_ALLOWED_KEYS,
    MAX_METADATA_BYTES,
)
from redis_client import get_redis_client

logger = logging.getLogger("farm_advisory")


class MessageBuffer:
    """Last-N message buffer using Redis for fast context retrieval."""

    # --- Task 6: observability counters (in-memory, reset on restart) ---
    _ops_total: int = 0
    _errors_total: int = 0

    def __init__(self) -> None:
        self.client = None
        self._shared_client = False
        self.buffer_size = SHORT_TERM_N
        self.ttl_seconds = SHORT_TERM_TTL_SECONDS
        self._initialize()

    def _initialize(self) -> None:
        """Initialize Redis client if Redis is enabled."""
        if self.client:
            return
        if REDIS_ENABLED:
            self.client = get_redis_client(decode_responses=True)
            if self.client:
                print(
                    f"[MessageBuffer] [OK] Initialized "
                    f"(buffer_size={self.buffer_size}, ttl_seconds={self.ttl_seconds})"
                )
            else:
                print("[MessageBuffer] [WARN] Redis unavailable, buffer disabled")
        else:
            print("[MessageBuffer] [WARN] Redis disabled, buffer disabled")

    def set_client(self, redis_client) -> None:
        """Inject a shared Redis client managed by FastAPI lifespan."""
        self.client = redis_client
        self._shared_client = redis_client is not None
        if self._shared_client:
            print(
                f"[MessageBuffer] [OK] Using shared Redis client "
                f"(buffer_size={self.buffer_size}, ttl_seconds={self.ttl_seconds})"
            )
        else:
            print("[MessageBuffer] [WARN] Shared Redis client unset")

    def _key(self, thread_id: str) -> str:
        """ key format: thread:{thread_id}:last_messages."""
        return REDIS_LAST_MESSAGES_KEY_TEMPLATE.format(thread_id=thread_id)

    def _normalize_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure Task 2 JSON message format is always present.
        Task 5 safety: truncate content to MAX_STORED_CONTENT_CHARS and
        filter/limit metadata to keep Redis memory bounded.
        """
        ts_value = message.get("ts")
        content = str(message.get("content") or "")
        if len(content) > MAX_STORED_CONTENT_CHARS:
            content = content[:MAX_STORED_CONTENT_CHARS] + "...[truncated]"
        normalized: Dict[str, Any] = {
            "message_id": str(message.get("message_id") or uuid.uuid4()),
            "role": str(message.get("role") or "assistant"),
            "content": content,
            "ts": ts_value if ts_value is not None else int(time.time() * 1000),
        }
        if "metadata" in message and message.get("metadata") is not None:
            raw_meta = message["metadata"]
            if isinstance(raw_meta, dict):
                # Whitelist keys and cap serialized size
                filtered = {k: v for k, v in raw_meta.items() if k in METADATA_ALLOWED_KEYS}
                serialized = json.dumps(filtered, separators=(",", ":"))
                if len(serialized.encode("utf-8")) <= MAX_METADATA_BYTES:
                    normalized["metadata"] = filtered
                else:
                    # Over budget — drop recommendations (largest field) and retry
                    filtered.pop("recommendations", None)
                    normalized["metadata"] = filtered
                    print(f"[MessageBuffer] Metadata trimmed (exceeded {MAX_METADATA_BYTES}B)")
            # Non-dict metadata is silently dropped
        return normalized

    def push_message(self, thread_id: str, message: Dict[str, Any]) -> bool:
        """
        Push one message into a thread buffer and keep only last N.
        Uses LPUSH + LTRIM + EXPIRE atomically for concurrency safety.
        """
        if not self.client:
            return False
        MessageBuffer._ops_total += 1
        start = time.perf_counter()
        try:
            key = self._key(thread_id)
            payload = json.dumps(self._normalize_message(message), separators=(",", ":"))

            pipe = self.client.pipeline(transaction=True)
            pipe.lpush(key, payload)
            pipe.ltrim(key, 0, self.buffer_size - 1)
            if self.ttl_seconds > 0:
                pipe.expire(key, self.ttl_seconds)
            pipe.llen(key)  # Task 6: fetch current list length for debug
            results = pipe.execute()
            latency_ms = (time.perf_counter() - start) * 1000
            buffer_len = results[-1]  # llen result is last
            logger.debug(
                f"[MessageBuffer] push_message thread={thread_id} "
                f"buffer_len={buffer_len} latency_ms={latency_ms:.2f}"
            )
            return True
        except Exception as e:
            MessageBuffer._errors_total += 1
            latency_ms = (time.perf_counter() - start) * 1000
            logger.error(
                f"[MessageBuffer] Error pushing message: {e} "
                f"(latency_ms={latency_ms:.2f}, errors_total={MessageBuffer._errors_total})"
            )
            return False

    def get_last_n(self, thread_id: str, n: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return ordered messages (oldest -> newest) for prompt context."""
        if not self.client:
            return []
        MessageBuffer._ops_total += 1
        start = time.perf_counter()
        try:
            limit = self.buffer_size if n is None else int(n)
            if limit <= 0:
                return []

            key = self._key(thread_id)
            items = self.client.lrange(key, 0, limit - 1)

            ordered: List[Dict[str, Any]] = []
            for item in reversed(items):
                ordered.append(json.loads(item))
            latency_ms = (time.perf_counter() - start) * 1000
            logger.debug(
                f"[MessageBuffer] get_last_n thread={thread_id} "
                f"returned={len(ordered)} latency_ms={latency_ms:.2f}"
            )
            return ordered
        except Exception as e:
            MessageBuffer._errors_total += 1
            latency_ms = (time.perf_counter() - start) * 1000
            logger.error(
                f"[MessageBuffer] Error getting messages: {e} "
                f"(latency_ms={latency_ms:.2f}, errors_total={MessageBuffer._errors_total})"
            )
            return []

    def clear_thread(self, thread_id: str) -> bool:
        """Delete the thread's last-N message list."""
        if not self.client:
            return False
        MessageBuffer._ops_total += 1
        start = time.perf_counter()
        try:
            key = self._key(thread_id)
            self.client.delete(key)
            latency_ms = (time.perf_counter() - start) * 1000
            logger.debug(
                f"[MessageBuffer] clear_thread thread={thread_id} latency_ms={latency_ms:.2f}"
            )
            return True
        except Exception as e:
            MessageBuffer._errors_total += 1
            latency_ms = (time.perf_counter() - start) * 1000
            logger.error(
                f"[MessageBuffer] Error clearing thread: {e} "
                f"(latency_ms={latency_ms:.2f}, errors_total={MessageBuffer._errors_total})"
            )
            return False

    # Backward-compatible wrappers for existing callers.
    def add_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        message: Dict[str, Any] = {"role": role, "content": content}
        if metadata is not None:
            message["metadata"] = metadata
        return self.push_message(thread_id, message)

    def get_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        return self.get_last_n(thread_id, self.buffer_size)

    def clear(self, thread_id: str) -> bool:
        return self.clear_thread(thread_id)

    def get_message_count(self, thread_id: str) -> int:
        """Get number of buffered messages for a thread."""
        if not self.client:
            return 0
        MessageBuffer._ops_total += 1
        try:
            key = self._key(thread_id)
            return self.client.llen(key)
        except Exception as e:
            MessageBuffer._errors_total += 1
            logger.error(f"[MessageBuffer] Error getting count: {e}")
            return 0

    @classmethod
    def stats(cls) -> Dict[str, int]:
        """Return observability counters (Task 6)."""
        return {"ops_total": cls._ops_total, "errors_total": cls._errors_total}


# Global instance
message_buffer = MessageBuffer()


# Task 2 helper functions (exact names) at module level.
def push_message(thread_id: str, message: Dict[str, Any]) -> bool:
    return message_buffer.push_message(thread_id, message)


def get_last_n(thread_id: str, n: Optional[int] = None) -> List[Dict[str, Any]]:
    return message_buffer.get_last_n(thread_id, n)


def clear_thread(thread_id: str) -> bool:
    return message_buffer.clear_thread(thread_id)
