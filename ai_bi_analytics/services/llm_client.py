"""
LLM client abstraction.

Encapsulates interaction with external LLM providers.
Allows swapping providers without affecting business logic.
"""

from abc import ABC, abstractmethod

import openai
from openai import OpenAI

from ai_bi_analytics.core.config import settings
from ai_bi_analytics.core.errors import LLMUnavailableError


class BaseLLMClient(ABC):
    """
    Abstract base class for LLM providers.
    """

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """
        Generate completion from prompt.
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

    def complete(self, prompt: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=250,
                temperature=0.0,
            )
        except openai.APIError as exc:
            # Provider errors carry request ids, quota and account details;
            # keep them in the log, not the response (audit SEC-4).
            raise LLMUnavailableError() from exc

        content = response.choices[0].message.content
        if not content:
            raise LLMUnavailableError("The language model returned no answer.")
        return content.strip()


def get_llm_client() -> BaseLLMClient:
    """
    Factory method for selecting LLM provider.
    """
    if settings.llm_provider == "openai":
        return OpenAILLMClient()

    raise ValueError("Unsupported LLM provider")
