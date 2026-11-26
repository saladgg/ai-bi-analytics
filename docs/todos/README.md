# Audit backlogs

Each numbered pair is one audit: `NN_<topic>.md` holds the findings with
evidence and code references; `NN_<topic>_todos.md` is the execution
checklist (IDs match across the pair, and each todos file carries a
status stamp at the top). Ship order within a backlog is its phase order.

| Pair | Topic | Status stamp lives in |
| ---- | ----- | --------------------- |
| 01 | General audit — security, hardening, architecture, code quality, performance, operations, missing capabilities across the whole repo (backend, Streamlit demo, Docker/compose, CI/release, tests) | [`01_general_audit_todos.md`](01_general_audit_todos.md) — **filed 2026-11-26; Phases 0 and 1 shipped the same day.** P0: AST SQL guard executing canonical SQL, DB-enforced read-only role, a working rate limiter, clean builds, an importable wheel (released as v1.0.1). P1: typed errors with request ids, bounded results, prompt separation, an allowlisted query scope, per-client hashed API keys, and CI with whole-repo lint, pip-audit, Trivy, gitleaks and Postgres integration. Phases 2–5 open |

Conventions: findings are severity-tagged (🔴/🟠/🟡/🟢) with per-item
effort estimates (S ≤ ½ day, M ≤ 2 days, L > 2 days); cross-backlog
overlaps are declared in each file's header ("tracked there, not
re-filed") so one item never lives in two checklists. Findings marked
**(verified)** were reproduced during the audit, not just read off the code.
