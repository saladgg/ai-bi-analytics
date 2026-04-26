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
- [API usage](#api-usage)
- [Development workflow](#development-workflow)
- [Releases](#releases)
- [Roadmap](#roadmap)

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
        │   SQL validator      │  SELECT-only, single statement
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
The validator rejects anything that isn't a single `SELECT`. `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, multi-statement payloads, and comments-as-injection are all blocked before the query reaches the database. The DB user itself should also be read-only (see [`.env.example`](.env.example) — `readonly_user`).

### Dynamic schema introspection
Schemas are reflected at request time via SQLAlchemy and passed to the LLM. No hard-coded schema strings means no schema drift between code and prompts.

### Redis distributed cache
Identical `(question, schema)` pairs reuse prior responses. Default TTL is 5 minutes. This cuts LLM spend and trims p95 latency on repeated dashboards-style traffic.

### Sliding-window rate limiting
Implemented as a Redis Lua script ([`ai_bi_analytics/core/lua/sliding_window_rate_limit.lua`](ai_bi_analytics/core/lua/sliding_window_rate_limit.lua)) so the check-and-increment is atomic across replicas. Default policy: 5 requests per minute per client.

### Observability
- **Structured logging** — request lifecycle, cache hit/miss, SQL, row counts, errors.
- **OpenTelemetry tracing** — FastAPI auto-instrumentation; spans cover the API, Redis, and DB calls so a single `trace_id` follows a request end-to-end.

### API-key auth
Static `x-api-key` header validated by [`ai_bi_analytics/api/deps.py`](ai_bi_analytics/api/deps.py). Suitable for internal/service-to-service use; swap in OAuth/JWT for end-user auth.

### Streamlit frontend (demo)
A minimal Streamlit UI ships under [`frontend/`](frontend/) for exploring the API without writing curl commands. **Demo only** — see [frontend/README.md](frontend/README.md) for limitations.

---

## Tech stack

| Layer                  | Technology                                           |
|------------------------|------------------------------------------------------|
| API framework          | FastAPI + Uvicorn                                    |
| Database               | PostgreSQL 18 (via SQLAlchemy 2.x)                   |
| Cache & rate limiting  | Redis 8 (Lua-scripted sliding window)                |
| LLM provider           | OpenAI (abstracted behind `services/llm_client.py`)  |
| Observability          | OpenTelemetry (FastAPI instrumentation)              |
| Frontend (demo)        | Streamlit + pandas + Plotly                          |
| Containerization       | Docker + docker-compose                              |
| Python tooling         | uv, ruff, mypy, pytest, pre-commit                   |
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
│   │   └── session.py            # SQLAlchemy session factory
│   ├── schemas/query.py          # Request/response models
│   ├── services/
│   │   ├── cache.py              # Redis response cache
│   │   ├── explanation.py        # LLM explanation step
│   │   ├── llm_client.py         # Provider abstraction
│   │   ├── nl_to_sql.py          # NL → SQL generation
│   │   ├── query_executor.py     # Read-only execution
│   │   ├── schema_loader.py      # Schema introspection
│   │   └── sql_validator.py      # SELECT-only guardrail
│   └── main.py                   # FastAPI app factory
│
├── frontend/                     # Streamlit demo UI
├── example/                      # DB user/data bootstrap scripts
├── tests/                        # pytest suite
│
├── Dockerfile
├── docker-compose.yml            # api + postgres + redis
├── Makefile                      # uv-based developer commands
├── pyproject.toml
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

### Option A — Docker (recommended)

Brings up `api`, `postgres`, and `redis` in one command.

```bash
make docker-build
make docker-up

# In another shell, seed sample data
python example/gen_test_table_data.py

make docker-down   # tear down (also removes named volumes)
```

The dockerized Postgres listens on host port **5433** (mapped to container 5432). See [example/README.md](example/README.md) for details on connecting and seeding.

### Option B — Run locally

```bash
# Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Set up venv + dev dependencies
make venv_setup
source .venv/bin/activate
make install-dev

# Start a Postgres + Redis somewhere reachable, then:
make run_local        # uvicorn with --reload on :8000

# Optional — seed sample data and launch the demo UI
python example/gen_test_table_data.py
make run_frontend     # Streamlit on :8501
```

Run `make help` for the full target list.

---

## API usage

All endpoints require a static `x-api-key` header that matches `API_KEY` in `.env`.

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
  "explanation": "The top three products by revenue are Product A, Product B, and Product C based on the total sales recorded in the database."
}
```

Interactive docs are served at `/docs` (Swagger) and `/redoc` once the API is running.

---

## Development workflow

```bash
make format      # ruff format + ruff --fix
make lint        # ruff check + mypy
make test        # pytest with coverage
make clean       # wipe caches (.pytest_cache, .ruff_cache, .mypy_cache, ...)
```

Tests live under [`tests/`](tests/) and run against a SQLite test DB plus mocked Redis/LLM. Coverage is reported to Coveralls (see badge).

Pre-commit hooks are configured in `.pre-commit-config.yaml`; install once with `pre-commit install`.

---

## Releases

Versioning and changelog are automated via [python-semantic-release](https://python-semantic-release.readthedocs.io/) using **Conventional Commits**. Tag-allowlist and bump rules live under `[tool.semantic_release]` in [`pyproject.toml`](pyproject.toml):

| Commit type                  | Version bump |
|------------------------------|--------------|
| `feat:`                      | minor        |
| `fix:`, `perf:`, `refactor:` | patch        |
| `BREAKING CHANGE:` footer    | major        |
| `docs:`, `chore:`, `ci:`, `test:`, `style:`, `build:` | none |

See [`CHANGELOG.md`](CHANGELOG.md) for the generated history.

---
