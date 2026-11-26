"""
Bounded queries and results (audit SEC-5).
"""

import json

import pytest
from ai_bi_analytics.core.config import settings
from ai_bi_analytics.services import cache, explanation
from ai_bi_analytics.services.explanation import describe_row_count
from ai_bi_analytics.services.query_executor import QueryResult, execute_query
from ai_bi_analytics.services.sql_validator import validate_sql
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def capped(sql, max_rows=100):
    return validate_sql(sql, max_rows=max_rows)


# ---------------------------------------------------------------------------
# Guard row cap
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("SELECT a FROM t", "SELECT a FROM t LIMIT 101"),
        ("SELECT a FROM t LIMIT 5000", "SELECT a FROM t LIMIT 101"),
        ("SELECT a FROM t LIMIT 5000 OFFSET 7", "SELECT a FROM t LIMIT 101 OFFSET 7"),
        ("SELECT a FROM t LIMIT ALL", "SELECT a FROM t LIMIT 101"),
        ("SELECT a FROM t LIMIT (SELECT 5)", "SELECT a FROM t LIMIT 101"),
        ("SELECT a FROM t FETCH FIRST 5000 ROWS ONLY", "SELECT a FROM t LIMIT 101"),
        (
            "SELECT a FROM t UNION SELECT b FROM u",
            "SELECT a FROM t UNION SELECT b FROM u LIMIT 101",
        ),
        (
            "WITH x AS (SELECT a FROM t) SELECT a FROM x ORDER BY a",
            "WITH x AS (SELECT a FROM t) SELECT a FROM x ORDER BY a LIMIT 101",
        ),
    ],
)
def test_unbounded_or_oversized_queries_are_capped(sql, expected):
    assert capped(sql) == expected


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM t LIMIT 3",
        "SELECT a FROM t LIMIT 100",
        "SELECT a FROM t ORDER BY a LIMIT 10 OFFSET 20",
        "SELECT a FROM t FETCH FIRST 5 ROWS ONLY",
    ],
)
def test_queries_within_cap_keep_their_limit(sql):
    assert "101" not in capped(sql)


def test_inner_limits_are_untouched():
    out = capped("SELECT a FROM (SELECT a FROM t LIMIT 5000) AS s")

    assert "LIMIT 5000" in out and out.endswith("LIMIT 101")


def test_no_cap_without_max_rows():
    assert validate_sql("SELECT a FROM t") == "SELECT a FROM t"


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


@pytest.fixture()
def numbers_db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE n (v INTEGER)"))
        conn.execute(
            text("INSERT INTO n VALUES " + ",".join(f"({i})" for i in range(10)))
        )
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_executor_truncates_past_max_rows(numbers_db):
    result = execute_query(numbers_db, "SELECT v FROM n ORDER BY v", max_rows=4)

    assert result == QueryResult(rows=[{"v": i} for i in range(4)], truncated=True)


@pytest.mark.parametrize("max_rows", [10, 50])
def test_executor_not_truncated_at_or_under_cap(numbers_db, max_rows):
    result = execute_query(numbers_db, "SELECT v FROM n", max_rows=max_rows)

    assert len(result.rows) == 10 and result.truncated is False


def test_executor_unbounded_when_no_cap(numbers_db):
    assert len(execute_query(numbers_db, "SELECT v FROM n").rows) == 10


# ---------------------------------------------------------------------------
# Explanation sampling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rows, truncated, shown, expected",
    [
        (3, False, 3, "Rows returned: 3."),
        (30, False, 20, "Rows returned: 30; the first 20 are shown."),
        (1000, True, 20, "Rows returned: more than 1000; the first 20 are shown."),
        (5, True, 5, "Rows returned: more than 5; the first 5 are shown."),
    ],
)
def test_describe_row_count(rows, truncated, shown, expected):
    result = QueryResult(rows=[{}] * rows, truncated=truncated)

    assert describe_row_count(result, shown) == expected


def test_explanation_gets_bounded_sample(monkeypatch):
    prompts = []

    class LLM:
        def complete(self, prompt, system=None):
            prompts.append(prompt)
            return "ok"

    monkeypatch.setattr(explanation, "get_llm_client", lambda: LLM())
    monkeypatch.setattr(settings, "explanation_sample_rows", 2)

    rows = [{"v": i} for i in range(500)]
    explanation.explain_result("q", "SELECT v FROM n", QueryResult(rows, True))

    payload = prompts[0].split("<result>\n")[1].split("\n</result>")[0]
    assert json.loads(payload) == [{"v": 0}, {"v": 1}]
    assert "Rows returned: more than 500; the first 2 are shown." in prompts[0]


# ---------------------------------------------------------------------------
# Cache size cap
# ---------------------------------------------------------------------------


def test_small_responses_are_cached():
    assert cache.set_cached_response("k", {"a": 1}) is True
    assert cache.get_cached_response("k") == {"a": 1}


def test_oversized_responses_are_not_cached(monkeypatch, caplog):
    monkeypatch.setattr(settings, "cache_max_bytes", 10)

    assert cache.set_cached_response("big", {"a": "x" * 50}) is False
    assert cache.get_cached_response("big") is None
    assert "not cached" in caplog.text


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------


def test_route_caps_rows_and_reports_truncation(client, sample_products, monkeypatch):
    from ai_bi_analytics.services import nl_to_sql

    class LLM:
        def complete(self, prompt, system=None):
            return "SELECT name FROM products ORDER BY name"

    monkeypatch.setattr(nl_to_sql, "get_llm_client", lambda: LLM())
    monkeypatch.setattr(explanation, "get_llm_client", lambda: LLM())
    monkeypatch.setattr(settings, "max_result_rows", 2)

    body = client.post("/api/query", json={"question": "all product names"}).json()

    assert body["sql"] == "SELECT name FROM products ORDER BY name LIMIT 3"
    assert body["result"] == [{"name": "Laptop"}, {"name": "Phone"}]
    assert body["row_count"] == 2
    assert body["truncated"] is True
