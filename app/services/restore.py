"""Staged restore flow and rollback decision tree (Gate 4)."""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.domain.value_objects import (
    ActorType,
    OperationStatus,
    OperationType,
    TriggerType,
    WorldState,
)
from app.ports.clock import Clock
from app.ports.persistence import PersistencePort
from app.services.backup import BackupService
from app.services.operations import OperationInput, OperationService


class RestartProbe(Protocol):
    def restart_and_confirm(self, world_id: str) -> bool: ...


class RestorePreconditionError(Exception):
    """Pre-operation restore rejection with an API-ready error code/status."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class RestoreResult:
    restore_id: str
    outcome: str
    rollback_operation_id: str | None = None


class RestoreService:
    """Validate -> pre-backup -> stage -> switch -> restart, with rollback."""

    def __init__(
        self,
        store: PersistencePort,
        clock: Clock,
        operations: OperationService,
        backups: BackupService,
        restart_probe: RestartProbe | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._operations = operations
        self._backups = backups
        self._restart_probe = restart_probe

    def restore(
        self,
        *,
        world_id: str,
        artifact_id: str,
        world_dir: str | Path,
        backup_dir: str | Path,
        staging_dir: str | Path,
        operation_id: str,
        operator_user_id: str,
        was_running: bool,
        rollback_of_restore_id: str | None = None,
    ) -> RestoreResult:
        world = self._store.reader().execute(
            'SELECT state FROM world_instances WHERE world_id = ?', (world_id,)
        ).fetchone()
        if world is None:
            raise RestorePreconditionError(
                'WORLD_NOT_FOUND', f'world not found: {world_id}', status_code=404
            )
        if world['state'] != WorldState.OFF.value:
            raise RestorePreconditionError(
                'WORLD_NOT_OFF',
                f'WORLD_NOT_OFF: restore requires an off world (state={world["state"]})',
            )

        self._backups.validate_artifact(artifact_id)
        pre_backup = self._backups.create_world_backup(
            world_id=world_id,
            world_dir=world_dir,
            backup_dir=backup_dir,
            operation_id=operation_id,
            category=TriggerType.PRE_RESTORE,
            running=False,
        )
        self._backups.extract_to_staging(artifact_id, staging_dir)
        self._switch_world(Path(world_dir), Path(staging_dir))
        restore_id = self._record_history(
            world_id=world_id,
            operation_id=operation_id,
            source_artifact_id=artifact_id,
            pre_restore_artifact_id=pre_backup.artifact_id,
            operator_user_id=operator_user_id,
            outcome='success',
            rollback_of_restore_id=rollback_of_restore_id,
        )

        if not was_running:
            self._set_world_state(world_id, WorldState.OFF)
            return RestoreResult(restore_id, 'success')

        if self._restart_succeeded(world_id):
            self._set_world_state(world_id, WorldState.RUNNING)
            return RestoreResult(restore_id, 'success')

        self._backups._flag_suspect(artifact_id)
        rollback_op = self._operations.create(
            OperationInput(
                op_type=OperationType.RESTORE,
                actor_type=ActorType.SYSTEM,
                world_id=world_id,
                data={'rollback_of_restore_id': restore_id, 'source_artifact_id': pre_backup.artifact_id},
                compensates_operation_id=operation_id,
            ),
            allow_world_conflict=True,
        )
        try:
            self._backups.extract_to_staging(pre_backup.artifact_id, staging_dir)
            self._switch_world(Path(world_dir), Path(staging_dir))
            self._operations.transition(rollback_op['op_id'], OperationStatus.COMPLETED)
            self._record_history(
                world_id=world_id,
                operation_id=rollback_op['op_id'],
                source_artifact_id=pre_backup.artifact_id,
                pre_restore_artifact_id=pre_backup.artifact_id,
                operator_user_id=operator_user_id,
                outcome='reverted',
                rollback_of_restore_id=restore_id,
            )
            self._update_restore_outcome(restore_id, 'reverted')
            self._set_world_state(world_id, WorldState.OFF)
            return RestoreResult(restore_id, 'reverted', rollback_op['op_id'])
        except Exception:
            self._operations.transition(
                rollback_op['op_id'],
                OperationStatus.FAILED,
                error_code='RESTORE_REVERT_FAILED',
            )
            self._update_restore_outcome(restore_id, 'failed')
            self._set_world_state(world_id, WorldState.ERROR)
            raise

    def _restart_succeeded(self, world_id: str) -> bool:
        if self._restart_probe is None:
            return False
        try:
            return self._restart_probe.restart_and_confirm(world_id)
        except Exception:
            return False

    def _switch_world(self, world_dir: Path, staging_dir: Path) -> None:
        archive_dir = world_dir.with_name(f'{world_dir.name}.restore-archive-{uuid.uuid4().hex[:8]}')
        archived_original = world_dir.exists()
        if archived_original:
            shutil.move(str(world_dir), str(archive_dir))
        try:
            shutil.move(str(staging_dir), str(world_dir))
        except Exception:
            if archived_original and archive_dir.exists():
                if world_dir.is_symlink() or world_dir.is_file():
                    world_dir.unlink()
                elif world_dir.exists():
                    shutil.rmtree(world_dir)
                shutil.move(str(archive_dir), str(world_dir))
            raise

    def _record_history(
        self,
        *,
        world_id: str,
        operation_id: str,
        source_artifact_id: str,
        pre_restore_artifact_id: str,
        operator_user_id: str,
        outcome: str,
        rollback_of_restore_id: str | None = None,
    ) -> str:
        restore_id = f'rs_{uuid.uuid4().hex[:16]}'
        now = int(self._clock.now())
        connection = self._store.writer()
        connection.execute(
            """
            INSERT INTO restore_history (
                restore_id, world_id, operation_id, source_artifact_id,
                pre_restore_artifact_id, operator_user_id, outcome,
                rollback_of_restore_id, started_at, finished_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                restore_id,
                world_id,
                operation_id,
                source_artifact_id,
                pre_restore_artifact_id,
                operator_user_id,
                outcome,
                rollback_of_restore_id,
                now,
                now,
                now,
            ),
        )
        connection.commit()
        return restore_id

    def _update_restore_outcome(self, restore_id: str, outcome: str) -> None:
        connection = self._store.writer()
        connection.execute('UPDATE restore_history SET outcome = ?, finished_at = ? WHERE restore_id = ?', (outcome, int(self._clock.now()), restore_id))
        connection.commit()

    def _set_world_state(self, world_id: str, state: WorldState) -> None:
        connection = self._store.writer()
        connection.execute(
            'UPDATE world_instances SET state = ?, updated_at = ? WHERE world_id = ?',
            (state.value, int(self._clock.now()), world_id),
        )
        connection.commit()
