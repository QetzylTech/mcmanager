# Document 5: Navigation & Workflow Blueprint

Purpose
- Site structure and navigation model for the next-generation manager, aligned with Docs 2/3 and useful legacy behavior.
- Separate manager-level pages from world-level pages so multi-world support stays explicit.

Terms
- **Server** — host hardware running the manager and managed Minecraft instances.
- **Manager** — the application being built; runs on the server and manages Minecraft instances.
- **World** — a Minecraft server instance run and managed by the manager.

Navigation model
- Persistent shell. Shared shell responsibilities: current page, selected world, alerts, theme, client/session state, reconnect/offline status.
- **Notifications** — persistent bell/dropdown in the shell (social-style): recent notifications sorted with `critical`/`high` above `normal`/`informational` (Doc 6 §2.8, Doc 8 NotificationService), unread-count badge (Status Indicator, Doc 4 §17), "mark all read," link to the full permanent history on Audit/History. Items readable/dismissible per-user (Doc 7 `notification_reads.dismissed_at`); dismissal never deletes the notification — Audit/History always shows the complete permanent record.
- World-scoped pages reflect the current selected world.
- Manager-scoped pages don't depend on a world being selected, though they may show a current-selection summary.

Navigation and structure

**Manager context**

- Homepage
  - Server Stats: CPU per-core activity, RAM use, storage use, number of worlds.
  - Currently running worlds, each with a Manage button.
  - Recently run worlds (recent 5, each with Manage). Each world on either list has quick actions: Start, Stop, Manage.
- World management page
  - World list: Minecraft version, mod launcher version, world name, current port if running.
  - Search/filter/grouping: search by name; filter by state/server-type/version. (Flat lists stop scaling around dozens-to-hundreds of worlds; backed by Doc 7 §2.4 `display_name` index.)
  - Create worlds from the curated template list (vanilla, forge, paper, fabric, etc., plus custom `Template` — server type is data-driven, not a fixed code list, Doc 7 §2.6).
  - Manage world (goes to world context).
  - Global world backup schedules and triggers.
- Setup / Onboarding page
  - First-run setup flow; later accessible from Manager Settings.
  - Date/time/timezone; idle countdown; notification settings (sounds, messages, repetition); path settings (world/backup/log directories); import worlds (optional); import template catalog; initial system-requirement checks (Java, Python, libraries, dependencies).
- Manager Settings page
  - Date/time/timezone; idle countdown; notification settings (sounds, messages, repetition); path settings (world/backup/log directories).
- User Management page
  - Client device list (device IP and name).
  - User list: last accessed, access/action history.
  - Blacklist and whitelist; Client Rulesets; account passwords and username setup.
  - Account privileges: **Client / Admin / Superadmin**. Superadmin-only: grant individual `permissions` to a specific Client or Admin (e.g. cleanup/maintenance access without full Admin promotion) — Doc 6 §2.16 delegation invariant.
- Maintenance and Retention page (global defaults; per-world overrides may exist)
  - Backup retention; stale-world cleanup (worlds created from restore operations); restore-artifact cleanup; old-log cleanup; manual stale-file cleanup with dry-run and wet-run modes; scheduled cleanup; missed-job handling.
- Instructions and documentation page
  - Dev notes and server manual; admin manual.
- System logs page
  - Manager activity logs; manager errors and system notifications.
- Audit / History page
  - All immutable actions, denials, restores, cleanup, crashes, notifications, manager restarts, sync operations, etc.
- Offsite sync settings page
  - Sync method selection (Google Drive, built-in sync, NAS/network storage, other); method key/credential requirements; global sync defaults; per-world sync override and inheritance rules.
  - Recent sync activity section: recent sync jobs across all worlds with status and failure reason (backed by `sync_records`/`sync_attempts`, Doc 6 §2.17.1/§2.17.2, Doc 7 §2.26/§2.27) — host-wide sync health at a glance.
- Manager maintenance page
  - Manager restart; server restart; manager version update; manager version rollback.
  - Manager backup / restore: trigger a ManagerBackup on demand (manager's own DB/settings/templates/permissions, independent of world content — Doc 6 §2.5, Doc 8 BackupService); view manager backup history; restore manager config from a prior ManagerBackup.
- World template catalog page
  - Template list; template management (add/edit/delete; edit versions, server type, Java runtime); create world from template.

**World context**

- World main page
  - World Stats: Minecraft version, mod launcher version, world name, world size in MB, last started, lifetime player list, last backup, current port if running.
  - World controls: start, stop, backup.
- World backup and restore page (list of backups; restore per backup)
  - Each backup row shows a sync status indicator (synced / pending / failed / not configured — Doc 4 §17). Clicking expands a per-attempt retry history view (`sync_attempts` timeline: attempt number, timestamp, outcome, error message) for that backup's sync job.
- World logs page (minecraft, debug, crash, backup, restore logs)
  - Log file list pane, live log pane, log file viewer pane.
- File manager for the world (guarded access to the current world's files: upload 1+ files, delete, rename, move, copy, create folders)
- World maintenance and retention settings (use global settings or override locally)
- World setup page
  - World properties edit page (validated `server.properties` editor).

Navigation rules
- Do not hide world selection inside the console page.
- Do not make world creation depend on visiting Settings first.
- Do not mix manager-wide history with one-world logs in the same page.
- Do not put destructive admin flows ahead of core daily actions in the nav.
- Keep legacy operational pages reachable in one click after world selection.
- Sync status/retry-history views are read-only displays layered onto existing pages (backup list, offsite sync settings) — no new top-level nav item; sync status is diagnostic information, not a primary action surface.

Future expandable pages
- Files — if file management becomes a separate first-class page from backups/logs.
- Clients / Devices — if device monitoring outgrows the Settings section.
- Cluster / Hosts — if multi-machine control becomes a major feature.
- Non-Minecraft server — if non-Minecraft server management arises.

Short summary
- Two levels: manager-level control plane and selected-world operations.
- The nav makes world selection explicit.
- Legacy console-style operational pages remain prominent.
- Settings, audit, and docs remain manager-wide support pages.
