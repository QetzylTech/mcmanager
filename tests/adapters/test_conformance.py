"""Document 13 section 6.3 conformance suite (C1–C14).

Every test runs against the in-process fake adapter AND the native platform
adapter (POSIX process groups / Windows job objects) — this is what makes
"portable process control" an executable check.
"""

from __future__ import annotations

import dataclasses
import sys
import time
from contextlib import suppress
from pathlib import Path

import psutil
import pytest

from app.domain.value_objects import ExitClass, ProcessState, Signal
from app.platform.process.base import LiveRegistry
from app.platform.process.posix import PosixProcessAdapter
from app.platform.process.windows import WindowsProcessAdapter
from app.ports.process_control import ProbeFingerprint
from tests.adapters.fake_server.fake_adapter import FakeProcessAdapter
from tests.adapters.fake_server.fake_server import _parse_args

SCRIPT_PATH = Path(__file__).resolve().parent / 'fake_server' / 'fake_server.py'


def _make_native() -> object:
    registry = LiveRegistry()
    if sys.platform.startswith('win'):
        return WindowsProcessAdapter(registry)
    return PosixProcessAdapter(registry)


def _make_adapter(kind: str) -> object:
    return _make_native() if kind == 'native' else FakeProcessAdapter()


def build_request(world_id: str, cwd: str, port: int, *args: str):
    from app.ports.process_control import SpawnRequest

    argv = [
        sys.executable,
        str(SCRIPT_PATH),
        f'--port={port}',
        f'--marker=world-{world_id}',
    ]
    argv.extend(args)
    return SpawnRequest(
        world_id=world_id,
        launch_command=argv,
        cwd=cwd,
        env={},
        session_id=world_id,
        log_dir=cwd,
    )


def free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def wait_for(predicate, timeout_s: float = 15.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def poll_until_exited(adapter, handle, timeout_s: float = 15.0) -> ExitClass:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = adapter.poll(handle)
        if not status.alive:
            return status.exit_class
        time.sleep(0.05)
    return ExitClass.RUNNING


def replay_lines(adapter, handle) -> list[tuple[str, int, str]]:
    return adapter.tail_replay(handle, 0)


def max_line_no(adapter, handle) -> int:
    lines = replay_lines(adapter, handle)
    return max(line_no for _channel, line_no, _line in lines) if lines else 0


def cleanup(adapter, handle) -> None:
    try:
        status = adapter.poll(handle)
        if status.alive:
            adapter.terminate(handle, graceful_deadline_s=3)
    finally:
        with suppress(Exception):
            adapter.close_handle(handle)


# --------------------------------------------------------------------------- C1


@pytest.mark.conformance
@pytest.mark.parametrize('kind', ['fake', 'native'])
def test_c1_spawn_probe_poll(kind, tmp_path):
    adapter = _make_adapter(kind)
    world_id = f'c1-{kind}'
    port = free_port()
    result = adapter.spawn(build_request(world_id, str(tmp_path), port))
    assert result.handle is not None, result.spawn_error
    handle = result.handle
    try:
        if kind == 'native':
            assert handle.process_group_id == handle.pid
        assert wait_for(lambda: adapter.probe(world_id, '').found, 10)
        probe = adapter.probe(
            world_id,
            '',
            fingerprint=ProbeFingerprint(
                pid=handle.pid, spawn_epoch=handle.spawn_epoch
            ),
        )
        assert probe.found and probe.matched_launch
        assert wait_for(lambda: adapter.poll(handle).alive, 10)
    finally:
        cleanup(adapter, handle)


# --------------------------------------------------------------------------- C2


@pytest.mark.conformance
@pytest.mark.parametrize('kind', ['fake', 'native'])
def test_c2_graceful_stdin_stop(kind, tmp_path):
    adapter = _make_adapter(kind)
    world_id = f'c2-{kind}'
    result = adapter.spawn(build_request(world_id, str(tmp_path), 0))
    assert result.handle is not None
    handle = result.handle
    try:
        assert wait_for(lambda: adapter.poll(handle).alive, 10)
        sent = adapter.write_stdin(handle, 'stop')
        assert sent.delivered, sent.error
        assert poll_until_exited(adapter, handle, 10) is ExitClass.GRACEFUL
    finally:
        cleanup(adapter, handle)


# --------------------------------------------------------------------------- C3


@pytest.mark.conformance
@pytest.mark.parametrize('kind', ['fake', 'native'])
def test_c3_forced_kill(kind, tmp_path):
    adapter = _make_adapter(kind)
    world_id = f'c3-{kind}'
    result = adapter.spawn(build_request(world_id, str(tmp_path), 0))
    assert result.handle is not None
    handle = result.handle
    try:
        assert wait_for(lambda: adapter.poll(handle).alive, 10)
        outcome = adapter.terminate(handle, graceful_deadline_s=0)
        assert outcome.resolved, outcome.error
        assert outcome.exit_class is ExitClass.FORCED
    finally:
        cleanup(adapter, handle)


# --------------------------------------------------------------------------- C4


@pytest.mark.conformance
@pytest.mark.parametrize('kind', ['fake', 'native'])
def test_c4_crash_detection(kind, tmp_path):
    adapter = _make_adapter(kind)
    world_id = f'c4-{kind}'
    result = adapter.spawn(
        build_request(world_id, str(tmp_path), 0, '--crash-after=0.2s')
    )
    assert result.handle is not None
    handle = result.handle
    try:
        assert poll_until_exited(adapter, handle, timeout_s=5.0) is ExitClass.CRASHED
        status = adapter.poll(handle)
        assert status.exit_code not in (0, 1)
    finally:
        cleanup(adapter, handle)


def test_fake_server_accepts_documented_and_millisecond_flags():
    documented = _parse_args(['--crash-after=2s', '--save-slow'])
    assert documented.crash_after_ms == 2000
    assert documented.save_slow_ms == 1000

    implementation_flags = _parse_args(
        ['--crash-after-ms=250', '--save-slow-ms=400']
    )
    assert implementation_flags.crash_after_ms == 250
    assert implementation_flags.save_slow_ms == 400


def test_fake_server_rejects_conflicting_duration_flags():
    with pytest.raises(SystemExit):
        _parse_args(['--crash-after=2s', '--crash-after-ms=2000'])
    with pytest.raises(SystemExit):
        _parse_args(['--save-slow', '--save-slow-ms=1000'])


def test_fake_adapter_documented_save_slow_mode(tmp_path):
    adapter = FakeProcessAdapter()
    result = adapter.spawn(
        build_request('save-slow', str(tmp_path), 0, '--save-slow')
    )
    assert result.handle is not None
    handle = result.handle
    started = time.monotonic()
    try:
        sent = adapter.write_stdin(handle, 'save-all')
        assert sent.delivered
        assert time.monotonic() - started >= 1.0
    finally:
        cleanup(adapter, handle)


# --------------------------------------------------------------------------- C5


@pytest.mark.conformance
@pytest.mark.parametrize('kind', ['fake', 'native'])
def test_c5_tail_and_replay(kind, tmp_path, monkeypatch):
    monkeypatch.setenv('VERBOSE_LOGGING', 'true')
    adapter = _make_adapter(kind)
    world_id = f'c5-{kind}'
    result = adapter.spawn(
        build_request(world_id, str(tmp_path), 0, '--tick-ms=1')
    )
    assert result.handle is not None
    handle = result.handle
    try:
        assert wait_for(lambda: max_line_no(adapter, handle) >= 3, 10)
        assert wait_for(
            lambda: any('world-c5' in line for _c, _n, line in replay_lines(adapter, handle)),
            10,
        )

        captured: list[str] = []

        def sink(*, world_id: str, session_token: str, channel: str, line: str) -> None:
            captured.append(line)

        tail = adapter.tail(handle, sink)
        try:
            assert wait_for(lambda: len(captured) >= 5, 10)
        finally:
            adapter.close_tail(tail)

        replayed: list[str] = []

        def sink2(*, world_id: str, session_token: str, channel: str, line: str) -> None:
            replayed.append(line)

        tail2 = adapter.tail(handle, sink2)
        adapter.close_tail(tail2)
        assert len(replayed) >= len(captured)
    finally:
        cleanup(adapter, handle)


# --------------------------------------------------------------------------- C6


@pytest.mark.conformance
@pytest.mark.parametrize('kind', ['fake', 'native'])
def test_c6_orphan_containment(kind, tmp_path):
    adapter = _make_adapter(kind)
    world_id = f'c6-{kind}'
    if kind == 'native':
        result = adapter.spawn(
            build_request(world_id, str(tmp_path), 0, '--spawn-grandchild')
        )
        assert result.handle is not None
        handle = result.handle
        try:
            assert wait_for(lambda: adapter.poll(handle).alive, 10)
            assert wait_for(lambda: _grandchildren(handle.pid), 10)
            descendant_pids = _grandchildren(handle.pid)
            outcome = adapter.terminate(handle, graceful_deadline_s=0)
            assert outcome.resolved and outcome.exit_class is ExitClass.FORCED
            assert wait_for(
                lambda: not any(_pid_is_running(pid) for pid in descendant_pids), 10
            )
        finally:
            cleanup(adapter, handle)
    else:
        # Fake adapter: no real grandchildren, but the forced kill must still
        # resolve and leave the virtual process terminated.
        result = adapter.spawn(build_request(world_id, str(tmp_path), 0))
        assert result.handle is not None
        handle = result.handle
        try:
            outcome = adapter.terminate(handle, graceful_deadline_s=0)
            assert outcome.resolved and outcome.exit_class is ExitClass.FORCED
            assert not adapter.poll(handle).alive
        finally:
            cleanup(adapter, handle)


def _grandchildren(pid: int) -> list[int]:
    try:
        parent = psutil.Process(pid)
        return [child.pid for child in parent.children(recursive=True)]
    except psutil.NoSuchProcess:
        return []


def _pid_is_running(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


# --------------------------------------------------------------------------- C7


@pytest.mark.conformance
@pytest.mark.parametrize('kind', ['fake', 'native'])
def test_c7_pid_reuse_guard(kind, tmp_path):
    adapter = _make_adapter(kind)
    world_id = f'c7-{kind}'
    result = adapter.spawn(build_request(world_id, str(tmp_path), 0))
    assert result.handle is not None
    handle = result.handle
    try:
        forged = dataclasses.replace(handle, spawn_epoch=handle.spawn_epoch - 99999.0)

        status = adapter.poll(forged)
        assert status.state is ProcessState.MISSING
        assert status.exit_class is ExitClass.RECONCILED_MISSING

        sent = adapter.write_stdin(forged, 'stop')
        assert not sent.delivered

        outcome = adapter.terminate(forged, graceful_deadline_s=2)
        assert not outcome.resolved

        near_collision = dataclasses.replace(
            handle, spawn_epoch=handle.spawn_epoch - 5.0
        )
        assert adapter.poll(near_collision).state is ProcessState.MISSING
        sent = adapter.send_signal(near_collision, Signal.TERMINATE)
        assert not sent.delivered
        assert not adapter.terminate(
            near_collision, graceful_deadline_s=0
        ).resolved

        # The innocent process (the real handle) must be unharmed.
        assert adapter.poll(handle).alive
    finally:
        cleanup(adapter, handle)


# --------------------------------------------------------------------------- C8


@pytest.mark.conformance
@pytest.mark.parametrize('kind', ['fake', 'native'])
def test_c8_readiness_via_socket(kind, tmp_path):
    from app.infrastructure.minecraft.readiness import port_is_bound

    adapter = _make_adapter(kind)
    world_id = f'c8-{kind}'
    port = free_port()
    result = adapter.spawn(build_request(world_id, str(tmp_path), port))
    assert result.handle is not None
    handle = result.handle
    try:
        assert wait_for(lambda: port_is_bound('127.0.0.1', port, 0.5), 15)
    finally:
        cleanup(adapter, handle)


# --------------------------------------------------------------------------- C9


@pytest.mark.conformance
@pytest.mark.parametrize('kind', ['fake', 'native'])
def test_c9_start_timeout(kind, tmp_path):
    adapter = _make_adapter(kind)
    world_id = f'c9-{kind}'
    result = adapter.spawn(
        build_request(world_id, str(tmp_path), 0, '--never-ready')
    )
    assert result.handle is not None
    handle = result.handle
    try:
        assert wait_for(lambda: adapter.poll(handle).alive, 10)
        # Supervisor-level timeout is enforced by the service layer against a
        # locked 120s value (Doc 8); the adapter's contract here is that a
        # never-ready process stays supervised and alive — no false ready.
        assert adapter.poll(handle).alive
    finally:
        cleanup(adapter, handle)


# --------------------------------------------------------------------------- C10


@pytest.mark.conformance
@pytest.mark.parametrize('kind', ['fake', 'native'])
def test_c10_stop_timeout_escalation(kind, tmp_path):
    adapter = _make_adapter(kind)
    world_id = f'c10-{kind}'
    result = adapter.spawn(
        build_request(world_id, str(tmp_path), 0, '--ignore-graceful')
    )
    assert result.handle is not None
    handle = result.handle
    try:
        assert wait_for(lambda: adapter.poll(handle).alive, 10)
        outcome = adapter.terminate(handle, graceful_deadline_s=2)
        assert outcome.resolved, outcome.error
        assert outcome.exit_class is ExitClass.FORCED
        assert not adapter.poll(handle).alive
    finally:
        cleanup(adapter, handle)


# --------------------------------------------------------------------------- C11


@pytest.mark.conformance
@pytest.mark.parametrize('kind', ['fake', 'native'])
def test_c11_boot_reconciliation(kind, tmp_path):
    from app.infrastructure.minecraft.rcon import RconClient

    adapter = _make_adapter(kind)
    world_id = f'c11-{kind}'
    port = free_port()
    rcon_port = free_port()
    extra_args = ('--spawn-grandchild',) if kind == 'native' else ()
    result = adapter.spawn(
        build_request(
            world_id,
            str(tmp_path),
            port,
            *extra_args,
            f'--rcon-port={rcon_port}',
        )
    )
    assert result.handle is not None
    handle = result.handle
    try:
        assert wait_for(lambda: adapter.poll(handle).alive, 10)
        fingerprint = ProbeFingerprint(
            pid=handle.pid,
            spawn_epoch=handle.spawn_epoch,
            launch_marker=f'world-{world_id}',
        )

        # Manager death: a fresh adapter instance with an empty registry.
        boot_adapter = _make_adapter(kind)
        probe = boot_adapter.probe(world_id, '', fingerprint=fingerprint)
        assert probe.found, 'boot reconciliation failed to re-attach a live world'
        assert probe.matched_launch
        assert boot_adapter.poll(probe.handle).alive

        if kind == 'native' and sys.platform.startswith('win'):
            descendant_pids = _grandchildren(handle.pid)
            assert descendant_pids, 'fake server did not create its child process'
            adapter.close_handle(handle)
            outcome = boot_adapter.terminate(probe.handle, graceful_deadline_s=0)
            assert outcome.resolved, outcome.error
            assert wait_for(
                lambda: not any(_pid_is_running(pid) for pid in descendant_pids), 10
            )
            return

        # The stdin pipe cannot be rebuilt after re-attachment (Doc 13
        # section 5.1) — RCON is the documented control channel instead.
        sent = boot_adapter.write_stdin(probe.handle, 'stop')
        if sent.delivered:
            # Fake adapter simulates stdin on the shared virtual process.
            assert (
                poll_until_exited(boot_adapter, probe.handle, 10)
                is ExitClass.GRACEFUL
            )
            assert not adapter.poll(handle).alive
            return

        assert sent.error == 'stdin_unavailable', sent.error

        rcon = RconClient('127.0.0.1', rcon_port, 'test-pass')
        try:
            rcon.connect()
            assert rcon.ping(), 'RCON ready probe failed after re-attach'
            rcon.command('stop')
        finally:
            rcon.close()

        # After re-attach there is no Popen handle, so the adapter cannot
        # know the exit code; graceful-vs-crash classification is overlaid by
        # the service layer (Doc 13 section 4.1). The adapter contract here
        # is that the re-attached world exited.
        assert poll_until_exited(boot_adapter, probe.handle, 10) is not ExitClass.RUNNING
        assert not adapter.poll(handle).alive
    finally:
        cleanup(adapter, handle)


# --------------------------------------------------------------------------- C12


@pytest.mark.conformance
@pytest.mark.parametrize('kind', ['fake', 'native'])
def test_c12_log_durability(kind, tmp_path, monkeypatch):
    monkeypatch.setenv('VERBOSE_LOGGING', 'true')
    adapter = _make_adapter(kind)
    world_id = f'c12-{kind}'
    session_log = tmp_path / f'{world_id}.log'
    result = adapter.spawn(
        build_request(world_id, str(tmp_path), 0, '--marker=durable-line')
    )
    assert result.handle is not None
    handle = result.handle

    captured: list[str] = []

    def sink(*, world_id: str, session_token: str, channel: str, line: str) -> None:
        captured.append(line)

    tail = adapter.tail(handle, sink)
    try:
        assert wait_for(lambda: any('durable-line' in line for line in captured), 10)
    finally:
        adapter.close_tail(tail)

    cleanup(adapter, handle)
    content = session_log.read_text(encoding='utf-8')
    assert 'durable-line' in content
    assert len(content.splitlines()) >= 2
    channel_log = tmp_path / f'{world_id}.stdout.log'
    assert 'durable-line' in channel_log.read_text(encoding='utf-8')


# --------------------------------------------------------------------------- C13


@pytest.mark.conformance
@pytest.mark.parametrize('kind', ['fake', 'native'])
def test_c13_slow_sink_backpressure(kind, tmp_path, monkeypatch):
    monkeypatch.setenv('VERBOSE_LOGGING', 'true')
    adapter = _make_adapter(kind)
    world_id = f'c13-{kind}'
    result = adapter.spawn(
        build_request(world_id, str(tmp_path), 0, '--tick-ms=1')
    )
    assert result.handle is not None
    handle = result.handle

    def slow_sink(*, world_id: str, session_token: str, channel: str, line: str) -> None:
        time.sleep(0.05)  # slow consumer — must never block the process reader
        return None

    tail = adapter.tail(handle, slow_sink)
    try:
        assert wait_for(lambda: max_line_no(adapter, handle) >= 20, 10)
        first_max = max_line_no(adapter, handle)
        assert wait_for(
            lambda: max_line_no(adapter, handle) > first_max + 20,
            10,
            interval=0.02,
        )
    finally:
        adapter.close_tail(tail)
        cleanup(adapter, handle)


# --------------------------------------------------------------------------- C14


def test_c14_no_systemd_in_control_plane() -> None:
    """Static structural test: no systemd/journalctl/systemctl/sc/service
    tokens anywhere in the app control-plane import graph (Doc 13 C14)."""
    root = Path(__file__).resolve().parents[2] / 'app'
    forbidden = (
        'systemd',
        'journalctl',
        'systemctl',
        'Start-Service',
        'Stop-Service',
        'Get-Service',
        'service(',
        'sc.exe',
    )

    offenders: list[str] = []
    for path in sorted(root.rglob('*.py')):
        if 'prototype' in str(path).lower():
            continue
        relative = path.relative_to(root)
        text = path.read_text(encoding='utf-8', errors='replace')
        for token in forbidden:
            if token in text:
                offenders.append(f'{relative}: {token}')

    assert not offenders, 'control-plane must not reference system services:\n' + '\n'.join(
        offenders
    )

    # No shell=True anywhere in the process-control package (injection guard).
    process_dir = root / 'platform' / 'process'
    for path in sorted(process_dir.rglob('*.py')):
        if 'shell=True' in path.read_text(encoding='utf-8'):
            raise AssertionError(f'shell=True forbidden in {path}')
