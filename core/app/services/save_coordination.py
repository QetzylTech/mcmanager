"""Production RCON-backed autosave suspension (Gate 4, Doc 14 section 8).

Implements the :class:`app.services.backup.SaveCoordinator` protocol. A
running-world backup must never zip a world mid-write, so the coordinator:

1. Resolves the world's open ``runtime_sessions`` row (the single open
   session per world, enforced by ``ux_runtime_sessions_open``).
2. Decrypts that session's RCON password from ``secrets``.
3. Issues the closed-allowlist command ladder ``save-off`` -> ``save-all``
   -> ``save-on`` through :class:`RconClient`.

The session's ``rcon_port`` was recorded at spawn (migration 002), so the
coordinator also works after a manager restart / boot reconciliation.
"""

from __future__ import annotations

from app.infrastructure.minecraft.rcon import RconClient, RconError
from app.infrastructure.sqlite.connection import SqliteStore
from app.ports.secrets_store import SecretsStore


class RconSaveCoordinationError(Exception):
    """Raised when RCON save suspension/flush/resume cannot be completed."""


class RconSaveCoordinator:
    """SaveCoordinator backed by the per-session rotated RCON credential."""

    def __init__(self, store: SqliteStore, secrets: SecretsStore) -> None:
        self._store = store
        self._secrets = secrets

    def suspend_autosave(self, world_id: str) -> None:
        client = self._connect(world_id)
        try:
            client.command('save-off')
        except RconError as exc:
            raise RconSaveCoordinationError(f'save-off failed: {exc}') from exc
        finally:
            client.close()

    def flush(self, world_id: str) -> None:
        client = self._connect(world_id)
        try:
            client.command('save-all')
        except RconError as exc:
            raise RconSaveCoordinationError(f'save-all failed: {exc}') from exc
        finally:
            client.close()

    def resume_autosave(self, world_id: str) -> None:
        client = self._connect(world_id)
        try:
            client.command('save-on')
        except RconError as exc:
            raise RconSaveCoordinationError(f'save-on failed: {exc}') from exc
        finally:
            client.close()

    # -- helpers -----------------------------------------------------------

    def _session(self, world_id: str) -> dict:
        row = self._store.reader().execute(
            """
            SELECT session_id, rcon_secret_id, rcon_port, port_used
            FROM runtime_sessions
            WHERE world_id = ? AND ended_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (world_id,),
        ).fetchone()
        if row is None:
            raise RconSaveCoordinationError(
                f'no open runtime session for world {world_id}'
            )
        return dict(row)

    def _connect(self, world_id: str) -> RconClient:
        session = self._session(world_id)
        if not session['rcon_port']:
            raise RconSaveCoordinationError(
                f'rcon port missing for world {world_id} session {session["session_id"]}'
            )
        try:
            password = self._secrets.read(session['rcon_secret_id'])
        except Exception as exc:  # SecretsError
            raise RconSaveCoordinationError(
                f'rcon secret unreadable for world {world_id}'
            ) from exc
        client = RconClient('127.0.0.1', session['rcon_port'], password)
        try:
            client.connect()
        except RconError as exc:
            client.close()
            raise RconSaveCoordinationError(
                f'rcon connect failed for world {world_id}: {exc}'
            ) from exc
        return client
