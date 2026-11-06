"""Gate 3 operation persistence and terminal-audit acceptance contracts."""

from __future__ import annotations

from app.domain.value_objects import ActorType, OperationStatus, OperationType
from app.services.operations import OperationInput, OperationService

from ._gate3_support import seed_world


def _create_operation(operations: OperationService, world_id: str) -> str:
    return operations.create(
        OperationInput(
            op_type=OperationType.BACKUP,
            actor_type=ActorType.SYSTEM,
            world_id=world_id,
        ),
        initial_status=OperationStatus.CREATED,
    )['op_id']


def test_progress_ticks_remain_in_memory_until_a_milestone(store, clock) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    op_id = _create_operation(operations, world_id)
    before = dict(
        store.reader()
        .execute('SELECT * FROM operations WHERE op_id = ?', (op_id,))
        .fetchone()
    )

    operations.update_progress_in_memory(op_id, progress_pct=37, step_name='copying_archive')

    after = dict(
        store.reader()
        .execute('SELECT * FROM operations WHERE op_id = ?', (op_id,))
        .fetchone()
    )
    assert operations._progress_cache[op_id] == {
        'progress_pct': 37,
        'step': 'copying_archive',
        'ts': int(clock.now()),
    }
    assert after == before


def test_non_milestone_transition_does_not_write_operation_row(store, clock) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    op_id = _create_operation(operations, world_id)

    operations.transition(op_id, OperationStatus.VALIDATING, checkpoint={'stage': 'checking'})

    row = store.reader().execute(
        'SELECT status, checkpoint FROM operations WHERE op_id = ?', (op_id,)
    ).fetchone()
    assert row['status'] == OperationStatus.CREATED.value
    assert row['checkpoint'] is None


def test_terminal_transition_emits_exactly_one_operation_audit(store, clock) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    op_id = _create_operation(operations, world_id)
    operations.transition(op_id, OperationStatus.RUNNING)

    assert (
        store.reader()
        .execute('SELECT COUNT(*) FROM audit_records WHERE operation_id = ?', (op_id,))
        .fetchone()[0]
        == 0
    )

    operations.transition(op_id, OperationStatus.COMPLETED)
    rows = store.reader().execute(
        'SELECT operation_id FROM audit_records WHERE operation_id = ?', (op_id,)
    ).fetchall()
    assert len(rows) == 1
