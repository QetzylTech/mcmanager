# Document 7: Database Schema & Persistence Design

Scope: buildable SQLite schema derived from Document 6 — every table, column, type, key,
index, and constraint. Everything here is downstream of Document 6; where a rule is named
(deletion tiers, secrets storage, etc.), it applies a decision already made there.

## 0. Conventions (apply to every table unless stated otherwise)

- **IDs**: `TEXT`, application-generated (UUIDv4 or similar). No auto-increment for
  anything referenced across tables or needing stable export/import identity.
  `INTEGER PRIMARY KEY AUTOINCREMENT` is acceptable only for purely internal,
  never-referenced rows (none currently).
- **Timestamps**: `INTEGER`, Unix epoch seconds.
- **Booleans**: `INTEGER` (0/1).
- **JSON payloads**: `TEXT`, application-validated. SQLite JSON1 functions may query them;
  no native JSON column type.
- **Deletion marker**: exactly one column, `deleted_at INTEGER NULL`, used identically
  everywhere a Tier 2 entity is soft-removed. `NULL` = active. No second column or
  status-enum substitute.
- **Deletion actor**: `deleted_by TEXT NULL` (user_id or `'system'`) on every table with
  `deleted_at`.
- **Tier 1 tables** (`audit_records`, `notifications`, `notification_reads`,
  `missed_run_records`, `sync_records`, `sync_attempts`) have no `deleted_at` column at all.
- **FK enforcement is the deletability boundary**: every *enforced* FK is
  `ON DELETE RESTRICT`. A table that must outlive its referent stores the ID as a plain
  value that is deliberately **not an FK**, plus a denormalized snapshot
  (`audit_records.actor_user_id` + `actor_username_snapshot`,
  `audit_records.device_id_snapshot`, `missed_run_records.schedule_id`,
  `runtime_sessions.launch_args_snapshot`). "Snapshot references are not FKs" — the
  deletability check for a Tier 2 row counts only enforced FKs, never plain-value snapshots.
- **Global Persistence Invariants (see ARCHITECTURE.md — do not restate here)**:
  - `PRAGMA foreign_keys = ON` on every connection before any other statement.
  - Boot-time `PRAGMA foreign_key_check` sweep after migrations, before serving requests —
    any violation is a startup-blocking critical error, never silently repaired.
- **No `ON DELETE CASCADE` anywhere.** Only Cleanup ever physically deletes, and it checks
  dependents explicitly.

## 1. Full Table List

Manager/global: `manager`, `global_settings`, `schema_migrations`
World/registry: `world_instances`, `world_settings`, `templates`, `java_runtimes`
Runtime: `runtime_sessions`, `operations`
Backup/restore/retention: `backup_artifacts`, `restore_history`, `schedules`,
`missed_run_records`, `cleanup_policies`
Sync: `sync_targets`, `sync_records`, `sync_attempts`
Notifications/audit: `notifications`, `notification_reads`, `audit_records`
Identity/security: `users`, `roles`, `role_assignments`, `permissions`, `devices`,
`client_sessions`, `secrets`

(27 tables.)

## 2. Table Definitions (compact SQL-like shorthand)

Legend: type `TEXT` unless marked (`INT`, `JSON`). `PK` = primary key. `FK->t` = enforced
FK to table t, `ON DELETE RESTRICT`. `UNIQ_SOFT` = unique WHERE `deleted_at IS NULL`
(partial index). `IMM` = immutable. `NULL` = nullable. `T1`/`T2` = deletion tier (Doc 6).
Indexes follow each table as `IDX:`. `//` = inline notes.

### 2.1 manager // T2, singleton — exactly one row, app-enforced
  manager_id: PK | deployed_version // commit ref | setup_completed: INT | created_at | updated_at

### 2.2 global_settings // T2, singleton; defaults inherited by any world without a `world_settings` override
  settings_id: PK | timezone // IANA | idle_countdown_seconds: INT | notification_defaults: JSON | minecraft_root_path | backup_root_path | log_root_path | offsite_sync_defaults: JSON // creds in secrets | version: INT // Document 11 §4 | updated_at | updated_by: FK->users

### 2.3 schema_migrations
  version: INT PK, sequential | name | applied_at: INT

### 2.4 world_instances // T2, tombstoned, never hard-deleted in practice per Doc 6
  world_id: PK IMM // forever, even past deleted_at | display_name: UNIQ_SOFT | template_id: FK->templates | server_type // vanilla/forge/fabric/paper/... | mc_version | java_runtime_id: FK->java_runtimes | port: INT UNIQ_SOFT | addressing_strategy // subdomain/port/path | addressing_value | state // off/queued/starting/running/stopping/restoring/backing_up/crashed/error | pre_backup_state: NULL // set only while state=backing_up | launch_args: JSON // editable only while state=off: Doc 6 §4, Document 11 §5 | metadata_version: INT // Document 11 §4, metadata fields only | deleted_at: NULL | deleted_by: NULL | created_at | updated_at
  IDX: (state), (deleted_at) partial, (display_name)

### 2.5 world_settings // T2, 1:1 with world_instances, row exists only when a world overrides global_settings
  world_id: PK FK->world_instances | minecraft_root_override: NULL | backup_root_override: NULL | log_root_override: NULL | offsite_sync_override: JSON NULL | idle_countdown_override: INT NULL // completes 3-tier inheritance, Doc 6 §2.10 | version: INT // Document 11 §4 | updated_at | updated_by: FK->users
  // notification_defaults deliberately has NO per-world override (Doc 6 §2.10)

### 2.6 templates // T2, soft-deleted/deprecated only, Doc 6 §2.12
  template_id: PK | name: UNIQ_SOFT | category // free-text, never a closed enum | default_version | config_defaults: JSON // must include generic launch-command template; adapter launches by data | source // built_in/imported | deprecated: INT // distinct from deleted_at: hidden from create, still referenced historically | version: INT // Document 11 §4 | deleted_at: NULL | deleted_by: NULL | created_at | updated_at

### 2.7 java_runtimes // T2, soft-deprecated only, Doc 6 §2.11
  runtime_id: PK | label: UNIQ_SOFT | executable_path | version_detected | status // registered/verified/missing/deprecated | deleted_at: NULL | deleted_by: NULL | created_at | updated_at

### 2.8 runtime_sessions // T2 in principle, practically permanent
  session_id: PK | world_id: FK->world_instances | started_at: INT // set only at confirmed running (Doc 6 §2.2) | ended_at: NULL | end_reason: NULL // graceful_stop/forced_stop/crashed/emergency_stop/reconciled_missing | rcon_secret_id: FK->secrets | port_used: INT | java_runtime_id: FK->java_runtimes // historical, not necessarily current | launch_args_snapshot: JSON // captured at launch; independent of later edits | created_at
  CONSTRAINT: partial UNIQUE (world_id) WHERE ended_at IS NULL — exactly one open session per world

### 2.9 operations // durable command-plane record; immutable except status progression
  op_id: PK | op_type // CreateWorld/Start/Stop/Kill/Backup/Restore/Cleanup/Sync/ConfigEdit/CrashDetected/DeleteWorld | world_id: NULL FK->world_instances // null = manager-global | actor_type // user/system | actor_user_id: NULL FK->users // null when actor_type=system | idempotency_key: NULL | status // Created/Queued/Validating/Running/Completed/Failed/Cancelled/TimedOut | checkpoint: JSON NULL | attempt: INT | compensates_operation_id: NULL FK->operations // compensating ops only | intent_at | started_at: NULL | finished_at: NULL | error_code: NULL | message: NULL | data_json: JSON NULL // type-specific payload incl. cleanup run summaries | created_at | updated_at
  IDX: (world_id, status) — REQUIRED, backs the derived world lock (Document 11 §1.1); (idempotency_key) unique-where-not-null, scoped by op_type

### 2.10 backup_artifacts // T2, created-on-success-only, Doc 6 §2.5
  artifact_id: PK | world_id: NULL FK->world_instances // NULL = ManagerBackup (manager DB/settings/templates/permissions) | category // session_end/manual/scheduled/pre_restore/emergency/manager_config | storage_path | size_bytes: INT | checksum | operation_id: FK->operations // producing Backup op | deleted_at: NULL // soft; file removed, row retained | deleted_by: NULL | created_at
  IDX: (world_id, category, created_at) — shape retention rules need for keep-newest-N-per-category

### 2.11 restore_history // T2, immutable append-only outcome record
  restore_id: PK | world_id: FK->world_instances | operation_id: FK->operations | source_artifact_id: NULL FK->backup_artifacts // null = raw snapshot path | pre_restore_artifact_id: FK->backup_artifacts // mandatory pre-restore backup | operator_user_id: FK->users | outcome // success/failed/reverted | rollback_of_restore_id: NULL FK->restore_history // corrective restore self-ref | started_at | finished_at: NULL | created_at

### 2.12 schedules // T2, Doc 6 §2.6
  schedule_id: PK | scope // global/world | world_id: NULL FK->world_instances // null when scope=global | schedule_type // backup/cleanup/maintenance | interval_spec: JSON // daily/weekly/monthly/every_n_days + params | time_of_day | enabled: INT | version: INT // Document 11 §4 | last_changed_by: FK->users | last_changed_at | deleted_at: NULL | deleted_by: NULL | created_at

### 2.13 missed_run_records // T1 — permanent, no deleted_at, Doc 6 §2.6.1
  missed_run_id: PK | schedule_id // plain value, NOT an FK (snapshot rationale §0) | schedule_name_snapshot | schedule_type_snapshot | expected_run_at | detected_at | resolution // pending/resolved/ignored | resolution_at: NULL | resolution_by: NULL // user_id, plain value, not an FK (must outlive referenced user) | created_at

### 2.14 cleanup_policies // T2, Doc 6 §2.7
  policy_id: PK | scope // global/world | world_id: NULL FK->world_instances | age_rule_days: INT // floor 3, app-enforced (Doc 6 §2.7) | space_rule_pct: INT NULL | count_rules: JSON // per-category floors, each >= 3 | schedule_id: NULL FK->schedules | version: INT // Document 11 §4 | last_changed_by: FK->users | last_changed_at | deleted_at: NULL | deleted_by: NULL | created_at

### 2.15 notifications // T1 — permanent, Doc 6 §2.8
  notification_id: PK | category | severity // critical/high/normal/informational — dropdown ordering (Doc 5) | message | related_operation_id: NULL FK->operations | related_world_id: NULL FK->world_instances | requires_action: INT | action_taken: NULL | created_at

### 2.16 notification_reads // T1 — permanent, per-user read/dismiss, Doc 6 §2.8
  notification_id: PK FK->notifications | user_id: PK FK->users | read_at: NULL | dismissed_at: NULL // hides from THIS user's dropdown only; notification row untouched

### 2.17 audit_records // T1 — permanent, append-only, Doc 6 §2.9/§0.1
  audit_id: PK | event_type | actor_type // user/system | actor_user_id: NULL // plain value, NOT an FK — survives soft-deleted User | actor_username_snapshot: NULL // captured at write from users.username — keeps logs readable after soft-delete/rename (Doc 6 §0.1) | device_id_snapshot: NULL // plain value, not an FK | device_name_snapshot: NULL | ip_snapshot: NULL | operation_id: NULL FK->operations | world_id: NULL FK->world_instances | payload: JSON NULL | annotation_of: NULL FK->audit_records // corrections/acknowledgements | created_at
  IDX: (created_at), (actor_user_id), (world_id)

### 2.18 users // T2, soft-deleted, Doc 6 §1.1/§2.1
  user_id: PK IMM | username: UNIQ_SOFT | display_name: NULL | secret_id: FK->secrets // password hash ref | status // active/disabled/locked | failed_login_count: INT | locked_until: NULL | created_by: NULL FK->users // self-ref | deleted_at: NULL | deleted_by: NULL | created_at | updated_at

### 2.19 roles // T2 for custom; baseline roles never deleted_at (app-enforced), Doc 6 §2.15
  role_id: PK | name: UNIQ_SOFT | description: NULL | is_system_role: INT // true for Client/Admin/Superadmin | version: INT // Document 11 §4 | deleted_at: NULL | deleted_by: NULL | created_at | updated_at

### 2.20 role_assignments // T2, Doc 6 §2.16
  assignment_id: PK | user_id: FK->users | role_id: FK->roles | granted_at | granted_by: FK->users | deleted_at: NULL | deleted_by: NULL
  CONSTRAINT: UNIQUE (user_id, role_id) WHERE deleted_at IS NULL

### 2.21 permissions // T2, Doc 6 §2.16
  permission_id: PK | role_id: NULL FK->roles | user_id: NULL FK->users | action_category | world_id: NULL FK->world_instances // null = global grant | granted_at | granted_by: FK->users | deleted_at: NULL | deleted_by: NULL | created_at | updated_at
  CHECK: (role_id IS NOT NULL) != (user_id IS NOT NULL)  // dual-ownership, exactly one attachment point

### 2.21a DB-level rules applied to the schema above (normative, not optional)

- `PRAGMA foreign_keys = ON` on every connection, before any other statement (see §0;
  ARCHITECTURE.md holds the invariant).
- All enforced FKs are `ON DELETE RESTRICT`; no orphaned child row can ever be inserted.
  Plain-value snapshot references are NOT FKs and are never part of the deletability
  boundary (§0).
- `permissions` dual-ownership is a real `CHECK` constraint in the DDL:
  `CHECK ((role_id IS NOT NULL) != (user_id IS NOT NULL))`.
- Scope rules are real `CHECK` constraints, same shape for `schedules`,
  `cleanup_policies`, `sync_targets`:
  `CHECK ((scope = 'global' AND world_id IS NULL) OR (scope != 'global' AND world_id IS NOT NULL))`.

### 2.22 devices // T2, Doc 6 §2.13
  device_id: PK | device_name | ip_address | owner: NULL | status // unrecognized/registered | last_seen_at: NULL | deleted_at: NULL // "revoked" per Doc 6 §2.13 | deleted_by: NULL | created_at | updated_at

### 2.23 client_sessions // T2, Doc 6 §2.14
  session_id: PK // session token stored HASHED here, not in secrets (Doc 6 §2.14) | user_id: FK->users | device_id: NULL FK->devices | ip_address | expires_at | step_up_confirmed_at: NULL | last_activity_at | deleted_at: NULL // revocation marker | deleted_by: NULL | created_at

### 2.24 secrets // server-side only; never exposed to any client-facing query path
  secret_id: PK | secret_type // user_password/rcon_credential/sync_credential/session_signing | encrypted_value | associated_entity_type // user/runtime_session/manager | associated_entity_id // plain value, NOT a cross-table FK (typed union not expressible in SQLite) | rotation_of: NULL FK->secrets // rotation chain | created_at | rotated_at: NULL

### 2.25 sync_targets // T2, Doc 6 §2.17
  sync_target_id: PK | scope // global/world | world_id: NULL FK->world_instances // null when scope=global | target_type // nas/google_drive/other | config: JSON // non-secret connection details | secret_id: FK->secrets // credential ref only | enabled: INT | version: INT // Document 11 §4 | deleted_at: NULL | deleted_by: NULL | created_at | updated_at

### 2.26 sync_records // T1 — permanent, no deleted_at; job wrapper over sync_attempts, Doc 6 §2.17.1
  sync_id: PK | artifact_id: FK->backup_artifacts | sync_target_id: FK->sync_targets | operation_id: FK->operations | status // pending/succeeded/failed — DERIVED from latest sync_attempts, never set independently | started_at // first attempt's started_at | finished_at: NULL // set only at terminal status | created_at
  IDX: (artifact_id) — has-this-backup-been-synced; (status) — failed-sync surfacing

### 2.27 sync_attempts // T1 — permanent, no deleted_at; actual retry history, Doc 6 §2.17.2
  attempt_id: PK | sync_id: FK->sync_records | attempt_number: INT // strictly sequential per sync_id, from 1, no gaps | started_at | finished_at | outcome // succeeded/failed_transient/failed_permanent | error_message: NULL // NULL on success | created_at
  CONSTRAINT: UNIQUE (sync_id, attempt_number)
  RULE: every column write-once; no UPDATE ever — a new attempt is a new row (append-only
  like audit_records)

## 3. ER Diagram

Removed (ARCHITECTURE.md §14 ruling 9): the Mermaid ER diagram duplicated the FK graph
already explicit in the compact SQL shorthand in §2 — every `FK->` edge and
`ON DELETE RESTRICT` rule is stated there verbatim, and §4's constraint summary is the
normative relationship contract. If a diagram is ever wanted for human review, it can be
regenerated from §2.

## 4. Constraint & Cascade Summary

- Every *enforced* FK is `ON DELETE RESTRICT`. The deliberately-not-enforced historical
  references (`missed_run_records.schedule_id`, `audit_records.actor_user_id`/
  `actor_username_snapshot`/`device_id_snapshot`/`device_name_snapshot`,
  `secrets.associated_entity_id`) are **plain values, not FKs** — excluded from the
  deletability boundary and appearing in neither `PRAGMA foreign_key_check` nor the FK
  graph (§0). See §0 for the mandatory `PRAGMA foreign_keys = ON` and boot
  `PRAGMA foreign_key_check` sweep, and §2.21a for the DDL `CHECK` constraints that must
  appear verbatim.
- No `ON DELETE CASCADE` anywhere. World tombstoning does not cascade at DB level — the
  application soft-deletes that world's `schedules`/`cleanup_policies` explicitly as its
  own logged `ConfigEdit` step.
- Uniqueness is scoped to live rows via partial indexes (`WHERE deleted_at IS NULL`) for:
  `world_instances.display_name`, `world_instances.port`, `templates.name`,
  `java_runtimes.label`, `users.username`, `roles.name`, `role_assignments
  (user_id, role_id)`.
- **World lock is derived, not stored**: the per-world lock (Document 11 §1.1) is "is there
  an in-flight Operation for this world" — a query over `operations` (`world_id = ? AND
  status IN ('Created','Queued','Validating','Running')`), backed by the `(world_id, status)`
  index. No lock column exists on `world_instances`; the previously planned
  `current_operation_id` column was removed to avoid a circular FK with
  `operations.world_id`. The `(world_id, status)` index is therefore a hard schema
  requirement, not an optimization.
- **No circular FKs anywhere**: every FK graph here is acyclic. `operations` references
  `world_instances`; nothing on `world_instances` references `operations` back.
  Deliberately-not-enforced snapshot references (see §0) are plain values, never FKs.
- **`version`-as-optimistic-lock**: `version` columns are compare-then-write conflict
  checks in application code (ConfigurationService, Doc 8), not pure audit metadata. No
  schema-level enforcement needed.

## 5. Migration Strategy

- `schema_migrations` tracks applied migrations sequentially by integer version; applied
  in order at boot, never out of order.
- Rollback where structurally reversible (nullable column, index); destructive migrations
  (drop/rename with data) require a written up/down pair and a dry-run row-count check
  before applying — never silently destroy user data.
- No migration may hard-delete Tier 1 data. Shape changes add columns/tables and backfill;
  never drop-and-recreate.

## 6. Startup Reconciliation (Doc 6 §2.2 as queries)

1. Load `schema_migrations`, apply pending.
2. Load `world_instances` where `deleted_at IS NULL`.
3. Load `runtime_sessions` where `ended_at IS NULL`.
4. Per open session: probe for a live process. Found -> keep open, `state = running`. Not
   found -> `ended_at = now`, `end_reason = 'reconciled_missing'`, emit
   `RuntimeSessionReconciled`, `state = off` (or `error` if the world's last Operation
   didn't reach a terminal status).
5. Load `operations` where `status IN ('Queued','Validating','Running')`; re-check world
   state; mark `Failed` with `error_code = 'manager_restart_incomplete'` if unresumable,
   else `Completed`/continue.
6. Republish current snapshots to reconnecting clients (runtime/service concern).

## 7. Example Records

`world_instances`
```
world_id: "w_7f3a...", display_name: "Survival Main", template_id: "t_vanilla",
server_type: "vanilla", mc_version: "1.21.1", java_runtime_id: "jr_21",
port: 25565, addressing_strategy: "port", addressing_value: "25565",
state: "running", pre_backup_state: null,
deleted_at: null, created_at: 1753142400
```

`operations`
```
op_id: "op_9c1e...", op_type: "Backup", world_id: "w_7f3a...",
actor_type: "user", actor_user_id: "u_44a1...", idempotency_key: "backup-w7f3a-20260724",
status: "Completed", attempt: 1, intent_at: 1753142400, started_at: 1753142401,
finished_at: 1753142455, data_json: "{\"artifact_id\":\"ba_88f2\",\"size_bytes\":48213112}"
```

`missed_run_records`
```
missed_run_id: "mr_1120...", schedule_id: "sch_daily_backup_w7f3a",
schedule_name_snapshot: "Daily Backup - Survival Main", schedule_type_snapshot: "backup",
expected_run_at: 1753056000, detected_at: 1753056300,
resolution: "resolved", resolution_at: 1753059900, resolution_by: "u_44a1..."
```

## 8. Normalization Review

- 3NF except deliberate denormalization: `audit_records.actor_username_snapshot`/
  `device_id_snapshot`/`device_name_snapshot`,
  `missed_run_records.schedule_name_snapshot`/`schedule_type_snapshot`,
  `runtime_sessions.launch_args_snapshot`. Each exists so a Tier 1/permanent record's
  meaning doesn't depend on a Tier 2 row that may later change or be soft-deleted — the
  correct tradeoff for historical integrity.
- `global_settings`/`world_settings` split keeps the singleton-default shape distinct from
  the sparse-per-world-override shape, avoiding a mostly-null table.

## 9. Performance Considerations

- Indexes target the query patterns the product needs: active-world lists, per-world
  operation history, retention evaluation by category, audit filtering by actor/world/time.
- `operations` and `audit_records` are the highest-write-volume tables (every
  state-changing action touches both). TEXT IDs with no auto-increment make write
  throughput depend on index maintenance, acceptable on the documented reference hardware.
- `runtime_sessions`' partial unique index (`world_id WHERE ended_at IS NULL`) is the
  constraint doing real concurrency enforcement — what actually prevents two simultaneous
  starts from producing two open sessions, not just application locking.
