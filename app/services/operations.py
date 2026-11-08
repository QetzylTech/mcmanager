"""Write-optimized operation engine with derived world locking (Gate 3)."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from app.domain.value_objects import ActorType, OperationStatus, OperationType
from app.ports.clock import Clock
from app.ports.persistence import PersistencePort
from app.services.audit import ActorSnapshot, AuditService
from app.services.notifications import NotificationService
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
_CANCELLABLE_TYPES = {
    OperationType.CREATE_WORLD.value,
    OperationType.BACKUP.value,
    OperationType.RESTORE.value,
    OperationType.CLEANUP.value,
    OperationType.SYNC.value,
    OperationType.DELETE_WORLD.value,
}


class OperationConflictError(Exception):
    """Raised when a derived world lock blocks a new operation."""


class OperationStateError(Exception):
    """Raised for invalid operation status transitions."""


class OperationNotCancellableError(Exception):
    """Raised when an operation type or status cannot be cancelled."""


@dataclass(frozen=True)
class OperationInput:
    op_type: OperationType
    actor_type: ActorType
    world_id: str | None = None
    actor_user_id: str | None = None
    idempotency_key: str | None = None
    data: dict[str, Any] | None = None
    compensates_operation_id: str | None = None


class OperationService:
    """Creates, queries, checkpoints, and terminalizes operation rows."""

    def __init__(
        self,
        store: PersistencePort,
        clock: Clock,
        audit: AuditService | None = None,
        realtime: RealtimeHub | None = None,
        notifications: NotificationService | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._audit = audit or AuditService(store, clock)
        self._realtime = realtime
        self._notifications = notifications
        self._progress_cache: dict[str, dict[str, Any]] = {}
        self._pending_checkpoints: dict[str, dict[str, Any]] = {}
        self._cancellation_events: dict[str, set[threading.Event]] = {}
        self._cancellation_lock = threading.Lock()
        self._progress_lock = threading.RLock()

    def register_cancellation(self, op_id: str) -> threading.Event:
        """Register a cooperative cancellation signal for active operation work."""
        event = threading.Event()
        with self._cancellation_lock:
            row = self._store.reader().execute(
                'SELECT status FROM operations WHERE op_id = ?', (op_id,)
            ).fetchone()
            if row is None or row['status'] == OperationStatus.CANCELLED.value:
                event.set()
            self._cancellation_events.setdefault(op_id, set()).add(event)
        return event

    def unregister_cancellation(self, op_id: str, event: threading.Event) -> None:
        """Remove a finished worker's cancellation signal."""
        with self._cancellation_lock:
            events = self._cancellation_events.get(op_id)
            if events is None:
                return
            events.discard(event)
            if not events:
                self._cancellation_events.pop(op_id, None)

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

    def has_active_operation(self, world_id: str, *, exclude_op_id: str) -> bool:
        statuses = (
            OperationStatus.CREATED.value,
            OperationStatus.VALIDATING.value,
            OperationStatus.RUNNING.value,
        )
        row = self._store.reader().execute(
            f"""
            SELECT 1
            FROM operations
            WHERE world_id = ?
              AND op_id <> ?
              AND status IN ({','.join('?' for _ in statuses)})
            LIMIT 1
            """,
            (world_id, exclude_op_id, *statuses),
        ).fetchone()
        return row is not None

    def create(
        self,
        request: OperationInput,
        *,
        initial_status: OperationStatus = OperationStatus.QUEUED,
        allow_world_conflict: bool = False,
    ) -> dict[str, Any]:
        operation, _ = self.create_with_replay(
            request,
            initial_status=initial_status,
            allow_world_conflict=allow_world_conflict,
        )
        return operation

    def create_with_replay(
        self,
        request: OperationInput,
        *,
        initial_status: OperationStatus = OperationStatus.QUEUED,
        allow_world_conflict: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        """Create an operation and report whether an existing request was replayed."""
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
                    return dict(existing), True

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
            if request.op_type == OperationType.SYNC:
                artifact_id = self._sync_artifact_id(request.data)
                if artifact_id is not None and self._has_in_flight_sync(
                    connection, artifact_id
                ):
                    status = OperationStatus.QUEUED

            if request.op_type == OperationType.CLEANUP:
                cleanup_scope = self._cleanup_scope(
                    {'world_id': request.world_id, 'data_json': json.dumps(request.data or {})}
                )
                if cleanup_scope is not None and self._has_in_flight_cleanup_scope(
                    connection, cleanup_scope
                ):
                    status = OperationStatus.QUEUED

            if (
                request.world_id is not None
                and not allow_world_conflict
                and request.op_type != OperationType.SYNC
            ):
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
                    return repeated, True
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 1, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)
                """,
                (
                    op_id,
                    request.op_type.value,
                    request.world_id,
                    request.actor_type.value,
                    request.actor_user_id,
                    request.idempotency_key,
                    status.value,
                    request.compensates_operation_id,
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
        return created, False

    def get_by_idempotency_key(
        self, op_type: OperationType, idempotency_key: str
    ) -> dict[str, Any] | None:
        row = self._store.reader().execute(
            'SELECT * FROM operations WHERE op_type = ? AND idempotency_key = ?',
            (op_type.value, idempotency_key),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_queued(
        self, op_types: tuple[OperationType, ...]
    ) -> list[dict[str, Any]]:
        if not op_types:
            return []
        rows = self._store.reader().execute(
            f"""
            SELECT *
            FROM operations
            WHERE status = ?
              AND op_type IN ({','.join('?' for _ in op_types)})
            ORDER BY created_at ASC, op_id ASC
            """,
            (OperationStatus.QUEUED.value, *(op_type.value for op_type in op_types)),
        ).fetchall()
        return [dict(row) for row in rows]

    def claim_queued(self, op_id: str) -> dict[str, Any] | None:
        """Atomically claim a durable queued operation for one dispatcher."""
        connection = self._store.writer()
        now = int(self._clock.now())
        try:
            connection.execute('BEGIN IMMEDIATE')
            current = connection.execute(
                'SELECT world_id, op_type FROM operations WHERE op_id = ? AND status = ?',
                (op_id, OperationStatus.QUEUED.value),
            ).fetchone()
            if current is None:
                connection.commit()
                return None
            if (
                current['world_id'] is not None
                and current['op_type'] != OperationType.SYNC.value
            ):
                active_statuses = (
                    OperationStatus.CREATED.value,
                    OperationStatus.VALIDATING.value,
                    OperationStatus.RUNNING.value,
                )
                active = connection.execute(
                    f"""
                    SELECT 1 FROM operations
                    WHERE world_id = ?
                      AND op_id <> ?
                      AND status IN ({','.join('?' for _ in active_statuses)})
                    LIMIT 1
                    """,
                    (current['world_id'], op_id, *active_statuses),
                ).fetchone()
                if active is not None:
                    connection.commit()
                    return None
            cursor = connection.execute(
                """
                UPDATE operations
                SET status = ?, started_at = COALESCE(started_at, ?), updated_at = ?
                WHERE op_id = ? AND status = ?
                """,
                (
                    OperationStatus.RUNNING.value,
                    now,
                    now,
                    op_id,
                    OperationStatus.QUEUED.value,
                ),
            )
            if cursor.rowcount != 1:
                connection.commit()
                return None
            row = connection.execute(
                'SELECT * FROM operations WHERE op_id = ?', (op_id,)
            ).fetchone()
            claimed = dict(row)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        self._publish_status(claimed, OperationStatus.RUNNING)
        return claimed

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
            cleanup_scope = self._cleanup_scope(
                {'world_id': request.world_id, 'data_json': json.dumps(request.data or {})}
            )
            matching_cleanup = [
                row
                for row in active
                if row['op_type'] == OperationType.CLEANUP.value
                and cleanup_scope is not None
                and self._cleanup_scope(row) == cleanup_scope
            ]
            if matching_cleanup:
                return active, OperationStatus.QUEUED, []
            conflicting = active_types - _RUNTIME_TYPES - {OperationType.CLEANUP.value}
            if conflicting:
                raise OperationConflictError(
                    f'Cleanup conflicts with in-flight operation for world {request.world_id}'
                )
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

    @staticmethod
    def _sync_artifact_id(data: dict[str, Any] | None) -> str | None:
        artifact_id = (data or {}).get('artifact_id')
        return artifact_id if isinstance(artifact_id, str) and artifact_id else None

    @staticmethod
    def _cleanup_scope(operation: dict[str, Any]) -> str | None:
        data_json = operation.get('data_json')
        try:
            data = json.loads(data_json or '{}')
        except (json.JSONDecodeError, TypeError):
            data = {}
        scope = data.get('scope')
        if isinstance(scope, str) and scope:
            return scope
        world_id = operation.get('world_id')
        return f'world:{world_id}' if world_id is not None else None

    @classmethod
    def _has_in_flight_sync(
        cls, connection: sqlite3.Connection, artifact_id: str
    ) -> bool:
        rows = connection.execute(
            f"""
            SELECT data_json FROM operations
            WHERE op_type = ? AND status IN ({','.join('?' for _ in IN_FLIGHT_STATUSES)})
            """,
            (OperationType.SYNC.value, *IN_FLIGHT_STATUSES),
        ).fetchall()
        return any(
            cls._sync_artifact_id(
                json.loads(row['data_json'] or '{}')
                if row['data_json'] is not None
                else None
            )
            == artifact_id
            for row in rows
        )

    @classmethod
    def _has_in_flight_cleanup_scope(
        cls, connection: sqlite3.Connection, scope: str
    ) -> bool:
        rows = connection.execute(
            f"""
            SELECT world_id, data_json FROM operations
            WHERE op_type = ? AND status IN ({','.join('?' for _ in IN_FLIGHT_STATUSES)})
            """,
            (OperationType.CLEANUP.value, *IN_FLIGHT_STATUSES),
        ).fetchall()
        return any(cls._cleanup_scope(dict(row)) == scope for row in rows)

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
                if self._notifications is not None:
                    self._notifications.publish_terminal_operation(
                        updated, connection=connection
                    )
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
        event_payload = {
            'world_id': row['world_id'],
            'operation_id': op_id,
            'stage': step_name,
            'pct': progress_pct,
        }
        if row['op_type'] == OperationType.BACKUP.value:
            self._publish('backup.progress', event_payload, row['world_id'])
        elif row['op_type'] == OperationType.RESTORE.value:
            self._publish(
                'restore.progress',
                {**event_payload, 'reverted': False},
                row['world_id'],
            )

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
        payload = {
            'op_type': operation['op_type'],
            'status': operation['status'],
            'error_code': operation['error_code'],
            'message': operation['message'],
        }
        if operation['op_type'] == OperationType.CONFIG_EDIT.value:
            try:
                config_edit = json.loads(operation['data_json'] or '{}')
            except json.JSONDecodeError:
                config_edit = {}
            payload.update(
                {
                    key: config_edit.get(key, {})
                    for key in ('entity', 'row_id', 'before', 'after')
                }
            )
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
            payload=payload,
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
        if position > 0:
            self._publish(
                'queue.position',
                {
                    'op_id': operation['op_id'],
                    'op_type': operation['op_type'],
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
        if self._realtime is not None:
            notification = self._store.reader().execute(
                """
                SELECT notification_id, category, severity, message,
                       related_operation_id, related_world_id, requires_action,
                       action_taken, created_at
                FROM notifications
                WHERE related_operation_id = ?
                """,
                (operation['op_id'],),
            ).fetchone()
            if notification is not None:
                self._publish(
                    'notification',
                    dict(notification),
                    operation['world_id'],
                )

    def _publish(self, event: str, payload: dict[str, Any], world_id: str | None) -> None:
        if self._realtime is None:
            return
        self._realtime.publish('events', event, payload)
        if world_id is not None:
            self._realtime.publish(f'world:{world_id}:events', event, payload)

    def publish_event(
        self, event: str, payload: dict[str, Any], *, world_id: str | None = None
    ) -> None:
        self._publish(event, payload, world_id)

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

    def list_operations(
        self,
        *,
        world_id: str | None = None,
        op_type: str | None = None,
        status: str | None = None,
        actor_user_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sort: tuple[tuple[str, bool], ...] = (("created_at", True),),
    ) -> tuple[list[dict[str, Any]], int]:
        """Return a filtered operation page and its total row count."""
        sort_columns = {
            "created_at": "created_at",
            "op_type": "op_type",
            "status": "status",
            "world_id": "world_id",
            "actor_user_id": "actor_user_id",
        }
        if not sort or any(field not in sort_columns for field, _ in sort):
            raise ValueError("unsupported operation sort field")

        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("world_id", world_id),
            ("op_type", op_type),
            ("status", status),
            ("actor_user_id", actor_user_id),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        connection = self._store.reader()
        total = connection.execute(
            "SELECT count(*) FROM operations" + where, params
        ).fetchone()[0]
        ordering = ", ".join(
            f"{sort_columns[field]} {'DESC' if descending else 'ASC'}"
            for field, descending in sort
        )
        ordering += ", op_id DESC"
        rows = connection.execute(
            "SELECT * FROM operations" + where + " ORDER BY " + ordering + " LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [dict(row) for row in rows], int(total)

    def get(self, op_id: str) -> dict[str, Any] | None:
        """Return the persisted operation record for a read-only API view."""
        row = self._store.reader().execute(
            'SELECT * FROM operations WHERE op_id = ?', (op_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def cancel(self, op_id: str) -> dict[str, Any]:
        """Atomically cancel an eligible operation and append its terminal audit."""
        connection = self._store.writer()
        now = int(self._clock.now())
        try:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute(
                'SELECT * FROM operations WHERE op_id = ?', (op_id,)
            ).fetchone()
            if row is None:
                raise OperationStateError(f'operation not found: {op_id}')

            current = dict(row)
            current_status = current['status']
            cancellable_status = current_status in {
                OperationStatus.QUEUED.value,
                OperationStatus.VALIDATING.value,
            } or (
                current_status == OperationStatus.RUNNING.value
                and current['op_type'] == OperationType.SYNC.value
            )
            if current['op_type'] not in _CANCELLABLE_TYPES or not cancellable_status:
                raise OperationNotCancellableError(op_id)

            cursor = connection.execute(
                """
                UPDATE operations
                SET status = ?, finished_at = ?, error_code = NULL,
                    message = ?, updated_at = ?
                WHERE op_id = ? AND op_type = ? AND status = ?
                """,
                (
                    OperationStatus.CANCELLED.value,
                    now,
                    'Cancelled by administrator.',
                    now,
                    op_id,
                    current['op_type'],
                    current_status,
                ),
            )
            if cursor.rowcount != 1:
                raise OperationNotCancellableError(op_id)

            cancelled = dict(
                connection.execute(
                    'SELECT * FROM operations WHERE op_id = ?', (op_id,)
                ).fetchone()
            )
            self._write_terminal_audit(connection, cancelled)
            if self._notifications is not None:
                self._notifications.publish_terminal_operation(
                    cancelled, connection=connection
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        with self._progress_lock:
            self._progress_cache.pop(op_id, None)
            self._pending_checkpoints.pop(op_id, None)
        with self._cancellation_lock:
            for event in self._cancellation_events.get(op_id, ()):
                event.set()
        self._publish_terminal(cancelled)
        return cancelled
