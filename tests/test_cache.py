"""
Unit tests for caching layer.
"""

import pytest
from ai_bi_analytics.services.cache import ResultCache, generate_cache_key


@pytest.fixture()
def cache(fake_redis, settings):
    return ResultCache(fake_redis, settings)


def test_cache_key_stable():
    q = "show products"
    schema = "products(id, name)"

    key1 = generate_cache_key(q, schema)
    key2 = generate_cache_key(q, schema)

    assert key1 == key2


def test_cache_key_differs():
    k1 = generate_cache_key("q1")
    k2 = generate_cache_key("q2")

    assert k1 != k2


def test_key_covers_scope_model_and_row_cap(cache, settings, monkeypatch):
    base = cache.key("q", "fp1")

    assert cache.key("q", "fp2") != base
    monkeypatch.setattr(settings, "llm_sql_model", "another-model")
    assert cache.key("q", "fp1") != base
    monkeypatch.undo()
    monkeypatch.setattr(settings, "max_result_rows", settings.max_result_rows + 1)
    assert cache.key("q", "fp1") != base


def test_get_cached_response_none_when_key_missing(cache):
    assert cache.get("query_cache:missing") is None


def test_cached_response_round_trip(cache):
    key = generate_cache_key("q")
    value = {"sql": "SELECT 1", "result": [], "explanation": "test"}

    cache.set(key, value)
    assert cache.get(key) == value
