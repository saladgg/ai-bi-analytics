# AI BI Analytics — General Audit Backlog

Execution checklist for [`01_general_audit.md`](01_general_audit.md).
IDs match that file; evidence, file:line references and rationale live
there. Ship order is phase order. Items within a phase are independent
unless a dependency is noted.

> **Status (2026-11-28):** **Phases 0–3 shipped.** Phase 0 was released
> as v1.0.1, Phase 1 as v1.1.0 and Phase 2 as v1.2.0, all through the
> CI-gated pipeline. Phase 3 (architecture, performance, code quality) is
> on `feat/phase3-architecture`:
> - ARCH-2: every tunable is in `Settings`; the engine, Redis and LLM
>   clients are built in the lifespan and closed on shutdown;
> - ARCH-1: a `QueryPipeline` service assembled through `Depends`; tests
>   use `create_app(settings, resources_factory=…)` and
>   `dependency_overrides`, with no import-path patching left;
> - ARCH-3 and PERF-2: a provider registry, structured SQL output
>   (`assumptions` reach the client), a model and token cap per task, one
>   SDK client per process with a timeout and retries, and an `explain`
>   flag;
> - PERF-1: an in-process schema cache, with a fingerprint in the response
>   cache key;
> - CQ-2, CQ-3, DX-1: the Streamlit demo no longer crashes, mypy runs
>   without its disabled checks, and the Makefile no longer lists phantom
>   targets.
>
> The concurrency decision (stay synchronous, size the threadpool) is
> written up in [`docs/architecture.md`](../architecture.md). The
> `feat` commits make the next release minor (1.3.0).
>
> **Open decisions:** the broken v1.0.0 release assets (PKG-1) and
> bumping uv in both repos (OPS-4).
> **Next:** Phase 4 (capabilities), starting with FEAT-8 (evaluation
> harness), so FEAT-2 and FEAT-3 can be measured.

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

## Phase 2 — Operability 🟠 ✅ (uv bump open, shared with menu-yetu)

- [x] **OPS-2 — Wire observability for real.** *feat(ops): structured
  logs, OTLP traces and metrics across the query pipeline*
  - [x] JSON logging honouring `LOG_LEVEL`; `LOG_FORMAT` (JSON outside
    dev, text in dev). *Deviation:* a ~30-line in-repo `JsonFormatter`
    instead of `structlog`/`python-json-logger`, so no new dependency.
    The `DEBUG`/`OTEL_ENABLED` `os.getenv`s and the dead `"app"` logger
    are gone.
  - [x] Request-id middleware (shipped with SEC-4 in Phase 1).
    `ContextLogFilter` now adds `trace_id`/`span_id` from the active span,
    so no logging instrumentor is needed.
  - [x] OTel bootstrap in `lifespan` behind `OTEL_ENABLED`: OTLP over
    http/protobuf or grpc (standard `OTEL_*` variables), service resource
    attributes, FastAPI (health excluded), SQLAlchemy and Redis
    instrumentation. *HTTPX not applicable:* openai 3.x uses `httpx2`,
    which has no instrumentor, so the LLM call gets a manual span.
  - [x] Manual spans per pipeline stage; the LLM span uses GenAI semconv
    attributes, including input/output token usage.
  - [x] Metrics: `aibi.queries`, `aibi.cache.lookups`, `aibi.errors` (by
    code, which covers validator rejections), `aibi.rate_limit.denials`,
    `aibi.llm.duration`, `aibi.llm.tokens`, `aibi.query.rows`,
    `aibi.query.truncated`. *Not done:* LLM cost, which needs a price
    table per model; that belongs with FEAT-9 spend controls.
  - [x] Logging policy: SQL logged at INFO (generated, scope-bound);
    questions logged as sha256 prefix + length unless `LOG_QUESTIONS`.
  - [x] README observability section rewritten.
  - [x] *Found on the way:* `opentelemetry-instrumentation-sqlalchemy`
    0.66b2 (latest) declares `sqlalchemy < 2.1`, and Phase 1's relock
    moved to 2.1.9, so it silently instrumented nothing. Now forced with
    `skip_dep_check=True` (the cursor-execute hooks it uses are unchanged
    in 2.1), plus `greenlet`, which its setup imports and SQLAlchemy 2.1 no
    longer installs. A test asserts SQL spans appear. **Remove the
    override once upstream declares 2.1 support.**
  - [x] Verified against a real OpenTelemetry Collector (OTLP/HTTP): the
    request span, stage, LLM, Redis and SQL spans and the `aibi.*` metrics
    arrived, and a JSON log line's `trace_id` matched 27 exported spans.
- [ ] **OPS-3 — Health and lifecycle.** `/api/health/live` +
  `/api/health/ready` (DB `SELECT 1` + Redis `PING`, short timeouts,
  unauthenticated, rate-limit-exempt); dispose the engine and close Redis
  in `lifespan` teardown; Dockerfile `HEALTHCHECK`; compose
  `healthcheck` + `depends_on: condition: service_healthy`.
- [x] **OPS-4 — Container and compose hardening.** (Partly pulled into
  Phase 1 by the Trivy work: an apt upgrade layer, no pip, uv bind-mounted
  at build time only, no baked uv cache, a `.venv/bin/uvicorn` CMD.)
  *build(docker): non-root, digest-pinned, demo-free API image; hardened
  compose*
  - [x] Non-root `USER app` (uid/gid 10001; app code root-owned and
    read-only to it). Python and uv images pinned by digest.
    `--proxy-headers` and `--timeout-graceful-shutdown 20` on the CMD.
    Workers: uvicorn's `WEB_CONCURRENCY` (default 1), preferring one per
    container and scaling out. A separate builder stage isn't needed:
    uv and its cache stay out of the image.
  - [x] The project itself is installed in the image. *Found on the way:*
    OPS-2 reads the version from package metadata, which
    `--no-install-project` never installed, so **the container crashed on
    startup**; unit tests passed because the dev venv installs the
    project. Also fixed with a `0+unknown` fallback (folded into the OPS-2
    commit), and CI's Docker job now starts the image and waits for it to
    turn healthy as non-root.
  - [x] streamlit, pandas, plotly, python-dotenv and requests moved to a
    `frontend` dependency group (included in `dev`). Image size:
    906 MB → 343 MB.
  - [x] Compose:
    - `version:` dropped, ports bound to `127.0.0.1`, Redis
      `--requirepass` (healthcheck via `REDISCLI_AUTH`).
    - The API gets in-network `DATABASE_URL`/`REDIS_URL` (read-only
      role), so it no longer depends on `.env` having compose-specific
      values.
    - Start command matches the image's; `restart: unless-stopped`.
    - *Deviation:* the source bind mount and `--reload` went into a
      tracked `docker-compose.dev.yml` (`make docker-up-dev`; `:z` for
      SELinux) rather than `compose.override.yaml`, which `.gitignore`
      reserves for personal overrides.
  - [x] Verified the full stack: every service healthy, `/ready` OK,
    Redis refusing unauthenticated clients, Postgres showing the API only
    as `ai_bi_readonly`, and the dev overlay reloading on a source change.
    Trivy: 0 fixable CRITICAL/HIGH.
  - [ ] **uv 0.10.9 itself has CVEs** (bundled zip, quinn-proto,
    rustls-webpki crates; Trivy, 2026-11-26). It no longer ships in the
    image, but CI, the release job and developer machines still run it,
    and menu-yetu pins the same version. Bump both repos together.
- [x] **PERF-3 — Cache resilience.** *fix(ops): make the cache fail open
  and give the rate limiter an explicit Redis-outage policy*
  - [x] Cache reads and writes fail open: logged, counted as
    `aibi.cache.lookups{result=error}`, and the request proceeds uncached.
    Corrupt entries read as misses.
  - [x] `RATE_LIMIT_FAIL_OPEN`, default **false**: a Redis outage returns
    503, keeping LLM spend bounded. When true, requests are served
    unthrottled and counted in `aibi.rate_limit.fail_open`.
  - [x] Normalised question (casefold, collapsed whitespace) in the key,
    with a separator so question and schema can't collide by
    concatenation.
  - [x] `CACHE_TTL_SECONDS` (0 disables caching). The size cap shipped with
    SEC-5; hit/miss metrics with OPS-2.

## Phase 3 — Architecture, performance, code quality 🟡 ✅

- [x] **ARCH-2 — Centralise config.** — *feat(api): query pipeline …*
  - [x] Everything is in `Settings`, including new fields: `REDIS_URL`
    (`RedisDsn`), Redis/DB timeouts, pool size, per-task LLM models and
    token caps, the LLM timeout and retries, `SCHEMA_CACHE_TTL_SECONDS`
    and `WORKER_THREADS`. `env` is a `Literal` (case-insensitive), and
    `OPENAI_API_KEY` is a `SecretStr`. `DATABASE_URL` and `REDIS_URL` are
    kept out of `repr`.
  - [x] `get_settings()` is `lru_cache`d, and the module-level `settings`
    object is gone. Request code reads `app.state.settings` (set by
    `create_app(cfg)`).
  - [x] `resources.py` builds the engine, session factory, Redis client,
    LLM client and schema cache in the lifespan, and closes them on
    shutdown even when a later startup step fails. Nothing connects at
    import.
  - [x] New startup check: outside development, `OPENAI_API_KEY` is
    required. In development the app starts without one, and queries fail
    with `llm_unavailable`.
  - [x] *Deviation:* `DATABASE_URL` stays a `str` validated by
    SQLAlchemy, because pydantic's DSN types reject the `sqlite://` URLs
    the tests and the smoke check use. `REDIS_URL`'s default is now
    `localhost`; compose sets its own.
- [x] **ARCH-1 — `QueryPipeline` service with DI.** — *feat(api): query pipeline …*
  - [x] `services/pipeline.py` orchestrates scope → cache → SQL → guard →
    execute → explain, with the stage spans and metrics. `SQLGuard` and
    `QueryExecutor` wrap the existing functions with the row cap.
  - [x] The route is three dependencies and one call. Auth and the rate
    limit are a dependency (`rate_limited_client`), so they run before a
    session is opened.
  - [x] Tests build the app with fakes (`tests/fakes.py`: a fake
    provider and a stub OpenAI SDK), and swap pieces with
    `dependency_overrides`. No test patches an import path any more.
- [x] **ARCH-3 — Task-level LLM interface.** — *feat(api): query pipeline …*
  - [x] `ChatProvider` (one completion) with
    `register_provider`/`build_provider`. `LLMClient.generate_sql()` /
    `.explain()` each have their own model and `max_tokens` (SQL 1000, up
    from 250).
  - [x] SQL generation uses a strict JSON schema (`sql`, `tables_used`,
    `assumptions`). Assumptions are bounded and returned in the response;
    `tables_used` is logged. A non-JSON answer is used as SQL, since the
    guard validates it either way.
  - [x] Both tasks return `usage`, and the pipeline logs input and output
    tokens per query (FEAT-9 builds on this). Hitting `max_tokens` is
    logged.
- [x] **PERF-1 — Schema cache.** — *feat(api): query pipeline …*
  - [x] `SchemaProvider` caches the scope in process for
    `SCHEMA_CACHE_TTL_SECONDS` (0 disables it), and is invalidatable. A
    `QueryScope.fingerprint` (schema, columns and types, redactions) plus
    the SQL model and row cap form the response cache key, instead of the
    full schema text.
  - [x] *Deviation:* no Redis copy of the scope. It is the guard's table
    allowlist, and the guard must not trust what a Redis client can write.
    One introspection per process per TTL is cheap.
  - [x] Cached responses are re-validated against `QueryResponse`; a
    stale shape is a miss.
- [x] **PERF-2 — LLM client lifecycle and concurrency.** — *feat(api): query pipeline …*
  - [x] One OpenAI client per process, with `LLM_TIMEOUT_SECONDS=20` and
    `LLM_MAX_RETRIES=2`, closed on shutdown.
  - [x] Decision: stay synchronous on a sized threadpool
    (`WORKER_THREADS`). The reasoning, sizing and revisit triggers are in
    `docs/architecture.md`.
  - [x] `explain: false` skips the explanation call. A cached answer
    without an explanation is explained once and the entry upgraded.
  - [x] Verified against the real SDK and a stub server: per-task model,
    caps and strict schema on the wire, and a hung endpoint failing in
    about 2.5 s (1 s timeout, 1 retry) with `llm_unavailable`.
- [x] **ARCH-4 — Lua loading.** Shipped with SEC-3 in Phase 0: the script
  is read once via `importlib.resources` (cached) and packaged as
  package-data (PKG-1). `register_script` per call only hashes the source
  client-side, so there's no per-request I/O or round trip.
- [x] **CQ-2 — Cleanup.**
  - [x] `core/security.py` holds SEC-8's key store (Phase 1).
  - [x] `black`/`isort` dropped (Phase 1).
  - [x] The misplaced `noqa` went with SEC-4's route rewrite.
  - [x] `Product` moved to `tests/fixtures/models.py`; `db/models.py` is
    gone.
  - [x] App version from `importlib.metadata` (`telemetry.SERVICE_VERSION`,
    used by FastAPI and the OTel resource; OPS-2).
  - [x] mypy `union-attr`/`arg-type` re-enabled across the package, tests,
    frontend and examples; one test helper needed narrowing.
- [x] **CQ-3 — Streamlit fixes.** — *fix(frontend): …*
  - [x] `auto_chart` charts the first label column against the first
    numeric one, skipping id columns. It no longer crashes on 2–3 column
    results.
  - [x] POSTs to `/api/query`. `ApiError` carries the message, code and
    request id; 429s show `Retry-After`; validation errors are joined.
  - [x] Shows `truncated`, `assumptions` and the `explain` toggle.
  - [x] `tests/test_frontend.py` covers it.
- [x] **DX-1 — Makefile/README truth.** — *chore(dx): …*
  - [x] `.pre-commit-config.yaml` (Phase 1).
  - [x] `help` lists the real targets. Added `check`. Removed `release`
    and `tempTarget`. Fixed `venv_setup` (no background `&`/`source`)
    and `clean` (`.pyc` and `.coverage` are files; `.venv` is skipped).
  - [x] The README Roadmap is current. The `pyproject` URLs point at real
    pages, and `docs/architecture.md` is new.

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
