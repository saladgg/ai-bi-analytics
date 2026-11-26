"""
Schema introspection service.

Builds the *query scope*: the tables and columns the LLM is shown and the
SQL guard lets a query read (audit SEC-7). Both use the same object, so
the model can't be told about something it isn't allowed to query, or
the other way round.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from ai_bi_analytics.core.config import Settings, settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueryScope:
    schema: str
    # table -> visible (name, type) columns, in database order
    columns: dict[str, list[tuple[str, str]]]
    # table -> lower-cased column names hidden from the LLM and the guard
    redacted: dict[str, frozenset[str]] = field(default_factory=dict)

    @property
    def tables(self) -> frozenset[str]:
        return frozenset(self.columns)

    @property
    def description(self) -> str:
        """Schema text for the LLM prompt (visible columns only)."""
        return "".join(
            f"{table}({', '.join(f'{name} {type_}' for name, type_ in cols)})\n"
            for table, cols in self.columns.items()
        )


def _parse_redactions(entries: list[str]) -> tuple[dict[str, set[str]], set[str]]:
    per_table: dict[str, set[str]] = {}
    everywhere: set[str] = set()
    for entry in entries:
        if "." in entry:
            table, column = entry.lower().split(".")
            per_table.setdefault(table, set()).add(column)
        else:
            everywhere.add(entry.lower())
    return per_table, everywhere


def load_query_scope(db: Session, cfg: Settings = settings) -> QueryScope:
    """
    Introspects the queryable schema (tables and views), applies
    ``QUERYABLE_TABLES`` and ``REDACTED_COLUMNS``.
    """
    bind = db.get_bind()
    inspector = inspect(bind)
    # SQLite (tests) has no schemas; Postgres uses the configured one.
    schema = cfg.queryable_schema if bind.dialect.name == "postgresql" else None

    names = sorted(
        set(inspector.get_table_names(schema=schema))
        | set(inspector.get_view_names(schema=schema))
    )

    if cfg.queryable_tables:
        wanted = {t.lower() for t in cfg.queryable_tables}
        missing = wanted - {n.lower() for n in names}
        if missing:
            logger.warning(
                "QUERYABLE_TABLES entries not found in schema %s: %s",
                cfg.queryable_schema,
                sorted(missing),
            )
        names = [n for n in names if n.lower() in wanted]

    redact_by_table, redact_everywhere = _parse_redactions(cfg.redacted_columns)

    columns: dict[str, list[tuple[str, str]]] = {}
    redacted: dict[str, frozenset[str]] = {}
    for table in names:
        hidden = redact_by_table.get(table.lower(), set()) | redact_everywhere
        visible: list[tuple[str, str]] = []
        removed: set[str] = set()
        for col in inspector.get_columns(table, schema=schema):
            if col["name"].lower() in hidden:
                removed.add(col["name"].lower())
            else:
                visible.append((col["name"], str(col["type"])))
        columns[table] = visible
        if removed:
            redacted[table] = frozenset(removed)

    return QueryScope(schema=cfg.queryable_schema, columns=columns, redacted=redacted)
