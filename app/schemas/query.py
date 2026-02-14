"""
Request and response schemas for natural-language querying.
"""

from pydantic import BaseModel


class QueryRequest(BaseModel):
    """
    Input payload containing the user's natural-language question.
    """

    question: str


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
