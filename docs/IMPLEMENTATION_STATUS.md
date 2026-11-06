# MCManager Implementation Status

Last verified: 2026-11-06

`docs/` is the product contract. This file records the current implementation
and verification state; passing a gate's focused tests does not mean the whole
product or release gate is complete.

Work-item ownership, dependencies, and current acceptance evidence are tracked
in [WORKBOARD.md](WORKBOARD.md).

## Gate status

| Gate | Status | Verified scope |
|---|---|---|
| 1 - Process and Minecraft adapters | Partial | Port-based Minecraft adapter wiring, process conformance, readiness, and missing-JAR validation. Windows conformance passed; POSIX was not run in this environment. |
| 2 - Persistence and domain | Partial | Domain lifecycle/invariants, effective settings resolution, ConfigEdit operations, and conflict mapping. Schema FK checks remain part of migration verification. |
| 3 - Control plane | Partial | Milestone-only operations, in-memory progress, terminal audit, conflict policy, startup reconciliation, supervisor/scheduler workers, and missed-run recording. |
| 4 - Operational subsystems | Partial | Native ZIP/SHA-256 backup, storage/flush guards, restore rollback, cleanup floors/operations, and sync retry/cap services. |
| 5 - API, streams, and shell | Partial | Session/CSRF/step-up middleware, auth routes, selected world/operation routes, SSE replay/subscription, multi-tab client, and shell navigation. |

Focused Windows verification:

| Command/suite | Result |
|---|---|
| Gates 1-5 acceptance and related regression tests | 125 passed; 1 failed because `benchmarks/thresholds.json` lacks the documented reference-host profile and required CPU/RSS/stream/log thresholds. |
| Gate 1 conformance and Minecraft gate tests | 53 passed. POSIX native conformance still needs a POSIX run. |
| Gate 2 realignment and schema/Phase 4 regressions | 21 passed. |
| Gate 3 acceptance and Gate 1/2 regressions | 61 passed. |
| Gate 4 acceptance and Gate 3 regressions | 35 passed. |
| Gate 5 browser and presentation/auth checks | Passed except for the performance-profile requirement above. |
| `python -m ruff check` on Gate 5 implementation files; `python -m compileall -q app` | Passed. |

The full `python -m pytest -q --no-cov` run is not green: it has the same
unconfigured Gate 5 performance check plus five `test_coverage_smoke.py`
failures. Those smoke cases currently use invalid string enums, missing
foreign-key seed rows, and an unwired diagnostics attribute; they need valid
fixtures and/or a diagnostics implementation before they can be used as full
suite evidence.

## Product scope still incomplete

- The full Document 10 route catalog is not implemented. Auth/session and
  selected world lifecycle/operation routes exist; CRUD and workflows for
  backups/restores, cleanup, sync, schedules, settings, templates/runtimes,
  admin, notifications, audit, files, and logs remain incomplete.
- The command layer exists only in part; most route catalog commands and query
  handlers are still missing.
- The 17 shell modules are navigable without full reloads, but most are still
  scaffold fragments rather than complete Document 4/5 workflows. World
  context selection and complete manager workflows remain open.
- SSE snapshots, replay, and client-side tab sharing are implemented, but the
  complete Document 10 topics, auth-expiry stream behavior, metrics cadence,
  and deployment proxy checks are not demonstrated.
- Runtime supervisor shutdown still needs lifecycle handling; a worker has
  logged an error when tests close the SQLite store before the worker stops.
- Performance release acceptance is blocked until a reference-host profile
  and measurable limits are supplied. Do not invent benchmark numbers.
- Cross-platform release acceptance is incomplete until C1-C14 passes on both
  Windows and POSIX. Full type/import-boundary and release gates also remain;
  no clean import-boundary check result is recorded.

## Run locally

Run the app from the repository root (local manager state and Minecraft
installations are kept in ignored directories under `app/`):

```powershell
python -m flask --app "app:create_app(database_path='app/data/manager.db', keyfile_path='app/data/secrets.key', migrations_dir='migrations')" run --host 127.0.0.1 --port 5000
```

Run tests and development tooling from the repository root; the application
source and migrations are in `app/` and `migrations/`. The application starts,
but it is not yet an operator-ready implementation of all Documents 4-14.
