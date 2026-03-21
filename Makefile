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
	@echo "  make check          CI formatting checks"
	@echo "  make test           Run tests"
	@echo "  make docker-build   Build Docker image"



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

SOURCE = app

.PHONY: lint format fix test

lint:
	uv run ruff check $(SOURCE) 
	uv run mypy $(SOURCE) 

format:
	uv run ruff format $(SOURCE) 

format-check:
	uv run ruff format --check $(SOURCE)

fix:
	uv run ruff check $(SOURCE) --fix 
	uv run ruff format $(SOURCE) 

test:
	uv run pytest --cov=$(SOURCE) --cov-report=term-missing

.PHONY: check
check: lint format-check


# ----------------------------------------------------------
# Run Application
# ----------------------------------------------------------
APP=app.main:app
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
	streamlit run frontend/streamlit_app.py

# ----------------------------------------------------------
# Docker
# ----------------------------------------------------------

.PHONY: docker-build
docker-build:
	docker build -t ai-bi-backend .

.PHONY: docker-up
docker-up:
	docker compose up --build

.PHONY: docker-down
docker-down:
	docker compose down -v

# ----------------------------------------------------------
# Packaging & Publishing
# ----------------------------------------------------------

.PHONY: build
build:
	rm -rf dist
	uv run python -m build

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
