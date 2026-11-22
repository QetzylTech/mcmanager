# AGENTS.md

This repository is the only authorized edit boundary for all project work.

Rules for every agent:
- Work only inside the repository root. Do not edit, move, or create files outside it, except that scratch artifacts must remain in an approved repository working directory such as `app/data/`, `dev_artifacts/`, or a task-local folder.
- Stop and report a blocker if required repository context is outside the authorized boundary.
- Before development work, read `docs/AGENT_DEVELOPMENT_WORKFLOW_SPEC.md`. It governs the development lifecycle and is subordinate to numbered product documents and approved architecture contracts.
- Read the relevant numbered product documents and `docs/ARCHITECTURE.md` before changing behavior or architecture.
- Read `docs/WORKBOARD.md` before claiming a task. Dependencies must be `Done`, ownership must be conflict-free, and an active task must have one accountable owner.
- Claim work by setting the card to `In Progress`, recording the owner and update date, and keeping the card's status aligned with its board section.
- Keep implementation bounded to the card; record unresolved decisions and blockers, and raise unrelated work as a separate task.
- Record reproducible evidence for implementation and verification. A passing nearby test or implementation claim is not task acceptance.
- Submit completed implementation to `Review`; do not self-approve or move your own task to `Done`. Independent audit and final verification must precede acceptance and commit authorization.
- Preserve historical audits and evidence. Reconcile findings against current source and tests before changing workboard status.
- Do not weaken product requirements, architecture, security, or quality gates without the authority that owns the requirement.
- Do not commit unreviewed or unverified work. The release controller or an explicitly authorized integrator authorizes commits.
