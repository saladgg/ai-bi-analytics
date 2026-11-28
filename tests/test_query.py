"""
Integration tests for NL → SQL → Execution pipeline.

Covers:
- Full request lifecycle
- Cache behavior
- LLM mocking
- API validation
"""

from ai_bi_analytics.api.deps import get_db
from fastapi.testclient import TestClient


def test_query_success(client, sample_products, fake_llm):
    """
    Should successfully process a query end-to-end.
    """
    response = client.post(
        "/api/query",
        json={"question": "show all products"},
        headers={"x-api-key": "test"},
    )

    assert response.status_code == 200

    data = response.json()

    assert "sql" in data
    assert "result" in data
    assert "explanation" in data
    assert isinstance(data["result"], list)


def test_query_cache_hit(client, sample_products, fake_llm):
    """
    Second request should hit cache.
    """
    payload = {"question": "show all products"}

    first = client.post(
        "/api/query",
        json=payload,
        headers={"x-api-key": "test"},
    )
    second = client.post(
        "/api/query",
        json=payload,
        headers={"x-api-key": "test"},
    )

    assert first.status_code == 200
    assert second.status_code == 200

    # Cached response should match
    assert first.json() == second.json()


def test_query_invalid_sql_blocked(client, fake_llm):
    """
    Ensure dangerous SQL is rejected.
    """
    fake_llm.sql = "DROP TABLE products;"

    response = client.post(
        "/api/query",
        json={"question": "delete everything"},
    )

    assert response.status_code == 422
    body = response.json()
    assert "only select" in body["detail"].lower()
    assert body["code"] == "unsafe_sql"
    assert body["request_id"] == response.headers["x-request-id"]


def test_query_missing_api_key(raw_app, db_session):
    """
    Should reject requests without API key.
    """

    def override_get_db():
        yield db_session

    raw_app.dependency_overrides[get_db] = override_get_db

    with TestClient(raw_app) as client:
        response = client.post(
            "/api/query",
            json={"question": "show products"},
            headers={},  # explicitly empty
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "APIKey"
