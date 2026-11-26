# CHANGELOG


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
