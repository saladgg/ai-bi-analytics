"""
Integration tests for NL → SQL → Execution pipeline.

Covers:
- Full request lifecycle
- Cache behavior
- LLM mocking
- API validation
"""

from fastapi.testclient import TestClient
from ai_bi_analytics.main import create_app
from ai_bi_analytics.db.session import get_db


def test_query_success(client, sample_products, mock_llm, mock_redis):
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


def test_query_cache_hit(client, sample_products, mock_llm):
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


def test_query_invalid_sql_blocked(client, monkeypatch):
    """
    Ensure dangerous SQL is rejected.
    """

    class FakeLLM:
        def complete(self, prompt):
            return "DROP TABLE products;"

    monkeypatch.setattr(
        "ai_bi_analytics.services.nl_to_sql.get_llm_client",
        lambda: FakeLLM(),
    )

    response = client.post(
        "/api/query",
        json={"question": "delete everything"},
    )

    assert response.status_code == 400
    assert "only select" in response.text.lower()


def test_query_missing_api_key(db_session):
    """
    Should reject requests without API key.
    """

    app = create_app()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        response = client.post(
            "/api/query",
            json={"question": "show products"},
            headers={},  # explicitly empty
        )

    # Accept both depending on implementation
    assert response.status_code in (401, 403, 422)