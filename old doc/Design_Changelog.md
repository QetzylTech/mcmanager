# Design Changelog (reference-only)

Purpose
- Archive of revision history, design-decision rationale, and "decided this pass" markers extracted from Documents 4–11 during the compression pass.
- **Reference-only.** Outside the numbered-document precedence chain (Document 10 §1). Historical context for why design decisions were made — not specification.
- New design decisions should continue to be recorded here; any *conflicts* they create belong in Document 10 §2 (per its Change Log Convention).

## Product decisions (recorded as the decisions were made)

- **User = individual named accounts** — username + password per person, not shared per-role credentials. Supersedes the legacy shared admin/superadmin password model.
- **Device attribution retained alongside named accounts** — every login attempt and audit record snapshots both `user_id` and `device_id`/IP at write time. Named accounts add "who" without dropping the legacy "from what device."
- **Baseline roles: Client / Admin / Superadmin** — supersedes Doc 2 §8.1's tentative "viewer/operator, admin, superadmin" naming. Admin = full world authority, no control-panel authority; Superadmin = both plus exclusive permission-delegation right.
- **Permission delegation restricted to Superadmin** — a Client or Admin can be granted individual `permissions` (e.g. cleanup/maintenance) without promotion.
- **Runtime config change rule** — Java runtime / launch args / port editable only while the world is `off`; write immediate, effect deferred to next boot (the running process only ever reads config at launch via its `launch_args_snapshot`).
- **Template independence** — `template_id` is provenance only; a world's config is copied at `CreateWorld` and never mutated by later template edits.
- **Notification severity expanded to four levels** (`critical`/`high`/`normal`/`informational`) and the notification dropdown made permanent — no UI path ever deletes a Notification; only ack/read/dismiss (per-user), with full history always in Audit/History.
- **Global Deletion & Retention Model** — three tiers; Tier 1 never deleted by anything; Tier 2 soft-deleted with the single shared `deleted_at` column and physically removed only by the Cleanup subsystem; no tier 3.
- **MissedRunRecord reclassified as a permanent record** — never deleted, soft or hard, by anything, including Cleanup; resolves as `resolved` or `ignored`.
- **Schedule / CleanupPolicy / Role / Permission / RoleAssignment no longer directly hard-deletable** — soft-delete + logged `ConfigEdit` Operation + AuditRecord; physical delete only via Cleanup. Corrects an earlier draft where these were hard-cascade-deletable.
- **Single shared `deleted_at` column** — no `revoked_at` split; same marker for "deleted" and "revoked" entities.
- **SyncAttempt split out from SyncRecord** — preserve full per-attempt retry history as immutable rows, not a single incrementing counter.

## Document 4 (Style Guide) — Revision 2
- Status Indicator component (§17) added only this revision. Full-project consistency recheck found: Doc 1 §8 (stat boxes) and Doc 5 (sync status badges) assume a non-interactive status-display component exists, and Document 10 §2.1 states status colors "are used freely elsewhere — stat boxes, status fields, notification entries" — but no such component was formally defined. The revision defines one: four closed meanings (positive/negative/neutral/transitional), reusing action-button color tokens, never interactive, never animated.

## Document 5 (Navigation & Workflow) — Revisions 2–3
- **Revision 2** closed a sync-visibility gap: Doc 2 §4.4 requires sync logs/failures to be surfaced in the UI, and Docs 6/7/8 define a real `sync_records`/`sync_attempts` retry-history model, but the original site map only had a settings page for *configuring* targets. Added: "Recent sync activity" section on the Offsite sync settings page (manager-wide sync health at a glance), and a per-backup sync status indicator with expandable per-attempt retry history in the world backup list.
- **Revision 3** (product-behavior review): proper notification dropdown in the shell (was a bare bullet) — severity-sorted, unread badge, mark-all-read, link to Audit/History, per-user dismiss; search/filter/grouping for the world list (flat lists stop scaling around dozens-to-hundreds of worlds; backed by the Doc 7 `display_name` index); ManagerBackup UI entry point on Manager Maintenance (closes the disaster-recovery gap from review); Client/Admin/Superadmin role renaming reflected in User Management.
- Sync status/retry views are read-only layers on existing pages — no new top-level nav item.

## Document 6 (Domain Model) — Revisions 2–7
- **Rev 2** onward: full definitions for `User` and `RuntimeSession` (the two entities Document 10 §4 forwarded as gaps); domain glossary; aggregate roots; entity lifecycles; state machines; domain events; invariants; ownership rules; traceability table.
- **Rev 5 correction (Rev 6/7)**: `MissedRunRecord` and Schedule/CleanupPolicy/Role/Permission deletions were modeled incorrectly (hard-cascade-deletable). Corrected per explicit instruction to the finalized Global Deletion & Retention Model: Tier 1 permanent; Tier 2 soft-delete + Cleanup-only physical delete; single shared `deleted_at`.
- **Gaps closed during revision**: `pre_backup_state` adopted (a flat state enum can't express "return to where I came from" for backups from `off` vs `running`); `CrashDetected` system-actor Operation type adopted (crash transitions otherwise lack durable, auditable treatment despite Doc 2 §9.2); `DeleteWorld`/world tombstone adopted (preserves the "world IDs immutably stable" invariant); `CreateWorld`/`DeleteWorld` promoted to first-class Operation types (previously world creation/deletion had no driving Operation at all — a real hole in an Operation-centric architecture).
- **Rev 6/7 additions**: ManagerBackup (nullable `backup_artifacts.world_id`, `category = 'manager_config'` — reuses the Backup Operation rather than a parallel concept; closes the disaster-recovery gap); backup lineage via existing FK chain (two-hop join, no graph table — revisit only if deeper-than-two-hop chaining is ever required); three-tier settings inheritance formalized (Manager default / world override / effective value — the only pattern for any world-overridable setting); `idle_countdown_override` added to complete that pattern; notification defaults deliberately Manager-default-only; future integration adapter pattern (Discord/Prometheus/Home Assistant/webhooks follow the SyncAdapter port shape); SyncTarget/SyncRecord/SyncAttempt entities (supporting the SyncService added to Doc 8).
- **Decisions during review**: per-user notification read state (`NotificationRead` join) is a direct downstream consequence of the individual-account decision; optimistic concurrency (`version`) generalized (final table in Document 11 §4).

## Document 7 (Database Schema) — Revisions 2–3
- **Rev 2**: table list expanded to 27 — adding `missed_run_records`, `notification_reads`, `role_assignments`, `schema_migrations`, `sync_targets`, `sync_records`, `sync_attempts` (`sync_attempts` split from `sync_records` per explicit instruction for full retry history).
- **Rev 3** (product-design review): `backup_artifacts.world_id` made nullable for ManagerBackup; `version` added to `global_settings`, `world_settings`, `templates`, `roles`, `sync_targets`, and `world_instances` (metadata fields only) — generalized optimistic concurrency beyond schedules/cleanup_policies; `world_settings.idle_countdown_override` (complete three-tier inheritance); `notifications.severity` to four levels; `notification_reads.dismissed_at` (per-user dropdown dismissal); `templates.category` documented as free-text/data-driven (closes the plugin-architecture question — adding a server type is a new row, not a code change, provided `config_defaults` carries a generic launch command).
- **Recheck-pass note**: `CreateWorld`/`DeleteWorld` added to `op_type`; `current_operation_id` clearing rule made explicit; circular-FK (`world_instances` ↔ `operations`, both RESTRICT) and version-as-optimistic-lock behaviors documented in §4 during a full cross-document consistency recheck.
- Outstanding: `permissions` "exactly one of role_id/user_id" must be written as real `CHECK` DDL.

## Document 8 (Application Services) — Revisions 2–3
- **Rev 2** closed the SyncService gap: offsite sync had requirements (Doc 2 §4.4) and schema entities but no owning service. Added a fully-specified SyncService — own command flow, sequence diagram, and two deliberate exceptions to the retry/cancellation rules (auto-retry transient failures with backoff; cancellable even mid-`Running`) justified by the fact that a network transfer reads an immutable local artifact and carries no irreversibility. The entities it needs (`SyncTarget`, `SyncRecord`, `SyncAttempt`) were added to Docs 6 and 7 in the same pass.
- **Rev 3**: role renaming; ManagerBackup executed by BackupService; optimistic concurrency generalized; §7's matrix marked superseded by Document 11 (retained where still correct).
- **Resolved during full-project recheck**: `CreateWorld`/`DeleteWorld` missing from the operation table (added — world creation/deletion now have idempotency guards and the standard authorize→validate→audit→notify flow); "elevated confirmation" defined precisely (step-up + scope preview; applies to Kill and DeleteWorld; Stop/Restore's existing password verification reads as the same concept); BackupService's ownership of dispatching the follow-on Sync Operation stated explicitly (matching the sequence diagram); `CleanupHardDeletePerformed` granularity settled at once-per-row in Doc 6.
- Outstanding (deferred to polishing session): exact numeric timeout/retry/scheduler-tick values; four sequence diagrams (ConfigEdit, Kill, CreateWorld, DeleteWorld) — same structural shape as those drawn.

## Document 9 (Design Completion Checklist) — Revision 2
- Replaced Revision 1 wholesale: Revision 1 predated the full expansion of Docs 6–8 and the creation of Docs 10–11, and every checklist line in it was stale. Revision 2 is reconciled with actual project state.

## Document 10 (Precedence & Conflict Resolution)
- Created to establish the numbering-based precedence rule and record all known conflicts. Introduced the **one-canonical-file-per-document rule** after the project briefly had original + `_v2` files for Documents 5–8 simultaneously with no rule for which governed. Resolutions recorded: nav-alert styling (Doc 4 wins), secrets storage (`secrets` table wins over env file), concurrency model (Doc 11 authoritative), baseline role naming (Client/Admin/Superadmin). Clarified non-conflicts: modal taxonomy and pane terminology.

## Document 11 (Concurrency, Locking & Conflict Resolution Model)
- Created to close the single largest design gap from full-project review: rich per-Operation conflict rules existed but no explicit model of what is lockable, how conflicts are detected, or what happens when they occur.
- Resolved in this document: lock taxonomy (world / global storage / cleanup scope / config version); the RenameWorld+Backup pair (allowed concurrently — metadata-only); runtime-config-edit-while-running (rejected unless `off`); Schedule edit during scheduler evaluation (re-read-before-dispatch, no lock needed); "Admin A / Admin B" optimistic concurrency generalized to every multi-admin-editable table; queue/reject/preempt consolidated from Doc 1 §14 and old Doc 8 §6/§7.
- Doc 8 §7 is superseded where it differs; its correct pairs are retained.

## Future entries
Add new design decisions here as they're made; add new document *conflicts* to Document 10 §2 first, per its Change Log Convention.
