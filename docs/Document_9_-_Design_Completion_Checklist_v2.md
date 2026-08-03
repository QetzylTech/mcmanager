Document 9: Design Completion Checklist (Revision 2 — Reconciled with Actual Project State)

Purpose
- Track remaining work required to fully complete the design documentation before implementation.
- Acts as the master design TODO list.
- This revision replaces Revision 1 wholesale rather than amending it — Revision 1 predated Documents 6, 7, and 8's full expansion and Document 10's creation, and every checklist line in it was stale.

Status Legend: `[ ]` Not Started `[~]` In Progress `[x]` Complete

Completed / Current Documents

- [x] Document 1 - Legacy Requirements (historical reference; superseded in places by Docs 2-5 per Document 10)
- [x] Document 2 - Product Requirements
- [x] Document 3 - System Architecture
- [x] Document 4 - Style Guide (Revision 2 — Status Indicator component added; full standalone document, verified against the original)
- [x] Document 5 - Navigation & Workflow (Revision 2 — sync status/retry-history views added; full standalone document, reconciled against the verified original after a mid-project gap where only inferred content was available)
- [x] Document 6 - Domain Model (substantially complete — see checklist below for the one open item)
- [x] Document 7 - Database Schema & Persistence Design (substantially complete — see checklist below for the one open item)
- [x] Document 8 - Application Services & Operation Flows (substantially complete — see checklist below for open items)
- [x] Document 9 - This document
- [x] Document 10 - Precedence & Conflict Resolution

Reference-only materials (not part of the numbered chain, per Document 10 §1): `ISO/IEC 25010`, `legacyARCHITECTURE.md`, `legacyImplementation.txt`, `ARCHITECTURE.md`.

------------------------------------------------------------------------

Document 6 Expansion (Domain Model)

- [x] Complete domain glossary.
- [x] Define all aggregate roots.
- [x] Define all entities (21 total: 16 original/formalized + `MissedRunRecord`, `NotificationRead`, `SyncTarget`, `SyncRecord`, `SyncAttempt`).
- [~] Define all value objects. Three formally typed (`Username`, `SecretRef`, `EndReason`); several more fields are candidates (trigger_type, notification severity, sync outcome enum, etc.) but not yet formally typed. Recommend doing this alongside Doc 7's DDL-authoring pass rather than as a standalone task.
- [x] Define ownership rules.
- [x] Define entity lifecycles.
- [x] Define state machines (WorldInstance, Operation, RuntimeSession, User, ClientSession).
- [x] Define domain events.
- [x] Define business invariants, including the Global Deletion & Retention Model (Tier 1 permanent / Tier 2 soft-then-Cleanup-only-hard-delete).
- [x] Add traceability to Documents 2-5.

------------------------------------------------------------------------

Document 7 Expansion (Database Schema)

- [x] Produce full ER diagram.
- [x] Fully specify every table (27 total).
- [x] Define every column.
- [x] Specify SQLite data types.
- [x] Define primary keys.
- [x] Define foreign keys.
- [x] Define indexes.
- [x] Define uniqueness constraints.
- [x] Define cascade behaviors (no `ON DELETE CASCADE` anywhere; FK enforcement = deletability boundary).
- [x] Define migration strategy in detail.
- [x] Define schema versioning.
- [x] Define startup reconciliation process.
- [x] Add example records.
- [x] Review normalization.
- [x] Review performance considerations.
- [~] One open item: the `permissions` table's "exactly one of `role_id`/`user_id`" rule is stated as an application-enforced invariant rather than an actual SQLite `CHECK` constraint. Should be written as real DDL (`CHECK ((role_id IS NOT NULL) != (user_id IS NOT NULL))`-style) when the schema is actually created, not left as prose.

------------------------------------------------------------------------

Document 8 Expansion (Application Services)

- [x] Expand every application service (16 total, including `SyncService`).
- [x] Define service responsibilities.
- [x] Define service boundaries.
- [x] Define command flow for every operation (11 types: CreateWorld, Start, Stop, Kill, Backup, Restore, Cleanup, Sync, ConfigEdit, CrashDetected, DeleteWorld).
- [x] Define query responsibilities.
- [~] Add sequence diagrams. Covered: Start, Backup, Restore, Cleanup, Sync, Crash Detection. Deferred: ConfigEdit, Kill, CreateWorld, DeleteWorld — same structural shape as diagrams already drawn, lower value to draw out individually.
- [x] Expand scheduler behavior.
- [x] Define retry policies.
- [x] Define timeout behavior.
- [x] Define cancellation behavior.
- [x] Define failure recovery.
- [x] Define concurrency rules (full conflict matrix, resolving the gap Doc 3 §7.3 originally flagged).
- [x] Define notification pipeline.
- [x] Define audit pipeline.
- [x] Map services to domain entities.
- Two items remain explicitly deferred to a dedicated polishing session (not blocking, but not done): exact numeric timeout/retry/scheduler-tick values (currently candidates, not locked constants), and the four deferred sequence diagrams above.

------------------------------------------------------------------------

Cross-document Review

- [x] Ensure terminology is consistent. (Doc 10 resolved the nav-alert, secrets-storage, and modal-taxonomy points; pane-terminology and modal-taxonomy "conflicts" were clarified as non-conflicts.)
- [x] Ensure naming is consistent.
- [x] Remove duplicated requirements. (Doc 10 is the authoritative arbiter going forward; see its Change Log Convention for how new duplicates/conflicts get handled.)
- [x] Verify navigation supports workflows. (Doc 5 Revision 2 closed the one gap found — sync status had no UI hook — and has since been reconciled against its verified original.)
- [x] Verify style guide supports UI layouts. (Doc 4 Revision 2 closed the one gap found — no formal status-indicator/badge component existed despite being assumed by Docs 1 and 5.)
- [x] Verify architecture supports requirements.
- [x] Verify persistence supports domain model. (Doc 7 is a direct, checked translation of Doc 6.)
- [x] Verify services align with persistence. (Doc 8's service-to-entity mapping table is checked against Doc 7's actual table list.)

------------------------------------------------------------------------

Implementation Readiness

Before coding, verify:

- [x] Domain model is complete.
- [x] Database schema is complete.
- [~] Service layer is complete. (Substantially — two items deferred to polishing session, see above.)
- [ ] API contract is complete. Not started. No route list, request/response shapes, SSE topic/payload catalog, or error-code catalog exists yet, despite Doc 2 §10.1 requiring structured error codes. This is the largest remaining gap before coding should start.
- [x] Security model is complete. (Doc 6 User/Role/Permission/ClientSession model, Doc 8 AuthenticationService/AuthorizationService, Doc 2 §8 requirements — all aligned.)
- [~] Error handling strategy exists. Doc 2 §10.1 requires short error codes with an expandable "more details" view, and Doc 7/8 support this structurally (`operations.error_code`, `operations.message`, `audit_records.payload`) — but no actual catalog of error codes exists yet.
- [x] Logging strategy exists. (Audit pipeline in Doc 8 §10, structured `audit_records` in Doc 7.)
- [ ] Testing strategy exists. Not started — no test pyramid, no mapping of tests to the ISO/IEC 25010 characteristics the project cares about, no acceptance-criteria-to-test mapping.
- [ ] Directory structure finalized. `ARCHITECTURE.md` states layering rules (`routes -> commands/queries -> services -> ports -> infrastructure -> platform`) but no concrete folder layout has been produced.
- [~] Coding standards finalized. `ARCHITECTURE.md` covers high-level rules; no linting/formatting/style-tool specifics exist yet.

------------------------------------------------------------------------

Known open items carried forward (not new, but not yet actioned)

- The platform process-control adapter (spawn/track/kill a Java process and tail its stdout without `systemd`/`journalctl`, cross-platform) has never been prototyped. This was flagged early as the single highest-risk unknown in the project and remains unaddressed.
- A minimal API contract (routes, payloads, SSE topics, error codes) — see Implementation Readiness above.
- Testing strategy and directory structure — see Implementation Readiness above.

Completion Goal

The design phase is considered complete when Documents 2 through 10 form a coherent specification that allows implementation with minimal architectural decision-making during development. By that standard, the documentation is close: the domain model, schema, and service layer are substantially locked, and what remains (API contract, testing strategy, directory structure, the process-control adapter spec) is implementation-adjacent scaffolding rather than open design questions.
