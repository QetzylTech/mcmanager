"""NotificationService (Document 6 section 2.8; Document 8 section 8).

Tier 1 permanent: notification rows are never deletable through any path —
they are only read/dismissed per user via ``notification_reads``. Reads are
created lazily, one row per (notification, user) when that user views it —
never fanned out upfront. ``notification_reads`` is also Tier 1 and
append-mostly: read/dismiss markers are the only permitted writes.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from app.domain.value_objects import NotificationSeverity, OperationStatus, OperationType
from app.ports.clock import Clock
from app.ports.persistence import PersistencePort

# Fixed trigger-list categories (Doc 8 section 8).
CATEGORY_WORLD_LIFECYCLE = 'world_lifecycle'
CATEGORY_BACKUP_RESTORE = 'backup_restore'
CATEGORY_SYNC = 'sync'
CATEGORY_SECURITY = 'security'
CATEGORY_STORAGE = 'storage'
CATEGORY_SCHEDULER = 'scheduler'
SUPPORTED_CATEGORIES = frozenset(
    {
        CATEGORY_WORLD_LIFECYCLE,
        CATEGORY_BACKUP_RESTORE,
        CATEGORY_SYNC,
        CATEGORY_SECURITY,
        CATEGORY_STORAGE,
        CATEGORY_SCHEDULER,
    }
)

_TERMINAL_NOTIFICATION_RULES = {
    (OperationType.START.value, OperationStatus.COMPLETED.value): (
        CATEGORY_WORLD_LIFECYCLE,
        NotificationSeverity.INFORMATIONAL,
        'World started.',
    ),
    (OperationType.STOP.value, OperationStatus.COMPLETED.value): (
        CATEGORY_WORLD_LIFECYCLE,
        NotificationSeverity.INFORMATIONAL,
        'World stopped.',
    ),
    (OperationType.KILL.value, OperationStatus.COMPLETED.value): (
        CATEGORY_WORLD_LIFECYCLE,
        NotificationSeverity.INFORMATIONAL,
        'World stopped.',
    ),
    (OperationType.CRASH_DETECTED.value, OperationStatus.COMPLETED.value): (
        CATEGORY_WORLD_LIFECYCLE,
        NotificationSeverity.CRITICAL,
        'World crashed.',
    ),
    (OperationType.BACKUP.value, OperationStatus.COMPLETED.value): (
        CATEGORY_BACKUP_RESTORE,
        NotificationSeverity.INFORMATIONAL,
        'Backup completed.',
    ),
    (OperationType.BACKUP.value, OperationStatus.FAILED.value): (
        CATEGORY_BACKUP_RESTORE,
        NotificationSeverity.HIGH,
        'Backup failed.',
    ),
    (OperationType.RESTORE.value, OperationStatus.COMPLETED.value): (
        CATEGORY_BACKUP_RESTORE,
        NotificationSeverity.INFORMATIONAL,
        'Restore completed.',
    ),
    (OperationType.RESTORE.value, OperationStatus.FAILED.value): (
        CATEGORY_BACKUP_RESTORE,
        NotificationSeverity.HIGH,
        'Restore failed.',
    ),
    (OperationType.CLEANUP.value, OperationStatus.COMPLETED.value): (
        CATEGORY_BACKUP_RESTORE,
        NotificationSeverity.INFORMATIONAL,
        'Cleanup completed.',
    ),
    (OperationType.SYNC.value, OperationStatus.FAILED.value): (
        CATEGORY_SYNC,
        NotificationSeverity.HIGH,
        'Sync failed.',
    ),
}

_TERMINAL_STATUSES = frozenset(
    {
        OperationStatus.COMPLETED.value,
        OperationStatus.FAILED.value,
        OperationStatus.CANCELLED.value,
        OperationStatus.TIMED_OUT.value,
    }
)


@dataclass(frozen=True)
class NotificationInput:
    """Payload for a single notification row."""

    category: str
    severity: NotificationSeverity
    message: str
    requires_action: bool = False
    related_operation_id: str | None = None
    related_world_id: str | None = None


class NotificationService:
    """Tier 1 permanent notification publisher + per-user read tracking."""

    def __init__(self, store: PersistencePort, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def publish(
        self,
        notification: NotificationInput,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> str:
        """Insert exactly one notifications row (Doc 8 section 8)."""
        self._validate(notification)
        writer = connection or self._store.writer()
        owns_transaction = connection is None
        if owns_transaction:
            writer.execute('BEGIN IMMEDIATE')
        try:
            notification_id = self._insert(writer, notification)
            if owns_transaction:
                writer.commit()
            return notification_id
        except Exception:
            if owns_transaction:
                writer.rollback()
            raise

    def publish_terminal_operation(
        self,
        operation: Mapping[str, Any],
        *,
        connection: sqlite3.Connection | None = None,
    ) -> str | None:
        """Publish the documented notification for a terminal operation once.

        Pass the OperationService transaction when available so the operation
        and notification become durable atomically.
        """
        status = operation.get('status')
        if status not in _TERMINAL_STATUSES:
            return None
        rule = _TERMINAL_NOTIFICATION_RULES.get((operation.get('op_type'), status))
        if rule is None:
            return None

        operation_id = operation.get('op_id')
        if not operation_id:
            raise ValueError('terminal operation requires op_id')

        category, severity, message = rule
        notification = NotificationInput(
            category=category,
            severity=severity,
            message=message,
            related_operation_id=operation_id,
            related_world_id=operation.get('world_id'),
        )
        self._validate(notification)

        writer = connection or self._store.writer()
        owns_transaction = connection is None
        if owns_transaction:
            writer.execute('BEGIN IMMEDIATE')
        try:
            existing = writer.execute(
                'SELECT notification_id FROM notifications '
                'WHERE related_operation_id = ? LIMIT 1',
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if owns_transaction:
                    writer.commit()
                return existing['notification_id']
            notification_id = self._insert(writer, notification)
            if owns_transaction:
                writer.commit()
            return notification_id
        except Exception:
            if owns_transaction:
                writer.rollback()
            raise

    def publish_missed_run(
        self,
        schedule_name: str,
        *,
        world_id: str | None,
        connection: sqlite3.Connection | None = None,
    ) -> str:
        """Publish the durable normal-severity notification for a missed run."""
        return self.publish(
            NotificationInput(
                category=CATEGORY_SCHEDULER,
                severity=NotificationSeverity.NORMAL,
                message=f'Scheduled run missed: {schedule_name}',
                requires_action=True,
                related_world_id=world_id,
            ),
            connection=connection,
        )

    @staticmethod
    def _validate(notification: NotificationInput) -> None:
        if notification.category not in SUPPORTED_CATEGORIES:
            raise ValueError(f'unsupported notification category: {notification.category}')
        if not isinstance(notification.severity, NotificationSeverity):
            raise ValueError(f'unsupported notification severity: {notification.severity}')

    def _insert(
        self, writer: sqlite3.Connection, notification: NotificationInput
    ) -> str:
        notification_id = f'n_{uuid.uuid4().hex[:16]}'
        writer.execute(
            'INSERT INTO notifications ('
            '  notification_id, category, severity, message,'
            '  related_operation_id, related_world_id,'
            '  requires_action, action_taken, created_at'
            ') VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)',
            (
                notification_id,
                notification.category,
                notification.severity.value,
                notification.message,
                notification.related_operation_id,
                notification.related_world_id,
                1 if notification.requires_action else 0,
                int(self._clock.now()),
            ),
        )
        return notification_id

    def mark_read(self, notification_id: str, user_id: str) -> None:
        """Lazy per-user read row (upsert read_at; never touches the row)."""
        connection = self._store.writer()
        connection.execute(
            'INSERT INTO notification_reads (notification_id, user_id, read_at, dismissed_at) '
            'VALUES (?, ?, ?, NULL) '
            'ON CONFLICT(notification_id, user_id) DO UPDATE SET read_at = excluded.read_at',
            (notification_id, user_id, int(self._clock.now())),
        )
        connection.commit()

    def dismiss(self, notification_id: str, user_id: str) -> None:
        """Hide from THIS user's dropdown only (Doc 6 section 2.8)."""
        connection = self._store.writer()
        connection.execute(
            'INSERT INTO notification_reads (notification_id, user_id, read_at, dismissed_at) '
            'VALUES (?, ?, NULL, ?) '
            'ON CONFLICT(notification_id, user_id) DO UPDATE SET dismissed_at = excluded.dismissed_at',
            (notification_id, user_id, int(self._clock.now())),
        )
        connection.commit()

    def list_for_user(
        self, user_id: str, *, include_dismissed: bool = False
    ) -> list[dict]:
        """Prioritized dropdown view: severity then recency (Doc 8 section 3).

        Dismissed rows are hidden from the dropdown (``include_dismissed``
        = False) but remain permanently queryable via
        ``include_dismissed=True`` for Audit/History views — the notification
        row itself is never touched.
        """
        connection = self._store.reader()
        dismissal_filter = (
            ''
            if include_dismissed
            else 'WHERE reads.notification_id IS NULL OR reads.dismissed_at IS NULL'
        )
        rows = connection.execute(
            f"""
            SELECT n.notification_id, n.category, n.severity, n.message,
                   n.related_operation_id, n.related_world_id,
                   n.requires_action, n.action_taken, n.created_at,
                   reads.read_at, reads.dismissed_at
            FROM notifications n
            LEFT JOIN notification_reads reads
              ON reads.notification_id = n.notification_id AND reads.user_id = ?
            {dismissal_filter}
            ORDER BY CASE n.severity
                WHEN 'critical' THEN 0
                WHEN 'high' THEN 1
                WHEN 'normal' THEN 2
                ELSE 3
            END, n.created_at DESC
            """,
            (user_id,),
        )
        return [dict(row) for row in rows]
