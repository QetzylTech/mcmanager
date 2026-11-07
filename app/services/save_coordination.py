"""Production RCON-backed autosave suspension (Gate 4, Doc 14 section 8).

Implements the :class:`app.services.backup.SaveCoordinator` protocol. A
running-world backup must never zip a world mid-write, so the coordinator:

1. Resolves the world's open ``runtime_sessions`` row (the single open
   session per world, enforced by ``ux_runtime_sessions_open``).
2. Decrypts that session's RCON password from ``secrets``.
3. Issues the closed-allowlist command ladder ``save-off`` -> ``save-all``
   -> ``save-on`` through an injected RCON port.

The session's ``rcon_port`` was recorded at spawn (migration 002), so the
coordinator also works after a manager restart / boot reconciliation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from app.ports.minecraft import MinecraftRconError, MinecraftRconPort
from app.ports.persistence import PersistencePort
from app.ports.secrets_store import SecretsStore


class RconSaveCoordinationError(Exception):
    """Raised when RCON save suspension/flush/resume cannot be completed."""


@dataclass(frozen=True)
class RuntimeSessionRcon:
    """RCON lookup data for one currently open runtime session."""

    session_id: str
    rcon_secret_id: str
    rcon_port: int | None


class RconSaveCoordinator:
    """SaveCoordinator backed by the per-session rotated RCON credential."""

    def __init__(
        self,
        store: PersistencePort,
        secrets: SecretsStore,
        *,
        rcon_factory: Callable[[str, int, str], MinecraftRconPort] | None = None,
    ) -> None:
        self._store = store
        self._secrets = secrets
        self._rcon_factory = rcon_factory

    def _build_client(self, host: str, port: int, password: str) -> MinecraftRconPort:
        if self._rcon_factory is None:
            raise RconSaveCoordinationError('RCON client factory must be injected')
        return self._rcon_factory(host, port, password)

    def suspend_autosave(self, world_id: str) -> None:
        client = self._connect(world_id)
        try:
            client.command('save-off')
        except MinecraftRconError as exc:
            raise RconSaveCoordinationError(f'save-off failed: {exc}') from exc
        finally:
            client.close()

    def flush(self, world_id: str) -> None:
        client = self._connect(world_id)
        try:
            client.command('save-all')
        except MinecraftRconError as exc:
            raise RconSaveCoordinationError(f'save-all failed: {exc}') from exc
        finally:
            client.close()

    def resume_autosave(self, world_id: str) -> None:
        client = self._connect(world_id)
        try:
            client.command('save-on')
        except MinecraftRconError as exc:
            raise RconSaveCoordinationError(f'save-on failed: {exc}') from exc
        finally:
            client.close()

    # -- helpers -----------------------------------------------------------

    def _session(self, world_id: str) -> RuntimeSessionRcon:
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
        return RuntimeSessionRcon(
            session_id=cast(str, row['session_id']),
            rcon_secret_id=cast(str, row['rcon_secret_id']),
            rcon_port=cast(int | None, row['rcon_port']),
        )

    def _connect(self, world_id: str) -> MinecraftRconPort:
        session = self._session(world_id)
        if session.rcon_port is None:
            raise RconSaveCoordinationError(
                f'rcon port missing for world {world_id} session {session.session_id}'
            )
        try:
            password = self._secrets.read(session.rcon_secret_id)
        except Exception as exc:  # SecretsError
            raise RconSaveCoordinationError(
                f'rcon secret unreadable for world {world_id}'
            ) from exc
        client = self._build_client(
            '127.0.0.1', session.rcon_port, password
        )
        try:
            client.connect()
        except MinecraftRconError as exc:
            client.close()
            raise RconSaveCoordinationError(
                f'rcon connect failed for world {world_id}: {exc}'
            ) from exc
        return client
