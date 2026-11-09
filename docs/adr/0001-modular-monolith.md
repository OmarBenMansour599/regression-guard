# ADR 0001: Modular monolith, CLI-first

Status: Accepted (2026-11-09)

## Context
The system needs an evaluation engine, comparison, reporting, notifications, storage, an API and a dashboard. Solo developer, free-tier LLM APIs, no scale requirements.

## Decision
One Python package (`regguard`) with strict layering; CLI, API and CI are thin shells over a shared service layer. Runs execute in-process with `asyncio`; run state is persisted in the DB. No microservices, queue or Redis.

## Consequences
+ Simple to develop, test and deploy; CI needs no server.
- Long runs are tied to a process; mitigated by persisted state and resumability. Revisit (ARQ/RQ) only if multi-tenant or long-running jobs require it.
- Layering must be enforced (import-linter) to avoid erosion.
