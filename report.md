# MCManager Master System Reconciliation

## Executive summary

**Bottom line:** MCManager is a real, layered Flask application with substantial implementation across persistence, authentication, world/process lifecycle, operations, backup/restore, scheduling, sync, APIs, and a browser shell. It is **not complete against the governing plans and is not release-ready**. Several release gates and acceptance dimensions remain unverified, and some documented operations are explicitly unavailable.

The plan corpus is broadly coherent and has a useful precedence model in [Architecture](docs/ARCHITECTURE.md), but it is not conflict-free. The most material unresolved deltas are:

1. Documents 5 and 10 describe runtime documentation sourced from repository `docs/`, while Document 12 establishes the distributed `app/docs/` boundary. The app's `app/docs/` currently contains only `.gitkeep`.
2. Document 8 requires a two-transfer global sync concurrency cap; `SyncService` has a daily transfer-byte quota, but no demonstrated two-transfer admission guard. The WBS also describes retries as `30s / 60s / 120s`, unlike Document 8's three total attempts with 30s and 60s waits.
3. Document 10's route paths are present, but four manager lifecycle routes return `501 NOT_IMPLEMENTED`. Route registration is not equivalent to behavioral, authorization, schema, error, or response-envelope parity.
4. Cleanup handles backup artifacts, not stale worlds or logs. Those scopes are explicitly unsupported pending product policy.
5. The app is layered rather than spaghetti, but its source layout and dependency boundaries diverge from the target architecture. Several service/repository/command boundaries are consolidated or absent, and the dependency-boundary test is recorded as failing.
6. The five gate pseudocode files are explicitly historical/superseded examples. They cover selected slices, not the complete functions, routes, requirements, or tests in Documents 4-14.
7. Workboard tracking is actionable and substantially better than the WBS as a status source, but it is not yet a definitive requirement-by-requirement inventory. "Done" cards record scoped slices, not overall gate or release completion.

### Inventory counts and evidence boundary

| Inventory | Observed |
|---|---:|
| Application Python files under `app/` | 92 |
| Python files under `tests/` | 54 |
| SQL migrations under `app/migrations/` | 4 |
| Documented HTTP API route entries in Document 10 | 110 |
| Documented HTTP routes matched to registered Flask routes | 110 / 110 |
| Additional registered HTTP routes outside that catalog | 5 |
| Documented SSE endpoints | 5 |
| Process-control conformance cases | C1-C14 |
| Workboard cards | 61 across Done, Review, To Do, Blocked, Backlog |

This report maps plans to repository evidence. It does **not** claim that a registered route, source symbol, or existing test proves full acceptance. The latest recorded full-suite evidence in [WORKBOARD.md](docs/WORKBOARD.md) is dated 2026-11-19: **493 passed, 8 failed, 4 skipped, 76.24% coverage, and 251 warnings**. That is a failed baseline, not a release pass. This reconciliation did not rerun the full suite. The current environment also lacks Node, so it could not rerun the browser Node suite.

## 1. Scope and method

Included: Architecture and Documents 4-14; all five gate pseudocode files; current `app/` source layout; migrations; test layout and mapped test modules; WBS and workboard status.

The crosswalk distinguishes:

- **Implemented / tested slice:** source exists and relevant test coverage is identified; this is not a claim of full system acceptance.
- **Partial:** some planned behavior exists, but important requirements, tests, or release evidence are missing.
- **Missing / unavailable:** no implementation or the registered operation explicitly reports `NOT_IMPLEMENTED`.
- **Consolidated:** behavior exists in a different module or combined implementation rather than the separately named planned component.
- **Intentional pending product content:** the application distribution boundary is present, but the new curated runtime documentation has not yet been authored.

Test modules below are representative evidence locations, not an assertion that every individual assertion has been inspected or that every documented test has passed in the current environment.

## 2. Requirement-by-requirement inventory

### 2.1 Architecture and Document 4: shared visual system

| Planned components and requirements | Pseudocode | Current source and evidence | Status / remaining |
|---|---|---|---|
| Five planes: presentation, control, runtime, data, integration; modular monolith; composition root; ports/adapters | Gate 5 illustrates selected web/UI behavior; it is not a full architecture pseudocode | `app/bootstrap.py`, `app/__init__.py`, `app/web/`, `app/services/`, `app/domain/`, `app/ports/`, `app/infrastructure/`, `app/platform/` | The overall layered shape exists. Target package boundaries are only partly enforced; see Document 12 and `KB-G0-BOUNDARY-REGRESSION`. |
| Shared light/dark tokens, pane layout, sticky navigation, global controls, 40px controls, shared colors and spacing | Gate 5 contains an obsolete shell sketch | `app/shell/templates/shell.html`, `app/shell/static/shell.css` | Shared tokens and global CSS exist and visibly align with key values. Responsive, interaction, and every component-level ban still need end-to-end acceptance. |
| Shared button/input/dropdown/status indicator; semantic dialog; four modal kinds; accessible responsive navigation | Gate 5 only sketches the shell and dialog | Same shell files plus `app/shell/static/operator_ui.js` | Partial. A persistent shell, notification dropdown, status badges, and `<dialog>` exist; complete conformance to each modal, component, and responsive rule is not established by the narrow browser suite. |
| One leader-tab SSE connection and BroadcastChannel dispatch | Gate 5 includes a historical stream-client sketch | `app/shell/static/stream_client.js`, `app/web/streams/` | Implemented slices and a 10-tab test are recorded. Reconnect/failover behavior under a live proxy remains open (`KB-G5-7`, `KB-G5-10`, `KB-G1-LOG-REPLAY`). |

### 2.2 Document 5: navigation and workflows

Document 5 plans manager and selected-world contexts, a persistent shell, setup/onboarding, world list and creation, manager settings, users/devices/roles/permissions, schedules, maintenance, documentation, system logs, audit/history, sync, manager lifecycle, templates, world main, backup/restore, logs, file manager, world maintenance, and world setup.

| Planned component | Current mapping | Test mapping | Status |
|---|---|---|---|
| Persistent shell, manager/world context, theme, navigation, notifications | `app/shell/templates/shell.html`; `app/shell/static/operator_ui.js`; `app/shell/static/shell.css` | `tests/browser/test_gate5_browser.test.cjs`; `tests/integration/test_gate5_browser_runner.py`; `tests/integration/test_gate5_acceptance.py` | Implemented shell/workflow slices. Browser acceptance is not comprehensive; recorded UI follow-up includes a regression test that was not run because Node was unavailable. |
| The 17 planned shell modules/workflows | Consolidated into dynamic page rendering in `operator_ui.js`; not 17 independent source modules | Browser test covers navigation across 17 modules (six tests recorded) | Partial: many operator workflows exist; manager restore/restart/update/rollback UI depends on backend contracts that are not implemented. See `KB-G5-6` and `KB-G5-8`. |
| Home/dashboard, world list/create/select, start/stop, world details | `app/web/api/system.py`, `app/web/api/world_management.py`, `app/services/worlds.py`, `app/shell/static/operator_ui.js` | `tests/integration/test_world_management_api.py`, `test_worlds_lifecycle.py`, `test_gate5_acceptance.py`, `test_gate2_realignment.py` | Core workflows exist; full Doc 5 UX acceptance is incomplete. |
| Backups/restores, logs/files, properties, world maintenance | `app/web/api/backup_catalogs.py`, `world_management.py`, `server_properties.py`; `app/services/{backup,restore,cleanup,server_properties}.py`; shell UI | `tests/integration/test_backup_catalog_api.py`, `test_restore_acceptance.py`, `test_cleanup_service.py`, `test_phase4_operational_subsystems.py`, `tests/unit/test_filesystem.py`, `tests/unit/test_readiness_rcon_props.py` | Backup/restore and backup cleanup are implemented in substantial slices. Stale-world/log cleanup remains unsupported; complete workflow acceptance remains open. |
| Users, roles, devices, permissions, schedules, templates, Java runtimes, settings | `app/web/api/administration.py`, `catalogs.py`, `configuration.py`; `app/services/auth.py`, `configuration.py`, `catalog_operations.py` | `tests/integration/test_auth.py`, `test_document10_catalog_apis.py`, `test_scheduler_service.py`, `test_gate2_realignment.py` | Many catalog/API slices exist. Service separation is consolidated, and full route-level authorization/contract parity remains open. |
| Documentation and manager logs | `app/web/api/manager_content.py`; shell documentation rendering in `operator_ui.js` | `tests/integration/test_document10_catalog_apis.py`, `test_phase5_presentation_hardening.py` | API implementation exists. The app's `app/docs/` has only `.gitkeep`, so it currently has no curated shipping documents. The user-requested new production docs remain intentionally future work. |
| Manager restart/update/rollback/restore | Routes in `app/web/api/administration.py` | `tests/integration/test_document10_catalog_apis.py`, `tests/integration/test_gate5_acceptance.py` | **Unavailable:** restore, restart, update, and rollback call `_blocked_manager_action` and return `501 NOT_IMPLEMENTED`. Manager backup is implemented as a durable operation. |

The exact 17 page slugs registered in `app/shell/routes.py` and returned by `GET /api/pages` are: `home`, `worlds`, `settings`, `users`, `maintenance`, `documentation`, `system-logs`, `audit`, `sync`, `manager-maintenance`, `templates`, `world-main`, `world-backups`, `world-logs`, `files`, `world-maintenance`, and `world-setup`. `app/web/api/pages.py` gives these page modules their section summaries. The slugs exist, but a page entry is not proof that every described workflow is complete.

**Plan inconsistency:** Document 5 still describes repository-local `docs/` as runtime documentation content; Document 12 says runtime docs belong under distributed `app/docs/`. Preserve repository planning documents as requested, but reconcile the runtime source/rendering contract in `KB-DOC-PLAN-COHERENCE`.

**Rendering deviation:** Document 5 says the API returns Markdown source for display as text until a trusted renderer exists. The current UI calls `markdownToHtml()` and renders a limited Markdown subset. It escapes source text and restricts link schemes, but the plan and UI behavior are still different and need an explicit product/documentation decision.

### 2.3 Documents 6 and 7: domain concepts and persistence

#### Document 6 component inventory

Document 6 intentionally adopts a hybrid model: `WorldInstance` is a pure domain aggregate; most other named concepts are persistence-backed records coordinated at service/transaction boundaries. Their lack of a dedicated dataclass is **not by itself a missing implementation**.

| Planned domain component | Current source representation | Tests / evidence | Status |
|---|---|---|---|
| WorldInstance; lifecycle transitions; invariants; deletion tiers | `app/domain/entities.py`, `lifecycle.py`, `invariants.py`, `deletion_tiers.py`; `app/services/worlds.py` | `tests/integration/test_gate2_realignment.py`, `test_worlds_lifecycle.py` | Implemented/tested slices; full state and transition acceptance remains broader than the focused tests. |
| User, lockout, password references, ClientSession, step-up, Device | Persistence records plus `app/services/auth.py`; web authorization/middleware | `tests/integration/test_auth.py`, `test_secrets.py`, `test_audit.py` | Substantial implementation/test coverage; all Doc 6 security and lifecycle cases are not proven by these suites alone. |
| RuntimeSession, Operation, BackupArtifact, RestoreHistory | SQLite schema plus `app/services/{worlds,runtime,operations,backup,restore}.py` | `test_schema_migrations.py`, `test_gate3_operations.py`, `test_runtime_reconciliation.py`, `test_gate4_acceptance.py`, `test_restore_acceptance.py` | Core slices present; all state-machine paths and crash/recovery stages are not fully accepted. |
| Schedule, MissedRunRecord, CleanupPolicy | SQLite schema; `app/services/scheduler.py`, `cleanup.py`, `configuration.py`; catalog APIs | `test_scheduler_service.py`, `test_cleanup_service.py`, `test_document10_catalog_apis.py` | Schedule/missed-run and backup cleanup slices exist. Cleanup policy/scope parity is incomplete. |
| Notification, per-user NotificationRead, AuditRecord | SQLite records; `app/services/notifications.py`, `audit.py`; `app/web/api/history.py` | `test_notifications.py`, `test_audit.py`, `test_gate3_audit_notification_pipeline.py` | Append-only and terminal audit/notification slices are tested; a complete event-by-event contract map remains open. |
| Manager singleton and manager lifecycle | SQLite manager record; `app/services/manager_lifecycle.py`; admin routes | `test_document10_catalog_apis.py`, `test_gate5_acceptance.py` | Manager backup exists; restore/restart/update/rollback remain explicitly blocked. |
| JavaRuntime and Template | Persistence and `app/services/catalog_operations.py`; `app/web/api/catalogs.py` | `test_document10_catalog_apis.py`, `test_java_gate.py` | Implemented through a consolidated dispatcher/API rather than dedicated `JavaRuntimeService` and `TemplateService` classes. |
| Role, RoleAssignment, Permission; direct grants and Superadmin protections | Persistence plus web/admin authorization code | `test_auth.py`, `test_document10_catalog_apis.py`, `test_gate5_acceptance.py` | Important slices exist, including last-Superadmin protection; full policy matrix parity remains open. |
| SyncTarget, SyncRecord, SyncAttempt | Persistence; `app/services/sync.py`; backup catalog routes | `test_sync_gate4.py`, `test_gate4_acceptance.py`, `test_backup_catalog_api.py` | Retry and daily-byte-cap slices exist; the global concurrency cap is not demonstrated. |
| Closed enums/value objects | `app/domain/value_objects.py` | `test_gate1_contracts.py`, `test_gate2_realignment.py`, adapter and service tests | Many enums are centralized; exhaustive value/object-to-contract tests are not established. |
| Full Document 6 domain event catalog | `app/domain/events.py` currently defines `WorldStateChanged` and `WorldDeleted`; operation/audit/notification services also use event-name strings | `test_gate3_audit_notification_pipeline.py`, `test_notifications.py`, `test_audit.py` | **Partial representation:** most named lifecycle/security/catalog events are not separate typed domain event classes. Their behavior needs a complete event-to-side-effect map; do not infer that missing event classes automatically mean missing behavior. |

Document 6's full event-name inventory is:

| Aggregate / event family | Planned events |
|---|---|
| User | `UserCreated`, `UserRoleChanged`, `UserPermissionGranted/Revoked`, `UserDisabled/Enabled/Locked/Unlocked`, `UserPasswordChanged`, `UserDeleted` |
| RuntimeSession | `RuntimeSessionStarted`, `RuntimeSessionEnded`, `RuntimeSessionReconciled` |
| WorldInstance | `WorldCreated/Queued/Starting/Started/StartFailed/Stopping/Stopped/Crashed/BackingUp/BackupSucceeded/BackupFailed/Restoring/RestoreSucceeded/RestoreFailed/ErrorAcknowledged/CrashAcknowledged/EulaRequired/EulaAccepted/Deleted(tombstoned)` |
| Operation | `OperationCreated/Queued/ValidationFailed/Started/Progress/Completed/Failed/Cancelled/TimedOut` |
| BackupArtifact | `BackupArtifactCreated`, `BackupArtifactDeleted` |
| Schedule / MissedRunRecord | `ScheduleCreated/Updated/Enabled/Disabled/Deleted(soft)/RunDue/RunMissed`; `MissedRunDetected/Resolved/Ignored` |
| CleanupPolicy | `CleanupPolicyCreated/Updated/Enabled/Disabled/Deleted(soft)/RunExecuted (dry|wet)/RunSummaryRecorded/HardDeletePerformed` |
| Sync | `SyncTargetCreated/Updated/Deleted(soft)`; `SyncJobStarted/Succeeded/Failed`; `SyncAttemptSucceeded/FailedTransient/FailedPermanent` |
| Notification / AuditRecord | `NotificationCreated/Read/ActionTaken/Dismissed`; `AuditRecordCreated` only |

This list identifies planned event components; exact event emission, ordering, persistence, audit, and notification behavior must be verified against the relevant service tests rather than inferred from the presence of the names.

#### Document 7 schema inventory

Document 7 specifies 28 tables. Four sequential migrations exist under `app/migrations/`; the migration test asserts 28 tables and checks FK behavior, rollback, idempotency, WAL, busy timeout, and reader/writer behavior.

| Planned table group and all table names | Source / tests | Status |
|---|---|---|
| Manager/global: `manager`, `global_settings`, `schema_migrations` | `app/migrations/001_initial_schema.sql` and subsequent migrations; `tests/integration/test_schema_migrations.py`, `test_bootstrap.py`, `test_gate2_realignment.py` | The 28-table count and migration/FK checks have explicit tests. |
| World/registry: `world_instances`, `world_settings`, `templates`, `java_runtimes` | Initial schema; world/catalog services and APIs | Core persistence and API slices exist; full constraint and optimistic-version matrix acceptance remains open. |
| Runtime: `runtime_sessions`, `operations` | Initial schema; runtime/reconciliation/operation services | Core behavior and selected recovery/conflict tests exist; not every Document 8/9 flow is verified. |
| Backup/restore/retention: `backup_artifacts`, `restore_history`, `schedules`, `missed_run_records`, `cleanup_policies` | Initial schema and later migrations; backup/restore/scheduler/cleanup services | Tables exist; non-backup cleanup scopes and full retention policy are missing. |
| Sync: `sync_targets`, `sync_records`, `sync_attempts` | Initial schema; `app/services/sync.py` | Tables and retry slices exist; the global concurrency-admission requirement remains unresolved. |
| Notifications/audit: `notifications`, `notification_reads`, `audit_records` | Initial schema; notifications/audit services | Core append/read paths and tests exist. |
| Identity/security: `users`, `roles`, `role_assignments`, `permissions`, `devices`, `client_sessions`, `secrets` | Initial schema; auth services and APIs | Core auth/security slices exist; full roles/grants/API contract acceptance remains open. |
| World properties: `server_properties_versions` | `app/migrations/004_server_properties_versions.sql`; server-properties service/API | Version storage exists; `KB-G5-API-CONTRACT` retains endpoint-level acceptance. |

The table count is not evidence that every documented DDL constraint or every service invariant is complete. `test_schema_migrations.py` explicitly tests several core constraints, but does not replace the full Document 6/7/9 acceptance map.

### 2.4 Documents 8 and 9: service responsibilities and concurrency

#### All planned Document 8 service components

| Planned service / capability | Current implementation mapping | Tests | Finding |
|---|---|---|---|
| WorldService: registry CRUD, create/delete/rename, off-only config | `app/services/worlds.py` (`WorldsService`) | `test_worlds_lifecycle.py`, `test_world_management_api.py`, `test_gate2_realignment.py` | Consolidated naming; implementation slices exist. |
| RuntimeService: start/stop/kill/sessions/probes/crash | `app/services/runtime.py`, `worlds.py`, `reconciliation.py`, `platform/process/` | `test_runtime_reconciliation.py`, `test_gate3_operations.py`, `test_gate3_runtime_scheduler.py`, `test_conformance.py` | RuntimeService is a facade; lifecycle logic remains in WorldsService. Cross-platform/live-server acceptance is incomplete. |
| OperationService: idempotency, status, progress, timeouts, cancel, milestone writes | `app/services/operations.py`; `app/commands/world.py` | `test_gate3_operations.py`, `test_gate3_operation_engine_behavior.py`, `test_gate5_acceptance.py` | Core operation slices exist; complete Document 9 matrix and all operation flows remain open. |
| BackupService | `app/services/backup.py`, `app/infrastructure/backup_engine.py`, save coordination | `test_gate4_acceptance.py`, `test_phase4_backup_coordination.py`, `test_backup_engine.py` | ZIP/SHA, staging, save restoration and selected failure paths are tested. |
| RestoreService | `app/services/restore.py` | `test_restore_acceptance.py`, `test_gate4_acceptance.py` | Mandatory pre-backup and rollback slices exist; all interruption stages/operational outcomes need acceptance. |
| CleanupService | `app/services/cleanup.py` | `test_cleanup_service.py`, `test_gate4_acceptance.py` | Backup artifact preview/deletion only. `stale_worlds` and `logs` are unsupported. |
| SyncService | `app/services/sync.py` | `test_sync_gate4.py`, `test_gate4_acceptance.py` | Attempt history, retry and daily byte quota exist. Two-simultaneous-transfer limit is not demonstrated; retry policy wording needs reconciliation. |
| SchedulerService | `app/services/scheduler.py` | `test_scheduler_service.py`, `test_gate3_runtime_scheduler.py` | Automatic tick/missed-run slices exist; full due/re-read/conflict matrix acceptance remains open. |
| AuthenticationService | `app/services/auth.py` | `test_auth.py`, `test_secrets.py` | Argon2id/session/step-up slices are present. |
| AuthorizationService | No dedicated class with this name; policy enforcement is consolidated across web auth/admin code | `test_auth.py`, `test_document10_catalog_apis.py`, `test_gate5_acceptance.py` | Architectural consolidation; exhaustive actor/role/grant/world/state matrix remains unverified. |
| NotificationService | `app/services/notifications.py` | `test_notifications.py`, `test_gate3_audit_notification_pipeline.py` | Core publish/read/dismiss and terminal-operation slices exist. |
| AuditService | `app/services/audit.py` | `test_audit.py`, `test_gate3_audit_notification_pipeline.py` | Append-only and terminal-only slices exist; exhaustive event coverage remains open. |
| FileManagerService | No separate service class; route logic in `app/web/api/world_management.py` with filesystem infrastructure/ports | `test_world_management_api.py`, `tests/unit/test_filesystem.py`, `test_phase4_operational_subsystems.py` | Consolidated route/infrastructure implementation; full Document 5 file workflow and elevated confirmation acceptance remains open. |
| TemplateService / JavaRuntimeService | Catalog APIs plus `app/services/catalog_operations.py` (`CatalogOperationDispatcher`) | `test_document10_catalog_apis.py`, `test_java_gate.py` | Behavior is consolidated; dedicated services are absent. |
| ConfigurationService | `app/services/configuration.py`; `app/web/api/configuration.py` | `test_gate2_realignment.py`, `test_document10_catalog_apis.py` | Effective configuration/version-conflict slices tested; all versioned entities and logged edit flows need contract-wide acceptance. |
| MetricsService | `app/services/metrics.py` | `tests/unit/test_metrics_service.py`, `test_gate5_acceptance.py` | Snapshot/cadence and streaming slices exist; measured performance/deployment evidence is incomplete. |

#### Document 8 operation functions and flow mapping

The eleven planned operation types and their planned owning services are listed individually so that a generic "operation engine exists" claim does not conceal missing paths.

| Operation type / planned flow | Current source | Test mapping | Finding |
|---|---|---|---|
| `CreateWorld`: authorize, validate template/port/address, create durable operation, provision directory/registry, finish `off` or EULA-gated | `WorldsService`, `OperationService`, `catalog_operations.py`; `world_management.py` | `test_world_management_api.py`, `test_worlds_lifecycle.py`, `test_gate5_acceptance.py` | Core creation path exists; full template/address/EULA acceptance is partial. |
| `Start`: storage/EULA/config preflight, enqueue operation, launch via adapter, readiness, open session only after confirmed running | `RuntimeService`, `WorldsService`, Minecraft gate/readiness, process ports | `test_worlds_lifecycle.py`, `test_runtime_reconciliation.py`, `test_java_gate.py`, `test_readiness_rcon_props.py`, adapter conformance | Implemented slices; live server-type and all timeout/startup failure paths remain. |
| `Stop`: authorize/step-up as required, graceful shutdown, end session only on confirmed stop | `RuntimeService`, `WorldsService`, `ProcessControlPort`, RCON | `test_worlds_lifecycle.py`, `test_gate3_operations.py`, `test_conformance.py` | Core flow exists; full cross-platform escalation acceptance remains. |
| `Kill`: explicit escalation; atomically supersede/cancel an in-flight Stop; force-terminate tree; close session | `OperationService`, `WorldsService`, process adapters | `test_gate3_conflicts.py`, `test_gate3_operation_engine_behavior.py`, `test_conformance.py` | Selected concurrency/termination slices exist. |
| `Backup`: scope/conflict/storage check; pause autosave/save/flush; capture/verify/register artifact; always restore autosave; trigger sync follow-on when configured | `BackupService`, `SaveCoordinator`, backup engine, sync service | `test_gate4_acceptance.py`, `test_phase4_backup_coordination.py`, `test_backup_engine.py`, `test_sync_gate4.py` | Strong core slices; all Document 14 save/crash/reboot cases remain incomplete. |
| `Restore`: validate source; require world off; mandatory pre-restore backup; stage/archive/switch; restart if previously running; record history; compensating rollback as a new operation | `RestoreService`, `BackupService`, `RuntimeService` | `test_restore_acceptance.py`, `test_gate4_acceptance.py` | Main acceptance paths exist; every interruption point and rollback failure branch needs fuller evidence. |
| `Cleanup`: evaluate preview, retention floors and blast radius; execute only via CleanupService; record summary | `CleanupService`, `backup_catalogs.py` | `test_cleanup_service.py`, `test_gate4_acceptance.py`, `test_backup_catalog_api.py` | Implemented for backup artifacts only; stale worlds/logs remain unsupported. |
| `Sync`: resolve target, single-flight per artifact, persist one immutable attempt per try, retry transient failures, cancel safely, notify terminal failure | `SyncService`, backup catalog API | `test_sync_gate4.py`, `test_gate4_acceptance.py`, `test_backup_catalog_api.py` | Retry/history and daily cap are covered in slices; global cap and complete status/cancellation policy remain open. |
| `ConfigEdit`: authorize category; compare submitted version before creating operation; apply edit with before/after audit; reject stale version | `ConfigurationService`, configuration/catalog/server-properties APIs | `test_gate2_realignment.py`, `test_document10_catalog_apis.py`, `test_gate5_acceptance.py` | Settings conflict flows exist; every versioned table and ConfigEdit category is not yet mapped. |
| `CrashDetected`: process observation creates system operation, closes session, updates state, audits and notifies | `RuntimeService`, `WorldsService`, reconciliation, audit/notification services | `test_runtime_reconciliation.py`, `test_gate3_audit_notification_pipeline.py`, `test_gate3_runtime_scheduler.py` | Selected cases exist; complete crash-to-notification E2E is missing. |
| `DeleteWorld`: require off/idle and preview/step-up; tombstone, soft-delete scoped policies, remove files, audit/notify | `WorldsService`, `world_management.py` | `test_world_management_api.py`, `test_gate3_conflicts.py`, `test_gate5_acceptance.py` | Core path and conflict cases exist; complete destructive-operation workflow acceptance remains open. |

#### Document 8 locked tuning constants

The following are planned contract values; their presence in a plan or test fixture does not establish that each is implemented/configurable as specified.

| Contract value | Required value |
|---|---|
| Scheduler tick | 30 seconds |
| Start readiness timeout | 120 seconds |
| Stop graceful deadline / Kill process deadline | 60 seconds / 10 seconds |
| Duplicate Start cooldown | 10 seconds |
| Sync transient retry | 3 total attempts; wait 30 seconds then 60 seconds |
| Sync attempt timeout / overall bound | 120 seconds / 30 minutes |
| Global simultaneous sync transfers | 2 |
| Metrics cadence / stream | null or 15-second cache / 1 Hz |
| Contextual storage reserve | 10 GB absolute reserve plus 10% free-space overflow bound |
| Step-up window | 10 minutes |
| Log ring buffer / deployed verbosity | 5,000 lines per world / `VERBOSE_LOGGING=false` |
| Supervisor cadence | 1 second running / 15 seconds idle |
| Render interval | 1 Hz |
| Cleanup blast-radius threshold | 500 candidates |
| Authentication throttle | 5 failures, 15-minute lockout |
| Session lifetime | 7 days inactivity, 30 days absolute maximum |
| Idle auto-stop default | Off |
| SSE replay buffer | 200 events per stream |

The workboard specifically identifies the sync concurrency and retry contract as unresolved. Performance and streaming cadence also need measured acceptance.

#### Document 9 concurrency requirements

| Planned lock/conflict component | Current mapping and tests | Status |
|---|---|---|
| Derived per-world lock from nonterminal Operations; atomic acquisition | `app/services/operations.py`; `test_gate3_conflicts.py`, `test_gate3_operation_engine_behavior.py` | Selected race/conflict cases pass in recorded evidence; full matrix and all race interleavings remain open. |
| Contextual global storage guard; cleanup/emergency-stop exceptions | Backup/runtime/cleanup services; `test_gate4_acceptance.py` | Contextual reserve tests exist; whole-operation contract needs acceptance. |
| Cleanup per-scope single flight | Cleanup/operation services; `test_cleanup_service.py`, `test_gate3_conflicts.py` | Backup cleanup is covered; other scopes are not implemented. |
| Optimistic locking for all versioned configuration rows | `ConfigurationService`, catalog/configuration APIs | Settings conflict tests exist in `test_gate2_realignment.py`; acceptance for every Document 9 versioned entity is not established (`KB-G9-CONTRACT`). |
| Start duplicate handling, Stop/Kill supersession, Restore/Delete ordering, queue/reject policy | Operation/world services | `test_gate3_conflicts.py` covers selected cases, including Kill/Stop and queued delete/restore. This is not exhaustive matrix coverage. |
| Sync per-artifact single flight plus global cap of 2 | `app/services/sync.py` has daily transfer accounting/reservations; no global two-transfer admission guard was demonstrated | Open product/implementation decision: `KB-G8-SYNC-CAP`. Daily quota is not a concurrency cap. |

### 2.5 Document 10: API and SSE inventory

All **110 documented HTTP method/path entries** were matched against current Flask registrations after including each blueprint's URL prefix. There are also five registered routes outside the catalog: two per-world cleanup-policy endpoints, two page-rendering routes, and the development/test supervisor tick route. This path-level match does not establish authentication, CSRF, step-up, request/response schema, error mapping, or UI behavior for each route.

| Document 10 family (route count) | Complete planned route set | Source mapping | Existing test modules |
|---|---|---|---|
| Auth & session (4) | `POST /api/auth/login`, `POST /api/auth/logout`, `POST /api/auth/step-up`, `GET /api/session` | `app/web/api/auth_routes.py` | `tests/integration/test_auth.py`, `test_document10_catalog_apis.py` |
| Worlds (15) | `GET /api/worlds`; `POST /api/worlds`; `GET/PATCH /api/worlds/{world_id}`; `POST /api/worlds/{world_id}/delete-preview`; `DELETE /api/worlds/{world_id}`; `GET/PATCH /api/worlds/{world_id}/runtime-config`; `POST /api/worlds/{world_id}/start`, `/stop`, `/kill`; `GET/POST /api/worlds/{world_id}/server-properties`; `POST /api/worlds/{world_id}/eula/accept`; `GET /api/worlds/{world_id}/eula` | `app/web/api/system.py`, `world_management.py`, `server_properties.py` | `test_world_management_api.py`, `test_worlds_lifecycle.py`, `test_gate5_acceptance.py`, `test_gate2_realignment.py`, `tests/unit/test_java_gate.py`, `test_readiness_rcon_props.py` |
| Operations (4) | `GET /api/operations`, `GET /api/operations/{op_id}`, `POST /api/operations/{op_id}/cancel`, `GET /api/worlds/{world_id}/operations` | `app/web/api/system.py` | `test_gate3_operations.py`, `test_gate3_operation_engine_behavior.py`, `test_gate3_conflicts.py`, `test_gate5_acceptance.py` |
| Backups & restores (8) | `GET/POST /api/worlds/{world_id}/backups`; `GET/DELETE /api/backups/{artifact_id}`; `GET /api/backups`; `GET /api/worlds/{world_id}/restores`; `POST /api/worlds/{world_id}/restores`; `POST /api/worlds/{world_id}/restores/rollback` | `app/web/api/backup_catalogs.py` | `test_backup_catalog_api.py`, `test_restore_acceptance.py`, `test_gate4_acceptance.py`, `test_phase4_backup_coordination.py` |
| Cleanup (6) | `GET/PATCH /api/cleanup/policy`; `POST /api/cleanup/dry-run`, `/execute`; `GET /api/cleanup/runs`; `GET /api/worlds/{world_id}/cleanup-preview` | `app/web/api/backup_catalogs.py` | `test_cleanup_service.py`, `test_gate4_acceptance.py`, `test_backup_catalog_api.py` |
| Sync (7) | `GET /api/sync/records`; `GET /api/backups/{artifact_id}/sync`; `POST /api/sync/retry`; `GET/POST /api/sync/targets`; `PATCH/DELETE /api/sync/targets/{target_id}` | `app/web/api/backup_catalogs.py` | `test_sync_gate4.py`, `test_gate4_acceptance.py`, `test_backup_catalog_api.py`, `test_document10_catalog_apis.py` |
| Schedules & missed runs (6) | `GET/POST /api/schedules`; `PATCH/DELETE /api/schedules/{schedule_id}`; `GET /api/missed-runs`; `PATCH /api/missed-runs/{missed_run_id}` | `app/web/api/catalogs.py` | `test_scheduler_service.py`, `test_document10_catalog_apis.py`, `test_gate3_runtime_scheduler.py` |
| Settings & manager (12) | `GET/PATCH /api/settings`; `GET/PATCH /api/worlds/{world_id}/settings`; `GET /api/manager`; `POST /api/manager/backup`, `/restore`, `/restart`, `/update`, `/rollback`; `GET/POST /api/setup` | `app/web/api/configuration.py`, `administration.py` | `test_document10_catalog_apis.py`, `test_gate2_realignment.py`, `test_gate5_acceptance.py` |
| Templates & Java runtimes (9) | `GET/POST /api/templates`; `PATCH/DELETE /api/templates/{template_id}`; `GET/POST /api/java-runtimes`; `POST /api/java-runtimes/{runtime_id}/verify`; `PATCH/DELETE /api/java-runtimes/{runtime_id}` | `app/web/api/catalogs.py` | `test_document10_catalog_apis.py`, `tests/unit/test_java_gate.py` |
| Users, roles, permissions, devices (15) | `GET/POST /api/users`; `PATCH/DELETE /api/users/{user_id}`; `GET/POST /api/roles`; `PATCH/DELETE /api/roles/{role_id}`; `GET /api/roles/{role_id}/permissions`; `POST /api/permissions`; `DELETE /api/permissions/{permission_id}`; `GET /api/devices`; `PATCH /api/devices/{device_id}`; `GET /api/devices/{device_id}/sessions`; `GET /api/session/activity` | `app/web/api/administration.py` | `test_auth.py`, `test_document10_catalog_apis.py`, `test_gate5_acceptance.py`, `test_audit.py` |
| Notifications & audit (6) | `GET /api/notifications`; `POST /api/notifications/{notification_id}/read`; `POST /api/notifications/{notification_id}/dismiss`; `POST /api/notifications/read-all`; `GET /api/audit`; `GET /api/audit/{audit_id}` | `app/web/api/history.py` | `test_notifications.py`, `test_audit.py`, `test_gate3_audit_notification_pipeline.py`, `test_document10_catalog_apis.py` |
| Files & world logs (10) | `GET /api/worlds/{world_id}/files`, `/files/download`; `POST /files`, `/files/mkdir`; `PATCH/DELETE /files`; `GET /api/worlds/{world_id}/logs`, `/logs/{channel}`, `/logs/{channel}/{file}`, `/logs/{channel}/tail` | `app/web/api/world_management.py`; live streams in `app/web/streams/` | `test_world_management_api.py`, `tests/unit/test_filesystem.py`, `test_phase4_operational_subsystems.py`, `test_realtime_slow_client.py` |
| Documentation & manager logs (5) | `GET /api/documentation`, `/api/documentation/{path}`, `/api/manager/logs`, `/api/manager/logs/{channel}`, `/api/manager/logs/{channel}/{file}` | `app/web/api/manager_content.py` | `test_document10_catalog_apis.py`, `test_phase5_presentation_hardening.py` |
| System (3) | `GET /api/health`, `/api/system/stats`, `/api/diagnostics` | `app/web/api/system.py` | `test_gate5_acceptance.py`, `tests/unit/test_metrics_service.py`; current full-suite evidence includes three health/diagnostics failures |

The five SSE endpoints are implemented separately in `app/web/streams/routes.py`: `/stream/events`, `/stream/worlds/{world_id}/events`, `/stream/worlds/{world_id}/logs`, `/stream/restore_logs`, and `/stream/metrics`. Relevant tests include `tests/unit/test_realtime_slow_client.py`, `tests/integration/test_gate5_browser_runner.py`, `test_gate5_acceptance.py`, and `tests/browser/test_gate5_browser.test.cjs`.

#### Registered routes outside the catalog

| Extra registered route | Current reason / status |
|---|---|
| `GET/PATCH /api/worlds/{world_id}/cleanup-policy` | Per-world policy API exists; documented global policy routes are separate. |
| `GET /api/pages`, `GET /api/pages/{slug}` | Shell/page rendering routes, not part of the JSON API catalog. |
| `POST /api/supervisor/tick` | Described in source as a manual development/test aid; reconcile its production exposure and contract in the API parity review. |

#### API implementation gaps

- Four documented manager actions (`restore`, `restart`, `update`, `rollback`) are registered but return `501 NOT_IMPLEMENTED`; manager backup is implemented.
- `KB-G5-API-CONTRACT` remains open for all-route auth/session/CSRF/role/step-up checks, payload/response schema, HTTP status, envelope, and error mapping. The workboard identifies settings-visibility policy as requiring a product decision.
- Several routes/components have implementation but no feature-level acceptance recorded, including server-properties editing, permission-grant enforcement, diagnostics/version metadata, sync-target CRUD, documentation/log browsing, and per-world cleanup-policy editing.

### 2.6 Document 11: testing strategy and acceptance

| Planned test requirement | Existing implementation/evidence | Gap |
|---|---|---|
| Unit/integration/E2E pyramid (~70/25/5) | Unit and integration suites exist; adapter conformance is under `tests/adapters/`; one browser Node test exists under `tests/browser/`. | There is no dedicated `tests/e2e/` package. The actual 70/25/5 distribution is not established in the current evidence. Service-level unit coverage and canonical UI/API/process E2E flows are incomplete (`KB-D11-TEST-PYRAMID`). |
| Domain invariants, service logic, fake ports, deterministic clocks | `tests/unit/` includes dependency, filesystem, readiness, metrics, and operation-related coverage; many feature tests are integration tests. | The planned complete Document 6 state/invariant matrix is not demonstrated. |
| Full SQLite schema/migration and FK behavior | `tests/integration/test_schema_migrations.py` tests the 28-table migration, FK checks, rollback, idempotence, WAL and locking behavior. | Does not itself prove all Doc 7 schema rules or all feature workflows. |
| Every operation/service integration flow; Document 9 conflict matrix; version conflicts | Gate 2/3/4 integration modules cover substantial slices, including selected interleavings and version conflicts. | Not every operation type, matrix cell, versioned entity, or recovery point is mapped to a passing test (`KB-G8-CONTRACT`, `KB-G9-CONTRACT`). |
| C1-C14 process adapter conformance and structural checks | `tests/adapters/test_conformance.py` includes test cases C1-C14. Workboard records Windows/fake slices and Windows/Ubuntu hosted workflow intent. | POSIX host result is blocked; hosted matrix results and live Minecraft spike remain; boundary/static gate currently has a recorded failure (`KB-G1-6`, `KB-G1-MINECRAFT`, `KB-G0-BOUNDARY-REGRESSION`). |
| Document 14 capability, Java, EULA, properties, RCON/save, archive, rollback tests | `tests/unit/test_java_gate.py`, `test_readiness_rcon_props.py`; integration backup/restore/platform suites. | Tests are partial relative to the full capability matrix and save-coordination failure bullets; live Vanilla/Paper/Fabric/Forge evidence is not complete. |
| Security acceptance job | Auth, secrets, audit, and selected Gate 5 tests exist; workboard records a dedicated security job and a 53-test focused Windows run. | Hosted Ubuntu/Python 3.11 results remain in the board; full route-by-route auth parity remains open. |
| Coverage floor: >=80% every module, >=85% overall | Latest recorded full run: 76.24% overall; 18/92 app modules below 80%. | Configured overall floor is recorded as 80%, not Document 11's 85%; no per-module floor is enforced (`KB-D11-COVERAGE`). |
| ISO/IEC 25010: security, compatibility, interaction, reliability, performance, flexibility, safety | Several functional, security, and reliability checks exist in focused suites. | Compatibility across POSIX/Windows, live proxy interaction, full reliability scenarios, flexibility/deployment topology, and calibrated performance remain open (`KB-D11-ISO-25010`). |
| Performance acceptance: reference profile, 300s idle, 50 clients, 1000 lines/sec, tail latency | `benchmarks/thresholds.json`, `benchmarks/performance_acceptance.py`, `benchmarks/spike_real_minecraft.py` exist; thresholds define the requested workload limits. | A file containing values is not measured evidence. Workboard says reference profile calibration and acceptance remain blocked (`KB-PERF-01`, `KB-G5-10`). |
| Release gate: all suites, security, performance, static checks, FK sweep, no high defects | Gate 2-4 focused acceptance has passed in recorded Windows evidence; the app has broad implementation slices. | The full suite fails, static gates are red, cross-OS and real-server acceptance are incomplete, and performance is uncalibrated. Not release-ready. |

### 2.7 Document 12: directory structure and coding boundaries

The production boundary is `app/`; observed source contains 92 Python files, four migrations, one HTML shell template, and three JavaScript files. That is a meaningful portable application package, not the repository as a whole. Repository planning docs, tests, WBS, workboard, benchmarks, prototypes, and developer tooling remain outside the intended production payload.

| Planned structure/rule | Current mapping | Finding |
|---|---|---|
| Composition root and portable startup | `app/main.py`, `app/bootstrap.py`, `app/__init__.py` | Present; bootstrap wires persistence, services, adapters, and workers. |
| Domain/value objects/events | `app/domain/` | Present but compact; only two typed domain event classes are defined versus Document 6's full event catalog. |
| Ports and leaf platform adapters | `app/ports/`, `app/platform/process/{base,posix,windows,tailing}.py` | POSIX/Windows process adapters exist. Hosted POSIX conformance is pending. |
| Minecraft adapters/capabilities | `app/infrastructure/minecraft/{capabilities,readiness,eula,properties_schema,java_compatibility,rcon,ping,adapter,gate}.py` | Broad planned capability modules exist; live supported-server-type validation is incomplete. |
| Service-per-capability organization | `app/services/` | Many services exist, but responsibilities are consolidated: no separate AuthorizationService, FileManagerService, TemplateService, or JavaRuntimeService class; RuntimeService is a facade over lifecycle logic in WorldsService. |
| Commands/queries and repositories | `app/commands/` currently contains `world.py`; SQLite implementation is in `app/infrastructure/sqlite/` | Planned CreateWorld/DeleteWorld/RenameWorld and broader command/query handlers, plus `repository.py`, `operations_repo.py`, and `audit_repo.py`, are absent. Services use the persistence abstraction but issue SQL through its connections. Tracked by `KB-D12-2`. |
| Import boundaries | `tests/unit/test_dependency_boundaries.py`; `app/services/server_properties.py` imports `app.infrastructure.minecraft.properties_schema` | A concrete service-to-infrastructure dependency exists and the boundary test is recorded as failing. Tracked by `KB-G0-BOUNDARY-REGRESSION`. |
| Tests layout/tooling | `tests/unit/`, `integration/`, `adapters/`, `browser/` | Functional suites exist but do not match a complete target test pyramid; static checks are not green. |
| Runtime documentation in shipped app | `app/docs/.gitkeep` | Directory exists but no user-facing content is shipped yet, consistent with the decision that new curated production docs will be written later. Update Documents 5/10 to agree with this boundary. |

**Architecture assessment:** The repository is organized into recognizable layers and cohesive capability areas; it is not accurately described as spaghetti. It is, however, a **partially conformant modular monolith**: service-to-infrastructure leakage, SQL-through-port patterns, consolidated feature services, and missing command/repository modules weaken the intended boundary. These are tracked, not hypothetical.

### 2.8 Documents 13 and 14: platform and Minecraft adapters

| Contract component | Current source | Test mapping | Status |
|---|---|---|---|
| Document 13 `ProcessControlPort`: `spawn`, `probe`, `send_signal`, `write_stdin`, `terminate`, `tail`, `poll`, `close_tail`, `close_handle`; `SpawnRequest`, `SpawnResult`, `ProcessStatus`, `ProbeFingerprint`, `ProbeResult`, `SendResult`, `TerminateResult`, `ProcessHandle`, `LineSink`, `TailHandle`, `ExitClass` | `app/ports/process_control.py`, `app/domain/value_objects.py` | `tests/adapters/test_conformance.py`, `tests/unit/test_gate1_contracts.py` | Present. The current port includes `write_stdin` and `close_handle` beyond Document 13's abbreviated interface. |
| POSIX and Windows process supervision, process-tree containment, PID identity | `app/platform/process/posix.py`, `windows.py`, `base.py` | `tests/adapters/test_conformance.py` C1-C14 | Both adapters exist. Workboard records Windows evidence; POSIX-host run remains blocked. |
| Tailing, replay, durability, slow-client backpressure | `app/platform/process/tailing.py`, `app/services/realtime.py`, `app/web/streams/` | `test_conformance.py`; `tests/unit/test_realtime_slow_client.py`; browser tests | Implemented slices; live proxy recovery and recorded full-suite failures remain. |
| C1-C14 process contracts | `tests/adapters/test_conformance.py` has C1 through C14 coverage | Same | Test definitions exist. The full cross-OS acceptance gate is not green; C11 real manager reattachment and the live server spike remain. |
| Server-type capabilities: Vanilla, Paper, Fabric, Forge | `app/infrastructure/minecraft/capabilities.py`, `adapter.py` | `tests/unit/test_java_gate.py`, `test_readiness_rcon_props.py`, adapter/integration suites | Capability structure exists; all matrix cells are not proven against live servers. |
| Readiness hierarchy and startup validation | `readiness.py`, `gate.py`, `ping.py`, `worlds.py` | readiness and lifecycle tests | Implemented slices; complete per-type operational readiness and live evidence remain. |
| EULA detection and explicit audited acceptance | `eula.py`, `app/services/worlds.py`, `app/web/api/system.py` | `test_worlds_lifecycle.py`, `test_world_management_api.py`, `test_gate5_acceptance.py` | Explicit acceptance path exists; full external-file-change and supported-server integration acceptance remains. |
| Version-aware `server.properties`, Java compatibility | `properties_schema.py`, `java_compatibility.py`, `server_properties.py` and service | `test_readiness_rcon_props.py`, `test_java_gate.py`, API tests | Core schemas/gates exist; acceptance across curated version/server-type sets is incomplete. |
| RCON session, player queries, command allowlist, shutdown ladder | `rcon.py`, runtime/save coordination, process adapters | `test_readiness_rcon_props.py`, `test_phase4_backup_coordination.py`, `test_conformance.py` | Partial; live RCON and per-platform server behavior remain unverified. |
| Save coordination and ZIP/SHA backup/restore rollback | `app/services/save_coordination.py`, `backup.py`, `restore.py`, `app/infrastructure/backup_engine.py` | `test_phase4_backup_coordination.py`, `test_gate4_acceptance.py`, `test_restore_acceptance.py`, `test_backup_engine.py` | Strong tested slices; Document 14's entire failure/boot-recovery matrix is not complete. |

Document 13 explicitly identifies itself as a specification/prototype guide, not proof of a finished multi-OS runtime. The live Minecraft spike remains blocked. Synthetic fake-server success is not evidence that every Vanilla/Paper/Fabric/Forge capability works.

The planned C1-C14 checks are: C1 spawn/probe/poll; C2 graceful stdin stop; C3 forced kill; C4 crash detection; C5 tail/replay; C6 orphan containment; C7 PID-reuse guard; C8 readiness via socket; C9 Start timeout; C10 Stop timeout escalation; C11 restart re-attach; C12 durable logs; C13 slow-sink backpressure; C14 no-systemd structural test. All are represented in `tests/adapters/test_conformance.py`; the platform completion state remains partial as described above.

## 3. Pseudocode completeness and mapping

Every `gate*_pseudocode.txt` file has a "CURRENT RECONCILIATION" header but explicitly says the body is retained historical/superseded pseudocode. The header/body distinction is important: these are **not current implementation instructions or complete behavioral specifications**.

| File | Historical scope represented | Current mapping | Missing from pseudocode |
|---|---|---|---|
| `docs/gate1_pseudocode.txt` | Process port/adapters, readiness, EULA, fake server, conformance | `app/ports/`, `app/platform/process/`, `app/infrastructure/minecraft/`, `app/services/worlds.py`; `tests/adapters/test_conformance.py` | Does not represent the complete current port, per-type capability rules, all C1-C14 implementation details, or live platform evidence. |
| `docs/gate2_pseudocode.txt` | SQLite/schema, values/exceptions, authentication, configuration | `app/infrastructure/sqlite/`, `app/domain/`, `app/services/auth.py`, `configuration.py`; migration/auth/config tests | Does not cover all 28 schema definitions and invariants, all entities/events, complete permission/security/API behavior, or every versioned table. |
| `docs/gate3_pseudocode.txt` | Operations, runtime/reconciliation, scheduler/missed runs, audit/notifications | `app/services/{operations,runtime,reconciliation,scheduler,audit,notifications}.py`; Gate 3 tests | Selected service flows only; not the complete Document 8/9 conflict matrix, all Operation types, or full event/test inventory. |
| `docs/gate4_pseudocode.txt` | Backup, restore, cleanup, sync | `app/services/{backup,restore,cleanup,sync}.py`, backup engine, Gate 4 tests | Body has known superseded semantics; does not fully represent the current cleanup scope limits, exact Document 8 sync contract, or all Document 14 recovery cases. |
| `docs/gate5_pseudocode.txt` | Middleware/security, example API delegation, SSE client, shell geometry, sample E2E/performance tests | `app/web/`, `app/web/streams/`, `app/shell/`, integration/browser tests | It is not a complete 110-route contract, UI module inventory, auth matrix, error/schema map, or genuine E2E/performance suite. Example paths and interfaces are historical. |

**Answers to pseudocode questions:** the pseudocode is useful as historical rationale and selected examples, but it is not complete or detailed enough to serve as an exhaustive executable blueprint. It does not contain every plan component/function or every test. Mapping should use the numbered plans and actual source; the files should remain labeled consistently historical/superseded per `KB-DOC-PSEUDOCODE-DECISION`.

## 4. Explicit gaps and deviations

### 4.1 Missing or unavailable product behavior

1. **Manager lifecycle:** manager restore, restart, update, rollback are registered API paths but return `501 NOT_IMPLEMENTED`; their recovery, supervisor, trusted-update, and compatibility contracts are not yet approved. (`KB-G5-8`)
2. **Cleanup scopes:** cleanup supports backup-artifact retention only. `stale_worlds` and `logs` are unsupported; eligibility and retention safeguards need a product decision before implementation. (`KB-G5-CLEANUP-POLICY`, `KB-G5-CLEANUP-SCOPES`)
3. **Sync concurrency:** the documented global cap of two simultaneous transfers has no demonstrated admission guard. The implemented daily 50-GiB limit is a different control. Reconcile retry count and waits across Document 8, API/WBS, implementation, and tests. (`KB-G8-SYNC-CAP`)
4. **Full API contract parity:** all 110 documented paths are registered, but registration does not prove auth/session/CSRF/step-up, payload validation, response shapes, error mapping, or feature behavior. (`KB-G5-API-CONTRACT`)
5. **Architecture contracts:** no dedicated AuthorizationService/FileManagerService/TemplateService/JavaRuntimeService; only a world command module; planned repository modules absent; RuntimeService is a facade; services retain SQL-through-persistence-connection patterns. Decide whether to refactor or revise the target architecture. (`KB-D12-2`)
6. **Import boundary:** `app/services/server_properties.py` has a concrete import from `app.infrastructure.minecraft.properties_schema`; the workboard records the dependency-boundary regression test failing. (`KB-G0-BOUNDARY-REGRESSION`)
7. **Full domain event catalog:** only two typed domain events are declared; map every planned Document 6 event to typed events or document the intentional alternate representation.
8. **Curated shipped docs:** `app/docs/` is empty except `.gitkeep`; this is expected while new production docs are deferred, but the runtime route/UI has no content to serve at present.

### 4.2 Missing or insufficient tests/evidence

- Full-suite acceptance: the recorded run has 8 failures, 251 warnings, and shutdown database-access warnings from queued workers.
- Complete service-level unit tests, every Document 6 state/invariant, every Document 8 operation flow, every Document 9 conflict cell/interleaving, and every versioned-config entity are not proven by the existing focused suites.
- Full UI workflows and canonical login/rehydrate/start/live-log/stop and crash-to-notification E2E flows are not represented by a dedicated Python E2E package.
- POSIX conformance and hosted cross-OS results are incomplete; Windows/fake results do not prove POSIX behavior.
- Live Vanilla/Paper/Fabric/Forge, Java compatibility, EULA, RCON, readiness, and save coordination evidence remains blocked/incomplete.
- Performance thresholds exist in `benchmarks/thresholds.json`, but profile calibration and measured acceptance are not recorded as complete.
- Security, route-level authorization, SSE reconnect/proxy behavior, deploy topology, compatibility, flexibility, and the entire ISO/IEC 25010 evidence map need acceptance.
- Coverage is below the documented floors; the configured overall floor and Document 11's stated overall floor disagree.

### 4.3 Architectural and document deviations

| Area | Plan | Current state | Severity |
|---|---|---|---|
| Runtime docs placement | Documents 5/10 say repository `docs/`; Document 12 says distributed `app/docs/` | API resolves content from the app package; app content directory is currently empty | Plan conflict; resolve without moving planning docs. |
| Markdown handling | Document 5 requires source/text display until a trusted renderer exists | `operator_ui.js` converts a limited Markdown subset to HTML | Behavioral/documentation mismatch; confirm intended renderer and security contract. |
| Service boundaries | Separate services depend on ports; modular per-service structure | Several responsibilities consolidated; direct concrete import and SQL access patterns exist | Maintainability and contract divergence; some are concrete failing evidence. |
| Command/query and repositories | Document 12 target layout includes broader command/query/repository modules | `app/commands/` contains `world.py`; named SQLite repository modules are absent | Architecture decision/migration still open. |
| Domain representation | Document 6 allows hybrid persistence-backed concepts | WorldInstance is the main pure domain entity; most other concepts are rows | Intentional per Document 6 §7; not itself a defect. |
| Event representation | Document 6 full typed event catalog | Two typed domain event classes; rest not represented as a complete typed catalog | Inventory/architecture gap; behavior must be traced before labeling functions missing. |
| UI source organization | Document 5 enumerates workflows/pages | One dynamic `operator_ui.js` implements multiple modules | Consolidated; acceptable only if all workflows and test expectations are satisfied. |
| WBS | Current `app/` layout and exact requirements | Several old `src/mcmanager/` paths and stale dependency/retry descriptions remain | Known inaccurate planning artifact; `KB-DOC-WBS` open. |
| Product stage | Production app under `app/`; separate prototype archive | Workboard correctly distinguishes production app from prototype folder; app contains real implementation | Do not label production app a prototype. It remains incomplete/release-blocked. |

## 5. Workboard and WBS reconciliation

### 5.1 Workboard status inventory

The workboard has **61 cards**: 31 Done, 5 Review, 18 To Do, 5 Blocked, and 2 Backlog. It maps the main known gaps to owning tasks and distinguishes gate-level from slice-level progress. This makes it the better status source, but it is not yet an exhaustive per-requirement/component/function/test ledger.

| Board section | Cards | Reconciliation |
|---|---:|---|
| Done | 31 | Records scoped implementation/test outcomes such as migration verification, selected lifecycle, API and gate slices. These do not imply that all of Documents 4-14 or a whole release gate is done. |
| Review | 5 | Implementation exists but acceptance/review remains: `KB-G5-3`, `KB-G5-CLEANUP-POLICY-API`, `KB-G4-VERIFY`, `KB-G5-11`, `KB-G1-LOG-REPLAY`. |
| To Do | 18 | Correctly tracks the major outstanding code, product decision, architecture, test, and documentation reconciliation work (IDs below). |
| Blocked | 5 | External/platform evidence or environment calibration is pending: real Minecraft, static gates, deployment metrics, POSIX, performance. |
| Backlog | 2 | Legacy-doc archive clarification and full Document 10 route parity inventory remain intentionally unstarted. |

#### Done-card register

The 31 Done cards map to specific slices in this report as follows:

| Inventory area | Done cards |
|---|---|
| Distribution/package and data boundary | `KB-LAYOUT-01`, `KB-PACKAGE-01`, `KB-DATA-01` |
| Domain, schema, and configuration | `KB-G2-ENTITY-MODEL`, `KB-G2-DOMAIN`, `KB-G2-MIGRATION`, `KB-G2-2`, `KB-G2-3` |
| Process/Minecraft adapters | `KB-G1-1`, `KB-G1-2`, `KB-G1-3`, `KB-G1-4` |
| Operations and control plane | `KB-G3-1`, `KB-G3-2`, `KB-G3-3`, `KB-G3-4`, `KB-G3-5` |
| API, UI, streams, and cancellation slices | `KB-G5-WORLD-LIST`, `KB-G5-1`, `KB-G5-2`, `KB-G5-4`, `KB-G5-5`, `KB-G5-7`, `KB-G5-9` |
| General gates and architecture | `KB-G0-1`, `KB-G0-2`, `KB-G0-3`, `KB-G0-4`, `KB-G0-6`, `KB-D12-1` |
| Documentation/status reconciliation | `KB-DOC-STATUS` |

These are not blanket pass claims: each status is limited to the card's acceptance evidence and date.

### 5.3 Open-card-to-inventory crosswalk

| Workboard cards | Master inventory area |
|---|---|
| `KB-G0-7`, `KB-G0-5`, `KB-G0-BOUNDARY-REGRESSION` | Full-suite failures, static gates, import boundary |
| `KB-G5-CLEANUP-POLICY`, `KB-G5-CLEANUP-SCOPES`, `KB-G5-CLEANUP-POLICY-API`, `KB-G5-3` | Cleanup policy, supported scopes, API/feature acceptance |
| `KB-G5-8`, `KB-G5-6` | Manager lifecycle backend and complete operator workflows |
| `KB-G8-CONTRACT`, `KB-G8-SYNC-CAP`, `KB-G9-CONTRACT` | Document 8/9 service and concurrency contract parity |
| `KB-D11-TEST-PYRAMID`, `KB-D11-COVERAGE`, `KB-D11-ISO-25010`, `KB-PERF-01` | Test distribution, coverage, quality/performance evidence |
| `KB-G1-MINECRAFT`, `KB-G1-6`, `KB-G1-FORGE-SHUTDOWN`, `KB-G1-LOG-REPLAY`, `KB-G5-10` | Live/platform/process/SSE acceptance |
| `KB-G5-API-CONTRACT`, `KB-G5-1`, `KB-G5-2`, `KB-G5-5`, `KB-G5-7`, `KB-G5-9` | HTTP/SSE authorization, lifecycle routes, files/logs, streams, cancellation |
| `KB-D12-2`, `KB-G0-1`, `KB-D12-1` | Service/repository/command structure and dependency boundaries |
| `KB-DOC-PLAN-COHERENCE`, `KB-DOC-PSEUDOCODE-DECISION`, `KB-DOC-WBS`, `KB-DOC-EVIDENCE-QUALITY`, `KB-DOC-STATUS`, `KB-DOC-LEGACY-ARCHIVE` | Documentation conflicts, pseudocode status, WBS accuracy, status/evidence hygiene |
| `KB-G2-ENTITY-MODEL`, `KB-G2-DOMAIN`, `KB-G2-MIGRATION`, `KB-G2-2`, `KB-G2-3` | Document 6/7 and configuration model; scope is domain/schema slices, not whole-system completion |
| `KB-G3-1` through `KB-G3-5` | Operations, conflict handling, audit/notifications, reconciliation, scheduler |
| `KB-G4-VERIFY` | Backup, restore, cleanup, sync and filesystem acceptance |
| `KB-G5-WORLD-LIST`, `KB-G5-4`, `KB-G5-API-CONTRACT` | World list, settings/catalog/admin API and route-level parity |

### 5.4 Tracking accuracy verdict

- **Workboard:** useful and mostly aligned with known high-level gaps. Its explicit caveat that slice-level completion differs from gate/release completion is correct. Some cards remain broad inventory/decision cards; they do not themselves enumerate every planned function and test.
- **WBS:** useful as work-package/dependency history, but not a reliable current completion ledger. It contains stale `src/mcmanager/` paths, a "zero-dependency" description that does not accurately describe the Flask application, and sync retry wording inconsistent with Document 8. `KB-DOC-WBS` tracks these issues.
- **Overall:** tracking is **moderately accurate but incomplete**. It is possible to identify principal next steps, but not to derive exact system completion percentages or prove all planned functions/tests from WBS/workboard statuses alone.

## 6. Ordered next steps

The board remains the task authority; this order is a recommendation from the reconciliation, not a replacement for task ownership/dependencies.

1. **Restore trustworthy verification first:** resolve the current full-suite failures and warnings; fix the service-boundary failure; restore configured static gates (`KB-G0-7`, `KB-G0-BOUNDARY-REGRESSION`, `KB-G0-5`).
2. **Close product-contract decisions before destructive/manager work:** decide stale-world/log cleanup policy and the sync concurrency/retry contract (`KB-G5-CLEANUP-POLICY`, `KB-G8-SYNC-CAP`).
3. **Implement only the approved missing behavior:** stale-world/log cleanup (`KB-G5-CLEANUP-SCOPES`); define manager recovery/security/update contracts before manager restore/restart/update/rollback (`KB-G5-8`).
4. **Complete API and service contract inventories:** check each route for auth, CSRF, role, step-up, input/output shape, status, errors, and explicit unavailable behavior; finish Document 8/9 mapping (`KB-G5-API-CONTRACT`, `KB-G8-CONTRACT`, `KB-G9-CONTRACT`).
5. **Make an architecture decision:** preserve current consolidated implementation with revised docs or migrate incrementally to the missing command/query/repository/service boundaries; avoid broad refactoring before the concrete import-boundary defect is fixed (`KB-D12-2`).
6. **Close platform/Minecraft acceptance:** run C1-C14 on POSIX and hosted OS matrix; perform isolated, disposable live-server spikes for supported server types; retain only verified evidence (`KB-G1-6`, `KB-G1-MINECRAFT`, `KB-G1-FORGE-SHUTDOWN`).
7. **Complete test and quality gates:** full UI/API/process E2E, missing service/concurrency/invariant cases, coverage floors, ISO quality map, and calibrated benchmark runs (`KB-D11-TEST-PYRAMID`, `KB-D11-COVERAGE`, `KB-D11-ISO-25010`, `KB-PERF-01`, `KB-G5-10`).
8. **Reconcile docs without moving the plans:** align Documents 5/10/12 on distributed runtime docs; decide Markdown rendering; keep five pseudocode files historical or refresh them deliberately; correct WBS paths/retry statements and date every verification claim (`KB-DOC-PLAN-COHERENCE`, `KB-DOC-PSEUDOCODE-DECISION`, `KB-DOC-WBS`, `KB-DOC-EVIDENCE-QUALITY`).

## 7. Final answers to the audit questions

1. **Are the plans coherent?** Mostly. Architecture provides a sound precedence model and Documents 4-14 cover the system in depth. Runtime documentation placement, sync cap/retry wording, and some WBS details conflict or are stale.
2. **Does implementation conform to all plans?** No. It conforms in many important slices but has documented and observed gaps, route placeholders, architecture deviations, and incomplete cross-platform/quality acceptance.
3. **Is repository structure organized or spaghetti?** Layered and recognizable, not spaghetti. It is too divergent from some target boundaries and has legacy/planning clutter outside the production `app/` boundary; those folders should not be confused with the production payload.
4. **Are pseudocodes complete and detailed?** No. All five are explicitly superseded historical examples and cover selected Gate 1-5 slices only.
5. **Are all planned components/functions present in pseudocode?** No. The pseudocode does not enumerate every domain event, service responsibility, HTTP route, UI workflow, constraint, test, or acceptance criterion.
6. **Are all planned components/functions present in source?** No. Major functionality exists, but manager lifecycle actions and stale-world/log cleanup are unavailable; sync concurrency is unresolved; multiple named architecture components are consolidated or absent; full event/test/API parity is not demonstrated.
7. **Is source code complete?** No. The latest recorded full suite fails, static gates are not green, and multiple planned behaviors/platforms remain unaccepted.
8. **Do WBS/workboard show the complete todo list and accurately track it?** They show the main open work and provide actionable owners/cards, but neither is a proven exhaustive function/component/test list. The workboard is the better current status source; several statuses represent slices, not whole plans.
9. **Are tests written for all functions/components?** No. Many focused tests exist, but complete domain/service/API/conflict/E2E/platform/performance coverage and documented coverage floors are not met.
10. **How accurate is project tracking?** Moderate, not definitive. Workboard tracks significant gaps and correctly marks the overall product as incomplete; stale WBS details and lack of an exhaustive requirement-to-test ledger limit confidence in completion claims.

## 8. Evidence references

- Governing plan: [Architecture](docs/ARCHITECTURE.md), [Documents 4-14](docs/).
- Pseudocode: [Gate 1](docs/gate1_pseudocode.txt), [Gate 2](docs/gate2_pseudocode.txt), [Gate 3](docs/gate3_pseudocode.txt), [Gate 4](docs/gate4_pseudocode.txt), [Gate 5](docs/gate5_pseudocode.txt).
- Current tracking and recorded test evidence: [WORKBOARD.md](docs/WORKBOARD.md), [wbs.txt](docs/wbs.txt).
- Production source boundary: `app/`; runtime documentation placeholder: `app/docs/.gitkeep`.
- Test inventory: `tests/unit/`, `tests/integration/`, `tests/adapters/`, `tests/browser/`.
- Performance assets: `benchmarks/thresholds.json`, `benchmarks/performance_acceptance.py`, `benchmarks/spike_real_minecraft.py`.
