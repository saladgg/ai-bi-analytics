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
from sqlalchemy.engine import make_url
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
    rows = execute_query(
        readonly_session, f"SELECT id, name FROM {TABLE} ORDER BY id"
    ).rows

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


@pytest.mark.parametrize(
    "sql, expected",
    [
        (
            f"WITH t AS (SELECT * FROM {TABLE}) SELECT name FROM t ORDER BY id",
            [{"name": "a"}, {"name": "b"}],
        ),
        (
            f"SELECT name, RANK() OVER (ORDER BY id DESC) AS r FROM {TABLE} ORDER BY r",
            [{"name": "b", "r": 1}, {"name": "a", "r": 2}],
        ),
        (
            f"SELECT $$x; DROP TABLE {TABLE}$$ AS s FROM {TABLE} LIMIT 1",
            [{"s": f"x; DROP TABLE {TABLE}"}],
        ),
        (
            f"```sql\nSELECT count(*) AS n /* c */ FROM {TABLE}; -- done\n```",
            [{"n": 2}],
        ),
    ],
)
def test_guard_canonical_sql_executes_on_postgres(readonly_session, sql, expected):
    """The guard executes SQL regenerated from its AST; it must stay valid
    Postgres with the same meaning as the model's original query."""
    from ai_bi_analytics.services.sql_validator import validate_sql

    canonical = validate_sql(sql, allowed_tables={TABLE})

    assert execute_query(readonly_session, canonical).rows == expected


# ---------------------------------------------------------------------------
# Query scope on a dedicated schema (audit SEC-7)
# ---------------------------------------------------------------------------

SCOPE_SCHEMA = "sec7_analytics"


@pytest.fixture(scope="module")
def analytics_schema(owner_engine):
    """A dedicated schema with a table, a view and a restricted column,
    provisioned with the shipped readonly_role.sql grants."""
    ro_user = make_url(READONLY_URL).username
    with owner_engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {SCOPE_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {SCOPE_SCHEMA}"))
        conn.execute(
            text(
                f"CREATE TABLE {SCOPE_SCHEMA}.customers (id int, city text, email text)"
            )
        )
        conn.execute(
            text(
                f"INSERT INTO {SCOPE_SCHEMA}.customers VALUES "
                "(1, 'Nairobi', 'a@x.com'), (2, 'Mombasa', 'b@x.com'), "
                "(3, 'Nairobi', 'c@x.com')"
            )
        )
        conn.execute(
            text(
                f"CREATE VIEW {SCOPE_SCHEMA}.customers_by_city AS "
                f"SELECT city, count(*) AS n FROM {SCOPE_SCHEMA}.customers "
                "GROUP BY city"
            )
        )
        conn.execute(text(f"GRANT USAGE ON SCHEMA {SCOPE_SCHEMA} TO {ro_user}"))
        conn.execute(
            text(f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCOPE_SCHEMA} TO {ro_user}")
        )
    yield SCOPE_SCHEMA
    with owner_engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {SCOPE_SCHEMA} CASCADE"))


@pytest.fixture()
def scoped_session(analytics_schema):
    engine = create_engine(
        READONLY_URL,
        **build_engine_kwargs(READONLY_URL, 1000, 5000, analytics_schema),
    )
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_scope_and_guard_on_dedicated_schema(scoped_session, analytics_schema):
    from ai_bi_analytics.core.config import Settings
    from ai_bi_analytics.services.schema_loader import load_query_scope
    from ai_bi_analytics.services.sql_validator import validate_sql

    cfg = Settings(
        _env_file=None,
        API_KEY="k",
        DATABASE_URL=READONLY_URL,
        QUERYABLE_SCHEMA=analytics_schema,
        REDACTED_COLUMNS="customers.email",
    )
    scope = load_query_scope(scoped_session, cfg)

    assert scope.tables == {"customers", "customers_by_city"}
    assert "email" not in scope.description
    assert scope.redacted == {"customers": frozenset({"email"})}

    # Unqualified names resolve through search_path.
    sql = validate_sql(
        "SELECT city, n FROM customers_by_city ORDER BY n DESC, city",
        allowed_tables=scope.tables,
        schema=scope.schema,
        redacted_columns=scope.redacted,
    )
    assert execute_query(scoped_session, sql).rows == [
        {"city": "Nairobi", "n": 2},
        {"city": "Mombasa", "n": 1},
    ]


def test_column_privileges_enforce_redaction_in_postgres(
    owner_engine, scoped_session, analytics_schema
):
    """The documented column-level grant makes the database itself refuse
    a hidden column, independently of the guard."""
    ro_user = make_url(READONLY_URL).username
    with owner_engine.begin() as conn:
        conn.execute(
            text(f"REVOKE SELECT ON {analytics_schema}.customers FROM {ro_user}")
        )
        conn.execute(
            text(
                f"GRANT SELECT (id, city) ON {analytics_schema}.customers TO {ro_user}"
            )
        )
    try:
        assert execute_query(scoped_session, "SELECT city FROM customers LIMIT 1").rows
        with pytest.raises(DBAPIError, match="permission denied"):
            execute_query(scoped_session, "SELECT email FROM customers")
        with pytest.raises(DBAPIError, match="permission denied"):
            execute_query(scoped_session, "SELECT * FROM customers")
    finally:
        with owner_engine.begin() as conn:
            conn.execute(
                text(f"GRANT SELECT ON {analytics_schema}.customers TO {ro_user}")
            )


def test_row_cap_truncates_on_postgres(readonly_session):
    """Audit SEC-5: the guard's LIMIT stops Postgres at cap + 1 rows and
    the executor reports truncation."""
    from ai_bi_analytics.services.sql_validator import validate_sql

    sql = validate_sql(
        f"SELECT id FROM {TABLE} ORDER BY id", allowed_tables={TABLE}, max_rows=1
    )
    result = execute_query(readonly_session, sql, max_rows=1)

    assert sql.endswith("LIMIT 2")
    assert result.rows == [{"id": 1}] and result.truncated is True
