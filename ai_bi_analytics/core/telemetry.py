"""
OpenTelemetry setup (audit OPS-2).

Disabled unless ``OTEL_ENABLED=true``. When enabled, traces and metrics are
exported over OTLP, configured by the standard environment variables
(``OTEL_EXPORTER_OTLP_ENDPOINT``, ``OTEL_EXPORTER_OTLP_PROTOCOL`` =
``http/protobuf`` (default) or ``grpc``, ``OTEL_EXPORTER_OTLP_HEADERS``, ...).
``OTEL_SERVICE_NAME`` overrides the service name (default ``APP_NAME``).

Instrumented: FastAPI requests, SQLAlchemy queries, Redis commands, plus
the manual pipeline and LLM spans and the metrics in ``core/metrics.py``.
Without a provider all of that is a no-op.

OpenTelemetry allows one global provider per process, so setup is
idempotent; the SDK flushes and shuts down at interpreter exit.
"""

import importlib.metadata
import logging
import os
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from sqlalchemy import Engine

from ai_bi_analytics.core.config import Settings

logger = logging.getLogger(__name__)

UNKNOWN_VERSION = "0+unknown"


def package_version() -> str:
    """
    The installed package version. Falls back (with a warning) instead of
    crashing when the project's metadata isn't installed, e.g. running from
    a source checkout without `uv sync`.
    """
    try:
        return importlib.metadata.version("ai-bi-analytics")
    except importlib.metadata.PackageNotFoundError:
        logger.warning("ai-bi-analytics package metadata not found; version unknown")
        return UNKNOWN_VERSION


SERVICE_VERSION = package_version()

_providers: tuple[TracerProvider, MeterProvider] | None = None


def otlp_exporters(protocol: str) -> tuple[Any, Any]:
    """Span and metric exporter classes for an OTLP protocol."""
    if protocol == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
    elif protocol == "http/protobuf":
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (  # type: ignore[assignment]
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[assignment]
            OTLPSpanExporter,
        )
    else:
        raise ValueError(
            f"Unsupported OTEL_EXPORTER_OTLP_PROTOCOL {protocol!r}; "
            "use 'http/protobuf' or 'grpc'"
        )
    return OTLPSpanExporter, OTLPMetricExporter


def build_resource(cfg: Settings) -> Resource:
    return Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME") or cfg.app_name,
            "service.version": SERVICE_VERSION,
            "deployment.environment.name": cfg.env,
        }
    )


def setup_telemetry(
    cfg: Settings,
    engine: Engine,
    *,
    span_exporter: SpanExporter | None = None,
    metric_reader: MetricReader | None = None,
) -> bool:
    """
    Installs the global tracer/meter providers and instrumentation.

    The exporter/reader arguments exist for tests; production uses OTLP.

    Returns:
        bool: whether telemetry is active.
    """
    global _providers
    if not cfg.otel_enabled:
        return False
    if _providers is not None:
        return True

    if span_exporter is None or metric_reader is None:
        protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
        span_cls, metric_cls = otlp_exporters(protocol)
        span_exporter = span_exporter or span_cls()
        metric_reader = metric_reader or PeriodicExportingMetricReader(metric_cls())

    resource = build_resource(cfg)
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)

    # opentelemetry-instrumentation-sqlalchemy (0.66b2, latest) declares
    # sqlalchemy < 2.1 and otherwise silently instruments nothing. It only
    # hooks the stable before/after_cursor_execute events, which 2.1 keeps,
    # so skip the version gate; tests/test_observability.py asserts SQL
    # spans appear, so CI fails if that ever stops holding. Remove the
    # override once upstream declares 2.1 support.
    SQLAlchemyInstrumentor().instrument(engine=engine, skip_dep_check=True)
    RedisInstrumentor().instrument()

    _providers = (tracer_provider, meter_provider)
    logger.info("OpenTelemetry enabled", extra={"service_version": SERVICE_VERSION})
    return True


def flush_telemetry() -> None:
    """Push buffered spans and metrics (e.g. before shutdown)."""
    if _providers is None:
        return
    tracer_provider, meter_provider = _providers
    tracer_provider.force_flush()
    meter_provider.force_flush()
