# ==========================================================
# AI BI Backend - Makefile
# Modern Python Backend with uv
# ==========================================================

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Available commands:"
	@echo "  make install        Install production dependencies"
	@echo "  make install-dev    Install dev dependencies"
	@echo "  make install-test   Install test dependencies"
	@echo "  make run            Run development server"
	@echo "  make prod           Run production server"
	@echo "  make lint           Run ruff"
	@echo "  make format         Format code"
	@echo "  make format-check   Check formatting without changing files (CI)"
	@echo "  make test           Run tests (fails under 100% line+branch coverage)"
	@echo "  make audit          Audit dependencies for known vulnerabilities"
	@echo "  make hooks-install  Install pre-commit + pre-push hooks (once per clone)"
	@echo "  make hooks-run      Run every hook (both stages) on all files"
	@echo "  make docker-build   Build Docker image"
	@echo "  make docker-up      Run api + postgres + redis (image as built)"
	@echo "  make docker-up-dev  Same, with the source mounted and auto-reload"
	@echo "  make api-key CLIENT=<id>  Generate a client API key + API_KEYS entry"



# ----------------------------------------------------------
# Dependency Management
# ----------------------------------------------------------
# Create ~/.netrc for private pip credentials(for uv)
# Use `only-managed` to bypass sudo installed system python

VENV_PYTHON := .venv/bin/python

.PHONY: venv_setup
venv_setup:
	uv venv --python 3.14 --python-preference only-managed &
	source .venv/bin/activate

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

.PHONY: format format-check lint test

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

.PHONY: tempTarget
tempTarget:
	UV_PUBLISH_USERNAME=$(CI_PYPI_USER) \
	UV_PUBLISH_PASSWORD=$(CI_PYPI_PASSWORD) \
	uv publish --index temp_index dist/*

.PHONY: release
release: build publish


# ----------------------------------------------------------
# Clean
# ----------------------------------------------------------

.PHONY: clean
clean:
	# Remove all Python cache directories
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".coverage" -delete
	find . -type d -name "htmlcov" -exec rm -rf {} +
	find . -type d -name ".tox" -exec rm -rf {} +
	find . -type d -name ".eggs" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
