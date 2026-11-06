"""World lifecycle orchestration (Gate 3) — end-to-end Start/Stop via the
native adapter and the fake Minecraft server double."""

from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

import pytest

from app.bootstrap import build_container
from app.domain.value_objects import EndReason, WorldState
from app.services.worlds import WorldLifecycleError

_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS = _ROOT / "migrations"
_FAKE_SERVER = Path(__file__).resolve().parents[1] / "adapters" / "fake_server" / "fake_server.py"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _seed_world(
    store,
    world_id: str,
    port: int,
    world_root: Path,
    *,
    eula_arg: str = "--eula=accepted",
    addressing_strategy: str = "port",
    addressing_value: str | None = None,
) -> Path:
    now = 1_700_000_000
    world_dir = world_root / f"World {world_id}"
    world_dir.mkdir(parents=True)
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
        INSERT INTO global_settings (
            settings_id, timezone, idle_countdown_seconds, minecraft_root_path,
            backup_root_path, log_root_path, offsite_sync_defaults, version,
            updated_at, updated_by
        ) VALUES ('global', 'UTC', NULL, ?, ?, ?, '{}', 1, ?, 'u_admin')
        """,
        (str(world_root), str(world_root / "backups"), str(world_root / "logs"), now),
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
    launch_args = json.dumps(
        [
            sys.executable,
            str(_FAKE_SERVER),
            f"--port={port}",
            f"--rcon-port={port + 10}",
            f"--marker=world-{world_id}",
            eula_arg,
        ]
    )
    connection.execute(
        """
        INSERT INTO world_instances (
            world_id, display_name, template_id, server_type, mc_version, java_runtime_id,
            port, addressing_strategy, addressing_value, state, pre_backup_state,
            launch_args, metadata_version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES (?, ?, 'tpl', 'vanilla', '1.21', 'java', ?, ?,
                  ?, 'off', NULL, ?, 1, NULL, NULL, ?, ?)
        """,
        (
            world_id,
            f"World {world_id}",
            port,
            addressing_strategy,
            addressing_value if addressing_value is not None else str(port),
            launch_args,
            now,
            now,
        ),
    )
    connection.commit()
    return world_dir


def _wait_for(predicate, timeout_s: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _state(store, world_id: str) -> str:
    return (
        store.reader()
        .execute("SELECT state FROM world_instances WHERE world_id = ?", (world_id,))
        .fetchone()["state"]
    )


def test_worlds_start_reaches_running_then_stop_returns_off(tmp_path):
    port = _free_port()
    container = build_container(
        database_path=tmp_path / "lifecycle.db",
        keyfile_path=tmp_path / "lifecycle.key",
        migrations_dir=_MIGRATIONS,
    )
    try:
        _seed_world(container.store, "world_1", port, tmp_path / "worlds")
        worlds = container.worlds

        session_id = worlds.start(world_id="world_1")
        assert session_id.startswith("rs_")
        assert _wait_for(lambda: _state(container.store, "world_1") == WorldState.RUNNING.value)

        session = (
            container.store.reader()
            .execute(
                "SELECT * FROM runtime_sessions WHERE world_id = ? AND ended_at IS NULL",
                ("world_1",),
            )
            .fetchone()
        )
        assert session is not None
        assert session["rcon_port"] == port + 10

        # Live protocol ping must confirm level-4 readiness on the running world.
        from app.infrastructure.minecraft.ping import ping_protocol

        assert ping_protocol("127.0.0.1", port, timeout_s=1.0)

        worlds.stop(world_id="world_1")
        assert _state(container.store, "world_1") == WorldState.OFF.value
        ended = (
            container.store.reader()
            .execute("SELECT end_reason FROM runtime_sessions WHERE world_id = ?", ("world_1",))
            .fetchone()
        )
        assert ended["end_reason"] == EndReason.GRACEFUL_STOP.value

        # Stopped world: the protocol ping no longer answers.
        assert not ping_protocol("127.0.0.1", port, timeout_s=0.5)
    finally:
        container.store.close()


def test_worlds_reports_open_session_crash_and_reconciles_missing(tmp_path):
    port = _free_port()
    container = build_container(
        database_path=tmp_path / "lifecycle2.db",
        keyfile_path=tmp_path / "lifecycle2.key",
        migrations_dir=_MIGRATIONS,
    )
    try:
        _seed_world(container.store, "world_crash", port, tmp_path / "worlds")
        worlds = container.worlds

        session_id = worlds.start(world_id="world_crash")
        assert _wait_for(lambda: _state(container.store, "world_crash") == WorldState.RUNNING.value)

        # Supervisor tick: process is alive -> no crash reported yet.
        assert worlds.poll_running() == []

        worlds.stop(world_id="world_crash")
        assert _state(container.store, "world_crash") == WorldState.OFF.value

        # Reconcile with no open session must be a no-op.
        assert worlds.reconcile() == []
        assert session_id
    finally:
        container.store.close()


def test_start_rejects_unaccepted_eula_without_operation(tmp_path):
    port = _free_port()
    container = build_container(
        database_path=tmp_path / "eula.db",
        keyfile_path=tmp_path / "eula.key",
        migrations_dir=_MIGRATIONS,
    )
    try:
        _seed_world(
            container.store, "world_eula", port, tmp_path / "worlds", eula_arg="--eula=false"
        )

        with pytest.raises(WorldLifecycleError, match="EULA_NOT_ACCEPTED"):
            container.worlds.start(world_id="world_eula")

        state = _state(container.store, "world_eula")
        assert state == WorldState.EULA_REQUIRED.value
        operations = (
            container.store.reader().execute("SELECT COUNT(*) FROM operations").fetchone()[0]
        )
        assert operations == 0
    finally:
        container.store.close()


def test_absolute_path_addressing_uses_world_directory(tmp_path):
    port = _free_port()
    container = build_container(
        database_path=tmp_path / "path.db",
        keyfile_path=tmp_path / "path.key",
        migrations_dir=_MIGRATIONS,
    )
    try:
        explicit_dir = tmp_path / "custom-world"
        _seed_world(
            container.store,
            "world_path",
            port,
            tmp_path / "worlds",
            addressing_strategy="path",
            addressing_value=str(explicit_dir),
        )
        explicit_dir.mkdir()

        session_id = container.worlds.start(world_id="world_path")
        assert session_id.startswith("rs_")
        assert (explicit_dir / "server.properties").exists()
        assert not (tmp_path / "worlds" / "World world_path" / "server.properties").exists()

        container.worlds.stop(world_id="world_path")
    finally:
        container.store.close()
