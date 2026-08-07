# Architecture Instructions

Standing instruction to AI coding assistants working on this project.
Reference-only material: it never supersedes a numbered document. First-read entry point
that points at the normative contracts. Normative corpus: Documents 4–8 and 11–15.
(Documents 1–3, 9, 10 are retired and removed; their residual content is consolidated
here and in the numbered documents — see §14.)

------------------------------------------------------------------------

## 0. Hard Constraints

Binding product constraints, not preferences. A change that violates one is rejected.
Verification for each lives in Document 13.

- **Modular monolith.** No microservices. One authoritative control plane.
- **Multi-world, multi-version.** Many independent world instances run concurrently on
  one host; each carries its own version/type/Java/ports/files/logs/backups/retention/crash
  handling. One world's crash/restore/backup never blocks unrelated worlds except where a
  shared global safety rule (storage guard) requires it.
- **No `systemd` / `journalctl` dependency.** The control plane must run anywhere Java and
  Python run. Structural test C14 (Document 15) + import-linter enforce this.
- **Portable process control.** Worlds launch via data-driven argv (no shell, no
  double-fork), supervised through the `ProcessControlPort` (Document 15) on every
  supported OS.
- **Idle CPU below the documented reference-host threshold** (5-minute average window with
  no state changes/backups/restores/active streams). Threshold + measurement method:
  Document 13 and `benchmarks/thresholds.json`.
- **Baseline memory within a documented range** for the manager alone (excluding managed MC
  processes). Method: Document 13.
- **Zero-trust security.** Trusted-network placement reduces exposure only; every request
  is authenticated with a server-issued session and authorized server-side, regardless of
  origin.
- **Realtime without client polling.** Shared server-side streams, compute-once fan-out
  (Document 12).
- **Auditability + defensive guardrails preserved.** Immutable audit/event history, durable
  Operations, storage safety, scope previews, elevated confirmation (Doc 6).
- **Low resource use.** Event-driven, throttled, or paused background work; no heavy
  per-client tasks; offline-capable without CDN.
- **Failure criteria are testable.** The negation of the above (Linux-only control,
  cross-world interference, lost auditability, excessive weight) must fail its matching
  test (Document 13).

------------------------------------------------------------------------

## 1. Top-Level Architecture

Five planes, one process (or two cooperating processes sharing one SQLite store, topology B):

- **Presentation plane** — persistent web shell; routed page modules; realtime client
  hydration. Each tab holds its own independent connection to shared server-side streams;
  no tab election, heartbeats, or client-side forwarding.
- **Control plane** — API/session gateway; authorization/policy; world orchestration;
  operation coordination; scheduler + background jobs.
- **Runtime plane** — world process supervision; RCON session handling; health probes;
  startup/shutdown detection (Document 15).
- **Data plane** — relational state; append-only audit/events; logs; world files; backups;
  secrets (Doc 7).
- **Integration plane** — OS process adapter; filesystem adapter; routing adapter; offsite
  sync adapter; future cluster adapters (all behind ports).

------------------------------------------------------------------------

## 2. Subsystem Map

Detail lives in Documents 8 / 6 / 11 / 12.

| § | Subsystem | Ownership / notes |
|---|---|---|
| 5.1 | Presentation & shell | Shell owns shared client state; per-tab independent streams; navigation + page-state persistence (Doc 4/5). |
| 5.2 | HTTP/API & session gateway | Thin routes; authn/authz/CSRF/step-up; maps requests to commands/queries (Document 12). |
| 5.3 | Realtime streams | SSE default; rehydration snapshot never blank; compute once, fan out (Document 12). |
| 5.4 | World registry | Canonical world list; immutable IDs; editable display name + policies (Doc 7). |
| 5.5 | World lifecycle orchestration | Runtime state machine; idempotency/cooldowns/conflicts; durable Operations; reconciliation (Doc 6, Document 11). |
| 5.6 | World runtime session | One contiguous run; per-session RCON rotation; durable metadata survives restart (Doc 6). |
| 5.7 | Background jobs & scheduler | Async ops off request path; missed-run detection (never auto-replayed); conflict rules (Doc 8, Document 11). |
| 5.8 | Backup/restore/sync/retention | Native portable engine is the **only** supported production path; script adapters transitional-only, retired before first stable release. Restore checkpointed with immutable history (Doc 8, Document 15). |
| 5.9 | File & config management | Guarded file ops; protected config editors; per-world path policy (Doc 8). |
| 5.10 | Security & secrets | Sessions, authz, device trust, step-up, secret rotation; secrets server-side only (Doc 8, Doc 7). |
| 5.11 | Audit, history & events | Append-only; immutable; feeds notifications + history views (Doc 6, Doc 8). |
| 5.12 | Observability & diagnostics | Status aggregation; health/consistency reports; failure context for "explain error" (Doc 8, Document 12). |
| 5.13 | Setup & settings | First-run setup + persistent settings share one model (Manager singleton, Doc 6). |
| 5.14 | Platform adapters | Spawning/termination, filesystem, disk checks, network/routing, sync, future cluster. Main portability boundary; Linux helpers exist only as adapter implementations. |

------------------------------------------------------------------------

## 3. General Rules

- **Normative corpus**: Documents 4–8 and 11–15 + this file. Documents 1–3, 9, and 10 are
  retired and removed — no archived copies exist. Their residual content was consolidated
  (see §14); never treat a retired document as a source of requirements.
- Read the numbered documents before making architectural decisions. Use CONTEXT_MAP.md to
  locate a contract instead of re-reading the corpus.
- Treat the design documents as the source of truth. If implementation conflicts with the
  documents, follow the documents.
- **Precedence.** Numbered documents are ordered by number; a higher-numbered document
  supersedes a lower-numbered one wherever they conflict.
  - **Document 11 is the final word on all operational locking, mutual exclusion,
    queue/reject/preempt semantics, and optimistic concurrency.**
  - **Documents 12–15 extend the specification** (API, testing, layout/tooling, process
    control). They introduce no competing business rules; they bind existing rules to wire
    formats, tests, physical layout, and platform behavior.
  - This file is reference-only and never supersedes a numbered document.
- **One canonical file per document number.** If two files claim the same number, stop and
  flag it — do not guess that a revision suffix wins. Stale copies are deleted, never
  allowed to coexist. Numbers 9 and 10 are retired and are never reused.
- **New conflicts** are appended to §14 (Conflict Log) before writing the code that
  resolves them. Check §14 and Document 11 before assuming a lower-numbered document is
  still accurate.

------------------------------------------------------------------------

## 4. Architecture

- Preserve the modular monolith; no microservices. Modules loosely coupled, highly
  cohesive.
- Dependency injection in a single composition root (`app/bootstrap.py`, Document 14).
- Ports-and-adapters for OS-specific, Minecraft-server-specific, and storage-specific
  behavior.
- **Adapter boundaries are enforced, not stylistic** (import-linter contracts, Document 14):
  - `platform/` is leaf-only. No `services/`, `commands/`, or `web/` module ever imports
    `platform/` or any script-based adapter directly.
  - `services/` depend on `ports/` interfaces only; concrete adapters are injected at the
    composition root.
  - No `shell=True` anywhere in `app/platform/process/` (Document 15).
- **Script-based adapters are retired** (§14 ruling 6). Scripts such as `backup.sh` exist
  only as transitional migration tools and must be removed before the first stable release.
  No new platform-specific script logic may be added. The native portable backup engine
  (`ports/backup_engine.py` + `infrastructure/backup_engine.py`) is the sole supported
  production path.

------------------------------------------------------------------------

## 5. Optimistic Concurrency

Applies to every multi-admin-editable configuration table.

- Every row in a multi-admin-editable configuration table carries a `version` column —
  `schedules`, `cleanup_policies`, `global_settings`, `world_settings`, `templates`,
  `roles`, `sync_targets`, and `world_instances` metadata fields.
- Every `ConfigEdit` submits the `version` the editor last read. `ConfigurationService`
  compares at write time; a mismatch is rejected with `409 CONFIG_VERSION_CONFLICT` and no
  write occurs. **Never last-save-wins.**
- `permissions` and `role_assignments` are deliberately excluded (atomic single-field
  grant/revoke rows).
- The version is compare-then-write logic in the service layer, not a DB constraint.

------------------------------------------------------------------------

## 6. Domain Model

- Do not rename domain entities; do not invent new domain concepts unless explicitly
  required.
- Preserve aggregate boundaries, ownership rules, and the documented business invariants
  (Doc 6).
- Every state-changing action executes as a durable Operation (Doc 6) — including
  `CreateWorld`/`DeleteWorld`, not just start/stop/backup/restore.
- Follow the Global Deletion & Retention Model (Doc 6): Tier 1 entities are never deleted
  by anything; Tier 2 entities are soft-deleted (`deleted_at`) by normal actions and
  physically removed only by `CleanupService`, never by any other route, command, or
  service.

------------------------------------------------------------------------

## 7. Persistence

- SQLite is the primary persistent store; runtime state stays in memory; only durable
  state is persisted. Follow the documented migration strategy (Doc 7).
- **Global Persistence Invariant** (defined once here; referenced by name — do not
  restate): every connection runs `PRAGMA foreign_keys = ON` before any other statement,
  and every boot runs a `PRAGMA foreign_key_check` sweep after migrations apply and before
  serving requests. Any violation is a startup-blocking critical error, never silently
  repaired.
- Clients connecting during boot reconciliation are rehydrated immediately from the
  durable snapshot plus the last cached live snapshot — never shown a blank or unknown
  state during the warm-up window.

------------------------------------------------------------------------

## 8. Operations

- All state-changing actions execute as durable Operations; maintain auditability; emit
  domain events; be restart-safe whenever practical (Doc 6/8).
- Runtime status is **never** derived from a single log line. The state resolver combines
  process state, health probes, startup signals, operation checkpoints, and crash markers.
  Log strings such as "Dedicated server took x seconds to load" are advisory only
  (Document 15).
- Follow queue/reject/preempt semantics (Document 11): Backup/Restore/Cleanup duplicates
  are queued single-flight (auto-dispatch, queue position surfaced via live stream — never
  rejected outright, never polled); Start duplicates ignored; DeleteWorld/ConfigEdit
  conflicts rejected. Priority between waiting operations is contextual (manual/
  safety-critical first).
- Storage guards are contextual (job size + configurable absolute reserve, default 10 GB,
  with a 10% free-space bound only as an overflow safety net), never a flat 10% rule.
- Runtime config (java runtime, launch args, port) is editable only while `state = off`;
  the write is immediate, the effect deferred to next boot by construction.

------------------------------------------------------------------------

## 9. Web Application

- Python + Flask. API endpoints stay thin; business logic lives in services/domain layers
  (layer chain: routes → commands → services → ports → infrastructure → platform,
  Document 14).
- No business logic in routes or templates.

------------------------------------------------------------------------

## 10. User Interface

- Follow the CSS Style Guide (Doc 4) and Navigation & Workflow Blueprint (Doc 5).
- One shared visual system. Page-scoped CSS only under Doc 4's Functional Appropriateness
  Exception (layout-only; shared tokens only; promoted when a second page needs it).
- Reuse shared components — including the Status Indicator (Doc 4) for any state display.
  No invented one-off badges.
- Multi-tab: each tab opens its own independent connection to the shared server-side
  streams. No primary/secondary election, TTL heartbeats, or BroadcastChannel forwarding.
  A failing/closed tab never disrupts others.
- Step-up verification is session-scoped and time-bounded (default 10 min); one successful
  verification authorizes subsequent sensitive actions in that window.

------------------------------------------------------------------------

## 11. Coding Standards

- Prefer readability over cleverness; keep functions focused and small; clear docstrings.
- Add tests for new functionality (Document 13).
- **Tooling is locked in Document 14 and enforced in CI (merge-blocking):** `black`
  (line length 100, single quotes), `isort` (profile=black), `ruff`, `mypy` (strict for
  `domain/`, `services/`, `ports/`, `commands/` — no `Any`), and `import-linter`
  (layering + leaf-platform contracts). Follow Document 14's directory layout — the
  physical folder structure is normative.
- Closed enums come from `domain/value_objects.py`. Never invent stringly-typed states
  inline; a value outside a documented closed set is a contract violation.
- Do not hand-roll HTML escaping or security utilities — use framework/Jinja mechanisms.

------------------------------------------------------------------------

## 12. Before Completing Any Task

- [ ] Aligns with Documents 4–8 and 11–15 (Document 11 for locking; §14 Conflict Log for
      all other conflicts; Docs 12–15 are API, testing, directory/standards, and
      process-control-adapter contracts).
- [ ] No architectural rule violated (monolith, ports-and-adapters, Operation-based
      control, deletion tiers, adapter leaf-only boundary).
- [ ] Optimistic concurrency respected: every ConfigEdit on a versioned table submits and
      validates `version`; no last-save-wins path (Document 11, §5 of this file).
- [ ] No script-based adapter introduced; `platform/` imports stay inside the platform
      layer; import-linter contracts hold.
- [ ] Naming consistent with the docs (no renamed/duplicated domain concepts).
- [ ] API routes/shapes/error codes follow Document 12 (route catalog, envelope, error
      catalog); SSE topics from Document 12.
- [ ] Code layout follows Document 14 (layering, module-per-service, composition-root DI).
- [ ] Tests added per Document 13 (pyramid, ISO/IEC 25010 mapping, coverage floors);
      Document 14 tooling gate green.
- [ ] Process control respects Document 15 (port interface used by services; platform
      implementations leaf-only; no systemd/journalctl; conformance suite expectations).
- [ ] Existing ports/adapters and shared components reused, not duplicated.

------------------------------------------------------------------------

## 13. Build Order & Gates

From retired Document 9 — the only content it carried. Implement in this order; nothing
downstream starts until its gate is green.

| # | Work item | Ready-to-code contract | Gate before next item |
|---|---|---|---|
| 1 | Platform process-control adapter prototype | Document 15 (port, POSIX/Windows, tailing, reconciliation, conformance) | Conformance C1–C14 green on the target OS **and** the fake adapter; C11 re-attach verified end-to-end with a real manager boot (Document 15) |
| 2 | Foundational layers: world registry + schema, settings/setup model, operation + audit model, adapter interfaces, session/auth core | Doc 7 (all tables; constraints), Doc 6, Document 14 layout, §7 of this file | `PRAGMA foreign_key_check` sweep clean on a fresh migration run; migrations runner test green (Document 13) |
| 3 | Control plane: world lifecycle orchestration, runtime state reconciliation, scheduler, metrics + log streams | Doc 6 (states), Doc 8 (30s tick), Document 12 (SSE topics), Document 15 (supervision) | Scheduler tick-to-Operation + missed-run integration tests green (Document 13); reconciler restart scenarios green |
| 4 | Operational subsystems: backup/restore, cleanup/retention, file/config management, offsite sync | Doc 8, Doc 6, Document 11 | Restore checkpoint-interrupt tests + optimistic-lock matrix green (Document 13) |
| 5 | Experience + hardening: shell polish/offline, multi-tab, diagnostics, ISO-aligned verification + thresholds | Doc 4/5 (UI), Document 12 (streams/rehydrate), Document 13 | E2E UI/SSE suites + performance benchmarks within thresholds (Document 13) |

Standing gates (enforced regardless of stage): script-based adapters retired (§14 ruling 6);
optimistic `version` on every ConfigEdit (Document 11, §5 of this file); `platform/`
leaf-only with import-linter CI contracts (Document 14); C14 no-systemd structural test
(Document 15); only `CleanupService` issues physical `DELETE FROM` (Doc 6);
black/isort/ruff/mypy/import-linter tooling gate (Document 14).

Reference shortcuts: locked tuning constants → Doc 8; error codes → Document 12; SSE topics
→ Document 12; closed enums → Doc 6.

------------------------------------------------------------------------

## 14. Conflict Log (resolved rulings)

Standing table of every resolved disagreement, from former Document 10 (retired). This is
the **only** place a new conflict gets recorded before it is resolved in code.

**Append convention.** New conflict discovered: append an entry `Conflict / Resolution /
Amends (where the rule now lives)` here before writing the resolving code. Document 11
governs locking/concurrency disagreements; Documents 12–15 govern their contracts; all
other disagreements are decided by the entry appended here.

| # | Standing rule | Normative home |
|---|---|---|
| 1 | Nav carries no status/notification indication — no flashing, pulsing, or state coloring. Ban is on *where* state appears (nav), not on the colors; state surfaces via the notification dropdown and per-page status displays. | Doc 4 (already specified the desired state) |
| 2 | Secrets live in the SQLite `secrets` table; the env file holds no secrets (only non-secret runtime config). Server-side-only access, per-session RCON isolation, and rotation rules are unchanged. | Doc 7/8 |
| 3 | Document 11 is authoritative for all concurrency/locking: lock taxonomy, generalized optimistic concurrency, mutual-exclusion matrix, queue/reject/preempt. | Document 11 |
| 4 | Baseline roles: **Client / Admin / Superadmin**. Admin has full world authority but not control-panel/user-management authority; Superadmin has both plus exclusive ability to delegate individual `permissions`. | Doc 6 |
| 5 | Doc 1 residuals consolidated: live-metrics broadcast set + MetricsCadence → Document 12; log channel taxonomy → Document 12; Instructions rendering contract → Doc 5; startup/shutdown chimes → Doc 8; restore-wins-over-delete → Document 11; epoch-second timestamps → Doc 7. | Document 12 / 5 / 8 / 11 / 7 |
| 6 | Script-based adapters are retired before first stable release; no new platform-specific script logic; the native portable backup engine is the only production path. Enforcement: import-linter leaf rule, no `shell=True` in `platform/process/`, no `scripts/` layer. | §4 of this file; Document 15 |
| 7 | Docs 1–3 retired and removed; this file is the single general-rules entry point; numbered documents remain the normative contracts. | This file |
| 8 | Traceability tables removed from every document; relationship provenance is inline. | All numbered documents |
| 9 | Doc 7 ER diagram removed; the FK graph in Doc 7 (compact table definitions + constraint summary) is the sole normative relationship contract. | Doc 7 |
