# MCManager Master System Reconciliation — Initial Evidence Pack

**Generated:** 2026-11-19  
**Repository snapshot:** uploaded `mcmanager.zip`  
**Scope:** documentation, source symbols, API route shapes, tests, pseudocode references, WBS/workboard.  
**Method:** static inspection of the extracted repository; Python AST inventories; Markdown specification extraction; source-level spot checks.  
**Important:** this is an initial reconciliation pack, not a passing release audit. The CSVs deliberately preserve `UNVERIFIED` where semantic conformance has not been established.

## Executive result

The repository now has a reproducible machine-readable inventory of key planned components and actual source/test symbols. It does **not** yet have a complete requirement-to-pseudocode-to-source-to-test proof. That remains the central outstanding task.

### Snapshot counts

| Inventory | Count | Interpretation |
|---|---:|---|
| Production Python files | 92 | Includes package initializers |
| Production Python classes/functions/methods catalogued | 602 | Private functions excluded; nested public symbols included |
| Production classes | 163 | AST declarations |
| Production functions/methods | 439 | AST declarations |
| Test Python files | 54 | Under `tests/` |
| Test-file classes/functions/helpers catalogued | 554 | Includes fixtures/helpers and test methods |
| Test-named functions (`test_*`) | 351 | Not equivalent to number of executed pytest cases |
| Document 10 route-catalog entries | 110 | HTTP route table rows |
| Source API/stream route handlers | 120 | Decorator-based route extraction |
| Document 10 route shapes found in source | 110/110 | Shape only; not authorization/schema/response parity |
| Additional source routes outside Doc 10 route catalog | 10 | Some are documented in the SSE section; others need disposition |
| Document 7 database tables | 28 | Extracted from its 28-table inventory |
| Document 8 service rows | 16 | Excludes Markdown separator |
| Document 6 entity/model subsection references | 22 | Includes lifecycle subsection references and repeated concepts |
| Workboard cards | 61 | Current board headings: 31 Done, 5 Review, 18 To Do, 5 Blocked, 2 Backlog |
| WBS stale `src/mcmanager/` references | 21 | Requires correction against actual `app/` layout |

## Important interpretation corrections

### 1. Document 6 intentionally specifies a hybrid domain model

Do not classify the absence of dataclasses for User, Operation, BackupArtifact, Schedule, etc. as a defect by itself. Document 6 §7 explicitly states that `WorldInstance` is the pure immutable domain entity and that remaining concepts are persistence-backed, with service/SQLite transaction boundaries enforcing their rules. The reconciliation must verify those persistence and service boundaries, not demand one Python class per conceptual entity.

### 2. Route presence is not API contract conformance

The route comparison finds 110 of 110 documented route shapes in source. This only proves a matching method/path shape was found. It does not prove request validation, response envelope, authorization, CSRF, step-up, status codes, error codes, idempotency, SSE semantics, or tests are conformant.

The 10 additional route shapes outside the Document 10 route-catalog table must be classified. Five `/stream/...` endpoints are described in Document 10's SSE Endpoints section and therefore are not undocumented merely because they are outside the HTTP Route catalog table. Remaining additions include page-module and cleanup-policy routes and the supervisor tick endpoint; reconcile these with Documents 5, 8, 10 and the architecture.

### 3. Pseudocode exact-name scan is deliberately weak evidence

There are 128 source symbol names with an exact textual mention in one or more historical gate pseudocode files. A name mention is not a function specification. The scan is supplied only as a search aid. No function is marked pseudocode-complete based on this scan.

### 4. Test file-name matches are only candidate links

`source_traceability.csv` associates source symbols with possible test files using file-name similarity. This is not proof that a test exercises a symbol. Every candidate must be confirmed by reading test bodies and assertions, or by adding explicit requirement/component IDs to tests.

## Confirmed source-level spot checks

- `app/web/api/administration.py` routes manager restore, restart, update and rollback to `_blocked_manager_action(...)`, with the missing contracts described in the reason text. These are intentionally blocked operations, not implemented lifecycle features.
- `app/services/cleanup.py` implements backup-artifact retention and deletion. It does not implement stale-world/log cleanup scopes.
- `app/services/sync.py` defines `DAILY_TRANSFER_CAP_BYTES` and a transfer-reservation lock. A daily byte cap/reservation is not the documented two-simultaneous-transfer admission limit; no explicit two-active-transfer counter/guard was found in the inspected service.
- `app/commands/world.py` exposes lifecycle command dispatch for Start/Stop/Kill. Document 12's wider command/query dispatch inventory is not represented as separate command-handler modules.
- `app/domain/entities.py` contains `WorldInstance`; Document 6 §7 explains why other concepts are persistence-backed, so the correct audit target is their durable behavior and service ownership.

## Artifact index

| File | Purpose |
|---|---|
| `planned_component_inventory.csv` | 176 planning references from Document 6 entity/model subsections, Document 7 tables, Document 8 services, and Document 10 route catalog |
| `source_symbol_inventory.csv` | All 602 catalogued production Python classes/functions/methods, with file and line |
| `test_symbol_inventory.csv` | All 554 catalogued test-file classes/functions/helpers |
| `source_traceability.csv` | Source symbol register with candidate test files and explicit unverified statuses |
| `route_inventory.csv` | Source route handlers, decorators, file and line |
| `api_route_parity.csv` | Document 10 route-catalog comparison against source route shapes |
| `pseudocode_name_scan.csv` | Exact-name search aid across the five historical gate pseudocode files |
| `NEXT_STEPS.md` | Ordered reconciliation and closure plan |

## Known boundaries / not yet done

This pack does not claim to have completed:
- A full semantic extraction of every normative requirement in Documents 4–14 and `ARCHITECTURE.md`.
- Service-by-service flow and state-transition mapping for Document 8.
- Operation-pair conflict matrix and all versioned entities for Document 9.
- Per-route request/response/auth/error-code verification for Document 10.
- Browser page/component and interaction inventory for all shell modules.
- Test assertion-to-requirement mapping and actual per-test execution evidence.
- Complete pseudocode for all planned and implemented functions.
- Live POSIX, Minecraft, proxy, performance, or hosted CI acceptance.

Those are explicit remaining work items, not assumed complete.

## Reproducibility

Inventories were generated from the uploaded snapshot. Source line numbers refer to that snapshot and will change if files are edited. Regenerate after source changes. The repository's `docs/audit.md` remains the prior audit record; this reconciliation pack supplements it and does not silently overwrite its historical findings.


## Additional environment and repository-hygiene findings

- A fresh `pytest --collect-only -q` attempt in the audit container could not import `flask` from `tests/conftest.py`; collection stopped before any tests ran. This is an environment/dependency availability failure, not a test failure. Install the pinned application/test dependencies before attempting an independent rerun.
- The extracted repository includes 237 files under `.git/` and 2088 files in common Python/tool cache directories. These should not be part of a clean source handoff.
- Runtime data candidates present in the snapshot include `app/data/manager.db`, `app/data/manager.db-wal`, `app/data/manager.db-shm`, and `app/data/secrets.key`. Treat the database as potentially sensitive and the key as secret material. Do not redistribute these files in source archives; inspect exposure history and rotate/re-encrypt as appropriate.
- The Git working tree reports 159 modified paths when checked against the included `.git` metadata. A comparison with end-of-line whitespace ignored showed no substantive diff summary, consistent with CRLF working-tree content versus LF Git blobs. This should be normalized using a deliberate `.gitattributes`/editor policy rather than treated as 159 independent code changes.
- The WBS contains 21 stale `src/mcmanager/` path references and describes the project as zero-dependency; both conflict with the actual `app/` layout and declared requirements.

## Comparison with `docs/audit.md`

| Existing audit claim | Reconciliation result |
|---|---|
| Numbered plans are coherent in concept but contain stale conflicts | Consistent with this review. The WBS path/dependency statements and runtime-doc path conflict remain concrete examples. |
| Gate pseudocode is historical, not a complete current specification | Consistent. The five gate files are not a complete function-level pseudocode index. Exact-name scan is only a discovery aid. |
| Manager restore/restart/update/rollback are not implemented | Confirmed by source spot-check: handlers delegate to `_blocked_manager_action(...)`. |
| Stale-world and log cleanup are not implemented | Consistent with `CleanupService` scope: backup-artifact retention/deletion is implemented; the other scopes are not represented as cleanup candidates/execution paths. |
| Sync concurrency cap is not enforced | Confirmed by source spot-check: service has daily byte-cap and reservation logic, but no explicit two-active-transfer admission guard was found. |
| Command/query layer is incomplete relative to Document 12 | Confirmed at module/class inventory level: `app/commands/world.py` provides world lifecycle commands only. |
| Workboard is not a complete traceability source | Confirmed: the board has 61 cards across statuses, while the source symbol inventory alone has 602 declarations and the requirement-level mapping is not present. Card count is not expected to equal symbol count, but the board does not provide a row for every component/function/test. |
| Current test run has 493 passed, 8 failed, 4 skipped, 76.24% coverage | Not independently reproduced. Test collection in this environment stops because Flask is unavailable. Retain the audit's figures as historical recorded evidence, not as a fresh result from this reconciliation. |
| 18/92 modules are below the coverage requirement | Not independently recalculated in this run. The audit's statement should be reconfirmed after installing dependencies and rerunning coverage. |
| Performance, POSIX, live Minecraft, proxy and hosted CI acceptance remain incomplete | No contrary evidence was found in the repository review; these remain external/host-dependent acceptance items. |

This reconciliation supplements `audit.md`; it does not overwrite the original audit or silently convert historical recorded test results into current evidence.


## Database schema name-level parity

The 28 table names listed by Document 7 are all found as `CREATE TABLE` declarations across the four production migration files: **28/28 name-level matches**. The migration SQL contains 0 `ON DELETE RESTRICT` clauses and zero actual `ON DELETE CASCADE` clauses after SQL comments are excluded. This is positive structural evidence.

It is not a complete schema acceptance result. Column types/defaults/nullability, composite and partial indexes, uniqueness under soft deletion, FK targets, immutability triggers, migration ordering, startup `foreign_key_check`, and transaction semantics still need field-by-field comparison and tests. See `schema_table_parity.csv` for table-by-table migration locations and test-file mentions.
