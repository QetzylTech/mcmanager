CREATE TABLE server_properties_versions (
    world_id   TEXT PRIMARY KEY REFERENCES world_instances(world_id) ON DELETE RESTRICT,
    version    INTEGER NOT NULL DEFAULT 1,
    updated_at INTEGER NOT NULL,
    updated_by TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT
);
