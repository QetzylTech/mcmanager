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
6. Transfer actionable findings from current evidence under `Audits/` into
   bounded cards here and verify the transfer checklist. This board is the
   source of truth for status and evidence. Do not maintain a competing status
   tracker. When a contract changes, update the governing numbered document
   first, then any pseudocode and audit record. Numbered product documents
   take precedence over WBS sketches and audit notes.
7. Record commands, pass/fail counts, and platform in `Evidence`. Do not
   overwrite evidence with a newer partial run.
8. Feature tests belong to the owning implementation card's acceptance
  workflow; their results determine whether that card is in Review or Done.
  Do not create a separate task just to complete tests for a feature. Standalone
  test/coverage cards are only for cross-cutting quality infrastructure and
  release floors, and do not replace feature-level acceptance.

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

## Audit transfer — 2026-11-20

Current findings and verification notes are under `Audits/`; this board
controls task status and evidence. The 2026-11-19 reconciliation pack and
inventories are historical snapshots under `old doc/Audits/` and must not be
treated as current results without fresh verification.

| Audit finding | Workboard tasks |
|---|---|
| AUD-2026-11-19-01 — Plan and WBS conflicts | KB-DOC-PLAN-COHERENCE, KB-DOC-WBS, KB-G8-SYNC-CAP |
| AUD-2026-11-19-02 — Historical/incomplete pseudocode | KB-DOC-PSEUDOCODE-DECISION |
| AUD-2026-11-19-03 — Product implementation gaps | KB-G5-CLEANUP-POLICY, KB-G5-CLEANUP-SCOPES, KB-G5-8, KB-G5-6, KB-G5-API-CONTRACT |
| AUD-2026-11-19-04 — Architecture boundary/divergence | KB-G0-BOUNDARY-REGRESSION, KB-D12-2 |
| AUD-2026-11-19-05 — Sync concurrency mismatch | KB-G8-SYNC-CAP, KB-G8-CONTRACT, KB-G4-VERIFY |
| AUD-2026-11-19-06 — Test pyramid and coverage gaps | KB-D11-TEST-PYRAMID, KB-D11-COVERAGE, KB-D11-ISO-25010; feature-owner cards |
| AUD-2026-11-19-07 — Full-suite failures | KB-G0-7, KB-G0-BOUNDARY-REGRESSION |
| AUD-2026-11-19-08 — Static gates and stale baselines | KB-G0-5, KB-DOC-EVIDENCE-QUALITY |
| AUD-2026-11-19-09 — Performance evidence | KB-PERF-01, KB-G5-10, KB-D11-ISO-25010 |
| AUD-2026-11-19-10 — Workboard/WBS traceability | KB-DOC-EVIDENCE-QUALITY, KB-DOC-WBS, KB-G5-API-CONTRACT, KB-G8-CONTRACT, KB-G9-CONTRACT |
| AUD-2026-11-19-11 — Legacy documentation inventory | KB-DOC-LEGACY-ARCHIVE |
| AUD-2026-11-20-01 — Restore active workboard and current Audits evidence layout | KB-DOC-EVIDENCE-QUALITY, KB-REC-01, KB-REC-05 |
| AUD-2026-11-20-02 — Record sync, API/SSE, diagnostics, schema, and restore realignments | KB-G8-SYNC-CAP, KB-G5-API-CONTRACT, KB-G1-LOG-REPLAY, KB-G4-VERIFY, KB-G0-7 |
| Detailed implementation/test inventory | Existing cleanup, lifecycle, architecture, API, test, platform, security, and performance cards above |

## Reconciliation reset — 2026-11-19 (historical snapshot)

The historical audit snapshot is no longer sufficient as a live status source.
Start with these bounded cards; update or close older cards only when the
recorded evidence supports the status change.

- **R0 baseline:** freeze the tested snapshot and reproduce or explicitly
  quarantine the reported baseline.
- **Specification normalization:** resolve only the known cross-document
  conflicts, do not redesign unrelated product behavior.
- **Traceability batches:** verify route, schema, source, and test mappings in
  independently reviewable groups.
- **External acceptance:** remain Blocked until the required host, hardware,
  credentials, or approved fixture is available.

## Reconciliation ledger

`Audits/reconciliation_traceability.csv` records current stable requirement
IDs, source status, implementation/test evidence, and owning cards. Historical
inventories in `old doc/Audits/` are source material only. Route, schema, and
external-host completeness remain explicitly `PRESENT_UNVERIFIED`, `MISSING`,
or `DEFERRED` until their owning cards finish acceptance. This ledger does not
create a completion percentage or treat route shape as full API conformance.

## Gate roll-up

| Area | Implemented and verified scope | Remaining acceptance / release state |
|---|---|---|
| Repository layout | Distributable `app/` contains startup, runtime requirements, migrations, and app-local configuration; manager state stays under `app/data/worlds/` | Package layout is Done; new curated runtime docs may be added under `app/docs/` |
| Gate 1 / WP 1.1–1.6 | Process ports, Windows/fake conformance, readiness, EULA flow, and durable logging | Partial: the conformance workflow now targets Windows and Ubuntu, but hosted results and real-server spike evidence remain |
| Gate 2 / WP 2.1–2.4 | WBS Gate 2 criterion verified: clean foreign-key check and migration rollback; domain, settings, and ConfigEdit slices also pass focused tests | Gate criterion passed on Windows; Document 6 model inventory and broader release acceptance remain |
| Gate 3 / WP 3.1–3.4 | WBS Gate 3 criterion verified: runtime re-attachment and derived-lock conflict behavior pass alongside operation, audit, and scheduler suites | Gate criterion passed on Windows; full release acceptance remains |
| Gate 4 / WP 4.1–4.4 | WBS Gate 4 pre-restore backup and compensating rollback criterion verified with focused backup/restore/cleanup/sync/filesystem suites | Gate criterion passed on Windows; three symlink checks, POSIX, and live RCON/NAS acceptance remain |
| Gate 5 / WP 5.1–5.3 | Auth, selected world/admin APIs, backup/restore/backup-cleanup/sync catalog, cancellation, SSE sharing, and world-list workflow | Partial: approved stale-backup/log cleanup implementation and tests, full shell workflows, manager lifecycle endpoints, hosted security job, and supported-proxy validation remain |

## Implementation status

**Current release state:** not release-ready. The latest full-suite evidence
and its limitation are recorded below and in
`Audits/REALIGNMENT_2026-11-20.md`.

The production-bound application is `app/`; it has a tested foundation and
substantial control-plane functionality, but has not passed release acceptance
and is not yet operator-ready. `Prototypes/` is a separate legacy reference
archive, not the current application. The principal known product gaps are
stale-backup/log cleanup workflows, manager lifecycle operations,
full contract parity, and cross-platform, deployment, and performance release
acceptance.

### Current verification — 2026-11-20

- Consolidated focused API, middleware, SSE, diagnostics/presentation, and sync
  run: **75 passed**; browser contract suite: **7 passed**. Separate schema/EULA
  checks passed (16 tests), world lifecycle checks passed (12 tests), and the
  coverage-focused additions passed (13 tests). These selections overlap and
  must not be added into one aggregate.
- Full suite before the coverage additions: **507 passed, 1 failed, 3 skipped,
  76.87% coverage, 259 warnings**. The sole test failure was missing
  `python-dotenv`; that dependency is already declared in `app/requirements.txt`.
  After installing the declared dependency, `tests/unit/test_main.py` passed
  (2 tests).
- The clean `.venv-phase4` run (`.\.venv-phase4\Scripts\python.exe -m pytest
  -q --tb=no`, Python 3.13.18) collected 526 tests: **523 passed, 0 failed,
  3 skipped, 79.85% coverage, 258 warnings** in 403.46s. Coverage missed the
  configured 80% floor. The captured shell exit code was reported as 0 despite
  pytest output reporting the floor failure; acceptance is based on the
  coverage result, not that wrapper exit code. The earlier agent claim of a
  passing coverage gate was incorrect; see
  `Audits/verification_log_2026-11-20.md`. This P0 card remains open.
- The focused run emitted worker/scheduler/metrics shutdown warnings about
  accessing the SQLite store after close. Track warning triage without counting
  these as test failures.
- `git -c core.whitespace=cr-at-eol diff --check` passed after restoring the
  active tracker and audit layout.
- Static cleanup: `python -m compileall -q app tests` passed; scoped Ruff on
  touched Python files passed. Repository Ruff still reports 41 findings and
  the broader service mypy run reports 232 errors.

### Historical verification snapshots

- The 2026-11-19 Windows / Python 3.13.14 full-suite run recorded **493 passed,
  8 failed, 4 skipped, 76.24% coverage, 251 warnings**. Its failures have since
  been addressed in focused changes; this run is historical, not current
  acceptance evidence.
- Repository-wide static checks on Windows / Python 3.13.14: Ruff **39**
  errors (28 fixable with `--fix`; 9 additional unsafe fixes are available);
  Black **84** files would be reformatted; isort **7** files were flagged.
  One additional test file was skipped because the Windows console encoding
  could not parse it;
  mypy **238** errors in 23 of 92 application files. `lint-imports` could not
  run because `lint_imports` is not installed in the project virtualenv.
- Historical `python -m pytest --no-cov -q -k "not performance_acceptance_smoke"`:
  **448 passed, 3 skipped, 1 deselected**. The skips require Windows symlink
  privileges unavailable on the recorded host; the deselected smoke is the
  long performance test. This is the 2026-11-08 historical result.
- Historical `node --test tests\browser\test_gate5_browser.test.cjs`: **6 passed**,
  including actual `operator_ui.js` navigation across all 17 modules, setup/
  login, Manager Backup submission, tokenized shell styling, and 10-tab stream
  sharing/failover. One additional check targets the unused legacy `shell.js`
  prototype and is not counted as production UI coverage.
- Dedicated security acceptance modules: **53 passed** locally; hosted
  GitHub Actions execution remains pending.
- Historical focused Gate 5/API/log verification: **57 passed** across
  `test_document10_catalog_apis.py`, `test_gate5_acceptance.py`,
  `test_world_management_api.py`, and `test_realtime_slow_client.py`;
  Gate 5 browser regression: **6 passed**.
  These verify existing API/browser behavior and do not close the manager
  lifecycle, shell workflow, cleanup-policy, hosted-security, or proxy gaps.
- Historical metrics/control-plane/presentation/Gate 5 integration: **42 passed,
  1 deselected**; the deselected test is the long performance smoke.
- Scoped Ruff, compilation, and focused mypy checks passed for the recorded
  feature slices; this is not a repository-wide static-gate pass.
- Five-agent MVP implementation follow-up (2026-11-08): manager backup ZIP
  artifact test **1 passed**; bootstrap/catalog tests **14 passed**; backup/
  restore coordination tests **31 passed**; proxy HTTPS cookie test **1 passed**.
  A broad non-performance suite was attempted but exceeded the terminal runner's
  30-second limit; no full-suite result is claimed.
- Earlier repository-wide static baselines (Ruff 46/52, Black 76/74 files,
  isort 9/14 files, mypy 217 errors) are superseded by the fresh results above.
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
- Implementation follow-up on 2026-11-19: added guarded server-properties
  editing, per-world cleanup-policy editing, sync-target CRUD, documentation
  and manager-log browsing, permission-grant enforcement, and expanded
  diagnostics/version metadata. Before the app-only packaging change,
  `python3 -m compileall -q app migrations`
  passed on Linux. Initial testing was still pending at that point. Later
  focused API checks and the 2026-11-20 browser contract suite (7 passed) are
  recorded under KB-G5-6; complete workflow acceptance remains open.

### MVP Code Backlog (Tests Excluded)

This is the currently known source/configuration work needed for the MVP. It
does not count missing tests, hosted runs, live-server exercises, benchmarks,
or documentation-only reconciliation as code gaps. The list is based on the
current implementation and known requirements; Document 8/9/10 code parity
reviews may expose additional concrete deltas.

| Work item | Code still needed | Existing tracking |
|---|---|---|
| Stale-backup and log cleanup | Review and verify approved `stale_backups` and `logs` policy: stale eligibility, oldest-first deletion of floor(50%) of eligible stale backups on each pressured run, protected references, rotated-log retention, previews, and scheduled execution. No stale-backup tombstone or grace period. Never select world directories or world records. | KB-G5-CLEANUP-POLICY, KB-G5-CLEANUP-SCOPES, KB-G5-3 |
| Complete operator workflows | Authenticated documentation, manager log browsing, sync-target CRUD, guarded `server.properties` editing, and per-world and manager-wide cleanup-policy editing now have implementations. A real-browser setup/login flow passes; broader browser acceptance remains outstanding. Manager restore/restart/update/rollback UI remains blocked on those backend contracts. | KB-G5-6; KB-G5-API-CONTRACT; KB-G5-8 |
| Manager lifecycle | Manager Backup is implemented as a durable operation and ZIP+SHA `manager_config` artifact. Implement manager restore, restart, update, and rollback only after defining the recovery, host-supervisor, trusted-update, and data-compatibility contracts; those routes remain `NOT_IMPLEMENTED`. | KB-G5-8 |
| API contract implementation | Guarded server-properties editing, per-client permission-grant enforcement, diagnostics telemetry, release-version metadata, global cleanup-policy routes, sync-target CRUD, and documentation/log APIs now have implementations. Complete full contract parity; settings-visibility response policy needs a product decision. Manager and stale/log cleanup behavior stay on their owning cards. | KB-G5-API-CONTRACT; owning feature cards |
| Production proxy trust | Nginx configuration and `trusted_proxy_hops` support now exist. Keep hop count opt-in and matched to the actual trusted proxy chain; no additional proxy code is currently identified. | KB-G5-10 |
| Production code health | Resolve source-level Ruff, Black, isort, mypy, and import-boundary failures in the configured project scope without broad unrelated formatting churn. | KB-G0-5 |
| Document 8/9 behavior deltas | Implement only concrete service/concurrency behavior found missing during the contract inventory; current cards primarily track contract mapping and tests, not a fully enumerated code delta. | KB-G8-CONTRACT, KB-G9-CONTRACT |

**Conditional code fix:** KB-G1-FORGE-SHUTDOWN records a Forge process that did
not exit after RCON `stop`. Implement a manager/adapter fix only if diagnosis
attributes the behavior to this project; do not add a workaround for server or
mod behavior without an explicit product decision.

### Non-Code MVP Acceptance (Not Counted Above)

- Run C1–C14 on a supported POSIX host and complete the real
  Vanilla/Paper/Fabric/Forge integration spike (KB-G1-6, KB-G1-MINECRAFT).
- Run the dedicated security job on its hosted Ubuntu/Python matrix and verify
  Nginx/ProxyFix and SSE reconnect behavior through a live deployment
  (KB-G5-11, KB-G5-10).
- Complete calibrated performance acceptance on a documented reference host
  (KB-PERF-01).
- Feature-specific tests and contract checks are completed and recorded on
  their owning implementation cards; cross-cutting test-pyramid, coverage, and
  ISO/IEC 25010 release floors remain tracked as quality gates
  (KB-D11-TEST-PYRAMID, KB-D11-COVERAGE, KB-D11-ISO-25010).
- Reconcile status labels, API/auth claims, and test evidence provenance
  (KB-DOC-EVIDENCE-QUALITY); reconcile obsolete WBS paths and fake-server flag
  names (KB-DOC-WBS).

### Run locally

Run the app from the repository root (manager state and Minecraft
installations are kept under ignored `app/data/` directories):

```console
python app/main.py
```

For an app-only copy, install `app/requirements.txt`, copy
`app/.env.example` to `app/.env`, then run `python main.py` from `app/`.
Repository planning documents are not part of that distribution.

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

### KB-G2-ENTITY-MODEL — Reconcile Document 6 concepts with domain classes

- **WBS/Docs:** WP 2.2; Document 6 §§1–7
- **Priority:** P1 · **Owner:** coordinator session · **Updated:** 2026-11-08
- **Depends on:** KB-G2-DOMAIN (Done)
- **Acceptance:** inventory Document 6's entity/aggregate concepts against
  domain classes, value objects, and persistence models; identify which
  concepts intentionally remain persistence-backed and which require domain
  types. Record an explicit implementation decision and tests before claiming
  complete domain-entity coverage.
- **Evidence:** Document 6 §7 now records the hybrid representation decision:
  `WorldInstance` is the pure immutable lifecycle aggregate, while the remaining
  concepts are persistence-backed at their transaction/service boundary and
  share the documented closed value objects. `tests/unit/domain`,
  `tests/integration/test_gate2_realignment.py`,
  `tests/integration/test_schema_migrations.py`, `tests/integration/test_auth.py`,
  and `tests/integration/test_secrets.py` passed (**106 passed**) on Windows /
  Python 3.14.9 using `.venv-phase4` on 2026-11-08.

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

- **WBS/Docs:** Document 12 §2; historical layout decision, superseded by
  KB-PACKAGE-01.
- **Priority:** P1 · **Owner:** repository session · **Updated:** 2026-11-06
- **Acceptance:** `app/` and `migrations/` exist at root; `core/` is absent;
  layout contract test passes.
- **Evidence:** `python -m pytest --no-cov -q tests/unit/test_project_tooling_contract.py`
  passed (1 test).

### KB-PACKAGE-01 — Make `app/` the production distribution boundary

- **WBS/Docs:** Document 12 §2; app-only distribution direction
- **Priority:** P1 · **Owner:** repository session · **Updated:** 2026-11-19
- **Acceptance:** `app/` contains its Python entry point, runtime
  requirements, migrations, ignored `.env` location, and runtime-doc location;
  startup and data paths resolve within that package without repository-level
  files. Keep developer planning docs, tests, and tools outside the package.
- **Evidence:** targeted startup, migration, package-layout, and world-lifecycle
  tests passed (35) on Windows / Python 3.13.14. Scoped Ruff and Black checks
  passed. A copied `app/` folder without repository-level files started and
  served HTTP 200. The 2026-11-19 full-suite counts are historical. The
  2026-11-20 clean full run had 523 passed, 0 failed, and 3 skipped, but
  coverage was 79.85% and remains below the configured gate; see KB-G0-7 and
  KB-D11-COVERAGE.

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
- **Latest Gate 2/schema verification — 2026-11-21:** migrations 006–007 now
  enforce append-only restore outcomes, sequential sync attempts, and the
  configurable global sync cap. The combined migration, Gate 2, restore, sync,
  and API selection passed; the full run passed **567 passed, 0 failed,
  3 skipped**. A focused Gate 2/schema/auth selection passed **45 tests**;
  authentication checks cover Argon2id storage, lockout, step-up expiry and
  password re-entry, and password-change session revocation. Remaining Gate 2
  work is complete 28-table parity, not execution of the historical DDL
  examples in `gate2_pseudocode.txt`.

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
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-08
- **Acceptance:** authenticated `GET /api/worlds` supports documented world
  filters, deleted-row opt-in, and pagination; the World Management shell
  page renders and queries that listing without full-page navigation.
- **Evidence:** focused world-list integration tests passed (2); Gate 5 browser
  suite passed (4), including first-run setup/login and in-page Backup/Start/Stop
  actions with session-bound CSRF/idempotency headers, tokenized 40px controls,
  and ten-tab stream-sharing/failover.

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
  allowed by Documents 8 and 12. This is historical evidence from the prior
  run, not the current boundary state: AUD-2026-11-19-04 found
  `app/services/server_properties.py` importing concrete
  `app.infrastructure.minecraft.properties_schema`, and the boundary test
  failed in the audit run. Track the regression in `KB-G0-BOUNDARY-REGRESSION`.

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
- **Current implementation follow-up — 2026-11-21:** CreateWorld now provisions
  and persists a stable world-ID directory, enters `eula_required`, and never
  accepts EULA implicitly. Rename preserves the provisioned path. The focused
  world-management, lifecycle, configuration, and migration selection passed
  (71 tests); the browser workflow suite passed (7 tests).

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
- **Current implementation follow-up — 2026-11-21:** Global settings now
  expose the configurable world-start concurrency limit (default 3; `NULL` or
  `0` means unlimited), with API validation and operator UI input handling.
  Settings and migration regressions passed in the 71-test focused selection.

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
  passed. The focused schema/EULA and world-lifecycle regressions passed 16
  and 12 tests respectively on 2026-11-20.

### KB-G1-2 — Complete durable, configurable process logging

- **WBS:** WP 1.4 · **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-07
- **Depends on:** —
- **Acceptance:** `VERBOSE_LOGGING=false` filters debug/raw output without
breaking readiness; durable per-session and channel logs persist alongside
bounded in-memory tailing; default is documented in `app/.env.example`.
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

### KB-G3-6 — Bound concurrent independent world starts

- **WBS:** WP 3.1
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-21
- **Depends on:** KB-G3-2 (Done)
- **Acceptance:** independent Start Operations dispatch concurrently up to the
  configured manager-wide limit (default 3); `NULL` or `0` means unlimited;
  queued starts remain durable, one failed world does not block others, and
  SQLite transactions remain isolated across worker threads.
- **Evidence:** the lifecycle integration test drives six fake worlds through
  readiness, checks the default-three admission, a limit of one, and unlimited
  dispatch; a persistence test verifies per-thread writer isolation. The
  focused world/configuration/migration selection passed (71 tests); the final
  full suite passed (577 passed, 3 skipped in 420.06s on Windows).

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
  orderly shutdown. The 2026-11-20 `node --test
  tests/browser/test_gate5_browser.test.cjs` run passed (7), including
  10-tab connection sharing/failover, topic forwarding, auth expiry/recovery,
  and manager shutdown. Scoped Ruff and diff checks passed.

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

### KB-G5-11 — Add the dedicated security acceptance suite

- **WBS/Docs:** Document 11 §§1.2, 2, and 4.3; Documents 7 and 8 §9
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-21
- **Depends on:** KB-G5-1, KB-G5-4, KB-G5-5 (Done)
- **Acceptance:** dedicated security coverage for direct-route authz,
  privilege escalation, CSRF/step-up expiry, throttling/lockout, Argon2id and
  session rotation, encrypted secrets and response redaction, security
  headers/non-loopback cookie behavior, last-Superadmin protection, and audit
  immutability.
- **Evidence:** focused local security suite passed (53) on Windows. The
  hosted workflow at commit `071711da582e8305e4a33feb9974204cb89e1e93` passed
  on Windows/Python 3.11.9 and Ubuntu/Python 3.11.18: **61 passed on each
  platform** (2026-11-20).

### KB-G1-6 — Run C1–C14 on a POSIX host

- **WBS:** WP 1.6
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-21
- **Acceptance:** run `tests/adapters/test_conformance.py` on a supported POSIX
  OS and attach the complete result; fix any platform-specific failures.
- **Evidence:** `.github/workflows/adapter-conformance.yml` passed at commit
  `071711da582e8305e4a33feb9974204cb89e1e93` on Ubuntu/Python 3.13.18 and
  Windows/Python 3.13.17: **30 passed on each platform** (2026-11-20).

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
- **Remaining:** Complete route-by-route Document 10 acceptance and browser
  verification. The stale-backup/log policy has since been approved and scope
  implementation is tracked on KB-G5-CLEANUP-SCOPES; the earlier unsupported-
  scope observation is historical and superseded.
- **Implementation update (2026-11-19):** sync-target create/update/enable/
  disable/delete endpoints were added. The new routes have not received
  standalone browser acceptance. The 2026-11-20 consolidated focused API,
  middleware, SSE, diagnostics/presentation, and sync selection passed
  (75 tests total); API test coverage now includes catalog and sync-target
  behavior. Full route-by-route Document 10 acceptance remains open.

### KB-G5-CLEANUP-POLICY-API — Expose global cleanup policy management

- **WBS/Docs:** Documents 5, 7, 8, and 10; cleanup-policy schema in migration
  001
- **Priority:** P1 · **Owner:** Unassigned
- **Status:** Review
- **Acceptance:** expose manager-wide and world cleanup-policy reads and
  versioned edits in Maintenance; include age/count/space, stale-session, and
  optional log-retention fields; preserve ConfigEdit/audit behavior and
  global-default inheritance.
- **Evidence:** manager-wide GET/PATCH routes, versioned ConfigEdit operation,
  step-up enforcement, and the Manager Maintenance editor are implemented.
  Migration 005 and the policy endpoints now include `stale_session_threshold`
  and nullable `log_retention_days`; focused API verification passed as part of
  the 97-test cleanup/API/scheduler/schema/operation run.
  AUD-2026-11-19-10 found this card under To Do despite its prior `Implemented`
  label; moved it to Review pending confirmation that every acceptance check
  is satisfied.

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
- **Concurrent cap admission:** `python -m pytest --no-cov -q
  tests/integration/test_sync_gate4.py` passed (9 tests) on Windows / Python
  3.13 on 2026-11-20. The current service reserves an active-transfer slot
  before target resolution and releases it on completion/failure. Tests cover
  the cap constant, direct rejection of a third reserved slot, and reservation
  behavior. They do not yet exercise three simultaneous `dispatch_sync` calls
  with a blocking transport; add that integration case before treating the
  global concurrency requirement as fully accepted.
- **Restore cleanup — 2026-11-20:** successful world restore removes the
  temporary restore archive while retaining the recovery pre-backup.
  `tests/integration/test_gate4_acceptance.py` includes the cleanup assertion.
- **Remaining:** run the symlink checks on a supported host and record live
  RCON/NAS integration evidence; the Windows skips and focused fake/local
  tests do not satisfy these acceptance items.

### KB-G1-LOG-REPLAY — Make live-log delivery recoverable

- **WBS/Docs:** WP 1.4 and WP 5.2; Documents 10 and 13
- **Priority:** P1 · **Owner:** Copilot agents · **Updated:** 2026-11-08
- **Depends on:** KB-G1-2, KB-G5-7
- **Status:** Review
- **Acceptance:** keep process-pipe ingestion non-blocking and make subscriber
  overflow recoverable from durable logs using an explicit cursor-gap/replay
  contract; clients must not silently miss lines when a bounded subscriber
  queue fills.
- **Evidence:** `/stream/worlds/{world_id}/logs` supports durable cursor replay
  and emits `log.replay`/`log.gap`; the stream client retains cursors and
  requests replay. The earlier focused API/log run (57 passed across four
  modules) included backlog replay beyond subscriber queue capacity and
  unavailable-cursor resnapshot. The prior 2026-11-19 failure report for the
  slow-client tests is historical.
- **Remaining:** review browser/client recovery under a live proxy; the full
  repository suite completed on 2026-11-20 with 523 passed, 0 failed, and
  3 skipped; coverage missed the configured floor. The 2026-11-19 failures,
  including the slow-client tests, are historical and resolved. Live proxy
  recovery remains unverified.

### KB-DOC-PLAN-COHERENCE — Reconcile runtime documentation references

- **WBS/Docs:** Documents 5, 10, and 12; AUD-2026-11-19-01
- **Priority:** P2 · **Owner:** Unassigned
- **Status:** Review
- **Acceptance:** align the runtime documentation location in Documents 5
  and 10 with Document 12's distributed `app/docs/` boundary. Preserve the
  distinction between repository planning docs and future curated operator
  docs; verify no runtime documentation API or UI points at the repository's
  planning-document tree.
- **Audit snapshot:** the 2026-11-19 report and inventory under
  `old doc/Audits/` describe
  the earlier conflict. The current Documents 5, 10, and 12 consistently
  identify `app/docs/` as shipped runtime content and root `docs/` as planning
  material; do not treat the older snapshot wording as current.
- **Current evidence:** `manager_content.py` resolves `app/docs/`, returns
  escaped source text with `rendered_html: null`, and the shell displays the
  content in `<pre>`. `app/docs/` currently contains only `.gitkeep`, so
  curated runtime documentation content remains future work.

### KB-DOC-PSEUDOCODE-DECISION — Decide how to retain historical pseudocode

- **WBS/Docs:** Five gate pseudocode files; AUD-2026-11-19-02
- **Priority:** P2 · **Owner:** Unassigned
- **Status:** Review
- **Decision:** retain all five gate files as historical, superseded examples;
  do not refresh them into a complete implementation or test inventory.
- **Acceptance:** each file must label its body as historical/superseded and
  point readers to the governing numbered documents. Do not present
  pseudocode as a complete implementation or test inventory.
- **Evidence:** all five files consistently identify themselves as historical
  snapshots and link to their governing numbered documents. They cover
  selected Gate 1–5 slices only, not every planned component, route, function,
  or acceptance flow. No pseudocode was changed by this decision.

### KB-DOC-WBS — Reconcile WBS paths and conformance details

- **WBS/Docs:** `wbs.txt`; Documents 12 and 13
- **Priority:** P2 · **Owner:** Unassigned
- **Status:** Review
- **Acceptance:** retain the WBS work-package/dependency structure while
  reconciling obsolete `src/mcmanager/` file-scope paths, the stale
  “zero-dependency” description, and fake-server flag names with the current
  root `app/` layout and conformance harness. Reconcile sync retry wording
  under `KB-G8-SYNC-CAP`; numbered documents remain authoritative.
- **Audit snapshot:** the 2026-11-19 audit pack counted 21 stale paths in its
  uploaded snapshot. The current `wbs.txt` contains no `src/mcmanager/` paths
  or zero-dependency claim; pure-domain “zero infrastructure dependencies”
  remains an acceptance criterion, not a project dependency claim.
- **Current evidence — 2026-11-20:** WBS file scopes use the current `app/`
  layout; the SQLite migration path and duplicate connection-file typo were
  corrected. Fake-server flags match the harness, sync retries are stated as
  three total attempts with 30s/60s waits (no 120s retry wait), and the
  runtime-document boundary now points to `app/docs/`. Kept the work-package
  plan structure; numbered documents remain authoritative.

### KB-G0-BOUNDARY-REGRESSION — Restore the service dependency boundary

- **WBS/Docs:** Document 12 §4; AUD-2026-11-19-04 and -07
- **Priority:** P1 · **Owner:** Copilot current session
- **Status:** Review
- **Acceptance:** remove the concrete infrastructure dependency from
  `app/services/server_properties.py` using an existing or appropriately
  extracted port/schema boundary; add/retain a focused regression assertion;
  pass `tests/unit/test_dependency_boundaries.py` and the relevant
  server-properties tests without broad exception lists or weakened checks.
- **Historical evidence:** the 2026-11-19 audit found the service importing
  `app.infrastructure.minecraft.properties_schema`; this was stale by the
  time it was rechecked. `KB-D12-2` separately tracks the broader command/query
  and repository architecture decision.
- **Current evidence — 2026-11-20:** `ServerPropertiesService` imports
  property schema types/functions through `app.ports.minecraft`; the focused
  server-properties boundary and persistence-port selection passed 31 tests
  with `--no-cov`. Broader architecture work remains open under `KB-D12-2`.
- **Follow-up — 2026-11-21:** the full suite found `CleanupService` imported
  `LocalFilesystem` directly as a fallback. The service now requires a
  `FilesystemPort`; `bootstrap.py` constructs the adapter and injects it.
  Cleanup-focused direct test construction now injects `LocalFilesystem`
  explicitly. Dependency-boundary, cleanup, Gate 4, phase-4, and isolated
  shutdown-warning checks passed (**40 passed**); scoped Ruff, Black, isort,
  and CRLF-aware diff checks passed.
- **Follow-up — 2026-11-21:** Java catalog verification now calls the
  `MinecraftServerPort` through the composition container; the port-boundary
  regression and related unit selection passed (**29 passed**). SQLite readers
  are now isolated per thread rather than shared across worker threads; the
  schema-migration concurrency tests and real-browser startup pass without the
  prior reader `InterfaceError`.

### KB-G8-SYNC-CAP — Resolve sync concurrency and retry contract

- **WBS/Docs:** Documents 8 and 10; WBS sync work package; AUD-2026-11-19-01
  and -05
- **Priority:** P1 · **Owner:** Copilot current session
- **Status:** Review
- **Acceptance:** retain Document 8's two-simultaneous-transfer cap and align
  Document 10, WBS, API errors, and implementation. Retain three total
  attempts with 30/60-second retry waits. Add a dispatch-level integration
  test with blocking transfers that proves the active cap is enforced at two,
  a third transfer is rejected, and slots are released after completion or
  failure; do not let the daily byte quota mask concurrency behavior.
- **Historical evidence — 2026-11-19:** the original scan found transfer byte
  reservations and a 50-GiB daily cap but no explicit two-transfer admission
  guard. This predates the implementation below.
- **Current evidence — 2026-11-20:** `SyncService` reserves an active-transfer
  slot against `SYNC_GLOBAL_CONCURRENCY_CAP = 2`, raises
  `SYNC_CONCURRENCY_CAP` before transfer start, and releases it in `finally`.
  Retry wording and three-attempt behavior are aligned and tested.
  `tests/integration/test_sync_gate4.py` passed (9 tests), but it does not yet
  prove admission across three simultaneous `dispatch_sync` calls.
- **Implementation follow-up — 2026-11-21:** Document 8 marks the cap
  configurable, so `global_settings.sync_global_concurrency_cap` is now a
  positive-integer, audited setting with default 2, migration 007, and
  `/api/settings` read/update support. Dispatch enforces the active configured
  cap; database work is serialized without serializing uploads. Blocking
  transfer tests cover a rejected extra dispatch and slot release; the
  configuration, sync, schema, and Gate 2 focused selection passed (**42
  passed**), and scoped Ruff passed. The full current suite and Chromium
  setup/login E2E also pass; see KB-G0-7 and KB-D11-TEST-PYRAMID.

## To Do

### KB-REC-01 — Freeze the reconciliation baseline

- **WBS/Docs:** `old doc/Audits/NEXT_STEPS.md` R0; Document 11
- **Priority:** P0 · **Owner:** Copilot current session · **Updated:** 2026-11-21
- **Status:** Review
- **Depends on:** —
- **Acceptance:** record the exact commit hash and clean/dirty-tree state;
  install the repository's declared test dependencies; run collection and a
  fresh full-suite command; attach the raw result and named environment. Re-run
  rather than copy any eight-failure or coverage count from an older snapshot.
  Before handoff, inspect `app/data/manager.db*` and `app/data/secrets.key`,
  confirm whether they are tracked/distributed, and document any credential or
  runtime-data remediation in an implementation card.
- **DoD:** baseline commit, platform/Python versions, command, pass/fail counts,
  coverage, skipped/deselected tests, and repository-hygiene disposition are
  written in this card.
- **Historical evidence:** the 2026-11-19 reports and test runs are archived
  under `old doc/Audits/` and are not current acceptance evidence.
- **Fresh evidence — 2026-11-20:** Windows/Python 3.13 full run before the
  coverage additions reported **507 passed, 1 failed, 3 skipped, 76.87%
  coverage, 259 warnings**. The sole failure was missing `python-dotenv`; that
  already-declared dependency was installed and `tests/unit/test_main.py`
  passed (2 tests). The later clean `.venv-phase4` run used Python 3.13.18 and
  recorded 523 passed, 0 failed, 3 skipped, 79.85% coverage, and 258 warnings
  in 403.46 seconds; it did not meet the configured 80% coverage floor.
  `Audits/verification_log_2026-11-20.md` retains the command and summary, but
  not raw console output. This card also requires the exact baseline commit,
  tree state, and runtime-data hygiene disposition before it can be marked Done.
- **Focused evidence:** boundary/sync suite 12 passed; boundary, sync,
  documentation, and catalog acceptance 23 passed; SSE/cancellation 8 passed;
  native C1–C14 sampled native C2/C4/C10/C11 cases 4 passed; shell/health 5
  passed.
- **Environment:** local verification used `.venv-phase4` with Python
  3.13.18. Hosted Python 3.11/3.13 matrix, POSIX conformance, and live-server
  acceptance remain external.
- **Baseline capture — 2026-11-21:** commit
  `071711da582e8305e4a33feb9974204cb89e1e93`, Windows/Python 3.13.14; initial
  worktree was dirty only in the cleanup API/error/test/workboard changes from
  this task. `app/data/manager.db` and `app/data/secrets.key` are ignored by
  `.gitignore` and neither is tracked; only names/metadata were inspected.
  `python -m pytest --no-cov -q` raw output is retained at
  `dev_artifacts/reports/audit_fullsuite_no_cov_2026-11-21.txt`: **531 passed,
  1 failed, 3 skipped** in 393.37s. The sole failure was the dependency-boundary
  test finding `CleanupService`'s concrete `LocalFilesystem` fallback. That
  dependency has since been moved to explicit composition-root injection; a
  focused 40-test run passes. The full rerun after this fix passed **532
  passed, 0 failed, 3 skipped** with `--no-cov` in 395.10s; one shutdown
  thread warning and one queued-operation dispatch error were still logged.
  Raw output is retained at
  `dev_artifacts/reports/audit_fullsuite_no_cov_2026-11-21_after_boundary_fix.txt`.
  Follow-up isolated the warning to the performance acceptance benchmark,
  which closed SQLite directly while app workers were still running. The
  benchmark now calls the app shutdown hook in `finally`, and its regression
  test verifies all workers have stopped. The smoke test passes with thread
  warnings promoted to errors (1 test, 300.40s). The coverage-enabled full
  run after this fix passed (532 passed, 3 skipped) with 80.27% coverage;
  the exact post-fix `--no-cov` rerun passed **532 passed, 0 failed,
  3 skipped** in 410.22s, with no warning summary. Raw output is retained at
  `dev_artifacts/reports/audit_fullsuite_no_cov_2026-11-21_post_lifecycle_fix.txt`.

### KB-REC-02 — Normalize known specification conflicts

- **WBS/Docs:** Documents 5, 8, 10, 12; `old doc/Audits/NEXT_STEPS.md` R1
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-21
- **Status:** Review
- **Depends on:** —
- **Acceptance:** make one reviewable change set that (1) defines
  `app/docs/` as shipped documentation and excludes repository planning docs
  from runtime lookup, (2) decides and documents the sync two-transfer cap,
  retry count, and waits, (3) reconciles stale WBS `src/mcmanager/`, dependency,
  and fake-server references, and (4) adds the `/api/pages`,
  `/api/worlds/{world_id}/cleanup-policy`, and `/api/supervisor/tick`
  contracts or explicitly places them outside Document 10. Update governing
  documents and tests as contracts change.
- **DoD:** each decision has a source reference, implementation/test impact,
  and no implementation card claims compliance merely from route shape.
- **Evidence — 2026-11-21:** Document 12 now distinguishes app-only runtime
  dependencies from development tools, marks `app/config.py` as planned, and
  defines `app/docs/` as shipped content. `manager_content._documentation_root`
  confirms the runtime API reads only `app/docs/`. Documents 8 and the WBS
  agree on the two-transfer cap, three attempts, 30s/60s waits, and 50-GiB
  daily reservation cap; Document 10 now describes the additional page,
  cleanup-policy, and supervisor routes. Documents 12–14 and the WBS align
  fake-server option names with the harness; legacy aliases remain explicitly
  identified. Gate 2–5 pseudocode paths were normalized, while Gate 1 remains
  a historical/superseded example. The edited documentation was reviewed
  against `app/requirements.txt`, `app/services/sync.py`,
  `app/web/api/manager_content.py`, and existing route/fake-server behavior.

### KB-REC-03 — Verify API contract parity in bounded route groups

- **WBS/Docs:** Document 10; historical inventory
  `old doc/Audits/api_route_parity.csv`
- **Priority:** P1 · **Owner:** Unassigned · **Updated:** 2026-11-19
- **Depends on:** KB-REC-01
- **Acceptance:** extend `KB-G5-API-CONTRACT` with a route-by-route checklist
  split across auth/world, backup/sync/cleanup, admin/catalog, and
  notification/files/system groups. For every row record registration,
  session/CSRF/role/step-up authorization, input and response schema, status,
  envelope/error mapping, SSE classification, and a named test. Create one
  implementation card for each concrete missing behavior; do not turn this
  card into a second implementation backlog.
- **DoD:** all 110 catalog rows and the five SSE plus page, per-world cleanup,
  and supervisor routes are classified as verified, missing, approved
  deviation, or deliberately deferred.

### KB-REC-04 — Verify Document 7 schema semantics

- **WBS/Docs:** Document 7; historical inventory
  `old doc/Audits/schema_table_parity.csv`
- **Priority:** P1 · **Owner:** Unassigned · **Updated:** 2026-11-19
- **Depends on:** KB-REC-01
- **Acceptance:** add table/constraint acceptance for all 28 tables, including
  column types, nullability, defaults, indexes, foreign keys, delete tiers,
  uniqueness, migration ordering, rollback, and startup consistency checks.
  Group results by table and keep feature behavior on its owning card.
- **DoD:** name-level parity is not accepted as table-level evidence; each
  migration rule has a named test or an explicit approved deviation.
- **Implementation evidence — 2026-11-21:** migration 006 enforces immutable
  `restore_history` rows and sequential `sync_attempts.attempt_number`
  inserts; rollback now records a corrective restore outcome instead of
  rewriting history. Migration 007 adds the audited global sync cap. Focused
  migration, restore, sync, and Gate 2 tests passed, and the full suite passed
  on Windows/Python 3.13.14. The complete 28-table parity inventory and
  migration history review remain open; the tagged Gate 2 pseudocode remains
  historical and its sample SQL was not applied.

### KB-REC-05 — Seed stable requirement traceability

- **WBS/Docs:** Documents 4–14 and `ARCHITECTURE.md`;
  `old doc/Audits/planned_component_inventory.csv`
- **Priority:** P1 · **Owner:** Unassigned · **Updated:** 2026-11-19
- **Depends on:** KB-REC-02
- **Acceptance:** assign stable `REQ-*` identifiers to normative requirements,
  split compound statements, and map each to one governing source section,
  exact source symbols, candidate tests, and status
  (`MISSING/PARTIAL/PRESENT_UNVERIFIED/VERIFIED/DEFERRED/APPROVED_DEVIATION`).
  Begin with the reconciliation gaps in this board, then expand the documents.
  No overall completion percentage may be reported until this inventory has
  a stable denominator.
- **DoD:** every open reconciliation card links at least one requirement ID;
  every Done card links source and passing evidence.
- **Status evidence — 2026-11-19:** moved to Review. The archived
  `old doc/Audits/reconciliation_traceability.csv` is an initial ledger, not
  an exhaustive requirement denominator.
- **Current evidence — 2026-11-20:** current IDs and statuses are recorded in
  `Audits/reconciliation_traceability.csv`; the ledger remains limited to
  audited items and does not establish a completion percentage.

### KB-G0-7 — Restore full-suite test acceptance

- **WBS/Docs:** Document 11; AUD-2026-11-19-07
- **Priority:** P0 · **Owner:** Copilot current session · **Updated:** 2026-11-21
- **Status:** Review
- **Depends on:** —
- **Acceptance:** rerun the full suite with `pytest --no-cov` on the current
  tree and retain the exact command/output; triage and record current
  background-worker and SQLite resource warnings. The 2026-11-19 test failures,
  including shell,
  diagnostics, dependency-boundary, and realtime slow-client failures, are
  historical and must not be listed as current. Coverage-floor work remains
  on `KB-D11-COVERAGE`.
- **Historical evidence:** 2026-11-19 Windows and Linux test counts are
  preserved under `old doc/Audits/` and are not current.
- **Earlier evidence — 2026-11-20:** Windows/Python 3.13 full run before the
  coverage additions reported **507 passed, 1 failed, 3 skipped, 76.87%
  coverage, 259 warnings**. The sole failure was missing `python-dotenv`; that
  already-declared dependency was installed and `tests/unit/test_main.py`
  passed (2 tests).
- **Latest clean evidence — 2026-11-20:** `.venv-phase4`, Python 3.13.18,
  `.\.venv-phase4\Scripts\python.exe -m pytest -q --tb=no`: **523 passed,
  0 failed, 3 skipped, 79.85% coverage, 258 warnings** in 403.46s. Coverage
  missed the configured 80% floor, so release acceptance remains open.
  Exact summary is retained in `Audits/verification_log_2026-11-20.md`; raw
  console output and a clean `--no-cov` full-suite run are still required.
- **Current run — 2026-11-21:** `python -m pytest --no-cov -q` on
  Windows/Python 3.13.14 reported **531 passed, 1 failed, 3 skipped**, exit 1.
  The sole failure exposed the concrete filesystem import in `CleanupService`;
  that boundary is fixed and its focused suite passes (40 tests). One
  `PytestUnhandledThreadExceptionWarning` also reported the metrics publisher
  reading after the SQLite store closed. The named restore test passes alone
  with that warning promoted to an error. The subsequent full rerun reproduced
  it; warning triage below identifies the performance benchmark as the
  lifecycle leak and records its fix.
- **Rerun — 2026-11-21:** after injecting `FilesystemPort` from the composition
  root, `python -m pytest --no-cov -q` passed **532 tests, 0 failed, 3 skipped**
  in 395.10s. The metrics-publisher warning recurred, and an operation worker
  logged `PersistenceError: store not open`; shutdown lifecycle triage remains
  open. Raw output is retained at
  `dev_artifacts/reports/audit_fullsuite_no_cov_2026-11-21_after_boundary_fix.txt`.
- **Warning triage — 2026-11-21:** the performance acceptance benchmark was
  closing its SQLite store directly, leaving its six app workers running.
  `benchmarks/performance_acceptance.py` now invokes the app shutdown hook in a
  `finally` block. Its regression test asserts that every worker has stopped;
  that test passed alone with `PytestUnhandledThreadExceptionWarning` treated
  as an error (1 passed, 300.40s). A pre-fix multi-file reproduction yielded
  87 passed and one setup error at
  `test_backup_catalog_auth_shapes_and_durable_operation`; the leftover
  benchmark workers were reported there. A subsequent coverage-enabled full
  run passed **532 tests, 0 failed, 3 skipped** with 286 SQLite
  `ResourceWarning`s in 411.08s; the worker shutdown errors did not recur.
  Raw output and coverage data are retained at
  `dev_artifacts/reports/audit_fullsuite_coverage_2026-11-21_post_lifecycle_fix.txt`
  and
  `dev_artifacts/reports/audit_fullsuite_coverage_2026-11-21_post_lifecycle_fix.coverage`.
  The exact `python -m pytest --no-cov -q` rerun passed **532 tests, 0 failed,
  3 skipped** in 410.22s, with no warning summary; raw output is retained at
  `dev_artifacts/reports/audit_fullsuite_no_cov_2026-11-21_post_lifecycle_fix.txt`.
  The 286 SQLite `ResourceWarning`s appeared only in the coverage run and are
  recorded without suppression.
- **Latest merged-agent run — 2026-11-21:** Windows/Python 3.13.14,
  `python -m pytest -q`: **568 passed, 0 failed, 3 skipped**, 297 warnings,
  in 404.36s. Coverage was 80.97%; the configured 80% floor passed, but the
  Document 11 85% floor did not. The run did not reproduce the browser-startup
  SQLite reader errors after per-thread reader isolation. Raw test and coverage
  summaries are retained at
  `dev_artifacts/reports/audit_fullsuite_coverage_2026-11-21_merged_agent_changes.txt`
  and
  `dev_artifacts/reports/audit_fullsuite_coverage_2026-11-21_merged_agent_changes_coverage.txt`.
- **Final no-coverage rerun — 2026-11-21:** Windows/Python 3.13.14,
  `python -m pytest --no-cov -q`: **568 passed, 0 failed, 3 skipped** in
  394.96s; no warning summary. Raw output is retained at
  `dev_artifacts/reports/audit_fullsuite_no_cov_2026-11-21_merged_agent_changes.txt`.
- **Open-task follow-up — 2026-11-21:** test fixtures now close the raw SQLite
  store in a finalizer, and the five coverage-smoke containers register store
  cleanup. This reduced the full coverage run's SQLite `ResourceWarning`s from
  297 to **0** without suppression. The coverage run passed **573 tests, 0
  failed, 3 skipped**, at **81.67%** in 405.11s; the full `--no-cov` rerun
  passed **573 tests, 0 failed, 3 skipped** in 391.90s, also with no warning
  summary. Raw output is retained at
  `dev_artifacts/reports/audit_fullsuite_coverage_2026-11-21_followup_tests.txt`
  and `dev_artifacts/reports/audit_fullsuite_no_cov_2026-11-21_followup_tests.txt`.
  The full suite now has 576 collected cases; focused properties, SQLite, and
  history API tests passed with `ResourceWarning` treated as an error.

### KB-G5-CLEANUP-POLICY — Approve safe stale-backup and log cleanup policy

- **WBS/Docs:** Document 10 cleanup scopes; Documents 5 and 8
- **Priority:** P1 · **Owner:** Unassigned
- **Status:** Done
- **Acceptance:** obtain explicit product-owner decisions for backup eligibility,
  storage trigger and batch size/repetition, session threshold, references, log
  retention, and protected log categories; document safeguards and execution
  requirements.
- **Evidence:** user approved `stale_backups` (never worlds/records), eligible
  categories `session_end`, `manual`, `emergency`, `pre_restore`, default 3-day
  age / 7 sessions / 90% pressure, latest/category-floor guards,
  restore/sync-reference protection, and unlimited-by-default logs restricted
  to expired rotated historical files. On each cleanup run at/above the
  configured threshold, directly delete the oldest floor(50% of eligible stale
  backups) per pressured world; no stale-backup tombstone or grace period.
  Documents 5–10 record the policy.

### KB-G5-CLEANUP-SCOPES — Implement stale-backup and log cleanup

- **WBS/Docs:** WP 4.3 and WP 5.1; Documents 5, 8, and 10
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G5-CLEANUP-POLICY
- **Status:** Review
- **Owner:** Copilot current session · **Updated:** 2026-11-21
- **Acceptance:** implement policy-backed candidate discovery, preview, and
  execution for `stale_backups` and `logs`; enforce exclusions, retention floors,
  pressure gating, 50% oldest-first batch selection on every pressured run,
  reference/path/in-flight guards, and audits; keep all physical deletion inside
  `CleanupService`. Also verify scheduled execution and the stated scheduled-
  backup count cap. Do not tombstone stale backups or apply a grace period.
- **Current evidence:** migration 005, cleanup policy fields, stale-backup/log
  candidate planning, preview binding, direct stale-backup deletion, log
  deletion, scheduled dispatch, API scopes, and the scheduled-backup cap are
  implemented. The 2026-11-21 cleanup-rule change deletes the oldest floor(50%)
  of eligible stale backups on each pressured run, with no stale tombstone or
  grace period. Windows targeted acceptance passed: **105 passed** with
  `pytest --no-cov` across cleanup, backup catalog API, scheduler, Gate 3
  operation behavior, and schema migrations. The focused cleanup tests cover
  repeated batches, retention/reference protections, and immediate deletion of
  legacy tombstones. Scoped Ruff, Black, and isort passed. The
  repository coverage threshold fails when these targeted tests run with
  coverage enabled, so the focused pass intentionally used `--no-cov`. The
  latest dispatcher error-code mapping was included in the 105-test and scoped
  static-gate rerun. The API error contract was completed 2026-11-21.
- **Handoff completed — 2026-11-21:** Registered `BACKUP_PATH_UNSAFE`,
  `CLEANUP_PATH_UNSAFE`, and `CLEANUP_STORAGE_USAGE_INVALID` in the API error
  catalog and mapped `delete_backup` `RetentionError` values by their service
  code instead of defaulting every failure to `BACKUP_RETENTION_GUARD`. Added
  an unsafe-backup-path route regression test. Reran the focused command:
  `python -m pytest --no-cov -q tests/integration/test_cleanup_service.py
  tests/integration/test_backup_catalog_api.py
  tests/integration/test_scheduler_service.py
  tests/integration/test_gate3_operation_engine_behavior.py
  tests/integration/test_schema_migrations.py`
  Then rerun scoped Ruff/Black/isort, `node --check
  app/shell/static/operator_ui.js`, and
  `git -c core.whitespace=cr-at-eol diff --check`. Scheduled backups are
  explicitly categorized and enqueue a durable cleanup operation; the cap is
  three, with referenced artifacts retained even if that means exceeding it.

### KB-D12-2 — Track remaining service-layer architecture divergences

- **WBS/Docs:** Document 12 §§2, 4–5; Documents 8 and 12 define service
  boundaries and the target application layout.
- **Priority:** P2 · **Owner:** Unassigned
- **Acceptance:** review service-level SQL access and the partial command/query
  layer against the governing documents; record an explicit implementation
  decision or bounded migration work before treating the architecture
  divergence as resolved. Include the missing planned command/query handlers
  (CreateWorld/DeleteWorld/RenameWorld and the base, runtime, backup, restore,
  cleanup, sync, config, crash, and query handlers) and the missing SQLite
  `repository.py`, `operations_repo.py`, and `audit_repo.py`; decide whether to
  implement these boundaries or revise the architecture to match the
  consolidated implementation.
- **Current evidence:** services use the persistence abstraction but issue
  SQL through its connections; `app/commands/` currently contains only the
  world command module. `RuntimeService` is a facade while `WorldsService`
  retains lifecycle logic. No refactor or contract change is authorized by
  this documentation card alone. AUD-2026-11-19-04 also found a concrete
  service-to-infrastructure import; the code fix is separately tracked by
  `KB-G0-BOUNDARY-REGRESSION`.
- **Follow-up — 2026-11-21:** Java catalog verification was moved behind
  `MinecraftServerPort` and its composition-root adapter; 29 focused unit
  tests and scoped Ruff/isort passed. SQL access through `PersistencePort`
  remains an accepted current boundary; planned repository/command layers
  still need a bounded migration decision. The SSE route's direct platform
  tail import is a separate migration candidate; no broad refactor was made.

### KB-G8-CONTRACT — Complete Document 8 service contract acceptance

- **WBS/Docs:** Documents 8 and 11; related implementation cards in Gates 2–4
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G2-MIGRATION, KB-G3-1, KB-G3-2, KB-G3-3, KB-G4-VERIFY
- **Acceptance:** inventory Document 8 service requirements against the
  existing implementation cards; create or update an owning implementation
  card for each concrete missing behavior, and record a final acceptance map.
  Explicitly reconcile the two-simultaneous-transfer cap and sync retry
  schedule with implementation and WBS under `KB-G8-SYNC-CAP`. Feature-level
  tests and evidence stay on those owning cards, not on this
  contract-inventory card.
- **Current evidence:** operation, scheduler, audit, backup, restore, cleanup,
  and sync slices have focused tests; contract-wide service acceptance remains
  open. The 2026-11-19 missing-cap finding is historical; see the verified
  implementation and focused test evidence under `KB-G8-SYNC-CAP`.

### KB-G9-CONTRACT — Complete Document 9 concurrency contract acceptance

- **WBS/Docs:** Document 9; related implementation cards KB-G2-3 and KB-G3-2
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G2-3, KB-G3-2
- **Acceptance:** map every Document 9 concurrency, conflict, locking, and
  optimistic-version requirement to its owning implementation card; create or
  update a code card for each concrete missing behavior and record explicit
  exceptions. Race/interleaving tests are acceptance evidence on the owning
  implementation cards, not separate feature tasks.
- **Current evidence:** the conflict matrix and ConfigEdit version behavior
  have focused coverage; full Document 9 acceptance remains open.

### KB-D11-TEST-PYRAMID — Close the Document 11 test-pyramid gaps

- **WBS/Docs:** Document 11 §§1–3
- **Priority:** P1 · **Owner:** Copilot current session · **Updated:** 2026-11-21
- **Status:** In Progress
- **Acceptance:** inventory required unit, integration, and end-to-end flows;
  measure the repository-wide test distribution against Document 11's
  approximate 70/25/5 pyramid and identify cross-cutting test-infrastructure
  changes needed to sustain it. Individual feature tests remain on their
  implementation cards; this card is not a queue for completing those tests.
- **Current evidence:** focused domain and integration suites exist, but
  service-level unit coverage and full browser E2E flows are incomplete.
  AUD-2026-11-19-06 adds the unclosed canonical real-HTTP/process flows and
  contract-to-test mapping to this inventory.
- **Collection inventory — 2026-11-21:** `pytest --no-cov --collect-only -q`
  collected 576 cases after the follow-up tests: 212 unit (36.8%), 334
  integration (58.0%), and 30 adapter conformance (5.2%). A separate
  Playwright Chromium test now exercises first-run setup, login, and the
  operator home page (**1 passed**); the mocked browser contract suite remains
  7 passed and is not counted as real-browser E2E. Broader HTTP/process
  workflows, additional browser journeys, and the approximate 70/25/5
  distribution remain open; adapter conformance remains its own layer.

### KB-D11-COVERAGE — Meet documented test coverage floors

- **WBS/Docs:** Document 11 coverage requirements
- **Priority:** P1 · **Owner:** Unassigned
- **Acceptance:** raise every measured module to at least 80% coverage and
  overall coverage to at least 85%; preserve meaningful assertions and record
  the repository-level coverage floor. Feature-specific coverage is owned by
  each implementation card and is not deferred to this cross-cutting gate.
- **Current evidence:** coverage-focused additions raised several core modules,
  but the 85% overall and per-module 80% floors remain unachieved; per-module
  enforcement is absent from pytest configuration. Prior evidence includes
  backup catalog API coverage at 44.46% and the 2026-11-19 run at 76.24%.
- **Previous baseline — 2026-11-21:** clean Windows/Python 3.13.14 full coverage run:
  **568 passed, 0 failed, 3 skipped**, 297 warnings, 80.97% overall, in
  404.36s. The configured 80% floor passed; Document 11's 85% floor did not.
  Thirteen of 92 measured modules remain below 80%: Minecraft properties
  schema (65.62%), SQLite connection (76.00%), process base (73.74%), POSIX
  process (22.89%), server-properties service (75.47%), worlds service
  (72.97%), administration API (54.52%), backup-catalog API (62.76%),
  catalogs API (65.83%), history API (77.30%), manager-content API (79.85%),
  server-properties API (77.14%), and world-management API (73.88%). Raw
  output and report are retained at
  `dev_artifacts/reports/audit_fullsuite_coverage_2026-11-21_merged_agent_changes.txt`
  and
  `dev_artifacts/reports/audit_fullsuite_coverage_2026-11-21_merged_agent_changes_coverage.txt`.
- **Latest follow-up — 2026-11-21:** after adding on-disk property validation,
  SQLite diagnostics/lifecycle, and history-query regressions, Windows/Python
  3.13.14 `python -m pytest -q` passed **573 tests, 0 failed, 3 skipped** at
  **81.67%** overall, with no warning summary, in 405.11s. The coverage run
  measured 9,275 statements and 10 modules remain below 80%: process base
  (73.74%), POSIX process adapter (22.89%), server-properties service (75.47%),
  worlds service (72.83%), administration API (54.52%), backup-catalog API
  (62.76%), catalogs API (65.83%), manager-content API (79.85%),
  server-properties API (77.14%), and world-management API (73.88%).
  `properties_schema.py` is now 96.88%, SQLite `connection.py` 91.20%, and
  history API 95.74%. The overall 85% floor and remaining per-module floors
  are still open. Raw coverage output:
  `dev_artifacts/reports/audit_fullsuite_coverage_2026-11-21_followup_tests.txt`.

### KB-D11-ISO-25010 — Complete the quality-characteristic evidence map

- **WBS/Docs:** Document 11 ISO/IEC 25010 mapping
- **Priority:** P2 · **Owner:** Unassigned
- **Acceptance:** map each applicable quality characteristic in the testing
  strategy to a measurable acceptance check and recorded evidence; add
  compatibility, performance, and flexibility checks that are currently
  unverified, coordinating performance thresholds with KB-PERF-01.
- **Current evidence:** functional suitability, reliability, and security
  coverage remain partial; compatibility, performance, and flexibility have
  not been verified. AUD-2026-11-19-06/-09 records the incomplete evidence map
  and missing calibrated performance acceptance.
- **Evidence map — 2026-11-21:** Functional checks include the latest full
  suite (567 passed, 3 skipped) but manager lifecycle and route parity remain
  incomplete. Compatibility has hosted Windows/Ubuntu adapter conformance
  evidence (30 each), but live Minecraft variants and POSIX process behavior
  remain unverified. Security CI passed 61 checks on each of Ubuntu/Windows
  for the recorded commit; live proxy validation remains open. Performance
  has only the 300-second idle smoke; calibrated 50-client/1000-line-per-
  second runs and reference-host/RSS evidence are missing. Interaction now has
  one real-browser setup/login flow, but full workflows, 10-tab failover, and
  live proxy/reconnect behavior remain unverified. Reliability still has
  skipped symlink checks and no live RCON/NAS acceptance. Maintainability
  remains blocked by repository static findings. Flexibility has adapter
  conformance but no split-topology or storage-adapter substitution proof.
  Safety has cleanup/restore guard tests, while full destructive-route parity
  remains open. Coverage remains below both documented floors; see
  `KB-D11-COVERAGE` and `KB-D11-TEST-PYRAMID`.

### KB-DOC-EVIDENCE-QUALITY — Reconcile status and evidence claims

- **WBS/Docs:** This workboard; Documents 10, 11, and 13
- **Priority:** P2 · **Owner:** Unassigned
- **Acceptance:** make this workboard the sole current implementation-status
  source; define how slice-level and gate-level statuses differ; reconcile
  duplicate gate/work-package summaries; narrow route and authorization
  claims to verified scope pending KB-G5-API-CONTRACT; and record exact
  commands, dates, platforms, and test scope where historical counts differ
  (including the 36-test and 97-test Gate 1 results). Reconcile the dated
  full-suite failures, static-gate counts, the implemented cleanup-policy API
  card's status, and claims that tests were or were not run. Do not combine
  overlapping test counts or present historical results as fresh.
- **Current evidence:** gate and work-package summaries are repeated in this
  board; route/auth claims require careful scoping against known exceptions;
  and the 36-test and 97-test Gate 1 records need exact test-selection
  provenance. The 2026-11-20 audit found the workboard had been incorrectly
  archived and that `Audits/` was missing; both locations have been restored.
  Stale snapshots remain under `old doc/`, while `Audits/` now contains current
  evidence. Current full-suite and coverage outputs are retained under
  `dev_artifacts/reports/` and summarized in
  `Audits/verification_log_2026-11-20.md`. The exact provenance for the
  historical 36-test and 97-test Gate 1 results, route/auth claim scoping, and
  cleanup-policy API card status still need reconciliation.

### KB-G5-6 — Complete real workflows for the 17 shell modules

- **WBS:** WP 5.3
- **Priority:** P1 · **Owner:** Unassigned · **Updated:** 2026-11-19
- **Depends on:** KB-G5-3, KB-G5-4, KB-G5-5
- **Acceptance:** modules are functional workflows, not scaffold fragments;
  manager/world context switching works; navigation stays in-place and obeys
  Document 4 tokens and 40px control geometry.
- **Progress:** Partial. `operator_ui.js` now supplies the persistent entry
  point, first-run/login flow, manager/world context switching, and workflows
  for world actions, backups/restores, users/roles/devices, settings, schedules,
  templates, runtimes, files/logs, sync activity, audit, notifications, and
  backup cleanup. Manager Backup is enabled. Follow-up implementation added
  authenticated documentation, manager log browsing, sync-target CRUD,
  guarded server-properties editing, per-world cleanup-policy editing, and
  manager-wide cleanup-policy editing.
- **Remaining code:** manager restore/restart/update/rollback UI after those
  backend contracts are implemented.
- **Evidence:** `node --test tests/browser/test_gate5_browser.test.cjs` passed
  (7 tests), including actual `operator_ui.js` navigation across all 17
  modules, setup/login, Manager Backup submission, style tokens, and 10-tab
  stream sharing. Two retained `shell.js` prototype checks are labeled legacy
  and are not counted as production UI coverage. Focused API checks for the
  2026-11-19 follow-up passed (11); live browser validation confirmed theme,
  notification dropdown, step-up dialog, global policy submission, and
  updated step-up/theme behavior. Broader full workflow acceptance remains open.
- **Real-browser evidence — 2026-11-21:** Playwright Chromium setup/login
  workflow passed (1 test) against a disposable local app fixture. This does
  not close full operator workflow acceptance; other authenticated flows and
  deployment/proxy behavior remain unverified.

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
- **Progress:** Partial. `POST /api/manager/backup` creates a durable Backup
  operation, writes a consistent SQLite snapshot through the SQLite backup
  API, packages it in the standard ZIP+SHA artifact format, and registers a
  `manager_config` artifact with `world_id = NULL`. The Manager Maintenance UI
  now exposes this action. Terminal operation audit is provided by
  OperationService.
- **Remaining:** manager restore/restart/update/rollback and their UI remain
  unimplemented; documentation, manager-log, and sync-target workflows do not
  satisfy lifecycle acceptance.
- **Current implementation update — 2026-11-20:** uninitialized manager
  responses now include stable `updated_at: null`; focused manager response
  assertions passed. Manager restore/restart/update/rollback remain blocked on
  their approved safety contracts.
- **Verification:** manager-backup artifact test (1 passed); combined bootstrap
  and catalog tests (14 passed); backup/restore coordination tests (31 passed).
- **Blocked product decisions:** Manager restore needs a defined restore scope,
  encryption-key handling, schema compatibility, and active-session/process
  recovery. Manager restart needs a host supervisor/relaunch contract and
  in-flight operation handling. Update needs trusted sources, package
  verification, staged replacement, migration, and health-check rules.
  Rollback needs target selection, data compatibility, and partial-failure
  recovery. Restore, restart, update, and rollback remain 501; restart
  additionally requires step-up authorization.

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
- **Evidence:** The 2026-11-19 audit run on Windows / Python 3.13 reported
  Ruff 39 errors, Black 84 files needing formatting, isort 7 failures, mypy
  238 errors in 23 files, and a nonzero import-linter result. The latest
  2026-11-20 checks report 41 repository-wide Ruff findings and 232 broad
  service mypy errors; compileall and scoped Ruff on touched files pass. No
  newer Black, isort, or import-linter results are available. Earlier
  snapshots (Ruff 46, Black 76, isort 9, mypy 217) are historical and must not
  be used as current baselines. Document 12 §8 records the canonical commands.
- **Fresh evidence — 2026-11-21:** repository-wide checks report Ruff **49
  findings**, Black **61 files** needing formatting, isort **4 files** with
  unsorted imports, and mypy **226 errors in 21 files**. Scoped Ruff, Black,
  and isort pass for the two files changed for worker cleanup. The import-linter
  package is installed, but invoking its console entry point exits 1 after
  printing only `modules`; no interpretable contract report was produced.
  Raw outputs are retained under `dev_artifacts/reports/audit_*_2026-11-21.txt`.
- **Post-agent rerun — 2026-11-21:** `ruff check app tests` reports **22
  errors**; `black --check app tests` reports **61 files** needing formatting;
  `isort --check-only app tests` reports **4 files**; `mypy app` reports
  **226 errors in 21 files** after correcting a newly introduced JavaDetection
  re-export issue. Scoped Ruff/isort passed for the changed Python
  files; scoped Black still flags pre-existing formatting in some touched
  modules, and broad formatting was not applied. Logs are retained as
  `dev_artifacts/reports/audit_ruff_2026-11-21_post_agents.txt`,
  `audit_black_2026-11-21_post_agents.txt`,
  `audit_isort_2026-11-21_post_agents.txt`, and
  `audit_mypy_2026-11-21_final.txt`; the intermediate 227-error run is
  retained as `audit_mypy_2026-11-21_post_agents.txt`.
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
- **Deployment code:** `deploy/nginx/mcmanager.conf` and
  `docs/deployment.md` now provide a TLS-terminating, unbuffered SSE proxy
  example. `create_app(trusted_proxy_hops=1)` opts into exactly one trusted
  proxy hop for forwarded client address and HTTPS detection; the default is
  zero. The focused forwarded-HTTPS cookie test passed.
- **Remaining:** Nginx is unavailable on the current host, so config syntax
  and live proxy/reconnect behavior remain unverified. Document 11's
  50-client/1Hz numbers are not a benchmark result; calibrated stream
  performance and CPU-flatness remain blocked on reference hardware.

### KB-PERF-01 — Calibrate and pass performance release acceptance

- **WBS:** Gate 5; Document 11 §4.2
- **Priority:** P1 · **Owner:** Unassigned
- **Blocked by:** A documented reference host and reproducible measurements
  must be supplied; thresholds must not be fabricated.
- **Acceptance:** record CPU/RAM/storage profile; measure 300-second idle CPU
  and process RSS (not `tracemalloc` allocation peak), 50-client 1Hz stream
  fan-out, and 1000-lines/sec ingestion with measured tail latency; ensure the
  benchmark exercises these workloads, commit justified
  `benchmarks/thresholds.json` values, and pass its acceptance test.

## Backlog

### KB-DOC-LEGACY-ARCHIVE — Clarify historical documentation status

- **WBS/Docs:** Repository structure; AUD-2026-11-19-11
- **Priority:** P3 · **Owner:** Copilot current session · **Updated:** 2026-11-21
- **Status:** Review
- **Depends on:** —
- **Acceptance:** inventory the historical materials in `old doc/`,
  `Prototypes/`, and root-level planning/documentation files; identify the
  canonical current plans and any actual runtime consumers; label the
  remaining material as authoritative, historical, or redundant. Preserve
  current numbered plan documents in `docs/`; do not move or delete files
  without an explicit decision supported by the inventory.
- **Current evidence — 2026-11-21:** `old doc/` contains 18 top-level files
  and 26 recursively, including older Document 4–9 copies, prior
  reconciliation/audit snapshots, and legacy architecture/implementation
  notes. `Prototypes/` contains 96 files across Experiment, Legacy, and V1–V4.
  Current authoritative plans are `docs/Document_4`–`Document_14`,
  `docs/ARCHITECTURE.md`, `docs/WORKBOARD.md`, and the current `Audits/`
  records. No runtime source references `old doc/` or `Prototypes/`; the
  repository-structure test asserts that `Prototypes/` exists. All archived
  files remain historical references; no deletion or duplicate claim is
  authorized by this inventory.

### KB-G5-API-CONTRACT — Audit full Document 10 contract parity

- **WBS/Docs:** Document 10 route catalog, envelope, auth, and error contracts
- **Priority:** P1 · **Owner:** Unassigned
- **Depends on:** KB-G5-3, KB-G5-4, KB-G5-5
- **Acceptance:** compare every documented API route against registration,
  authorization (including session, CSRF, role, and step-up requirements on
  every mutating route), request/response schema, status, envelope, and error
  mapping; create or update an owning implementation card for each concrete
  missing behavior and record explicit `NOT_IMPLEMENTED` exceptions. Feature
  checks remain acceptance evidence on their implementation cards. Include
  manager lifecycle routes and all cleanup scopes; this is a parity inventory,
  not a substitute for implementing the owning feature cards.
- **Current evidence:** Server-properties editing,
  permission-grant enforcement, diagnostics/version metadata, sync-target
  CRUD, documentation/log browsing, and per-world cleanup-policy editing have
  implementations, but lack feature-level acceptance.
  Full parity remains open; additional concrete route or service deltas may
  be discovered.
- **Route fixes — 2026-11-21:** corrected the runtime-config PATCH step-up
  requirement and aligned restore and world cleanup-policy grants with
  `world.restore.restore` and `world.cleanup`. Added two integration
  regressions; both passed, and scoped Ruff passed. This closes those identified
  mismatches only; the full route-by-route inventory and remaining settings
  visibility decision are still open.
- **History-query regressions — 2026-11-21:** added authenticated API checks
  for invalid audit/notification filters and pagination, ISO/epoch date
  filters, multi-field audit sorting, and missing audit/notification IDs.
  The focused API/schema/properties set passed **61 tests** with
  `ResourceWarning` promoted to an error. This adds coverage but does not close
  the Document 10 route-by-route inventory.
