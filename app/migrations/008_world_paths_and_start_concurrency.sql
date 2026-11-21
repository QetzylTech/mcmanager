ALTER TABLE world_instances
    ADD COLUMN world_directory TEXT NULL;

ALTER TABLE global_settings
    ADD COLUMN max_concurrent_world_starts INTEGER NULL DEFAULT 3
    CHECK (max_concurrent_world_starts IS NULL OR max_concurrent_world_starts >= 0);
