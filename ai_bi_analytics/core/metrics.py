"""
Application metrics (audit OPS-2).

Instruments are created on OpenTelemetry's proxy meter at import time:
they record nothing until ``core.telemetry.setup_telemetry`` installs a
provider, and then start exporting without being re-created.

Attribute values are low-cardinality on purpose (model, outcome, error
code, client id); questions, SQL and table names stay in logs and traces.
"""

from opentelemetry import metrics

_meter = metrics.get_meter("ai_bi_analytics")

queries = _meter.create_counter(
    "aibi.queries",
    description="Answered /api/query requests, by source (llm or cache).",
)
llm_duration = _meter.create_histogram(
    "aibi.llm.duration",
    unit="s",
    description="LLM call latency, by model and outcome.",
)
llm_tokens = _meter.create_counter(
    "aibi.llm.tokens",
    unit="{token}",
    description="LLM tokens, by model and type (input or output).",
)
cache_lookups = _meter.create_counter(
    "aibi.cache.lookups",
    description="Response cache lookups, by result (hit, miss or error).",
)
schema_cache_lookups = _meter.create_counter(
    "aibi.schema_cache.lookups",
    description="Query-scope cache lookups, by result (hit or miss).",
)
errors = _meter.create_counter(
    "aibi.errors",
    description="Client-visible errors, by stable error code.",
)
rate_limit_denials = _meter.create_counter(
    "aibi.rate_limit.denials",
    description="Requests rejected by the rate limiter.",
)
rate_limit_fail_open = _meter.create_counter(
    "aibi.rate_limit.fail_open",
    description="Requests served unthrottled because Redis was unreachable.",
)
query_rows = _meter.create_histogram(
    "aibi.query.rows",
    unit="{row}",
    description="Rows returned per executed query.",
)
query_truncations = _meter.create_counter(
    "aibi.query.truncated",
    description="Executed queries whose result hit MAX_RESULT_ROWS.",
)
