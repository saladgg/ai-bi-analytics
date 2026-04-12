"""
Unit tests for SQL validation logic.

Ensures:
- Only SELECT queries allowed
- Injection attempts blocked
"""

import pytest
from ai_bi_analytics.services.sql_validator import validate_sql


def test_valid_select():
    validate_sql("SELECT * FROM products")


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE products;",
        "DELETE FROM products;",
        "UPDATE products SET name='x';",
        "INSERT INTO products VALUES (1);",
        "ALTER TABLE products ADD COLUMN test INT;",
    ],
)
def test_forbidden_statements(sql):
    with pytest.raises(ValueError):
        validate_sql(sql)


def test_multiple_statements_blocked():
    sql = "SELECT * FROM products; DROP TABLE users;"
    with pytest.raises(ValueError):
        validate_sql(sql)


def test_non_select_blocked():
    sql = "WITH temp AS (DELETE FROM products) SELECT * FROM temp;"
    with pytest.raises(ValueError):
        validate_sql(sql)


def test_multiple_statements_without_forbidden_keywords_blocked():
    # No forbidden keywords, but more than one statement delimiter.
    sql = "SELECT * FROM products; SELECT * FROM users;"
    with pytest.raises(ValueError) as exc:
        validate_sql(sql)
    assert "Multiple SQL statements" in str(exc.value)


def test_sql_comments_blocked():
    sql = "SELECT * FROM products -- comment"
    with pytest.raises(ValueError) as exc:
        validate_sql(sql)
    assert "SQL comments" in str(exc.value)

