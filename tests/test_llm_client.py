import pytest

from ai_bi_analytics.core.config import settings
from ai_bi_analytics.services.llm_client import BaseLLMClient, OpenAILLMClient, get_llm_client


def test_base_llm_client_complete_executes_abstract_body():
    class DummyClient(BaseLLMClient):
        def complete(self, prompt: str) -> str:
            # Execute the abstract base implementation (covers the `pass` line).
            BaseLLMClient.complete(self, prompt)
            return "ok"

    assert DummyClient().complete("prompt") == "ok"


def test_openai_llm_client_requires_api_key(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)

    with pytest.raises(ValueError) as exc:
        OpenAILLMClient()

    assert "OpenAI API key not configured" in str(exc.value)


def test_openai_llm_client_complete_strips_content(monkeypatch):
    class FakeOpenAI:
        def __init__(self, api_key: str):
            self.api_key = api_key

            class FakeChat:
                class FakeCompletions:
                    def create(self, **kwargs):
                        _ = kwargs  # keep kwargs visible for debugging
                        return type(
                            "Response",
                            (),
                            {
                                "choices": [
                                    type(
                                        "Choice",
                                        (),
                                        {
                                            "message": type(
                                                "Msg",
                                                (),
                                                {"content": "  hello from llm  \n"},
                                            )(),
                                        },
                                    )()
                                ]
                            },
                        )()

                completions = FakeCompletions()

            self.chat = FakeChat()

    monkeypatch.setattr("ai_bi_analytics.services.llm_client.OpenAI", FakeOpenAI)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")

    client = OpenAILLMClient()
    assert client.complete("prompt") == "hello from llm"


def test_get_llm_client_openai_provider(monkeypatch):
    class FakeOpenAILLMClient(OpenAILLMClient):
        def __init__(self) -> None:
            # Avoid calling the real OpenAILLMClient/OpenAI initialization.
            self.client = None

    # Avoid triggering the real OpenAILLMClient init/OpenAI call.
    monkeypatch.setattr("ai_bi_analytics.services.llm_client.OpenAILLMClient", FakeOpenAILLMClient)
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")

    # Monkeypatching the class is sufficient since __init__ will be inherited.
    client = get_llm_client()
    assert isinstance(client, FakeOpenAILLMClient)


def test_get_llm_client_unsupported_provider_raises(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "some-unknown-provider")

    with pytest.raises(ValueError) as exc:
        get_llm_client()

    assert "Unsupported LLM provider" in str(exc.value)

