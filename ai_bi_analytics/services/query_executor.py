"""
Query execution service.

Executes validated SQL queries against the database.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session


def execute_query(db: Session, sql: str) -> list[dict]:
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

    Returns:
        list[dict]: Result rows as dictionaries.
    """

    if db.get_bind().dialect.name != "postgresql":
        result = db.execute(text(sql))
        return [dict(row._mapping) for row in result.fetchall()]

    # SET TRANSACTION must be the first statement of its transaction.
    db.rollback()
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))
        result = db.execute(text(sql))
        return [dict(row._mapping) for row in result.fetchall()]
    finally:
        db.rollback()
