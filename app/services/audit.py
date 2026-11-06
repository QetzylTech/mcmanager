"""AuditService (Document 6 section 0.1 / section 2.9; Document 8 section 10).

Insert-only. Unless the actor snapshots are supplied explicitly, the
service resolves live username/device snapshots at write time and never
joins them later — ``audit_records`` rows keep their meaning after the
referenced user/device is soft-deleted or renamed.

The underlying table has DB-level triggers refusing UPDATE/DELETE; this
service provides no update/delete path at all. Corrections and
acknowledgements are new rows via ``annotation_of``.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from app.domain.value_objects import ActorType
from app.infrastructure.sqlite.connection import SqliteStore
from app.ports.clock import Clock

# Event-type catalog used by Gate 2 consumers (Doc 8 section 10).
EVENT_LOGIN_SUCCESS = 'user_login_success'
EVENT_LOGIN_FAILED = 'user_login_failed'
EVENT_LOGIN_LOCKED = 'user_login_locked'
EVENT_SESSION_ISSUED = 'session_issued'
EVENT_SESSION_REVOKED = 'session_revoked'
EVENT_STEP_UP_CONFIRMED = 'step_up_confirmed'
EVENT_PASSWORD_CHANGED = 'password_changed'
EVENT_AUTHZ_DENIED = 'authorization_denied'


@dataclass(frozen=True)
class ActorSnapshot:
    """Actor context captured at write time (Doc 6 section 0.1).

    ``user_id``/``device_id`` are plain values, deliberately not FKs.
    """

    actor_type: ActorType
    user_id: str | None = None
    username: str | None = None
    device_id: str | None = None
    device_name: str | None = None
    ip: str | None = None


class AuditService:
    """Append-only audit writer."""

    def __init__(self, store: SqliteStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def snapshot_for_user(
        self, *, user_id: str, device_id: str | None, device_name: str | None, ip: str | None
    ) -> ActorSnapshot:
        """Resolve the live username at write time for a user actor."""
        connection = self._store.reader()
        row = connection.execute(
            'SELECT username FROM users WHERE user_id = ?', (user_id,)
        ).fetchone()
        username = row['username'] if row is not None else None
        return ActorSnapshot(
            actor_type=ActorType.USER,
            user_id=user_id,
            username=username,
            device_id=device_id,
            device_name=device_name,
            ip=ip,
        )

    def system(self) -> ActorSnapshot:
        """Actor context for system-originated records."""
        return ActorSnapshot(actor_type=ActorType.SYSTEM)

    def write(
        self,
        *,
        event_type: str,
        actor: ActorSnapshot,
        operation_id: str | None = None,
        world_id: str | None = None,
        payload: dict[str, Any] | None = None,
        annotation_of: str | None = None,
        when: float | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> str:
        """Append exactly one audit record (Doc 8 section 10)."""
        audit_id = f'au_{uuid.uuid4().hex[:16]}'
        writer = connection or self._store.writer()
        writer.execute(
            'INSERT INTO audit_records ('
            '  audit_id, event_type, actor_type,'
            '  actor_user_id, actor_username_snapshot,'
            '  device_id_snapshot, device_name_snapshot, ip_snapshot,'
            '  operation_id, world_id, payload, annotation_of, created_at'
            ') VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                audit_id,
                event_type,
                actor.actor_type.value,
                actor.user_id,
                actor.username,
                actor.device_id,
                actor.device_name,
                actor.ip,
                operation_id,
                world_id,
                json.dumps(payload) if payload is not None else None,
                annotation_of,
                int(when or self._clock.now()),
            ),
        )
        if connection is None:
            writer.commit()
        return audit_id
