# Document 9: Design Completion Checklist

Purpose
- Track remaining work required to fully complete the design before implementation.
- Acts as the master design TODO list.

Status Legend: `[ ]` Not Started `[~]` In Progress `[x]` Complete

Completed / Current Documents

- [x] Document 1 — Legacy Requirements (historical reference; superseded in places by Docs 2–5 and Doc 10)
- [x] Document 2 — Product Requirements
- [x] Document 3 — System Architecture
- [x] Document 4 — Style Guide
- [x] Document 5 — Navigation & Workflow
- [x] Document 6 — Domain Model (substantially complete — one open item, see below)
- [x] Document 7 — Database Schema & Persistence Design (substantially complete — one open item, see below)
- [x] Document 8 — Application Services & Operation Flows (substantially complete — see open items below)
- [x] Document 9 — This document
- [x] Document 10 — Precedence & Conflict Resolution
- [x] Document 11 — Concurrency, Locking & Conflict Resolution Model

Reference-only materials (outside the numbered chain, per Doc 10 §1): `ISO/IEC 25010`, `legacyARCHITECTURE.md`, `legacyImplementation.txt`, `ARCHITECTURE.md`, `Design_Changelog.md`.

------------------------------------------------------------------------

Document 6 Expansion (Domain Model)

- [x] Complete domain glossary (§3.1, canonical terminology source).
- [x] Define all aggregate roots (§6).
- [x] Define all entities (21 total: 16 original/formalized + `MissedRunRecord`, `NotificationRead`, `SyncTarget`, `SyncRecord`, `SyncAttempt`).
- [~] Define all value objects. Three formally typed (`Username`, `SecretRef`, `EndReason`); several more fields are candidates (trigger_type, notification severity, sync outcome enum, etc.). Recommend doing alongside Doc 7's DDL-authoring pass.
- [x] Define ownership rules (§3.2).
- [x] Define entity lifecycles (§2).
- [x] Define state machines (WorldInstance, Operation, RuntimeSession, User, ClientSession).
- [x] Define domain events (§3, per entity).
- [x] Define business invariants, including the Global Deletion & Retention Model (Tier 1 permanent / Tier 2 soft-then-Cleanup-only-hard-delete, §0/§4).
- [x] Add traceability to Documents 2–5 (§7).

------------------------------------------------------------------------

Document 7 Expansion (Database Schema)

- [x] Produce full ER diagram (§3).
- [x] Fully specify every table (27 total, §2).
- [x] Define every column (§2).
- [x] Specify SQLite data types (§0, §2).
- [x] Define primary keys, foreign keys, indexes, uniqueness constraints (§2, §4).
- [x] Define cascade behaviors (no `ON DELETE CASCADE` anywhere; FK enforcement = deletability boundary).
- [x] Define migration strategy in detail (§5) and schema versioning (§2.3, §5).
- [x] Define startup reconciliation process (§6).
- [x] Add example records (§7).
- [x] Review normalization (§8) and performance considerations (§9).
- [~] One open item: the `permissions` table's "exactly one of `role_id`/`user_id`" rule must be written as real SQLite DDL — `CHECK ((role_id IS NOT NULL) != (user_id IS NOT NULL))` — when the schema is created, not left as prose (stated at §2.21).

------------------------------------------------------------------------

Document 8 Expansion (Application Services)

- [x] Expand every application service (16 total, including `SyncService`, §1).
- [x] Define service responsibilities and boundaries (§1).
- [x] Define command flow for every operation (11 types, §2).
- [x] Define query responsibilities (§3).
- [~] Add flow documentation (§4): Start drawn as a canonical sequence diagram; the other ten operations covered as compact flow summaries. Deferred: full diagrams for ConfigEdit, Kill, CreateWorld, DeleteWorld — same structural shape as the canonical one.
- [x] Expand scheduler behavior (§5).
- [x] Define retry, timeout, and cancellation policies (§6).
- [x] Define failure recovery (§8).
- [x] Define concurrency rules — resolved wholesale: Document 11 is authoritative (§7).
- [x] Define notification pipeline (§9) and audit pipeline (§10).
- [x] Map services to domain entities (§11).
- Two items remain deferred to a dedicated polishing session (not blocking): exact numeric timeout/retry/scheduler-tick values (currently candidates, not locked constants), and the four deferred sequence diagrams above.

------------------------------------------------------------------------

Cross-document Review

- [x] Ensure terminology is consistent. (Doc 10 resolved the nav-alert, secrets-storage, and modal-taxonomy points; pane-terminology and modal-taxonomy points were clarified as non-conflicts.)
- [x] Ensure naming is consistent.
- [x] Remove duplicated requirements. (Doc 10 is the authoritative arbiter; see its Change Log Convention.)
- [x] Verify navigation supports workflows. (Notification dropdown, world search/filter, ManagerBackup UI entry point are in Doc 5.)
- [x] Verify style guide supports UI layouts. (Status Indicator component in Doc 4 §17.)
- [x] Verify architecture supports requirements.
- [x] Verify persistence supports domain model. (Doc 7 is a direct, checked translation of Doc 6.)
- [x] Verify services align with persistence. (Doc 8's service-to-entity mapping is checked against Doc 7's table list.)

------------------------------------------------------------------------

Implementation Readiness

Before coding, verify:

- [x] Domain model is complete.
- [x] Database schema is complete.
- [~] Service layer is complete. (Substantially — two items deferred to a polishing session, see above.)
- [ ] API contract is complete. Not started. No route list, request/response shapes, SSE topic/payload catalog, or error-code catalog exists yet, despite Doc 2 §10.1 requiring structured error codes. Largest remaining gap before coding.
- [x] Security model is complete. (Doc 6 User/Role/Permission/ClientSession model, Doc 8 AuthenticationService/AuthorizationService, Doc 2 §8 — aligned.)
- [~] Error handling strategy exists. Doc 2 §10.1 requires short error codes with an expandable "more details" view; Doc 7/8 support this structurally (`operations.error_code`, `operations.message`, `audit_records.payload`) — but no actual catalog of error codes exists yet.
- [x] Logging strategy exists. (Audit pipeline Doc 8 §10, structured `audit_records` Doc 7.)
- [ ] Testing strategy exists. Not started — no test pyramid, no mapping of tests to the ISO/IEC 25010 characteristics, no acceptance-criteria-to-test mapping.
- [ ] Directory structure finalized. `ARCHITECTURE.md` states layering rules (`routes -> commands/queries -> services -> ports -> infrastructure -> platform`) but no concrete folder layout has been produced.
- [~] Coding standards finalized. `ARCHITECTURE.md` covers high-level rules; no linting/formatting/style-tool specifics exist yet.

------------------------------------------------------------------------

Known open items carried forward (not new, but not yet actioned)

- The platform process-control adapter (spawn/track/kill a Java process and tail its stdout without `systemd`/`journalctl`, cross-platform) has never been prototyped. Flagged early as the single highest-risk unknown in the project; remains unaddressed.
- A minimal API contract (routes, payloads, SSE topics, error codes) — see Implementation Readiness above.
- Testing strategy and directory structure — see Implementation Readiness above.

Completion Goal

The design phase is considered complete when Documents 2–11 form a coherent specification that allows implementation with minimal architectural decision-making during development. By that standard the documentation is close: the domain model, schema, and service layer are substantially locked, and what remains (API contract, testing strategy, directory structure, the process-control adapter spec) is implementation-adjacent scaffolding rather than open design questions.
