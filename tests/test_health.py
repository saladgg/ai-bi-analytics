"""
Health endpoints and lifecycle (audit OPS-3).
"""

import pytest
from ai_bi_analytics.core import redis_client as redis_module
from ai_bi_analytics.db.session import build_engine_kwargs
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


@pytest.fixture()
def raw_client(raw_app):
    # No auth/DB overrides: health must work for an anonymous caller.
    with TestClient(raw_app) as client:
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


def test_readiness_503_when_database_down(raw_client, resources, monkeypatch, caplog):
    def refuse(*_args, **_kwargs):
        raise OperationalError("connect", {}, Exception("db.internal refused"))

    monkeypatch.setattr(resources.engine, "connect", refuse)

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


def test_shutdown_closes_every_client(raw_app, resources, fake_llm, monkeypatch):
    calls = []
    monkeypatch.setattr(resources.engine, "dispose", lambda: calls.append("db"))
    monkeypatch.setattr(resources.redis, "close", lambda: calls.append("redis"))

    with TestClient(raw_app):
        assert calls == [] and not fake_llm.closed

    assert calls == ["redis", "db"]
    assert fake_llm.closed


def test_one_failing_close_does_not_stop_the_others(resources, monkeypatch, caplog):
    calls = []

    def broken():
        raise RuntimeError("socket already gone")

    monkeypatch.setattr(resources.redis, "close", broken)
    monkeypatch.setattr(resources.engine, "dispose", lambda: calls.append("db"))

    resources.close()

    assert calls == ["db"]
    assert "Closing the redis client failed" in caplog.text


def test_clients_close_when_startup_fails(settings, resources, monkeypatch):
    from ai_bi_analytics import main

    closed = []
    monkeypatch.setattr(resources, "close", lambda: closed.append(True))

    def unsafe(*_args):
        raise RuntimeError("privileged role")

    monkeypatch.setattr(main, "assert_database_role_is_safe", unsafe)
    app = main.create_app(settings, resources_factory=lambda _cfg: resources)

    with pytest.raises(RuntimeError, match="privileged role"), TestClient(app):
        pass  # pragma: no cover - startup raises first

    assert closed == [True]


def test_postgres_connections_have_connect_timeout():
    kwargs = build_engine_kwargs(
        "postgresql://u:p@h/db", 1, 1, connect_timeout_seconds=7
    )

    assert kwargs["connect_args"]["connect_timeout"] == 7


def test_redis_client_has_socket_timeouts():
    client = redis_module.build_redis_client("redis://localhost:6399/0", 1.5)
    kwargs = client.connection_pool.connection_kwargs

    assert kwargs["socket_timeout"] == 1.5
    assert kwargs["socket_connect_timeout"] == 1.5
