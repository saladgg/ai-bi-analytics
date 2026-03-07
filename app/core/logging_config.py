import os
from logging.config import dictConfig

DEBUG = os.getenv("DEBUG", "false").lower() == "true"
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "false").lower() == "true"


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": (
                "[%(asctime)s] %(levelname)s "
                "[trace_id=%(trace_id)s span_id=%(span_id)s] "
                "[%(name)s:%(lineno)s] "
                "%(message)s"
            ),
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "defaults": {"trace_id": "N/A", "span_id": "N/A"},  # Add defaults
        },
        "simple": {"format": "%(levelname)s [%(name)s] %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "DEBUG" if DEBUG else "INFO",
            "formatter": "verbose" if not DEBUG else "simple",
        },
    },
    "loggers": {
        "uvicorn": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "app": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "DEBUG" if DEBUG else "INFO",
    },
}


def setup_logging():
    dictConfig(LOGGING)
