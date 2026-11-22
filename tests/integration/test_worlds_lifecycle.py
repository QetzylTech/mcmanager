"""World lifecycle orchestration (Gate 3) — end-to-end Start/Stop via the
native adapter and the fake Minecraft server double."""

from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

import pytest

from app import create_app
from app.bootstrap import build_container
from app.domain.value_objects import (
    ActorType,
    EndReason,
    OperationStatus,
    OperationType,
    WorldState,
)
from app.ports.process_control import ProbeResult
from app.services.operations import OperationInput
from app.services.worlds import StartTimeoutError, WorldLifecycleError
from app.web.middleware import session_csrf_token

_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS = _ROOT / "app" / "migrations"
_FAKE_SERVER = Path(__file__).resolve().parents[1] / "adapters" / "fake_server" / "fake_server.py"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _free_port_pair(used_ports: set[int]) -> int:
    for _ in range(100):
        candidate = _free_port()
        if (
            candidate + 10 > 65535
            or candidate in used_ports
            or candidate + 10 in used_ports
            or candidate - 10 in used_ports
        ):
            continue
        sockets = []
        pair_is_free = True
        try:
            for port in (candidate, candidate + 10):
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sockets.append(sock)
                sock.bind(("127.0.0.1", port))
        except OSError:
            pair_is_free = False
        finally:
            for sock in sockets:
                sock.close()
        if pair_is_free and not any(
            _port_is_listening(port) for port in (candidate, candidate + 10)
        ):
            return candidate
    raise RuntimeError("could not reserve an unused server/RCON port pair")


def _port_is_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
            return True
    except OSError:
        return False


def _seed_world(
    store,
    world_id: str,
    port: int,
    world_root: Path,
    *,
    eula_arg: str = "--eula=accepted",
    addressing_strategy: str = "port",
    addressing_value: str | None = None,
    audited_eula: bool | None = None,
    ready_ms: int = 0,
) -> Path:
    now = 1_700_000_000
    world_dir = world_root / f"World {world_id}"
    world_dir.mkdir(parents=True)
    eula_accepted = eula_arg != "--eula=false"
    (world_dir / "eula.txt").write_text(
        f"eula={'true' if eula_accepted else 'false'}\n", encoding="utf-8"
    )
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
    launch_argv = [
        sys.executable,
        str(_FAKE_SERVER),
        f"--port={port}",
        f"--rcon-port={port + 10}",
        f"--marker=world-{world_id}",
        eula_arg,
    ]
    if ready_ms:
        launch_argv.append(f"--ready-ms={ready_ms}")
    launch_args = json.dumps(launch_argv)
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
    if audited_eula if audited_eula is not None else eula_accepted:
        connection.execute(
            """
            INSERT INTO audit_records (
                audit_id, event_type, actor_type, actor_user_id,
                actor_username_snapshot, world_id, payload, created_at
            ) VALUES (?, 'world_eula_accepted', 'user', 'u_admin', 'admin', ?, ?, ?)
            """,
            (f"au_{world_id}", world_id, '{"accepted": true}', now),
        )
    connection.commit()
    return world_dir


def _insert_lifecycle_world(
    store, world_id: str, port: int, world_root: Path, ready_ms: int
) -> Path:
    now = 1_700_000_000
    world_dir = world_root / f"World {world_id}"
    world_dir.mkdir(parents=True)
    (world_dir / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    launch_args = json.dumps(
        [
            sys.executable,
            str(_FAKE_SERVER),
            f"--port={port}",
            f"--rcon-port={port + 10}",
            f"--marker=world-{world_id}",
            f"--ready-ms={ready_ms}",
            "--eula=accepted",
        ]
    )
    store.writer().execute(
        """
        INSERT INTO world_instances (
            world_id, display_name, template_id, server_type, mc_version, java_runtime_id,
            port, addressing_strategy, addressing_value, state, pre_backup_state,
            launch_args, metadata_version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES (?, ?, 'tpl', 'vanilla', '1.21', 'java', ?, 'port',
                  ?, 'off', NULL, ?, 1, NULL, NULL, ?, ?)
        """,
        (
            world_id,
            f"World {world_id}",
            port,
            str(port),
            launch_args,
            now,
            now,
        ),
    )
    store.writer().execute(
        """
        INSERT INTO audit_records (
            audit_id, event_type, actor_type, actor_user_id,
            actor_username_snapshot, world_id, payload, created_at
        ) VALUES (?, 'world_eula_accepted', 'user', 'u_admin', 'admin', ?, ?, ?)
        """,
        (f"au_{world_id}", world_id, '{"accepted": true}', now),
    )
    store.writer().commit()
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
        session_log = tmp_path / "worlds" / "logs" / "world_1" / f"{session_id}.log"
        channel_log = session_log.with_name(f"{session_id}.stdout.log")
        assert _wait_for(
            lambda: session_log.exists()
            and "Starting minecraft server" in session_log.read_text(encoding="utf-8")
        )
        assert "Starting minecraft server" in channel_log.read_text(encoding="utf-8")

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


def test_world_kill_forces_off_and_terminalizes_forced_stop(tmp_path):
    port = _free_port()
    container = build_container(
        database_path=tmp_path / "kill-lifecycle.db",
        keyfile_path=tmp_path / "kill-lifecycle.key",
        migrations_dir=_MIGRATIONS,
    )
    try:
        _seed_world(container.store, "world_kill", port, tmp_path / "worlds")
        session_id = container.worlds.start(world_id="world_kill")
        assert _wait_for(
            lambda: _state(container.store, "world_kill") == WorldState.RUNNING.value
        )

        op_id = container.worlds.kill(world_id="world_kill")

        assert _state(container.store, "world_kill") == WorldState.OFF.value
        operation = container.operations.get(op_id)
        assert operation["status"] == OperationStatus.COMPLETED.value
        session = (
            container.store.reader()
            .execute(
                "SELECT end_reason, ended_at FROM runtime_sessions "
                "WHERE world_id = ? AND session_id = ?",
                ("world_kill", session_id),
            )
            .fetchone()
        )
        assert session["end_reason"] == EndReason.FORCED_STOP.value
        assert session["ended_at"] is not None
        assert container.worlds.supervisor_interval_seconds() == 15.0
    finally:
        container.store.close()


def test_queued_world_starts_run_in_parallel_with_configurable_limit(tmp_path):
    container = build_container(
        database_path=tmp_path / "parallel.db",
        keyfile_path=tmp_path / "parallel.key",
        migrations_dir=_MIGRATIONS,
    )
    world_ids = [f"world_parallel_{index}" for index in range(6)]
    failure_world_ids = [f"world_failure_{index}" for index in range(3)]
    selected_ports = []
    while len(selected_ports) < len(world_ids) + len(failure_world_ids):
        selected_ports.append(_free_port_pair(set(selected_ports)))
    seeded_world_ids = []
    try:
        root = tmp_path / "worlds"
        _seed_world(
            container.store,
            world_ids[0],
            selected_ports[0],
            root,
            ready_ms=2000,
        )
        seeded_world_ids.append(world_ids[0])
        for world_id, port in zip(
            world_ids[1:], selected_ports[1 : len(world_ids)], strict=True
        ):
            _insert_lifecycle_world(container.store, world_id, port, root, 2000)
            seeded_world_ids.append(world_id)

        operations = [
            container.worlds.enqueue_start(
                world_id=world_id,
                actor_type=ActorType.USER,
                actor_user_id="u_admin",
                idempotency_key=f"parallel-default-{world_id}",
            )[0]
            for world_id in world_ids
        ]
        started_at = time.monotonic()
        dispatched = container.worlds.dispatch_queued_operations()
        elapsed = time.monotonic() - started_at
        assert len(dispatched) == 3
        assert elapsed < 5.5
        assert sum(
            _state(container.store, world_id) == WorldState.RUNNING.value
            for world_id in world_ids
        ) == 3
        assert sum(
            container.operations.get(operation["op_id"])["status"]
            == OperationStatus.QUEUED.value
            for operation in operations
        ) == 3

        container.store.writer().execute(
            "UPDATE global_settings SET max_concurrent_world_starts = 1"
        )
        container.store.writer().commit()
        limited_dispatched = container.worlds.dispatch_queued_operations()
        assert len(limited_dispatched) == 1
        assert sum(
            _state(container.store, world_id) == WorldState.RUNNING.value
            for world_id in world_ids
        ) == 4
        assert sum(
            container.operations.get(operation["op_id"])["status"]
            == OperationStatus.QUEUED.value
            for operation in operations
        ) == 2

        container.store.writer().execute(
            "UPDATE global_settings SET max_concurrent_world_starts = 0"
        )
        container.store.writer().commit()
        container.worlds.dispatch_queued_operations()
        assert all(
            _state(container.store, world_id) == WorldState.RUNNING.value
            for world_id in world_ids
        )

        for world_id, candidate in zip(
            failure_world_ids, selected_ports[len(world_ids) :], strict=True
        ):
            _insert_lifecycle_world(container.store, world_id, candidate, root, 0)
            seeded_world_ids.append(world_id)
        container.store.writer().execute(
            "UPDATE global_settings SET max_concurrent_world_starts = 0"
        )
        container.store.writer().commit()
        failure_operations = [
            container.worlds.enqueue_start(
                world_id=world_id,
                actor_type=ActorType.USER,
                actor_user_id="u_admin",
                idempotency_key=f"parallel-failure-{world_id}",
            )[0]
            for world_id in failure_world_ids
        ]
        (
            container.worlds._world_dir(
                container.worlds._world(failure_world_ids[0])
            )
            / "eula.txt"
        ).write_text("eula=false\n", encoding="utf-8")
        failure_dispatched = container.worlds.dispatch_queued_operations()
        assert {operation["op_id"] for operation in failure_operations} <= set(
            failure_dispatched
        )
        assert (
            container.operations.get(failure_operations[0]["op_id"])["status"]
            == OperationStatus.FAILED.value
        )
        assert all(
            _state(container.store, world_id) == WorldState.RUNNING.value
            for world_id in failure_world_ids[1:]
        )
    finally:
        try:
            for world_id in seeded_world_ids:
                if _state(container.store, world_id) == WorldState.RUNNING.value:
                    container.worlds.stop(world_id=world_id)
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


def test_reconcile_never_probes_eula_required_world(tmp_path, monkeypatch):
    container = build_container(
        database_path=tmp_path / "eula-reconcile.db",
        keyfile_path=tmp_path / "eula-reconcile.key",
        migrations_dir=_MIGRATIONS,
    )
    try:
        port = _free_port()
        _seed_world(container.store, "world_eula_reconcile", port, tmp_path / "worlds")
        now = int(container.clock.now())
        connection = container.store.writer()
        connection.execute(
            "UPDATE world_instances SET state = ? WHERE world_id = ?",
            (WorldState.EULA_REQUIRED.value, "world_eula_reconcile"),
        )
        connection.execute(
            """
            INSERT INTO runtime_sessions (
                session_id, world_id, started_at, ended_at, end_reason,
                rcon_secret_id, port_used, java_runtime_id,
                launch_args_snapshot, rcon_port, created_at
            ) VALUES (?, ?, ?, NULL, NULL, 'sec_admin', ?, 'java', '{}', ?, ?)
            """,
            ("rs_eula_reconcile", "world_eula_reconcile", now, port, port + 10, now),
        )
        connection.commit()

        def unexpected_probe(*_args, **_kwargs):
            raise AssertionError("eula_required worlds must not be probed")

        monkeypatch.setattr(container.process_adapter, "probe", unexpected_probe)

        assert container.worlds.reconcile() == []
        session = (
            container.store.reader()
            .execute(
                "SELECT ended_at FROM runtime_sessions WHERE session_id = ?",
                ("rs_eula_reconcile",),
            )
            .fetchone()
        )
        assert session["ended_at"] is None
    finally:
        container.store.close()


def test_reconcile_fails_interrupted_start_without_open_session(tmp_path):
    container = build_container(
        database_path=tmp_path / "interrupted-start.db",
        keyfile_path=tmp_path / "interrupted-start.key",
        migrations_dir=_MIGRATIONS,
    )
    try:
        _seed_world(container.store, "world_interrupted", _free_port(), tmp_path / "worlds")
        operation = container.operations.create(
            OperationInput(
                op_type=OperationType.START,
                actor_type=ActorType.SYSTEM,
                world_id="world_interrupted",
            ),
            initial_status=OperationStatus.RUNNING,
        )
        container.store.writer().execute(
            "UPDATE world_instances SET state = ? WHERE world_id = ?",
            (WorldState.STARTING.value, "world_interrupted"),
        )
        container.store.writer().commit()

        assert container.worlds.reconcile() == []

        operation_row = container.operations.get(operation["op_id"])
        assert operation_row["status"] == OperationStatus.FAILED.value
        assert operation_row["error_code"] == "manager_restart_incomplete"
        assert _state(container.store, "world_interrupted") == WorldState.ERROR.value
        assert (
            container.store.reader()
            .execute(
                "SELECT COUNT(*) FROM audit_records WHERE operation_id = ?",
                (operation["op_id"],),
            )
            .fetchone()[0]
            == 1
        )
    finally:
        container.store.close()


def test_reconcile_fails_start_when_open_session_process_is_missing(tmp_path, monkeypatch):
    port = _free_port()
    container = build_container(
        database_path=tmp_path / "missing-start-process.db",
        keyfile_path=tmp_path / "missing-start-process.key",
        migrations_dir=_MIGRATIONS,
    )
    try:
        _seed_world(container.store, "world_missing_process", port, tmp_path / "worlds")
        operation = container.operations.create(
            OperationInput(
                op_type=OperationType.START,
                actor_type=ActorType.SYSTEM,
                world_id="world_missing_process",
            ),
            initial_status=OperationStatus.RUNNING,
        )
        session_id = "rs_interrupted_start"
        now = int(container.clock.now())
        connection = container.store.writer()
        connection.execute(
            "UPDATE world_instances SET state = ? WHERE world_id = ?",
            (WorldState.STARTING.value, "world_missing_process"),
        )
        connection.execute(
            """
            INSERT INTO runtime_sessions (
                session_id, world_id, started_at, ended_at, end_reason,
                rcon_secret_id, port_used, java_runtime_id,
                launch_args_snapshot, created_at
            ) VALUES (?, ?, ?, NULL, NULL, 'sec_admin', ?, 'java', '{}', ?)
            """,
            (session_id, "world_missing_process", now, port, now),
        )
        connection.commit()
        monkeypatch.setattr(
            container.process_adapter,
            "probe",
            lambda *_args, **_kwargs: ProbeResult(found=False),
        )

        assert container.worlds.reconcile() == []

        operation_row = container.operations.get(operation["op_id"])
        session = (
            container.store.reader()
            .execute(
                "SELECT ended_at, end_reason FROM runtime_sessions WHERE session_id = ?",
                (session_id,),
            )
            .fetchone()
        )
        assert operation_row["status"] == OperationStatus.FAILED.value
        assert operation_row["error_code"] == "manager_restart_incomplete"
        assert _state(container.store, "world_missing_process") == WorldState.ERROR.value
        assert session["ended_at"] is not None
        assert session["end_reason"] == EndReason.RECONCILED_MISSING.value
        assert (
            container.store.reader()
            .execute(
                "SELECT COUNT(*) FROM audit_records WHERE operation_id = ?",
                (operation["op_id"],),
            )
            .fetchone()[0]
            == 1
        )
    finally:
        container.store.close()


def test_start_timeout_terminalizes_operation_and_closes_session(tmp_path, monkeypatch):
    while True:
        port = _free_port()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as rcon_sock:
            try:
                rcon_sock.bind(("127.0.0.1", port + 10))
            except OSError:
                continue
        break
    container = build_container(
        database_path=tmp_path / "start-timeout.db",
        keyfile_path=tmp_path / "start-timeout.key",
        migrations_dir=_MIGRATIONS,
    )
    try:
        _seed_world(container.store, "world_start_timeout", port, tmp_path / "worlds")
        monkeypatch.setattr("app.services.worlds.START_READINESS_TIMEOUT_S", 0)

        with pytest.raises(StartTimeoutError):
            container.worlds.start(world_id="world_start_timeout")

        operation = (
            container.store.reader()
            .execute(
                "SELECT op_id, status, error_code FROM operations WHERE world_id = ?",
                ("world_start_timeout",),
            )
            .fetchone()
        )
        session = (
            container.store.reader()
            .execute(
                "SELECT ended_at, end_reason FROM runtime_sessions WHERE world_id = ?",
                ("world_start_timeout",),
            )
            .fetchone()
        )
        assert operation["status"] == OperationStatus.TIMED_OUT.value
        assert operation["error_code"] == "START_TIMEOUT"
        assert _state(container.store, "world_start_timeout") == WorldState.ERROR.value
        assert session["ended_at"] is not None
        assert session["end_reason"] == EndReason.CRASHED.value
        assert (
            container.store.reader()
            .execute(
                "SELECT COUNT(*) FROM audit_records WHERE operation_id = ?",
                (operation["op_id"],),
            )
            .fetchone()[0]
            == 1
        )
    finally:
        container.store.close()


def test_reconcile_records_crash_operation_audit_and_notification(tmp_path, monkeypatch):
    port = _free_port()
    container = build_container(
        database_path=tmp_path / "reconciled-crash.db",
        keyfile_path=tmp_path / "reconciled-crash.key",
        migrations_dir=_MIGRATIONS,
    )
    try:
        _seed_world(container.store, "world_reconciled_crash", port, tmp_path / "worlds")
        now = int(container.clock.now())
        connection = container.store.writer()
        connection.execute(
            "UPDATE world_instances SET state = ? WHERE world_id = ?",
            (WorldState.RUNNING.value, "world_reconciled_crash"),
        )
        connection.execute(
            """
            INSERT INTO runtime_sessions (
                session_id, world_id, started_at, ended_at, end_reason,
                rcon_secret_id, port_used, java_runtime_id,
                launch_args_snapshot, created_at
            ) VALUES ('rs_reconciled_crash', ?, ?, NULL, NULL, 'sec_admin', ?, 'java', '{}', ?)
            """,
            ("world_reconciled_crash", now, port, now),
        )
        connection.commit()
        monkeypatch.setattr(
            container.process_adapter,
            "probe",
            lambda *_args, **_kwargs: ProbeResult(found=False),
        )

        assert container.worlds.reconcile() == []

        crash = (
            container.store.reader()
            .execute(
                "SELECT op_id, status FROM operations WHERE op_type = ?",
                (OperationType.CRASH_DETECTED.value,),
            )
            .fetchone()
        )
        session = (
            container.store.reader()
            .execute(
                "SELECT ended_at, end_reason FROM runtime_sessions WHERE session_id = ?",
                ("rs_reconciled_crash",),
            )
            .fetchone()
        )
        notification = (
            container.store.reader()
            .execute(
                "SELECT category, severity, related_operation_id, related_world_id "
                "FROM notifications WHERE related_operation_id = ?",
                (crash["op_id"],),
            )
            .fetchone()
        )
        assert crash["status"] == OperationStatus.COMPLETED.value
        assert _state(container.store, "world_reconciled_crash") == WorldState.CRASHED.value
        assert session["ended_at"] is not None
        assert session["end_reason"] == EndReason.RECONCILED_MISSING.value
        assert (
            container.store.reader()
            .execute(
                "SELECT COUNT(*) FROM audit_records WHERE operation_id = ?",
                (crash["op_id"],),
            )
            .fetchone()[0]
            == 1
        )
        assert notification["category"] == "world_lifecycle"
        assert notification["severity"] == "critical"
        assert notification["related_world_id"] == "world_reconciled_crash"
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


def test_external_eula_file_edit_cannot_bypass_audited_acceptance(tmp_path):
    port = _free_port()
    container = build_container(
        database_path=tmp_path / "external-eula.db",
        keyfile_path=tmp_path / "external-eula.key",
        migrations_dir=_MIGRATIONS,
    )
    try:
        world_dir = _seed_world(
            container.store,
            "world_external_eula",
            port,
            tmp_path / "worlds",
            audited_eula=False,
        )
        (world_dir / "eula.txt").write_text("eula=true\n", encoding="utf-8")

        with pytest.raises(WorldLifecycleError, match="EULA_NOT_ACCEPTED"):
            container.worlds.start(world_id="world_external_eula")

        assert _state(container.store, "world_external_eula") == WorldState.EULA_REQUIRED.value
        assert (
            container.store.reader().execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0
        )
    finally:
        container.store.close()


def test_eula_acceptance_is_explicit_and_audited(tmp_path):
    port = _free_port()
    container = build_container(
        database_path=tmp_path / "accept-eula.db",
        keyfile_path=tmp_path / "accept-eula.key",
        migrations_dir=_MIGRATIONS,
    )
    try:
        world_dir = _seed_world(
            container.store,
            "world_accept_eula",
            port,
            tmp_path / "worlds",
            eula_arg="--eula=false",
        )
        container.store.writer().execute(
            "UPDATE world_instances SET state = ? WHERE world_id = ?",
            (WorldState.EULA_REQUIRED.value, "world_accept_eula"),
        )
        container.store.writer().commit()

        with pytest.raises(WorldLifecycleError, match="explicit EULA acceptance"):
            container.worlds.accept_eula(
                world_id="world_accept_eula",
                actor_user_id="u_admin",
                accepted=False,
            )
        assert "eula=false" in (world_dir / "eula.txt").read_text(encoding="utf-8")

        operation, replayed = container.worlds.accept_eula(
            world_id="world_accept_eula",
            actor_user_id="u_admin",
            accepted=True,
            idempotency_key="accept-world-eula",
        )
        assert replayed is False
        replay, replayed = container.worlds.accept_eula(
            world_id="world_accept_eula",
            actor_user_id="u_admin",
            accepted=True,
            idempotency_key="accept-world-eula",
        )
        assert replayed is True
        assert replay["op_id"] == operation["op_id"]

        assert "eula=true" in (world_dir / "eula.txt").read_text(encoding="utf-8")
        assert _state(container.store, "world_accept_eula") == WorldState.OFF.value
        audit = (
            container.store.reader()
            .execute(
                "SELECT actor_user_id, world_id, event_type FROM audit_records "
                "WHERE world_id = ? AND event_type = 'world_eula_accepted'",
                ("world_accept_eula",),
            )
            .fetchone()
        )
        assert audit["actor_user_id"] == "u_admin"
        assert audit["world_id"] == "world_accept_eula"
        assert (
            container.store.reader()
            .execute(
                "SELECT count(*) FROM audit_records "
                "WHERE world_id = ? AND event_type = 'world_eula_accepted'",
                ("world_accept_eula",),
            )
            .fetchone()[0]
            == 1
        )
        operation = (
            container.store.reader()
            .execute(
                "SELECT op_type, status, data_json FROM operations WHERE world_id = ?",
                ("world_accept_eula",),
            )
            .fetchone()
        )
        operation_data = json.loads(operation["data_json"])
        assert operation["op_type"] == OperationType.CONFIG_EDIT.value
        assert operation["status"] == OperationStatus.COMPLETED.value
        assert operation_data == {
            "entity": "eula",
            "row_id": "world_accept_eula",
            "before": {"accepted": False},
            "after": {"accepted": True},
        }
    finally:
        container.store.close()


def test_eula_accept_api_requires_step_up_and_records_operator(tmp_path):
    app = create_app(
        database_path=tmp_path / "eula-api.db",
        keyfile_path=tmp_path / "eula-api.key",
        migrations_dir=_MIGRATIONS,
    )
    container = app.extensions["mcmanager_container"]
    try:
        user_id = container.auth.provision_first_superadmin(
            username="eula-admin",
            password="eula-password",
            device_id="eula-device",
            device_name="EULA test",
            ip="127.0.0.1",
        )
        world_dir = _seed_world(
            container.store,
            "world_eula_api",
            _free_port(),
            tmp_path / "worlds",
            eula_arg="--eula=false",
        )
        container.store.writer().execute(
            "UPDATE world_instances SET state = ? WHERE world_id = ?",
            (WorldState.EULA_REQUIRED.value, "world_eula_api"),
        )
        container.store.writer().commit()
        client = app.test_client()
        session = container.auth.authenticate(
            username="eula-admin",
            password="eula-password",
            device_id="eula-device",
            device_name="EULA test",
            ip="127.0.0.1",
        )
        client.set_cookie("mcmanager_session", session.token)
        csrf = session_csrf_token(session.token)
        client.set_cookie("csrf_token", csrf)

        blocked = client.post(
            "/api/worlds/world_eula_api/eula/accept",
            json={"accepted": True},
            headers={"X-CSRF-Token": csrf},
        )
        assert blocked.status_code == 403
        assert blocked.get_json()["error"]["code"] == "STEP_UP_REQUIRED"
        assert "eula=false" in (world_dir / "eula.txt").read_text(encoding="utf-8")

        step_up = client.post(
            "/api/auth/step-up",
            json={"password": "eula-password", "device_id": "eula-device"},
            headers={"X-CSRF-Token": csrf},
        )
        assert step_up.status_code == 200
        csrf = client.get_cookie("csrf_token").value

        rejected = client.post(
            "/api/worlds/world_eula_api/eula/accept",
            json={"accepted": False},
            headers={"X-CSRF-Token": csrf},
        )
        assert rejected.status_code == 400

        accepted_headers = {
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "accept-world-eula-api",
        }
        accepted = client.post(
            "/api/worlds/world_eula_api/eula/accept",
            json={"accepted": True},
            headers=accepted_headers,
        )
        assert accepted.status_code == 200
        accepted_payload = accepted.get_json()
        replay = client.post(
            "/api/worlds/world_eula_api/eula/accept",
            json={"accepted": True},
            headers=accepted_headers,
        )
        assert replay.status_code == 200
        replay_payload = replay.get_json()
        assert replay_payload["meta"]["idempotency_key"] == "accept-world-eula-api"
        assert replay_payload["meta"]["op_id"] == accepted_payload["meta"]["op_id"]
        assert "eula=true" in (world_dir / "eula.txt").read_text(encoding="utf-8")
        audit = (
            container.store.reader()
            .execute(
                "SELECT actor_user_id, event_type FROM audit_records "
                "WHERE world_id = ? AND event_type = 'world_eula_accepted'",
                ("world_eula_api",),
            )
            .fetchone()
        )
        assert audit["actor_user_id"] == user_id
        assert (
            container.store.reader()
            .execute(
                "SELECT count(*) FROM audit_records "
                "WHERE world_id = ? AND event_type = 'world_eula_accepted'",
                ("world_eula_api",),
            )
            .fetchone()[0]
            == 1
        )
    finally:
        app.extensions["mcmanager_shutdown"]()


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
        (explicit_dir / "eula.txt").write_text("eula=true\n", encoding="utf-8")

        session_id = container.worlds.start(world_id="world_path")
        assert session_id.startswith("rs_")
        assert (explicit_dir / "server.properties").exists()
        assert not (tmp_path / "worlds" / "World world_path" / "server.properties").exists()

        container.worlds.stop(world_id="world_path")
    finally:
        container.store.close()


def test_queued_world_create_delete_and_replay(tmp_path):
    port = _free_port()
    container = build_container(
        database_path=tmp_path / "queued-create-delete.db",
        keyfile_path=tmp_path / "queued-create-delete.key",
        migrations_dir=_MIGRATIONS,
    )
    try:
        _seed_world(container.store, "world_template", port, tmp_path / "worlds")
        created_port = _free_port()
        now = int(container.clock.now())
        world_directory = tmp_path / "worlds" / "World world_created"
        world = {
            "world_id": "world_created",
            "display_name": "World created",
            "template_id": "tpl",
            "server_type": "vanilla",
            "mc_version": "1.21",
            "java_runtime_id": "java",
            "port": created_port,
            "addressing_strategy": "port",
            "addressing_value": str(created_port),
            "state": WorldState.EULA_REQUIRED.value,
            "pre_backup_state": None,
            "launch_args": None,
            "world_directory": str(world_directory),
            "metadata_version": 1,
            "deleted_at": None,
            "deleted_by": None,
            "created_at": now,
            "updated_at": now,
        }

        create, replayed = container.worlds.enqueue_world_mutation(
            op_type=OperationType.CREATE_WORLD,
            world_id=None,
            actor_user_id="u_admin",
            idempotency_key="create-world-queued",
            data={"world_action": "create", "world": world},
        )
        assert replayed is False
        assert create["op_id"] in container.worlds.dispatch_queued_world_mutations()

        created = (
            container.store.reader()
            .execute(
                "SELECT world_id, state, world_directory, deleted_at "
                "FROM world_instances WHERE world_id = ?",
                ("world_created",),
            )
            .fetchone()
        )
        assert created["state"] == WorldState.EULA_REQUIRED.value
        assert created["deleted_at"] is None
        assert Path(created["world_directory"]) == world_directory
        assert world_directory.is_dir()
        assert not (world_directory.parent / ".mcmanager-world_created.provisioning").exists()
        assert (
            container.operations.get(create["op_id"])["status"]
            == OperationStatus.COMPLETED.value
        )

        accepted, replayed = container.worlds.accept_eula(
            world_id="world_created",
            actor_user_id="u_admin",
            accepted=True,
            idempotency_key="accept-created-world-eula",
        )
        assert replayed is False
        assert accepted["status"] == OperationStatus.COMPLETED.value
        delete_preview = (
            container.store.reader()
            .execute(
                "SELECT state, metadata_version FROM world_instances WHERE world_id = ?",
                ("world_created",),
            )
            .fetchone()
        )
        assert delete_preview["state"] == WorldState.OFF.value

        delete, replayed = container.worlds.enqueue_world_mutation(
            op_type=OperationType.DELETE_WORLD,
            world_id="world_created",
            actor_user_id="u_admin",
            idempotency_key="delete-world-queued",
            data={
                "world_action": "delete",
                "preview_version": delete_preview["metadata_version"],
            },
        )
        assert replayed is False
        assert delete["op_id"] in container.worlds.dispatch_queued_world_mutations()
        deleted = (
            container.store.reader()
            .execute(
                "SELECT deleted_at, deleted_by, metadata_version "
                "FROM world_instances WHERE world_id = ?",
                ("world_created",),
            )
            .fetchone()
        )
        assert deleted["deleted_at"] is not None
        assert deleted["deleted_by"] == "u_admin"
        assert deleted["metadata_version"] == 2

        replay, replayed = container.worlds.enqueue_world_mutation(
            op_type=OperationType.DELETE_WORLD,
            world_id="world_created",
            actor_user_id="u_admin",
            idempotency_key="delete-world-queued-replay",
            data={
                "world_action": "delete",
                "preview_version": delete_preview["metadata_version"],
            },
        )
        assert replayed is False
        assert replay["op_id"] in container.worlds.dispatch_queued_world_mutations()
        assert (
            container.operations.get(replay["op_id"])["status"]
            == OperationStatus.COMPLETED.value
        )
    finally:
        container.store.close()


def test_queued_runtime_config_and_file_edit_branches(tmp_path):
    port = _free_port()
    container = build_container(
        database_path=tmp_path / "queued-config-edit.db",
        keyfile_path=tmp_path / "queued-config-edit.key",
        migrations_dir=_MIGRATIONS,
    )
    try:
        world_dir = _seed_world(
            container.store,
            "world_config_edit",
            port,
            tmp_path / "worlds",
        )

        runtime, replayed = container.worlds.enqueue_world_mutation(
            op_type=OperationType.CONFIG_EDIT,
            world_id="world_config_edit",
            actor_user_id="u_admin",
            idempotency_key="rename-world-config",
            data={
                "world_action": "runtime_config",
                "queued_runtime_config": True,
                "expected_version": 1,
                "before": {"display_name": "World world_config_edit"},
                "after": {"display_name": "Renamed world"},
            },
        )
        assert replayed is False
        assert runtime["op_id"] in container.worlds.dispatch_queued_world_mutations()
        renamed = container.worlds._world("world_config_edit")
        assert renamed["display_name"] == "Renamed world"
        assert renamed["metadata_version"] == 2

        replay, replayed = container.worlds.enqueue_world_mutation(
            op_type=OperationType.CONFIG_EDIT,
            world_id="world_config_edit",
            actor_user_id="u_admin",
            idempotency_key="rename-world-config-replay",
            data={
                "world_action": "runtime_config",
                "queued_runtime_config": True,
                "expected_version": 1,
                "before": {"display_name": "World world_config_edit"},
                "after": {"display_name": "Renamed world"},
            },
        )
        assert replayed is False
        assert replay["op_id"] in container.worlds.dispatch_queued_world_mutations()

        source = world_dir / "source.txt"
        source.write_text("copy me\n", encoding="utf-8")
        copy, replayed = container.worlds.enqueue_world_mutation(
            op_type=OperationType.CONFIG_EDIT,
            world_id="world_config_edit",
            actor_user_id="u_admin",
            idempotency_key="copy-world-file",
            data={
                "world_action": "file_edit",
                "queued_file_edit": True,
                "action": "copy",
                "from": "source.txt",
                "to": "copied.txt",
                "world_root": str(world_dir),
            },
        )
        assert replayed is False
        assert copy["op_id"] in container.worlds.dispatch_queued_world_mutations()
        assert (world_dir / "copied.txt").read_text(encoding="utf-8") == "copy me\n"

        same_copy, replayed = container.worlds.enqueue_world_mutation(
            op_type=OperationType.CONFIG_EDIT,
            world_id="world_config_edit",
            actor_user_id="u_admin",
            idempotency_key="copy-world-file-same",
            data={
                "world_action": "file_edit",
                "queued_file_edit": True,
                "action": "copy",
                "from": "source.txt",
                "to": "copied.txt",
                "world_root": str(world_dir),
            },
        )
        assert replayed is False
        assert same_copy["op_id"] in container.worlds.dispatch_queued_world_mutations()
        assert (
            container.operations.get(same_copy["op_id"])["status"]
            == OperationStatus.COMPLETED.value
        )

        move, replayed = container.worlds.enqueue_world_mutation(
            op_type=OperationType.CONFIG_EDIT,
            world_id="world_config_edit",
            actor_user_id="u_admin",
            idempotency_key="move-world-file",
            data={
                "world_action": "file_edit",
                "queued_file_edit": True,
                "action": "rename",
                "from": "source.txt",
                "to": "renamed.txt",
                "world_root": str(world_dir),
            },
        )
        assert replayed is False
        assert move["op_id"] in container.worlds.dispatch_queued_world_mutations()
        assert not source.exists()
        assert (world_dir / "renamed.txt").read_text(encoding="utf-8") == "copy me\n"

        absolute, replayed = container.worlds.enqueue_world_mutation(
            op_type=OperationType.CONFIG_EDIT,
            world_id="world_config_edit",
            actor_user_id="u_admin",
            idempotency_key="reject-absolute-world-file",
            data={
                "world_action": "file_edit",
                "queued_file_edit": True,
                "action": "copy",
                "from": str(tmp_path / "outside.txt"),
                "to": "copied.txt",
                "world_root": str(world_dir),
            },
        )
        assert replayed is False
        assert absolute["op_id"] in container.worlds.dispatch_queued_world_mutations()
        assert (
            container.operations.get(absolute["op_id"])["status"]
            == OperationStatus.FAILED.value
        )
        assert (
            container.operations.get(absolute["op_id"])["error_code"]
            == "OP_EXECUTION_FAILED"
        )
    finally:
        container.store.close()


@pytest.mark.parametrize(
    ("state", "expected_state"),
    [
        (WorldState.QUEUED, WorldState.OFF),
        (WorldState.RUNNING, WorldState.CRASHED),
        (WorldState.OFF, WorldState.OFF),
        (WorldState.CRASHED, WorldState.CRASHED),
    ],
)
def test_reconcile_fails_interrupted_start_for_persisted_states(
    tmp_path, state, expected_state
):
    container = build_container(
        database_path=tmp_path / f"interrupted-{state.value}.db",
        keyfile_path=tmp_path / f"interrupted-{state.value}.key",
        migrations_dir=_MIGRATIONS,
    )
    try:
        _seed_world(
            container.store,
            f"world_interrupted_{state.value}",
            _free_port(),
            tmp_path / "worlds",
        )
        world_id = f"world_interrupted_{state.value}"
        operation = container.operations.create(
            OperationInput(
                op_type=OperationType.START,
                actor_type=ActorType.SYSTEM,
                world_id=world_id,
            ),
            initial_status=OperationStatus.RUNNING,
        )
        container.store.writer().execute(
            "UPDATE world_instances SET state = ? WHERE world_id = ?",
            (state.value, world_id),
        )
        container.store.writer().commit()

        assert container.worlds.reconcile() == []
        assert _state(container.store, world_id) == expected_state.value
        assert (
            container.operations.get(operation["op_id"])["status"]
            == OperationStatus.FAILED.value
        )
        assert (
            container.operations.get(operation["op_id"])["error_code"]
            == "manager_restart_incomplete"
        )
    finally:
        container.store.close()
def test_queued_world_create_failure_cleans_owned_provisioning_artifacts(container, tmp_path):
    import sqlite3

    import pytest

    world_id = "w_provision_failure"
    world_directory = tmp_path / "worlds" / world_id
    provisioning_marker = world_directory.parent / f".mcmanager-{world_id}.provisioning"

    with pytest.raises(sqlite3.OperationalError, match="no column named"):
        container.worlds._apply_queued_world_create(
            {"op_id": "op_provision_failure"},
            {
                "world": {
                    "world_id": world_id,
                    "world_directory": str(world_directory),
                    "invalid_column": "force insert failure",
                }
            },
        )

    assert not world_directory.exists()
    assert not provisioning_marker.exists()


def test_queued_world_create_refuses_unowned_directories_and_markers(container, tmp_path):
    import pytest

    from app.services.worlds import WorldConflictError

    existing_directory = tmp_path / "existing" / "w_existing"
    existing_directory.mkdir(parents=True)
    with pytest.raises(WorldConflictError, match="directory already exists"):
        container.worlds._apply_queued_world_create(
            {"op_id": "op_existing_directory"},
            {
                "world": {
                    "world_id": "w_existing",
                    "world_directory": str(existing_directory),
                }
            },
        )
    existing_marker = existing_directory.parent / ".mcmanager-w_existing.provisioning"
    assert not existing_marker.exists()

    world_id = "w_other_provisioner"
    world_directory = tmp_path / "provisioning" / world_id
    world_directory.parent.mkdir()
    provisioning_marker = world_directory.parent / f".mcmanager-{world_id}.provisioning"
    provisioning_marker.write_text("another-world", encoding="utf-8")
    with pytest.raises(WorldConflictError, match="being provisioned"):
        container.worlds._apply_queued_world_create(
            {"op_id": "op_other_provisioner"},
            {
                "world": {
                    "world_id": world_id,
                    "world_directory": str(world_directory),
                }
            },
        )

    assert existing_directory.is_dir()
    assert not world_directory.exists()
    assert provisioning_marker.read_text(encoding="utf-8") == "another-world"
