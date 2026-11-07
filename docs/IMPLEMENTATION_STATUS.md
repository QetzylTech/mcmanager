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
product gaps are stale-world/log cleanup policy and workflows, complete shell
workflows, manager lifecycle operations, safe cancellation of in-flight sync,
and cross-platform, deployment, and performance release acceptance.

## Gate status

| Gate | Status | Implemented and verified scope | Remaining acceptance |
|---|---|---|---|
| 1 - Process and Minecraft adapters | Partial | Port-based process/Minecraft wiring, Windows/fake adapter contracts, readiness and EULA flow, durable logging | POSIX C1-C14 evidence and real Vanilla/Paper/Fabric/Forge integration spike |
| 2 - Persistence and domain | Core slices Done | Migration/persistence checks, domain lifecycle validation, effective configuration, ConfigEdit operations and conflict mapping | Broader release/security acceptance; see workboard |
| 3 - Control plane | Core slices Done | Durable queued operations, progress/replay, conflict matrix, terminal audit, crash-safe reconciliation, scheduler/missed-run behavior | Full release acceptance beyond the focused suites |
| 4 - Operational subsystems | Review | Backup integrity, save coordination, restore rollback, cleanup floors, sync retry/cap, and filesystem hardening have focused Windows tests | Three symlink checks, POSIX and live RCON/NAS acceptance remain unverified |
| 5 - API, streams, and shell | Partial | Auth/CSRF/step-up foundations, world/settings/admin APIs, backup/restore/backup-cleanup/sync catalog workflows, queued and Running Sync cancellation, SSE replay/auth/topic behavior, shared browser connection, local security acceptance suite, cached metrics publisher, and rate-limited slow-client alerts | Stale-world/log cleanup policy, manager lifecycle operations, full shell workflows, supported-proxy validation, hosted security-job execution |

## Latest recorded verification

Windows / Python 3.13.14, updated 2026-11-07:

| Command/suite | Result |
|---|---|
| `python -m pytest --no-cov -q -k "not performance_acceptance_smoke"` | **448 passed, 3 skipped, 1 deselected**. The skips are symlink tests requiring a Windows privilege unavailable on this host; the deselected smoke is the long calibrated performance test. |
| `node --test tests\browser\test_gate5_browser.test.cjs` | **2 passed**, including 10-tab stream sharing/failover, documented event forwarding, auth expiry/recovery, and manager shutdown. |
| Dedicated security acceptance modules | **53 passed** on Windows; scoped Ruff and diff checks passed. The separate GitHub Actions job is added; hosted execution is pending. |
| Metrics/control-plane/presentation/Gate 5 integration | **42 passed, 1 deselected**; scoped Ruff passed. The deselected test is the long performance smoke. |
| Scoped Ruff, compilation, and focused mypy checks | Passed for the feature slices recorded on the workboard; this is not a repository-wide static-gate pass. |
| Repository-wide static checks | Not green: Ruff reports 46 errors; Black would reformat 76 files; isort reports 9 files; mypy reports 217 errors; `lint-imports` is unavailable in the selected interpreter. |

The three Windows symlink skips are an environment limitation, not passing
acceptance. POSIX adapter conformance and live RCON/NAS integration have not
been run. Calibrated performance acceptance remains blocked pending a
documented reference host and justified thresholds; no benchmark limits should
be inferred from the deselected smoke test.

## Major remaining product work

- Complete Document 10 cleanup scopes: the backup scope is implemented, but
  stale-world/log candidate eligibility and retention policy need a governing
  decision before destructive workflows can be completed.
- Complete the 17 shell modules as real manager/world workflows, including
  explicit world context switching.
- Implement manager restart/update/rollback and manager backup/restore
  operations; several registered endpoints currently return
  `NOT_IMPLEMENTED`.
- Verify streaming through the supported proxy shape; the cached metrics
  publisher, local cadence/fan-out checks, and rate-limited slow-client alerts
  now pass.
- Run the dedicated security acceptance GitHub Actions job on a hosted PR or
  push; its local 53-test suite passes.
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
