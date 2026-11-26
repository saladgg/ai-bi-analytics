"""
Query scope: what the LLM sees and what the guard lets run (audit SEC-7).
"""

import pytest
from ai_bi_analytics.core.config import Settings
from ai_bi_analytics.core.startup_checks import (
    UnsafeConfigurationError,
    check_query_scope,
)
from ai_bi_analytics.db.session import build_engine_kwargs
from ai_bi_analytics.services.schema_loader import QueryScope, load_query_scope
from ai_bi_analytics.services.sql_validator import UnsafeSQLError, validate_sql
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def make_settings(**env) -> Settings:
    base = {"API_KEY": "k", "DATABASE_URL": "sqlite://"}
    return Settings(**{**base, **env})


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_comma_separated_lists_are_parsed():
    cfg = make_settings(
        QUERYABLE_TABLES=" products, orders ,, ",
        REDACTED_COLUMNS="users.email,ssn",
    )

    assert cfg.queryable_tables == ["products", "orders"]
    assert cfg.redacted_columns == ["users.email", "ssn"]


def test_lists_default_empty():
    cfg = make_settings()

    assert cfg.queryable_tables == [] and cfg.redacted_columns == []
    assert cfg.queryable_schema == "public"


def test_lists_accept_python_lists():
    assert make_settings(QUERYABLE_TABLES=["a"]).queryable_tables == ["a"]


@pytest.mark.parametrize(
    "env, match",
    [
        ({"QUERYABLE_SCHEMA": "public -c x=y"}, "QUERYABLE_SCHEMA"),
        ({"QUERYABLE_SCHEMA": "1abc"}, "QUERYABLE_SCHEMA"),
        ({"QUERYABLE_TABLES": "products,drop table"}, "QUERYABLE_TABLES"),
        ({"REDACTED_COLUMNS": "a.b.c"}, "REDACTED_COLUMNS"),
        ({"REDACTED_COLUMNS": "users.e-mail"}, "REDACTED_COLUMNS"),
    ],
)
def test_invalid_identifiers_rejected(env, match):
    with pytest.raises(ValidationError, match=match):
        make_settings(**env)


def test_search_path_set_on_postgres_connections():
    kwargs = build_engine_kwargs("postgresql://u:p@h/db", 1, 1, "analytics")

    assert "-c search_path=analytics" in kwargs["connect_args"]["options"]


# ---------------------------------------------------------------------------
# Startup check
# ---------------------------------------------------------------------------


def test_scope_check_passes_with_allowlist():
    check_query_scope(make_settings(ENV="production", QUERYABLE_TABLES="products"))


def test_scope_check_refuses_empty_allowlist_outside_dev():
    with pytest.raises(UnsafeConfigurationError, match="QUERYABLE_TABLES"):
        check_query_scope(make_settings(ENV="production"))


def test_scope_check_warns_in_dev(caplog):
    check_query_scope(make_settings(ENV="development"))

    assert "QUERYABLE_TABLES is empty" in caplog.text


# ---------------------------------------------------------------------------
# load_query_scope
# ---------------------------------------------------------------------------


@pytest.fixture()
def scope_db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE products (id INTEGER, name TEXT, cost REAL)"))
        conn.execute(
            text("CREATE TABLE users (id INTEGER, email TEXT, ssn TEXT, city TEXT)")
        )
        conn.execute(text("CREATE TABLE secrets (id INTEGER, value TEXT)"))
        conn.execute(text("CREATE VIEW sales_by_city AS SELECT city FROM users"))
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_scope_includes_tables_and_views(scope_db):
    scope = load_query_scope(scope_db, make_settings())

    assert scope.tables == {"products", "users", "secrets", "sales_by_city"}
    assert "sales_by_city(city TEXT)\n" in scope.description


def test_allowlist_limits_scope_and_warns_on_missing(scope_db, caplog):
    scope = load_query_scope(
        scope_db, make_settings(QUERYABLE_TABLES="Products,sales_by_city,ghost")
    )

    assert scope.tables == {"products", "sales_by_city"}
    assert "secrets" not in scope.description
    assert "['ghost']" in caplog.text


def test_redactions_hide_columns_per_table_and_everywhere(scope_db):
    scope = load_query_scope(
        scope_db,
        make_settings(REDACTED_COLUMNS="users.email,SSN,products.missing"),
    )

    assert scope.redacted == {"users": frozenset({"email", "ssn"})}
    assert "users(id INTEGER, city TEXT)\n" in scope.description
    assert "email" not in scope.description and "ssn" not in scope.description
    assert "products(id INTEGER, name TEXT, cost REAL)\n" in scope.description


def test_description_format():
    scope = QueryScope(
        schema="public",
        columns={"a": [("x", "INT"), ("y", "TEXT")], "b": [("z", "INT")]},
    )

    assert scope.description == "a(x INT, y TEXT)\nb(z INT)\n"
    assert scope.redacted == {}


# ---------------------------------------------------------------------------
# Guard: schema and redactions
# ---------------------------------------------------------------------------

TABLES = {"products", "users", "orders"}
REDACTED = {"users": {"email", "ssn"}}


def guard(sql, **kwargs):
    kwargs.setdefault("redacted_columns", REDACTED)
    return validate_sql(sql, allowed_tables=TABLES, **kwargs)


def test_custom_schema_qualifier_allowed_and_public_rejected():
    assert guard("SELECT * FROM analytics.products", schema="analytics")
    with pytest.raises(UnsafeSQLError, match="Schema 'public'"):
        guard("SELECT * FROM public.products", schema="analytics")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, city FROM users",
        "SELECT COUNT(*) FROM users",
        "SELECT COUNT(u.*) FROM users u",
        "SELECT * FROM products",  # unrestricted table
        "SELECT p.* FROM products p JOIN orders o ON o.id = p.id",
        "SELECT u.city, p.name FROM users u JOIN products p ON p.id = u.id",
    ],
)
def test_redaction_allows_safe_queries(sql):
    assert guard(sql)


@pytest.mark.parametrize(
    "sql, match",
    [
        ("SELECT email FROM users", "Column 'email'"),
        ("SELECT u.SSN FROM users u", "Column 'SSN'"),
        ("SELECT city FROM users WHERE email LIKE '%@x.com'", "Column 'email'"),
        ("SELECT * FROM users", r"SELECT \*"),
        ("SELECT u.* FROM users u", r"SELECT \*"),
        ("SELECT p.* FROM products p JOIN users u ON u.id = p.id", r"SELECT \*"),
        ("WITH x AS (SELECT * FROM users) SELECT city FROM x", r"SELECT \*"),
        ("WITH x AS (SELECT email AS e FROM users) SELECT e FROM x", "Column 'email'"),
        ("SELECT row_to_json(u) FROM users u", "Whole-row references to 'u'"),
        ("SELECT users FROM users", "Whole-row references to 'users'"),
        ("SELECT to_jsonb(u.*) FROM users u", r"SELECT \*"),
    ],
)
def test_redaction_blocks_leaks(sql, match):
    with pytest.raises(UnsafeSQLError, match=match):
        guard(sql)


def test_no_redactions_means_no_redaction_checks():
    assert guard("SELECT * FROM users", redacted_columns={})
    assert guard("SELECT * FROM users", redacted_columns={"users": set()})


def test_route_enforces_scope_end_to_end(client, monkeypatch):
    """The model is only shown allowlisted tables, and SQL that strays
    outside them is rejected even if the model produces it."""
    from ai_bi_analytics.core.config import settings
    from ai_bi_analytics.services import explanation, nl_to_sql

    prompts = []

    class LLM:
        def complete(self, prompt, system=None):
            prompts.append(prompt)
            return "SELECT * FROM secret_table"

    monkeypatch.setattr(settings, "queryable_tables", ["products"])
    monkeypatch.setattr(nl_to_sql, "get_llm_client", lambda: LLM())
    monkeypatch.setattr(explanation, "get_llm_client", lambda: LLM())

    response = client.post("/api/query", json={"question": "show secrets"})

    assert response.status_code == 422
    assert "Unknown table 'secret_table'" in response.json()["detail"]
    assert "products(" in prompts[0]
