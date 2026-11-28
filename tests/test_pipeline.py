"""
The query pipeline (audit ARCH-1), the explain flag and structured
answers (PERF-2, ARCH-3), and the schema cache (PERF-1).
"""

import logging

import pytest
from ai_bi_analytics.api.deps import get_llm
from ai_bi_analytics.services.llm_client import LLMClient
from ai_bi_analytics.services.schema_loader import QueryScope, SchemaProvider
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tests.fakes import FakeProvider

QUESTION = {"question": "show all products"}


def ask(client, **extra):
    response = client.post("/api/query", json={**QUESTION, **extra})
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Structured answers
# ---------------------------------------------------------------------------


def test_assumptions_are_returned(client, sample_products, fake_llm):
    fake_llm.answer_json(
        "SELECT name FROM products", ["products"], ["'all' means every row"]
    )

    body = ask(client)

    assert body["sql"].startswith("SELECT name FROM products")
    assert body["assumptions"] == ["'all' means every row"]


def test_token_usage_is_logged(client, sample_products, caplog):
    with caplog.at_level(logging.INFO, logger="ai_bi_analytics.services.pipeline"):
        ask(client)

    record = next(r for r in caplog.records if r.getMessage() == "Query executed")
    # Two calls of FakeProvider's LLMUsage(10, 5).
    assert (record.llm_input_tokens, record.llm_output_tokens) == (20, 10)


def test_llm_can_be_replaced_with_dependency_overrides(app, client, sample_products):
    other = FakeProvider(explanation="From the override.")
    app.dependency_overrides[get_llm] = lambda: LLMClient(other, app.state.settings)

    assert ask(client)["explanation"] == "From the override."
    assert len(other.calls) == 2


# ---------------------------------------------------------------------------
# explain flag
# ---------------------------------------------------------------------------


def test_explain_false_skips_the_second_llm_call(client, sample_products, fake_llm):
    body = ask(client, explain=False)

    assert body["explanation"] is None
    assert len(fake_llm.sql_calls) == 1 and fake_llm.explain_calls == []


def test_cached_answer_without_explanation_is_explained_once(
    client, sample_products, fake_llm
):
    ask(client, explain=False)

    first = ask(client)
    second = ask(client)

    assert first["explanation"] == second["explanation"] == "Fake explanation."
    # One SQL generation in total; one explanation, then the upgraded entry.
    assert len(fake_llm.sql_calls) == 1
    assert len(fake_llm.explain_calls) == 1


def test_explain_false_on_a_cached_explained_answer(client, sample_products, fake_llm):
    ask(client)

    body = ask(client, explain=False)

    assert body["explanation"] is None
    assert len(fake_llm.calls) == 2  # nothing new


def test_cache_entry_with_unexpected_shape_is_a_miss(
    client, sample_products, fake_llm, fake_redis, caplog
):
    ask(client)
    (key,) = fake_redis.keys("query_cache:*")
    fake_redis.set(key, '{"sql": "SELECT 1"}')

    ask(client)

    assert len(fake_llm.sql_calls) == 2
    assert "unexpected shape" in caplog.text


# ---------------------------------------------------------------------------
# Schema cache
# ---------------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture()
def counting_db(monkeypatch):
    """A SQLite session whose introspection calls are counted."""
    from ai_bi_analytics.services import schema_loader

    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE products (id INTEGER, name TEXT)"))
    calls = []
    real = schema_loader.load_query_scope

    def counting(db, cfg):
        calls.append(1)
        return real(db, cfg)

    monkeypatch.setattr(schema_loader, "load_query_scope", counting)
    with Session(engine) as session:
        yield session, calls
    engine.dispose()


def test_scope_is_reused_within_ttl_then_reloaded(counting_db, settings, monkeypatch):
    db, calls = counting_db
    monkeypatch.setattr(settings, "schema_cache_ttl_seconds", 60)
    clock = Clock()
    provider = SchemaProvider(settings, clock=clock)

    first = provider.get(db)
    clock.now += 59
    assert provider.get(db) is first
    assert len(calls) == 1

    clock.now += 2
    assert provider.get(db) == first
    assert len(calls) == 2


def test_zero_ttl_introspects_every_time(counting_db, settings, monkeypatch):
    db, calls = counting_db
    monkeypatch.setattr(settings, "schema_cache_ttl_seconds", 0)
    provider = SchemaProvider(settings)

    provider.get(db)
    provider.get(db)

    assert len(calls) == 2


def test_invalidate_forces_reload(counting_db, settings):
    db, calls = counting_db
    provider = SchemaProvider(settings)

    provider.get(db)
    provider.invalidate()
    provider.get(db)

    assert len(calls) == 2


def test_cache_hits_skip_introspection(client, sample_products, resources, monkeypatch):
    ask(client)
    calls = []
    monkeypatch.setattr(
        resources.schema, "get", lambda db: calls.append(1) or real_scope
    )
    real_scope = SchemaProvider(resources.schema._cfg).get(resources.session_factory())

    ask(client)

    assert calls == [1]  # served from the in-process scope, then the cache


def scope(**overrides) -> QueryScope:
    base = {
        "schema": "public",
        "columns": {"products": [("id", "INTEGER"), ("name", "TEXT")]},
        "redacted": {},
    }
    return QueryScope(**{**base, **overrides})


@pytest.mark.parametrize(
    "changed",
    [
        {"schema": "sales"},
        {"columns": {"products": [("id", "INTEGER")]}},
        {"columns": {"products": [("id", "BIGINT"), ("name", "TEXT")]}},
        {"redacted": {"products": frozenset({"cost"})}},
    ],
)
def test_fingerprint_tracks_everything_that_changes_an_answer(changed):
    assert scope().fingerprint == scope().fingerprint
    assert scope(**changed).fingerprint != scope().fingerprint
