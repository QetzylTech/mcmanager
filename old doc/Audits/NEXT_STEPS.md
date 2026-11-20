# Reconciliation closure plan

This plan is ordered to avoid coding against an unstable specification. Checkboxes are intentionally open: generation of inventories does not close semantic verification.

## R0 — Freeze the audit baseline
- [ ] Preserve the uploaded repository snapshot and record its commit/hash.
- [ ] Re-run tests and static gates in a reproducible environment; attach raw logs.
- [ ] Reconfirm the eight failures and coverage values in `docs/audit.md`; do not carry them forward as current results without a new run.
- [ ] Confirm whether `app/data/secrets.key`, SQLite DB/WAL/SHM files are tracked or distributed; remove runtime secrets/data from source archives and rotate exposed credentials where appropriate.

## R1 — Normalize the governing specifications
- [ ] Establish precedence between `ARCHITECTURE.md` and Documents 4–14.
- [ ] Resolve the runtime documentation location conflict (`docs/` vs `app/docs/`).
- [ ] Reconcile Document 8's two-transfer sync concurrency requirement with the current byte reservation implementation.
- [ ] Correct all stale WBS references (`src/mcmanager/` → actual approved package layout) and dependency claims.
- [ ] Classify every item in `old doc/` and `Prototypes/` as historical, reference-only, or active.
- [ ] Update Document 10 for additional routes not currently in its route catalog: `/api/pages`, `/api/worlds/{world_id}/cleanup-policy`, `/api/supervisor/tick`, or explicitly record their approved alternate contract location.
- [ ] Keep the five SSE endpoints reconciled to Document 10's SSE section; do not duplicate them as ordinary route-catalog entries unless the spec calls for it.

## R2 — Complete requirement inventory
- [ ] Extend `planned_component_inventory.csv` with every normative requirement, invariant, state transition, API schema, SSE topic, UI workflow, adapter capability, security rule, and acceptance criterion from `ARCHITECTURE.md` and Documents 4–14.
- [ ] Give each requirement a stable `REQ-*` identifier.
- [ ] Split compound requirements into independently verifiable statements.
- [ ] Record the source section and exact wording/summary without paraphrasing away constraints.

## R3 — Complete pseudocode
- [ ] For each requirement, identify the owning component and pseudocode entry.
- [ ] Write pseudocode for each service method, command/query, route, background job, adapter operation, UI workflow and state transition.
- [ ] Include preconditions, inputs, outputs, side effects, transaction boundaries, authorization, concurrency, errors, compensation/recovery and emitted events.
- [ ] Map each pseudocode entry to requirement IDs.
- [ ] Review pseudocode against the actual approved specification, not just current implementation.

## R4 — Source reconciliation
- [ ] For each requirement/pseudocode entry, map exact source symbol(s) and line range(s).
- [ ] Record `MISSING`, `PARTIAL`, `PRESENT_UNVERIFIED`, `VERIFIED`, `DEFERRED`, or `APPROVED_DEVIATION`.
- [ ] Confirm service responsibility ownership and port boundaries.
- [ ] Verify Document 6 persistence-backed concepts against schema constraints and transaction behavior, respecting §7's hybrid model.
- [ ] Verify all 28 schema tables, indexes, FKs, deletion tiers, migrations and startup reconciliation behavior.

## R5 — Test reconciliation
- [ ] Map each requirement and source symbol to one or more named tests.
- [ ] Confirm tests assert behavior and failure cases, not merely call the code.
- [ ] Add stable requirement/component IDs to test names, markers, or metadata.
- [ ] Record latest run ID, environment, command, result and evidence artifact.
- [ ] Enforce Document 11's per-module and overall coverage floors.
- [ ] Complete API, service, concurrency, browser, E2E, cross-platform, live Minecraft, security, proxy and performance acceptance.

## R6 — Close known functional gaps
- [ ] Manager restore/restart/update/rollback contracts and implementations.
- [ ] Stale-world and log cleanup policies, preview and safe deletion.
- [ ] Explicit sync concurrency admission limit or approved spec revision.
- [ ] Remaining command/query architecture or approved consolidation decision.
- [ ] Remaining shell workflows and browser acceptance.
- [ ] Complete route/auth/schema/error/SSE parity.

## R7 — Make tracking evidence-backed
- [ ] Every workboard card links to requirement IDs.
- [ ] Every Done card links to source and passing test evidence.
- [ ] Blocked/Review/To Do statuses match actual implementation state.
- [ ] WBS remains a work breakdown, not the detailed traceability register.
- [ ] Generate a report from the traceability matrix rather than manually maintaining competing completion counts.

## Exit criteria
The reconciliation is complete only when every in-scope requirement has:
1. An authoritative specification reference.
2. A complete pseudocode reference.
3. An implementation status and exact source mapping.
4. A test mapping and passing evidence, or an explicit approved deferral/deviation.
5. A corresponding workboard disposition.

No overall completion percentage should be published until the inventory denominator is stable and every row has a defensible status.
