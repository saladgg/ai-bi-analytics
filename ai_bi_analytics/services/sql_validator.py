"""
SQL guard for LLM-generated queries (audit SEC-1, CQ-1).

The model's output is attacker-influenced (the user's question goes into
its prompt), so this treats it as untrusted input. The SQL is parsed into
an AST (sqlglot, Postgres dialect) and accepted only if it is:

- exactly one statement,
- a read query (``SELECT``, set operations, ``WITH ... SELECT``),
- free of any write, DDL, transaction, ``COPY``, ``SELECT INTO`` or
  row-locking construct anywhere in the tree (including inside CTEs),
- free of dangerous functions (server files, large objects, sleeps,
  settings, sequences, dblink, XML query helpers),
- reading only known tables in the queryable schema, never system
  catalogs,
- not touching redacted columns: no explicit reference, no ``*`` and no
  whole-row reference on a table that has them (audit SEC-7).

``validate_sql`` returns SQL **regenerated from the validated AST**, and
that is what gets executed. What was checked is exactly what runs, so
tricks that make this parser and Postgres disagree have nothing to
exploit. Comments are dropped in the process.

Parsing also removes the old substring checks' false positives
(``created_at`` was rejected for containing ``CREATE``, and every CTE was
rejected for not starting with ``SELECT``).

The database's read-only role (``db/session.py``, SEC-2) is the backstop
if anything here is ever wrong.
"""

import re
from collections.abc import Collection, Mapping

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from ai_bi_analytics.core.errors import UnsafeSQLError

__all__ = ["UnsafeSQLError", "strip_code_fences", "validate_sql"]

DIALECT = "postgres"


READ_ROOTS: tuple[type[exp.Expression], ...] = (exp.Select, exp.SetOperation)

# Any of these anywhere in the tree rejects the query.
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Copy,
    exp.Grant,
    exp.Revoke,
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Command,  # statements sqlglot doesn't model (DO, CALL, VACUUM, ...)
    exp.Into,  # SELECT ... INTO new_table
    exp.Lock,  # FOR UPDATE / FOR SHARE
    exp.LoadData,
    exp.Analyze,
    exp.Execute,
    exp.Declare,
    exp.Kill,
    exp.Comment,
    exp.Use,
    exp.Pragma,
)

BLOCKED_SCHEMAS = frozenset({"pg_catalog", "information_schema", "pg_toast"})
DEFAULT_SCHEMA = "public"

BLOCKED_FUNCTION_PREFIXES = (
    "pg_",  # pg_sleep, pg_read_file, pg_ls_dir, pg_terminate_backend, ...
    "lo_",  # large objects: lo_import / lo_export touch server files
    "dblink",
    "query_to_xml",
    "table_to_xml",
    "cursor_to_xml",
    "schema_to_xml",
    "database_to_xml",
)
BLOCKED_FUNCTIONS = frozenset(
    {
        "set_config",
        "current_setting",
        "nextval",
        "setval",
        "currval",
        "lastval",
        "txid_current",
        "inet_server_addr",
        "inet_server_port",
        "inet_client_addr",
        "inet_client_port",
        "current_query",
    }
)

_CODE_FENCE = re.compile(r"^\s*```[A-Za-z]*\s*(.*?)\s*```\s*$", re.DOTALL)


def strip_code_fences(sql: str) -> str:
    """Models often wrap SQL in ```sql fences despite instructions."""
    match = _CODE_FENCE.match(sql)
    return match.group(1) if match else sql


def _function_name(func: exp.Func) -> str:
    if isinstance(func, exp.Anonymous):
        return func.name.lower()
    return func.sql_name().lower()


def _is_blocked_function(name: str) -> bool:
    return name in BLOCKED_FUNCTIONS or name.startswith(BLOCKED_FUNCTION_PREFIXES)


def _cte_names(tree: exp.Expression) -> set[str]:
    return {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}


def _check_table(
    table: exp.Table,
    cte_names: set[str],
    allowed_exact: set[str] | None,
    allowed_folded: set[str] | None,
    queryable_schema: str,
) -> None:
    if not isinstance(table.this, exp.Identifier):
        # Table-valued function (e.g. generate_series); functions are
        # checked separately.
        return

    name = table.name
    schema = table.db.lower()

    if table.catalog:
        raise UnsafeSQLError("Cross-database table references are not allowed.")
    if schema in BLOCKED_SCHEMAS or name.lower().startswith("pg_"):
        raise UnsafeSQLError("System catalogs are not queryable.")
    if schema not in ("", queryable_schema.lower()):
        raise UnsafeSQLError(f"Schema '{table.db}' is not queryable.")

    if not schema and name.lower() in cte_names:
        return

    if allowed_exact is None or allowed_folded is None:
        return

    quoted = table.this.quoted
    known = name in allowed_exact if quoted else name.lower() in allowed_folded
    if not known:
        raise UnsafeSQLError(f"Unknown table '{name}'.")


def _is_count_star(star: exp.Star) -> bool:
    parent = star.parent
    if isinstance(parent, exp.Column):  # COUNT(t.*)
        parent = parent.parent
    return isinstance(parent, exp.Count)


def _check_redactions(
    tree: exp.Expression, redacted_columns: Mapping[str, Collection[str]]
) -> None:
    """
    Conservative by design: blocks a redacted column name wherever it
    appears (even qualified by another table), any ``*`` other than
    ``COUNT(*)``, and bare references to a restricted table's name or alias
    (whole-row values such as ``row_to_json(u)``). The database's column
    privileges are the authoritative control; see example/readonly_role.sql.
    """
    restricted = {
        t.lower(): {c.lower() for c in cols}
        for t, cols in redacted_columns.items()
        if cols
    }
    referenced = {
        table.name.lower(): table.alias_or_name.lower()
        for table in tree.find_all(exp.Table)
        if table.name.lower() in restricted
    }
    if not referenced:
        return

    hidden = set().union(*(restricted[t] for t in referenced))
    row_names = set(referenced) | set(referenced.values())

    for star in tree.find_all(exp.Star):
        if not _is_count_star(star):
            raise UnsafeSQLError(
                "SELECT * is not allowed on tables with restricted columns; "
                "list the columns instead."
            )
    for column in tree.find_all(exp.Column):
        name = column.name.lower()
        if name in hidden:
            raise UnsafeSQLError(f"Column '{column.name}' is not queryable.")
        if not column.table and name in row_names:
            raise UnsafeSQLError(
                f"Whole-row references to '{column.name}' are not allowed."
            )


def validate_sql(
    sql: str,
    allowed_tables: Collection[str] | None = None,
    *,
    schema: str = DEFAULT_SCHEMA,
    redacted_columns: Mapping[str, Collection[str]] | None = None,
) -> str:
    """
    Validates LLM-generated SQL and returns the canonical query to execute.

    Args:
        sql: Raw model output.
        allowed_tables: Table names (as reflected from the database) the
            query may read. ``None`` skips the allowlist check but still
            blocks system catalogs and other schemas.
        schema: The queryable schema; table references may be unqualified
            or qualified with it.
        redacted_columns: table -> column names the query may not touch.

    Returns:
        str: SQL regenerated from the validated AST (comments removed).
            Execute this, not the input.

    Raises:
        UnsafeSQLError: The query is not a single, safe read.
    """
    candidate = strip_code_fences(sql).strip()
    if not candidate:
        raise UnsafeSQLError("Empty SQL.")

    try:
        # Empty statements (``;;``) parse as None and a comment-only trailer
        # (``SELECT 1; -- done``) as a bare Semicolon node; neither is a
        # statement Postgres would execute.
        statements = [
            s
            for s in sqlglot.parse(candidate, read=DIALECT)
            if s is not None and not isinstance(s, exp.Semicolon)
        ]
    except SqlglotError as exc:
        raise UnsafeSQLError("SQL could not be parsed.") from exc

    if len(statements) != 1:
        raise UnsafeSQLError("Multiple SQL statements are not allowed.")

    tree = statements[0]

    if not isinstance(tree, READ_ROOTS):
        raise UnsafeSQLError("Only SELECT statements are allowed.")

    forbidden = next(tree.find_all(*FORBIDDEN_NODES), None)
    if forbidden is not None:
        raise UnsafeSQLError(
            f"Only SELECT statements are allowed ({type(forbidden).__name__} found)."
        )

    for func in tree.find_all(exp.Func):
        name = _function_name(func)
        if _is_blocked_function(name):
            raise UnsafeSQLError(f"Function '{name}' is not allowed.")

    allowed_exact = set(allowed_tables) if allowed_tables is not None else None
    allowed_folded = (
        {t.lower() for t in allowed_exact} if allowed_exact is not None else None
    )
    cte_names = _cte_names(tree)
    for table in tree.find_all(exp.Table):
        _check_table(table, cte_names, allowed_exact, allowed_folded, schema)

    if redacted_columns:
        _check_redactions(tree, redacted_columns)

    return tree.sql(dialect=DIALECT, comments=False)
