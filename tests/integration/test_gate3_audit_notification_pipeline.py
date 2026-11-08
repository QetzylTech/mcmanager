"""Gate 3 audit and notification pipeline contracts (WP 3.4)."""

from __future__ import annotations

import json

import pytest

from app.bootstrap import Container
from app.domain.value_objects import (
    ActorType,
    NotificationSeverity,
    OperationStatus,
    OperationType,
)
from app.services.audit import (
    AUTH_EVENT_TYPES,
    EVENT_AUTHZ_DENIED,
    EVENT_LOGIN_FAILED,
    EVENT_LOGIN_LOCKED,
    EVENT_LOGIN_SUCCESS,
    EVENT_PASSWORD_CHANGED,
    EVENT_SESSION_ISSUED,
    EVENT_SESSION_REVOKED,
    EVENT_STEP_UP_CONFIRMED,
    ActorSnapshot,
    operation_event_type,
)
from app.services.notifications import (
    CATEGORY_BACKUP_RESTORE,
    CATEGORY_SYNC,
    CATEGORY_WORLD_LIFECYCLE,
    NotificationInput,
)
from app.services.operations import OperationInput


def test_documented_auth_event_catalog_is_exact() -> None:
    documented = {
        EVENT_LOGIN_SUCCESS,
        EVENT_LOGIN_FAILED,
        EVENT_LOGIN_LOCKED,
        EVENT_SESSION_ISSUED,
        EVENT_SESSION_REVOKED,
        EVENT_STEP_UP_CONFIRMED,
        EVENT_PASSWORD_CHANGED,
        EVENT_AUTHZ_DENIED,
    }
    assert AUTH_EVENT_TYPES == documented
    assert documented == {
        'user_login_success',
        'user_login_failed',
        'user_login_locked',
        'session_issued',
        'session_revoked',
        'step_up_confirmed',
        'password_changed',
        'authorization_denied',
    }


def test_operation_audit_event_names_are_terminal_only() -> None:
    assert operation_event_type(OperationType.START, OperationStatus.COMPLETED) == (
        'operation.start.completed'
    )
    with pytest.raises(ValueError, match='not a terminal operation status'):
        operation_event_type(OperationType.START, OperationStatus.RUNNING)


def test_audit_captures_actor_and_target_snapshots(container: Container) -> None:
    user_id = container.auth.provision_first_superadmin(
        username='snapshot_user',
        password='secret123!',
        device_id=None,
        device_name=None,
        ip='127.0.0.1',
    )
    actor = container.audit.snapshot_for_user(
        user_id=user_id,
        device_id='device-before',
        device_name='Console',
        ip='192.0.2.10',
    )

    audit_id = container.audit.write(
        event_type=EVENT_LOGIN_SUCCESS,
        actor=actor,
        payload={'result': 'accepted'},
        target_snapshot={'kind': 'user', 'user_id': user_id, 'username': 'snapshot_user'},
    )

    row = container.store.reader().execute(
        'SELECT actor_user_id, actor_username_snapshot, device_id_snapshot, '
        'device_name_snapshot, ip_snapshot, payload FROM audit_records WHERE audit_id = ?',
        (audit_id,),
    ).fetchone()
    assert row['actor_user_id'] == user_id
    assert row['actor_username_snapshot'] == 'snapshot_user'
    assert row['device_id_snapshot'] == 'device-before'
    assert row['device_name_snapshot'] == 'Console'
    assert row['ip_snapshot'] == '192.0.2.10'
    assert json.loads(row['payload']) == {
        'result': 'accepted',
        'target_snapshot': {
            'kind': 'user',
            'user_id': user_id,
            'username': 'snapshot_user',
        },
    }

    container.store.writer().execute(
        'UPDATE users SET username = ? WHERE user_id = ?',
        ('renamed_snapshot_user', user_id),
    )
    container.store.writer().execute(
        'UPDATE users SET deleted_at = ? WHERE user_id = ?',
        (int(container.clock.now()), user_id),
    )
    container.store.writer().commit()
    persisted = container.store.reader().execute(
        'SELECT actor_username_snapshot, payload FROM audit_records WHERE audit_id = ?',
        (audit_id,),
    ).fetchone()
    assert persisted['actor_username_snapshot'] == 'snapshot_user'
    assert json.loads(persisted['payload'])['target_snapshot']['username'] == 'snapshot_user'


@pytest.mark.parametrize(
    ('op_type', 'status', 'category', 'severity'),
    [
        (OperationType.START, OperationStatus.COMPLETED, CATEGORY_WORLD_LIFECYCLE, 'informational'),
        (OperationType.STOP, OperationStatus.COMPLETED, CATEGORY_WORLD_LIFECYCLE, 'informational'),
        (OperationType.CRASH_DETECTED, OperationStatus.COMPLETED, CATEGORY_WORLD_LIFECYCLE, 'critical'),
        (OperationType.BACKUP, OperationStatus.COMPLETED, CATEGORY_BACKUP_RESTORE, 'informational'),
        (OperationType.BACKUP, OperationStatus.FAILED, CATEGORY_BACKUP_RESTORE, 'high'),
        (OperationType.RESTORE, OperationStatus.COMPLETED, CATEGORY_BACKUP_RESTORE, 'informational'),
        (OperationType.RESTORE, OperationStatus.FAILED, CATEGORY_BACKUP_RESTORE, 'high'),
        (OperationType.CLEANUP, OperationStatus.COMPLETED, CATEGORY_BACKUP_RESTORE, 'informational'),
        (OperationType.SYNC, OperationStatus.FAILED, CATEGORY_SYNC, 'high'),
    ],
)
def test_terminal_operation_notifications_are_persisted_once(
    container: Container,
    op_type: OperationType,
    status: OperationStatus,
    category: str,
    severity: str,
) -> None:
    operation = container.operations.create(
        OperationInput(op_type=op_type, actor_type=ActorType.SYSTEM)
    )
    terminal = container.operations.transition(operation['op_id'], status)

    notification_id = container.notifications.publish_terminal_operation(terminal)
    assert notification_id is not None
    assert container.notifications.publish_terminal_operation(terminal) == notification_id

    rows = container.store.reader().execute(
        'SELECT category, severity, related_operation_id FROM notifications '
        'WHERE notification_id = ?',
        (notification_id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]['category'] == category
    assert rows[0]['severity'] == severity
    assert rows[0]['related_operation_id'] == operation['op_id']
    assert rows[0]['severity'] in {severity.value for severity in NotificationSeverity}


@pytest.mark.parametrize(
    ('op_type', 'status'),
    [
        (OperationType.START, OperationStatus.RUNNING),
        (OperationType.BACKUP, OperationStatus.CANCELLED),
        (OperationType.SYNC, OperationStatus.COMPLETED),
        (OperationType.CONFIG_EDIT, OperationStatus.FAILED),
    ],
)
def test_non_trigger_terminal_states_do_not_publish_notifications(
    container: Container, op_type: OperationType, status: OperationStatus
) -> None:
    operation = container.operations.create(
        OperationInput(op_type=op_type, actor_type=ActorType.SYSTEM)
    )
    transitioned = container.operations.transition(operation['op_id'], status)

    assert container.notifications.publish_terminal_operation(transitioned) is None
    count = container.store.reader().execute(
        'SELECT count(*) FROM notifications WHERE related_operation_id = ?',
        (operation['op_id'],),
    ).fetchone()[0]
    assert count == 0


def test_terminal_notifications_are_not_pre_fanned_to_users(container: Container) -> None:
    operation = container.operations.create(
        OperationInput(op_type=OperationType.BACKUP, actor_type=ActorType.SYSTEM)
    )
    terminal = container.operations.transition(
        operation['op_id'], OperationStatus.COMPLETED
    )
    notification_id = container.notifications.publish_terminal_operation(terminal)

    assert notification_id is not None
    assert container.store.reader().execute(
        'SELECT count(*) FROM notifications WHERE notification_id = ?',
        (notification_id,),
    ).fetchone()[0] == 1
    assert container.store.reader().execute(
        'SELECT count(*) FROM notification_reads'
    ).fetchone()[0] == 0


def test_notification_categories_are_a_closed_supported_set(container: Container) -> None:
    with pytest.raises(ValueError, match='unsupported notification category'):
        container.notifications.publish(
            NotificationInput(
                category='unexpected_event',
                severity=NotificationSeverity.NORMAL,
                message='Must not be persisted',
            )
        )
    assert container.store.reader().execute(
        'SELECT count(*) FROM notifications'
    ).fetchone()[0] == 0
