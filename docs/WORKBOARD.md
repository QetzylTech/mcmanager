# MCManager Workboard

This is the shared, repository-tracked Kanban board for WBS and realignment
work. Read it before taking a task; update the card here so a new agent can
resume without relying on chat history. The board tracks implementation and
verification, not just code-writing.

## Board rules

1. Keep one bounded deliverable per card. `KB-` identifiers are board-local
   stable references; WBS/realignment IDs in each card are source references.
   Do not renumber or reuse board IDs.
2. Before starting, move the card to **In Progress**, set `Owner` to your
   agent/session identifier, and update `Updated`. Re-read this file first and
   edit only your card to avoid overwriting another agent's update.
3. Move implementation-complete work to **Review** with the exact tests or
   evidence recorded. Move it to **Done** only when every acceptance check on
   the card passes. A passing nearby test is not a substitute.
4. If blocked, move the card to **Blocked** and state the concrete blocker and
   what will unblock it. Do not invent benchmark limits or mark external-host
   checks complete without running them.
5. Only start a card when its dependencies are Done. Follow the WBS dependency
   graph; do not parallelize changes to the same world-lock or lifecycle story.
6. When a contract changes, update the governing numbered document first,
   then its pseudocode/audit notes and this board. Numbered product documents
   take precedence over WBS sketches and older audit notes.
7. Record commands, pass/fail counts, and platform in `Evidence`. Do not
   overwrite evidence with a newer partial run.

### Status meanings

- **To Do** — unowned work. Check every listed dependency; claim only after
  they are all Done.
- **In Progress** — actively owned by an agent.
- **Review** — implementation is present; acceptance evidence/review remains.
- **Blocked** — cannot proceed until the stated external or prerequisite
  condition changes.
- **Backlog** — valid work, but intentionally not ready to start yet.
- **Done** — acceptance criteria passed and evidence is recorded.

Priority: **P0** release blocker / foundational, **P1** required gate work,
**P2** important follow-up, **P3** housekeeping.

## Gate roll-up

| Area | Current board view | Release state |
|---|---|---|
| Repository layout | Root `app/` and `migrations/`; world data in `app/data/worlds/` | Layout slice done; remaining Doc 12 root-entry differences tracked below |
| Gate 1 / WP 1.1–1.6 | Adapter spike exists; POSIX acceptance and several wiring/logging contracts remain | Partial |
| Gate 2 / WP 2.1–2.4 | Schema and core services exist; effective configuration and operation/error integration remain | Partial |
| Gate 3 / WP 3.1–3.4 | Operations, runtime, scheduler, and audit foundations exist; behavior and lifecycle acceptance remain | Partial |
| Gate 4 / WP 4.1–4.4 | Backup, restore, cleanup, and sync implementations are reported present; verify exact acceptance | Review |
| Gate 5 / WP 5.1–5.3 | Auth, selected API routes, SSE sharing, and shell navigation exist; catalog/workflows/performance remain | Partial |

## Latest verification snapshot

Updated 2026-11-06 on Windows:

- `python -m pytest -q`: **179 passed, 6 failed, 85 warnings**; coverage
  **81.66%**. The failures are one performance-threshold contract and five
  coverage-smoke tests (invalid enum fixtures, FK seed failures, and missing
  `Container.diagnostics`).
- `node --test tests\browser\test_gate5_browser.test.cjs`: **2 passed**.
- Static checks are not green: Ruff reported 52 errors; Black would reformat
  74 files; isort reported 14 files; mypy failed; import-linter reported
  `app layers BROKEN`.
- POSIX conformance and calibrated performance acceptance have not been run.

These are a baseline, not a claim that every failure is caused by current
layout changes. Re-run the relevant command when closing a card.

## Done

### KB-LAYOUT-01 — Put application and migrations at repository root

- **WBS/Docs:** Document 12 §2; realignment packaging decision superseded by
  the user's explicit layout direction.
- **Priority:** P1 · **Owner:** repository session · **Updated:** 2026-11-06
- **Acceptance:** `app/` and `migrations/` exist at root; `core/` is absent;
  layout contract test passes.
- **Evidence:** `python -m pytest --no-cov -q tests/unit/test_project_tooling_contract.py`
  passed (1 test).

### KB-DATA-01 — Keep managed worlds inside application data

- **WBS/Docs:** Document 12 runtime data location instruction; user direction.
- **Priority:** P1 · **Owner:** repository session · **Updated:** 2026-11-06
- **Acceptance:** managed world is under `app/data/worlds/`; database world
  root and world path resolve; foreign-key check is clean.
- **Evidence:** layout contract passed; world lifecycle test passed on retry;
  database paths existed and `PRAGMA foreign_key_check` returned no rows.

## In Progress

_No cards are currently claimed._

## Review

### KB-G2-DOMAIN — Verify domain model and transition coverage

- **WBS:** WP 2.2 · **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** —
- **Acceptance:** domain entities, events, invariants, deletion tiers, and
  lifecycle guards are pure of framework/persistence imports; unit tests cover
  every documented world-state transition and invariant.
- **Evidence:** modules exist under `app/domain/`; current complete test suite
  is not green. Record the focused test command and coverage before Done.

### KB-G2-MIGRATION — Verify migration and persistence contract

- **WBS:** WP 2.1 · **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** —
- **Acceptance:** production-style migration test applies all migrations,
  verifies rollback behavior, `foreign_key_check`, foreign keys on every
  connection, WAL/busy timeout, and concurrent access without raw lock errors.
- **Evidence:** database FK check passed for the local app DB; migration
  rollback/concurrency acceptance is not established by that check alone.

### KB-G4-VERIFY — Close Gate 4 against its exact acceptance checks

- **WBS:** WP 4.1–4.4 · **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** —
- **Acceptance:** test ZIP/SHA-256 roundtrip and save-on after failed
  compression; restore failure triggers pre-restore compensation and marks
  source suspect; cleanup enforces both age/count floors; sync retries at
  30/60/120 seconds without blocking local backup.
- **Evidence:** implementation is reported present in `realignment.txt`;
  collect fresh test results for each listed behavior before marking Done.

## To Do

### KB-G0-1 — Enforce dependency boundaries through ports and repositories

- **WBS/Docs:** Document 12 §4–5; realignment G0-1
- **Priority:** P0 · **Owner:** Unassigned · **Updated:** 2026-11-06
- **Depends on:** —
- **Acceptance:** services do not import concrete platform/process adapters;
  persistence access goes through repository ports/adapters; bootstrap is the
  composition root; configured import contracts pass and test/CI invokes them.

### KB-G0-2 — Centralize and map API error codes

- **WBS/Docs:** WP 5.1; Document 10; realignment G0-3
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** —
- **Acceptance:** documented errors (including CSRF, step-up, world conflict,
  version conflict, storage guard, and cancellation) map to their required
  HTTP status and response envelope; API tests assert the mappings.

### KB-G0-3 — Make startup and worker lifecycle failures visible

- **WBS/Docs:** WP 3.2–3.3; Document 12 §5; realignment G0-2/G3-4/G3-5
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** —
- **Acceptance:** reconciliation errors are surfaced and reflected in health;
  supervisor/scheduler workers have explicit start/stop lifecycle; closing the
  app/store cannot leave workers logging against a closed database.

### KB-G0-4 — Repair full-suite smoke failures

- **WBS/Docs:** Document 11; current full-suite baseline
- **Priority:** P0 · **Owner:** Unassigned
- **Depends on:** —
- **Acceptance:** all five `tests/unit/test_coverage_smoke.py` failures are
  fixed at the correct layer (valid enum values/FK fixtures and a deliberate
  diagnostics implementation or corrected expectation); focused tests and
  full suite pass without weakening assertions.

### KB-G0-5 — Restore green repository static gates

- **WBS/Docs:** Document 12 §8
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G0-1
- **Acceptance:** Ruff, Black, isort, mypy, and import-linter pass on the
  configured project scope; add those commands to the documented/CI gate.
  Avoid broad formatting churn without coordinating it as a dedicated slice.

### KB-G0-6 — Reconcile stale audit and pseudocode with governing docs

- **WBS/Docs:** realignment G0-6; all `docs/gate*_pseudocode.txt`
- **Priority:** P2 · **Owner:** Unassigned
- **Depends on:** —
- **Acceptance:** Document 12's root layout and numbered-document precedence
  are reflected in realignment notes; schema/process/API pseudocode matches
  the numbered documents and current implementation where accepted.

### KB-G1-1 — Inject process and Minecraft capabilities through ports

- **WBS:** WP 1.1, WP 1.5; realignment G1-1
- **Priority:** P0 · **Owner:** Unassigned
- **Depends on:** KB-G0-1
- **Acceptance:** `WorldsService` and save coordination depend on ports, not
  concrete Minecraft infrastructure; bootstrap supplies implementations;
  port and composition tests pass.

### KB-G1-2 — Complete durable, configurable process logging

- **WBS:** WP 1.4; realignment G1-2
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** —
- **Acceptance:** `VERBOSE_LOGGING=false` filters debug/raw output without
  breaking readiness; session logs persist durably alongside bounded
  in-memory tailing; default is documented in `.env.example`.

### KB-G1-3 — Enforce Minecraft readiness and EULA product flow

- **WBS:** WP 1.5; realignment G1-3
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G1-1
- **Acceptance:** each server type reaches `running` only at its highest
  applicable readiness level; EULA acceptance has one audited HTTP flow and
  cannot be bypassed by start or external file changes.

### KB-G1-4 — Align process handle contract across adapters

- **WBS:** WP 1.1–1.3; realignment G1-4
- **Priority:** P2 · **Owner:** Unassigned
- **Depends on:** —
- **Acceptance:** documented process identity/group fields are exposed
  consistently; signal/terminate PID-reuse guards remain intact; Windows
  re-attach and adapter conformance tests pass.

### KB-G2-2 — Implement effective configuration resolution

- **WBS:** WP 2.4; realignment G2-2
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G2-DOMAIN
- **Acceptance:** `ConfigurationService` resolves global settings, world
  overrides, and effective values; tests cover both global fallback and
  world-specific override without callers reading singleton settings directly.

### KB-G2-3 — Route ConfigEdit through durable operations and map conflicts

- **WBS:** WP 2.4; realignment G2-3
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G0-2, KB-G2-2, KB-G3-1, KB-G3-3
- **Acceptance:** stale versions return the documented
  `CONFIG_VERSION_CONFLICT`; ConfigEdit is persisted as an Operation with
  terminal audit behavior; integration test covers success and conflict.

### KB-G3-1 — Keep operation progress in memory between milestones

- **WBS:** WP 3.1; realignment G3-1
- **Priority:** P0 · **Owner:** Unassigned
- **Depends on:** KB-G0-1
- **Acceptance:** progress ticks are published to realtime subscribers without
  per-tick operation writes; only documented milestones are persisted;
  reconnect/snapshot and operation-read behavior remain correct.

### KB-G3-2 — Implement the Document 9 conflict matrix

- **WBS:** WP 3.1; realignment G3-2
- **Priority:** P0 · **Owner:** Unassigned
- **Depends on:** KB-G3-1
- **Acceptance:** parametrized tests cover each requested-operation /
  in-flight-operation cell, including single-flight queueing, duplicate Start
  handling, rejection rules, Kill superseding Stop, and Restore/Delete
  precedence.

### KB-G3-3 — Audit each terminal operation exactly once

- **WBS:** WP 3.4; realignment G3-3
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G3-1
- **Acceptance:** terminal success/failure/cancellation writes exactly the
  documented audit event; intermediate progress writes none; auth/config
  audit behavior remains intact.

### KB-G3-4 — Verify crash-safe runtime reconciliation and supervisor behavior

- **WBS:** WP 3.2; realignment G3-4
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G1-1, KB-G0-3
- **Acceptance:** after manager restart a live server is re-attached rather
  than restarted; failed starts reach the documented timeout state; reconcile
  errors are visible; process crash produces the expected operation/audit/
  notification.

### KB-G3-5 — Run the scheduler automatically and verify missed-run behavior

- **WBS:** WP 3.3; realignment G3-5
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G0-3, KB-G3-2
- **Acceptance:** app lifecycle starts/stops the 30-second scheduler; due work
  dispatches when clear; conflicts create durable missed-run records and are
  never auto-replayed.

### KB-G5-1 — Complete authenticated, CSRF-safe API foundations

- **WBS:** WP 5.1; realignment G5-1/G5-6/G5-7
- **Priority:** P0 · **Owner:** Unassigned
- **Depends on:** KB-G0-2
- **Acceptance:** every mutating route enforces session, CSRF, role, and
  step-up requirements from Document 10; tests cover missing/invalid tokens,
  expiry, and authorization failures.

### KB-G5-2 — Make operation routes durably asynchronous

- **WBS:** WP 5.1; realignment G5-2/G5-3
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G3-1, KB-G3-2
- **Acceptance:** mutating routes return promptly with the documented 202
  operation envelope and `meta.op_id`; work is durable/restart-safe and
  idempotency/conflict behavior is tested.

### KB-G5-3 — Implement backup, restore, cleanup, and sync API catalog

- **WBS:** WP 5.1; realignment G5-8/G5-11
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G5-1, KB-G5-2, KB-G4-VERIFY
- **Acceptance:** Document 10 routes exist with authorization, request/
  response schemas, error mapping, and tests for backup, restore/rollback,
  cleanup preview/execute, and sync.

### KB-G5-4 — Implement settings, schedules, runtime, and administration APIs

- **WBS:** WP 5.1; realignment G5-9/G5-10
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G5-1, KB-G5-2, KB-G2-3, KB-G3-5
- **Acceptance:** Document 10 settings, schedules/missed-runs, templates,
  Java runtimes, admin, notifications, and audit routes are implemented and
  covered by authorized success/error tests.

### KB-G5-5 — Implement world CRUD, EULA, files, and logs APIs

- **WBS:** WP 5.1; realignment G5-7/G5-10
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G1-3, KB-G5-1, KB-G5-2
- **Acceptance:** Document 10 world create/update/delete, runtime config,
  EULA, file management, and log routes enforce their documented guards and
  have integration coverage.

### KB-G5-6 — Complete real workflows for the 17 shell modules

- **WBS:** WP 5.3; realignment G5-12
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G5-3, KB-G5-4, KB-G5-5
- **Acceptance:** modules are functional workflows, not scaffold fragments;
  manager/world context switching works; navigation stays in-place and obeys
  Document 4 tokens and 40px control geometry.

### KB-G5-7 — Verify authenticated SSE lifecycle and complete stream topics

- **WBS:** WP 5.2; realignment G5-5/G5-13
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G5-1, KB-G3-1
- **Acceptance:** reconnect replay, snapshot, auth expiry, all documented
  topics, subscriber cleanup, and 10-tab single-EventSource/failover behavior
  pass server and browser tests.

### KB-D12-1 — Match remaining Document 12 top-level entries

- **WBS/Docs:** Document 12 §2
- **Priority:** P2 · **Owner:** Unassigned
- **Depends on:** —
- **Acceptance:** decide and implement the documented root `static/`,
  `templates/`, and `.env.example` entries without duplicating assets; resolve
  the `Prototypes` casing/layout difference, and add a contract test for the
  agreed structure.

### KB-DOC-STATUS — Reconcile current status and audit evidence

- **WBS/Docs:** `IMPLEMENTATION_STATUS.md`, `realignment.txt`
- **Priority:** P2 · **Owner:** Unassigned
- **Depends on:** KB-G2-DOMAIN, KB-G2-MIGRATION, KB-G4-VERIFY
- **Acceptance:** recorded test commands/counts match a dated fresh run; gate
  claims agree with verified acceptance; obsolete packaging notes and
  contradictions are explicitly superseded rather than silently retained.

## Blocked

### KB-G1-6 — Run C1–C14 on a POSIX host

- **WBS:** WP 1.6; realignment G1-6
- **Priority:** P1 · **Owner:** Unassigned
- **Blocked by:** No POSIX host/CI result is available in this work session.
- **Acceptance:** run `tests/adapters/test_conformance.py` on a supported POSIX
  OS and attach the complete result; fix any platform-specific failures.

### KB-PERF-01 — Calibrate and pass performance release acceptance

- **WBS:** Gate 5; Document 11 §4.2; realignment G5-13
- **Priority:** P1 · **Owner:** Unassigned
- **Blocked by:** A documented reference host and reproducible measurements
  must be supplied; thresholds must not be fabricated.
- **Acceptance:** record CPU/RAM/storage profile; measure 300-second idle CPU
  and RSS, 50-client 1Hz stream fan-out, and 1000-lines/sec ingestion with
  measured tail latency; commit the justified `benchmarks/thresholds.json`
  and pass its acceptance test.

## Backlog

_No additional work is intentionally deferred. Add newly identified scope here
before implementation so agents can review dependencies and acceptance._
