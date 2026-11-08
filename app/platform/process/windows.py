"""Windows process-control adapter (Document 13 section 3.2).

- Spawn via ``CREATE_NEW_PROCESS_GROUP`` plus an OS Job Object; the job is
  the supervision unit bounding the tree for termination and orphan
  containment (C6).
- ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` is deliberately NOT set (ARCHITECTURE
  ruling 10): worlds survive manager death and are re-attached at boot.
- Termination ladder: TERMINATE = ``CTRL_BREAK_EVENT`` to the process group
  (``GenerateConsoleCtrlEvent``), then KILL = ``TerminateJobObject`` to
  guarantee the whole job tree dies.
- PID-reuse guard via psutil creation-time comparison vs the spawn snapshot.
- Boot reconciliation (C11): ``probe()`` re-attaches to a live process
  matching a launch fingerprint — never trusting stale metadata alone.

No shell-string execution anywhere. No Windows service-manager integration.
Importing this module on a non-Windows host is safe: all kernel32 wiring is
lazy.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
import sys
import time
from contextlib import suppress
from ctypes import wintypes
from dataclasses import dataclass

import psutil

from app.domain.value_objects import Signal
from app.platform.process.base import BaseProcessAdapter, LiveRegistry, RegistryEntry
from app.platform.process.tailing import ProcessLineReader, session_log_for
from app.ports.process_control import (
    ProbeFingerprint,
    ProbeResult,
    ProcessHandle,
    SendResult,
    SpawnRequest,
    SpawnResult,
    TailHandle,
)

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
JobObjectExtendedLimitInformation = 9
JOB_OBJECT_ALL_ACCESS = 0x001F001F
ERROR_ALREADY_EXISTS = 183

_IDENTITY_TOLERANCE_S = 1.0


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('PerProcessUserTimeLimit', wintypes.LARGE_INTEGER),
        ('PerJobUserTimeLimit', wintypes.LARGE_INTEGER),
        ('LimitFlags', wintypes.DWORD),
        ('MinimumWorkingSetSize', ctypes.c_size_t),
        ('MaximumWorkingSetSize', ctypes.c_size_t),
        ('ActiveProcessLimit', wintypes.DWORD),
        ('Affinity', ctypes.c_size_t),
        ('PriorityClass', wintypes.DWORD),
        ('SchedulingClass', wintypes.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ('ReadOperationCount', ctypes.c_ulonglong),
        ('WriteOperationCount', ctypes.c_ulonglong),
        ('OtherOperationCount', ctypes.c_ulonglong),
        ('ReadTransferCount', ctypes.c_ulonglong),
        ('WriteTransferCount', ctypes.c_ulonglong),
        ('OtherTransferCount', ctypes.c_ulonglong),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ('IoInfo', IO_COUNTERS),
        ('ProcessMemoryLimit', ctypes.c_size_t),
        ('JobMemoryLimit', ctypes.c_size_t),
        ('PeakProcessMemoryUsed', ctypes.c_size_t),
        ('PeakJobMemoryUsed', ctypes.c_size_t),
    ]


_kernel32: dict[str, object] | None = None


def _load_kernel32() -> dict[str, object] | None:
    """Wire kernel32 entry points once. Returns None off-Windows."""
    global _kernel32
    if _kernel32 is not None:
        return _kernel32
    if not sys.platform.startswith('win'):
        _kernel32 = {}
        return _kernel32
    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    except (OSError, AttributeError):
        _kernel32 = {}
        return _kernel32

    def _setup(name: str, argtypes: list[object], restype: object) -> None:
        func = getattr(kernel32, name)
        func.argtypes = argtypes  # type: ignore[attr-defined]
        func.restype = restype  # type: ignore[attr-defined]

    _setup('CreateJobObjectW', [wintypes.LPVOID, wintypes.LPCWSTR], wintypes.HANDLE)
    _setup(
        'OpenJobObjectW',
        [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR],
        wintypes.HANDLE,
    )
    _setup(
        'SetInformationJobObject',
        [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD],
        wintypes.BOOL,
    )
    _setup('AssignProcessToJobObject', [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL)
    _setup('TerminateJobObject', [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL)
    _setup('GenerateConsoleCtrlEvent', [wintypes.DWORD, wintypes.DWORD], wintypes.BOOL)
    _setup('TerminateProcess', [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL)
    _setup('CloseHandle', [wintypes.HANDLE], wintypes.BOOL)

    _kernel32 = {
        'create_job': kernel32.CreateJobObjectW,
        'open_job': kernel32.OpenJobObjectW,
        'set_info': kernel32.SetInformationJobObject,
        'assign': kernel32.AssignProcessToJobObject,
        'terminate_job': kernel32.TerminateJobObject,
        'ctrl_break': kernel32.GenerateConsoleCtrlEvent,
        'terminate_process': kernel32.TerminateProcess,
        'close_handle': kernel32.CloseHandle,
    }
    return _kernel32


def _job_object_name(world_id: str) -> str:
    world_hash = hashlib.sha256(world_id.encode('utf-8')).hexdigest()
    return f'Local\\McManager-{world_hash}'


def _create_job_object(world_id: str) -> int:
    """Create a named job without KILL_ON_JOB_CLOSE (ruling 10)."""
    api = _load_kernel32()
    if not api:
        raise OSError('kernel32 unavailable (non-Windows host)')
    ctypes.set_last_error(0)
    job = api['create_job'](None, _job_object_name(world_id))  # type: ignore[operator]
    if not job:
        raise OSError(ctypes.get_last_error() or 1, 'CreateJobObject failed')
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        api['close_handle'](job)  # type: ignore[operator]
        raise OSError(ERROR_ALREADY_EXISTS, 'Job Object already exists for world')

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = 0
    ok = api['set_info'](  # type: ignore[operator]
        job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
    )
    if not ok:
        api['close_handle'](job)  # type: ignore[operator]
        raise OSError(ctypes.get_last_error() or 1, 'SetInformationJobObject failed')
    return int(job)


def _open_job_object(world_id: str) -> int | None:
    api = _load_kernel32()
    if not api:
        return None
    job = api['open_job'](JOB_OBJECT_ALL_ACCESS, False, _job_object_name(world_id))  # type: ignore[operator]
    return int(job) if job else None


def _assign_process_to_job(job_handle: int, process_handle: int) -> None:
    api = _load_kernel32()
    if not api:
        raise OSError('kernel32 unavailable (non-Windows host)')
    if not api['assign'](job_handle, process_handle):  # type: ignore[operator]
        raise OSError(ctypes.get_last_error() or 1, 'AssignProcessToJobObject failed')


def _pid_matches(pid: int, spawn_epoch: float) -> bool:
    try:
        process = psutil.Process(pid)
        return abs(process.create_time() - spawn_epoch) < _IDENTITY_TOLERANCE_S
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return False


@dataclass(frozen=True)
class WindowsHandle:
    """Opaque Windows process-tree handle (gate1 Module 1 fields)."""

    world_id: str
    pid: int
    spawn_epoch: float
    process_group_id: int | None = None
    job_handle: object | None = None

    def identity_matches(self) -> bool:
        return _pid_matches(self.pid, self.spawn_epoch)


class WindowsProcessAdapter(BaseProcessAdapter):
    """Doc 13 section 3.2 Windows implementation."""

    def __init__(self, registry: LiveRegistry | None = None) -> None:
        super().__init__(registry)
        self._job_handles: dict[str, int] = {}

    # -- spawn ---------------------------------------------------------------

    def spawn(self, request: SpawnRequest) -> SpawnResult:
        """Spawn via CREATE_NEW_PROCESS_GROUP + Job Object."""
        argv = request.launch_command
        if not isinstance(argv, list):
            return SpawnResult(handle=None, started_at=time.time(), spawn_error='no_argv')
        try:
            job_handle = _create_job_object(request.world_id)
        except OSError as exc:
            return SpawnResult(handle=None, started_at=time.time(), spawn_error=str(exc))
        try:
            popen = subprocess.Popen(
                request.launch_command,
                cwd=request.cwd,
                env={**os.environ, **request.env},
                creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
            _assign_process_to_job(job_handle, popen._handle)
        except (OSError, AttributeError) as exc:
            self._close_job(job_handle)
            return SpawnResult(handle=None, started_at=time.time(), spawn_error=str(exc))

        process = psutil.Process(popen.pid)
        handle = WindowsHandle(
            world_id=request.world_id,
            pid=popen.pid,
            spawn_epoch=process.create_time(),
            process_group_id=popen.pid,
            job_handle=job_handle,
        )
        entry = RegistryEntry(
            handle=handle,
            process=process,
            args_snapshot=list(argv),
            spawn_epoch=handle.spawn_epoch,
            popen=popen,
        )
        self._registry.register(entry)
        self._job_handles[request.world_id] = job_handle
        self._start_readers(entry, request)
        return SpawnResult(handle=handle, started_at=entry.spawn_epoch)

    def _close_job(self, job_handle: int) -> None:
        api = _load_kernel32()
        if not api:
            return
        with suppress(ctypes.ArgumentError, OSError):
            api['close_handle'](job_handle)  # type: ignore[operator]

    def _start_readers(self, entry: RegistryEntry, request: SpawnRequest) -> None:
        popen = entry.popen
        if popen is None:
            return
        durable = session_log_for(request.log_dir, request.session_id or request.world_id)
        for channel, stream in (
            (request.stdout_channel, popen.stdout),
            (request.stderr_channel, popen.stderr),
        ):
            if stream is None:
                continue
            buffer = entry.buffer.channel(channel)
            reader = ProcessLineReader(
                stream,
                world_id=entry.handle.world_id,
                session_token=request.session_id,
                channel=channel,
                buffer=buffer,
                sink=None,
                durable_log=durable,
            )
            reader.start()
            entry.readers.append(reader)

    # -- signals -------------------------------------------------------------

    def _signal_tree_impl(
        self, process: psutil.Process, handle: ProcessHandle, signal: Signal
    ) -> SendResult:
        if signal is Signal.KILL:
            return SendResult(delivered=False, error='use_terminate_for_kill')
        api = _load_kernel32()
        if not api:
            return SendResult(delivered=False, error='kernel32_unavailable')
        group_id = handle.process_group_id or process.pid
        ok = api['ctrl_break'](1, group_id)  # type: ignore[operator]
        if ok:
            return SendResult(delivered=True)
        return SendResult(delivered=False, error='ctrl_break_failed')

    def _kill_tree_impl(self, process: psutil.Process, handle: ProcessHandle) -> None:
        if isinstance(handle, WindowsHandle) and handle.job_handle:
            self._terminate_job(handle.job_handle)
            return
        # A re-attached process has no rebuildable Job Object handle.
        process.kill()

    def _terminate_job(self, job_handle: int) -> None:
        api = _load_kernel32()
        if api and job_handle:
            try:
                api['terminate_job'](job_handle, 1)  # type: ignore[operator]
            finally:
                self._close_job(job_handle)

    # -- probe / boot reconciliation (C11) -------------------------------------

    def probe(
        self,
        world_id: str,
        session_token: str,
        *,
        fingerprint: ProbeFingerprint | None = None,
    ) -> ProbeResult:
        if fingerprint is not None:
            result = self._probe_fingerprint(world_id, fingerprint)
            if result.found:
                return result

        entry = self._registry.get(world_id)
        if entry is None:
            return ProbeResult(found=False)
        handle = entry.handle
        if not handle.identity_matches():
            return ProbeResult(found=False)
        try:
            process = psutil.Process(handle.pid)
            if process.is_running():
                return ProbeResult(found=True, handle=handle, matched_launch=True)
        except psutil.NoSuchProcess:
            return ProbeResult(found=False)
        return ProbeResult(found=False)

    def _probe_fingerprint(
        self, world_id: str, fingerprint: ProbeFingerprint
    ) -> ProbeResult:
        if fingerprint.pid is None or fingerprint.spawn_epoch is None:
            return ProbeResult(found=False)
        if not _pid_matches(fingerprint.pid, fingerprint.spawn_epoch):
            return ProbeResult(found=False)
        try:
            process = psutil.Process(fingerprint.pid)
            if not process.is_running():
                return ProbeResult(found=False)
        except psutil.NoSuchProcess:
            return ProbeResult(found=False)
        if fingerprint.launch_marker:
            try:
                argv = process.cmdline()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                argv = []
            if not any(fingerprint.launch_marker in arg for arg in argv):
                return ProbeResult(found=False)
        job_handle = _open_job_object(world_id)
        if job_handle is None:
            return ProbeResult(found=False)
        handle = WindowsHandle(
            world_id=world_id,
            pid=fingerprint.pid,
            spawn_epoch=fingerprint.spawn_epoch,
            process_group_id=fingerprint.pid,
            job_handle=job_handle,
        )
        entry = RegistryEntry(
            handle=handle,
            process=process,
            args_snapshot=[fingerprint.launch_marker or ''],
            spawn_epoch=fingerprint.spawn_epoch,
        )
        self._registry.register(entry)
        self._job_handles[world_id] = job_handle
        return ProbeResult(found=True, handle=handle, matched_launch=True)

    def close_handle(self, handle: ProcessHandle) -> None:
        """Close the job object handle when the world is dropped (C3/C6)."""
        if isinstance(handle, WindowsHandle):
            job_handle = self._job_handles.pop(handle.world_id, None)
            if job_handle:
                self._close_job(job_handle)
            elif handle.job_handle:
                self._close_job(handle.job_handle)
        super().close_handle(handle)

    # -- tailing --------------------------------------------------------------

    def tail(
        self, handle: ProcessHandle, sink: object, *, since_offset: int = 0
    ) -> TailHandle:
        entry = self._registry.get(handle.world_id)
        if entry is None:
            raise LookupError(f'no registry entry for {handle.world_id}')

        for channel in entry.buffer.channels():
            buffer = entry.buffer.channel(channel)
            for _line_no, line in buffer.tail(since_offset):
                if callable(sink):
                    sink(
                        world_id=handle.world_id,
                        session_token='',
                        channel=channel,
                        line=line,
                    )
            if since_offset and buffer.trimmed(since_offset) and callable(sink):
                sink(
                    world_id=handle.world_id,
                    session_token='',
                    channel='__meta',
                    line='buffer_trimmed',
                )

        tail_handle = _WindowsTailHandle(handle.world_id, self, entry)

        def forward(channel: str, line_no: int, line: str) -> None:
            if callable(sink):
                sink(
                    world_id=handle.world_id,
                    session_token='',
                    channel=channel,
                    line=line,
                )

        for channel in entry.buffer.channels():
            buffer = entry.buffer.channel(channel)
            callback = lambda line_no, line, ch=channel: forward(ch, line_no, line)  # noqa: E731
            subscription = buffer.subscribe(callback)
            tail_handle._subscriptions.append((buffer, subscription))
        return tail_handle

    def close_tail(self, tail: TailHandle) -> None:
        tail.close()

    def tail_replay(self, handle: ProcessHandle, since_offset: int) -> list[tuple[str, int, str]]:
        """Return buffered lines as (channel, line_no, line); used by tests."""
        entry = self._registry.get(handle.world_id)
        if entry is None:
            return []
        result: list[tuple[str, int, str]] = []
        for channel in entry.buffer.channels():
            buffer = entry.buffer.channel(channel)
            for line_no, line in buffer.tail(since_offset):
                result.append((channel, line_no, line))
        return result


class _WindowsTailHandle:
    """Subscription handle; unsubscribes callbacks on close."""

    def __init__(
        self, world_id: str, adapter: WindowsProcessAdapter, entry: RegistryEntry
    ) -> None:
        self.world_id = world_id
        self._adapter = adapter
        self._entry = entry
        self._subscriptions: list[tuple[object, object]] = []
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for buffer, subscription in self._subscriptions:
            buffer.unsubscribe(subscription)  # type: ignore[attr-defined]
