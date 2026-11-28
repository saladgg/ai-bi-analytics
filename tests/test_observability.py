"""
Logging, tracing and metrics (audit OPS-2).

OpenTelemetry allows one global provider per process, so this module
installs it once, with in-memory exporters, and the tests read spans and
metric deltas from them.
"""

import json
import logging
import sys
from collections import defaultdict

import openai
import pytest
from ai_bi_analytics.core import telemetry
from ai_bi_analytics.core.config import Settings
from ai_bi_analytics.core.logging_config import JsonFormatter, build_logging_config
from ai_bi_analytics.core.request_context import ContextLogFilter
from ai_bi_analytics.core.telemetry import (
    SERVICE_VERSION,
    build_resource,
    flush_telemetry,
    otlp_exporters,
    setup_telemetry,
)
from ai_bi_analytics.services.pipeline import question_log_fields
from opentelemetry import trace
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from pydantic import ValidationError

from tests.conftest import engine as test_engine
from tests.fakes import fake_openai_provider

SPANS = InMemorySpanExporter()
READER = InMemoryMetricReader()


def make_settings(**env) -> Settings:
    return Settings(
        _env_file=None, **{"API_KEY": "k", "DATABASE_URL": "sqlite://", **env}
    )


@pytest.fixture(scope="module", autouse=True)
def telemetry_on():
    assert setup_telemetry(
        make_settings(OTEL_ENABLED="true"),
        test_engine,
        span_exporter=SPANS,
        metric_reader=READER,
    )


@pytest.fixture(autouse=True)
def clear_spans():
    flush_telemetry()
    SPANS.clear()


def finished_spans():
    flush_telemetry()
    return SPANS.get_finished_spans()


def metric_points() -> dict[str, list[tuple[dict, float]]]:
    points: dict[str, list[tuple[dict, float]]] = defaultdict(list)
    data = READER.get_metrics_data()
    for resource_metrics in data.resource_metrics if data else []:
        for scope in resource_metrics.scope_metrics:
            for metric in scope.metrics:
                for point in metric.data.data_points:
                    # Counters have a value; histograms count observations.
                    value = getattr(point, "value", None)
                    if value is None:
                        value = getattr(point, "count")  # noqa: B009
                    points[metric.name].append((dict(point.attributes or {}), value))
    return points


def metric_total(name: str, **attrs) -> float:
    return sum(
        value
        for point_attrs, value in metric_points().get(name, [])
        if all(point_attrs.get(k) == v for k, v in attrs.items())
    )


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def test_disabled_telemetry_installs_nothing():
    assert setup_telemetry(make_settings(), test_engine) is False


def test_setup_is_idempotent():
    providers = telemetry._providers

    assert setup_telemetry(make_settings(OTEL_ENABLED="true"), test_engine)
    assert telemetry._providers is providers


def test_default_exporters_come_from_otlp_protocol(monkeypatch):
    created = []

    class FakeSpanExporter:
        def __init__(self):
            created.append("span")

        def export(self, spans):  # pragma: no cover - never flushed
            return None

        def shutdown(self):  # pragma: no cover
            return None

    class FakeMetricExporter:
        _preferred_temporality: dict = {}
        _preferred_aggregation: dict = {}

        def __init__(self):
            created.append("metric")

    protocols = []
    monkeypatch.setattr(telemetry, "_providers", None)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
    monkeypatch.setattr(
        telemetry,
        "otlp_exporters",
        lambda protocol: (
            protocols.append(protocol) or (FakeSpanExporter, FakeMetricExporter)
        ),
    )
    monkeypatch.setattr(
        telemetry,
        "PeriodicExportingMetricReader",
        lambda exporter: InMemoryMetricReader(),
    )
    for name in ("set_tracer_provider", "set_meter_provider"):
        target = telemetry.trace if name == "set_tracer_provider" else telemetry.metrics
        monkeypatch.setattr(target, name, lambda provider: None)
    monkeypatch.setattr(
        telemetry.SQLAlchemyInstrumentor, "instrument", lambda *a, **k: None
    )
    monkeypatch.setattr(telemetry.RedisInstrumentor, "instrument", lambda *a, **k: None)

    assert setup_telemetry(make_settings(OTEL_ENABLED="true"), test_engine)
    assert protocols == ["grpc"] and created == ["span", "metric"]


@pytest.mark.parametrize(
    "protocol, module",
    [
        ("grpc", "opentelemetry.exporter.otlp.proto.grpc"),
        ("http/protobuf", "opentelemetry.exporter.otlp.proto.http"),
    ],
)
def test_otlp_exporter_selection(protocol, module):
    span_cls, metric_cls = otlp_exporters(protocol)

    assert span_cls.__module__.startswith(module)
    assert metric_cls.__module__.startswith(module)


def test_unknown_otlp_protocol_rejected():
    with pytest.raises(ValueError, match="http/protobuf"):
        otlp_exporters("carrier-pigeon")


def test_resource_attributes(monkeypatch):
    attrs = build_resource(make_settings(ENV="staging", APP_NAME="bi")).attributes
    assert attrs["service.name"] == "bi"
    assert attrs["service.version"] == SERVICE_VERSION
    assert attrs["deployment.environment.name"] == "staging"

    monkeypatch.setenv("OTEL_SERVICE_NAME", "bi-eu")
    assert build_resource(make_settings()).attributes["service.name"] == "bi-eu"


def test_flush_is_a_noop_without_providers(monkeypatch):
    monkeypatch.setattr(telemetry, "_providers", None)

    flush_telemetry()


def test_openapi_reports_package_version(client):
    assert client.get("/openapi.json").json()["info"]["version"] == SERVICE_VERSION


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------

STAGES = [
    "query.scope",
    "query.cache_lookup",
    "query.generate_sql",
    "query.validate",
    "query.execute",
    "query.explain",
]


def test_query_produces_request_and_stage_spans(client, sample_products):
    assert (
        client.post("/api/query", json={"question": "show products"}).status_code == 200
    )

    spans = {span.name: span for span in finished_spans()}
    request = spans["POST /api/query"]
    for stage in STAGES:
        assert spans[stage].parent.span_id == request.context.span_id, stage
    assert spans["query.execute"].attributes["aibi.query.rows"] == 3
    assert spans["query.cache_lookup"].attributes["aibi.cache.hit"] is False

    # SQLAlchemy spans nest under the stage that ran them.
    execute = spans["query.execute"]
    sql_children = [
        s
        for s in finished_spans()
        if s.parent and s.parent.span_id == execute.context.span_id
    ]
    assert sql_children, "expected a SQLAlchemy span under query.execute"


def test_health_probes_are_not_traced(client):
    client.get("/api/health/live")
    client.get("/api/health/ready")

    assert not [s for s in finished_spans() if "health" in s.name]


def test_log_lines_carry_the_active_trace():
    tracer = trace.get_tracer("test")
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "m", None, None)

    with tracer.start_as_current_span("unit") as span:
        ContextLogFilter().filter(record)
        context = span.get_span_context()

    assert record.trace_id == format(context.trace_id, "032x")
    assert record.span_id == format(context.span_id, "016x")


# ---------------------------------------------------------------------------
# LLM span + metrics
# ---------------------------------------------------------------------------


def complete(provider, model="gpt-4o-mini"):
    return provider.complete(system="s", prompt="q", model=model, max_tokens=10)


def test_llm_call_span_and_token_metrics(monkeypatch, settings):
    provider = fake_openai_provider(monkeypatch, settings)
    before_in = metric_total("aibi.llm.tokens", type="input")
    before_out = metric_total("aibi.llm.tokens", type="output")
    before_ok = metric_total("aibi.llm.duration", outcome="ok")

    assert complete(provider).text == "SELECT 1"

    span = next(s for s in finished_spans() if s.name == "chat gpt-4o-mini")
    assert span.attributes["gen_ai.system"] == "openai"
    assert span.attributes["gen_ai.request.model"] == "gpt-4o-mini"
    assert span.attributes["gen_ai.request.max_tokens"] == 10
    assert span.attributes["gen_ai.usage.input_tokens"] == 120
    assert span.attributes["gen_ai.usage.output_tokens"] == 30
    assert metric_total("aibi.llm.tokens", type="input") - before_in == 120
    assert metric_total("aibi.llm.tokens", type="output") - before_out == 30
    assert metric_total("aibi.llm.duration", outcome="ok") - before_ok == 1


def test_llm_failure_records_error_outcome(monkeypatch, settings):
    request = sys.modules["httpx2"].Request("POST", "https://api.openai.com")
    provider = fake_openai_provider(
        monkeypatch, settings, raises=openai.APIConnectionError(request=request)
    )
    before = metric_total("aibi.llm.duration", outcome="error")

    with pytest.raises(Exception, match="unavailable"):
        complete(provider)

    assert metric_total("aibi.llm.duration", outcome="error") - before == 1


@pytest.mark.parametrize(
    "usage", [None, type("U", (), {"prompt_tokens": None, "completion_tokens": "x"})()]
)
def test_missing_or_odd_usage_is_ignored(monkeypatch, settings, usage):
    provider = fake_openai_provider(monkeypatch, settings, usage=usage)

    assert complete(provider).text == "SELECT 1"
    span = next(s for s in finished_spans() if s.name == "chat gpt-4o-mini")
    assert "gen_ai.usage.input_tokens" not in span.attributes


# ---------------------------------------------------------------------------
# Pipeline metrics
# ---------------------------------------------------------------------------


def test_query_metrics_llm_then_cache(client, sample_products):
    llm = metric_total("aibi.queries", source="llm", client_id="test-client")
    cache = metric_total("aibi.queries", source="cache", client_id="test-client")
    miss = metric_total("aibi.cache.lookups", result="miss")
    hit = metric_total("aibi.cache.lookups", result="hit")
    rows = metric_total("aibi.query.rows")

    for _ in range(2):
        client.post("/api/query", json={"question": "metrics question"})

    assert (
        metric_total("aibi.queries", source="llm", client_id="test-client") - llm == 1
    )
    assert (
        metric_total("aibi.queries", source="cache", client_id="test-client") - cache
        == 1
    )
    assert metric_total("aibi.cache.lookups", result="miss") - miss == 1
    assert metric_total("aibi.cache.lookups", result="hit") - hit == 1
    assert metric_total("aibi.query.rows") - rows == 1


def test_truncation_metric(client, sample_products, settings, monkeypatch):
    monkeypatch.setattr(settings, "max_result_rows", 1)
    before = metric_total("aibi.query.truncated")

    client.post("/api/query", json={"question": "truncate me"})

    assert metric_total("aibi.query.truncated") - before == 1


def test_error_metric_by_code(client, fake_llm):
    fake_llm.sql = "DROP TABLE products"
    before = metric_total("aibi.errors", code="unsafe_sql")

    assert client.post("/api/query", json={"question": "drop it"}).status_code == 422

    assert metric_total("aibi.errors", code="unsafe_sql") - before == 1


def test_internal_error_metric(raw_app):
    from fastapi.testclient import TestClient

    app = raw_app

    def boom():
        raise RuntimeError("x")

    app.add_api_route("/boom", boom)
    before = metric_total("aibi.errors", code="internal_error")
    with TestClient(app) as client:
        client.get("/boom")

    assert metric_total("aibi.errors", code="internal_error") - before == 1


def test_rate_limit_denial_metric(client, sample_products, settings):
    before = metric_total("aibi.rate_limit.denials")

    for _ in range(settings.rate_limit_requests + 1):
        client.post("/api/query", json={"question": "again and again"})

    assert metric_total("aibi.rate_limit.denials") - before == 1


# ---------------------------------------------------------------------------
# Logging configuration and policy
# ---------------------------------------------------------------------------


def make_record(msg="hello", **extra):
    record = logging.LogRecord("app.x", logging.WARNING, __file__, 7, msg, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    ContextLogFilter().filter(record)
    return record


def test_json_formatter_includes_context_and_extras():
    out = json.loads(JsonFormatter().format(make_record(sql="SELECT 1", row_count=3)))

    assert out["message"] == "hello"
    assert out["level"] == "WARNING"
    assert out["logger"] == "app.x"
    assert out["request_id"] == "-" and out["trace_id"] == "-"
    assert out["sql"] == "SELECT 1" and out["row_count"] == 3
    assert "lineno" not in out and "msg" not in out


def test_json_formatter_includes_exception():
    try:
        raise ValueError("bad")
    except ValueError:
        record = make_record()
        record.exc_info = sys.exc_info()

    assert "ValueError: bad" in json.loads(JsonFormatter().format(record))["exception"]


@pytest.mark.parametrize(
    "env, fmt, expected",
    [
        ({"ENV": "development"}, None, "text"),
        ({"ENV": "production"}, None, "json"),
        ({"ENV": "production"}, "text", "text"),
        ({"ENV": "development"}, "json", "json"),
    ],
)
def test_log_format_selection(env, fmt, expected):
    extra = {"LOG_FORMAT": fmt} if fmt else {}
    cfg = make_settings(**env, **extra)

    config = build_logging_config(cfg)
    assert cfg.effective_log_format == expected
    assert config["handlers"]["console"]["formatter"] == expected


def test_log_level_applied_and_validated():
    config = build_logging_config(make_settings(LOG_LEVEL="warning"))

    assert config["root"]["level"] == "WARNING"
    assert config["loggers"]["uvicorn.access"]["level"] == "WARNING"
    with pytest.raises(ValidationError, match="LOG_LEVEL"):
        make_settings(LOG_LEVEL="loud")


def test_questions_not_logged_by_default():
    fields = question_log_fields("revenue for customer Jane Doe", False)

    assert fields["question_length"] == 29
    assert len(fields["question_sha256"]) == 16
    assert "question" not in fields


def test_questions_logged_when_enabled():
    assert question_log_fields("q?", True) == {"question": "q?"}


def test_version_falls_back_without_package_metadata(monkeypatch, caplog):
    import importlib.metadata

    def missing(_name):
        raise importlib.metadata.PackageNotFoundError("ai-bi-analytics")

    monkeypatch.setattr(importlib.metadata, "version", missing)

    assert telemetry.package_version() == telemetry.UNKNOWN_VERSION
    assert "metadata not found" in caplog.text
