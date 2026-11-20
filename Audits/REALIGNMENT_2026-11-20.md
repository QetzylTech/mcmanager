# Realignment record — 2026-11-20

This record summarizes changes made against the governing Documents 4–14 and
the current evidence collected on 2026-11-20. It supplements (and does not
replace) the active workboard at `docs/WORKBOARD.md`.

The workboard remains the single source of current task status. During an
intermediate cleanup, it and the audit pack were briefly moved to the `old doc/`
archive; this was corrected after repository guidance was rechecked. The
current workboard is restored at `docs/WORKBOARD.md`. Historical audit
snapshots remain under `old doc/Audits/`, while this directory contains the
current realignment record, verification log, and limited current traceability
ledger.

## Completed implementation and documentation slices

- Enforced the Document 8 global cap of two simultaneous sync transfers; the
  focused sync suite passed. Retry behavior remains three total attempts with
  waits of 30 and 60 seconds.
- Corrected server-properties service dependency-boundary evidence and tests.
- Improved health/diagnostics metadata and canonical response coverage.
- Fixed SSE replay line numbering, reconnect snapshot cursors, and required
  restore-log stream input; added regression cases.
- Added Admin authorization to page-module routes and step-up protection for
  supervisor tick.
- Corrected the WBS/runtime documentation references, sync retry wording, and
  Document 7's missing RCON port field.
- Prevented reconciliation from probing `eula_required` worlds.
- Preserved temporary restore archives cleanup after successful restore while
  retaining recovery pre-backups.
- Fixed browser CSRF headers across step-up retry and safer theme initialization.
- Added focused coverage for process health, runtime documentation/log APIs,
  server-properties behavior, and platform data-path fallbacks.

## Verification reported

- Consolidated focused API, middleware, SSE, diagnostics/presentation, and sync
  run: 75 Python tests passed.
- Browser contract suite: 7 tests passed.
- Schema/EULA-focused checks: 16 schema/EULA tests and 12 lifecycle tests
  passed.
- Coverage-focused additions: 13 tests passed.
- The clean full-suite run after coverage additions did **not** reach the
  configured floor: 523 passed, 0 failed, 3 skipped, 79.85% coverage, and 258
  warnings. An earlier report claimed it passed; that claim was corrected
  after identifying that 80.18% came from append-mode coverage data.
- `python-dotenv` was already declared by `app/requirements.txt` but absent
  from the active Python environment. Installing the declared package fixed
  the isolated `tests/unit/test_main.py` run (2 passed).

## Still open or blocked

- Stale-world and log cleanup remains unsupported until a product policy
  specifies eligibility, retention, preview, safeguards, and deletion rules.
- Manager restore, restart, update, and rollback remain `501 NOT_IMPLEMENTED`
  pending approved recovery, supervisor, trust, and compatibility contracts.
- Full route-by-route Document 10 parity and the Document 8/9 requirement maps
  remain incomplete.
- Hosted POSIX/security/proxy acceptance, live Minecraft variants, calibrated
  performance measurements, and complete browser E2E evidence remain open.
- Repository-wide Ruff and mypy gates still report outstanding findings.

## Handling rule

Update the relevant card in `docs/WORKBOARD.md` with exact evidence before
changing a status. This file is a dated audit record, not a second status
tracker.
