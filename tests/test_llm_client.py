"""
LLM layer (audit ARCH-3, PERF-2): provider registry, the OpenAI provider's
client lifecycle, and the task-level client's structured output.
"""

import json

import pytest
from ai_bi_analytics.core.errors import LLMUnavailableError
from ai_bi_analytics.services import llm_client
from ai_bi_analytics.services.llm_client import (
    LLMClient,
    LLMUsage,
    OpenAIProvider,
    build_provider,
    register_provider,
    registered_providers,
)
from ai_bi_analytics.services.nl_to_sql import (
    MAX_ASSUMPTION_LENGTH,
    MAX_ASSUMPTIONS,
    SQLAnswer,
    parse_sql_response,
)
from ai_bi_analytics.services.query_executor import QueryResult

from tests.fakes import FakeProvider, fake_openai_provider

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_openai_is_registered_and_built_by_default(monkeypatch, settings):
    fake_openai_provider(monkeypatch, settings)

    assert "openai" in registered_providers()
    assert isinstance(build_provider(settings), OpenAIProvider)


def test_custom_provider_can_be_registered(monkeypatch, settings):
    monkeypatch.setattr(llm_client, "_PROVIDERS", dict(llm_client._PROVIDERS))
    fake = FakeProvider()
    register_provider("fake")(lambda _cfg: fake)
    monkeypatch.setattr(settings, "llm_provider", "fake")

    assert build_provider(settings) is fake


def test_unknown_provider_names_the_registered_ones(monkeypatch, settings):
    monkeypatch.setattr(settings, "llm_provider", "some-unknown-provider")

    with pytest.raises(ValueError, match="'some-unknown-provider'; registered: openai"):
        build_provider(settings)


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------


def test_one_sdk_client_with_timeout_and_retries(monkeypatch, settings):
    monkeypatch.setattr(settings, "llm_timeout_seconds", 12.5)
    monkeypatch.setattr(settings, "llm_max_retries", 3)

    provider = fake_openai_provider(monkeypatch, settings)

    assert provider._client.kwargs == {  # type: ignore[union-attr]
        "api_key": "sk-test",
        "timeout": 12.5,
        "max_retries": 3,
    }


def test_close_closes_the_sdk_client(monkeypatch, settings):
    provider = fake_openai_provider(monkeypatch, settings)
    client = provider._client

    provider.close()

    assert client.closed  # type: ignore[union-attr]


def test_missing_key_starts_but_fails_requests(monkeypatch, settings, caplog):
    monkeypatch.setattr(settings, "openai_api_key", None)

    provider = OpenAIProvider(settings)
    provider.close()  # nothing to close

    assert "OPENAI_API_KEY is not set" in caplog.text
    with pytest.raises(LLMUnavailableError, match="not configured"):
        provider.complete(system="s", prompt="p", model="m", max_tokens=1)


def test_completion_is_stripped_and_carries_usage(monkeypatch, settings):
    provider = fake_openai_provider(monkeypatch, settings, content="  hi \n")

    completion = provider.complete(system="s", prompt="p", model="m", max_tokens=5)

    assert completion.text == "hi"
    assert completion.usage == LLMUsage(120, 30)


def test_hitting_max_tokens_is_logged(monkeypatch, settings, caplog):
    provider = fake_openai_provider(monkeypatch, settings, finish_reason="length")

    provider.complete(system="s", prompt="p", model="m", max_tokens=5)

    assert "hit max_tokens" in caplog.text


def test_usage_adds_up():
    assert LLMUsage(1, 2) + LLMUsage(10, 20) == LLMUsage(11, 22)


# ---------------------------------------------------------------------------
# Structured SQL answers
# ---------------------------------------------------------------------------


def test_json_answer_is_parsed():
    answer = parse_sql_response(
        json.dumps(
            {
                "sql": " SELECT 1 ",
                "tables_used": ["products", 7, " "],
                "assumptions": ["'top' means by revenue"],
            }
        )
    )

    assert answer == SQLAnswer(
        sql="SELECT 1",
        tables_used=("products",),
        assumptions=("'top' means by revenue",),
    )


@pytest.mark.parametrize(
    "text",
    [
        "SELECT name FROM products",
        '["SELECT 1"]',
        '{"query": "SELECT 1"}',
        '{"sql": 5}',
    ],
)
def test_non_conforming_answer_is_treated_as_sql(text):
    assert parse_sql_response(text) == SQLAnswer(sql=text)


def test_assumptions_are_bounded():
    answer = parse_sql_response(
        json.dumps(
            {
                "sql": "SELECT 1",
                "tables_used": "not a list",
                "assumptions": ["x" * 1000] * 20,
            }
        )
    )

    assert answer.tables_used == ()
    assert len(answer.assumptions) == MAX_ASSUMPTIONS
    assert all(len(a) == MAX_ASSUMPTION_LENGTH for a in answer.assumptions)


def test_generate_sql_returns_parsed_answer_and_usage(settings):
    provider = FakeProvider()
    provider.answer_json("SELECT 1", ["t"], ["a"])

    generated = LLMClient(provider, settings).generate_sql("q", "t(a int)\n")

    assert (generated.sql, generated.tables_used, generated.assumptions) == (
        "SELECT 1",
        ("t",),
        ("a",),
    )
    assert generated.usage == LLMUsage(10, 5)


def test_explain_returns_text_and_usage(settings):
    explained = LLMClient(FakeProvider(), settings).explain(
        "q", "SELECT 1", QueryResult([])
    )

    assert explained.text == "Fake explanation."
    assert explained.usage == LLMUsage(10, 5)


def test_client_close_closes_provider(settings):
    provider = FakeProvider()

    LLMClient(provider, settings).close()

    assert provider.closed
