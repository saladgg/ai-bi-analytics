"""
Global pytest configuration and reusable fixtures.

The app is built with ``create_app(settings, resources_factory=...)`` so
every external client is an in-memory fake: a SQLite engine, fakeredis
(running the real Lua) and a fake LLM provider. Tests change behaviour by
configuring those fakes, by ``app.dependency_overrides``, or by setting
attributes on the ``settings`` fixture; never by patching import paths
(audit ARCH-1).
"""

import fakeredis
import pytest
from ai_bi_analytics.api.deps import get_db, verify_api_key
from ai_bi_analytics.core.config import Settings, get_settings
from ai_bi_analytics.core.security import Principal
from ai_bi_analytics.main import create_app
from ai_bi_analytics.resources import Resources
from ai_bi_analytics.services.llm_client import LLMClient
from ai_bi_analytics.services.schema_loader import SchemaProvider
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.fakes import FakeProvider
from tests.fixtures.models import Base, Product

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
    A session inside a transaction that is rolled back after the test.
    """
    connection = engine.connect()
    transaction = connection.begin()

    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def settings() -> Settings:
    """
    The process settings (what ``create_app()`` uses by default).
    Monkeypatch attributes on it to change behaviour for one test.
    """
    return get_settings()


# -----------------------------
# Fakes for external clients
# -----------------------------


@pytest.fixture()
def fake_redis():
    """
    In-memory Redis that executes Lua for real (``fakeredis[lua]``).

    The rate limiter and the response cache both run their real code
    against it. The previous hand-written fakes didn't match the Lua
    script's semantics and hid a limiter that never blocked (audit SEC-3).
    """
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture()
def fake_llm() -> FakeProvider:
    """The LLM provider behind the app; configure its answers per test."""
    return FakeProvider()


@pytest.fixture()
def resources(settings, fake_redis, fake_llm):
    """
    What the app's lifespan would build. The engine is the app's own (same
    database file as ``db_session``), because shutdown disposes it.
    """
    app_engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )
    yield Resources(
        engine=app_engine,
        session_factory=sessionmaker(bind=app_engine),
        redis=fake_redis,
        llm=LLMClient(fake_llm, settings),
        schema=SchemaProvider(settings),
    )
    app_engine.dispose()


# -----------------------------
# FastAPI app and client
# -----------------------------


@pytest.fixture()
def app(settings, resources, db_session):
    """
    The app with fake clients, the test session and auth bypassed.
    """
    application = create_app(settings, resources_factory=lambda _cfg: resources)

    def override_get_db():
        yield db_session

    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[verify_api_key] = lambda: Principal("test-client")
    return application


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def raw_app(settings, resources):
    """The app with fake clients but real auth and sessions."""
    return create_app(settings, resources_factory=lambda _cfg: resources)


# -----------------------------
# Sample Test Data Fixture
# -----------------------------


@pytest.fixture()
def sample_products(db_session):
    """
    Inserts sample products into test DB.
    """
    products = [
        Product(name="Laptop", category="Electronics", revenue=1200),
        Product(name="Phone", category="Electronics", revenue=800),
        Product(name="Shoes", category="Fashion", revenue=200),
    ]

    db_session.add_all(products)
    db_session.commit()

    return products
