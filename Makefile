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


# ----------------------------------------------------------
# Variables
# ----------------------------------------------------------

APP=app.main:app
HOST=0.0.0.0
PORT=8000

# ----------------------------------------------------------
# Dependency Management
# ----------------------------------------------------------

.PHONY: install
install:
	uv sync

.PHONY: install-dev
install-dev:
	uv sync --extra dev

.PHONY: update
update:
	uv lock --upgrade

# ----------------------------------------------------------
# Run Application
# ----------------------------------------------------------

.PHONY: run
run:
	uv run uvicorn $(APP) --reload --host $(HOST) --port $(PORT)

.PHONY: prod
prod:
	uv run uvicorn $(APP) --host $(HOST) --port $(PORT)

# ----------------------------------------------------------
# Linting & Formatting
# ----------------------------------------------------------

.PHONY: lint
lint:
	uv run ruff check app

.PHONY: format
format:
	uv run black app
	uv run isort app

.PHONY: lint-fix
lint-fix:
	uv run ruff check app --fix
	uv run black app
	uv run isort app

.PHONY: check
check:
	uv run ruff check app
	uv run black --check app
	uv run isort --check-only app

# ----------------------------------------------------------
# Testing
# ----------------------------------------------------------

.PHONY: test
test:
	uv run pytest

.PHONY: test-cov
test-cov:
	uv run pytest --cov=app --cov-report=term-missing

# ----------------------------------------------------------
# Security / Safety
# ----------------------------------------------------------

.PHONY: safety
safety:
	uv run pip check

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
	docker compose down

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
