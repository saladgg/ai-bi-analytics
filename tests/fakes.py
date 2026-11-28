"""
In-memory stand-ins for the app's external clients.
"""

import json
from dataclasses import dataclass, field

from ai_bi_analytics.services.llm_client import Completion, LLMUsage, ResponseFormat

DEFAULT_SQL = "SELECT * FROM products;"
DEFAULT_EXPLANATION = "Fake explanation."


@dataclass
class FakeProvider:
    """
    A ``ChatProvider`` that answers SQL-generation requests (the ones with
    a response format) with ``sql`` and everything else with
    ``explanation``. ``sql`` is sent as-is: plain SQL exercises the
    fallback parser, a JSON string the structured-output path. Every call
    is recorded.
    """

    sql: str = DEFAULT_SQL
    explanation: str = DEFAULT_EXPLANATION
    usage: LLMUsage = field(default_factory=lambda: LLMUsage(10, 5))
    calls: list[dict] = field(default_factory=list)
    closed: bool = False
    name: str = "fake"

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str,
        max_tokens: int,
        response_format: ResponseFormat | None = None,
    ) -> Completion:
        self.calls.append(
            {
                "system": system,
                "prompt": prompt,
                "model": model,
                "max_tokens": max_tokens,
                "response_format": response_format,
            }
        )
        text = self.sql if response_format is not None else self.explanation
        return Completion(text, self.usage)

    def close(self) -> None:
        self.closed = True

    def answer_json(self, sql: str, tables_used=(), assumptions=()) -> None:
        self.sql = json.dumps(
            {
                "sql": sql,
                "tables_used": list(tables_used),
                "assumptions": list(assumptions),
            }
        )

    @property
    def sql_calls(self) -> list[dict]:
        return [c for c in self.calls if c["response_format"] is not None]

    @property
    def explain_calls(self) -> list[dict]:
        return [c for c in self.calls if c["response_format"] is None]


DEFAULT_USAGE = object()


def fake_openai_provider(
    monkeypatch,
    settings,
    *,
    raises: Exception | None = None,
    content: str | None = "SELECT 1",
    usage: object = DEFAULT_USAGE,
    finish_reason: str = "stop",
    sent: list[dict] | None = None,
):
    """
    An ``OpenAIProvider`` whose SDK client is a stub: it records each
    request's kwargs in ``sent`` and answers with ``content`` (or raises).
    """
    from ai_bi_analytics.services import llm_client
    from pydantic import SecretStr

    if usage is DEFAULT_USAGE:
        usage = type("U", (), {"prompt_tokens": 120, "completion_tokens": 30})()

    class Completions:
        def create(self, **kwargs):
            if sent is not None:
                sent.append(kwargs)
            if raises:
                raise raises
            message = type("M", (), {"content": content})()
            choice = type(
                "C", (), {"message": message, "finish_reason": finish_reason}
            )()
            return type("R", (), {"choices": [choice], "usage": usage})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            self.chat = type("Chat", (), {"completions": Completions()})()

        def close(self):
            self.closed = True

    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("sk-test"))
    return llm_client.OpenAIProvider(settings)
