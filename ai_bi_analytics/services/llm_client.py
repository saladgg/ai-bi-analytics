"""
LLM client abstraction.

Encapsulates interaction with external LLM providers.
Allows swapping providers without affecting business logic.
"""

import time
from abc import ABC, abstractmethod

import openai
from openai import OpenAI
from opentelemetry import trace

from ai_bi_analytics.core import metrics
from ai_bi_analytics.core.config import settings
from ai_bi_analytics.core.errors import LLMUnavailableError

tracer = trace.get_tracer(__name__)


class BaseLLMClient(ABC):
    """
    Abstract base class for LLM providers.
    """

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> str:
        """
        Generate a completion.

        Args:
            prompt: The user message (may contain untrusted, tagged data).
            system: Instructions, sent as a separate system message.
        """
        pass


class OpenAILLMClient(BaseLLMClient):
    """
    OpenAI-based LLM implementation.
    """

    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise ValueError("OpenAI API key not configured")

        self.client = OpenAI(api_key=settings.openai_api_key)

    model = "gpt-4o-mini"

    def complete(self, prompt: str, system: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # openai 3.x's HTTP client has no auto-instrumentation, so the call
        # gets a manual span (GenAI semantic-convention attribute names),
        # a latency histogram and token counters (audit OPS-2).
        with tracer.start_as_current_span(f"chat {self.model}") as span:
            span.set_attribute("gen_ai.system", "openai")
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.request.model", self.model)
            started = time.perf_counter()
            outcome = "error"
            try:
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,  # type: ignore[arg-type]
                        max_tokens=250,
                        temperature=0.0,
                    )
                except openai.APIError as exc:
                    # Provider errors carry request ids, quota and account
                    # details; keep them in the log, not the response
                    # (audit SEC-4).
                    raise LLMUnavailableError() from exc

                self._record_usage(span, getattr(response, "usage", None))
                content = response.choices[0].message.content
                if not content:
                    raise LLMUnavailableError("The language model returned no answer.")
                outcome = "ok"
                return content.strip()
            finally:
                metrics.llm_duration.record(
                    time.perf_counter() - started,
                    {"model": self.model, "outcome": outcome},
                )

    def _record_usage(self, span: trace.Span, usage: object) -> None:
        if usage is None:
            return
        for token_type, field in (
            ("input", "prompt_tokens"),
            ("output", "completion_tokens"),
        ):
            count = getattr(usage, field, None)
            if isinstance(count, int):
                span.set_attribute(f"gen_ai.usage.{token_type}_tokens", count)
                metrics.llm_tokens.add(count, {"model": self.model, "type": token_type})


def get_llm_client() -> BaseLLMClient:
    """
    Factory method for selecting LLM provider.
    """
    if settings.llm_provider == "openai":
        return OpenAILLMClient()

    raise ValueError("Unsupported LLM provider")
