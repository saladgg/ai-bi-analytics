"""
Logging configuration module.

Configures application-wide structured logging.
"""

import logging
from app.core.config import settings


def setup_logging() -> None:
    """
    Configure root logger based on application settings.
    """

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    logging.getLogger("uvicorn").setLevel(settings.log_level.upper())
