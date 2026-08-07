# Document 5: MC Manager Proposed Site Map

Site structure and navigation model. Manager-level pages are separate from world-level
pages so multi-world support stays explicit.

Terms
- Server — host hardware running the manager and managed Minecraft instances.
- Manager — the application being built; runs on the server and manages Minecraft instances.
- World — a Minecraft server instance run and managed by the manager.

Navigation model
- The shell stays persistent.
- Shared shell responsibilities:
  - current page
  - selected world
  - alerts
  - notifications — a persistent bell/dropdown element in the shell. Shows recent
    notifications sorted with `critical`/`high` severity surfaced above `normal`/
    `informational` (Doc 6), an unread-count badge (Status Indicator component, Doc 4),
    "mark all read," and a link to the full permanent history on the Audit/History page.
    Items can be marked read or dismissed from the dropdown (per-user, per
    `notification_reads.dismissed_at`) but this never deletes the underlying notification —
    the Audit/History page always shows the complete permanent record regardless of any
    user's dropdown-dismiss state.
  - theme
  - client/session state
  - reconnect/offline status
- World-scoped pages reflect the current selected world.
- Manager-scoped pages should not depend on one world being selected, though they may show
  a current selection summary.

Navigation and structure
Manager Context
  - Homepage
  -- Server Stats (CPU per-core activity, RAM use, storage use, number of worlds)
  -- List of currently running worlds has manage button (opens world context)
  -- List of recently run worlds (recent 5, each with manage button)
  --- Each world on the list has quick actions: Start, Stop, Manage button
  - World management page
  -- List of worlds (With info: Minecraft version, mod launcher version, world name, current
     port used if running)
  -- Search/filter/grouping: search-by-name, filter by state/server-type/version (the
     `display_name` index backs this)
  --- Create new worlds based on curated list of worlds (vanilla, forge, paper, fabric, etc
     — plus any custom `Template` an admin has added; server type is data-driven, not a
     fixed code list)
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
  -- User account privileges (**Client / Admin / Superadmin**). Superadmin-only: grant
     individual `permissions` to a specific Client or Admin account (e.g. a Client granted
     cleanup/maintenance access without a full Admin promotion) — Doc 6 delegation invariant.
  - Maintenance and Retention page - global settings, treated as default settings unless
    local settings exist per world.
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
  -- Rendering contract: content = markdown from the docs folder, rendered to CSS+HTML via
     the shared style system (Doc 4); an auto-generated clickable side ToC is produced for
     every page; the in-file ToC is suppressed in desktop mode to avoid duplication. No
     interactive rendering logic lives in this document's scope — it is a page contract only.
  - System logs page
  -- Manager activity logs
  -- Manager errors and system notifications
  - Audit/ History page
  -- All immutable actions, denials, restores, cleanup, crashes, notifications, manager
     restarts, sync operations, etc.
  - Offsite sync settings page
  -- Sync method selection (Google Drive, built-in sync function, NAS/network storage, other)
  -- Sync method key/credential requirements depending on selected method
  -- Global sync defaults
  -- Per-world sync override and inheritance rules
  -- "Recent sync activity" section: recent sync jobs across all worlds with status and
     failure reason — the manager-wide health view. Backed by `sync_records`/`sync_attempts`
     (Doc 6).
  - Manager maintenance page
  -- Manager restart
  -- Server restart
  -- Manager version update
  -- Manager version rollback
  -- Manager backup / restore: trigger a ManagerBackup on demand (manager's own
     database/settings/templates/permissions, independent of any world's content — Doc 6,
     BackupService), view manager backup history, restore the manager's configuration from
     a prior ManagerBackup
  - World template catalog page
  -- World template list
  -- World template management (adding, editing, deleting templates) - can edit versions,
     server type, Java runtime
  -- Create world from template
World Context
  - World main page
  -- World Stats (Minecraft version, mod launcher version if modded, world name, world size
     in MB, last started, lifetime player list, last backup, current port if running)
  -- World controls (start, stop, backup)
  - World backup and restore page (List of backups, restore for each backup)
  -- Each backup list row shows a sync status indicator (synced / pending / failed / not
     configured — per Doc 4), reflecting that backup's `sync_records.status`. Clicking it
     expands a per-attempt retry history view (the `sync_attempts` timeline — attempt
     number, timestamp, outcome, error message) for that backup's sync job.
  - World logs page (minecraft logs, debug logs, crash logs, backup logs, restore logs)
  -- log file list pane, live log pane, log file viewer pane
  - File manager for the world (guarded folder access for the current world - upload 1 or
    multiple files, delete files, rename files, move files, copy files, create new folder)
  - World maintenance and retention settings - can use global settings or override with
    local settings.
  - World setup page
  -- World properties edit page (editor for server.properties with validation)

Navigation rules
- Do not hide world selection inside the console page.
- Do not make world creation depend on visiting Settings first.
- Do not mix manager-wide history with one-world logs in the same page.
- Do not put destructive admin flows ahead of core daily actions in the nav.
- Keep legacy operational pages easy to reach in one click after world selection.

Future expandable pages
- Files — if file management becomes a separate first-class page from backups/logs
- Clients / Devices — if device monitoring grows larger than the Settings section
- Cluster / Hosts — if multi-machine control becomes a major feature
- Non-Minecraft server — if need for non-Minecraft server management arises

Summary
- The site is organized around two levels: manager-level control plane and selected-world
  operations.
- The nav makes world selection explicit.
- Legacy console-style operational pages remain prominent.
- Settings, audit, and docs remain manager-wide support pages.
