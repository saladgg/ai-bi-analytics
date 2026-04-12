"""
Query execution service.

Executes validated SQL queries against the database.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session


def execute_query(db: Session, sql: str) -> list[dict]:
    """
    Executes a validated SQL query.

    Args:
        db (Session): SQLAlchemy session.
        sql (str): Safe SQL query.

    Returns:
        list[dict]: Result rows as dictionaries.
    """

    result = db.execute(text(sql))
    rows = result.fetchall()

    return [dict(row._mapping) for row in rows]
