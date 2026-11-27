"""
Logging configuration (audit OPS-2).

- Level from ``LOG_LEVEL``; format from ``LOG_FORMAT`` (JSON outside
  development, text in development).
- Every record carries ``request_id``, ``trace_id`` and ``span_id``
  (see ``request_context.ContextLogFilter``).
- The JSON formatter includes ``extra={...}`` fields, so structured context
  (SQL, row counts, client id) reaches the log pipeline instead of being
  dropped by a text format string.
"""

import json
import logging
from logging.config import dictConfig
from typing import Any

from ai_bi_analytics.core.config import Settings, settings

TEXT_FORMAT = (
    "[%(asctime)s] %(levelname)s "
    "[request_id=%(request_id)s trace_id=%(trace_id)s span_id=%(span_id)s] "
    "[%(name)s:%(lineno)s] %(message)s"
)

# Attributes every LogRecord has; anything else came from `extra=`.
_STANDARD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "request_id", "trace_id", "span_id", "taskName"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line; extras are top-level keys."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "trace_id": getattr(record, "trace_id", "-"),
            "span_id": getattr(record, "span_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def build_logging_config(cfg: Settings) -> dict[str, Any]:
    formatter = "json" if cfg.effective_log_format == "json" else "text"
    handler = {
        "class": "logging.StreamHandler",
        "formatter": formatter,
        "filters": ["context"],
    }
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "text": {
                "format": TEXT_FORMAT,
                "datefmt": "%Y-%m-%d %H:%M:%S",
                "defaults": {"request_id": "-", "trace_id": "-", "span_id": "-"},
            },
            "json": {"()": "ai_bi_analytics.core.logging_config.JsonFormatter"},
        },
        "filters": {
            "context": {"()": "ai_bi_analytics.core.request_context.ContextLogFilter"}
        },
        "handlers": {"console": handler},
        "loggers": {
            # uvicorn configures its own handlers; route them through ours.
            name: {"handlers": ["console"], "level": cfg.log_level, "propagate": False}
            for name in ("uvicorn", "uvicorn.error", "uvicorn.access")
        },
        "root": {"handlers": ["console"], "level": cfg.log_level},
    }


def setup_logging(cfg: Settings = settings) -> None:
    dictConfig(build_logging_config(cfg))
