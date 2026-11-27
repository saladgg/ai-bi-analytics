"""
Health endpoints and lifecycle (audit OPS-3).
"""

import pytest
from ai_bi_analytics.core import redis_client as redis_module
from ai_bi_analytics.db import session as db_session
from ai_bi_analytics.db.session import CONNECT_TIMEOUT_SECONDS, build_engine_kwargs
from ai_bi_analytics.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


@pytest.fixture()
def raw_client():
    # No auth/DB overrides: health must work for an anonymous caller.
    with TestClient(create_app()) as client:
        yield client


@pytest.mark.parametrize("path", ["/api/health", "/api/health/live"])
def test_liveness(raw_client, path):
    response = raw_client.get(path)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_ok_when_dependencies_answer(raw_client):
    response = raw_client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "redis": "ok"},
    }


def test_readiness_503_when_database_down(raw_client, monkeypatch, caplog):
    def refuse(*_args, **_kwargs):
        raise OperationalError("connect", {}, Exception("db.internal refused"))

    monkeypatch.setattr(db_session.engine, "connect", refuse)

    response = raw_client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "error", "redis": "ok"},
    }
    assert "db.internal" not in response.text
    assert "db.internal" in caplog.text


def test_readiness_503_when_redis_down(raw_client, fake_redis, monkeypatch):
    def down():
        raise ConnectionError("redis.internal:6379 unreachable")

    monkeypatch.setattr(fake_redis, "ping", down)

    response = raw_client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "redis": "error"}
    assert "redis.internal" not in response.text


def test_health_is_not_rate_limited(raw_client):
    for _ in range(20):
        assert raw_client.get("/api/health/ready").status_code == 200


def test_shutdown_disposes_pool_and_closes_redis(monkeypatch, fake_redis):
    calls = []
    monkeypatch.setattr(db_session.engine, "dispose", lambda: calls.append("db"))
    monkeypatch.setattr(fake_redis, "close", lambda: calls.append("redis"))

    with TestClient(create_app()):
        assert calls == []

    assert calls == ["db", "redis"]


def test_postgres_connections_have_connect_timeout():
    kwargs = build_engine_kwargs("postgresql://u:p@h/db", 1, 1)

    assert kwargs["connect_args"]["connect_timeout"] == CONNECT_TIMEOUT_SECONDS


def test_redis_client_has_socket_timeouts():
    client = redis_module.build_redis_client("redis://localhost:6399/0")
    kwargs = client.connection_pool.connection_kwargs

    assert kwargs["socket_timeout"] == redis_module.SOCKET_TIMEOUT_SECONDS
    assert kwargs["socket_connect_timeout"] == redis_module.SOCKET_TIMEOUT_SECONDS
