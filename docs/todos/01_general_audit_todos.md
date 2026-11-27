# AI BI Analytics — General Audit Backlog

Execution checklist for [`01_general_audit.md`](01_general_audit.md).
IDs match that file; evidence, file:line references and rationale live
there. Ship order is phase order. Items within a phase are independent
unless a dependency is noted.

> **Status (2026-11-26):** **Phases 0 and 1 shipped.** Phase 0 (SQL guard,
> read-only database, rate limiter, build and packaging) was released as
> v1.0.1 through the CI-gated pipeline. Phase 1 (typed errors, bounded
> results, prompt separation, query scope, per-client API keys, and CI
> that lints the whole repo, audits dependencies, scans the image and
> secrets, and runs the Postgres integration suite) is on
> `fix/phase1-request-path-and-ci`; its `feat(auth)` commit makes the next
> release a minor one. pip-audit and Trivy are clean.
>
> **Open decisions:** the broken v1.0.0 release assets (PKG-1), enabling
> Coveralls, and bumping uv in both repos (OPS-4). **Next:** Phase 2
> (OPS-2 observability, OPS-3 health and lifecycle, the rest of OPS-4,
> PERF-3).

---

## Phase 0 — Stop the bleeding (security + broken build) 🔴 ✅ (one decision open)

- [x] **SEC-2 — Enforce read-only at the database.** — *fix(security): enforce read-only query execution…*
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
- [x] **SEC-1 + CQ-1 — AST guard.** — *fix(security): replace substring SQL checks with an AST guard*
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
- [x] **SEC-3 — Make the rate limiter actually limit.** — *fix(security): make the rate limiter actually limit*
  - [x] Lua returns `{allowed, count, retry_after_ms}`, uses Redis `TIME`,
    ms scores, unique `now_ms:uuid` members, and `PEXPIRE`.
  - [x] Python branches on `allowed`. 429s carry `Retry-After` and
    `X-RateLimit-*`; successful `/api/query` responses carry
    `X-RateLimit-*`.
  - [x] Bucket = `request.client.host`; the raw `X-Forwarded-For` read is
    gone. Uvicorn's proxy-header handling is on by default and trusts
    `FORWARDED_ALLOW_IPS` (documented in `.env.example`), so no
    Dockerfile change was needed.
  - [x] Key on the client id. Shipped with SEC-8 in Phase 1.
  - [x] `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` settings. The
    Lua script loads via `importlib.resources` (fixes ARCH-4's CWD
    dependency).
  - [x] `fakeredis[lua]` runs the real script in tests; the route also
    exercises the real cache module now. Re-verified on `redis-server`.
- [x] **OPS-1 — Clean-clone build, no secrets in images.** — *fix(build): make clean-clone Docker builds…*
  - [x] `uv.lock` committed; `uv.lock` and `*.dockerignore` removed from
    `.gitignore`.
  - [x] `.dockerignore` added.
  - [x] Verified: a fresh `git clone` builds, and a canary `.env` is absent
    from the image.
- [x] **PKG-1 — Ship an importable wheel.** — *fix(build): make clean-clone Docker builds…*
  - [x] Package discovery and Lua package-data.
  - [x] `build` removed from runtime deps; `version = "1.0.0"` (PSR
    `version_toml` switched to number format `:nf` so it stays PEP 440).
    The `make build` target uses `uv build`.
  - [x] CI step "Wheel smoke test" installs the built wheel into a clean
    venv and imports `ai_bi_analytics.main`.
  - [ ] **Decision needed:** yank or annotate the broken v1.0.0 GitHub
    release assets. Merging this branch's `fix:` commits will cut v1.0.1
    with a working wheel.

## Phase 1 — Harden the request path and make CI a real gate 🟠 ✅

Shipped on `fix/phase1-request-path-and-ci` (one commit per item; commit
subjects in *italics*). The full suite is 287 tests, 18 of them against
Postgres 18, at 100% line and branch coverage.

- [x] **SEC-4 — Typed errors, no leakage.** *fix(security): return typed,
  client-safe errors with request ids*
  - [x] `core/errors.py`: `AppError` with status, a stable `code` and a
    client-safe message: `UnsafeSQLError` 422, `QueryExecutionError` 422
    (*added*: safe SQL that fails, e.g. a hallucinated column),
    `QueryTimeoutError` 504, `LLMUnavailableError` 502,
    `DependencyUnavailableError` 503.
  - [x] `db/errors.py` maps driver errors by Postgres SQLSTATE (57014,
    25006/42501, 08/53/57P, code-less psycopg2 connection failures).
    Handlers for `AppError`, `DBAPIError` and `RedisError` return
    `{detail, code, request_id}`; the route's blanket `except` is gone.
  - [x] *Added*: `RequestIdMiddleware` (pure ASGI, outermost) accepts a
    safe `X-Request-ID` or generates one, echoes it, puts it on every log
    line, and turns unhandled exceptions into a JSON 500 carrying it.
    This pulls the request-id part of OPS-2 forward.
- [x] **SEC-5 — Bound every query.** *fix(security): bound result sets,
  explanation input and cached responses*
  - [x] *Deviation:* instead of wrapping the SQL in a subquery, the guard
    rewrites the outermost `LIMIT` (handling `FETCH FIRST`, `LIMIT ALL`
    and expressions, keeping `OFFSET`) to `MAX_RESULT_ROWS + 1` unless the
    query asks for fewer, so ordering semantics are untouched. The
    executor's `fetchmany(cap + 1)` is the second bound.
  - [x] `QueryResult(rows, truncated)`; `row_count`/`truncated` on the
    response; `EXPLANATION_SAMPLE_ROWS` sample plus a row-count line in
    the prompt; `CACHE_MAX_BYTES`.
- [x] **SEC-6 — Prompt input bounds.** *fix(security): bound questions and
  separate prompt rules from untrusted text*
  - [x] A validator (not `Field` limits, so `MAX_QUESTION_LENGTH` is
    configurable) strips control chars and enforces 3..limit.
    `complete(prompt, system=)`; rules in the system message;
    `untrusted_block` tags the question, schema, SQL and rows, and removes
    any copy of the tag so the block can't be closed early.
- [x] **SEC-7 — Table/schema allowlist.** *fix(security): scope the LLM and
  the SQL guard to an explicit allowlist*
  - [x] *Deviation:* one `QUERYABLE_SCHEMA` (also the connection
    `search_path`), not `QUERYABLE_SCHEMAS`. A dedicated analytics schema
    covers the stated use case without multi-schema name resolution.
  - [x] `QUERYABLE_TABLES` (views included); the app refuses to start
    without it outside dev. `REDACTED_COLUMNS` (`table.column` or bare
    `column`). One `QueryScope` feeds both the prompt and the guard.
  - [x] The guard rejects redacted columns, `SELECT *` other than
    `COUNT(*)`, and whole-row references on restricted tables
    (conservative). `readonly_role.sql` takes a `schema` variable and
    documents column-level grants. Postgres integration proves
    `search_path` resolution and column privileges.
- [x] **SEC-8 — API-key auth.** *feat(auth): per-client hashed API keys
  with constant-time lookup* (the `feat` makes the next release minor)
  - [x] `APIKeyHeader(auto_error=False)`; missing or invalid → 401 with
    `WWW-Authenticate: APIKey` (test pinned).
  - [x] `API_KEYS=client_id:sha256` (hashes only; rotation = two entries);
    `ApiKeyStore` compares every entry with `hmac.compare_digest`; returns
    a `Principal`. The legacy `API_KEY` still works as client `default`.
  - [x] Startup validation outside dev: ≥ 32 chars, not a placeholder.
  - [x] Removed the API-key print from `frontend/api.py`.
  - [x] *Added*: `make api-key CLIENT=<id>` generates a key and its entry.
  - [x] The rate limiter keys on `client:<id>` (closes the SEC-3 leftover).
- [x] **CI-1 — CI gates.**
  - [x] Trigger on `pull_request` + `push: main`.
  - [x] CI runs a check-only `make format-check` instead of `make format`.
  - [x] ruff (format + lint) and mypy cover `ai_bi_analytics`, `tests`,
    `frontend` and `example`. *ci: lint, format-check and type-check the
    whole repo; add bandit rules*
  - [x] `--cov-branch --cov-fail-under=100`: line and branch coverage
    gated at 100%.
  - [x] Coverage uploaded to Coveralls (non-blocking). **Needs the repo
    enabled on coveralls.io** for the badge to show data.
  - [x] `make audit` (pip-audit via OSV) in CI. The first run found 248
    CVEs in 13 packages; relocking (plus unpinning `streamlit==1.55.0`,
    which held pillow back) cleared them all. *build(deps): clear all known
    dependency vulnerabilities and add make audit*
  - [x] SAST: ruff `S` (flake8-bandit) rules instead of a separate bandit
    run.
  - [x] Dependabot for uv, github-actions and docker.
  - [x] Docker build + Trivy job. Trivy found fixable HIGH/CRITICAL CVEs
    in Debian (libzstd1), in the base image's pip, and in the uv binary,
    plus 536 MB of uv cache baked into the image. All fixed; the image
    went from 1.68 GB to 906 MB. *build(docker): ship an image with no
    known fixable HIGH/CRITICAL CVEs*
  - [x] *Added*: gitleaks secret scan over full history (clean).
  - [x] Release only after CI is green (Phase 0).
  - [x] All `ci.yaml` actions SHA-pinned; the workflow token is
    `contents: read`.
- [x] **TEST-1 — Tests that would have caught Phase 0.**
  - [x] `fakeredis[lua]` for the limiter and cache (Phase 0, SEC-3).
  - [x] Postgres 18 service container in CI, provisioned by the shipped
    `readonly_role.sql`; the integration suite runs on every PR, and the
    step fails if it skips.
  - [x] Route tests use the real `services/cache.py` (Phase 0, SEC-3).
  - [x] Error-path tests for every SEC-4 status/code (`test_errors.py`);
    prompt-content tests (`test_prompts.py`); `schema_loader` output
    tests (`test_query_scope.py`).

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
- [ ] **OPS-4 — Container and compose hardening.** (Partly pulled into
  Phase 1 by the Trivy work: an apt upgrade layer, no pip, uv
  bind-mounted at build time only, no baked uv cache, a
  `.venv/bin/uvicorn` CMD, and the compose `/app/.venv` volume.)
  - [ ] Non-root `USER`, base pinned by digest, add `--proxy-headers`
    and `--timeout-graceful-shutdown 20` to the CMD; decide worker count.
    (A separate builder stage is no longer needed for size: uv and its
    cache already stay out of the image.)
  - [ ] **uv 0.10.9 itself has CVEs** (bundled zip, quinn-proto,
    rustls-webpki crates; Trivy, 2026-11-26). It no longer ships in the
    image, but CI, the release job and developer machines still run it,
    and menu-yetu pins the same version. Bump both repos together.
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
- [x] **ARCH-4 — Lua loading.** Shipped with SEC-3 in Phase 0: the script
  is read once via `importlib.resources` (cached) and packaged as
  package-data (PKG-1). `register_script` per call only hashes the source
  client-side, so there's no per-request I/O or round trip.
- [ ] **CQ-2 — Cleanup.**
  - [x] `core/security.py` holds SEC-8's key store (Phase 1).
  - [x] `black`/`isort` dropped (Phase 1).
  - [x] The misplaced `noqa` went with SEC-4's route rewrite.
  - [ ] Move `Product` to `tests/fixtures`.
  - [ ] App version from `importlib.metadata` (FastAPI still reports
    `0.1.0`).
  - [ ] Re-enable mypy `union-attr`/`arg-type` and fix what surfaces.
- [ ] **CQ-3 — Streamlit fixes.** `auto_chart` picks the first categorical
  and first numeric column (fixes the `IndexError` on 2–3 column results);
  POST to `/api/query` without the slash; friendly error rendering; show
  `truncated` (SEC-5).
- [ ] **DX-1 — Makefile/README truth.** *Partly done:* `.pre-commit-config.yaml`
  now exists (commit: hygiene, private keys, gitleaks, actionlint, ruff,
  mypy; push: `make audit` and the full suite at 100% coverage, run with
  `SKIP_DOTENV=1`), with `make hooks-install` / `make hooks-run`. Both a
  bad commit and a coverage-failing push were shown to be blocked.** Fix `help`, add `check`, remove
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
