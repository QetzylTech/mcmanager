"""In-process ProcessControlPort double (Document 13 section 6.1).

Implements the same port as the POSIX/Windows adapters but without real OS
processes, driven by the same argv convention as ``fake_server.py``:

- ``--port=N`` / ``--rcon-port=N``: binds real sockets on localhost so
  readiness (C8) and RCON (Doc 14) probes are real socket probes.
- ``--crash-after-ms=N``: the virtual process exits with an abnormal code
  after N ms (C4).
- ``--tick-ms=N``: emits tick lines (C5).
- ``--ignore-graceful`` / ``--ignore-rcon-stop``: stdin ``stop`` / RCON
  ``stop`` are refused so the escalation ladder (C10) is exercised.
- ``--save-slow-ms`` / ``--ignore-save-on``: save-coordination behaviour for
  Doc 14 tests.

The fake runs a virtual clock, buffers lines in a ``LogRingBuffer`` (same
tailing code as the native adapters), and emits a real "ready" event when the
virtual process reaches readiness. Process identity is simulated on a pid +
spawn-epoch handle; the PID-reuse guard (C7) is testable by forging a
mismatched epoch.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass

from app.domain.value_objects import ExitClass, ProcessState, Signal
from app.platform.process.tailing import LogRingBuffer
from app.ports.process_control import (
    ProbeFingerprint,
    ProbeResult,
    ProcessHandle,
    ProcessStatus,
    SendResult,
    SpawnRequest,
    SpawnResult,
    TailHandle,
    TerminateResult,
)

# Live processes surviving "manager death": keyed by pid so a fresh adapter
# instance (boot) can re-attach by fingerprint — mirrors native OS enumeration.
_SURVIVORS: dict[int, '_VirtualProcess'] = {}
_SURVIVORS_MUTEX = threading.Lock()


def _parse_int_after_flag(argv: list[str], flag: str, default: int = 0) -> int:
    """Parse ``--flag=N`` from an argv list (fake_server-style)."""
    for arg in argv:
        if arg.startswith(flag + '='):
            tail = arg[len(flag) + 1 :]
            try:
                return int(tail)
            except ValueError:
                return default
    return default


def _optional_int_after_flag(argv: list[str], flag: str) -> int | None:
    """Return the int for ``--flag=N`` or None when absent."""
    for arg in argv:
        if arg.startswith(flag + '='):
            tail = arg[len(flag) + 1 :]
            try:
                return int(tail)
            except ValueError:
                return None
    return None


@dataclass(frozen=True)
class FakeHandle:
    """Opaque in-process handle for the fake adapter."""

    world_id: str
    pid: int
    spawn_epoch: float
    exit_class: ExitClass = ExitClass.RUNNING

    def identity_matches(self) -> bool:
        return True

    def process_group_id(self) -> int | None:
        return self.pid


class _VirtualProcess:
    """A fake supervised process: virtual clock + real sockets + ring buffer."""

    def __init__(self, request: SpawnRequest, handle: FakeHandle) -> None:
        self.request = request
        self.handle = handle
        self.buffer = LogRingBuffer()
        self.stopped = threading.Event()
        self.graceful_ignored = any(
            arg == '--ignore-graceful' for arg in request.launch_command
        )
        self.rcon_stop_ignored = any(
            arg == '--ignore-rcon-stop' for arg in request.launch_command
        )
        self.ignore_save_on = any(
            arg == '--ignore-save-on' for arg in request.launch_command
        )
        self.crash_after_ms = _parse_int_after_flag(
            request.launch_command, '--crash-after-ms'
        )
        self.tick_ms = _parse_int_after_flag(request.launch_command, '--tick-ms')
        self.ready_ms = _parse_int_after_flag(request.launch_command, '--ready-ms')
        self.never_ready = any(arg == '--never-ready' for arg in request.launch_command)
        self.save_slow_ms = _parse_int_after_flag(
            request.launch_command, '--save-slow-ms'
        )
        self.tcp_port = _optional_int_after_flag(request.launch_command, '--port')
        self.rcon_port = _optional_int_after_flag(request.launch_command, '--rcon-port')
        self.rcon_password = 'test-pass'

        self._started = time.monotonic()
        self._listener: socket.socket | None = None
        self._rcon_listener: socket.socket | None = None

        # Last-wins like argparse: build_request prepends its own marker and
        # tests append a more specific one (C12) that must win.
        marker = ''
        for arg in request.launch_command or ():
            if arg.startswith('--marker='):
                marker = arg[len('--marker='):]
        if marker:
            self._emit(f'[FakeServer] marker={marker}')

        self._emit('Starting minecraft server version 1.21')
        if self.tcp_port:
            self._listen_tcp()
            self._emit(f'listening on 127.0.0.1:{self.tcp_port}')
        if self.rcon_port:
            self._listen_rcon()
            self._emit(f'rcon listening on 127.0.0.1:{self.rcon_port}')

        self._thread = threading.Thread(target=self._run, name='fake-server', daemon=True)
        self._thread.start()

    # -- output ---------------------------------------------------------------

    def _emit(self, line: str) -> None:
        self.buffer.append('stdout', line)

    # -- sockets --------------------------------------------------------------

    def _listen_tcp(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', self.tcp_port or 0))
        listener.listen(8)
        self._listener = listener

        def _serve() -> None:
            while not self.stopped.is_set():
                try:
                    conn, _addr = listener.accept()
                except OSError:
                    return
                try:
                    conn.settimeout(1.0)
                    raw = conn.recv(2)
                    if raw == b'\xfe\x01':
                        # Legacy server-list-ping handshake (level-4 probe).
                        conn.sendall(b'\xff\x00\x07localhost\x00\x63\x00\xdd\x00\x01\x00\x00')
                    else:
                        conn.sendall(b'FakeServer\r\n')
                except OSError:
                    pass
                finally:
                    try:
                        conn.close()
                    except OSError:
                        pass

        threading.Thread(target=_serve, name='fake-tcp-accept', daemon=True).start()

    def _listen_rcon(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', self.rcon_port or 0))
        listener.listen(4)
        self._rcon_listener = listener

        def _handle(conn: socket.socket) -> None:
            import struct

            try:
                while True:
                    header = conn.recv(4)
                    if len(header) < 4:
                        return
                    (length,) = struct.unpack('<i', header)
                    body = b''
                    while len(body) < length:
                        chunk = conn.recv(length - len(body))
                        if not chunk:
                            return
                        body += chunk
                    request_id, ptype = struct.unpack('<ii', body[:8])
                    payload = body[8:-2].decode('utf-8', errors='replace')
                    if ptype == 3:
                        ok = payload == self.rcon_password
                        conn.sendall(
                            struct.pack('<ii', request_id if ok else -1, 2) + b'\x00\x00'
                        )
                        continue
                    if ptype == 2:
                        response = self._rcon_command(payload)
                        conn.sendall(
                            struct.pack('<i', 4 + 4 + 4 + len(response) + 2)
                            + struct.pack('<ii', request_id, 0)
                            + response.encode('utf-8')
                            + b'\x00\x00'
                        )
            except (OSError, struct.error):
                return
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

        def _serve() -> None:
            while not self.stopped.is_set():
                try:
                    conn, _addr = listener.accept()
                except OSError:
                    return
                threading.Thread(target=_handle, args=(conn,), daemon=True).start()

        threading.Thread(target=_serve, name='fake-rcon-accept', daemon=True).start()

    def _rcon_command(self, command: str) -> str:
        normalized = command.strip().lower()
        if normalized == 'stop':
            if self.rcon_stop_ignored:
                return 'Cannot stop the server from the console without a stop request.'
            self.stopped.set()
            return 'Stopping the server...'
        if normalized == 'list':
            return 'There are 0 of a max of 20 players online:'
        if normalized == 'save-all':
            if self.save_slow_ms > 0:
                time.sleep(self.save_slow_ms / 1000.0)
            return 'Saved the game'
        if normalized == 'save-off':
            return 'Autosave disabled'
        if normalized == 'save-on':
            if self.ignore_save_on:
                return 'Autosave is already disabled'
            return 'Autosave enabled'
        return f'Unknown command: {command}'

    def stdin_command(self, command: str) -> str:
        normalized = command.strip().lower()
        if normalized == 'stop':
            if self.graceful_ignored:
                return 'ignored'
            self.stopped.set()
            self._emit('Stopping the server (stdin stop)')
            return 'stopping'
        if normalized in ('save-all', 'save-off', 'save-on', 'list'):
            response = self._rcon_command(command)
            self._emit(f'[FakeServer] {response}')
            return response
        return f'Unknown command: {command}'

    # -- virtual lifecycle ------------------------------------------------------

    def _run(self) -> None:
        crash_deadline = (
            self._started + self.crash_after_ms / 1000.0 if self.crash_after_ms else None
        )
        ready_deadline = (
            self._started + self.ready_ms / 1000.0 if not self.never_ready else None
        )
        # One tick line per ``tick_ms`` milliseconds (time-based, so
        # ``--tick-ms=1`` yields a steady high-rate stream for C5/C13).
        next_tick = self._started + (self.tick_ms / 1000.0) if self.tick_ms > 0 else None
        tick_count = 0
        while not self.stopped.is_set():
            now = time.monotonic()
            if crash_deadline is not None and now >= crash_deadline:
                self._emit('Crashed unexpectedly')
                self.handle = FakeHandle(
                    world_id=self.handle.world_id,
                    pid=self.handle.pid,
                    spawn_epoch=self.handle.spawn_epoch,
                    exit_class=ExitClass.CRASHED,
                )
                return
            if ready_deadline is not None and now >= ready_deadline:
                self._emit('Done (1.234s)! For help, type "help"')
                ready_deadline = None
            if next_tick is not None and now >= next_tick:
                tick_count += 1
                self._emit(f'tick {tick_count}')
                next_tick += self.tick_ms / 1000.0
            time.sleep(0.005)

    @property
    def alive(self) -> bool:
        if self.handle.exit_class is not ExitClass.RUNNING:
            return False
        return not self.stopped.is_set()

    def exit_class_now(self) -> ExitClass:
        if self.stopped.is_set():
            return ExitClass.GRACEFUL
        if self.handle.exit_class is not ExitClass.RUNNING:
            return self.handle.exit_class
        return ExitClass.RUNNING


class FakeProcessAdapter:
    """In-process ProcessControlPort double (Doc 13 section 6.1)."""

    def __init__(self) -> None:
        self._processes: dict[str, _VirtualProcess] = {}
        self._next_pid = 10000
        self._mutex = threading.Lock()

    # -- port -----------------------------------------------------------------

    def spawn(self, request: SpawnRequest) -> SpawnResult:
        argv = request.launch_command
        if not isinstance(argv, list):
            return SpawnResult(handle=None, started_at=time.time(), spawn_error='no_argv')
        with self._mutex:
            self._next_pid += 1
            pid = self._next_pid
        handle = FakeHandle(world_id=request.world_id, pid=pid, spawn_epoch=time.time())
        process = _VirtualProcess(request, handle)
        with self._mutex:
            self._processes[request.world_id] = process
        with _SURVIVORS_MUTEX:
            _SURVIVORS[pid] = process
        return SpawnResult(handle=handle, started_at=handle.spawn_epoch)

    def probe(
        self,
        world_id: str,
        session_token: str,
        *,
        fingerprint: ProbeFingerprint | None = None,
    ) -> ProbeResult:
        with self._mutex:
            process = self._processes.get(world_id)
        source = 'registry'
        if process is None and fingerprint is not None and fingerprint.pid is not None:
            # Boot reconciliation: a fresh instance re-attaches by enumerating
            # live processes (the shared survivor store) matching the launch
            # fingerprint — the fake analogue of native OS enumeration.
            with _SURVIVORS_MUTEX:
                candidate = _SURVIVORS.get(fingerprint.pid)
            if candidate is not None and candidate.alive:
                if fingerprint.spawn_epoch is not None:
                    if abs(fingerprint.spawn_epoch - candidate.handle.spawn_epoch) > 0.5:
                        candidate = None
                if candidate is not None and fingerprint.launch_marker:
                    if not any(
                        fingerprint.launch_marker in arg
                        for arg in (candidate.request.launch_command or [])
                    ):
                        candidate = None
                if candidate is not None:
                    process = candidate
                    source = 'reattached'
                    with self._mutex:
                        self._processes[world_id] = process
        if process is None:
            return ProbeResult(found=False)
        if not process.alive:
            return ProbeResult(found=False)
        if fingerprint is not None and source == 'registry':
            if fingerprint.spawn_epoch is not None:
                if abs(fingerprint.spawn_epoch - process.handle.spawn_epoch) > 0.5:
                    return ProbeResult(found=False)
            if fingerprint.launch_marker and not any(
                fingerprint.launch_marker in arg
                for arg in (process.request.launch_command or [])
            ):
                return ProbeResult(found=False)
        return ProbeResult(found=True, handle=process.handle, matched_launch=True)

    def _resolve(self, handle: ProcessHandle) -> _VirtualProcess | None:
        """Identity guard (C7): a forged epoch must reject the handle.

        Liveness is NOT part of resolution — ``poll`` must classify an
        exited-but-identity-matching process (C4). Call sites that require a
        live process check ``alive`` themselves.
        """
        process = self._processes.get(handle.world_id)
        if process is None:
            return None
        if abs(handle.spawn_epoch - process.handle.spawn_epoch) > 0.5:
            return None
        return process

    def send_signal(self, handle: ProcessHandle, signal: Signal) -> SendResult:
        process = self._resolve(handle)
        if process is None or not process.alive:
            return SendResult(delivered=False, error='process_missing')
        if signal is Signal.KILL:
            return SendResult(delivered=False, error='use_terminate_for_kill')
        if process.graceful_ignored:
            return SendResult(delivered=False, error='signal_ignored')
        process.stopped.set()
        return SendResult(delivered=True)

    def write_stdin(self, handle: ProcessHandle, text: str) -> SendResult:
        process = self._resolve(handle)
        if process is None or not process.alive:
            return SendResult(delivered=False, error='process_missing')
        process.stdin_command(text)
        return SendResult(delivered=True)
    def poll(self, handle: ProcessHandle) -> ProcessStatus:
        process = self._resolve(handle)
        if process is None:
            return ProcessStatus(
                state=ProcessState.MISSING, exit_class=ExitClass.RECONCILED_MISSING
            )
        if not process.alive:
            return ProcessStatus(
                state=ProcessState.EXITED,
                exit_code=42 if process.handle.exit_class is ExitClass.CRASHED else 0,
                exit_ts=time.time(),
                exit_class=process.exit_class_now(),
            )
        return ProcessStatus(state=ProcessState.RUNNING, exit_class=ExitClass.RUNNING)

    def tail_replay(
        self, handle: ProcessHandle, since_offset: int = 0
    ) -> list[tuple[str, int, str]]:
        """Return buffered lines as (channel, line_no, line); mirrors native."""
        process = self._processes.get(handle.world_id)
        if process is None:
            return []
        result: list[tuple[str, int, str]] = []
        for channel in process.buffer.channels():
            buffer = process.buffer.channel(channel)
            for line_no, line in buffer.tail(since_offset):
                result.append((channel, line_no, line))
        return result
    def close_handle(self, handle: ProcessHandle) -> None:
        with self._mutex:
            process = self._processes.pop(handle.world_id, None)
        if process is not None:
            with _SURVIVORS_MUTEX:
                _SURVIVORS.pop(process.handle.pid, None)

    def drop_for_crash(self, world_id: str) -> None:
        """Simulate manager death: instance registry cleared; worlds live on
        in the shared survivor store (re-attachable by a fresh instance)."""
        with self._mutex:
            self._processes.pop(world_id, None)

    def terminate(self, handle: ProcessHandle, *, graceful_deadline_s: int) -> TerminateResult:
        # PID-reuse guard (C7): a forged handle must never reach the process.
        process = self._resolve(handle)
        if process is None:
            return TerminateResult(
                resolved=False,
                exit_class=ExitClass.RECONCILED_MISSING,
                error='process_missing',
            )
        if not process.alive:
            return TerminateResult(
                resolved=True,
                exit_class=process.exit_class_now(),
                error='already_exited',
            )
        if graceful_deadline_s > 0 and not process.graceful_ignored:
            process.stopped.set()
            return TerminateResult(
                resolved=True, exit_class=ExitClass.GRACEFUL, exit_code=0
            )
        process.stopped.set()
        process.handle = FakeHandle(
            world_id=handle.world_id,
            pid=handle.pid,
            spawn_epoch=handle.spawn_epoch,
            exit_class=ExitClass.FORCED,
        )
        return TerminateResult(
            resolved=True, exit_class=ExitClass.FORCED, exit_code=137
        )

    def tail(
        self, handle: ProcessHandle, sink: object, *, since_offset: int = 0
    ) -> TailHandle:
        process = self._processes.get(handle.world_id)
        if process is None:
            raise LookupError(f'no process for {handle.world_id}')

        def forward(channel: str, line_no: int, line: str) -> None:
            if callable(sink):
                sink(
                    world_id=handle.world_id,
                    session_token='',
                    channel=channel,
                    line=line,
                )

        for channel in process.buffer.channels():
            buffer = process.buffer.channel(channel)
            for line_no, line in buffer.tail(since_offset):
                forward(channel, line_no, line)
            if since_offset and buffer.trimmed(since_offset):
                forward('__meta', 0, 'buffer_trimmed')

        return FakeTailHandle(handle.world_id, process, sink)

    def close_tail(self, tail: TailHandle) -> None:
        tail.close()


class FakeTailHandle:
    """Subscription handle that unsubscribes on close."""

    def __init__(self, world_id: str, process: _VirtualProcess, sink: object) -> None:
        self.world_id = world_id
        self._process = process
        self._sink = sink
        self._subscriptions: list[tuple[object, object]] = []

        def forward(channel: str, line_no: int, line: str) -> None:
            if callable(sink):
                sink(
                    world_id=world_id,
                    session_token='',
                    channel=channel,
                    line=line,
                )

        for channel in process.buffer.channels():
            buffer = process.buffer.channel(channel)
            callback = lambda line_no, line, ch=channel: forward(ch, line_no, line)  # noqa: E731
            subscription = buffer.subscribe(callback)
            self._subscriptions.append((buffer, subscription))

    def close(self) -> None:
        for buffer, subscription in self._subscriptions:
            buffer.unsubscribe(subscription)  # type: ignore[attr-defined]
