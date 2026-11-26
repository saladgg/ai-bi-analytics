"""
Redis-backed response caching layer.
"""

import hashlib
import json
import logging

from ai_bi_analytics.core.config import settings
from ai_bi_analytics.core.redis_client import redis_client

logger = logging.getLogger(__name__)

CACHE_TTL = 300  # 5 minutes


def generate_cache_key(question: str) -> str:
    return "query_cache:" + hashlib.sha256(question.encode()).hexdigest()


def get_cached_response(key: str):
    data = redis_client.get(key)
    if data:
        return json.loads(data)
    return None


def set_cached_response(key: str, value: dict) -> bool:
    """
    Caches a JSON-serialisable response. Responses above CACHE_MAX_BYTES
    are skipped so one large result can't crowd out the cache (audit SEC-5).

    Returns:
        bool: whether the response was cached.
    """
    payload = json.dumps(value)
    size = len(payload.encode())
    if size > settings.cache_max_bytes:
        logger.info("Response not cached: %d bytes > CACHE_MAX_BYTES", size)
        return False
    redis_client.setex(key, CACHE_TTL, payload)
    return True
