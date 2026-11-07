# MCManager Implementation Status

Last verified: 2026-11-07

`docs/` is the product contract. This file summarizes implementation and
verification state; passing focused tests does not mean a whole gate or the
product is release-ready. Work-item ownership, dependencies, and detailed
evidence are tracked in [WORKBOARD.md](WORKBOARD.md).

## Current assessment

MCManager has a tested application foundation and substantial control-plane
functionality. It is an **early functional prototype, not yet an
operator-ready MVP** for dependable day-to-day server management. The main
product gaps are the remaining backup/restore/cleanup/sync API workflows,
complete shell workflows, manager lifecycle operations, and cross-platform,
security, and performance release acceptance.

## Gate status

| Gate | Status | Implemented and verified scope | Remaining acceptance |
|---|---|---|---|
| 1 - Process and Minecraft adapters | Partial | Port-based process/Minecraft wiring, Windows/fake adapter contracts, readiness and EULA flow, durable logging | POSIX C1-C14 evidence and real Vanilla/Paper/Fabric/Forge integration spike |
| 2 - Persistence and domain | Core slices Done | Migration/persistence checks, domain lifecycle validation, effective configuration, ConfigEdit operations and conflict mapping | Broader release/security acceptance; see workboard |
| 3 - Control plane | Core slices Done | Durable queued operations, progress/replay, conflict matrix, terminal audit, crash-safe reconciliation, scheduler/missed-run behavior | Full release acceptance beyond the focused suites |
| 4 - Operational subsystems | Review | Backup integrity, save coordination, restore rollback, cleanup floors, sync retry/cap, and filesystem hardening have focused Windows tests | Three symlink checks, POSIX and live RCON/NAS acceptance remain unverified |
| 5 - API, streams, and shell | Partial | Auth/CSRF/step-up foundations, world APIs, settings/catalog/admin APIs, durable operations, SSE replay/auth/topic behavior, shared browser connection and world-list workflow | Backup/restore/cleanup/sync APIs, manager lifecycle operations, operation cancellation, full shell workflows, metrics/proxy and security acceptance |

## Latest recorded verification

Windows / Python 3.13.14, updated 2026-11-07:

| Command/suite | Result |
|---|---|
| `python -m pytest --no-cov -q -k "not performance_acceptance_smoke"` | **448 passed, 3 skipped, 1 deselected**. The skips are symlink tests requiring a Windows privilege unavailable on this host; the deselected smoke is the long calibrated performance test. |
| `node --test tests\browser\test_gate5_browser.test.cjs` | **2 passed**, including 10-tab stream sharing/failover, documented event forwarding, auth expiry/recovery, and manager shutdown. |
| Scoped Ruff, compilation, and focused mypy checks | Passed for the feature slices recorded on the workboard; this is not a repository-wide static-gate pass. |
| Repository-wide static checks | Not green: the recorded baseline reported 52 Ruff errors, Black would reformat 74 files, isort reported 14 files, mypy failed, and import-linter reported `app layers BROKEN`. |

The three Windows symlink skips are an environment limitation, not passing
acceptance. POSIX adapter conformance and live RCON/NAS integration have not
been run. Calibrated performance acceptance remains blocked pending a
documented reference host and justified thresholds; no benchmark limits should
be inferred from the deselected smoke test.

## Major remaining product work

- Implement and test the Document 10 backup, restore/rollback, cleanup, and
  sync API catalog.
- Complete the 17 shell modules as real manager/world workflows, including
  explicit world context switching.
- Implement manager restart/update/rollback and manager backup/restore
  operations; several registered endpoints currently return
  `NOT_IMPLEMENTED`.
- Implement the documented operation-cancellation endpoint.
- Verify and complete metrics cadence, streaming behavior through the
  supported proxy shape, and the dedicated security acceptance suite.
- Run the real Minecraft adapter integration spike across Vanilla, Paper,
  Fabric, and Forge, and run C1-C14 on a supported POSIX host.
- Restore green repository-wide lint, format, type, and import-boundary gates.
- Complete calibrated performance release acceptance after the reference
  host/profile is available.

Detailed dependencies and acceptance criteria for these items are in
[WORKBOARD.md](WORKBOARD.md). Gate 4 verification and a full Document 10 API
contract parity audit also remain open there.

## Run locally

Run the app from the repository root (local manager state and Minecraft
installations are kept in ignored directories under `app/`):

```powershell
python -m flask --app "app:create_app(database_path='app/data/manager.db', keyfile_path='app/data/secrets.key', migrations_dir='migrations')" run --host 127.0.0.1 --port 5000
```

Application startup is not evidence that all operator workflows or release
gates are complete.
