"""
Redis-backed response cache.

The cache is an optimisation, never a dependency (audit PERF-3): any Redis
error on read or write is logged and counted
(``aibi.cache.lookups{result=error}``), and the request carries on as a
cache miss.
"""

import hashlib
import json
import logging
from typing import Any

import redis
from redis.exceptions import RedisError

from ai_bi_analytics.core import metrics
from ai_bi_analytics.core.config import Settings

logger = logging.getLogger(__name__)

KEY_PREFIX = "query_cache:"


def normalise_question(question: str) -> str:
    """Case- and whitespace-insensitive, so trivial variants share an entry."""
    return " ".join(question.casefold().split())


def generate_cache_key(question: str, *context: str) -> str:
    """
    Key for a question in a context: the query scope's fingerprint, and
    anything else that changes the answer (model, row cap). A scope or
    configuration change never serves a stale answer. Parts are joined
    with a separator so they can't run together.
    """
    material = "\x1f".join([normalise_question(question), *context])
    return KEY_PREFIX + hashlib.sha256(material.encode()).hexdigest()


class ResultCache:
    def __init__(self, client: redis.Redis, cfg: Settings) -> None:
        self._redis = client
        self._cfg = cfg

    def key(self, question: str, scope_fingerprint: str) -> str:
        return generate_cache_key(
            question,
            scope_fingerprint,
            self._cfg.llm_sql_model,
            str(self._cfg.max_result_rows),
        )

    def get(self, key: str) -> dict[str, Any] | None:
        try:
            data = self._redis.get(key)
        except RedisError:
            logger.warning("Cache read failed; continuing without cache", exc_info=True)
            metrics.cache_lookups.add(1, {"result": "error"})
            return None

        if data:
            try:
                value = json.loads(data)  # type: ignore[arg-type]
            except json.JSONDecodeError:
                logger.warning("Ignoring corrupt cache entry", extra={"cache_key": key})
            else:
                if isinstance(value, dict):
                    metrics.cache_lookups.add(1, {"result": "hit"})
                    return value
                logger.warning("Ignoring corrupt cache entry", extra={"cache_key": key})
        metrics.cache_lookups.add(1, {"result": "miss"})
        return None

    def set(self, key: str, value: dict[str, Any]) -> bool:
        """
        Caches a JSON-serialisable response for CACHE_TTL_SECONDS (0 disables
        caching). Responses above CACHE_MAX_BYTES are skipped so one large
        result can't crowd out the cache (audit SEC-5).

        Returns:
            bool: whether the response was cached.
        """
        ttl = self._cfg.cache_ttl_seconds
        if ttl <= 0:
            return False
        payload = json.dumps(value)
        size = len(payload.encode())
        if size > self._cfg.cache_max_bytes:
            logger.info("Response not cached: %d bytes > CACHE_MAX_BYTES", size)
            return False
        try:
            self._redis.setex(key, ttl, payload)
        except RedisError:
            logger.warning("Cache write failed; response not cached", exc_info=True)
            return False
        return True
