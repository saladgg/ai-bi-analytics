"""
Cache and rate-limiter behaviour when Redis misbehaves (audit PERF-3).
"""

import pytest
from ai_bi_analytics.services.cache import (
    ResultCache,
    generate_cache_key,
    normalise_question,
)
from redis.exceptions import ConnectionError as RedisConnectionError


def redis_down(*_args, **_kwargs):
    raise RedisConnectionError("redis.internal:6379 unreachable")


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "variant",
    ["Top 3 products", "top 3 products", "  TOP   3\tproducts ", "Top 3\nProducts"],
)
def test_trivial_question_variants_share_a_key(variant):
    assert generate_cache_key(variant, "schema") == generate_cache_key(
        "top 3 products", "schema"
    )


def test_schema_changes_the_key():
    assert generate_cache_key("q", "a(x INT)\n") != generate_cache_key(
        "q", "b(x INT)\n"
    )


def test_question_and_schema_cannot_collide_by_concatenation():
    assert generate_cache_key("ab", "c") != generate_cache_key("a", "bc")


def test_normalise_question():
    assert normalise_question("  Hello\tWORLD \n") == "hello world"


# ---------------------------------------------------------------------------
# Cache fails open
# ---------------------------------------------------------------------------


@pytest.fixture()
def cache(fake_redis, settings):
    return ResultCache(fake_redis, settings)


def test_read_error_is_a_miss(cache, fake_redis, monkeypatch, caplog):
    monkeypatch.setattr(fake_redis, "get", redis_down)

    assert cache.get("query_cache:x") is None
    assert "Cache read failed" in caplog.text


def test_write_error_is_not_fatal(cache, fake_redis, monkeypatch, caplog):
    monkeypatch.setattr(fake_redis, "setex", redis_down)

    assert cache.set("query_cache:x", {"a": 1}) is False
    assert "Cache write failed" in caplog.text


def test_corrupt_entry_is_a_miss(cache, fake_redis, caplog):
    fake_redis.set("query_cache:bad", "{not json")

    assert cache.get("query_cache:bad") is None
    assert "corrupt cache entry" in caplog.text


def test_non_object_entry_is_a_miss(cache, fake_redis, caplog):
    fake_redis.set("query_cache:list", "[1, 2]")

    assert cache.get("query_cache:list") is None
    assert "corrupt cache entry" in caplog.text


def test_ttl_is_configurable(cache, settings, fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "cache_ttl_seconds", 42)

    assert cache.set("query_cache:t", {"a": 1}) is True
    # TTL rounds down, so a just-set key can already read 41.
    assert 40 <= fake_redis.ttl("query_cache:t") <= 42


def test_zero_ttl_disables_caching(cache, settings, fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "cache_ttl_seconds", 0)

    assert cache.set("query_cache:t", {"a": 1}) is False
    assert fake_redis.get("query_cache:t") is None


def test_query_succeeds_with_cache_down(
    client, sample_products, fake_redis, monkeypatch
):
    # Only the cache is down here: limiter commands still work.
    monkeypatch.setattr(fake_redis, "get", redis_down)
    monkeypatch.setattr(fake_redis, "setex", redis_down)

    response = client.post("/api/query", json={"question": "show products"})

    assert response.status_code == 200
    assert response.json()["row_count"] == 3


# ---------------------------------------------------------------------------
# Rate limiter policy
# ---------------------------------------------------------------------------


def test_limiter_fails_closed_by_default(client, fake_redis, monkeypatch):
    monkeypatch.setattr(fake_redis, "evalsha", redis_down)
    monkeypatch.setattr(fake_redis, "eval", redis_down)

    response = client.post("/api/query", json={"question": "show products"})

    assert response.status_code == 503
    assert response.json()["code"] == "dependency_unavailable"
    assert "redis.internal" not in response.text


def test_limiter_can_fail_open(
    client, sample_products, settings, fake_redis, monkeypatch, caplog
):
    monkeypatch.setattr(settings, "rate_limit_fail_open", True)
    monkeypatch.setattr(fake_redis, "evalsha", redis_down)
    monkeypatch.setattr(fake_redis, "eval", redis_down)

    response = client.post("/api/query", json={"question": "show products"})

    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == str(settings.rate_limit_requests)
    assert "failing open" in caplog.text
