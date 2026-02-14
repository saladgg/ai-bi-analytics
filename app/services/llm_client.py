"""
LLM client abstraction.

Encapsulates interaction with external LLM providers.
Allows swapping providers without affecting business logic.
"""

from abc import ABC, abstractmethod

from openai import OpenAI

from app.core.config import settings


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
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=250,
            temperature=0.0,
        )

        return response.choices[0].message.content.strip()


def get_llm_client() -> BaseLLMClient:
    """
    Factory method for selecting LLM provider.
    """
    if settings.llm_provider == "openai":
        return OpenAILLMClient()

    raise ValueError("Unsupported LLM provider")
