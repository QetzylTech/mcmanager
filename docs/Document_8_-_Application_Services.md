# Document 8: Application Services & Operation Flows

Concrete service behavior from Doc 6/7 — who does what, in what order, with retry/timeout/cancellation/concurrency rules.

## 1 Service responsibilities & boundaries

`[X: a,b]` = owns; `Delegates: [X]`; `Touches:` = tables/files. Service = owning service for its operation types unless noted.

| Service | Capabilities | Delegates | Touches |
|---|---|---|---|
| WorldService | Registry:CRUD, Create:Template, Delete:Tombstone, Rename:Metadata(ConfigEdit), Enforce:ConfigOffOnly | Process:Runtime, Data:Backup/Restore/Cleanup | `world_instances`, `world_settings`, `templates`(R), `java_runtimes`(R) |
| RuntimeService | Start, Stop, Kill, Session:Open/Close, RCON:RotatePerSession, Health:Probe, Crash:Detect, State:Resolve | Operation wrapper:OperationService/Scheduler | `world_instances`, `runtime_sessions`, `secrets`(RCON only) |
| OperationService | Op:Create/Status/Checkpoint/Idempotency/Timeout/Cancel, in-memory progress broadcast, milestone-only persistence, Lock:ReleaseAtTerminal (Doc 9 §1.1) | Domain action:owning service | `operations` |
| BackupService | Backup:Capture/RegisterArtifact/ResumeAutosave, RCON:NotifyPlayers, Sync:TriggerFollowOn, ManagerBackup(world_id=NULL) | When:Scheduler/User, Transfer:SyncService | `backup_artifacts`, `operations`(checkpoints), `runtime_sessions`(R) |
| RestoreService | Restore:Validate/PreBackup/Stage/Archive/Switch/RestartIfWasRunning, History:Record | PreBackup:BackupService | `restore_history`, `backup_artifacts`, `world_instances`, `operations` |
| CleanupService | Retention:Dry/Wet, Delete:HardOnlyPath (any Tier 2 past window) | — | `backup_artifacts`(file+row), stale world dirs, aged-out soft-deleted Tier 2 rows |
| SyncService | Sync:Transfer, Records:JobPerArtifact+AttemptPerTry, Retry:TransientBackoff (§6) | Target/Creds:ConfigurationService, Backup:BackupService | `sync_records`, `sync_attempts`, `sync_targets`(R), `backup_artifacts`(R), `secrets`(adapter) |
| SchedulerService | Schedule:Evaluate/Dispatch, Missed:Detect+Record(create only) | Work:owning service | `schedules`, `missed_run_records`(create), `operations`(create) |
| AuthenticationService | Login:User+Pass, Session:Issue/StepUp, Throttle:PassRetry/Lockout | Authorize:AuthorizationService | `users`, `secrets`(password check), `client_sessions`, `devices`(context) |
| AuthorizationService | Policy:Eval(actor,role,grant,world,state), Roles:Client/Admin/Superadmin, Delegate:SuperadminOnly (Doc 6 §2.16) | AuthN:AuthService — assumes valid session | `roles`, `role_assignments`, `permissions`(R-heavy) |
| NotificationService | Notify:Publish(4 severities), Reads:LazyPerUser, Serve:DropdownSorted | — | `notifications`, `notification_reads` |
| AuditService | Audit:Write terminal operations, security/auth events, and ConfigEdit diffs (actor/device snapshot at write, Doc 6 §0.1) | — | `audit_records` (insert-only; no UPDATE/DELETE ever) |
| FileManagerService | Files:Guarded CRUD, Confirmation:Elevated, Audit:Entry | — | world filesystem (via adapter), `audit_records`(write) |
| TemplateService / JavaRuntimeService | Template:CRUD+Deprecate, JavaRuntime:CRUD+Deprecate, Launches:DataDriven(category free-text) | — | `templates`, `java_runtimes` |
| ConfigurationService | Config:GuardedEdits(server.properties), ConfigEdit:Orchestrate(never silent), Settings:3-TierInheritance, Version:OptimisticCheck (Doc 9 §4) | Executing the ops themselves | `world_instances`(metadata), `world_settings`, `global_settings`, `schedules`, `cleanup_policies`, `roles`, `permissions`, `role_assignments`, `sync_targets`, `templates`(write via logged ConfigEdit) |
| MetricsService | Metrics:Cadence(null/15s-cache/1Hz), Snapshot:CacheForFirstPaint | — | none persisted (reads `world_instances`/`runtime_sessions`, broadcasts) |

### Service dependency boundary

Application services depend on domain types and ports, not concrete infrastructure or platform adapters. The composition root supplies adapter implementations through constructor injection. Existing transaction-oriented SQL paths use the persistence port to preserve transaction behavior; new persistence behavior should use repositories where practical.

## 2 Command flow per operation type

Standard shape for all: authorize → validate preconditions → create Operation → queue → dispatch → execute with checkpoints → audit → notify → terminal status. Differences per type = preconditions + domain service.

| Operation Type | Preconditions | Domain Service | Terminal Success State |
|---|---|---|---|
| CreateWorld | valid Template, non-conflicting port/addressing, authorization | WorldService | new `world_instances` row, `state = off` |
| Start | world `off`, storage guard passes, not in 10s cooldown, **EULA accepted** (Doc 14 §5 — `eula_required` rejects `EULA_NOT_ACCEPTED`, no Operation) | RuntimeService | `state = running`, new `runtime_sessions` row |
| Stop | world != `off`, password verified | RuntimeService | `state = off`, `runtime_sessions.ended_at` set |
| Kill | world `running`/`stopping` (escalation), password step-up + elevated confirmation | RuntimeService | same as Stop, `end_reason = forced_stop` |
| Backup | no backup/restore/cleanup running for this world, storage guard passes | BackupService | new `backup_artifacts` row, world returns to `pre_backup_state` |
| Restore | world `off`, no backup/cleanup running, valid artifact | RestoreService | `restore_history` row, world back to `off` |
| Cleanup | no backup/restore running for the affected scope | CleanupService | cleanup summary in `operations.data_json`, any row/file removal performed |
| Sync | backup just completed, a `SyncTarget` resolves (override or global default) | SyncService | new `sync_records` row (`succeeded`) |
| ConfigEdit | authorization for the specific config category | ConfigurationService | updated row + `deleted_at`/`revoked` marker if applicable, always with `audit_records` entry |
| CrashDetected | none (system-observed) | RuntimeService | `state = crashed`, actor_type = `system` |
| DeleteWorld | world `off`, no backup/restore/cleanup running, password step-up + elevated confirmation | WorldService | `deleted_at` set (tombstoned), files removed from disk |

**"Elevated confirmation"** (Kill, DeleteWorld; Stop/Restore's existing password verification = same concept): both (1) password step-up (re-entry even for an authenticated session) and (2) explicit scope-preview confirmation screen showing exactly what will be affected before commit.

### 2.x Flows (compressed; diagram shape is uniform)

- **Start:** POST /worlds/{id}/start → authz(start) → create Op(Queued) → dispatch → launch via platform adapter → checkpoint(starting) → wait readiness → checkpoint(running) + open RuntimeSession → audit(OpCompleted) → notify(WorldStarted).
- **Backup (running):** trigger → create Op → dispatch → storage guard → RCON pause autosave → capture archive → register BackupArtifact → RCON resume autosave → checkpoint(Completed) → audit.
- **Restore:** create Op (password-verified) → dispatch → validate artifact integrity → **mandatory pre-restore backup** → stage extracted files → archive old world → switch server.properties → record restore_history → checkpoint(Completed | Failed[reverted]) → audit.
- **Cleanup (wet):** create Op(wet=true, password+ack) → dispatch → evaluate candidates against CleanupPolicy floors → apply blast-radius cap → physical DELETE (only hard-delete path) → checkpoint(Completed, summary in data_json) → audit.
- **Sync (auto after backup):** register artifact → create Op(Sync, artifact_id) → dispatch → create sync_records(pending) → resolve SyncTarget → loop attempts: upload; insert immutable sync_attempts row (attempt_number+1) → update sync_records.status from latest attempt → checkpoint(Completed|Failed) → notify(SyncFailed) on terminal failure.
- **Crash detection:** probe observes unexpected exit → create Op(CrashDetected, actor=system) → state=crashed, close RuntimeSession(end_reason=crashed) → audit → notify(WorldCrashed).
- **ConfigEdit:** PATCH with version → authz → **compare submitted version vs current; stale → 409 CONFIG_VERSION_CONFLICT, no Operation** (Doc 9 §4) → create Op → apply write (deleted_at/revoked marker if applicable) → checkpoint(Completed) → audit with before/after diff in payload.
- **Kill:** POST (step-up + elevated confirmation) → authz → create Op(Kill) — **atomically cancels in-flight Stop (`superseded_by_kill`), becomes sole in-flight op** → forced terminate via platform adapter (process group / job object) → checkpoint(Completed) + close RuntimeSession(forced_stop) → audit → notify.
- **CreateWorld:** POST /api/worlds → authz(create_world) → create Op → dispatch → validate template + port/addressing uniqueness → provision directories + registry row (state=off) → checkpoint(Completed) → audit.
- **DeleteWorld:** POST (step-up + preview hash) → authz → precondition: state=off, no in-flight Backup/Restore/Cleanup → else 409, no Operation → create Op → tombstone world_instances, soft-delete schedules/cleanup_policies → remove world files → checkpoint(Completed) → audit → notify.

## 3 Query responsibilities

- World list/detail → WorldService (composes RuntimeService live state + BackupService last-backup summary; search-by-name + state/version filtering at query layer, backed by `world_instances (display_name)` index).
- Live metrics → MetricsService. Operation history/status → OperationService. Backup/restore inventory → BackupService/RestoreService.
- Notifications (unread count, prioritized list) → NotificationService, joined against `notification_reads` for requesting user, sorted severity then recency.
- Audit/history views → AuditService. Missed-run list → SchedulerService. Device/user/role views → AuthenticationService / AuthorizationService.

## 4 Scheduler

- Evaluate all enabled `schedules` on a fixed tick: **every 30 seconds** (locked, §6.0).
- Per due schedule: check conflicting in-flight Operation for the same scope (Doc 9); if clear, create+dispatch; if not clear, or tick missed (manager down/skipped), create `missed_run_records` row — **missed runs are never auto-caught-up**.
- A missed run sits `pending` until an operator marks it `resolved` (manually running the job) or `ignored`.

## 5 Retry, timeout, cancellation

### 5.0 Locked tuning constants

Ship as defaults in `global_settings`; globally overridable only where the table says "configurable" — an override = plain `global_settings` edit (ConfigEdit + audit), never a code change. Changing these defaults in the design docs requires an ARCHITECTURE §16 conflict-log entry.

| Constant | Locked value | Notes |
|---|---|---|
| Scheduler tick interval | **30s** | §4; missed-run detection at tick granularity |
| Start readiness timeout | **120s** | configurable; timeout → Start `TimedOut`, world `error` (Doc 13 §4.2) |
| Stop graceful deadline | **60s** | then escalate to Kill (escalation reuses Kill path — Doc 13 C10) |
| Kill process-level deadline | **10s** | after forced signal, if tree not exited → supervisor re-asserts termination, marks `forced` on exit-classification |
| Start cooldown | **10s** | duplicate-start guard (Doc 9 §6 "Start — Ignored") |
| Sync transient retries | **3 total attempts** | exp backoff waits 30s/60s between attempts; 3rd `failed_transient` → SyncRecord `failed` |
| Sync per-attempt timeout | **120s** | configurable |
| Sync outer overall bound | **30min** | total wall-clock for all attempts; configurable |
| Sync global concurrency cap | **2 simultaneous transfers** | §7; configurable (Doc 10 `SYNC_CONCURRENCY_CAP`) |
| MetricsCadence | null / **15s** cache / **1Hz** stream | locked, not part of global settings |
| Storage guard default reserve | **10 GB** absolute | + 10% free-space bound as overflow safety net (Doc 9 §1.2); configurable |
| Step-up window | **10min** | Doc 6 §2.14; configurable |
| Log line buffer | **5000 lines** per world | ring buffer (Doc 13 §3.3); configurable when `VERBOSE_LOGGING=true`; deployed `VERBOSE_LOGGING=false` processes essential channels only |
| `VERBOSE_LOGGING` | **false** deployed default | non-secret `.env` flag; false suppresses debug, filters raw Minecraft output, and omits step-level backup/restore and sync traces; true enables full canonical-channel ingestion |
| Supervisor poll cadence | **1s** running; **15s** idle/all-off | Doc 13 §4.1; not user-configurable |
| Render interval (live metrics) | **1Hz** | bounded by MetricsCadence |
| Blast-radius cap | **500 candidates** per cleanup action | beyond this, elevated confirmation required (Doc 10 `CLEANUP_BLAST_RADIUS`); configurable |
| Password retry throttle | **5 failures** → lockout; lockout **15 min** | configurable via `global_settings` (Doc 6 §1.1) |
| Session expiry | **7 days** inactivity; absolute max **30 days** | Doc 6 §2.14; configurable |
| Idle auto-stop default | **off** (disabled) | per-world `idle_countdown_seconds`; 3-tier settings (Doc 6 §2.10) |
| SSE replay buffer | **200 events** per stream | Doc 10; configurable |

Referenced by Doc 13 (C9/C10), Doc 10 (`OP_TIMEOUT`, `AUTH_THROTTLED`), Doc 11 (injected-clock tests).

### 5.1 Per-operation retry/timeout/cancel

| Operation Type | Auto-retry? | Timeout (locked §5.0) | Cancellable? |
|---|---|---|---|
| CreateWorld | No | Short (dir/registry setup) — default 120s | While `Queued`/`Validating` only |
| Start | No (duplicate-start guard + 10s cooldown; failed start needs new explicit action) | **120s** readiness (configurable) | No — mid-launch interruption is a Kill |
| Stop | No | **60s** before escalating to Kill | No |
| Kill | No | **10s** process-level | No |
| Backup | No (failure surfaced; retry = new trigger) | Configurable per world size | While `Queued`/`Validating` only |
| Restore | No | Longer default (file I/O) — default 30min | While `Queued`/`Validating` only — once staging begins, must run to terminal |
| Cleanup | No | Configurable, scales with candidate set | Yes while `Queued`/`Validating`; dry-runs inherently low-risk |
| Sync | **Yes — the one exception.** Exp backoff **3 total attempts** (wait 30s, then 60s) for transient; permanent failures go straight `Failed` | Per-attempt **120s** + outer **30min** (configurable) | **Yes, even while `Running`** — aborting a transfer is safe (source artifact immutable/untouched) |
| ConfigEdit | N/A (sync-fast) | Short (formality) — default 30s | No |
| CrashDetected | N/A (system observation) | N/A | No |
| DeleteWorld | No | Configurable, scales with world size — default 30min | While `Queued`/`Validating` only, before file removal |

- **Running Sync cancellation:** the in-flight attempt is appended once with
  outcome `failed_transient` and a cancellation message; the `SyncRecord`
  becomes terminal `failed`; the Operation becomes terminal `Cancelled` and
  receives its single terminal audit. No automatic retry follows. A later
  operator retry creates a new Sync Operation and SyncRecord. The source
  artifact remains unchanged, and the NAS adapter removes any unpublished
  temporary upload before returning.

- General rule: `Cancelled` only reachable from `Queued`/`Validating`. Nothing cancellable once `Running` — real-world side effects can't be safely unwound. Kill is the safe way to interrupt a `running` world; in-flight Backup/Restore must run to terminal.
- **Kill is the single exception to "nothing is cancellable once `Running`":** dispatching Kill atomically cancels in-flight `Stop` (`error_code = 'superseded_by_kill'`) and becomes sole in-flight Operation, keeping the derived world lock unambiguous (Doc 9 §6, Doc 6 §2.4). Kill's own runtime-process interruption is its `Running` work and is not cancelled.
- Sync is the deliberate exception to both general rules (auto-retry, cancel-while-Running) — network transfer failures/aborts carry no irreversibility risk; the thing being moved already exists safely elsewhere.

## 6 Concurrency & conflict

Governed entirely by Doc 9 (mutual-exclusion matrix, lock taxonomy, optimistic concurrency, queue/reject/preempt). This section retained only for residuals Doc 9 does not cover:

- **Sync vs. operational matrix:** Sync is single-flight per artifact (no duplicate concurrent upload of the same `backup_artifacts` row) but otherwise independent of the Backup/Restore/Cleanup/Start/Stop matrix — it only reads an immutable artifact file, never touches live world state. Configurable global concurrency cap (e.g. max 2 simultaneous transfers) recommended given modest-hardware target.
- **Locking granularity:** Backup/Restore/Cleanup conflicts evaluated per-world for world-scoped operations; storage guard is the single global lock (Doc 9 §1.2).

## 7 Failure recovery (service-level for Doc 7 §6 reconciliation)

- **Start** left `Validating`/`Running` past restart with no matching process → `Failed`, `error_code = manager_restart_incomplete`, world resolved `off`.
- **Backup** interrupted → `Failed`; no `backup_artifacts` row ever created for a failed attempt (Doc 6 §2.5), so nothing to clean up.
- **Restore** interrupted mid-flight (manager crash) → no dedicated undo; recovery = operator manually re-runs Restore using the pre-restore backup created at the start. Known, accepted product limitation (Doc 6 §2.5).
- **Restore with failed post-restore startup** — the *different* case, when the switch succeeded but the world fails to come back up — is **not** operator-invented: RestoreService follows the Doc 14 §12 decision tree (automatic rollback to `pre_restore_artifact_id` as a compensating Operation; only if rollback itself fails does the world sit in `error` for operator action). The tree is normative; RestoreService implements it, does not design it.
- **Cleanup** interrupted mid-delete → partial deletion possible; next evaluation re-computes candidate discovery fresh against current state — idempotent by construction.

## 8 Notification pipeline

- Fixed trigger list: world started/stopped/crashed, world being backed up/restored, sync failure, suspicious client activity, unauthorized action attempts, critical low storage, missed scheduled jobs.
- Every trigger creates exactly one `notifications` row (Tier 1). `notification_reads` rows created lazily, one per user, when that user views the notification — never fanned out upfront.
- Severity: critical = crash/unauthorized-attempt/critical-storage; high = backup/restore failed, sync failed (terminal); normal = missed job, sync retry, suspicious activity; informational = started/stopped, backup/cleanup succeeded. (Four levels per Doc 6 §2.8.)
- Startup/shutdown chimes: startup chime on manager readiness, shutdown chime on shutdown begin. Both **resolver-based** — keyed off the reconciled state resolver, never a log line alone (Doc 13), and off Manager lifecycle events `ManagerSetupCompleted`/`ManagerRestarted` and shutdown initiation. Content configurable via `notification_defaults` (Doc 6 — Manager-default only, no per-world override). Optional user-facing sounds; never carry state by themselves (no nav alert / Doc 4 violation).

## 9 Security contract (implementation requirements — not options)

Locked by ARCHITECTURE §16 ruling 14. Applied by AuthenticationService/AuthorizationService/web middleware; do not invent alternatives at implementation time.

- **Password hashing: Argon2id** (memory-hard, OWASP-recommended). Hash stored via `secrets` table (Doc 7 §2.24) — never on the User row, never plaintext.
- **Session-ID rotation:** fresh session ID after login, after any privilege elevation (step-up confirm), and after a password change. Old ID revoked (`client_sessions.deleted_at`), new ID issued. No rotation = security defect.
- **HTTPS:** mandatory for any non-loopback deployment. Plain HTTP only on loopback; `Secure` cookie flag whenever not loopback. Deployment docs make this explicit.
- **Security headers** (every HTTP response, incl. SSE where applicable): `Content-Security-Policy` (tight default; frame-ancestors 'none' for clickjacking), `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, cache-control `no-store` on `/api` responses carrying user-specific/world-private data.
- **Password reset/recovery:** **no password-reset mechanism by design.** An operator-level Superadmin can reset another user's password (`PATCH /api/users/{id}`); self-recovery out of scope. Documented decision, not an omission. (Locked out user → same Superadmin path.)
- **Secrets at rest:** all `secrets` values encrypted at rest (Doc 7 §10). Nothing plaintext in the DB beyond non-secret config Doc 7 classifies as such.

## 10 Audit pipeline

- Every Operation terminal status transition (`Completed`, `Failed`, `Cancelled`, `TimedOut`) → exactly one `audit_records` row. Creation and intermediate checkpoint/status updates create none.
- Every `ConfigEdit` → `audit_records` row with before/after diff in `payload`.
- Every login attempt (success/failure) and every authorization denial → `audit_records` row, with `actor_username_snapshot` + `device_id_snapshot`/`device_name_snapshot` captured at that moment (Doc 6 §0.1).
- AuditService never updates or deletes; corrections use `annotation_of` (Doc 6 §2.9).

## 11 Anonymization policy (deliberately no service)

- **No AnonymizationService, no Anonymize or Erase operation type.** Anonymization/right-to-erasure is out of scope by design (Doc 6 audit invariant): Tier 1 records permanent and unmodifiable; no service may mutate/delete them to satisfy a scrub request.
- GDPR needs handled by data minimization at write time (capture only what the product needs), not retroactive mutation. If future law requires erasure, that's a product/legal decision gated on a documented migration preserving audit structural integrity — not a new service bolted into this design.
- Fallback for user deletion: User row soft-deleted (Tier 2, Doc 6 §2.1); historical audit references remain readable via `actor_username_snapshot` with no join to the deleted row.
- This section exists to say explicitly the gap is a documented, accepted decision, so implementers don't invent a scrubbing service.
