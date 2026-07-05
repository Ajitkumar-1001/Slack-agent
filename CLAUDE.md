# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FlowPilot AI — a Slack-native project execution copilot (Slack Agent Builder Challenge 2026 MVP). Core loop:

```
Slack request -> grounded ProjectPlan -> Block Kit approval card -> human decision -> GitHub issues -> audit log -> Slack summary
```

The MVP is "done" when one Slack request becomes a structured plan, an approval card, approved GitHub issues, an audit entry, and a final Slack summary. It is **not** a chatbot, dashboard, or autonomous agent.

## Where the truth lives (read before implementing)

Most of the design is documentation, and most of it is **gitignored** (local-only but binding):

- `.specify/memory/constitution.md` — **15 non-negotiable principles**, the highest-precedence rules. Read this first.
- `Slack-agent/` — an Obsidian vault, the design source of truth:
  - `PRD/SourceOfTruth.md`, `PRD/MVP-Architecture-Plan.md` — product + phase plan
  - `Architecture/System-overview.md` — implementation-facing architecture, data model, API surface, prompt contract, failure modes
  - `Decisions/` — ADR-001..004 (Slack-is-frontend, lean planner-orchestrator, GitHub-first writes, approval + idempotency)
  - `Implementation/Phase-*.md` — per-phase build instructions

Precedence when guidance conflicts: (1) constitution, (2) PRD SourceOfTruth, (3) ADRs.

## Current state

The code is **scaffolding only**. `backend/main.py` is a hello-world stub; the package `__init__.py` files are empty. The module layout below is the *planned* target from the architecture plan — most files don't exist yet. Build it one phase at a time (constitution XIV); don't pull later-phase capabilities forward.

## Commands

All backend work runs through `uv` from `backend/` (Python 3.12; pip/Poetry/Conda are forbidden):

```bash
cd backend
uv sync                                      # install deps from uv.lock
uv run uvicorn app.main:app --reload         # run the API (once app/main.py exists)
uv run pytest                                # all tests
uv run pytest tests/test_schemas.py          # a single test file
uv run pytest tests/test_schemas.py::test_x  # a single test
uv run ruff check .                          # lint
uv run ruff format .                         # format
uv run mypy .                                # type check (pyright also available)
```

Pre-completion gate (constitution): ruff + type check + pytest must actually run and pass; report new vs. pre-existing failures separately.

## Architecture

Single planner-orchestrator with typed tool adapters — **not** a multi-agent supervisor (ADR-002). Planned `backend/` layout:

- `app/` — FastAPI app factory, routes (`/health`, `/slack/events`, `/slack/actions`), Pydantic settings, structlog
- `slack/` — Slack Bolt wiring, event handlers, approval-button actions, Block Kit renderers
- `agents/` — `schemas.py` (ProjectPlan, Milestone, Task, Risk, Dependency), `planner.py` (structured generation), `prompts.py`
- `workflows/` — `create_plan.py`, `approve_plan.py`, `execute_plan.py` (deterministic state machine; LangGraph, if used, is state-machine-only per constitution VI)
- `tools/` — `slack_rts.py` (Slack Real-Time Search), `github.py` (issue adapter) — external systems isolated here
- `db/` — SQLAlchemy models + Alembic migrations over PostgreSQL/Supabase; `repository.py`, `session.py`

Approval state machine: `proposal_created -> pending_approval -> {approved | rejected | edit_requested} -> executing -> {executed | failed}`.

## Hard constraints (these will get violated if you're not careful)

- **No external write before human approval.** Reject creates zero artifacts. Approve records an `ApprovalDecision` (persisted) before any write. No autonomous writes.
- **Every external write is idempotent**, with a durable per-action idempotency key in the DB — not in-memory. Retries / duplicate approvals must not create duplicate GitHub issues.
- **Never persist or index raw Slack messages.** No pgvector index over Slack. RTS context is used for the active workflow then discarded; only derived artifacts (proposals, plans, logs) are stored.
- **Slack RTS is the only Slack retrieval mechanism** — no custom crawler/export/vector index.
- **LLM output must validate against Pydantic** at the boundary; validation failure triggers retry or safe failure, never best-effort parsing.
- **Slack is the only frontend.** No Next.js / web / dashboard for MVP (constitution II).
- Secrets come from env / Pydantic Settings only — never hardcoded, never logged.
- Every major workflow event gets an audit/`ActionLog` entry.
- Approved v1 dependencies only; introducing a new agent-orchestration framework (CrewAI, AutoGen, etc.) or a Slack vector DB requires a superseding ADR.

<!-- SPECKIT START -->
Active feature: **001-flowpilot-slack-mvp**. Read the plan and its design
artifacts for technologies, project structure, contracts, and validation steps:
- Plan: `.specify/specs/001-flowpilot-slack-mvp/plan.md`
- Spec: `.specify/specs/001-flowpilot-slack-mvp/spec.md`
- Data model: `.specify/specs/001-flowpilot-slack-mvp/data-model.md`
- Research: `.specify/specs/001-flowpilot-slack-mvp/research.md`
- Contracts: `.specify/specs/001-flowpilot-slack-mvp/contracts/`
- Quickstart (per-phase validation): `.specify/specs/001-flowpilot-slack-mvp/quickstart.md`
<!-- SPECKIT END -->
