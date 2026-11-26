"""
Configuration checks run once at startup, in ``lifespan``.

Development keeps working with permissive defaults; any other ``ENV``
fails fast on settings that would be unsafe in a shared deployment.
"""

import logging

from ai_bi_analytics.core.config import Settings
from ai_bi_analytics.core.security import MIN_KEY_LENGTH, PLACEHOLDER_KEYS

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


def check_api_keys(cfg: Settings) -> None:
    """
    Audit SEC-8: a short or placeholder legacy API_KEY (e.g. the
    ``change-me`` from .env.example) is refused outside development.
    API_KEYS entries are hashes of generated keys, validated on load.
    """
    if cfg.api_key is None:
        return
    key = cfg.api_key.get_secret_value()
    problems = []
    if key.lower() in PLACEHOLDER_KEYS:
        problems.append("is a placeholder")
    if len(key) < MIN_KEY_LENGTH:
        problems.append(f"is shorter than {MIN_KEY_LENGTH} characters")
    if not problems:
        return
    message = f"API_KEY {' and '.join(problems)}."
    if cfg.env != DEVELOPMENT_ENV:
        raise UnsafeConfigurationError(
            message + " Generate keys with `python -m ai_bi_analytics.core.security"
            " <client_id>` and use API_KEYS."
        )
    logger.warning("%s Allowed only because ENV=%s.", message, cfg.env)


def run_startup_checks(cfg: Settings) -> None:
    check_query_scope(cfg)
    check_api_keys(cfg)
