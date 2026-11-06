"""Shared cross-platform process-supervision helpers (Document 13).

Provides the live registry, PID-identity verification, exit classification,
and termination escalation ladder shared by the POSIX and Windows adapters.
No shell-string execution anywhere in this package (Doc 12 section 8 /
Doc 13 C14); launches are always explicit argv lists.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field

import psutil

from app.domain.value_objects import ExitClass, ProcessState, Signal
from app.platform.process.tailing import LogRingBuffer
from app.ports.process_control import (
    ProcessHandle,
    ProcessStatus,
    SendResult,
    SpawnResult,
    TerminateResult,
)

# PID-identity tolerance: two processes can never share a create-time within
# this window on any supported OS, making the reuse guard reliable.
_PID_IDENTITY_TOLERANCE_S = 30.0

# Escalation: after a forced signal, wait at most this long for the tree to
# exit before declaring the termination unresolved (Doc 13 C3 / Doc 8 Kill
# deadline 10s).
_KILL_SETTLE_DEADLINE_S = 10.0


@dataclass
class RegistryEntry:
    """One supervised process tree, keyed by world_id."""

    handle: ProcessHandle
    process: psutil.Process
    args_snapshot: list[str]
    spawn_epoch: float
    popen: subprocess.Popen[bytes] | None = None
    state: ProcessState = ProcessState.RUNNING
    exit_code: int | None = None
    exit_ts: float | None = None
    exit_class: ExitClass = ExitClass.RUNNING
    buffer: LogRingBuffer = field(default_factory=LogRingBuffer)
    readers: list[object] = field(default_factory=list)


class LiveRegistry:
    """In-memory world_id -> process mapping (Doc 13 section 3.1/3.2).

    Runtime registration metadata only — never a durability mechanism.
    Reconstructed at boot by reconciliation probing.
    """

    def __init__(self) -> None:
        self._entries: dict[str, RegistryEntry] = {}
        self._mutex = threading.RLock()

    def register(self, entry: RegistryEntry) -> None:
        with self._mutex:
            self._entries[entry.handle.world_id] = entry

    def get(self, world_id: str) -> RegistryEntry | None:
        with self._mutex:
            return self._entries.get(world_id)

    def remove(self, world_id: str) -> None:
        with self._mutex:
            self._entries.pop(world_id, None)

    def all(self) -> tuple[RegistryEntry, ...]:
        with self._mutex:
            return tuple(self._entries.values())

    def clear(self) -> None:
        with self._mutex:
            self._entries.clear()

    # -- process-enumeration facade (oracle for C11 probe) ---------------------

    def snapshot_for_probe(self) -> list[tuple[str, int, float, str]]:
        """Return (world_id, pid, spawn_epoch, cwd-or-'') tuples to probe.

        The probe re-attachment path (Doc 13 section 5.1) enumerates live
        processes and matches each against this snapshot. A fresh registry
        (post-crash boot) is empty — the caller then passes a known
        fingerprint built from the world's launch snapshot instead.
        """
        with self._mutex:
            return [
                (
                    entry.handle.world_id,
                    entry.handle.pid,
                    entry.handle.spawn_epoch,
                    entry.args_snapshot[0] if entry.args_snapshot else '',
                )
                for entry in self._entries.values()
            ]


class BaseProcessAdapter:
    """Shared process-supervision logic for the platform adapters.

    Subclasses implement ``_spawn_impl``, ``_signal_tree_impl`` and
    ``_kill_tree_impl``; the base provides the escalation ladder, identity
    guard, polling, exit classification, and the stdin channel.
    """

    def __init__(self, registry: LiveRegistry | None = None) -> None:
        self._registry = registry or LiveRegistry()

    # -- spawn ---------------------------------------------------------------

    def spawn(self, request: object) -> SpawnResult:
        argv = getattr(request, 'launch_command', None)
        if not isinstance(argv, list):
            return SpawnResult(handle=None, started_at=time.time(), spawn_error='no_argv')
        try:
            process, handle = self._spawn_impl(request)
        except OSError as exc:
            return SpawnResult(handle=None, started_at=time.time(), spawn_error=str(exc))

        entry = RegistryEntry(
            handle=handle,
            process=process,
            args_snapshot=list(argv),
            spawn_epoch=handle.spawn_epoch,
            popen=getattr(request, 'popen', None),
        )
        self._registry.register(entry)
        self._start_readers(entry, request)
        return SpawnResult(handle=handle, started_at=entry.spawn_epoch)

    def _spawn_impl(self, request: object) -> tuple[psutil.Process, ProcessHandle]:
        raise NotImplementedError

    def _start_readers(self, entry: RegistryEntry, request: object) -> None:
        """Wire line-reader threads for stdout/stderr (overridable)."""
        return None

    # -- identity guard (Doc 13 C7) -------------------------------------------

    def identity_matches(self, handle: ProcessHandle) -> bool:
        """True when the recorded pid still maps to the same process."""
        try:
            process = psutil.Process(handle.pid)
            create_time = process.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            return False
        return abs(create_time - handle.spawn_epoch) < _PID_IDENTITY_TOLERANCE_S

    def _resolve_process(self, handle: ProcessHandle) -> psutil.Process | None:
        if not self.identity_matches(handle):
            return None
        try:
            return psutil.Process(handle.pid)
        except psutil.NoSuchProcess:
            return None

    # -- exit codes (psutil.Process has no returncode; Popen is authoritative) --

    def _registry_exit_code(self, world_id: str) -> int | None:
        """Real exit code via the Popen handle when available."""
        entry = self._registry.get(world_id)
        if entry is None or entry.popen is None:
            return None
        try:
            return entry.popen.poll()  # type: ignore[union-attr]  # Popen has poll
        except (AttributeError, ValueError):
            return None

    def _poll_exit_code(self, world_id: str, process: psutil.Process) -> int | None:
        code = self._registry_exit_code(world_id)
        if code is not None:
            return code
        return getattr(process, 'returncode', None)

    def _safe_returncode(self, world_id: str, process: psutil.Process) -> int | None:
        """Non-fatal exit-code accessor (psutil.Process lacks ``returncode``)."""
        return self._poll_exit_code(world_id, process)

    # -- signals ---------------------------------------------------------------

    def _signal_tree_impl(self, process: psutil.Process, signal: Signal) -> SendResult:
        raise NotImplementedError

    def _kill_tree_impl(self, process: psutil.Process) -> None:
        raise NotImplementedError

    def send_signal(self, handle: ProcessHandle, signal: Signal) -> SendResult:
        process = self._resolve_process(handle)
        if process is None:
            return SendResult(delivered=False, error='process_missing')
        try:
            return self._signal_tree_impl(process, signal)
        except (psutil.Error, OSError) as exc:
            return SendResult(delivered=False, error=str(exc))

    # -- stdin (Doc 14 shutdown ladder step 2) --------------------------------

    def write_stdin(self, handle: ProcessHandle, text: str) -> SendResult:
        """Write a command to the child's stdin (graceful stop fallback).

        Refuses when the stdin pipe is closed, the process is missing
        (PID-reuse guard applies first), or the world was re-attached at
        boot (the stdin pipe cannot be rebuilt — RCON applies instead).
        """
        process = self._resolve_process(handle)
        if process is None:
            return SendResult(delivered=False, error='process_missing')
        entry = self._registry.get(handle.world_id)
        if entry is None or entry.popen is None or entry.popen.stdin is None:
            return SendResult(delivered=False, error='stdin_unavailable')
        stream = entry.popen.stdin
        try:
            stream.write((text + '\n').encode('utf-8'))
            stream.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            return SendResult(delivered=False, error=str(exc))
        return SendResult(delivered=True)

    # -- terminate (escalation ladder) ------------------------------------------

    def terminate(self, handle: ProcessHandle, graceful_deadline_s: int = 10) -> TerminateResult:
        """Escalation ladder (Doc 13 section 3 / Doc 8 section 5.0).

        TERMINATE -> wait for graceful_deadline_s -> KILL. A zero deadline
        means immediate forced kill (C3).
        """
        process = self._resolve_process(handle)
        if process is None:
            return TerminateResult(
                resolved=False,
                exit_class=ExitClass.RECONCILED_MISSING,
                error='process_missing',
            )

        if graceful_deadline_s > 0:
            result = self._signal_tree_impl(process, Signal.TERMINATE)
            if result.delivered:
                deadline = time.time() + graceful_deadline_s
                while time.time() < deadline:
                    if self._process_exited(process):
                        return TerminateResult(
                            resolved=True,
                            exit_class=ExitClass.GRACEFUL,
                            exit_code=self._safe_returncode(handle.world_id, process),
                        )
                    time.sleep(0.2)
                return self._kill_and_classify(handle, process)

        return self._kill_and_classify(handle, process)

    def _kill_and_classify(
        self, handle: ProcessHandle, process: psutil.Process
    ) -> TerminateResult:
        try:
            self._kill_tree_impl(process)
        except (psutil.Error, OSError) as exc:
            return TerminateResult(
                resolved=False, exit_class=ExitClass.FORCED, error=str(exc)
            )
        deadline = time.time() + _KILL_SETTLE_DEADLINE_S
        while time.time() < deadline:
            if self._process_exited(process):
                return TerminateResult(
                    resolved=True,
                    exit_class=ExitClass.FORCED,
                    exit_code=self._safe_returncode(handle.world_id, process),
                )
            time.sleep(0.2)
        return TerminateResult(
            resolved=False, exit_class=ExitClass.FORCED, error='kill_settle_timeout'
        )

    def _process_exited(self, process: psutil.Process) -> bool:
        try:
            return process.status() == psutil.STATUS_ZOMBIE or not process.is_running()
        except psutil.NoSuchProcess:
            return True
        except psutil.AccessDenied:
            return False

    # -- poll / classify ---------------------------------------------------------

    def poll(self, handle: ProcessHandle) -> ProcessStatus:
        """Live status of a supervised process.

        Exit classification is context-free at the adapter layer: an exited
        process reports its Popen exit code; a process that simply vanished
        reports ``crashed`` unless it exited 0/1 (stop-triggered). The
        supervisor overlays Stop-in-flight context at the service layer
        (Doc 13 section 4.1).
        """
        world_id = handle.world_id
        try:
            process = psutil.Process(handle.pid)
        except psutil.NoSuchProcess:
            code = self._registry_exit_code(world_id)
            return ProcessStatus(
                state=ProcessState.EXITED,
                exit_code=code,
                exit_ts=time.time(),
                exit_class=self._classify_exit(code),
            )
        if not self.identity_matches(handle):
            # PID reused by a different process: never signal it (Doc 13 C7).
            return ProcessStatus(
                state=ProcessState.MISSING,
                exit_class=ExitClass.RECONCILED_MISSING,
            )
        try:
            if not process.is_running():
                code = self._poll_exit_code(world_id, process)
                return ProcessStatus(
                    state=ProcessState.EXITED,
                    exit_code=code,
                    exit_ts=time.time(),
                    exit_class=self._classify_exit(code),
                )
        except psutil.NoSuchProcess:
            # Race: the process exited between the status() probe and the
            # result return. psutil on Windows raises NoSuchProcess here
            # instead of returning False — classify via the Popen exit code.
            code = self._registry_exit_code(world_id)
            return ProcessStatus(
                state=ProcessState.EXITED,
                exit_code=code,
                exit_ts=time.time(),
                exit_class=self._classify_exit(code),
            )
        return ProcessStatus(state=ProcessState.RUNNING, exit_class=ExitClass.RUNNING)

    def _classify_exit(self, exit_code: int | None) -> ExitClass:
        """Unexpected exit => crash; expected 0/1 (stop-triggered) => graceful.

        The supervisor's context (Stop in flight, killed, etc.) overrides this
        classification at the service layer.
        """
        if exit_code in (0, 1):
            return ExitClass.GRACEFUL
        return ExitClass.CRASHED

    def close_handle(self, handle: ProcessHandle) -> None:
        self._registry.remove(handle.world_id)
