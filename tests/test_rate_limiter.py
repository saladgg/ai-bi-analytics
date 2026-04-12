"""
Tests for Redis-based sliding window rate limiter.
"""

import time
import importlib
import pytest
from fastapi import Request

from ai_bi_analytics.core.rate_limiter import enforce_rate_limit


class DummyRequest:
    """
    Minimal request mock compatible with FastAPI Request.
    """

    def __init__(self, client_ip="127.0.0.1"):
        self.client = type("Client", (), {"host": client_ip})
        self.headers = {}  



def test_rate_limit_allows_requests(monkeypatch):
    """
    Should allow requests under limit.
    """

    calls = []

    def fake_redis_eval(*args, **kwargs):
        calls.append(1)
        return 0  # under limit

    monkeypatch.setattr(
        "ai_bi_analytics.core.rate_limiter.redis_client.eval",
        fake_redis_eval,
    )

    request = DummyRequest()

    for _ in range(3):
        enforce_rate_limit(request)


def test_rate_limit_blocks():
    request = DummyRequest()

    # exceed limit
    for _ in range(6):  # RATE_LIMIT = 5
        try:
            enforce_rate_limit(request)
        except Exception:
            return  # success

    pytest.fail("Rate limit did not trigger")


def test_get_rate_limit_script_registers_lua(monkeypatch):
    # The autouse fixture in tests/conftest.py replaces `get_rate_limit_script`.
    # Reloading ensures we execute the real implementation for coverage.
    import ai_bi_analytics.core.rate_limiter as rate_limiter

    rate_limiter = importlib.reload(rate_limiter)

    captured = {"lua_text": None}

    def fake_register_script(lua_text: str):
        captured["lua_text"] = lua_text

        def fake_script(*args, **kwargs):
            return 123

        return fake_script

    monkeypatch.setattr(
        rate_limiter.redis_client,
        "register_script",
        fake_register_script,
    )

    script_fn = rate_limiter.get_rate_limit_script()
    assert captured["lua_text"] is not None
    assert "ZREMRANGEBYSCORE" in captured["lua_text"]
    assert callable(script_fn)

