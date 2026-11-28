"""
LLM access (audit ARCH-3, PERF-2).

Two layers:

- ``ChatProvider``: one chat completion against a vendor API. Providers
  register by name (``register_provider``) and ``LLM_PROVIDER`` selects
  one. A provider owns one SDK client (and its HTTP pool) for the life of
  the process, with a request timeout and bounded retries.
- ``LLMClient``: the tasks the pipeline needs, ``generate_sql`` (structured
  output) and ``explain``, each with its own model and token cap. Both
  return the provider's token usage.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import openai
from openai import OpenAI
from opentelemetry import trace

from ai_bi_analytics.core import metrics
from ai_bi_analytics.core.config import Settings
from ai_bi_analytics.core.errors import LLMUnavailableError
from ai_bi_analytics.services.explanation import (
    EXPLANATION_RULES,
    build_explanation_prompt,
)
from ai_bi_analytics.services.nl_to_sql import (
    SQL_GENERATION_RULES,
    SQL_RESPONSE_SCHEMA,
    build_sql_prompt,
    parse_sql_response,
)
from ai_bi_analytics.services.query_executor import QueryResult

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: "LLMUsage") -> "LLMUsage":
        return LLMUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
        )


@dataclass(frozen=True)
class ResponseFormat:
    """A JSON schema the completion must follow (structured output)."""

    name: str
    schema: dict[str, Any]


SQL_RESPONSE_FORMAT = ResponseFormat("sql_query", SQL_RESPONSE_SCHEMA)


@dataclass(frozen=True)
class Completion:
    text: str
    usage: LLMUsage = field(default_factory=LLMUsage)


class ChatProvider(Protocol):
    name: str

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str,
        max_tokens: int,
        response_format: ResponseFormat | None = None,
    ) -> Completion:
        """
        One chat completion.

        Args:
            system: Instructions, sent as the system message.
            prompt: The user message (may contain untrusted, tagged data).

        Raises:
            LLMUnavailableError: the provider failed or returned nothing.
        """
        ...  # pragma: no cover

    def close(self) -> None: ...  # pragma: no cover


ProviderFactory = Callable[[Settings], ChatProvider]
_PROVIDERS: dict[str, ProviderFactory] = {}


def register_provider(name: str) -> Callable[[ProviderFactory], ProviderFactory]:
    """Makes a provider selectable with ``LLM_PROVIDER=<name>``."""

    def decorator(factory: ProviderFactory) -> ProviderFactory:
        _PROVIDERS[name] = factory
        return factory

    return decorator


def registered_providers() -> list[str]:
    return sorted(_PROVIDERS)


def build_provider(cfg: Settings) -> ChatProvider:
    try:
        factory = _PROVIDERS[cfg.llm_provider]
    except KeyError:
        raise ValueError(
            f"Unsupported LLM_PROVIDER {cfg.llm_provider!r}; "
            f"registered: {', '.join(registered_providers())}"
        ) from None
    return factory(cfg)


@register_provider("openai")
class OpenAIProvider:
    """OpenAI chat completions."""

    name = "openai"

    def __init__(self, cfg: Settings) -> None:
        key = cfg.openai_api_key.get_secret_value() if cfg.openai_api_key else ""
        self._client: OpenAI | None = None
        if not key:
            # The app still starts (health checks, local work without a
            # key); queries fail with llm_unavailable. Outside development
            # the startup checks refuse to boot instead.
            logger.warning("OPENAI_API_KEY is not set; LLM requests will fail")
            return
        # One client, one HTTP pool, per process (audit PERF-2). The SDK
        # retries connection errors, 408/409/429 and 5xx with backoff.
        self._client = OpenAI(
            api_key=key,
            timeout=cfg.llm_timeout_seconds,
            max_retries=cfg.llm_max_retries,
        )

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str,
        max_tokens: int,
        response_format: ResponseFormat | None = None,
    ) -> Completion:
        if self._client is None:
            raise LLMUnavailableError("The language model is not configured.")

        request: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }
        if response_format is not None:
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_format.name,
                    "schema": response_format.schema,
                    "strict": True,
                },
            }

        # openai 3.x's HTTP client has no auto-instrumentation, so the call
        # gets a manual span (GenAI semantic-convention attribute names),
        # a latency histogram and token counters (audit OPS-2).
        with tracer.start_as_current_span(f"chat {model}") as span:
            span.set_attribute("gen_ai.system", self.name)
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.request.model", model)
            span.set_attribute("gen_ai.request.max_tokens", max_tokens)
            started = time.perf_counter()
            outcome = "error"
            try:
                try:
                    response = self._client.chat.completions.create(**request)
                except openai.APIError as exc:
                    # Provider errors carry request ids, quota and account
                    # details; keep them in the log, not the response
                    # (audit SEC-4).
                    raise LLMUnavailableError() from exc

                usage = _usage(getattr(response, "usage", None))
                _record_usage(span, model, usage)
                choice = response.choices[0]
                if choice.finish_reason == "length":
                    logger.warning(
                        "LLM output hit max_tokens",
                        extra={"model": model, "max_tokens": max_tokens},
                    )
                content = choice.message.content
                if not content:
                    raise LLMUnavailableError("The language model returned no answer.")
                outcome = "ok"
                return Completion(content.strip(), usage)
            finally:
                metrics.llm_duration.record(
                    time.perf_counter() - started,
                    {"model": model, "outcome": outcome},
                )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


def _usage(usage: object) -> LLMUsage:
    counts = [getattr(usage, f, None) for f in ("prompt_tokens", "completion_tokens")]
    return LLMUsage(*(c if isinstance(c, int) else 0 for c in counts))


def _record_usage(span: trace.Span, model: str, usage: LLMUsage) -> None:
    for token_type, count in (
        ("input", usage.input_tokens),
        ("output", usage.output_tokens),
    ):
        if count:
            span.set_attribute(f"gen_ai.usage.{token_type}_tokens", count)
            metrics.llm_tokens.add(count, {"model": model, "type": token_type})


@dataclass(frozen=True)
class GeneratedSQL:
    sql: str
    # As reported by the model: informational only; the SQL guard decides
    # what the query may read.
    tables_used: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    usage: LLMUsage = field(default_factory=LLMUsage)


@dataclass(frozen=True)
class Explanation:
    text: str
    usage: LLMUsage = field(default_factory=LLMUsage)


class LLMClient:
    """The pipeline's LLM tasks, each with its own model and token cap."""

    def __init__(self, provider: ChatProvider, cfg: Settings) -> None:
        self.provider = provider
        self._cfg = cfg

    def generate_sql(self, question: str, schema_description: str) -> GeneratedSQL:
        completion = self.provider.complete(
            system=SQL_GENERATION_RULES,
            prompt=build_sql_prompt(question, schema_description),
            model=self._cfg.llm_sql_model,
            max_tokens=self._cfg.llm_sql_max_tokens,
            response_format=SQL_RESPONSE_FORMAT,
        )
        parsed = parse_sql_response(completion.text)
        return GeneratedSQL(
            sql=parsed.sql,
            tables_used=parsed.tables_used,
            assumptions=parsed.assumptions,
            usage=completion.usage,
        )

    def explain(self, question: str, sql: str, result: QueryResult) -> Explanation:
        completion = self.provider.complete(
            system=EXPLANATION_RULES,
            prompt=build_explanation_prompt(
                question, sql, result, self._cfg.explanation_sample_rows
            ),
            model=self._cfg.llm_explain_model,
            max_tokens=self._cfg.llm_explain_max_tokens,
        )
        return Explanation(completion.text, completion.usage)

    def close(self) -> None:
        self.provider.close()
