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
