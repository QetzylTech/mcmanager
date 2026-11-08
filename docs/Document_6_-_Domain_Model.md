# Document 6: Domain Model

Users = individual named accounts (own username+password), not shared per-role credentials.

## Audit invariant (defined once here; reference by name elsewhere)

- Every login attempt (success/fail) → audit record: user_id, device_id (or raw IP/device-name if unrecognized), timestamp.
- User-action AuditRecord snapshots user_id, username, device_id (or raw IP/device-name) **at write time** — never by joining live tables later. username snapshot keeps logs readable after soft-delete/rename.
- Every state change = durable Operation; only an Operation's terminal transition (`Completed`, `Failed`, `Cancelled`, `TimedOut`) appends an `audit_records` row. Intermediate creation, queue, validation, running, and progress states do not. Corrections/acks = new rows via `annotation_of` (§2.9), never updates.
- Audit records are also created for security/auth events and explicit `ConfigEdit` operations with before/after diffs.
- Named accounts = second attribution layer (who) atop device/IP (from what); never replaces it.
- **Anonymization out of scope by design.** `audit_records`, `notification_reads`, `missed_run_records`, `sync_records`, `sync_attempts` permanent/unmodifiable — no erasure. Only permitted mechanism: data minimization at write time. Gap with law = documented, accepted product limitation; legal review before launch.

## 1 Core entities

Field shorthand: `field: [type, constraints]` (PK, FK, UNIQUE, IMMUTABLE, NULL, snapshot).

### 1.1 User (aggregate root; distinct from Device)
- `user_id` [TEXT, PK, IMMUTABLE] — never reused, even after deletion.
- `username` [TEXT, UNIQUE among non-deleted] — editable (admin/superadmin/self, step-up); never a FK; `user_id` is the durable reference.
- `display_name` [TEXT NULL]; `password` [SecretRef → `secrets` table, never on row].
- `status` [active|disabled|locked|deleted(soft)]; `failed_login_count`, `locked_until` (retry throttle/lockout).
- `created_by` [TEXT NULL] self-ref FK (accountability).
- Relationships: many RoleAssignments; direct Permission grants; actor on Operations/AuditRecords; many ClientSessions (User=identity, Device=trust context, IP separate).
- Login = username+password. Device identity recorded alongside login for audit only; never substitutes for a credential.
- NOT modeled: multiple humans sharing one User row. Same privilege ⇒ two User rows.

### 1.2 RuntimeSession (child of WorldInstance)
One continuous execution, confirmed startup → confirmed stop. Durable columns (survive restart):
- `session_id` [PK IMMUTABLE]; `world_id` [FK→world_instances RESTRICT]; `started_at` [INTEGER — set only at confirmed-`running`, not button press]; `ended_at` [NULL]; `end_reason` [graceful_stop|forced_stop|crashed|emergency_stop|reconciled_missing, NULL while open]; `rcon_secret_ref` [FK→secrets RESTRICT, never raw credential]; `port_used`; `java_runtime_id`; `launch_args_snapshot` [JSON] captured at launch for audit.
- NOT persisted: PID/handle, live health results — runtime-registry concerns reconstructed at boot.
- Constraint: exactly one open session per world — partial unique index on `world_id WHERE ended_at IS NULL`.

## 2 Lifecycles & state machines

### 2.1 User
`Provisioned → Active`; `Active ↔ Disabled` (admin); `Active → Locked` (N consecutive fails) `→ Active` (cooldown OR admin unlock); `Active | Disabled → Deleted` (soft, terminal). Hard delete never while any Operation/AuditRecord/Notification references user_id (in practice always — audit append-only/permanent).

### 2.2 RuntimeSession
`(running confirmed) → Open`; `Open → Closed[graceful_stop | forced_stop | crashed | emergency_stop | reconciled_missing]`. Created only at confirmed `running`; failed/aborted starts produce no session. Manager restart: open session matched to live process → stays Open; no match → force-close `reconciled_missing`. Invariant: no Open session after reconciliation pass completes.

### 2.3 WorldInstance
```
off → queued (Start created) → starting (launch attempted) → running (readiness per Doc 14 §3; RuntimeSession opens here)
starting → error (exit/timeout before readiness)
running → stopping (operator, idle auto-stop, or emergency)
running → crashed (unexpected exit, no Stop in flight)
running | off → backing_up (Backup created)
off → restoring (Restore created — off-only)
stopping → off (shutdown confirmed)
backing_up → resume_state (off|running) | error
restoring → off (success or safely-reverted failure) | error (cannot safely auto-revert)
eula_required → off (explicit audited EULA acceptance — Doc 14 §5)
error → off | crashed → off (explicit operator acknowledgement — never auto-clears)
off → tombstoned (DeleteWorld completes)
```
- Operation types: CreateWorld, Start, Stop, Kill, Backup, Restore, Cleanup, Sync, ConfigEdit, CrashDetected, DeleteWorld. CreateWorld provisions directories/ports/registry row from a Template; DeleteWorld tombstones with wide historical fan-out.
- DeleteWorld: only reachable from `off`; rejects outright (never queues) otherwise.
- `resume_state`: WorldInstance persists `pre_backup_state` (`off`|`running`) and returns to it on success — never unconditionally to `off`.
- `eula_required`: entered when CreateWorld provisions without an accepted EULA, or external edit reverts `eula.txt`→false at next Start (Doc 14 §5). Start rejected while `eula_required`; only explicit audited acceptance returns to `off`. Never auto-clears.

### 2.4 Operation
`Created → Queued → Validating → Running → Completed | Failed | TimedOut`; `Validating → Failed` (precondition/guard rejection); `Queued | Validating → Cancelled` (cancellable types only). Terminal states never reopened. Termination-from-`Running` forbidden with exactly one exception: Kill atomically cancels in-flight Stop (`error_code = 'superseded_by_kill'`) and becomes sole in-flight Operation — derived lock always sees exactly one non-terminal Operation per world. Compensating actions = **new** Operations referencing the failed op's `id`. Crash detection observation-driven: system-actor `CrashDetected` (actor = `system`).

### 2.5 BackupArtifact
`(backup succeeds) → Created [immutable]`; `Created → Deleted (soft)`. Rows created only on successful capture — no pending/failed artifact state. Soft delete: `deleted_at` + `deleted_by_operation_id`, file removed, row retained. Retention-protection invariant: keep-newest-N floor per category + always the single most recent artifact of a required category — immune to ordinary cleanup (dry or wet); only explicit superadmin force-flow bypasses (elevated confirmation + immutable logging). ManagerBackup: `world_id` NULL = manager's own state (DB, global settings, templates, role/permission assignments — no world content), `category = 'manager_config'`. Lineage via existing FKs (`restore_history.source_artifact_id` → Backup A, `pre_restore_artifact_id` → Backup B, `sync_records.artifact_id` → Backup B's sync) — two-hop join; no graph/edge table.

### 2.6 Schedule
`Created → Enabled | Disabled; Enabled ↔ Disabled`; any field edit → `version++`, `last_changed_by/at`, ConfigEdit Operation + audit; `Enabled | Disabled → deleted_at` (soft). No hard delete; "delete" sets `deleted_at`, stops firing, row+edit history queryable; physical removal only via Cleanup. `version` = optimistic concurrency — stale edit rejected (never last-write-wins). World tombstone ⇒ world-scoped Schedules soft-deleted with it (not hard-cascade).

### 2.6.1 MissedRunRecord (T1 — permanent; never deleted, soft or hard, by anything incl. Cleanup)
`(run doesn't fire) → Created, resolution = pending`; `pending → resolved | ignored` (terminal). Fields: `schedule_id` (plain value, not FK), `schedule_name_snapshot`, `schedule_type_snapshot` (write-once at detection), `expected_run_at`, `detected_at`, `resolution`, `resolution_at`, `resolution_by`. Events: `MissedRunDetected/Resolved/Ignored`.

### 2.7 CleanupPolicy
`Created → Enabled | Disabled; ↔`; any edit → `version++`, ConfigEdit + audit; → `deleted_at` (soft). Same soft-delete/logging/versioning as Schedule; tombstone soft-deletes world-scoped policies. Hard-guard invariants: Age floor 3 days (cannot save lower); Count floor 3 per backup category (session/manual/pre_restore/emergency) + per stale-world scope; floors + §2.5 retention-protection = one guarantee — a policy edit stranding a required artifact below floor rejected at save.

### 2.8 Notification
`Created → Read (per-user) | ActionTaken | Dismissed`. Never deletable through any UI path — only acknowledged/read/addressed; Dismissed clears the dropdown view, row stays permanently queryable on Audit/History. `severity [critical|high|normal|informational]` drives dropdown ordering. Mapping: critical = world crashed, unauthorized attempt, critical low storage; high = backup/restore failed, sync failed (terminal); normal = missed job, sync retry, suspicious activity; informational = started/stopped, backup/cleanup succeeded. Per-user read via `NotificationRead(notification_id, user_id, read_at)` join — never a boolean column; broadcast notifications read independently by multiple users.

Log channel behavior is environment-driven: with `VERBOSE_LOGGING=false`, `debug` is suppressed and `minecraft` retains only severe warnings, errors, crashes, and readiness markers; backup/restore and sync omit step-level traces. With `VERBOSE_LOGGING=true`, all canonical channels retain full output.

### 2.9 AuditRecord
`(terminal operation transition | security/auth event | ConfigEdit) → Created [terminal — insert-only log]`. Operation audit rows are created only for `Completed`, `Failed`, `Cancelled`, or `TimedOut`; intermediate checkpoints are not audited. Corrections/acks = new rows with `annotation_of` self-ref — never updates.

### 2.10 Manager (singleton — exactly one row per deployment, hard invariant)
`Uninitialized → SetupInProgress → Operational`; `Operational → UpdateInProgress → Operational`; `Operational → RollbackInProgress → Operational`. Owns deployed version/commit, setup-completion flag, composition of `global_settings`. **Settings inheritance — exactly three tiers, the ONLY pattern for any world-specific setting:** (1) Manager default = `global_settings` baseline; (2) World override = `world_id`-scoped row in same table; (3) Effective = "override if one exists and is enabled, else Manager default" — never both, never neither-silently-picked. Exception: notification defaults (sound/message templates) Manager-default-only — no per-world override. Future integrations (Discord/Prometheus/Grafana/Home Assistant/webhooks): small purpose-specific port (`NotificationAdapter`, `MetricsExportAdapter`, …) configured with the same global-default-with-world-override shape; no new entities until a concrete requirement. Events: `ManagerSetupCompleted`, `ManagerUpdateStarted/Completed`, `ManagerRolledBack`, `ManagerRestarted`.

### 2.11 JavaRuntime
`Registered → Verified (health check)`; `Registered | Verified → Missing (path gone at boot)`; `Verified → Deprecated → deleted_at (soft)`. Never hard-deleted if any RuntimeSession `launch_args_snapshot` references it (even tombstoned worlds) — in practice almost never leaves Deprecated. Events: `JavaRuntimeRegistered/Verified/MarkedMissing/Deprecated`.

### 2.12 Template
`Created → Updated (versioned)`; `Created | Updated → Deprecated → deleted_at (soft)`. Referenced by any WorldInstance creation history → never hard-deleted, only deprecated; template "delete" = this deprecation. Events: `TemplateCreated/Updated/Deprecated/Deleted(soft)`.

### 2.13 Device
`Unrecognized → Registered (admin approval)`; `Registered → Updated | Revoked`. Never hard-deleted once any AuditRecord/ClientSession snapshotted its `device_id` (effectively always). "Delete" = Revoked. Events: `DeviceRegistered/Updated/Revoked` (`last_seen_at` = field update, not event).

### 2.14 ClientSession
`Created → Active → Expired (passive) | Revoked (logout/admin/password change)`; `Active → StepUpConfirmed` (temporary elevated state, reverts to Active). Step-up: session-scoped, time-bounded (default 10 min), server-enforced on every elevated request; reverts on expiry/revocation/context change. Password never stored/cached/pre-filled — entered, verified, discarded. Invariant: Expired/Revoked session can never authorize — enforced server-side on every request. Revocation uses shared `deleted_at`; expiry time-based (`expires_at`). Token stored hashed on ClientSession row, NOT in `secrets` (short-lived, self-invalidating — deliberate scope boundary). Events: `ClientSessionCreated/Expired/Revoked/StepUpConfirmed`.

### 2.15 Role
`Created → Updated (ConfigEdit + audit)`; `Created | Updated → deleted_at (soft; custom only, no current holders)`. Baseline roles (non-deletable, `is_system_role = true`): **Client** (base, read-only + any individually granted permissions), **Admin** (full world authority — start/stop/backup/restore/maintenance across all worlds — but NO control-panel/user/role management, no manager settings/update/rollback), **Superadmin** (everything Admin + control-panel: user accounts, role/permission assignment, manager-wide settings, update/rollback/restart). Custom roles: freely created/edited/soft-deleted subject to no current holders. Trio never deleted, soft or hard — same non-bypassable guard category as the §4 superadmin floor. Events: `RoleCreated/Updated/Deleted(soft)`.

### 2.16 Permission & RoleAssignment
`Granted → Revoked (deleted_at set, ConfigEdit Operation + audit)`. Delegation invariant: **only a Superadmin** may create/revoke a `permissions` row for another User (how a Client gets cleanup/maintenance without full Admin promotion). Admin has full world authority but cannot grant permissions. Permission attaches to a Role (all holders) OR directly to a User (per-world override) — one mechanism, two attachment points. Revocation soft (shared `deleted_at`); "who could do what, when" stays reconstructable. Physical removal only via Cleanup. Events: `PermissionGranted/Revoked`, `RoleAssignmentGranted/Revoked`.

### 2.17 SyncTarget
`Created → Updated (ConfigEdit + audit)`; `Created | Updated → deleted_at (soft — Tier 2)`. One offsite destination: `type [nas|google_drive|other]`, non-secret config, credential ref in `secrets`, scope `[global|world]` — same global-default-with-per-world-override shape as Schedule/CleanupPolicy. Invariant: exactly one resolvable SyncTarget per world at sync time (world override if present+enabled, else global default, else none = nothing to do, not an error). Events: `SyncTargetCreated/Updated/Deleted(soft)`.

### 2.17.1 SyncRecord (job wrapper over immutable SyncAttempt rows)
`(Sync dispatched) → Created, status = pending → succeeded | failed`. One sync job (one artifact, one target, one Operation). Never deleted (Tier 1). `status` derived from most recent SyncAttempt — never set independently; only moves forward. Fields: `sync_id`, `artifact_id [FK RESTRICT]`, `sync_target_id [FK RESTRICT]`, `operation_id [FK RESTRICT]`, `status`, `started_at`, `finished_at`, `created_at`. Events: `SyncJobStarted/Succeeded/Failed`.

### 2.17.2 SyncAttempt (the actual retry history)
`(one transfer attempt) → Created [immutable — never updated, never deleted]`. One row per attempt, always (first-try success = 1 row; 2 failures + success = 3). Fields: `attempt_id`, `sync_id [FK RESTRICT]`, `attempt_number [UNIQUE(sync_id, attempt_number), strictly sequential from 1, no gaps]`, `started_at`, `finished_at`, `outcome [succeeded|failed_transient|failed_permanent]`, `error_message NULL`, `created_at`. `failed_transient` = retryable (network); `failed_permanent` = not (rejected credentials etc.) → SyncRecord `failed` immediately. Events: `SyncAttemptSucceeded/FailedTransient/FailedPermanent`.

### 2.18–2.19 Notification + AuditRecord events
`NotificationCreated/Read/ActionTaken/Dismissed`; `AuditRecordCreated` only — no update/delete event by design.

## 3 Domain events (full catalog)

- **User:** `UserCreated`, `UserRoleChanged`, `UserPermissionGranted/Revoked`, `UserDisabled/Enabled/Locked/Unlocked`, `UserPasswordChanged`, `UserDeleted`. Privilege changes MUST produce an AuditRecord — hard requirement.
- **RuntimeSession:** `RuntimeSessionStarted`, `RuntimeSessionEnded` (carries `end_reason`), `RuntimeSessionReconciled` (only when restart forces a stale session closed).
- **WorldInstance:** `WorldCreated/Queued/Starting/Started/StartFailed/Stopping/Stopped/Crashed/BackingUp/BackupSucceeded (returns to resume_state)/BackupFailed/Restoring/RestoreSucceeded/RestoreFailed/ErrorAcknowledged/CrashAcknowledged/EulaRequired/EulaAccepted/Deleted(tombstoned)`.
- **Operation:** `OperationCreated/Queued/ValidationFailed/Started/Progress (checkpoint payload)/Completed/Failed/Cancelled/TimedOut`.
- **BackupArtifact:** `BackupArtifactCreated`, `BackupArtifactDeleted` (carries `deleted_by_operation_id`).
- **Schedule:** `ScheduleCreated/Updated (carries new version)/Enabled/Disabled/Deleted(soft)/RunDue/RunMissed (creates MissedRunRecord)`.
- **MissedRunRecord:** `MissedRunDetected/Resolved/Ignored`.
- **CleanupPolicy:** `CleanupPolicyCreated/Updated/Enabled/Disabled/Deleted(soft)/RunExecuted (dry|wet)/RunSummaryRecorded/HardDeletePerformed` — last fires once per row physically deleted (12 rows = 12 fires), per-row audit precision.
- **SyncTarget:** `SyncTargetCreated/Updated/Deleted(soft)`. **SyncRecord:** `SyncJobStarted/Succeeded/Failed`. **SyncAttempt:** `SyncAttemptSucceeded/FailedTransient/FailedPermanent`.
- **Notification:** `NotificationCreated/Read/ActionTaken/Dismissed`. **AuditRecord:** `AuditRecordCreated` only.

## 4 Business invariants

**User:** username unique among non-deleted; password SecretRef never null for an `active` User; ≥1 active Superadmin always exists — disabling/deleting/demoting the last is rejected outright (non-bypassable); a User can never authorize their own step-up action with standing session alone — password re-entry required; every User-action AuditRecord carries a device identity snapshot at action time (never reconstructed by joining current Device table).

**RuntimeSession:** exactly one open session per WorldInstance (schema-enforced); `rcon_secret_ref` generated for that specific session — never reused from a prior one; `ended_at` set once; `end_reason` immutable after set.

**WorldInstance:** every transition driven by an Operation (crash via `CrashDetected` system Operation — no carve-out); `pre_backup_state` set when entering `backing_up`, resolves to valid prior state (`off`|`running`); `error`/`crashed` require explicit acknowledgement before `off` — no code path silently clears; `restoring` entered only from `off` (rejected before an Operation is created); **world lock is derived, not stored** — "locked" exactly while an in-flight (non-terminal) Operation targets it: query `world_id = ? AND status IN ('Created','Queued','Validating','Running')`, no lock column (Doc 7). Runtime config (`java_runtime_id`, `launch_args`, `port`) editable only while `state = off`; write immediate (column update), effect deferred to next boot by construction (running process only reads config at boot — captured in `launch_args_snapshot`). Template independence: `template_id` provenance only; all runtime config copied into WorldInstance at CreateWorld and sole source of truth thereafter; editing/deprecating a Template never mutates an existing WorldInstance. RenameWorld (display_name only) = lightweight ConfigEdit-type Operation — no files/process, allowed concurrently with Backup/Restore/Cleanup. `eula_required`: Start rejected while EULA not accepted; only route to `off` is the explicit audited acceptance (Doc 14 §5).

**Operation:** Failed/TimedOut never rewritten to Completed, and vice versa — one-directional progression; any compensating action is a new Operation referencing the original by ID; every user-triggered WorldInstance transition has exactly one driving Operation; full mutual-exclusion rules in Doc 9 (supersedes any conflicting text elsewhere).

**Global Deletion:** no service, route, or command handler other than `CleanupService` ever executes a physical `DELETE FROM` (arch-enforced); Tier 1 entities excluded from Cleanup's sweep entirely — never candidates for physical deletion, by anyone, ever; every Tier 2 soft-delete/revoke produces a `ConfigEdit` Operation + AuditRecord.

**MissedRunRecord:** `resolution` starts `pending`, transitions to exactly one of `resolved`/`ignored`, terminal; snapshot fields write-once, fixed to moment of detection.

**SyncTarget / SyncRecord / SyncAttempt:** exactly one SyncTarget resolves per world at sync time — never zero-or-ambiguous, never two silently picked; SyncRecord `status` only moves `pending -> succeeded|failed`, always derived from its SyncAttempt rows; SyncAttempt rows immutable, `attempt_number` strictly sequential no gaps; sync failure never mutates `backup_artifacts` — local backup validity independent of offsite mirroring.

## 5 Value Objects

Closed sets here are normative for Doc 7 schema, Doc 10 API, and Doc 11 tests. Additions only via ARCHITECTURE §16 conflict-log entry. "String-typed by design" = documented closed set, never free text.

- `Username` — 3–32 chars, `[A-Za-z0-9._-]`, not starting `.` or `-`.
- `SecretRef` — opaque pointer into `secrets`; never carries the value outside the security subsystem.
- `WorldId` — immutable app-generated TEXT id (UUIDv4 or similar), never reused.
- `OperationType` — `CreateWorld | Start | Stop | Kill | Backup | Restore | Cleanup | Sync | ConfigEdit | CrashDetected | DeleteWorld`.
- `WorldState` — `off | queued | starting | running | stopping | restoring | backing_up | crashed | error | eula_required`. `pre_backup_state` = `WorldState | None` restricted to `{off, running}` while set (`eula_required` never a `pre_backup_state`).
- `OperationStatus` — `Created | Queued | Validating | Running | Completed | Failed | Cancelled | TimedOut`.
- `EndReason` — `graceful_stop | forced_stop | crashed | emergency_stop | reconciled_missing`.
- `TriggerType` — backup trigger classification: `session_end | manual | scheduled | pre_restore | emergency | manager_config`. Identical to BackupArtifact's `category`; one enum, two column names (`trigger_type` naming/metadata, `category` Doc 7).
- `NotificationSeverity` — `critical | high | normal | informational`; drives dropdown ordering, never free text.
- `SyncOutcome` — `succeeded | failed_transient | failed_permanent`. `failed_transient` = retryable; `failed_permanent` = terminal for that job.
- `SyncRecordStatus` — `pending | succeeded | failed`; derived from latest SyncAttempt, never set independently.
- `MissedRunResolution` — `pending | resolved | ignored`, terminal once set.
- `ScheduleType` — `backup | cleanup | maintenance`.
- `ScheduleScope` / `PolicyScope` / `SyncTargetScope` — one shared enum `scope`: `global | world`.
- `CleanupPolicySpaceRule` — nullable `space_rule_pct`; constrained 0 < pct ≤ 90 when set.
- `BackupCategory` — alias of `TriggerType`; normative name for Doc 7 `backup_artifacts.category`; API distinguishes `trigger` (cause) from `category` (classification) only in payload naming, never in allowed values.
- `UserStatus` — `active | disabled | locked` (storage; `deleted`/soft = `deleted_at` marker, not a status value).
- `JavaRuntimeStatus` — `registered | verified | missing | deprecated`.
- `DeviceStatus` — `unrecognized | registered` (revoked = `deleted_at` marker).
- `ActorType` — `user | system`.
- `ConfigEditEntity` — identifies the versioned entity a ConfigEdit targets: `schedules | cleanup_policies | global_settings | world_settings | templates | roles | sync_targets | world_instances(metadata) | server_properties | java_runtimes | users | devices | eula`. String-typed-by-design closed set (`eula` covers explicit EULA acceptance, Doc 14 §5).
- `EulaState` — `not_present | unaccepted | accepted` (Doc 14 §5). Detected from `eula.txt`; `accepted` written **only** by the explicit audited operator action — never by provisioning, never silently.
- `ServerReadinessLevel` — `process_alive | port_bound | rcon_ready | probe_ok | operationally_valid` (Doc 14 §3). Strictly ordered; highest available level for the server type gates `starting -> running`.
- String-typed-by-design closed sets (validated in code): `server_type` (Template/WorldInstance — must match an existing Template's category or built-in curated set); `addressing_strategy` (`subdomain | port | path`); `sync_target_type` (`nas | google_drive | other`); `notification_defaults` keys.
- `AddressingStrategy` — `subdomain | port | path`. One per world, not free text.
- `SyncTargetType` — `nas | google_drive | other` (`other` deliberately open-ended but a registered value, never raw text).

Versioning note: Doc 7 inline column comments reference this section by name — single source of truth, named rules applied, not duplicated.

## 6 Aggregate roots & deletion tiers

**Roots:** Manager (singleton), WorldInstance, Template, Device, User, Role. Everything else is a child/referenced entity inside one of those roots, never independently addressable: RuntimeSession, BackupArtifact, Operation, Schedule, CleanupPolicy, MissedRunRecord, Notification, NotificationRead, AuditRecord, Permission, ClientSession, JavaRuntime, SyncTarget, SyncRecord, SyncAttempt.

**Ownership rules**
- Manager owns: world registry, global settings, and (as defaults) Schedules/CleanupPolicies/SyncTargets not overridden per-world.
- WorldInstance owns: its RuntimeSessions, BackupArtifacts, world-scoped Operations, and its own Schedule/CleanupPolicy/SyncTarget overrides. Tombstoned, never hard-deleted — too much history hangs off its immutable ID.
- RuntimeSession is owned exclusively by one WorldInstance.
- User owns: its RoleAssignments, direct Permission grants; referenced as actor on its own Operations/AuditRecords/ClientSessions — but does not own those rows in the deletion sense (soft-deleted User leaves all historical references intact).
- Device is referenced by (never owns) ClientSessions and AuditRecords; reference survives revocation.
- Template/JavaRuntime are referenced by WorldInstance creation history / RuntimeSession launch snapshots, but own neither.
- Schedule/CleanupPolicy/SyncTarget are owned by either Manager (global) or one WorldInstance (override) — never both; resolution belongs to ConfigurationService.
- SyncRecord is owned by the BackupArtifact it mirrors (via its Sync Operation), not by SyncTarget. SyncAttempt is owned exclusively by its SyncRecord.
- **General rule (authoritative):** nothing is ever hard-deleted by a normal user-facing action. Tier 1 (AuditRecord, Notification, NotificationRead, MissedRunRecord, SyncRecord, SyncAttempt) is permanent and untouched even by Cleanup. Everything else that can be "deleted"/"revoked" — WorldInstance, Device, JavaRuntime, Template, User, BackupArtifact, Schedule, CleanupPolicy, Role, Permission, RoleAssignment, ClientSession, SyncTarget — is soft-marked with one shared `deleted_at` column, change logged, and the only physical delete in the system is the Cleanup subsystem.

**Global Deletion & Retention Model** (applies to every entity; classify any new entity here):
- **Tier 1 — Permanent, never deleted by anything, ever:** AuditRecord, Notification, NotificationRead, MissedRunRecord, SyncRecord, SyncAttempt.
- **Tier 2 — Soft-deleted/revoked immediately by normal operations, physically removed only by Cleanup, if ever:** WorldInstance, Device, JavaRuntime, Template, User, BackupArtifact (metadata row), Schedule, CleanupPolicy, Role (custom only), Permission grants, RoleAssignments, ClientSession, SyncTarget.
- No tier 3. No entity has a user-facing "delete" that physically removes a row directly.
- Column convention: one shared `deleted_at` timestamp for every Tier 2 soft-removal (conceptually "delete" or "revoke"), plus optional `deleted_by` actor. No `revoked_at` split.
- Hard-delete rule: only `CleanupService` (via a Cleanup Operation) ever issues a physical `DELETE FROM`. Cleanup sweeps expired artifacts and stale world data, and generalizes to aged-out already-soft-deleted Tier 2 config rows past their retention window once nothing depends on them. WorldInstance/Device/JavaRuntime/Template/User are Tier 2 in principle but rarely swept in practice (Tier 1 rows almost always still reference them) — "eligible for Cleanup" does not mean "will be swept."

## 7 Implementation representation decision

The application deliberately uses a hybrid representation of this model. This
section records the implementation boundary; it does not relax any lifecycle,
ownership, deletion, or persistence requirement above.

`WorldInstance` is the current pure, immutable domain entity. Its state,
backup-resume state, and tombstone invariants are enforced in
`app/domain/entities.py`, `app/domain/invariants.py`, and
`app/domain/lifecycle.py`. World lifecycle decisions return immutable domain
events. The closed sets in §5 are represented by `app/domain/value_objects.py`.

The remaining concepts are intentionally persistence-backed at this stage.
They have relationships, uniqueness, optimistic-version, partial-index, or
audit-history rules that must be atomically enforced with their durable row(s).
Their behavior belongs in the relevant service and SQLite repository/transaction
boundary, rather than in speculative duplicate dataclasses:

| Document 6 concept | Current representation and enforcement boundary |
|---|---|
| Manager and global/world settings | `manager`, `global_settings`, and `world_settings` rows; `ConfigurationService` resolves the three tiers and performs version-checked edits. |
| User, Role, RoleAssignment, Permission, Device, ClientSession, and SecretRef | `users`, role/permission, device, client-session, and `secrets` rows; authentication, step-up, authorization, and encrypted-secret behavior are service/repository concerns. |
| RuntimeSession and JavaRuntime | `runtime_sessions` and `java_runtimes` rows; the open-session partial unique index and runtime reconciliation enforce the durable/runtime split. |
| Template | `templates` rows; provenance and versioning are persisted so template edits cannot mutate existing worlds. |
| Operation and AuditRecord | `operations` and `audit_records` rows; operation/audit services enforce terminal transitions and append-only attribution. |
| BackupArtifact and restore history | `backup_artifacts` and `restore_history` rows; backup/restore services enforce capture, retention, and compensation behavior. |
| Schedule, CleanupPolicy, and MissedRunRecord | their schema rows; scheduler and cleanup services enforce optimistic edits, missed-run permanence, and retention floors. |
| Notification and NotificationRead | `notifications` and `notification_reads` rows; notification service preserves per-user read state. |
| SyncTarget, SyncRecord, and SyncAttempt | their schema rows; configuration and sync services resolve targets and persist immutable attempt history. |

Scalar concepts such as `Username`, `WorldId`, `SecretRef`, and
`CleanupPolicySpaceRule` remain validated strings/columns rather than wrapper
classes. Introducing wrappers without a distinct behavior or ownership boundary
would duplicate validation and risk divergence from the schema. New pure domain
types are required only when a concept gains in-memory state transitions or
invariants that can be decided independently of a transaction; otherwise its
durable constraints remain the source of truth.

This decision is covered by the domain contract and lifecycle tests
(`tests/unit/domain/test_domain_contracts.py` and
`tests/unit/domain/test_world_lifecycle.py`) and the Gate 2 integration tests
for schema, authentication/secrets, and configuration inheritance.
