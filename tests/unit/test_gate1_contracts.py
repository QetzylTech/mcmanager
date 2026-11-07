"""Focused Gate 1 adapter-boundary contracts."""

from __future__ import annotations

import ast
import inspect
import io
import os
import threading
from dataclasses import fields
from pathlib import Path

from app.domain.value_objects import Signal
from app.platform.process.base import BaseProcessAdapter
from app.platform.process.posix import PosixHandle
from app.platform.process.tailing import (
    DurableSessionLog,
    LogRingBuffer,
    LogStreamTailer,
    ProcessLineReader,
    ingest_log_line,
)
from app.platform.process.windows import WindowsHandle
from app.ports.process_control import ProcessHandle, SendResult
from app.services.save_coordination import RconSaveCoordinator, RuntimeSessionRcon
from app.services.worlds import WorldsService
from tests.adapters.fake_server.fake_adapter import FakeHandle

_HANDLE_FIELDS = {
    'world_id',
    'pid',
    'spawn_epoch',
    'process_group_id',
    'job_handle',
}


def test_process_handle_field_names_are_uniform():
    assert set(ProcessHandle.__annotations__) == _HANDLE_FIELDS
    for handle_type in (PosixHandle, WindowsHandle, FakeHandle):
        assert {field.name for field in fields(handle_type)} >= _HANDLE_FIELDS


def test_send_signal_rechecks_identity_immediately_before_delivery(monkeypatch):
    adapter = BaseProcessAdapter()
    handle = PosixHandle(
        world_id='identity-race',
        pid=os.getpid(),
        spawn_epoch=0.0,
    )
    checks = iter((True, False))
    delivered = []

    monkeypatch.setattr(adapter, 'identity_matches', lambda _handle: next(checks))
    monkeypatch.setattr(
        adapter,
        '_signal_tree_impl',
        lambda _process, _handle, _signal: delivered.append(True)
        or SendResult(delivered=True),
    )

    result = adapter.send_signal(handle, Signal.TERMINATE)

    assert not result.delivered
    assert delivered == []


def test_terminate_rechecks_identity_before_forced_termination(monkeypatch):
    adapter = BaseProcessAdapter()
    handle = PosixHandle(
        world_id='identity-race',
        pid=os.getpid(),
        spawn_epoch=0.0,
    )
    checks = iter((True, False))
    terminated = []

    monkeypatch.setattr(adapter, 'identity_matches', lambda _handle: next(checks))
    monkeypatch.setattr(
        adapter, '_kill_tree_impl', lambda _process, _handle: terminated.append(True)
    )

    result = adapter.terminate(handle, graceful_deadline_s=0)

    assert not result.resolved
    assert terminated == []


def test_worlds_service_uses_ports_and_bootstrap_injects_them(container):
    source = Path(inspect.getsourcefile(WorldsService)).read_text(encoding='utf-8')
    tree = ast.parse(source)
    infrastructure_imports = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith('app.infrastructure.minecraft')
    ]
    assert infrastructure_imports == []
    assert container.worlds._adapter is container.process_adapter
    assert container.worlds._minecraft is container.minecraft_adapter


def test_verbose_logging_filters_only_debug_and_persists_session_lines(
    tmp_path, monkeypatch
):
    log_path = tmp_path / 'session.log'
    buffer = LogRingBuffer()
    durable = DurableSessionLog(str(log_path))
    monkeypatch.setenv('VERBOSE_LOGGING', 'false')

    assert not ingest_log_line(buffer, 'stdout', '[DEBUG] hidden', durable_log=durable)
    assert not ingest_log_line(
        buffer, 'debug', 'verbose diagnostic detail', durable_log=durable
    )
    assert ingest_log_line(buffer, 'stderr', '[ERROR] retained', durable_log=durable)
    assert ingest_log_line(
        buffer, 'debug', '[ERROR] debug subsystem failed', durable_log=durable
    )

    assert buffer.channel('stdout').tail() == []
    assert [line for _, line in buffer.channel('debug').tail()] == [
        '[ERROR] debug subsystem failed'
    ]
    assert [line for _, line in buffer.channel('stderr').tail()] == ['[ERROR] retained']
    content = log_path.read_text(encoding='utf-8')
    assert '[DEBUG] hidden' not in content
    assert 'verbose diagnostic detail' not in content
    assert '[ERROR] retained' in content
    assert '[ERROR] debug subsystem failed' in content
    assert (tmp_path / 'session.stderr.log').read_text(encoding='utf-8') == (
        '[ERROR] retained\n'
    )
    assert (
        (tmp_path / 'session.debug.log').read_text(encoding='utf-8')
        == '[ERROR] debug subsystem failed\n'
    )

    monkeypatch.setenv('VERBOSE_LOGGING', 'true')
    assert ingest_log_line(buffer, 'stdout', '[DEBUG] visible', durable_log=durable)
    assert '[DEBUG] visible' in log_path.read_text(encoding='utf-8')
    assert '[DEBUG] visible' in (tmp_path / 'session.stdout.log').read_text(
        encoding='utf-8'
    )
    DurableSessionLog(str(log_path)).write('stderr', 'appended after restart')
    assert 'appended after restart' in log_path.read_text(encoding='utf-8')
    assert 'appended after restart' in (
        tmp_path / 'session.stderr.log'
    ).read_text(encoding='utf-8')


def test_graceful_stop_tries_rcon_before_stdin_fallback():
    calls: list[str] = []
    wait_results = iter((False, True))
    service = object.__new__(WorldsService)
    handle = object()

    class Adapter:
        def write_stdin(self, _handle, text):
            calls.append(f'stdin:{text}')
            return SendResult(delivered=True)

    service._adapter = Adapter()
    service._resolve_handle = lambda _world_id: handle
    service._rcon_command_quiet = lambda _world_id, command: calls.append(
        f'rcon:{command}'
    )
    service._wait_exit = lambda _handle, _timeout: calls.append('wait') or next(
        wait_results
    )

    assert service._attempt_graceful_stop('world-1')
    assert calls == ['rcon:stop', 'wait', 'stdin:stop', 'wait']


def test_nonverbose_tailing_filters_raw_noise_but_preserves_readiness_and_errors(
    tmp_path, monkeypatch
):
    monkeypatch.setenv('VERBOSE_LOGGING', 'false')
    log_path = tmp_path / 'session.log'
    buffer = LogRingBuffer()
    durable = DurableSessionLog(str(log_path))
    readiness_seen = threading.Event()
    error_seen = threading.Event()
    captured: list[str] = []

    def sink(**event: str) -> None:
        captured.append(event['line'])
        if 'Done (' in event['line']:
            readiness_seen.set()
        if '[ERROR]' in event['line']:
            error_seen.set()

    reader = ProcessLineReader(
        io.BytesIO(
            b'[FakeServer] tick 1\n'
            b'Done (1.234s)! For help, type "help"\n'
            b'[ERROR] world save failed\n'
        ),
        world_id='world-1',
        session_token='session-1',
        channel='stdout',
        buffer=buffer.channel('stdout'),
        sink=sink,
        durable_log=durable,
    )
    reader.start()

    assert readiness_seen.wait(2)
    assert error_seen.wait(2)
    assert captured == [
        'Done (1.234s)! For help, type "help"',
        '[ERROR] world save failed',
    ]
    assert [line for _, line in buffer.channel('stdout').tail()] == captured
    content = log_path.read_text(encoding='utf-8')
    assert '[FakeServer] tick 1' not in content
    assert 'Done (1.234s)! For help, type "help"' in content
    assert '[ERROR] world save failed' in content


def test_process_line_reader_bounds_utf8_lines_by_bytes(monkeypatch):
    monkeypatch.setenv('VERBOSE_LOGGING', 'true')
    line = '界' * 40
    buffer = LogRingBuffer().channel('stdout')
    reader = ProcessLineReader(
        io.BytesIO((line + '\n').encode('utf-8')),
        world_id='world-1',
        session_token='session-1',
        channel='stdout',
        buffer=buffer,
        sink=None,
        max_line_bytes=32,
    )
    reader.start()
    assert reader._thread is not None
    reader._thread.join(timeout=2)

    captured = buffer.tail()
    assert len(captured) == 1
    assert len(captured[0][1].encode('utf-8')) <= 32
    assert captured[0][1].endswith('...[line truncated]')


def test_log_stream_tailer_uses_same_nonverbose_filter_and_keeps_5000_lines(
    tmp_path, monkeypatch
):
    monkeypatch.setenv('VERBOSE_LOGGING', 'false')
    tailer = LogStreamTailer('world-1', 'session-1', str(tmp_path))

    assert not tailer.process_pipe_output('stdout', '[FakeServer] tick 1')
    assert tailer.process_pipe_output(
        'stdout', 'Done (1.234s)! For help, type "help"'
    )
    assert tailer.process_pipe_output('stderr', '[ERROR] retained')
    assert len(tailer.ring_buffer) == 2
    assert tailer.ring_buffer[-1]['line'] == '[ERROR] retained'
    assert tailer.log_file_path is not None
    content = Path(tailer.log_file_path).read_text(encoding='utf-8')
    assert '[FakeServer] tick 1' not in content
    assert 'Done (1.234s)! For help, type "help"' in content
    assert '[ERROR] retained' in content

    live_buffer = LogRingBuffer().channel('stdout')
    for line_number in range(5001):
        live_buffer.append(f'line {line_number}')
    lines = live_buffer.tail()
    assert len(lines) == 5000
    assert lines[0] == (1, 'line 1')
    assert lines[-1] == (5000, 'line 5000')


def test_rcon_save_coordinator_uses_injected_factory():
    calls: list[tuple[str, int, str]] = []

    class Client:
        def __init__(self, host: str, port: int, password: str) -> None:
            calls.append((host, port, password))

        def connect(self) -> None:
            pass

        def command(self, command: str) -> str:
            return ''

        def close(self) -> None:
            pass

    coordinator = RconSaveCoordinator(
        None,
        None,
        rcon_factory=lambda host, port, password: Client(host, port, password),
    )
    coordinator._session = lambda _world_id: RuntimeSessionRcon(
        session_id='s1', rcon_port=25575, rcon_secret_id='secret'
    )
    coordinator._secrets = type('Secrets', (), {'read': lambda self, _key: 'pw'})()

    coordinator.suspend_autosave('world-1')

    assert calls == [('127.0.0.1', 25575, 'pw')]
