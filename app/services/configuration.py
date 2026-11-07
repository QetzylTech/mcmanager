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
from app.ports.clock import Clock
from app.ports.persistence import PersistencePort
from app.services.operations import OperationInput, OperationService


class ConfigurationConflictError(Exception):
    """Raised when submitted version is stale."""


VERSION_TABLES = {
    ConfigEditEntity.SCHEDULES: ('schedules', 'schedule_id', 'version'),
    ConfigEditEntity.CLEANUP_POLICIES: ('cleanup_policies', 'policy_id', 'version'),
    ConfigEditEntity.GLOBAL_SETTINGS: ('global_settings', 'settings_id', 'version'),
    ConfigEditEntity.WORLD_SETTINGS: ('world_settings', 'world_id', 'version'),
    ConfigEditEntity.TEMPLATES: ('templates', 'template_id', 'version'),
    ConfigEditEntity.JAVA_RUNTIMES: ('java_runtimes', 'runtime_id', 'version'),
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
        store: PersistencePort,
        clock: Clock,
        operations: OperationService | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._operations = operations or OperationService(store, clock)

    def resolve_effective(self, world_id: str) -> dict[str, Any]:
        """Resolve singleton defaults and nullable per-world overrides."""
        global_settings = self.resolve_global()
        world_settings = self.resolve_world(world_id)

        effective = {
            key: global_settings[key]
            for key in (
                "timezone",
                "idle_countdown_seconds",
                "notification_defaults",
                "minecraft_root_path",
                "backup_root_path",
                "log_root_path",
                "offsite_sync_defaults",
            )
        }
        if world_settings is None:
            return effective

        overrides = {
            "idle_countdown_seconds": "idle_countdown_override",
            "minecraft_root_path": "minecraft_root_override",
            "backup_root_path": "backup_root_override",
            "log_root_path": "log_root_override",
            "offsite_sync_defaults": "offsite_sync_override",
        }
        for effective_key, override_key in overrides.items():
            override_value = world_settings[override_key]
            if override_value is not None:
                effective[effective_key] = override_value
        return effective

    def resolve_global(self) -> dict[str, Any]:
        """Return the manager-wide settings baseline, including its version."""
        row = self._store.reader().execute(
            "SELECT * FROM global_settings ORDER BY settings_id LIMIT 1"
        ).fetchone()
        if row is None:
            raise KeyError("global_settings")
        settings = dict(row)
        for column in ("notification_defaults", "offsite_sync_defaults"):
            if settings[column] is not None:
                settings[column] = json.loads(settings[column])
        return settings

    def resolve_world(self, world_id: str) -> dict[str, Any] | None:
        """Return a world's stored overrides, decoding JSON-valued settings."""
        row = self._store.reader().execute(
            "SELECT * FROM world_settings WHERE world_id = ?", (world_id,)
        ).fetchone()
        if row is None:
            return None

        settings = dict(row)
        if settings["offsite_sync_override"] is not None:
            settings["offsite_sync_override"] = json.loads(
                settings["offsite_sync_override"]
            )
        return settings

    def update_versioned(self, update: VersionedUpdate) -> dict[str, Any]:
        updated, _ = self.update_versioned_with_operation(update)
        return updated

    def update_versioned_with_operation(
        self, update: VersionedUpdate
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if update.entity not in VERSION_TABLES:
            raise ValueError(f'entity is not versioned: {update.entity.value}')
        table, key_column, version_column = VERSION_TABLES[update.entity]
        if not update.fields:
            raise ValueError('update requires at least one field')
        disallowed = {key_column, version_column}
        if disallowed.intersection(update.fields):
            raise ValueError('cannot update identity or version columns directly')

        table_columns = {
            row['name']
            for row in self._store.reader().execute(f'PRAGMA table_info({table})')
        }
        unknown = set(update.fields).difference(table_columns)
        if unknown:
            raise ValueError(f'unknown fields for {update.entity.value}: {sorted(unknown)}')

        connection = self._store.writer()
        current = connection.execute(
            f'SELECT * FROM {table} WHERE {key_column} = ?', (update.row_id,)
        ).fetchone()
        creating_world_override = (
            update.entity is ConfigEditEntity.WORLD_SETTINGS
            and current is None
            and update.expected_version == 0
        )
        if current is None and not creating_world_override:
            if update.entity is ConfigEditEntity.WORLD_SETTINGS:
                raise ConfigurationConflictError('CONFIG_VERSION_CONFLICT')
            raise KeyError(update.row_id)
        if current is not None and current[version_column] != update.expected_version:
            raise ConfigurationConflictError('CONFIG_VERSION_CONFLICT')

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
            if row is None and not creating_world_override:
                raise KeyError(update.row_id)
            payload["before"] = (
                {column: row[column] for column in update.fields}
                if row is not None
                else {column: None for column in update.fields}
            )
            payload["after"] = dict(update.fields)
            if row is not None and row[version_column] != update.expected_version:
                raise ConfigurationConflictError('CONFIG_VERSION_CONFLICT')

            fields = dict(update.fields)
            if row is None:
                if update.actor_user_id is None:
                    raise ValueError('creating world settings requires an actor user')
                insert_fields = {
                    'world_id': update.row_id,
                    **fields,
                    'version': 1,
                    'updated_at': now,
                    'updated_by': update.actor_user_id,
                }
                columns = ', '.join(insert_fields)
                placeholders = ', '.join('?' for _ in insert_fields)
                connection.execute(
                    f'INSERT INTO {table} ({columns}) VALUES ({placeholders})',
                    list(insert_fields.values()),
                )
            else:
                if 'updated_at' in row and 'updated_at' not in fields:
                    fields['updated_at'] = now
                if (
                    'updated_by' in row
                    and update.actor_user_id is not None
                    and 'updated_by' not in fields
                ):
                    fields['updated_by'] = update.actor_user_id
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
            operation = self._operations.transition(
                operation["op_id"],
                OperationStatus.COMPLETED,
                data=payload,
            )
            return dict(updated), operation
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
