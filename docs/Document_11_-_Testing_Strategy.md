# Document 11: Testing Strategy

Test pyramid, ISO/IEC 25010 mapping, acceptance testing, and verification gating.

## 1 Test pyramid

```
      E2E (UI + API + real process)        ~5%
     Integration (services + SQLite + adapters)  ~25%
    Unit (domain + services, no I/O)      ~70%
```

### 1.1 Unit (~70%)

Scope:
- Domain model: every lifecycle transition in Doc 6 (WorldInstance, Operation, RuntimeSession, SyncRecord/SyncAttempt, Schedule/MissedRunRecord, Notification read/dismiss, User lockout, Manager lifecycle).
- Business invariants (Doc 6): one-open-session-per-world (schema-enforced, but service-level duplicates must be rejected before reaching DB); `pre_backup_state` resolution; error/crashed never auto-clear; last-Superadmin guard; retention-floor guards; SyncRecord status derivation; MissedRunRecord terminal transitions; permission dual-attachment CHECK.
- Pure service logic with repository/port fakes: no filesystem, no real process, no network. Services use injected port interfaces; fakes live in the test package.

Rules:
- No real I/O / real SQLite `:memory:` dependency where avoidable — but SQLite `:memory:` allowed for SQL-string unit tests when it makes a test materially more truthful; prefer port fakes for behavior tests.
- Deterministic clocks: injectable `Clock` port (epoch-seconds source) so timeout/cooldown/step-up-window tests are fast and race-free.

### 1.2 Integration (~25%)

Scope:
- Services against real SQLite (in-memory or temp-file per run) with `PRAGMA foreign_keys = ON` (ARCHITECTURE invariant) + full Doc 7 schema.
- Migration path: apply `schema_migrations` 0→latest in one test; verify `PRAGMA foreign_key_check` passes.
- Every Operation type end-to-end service flow against the schema: CreateWorld, Start, Stop, Kill, Backup, Restore, Cleanup, Sync, ConfigEdit, CrashDetected, DeleteWorld (Doc 8) with correct rows created (operations, backup_artifacts, runtime_sessions, restore_history, sync_records, sync_attempts, audit_records).
- Concurrency matrix (Doc 9): full mutual-exclusion matrix as parametrized tests — each cell (requested op × in-flight op) asserts queue/reject/ignore exactly per the table.
- Optimistic locking (Doc 9): stale-`version` writes rejected for every table in the version list (not just schedules).
- Tick-to-Operation: SchedulerService against SQLite with injected clock — due dispatch, missed-run detection, re-read-before-dispatch behavior, disabled/deleted schedule window.
- Restore checkpointing: interrupt restore at each stage (validate/pre-backup/stage/archive/switch/record); assert known state (Doc 8 failure recovery).
- Audit coverage: for each op type + audit-triggering event (Doc 8), exactly the documented audit rows created; `annotation_of` corrections; snapshot immutability (rename user → old audit rows unchanged).
- Storage guard (Doc 9): contextual reserve math, emergency-stop never blocked, cleanup never blocked.
- Global Deletion & Retention Model: no code path except CleanupService ever physical-deletes (static test: grep for `DELETE FROM` outside cleanup package — enforced at review too); Tier 1 tables never have `deleted_at` written.
- Minecraft adaptation (Doc 14): capability-schema tests (every declared capability cell has an implementation or explicit `none`); EULA state-machine tests (`not_present -> unaccepted -> accepted`, Start rejected while `eula_required`, external `eula.txt` revert re-gates); Java-compatibility matrix validation; `server.properties` schema tests per curated version (key accepted/obsolete/unknown, `replaced_by_gamerule` hints); save-coordination edge tests (each Doc 14 §10 bullet: RCON loss mid-backup, `save-off`-ok-`save-all`-fails, manager crash between `save-off`/`save-on` with boot recovery); backup integrity tests (interrupt leaves only `.part`, checksum mismatch blocks restore, structural failure flags `suspect`); restore rollback decision-tree tests (failed post-restore startup → automatic compensating rollback; rollback failure leaves `error`).
- SQLite operational contract (Doc 7 §10): WAL + busy_timeout + writer/reader split held under concurrent load; `SQLITE_BUSY` mapped, never raw 500; ManagerBackup uses SQLite backup API (assert consistent snapshot while writes in flight — plain `.db` copy of live DB is a test failure); secrets rows ciphertext at rest (assert no `secrets.encrypted_value` contains known plaintext).
- Security contract (Doc 8 §9): Argon2id used (assert hash prefix, no raw SHA/bcrypt-md5); session-ID rotation after login/elevation/password change (old revoked, new issued); HTTPS-mandatory for non-loopback; security headers present; secrets never in any response serialization.
- SSE delivery semantics (Doc 10): at-least-once reconnect replay within window; ordering per stream; replay-past-window → snapshot + rehydration; duplicate event application idempotent.

- `VERBOSE_LOGGING`: unit and integration suites verify `false` suppresses debug and filters raw Minecraft noise without breaking readiness parsing; `true` retains all canonical channels.
- Write-amplification benchmark: intermediate checkpoints produce no audit rows and no operation writes beyond creation, `Running`, and terminal milestones.

### 1.3 E2E (~5%)

Scope:
- Real HTTP server (Flask test client or bound localhost) + real filesystem sandbox + real `java` only if available; otherwise fake executable behaving like a Minecraft server (Doc 13 test double).
- UI smoke: shell API flows — login, rehydrate snapshot, start world, live log line arrival, stop world.
- SSE: connect, receive `snapshot`, assert subsequent events; reconnect with `Last-Event-ID` replays buffered events.
- Crash-to-notification E2E: kill fake server process mid-run → world.state `crashed`, CrashDetected Operation, notification, audit record.

E2E intentionally thin/slow; one or two canonical flow suites per release, not a regression workhorse. Most coverage lives in §1.1/§1.2.

## 2 ISO/IEC 25010 mapping

Every characteristic maps to a concrete, gated verification. Mandatory: a change touching a listed behavior must carry the corresponding test.

| Characteristic | Product behavior | How tested | Gate |
|---|---|---|---|
| **Functional suitability** | Operation preconditions, lifecycle state machines, conflict matrix, retention floors, permission model (Doc 6, Doc 9) | Unit §1.1 + integration matrix §1.2; every op type has happy-path + rejected-path test | All pass before merge |
| **Performance efficiency** | Idle CPU below documented threshold (5-min window); baseline memory range; leader-tab stream sharing and reduced operation/audit writes (Doc 10) | Benchmark suite vs reference-hardware profile: idle 5-min CPU avg, RSS baseline, multi-tab one-SSE fan-out, 1000 log lines/sec ingestion, terminal-only audit write volume | Benchmark regression vs documented baseline fails release (§4.2) |
| **Compatibility** | Runs on each supported OS; adapters replaceable (Doc 12, Doc 13) | Adapter conformance suite (Doc 13) on every supported OS in CI; storage/backend-agnostic core never imports platform code | Full suite green on ≥2 OSes for release |
| **Interaction capability** | Shell rehydration, BroadcastChannel multi-tab sharing, offline/reconnect, queue-position surfacing (Doc 10) | E2E SSE suite: reconnect replay, dual-tab single leader connection, leader-election failover, blank-state prohibition asserted on connect | E2E suite green |
| **Reliability** | Startup reconciliation, restart-safe ops, restore checkpointing, crash detection (Doc 7 §6, Doc 8) | Integration: reconciliation scenarios (§1.2), kill-mid-restore at every stage, process-exit-mid-backup, kill-supersedes-stop atomicity | All pass before merge |
| **Security** | Zero-trust authn/authz, step-up windows, secret isolation, throttle/lockout, CSRF, audit immutability (Doc 6) | Dedicated security suite: auth bypass (direct route calls without session), role escalation (Client calling SA routes), CSRF missing token, step-up expiry, throttle lockout, secrets not in any response, audit immutability (UPDATE/DELETE on audit tables fails) | All pass before merge; security suite = own CI job |
| **Maintainability** | Modular ports/adapters, no platform imports in core, service boundaries (Doc 8, Doc 12) | Static analysis gate: `ports/` boundaries, circular-import checker, lint + format + type gates (§3.2); design-structure tests assert core imports no adapter packages | Static gate green |
| **Flexibility** | OS/runtime/storage adapters swappable; split deployment topologies | Adapter conformance suite runs same tests against every adapter; deployment smoke: single-process + split web/worker boots | Conformance green per adapter |
| **Safety** | Fail-closed destructive ops, scope preview, blast-radius cap, emergency stop always allowed (Doc 9) | Integration: destructive-op guards (DeleteWorld, Cleanup wet, Kill, file delete) require step-up + preview; emergency stop during storage-guard trip succeeds; cleanup never deletes last viable artifact | All pass before merge |

## 3 Tooling & test standards

### 3.1 Framework
- `pytest` single runner for unit/integration/E2E. No second framework.
- Coverage: `pytest-cov`; per-module floor 80% line, overall floor 85%. Exceptions (arg-parsing shims, generated code) in explicit `# pragma: no cover` allowlist — never blanket-excluded.
- SQLite tests: one shared fixture building Doc 7 schema + applying migrations; every test in its own rolled-back or fresh DB.

### 3.2 Coding standards interaction
- The Document 12-locked tools (ruff, mypy, black, isort) run in CI and block merge on violation. Tests subject to the same lint gate as production code.
- Type-checking of tests required (mypy) — untyped tests drift fastest.
- No `try/except` swallowing in tests: assert the intended error, never pass because an exception was hidden.

### 3.3 Test data & fixtures
- Factories (not raw INSERT literals) for every aggregate: world, operation, session, artifact, sync record, user, role, permission, device, schedule, cleanup policy, notification, audit record.
- Factory defaults valid per Doc 7 constraints so tests fail on product bugs, not fixture bugs.
- Seed closed enums from Doc 6 / Doc 10: world states, op types, backup categories, notification severities, sync outcomes, end reasons — a test using a value outside a closed set is a product-contract test failure.

## 4 Acceptance testing

### 4.1 Functional acceptance

| Acceptance criterion | Executable check |
|---|---|
| Manages multiple worlds concurrently without cross-world interference | Integration: 3 worlds running/backed-up/restored in parallel; per-world locks never block unrelated worlds; crash in world A leaves B/C running and unblocked |
| Runs on >1 OS without redesigning the core control model | Adapter conformance suite green on ≥2 supported OSes (Doc 13) |
| Preserves operational strengths (start/stop/backup/restore/cleanup/live logs/setup/audit) | E2E canonical flows for each strength (Doc 5 pages reachable and functional) |
| Improves reliability, observability, portability, maintainability | §2 gates: reliability tests, SSE/observability E2E, adapter conformance, static boundary gate |
| Lightweight on modest hardware | §4.2 performance acceptance |

Failure criteria are the negation: the matching test **must fail** if the product still (a) depends on Linux service-manager assumptions, (b) cannot isolate worlds, (c) loses auditability/defensive protections, or (d) becomes too heavy — enforced by the adapter conformance suite (no `systemd`/`journalctl` in the adapter-neutral path), cross-world independence tests, audit-immutability suite, and performance benchmarks respectively. A specific structural test asserts the control-plane code imports no `systemd`/`journalctl`/`subprocess`-based platform module (Doc 13 guards this).

### 4.2 Performance acceptance (reference hardware)
- Reference profile documented (CPU model, core count, RAM, storage type) before any benchmark — repeatable method, not informal observation.
- Benchmarks (scripted, repeatable):
  - Idle: 5-min avg CPU (no state changes/backups/restores/active streams) < documented threshold; baseline RSS within documented range.
  - Stream fan-out: 50 concurrent SSE clients receiving 1Hz metric updates without per-client recomputation (CPU flat with client count proves compute-once).
  - Log ingestion: 1000 lines/sec through world-log pipeline with ≤ documented tail latency.
- Thresholds in a single `benchmarks/thresholds.json` — hardware change updates numbers, not code.

### 4.3 Release gate

A release candidate ships only when:
1. Unit + integration + E2E suites green on CI matrix (≥2 OSes where the adapter suite applies).
2. Security suite green (own CI job).
3. Performance benchmarks within documented thresholds.
4. Static gate green (lint, format, types, boundary/import checks).
5. `PRAGMA foreign_key_check` sweep in the production-style migration test passes.
6. No open `Critical` or `High` defect against the acceptance criteria in §4.
