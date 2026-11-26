"""
Query execution service.

Executes validated SQL queries against the database.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class QueryResult:
    rows: list[dict]
    # True when the query produced more than ``max_rows`` and the extra
    # rows were dropped (audit SEC-5).
    truncated: bool = False


def _fetch(db: Session, sql: str, max_rows: int | None) -> QueryResult:
    result = db.execute(text(sql))
    if max_rows is None:
        return QueryResult([dict(row._mapping) for row in result.fetchall()])
    # Never materialise more than one row past the cap, whatever the SQL
    # says; the guard's LIMIT is the first bound, this is the second.
    rows = result.fetchmany(max_rows + 1)
    return QueryResult(
        rows=[dict(row._mapping) for row in rows[:max_rows]],
        truncated=len(rows) > max_rows,
    )


def execute_query(db: Session, sql: str, max_rows: int | None = None) -> QueryResult:
    """
    Executes a validated SQL query.

    On Postgres the query runs inside an explicit ``READ ONLY``
    transaction that is always rolled back, so even SQL that slipped past
    the guard cannot persist anything (audit SEC-2). This is on top of the
    connection-level ``default_transaction_read_only`` set in
    ``db/session.py``.

    Args:
        db (Session): SQLAlchemy session.
        sql (str): Safe SQL query.
        max_rows (int | None): Most rows to return; ``truncated`` is set
            when the query produced more.

    Returns:
        QueryResult: Rows as dictionaries, plus the truncation flag.
    """

    if db.get_bind().dialect.name != "postgresql":
        return _fetch(db, sql, max_rows)

    # SET TRANSACTION must be the first statement of its transaction.
    db.rollback()
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))
        return _fetch(db, sql, max_rows)
    finally:
        db.rollback()
