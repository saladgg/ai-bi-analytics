# AI BI Analytics — General Audit Backlog

Execution checklist for [`01_general_audit.md`](01_general_audit.md).
IDs match that file; evidence, file:line references and rationale live
there. Ship order is phase order. Items within a phase are independent
unless a dependency is noted.

> **Status (2026-11-26):** **Phase 0 shipped** on
> `fix/phase0-security-build-hardening` (one commit per finding: OPS-1 +
> PKG-1, SEC-2, SEC-3, SEC-1 + CQ-1). Every fix was re-verified against
> the real component, not just the unit suite:
> - the audit's validator probe now rejects every bypass and accepts
>   every false positive;
> - 20 burst requests against `redis-server` give 5 allowed and 15
>   blocked, with spoofed `X-Forwarded-For` ignored;
> - the new Postgres 18 integration suite (15 tests) passes, refusing
>   writes, a smuggled `COMMIT`, writable CTEs, `GRANT`, `pg_read_file`
>   and a `pg_sleep` past the timeout;
> - a clean clone builds in Docker with a canary `.env` absent from the
>   image;
> - the wheel installs and imports from a fresh venv.
>
> Suite: 131 passed + 15 integration (skipped unless `TEST_POSTGRES_*_URL`
> are set), 100% line coverage. **Still open from Phase 0:** the release
> decision on the broken v1.0.0 assets (PKG-1) and keying the limiter on
> client identity (needs SEC-8). The integration suite isn't wired into
> CI yet; that is TEST-1 in Phase 1.
> Phases 1–3 are next. Phases 4–5 are product-shaped and need a scope
> decision before anyone builds them.

---

## Phase 0 — Stop the bleeding (security + broken build) 🔴 ✅ (one decision open)

- [x] **SEC-2 — Enforce read-only at the database.** `2c6eb2e`
  - [x] `db/session.py` `build_engine_kwargs`: Postgres connections start
    with `default_transaction_read_only=on`, `statement_timeout` and
    `idle_in_transaction_session_timeout` (new settings
    `DB_STATEMENT_TIMEOUT_MS` / `DB_IDLE_IN_TRANSACTION_TIMEOUT_MS`).
    Non-Postgres URLs are untouched.
  - [x] `query_executor.py`: on Postgres, `SET TRANSACTION READ ONLY` as
    the first statement and a `rollback()` in `finally`.
  - [x] `example/readonly_role.sql` (idempotent, psql variables): a
    `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    NOINHERIT` role. The read-only default and timeouts are also pinned
    **on the role**, so they hold behind PgBouncer. Compose runs it on
    first start (`example/initdb/10_readonly_role.sh`), and
    `db_user_setup.py` now creates an owner and a read-only role with
    psql variables instead of f-string SQL. *Deviation:* `SELECT` is
    granted schema-wide on `public` (plus default privileges for new
    tables), not per table. Narrowing comes with SEC-7's allowlist.
  - [x] `assert_database_role_is_safe` in `lifespan` refuses to boot outside
    development on `SUPERUSER`, `CREATEROLE`, `CREATEDB` or `BYPASSRLS`,
    and fails closed when the role can't be verified. In development it
    only warns.
  - [x] `.env.example`, README, and `example/README.md` (two-role model,
    plus manual role creation for pre-existing compose volumes).
  - [x] `tests/integration/test_postgres_readonly.py`, verified on
    Postgres 18.
- [x] **SEC-1 + CQ-1 — AST guard.** `d0b3557`
  - [x] `sqlglot` postgres dialect; exactly one statement; root is `Select`
    or a set operation (`WITH` parses as a `Select` with CTEs). Empty and
    comment-only trailers (`;;`, `; -- done`) don't count as statements.
  - [x] Forbidden-node scan of the whole tree (DML, DDL, `COPY`, `GRANT`,
    `SET`, transactions, `Command`, `SELECT INTO`, `FOR UPDATE/SHARE`, …).
  - [x] Reflected-table allowlist (`schema_loader.load_table_names`); CTE
    names allowed; quoted identifiers stay case-sensitive; non-default
    schemas, cross-database references and system catalogs are rejected
    even without an allowlist.
  - [x] Function **denylist** (`pg_*`, `lo_*`, `dblink*`, `*_to_xml`,
    `set_config`, `current_setting`, sequence functions, `inet_*`, …).
    An allowlist was judged too likely to reject legitimate model output
    for now; the read-only role is the backstop.
  - [x] Strips markdown code fences.
  - [x] **Added beyond the plan:** the route executes SQL regenerated from
    the validated AST (comments dropped), not the raw model output.
    Integration tests confirm it keeps its meaning on Postgres.
  - [x] Corpus in `tests/test_sql_validator.py`: every verified bypass,
    nested and CTE variants, catalogs, unknown tables, and false-positive
    regressions.
- [x] **SEC-3 — Make the rate limiter actually limit.** `c33e2cf`
  - [x] Lua returns `{allowed, count, retry_after_ms}`, uses Redis `TIME`,
    ms scores, unique `now_ms:uuid` members, and `PEXPIRE`.
  - [x] Python branches on `allowed`. 429s carry `Retry-After` and
    `X-RateLimit-*`; successful `/api/query` responses carry
    `X-RateLimit-*`.
  - [x] Bucket = `request.client.host`; the raw `X-Forwarded-For` read is
    gone. Uvicorn's proxy-header handling is on by default and trusts
    `FORWARDED_ALLOW_IPS` (documented in `.env.example`), so no
    Dockerfile change was needed.
  - [ ] Key on the client id. Blocked on SEC-8 (Phase 1).
  - [x] `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` settings. The
    Lua script loads via `importlib.resources` (fixes ARCH-4's CWD
    dependency).
  - [x] `fakeredis[lua]` runs the real script in tests; the route also
    exercises the real cache module now. Re-verified on `redis-server`.
- [x] **OPS-1 — Clean-clone build, no secrets in images.** `02b54a6`
  - [x] `uv.lock` committed; `uv.lock` and `*.dockerignore` removed from
    `.gitignore`.
  - [x] `.dockerignore` added.
  - [x] Verified: a fresh `git clone` builds, and a canary `.env` is absent
    from the image.
- [x] **PKG-1 — Ship an importable wheel.** `02b54a6`
  - [x] Package discovery and Lua package-data.
  - [x] `build` removed from runtime deps; `version = "1.0.0"` (PSR
    `version_toml` switched to number format `:nf` so it stays PEP 440).
    The `make build` target uses `uv build`.
  - [x] CI step "Wheel smoke test" installs the built wheel into a clean
    venv and imports `ai_bi_analytics.main`.
  - [ ] **Decision needed:** yank or annotate the broken v1.0.0 GitHub
    release assets. Merging this branch's `fix:` commits will cut v1.0.1
    with a working wheel.

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
