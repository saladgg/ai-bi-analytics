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
	@echo "  make run            Run development server"
	@echo "  make prod           Run production server"
	@echo "  make lint           Run ruff"
	@echo "  make format         Format code"
	@echo "  make check          CI formatting checks"
	@echo "  make test           Run tests"
	@echo "  make docker-build   Build Docker image"


.PHONY: all
all: clean lint format fix test

# ----------------------------------------------------------
# Dependency Management
# ----------------------------------------------------------
# Create ~/.netrc for private pip credentials(for uv)

.PHONY: venv_setup
venv_setup:
	uv venv --python 3.14 && source .venv/bin/activate

.PHONY: install install-dev

install:
	uv lock --prerelease=allow
	uv sync

install-dev:
	uv lock --prerelease=allow
	uv sync --group dev

.PHONY: update
update:
	uv lock --upgrade --prerelease=allow

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

fix:
	uv run ruff check $(SOURCE) --fix
	uv run ruff format $(SOURCE)

test:
	uv run pytest

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
	rm -rf __pycache__
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf .mypy_cache
	rm -rf htmlcov
	rm -rf .coverage
	find . -type d -name "__pycache__" -exec rm -r {} +
