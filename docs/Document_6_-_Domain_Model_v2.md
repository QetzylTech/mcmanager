# Document 6: Domain Model

Scope: every domain entity, lifecycle, invariant, event, ownership rule, and the Global
Deletion & Retention Model. Users are individual named accounts (own username + password),
not shared per-role credentials.

## 0.1 Global Audit Invariant (defined once here; reference by name — do not restate)

- Every login attempt — successful or failed — produces an audit record capturing `user_id`,
  `device_id` (or raw IP/device-name if the device isn't recognized/registered), and timestamp.
- Every User-action `AuditRecord` snapshots `user_id`, `username`, and `device_id` (or raw
  IP/device-name) at write time, never by joining live tables later — a later User
  rename/soft-delete or Device rename/reassign can never silently change an append-only
  record's meaning. `username` snapshot keeps logs readable after the User row is
  soft-deleted or renamed.
- Every state-changing action executes as a durable Operation; every Operation's creation
  and terminal transition produces exactly one `audit_records` row. Corrections/
  acknowledgements are new rows via `annotation_of` (§2.9), never updates to the original.
- Named accounts add a second attribution layer (`who`) on top of the legacy device/IP
  layer (`from what`) — they never replace it.
- **Anonymization is out of scope by design.** Audit snapshots are permanent and
  unmodifiable; there is no GDPR-style right-to-erasure scrubbing of `audit_records`,
  `notification_reads`, `missed_run_records`, `sync_records`, or `sync_attempts`. If
  anonymity is ever required, the only permitted mechanism is data minimization at write
  time: storing *less* identifying data at capture is a valid future policy change;
  mutating or deleting stored rows is not. Any gap with governing law is a documented,
  accepted product limitation requiring legal review before launch, not a future feature.

## 1. Core Entities

Field shorthand: `field: [type, constraints]` (PK, FK, UNIQUE, IMMUTABLE, NULL, snapshot).

### 1.1 User (aggregate root; distinct from Device)

- `user_id: [TEXT, PK, IMMUTABLE]` — never reused, even after deletion.
- `username: [TEXT, UNIQUE among non-deleted]` — editable by admin/superadmin or self,
  subject to step-up. Never a FK; `user_id` is the durable reference.
- `display_name: [TEXT NULL]` — cosmetic, no uniqueness.
- `password: [SecretRef]` — hash lives in `secrets` table, never on the User row.
- `status: [active|disabled|locked|deleted(soft)]`; `failed_login_count`, `locked_until`
  support retry throttling/lockout.
- Relationships: many RoleAssignments; many direct Permission grants (per-world overrides);
  actor on many Operations and AuditRecords; many ClientSessions (User = identity, Device =
  trust context, IP — separate concepts).
- Login = username + password. Device identity is recorded alongside every login for audit
  only (§0.1); it never substitutes for a credential.
- `created_by: [TEXT NULL]` — self-ref FK to provisioning user (accountability).
- NOT modeled: multiple humans sharing one User row. Same privilege level ⇒ two User rows
  with the same Role.

### 1.2 RuntimeSession (child of WorldInstance)

One continuous execution of a WorldInstance, from confirmed startup to confirmed stop.
Durable columns (survive restart):

- `session_id: [TEXT, PK, IMMUTABLE]`
- `world_id: [FK -> world_instances, RESTRICT]`
- `started_at: [INTEGER]` — set only at the confirmed-`running` transition, not button press.
- `ended_at: [INTEGER NULL]`; `end_reason: [graceful_stop|forced_stop|crashed|emergency_stop|reconciled_missing, NULL while open]`
- `rcon_secret_ref: [FK -> secrets, RESTRICT]` — never the raw credential.
- `port_used`, `java_runtime_id`, `launch_args_snapshot: [JSON]` — captured at launch for
  audit; independent of later edits.
- NOT persisted here: process PID/handle, live health-check results — runtime-registry
  concerns reconstructed at boot.
- Constraint: exactly one open session per world — partial unique index on `world_id WHERE
  ended_at IS NULL`.

## 2. Lifecycles & State Machines

### 2.1 User lifecycle
```
Provisioned -> Active
Active -> Disabled (admin) ; Disabled -> Active (admin re-enable)
Active -> Locked (N consecutive failed logins) ; Locked -> Active (cooldown OR admin unlock)
Active | Disabled -> Deleted (soft, terminal)
```
Hard delete never allowed while any Operation/AuditRecord/Notification references `user_id`
— in practice always, since audit history is append-only and permanent.

### 2.2 RuntimeSession lifecycle
```
(WorldInstance confirmed running) -> Open
Open -> Closed[graceful_stop | forced_stop | crashed | emergency_stop | reconciled_missing]
```
Created only at confirmed `running` — failed/aborted starts produce no session. On manager
restart: match open session to a discovered live process → remains Open; no match →
force-close `end_reason = reconciled_missing`. Invariant: no RuntimeSession is left `Open`
after a reconciliation pass completes.

### 2.3 WorldInstance lifecycle
```
(does not exist) -> off              (CreateWorld completes)
off -> queued          (Start created)
queued -> starting      (dispatch, launch attempted)
starting -> running     (readiness confirmed — RuntimeSession opens here)
starting -> error       (exit/timeout before readiness)
running -> stopping     (Stop: operator, idle auto-stop, or emergency)
running -> crashed      (unexpected exit, no Stop in flight)
running | off -> backing_up   (Backup created)
off -> restoring        (Restore created — off-only)
stopping -> off         (shutdown confirmed)
backing_up -> <resume_state>   (backup success)
backing_up -> error     (backup fails)
restoring -> off        (restore completes, success or safely-reverted failure)
restoring -> error      (restore fails, cannot safely auto-revert)
error -> off            (explicit operator acknowledgement — never auto-clears)
crashed -> off          (explicit operator acknowledgement — never auto-clears)
off -> (tombstoned)     (DeleteWorld completes)
```
- Operation types: CreateWorld, Start, Stop, Kill, Backup, Restore, Cleanup, Sync,
  ConfigEdit, CrashDetected, DeleteWorld. CreateWorld provisions directories/ports/registry
  row from a Template; DeleteWorld tombstones with wide historical fan-out.
- `DeleteWorld` invariant: only reachable from `off`; rejects outright (never queues)
  otherwise.
- `resume_state`: `backing_up` is reachable from `off` and `running`, so WorldInstance
  persists `pre_backup_state` and returns to it on success — never unconditionally to `off`.
- `error`/`crashed` are deliberately not self-clearing — errors surfaced, not silently
  recovered.

### 2.4 Operation lifecycle
```
Created -> Queued -> Validating -> Running -> Completed | Failed | TimedOut
Validating -> Failed          (precondition/guard rejection)
Queued | Validating -> Cancelled   (only for cancellable types)
```
- `Completed`/`Failed`/`Cancelled`/`TimedOut` are terminal; no terminal Operation is
  reopened.
- Termination-from-`Running` is forbidden with exactly one exception: `Kill` atomically
  cancels an in-flight `Stop` (`error_code = 'superseded_by_kill'`) and becomes the sole
  in-flight Operation. The derived world lock always sees exactly one non-terminal Operation
  per world.
- Compensating actions (failed-restore revert) are **new** Operations referencing the failed
  Operation's `id` — never a mutation of the original outcome.
- Crash detection is observation-driven: a system-actor `CrashDetected` Operation (actor =
  `system`) gives crash transitions the same durable-record treatment as user-triggered ones.

### 2.5 BackupArtifact lifecycle
```
(backup succeeds) -> Created   [immutable from this point]
Created -> Deleted   (soft)
```
- Rows created only on successful capture — no `pending`/`failed` artifact state. A failed
  backup = Failed Operation, no artifact row.
- Deletion is soft: `deleted_at` + `deleted_by_operation_id` set, file removed from disk,
  row retained.
- Retention-protection invariant: the "keep newest N" floor per category and always the
  single most recent artifact of a required category can never be deleted by an ordinary
  cleanup run (dry or wet). Only an explicit superadmin force-flow bypasses it (with
  elevated confirmation + immutable logging).
- ManagerBackup: `world_id` NULL-able; NULL = backup of manager's own state (DB, global
  settings, templates, role/permission assignments — no world content),
  `category = 'manager_config'`.
- Backup lineage: fully traceable through existing FKs — `restore_history.source_artifact_id`
  → Backup A, `pre_restore_artifact_id` → Backup B, `sync_records.artifact_id` → Backup B's
  sync. A two-hop join; no graph/edge table needed.

### 2.6 Schedule lifecycle
```
Created -> Enabled | Disabled ; Enabled <-> Disabled
(any field edit) -> version++, last_changed_by/at updated, ConfigEdit Operation + audit
Enabled | Disabled -> deleted_at set (soft)
```
- No direct hard delete. "Delete" sets `deleted_at`, stops firing; row and edit history
  remain queryable; physical removal only via Cleanup.
- `version` is optimistic-concurrency control: an edit against a stale `version` is rejected
  (never last-write-wins).
- World tombstone ⇒ world-scoped Schedules soft-deleted with it (not hard-cascade).

### 2.6.1 MissedRunRecord lifecycle (permanent — never deleted, soft or hard, by anything incl. Cleanup)
```
(scheduled run doesn't fire) -> Created, resolution = pending
pending -> resolved | ignored    (terminal; never back to pending)
```
- Fields: `schedule_id` (plain value, not enforced FK), `schedule_name_snapshot`,
  `schedule_type_snapshot` (captured at detection), `expected_run_at`, `detected_at`,
  `resolution`, `resolution_at`, `resolution_by`.
- Snapshot fields are write-once; record stays meaningful if the parent Schedule is
  edited/deleted.
- Events: `MissedRunDetected`, `MissedRunResolved`, `MissedRunIgnored`.

### 2.7 CleanupPolicy lifecycle
```
Created -> Enabled | Disabled ; Enabled <-> Disabled
(any edit) -> version++, logged via ConfigEdit Operation + audit
Created | Enabled | Disabled -> deleted_at set (soft)
```
- Same soft-delete/logging/versioning as Schedule; world tombstone soft-deletes world-scoped
  policies.
- Hard-guard invariants:
  - Age Rule floor: 3 days minimum — cannot be saved lower.
  - Count Rule floor: 3 per backup category (session/manual/pre_restore/emergency) and per
    stale-world scope.
  - Floors + the §2.5 retention-protection invariant are two views of one guarantee — a
    policy edit that strands a required artifact below its floor is rejected at save time.

### 2.8 Notification lifecycle
```
Created -> Read (per-user) | ActionTaken | Dismissed
```
- Never deletable through any UI path — only acknowledged, marked read, or addressed.
  `Dismissed` clears the active dropdown view; the row stays permanently queryable on the
  Audit/History page.
- `severity: [critical|high|normal|informational]` — drives dropdown prioritization
  (critical/high above normal/informational). Mapping: critical = world crashed,
  unauthorized attempt, critical low storage; high = backup/restore failed, sync failed
  (terminal); normal = missed job, sync retry, suspicious activity; informational =
  started/stopped, backup/cleanup succeeded.
- Per-user read state via `NotificationRead(notification_id, user_id, read_at)` join — never
  a boolean column; broadcast notifications are read independently by multiple users.

### 2.9 AuditRecord lifecycle
```
(action occurs) -> Created   [terminal — pure insert-only log]
```
Corrections/acknowledgements are new rows with `annotation_of` self-reference — never
updates to the original.

### 2.10 Manager lifecycle (singleton — exactly one row per deployment, hard invariant)
```
Uninitialized -> SetupInProgress -> Operational
Operational -> UpdateInProgress -> Operational
Operational -> RollbackInProgress -> Operational
```
- Owns deployed version/commit reference, setup-completion flag, composition of
  `global_settings`.
- Settings inheritance — exactly three tiers, the ONLY pattern for any world-specific
  setting: (1) Manager default = `global_settings` baseline; (2) World override = `world_id`-
  scoped row in the same table; (3) Effective value = "world override if one exists and is
  enabled, else Manager default" — never both, never neither-silently-picked.
- Exception: notification defaults (sound/message templates) are Manager-default-only — no
  per-world override.
- Future integration points (Discord/Prometheus/Grafana/Home Assistant/webhooks): follow the
  `SyncAdapter` port pattern — a small purpose-specific port (`NotificationAdapter`,
  `MetricsExportAdapter`, ...) configured with the same global-default-with-world-override
  shape. No new entities until a concrete requirement exists.
- Events: `ManagerSetupCompleted`, `ManagerUpdateStarted/Completed`, `ManagerRolledBack`,
  `ManagerRestarted`.

### 2.11 JavaRuntime lifecycle
```
Registered -> Verified (health check) ; Registered|Verified -> Missing (path gone at boot)
Verified -> Deprecated ; Deprecated -> deleted_at set (soft)
```
Never hard-deleted if any RuntimeSession's `launch_args_snapshot` references it (even
tombstoned worlds) — in practice it almost never leaves `Deprecated`.
Events: `JavaRuntimeRegistered/Verified/MarkedMissing/Deprecated`.

### 2.12 Template lifecycle
```
Created -> Updated (versioned) ; Created|Updated -> Deprecated -> deleted_at set (soft)
```
Same provenance rule as JavaRuntime: a Template referenced by any WorldInstance's creation
history is never hard-deleted, only deprecated. Template "delete" = this deprecation flow.
Events: `TemplateCreated/Updated/Deprecated/Deleted(soft)`.

### 2.13 Device lifecycle
```
Unrecognized -> Registered (admin approval) ; Registered -> Updated | Revoked
```
Never hard-deleted once any AuditRecord/ClientSession has snapshotted its `device_id`
(effectively always). Device "delete" = `Revoked`.
Events: `DeviceRegistered/Updated/Revoked` (`last_seen_at` is a field update, not an event).

### 2.14 ClientSession lifecycle
```
Created -> Active -> Expired (passive) | Revoked (logout/admin/password change)
Active -> StepUpConfirmed (temporary elevated state, reverts to Active)
```
- Step-up is session-scoped, time-bounded (default 10 min), enforced server-side on every
  elevated request; reverts on expiry, revocation, or context change. Password is never
  stored/cached/pre-filled — entered, verified, discarded.
- Invariant: Expired/Revoked session can never authorize any action — enforced server-side
  on every request.
- Revocation uses the shared `deleted_at` column; expiry is time-based (`expires_at`), no
  `deleted_at` needed.
- Session token stored hashed on the ClientSession row, NOT in `secrets` — short-lived and
  self-invalidating (deliberate scope boundary).
- Events: `ClientSessionCreated/Expired/Revoked/StepUpConfirmed`.

### 2.15 Role lifecycle
```
Created -> Updated (ConfigEdit + audit)
Created | Updated -> deleted_at set (soft; custom roles only, no current holders)
```
- Baseline roles (non-deletable, `is_system_role = true`): **Client** (base, read-only +
  any individually granted permissions), **Admin** (full world authority — start/stop/
  backup/restore/maintenance across all worlds — but no control-panel/user/role management,
  no manager settings/update/rollback), **Superadmin** (everything Admin has, plus
  control-panel authority: user accounts, role/permission assignment, manager-wide settings,
  update/rollback/restart).
- Custom roles: freely created/edited/soft-deleted, subject to no current holders.
- The trio can never be deleted, soft or hard — same non-bypassable guard category as the
  §4 superadmin floor.
- Events: `RoleCreated/Updated/Deleted(soft)`.

### 2.16 Permission & RoleAssignment lifecycle
```
Granted -> Revoked   (deleted_at set, ConfigEdit Operation + audit)
```
- Delegation invariant: only a **Superadmin** may create/revoke a `permissions` row for
  another User (how a Client gets cleanup/maintenance without full Admin promotion). Admin
  has full world authority but cannot grant permissions.
- Permission attaches to a Role (all holders) OR directly to a User (per-world override) —
  one mechanism, two attachment points.
- Revocation is soft (shared `deleted_at`); "who could do what, when" stays reconstructable.
  Physical removal only via Cleanup.
- Events: `PermissionGranted/Revoked`, `RoleAssignmentGranted/Revoked`.

### 2.17 SyncTarget lifecycle
```
Created -> Updated (ConfigEdit + audit)
Created | Updated -> deleted_at set (soft — Tier 2)
```
- One configured offsite destination: `type [nas|google_drive|other]`, non-secret config,
  credential ref in `secrets`, scope `[global|world]` — same global-default-with-per-world-
  override shape as Schedule/CleanupPolicy.
- Invariant: exactly one resolvable SyncTarget per world at sync time (world override if
  present+enabled, else global default, else none = nothing to do, not an error).
- Events: `SyncTargetCreated/Updated/Deleted(soft)`.

### 2.17.1 SyncRecord lifecycle (job wrapper over immutable SyncAttempt rows)
```
(Sync dispatched) -> Created, status = pending -> succeeded | failed
```
- One sync job (one artifact, one target, one Operation). Never deleted (Tier 1). `status`
  is derived from the most recent SyncAttempt — never set independently; only moves forward.
- Fields: `sync_id`, `artifact_id [FK RESTRICT]`, `sync_target_id [FK RESTRICT]`,
  `operation_id [FK RESTRICT]`, `status`, `started_at`, `finished_at`, `created_at`.
- Events: `SyncJobStarted/Succeeded/Failed`.

### 2.17.2 SyncAttempt lifecycle (the actual retry history)
```
(SyncService makes one transfer attempt) -> Created   [immutable — never updated, never deleted]
```
- One row per attempt, always (successful first try = one row; 2 failures + success = three).
- Fields: `attempt_id`, `sync_id [FK RESTRICT]`, `attempt_number [UNIQUE(sync_id,
  attempt_number), strictly sequential from 1, no gaps]`, `started_at`, `finished_at`,
  `outcome [succeeded|failed_transient|failed_permanent]`, `error_message NULL`, `created_at`.
- `failed_transient` = retryable (network); `failed_permanent` = not (rejected credentials
  etc.), SyncRecord → `failed` immediately.
- Events: `SyncAttemptSucceeded/FailedTransient/FailedPermanent`.

### 2.18 Notification events
`NotificationCreated`, `NotificationRead` (per user), `NotificationActionTaken`,
`NotificationDismissed`.

### 2.19 AuditRecord events
`AuditRecordCreated` only — no update/delete event by design.

## 3. Domain Events (full event catalog)

- User: `UserCreated`, `UserRoleChanged`, `UserPermissionGranted/Revoked`,
  `UserDisabled/Enabled/Locked/Unlocked`, `UserPasswordChanged`, `UserDeleted`. Privilege
  changes MUST produce an AuditRecord — hard requirement.
- RuntimeSession: `RuntimeSessionStarted`, `RuntimeSessionEnded` (carries `end_reason`),
  `RuntimeSessionReconciled` (fired only when restart forces a stale session closed).
- WorldInstance: `WorldCreated/Queued/Starting/Started/StartFailed/Stopping/Stopped/Crashed/
  BackingUp/BackupSucceeded (returns to resume_state)/BackupFailed/Restoring/
  RestoreSucceeded/RestoreFailed/ErrorAcknowledged/CrashAcknowledged/Deleted(tombstoned)`.
- Operation: `OperationCreated/Queued/ValidationFailed/Started/Progress (checkpoint payload)/
  Completed/Failed/Cancelled/TimedOut`.
- BackupArtifact: `BackupArtifactCreated`, `BackupArtifactDeleted` (carries
  `deleted_by_operation_id`).
- Schedule: `ScheduleCreated/Updated (carries new version)/Enabled/Disabled/Deleted(soft)/
  RunDue/RunMissed (creates MissedRunRecord)`.
- MissedRunRecord: `MissedRunDetected/Resolved/Ignored`.
- CleanupPolicy: `CleanupPolicyCreated/Updated/Enabled/Disabled/Deleted(soft)/RunExecuted
  (dry|wet)/RunSummaryRecorded/HardDeletePerformed` — the last fires once per row physically
  deleted (12 rows = 12 fires), per-row audit precision.
- SyncTarget: `SyncTargetCreated/Updated/Deleted(soft)`. SyncRecord:
  `SyncJobStarted/Succeeded/Failed`. SyncAttempt: `SyncAttemptSucceeded/FailedTransient/
  FailedPermanent`.
- Notification: `NotificationCreated/Read/ActionTaken/Dismissed`. AuditRecord:
  `AuditRecordCreated` only.

## 4. Business Invariants

User
- `username` unique among non-deleted users.
- Password `SecretRef` never null for an `active` User.
- At least one `active` Superadmin always exists — disabling/deleting/demoting the last one
  is rejected outright (non-bypassable).
- A User can never authorize their own step-up-protected action with standing session alone
  — password re-entry required regardless of identity.
- Every User-action AuditRecord carries a device identity snapshot captured at action time
  (never reconstructed by joining the current Device table).

RuntimeSession
- Exactly one open session per WorldInstance (schema-enforced).
- `rcon_secret_ref` points to a credential generated for that specific session — never
  reused from a prior session.
- `ended_at` set once; `end_reason` immutable after being set.

WorldInstance
- Every transition is driven by an Operation (crash handled via `CrashDetected` system
  Operation — no carve-out).
- `pre_backup_state` must be set when entering `backing_up` and resolve to a valid prior
  state (`off`|`running`) on completion.
- `error`/`crashed` require explicit acknowledgement before returning to `off`; no code
  path silently clears either.
- `restoring` entered only from `off`; a restore attempt while running is rejected before
  an Operation is created.
- The world lock is derived, not stored: a world is "locked" exactly while an in-flight
  (non-terminal) Operation targets it — query `world_id = ? AND status IN
  ('Created','Queued','Validating','Running')`. No lock column exists on `world_instances`.
- Runtime configuration change rule: `java_runtime_id`, `launch_args`, `port` editable only
  while `state = off` — rejected otherwise. The write is immediate (column update); the
  *effect* is deferred to next boot by construction — an already-running process only reads
  config at boot (captured in its `launch_args_snapshot`).
- Template independence: `template_id` is provenance only. All runtime configuration is
  copied into the WorldInstance row at CreateWorld and is the sole source of truth from then
  on; editing/deprecating a Template never mutates an existing WorldInstance.
- RenameWorld (editing `display_name` only) is a lightweight ConfigEdit-type Operation —
  touches no files/process, allowed concurrently with Backup/Restore/Cleanup.

Operation
- A Failed/TimedOut Operation is never rewritten to Completed, and vice versa — one-
  directional progression.
- Any compensating action is a new Operation referencing the original by ID.
- Every user-triggered WorldInstance transition has exactly one driving Operation.
- Full mutual-exclusion rules for every Operation type are defined in Document 11, which
  supersedes any conflict-rule text elsewhere where they differ.

Global Deletion
- No service, route, or command handler other than `CleanupService` ever executes a physical
  `DELETE FROM` (enforced at the architecture layer).
- Tier 1 entities are excluded from Cleanup's sweep entirely — never candidates for physical
  deletion, by anyone, ever.
- Every Tier 2 soft-delete/revoke produces a `ConfigEdit` Operation + AuditRecord.

MissedRunRecord
- `resolution` starts `pending`, transitions to exactly one of `resolved`/`ignored`,
  terminal.
- Snapshot fields are write-once, fixed to the moment of detection.

SyncTarget / SyncRecord / SyncAttempt
- Exactly one SyncTarget resolves per world at sync time — never zero-or-ambiguous, never
  two targets silently picked between.
- SyncRecord `status` only moves `pending -> succeeded|failed`, always derived from its
  SyncAttempt rows.
- SyncAttempt rows are immutable; `attempt_number` strictly sequential with no gaps.
- Sync failure never mutates `backup_artifacts` — local backup validity is independent of
  offsite mirroring.

## 5. Value Objects

All closed sets here are normative for the schema (Doc 7), the API (Document 12), and tests
(Document 13). Additions are possible only through an ARCHITECTURE.md §14 conflict-log entry.
Where a value object is "string-typed by design" it is still a documented closed set —
never free text.

- `Username` — 3–32 chars, `[A-Za-z0-9._-]`, must not start with `.` or `-`.
- `SecretRef` — opaque pointer into `secrets`; never carries the secret value outside the
  security subsystem.
- `WorldId` — immutable application-generated TEXT id (UUIDv4 or similar), never reused.
- `OperationType` — `CreateWorld | Start | Stop | Kill | Backup | Restore | Cleanup | Sync |
  ConfigEdit | CrashDetected | DeleteWorld`.
- `WorldState` — `off | queued | starting | running | stopping | restoring | backing_up |
  crashed | error`. One open value: `pre_backup_state` is a `WorldState | None` restricted
  to `{off, running}` while set.
- `OperationStatus` — `Created | Queued | Validating | Running | Completed | Failed |
  Cancelled | TimedOut`.
- `EndReason` — `graceful_stop | forced_stop | crashed | emergency_stop |
  reconciled_missing`.
- `TriggerType` — backup trigger classification/naming: `session_end | manual | scheduled |
  pre_restore | emergency | manager_config`. Identical to BackupArtifact's `category`; one
  enum, two column names (`trigger_type` in naming/metadata, `category` in Doc 7).
- `NotificationSeverity` — `critical | high | normal | informational`. Drives dropdown
  ordering, never free text.
- `SyncOutcome` — `succeeded | failed_transient | failed_permanent`.
  `failed_transient` = retryable; `failed_permanent` = terminal for that job.
- `SyncRecordStatus` — `pending | succeeded | failed`; derived from the latest SyncAttempt,
  never set independently.
- `MissedRunResolution` — `pending | resolved | ignored`, terminal once set.
- `ScheduleType` — `backup | cleanup | maintenance`.
- `ScheduleScope` / `PolicyScope` / `SyncTargetScope` — one shared enum `scope`:
  `global | world`.
- `CleanupPolicySpaceRule` — nullable `space_rule_pct`; constrained 0 < pct ≤ 90 when set.
- `BackupCategory` — alias of `TriggerType`; normative name for Doc 7
  `backup_artifacts.category`; API distinguishes `trigger` (cause) from `category`
  (classification) only in payload naming, never in allowed values.
- `UserStatus` — `active | disabled | locked` (storage; `deleted`/soft is the `deleted_at`
  marker, not a status value).
- `JavaRuntimeStatus` — `registered | verified | missing | deprecated`.
- `DeviceStatus` — `unrecognized | registered` (revoked = `deleted_at` marker).
- `ActorType` — `user | system`.
- `ConfigEditEntity` — identifies which versioned entity a ConfigEdit targets
  (ARCHITECTURE.md §5 list): `schedules | cleanup_policies | global_settings |
  world_settings | templates | roles | sync_targets | world_instances(metadata) |
  server_properties | java_runtimes | users | devices`. String-typed-by-design closed set.
- String-typed-by-design closed sets (validated in code): `server_type` (Template/
  WorldInstance — free-text category, must match an existing Template's category or
  built-in curated set); `addressing_strategy` (`subdomain | port | path`);
  `sync_target_type` (`nas | google_drive | other`); `notification_defaults` keys.
- `AddressingStrategy` — `subdomain | port | path`. One per world, not free text.
- `SyncTargetType` — `nas | google_drive | other` (`other` deliberately open-ended but a
  registered value, never raw text).

Versioning note: several enums already appear as schema column comments in Doc 7. The closed
sets above are the single source of truth; Doc 7's inline comments reference them by this
section rather than restating (named rules applied, not duplicated).

## 6. Aggregate Roots

- Roots: Manager (singleton), WorldInstance, Template, Device, User, Role.
- Everything else is a child/referenced entity inside one of those roots, never
  independently addressable: RuntimeSession, BackupArtifact, Operation, Schedule,
  CleanupPolicy, MissedRunRecord, Notification, NotificationRead, AuditRecord, Permission,
  ClientSession, JavaRuntime, SyncTarget, SyncRecord, SyncAttempt.

Ownership rules
- Manager owns: world registry, global settings, and (as defaults) Schedules/
  CleanupPolicies/SyncTargets not overridden per-world.
- WorldInstance owns: its RuntimeSessions, BackupArtifacts, world-scoped Operations, and its
  own Schedule/CleanupPolicy/SyncTarget overrides. Tombstoned, never hard-deleted — too much
  history hangs off its immutable ID.
- RuntimeSession is owned exclusively by one WorldInstance.
- User owns: its RoleAssignments, direct Permission grants; referenced as actor on its own
  Operations/AuditRecords/ClientSessions — but does not own those rows in the deletion sense
  (soft-deleted User leaves all historical references intact).
- Device is referenced by (never owns) ClientSessions and AuditRecords; reference survives
  revocation.
- Template/JavaRuntime are referenced by WorldInstance creation history / RuntimeSession
  launch snapshots, but own neither.
- Schedule/CleanupPolicy/SyncTarget are owned by either Manager (global) or one WorldInstance
  (override) — never both; resolution belongs to ConfigurationService.
- SyncRecord is owned by the BackupArtifact it mirrors (via its Sync Operation), not by
  SyncTarget. SyncAttempt is owned exclusively by its SyncRecord.
- General rule (authoritative): nothing is ever hard-deleted by a normal user-facing action.
  Tier 1 (AuditRecord, Notification, NotificationRead, MissedRunRecord, SyncRecord,
  SyncAttempt) is permanent and untouched even by Cleanup. Everything else that can be
  "deleted" or "revoked" — WorldInstance, Device, JavaRuntime, Template, User, BackupArtifact,
  Schedule, CleanupPolicy, Role, Permission, RoleAssignment, ClientSession, SyncTarget — is
  soft-marked with one shared `deleted_at` column, change logged, and the only physical
  delete anywhere in the system is the Cleanup subsystem.

Global Deletion & Retention Model (applies to every entity; classify any new entity here)

- Tier 1 — Permanent, never deleted by anything, ever: AuditRecord, Notification,
  NotificationRead, MissedRunRecord, SyncRecord, SyncAttempt.
- Tier 2 — Soft-deleted/revoked immediately by normal operations, physically removed only by
  Cleanup, if ever: WorldInstance, Device, JavaRuntime, Template, User, BackupArtifact
  (metadata row), Schedule, CleanupPolicy, Role (custom only), Permission grants,
  RoleAssignments, ClientSession, SyncTarget.
- There is no tier 3. No entity has a user-facing "delete" that physically removes a row
  directly.
- Column convention: one shared `deleted_at` timestamp for every Tier 2 soft-removal
  (conceptually "delete" or "revoke"), plus optional `deleted_by` actor. No `revoked_at`
  split.
- Hard-delete rule: only `CleanupService` (via a Cleanup Operation) ever issues a physical
  `DELETE FROM`. Cleanup sweeps expired artifacts and stale world data, and generalizes to
  aged-out already-soft-deleted Tier 2 config rows past their retention window once nothing
  depends on them. WorldInstance/Device/JavaRuntime/Template/User are Tier 2 in principle but
  rarely swept in practice (Tier 1 rows almost always still reference them) — "eligible for
  Cleanup" does not mean "will be swept."
