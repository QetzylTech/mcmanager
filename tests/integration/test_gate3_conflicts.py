"""Gate 3 Doc 9 queue, reject, ignore, and preemption contracts."""

from __future__ import annotations

import pytest

from app.domain.value_objects import ActorType, OperationStatus, OperationType
from app.services.operations import OperationConflictError, OperationInput, OperationService

from ._gate3_support import seed_world


def _create(
    operations: OperationService,
    world_id: str,
    op_type: OperationType,
    *,
    status: OperationStatus = OperationStatus.RUNNING,
    idempotency_key: str | None = None,
    allow_world_conflict: bool = False,
) -> dict:
    return operations.create(
        OperationInput(
            op_type=op_type,
            actor_type=ActorType.SYSTEM,
            world_id=world_id,
            idempotency_key=idempotency_key,
        ),
        initial_status=status,
        allow_world_conflict=allow_world_conflict,
    )


@pytest.mark.parametrize(
    'op_type',
    [OperationType.BACKUP, OperationType.RESTORE, OperationType.CLEANUP],
)
def test_same_class_destructive_requests_queue_single_flight(store, clock, op_type) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    active = _create(operations, world_id, op_type)

    queued = _create(operations, world_id, op_type, status=OperationStatus.QUEUED)

    assert queued['op_id'] != active['op_id']
    assert queued['status'] == OperationStatus.QUEUED.value


def test_restore_is_rejected_while_backup_is_running(store, clock) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    _create(operations, world_id, OperationType.BACKUP)

    with pytest.raises(OperationConflictError):
        _create(operations, world_id, OperationType.RESTORE)


def test_duplicate_start_trigger_is_ignored_without_another_operation(store, clock) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    first = _create(operations, world_id, OperationType.START)

    _create(operations, world_id, OperationType.START)

    rows = store.reader().execute(
        'SELECT op_id FROM operations WHERE world_id = ? AND op_type = ?',
        (world_id, OperationType.START.value),
    ).fetchall()
    assert [row['op_id'] for row in rows] == [first['op_id']]


def test_kill_preempts_stop_and_is_the_only_in_flight_operation(store, clock) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    stop = _create(operations, world_id, OperationType.STOP)

    kill = _create(operations, world_id, OperationType.KILL)

    stop_row = store.reader().execute(
        'SELECT status, error_code FROM operations WHERE op_id = ?', (stop['op_id'],)
    ).fetchone()
    assert stop_row['status'] == OperationStatus.CANCELLED.value
    assert stop_row['error_code'] == 'superseded_by_kill'
    assert operations.has_in_flight_operation(world_id, exclude_op_id=kill['op_id']) is False
    assert operations.has_in_flight_operation(world_id)


def test_restore_preempts_queued_delete_for_same_world(store, clock) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    delete = _create(
        operations,
        world_id,
        OperationType.DELETE_WORLD,
        status=OperationStatus.QUEUED,
    )

    restore = _create(
        operations,
        world_id,
        OperationType.RESTORE,
        status=OperationStatus.QUEUED,
    )

    deleted = store.reader().execute(
        'SELECT status FROM operations WHERE op_id = ?', (delete['op_id'],)
    ).fetchone()
    assert deleted['status'] == OperationStatus.CANCELLED.value
    assert restore['status'] == OperationStatus.QUEUED.value
