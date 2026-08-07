Document 9: Design Completion Checklist

Purpose
- Track remaining work required to fully complete the design documentation before implementation.
- Acts as the master design TODO list.
- Only open or deferred items retain detail; completed items reference their defining document instead of restating the work.

Status Legend: `[ ]` Not Started `[~]` In Progress

All of Documents 1-11 and `ARCHITECTURE.md` are complete, with the open items below.

------------------------------------------------------------------------

Open Items

Doc 6:
- [~] Finish typing the remaining value objects (`trigger_type`, notification severity, sync outcome enum, etc. — three already typed). Minor/mechanical; can proceed alongside Doc 7's DDL-authoring pass.

Doc 8 (deferred to polishing session, not blocking):
- [~] Exact numeric timeout/retry/scheduler-tick values (currently candidates, not locked constants).
- [~] Sequence diagrams for ConfigEdit, Kill, CreateWorld, DeleteWorld (same structural shape as the six already drawn).

Implementation Readiness
- [x] Domain model complete. (Doc 6.)
- [x] Database schema complete. (Doc 7.)
- [~] Service layer substantially complete. (Doc 8, two deferred items above.)
- [ ] API contract: Not started. No route list, request/response shapes, SSE topic/payload catalog, or error-code catalog — the largest remaining gap before coding.
- [x] Security model complete. (Doc 6 User/Role/Permission/ClientSession; Doc 8 Authentication/Authorization; Doc 2 §8.)
- [~] Error handling strategy: structure exists (`operations.error_code`/`message`, `audit_records.payload`, Doc 2 §10.1) but no actual error-code catalog.
- [x] Logging strategy complete. (Doc 8 §10 audit pipeline, Doc 7 `audit_records`.)
- [ ] Testing strategy: Not started — no test pyramid, no ISO/IEC 25010 characteristic mapping, no acceptance-to-test mapping.
- [ ] Directory structure: Not finalized — `ARCHITECTURE.md` states the layering rules (`routes -> commands/queries -> services -> ports -> infrastructure -> platform`) but no concrete folder layout has been produced.
- [~] Coding standards: high-level rules in `ARCHITECTURE.md`; no linting/formatting/style-tool specifics.

------------------------------------------------------------------------

Known open items carried forward (not new, not yet actioned)

- The platform process-control adapter (spawn/track/kill a Java process and tail its stdout without `systemd`/`journalctl`, cross-platform) has never been prototyped — the single highest-risk unknown in the project.
- API contract and error-code catalog — see Implementation Readiness.
- Testing strategy and directory structure — see Implementation Readiness.

Completion Goal

The design phase is considered complete when Documents 2 through 11 form a coherent specification that allows implementation with minimal architectural decision-making during development. By that standard the documentation is close: domain model, schema, and service layer are locked, and what remains (API contract, testing strategy, directory structure, process-control adapter spec) is implementation-adjacent scaffolding rather than open design questions.
