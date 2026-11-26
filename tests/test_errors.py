"""
Error handling and request ids (audit SEC-4): typed errors map to the
right status with a client-safe body, internals never reach the client,
and every response can be correlated with the server log.
"""

import logging

import openai
import psycopg2
import pytest
from ai_bi_analytics.core.errors import (
    DependencyUnavailableError,
    LLMUnavailableError,
    QueryExecutionError,
    QueryTimeoutError,
    UnsafeSQLError,
)
from ai_bi_analytics.core.request_context import RequestIdLogFilter, get_request_id
from ai_bi_analytics.db.errors import translate_db_error
from ai_bi_analytics.main import create_app
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import DBAPIError, OperationalError

SECRET = "postgres-primary.internal:5432 password=hunter2"


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def raw_client(app):
    with TestClient(app) as client:
        yield client


def add_failing_route(app, exc):
    def boom():
        raise exc

    app.add_api_route("/boom", boom)


class FakePgError(Exception):
    def __init__(self, pgcode):
        super().__init__(SECRET)
        self.pgcode = pgcode


def db_error(orig, connection_invalidated=False):
    return DBAPIError(
        "SELECT secret", {}, orig, connection_invalidated=connection_invalidated
    )


# ---------------------------------------------------------------------------
# Request ids
# ---------------------------------------------------------------------------


def test_request_id_generated_and_echoed(raw_client):
    response = raw_client.get("/api/health")

    assert len(response.headers["x-request-id"]) == 32


def test_safe_incoming_request_id_is_kept(raw_client):
    response = raw_client.get("/api/health", headers={"X-Request-ID": "abc-123.x_y"})

    assert response.headers["x-request-id"] == "abc-123.x_y"


@pytest.mark.parametrize("bad", ["has space", "x" * 65, "../etc", "a;b"])
def test_unsafe_incoming_request_id_is_replaced(raw_client, bad):
    response = raw_client.get("/api/health", headers={"X-Request-ID": bad})

    assert response.headers["x-request-id"] != bad
    assert len(response.headers["x-request-id"]) == 32


def test_log_records_carry_request_id():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)

    assert RequestIdLogFilter().filter(record) is True
    assert record.request_id == get_request_id() == "-"


# ---------------------------------------------------------------------------
# Typed errors -> status + safe body
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc, status, code",
    [
        (UnsafeSQLError("Only SELECT statements are allowed."), 422, "unsafe_sql"),
        (QueryExecutionError(), 422, "query_failed"),
        (QueryTimeoutError(), 504, "query_timeout"),
        (LLMUnavailableError(), 502, "llm_unavailable"),
        (DependencyUnavailableError(), 503, "dependency_unavailable"),
    ],
)
def test_app_errors_map_to_status_and_body(app, exc, status, code):
    add_failing_route(app, exc)
    with TestClient(app) as client:
        response = client.get("/boom")

    body = response.json()
    assert response.status_code == status
    assert body["code"] == code
    assert body["detail"] == exc.public_message
    assert body["request_id"] == response.headers["x-request-id"]


def test_db_error_is_translated_and_not_leaked(app, caplog):
    add_failing_route(app, db_error(FakePgError("57014")))
    with TestClient(app) as client:
        response = client.get("/boom")

    assert response.status_code == 504
    assert response.json()["code"] == "query_timeout"
    assert "hunter2" not in response.text
    assert "SELECT secret" not in response.text
    # ...but the detail is in the server log for operators.
    assert "hunter2" in caplog.text


def test_redis_error_is_503_without_detail(app):
    add_failing_route(app, RedisConnectionError(SECRET))
    with TestClient(app) as client:
        response = client.get("/boom")

    assert response.status_code == 503
    assert "hunter2" not in response.text


def test_unhandled_error_is_generic_json_500_with_request_id(app, caplog):
    add_failing_route(app, RuntimeError(SECRET))
    with TestClient(app) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error.",
        "code": "internal_error",
        "request_id": response.headers["x-request-id"],
    }
    assert "hunter2" not in response.text
    assert "hunter2" in caplog.text


def test_error_after_response_started_propagates(app):
    def stream():
        yield b"partial"
        raise RuntimeError("mid-stream")

    app.add_api_route("/stream", lambda: StreamingResponse(stream()))
    with TestClient(app) as client, pytest.raises(RuntimeError, match="mid-stream"):
        client.get("/stream")


def test_client_errors_log_as_warning_not_error(app, caplog):
    add_failing_route(app, UnsafeSQLError("nope"))
    with TestClient(app) as client:
        client.get("/boom")

    records = [r for r in caplog.records if "unsafe_sql" in r.getMessage()]
    assert records and all(r.levelno == logging.WARNING for r in records)


# ---------------------------------------------------------------------------
# translate_db_error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pgcode, expected",
    [
        ("57014", QueryTimeoutError),
        ("25006", UnsafeSQLError),
        ("42501", UnsafeSQLError),
        ("08006", DependencyUnavailableError),
        ("53300", DependencyUnavailableError),
        ("57P01", DependencyUnavailableError),
        ("42703", QueryExecutionError),  # undefined column
        ("42P01", QueryExecutionError),  # undefined table
    ],
)
def test_translate_by_sqlstate(pgcode, expected):
    assert isinstance(translate_db_error(db_error(FakePgError(pgcode))), expected)


def test_translate_invalidated_connection():
    error = translate_db_error(db_error(FakePgError(None), connection_invalidated=True))

    assert isinstance(error, DependencyUnavailableError)


def test_translate_codeless_psycopg2_operational_error_as_unavailable():
    exc = OperationalError("connect", {}, psycopg2.OperationalError("refused"))

    assert isinstance(translate_db_error(exc), DependencyUnavailableError)


def test_translate_other_codeless_error_as_query_failure():
    # e.g. SQLite's "no such column"
    assert isinstance(
        translate_db_error(db_error(Exception("no such column"))), QueryExecutionError
    )


# ---------------------------------------------------------------------------
# LLM client error mapping
# ---------------------------------------------------------------------------


def make_openai_client(monkeypatch, *, raises=None, content="SELECT 1"):
    from ai_bi_analytics.core.config import settings
    from ai_bi_analytics.services import llm_client

    class Completions:
        def create(self, **_kwargs):
            if raises:
                raise raises
            message = type("M", (), {"content": content})()
            choice = type("C", (), {"message": message})()
            return type("R", (), {"choices": [choice]})()

    class FakeOpenAI:
        def __init__(self, api_key):
            self.chat = type("Chat", (), {"completions": Completions()})()

    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    return llm_client.OpenAILLMClient()


def test_provider_error_becomes_llm_unavailable(monkeypatch):
    import httpx

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    client = make_openai_client(
        monkeypatch, raises=openai.APIConnectionError(request=request)
    )

    with pytest.raises(LLMUnavailableError) as exc:
        client.complete("prompt")
    assert isinstance(exc.value.__cause__, openai.APIConnectionError)


@pytest.mark.parametrize("content", [None, ""])
def test_empty_completion_becomes_llm_unavailable(monkeypatch, content):
    client = make_openai_client(monkeypatch, content=content)

    with pytest.raises(LLMUnavailableError, match="no answer"):
        client.complete("prompt")
