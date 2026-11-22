# MCManager Agent Development Workflow Specification

**Document ID:** ADWS-001  
**Version:** 1.0  
**Status:** Approved  
**Date:** 2026-11-22  
**Applies to:** AI-agent-assisted development in the MCManager repository

---

## 1. Purpose

This specification defines the controlled workflow for planning, assigning, implementing, integrating, auditing, correcting, verifying, and committing changes to MCManager.

Its purpose is to ensure that:

- All agents work from the same approved product requirements and architecture.
- Work is divided into bounded, traceable tasks.
- Agents do not make conflicting changes to shared files or interfaces.
- Implementation claims are supported by reproducible evidence.
- Review and acceptance are independent of implementation.
- The committed repository state has passed the required checks.
- Project state can be recovered from repository records without relying on chat history.

This document governs the **development process**. It does not replace numbered product requirements, `docs/ARCHITECTURE.md`, technical contracts, security rules, or release criteria. `docs/WORKBOARD.md` is the live task and evidence tracker; this specification governs how that tracker and the development lifecycle are used.

## 2. Scope

This specification applies to:

- AI agents that inspect, plan, implement, test, review, audit, document, or integrate repository changes.
- Human operators who assign work, approve decisions, resolve blockers, or authorize commits.
- All tracked source code, tests, configuration, documentation, deployment assets, and development tooling.

All work remains subject to the repository boundary in `AGENTS.md`.

The production application remains under `app/`. Development tooling, tests, documentation, prototypes, audit records, and generated development evidence must not be treated as production application content unless an approved product requirement says otherwise.

## 3. Governing documents and precedence

The following repository records remain authoritative for their stated purposes:

| Record | Authority |
|---|---|
| Numbered product documents | Product requirements, behavior, contracts, quality requirements, and acceptance criteria |
| `docs/ARCHITECTURE.md` | Architecture index, cross-cutting constraints, architectural rules, and build gates |
| `docs/wbs.txt` | Work-package decomposition and dependency context, subject to current numbered documents and workboard reconciliation |
| `docs/WORKBOARD.md` | Authoritative current task status, ownership, dependencies, and task evidence |
| `AGENTS.md` | Repository edit boundary and rules that apply to every agent |
| `Audits/` | Audit findings, verification records, and supporting evidence; not an independent task-status tracker |
| `old doc/`, historical pseudocode, and archived prototypes | Historical reference only unless explicitly reinstated by an approved decision |

When sources conflict:

1. Stop work that depends on the conflicting interpretation.
2. Identify the exact conflicting statements and their source locations.
3. Follow the precedence rules in the governing product documents and architecture index.
4. Do not silently choose the interpretation that is easiest to implement.
5. Record the resolution in the governing document.
6. Update dependent WBS, workboard, implementation, and audit references as required.

This workflow specification must not silently amend product behavior or architecture. If this specification conflicts with a numbered product document, the numbered product document takes precedence. Update this specification after an approved process change.

## 4. Core operating principles

### 4.1 Repository state is the source of truth

Agents must not rely on conversation history as the only record of requirements, task ownership, decisions, test results, or completion.

Before acting, an agent must inspect the current repository state and the relevant governing records.

### 4.2 One bounded task has one accountable owner

Each active workboard card must have one accountable owner. Supporting agents may be assigned, but they must not independently change the same task or shared files without coordination.

### 4.3 Plan before implementation

An agent must not begin implementation until the task is sufficiently defined, dependencies are complete, and its scope is understood.

### 4.4 Evidence before status

A task's status must reflect its actual state. A claim that code is complete is not evidence that acceptance criteria pass.

### 4.5 Independent acceptance

The implementing agent may submit work and provide evidence. It must not be the sole authority that approves its own work as accepted.

### 4.6 No silent scope expansion

Agents must not add unrelated refactoring, architectural changes, dependency changes, formatting sweeps, or feature work to a bounded task. Raise additional work as a separate proposal or workboard card.

### 4.7 Preserve uncertainty

Use explicit states such as `NOT_RUN`, `NOT_VERIFIED`, `BLOCKED`, `NOT_APPLICABLE` (with reason), and `FAILED`. Do not convert missing evidence into a pass.

### 4.8 Do not weaken acceptance criteria silently

An agent must not lower a documented quality threshold, skip a required test category, alter a security boundary, or redefine completion to make a task pass. A change requires an approved decision in the governing source.

## 5. Roles and authority

Roles describe responsibilities, not necessarily separate models or separate running processes. One agent may perform more than one role when the separation-of-duties rules below are preserved.

| Role | Primary responsibilities | Authority |
|---|---|---|
| Product/Design authority | Clarify intended behavior and resolve product decisions | Approves product-level decisions |
| Planner | Decompose approved requirements into bounded work | Proposes tasks, dependencies, and acceptance criteria |
| Coordinator | Assign work, track dependencies, prevent ownership conflicts, maintain workflow state | Controls task assignment and coordination |
| Implementer | Modify assigned code, tests, or documentation and report evidence | Implements only its assigned scope |
| Integrator | Combine completed work and resolve integration issues | Controls integration activity within approved scope |
| Auditor/Reviewer | Independently assess requirement compliance, implementation quality, and evidence | Recommends acceptance, rejection, or remediation |
| Release controller | Confirm final gates and authorize repository commit/release actions | Authorizes commit after required approvals |
| Human operator | Resolve escalations and approve decisions reserved for human authority | Final authority where product, security, data-loss, or release policy requires it |

### 5.1 Separation of duties

- The implementer must not be the sole reviewer of its own task.
- The planner must not treat an agent's estimate or completion claim as acceptance evidence.
- The coordinator must not override a product or architecture decision.
- The auditor must not silently modify implementation while performing an audit. If a correction is needed, record a finding and return it for remediation.
- The release controller must not commit work that has not passed the required acceptance and final verification gates.
- Human approval is required for unresolved product decisions, changes to governing contracts, security-sensitive exceptions, destructive operations, and release exceptions.

## 6. End-to-end workflow

The project cycle is:

1. Design
2. Work Breakdown Planning
3. Pre-execution Validation
4. Work Assignment and Execution
5. Integration and Verification
6. Independent Audit
7. Remediation and Cleanup
8. Final Verification
9. Commit
10. Repeat

A stage may be repeated when its exit criteria are not met. A task may be blocked at any stage when a required dependency, decision, environment, credential, fixture, or external system is unavailable.

### 6.1 Stage 1 — Design

**Objective:** Establish what must change and why, without prematurely prescribing implementation details unless the architecture requires them.

**Inputs:**
- Approved product requirements.
- Current architecture and technical contracts.
- Existing implementation and test behavior.
- Open audit findings and approved change requests.

**Activities:**
- Identify the requirement or defect.
- Inspect current behavior and relevant code.
- Identify affected subsystems, interfaces, data, security boundaries, and user workflows.
- Identify compatibility and migration implications.
- Resolve ambiguity before work is decomposed.
- Record any approved departure from the existing architecture.

**Required outputs:**
- A clear problem statement.
- Expected behavior and non-goals.
- Affected requirements and architecture references.
- Known constraints and risks.
- Test and verification expectations.
- An approved decision where product or architecture behavior changes.

**Exit criteria:**
- The intended outcome is unambiguous.
- Conflicting requirements are resolved or explicitly blocked.
- The change is consistent with governing documents, or an approved change to those documents exists.

**Failure path:** Return to design or mark the dependent work blocked. Do not ask implementers to guess.

### 6.2 Stage 2 — Work Breakdown Planning

**Objective:** Convert approved design into independently assignable and verifiable work.

**Activities:**
- Create or update WBS work packages where required.
- Create bounded workboard cards with stable IDs.
- Identify dependencies and sequencing.
- Identify files, modules, interfaces, schemas, and tests likely to change.
- Define acceptance criteria that can be checked.
- Identify integration points and shared-file conflicts.
- Identify platform, external-host, hardware, or credential requirements.

**Each workboard card must include:**
- Stable task ID and concise title.
- Requirement, numbered-document, architecture, and WBS references.
- Objective and bounded deliverable.
- Explicit in-scope and out-of-scope work.
- Dependencies.
- Expected file or subsystem scope, where known.
- Acceptance criteria.
- Required tests and evidence.
- External prerequisites and risks.
- Owner and status.

**Planning rules:**
- One card represents one bounded deliverable.
- Do not split feature tests away from the feature's owning task merely to make implementation appear complete.
- Standalone testing cards are appropriate for cross-cutting test infrastructure and documented release gates.
- Do not duplicate an existing open task. Extend or reconcile the existing card.
- Do not mark a dependency complete based only on a claim; use the workboard's accepted status and evidence.

**Exit criteria:**
- Tasks are bounded and traceable.
- Dependencies are explicit.
- Acceptance criteria are testable.
- Ownership conflicts are identified.
- The workboard is updated.

### 6.3 Stage 3 — Pre-execution Validation

**Objective:** Confirm that a task is ready to be assigned and implemented.

The coordinator or a designated validation agent checks:

- All required dependencies are `Done`.
- The governing requirements and relevant implementation have been read.
- The acceptance criteria are sufficiently precise.
- The task does not conflict with another active task's file or interface ownership.
- Required test fixtures, environments, credentials, and platform access are available.
- Existing behavior and regression risks are understood.
- The task does not rely on superseded plans or historical audit data as current truth.
- Any required product or architecture decision is already approved.

**Exit criteria:** The task is ready to be assigned.

**Failure path:** Return the task to planning or mark it `Blocked` with the exact blocker and the condition required to unblock it.

### 6.4 Stage 4 — Work Assignment and Execution

**Objective:** Implement the assigned deliverable within its approved scope.

**Before editing, the implementer must:**
1. Read `AGENTS.md`.
2. Read the current workboard and the assigned card.
3. Confirm that dependencies are `Done`.
4. Confirm that the card is not already owned by another active agent.
5. Set the card to `In Progress`, record its owner/session identifier, and update its date.
6. Inspect relevant source, tests, architecture, and contracts.
7. Confirm the intended files and integration points.

**During implementation, the implementer must:**
- Work only within the repository boundary.
- Follow the approved architecture and product contracts.
- Avoid unrelated changes.
- Preserve existing behavior unless the requirement changes it.
- Add or update tests for the behavior changed.
- Run focused tests during development.
- Record commands and actual results.
- Stop and report unexpected contract conflicts or scope expansion.
- Keep temporary artifacts in approved repository working locations.
- Avoid overwriting another agent's workboard edits; re-read the board before changing the assigned card.

**On completion, the implementer must provide:**
- Summary of changes.
- Files changed.
- Requirements and task IDs addressed.
- Tests executed, with exact commands and results.
- Tests not executed and why.
- Known limitations and residual risks.
- Any architecture or contract divergence.
- Relevant evidence locations.

The implementer then moves the card to `Review`, not `Done`.

**Exit criteria:** The implementation is ready for integration/review, and the evidence is recorded.

**Failure path:** If blocked, set `Blocked` and state the concrete blocker, its impact, and the condition required to resume. Do not claim completion.

### 6.5 Stage 5 — Integration and Verification

**Objective:** Verify that the candidate changes work with the current repository state and do not break dependent components.

**Activities:**
- Inspect the complete change set.
- Confirm that only intended files changed.
- Resolve merge or integration conflicts.
- Run focused tests for each changed area.
- Run relevant integration and regression tests.
- Run required static checks and architecture-boundary checks.
- Verify migrations, data compatibility, and rollback behavior where applicable.
- Verify platform-specific behavior where required.
- Confirm that test evidence corresponds to the candidate source revision.

**Rules:**
- A focused test pass does not replace required integration or regression tests.
- A mocked test does not establish live-host, deployment, or external-service acceptance.
- A no-coverage test run does not establish coverage compliance.
- A previous commit's result does not establish the current candidate's result.
- If integration requires changes outside the approved task scope, obtain coordination approval and update the task plan.

**Exit criteria:**
- Required integration checks pass, or outstanding failures are clearly recorded and assigned.
- No unexplained regression is accepted.
- The integrated candidate is ready for independent audit.

### 6.6 Stage 6 — Independent Audit

**Objective:** Determine whether the implementation satisfies its requirements and is suitable for acceptance.

The auditor must independently inspect the requirements, changes, tests, and evidence. It must not rely only on the implementer's summary.

**Audit dimensions:**

1. **Requirement compliance**
   - Does the implementation satisfy each acceptance criterion?
   - Are any requirements omitted or only partially implemented?
   - Does behavior match the approved product contract?

2. **Architecture and boundaries**
   - Are dependency directions and module boundaries respected?
   - Are ports, adapters, repositories, and service responsibilities consistent with approved architecture?
   - Are deviations documented and approved?

3. **Correctness and safety**
   - Are error paths, lifecycle transitions, concurrency, persistence, recovery, and data integrity handled?
   - Are security and authorization requirements preserved?
   - Are destructive or irreversible actions protected by the required controls?

4. **Testing and evidence**
   - Do tests cover the changed behavior and relevant failure cases?
   - Are results reproducible and tied to the correct source state?
   - Are external and platform-specific checks distinguished from mocked checks?
   - Are coverage and quality gates measured using the required method?

5. **Maintainability and scope**
   - Are changes bounded and understandable?
   - Is unrelated code modified?
   - Are temporary artifacts, dead code, and stale documentation introduced?

**Audit result must be one of:**
- `PASS` — all applicable acceptance checks are satisfied.
- `PASS_WITH_FINDINGS` — acceptance is satisfied, but non-blocking findings remain explicitly assigned or recorded.
- `FAIL` — one or more required acceptance checks fail.
- `BLOCKED` — required evidence or environment is unavailable.
- `NOT_APPLICABLE` — a check does not apply, with a reason.

A task cannot be accepted with a `FAIL` or `BLOCKED` result.

**Required audit record:**
- Audit ID and date.
- Candidate commit or source revision.
- Scope and task IDs.
- Governing requirements reviewed.
- Checks performed and exact evidence.
- Findings with severity and affected requirements.
- Result and reviewer identity.
- Remediation task references, where applicable.

**Finding severity:**
- `BLOCKER` — data loss, security breach, critical contract violation, unsafe behavior, or release-stopping failure.
- `MAJOR` — required behavior is missing or incorrect, or a required quality gate fails.
- `MINOR` — non-blocking defect or maintainability issue.
- `OBSERVATION` — improvement or risk note that does not fail acceptance.

Severity must be based on impact, not the number of findings.

### 6.7 Stage 7 — Remediation and Cleanup

**Objective:** Correct audit findings and leave the candidate coherent.

**Activities:**
- Convert actionable findings into bounded workboard tasks or link them to existing cards.
- Assign each finding an owner.
- Correct defects within the approved scope.
- Update tests to prevent recurrence.
- Update documentation where behavior or contracts changed.
- Remove task-specific temporary artifacts that are no longer needed.
- Reconcile duplicate, stale, or contradictory status and evidence records.
- Preserve audit history; do not rewrite historical results as if they were current.

**Rules:**
- Do not close a finding based on a verbal claim.
- Do not delete evidence needed to reproduce or understand a historical result.
- Do not use cleanup as permission for broad refactoring.
- Re-audit affected requirements when remediation changes behavior.
- A material implementation change invalidates prior verification for the affected scope.

**Exit criteria:** All blocking and major findings are resolved or explicitly remain open, and the candidate is ready for final verification. Any remaining minor findings must have an owner and disposition.

### 6.8 Stage 8 — Final Verification

**Objective:** Verify the exact candidate that will be committed.

Final verification must run after remediation and cleanup. It must not rely on results from an earlier candidate.

**Required checks, as applicable to the task and current release gate:**
- Focused unit and integration tests.
- Relevant full test suite.
- Coverage requirements from the governing quality document.
- Ruff, Black, isort, mypy, and import-linter checks where required by the current quality gate.
- Adapter/platform conformance.
- Browser or end-to-end tests.
- Security checks.
- Migration and data-integrity checks.
- Deployment and performance checks when required.
- Workboard and audit evidence reconciliation.

For every check, record:
- Exact command or procedure.
- Source revision or candidate identifier.
- Operating system and relevant runtime/tool versions.
- Result, including pass/fail/skip counts.
- Raw output or durable evidence location.
- Any limitation or reason not run.

**Exit criteria:**
- All mandatory checks for the task and release scope pass.
- No unresolved blocker or major finding remains.
- Evidence matches the exact candidate.
- Workboard status and audit records are consistent.

If a mandatory check cannot run, the task remains blocked or unaccepted. Do not substitute a different check without approval.

### 6.9 Stage 9 — Commit

**Objective:** Commit only the verified and accepted candidate.

**Pre-commit requirements:**
- The task is accepted by an independent reviewer.
- Required final verification has passed.
- The worktree and staged changes have been inspected.
- No unrelated or generated files are included.
- Workboard status and evidence are current.
- Audit findings have a recorded disposition.
- The commit message identifies the task or work package.

**Commit rules:**
- The release controller or explicitly authorized integrator performs the commit.
- Do not commit partially implemented or unreviewed work as complete.
- Do not combine unrelated tasks merely for convenience.
- Preserve task-to-commit traceability.
- Do not amend or rewrite shared history unless the repository's approved collaboration policy permits it.

**After commit:**
- Record the commit hash in the relevant workboard card.
- Update task status to `Done` only after acceptance and evidence requirements are satisfied.
- Record any remaining follow-up work as separate tasks.
- Confirm the committed tree contains the verified changes.

### 6.10 Stage 10 — Repeat

The coordinator selects the next ready task or work package based on:
- Dependency completion.
- Priority.
- Risk.
- Available agent capacity.
- File and interface ownership.
- Required external resources.

The next cycle begins from the current repository state, not from an earlier snapshot or agent memory.

## 7. Task state model

The workboard remains the authoritative task tracker. Its existing status names are retained.

| Status | Meaning | Entry condition |
|---|---|---|
| `Backlog` | Valid work intentionally not ready to start | Scope or prerequisite is not yet ready |
| `To Do` | Ready, unowned work | Dependencies and planning requirements are satisfied |
| `In Progress` | Work is actively owned | Owner claims the task before editing |
| `Review` | Implementation is submitted; independent acceptance remains | Implementation and evidence are recorded |
| `Blocked` | Work cannot proceed | Concrete blocker and unblocking condition are recorded |
| `Done` | Acceptance is complete | Criteria pass, review is independent, evidence is durable, and commit reference is recorded where required |

### 7.1 Allowed transitions

- `Backlog` → `To Do`: prerequisites and planning are complete.
- `To Do` → `In Progress`: dependencies are `Done` and an owner claims the task.
- `In Progress` → `Review`: implementation is submitted with evidence.
- `In Progress` → `Blocked`: a concrete blocker is found.
- `Review` → `Done`: independent acceptance and required evidence pass.
- `Review` → `In Progress`: remediation is required and the task returns to its owner.
- `Review` → `Blocked`: required review evidence or environment is unavailable.
- `Blocked` → prior active state: the blocker is removed and the task is reassessed.
- `Done` → `In Progress`: only when new evidence, regression, or changed requirements justify reopening; record why.

Do not change status by moving a card between headings alone. The card's explicit status field and its section placement must agree.

## 8. Parallel execution and conflict control

Parallel work is allowed only when task boundaries and integration points are sufficiently independent.

### 8.1 Ownership

- Each active task has one accountable owner.
- Shared files and interfaces must have an identified owner or an explicit coordination agreement.
- Agents must not edit another agent's active task scope without approval.
- The coordinator maintains a current view of active ownership.

### 8.2 Parallelization criteria

Tasks may run in parallel when:
- Dependencies are complete.
- They do not modify the same files or tightly coupled interfaces, or a coordination plan exists.
- Their outputs can be integrated independently.
- Shared contracts are stable.
- Test and integration responsibilities are clear.

Do not parallelize work on the same lifecycle, locking, migration, or concurrency story when changes can invalidate each other.

### 8.3 Integration conflicts

When a conflict occurs:
1. Stop competing edits to the affected scope.
2. Identify the owners and affected task IDs.
3. Determine the governing contract.
4. Agree on one integration plan.
5. Update task scope or dependencies if needed.
6. Integrate and rerun affected tests.
7. Record the resolution.

Do not resolve a conflict by silently discarding another agent's changes.

## 9. Evidence and audit records

Evidence must be sufficient for another agent to reproduce or independently assess the claim.

### 9.1 Evidence requirements

Evidence should identify:
- Task ID and requirement reference.
- Source revision or commit.
- Environment and platform.
- Exact command or test procedure.
- Result and counts.
- Relevant output, report, or artifact location.
- Date and responsible agent.
- Limitations, skips, and unverified conditions.

### 9.2 Evidence quality rules

- Preserve raw output for important release gates where practical.
- Distinguish a test collection count from a passed-test count.
- Distinguish coverage runs from no-coverage runs.
- Distinguish local, hosted CI, live deployment, and external-host results.
- Do not claim a platform check passed when it was run only on another platform.
- Do not use stale audit snapshots as current evidence without revalidation.
- Do not overwrite an older result with a newer partial result.
- Record failed and skipped checks; do not report only successful checks.

### 9.3 Storage

- `docs/WORKBOARD.md` stores current task status and concise evidence references.
- `Audits/` stores audit reports, verification logs, and supporting evidence.
- `Audits/README.md` identifies the current audit evidence layout.
- Historical audit records remain historical and must be labeled as such.
- Avoid creating a second task-status tracker.

## 10. Quality gates

Quality gates are defined by the governing product and quality documents and their approved tooling configuration.

This workflow does not establish new numeric thresholds. In particular, agents must not infer a threshold from the current tool configuration when a governing document specifies a different value.

When a documented requirement and a tool configuration disagree:
1. Record the discrepancy.
2. Block any claim that the requirement is enforced.
3. Create or update a bounded reconciliation task.
4. Obtain approval for the governing requirement or configuration change.
5. Verify the corrected enforcement with a reproducible run.

A quality gate is satisfied only when:
- Its governing requirement is known.
- Its required method is executed.
- The result meets the approved threshold.
- Evidence is retained.
- The result applies to the candidate being accepted.

## 11. Architecture changes and implementation divergence

An agent must not silently reshape architecture to make an implementation task easier or to match a stale sketch.

When implementation must diverge from the approved architecture:
- Stop the affected implementation if the divergence changes a contract or boundary.
- Describe the original requirement and proposed implementation.
- Explain the reason and consequences.
- Identify affected documents, interfaces, tests, migrations, and dependent tasks.
- Obtain the required architecture/product approval.
- Record the decision in the repository's approved decision record location.
- Update governing documentation before dependent implementation proceeds.

A difference between an old plan and current approved architecture is not, by itself, authorization to refactor.

## 12. Blockers, exceptions, and escalation

A blocker record must include:
- Task ID.
- Concrete blocker.
- Affected work and dependencies.
- Evidence that establishes the blocker.
- What is needed to unblock it.
- Responsible party, if known.
- Date identified.

Examples include:
- Missing external host or supported platform.
- Missing credentials or approved test fixture.
- Unresolved product or architecture decision.
- Conflicting governing documents.
- Unavailable hardware or third-party service.
- Required dependency not accepted.

An exception to a mandatory requirement requires explicit approval from the authority responsible for that requirement. The exception must identify:
- Requirement being excepted.
- Reason.
- Risk and impact.
- Scope and duration.
- Compensating controls, if any.
- Approver.
- Revalidation or expiry condition.

Agents must not approve their own exceptions.

## 13. Security and operational safety

All agents must follow `AGENTS.md` and the product's security and data-safety contracts.

In addition:
- Do not expose secrets in logs, reports, commits, or generated artifacts.
- Do not weaken authentication, authorization, CSRF, step-up, encryption, or audit behavior to make tests pass.
- Do not use production data for tests unless explicitly authorized and protected by the applicable policy.
- Use disposable fixtures and environments for destructive integration tests.
- Do not run destructive cleanup, restore, migration, or process-control tests against valuable user data.
- Stop when a task requires an unsafe or unauthorized action.
- Record security-sensitive findings through the approved audit process.

## 14. Documentation and workboard maintenance

The workboard is a live operational record, not a historical narrative.

Agents updating it must:
- Re-read the latest file before editing.
- Modify only the relevant card or clearly scoped section.
- Preserve stable task IDs.
- Keep section placement and explicit card status consistent.
- Update `Owner`, `Updated`, dependencies, evidence, and status when applicable.
- Avoid replacing detailed evidence with a newer partial result.
- Transfer actionable audit findings into existing or new bounded cards.
- Verify that audit-to-workboard transfers are complete.
- Keep gate summaries and current verification counts aligned with the latest retained evidence.

When a product contract changes, update the governing numbered document first, then dependent architecture references, WBS, workboard cards, implementation, tests, and audit records.

## 15. Completion definitions

### 15.1 Implementation complete

Implementation is complete when the assigned code or documentation changes exist and the implementer has recorded the required evidence.

This permits submission to `Review`. It does not mean the task is accepted.

### 15.2 Task accepted

A task is accepted when:
- All task acceptance criteria pass.
- Required tests and quality checks pass.
- An independent reviewer records acceptance.
- Blocking and major findings are resolved.
- Evidence is durable and tied to the reviewed candidate.
- Any approved exception is recorded.

### 15.3 Task done

A task is `Done` when it is accepted and its required commit/reference and workboard records are complete.

### 15.4 Release ready

A task being `Done` does not establish that the whole product is release-ready.

Release readiness requires all release-scoped requirements, quality gates, platform checks, security checks, deployment checks, and external acceptance criteria to be satisfied or explicitly excepted by the correct authority.

## 16. Required agent response format

At the end of a task, an agent must provide a concise structured report:

```text
Task:
Owner:
Status:

Changes:
- ...

Requirements addressed:
- ...

Verification:
- Command/procedure:
  Result:
  Environment:
  Evidence:

Not run / blocked:
- ...

Audit or review:
- Pending / Pass / Findings / Blocked

Risks and limitations:
- ...

Workboard updated:
- Yes / No

Commit:
- Not committed / <commit hash>
```

Do not report a check as passed unless it was executed and its result is available.

## 17. Initial adoption in MCManager

This document is proposed as a process specification and does not automatically change existing product requirements or task status.

Adoption should proceed as a bounded documentation task:

1. Review this specification against the current numbered documents and `docs/ARCHITECTURE.md`.
2. Resolve any process conflicts without changing product behavior.
3. Add a workboard card or update the relevant documentation task.
4. Update `AGENTS.md` only with concise repository-wide rules that every agent must always follow; keep detailed workflow policy here.
5. Reconcile the workboard's status definitions and evidence rules with this specification.
6. Validate that the workflow can be followed using the existing repository layout and tools.
7. Record approval and the commit reference.

Until approved, this document is guidance for review and must not be treated as authority to override existing governing records.

---

## Appendix A — Stage gate summary

| Gate | Required decision | Minimum exit evidence |
|---|---|---|
| Design → Planning | Is the intended behavior approved and unambiguous? | Requirement and design references; decisions recorded |
| Planning → Pre-execution | Is the work bounded and testable? | Workboard card, dependencies, acceptance criteria |
| Pre-execution → Execution | Is the task ready and conflict-free? | Dependency check, owner/scope check, prerequisites |
| Execution → Integration | Is implementation submitted with evidence? | Change summary, focused test results, known limitations |
| Integration → Audit | Does the integrated candidate pass required integration checks? | Test and static-check results tied to candidate |
| Audit → Remediation or Final Verification | Does independent review pass? | Audit report and finding disposition |
| Remediation → Final Verification | Are required findings corrected? | Corrections, updated tests, finding references |
| Final Verification → Commit | Does the exact candidate pass mandatory gates? | Final verification record, clean scoped change set |
| Commit → Repeat | Is the accepted work traceable? | Commit hash, updated workboard |

## Appendix B — Non-negotiable rules

1. Read `AGENTS.md` before repository work.
2. Read the current workboard before claiming a task.
3. Do not start until dependencies are `Done`.
4. Claim the task before editing.
5. Work only within the assigned scope and repository boundary.
6. Do not silently change governing requirements or architecture.
7. Submit implementation to `Review`; do not self-approve.
8. Record exact verification evidence.
9. Re-run affected checks after remediation and cleanup.
10. Commit only the accepted, finally verified candidate.
11. Keep the workboard as the sole current task-status tracker.
12. Never turn missing evidence into a pass.
