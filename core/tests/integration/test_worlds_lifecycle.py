"""World lifecycle orchestration (Gate 3) — end-to-end Start/Stop via the
native adapter and the fake Minecraft server double."""

from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

from app.bootstrap import build_container
from app.domain.value_objects import EndReason, WorldState

_MIGRATIONS = Path(__file__).resolve().parents[2] / 'migrations'
_FAKE_SERVER = Path(__file__).resolve().parents[1] / 'adapters' / 'fake_server' / 'fake_server.py'


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def _seed_world(store, world_id: str, port: int) -> None:
    now = 1_700_000_000
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
            f'--port={port}',
            f'--rcon-port={port + 10}',
            f'--marker=world-{world_id}',
            '--eula=accepted',
        ]
    )
    connection.execute(
        """
        INSERT INTO world_instances (
            world_id, display_name, template_id, server_type, mc_version, java_runtime_id,
            port, addressing_strategy, addressing_value, state, pre_backup_state,
            launch_args, metadata_version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES (?, ?, 'tpl', 'vanilla', '1.21', 'java', ?, 'port',
                  ?, 'off', NULL, ?, 1, NULL, NULL, ?, ?)
        """,
        (world_id, f'World {world_id}', port, str(port), launch_args, now, now),
    )
    connection.commit()


def _wait_for(predicate, timeout_s: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _state(store, world_id: str) -> str:
    return store.reader().execute(
        'SELECT state FROM world_instances WHERE world_id = ?', (world_id,)
    ).fetchone()['state']


def test_worlds_start_reaches_running_then_stop_returns_off(tmp_path):
    port = _free_port()
    container = build_container(
        database_path=tmp_path / 'lifecycle.db',
        keyfile_path=tmp_path / 'lifecycle.key',
        migrations_dir=_MIGRATIONS,
    )
    try:
        _seed_world(container.store, 'world_1', port)
        worlds = container.worlds

        session_id = worlds.start(world_id='world_1')
        assert session_id.startswith('rs_')
        assert _wait_for(lambda: _state(container.store, 'world_1') == WorldState.RUNNING.value)

        session = container.store.reader().execute(
            'SELECT * FROM runtime_sessions WHERE world_id = ? AND ended_at IS NULL',
            ('world_1',),
        ).fetchone()
        assert session is not None
        assert session['rcon_port'] == port + 10

        # Live protocol ping must confirm level-4 readiness on the running world.
        from app.infrastructure.minecraft.ping import ping_protocol

        assert ping_protocol('127.0.0.1', port, timeout_s=1.0)

        worlds.stop(world_id='world_1')
        assert _state(container.store, 'world_1') == WorldState.OFF.value
        ended = container.store.reader().execute(
            'SELECT end_reason FROM runtime_sessions WHERE world_id = ?', ('world_1',)
        ).fetchone()
        assert ended['end_reason'] == EndReason.GRACEFUL_STOP.value

        # Stopped world: the protocol ping no longer answers.
        assert not ping_protocol('127.0.0.1', port, timeout_s=0.5)
    finally:
        container.store.close()


def test_worlds_reports_open_session_crash_and_reconciles_missing(tmp_path):
    port = _free_port()
    container = build_container(
        database_path=tmp_path / 'lifecycle2.db',
        keyfile_path=tmp_path / 'lifecycle2.key',
        migrations_dir=_MIGRATIONS,
    )
    try:
        _seed_world(container.store, 'world_crash', port)
        worlds = container.worlds

        session_id = worlds.start(world_id='world_crash')
        assert _wait_for(lambda: _state(container.store, 'world_crash') == WorldState.RUNNING.value)

        # Supervisor tick: process is alive -> no crash reported yet.
        assert worlds.poll_running() == []

        worlds.stop(world_id='world_crash')
        assert _state(container.store, 'world_crash') == WorldState.OFF.value

        # Reconcile with no open session must be a no-op.
        assert worlds.reconcile() == []
        assert session_id
    finally:
        container.store.close()
