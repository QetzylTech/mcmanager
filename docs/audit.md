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
   Keep this file as the dated audit record or replace it when starting the
   next audit; do not maintain task status separately here.

## Current audit draft

**Status:** Findings transferred to `WORKBOARD.md`; retain this dated audit
record for the 2026-11-19 implementation review.
**Scope:** Known unbuilt application components and recent implementation
claims arising from Documents 5, 8, 10, and the 2026-11-19 code follow-up.
**Date:** 2026-11-19

**Criteria and sources examined:** `docs/WORKBOARD.md`, Documents 5, 8, and
10, `app/web/api/administration.py`, `app/web/api/backup_catalogs.py`,
`app/web/api/server_properties.py`, `app/web/api/manager_content.py`,
`app/web/middleware.py`, `app/services/diagnostics.py`, and
`app/shell/static/operator_ui.js`.

**Limitations:** Focused catalog API checks passed (11), and a live browser
check confirmed theme switching, notification dropdown rendering, step-up
confirmation, and global cleanup-policy submission. The added Node browser
regression could not be run because Node is unavailable. Product-policy
questions are not treated as verified implementation defects.

### Findings

- **AUD-2026-11-19-01 — Global cleanup-policy management (resolved)**
  - **Resolution:** Manager-wide cleanup-policy GET/PATCH routes and the
    Manager Maintenance editor are implemented, including versioned
    ConfigEdit behavior and step-up enforcement. Focused catalog API checks
    passed (11).
  - **Transfer:** `KB-G5-CLEANUP-POLICY-API` is marked Implemented in
    `WORKBOARD.md`. Stale-world and log cleanup remain separately blocked on
    explicit policy decisions.
- **AUD-2026-11-19-02 — Stale-world and log cleanup remain unsupported**
  - **Verified gap:** Cleanup currently accepts backups only; other scopes
    return `CLEANUP_SCOPE_UNSUPPORTED`.
  - **Decision needed:** Candidate eligibility, retention, exclusions, and
    destructive safeguards for stale worlds and logs are not fully specified.
  - **Transfer:** Policy decision and implementation are tracked by
    `KB-G5-CLEANUP-POLICY` and `KB-G5-CLEANUP-SCOPES`.
- **AUD-2026-11-19-03 — Manager lifecycle operations are not implemented**
  - **Verified gap:** Manager restore, restart, update, and rollback routes
    return `NOT_IMPLEMENTED`; Manager Backup exists.
  - **Decision needed:** Restore/recovery scope, host supervision, trusted
    update verification, schema compatibility, and rollback behavior require
    product/operations contracts.
  - **Transfer:** Tracked by `KB-G5-8`.
- **AUD-2026-11-19-04 — Session settings visibility is undefined**
  - **Unresolved contract question:** Document 10 requests settings visibility
    in the session response, but no governing policy defines its derivation or
    shape.
  - **Transfer:** Decision and contract parity are tracked by
    `KB-G5-API-CONTRACT`.
- **AUD-2026-11-19-05 — Full API contract parity remains unverified**
  - **Verification gap:** The full route/auth/schema/error mapping inventory
    has not been completed, so further concrete gaps may exist.
  - **Transfer:** Tracked by `KB-G5-API-CONTRACT`.
- **AUD-2026-11-19-06 — Recent feature follow-up lacks feature acceptance**
  - **Verified limitation:** Server-properties editing, permission-grant
    enforcement, diagnostics/version metadata, sync-target CRUD,
    documentation/log browsing, and per-world and manager-wide
    cleanup-policy editing have implementations. Focused API checks and live
    browser validation cover the cleanup-policy and shell interactions; full
    feature-specific/browser-suite acceptance remains outstanding.
  - **Transfer:** Acceptance remains with the owning implementation cards,
    including `KB-G5-3`, `KB-G5-6`, and `KB-G5-API-CONTRACT`.

### Transfer checklist

- [x] Each actionable finding has a corresponding task in `WORKBOARD.md`.
- [x] Findings requiring a product or policy decision are tracked as tasks.
- [x] Verification limits and unresolved contract questions are recorded above.
