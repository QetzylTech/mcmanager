from __future__ import annotations


def seed_world(store, *, world_id: str = 'gate3_world') -> str:
    now = 1_700_000_000
    connection = store.writer()
    connection.execute(
        "INSERT INTO secrets VALUES ('gate3_secret', 'user_password', 'x', 'user', "
        "'gate3_admin', NULL, ?, NULL)",
        (now,),
    )
    connection.execute(
        """
        INSERT INTO users (
            user_id, username, display_name, secret_id, status, failed_login_count,
            locked_until, created_by, deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('gate3_admin', 'gate3_admin', NULL, 'gate3_secret', 'active', 0,
                  NULL, NULL, NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    connection.execute(
        """
        INSERT INTO templates (
            template_id, name, category, default_version, config_defaults, source,
            deprecated, version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('gate3_template', 'Vanilla', 'vanilla', '1.21', '{}', 'built_in',
                  0, 1, NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    connection.execute(
        """
        INSERT INTO java_runtimes (
            runtime_id, label, executable_path, version_detected, status,
            deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('gate3_java', 'Java 21', 'java', '21', 'verified', NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    connection.execute(
        """
        INSERT INTO world_instances (
            world_id, display_name, template_id, server_type, mc_version, java_runtime_id,
            port, addressing_strategy, addressing_value, state, pre_backup_state,
            launch_args, metadata_version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES (?, 'Gate 3', 'gate3_template', 'vanilla', '1.21', 'gate3_java',
                  25565, 'port', '25565', 'off', NULL, '{}', 1, NULL, NULL, ?, ?)
        """,
        (world_id, now, now),
    )
    connection.commit()
    return world_id
