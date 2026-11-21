-- Document 6/7 require restore outcomes and sync attempts to remain append-only
-- history rather than mutable audit-like records.
CREATE TRIGGER trg_restore_history_no_update
BEFORE UPDATE ON restore_history
BEGIN
    SELECT RAISE(ABORT, 'restore_history is append-only - UPDATE forbidden');
END;

CREATE TRIGGER trg_restore_history_no_delete
BEFORE DELETE ON restore_history
BEGIN
    SELECT RAISE(ABORT, 'restore_history is append-only - DELETE forbidden');
END;

-- Sync attempts must be numbered consecutively from 1 for each sync record.
-- The existing UNIQUE constraint prevents duplicates but not gaps.
CREATE TRIGGER trg_sync_attempts_sequential_insert
BEFORE INSERT ON sync_attempts
WHEN NEW.attempt_number != COALESCE(
    (SELECT MAX(attempt_number) + 1 FROM sync_attempts WHERE sync_id = NEW.sync_id),
    1
)
BEGIN
    SELECT RAISE(ABORT, 'sync_attempts must be strictly sequential');
END;
