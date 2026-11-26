"""
Database session management.

Provides the SQLAlchemy engine and session factory, and the guards that
keep query execution read-only at the database layer (audit SEC-2).

The SQL guard (`services/sql_validator.py`) is the first line of defence;
everything here is the second, and must hold even if the guard is
bypassed:

- every Postgres connection starts with ``default_transaction_read_only``
  and server-side statement/idle timeouts,
- ``services/query_executor.py`` additionally opens each query in an
  explicit ``READ ONLY`` transaction and always rolls back,
- ``assert_database_role_is_safe`` refuses to boot outside development
  when the configured role could write or escalate.
"""

import logging
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from ai_bi_analytics.core.config import settings

logger = logging.getLogger(__name__)

DEVELOPMENT_ENV = "development"


def is_postgres_url(database_url: str) -> bool:
    return make_url(database_url).get_backend_name() == "postgresql"


def build_engine_kwargs(
    database_url: str,
    statement_timeout_ms: int,
    idle_in_transaction_timeout_ms: int,
    search_path: str = "public",
) -> dict[str, Any]:
    """
    Engine options. On Postgres, every connection is read-only by default
    and carries server-side timeouts, so a runaway or malicious query is
    stopped by the database rather than by the application.

    Note: libpq ``options`` are not honoured through PgBouncer in
    transaction-pooling mode; set the same values on the role instead
    (see ``example/readonly_role.sql``).
    """
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if is_postgres_url(database_url):
        kwargs["connect_args"] = {
            "options": (
                "-c default_transaction_read_only=on "
                f"-c statement_timeout={statement_timeout_ms} "
                f"-c idle_in_transaction_session_timeout="
                f"{idle_in_transaction_timeout_ms} "
                # Unqualified names resolve in the queryable schema (SEC-7).
                # Validated as a plain identifier in Settings.
                f"-c search_path={search_path}"
            )
        }
    return kwargs


engine = create_engine(
    settings.database_url,
    **build_engine_kwargs(
        settings.database_url,
        settings.db_statement_timeout_ms,
        settings.db_idle_in_transaction_timeout_ms,
        settings.queryable_schema,
    ),
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db():
    """
    Dependency generator for database session.

    Yields:
        Session: SQLAlchemy session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


ROLE_PRIVILEGE_QUERY = text(
    "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls "
    "FROM pg_roles WHERE rolname = current_user"
)


class UnsafeDatabaseRoleError(RuntimeError):
    """The configured database role can write, escalate, or bypass RLS."""


def assert_database_role_is_safe(db_engine: Engine, env: str) -> None:
    """
    Refuse to run against a privileged database role outside development.

    A superuser (or a role that can create roles/databases or bypass RLS)
    turns any SQL-guard bypass into full database — and, via
    ``COPY ... TO PROGRAM``, host — compromise. In development this only
    warns so local setups keep working.

    Raises:
        UnsafeDatabaseRoleError: privileged role and ``env`` is not
            development, or the privileges could not be verified.
    """
    if db_engine.dialect.name != "postgresql":
        return

    enforce = env != DEVELOPMENT_ENV
    try:
        with db_engine.connect() as conn:
            row = conn.execute(ROLE_PRIVILEGE_QUERY).one()
    except Exception as exc:
        if enforce:
            raise UnsafeDatabaseRoleError(
                "Could not verify database role privileges"
            ) from exc
        logger.warning("Could not verify database role privileges: %s", exc)
        return

    granted = [
        name
        for name, value in zip(
            ("SUPERUSER", "CREATEROLE", "CREATEDB", "BYPASSRLS"), row, strict=True
        )
        if value
    ]
    if not granted:
        return

    message = (
        "Database role has privileges the query service must not hold: "
        f"{', '.join(granted)}. Connect as a read-only role "
        "(see example/readonly_role.sql)."
    )
    if enforce:
        raise UnsafeDatabaseRoleError(message)
    logger.warning("%s Allowed only because ENV=%s.", message, env)
