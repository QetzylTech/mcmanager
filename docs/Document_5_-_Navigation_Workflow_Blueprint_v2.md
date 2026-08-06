Document 5: MC Manager Proposed Site Map (Revision 3 — Notification Dropdown, World Search/Filter, ManagerBackup UI)

Revision note
- This is a full, standalone replacement for the original Document 5, not a delta layered on top of it. Everything not marked "Amendment"/"added this revision" is the verified original document, unchanged.
- Revision 2 closed a sync-visibility gap: Doc 2 §4.4 requires "sync logs and sync failures must be stored and surfaced in the UI," and Documents 6/7/8 define a real `sync_records`/`sync_attempts` retry-history model to surface, but the original only had a settings page for *configuring* sync targets.
- Revision 3 (this revision) addresses the product-behavior review: a proper notification dropdown (was previously just a bare "notifications" bullet with no defined UI), search/filter for world lists at scale, a ManagerBackup UI entry point, and the Client/Admin/Superadmin role renaming.

Purpose
- Define a proposed site structure and navigation model for the next-generation manager.
- Keep the structure aligned with `Document 2 - more specific requirements.txt`, `Document 3 - initial architecture.txt`, and useful legacy behavior.
- Separate manager-level pages from world-level pages so multi-world support stays explicit.
- The navigation and workflow design of the application supporting and adhering to documents 1-4

Terms
- Server - host hardware that runs the manager and managed Minecraft instances.
- Manager - the application being built; runs on the server and manages Minecraft instances.
- World - a Minecraft server instance that is run and managed by the manager.

Navigation model
- The shell should stay persistent.
- Shared shell responsibilities:
  - current page
  - selected world
  - alerts
  - **notifications — a persistent bell/dropdown element in the shell (Facebook/YouTube-style), added this revision per your explicit product decision.** Shows recent notifications sorted with `critical`/`high` severity surfaced above `normal`/`informational` (Doc 6 §2.8, Doc 8 `NotificationService`), an unread-count badge (using the Status Indicator component, Doc 4 §17), "mark all read," and a link to the full permanent history on the Audit/History page. Items can be marked read or dismissed from the dropdown (per-user, per Doc 7 `notification_reads.dismissed_at`) but this never deletes the underlying notification — the Audit/History page always shows the complete permanent record regardless of any user's dropdown-dismiss state.
  - theme
  - client/session state
  - reconnect/offline status
- World-scoped pages should reflect the current selected world.
- Manager-scoped pages should not depend on one world being selected, though they may show a current selection summary.

Navigation and structure
Manager Context
  - Homepage
  -- Server Stats (CPU per-core activity, RAM use, storage use, number of worlds)
  -- List of currently running worlds has manage button (opens world context)
  -- List of recently run worlds (recent 5, each with manage button)
  --- Each world on the list has quick actions: Start, Stop, Manage button
  - World management page
  -- List of worlds (With info: Minecraft version, mod launcher version, world name, current port used if running)
  -- **Search/filter/grouping (added this revision)**: search-by-name, filter by state/server-type/version. Original list-only assumption was sized for dozens of worlds; once a deployment approaches hundreds, an unfiltered flat list stops being usable at a glance (Doc 7 §2.4's `display_name` index backs this).
  --- Create new worlds based on curated list of worlds (vanilla, forge, paper, fabric, etc — plus any custom `Template` an admin has added, since server type is data-driven, not a fixed code list, per Doc 7 §2.6)
  --- Manage world (go to world context)
  -- Global world backup schedules and triggers
  - Setup / Onboarding page
  -- First-run setup flow
  -- Later accessible from Manager Settings
  -- Date, time, and timezone
  -- Idle countdown settings
  -- Notification settings (custom alert sounds, custom alert messages, alert repetition)
  -- Path settings (Minecraft world directories, backup directories, log file directories)
  -- Import worlds (optional)
  -- Import template catalog
  -- Initial checks for system requirements (Java, Python, libraries, other dependencies)
  - Manager Settings page
  -- Date, time, and timezone
  -- Idle countdown settings
  -- Notification settings (custom alert sounds, custom alert messages, alert repetition)
  -- Path settings (Minecraft world directories, backup directories, log file directories)
  - User Management page
  -- Client device list (device IP and device name list)
  -- User list with info: last accessed, history of access and actions
  -- Blacklist and Whitelist
  -- Client Rulesets page
  -- User account passwords and username setup
  -- User account privileges (**Client / Admin / Superadmin** — renamed this revision per your explicit product decision, supersedes the earlier "viewer/operator, admin, superadmin" draft naming). Superadmin-only: grant individual `permissions` to a specific Client or Admin account (e.g. a Client granted cleanup/maintenance access without a full Admin promotion) — Doc 6 §2.16 delegation invariant.
  - Maintenance and Retention page - global settings, treated as default settings unless local settings exist per world.
  -- Backup retention settings
  -- Stale world cleanup settings - cleanup stale worlds created from restore operations
  -- Restore artifact cleanup settings
  -- Old log cleanup settings
  -- Manual stale file cleanup with dry run and wet run modes
  -- Scheduled cleanup settings
  -- Missed job handling
  - Instructions and documentation page
  -- Dev notes and server manual
  -- Admin manual
  - System logs page
  -- Manager activity logs
  -- Manager errors and system notifications
  - Audit/ History page
  -- All immutable actions, denials, restores, cleanup, crashes, notifications, manager restarts, sync operations, etc.
  - Offsite sync settings page
  -- Sync method selection (Google Drive, built-in sync function, NAS/network storage, other)
  -- Sync method key/credential requirements depending on selected method
  -- Global sync defaults
  -- Per-world sync override and inheritance rules
  -- **Amendment (Revision 2)**: a "Recent sync activity" section on this page, listing recent sync jobs across all worlds with status and failure reason — the manager-wide counterpart to the per-backup view added below, for operators who want to see sync health across the whole host at a glance rather than drilling into one world's backup list at a time. Backed by `sync_records`/`sync_attempts` (Doc 6 §2.17.1/§2.17.2, Doc 7 §2.26/§2.27).
  - Manager maintenance page
  -- Manager restart
  -- Server restart
  -- Manager version update
  -- Manager version rollback
  -- **Manager backup / restore (added this revision, closes the disaster-recovery gap from review)**: trigger a ManagerBackup on demand (backs up the manager's own database/settings/templates/permissions, independent of any world's content — Doc 6 §2.5, Doc 8 `BackupService`), view manager backup history, restore the manager's own configuration from a prior ManagerBackup.
  - World template catalog page
  -- World template list
  -- World template management (adding, editing, deleting templates) - can edit versions, server type, Java runtime
  -- Create world from template
World Context
  - World main page
  -- World Stats (Minecraft version, mod launcher version if modded, world name, world size in MB, last started, lifetime player list, last backup, current port if running)
  -- World controls (start, stop, backup)
  - World backup and restore page (List of backups, restore for each backup)
  -- **Amendment (Revision 2)**: each backup list row now also shows a sync status indicator (synced / pending / failed / not configured — per Doc 4 §17's Status Indicator component), reflecting that backup's `sync_records.status`. Clicking a backup's sync status indicator expands a per-attempt retry history view (the `sync_attempts` timeline — attempt number, timestamp, outcome, error message) for that backup's sync job. This is the direct UI consumer of the retry-history model added to Doc 6/7 — without this hook, that data would be persisted but never actually visible to an operator, which defeats the point of tracking it.
  - World logs page (minecraft logs, debug logs, crash logs, backup logs, restore logs)
  -- log file list pane, live log pane, log file viewer pane
  - File manager for the world (guarded folder access for the current world - upload 1 or multiple files, delete files, rename files, move files, copy files, create new folder)
  - World maintenance and retention settings - can use global settings or override with local settings.
  - World setup page
  -- World properties edit page (editor for server.properties with validation)

Navigation rules
- Do not hide world selection inside the console page.
- Do not make world creation depend on visiting Settings first.
- Do not mix manager-wide history with one-world logs in the same page.
- Do not put destructive admin flows ahead of core daily actions in the nav.
- Keep legacy operational pages easy to reach in one click after world selection.
- **Amendment (Revision 2)**: sync status/retry-history views are read-only displays layered onto existing pages (backup list, offsite sync settings) — they do not introduce a new top-level nav item, consistent with "do not put destructive admin flows ahead of core daily actions in the nav": sync status is diagnostic information, not a primary action surface.

Future expandable pages
- Files
  - if file management becomes a separate first-class page from backups/logs
- Clients / Devices
  - if device monitoring grows larger than the Settings section
- Cluster / Hosts
  - if multi-machine control becomes a major feature
- Non-Minecraft server
  - if need for non-Minecraft server management arises

Short summary
- The site should be organized around two levels:
  - manager-level control plane
  - selected-world operations
- The nav should make world selection explicit.
- Legacy console-style operational pages should remain prominent.
- Settings, audit, and docs should remain manager-wide support pages.
