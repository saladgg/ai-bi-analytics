"""
Request and response schemas for natural-language querying.
"""

import re

from pydantic import BaseModel, Field, field_validator

from ai_bi_analytics.core.config import settings

MIN_QUESTION_LENGTH = 3

# C0 controls (except tab/newline/CR) and DEL: never meaningful in a
# question, and a common way to smuggle content past log or prompt review.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class QueryRequest(BaseModel):
    """
    Input payload containing the user's natural-language question.

    The question is bounded (audit SEC-6): it goes into an LLM prompt, so
    an unbounded one is a cost-amplification vector.
    """

    question: str = Field(
        description=(
            "Natural-language business question. Control characters are "
            "removed; length is limited by MAX_QUESTION_LENGTH."
        ),
        examples=["What are the top 3 products by revenue?"],
    )

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        value = _CONTROL_CHARS.sub("", value).strip()
        if len(value) < MIN_QUESTION_LENGTH:
            raise ValueError(
                f"question must be at least {MIN_QUESTION_LENGTH} characters"
            )
        if len(value) > settings.max_question_length:
            raise ValueError(
                f"question must be at most {settings.max_question_length} characters"
            )
        return value


class QueryResponse(BaseModel):
    """
    Structured response returned to the client.

    Attributes:
        sql (str): Generated SQL query.
        result (list[dict]): Query result rows.
        explanation (str): AI-generated explanation.
    """

    sql: str
    result: list[dict]
    explanation: str
