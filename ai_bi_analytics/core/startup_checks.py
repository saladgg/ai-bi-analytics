"""
Configuration checks run once at startup, in ``lifespan``.

Development keeps working with permissive defaults; any other ``ENV``
fails fast on settings that would be unsafe in a shared deployment.
"""

import logging

from ai_bi_analytics.core.config import Settings

logger = logging.getLogger(__name__)

DEVELOPMENT_ENV = "development"


class UnsafeConfigurationError(RuntimeError):
    """A setting is unsafe outside development."""


def check_query_scope(cfg: Settings) -> None:
    """
    Audit SEC-7: without an allowlist every table in the schema is shown to
    a third-party LLM and is queryable, so an explicit list is required
    outside development.
    """
    if cfg.queryable_tables:
        return
    message = (
        "QUERYABLE_TABLES is empty: every table in schema "
        f"'{cfg.queryable_schema}' is exposed to the LLM and queryable."
    )
    if cfg.env != DEVELOPMENT_ENV:
        raise UnsafeConfigurationError(message + " Set it explicitly.")
    logger.warning("%s Allowed only because ENV=%s.", message, cfg.env)


def run_startup_checks(cfg: Settings) -> None:
    check_query_scope(cfg)
