# AI BI Analytics — General Audit Backlog

Execution checklist for [`01_general_audit.md`](01_general_audit.md).
IDs match that file; evidence, file:line references and rationale live
there. Ship order is phase order. Items within a phase are independent
unless a dependency is noted.

> **Status (2026-11-26):** **Filed, nothing shipped.** Phase 0 is the
> go-live blocker set. The service shouldn't be pointed at any database
> holding real data until SEC-1, SEC-2 and SEC-3 are done, and v1.0.0
> artifacts shouldn't be consumed until PKG-1 is done. Phases 4–5 are
> product-shaped and need a scope decision before anyone builds them.

---

## Phase 0 — Stop the bleeding (security + broken build) 🔴

- [ ] **SEC-2 — Enforce read-only at the database (ship first, cheapest
  real control).**
  - [ ] `db/session.py`: `connect_args={"options": "-c default_transaction_read_only=on -c statement_timeout=<cfg> -c idle_in_transaction_session_timeout=<cfg>"}`
    (Postgres only; skip for SQLite in tests).
  - [ ] `query_executor.py`: run inside `SET TRANSACTION READ ONLY`; always
    `rollback()`.
  - [ ] `example/readonly_role.sql` + rewrite `example/db_user_setup.py`:
    an owner role for seeding, a `NOSUPERUSER NOCREATEDB NOCREATEROLE`
    read-only role with `SELECT` on allowlisted tables only, and no
    `pg_read_server_files` / `pg_execute_server_program` membership.
  - [ ] Startup guard in `lifespan`: refuse to boot when `ENV != development`
    and `current_user` has `rolsuper` or `rolcreaterole`.
  - [ ] `.env.example` and README: the app connects as the read-only role;
    seeding uses the owner role.
- [ ] **SEC-1 + CQ-1 — Replace the string validator with an AST guard.**
  - [ ] Add `sqlglot`; parse with the postgres dialect; reject anything
    other than exactly one statement whose root is `Select`, `Union` or
    `With`→`Select`.
  - [ ] Table allowlist check (depends on SEC-7 settings; until then, use
    the reflected table set). Reject `pg_catalog` / `information_schema`
    references.
  - [ ] Function allowlist (aggregates, date/time, string, math,
    `COALESCE`/`CASE`…) or, at minimum, a denylist: `pg_*`, `lo_*`,
    `dblink*`, `set_config`, `current_setting`, `query_to_xml*`, `copy`.
  - [ ] Strip markdown code fences before parsing.
  - [ ] Adversarial test corpus covering every **(verified)** row in the
    findings table plus case and whitespace variants; regression tests for
    `created_at`, `last_update`, string literals and CTEs passing.
- [ ] **SEC-3 — Make the rate limiter actually limit.**
  - [ ] Lua: return `{allowed(0|1), count}`; unique member (Redis `TIME`
    micros + random suffix); millisecond scores; `PEXPIRE`.
  - [ ] Python: branch on `allowed`; return `Retry-After` and
    `X-RateLimit-Limit/Remaining`.
  - [ ] Key on the client id once SEC-8 lands; meanwhile use
    `request.client.host` only. Drop the raw `X-Forwarded-For` read and run
    uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy>`.
  - [ ] Move the limit and window into Settings (with ARCH-2).
  - [ ] Replace the conftest fake with `fakeredis[lua]` so tests run the
    real script; assert request N+1 gets a 429 (see TEST-1).
- [ ] **OPS-1 — Fix the clean-clone build and stop baking secrets into
  images.**
  - [ ] Remove `uv.lock` and `*.dockerignore` from `.gitignore`; commit
    `uv.lock`.
  - [ ] Add `.dockerignore` (`.env*`, `.venv`, `.git`, `dist`, `*.db`,
    caches, `.idea`, `.qodo`, `tests`, `docs`, `frontend`, `example`).
  - [ ] Verify with `git clone` into a temp dir, then `docker build`.
- [ ] **PKG-1 — Ship an importable wheel.**
  - [ ] `[tool.setuptools.packages.find] include = ["ai_bi_analytics*"]`
    and `[tool.setuptools.package-data] ai_bi_analytics = ["core/lua/*.lua"]`.
  - [ ] Remove `build` from runtime `dependencies`; drop the `v` from
    `version`.
  - [ ] CI smoke step: `uv build` → fresh venv → `pip install dist/*.whl`
    → `python -c "import ai_bi_analytics.main"`.
  - [ ] Decide whether to yank or annotate the broken v1.0.0 GitHub
    release assets.

## Phase 1 — Harden the request path and make CI a real gate 🟠

- [ ] **SEC-4 — Typed errors, no leakage.** An exception hierarchy in
  `ai_bi_analytics/core/errors.py` (`UnsafeSQLError` 422,
  `LLMUnavailableError` 502/503, `QueryTimeoutError` 504, a fallback 500)
  with handlers registered in `create_app`; `logger.exception` with a
  request id; the response body has a generic message plus the request id.
  Delete the blanket `except Exception` in the route.
- [ ] **SEC-5 — Bound every query.** `LIMIT :max_rows + 1` wrapper,
  `fetchmany`, `truncated`/`row_count` on `QueryResponse`, a bounded
  sample for the explanation prompt, no caching above `CACHE_MAX_BYTES`.
  Timeouts come from SEC-2.
- [ ] **SEC-6 — Prompt input bounds.**
  `question: str = Field(min_length=3, max_length=<cfg, default 500>)`;
  strip control characters; system/user message split; delimited
  untrusted blocks for the question and result data.
- [ ] **SEC-7 — Table/schema allowlist.** `QUERYABLE_SCHEMAS`,
  `QUERYABLE_TABLES` and `REDACTED_COLUMNS` in Settings, used by
  `schema_loader` *and* the SEC-1 guard; fail closed in non-dev if
  `QUERYABLE_TABLES` is unset.
- [ ] **SEC-8 — API-key auth.**
  - [ ] `APIKeyHeader(name="x-api-key", auto_error=False)`; missing or
    invalid → 401 (pin the test).
  - [ ] `API_KEYS` as `client_id:sha256` pairs; `hmac.compare_digest`
    lookup; return a `Principal(client_id)` dependency used by the rate
    limiter and logs.
  - [ ] Startup validation outside dev: ≥ 32 chars, not `change-me`.
  - [ ] Remove `print("API KEY:", …)` from `frontend/api.py`.
- [ ] **CI-1 — CI gates.**
  - [ ] Trigger on `pull_request` + `push: main`.
  - [ ] Add a `make check` target: `ruff format --check .`, `ruff check .`,
    `mypy`; CI runs that instead of `make format`. Extend ruff to `tests/`,
    `frontend/` and `example/`.
  - [ ] `pytest --cov-branch --cov-fail-under=<n>`; upload coverage
    (Coveralls, to make the README badge real) or remove the badge.
  - [ ] `uv audit` or `pip-audit`; `bandit -r ai_bi_analytics` (or
    CodeQL); Dependabot for `uv`, `github-actions` and `docker`.
  - [ ] Docker build job (+ Trivy/Grype scan) and the PKG-1 wheel smoke
    test.
  - [ ] Release only after CI is green (one workflow with
    `needs: [lint-test, build]`, or `workflow_run` on CI success). Pin
    actions to SHAs, pin the PSR version, and delete the "Debug Git state"
    step.
- [ ] **TEST-1 — Tests that would have caught Phase 0.**
  - [ ] `fakeredis[lua]` for the limiter and cache; remove the dead
    `redis_client.eval` patch test.
  - [ ] An `integration` marker with a Postgres service container in CI:
    executor + read-only role (a write attempt must fail) + validator
    corpus end to end + multi-statement attempt.
  - [ ] Route tests that exercise the real `services/cache.py` (stop
    patching the cache functions).
  - [ ] Error-path tests for each SEC-4 status code; prompt-content tests
    for `nl_to_sql` and `explanation`; `schema_loader` output test.

## Phase 2 — Operability 🟠

- [ ] **OPS-2 — Wire observability for real.**
  - [ ] JSON logging (`structlog` or `python-json-logger`) honouring
    `settings.log_level`; delete the `DEBUG`/`OTEL_ENABLED` `os.getenv`s
    and the dead `"app"` logger.
  - [ ] A request-id middleware (accept the inbound `X-Request-ID` or
    generate one), bound into the log context and echoed in responses.
  - [ ] OTel SDK bootstrap in `lifespan` behind `OTEL_ENABLED`: OTLP
    exporter, service resource attributes, and FastAPI + SQLAlchemy +
    Redis + HTTPX + logging instrumentors.
  - [ ] Manual spans per pipeline stage, with LLM token usage as span
    attributes.
  - [ ] Metrics: LLM latency/tokens/cost, cache hit ratio, validator
    rejections by reason, rate-limit denials, rows returned, truncations.
  - [ ] Decide the logging policy for raw questions and SQL (INFO vs
    DEBUG, redaction).
  - [ ] Correct the README's observability section to match what ships.
- [ ] **OPS-3 — Health and lifecycle.** `/api/health/live` +
  `/api/health/ready` (DB `SELECT 1` + Redis `PING`, short timeouts,
  unauthenticated, rate-limit-exempt); dispose the engine and close Redis
  in `lifespan` teardown; Dockerfile `HEALTHCHECK`; compose
  `healthcheck` + `depends_on: condition: service_healthy`.
- [ ] **OPS-4 — Container and compose hardening.**
  - [ ] Multi-stage Dockerfile (uv builder → slim runtime), non-root
    `USER`, base pinned by digest, `CMD [".venv/bin/uvicorn", …,
    "--proxy-headers", "--timeout-graceful-shutdown", "20"]`; decide
    worker count.
  - [ ] Move streamlit, pandas, plotly, python-dotenv and requests into a
    `frontend` optional dependency group (or a separate
    `frontend/pyproject.toml`); the API image installs without them.
  - [ ] Compose: drop `version:`, bind ports to `127.0.0.1`, Redis
    `--requirepass`, non-superuser app credentials (SEC-2), source bind
    mount only in `compose.override.yaml`, one start command shared with
    the Dockerfile.
- [ ] **PERF-3 — Cache resilience.** Cache get/set fail open (log and
  continue); `RATE_LIMIT_FAIL_OPEN` setting; normalised question in the key;
  configurable TTL; size cap (with SEC-5); hit/miss metric (with OPS-2).

## Phase 3 — Architecture, performance, code quality 🟡

- [ ] **ARCH-2 — Centralise config** (do first; it unblocks the rest of
  this phase). Everything into `Settings` (`REDIS_URL`, limits, TTLs, model
  names, `max_tokens`, timeouts); `env: Literal[...]`, `SecretStr`, DSN
  types; `get_settings()` with `lru_cache`; engine, Redis and LLM clients
  built in `lifespan`, not at import.
- [ ] **ARCH-1 — `QueryPipeline` service with DI.** Inject `LLMClient`,
  `SchemaProvider`, `SQLGuard`, `QueryExecutor` and `ResultCache` via
  `Depends`; thin route; tests use `app.dependency_overrides` instead of
  monkeypatching import paths.
- [ ] **ARCH-3 — Task-level LLM interface.** `generate_sql()` with
  structured output (`{sql, tables_used, assumptions}`) and `explain()`;
  per-task model and `max_tokens` (SQL generation well above 250); return
  `usage`; provider registry.
- [ ] **PERF-1 — Schema cache.** A TTL'd in-process and Redis cache of the
  rendered schema plus a fingerprint; cache lookup before introspection;
  fingerprint (not full text) in the response cache key.
- [ ] **PERF-2 — LLM client lifecycle and concurrency.** One client per
  process (from `lifespan`), `timeout≈20s`, `max_retries=2`; decide between
  async (`AsyncOpenAI` + async route ± `asyncpg`) and a sized threadpool,
  and write the decision down; optional `explain=false` request flag.
- [ ] **ARCH-4 — Lua loading.** `importlib.resources`, registered once at
  startup (pairs with PKG-1 package-data).
- [ ] **CQ-2 — Cleanup.** Delete `core/security.py` (or give it SEC-8's
  code); move `Product` to `tests/fixtures`; app version from
  `importlib.metadata`; drop `black`/`isort` (ruff covers both); remove
  the misplaced `noqa`; re-enable mypy `union-attr`/`arg-type` and fix
  what surfaces (`request.client` may be `None`).
- [ ] **CQ-3 — Streamlit fixes.** `auto_chart` picks the first categorical
  and first numeric column (fixes the `IndexError` on 2–3 column results);
  POST to `/api/query` without the slash; friendly error rendering; show
  `truncated` (SEC-5).
- [ ] **DX-1 — Makefile/README truth.** Fix `help`, add `check`, remove
  `release: … publish` and `tempTarget`, fix `venv_setup` and `clean`;
  add `.pre-commit-config.yaml` (ruff, ruff-format, mypy, end-of-file,
  detect-private-key) or remove the README claim; add the Roadmap section
  (pointing at this backlog) or drop it from the TOC; fill in the
  `pyproject` URLs.

## Phase 4 — Capabilities (needs a scope decision per item) 🟢

> Accuracy-first ordering. FEAT-2 and FEAT-3 move answer quality the
> most; FEAT-8 is how you prove it.

- [ ] **FEAT-8 — Evaluation harness** (build first so FEAT-2/3 are
  measurable): a golden question set against the seed DB, comparing
  result fingerprints rather than SQL text; deterministic with a mocked LLM
  in CI and real-model nightly.
- [ ] **FEAT-2 — Self-correction loop:** one bounded retry feeding the
  validator or DB error back to the model.
- [ ] **FEAT-3 — Semantic context:** `COMMENT ON` descriptions, FKs,
  low-cardinality sample values, a glossary, few-shot examples.
- [ ] **FEAT-1 — Query audit log** (separate writable store; the app's
  query role stays read-only).
- [ ] **FEAT-9 — Spend controls:** per-client token/cost budgets from
  `usage`, and a global circuit breaker.
- [ ] **FEAT-4 — Pagination** (`limit`/`cursor`) on top of SEC-5.
- [ ] **FEAT-5 — `EXPLAIN` cost gate.**

## Phase 5 — Platform hygiene and multi-client 🟢

- [ ] **FEAT-6 — API hygiene:** `/api/v1` prefix, `/docs` off or protected
  in prod, explicit CORS, security headers, a request body size limit,
  error schemas in OpenAPI.
- [ ] **FEAT-7 — Per-client scoping / RBAC:** client → allowed
  tables/schemas/row filters; cache keys scoped per client (depends on
  SEC-8 identity and SEC-7 allowlists).

---

## Next step

Start Phase 0 in this order: **OPS-1 + PKG-1** (one small PR that makes the
build and release artifacts trustworthy), then **SEC-2** (DB-level
read-only, the cheapest real control), then **SEC-3**, then **SEC-1** (the
largest item; land it with its adversarial corpus). Each is one PR with
its own tests.
