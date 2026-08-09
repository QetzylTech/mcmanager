"""Optimistic concurrency for multi-admin configuration tables (Gate 4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.value_objects import ConfigEditEntity
from app.infrastructure.sqlite.connection import SqliteStore
from app.ports.clock import Clock


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


class ConfigurationService:
    """Compare-submitted-version-before-write for every versioned config row."""

    def __init__(self, store: SqliteStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def update_versioned(self, update: VersionedUpdate) -> dict[str, Any]:
        if update.entity not in VERSION_TABLES:
            raise ValueError(f'entity is not versioned: {update.entity.value}')
        table, key_column, version_column = VERSION_TABLES[update.entity]
        if not update.fields:
            raise ValueError('update requires at least one field')
        disallowed = {key_column, version_column}
        if disallowed.intersection(update.fields):
            raise ValueError('cannot update identity or version columns directly')

        connection = self._store.writer()
        now = int(self._clock.now())
        try:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute(
                f'SELECT * FROM {table} WHERE {key_column} = ?', (update.row_id,)
            ).fetchone()
            if row is None:
                raise KeyError(update.row_id)
            if row[version_column] != update.expected_version:
                raise ConfigurationConflictError('CONFIG_VERSION_CONFLICT')

            fields = dict(update.fields)
            if 'updated_at' in row.keys() and 'updated_at' not in fields:
                fields['updated_at'] = now
            if 'last_changed_at' in row.keys() and 'last_changed_at' not in fields:
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
            return dict(updated)
        except Exception:
            connection.rollback()
            raise
