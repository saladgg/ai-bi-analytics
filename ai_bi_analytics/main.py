"""
Application entry point for the AI-Powered Business Intelligence Backend.

This module initializes the FastAPI application, configures middleware,
and exposes the application instance used by ASGI servers.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from redis.exceptions import RedisError
from sqlalchemy.exc import DBAPIError

from ai_bi_analytics.api.routes import health, query
from ai_bi_analytics.core import redis_client as redis_module
from ai_bi_analytics.core.config import settings
from ai_bi_analytics.core.errors import AppError, DependencyUnavailableError
from ai_bi_analytics.core.logging_config import setup_logging
from ai_bi_analytics.core.request_context import RequestIdMiddleware, error_body
from ai_bi_analytics.core.startup_checks import run_startup_checks
from ai_bi_analytics.db.errors import translate_db_error
from ai_bi_analytics.db.session import assert_database_role_is_safe, engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logging.info("Starting %s in %s", settings.app_name, settings.env)
    run_startup_checks(settings)
    assert_database_role_is_safe(engine, settings.env)
    yield
    # Graceful shutdown (audit OPS-3): close pooled connections so Postgres
    # and Redis see clean disconnects rather than dropped sockets.
    logging.info("Shutting down %s", settings.app_name)
    engine.dispose()
    redis_module.redis_client.close()


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        FastAPI: Configured FastAPI application instance.
    """

    setup_logging()

    app = FastAPI(
        title="AI-Powered Business Intelligence Backend",
        description=(
            "A production-grade backend service that enables "
            "natural-language querying over PostgreSQL with "
            "AI-powered SQL generation and explainable results."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    FastAPIInstrumentor.instrument_app(app)
    register_exception_handlers(app)
    # Outermost: also turns unhandled exceptions into a JSON 500 with the
    # request id, instead of leaking or returning plain text.
    app.add_middleware(RequestIdMiddleware)

    app.include_router(query.router, prefix="/api")
    app.include_router(health.router, prefix="/api")

    return app


def _app_error_response(exc: AppError) -> JSONResponse:
    return JSONResponse(
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
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("%s: %s", exc.code, exc, exc_info=exc.__cause__)
        else:
            logger.warning("%s: %s", exc.code, exc)
        return _app_error_response(exc)

    @app.exception_handler(DBAPIError)
    async def handle_db_error(_request: Request, exc: DBAPIError) -> JSONResponse:
        error = translate_db_error(exc)
        logger.error("Database error mapped to %s", error.code, exc_info=exc)
        return _app_error_response(error)

    @app.exception_handler(RedisError)
    async def handle_redis_error(_request: Request, exc: RedisError) -> JSONResponse:
        logger.error("Redis error", exc_info=exc)
        return _app_error_response(DependencyUnavailableError())


app = create_app()
