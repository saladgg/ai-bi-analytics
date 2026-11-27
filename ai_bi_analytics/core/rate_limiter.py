"""
Redis sliding-window rate limiter (atomic Lua script).

Audit SEC-3: the previous version could never reject a request (the
script returned the limit itself when full, and the caller only rejected
counts *above* the limit), counted same-second requests once, and keyed
on a client-supplied ``X-Forwarded-For`` header.
"""

import logging
import math
import uuid
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

from fastapi import HTTPException, Request, status
from redis.exceptions import RedisError

from ai_bi_analytics.core import metrics
from ai_bi_analytics.core.config import settings
from ai_bi_analytics.core.redis_client import redis_client

KEY_PREFIX = "rate_limit:"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int

    def headers(self) -> dict[str, str]:
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
        }
        if not self.allowed:
            headers["Retry-After"] = str(self.retry_after_seconds)
        return headers


@lru_cache(maxsize=1)
def _lua_source() -> str:
    # Resolved from the installed package, not the working directory.
    return (
        files("ai_bi_analytics.core")
        .joinpath("lua", "sliding_window_rate_limit.lua")
        .read_text()
    )


def get_rate_limit_script():
    # register_script only hashes the source client-side; no round trip.
    return redis_client.register_script(_lua_source())


def client_identifier(request: Request) -> str:
    """
    The rate-limit bucket for a request.

    Uses the socket peer address. Behind a reverse proxy, uvicorn rewrites
    it from ``X-Forwarded-For`` only when the proxy is trusted
    (``FORWARDED_ALLOW_IPS``), so clients can't pick their own bucket.
    Never read ``X-Forwarded-For`` here directly.
    """
    return request.client.host if request.client else "unknown"


def check_rate_limit(
    identifier: str,
    limit: int,
    window_seconds: int,
) -> RateLimitResult:
    allowed, count, retry_after_ms = get_rate_limit_script()(
        keys=[KEY_PREFIX + identifier],
        args=[window_seconds * 1000, limit, uuid.uuid4().hex],
    )
    return RateLimitResult(
        allowed=bool(int(allowed)),
        limit=limit,
        remaining=max(limit - int(count), 0),
        retry_after_seconds=max(math.ceil(int(retry_after_ms) / 1000), 1),
    )


def enforce_rate_limit(
    request: Request, identity: str | None = None
) -> RateLimitResult:
    """
    Records the request against the caller's window.

    Args:
        identity: Bucket for an authenticated caller (e.g.
            ``client:<id>``). Without one, the client address is used.

    Returns:
        RateLimitResult: for setting ``X-RateLimit-*`` response headers.

    Raises:
        HTTPException: 429 with ``Retry-After`` when the window is full.
    """
    try:
        result = check_rate_limit(
            identity or client_identifier(request),
            settings.rate_limit_requests,
            settings.rate_limit_window_seconds,
        )
    except RedisError:
        # Audit PERF-3: an explicit policy rather than an accident. Fail
        # closed (default) re-raises, which the RedisError handler turns
        # into a 503; fail open serves the request unthrottled.
        if not settings.rate_limit_fail_open:
            raise
        logger.warning("Rate limiter unavailable; failing open", exc_info=True)
        metrics.rate_limit_fail_open.add(1)
        return RateLimitResult(
            allowed=True,
            limit=settings.rate_limit_requests,
            remaining=settings.rate_limit_requests,
            retry_after_seconds=1,
        )
    if not result.allowed:
        metrics.rate_limit_denials.add(1)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers=result.headers(),
        )
    return result
