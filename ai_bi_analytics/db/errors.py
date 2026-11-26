"""
Map database driver errors to typed application errors (audit SEC-4).

Uses Postgres SQLSTATE codes where available, so the client gets an
accurate status without seeing the driver's message (which can contain
hosts, SQL text and object names).
"""

import psycopg2
from sqlalchemy.exc import DBAPIError

from ai_bi_analytics.core.errors import (
    AppError,
    DependencyUnavailableError,
    QueryExecutionError,
    QueryTimeoutError,
    UnsafeSQLError,
)

QUERY_CANCELED = "57014"  # statement_timeout fired
READ_ONLY_VIOLATIONS = frozenset(
    {
        "25006",  # read_only_sql_transaction
        "42501",  # insufficient_privilege
    }
)
UNAVAILABLE_CLASSES = ("08", "53", "57P")  # connection, resources, shutdown


def translate_db_error(exc: DBAPIError) -> AppError:
    pgcode = getattr(exc.orig, "pgcode", None)

    if pgcode == QUERY_CANCELED:
        return QueryTimeoutError()
    if pgcode in READ_ONLY_VIOLATIONS:
        return UnsafeSQLError(
            "The query was refused by the database's read-only policy."
        )
    if pgcode and pgcode.startswith(UNAVAILABLE_CLASSES):
        return DependencyUnavailableError()
    if exc.connection_invalidated or (
        pgcode is None and isinstance(exc.orig, psycopg2.OperationalError)
    ):
        # psycopg2 raises code-less OperationalErrors for connection
        # failures (refused, auth, DNS).
        return DependencyUnavailableError()
    return QueryExecutionError()
