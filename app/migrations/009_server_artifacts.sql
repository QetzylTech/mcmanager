CREATE TABLE server_artifacts (
    server_artifact_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL CHECK (provider IN (
        'vanilla', 'paper', 'purpur', 'fabric', 'forge', 'neoforge'
    )),
    mc_version TEXT NOT NULL,
    build TEXT NOT NULL,
    artifact_kind TEXT NOT NULL CHECK (artifact_kind IN (
        'runnable_server', 'launcher', 'installer'
    )),
    source_url TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    upstream_checksums TEXT NULL,
    verified_at INTEGER NOT NULL,
    downloaded_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'available' CHECK (status IN ('available', 'retired')),
    deleted_at INTEGER NULL,
    deleted_by TEXT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (deleted_by) REFERENCES users(user_id) ON DELETE RESTRICT
);
CREATE INDEX idx_server_artifacts_provider_version_build
    ON server_artifacts(provider, mc_version, build, status);
CREATE INDEX idx_server_artifacts_sha256 ON server_artifacts(sha256);
CREATE UNIQUE INDEX idx_one_server_artifact_migration_in_flight
    ON operations(op_type)
    WHERE op_type = 'ServerArtifactMigration'
      AND status IN ('Queued', 'Validating', 'Running');

ALTER TABLE world_instances
    ADD COLUMN server_artifact_id TEXT NULL
    REFERENCES server_artifacts(server_artifact_id) ON DELETE RESTRICT;
ALTER TABLE world_instances
    ADD COLUMN server_artifact_provenance_json TEXT NULL;

ALTER TABLE templates
    ADD COLUMN compatibility_constraints TEXT NULL;
UPDATE templates
SET compatibility_constraints = json_object(
    'providers', json_array(lower(category)),
    'mc_versions', json_array(default_version)
)
WHERE compatibility_constraints IS NULL;

CREATE TABLE server_artifact_migration_runs (
    operation_id TEXT PRIMARY KEY REFERENCES operations(op_id) ON DELETE RESTRICT,
    source_root_kind TEXT NOT NULL CHECK (
        source_root_kind IN ('legacy_app_data', 'configured_artifact_root')
    ),
    source_manifest_sha256 TEXT NOT NULL,
    backup_relative_path TEXT NOT NULL,
    staging_relative_path TEXT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('running', 'succeeded', 'failed', 'rolled_back')),
    unresolved_count INTEGER NOT NULL DEFAULT 0 CHECK (unresolved_count >= 0),
    orphan_count INTEGER NOT NULL DEFAULT 0 CHECK (orphan_count >= 0),
    rollback_status TEXT NOT NULL CHECK (
        rollback_status IN ('not_needed', 'pending', 'completed', 'failed')
    ),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE server_artifact_migration_entries (
    entry_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL
        REFERENCES server_artifact_migration_runs(operation_id) ON DELETE RESTRICT,
    entry_kind TEXT NOT NULL CHECK (entry_kind IN ('manifest_entry', 'orphan_file')),
    source_index INTEGER NOT NULL CHECK (source_index >= 0),
    source_name TEXT NOT NULL,
    relative_path TEXT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('imported', 'unresolved', 'orphan')),
    reason_code TEXT NULL,
    candidate_count INTEGER NULL CHECK (candidate_count IS NULL OR candidate_count >= 0),
    size_bytes INTEGER NULL CHECK (size_bytes IS NULL OR size_bytes >= 0),
    sha256 TEXT NULL,
    server_artifact_id TEXT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE (operation_id, entry_kind, source_index)
);
CREATE INDEX idx_server_artifact_migration_entries_review
    ON server_artifact_migration_entries(operation_id, outcome, source_index);
