# Architecture

How a request flows through the service, where each piece lives, and the
decisions behind the shape. The audit backlog in
[`todos/01_general_audit_todos.md`](todos/01_general_audit_todos.md) has
the history.

## Request path

```
POST /api/query
  │
  ├─ verify_api_key        api/deps.py         401 on a missing/unknown key
  ├─ rate_limited_client   api/deps.py         429 when the client's window is full
  ├─ get_db                api/deps.py         one session per request
  └─ QueryPipeline.run     services/pipeline.py
       ├─ query.scope         SchemaProvider       in-process, TTL'd (SCHEMA_CACHE_TTL_SECONDS)
       ├─ query.cache_lookup  ResultCache          Redis; fails open
       ├─ query.generate_sql  LLMClient            structured output: sql, tables_used, assumptions
       ├─ query.validate      SQLGuard             AST guard; returns the SQL that will run
       ├─ query.execute       QueryExecutor        READ ONLY transaction, row cap
       └─ query.explain       LLMClient            skipped when the request sets explain=false
```

Each stage is an OpenTelemetry span under the FastAPI request span.
Typed errors (`core/errors.py`) and database/Redis exceptions bubble up to
the handlers in `main.py`, which map them to client-safe JSON.

## Wiring

- **Settings** (`core/config.py`): every tunable is a field on `Settings`,
  read from the environment once. `get_settings()` caches the instance;
  `create_app(cfg)` stores the one it uses on `app.state.settings`, and
  request code reads it from there. Nothing reads `os.environ` directly.
- **Process-wide clients** (`resources.py`): the SQLAlchemy engine, the
  Redis client and the LLM client (each with its own connection pool) and
  the schema cache are built in the lifespan, not at import, and closed on
  shutdown. A failed startup step still closes them.
- **Dependencies** (`api/deps.py`): the route asks for a `QueryPipeline`,
  assembled per request from `get_llm`, `get_schema_provider`,
  `get_result_cache` and the settings. Assembly is a handful of attribute
  reads; the pools behind them are shared.
- **Tests** build the app with `create_app(settings, resources_factory=…)`
  to get SQLite, fakeredis and a fake LLM provider, and swap single pieces
  with `app.dependency_overrides`. Nothing patches import paths.

## LLM layer

`services/llm_client.py` has two levels:

- `ChatProvider`: one chat completion against a vendor. Providers register
  by name (`@register_provider("openai")`) and `LLM_PROVIDER` picks one.
  The OpenAI provider keeps a single SDK client per process, with
  `LLM_TIMEOUT_SECONDS` per attempt and `LLM_MAX_RETRIES` retries (the SDK
  retries connection errors, 408/409/429 and 5xx with backoff).
- `LLMClient`: the tasks. `generate_sql()` asks for JSON against a strict
  schema and parses it (`services/nl_to_sql.py`); a provider without
  structured output can answer with bare SQL, which the parser accepts
  because the guard validates either way. `explain()` sends a bounded
  sample of rows (`services/explanation.py`). Each task has its own model
  and token cap (`LLM_SQL_*`, `LLM_EXPLAIN_*`), and both return token
  usage, which the pipeline logs per query.

To add a provider, implement `complete()` and `close()` and register it:

```python
@register_provider("acme")
class AcmeProvider:
    name = "acme"

    def __init__(self, cfg: Settings) -> None: ...
    def complete(self, *, system, prompt, model, max_tokens, response_format=None) -> Completion: ...
    def close(self) -> None: ...
```

## Caching

| Cache | Where | Key | Invalidation |
|---|---|---|---|
| Query scope | in process | (one per process) | `SCHEMA_CACHE_TTL_SECONDS` (default 300 s) |
| Responses | Redis | normalised question + scope fingerprint + SQL model + row cap | `CACHE_TTL_SECONDS` (default 300 s) |

The scope fingerprint hashes everything that changes an answer (schema,
visible columns and types, redactions), so a schema change produces new
keys rather than stale hits. A schema change reaches the prompt and the
guard within one scope TTL.

The scope is **not** shared through Redis on purpose. It is the SQL
guard's table allowlist, and the guard must not depend on anything a Redis
client could write. Introspection costs a few catalog queries once per
TTL per process, so there is little to gain.

A cached answer stored without an explanation (`explain: false`) is
explained on the next request that wants one, and the entry is upgraded:
one LLM call instead of two.

## Decision: a synchronous pipeline on a sized threadpool (PERF-2)

**Context.** A query makes up to two LLM calls (seconds each) plus a
database round trip. The route is a plain `def`, so Starlette runs it in
AnyIO's worker threadpool; the event loop itself never blocks.

**Options.**

1. Fully async: `AsyncOpenAI`, an async route, `redis.asyncio`, and
   `asyncpg` or psycopg 3 async through SQLAlchemy's asyncio extension.
2. Keep the synchronous stack and size the threadpool deliberately.

**Decision: option 2.** Every blocking call releases the GIL while it
waits on I/O, so threads give real concurrency here. Going async would mean
rewriting the executor (`SET TRANSACTION READ ONLY`, `fetchmany`
truncation), the guard's Postgres integration tests, the rate limiter and
the cache, for no change in what one process can serve: throughput is
bounded by the LLM provider's latency and rate limits, not by thread
overhead, and the per-client rate limit (5 requests per minute by default)
keeps concurrency low.

**Sizing.**

- `WORKER_THREADS` (default 40, AnyIO's default) caps concurrent requests
  per process; extra requests queue.
- `DB_POOL_SIZE` + `DB_MAX_OVERFLOW` (default 5 + 10) caps concurrent
  database work. A request checks a connection out only while its query
  runs (the executor rolls back, which returns it), not during the LLM
  calls, so a pool much smaller than the threadpool is normal. When every
  connection is busy, a query waits up to SQLAlchemy's 30 s pool timeout.
- Scale out with more containers (`WEB_CONCURRENCY=1` each) rather than
  more threads; each container has its own pools.
- The worst case for one request is about
  `2 × LLM_TIMEOUT_SECONDS × (LLM_MAX_RETRIES + 1)` plus backoff; lower
  either setting for tighter latency bounds.

**Revisit when** a single process must hold hundreds of concurrent slow
requests (long-polling, streaming answers), or the provider SDK drops
synchronous support.

**Also added:** `explain: false` on the request skips the second LLM call,
for callers that only need the rows.
