"""
Dependency utilities for API authentication and shared components.
"""

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from ai_bi_analytics.core.config import Settings, settings
from ai_bi_analytics.core.security import (
    LEGACY_CLIENT_ID,
    ApiKeyStore,
    Principal,
    hash_api_key,
    parse_api_key_entry,
)

api_key_header = APIKeyHeader(
    name="x-api-key",
    auto_error=False,
    description="Client API key (see API_KEYS).",
)


def build_key_store(cfg: Settings) -> ApiKeyStore:
    entries = [parse_api_key_entry(entry) for entry in cfg.api_keys]
    if cfg.api_key is not None and cfg.api_key.get_secret_value():
        entries.append((LEGACY_CLIENT_ID, hash_api_key(cfg.api_key.get_secret_value())))
    return ApiKeyStore(entries)


def verify_api_key(x_api_key: str | None = Security(api_key_header)) -> Principal:
    """
    Authenticates the ``x-api-key`` header.

    Returns:
        Principal: the calling client.

    Raises:
        HTTPException: 401 when the key is missing or unknown.
    """
    principal = build_key_store(settings).authenticate(x_api_key)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "APIKey"},
        )
    return principal
