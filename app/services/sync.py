"""Offsite artifact synchronization with bounded retry and transfer policy."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from datetime import time as datetime_time
from pathlib import Path
from typing import Any

from app.domain.tuning import SYNC_BACKOFF_BASE_S, SYNC_TRANSIENT_RETRIES
from app.domain.value_objects import (
    ActorType,
    OperationStatus,
    OperationType,
    SyncOutcome,
    SyncRecordStatus,
)
from app.infrastructure.sqlite.connection import SqliteStore
from app.ports.clock import Clock, SystemClock
from app.ports.sync_transport import SyncTransportPort
from app.services.operations import OperationInput, OperationService


class SyncError(Exception):
    """Raised when a sync request cannot be dispatched safely."""


class SyncService:
    """Record sync jobs and their immutable retry timeline."""

    BACKOFF_DELAYS = tuple(
        SYNC_BACKOFF_BASE_S * (2**index) for index in range(SYNC_TRANSIENT_RETRIES)
    )
    DAILY_TRANSFER_CAP_BYTES = 50 * 1024**3

    def __init__(
        self,
        store: SqliteStore,
        transport: SyncTransportPort,
        clock: Clock | None = None,
        operations: OperationService | None = None,
    ) -> None:
        self._store = store
        self._transport = transport
        self._clock = clock or SystemClock()
        self._operations = operations or OperationService(store, self._clock)

    def get_bytes_transferred_today(self) -> int:
        now = datetime.fromtimestamp(self._clock.now(), UTC)
        start = int(datetime.combine(now.date(), datetime_time.min, UTC).timestamp())
        end = start + 24 * 60 * 60
        row = self._store.reader().execute(
            """
            SELECT COALESCE(SUM(backup_artifacts.size_bytes), 0) AS transferred
            FROM sync_attempts
            JOIN sync_records USING (sync_id)
            JOIN backup_artifacts USING (artifact_id)
            WHERE sync_attempts.outcome = ?
              AND sync_attempts.finished_at >= ?
              AND sync_attempts.finished_at < ?
            """,
            (SyncOutcome.SUCCEEDED.value, start, end),
        ).fetchone()
        return int(row['transferred'])

    def dispatch_sync(self, artifact_id: str, target_id: str) -> str:
        """Upload an artifact and return its durable sync-record id.

        This method is intended to be dispatched by a worker. BackupService
        never calls it, so remote outages cannot delay local artifact creation.
        """
        if self.get_bytes_transferred_today() >= self.DAILY_TRANSFER_CAP_BYTES:
            raise SyncError('SYNC_CAP_EXCEEDED')
        artifact = self._store.reader().execute(
            """
            SELECT artifact_id, world_id, storage_path, size_bytes
            FROM backup_artifacts
            WHERE artifact_id = ? AND deleted_at IS NULL
            """,
            (artifact_id,),
        ).fetchone()
        if artifact is None:
            raise SyncError(f'BACKUP_NOT_FOUND: {artifact_id}')
        if (
            self.get_bytes_transferred_today() + int(artifact['size_bytes'])
            > self.DAILY_TRANSFER_CAP_BYTES
        ):
            raise SyncError('SYNC_CAP_EXCEEDED')
        target = self._resolve_target(target_id)

        now = int(self._clock.now())
        operation = self._operations.create(
            OperationInput(
                op_type=OperationType.SYNC,
                actor_type=ActorType.SYSTEM,
                world_id=artifact['world_id'],
                data={'artifact_id': artifact_id, 'sync_target_id': target_id},
            ),
            initial_status=OperationStatus.RUNNING,
            allow_world_conflict=True,
        )
        sync_id = f'sy_{uuid.uuid4().hex[:16]}'
        connection = self._store.writer()
        connection.execute(
            """
            INSERT INTO sync_records (
                sync_id, artifact_id, sync_target_id, operation_id, status,
                started_at, finished_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                sync_id,
                artifact_id,
                target['sync_target_id'],
                operation['op_id'],
                SyncRecordStatus.PENDING.value,
                now,
                now,
            ),
        )
        connection.commit()

        succeeded = False
        for attempt_number in range(1, len(self.BACKOFF_DELAYS) + 2):
            started_at = int(self._clock.now())
            error_message: str | None = None
            outcome = SyncOutcome.SUCCEEDED
            try:
                self._transport.upload_file(target_id, Path(artifact['storage_path']))
                succeeded = True
            except Exception as exc:
                outcome = SyncOutcome.FAILED_TRANSIENT
                error_message = str(exc)[:1000]
            finished_at = int(self._clock.now())
            self._record_attempt(
                sync_id,
                attempt_number,
                started_at,
                finished_at,
                outcome,
                error_message,
            )
            if succeeded:
                break
            if attempt_number <= len(self.BACKOFF_DELAYS):
                time.sleep(self.BACKOFF_DELAYS[attempt_number - 1])

        terminal_status = (
            SyncRecordStatus.SUCCEEDED if succeeded else SyncRecordStatus.FAILED
        )
        finished_at = int(self._clock.now())
        connection = self._store.writer()
        connection.execute(
            'UPDATE sync_records SET status = ?, finished_at = ? WHERE sync_id = ?',
            (terminal_status.value, finished_at, sync_id),
        )
        connection.commit()
        self._operations.transition(
            operation['op_id'],
            OperationStatus.COMPLETED if succeeded else OperationStatus.FAILED,
            error_code=None if succeeded else 'SYNC_FAILED',
            message=None if succeeded else 'offsite upload exhausted transient retries',
            data={'sync_id': sync_id, 'status': terminal_status.value},
        )
        return sync_id

    def _resolve_target(self, target_id: str) -> dict[str, Any]:
        row = self._store.reader().execute(
            """
            SELECT sync_target_id, enabled
            FROM sync_targets
            WHERE sync_target_id = ? AND deleted_at IS NULL
            """,
            (target_id,),
        ).fetchone()
        if row is not None:
            if not row['enabled']:
                raise SyncError(f'SYNC_TARGET_DISABLED: {target_id}')
            return dict(row)

        # A lightweight transport target is useful for configured worker
        # adapters in installations that have not yet exposed target CRUD.
        secret = self._store.reader().execute(
            'SELECT secret_id FROM secrets ORDER BY created_at LIMIT 1'
        ).fetchone()
        if secret is None:
            raise SyncError(f'SYNC_TARGET_NOT_FOUND: {target_id}')
        connection = self._store.writer()
        connection.execute(
            """
            INSERT INTO sync_targets (
                sync_target_id, scope, world_id, target_type, config, secret_id,
                enabled, version, deleted_at, deleted_by, created_at, updated_at
            ) VALUES (?, 'global', NULL, 'nas', ?, ?, 1, 1, NULL, NULL, ?, ?)
            """,
            (
                target_id,
                json.dumps({'adapter': 'nas'}),
                secret['secret_id'],
                int(self._clock.now()),
                int(self._clock.now()),
            ),
        )
        connection.commit()
        return {'sync_target_id': target_id, 'enabled': 1}

    def _record_attempt(
        self,
        sync_id: str,
        attempt_number: int,
        started_at: int,
        finished_at: int,
        outcome: SyncOutcome,
        error_message: str | None,
    ) -> None:
        connection = self._store.writer()
        connection.execute(
            """
            INSERT INTO sync_attempts (
                attempt_id, sync_id, attempt_number, started_at, finished_at,
                outcome, error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f'sa_{uuid.uuid4().hex[:16]}',
                sync_id,
                attempt_number,
                started_at,
                finished_at,
                outcome.value,
                error_message,
                finished_at,
            ),
        )
        connection.commit()
