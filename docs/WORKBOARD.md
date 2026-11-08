# MCManager Workboard

This is the shared, repository-tracked Kanban board for implementation,
verification, and release status. Read it before taking a task; update the
card here so a new agent can resume without relying on chat history. The board
tracks implementation and verification, not just code-writing.

## Board rules

1. Keep one bounded deliverable per card. `KB-` identifiers are board-local
   stable references; WBS and numbered-document references in each card are
   source references. Do not renumber or reuse board IDs.
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
6. Write audit findings in `docs/audit.md` first. Transfer every actionable
   finding into a bounded card in this board and verify the transfer checklist
   there; this board is the source of truth for task status and evidence.
   When a contract changes, update the governing numbered document first,
   then its pseudocode and the audit record as needed. Numbered product
   documents take precedence over WBS sketches and audit notes.
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

| Area | Implemented and verified scope | Remaining acceptance / release state |
|---|---|---|
| Repository layout | Root `app/` and `migrations/`; managed world data under `app/data/worlds/` | Layout work is Done; remaining Document 12 structure differences are tracked separately |
| Gate 1 / WP 1.1–1.6 | Process ports, Windows/fake conformance, readiness, EULA flow, and durable logging | Partial: the conformance workflow now targets Windows and Ubuntu, but hosted results and real-server spike evidence remain |
| Gate 2 / WP 2.1–2.4 | WBS Gate 2 criterion verified: clean foreign-key check and migration rollback; domain, settings, and ConfigEdit slices also pass focused tests | Gate criterion passed on Windows; Document 6 model inventory and broader release acceptance remain |
| Gate 3 / WP 3.1–3.4 | WBS Gate 3 criterion verified: runtime re-attachment and derived-lock conflict behavior pass alongside operation, audit, and scheduler suites | Gate criterion passed on Windows; full release acceptance remains |
| Gate 4 / WP 4.1–4.4 | WBS Gate 4 pre-restore backup and compensating rollback criterion verified with focused backup/restore/cleanup/sync/filesystem suites | Gate criterion passed on Windows; three symlink checks, POSIX, and live RCON/NAS acceptance remain |
| Gate 5 / WP 5.1–5.3 | Auth, selected world/admin APIs, backup/restore/backup-cleanup/sync catalog, cancellation, SSE sharing, and world-list workflow | Partial: stale-world/log cleanup policy, full shell workflows, manager lifecycle endpoints, hosted security job, and supported-proxy validation remain |

## Implementation status

**Last recorded verification:** 2026-11-08, Windows / Python 3.13.14. This
summary is a dated evidence snapshot, not a claim that every gate or the
product is release-ready.

MCManager has a tested application foundation and substantial control-plane
functionality. It is an **early functional prototype, not yet an
operator-ready MVP**. The principal product gaps are stale-world/log cleanup
policy and workflows, complete shell workflows, manager lifecycle operations,
and cross-platform, deployment, and performance release acceptance.

### Latest recorded verification

- `python -m pytest --no-cov -q -k "not performance_acceptance_smoke"`:
  **448 passed, 3 skipped, 1 deselected**. The skips require Windows symlink
  privileges unavailable on the recorded host; the deselected smoke is the
  long performance test.
- `node --test tests\browser\test_gate5_browser.test.cjs`: **2 passed**,
  including 10-tab stream sharing/failover, event forwarding, auth recovery,
  and manager shutdown.
- Dedicated security acceptance modules: **53 passed** locally; hosted
  GitHub Actions execution remains pending.
- Focused Gate 5 API verification: **47 passed** across
  `test_gate5_acceptance.py`, `test_document10_catalog_apis.py`, and
  `test_world_management_api.py`; Gate 5 browser regression: **2 passed**.
  These verify existing API/browser behavior and do not close the manager
  lifecycle, shell workflow, cleanup-policy, hosted-security, or proxy gaps.
- Metrics/control-plane/presentation/Gate 5 integration: **42 passed,
  1 deselected**; the deselected test is the long performance smoke.
- Scoped Ruff, compilation, and focused mypy checks passed for the recorded
  feature slices; this is not a repository-wide static-gate pass.
- Repository-wide static baselines are historical and inconsistent: one
  recorded snapshot reports Ruff 46, Black 76 files, isort 9 files, and mypy
  217 errors; an earlier board entry reports Ruff 52, Black 74 files, and
  isort 14 files. The latest recorded status snapshot says `lint-imports` was
  unavailable, while an earlier entry reports broken import boundaries. These
  commands were not rerun during this documentation consolidation; none should be
  presented as a fresh result.
- POSIX conformance, live Minecraft/RCON/NAS integration, and calibrated
  performance acceptance have not been verified. The Windows symlink skips
  are an environment limitation, not passing acceptance.
- Focused Gate 2 verification on 2026-11-08: domain, Gate 2 realignment, and
  migration suites passed (91) on Windows / Python 3.13.14.
- Focused Gate 3 verification on 2026-11-08: operation, conflict, operation
  engine, audit/notification, runtime/scheduler, and reconciliation suites
  passed (94) on Windows / Python 3.13.14.
- Focused Gate 4 verification on 2026-11-08: backup, restore, cleanup, sync,
  and filesystem suites passed (68), with 3 Windows symlink-privilege skips,
  on Windows / Python 3.13.14.

### Remaining product work

- Decide and implement safe stale-world/log cleanup policy and workflows
  (KB-G5-CLEANUP-POLICY, KB-G5-3).
- Complete real workflows for the 17 shell modules (KB-G5-6).
- Implement manager restart/update/rollback and manager backup/restore
  operations (KB-G5-8).
- Run C1–C14 on a supported POSIX host and the real Vanilla/Paper/Fabric/Forge
  integration spike (KB-G1-6, KB-G1-MINECRAFT).
- Run the dedicated security job on its hosted Ubuntu/Python matrix and verify
  the supported streaming proxy (KB-G5-11, KB-G5-10).
- Restore repository-wide static gates (KB-G0-5) and complete calibrated
  performance acceptance when a documented reference host is available
  (KB-PERF-01).
- Complete full Document 10 API contract parity (KB-G5-API-CONTRACT).
- Complete Document 8/9 contract acceptance and Document 11 testing/quality
  coverage work (KB-G8-CONTRACT, KB-G9-CONTRACT, KB-D11-TEST-PYRAMID,
  KB-D11-COVERAGE, KB-D11-ISO-25010).
- Reconcile status labels, API/auth claims, and test evidence provenance in
  this workboard (KB-DOC-EVIDENCE-QUALITY).
- Reconcile the WBS's obsolete file paths and fake-server flag names while
  retaining its work-package/dependency structure (KB-DOC-WBS).

### Run locally

Run the app from the repository root (manager state and Minecraft
installations are kept under ignored `app/data/` directories):

```powershell
python -m flask --app "app:create_app(database_path='app/data/manager.db', keyfile_path='app/data/secrets.key', migrations_dir='migrations')" run --host 127.0.0.1 --port 5000
```

Application startup is not evidence that operator workflows or release gates
are complete.

## Tracked implementation workstreams

These group implementation slices under parent acceptance cards; they are not
gate-completion claims. Parent cards remain open until all acceptance evidence
is integrated and reviewed.

| Workstream | Parent card(s) | Scope |
|---|---|---|
| Gate 1 process adapters | KB-G1-4, KB-G1-6 | Windows/fake process-handle contract completed; Windows/Ubuntu hosted conformance results remain pending |
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

### KB-G5-9 — Add cancellable-operation API behavior

- **WBS/Docs:** WP 5.1; Documents 9 and 10 Operations
- **Priority:** P1 · **Owner:** Copilot agent Sync-Cancel · **Updated:** 2026-11-07
- **Depends on:** KB-G5-1, KB-G5-2 (Done)
- **Acceptance:** implement `POST /api/operations/{op_id}/cancel` for only
  cancellable operation types in `Queued` or `Validating` (Sync may also be
  cancelled while `Running` per Document 8), enforce documented authorization
  and idempotency, return the canonical conflict/error envelopes otherwise,
  and verify terminal audit behavior.
- **Evidence:** `python -m pytest --no-cov -q
  tests/integration/test_world_management_api.py -k cancel` passed (10 passed,
  2 deselected); the combined Sync/cancellation/metrics/slow-client unit set
  passed (23). Scoped Ruff passed. Coverage includes cancellable queued types,
  Running Sync cooperative cancellation, partial NAS upload removal, one
  terminal audit, terminal failed SyncRecord/failed_transient attempt, and no
  retry after cancellation.

### KB-LAYOUT-01 — Put application and migrations at repository root

- **WBS/Docs:** Document 12 §2; the prior packaging decision was superseded by
  the explicit root-layout direction.
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
- **Latest verification:** `python -m pytest --no-cov -q
  tests\unit\domain tests\integration\test_gate2_realignment.py
  tests\integration\test_schema_migrations.py` passed (91) on Windows /
  Python 3.13.14 on 2026-11-08, including clean `foreign_key_check` and
  failed-migration rollback assertions.
- **Adjacent Gate 2 note:** `tests\integration\test_gate2_realignment.py`
  was 8 passed / 4 failed in configuration/API expectations outside WP 2.1.

### KB-G0-2 — Centralize and map API error codes

- **WBS/Docs:** WP 5.1; Document 10
- **Priority:** P1 · **Owner:** Copilot agent G0-2 · **Updated:** 2026-11-07
- **Acceptance:** documented errors (including CSRF, step-up, world conflict,
  version conflict, storage guard, and cancellation) map to their required
  HTTP status and response envelope; API tests assert the mappings.
- **Evidence:** centralized catalog and compatibility codes implemented in
  `app/web/errors.py`; `python -m pytest --no-cov -q
  tests/unit/test_web_errors.py` passed (15 tests), with Ruff passing for the
  changed implementation and tests. Cancellation maps to
  `OP_NOT_CANCELLABLE`; the route and service are implemented and tracked by
  KB-G5-9.

### KB-G0-6 — Reconcile stale audit and pseudocode with governing docs

- **WBS/Docs:** Documents 4–14; all `docs/gate*_pseudocode.txt`
- **Priority:** P2 · **Owner:** Copilot agent G0-6 · **Updated:** 2026-11-07
- **Acceptance:** root layout and numbered-document precedence are reflected
  in current project status; gate pseudocode no longer contradicts governing
  numbered documents.
- **Evidence:** the five pseudocode files were checked against the numbered
  documents and now distinguish governing contracts/current addenda from
  historical examples. This records the reconciliation performed on
  2026-11-07; it does not assert that every historical code sample matches
  current source. The obsolete planning/status documents have since been
  consolidated into this workboard.

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

- **WBS:** WP 5.1
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

- **WBS/Docs:** WP 3.2–3.3; Document 12 §5
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

- **WBS:** WP 1.1–1.3
- **Priority:** P2 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** —
- **Acceptance:** process identity/group fields align across adapters; PID
  reuse guards, world survival, and conformance remain intact.
- **Evidence:** native Windows and fake-adapter conformance plus process
  contract tests passed (36 tests) on Windows. The POSIX adapter was not
  exercised on this host; cross-platform C1–C14 evidence remains tracked by
  KB-G1-6.

### KB-G0-1 — Enforce dependency boundaries through ports and repositories

- **WBS/Docs:** Document 12 §4–5
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

- **WBS:** WP 1.1, WP 1.5
- **Priority:** P0 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G0-1 (Done)
- **Acceptance:** `WorldsService` and save coordination depend on ports, not
  concrete Minecraft infrastructure; bootstrap supplies implementations;
  port and composition tests pass.
- **Evidence:** `WorldsService` and save coordination have no concrete
  infrastructure/platform imports; bootstrap injects process, Minecraft, and
  RCON implementations. Port/readiness/Java/bootstrap/world-lifecycle tests
  passed (69) on Windows; scoped Ruff passed.

### KB-G5-5 — Implement world CRUD, EULA, files, and logs APIs

- **WBS:** WP 5.1
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G1-3, KB-G5-1, KB-G5-2 (Done)
- **Acceptance:** Document 10 world create/update/delete, runtime config,
  EULA, file management, and log routes enforce their documented guards;
  Operation-creating writes return durable documented operation envelopes.
- **Evidence:** the focused world-management, Gate 5 auth/async, and lifecycle
  suites passed (37); scoped Ruff, py_compile, and diff checks passed. Coverage
  includes guarded CRUD/runtime/EULA/files/log access, queued/idempotent world
  changes, FileEdit recovery, and ConfigEdit EULA response metadata. Follow-up
  EULA idempotency replay tests passed (2) and scoped Ruff passed after adding
  same-key operation replay and single-acceptance audit assertions.

### KB-G5-4 — Implement settings, schedules, runtime, and administration APIs

- **WBS:** WP 5.1
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G5-1, KB-G5-2, KB-G2-3, KB-G3-5 (Done)
- **Acceptance:** Document 10 settings, schedules/missed-runs, templates,
  Java runtimes, admin, notifications, and audit routes are implemented and
  covered by authorized success/error tests.
- **Evidence:** `tests/integration/test_document10_catalog_apis.py`,
  `tests/integration/test_schema_migrations.py`, and
  `tests/integration/test_scheduler_service.py` passed (25); scoped Ruff,
  compile, and diff checks passed. Manager backup/restore/restart/update/
  rollback endpoints are a separate KB-G5-8 deliverable.

### KB-DOC-STATUS — Reconcile current status and verification evidence

- **WBS/Docs:** this workboard and gate reconciliation headers
- **Priority:** P2 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G2-DOMAIN, KB-G2-MIGRATION, KB-G4-VERIFY (Done)
- **Acceptance:** recorded test commands/counts match a dated fresh run; gate
  claims agree with verified acceptance; obsolete packaging notes and
  contradictions are explicitly superseded rather than silently retained.
- **Evidence:** implementation status and remaining gaps are recorded in this
  board. Historical test/static results are date-qualified and not presented
  as fresh runs. POSIX, hosted CI, proxy behavior, and calibrated performance
  remain open.

### KB-G1-3 — Enforce Minecraft readiness and EULA product flow

- **WBS:** WP 1.5
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

- **WBS:** WP 3.1
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

- **WBS:** WP 3.1
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

- **WBS:** WP 3.4
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G3-1 (Done)
- **Acceptance:** terminal success/failure/cancellation writes exactly the
  documented audit event; intermediate progress writes none; auth/config
  audit behavior remains intact.
- **Evidence:** terminal-transition matrix, intermediate-no-audit, auth audit
  catalog, and ConfigEdit operation/conflict tests passed (73 operation/audit
  tests plus 2 config tests) on Windows. Ruff passed for the operation engine.

### KB-G3-4 — Verify crash-safe runtime reconciliation and supervisor behavior

- **WBS:** WP 3.2
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
- **Latest verification:** the combined Gate 3 operation, conflict,
  operation-engine, audit/notification, runtime/scheduler, and reconciliation
  suites passed (94) on Windows / Python 3.13.14 on 2026-11-08. Two stale
  worker-roster assertions were updated to include the catalog, sync, and
  metrics workers already started by the app factory.

### KB-G3-5 — Run the scheduler automatically and verify missed-run behavior

- **WBS:** WP 3.3
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

- **WBS:** WP 5.1
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

- **WBS:** WP 5.2
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
- **Acceptance:** the implemented `WorldInstance` entity, events, invariants,
  deletion tiers, and lifecycle guards are pure of framework/persistence
  imports; unit tests cover every documented world-state transition and
  invariant. This card does not claim that every conceptual entity in
  Document 6 is represented by a domain entity class.
- **Evidence:** lifecycle transition intent/timestamp validation and invalid
  input preservation tests are complete.
  `python -m pytest --no-cov -q --basetemp=dev_artifacts/scratch/verify-g2-domain-final
  tests/unit/domain tests/integration/test_gate2_realignment.py` passed (77).
  Scoped Ruff, focused mypy, and diff checks passed.

### KB-G2-2 — Implement effective configuration resolution

- **WBS:** WP 2.4
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

- **WBS:** WP 2.4
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

### KB-G5-3 — Implement backup, restore, cleanup, and sync API catalog

- **WBS:** WP 5.1
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G5-1, KB-G5-2, KB-G4-VERIFY
- **Status:** Review
- **Acceptance:** Document 10 routes exist with authorization, request/
  response schemas, error mapping, and tests for backup, restore/rollback,
  cleanup preview/execute, and sync.
- **Evidence:** `tests/integration/test_backup_catalog_api.py` covers durable
  backup deletion, idempotent replay, retention rejection, deletion/audit, and
  Superadmin + step-up force guards alongside the other catalog workflows.
  The focused deletion test passed; all 4 module tests passed before the module
  command exited on the global 80% coverage gate (44.46%). Scoped Ruff passed
  on changed Python files. Backup-scope cleanup preview/execute is covered.
- **Remaining:** Document 10 also defines `stale_worlds` and `logs` cleanup
  scopes, but the route currently returns `CLEANUP_SCOPE_UNSUPPORTED` for both.
  KB-G5-CLEANUP-POLICY must resolve their eligibility and retention contract
  before those destructive workflows can be implemented/tested. Do not mark
  this card Done until the policy is documented and the scopes are covered.

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
- **Latest verification:** the same focused Gate 4 suite passed (68 passed,
  3 skipped) on Windows / Python 3.13.14 on 2026-11-08. Scoped Ruff and diff
  checks passed. The sync retry test now uses the injected sleeper instead of
  monkeypatching a removed module-level `time.sleep` hook.
- **Remaining:** run the symlink checks on a supported host and record live
  RCON/NAS integration evidence; the Windows skips and focused fake/local
  tests do not satisfy these acceptance items.

### KB-G5-11 — Add the dedicated security acceptance suite

- **WBS/Docs:** Document 11 §§1.2, 2, and 4.3; Documents 7 and 8 §9
- **Priority:** P1 · **Owner:** Copilot agent Security-CI · **Updated:** 2026-11-07
- **Depends on:** KB-G5-1, KB-G5-4, KB-G5-5 (Done)
- **Status:** Review
- **Acceptance:** dedicated security coverage for direct-route authz,
  privilege escalation, CSRF/step-up expiry, throttling/lockout, Argon2id and
  session rotation, encrypted secrets and response redaction, security
  headers/non-loopback cookie behavior, last-Superadmin protection, and audit
  immutability.
- **Evidence:** `python -m pytest --no-cov -q
  --basetemp=dev_artifacts/scratch/verify-security-final
  tests/integration/test_gate5_acceptance.py tests/integration/test_auth.py
  tests/integration/test_secrets.py tests/integration/test_audit.py
  tests/integration/test_document10_catalog_apis.py` passed (53) on Windows.
  Scoped Ruff and `git -c core.whitespace=cr-at-eol diff --check` passed.
  Coverage includes HTTPS rejection without cookie issuance, Secure cookies,
  CSP frame restrictions, API no-store, HTTP login lockout, last-Superadmin
  protection, sync-secret redaction, Argon2id, session rotation, and immutable
  audits. `.github/workflows/security.yml` runs this set in its own job.
- **Remaining:** The Ubuntu and Python 3.11 matrix legs need a hosted run;
  local verification used Windows / Python 3.13.

## To Do

### KB-G5-CLEANUP-POLICY — Decide safe stale-world and log cleanup policy

- **WBS/Docs:** Document 10 cleanup scopes; Documents 5 and 8
- **Priority:** P1 · **Owner:** Unassigned
- **Acceptance:** obtain an explicit product-owner decision for stale-world
  eligibility and log retention/eligibility; document safeguards, exclusions,
  preview information, and execution requirements in the governing documents.
  Do not implement destructive cleanup until the policy is approved and
  documented.
- **Current evidence:** `stale_worlds` and `logs` cleanup scopes currently
  return `CLEANUP_SCOPE_UNSUPPORTED`; the governing documents do not define
  safe candidate eligibility or retention parameters.

### KB-G2-ENTITY-MODEL — Reconcile Document 6 concepts with domain classes

- **WBS/Docs:** WP 2.2; Document 6 §§1–6
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G2-DOMAIN (Done)
- **Acceptance:** inventory Document 6's entity/aggregate concepts against
  domain classes, value objects, and persistence models; identify which
  concepts intentionally remain persistence-backed and which require domain
  types. Record an explicit implementation decision and tests before claiming
  complete domain-entity coverage.
- **Current evidence:** `app/domain/entities.py` defines `WorldInstance`;
  Document 6 describes additional concepts represented across schema and
  value objects. Full conceptual coverage has not been established by the
  focused lifecycle test run.

### KB-D12-2 — Track remaining service-layer architecture divergences

- **WBS/Docs:** Document 12 §§2, 4–5; Documents 8 and 12 define service
  boundaries and the target application layout.
- **Priority:** P2 · **Owner:** Unassigned
- **Acceptance:** review service-level SQL access and the partial command/query
  layer against the governing documents; record an explicit implementation
  decision or bounded migration work before treating the architecture
  divergence as resolved.
- **Current evidence:** services use the persistence abstraction but issue
  SQL through its connections; `app/commands/` currently contains only the
  world command module. `RuntimeService` is a facade while `WorldsService`
  retains lifecycle logic. No refactor or contract change is authorized by
  this documentation card alone.

### KB-G8-CONTRACT — Complete Document 8 service contract acceptance

- **WBS/Docs:** Documents 8 and 11; related implementation cards in Gates 2–4
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G2-MIGRATION, KB-G3-1, KB-G3-2, KB-G3-3, KB-G4-VERIFY
- **Acceptance:** inventory Document 8 service requirements against the
  existing focused acceptance cards; identify uncovered behavior, add
  contract-level tests for each uncovered requirement, and record a final
  acceptance map without treating implementation presence as contract
  completion.
- **Current evidence:** operation, scheduler, audit, backup, restore, cleanup,
  and sync slices have focused tests; contract-wide service acceptance remains
  open.

### KB-G9-CONTRACT — Complete Document 9 concurrency contract acceptance

- **WBS/Docs:** Document 9; related implementation cards KB-G2-3 and KB-G3-2
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G2-3, KB-G3-2
- **Acceptance:** map every Document 9 concurrency, conflict, locking, and
  optimistic-version requirement to implementation and tests; add tests for
  uncovered race/interleaving cases and record explicit exceptions before
  claiming full contract acceptance.
- **Current evidence:** the conflict matrix and ConfigEdit version behavior
  have focused coverage; full Document 9 acceptance remains open.

### KB-D11-TEST-PYRAMID — Close the Document 11 test-pyramid gaps

- **WBS/Docs:** Document 11 §§1–3
- **Priority:** P1 · **Owner:** Unassigned
- **Acceptance:** inventory required unit, integration, and end-to-end flows;
  add the missing service-level unit tests and representative full user-flow
  E2E tests; record measured test distribution against Document 11's
  approximate 70/25/5 pyramid or document an approved variance.
- **Current evidence:** focused domain and integration suites exist, but
  service-level unit coverage and full browser E2E flows are incomplete.

### KB-D11-COVERAGE — Meet documented test coverage floors

- **WBS/Docs:** Document 11 coverage requirements
- **Priority:** P1 · **Owner:** Unassigned
- **Acceptance:** raise every measured module to at least 80% coverage and
  overall coverage to at least 85%; preserve meaningful assertions, add
  coverage for the backup catalog API, and record the exact coverage command
  and result.
- **Current evidence:** backup catalog API coverage was recorded at
  44.46% and the documented module/overall floors as unmet.

### KB-D11-ISO-25010 — Complete the quality-characteristic evidence map

- **WBS/Docs:** Document 11 ISO/IEC 25010 mapping
- **Priority:** P2 · **Owner:** Unassigned
- **Acceptance:** map each applicable quality characteristic in the testing
  strategy to a measurable acceptance check and recorded evidence; add
  compatibility, performance, and flexibility checks that are currently
  unverified, coordinating performance thresholds with KB-PERF-01.
- **Current evidence:** functional suitability, reliability, and security
  coverage remain partial; compatibility, performance, and flexibility have
  not been verified.

### KB-DOC-EVIDENCE-QUALITY — Reconcile status and evidence claims

- **WBS/Docs:** This workboard; Documents 10, 11, and 13
- **Priority:** P2 · **Owner:** Unassigned
- **Acceptance:** make this workboard the sole current implementation-status
  source; define how slice-level and gate-level statuses differ; reconcile
  duplicate gate/work-package summaries; narrow route and authorization
  claims to verified scope pending KB-G5-API-CONTRACT; and record exact
  commands, dates, platforms, and test scope where historical counts differ
  (including the 36-test and 97-test Gate 1 results). Do not combine
  overlapping test counts or present historical results as fresh.
- **Current evidence:** gate and work-package summaries are repeated in this
  board; route/auth claims require careful scoping against known exceptions;
  and the 36-test and 97-test Gate 1 records need exact test-selection
  provenance.

### KB-DOC-WBS — Reconcile WBS paths and conformance details

- **WBS/Docs:** `wbs.txt`; Documents 12 and 13
- **Priority:** P2 · **Owner:** Unassigned
- **Acceptance:** retain the WBS work-package/dependency structure while
  reconciling obsolete `src/mcmanager/` file-scope paths and fake-server flag
  names with the current root `app/` layout and conformance harness. Numbered
  documents remain authoritative.
- **Current evidence:** Gate 1 file-scope paths now match root `app/`; the
  fake-server harness accepts both the documented `--crash-after` and
  `--save-slow` modes and the millisecond variants used by focused tests.
  Other WBS work-package paths still require reconciliation.

### KB-G5-6 — Complete real workflows for the 17 shell modules

- **WBS:** WP 5.3
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G5-3, KB-G5-4, KB-G5-5
- **Acceptance:** modules are functional workflows, not scaffold fragments;
  manager/world context switching works; navigation stays in-place and obeys
  Document 4 tokens and 40px control geometry.

### KB-G1-FORGE-SHUTDOWN — Diagnose Forge process exit after RCON stop

- **WBS/Docs:** WP 1.5–1.6; Documents 13 §3 and 14 §§8, 10
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** —
- **Acceptance:** reproduce the real Forge shutdown sequence in an isolated
  world copy; determine whether the delayed exit is server/mod behavior,
  Java/runtime behavior, or process-adapter behavior. If attributable to the
  manager or adapter, implement and test the fix. Record the server log's
  final save/RCON state and actual process exit classification without
  weakening the documented shutdown ladder.
- **Current evidence:** on Forge 1.20.1-47.4.10 / Java 21.0.13, RCON `stop`
  caused all chunks to be saved and the RCON listener to stop, but the
  supervised Java process did not exit within 180 seconds and was force
  terminated. The existing server log also contains mod error/warning
  messages; their relation to shutdown is unverified.

### KB-G5-8 — Implement manager lifecycle operations

- **WBS/Docs:** WP 5.1; Documents 5 Manager Maintenance, 6 Manager lifecycle,
  8, and 10
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G5-2, KB-G5-3, KB-G5-4
- **Acceptance:** replace `NOT_IMPLEMENTED` for manager/server restart,
  software update/rollback, and manager backup/restore with authorized,
  durable Operation workflows, recovery behavior, audit records, and
  integration coverage. Coordinate route/catalog ownership with KB-G5-3.

## Blocked

### KB-G1-MINECRAFT — Run the real Minecraft adapter integration spike

- **WBS/Docs:** WP 1.5; Documents 13 §5 and 14 §13
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G1-1, KB-G1-3 (Done)
- **Status:** Blocked
- **Blocked by:** This machine currently has a Forge 1.20.1 installation in
  ignored `app/data/worlds/` data; that installation may be absent in another
  checkout/CI worker. Vanilla, Paper, and Fabric installations or approved
  test fixtures are also needed for the full spike. Follow Document 11 §1.4
  before using any local server, and investigate KB-G1-FORGE-SHUTDOWN before
  claiming Forge shutdown acceptance.
- **Acceptance:** headless Vanilla, Paper, Fabric, and Forge runs verify
  pre-spawn Java/EULA gating, declared readiness signals, RCON/save behavior
  where supported, shutdown, and startup-failure classification. Record
  server/JDK versions and results; do not treat fake-server tests as live
  adapter evidence.
- **Partial evidence:** an isolated copy of the Forge 1.20.1-47.4.10 world
  was run on Windows / Java 21.0.13 using `WindowsProcessAdapter`, loopback
  ports, and the manager's RCON/readiness code. Java compatibility, protocol
  ping, authenticated RCON `list`, and `save-off`/`save-all`/`save-on` passed.
  The server logged that all chunks were saved and the RCON listener stopped,
  but the Java process remained alive beyond 180 seconds after RCON `stop` and
  required forced termination. This is not a clean shutdown pass. Vanilla,
  Paper, and Fabric were not tested.

### KB-G0-5 — Restore green repository static gates

- **WBS/Docs:** Document 12 §8
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G0-1
- **Status:** Blocked
- **Acceptance:** Ruff, Black, isort, mypy, and import-linter pass on the
  configured project scope; add those commands to the documented/CI gate.
  Avoid broad formatting churn without coordinating it as a dedicated slice.
- **Evidence:** Windows / Python 3.13 baseline: `python -m ruff check app tests`
  reports 46 errors; `python -m black --check app tests` reports 76 files to
  reformat after aligning Black with Document 12's single-quote style;
  `python -m isort --check-only app tests` reports 9 files; `python -m mypy app`
  reports 217 errors. `lint-imports` cannot start because the command is not
  installed in the selected interpreter, though `import-linter` is declared in
  `requirements-dev.txt`. Document 12 §8 now records the canonical commands.
- **Blocker:** The remaining Black set includes protected shell/backup files;
  mypy failures include process adapters and protected API slices. These files
  and their tests are outside this card's authorized edit scope. Install the
  declared dev dependencies and coordinate those feature slices before claiming
  all gates green. Root security and adapter-conformance workflows now exist,
  but there is no general static-gate workflow; the earlier workflow under
  `legacy implementation/` still references the legacy layout.

### KB-G5-10 — Verify metrics cadence and streaming deployment behavior

- **WBS/Docs:** WP 5.2; Documents 10 MetricsCadence and 11 §§1.2, 4.1
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** KB-G5-7 (Done)
- **Status:** Blocked
- **Acceptance:** verify `/stream/metrics`, zero-client/all-worlds-off
  suppression, 15-second cached refresh, 1Hz fan-out while subscribed,
  heartbeat and slow-client behavior, and no per-client recomputation.
  Exercise the supported deployment proxy with buffering disabled and record
  reconnect/stream results; add or fix tests for uncovered behavior.
- **Evidence:** `python -m pytest --no-cov -q -k
  "not performance_acceptance_smoke"
  tests/integration/test_phase3_control_plane.py
  tests/integration/test_phase5_presentation_hardening.py
  tests/integration/test_gate5_acceptance.py` passed (42 passed, 1 deselected)
  on Windows. The MetricsService now refreshes a shared host/world snapshot
  every 15 seconds when any world is active, publishes the cached snapshot at
  1 Hz to connected clients, and performs no collection/emission when there
  are no clients and all worlds are off. Tests cover a nonblank authenticated
  `/stream/metrics` snapshot, cache refresh, 50-subscriber fan-out without
  per-subscriber collection, slow-subscriber removal, and the 15-second
  heartbeat. Scoped Ruff passed for the implementation and tests.
- **Remaining:** The repository has no supported deployment proxy
  configuration; `X-Accel-Buffering: no` is not evidence the proxy honors it.
  Document 11's 50-client/1Hz numbers are not a benchmark result; calibrated
  stream performance and CPU-flatness remain blocked on reference hardware.

### KB-G1-6 — Run C1–C14 on a POSIX host

- **WBS:** WP 1.6
- **Priority:** P1 · **Owner:** Unassigned · **Updated:** 2026-11-08
- **Status:** Blocked
- **Blocked by:** Hosted Ubuntu/Windows workflow results are still pending;
  the workflow has been configured as a two-OS matrix but has not run on
  GitHub Actions.
- **Acceptance:** run `tests/adapters/test_conformance.py` on a supported POSIX
  OS and attach the complete result; fix any platform-specific failures.
- **Evidence:** `.github/workflows/adapter-conformance.yml` now runs the same
  suite on `ubuntu-latest` and `windows-latest`. Previous local Windows
  evidence is supplemented by
  `python -m pytest --no-cov -q tests\adapters\test_conformance.py` on Windows
  (30 passed, 2026-11-08). No POSIX conformance pass is claimed until the
  hosted Ubuntu leg completes.

### KB-PERF-01 — Calibrate and pass performance release acceptance

- **WBS:** Gate 5; Document 11 §4.2
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
  authorization (including session, CSRF, role, and step-up requirements on
  every mutating route), request/response schema, status, envelope, and error
  mapping; record explicit `NOT_IMPLEMENTED` exceptions and add contract-level
  tests for uncovered behavior. Include manager lifecycle routes and all
  cleanup scopes. This is a final parity review, not a substitute for
  implementing the route-catalog cards.
