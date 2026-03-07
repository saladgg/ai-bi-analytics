"""
Redis sliding-window rate limiter using Lua script.
"""

import time

from fastapi import HTTPException, Request

from app.core.redis_client import redis_client

RATE_LIMIT = 5
WINDOW_SECONDS = 60


with open("app/core/lua/sliding_window_rate_limit.lua") as f:
    RATE_LIMIT_SCRIPT = redis_client.register_script(f.read())


def enforce_rate_limit(request: Request) -> None:
    """
    Enforces rate limit using Redis Lua script.
    """

    client_ip = request.headers.get(
        "X-Forwarded-For",
        request.client.host,
    )

    key = f"rate_limit:{client_ip}"

    now = int(time.time())

    request_count = RATE_LIMIT_SCRIPT(
        keys=[key],
        args=[now, WINDOW_SECONDS, RATE_LIMIT],
    )

    if int(request_count) > RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
        )
