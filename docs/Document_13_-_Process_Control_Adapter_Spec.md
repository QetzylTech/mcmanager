# Document 13: Platform Process-Control Adapter Specification

Portable mechanism for spawning, tracking, supervising, terminating Java (Minecraft) processes and tailing their output — **no dependency on `systemd`, `journalctl`, or any Linux service manager**. Defines the adapter's port interface, POSIX/Windows implementations, supervision semantics, output tailing, termination, and the conformance suite that retires the highest-risk unknown. A **spec + prototype guide**, not a finished implementation.

Governing: process supervision + reconciliation — Doc 7 §6; RuntimeSession durability boundary — Doc 6 §1.2 (PID/handle + live health not persisted); state resolution — never log-line-sole (ARCHITECTURE §10); timeout/termination — Doc 8; Kill supersession — Doc 9 §6; API integration — Doc 10; directory/boundary — Doc 12; tests — Doc 11; Minecraft-specific runtime (readiness ladder, EULA, save) — Doc 14.

## 1 Scope

### 1.1 In scope
- Spawn a world's Java process from a data-driven launch command (templates carry the generic launch template; adapters launch by data, never a hard-coded `java` invocation baked in).
- Track the child: stable handle, PID, process group/job, exit status, uptime.
- Terminate: graceful (RCON stop or stdin `stop`), forced (`TERM`/`KILL` POSIX; `CTRL_BREAK_EVENT`/`TerminateProcess` Windows), always with escalation order.
- Tail stdout/stderr with bounded buffers + SSE-ready emission (Doc 10 `log.line`).
- Detect/classify exits (normal, crash, forced, missing-after-restart) for the state resolver.
- Survive manager restart: reconstruct the live-process registry by probing expected world processes (Doc 7 §6), never by trusting stale metadata alone.

### 1.2 Non-goals (do not build)
- No `systemd` units, `journalctl` reads, `service`/`sc` management, `cron`-based world control.
- No daemonization/forking of the manager itself.
- No network-level process management (future cluster = separate adapter).
- No OS-level file locking (Doc 9: the RCON autosave-pause sequence is the domain-level equivalent; not this adapter's concern).
- No shell-script wrappers as the control mechanism — script adapters are transitional-only and must be retired; this spec defines the native path (ARCHITECTURE §6).

## 2 Port interface (`ports/process_control.py`)

Abstract; implementations in `platform/process/*` (Doc 12 §4 leaf rule). All methods async-capable or use a thread-pool executor — single-process modular monolith must never block the event loop on process I/O.

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

Key value objects (defined in `domain/value_objects.py` per Doc 6 / Doc 12):
- `SpawnRequest`: `world_id`, `launch_command: list[str]` (data-driven from Template/JavaRuntime + launch_args), `cwd`, `env: dict` (base env + injected secrets via env-var/arg path chosen at composition root), `stdout_channel`, `stderr_channel`.
- `SpawnResult`: `handle` (opaque, per-platform), `started_at`, `spawn_error?`.
- `ProcessStatus`: `alive: bool`, `exit_code: int | None`, `exit_ts: int | None`, `state_class: ExitClass` (below).
- `ProbeResult`: `found: bool`, `handle?`, `matched_launch: bool` — used by reconciliation (Doc 7 §6 step 4).
- `ExitClass` (closed enum): `running | graceful | forced | crashed | reconciled_missing | spawn_failed`.

## 3 Per-platform implementation strategies

### 3.1 POSIX (Linux, macOS, BSD) — `platform/process/posix.py`
- Spawn via `posix_spawn`/`subprocess.Popen` with `start_new_session=True` (`setsid()`) → own process group/session. The group is the supervision unit: killing the group kills the server + any children (e.g. Java helper processes), preventing orphans.
- No systemd/systemctl/journalctl. Log capture = adapter's own pipe-tailing (`stdout=PIPE, stderr=PIPE`), never `journalctl` reads.
- PID tracking: **live registry** maps `world_id → {handle, pid, process_group, launch_args_snapshot_hash, spawn_epoch, state}`. In-memory only (Doc 6 §1.2: PID/handle not persisted), **reconstructed at boot** by reconciliation (§5.2). Runtime registration metadata, not a durability mechanism.
- Signals:
  - Graceful: RCON `stop` first (Doc 8 Stop); fallback `SIGTERM` to the process group after RCON declared unavailable.
  - Forced (Kill, or Stop timed out at 60s — Doc 8): `SIGKILL` to the process group.
  - Emergency stop: immediate `SIGKILL` to the group, always allowed even while the storage guard is tripped (Doc 9 §1.2).
- Orphan/child handling: `kill(-pgid)` reaches grandchildren. A double-forked daemon would escape — therefore the launch path uses a **wrapper-less direct spawn** (no shell, no double-fork): `launch_command` is an explicit argv list executed directly, so the Java process is a direct child of the manager in the new session. `shell=False` mandatory and hard-coded (no shell interpolation of launch args).
- PID-reuse guard: before any signal/probe verify `handle.pid` still maps to the recorded process (`os.kill(pid, 0)` + `/proc` identity check where available, e.g. `/proc/{pid}/stat` starttime on Linux; `proc_pidinfo`/`kern.proc.pid` on macOS/BSD when accessible). Compare recorded spawn starttime vs current; mismatch → report `reconciled_missing`, do not signal.

### 3.2 Windows — `platform/process/windows.py`
- Spawn via `subprocess.CREATE_NEW_PROCESS_GROUP` (gives `CTRL_BREAK_EVENT` capability) **plus an OS Job Object** where available (Win8+/all supported). The Job Object = Windows analog of the POSIX process-group supervision unit — bounds the tree so forced termination + orphan containment work. **`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is NOT set by default** (ARCHITECTURE §16 ruling 10): world survival across manager death is a cross-platform invariant, so the job must not kill the world tree when the manager dies, exactly as on POSIX. Cleanup-on-manager-death is replaced by boot reconciliation (§5).
- All processes in the job share one supervision unit; grandchildren cannot escape the job.
- Termination:
  - Graceful: RCON `stop` first (same as POSIX). Fallback: `CTRL_BREAK_EVENT` to the process group (`GenerateConsoleCtrlEvent`), which Java's console handler may treat as shutdown; skipped if the world has no console.
  - Forced: `TerminateProcess` on the job's primary process **and** `TerminateJobObject` to guarantee children terminated (a job without `KILL_ON_JOB_CLOSE` can still be terminated as a unit).
  - Emergency: `TerminateJobObject` immediately.
- PID tracking: same in-memory live-registry shape as POSIX, `handle` = small object holding `pid`, job handle, creation-time snapshot. PID-reuse guard via comparing `process.CreationTime` (from `NtQueryInformationProcess`/`psutil`) at probe time vs recorded spawn time.
- Console/pipe note: servers needing a TTY (some Forge consoles) may get a hidden pseudo-console via Windows Pseudo Console (ConPTY). Default is pipe-based capture (identical to POSIX) to keep resource use minimal.

### 3.3 Output tailing — `platform/process/tailing.py` (shared)
- Each spawned process gets two line readers (stdout, stderr) on dedicated reader threads/async tasks. Lines normalized to `\n`, capped (e.g. 64KB per line, remainder dropped with a sentinel marker), then emitted to a **bounded ring buffer** (default 5000 lines/world, configurable) + fan-out to attached SSE sinks (Doc 10 `log.line` — server computes once, fans out; no per-client reader). With `VERBOSE_LOGGING=false`, nonessential raw stdout/stderr noise bypasses disk and buffer writes; severe warnings, errors, crashes, and readiness markers still flow so readiness evaluation remains intact. `VERBOSE_LOGGING=true` retains full output.
- `tail(since_offset=N)` replays buffered lines after `N` for reconnect hydration (Doc 10 `Last-Event-ID`). When the buffer has trimmed past `N` (slot dropped), the adapter signals `buffer_trimmed` so the client views the on-disk log file instead (Doc 10 `logs/{channel}/tail`).
- Buffers are memory-only (cache, never sole source of truth). Durability = on-disk log files the manager writes (§4.3); the ring buffer is the fast replay layer.
- Backpressure: slow SSE sink → drop the slowest sink rather than block the process reader (a dead world process read blocks the supervisor). Slow-sink disconnect surfaced as an alert once per minute per client.

## 4 Runtime supervision semantics

### 4.1 Status polling & crash detection
- Live registry holds per-world `ProcessStatus`. Supervisor loop (part of RuntimeService, cadence locked in Doc 8 — 1s running worlds, 15s idle/all-off) calls `poll()`.
- `poll()` feeds the state resolver (ARCHITECTURE §10) which combines: operation checkpoints + process state + health probes + advisory log strings. **A log line alone never flips state to `running`**; confirmed-running = readiness confirmed by health/process state, after which RuntimeSession opens (Doc 6 §2.2).
- Exit classification (`ExitClass`) feeds `end_reason`:
  - `graceful` ↔ `graceful_stop` (Stop completed via RCON; expected exit code 0 typically)
  - `forced` ↔ `forced_stop | emergency_stop` (killed)
  - `crashed` ↔ `crashed` (unexpected exit — no Stop in flight, nonzero exit or signal; always produces CrashDetected Operation + notification, Doc 8 §2.x)
  - `reconciled_missing` ↔ `reconciled_missing` (boot found no live process for an open session — Doc 6 §2.2, Doc 7 §6 step 4)
  - `spawn_failed` → Start Operation `Failed` (Doc 8 Start preconditions), world returns `off`.

### 4.2 Readiness (Start)
- After spawn, RuntimeService waits for readiness through the **state resolver**, not a single log line. C8 socket check = **minimum floor, not the contract**: Doc 14 §3 hierarchy (`process_alive → port_bound → rcon_ready → probe_ok → operationally_valid`) is normative; `starting -> running` fires only at the highest available level for the server type. TCP listen, RCON ping, process alive past the quick-crash window, and advisory log strings feed the resolver as candidate signals — never alone.
- Locked 120s Start readiness timeout (Doc 8) enforced by the supervisor; on timeout Start Operation → `TimedOut`, world → `error` (never auto-cleared, Doc 6 §2.3).

### 4.3 Log durability
- The adapter's accepted line emission also drives the manager's on-disk world log file writer (per world, per session: `logs/{world_id}/{session_id}.log` + channel-split files). In deployed `VERBOSE_LOGGING=false` mode, filtered noise never reaches these writers or buffers, preventing log churn and buffer thrashing. The ring buffer serves the live tail; the on-disk file is the durable, queryable, downloadable channel (Doc 10 files/logs). Both fed from the single line source in §3.3 — no double readers.

## 5 Reconciliation & restart behavior

### 5.1 Never trust stale metadata alone
- PIDs/handles not persisted (Doc 6 §1.2). On boot the live registry is empty; reconciliation (Doc 7 §6) rebuilds it by probing.
- Per open `runtime_sessions` row (Doc 7 §6 step 3), the adapter `probe()`s for a live Java process matching that world's **launch fingerprint**: `launch_args_snapshot` + spawn path + (best-effort) process command-line match. POSIX: scan `/proc` command lines for the java executable + the world's `launch_args_snapshot` markers (e.g. unique server jar path or `-Dworld_id` system property). Windows: `CreateToolhelp32Snapshot`/`psutil` enumeration matching command line.
- `ProbeResult.found` + `matched_launch` → keep session open, world `running`, rebuild handle. No match → `reconciled_missing` (Doc 7 §6 step 4), world `off` (or `error` if the world's last Operation wasn't terminal).

### 5.2 Boot sequence
1. Load scheduler-independent startup config.
2. Build adapter (composition root, Doc 12).
3. Reconciliation probes open sessions → builds live registry.
4. Reconcile interrupted Operations (Doc 7 §6 step 5: `manager_restart_incomplete`).
5. Republish snapshot to reconnecting clients (never blank).

### 5.3 Manager crash cleanup
- POSIX: world processes run in their own sessions/process groups **detached from the manager's lifetime** — if the manager dies (SIGKILL, power loss), worlds keep running. Matches the "reconcile on boot" model: after crash, self-terminated worlds show `reconciled_missing`; still-running worlds are re-probed and re-attached. No systemd `KillMode` semantics — the manager deliberately does **not** kill worlds on its own exit, because an operator may restart the manager while worlds serve players.
- Windows: because the Job Object **does not set `KILL_ON_JOB_CLOSE` by default** (§3.2, ARCHITECTURE §16 ruling 10), manager death leaves the job tree running — same semantics as POSIX. World survival across manager restart is a **cross-platform invariant**, not a per-deployment option: no platform difference, no silent divergence.

## 6 Conformance suite & test double

### 6.1 Why
The adapter is the highest-risk component. The suite runs the **same tests against every implementation** (POSIX, Windows, plus a `FakeProcessAdapter` used in unit/E2E tests) — this is what makes "runs on >1 OS without redesigning the core control model" an executable check (Doc 11).

### 6.2 The fake server binary (`tests/adapters/fake_server`)
A tiny program (Python or compiled per-OS) behaving like a Minecraft server for process-control purposes:
- Prints startup banner lines to stdout (incl. configurable "ready" marker — advisory evidence only, never the sole readiness signal, per §4.1).
- Listens on a TCP port (echo or minimal RCON-frame responder) so readiness probes are real socket probes.
- Writes `tick` lines at a configurable rate to stdout (log-ingestion benchmark source, Doc 11).
- Responds to: stdin `stop` (graceful exit 0), `SIGTERM`/`CTRL_BREAK` (graceful-ish exit), SIGKILL/TerminateProcess (crash exit); `--crash-after=N` mode for deterministic crash tests.
- **Doc 14 extensions** (for Minecraft-adapter integration tests, Doc 11):
  - `--eula={not_present|unaccepted|accepted}`: writes/omits `eula.txt` accordingly; refuses to stay up unless EulaState `accepted` — deterministic EULA-gate testing.
  - `--save-slow`: `save-all` responses delayed (async-flush simulation) so save-completion detection is testable.
  - `--ignore-save-on`: accepts `save-off` but never restores autosave on `save-on` — exercises save-coordination recovery paths (Doc 8, Doc 14 §10).

### 6.3 Conformance tests (run per adapter per OS in CI)

| # | Test | Asserts |
|---|---|---|
| C1 | spawn → probe → poll | `spawn()` creates live process; `probe()` finds it; `poll()` reports `running` |
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
| C14 | no-systemd structural test | static scan: no `systemd`/`journalctl`/`systemctl`/`sc`/`service` token anywhere in `app/` control-plane import graph (Doc 11) |

## 7 Structural guarantee tests (static, CI)

- C14 above plus:
- `platform/` is the only package that may import `os`-level process APIs; `services/runtime.py` and `commands/` import only `ports/process_control.py`.
- No shell=True anywhere in `app/platform/process/` (guard against shell interpolation injection of launch args).
- Import-linter contracts (Doc 12) block any `services/* → platform/*` edge.

## 8 Prototype plan (recommended first step)

Two spike questions to answer before full implementation; outputs = conformance suite results on each target OS:

1. Spawn real **Vanilla, Paper, Forge, Fabric** servers headlessly via this spec on Linux + Windows; run C1–C6 + C8–C10. Record: child-tree behavior, readiness-cue reliability across server types (validated against the Doc 14 hierarchy, incl. Forge/Fabric slow startup), PID-reuse exposure on the reference OSes, Windows Job-Object availability assumptions.
2. Validate the cross-platform world-survival invariant (§5.3, ARCHITECTURE §16 ruling 10): worlds keep running when the manager dies on both POSIX and Windows, re-attached by boot reconciliation. Single behavior — no per-OS option.

Extended by Gate 1 real-Minecraft spike (ARCHITECTURE §15 item 1): EULA gating, Java compatibility, RCON, and save coordination exercised against live Vanilla/Paper/Forge/Fabric behavior per Doc 14 §13.

Live server installations may be available as ignored machine-local data
under `app/data/worlds/`, but their presence and server-type coverage are not
guaranteed in every checkout or CI worker. Check before planning a spike. If
using one, follow Document 11 §1.4: test a disposable copy with loopback-only
ports, preserve the original world and EULA state, and report only the
server types and behaviors actually exercised. Missing live installations do
not block synthetic conformance tests; synthetic results do not count as live
Minecraft evidence.

Prototype acceptance gate: conformance C1–C14 green on the target OS + the fake adapter, plus C11 (re-attach) verified end-to-end with a real manager boot.
