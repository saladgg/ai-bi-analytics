"""
End-to-end checks of SEC-2 against a real PostgreSQL.

Skipped unless both URLs are set, e.g. against the compose Postgres:

    TEST_POSTGRES_OWNER_URL=postgresql+psycopg2://test_user:test_pwd@localhost:5433/ai_bi_db
    TEST_POSTGRES_READONLY_URL=postgresql+psycopg2://ai_bi_readonly:readonly_pwd@localhost:5433/ai_bi_db

The read-only role must have been created with example/readonly_role.sql
(the compose Postgres does this on first start).
"""

import os

import pytest
from ai_bi_analytics.db.session import (
    UnsafeDatabaseRoleError,
    assert_database_role_is_safe,
    build_engine_kwargs,
)
from ai_bi_analytics.services.query_executor import execute_query
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

OWNER_URL = os.getenv("TEST_POSTGRES_OWNER_URL")
READONLY_URL = os.getenv("TEST_POSTGRES_READONLY_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (OWNER_URL and READONLY_URL),
        reason="TEST_POSTGRES_OWNER_URL / TEST_POSTGRES_READONLY_URL not set",
    ),
]

TABLE = "sec2_readonly_probe"


@pytest.fixture(scope="module")
def owner_engine():
    engine = create_engine(OWNER_URL)
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
        conn.execute(text(f"CREATE TABLE {TABLE} (id int, name text)"))
        conn.execute(text(f"INSERT INTO {TABLE} VALUES (1, 'a'), (2, 'b')"))
    yield engine
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
    engine.dispose()


@pytest.fixture()
def readonly_session(owner_engine):
    engine = create_engine(
        READONLY_URL, **build_engine_kwargs(READONLY_URL, 1000, 5000)
    )
    with Session(engine) as session:
        yield session
    engine.dispose()


def row_count(owner_engine) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one()


def test_select_works(readonly_session):
    rows = execute_query(readonly_session, f"SELECT id, name FROM {TABLE} ORDER BY id")

    assert rows == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]


@pytest.mark.parametrize(
    "sql",
    [
        f"DELETE FROM {TABLE}",
        f"SELECT 1; DELETE FROM {TABLE}",
        f"SELECT 1; GRANT ALL ON {TABLE} TO PUBLIC",
        "SELECT 1; CREATE TABLE sec2_should_not_exist (x int)",
        f"WITH d AS (DELETE FROM {TABLE} RETURNING *) SELECT * FROM d",
    ],
)
def test_writes_are_refused_by_the_database(readonly_session, owner_engine, sql):
    with pytest.raises(DBAPIError):
        execute_query(readonly_session, sql)

    assert row_count(owner_engine) == 2


def test_commit_smuggled_into_query_cannot_persist_a_write(
    readonly_session, owner_engine
):
    with pytest.raises(DBAPIError):
        execute_query(readonly_session, f"SELECT 1; COMMIT; DELETE FROM {TABLE}")

    assert row_count(owner_engine) == 2


def test_statement_timeout_is_enforced(readonly_session):
    with pytest.raises(DBAPIError, match="statement timeout"):
        execute_query(readonly_session, "SELECT pg_sleep(5)")


def test_server_file_read_is_denied(readonly_session):
    with pytest.raises(DBAPIError, match="permission denied"):
        execute_query(readonly_session, "SELECT pg_read_file('/etc/passwd')")


def test_readonly_role_passes_startup_check():
    engine = create_engine(READONLY_URL)
    try:
        assert_database_role_is_safe(engine, "production")
    finally:
        engine.dispose()


def test_superuser_fails_startup_check():
    engine = create_engine(OWNER_URL)
    try:
        is_super = (
            engine.connect()
            .execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"))
            .scalar_one()
        )
        if not is_super:
            pytest.skip("owner URL is not a superuser")
        with pytest.raises(UnsafeDatabaseRoleError):
            assert_database_role_is_safe(engine, "production")
    finally:
        engine.dispose()
