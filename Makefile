# ==========================================================
# AI BI Backend - Makefile
# Modern Python Backend with uv
# ==========================================================

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Available commands:"
	@echo "  make venv_setup     Create .venv with a uv-managed Python 3.14"
	@echo "  make install        Install runtime dependencies"
	@echo "  make install-dev    Install dev dependencies (tests, lint, demo UI)"
	@echo "  make install-test   Install runtime + test dependencies"
	@echo "  make update         Upgrade locked dependency versions"
	@echo "  make run_local      Run the API with auto-reload on :8000"
	@echo "  make run_prod       Run the API without reload"
	@echo "  make run_frontend   Run the Streamlit demo on :8501"
	@echo "  make format         Format code and apply lint fixes"
	@echo "  make format-check   Check formatting without changing files (CI)"
	@echo "  make lint           ruff + mypy"
	@echo "  make test           Run tests (fails under 100% line+branch coverage)"
	@echo "  make audit          Audit dependencies for known vulnerabilities"
	@echo "  make check          Everything CI checks: format-check, lint, audit, test"
	@echo "  make hooks-install  Install pre-commit + pre-push hooks (once per clone)"
	@echo "  make hooks-run      Run every hook (both stages) on all files"
	@echo "  make docker-build   Build Docker image"
	@echo "  make docker-up      Run api + postgres + redis (image as built)"
	@echo "  make docker-up-dev  Same, with the source mounted and auto-reload"
	@echo "  make docker-down    Stop the stack and delete its volumes"
	@echo "  make build          Build the wheel and sdist into dist/"
	@echo "  make api-key CLIENT=<id>  Generate a client API key + API_KEYS entry"
	@echo "  make clean          Remove caches and build output"


# ----------------------------------------------------------
# Dependency Management
# ----------------------------------------------------------
# `only-managed` uses a uv-managed interpreter, not the system Python.

.PHONY: venv_setup
venv_setup:
	uv venv --python 3.14 --python-preference only-managed
	@echo "Activate with: source .venv/bin/activate (or prefix commands with uv run)"

.PHONY: install install-dev install-test update

# Main install (production / default dependencies)
install:
	uv sync

# Development dependencies (main + dev group)
install-dev:
	uv sync --group dev

# Test/CI dependencies (main + test group, no dev)
install-test:
	uv sync --group test

# Update dependencies (upgrade versions in lockfile)
update:
	uv lock --upgrade

# ----------------------------------------------------------
# Linting & Formatting
# ----------------------------------------------------------

SOURCE = ai_bi_analytics
# Everything ruff formats and lints (mypy's file list is in pyproject.toml).
LINT_PATHS = ai_bi_analytics tests frontend example

.PHONY: api-key
api-key:
	@test -n "$(CLIENT)" || (echo "usage: make api-key CLIENT=<client_id>" && exit 2)
	uv run python -m ai_bi_analytics.core.security $(CLIENT)

.PHONY: format format-check lint test check

format:
	uv run ruff format $(LINT_PATHS)
	uv run ruff check $(LINT_PATHS) --fix

format-check:
	uv run ruff format --check $(LINT_PATHS)

lint:
	uv run ruff check $(LINT_PATHS)
	uv run mypy

test:
	uv run pytest

# What CI's test job runs, in the same order.
check: format-check lint audit test

.PHONY: hooks-install hooks-run
hooks-install:
	uv run pre-commit install --install-hooks

hooks-run:
	uv run pre-commit run --all-files
	uv run pre-commit run --all-files --hook-stage pre-push

.PHONY: audit
audit:
	# OSV batches its queries; the default PyPI service issues one request
	# per installed package and times out intermittently in CI.
	uv run pip-audit -s osv --timeout 60

# ----------------------------------------------------------
# Run Application
# ----------------------------------------------------------
APP=ai_bi_analytics.main:app
HOST=0.0.0.0
PORT=8000

.PHONY: run_local
run_local:
	uv run uvicorn $(APP) --reload --host $(HOST) --port $(PORT)

.PHONY: run_prod
run_prod:
	uv run uvicorn $(APP) --host $(HOST) --port $(PORT)


# ----------------------------------------------------------
# Run Frontend
# ----------------------------------------------------------

.PHONY: run_frontend
run_frontend:
	uv run --group frontend streamlit run frontend/streamlit_app.py

# ----------------------------------------------------------
# Docker
# ----------------------------------------------------------

.PHONY: docker-build
docker-build:
	docker build -t ai-bi-backend .

.PHONY: docker-up
docker-up:
	docker compose up --build

# Development: bind-mounts the source and reloads on change.
.PHONY: docker-up-dev
docker-up-dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

.PHONY: docker-down
docker-down:
	docker compose down -v

# ----------------------------------------------------------
# Packaging & Publishing
# ----------------------------------------------------------

.PHONY: build
build:
	rm -rf dist
	uv build

# Releases are automated (semantic-release on main after CI passes); see
# README "Releases". There is no manual release target.


# ----------------------------------------------------------
# Clean
# ----------------------------------------------------------

.PHONY: clean
clean:
	# Caches and build output; never touches .venv or .env.
	find . -path ./.venv -prune -o -type d \( -name "__pycache__" -o -name ".pytest_cache" \
		-o -name ".ruff_cache" -o -name ".mypy_cache" -o -name "htmlcov" \
		-o -name "*.egg-info" \) -exec rm -rf {} +
	find . -path ./.venv -prune -o -type f -name "*.py[co]" -delete
	rm -rf .coverage coverage.xml dist build test.db
