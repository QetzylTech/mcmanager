# MCManager Implementation Status

Last audited: 2026-08-09

This file tracks what is actually implemented in `core/`, not what the design
docs say should eventually exist. Treat `docs/` as the target contract and this
file as the current build reality.

Legend:

- `Done`: implemented, wired, and covered by tests or a verification artifact.
- `Partial`: some service or test coverage exists, but the user-facing flow is
  incomplete or only works through internal/dev paths.
- `Scaffold`: route/page/module exists mostly as a placeholder.
- `Missing`: planned in docs, not materially implemented.
- `Unknown`: needs a focused audit.

## Summary

| Area | Status | Notes |
|---|---|---|
| Flask app boot | Done | `app:create_app(...)` builds the container, runs migrations, registers shell/API/stream blueprints. |
| SQLite schema/migrations | Done | 27-table schema applies; `audit_verify_out.txt` confirms table count. |
| Web shell/page serving | Partial | The app serves the persistent shell and 17 page slugs, but most pages are skeletal sections. |
| Page APIs | Scaffold | `/api/pages` and `/api/pages/<slug>` return page metadata and limited world summaries. |
| System health/diagnostics | Partial | `/api/health`, `/api/diagnostics`, `/api/system/stats` exist. |
| Auth/session/security | Partial | Service exists and tests exist, but full web middleware/API catalog is not wired. |
| World lifecycle | Partial | Start/Stop/Kill service and dev API routes exist; depends on seeded DB/runtime configuration. |
| Process control adapter | Partial | POSIX/Windows adapters and fake-server conformance tests exist. Real-world production hardening still needs audit. |
| Minecraft pre-launch gate | Done/Partial | EULA, Java compatibility, port, jar, and readiness helpers exist with tests; UI acceptance flow is not fully wired. |
| RCON save coordination | Partial | Service exists for save-off/save-all/save-on; needs end-to-end backup/restore validation. |
| Backup/restore/cleanup | Partial | Service modules and integration tests exist, but app-facing workflows/API/UI are incomplete. |
| Scheduler | Partial | Tick/missed-run service exists; background scheduler startup is not fully app-wired. |
| Realtime/SSE | Partial | Shared SSE primitives/routes exist; full topic contract and UI usage are incomplete. |
| Notifications/audit | Partial | Services and tests exist; full user-facing history/notification workflows are incomplete. |
| Configuration/version conflicts | Partial | `ConfigurationService` implements optimistic update checks; full ConfigEdit command/API/UI coverage is incomplete. |
| Commands layer | Missing | Doc 12 expects `app/commands/`; current implementation routes call services directly. |
| Full Doc 10 API catalog | Missing | Only a small subset of routes exists. |
| Full Doc 4/5 UI workflows | Missing | Pages are served, but not feature-complete management screens. |
| Operator-ready product | Missing | Current app is not a complete Minecraft manager yet. |

## Start Command

From `core/`:

```powershell
python -m flask --app "app:create_app(database_path='manager.db', keyfile_path='secrets.key', migrations_dir='migrations')" run --host 127.0.0.1 --port 5000
```

Open `http://127.0.0.1:5000`.

This starts the Flask app and serves the shell. It does not mean all planned
features are usable.

## Verified Evidence

Existing verification artifacts:

| Artifact | Meaning |
|---|---|
| `audit_verify_out.txt` | Flask import OK, app module path OK, migrations produce 27 tables, Windows process adapter selected, scheduler tick is 30 seconds. |
| `full_suite_out.txt` | A previous run reported `67 passed in 33.46s`. This proves that test slice passed then, not full product completeness. |
| `conformance_out.txt` / pytest logs | Adapter/process-control test output snapshots. Need rerun before treating as current. |

Recent manual verification:

| Check | Result |
|---|---|
| `python -m py_compile app\services\worlds.py tests\integration\test_worlds_lifecycle.py` | Passed after latest world-lifecycle edits. |
| Direct EULA smoke | Passed: unaccepted EULA rejects without creating an Operation and moves world to `eula_required`. |
| Focused pytest lifecycle run | Blocked by local temp-directory permission errors in this environment during previous audit. |

## Implemented Routes

Current API/shell routes visible in code:

| Route | Status | Notes |
|---|---|---|
| `GET /` | Partial | Serves shell HTML. |
| `GET /pages/<slug>` | Partial | Serves shell HTML for known page slugs. |
| `GET /api/pages` | Scaffold | Lists the 17 registered page modules. |
| `GET /api/pages/<slug>` | Scaffold | Returns section metadata and limited world lists for selected pages. |
| `GET /api/health` | Partial | Checks scheduler object, SQLite writer query, process adapter class. |
| `GET /api/diagnostics` | Partial | Returns diagnostics service payload. |
| `GET /api/system/stats` | Partial | Returns world count and active world count. |
| `POST /api/worlds/<world_id>/start` | Partial/dev | Calls `WorldsService.start` directly. Requires correctly seeded world/template/java/settings rows. |
| `POST /api/worlds/<world_id>/stop` | Partial/dev | Calls `WorldsService.stop` directly. |
| `POST /api/worlds/<world_id>/kill` | Partial/dev | Calls `WorldsService.kill` directly. |
| `POST /api/supervisor/tick` | Dev aid | Manually runs crash detection for open sessions. |
| `/stream/*` routes | Partial | SSE routes exist; exact topic completeness needs audit against Doc 10. |

## Page Modules

The shell registers these pages:

| Page | Status | Notes |
|---|---|---|
| home | Scaffold | Shows shell; API can return running/recent worlds. |
| worlds | Scaffold | API can return world list. |
| settings | Scaffold | Sections only. |
| users | Scaffold | Sections only. |
| maintenance | Scaffold | Sections only. |
| documentation | Scaffold | Sections only. |
| system-logs | Scaffold | Sections only. |
| audit | Scaffold | Sections only. |
| sync | Scaffold | Sections only. |
| manager-maintenance | Scaffold | Sections only. |
| templates | Scaffold | Sections only. |
| world-main | Scaffold | API can return world list. |
| world-backups | Scaffold | Sections only. |
| world-logs | Scaffold | Sections only. |
| files | Scaffold | Sections only. |
| world-maintenance | Scaffold | Sections only. |
| world-setup | Scaffold | Sections only. |

## Service Layer Status

| Service/module | Status | Notes |
|---|---|---|
| `bootstrap.py` | Done/Partial | Composition root exists; background scheduler serving behavior still needs audit. |
| `services/audit.py` | Partial | Insert/read tests exist; full immutable audit workflow not fully user-facing. |
| `services/auth.py` | Partial | Auth service and tests exist; middleware/routes are incomplete versus docs. |
| `services/operations.py` | Partial | Durable operation rows and derived world lock exist; queue/preempt matrix not fully implemented. |
| `services/worlds.py` | Partial | Start/Stop/Kill/reconcile/poll implemented; create/delete/config UI/API not complete. |
| `services/scheduler.py` | Partial | Tick/dispatch/missed-run logic exists; app background loop needs audit. |
| `services/backup.py` | Partial | ZIP/SHA-256 service exists; user-facing workflow incomplete. |
| `services/restore.py` | Partial | Staged restore/rollback logic exists; user-facing workflow incomplete. |
| `services/cleanup.py` | Partial | Retention cleanup exists; UI/API incomplete. |
| `services/configuration.py` | Partial | Versioned update checks exist; full ConfigEdit orchestration incomplete. |
| `services/notifications.py` | Partial | Notification persistence/read behavior exists; UI/API incomplete. |
| `services/realtime.py` | Partial | SSE fan-out primitives exist; full topic contract incomplete. |
| `services/save_coordination.py` | Partial | RCON save coordination exists; needs end-to-end coverage through backup. |
| `services/diagnostics.py` | Partial | Basic diagnostics exist. |

## Infrastructure/Adapter Status

| Module | Status | Notes |
|---|---|---|
| SQLite connection/migrations | Done | Foreign keys and migration runner exist. |
| Secrets store | Partial | Encrypted secret storage exists; full security flow not complete. |
| Minecraft gate/readiness/RCON/properties/Java helpers | Partial | Good low-level coverage; not fully surfaced in UI/API. |
| Process adapters | Partial | Windows/POSIX adapter code and conformance tests exist. |
| Filesystem/backup/sync ports from Doc 12 | Missing/Partial | Several expected ports/adapters are not present as separate modules. |

## Major Gaps Against Docs

These are not small bugs; they are structural gaps relative to Docs 4-14.

| Gap | Expected by | Current state |
|---|---|---|
| Command/query layer | Doc 12 | `app/commands/` does not exist. Routes call services directly. |
| Full route catalog | Doc 10 | Only pages, health/diagnostics/stats, world start/stop/kill, supervisor tick, and streams are visible. |
| Authentication middleware/CSRF/step-up enforcement | Docs 8/10/12 | Not fully wired as web middleware. |
| Full setup flow | Docs 5/6/10 | Not implemented as an app workflow. |
| World creation/deletion API/UI | Docs 8/10 | Service/API/UI coverage incomplete. |
| EULA accept route/UI | Docs 10/14 | Low-level writer exists; route and full audited workflow are missing/incomplete. |
| Full backup/restore/cleanup UI/API | Docs 8/10/14 | Services exist; user-facing control surface incomplete. |
| Sync targets/offsite sync workflow | Docs 8/10 | Not complete. |
| File manager | Docs 8/10 | Not complete. |
| Full metrics/SSE topic set | Doc 10 | Partial. |
| Import-linter/tooling gate | Doc 12 | Config exists, but current tree already diverges from Doc 12's expected command layer. |
| Full release gate | Doc 11 | Not currently demonstrated by a fresh clean run. |

## Next Checklist

Recommended next work, in order:

1. Decide whether this repo is meant to become the full Docs 4-14 product or remain a smaller Flask control prototype.
2. Add a `create_app` launcher script or documented `flask --app` command in a README.
3. Add first-run setup or seed tooling so the app can create a usable admin, paths, template, Java runtime, and world from the UI.
4. Wire auth/session middleware before expanding operational routes.
5. Build the command/query layer or update Doc 12 if the architecture has intentionally changed.
6. Convert service-only functionality into API routes matching Doc 10.
7. Replace scaffold pages with real workflows one page at a time.
8. Add a CI-friendly status command that runs migrations, starts app factory, lists routes, and runs the relevant tests without relying on stale output files.
9. Keep this file updated whenever a feature moves from `Scaffold` to `Partial` or `Done`.
