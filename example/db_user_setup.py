"""Create the database and its two roles on a local (non-Docker) PostgreSQL.

Two roles, deliberately separate (audit SEC-2):

- an **owner** role (``DB_OWNER_USER``) that owns the database and is used
  to create and seed tables (``example/gen_test_table_data.py``);
- a **read-only** role (``DB_READONLY_USER``) that the API connects as.
  It can only ``SELECT``, defaults to read-only transactions, and has a
  statement timeout (see ``example/readonly_role.sql``).

Neither role is a superuser. Passwords come from the environment; the
defaults are for local development only.

Usage::

    DB_OWNER_PASSWORD=... DB_READONLY_PASSWORD=... python example/db_user_setup.py

Requires ``sudo -u postgres psql`` access on the local machine.
"""

import os
import subprocess
import sys
from pathlib import Path

DB_NAME = os.getenv("DB_NAME", "ai_bi_db")
DB_OWNER_USER = os.getenv("DB_OWNER_USER", "ai_bi_owner")
DB_OWNER_PASSWORD = os.getenv("DB_OWNER_PASSWORD", "owner_pwd")
DB_READONLY_USER = os.getenv("DB_READONLY_USER", "ai_bi_readonly")
DB_READONLY_PASSWORD = os.getenv("DB_READONLY_PASSWORD", "readonly_pwd")

READONLY_ROLE_SQL = Path(__file__).with_name("readonly_role.sql")

PSQL = ["sudo", "-u", "postgres", "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1"]

# Values are passed as psql variables (:'name' literals / :"name"
# identifiers) and quoted by psql, never interpolated into SQL text.
CREATE_OWNER_SQL = """
SELECT format('CREATE ROLE %I LOGIN', :'owner_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'owner_user')
\\gexec
ALTER ROLE :"owner_user" WITH LOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB
    PASSWORD :'owner_password';
SELECT format('CREATE DATABASE %I OWNER %I', :'db_name', :'owner_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name')
\\gexec
ALTER DATABASE :"db_name" SET timezone TO 'UTC';
"""

# Make the owner own the public schema so its tables and default
# privileges line up with what readonly_role.sql grants.
OWN_PUBLIC_SCHEMA_SQL = 'ALTER SCHEMA public OWNER TO :"owner_user";'


def run_psql(
    variables: dict[str, str],
    *,
    sql: str | None = None,
    sql_file: Path | None = None,
    dbname: str | None = None,
) -> None:
    cmd = list(PSQL)
    if dbname:
        cmd += ["-d", dbname]
    for name, value in variables.items():
        cmd += ["-v", f"{name}={value}"]

    stdin = None
    if sql_file is not None:
        # psql runs as the postgres OS user, which may not be able to read
        # the repo checkout, so stream the file over stdin instead of -f.
        stdin = sql_file.read_text()
    elif sql is not None:
        stdin = sql

    try:
        subprocess.run(cmd, input=stdin, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"psql failed: {e.stderr.strip()}", file=sys.stderr)  # noqa: T201
        sys.exit(1)


def main() -> None:
    run_psql(
        {
            "owner_user": DB_OWNER_USER,
            "owner_password": DB_OWNER_PASSWORD,
            "db_name": DB_NAME,
        },
        sql=CREATE_OWNER_SQL,
    )
    run_psql({"owner_user": DB_OWNER_USER}, sql=OWN_PUBLIC_SCHEMA_SQL, dbname=DB_NAME)
    run_psql(
        {
            "ro_user": DB_READONLY_USER,
            "ro_password": DB_READONLY_PASSWORD,
            "db_name": DB_NAME,
            "owner_role": DB_OWNER_USER,
        },
        sql_file=READONLY_ROLE_SQL,
        dbname=DB_NAME,
    )

    print(  # noqa: T201
        "Database setup completed.\n"
        f"  seed as : postgresql+psycopg2://{DB_OWNER_USER}:***@localhost:5432/{DB_NAME}\n"
        f"  API uses: postgresql+psycopg2://{DB_READONLY_USER}:***@localhost:5432/{DB_NAME}"
    )


if __name__ == "__main__":
    main()
