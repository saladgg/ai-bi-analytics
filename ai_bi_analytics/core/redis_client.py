"""
Redis client construction.

One client (with its connection pool) per process, built in the app's
lifespan (audit ARCH-2) and used for rate limiting and response caching.
"""

import redis

# Bounded timeouts (audit OPS-3): without them an unreachable Redis hangs
# every request (rate limiter, cache) and the readiness probe on the OS TCP
# timeout instead of failing fast with a 503.
DEFAULT_SOCKET_TIMEOUT_SECONDS = 2.0


def build_redis_client(
    url: str, socket_timeout_seconds: float = DEFAULT_SOCKET_TIMEOUT_SECONDS
) -> redis.Redis:
    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=socket_timeout_seconds,
        socket_timeout=socket_timeout_seconds,
        health_check_interval=30,
    )
