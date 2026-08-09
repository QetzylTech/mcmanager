"""AuditService append-only contract (Doc 6 §2.9, Doc 8 §10)."""

from __future__ import annotations

import sqlite3

import pytest

from app.bootstrap import Container
from app.services.audit import ActorSnapshot
from app.domain.value_objects import ActorType


def test_audit_update_forbidden(container: Container) -> None:
    audit_id = container.audit.write(
        event_type='test_event',
        actor=container.audit.system(),
    )
    with pytest.raises(sqlite3.IntegrityError, match='UPDATE forbidden'):
        container.store.writer().execute(
            'UPDATE audit_records SET event_type = ? WHERE audit_id = ?',
            ('tampered', audit_id),
        )


def test_audit_delete_forbidden(container: Container) -> None:
    audit_id = container.audit.write(
        event_type='test_event',
        actor=container.audit.system(),
    )
    with pytest.raises(sqlite3.IntegrityError, match='DELETE forbidden'):
        container.store.writer().execute(
            'DELETE FROM audit_records WHERE audit_id = ?', (audit_id,)
        )


def test_username_snapshot_immutable_after_rename(container: Container) -> None:
    user_id = container.auth.provision_first_superadmin(
        username='original_name',
        password='secret123!',
        device_id=None,
        device_name=None,
        ip='127.0.0.1',
    )
    audit_id = container.audit.write(
        event_type='test_snapshot',
        actor=container.audit.snapshot_for_user(
            user_id=user_id, device_id=None, device_name=None, ip='127.0.0.1'
        ),
    )
    container.store.writer().execute(
        'UPDATE users SET username = ? WHERE user_id = ?',
        ('renamed_user', user_id),
    )
    container.store.writer().commit()
    row = container.store.reader().execute(
        'SELECT actor_username_snapshot FROM audit_records WHERE audit_id = ?',
        (audit_id,),
    ).fetchone()
    assert row['actor_username_snapshot'] == 'original_name'


def test_annotation_of_creates_linked_record(container: Container) -> None:
    original_id = container.audit.write(
        event_type='original',
        actor=container.audit.system(),
    )
    correction_id = container.audit.write(
        event_type='correction',
        actor=ActorSnapshot(actor_type=ActorType.SYSTEM),
        annotation_of=original_id,
    )
    row = container.store.reader().execute(
        'SELECT annotation_of FROM audit_records WHERE audit_id = ?',
        (correction_id,),
    ).fetchone()
    assert row['annotation_of'] == original_id
