# MC Manager — Context Map (LLM Index)

Purpose: locate any technical contract without re-reading the corpus. Reading order for a
task: **ARCHITECTURE.md** (rules + constraints + conflict log) → jump to the document/section
this map points at. Normative corpus = Documents 4–8, 11–15 + ARCHITECTURE.md.
Documents 1–3, 9, and 10 are retired and removed — no archived copies exist
(ARCHITECTURE.md §14 ruling 7).

------------------------------------------------------------------------

## Document Index

| File | Status | Contains (jump targets) |
|---|---|---|
| ARCHITECTURE.md | normative (reference-only) | Hard constraints §0; planes §1; subsystem map §2; general rules + precedence §3; adapter boundaries + script retirement §4; optimistic concurrency §5; domain §6; persistence invariant §7; operations §8; web §9; UI §10; coding standards §11; completion checklist §12; **build order & gates §13**; **conflict log §14** |
| Document 4 (style guide) | normative | Global tokens; layout system; nav bans; component property table; modal kinds; responsive; status indicators |
| Document 5 (nav/workflow) | normative | Shell responsibilities; manager-context pages; world-context pages; nav rules; Instructions rendering contract |
| Document 6 (domain model) | normative | Global audit invariant; entities; lifecycles; event catalog; invariants; closed enum value objects; aggregate roots + deletion tiers |
| Document 7 (schema) | normative | Conventions (IDs, timestamps, deleted_at, FK-restrict, persistence invariants); 27 table definitions; constraint/cascade summary; migration strategy; startup reconciliation |
| Document 8 (services) | normative | Capability matrix; operation preconditions/terminal states; scheduler; **locked tuning constants**; retry/cancel policy; failure recovery; notification pipeline; audit pipeline |
| Document 11 (concurrency) | normative | Lock taxonomy; what is not lockable; mutual-exclusion matrix; **optimistic-concurrency version table**; runtime-config-off-only; queue/reject/preempt table (incl. restore-wins-over-delete) |
| Document 12 (API contract) | normative | **Route catalog**; envelope; error-code catalog; SSE endpoints/topics; MetricsCadence + broadcast set |
| Document 13 (testing) | normative | Pyramid (70/25/5); ISO/IEC 25010 mapping; tooling/coverage; acceptance + performance + release gate |
| Document 14 (directory/standards) | normative | Top-level layout; app package layout; **dependency rule**; composition/boot; tests layout; **tooling locks** (black/isort/ruff/mypy/import-linter) |
| Document 15 (process-control adapter) | normative | Port interface; POSIX / Windows / tailing; supervision; reconciliation; **conformance suite C1–C14**; static guards; prototype plan |

------------------------------------------------------------------------

## Cross-Cutting References (single sources, do not restate elsewhere)

- Locked numeric constants → Doc 8 (scheduler 30s, Start 120s, Stop 60s, Kill 10s, cooldown
  10s, sync backoff, MetricsCadence, storage reserve 10 GB, step-up 10min, log buffer 5000,
  blast radius 500, throttle, session expiry, SSE replay 200).
- Versioned optimistic-lock tables → Document 11 (schedules, cleanup_policies,
  global_settings, world_settings, templates, roles, sync_targets, world_instances metadata;
  permissions/role_assignments excluded).
- Queue/reject/preempt semantics → Document 11 (Backup/Restore/Cleanup queued single-flight;
  Start ignored; ConfigEdit/DeleteWorld rejected; Kill supersedes Stop; restore wins over
  delete).
- Error codes → Document 12 (additive-only). SSE topics → Document 12. Closed enums → Doc 6.
- Deletion tiers → Doc 6 (Tier 1 permanent; Tier 2 soft + Cleanup-only physical delete).
- Adapter/import boundaries → Document 14 + ARCHITECTURE.md §4 (platform leaf-only; no
  shell=True in `app/platform/process/`; no systemd/journalctl — C14).
- Test/quality gates → Document 13; tooling gate → Document 14.
- Precedence + how to log a new conflict → ARCHITECTURE.md §3/§14 (append to §14 before
  writing code).
- Process-control prototype gate → Document 15 (C1–C14 on target OS + fake adapter + C11 E2E).

## Fallback Rules

- If two documents disagree: Document 11 governs locking/concurrency; ARCHITECTURE.md §14
  (Conflict Log) governs all other resolved disagreements; a higher document number wins
  otherwise (ARCHITECTURE.md §3).
- One canonical file per document number (ARCHITECTURE.md §3): if two files claim the same
  number, stop and flag rather than guessing. Numbers 9 and 10 are retired and never reused.
