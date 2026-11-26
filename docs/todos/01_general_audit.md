# AI BI Analytics — General Audit (security, architecture, quality, operations)

**Date:** 2026-11-26 · `main` at `8b090da` (v1.0.0 released).
**Scope:** the whole repository — `ai_bi_analytics/` (FastAPI backend),
`frontend/` (Streamlit demo), `example/` (bootstrap scripts), `tests/`,
`Dockerfile`, `docker-compose.yml`, `Makefile`, `pyproject.toml`, and
`.github/workflows/`.
**Method:** every tracked file was read end to end (53 files, ~200
statements of app code). Suspected defects were then reproduced rather than
inferred: the SQL validator was probed with a bypass / false-positive corpus,
the rate limiter was run against a real `redis-server`, a clean-clone
`uv sync --frozen` was attempted, and the released wheel in `dist/` was
unpacked. Findings marked **(verified)** come from those runs.

**Baseline:** `make test` → 30 passed, **100% line coverage**. That number
is misleading: three of the four 🔴 findings below sit on lines the suite
"covers", because the fakes in `tests/conftest.py` don't behave like the
real components (see TEST-1).

**Cross-reference:** this is the first backlog in `docs/todos/`; nothing is
tracked elsewhere.

---

## Summary

| Sev | ID | One-liner |
| --- | -- | --------- |
| 🔴 | SEC-1 | SQL guardrail is bypassable: `SELECT 1; <anything>` passes, and dangerous functions/catalogs aren't blocked |
| 🔴 | SEC-2 | Nothing enforces read-only at the database; bootstrap creates a **SUPERUSER** app role |
| 🔴 | SEC-3 | Rate limiter never blocks — 20/20 burst requests allowed (off-by-one + key collision + spoofable IP) |
| 🔴 | OPS-1 | Clean-clone Docker build fails; `.dockerignore` can't be committed so `.env` would be baked into the image |
| 🔴 | PKG-1 | Released v1.0.0 wheel contains only `main.py` + `__init__.py` — it can't be imported |
| 🟠 | SEC-4 | Every exception is returned verbatim as a 400 (DB hosts, SQL, provider errors leak) |
| 🟠 | SEC-5 | No row cap, no statement timeout; full result set goes into memory, the LLM prompt and Redis |
| 🟠 | SEC-6 | Unbounded question length; user text and DB row contents are interpolated raw into prompts |
| 🟠 | SEC-7 | Every table in the database is exposed to the LLM (no allowlist) |
| 🟠 | SEC-8 | Non-constant-time API-key compare, single static key, missing key → 422, frontend prints the key |
| 🟠 | OPS-2 | Observability is advertised but not wired (no exporter, no DB/Redis spans, `extra` fields dropped, trace ids always `N/A`) |
| 🟠 | OPS-3 | Health check doesn't check dependencies; no Docker/compose healthchecks |
| 🟠 | OPS-4 | Container runs as root, ships the demo UI's deps, compose publishes password-less Redis and test-cred Postgres |
| 🟠 | CI-1 | CI can't fail on formatting, doesn't run on PRs, and the release workflow doesn't wait for CI |
| 🟠 | TEST-1 | 100% coverage hides real defects — fakes diverge from real Redis/Lua/Postgres behaviour |
| 🟡 | CQ-1 | Validator false positives: `created_at`, `last_update`, `'Delete Key'`, and every CTE are rejected |
| 🟡 | PERF-1 | Full schema introspection on every request, even cache hits |
| 🟡 | PERF-2 | New OpenAI client (and HTTP pool) twice per request; no timeout; sync route holds a threadpool slot for both LLM calls |
| 🟡 | PERF-3 | Cache: exact-text keys only, unbounded values, hard dependency (Redis down → request fails) |
| 🟡 | ARCH-1 | Pipeline orchestration lives in the route handler |
| 🟡 | ARCH-2 | Config sprawl: env read in 3 places, tunables hardcoded, clients built at import time |
| 🟡 | ARCH-3 | LLM abstraction is a bare `complete(str) -> str`; model and `max_tokens=250` hardcoded |
| 🟡 | ARCH-4 | Lua script loaded via CWD-relative path on every request |
| 🟡 | CQ-2 | Dead/misleading code: empty `security.py`, test-only `Product` model, version drift, unused logger |
| 🟡 | CQ-3 | Streamlit demo crashes on 2–3 column results; posts to a redirecting URL |
| 🟡 | DX-1 | Makefile/README drift: phantom targets, missing pre-commit config, missing Roadmap section |
| 🟢 | FEAT-1…9 | Missing capabilities: audit log, self-correction, semantic context, pagination, cost gate, API hygiene, per-key scoping, eval harness, spend caps |

---

## Security

### 🔴 CRITICAL

**SEC-1. The SQL guardrail is bypassable and is the only real control.
(verified)**
`services/sql_validator.py:28-40` is four string checks on the upper-cased
text. The question is user-controlled and goes straight into the prompt
(SEC-6), so an attacker steers what the LLM emits — the validator is the
last line of defence, and it misses:

| Input | Result |
| ----- | ------ |
| `SELECT 1; GRANT ALL ON products TO public` | **ALLOWED** — `count(";") > 1` only rejects *two* semicolons |
| `SELECT pg_sleep(600)` | **ALLOWED** — ties up a connection for 10 min |
| `SELECT pg_read_file('/etc/passwd')` | **ALLOWED** |
| `SELECT usename, passwd FROM pg_shadow` | **ALLOWED** |
| `SELECT lo_import('/etc/passwd')`, `SELECT set_config(...)` | **ALLOWED** |

psycopg2 sends `text(sql)` over the simple-query protocol, which executes
every statement in the string. `GRANT`, `COPY`, `COMMIT`, `SET`, `DO`,
`CALL`, `VACUUM`, `LISTEN`… are not in `FORBIDDEN_KEYWORDS`. The worst
case is `SELECT 1; COPY (SELECT '') TO PROGRAM '<shell command>'`. It has
no forbidden keyword, and it runs OS commands whenever the role is a
superuser, which is exactly what the shipped bootstrap creates (SEC-2).
→ Replace the string checks with an AST validator (`sqlglot`, postgres
dialect): exactly one statement; root is `Select`/`Union`/`With`→`Select`;
every referenced table is in the allowlist (SEC-7); no system schemas
(`pg_catalog`, `information_schema`); functions checked against an
allowlist (aggregates, date/string/math) or at least a denylist
(`pg_*`, `lo_*`, `dblink*`, `set_config`, `current_setting`,
`query_to_xml`…). Strip markdown fences before parsing. This also fixes
CQ-1. **Effort: M.**

**SEC-2. Read-only is a README claim, not a property of the system.**
README says execution uses a "read-only role", but nothing enforces it:
`db/session.py:13-16` sets no session options, `get_db` never opens a
read-only transaction, and `example/db_user_setup.py:65-71` creates the app
user `WITH SUPERUSER CREATEDB CREATEROLE`. `docker-compose.yml:23` also
makes `test_user` the image superuser, and `example/gen_test_table_data.py`
connects as that user. Any SEC-1 bypass therefore runs with full
privileges.
→ Defence in depth that doesn't depend on SEC-1 being perfect:
(a) `connect_args={"options": "-c default_transaction_read_only=on -c statement_timeout=5000 -c idle_in_transaction_session_timeout=10000"}`;
(b) run each query inside `SET TRANSACTION READ ONLY` and always roll back;
(c) ship `example/readonly_role.sql`: a `NOSUPERUSER NOCREATEDB NOCREATEROLE`
role with `SELECT` on allowlisted tables only, and no `pg_read_server_files`,
`pg_execute_server_program` or `pg_monitor`;
(d) a startup check (`SELECT rolsuper, rolcreaterole FROM pg_roles WHERE rolname = current_user`)
that refuses to boot in non-development `ENV` if the role is privileged.
Rewrite `db_user_setup.py` to create two roles: an owner for seeding and a
read-only role for the app. **Effort: S–M.**

**SEC-3. The rate limiter never blocks. (verified)**
The verification run sent 20 rapid requests from one client against a real
Redis: **20 allowed, 0 blocked**, and the sorted set ended with **1
member**. There are three independent defects:
1. **Off-by-one contract mismatch.** The Lua script
   (`core/lua/sliding_window_rate_limit.lua:21-23`) returns `request_count`
   (= `limit`) when the window is full, without adding. Python
   (`core/rate_limiter.py:40`) rejects only when `count > RATE_LIMIT`. At
   the cap it gets `5`, `5 > 5` is false, and the request is allowed. The
   count can never exceed the limit, so the limiter can never fire.
2. **Member collision.** `ZADD key now now` uses whole-second timestamps as
   the member, so every request in the same second overwrites one entry and
   bursts are undercounted even once (1) is fixed.
3. **Spoofable key.** `client_ip = request.headers.get("X-Forwarded-For", ...)`
   (`rate_limiter.py:26-29`) trusts a client-supplied header verbatim. A
   new random value per request gets a fresh bucket. The header can also be
   a comma-separated chain.

The test suite passes because `conftest.py:158-168` replaces the script with
a counter that increments without bound (TEST-1).
→ Make the script return an explicit allow/deny (`0`/`1`) plus the
remaining count. Use a unique member (`now_ms .. ':' .. uuid` or Redis
`TIME` inside the script) and millisecond scores. Key on the authenticated
client identity (SEC-8) first and fall back to the IP. Take the IP from
`request.client.host` with uvicorn `--proxy-headers --forwarded-allow-ips`
set to the real proxy. Return `Retry-After` and `X-RateLimit-*` headers.
Make limits configurable (ARCH-2). **Effort: S.**

### 🟠 HIGH

**SEC-4. Raw exception text is returned to the caller.**
`api/routes/query.py:71-73` wraps the whole pipeline in `except Exception`
and returns `HTTPException(400, detail=str(exc))`. psycopg2 errors include
the server host/IP and the failing SQL; OpenAI errors include request ids
and quota details; SQLAlchemy errors include the full statement. A
connection-refused error with the Postgres container's internal IP has
already been seen in a response body during local debugging. Status codes
are also wrong: an LLM outage or DB timeout is reported as a client error
(400). `logger.error("Request failure: %s", str(exc))` drops the traceback.
→ A small exception hierarchy (`UnsafeSQLError`→422,
`LLMUnavailableError`→502/503, `QueryTimeoutError`→504, anything
else→500 with a generic message and a request id). Register handlers in
`create_app`, and log with `logger.exception(...)`. **Effort: S.**

**SEC-5. Unbounded queries and result sets.**
There is no `LIMIT` enforcement, no `statement_timeout` (SEC-2), and
`query_executor.py:24` calls `fetchall()`. One question like "show me
every order with every customer" (or the **(verified)** cartesian
`SELECT * FROM products a, products b, products c`) materialises the whole
result in API memory. The whole result is then interpolated into the
explanation prompt (`explanation.py:35-36`, which means token cost and
context-window failures), serialised into Redis (`cache.py:24-29`), and
returned as one JSON body.
→ Wrap the validated query as `SELECT * FROM (<sql>) AS q LIMIT :max_rows + 1`,
use `fetchmany`, and return `truncated: bool` and `row_count`. Send the
explanation step a bounded sample (first N rows + column stats), not the
full set. Skip caching above a byte threshold. Add a server-side
`statement_timeout`. See FEAT-4/FEAT-5 for pagination and cost gating.
**Effort: S–M.**

**SEC-6. Prompt construction has no input bounds or separation.**
`schemas/query.py:13` is `question: str` with no length limit, so a
megabyte question is accepted and forwarded to the LLM (cost-amplification
DoS). Both prompts (`nl_to_sql.py:37-45`, `explanation.py:26-42`) are one
f-string in a single `user` message, with the rules, schema, and untrusted
question all mixed. The explanation prompt also embeds **database row
contents**, a second injection channel: any user who can write a product
name can instruct the explainer.
→ `question: str = Field(min_length=3, max_length=500)` and strip control
characters. Put the rules in a `system` message and wrap the untrusted
question and data in clear delimiters. Ask for structured output (ARCH-3).
Treat model output as untrusted no matter what; SEC-1/SEC-2 are the real
controls, so this item is about cost and accuracy, not the security
boundary. **Effort: S.**

**SEC-7. The entire database is in scope.**
`services/schema_loader.py:23` sends every table in the default schema
(names + column types) to a third-party LLM, and the validator lets the
LLM query any of them. Point this at a real operational database and
`users`, `sessions`, `payments` and the like become queryable and are
disclosed to the provider.
→ `QUERYABLE_TABLES` (and optional `QUERYABLE_SCHEMAS`) plus a
`REDACTED_COLUMNS` denylist in Settings. Use them in the schema loader
(what the LLM sees) **and** the AST validator (what can run). Add a schema
option so analytics views in a dedicated schema can be exposed instead of
base tables. **Effort: S.**

**SEC-8. API-key authentication weaknesses.**
- `api/deps.py:17` compares with `!=`, which is not constant-time. Use
  `hmac.compare_digest`.
- There is one shared static key, with no rotation path (it can't accept
  old+new during a rollover) and no per-client identity. Rate limiting
  (SEC-3), auditing (FEAT-1) and scoping (FEAT-7) all need to know *who*
  called.
- A missing header gives **422** (FastAPI's `Header(...)` validation), not
  401. `tests/test_query.py:103` hides this by accepting `401, 403, 422`.
- `Header(...)` isn't a security scheme, so the key is missing from
  OpenAPI's "Authorize" flow. Use `fastapi.security.APIKeyHeader(auto_error=False)`.
- There is no guard against `API_KEY=change-me` (`.env.example:7`) or short
  keys outside development.
- `frontend/api.py:10` **prints the API key to stdout** on every Streamlit
  start.
→ `API_KEYS` as a set of `{client_id: sha256(key)}` entries, a
constant-time lookup, 401 on missing/invalid, a startup validation
(length ≥ 32, not a placeholder) when `ENV != development`, and remove the
print. **Effort: S.**

---

## Operations & delivery

### 🔴 CRITICAL

**OPS-1. The container build is broken from a clean clone, and would leak
secrets once fixed. (verified)**
- `.gitignore:50` ignores `uv.lock` (it was committed, then deleted in
  `dc2931e`). `Dockerfile:12` runs `uv sync ... --frozen`. On a clean clone
  this fails: `error: Unable to find lockfile at uv.lock, but --frozen was
  provided`. It only works on a machine that happens to have a local
  lockfile. Builds are also not reproducible, since every dependency is a
  floor (`>=`).
- `.gitignore:24` (`*.dockerignore`) also ignores **`.dockerignore`
  itself**, so it can never be committed. `Dockerfile:15` does `COPY . .`
  with no ignore file, which copies the local `.env` (API key, OpenAI key,
  DB password), `.venv/`, `test.db`, `.git/`, `dist/` and `.idea/` into an
  image layer.
→ Commit `uv.lock`, remove both ignore rules, and add a `.dockerignore`
(`.env*`, `.venv`, `.git`, `dist`, `*.db`, caches, `tests`, `frontend`,
`docs`). **Effort: S.**

**PKG-1. The released wheel is unimportable. (verified)**
`pyproject.toml:68-69` declares `packages = ["ai_bi_analytics"]`. That
lists the top-level package only, so setuptools omits every subpackage.
`dist/ai_bi_analytics-1.0.0-py3-none-any.whl` contains exactly
`ai_bi_analytics/__init__.py` and `ai_bi_analytics/main.py`, and
`import ai_bi_analytics.main` fails on `ai_bi_analytics.api`. The `.lua`
file isn't packaged either (not package data). `release.yaml` uploads this
artifact to the GitHub release.
→ `[tool.setuptools.packages.find] include = ["ai_bi_analytics*"]` +
`[tool.setuptools.package-data] ai_bi_analytics = ["core/lua/*.lua"]`
(or move to `hatchling`). Add a CI step that builds the wheel, installs it
into a fresh venv, and imports `ai_bi_analytics.main`. Also remove `build`
from runtime `dependencies` (`pyproject.toml:35`); it is a build-time tool.
**Effort: S.**

### 🟠 HIGH

**OPS-2. Observability is advertised but not wired.**
The README promises structured logging and "spans cover the API, Redis, and
DB calls so a single `trace_id` follows a request end-to-end". In the code:
- `main.py:47` calls `FastAPIInstrumentor.instrument_app(app)`, but no
  `TracerProvider` or exporter is configured anywhere, so spans go to the
  no-op provider. `opentelemetry-exporter-otlp` is installed but unused.
- There is no SQLAlchemy, Redis or HTTPX/OpenAI instrumentation, so no DB
  or Redis spans.
- `logging_config.py:16` formats `%(trace_id)s %(span_id)s`, but nothing
  injects them (no `LoggingInstrumentor`), so they are always `N/A`.
- `query.py:49-56` logs `extra={"question","sql","row_count"}`, but the
  text formatter never renders extras, so they are **silently dropped**.
  There is no JSON formatter.
- `OTEL_ENABLED` (`logging_config.py:5`) is read and never used;
  `settings.log_level` / `LOG_LEVEL` is never used (levels come from a
  separate `DEBUG` env var).
- The configured `"app"` logger (`logging_config.py:47`) matches nothing,
  because modules use `__name__` = `ai_bi_analytics.*`.
- There are no metrics: no LLM latency/tokens/cost, cache hit ratio,
  validator rejections or rate-limit denials.
- The full question and SQL are logged at INFO; once logs ship anywhere,
  treat questions as potentially sensitive.
→ JSON logs (`structlog` or `python-json-logger`) with a request-id
middleware. Set up the OTel SDK in `lifespan` behind `OTEL_ENABLED`
(OTLP exporter, resource attributes), with instrumentors for FastAPI,
SQLAlchemy, Redis, HTTPX and logging. Add custom spans per pipeline stage
(`schema`, `nl_to_sql`, `validate`, `execute`, `explain`) carrying token
usage attributes. Add an OTel metrics exporter or `/metrics`. Use one log
level setting. **Effort: M.**

**OPS-3. No real health or readiness signal.**
`/api/health` (`main.py:52-60`) always returns `ok`, even with Postgres or
Redis down. The Dockerfile has no `HEALTHCHECK`. Compose
`depends_on` (`docker-compose.yml:14-16`) only orders startup, so the API
starts before Postgres accepts connections. The engine and Redis pool are
never disposed on shutdown.
→ Split `/api/health/live` (process up) from `/api/health/ready` (`SELECT
1` + `PING`, with a short timeout), keep both unauthenticated and
rate-limit-exempt, and add a `HEALTHCHECK` plus compose `healthcheck` +
`condition: service_healthy`. Dispose the engine and close Redis in
`lifespan` after `yield`. **Effort: S.**

**OPS-4. Container and compose hardening.**
Dockerfile:
- It runs as **root** (no `USER`).
- The CMD is `uv run …` (`Dockerfile:24`). `uv run` may re-resolve or sync
  at start-up; call `.venv/bin/uvicorn` directly.
- It is single-stage, and the image carries `uv` plus the **Streamlit,
  pandas and Plotly** stack (`pyproject.toml:40-42` lists the demo UI's
  dependencies as backend runtime deps). That means a large image and a
  large CVE surface.
- The `python:3.14-slim` tag floats (no digest).
- Uvicorn runs one worker with no `--proxy-headers` (needed for SEC-3) and
  no `--timeout-graceful-shutdown`.

Compose:
- Redis is published on `0.0.0.0:6379` **with no password**.
- Postgres is published on `0.0.0.0:5433` with `test_user/test_pwd`
  superuser credentials.
- The API bind-mounts the source tree (`.:/app`) and has `restart: always`,
  which mixes dev and prod concerns.
- The obsolete `version: "3.14"` key draws a warning in Compose v2.
- The command (`create_app --factory`) differs from the Dockerfile's `CMD`
  (`main:app`), so the two run paths diverge.
→ Multi-stage build (builder with uv → slim runtime with only `.venv` and
the package), a non-root `USER app`, pinned base digest, and `HEALTHCHECK`.
Move streamlit/pandas/plotly/python-dotenv into an optional
`[project.optional-dependencies] frontend` group or a separate
`frontend/pyproject.toml`. Compose: bind ports to `127.0.0.1`, Redis
`--requirepass`, dev-only bind mount in `compose.override.yaml`, and one
start command. **Effort: M.**

**CI-1. CI doesn't gate anything that matters.**
- The "Format check" step (`ci.yaml:22-23`) runs `make format`, which runs
  `ruff format` and `ruff check --fix`. It **rewrites files and exits 0**,
  so it can't fail. It needs `ruff format --check` + `ruff check` (no fix).
- CI triggers only on `push` to `main` (`ci.yaml:3-5`), not on
  `pull_request`.
- `release.yaml` triggers on the same push and **doesn't depend on CI**, so
  a red build still cuts a release and uploads (the broken, see PKG-1)
  artifacts. Chain them with `workflow_run` or merge into one workflow with
  `needs:`.
- The README shows a Coveralls badge, but CI uploads no coverage, and there
  is no coverage floor (`--cov-fail-under`).
- `ruff`/`mypy` only cover `ai_bi_analytics/`; `tests/`, `frontend/` and
  `example/` are never linted (several test files fail `ruff format`).
- There is no dependency audit (`pip-audit` / `uv` audit), no SAST
  (`bandit` or CodeQL), no Docker build/scan step, and no Dependabot or
  Renovate.
- Actions are pinned by tag, not SHA. `release.yaml` has a leftover
  "Debug Git state" step and installs PSR unpinned with `pip`.
- There is no Postgres/Redis service container, so nothing in CI touches
  the real backends (TEST-1).
→ See the todos file, Phase 1. **Effort: S–M.**

**TEST-1. 100% coverage, low assurance.**
The suite reports 100% line coverage, yet it misses SEC-1, SEC-3, CQ-1 and
PKG-1:
- `conftest.py:158-168` fakes the rate-limit script with an unbounded
  counter that doesn't match the Lua semantics, so `test_rate_limit_blocks`
  passes while the real limiter never blocks.
- `test_rate_limiter.py:31-38` patches `redis_client.eval`, which the code
  never calls. The test asserts nothing.
- `test_sql_validator.py:38-41` (`WITH temp AS (DELETE …)`) passes because
  of the "must start with SELECT" rule, not because DELETE was detected.
  The validator has no adversarial corpus (multi-statement with one `;`,
  functions, catalogs, case and whitespace tricks, string literals).
- `test_query_missing_api_key` accepts `401, 403, 422`; it should pin 401.
- `conftest.py` patches both Redis *and* the cache functions, so the route
  never exercises `services/cache.py`.
- SQLite stands in for Postgres. Dialect, `information_schema`,
  multi-statement execution and read-only transactions can't be tested.
- `app = create_app()` runs at import time (`main.py:65`), and the `client`
  fixture builds a second app. `Settings()` needs env vars at import, which
  is why CI passes `API_KEY`/`DATABASE_URL`.
- Nothing tests the error-handling path, the prompt contents (that the
  schema and question appear and the rules come first), the schema loader
  output format, or executor limits.
→ Use `fakeredis[lua]` (runs the real Lua) or a testcontainers Redis, plus
an `@pytest.mark.integration` Postgres suite (CI service container) for
the executor, the read-only role and the validator corpus. Turn on branch
coverage with a floor. Use real dependency injection (ARCH-1) so tests
override providers instead of monkeypatching module paths. **Effort: M.**

---

## Code quality, architecture, performance

### 🟡 MEDIUM

**CQ-1. The validator rejects legitimate analytics SQL. (verified)**
A substring check on upper-cased text rejects:
- `SELECT created_at FROM orders` (contains `CREATE`);
- `SELECT last_update FROM t` (contains `UPDATE`);
- `WHERE name = 'Delete Key'` (inside a string literal);
- **every CTE**, since `WITH x AS (SELECT 1) SELECT …` fails the
  `startswith("SELECT")` check.

An LLM answer wrapped in a ```` ```sql ```` fence also fails, even though
the prompt asks for no fences. Users see a 400 "Forbidden SQL keyword" on
correct queries. → Fixed by SEC-1's AST approach. Add these cases as
regression tests. **Effort: incl. in SEC-1.**

**PERF-1. Schema introspection runs on every request, before the cache
lookup.**
`query.py:38-39` calls `load_schema_metadata(db)` first, which does
`get_table_names()` plus one `get_columns()` per table (N+1 catalog
queries). That happens on cache hits too, and the full schema text then
becomes part of the hashed cache key.
→ Cache the rendered schema in-process (TTL, e.g. 5 min) and in Redis keyed
by a schema fingerprint. Use the **fingerprint**, not the full text, in the
response cache key. Look up the cache first and introspect only on a miss.
**Effort: S.**

**PERF-2. LLM client lifecycle and concurrency.**
`get_llm_client()` builds a new `OpenAI(...)`, and so a new HTTPX
connection pool, on every call. That is twice per request (`nl_to_sql.py:35`,
`explanation.py:24`), with no keep-alive reuse. The client sets no
`timeout` (the SDK default is 10 minutes) and no explicit `max_retries`.
The route is a sync `def`, so each request holds one of AnyIO's ~40
threadpool tokens for two serial LLM round-trips, and throughput caps out
early under load.
→ Build one client in `lifespan` and inject it with `Depends`. Set
`timeout≈20s` and `max_retries=2`. Either go async (`AsyncOpenAI`, async
route, async DB via `asyncpg`) or deliberately size the threadpool and
document it. Consider making the explanation optional
(`?explain=false`) or streaming it. **Effort: M.**

**PERF-3. Cache design.**
- The key is `sha256(question + "|" + schema)` (`query.py:39`), so
  "Top 3 products" and "top 3 products " miss each other. Normalise
  (case-fold, collapse whitespace) at minimum.
- Values are unbounded (see SEC-5).
- The TTL is fixed at 300 s and not configurable.
- There are no hit/miss metrics.
- **Redis is a hard dependency.** If it is down, `enforce_rate_limit` and
  `get_cached_response` raise and the whole request fails (as a 400, see
  SEC-4).
→ Cache reads and writes should fail open (log and continue). The rate
limiter should have an explicit `RATE_LIMIT_FAIL_OPEN` policy. Normalise
keys, make the TTL configurable, add a size cap, and emit metrics. Tenant
and key scoping of cache entries becomes necessary once FEAT-7 lands.
**Effort: S.**

**ARCH-1. Orchestration lives in the route.**
`api/routes/query.py:26-73` runs the schema, cache, NL→SQL, validate,
execute, explain, log and cache-write steps inline. Each service grabs its
own collaborators through module-level globals (`get_llm_client()`,
`redis_client`), so tests have to monkeypatch import paths (see
`conftest.py`).
→ Add a `QueryPipeline` service with injected `LLMClient`, `SchemaProvider`,
`SQLGuard`, `QueryExecutor` and `ResultCache`, wired once in `lifespan` and
exposed via `Depends`. The route becomes about 10 lines. This is also the
natural seam if the NL→SQL core is later extracted into a reusable library.
**Effort: M.**

**ARCH-2. Config sprawl and import-time side effects.**
- `REDIS_URL` comes from `os.getenv` in `core/redis_client.py:13`, and
  `DEBUG`/`OTEL_ENABLED` from `os.getenv` in `logging_config.py:4-5`;
  `Settings` knows about neither.
- `RATE_LIMIT`, `WINDOW_SECONDS`, `CACHE_TTL`, the model name
  (`"gpt-4o-mini"`, `llm_client.py:41`) and `max_tokens` are hardcoded.
- `Settings()` (`config.py:39`), the SQLAlchemy engine (`session.py:13`),
  the Redis client and `app` (`main.py:65`) are all created at **import
  time**.
- `env` is an unvalidated `str`.
→ Move everything into `Settings`. Use `env: Literal["development",
"staging","production"]`, `SecretStr` for keys, `RedisDsn`/`PostgresDsn`
types, and `@lru_cache get_settings()`. Create the engine and clients in
`lifespan` (or lazily) so imports have no side effects. **Effort: S–M.**

**ARCH-3. The LLM abstraction is too thin to be swappable in practice.**
`BaseLLMClient.complete(prompt: str) -> str` doesn't support system
messages, structured output or token usage. The provider is selected by
string compare and the model is hardcoded. `max_tokens=250`
(`llm_client.py:43`) is shared by both SQL generation and explanation, so a
moderately complex query (joins, CTEs, CASE) can be **truncated** and then
rejected or, worse, executed partially formed.
→ Task-level methods (`generate_sql(question, schema) -> SQLDraft`,
`explain(...) -> str`), structured output (JSON schema or tool call
returning `{sql, tables_used, assumptions}`), per-task model and
`max_tokens` settings, and `usage` returned for metering (FEAT-9). Add a
provider registry so a second provider is a new class plus a config value.
**Effort: M.**

**ARCH-4. The Lua script loads via a CWD-relative path on every request.**
`core/rate_limiter.py:16` does `open("ai_bi_analytics/core/lua/…")`. That
breaks when the process isn't started from the repo root (an installed
wheel, a different `WORKDIR`, or a test runner run from elsewhere). The
file is also read and re-registered on every request.
→ `importlib.resources.files(__package__) / "lua" / "…"`, registered once
at startup. Package the file (PKG-1). **Effort: S.**

**CQ-2. Dead and misleading code.**
- `core/security.py` is empty.
- `db/models.py` `Product` is used only by tests. The app is
  schema-agnostic, so the model belongs in `tests/fixtures`.
- FastAPI reports `version="0.1.0"` (`main.py:43`) while the package is
  `v1.0.0`. Read it from `importlib.metadata.version(...)`. Also,
  `version = "v1.0.0"` in `pyproject.toml:7` relies on PEP 440
  normalisation; drop the `v`.
- `# noqa B008` (`query.py:73`) sits on a `raise`, not a default argument,
  and B008 is already ignored globally.
- The lifespan log uses an f-string on the root logger (`main.py:22`).
- `black` and `isort` sit in dev deps and config alongside `ruff`, which
  already covers both.
- mypy disables `union-attr` and `arg-type` globally (`pyproject.toml:95-98`),
  which hides real `None` bugs (e.g. `request.client` can be `None` at
  `rate_limiter.py:28`).
- `schema_loader` builds a string with `+=` in a loop.
**Effort: S.**

**CQ-3. Streamlit demo bugs.**
- `frontend/utils.py:6-10` checks `df.shape[1] < 2`, then indexes
  `df.columns[2]` and `[3]`. Any 2- or 3-column result (`name, revenue`,
  the most common BI shape) raises `IndexError` and crashes the page.
  `[0]`/`[1]` were intended, or better, pick the first categorical and
  first numeric column.
- It posts to `/api/query/` (trailing slash) while the route is
  `/api/query`, costing a 307 redirect per call.
- It prints the API key (SEC-8).
- It shows raw backend error text.
- `requests` is used but not declared.
- None of the frontend is linted.
**Effort: S.**

**DX-1. Makefile and README drift.**
- `make help` lists `run`, `prod` and `check`, which don't exist (the real
  targets are `run_local` and `run_prod`, and there is no `check`).
- `release: build publish` depends on a `publish` target that doesn't
  exist.
- `venv_setup` runs `uv venv … &` (backgrounded) and then `source`, which
  can't affect the caller's shell from make. It also pins `--python 3.14`
  while `requires-python` allows 3.12.
- `clean` uses `-type d -name "*.pyc"`, which deletes nothing.
- The leftover `tempTarget` has CI-flavoured credentials.
- The README says pre-commit "is configured in `.pre-commit-config.yaml`",
  but **that file doesn't exist**. The README's table of contents links a
  `Roadmap` section that doesn't exist either.
- `pyproject` URLs carry `# todo` markers.
**Effort: S.**

---

## Missing capabilities

### 🟢 LOW (product-shaped; each needs a scope decision before building)

- **FEAT-1. Query audit log.** Persist who asked what, generated SQL,
  validator verdict, row count, latency, tokens and cost per request (a
  Postgres table in a separate, writable schema or DB). This is the
  "auditable" story the README implies, and the data source for FEAT-8/9.
- **FEAT-2. Self-correction loop.** On validator rejection or DB error,
  re-prompt once with the error (bounded retries) before failing. This is
  the single biggest accuracy win for NL→SQL.
- **FEAT-3. Semantic context.** Include Postgres `COMMENT ON` table and
  column descriptions, FK relationships, a few sample distinct values for
  low-cardinality columns, a business glossary, and few-shot
  question→SQL examples in the prompt.
- **FEAT-4. Pagination and truncation metadata.** `limit`/`cursor` on the
  request, plus `truncated` and `row_count` on the response (builds on
  SEC-5).
- **FEAT-5. Pre-execution cost gate.** `EXPLAIN (FORMAT JSON)` and reject
  above a configured total cost or row estimate. This complements
  `statement_timeout`.
- **FEAT-6. API hygiene.** Version the API (`/api/v1`), disable or protect
  `/docs` and `/redoc` in production, an explicit CORS policy, security
  headers, a request-size limit, and typed error response schemas in
  OpenAPI.
- **FEAT-7. Per-client scoping / RBAC.** Once keys carry identity (SEC-8),
  map clients to allowed tables/schemas and row-level filters, and scope
  cache entries accordingly.
- **FEAT-8. Evaluation harness.** A golden set of questions with expected
  SQL or result fingerprints against the seed DB, run in CI (or nightly
  with a real model) to catch prompt or model regressions.
- **FEAT-9. Spend controls.** The README lists "unbounded LLM spend" as a
  risk this project addresses, but the only control is the (broken) rate
  limiter. Add per-key daily token/cost budgets from `usage` (ARCH-3) and a
  global circuit breaker.
