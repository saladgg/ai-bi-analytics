"""
Global pytest configuration and reusable fixtures.

This file provides:
- Test client (FastAPI)
- Test database session
- Dependency overrides
- Common utilities for all tests

Automatically discovered by pytest.
"""

import fakeredis
import pytest
from ai_bi_analytics.api.deps import verify_api_key
from ai_bi_analytics.db.models import Base
from ai_bi_analytics.db.session import get_db
from ai_bi_analytics.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# -----------------------------
# Test Database Setup
# -----------------------------

SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """
    Creates all tables once per test session.
    """
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session():
    """
    Creates a new database session per test.

    Rolls back after each test to ensure isolation.
    """
    connection = engine.connect()
    transaction = connection.begin()

    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# -----------------------------
# FastAPI Test Client
# -----------------------------


@pytest.fixture()
def client(db_session):
    """
    Provides a test client with DB + auth override.
    """

    app = create_app()

    def override_get_db():
        yield db_session

    def override_verify_api_key():
        return None  # bypass auth

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_api_key] = override_verify_api_key

    with TestClient(app) as c:
        yield c


# -----------------------------
# Sample Test Data Fixture
# -----------------------------


@pytest.fixture()
def sample_products(db_session):
    """
    Inserts sample products into test DB.
    """
    from ai_bi_analytics.db.models import Product

    products = [
        Product(name="Laptop", category="Electronics", revenue=1200),
        Product(name="Phone", category="Electronics", revenue=800),
        Product(name="Shoes", category="Fashion", revenue=200),
    ]

    db_session.add_all(products)
    db_session.commit()

    return products


# -----------------------------
# Mock LLM
# -----------------------------


@pytest.fixture()
def mock_llm(monkeypatch):
    """
    Mock LLM response to avoid real API calls.
    """

    def fake_complete(self, prompt: str):
        return "SELECT * FROM products;"

    mock_llm_instance = type("MockLLM", (), {"complete": fake_complete})()

    monkeypatch.setattr(
        "ai_bi_analytics.services.nl_to_sql.get_llm_client",
        lambda: mock_llm_instance,
    )

    monkeypatch.setattr(
        "ai_bi_analytics.services.explanation.get_llm_client",
        lambda: mock_llm_instance,
    )


# -----------------------------
# Redis (rate limiter + cache)
# -----------------------------
@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """
    In-memory Redis that executes Lua for real (``fakeredis[lua]``).

    The rate limiter and the response cache both run their real code
    against it. The previous hand-written fakes didn't match the Lua
    script's semantics and hid a limiter that never blocked (audit SEC-3).
    """
    client = fakeredis.FakeRedis(decode_responses=True)

    monkeypatch.setattr("ai_bi_analytics.core.rate_limiter.redis_client", client)
    monkeypatch.setattr("ai_bi_analytics.services.cache.redis_client", client)

    return client
