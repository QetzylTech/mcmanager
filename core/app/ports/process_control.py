"""Process-control port interface (Document 13 section 2).

Abstract protocol; implementations live in ``app/platform/process/*``.
Services depend on this interface only — never on a concrete adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.domain.value_objects import ExitClass, ProcessState, Signal


@dataclass(frozen=True)
class SpawnRequest:
    """Data-driven launch request. ``launch_command`` is an explicit argv
    list executed directly — never a shell string."""

    world_id: str
    launch_command: list[str]
    cwd: str
    env: dict[str, str] = field(default_factory=dict)
    stdout_channel: str = 'stdout'
    stderr_channel: str = 'stderr'


@dataclass(frozen=True)
class SpawnResult:
    """Outcome of a spawn attempt. ``handle`` is None when spawn failed."""

    handle: 'ProcessHandle | None'
    started_at: float
    spawn_error: str | None = None


@dataclass(frozen=True)
class ProcessStatus:
    """Snapshot of a supervised process's live state."""

    state: ProcessState
    exit_code: int | None = None
    exit_ts: float | None = None
    exit_class: ExitClass = ExitClass.RUNNING

    @property
    def alive(self) -> bool:
        return self.state is ProcessState.RUNNING


@dataclass(frozen=True)
class ProbeFingerprint:
    """Launch fingerprint used by boot reconciliation (Doc 13 section 5.1).

    When a world's open runtime_session row is found, the adapter probes for
    a live process matching this fingerprint instead of trusting stale
    metadata. ``launch_marker`` is a unique argv substring (e.g. the world's
    server jar path or a ``-Dworld_id`` system property).
    """

    pid: int | None = None
    spawn_epoch: float | None = None
    cwd: str | None = None
    launch_marker: str | None = None


@dataclass(frozen=True)
class ProbeResult:
    """Boot-reconciliation probe outcome (Doc 13 section 5)."""

    found: bool
    handle: 'ProcessHandle | None' = None
    matched_launch: bool = False


class ProcessHandle(Protocol):
    """Opaque per-platform handle to a supervised process tree.

    The identity-isolation point: ``pid``/identity are captured at spawn and
    re-verified before every signal decision (PID-reuse guard, Doc 13 C7).
    """

    world_id: str
    pid: int
    spawn_epoch: float

    def identity_matches(self) -> bool:
        """True when the recorded PID still maps to the spawned process.

        Rejects PID-reuse collisions that would otherwise deliver signals to
        an innocent process."""

    def process_group_id(self) -> int | None:
        """Windows: job-object id; POSIX: process-group id (None if n/a)."""


@dataclass(frozen=True)
class SendResult:
    """Outcome of a signal/command-delivery attempt."""

    delivered: bool
    error: str | None = None


@dataclass(frozen=True)
class TerminateResult:
    """Outcome of a terminate(escalation) attempt."""

    resolved: bool
    exit_class: ExitClass
    exit_code: int | None = None
    error: str | None = None


class LineSink(Protocol):
    """Sink receiving normalized log lines from a supervised process."""

    def __call__(
        self, *, world_id: str, session_token: str, channel: str, line: str
    ) -> None: ...


class TailHandle(Protocol):
    """Opaque handle to a line-tail subscription."""

    world_id: str

    def close(self) -> None: ...


@runtime_checkable
class ProcessControlPort(Protocol):
    """Port for spawning/supervising world processes (Doc 13 section 2)."""

    def spawn(self, request: SpawnRequest) -> SpawnResult: ...

    def probe(
        self,
        world_id: str,
        session_token: str,
        *,
        fingerprint: ProbeFingerprint | None = None,
    ) -> ProbeResult: ...

    def send_signal(self, handle: ProcessHandle, signal: Signal) -> SendResult: ...

    def write_stdin(self, handle: ProcessHandle, text: str) -> SendResult: ...

    def terminate(
        self, handle: ProcessHandle, *, graceful_deadline_s: int
    ) -> TerminateResult: ...

    def tail(
        self, handle: ProcessHandle, sink: LineSink, *, since_offset: int = 0
    ) -> TailHandle: ...

    def poll(self, handle: ProcessHandle) -> ProcessStatus: ...

    def close_tail(self, tail: TailHandle) -> None: ...

    def close_handle(self, handle: ProcessHandle) -> None: ...
