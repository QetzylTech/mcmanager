**AI instruction** — reference-only; never supersedes a numbered document. Corpus: this file + Documents 4–14 (contiguous). Documents 1–3 retired; residuals consolidated here (§15/§16). Precedence: higher doc number wins; Doc 9 final on locking/concurrency; Doc 14 final on Minecraft adaptation.

## 1 Document Index

| Doc | File | Jump targets |
|---|---|---|
| 4 | style guide | Tokens; layout system; nav bans; component property table; modal kinds; responsive; status indicators |
| 5 | nav/workflow | Shell responsibilities; manager-context pages; world-context pages; nav rules; Instructions rendering contract |
| 6 | domain model | Global audit invariant; entities; lifecycles; event catalog; invariants; closed enum value objects; aggregate roots + deletion tiers |
| 7 | schema | Conventions (IDs/timestamps/deleted_at/FK-restrict/invariants); 27 table definitions; constraint/cascade summary; migration strategy; startup reconciliation |
| 8 | services | Capability matrix; operation preconditions/terminal states; scheduler; **locked tuning constants**; retry/cancel policy; failure recovery; notification/audit pipeline |
| 9 | concurrency | Lock taxonomy; what is not lockable; mutual-exclusion matrix; **optimistic-concurrency version table**; runtime-config-off-only; queue/reject/preempt (incl. restore-wins-over-delete) |
| 10 | API contract | **Route catalog**; envelope; error-code catalog; SSE endpoints/topics; MetricsCadence + broadcast set |
| 11 | testing | Pyramid (70/25/5); ISO/IEC 25010 mapping; tooling/coverage; acceptance + performance + release gate |
| 12 | directory/standards | Top-level + app package layout; **dependency rule**; composition/boot; tests layout; **tooling locks** (black/isort/ruff/mypy/import-linter) |
| 13 | process-control adapter | Port interface; POSIX/Windows/tailing; supervision; reconciliation; **conformance suite C1–C14**; static guards; prototype plan |
| 14 | minecraft adapter | **Capability matrix** (Vanilla/Paper/Fabric/Forge); **readiness hierarchy**; EULA model; version-aware `server.properties`; Java compatibility; shutdown ladder; save coordination; backup format + integrity; restore rollback tree |

Fallback rules: disagreement → Doc 9 governs locking/concurrency; §16 Conflict Log governs all other resolved disagreements; otherwise higher number wins. One canonical file per number — if two files claim the same number, stop and flag; stale copies are deleted, never coexist.

## 2 Cross-Cutting References (single sources, do not restate elsewhere)

- Locked numeric constants → Doc 8 (scheduler 30s, Start 120s, Stop 60s, Kill 10s, cooldown 10s, sync backoff, MetricsCadence, storage reserve 10 GB, step-up 10min, log buffer 5000, blast radius 500, throttle, session expiry, SSE replay 200).
- Minecraft runtime contracts → Doc 14 (readiness §3; EULA §5; properties §6; Java §7; save §10; backup format/integrity §11; rollback §12).
- World-survival invariant → §16 ruling 10 (Windows `KILL_ON_JOB_CLOSE` not default; Doc 13 §3.2/§5.3).
- Security finishes → §16 ruling 14 (Argon2id, session rotation, HTTPS, security headers, no password-reset by design, secrets encrypted at rest).
- Optimistic-lock tables → Doc 9 §4. Queue/reject/preempt → Doc 9 §6.
- Error codes → Doc 10 (additive-only). SSE topics → Doc 10. Closed enums → Doc 6.
- Deletion tiers → Doc 6 (Tier 1 permanent; Tier 2 soft + Cleanup-only physical delete).
- Adapter/import boundaries → Doc 12 + §6 here (platform leaf-only; no shell=True in `app/platform/process/`; no systemd/journalctl — C14).
- Test gates → Doc 11; tooling gate → Doc 12.
- Process-control prototype gate → Doc 13 (C1–C14 on target OS + fake adapter + C11 E2E). Minecraft spike gate → Doc 14 (§15 item 1).

## 3 Hard Constraints

Binding; a change violating one is rejected. Verification in Doc 11.

- **Modular monolith.** No microservices. One authoritative control plane.
- **Multi-world, multi-version.** Many independent worlds per host, each with own version/type/Java/ports/files/logs/backups/retention/crash handling. One world's crash/restore/backup never blocks unrelated worlds except the shared global storage guard.
- **No `systemd`/`journalctl` dependency.** Runs anywhere Java+Python run. C14 (Doc 13) + import-linter.
- **Portable process control.** Data-driven argv launch, no shell/double-fork; supervised via `ProcessControlPort` (Doc 13) on every OS.
- **Idle CPU below documented reference-host threshold** (5-min avg, no state changes/backups/restores/streams). Threshold+method: Doc 11 + `benchmarks/thresholds.json`.
- **Baseline memory within documented range** (manager only, excluding MC processes). Method: Doc 11.
- **Zero-trust security.** Every request authenticated (server-issued session) and authorized server-side regardless of origin.
- **Realtime without client polling.** Shared server-side streams, compute-once fan-out (Doc 10).
- **Auditability + guardrails preserved.** Immutable audit/events; durable Operations; storage safety; scope previews; elevated confirmation (Doc 6).
- **Low resource use.** Event-driven/throttled/paused background work; no heavy per-client tasks; offline-capable, no CDN.
- **Failure criteria testable.** Negation (Linux-only control, cross-world interference, lost auditability, excessive weight) fails its matching test (Doc 11).

## 4 Planes & Subsystem Map

Five planes, one process (or two cooperating processes sharing one SQLite store, topology B):

- **Presentation** — persistent web shell; routed page modules; one leader-tab SSE connection per browser origin, shared with follower tabs through the `mcmanager_stream_channel` BroadcastChannel and leader election.
- **Control** — API/session gateway; authorization/policy; world orchestration; operation coordination; scheduler + background jobs.
- **Runtime** — world process supervision; RCON sessions; health probes; startup/shutdown detection (Doc 13).
- **Data** — relational state; append-only audit/events; logs; world files; backups; secrets (Doc 7).
- **Integration** — OS process adapter; filesystem; routing; offsite sync; future cluster (all behind ports).

| § | Subsystem | Ownership / notes |
|---|---|---|
| 5.1 | Presentation & shell | Shared client state; BroadcastChannel-dispatched leader-tab stream; navigation + page-state persistence (Doc 4/5). |
| 5.2 | HTTP/API & session gateway | Thin routes; authn/authz/CSRF/step-up; maps to commands/queries (Doc 10). |
| 5.3 | Realtime streams | SSE default; rehydration snapshot never blank; leader tab fans out through BroadcastChannel; `VERBOSE_LOGGING` filters nonessential channels (Doc 10). |
| 5.4 | World registry | Canonical list; immutable IDs; editable display name + policies (Doc 7). |
| 5.5 | World lifecycle | State machine; idempotency/cooldowns/conflicts; durable Operations; reconciliation; EULA + readiness gating (Doc 6, Doc 9, Doc 14). |
| 5.6 | Runtime session | One contiguous run; per-session RCON rotation; durable metadata survives restart (Doc 6). |
| 5.7 | Scheduler & background jobs | Async off request path; missed-run detection (never auto-replayed); conflicts (Doc 8, Doc 9). |
| 5.8 | Backup/restore/sync/retention | Native portable engine = **only** production path; script adapters transitional, retired before first stable. Restore checkpointed with immutable history (Doc 8, Doc 13). |
| 5.9 | File & config management | Guarded file ops; protected config editors; per-world path policy (Doc 8). |
| 5.10 | Security & secrets | Sessions, authz, device trust, step-up, rotation; secrets server-side only (Doc 8, Doc 7). |
| 5.11 | Audit/history/events | Append-only immutable; feeds notifications + history views (Doc 6, Doc 8). |
| 5.12 | Observability | Status aggregation; health/consistency reports; "explain error" context (Doc 8, Doc 10). Manager health ≠ world health: scheduler tick, SQLite writer, process adapter individually observable (ruling 12). |
| 5.13 | Setup & settings | First-run + persistent settings share one model (Manager singleton, Doc 6). |
| 5.14 | Platform adapters | Spawning/termination, filesystem, disk, network/routing, sync, cluster. Main portability boundary; Linux helpers exist only as adapter implementations. |

## 5 General Rules & Precedence

- Read numbered docs before architecture decisions; use §1 to locate a contract.
- Docs are source of truth; implementation conflict → follow docs.
- **Precedence:** higher number supersedes lower. **Doc 9 is the final word on all operational locking, mutual exclusion, queue/reject/preempt, and optimistic concurrency.** **Docs 10–14 extend the spec** (API, testing, layout/tooling, process control, Minecraft adaptation) — no competing business rules, only binding existing rules to wire formats/tests/layout/platform/Minecraft runtime. **Doc 14 is the final word on Minecraft adaptation** (readiness, EULA, `server.properties`, Java, RCON, save coordination). This file is reference-only.
- **One canonical file per number.** Duplicate number = stop and flag; never guess a revision suffix wins. Stale copies deleted.
- **New conflicts** appended to §16 before writing resolving code. Check §16 + Doc 9 before assuming a lower-numbered doc is still accurate.

## 6 Architecture

- Modular monolith; modules loosely coupled, highly cohesive.
- DI in a single composition root (`app/bootstrap.py`, Doc 12).
- Ports-and-adapters for OS/Minecraft/storage-specific behavior.
- **Adapter boundaries enforced** (import-linter, Doc 12): `platform/` leaf-only — no `services/`/`commands/`/`web/` module imports it or any script adapter; `services/` depend on `ports/` interfaces only; concrete adapters injected at composition root; no `shell=True` in `app/platform/process/` (Doc 13).
- **Script adapters retired** (ruling 6): `backup.sh`-style scripts are transitional only, removed before first stable; no new platform-specific script logic. Native portable engine (`ports/backup_engine.py` + `infrastructure/backup_engine.py`) is the sole production path.

## 7 Optimistic Concurrency

Applies to every multi-admin-editable config table.

- Every such row carries `version` — `schedules`, `cleanup_policies`, `global_settings`, `world_settings`, `templates`, `roles`, `sync_targets`, `world_instances` metadata fields.
- Every `ConfigEdit` submits the last-read `version`; `ConfigurationService` compares at write; mismatch → `409 CONFIG_VERSION_CONFLICT`, no write. **Never last-save-wins.**
- `permissions`/`role_assignments` excluded (atomic single-field grant/revoke).
- Version = service-layer compare-then-write, not a DB constraint.

## 8 Domain Model

- No renaming domain entities or inventing concepts unless explicitly required; preserve aggregate boundaries, ownership, documented invariants (Doc 6).
- Every state-changing action is a durable Operation (incl. `CreateWorld`/`DeleteWorld`) (Doc 6).
- Deletion tiers (Doc 6): Tier 1 never deleted by anything; Tier 2 soft-deleted (`deleted_at`) by normal actions, physically removed only by `CleanupService` — never any other route/command/service.

## 9 Persistence

- SQLite primary store; runtime state in memory; only durable state persisted (Doc 7).
- **Global Persistence Invariant** (defined once here; referenced by name): every connection runs `PRAGMA foreign_keys = ON` before any other statement; every boot runs `PRAGMA foreign_key_check` after migrations before serving. Any violation = startup-blocking critical error, never silently repaired.
- Clients connecting during boot reconciliation are rehydrated immediately from durable + last cached live snapshot — never blank/unknown during warm-up.

## 10 Operations

- All state changes = durable Operations; terminal transitions and security/config events append audits, while intermediate checkpoints stay in memory and broadcast over SSE; restart-safe where practical (Doc 6/8).
- Runtime status **never** from a single log line. State resolver = process state + health probes + startup signals + operation checkpoints + crash markers. Log strings advisory (Doc 13). Readiness per Doc 14 hierarchy; listening port alone ≠ `running` (ruling 13).
- Queue/reject/preempt (Doc 9): Backup/Restore/Cleanup duplicates queued single-flight (auto-dispatch, position via live stream — never rejected, never polled); Start duplicates ignored; DeleteWorld/ConfigEdit conflicts rejected. Priority between waiting ops contextual (manual/safety-critical first).
- Storage guards contextual (job size + configurable absolute reserve, default 10 GB; 10% free-space only as overflow safety net) — never a flat 10% rule.
- Runtime config (java, launch args, port) editable only while `state = off`; write immediate, effect deferred to next boot by construction.

## 11 Web Application

- Python + Flask. API endpoints thin; logic in services/domain (routes → commands → services → ports → infrastructure → platform, Doc 12).
- No business logic in routes or templates.

## 12 UI

- Doc 4 style + Doc 5 nav.
- One shared visual system; page-scoped CSS only under Doc 4 §0 (layout-only, shared tokens, promoted when a second page needs it).
- Reuse shared components — incl. Status Indicator (Doc 4) for any state display; no invented one-off badges.
- Multi-tab: a leader tab owns the primary SSE connection and forwards events through `mcmanager_stream_channel`; follower tabs elect a replacement leader when it closes.
- Step-up: session-scoped, time-bounded (default 10 min); one success authorizes subsequent sensitive actions in the window.

## 13 Coding Standards

- Readable, focused, small functions; clear docstrings; tests for new functionality (Doc 11).
- **Tooling locked in Doc 12, enforced CI-merge-blocking:** `black` (100, single quotes), `isort` (profile=black), `ruff`, `mypy` strict (`domain/`/`services/`/`ports/`/`commands/` — no `Any`), `import-linter` (layering + leaf-platform). Doc 12 directory layout is normative.
- Closed enums from `domain/value_objects.py`; never inline stringly-typed states; value outside a documented closed set = contract violation.
- No hand-rolled HTML escaping/security utilities — framework/Jinja mechanisms only.

## 14 Task Completion Checklist

- [ ] Aligns with Docs 4–14 (Doc 9 for locking; §16 for other conflicts; Docs 10–14 = API/testing/directory/process-control/Minecraft contracts).
- [ ] No architectural rule violated (monolith, ports-and-adapters, Operation-based control, deletion tiers, leaf boundary).
- [ ] Optimistic concurrency: every ConfigEdit on a versioned table submits/validates `version`; no last-save-wins path (Doc 9 §4).
- [ ] No script adapter introduced; `platform/` imports leaf-only; import-linter contracts hold.
- [ ] Naming consistent (no renamed/duplicated domain concepts).
- [ ] API routes/shapes/error codes per Doc 10 (route catalog, envelope, error catalog); SSE topics per Doc 10.
- [ ] Layout per Doc 12; module-per-service; composition-root DI.
- [ ] Tests per Doc 11 (pyramid, ISO/IEC 25010 mapping, coverage floors); Doc 12 tooling gate green.
- [ ] Process control per Doc 13 (port used by services; platform impls leaf-only; no systemd/journalctl; conformance expectations).
- [ ] Minecraft behavior per Doc 14 (readiness hierarchy, EULA gating, version-aware server.properties, Java compatibility, save coordination).
- [ ] Existing ports/adapters/shared components reused, not duplicated.

## 15 Build Order & Gates

Retired-document residual. Implement in order; nothing downstream starts until its gate is green.

| # | Work item | Ready-to-code contract | Gate before next item |
|---|---|---|---|
| 1 | Platform process-control adapter prototype **+ real Minecraft spike** | Doc 13 (port, POSIX/Windows, tailing, reconciliation, conformance); Doc 14 (readiness, EULA, Java, save) | C1–C14 green on target OS + fake adapter; C11 re-attach E2E with real manager boot (Doc 13); live Vanilla/Paper/Forge/Fabric spike validates Doc 14 readiness + Java assumptions |
| 2 | Foundational layers: registry + schema, settings/setup, operation + audit, adapter interfaces, session/auth core | Doc 7, Doc 6, Doc 12 layout; `eula_required` + EulaState (Doc 14 §5, Doc 6 §2.3) | `foreign_key_check` clean on fresh migration; migrations runner test green (Doc 11) |
| 3 | Control plane: lifecycle orchestration, reconciliation, scheduler, metrics + log streams | Doc 6 (states), Doc 8 (30s tick), Doc 10 (SSE), Doc 13 (supervision) | Tick→Operation + missed-run integration green (Doc 11); reconciler restart scenarios green |
| 4 | Operational subsystems: backup/restore, cleanup/retention, file/config, offsite sync | Doc 8, Doc 6, Doc 9 | Restore checkpoint-interrupt + optimistic-lock matrix green (Doc 11) |
| 5 | Experience + hardening: shell/offline, multi-tab, diagnostics, ISO verification + thresholds | Doc 4/5, Doc 10, Doc 11 | E2E UI/SSE + performance benchmarks within thresholds (Doc 11) |

Standing gates: script adapters retired (ruling 6); `version` on every ConfigEdit (Doc 9 §4); `platform/` leaf with import-linter (Doc 12); C14 no-systemd (Doc 13); only `CleanupService` issues physical `DELETE FROM` (Doc 6); tooling gate (Doc 12).
Shortcuts: locked constants → Doc 8; error codes/SSE topics → Doc 10; closed enums → Doc 6; Minecraft runtime contracts → Doc 14.

## 16 Conflict Log (resolved rulings)

Standing table of every resolved disagreement. The **only** place a new conflict is recorded before resolution in code.
**Append convention:** new conflict → append `Conflict / Resolution / Amends` row here before writing resolving code. Doc 9 governs locking/concurrency; Docs 10–14 govern their contracts; all else decided by the row appended here.

| # | Standing rule | Normative home |
|---|---|---|
| 1 | Nav carries no status/notification indication — no flashing, pulsing, state coloring. Ban is on *where* state appears (nav), not the colors; state surfaces via notification dropdown + per-page status displays. | Doc 4 |
| 2 | Secrets live in SQLite `secrets` table; env file holds no secrets (non-secret runtime config only). Server-side-only access, per-session RCON isolation, rotation unchanged. | Doc 7/8 |
| 3 | Doc 9 authoritative for all concurrency/locking: lock taxonomy, generalized optimistic concurrency, mutual-exclusion matrix, queue/reject/preempt. | Doc 9 |
| 4 | Baseline roles: **Client / Admin / Superadmin**. Admin has full world authority but not control-panel/user-management; Superadmin has both plus exclusive right to delegate individual `permissions`. | Doc 6 |
| 5 | Retired Doc 1 residuals: live-metrics broadcast set + MetricsCadence → Doc 10; log channel taxonomy → Doc 10; Instructions rendering contract → Doc 5; startup/shutdown chimes → Doc 8; restore-wins-over-delete → Doc 9; epoch-second timestamps → Doc 7. | Doc 10/5/8/9/7 |
| 6 | Script-based adapters retired before first stable; no new platform-specific script logic; native portable backup engine only production path. Enforcement: import-linter leaf rule, no `shell=True` in `platform/process/`, no `scripts/` layer. | §6; Doc 13 |
| 7 | Docs 1–3 retired; this file is the single general-rules entry point; numbered docs remain normative. | This file |
| 8 | Traceability tables removed from every doc; relationship provenance inline. | All numbered docs |
| 9 | Doc 7 ER diagram removed; FK graph in Doc 7 (compact table definitions + constraint summary) is the sole normative relationship contract. | Doc 7 |
| 10 | **World survival across manager restart = cross-platform invariant.** Windows Job Object must NOT default to `KILL_ON_JOB_CLOSE`; worlds survive manager death on every OS, re-attached by boot reconciliation. "Deployment option" resolved away: survival is the default, never silently divergent per-OS. | Doc 13 §3.2/§5.3; Doc 7 §6 |
| 11 | **EULA never auto-accepted.** Manager detects `eula.txt`, gates Start behind it (`eula_required`), writes `eula=true` only after explicit, audited, step-up-protected operator action. | Doc 14 §5; Doc 6 §2.3 |
| 12 | **Manager health ≠ world health.** Diagnostics separately observe scheduler tick, SQLite writer, process adapter; live HTTP server ≠ healthy manager. | Doc 10 (system routes); Doc 8 |
| 13 | **Minecraft readiness is a hierarchy, not a socket check.** `starting -> running` requires highest available level (Doc 14 §3); Doc 13 C8 socket test is the minimum floor, not the contract. | Doc 14 §3; Doc 13 C8 |
| 14 | **Security finishes: Argon2id** hashing; session-ID rotation on login/elevation/password change; HTTPS mandatory for non-loopback; security-header contract (CSP, X-Content-Type-Options, Referrer-Policy, frame-ancestors, cache control); no password-reset mechanism by design; secrets encrypted at rest in `secrets`. | Doc 7 §2.21a/§2.24; Doc 8 (Auth/Security); Doc 10 |
| 15 | **Backup artifact format locked: ZIP** (deflate, streaming) + **SHA-256** checksum; `.part` atomic write + fsync + rename; post-write verification before registration; structural verification before restore. | Doc 14 §11; Doc 7 §2.10 |
| 16 | **ManagerBackup uses SQLite backup API** (online consistent snapshot), never a plain file copy of a live `.db`. | Doc 14 §11; Doc 7 SQLite operational contract |
| 17 | **Multi-tab stream sharing uses client-side BroadcastChannel.** A leader tab holds the primary SSE connection and forwards events via `mcmanager_stream_channel`; followers elect a replacement on leader loss. | Doc 4/5/10/11/12 |
