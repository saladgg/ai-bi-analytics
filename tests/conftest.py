"""
Global pytest configuration and reusable fixtures.

This file provides:
- Test client (FastAPI)
- Test database session
- Dependency overrides
- Common utilities for all tests

Automatically discovered by pytest.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_bi_analytics.main import create_app
from ai_bi_analytics.db.models import Base
from ai_bi_analytics.db.session import get_db
from ai_bi_analytics.api.deps import verify_api_key



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
# Mock rate_limiter
# -----------------------------
@pytest.fixture(autouse=True)
def mock_rate_limiter(monkeypatch):
    """
    Mock Lua rate limiter script directly.

    This avoids real Redis calls caused by register_script.
    """

    fake_store = {}

    def fake_rate_limit_script(*args, **kwargs):
        """
        Simulates sliding window rate limiting.
        """
        key = kwargs.get("keys", [None])[0]

        count = fake_store.get(key, 0)
        count += 1
        fake_store[key] = count

        return count  

    monkeypatch.setattr(
    "ai_bi_analytics.core.rate_limiter.get_rate_limit_script",
    lambda: fake_rate_limit_script,
    )
    

# -----------------------------
# Mock redis
# -----------------------------
@pytest.fixture(autouse=True)
def mock_redis(monkeypatch):
    """
    Mock Redis globally for all tests.

    Prevents real Redis connections and provides
    in-memory behavior for cache + rate limiter.
    """

    fake_store = {}

    def fake_get(key):
        return fake_store.get(key)

    def fake_setex(key, ex, value):
        fake_store[key] = value

    # Patch Redis client methods actually used by cache.py
    monkeypatch.setattr(
        "ai_bi_analytics.services.cache.redis_client.get",
        fake_get,
    )

    monkeypatch.setattr(
        "ai_bi_analytics.services.cache.redis_client.setex",
        fake_setex,
    )

# -----------------------------
# Mock cache
# -----------------------------
@pytest.fixture(autouse=True)
def mock_cache(monkeypatch):
    """
    Mock cache layer (NOT Redis directly).
    """

    fake_cache = {}

    def fake_get_cached_response(key):
        return fake_cache.get(key)

    def fake_set_cached_response(key, value):
        fake_cache[key] = value

    monkeypatch.setattr(
        "ai_bi_analytics.api.routes.query.get_cached_response",
        fake_get_cached_response,
    )

    monkeypatch.setattr(
        "ai_bi_analytics.api.routes.query.set_cached_response",
        fake_set_cached_response,
    )
