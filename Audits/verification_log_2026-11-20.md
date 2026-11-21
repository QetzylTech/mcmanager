# Verification log — 2026-11-20

This log records exact results available from the realignment. Test selections
overlap; do not sum their counts. Full-suite acceptance remains open until an
exact passing run and raw output are retained.

## Full test suite

1. Windows / Python 3.13, full pytest with coverage, before coverage additions:
   **507 passed, 1 failed, 3 skipped, 76.87% coverage, 259 warnings**; exit 1.
   The one failure was `tests/unit/test_main.py` because `python-dotenv` was
   missing from the environment.
2. `python-dotenv>=1.0.0` was already declared in `app/requirements.txt`.
   Installed the declared package without changing manifests.
3. `python -m pytest --no-cov -q tests/unit/test_main.py`: **2 passed**.
4. **Correction to earlier report:** the clean `.venv-phase4` run used
   `.\.venv-phase4\Scripts\python.exe -m pytest -q --tb=no` with Python
   3.13.18. It collected 526 tests: **523 passed, 0 failed, 3 skipped,
   79.85% coverage, 258 warnings** in 403.46 seconds. The configured 80%
   coverage floor was not reached. An earlier report that the gate passed was
   incorrect; the 80.18% result came from append-mode coverage data and is not
   valid clean-run evidence. The captured shell exit code was reported as 0;
   the pytest coverage result is still treated as a failed acceptance gate.

## Focused checks

- Consolidated API, middleware, SSE, diagnostics/presentation, and sync
  selection: **75 passed**.
- Browser contract suite: **7 passed**.
- Schema/EULA-focused checks: **16 passed**.
- World lifecycle checks: **12 passed**.
- Coverage-focused additions: **13 passed**: `test_process_health.py` (5),
  `test_manager_content.py` (2), `test_coverage_smoke.py` (1), and
  `test_world_management_api.py` (5, including parameter cases).
- Boundary-focused checks: **31 passed** with `--no-cov`.
- Sync gate: **9 passed**.

Focused results were reported by their owning checks. Commands for the full
75-test and browser runs should be recorded with the next reproducible
verification; do not infer them from the counts.

## Static checks and remaining warnings

- `python -m compileall -q app tests`: passed in the dedicated static-cleanup
  environment.
- Scoped Ruff checks on touched Python files passed. Repository-wide Ruff
  still reported 41 findings; broad mypy still reported 232 errors.
- Tests passed, but shutdown warnings showed background workers/scheduler/
  metrics accessing SQLite after store closure. Warning triage remains open.

## Follow-up hosted evidence — 2026-11-21

The latest hosted runs available at this follow-up are for commit
`071711da582e8305e4a33feb9974204cb89e1e93`:

- Adapter conformance, GitHub Actions run
  [44758805072](https://github.com/QetzylTech/mcmanager/actions/runs/44758805072):
  Ubuntu/Python 3.13.18 **30 passed**; Windows/Python 3.13.17 **30 passed**.
- Security acceptance, GitHub Actions run
  [44758805103](https://github.com/QetzylTech/mcmanager/actions/runs/44758805103):
  Ubuntu/Python 3.11.18 **61 passed**; Windows/Python 3.11.9 **61 passed**.

These runs postdate the 2026-11-20 verification entry but do not include
uncommitted local changes made after that commit.

## Local full-suite follow-up — 2026-11-21

On Windows / Python 3.13.14, the cleanup boundary correction was followed by
`python -m pytest --no-cov -q`: **532 passed, 0 failed, 3 skipped** in 395.10s.
Exit code was 0. Raw console output is retained at
`dev_artifacts/reports/audit_fullsuite_no_cov_2026-11-21_after_boundary_fix.txt`.
The run still emitted one `PytestUnhandledThreadExceptionWarning` for the
metrics publisher reading after the SQLite store closed; the operation worker
also logged `PersistenceError: store not open` during shutdown. Follow-up
reproduced the warning in an app-test group (87 passed, one setup error) and
traced it to `benchmarks/performance_acceptance.py` closing SQLite directly
while its background app workers remained active. The benchmark now calls the
registered app shutdown hook in `finally`, and a regression assertion checks
that all workers stop. The performance smoke passed alone with thread warnings
promoted to errors (1 passed in 300.40s). A subsequent coverage-enabled full
run passed **532 tests, 0 failed, 3 skipped** with 286 SQLite
`ResourceWarning`s in 411.08s. The metrics-publisher and operation-worker
`PersistenceError: store not open` shutdown errors did not recur; the remaining
resource warnings are not suppressed. The run reached **80.27% overall**,
satisfying the configured 80% pytest floor but remaining below Document 11's
85% requirement. The per-module report shows 15 of 92 modules below 80%:

- `app/commands/world.py` (70%), `app/infrastructure/minecraft/properties_schema.py`
  (66%), `app/infrastructure/sqlite/connection.py` (72%),
  `app/platform/process/base.py` (75%), `app/platform/process/posix.py` (23%),
  `app/services/catalog_operations.py` (70%), `app/services/save_coordination.py`
  (73%), `app/services/server_properties.py` (75%), `app/services/worlds.py`
  (73%), `app/web/api/administration.py` (55%),
  `app/web/api/backup_catalogs.py` (61%), `app/web/api/catalogs.py` (66%),
  `app/web/api/history.py` (77%), `app/web/api/server_properties.py` (77%),
  and `app/web/api/world_management.py` (74%).

Raw console output and coverage data are retained at
`dev_artifacts/reports/audit_fullsuite_coverage_2026-11-21_post_lifecycle_fix.txt`
and
`dev_artifacts/reports/audit_fullsuite_coverage_2026-11-21_post_lifecycle_fix.coverage`.
The exact post-fix `python -m pytest --no-cov -q` rerun passed **532 tests,
0 failed, 3 skipped** in 410.22s with no warning summary. Raw output is retained
at `dev_artifacts/reports/audit_fullsuite_no_cov_2026-11-21_post_lifecycle_fix.txt`.

## Repository-wide static gates — 2026-11-21

Fresh Windows/Python 3.13.14 checks remain non-green: Ruff reported 49
findings, Black reported 61 files needing formatting, isort reported 4 files
with incorrectly sorted imports, and mypy reported 226 errors in 21 files.
The changed benchmark and its regression test pass scoped Ruff, Black, and
isort. The `lint-imports` entry point exited 1 after printing only `modules`,
so no interpretable current import-contract report was obtained. No broad
autofix was applied. Raw results are retained in
`dev_artifacts/reports/audit_ruff_2026-11-21.txt`,
`dev_artifacts/reports/audit_black_2026-11-21.txt`,
`dev_artifacts/reports/audit_isort_2026-11-21.txt`,
`dev_artifacts/reports/audit_mypy_2026-11-21.txt`, and
`dev_artifacts/reports/audit_import_linter_2026-11-21.txt`.

## Merged audit follow-up — 2026-11-21

- **Full suite:** Windows / Python 3.13.14, `python -m pytest -q`:
  **568 passed, 0 failed, 3 skipped**, 297 warnings, 404.36 seconds. Coverage
  was **80.97%**, above the configured 80% floor but below Document 11's 85%
  floor. Thirteen of 92 measured modules remain below 80%. Raw output and
  per-module report:
  `dev_artifacts/reports/audit_fullsuite_coverage_2026-11-21_merged_agent_changes.txt`
  and
  `dev_artifacts/reports/audit_fullsuite_coverage_2026-11-21_merged_agent_changes_coverage.txt`.
  Warnings were retained, not suppressed.
- **Full suite without coverage:** Windows / Python 3.13.14,
  `python -m pytest --no-cov -q`: **568 passed, 0 failed, 3 skipped** in
  394.96 seconds, with no warning summary. Raw output:
  `dev_artifacts/reports/audit_fullsuite_no_cov_2026-11-21_merged_agent_changes.txt`.
- **Focused integration:** the combined Gate 2/schema, sync, restore, API,
  scheduler, boundary, and coverage selections passed **153 tests** with
  `--no-cov`. This included append-only restore outcomes, sequential sync
  attempts, configurable sync concurrency, and per-thread SQLite readers.
- **Gate 2 authentication:** `test_auth.py`, `test_gate2_realignment.py`, and
  `test_schema_migrations.py` passed **45 tests**. Coverage includes Argon2id
  storage, five-failure lockout and expiry, step-up expiry/re-entry, and
  password-change session revocation.
- **Browser:** `npm.cmd run test:browser:e2e` passed **1 Playwright Chromium
  test** for first-run setup, login, and operator-home rendering. The first
  run exposed shared read-connection misuse during background dispatch; the
  SQLite store now assigns a read-only connection per thread. The successful
  browser run no longer logged that `sqlite3.InterfaceError`. The existing
  mocked-DOM browser contract suite remains separate (7 passed).
- **Schema/configuration:** migration 006 enforces append-only
  `restore_history` and sequential `sync_attempts`; migration 007 adds the
  audited positive-integer `global_settings.sync_global_concurrency_cap`
  (default 2). The settings API and Document 7/8/10 contracts were updated.
  The Gate 2 pseudocode remains a historical snapshot; its obsolete status
  and monolithic-schema references were corrected, not executed.
- **API and architecture:** route regressions cover the runtime-config
  step-up rule and restore/cleanup grants (2 focused tests passed). Java
  catalog verification now uses the Minecraft server port (29 focused unit
  tests passed). The larger route and architecture inventories remain open.
- **Static gates:** fresh repository checks report Ruff **22 errors**, Black
  **61 files** needing formatting, isort **4 files**, and final mypy **226
  errors in 21 files** after correcting one introduced type-export issue.
  Scoped Ruff/isort passed for the changed Python set; Black
  still reports formatting in some touched files, and no broad formatter or
  autofix was applied. Logs:
  `dev_artifacts/reports/audit_ruff_2026-11-21_post_agents.txt`,
  `audit_black_2026-11-21_post_agents.txt`,
  `audit_isort_2026-11-21_post_agents.txt`, and
  `audit_mypy_2026-11-21_final.txt` (intermediate count:
  `audit_mypy_2026-11-21_post_agents.txt`).
- **Remaining acceptance:** the 85% overall and per-module coverage floors,
  complete 28-table schema parity and auth acceptance, full Document 10 route
  parity, broader HTTP/process E2E, additional browser workflows, calibrated
  performance, live server/proxy checks, and product safety contracts remain
  open or externally blocked.

## Open-task follow-up — 2026-11-21

- **SQLite fixture lifecycle:** the shared raw-store fixture now closes its
  store in `finally`; coverage-smoke containers register a store-close
  finalizer. The five tests that constructed those containers no longer leave
  writer/reader connections open.
- **Focused regressions:** on Windows/Python 3.13.14,
  `python -m pytest --no-cov -q -W error::ResourceWarning
  tests/unit/test_readiness_rcon_props.py tests/integration/test_schema_migrations.py
  tests/integration/test_document10_catalog_apis.py` passed **61 tests**.
  `python -m pytest --no-cov -q -W error::ResourceWarning
  tests/unit/test_coverage_smoke.py tests/unit/test_dependency_boundaries.py`
  passed **12 tests**. Ruff passed on the changed test files.
- **Full coverage suite:** `python -m pytest -q` passed **573 tests, 0 failed,
  3 skipped**, reached **81.67%** coverage, and produced no warning summary in
  405.11 seconds. The configured 80% floor passes; Document 11's 85% floor
  remains open. Ten of 92 modules remain below 80%: process base (73.74%),
  POSIX process adapter (22.89%), server-properties service (75.47%), worlds
  service (72.83%), administration API (54.52%), backup-catalog API (62.76%),
  catalogs API (65.83%), manager-content API (79.85%), server-properties API
  (77.14%), and world-management API (73.88%). `properties_schema.py` reached
  96.88%, SQLite `connection.py` 91.20%, and history API 95.74%.
- **Full no-coverage suite:** `python -m pytest --no-cov -q` passed
  **573 tests, 0 failed, 3 skipped** in 391.90 seconds, with no warning summary.
  The collection inventory is 576 cases: 212 unit, 334 integration, and 30
  adapter-conformance cases.
- **Retained raw outputs:**
  `dev_artifacts/reports/audit_fullsuite_coverage_2026-11-21_followup_tests.txt`
  and
  `dev_artifacts/reports/audit_fullsuite_no_cov_2026-11-21_followup_tests.txt`.
- **API parity progress:** history API regression coverage now exercises
  invalid filters/pagination, epoch and ISO timestamps, multi-field sorting,
  and missing record IDs. Full Document 10 route parity remains open.
