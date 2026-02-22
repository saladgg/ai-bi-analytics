"""
In-memory caching layer for AI responses.
"""

import hashlib

from cachetools import TTLCache

# 100 entries, 5-minute TTL
query_cache = TTLCache(maxsize=100, ttl=300)


def generate_cache_key(question: str) -> str:
    """
    Generates deterministic hash key for question.
    """
    return hashlib.sha256(question.encode()).hexdigest()
