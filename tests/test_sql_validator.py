"""
Unit tests for the SQL guard (audit SEC-1, CQ-1).

The rejection corpus covers every bypass the audit reproduced against the
old substring validator, plus related constructs. The acceptance corpus
pins the legitimate analytics SQL the old validator wrongly rejected.
"""

import pytest
from ai_bi_analytics.services.sql_validator import UnsafeSQLError, validate_sql

TABLES = {"products", "orders", "Customers"}


def accept(sql: str, tables=TABLES) -> str:
    return validate_sql(sql, allowed_tables=tables)


def reject(sql: str, match: str | None = None, tables=TABLES) -> None:
    with pytest.raises(UnsafeSQLError, match=match):
        validate_sql(sql, allowed_tables=tables)


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        # Verified bypasses of the old validator (single ';' passed).
        "SELECT 1; GRANT ALL ON products TO public",
        "SELECT 1; COPY (SELECT '') TO PROGRAM 'id'",
        "SELECT 1; COMMIT; DROP TABLE products",
        "SELECT 1; SET ROLE postgres",
        "SELECT 1; DO $$BEGIN PERFORM 1; END$$",
        "SELECT 1; CALL some_proc()",
        "SELECT 1; VACUUM products",
        "SELECT * FROM products; SELECT * FROM orders",
    ],
)
def test_multiple_statements_rejected(sql):
    reject(sql, match="Multiple SQL statements")


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE products",
        "DELETE FROM products",
        "UPDATE products SET name = 'x'",
        "INSERT INTO products VALUES (1)",
        "ALTER TABLE products ADD COLUMN test INT",
        "TRUNCATE products",
        "CREATE TABLE x (id int)",
        "GRANT ALL ON products TO public",
        "COPY products TO PROGRAM 'id'",
        "SET ROLE postgres",
        "COMMIT",
        "VACUUM products",
        "DO $$BEGIN PERFORM 1; END$$",
        "  delete from products  ",
    ],
)
def test_non_read_statements_rejected(sql):
    reject(sql, match="Only SELECT")


@pytest.mark.parametrize(
    "sql",
    [
        # Writes hidden inside an otherwise-read query.
        "WITH d AS (DELETE FROM products RETURNING *) SELECT * FROM d",
        "WITH u AS (UPDATE products SET name = 'x' RETURNING *) SELECT * FROM u",
        "WITH i AS (INSERT INTO products VALUES (1) RETURNING *) SELECT * FROM i",
        # Creates a table.
        "SELECT * INTO stolen FROM products",
        # Takes row locks.
        "SELECT * FROM products FOR UPDATE",
        "SELECT * FROM products FOR SHARE",
    ],
)
def test_writes_and_locks_inside_select_rejected(sql):
    reject(sql, match="Only SELECT")


@pytest.mark.parametrize(
    "sql, function",
    [
        ("SELECT pg_sleep(600)", "pg_sleep"),
        ("SELECT PG_SLEEP(1)", "pg_sleep"),
        ("SELECT pg_catalog.pg_sleep(1)", "pg_sleep"),
        ("SELECT pg_read_file('/etc/passwd')", "pg_read_file"),
        ("SELECT pg_ls_dir('.')", "pg_ls_dir"),
        ("SELECT pg_terminate_backend(1)", "pg_terminate_backend"),
        ("SELECT lo_import('/etc/passwd')", "lo_import"),
        ("SELECT lo_export(1, '/tmp/x')", "lo_export"),
        (
            "SELECT set_config('default_transaction_read_only', 'off', false)",
            "set_config",
        ),
        ("SELECT current_setting('data_directory')", "current_setting"),
        ("SELECT nextval('products_id_seq')", "nextval"),
        ("SELECT setval('products_id_seq', 1)", "setval"),
        ("SELECT * FROM dblink('host=evil', 'SELECT 1') AS t(a int)", "dblink"),
        ("SELECT query_to_xml('SELECT 1', true, true, '')", "query_to_xml"),
        ("SELECT inet_server_addr()", "inet_server_addr"),
        # Nested inside otherwise-normal expressions.
        ("SELECT name FROM products WHERE id = (SELECT pg_sleep(5))::int", "pg_sleep"),
        ("WITH x AS (SELECT pg_sleep(5)) SELECT * FROM x", "pg_sleep"),
    ],
)
def test_dangerous_functions_rejected(sql, function):
    reject(sql, match=f"Function '{function}'")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT usename, passwd FROM pg_shadow",
        "SELECT * FROM pg_catalog.pg_authid",
        "SELECT * FROM pg_roles",
        "SELECT table_name FROM information_schema.tables",
        "SELECT * FROM products JOIN pg_catalog.pg_user ON true",
    ],
)
def test_system_catalogs_rejected(sql):
    reject(sql, match="System catalogs")


def test_system_catalogs_rejected_even_without_allowlist():
    with pytest.raises(UnsafeSQLError, match="System catalogs"):
        validate_sql("SELECT * FROM pg_shadow")


@pytest.mark.parametrize(
    "sql, match",
    [
        ("SELECT * FROM users", "Unknown table 'users'"),
        ("SELECT * FROM products JOIN secrets ON true", "Unknown table 'secrets'"),
        ("SELECT * FROM private.products", "Schema 'private'"),
        ("SELECT * FROM otherdb.public.products", "Cross-database"),
        # Quoted identifiers are case-sensitive in Postgres.
        ('SELECT * FROM "PRODUCTS"', "Unknown table 'PRODUCTS'"),
    ],
)
def test_unknown_tables_and_schemas_rejected(sql, match):
    reject(sql, match=match)


@pytest.mark.parametrize("sql", ["", "   ", "``` ```", "SELEC * FROM", "SELECT (("])
def test_empty_or_unparseable_rejected(sql):
    reject(sql)


# ---------------------------------------------------------------------------
# Acceptance — legitimate analytics SQL (several were false positives before)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM products",
        "SELECT * FROM products;",
        "select name, revenue from products order by revenue desc limit 3",
        # Column names containing old "forbidden" substrings.
        "SELECT created_at, updated_at, deleted FROM orders",
        "SELECT last_update FROM orders",
        # Forbidden words inside string literals.
        "SELECT * FROM products WHERE name = 'Delete Key'",
        "SELECT * FROM products WHERE name = 'DROP TABLE products; --'",
        # CTEs, set operations, subqueries, window functions.
        "WITH top AS (SELECT * FROM products ORDER BY revenue DESC LIMIT 3) "
        "SELECT name FROM top",
        "SELECT name FROM products UNION ALL SELECT 'x' FROM orders",
        "SELECT category, SUM(revenue) AS total, "
        "RANK() OVER (ORDER BY SUM(revenue) DESC) FROM products GROUP BY category",
        "SELECT * FROM products WHERE id IN (SELECT id FROM orders)",
        "SELECT date_trunc('month', created_at), COUNT(*) FROM orders GROUP BY 1",
        "SELECT COALESCE(name, 'n/a'), CASE WHEN revenue > 10 THEN 1 ELSE 0 END "
        "FROM products",
        "SELECT * FROM generate_series(1, 3)",
        # Schema-qualified default schema, aliases, mixed case.
        "SELECT p.name FROM public.products AS p",
        "SELECT * FROM PRODUCTS",
        'SELECT * FROM "Customers"',
        "SELECT * FROM customers",
        # Fenced model output.
        "```sql\nSELECT * FROM products\n```",
        "```\nSELECT * FROM products\n```",
    ],
)
def test_legitimate_queries_accepted(sql):
    assert accept(sql).upper().startswith(("SELECT", "WITH"))


def test_returns_canonical_sql_without_comments():
    canonical = accept("SELECT name /* hidden */ FROM products -- trailing")

    assert canonical == "SELECT name FROM products"


def test_canonical_sql_drops_trailing_semicolon_and_fences():
    assert accept("```sql\nSELECT 1 FROM products;\n```") == "SELECT 1 FROM products"


def test_dollar_quoted_payload_stays_a_literal():
    canonical = accept("SELECT $$a; DROP TABLE products$$ FROM products")

    assert canonical == "SELECT 'a; DROP TABLE products' FROM products"


def test_allowlist_is_optional():
    assert validate_sql("SELECT * FROM anything") == "SELECT * FROM anything"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT name FROM products; -- done",
        "SELECT name FROM products; /* done */",
        "SELECT name FROM products;;",
    ],
)
def test_trailing_comment_or_empty_statement_is_not_a_second_statement(sql):
    assert accept(sql) == "SELECT name FROM products"


def test_comment_trailer_cannot_hide_a_second_statement():
    reject("SELECT 1 FROM products; /* x */ DROP TABLE products", match="Multiple")
