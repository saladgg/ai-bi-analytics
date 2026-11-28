"""
Request dependencies: settings, process-wide clients, authentication,
rate limiting and the query pipeline (audit ARCH-1).

Everything comes from the app (``app.state``), never from module globals,
so tests replace any piece with ``app.dependency_overrides``.
"""

from collections.abc import Iterator

import redis
from fastapi import Depends, HTTPException, Request, Response, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from ai_bi_analytics.core.config import Settings
from ai_bi_analytics.core.rate_limiter import enforce_rate_limit
from ai_bi_analytics.core.security import (
    LEGACY_CLIENT_ID,
    ApiKeyStore,
    Principal,
    hash_api_key,
    parse_api_key_entry,
)
from ai_bi_analytics.resources import Resources
from ai_bi_analytics.services.cache import ResultCache
from ai_bi_analytics.services.llm_client import LLMClient
from ai_bi_analytics.services.pipeline import QueryPipeline
from ai_bi_analytics.services.query_executor import QueryExecutor
from ai_bi_analytics.services.schema_loader import SchemaProvider
from ai_bi_analytics.services.sql_validator import SQLGuard

api_key_header = APIKeyHeader(
    name="x-api-key",
    auto_error=False,
    description="Client API key (see API_KEYS).",
)


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_resources(request: Request) -> Resources:
    return request.app.state.resources


def get_db(resources: Resources = Depends(get_resources)) -> Iterator[Session]:
    """A session per request, closed afterwards."""
    db = resources.session_factory()
    try:
        yield db
    finally:
        db.close()


def get_redis(resources: Resources = Depends(get_resources)) -> redis.Redis:
    return resources.redis


def get_llm(resources: Resources = Depends(get_resources)) -> LLMClient:
    return resources.llm


def get_schema_provider(
    resources: Resources = Depends(get_resources),
) -> SchemaProvider:
    return resources.schema


def get_result_cache(
    client: redis.Redis = Depends(get_redis),
    cfg: Settings = Depends(get_app_settings),
) -> ResultCache:
    return ResultCache(client, cfg)


def get_query_pipeline(
    cfg: Settings = Depends(get_app_settings),
    llm: LLMClient = Depends(get_llm),
    schema: SchemaProvider = Depends(get_schema_provider),
    cache: ResultCache = Depends(get_result_cache),
) -> QueryPipeline:
    return QueryPipeline(
        cfg=cfg,
        llm=llm,
        schema=schema,
        guard=SQLGuard(cfg.max_result_rows),
        executor=QueryExecutor(cfg.max_result_rows),
        cache=cache,
    )


def build_key_store(cfg: Settings) -> ApiKeyStore:
    entries = [parse_api_key_entry(entry) for entry in cfg.api_keys]
    if cfg.api_key is not None and cfg.api_key.get_secret_value():
        entries.append((LEGACY_CLIENT_ID, hash_api_key(cfg.api_key.get_secret_value())))
    return ApiKeyStore(entries)


def verify_api_key(
    x_api_key: str | None = Security(api_key_header),
    cfg: Settings = Depends(get_app_settings),
) -> Principal:
    """
    Authenticates the ``x-api-key`` header.

    Returns:
        Principal: the calling client.

    Raises:
        HTTPException: 401 when the key is missing or unknown.
    """
    principal = build_key_store(cfg).authenticate(x_api_key)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "APIKey"},
        )
    return principal


def rate_limited_client(
    request: Request,
    response: Response,
    principal: Principal = Depends(verify_api_key),
    client: redis.Redis = Depends(get_redis),
    cfg: Settings = Depends(get_app_settings),
) -> Principal:
    """
    The authenticated caller, counted against its rate-limit window.

    Raises:
        HTTPException: 429 with ``Retry-After`` when the window is full.
    """
    rate_limit = enforce_rate_limit(
        request, client, cfg, f"client:{principal.client_id}"
    )
    response.headers.update(rate_limit.headers())
    # Error handlers build their own response; they copy these from here.
    request.state.rate_limit_headers = rate_limit.headers()
    return principal
