"""
Request and response schemas for natural-language querying.
"""

import re

from pydantic import BaseModel, Field, field_validator

from ai_bi_analytics.core.config import get_settings

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
    explain: bool = Field(
        default=True,
        description=(
            "Ask the LLM to explain the result. false skips that second LLM "
            "call (faster, cheaper) and returns explanation: null."
        ),
    )

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        value = _CONTROL_CHARS.sub("", value).strip()
        if len(value) < MIN_QUESTION_LENGTH:
            raise ValueError(
                f"question must be at least {MIN_QUESTION_LENGTH} characters"
            )
        max_length = get_settings().max_question_length
        if len(value) > max_length:
            raise ValueError(f"question must be at most {max_length} characters")
        return value


class QueryResponse(BaseModel):
    """
    Structured response returned to the client.

    Attributes:
        sql (str): The executed SQL (the guard's canonical form).
        result (list[dict]): Query result rows, at most MAX_RESULT_ROWS.
        row_count (int): Number of rows in ``result``.
        truncated (bool): The query produced more rows than were returned.
        explanation (str | None): AI-generated explanation; null when the
            request set ``explain: false``.
        assumptions (list[str]): How the model interpreted ambiguous parts
            of the question; empty when nothing was ambiguous.
    """

    sql: str
    result: list[dict]
    row_count: int
    truncated: bool
    explanation: str | None
    assumptions: list[str] = Field(default_factory=list)
