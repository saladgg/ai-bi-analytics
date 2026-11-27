"""
Redis-backed response caching layer.

The cache is an optimisation, never a dependency (audit PERF-3): any Redis
error on read or write is logged and counted
(``aibi.cache.lookups{result=error}``), and the request carries on as a
cache miss.
"""

import hashlib
import json
import logging

from redis.exceptions import RedisError

from ai_bi_analytics.core import metrics
from ai_bi_analytics.core.config import settings
from ai_bi_analytics.core.redis_client import redis_client

logger = logging.getLogger(__name__)

KEY_PREFIX = "query_cache:"


def normalise_question(question: str) -> str:
    """Case- and whitespace-insensitive, so trivial variants share an entry."""
    return " ".join(question.casefold().split())


def generate_cache_key(question: str, schema_description: str = "") -> str:
    """
    Key for a question against a schema. The schema text is part of the
    key, so a schema or scope change never serves a stale answer.
    """
    material = normalise_question(question) + "\x1f" + schema_description
    return KEY_PREFIX + hashlib.sha256(material.encode()).hexdigest()


def get_cached_response(key: str) -> dict | None:
    try:
        data = redis_client.get(key)
    except RedisError:
        logger.warning("Cache read failed; continuing without cache", exc_info=True)
        metrics.cache_lookups.add(1, {"result": "error"})
        return None

    if data:
        try:
            value = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("Ignoring corrupt cache entry", extra={"cache_key": key})
        else:
            metrics.cache_lookups.add(1, {"result": "hit"})
            return value
    metrics.cache_lookups.add(1, {"result": "miss"})
    return None


def set_cached_response(key: str, value: dict) -> bool:
    """
    Caches a JSON-serialisable response for CACHE_TTL_SECONDS (0 disables
    caching). Responses above CACHE_MAX_BYTES are skipped so one large
    result can't crowd out the cache (audit SEC-5).

    Returns:
        bool: whether the response was cached.
    """
    if settings.cache_ttl_seconds <= 0:
        return False
    payload = json.dumps(value)
    size = len(payload.encode())
    if size > settings.cache_max_bytes:
        logger.info("Response not cached: %d bytes > CACHE_MAX_BYTES", size)
        return False
    try:
        redis_client.setex(key, settings.cache_ttl_seconds, payload)
    except RedisError:
        logger.warning("Cache write failed; response not cached", exc_info=True)
        return False
    return True
