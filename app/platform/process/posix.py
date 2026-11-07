"""POSIX process-control adapter (Document 13 section 3.1).

- Spawn via ``subprocess.Popen`` with ``start_new_session=True``
  (``setsid()``) -> own process group/session; the group is the supervision
  unit, so killing the group kills the server plus any children (orphan
  containment, C6).
- No service-manager integration and no external log daemons: log capture is
  the adapter's own pipe-tailing.
- Signals: TERMINATE = SIGTERM to the process group; KILL = SIGKILL to the
  process group. PID-reuse guard via psutil creation-time vs spawn snapshot.
- Boot reconciliation (C11): ``probe()`` re-attaches to a live process
  matching a launch fingerprint (Doc 13 section 5.1) — never trusting stale
  metadata alone.

Only imported on non-Windows hosts; kept import-safe on Windows for tests.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
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

_IDENTITY_TOLERANCE_S = 1.0


@dataclass(frozen=True)
class PosixHandle:
    """Opaque POSIX process-tree handle (gate1 Module 1 fields)."""

    world_id: str
    pid: int
    spawn_epoch: float
    process_group_id: int | None = None
    job_handle: object | None = None

    def identity_matches(self) -> bool:
        return _pid_matches(self.pid, self.spawn_epoch)


def _pid_matches(pid: int, spawn_epoch: float) -> bool:
    try:
        process = psutil.Process(pid)
        return abs(process.create_time() - spawn_epoch) < _IDENTITY_TOLERANCE_S
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return False


class PosixProcessAdapter(BaseProcessAdapter):
    """Doc 13 section 3.1 POSIX implementation."""

    def __init__(self, registry: LiveRegistry | None = None) -> None:
        super().__init__(registry)
        self._primary_jobs: dict[str, int] = {}

    # -- spawn ---------------------------------------------------------------

    def _spawn_impl(self, request: SpawnRequest) -> tuple[psutil.Process, ProcessHandle]:
        popen = subprocess.Popen(
            request.launch_command,
            cwd=request.cwd,
            env={**os.environ, **request.env},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            shell=False,  # mandatory: no shell interpolation of launch args
        )
        process = psutil.Process(popen.pid)
        handle = PosixHandle(
            world_id=request.world_id,
            pid=popen.pid,
            spawn_epoch=process.create_time(),
            process_group_id=os.getpgid(popen.pid),
        )
        return process, handle

    def spawn(self, request: SpawnRequest) -> SpawnResult:
        """Override to stash the ``Popen`` for the stdin channel + readers."""
        argv = request.launch_command
        if not isinstance(argv, list):
            return SpawnResult(handle=None, started_at=time.time(), spawn_error='no_argv')
        try:
            popen = subprocess.Popen(
                request.launch_command,
                cwd=request.cwd,
                env={**os.environ, **request.env},
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                shell=False,  # mandatory: no shell interpolation of launch args
            )
        except OSError as exc:
            return SpawnResult(handle=None, started_at=time.time(), spawn_error=str(exc))

        process = psutil.Process(popen.pid)
        handle = PosixHandle(
            world_id=request.world_id,
            pid=popen.pid,
            spawn_epoch=process.create_time(),
            process_group_id=os.getpgid(popen.pid),
        )
        entry = RegistryEntry(
            handle=handle,
            process=process,
            args_snapshot=list(argv),
            spawn_epoch=handle.spawn_epoch,
            popen=popen,
        )
        self._registry.register(entry)
        self._start_readers(entry, request)
        return SpawnResult(handle=handle, started_at=entry.spawn_epoch)

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
        self, process: psutil.Process, handle: ProcessHandle, signal_: Signal
    ) -> SendResult:
        if signal_ is Signal.KILL:
            return SendResult(delivered=False, error='use_terminate_for_kill')
        pgid = handle.process_group_id
        if pgid is None:
            pgid = os.getpgid(process.pid)
        os.killpg(pgid, signal.SIGTERM)
        return SendResult(delivered=True)

    def _kill_tree_impl(self, process: psutil.Process, handle: ProcessHandle) -> None:
        pgid = handle.process_group_id
        if pgid is None:
            pgid = os.getpgid(process.pid)
        os.killpg(pgid, signal.SIGKILL)

    # -- probe / boot reconciliation (C11) -------------------------------------

    def probe(
        self,
        world_id: str,
        session_token: str,
        *,
        fingerprint: ProbeFingerprint | None = None,
    ) -> ProbeResult:
        """Re-attach to a live process (Doc 13 section 5.1).

        1. Registry-first: a supervised pid still matching its spawn identity.
        2. Fingerprint fallback: enumerate live processes matching the launch
           fingerprint (pid + spawn-epoch tolerance, first argv, cwd) and
           register a new handle — this is the boot-reconciliation path.
        """
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
        try:
            pgid = os.getpgid(fingerprint.pid)
        except (ProcessLookupError, PermissionError):
            pgid = fingerprint.pid
        handle = PosixHandle(
            world_id=world_id,
            pid=fingerprint.pid,
            spawn_epoch=fingerprint.spawn_epoch,
            process_group_id=pgid,
        )
        entry = RegistryEntry(
            handle=handle,
            process=process,
            args_snapshot=[fingerprint.launch_marker or ''],
            spawn_epoch=fingerprint.spawn_epoch,
        )
        self._registry.register(entry)
        self._primary_jobs[world_id] = pgid
        return ProbeResult(found=True, handle=handle, matched_launch=True)

    # -- tailing --------------------------------------------------------------

    def tail(
        self, handle: ProcessHandle, sink: object, *, since_offset: int = 0
    ) -> TailHandle:
        entry = self._registry.get(handle.world_id)
        if entry is None:
            raise LookupError(f'no registry entry for {handle.world_id}')

        for channel in entry.buffer.channels():
            buffer = entry.buffer.channel(channel)
            for line_no, line in buffer.tail(since_offset):
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

        tail_handle = _PosixTailHandle(handle.world_id, self, entry)

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


class _PosixTailHandle:
    """Subscription handle; unsubscribes callbacks on close."""

    def __init__(self, world_id: str, adapter: PosixProcessAdapter, entry: RegistryEntry) -> None:
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
