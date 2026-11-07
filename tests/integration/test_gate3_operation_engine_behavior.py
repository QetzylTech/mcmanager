"""Focused Gate 3 operation-engine contracts from Documents 8, 9, and 11."""

from __future__ import annotations

import json

import pytest

from app.domain.value_objects import ActorType, OperationStatus, OperationType
from app.services.operations import OperationConflictError, OperationInput, OperationService
from app.services.realtime import RealtimeHub

from ._gate3_support import seed_world


def _create(
    operations: OperationService,
    op_type: OperationType,
    *,
    world_id: str | None,
    status: OperationStatus = OperationStatus.RUNNING,
    data: dict | None = None,
    idempotency_key: str | None = None,
    allow_world_conflict: bool = False,
) -> dict:
    return operations.create(
        OperationInput(
            op_type=op_type,
            actor_type=ActorType.SYSTEM,
            world_id=world_id,
            idempotency_key=idempotency_key,
            data=data,
        ),
        initial_status=status,
        allow_world_conflict=allow_world_conflict,
    )


def test_progress_is_cached_and_published_without_operation_writes(store, clock) -> None:
    world_id = seed_world(store)
    realtime = RealtimeHub()
    operations = OperationService(store, clock, realtime=realtime)
    operation = _create(
        operations,
        OperationType.BACKUP,
        world_id=world_id,
        status=OperationStatus.CREATED,
    )
    op_id = operation['op_id']
    before = dict(
        store.reader().execute('SELECT * FROM operations WHERE op_id = ?', (op_id,)).fetchone()
    )

    operations.update_progress_in_memory(op_id, progress_pct=37, step_name='copying_archive')
    operations.transition(op_id, OperationStatus.VALIDATING, checkpoint={'stage': 'checking'})

    after = dict(
        store.reader().execute('SELECT * FROM operations WHERE op_id = ?', (op_id,)).fetchone()
    )
    assert after == before
    assert operations._progress_cache[op_id] == {
        'progress_pct': 37,
        'step': 'copying_archive',
        'ts': int(clock.now()),
    }
    for stream in ('events', f'world:{world_id}:events'):
        events = realtime.replay(stream, last_event_id=None)
        assert [event.event for event in events] == [
            'operation.created',
            'operation.progress',
            'backup.progress',
            'operation.progress',
        ]
        assert events[1].data['pct'] == 37
        assert events[2].data['stage'] == 'copying_archive'
        assert events[3].data['status'] == OperationStatus.VALIDATING.value

    operations.transition(op_id, OperationStatus.RUNNING)
    assert store.reader().execute(
        'SELECT status FROM operations WHERE op_id = ?', (op_id,)
    ).fetchone()['status'] == OperationStatus.RUNNING.value


def test_idempotency_replay_returns_original_operation_without_extra_rows(store, clock) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    first = _create(
        operations,
        OperationType.BACKUP,
        world_id=world_id,
        status=OperationStatus.QUEUED,
        idempotency_key='same-backup-trigger',
    )
    replay = _create(
        operations,
        OperationType.BACKUP,
        world_id=world_id,
        status=OperationStatus.QUEUED,
        idempotency_key='same-backup-trigger',
    )

    assert replay['op_id'] == first['op_id']
    assert store.reader().execute(
        'SELECT COUNT(*) FROM operations WHERE idempotency_key = ?',
        ('same-backup-trigger',),
    ).fetchone()[0] == 1


def test_queued_operation_can_be_claimed_only_once(store, clock) -> None:
    operations = OperationService(store, clock)
    operation = _create(
        operations,
        OperationType.START,
        world_id=None,
        status=OperationStatus.QUEUED,
    )

    claimed = operations.claim_queued(operation['op_id'])

    assert claimed is not None
    assert claimed['status'] == OperationStatus.RUNNING.value
    assert operations.claim_queued(operation['op_id']) is None


@pytest.mark.parametrize(
    ('requested', 'active', 'expected'),
    [
        (OperationType.BACKUP, OperationType.BACKUP, 'queued'),
        (OperationType.BACKUP, OperationType.RESTORE, 'reject'),
        (OperationType.BACKUP, OperationType.CLEANUP, 'reject'),
        (OperationType.BACKUP, OperationType.START, 'create'),
        (OperationType.BACKUP, OperationType.STOP, 'create'),
        (OperationType.BACKUP, OperationType.KILL, 'create'),
        (OperationType.RESTORE, OperationType.BACKUP, 'reject'),
        (OperationType.RESTORE, OperationType.RESTORE, 'queued'),
        (OperationType.RESTORE, OperationType.CLEANUP, 'reject'),
        (OperationType.RESTORE, OperationType.START, 'reject'),
        (OperationType.RESTORE, OperationType.STOP, 'reject'),
        (OperationType.RESTORE, OperationType.KILL, 'reject'),
        (OperationType.CLEANUP, OperationType.BACKUP, 'reject'),
        (OperationType.CLEANUP, OperationType.RESTORE, 'reject'),
        (OperationType.CLEANUP, OperationType.CLEANUP, 'queued'),
        (OperationType.CLEANUP, OperationType.START, 'create'),
        (OperationType.CLEANUP, OperationType.STOP, 'create'),
        (OperationType.CLEANUP, OperationType.KILL, 'create'),
        (OperationType.DELETE_WORLD, OperationType.BACKUP, 'reject'),
        (OperationType.DELETE_WORLD, OperationType.RESTORE, 'reject'),
        (OperationType.DELETE_WORLD, OperationType.CLEANUP, 'reject'),
        (OperationType.DELETE_WORLD, OperationType.START, 'reject'),
        (OperationType.DELETE_WORLD, OperationType.STOP, 'reject'),
        (OperationType.DELETE_WORLD, OperationType.KILL, 'reject'),
        (OperationType.START, OperationType.START, 'ignore'),
        (OperationType.START, OperationType.BACKUP, 'create'),
        (OperationType.START, OperationType.CLEANUP, 'create'),
        (OperationType.START, OperationType.STOP, 'reject'),
        (OperationType.START, OperationType.KILL, 'reject'),
        (OperationType.STOP, OperationType.STOP, 'ignore'),
        (OperationType.STOP, OperationType.BACKUP, 'queued'),
        (OperationType.STOP, OperationType.CLEANUP, 'create'),
        (OperationType.STOP, OperationType.START, 'reject'),
        (OperationType.STOP, OperationType.KILL, 'reject'),
        (OperationType.KILL, OperationType.STOP, 'preempt'),
        (OperationType.KILL, OperationType.BACKUP, 'create'),
        (OperationType.KILL, OperationType.CLEANUP, 'create'),
        (OperationType.KILL, OperationType.START, 'reject'),
        (OperationType.KILL, OperationType.KILL, 'reject'),
        (OperationType.BACKUP, OperationType.DELETE_WORLD, 'reject'),
        (OperationType.RESTORE, OperationType.DELETE_WORLD, 'queued'),
        (OperationType.CLEANUP, OperationType.DELETE_WORLD, 'reject'),
        (OperationType.DELETE_WORLD, OperationType.DELETE_WORLD, 'reject'),
        (OperationType.START, OperationType.DELETE_WORLD, 'reject'),
        (OperationType.STOP, OperationType.DELETE_WORLD, 'reject'),
        (OperationType.KILL, OperationType.DELETE_WORLD, 'reject'),
    ],
)
def test_doc9_world_conflict_policy(store, clock, requested, active, expected) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    active_status = (
        OperationStatus.QUEUED
        if active is OperationType.DELETE_WORLD
        else OperationStatus.RUNNING
    )
    active_row = _create(
        operations,
        active,
        world_id=world_id,
        status=active_status,
    )

    def request() -> dict:
        return _create(
            operations,
            requested,
            world_id=world_id,
            status=OperationStatus.QUEUED,
        )

    if expected == 'reject':
        with pytest.raises(OperationConflictError):
            request()
        return

    result = request()
    if expected == 'ignore':
        assert result['op_id'] == active_row['op_id']
    elif expected == 'queued':
        assert result['op_id'] != active_row['op_id']
        assert result['status'] == OperationStatus.QUEUED.value
    elif expected == 'preempt':
        cancelled = store.reader().execute(
            'SELECT status, error_code FROM operations WHERE op_id = ?',
            (active_row['op_id'],),
        ).fetchone()
        assert cancelled['status'] == OperationStatus.CANCELLED.value
        assert cancelled['error_code'] == 'superseded_by_kill'
        assert result['status'] == OperationStatus.QUEUED.value
    else:
        assert result['op_id'] != active_row['op_id']


def test_restore_preempts_queued_delete_and_audits_cancelled_operation_once(store, clock) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    delete = _create(
        operations,
        OperationType.DELETE_WORLD,
        world_id=world_id,
        status=OperationStatus.QUEUED,
    )

    restore = _create(
        operations,
        OperationType.RESTORE,
        world_id=world_id,
        status=OperationStatus.QUEUED,
    )

    row = store.reader().execute(
        'SELECT status, error_code FROM operations WHERE op_id = ?', (delete['op_id'],)
    ).fetchone()
    assert row['status'] == OperationStatus.CANCELLED.value
    assert row['error_code'] == 'superseded_by_restore'
    assert restore['status'] == OperationStatus.QUEUED.value
    assert store.reader().execute(
        'SELECT COUNT(*) FROM audit_records WHERE operation_id = ?', (delete['op_id'],)
    ).fetchone()[0] == 1


@pytest.mark.parametrize('terminal', list(OperationStatus)[-4:])
def test_terminal_transition_audits_once_and_intermediate_transition_does_not(
    store, clock, terminal
) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    operation = _create(
        operations,
        OperationType.BACKUP,
        world_id=world_id,
        status=OperationStatus.CREATED,
    )
    operations.transition(operation['op_id'], OperationStatus.VALIDATING)
    assert store.reader().execute(
        'SELECT COUNT(*) FROM audit_records WHERE operation_id = ?',
        (operation['op_id'],),
    ).fetchone()[0] == 0

    operations.transition(operation['op_id'], terminal)

    assert store.reader().execute(
        'SELECT COUNT(*) FROM audit_records WHERE operation_id = ?',
        (operation['op_id'],),
    ).fetchone()[0] == 1


def test_sync_is_independent_but_queued_single_flight_per_artifact(store, clock) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    first = _create(
        operations,
        OperationType.SYNC,
        world_id=world_id,
        data={'artifact_id': 'artifact-a'},
        allow_world_conflict=True,
    )

    duplicate = _create(
        operations,
        OperationType.SYNC,
        world_id=world_id,
        data={'artifact_id': 'artifact-a'},
        allow_world_conflict=True,
    )
    independent = _create(
        operations,
        OperationType.SYNC,
        world_id=world_id,
        data={'artifact_id': 'artifact-b'},
        allow_world_conflict=True,
    )

    assert duplicate['op_id'] != first['op_id']
    assert duplicate['status'] == OperationStatus.QUEUED.value
    assert independent['status'] == OperationStatus.RUNNING.value


def test_cleanup_is_queued_per_scope_including_manager_scoped_runs(store, clock) -> None:
    operations = OperationService(store, clock)
    running = _create(
        operations,
        OperationType.CLEANUP,
        world_id=None,
        data={'scope': 'backups'},
    )

    duplicate_scope = _create(
        operations,
        OperationType.CLEANUP,
        world_id=None,
        data={'scope': 'backups'},
    )
    independent_scope = _create(
        operations,
        OperationType.CLEANUP,
        world_id=None,
        data={'scope': 'stale_worlds'},
    )

    assert duplicate_scope['op_id'] != running['op_id']
    assert duplicate_scope['status'] == OperationStatus.QUEUED.value
    assert independent_scope['status'] == OperationStatus.RUNNING.value
    rows = store.reader().execute(
        'SELECT op_id, status, data_json FROM operations WHERE op_type = ?',
        (OperationType.CLEANUP.value,),
    ).fetchall()
    assert len(rows) == 3
    assert [json.loads(row['data_json'])['scope'] for row in rows] == [
        'backups',
        'backups',
        'stale_worlds',
    ]
