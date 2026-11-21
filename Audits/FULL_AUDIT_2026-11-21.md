# Full repository audit — 2026-11-21

## Executive result

**The repository is substantially implemented, but is not release-ready.** The
latest local no-coverage suite passed, but not every documented feature has
complete acceptance tests, the documented coverage requirement is unmet, and
multiple external/platform checks remain open. Several implementation and
documentation inventories are still explicitly marked Review, To Do, or
Blocked on the workboard.

The audit baseline is commit `7edd37f` (`Complete audit remediation and world
lifecycle support`). The worktree was clean at the start of this audit.

| Area | Finding |
|---|---|
| Current Python tests | 580 collected: 212 unit, 338 integration, 30 adapter-conformance. |
| Latest full run | `python -m pytest --no-cov -q`: 577 passed, 3 skipped, 420.06s on Windows. This was the same source tree immediately before commit `7edd37f`; the raw console output is not retained in `Audits/`. |
| Coverage | **Not remeasured at 580 tests.** Latest retained coverage run is 573 passed / 3 skipped at 81.67%, below Document 11's 85% overall target; 10 measured modules were below 80%. |
| Static gates, rerun during this audit | Ruff: 21 findings; Black: 66 files need formatting; isort: 4 files; mypy: 226 errors in 21 files. `lint-imports` executable is unavailable, so its configured contracts were not verified. |
| Browser | The mocked browser contract suite has 7 tests. One Playwright setup/login flow has prior evidence, but it was not rerun at `7edd37f`; full operator workflows remain open. |
| Docs/plans | Numbered documents are mostly aligned with recent product decisions, but Document 8 contains a direct cleanup-policy contradiction. Document 11's coverage floor conflicts with `pyproject.toml`; current workboard and audit-ledger summaries lag the latest test count. |

Passing tests establish behavior only for the exercised cases. They do not
close the route-by-route, service-contract, concurrency-matrix, live-server,
deployment, or performance acceptance still tracked below.

## Scope and method

This review reconciled the current `app/` module tree and `tests/` tree against
the current numbered product documents, `docs/ARCHITECTURE.md`, `docs/wbs.txt`,
`docs/WORKBOARD.md`, the active `Audits/` records, and `pyproject.toml`. It
also reran test collection and repository-wide Ruff, Black, isort, and mypy
checks. No live Minecraft instance, Nginx deployment, hosted CI workflow, or
reference-hardware benchmark was run as part of this audit.

Status terms used below:

- **Done/verified:** implementation exists and the cited focused or full test
  evidence exercised it. This does not imply the complete numbered-document
  contract is accepted.
- **Implemented; acceptance open:** code exists, but route, scenario, browser,
  cross-platform, or external evidence remains incomplete.
- **Missing:** a documented capability has no functioning implementation or
  is explicitly returned as `501 NOT_IMPLEMENTED`.
- **Architecture decision needed:** the current code works through a
  consolidated design that differs from the target package plan; decide
  whether to refactor or revise the plan before treating it as a defect.

## Feature and module inventory

### Implemented and exercised

| Component / modules | Current evidence and scope |
|---|---|
| Domain and persistence: `app/domain/`, `app/infrastructure/sqlite/connection.py`, `app/infrastructure/sqlite/migrations.py`, `app/migrations/` | The domain, SQLite persistence, migration path, and append-only restore/sequential sync-attempt rules are implemented. Migrations 006–008 add schema semantics, the configurable sync cap, and stable world paths/start concurrency. `tests/integration/test_schema_migrations.py` and the full no-coverage run pass. Complete 28-table schema acceptance remains open under `KB-REC-04`. |
| World lifecycle: `app/services/worlds.py`, `app/services/world_paths.py`, `app/web/api/world_management.py`, `app/web/api/system.py` | World creation provisions a stable ID-based directory, keeps EULA acceptance explicit, preserves paths on rename, and dispatches independent starts with a configurable limit (default 3; `0`/`NULL` unlimited). Failure isolation and thread-local SQLite writer connections are tested. The latest full suite passed; `KB-G3-6` records the feature evidence. |
| Authentication and authorization: `app/services/auth.py`, `app/web/middleware.py`, `app/web/api/auth_routes.py`, `app/web/api/administration.py` | Login/session/step-up, CSRF, permission grants, lockout, and security acceptance have local tests. A hosted security workflow previously passed 61 checks per OS on commit `071711d`; it has not been rerun on `7edd37f`. |
| Operations, scheduler, and realtime: `app/services/operations.py`, `app/services/scheduler.py`, `app/services/realtime.py`, `app/web/streams/` | Durable operations, scheduler behavior, SSE replay/cursors, and selected cancellation/metrics behavior have focused and full-suite coverage. Full Document 8/9 acceptance, live-proxy replay, and the complete topic/workflow inventory remain open. |
| Backup, restore, cleanup, and sync: `app/services/backup.py`, `restore.py`, `cleanup.py`, `sync.py`, `app/web/api/backup_catalogs.py` | ZIP/checksum backup, SQLite online manager backup, corrective restore history, stale-backup/log cleanup, and sync caps/retries are implemented. Stale backups are directly deleted—no new tombstones or grace period—when pressure triggers an oldest-first floor(50%) eligible batch. Cleanup policy approval is Done; implementation/API acceptance is still Review. |
| Minecraft/process adapters: `app/ports/process_control.py`, `app/platform/process/`, `app/infrastructure/minecraft/`, `tests/adapters/` | Windows and fake-server process adapters, readiness/EULA/RCON/property/Java checks, and conformance tests exist. Hosted adapter conformance previously passed 30 tests on Windows and Ubuntu at `071711d`; full live Minecraft variants and the Forge shutdown issue remain open. |
| Operator shell: `app/shell/static/operator_ui.js`, `tests/browser/test_gate5_browser.test.cjs` | Navigation across 17 shell modules and selected workflows are implemented; the mocked-DOM suite has 7 passing tests. That is not full end-to-end workflow acceptance. |
| Manager content: `app/web/api/manager_content.py` | Safe Markdown-source and manager-log APIs exist. The curated runtime content directory `app/docs/` currently contains only `.gitkeep`. |

### Missing implementation or function-level gaps

| Missing capability | Exact module / functions | Required work |
|---|---|---|
| Manager restore, restart, update, rollback | `app/web/api/administration.py`: `manager_restore`, `manager_restart`, `manager_update`, `manager_rollback`; all currently call `_blocked_manager_action` and return 501. `app/services/manager_lifecycle.py` currently provides only `request_backup` and `execute_backup`. | First approve recovery, key/encryption, schema-compatibility, supervisor/relaunch, trusted-update, rollback-target, and partial-failure contracts. Then add durable service methods, worker/recovery behavior, audit coverage, UI actions, and integration/E2E tests. See `KB-G5-8`. |
| Manager lifecycle UI | `app/shell/static/operator_ui.js` | Restore/restart/update/rollback actions are not implemented; add only after the backend contracts and routes are approved. |
| Curated operator documentation | `app/docs/` | Runtime documentation endpoints are present, but no curated Markdown documents are shipped. Add approved operator content or keep this feature explicitly future-facing. |
| Planned command/query and SQLite repository layers | `app/commands/` currently contains only `world.py`; `app/infrastructure/sqlite/` has no `repository.py`, `operations_repo.py`, or `audit_repo.py`. | This is an architecture-plan divergence, not proof that existing behavior is broken. Decide whether to implement the layers or revise Documents 8/12 to describe the consolidated service/SQL-through-`PersistencePort` design. Also review `WorldsService` retaining lifecycle logic behind the `RuntimeService` facade and the SSE route's direct platform-tail dependency. See `KB-D12-2`. |

The manager routes are explicitly declared in Document 10, but declaration is
not implementation. Their `501` responses are also present in the error
catalog; the product remains incomplete until the safety decisions above are
made.

### Implemented, but not fully accepted

- **Document 10 API:** source has route handlers across
  `app/web/api/{auth_routes,world_management,system,backup_catalogs,catalogs,
  configuration,administration,history,manager_content,server_properties}.py`.
  The workboard still requires an endpoint-by-endpoint check of registration,
  auth/grants, CSRF/step-up, schemas, statuses, envelopes, and error mapping.
  Specific open items include settings-visibility policy, history/query
  parity, cleanup-policy and backup/sync acceptance, and the 501 manager routes.
- **Document 8 service contract:** service slices have tests, but no completed
  requirement-to-source-to-test matrix. Record missing behaviors as feature
  tasks rather than claiming acceptance from nearby tests (`KB-G8-CONTRACT`).
- **Document 9 conflict model:** selected conflict and optimistic-version
  cases are tested; a complete matrix/race inventory and explicit exceptions
  have not been accepted (`KB-G9-CONTRACT`).
- **Cleanup scopes:** cleanup code and focused tests exist, but
  `KB-G5-CLEANUP-SCOPES` remains Review for full scope, reference/path/in-flight
  guards, repeated pressure batches, scheduled behavior, and final acceptance.
- **Logs, metrics, and SSE:** selected replay, fan-out, and slow-client cases
  exist. `KB-G1-LOG-REPLAY` and `KB-G5-10` still require live-proxy/client
  recovery and deployed cadence evidence.
- **Security and adapter CI:** hosted evidence is for `071711d`, not current
  `7edd37f`; rerun on the audited commit before using it as current release
  evidence.

## Test inventory and unanswered test question

**No: all tests required by the plans are not yet written or accepted.** The
current 580-test Python collection is substantial and passes without coverage,
but Document 11 specifies a wider set of measurable and external acceptance
checks. The 212/338/30 distribution is approximately 36.6% unit, 58.3%
integration, and 5.2% adapter-conformance; it is not the documented
approximately 70/25/5 unit/integration/E2E pyramid. The one Playwright
setup/login test is separate from pytest collection and does not close the
other journeys.

Known test work still open:

1. **Coverage:** rerun coverage on the current 580-case tree. The latest
   retained run (573 cases) reached 81.67%, below the 85% overall contract.
   The latest retained report lists these 10 modules below 80%:
   `app/platform/process/base.py` (73.74%),
   `app/platform/process/posix.py` (22.89%),
   `app/services/server_properties.py` (75.47%),
   `app/services/worlds.py` (72.83%),
   `app/web/api/administration.py` (54.52%),
   `app/web/api/backup_catalogs.py` (62.76%),
   `app/web/api/catalogs.py` (65.83%),
   `app/web/api/manager_content.py` (79.85%),
   `app/web/api/server_properties.py` (77.14%), and
   `app/web/api/world_management.py` (73.88%). Re-measure before treating
   those percentages as current. `pyproject.toml` enforces only a global 80%
   floor and has no per-module floor, so tooling does not enforce Document 11.
2. **API contract:** add/finish route-specific tests for request/response
   schema, access/grants, CSRF/step-up, status codes, canonical envelopes,
   idempotency, and error mappings across every Document 10 route. Existing
   history and authorization regressions cover only selected cases.
3. **Operation/concurrency contracts:** verify every Document 8 operation
   path and the full Document 9 conflict matrix, including races and stale
   versions. Required cases include interrupted restore checkpoints,
   kill-supersedes-stop, scheduler disable/delete races, cleanup-vs-sync/
   restore references, and parallel dispatch bounds.
4. **Real browser E2E:** beyond setup/login, cover world create/start/stop,
   backup/restore, EULA, files/logs, settings/cleanup, sync-target CRUD,
   audit/notifications, and error/recovery journeys. Verify multi-tab
   leader failover and authenticated SSE in the browser.
5. **Process/Minecraft:** run POSIX conformance on current code; run disposable,
   consent-safe Vanilla/Paper/Fabric/Forge acceptance. Diagnose
   `KB-G1-FORGE-SHUTDOWN`: Forge 1.20.1-47.4.10 / Java 21.0.13 saved data and
   stopped RCON after `stop`, but the process remained alive beyond 180 seconds
   and was force-terminated. Also run symlink, live RCON/NAS, and restart
   re-attachment cases on supported hosts.
6. **Deployment/performance:** test Nginx syntax and live TLS/proxy/SSE
   buffering/reconnect behavior. On documented reference hardware measure
   300-second idle CPU and RSS, 50-client 1Hz fan-out, and 1,000-line/sec log
   ingestion/tail latency. Do not invent thresholds.
7. **Quality-characteristic evidence:** finish the Document 11
   ISO/IEC 25010 map for compatibility, flexibility, interaction,
   reliability, safety, and maintainability.

The current full no-coverage pass does not answer the coverage question and
does not convert untested or external requirements into passing tests.

## Documentation and system-plan coherence

| Source | Assessment |
|---|---|
| Documents 4–7 | Generally aligned to the current architecture and recent schema decisions. Document 6 distinguishes world tombstoning from stale-backup deletion; the user rule prohibits stale-backup tombstones, not world-record tombstones. Complete schema parity remains open. |
| Document 8 | **Internal contradiction:** the CleanupService summary table says `StaleBackup:Tombstone/Purge` (line 16), while the cleanup flow later says direct deletion with no tombstone/grace period (line 58), and the agreed policy does not tombstone stale backups. Correct the table entry. |
| Document 9 | World-start admission (default 3, configurable, `0`/`NULL` unlimited) is aligned with the implementation. Full conflict/race acceptance remains incomplete. |
| Document 10 | Recent cleanup, concurrency, stable-directory, and EULA contracts are present. It documents manager lifecycle routes that intentionally return 501. Full route/request/auth/error parity remains open, so the document is not a completion claim. |
| Document 11 | **Configuration conflict:** requires 85% overall plus 80% per module; `pyproject.toml` only fails below 80% overall and has no per-module enforcement. The test pyramid is also not met. Choose and implement the gate; do not lower the plan silently. |
| Document 12 | Current code is broadly within `app/`, but its proposed command/repository layout is not fully implemented. The divergence is already identified by `KB-D12-2`; make an explicit architecture decision. Current static gates are red. |
| Documents 13–14 | Process and Minecraft contracts match substantial adapters and fake-server tests. Real Minecraft variants, current-commit hosted runs, live proxy/RCON/NAS, and some process edge cases remain unverified. |
| `docs/WORKBOARD.md` | Still the declared source of truth, but its roll-ups contain stale 523/573 counts alongside a newer 577 result. Status sections also conflict with explicit card fields: e.g. `KB-G0-7` is under “To Do” but marked Review, and `KB-G5-CLEANUP-POLICY` is under “To Do” but marked Done. Reconcile section placement, card status, and repeated gate summaries. |
| `Audits/verification_log_2026-11-20.md` | Contains useful history through the 573-test/81.67% run, but does not record the later 577-pass no-coverage run or current commit. Keep historical entries; append the new baseline and distinguish no-coverage from coverage evidence. |
| `Audits/reconciliation_traceability.csv` | Useful partial ledger, not exhaustive. Its suite/authorization rows still cite 573 tests. Refresh evidence against `7edd37f`; continue to avoid an overall completion percentage until the denominator is complete. |
| Gate pseudocode, WBS, archived plans | `docs/gate1_pseudocode.txt` through `gate5_pseudocode.txt` explicitly label themselves historical/superseded, which is coherent. `old doc/` and `Prototypes/` are historical references, not current plans. Keep the numbered documents and workboard authoritative; do not implement from archived pseudocode. |
| Deployment docs | `docs/deployment.md` correctly states that the Nginx example has not been exercised against a live deployment. This is an open verification item, not stale evidence. |
| Runtime docs content | The runtime documentation API is implemented, but `app/docs/` has no curated content beyond `.gitkeep`; this remains future content, not a broken repository-planning-doc lookup. |

## Complete action list

The following consolidates the currently open workboard cards and audit
findings. Existing card IDs remain the tracking references; duplicate
inventories should be reconciled rather than implemented twice.

### P0 — current acceptance and evidence

1. **Freeze the current baseline** (`KB-REC-01`, `KB-G0-7`): retain the exact
   command and raw output for the 580-case run at `7edd37f`; record platform,
   Python version, clean-tree state, skips, warning summary, and runtime-data
   hygiene. The prior 577/3 result passed, but the raw output is not currently
   stored under `Audits/`.
2. **Refresh current status evidence** (`KB-DOC-EVIDENCE-QUALITY`,
   `KB-REC-05`): update the workboard roll-ups, `Audits/verification_log`,
   and traceability CSV with the current 580-collected/577-passed run; keep
   573/81.67% clearly labeled as the last coverage run, not the current case
   count.
3. **Resolve and enforce coverage gates** (`KB-D11-COVERAGE`): rerun coverage
   at 580 cases, reach at least 85% overall and 80% per measured module, and
   configure enforcement consistent with Document 11.

### P1 — feature and contract completion

4. **Finish API parity** (`KB-G5-API-CONTRACT`, `KB-REC-03`, `KB-G5-3`,
   `KB-G5-CLEANUP-POLICY-API`): inventory each documented route and handler;
   verify auth/grants, CSRF/step-up, request/response, status/envelope, error
   mapping, and tests. Include world management, backup/restore, cleanup,
   sync, catalogs/settings, administration/history, server properties,
   documentation/logs, and manager routes. Resolve the settings-visibility
   product decision and record `NOT_IMPLEMENTED` exceptions explicitly.
5. **Implement manager restore/restart/update/rollback** (`KB-G5-8`): approve
   the safety contracts first, then add service functions, durable operations,
   recovery, audit, UI, and regression/E2E tests for the four 501 handlers.
6. **Close service and concurrency inventories** (`KB-G8-CONTRACT`,
   `KB-G9-CONTRACT`, `KB-G4-VERIFY`, `KB-G8-SYNC-CAP`): map each Document 8/9
   requirement to implementation and evidence; add missing race/matrix cases.
   Complete supported-host symlink checks and live RCON/NAS acceptance.
7. **Complete cleanup acceptance and fix its docs** (`KB-G5-CLEANUP-SCOPES`,
   `KB-REC-02`): change Document 8's stale `Tombstone/Purge` table label;
   verify previews, repeated 50% batches under pressure, exclusions,
   retention/reference/path/in-flight guards, audit records, and scheduled
   execution. Preserve the no-tombstone/no-grace rule for stale backups.
8. **Complete real operator workflows** (`KB-G5-6`): add browser E2E for
   the workflow families listed above, multi-tab failover, and error recovery.
   Keep the existing 7 mocked-browser tests distinct from the 1 real-browser
   setup/login test.
9. **Revalidate process/Minecraft behavior** (`KB-G1-6`, `KB-G1-MINECRAFT`,
   `KB-G1-FORGE-SHUTDOWN`): rerun hosted conformance on `7edd37f`, diagnose
   Forge stop behavior, and run approved disposable Vanilla/Paper/Fabric/
   Forge tests. Record exact OS/server/Java and completed checks.
10. **Verify deployed metrics and proxy** (`KB-G5-10`): validate Nginx
    syntax, live HTTPS/ProxyFix trust, SSE buffering/replay, and cadence in a
    deployment; do not count mocked stream tests as deployment acceptance.
11. **Pass calibrated performance acceptance** (`KB-PERF-01`): obtain a
    reference host, record hardware, measure idle CPU/RSS, 50-client fan-out,
    and 1,000-line/sec ingestion, then justify thresholds and retain results.
12. **Restore static gates** (`KB-G0-5`): resolve current 21 Ruff findings,
    66 Black files, 4 isort files, 226 mypy errors/21 files, and restore an
    executable import-linter gate. Do this in bounded changes without broad
    unrelated formatting.
13. **Complete the schema audit** (`KB-REC-04`): finish the table/constraint/
    FK/index/default/migration and rollback inventory for all 28 schema
    tables, including the latest migrations and deletion-tier rules.

### P2 — plan and evidence coherence

14. **Make the architecture decision** (`KB-D12-2`, `KB-D12-1`,
    `KB-G0-BOUNDARY-REGRESSION`): choose whether to add repository/command
    layers or revise the target architecture. Record the direct SQL and SSE
    platform-tail boundaries and test the chosen rules.
15. **Finish the domain and traceability maps** (`KB-G2-ENTITY-MODEL`,
    `KB-G2-DOMAIN`, `KB-REC-05`): map all domain entities/transitions and
    schema requirements to implementation and tests.
16. **Close documentation decisions** (`KB-DOC-PLAN-COHERENCE`,
    `KB-DOC-PSEUDOCODE-DECISION`, `KB-DOC-WBS`, `KB-DOC-LEGACY-ARCHIVE`):
    verify current runtime-doc references, keep pseudocode clearly historical,
    finish WBS/plan inventory, and distinguish canonical plans from archives.
17. **Complete ISO/IEC 25010 acceptance** (`KB-D11-ISO-25010`) and the
    remaining workboard card/status reconciliation (`KB-DOC-EVIDENCE-QUALITY`).
18. **Add curated runtime docs** under `app/docs/` if the operator-facing
    documentation feature is intended for the release; otherwise mark it
    explicitly deferred.

## Workboard queue cross-check

Open/review/blocked/backlog cards found during this audit:

- **Review:** `KB-G5-3`, `KB-G5-CLEANUP-POLICY-API`, `KB-G4-VERIFY`,
  `KB-G1-LOG-REPLAY`, `KB-DOC-PLAN-COHERENCE`,
  `KB-DOC-PSEUDOCODE-DECISION`, `KB-DOC-WBS`,
  `KB-G0-BOUNDARY-REGRESSION`, `KB-G8-SYNC-CAP`.
- **To Do / still open:** `KB-REC-01`–`KB-REC-05`, `KB-G0-7`,
  `KB-G5-CLEANUP-SCOPES`, `KB-D12-2`, `KB-G8-CONTRACT`,
  `KB-G9-CONTRACT`, `KB-D11-TEST-PYRAMID`, `KB-D11-COVERAGE`,
  `KB-D11-ISO-25010`, `KB-DOC-EVIDENCE-QUALITY`, `KB-G5-6`,
  `KB-G1-FORGE-SHUTDOWN`, `KB-G5-8`.
- **Blocked:** `KB-G1-MINECRAFT`, `KB-G0-5`, `KB-G5-10`, `KB-PERF-01`.
- **Backlog:** `KB-DOC-LEGACY-ARCHIVE`, `KB-G5-API-CONTRACT`.

The workboard has 67 cards total; the `Done` section has 34 cards. Treat these
as board counts, not a repository completion percentage. Some cards have
explicit statuses that disagree with their section; reconcile before using
section placement as status.
