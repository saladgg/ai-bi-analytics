# Example Setup

Quick-start helpers for bringing up a working PostgreSQL environment for the
`ai-bi-analytics` service. Use these to seed a database the API can query
during local development or demos.

## Contents

| File | Purpose |
|------|---------|
| [db_user_setup.py](db_user_setup.py) | Create a PostgreSQL role and database on a **host-installed** Postgres (uses `sudo -u postgres psql`). |
| [gen_test_table_data.py](gen_test_table_data.py) | Create a `products` table and populate it with ~1,000 rows of fake data via SQLAlchemy + Faker. |

## Which script do I need?

The two scripts cover different scenarios — pick based on how you are running
Postgres:

- **Postgres in Docker (`make docker-up`)** → skip `db_user_setup.py`. The
  `postgres` service in [docker-compose.yml](../docker-compose.yml) already
  provisions `test_user` / `test_pwd` and the `ai_bi_db` database. Run
  `gen_test_table_data.py` only.
- **Postgres installed natively on your host** → run `db_user_setup.py` first
  to create the role and database, then `gen_test_table_data.py` to seed it.

## Prerequisites

- Project dependencies installed (`make install-dev` from the repo root).
- A reachable PostgreSQL instance (Docker or host).
- For `db_user_setup.py`: `sudo` access and a local `postgres` superuser role
  (the default on Debian/Ubuntu/Fedora packages of PostgreSQL).

## 1. Create the database and user (host Postgres only)

```bash
python example/db_user_setup.py
```

Defaults defined at the top of the script:

| Setting | Value |
|---------|-------|
| `DB_NAME` | `ai_bi_db` |
| `DB_USER` | `app` |
| `DB_PASSWORD` | `app` |

The script is idempotent — it `ALTER`s the role if it already exists and skips
database creation if `ai_bi_db` is already present. Edit the constants at the
top of the file to use different credentials.

## 2. Seed the `products` table

```bash
python example/gen_test_table_data.py
```

The default `DATABASE_URL` in the script is:

```
postgresql+psycopg2://test_user:test_pwd@localhost:5433/ai_bi_db
```

Port `5433` matches the host-side mapping for the dockerized Postgres in
[docker-compose.yml](../docker-compose.yml) (`5433:5432`). Update the URL if:

- you ran `db_user_setup.py` against a host Postgres → use `app:app@localhost:5432/ai_bi_db`,
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
POST /api/query/
{ "question": "What are the top 3 products by revenue?" }
```
