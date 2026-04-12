"""
Unit tests for caching layer.
"""

from ai_bi_analytics.services.cache import generate_cache_key, get_cached_response, set_cached_response


def test_cache_key_stable():
    q = "show products"
    schema = "products(id, name)"

    key1 = generate_cache_key(q + schema)
    key2 = generate_cache_key(q + schema)

    assert key1 == key2


def test_cache_key_differs():
    k1 = generate_cache_key("q1")
    k2 = generate_cache_key("q2")

    assert k1 != k2


def test_get_cached_response_none_when_key_missing():
    assert get_cached_response("query_cache:missing") is None


def test_cached_response_round_trip():
    key = generate_cache_key("q")
    value = {"sql": "SELECT 1", "result": [], "explanation": "test"}

    set_cached_response(key, value)
    assert get_cached_response(key) == value
