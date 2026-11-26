-- Least-privilege, read-only role for the ai-bi-analytics query service
-- (audit SEC-2). Idempotent: safe to re-run, also rotates the password.
--
-- Run as a role that owns the target tables (or a superuser):
--
--   psql "<admin connection>" \
--     -v ro_user=ai_bi_readonly \
--     -v ro_password='<strong password>' \
--     -v db_name=ai_bi_db \
--     -v owner_role=<role that creates/owns the tables> \
--     -f example/readonly_role.sql
--
-- The service connects as :ro_user. It may only read tables in the
-- public schema, and the database also enforces a read-only default and
-- a statement timeout on the role itself, so these hold even through a
-- connection pooler that drops libpq startup options.
--
-- To narrow access further, replace the schema-wide GRANT SELECT below
-- with per-table grants (audit SEC-7 adds an application-side allowlist).

\set ON_ERROR_STOP on

SELECT format('CREATE ROLE %I LOGIN', :'ro_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'ro_user')
\gexec

ALTER ROLE :"ro_user" WITH
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    NOINHERIT PASSWORD :'ro_password';

ALTER ROLE :"ro_user" SET default_transaction_read_only = on;
ALTER ROLE :"ro_user" SET statement_timeout = '5s';
ALTER ROLE :"ro_user" SET idle_in_transaction_session_timeout = '10s';

GRANT CONNECT ON DATABASE :"db_name" TO :"ro_user";

-- No object creation in public by anyone but owners (default since PG15;
-- explicit for older servers).
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"ro_user";

GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"ro_user";
-- Tables created later by the owner become readable automatically.
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_role" IN SCHEMA public
    GRANT SELECT ON TABLES TO :"ro_user";
