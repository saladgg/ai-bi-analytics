# CHANGELOG


## v1.3.0 (2026-11-28)

### Features

- **api**: Query pipeline with injected clients, structured LLM output and a schema cache
  ([#12](https://github.com/saladgg/ai-bi-analytics/pull/12),
  [`22c28ba`](https://github.com/saladgg/ai-bi-analytics/commit/22c28ba56c9d8102ef05d84a148995cbe706b51b))

* feat(api): query pipeline with injected clients, structured LLM output and a schema cache

Phase 3 of the general audit (ARCH-1, ARCH-2, ARCH-3, PERF-1, PERF-2, CQ-2).

- Settings: every tunable is a field (Redis URL and timeouts, DB connect timeout and pool size,
  per-task LLM model and token cap, LLM timeout and retries, schema-cache TTL, worker threads). ENV
  is a Literal, OPENAI_API_KEY a SecretStr, and both URLs stay out of repr. get_settings() replaces
  the import-time singleton. - resources.py builds the engine, Redis client, LLM client and schema
  cache in the lifespan and closes them on shutdown, even if a later startup step fails. Nothing
  connects at import. - QueryPipeline (services/pipeline.py) owns the NL -> SQL -> result flow. The
  route takes it, the session and the rate-limited caller as dependencies. Auth and the rate limit
  run before a session opens. - LLM layer: a ChatProvider registry, and an LLMClient with
  generate_sql() (strict JSON schema: sql, tables_used, assumptions) and explain(), each with its
  own model and token cap. Both return usage, which is logged per query. One SDK client per process,
  with a timeout and bounded retries. - The response gains `assumptions`. The request gains
  `explain` (false skips the second LLM call). A cached answer stored without an explanation is
  explained once and the entry upgraded. - SchemaProvider caches the query scope in process for
  SCHEMA_CACHE_TTL_SECONDS. The scope's fingerprint, the SQL model and the row cap form the response
  cache key. Cached responses are re-validated, and a stale shape is a miss. - Outside development,
  startup now requires OPENAI_API_KEY. - Tests build the app with fakes through create_app(settings,
  resources_factory=...) and use dependency_overrides. Nothing patches import paths. The Product
  model moved to tests/fixtures.

* fix(frontend): stop the demo crashing on small results and show API errors clearly

Audit CQ-3.

- auto_chart read columns 2 and 3 and raised IndexError on 2-3 column results. It now charts the
  first label column against the first numeric one, skips id columns, and draws nothing when no pair
  fits. - The demo POSTs to /api/query; the trailing slash forced a redirect. - ApiError carries the
  API's message, code and request id. 429s mention Retry-After, and validation errors are joined
  into one message. - The page flags truncated results and the model's assumptions, and has an
  "Explain the result" toggle that maps to the new `explain` flag.

* chore(dx): re-enable mypy checks, fix Makefile targets and project URLs

Audit CQ-2 and DX-1.

- mypy runs with union-attr and arg-type enabled again. - `make help` lists the targets that exist.
  Added `make check` (what CI's test job runs). - Removed the `release` target (it depended on a
  missing `publish`) and `tempTarget`. - Fixed `venv_setup`, which backgrounded uv and sourced the
  venv in a throwaway shell. - Fixed `clean`, which treated .pyc and .coverage as directories. It
  now also skips .venv. - The pyproject URLs point at real pages.

* docs: architecture notes, configuration reference and Phase 3 status

- docs/architecture.md covers: - the request path and how clients are wired and injected; - the LLM
  layer and how to add a provider; - both caches and why the scope isn't shared through Redis; - the
  PERF-2 decision to stay synchronous on a sized threadpool. - README: the pipeline diagram, the
  task-level LLM interface, the schema cache, the explain flag and assumptions, and the new
  settings. - .env.example lists the new settings. - Backlog: Phase 3 ticked, with its deviations.

* fix(config): don't refuse to start on .env entries the app doesn't read

pydantic-settings forbids unknown .env keys by default. .env.example has carried REDIS_PASSWORD
  (read by docker compose) since v1.2.0, so `cp .env.example .env` produced a config the app refused
  to load. The same applied to FORWARDED_ALLOW_IPS (uvicorn) and the OTEL_EXPORTER_* variables once
  uncommented. Unknown entries are now ignored. Environment variables were never affected.

Tests load .env.example itself and a .env with those extras.


## v1.2.0 (2026-11-27)

### Features

- **ops**: Health checks, OTLP observability, cache resilience and a hardened container
  ([#11](https://github.com/saladgg/ai-bi-analytics/pull/11),
  [`e98c6c8`](https://github.com/saladgg/ai-bi-analytics/commit/e98c6c8ca9b6df05d06511c36398277951774e81))

* docs(audit): mark ARCH-4 done and split CQ-2 into done and open parts

ARCH-4 shipped with SEC-3 in Phase 0 but was still unticked. CQ-2 was partly done in Phase 1
  (security.py holds the key store, black/isort dropped, the stray noqa removed); the remaining
  sub-items are listed.

* feat(ops): liveness and readiness endpoints, connect timeouts, clean shutdown

OPS-3: /api/health always returned ok, even with Postgres or Redis down, and nothing bounded a
  connection attempt, so a blackholed dependency hung requests on the OS TCP timeout.

- /api/health/live (process up; /api/health kept as an alias) and /api/health/ready (SELECT 1 +
  PING; 503 naming the failed check, details only in the log). Both unauthenticated and outside the
  rate limiter. - Postgres connect_timeout 5 s; Redis socket and connect timeouts 2 s and a periodic
  health check (build_redis_client) - lifespan disposes the DB pool and closes Redis on shutdown -
  Docker HEALTHCHECK on /live using the image's Python (slim has no curl) - compose: pg_isready and
  redis-cli healthchecks; the API waits for service_healthy

Verified in the built image: Docker reports healthy, /ready returns 503 naming redis promptly when
  Redis is absent, and docker stop runs the cleanup.

* feat(ops): structured logs, OTLP traces and metrics across the query pipeline

OPS-2: observability was advertised but not wired. No tracer provider or exporter existed, trace ids
  in logs were always N/A, extra={...} fields were silently dropped by the text formatter, LOG_LEVEL
  was ignored, and there were no metrics.

Logs - LOG_LEVEL applies to root and uvicorn; LOG_FORMAT is json outside development and text in it
  (small in-repo JsonFormatter: one object per line with extras as keys) - ContextLogFilter adds
  trace_id/span_id from the active span next to request_id - questions are logged as a sha256 prefix
  + length unless LOG_QUESTIONS

Traces and metrics (OTEL_ENABLED; standard OTEL_EXPORTER_OTLP_* config, http/protobuf or grpc) -
  tracer and meter providers with service.name/version/environment - FastAPI (health excluded),
  SQLAlchemy and Redis instrumentation - a span per pipeline stage, and a manual LLM span with GenAI
  attributes and token usage (openai 3.x's httpx2 has no instrumentor) - aibi.queries,
  cache.lookups, errors{code}, rate_limit.denials, llm.duration, llm.tokens, query.rows,
  query.truncated - the FastAPI and OTel version comes from package metadata (was 0.1.0)

opentelemetry-instrumentation-sqlalchemy 0.66b2 (latest) declares sqlalchemy < 2.1 and silently
  skipped our 2.1.9. It is instrumented with skip_dep_check (its cursor-execute hooks are unchanged
  in 2.1) plus greenlet, which its setup imports. A test asserts SQL spans exist.

Verified against a real OpenTelemetry Collector: request, stage, LLM, Redis and SQL spans and the
  aibi.* metrics arrived, and a JSON log line's trace_id matched the exported trace.

* fix(ops): make the cache fail open and give the rate limiter an explicit Redis-outage policy

PERF-3: Redis was a hard dependency. Any error in the cache or the limiter failed the whole request,
  even though the cache is only an optimisation. Cache keys were also exact-text, so 'Top 3
  products' and 'top 3 products' never shared an entry.

- cache reads and writes fail open (logged, counted as aibi.cache.lookups{result=error}); corrupt
  entries read as misses. The hit/miss/error metric moved into the cache module, which is the only
  place that can tell them apart. - RATE_LIMIT_FAIL_OPEN, default false: a limiter outage returns
  503 so LLM spend stays bounded; true serves unthrottled and counts aibi.rate_limit.fail_open -
  keys use the case- and whitespace-normalised question plus a separator before the schema text -
  CACHE_TTL_SECONDS (default 300; 0 disables caching)

Tests cover each Redis failure mode, both limiter policies, and a full query succeeding with the
  cache down.

* fix(api): keep rate-limit headers on error responses

The error handlers (SEC-4) build a fresh JSONResponse, which dropped the X-RateLimit-Limit/Remaining
  headers the route had already set. Clients saw them only on success. Found while exercising the
  full compose stack: a 502 from an unreachable LLM had no rate-limit headers.

The route keeps its rate-limit headers on request.state, and the AppError, DBAPIError and RedisError
  handlers copy them onto the error response.

* build(docker): non-root, digest-pinned, demo-free API image; hardened compose

OPS-4 (remainder): - the image runs as USER app (uid/gid 10001); app code is root-owned and
  read-only to it - python:3.14-slim and the build-time uv image are pinned by digest - CMD adds
  --proxy-headers and --timeout-graceful-shutdown 20; worker count via uvicorn's WEB_CONCURRENCY
  (default 1, scale by containers) - HEALTHCHECK --start-interval=2s, so a fresh container turns
  healthy in seconds rather than after the first 30 s interval - the project itself is installed
  (non-editable). OPS-2 reads the version from package metadata, and --no-install-project never
  installed it, so the container crashed at startup while unit tests passed. CI's Docker job now
  starts the image and requires it to turn healthy as uid 10001. - streamlit, pandas, plotly,
  python-dotenv and requests moved to a 'frontend' dependency group (included in dev): 906 MB -> 343
  MB

Compose: - dropped the obsolete version key; ports bound to 127.0.0.1 - Redis requires a password
  (REDIS_PASSWORD; healthcheck via REDISCLI_AUTH) - the API gets in-network DATABASE_URL (read-only
  role) and REDIS_URL, and its start command matches the image's - restart: unless-stopped - source
  bind mount + --reload moved to docker-compose.dev.yml (make docker-up-dev)

Verified with the full stack: every service healthy, /ready ok, Redis refusing unauthenticated
  clients, Postgres showing the API only as ai_bi_readonly, the dev overlay reloading on change;
  Trivy clean.

* docs: record Phase 2 and update the roadmap

The backlog status stamp, the docs/todos index and the README roadmap now reflect Phase 2 (OPS-2,
  OPS-3, OPS-4, PERF-3), the two bugs the full-stack run surfaced, and Phase 3 as next.


## v1.1.0 (2026-11-26)

### Features

- **security**: Harden the request path, add per-client API keys and CI/local gates
  ([#7](https://github.com/saladgg/ai-bi-analytics/pull/7),
  [`e14ca72`](https://github.com/saladgg/ai-bi-analytics/commit/e14ca72c6e34d2caf01e122d9d9c77feba838c1e))

* chore(license): license the project under MIT

Matches the py-authz licensing: an MIT LICENSE file and a README footer linking it. pyproject uses
  the PEP 639 SPDX form (license = "MIT", license-files) rather than the deprecated { text = ... }
  table, so the wheel carries License-Expression: MIT and ships the LICENSE file.

* fix(security): return typed, client-safe errors with request ids

SEC-4: the route wrapped the whole pipeline in 'except Exception' and returned str(exc) as a 400.
  Database hosts, SQL text and provider error details reached clients, and outages were reported as
  client errors.

- core/errors.py: AppError hierarchy carrying status, a stable code and a client-safe message
  (UnsafeSQLError 422, QueryExecutionError 422, QueryTimeoutError 504, LLMUnavailableError 502,
  DependencyUnavailableError 503) - db/errors.py maps driver errors by Postgres SQLSTATE: 57014
  timeout, 25006/42501 read-only policy, 08/53/57P unavailable, and code-less psycopg2 connection
  failures - handlers for AppError, DBAPIError and RedisError log the detail and return {detail,
  code, request_id}; the route's blanket try/except is gone - the OpenAI client wraps provider
  errors and empty completions in LLMUnavailableError - RequestIdMiddleware (pure ASGI, outermost)
  accepts a safe X-Request-ID or generates one, echoes it, adds it to every log line, and turns
  unhandled exceptions into a generic JSON 500 that carries it

Tests assert each status/code mapping, that secrets in exception text never appear in responses but
  do appear in logs, and the request-id edge cases.

* fix(security): bound questions and separate prompt rules from untrusted text

SEC-6: the question was an unbounded str (a megabyte question was forwarded to the LLM), and both
  prompts were one f-string mixing rules, schema, the question and, for explanations, raw database
  rows. That gave attackers a second injection channel through any writable column.

- QueryRequest strips control characters and whitespace and enforces 3..MAX_QUESTION_LENGTH (default
  500) characters; violations are a 422 before any LLM call - BaseLLMClient.complete takes an
  optional system message; rules now go there and untrusted content goes in the user message -
  services/prompting.untrusted_block wraps the question, schema, SQL and result rows in named tags
  and removes any copy of the tag from the content, so it can't close the block early - both rule
  sets tell the model tagged content is data, never instructions; result rows are sent as JSON
  (default=str for Decimal and dates)

This is about cost and answer quality. The SQL guard and the read-only role remain the security
  boundary.

* fix(security): scope the LLM and the SQL guard to an explicit allowlist

SEC-7: every table in the default schema was sent to a third-party LLM and was queryable. Pointed at
  an operational database, users, sessions and payments tables were disclosed and readable.

- QUERYABLE_SCHEMA (default public; also the connection search_path, validated as a plain
  identifier), QUERYABLE_TABLES and REDACTED_COLUMNS (table.column or bare column) settings -
  outside ENV=development the app refuses to start without QUERYABLE_TABLES (new
  core/startup_checks.py, run in lifespan) - schema_loader builds one QueryScope (tables and views,
  allowlist applied, redacted columns removed). It feeds both the prompt and the guard, so the model
  is never shown anything it can't query, and the reverse. This also drops the second introspection
  pass per request. - the guard accepts the configured schema and rejects redacted columns, any
  SELECT * other than COUNT(*), and whole-row references (row_to_json(u)) on restricted tables. It
  is deliberately conservative; database column privileges are the authoritative layer. -
  readonly_role.sql takes an optional schema variable (default public), sets the role's search_path,
  and documents column-level grants

Integration tests on Postgres 18 cover a dedicated schema with a view resolving through search_path,
  and a column-level grant making Postgres refuse both the hidden column and SELECT *.

* fix(security): bound result sets, explanation input and cached responses

SEC-5: queries had no row cap. fetchall() materialised the whole result, which then went into the
  explanation prompt, into Redis and back to the client. One broad question or cartesian join could
  exhaust memory and blow up LLM cost.

- the guard rewrites the outermost LIMIT to MAX_RESULT_ROWS + 1 (default 1000) unless the query
  already asks for fewer; OFFSET is kept and FETCH FIRST, LIMIT ALL and expression limits are
  handled, so Postgres itself stops at the cap - the executor uses fetchmany(cap + 1) as a second
  bound and returns QueryResult(rows, truncated); responses gain row_count and truncated - the
  explanation prompt gets at most EXPLANATION_SAMPLE_ROWS (default 20) plus a row-count line, and
  the rules tell the model not to present a sample as the full answer - responses above
  CACHE_MAX_BYTES (default 512000) are not cached

README documents the bounds, the new response fields, and the error contract from SEC-4. Verified on
  Postgres 18: the capped canonical SQL truncates and reports it.

* feat(auth): per-client hashed API keys with constant-time lookup

SEC-8: one shared static key compared with !=, no rotation path, no caller identity, 422 on a
  missing header, nothing stopping the change-me placeholder in production, and the Streamlit demo
  printed the key to stdout on start.

- API_KEYS=client_id:sha256(key),... : the server stores only hashes, each client has an identity,
  and rotation is two entries side by side (validated on load; duplicate client ids rejected) -
  ApiKeyStore compares against every entry with hmac.compare_digest without stopping early -
  APIKeyHeader security scheme (shown in OpenAPI); missing or unknown keys get 401 with
  WWW-Authenticate: APIKey; the dependency returns a Principal - the legacy API_KEY still works as
  client 'default' (now a SecretStr); outside development it must be 32+ chars and not a placeholder
  (new startup check) - the rate limiter keys on client:<id> for authenticated requests, closing the
  SEC-3 follow-up; logs carry client_id - 'make api-key CLIENT=<id>' / 'python -m
  ai_bi_analytics.core.security' generates a key and its API_KEYS entry - removed the API-key print
  from frontend/api.py

Tests isolate Settings from the process env and the local .env file.

* ci: lint, format-check and type-check the whole repo; add bandit rules

CI-1: ruff and mypy only covered ai_bi_analytics/, so tests, the Streamlit demo and the bootstrap
  scripts drifted (unformatted files, unsorted imports, a deprecated declarative_base, a type
  error).

- make format, format-check and lint cover ai_bi_analytics, tests, frontend and example; mypy's file
  list lives in pyproject - ruff 'S' (flake8-bandit) rules are on everywhere, with per-file ignores
  for test asserts and fixture SQL and for psql/subprocess and random use in example/ - the one
  package assert (row-cap type narrowing) is an explicit check, since python -O strips asserts -
  example models use SQLAlchemy 2 DeclarativeBase; long lines split

* build(deps): clear all known dependency vulnerabilities and add make audit

CI-1: nothing audited dependencies. pip-audit (OSV) found 248 known

vulnerabilities in 13 packages: in the API's runtime path (starlette, urllib3, anyio, idna, certifi,
  pydantic-settings, opentelemetry-api), in the Streamlit demo's tree (pillow, gitpython, tornado),
  and in dev tools (virtualenv, filelock, black).

- relocked with upgrades within the declared constraints. uv.lock had been frozen since it was first
  committed. - streamlit was pinned ==1.55.0, which held pillow below the fixed 13.x; now >=1.55.0,
  resolving to 1.67.0 (verified with Streamlit's AppTest) - openai's unbounded floor resolved to
  3.x; the chat.completions, APIError and APIConnectionError surfaces this code uses are unchanged,
  and the floor is now the tested >=3.60.0 - dropped black and isort; ruff already formats and sorts
  imports - added pip-audit (dev) and 'make audit' - frontend/api.py fails clearly instead of
  sending x-api-key: None (caught by the newer requests stubs)

pip-audit now reports no known vulnerabilities; 287 tests pass, including Postgres integration.

* build(docker): ship an image with no known fixable HIGH/CRITICAL CVEs

Trivy 0.72.0 (CRITICAL/HIGH, fixable only) failed the image on: - libzstd1: Debian fix released
  after the base image was built - msgpack and urllib3 vendored in the base image's system pip,
  which the app never uses - zip, quinn-proto and rustls-webpki inside the uv 0.10.9 binary

It also found 536 MB of uv download cache baked into a layer.

- apt-get upgrade layer, keyed on an APT_CACHE_BUST build arg so CI's layer cache can't pin stale
  packages - system pip uninstalled - uv bind-mounted from its pinned official image for the 'uv
  sync' step only, so it never ships; UV_NO_CACHE so no cache is baked in - CMD runs
  .venv/bin/uvicorn instead of 'uv run' (no runtime re-sync or download; pulled forward from OPS-4)
  - compose uses the same entrypoint and keeps the image's venv behind an anonymous /app/.venv
  volume, which the source bind mount used to hide

Image 1.68 GB -> 906 MB. Trivy exits 0, the container serves /api/health, and the compose-style
  bind-mount startup works.

* ci: Postgres integration, audit, image scan, secret scan, SHA-pinned actions

CI-1 / TEST-1: - lint-test: a Postgres 18 service; the shipped readonly_role.sql creates the
  read-only role, so the integration suite (read-only enforcement, guard output, query scope, row
  cap) runs on every PR, and the step fails if it silently skips - 'make audit' (pip-audit via OSV)
  gates on known dependency CVEs - coverage.xml goes to Coveralls (non-blocking; the 100% gate is
  the real check) - docker-build: builds from a clean checkout with a daily apt cache-bust and scans
  with Trivy (fixable CRITICAL/HIGH fail the build) - secret-scan: gitleaks 8.30.1 over full history
  (clean today) - every action SHA-pinned; workflow token is contents: read - Dependabot for uv,
  GitHub Actions and Docker, weekly, minor/patch grouped

release.yaml already waits for all of CI to pass on main.

* docs: record Phase 1 and document the new workflow and CI gates

The 01 backlog ticks every Phase 1 item and records: - deviations: a LIMIT rewrite instead of a
  subquery wrapper, and a single QUERYABLE_SCHEMA - additions: QueryExecutionError, request ids,
  make api-key, gitleaks - the OPS-4 parts pulled forward by the Trivy work - uv 0.10.9's own CVEs,
  to fix together with menu-yetu - open decisions: v1.0.0 assets, Coveralls, the uv bump

README lists the new make targets, what the integration suite and CI cover, Dependabot, and the
  updated roadmap.

* style: normalise end-of-file newlines

Found by the new end-of-file-fixer hook.

* ci: add pre-commit and pre-push hooks that mirror CI

There were no local hooks (the README claimed a .pre-commit-config.yaml that didn't exist), so
  formatting, lint, typing, CVE and coverage failures only surfaced in CI after a push.

- commit stage: file hygiene, detect-private-key, gitleaks 8.30.1 (same version as CI), actionlint,
  and ruff format, ruff check and mypy run from the project venv via 'uv run', so hooks can't drift
  from CI's tool versions - push stage: 'make audit' and the full test suite with the 100% line +
  branch coverage gate (about 2 s here) - SKIP_DOTENV=1 makes Settings ignore the local .env, so the
  push-stage tests see the same configuration as CI - make hooks-install / hooks-run; README and
  backlog (DX-1) updated

Verified in a scratch clone: a commit with unformatted code and a private key is rejected, and a
  push of untested code (99.33% coverage) is rejected before reaching the remote.


## v1.0.1 (2026-11-26)

### Chores

- **BE-2036**: Rename setup_scripts to example and refresh quick-start docs
  ([`26ce93a`](https://github.com/saladgg/ai-bi-analytics/commit/26ce93aa075d3e223bc00a32433fdc400c733e82))

- Move setup_scripts/{db_user_setup,gen_test_table_data}.py under example/ and rewrite the example
  README with separate Docker vs host-Postgres flows, prerequisites, and a verification snippet. -
  Update the root README directory tree and command snippets to reference the new example/ path (and
  surface db_user_setup.py, which the old tree omitted). - Switch the release workflow's Semantic
  Release step from secrets.CI_TOKEN to the built-in secrets.GITHUB_TOKEN to remove the dependency
  on a custom PAT.

- **DE-1032**: Refresh README and modernize FastAPI/Pydantic v2 idioms
  ([`8b090da`](https://github.com/saladgg/ai-bi-analytics/commit/8b090da7b2d7b40aa01d7c3c10fdb104caa8211a))

- Rewrite README to match the real ai_bi_analytics/ package layout, fix quickstart commands and API
  path, and add Releases, frontend, and ToC sections - Replace deprecated @app.on_event("startup")
  with FastAPI lifespan context manager in main.py - Migrate Settings from inner Config class to
  model_config = SettingsConfigDict (Pydantic v2 idiom)

### Refactoring

- **audit**: Add general audit findings and phased backlog
  ([#6](https://github.com/saladgg/ai-bi-analytics/pull/6),
  [`38b72dd`](https://github.com/saladgg/ai-bi-analytics/commit/38b72dd76b2fd33fe06b700e689966f9f446c52f))

* docs(audit): add general audit findings and phased backlog

Adds docs/todos/ with the 01 general audit pair: findings with evidence (01_general_audit.md) and
  the phased execution checklist (01_general_audit_todos.md), plus an index README.

* fix(build): make clean-clone Docker builds and released wheels work

OPS-1: uv.lock was gitignored while the Dockerfile syncs with --frozen, so docker build failed on
  any fresh clone. The *.dockerignore rule also ignored .dockerignore itself, leaving COPY . . free
  to bake .env, .venv, test.db and .git into an image layer. Commit uv.lock, stop ignoring
  .dockerignore and add one.

PKG-1: [tool.setuptools] packages listed only the top-level package, so the v1.0.0 wheel shipped
  just __init__.py and main.py and could not be imported. Use package discovery, ship the Lua script
  as package data, drop build from runtime deps, use a PEP 440 version (PSR writes it in number
  format), and add a CI step that installs the wheel into a clean venv and imports it.

* fix(security): enforce read-only query execution at the database

SEC-2: read-only was a README claim, not a property of the system. The bootstrap script created the
  app user WITH SUPERUSER, so any SQL-guard bypass ran with full database (and, via COPY TO PROGRAM,
  host) privileges.

Defence in depth that holds even if the SQL guard is bypassed: - every Postgres connection starts
  with default_transaction_read_only and server-side statement / idle-in-transaction timeouts - each
  query runs in an explicit READ ONLY transaction that is always rolled back - outside
  ENV=development the app refuses to boot if its role is SUPERUSER, CREATEROLE, CREATEDB or
  BYPASSRLS (fails closed when the role can't be verified) - example/readonly_role.sql creates a
  least-privilege SELECT-only role with the same defaults pinned on the role; compose creates it on
  first start; db_user_setup.py now creates an owner + read-only role pair and passes values as psql
  variables instead of f-string SQL

Verified against Postgres 18 by tests/integration/test_postgres_readonly.py (skipped unless
  TEST_POSTGRES_*_URL are set): multi-statement writes, a smuggled COMMIT, writable CTEs, GRANT,
  pg_sleep timeout and pg_read_file are all refused.

* fix(security): make the rate limiter actually limit

SEC-3: the limiter could never reject a request. Against a real Redis,

20 rapid requests from one client were all allowed: - the Lua script returned the limit itself when
  the window was full, and the caller only rejected counts above the limit - members were
  whole-second timestamps, so a burst in one second collapsed into a single entry - the bucket key
  came from a client-supplied X-Forwarded-For header, so a new value per request bypassed it
  entirely

The script now returns an explicit {allowed, count, retry_after_ms}, takes time from Redis TIME,
  scores in milliseconds with unique members, and uses PEXPIRE. The bucket is the socket peer
  address (uvicorn applies X-Forwarded-For only from FORWARDED_ALLOW_IPS proxies). 429s carry
  Retry-After and every response carries X-RateLimit-Limit/Remaining. The limit and window are
  settings, and the script loads via importlib.resources instead of a CWD-relative path (ARCH-4).

Tests now run the real Lua via fakeredis[lua]. The hand-written fakes had different semantics and
  hid this bug. The route also exercises the real cache module now. Re-verified against
  redis-server: 5 allowed, 15 blocked, spoofed XFF ignored.

* fix(security): replace substring SQL checks with an AST guard

SEC-1: the validator was four string checks, and it was the only real control between an
  attacker-steerable LLM and the database. Reproduced bypasses: 'SELECT 1; GRANT ...' (only two
  semicolons were rejected), pg_sleep, pg_read_file, lo_import, set_config, and pg_shadow reads.
  With 'SELECT 1; COPY ... TO PROGRAM' and a superuser role, that is host RCE.

The guard now parses with sqlglot (postgres dialect) and accepts only: - exactly one statement whose
  root is SELECT or a set operation - no write, DDL, COPY, GRANT, SET, transaction, SELECT INTO or
  FOR UPDATE/SHARE node anywhere, CTEs included - no dangerous functions (pg_*, lo_*, dblink,
  *_to_xml, set_config, current_setting, sequence functions, ...) - only reflected tables from the
  default schema, never system catalogs

It returns SQL regenerated from the validated AST, and the route executes that instead of the raw
  model output. What was checked is exactly what runs, and comments are dropped.

CQ-1: parsing also fixes false positives. created_at, last_update, 'Delete Key' literals, every CTE,
  and fenced model output were rejected before.

Tests: a 100+ case adversarial/acceptance corpus. Integration tests confirm the canonical SQL runs
  on Postgres 18 with the original meaning, including dollar-quoted payloads staying literals.

* docs(audit): mark Phase 0 shipped and document the new guardrails

README now describes the AST guard (canonical SQL execution), the database-enforced read-only role,
  and the rate limiter's headers, settings and proxy trust. The 01 backlog records what shipped per
  item, where it deviated from the plan, and what stays open (v1.0.0 asset decision, client-id
  keying pending SEC-8).

* docs(readme): document Phase 0 guardrails, configuration and license

- add a Configuration table covering the new DB timeout and rate-limit settings and
  FORWARDED_ALLOW_IPS - getting-started steps now use the read-only role for the API and the owner
  role for seeding - document rate-limit headers and that the returned sql is what ran - document
  the opt-in Postgres integration suite - correct claims that weren't true: pre-commit config,
  Coveralls upload, and OpenTelemetry DB/Redis spans - add the Roadmap section the table of contents
  already linked to - add a proprietary License footer matching pyproject.toml

* docs(audit): point Phase 0 checklist at rewritten commit hashes

* ci: gate releases on green CI and enforce 100% coverage

Coverage: pytest now fails under 100% line AND branch coverage (--cov-branch --cov-fail-under=100,
  mirrored in [tool.coverage]). The suite is at 100% for both (318 statements, 58 branches).

CI: runs on pull requests as well as main. The format step was 'make format', which rewrites files
  and always exits 0; it is now a check-only 'make format-check'.

Release, aligned with menu-yetu's pipeline: - triggers on workflow_run of CI and only when that run
  succeeded on main, instead of racing CI on push (a red build could be released) - releases the
  exact CI-validated SHA (checkout by head_sha, then reattach main so PSR accepts it; a newer main
  fails fast) - serialized with a non-cancelling concurrency group - actions SHA-pinned; uv 0.10.9
  and python-semantic-release 9.21.1 pinned; leftover debug step removed - build_command 'uv lock &&
  uv build' keeps uv.lock's own version in step with each release (committed via assets) and builds
  the wheel and sdist attached to the GitHub release

Dry run of PSR 9.21.1 against v1.0.0 computes 1.0.1 for this branch.

* docs: record CI/release gating and the coverage gate

README explains the CI-gated release flow and the 100% coverage gate. The 01 backlog ticks the CI-1
  and TEST-1 items that shipped and now references Phase 0 commits by subject rather than hash, so
  the references survive history rewrites.


## v1.0.0 (2026-04-25)

### Bug Fixes

- **BE-2034**: Fix semantic release failure
  ([`9061f69`](https://github.com/saladgg/ai-bi-analytics/commit/9061f69e26c757caf2b0263aaea4b0d21ae606be))

- **DT-2025**: Ensure make install* runs against active venv
  ([`15ec9af`](https://github.com/saladgg/ai-bi-analytics/commit/15ec9af11572328481366481823883ef73bd953c))

### Chores

- Improve documentation
  ([`dc2931e`](https://github.com/saladgg/ai-bi-analytics/commit/dc2931e975d7ef775682d273c2e64d898d02a59c))

- Improve project documentation
  ([`14cb025`](https://github.com/saladgg/ai-bi-analytics/commit/14cb0259111997af3c8f067b8936f0ef19f514c2))

### Documentation

- **DT-2026**: Improve technical documentation.
  ([`9a7831e`](https://github.com/saladgg/ai-bi-analytics/commit/9a7831ef678b58059471b7337c20bb9b68a78e76))

### Features

- Add initial versioning support and expand Makefile helpers
  ([`2c41210`](https://github.com/saladgg/ai-bi-analytics/commit/2c41210bd8e7ae4850c1d2fa4362a5f612fb3fef))

- add mypy type checker integration - update ruff configuration (enable more rules, adjust line
  length, etc.) - improve natural language → SQL prompt for better accuracy and robustness -
  introduce basic version bumping helpers in Makefile

- Add rate limiting, caching layer, and dynamic schema introspection
  ([`0499eb9`](https://github.com/saladgg/ai-bi-analytics/commit/0499eb9d1a9dbb7590b47c480b4a6cfcff49881e))

- Implemented SlowAPI-based request rate limiting (5 req/min) - Added TTL-based in-memory caching to
  reduce repeated LLM calls - Introduced dynamic SQL schema introspection via SQLAlchemy inspector -
  Refactored NL→SQL prompt to merge strict generation rules with dynamic schema - Improved logging
  and structured query execution flow

Enhances system robustness, cost control, and production readiness.

- Migrate to Redis-backed rate limiting and distributed caching
  ([`d734a7a`](https://github.com/saladgg/ai-bi-analytics/commit/d734a7a823171c5adf945500184217cf799c8d6c))

- Removed in-memory SlowAPI rate limiting - Implemented Redis fixed-window rate limiter - Replaced
  TTLCache with Redis-based response caching - Extended Docker Compose with Redis service - Improved
  horizontal scalability and persistence

Enhances production readiness and distributed system capability.

- **backend**: Initialize AI-powered BI backend architecture with uv, CI, and Docker support
  ([`3e5a1a8`](https://github.com/saladgg/ai-bi-analytics/commit/3e5a1a891c00ea0c3b416a21a04b82f9bedadfb8))

- scaffold FastAPI application with modular structure - implement AI service layer for LLM-powered
  query analysis - integrate SQLAlchemy with PostgreSQL - configure uv-based dependency management
  and locking - add Makefile for linting, formatting, testing, and Docker workflows - introduce
  Dockerfile optimized for layer caching - configure GitHub Actions CI pipeline - set up ruff,
  black, isort, and pytest tooling - establish clean project structure aligned with backend best
  practices

- **BE-2033**: Add semantic release pipeline based on python semantic release (PSR) package
  ([#5](https://github.com/saladgg/ai-bi-analytics/pull/5),
  [`f0283fa`](https://github.com/saladgg/ai-bi-analytics/commit/f0283fa63916dff0fe17cd98344ab5c94cc60808))

- **core**: Bootstrap production-ready AI BI backend with clean architecture and modern tooling
  ([`7828b26`](https://github.com/saladgg/ai-bi-analytics/commit/7828b26c009df83415cc899d56350f525ee72764))

- design layered backend architecture (API, services, persistence) - integrate LLM-driven analytics
  service layer - configure PostgreSQL via SQLAlchemy ORM - adopt uv for fast, reproducible
  dependency management - add Docker support with optimized build caching - implement CI pipeline
  with linting and testing gates - standardize development workflow via Makefile - enforce
  formatting and static analysis using ruff and black

- **DT-2025**: Add structured logging configuration and OpenTelemetry instrumentation
  ([`0646046`](https://github.com/saladgg/ai-bi-analytics/commit/0646046fd7f806c5e9d9101757e44d420453f53a))

- Introduced centralized logging configuration for FastAPI application - Added environment-aware log
  levels (DEBUG for dev, INFO for production) - Implemented verbose and simple formatters with
  trace/span correlation support - Configured console logging handlers for uvicorn and application
  modules - Integrated OpenTelemetry FastAPI instrumentation for distributed tracing - Prepared
  logging pipeline for OTLP-compatible observability backends

- **DT-2025**: Upgrade Redis rate limiting to Lua sliding-window implementation
  ([`def8d12`](https://github.com/saladgg/ai-bi-analytics/commit/def8d12c7a503666c83f1d8a3df5e19c07d0b177))

- Added Redis Lua script to perform sliding-window rate limiting - Eliminates multi-command pipeline
  in favor of single atomic execution - Reduces network overhead and improves concurrency guarantees
  - Maintains accurate request quotas across distributed API instances

- **FE-2028**: Add minimal Streamlit UI for querying and visualizing results
  ([`edd9477`](https://github.com/saladgg/ai-bi-analytics/commit/edd9477b939848d63c282997a6c7f1aec696dd07))

- Add Streamlit app as frontend interface for /api/query endpoint - Implement question input and API
  integration - Display query results in tabular format - Add automatic chart generation for numeric
  results - Show generated SQL inline under Results section - Include explanation section for query
  insights - Structure frontend into api and utils modules

### Refactoring

- **BE-2032**: Rename repo to ai-bi-analytics
  ([`0b1c014`](https://github.com/saladgg/ai-bi-analytics/commit/0b1c014e2b9b48fbfa7a55076f8abe6d64f17840))
