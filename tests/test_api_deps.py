"""
API-key authentication (audit SEC-8).
"""

import pytest
from ai_bi_analytics.api.deps import build_key_store, verify_api_key
from ai_bi_analytics.core.config import Settings, settings
from ai_bi_analytics.core.security import (
    ApiKeyStore,
    Principal,
    generate_api_key,
    hash_api_key,
    main,
    parse_api_key_entry,
)
from ai_bi_analytics.core.startup_checks import (
    UnsafeConfigurationError,
    check_api_keys,
)
from ai_bi_analytics.db.session import get_db
from ai_bi_analytics.main import create_app
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

ALICE_KEY = "alice-" + "a" * 40
BOB_KEY = "bob-" + "b" * 40


def entry(client_id, key):
    return f"{client_id}:{hash_api_key(key)}"


def make_settings(**env) -> Settings:
    # Isolated from the process environment and any local .env file.
    return Settings(_env_file=None, **{"DATABASE_URL": "sqlite://", **env})


@pytest.fixture(autouse=True)
def no_key_env(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("API_KEYS", raising=False)


@pytest.fixture()
def two_clients(monkeypatch):
    monkeypatch.setattr(
        settings, "api_keys", [entry("alice", ALICE_KEY), entry("bob", BOB_KEY)]
    )
    monkeypatch.setattr(settings, "api_key", None)


# ---------------------------------------------------------------------------
# Key store
# ---------------------------------------------------------------------------


def test_each_key_maps_to_its_client(two_clients):
    assert verify_api_key(ALICE_KEY) == Principal("alice")
    assert verify_api_key(BOB_KEY) == Principal("bob")


@pytest.mark.parametrize("presented", [None, "", "wrong", ALICE_KEY + "x"])
def test_missing_or_unknown_key_is_401(two_clients, presented):
    with pytest.raises(HTTPException) as exc:
        verify_api_key(presented)

    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid or missing API key"
    assert exc.value.headers == {"WWW-Authenticate": "APIKey"}


def test_legacy_single_key_authenticates_as_default(monkeypatch):
    monkeypatch.setattr(settings, "api_keys", [])
    monkeypatch.setattr(settings, "api_key", SecretStr("legacy-key"))

    assert verify_api_key("legacy-key") == Principal("default")


def test_legacy_and_listed_keys_coexist(monkeypatch):
    monkeypatch.setattr(settings, "api_keys", [entry("alice", ALICE_KEY)])
    monkeypatch.setattr(settings, "api_key", SecretStr("legacy-key"))

    assert len(build_key_store(settings)) == 2
    assert verify_api_key(ALICE_KEY) == Principal("alice")
    assert verify_api_key("legacy-key") == Principal("default")


def test_rotation_two_keys_for_one_client_both_work():
    old, new = generate_api_key(), generate_api_key()
    store = ApiKeyStore([("alice", hash_api_key(old)), ("alice", hash_api_key(new))])

    assert store.authenticate(old) == store.authenticate(new) == Principal("alice")


def test_store_checks_every_entry(monkeypatch):
    """No early exit: every entry is compared even after a match."""
    import ai_bi_analytics.core.security as security

    calls = []
    real = security.hmac.compare_digest

    def counting(a, b):
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(security.hmac, "compare_digest", counting)
    store = ApiKeyStore([("a", hash_api_key("k1")), ("b", hash_api_key("k2"))])

    assert store.authenticate("k1") == Principal("a")
    assert len(calls) == 2


def test_generated_keys_are_long_and_unique():
    keys = {generate_api_key() for _ in range(20)}

    assert len(keys) == 20 and all(len(k) >= 43 for k in keys)


@pytest.mark.parametrize(
    "bad",
    [
        "no-colon",
        "bad id:" + "0" * 64,
        "alice:abc",
        "alice:" + "g" * 64,
        ":" + "0" * 64,
    ],
)
def test_malformed_entries_rejected(bad):
    with pytest.raises(ValueError):
        parse_api_key_entry(bad)


def test_entry_digest_is_normalised():
    assert parse_api_key_entry(" alice : " + "AB" * 32) == ("alice", "ab" * 32)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_some_key_must_be_configured():
    with pytest.raises(ValidationError, match="API_KEYS"):
        make_settings()
    with pytest.raises(ValidationError, match="API_KEYS"):
        make_settings(API_KEY="")


def test_api_keys_parsed_from_comma_separated_env():
    cfg = make_settings(API_KEYS=f"{entry('a', 'x')}, {entry('b', 'y')}")

    assert [parse_api_key_entry(e)[0] for e in cfg.api_keys] == ["a", "b"]


def test_duplicate_client_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate client ids"):
        make_settings(API_KEYS=f"{entry('a', 'x')},{entry('a', 'y')}")


def test_api_key_is_secret():
    cfg = make_settings(API_KEY="super-secret-value")

    assert "super-secret-value" not in repr(cfg)


# ---------------------------------------------------------------------------
# Startup check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key, problem",
    [("change-me", "placeholder"), ("short-but-not-placeholder", "shorter than 32")],
)
def test_weak_legacy_key_refused_outside_dev(key, problem):
    with pytest.raises(UnsafeConfigurationError, match=problem):
        check_api_keys(make_settings(ENV="production", API_KEY=key))


def test_weak_legacy_key_only_warns_in_dev(caplog):
    check_api_keys(make_settings(ENV="development", API_KEY="change-me"))

    assert "placeholder" in caplog.text


def test_strong_or_absent_legacy_key_passes():
    check_api_keys(make_settings(ENV="production", API_KEY=generate_api_key()))
    check_api_keys(make_settings(ENV="production", API_KEYS=entry("a", "k")))


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------


def test_rate_limit_is_per_client(two_clients, db_session, sample_products, mock_llm):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session

    with TestClient(app) as client:
        statuses = {
            name: [
                client.post(
                    "/api/query",
                    json={"question": "show products"},
                    headers={"x-api-key": key},
                ).status_code
                for _ in range(settings.rate_limit_requests + 1)
            ]
            for name, key in [("alice", ALICE_KEY), ("bob", BOB_KEY)]
        }

    # Each client gets its own full window from the same address.
    assert statuses["alice"][:-1] == [200] * settings.rate_limit_requests
    assert statuses["alice"][-1] == 429
    assert statuses["bob"][:-1] == [200] * settings.rate_limit_requests


def test_openapi_declares_api_key_scheme():
    schema = create_app().openapi()

    assert schema["components"]["securitySchemes"]["APIKeyHeader"] == {
        "type": "apiKey",
        "description": "Client API key (see API_KEYS).",
        "in": "header",
        "name": "x-api-key",
    }


# ---------------------------------------------------------------------------
# Key generator CLI
# ---------------------------------------------------------------------------


def test_cli_prints_key_and_matching_entry(capsys):
    assert main(["reporting-svc"]) == 0

    lines = [line.strip() for line in capsys.readouterr().out.splitlines()]
    key, server_entry = lines[1], lines[3]
    assert parse_api_key_entry(server_entry) == ("reporting-svc", hash_api_key(key))


@pytest.mark.parametrize("argv", [[], ["a", "b"], ["bad id"]])
def test_cli_usage_errors(argv, capsys):
    assert main(argv) == 2
    assert "usage" in capsys.readouterr().out
