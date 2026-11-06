"""Write-optimized operation engine with derived world locking (Gate 3)."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from app.domain.value_objects import ActorType, OperationStatus, OperationType
from app.infrastructure.sqlite.connection import SqliteStore
from app.ports.clock import Clock
from app.services.audit import ActorSnapshot, AuditService
from app.services.realtime import RealtimeHub

IN_FLIGHT_STATUSES = (
    OperationStatus.CREATED.value,
    OperationStatus.QUEUED.value,
    OperationStatus.VALIDATING.value,
    OperationStatus.RUNNING.value,
)
TERMINAL_STATUSES = (
    OperationStatus.COMPLETED.value,
    OperationStatus.FAILED.value,
    OperationStatus.CANCELLED.value,
    OperationStatus.TIMED_OUT.value,
)

_SINGLE_FLIGHT_TYPES = {
    OperationType.BACKUP.value,
    OperationType.RESTORE.value,
    OperationType.CLEANUP.value,
}
_RUNTIME_TYPES = {
    OperationType.START.value,
    OperationType.STOP.value,
    OperationType.KILL.value,
}


class OperationConflictError(Exception):
    """Raised when a derived world lock blocks a new operation."""


class OperationStateError(Exception):
    """Raised for invalid operation status transitions."""


@dataclass(frozen=True)
class OperationInput:
    op_type: OperationType
    actor_type: ActorType
    world_id: str | None = None
    actor_user_id: str | None = None
    idempotency_key: str | None = None
    data: dict[str, Any] | None = None


class OperationService:
    """Creates, queries, checkpoints, and terminalizes operation rows."""

    def __init__(
        self,
        store: SqliteStore,
        clock: Clock,
        audit: AuditService | None = None,
        realtime: RealtimeHub | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._audit = audit or AuditService(store, clock)
        self._realtime = realtime
        self._progress_cache: dict[str, dict[str, Any]] = {}
        self._pending_checkpoints: dict[str, dict[str, Any]] = {}
        self._progress_lock = threading.RLock()

    def has_in_flight_operation(self, world_id: str, *, exclude_op_id: str | None = None) -> bool:
        """Derived world lock query (Doc 9 section 1.1)."""
        params: list[Any] = [world_id, *IN_FLIGHT_STATUSES]
        exclusion = ''
        if exclude_op_id is not None:
            exclusion = ' AND op_id <> ?'
            params.append(exclude_op_id)
        row = self._store.reader().execute(
            f"""
            SELECT 1
            FROM operations
            WHERE world_id = ?
              AND status IN ({','.join('?' for _ in IN_FLIGHT_STATUSES)})
              {exclusion}
            LIMIT 1
            """,
            params,
        ).fetchone()
        return row is not None

    def create(
        self,
        request: OperationInput,
        *,
        initial_status: OperationStatus = OperationStatus.QUEUED,
        allow_world_conflict: bool = False,
    ) -> dict[str, Any]:
        """Create an operation, applying Doc 9 queue/reject/ignore/preempt rules."""
        connection = self._store.writer()
        now = int(self._clock.now())
        terminal_audits: list[dict[str, Any]] = []
        created: dict[str, Any] | None = None
        try:
            connection.execute('BEGIN IMMEDIATE')
            if request.idempotency_key is not None:
                existing = connection.execute(
                    'SELECT * FROM operations WHERE op_type = ? AND idempotency_key = ?',
                    (request.op_type.value, request.idempotency_key),
                ).fetchone()
                if existing is not None:
                    connection.commit()
                    return dict(existing)

            active: list[dict[str, Any]] = []
            if request.world_id is not None:
                rows = connection.execute(
                    f"""
                    SELECT * FROM operations
                    WHERE world_id = ?
                      AND status IN ({','.join('?' for _ in IN_FLIGHT_STATUSES)})
                    ORDER BY created_at ASC
                    """,
                    (request.world_id, *IN_FLIGHT_STATUSES),
                ).fetchall()
                active = [dict(row) for row in rows]

            status = initial_status
            if request.world_id is not None and not allow_world_conflict:
                repeated = next(
                    (
                        row
                        for row in active
                        if row['op_type'] == request.op_type.value
                        and request.op_type
                        in (OperationType.START, OperationType.STOP)
                    ),
                    None,
                )
                if repeated is not None:
                    connection.commit()
                    return repeated
                active, status, terminal_audits = self._apply_conflict_policy(
                    connection, request, active, status, now
                )

            op_id = f'op_{uuid.uuid4().hex[:16]}'
            connection.execute(
                """
                INSERT INTO operations (
                    op_id, op_type, world_id, actor_type, actor_user_id,
                    idempotency_key, status, checkpoint, attempt,
                    compensates_operation_id, intent_at, started_at,
                    finished_at, error_code, message, data_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 1, NULL, ?, ?, NULL, NULL, NULL, ?, ?, ?)
                """,
                (
                    op_id,
                    request.op_type.value,
                    request.world_id,
                    request.actor_type.value,
                    request.actor_user_id,
                    request.idempotency_key,
                    status.value,
                    now,
                    now if status == OperationStatus.RUNNING else None,
                    json.dumps(request.data) if request.data is not None else None,
                    now,
                    now,
                ),
            )
            row = connection.execute('SELECT * FROM operations WHERE op_id = ?', (op_id,)).fetchone()
            created = dict(row)
            for terminal_row in terminal_audits:
                self._write_terminal_audit(connection, terminal_row)
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        for terminal_row in terminal_audits:
            self._publish_terminal(terminal_row)
        assert created is not None
        self._publish_created(created)
        return created

    def _apply_conflict_policy(
        self,
        connection: sqlite3.Connection,
        request: OperationInput,
        active: list[dict[str, Any]],
        status: OperationStatus,
        now: int,
    ) -> tuple[list[dict[str, Any]], OperationStatus, list[dict[str, Any]]]:
        if not active:
            return active, status, []

        op_type = request.op_type.value
        same_type = [row for row in active if row['op_type'] == op_type]
        if same_type and op_type not in _SINGLE_FLIGHT_TYPES:
            raise OperationConflictError(f'{op_type} is already in flight for world {request.world_id}')

        if op_type == OperationType.KILL.value:
            stops = [row for row in active if row['op_type'] == OperationType.STOP.value]
            if stops and {row['op_type'] for row in active} == {OperationType.STOP.value}:
                terminal_rows: list[dict[str, Any]] = []
                for stop in stops:
                    cancelled = self._cancel_row(
                        connection, stop, now, error_code='superseded_by_kill'
                    )
                    terminal_rows.append(cancelled)
                return [], status, terminal_rows

        if op_type == OperationType.RESTORE.value:
            deletes = [
                row
                for row in active
                if row['op_type'] == OperationType.DELETE_WORLD.value
                and row['status'] == OperationStatus.QUEUED.value
            ]
            if deletes:
                terminal_rows = []
                for delete in deletes:
                    terminal_rows.append(
                        self._cancel_row(
                            connection,
                            delete,
                            now,
                            error_code='superseded_by_restore',
                        )
                    )
                active = [row for row in active if row not in deletes]
                if not active:
                    return active, status, terminal_rows
                active_types = {row['op_type'] for row in active}
                if active_types == {OperationType.RESTORE.value}:
                    return active, OperationStatus.QUEUED, terminal_rows
                if active_types != {OperationType.RESTORE.value}:
                    raise OperationConflictError(
                        f'restore conflicts with an in-flight operation for world {request.world_id}'
                    )

        active_types = {row['op_type'] for row in active}
        if op_type == OperationType.BACKUP.value:
            conflicting = active_types - _RUNTIME_TYPES
            if conflicting - {OperationType.BACKUP.value}:
                raise OperationConflictError(
                    f'Backup conflicts with in-flight operation for world {request.world_id}'
                )
            if OperationType.BACKUP.value in active_types:
                return active, OperationStatus.QUEUED, []
            return active, status, []

        if op_type == OperationType.RESTORE.value and active_types == {
            OperationType.RESTORE.value
        }:
            return active, OperationStatus.QUEUED, []

        if op_type == OperationType.CLEANUP.value:
            conflicting = active_types - _RUNTIME_TYPES
            if conflicting - {OperationType.CLEANUP.value}:
                raise OperationConflictError(
                    f'Cleanup conflicts with in-flight operation for world {request.world_id}'
                )
            if OperationType.CLEANUP.value in active_types:
                return active, OperationStatus.QUEUED, []
            return active, status, []

        if op_type == OperationType.STOP.value:
            if OperationType.BACKUP.value in active_types:
                if active_types - {
                    OperationType.BACKUP.value,
                    OperationType.CLEANUP.value,
                }:
                    raise OperationConflictError(
                        f'Stop conflicts with in-flight operation for world {request.world_id}'
                    )
                return active, OperationStatus.QUEUED, []
            if active_types.issubset({OperationType.CLEANUP.value}):
                return active, status, []

        if op_type in (OperationType.START.value, OperationType.KILL.value) and active_types.issubset(
            {OperationType.BACKUP.value, OperationType.CLEANUP.value}
        ):
            return active, status, []

        # ConfigEdit, DeleteWorld, and cross-class destructive work reject.
        raise OperationConflictError(
            f'{op_type} conflicts with in-flight operation for world {request.world_id}'
        )

    def _cancel_row(
        self,
        connection: sqlite3.Connection,
        row: dict[str, Any],
        now: int,
        *,
        error_code: str,
    ) -> dict[str, Any]:
        connection.execute(
            """
            UPDATE operations
            SET status = ?, finished_at = ?, error_code = ?, updated_at = ?
            WHERE op_id = ? AND status IN (?, ?, ?, ?)
            """,
            (
                OperationStatus.CANCELLED.value,
                now,
                error_code,
                now,
                row['op_id'],
                *IN_FLIGHT_STATUSES,
            ),
        )
        cancelled = dict(
            connection.execute('SELECT * FROM operations WHERE op_id = ?', (row['op_id'],)).fetchone()
        )
        return cancelled

    def transition(
        self,
        op_id: str,
        status: OperationStatus,
        *,
        checkpoint: dict[str, Any] | None = None,
        error_code: str | None = None,
        message: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist only Running and terminal milestones; intermediate state stays in memory."""
        connection = self._store.writer()
        now = int(self._clock.now())
        terminal = status.value in TERMINAL_STATUSES
        try:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM operations WHERE op_id = ?', (op_id,)).fetchone()
            if row is None:
                raise OperationStateError(f'operation not found: {op_id}')
            current = dict(row)
            if current['status'] in TERMINAL_STATUSES:
                raise OperationStateError(f'operation already terminal: {op_id}')

            if status not in (OperationStatus.RUNNING,) and not terminal:
                if checkpoint is not None:
                    with self._progress_lock:
                        self._pending_checkpoints[op_id] = checkpoint
                connection.commit()
                self._publish_status(current, status, checkpoint=checkpoint)
                return current

            persisted_checkpoint = checkpoint
            if persisted_checkpoint is None:
                with self._progress_lock:
                    persisted_checkpoint = self._pending_checkpoints.get(op_id)
                    if persisted_checkpoint is None:
                        persisted_checkpoint = self._progress_cache.get(op_id)
            checkpoint_json = (
                json.dumps(persisted_checkpoint)
                if persisted_checkpoint is not None
                else current['checkpoint']
            )
            started_at = current['started_at']
            if status == OperationStatus.RUNNING and started_at is None:
                started_at = now
            finished_at = now if terminal else current['finished_at']
            data_json = json.dumps(data) if data is not None else current['data_json']
            connection.execute(
                """
                UPDATE operations
                SET status = ?, checkpoint = ?, started_at = ?, finished_at = ?,
                    error_code = ?, message = ?, data_json = ?, updated_at = ?
                WHERE op_id = ?
                """,
                (
                    status.value,
                    checkpoint_json,
                    started_at,
                    finished_at,
                    error_code,
                    message,
                    data_json,
                    now,
                    op_id,
                ),
            )
            updated = dict(
                connection.execute('SELECT * FROM operations WHERE op_id = ?', (op_id,)).fetchone()
            )
            if terminal:
                self._write_terminal_audit(connection, updated)
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        with self._progress_lock:
            if terminal:
                self._progress_cache.pop(op_id, None)
            self._pending_checkpoints.pop(op_id, None)
        self._publish_terminal(updated) if terminal else self._publish_status(updated, status)
        return updated

    def update_progress_in_memory(
        self, op_id: str, *, progress_pct: int, step_name: str
    ) -> None:
        """Cache and publish a progress tick without touching SQLite."""
        if not 0 <= progress_pct <= 100:
            raise ValueError('progress_pct must be between 0 and 100')
        row = self._store.reader().execute(
            'SELECT * FROM operations WHERE op_id = ?', (op_id,)
        ).fetchone()
        if row is None:
            raise OperationStateError(f'operation not found: {op_id}')
        if row['status'] in TERMINAL_STATUSES:
            raise OperationStateError(f'operation already terminal: {op_id}')
        progress = {'progress_pct': progress_pct, 'step': step_name, 'ts': int(self._clock.now())}
        with self._progress_lock:
            self._progress_cache[op_id] = progress
        payload = {
            'op_id': op_id,
            'op_type': row['op_type'],
            'status': row['status'],
            'checkpoint': progress,
            'pct': progress_pct,
            'step': step_name,
            'ts': progress['ts'],
        }
        self._publish('operation.progress', payload, row['world_id'])

    def _write_terminal_audit(
        self, connection: sqlite3.Connection, operation: dict[str, Any]
    ) -> None:
        actor_type = ActorType(operation['actor_type'])
        username = None
        if operation['actor_user_id'] is not None:
            user = connection.execute(
                'SELECT username FROM users WHERE user_id = ?', (operation['actor_user_id'],)
            ).fetchone()
            username = user['username'] if user is not None else None
        self._audit.write(
            event_type=(
                f"operation.{operation['op_type'].lower()}.{operation['status'].lower()}"
            ),
            actor=ActorSnapshot(
                actor_type=actor_type,
                user_id=operation['actor_user_id'],
                username=username,
            ),
            operation_id=operation['op_id'],
            world_id=operation['world_id'],
            payload={
                'op_type': operation['op_type'],
                'status': operation['status'],
                'error_code': operation['error_code'],
                'message': operation['message'],
            },
            when=operation['finished_at'],
            connection=connection,
        )

    def _publish_created(self, operation: dict[str, Any]) -> None:
        position = 0
        if operation['status'] == OperationStatus.QUEUED.value and operation['world_id'] is not None:
            position = self._store.reader().execute(
                """
                SELECT COUNT(*) FROM operations
                WHERE world_id = ? AND status = ?
                  AND (
                    created_at < ?
                    OR (created_at = ? AND op_id <= ?)
                  )
                """,
                (
                    operation['world_id'],
                    OperationStatus.QUEUED.value,
                    operation['created_at'],
                    operation['created_at'],
                    operation['op_id'],
                ),
            ).fetchone()[0]
        self._publish(
            'operation.created',
            {
                'op_id': operation['op_id'],
                'op_type': operation['op_type'],
                'world_id': operation['world_id'],
                'actor_type': operation['actor_type'],
                'status': operation['status'],
                'queue_position': position,
            },
            operation['world_id'],
        )

    def _publish_status(
        self,
        operation: dict[str, Any],
        status: OperationStatus,
        *,
        checkpoint: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            'op_id': operation['op_id'],
            'op_type': operation['op_type'],
            'status': status.value,
            'checkpoint': checkpoint,
        }
        self._publish('operation.progress', payload, operation['world_id'])

    def _publish_terminal(self, operation: dict[str, Any]) -> None:
        self._publish(
            'operation.terminal',
            {
                'op_id': operation['op_id'],
                'op_type': operation['op_type'],
                'world_id': operation['world_id'],
                'status': operation['status'],
                'error_code': operation['error_code'],
                'message': operation['message'],
            },
            operation['world_id'],
        )

    def _publish(self, event: str, payload: dict[str, Any], world_id: str | None) -> None:
        if self._realtime is None:
            return
        self._realtime.publish('events', event, payload)
        if world_id is not None:
            self._realtime.publish(f'world:{world_id}:events', event, payload)

    def list_incomplete(self) -> list[dict[str, Any]]:
        rows = self._store.reader().execute(
            f"""
            SELECT *
            FROM operations
            WHERE status IN ({','.join('?' for _ in IN_FLIGHT_STATUSES)})
            ORDER BY created_at ASC
            """,
            IN_FLIGHT_STATUSES,
        ).fetchall()
        return [dict(row) for row in rows]

    def get(self, op_id: str) -> dict[str, Any] | None:
        """Return the persisted operation record for a read-only API view."""
        row = self._store.reader().execute(
            'SELECT * FROM operations WHERE op_id = ?', (op_id,)
        ).fetchone()
        return dict(row) if row is not None else None
