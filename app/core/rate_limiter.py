"""
Redis-backed rate limiting.

Implements fixed-window rate limiting using Redis.
"""

from fastapi import HTTPException, Request

from app.core.redis_client import redis_client

RATE_LIMIT = 5
WINDOW_SECONDS = 60


def enforce_rate_limit(request: Request) -> None:
    """
    Enforces rate limiting per client IP.

    Args:
        request (Request): FastAPI request object.

    Raises:
        HTTPException: If rate limit exceeded.
    """
    client_ip = request.client.host
    key = f"rate_limit:{client_ip}"

    current = redis_client.get(key)

    if current and int(current) >= RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
        )

    pipe = redis_client.pipeline()
    pipe.incr(key, 1)
    pipe.expire(key, WINDOW_SECONDS)
    pipe.execute()
