# Document 13: Testing Strategy

Scope: the testing approach for the manager — test pyramid, ISO/IEC 25010 quality-
characteristic mapping, acceptance testing, and the verification gating that applies
before release.

## 1. Test Pyramid

```
         /  E2E (UI + API + real process)      ~5%
        /  Integration (services + SQLite + adapters)  ~25%
       /   Unit (domain + services, no I/O)   ~70%
```

### 1.1 Unit tests (~70%)

Scope:
- Domain model: every lifecycle transition in Doc 6 (WorldInstance, Operation,
  RuntimeSession, SyncRecord/SyncAttempt, Schedule/MissedRunRecord, Notification
  read/dismiss, User lockout, Manager lifecycle).
- Business invariants (Doc 6): one-open-session-per-world is schema-enforced, but
  service-level duplicates must be rejected before reaching the DB; `pre_backup_state`
  resolution; error/crashed never auto-clear; last-Superadmin guard; retention-floor
  guards; SyncRecord status derivation; MissedRunRecord terminal transitions; permission
  dual-attachment CHECK.
- Pure service logic with repository/port fakes: no filesystem, no real process, no
  network. Services use injected port interfaces; fakes live in the test package.

Rules:
- No real I/O, no real SQLite `:memory:` dependency at this layer where avoidable — but
  SQLite `:memory:` is allowed for SQL-string unit tests when it makes a test materially
  more truthful; prefer port fakes for behavior tests.
- Deterministic clocks: pass a `Clock` port (injectable epoch-seconds source) so
  timeout/cooldown/step-up-window tests are fast and race-free.

### 1.2 Integration tests (~25%)

Scope:
- Services against real SQLite (in-memory or temp-file per test run) with
  `PRAGMA foreign_keys = ON` (ARCHITECTURE.md invariant) and the full schema from Doc 7.
- Migration path: apply `schema_migrations` from 0 to latest in one test; verify
  `PRAGMA foreign_key_check` passes.
- Every Operation type end-to-end service flow against the schema: CreateWorld, Start,
  Stop, Kill, Backup, Restore, Cleanup, Sync, ConfigEdit, CrashDetected, DeleteWorld
  (Doc 8) with correct rows created (operations, backup_artifacts, runtime_sessions,
  restore_history, sync_records, sync_attempts, audit_records).
- Concurrency matrix (Document 11): the full mutual-exclusion matrix as parametrized
  tests — each cell (requested op × in-flight op) asserts queue/reject/ignore exactly per
  the table.
- Optimistic locking (Document 11): stale-`version` writes rejected for every table in the
  version list (not just schedules).
- Tick-to-Operation: SchedulerService against SQLite with injected clock — due dispatch,
  missed-run detection, re-read-before-dispatch behavior, disabled/deleted schedule window.
- Restore checkpointing: interrupt restore at each stage (validate/pre-backup/stage/
  archive/switch/record) and assert the system leaves a known state (Doc 8 failure
  recovery).
- Audit coverage: for each operation type and each audit-triggering event (Doc 8), exactly
  the documented audit rows are created; `annotation_of` corrections; snapshot immutability
  (rename user → old audit rows unchanged).
- Storage guard (Document 11): contextual reserve math, emergency-stop never blocked,
  cleanup never blocked.
- Global Deletion & Retention Model: verify no code path except CleanupService ever
  physical-deletes (static test: grep for `DELETE FROM` outside the cleanup package —
  enforced at review too); Tier 1 tables never have `deleted_at` written.

### 1.3 End-to-end tests (~5%)

Scope:
- Real HTTP server (Flask test client or bound localhost) + real filesystem sandbox + real
  `java` only if available; otherwise a fake executable that behaves like a Minecraft
  server (see Document 15 test double) for process-control E2E.
- UI smoke: the shell's API flows — login, rehydrate snapshot, start world, live log line
  arrival, stop world.
- SSE: connect, receive `snapshot`, assert subsequent events; reconnect with
  `Last-Event-ID` replays buffered events.
- Crash-to-notification E2E: kill the fake server process mid-run → world.state `crashed`,
  CrashDetected Operation, notification, audit record.

E2E is intentionally thin and slow; one or two canonical flow suites per release, not a
regression workhorse. Most coverage lives in §1.1/§1.2.

## 2. ISO/IEC 25010 Characteristic Mapping

Every quality characteristic maps to a concrete, gated verification. Mandatory: a change
that touches a behavior listed below must carry the corresponding test.

| Characteristic (ISO/IEC 25010) | Product behavior | How tested | Gate |
|---|---|---|---|
| **Functional suitability** | Operation preconditions, lifecycle state machines, conflict matrix, retention floors, permission model (Doc 6, Document 11) | Unit tests §1.1 + integration matrix §1.2; every operation type has a happy-path + rejected-path test | All must pass before merge |
| **Performance efficiency** | Idle CPU below documented threshold over 5-min window; baseline memory range; stream fan-out without per-client loops (MetricsCadence + broadcast set, Document 12) | Performance benchmark suite against reference-hardware profile: idle 5-min CPU average, RSS baseline, 50 simultaneous SSE clients fan-out, 1000 log lines/sec ingestion | Benchmark regression vs. documented baseline fails the release; see §4.2 |
| **Compatibility** | Runs on each supported OS; adapters replaceable (Document 14, Document 15) | Adapter conformance suite (Document 15) runs on every supported OS in CI; storage/backend-agnostic core never imports platform code | Full suite green on ≥2 OSes for release |
| **Interaction capability** | Shell rehydration, multi-tab independent streams, offline/reconnect, queue-position surfacing (Document 12) | E2E SSE suite: reconnect replay, dual-tab independent streams (no election), blank-state prohibition asserted on connect | E2E suite green |
| **Reliability** | Startup reconciliation, restart-safe operations, restore checkpointing, crash detection (Doc 7 §6, Doc 8) | Integration: reconciliation scenarios (§1.2), kill-mid-restore at every stage, process-exit-mid-backup, kill-supersedes-stop atomicity | All must pass before merge |
| **Security** | Zero-trust authn/authz, step-up windows, secret isolation, throttle/lockout, CSRF, audit immutability (Doc 6) | Dedicated security test suite: auth bypass attempts (direct route calls without session), role escalation (Client calling SA routes), CSRF missing token, step-up expiry, throttle lockout, secrets not in any response serialization, audit immutability (UPDATE/DELETE on audit tables fails) | All must pass before merge; security suite is its own CI job |
| **Maintainability** | Modular ports/adapters, no platform imports in core, service boundaries (Doc 8, Document 14) | Static analysis gate: `ports/` boundaries, circular-import checker, lint + format + type gates (§3.2); design-structure tests assert core imports no adapter packages | Static gate green |
| **Flexibility** | OS/runtime/storage adapters swappable; split deployment topologies | Adapter conformance suite runs the same tests against every adapter implementation; deployment smoke: single-process and split web/worker boots | Conformance suite green per adapter |
| **Safety** | Fail-closed destructive ops, scope preview, blast-radius cap, emergency stop always allowed (Document 11) | Integration: destructive-op guards (DeleteWorld, Cleanup wet, Kill, file delete) require step-up + preview; emergency stop during storage-guard trip succeeds; cleanup never deletes last viable artifact | All must pass before merge |

## 3. Tooling & Test Standards

### 3.1 Framework

- Python: `pytest` as the single test runner for unit/integration/E2E. No second
  framework.
- Coverage: `pytest-cov`; per-module floor 80% line coverage, overall floor 85%.
  Exceptions (argument-parsing shims, generated code) listed in an explicit
  `# pragma: no cover` allowlist — never blanket-excluded.
- SQLite tests: one shared fixture building the Doc 7 schema and applying migrations;
  every test runs in its own rolled-back or fresh DB.

### 3.2 Coding standards interaction

- The Doc 14-locked tools (ruff, mypy, black, isort) run in CI and block merge on
  violation. Tests are subject to the same lint gate as production code.
- Type-checking of tests is required (mypy) — untyped tests drift fastest.
- No `try/except` swallowing in tests: assert the intended error, never pass because an
  exception was hidden.

### 3.3 Test data & fixtures

- Factories (not raw INSERT literals) for every aggregate: world, operation, session,
  artifact, sync record, user, role, permission, device, schedule, cleanup policy,
  notification, audit record.
- Factory defaults must be valid per Doc 7 constraints so tests fail on product bugs, not
  fixture bugs.
- Seed the closed enums from Doc 6 / Document 12: world states, op types, backup
  categories, notification severities, sync outcomes, end reasons — a test that uses a
  value outside the closed set is a product-contract test failure.

## 4. Acceptance Testing

### 4.1 Functional acceptance

| Acceptance criterion | Executable check |
|---|---|
| Manages multiple worlds concurrently without cross-world interference | Integration: 3 worlds running/backed-up/restored in parallel; per-world locks never block unrelated worlds; a crash in world A leaves B/C running and unblocked |
| Runs on more than one OS without redesigning the core control model | Adapter conformance suite green on ≥2 supported OSes (Document 15) |
| Preserves operational strengths (start/stop/backup/restore/cleanup/live logs/setup/audit) | E2E canonical flows for each strength (Doc 5 pages reachable and functional) |
| Improves reliability, observability, portability, maintainability | §2 gates: reliability tests, SSE/observability E2E, adapter conformance, static boundary gate |
| Lightweight on modest hardware | §4.2 performance acceptance |

Failure criteria are the negation: the matching test **must fail** if the product still (a)
depends on Linux service-manager assumptions, (b) cannot isolate worlds, (c) loses
auditability/defensive protections, or (d) becomes too heavy — enforced by the adapter
conformance suite (no `systemd`/`journalctl` anywhere in the adapter-neutral path), the
cross-world independence tests, the audit-immutability suite, and the performance
benchmarks respectively. A specific structural test asserts the control-plane code imports
no `systemd`/`journalctl`/`subprocess`-based platform module (Document 15 guards this).

### 4.2 Performance acceptance (reference hardware)

- Reference profile must be documented (CPU model, core count, RAM, storage type) before
  any benchmark is run — a repeatable method, not informal observation.
- Benchmarks (scripted, repeatable):
  - Idle: 5-minute average CPU (no state changes/backups/restores/active streams) <
    documented threshold; baseline RSS within documented range.
  - Stream fan-out: 50 concurrent SSE clients receiving 1Hz metric updates without
    per-client recomputation (CPU flat with client count proves compute-once).
  - Log ingestion: 1000 lines/sec through the world-log pipeline with ≤ documented tail
    latency.
- Thresholds live in a single `benchmarks/thresholds.json` so a hardware change updates
  numbers, not code.

### 4.3 Release gate

A release candidate ships only when:

1. Unit + integration + E2E suites green on CI matrix (≥2 OSes where the adapter suite
   applies).
2. Security suite green (own CI job).
3. Performance benchmarks within documented thresholds.
4. Static gate green (lint, format, types, boundary/import checks).
5. `PRAGMA foreign_key_check` sweep in the production-style migration test passes.
6. No open `Critical` or `High` defect against the acceptance criteria in this section.
