"""Cleanup and retention enforcement for Tier 2 rows/artifacts (Gate 4)."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.domain.tuning import (
    CLEANUP_AGE_FLOOR_DAYS,
    CLEANUP_BLAST_RADIUS_CAP,
    CLEANUP_COUNT_FLOOR,
    CLEANUP_STALE_SESSION_DEFAULT,
    CLEANUP_STORAGE_THRESHOLD_DEFAULT_PCT,
    CLEANUP_TOMBSTONE_GRACE_DAYS,
)
from app.domain.value_objects import OperationStatus
from app.infrastructure.filesystem import LocalFilesystem
from app.ports.clock import Clock
from app.ports.filesystem import FilesystemPort
from app.ports.persistence import PersistencePort
from app.services.audit import AuditService
from app.services.configuration import ConfigurationService
from app.services.operations import OperationService

DAY = 24 * 60 * 60
STALE_BACKUP_CATEGORIES = frozenset({'session_end', 'manual', 'emergency', 'pre_restore'})
SCHEDULED_BACKUP_CAP = 3
IN_FLIGHT_CLEANUP_CONFLICTS = (
    'Backup',
    'Cleanup',
    'Restore',
    'Sync',
)


class RetentionError(Exception):
    """Raised when cleanup would violate retention safety rules."""


@dataclass(frozen=True)
class CleanupCandidate:
    artifact_id: str
    storage_path: str
    world_id: str | None
    category: str
    created_at: int
    sessions_since: int = 0


@dataclass(frozen=True)
class LogCandidate:
    world_id: str
    session_id: str
    path: str
    modified_at: int


class CleanupService:
    """Only service allowed to physically remove Tier 2 backup artifacts."""

    def __init__(
        self,
        store: PersistencePort,
        clock: Clock,
        operations: OperationService | None = None,
        configuration: ConfigurationService | None = None,
        filesystem: FilesystemPort | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._operations = operations or OperationService(store, clock)
        self._configuration = configuration or ConfigurationService(store, clock)
        self._filesystem = filesystem or LocalFilesystem()
        self._audit = audit or AuditService(store, clock)
        self._previews: dict[tuple[str | None, str], str] = {}

    def cleanup_policy(self, world_id: str | None) -> dict[str, Any]:
        """Resolve a world policy with manager defaults and validate its values."""
        reader = self._store.reader()
        policy = None
        if world_id is not None:
            policy = reader.execute(
                """
                SELECT * FROM cleanup_policies
                WHERE scope = 'world' AND world_id = ? AND deleted_at IS NULL
                ORDER BY version DESC LIMIT 1
                """,
                (world_id,),
            ).fetchone()
        if policy is None:
            policy = reader.execute("""
                SELECT * FROM cleanup_policies
                WHERE scope = 'global' AND world_id IS NULL AND deleted_at IS NULL
                ORDER BY version DESC LIMIT 1
                """).fetchone()

        values: dict[str, Any] = {
            'age_rule_days': CLEANUP_AGE_FLOOR_DAYS,
            'space_rule_pct': CLEANUP_STORAGE_THRESHOLD_DEFAULT_PCT,
            'count_rules': {},
            'stale_session_threshold': CLEANUP_STALE_SESSION_DEFAULT,
            'log_retention_days': None,
            'version': None,
        }
        if policy is not None:
            values.update(dict(policy))
            values['version'] = int(policy['version'])
            if policy['count_rules']:
                try:
                    count_rules = json.loads(policy['count_rules'])
                except (TypeError, json.JSONDecodeError) as exc:
                    raise RetentionError('CLEANUP_POLICY_INVALID') from exc
                if not isinstance(count_rules, dict):
                    raise RetentionError('CLEANUP_POLICY_INVALID')
                if not all(
                    isinstance(category, str)
                    and category
                    and type(retain_count) is int
                    and retain_count >= CLEANUP_COUNT_FLOOR
                    for category, retain_count in count_rules.items()
                ):
                    raise RetentionError('CLEANUP_POLICY_INVALID')
                values['count_rules'] = count_rules
            else:
                values['count_rules'] = {}
            if values['space_rule_pct'] is None:
                values['space_rule_pct'] = CLEANUP_STORAGE_THRESHOLD_DEFAULT_PCT

        if (
            type(values['age_rule_days']) is not int
            or values['age_rule_days'] < CLEANUP_AGE_FLOOR_DAYS
            or type(values['space_rule_pct']) is not int
            or not 1 <= values['space_rule_pct'] <= 90
            or type(values['stale_session_threshold']) is not int
            or values['stale_session_threshold'] < 1
            or (
                values['log_retention_days'] is not None
                and (
                    type(values['log_retention_days']) is not int
                    or values['log_retention_days'] < CLEANUP_AGE_FLOOR_DAYS
                )
            )
        ):
            raise RetentionError('CLEANUP_POLICY_INVALID')
        return values

    def _world_ids(self, world_id: str | None) -> list[str]:
        if world_id is not None:
            exists = (
                self._store.reader()
                .execute('SELECT 1 FROM world_instances WHERE world_id = ?', (world_id,))
                .fetchone()
            )
            return [world_id] if exists is not None else []
        rows = (
            self._store.reader()
            .execute('SELECT world_id FROM world_instances ORDER BY world_id')
            .fetchall()
        )
        return [str(row['world_id']) for row in rows]

    def _effective_root(self, world_id: str, setting: str, fallback: str) -> Path:
        try:
            value = self._configuration.resolve_effective(world_id)[setting]
        except KeyError:
            value = fallback
        return Path(str(value or fallback)) / world_id

    def _backup_root(self, world_id: str) -> Path:
        return self._effective_root(world_id, 'backup_root_path', 'backups')

    def _log_root(self, world_id: str) -> Path:
        return self._effective_root(world_id, 'log_root_path', 'logs') / world_id

    def _require_backup_path(self, world_id: str, path: str) -> Path:
        candidate = Path(path)
        root = self._backup_root(world_id)
        if (
            candidate.suffix.lower() != '.zip'
            or candidate.is_symlink()
            or not self._filesystem.is_within(candidate, root)
        ):
            raise RetentionError('BACKUP_PATH_UNSAFE')
        return candidate

    def _pressure(self, world_id: str, threshold_pct: int) -> dict[str, Any]:
        root = self._backup_root(world_id)
        probe = root
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        if probe.is_file():
            probe = probe.parent
        usage = self._filesystem.disk_usage(probe)
        if usage.total <= 0 or not 0 <= usage.used <= usage.total:
            raise RetentionError('CLEANUP_STORAGE_USAGE_INVALID')
        used_pct = (usage.used * 100) / usage.total
        return {
            'threshold_pct': threshold_pct,
            'used_pct': round(used_pct, 2),
            'triggered': usage.used * 100 >= threshold_pct * usage.total,
        }

    def _world_has_in_flight_operation(
        self, connection: Any, world_id: str, operation_id: str
    ) -> bool:
        placeholders = ', '.join('?' for _ in IN_FLIGHT_CLEANUP_CONFLICTS)
        statuses = (
            OperationStatus.CREATED.value,
            OperationStatus.QUEUED.value,
            OperationStatus.VALIDATING.value,
            OperationStatus.RUNNING.value,
        )
        row = connection.execute(
            f"""
            SELECT 1 FROM operations
            WHERE world_id = ?
              AND op_id <> ?
              AND op_type IN ({placeholders})
              AND status IN ({', '.join('?' for _ in statuses)})
            LIMIT 1
            """,
            (
                world_id,
                operation_id,
                *IN_FLIGHT_CLEANUP_CONFLICTS,
                *statuses,
            ),
        ).fetchone()
        return row is not None

    @staticmethod
    def _artifact_is_referenced(connection: Any, artifact_id: str) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM restore_history
            WHERE source_artifact_id = ? OR pre_restore_artifact_id = ?
            UNION ALL
            SELECT 1 FROM sync_records WHERE artifact_id = ?
            LIMIT 1
            """,
            (artifact_id, artifact_id, artifact_id),
        ).fetchone()
        return row is not None

    def stale_backup_candidates(
        self,
        *,
        world_id: str | None,
        operation_id: str,
    ) -> tuple[list[CleanupCandidate], dict[str, dict[str, Any]]]:
        """Find policy-eligible backup artifacts only when their volume is pressured."""
        candidates: list[CleanupCandidate] = []
        pressure_by_world: dict[str, dict[str, Any]] = {}
        now = int(self._clock.now())
        reader = self._store.reader()
        for candidate_world_id in self._world_ids(world_id):
            policy = self.cleanup_policy(candidate_world_id)
            pressure = self._pressure(candidate_world_id, policy['space_rule_pct'])
            pressure_by_world[candidate_world_id] = pressure
            if not pressure['triggered'] or self._world_has_in_flight_operation(
                reader, candidate_world_id, operation_id
            ):
                continue
            rows = reader.execute(
                """
                SELECT b.*,
                       (SELECT COUNT(*) FROM runtime_sessions rs
                        WHERE rs.world_id = b.world_id AND rs.ended_at > b.created_at)
                           AS sessions_since
                FROM backup_artifacts b
                WHERE b.world_id = ?
                  AND b.deleted_at IS NULL
                  AND b.stale_tombstoned_at IS NULL
                  AND b.suspect = 0
                  AND b.category IN ('session_end', 'manual', 'emergency', 'pre_restore')
                ORDER BY b.category, b.created_at DESC, b.artifact_id DESC
                """,
                (candidate_world_id,),
            ).fetchall()
            groups: dict[str, list[Any]] = defaultdict(list)
            for row in rows:
                groups[str(row['category'])].append(row)
            cutoff = now - policy['age_rule_days'] * DAY
            count_rules = policy['count_rules']
            for category, artifacts in groups.items():
                keep_count = count_rules.get(category, CLEANUP_COUNT_FLOOR)
                if type(keep_count) is not int or keep_count < CLEANUP_COUNT_FLOOR:
                    raise RetentionError('CLEANUP_POLICY_INVALID')
                protected_ids = {str(row['artifact_id']) for row in artifacts[:keep_count]}
                for row in artifacts:
                    artifact_id = str(row['artifact_id'])
                    if (
                        artifact_id in protected_ids
                        or int(row['created_at']) > cutoff
                        or int(row['sessions_since']) < policy['stale_session_threshold']
                        or self._artifact_is_referenced(reader, artifact_id)
                    ):
                        continue
                    path = self._require_backup_path(candidate_world_id, str(row['storage_path']))
                    candidates.append(
                        CleanupCandidate(
                            artifact_id=artifact_id,
                            storage_path=str(path),
                            world_id=candidate_world_id,
                            category=category,
                            created_at=int(row['created_at']),
                            sessions_since=int(row['sessions_since']),
                        )
                    )
        candidates.sort(key=lambda candidate: (candidate.world_id or '', candidate.created_at))
        return candidates, pressure_by_world

    def stale_tombstone_candidates(
        self, *, world_id: str | None, operation_id: str
    ) -> list[CleanupCandidate]:
        """Find tombstoned backup artifacts whose grace period has elapsed."""
        cutoff = int(self._clock.now()) - CLEANUP_TOMBSTONE_GRACE_DAYS * DAY
        rows = (
            self._store.reader()
            .execute(
                """
            SELECT artifact_id, world_id, category, storage_path, created_at,
                   stale_tombstoned_at
            FROM backup_artifacts
            WHERE stale_tombstoned_at IS NOT NULL
              AND deleted_at IS NOT NULL
              AND stale_tombstoned_at <= ?
              AND world_id IS NOT NULL
              AND category IN ('session_end', 'manual', 'emergency', 'pre_restore')
              AND (? IS NULL OR world_id = ?)
            ORDER BY stale_tombstoned_at, artifact_id
            """,
                (cutoff, world_id, world_id),
            )
            .fetchall()
        )
        candidates: list[CleanupCandidate] = []
        for row in rows:
            candidate_world_id = str(row['world_id'])
            if self._world_has_in_flight_operation(
                self._store.reader(), candidate_world_id, operation_id
            ) or self._artifact_is_referenced(self._store.reader(), str(row['artifact_id'])):
                continue
            path = self._require_backup_path(candidate_world_id, str(row['storage_path']))
            candidates.append(
                CleanupCandidate(
                    artifact_id=str(row['artifact_id']),
                    storage_path=str(path),
                    world_id=candidate_world_id,
                    category=str(row['category']),
                    created_at=int(row['created_at']),
                )
            )
        return candidates

    def log_candidates(self, *, world_id: str | None, operation_id: str) -> list[LogCandidate]:
        """Find expired files for closed, normal runtime sessions only."""
        candidates: list[LogCandidate] = []
        now = int(self._clock.now())
        reader = self._store.reader()
        for candidate_world_id in self._world_ids(world_id):
            policy = self.cleanup_policy(candidate_world_id)
            retention_days = policy['log_retention_days']
            if retention_days is None or self._world_has_in_flight_operation(
                reader, candidate_world_id, operation_id
            ):
                continue
            cutoff = now - retention_days * DAY
            sessions = reader.execute(
                """
                SELECT session_id, ended_at, end_reason
                FROM runtime_sessions
                WHERE world_id = ? AND ended_at IS NOT NULL
                ORDER BY ended_at, session_id
                """,
                (candidate_world_id,),
            ).fetchall()
            root = self._log_root(candidate_world_id)
            for session in sessions:
                if int(session['ended_at']) > cutoff or session['end_reason'] != 'graceful_stop':
                    continue
                session_id = str(session['session_id'])
                if (
                    not session_id
                    or Path(session_id).name != session_id
                    or any(character in session_id for character in '*?[]')
                ):
                    continue
                session_log = root / f'{session_id}.log'
                if not session_log.parent.is_dir():
                    continue
                for path in session_log.parent.iterdir():
                    if (
                        not path.is_file()
                        or path.is_symlink()
                        or not path.name.startswith(f'{session_id}.log.')
                        or not self._filesystem.is_within(path, root)
                        or int(self._filesystem.modified_at(path)) > cutoff
                    ):
                        continue
                    candidates.append(
                        LogCandidate(
                            world_id=candidate_world_id,
                            session_id=session_id,
                            path=str(path),
                            modified_at=int(self._filesystem.modified_at(path)),
                        )
                    )
        candidates.sort(key=lambda candidate: candidate.path)
        return candidates

    def delete_backup_artifact(
        self, artifact_id: str, *, deleted_by: str, force: bool = False
    ) -> None:
        """Remove an artifact file while preserving retention floors unless forced."""
        row = self.validate_backup_artifact_delete(artifact_id, force=force)
        world_id = row["world_id"]
        if not isinstance(world_id, str):
            raise RetentionError('BACKUP_PATH_UNSAFE')
        self._require_backup_path(world_id, str(row["storage_path"])).unlink(missing_ok=True)
        connection = self._store.writer()
        connection.execute(
            "UPDATE backup_artifacts SET deleted_at = ?, deleted_by = ? "
            "WHERE artifact_id = ? AND deleted_at IS NULL",
            (int(self._clock.now()), deleted_by, artifact_id),
        )
        connection.commit()

    def enforce_scheduled_backup_cap(
        self, *, operation_id: str, world_id: str | None
    ) -> dict[str, list[str]]:
        """Retain at most three unreferenced scheduled backups when safety permits."""
        operation = (
            self._store.reader()
            .execute('SELECT op_type, status FROM operations WHERE op_id = ?', (operation_id,))
            .fetchone()
        )
        if (
            operation is None
            or operation['op_type'] != 'Cleanup'
            or operation['status']
            in {
                OperationStatus.COMPLETED.value,
                OperationStatus.FAILED.value,
                OperationStatus.CANCELLED.value,
                OperationStatus.TIMED_OUT.value,
            }
        ):
            raise RetentionError('CLEANUP_OPERATION_REQUIRED')
        if world_id is None:
            raise RetentionError('CLEANUP_WORLD_REQUIRED')

        rows = (
            self._store.reader()
            .execute(
                """
                SELECT artifact_id
                FROM backup_artifacts
                WHERE world_id = ? AND category = 'scheduled' AND deleted_at IS NULL
                ORDER BY created_at DESC, artifact_id DESC
                """,
                (world_id,),
            )
            .fetchall()
        )
        deleted: list[str] = []
        protected: list[str] = []
        for row in rows[SCHEDULED_BACKUP_CAP:]:
            artifact_id = str(row['artifact_id'])
            if self._artifact_is_referenced(self._store.reader(), artifact_id):
                protected.append(artifact_id)
                continue
            self.delete_backup_artifact(artifact_id, deleted_by='system')
            self._audit.write(
                event_type='cleanup.scheduled_backup_deleted',
                actor=self._audit.system(),
                operation_id=operation_id,
                world_id=world_id,
                payload={'artifact_id': artifact_id, 'retained_cap': SCHEDULED_BACKUP_CAP},
            )
            deleted.append(artifact_id)
        return {'deleted_artifact_ids': deleted, 'protected_artifact_ids': protected}

    def validate_backup_artifact_delete(
        self, artifact_id: str, *, force: bool = False
    ) -> dict[str, Any]:
        """Check artifact existence and retention rules without mutating state."""
        row = (
            self._store.reader()
            .execute(
                "SELECT * FROM backup_artifacts WHERE artifact_id = ? AND deleted_at IS NULL",
                (artifact_id,),
            )
            .fetchone()
        )
        if row is None:
            raise KeyError(artifact_id)
        if self._artifact_is_referenced(self._store.reader(), artifact_id):
            raise RetentionError('BACKUP_RETENTION_GUARD')
        siblings = (
            self._store.reader()
            .execute(
                """
            SELECT artifact_id, suspect
            FROM backup_artifacts
            WHERE world_id IS ? AND category = ? AND deleted_at IS NULL
            ORDER BY created_at DESC
            """,
                (row["world_id"], row["category"]),
            )
            .fetchall()
        )
        remaining = [item for item in siblings if item["artifact_id"] != artifact_id]
        violates_floor = len(remaining) < CLEANUP_COUNT_FLOOR or not any(
            item["suspect"] == 0 for item in remaining
        )
        if violates_floor and not force:
            raise RetentionError("BACKUP_RETENTION_GUARD")
        return dict(row)

    def backup_candidates(
        self,
        *,
        older_than_days: int,
        keep_per_category: int = CLEANUP_COUNT_FLOOR,
        world_id: str | None = None,
    ) -> list[CleanupCandidate]:
        if older_than_days < CLEANUP_AGE_FLOOR_DAYS:
            raise RetentionError('age floor is 3 days')
        if keep_per_category < CLEANUP_COUNT_FLOOR:
            raise RetentionError('count floor is 3 per world/category')
        cutoff = int(self._clock.now()) - older_than_days * 24 * 60 * 60
        rows = (
            self._store.reader()
            .execute(
                """
            SELECT *
            FROM backup_artifacts
            WHERE deleted_at IS NULL
              AND (? IS NULL OR world_id = ?)
            ORDER BY world_id, category, created_at DESC
            """,
                (world_id, world_id),
            )
            .fetchall()
        )
        grouped: dict[tuple[str | None, str], list[Any]] = defaultdict(list)
        for row in rows:
            grouped[(row['world_id'], row['category'])].append(row)

        candidates: list[CleanupCandidate] = []
        for (_world_id, _category), artifacts in grouped.items():
            viable = [row for row in artifacts if row['suspect'] == 0]
            protected_ids = {row['artifact_id'] for row in artifacts[:keep_per_category]}
            if viable:
                protected_ids.add(viable[0]['artifact_id'])
            for row in artifacts:
                if (
                    row['created_at'] >= cutoff
                    or row['artifact_id'] in protected_ids
                    or row['suspect'] != 0
                ):
                    continue
                candidates.append(
                    CleanupCandidate(
                        artifact_id=row['artifact_id'],
                        storage_path=row['storage_path'],
                        world_id=row['world_id'],
                        category=row['category'],
                        created_at=row['created_at'],
                    )
                )
        return sorted(candidates, key=lambda candidate: candidate.created_at)

    def execute_backup_cleanup(
        self,
        candidates: list[CleanupCandidate],
        *,
        deleted_by: str = 'system',
        older_than_days: int = CLEANUP_AGE_FLOOR_DAYS,
        keep_per_category: int = CLEANUP_COUNT_FLOOR,
        world_id: str | None = None,
        elevated_confirmation: bool = False,
    ) -> int:
        if len(candidates) > CLEANUP_BLAST_RADIUS_CAP and not elevated_confirmation:
            raise RetentionError('CLEANUP_BLAST_RADIUS')
        eligible = self.backup_candidates(
            older_than_days=older_than_days,
            keep_per_category=keep_per_category,
            world_id=world_id,
        )
        if candidates != eligible:
            raise RetentionError('CLEANUP_PREVIEW_REQUIRED_OR_STALE')

        now = int(self._clock.now())
        connection = self._store.writer()
        deleted = 0
        for candidate in candidates:
            still_live = connection.execute(
                'SELECT deleted_at FROM backup_artifacts WHERE artifact_id = ?',
                (candidate.artifact_id,),
            ).fetchone()
            if still_live is None or still_live['deleted_at'] is not None:
                continue
            Path(candidate.storage_path).unlink(missing_ok=True)
            connection.execute(
                'UPDATE backup_artifacts SET deleted_at = ?, deleted_by = ? WHERE artifact_id = ?',
                (now, deleted_by, candidate.artifact_id),
            )
            deleted += 1
        connection.commit()
        return deleted

    def _plan(self, *, scope: str, world_id: str | None, operation_id: str) -> dict[str, Any]:
        if scope == 'stale_backups':
            tombstone, pressure = self.stale_backup_candidates(
                world_id=world_id, operation_id=operation_id
            )
            purge = self.stale_tombstone_candidates(world_id=world_id, operation_id=operation_id)
            return {
                'tombstone': tombstone,
                'purge': purge,
                'pressure': pressure,
                'policies': {
                    item_world_id: self.cleanup_policy(item_world_id)['version']
                    for item_world_id in self._world_ids(world_id)
                },
            }
        if scope == 'logs':
            logs = self.log_candidates(world_id=world_id, operation_id=operation_id)
            return {
                'logs': logs,
                'policies': {
                    item_world_id: self.cleanup_policy(item_world_id)['version']
                    for item_world_id in self._world_ids(world_id)
                },
            }
        raise RetentionError('CLEANUP_SCOPE_UNSUPPORTED')

    @staticmethod
    def _plan_fingerprint(plan: dict[str, Any], *, scope: str, world_id: str | None) -> str:
        def artifact_data(candidate: CleanupCandidate) -> dict[str, Any]:
            return {
                'artifact_id': candidate.artifact_id,
                'storage_path': candidate.storage_path,
                'world_id': candidate.world_id,
                'category': candidate.category,
                'created_at': candidate.created_at,
                'sessions_since': candidate.sessions_since,
            }

        snapshot: dict[str, Any] = {
            'scope': scope,
            'world_id': world_id,
            'policies': plan['policies'],
        }
        if scope == 'stale_backups':
            snapshot.update(
                {
                    'tombstone': [artifact_data(item) for item in plan['tombstone']],
                    'purge': [artifact_data(item) for item in plan['purge']],
                    'pressure': {
                        item_world_id: {
                            'threshold_pct': pressure['threshold_pct'],
                            'triggered': pressure['triggered'],
                        }
                        for item_world_id, pressure in plan['pressure'].items()
                    },
                }
            )
        else:
            snapshot['logs'] = [
                {
                    'world_id': item.world_id,
                    'session_id': item.session_id,
                    'path': item.path,
                    'modified_at': item.modified_at,
                }
                for item in plan['logs']
            ]
        canonical = json.dumps(snapshot, sort_keys=True, separators=(',', ':'))
        return sha256(canonical.encode('utf-8')).hexdigest()

    def _tombstone_stale_backups(
        self, candidates: list[CleanupCandidate], *, operation_id: str
    ) -> list[str]:
        if not candidates:
            return []
        connection = self._store.writer()
        connection.execute('BEGIN IMMEDIATE')
        try:
            current, _ = self.stale_backup_candidates(world_id=None, operation_id=operation_id)
            current_by_id = {candidate.artifact_id: candidate for candidate in current}
            applied: list[str] = []
            now = int(self._clock.now())
            for candidate in candidates:
                latest = current_by_id.get(candidate.artifact_id)
                if latest != candidate:
                    raise RetentionError('CLEANUP_PREVIEW_REQUIRED_OR_STALE')
                cursor = connection.execute(
                    """
                    UPDATE backup_artifacts
                    SET deleted_at = ?, deleted_by = 'system', stale_tombstoned_at = ?
                    WHERE artifact_id = ? AND deleted_at IS NULL
                      AND stale_tombstoned_at IS NULL
                      AND category IN ('session_end', 'manual', 'emergency', 'pre_restore')
                      AND NOT EXISTS (
                          SELECT 1 FROM restore_history
                          WHERE source_artifact_id = backup_artifacts.artifact_id
                             OR pre_restore_artifact_id = backup_artifacts.artifact_id
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM sync_records
                          WHERE artifact_id = backup_artifacts.artifact_id
                      )
                    """,
                    (now, now, candidate.artifact_id),
                )
                if cursor.rowcount != 1:
                    raise RetentionError('CLEANUP_PREVIEW_REQUIRED_OR_STALE')
                self._audit.write(
                    event_type='cleanup.backup_stale_tombstoned',
                    actor=self._audit.system(),
                    operation_id=operation_id,
                    world_id=candidate.world_id,
                    payload={
                        'artifact_id': candidate.artifact_id,
                        'category': candidate.category,
                        'sessions_since': candidate.sessions_since,
                    },
                    connection=connection,
                )
                applied.append(candidate.artifact_id)
            connection.commit()
            return applied
        except Exception:
            connection.rollback()
            raise

    def _purge_stale_backups(
        self, candidates: list[CleanupCandidate], *, operation_id: str
    ) -> list[str]:
        if not candidates:
            return []
        connection = self._store.writer()
        connection.execute('BEGIN IMMEDIATE')
        try:
            current = self.stale_tombstone_candidates(world_id=None, operation_id=operation_id)
            current_by_id = {candidate.artifact_id: candidate for candidate in current}
            purged: list[str] = []
            for candidate in candidates:
                if current_by_id.get(candidate.artifact_id) != candidate:
                    raise RetentionError('CLEANUP_PREVIEW_REQUIRED_OR_STALE')
                if candidate.world_id is None:
                    raise RetentionError('BACKUP_PATH_UNSAFE')
                if self._artifact_is_referenced(connection, candidate.artifact_id):
                    raise RetentionError('BACKUP_RETENTION_GUARD')
                path = self._require_backup_path(candidate.world_id, candidate.storage_path)
                path.unlink(missing_ok=True)
                cursor = connection.execute(
                    """
                    DELETE FROM backup_artifacts
                    WHERE artifact_id = ? AND stale_tombstoned_at IS NOT NULL
                      AND stale_tombstoned_at <= ?
                      AND NOT EXISTS (
                          SELECT 1 FROM restore_history
                          WHERE source_artifact_id = backup_artifacts.artifact_id
                             OR pre_restore_artifact_id = backup_artifacts.artifact_id
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM sync_records
                          WHERE artifact_id = backup_artifacts.artifact_id
                      )
                    """,
                    (
                        candidate.artifact_id,
                        int(self._clock.now()) - CLEANUP_TOMBSTONE_GRACE_DAYS * DAY,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RetentionError('CLEANUP_PREVIEW_REQUIRED_OR_STALE')
                self._audit.write(
                    event_type='cleanup.backup_hard_deleted',
                    actor=self._audit.system(),
                    operation_id=operation_id,
                    world_id=candidate.world_id,
                    payload={
                        'artifact_id': candidate.artifact_id,
                        'category': candidate.category,
                    },
                    connection=connection,
                )
                purged.append(candidate.artifact_id)
            connection.commit()
            return purged
        except Exception:
            connection.rollback()
            raise

    def _delete_expired_logs(
        self, candidates: list[LogCandidate], *, operation_id: str, world_id: str | None
    ) -> list[str]:
        if not candidates:
            return []
        connection = self._store.writer()
        connection.execute('BEGIN IMMEDIATE')
        try:
            current = self.log_candidates(world_id=world_id, operation_id=operation_id)
            current_by_path = {candidate.path: candidate for candidate in current}
            deleted: list[str] = []
            for candidate in candidates:
                if current_by_path.get(candidate.path) != candidate:
                    raise RetentionError('CLEANUP_PREVIEW_REQUIRED_OR_STALE')
                path = Path(candidate.path)
                if path.is_symlink() or not self._filesystem.is_within(
                    path, self._log_root(candidate.world_id)
                ):
                    raise RetentionError('LOG_PATH_UNSAFE')
                path.unlink(missing_ok=True)
                self._audit.write(
                    event_type='cleanup.log_file_deleted',
                    actor=self._audit.system(),
                    operation_id=operation_id,
                    world_id=candidate.world_id,
                    payload={
                        'session_id': candidate.session_id,
                        'filename': path.name,
                    },
                    connection=connection,
                )
                deleted.append(candidate.path)
            connection.commit()
            return deleted
        except Exception:
            connection.rollback()
            raise

    def run_scheduled_cleanup(
        self, *, operation_id: str, world_id: str | None, schedule_id: str
    ) -> dict[str, Any]:
        """Run retention cleanup from an explicitly configured cleanup schedule."""
        scheduled_policy = (
            self._store.reader()
            .execute(
                """
            SELECT s.world_id
            FROM schedules s
            JOIN cleanup_policies p
              ON p.schedule_id = s.schedule_id
             AND p.scope = s.scope
             AND p.world_id IS s.world_id
            WHERE s.schedule_id = ? AND s.schedule_type = 'cleanup'
              AND s.enabled = 1 AND s.deleted_at IS NULL
              AND p.deleted_at IS NULL
            """,
                (schedule_id,),
            )
            .fetchone()
        )
        if scheduled_policy is None or scheduled_policy['world_id'] != world_id:
            raise RetentionError('CLEANUP_SCHEDULE_UNRESOLVED')

        tombstone_candidates, pressure = self.stale_backup_candidates(
            world_id=world_id, operation_id=operation_id
        )
        purge_candidates = self.stale_tombstone_candidates(
            world_id=world_id, operation_id=operation_id
        )
        log_candidates = self.log_candidates(world_id=world_id, operation_id=operation_id)
        tombstone_candidates = tombstone_candidates[:CLEANUP_BLAST_RADIUS_CAP]
        purge_candidates = purge_candidates[:CLEANUP_BLAST_RADIUS_CAP]
        log_candidates = log_candidates[:CLEANUP_BLAST_RADIUS_CAP]
        tombstoned = self._tombstone_stale_backups(tombstone_candidates, operation_id=operation_id)
        purged = self._purge_stale_backups(purge_candidates, operation_id=operation_id)
        deleted_logs = self._delete_expired_logs(
            log_candidates, operation_id=operation_id, world_id=world_id
        )
        return {
            'mode': 'scheduled',
            'scope': 'stale_backups_and_logs',
            'storage_pressure': pressure,
            'tombstoned_artifact_ids': tombstoned,
            'purged_artifact_ids': purged,
            'deleted_log_count': len(deleted_logs),
        }

    def evaluate_and_execute_cleanup(
        self,
        *,
        op_id: str,
        world_id: str | None = None,
        dry_run: bool = True,
        older_than_days: int = CLEANUP_AGE_FLOOR_DAYS,
        keep_per_category: int = CLEANUP_COUNT_FLOOR,
        elevated_confirmation: bool = False,
        scope: str = 'backups',
        deleted_by: str = 'system',
        dry_run_operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Preview or perform a retention-bounded cleanup as a durable Operation."""
        operation = (
            self._store.reader()
            .execute('SELECT op_type, status FROM operations WHERE op_id = ?', (op_id,))
            .fetchone()
        )
        if (
            operation is None
            or operation['op_type'] != 'Cleanup'
            or operation['status']
            in {
                OperationStatus.COMPLETED.value,
                OperationStatus.FAILED.value,
                OperationStatus.CANCELLED.value,
                OperationStatus.TIMED_OUT.value,
            }
        ):
            raise RetentionError('CLEANUP_OPERATION_REQUIRED')
        try:
            plan: dict[str, Any] = {}
            tombstone_target_ids: list[str] = []
            purge_target_ids: list[str] = []
            log_target_ids: list[dict[str, str]] = []
            if scope == 'backups':
                candidates = self.backup_candidates(
                    older_than_days=older_than_days,
                    keep_per_category=keep_per_category,
                    world_id=world_id,
                )
                target_count = len(candidates)
                preview_fingerprint = self._preview_fingerprint(
                    candidates,
                    older_than_days=older_than_days,
                    keep_per_category=keep_per_category,
                    world_id=world_id,
                    scope=scope,
                )
            elif scope in {'stale_backups', 'logs'}:
                plan = self._plan(scope=scope, world_id=world_id, operation_id=op_id)
                if scope == 'stale_backups':
                    target_count = len(plan['tombstone']) + len(plan['purge'])
                    tombstone_target_ids = [item.artifact_id for item in plan['tombstone']]
                    purge_target_ids = [item.artifact_id for item in plan['purge']]
                else:
                    target_count = len(plan['logs'])
                    log_target_ids = [
                        {
                            'world_id': item.world_id,
                            'session_id': item.session_id,
                            'filename': Path(item.path).name,
                        }
                        for item in plan['logs']
                    ]
                preview_fingerprint = self._plan_fingerprint(plan, scope=scope, world_id=world_id)
            else:
                raise RetentionError('CLEANUP_SCOPE_UNSUPPORTED')
            if (
                not dry_run
                and target_count > CLEANUP_BLAST_RADIUS_CAP
                and not elevated_confirmation
            ):
                raise RetentionError('CLEANUP_BLAST_RADIUS')
            key = (world_id, scope)
            matched_preview = self._previews.get(key)
            if not dry_run and dry_run_operation_id is not None:
                preview = (
                    self._store.reader()
                    .execute(
                        """
                    SELECT op_type, status, data_json
                    FROM operations
                    WHERE op_id = ?
                    """,
                        (dry_run_operation_id,),
                    )
                    .fetchone()
                )
                if (
                    preview is not None
                    and preview['op_type'] == 'Cleanup'
                    and preview['status'] == OperationStatus.COMPLETED.value
                    and preview['data_json']
                ):
                    preview_data = json.loads(preview['data_json'])
                    if (
                        preview_data.get('scope') == scope
                        and preview_data.get('world_id') == world_id
                    ):
                        matched_preview = preview_data.get('preview_fingerprint')
                    else:
                        matched_preview = None
                else:
                    matched_preview = None
            if not dry_run and matched_preview != preview_fingerprint:
                raise RetentionError('CLEANUP_PREVIEW_REQUIRED_OR_STALE')
            self._operations.transition(op_id, OperationStatus.RUNNING)
            if dry_run:
                self._previews[key] = preview_fingerprint
                result: dict[str, Any] = {
                    'mode': 'dry_run',
                    'scope': scope,
                    'world_id': world_id,
                    'target_count': target_count,
                    'preview_fingerprint': preview_fingerprint,
                }
                if scope == 'backups':
                    result.update(
                        {
                            'targets': [candidate.artifact_id for candidate in candidates],
                            'older_than_days': older_than_days,
                            'keep_per_category': keep_per_category,
                        }
                    )
                elif scope == 'stale_backups':
                    result.update(
                        {
                            'tombstone_targets': tombstone_target_ids,
                            'purge_targets': purge_target_ids,
                            'storage_pressure': plan['pressure'],
                        }
                    )
                else:
                    result['targets'] = log_target_ids
            else:
                if scope == 'backups':
                    result = {
                        'mode': 'wet_run',
                        'deleted_count': self.execute_backup_cleanup(
                            candidates,
                            deleted_by=deleted_by,
                            older_than_days=older_than_days,
                            keep_per_category=keep_per_category,
                            world_id=world_id,
                            elevated_confirmation=elevated_confirmation,
                        ),
                        'target_count': target_count,
                    }
                elif scope == 'stale_backups':
                    tombstoned = self._tombstone_stale_backups(
                        plan['tombstone'], operation_id=op_id
                    )
                    purged = self._purge_stale_backups(plan['purge'], operation_id=op_id)
                    result = {
                        'mode': 'wet_run',
                        'scope': scope,
                        'world_id': world_id,
                        'tombstoned_artifact_ids': tombstoned,
                        'purged_artifact_ids': purged,
                        'target_count': len(tombstoned) + len(purged),
                    }
                else:
                    deleted_logs = self._delete_expired_logs(
                        plan['logs'], operation_id=op_id, world_id=world_id
                    )
                    result = {
                        'mode': 'wet_run',
                        'scope': scope,
                        'world_id': world_id,
                        'deleted_log_count': len(deleted_logs),
                        'target_count': len(deleted_logs),
                    }
            self._operations.transition(op_id, OperationStatus.COMPLETED, data=result)
            return result
        except RetentionError as exc:
            operation = (
                self._store.reader()
                .execute('SELECT status FROM operations WHERE op_id = ?', (op_id,))
                .fetchone()
            )
            if operation is not None and operation['status'] not in {
                OperationStatus.COMPLETED.value,
                OperationStatus.FAILED.value,
                OperationStatus.CANCELLED.value,
                OperationStatus.TIMED_OUT.value,
            }:
                self._operations.transition(
                    op_id,
                    OperationStatus.FAILED,
                    error_code=str(exc),
                    message=str(exc),
                )
            raise

    @staticmethod
    def _preview_fingerprint(
        candidates: list[CleanupCandidate],
        *,
        older_than_days: int,
        keep_per_category: int,
        world_id: str | None,
        scope: str,
    ) -> str:
        """Bind confirmation to the policy and exact artifact metadata previewed."""
        snapshot = {
            'older_than_days': older_than_days,
            'keep_per_category': keep_per_category,
            'scope': scope,
            'world_id': world_id,
            'targets': [
                {
                    'artifact_id': candidate.artifact_id,
                    'storage_path': candidate.storage_path,
                    'world_id': candidate.world_id,
                    'category': candidate.category,
                    'created_at': candidate.created_at,
                }
                for candidate in candidates
            ],
        }
        canonical = json.dumps(snapshot, sort_keys=True, separators=(',', ':'))
        return sha256(canonical.encode('utf-8')).hexdigest()
