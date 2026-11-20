-- Cleanup policy extensions for stale-backup and historical-log retention.
ALTER TABLE cleanup_policies
    ADD COLUMN stale_session_threshold INTEGER NOT NULL DEFAULT 7
    CHECK (stale_session_threshold > 0);

ALTER TABLE cleanup_policies
    ADD COLUMN log_retention_days INTEGER NULL
    CHECK (log_retention_days IS NULL OR log_retention_days >= 3);

-- A dedicated timestamp distinguishes stale-backup tombstones from direct
-- user deletions, whose files are removed immediately by the existing flow.
ALTER TABLE backup_artifacts
    ADD COLUMN stale_tombstoned_at INTEGER NULL;

CREATE INDEX idx_backup_artifacts_stale_tombstones
    ON backup_artifacts(stale_tombstoned_at)
    WHERE stale_tombstoned_at IS NOT NULL;
