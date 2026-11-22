"""Focused Gate 1 adapter-boundary contracts."""

from __future__ import annotations

import ast
import inspect
import io
import os
import threading
from dataclasses import fields
from pathlib import Path
from unittest.mock import Mock

import psutil
import pytest

from app.domain.value_objects import ExitClass, ProcessState, Signal
from app.platform.process import windows as windows_process
from app.platform.process.base import BaseProcessAdapter, LiveRegistry, RegistryEntry
from app.platform.process.posix import PosixHandle, PosixProcessAdapter
from app.platform.process.tailing import (
    DurableSessionLog,
    LogRingBuffer,
    LogStreamTailer,
    ProcessLineReader,
    ingest_log_line,
    read_durable_log,
)
from app.platform.process.windows import WindowsHandle, WindowsProcessAdapter
from app.ports.process_control import (
    ProbeFingerprint,
    ProcessHandle,
    SendResult,
    SpawnRequest,
)
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


def test_windows_fingerprint_reattaches_named_job(monkeypatch):
    class Process:
        def is_running(self):
            return True

    adapter = WindowsProcessAdapter()
    monkeypatch.setattr(windows_process, '_pid_matches', lambda _pid, _epoch: True)
    monkeypatch.setattr(windows_process.psutil, 'Process', lambda _pid: Process())
    monkeypatch.setattr(windows_process, '_open_job_object', lambda world_id: 731)

    result = adapter.probe(
        'world-reattach',
        '',
        fingerprint=ProbeFingerprint(pid=1234, spawn_epoch=1.0),
    )

    assert result.found
    assert isinstance(result.handle, WindowsHandle)
    assert result.handle.job_handle == 731
    assert adapter._job_handles['world-reattach'] == 731


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


def test_live_registry_register_snapshot_remove_and_clear():
    registry = LiveRegistry()
    handle = PosixHandle(
        world_id='world-1',
        pid=4321,
        spawn_epoch=123.5,
        process_group_id=4321,
    )
    entry = RegistryEntry(
        handle=handle,
        process=Mock(),
        args_snapshot=['java', '-Dworld=world-1'],
        spawn_epoch=123.5,
    )

    registry.register(entry)
    assert registry.get('world-1') is entry
    assert registry.snapshot_for_probe() == [('world-1', 4321, 123.5, 'java')]
    assert registry.all() == (entry,)

    registry.remove('world-1')
    assert registry.get('world-1') is None
    registry.register(entry)
    registry.clear()
    assert registry.all() == ()


@pytest.mark.parametrize(
    'argv',
    [None, 'java -jar server.jar', ('java', '-jar')],
)
def test_base_spawn_rejects_non_list_launch_commands(argv):
    adapter = BaseProcessAdapter()
    request = Mock(launch_command=argv)

    result = adapter.spawn(request)

    assert result.handle is None
    assert result.spawn_error == 'no_argv'


def test_base_spawn_reports_oserror_and_does_not_register(monkeypatch):
    adapter = BaseProcessAdapter()
    request = Mock(launch_command=['java', '-jar', 'server.jar'])
    monkeypatch.setattr(
        adapter,
        '_spawn_impl',
        Mock(side_effect=OSError('spawn denied')),
    )

    result = adapter.spawn(request)

    assert result.handle is None
    assert result.spawn_error == 'spawn denied'
    assert adapter._registry.all() == ()


def test_base_identity_and_exit_code_helpers_cover_psutil_boundaries(monkeypatch):
    adapter = BaseProcessAdapter()
    handle = PosixHandle(
        world_id='identity',
        pid=9876,
        spawn_epoch=100.0,
    )
    process = Mock(create_time=Mock(return_value=100.25))
    monkeypatch.setattr(psutil, 'Process', lambda _pid: process)

    assert adapter.identity_matches(handle)

    process.create_time.return_value = 102.0
    assert not adapter.identity_matches(handle)

    def denied(_pid):
        raise psutil.AccessDenied(pid=9876)

    monkeypatch.setattr(psutil, 'Process', denied)
    assert not adapter.identity_matches(handle)
    assert adapter._resolve_process(handle) is None


def test_base_registry_exit_code_handles_poll_and_invalid_popen(monkeypatch):
    registry = LiveRegistry()
    popen = Mock()
    popen.poll.return_value = 7
    process = Mock(returncode=None)
    handle = PosixHandle(world_id='world-code', pid=10, spawn_epoch=1.0)
    registry.register(
        RegistryEntry(
            handle=handle,
            process=process,
            args_snapshot=['java'],
            spawn_epoch=1.0,
            popen=popen,
        )
    )
    adapter = BaseProcessAdapter(registry)

    assert adapter._registry_exit_code('world-code') == 7
    assert adapter._safe_returncode('world-code', process) == 7

    popen.poll.side_effect = ValueError('closed')
    assert adapter._registry_exit_code('world-code') is None
    assert adapter._safe_returncode('world-code', process) is None


def test_base_write_stdin_success_and_closed_pipe(monkeypatch):
    registry = LiveRegistry()
    stream = io.BytesIO()
    popen = Mock(stdin=stream)
    process = Mock()
    handle = PosixHandle(world_id='world-stdin', pid=20, spawn_epoch=2.0)
    registry.register(
        RegistryEntry(
            handle=handle,
            process=process,
            args_snapshot=['java'],
            spawn_epoch=2.0,
            popen=popen,
        )
    )
    adapter = BaseProcessAdapter(registry)
    monkeypatch.setattr(adapter, '_resolve_process', lambda _handle: process)

    assert adapter.write_stdin(handle, 'stop').delivered
    assert stream.getvalue() == b'stop\n'

    stream.close()
    result = adapter.write_stdin(handle, 'stop')
    assert not result.delivered
    assert result.error


def test_base_poll_classifies_running_zombie_pid_reuse_and_missing(monkeypatch):
    registry = LiveRegistry()
    handle = PosixHandle(world_id='world-poll', pid=30, spawn_epoch=3.0)
    process = Mock()
    process.status.return_value = psutil.STATUS_RUNNING
    process.is_running.return_value = True
    popen = Mock()
    popen.poll.return_value = 0
    registry.register(
        RegistryEntry(
            handle=handle,
            process=process,
            args_snapshot=['java'],
            spawn_epoch=3.0,
            popen=popen,
        )
    )
    adapter = BaseProcessAdapter(registry)
    monkeypatch.setattr(psutil, 'Process', lambda _pid: process)
    monkeypatch.setattr(adapter, 'identity_matches', lambda _handle: True)

    assert adapter.poll(handle).state is ProcessState.RUNNING

    process.status.return_value = psutil.STATUS_ZOMBIE
    process.returncode = 0
    status = adapter.poll(handle)
    assert status.state is ProcessState.EXITED
    assert status.exit_code == 0
    assert status.exit_class is ExitClass.GRACEFUL

    monkeypatch.setattr(adapter, 'identity_matches', lambda _handle: False)
    status = adapter.poll(handle)
    assert status.state is ProcessState.MISSING
    assert status.exit_class is ExitClass.RECONCILED_MISSING

    monkeypatch.setattr(
        psutil,
        'Process',
        lambda _pid: (_ for _ in ()).throw(psutil.NoSuchProcess(30)),
    )
    status = adapter.poll(handle)
    assert status.state is ProcessState.EXITED
    assert status.exit_class is ExitClass.GRACEFUL


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


def test_base_terminate_resolves_graceful_exit_and_forced_settle(monkeypatch):
    registry = LiveRegistry()
    popen = Mock()
    popen.poll.return_value = 0
    process = Mock()
    process.status.return_value = psutil.STATUS_ZOMBIE
    handle = PosixHandle(world_id='world-stop', pid=40, spawn_epoch=4.0)
    registry.register(
        RegistryEntry(
            handle=handle,
            process=process,
            args_snapshot=['java'],
            spawn_epoch=4.0,
            popen=popen,
        )
    )
    adapter = BaseProcessAdapter(registry)
    monkeypatch.setattr(adapter, '_resolve_process', lambda _handle: process)
    monkeypatch.setattr(adapter, 'identity_matches', lambda _handle: True)
    monkeypatch.setattr(
        adapter,
        '_signal_tree_impl',
        lambda _process, _handle, _signal: SendResult(delivered=True),
    )

    result = adapter.terminate(handle, graceful_deadline_s=1)

    assert result.resolved
    assert result.exit_class is ExitClass.GRACEFUL
    assert result.exit_code == 0

    adapter = BaseProcessAdapter(registry)
    monkeypatch.setattr(adapter, '_resolve_process', lambda _handle: process)
    monkeypatch.setattr(adapter, 'identity_matches', lambda _handle: True)
    monkeypatch.setattr(adapter, '_kill_tree_impl', lambda _process, _handle: None)
    process.status.return_value = psutil.STATUS_RUNNING
    process.is_running.return_value = True
    process.returncode = None
    clock = iter((0.0, 11.0))
    monkeypatch.setattr('app.platform.process.base.time.time', lambda: next(clock))
    monkeypatch.setattr('app.platform.process.base.time.sleep', lambda _seconds: None)

    result = adapter.terminate(handle, graceful_deadline_s=0)

    assert not result.resolved
    assert result.error == 'kill_settle_timeout'


def test_posix_pid_matches_accepts_close_epoch_and_rejects_identity_errors(monkeypatch):
    process = Mock(create_time=Mock(return_value=50.25))
    monkeypatch.setattr(psutil, 'Process', lambda _pid: process)

    assert PosixHandle('world-1', 123, 50.0).identity_matches()

    process.create_time.return_value = 52.0
    assert not PosixHandle('world-1', 123, 50.0).identity_matches()

    monkeypatch.setattr(
        psutil,
        'Process',
        lambda _pid: (_ for _ in ()).throw(psutil.NoSuchProcess(123)),
    )
    assert not PosixHandle('world-1', 123, 50.0).identity_matches()


def test_posix_spawn_uses_direct_argv_and_stashes_popen(monkeypatch, tmp_path):
    from app.platform.process import posix as posix_process

    popen = Mock(
        pid=600,
        stdin=io.BytesIO(),
        stdout=io.BytesIO(),
        stderr=io.BytesIO(),
    )
    popen_command = Mock(return_value=popen)
    monkeypatch.setattr(
        'app.platform.process.posix.subprocess.Popen',
        popen_command,
    )
    monkeypatch.setattr(
        'app.platform.process.posix.psutil.Process',
        lambda _pid: Mock(create_time=lambda: 600.5),
    )
    monkeypatch.setattr(posix_process.os, 'getpgid', lambda _pid: 600, raising=False)
    adapter = PosixProcessAdapter()
    monkeypatch.setattr(adapter, '_start_readers', lambda _entry, _request: None)
    request = SpawnRequest(
        world_id='world-posix',
        launch_command=['java', '-jar', 'server.jar'],
        cwd=str(tmp_path),
        env={'JAVA_HOME': '/opt/java'},
    )

    result = adapter.spawn(request)

    assert result.handle is not None
    assert result.handle.process_group_id == 600
    assert adapter._registry.get('world-posix') is not None
    popen_command.assert_called_once()
    assert popen_command.call_args.args[0] == request.launch_command
    kwargs = popen_command.call_args.kwargs
    assert kwargs['cwd'] == str(tmp_path)
    assert kwargs['start_new_session'] is True
    assert kwargs['shell'] is False
    assert kwargs['stdin'] is not None
    assert kwargs['stdout'] is not None
    assert kwargs['stderr'] is not None


def test_posix_signal_and_kill_use_process_group(monkeypatch):
    from app.platform.process import posix as posix_process

    adapter = PosixProcessAdapter()
    process = Mock(pid=700)
    handle = PosixHandle(
        world_id='world-signal',
        pid=700,
        spawn_epoch=700.0,
        process_group_id=700,
    )
    calls = []
    monkeypatch.setattr(
        posix_process.os,
        'killpg',
        lambda pgid, sig: calls.append((pgid, sig)),
        raising=False,
    )
    monkeypatch.setattr(posix_process.signal, 'SIGKILL', 9, raising=False)

    assert adapter._signal_tree_impl(process, handle, Signal.TERMINATE).delivered
    adapter._kill_tree_impl(process, handle)
    assert calls == [
        (700, posix_process.signal.SIGTERM),
        (700, posix_process.signal.SIGKILL),
    ]

    result = adapter._signal_tree_impl(process, handle, Signal.KILL)
    assert not result.delivered
    assert result.error == 'use_terminate_for_kill'


def test_posix_fingerprint_probe_registers_marker_match_and_rejects_mismatch(
    monkeypatch,
):
    from app.platform.process import posix as posix_process

    adapter = PosixProcessAdapter()
    process = Mock()
    process.status.return_value = psutil.STATUS_RUNNING
    process.is_running.return_value = True
    process.cmdline.return_value = [
        '/usr/bin/java',
        '-Dworld_id=world-fingerprint',
    ]
    monkeypatch.setattr(psutil, 'Process', lambda _pid: process)
    monkeypatch.setattr(
        'app.platform.process.posix._pid_matches',
        lambda _pid, _epoch: True,
    )
    monkeypatch.setattr(posix_process.os, 'getpgid', lambda _pid: 800, raising=False)

    result = adapter.probe(
        'world-fingerprint',
        '',
        fingerprint=ProbeFingerprint(
            pid=800,
            spawn_epoch=800.5,
            launch_marker='world-fingerprint',
        ),
    )

    assert result.found
    assert result.handle is not None
    assert result.handle.process_group_id == 800
    assert adapter._registry.get('world-fingerprint') is not None

    process.cmdline.return_value = ['/usr/bin/java', 'other-world.jar']
    result = adapter.probe(
        'world-mismatch',
        '',
        fingerprint=ProbeFingerprint(
            pid=801,
            spawn_epoch=801.5,
            launch_marker='world-mismatch',
        ),
    )
    assert not result.found


def test_posix_tail_replay_and_close_are_repeat_safe():
    adapter = PosixProcessAdapter()
    handle = PosixHandle(world_id='world-tail', pid=900, spawn_epoch=900.0)
    entry = RegistryEntry(
        handle=handle,
        process=Mock(),
        args_snapshot=['java'],
        spawn_epoch=900.0,
    )
    entry.buffer.channel('stdout').append('ready')
    entry.buffer.channel('stdout').append('Done')
    adapter._registry.register(entry)
    replay = []

    tail = adapter.tail(
        handle,
        lambda *, world_id, session_token, channel, line: replay.append(
            (channel, line)
        ),
        since_offset=1,
    )

    assert replay == [('stdout', 'Done')]
    assert adapter.tail_replay(handle, 0) == [
        ('stdout', 0, 'ready'),
        ('stdout', 1, 'Done'),
    ]
    adapter.close_tail(tail)
    adapter.close_tail(tail)


def test_posix_spawn_rejects_non_argv_and_reports_oserror(monkeypatch, tmp_path):
    from app.platform.process import posix as posix_process

    adapter = PosixProcessAdapter()
    invalid_request = Mock(launch_command=('java', '-jar', 'server.jar'))

    invalid = adapter.spawn(invalid_request)

    assert invalid.handle is None
    assert invalid.spawn_error == 'no_argv'
    assert adapter._registry.all() == ()

    monkeypatch.setattr(
        posix_process.subprocess,
        'Popen',
        Mock(side_effect=OSError('executable not found')),
    )
    request = SpawnRequest(
        world_id='world-spawn-error',
        launch_command=['java', '-jar', 'server.jar'],
        cwd=str(tmp_path),
    )

    failed = adapter.spawn(request)

    assert failed.handle is None
    assert failed.spawn_error == 'executable not found'
    assert adapter._registry.all() == ()


def test_posix_reader_setup_skips_missing_pipes_and_recovered_processes(
    monkeypatch, tmp_path
):
    from app.platform.process import posix as posix_process

    adapter = PosixProcessAdapter()
    handle = PosixHandle('world-readers', 901, 901.0)
    stdout = io.BytesIO()
    popen = Mock(stdout=stdout, stderr=None)
    entry = RegistryEntry(
        handle=handle,
        process=Mock(),
        args_snapshot=['java'],
        spawn_epoch=901.0,
        popen=popen,
    )
    durable_log = object()
    reader = Mock()
    reader_factory = Mock(return_value=reader)
    log_factory = Mock(return_value=durable_log)
    monkeypatch.setattr(posix_process, 'ProcessLineReader', reader_factory)
    monkeypatch.setattr(posix_process, 'session_log_for', log_factory)
    request = SpawnRequest(
        world_id='world-readers',
        launch_command=['java'],
        cwd=str(tmp_path),
        stdout_channel='console-out',
        stderr_channel='console-err',
        session_id='session-readers',
        log_dir=str(tmp_path),
    )

    adapter._start_readers(entry, request)

    reader_factory.assert_called_once_with(
        stdout,
        world_id='world-readers',
        session_token='session-readers',
        channel='console-out',
        buffer=entry.buffer.channel('console-out'),
        sink=None,
        durable_log=durable_log,
    )
    reader.start.assert_called_once_with()
    assert entry.readers == [reader]

    recovered_entry = RegistryEntry(
        handle=PosixHandle('world-recovered', 902, 902.0),
        process=Mock(),
        args_snapshot=['java'],
        spawn_epoch=902.0,
    )
    adapter._start_readers(recovered_entry, request)
    log_factory.assert_called_once_with(str(tmp_path), 'session-readers')
    assert recovered_entry.readers == []


def test_posix_signal_falls_back_to_the_process_group_lookup(monkeypatch):
    from app.platform.process import posix as posix_process

    adapter = PosixProcessAdapter()
    process = Mock(pid=903)
    handle = PosixHandle('world-group-fallback', 903, 903.0)
    calls = []
    monkeypatch.setattr(
        posix_process.os,
        'getpgid',
        lambda pid: pid,
        raising=False,
    )
    monkeypatch.setattr(
        posix_process.os,
        'killpg',
        lambda pgid, sig: calls.append((pgid, sig)),
        raising=False,
    )
    monkeypatch.setattr(posix_process.signal, 'SIGKILL', 999, raising=False)

    assert adapter._signal_tree_impl(
        process, handle, Signal.TERMINATE
    ).delivered
    adapter._kill_tree_impl(process, handle)

    assert calls == [
        (903, posix_process.signal.SIGTERM),
        (903, posix_process.signal.SIGKILL),
    ]


def test_posix_probe_uses_registry_only_for_a_matching_live_process(monkeypatch):
    from app.platform.process import posix as posix_process

    adapter = PosixProcessAdapter()
    assert not adapter.probe('world-registry-probe', 'session').found
    handle = PosixHandle('world-registry-probe', 904, 904.0)
    entry = RegistryEntry(
        handle=handle,
        process=Mock(),
        args_snapshot=['java'],
        spawn_epoch=904.0,
    )
    adapter._registry.register(entry)
    process = Mock()
    process.status.return_value = psutil.STATUS_RUNNING
    process.is_running.return_value = True
    monkeypatch.setattr(PosixHandle, 'identity_matches', lambda _self: True)
    monkeypatch.setattr(posix_process.psutil, 'Process', lambda _pid: process)

    matched = adapter.probe('world-registry-probe', 'session')

    assert matched.found
    assert matched.matched_launch
    assert matched.handle is handle

    process.status.return_value = psutil.STATUS_ZOMBIE
    assert not adapter.probe('world-registry-probe', 'session').found

    process.status.return_value = psutil.STATUS_RUNNING
    process.is_running.return_value = False
    assert not adapter.probe('world-registry-probe', 'session').found

    process.is_running.return_value = True
    monkeypatch.setattr(
        posix_process.psutil,
        'Process',
        Mock(side_effect=psutil.NoSuchProcess(904)),
    )
    assert not adapter.probe('world-registry-probe', 'session').found

    monkeypatch.setattr(PosixHandle, 'identity_matches', lambda _self: False)
    assert not adapter.probe('world-registry-probe', 'session').found


def test_posix_fingerprint_probe_fails_closed_and_uses_pid_when_group_lookup_fails(
    monkeypatch,
):
    from app.platform.process import posix as posix_process

    adapter = PosixProcessAdapter()
    assert not adapter._probe_fingerprint('world-incomplete', ProbeFingerprint()).found
    assert not adapter._probe_fingerprint(
        'world-incomplete',
        ProbeFingerprint(pid=905),
    ).found

    process = Mock()
    process.status.return_value = psutil.STATUS_RUNNING
    process.is_running.return_value = True
    process.cmdline.side_effect = psutil.AccessDenied(pid=905)
    monkeypatch.setattr(posix_process.psutil, 'Process', lambda _pid: process)
    monkeypatch.setattr(
        posix_process,
        '_pid_matches',
        Mock(return_value=False),
    )
    marker = ProbeFingerprint(
        pid=905,
        spawn_epoch=905.0,
        launch_marker='world-marker',
    )

    assert not adapter._probe_fingerprint('world-marker', marker).found
    monkeypatch.setattr(
        posix_process,
        '_pid_matches',
        lambda _pid, _epoch: True,
    )
    process.status.return_value = psutil.STATUS_ZOMBIE
    assert not adapter._probe_fingerprint('world-marker', marker).found
    process.status.return_value = psutil.STATUS_RUNNING
    process.is_running.return_value = False
    assert not adapter._probe_fingerprint('world-marker', marker).found
    process.is_running.return_value = True

    assert not adapter._probe_fingerprint('world-marker', marker).found

    monkeypatch.setattr(
        posix_process.os,
        'getpgid',
        Mock(side_effect=PermissionError('process group unavailable')),
        raising=False,
    )
    process.cmdline.side_effect = None
    reattached = adapter._probe_fingerprint(
        'world-no-marker',
        ProbeFingerprint(pid=906, spawn_epoch=906.0),
    )

    assert reattached.found
    assert reattached.handle is not None
    assert reattached.handle.process_group_id == 906
    assert adapter._registry.get('world-no-marker') is not None


def test_posix_tail_reports_truncation_and_missing_registry():
    adapter = PosixProcessAdapter()
    handle = PosixHandle('world-truncated-tail', 907, 907.0)

    with pytest.raises(LookupError, match='no registry entry'):
        adapter.tail(handle, None)
    assert adapter.tail_replay(handle, 0) == []

    entry = RegistryEntry(
        handle=handle,
        process=Mock(),
        args_snapshot=['java'],
        spawn_epoch=907.0,
    )
    entry.buffer = LogRingBuffer(maxlen=1)
    entry.buffer.append('stdout', 'older line')
    entry.buffer.append('stdout', 'middle line')
    entry.buffer.append('stdout', 'retained line')
    adapter._registry.register(entry)
    replay = []
    live_line_received = threading.Event()

    def receive(**event):
        replay.append(event)
        if event['line'] == 'live line':
            live_line_received.set()

    tail = adapter.tail(
        handle,
        receive,
        since_offset=1,
    )

    assert [(item['channel'], item['line']) for item in replay] == [
        ('stdout', 'retained line'),
        ('__meta', 'buffer_trimmed'),
    ]
    entry.buffer.append('stdout', 'live line')
    assert live_line_received.wait(timeout=1)
    assert replay[-1]['line'] == 'live line'
    adapter.close_tail(tail)


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


def test_durable_log_reader_replays_by_utf8_byte_cursor(tmp_path):
    path = tmp_path / 'session.log'
    durable = DurableSessionLog(str(path))
    durable.write('stdout', 'ready')
    durable.write('stderr', 'world loaded: 界')

    records, offset = read_durable_log(path)
    assert [(channel, line) for _, _, channel, line in records] == [
        ('stdout', 'ready'),
        ('stderr', 'world loaded: 界'),
    ]
    first_record = path.read_bytes().splitlines(keepends=True)[0]
    assert records[0][1] == len(first_record)
    replayed, replay_offset = read_durable_log(path, records[0][1])
    assert replayed == [records[1]]
    assert replay_offset == offset

    with path.open('ab') as handle:
        handle.write(b'[stdout] partial')
    partial, partial_offset = read_durable_log(path, offset)
    assert partial == []
    assert partial_offset == offset


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
