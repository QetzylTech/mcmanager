Document 6: Domain Model (Revision 6+ — Deletion Model Corrected, Sync Entities Added, Cross-Reference Cleanup, CreateWorld/DeleteWorld Gap Closed)

Purpose
- Extends the original Document 6 with full definitions for the two entities flagged as gaps in Document 10 §4: `User` and `RuntimeSession`.
- Everything from the original Document 6 not touched here still stands as-is.
- This revision closes several Document 9 "Document 6 Expansion" checklist lines, but only for the entities covered below. The checklist remains open for the remaining entities (Operation, BackupArtifact, WorldInstance state machine, etc.) — see §7.
- **This revision corrects three things from Revision 5, per explicit instruction:** (1) `MissedRunRecord` is reclassified from "configuration, hard-cascade-deletable" to a permanent record that is never deleted, only resolved or ignored; (2) Schedule, CleanupPolicy, Role, and Permission/RoleAssignment no longer support direct hard delete — they soft-delete (a single `deleted_at` column, used everywhere) with every change logged; (3) a new global rule is introduced: the Cleanup subsystem is the only part of the system that ever performs a physical row delete, for anything, anywhere.

Decision on record
- Per your answer: `User` means individual named accounts (own username + password each), not shared per-role credentials. This supersedes the legacy shared admin/superadmin password model. Everything below is written against that decision.

1. Updated Core Entities

1.1 User (new — full definition)
- User is a first-class entity and aggregate root, distinct from Device.
- Identity
  - `user_id` — immutable, machine-readable, assigned at creation. Never reused, even after deletion.
  - `username` — unique among non-deleted users. Editable by an admin/superadmin or by the user themself, subject to step-up authentication. Not used as a foreign key anywhere; `user_id` is the durable reference.
  - `display_name` — optional, cosmetic only, no uniqueness constraint.
- Credentials
  - The password hash is not stored on the User entity itself. Per Document 10 §2.2, it lives in the `secrets` table; the User row holds a reference to its secret record, not the hash directly.
  - This mirrors Doc 3 §6.5's own content list, which already named "password hashes" as secret-store content — Document 10 just made it official for the schema.
- Status
  - `status`: `active` | `disabled` | `locked` | `deleted` (soft).
  - `failed_login_count`, `locked_until` — support the password-retry throttling required by Doc 2 §8.4 / Doc 1 §12.
- Relationships
  - Has many `RoleAssignments` (User <-> Role, many-to-many).
  - Has many direct `Permission` grants for per-world overrides (Doc 2 §8.1: "permissions per client, per user, per world, and per action category"). Role assignment covers the common case; direct Permission grants cover the exception case without needing a new Role per world.
  - Is the actor on many `Operation` records.
  - Is the actor on many `AuditRecord` entries.
  - Has many `ClientSession`s. A ClientSession binds a User to a session token, a Device (trust context), and an IP; the User is the identity, the Device is contextual trust, and these remain separate concepts (Doc 2 §8.2 already requires this separation).
  - Login is by username + password. Device identity is not a login credential and never substitutes for one — it is recorded alongside every login for audit purposes only (see "Audit capture" below).
- Audit capture (clarified per your instruction to keep device recording even with named accounts)
  - Every login attempt — successful or failed — creates a ClientSession-linked record capturing `user_id`, `device_id` (or raw IP/device-name if the device isn't yet a recognized/registered Device), and timestamp.
  - Every `AuditRecord` produced by a User action snapshots both `user_id` and `device_id` at write time, rather than only storing a `session_id` and joining live tables later. This matters because Device rows can be renamed, reassigned, or deleted after the fact (Doc 2 §17 device edit/delete flows), and an append-only audit record must not silently change meaning if the Device row it points to later changes. This follows Doc 2 §8.2's guidance directly: "actor attribution should prefer stable logical identity... while still retaining raw network evidence... for forensics."
  - This means named individual accounts do not remove any of the legacy device/IP attribution value — they add a second, more precise attribution layer (who) on top of the existing one (from what device/IP), rather than replacing it.
  - `created_by` — self-referencing optional link to the User who provisioned this account (accountability for account creation, per Doc 2 §9.2 audit coverage).
- Not modeled
  - Multiple humans sharing one User row is explicitly out of scope now that individual accounts were chosen. If two people need the same privilege level, they get two User rows with the same Role, not one shared row.

1.2 RuntimeSession (formalized — was narrative-only in Revision 1)
- Represents one continuous execution of a WorldInstance, from confirmed startup to confirmed stop.
- Durable columns (persisted, survives restart, per Doc 7 §2 persistence philosophy)
  - `session_id` — immutable, unique.
  - `world_id` — required FK to WorldInstance.
  - `started_at` — timestamp of the confirmed-running transition (see 2.2 below — not the button-press moment).
  - `ended_at` — nullable while the session is open.
  - `end_reason` — `graceful_stop` | `forced_stop` | `crashed` | `emergency_stop` | `reconciled_missing` (see 2.2).
  - `rcon_secret_ref` — reference into the `secrets` table for this session's RCON credential. Never the raw credential.
  - `port_used`, `java_runtime_id`, `launch_args_snapshot` — captured at launch time for historical/audit reference, independent of whether the live process is still around.
- Explicitly NOT persisted on this entity (per Doc 7 §2's "Do NOT Persist" list)
  - Process PID / process handle.
  - Live health-check results.
  - These are runtime-registry concerns, reconstructed at boot per Doc 3 §7.4, not part of the durable RuntimeSession row.
- Relationships
  - Belongs to exactly one WorldInstance (unchanged from Revision 1).
  - Only one open (unended) RuntimeSession may exist per WorldInstance at a time (unchanged invariant, now enforceable as a DB constraint: a partial unique index on `world_id` where `ended_at IS NULL`).

2. State Machines (new section)

2.1 User lifecycle
```
Provisioned -> Active
Active -> Disabled (admin action)
Disabled -> Active (admin re-enable)
Active -> Locked (N consecutive failed logins)
Locked -> Active (cooldown elapses OR admin unlock)
Active | Disabled -> Deleted (soft delete only)
```
- `Deleted` is terminal and irreversible through normal flows (a new account can be created with a new `user_id`, but a deleted account is not reactivated — this keeps historical actor references unambiguous).
- Hard delete is never allowed. A User row is never physically removed while any Operation, AuditRecord, or Notification still references its `user_id` — which in practice is always, since audit history is append-only and permanent (Doc 6 original "Key invariants": "Audit records are append-only").

2.2 RuntimeSession lifecycle
```
(WorldInstance reaches confirmed "running" state) -> Open
Open -> Closed[graceful_stop]   (operator-initiated stop completes normally)
Open -> Closed[forced_stop]     (kill/force-stop escalation)
Open -> Closed[crashed]         (crash detected while session was open)
Open -> Closed[emergency_stop]  (storage-guard-triggered emergency shutdown)
Open -> Closed[reconciled_missing]  (manager restart finds no matching live process)
```
- A RuntimeSession is created only at the moment the WorldInstance's runtime state resolver (Doc 3 §7.1) confirms `running` — not at `queued` or `starting`. This matches the original Doc 6 wording ("Starts when the server launches successfully") and avoids counting failed/aborted starts as sessions.
- On manager restart (Doc 3 §7.4 startup reconciliation), any RuntimeSession left `Open` from before the restart must be resolved one of two ways:
  - matched against a discovered live process for that world -> session remains Open, continues as-is.
  - no matching process found -> session is force-closed with `end_reason = reconciled_missing`.
- No RuntimeSession may be left `Open` indefinitely after a reconciliation pass completes. This is the formal version of the exact failure class the legacy system's `operation_reconciler` was built to patch over (see `legacyImplementation.txt` §10) — writing it as a state-machine rule here means it's a testable invariant, not just a background job's implicit behavior.

2.3 WorldInstance lifecycle (formalizing the flat state list in Doc 3 §7.1)
```
(does not exist) -> off              (CreateWorld Operation completes)
off -> queued          (Start Operation created)
queued -> starting      (scheduler dispatches, process launch attempted)
starting -> running     (startup signal / readiness confirmed — this is also the instant a RuntimeSession opens, per §2.2)
starting -> error       (process exits or times out before readiness is confirmed)
running -> stopping     (Stop Operation: operator stop, idle auto-stop, or emergency stop)
running -> crashed      (process exits unexpectedly with no Stop operation in flight)
running | off -> backing_up   (Backup Operation created; see resume_state note below)
off -> restoring        (Restore Operation created — restore is off-only, per Doc 1 §3 "Restore is disabled when the server is running")
stopping -> off          (shutdown confirmed)
backing_up -> <resume_state>   (backup completes — see below)
backing_up -> error      (backup fails)
restoring -> off          (restore completes, success or safely-reverted failure — Doc 1 §3: corrupted-backup restores are fully reverted)
restoring -> error        (restore fails in a way that cannot be safely auto-reverted)
error -> off              (requires explicit operator acknowledgement — never auto-clears)
crashed -> off            (requires explicit operator acknowledgement — never auto-clears)
off -> (tombstoned)       (DeleteWorld Operation completes — see invariant below)
```
- **Gap closed this pass**: world creation and deletion previously had no driving Operation type at all — a real hole in an architecture built entirely around "every state-changing action is an Operation" (Doc 3 §4.4). `CreateWorld` and `DeleteWorld` are added as first-class Operation types (alongside Start/Stop/Kill/Backup/Restore/Cleanup/Sync/ConfigEdit/CrashDetected — see Doc 8 §2) rather than folded into `ConfigEdit`, since both are structurally heavier than a field edit: `CreateWorld` provisions directories, ports, and a registry row from a Template; `DeleteWorld` tombstones a row with wide historical fan-out.
- `DeleteWorld` invariant: only reachable from `off` — a running, backing-up, or restoring world cannot be deleted out from under itself. The Operation must first reject (not silently queue-and-wait) if the world isn't `off`.
- `resume_state` note: `backing_up` is reachable from both `off` and `running` (backups can run against a live or a stopped world), so WorldInstance must persist which state it was in immediately before entering `backing_up` and return to that same state on success — not unconditionally to `off`. This is a gap in the flat state list from Doc 3 §7.1: a single enum can't express "return to where I came from," so the schema needs an explicit `pre_backup_state` column (or equivalent) alongside the current state.
- `error` and `crashed` are deliberately not self-clearing. Doc 2 §10.2 requires errors to be "recorded and surfaced by default instead of silent recovery," so both states persist until an operator dismisses them (optionally after taking a recovery action), consistent with how `starting -> error` never silently falls back to `off` on a failed launch either — that failure must be visible, not swallowed the way `legacyImplementation.txt` §10 shows the legacy reconciler sometimes doing.

2.4 Operation lifecycle (formalizing Doc 8 §3)
```
Created -> Queued
Queued -> Validating           (scheduler dispatches)
Validating -> Running          (preconditions/guards pass)
Validating -> Failed           (preconditions/guards reject — e.g. storage guard, conflict guard)
Running -> Completed
Running -> Failed
Running -> TimedOut
Queued | Validating -> Cancelled   (only for Operation types that support cancellation; not every type does)
```
- `Completed`, `Failed`, `Cancelled`, and `TimedOut` are all terminal. Consistent with the existing Doc 6 invariant "Operations are immutable except for status progression," no terminal Operation is ever reopened.
- Compensating actions (e.g. the automatic revert of a failed restore, Doc 1 §3) are recorded as **new** Operations that reference the failed Operation's `id`, never as a mutation of the original Operation's outcome. A failed restore's revert is its own auditable event, not a quiet rewrite of what happened.
- Not every WorldInstance transition today has a corresponding Operation. Crash detection is observation-driven, not command-driven, so nothing in Doc 8's Operation type list (`Start, Stop, Kill, Backup, Restore, Cleanup, Sync, ConfigEdit`) currently covers it. Given Doc 2 §9.2 explicitly requires audit coverage for "crashes and recovery attempts," and the architecture's own principle that all state-changing activity should be durable and auditable (Doc 3 §4.4), this revision recommends adding a system-actor Operation type (e.g. `CrashDetected`, actor = `system`) so crash transitions get the same durable-record treatment as user-triggered ones, rather than only producing a Notification/AuditRecord out of band.

2.5 BackupArtifact lifecycle
```
(backup job succeeds) -> Created   [immutable from this point on]
Created -> Deleted   (soft — see below)
```
- A BackupArtifact row is only ever created on a *successful* capture. A failed backup attempt produces a Failed Operation but no BackupArtifact row — there is no `pending` or `failed` state on the artifact itself, keeping the original Doc 6 wording ("Immutable backup produced by the manager") literally true.
- Deletion is soft, not physical-row-delete: `deleted_at` and `deleted_by_operation_id` are set, the underlying file is removed from disk, but the row remains queryable so cleanup history and audit trails can still say what existed and when it was removed. This mirrors how BackupArtifact rows already can't be truly forgotten per Doc 7 §9 ("Never automatically delete: ... Required recovery artifacts") — the same soft-delete shape is just extended to *all* artifacts, required or not, for consistent history.
- Retention-protection invariant (restated formally from Doc 1 §4 / Doc 2 §4.5): for each backup category, the artifact(s) needed to satisfy that category's configured "keep newest N" floor, and in all cases the single most recent artifact of a required category, can never be deleted by an ordinary cleanup run — dry or wet. Only an explicit superadmin force-flow can bypass this, and Doc 2 §8.4 already requires that path to carry elevated confirmation and immutable logging.

2.6 Schedule lifecycle
```
Created -> Enabled
Created -> Disabled
Enabled <-> Disabled   (toggle)
(any field edit) -> version incremented, last_changed_by/at updated, ConfigEdit Operation + AuditRecord logged
Enabled | Disabled -> deleted_at set   (soft delete — see Global Deletion & Retention Model below)
```
- A Schedule is forward-looking configuration, but per your instruction it is no longer hard-deleted directly by a user action. "Delete" sets `deleted_at` and stops it from firing; the row and its edit history remain queryable. Physical row removal, if it ever happens, is performed only by the Cleanup subsystem — see the Global Deletion & Retention Model section below.
- Every edit — including the soft-delete itself — bumps a version counter and produces a `ConfigEdit` Operation plus a resulting AuditRecord, carrying forward the legacy `rule_version`/`schedule_version` pattern (`legacyImplementation.txt`, `cleanup_store`) so "who changed this rule last" (Doc 1 §4) and the full change history stay reconstructable, not just the current state.
- **Decided this pass**: `version` is not just a display counter — it is used for optimistic concurrency control. An edit submitted against a stale `version` (i.e. someone else changed the Schedule since the editor loaded it) is rejected with a conflict error rather than silently overwriting the intervening change. This closes a previously-undefined gap: two admins editing the same Schedule concurrently now get a clear conflict signal instead of last-write-wins.
- When a WorldInstance is tombstoned, its world-scoped Schedules are soft-deleted (`deleted_at` set) at the same time, not hard-cascade-deleted — consistent with the same rule.

2.6.1 MissedRunRecord lifecycle (corrected — this is a permanent record, never deleted)
```
(scheduled run doesn't fire on time) -> Created, resolution = pending
pending -> resolved   (operator ran the missed job, or it's otherwise been addressed)
pending -> ignored    (operator dismissed it without running the missed job)
```
- MissedRunRecord is never deleted — soft or hard — by anything, including the Cleanup subsystem. It sits in the same permanent tier as AuditRecord and Notification: Doc 1 §13 and Doc 3 §5.7 require missed backups/cleanups to be recorded and surfaced, not silently caught up or forgotten, and a record that could later disappear would undercut exactly that guarantee.
- Fields: `schedule_id`, `expected_run_at`, `detected_at`, `resolution` (`pending`/`resolved`/`ignored`), `resolution_at`, `resolution_by`. It also carries a small snapshot of the Schedule's identifying info (name, type) captured at detection time, so the record stays meaningful even if the parent Schedule is later edited or soft-deleted — the same write-time-snapshot pattern already used for AuditRecord's device attribution in §1.1.
- Domain events: `MissedRunDetected`, `MissedRunResolved`, `MissedRunIgnored`.

2.7 CleanupPolicy lifecycle
```
Created -> Enabled
Created -> Disabled
Enabled <-> Disabled
(any field edit) -> version incremented, last_changed_by/at updated, ConfigEdit Operation + AuditRecord logged
Enabled | Disabled -> deleted_at set   (soft delete — see Global Deletion & Retention Model below)
```
- Same treatment as Schedule: soft-delete via `deleted_at`, every edit and deletion logged through a `ConfigEdit` Operation and AuditRecord, and the same world-tombstone-triggers-soft-delete (not hard-cascade) rule. `version` is likewise used for optimistic concurrency control, same as Schedule (decided this pass — see §2.6).
- Hard-guard invariants (currently only prose in Doc 1 §4) become formal domain invariants on this entity:
  - Age Rule minimum is a floor of 3 days; a CleanupPolicy cannot be saved with a lower value.
  - Count Rule minimum is a floor of 3 per backup category (session/manual/pre-restore/emergency) and per stale-world scope.
  - These floors, plus the BackupArtifact retention-protection invariant in §2.5, are two views of the same guarantee and must never be allowed to drift apart — a policy edit that would strand a required artifact below its floor is rejected at save time, not discovered later at cleanup-run time.

2.8 Notification lifecycle
```
Created -> (per-user) Read
Created -> ActionTaken   (for prompts that require a response, e.g. Action Prompt modal per Doc 4 §11.2)
Created -> Dismissed
```
- Notifications are historical (Doc 2 §7.3: "History of notifications must be kept as well as actions taken if actions are prompted"), so like BackupArtifact and AuditRecord, the row is never physically deleted — only its read/action state changes.
- Consequence of the User-model decision (see "Decision on record" above): now that accounts are individually named rather than shared/device-based, "read" state is naturally per-user, not a single flag on the Notification. This needs a join record (`NotificationRead`: `notification_id`, `user_id`, `read_at`) rather than a boolean column, since a broadcast notification (Doc 1 §1 — "everything is broadcast to clients") can be read independently by multiple logged-in users. This wasn't an issue under the shared-credential model considered earlier in this conversation; it's a direct downstream effect of the individual-account decision and should be treated as settled alongside it, not revisited separately.

2.9 AuditRecord lifecycle
```
(action occurs) -> Created   [terminal — no further states]
```
- This is the simplest entity in the model by design: pure insert-only log, matching the original Doc 6 invariant ("Audit records are append-only").
- Corrections or acknowledgements are modeled as new AuditRecord rows with an optional `annotation_of` self-reference to the record being corrected/acknowledged — never as an update to the original row's fields. This makes the existing Doc 6 language ("may allow new corrective entries... but should not allow silent destructive rewriting") into an actual schema-level rule instead of a policy statement.

Decisions Resolved (were open items in Revision 4, now settled)
- `pre_backup_state` is adopted as a persisted column on WorldInstance, per §2.3.
- Crash detection gets its own system-actor Operation type, `CrashDetected` (actor = `system`), so every WorldInstance transition — including crashes — is driven by a durable Operation record with no carve-out. This closes the gap noted in §2.4.
- World deletion cascade (corrected per your instruction): Schedule and CleanupPolicy are soft-deleted (`deleted_at` set), not hard-cascade-deleted, when their WorldInstance is tombstoned — consistent with the rule that only the Cleanup subsystem ever performs a physical delete (see the Global Deletion & Retention Model, immediately below). `MissedRunRecord` is excluded from this entirely: it is a permanent record and is untouched by world deletion, retaining its own snapshot fields regardless of what happens to the parent Schedule or WorldInstance. Everything historical — Operation, BackupArtifact, AuditRecord, RuntimeSession, Notification, MissedRunRecord — must retain a permanently valid `world_id` (or `schedule_id`) reference, which is only possible if WorldInstance (and, in practice, Schedule/CleanupPolicy) are never physically deleted outside a controlled Cleanup sweep. **WorldInstance itself is therefore soft-deleted (tombstoned)**: a `deleted_at` / `deleted_by_operation_id` pair is set, files are removed from disk as part of the `DeleteWorld` Operation (Doc 8 §2), but the row and its immutable `world_id` persist forever. Tombstoning a world is a `DeleteWorld` Operation, not a raw registry write — otherwise the existing Doc 6 invariant "World IDs are immutable" would break the first time any world is ever deleted.

Global Deletion & Retention Model (new — formalizes your instruction on delete/revoke/cleanup)

Three tiers, applied consistently across every entity in this document:

- **Tier 1 — Permanent, never deleted by anything, ever:** AuditRecord, Notification, NotificationRead, MissedRunRecord, SyncRecord, SyncAttempt. These are the record of what happened; deleting them would falsify history, not just tidy it up.
- **Tier 2 — Soft-deleted/revoked immediately by normal operations, physically removed only by Cleanup, if ever:** WorldInstance, Device, JavaRuntime, Template, User, BackupArtifact (metadata row), Schedule, CleanupPolicy, Role (custom roles only), Permission grants, RoleAssignments, ClientSession, SyncTarget. Every "delete" or "revoke" action on these entities is a status-column update plus a logged change (via a `ConfigEdit` Operation and AuditRecord where applicable) — never an immediate `DELETE FROM`.
- **There is no tier 3.** No entity in this model has a user-facing "delete" button that physically removes a row from the database directly.

Column naming convention (one column, used identically for every soft-removal across every entity — no split between "deleted" objects and "revoked" grants):
- `deleted_at` — the single timestamp column used whenever a Tier 2 entity is soft-removed, whether that's conceptually a "delete" (WorldInstance, Device, JavaRuntime, Template, User, BackupArtifact, Schedule, CleanupPolicy, Role) or a "revoke" (Permission, RoleAssignment, ClientSession). The underlying domain language can still say "revoked" where that reads more naturally (a Permission is "revoked," not "deleted"), but the schema-level marker is always `deleted_at`.
- May carry a companion `deleted_by` (actor) column, matching the pattern already used for `deleted_by_operation_id` on WorldInstance and BackupArtifact.

The hard-delete rule (the core of your instruction): **the only part of the system that ever issues a physical `DELETE FROM` against the database is the Cleanup subsystem** (`CleanupService`, via a Cleanup Operation). No route, command handler, or other service ever hard-deletes a row directly — soft-delete/revoke is the only action available anywhere outside of Cleanup. In practice:
- Cleanup's existing job (Doc 1 §4, Doc 2 §4.5) already sweeps expired BackupArtifacts and stale world data past their retention window — that scope now generalizes to also sweep aged-out, already-soft-deleted Tier 2 config rows (Schedule, CleanupPolicy, Role, Permission, RoleAssignment) past their own retention window, once nothing else still depends on them.
- WorldInstance, Device, JavaRuntime, Template, and User are Tier 2 in principle but in practice are unlikely to ever actually reach physical deletion, since Tier 1 records almost always still reference them — this is expected and fine; "eligible for Cleanup" doesn't mean "will ever actually be swept."
- This rule replaces the "hard delete allowed" language originally used for Schedule/CleanupPolicy/Role/Permission — those sections are corrected above and below to match.

2.10 Manager lifecycle
```
Uninitialized -> SetupInProgress -> Operational
Operational -> UpdateInProgress -> Operational
Operational -> RollbackInProgress -> Operational
```
- Manager is a singleton — exactly one Manager configuration row exists per deployment. This is a hard invariant, not a soft convention: nothing in the system creates a second one.
- Owns the current deployed version/commit reference (Doc 1 §17: "record current commit version, pull latest code, restart" / "rollback to previously deployed commit"), setup-completion flag, and the global settings it composes (the existing `global_settings` table in Doc 7).
- Domain events: `ManagerSetupCompleted`, `ManagerUpdateStarted`, `ManagerUpdateCompleted`, `ManagerRolledBack`, `ManagerRestarted`.

2.11 JavaRuntime lifecycle
```
Registered -> Verified   (health check confirms the executable works)
Registered | Verified -> Missing   (path no longer resolves at boot reconciliation)
Verified -> Deprecated   (superseded but kept for historical reference)
Deprecated -> deleted_at set   (soft — physical removal, if ever, is Cleanup's job alone, per the Global Deletion & Retention Model above)
```
- Invariant: a JavaRuntime can never be hard-deleted if any RuntimeSession's `launch_args_snapshot` (§1.2) references it, even for worlds that no longer exist (their WorldInstance is tombstoned, not gone). In practice this means it almost never leaves `Deprecated` — the same soft-removal pattern used everywhere else in this document for anything with historical references.
- Domain events: `JavaRuntimeRegistered`, `JavaRuntimeVerified`, `JavaRuntimeMarkedMissing`, `JavaRuntimeDeprecated`.

2.12 Template lifecycle
```
Created -> Updated (versioned)
Created | Updated -> Deprecated
Deprecated -> deleted_at set   (soft — physical removal, if ever, is Cleanup's job alone, per the Global Deletion & Retention Model above)
```
- Invariant: same provenance rule as JavaRuntime — a Template referenced by any WorldInstance's creation history (even a tombstoned one) is never hard-deleted, only deprecated. Doc 5's "World template catalog page" management (add/edit/delete) should read "delete" as this deprecation flow, not a physical row removal.
- Domain events: `TemplateCreated`, `TemplateUpdated`, `TemplateDeprecated`, `TemplateDeleted` (soft).

2.13 Device lifecycle
```
Unrecognized (seen, not yet registered) -> Registered   (admin approval, Doc 2 §8.2)
Registered -> Updated
Registered -> Revoked
```
- Invariant: Device rows are never hard-deleted once any AuditRecord or ClientSession has snapshotted their `device_id` (which, per the audit-capture rule in §1.1, is effectively always). "Delete" in Doc 2 §17's device management UI means `Revoked`, not a physical row removal — consistent with the write-time-snapshot design already established for audit records.
- Domain events: `DeviceRegistered`, `DeviceUpdated`, `DeviceRevoked`. (`last_seen_at` is a field update, not a domain event on its own — treating every heartbeat as an event would flood the audit trail for no operational benefit.)

2.14 ClientSession lifecycle
```
Created -> Active
Active -> Expired    (passive, time-based)
Active -> Revoked    (explicit — logout, admin action, or password change)
Active -> StepUpConfirmed (temporary elevated state for a single sensitive action, then reverts to Active)
```
- Invariant: an Expired or Revoked session can never authorize any action; this is enforced server-side on every request, never inferred client-side (Doc 3 §8.2).
- Revocation uses the same shared `deleted_at` column as every other Tier 2 entity (see Global Deletion & Retention Model, §2 addendum after 2.9) — Expiry is time-based and doesn't require `deleted_at` to be set, only a passed `expires_at`.
- Domain events: `ClientSessionCreated`, `ClientSessionExpired`, `ClientSessionRevoked`, `ClientSessionStepUpConfirmed`.
- Design note: the session token itself is stored (hashed) on the ClientSession row, not in the `secrets` table. Unlike RCON credentials or password hashes, a session token is short-lived and self-invalidating on expiry, so it doesn't need the same long-term secret-management treatment as the artifacts covered under Document 10 §2.2 — this is a deliberate scope boundary, not an oversight.

2.15 Role lifecycle
```
Created -> Updated   (ConfigEdit Operation + AuditRecord logged)
Created | Updated -> deleted_at set   (soft delete, custom roles only, no current holders — see below)
```
- Invariant: the three baseline roles required by Doc 2 §8.1 (viewer/operator, admin, superadmin) are marked `is_system_role` and can never be deleted, soft or hard, regardless of assignment count. This is the same category of non-bypassable guard as the superadmin-floor invariant in §4 — together they ensure the privilege model can't be dismantled from inside the UI.
- Custom roles beyond the three baseline ones may be freely created/edited/soft-deleted, subject to having no current holders. As with Schedule/CleanupPolicy, "delete" sets `deleted_at`, is logged, and physical removal — if it ever happens — is Cleanup's job alone (Global Deletion & Retention Model, above).
- Domain events: `RoleCreated`, `RoleUpdated`, `RoleDeleted` (soft).

2.16 Permission & RoleAssignment lifecycle
```
Granted -> Revoked   (deleted_at set, ConfigEdit Operation + AuditRecord logged)
```
- A Permission grant is either attached to a Role (applies to every User holding that role) or directly to a User (per-world override, per Doc 2 §8.1). This dual-attachment was already implied by the original Doc 6 text ("Role contains many Permissions" and Permission "grants an action globally or for a specific WorldInstance") and by the direct-grant relationship added to User in §1.1 — this section just names it as one mechanism serving two attachment points rather than two separate systems.
- `RoleAssignment` (the User <-> Role join referenced in §1.1) follows the identical pattern: `Granted -> Revoked`, using `deleted_at`, logged the same way.
- Revocation is soft (the shared `deleted_at` timestamp), not a row delete, so "who could do what, and when" remains reconstructable from history — the same append-preferred pattern used for Notification and AuditRecord. Physical removal of a revoked Permission or RoleAssignment row, if it ever happens, is Cleanup's job alone, per the Global Deletion & Retention Model above.
- Domain events: `PermissionGranted`, `PermissionRevoked`, `RoleAssignmentGranted`, `RoleAssignmentRevoked`. (The User-scoped variants `UserPermissionGranted`/`UserPermissionRevoked` from §3 are the User-facing view of the Permission events, not a separate event family.)

2.17 SyncTarget lifecycle (new — fills the SyncService gap raised in Document 8)
```
Created -> Updated   (ConfigEdit Operation + AuditRecord logged, per Doc 8 ConfigurationService)
Created | Updated -> deleted_at set   (soft delete — Tier 2, Global Deletion & Retention Model applies)
```
- Represents one configured offsite destination: type (`nas` / `google_drive` / other, per Doc 2 §4.4), non-secret config (host/path for NAS, etc.), a reference to its credential in `secrets`, and scope (`global` default or a specific `world_id` override) — the same global-default-with-per-world-override shape already used for Schedule and CleanupPolicy.
- Invariant: exactly one resolvable SyncTarget applies per world at sync time — a world-scoped override if one exists and is enabled, otherwise the global default. If neither exists, Sync simply has nothing to do for that world's backups (not an error state).
- Domain events: `SyncTargetCreated`, `SyncTargetUpdated`, `SyncTargetDeleted` (soft).

2.17.1 SyncRecord lifecycle (revised — now a job wrapper over immutable SyncAttempt rows, for full retry history)
```
(Sync Operation dispatched) -> Created, status = pending
pending -> succeeded   (most recent SyncAttempt succeeded)
pending -> failed      (most recent SyncAttempt failed and no retries remain, per Doc 8 §6)
```
- SyncRecord represents one sync *job* (one artifact, one target, one Operation) — never deleted, soft or hard, same permanence rationale as before.
- Fields: `sync_id`, `artifact_id` (FK -> backup_artifacts, RESTRICT), `sync_target_id` (FK -> sync_targets, RESTRICT), `operation_id` (FK -> operations, RESTRICT), `status`, `started_at` (first attempt's start), `finished_at` (set only once `status` reaches a terminal value), `created_at`. `status` is derived from — and updated by — the outcome of its most recent SyncAttempt; SyncRecord itself does not store per-attempt detail anymore.
- Domain events: `SyncJobStarted`, `SyncJobSucceeded`, `SyncJobFailed`.

2.17.2 SyncAttempt lifecycle (new — the actual retry history, per your instruction)
```
(SyncService makes one transfer attempt) -> Created   [immutable from this point on — never updated, never deleted]
```
- One row per attempt, always. Attempt 1 of a sync that succeeds on the first try still gets exactly one SyncAttempt row; a sync that fails twice before succeeding gets three.
- Fields: `attempt_id`, `sync_id` (FK -> sync_records.sync_id, RESTRICT), `attempt_number` (1, 2, 3...), `started_at`, `finished_at`, `outcome` (`succeeded` / `failed_transient` / `failed_permanent` — distinguishing retryable network failures from permanent ones like rejected credentials, matching SyncService's own retry decision in Doc 8 §6), `error_message` (NULL on success), `created_at`.
- Invariant: a SyncAttempt row is never updated or deleted once written — it is a pure historical fact ("at this timestamp, this attempt did this"), the same immutability guarantee as AuditRecord, just scoped to one sync job instead of the whole system.
- Invariant: `attempt_number` is strictly sequential per `sync_id`, starting at 1, with no gaps — enforceable as a partial constraint (`UNIQUE(sync_id, attempt_number)`) at the schema level.
- Domain events: `SyncAttemptSucceeded`, `SyncAttemptFailedTransient` (will retry), `SyncAttemptFailedPermanent` (will not retry, SyncRecord moves to `failed` immediately).

3. Domain Events (new section, scoped to these two entities)

User events
- `UserCreated`, `UserRoleChanged`, `UserPermissionGranted`, `UserPermissionRevoked`, `UserDisabled`, `UserEnabled`, `UserLocked`, `UserUnlocked`, `UserPasswordChanged`, `UserDeleted`.
- `UserRoleChanged` and permission grant/revoke events must always produce an AuditRecord (Doc 2 §9.2 requires config/privilege changes to be logged) — this is a hard requirement, not optional telemetry.

RuntimeSession events
- `RuntimeSessionStarted`, `RuntimeSessionEnded` (carries `end_reason`), `RuntimeSessionReconciled` (fired specifically when a restart forces a stale session closed — distinct from a normal `RuntimeSessionEnded` so operators can tell the difference between "we saw it stop" and "we never actually saw it stop, we inferred it").

WorldInstance events
- `WorldCreated`, `WorldQueued`, `WorldStarting`, `WorldStarted` (i.e. reached `running`), `WorldStartFailed`, `WorldStopping`, `WorldStopped`, `WorldCrashed`, `WorldBackingUp`, `WorldBackupSucceeded` (returns to `resume_state`), `WorldBackupFailed`, `WorldRestoring`, `WorldRestoreSucceeded`, `WorldRestoreFailed`, `WorldErrorAcknowledged`, `WorldCrashAcknowledged`, `WorldDeleted` (tombstoned).
- These are the events Doc 8's workflows already gesture at (`WorldStarted`, `BackupCompleted`, `RestoreCompleted` are named in Doc 8 §2's command flow table) — this section just gives the full set a consistent naming pattern and fills in the gaps (failure and acknowledgement events weren't previously named anywhere).

Operation events
- `OperationCreated`, `OperationQueued`, `OperationValidationFailed`, `OperationStarted`, `OperationProgress` (carries a checkpoint payload), `OperationCompleted`, `OperationFailed`, `OperationCancelled`, `OperationTimedOut`.

BackupArtifact events
- `BackupArtifactCreated`, `BackupArtifactDeleted` (carries `deleted_by_operation_id`).

Schedule events
- `ScheduleCreated`, `ScheduleUpdated` (carries new version), `ScheduleEnabled`, `ScheduleDisabled`, `ScheduleDeleted` (soft), `ScheduleRunDue`, `ScheduleRunMissed` (creates a `MissedRunRecord`).

MissedRunRecord events
- `MissedRunDetected`, `MissedRunResolved`, `MissedRunIgnored`. (Replaces the earlier `MissedRunAcknowledged` — resolution is now explicit about whether the missed run was actually addressed or just dismissed, and the record itself is permanent.)

CleanupPolicy events
- `CleanupPolicyCreated`, `CleanupPolicyUpdated`, `CleanupPolicyEnabled`, `CleanupPolicyDisabled`, `CleanupPolicyDeleted` (soft), `CleanupRunExecuted` (carries dry/wet flag), `CleanupRunSummaryRecorded`, `CleanupHardDeletePerformed` (fired only when Cleanup actually performs a physical row removal on any Tier 2 entity — the one event type that corresponds to a real `DELETE FROM` anywhere in the system). **Decided this pass**: fires once per row physically deleted, not once per Cleanup run — a single wet run that hard-deletes 12 aged-out rows produces 12 of these events, giving per-row audit precision rather than one opaque batch event.

SyncTarget events
- `SyncTargetCreated`, `SyncTargetUpdated`, `SyncTargetDeleted` (soft).

SyncRecord events
- `SyncJobStarted`, `SyncJobSucceeded`, `SyncJobFailed`.

SyncAttempt events
- `SyncAttemptSucceeded`, `SyncAttemptFailedTransient` (will retry), `SyncAttemptFailedPermanent` (will not retry).

Notification events
- `NotificationCreated`, `NotificationRead` (per user), `NotificationActionTaken`, `NotificationDismissed`.

AuditRecord events
- `AuditRecordCreated` only — by design, there is no update or delete event for this entity.

3.1 Domain Glossary (closes the last open Doc 9 checklist line for terminology)

- **Manager** — the singleton control-plane application: owns global config, world registry, scheduling, security, and the event bus.
- **WorldInstance** — one independently managed Minecraft server: identity, paths, ports, config, logs, backups, policies.
- **RuntimeSession** — one continuous execution window of a WorldInstance, from confirmed startup to confirmed stop; owns per-session RCON credentials.
- **JavaRuntime** — a registered Java installation usable by one or more WorldInstances.
- **Template** — a reusable server baseline (Vanilla, Paper, Fabric, Forge, etc.) used to create new WorldInstances.
- **Operation** — the durable record for any state-changing action; every privileged or state-changing request becomes one.
- **BackupArtifact** — an immutable backup produced by a successful Backup Operation, belonging to one WorldInstance.
- **Schedule** — recurring-execution configuration for backups, cleanup, or maintenance.
- **MissedRunRecord** — a permanent record of a Schedule occurrence that was due but did not run; resolved as `resolved` or `ignored`, never deleted, by anyone, ever.
- **RoleAssignment** — the User <-> Role link; same grant/revoke pattern as Permission, using the shared `deleted_at` column.
- **CleanupPolicy** — retention rules (age/count/space/schedule) governing backup and stale-world deletion for a scope.
- **Notification** — a user-visible event generated from an Operation or system event; historical, never deleted.
- **NotificationRead** — a per-user record of whether a given Notification has been read.
- **AuditRecord** — an immutable, append-only history entry for a security- or operationally-significant event.
- **ClientSession** — an authenticated browser session bound to a User, a Device, and a token, with expiration and revocation.
- **Device** — a known client machine used as contextual trust signal and audit-attribution target; never the sole basis for authorization.
- **User** — an individually named account (username + password) that authenticates, is assigned Roles/Permissions, and acts as the actor on Operations and AuditRecords.
- **Role** — a named permission grouping (viewer/operator, admin, superadmin, plus optional custom roles) assignable to Users.
- **Permission** — a grant of one action category, either globally or scoped to a specific WorldInstance, attached to a Role or directly to a User.
- **SyncTarget** — a configured offsite backup destination (NAS, Google Drive, etc.), global-default-with-per-world-override, same shape as Schedule/CleanupPolicy.
- **SyncRecord** — a permanent record of one offsite sync job for one BackupArtifact against one SyncTarget; its `status` reflects the outcome of its most recent SyncAttempt.
- **SyncAttempt** — one immutable, permanent record of a single transfer try within a SyncRecord's job — the actual retry history, queryable per attempt.
- **Tombstoned** — the soft-delete state applied to WorldInstance (and analogously to Device, JavaRuntime, Template) where the row and its immutable ID persist permanently, but the entity is no longer active/selectable.
- **Tier 1 / Tier 2** — the two deletion classes in the Global Deletion & Retention Model (§2, after 2.9). Tier 1 (AuditRecord, Notification, NotificationRead, MissedRunRecord, SyncRecord, SyncAttempt) is never deleted by anything. Tier 2 (everything else that can be "deleted") is soft-marked immediately and physically removed only by the Cleanup subsystem, if ever.
- **Actor** — whichever User or system process (`system`) initiated an Operation or produced an AuditRecord; always attributable, never anonymous.

3.2 Ownership Rules (standalone, aggregating what was previously implicit in each entity's relationships)

- Manager owns: the world registry, global settings, and (transitively, as defaults) Schedules and CleanupPolicies that aren't overridden per-world.
- WorldInstance owns: its RuntimeSessions, BackupArtifacts, Operations scoped to it, and its own Schedule/CleanupPolicy overrides. WorldInstance is tombstoned, never hard-deleted, precisely because so much history hangs off its ID (Decisions Resolved, above).
- RuntimeSession is owned exclusively by one WorldInstance; it is a child entity, never independently addressable outside that boundary (confirmed in §6, Aggregate Roots).
- User owns: its RoleAssignments, direct Permission grants, and is the referenced actor on its own Operations, AuditRecords, and ClientSessions — but User does not own those referencing rows in the deletion sense; a deleted (soft) User leaves all historical references intact, same pattern as WorldInstance.
- Device is referenced by, but does not own, ClientSessions and AuditRecords — the reference is one-directional and survives Device revocation.
- Template and JavaRuntime are referenced by WorldInstance creation history and RuntimeSession launch snapshots respectively, but own neither — they are catalog/registry entities, not aggregates that WorldInstance belongs to.
- CleanupPolicy and Schedule are owned by either Manager (global default) or a specific WorldInstance (override); never both at once for the same scope — the resolution rule (which one applies) belongs in Doc 8's ConfigurationService, not restated here.
- SyncTarget follows the identical global-default-or-world-override ownership shape as Schedule/CleanupPolicy. SyncRecord is owned by the BackupArtifact it mirrors (via the Sync Operation that produced it), not by SyncTarget — a SyncRecord's meaning shouldn't depend on the target config surviving, which is why its FK to `sync_targets` still exists (per Doc 7) but SyncRecord itself is Tier 1 regardless of what happens to the target later. SyncAttempt is owned exclusively by its SyncRecord — a child entity, never independently addressable, same relationship shape as RuntimeSession-to-WorldInstance.
- General rule applied throughout this document (corrected — see the Global Deletion & Retention Model, §2 addendum after 2.9): **nothing is ever hard-deleted by a normal user-facing action. AuditRecord, Notification, NotificationRead, and MissedRunRecord are permanent and untouched even by Cleanup. Everything else that can be "deleted" or "revoked" — WorldInstance, Device, JavaRuntime, Template, User, BackupArtifact, Schedule, CleanupPolicy, Role, Permission, RoleAssignment, ClientSession — is soft-marked using one shared `deleted_at` column, with the change logged, and the only thing in the entire system that ever performs a physical row delete is the Cleanup subsystem.** Every lifecycle in §2 was written to this rule.

4. Business Invariants (expanded)

User invariants
- `username` is unique among non-deleted users.
- Password secret reference is never null for an `active` User.
- At least one `active` User with the superadmin role must exist at all times. Disabling, deleting, or demoting the last superadmin is rejected outright — non-bypassable, consistent with Doc 2 §8.4's "non-bypassable safety guards" principle applied here to account lockout risk rather than just data deletion.
- A User can never authorize their own step-up-protected action using only their own standing session; step-up (password re-entry) is still required per Doc 2 §8.2 regardless of who the user is.
- Every AuditRecord tied to a User action carries a device identity snapshot captured at the time of the action; it is never solely reconstructed by joining to the current state of the Device table.

RuntimeSession invariants
- Exactly one open RuntimeSession per WorldInstance (restated from Revision 1, now schema-enforceable).
- Every RuntimeSession's `rcon_secret_ref` must point to a credential generated for that specific session — never reused from a prior session for the same world (Doc 3 §5.6/§8.4, unchanged).
- A RuntimeSession's `ended_at` is only ever set once; end reason is immutable after being set (consistent with the general "Operations are immutable except for status progression" pattern already applied elsewhere in Doc 6).

WorldInstance invariants
- Every WorldInstance transition is driven by an Operation, except `crashed` (an observed, not commanded, transition — see Operation invariants below for how that gap is handled).
- `pre_backup_state` must be set whenever entering `backing_up` and must resolve to a valid prior state (`off` or `running`) on completion — a world can never "forget" what it was doing before a backup started.
- `error` and `crashed` require an explicit acknowledgement action (`WorldErrorAcknowledged` / `WorldCrashAcknowledged`) before returning to `off`. No code path silently clears either state.
- `restoring` may only be entered from `off` (Doc 1 §3); an attempt to restore while `running` is rejected before an Operation is even created, not handled by a failed Operation after the fact.
- `current_operation_id` is set when an Operation begins driving a transition and is cleared (set to `NULL`) the moment that Operation reaches any terminal status (`Completed`/`Failed`/`Cancelled`/`TimedOut`) — it is never left pointing at a finished Operation. (Gap identified and closed this pass — previously unstated.)

Operation invariants
- A Failed or TimedOut Operation is never rewritten to Completed, and vice versa — state progression is one-directional per the existing Doc 6 rule.
- Any compensating action (automatic rollback, safe-revert of a corrupted restore) is a new Operation referencing the original by ID, never a mutation of the original's `status` or `result`.
- Every user-triggered WorldInstance transition has exactly one driving Operation. Crash detection currently does not (see §2.4) — this revision recommends adding a system-actor Operation type for it so the "every state-changing action is an Operation" principle (Doc 3 §4.4) holds without a carve-out.

Global Deletion invariants (new this revision)
- No service, route, or command handler other than `CleanupService` ever executes a physical `DELETE FROM` against the database. This is enforced at the architecture layer (Doc 3 §4.1's single-authoritative-control-plane principle extends to this specifically), not just as a coding convention.
- Tier 1 entities (AuditRecord, Notification, NotificationRead, MissedRunRecord, SyncRecord, SyncAttempt) are excluded from Cleanup's sweep scope entirely — they are never candidates for physical deletion, by anyone, ever.
- Every soft-delete or revoke action (setting the shared `deleted_at` column) on a Tier 2 entity produces a `ConfigEdit` Operation and a corresponding AuditRecord, so the change itself is logged even though the row survives.

MissedRunRecord invariants (new this revision)
- `resolution` starts at `pending` and transitions to exactly one of `resolved` or `ignored` — never back to `pending`, and never both.
- A MissedRunRecord's snapshot fields (schedule name/type at detection time) are set once at creation and never updated, even if the parent Schedule is later edited or soft-deleted — this keeps the record's meaning fixed to the moment the miss was detected.

SyncTarget / SyncRecord / SyncAttempt invariants (new this revision)
- Exactly one SyncTarget resolves per world at sync time (world override if present and enabled, else global default, else none) — never zero-or-ambiguous, never two competing targets silently picked between.
- A SyncRecord's `status` only ever moves forward: `pending -> succeeded` or `pending -> failed`, never backward, and it is always derived from the SyncAttempt rows underneath it, never set independently of them.
- A SyncAttempt row is immutable once written — never updated, never deleted — and `attempt_number` is strictly sequential per `sync_id` with no gaps.
- Sync failure never mutates `backup_artifacts` — the local backup's validity is entirely independent of whether it was ever successfully mirrored offsite.

5. Value Objects (new, scoped to these two entities)
- `Username` — validated string (allowed charset/length rules to be defined during Doc 7 column typing pass).
- `SecretRef` — opaque pointer to a `secrets` table row; never carries the secret value itself in memory contexts outside the security subsystem.
- `EndReason` — closed enum as listed in §2.2, not a free-text field.

6. Updated Suggested Aggregate Roots
- Manager (singleton)
- WorldInstance
- Template
- Device
- User
- Role (Permissions can attach to a Role or directly to a User; Role itself is a small independent aggregate root since it's managed and referenced independently of any one User or WorldInstance)
- `RuntimeSession`, `BackupArtifact`, `Operation`, `Schedule`, `CleanupPolicy`, `MissedRunRecord`, `Notification`, `NotificationRead`, `AuditRecord`, `Permission`, `ClientSession`, `JavaRuntime`, `SyncTarget`, `SyncRecord`, `SyncAttempt` all remain child/referenced entities inside one of the roots above — none of them are independently addressable aggregate roots in their own right.

7. Traceability

| Element | Traces to |
|---|---|
| User individual-account model | This conversation's decision (see "Decision on record" above); Doc 2 §8.1 privilege levels |
| Password secret reference (not stored on User) | Document 10 §2.2 secrets resolution; Doc 3 §6.5 |
| Per-user, per-world Permission override | Doc 2 §8.1 ("permissions per client, per user, per world, and per action category") |
| User/Device separation | Doc 2 §8.2 |
| Device identity recorded on every login/audit action alongside username | This conversation's decision — named accounts add attribution precision without dropping legacy device/IP tracking; Doc 2 §8.2, §17 |
| Superadmin-floor invariant | Doc 2 §8.4 non-bypassable safety guards |
| RuntimeSession durable vs. runtime-only columns | Doc 7 §2 persistence philosophy |
| RuntimeSession start = confirmed running, not button press | Original Doc 6 wording; Doc 3 §7.1 runtime state resolver |
| RuntimeSession reconciliation on restart | Doc 3 §7.4; `legacyImplementation.txt` §10 (operation reconciler) as the failure mode this formalizes against |
| RCON rotation per session | Doc 3 §5.6, §8.4 (unchanged, restated) |
| WorldInstance state list | Doc 3 §7.1 (formalized here into transitions) |
| `pre_backup_state` / resume-state gap | Identified in this revision; not previously specified anywhere |
| Restore is off-only | Doc 1 §3 |
| Corrupted-backup restores fully revert | Doc 1 §3 |
| Error/crash require explicit acknowledgement | Doc 2 §10.2 |
| Operation lifecycle | Doc 8 §3 (formalized here into transitions) |
| Compensating actions as new Operations, not mutations | Original Doc 6 invariant ("Operations are immutable except for status progression"), applied here |
| Crash lacks a driving Operation type | Identified in this revision; recommend new `CrashDetected` system-actor Operation type; Doc 2 §9.2, Doc 3 §4.4 |
| BackupArtifact soft-delete, created-on-success-only | Doc 7 §9 retention rule, extended here for consistency; original Doc 6 "Immutable backup" wording |
| BackupArtifact retention-protection floor | Doc 1 §4, Doc 2 §4.5 |
| Schedule/CleanupPolicy version-on-edit | `legacyImplementation.txt` `cleanup_store` rule/schedule version pattern; Doc 1 §4 |
| MissedRunRecord (new entity) | Doc 1 §13, Doc 3 §5.7 — previously only a background-job concern, now a domain object |
| CleanupPolicy hard-guard floors as formal invariants | Doc 1 §4 |
| Notification per-user read state (NotificationRead join) | Direct consequence of the individual-account decision earlier in this conversation; Doc 2 §7.3, Doc 1 §1 broadcast model |
| AuditRecord annotation-of pattern | Original Doc 6 ("append-only... may allow new corrective entries") |
| pre_backup_state decision (adopted) | Resolved this revision |
| CrashDetected system-actor Operation type (adopted) | Resolved this revision; Doc 2 §9.2, Doc 3 §4.4 |
| WorldInstance tombstone / soft-delete (adopted) | Resolved this revision; implemented via the `DeleteWorld` Operation type (Doc 8 §2); preserves original Doc 6 invariant "World IDs are immutable" |
| Manager singleton | Doc 1 §17, Doc 3 §5.13 |
| JavaRuntime/Template soft-delete via provenance | Same historical-reference pattern applied consistently across this document |
| Device revocation vs. hard delete | Doc 2 §17 device management UI; consistent with audit-snapshot rule in §1.1 |
| ClientSession token stored outside `secrets` table | Scope boundary decided this revision — short-lived, self-invalidating tokens vs. long-term secrets |
| Role system-role floor | Doc 2 §8.1; same category as superadmin-floor invariant |
| Permission dual-attachment (Role or direct User grant) | Original Doc 6 wording + §1.1 direct-grant addition, unified here |
| SyncTarget / SyncRecord / SyncAttempt (new entities) | Doc 2 §4.4 offsite sync requirement; SyncService gap identified and closed in Document 8; Doc 3 §3.1/§5.14 offsite sync adapter slot; SyncAttempt split out per your explicit instruction to preserve full retry history |
| Global Deletion & Retention Model (three-tier) | This conversation's explicit instruction — corrects Revision 5 |
| MissedRunRecord reclassified as permanent, never deleted | This conversation's explicit instruction — corrects Revision 5 |
| Schedule/CleanupPolicy/Role/Permission/RoleAssignment: soft-delete + logged change, physical delete only via Cleanup | This conversation's explicit instruction — corrects Revision 5 |
| Single shared `deleted_at` column (no `revoked_at` split) | This conversation's explicit instruction |

8. Document 6 Checklist Status (final)

Cross-checking against the Document 9 "Document 6 Expansion" checklist:
- [x] Complete domain glossary — §3.1.
- [x] Define all aggregate roots — §6.
- [x] Define all entities — sixteen original entities (including `User` and formalized `RuntimeSession`) plus `MissedRunRecord`, `NotificationRead`, `SyncTarget`, `SyncRecord`, and `SyncAttempt` — twenty-one entities total — now have full definitions across Revisions 2-6.
- [~] Define all value objects — three are formally typed (`Username`, `SecretRef`, `EndReason`); several more fields introduced across this document (trigger_type, notification category/severity, etc.) are value-object candidates but not yet formally typed. This is the one item not fully closed.
- [x] Define ownership rules — §3.2.
- [x] Define entity lifecycles — §2 (all sixteen).
- [x] Define state machines — §2 (WorldInstance, Operation, RuntimeSession, User, ClientSession are the entities with genuine multi-state machines; the rest are simpler create/soft-delete lifecycles, documented as such rather than padded into artificial state diagrams).
- [x] Define domain events — §3, per entity.
- [x] Define business invariants — §4, per entity plus this document's decisions.
- [x] Add traceability to Documents 2-5 — the running table in §7, now covering every entity introduced across Revisions 2-5.

Remaining work before Document 6 can be marked fully `[x]` in Document 9:
- Finish typing the remaining value objects (minor, mechanical — can happen alongside Doc 7's column-typing pass rather than blocking it).

Everything else that made Document 6 an in-progress `[~]` document in Document 9 is now addressed.

Correction note: this revision also fixes a modeling error from Revision 5, where `MissedRunRecord` was incorrectly grouped with hard-cascade-deletable configuration and Schedule/CleanupPolicy/Role/Permission were described as directly hard-deletable. Both are corrected above per explicit instruction, and the new Global Deletion & Retention Model section (§2, after 2.9) is now the authoritative statement on deletion for every entity in this document — any future entity added to Doc 6 should be classified into Tier 1 or Tier 2 against that section rather than deciding deletion behavior ad hoc.

Addition note: `SyncTarget` (Tier 2), `SyncRecord` (Tier 1), and `SyncAttempt` (Tier 1, new — split out per explicit instruction to preserve full per-attempt retry history rather than a single incrementing counter) are added in this pass to support the `SyncService` defined in Document 8, closing the previously-flagged "no owning service for offsite sync" gap end-to-end across the domain model, schema, and service layer simultaneously rather than leaving the entities undefined while the service existed.
