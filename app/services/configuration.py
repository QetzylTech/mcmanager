"""Effective configuration and versioned, durable configuration edits."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.domain.value_objects import (
    ActorType,
    ConfigEditEntity,
    OperationStatus,
    OperationType,
)
from app.infrastructure.sqlite.connection import SqliteStore
from app.ports.clock import Clock
from app.services.operations import OperationInput, OperationService


class ConfigurationConflictError(Exception):
    """Raised when submitted version is stale."""


VERSION_TABLES = {
    ConfigEditEntity.SCHEDULES: ('schedules', 'schedule_id', 'version'),
    ConfigEditEntity.CLEANUP_POLICIES: ('cleanup_policies', 'policy_id', 'version'),
    ConfigEditEntity.GLOBAL_SETTINGS: ('global_settings', 'settings_id', 'version'),
    ConfigEditEntity.WORLD_SETTINGS: ('world_settings', 'world_id', 'version'),
    ConfigEditEntity.TEMPLATES: ('templates', 'template_id', 'version'),
    ConfigEditEntity.ROLES: ('roles', 'role_id', 'version'),
    ConfigEditEntity.SYNC_TARGETS: ('sync_targets', 'sync_target_id', 'version'),
    ConfigEditEntity.WORLD_INSTANCES: ('world_instances', 'world_id', 'metadata_version'),
}


@dataclass(frozen=True)
class VersionedUpdate:
    entity: ConfigEditEntity
    row_id: str
    expected_version: int
    fields: dict[str, Any]
    actor_type: ActorType = ActorType.SYSTEM
    actor_user_id: str | None = None


class ConfigurationService:
    """Compare-submitted-version-before-write for every versioned config row."""

    def __init__(
        self,
        store: SqliteStore,
        clock: Clock,
        operations: OperationService | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._operations = operations or OperationService(store, clock)

    def resolve_effective(self, world_id: str) -> dict[str, Any]:
        """Resolve singleton defaults and nullable per-world overrides."""
        connection = self._store.reader()
        global_row = connection.execute(
            "SELECT * FROM global_settings ORDER BY settings_id LIMIT 1"
        ).fetchone()
        if global_row is None:
            raise KeyError("global_settings")
        world_row = connection.execute(
            "SELECT * FROM world_settings WHERE world_id = ?", (world_id,)
        ).fetchone()

        def decode_json(value: Any) -> Any:
            return json.loads(value) if value is not None else None

        effective = {
            "timezone": global_row["timezone"],
            "idle_countdown_seconds": global_row["idle_countdown_seconds"],
            "notification_defaults": decode_json(
                global_row["notification_defaults"]
            ),
            "minecraft_root_path": global_row["minecraft_root_path"],
            "backup_root_path": global_row["backup_root_path"],
            "log_root_path": global_row["log_root_path"],
            "offsite_sync_defaults": decode_json(
                global_row["offsite_sync_defaults"]
            ),
        }
        if world_row is None:
            return effective

        overrides = {
            "idle_countdown_seconds": "idle_countdown_override",
            "minecraft_root_path": "minecraft_root_override",
            "backup_root_path": "backup_root_override",
            "log_root_path": "log_root_override",
            "offsite_sync_defaults": "offsite_sync_override",
        }
        for effective_key, override_key in overrides.items():
            override_value = world_row[override_key]
            if override_value is not None:
                effective[effective_key] = (
                    decode_json(override_value)
                    if effective_key == "offsite_sync_defaults"
                    else override_value
                )
        return effective

    def update_versioned(self, update: VersionedUpdate) -> dict[str, Any]:
        if update.entity not in VERSION_TABLES:
            raise ValueError(f'entity is not versioned: {update.entity.value}')
        table, key_column, version_column = VERSION_TABLES[update.entity]
        if not update.fields:
            raise ValueError('update requires at least one field')
        disallowed = {key_column, version_column}
        if disallowed.intersection(update.fields):
            raise ValueError('cannot update identity or version columns directly')

        world_id = (
            update.row_id
            if update.entity
            in (ConfigEditEntity.WORLD_SETTINGS, ConfigEditEntity.WORLD_INSTANCES)
            else None
        )
        operation = self._operations.create(
            OperationInput(
                op_type=OperationType.CONFIG_EDIT,
                actor_type=update.actor_type,
                actor_user_id=update.actor_user_id,
                world_id=world_id,
                data={
                    "entity": update.entity.value,
                    "row_id": update.row_id,
                    "before": {},
                    "after": {},
                },
            ),
            initial_status=OperationStatus.QUEUED,
            allow_world_conflict=True,
        )
        self._operations.transition(operation["op_id"], OperationStatus.RUNNING)
        connection = self._store.writer()
        now = int(self._clock.now())
        payload: dict[str, Any] = {
            "entity": update.entity.value,
            "row_id": update.row_id,
            "before": {},
            "after": {},
        }
        try:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute(
                f'SELECT * FROM {table} WHERE {key_column} = ?', (update.row_id,)
            ).fetchone()
            if row is None:
                raise KeyError(update.row_id)
            payload["before"] = {
                column: row[column] for column in update.fields
            }
            payload["after"] = dict(update.fields)
            if row[version_column] != update.expected_version:
                raise ConfigurationConflictError('CONFIG_VERSION_CONFLICT')

            fields = dict(update.fields)
            if 'updated_at' in row and 'updated_at' not in fields:
                fields['updated_at'] = now
            if 'last_changed_at' in row and 'last_changed_at' not in fields:
                fields['last_changed_at'] = now
            assignments = [f'{column} = ?' for column in fields]
            assignments.append(f'{version_column} = {version_column} + 1')
            values = list(fields.values())
            values.append(update.row_id)
            connection.execute(
                f"UPDATE {table} SET {', '.join(assignments)} WHERE {key_column} = ?",
                values,
            )
            updated = connection.execute(
                f'SELECT * FROM {table} WHERE {key_column} = ?', (update.row_id,)
            ).fetchone()
            connection.commit()
            self._operations.transition(
                operation["op_id"],
                OperationStatus.COMPLETED,
                data=payload,
            )
            return dict(updated)
        except Exception as exc:
            connection.rollback()
            if isinstance(exc, ConfigurationConflictError):
                error_code = "CONFIG_VERSION_CONFLICT"
            else:
                error_code = "CONFIG_EDIT_FAILED"
            self._operations.transition(
                operation["op_id"],
                OperationStatus.FAILED,
                error_code=error_code,
                message=str(exc),
                data=payload,
            )
            raise
