# Audit backlogs

Each numbered pair is one audit: `NN_<topic>.md` holds the findings with
evidence and code references; `NN_<topic>_todos.md` is the execution
checklist (IDs match across the pair, and each todos file carries a
status stamp at the top). Ship order within a backlog is its phase order.

| Pair | Topic | Status stamp lives in |
| ---- | ----- | --------------------- |
| 01 | General audit — security, hardening, architecture, code quality, performance, operations, missing capabilities across the whole repo (backend, Streamlit demo, Docker/compose, CI/release, tests) | [`01_general_audit_todos.md`](01_general_audit_todos.md) — **filed 2026-11-26; Phases 0–3 shipped by 2026-11-28.** P0 (v1.0.1): AST SQL guard, DB-enforced read-only role, a working rate limiter, clean builds. P1 (v1.1.0): typed errors with request ids, bounded results, prompt separation, an allowlisted query scope, per-client hashed API keys, full CI gates. P2 (v1.2.0): liveness/readiness, OTLP traces and metrics with JSON logs, a fail-open cache, and a non-root 343 MB image with hardened compose. P3: central config with clients built at startup, a DI'd query pipeline, a task-level LLM interface with structured output, a schema cache, and the Streamlit and Makefile fixes. Phases 4–5 open |

Conventions: findings are severity-tagged (🔴/🟠/🟡/🟢) with per-item
effort estimates (S ≤ ½ day, M ≤ 2 days, L > 2 days); cross-backlog
overlaps are declared in each file's header ("tracked there, not
re-filed") so one item never lives in two checklists. Findings marked
**(verified)** were reproduced during the audit, not just read off the code.
