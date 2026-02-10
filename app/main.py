"""
Application entry point.

Initializes FastAPI app, middleware, routing, and lifecycle events.
"""

from fastapi import FastAPI
from app.api.routes import query
from app.core.logging import setup_logging

def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        title="AI-Powered BI Backend",
        description="Natural language querying over PostgreSQL with explainable AI",
        version="1.0.0",
    )

    app.include_router(query.router, prefix="/api")

    return app

app = create_app()
