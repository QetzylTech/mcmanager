"""Scheduler dispatch and missed-run contracts (WP 3.3)."""

from __future__ import annotations

import json

import pytest

from app.domain.value_objects import ActorType, OperationStatus, OperationType
from app.services.notifications import CATEGORY_SCHEDULER, NotificationService
from app.services.operations import OperationInput, OperationService
from app.services.scheduler import SchedulerService

from ._gate3_support import seed_world

_DAY = 24 * 60 * 60


def _insert_schedule(
    store,
    clock,
    world_id: str,
    *,
    schedule_id: str = 'scheduler_contract',
    last_changed_at: int | None = None,
) -> None:
    now = int(clock.now())
    changed_at = now - _DAY if last_changed_at is None else last_changed_at
    store.writer().execute(
        """
        INSERT INTO schedules (
            schedule_id, scope, world_id, schedule_type, interval_spec, time_of_day,
            enabled, version, last_changed_by, last_changed_at, deleted_at, deleted_by, created_at
        ) VALUES (?, 'world', ?, 'backup', ?, '00:00', 1, 1, 'gate3_admin', ?, NULL, NULL, ?)
        """,
        (
            schedule_id,
            world_id,
            json.dumps({'kind': 'every_n_days', 'days': 1}),
            changed_at,
            changed_at,
        ),
    )
    store.writer().commit()


def test_tick_interval_is_exactly_thirty_seconds(store, clock) -> None:
    assert SchedulerService(store, clock, OperationService(store, clock)).tick_interval_seconds == 30


def test_fresh_due_schedule_dispatches_once_when_scope_is_clear(store, clock) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    scheduler = SchedulerService(store, clock, operations)
    _insert_schedule(store, clock, world_id)

    first = scheduler.tick()
    second = scheduler.tick()

    assert (first.due, first.dispatched, first.missed) == (1, 1, 0)
    assert (second.dispatched, second.missed) == (0, 0)
    assert store.reader().execute(
        "SELECT COUNT(*) FROM operations WHERE idempotency_key LIKE 'schedule:%'"
    ).fetchone()[0] == 1


def test_scheduled_backup_can_run_alongside_runtime_operation(store, clock) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    scheduler = SchedulerService(store, clock, operations)
    _insert_schedule(store, clock, world_id)
    operations.create(
        OperationInput(
            op_type=OperationType.STOP,
            actor_type=ActorType.SYSTEM,
            world_id=world_id,
        ),
        initial_status=OperationStatus.RUNNING,
    )

    result = scheduler.tick()

    assert (result.dispatched, result.missed) == (1, 0)
    assert store.reader().execute(
        "SELECT COUNT(*) FROM operations WHERE idempotency_key LIKE 'schedule:%'"
    ).fetchone()[0] == 1


def test_conflicting_due_run_is_durable_and_not_replayed(store, clock) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    notifications = NotificationService(store, clock)
    scheduler = SchedulerService(store, clock, operations, notifications)
    _insert_schedule(store, clock, world_id)
    active = operations.create(
        OperationInput(
            op_type=OperationType.BACKUP,
            actor_type=ActorType.SYSTEM,
            world_id=world_id,
        ),
        initial_status=OperationStatus.RUNNING,
    )

    first = scheduler.tick()
    operations.transition(active['op_id'], OperationStatus.COMPLETED)
    second = scheduler.tick()

    assert (first.dispatched, first.missed) == (0, 1)
    assert (second.dispatched, second.missed) == (0, 0)
    assert store.reader().execute(
        "SELECT COUNT(*) FROM operations WHERE idempotency_key LIKE 'schedule:%'"
    ).fetchone()[0] == 0
    missed = store.reader().execute(
        'SELECT resolution FROM missed_run_records WHERE schedule_id = ?',
        ('scheduler_contract',),
    ).fetchall()
    assert [row['resolution'] for row in missed] == ['pending']
    notification_rows = store.reader().execute(
        'SELECT category, severity, message, requires_action, related_world_id '
        'FROM notifications WHERE category = ?',
        (CATEGORY_SCHEDULER,),
    ).fetchall()
    assert len(notification_rows) == 1
    assert notification_rows[0]['category'] == CATEGORY_SCHEDULER
    assert notification_rows[0]['severity'] == 'normal'
    assert notification_rows[0]['message'] == f'Scheduled run missed: {world_id} backup schedule'
    assert notification_rows[0]['requires_action'] == 1
    assert notification_rows[0]['related_world_id'] == world_id


@pytest.mark.parametrize(
    ('mutation',),
    [('disable',), ('delete',)],
)
def test_schedule_disabled_or_deleted_before_dispatch_is_skipped(
    store, clock, monkeypatch, mutation: str
) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    scheduler = SchedulerService(store, clock, operations)
    _insert_schedule(store, clock, world_id)
    read_schedule = scheduler._schedule_for_dispatch

    def mutate_then_reread(schedule_id: str):
        if mutation == 'disable':
            store.writer().execute(
                'UPDATE schedules SET enabled = 0 WHERE schedule_id = ?',
                (schedule_id,),
            )
        else:
            store.writer().execute(
                'UPDATE schedules SET deleted_at = ? WHERE schedule_id = ?',
                (int(clock.now()), schedule_id),
            )
        store.writer().commit()
        return read_schedule(schedule_id)

    monkeypatch.setattr(scheduler, '_schedule_for_dispatch', mutate_then_reread)

    result = scheduler.tick()

    assert (result.due, result.dispatched, result.missed) == (1, 0, 0)
    assert store.reader().execute(
        "SELECT COUNT(*) FROM operations WHERE idempotency_key LIKE 'schedule:%'"
    ).fetchone()[0] == 0
