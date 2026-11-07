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
| Repository layout | Root `app/` and `migrations/`; managed world data under `app/data/worlds/` | Layout work recorded Done; remaining Doc 12 root-entry differences have a tracked card |
| Gate 1 / WP 1.1–1.6 | Process ports, Windows/fake conformance, readiness, EULA flow, and durable logging are implemented | Partial: POSIX and real-server spike evidence remain |
| Gate 2 / WP 2.1–2.4 | Migration/persistence, domain validation, effective settings, and ConfigEdit operation integration are implemented and tested | Core slices recorded Done; overall gate remains partial pending broader release acceptance |
| Gate 3 / WP 3.1–3.4 | Durable operations, conflict policy, terminal audit, reconciliation, scheduler, and notifications have focused coverage | Core slices recorded Done; full release acceptance remains |
| Gate 4 / WP 4.1–4.4 | Backup, restore, cleanup, and sync services have focused verification | Review: Windows symlink checks, POSIX, and live RCON/NAS acceptance remain |
| Gate 5 / WP 5.1–5.3 | Auth foundations, selected world/admin APIs, SSE sharing, and world-list workflow are implemented | Partial: backup/restore/cleanup/sync catalog and full shell workflows remain; manager lifecycle endpoints are not implemented |

## Latest verification snapshot

Updated 2026-11-07 on Windows / Python 3.13.14:

- `python -m pytest --no-cov -q -k "not performance_acceptance_smoke"`:
  **448 passed, 3 skipped, 1 deselected**. Skips are symlink checks that
  require a Windows privilege unavailable on this host; the deselected smoke
  is the long performance acceptance test.
- `node --test tests\browser\test_gate5_browser.test.cjs`: **2 passed**,
  including all documented manager event topics and auth expiry/recovery.
- Repository-wide static checks remain unverified/known red from the prior
  baseline: Ruff reported 52 errors; Black would reformat 74 files; isort
  reported 14 files; mypy failed; import-linter reported `app layers BROKEN`.
  Scoped Ruff checks for the updated lifecycle, auth, Gate 4, process-contract,
  health, world API, catalog/admin API, ConfigEdit, and SSE slices passed.
- POSIX conformance and calibrated performance acceptance have not been run.

The performance smoke was excluded because it performs the long calibrated
benchmark; release performance acceptance remains blocked pending a reference
host and justified limits.

## Tracked implementation workstreams

These group implementation slices under parent acceptance cards; they are not
gate-completion claims. Parent cards remain open until all acceptance evidence
is integrated and reviewed.

| Workstream | Parent card(s) | Scope |
|---|---|---|
| Gate 1 process adapters | KB-G1-4, KB-G1-6 | Windows/fake process-handle contract completed; POSIX evidence remains blocked |
| Gate 1 Minecraft readiness | KB-G1-1, KB-G1-3 | Port wiring, readiness hierarchy, EULA product flow |
| Gate 1 durable logging | KB-G1-2 | Verbose filtering, durable logs, tailing behavior |
| Gate 2 domain model | KB-G2-DOMAIN | Domain purity, transitions, invariants, unit tests |
| Gate 2 configuration/API | KB-G2-2, KB-G2-3 | Effective settings, version conflicts, ConfigEdit integration |
| Gate 2 persistence | KB-G2-MIGRATION | Migration, rollback, FK/WAL/concurrency acceptance |
| Gate 3 operation engine | KB-G3-1, KB-G3-2, KB-G3-3 | Milestone writes, progress, conflict policy, terminal audit integration |
| Gate 3 runtime reconciliation | KB-G3-4 | Crash-safe reattach and runtime reconciliation acceptance |
| Gate 3 scheduler | KB-G3-5 | Tick, conflict/missed-run behavior; startup seam reported separately |
| Gate 3 audit/notifications | KB-G3-3 | Append-only audit and notification service contracts |
| Gate 4 native backup engine | KB-G4-VERIFY | Archive integrity, staging, atomic publish, cleanup on failure |
| Gate 4 save coordination | KB-G4-VERIFY | RCON flush/freshness/save-on and backup orchestration |
| Gate 4 restore rollback | KB-G4-VERIFY | Pre-restore backup, probe, suspect marking, compensation |
| Gate 4 cleanup/retention | KB-G4-VERIFY | Preview, age/count floors, blast-radius limit |
| Gate 4 sync retries | KB-G4-VERIFY | Retry timeline, cap, NAS transport and local-backup isolation |
| Gate 4 filesystem policy | KB-G4-VERIFY | Path containment, free-space math, tree size and mtime |

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

### KB-G2-MIGRATION — Verify migration and persistence contract

- **WBS:** WP 2.1 · **Priority:** P1 · **Owner:** Copilot session
  · **Updated:** 2026-11-06
- **Acceptance:** production-style migration test applies all migrations,
  verifies rollback behavior, `foreign_key_check`, foreign keys on every
  connection, WAL/busy timeout, and concurrent access without raw lock errors.
- **Evidence:** Test-first run of
  `python -m pytest --no-cov -q tests\integration\test_schema_migrations.py`
  produced 11 passed / 1 failed; failing migration leaked its DDL table.
  After fix, `python -m pytest --no-cov -q tests\integration\test_schema_migrations.py tests\integration\test_bootstrap.py`
  passed (17 tests) on Windows; `python -m ruff check app\infrastructure\sqlite\migrations.py tests\integration\test_schema_migrations.py`
  and `git -c core.whitespace=cr-at-eol --no-pager diff --check` passed.
- **Adjacent Gate 2 note:** `tests\integration\test_gate2_realignment.py`
  was 8 passed / 4 failed in configuration/API expectations outside WP 2.1.

### KB-G0-2 — Centralize and map API error codes

- **WBS/Docs:** WP 5.1; Document 10; realignment G0-3
- **Priority:** P1 · **Owner:** Copilot agent G0-2 · **Updated:** 2026-11-07
- **Acceptance:** documented errors (including CSRF, step-up, world conflict,
  version conflict, storage guard, and cancellation) map to their required
  HTTP status and response envelope; API tests assert the mappings.
- **Evidence:** centralized catalog and compatibility codes implemented in
  `app/web/errors.py`; `python -m pytest --no-cov -q
  tests/unit/test_web_errors.py` passed (15 tests), with Ruff passing for the
  changed implementation and tests. Cancellation maps to `OP_NOT_CANCELLABLE`;
  the missing cancellation route/service is tracked by KB-G5-9.

### KB-G0-6 — Reconcile stale audit and pseudocode with governing docs

- **WBS/Docs:** realignment G0-6; all `docs/gate*_pseudocode.txt`
- **Priority:** P2 · **Owner:** Copilot agent G0-6 · **Updated:** 2026-11-07
- **Acceptance:** root layout and numbered-document precedence are reflected
  in the realignment notes; gate pseudocode no longer contradicts governing
  numbered documents.
- **Evidence:** all five gate pseudocode files and `docs/realignment.txt`
  now distinguish normative contracts, current implementation, and
  superseded historical material. CRLF-aware whitespace check passed.

### KB-D12-1 — Match remaining Document 12 top-level entries

- **WBS/Docs:** Document 12 §2
- **Priority:** P2 · **Owner:** Copilot agent D12-1 · **Updated:** 2026-11-07
- **Acceptance:** resolve root asset paths without duplicate assets, document
  the existing Prototypes casing/layout, and add a repository-structure test.
- **Evidence:** Document 12 records the `app/shell/static/` and
  `app/shell/templates/` resolution and current Prototypes layout;
  `tests/unit/test_repository_structure_contract.py`: 2 passed; Ruff passed.

### KB-G5-WORLD-LIST — Implement the canonical world-list API and shell workflow

- **WBS/Docs:** Document 10 Worlds list; Document 5 World management; child
  slice of KB-G5-5 and KB-G5-6 (both parent cards remain open).
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Acceptance:** authenticated `GET /api/worlds` supports documented world
  filters, deleted-row opt-in, and pagination; the World Management shell
  page renders and queries that listing without full-page navigation.
- **Evidence:** focused world-list integration tests passed (2); browser
  regression suite passed (2). The ten-tab stream-sharing regression remained
  green.

### KB-G5-1 — Complete authenticated, CSRF-safe API foundations

- **WBS:** WP 5.1; realignment G5-1/G5-6/G5-7
- **Priority:** P0 · **Owner:** Copilot agent G5-1 · **Updated:** 2026-11-07
- **Depends on:** KB-G0-2 (Done)
- **Acceptance:** every implemented mutating route enforces session, CSRF,
  role, and step-up requirements from Document 10; tests cover missing/invalid
  tokens, expiry, and authorization failures.
- **Evidence:** middleware enforces session and session-bound CSRF checks on
  mutations, admin authorization for implemented protected routes, and
  step-up for stop/kill/EULA/runtime-config actions. The full
  `tests\integration\test_gate5_acceptance.py` suite passed (18 tests) on
  Windows; Ruff passed for middleware and acceptance tests.

### KB-G0-3 — Make startup and worker lifecycle failures visible

- **WBS/Docs:** WP 3.2–3.3; Document 12 §5; realignment G0-2/G3-4/G3-5
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** —
- **Acceptance:** reconciliation errors surface in health; workers have explicit
  lifecycle; app/store closure cannot leave workers using a closed database.
- **Evidence:** startup reconciliation health is surfaced by `/api/health`;
  workers are stopped and joined before store close. The combined
  runtime-reconciliation, Gate 3 worker/scheduler, and presentation-health
  selectors passed (17 passed, 1 long benchmark deselected); Ruff passed for
  the health route and reconciliation/lifecycle services.

### KB-G0-4 — Repair full-suite smoke failures

- **WBS/Docs:** Document 11; current full-suite baseline
- **Priority:** P0 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** —
- **Acceptance:** invalid enum/FK fixtures are repaired; diagnostics expectation
  is deliberate; focused tests and full suite pass without weakened assertions.
- **Evidence:** smoke tests passed (6); broad suite passed (409 passed,
  3 Windows symlink skips, 1 long benchmark deselected) with `--no-cov`.

### KB-G1-4 — Align process handle contract across adapters

- **WBS:** WP 1.1–1.3; realignment G1-4
- **Priority:** P2 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** —
- **Acceptance:** process identity/group fields align across adapters; PID
  reuse guards, world survival, and conformance remain intact.
- **Evidence:** native Windows and fake-adapter conformance plus process
  contract tests passed (36 tests) on Windows. The POSIX adapter was not
  exercised on this host; cross-platform C1–C14 evidence remains tracked by
  KB-G1-6.

### KB-G0-1 — Enforce dependency boundaries through ports and repositories

- **WBS/Docs:** Document 12 §4–5; realignment G0-1
- **Priority:** P0 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** —
- **Acceptance:** services avoid concrete platform/process adapters; persistence
  access is behind ports/adapters; bootstrap is the composition root; configured
  import contracts pass and test/CI invokes them.
- **Evidence:** all application services now use port/service interfaces rather
  than importing concrete infrastructure or platform modules. The dependency
  boundary tests and scheduler/smoke regressions passed (19 tests); the broad
  suite passed (409 passed, 3 Windows symlink skips, 1 long benchmark
  deselected). Scoped Ruff and isolated strict mypy checks passed. Existing
  SQL-heavy paths remain behind the transaction-aware persistence port as
  allowed by Documents 8 and 12.

### KB-G1-1 — Inject process and Minecraft capabilities through ports

- **WBS:** WP 1.1, WP 1.5; realignment G1-1
- **Priority:** P0 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G0-1 (Done)
- **Acceptance:** `WorldsService` and save coordination depend on ports, not
  concrete Minecraft infrastructure; bootstrap supplies implementations;
  port and composition tests pass.
- **Evidence:** `WorldsService` and save coordination have no concrete
  infrastructure/platform imports; bootstrap injects process, Minecraft, and
  RCON implementations. Port/readiness/Java/bootstrap/world-lifecycle tests
  passed (69) on Windows; scoped Ruff passed.

### KB-G1-3 — Enforce Minecraft readiness and EULA product flow

- **WBS:** WP 1.5; realignment G1-3
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G1-1 (Done)
- **Acceptance:** each server type reaches `running` only at its highest
  applicable readiness level; EULA acceptance has one audited HTTP flow and
  cannot be bypassed by start or external file changes.
- **Evidence:** `WorldsService` now persists EULA consent as a terminal
  `ConfigEdit` Operation (`entity=eula`) and keeps the explicit acceptance
  audit. Tests cover each server-type readiness target, step-up/API audit,
  operation details, and rejection of unaudited external EULA edits.
  `python -m pytest --no-cov -q` for Gate 1 contracts, readiness, Java,
  bootstrap, and world lifecycle passed (73 tests) on Windows; scoped Ruff
  passed.

### KB-G1-2 — Complete durable, configurable process logging

- **WBS:** WP 1.4 · **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** —
- **Acceptance:** `VERBOSE_LOGGING=false` filters debug/raw output without
  breaking readiness; durable per-session and channel logs persist alongside
  bounded in-memory tailing; default is documented in `.env.example`.
- **Evidence:** process markers bypass debug filtering; tail limits count UTF-8
  bytes including truncation sentinels.
  `python -m pytest --no-cov -q --basetemp=dev_artifacts/scratch/verify-g1-logging
  tests/unit/test_gate1_contracts.py tests/unit/test_readiness_rcon_props.py
  tests/unit/test_java_gate.py tests/integration/test_worlds_lifecycle.py
  tests/adapters/test_conformance.py` passed (97) on Windows; scoped Ruff and
  diff checks passed.

### KB-G3-1 — Keep operation progress in memory between milestones

- **WBS:** WP 3.1; realignment G3-1
- **Priority:** P0 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G0-1 (Done)
- **Acceptance:** progress ticks are published to realtime subscribers without
  per-tick operation writes; only documented milestones are persisted;
  reconnect/snapshot and operation-read behavior remain correct.
- **Evidence:** progress/checkpoint/replay and audit/notification contracts
  passed in `tests\integration\test_gate3_operation_engine_behavior.py` and
  `tests\integration\test_gate3_audit_notification_pipeline.py` (66 tests) on
  Windows. The tests verify in-memory progress, no per-tick operation writes,
  stream replay, milestone persistence, and correct terminal reads.

### KB-G3-2 — Implement the Document 9 conflict matrix

- **WBS:** WP 3.1; realignment G3-2
- **Priority:** P0 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G3-1 (Done)
- **Acceptance:** parametrized tests cover each requested-operation /
  in-flight-operation cell, including single-flight queueing, duplicate Start
  handling, rejection rules, Kill superseding Stop, and Restore/Delete
  precedence.
- **Evidence:** Added queued DeleteWorld coverage for every requested
  lock-operation type. The expanded conflict matrix plus Restore/Delete and
  terminal-audit regression suites passed (73 tests) on Windows; Ruff passed.

### KB-G3-3 — Audit each terminal operation exactly once

- **WBS:** WP 3.4; realignment G3-3
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G3-1 (Done)
- **Acceptance:** terminal success/failure/cancellation writes exactly the
  documented audit event; intermediate progress writes none; auth/config
  audit behavior remains intact.
- **Evidence:** terminal-transition matrix, intermediate-no-audit, auth audit
  catalog, and ConfigEdit operation/conflict tests passed (73 operation/audit
  tests plus 2 config tests) on Windows. Ruff passed for the operation engine.

### KB-G3-4 — Verify crash-safe runtime reconciliation and supervisor behavior

- **WBS:** WP 3.2; realignment G3-4
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G1-1, KB-G0-3
- **Acceptance:** after manager restart a live server is re-attached rather
  than restarted; failed starts reach the documented timeout state; reconcile
  errors are visible; process crash produces the expected operation/audit/
  notification.
- **Evidence:** `python -m pytest tests/integration/test_worlds_lifecycle.py
  tests/integration/test_runtime_reconciliation.py
  tests/integration/test_phase5_presentation_hardening.py
  tests/adapters/test_conformance.py -k "start_timeout_terminalizes_operation_and_closes_session
  or reconcile_records_crash_operation_audit_and_notification or
  reconciliation_failure_is_health_visible_and_reraised or
  startup_reconciliation_failure_blocks_app_and_worker_start or
  c11_boot_reconciliation" --no-cov` passed (6 tests) on Windows, including
  native/fake process reattachment. The broad suite passed (420 passed,
  3 skipped, 1 deselected); skipped symlink checks require unavailable Windows
  privilege, and the long performance smoke remains excluded.

### KB-G3-5 — Run the scheduler automatically and verify missed-run behavior

- **WBS:** WP 3.3; realignment G3-5
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G0-3, KB-G3-2
- **Acceptance:** app lifecycle starts/stops the 30-second scheduler; due work
  dispatches when clear; conflicts create durable missed-run records and are
  never auto-replayed.
- **Evidence:** `python -m pytest --no-cov -q
  tests/integration/test_scheduler_service.py
  tests/integration/test_gate3_runtime_scheduler.py` passed (10 tests) on
  Windows, covering automatic worker startup/shutdown, 30-second cadence,
  one-time dispatch, and durable non-replayed conflict records. Scoped Ruff
  passed. The broad suite passed (420 passed, 3 skipped, 1 deselected).

### KB-G5-2 — Make operation routes durably asynchronous

- **WBS:** WP 5.1; realignment G5-2/G5-3
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G3-1, KB-G3-2
- **Acceptance:** mutating routes return promptly with the documented 202
  operation envelope and `meta.op_id`; work is durable/restart-safe and
  idempotency/conflict behavior is tested.
- **Evidence:** lifecycle routes persist `Queued` operations and return
  operation/idempotency metadata; the atomic dispatcher resumes queued work
  after container rebuild. Idempotent replay, single-claim, and queue recovery
  tests passed. Focused API/runtime verification passed (82 tests); the broad
  suite passed (423 passed, 3 skipped, 1 deselected) on Windows. Scoped Ruff
  and mypy for the operation/lifecycle services passed.

### KB-G5-7 — Verify authenticated SSE lifecycle and complete stream topics

- **WBS:** WP 5.2; realignment G5-5/G5-13
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G5-1, KB-G3-1
- **Acceptance:** reconnect replay, snapshot, auth expiry, all documented
  topics, subscriber cleanup, and 10-tab single-EventSource/failover behavior
  pass server and browser tests.
- **Evidence:** `python -m pytest --no-cov -q
  --basetemp=dev_artifacts/scratch/verify-g57-rerun
  tests/integration/test_gate3_operation_engine_behavior.py
  tests/integration/test_gate5_acceptance.py -k
  "progress_is_cached or sse or stream"` passed (8), covering replay, complete
  snapshots, auth expiry, cleanup on close, all documented topic names, and
  orderly shutdown. `node --test tests/browser/test_gate5_browser.test.cjs`
  passed (2), covering 10-tab connection sharing/failover, topic forwarding,
  auth expiry/recovery, and manager shutdown. Scoped Ruff and diff checks passed.

### KB-G2-DOMAIN — Verify domain model and transition coverage

- **WBS:** WP 2.2 · **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** —
- **Acceptance:** domain entities, events, invariants, deletion tiers, and
  lifecycle guards are pure of framework/persistence imports; unit tests cover
  every documented world-state transition and invariant.
- **Evidence:** lifecycle transition intent/timestamp validation and invalid
  input preservation tests are complete.
  `python -m pytest --no-cov -q --basetemp=dev_artifacts/scratch/verify-g2-domain-final
  tests/unit/domain tests/integration/test_gate2_realignment.py` passed (77).
  Scoped Ruff, focused mypy, and diff checks passed.

### KB-G2-2 — Implement effective configuration resolution

- **WBS:** WP 2.4; realignment G2-2
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G2-DOMAIN (Done)
- **Acceptance:** `ConfigurationService` resolves global settings, world
  overrides, and effective values; tests cover both global fallback and
  world-specific override without callers reading singleton settings directly.
- **Evidence:** `python -m pytest --no-cov -q
  --basetemp=dev_artifacts/scratch/verify-g2-config-final
  tests/integration/test_gate2_realignment.py` passed (15); scoped Ruff and
  diff checks passed.

### KB-G2-3 — Route ConfigEdit through durable operations and map conflicts

- **WBS:** WP 2.4; realignment G2-3
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G0-2, KB-G2-2, KB-G3-1, KB-G3-3 (Done)
- **Acceptance:** stale versions return the documented
  `CONFIG_VERSION_CONFLICT`; ConfigEdit is persisted as an Operation with
  terminal audit behavior; integration test covers success and conflict.
- **Evidence:** global and world-settings PATCH routes create ConfigEdit
  Operations and return `meta.op_id`; stale-version conflicts create neither
  an operation nor an audit row. Focused Gate 2, Gate 3 audit, and
  operation-engine suites passed (94); scoped Ruff and mypy passed for the
  configuration service, route, and response helpers.

## Review

### KB-G5-5 — Implement world CRUD, EULA, files, and logs APIs

- **WBS:** WP 5.1; realignment G5-7/G5-10
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G1-3, KB-G5-1, KB-G5-2 (Done)
- **Acceptance:** Document 10 world create/update/delete, runtime config,
  EULA, file management, and log routes enforce their documented guards;
  Operation-creating writes return durable documented operation envelopes.
- **Evidence:** the focused world-management, Gate 5 auth/async, and lifecycle
  suites passed (37); scoped Ruff, py_compile, and diff checks passed. Coverage
  includes guarded CRUD/runtime/EULA/files/log access, queued/idempotent world
  changes, FileEdit recovery, and ConfigEdit EULA response metadata.

### KB-G5-4 — Implement settings, schedules, runtime, and administration APIs

- **WBS:** WP 5.1; realignment G5-9/G5-10
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G5-1, KB-G5-2, KB-G2-3, KB-G3-5 (Done)
- **Acceptance:** Document 10 settings, schedules/missed-runs, templates,
  Java runtimes, admin, notifications, and audit routes are implemented and
  covered by authorized success/error tests.
- **Evidence:** `tests/integration/test_document10_catalog_apis.py`,
  `tests/integration/test_schema_migrations.py`, and
  `tests/integration/test_scheduler_service.py` passed (25); scoped Ruff,
  compile, and diff checks passed. Schedule, missed-run, template, Java
  runtime, user/role/permission/device, notification, and audit routes have
  authorized integration coverage. Manager backup/restore/restart/update/
  rollback endpoints are registered but return `NOT_IMPLEMENTED` because the
  application has no manager lifecycle service; implementation is tracked by
  KB-G5-8.

### KB-G4-VERIFY — Close Gate 4 against its exact acceptance checks

- **WBS/Docs:** WP 4.1–4.4; Documents 6, 8, 9, 11, and 14.
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Acceptance:** native archive integrity and failure cleanup; RCON save
  flush/freshness/save-on; staged restore with mandatory compensation and
  suspect marking; cleanup age/count floors and blast-radius cap; three sync
  attempts with 30/60-second waits; safe filesystem containment and sizing.
- **Evidence:** `python -m pytest --no-cov -q
  --basetemp=dev_artifacts/scratch/verify-g4-final` with the focused Gate 4 suite
  (`tests/unit/test_dependency_boundaries.py`,
  `tests/unit/test_backup_engine.py`, `tests/unit/test_filesystem.py`,
  `tests/integration/test_cleanup_service.py`,
  `tests/integration/test_sync_gate4.py`,
  `tests/integration/test_gate4_acceptance.py`,
  `tests/integration/test_phase4_backup_coordination.py`,
  `tests/integration/test_phase4_operational_subsystems.py`,
  `tests/integration/test_restore_acceptance.py`) passed (66 passed,
  3 skipped) on Windows. Scoped Ruff and diff checks passed. Three symlink
  checks remain unverified because Windows denied symlink creation
  (`WinError 1314`); POSIX and live RCON/NAS integration were not run.

## To Do

### KB-G0-5 — Restore green repository static gates

- **WBS/Docs:** Document 12 §8
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G0-1
- **Acceptance:** Ruff, Black, isort, mypy, and import-linter pass on the
  configured project scope; add those commands to the documented/CI gate.
  Avoid broad formatting churn without coordinating it as a dedicated slice.

### KB-G5-3 — Implement backup, restore, cleanup, and sync API catalog

- **WBS:** WP 5.1; realignment G5-8/G5-11
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G5-1, KB-G5-2, KB-G4-VERIFY
- **Acceptance:** Document 10 routes exist with authorization, request/
  response schemas, error mapping, and tests for backup, restore/rollback,
  cleanup preview/execute, and sync.

### KB-G5-6 — Complete real workflows for the 17 shell modules

- **WBS:** WP 5.3; realignment G5-12
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G5-3, KB-G5-4, KB-G5-5
- **Acceptance:** modules are functional workflows, not scaffold fragments;
  manager/world context switching works; navigation stays in-place and obeys
  Document 4 tokens and 40px control geometry.

### KB-G1-MINECRAFT — Run the real Minecraft adapter integration spike

- **WBS/Docs:** WP 1.5; Documents 13 §5 and 14 §13
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G1-1, KB-G1-3 (Done)
- **Acceptance:** headless Vanilla, Paper, Fabric, and Forge runs verify
  pre-spawn Java/EULA gating, declared readiness signals, RCON/save behavior
  where supported, shutdown, and startup-failure classification. Record
  server/JDK versions and results; do not treat fake-server tests as live
  adapter evidence.

### KB-G5-8 — Implement manager lifecycle operations

- **WBS/Docs:** WP 5.1; Documents 5 Manager Maintenance, 6 Manager lifecycle,
  8, and 10
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G5-2, KB-G5-3, KB-G5-4
- **Acceptance:** replace `NOT_IMPLEMENTED` for manager/server restart,
  software update/rollback, and manager backup/restore with authorized,
  durable Operation workflows, recovery behavior, audit records, and
  integration coverage. Coordinate route/catalog ownership with KB-G5-3.

### KB-G5-9 — Add cancellable-operation API behavior

- **WBS/Docs:** WP 5.1; Documents 9 and 10 Operations
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G5-1, KB-G5-2 (Done)
- **Acceptance:** implement `POST /api/operations/{op_id}/cancel` for only
  cancellable operation types in `Queued` or `Validating`, enforce documented
  authorization and idempotency, return the canonical conflict/error
  envelopes otherwise, and verify terminal audit behavior.

### KB-G5-10 — Verify metrics cadence and streaming deployment behavior

- **WBS/Docs:** WP 5.2; Documents 10 MetricsCadence and 11 §§1.2, 4.1
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G5-7 (Done)
- **Acceptance:** verify `/stream/metrics`, zero-client/all-worlds-off
  suppression, 15-second cached refresh, 1Hz fan-out while subscribed,
  heartbeat and slow-client behavior, and no per-client recomputation.
  Exercise the supported deployment proxy with buffering disabled and record
  reconnect/stream results; add or fix tests for uncovered behavior.

### KB-G5-11 — Add the dedicated security acceptance suite

- **WBS/Docs:** Document 11 §§1.2, 2, and 4.3; Documents 7 and 8 §9
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G5-1, KB-G5-4, KB-G5-5
- **Acceptance:** run a dedicated security suite/CI job for direct-route authz,
  privilege escalation, CSRF and step-up expiry, throttling/lockout,
  Argon2id and session rotation, encrypted secrets and response redaction,
  security headers/non-loopback cookie behavior, last-Superadmin protection,
  and audit immutability. Fix gaps without weakening assertions.

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

### KB-G5-API-CONTRACT — Audit full Document 10 contract parity

- **WBS/Docs:** Document 10 route catalog, envelope, auth, and error contracts
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G5-3, KB-G5-4, KB-G5-5
- **Acceptance:** compare every documented API route against registration,
  authorization, request/response schema, status, envelope, and error mapping;
  record explicit `NOT_IMPLEMENTED` exceptions and add contract-level tests
  for uncovered behavior. This is a final parity review, not a substitute for
  implementing the route-catalog cards.
