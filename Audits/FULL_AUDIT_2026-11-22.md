# Full repository audit - 2026-11-22

## Executive result

**FAIL** - the repository has substantial implementation. A later coverage
remediation run now passes the documented coverage floors, but required static,
live-platform, and feature-completeness gates remain open.

## Audit identity

- Audit ID: `AUD-2026-11-22-01`
- Date: 2026-11-22
- Scope: full project implementation and release readiness
- Related workboard cards: `KB-G0-5`, `KB-G0-7`, `KB-D11-COVERAGE`,
  `KB-D11-TEST-PYRAMID`, `KB-G5-8`, `KB-G5-API-CONTRACT`, `KB-REC-03`,
  `KB-REC-04`, `KB-D12-2`, `KB-G1-MINECRAFT`, `KB-G5-10`, `KB-PERF-01`

## Scope and candidate

- Candidate code revision: `22155c1a395cb6b6cdddae79483f16c7f6d71faa`
- Audit report and raw outputs are uncommitted evidence files and are not part
  of the candidate code revision.
- Platform: Windows
- Python: 3.13.18 in `.venv-phase4`
- Governing requirements:
  - `docs/AGENT_DEVELOPMENT_WORKFLOW_SPEC.md`
  - `docs/ARCHITECTURE.md`
  - Documents 4-14 under `docs/`
  - `docs/WORKBOARD.md`
  - `pyproject.toml`
- Independent reviewer: Copilot SDK in VS Code, 2026-11-22

## Verification summary

| Check | Result | Evidence |
|---|---|---|
| Test collection | 580 collected | `pytest --collect-only -q` |
| Full no-coverage suite | **577 passed, 3 skipped** in 439.77s | `dev_artifacts/reports/audit_fullsuite_no_cov_2026-11-22.txt` |
| Real Playwright browser flow | 1 passed | First-run setup/login/operator home |
| Python compileall | Passed | `app`, `tests`, `dev_tools` |
| Workflow verifier | Passed, 0 status/section warnings | `python dev_tools/workflow_verify.py` |
| Ruff | Failed: 36 errors | `dev_artifacts/reports/audit_ruff_2026-11-22.txt` |
| Black | Failed: 67 files need formatting | `dev_artifacts/reports/audit_black_2026-11-22.txt` |
| isort | Failed: 6 files have unsorted imports | `dev_artifacts/reports/audit_isort_2026-11-22.txt` |
| mypy | Failed: 1010 errors in 67 files | `dev_artifacts/reports/audit_mypy_2026-11-22.txt` |
| import-linter | Blocked: `lint_imports` module/console entry point unavailable | `dev_artifacts/reports/audit_lint_imports_2026-11-22.txt` |
| Full coverage suite | **577 passed, 3 skipped; 81.77%** in 441.91s. Configured 80% floor passed; Document 11's 85% overall and 80% per-module floors failed (9 modules below 80%) | `dev_artifacts/reports/audit_fullsuite_coverage_2026-11-22.txt` |
| Coverage remediation follow-up | **643 passed, 3 skipped; 87.53%** in 460.80s; every measured module met 80% | `dev_artifacts/reports/coverage_final.txt` |
| Fresh coverage review rerun | **643 passed, 3 skipped; 87.60%** in 467.56s; every measured module met 80%; independent review PASS_WITH_FINDINGS | `dev_artifacts/reports/coverage_current_review_rerun_2026-11-22.txt` |

The earlier disk-space failure was resolved by removing named generated
scratch artifacts; the coverage run then completed. Its result supersedes the
prior 81.67% snapshot for the original candidate baseline. The remediation
follow-up is a separate, uncommitted verification on the same working tree;
it supersedes the coverage status only, not the other audit findings.

Modules below Document 11's 80% per-module floor: `app/platform/process/base.py`
(74%), `app/platform/process/posix.py` (23%),
`app/services/server_properties.py` (79%), `app/services/worlds.py` (73%),
`app/web/api/administration.py` (55%), `app/web/api/backup_catalogs.py` (63%),
`app/web/api/catalogs.py` (66%), `app/web/api/server_properties.py` (77%), and
`app/web/api/world_management.py` (74%).

The follow-up run closed these coverage-floor findings: `app/services/worlds.py`
measured 80%, `app/web/api/backup_catalogs.py` 81%, and every other measured
module was also at least 80%; total coverage was 87.53%.

The fresh review rerun on Windows/Python 3.13.18 passed 643 tests with 3
skipped and 87.60% overall coverage (9,395 statements) in 467.56s. Every
measured module met 80%; the lowest were `app/services/worlds.py` and
`app/web/api/manager_content.py` at 80%. Independent review returned
PASS_WITH_FINDINGS: the current-tree evidence and coverage claims are supported;
automated enforcement of the 85% overall and per-module floors remains a
non-blocking follow-up. The workboard remains in Review for authorized status
acceptance; the overall project audit remains **FAIL**.

## Components, features, functions, and modules not built

### Directly unimplemented HTTP/lifecycle functions

| Missing component or function | Source evidence | Workboard owner |
|---|---|---|
| `app/web/api/administration.py::manager_restore()` | 501 response; no restore workflow | `KB-G5-8` |
| `app/web/api/administration.py::manager_restart()` and host relaunch | 501 plus disabled UI; no supervisor/relaunch contract | `KB-G5-8` |
| `app/web/api/administration.py::manager_update()` | 501; no staged package verification, migration, health-check, or trusted-source workflow | `KB-G5-8` |
| `app/web/api/administration.py::manager_rollback()` | 501; no target selection, compatibility decision, or partial-failure recovery | `KB-G5-8` |
| Curated runtime documentation content | `app/docs/` contains only `.gitkeep`; no authored operator documents | `KB-G5-8`, `KB-DOC-PLAN-COHERENCE` |
| Template server-jar provisioning | Downloader/archive exists in local data, but CreateWorld does not resolve or copy a selected artifact | `KB-G1-SERVER-JAR-CATALOG` |

The manager backup action exists and is partially implemented. The four
remaining lifecycle operations are explicitly not built.

### Server-jar archive and CreateWorld integration

- The local archive is `app/data/serverjars/`, currently containing 695
  `.jar` files: Fabric 537, NeoForge 20, Purpur 41, Vanilla 97; no Paper or
  Forge directories were present.
- The ignored `app/data/serverjars/minecraft_server_archive.py` supports
  Vanilla, Purpur, Paper, Fabric, Forge, and NeoForge. Its default output is
  the working-directory-relative `MinecraftArchive`; it only targets the
  app's serverjars directory when an explicit `--output` is supplied.
- The local `manifest.json` records absolute paths rooted at
  `C:\AI\OdyssuesMount\WorldArchives`, rather than the current
  `app\data\serverjars` path. Treat these manifest paths as stale/unreconciled
  provenance; do not use them as a validated current path map.
- The downloader documents Forge and NeoForge artifacts as installers, not
  installed server jars; Fabric artifacts are launchers that fetch game
  components on first run. A provider/version match alone is insufficient to
  prove an artifact can be launched as `java -jar`.
- `app/web/api/world_management.py::create_world()` uses the template's
  category and default version to create world metadata and an EULA-gated
  world directory. It does not consult the downloader, its manifest, or
  `app/data/serverjars`, nor copy a selected artifact into the world.
- `app/services/worlds.py::_launch_context()` discovers a jar only in the
  world's directory (`_find_jar(world_dir)`). The startup gate rejects a
  missing jar unless an explicit launch-argument override is supplied.
- The governing plan requires a JAR path to exist before Start (Document 14
  §4), and CreateWorld to validate a template and provision the world
  directory (Document 8 §2). It does not yet define shared archive lookup,
  artifact selection, or installation behavior. This is a plan-to-code gap
  that needs an approved artifact contract, not just a path change.
- Both the downloader and archive live under ignored `app/data/`, so neither
  is tracked in the candidate or included in a clean source checkout.

**Finding — MAJOR:** Creating a world from a catalog template does not use
the downloaded server-jar archive. The standard flow can create the metadata
and directory but has no automatic path to provision a runnable server
artifact; Start may consequently fail its documented JAR-existence check.
Track remediation under `KB-G1-SERVER-JAR-CATALOG`. This is distinct from the
known manager lifecycle 501 routes.

### Missing or incomplete planned architecture modules

| Planned module or layer | Current state | Finding |
|---|---|---|
| Command/query handlers for runtime, backup, restore, cleanup, sync, config, crash, and queries | Only `app/commands/world.py` exists | Planned command layer is not implemented |
| SQLite generic repository | Missing planned `repository.py` | Services currently issue SQL through `PersistencePort` connections |
| SQLite operation repository | Missing planned `operations_repo.py` | Derived-lock queries are not isolated in a repository module |
| SQLite audit repository | Missing planned `audit_repo.py` | Audit writes remain service/connection-based rather than the planned repository layer |
| Google Drive sync transport | No concrete implementation behind the future target; NAS is implemented | Document 12 labels this a future target |
| External notification adapters | No concrete Discord/webhook delivery | Document 6 labels integrations as future, requirement-gated ports |
| Metrics export adapters | No concrete Prometheus/Grafana exporter | Document 6 labels integrations as future, requirement-gated ports |

This is a planned-layer divergence, not necessarily a broken runtime. It
requires an approved architecture decision or bounded migration. The Google
Drive, external notification, and metrics exporters are explicitly future
integrations in the product/architecture documents; they are not reported as
current release blockers.

### Features with implementation but incomplete acceptance

- Full route-by-route Document 10 API parity
- Complete 28-table Document 7 schema parity and migration-history acceptance
- Complete Document 8 service requirement matrix
- Complete Document 9 concurrency/conflict matrix and every stale-version case
- Full 17-module shell workflow acceptance beyond setup/login
- Live Nginx/TLS/SSE proxy and reconnect validation
- Live real-server acceptance for Vanilla, Paper, Fabric, and Forge
- Forge clean shutdown after RCON stop
- Real performance acceptance for idle CPU/RSS, 50-client 1Hz fan-out, and
  1000 log-lines/sec latency
- Dedicated security acceptance suite and hosted security rerun on this candidate
- Complete ISO/IEC 25010 quality-characteristic evidence
- Test pyramid correction: the last documented breakdown (576 collected on
  2026-11-21) was 36.8% unit, 58.0% integration, and 5.2% adapter conformance,
  not 70/25/5. The initial 580-case collection was not independently
  categorized in this audit; the remediation run later collected 646 cases,
  but its distribution was not recategorized.

## Requirements and architecture findings

### BLOCKER - static analysis release gates

Ruff, Black, isort, and mypy are required merge/release gates in Document 11
and Document 12 and fail on the candidate. The import-linter package/entry
point is unavailable. The 2026-11-22 coverage remediation follow-up passes
Document 11's overall and per-module floors; see the verification table and
`KB-D11-COVERAGE`.

Affected requirements: Document 11 §§3.2, 4.3; Document 12 §8.

### MAJOR - manager lifecycle operations are incomplete

Manager restore, restart, update, and rollback remain 501 responses. The
missing decisions include encryption-key scope, schema compatibility,
supervisor/relaunch behavior, trusted update verification, rollback targets,
and partial-failure recovery.

Affected requirements: Document 6 Manager lifecycle; Document 8; Document 10;
Document 11 safety and reliability gates.

### MAJOR - external and live acceptance remains unverified

No current live Vanilla/Paper/Fabric acceptance, no live Nginx/TLS proxy,
and no calibrated reference-hardware benchmark are retained. The real
Playwright run covers only setup/login/operator-home loading.

Affected requirements: Document 11 §§1.4, 4.1-4.2.

### MAJOR - architecture plan and implementation differ

The command, repository, and service boundaries described in Document 12 are
only partially present. This is open under `KB-D12-2`; no architecture
amendment or migration was independently accepted.

Affected requirements: Document 12 §§2-5; Architecture service boundaries.

### MAJOR - API and schema parity is incomplete

Existing route/catalog tests do not close all 110+ route, schema,
authorization, error-envelope, and SSE contract rows. 28-table schema parity
is not complete.

Affected requirements: Documents 7 and 10.

### MAJOR - test distribution remains open

The test pyramid is not presently 70/25/5. The latest coverage run passes the
85% overall and 80% per-module floors, but the pyramid distribution and
broader workflow coverage remain open.

Affected requirements: Document 11 §§1-3.

## Existing implementation that is present

The audit confirms substantial implementation, including world lifecycle,
operations and reconciliation, audit and notification pipelines, backup and
restore coordination, cleanup policy and stale-artifact cleanup, sync targets,
authentication and authorization, SSE infrastructure, server-properties
editing, Windows/POSIX process adapters, fake-server conformance, and a real
Chromium setup/login flow.

## Audit result

- **Outcome:** FAIL
- **Reason:** required static gates fail; lifecycle/API/host/performance
  acceptance and the test-pyramid target also remain incomplete. The coverage
  floors passed in the documented remediation follow-up.
- **No task was accepted or moved to Done by this audit.**
- **Coverage remediation follow-up:** `KB-D11-COVERAGE` reached its stated
  overall and per-module thresholds. Its fresh evidence received an
  independent `PASS_WITH_FINDINGS` review; manual threshold enforcement remains
  a non-blocking finding, and authorized status acceptance is pending. This does
  not close the broader audit or separate test-pyramid work.
- **Existing finding owners:** `KB-G0-5`, `KB-G0-7`, `KB-D11-COVERAGE`,
  `KB-D11-TEST-PYRAMID`, `KB-G5-8`, `KB-G5-API-CONTRACT`, `KB-REC-03`,
  `KB-REC-04`, `KB-D12-2`, `KB-G1-MINECRAFT`, `KB-G1-SERVER-JAR-CATALOG`,
  `KB-G5-10`, `KB-PERF-01`.