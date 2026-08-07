# Document 15: Platform Process-Control Adapter Specification

Scope: the portable mechanism for spawning, tracking, supervising, and terminating Java
(Minecraft server) processes and tailing their output — with **no dependency on
`systemd`, `journalctl`, or any Linux service manager**. Defines the adapter's port
interface, per-platform implementations (POSIX and Windows), runtime supervision
semantics, output tailing, termination strategies, and the conformance suite that retires
the highest-risk unknown. A **spec + prototype guide**, not a finished implementation.

Governing contracts: process supervision + reconciliation — Doc 7 §6; RuntimeSession
durability boundary — Doc 6 §1.2 (PID/handle and live health not persisted); state
resolution — never log-line-sole (ARCHITECTURE.md §8); timeout/termination policy — Doc 8;
Kill supersession — Document 11 §6; API integration — Document 12; directory/boundary
placement — Document 14; tests — Document 13.

## 1. Scope & Non-Goals

### 1.1 In scope

- Spawn a world's Java process from a data-driven launch command (templates carry the
  generic launch template; adapters launch by data, never a hard-coded `java` invocation
  baked into the adapter).
- Track the child: stable handle, PID, process group/job, exit status, uptime.
- Terminate: graceful (RCON stop command or stdin `stop`), forced (`TERM`/`KILL` on POSIX;
  `CTRL_BREAK_EVENT`/`TerminateProcess` on Windows), always with escalation order.
- Tail stdout/stderr with bounded buffers and SSE-ready emission (Document 12 `log.line`).
- Detect and classify exits (normal, crash, forced, missing-after-restart) for the state
  resolver.
- Survive manager restart: reconstruct the live-process registry by probing expected world
  processes (Doc 7 §6), never by trusting stale metadata alone.

### 1.2 Non-goals (explicitly out of scope — do not build)

- No `systemd` unit definitions, `journalctl` reads, `service`/`sc` management, or
  `cron`-based world control.
- No daemonization/forking of the manager itself.
- No network-level process management (future cluster support is a separate adapter).
- No OS-level file locking (Document 11: the RCON autosave-pause sequence is the
  domain-level equivalent; not this adapter's concern).
- No shell-script wrappers as the control mechanism — script adapters are transitional-only
  and must be retired; this spec defines the native path (ARCHITECTURE.md §4).

## 2. Port Interface (`ports/process_control.py`)

Abstract; implementations live in `platform/process/*` (Document 14 §4 leaf rule). All
methods are async-capable or use a thread-pool executor — the manager is a single-process
modular monolith and must never block the event loop on process I/O.

```python
class ProcessControlPort(Protocol):
    """Port for spawning/supervising world processes. Implementations are
    per-platform. Services depend on this interface only."""

    def spawn(self, request: SpawnRequest) -> SpawnResult: ...
    def probe(self, world_id: str, session_token: str) -> ProbeResult: ...
    def send_signal(self, handle: ProcessHandle, signal: Signal) -> SendResult: ...
    def terminate(self, handle: ProcessHandle, *, graceful_deadline_s: int) -> TerminateResult: ...
    def tail(self, handle: ProcessHandle, sink: LineSink, *, since_offset: int = 0) -> TailHandle: ...
    def poll(self, handle: ProcessHandle) -> ProcessStatus: ...
    def close_tail(self, tail: TailHandle) -> None: ...
```

Key value objects (defined in `domain/value_objects.py` per Doc 6 / Document 14):

- `SpawnRequest`: `world_id`, `launch_command: list[str]` (data-driven from Template/
  JavaRuntime + launch_args), `cwd`, `env: dict` (base env + injected secrets via
  env-var/arg path chosen at composition root), `stdout_channel`, `stderr_channel`.
- `SpawnResult`: `handle` (opaque, per-platform), `started_at`, `spawn_error?`.
- `ProcessStatus`: `alive: bool`, `exit_code: int | None`, `exit_ts: int | None`,
  `state_class: ExitClass` (below).
- `ProbeResult`: `found: bool`, `handle?`, `matched_launch: bool` — used by reconciliation
  (Doc 7 §6 step 4).
- `ExitClass` (closed enum): `running | graceful | forced | crashed | reconciled_missing |
  spawn_failed`.

## 3. Per-Platform Implementation Strategies

### 3.1 POSIX (Linux, macOS, BSD) — `platform/process/posix.py`

- Spawn via `posix_spawn` or `subprocess.Popen` with `start_new_session=True` (POSIX:
  `setsid()`) so the world runs in its **own process group/session**. The group is the
  supervision unit: killing the group kills the server and any children it spawned (e.g.
  Java's own helper processes), preventing orphans.
- No `systemd` unit, no `systemctl`, no `journalctl`. Log capture is the adapter's own
  pipe-tailing (`stdout=PIPE, stderr=PIPE`), never `journalctl` reads.
- PID tracking: a **live registry** maps `world_id → {handle, pid, process_group,
  launch_args_snapshot_hash, spawn_epoch, state}`. This registry is in-memory only
  (Doc 6 §1.2: PID/handle not persisted) and is **reconstructed at boot** by the
  reconciliation pass (§5.2). It is not a durability mechanism; it is the runtime
  registration metadata required for supervision.
- Signals:
  - Graceful: manager sends RCON `stop` first (Doc 8 Stop); as fallback, `SIGTERM` to the
    process group after the RCON path is declared unavailable.
  - Forced (`Kill`, or Stop timed out at 60s — Doc 8): `SIGKILL` to the process group.
  - Emergency stop: immediate `SIGKILL` to the group, always allowed even while the storage
    guard is tripped (Document 11 §1.2).
- Orphan/child handling: because the process group is the unit, `kill(-pgid)` reaches
  grandchildren. A double-forked daemon would escape — therefore the launch path uses a
  **wrapper-less direct spawn** (no shell, no double-fork): `launch_command` is an explicit
  argv list executed directly, so the Java process is a direct child of the manager in the
  new session. `shell=False` is mandatory and hard-coded (no shell interpolation of launch
  args).
- PID-reuse guard: before any signal or probe, verify `handle.pid` still maps to the
  recorded process (`os.kill(pid, 0)` + `/proc` identity check where available, e.g. read
  `/proc/{pid}/stat` starttime on Linux; equivalent `proc_pidinfo`/`kern.proc.pid` on
  macOS/BSD when accessible). Compare recorded spawn starttime with the current process's
  starttime to detect PID reuse. On mismatch, report `reconciled_missing` and do not signal.

### 3.2 Windows — `platform/process/windows.py`

- Spawn via `subprocess.CREATE_NEW_PROCESS_GROUP` (gives `CTRL_BREAK_EVENT` capability)
  **plus an OS Job Object** where available (Win8+/all supported). Job Objects with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` ensure that when the manager dies, the OS kills the
  job tree — replacing what systemd would otherwise do for cleanup. The Windows analog of
  the POSIX process-group supervision unit.
- All processes in the job share one supervision unit; grandchildren cannot escape the job.
- Termination:
  - Graceful: RCON `stop` first (same as POSIX). Fallback path: `CTRL_BREAK_EVENT` to the
    process group (`GenerateConsoleCtrlEvent`), which Java's console handler may treat as
    shutdown; skipped if the world has no console.
  - Forced: `TerminateProcess` on the job's primary process **and** `TerminateJobObject` to
    guarantee children are terminated (a job without `KILL_ON_JOB_CLOSE` can still be
    terminated as a unit).
  - Emergency: `TerminateJobObject` immediately.
- PID tracking: same in-memory live registry shape as POSIX, with `handle` = a small object
  holding `pid`, job handle, and creation-time snapshot. PID-reuse guard via comparing
  `process.CreationTime` (from `NtQueryInformationProcess`/`psutil`) at probe time against
  the recorded spawn time.
- Console/pipe note: for servers that need a TTY (some Forge consoles), the adapter may
  allocate a hidden pseudo-console via Windows Pseudo Console (ConPTY). Default, however,
  is pipe-based capture (identical to POSIX) to keep resource use minimal.

### 3.3 Output tailing — `platform/process/tailing.py` (shared)

- Each spawned process gets two line readers (stdout, stderr) on dedicated reader
  threads/async tasks. Lines are normalized to `\n`, capped (e.g. 64KB per line, remainder
  dropped with a sentinel marker), and emitted to a **bounded ring buffer** (default 5000
  lines per world, configurable) plus fan-out to attached SSE sinks (Document 12 `log.line`
  — server computes once, fans out; no per-client reader).
- `tail(since_offset=N)` replays buffered lines after `N` for reconnect hydration
  (Document 12 `Last-Event-ID`). When the buffer has trimmed past `N` (buffer slot
  dropped), the adapter signals `buffer_trimmed` so the client knows to view the on-disk
  log file instead (Document 12 `logs/{channel}/tail`).
- Buffers are memory-only (cache for performance, never sole source of truth). Durability
  is the on-disk log files the manager writes (§4.3); the ring buffer is the fast replay
  layer.
- Backpressure: if an SSE sink is slow, the adapter drops the slowest sink rather than
  blocking the process reader (a dead world process read blocks the supervisor).
  Slow-sink disconnect is surfaced as an alert once per minute per client.

## 4. Runtime Supervision Semantics

### 4.1 Status polling & crash detection

- The live registry holds per-world `ProcessStatus`. A supervisor loop (part of
  RuntimeService, cadence locked in Doc 8 — 1s for running worlds, 15s for idle/all-off)
  calls `poll()`.
- `poll()` feeds the state resolver (ARCHITECTURE.md §8) which combines: operation
  checkpoints + process state + health probes + advisory log strings. **A log line alone
  never flips state to `running`**; the confirmed-running transition is readiness confirmed
  by health/process state, after which RuntimeSession opens (Doc 6 §2.2).
- Exit classification (`ExitClass`) feeds `end_reason`:
  - `graceful` ↔ `graceful_stop` (Stop completed via RCON; expected exit code 0 typically)
  - `forced` ↔ `forced_stop | emergency_stop` (killed)
  - `crashed` ↔ `crashed` (unexpected exit — no Stop in flight, exit code nonzero or
    signal; always produces CrashDetected Operation + notification, Doc 8 §4.6)
  - `reconciled_missing` ↔ `reconciled_missing` (boot found no live process for an open
    session — Doc 6 §2.2, Doc 7 §6 step 4)
  - `spawn_failed` → Start Operation `Failed` (Doc 8 Start preconditions/terminal), world
    returns to `off`.

### 4.2 Readiness (Start)

- After spawn, RuntimeService waits for readiness through the **state resolver**, not a
  single log line. Candidate signals: TCP listen on the world's assigned port; RCON
  authenticated ping; process alive past quick-crash window; advisory log strings as minor
  evidence only.
- The locked 120s Start readiness timeout (Doc 8) is enforced by the supervisor; on timeout
  the Start Operation → `TimedOut`, world → `error` (never auto-cleared, Doc 6 §2.3).

### 4.3 Log durability

- The adapter's line emission also drives the manager's own on-disk world log file writer
  (per world, per session: `logs/{world_id}/{session_id}.log` plus channel-split files).
  The ring buffer serves the live tail; the on-disk file is the durable, queryable,
  downloadable channel (Document 12 files/logs). Both are fed from the single line source
  in §3.3 — no double readers.

## 5. Reconciliation & Restart Behavior

### 5.1 Never trust stale metadata alone

- PIDs/handles are not persisted (Doc 6 §1.2). On boot the live registry is empty; the
  reconciliation pass (Doc 7 §6) rebuilds it by probing.
- Per open `runtime_sessions` row (Doc 7 §6 step 3), the adapter `probe()`s for a live Java
  process matching that world's **launch fingerprint**: `launch_args_snapshot` + spawn path
  + (best-effort) process command-line match. POSIX: scan `/proc` command lines for the
  java executable and the world's `launch_args_snapshot` markers (e.g. the unique server
  jar path or `-Dworld_id` system property). Windows:
  `CreateToolhelp32Snapshot`/`psutil` process enumeration matching command line.
- `ProbeResult.found` + `matched_launch` → keep session open, world `running`, rebuild
  handle. No match → `reconciled_missing` (Doc 7 §6 step 4), world `off` (or `error` if
  the world's last Operation wasn't terminal).

### 5.2 Boot sequence

1. Load scheduler-independent startup config.
2. Build adapter (composition root, Document 14).
3. Reconciliation probes open sessions → builds live registry.
4. Reconcile interrupted Operations (Doc 7 §6 step 5: `manager_restart_incomplete`).
5. Republish snapshot to reconnecting clients (never blank).

### 5.3 Manager crash cleanup

- POSIX: the world processes run in their own sessions/process groups **detached from the
  manager's lifetime** — if the manager dies (SIGKILL, power loss), world processes keep
  running. This matches the "reconcile on boot" model: after a crash, worlds that
  self-terminated show `reconciled_missing`; worlds still running are re-probed and
  re-attached. No systemd `KillMode` semantics exist here — the manager deliberately does
  **not** kill worlds on its own exit, because an operator may restart the manager while
  worlds serve players.
- Windows with Job Object `KILL_ON_JOB_CLOSE`: the OS terminates the job tree if the
  manager process dies. **This differs from POSIX** and is a genuine platform difference:
  on Windows, worlds do not survive a manager crash by default. Where an operator needs
  worlds to survive, the composition root (Document 14) must configure the job without
  `KILL_ON_JOB_CLOSE` and rely on reconciliation — a deliberate per-deployment choice,
  documented here, never silently divergent.

## 6. Conformance Suite & Test Double

### 6.1 Why a conformance suite

The adapter is the highest-risk component. The suite runs the **same tests against every
implementation** (POSIX, Windows, plus a `FakeProcessAdapter` used in unit/E2E tests) —
this is what makes "runs on more than one OS without redesigning the core control model"
an executable check (Document 13).

### 6.2 The fake server binary (`tests/adapters/fake_server`)

A tiny program (Python or compiled per-OS) that behaves like a Minecraft server for
process-control purposes:
- Prints startup banner lines to stdout (including a configurable "ready" marker — used
  only as advisory evidence, never the sole readiness signal, per §4.1).
- Listens on a TCP port (echo or minimal RCON-frame responder) so readiness probes are
  real socket probes.
- Writes `tick` lines at a configurable rate to stdout (log-ingestion benchmark source,
  Document 13).
- Responds to: stdin `stop` (graceful exit 0), `SIGTERM`/`CTRL_BREAK` (graceful-ish exit),
  SIGKILL/TerminateProcess (crash exit); a `--crash-after=N` mode for deterministic crash
  tests.

### 6.3 Conformance tests (run per adapter per OS in CI)

| # | Test | Asserts |
|---|---|---|
| C1 | spawn → probe → poll | `spawn()` creates a live process; `probe()` finds it; `poll()` reports `running` |
| C2 | graceful stop via stdin | world exits 0, `ExitClass.graceful` |
| C3 | forced kill | `terminate(graceful_deadline_s=0)` kills the tree; `ExitClass.forced` |
| C4 | crash detection | `--crash-after=2s` (no stop) → `ExitClass.crashed`, nonzero/abnormal exit |
| C5 | tail + replay | capture N lines; `tail(since_after=N-3)` replays last 3; `buffer_trimmed` after overflow |
| C6 | orphan containment | fake_server spawns a grandchild helper; kill the group → grandchild also dead (POSIX group/job semantics) |
| C7 | PID-reuse guard | fake PID collides with a recycled process → probe reports `reconciled_missing`, no signal sent to innocent process |
| C8 | readiness via socket | spawn, wait: port listen detected → readiness signal for state resolver |
| C9 | Start timeout | fake with `--never-ready` → supervisor enforces locked 120s timeout → `TimedOut` |
| C10 | Stop timeout escalation | fake ignoring stdin stop → after locked 60s → forced kill |
| C11 | restart re-attach | spawn, simulate manager dead (stop manager process), boot manager → probe re-attaches to live world; killed-world → `reconciled_missing` |
| C12 | log durability | emitted lines present in session log file on disk after close |
| C13 | slow-sink backpressure | slow SSE sink dropped without blocking process reader |
| C14 | no-systemd structural test | static scan: no `systemd`/`journalctl`/`systemctl`/`sc`/`service` token anywhere in `app/` control-plane import graph (Document 13) |

## 7. Structural Guarantee Tests (static, CI)

- C14 above plus:
- `platform/` is the only package that may import `os`-level process APIs;
  `services/runtime.py` and `commands/` import only `ports/process_control.py`.
- No shell=True anywhere in `app/platform/process/` (guard against shell interpolation
  injection of launch args).
- Import-linter contracts (Document 14) block any `services/* → platform/*` edge.

## 8. Prototype Plan (the recommended first step)

Two spike questions to answer before full implementation; the outputs are the conformance
suite results on each target OS:

1. Spawn a real vanilla Paper/Forge server headlessly via this spec on Linux and Windows,
   and run C1-C6 + C8-C10. Record: child-tree behavior, readiness-cue reliability across
   server types, PID-reuse exposure on the reference OSes, and Windows Job-Object
   availability assumptions.
2. Validate the `KILL_ON_JOB_CLOSE` deployment choice (§5.3) against the operator
   requirement that a manager restart does not stop worlds.

The prototype's acceptance gate: conformance C1-C14 green on the target OS and on the fake
adapter, plus C11 (re-attach) verified end-to-end with a real manager boot.
