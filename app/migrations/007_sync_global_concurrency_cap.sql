ALTER TABLE global_settings
    ADD COLUMN sync_global_concurrency_cap INTEGER NOT NULL DEFAULT 2
    CHECK (sync_global_concurrency_cap > 0);
