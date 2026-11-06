-- Migration 001: initial 27-table schema (Document 7 section 2).
--
-- Conventions (Doc 7 section 0), applied to every table:
--   * IDs are TEXT, app-generated (UUIDv4+); no auto-increment.
--   * Timestamps INTEGER Unix epoch seconds. Booleans INTEGER 0/1. JSON TEXT.
--   * Tier 2 soft-removal: exactly one `deleted_at INTEGER NULL` +
--     `deleted_by TEXT NULL` (user_id or 'system').
--   * Tier 1 tables (audit_records, notifications, notification_reads,
--     missed_run_records, sync_records, sync_attempts) have NO deleted_at.
--   * Every enforced FK is ON DELETE RESTRICT. No ON DELETE CASCADE anywhere.
--   * Snapshot references are plain values, deliberately NOT FKs.
--
-- SQLite requires referenced tables to exist first, so CREATE order follows
-- the FK graph, not the Doc 7 section numbering. Section numbers are kept as
-- comments for traceability.

-- ---------------------------------------------------------------------------
-- 2.3 schema_migrations
-- ---------------------------------------------------------------------------
CREATE TABLE schema_migrations (
    version    INTEGER PRIMARY KEY,          -- sequential
    name       TEXT NOT NULL,
    applied_at INTEGER NOT NULL
);

-- ---------------------------------------------------------------------------
-- 2.24 secrets — created before users: users.secret_id references it
-- ---------------------------------------------------------------------------
CREATE TABLE secrets (
    secret_id             TEXT PRIMARY KEY,
    secret_type           TEXT NOT NULL,     -- user_password/rcon_credential/sync_credential/session_signing
    encrypted_value       TEXT NOT NULL,     -- ciphertext at rest (Doc 7 section 10) — never plaintext
    associated_entity_type TEXT NOT NULL,    -- user/runtime_session/manager
    associated_entity_id  TEXT NOT NULL,     -- plain value, NOT a cross-table FK (typed union not expressible)
    rotation_of           TEXT NULL REFERENCES secrets(secret_id) ON DELETE RESTRICT,
    created_at            INTEGER NOT NULL,
    rotated_at            INTEGER NULL
);

-- ---------------------------------------------------------------------------
-- 2.18 users
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    user_id            TEXT PRIMARY KEY,     -- IMMUTABLE, never reused even past deleted_at
    username           TEXT NOT NULL,
    display_name       TEXT NULL,
    secret_id          TEXT NOT NULL REFERENCES secrets(secret_id) ON DELETE RESTRICT,
    status             TEXT NOT NULL DEFAULT 'active',  -- active/disabled/locked (deleted = deleted_at marker)
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until       INTEGER NULL,
    created_by         TEXT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    deleted_at         INTEGER NULL,
    deleted_by         TEXT NULL,
    created_at         INTEGER NOT NULL,
    updated_at         INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_users_username_live ON users(username) WHERE deleted_at IS NULL;

-- ---------------------------------------------------------------------------
-- 2.19 roles
-- ---------------------------------------------------------------------------
CREATE TABLE roles (
    role_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT NULL,
    is_system_role  INTEGER NOT NULL DEFAULT 0,  -- true for Client/Admin/Superadmin
    version         INTEGER NOT NULL DEFAULT 1,
    deleted_at      INTEGER NULL,
    deleted_by      TEXT NULL,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_roles_name_live ON roles(name) WHERE deleted_at IS NULL;

-- ---------------------------------------------------------------------------
-- 2.20 role_assignments
-- ---------------------------------------------------------------------------
CREATE TABLE role_assignments (
    assignment_id TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    role_id       TEXT NOT NULL REFERENCES roles(role_id) ON DELETE RESTRICT,
    granted_at    INTEGER NOT NULL,
    granted_by    TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    deleted_at    INTEGER NULL,
    deleted_by    TEXT NULL
);
CREATE UNIQUE INDEX ux_role_assignments_live ON role_assignments(user_id, role_id) WHERE deleted_at IS NULL;

-- ---------------------------------------------------------------------------
-- 2.22 devices
-- ---------------------------------------------------------------------------
CREATE TABLE devices (
    device_id    TEXT PRIMARY KEY,
    device_name  TEXT NOT NULL,
    ip_address   TEXT NOT NULL,
    owner        TEXT NULL,
    status       TEXT NOT NULL DEFAULT 'unrecognized',  -- unrecognized/registered
    last_seen_at INTEGER NULL,
    deleted_at   INTEGER NULL,   -- "revoked" per Doc 6 section 2.13
    deleted_by   TEXT NULL,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL
);

-- ---------------------------------------------------------------------------
-- 2.23 client_sessions — token stored HASHED here, never in secrets
-- ---------------------------------------------------------------------------
CREATE TABLE client_sessions (
    session_id           TEXT PRIMARY KEY,   -- SHA-256 of the raw session token
    user_id              TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    device_id            TEXT NULL REFERENCES devices(device_id) ON DELETE RESTRICT,
    ip_address           TEXT NOT NULL,
    expires_at           INTEGER NOT NULL,
    step_up_confirmed_at INTEGER NULL,
    last_activity_at     INTEGER NOT NULL,
    deleted_at           INTEGER NULL,       -- revocation marker
    deleted_by           TEXT NULL,
    created_at           INTEGER NOT NULL
);
CREATE INDEX idx_client_sessions_user ON client_sessions(user_id);

-- ---------------------------------------------------------------------------
-- 2.1 manager — singleton, exactly one row app-enforced
-- ---------------------------------------------------------------------------
CREATE TABLE manager (
    manager_id        TEXT PRIMARY KEY,
    deployed_version  TEXT NOT NULL,
    setup_completed   INTEGER NOT NULL DEFAULT 0,
    created_at        INTEGER NOT NULL,
    updated_at        INTEGER NOT NULL
);

-- ---------------------------------------------------------------------------
-- 2.2 global_settings — singleton defaults, 3-tier inheritance baseline
-- ---------------------------------------------------------------------------
CREATE TABLE global_settings (
    settings_id             TEXT PRIMARY KEY,
    timezone                TEXT NOT NULL,             -- IANA
    idle_countdown_seconds  INTEGER NULL,              -- 3-tier: world may override
    notification_defaults   TEXT NULL,                 -- JSON; Manager-default only, no per-world override
    minecraft_root_path     TEXT NOT NULL,
    backup_root_path        TEXT NOT NULL,
    log_root_path           TEXT NOT NULL,
    offsite_sync_defaults   TEXT NULL,                 -- JSON; non-secret defaults
    version                 INTEGER NOT NULL DEFAULT 1, -- optimistic lock (Doc 9 section 4)
    updated_at              INTEGER NOT NULL,
    updated_by              TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT
);

-- ---------------------------------------------------------------------------
-- 2.6 templates
-- ---------------------------------------------------------------------------
CREATE TABLE templates (
    template_id     TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,          -- free-text, never a closed enum
    default_version TEXT NOT NULL,
    config_defaults TEXT NOT NULL,          -- JSON; must include generic launch-command template
    source          TEXT NOT NULL,          -- built_in/imported
    deprecated      INTEGER NOT NULL DEFAULT 0,  -- distinct from deleted_at
    version         INTEGER NOT NULL DEFAULT 1,
    deleted_at      INTEGER NULL,
    deleted_by      TEXT NULL,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_templates_name_live ON templates(name) WHERE deleted_at IS NULL;

-- ---------------------------------------------------------------------------
-- 2.7 java_runtimes
-- ---------------------------------------------------------------------------
CREATE TABLE java_runtimes (
    runtime_id         TEXT PRIMARY KEY,
    label              TEXT NOT NULL,
    executable_path    TEXT NOT NULL,
    version_detected   TEXT NULL,
    status             TEXT NOT NULL DEFAULT 'registered',  -- registered/verified/missing/deprecated
    deleted_at         INTEGER NULL,
    deleted_by         TEXT NULL,
    created_at         INTEGER NOT NULL,
    updated_at         INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_java_runtimes_label_live ON java_runtimes(label) WHERE deleted_at IS NULL;

-- ---------------------------------------------------------------------------
-- 2.4 world_instances — tombstoned, never hard-deleted in practice
-- ---------------------------------------------------------------------------
CREATE TABLE world_instances (
    world_id           TEXT PRIMARY KEY,      -- IMMUTABLE, forever even past deleted_at
    display_name       TEXT NOT NULL,
    template_id        TEXT NOT NULL REFERENCES templates(template_id) ON DELETE RESTRICT,
    server_type        TEXT NOT NULL,         -- vanilla/forge/fabric/paper/...
    mc_version         TEXT NOT NULL,
    java_runtime_id    TEXT NOT NULL REFERENCES java_runtimes(runtime_id) ON DELETE RESTRICT,
    port               INTEGER NOT NULL,
    addressing_strategy TEXT NOT NULL,        -- subdomain/port/path
    addressing_value   TEXT NOT NULL,
    state              TEXT NOT NULL,         -- off/queued/starting/running/stopping/restoring/backing_up/crashed/error/eula_required
    pre_backup_state   TEXT NULL,             -- only while state=backing_up; restricted to {off, running}
    launch_args        TEXT NULL,             -- JSON; editable only while state=off
    metadata_version   INTEGER NOT NULL DEFAULT 1,  -- Doc 9 section 4, metadata fields only
    deleted_at         INTEGER NULL,
    deleted_by         TEXT NULL,
    created_at         INTEGER NOT NULL,
    updated_at         INTEGER NOT NULL
);
CREATE INDEX idx_world_instances_state ON world_instances(state);
CREATE INDEX idx_world_instances_deleted ON world_instances(deleted_at) WHERE deleted_at IS NULL;
CREATE INDEX idx_world_instances_display_name ON world_instances(display_name);
CREATE UNIQUE INDEX ux_world_instances_display_name_live ON world_instances(display_name) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX ux_world_instances_port_live ON world_instances(port) WHERE deleted_at IS NULL;

-- ---------------------------------------------------------------------------
-- 2.5 world_settings — row exists only when a world overrides global_settings
-- ---------------------------------------------------------------------------
CREATE TABLE world_settings (
    world_id                TEXT PRIMARY KEY REFERENCES world_instances(world_id) ON DELETE RESTRICT,
    minecraft_root_override TEXT NULL,
    backup_root_override    TEXT NULL,
    log_root_override       TEXT NULL,
    offsite_sync_override   TEXT NULL,        -- JSON
    idle_countdown_override INTEGER NULL,     -- completes 3-tier inheritance
    version                 INTEGER NOT NULL DEFAULT 1,
    updated_at              INTEGER NOT NULL,
    updated_by              TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT
);

-- ---------------------------------------------------------------------------
-- 2.21 permissions — dual-ownership CHECK (verbatim, Doc 7 section 2.21a)
-- ---------------------------------------------------------------------------
CREATE TABLE permissions (
    permission_id   TEXT PRIMARY KEY,
    role_id         TEXT NULL REFERENCES roles(role_id) ON DELETE RESTRICT,
    user_id         TEXT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    action_category TEXT NOT NULL,
    world_id        TEXT NULL REFERENCES world_instances(world_id) ON DELETE RESTRICT,
    granted_at      INTEGER NOT NULL,
    granted_by      TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    deleted_at      INTEGER NULL,
    deleted_by      TEXT NULL,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    CHECK ((role_id IS NOT NULL) != (user_id IS NOT NULL))
);
CREATE INDEX idx_permissions_entity ON permissions(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX idx_permissions_role ON permissions(role_id) WHERE role_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2.8 runtime_sessions — one open session per world, schema-enforced
-- ---------------------------------------------------------------------------
CREATE TABLE runtime_sessions (
    session_id           TEXT PRIMARY KEY,
    world_id             TEXT NOT NULL REFERENCES world_instances(world_id) ON DELETE RESTRICT,
    started_at           INTEGER NOT NULL,    -- set only at confirmed running
    ended_at             INTEGER NULL,
    end_reason           TEXT NULL,           -- graceful_stop/forced_stop/crashed/emergency_stop/reconciled_missing
    rcon_secret_id       TEXT NOT NULL REFERENCES secrets(secret_id) ON DELETE RESTRICT,
    port_used            INTEGER NOT NULL,
    java_runtime_id      TEXT NOT NULL REFERENCES java_runtimes(runtime_id) ON DELETE RESTRICT,  -- historical
    launch_args_snapshot TEXT NOT NULL,       -- JSON captured at launch; independent of later edits
    created_at           INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_runtime_sessions_open ON runtime_sessions(world_id) WHERE ended_at IS NULL;

-- ---------------------------------------------------------------------------
-- 2.9 operations — durable command-plane record; immutable except status
-- ---------------------------------------------------------------------------
CREATE TABLE operations (
    op_id                   TEXT PRIMARY KEY,
    op_type                 TEXT NOT NULL,    -- CreateWorld/Start/Stop/Kill/Backup/Restore/Cleanup/Sync/ConfigEdit/CrashDetected/DeleteWorld
    world_id                TEXT NULL REFERENCES world_instances(world_id) ON DELETE RESTRICT,  -- null = manager-global
    actor_type              TEXT NOT NULL,    -- user/system
    actor_user_id           TEXT NULL REFERENCES users(user_id) ON DELETE RESTRICT,  -- null when actor_type=system
    idempotency_key         TEXT NULL,
    status                  TEXT NOT NULL,    -- Created/Queued/Validating/Running/Completed/Failed/Cancelled/TimedOut
    checkpoint              TEXT NULL,        -- JSON
    attempt                 INTEGER NOT NULL DEFAULT 1,
    compensates_operation_id TEXT NULL REFERENCES operations(op_id) ON DELETE RESTRICT,  -- compensating ops only
    intent_at               INTEGER NOT NULL,
    started_at              INTEGER NULL,
    finished_at             INTEGER NULL,
    error_code              TEXT NULL,
    message                 TEXT NULL,
    data_json               TEXT NULL,        -- JSON; type-specific payload
    created_at              INTEGER NOT NULL,
    updated_at              INTEGER NOT NULL
);
-- REQUIRED: backs the derived world lock (Doc 9 section 1.1).
CREATE INDEX idx_operations_world_status ON operations(world_id, status);
-- Idempotency, scoped by op_type (partial unique over non-null keys).
CREATE UNIQUE INDEX ux_operations_idempotency ON operations(op_type, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX idx_operations_status ON operations(status);

-- ---------------------------------------------------------------------------
-- 2.10 backup_artifacts — created-on-success-only
-- ---------------------------------------------------------------------------
CREATE TABLE backup_artifacts (
    artifact_id    TEXT PRIMARY KEY,
    world_id       TEXT NULL REFERENCES world_instances(world_id) ON DELETE RESTRICT,  -- NULL = ManagerBackup
    category       TEXT NOT NULL,    -- session_end/manual/scheduled/pre_restore/emergency/manager_config
    storage_path   TEXT NOT NULL,
    size_bytes     INTEGER NOT NULL,
    checksum       TEXT NOT NULL,    -- SHA-256 over full artifact
    suspect        INTEGER NOT NULL DEFAULT 0,  -- set when a restore fails structural validation
    operation_id   TEXT NOT NULL REFERENCES operations(op_id) ON DELETE RESTRICT,
    deleted_at     INTEGER NULL,     -- soft; file removed, row retained
    deleted_by     TEXT NULL,
    created_at     INTEGER NOT NULL
);
-- Shape retention keep-newest-N-per-category needs.
CREATE INDEX idx_backup_artifacts_retention ON backup_artifacts(world_id, category, created_at);

-- ---------------------------------------------------------------------------
-- 2.11 restore_history — immutable append-only outcome record
-- ---------------------------------------------------------------------------
CREATE TABLE restore_history (
    restore_id              TEXT PRIMARY KEY,
    world_id                TEXT NOT NULL REFERENCES world_instances(world_id) ON DELETE RESTRICT,
    operation_id            TEXT NOT NULL REFERENCES operations(op_id) ON DELETE RESTRICT,
    source_artifact_id      TEXT NULL REFERENCES backup_artifacts(artifact_id) ON DELETE RESTRICT,  -- null = raw snapshot path
    pre_restore_artifact_id TEXT NOT NULL REFERENCES backup_artifacts(artifact_id) ON DELETE RESTRICT,  -- mandatory pre-restore backup
    operator_user_id        TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    outcome                 TEXT NOT NULL,    -- success/failed/reverted
    rollback_of_restore_id  TEXT NULL REFERENCES restore_history(restore_id) ON DELETE RESTRICT,  -- corrective restore self-ref
    started_at              INTEGER NOT NULL,
    finished_at             INTEGER NULL,
    created_at              INTEGER NOT NULL
);

-- ---------------------------------------------------------------------------
-- 2.12 schedules — scope CHECK (verbatim, Doc 7 section 2.21a)
-- ---------------------------------------------------------------------------
CREATE TABLE schedules (
    schedule_id      TEXT PRIMARY KEY,
    scope            TEXT NOT NULL,           -- global/world
    world_id         TEXT NULL REFERENCES world_instances(world_id) ON DELETE RESTRICT,  -- null when scope=global
    schedule_type    TEXT NOT NULL,           -- backup/cleanup/maintenance
    interval_spec    TEXT NOT NULL,           -- JSON: daily/weekly/monthly/every_n_days + params
    time_of_day      TEXT NOT NULL,
    enabled          INTEGER NOT NULL DEFAULT 1,
    version          INTEGER NOT NULL DEFAULT 1,
    last_changed_by  TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    last_changed_at  INTEGER NOT NULL,
    deleted_at       INTEGER NULL,
    deleted_by       TEXT NULL,
    created_at       INTEGER NOT NULL,
    CHECK ((scope = 'global' AND world_id IS NULL) OR (scope <> 'global' AND world_id IS NOT NULL))
);
CREATE INDEX idx_schedules_world ON schedules(world_id) WHERE world_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2.13 missed_run_records — Tier 1, permanent, no deleted_at
-- ---------------------------------------------------------------------------
CREATE TABLE missed_run_records (
    missed_run_id          TEXT PRIMARY KEY,
    schedule_id            TEXT NOT NULL,     -- plain value, NOT an FK (snapshot rationale, Doc 7 section 0)
    schedule_name_snapshot TEXT NOT NULL,
    schedule_type_snapshot TEXT NOT NULL,
    expected_run_at        INTEGER NOT NULL,
    detected_at            INTEGER NOT NULL,
    resolution             TEXT NOT NULL DEFAULT 'pending',  -- pending/resolved/ignored
    resolution_at          INTEGER NULL,
    resolution_by          TEXT NULL,         -- user_id, plain value, NOT an FK
    created_at             INTEGER NOT NULL
);
CREATE INDEX idx_missed_run_records_resolution ON missed_run_records(resolution);

-- ---------------------------------------------------------------------------
-- 2.14 cleanup_policies — scope CHECK (verbatim); age floor 3 app-enforced
-- ---------------------------------------------------------------------------
CREATE TABLE cleanup_policies (
    policy_id        TEXT PRIMARY KEY,
    scope            TEXT NOT NULL,           -- global/world
    world_id         TEXT NULL REFERENCES world_instances(world_id) ON DELETE RESTRICT,
    age_rule_days    INTEGER NOT NULL,        -- floor 3, app-enforced
    space_rule_pct   INTEGER NULL,            -- 0 < pct <= 90 when set
    count_rules      TEXT NULL,               -- JSON; per-category floors, each >= 3
    schedule_id      TEXT NULL REFERENCES schedules(schedule_id) ON DELETE RESTRICT,
    version          INTEGER NOT NULL DEFAULT 1,
    last_changed_by  TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    last_changed_at  INTEGER NOT NULL,
    deleted_at       INTEGER NULL,
    deleted_by       TEXT NULL,
    created_at       INTEGER NOT NULL,
    CHECK ((scope = 'global' AND world_id IS NULL) OR (scope <> 'global' AND world_id IS NOT NULL)),
    CHECK (space_rule_pct IS NULL OR (space_rule_pct > 0 AND space_rule_pct <= 90))
);
CREATE INDEX idx_cleanup_policies_world ON cleanup_policies(world_id) WHERE world_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2.15 notifications — Tier 1, permanent, never deletable
-- ---------------------------------------------------------------------------
CREATE TABLE notifications (
    notification_id       TEXT PRIMARY KEY,
    category              TEXT NOT NULL,
    severity              TEXT NOT NULL,      -- critical/high/normal/informational
    message               TEXT NOT NULL,
    related_operation_id  TEXT NULL REFERENCES operations(op_id) ON DELETE RESTRICT,
    related_world_id      TEXT NULL REFERENCES world_instances(world_id) ON DELETE RESTRICT,
    requires_action       INTEGER NOT NULL DEFAULT 0,
    action_taken          TEXT NULL,
    created_at            INTEGER NOT NULL
);
CREATE INDEX idx_notifications_created ON notifications(created_at);

-- ---------------------------------------------------------------------------
-- 2.16 notification_reads — Tier 1, per-user read/dismiss
-- ---------------------------------------------------------------------------
CREATE TABLE notification_reads (
    notification_id TEXT NOT NULL REFERENCES notifications(notification_id) ON DELETE RESTRICT,
    user_id         TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    read_at         INTEGER NULL,
    dismissed_at    INTEGER NULL,             -- hides from THIS user's dropdown only
    PRIMARY KEY (notification_id, user_id)
);

-- ---------------------------------------------------------------------------
-- 2.17 audit_records — Tier 1, permanent, append-only, insert-only
-- ---------------------------------------------------------------------------
CREATE TABLE audit_records (
    audit_id              TEXT PRIMARY KEY,
    event_type            TEXT NOT NULL,
    actor_type            TEXT NOT NULL,      -- user/system
    actor_user_id         TEXT NULL,          -- plain value, NOT an FK — survives soft-deleted User
    actor_username_snapshot TEXT NULL,        -- captured at write time (Doc 6 section 0.1)
    device_id_snapshot    TEXT NULL,          -- plain value, not an FK
    device_name_snapshot  TEXT NULL,
    ip_snapshot           TEXT NULL,
    operation_id          TEXT NULL REFERENCES operations(op_id) ON DELETE RESTRICT,
    world_id              TEXT NULL REFERENCES world_instances(world_id) ON DELETE RESTRICT,
    payload               TEXT NULL,          -- JSON
    annotation_of         TEXT NULL REFERENCES audit_records(audit_id) ON DELETE RESTRICT,  -- corrections/acknowledgements
    created_at            INTEGER NOT NULL
);
CREATE INDEX idx_audit_records_created ON audit_records(created_at);
CREATE INDEX idx_audit_records_actor ON audit_records(actor_user_id);
CREATE INDEX idx_audit_records_world ON audit_records(world_id);

-- Immutability: audit_records is append-only. No UPDATE/DELETE ever —
-- enforced at the database, not just service convention (Doc 6 section 2.9,
-- Doc 7 section 2.17; Doc 11 security suite).
CREATE TRIGGER trg_audit_records_no_update
BEFORE UPDATE ON audit_records
BEGIN
    SELECT RAISE(ABORT, 'audit_records is append-only — UPDATE forbidden');
END;

CREATE TRIGGER trg_audit_records_no_delete
BEFORE DELETE ON audit_records
BEGIN
    SELECT RAISE(ABORT, 'audit_records is append-only — DELETE forbidden');
END;

-- ---------------------------------------------------------------------------
-- 2.25 sync_targets — scope CHECK (verbatim)
-- ---------------------------------------------------------------------------
CREATE TABLE sync_targets (
    sync_target_id TEXT PRIMARY KEY,
    scope          TEXT NOT NULL,             -- global/world
    world_id       TEXT NULL REFERENCES world_instances(world_id) ON DELETE RESTRICT,
    target_type    TEXT NOT NULL,             -- nas/google_drive/other
    config         TEXT NOT NULL,             -- JSON; non-secret connection details
    secret_id      TEXT NOT NULL REFERENCES secrets(secret_id) ON DELETE RESTRICT,  -- credential ref only
    enabled        INTEGER NOT NULL DEFAULT 1,
    version        INTEGER NOT NULL DEFAULT 1,
    deleted_at     INTEGER NULL,
    deleted_by     TEXT NULL,
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL,
    CHECK ((scope = 'global' AND world_id IS NULL) OR (scope <> 'global' AND world_id IS NOT NULL))
);
CREATE INDEX idx_sync_targets_world ON sync_targets(world_id) WHERE world_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2.26 sync_records — Tier 1, job wrapper over immutable sync_attempts
-- ---------------------------------------------------------------------------
CREATE TABLE sync_records (
    sync_id        TEXT PRIMARY KEY,
    artifact_id    TEXT NOT NULL REFERENCES backup_artifacts(artifact_id) ON DELETE RESTRICT,
    sync_target_id TEXT NOT NULL REFERENCES sync_targets(sync_target_id) ON DELETE RESTRICT,
    operation_id   TEXT NOT NULL REFERENCES operations(op_id) ON DELETE RESTRICT,
    status         TEXT NOT NULL,             -- pending/succeeded/failed — DERIVED from latest sync_attempts
    started_at     INTEGER NOT NULL,          -- first attempt's started_at
    finished_at    INTEGER NULL,
    created_at     INTEGER NOT NULL
);
CREATE INDEX idx_sync_records_artifact ON sync_records(artifact_id);   -- has-this-backup-been-synced
CREATE INDEX idx_sync_records_status ON sync_records(status);          -- failed-sync surfacing

-- ---------------------------------------------------------------------------
-- 2.27 sync_attempts — Tier 1, write-once rows, never updated
-- ---------------------------------------------------------------------------
CREATE TABLE sync_attempts (
    attempt_id      TEXT PRIMARY KEY,
    sync_id         TEXT NOT NULL REFERENCES sync_records(sync_id) ON DELETE RESTRICT,
    attempt_number  INTEGER NOT NULL,         -- strictly sequential per sync_id, from 1, no gaps
    started_at      INTEGER NOT NULL,
    finished_at     INTEGER NULL,
    outcome         TEXT NOT NULL,            -- succeeded/failed_transient/failed_permanent
    error_message   TEXT NULL,                -- NULL on success
    created_at      INTEGER NOT NULL,
    UNIQUE (sync_id, attempt_number)
);

-- Immutability: sync_attempts rows are write-once (Doc 6 section 2.17.2).
CREATE TRIGGER trg_sync_attempts_no_update
BEFORE UPDATE ON sync_attempts
BEGIN
    SELECT RAISE(ABORT, 'sync_attempts is write-once — UPDATE forbidden');
END;

CREATE TRIGGER trg_sync_attempts_no_delete
BEFORE DELETE ON sync_attempts
BEGIN
    SELECT RAISE(ABORT, 'sync_attempts is write-once — DELETE forbidden');
END;
