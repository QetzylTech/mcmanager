"""Gate 3 boot, worker-loop, supervisor, and scheduler acceptance contracts."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

from app.domain.value_objects import ActorType, OperationStatus, OperationType
from app.services.operations import OperationInput, OperationService
from app.services.scheduler import SchedulerService

from ._gate3_support import seed_world


def test_create_app_surfaces_boot_reconciliation_failure(monkeypatch) -> None:
    app_module = importlib.import_module('app')
    error = RuntimeError('reconciliation probe failed')
    container = SimpleNamespace(
        worlds=SimpleNamespace(reconcile=lambda: (_ for _ in ()).throw(error))
    )
    monkeypatch.setattr(app_module, 'build_container', lambda **_kwargs: container)

    try:
        app_module.create_app(database_path='unused.db', keyfile_path='unused.key')
    except RuntimeError as caught:
        assert caught is error
    else:
        raise AssertionError('boot reconciliation failure was swallowed')


def test_create_app_starts_supervisor_scheduler_and_operation_workers(monkeypatch) -> None:
    app_module = importlib.import_module('app')
    container = SimpleNamespace(
        worlds=SimpleNamespace(reconcile=lambda: None, poll_running=lambda: []),
        scheduler=SimpleNamespace(tick_interval_seconds=30, tick=lambda: None),
    )
    closed: list[bool] = []
    container.store = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(app_module, 'build_container', lambda **_kwargs: container)

    app = app_module.create_app(database_path='unused.db', keyfile_path='unused.key')

    workers = app.extensions['mcmanager_workers']
    assert {thread.name for thread in workers} == {
        "mcmanager-runtime-supervisor",
        "mcmanager-scheduler",
        "mcmanager-operation-dispatcher",
    }
    assert all(thread.daemon and thread.ident is not None for thread in workers)
    app.extensions['mcmanager_shutdown']()
    assert app.extensions['mcmanager_workers_stop'].is_set()
    assert all(not thread.is_alive() for thread in workers)
    assert closed == [True]


def test_scheduler_conflict_is_recorded_once_and_never_replayed(store, clock) -> None:
    world_id = seed_world(store)
    operations = OperationService(store, clock)
    scheduler = SchedulerService(store, clock, operations)
    now = int(clock.now())
    store.writer().execute(
        """
        INSERT INTO schedules (
            schedule_id, scope, world_id, schedule_type, interval_spec, time_of_day,
            enabled, version, last_changed_by, last_changed_at, deleted_at, deleted_by, created_at
        ) VALUES ('gate3_schedule', 'world', ?, 'backup', ?, '00:00', 1, 1,
                  'gate3_admin', ?, NULL, NULL, ?)
        """,
        (world_id, '{"kind":"every_n_days","days":1}', now - 86_400, now - 86_400),
    )
    store.writer().commit()
    active = operations.create(
        OperationInput(
            op_type=OperationType.BACKUP,
            actor_type=ActorType.SYSTEM,
            world_id=world_id,
        ),
        initial_status=OperationStatus.RUNNING,
    )

    first_tick = scheduler.tick()
    assert first_tick.missed == 1
    operations.transition(active['op_id'], OperationStatus.COMPLETED)
    second_tick = scheduler.tick()

    assert second_tick.dispatched == 0
    assert store.reader().execute(
        "SELECT COUNT(*) FROM operations WHERE world_id = ? AND op_type = 'Backup'",
        (world_id,),
    ).fetchone()[0] == 1
    missed = store.reader().execute(
        'SELECT resolution FROM missed_run_records WHERE schedule_id = ?',
        ('gate3_schedule',),
    ).fetchall()
    assert [row['resolution'] for row in missed] == ['pending']


def test_scheduler_cadence_remains_thirty_seconds(store, clock) -> None:
    assert SchedulerService(store, clock, OperationService(store, clock)).tick_interval_seconds == 30
