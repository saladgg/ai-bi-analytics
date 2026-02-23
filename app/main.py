"""
Application entry point for the AI-Powered Business Intelligence Backend.

This module initializes the FastAPI application, configures middleware,
and exposes the application instance used by ASGI servers.
"""

from fastapi import FastAPI

from app.api.routes import query
from app.core.config import settings
from app.core.logging import setup_logging


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
    )

    @app.on_event("startup")
    def startup_event():
        import logging

        logging.info(f"Starting {settings.app_name} in {settings.env}")

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
