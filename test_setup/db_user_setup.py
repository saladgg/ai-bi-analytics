"""A simple script for creating database and database user on PostgreSQL."""

import subprocess
import sys
from typing import Optional

# Database configuration

DB_NAME = "ai_bi_db"
DB_USER = "app"
DB_PASSWORD = "app"


def run_psql_command(command: str, dbname: Optional[str] = None) -> None:
    """Execute PostgreSQL commands.

    Args:
        command: The SQL command to execute
        dbname: Optional database name to connect to
    """
    try:
        cmd = ["sudo", "-u", "postgres", "psql", "-U", "postgres"]
        if dbname:
            cmd.extend(["-d", dbname])
        cmd.extend(["-c", command])

        subprocess.run(
            cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
    except subprocess.CalledProcessError as e:
        print(  # noqa: T201
            f"Error executing command: {e.stderr.strip()}", file=sys.stderr
        )
        sys.exit(1)


def database_exists(dbname: str) -> bool:
    """Check if a database exists."""
    try:
        result = subprocess.run(
            ["sudo", "-u", "postgres", "psql", "-U", "postgres", "-lqt"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return dbname in [
            line.split("|")[0].strip() for line in result.stdout.splitlines()
        ]
    except subprocess.CalledProcessError as e:
        print(  # noqa: T201
            f"Error checking database existence: {e.stderr.strip()}", file=sys.stderr
        )
        return False


def main() -> None:
    """Set up the PostgreSQL database and user with appropriate privileges."""
    # Create or update user with superuser, createdb, createrole, and login privileges
    run_psql_command(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{DB_USER}') THEN
                CREATE USER {DB_USER}
                WITH SUPERUSER CREATEDB CREATEROLE LOGIN
                PASSWORD '{DB_PASSWORD}';
            ELSE
                ALTER USER {DB_USER}
                WITH SUPERUSER CREATEDB CREATEROLE LOGIN
                PASSWORD '{DB_PASSWORD}';
            END IF;
        END $$;
        """
    )

    # Create the database if it doesn't exist
    if not database_exists(DB_NAME):
        run_psql_command(f"CREATE DATABASE {DB_NAME} OWNER {DB_USER};")
    else:
        print(f"Database {DB_NAME} already exists, skipping creation.")  # noqa: T201

    # Set the database timezone to UTC
    run_psql_command(f"ALTER DATABASE {DB_NAME} SET timezone TO 'UTC';", dbname=DB_NAME)

    # Grant all privileges on the database to the user
    run_psql_command(f"GRANT ALL PRIVILEGES ON DATABASE {DB_NAME} TO {DB_USER};")

    print("Database setup completed successfully.")  # noqa: T201


if __name__ == "__main__":
    main()
