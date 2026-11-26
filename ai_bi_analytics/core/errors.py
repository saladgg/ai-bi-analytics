"""
Typed application errors (audit SEC-4).

Each error carries the HTTP status and a message that is safe to show a
client. Internal details (database hosts, SQL errors, provider responses)
go to the server log with the request id and never into the response
body.
"""

from fastapi import status


class AppError(Exception):
    """Base class: an expected failure with a client-safe message."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    default_message: str = "Internal server error."

    def __init__(self, message: str | None = None) -> None:
        self.public_message = message or self.default_message
        super().__init__(self.public_message)


class UnsafeSQLError(AppError, ValueError):
    """Generated SQL was rejected by the guard or the database's policy."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "unsafe_sql"
    default_message = "The generated query was rejected."


class QueryExecutionError(AppError):
    """The generated SQL was valid and safe but failed when executed."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "query_failed"
    default_message = (
        "The generated query could not be executed. Try rephrasing the question."
    )


class QueryTimeoutError(AppError):
    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    code = "query_timeout"
    default_message = "The query took too long and was cancelled."


class LLMUnavailableError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "llm_unavailable"
    default_message = "The language model is unavailable. Try again shortly."


class DependencyUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "dependency_unavailable"
    default_message = "A backing service is unavailable. Try again shortly."
