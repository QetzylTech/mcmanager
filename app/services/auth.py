"""AuthenticationService (Document 8 section 9; Document 6 sections 1.1, 2.14).

Zero-trust identity core:

- Passwords hashed with **Argon2id** (never plaintext; stored via the
  ``secrets`` table, never on the users row).
- Session tokens random-per-issuance; **only the SHA-256 hash** is stored on
  ``client_sessions.session_id`` (Doc 7 section 2.23).
- **Session-ID rotation**: a fresh token after login, after step-up
  confirmation, and after a password change; the old row is revoked via
  ``deleted_at`` (Doc 8 section 9 — "no rotation = security defect").
- **Step-up**: password re-entry required (standing session is never enough)
  and the elevated state expires after the locked 10-minute window.
- Throttle/lockout: 5 failed logins -> 15-minute lockout (Doc 8 section 5.0).

Every login attempt — success, failure, and lockout — and every session
rotation, step-up confirmation, and password change writes an audit record
with actor/device snapshots captured at write time (Doc 6 section 0.1).
"""

from __future__ import annotations

import hashlib
import secrets as crypto
import uuid
from dataclasses import dataclass

import argon2

from app.ports.clock import Clock
from app.ports.persistence import PersistencePort
from app.ports.secrets_store import SecretsStore, SecretType
from app.services.audit import (
    EVENT_LOGIN_FAILED,
    EVENT_LOGIN_LOCKED,
    EVENT_LOGIN_SUCCESS,
    EVENT_PASSWORD_CHANGED,
    EVENT_SESSION_ISSUED,
    EVENT_SESSION_REVOKED,
    EVENT_STEP_UP_CONFIRMED,
    AuditService,
)

# Locked defaults (Doc 8 section 5.0; shipped as initial global defaults).
_MAX_FAILED_LOGINS = 5
_LOCKOUT_SECONDS = 15 * 60
_STEP_UP_WINDOW_S = 10 * 60  # the locked 10-minute step-up window
_SESSION_IDLE_SECONDS = 7 * 24 * 3600

_HASHER = argon2.PasswordHasher()

SUPERADMIN_ROLE = 'Superadmin'


class AuthenticationError(Exception):
    """Base class for authentication failures."""


class InvalidCredentialsError(AuthenticationError):
    """Username/password mismatch or unknown user."""


class UserLockedError(AuthenticationError):
    """Account locked after repeated failures."""


class UserDisabledError(AuthenticationError):
    """Account disabled by an operator."""


class SessionError(AuthenticationError):
    """Invalid, expired, or revoked session."""


class StepUpRequiredError(AuthenticationError):
    """Sensitive action requires a fresh password step-up."""


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _new_token() -> str:
    return crypto.token_urlsafe(32)


@dataclass(frozen=True)
class Session:
    """An issued client session. ``token`` is the raw bearer value shown to
    the client exactly once; only its SHA-256 is stored at rest."""

    user_id: str
    token: str
    expires_at: int
    step_up_confirmed_at: int | None
    created_at: int

    @property
    def session_id_hash(self) -> str:
        return _hash_token(self.token)


class AuthenticationService:
    """Identity core: users, password verification, sessions, step-up."""

    def __init__(
        self,
        store: PersistencePort,
        secrets_store: SecretsStore,
        clock: Clock,
        audit: AuditService,
    ) -> None:
        self._store = store
        self._secrets = secrets_store
        self._clock = clock
        self._audit = audit

    # -- users ---------------------------------------------------------------

    def provision_first_superadmin(
        self,
        *,
        username: str,
        password: str,
        device_id: str | None,
        device_name: str | None,
        ip: str,
    ) -> str:
        """Guard: only when no active user exists (Doc 6 section 4 —
        last-Superadmin invariant, inverse side).

        Creates the Superadmin baseline role if missing, the user, and its
        role assignment. This is the only bootstrap path into the system.
        """
        connection = self._store.reader()
        active = connection.execute(
            'SELECT count(*) FROM users WHERE deleted_at IS NULL'
        ).fetchone()[0]
        if active > 0:
            raise AuthenticationError('users already exist; first-superadmin path closed')

        now = int(self._clock.now())
        user_id = f'u_{uuid.uuid4().hex[:16]}'
        secret_id = self._secrets.store(
            secret_type=SecretType.USER_PASSWORD,
            associated_entity_type='user',
            associated_entity_id=user_id,
            plaintext=_HASHER.hash(password),
        )
        writer = self._store.writer()
        writer.execute(
            'INSERT INTO users ('
            '  user_id, username, display_name, secret_id, status,'
            '  failed_login_count, locked_until, created_by,'
            '  deleted_at, deleted_by, created_at, updated_at'
            ') VALUES (?, ?, NULL, ?, ?, 0, NULL, NULL, NULL, NULL, ?, ?)',
            (user_id, username, secret_id, 'active', now, now),
        )
        self._ensure_system_role(writer, SUPERADMIN_ROLE, now)
        role_id = self._role_id(writer, SUPERADMIN_ROLE)
        writer.execute(
            'INSERT INTO role_assignments ('
            '  assignment_id, user_id, role_id, granted_at, granted_by,'
            '  deleted_at, deleted_by'
            ') VALUES (?, ?, ?, ?, ?, NULL, NULL)',
            (f'ra_{uuid.uuid4().hex[:12]}', user_id, role_id, now, user_id),
        )
        writer.commit()
        self._audit.write(
            event_type='user_created',
            actor=self._audit.snapshot_for_user(
                user_id=user_id, device_id=device_id, device_name=device_name, ip=ip
            ),
            payload={'username': username, 'role': SUPERADMIN_ROLE, 'bootstrap': True},
        )
        return user_id

    def _ensure_system_role(self, connection: object, name: str, now: int) -> None:
        if self._role_id(connection, name) is not None:
            return
        connection.execute(
            'INSERT INTO roles ('
            '  role_id, name, description, is_system_role, version,'
            '  deleted_at, deleted_by, created_at, updated_at'
            ') VALUES (?, ?, ?, 1, 1, NULL, NULL, ?, ?)',
            (f'r_{uuid.uuid4().hex[:12]}', name, f'baseline {name} role', now, now),
        )

    def _role_id(self, connection: object, name: str) -> str | None:
        row = connection.execute(
            'SELECT role_id FROM roles WHERE name = ? AND deleted_at IS NULL', (name,)
        ).fetchone()
        return row['role_id'] if row is not None else None

    # -- password ---------------------------------------------------------------

    def _password_secret(self, user_id: str) -> str:
        row = self._store.reader().execute(
            'SELECT secret_id FROM users WHERE user_id = ?', (user_id,)
        ).fetchone()
        if row is None:
            raise InvalidCredentialsError('unknown user')
        return row['secret_id']

    def _verify_password(self, user_id: str, password: str) -> bool:
        stored = self._secrets.read(self._password_secret(user_id))
        try:
            _HASHER.verify(stored, password)
            return True
        except argon2.exceptions.VerificationError:
            # Covers VerifyMismatchError (wrong password) and
            # InvalidHashError/VerificationError (corrupt/canned hash):
            # a failed verification is a failed login, never an exception.
            return False

    # -- login / throttle ------------------------------------------------------

    def authenticate(
        self,
        *,
        username: str,
        password: str,
        device_id: str | None,
        device_name: str | None,
        ip: str,
    ) -> Session:
        """Verify credentials, enforce throttle/lockout, audit, issue session."""
        now = self._clock.now()
        row = self._store.reader().execute(
            'SELECT user_id, status, failed_login_count, locked_until '
            'FROM users WHERE username = ? AND deleted_at IS NULL',
            (username,),
        ).fetchone()
        if row is None:
            self._audit.write(
                event_type=EVENT_LOGIN_FAILED,
                actor=self._audit.system(),
                payload={'username': username, 'ip': ip, 'reason': 'unknown_user'},
            )
            raise InvalidCredentialsError('invalid credentials')

        user_id = row['user_id']
        actor = self._audit.snapshot_for_user(
            user_id=user_id, device_id=device_id, device_name=device_name, ip=ip
        )
        if row['status'] == 'locked' and row['locked_until'] and now < row['locked_until']:
            self._audit.write(event_type=EVENT_LOGIN_LOCKED, actor=actor)
            raise UserLockedError('account locked; try again later')
        if row['status'] == 'disabled':
            self._audit.write(
                event_type=EVENT_LOGIN_FAILED, actor=actor, payload={'reason': 'disabled'}
            )
            raise UserDisabledError('account disabled')

        if not self._verify_password(user_id, password):
            self._register_failure(user_id, row['failed_login_count'], actor)
            self._audit.write(
                event_type=EVENT_LOGIN_FAILED, actor=actor, payload={'reason': 'bad_password'}
            )
            raise InvalidCredentialsError('invalid credentials')

        # Also clear a stale 'locked' status left after the lockout window
        # elapsed without an intervening login (Doc 6 section 2.1:
        # Locked -> Active on cooldown expiry).
        self._store.writer().execute(
            'UPDATE users SET failed_login_count = 0, locked_until = NULL, '
            'status = CASE WHEN status = \'locked\' THEN \'active\' ELSE status END, '
            'updated_at = ? WHERE user_id = ?',
            (int(now), user_id),
        )
        self._store.writer().commit()
        self._audit.write(event_type=EVENT_LOGIN_SUCCESS, actor=actor)
        return self.issue_session(
            user_id=user_id, device_id=device_id, device_name=device_name, ip=ip
        )

    def _register_failure(self, user_id: str, previous_count: int, actor: object) -> None:
        writer = self._store.writer()
        count = previous_count + 1
        now = int(self._clock.now())
        locked_until = now + _LOCKOUT_SECONDS if count >= _MAX_FAILED_LOGINS else None
        writer.execute(
            'UPDATE users SET failed_login_count = ?, locked_until = ?, status = ?, '
            'updated_at = ? WHERE user_id = ?',
            (
                count,
                locked_until,
                'locked' if locked_until else 'active',
                now,
                user_id,
            ),
        )
        writer.commit()
        if locked_until:
            self._audit.write(
                event_type=EVENT_LOGIN_LOCKED,
                actor=actor,
                payload={'lockout_seconds': _LOCKOUT_SECONDS},
            )

    # -- sessions --------------------------------------------------------------

    def _ensure_device(
        self, *, device_id: str | None, device_name: str | None, ip: str
    ) -> None:
        """Upsert the device row before a session references it (FK invariant).

        A new device enters as ``unrecognized`` (admin approval later —
        Doc 6 section 2.13); every sighting refreshes ``last_seen_at``.
        Accepting no device_id leaves ``client_sessions.device_id`` NULL
        (raw-IP-only context is audit-legal, Doc 6 section 0.1).
        """
        if device_id is None:
            return
        writer = self._store.writer()
        now = int(self._clock.now())
        writer.execute(
            'INSERT INTO devices ('
            '  device_id, device_name, ip_address, owner, status,'
            '  last_seen_at, deleted_at, deleted_by, created_at, updated_at'
            ') VALUES (?, ?, ?, NULL, ?, ?, NULL, NULL, ?, ?) '
            'ON CONFLICT(device_id) DO UPDATE SET last_seen_at = excluded.last_seen_at',
            (
                device_id,
                device_name or device_id,
                ip,
                'unrecognized',
                now,
                now,
                now,
            ),
        )
        writer.commit()

    def issue_session(
        self,
        *,
        user_id: str,
        device_id: str | None,
        device_name: str | None,
        ip: str,
    ) -> Session:
        """Issue a fresh session after login/rotation (token hashed at rest)."""
        self._ensure_device(device_id=device_id, device_name=device_name, ip=ip)
        now = self._clock.now()
        session = Session(
            user_id=user_id,
            token=_new_token(),
            expires_at=int(now) + _SESSION_IDLE_SECONDS,
            step_up_confirmed_at=None,
            created_at=int(now),
        )
        writer = self._store.writer()
        writer.execute(
            'INSERT INTO client_sessions ('
            '  session_id, user_id, device_id, ip_address,'
            '  expires_at, step_up_confirmed_at, last_activity_at,'
            '  deleted_at, deleted_by, created_at'
            ') VALUES (?, ?, ?, ?, ?, NULL, ?, NULL, NULL, ?)',
            (
                session.session_id_hash,
                user_id,
                device_id,
                ip,
                session.expires_at,
                int(now),
                int(now),
            ),
        )
        writer.commit()
        self._audit.write(
            event_type=EVENT_SESSION_ISSUED,
            actor=self._audit.snapshot_for_user(
                user_id=user_id, device_id=device_id, device_name=device_name, ip=ip
            ),
        )
        return session

    def validate_session(self, raw_token: str, *, ip: str) -> Session:
        """Resolve a bearer token to a live session (revoked/expired = reject)."""
        session_hash = _hash_token(raw_token)
        row = self._store.reader().execute(
            'SELECT user_id, expires_at, step_up_confirmed_at, last_activity_at, '
            'created_at, deleted_at '
            'FROM client_sessions WHERE session_id = ?',
            (session_hash,),
        ).fetchone()
        if row is None or row['deleted_at'] is not None:
            raise SessionError('session revoked or unknown')
        now = self._clock.now()
        if row['expires_at'] < now:
            self.revoke_session_id(session_hash)
            raise SessionError('session expired')
        return Session(
            user_id=row['user_id'],
            token=raw_token,
            expires_at=row['expires_at'],
            step_up_confirmed_at=row['step_up_confirmed_at'],
            created_at=row['created_at'],
        )

    def revoke_session_id(self, session_id_hash: str) -> None:
        writer = self._store.writer()
        row = writer.execute(
            'SELECT user_id FROM client_sessions WHERE session_id = ?', (session_id_hash,)
        ).fetchone()
        if row is None:
            return
        writer.execute(
            'UPDATE client_sessions SET deleted_at = ?, deleted_by = ?, last_activity_at = ? '
            'WHERE session_id = ?',
            (int(self._clock.now()), 'system', int(self._clock.now()), session_id_hash),
        )
        writer.commit()
        self._audit.write(
            event_type=EVENT_SESSION_REVOKED,
            actor=self._audit.system(),
            payload={'user_id': row['user_id']},
        )

    # -- step-up ---------------------------------------------------------------

    def confirm_step_up(
        self,
        *,
        raw_token: str,
        password: str,
        device_id: str | None,
        device_name: str | None,
        ip: str,
    ) -> Session:
        """Step-up requires password RE-ENTRY (standing session insufficient,
        Doc 6 section 4). Success = fresh rotated session with a confirmed
        step-up timestamp (Doc 8 section 9 rotation rule).
        """
        current = self.validate_session(raw_token, ip=ip)
        if not self._verify_password(current.user_id, password):
            actor = self._audit.snapshot_for_user(
                user_id=current.user_id,
                device_id=device_id,
                device_name=device_name,
                ip=ip,
            )
            self._audit.write(
                event_type=EVENT_LOGIN_FAILED, actor=actor, payload={'reason': 'step_up'}
            )
            raise InvalidCredentialsError('step-up password rejected')

        self.revoke_session_id(current.session_id_hash)
        session = self.issue_session(
            user_id=current.user_id, device_id=device_id, device_name=device_name, ip=ip
        )
        confirmed_at = int(self._clock.now())
        writer = self._store.writer()
        writer.execute(
            'UPDATE client_sessions SET step_up_confirmed_at = ? WHERE session_id = ?',
            (confirmed_at, session.session_id_hash),
        )
        writer.commit()
        elevated = Session(
            user_id=session.user_id,
            token=session.token,
            expires_at=session.expires_at,
            step_up_confirmed_at=confirmed_at,
            created_at=session.created_at,
        )
        self._audit.write(
            event_type=EVENT_STEP_UP_CONFIRMED,
            actor=self._audit.snapshot_for_user(
                user_id=current.user_id,
                device_id=device_id,
                device_name=device_name,
                ip=ip,
            ),
        )
        return elevated

    def require_step_up(self, session: Session) -> None:
        """Server-enforced 10-minute elevated window (Doc 6 section 2.14)."""
        confirmed = session.step_up_confirmed_at
        if confirmed is None:
            raise StepUpRequiredError('step-up not confirmed')
        if self._clock.now() - confirmed > _STEP_UP_WINDOW_S:
            raise StepUpRequiredError('step-up window expired')

    # -- password change ---------------------------------------------------------

    def change_password(self, *, user_id: str, new_password: str, by_user_id: str) -> None:
        """Rotate the password secret and revoke ALL of the target's sessions.

        No session is issued here: minting a token for the target user would
        hand an impersonation credential to ``by_user_id`` (the Superadmin
        reset path). After a password change every old session is dead; the
        target re-authenticates and the fresh login issues a new session —
        satisfying the Doc 8 section 9 rotation rule without escalation.
        """
        writer = self._store.writer()
        now = int(self._clock.now())
        new_secret = self._secrets.rotate(
            self._password_secret(user_id),
            new_plaintext=_HASHER.hash(new_password),
            associated_entity_type='user',
            associated_entity_id=user_id,
        )
        writer.execute(
            'UPDATE users SET secret_id = ?, updated_at = ? WHERE user_id = ?',
            (new_secret, now, user_id),
        )
        writer.execute(
            'UPDATE client_sessions SET deleted_at = ?, deleted_by = ? '
            'WHERE user_id = ? AND deleted_at IS NULL',
            (now, by_user_id, user_id),
        )
        writer.commit()
        self._audit.write(
            event_type=EVENT_PASSWORD_CHANGED,
            actor=self._audit.snapshot_for_user(
                user_id=by_user_id, device_id=None, device_name=None, ip=None
            ),
            payload={'target_user_id': user_id},
        )
