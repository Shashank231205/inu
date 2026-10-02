# 0003. Python monorepo on a uv workspace

- **Status:** accepted
- **Date:** 2026-10-02

## Context

INU has a core library and several deployables (voice gateway, API, worker, training jobs). They share domain types and must stay version-consistent. The laptop runs Windows with no `make`, and Docker isn't installed yet.

## Decision

- **Language:** Python 3.12. The ML, audio and inference ecosystems all target it, and asyncio fits the streaming pipeline.
- **Workspace:** a uv workspace with one lockfile. The core library lives in `packages/`; deployables go in `apps/` as they are built.
- **Task runner:** Poe the Poet, defined in `pyproject.toml`. It works the same on Windows and Linux with no system dependency.
- **Quality:** ruff (lint and format), mypy in strict mode, pytest with coverage, and pre-commit hooks.
- **Secret scanning:** detect-secrets in the pre-commit hook, gitleaks in CI. Windows Smart App Control blocks the unsigned gitleaks binary that pre-commit compiles locally, and pure-Python detect-secrets doesn't have that problem. Running both also catches more, since their rule sets differ.
- **Commits:** Conventional Commits, enforced by a commit-msg hook.

Frontend code (HUD, phone PWA) will get its own ADR when Stage H starts.

## Alternatives considered

| Option | Why not |
|---|---|
| Poetry | Slower, and its workspace support is weaker than uv's |
| Separate repos per service | Version drift and duplicated domain types for a single-developer system |
| Make / just | Make isn't on Windows by default; just adds a system install for little gain |
| Go or Rust for the voice loop | Most of the work happens in native inference libraries; Python orchestration overhead is small compared with the latency budget. Revisit if profiling in Phase 11 says otherwise. |

## Consequences

One `uv sync` sets up everything. Python's GIL means CPU-heavy work must go to thread or process pools. This is handled in the pipeline design (Phase 9).
