# AI-Powered Business Intelligence Tool

![FastAPI](https://img.shields.io/badge/FastAPI-Backend-green)
![Python](https://img.shields.io/badge/Python-3.14-blue)
![Redis](https://img.shields.io/badge/Redis-Caching-red)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-blue)
![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-Observability-purple)
![Docker](https://img.shields.io/badge/Docker-Containerized-blue)
[![Coverage Status](https://coveralls.io/repos/github/saladgg/ai-bi-analytics/badge.svg)](https://coveralls.io/github/saladgg/ai-bi-analytics)

A production-grade FastAPI service that turns **natural-language questions into safe, explainable SQL** over PostgreSQL — with strict guardrails, distributed rate limiting, Redis caching, and OpenTelemetry tracing.

---

## Table of Contents

- [Why this exists](#why-this-exists)
- [How it works](#how-it-works)
- [Features](#features)
- [Tech stack](#tech-stack)
- [Project layout](#project-layout)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [API usage](#api-usage)
- [Development workflow](#development-workflow)
- [Releases](#releases)
- [Roadmap](#roadmap)
- [License](#license)

---

## Why this exists

Business users routinely need answers from relational data, but cannot write SQL. Wiring an LLM directly to a database naively introduces real risks:

- SQL injection and destructive statements
- Hallucinated columns, tables, or values
- Unbounded LLM spend
- No way to trace, debug, or audit what ran

This project demonstrates how to ship that capability **safely**: an LLM-backed pipeline wrapped in validation, read-only execution, caching, rate limiting, and observability.

---

## How it works

```
        ┌──────────────┐
        │    Client    │
        └──────┬───────┘
               │  POST /api/query  (x-api-key)
               ▼
        ┌──────────────┐    ┌──────────────────────────┐
        │   FastAPI    │───▶│ Rate limiter (Redis Lua)│
        └──────┬───────┘    └──────────────────────────┘
               │
               ▼
        ┌──────────────┐    ┌──────────────────────────┐
        │ Cache lookup │───▶│ Hit → return cached JSON│
        └──────┬───────┘    └──────────────────────────┘
               │ miss
               ▼
        ┌──────────────────────┐
        │ Schema introspection │  (SQLAlchemy reflect)
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐
        │   NL → SQL  (LLM)    │
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐
        │   SQL guard (AST)    │  one read query, known tables
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐
        │   PostgreSQL exec    │  read-only role
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐
        │ Explanation  (LLM)   │
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐
        │ Cache write + return │
        └──────────────────────┘

Cross-cutting:  structured logging  •  OpenTelemetry tracing (FastAPI instr.)
```

---

## Features

### NL → SQL with strict guardrails
Generated SQL is parsed into an AST ([sqlglot](https://github.com/tobymao/sqlglot), Postgres dialect) and accepted only if it is exactly one read query (`SELECT`, `UNION`, `WITH … SELECT`) with no write, DDL, `COPY`, `SELECT INTO` or row lock anywhere in the tree, no dangerous functions (`pg_sleep`, `pg_read_file`, `lo_*`, `dblink`, `set_config`, …), and only tables in the configured query scope (`QUERYABLE_SCHEMA` / `QUERYABLE_TABLES`, never system catalogs) without touching `REDACTED_COLUMNS`. The API executes SQL **regenerated from the validated AST**, not the raw model output, so what was checked is exactly what runs. The database enforces this independently: the API connects as a read-only role (`SELECT` only, read-only transactions by default, server-side statement timeout), every query runs in an explicit `READ ONLY` transaction that is always rolled back, and outside `ENV=development` the service refuses to start on a privileged role. See [example/README.md](example/README.md#two-roles-on-purpose).

### Dynamic schema introspection
Tables and views in the queryable schema are reflected at request time via SQLAlchemy, narrowed to `QUERYABLE_TABLES` with `REDACTED_COLUMNS` removed, and passed to the LLM. The guard enforces that same scope, so the model is never shown anything it can't query, and the reverse. No hard-coded schema strings means no schema drift between code and prompts.

### Redis distributed cache
Identical `(question, schema)` pairs reuse prior responses. Default TTL is 5 minutes. This cuts LLM spend and trims p95 latency on repeated dashboards-style traffic.

### Sliding-window rate limiting
Implemented as a Redis Lua script ([`ai_bi_analytics/core/lua/sliding_window_rate_limit.lua`](ai_bi_analytics/core/lua/sliding_window_rate_limit.lua)) so the check-and-record is atomic across replicas and uses the Redis server's clock. Default policy: 5 requests per minute per client (`RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS`), keyed on the authenticated client id. `X-Forwarded-For` is honoured only from proxies listed in uvicorn's `FORWARDED_ALLOW_IPS`. Responses carry `X-RateLimit-Limit` / `X-RateLimit-Remaining`, and 429s carry `Retry-After`.

### Observability
- **Logging** — request lifecycle, SQL and errors via the standard `logging` config in [`core/logging_config.py`](ai_bi_analytics/core/logging_config.py).
- **OpenTelemetry** — FastAPI auto-instrumentation is enabled.

Not wired yet (tracked as OPS-2 in [`docs/todos`](docs/todos/01_general_audit_todos.md)): an OTLP exporter, DB/Redis/LLM spans, trace ids in log lines, JSON logs, and metrics.

### API-key auth
Each client sends its own key in the `x-api-key` header. The server stores only SHA-256 hashes (`API_KEYS=client_id:hash,...`), compares in constant time against every entry, and identifies the caller for rate limiting and logs. To rotate a key, list the new entry next to the old one, then remove the old. Missing or unknown keys get `401`. Generate a key with `make api-key CLIENT=<id>`. See [`core/security.py`](ai_bi_analytics/core/security.py). Suitable for internal and service-to-service use; swap in OAuth/JWT for end-user auth.

### Streamlit frontend (demo)
A minimal Streamlit UI ships under [`frontend/`](frontend/) for exploring the API without writing curl commands. **Demo only** — see [frontend/README.md](frontend/README.md) for limitations.

---

## Tech stack

| Layer                  | Technology                                           |
|------------------------|------------------------------------------------------|
| API framework          | FastAPI + Uvicorn                                    |
| Database               | PostgreSQL 18 (via SQLAlchemy 2.x), read-only role   |
| SQL guard              | sqlglot (AST parse + canonical regeneration)         |
| Cache & rate limiting  | Redis 8 (Lua-scripted sliding window)                |
| LLM provider           | OpenAI (abstracted behind `services/llm_client.py`)  |
| Observability          | OpenTelemetry (FastAPI instrumentation)              |
| Frontend (demo)        | Streamlit + pandas + Plotly                          |
| Containerization       | Docker + docker-compose                              |
| Python tooling         | uv, ruff, mypy, pytest, fakeredis                    |
| Release automation     | python-semantic-release (Conventional Commits)       |

---

## Project layout

```
ai-bi-analytics/
├── ai_bi_analytics/              # Application package
│   ├── api/
│   │   ├── deps.py               # API-key auth dependency
│   │   └── routes/query.py       # POST /api/query
│   ├── core/
│   │   ├── config.py             # Pydantic settings
│   │   ├── logging_config.py
│   │   ├── rate_limiter.py       # Redis sliding-window limiter
│   │   ├── redis_client.py
│   │   ├── security.py
│   │   └── lua/sliding_window_rate_limit.lua
│   ├── db/
│   │   ├── models.py
│   │   └── session.py            # Engine (read-only + timeouts), role guard
│   ├── schemas/query.py          # Request/response models
│   ├── services/
│   │   ├── cache.py              # Redis response cache
│   │   ├── explanation.py        # LLM explanation step
│   │   ├── llm_client.py         # Provider abstraction
│   │   ├── nl_to_sql.py          # NL → SQL generation
│   │   ├── query_executor.py     # READ ONLY transaction, always rolled back
│   │   ├── schema_loader.py      # Schema + table-name introspection
│   │   └── sql_validator.py      # AST SQL guard (sqlglot)
│   └── main.py                   # FastAPI app factory
│
├── frontend/                     # Streamlit demo UI
├── example/
│   ├── readonly_role.sql         # Least-privilege role the API connects as
│   ├── initdb/                   # Compose Postgres first-start hook
│   ├── db_user_setup.py          # Owner + read-only roles on host Postgres
│   └── gen_test_table_data.py    # Seed sample data (owner role)
├── tests/                        # pytest suite
│   └── integration/              # Real-Postgres checks (opt-in)
├── docs/todos/                   # Audit findings + phased backlogs
│
├── Dockerfile
├── .dockerignore                 # Keeps .env, .venv, .git out of images
├── docker-compose.yml            # api + postgres + redis
├── Makefile                      # uv-based developer commands
├── pyproject.toml
├── uv.lock                       # Pinned dependency set (Docker uses --frozen)
├── .env.example
├── CHANGELOG.md                  # Generated by semantic-release
└── README.md
```

---

## Getting started

### Prerequisites

- Python **3.12 – 3.14**
- [`uv`](https://github.com/astral-sh/uv) for environment management
- Docker + Docker Compose (for the easy path)
- An OpenAI API key

### 1. Configure environment

Copy [`.env.example`](.env.example) to `.env` and fill it in:

```bash
cp .env.example .env
# then edit .env: API_KEY, DATABASE_URL, OPENAI_API_KEY, ...
```

`DATABASE_URL` must use a **read-only** role. Outside `ENV=development` the API refuses to start if the role is a superuser or can create roles/databases or bypass RLS. See [Configuration](#configuration).

### Option A — Docker (recommended)

Brings up `api`, `postgres`, and `redis` in one command.

```bash
make docker-build
make docker-up

# In another shell, seed sample data (connects as the owner role)
python example/gen_test_table_data.py

make docker-down   # tear down (also removes named volumes)
```

The dockerized Postgres listens on host port **5433** (mapped to container 5432). On first start with an empty volume it creates the read-only `ai_bi_readonly` role the API should use. If your `postgres_data` volume predates that, see [example/README.md](example/README.md#which-script-do-i-need) for the one-line fix.

### Option B — Run locally

```bash
# Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Set up venv + dev dependencies
make venv_setup
source .venv/bin/activate
make install-dev

# Start a Postgres + Redis somewhere reachable.
# Host-installed Postgres: create the database + owner and read-only roles
python example/db_user_setup.py

make run_local        # uvicorn with --reload on :8000

# Optional — seed sample data (owner role) and launch the demo UI
SEED_DATABASE_URL=postgresql+psycopg2://ai_bi_owner:owner_pwd@localhost:5432/ai_bi_db \
  python example/gen_test_table_data.py
make run_frontend     # Streamlit on :8501
```

Run `make help` for the full target list.

---

## Configuration

Settings load from the environment (or `.env`) via [`core/config.py`](ai_bi_analytics/core/config.py).

| Variable | Default | Purpose |
|----------|---------|---------|
| `API_KEYS` | empty | `client_id:sha256(key)` entries, one per client (generate with `make api-key CLIENT=<id>`) |
| `API_KEY` | empty | Legacy single key, authenticates as client `default`. Outside development: 32+ chars, not a placeholder. One of `API_KEYS`/`API_KEY` is required |
| `DATABASE_URL` | — (required) | SQLAlchemy URL; must use a read-only role |
| `ENV` | `development` | Anything else enforces the database role check at startup |
| `DB_STATEMENT_TIMEOUT_MS` | `5000` | Server-side cap per query |
| `DB_IDLE_IN_TRANSACTION_TIMEOUT_MS` | `10000` | Server-side cap on idle open transactions |
| `QUERYABLE_SCHEMA` | `public` | The one schema the LLM sees and queries (also the connection's `search_path`) |
| `QUERYABLE_TABLES` | empty | Comma-separated tables/views the LLM may use. **Required outside `ENV=development`**; empty means every table in the schema |
| `REDACTED_COLUMNS` | empty | `table.column` or bare `column` entries hidden from the LLM and rejected by the guard (including `SELECT *` on those tables) |
| `MAX_QUESTION_LENGTH` | `500` | Longest accepted question, in characters |
| `MAX_RESULT_ROWS` | `1000` | Most rows per query; the guard caps `LIMIT`, and responses flag `truncated` |
| `EXPLANATION_SAMPLE_ROWS` | `20` | Rows sent to the LLM for the explanation |
| `CACHE_MAX_BYTES` | `512000` | Larger responses aren't cached |
| `RATE_LIMIT_REQUESTS` | `5` | Requests per client per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Sliding-window length |
| `REDIS_URL` | `redis://redis:6379/0` | Cache and rate-limit store |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies uvicorn trusts for `X-Forwarded-For` |
| `LLM_PROVIDER` / `OPENAI_API_KEY` | `openai` / — | LLM backend |

---

## API usage

`/api/query` requires an `x-api-key` header holding a client key (see [API-key auth](#api-key-auth)); `/api/health` is open.

### Health

```
GET /api/health  →  {"status": "ok"}
```

### Query

```http
POST /api/query
Content-Type: application/json
x-api-key: <your key>

{
  "question": "What are the top 3 products by revenue?"
}
```

Response:

```json
{
  "sql": "SELECT product_name, SUM(revenue) AS total_revenue FROM products GROUP BY product_name ORDER BY total_revenue DESC LIMIT 3;",
  "result": [
    {"product_name": "Product A", "total_revenue": 125000},
    {"product_name": "Product B", "total_revenue":  98000},
    {"product_name": "Product C", "total_revenue":  87000}
  ],
  "row_count": 3,
  "truncated": false,
  "explanation": "The top three products by revenue are Product A, Product B, and Product C based on the total sales recorded in the database."
}
```

`sql` is the guard's canonical form of the generated query, which is exactly what was executed. Results are capped at `MAX_RESULT_ROWS`: a query without a smaller `LIMIT` gets `LIMIT MAX_RESULT_ROWS + 1`, and `truncated: true` means more rows existed than were returned.

Errors return `{"detail", "code", "request_id"}`: `422` for a rejected or failed query or an invalid question, `502` if the LLM is unavailable, `503` if Postgres or Redis is unavailable, and `504` if a query timed out. Every response carries an `X-Request-ID` header (one you send is reused if it's safe), and the same id appears in the server logs.

Every `/api/query` response carries `X-RateLimit-Limit` and `X-RateLimit-Remaining`. Over the limit, the API returns **429** with `Retry-After`.

Interactive docs are served at `/docs` (Swagger) and `/redoc` once the API is running.

---

## Development workflow

```bash
make format        # ruff format + ruff --fix (package, tests, frontend, example)
make format-check  # the same, check-only (what CI runs)
make lint          # ruff check (incl. bandit-style S rules) + mypy
make test          # pytest; fails below 100% line + branch coverage
make audit         # pip-audit: known vulnerabilities in locked dependencies
make api-key CLIENT=<id>   # generate a client key and its API_KEYS entry
make clean         # wipe caches (.pytest_cache, .ruff_cache, .mypy_cache, ...)
```

Tests live under [`tests/`](tests/) and run against a SQLite test DB, an in-memory Redis that executes the real Lua script ([fakeredis](https://github.com/cunla/fakeredis-py)), and a mocked LLM. `make test` **fails below 100% line and branch coverage**, locally and in CI. When running a subset of tests, pass `--no-cov`.

The integration suite in [`tests/integration/`](tests/integration/) runs against a real PostgreSQL. It covers read-only enforcement, timeouts, the guard's canonical SQL, the query scope on a dedicated schema, column privileges and the row cap. CI runs it on every PR. Locally it is skipped unless both URLs are set, e.g. against the compose Postgres:

```bash
TEST_POSTGRES_OWNER_URL=postgresql+psycopg2://test_user:test_pwd@localhost:5433/ai_bi_db \
TEST_POSTGRES_READONLY_URL=postgresql+psycopg2://ai_bi_readonly:readonly_pwd@localhost:5433/ai_bi_db \
  make test
```

---

## Releases

Versioning and changelog are automated via [python-semantic-release](https://python-semantic-release.readthedocs.io/) using **Conventional Commits**. Tag-allowlist and bump rules live under `[tool.semantic_release]` in [`pyproject.toml`](pyproject.toml):

| Commit type                  | Version bump |
|------------------------------|--------------|
| `feat:`                      | minor        |
| `fix:`, `perf:`, `refactor:` | patch        |
| `BREAKING CHANGE:` footer    | major        |
| `docs:`, `chore:`, `ci:`, `test:`, `style:`, `build:` | none |

Releases are fully automated and gated on CI:

1. A PR runs CI ([`ci.yaml`](.github/workflows/ci.yaml), every action SHA-pinned):
   - format check, lint and mypy across the repo
   - dependency audit
   - tests at 100% line and branch coverage, including the Postgres integration suite
   - wheel smoke test
   - Docker image build with a Trivy scan (fixable CRITICAL/HIGH CVEs fail the build)
   - gitleaks secret scan over the full history
2. On merge, CI runs again on `main`.
3. Only if that run succeeds does [`release.yaml`](.github/workflows/release.yaml) run semantic-release, on the exact commit CI validated. It bumps the version, re-locks `uv.lock`, updates the changelog, tags, and publishes a GitHub release with the wheel and sdist attached.

Releases are serialized, so two quick merges can't collide. A red build is never released. Dependabot opens weekly update PRs for Python packages, GitHub Actions and the Docker base image, and they go through the same gates.

See [`CHANGELOG.md`](CHANGELOG.md) for the generated history.

---

## Roadmap

Planned work lives in [`docs/todos/`](docs/todos/README.md) as audit findings paired with phased checklists. The current backlog, [`01_general_audit_todos.md`](docs/todos/01_general_audit_todos.md), has shipped:

- **Phase 0:** SQL guard, read-only database, rate limiting, build and packaging.
- **Phase 1:** typed errors, bounded results, prompt separation, allowlisted query scope, per-client API keys, and full CI gates.

Next up is Phase 2: OpenTelemetry export and metrics, readiness checks, the rest of the container hardening, and cache resilience.

---

## License

[MIT](LICENSE) © Salad Guyo
