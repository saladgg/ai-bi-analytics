"""
Redis-backed response caching layer.
"""

import hashlib
import json

from app.core.redis_client import redis_client

CACHE_TTL = 300  # 5 minutes


def generate_cache_key(question: str) -> str:
    return "query_cache:" + hashlib.sha256(question.encode()).hexdigest()


def get_cached_response(key: str):
    data = redis_client.get(key)
    if data:
        return json.loads(data)
    return None


def set_cached_response(key: str, value: dict):
    redis_client.setex(
        key,
        CACHE_TTL,
        json.dumps(value),
    )
