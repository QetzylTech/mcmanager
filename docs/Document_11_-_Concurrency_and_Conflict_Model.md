# Document 11: Concurrency, Locking & Conflict Resolution Model

Scope: every resource in the system that more than one actor (user, background job, or
another Operation) could touch simultaneously. Authoritative for all lock
taxonomy, conflict detection, and queue/reject/preempt semantics.

## 1. Lock Taxonomy

Four lock classes. None are literal database row locks — SQLite's own locking is a
mechanism, not a domain concept. These are *application-level* locks enforced by the
services, backed by the state already in the schema.

### 1.1 World lock (per-world, blocking)

- Scope: one `world_id`.
- Held by: whichever of Start/Stop/Kill/Backup/Restore/Cleanup/DeleteWorld currently has an
  in-flight Operation against that world.
- Mechanism: **derived, not stored** — "does an in-flight Operation exist for this world?"
  is a query over `operations`: `world_id = ? AND status IN
  ('Created','Queued','Validating','Running')`, backed by the `(world_id, status)` index
  (Doc 7). No lock column on `world_instances` — the former `current_operation_id` column
  was removed to avoid a circular FK with `operations.world_id`.
- Race note: the acquire step must be a single transaction — INSERT the new Operation row
  and re-check that no non-terminal Operation exists for the world in the same transaction.
  The `(world_id, status)` index plus SQLite's serialized writes make this atomic.
- Not reentrant: an Operation cannot be nested inside another on the same world.
  Compensating actions (automatic restore-revert) are new Operations that wait for the
  original to reach a terminal state first.

### 1.2 Global storage lock (system-wide, blocking)

- Scope: the entire host.
- Held implicitly whenever the storage guard is tripped — not a lock anyone acquires and
  releases; a standing precondition re-checked by every Operation type that writes to disk
  (Start, Backup, Restore, Sync).
- The guard is **contextual, not a flat percentage**: compares the estimated job size
  (world, backup artifact, restore target) against available free space minus a configurable
  absolute reserve (default 10 GB), with a 10% free-space bound applying only as an overflow
  safety net. A 10 MB world on a 1 TB drive must not be blocked at 9% free; a 500 GB world
  must not start at 11% free only to trip an emergency shutdown.
- While tripped: Start and Backup are blocked for *every* world — the one world-agnostic
  lock, because disk space is a shared host resource. Cleanup is *triggered* by this
  condition, never blocked by it; emergency stop remains always allowed.

### 1.3 Cleanup scope lock (per-scope, blocking, single-flight)

- Scope: `backups` or `stale_worlds` (or a specific world's cleanup, if world-scoped).
- A second Cleanup request against the same scope while one runs is queued single-flight
  (per §6) — waits and auto-dispatches when the in-flight Cleanup reaches a terminal state.
  Guarantees one Cleanup per scope at a time; does not reject additional requests.

### 1.4 Config version lock (per-row, optimistic, non-blocking)

- Scope: one row in any multi-editor-reachable configuration table.
- **Not** a blocking lock — nobody waits. Detects simultaneous edits and rejects instead of
  silently overwriting. Full treatment in §4.

## 2. What Is *Not* Separately Lockable (and why)

- **Filesystem locks are not a domain-model concept.** BackupService's "pause autosave via
  RCON, wait for acknowledgement, then capture" sequence *is* the domain-level equivalent of
  a filesystem lock — guarantees the world isn't writing to its save files during capture
  without an OS-level file lock. Platform-adapter implementation detail below this
  document's line.
- **RuntimeSession is not separately lockable** — the partial unique index (`world_id WHERE
  ended_at IS NULL`, Doc 7) already makes "one open session per world" a database-enforced
  invariant, stronger than an application lock.
- **Notifications and audit records are never lock targets** — insert-only from every
  writer's perspective, so nothing to conflict over.

## 3. Full Mutual-Exclusion Matrix

### 3.1 World-scoped operations (same world)

| | Backup running | Restore running | Cleanup running | Start/Stop/Kill |
|---|---|---|---|---|
| **Backup requested** | queue (single-flight, idempotency-key reuse) | reject until restore finishes | reject until cleanup finishes | independent — a running world can be backed up; Stop is queued behind the backup, not blocked |
| **Restore requested** | reject until backup finishes | queue (single-flight, §6) — auto-dispatches when in-flight Restore reaches terminal; world must still be `off` at dispatch | reject until cleanup finishes | rejected outright — world must already be `off`, checked before an Operation is created |
| **Cleanup requested (this world's scope)** | reject until backup finishes | reject until restore finishes | queue (single-flight per scope, §1.3/§6) — auto-dispatches when in-flight Cleanup reaches terminal | not affected |
| **DeleteWorld requested** | reject — world must be `off` and idle | reject | reject | requires `off`; Start/Stop/Kill mid-`DeleteWorld` rejected by the world lock (§1.1) |
| **RenameWorld requested** (display_name edit only — a `ConfigEdit`) | **allowed concurrently** — metadata-only, no files/process touched, paths keyed by immutable `world_id` not `display_name` | allowed concurrently | allowed concurrently | allowed concurrently |
| **Runtime config edit requested** (Java runtime, launch args, port — see §5) | rejected while world is anything but `off` — precondition failure, not queue-and-wait | rejected unless `off` | rejected unless `off` | rejected unless `off` |

### 3.2 Priority ordering when multiple *want* to run (contextual, not a fixed hierarchy)

- User-initiated (manual) operations outrank scheduled/automatic ones — an urgent manual
  restore must not be blocked behind a routine scheduled backup.
- Safety-critical operations (emergency cleanup, emergency stop) outrank all routine
  operations — a cleanup that prevents a crash outranks a scheduled backup.
- Absent a manual or safety-critical reason, backup-over-restore-over-cleanup remains the
  default tie-breaker.
- Enforced through the queue ordering in §6 (waiting Operations ordered by this rule when
  dispatched), not by services side-checking for an in-flight Backup.

### 3.3 Scheduler vs. concurrent config edit

- SchedulerService does not hold a lock on the Schedule row between "this is due" and
  "dispatch the Operation." It re-reads the Schedule immediately before dispatch, never
  from a cached tick-start snapshot. A concurrent disable/delete in that window is caught
  by the re-read; dispatch is skipped — worst case one tick is skipped and the next picks
  up the new state. No blocking lock needed: the window is short and a missed tick is not a
  missed *run* (missed-run detection is a separate, deliberate mechanism).

## 4. Optimistic Concurrency, Generalized

`version`-based optimistic locking is the standing rule for **every** multi-admin-editable
configuration entity:

| Table | Has `version`? |
|---|---|
| `schedules` | Yes |
| `cleanup_policies` | Yes |
| `global_settings` | Yes |
| `world_settings` | Yes |
| `templates` | Yes |
| `roles` | Yes |
| `sync_targets` | Yes |
| `world_instances` (metadata fields only — `display_name`, not runtime state) | Yes — scoped to `ConfigEdit`-driven fields only, not the operational state-machine fields |

Rule (applies uniformly): every `ConfigEdit` Operation submits the `version` the editor
last read. `ConfigurationService` compares at write time. Mismatch → rejected with a
conflict error; the editor re-fetches and reapplies — never silently overwritten.

`permissions` and `role_assignments` are deliberately **excluded** — single-field
grant/revoke rows, not multi-field documents edited in place; the grant/revoke action is
already atomic.

## 5. Runtime Configuration Change Rule

- Java runtime, launch arguments, and port are editable **only while the world is `off`.**
  Any other state → rejected at the precondition check, before a `ConfigEdit` Operation is
  created — a hard precondition, not a queued/deferred edit.
- The edit takes effect **immediately** in the stored `world_instances` row — no "pending"
  state, it is just a configuration write.
- The *running world process* only reads this configuration **at boot** (the next `Start`),
  captured in that `RuntimeSession`'s `launch_args_snapshot` — editing the live row never
  reaches back into an already-running process.
- Net effect: "changes apply immediately" and "changes require the world to be off" are
  not in tension — the write is immediate, the *effect* is deferred to next boot by
  construction, since nothing but boot ever reads the config.

## 6. Queue / Reject / Preempt — one authoritative table

| Operation Type | On duplicate/conflicting trigger |
|---|---|
| Start | Ignored — subsequent triggers no-op until state returns to `off` (10s cooldown additionally prevents rapid re-trigger) |
| Stop | Always allowed, idempotent — safe to call repeatedly; button disables once not `running` |
| Kill | Allowed as explicit escalation over a `Stop` in flight — the only case where one Operation type acts on a world already mid-Operation, because Kill exists to interrupt a stuck Stop. **Supersession semantics (keeps the derived lock query unambiguous):** dispatching Kill atomically (1) transitions the in-flight `Stop` to `Cancelled` with `error_code = 'superseded_by_kill'` — the single exception to "nothing is cancellable once `Running`" — and (2) creates the `Kill` Operation as the *only* in-flight Operation for the world. The derived lock (§1.1) always sees exactly one non-terminal row per world; Kill and Stop never coexist non-terminal |
| Backup | Queued (single-flight, idempotency-key reuse) — never rejected outright |
| Restore | Queued (single-flight) — auto-dispatches when the in-flight Restore reaches terminal; off-only precondition must still hold at dispatch |
| Cleanup | Queued (single-flight per scope) — auto-dispatches when the in-flight Cleanup reaches terminal |
| Sync | Queued per artifact (single-flight per artifact); independently cancellable even mid-`Running` |
| ConfigEdit | Rejected on stale `version` (§4) — never queued, never silently applied |
| CreateWorld | N/A — no existing row to conflict with; port/addressing uniqueness is the only collision surface, checked at validation |
| DeleteWorld | Rejected if world isn't `off` or has any in-flight Backup/Restore/Cleanup (§3.1) |
| Restore vs. DeleteWorld (both queued, same world) | **Restoration wins over deletion** — a queued DeleteWorld is preempted (auto-cancelled) by a subsequently queued Restore for the same world; restore-to-viable-state is the higher-value operation; DeleteWorld may be re-issued after Restore completes. Both off-only, so this only applies while the world is `off` and both wait in the queue — never forces a running world into a state change |
| CrashDetected | N/A — system-observed, not triggered, cannot itself conflict |
