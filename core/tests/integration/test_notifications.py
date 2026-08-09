"""NotificationService Tier 1 permanent contract (Doc 6 §2.8, Doc 8 §8)."""

from __future__ import annotations

from app.bootstrap import Container
from app.domain.value_objects import NotificationSeverity
from app.services.notifications import (
    CATEGORY_SECURITY,
    NotificationInput,
)


def _bootstrap_user(container: Container) -> str:
    return container.auth.provision_first_superadmin(
        username='admin',
        password='secret123!',
        device_id=None,
        device_name=None,
        ip='127.0.0.1',
    )


def test_publish_creates_permanent_row(container: Container) -> None:
    notification_id = container.notifications.publish(
        NotificationInput(
            category=CATEGORY_SECURITY,
            severity=NotificationSeverity.HIGH,
            message='Suspicious activity detected',
            requires_action=True,
        )
    )
    row = container.store.reader().execute(
        'SELECT message, requires_action FROM notifications WHERE notification_id = ?',
        (notification_id,),
    ).fetchone()
    assert row['message'] == 'Suspicious activity detected'
    assert row['requires_action'] == 1


def test_mark_read_is_lazy_per_user(container: Container) -> None:
    user_id = _bootstrap_user(container)
    notification_id = container.notifications.publish(
        NotificationInput(
            category=CATEGORY_SECURITY,
            severity=NotificationSeverity.NORMAL,
            message='Test notification',
        )
    )
    before = container.store.reader().execute(
        'SELECT count(*) FROM notification_reads'
    ).fetchone()[0]
    assert before == 0
    container.notifications.mark_read(notification_id, user_id)
    row = container.store.reader().execute(
        'SELECT read_at, dismissed_at FROM notification_reads '
        'WHERE notification_id = ? AND user_id = ?',
        (notification_id, user_id),
    ).fetchone()
    assert row['read_at'] is not None
    assert row['dismissed_at'] is None


def test_dismiss_hides_from_dropdown_only(container: Container) -> None:
    user_id = _bootstrap_user(container)
    notification_id = container.notifications.publish(
        NotificationInput(
            category=CATEGORY_SECURITY,
            severity=NotificationSeverity.NORMAL,
            message='Dismiss me',
        )
    )
    container.notifications.dismiss(notification_id, user_id)
    visible = container.notifications.list_for_user(user_id, include_dismissed=False)
    assert all(row['notification_id'] != notification_id for row in visible)
    all_rows = container.notifications.list_for_user(user_id, include_dismissed=True)
    assert any(row['notification_id'] == notification_id for row in all_rows)


def test_list_orders_by_severity_then_recency(container: Container) -> None:
    user_id = _bootstrap_user(container)
    container.notifications.publish(
        NotificationInput(
            category=CATEGORY_SECURITY,
            severity=NotificationSeverity.NORMAL,
            message='normal',
        )
    )
    container.notifications.publish(
        NotificationInput(
            category=CATEGORY_SECURITY,
            severity=NotificationSeverity.CRITICAL,
            message='critical',
        )
    )
    rows = container.notifications.list_for_user(user_id)
    assert rows[0]['severity'] == 'critical'
