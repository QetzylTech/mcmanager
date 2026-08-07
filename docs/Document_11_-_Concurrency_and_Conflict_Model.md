Document 11: Concurrency, Locking & Conflict Resolution Model

Purpose
- Closes the single largest design gap identified in the full-project review: the system has rich per-Operation-type conflict rules (Doc 8 §7) but no single, explicit model answering what is lockable, how conflicts are detected, and what happens when they occur.
- This document is the authoritative answer. Doc 8 §7's matrix is subsumed into and superseded by §3 below where they differ.
- Scope: every resource in the system that more than one actor (user, background job, or another Operation) could touch simultaneously.

1. Lock Taxonomy

Four distinct lock classes exist. None of them are literal database row locks — SQLite's own locking is a mechanism, not a domain concept — these are *application-level* locks enforced by the services in Doc 8, backed by the state already in Doc 7's schema.

1.1 World lock (per-world, blocking)
- Scope: one `world_id`.
- Held by: whichever of Start/Stop/Kill/Backup/Restore/Cleanup/DeleteWorld currently has an in-flight Operation against that world.
- Mechanism: the lock is **derived, not stored** — "does an in-flight Operation exist for this world?" is a query over `operations`: `operations.world_id = ? AND operations.status IN ('Created','Queued','Validating','Running')`, backed by the `(world_id, status)` index (Doc 7 §2.9). A second Operation targeting the same world runs this query as its first precondition. This requires no separate lock table and no lock column on `world_instances` — the previously planned `current_operation_id` column was removed from Doc 7 to avoid a circular FK with `operations.world_id` (Doc 7 §4).
- Race note: because the lock is a status query rather than a column, the acquire step must be a single transaction — INSERT the new Operation row and re-check that no non-terminal Operation exists for the world in the same transaction. The `(world_id, status)` index plus SQLite's serialized writes make this atomic; a second concurrent acquire inserts after the first and immediately sees a non-terminal row, satisfying the mutual-exclusion guarantee.
- Not reentrant: an Operation cannot be nested inside another Operation on the same world. Compensating actions (e.g. an automatic restore-revert) are new Operations that wait for the original to reach a terminal state first, per Doc 6 §2.4.

1.2 Global storage lock (system-wide, blocking)
- Scope: the entire host.
- Held implicitly whenever the storage guard is tripped — this isn't a lock anyone acquires and releases, it's a standing precondition re-checked by every Operation type that writes to disk (Start, Backup, Restore, Sync).
- The guard is **contextual, not a flat percentage**: it compares the estimated size of the job being written (world, backup artifact, restore target) against available free space minus a configurable absolute reserve (default 10 GB), with a 10% free-space bound applying only as an overflow safety net. A 10 MB world on a 1 TB drive must not be blocked at 9% free, and a 500 GB world must not be allowed to start at 11% free only to immediately trip an emergency shutdown.
- While tripped: Start and Backup are blocked for *every* world, not just the one being acted on (Doc 1 §2/§3). This is the one lock in the system that is world-agnostic by design, because disk space is a shared host resource. Cleanup is what's *triggered* by this condition, never blocked by it; emergency stop remains always allowed.

1.3 Cleanup scope lock (per-scope, blocking, single-flight)
- Scope: `backups` or `stale_worlds` (or a specific world's cleanup, if world-scoped).
- A second Cleanup request against the same scope while one is running is queued single-flight (per §6) — it waits and auto-dispatches when the in-flight Cleanup reaches a terminal state. The lock guarantees only one Cleanup executes per scope at a time; it does not reject additional requests. (Amends the earlier "rejected outright" wording of Doc 8 §7.)

1.4 Config version lock (per-row, optimistic, non-blocking)
- Scope: one row in any multi-editor-reachable configuration table.
- This is **not** a blocking lock — nobody waits. It's how simultaneous edits by different admins get detected and rejected instead of silently overwritten. Full treatment in §4.

2. What Is *Not* Separately Lockable (and why)

- **Filesystem locks are not a domain-model concept.** BackupService's "pause autosave via RCON, wait for acknowledgement, then capture" sequence (Doc 8 §4.2) *is* the domain-level equivalent of a filesystem lock — it guarantees the world isn't writing to its save files during capture without needing an OS-level file lock. This is a platform-adapter implementation detail below the line this document draws.
- **RuntimeSession is not separately lockable** — the partial unique index (`world_id WHERE ended_at IS NULL`, Doc 7 §2.8) already makes "one open session per world" a database-enforced invariant, which is a stronger guarantee than an application lock would give.
- **Notifications and audit records are never lock targets** — they're insert-only from every writer's perspective (Doc 6 Tier 1), so there's nothing to conflict over.

3. Full Mutual-Exclusion Matrix (supersedes Doc 8 §7)

3.1 World-scoped operations (same world)

| | Backup running | Restore running | Cleanup running | Start/Stop/Kill |
|---|---|---|---|---|
| **Backup requested** | queue (single-flight, idempotency-key reuse) | reject until restore finishes | reject until cleanup finishes | independent — a running world can be backed up; Stop is queued behind the backup, not blocked |
| **Restore requested** | reject until backup finishes | queue (single-flight, §6) — auto-dispatches when the in-flight Restore reaches a terminal state; world must still be `off` at dispatch | reject until cleanup finishes | rejected outright — world must already be `off`, checked before an Operation is even created |
| **Cleanup requested (this world's scope)** | reject until backup finishes | reject until restore finishes | queue (single-flight per scope, §1.3/§6) — auto-dispatches when the in-flight Cleanup reaches a terminal state | not affected |
| **DeleteWorld requested** | reject — world must be `off` and idle | reject | reject | requires `off`; Start/Stop/Kill against a world mid-`DeleteWorld` are rejected by the world lock (§1.1) |
| **RenameWorld requested** (display_name edit only — a `ConfigEdit`) | **allowed concurrently** — renaming is metadata-only, doesn't touch files or the process, world paths are keyed by immutable `world_id` not `display_name` | allowed concurrently | allowed concurrently | allowed concurrently |
| **Runtime config edit requested** (Java runtime, launch args, port — see §5) | rejected while world is anything but `off` — this is a precondition failure, not a queue-and-wait | rejected unless `off` | rejected unless `off` | rejected unless `off` |

3.2 Priority ordering when multiple *want* to run (contextual, not a fixed hierarchy)
- The legacy "Backup > Restore > Cleanup" rule (Doc 1 §14) is superseded by contextual priority, applied when multiple Operations wait for the same lock/queue:
  - User-initiated (manual) operations outrank scheduled/automatic ones — an urgent manual restore must not be blocked behind a routine scheduled backup.
  - Safety-critical operations (emergency cleanup, emergency stop) outrank all routine operations — a cleanup that prevents a crash outranks a scheduled backup.
  - Absent a manual or safety-critical reason, the legacy backup-over-restore-over-cleanup ordering still applies as the default tie-breaker.
- Enforced through the queue ordering in §6 (waiting Operations are ordered by this rule when dispatched) rather than by each service side-checking for an in-flight Backup.

3.3 Scheduler vs. concurrent config edit
- SchedulerService does not hold a lock on the Schedule row between "this is due" and "dispatch the Operation." Instead it re-reads the Schedule immediately before dispatch, not from a cached tick-start snapshot. If a concurrent edit disabled or deleted the Schedule in that (sub-second) window, the re-read catches it and the dispatch is skipped — worst case, one tick's dispatch is skipped and the next tick picks up the new state correctly. No blocking lock is needed because the window is short and the cost of a missed tick is zero (it's not a missed *run* — see Doc 6 §2.6.1, missed-run detection is a separate, deliberate mechanism for actual due-and-skipped occurrences).

4. Optimistic Concurrency, Generalized (resolves "last save wins")

Doc 6 previously defined `version`-based optimistic locking only for `schedules` and `cleanup_policies`. That pattern is now the standing rule for **every** multi-admin-editable configuration entity:

| Table | Has `version`? |
|---|---|
| `schedules` | Yes |
| `cleanup_policies` | Yes |
| `global_settings` | Yes |
| `world_settings` | Yes |
| `templates` | Yes |
| `roles` | Yes |
| `sync_targets` | Yes |
| `world_instances` (metadata fields only — `display_name`, not runtime state) | Yes — scoped to the `ConfigEdit`-driven fields only, not the operational state machine fields |

Rule (applies uniformly): every `ConfigEdit` Operation submits the `version` the editor last read alongside the change. `ConfigurationService` compares it to the current `version` at write time. If they don't match, the write is rejected with a conflict error — the editor is told someone else changed it since they loaded it, and must re-fetch and reapply, not silently overwritten. This closes exactly the "Admin A / Admin B" scenario raised in the review, for every entity in that table, not just schedules.

`permissions` and `role_assignments` are deliberately **excluded** from this table — they're single-field grant/revoke rows (Doc 6 §2.16), not multi-field documents an admin edits in place, so there's nothing meaningful to "conflict" on beyond the grant/revoke action itself, which is already atomic.

5. Runtime Configuration Change Rule (resolves the ambiguity raised)

- Java runtime, launch arguments, and port are editable **only while the world is `off`.** Any edit attempt while the world is in any other state is rejected at the precondition check, before a `ConfigEdit` Operation is even created — this is a hard precondition, not a queued or deferred edit.
- The edit itself takes effect **immediately** in the stored `world_instances` row — there's no separate "pending" state, because it's just a configuration write.
- The *running world process* only ever reads this configuration **at boot** (the next `Start`). A world that's already running was launched with whatever configuration existed at its last `Start`, captured in that `RuntimeSession`'s `launch_args_snapshot` (Doc 6 §1.2) — editing the live `world_instances` row never reaches back into an already-running process.
- Net effect: "changes apply immediately" and "changes require the world to be off" are not in tension — the write is immediate, the *effect* is deferred to next boot by construction, since nothing but boot ever reads the config.

6. Queue / Reject / Preempt — one authoritative table

| Operation Type | On duplicate/conflicting trigger |
|---|---|
| Start | Ignored — subsequent triggers no-op until state returns to `off` (10s cooldown additionally prevents rapid re-trigger) |
| Stop | Always allowed, idempotent — safe to call repeatedly, button just disables once not `running` |
| Kill | Allowed as an explicit escalation over a `Stop` already in flight — the only case in the system where one Operation type is allowed to act on a world already mid-Operation, because Kill exists specifically to interrupt a stuck Stop. **Supersession semantics (keeps the derived lock query unambiguous):** dispatching Kill atomically (1) transitions the in-flight `Stop` to `Cancelled` with `error_code = 'superseded_by_kill'` — the single documented exception to the general rule that nothing is cancellable once `Running` (Doc 6 §2.4, Doc 8 §6) — and (2) creates the `Kill` Operation, which becomes the *only* in-flight Operation for the world. The derived world lock (§1.1) therefore always sees exactly one non-terminal row per world; Kill and Stop never coexist in a non-terminal state. |
| Backup | Queued (single-flight, idempotency-key reuse) — never rejected outright |
| Restore | Queued (single-flight) — auto-dispatches when the in-flight Restore reaches a terminal state; the world must still satisfy the off-only precondition at dispatch time |
| Cleanup | Queued (single-flight per scope) — auto-dispatches when the in-flight Cleanup reaches a terminal state |
| Sync | Queued per artifact (single-flight per artifact); independently cancellable even mid-`Running` (Doc 8 §6 exception) |
| ConfigEdit | Rejected on stale `version` (§4) — never queued, never silently applied |
| CreateWorld | N/A — no existing row to conflict with; port/addressing uniqueness is the only collision surface, checked at validation |
| DeleteWorld | Rejected if world isn't `off` or has any in-flight Backup/Restore/Cleanup (§3.1) |
| CrashDetected | N/A — system-observed, not triggered, cannot itself conflict |

7. Traceability

| Element | Traces to |
|---|---|
| World lock derived from in-flight `operations` query | Doc 7 §4 (derived lock, acyclic FK graph), Doc 7 §2.9 (`(world_id, status)` index) |
| Global storage lock | Doc 1 §2/§3, Doc 2 §11.2 |
| Cleanup scope single-flight | Doc 8 §7 (queued single-flight rather than rejected outright, per §1.3/§6) |
| Scheduler re-read-before-dispatch | Closes the "change schedule while scheduler is evaluating" question from the project review |
| RenameWorld allowed concurrently with Backup/Restore/Cleanup | Closes the "Rename World + Backup" question from the project review |
| Runtime config only-when-off, immediate write / deferred effect | Product decision |
| `version` generalized to every multi-admin-editable table | Closes the "Admin A / Admin B" multi-user-edit question from the project review |
| Queue/reject/preempt table | Consolidates Doc 1 §14, Doc 8 §6/§7 into one place |
