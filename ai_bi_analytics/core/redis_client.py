"""
Redis client configuration.

Provides centralized Redis connection used for:
- Rate limiting
- Response caching
"""

import os

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


# Bounded timeouts (audit OPS-3): without them an unreachable Redis hangs
# every request (rate limiter, cache) and the readiness probe on the OS TCP
# timeout instead of failing fast with a 503.
SOCKET_TIMEOUT_SECONDS = 2


def build_redis_client(url: str) -> redis.Redis:
    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=SOCKET_TIMEOUT_SECONDS,
        socket_timeout=SOCKET_TIMEOUT_SECONDS,
        health_check_interval=30,
    )


redis_client = build_redis_client(REDIS_URL)
