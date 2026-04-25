# AI-Powered Business Intelligence Tool

![FastAPI](https://img.shields.io/badge/FastAPI-Backend-green)
![Python](https://img.shields.io/badge/Python-3.14-blue)
![Redis](https://img.shields.io/badge/Redis-Caching-red)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-blue)
![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-Observability-purple)
![Docker](https://img.shields.io/badge/Docker-Containerized-blue)
![Tests](https://img.shields.io/badge/tests-pytest-100%25-coverage-green)


---

# Overview

A production-grade FastAPI tool enabling **natural-language queries over PostgreSQL** with safe SQL generation and explainable outputs.

This project demonstrates how to design **AI-powered systems safely and reliably**, combining modern LLM capabilities with strict backend guardrails.

---

# Problem

Business users often need insights from relational databases but cannot write SQL.

Naive LLM integrations introduce serious risks:

- SQL injection
- Destructive queries
- Hallucinated outputs
- Lack of observability
- Uncontrolled API usage

---

# Solution

This tool implements a **safe AI query pipeline**:

- Converts natural language → SQL
- Enforces strict SQL safety validation
- Executes queries using read-only database access
- Generates grounded explanations
- Applies distributed rate limiting
- Uses Redis caching to reduce LLM calls
- Provides observability via structured logging and tracing

---

# Architecture

``` 

  +-------------------+
  |      Client       |
  +---------+---------+
            |
            v
  +-------------------+
  |      FastAPI      |
  |      API Layer    |
  +---------+---------+
            |
            v
  +-------------------+
  |  NL → SQL Service |
  | (LLM Abstraction) |
  +---------+---------+
            |
            v
  +-------------------+
  |  SQL Validator    |
  |  (Read-Only Safe) |
  +---------+---------+
            |
            v
  +-------------------+
  |    PostgreSQL     |
  |     Database      |
  +---------+---------+
            |
            v
  +-------------------+
  | Explanation Layer |
  +-------------------+

Supporting Systems
──────────────────────────
**Redis** -> (Caching + Rate Limiting)
**OpenTelemetry** -> Tracing
**Structured Logging** -> Observability

```

---

# Key Features

### Natural Language to SQL
Transforms user questions into executable SQL queries using an LLM abstraction layer.

**Example:**

"What are the top 3 products by revenue?"


---

# SQL Safety Guardrails

The system enforces strict rules:

- Only `SELECT` queries allowed
- No `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`
- Single statement enforcement
- SQL validation layer before execution

This prevents destructive queries.

---

# Redis Distributed Caching

The backend caches query results using Redis:

- prevents repeated LLM calls
- improves latency
- reduces infrastructure cost

Cache TTL: **5 minutes**

---

# Redis Sliding Window Rate Limiting

The API enforces request quotas using **Redis Lua scripts**.

Features:

- distributed rate limiting
- sliding window algorithm
- atomic execution
- high concurrency safety

Example policy:

`5 requests per minute per client`

---

# Dynamic Schema Introspection

The system dynamically extracts database schema using SQLAlchemy.

This allows the LLM to generate accurate SQL without hardcoded schema descriptions.

Benefits:

- prevents schema drift
- improves query accuracy

---

# Observability

The service includes **production-grade observability**.

### Structured Logging

Logs include:

- request lifecycle
- cache hits/misses
- SQL execution
- error tracing

Example log:

`[INFO] Query executed rows=3 latency_ms=41`


---

### Distributed Tracing

Using **OpenTelemetry instrumentation for FastAPI**.

Each request includes:

- `trace_id`
- `span_id`


This enables tracing across:

- API calls
- Redis
- database queries

---

# Key Engineering Decisions

- LLM abstraction layer
- Explicit SQL safety validation
- Redis-based distributed caching
- Lua-based sliding window rate limiter
- Dynamic database schema introspection
- Structured logging
- OpenTelemetry tracing
- Dependency injection for testability
- Dockerized infrastructure


---

## Tech Stack

| Layer | Technology |
|------|-------------|
| API Framework | FastAPI |
| Database | PostgreSQL |
| Cache / Rate Limiting | Redis |
| LLM Integration | OpenAI (abstracted provider layer) |
| Observability | OpenTelemetry |
| Containerization | Docker |
| Task Automation | Makefile |
| Python Environment | uv |

---


# Project Structure

## Project Structure

```
ai-bi-analytics/
│
├── app/
│   ├── api/                    # FastAPI route definitions
│   │   └── query_routes.py
│   │
│   ├── services/               # Core business logic
│   │   ├── nl_to_sql.py
│   │   ├── explanation_service.py
│   │   └── query_executor.py
│   │
│   ├── validators/             # SQL safety validation
│   │   └── sql_validator.py
│   │
│   ├── db/                     # Database access layer
│   │   ├── database.py
│   │   └── schema_introspection.py
│   │
│   ├── core/                   # Shared configs and utilities
│   │   ├── config.py
│   │   └── dependencies.py
│   │
│   └── observability/          # Logging and telemetry
│       ├── logging.py
│       └── tracing.py
│
├── example/                    # Quick-start DB setup and seed scripts
│   ├── db_user_setup.py        # Provisions Postgres role + database (host Postgres)
│   └── gen_test_table_data.py  # Creates and populates sample products table
│
├── tests/                      # Unit and integration tests
│
├── Dockerfile                  # Container definition
├── docker-compose.yml          # Local multi-service setup
├── Makefile                    # Developer workflow commands
├── pyproject.toml              # Python project configuration
├── .env.example                # Environment configuration template
└── README.md                   # Project documentation
```

---
## Starting the app

- First create your environment configuration.
- Create `.env` file based on `.env.example` at the root of the project.
- Update the variables according to your needs.
- Next you can either run the app the docker way or directly from the repo.

### Option 1 — Run with Docker

```bash
(ai-bi-analytics) user@comp: ai-bi-analytics\λ make docker-build
(ai-bi-analytics) user@comp: ai-bi-analytics\λ make docker-up
(ai-bi-analytics) user@comp: ai-bi-analytics\λ python example/gen_test_table_data.py # create products table with some dummy data
(ai-bi-analytics) user@comp: ai-bi-analytics\λ make docker-down # stop the container
```

### Option 2 — Run Locally (Recommended for Development)


```bash

curl -LsSf https://astral.sh/uv/install.sh | sh # install uv globally
user@comp: ai-bi-analytics~$ # clone and navigate to the project directory
user@comp: ai-bi-analytics~$ make venv_setup # create venv
user@comp: ai-bi-analytics~$ source .venv/bin/activate # activate the venv
(ai-bi-analytics) user@comp: ai-bi-analytics~$ make help # show available make commands
(ai-bi-analytics) user@comp: ai-bi-analytics~$ make install-dev
(ai-bi-analytics) user@comp: ai-bi-analytics~$ make all # clean lint format fix test
(ai-bi-analytics) user@comp: ai-bi-analytics~$ make run_local # start the API
(ai-bi-analytics) user@comp: ai-bi-analytics~$ python example/gen_test_table_data.py # to create products table with some dummy data
```

---
## API Usage

- Once the service is running, you can send requests to the API.
- Authentication requires an API key.

```
Header:
x-api-key: YOUR_API_KEY
```

**Sample Request:**

```json
POST {{baseUrl}}/api/query/

{
  "question": "What are the top 3 products by revenue?"
}
```

**Sample Response:**
```json
{
  "sql": "SELECT product_name, SUM(revenue) AS total_revenue FROM products GROUP BY product_name ORDER BY total_revenue DESC LIMIT 3;",
  "result": [
    {
      "product_name": "Product A",
      "total_revenue": 125000
    },
    {
      "product_name": "Product B",
      "total_revenue": 98000
    },
    {
      "product_name": "Product C",
      "total_revenue": 87000
    }
  ],
  "explanation": "The top three products by revenue are Product A, Product B, and Product C based on the total sales recorded in the database."
}
```