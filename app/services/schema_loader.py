"""
Schema introspection service.

Extracts database schema dynamically to provide
accurate context to the LLM.
"""

from sqlalchemy import inspect
from sqlalchemy.orm import Session


def load_schema_metadata(db: Session) -> str:
    """
    Extracts table and column metadata for LLM context.

    Returns:
        str: Schema description formatted for prompting.
    """

    inspector = inspect(db.bind)
    schema_description = ""

    for table_name in inspector.get_table_names():
        columns = inspector.get_columns(table_name)
        column_defs = ", ".join(f"{col['name']} {col['type']}" for col in columns)
        schema_description += f"{table_name}({column_defs})\n"

    return schema_description
