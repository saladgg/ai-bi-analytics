# AI-Powered Business Intelligence Backend

## Overview

A production-grade FastAPI backend enabling natural-language
queries over PostgreSQL with safe SQL generation and explainable outputs.

## Problem

Business users need insights from databases but cannot write SQL.
Naive LLM integrations risk unsafe query execution.

## Solution

This system:
- Converts natural language to SQL
- Enforces strict read-only guardrails
- Executes validated queries
- Generates grounded explanations
- Logs AI decisions for traceability

## Architecture

[Include simple architecture diagram]

Client → FastAPI → NL-to-SQL → SQL Validator → PostgreSQL
                              → Explanation Service

## Key Engineering Decisions

- LLM abstraction layer
- Explicit SQL safety validation
- Read-only database access
- Dependency injection for testability
- Structured logging
- Dockerized deployment

## Example Request

POST /api/query

{
  "question": "What are the top 3 products by revenue?"
}

## Example Response

{
  "sql": "...",
  "result": [...],
  "explanation": "The top three products by revenue are..."
}


## Basic start-up commands
```bash
user@comp: ~\λ curl -LsSf https://astral.sh/uv/install.sh | sh # install uv globally
user@comp: ai_bi_backend\λ # clone and navigate to the project directory
user@comp: ai_bi_backend\λ uv venv --python 3.14 # create venv
user@comp: ai_bi_backend\λ source .venv/bin/activate # activate the venv
(ai_bi_backend) user@comp: ai_bi_backend\λ make help # show available make commands
(ai_bi_backend) user@comp: ai_bi_backend\λ make install-dev
(ai_bi_backend) user@comp: ai_bi_backend\λ make run
```

## Docker commands

```bash
(ai_bi_backend) user@comp: ai_bi_backend\λ make docker-build
(ai_bi_backend) user@comp: ai_bi_backend\λ make docker-up
(ai_bi_backend) user@comp: ai_bi_backend\λ make docker-down
```

