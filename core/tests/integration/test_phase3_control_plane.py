from __future__ import annotations

import json

import pytest

from app.domain.tuning import SCHEDULER_TICK_INTERVAL_S
from app.domain.value_objects import ActorType, OperationStatus, OperationType
from app.services.operations import OperationConflictError, OperationInput, OperationService
from app.services.realtime import LogFanout, RealtimeHub
from app.services.scheduler import SchedulerService


def _seed_world(store) -> str:
    now = 1_700_000_000
    connection = store.writer()
    connection.execute(
        "INSERT INTO secrets VALUES ('sec_admin', 'user_password', 'x', 'user', 'u_admin', NULL, ?, NULL)",
        (now,),
    )
    connection.execute(
        """
        INSERT INTO users (
            user_id, username, display_name, secret_id, status, failed_login_count,
            locked_until, created_by, deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('u_admin', 'admin', NULL, 'sec_admin', 'active', 0, NULL, NULL, NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    connection.execute(
        """
        INSERT INTO templates (
            template_id, name, category, default_version, config_defaults, source,
            deprecated, version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('tpl', 'Vanilla', 'vanilla', '1.21', '{}', 'built_in', 0, 1, NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    connection.execute(
        """
        INSERT INTO java_runtimes (
            runtime_id, label, executable_path, version_detected, status,
            deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('java', 'Java 21', 'java', '21', 'verified', NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    connection.execute(
        """
        INSERT INTO world_instances (
            world_id, display_name, template_id, server_type, mc_version, java_runtime_id,
            port, addressing_strategy, addressing_value, state, pre_backup_state,
            launch_args, metadata_version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('world_1', 'Survival', 'tpl', 'vanilla', '1.21', 'java', 25565, 'port',
                  '25565', 'off', NULL, '{}', 1, NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    connection.commit()
    return 'world_1'


def test_operation_idempotency_and_derived_world_lock(store, clock):
    world_id = _seed_world(store)
    service = OperationService(store, clock)

    first = service.create(
        OperationInput(
            op_type=OperationType.BACKUP,
            actor_type=ActorType.SYSTEM,
            world_id=world_id,
            idempotency_key='same-trigger',
        )
    )
    replay = service.create(
        OperationInput(
            op_type=OperationType.BACKUP,
            actor_type=ActorType.SYSTEM,
            world_id=world_id,
            idempotency_key='same-trigger',
        )
    )

    assert replay['op_id'] == first['op_id']
    assert service.has_in_flight_operation(world_id)
    with pytest.raises(OperationConflictError):
        service.create(
            OperationInput(
                op_type=OperationType.RESTORE,
                actor_type=ActorType.SYSTEM,
                world_id=world_id,
            )
        )

    service.transition(first['op_id'], OperationStatus.COMPLETED, checkpoint={'stage': 'done'})
    assert not service.has_in_flight_operation(world_id)


def test_scheduler_tick_dispatches_due_schedule_and_records_conflict_as_missed(store, clock):
    world_id = _seed_world(store)
    operations = OperationService(store, clock)
    scheduler = SchedulerService(store, clock, operations)
    assert scheduler.tick_interval_seconds == SCHEDULER_TICK_INTERVAL_S == 30
    connection = store.writer()
    connection.execute(
        """
        INSERT INTO schedules (
            schedule_id, scope, world_id, schedule_type, interval_spec, time_of_day,
            enabled, version, last_changed_by, last_changed_at, deleted_at, deleted_by, created_at
        ) VALUES ('sch_1', 'world', ?, 'backup', ?, '00:00', 1, 1, 'u_admin', ?, NULL, NULL, ?)
        """,
        (world_id, json.dumps({'kind': 'every_n_days', 'days': 1}), int(clock.now()) - 90_000, int(clock.now()) - 90_000),
    )
    connection.commit()

    result = scheduler.tick()
    assert result.due == 1
    assert result.dispatched == 1
    assert result.missed == 0

    connection.execute(
        """
        INSERT INTO schedules (
            schedule_id, scope, world_id, schedule_type, interval_spec, time_of_day,
            enabled, version, last_changed_by, last_changed_at, deleted_at, deleted_by, created_at
        ) VALUES ('sch_2', 'world', ?, 'cleanup', ?, '00:00', 1, 1, 'u_admin', ?, NULL, NULL, ?)
        """,
        (world_id, json.dumps({'kind': 'every_n_days', 'days': 1}), int(clock.now()) - 90_000, int(clock.now()) - 90_000),
    )
    connection.commit()

    result = scheduler.tick()
    assert result.missed == 1
    missed = store.reader().execute('SELECT * FROM missed_run_records WHERE schedule_id = ?', ('sch_2',)).fetchone()
    assert missed['resolution'] == 'pending'


def test_realtime_hub_replay_and_log_fanout():
    hub = RealtimeHub(replay_limit=2)
    first = hub.publish('events', 'world.state', {'world_id': 'w', 'state': 'off'})
    second = hub.publish('events', 'world.state', {'world_id': 'w', 'state': 'running'})
    hub.publish('events', 'notification', {'message': 'done'})

    assert [event.sequence for event in hub.replay('events', last_event_id=first.sequence)] == [second.sequence, 3]

    subscriber = hub.subscribe('events', last_event_id=second.sequence)
    frames = subscriber.frames()
    assert 'event: notification' in next(frames)

    logs = LogFanout(hub, line_limit=1)
    event = logs.append(world_id='w', session_id='s', channel='minecraft', line='ready', ts=123)
    assert event.event == 'log.line'
    assert logs.buffered('w')[0]['line_no'] == 1
