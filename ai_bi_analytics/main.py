"""
Application entry point for the AI-Powered Business Intelligence Backend.

This module initializes the FastAPI application, configures middleware,
and exposes the application instance used by ASGI servers.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from ai_bi_analytics.api.routes import query
from ai_bi_analytics.core.config import settings
from ai_bi_analytics.core.logging_config import setup_logging
from ai_bi_analytics.db.session import assert_database_role_is_safe, engine


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logging.info("Starting %s in %s", settings.app_name, settings.env)
    assert_database_role_is_safe(engine, settings.env)
    yield


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

    # main endpoint
    app.include_router(query.router, prefix="/api")

    @app.get("/api/health", tags=["health"])
    def health_check() -> dict[str, str]:
        """
        Health check endpoint used for monitoring and orchestration.

        Returns:
            dict: Application health status.
        """
        return {"status": "ok"}

    return app


app = create_app()
