"""
Tests for the Redis sliding-window rate limiter (audit SEC-3).

Runs the real Lua script against ``fakeredis[lua]`` (see conftest), so
these exercise the actual check-and-record contract, not a stand-in.
"""

import time

import pytest
from ai_bi_analytics.core import rate_limiter
from ai_bi_analytics.core.config import settings
from ai_bi_analytics.core.rate_limiter import (
    KEY_PREFIX,
    check_rate_limit,
    client_identifier,
    enforce_rate_limit,
)
from fastapi import HTTPException

LIMIT = 5
WINDOW = 60


class DummyRequest:
    def __init__(self, client_ip="127.0.0.1", headers=None):
        self.client = type("Client", (), {"host": client_ip})() if client_ip else None
        self.headers = headers or {}


@pytest.fixture(autouse=True)
def default_limits(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_requests", LIMIT)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", WINDOW)


def test_allows_up_to_the_limit_then_rejects():
    request = DummyRequest()

    remaining = [enforce_rate_limit(request).remaining for _ in range(LIMIT)]

    assert remaining == [4, 3, 2, 1, 0]
    with pytest.raises(HTTPException) as exc:
        enforce_rate_limit(request)
    assert exc.value.status_code == 429


def test_rejection_carries_retry_after_and_limit_headers():
    request = DummyRequest()
    for _ in range(LIMIT):
        enforce_rate_limit(request)

    with pytest.raises(HTTPException) as exc:
        enforce_rate_limit(request)

    headers = exc.value.headers
    assert headers["X-RateLimit-Limit"] == str(LIMIT)
    assert headers["X-RateLimit-Remaining"] == "0"
    assert 1 <= int(headers["Retry-After"]) <= WINDOW


def test_rejected_requests_are_not_recorded(fake_redis):
    request = DummyRequest()
    for _ in range(LIMIT + 3):
        try:
            enforce_rate_limit(request)
        except HTTPException:
            pass

    assert fake_redis.zcard(KEY_PREFIX + "127.0.0.1") == LIMIT


def test_burst_within_one_millisecond_is_fully_counted(fake_redis):
    # Whole-second timestamps used as members made a burst collapse into
    # one entry. Every request must be recorded.
    results = [check_rate_limit("burst", 100, WINDOW) for _ in range(50)]

    assert all(r.allowed for r in results)
    assert fake_redis.zcard(KEY_PREFIX + "burst") == 50


def test_spoofed_forwarded_for_does_not_open_new_buckets():
    for i in range(LIMIT):
        enforce_rate_limit(DummyRequest(headers={"X-Forwarded-For": f"10.0.0.{i}"}))

    with pytest.raises(HTTPException):
        enforce_rate_limit(DummyRequest(headers={"X-Forwarded-For": "10.9.9.9"}))


def test_clients_have_independent_windows():
    for _ in range(LIMIT):
        enforce_rate_limit(DummyRequest("1.1.1.1"))

    assert enforce_rate_limit(DummyRequest("2.2.2.2")).allowed


def test_entries_older_than_the_window_are_pruned(fake_redis):
    key = KEY_PREFIX + "old"
    stale_ms = int(time.time() * 1000) - (WINDOW * 1000) - 1
    fake_redis.zadd(key, {f"{stale_ms}:{i}": stale_ms for i in range(LIMIT)})

    result = check_rate_limit("old", LIMIT, WINDOW)

    assert result.allowed
    assert fake_redis.zcard(key) == 1


def test_key_expires_with_the_window(fake_redis):
    check_rate_limit("ttl", LIMIT, WINDOW)

    assert 0 < fake_redis.pttl(KEY_PREFIX + "ttl") <= WINDOW * 1000


def test_client_identifier_falls_back_without_peer():
    assert client_identifier(DummyRequest(client_ip=None)) == "unknown"


def test_lua_script_loads_independently_of_working_directory(tmp_path, monkeypatch):
    rate_limiter._lua_source.cache_clear()
    monkeypatch.chdir(tmp_path)

    assert "ZREMRANGEBYSCORE" in rate_limiter._lua_source()


def test_query_endpoint_returns_rate_limit_headers_then_429(
    client, sample_products, mock_llm
):
    payload = {"question": "show all products"}

    first = client.post("/api/query", json=payload)
    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == str(LIMIT)
    assert first.headers["X-RateLimit-Remaining"] == str(LIMIT - 1)

    for _ in range(LIMIT - 1):
        client.post("/api/query", json=payload)

    blocked = client.post("/api/query", json=payload)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_error_responses_keep_rate_limit_headers(client, monkeypatch):
    """A request that passed the limiter but then failed (here: unsafe SQL)
    still reports the caller's remaining budget."""
    from ai_bi_analytics.services import nl_to_sql

    class DropLLM:
        def complete(self, prompt, system=None):
            return "DROP TABLE products"

    monkeypatch.setattr(nl_to_sql, "get_llm_client", lambda: DropLLM())

    response = client.post("/api/query", json={"question": "drop it"})

    assert response.status_code == 422
    assert response.headers["X-RateLimit-Limit"] == str(LIMIT)
    assert response.headers["X-RateLimit-Remaining"] == str(LIMIT - 1)
