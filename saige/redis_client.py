# --- redis_client.py --- (Redis connection manager with pooling)
from __future__ import annotations

"""
Shared Redis client management for FastAPI and helper modules.
Supports REDIS_URL (preferred) with fallback host/port/password/db vars.
"""
import logging
import time
from typing import Any, Dict, Optional, TYPE_CHECKING
from urllib.parse import urlparse

try:
    import redis
except ImportError:  # pragma: no cover - optional dependency in local dev
    redis = None

if TYPE_CHECKING:
    import redis as redis_types
    ConnectionPoolT = redis_types.ConnectionPool
    RedisT = redis_types.Redis
else:
    ConnectionPoolT = Any
    RedisT = Any

from config import (
    REDIS_AVAILABLE,
    REDIS_ENABLED,
    REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
    REDIS_SOCKET_TIMEOUT_SECONDS,
    REDIS_SSL_CERT_REQS,
    get_redis_url,
    redis_connection_mode,
)

logger = logging.getLogger("farm_advisory")


class RedisClientManager:
    """Manage shared Redis connection pools for text and binary clients."""

    def __init__(self) -> None:
        self._pool_text: Optional[ConnectionPoolT] = None
        self._pool_binary: Optional[ConnectionPoolT] = None
        self._redis_url: Optional[str] = get_redis_url() if REDIS_ENABLED else None
        self._mode = redis_connection_mode()
        self._last_error: Optional[str] = None

    def _pool_kwargs(self, decode_responses: bool) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "decode_responses": decode_responses,
            "socket_connect_timeout": REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
            "socket_timeout": REDIS_SOCKET_TIMEOUT_SECONDS,
            "retry_on_timeout": True,
            "health_check_interval": 30,
        }
        if self._redis_url and self._redis_url.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = REDIS_SSL_CERT_REQS
        return kwargs

    def _get_or_create_pool(self, decode_responses: bool) -> Optional[ConnectionPoolT]:
        if not REDIS_ENABLED or not REDIS_AVAILABLE:
            return None
        if not self._redis_url:
            return None

        if decode_responses and self._pool_text:
            return self._pool_text
        if not decode_responses and self._pool_binary:
            return self._pool_binary

        try:
            pool = redis.ConnectionPool.from_url(self._redis_url, **self._pool_kwargs(decode_responses))
            if decode_responses:
                self._pool_text = pool
            else:
                self._pool_binary = pool
            return pool
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"[Redis] Failed to create connection pool (mode={self._mode}): {e}")
            return None

    def get_client(self, decode_responses: bool = False) -> Optional[RedisT]:
        """Return pooled Redis client (text or binary) if redis is enabled/available."""
        pool = self._get_or_create_pool(decode_responses)
        if not pool:
            return None
        return redis.Redis(connection_pool=pool)

    def ping(self) -> bool:
        """Ping Redis using binary client and track last error."""
        client = self.get_client(decode_responses=False)
        if not client:
            if not self._last_error:
                self._last_error = "Redis client unavailable"
            return False

        try:
            client.ping()
            self._last_error = None
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"[Redis] Ping failed (mode={self._mode}): {e}")
            return False

    def close(self) -> None:
        """Close all Redis pools managed by this instance."""
        for pool in (self._pool_text, self._pool_binary):
            if not pool:
                continue
            try:
                pool.disconnect()
            except Exception as e:
                logger.warning(f"[Redis] Pool disconnect warning: {e}")
        self._pool_text = None
        self._pool_binary = None

    def connection_info(self) -> Dict[str, Any]:
        """Return non-sensitive Redis connection metadata."""
        info: Dict[str, Any] = {
            "enabled": REDIS_ENABLED,
            "available": REDIS_AVAILABLE,
            "mode": self._mode,
        }
        if not REDIS_ENABLED:
            info["status"] = "disabled"
            return info
        if not REDIS_AVAILABLE:
            info["status"] = "unavailable"
            return info

        redis_url = self._redis_url or ""
        parsed = urlparse(redis_url) if redis_url else None
        if parsed and parsed.hostname:
            db = parsed.path.lstrip("/") if parsed.path else ""
            info["scheme"] = parsed.scheme or "redis"
            info["target"] = f"{parsed.hostname}:{parsed.port or 6379}/{db or '0'}"
        if REDIS_SSL_CERT_REQS:
            info["ssl_cert_reqs"] = REDIS_SSL_CERT_REQS
        if self._last_error:
            info["last_error"] = self._last_error
        return info

    def last_error(self) -> Optional[str]:
        return self._last_error


_default_manager: Optional[RedisClientManager] = None


def get_redis_manager() -> RedisClientManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = RedisClientManager()
    return _default_manager


def get_redis_client(decode_responses: bool = False) -> Optional[RedisT]:
    """
    Backward-compatible helper: returns a live Redis client when possible.
    Keeps old semantics by validating with ping before returning.
    """
    manager = get_redis_manager()
    client = manager.get_client(decode_responses=decode_responses)
    if not client:
        return None

    try:
        client.ping()
        return client
    except Exception as e:
        logger.error(f"[Redis] Connection failed during client validation (mode={manager.connection_info().get('mode')}): {e}")
        return None


def test_redis_connection() -> bool:
    """Test Redis connection and return True if successful."""
    manager = get_redis_manager()
    start = time.perf_counter()
    is_ok = manager.ping()
    elapsed_ms = (time.perf_counter() - start) * 1000
    info = manager.connection_info()

    if is_ok:
        success_message = (
            f"[Redis] [OK] Connection successful (mode={info.get('mode')}, "
            f"target={info.get('target', 'n/a')}, latency_ms={elapsed_ms:.2f})"
        )
        logger.info(success_message)
        print(success_message)
    else:
        failure_message = (
            f"[Redis] [FAIL] Connection test failed (mode={info.get('mode')}, "
            f"target={info.get('target', 'n/a')}): {info.get('last_error', 'unknown error')}"
        )
        logger.error(failure_message)
        print(failure_message)

    return is_ok
