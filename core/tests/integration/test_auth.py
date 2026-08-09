"""AuthenticationService security contract (Doc 8 §9)."""

from __future__ import annotations

import hashlib

import pytest

from app.bootstrap import Container
from app.services.audit import (
    EVENT_LOGIN_FAILED,
    EVENT_LOGIN_LOCKED,
    EVENT_LOGIN_SUCCESS,
    EVENT_PASSWORD_CHANGED,
    EVENT_SESSION_ISSUED,
    EVENT_SESSION_REVOKED,
    EVENT_STEP_UP_CONFIRMED,
)
from app.services.auth import (
    AuthenticationError,
    InvalidCredentialsError,
    SessionError,
    StepUpRequiredError,
    UserLockedError,
)
from tests.conftest import FakeClock

_PASSWORD = 'correct-horse-battery-staple!'


def _bootstrap_admin(container: Container) -> str:
    return container.auth.provision_first_superadmin(
        username='admin',
        password=_PASSWORD,
        device_id='dev-001',
        device_name='Test Device',
        ip='127.0.0.1',
    )


def test_provision_first_superadmin_only_when_empty(container: Container) -> None:
    _bootstrap_admin(container)
    with pytest.raises(AuthenticationError, match='already exist'):
        container.auth.provision_first_superadmin(
            username='other',
            password='x',
            device_id=None,
            device_name=None,
            ip='127.0.0.1',
        )


def test_password_stored_as_argon2id_in_secrets(container: Container) -> None:
    user_id = _bootstrap_admin(container)
    row = container.store.reader().execute(
        'SELECT secret_id FROM users WHERE user_id = ?', (user_id,)
    ).fetchone()
    stored_hash = container.secrets.read(row['secret_id'])
    assert stored_hash.startswith('$argon2id$')
    assert _PASSWORD not in stored_hash


def test_session_token_hashed_at_rest(container: Container) -> None:
    _bootstrap_admin(container)
    session = container.auth.authenticate(
        username='admin',
        password=_PASSWORD,
        device_id='dev-001',
        device_name='Test Device',
        ip='127.0.0.1',
    )
    row = container.store.reader().execute(
        'SELECT session_id FROM client_sessions WHERE user_id = ?',
        (session.user_id,),
    ).fetchone()
    assert row['session_id'] == hashlib.sha256(session.token.encode()).hexdigest()
    assert session.token not in row['session_id']


def test_login_success_writes_audit(container: Container) -> None:
    _bootstrap_admin(container)
    container.auth.authenticate(
        username='admin',
        password=_PASSWORD,
        device_id='dev-001',
        device_name='Test Device',
        ip='127.0.0.1',
    )
    events = container.store.reader().execute(
        'SELECT event_type FROM audit_records ORDER BY created_at'
    ).fetchall()
    types = [row['event_type'] for row in events]
    assert EVENT_LOGIN_SUCCESS in types
    assert EVENT_SESSION_ISSUED in types


def test_login_failure_writes_audit(container: Container) -> None:
    _bootstrap_admin(container)
    with pytest.raises(InvalidCredentialsError):
        container.auth.authenticate(
            username='admin',
            password='wrong',
            device_id='dev-001',
            device_name='Test Device',
            ip='127.0.0.1',
        )
    row = container.store.reader().execute(
        'SELECT event_type FROM audit_records WHERE event_type = ?',
        (EVENT_LOGIN_FAILED,),
    ).fetchone()
    assert row is not None


def test_lockout_after_five_failures(container: Container, clock: FakeClock) -> None:
    _bootstrap_admin(container)
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            container.auth.authenticate(
                username='admin',
                password='wrong',
                device_id='dev-001',
                device_name='Test Device',
                ip='127.0.0.1',
            )
    with pytest.raises(UserLockedError):
        container.auth.authenticate(
            username='admin',
            password=_PASSWORD,
            device_id='dev-001',
            device_name='Test Device',
            ip='127.0.0.1',
        )
    locked = container.store.reader().execute(
        'SELECT event_type FROM audit_records WHERE event_type = ?',
        (EVENT_LOGIN_LOCKED,),
    ).fetchall()
    assert len(locked) >= 1


def test_lockout_clears_after_window(container: Container, clock: FakeClock) -> None:
    _bootstrap_admin(container)
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            container.auth.authenticate(
                username='admin',
                password='wrong',
                device_id='dev-001',
                device_name='Test Device',
                ip='127.0.0.1',
            )
    clock.advance(16 * 60)
    session = container.auth.authenticate(
        username='admin',
        password=_PASSWORD,
        device_id='dev-001',
        device_name='Test Device',
        ip='127.0.0.1',
    )
    assert session.user_id


def test_step_up_rotates_session(container: Container) -> None:
    _bootstrap_admin(container)
    original = container.auth.authenticate(
        username='admin',
        password=_PASSWORD,
        device_id='dev-001',
        device_name='Test Device',
        ip='127.0.0.1',
    )
    elevated = container.auth.confirm_step_up(
        raw_token=original.token,
        password=_PASSWORD,
        device_id='dev-001',
        device_name='Test Device',
        ip='127.0.0.1',
    )
    assert elevated.token != original.token
    assert elevated.step_up_confirmed_at is not None
    with pytest.raises(SessionError):
        container.auth.validate_session(original.token, ip='127.0.0.1')
    events = container.store.reader().execute(
        'SELECT event_type FROM audit_records WHERE event_type IN (?, ?)',
        (EVENT_SESSION_REVOKED, EVENT_STEP_UP_CONFIRMED),
    ).fetchall()
    assert len(events) >= 2


def test_step_up_window_expires(container: Container, clock: FakeClock) -> None:
    _bootstrap_admin(container)
    session = container.auth.authenticate(
        username='admin',
        password=_PASSWORD,
        device_id='dev-001',
        device_name='Test Device',
        ip='127.0.0.1',
    )
    elevated = container.auth.confirm_step_up(
        raw_token=session.token,
        password=_PASSWORD,
        device_id='dev-001',
        device_name='Test Device',
        ip='127.0.0.1',
    )
    container.auth.require_step_up(elevated)
    clock.advance(11 * 60)
    with pytest.raises(StepUpRequiredError, match='expired'):
        container.auth.require_step_up(elevated)


def test_step_up_requires_password_reentry(container: Container) -> None:
    _bootstrap_admin(container)
    session = container.auth.authenticate(
        username='admin',
        password=_PASSWORD,
        device_id='dev-001',
        device_name='Test Device',
        ip='127.0.0.1',
    )
    with pytest.raises(InvalidCredentialsError):
        container.auth.confirm_step_up(
            raw_token=session.token,
            password='wrong',
            device_id='dev-001',
            device_name='Test Device',
            ip='127.0.0.1',
        )


def test_password_change_revokes_all_sessions(container: Container) -> None:
    user_id = _bootstrap_admin(container)
    session = container.auth.authenticate(
        username='admin',
        password=_PASSWORD,
        device_id='dev-001',
        device_name='Test Device',
        ip='127.0.0.1',
    )
    container.auth.change_password(
        user_id=user_id,
        new_password='new-password-123!',
        by_user_id=user_id,
    )
    with pytest.raises(SessionError):
        container.auth.validate_session(session.token, ip='127.0.0.1')
    row = container.store.reader().execute(
        'SELECT event_type FROM audit_records WHERE event_type = ?',
        (EVENT_PASSWORD_CHANGED,),
    ).fetchone()
    assert row is not None
    active = container.store.reader().execute(
        'SELECT count(*) FROM client_sessions WHERE user_id = ? AND deleted_at IS NULL',
        (user_id,),
    ).fetchone()[0]
    assert active == 0


def test_expired_session_rejected(container: Container, clock: FakeClock) -> None:
    _bootstrap_admin(container)
    session = container.auth.authenticate(
        username='admin',
        password=_PASSWORD,
        device_id='dev-001',
        device_name='Test Device',
        ip='127.0.0.1',
    )
    clock.advance(8 * 24 * 3600)
    with pytest.raises(SessionError, match='expired'):
        container.auth.validate_session(session.token, ip='127.0.0.1')
