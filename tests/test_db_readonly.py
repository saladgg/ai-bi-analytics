"""
Unit tests for database-layer read-only enforcement (audit SEC-2).

The Postgres behaviour itself is exercised end to end in
tests/integration/test_postgres_readonly.py.
"""

import pytest
from ai_bi_analytics.db import session as session_mod
from ai_bi_analytics.db.session import (
    UnsafeDatabaseRoleError,
    assert_database_role_is_safe,
    build_engine_kwargs,
)
from ai_bi_analytics.services.query_executor import execute_query

PG_URL = "postgresql+psycopg2://u:p@localhost:5432/db"


def test_postgres_engine_is_read_only_with_timeouts():
    kwargs = build_engine_kwargs(PG_URL, 1234, 5678)

    options = kwargs["connect_args"]["options"]
    assert "-c default_transaction_read_only=on" in options
    assert "-c statement_timeout=1234" in options
    assert "-c idle_in_transaction_session_timeout=5678" in options
    assert kwargs["pool_pre_ping"] is True


def test_non_postgres_engine_gets_no_pg_options():
    kwargs = build_engine_kwargs("sqlite:///./x.db", 1, 1)

    assert "connect_args" not in kwargs


# ---------------------------------------------------------------------------
# assert_database_role_is_safe
# ---------------------------------------------------------------------------


class FakeResult:
    def __init__(self, row):
        self._row = row

    def one(self):
        return self._row


class FakeConnection:
    def __init__(self, row=None, error=None):
        self._row = row
        self._error = error

    def __enter__(self):
        if self._error:
            raise self._error
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, _stmt):
        return FakeResult(self._row)


class FakeEngine:
    def __init__(self, dialect="postgresql", row=None, error=None):
        self.dialect = type("Dialect", (), {"name": dialect})()
        self._conn = FakeConnection(row, error)

    def connect(self):
        return self._conn


SAFE_ROW = (False, False, False, False)
SUPERUSER_ROW = (True, False, False, False)


def test_role_check_skips_non_postgres():
    assert_database_role_is_safe(FakeEngine(dialect="sqlite"), "production")


def test_role_check_passes_for_unprivileged_role():
    assert_database_role_is_safe(FakeEngine(row=SAFE_ROW), "production")


@pytest.mark.parametrize(
    "row, privilege",
    [
        ((True, False, False, False), "SUPERUSER"),
        ((False, True, False, False), "CREATEROLE"),
        ((False, False, True, False), "CREATEDB"),
        ((False, False, False, True), "BYPASSRLS"),
    ],
)
def test_role_check_refuses_privileged_role_outside_dev(row, privilege):
    with pytest.raises(UnsafeDatabaseRoleError, match=privilege):
        assert_database_role_is_safe(FakeEngine(row=row), "production")


def test_role_check_only_warns_in_development(caplog):
    assert_database_role_is_safe(FakeEngine(row=SUPERUSER_ROW), "development")

    assert "SUPERUSER" in caplog.text


def test_role_check_fails_closed_when_unverifiable_outside_dev():
    engine = FakeEngine(error=ConnectionError("db down"))

    with pytest.raises(UnsafeDatabaseRoleError, match="Could not verify"):
        assert_database_role_is_safe(engine, "staging")


def test_role_check_warns_when_unverifiable_in_dev(caplog):
    assert_database_role_is_safe(
        FakeEngine(error=ConnectionError("db down")), "development"
    )

    assert "Could not verify" in caplog.text


def test_lifespan_runs_role_check(monkeypatch):
    import ai_bi_analytics.main as main_mod
    from fastapi.testclient import TestClient

    calls = []
    monkeypatch.setattr(
        main_mod,
        "assert_database_role_is_safe",
        lambda engine, env: calls.append((engine, env)),
    )

    with TestClient(main_mod.create_app()):
        pass

    assert calls == [(session_mod.engine, main_mod.settings.env)]


# ---------------------------------------------------------------------------
# execute_query on Postgres: explicit READ ONLY transaction, always rolled back
# ---------------------------------------------------------------------------


class RecordingSession:
    def __init__(self, fail_on=None):
        self.calls: list[str] = []
        self._fail_on = fail_on

    def get_bind(self):
        return FakeEngine(dialect="postgresql")

    def rollback(self):
        self.calls.append("ROLLBACK")

    def execute(self, stmt):
        sql = str(stmt)
        self.calls.append(sql)
        if self._fail_on and self._fail_on in sql:
            raise RuntimeError("boom")
        return type("Result", (), {"fetchall": lambda _self: []})()


def test_postgres_query_runs_in_read_only_transaction():
    db = RecordingSession()

    assert execute_query(db, "SELECT 1") == []
    assert db.calls == ["ROLLBACK", "SET TRANSACTION READ ONLY", "SELECT 1", "ROLLBACK"]


def test_postgres_query_rolls_back_on_error():
    db = RecordingSession(fail_on="SELECT 1")

    with pytest.raises(RuntimeError):
        execute_query(db, "SELECT 1")

    assert db.calls[-1] == "ROLLBACK"
