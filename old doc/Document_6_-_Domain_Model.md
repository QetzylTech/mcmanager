# Document 6: Domain Model

Purpose
- Define the entities, lifecycles, invariants, domain events, and ownership rules for the manager.
- Canonical terminology source: **§3.1 Domain Glossary**. Other documents reference this glossary instead of redefining terms.
- Downstream: Document 7 (schema), Document 8 (services), Document 11 (concurrency).

Decisions on record
- **User** = individually named accounts (own username + password each), not shared per-role credentials. Supersedes the legacy shared admin/superadmin password model.
- Roles are **Client / Admin / Superadmin** (Doc 2 §8.1's tentative naming superseded).

§0. Common Entity Conventions (apply to every entity unless stated otherwise)

Three lifecycle shapes cover every entity:

1. **State-machine entity** — multiple meaningful runtime states with explicit transitions: User, RuntimeSession, WorldInstance, Operation, ClientSession. Transitions specified per entity in §2; domain events fire per transition; terminal states never reopen.
2. **Config entity** — created → edited → soft-deleted. Every edit and every soft-delete increments `version`, records `last_changed_by`/`last_changed_at`, and produces a `ConfigEdit` Operation + AuditRecord. Edits use optimistic concurrency: a write against a stale `version` is rejected with a conflict error (Document 11 §4 is the authoritative table of `version` tables). "Delete" sets the shared `deleted_at`; physical removal, if ever, is the Cleanup subsystem's job alone (Global Deletion & Retention Model). Schedule, CleanupPolicy, Role (custom), Permission, RoleAssignment, SyncTarget, Template, JavaRuntime, Device, User follow this shape.
3. **Permanent record** — created once; never deleted, soft or hard, by anything — including Cleanup. Mutable fields (read state, resolution) transition per the entity's lifecycle and are never erased. AuditRecord, Notification, NotificationRead, MissedRunRecord, SyncRecord, SyncAttempt fit this shape.

Shared column naming
- `deleted_at` — the single timestamp column for every soft-removal, whether the domain language says "deleted" (WorldInstance, Device, JavaRuntime, Template, User, BackupArtifact, Schedule, CleanupPolicy, Role) or "revoked" (Permission, RoleAssignment, ClientSession). Optionally `deleted_by` (actor).
- `version` — optimistic-concurrency counter on every multi-admin-editable config entity.
- `created_at` / `updated_at` / `created_by` / `last_changed_by` / `last_changed_at` — used as per-entity relevance dictates.
- Write-time snapshots — any permanent record that must outlive the rows it references stores a denormalized snapshot of identifying fields at write time (e.g. `audit_records.device_id_snapshot`, `missed_run_records.schedule_name_snapshot`, `runtime_sessions.launch_args_snapshot`) instead of relying on a live join.

Global Deletion & Retention Model — the authoritative statement, referenced everywhere
- **Tier 1 — Permanent, never deleted by anything, ever:** AuditRecord, Notification, NotificationRead, MissedRunRecord, SyncRecord, SyncAttempt. These are the record of what happened; deleting them would falsify history.
- **Tier 2 — Soft-deleted/revoked immediately by normal operations, physically removed only by Cleanup, if ever:** WorldInstance, Device, JavaRuntime, Template, User, BackupArtifact (metadata row), Schedule, CleanupPolicy, Role (custom), Permission, RoleAssignment, ClientSession, SyncTarget. Every "delete"/"revoke" is a `deleted_at` update plus a logged change (`ConfigEdit` Operation + AuditRecord) — never an immediate `DELETE FROM`.
- **There is no tier 3.** No entity has a user-facing delete that physically removes a row directly.
- **Hard-delete rule:** the only part of the system that ever issues a physical `DELETE FROM` is the Cleanup subsystem (via a Cleanup Operation). In practice Cleanup's sweep covers aged-out, already-soft-deleted Tier 2 config rows past retention; WorldInstance, Device, JavaRuntime, Template, User are Tier 2 in principle but rarely reach physical deletion because Tier 1 records almost always still reference them — "eligible for Cleanup" ≠ "will be swept." Tier 1 table *shape* changes happen via additive migrations (Doc 7 §5), never drop-and-recreate.

1. Core Entities

1.1 User (aggregate root)
- Identity: `user_id` (immutable, machine-readable, never reused even after deletion); `username` (unique among non-deleted users; editable by admin/superadmin or self, subject to step-up; not a foreign key); `display_name` (optional, cosmetic).
- Credentials: password hash is not on the User row — it lives in `secrets` (Doc 10 §2.2, Doc 7 §2.24); the User holds a `secret_id` reference.
- Status: `active` | `disabled` | `locked` | `deleted` (soft). `failed_login_count`, `locked_until` support password-retry throttling (Doc 2 §8.4, Doc 1 §12).
- Relationships: many RoleAssignments; many direct Permission grants (per-world overrides per Doc 2 §8.1); actor on many Operations and AuditRecords; many ClientSessions (a session binds a User to a token, a Device as trust context, and an IP — identity and trust context stay separate, Doc 2 §8.2); `created_by` self-reference to the provisioning account.
- Audit capture: every login attempt (success/failure) and every AuditRecord from a User action snapshots both `user_id` and `device_id` (+ device name/IP) at write time — never joined live later, since Device rows can be renamed/reassigned/deleted. Named accounts add "who" without dropping legacy device/IP attribution ("from what").
- Not modeled: multiple humans sharing one User row. Same privilege level for two people = two User rows with the same Role.

1.2 RuntimeSession
- One continuous execution of a WorldInstance, from confirmed startup to confirmed stop.
- Durable columns: `session_id` (PK), `world_id` (FK), `started_at` (confirmed-running transition, not button-press), `ended_at` (nullable while open), `end_reason` (`graceful_stop` | `forced_stop` | `crashed` | `emergency_stop` | `reconciled_missing`), `rcon_secret_ref` (reference into `secrets`, never raw), `port_used`, `java_runtime_id`, `launch_args_snapshot` (captured at launch; independent of later config edits).
- Explicitly NOT persisted here (runtime-registry concerns, reconstructed at boot per Doc 3 §7.4): process PID/handle, live health-check results.
- Relationships: belongs to exactly one WorldInstance; at most one open (unended) session per world — partial unique index on `world_id WHERE ended_at IS NULL`.

2. State Machines (lifecycles)

2.1 User
```
Provisioned -> Active
Active -> Disabled (admin) | Locked (N consecutive failed logins) | Deleted (soft)
Disabled -> Active (admin re-enable)
Locked -> Active (cooldown elapses OR admin unlock)
```
- `Deleted` is terminal through normal flows (a new account gets a new `user_id`; a deleted account isn't reactivated — keeps historical actor references unambiguous). Hard delete never allowed while any Operation/AuditRecord/Notification references the `user_id` — in practice always.
- Events: `UserCreated`, `UserRoleChanged`, `UserPermissionGranted`, `UserPermissionRevoked`, `UserDisabled`, `UserEnabled`, `UserLocked`, `UserUnlocked`, `UserPasswordChanged`, `UserDeleted`. Role/permission changes must always produce an AuditRecord (Doc 2 §9.2).

2.2 RuntimeSession
```
(WorldInstance reaches confirmed running) -> Open
Open -> Closed[graceful_stop] | Closed[forced_stop] | Closed[crashed] | Closed[emergency_stop] | Closed[reconciled_missing]
```
- Created only when the runtime state resolver (Doc 3 §7.1) confirms `running` — never at `queued`/`starting` — so failed/aborted starts don't count as sessions.
- On manager restart (Doc 3 §7.4): an `Open` session matched against a discovered live process → stays open; no match → force-closed with `end_reason = reconciled_missing`. No session may remain `Open` after a reconciliation pass. Formalizes the failure class the legacy `operation_reconciler` patched over (legacyImplementation.txt §10) into a testable invariant.
- Events: `RuntimeSessionStarted`, `RuntimeSessionEnded` (carries `end_reason`), `RuntimeSessionReconciled` (restart-inferred close — distinct from normal end).

2.3 WorldInstance (aggregate root; Tombstoned/Tier 2)
```
(does not exist) -> off           (CreateWorld Operation completes)
off -> queued                      (Start Operation created)
queued -> starting                 (scheduler dispatches, launch attempted)
starting -> running                (readiness confirmed — a RuntimeSession opens, §2.2)
starting -> error                  (process exits/times out before readiness)
running -> stopping                (Stop Operation: operator, idle auto-stop, or emergency)
running -> crashed                 (process exits unexpectedly, no Stop in flight)
running | off -> backing_up        (Backup Operation created)
off -> restoring                   (Restore Operation created — restore is off-only, Doc 1 §3)
stopping -> off                    (shutdown confirmed)
backing_up -> <resume_state>       (backup completes)
backing_up -> error                (backup fails)
restoring -> off                   (restore completes — success or safely-reverted failure, Doc 1 §3)
restoring -> error                 (restore fails unsafely, cannot auto-revert)
error | crashed -> off             (explicit operator acknowledgement — never auto-clears)
off -> tombstoned                  (DeleteWorld Operation completes)
```
- `backing_up` reachable from both `off` and `running`; the prior state is persisted in `pre_backup_state` and returned to on success — never unconditionally to `off`.
- `DeleteWorld` invariant: only reachable from `off`; rejects (not queues) otherwise. Tombstoning sets `deleted_at`/`deleted_by_operation_id` and removes files from disk as part of the Operation; the row and immutable `world_id` persist forever — otherwise "World IDs are immutable" breaks on first deletion. It is a `DeleteWorld` Operation, never a raw registry write.
- `CreateWorld`/`DeleteWorld` are first-class Operation types (Doc 8 §2), structurally heavier than `ConfigEdit` (provisioning/tombstone with wide historical fan-out).
- Runtime config change rule: `java_runtime_id`, `launch_args`, `port` editable only while `state = off` — any other state rejects at precondition, before a `ConfigEdit` Operation is created. Write immediate (column update); effect deferred to next boot by construction, since a running process only reads config at launch (its own `launch_args_snapshot`). Full treatment: Document 11 §5.
- Template independence: `template_id` is provenance/history only. Runtime config is copied into the world's own row at `CreateWorld`; editing/deprecating a Template never mutates an existing world.
- `RenameWorld` (display_name only) is a lightweight `ConfigEdit`-type Operation touching no files/process; allowed concurrently with Backup/Restore/Cleanup (Document 11 §3.1).
- Events: `WorldCreated`, `WorldQueued`, `WorldStarting`, `WorldStarted`, `WorldStartFailed`, `WorldStopping`, `WorldStopped`, `WorldCrashed`, `WorldBackingUp`, `WorldBackupSucceeded`, `WorldBackupFailed`, `WorldRestoring`, `WorldRestoreSucceeded`, `WorldRestoreFailed`, `WorldErrorAcknowledged`, `WorldCrashAcknowledged`, `WorldDeleted` (tombstoned).

2.4 Operation
```
Created -> Queued -> Validating -> Running -> Completed | Failed | TimedOut
Queued | Validating -> Cancelled   (only for cancellable types, Doc 8 §6)
```
- `Completed`, `Failed`, `Cancelled`, `TimedOut` are terminal. Operations are immutable except status progression; no terminal Operation is reopened.
- Compensating actions (e.g. auto-revert of a failed restore) are recorded as **new** Operations referencing the failed Operation's `id` (`compensates_operation_id`) — never a mutation of the original's outcome.
- Every user-triggered WorldInstance transition has exactly one driving Operation. Crash detection is observation-driven, so it gets its own system-actor Operation type `CrashDetected` (actor = `system`) — closing the gap where crash transitions would otherwise lack durable, auditable treatment (Doc 2 §9.2, Doc 3 §4.4).
- `world_instances.current_operation_id` is set when an Operation drives a transition and cleared the moment it reaches any terminal status — never left pointing at a finished Operation (Doc 8 OperationService).
- Events: `OperationCreated`, `OperationQueued`, `OperationValidationFailed`, `OperationStarted`, `OperationProgress`, `OperationCompleted`, `OperationFailed`, `OperationCancelled`, `OperationTimedOut`.
- Full mutual exclusion for every Operation type — Document 11 is authoritative where any conflict-rule text differs.

2.5 BackupArtifact (Tier 2, created-on-success-only)
```
(backup job succeeds) -> Created   [immutable from this point on]
Created -> Deleted   (soft)
```
- A row is created only on a *successful* capture; a failed attempt produces a Failed Operation but no artifact row — no `pending`/`failed` artifact state.
- Deletion is soft: `deleted_at`/`deleted_by_operation_id` set, file removed from disk, row retained so history stays queryable.
- Retention protection: for each backup category, artifacts satisfying the configured "keep newest N" floor — and always the single most recent artifact of a required category — can never be deleted by an ordinary dry/wet cleanup run. Only an explicit superadmin force-flow bypasses this, with elevated confirmation and immutable logging (Doc 2 §8.4).
- **ManagerBackup**: `world_id` nullable; `NULL` = backup of the manager's own state (SQLite DB, global settings, templates, role/permission assignments — everything except world content), distinguished by `category = 'manager_config'`. Reuses the existing Backup Operation type and the `operations.world_id NULL` manager-global pattern; no new entity.
- **Backup lineage**: Backup → Restore → Backup → Sync already traceable through existing FKs (`restore_history.source_artifact_id` → Backup A, `restore_history.pre_restore_artifact_id` → Backup B, `sync_records.artifact_id` → Backup B). Lineage is a two-hop join, not a graph traversal; no edge/graph table unless a future requirement needs deeper-than-two-hop chaining.
- Events: `BackupArtifactCreated`, `BackupArtifactDeleted`.

2.6 Schedule (config entity, Tier 2)
- Lifecycle: `Created -> Enabled | Disabled`; `Enabled <-> Disabled`; edits increment `version` and log a `ConfigEdit` Operation + AuditRecord (carries forward the legacy `rule_version`/`schedule_version` pattern — Doc 1 §4 "who changed this rule last"); "delete" sets `deleted_at` and stops it firing (row + edit history remain queryable); world tombstone soft-deletes its world-scoped Schedules (never hard-cascade).
- `version` is optimistic concurrency control, not just a display counter (Document 11 §4).
- Events: `ScheduleCreated`, `ScheduleUpdated`, `ScheduleEnabled`, `ScheduleDisabled`, `ScheduleDeleted` (soft), `ScheduleRunDue`, `ScheduleRunMissed` (creates a MissedRunRecord).

2.6.1 MissedRunRecord (Tier 1 — permanent, never deleted)
```
(scheduled run doesn't fire on time) -> Created, resolution = pending
pending -> resolved   (operator ran the missed job or addressed it)
pending -> ignored    (operator dismissed without running)
```
- Never deleted, soft or hard, by anything — same permanent tier as AuditRecord/Notification (Doc 1 §13, Doc 3 §5.7: missed runs recorded and surfaced, never silently caught up).
- Fields: `schedule_id`, `expected_run_at`, `detected_at`, `resolution` (`pending`/`resolved`/`ignored`), `resolution_at/by`; plus a snapshot of the Schedule's name/type at detection time so the record stays meaningful if the parent Schedule is edited or soft-deleted.
- Invariants: `resolution` goes `pending` → exactly one of `resolved`/`ignored`, never back; snapshot fields set once, never updated.
- Events: `MissedRunDetected`, `MissedRunResolved`, `MissedRunIgnored`.

2.7 CleanupPolicy (config entity, Tier 2)
- Same treatment as Schedule: soft-delete via `deleted_at`, every edit/deletion logged (`ConfigEdit` + AuditRecord), world-tombstone triggers soft-delete not hard-cascade, `version` = optimistic concurrency.
- Hard-guard invariants (formalizing Doc 1 §4 prose): Age Rule minimum floor 3 days; Count Rule minimum floor 3 per backup category (session/manual/pre-restore/emergency) and per stale-world scope; these floors and the §2.5 retention protection are two views of one guarantee and must never drift apart — a policy edit that strands a required artifact below its floor is rejected at save time.
- Events: `CleanupPolicyCreated`, `CleanupPolicyUpdated`, `CleanupPolicyEnabled`, `CleanupPolicyDisabled`, `CleanupPolicyDeleted` (soft), `CleanupRunExecuted` (dry/wet), `CleanupRunSummaryRecorded`, `CleanupHardDeletePerformed` (fires once per row physically deleted — the only event corresponding to a real `DELETE FROM` anywhere).

2.8 Notification (Tier 1 — permanent, per-user read state)
```
Created -> (per-user) Read
Created -> ActionTaken   (for response-requiring prompts)
Created -> Dismissed     (cleared from active dropdown view — not a delete)
```
- Never physically deleted through any UI path — only acknowledged, marked read, or marked addressed. `Dismissed` clears the active dropdown view (Doc 5); the row stays permanently queryable in Audit/History.
- Severity: `critical` / `high` / `normal` / `informational`. Suggested trigger mapping (Doc 8 §9): critical = crash, unauthorized attempt, critical low storage; high = backup/restore failed, sync failed terminal; normal = missed job, sync retry, suspicious activity; informational = started/stopped, backup/cleanup succeeded.
- Read state is per-user (individual-account model) via `NotificationRead` join (`notification_id`, `user_id`, `read_at`, `dismissed_at`) — a broadcast notification can be read independently by multiple users; `dismissed_at` hides it from that user's dropdown only.
- Events: `NotificationCreated`, `NotificationRead`, `NotificationActionTaken`, `NotificationDismissed`.

2.9 AuditRecord (Tier 1 — append-only)
```
(action occurs) -> Created   [terminal — no further states]
```
- Pure insert-only log. Corrections/acknowledgements are new rows with an optional `annotation_of` self-reference to the corrected record — never an update to the original (Doc 6 original invariant: "Audit records are append-only", made schema-level).
- Event: `AuditRecordCreated` only — by design, no update/delete event exists.

**Global Deletion & Retention Model** — authoritative statement in §0. Key follow-ons:
- Cleanup's existing job (Doc 1 §4, Doc 2 §4.5) sweeps expired BackupArtifacts and stale worlds past retention; scope generalizes to aged-out, already-soft-deleted Tier 2 config rows (Schedule, CleanupPolicy, Role, Permission, RoleAssignment) once nothing depends on them.
- No route, command handler, or service other than CleanupService ever hard-deletes a row (enforced at the architecture layer, Doc 3 §4.1).
- Every Tier 2 soft-delete/revoke produces a `ConfigEdit` Operation + AuditRecord.
- New entities added to Doc 6 in future must be classified into Tier 1 or Tier 2 against §0 — never ad hoc.

2.10 Manager (singleton aggregate root; Tier 2 in principle)
```
Uninitialized -> SetupInProgress -> Operational
Operational -> UpdateInProgress -> Operational
Operational -> RollbackInProgress -> Operational
```
- Exactly one Manager configuration row per deployment — a hard invariant, not a convention.
- Owns: deployed version/commit reference (Doc 1 §17 update/rollback), setup-completion flag, and the composition of global settings (Doc 7 `global_settings`).
- **Three-tier settings inheritance** (the only pattern for any world-overridable setting — backup Schedules, CleanupPolicies, SyncTargets, idle-countdown timing): (1) Manager default — `global_settings` baseline row; (2) World override — `world_id`-scoped row in the same table (`world_settings.idle_countdown_override` added to close the one setting that lacked it); (3) Effective value — resolved at read/evaluation as "world override if one exists and is enabled, else Manager default." No setting gets a bespoke inheritance rule.
- Notification defaults (sound/message templates) are Manager-default-only by deliberate exclusion — no per-world override — revisit only if a concrete need appears.
- Future integration point: the `SyncAdapter` port pattern (Doc 3 §3.1/§5.14, Doc 8 SyncService) is the template for future outbound integrations — Discord, Prometheus/Grafana, Home Assistant, webhooks — each a new adapter behind a small purpose-specific port, configured with the same global-default-with-world-override shape as SyncTarget. Architectural note only; no new entities now.
- Events: `ManagerSetupCompleted`, `ManagerUpdateStarted`, `ManagerUpdateCompleted`, `ManagerRolledBack`, `ManagerRestarted`.

2.11 JavaRuntime (config entity, Tier 2)
```
Registered -> Verified (health check)
Registered | Verified -> Missing (path unresolvable at boot)
Verified -> Deprecated (superseded, kept historically)
Deprecated -> deleted_at set (soft)
```
- Never hard-deleted if any RuntimeSession's `launch_args_snapshot` references it — even for tombstoned worlds. In practice it rarely leaves `Deprecated`.
- Events: `JavaRuntimeRegistered`, `JavaRuntimeVerified`, `JavaRuntimeMarkedMissing`, `JavaRuntimeDeprecated`.

2.12 Template (config entity, Tier 2)
```
Created -> Updated (versioned)
Created | Updated -> Deprecated
Deprecated -> deleted_at set (soft)
```
- Never hard-deleted if referenced by any WorldInstance's creation history (even tombstoned). Doc 5's template-management "delete" means this deprecation flow.
- Events: `TemplateCreated`, `TemplateUpdated`, `TemplateDeprecated`, `TemplateDeleted` (soft).

2.13 Device (config entity/Tier 2)
```
Unrecognized (seen, not registered) -> Registered (admin approval)
Registered -> Updated
Registered -> Revoked
```
- Never hard-deleted once any AuditRecord or ClientSession snapshotted its `device_id` (effectively always). Doc 2 §17's device "delete" UI means `Revoked`.
- `last_seen_at` is a field update, not a domain event (every heartbeat as an event would flood the audit trail).
- Events: `DeviceRegistered`, `DeviceUpdated`, `DeviceRevoked`.

2.14 ClientSession (state-machine entity, Tier 2)
```
Created -> Active
Active -> Expired (passive, time-based)
Active -> Revoked (logout, admin action, or password change)
Active -> StepUpConfirmed (temporary elevated state for one sensitive action, then reverts to Active)
```
- Expired/Revoked sessions can never authorize any action — enforced server-side on every request, never client-side (Doc 3 §8.2).
- Revocation uses the shared `deleted_at`; expiry is time-based (`expires_at` passed), no marker needed.
- The session token is stored (hashed) on the ClientSession row, not in `secrets` — short-lived, self-invalidating, so it doesn't need long-term secret treatment (deliberate scope boundary vs. Doc 10 §2.2 artifacts).
- Events: `ClientSessionCreated`, `ClientSessionExpired`, `ClientSessionRevoked`, `ClientSessionStepUpConfirmed`.

2.15 Role (config entity; custom roles Tier 2)
```
Created -> Updated (ConfigEdit + AuditRecord logged)
Created | Updated -> deleted_at set (soft; custom roles only, no current holders)
```
- Baseline roles per product decision: **Client**, **Admin**, **Superadmin** (supersedes Doc 2 §8.1's tentative naming).
  - **Client** — base authenticated-user role: read-only by default plus whatever `permissions` (§2.16) a Superadmin has individually granted. Default for a home server's non-owner users.
  - **Admin** — complete world-operation authority (start/stop/backup/restore/maintenance across all worlds), but not control-panel application authority (no user/role/permission management, no manager-level settings, no update/rollback).
  - **Superadmin** — everything Admin has, plus control-panel authority: user accounts, role/permission assignment (including granting individual `permissions` to Client/Admin accounts), manager-wide settings, update/rollback/restart.
- Invariants: the three baseline roles are `is_system_role`, never deletable (soft or hard); with the superadmin-floor invariant (§4), the privilege model can't be dismantled from inside the UI. Custom roles may be created/edited/soft-deleted subject to having no current holders.
- Events: `RoleCreated`, `RoleUpdated`, `RoleDeleted` (soft).

2.16 Permission & RoleAssignment (config entities, Tier 2)
```
Granted -> Revoked (deleted_at set; ConfigEdit + AuditRecord logged)
```
- **Delegation invariant:** only a Superadmin may create or revoke a `permissions` row for another User. An Admin cannot grant permissions even though it has full world authority — permission delegation is control-panel management, Superadmin-exclusive (§2.15).
- Dual attachment (one mechanism, two attachment points): a Permission attaches to a Role (applies to all holders) or directly to a User (per-world override, Doc 2 §8.1).
- `RoleAssignment` (User ↔ Role join) follows the identical `Granted -> Revoked` pattern with `deleted_at`, logged the same way.
- Revocation is soft so "who could do what, and when" stays reconstructable; physical removal, if ever, is Cleanup's job.
- Events: `PermissionGranted`, `PermissionRevoked`, `RoleAssignmentGranted`, `RoleAssignmentRevoked` (`UserPermissionGranted/Revoked` are the User-scoped view of Permission events, not a separate family).

2.17 SyncTarget (config entity, Tier 2)
```
Created -> Updated (ConfigEdit + AuditRecord, per Doc 8 ConfigurationService)
Created | Updated -> deleted_at set (soft)
```
- One configured offsite destination: type (`nas`/`google_drive`/other, Doc 2 §4.4), non-secret config, credential reference into `secrets`, scope (`global` default or `world_id` override) — same global-default-with-per-world-override shape as Schedule/CleanupPolicy.
- Invariant: exactly one resolvable SyncTarget applies per world at sync time (world override if present and enabled, else global default, else none — "none" means no sync, not an error).
- Events: `SyncTargetCreated`, `SyncTargetUpdated`, `SyncTargetDeleted` (soft).

2.17.1 SyncRecord (Tier 1 — permanent; job wrapper over immutable SyncAttempts)
```
(Sync Operation dispatched) -> Created, status = pending
pending -> succeeded   (most recent SyncAttempt succeeded)
pending -> failed      (most recent SyncAttempt failed, no retries remain, Doc 8 §6)
```
- One sync *job* (one artifact, one target, one Operation). Fields: `sync_id`, `artifact_id`, `sync_target_id`, `operation_id`, `status`, `started_at`, `finished_at` (set only at terminal status). `status` is derived from — never set independently of — the outcome of its most recent SyncAttempt.
- Events: `SyncJobStarted`, `SyncJobSucceeded`, `SyncJobFailed`.

2.17.2 SyncAttempt (Tier 1 — the actual retry history)
```
(SyncService makes one transfer attempt) -> Created   [immutable — never updated, never deleted]
```
- One row per attempt, always (first-try success still gets one row; two failures before success gets three).
- Fields: `attempt_id`, `sync_id`, `attempt_number` (strictly sequential per `sync_id`, starting 1, no gaps — `UNIQUE(sync_id, attempt_number)`), `started_at`, `finished_at`, `outcome` (`succeeded` / `failed_transient` / `failed_permanent` — distinguishing retryable from permanent like rejected credentials, matching Doc 8 §6), `error_message` (NULL on success).
- Invariant: immutable once written; a new attempt is always a new row.
- Events: `SyncAttemptSucceeded`, `SyncAttemptFailedTransient` (will retry), `SyncAttemptFailedPermanent` (SyncRecord → `failed` immediately).

3. Domain Events

- Full per-entity event lists are inline in §2. Cross-cutting rules:
  - Every WorldInstance transition fires its corresponding event (§2.3).
  - Operation events (§2.4) cover the full command plane.
  - `CleanupHardDeletePerformed` fires per row deleted, not per run.
  - `UserRoleChanged` and permission grant/revoke events always produce an AuditRecord — hard requirement, not optional telemetry.

3.1 Domain Glossary (canonical — other documents reference this instead of redefining terms)

- **Manager** — singleton control-plane application: global config, world registry, scheduling, security, event bus.
- **WorldInstance** — one independently managed Minecraft server: identity, paths, ports, config, logs, backups, policies.
- **RuntimeSession** — one continuous execution window of a WorldInstance, confirmed startup to confirmed stop; owns per-session RCON credentials.
- **JavaRuntime** — a registered Java installation usable by one or more WorldInstances.
- **Template** — a reusable server baseline (Vanilla, Paper, Fabric, Forge, etc.) for creating WorldInstances.
- **Operation** — the durable record for any state-changing action; every privileged/state-changing request becomes one.
- **BackupArtifact** — an immutable backup produced by a successful Backup Operation, belonging to one WorldInstance (or the Manager, for ManagerBackup).
- **Schedule** — recurring-execution configuration for backups, cleanup, or maintenance.
- **MissedRunRecord** — a permanent record of a Schedule occurrence due but not run; `resolved` or `ignored`, never deleted.
- **RoleAssignment** — the User ↔ Role link; grant/revoke using the shared `deleted_at`.
- **CleanupPolicy** — retention rules (age/count/space/schedule) for backup and stale-world deletion for a scope.
- **Notification** — a user-visible event from an Operation or system event; historical, never deleted.
- **NotificationRead** — per-user record of whether a Notification has been read/dismissed.
- **AuditRecord** — immutable, append-only history entry for a security- or operationally-significant event.
- **ClientSession** — authenticated browser session bound to a User, Device, and token, with expiration and revocation.
- **Device** — a known client machine used as trust signal and audit-attribution target; never the sole basis for authorization.
- **User** — an individually named account (username + password) that authenticates, holds Roles/Permissions, and is the actor on Operations and AuditRecords.
- **Role** — a named permission grouping (Client, Admin, Superadmin, plus optional custom roles) assignable to Users.
- **Permission** — a grant of one action category, globally or world-scoped, attached to a Role or directly to a User.
- **SyncTarget** — a configured offsite backup destination (NAS, Google Drive, etc.); global-default-with-per-world-override.
- **SyncRecord** — a permanent record of one offsite sync job for one BackupArtifact against one SyncTarget; `status` reflects the most recent SyncAttempt.
- **SyncAttempt** — one immutable, permanent record of a single transfer try within a SyncRecord's job — the actual retry history.
- **Tombstoned** — soft-delete state applied to WorldInstance (and analogously Device, JavaRuntime, Template) where the row and immutable ID persist permanently.
- **Tier 1 / Tier 2** — the two deletion classes in the Global Deletion & Retention Model (§0). Tier 1 never deleted by anything; Tier 2 soft-marked immediately, physically removed only by Cleanup, if ever.
- **Actor** — the User or system process (`system`) that initiated an Operation or produced an AuditRecord; always attributable, never anonymous.

3.2 Ownership Rules
- Manager owns: world registry, global settings, and (transitively, as defaults) Schedules/CleanupPolicies not overridden per-world.
- WorldInstance owns: its RuntimeSessions, BackupArtifacts, scoped Operations, and its own Schedule/CleanupPolicy overrides. Tombstoned, never hard-deleted, because so much history hangs off its ID.
- RuntimeSession is owned exclusively by one WorldInstance; a child entity, never independently addressable (§5, Aggregate Roots).
- User owns: its RoleAssignments, direct Permission grants, and is the referenced actor on its own Operations/AuditRecords/ClientSessions — but does not own those rows in the deletion sense; a soft-deleted User leaves all historical references intact.
- Device is referenced by (does not own) ClientSessions and AuditRecords; the reference is one-directional and survives revocation.
- Template and JavaRuntime are referenced by WorldInstance creation history and RuntimeSession launch snapshots respectively, but own neither — catalog/registry entities, not aggregates.
- CleanupPolicy and Schedule are owned by either Manager (global default) or a specific WorldInstance (override); never both for the same scope — the resolution rule belongs to Doc 8 ConfigurationService.
- SyncTarget follows the identical global-default-or-world-override shape. SyncRecord is owned by the BackupArtifact it mirrors, not by SyncTarget — its FK to `sync_targets` exists but the record is Tier 1 regardless. SyncAttempt is owned exclusively by its SyncRecord; a child entity, never independently addressable.
- General rule (single statement): nothing is ever hard-deleted by a normal user-facing action. Tier 1 is permanent, untouched even by Cleanup. Everything else that can be "deleted"/"revoked" is soft-marked with the shared `deleted_at`, logged, and only the Cleanup subsystem ever physically deletes. Every lifecycle in §2 was written to this rule.

4. Business Invariants

- Every business invariant is stated once at its defining location and referenced, not restated:
  - User → §1.1, §2.1 · RuntimeSession → §1.2, §2.2 · WorldInstance → §2.3 · Operation → §2.4 · BackupArtifact → §2.5 · Schedule → §2.6 · MissedRunRecord → §2.6.1 · CleanupPolicy → §2.7 · Notification / NotificationRead → §2.8 · AuditRecord → §2.9 · Manager → §2.10 · JavaRuntime → §2.11 · Template → §2.12 · Device → §2.13 · ClientSession → §2.14 · Role → §2.15 · Permission / RoleAssignment → §2.16 · SyncTarget / SyncRecord / SyncAttempt → §2.17–2.17.2
  - Cross-cutting (deletion model, snapshot pattern, `version` optimistic concurrency) → §0.
  - Concurrency and Operation mutual exclusion → Document 11.

5. Value Objects
- `Username` — validated string (charset/length rules finalized during Doc 7 DDL pass).
- `SecretRef` — opaque pointer to a `secrets` row; never carries the secret value outside the security subsystem.
- `EndReason` — closed enum per §2.2, not free text.

6. Aggregate Roots
- Manager (singleton), WorldInstance, Template, Device, User, Role (Permissions attach to a Role or directly to a User; Role is a small independent root, managed and referenced independently of any one User or WorldInstance).
- `RuntimeSession`, `BackupArtifact`, `Operation`, `Schedule`, `CleanupPolicy`, `MissedRunRecord`, `Notification`, `NotificationRead`, `AuditRecord`, `Permission`, `ClientSession`, `JavaRuntime`, `SyncTarget`, `SyncRecord`, `SyncAttempt` remain child/referenced entities inside the roots above — none independently addressable.

7. Traceability

| Element | Traces to |
|---|---|
| User individual-account model | Explicit product decision (see "Decisions on record"); Doc 2 §8.1 |
| Password secret reference not on User row | Doc 10 §2.2; Doc 3 §6.5 |
| Per-user, per-world Permission override | Doc 2 §8.1 |
| User/Device separation; device captured on every login/audit | Doc 2 §8.2, §17 device flows |
| Superadmin-floor invariant | Doc 2 §8.4 non-bypassable guards |
| RuntimeSession durable vs. runtime-only columns | Doc 7 §2 persistence philosophy |
| RuntimeSession starts at confirmed running | Original Doc 6; Doc 3 §7.1 |
| RuntimeSession reconciliation on restart | Doc 3 §7.4; failure mode in `legacyImplementation.txt` §10 |
| RCON rotation per session | Doc 3 §5.6, §8.4 |
| WorldInstance state list | Doc 3 §7.1 (formalized into transitions) |
| `pre_backup_state` resume-state gap | Identified at revision time; not previously specified |
| Restore is off-only; corrupted restores fully revert | Doc 1 §3 |
| Error/crash require explicit acknowledgement | Doc 2 §10.2 |
| Operation lifecycle | Doc 8 §3 (formalized into transitions) |
| Compensating actions as new Operations | Doc 6 original invariant, applied |
| Crash needs a driving Operation type | Identified at revision time; Doc 2 §9.2, Doc 3 §4.4 |
| BackupArtifact soft-delete, created-on-success-only | Doc 7 §9 retention rule extended; original "Immutable backup" |
| BackupArtifact retention-protection floor | Doc 1 §4, Doc 2 §4.5 |
| Version-on-edit for Schedule/CleanupPolicy | `legacyImplementation.txt` `cleanup_store`; Doc 1 §4 |
| MissedRunRecord | Doc 1 §13, Doc 3 §5.7 |
| CleanupPolicy hard-guard floors | Doc 1 §4 |
| Per-user NotificationRead | Individual-account decision; Doc 2 §7.3, Doc 1 §1 broadcast |
| AuditRecord annotation-of | Original Doc 6 append-only wording |
| WorldInstance tombstone / soft-delete | Resolved at revision time; preserves "World IDs are immutable" |
| Manager singleton | Doc 1 §17, Doc 3 §5.13 |
| JavaRuntime/Template soft-delete via provenance | Consistent historical-reference pattern |
| Device revocation vs. hard delete | Doc 2 §17 |
| ClientSession token outside `secrets` | Scope boundary decided at revision time |
| Role system-role floor; role renaming; Superadmin-only delegation | Explicit product decision; Doc 2 §8.1 |
| Runtime config off-only rule; Template independence; three-tier inheritance; ManagerBackup; backup lineage via FKs; integration adapter pattern; 4-level notification severity | Explicit product decisions and review findings (full context: Design Changelog; Document 11 §4–5) |
| Global Deletion & Retention Model; MissedRunRecord permanence; soft-delete + Cleanup-only physical delete; single shared `deleted_at` | Explicit product decisions (Design Changelog) |
| SyncTarget / SyncRecord / SyncAttempt | Doc 2 §4.4; SyncService gap closure (Doc 8); SyncAttempt split for full retry history |
| Full concurrency/locking model | Document 11 |
