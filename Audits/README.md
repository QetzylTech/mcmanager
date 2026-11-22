# Audit evidence

`docs/WORKBOARD.md` is the authoritative current task and verification tracker.
This directory contains current audit findings, migration summaries, realignment
notes, verification logs, and supporting evidence. It is not a separate task
status tracker.

Development audits follow
[`docs/AGENT_DEVELOPMENT_WORKFLOW_SPEC.md`](../docs/AGENT_DEVELOPMENT_WORKFLOW_SPEC.md),
subject to the precedence of numbered product documents and
`docs/ARCHITECTURE.md`.

## Current and historical records

Current records describe the repository state against which they were written.
Historical records remain intact and must not be rewritten to make older audit
formats or findings look current. Historical audits under `old doc/Audits/` and
older reports in this directory are provenance only until their findings are
reconciled against current source, tests, governing documents, and the active
workboard.

Do not copy stale baseline counts or platform results into current summaries
without identifying the candidate revision and rerunning or retaining exact
reproducible evidence.

## Audit record format

Every new audit should identify:

- Audit ID and date.
- Candidate commit or source revision.
- Scope and workboard task IDs.
- Governing requirements reviewed.
- Exact checks and evidence locations.
- Findings and severity.
- Reviewer identity and outcome.
- Remediation or follow-up task references.

Audit outcomes are `PASS`, `PASS_WITH_FINDINGS`, `FAIL`, `BLOCKED`, or
`NOT_APPLICABLE`. Finding severities are `BLOCKER`, `MAJOR`, `MINOR`, or
`OBSERVATION`.

Audit reports should assess requirement compliance, architecture and boundary
compliance, correctness and safety, testing and evidence, and maintainability
and scope.

## Findings and closure

Actionable findings are transferred to existing bounded workboard cards or new
cards with acceptance criteria and an owner. A verbal claim or implementation
summary does not close a finding. Remediation changes invalidate prior affected
verification and require re-audit. Blocked findings remain open until the exact
environment, dependency, fixture, or decision is available.

Closing a finding requires independent verification, durable evidence, and a
workboard status update. `Audits/` preserves the audit history; it does not
control task status.

## Current records

- [Full repository audit - 2026-11-22](FULL_AUDIT_2026-11-22.md)
- [Independent workflow migration audit - 2026-11-22](INDEPENDENT_AUDIT_2026-11-22.md)
- [Full repository audit — 2026-11-21](FULL_AUDIT_2026-11-21.md)
- [2026-11-20 realignment and verification](REALIGNMENT_2026-11-20.md)
- [2026-11-20 verification log](verification_log_2026-11-20.md)
- [Current requirement traceability ledger](reconciliation_traceability.csv)
- [Historical audit snapshot index](../old%20doc/REALIGNMENT_HISTORY.md)
