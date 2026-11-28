"""
Application entry point for the AI-Powered Business Intelligence Backend.

This module initializes the FastAPI application, configures middleware,
and exposes the application instance used by ASGI servers.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from anyio import to_thread
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from redis.exceptions import RedisError
from sqlalchemy.exc import DBAPIError

from ai_bi_analytics.api.routes import health, query
from ai_bi_analytics.core import metrics
from ai_bi_analytics.core.config import Settings, get_settings
from ai_bi_analytics.core.errors import AppError, DependencyUnavailableError
from ai_bi_analytics.core.logging_config import setup_logging
from ai_bi_analytics.core.request_context import RequestIdMiddleware, error_body
from ai_bi_analytics.core.startup_checks import run_startup_checks
from ai_bi_analytics.core.telemetry import (
    SERVICE_VERSION,
    flush_telemetry,
    setup_telemetry,
)
from ai_bi_analytics.db.errors import translate_db_error
from ai_bi_analytics.db.session import assert_database_role_is_safe
from ai_bi_analytics.resources import ResourcesFactory, build_resources

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg: Settings = app.state.settings
    logger.info("Starting %s in %s", cfg.app_name, cfg.env)
    run_startup_checks(cfg)
    # Clients are built here, not at import (audit ARCH-2), and closed on
    # shutdown even when a later startup step fails.
    resources = app.state.resources_factory(cfg)
    app.state.resources = resources
    try:
        assert_database_role_is_safe(resources.engine, cfg.env)
        setup_telemetry(cfg, resources.engine)
        # The query route is synchronous and runs in this threadpool; see
        # docs/architecture.md for why, and how to size it.
        to_thread.current_default_thread_limiter().total_tokens = cfg.worker_threads
        yield
        flush_telemetry()
        logger.info("Shutting down %s", cfg.app_name)
    finally:
        resources.close()


def create_app(
    cfg: Settings | None = None,
    *,
    resources_factory: ResourcesFactory = build_resources,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        cfg: Settings; defaults to ``get_settings()`` (the environment).
        resources_factory: Builds the engine, Redis and LLM clients at
            startup. Tests pass one that returns in-memory fakes.

    Returns:
        FastAPI: Configured FastAPI application instance.
    """
    cfg = cfg or get_settings()
    setup_logging(cfg)

    app = FastAPI(
        title="AI-Powered Business Intelligence Backend",
        description=(
            "A production-grade backend service that enables "
            "natural-language querying over PostgreSQL with "
            "AI-powered SQL generation and explainable results."
        ),
        version=SERVICE_VERSION,
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.resources_factory = resources_factory

    # Health probes run every few seconds; tracing them is noise.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="api/health")
    register_exception_handlers(app)
    # Outermost: also turns unhandled exceptions into a JSON 500 with the
    # request id, instead of leaking or returning plain text.
    app.add_middleware(RequestIdMiddleware)

    app.include_router(query.router, prefix="/api")
    app.include_router(health.router, prefix="/api")

    return app


def _app_error_response(exc: AppError, request: Request) -> JSONResponse:
    metrics.errors.add(1, {"code": exc.code})
    return JSONResponse(
        # A fresh response would drop headers the route already set; keep
        # the rate-limit headers so clients see them on errors too.
        headers=getattr(request.state, "rate_limit_headers", None),
        status_code=exc.status_code,
        content=error_body(exc.code, exc.public_message),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """
    Typed errors to client-safe JSON (audit SEC-4). Bodies carry a
    message, a stable ``code`` and the ``request_id``; the underlying
    detail is only logged.
    """

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("%s: %s", exc.code, exc, exc_info=exc.__cause__)
        else:
            logger.warning("%s: %s", exc.code, exc)
        return _app_error_response(exc, request)

    @app.exception_handler(DBAPIError)
    async def handle_db_error(request: Request, exc: DBAPIError) -> JSONResponse:
        error = translate_db_error(exc)
        logger.error("Database error mapped to %s", error.code, exc_info=exc)
        return _app_error_response(error, request)

    @app.exception_handler(RedisError)
    async def handle_redis_error(request: Request, exc: RedisError) -> JSONResponse:
        logger.error("Redis error", exc_info=exc)
        return _app_error_response(DependencyUnavailableError(), request)


app = create_app()
