# Audit Staging Document

Use this file as the working destination for repository audits before creating
or updating tasks in `WORKBOARD.md`. It is a staging document, not a second
task board: `WORKBOARD.md` remains the source of truth for actionable work,
owners, dependencies, status, and verification evidence.

## Audit workflow

1. Replace the prior draft below with a dated audit: state the scope, criteria
   and sources examined, evidence and limitations, and findings.
2. Give each finding a stable temporary identifier and describe the observed
   gap, its impact, and the evidence supporting it. Separate verified issues
   from questions or unverified risks.
3. For each actionable finding, create or update a bounded task in
   `WORKBOARD.md`. Include acceptance criteria, priority, dependencies,
   evidence, and any blocker. Link related audit findings in the task when
   useful.
4. Verify that every actionable finding is represented by a workboard task.
   Record the transfer status and any findings that require a decision but
   cannot yet be implemented.
5. Once transfer is complete, the workboard controls task status and progress.
   Normally clear dated findings after transfer; retain a dated audit record
   when explicitly requested, without maintaining task status here.

## Audit record — 2026-11-19 (fresh re-run)

**Disposition:** Retained at the user's request. The workboard remains the
source of truth for task status and progress.

**Bottom line:** MCManager's production-bound application is a substantial,
organized implementation, but it is not complete, fully conformant, or
release-ready. The separate `Prototypes/` folder is a legacy reference
archive, not the current application. The numbered documents provide a strong
conceptual design, but the plans, legacy pseudocode/WBS, implementation,
tests, and tracking are not synchronized enough to act as one reliable
completion map.

### Verdicts against the original audit questions

1. **Are the plans coherent?** Mostly coherent at the conceptual level, but
   stale runtime-documentation paths, sync limits/retry wording, and WBS paths
   need reconciliation.
2. **Does the app conform to every plan?** No. Manager lifecycle workflows,
   cleanup scopes, documented sync concurrency, and complete API/service
   acceptance remain open.
3. **Is the repository organized?** The production `app/` boundary and source
   layers are recognizable; it is not generally spaghetti. There is
   architectural drift and avoidable archive clutter, especially `old doc/`.
4. **Are the pseudocodes complete and detailed?** No. All five are historical
   snapshots, not a complete current specification.
5. **Do the pseudocodes cover every planned component?** No; their selective
   examples cannot establish full component/function coverage.
6. **Is every planned component in source?** No. Confirmed gaps include four
   manager lifecycle operations, stale-world/log cleanup, and pieces of the
   planned command/query and repository architecture.
7. **Is the source complete?** No. The production implementation is substantial
   but has explicit 501 responses, unsupported scopes, failed tests, and
   unverified platform/deployment acceptance.
8. **Does the WBS/workboard list every task and accurately track it?** No.
   The board is a useful partial backlog, but full route/service/test
   traceability is still open; the WBS is work-package-level and stale in
   places.
9. **Are all planned tests written and passing?** No. The full suite has eight
   failures; coverage is 76.24%; complete E2E, per-module floors, POSIX, live
   server/proxy, and performance acceptance are not demonstrated.
10. **How accurate is project tracking?** Mixed. The updated workboard now has
    a fresh failing-suite/static snapshot, but its complete scope/status
    accuracy still depends on closing the open contract-inventory cards.

**Scope:** Reviewed the numbered design documents (4–14), architecture index,
WBS, workboard, five gate pseudocode files, application/test/benchmark
inventories, and relevant implementation and test code. This audit focuses on
plan coherence, implementation completeness/conformance, repository structure,
testing, and tracking.

**Verification performed:** Full `pytest` run with coverage on Windows /
Python 3.13.14 completed in 401.61 seconds: 493 passed, 8 failed, 4 skipped,
76.24% coverage, and 251 warnings. Rerunning the eight failed cases confirmed
the same failures. Ruff, Black, isort, and mypy were rerun from `.venv`;
`lint-imports` could not run because its module is not installed there. The
route-by-route Document 10 parity card remains open, so this audit does not
claim every route/schema/auth combination was independently verified.

### Findings

#### AUD-2026-11-19-01 — Numbered plans are coherent in concept, but contain stale conflicts

- **Assessment:** The numbered documents define useful concepts and precedence,
  but several references conflict or remain stale.
- **Evidence:** Documents 5 and 10 still say runtime documentation comes from
  repository `docs/`, while Document 12 makes `app/docs/` the distributed
  runtime-documentation location. Document 8 specifies a two-transfer
  concurrency cap, and a matching constant exists in `app/domain/tuning.py`,
  but `SyncService` has no corresponding concurrent-transfer admission guard;
  its implemented reservation enforces a 50-GiB daily byte cap. The WBS
  retains old `src/mcmanager/` paths, calls the project
  “zero-dependency,” and specifies sync delays of 30/60/120 seconds, unlike
  Document 8's three-attempt 30/60-second policy.
- **Impact:** Document precedence resolves some disputes on paper, but stale
  references make the intended current contract ambiguous to implementers.
- **References:** [Document 5](./Document_5_-_Navigation_Workflow_Blueprint.md#L39),
  [Document 8](./Document_8_-_Application_Services.md#L94),
  [Document 10](./Document_10_-_API_Contract.md#L219),
  [Document 12](./Document_12_-_Directory_Structure_and_Coding_Standards.md#L51),
  [WBS](./wbs.txt#L6), [WBS sync package](./wbs.txt#L218).
- **Tracking:** `KB-DOC-PLAN-COHERENCE`, `KB-DOC-WBS`, and
  `KB-G8-SYNC-CAP`; broader service acceptance remains in `KB-G8-CONTRACT`
  and `KB-G4-VERIFY`.

#### AUD-2026-11-19-02 — Gate pseudocode is historical, not a complete current specification

- **Assessment:** All five gate pseudocode files identify themselves as
  historical/superseded snapshots. They cover selected examples, not every
  planned function, component, API, page, or acceptance flow.
- **Impact:** Pseudocode cannot be used to prove that all planned components
  are represented or implemented. The numbered documents must remain
  authoritative; the pseudocode needs an explicit archive/refresh decision.
- **References:** [Gate 1](./gate1_pseudocode.txt#L1),
  [Gate 2](./gate2_pseudocode.txt#L1),
  [Gate 3](./gate3_pseudocode.txt#L1),
  [Gate 4](./gate4_pseudocode.txt#L1),
  [Gate 5](./gate5_pseudocode.txt#L1).
- **Tracking:** `KB-DOC-PSEUDOCODE-DECISION` now requires an explicit
  keep-as-historical or refresh decision; `KB-DOC-WBS` and
  `KB-DOC-EVIDENCE-QUALITY` cover related WBS/evidence cleanup.

#### AUD-2026-11-19-03 — Product implementation is incomplete

- **Assessment:** The source contains substantial functionality, but not every
  planned component/workflow is implemented.
- **Verified examples:** Manager restore, restart, update, and rollback remain
  `NOT_IMPLEMENTED`; stale-world and log cleanup scopes remain unsupported.
  Full Document 10 parity, full shell workflows, and manager lifecycle work
  remain open. `app/docs/` is empty by design pending the future curated
  runtime documentation.
- **Impact:** The production application is under active development and is
  not yet an operator-ready MVP. Some gaps are deliberately blocked on
  product/operations decisions and should not be mistaken for accidental
  omissions.
- **References:** [Manager API](../app/web/api/administration.py#L114),
  [cleanup API](../app/web/api/backup_catalogs.py#L455),
  [workboard cleanup tasks](./WORKBOARD.md),
  [manager lifecycle task](./WORKBOARD.md),
  [API parity task](./WORKBOARD.md).
- **Tracking:** Existing cards `KB-G5-CLEANUP-POLICY`,
  `KB-G5-CLEANUP-SCOPES`, `KB-G5-8`, `KB-G5-6`, and `KB-G5-API-CONTRACT`.

#### AUD-2026-11-19-04 — One verified service-layer boundary violation

- **Assessment:** The source is organized into recognizable layers, but the
  dependency rule is not consistently enforced.
- **Evidence:** `app/services/server_properties.py` imports concrete
  `app.infrastructure.minecraft.properties_schema`; the full suite's
  `test_services_use_ports_instead_of_concrete_infrastructure` fails.
  `app/commands/` contains only a small world-command module, and services
  still use SQL through the persistence abstraction.
- **Impact:** The architecture is not “spaghetti,” but this is a concrete
  ports-and-adapters violation and the command/query architecture is partial.
- **References:** [ServerPropertiesService](../app/services/server_properties.py#L17),
  [boundary test](../tests/unit/test_dependency_boundaries.py#L66),
  [workboard architecture task](./WORKBOARD.md).
- **Tracking:** the concrete import regression is assigned to
  `KB-G0-BOUNDARY-REGRESSION`; broader module/repository architecture is
  assigned to `KB-D12-2`. `KB-G0-1` retains its historical verification and
  links the regression follow-up.

#### AUD-2026-11-19-05 — Sync concurrency contract is not aligned with implementation

- **Assessment:** The source declares a two-transfer cap and API error, but
  `SyncService` does not enforce that cap; it enforces a 50-GiB daily
  transfer-byte limit with byte reservations. The WBS also uses a different
  retry-delay description than Document 8.
- **Impact:** The declared `SYNC_CONCURRENCY_CAP` behavior is not enforced by
  the current service. Resolve the intended policy before declaring sync
  contract parity.
- **References:** [Document 8](./Document_8_-_Application_Services.md#L94),
  [Document 10](./Document_10_-_API_Contract.md#L338),
  [SyncService](../app/services/sync.py#L47),
  [WBS sync package](./wbs.txt#L218).
- **Tracking:** `KB-G8-SYNC-CAP` requires a policy decision and either
  implementation/tests or contract removal; `KB-G8-CONTRACT` and
  `KB-G4-VERIFY` include the contract and feature acceptance.

#### AUD-2026-11-19-06 — Test coverage and test shape do not meet the plan

- **Evidence:** The fresh full coverage run reported 493 passed, 8 failed, 4
  skipped, and 76.24% overall coverage; 18 of 92 application modules are
  below 80%.
  Examples include POSIX process control at 22%, process health at 0%,
  server-properties service at 21%, and manager-content API at 19%. The
  inventory contains 15 unit, 28 integration, and 1 adapter Python test
  modules, plus one browser suite; there is no dedicated `tests/e2e/` package.
- **Plan/config mismatch:** Document 11 requires 80% per module and 85%
  overall. `pyproject.toml` enforces only an 80% overall floor; no per-module
  floor is configured.
- **Impact:** Tests do not cover every planned function/component, and the
  stated release-quality test pyramid and coverage floors are not satisfied.
- **References:** [Document 11](./Document_11_-_Testing_Strategy.md#L103),
  [pytest configuration](../pyproject.toml#L46),
  [coverage task](./WORKBOARD.md),
  [test layout plan](./Document_12_-_Directory_Structure_and_Coding_Standards.md#L228).
- **Tracking:** `KB-D11-TEST-PYRAMID`, `KB-D11-COVERAGE`, and
  `KB-D11-ISO-25010`.

#### AUD-2026-11-19-07 — Current full-suite failures remain

- **Evidence:** The fresh run reported 8 failed, 493 passed, 4 skipped, and
  251 warnings. Failures are in shell token/style expectations, the
  persistent-shell module list, three health/diagnostics expectations, the
  service dependency-boundary check, and two realtime slow-client stream
  tests. The run also logged background operation workers attempting queued
  dispatch after the SQLite store had closed; this needs triage with the
  warnings, but was not counted as an additional failed test.
- **Failing tests:** `test_shell_uses_shared_tokens_and_no_inline_style_overrides`,
  `test_persistent_shell_renders_all_17_nav_modules`,
  `test_health_monitors_scheduler_sqlite_writer_and_process_adapter`,
  `test_health_reports_reconciliation_failure`,
  `test_health_reports_degrades_to_503_when_writer_down`,
  `test_services_use_ports_instead_of_concrete_infrastructure`,
  `test_world_log_stream_replays_backlog_after_cursor_without_queue_overflow`,
  and `test_world_log_stream_reports_unavailable_cursor_then_resnapshots`.
- **Impact:** A failed full suite and failed coverage gate prevent a claim of
  repository-wide acceptance. Focused passing tests do not close these failures.
- **Tracking:** `KB-G0-7` owns restoration of the full-suite pass;
  `KB-G0-BOUNDARY-REGRESSION` owns the boundary failure.
  `KB-DOC-EVIDENCE-QUALITY` owns dated result reconciliation and affected
  feature cards retain their feature-specific checks.

#### AUD-2026-11-19-08 — Static quality gates fail; prior baselines were stale

- **Evidence:** Current checks reported 39 Ruff errors (28 fixable, with 9
  additional unsafe fixes available), 84 files needing Black formatting, 7
  isort failures plus one file that isort could not parse under the Windows
  console encoding, and 238 mypy errors in 23 of 92 files. `lint-imports` was
  unavailable because its module is not installed in the project virtualenv;
  import-boundary conformance therefore remains unverified by that command.
  The workflow directory contains adapter-conformance and security jobs but no
  general static-gate job.
- **Impact:** The documented CI/static merge gate is not green. The workboard
  has been updated with these fresh counts; fixing the gates remains open.
- **References:** [Document 12 tooling](./Document_12_-_Directory_Structure_and_Coding_Standards.md#L256),
  [static gate card](./WORKBOARD.md).
- **Tracking:** `KB-G0-5` owns restoring the static gates;
  `KB-DOC-EVIDENCE-QUALITY` owns replacing stale recorded baselines.

#### AUD-2026-11-19-09 — Performance acceptance is not evidenced by current tooling

- **Evidence:** `benchmarks/thresholds.json` contains generic reference-host
  values, but no calibrated run was found. `performance_acceptance.py` reports
  `tracemalloc` peak as RSS, and its measured flow does not exercise the
  documented 50-client stream fan-out or 1000-lines/sec log ingestion.
  Nginx/proxy behavior remains unverified.
- **Impact:** The existing benchmark cannot prove the documented RSS,
  throughput, and stream-performance criteria.
- **References:** [performance script](../benchmarks/performance_acceptance.py#L17),
  [thresholds](../benchmarks/thresholds.json),
  [Document 11 performance criteria](./Document_11_-_Testing_Strategy.md#L130),
  [performance task](./WORKBOARD.md).
- **Tracking:** `KB-PERF-01`, `KB-G5-10`, and `KB-D11-ISO-25010`.

#### AUD-2026-11-19-10 — Workboard is useful but not a complete traceability source

- **Evidence:** The WBS is work-package-level and retains obsolete paths; the
  workboard describes its code backlog as “currently known,” leaves full
  Document 8/9/10 acceptance open, and has a card under To Do marked
  “Implemented.” Before this re-run its top verification snapshot was dated
  2026-11-08 despite later evidence elsewhere; this audit updated that snapshot
  with the fresh full-suite and static-check results. A follow-up note says no
  tests/browser checks were run at that point, while later entries record
  focused API and live-browser checks.
- **Impact:** The board is a useful partial backlog, but it does not enumerate
  every requirement/function and should not be treated as an authoritative
  release-status snapshot without reconciliation.
- **References:** [workboard status snapshot](./WORKBOARD.md),
  [known code backlog](./WORKBOARD.md),
  [evidence-quality task](./WORKBOARD.md),
  [WBS reconciliation task](./WORKBOARD.md).
- **Tracking:** `KB-DOC-EVIDENCE-QUALITY`, `KB-DOC-WBS`,
  `KB-G8-CONTRACT`, and `KB-G9-CONTRACT`.

#### AUD-2026-11-19-11 — Archived documentation needs an explicit status

- **Assessment:** The current numbered plan documents remain the active
  planning set, but the repository also contains a separate `old doc/`
  archive that is not classified in the current documentation index.
- **Evidence:** `old doc/` contains 16 files, including older Document 5–9
  copies and legacy architecture/implementation notes; `Prototypes/` is a
  separate reference archive. This audit did not establish that every
  archived file is a duplicate or safe to delete.
- **Impact:** The archive contributes to repository clutter and makes it less
  obvious which documents are authoritative. No files should be removed or
  moved until their use and status are checked; current numbered plans stay
  where they are.
- **Tracking:** `KB-DOC-LEGACY-ARCHIVE`.

### Recommended next actions

1. **Restore the full-suite pass (P0):** fix the dependency-boundary failure
   under `KB-G0-BOUNDARY-REGRESSION`, then address the remaining seven
   failing shell, health/diagnostics, and realtime tests under `KB-G0-7`.
   Triage the 251 warnings and the background-worker shutdown errors without
   weakening assertions.
2. **Resolve product policies before implementing destructive or conflicting
   behavior (P1):** decide stale-world/log cleanup eligibility and retention
   (`KB-G5-CLEANUP-POLICY`), and decide whether the two-transfer sync cap and
   retry schedule remain required (`KB-G8-SYNC-CAP`).
3. **Complete missing operator workflows:** implement the policy-backed
   cleanup scopes after their decision, and replace the manager restore,
   restart, update, and rollback 501 responses with approved durable
   workflows (`KB-G5-CLEANUP-SCOPES`, `KB-G5-8`).
4. **Finish contract traceability:** after their listed prerequisites are
   Done, complete route/auth/schema/error, service-flow, and
   concurrency/versioning inventories (`KB-G5-API-CONTRACT`,
   `KB-G8-CONTRACT`, `KB-G9-CONTRACT`). Add any newly confirmed gaps to the
   owning implementation cards.
5. **Close test and quality gates:** meet Document 11's 80%-per-module and
   85%-overall floors, restore repository-wide static checks, and complete
   browser/E2E acceptance (`KB-D11-COVERAGE`, `KB-D11-TEST-PYRAMID`,
   `KB-G0-5`).
6. **Run external release acceptance:** POSIX conformance, hosted security
   CI, live Minecraft/server-type and proxy checks, and calibrated
   performance testing remain open or blocked on external hosts/reference
   hardware.
7. **Reconcile the documentation set:** align the runtime-doc references,
   WBS, pseudocode status, and historical archive while keeping current
   numbered plans in place (`KB-DOC-PLAN-COHERENCE`, `KB-DOC-WBS`,
   `KB-DOC-PSEUDOCODE-DECISION`, `KB-DOC-LEGACY-ARCHIVE`).

### Detailed outstanding implementation and test inventory — 2026-11-19

This addendum records the complete **currently verified** list of known
unfinished production behavior, planned architectural components, and
acceptance tests. “Missing” is reserved for confirmed absent behavior.
“Incomplete/unverified” means some implementation or tests exist, but the
governing contract has not been traced and accepted end to end. These are not
interchangeable.

The inventory is bounded by the current repository and open workboard cards.
It cannot honestly be called exhaustive down to every route, function, or test
case until `KB-G5-API-CONTRACT`, `KB-G8-CONTRACT`, and `KB-G9-CONTRACT` finish
their route-by-route/service-by-service inventories. Any additional gaps they
discover must be added here and to the owning workboard cards. The open
inventory itself is a known project-tracking gap, not evidence that every
unlisted feature is complete.

#### Production behavior and planned components not yet complete

| Area | Confirmed missing or incomplete work | Evidence / qualification | Tracking |
|---|---|---|---|
| Stale-world cleanup | Product rules are still missing: candidate eligibility, retention, exclusions, preview contents, and execution safeguards. After approval, implement discovery, dry-run preview, and wet deletion for `stale_worlds`, including audit and result summaries. | The API currently rejects this scope as unsupported; `CleanupService` only performs backup-artifact cleanup. Destructive implementation is correctly blocked pending policy. | `KB-G5-CLEANUP-POLICY`, `KB-G5-CLEANUP-SCOPES` |
| Log cleanup | Define log retention/eligibility and exclusions, then implement candidate discovery, preview, and wet deletion through `CleanupService`, with containment, safeguards, audit, and summaries. | The `logs` cleanup scope is also unsupported; no approved policy exists. | `KB-G5-CLEANUP-POLICY`, `KB-G5-CLEANUP-SCOPES` |
| Manager restore | Implement the manager configuration restore operation, including scope, encryption-key handling, schema compatibility, and recovery of active sessions/world processes; then add the operator workflow. | `manager_restore()` currently returns `NOT_IMPLEMENTED` (501). | `KB-G5-8` |
| Manager restart | Define the host-supervisor/relaunch and in-flight-operation contract, then implement the durable authorized restart workflow and UI. | `manager_restart()` currently returns `NOT_IMPLEMENTED` (501); restart also requires step-up authorization. | `KB-G5-8` |
| Manager update | Define trusted version sources, package verification, staged replacement, migration, and post-update health checks; then implement the durable update workflow and UI. | `manager_update()` currently returns `NOT_IMPLEMENTED` (501). | `KB-G5-8` |
| Manager rollback | Define target selection, data compatibility, and partial-failure recovery; then implement the durable rollback workflow and UI. | `manager_rollback()` currently returns `NOT_IMPLEMENTED` (501). | `KB-G5-8` |
| Sync concurrency contract | Decide whether the documented two-simultaneous-transfer cap remains normative; if so, add an admission limit and matching error behavior. | A cap constant and API error exist, but no explicit two-transfer admission guard is evidenced in `SyncService`; its byte reservation logic does not prove a concurrency cap. The service and spec must be reconciled before calling this implemented. | `KB-G8-SYNC-CAP`, `KB-G8-CONTRACT`, `KB-G4-VERIFY` |
| Command/query layer | Complete or explicitly revise the planned command/query dispatch layer. The only command module currently present is `app/commands/world.py`, which wraps Start/Stop/Kill; the separately specified CreateWorld/DeleteWorld/RenameWorld handlers and base/protocol, runtime, backup, restore, cleanup, sync, config, crash, and query handlers are absent as components. | This is a confirmed architecture/layout divergence from Document 12, not proof that each operation's business behavior is absent; some behavior currently resides in routes/services. | `KB-D12-2` |
| Persistence repositories | Decide and implement the planned SQLite generic, operation, and audit repositories, or update the architecture to accept the current persistence-port/SQL arrangement. | `repository.py`, `operations_repo.py`, and `audit_repo.py` are absent; the board records direct SQL through the persistence abstraction. | `KB-D12-2` |
| Other operator workflows | Finish the remaining real workflows across the 17 shell modules, including manager lifecycle actions after their backend contracts exist. Complete browser acceptance for recently added settings, properties, sync-target, documentation, and manager-log workflows. | The shell card is partial. Existing UI/API implementation is not acceptance evidence; the recorded Node regression for the latest UI work was not run because Node was unavailable. | `KB-G5-6`, `KB-G5-8`, `KB-G5-API-CONTRACT` |

The documentation separately marks the Google Drive transport, notification
adapter, and metrics-export adapter as future/stub scope. They are **not**
counted as missing MVP work in this inventory unless product scope changes.
Likewise, absent module names whose responsibilities are already implemented
inside consolidated modules are architecture differences, not automatically
missing features.

#### Tests and acceptance checks not yet written, complete, or demonstrated

| Test/acceptance area | Remaining required coverage | Evidence / qualification | Tracking |
|---|---|---|---|
| Cleanup scopes | Policy and candidate-selection unit tests; API/integration tests for preview freshness, retention/exclusions, blast-radius safeguards, wet deletion, audit, and summaries for stale worlds and logs. | The corresponding cleanup behavior is not implemented, so its feature tests cannot yet pass; add them with the owning implementation card after policy approval. | `KB-G5-CLEANUP-POLICY`, `KB-G5-CLEANUP-SCOPES` |
| Manager lifecycle | Integration acceptance for manager restore/restart/update/rollback authorization, durable operations, recovery/failure paths, audit, and UI submission/status. | Backup has focused evidence; the other four actions are 501 and have no completed feature acceptance. | `KB-G5-8` |
| Document 8 service contract | A final acceptance map and any missing tests for every service/operation flow, operation persistence, audit/notification outcomes, cancellation/retry/timeout, scheduler/missed-run behavior, storage guard, and restore recovery. | Focused suites exist, but service-wide acceptance is not established; identify exact missing cases during the contract inventory rather than assuming every listed case is absent. | `KB-G8-CONTRACT`; feature-owner cards |
| Document 9 concurrency/versioning | Complete the operation-pair conflict matrix, atomic/race behavior, lock release and queue/reject semantics, and stale-version rejection for every versioned entity. | Some conflict and ConfigEdit tests exist; the full matrix and all versioned entities have not been mapped to passing tests. | `KB-G9-CONTRACT`; feature-owner cards |
| Document 10 API contract | Per-route checks for registration, access/session/CSRF/step-up rules, request and response shape, status/envelope/error mapping, including the newly added APIs and explicit 501 exceptions. | Full route/auth/schema parity remains open; passing selected catalog tests do not establish coverage for every route combination. | `KB-G5-API-CONTRACT` |
| Shell/browser workflows | Browser acceptance for all production workflows and 17 shell modules, including manager lifecycle UI when implemented; run the recorded-but-unrun Node regression. | A browser suite exists, but workboard acceptance remains partial and the latest regression was not executed. | `KB-G5-6`, `KB-G5-8` |
| End-to-end flows | Complete the canonical real-HTTP/API + process flows: login and rehydration, start/live-log/stop, SSE snapshot/replay/reconnect, and crash-to-state/operation/notification/audit. | There is no dedicated `tests/e2e/` package. Existing browser and integration tests cover slices, not the complete Document 11 E2E scope. | `KB-D11-TEST-PYRAMID`, feature-owner cards |
| Unit/integration completeness and coverage | Complete the documented unit/service and SQLite integration inventory; achieve at least 80% line coverage per module and 85% overall; configure/enforce both floors. | Document 11's coverage and pyramid requirements are not closed. Current pytest configuration enforces only an 80% overall floor, not the per-module floor or 85% overall floor. | `KB-D11-COVERAGE`, `KB-D11-TEST-PYRAMID` |
| Quality-characteristic evidence | Add/complete measurable tests and recorded evidence for every applicable ISO/IEC 25010 characteristic, especially compatibility, flexibility, security, and performance. | The evidence map is partial; compatibility/performance/flexibility acceptance is not established. | `KB-D11-ISO-25010` |
| Performance acceptance | Measure a documented reference host for 300-second idle CPU/RSS, 50 concurrent 1-Hz SSE clients with compute-once/CPU-flatness, and 1,000 log lines/sec with tail latency. Correct the benchmark so RSS is actually measured as RSS. | A benchmark script exists, but calibrated results and the documented workloads are not established; the current script's `tracemalloc` peak is not process RSS. | `KB-PERF-01`, `KB-G5-10` |
| Minecraft live acceptance | Run and record the real-server checks for Vanilla, Paper, Fabric, and Forge, covering Java/EULA preflight, readiness, RCON/save behavior where supported, shutdown, and startup-failure classification. | Fake-server and C1–C14 conformance tests are written. Live evidence is partial for Forge only; Vanilla/Paper/Fabric are untested, and Forge did not exit cleanly after RCON stop. | `KB-G1-MINECRAFT`, `KB-G1-FORGE-SHUTDOWN` |
| Cross-platform conformance | Run the existing C1–C14 suite on a supported POSIX host and record the hosted Ubuntu result. | The tests are written and Windows evidence exists; the POSIX/hosted run remains pending. | `KB-G1-6` |
| Security CI | Run the existing dedicated security suite on the hosted Ubuntu/Python matrix and record results. | Local focused evidence exists; hosted execution remains pending. | `KB-G5-11` |
| Live proxy/SSE deployment | Verify proxy configuration and live HTTPS, buffering-disabled SSE reconnect/replay behavior through the supported deployment shape. | Nginx example/configuration exists; live proxy validation has not been run on the current host. | `KB-G5-10` |

#### Explicitly unresolved inventory boundaries

These are not additional claims that specific code is missing. They are the
remaining audits required to discover and name any further missing functions
or tests:

- `KB-G5-API-CONTRACT` must finish the Document 10 route-by-route comparison.
- `KB-G8-CONTRACT` and `KB-G9-CONTRACT` must finish service-flow and
  concurrency/versioning traceability.
- `KB-D11-TEST-PYRAMID`, `KB-D11-COVERAGE`, and `KB-D11-ISO-25010` must
  establish the complete test inventory and measured quality gates.
- Feature-level test gaps discovered by those audits belong on the owning
  implementation cards; cross-cutting test infrastructure belongs on the
  Document 11 cards.

Accordingly, this addendum is the fullest evidence-backed list available now,
but a claim that it names every missing function/test would be premature until
the four inventory/acceptance cards above are completed.

### Tracking disposition

**Transfer status:** every currently identified actionable finding and
addendum item is assigned to an existing or newly created workboard card.
`docs/WORKBOARD.md` is authoritative for status, ownership, dependencies, and
verification; this retained audit is not a second task board.

| Audit finding | Workboard task(s) | Transfer |
|---|---|---|
| AUD-2026-11-19-01 | `KB-DOC-PLAN-COHERENCE`, `KB-DOC-WBS`, `KB-G8-SYNC-CAP` | Transferred |
| AUD-2026-11-19-02 | `KB-DOC-PSEUDOCODE-DECISION` | Transferred |
| AUD-2026-11-19-03 | `KB-G5-CLEANUP-POLICY`, `KB-G5-CLEANUP-SCOPES`, `KB-G5-8`, `KB-G5-6`, `KB-G5-API-CONTRACT` | Transferred |
| AUD-2026-11-19-04 | `KB-G0-BOUNDARY-REGRESSION`, `KB-D12-2` | Transferred |
| AUD-2026-11-19-05 | `KB-G8-SYNC-CAP`, `KB-G8-CONTRACT`, `KB-G4-VERIFY` | Transferred |
| AUD-2026-11-19-06 | `KB-D11-TEST-PYRAMID`, `KB-D11-COVERAGE`, `KB-D11-ISO-25010`, feature-owner cards | Transferred |
| AUD-2026-11-19-07 | `KB-G0-7`, `KB-G0-BOUNDARY-REGRESSION` | Transferred |
| AUD-2026-11-19-08 | `KB-G0-5`, `KB-DOC-EVIDENCE-QUALITY` | Transferred |
| AUD-2026-11-19-09 | `KB-PERF-01`, `KB-G5-10`, `KB-D11-ISO-25010` | Transferred |
| AUD-2026-11-19-10 | `KB-DOC-EVIDENCE-QUALITY`, `KB-DOC-WBS`, `KB-G5-API-CONTRACT`, `KB-G8-CONTRACT`, `KB-G9-CONTRACT` | Transferred |
| AUD-2026-11-19-11 | `KB-DOC-LEGACY-ARCHIVE` | Transferred |
| Detailed implementation/test inventory | Cleanup, manager lifecycle, architecture, API, test, platform, security, and performance cards listed above | Transferred |

The inventory remains bounded by the unresolved route/service/test traceability
cards (`KB-G5-API-CONTRACT`, `KB-G8-CONTRACT`, `KB-G9-CONTRACT`, and the
Document 11 cards). Any newly discovered gap must be added to its owning
workboard card; this is the explicit limit on claims of exhaustiveness.
