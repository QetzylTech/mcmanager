# Document 5: Site Map & Navigation

Site structure and navigation model. Manager-level pages separate from world-level pages so multi-world support stays explicit.

Terms: **Server** = host hardware running manager + managed instances. **Manager** = the application. **World** = a Minecraft instance run/managed by the manager.

## Navigation model

Persistent shell. Shared shell responsibilities:
- current page, selected world, theme, client/session state, reconnect/offline status
- stream lifecycle: one leader tab opens the backend SSE stream and dispatches received events to all same-origin tabs through `mcmanager_stream_channel`; leader loss triggers follower election and reconnection
- **Notifications** — persistent bell/dropdown: recent notifications sorted with `critical`/`high` above `normal`/`informational` (Doc 6), unread-count badge (Status Indicator, Doc 4), "mark all read," link to full permanent history on Audit/History page. Items markable read/dismissed from dropdown (per-user, per `notification_reads.dismissed_at`) but never delete the underlying notification — Audit/History always shows the complete permanent record.

World-scoped pages reflect the selected world. Manager-scoped pages must not depend on a world being selected (may show current selection summary).

## Manager Context

**Homepage**
- Server Stats: CPU per-core, RAM, storage, world count
- Running worlds list (manage button → world context)
- Recently run worlds (recent 5, each with manage button)
- Each world row quick actions: Start, Stop, Manage

**World management**
- World list (Minecraft version, mod launcher version, name, current port if running)
- Search-by-name; filter by state/server-type/version (`display_name` index backs this)
- Create from curated templates (vanilla/forge/paper/fabric + custom admin `Template`; server type data-driven, not fixed code list)
- Manage world → world context
- Global backup schedules + triggers

**Setup / Onboarding** — first-run setup flow; later accessible from Manager Settings. Date/time/timezone; idle countdown; notification settings (custom sounds/messages/repetition); path settings (world/backup/log dirs); import worlds (optional); import template catalog; initial system requirements checks (Java, Python, libs, deps).

**Manager Settings** — date/time/timezone; idle countdown; notifications; path settings.

**User Management** — device list (IP + name); user list (last accessed, access/action history); blacklist/whitelist; Client Rulesets; user passwords/usernames; privileges (**Client/Admin/Superadmin**). Superadmin-only: grant individual `permissions` to a Client/Admin without full promotion (Doc 6 delegation invariant).

**Maintenance & Retention** (global defaults; per-world overrides unless local exists) — backup retention; stale-world cleanup (from restores); restore-artifact cleanup; old-log cleanup; manual stale-file cleanup dry/wet; scheduled cleanup; missed-job handling.

**Instructions & Documentation** — dev notes + server manual; admin manual. Rendering contract: content = markdown from docs folder rendered to CSS+HTML via shared style system (Doc 4); auto-generated clickable side ToC per page; in-file ToC suppressed in desktop mode (avoid duplication). Page contract only — no interactive rendering logic.

**System Logs** — manager activity logs; manager errors + system notifications.

**Audit/History** — all immutable actions, denials, restores, cleanup, crashes, notifications, manager restarts, sync operations, etc.

**Offsite Sync Settings** — sync method (Google Drive, built-in, NAS/network, other); method-specific key/credential requirements; global sync defaults; per-world override + inheritance; "recent sync activity" section: recent sync jobs across worlds with status + failure reason — manager-wide health view (backed by `sync_records`/`sync_attempts`, Doc 6).

**Manager Maintenance** — manager restart; server restart; version update; version rollback; ManagerBackup/restore (manager's own DB/settings/templates/permissions, independent of world content — Doc 6, BackupService); backup history; restore manager config.

**World Template Catalog** — template list; management (add/edit/delete; edit versions, server type, Java runtime); create world from template.

## World Context

**World main** — Stats (Minecraft version, mod launcher version, name, size MB, last started, lifetime player list, last backup, current port if running); controls (start, stop, backup).

**World Backup & Restore** — backup list with restore per backup. Each row shows sync status indicator (synced/pending/failed/not configured — Doc 4) reflecting `sync_records.status`; clicking expands per-attempt retry history (`sync_attempts` timeline: attempt number, timestamp, outcome, error message).

**World Logs** — minecraft/debug/crash/backup/restore logs; panes: log file list, live log, file viewer. Panes consume the shell BroadcastChannel dispatcher, never direct EventSource instances. With `VERBOSE_LOGGING=false`, debug is unavailable and Minecraft output is limited to severe warnings, errors, crashes, and readiness markers; `VERBOSE_LOGGING=true` exposes full channel output.

**File Manager** — guarded folder access for current world (upload 1+ files, delete, rename, move, copy, new folder).

**World Maintenance & Retention** — use global settings or override locally.

**World Setup** — server.properties editor with validation.

## Navigation rules

- Do not hide world selection inside the console page.
- Do not make world creation depend on visiting Settings first.
- Do not mix manager-wide history with one-world logs in the same page.
- Do not put destructive admin flows ahead of core daily actions in the nav.
- Keep legacy operational pages easy to reach in one click after world selection.

## Future expandable pages

- Files — if file management becomes a separate first-class page from backups/logs
- Clients / Devices — if device monitoring outgrows Settings
- Cluster / Hosts — if multi-machine control becomes major
- Non-Minecraft server — if non-Minecraft server management is needed

## Summary

Two levels: manager control plane + selected-world operations. Nav makes world selection explicit. Legacy console-style pages stay prominent. Settings/audit/docs remain manager-wide support pages.
