"""Durable Operation engine (Gate 3).

Operations are the command plane: world-scoped state changes are represented
by durable rows first, then progress through explicit status transitions.
The per-world lock is derived from non-terminal operation rows, never stored
on ``world_instances``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from app.domain.value_objects import ActorType, OperationStatus, OperationType
from app.infrastructure.sqlite.connection import SqliteStore
from app.ports.clock import Clock

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

    def __init__(self, store: SqliteStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

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
        """Insert an operation row, atomically enforcing the derived lock.

        Idempotency is scoped by ``op_type``. A replay returns the existing row
        without creating a duplicate command.
        """
        connection = self._store.writer()
        now = int(self._clock.now())
        if request.idempotency_key is not None:
            existing = connection.execute(
                'SELECT * FROM operations WHERE op_type = ? AND idempotency_key = ?',
                (request.op_type.value, request.idempotency_key),
            ).fetchone()
            if existing is not None:
                return dict(existing)

        op_id = f'op_{uuid.uuid4().hex[:16]}'
        data_json = json.dumps(request.data) if request.data is not None else None
        try:
            connection.execute('BEGIN IMMEDIATE')
            if request.world_id is not None and not allow_world_conflict:
                conflict = connection.execute(
                    f"""
                    SELECT op_id
                    FROM operations
                    WHERE world_id = ?
                      AND status IN ({','.join('?' for _ in IN_FLIGHT_STATUSES)})
                    LIMIT 1
                    """,
                    (request.world_id, *IN_FLIGHT_STATUSES),
                ).fetchone()
                if conflict is not None:
                    raise OperationConflictError(
                        f"world {request.world_id} already has in-flight operation {conflict['op_id']}"
                    )

            connection.execute(
                """
                INSERT INTO operations (
                    op_id, op_type, world_id, actor_type, actor_user_id,
                    idempotency_key, status, checkpoint, attempt,
                    compensates_operation_id, intent_at, started_at,
                    finished_at, error_code, message, data_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 1, NULL, ?, NULL, NULL, NULL, NULL, ?, ?, ?)
                """,
                (
                    op_id,
                    request.op_type.value,
                    request.world_id,
                    request.actor_type.value,
                    request.actor_user_id,
                    request.idempotency_key,
                    initial_status.value,
                    now,
                    data_json,
                    now,
                    now,
                ),
            )
            row = connection.execute('SELECT * FROM operations WHERE op_id = ?', (op_id,)).fetchone()
            connection.commit()
            return dict(row)
        except Exception:
            connection.rollback()
            raise

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
        """Advance an operation status; terminal operations are immutable."""
        connection = self._store.writer()
        now = int(self._clock.now())
        try:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM operations WHERE op_id = ?', (op_id,)).fetchone()
            if row is None:
                raise OperationStateError(f'operation not found: {op_id}')
            if row['status'] in TERMINAL_STATUSES:
                raise OperationStateError(f'operation already terminal: {op_id}')

            started_at = row['started_at']
            if status in (OperationStatus.VALIDATING, OperationStatus.RUNNING) and started_at is None:
                started_at = now
            finished_at = now if status.value in TERMINAL_STATUSES else row['finished_at']
            data_json = json.dumps(data) if data is not None else row['data_json']
            checkpoint_json = json.dumps(checkpoint) if checkpoint is not None else row['checkpoint']

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
            updated = connection.execute('SELECT * FROM operations WHERE op_id = ?', (op_id,)).fetchone()
            connection.commit()
            return dict(updated)
        except Exception:
            connection.rollback()
            raise

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
