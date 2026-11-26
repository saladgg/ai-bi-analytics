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
--     [-v schema=analytics] \
--     -f example/readonly_role.sql
--
-- The service connects as :ro_user. It may only read tables in :schema
-- (default public; match the app's QUERYABLE_SCHEMA), and the database
-- also enforces a read-only default and
-- a statement timeout on the role itself, so these hold even through a
-- connection pooler that drops libpq startup options.
--
-- Narrowing access (audit SEC-7). The app's QUERYABLE_TABLES and
-- REDACTED_COLUMNS limit what the LLM sees and what the SQL guard allows;
-- the database grants below are the authoritative layer. To enforce the
-- same limits in Postgres, replace the schema-wide GRANT SELECT with
-- per-table grants, and for tables with hidden columns grant only the
-- visible ones (column privileges):
--
--   REVOKE SELECT ON users FROM ai_bi_readonly;
--   GRANT SELECT (id, city, created_at) ON users TO ai_bi_readonly;
--
-- A column-level grant also makes SELECT * on that table fail.

\set ON_ERROR_STOP on

\if :{?schema}
\else
    \set schema public
\endif

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

-- No object creation in the schema by anyone but owners (default for
-- public since PG15; explicit for older servers and other schemas).
REVOKE CREATE ON SCHEMA :"schema" FROM PUBLIC;
GRANT USAGE ON SCHEMA :"schema" TO :"ro_user";

-- Unqualified names resolve in the queryable schema, matching the app.
ALTER ROLE :"ro_user" SET search_path = :"schema";

GRANT SELECT ON ALL TABLES IN SCHEMA :"schema" TO :"ro_user";
-- Tables and views created later by the owner become readable automatically.
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_role" IN SCHEMA :"schema"
    GRANT SELECT ON TABLES TO :"ro_user";
