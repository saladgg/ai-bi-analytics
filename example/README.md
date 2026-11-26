# Example Setup

Quick-start helpers for bringing up a working PostgreSQL environment for the
`ai-bi-analytics` service. Use these to seed a database the API can query
during local development or demos.

## Contents

| File | Purpose |
|------|---------|
| [readonly_role.sql](readonly_role.sql) | Create/rotate the **read-only** role the API connects as. Works on any Postgres; run with `psql -v ... -f`. |
| [initdb/10_readonly_role.sh](initdb/10_readonly_role.sh) | Runs `readonly_role.sql` automatically on first start of the compose Postgres. |
| [db_user_setup.py](db_user_setup.py) | Create the database, an owner role, and the read-only role on a **host-installed** Postgres (uses `sudo -u postgres psql`). |
| [gen_test_table_data.py](gen_test_table_data.py) | Create a `products` table and populate it with ~1,000 rows of fake data via SQLAlchemy + Faker. |

## Two roles, on purpose

The API runs LLM-generated SQL, so it must never connect as a role that can
write (audit SEC-2, see [`docs/todos/01_general_audit.md`](../docs/todos/01_general_audit.md)):

| Role | Used by | Can |
|------|---------|-----|
| owner (`test_user` in compose, `ai_bi_owner` on host) | seeding scripts, migrations | create and write tables |
| `ai_bi_readonly` | the API (`DATABASE_URL`) | `SELECT` only; read-only transactions by default; 5 s statement timeout |

Outside `ENV=development` the API **refuses to start** if `DATABASE_URL`'s
role is a superuser or can create roles/databases or bypass RLS.

## Which script do I need?

- **Postgres in Docker (`make docker-up`)** → skip `db_user_setup.py`. The
  `postgres` service in [docker-compose.yml](../docker-compose.yml) creates
  `test_user` (owner), the `ai_bi_db` database and, on **first start with an
  empty volume**, the `ai_bi_readonly` / `readonly_pwd` role. Point the API at
  `ai_bi_readonly` and run `gen_test_table_data.py` (which uses the owner).

  Already had a `postgres_data` volume before this change? The init script
  won't re-run; either `make docker-down` (wipes the volume) or create the
  role by hand:

  ```bash
  docker exec -i ai_bi_postgres psql -U test_user -d ai_bi_db \
    -v ro_user=ai_bi_readonly -v ro_password=readonly_pwd \
    -v db_name=ai_bi_db -v owner_role=test_user < example/readonly_role.sql
  ```
- **Postgres installed natively on your host** → run `db_user_setup.py` first
  to create the database and both roles, then `gen_test_table_data.py` with
  `SEED_DATABASE_URL` pointing at the owner role.

## Prerequisites

- Project dependencies installed (`make install-dev` from the repo root).
- A reachable PostgreSQL instance (Docker or host).
- For `db_user_setup.py`: `sudo` access and a local `postgres` superuser role
  (the default on Debian/Ubuntu/Fedora packages of PostgreSQL).

## 1. Create the database and roles (host Postgres only)

```bash
DB_OWNER_PASSWORD='<owner pw>' DB_READONLY_PASSWORD='<api pw>' \
  python example/db_user_setup.py
```

| Env var | Default |
|---------|---------|
| `DB_NAME` | `ai_bi_db` |
| `DB_OWNER_USER` / `DB_OWNER_PASSWORD` | `ai_bi_owner` / `owner_pwd` |
| `DB_READONLY_USER` / `DB_READONLY_PASSWORD` | `ai_bi_readonly` / `readonly_pwd` |

The defaults are for local development only. The script is idempotent:
re-running it re-applies privileges and rotates both passwords. Values are
passed to `psql` as variables, never formatted into SQL.

## 2. Seed the `products` table

```bash
python example/gen_test_table_data.py
```

The script connects with `SEED_DATABASE_URL` (an **owner** role — seeding
writes). The default is:

```
postgresql+psycopg2://test_user:test_pwd@localhost:5433/ai_bi_db
```

Port `5433` matches the host-side mapping for the dockerized Postgres in
[docker-compose.yml](../docker-compose.yml) (`5433:5432`). Set `SEED_DATABASE_URL` if:

- you ran `db_user_setup.py` against a host Postgres → use `ai_bi_owner:<pw>@localhost:5432/ai_bi_db`,
- you changed credentials in `docker-compose.yml`,
- or you are pointing at a remote database.

The script:

1. Creates the `products` table if it does not exist (`id`, `name`, `category`, `revenue`).
2. Generates 1,000 fake products across 20 categories and 16 brands.
3. Bulk-inserts them in a single transaction.

To reset the table on each run, uncomment the `clear_table_if_exists(session)`
call inside `main()`.

## Verifying the seed

```bash
# Dockerized Postgres
docker exec -it ai_bi_postgres psql -U test_user -d ai_bi_db -c \
  "SELECT category, COUNT(*) FROM products GROUP BY category ORDER BY 2 DESC LIMIT 5;"
```

You can then issue a natural-language query against the running API, e.g.

```json
POST /api/query
{ "question": "What are the top 3 products by revenue?" }
```
