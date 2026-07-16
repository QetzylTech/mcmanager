window.MCWEBPrototypeData = {
  runtime: {
    serverStatus: "Off",
    playersOnline: 0,
    tickRate: "--",
    backupStatus: "Idle",
    serviceRunning: false,
    sessionStartedAt: null,
    idleCountdownSeconds: 180,
    lastBackupTime: "2026-05-09 21:14",
    nextBackupTime: "2026-05-09 22:00",
    cpuPerCore: [4, 8, 5, 11],
    ramUsage: "1.9 GB / 16 GB",
    cpuFrequency: "4.2 GHz",
    storageUsage: "61% used, 732 GB free"
  },
  logs: {
    minecraft: [
      "[21:13:14] [Server thread/INFO]: Preparing spawn area: 0%",
      "[21:13:15] [Server thread/INFO]: Time elapsed: 3372 ms",
      "[21:14:02] [Server thread/INFO]: <marites> checking storage before event",
      "[21:14:17] [Server thread/WARN]: Can't keep up! Is the server overloaded?",
      "[21:15:02] [Server thread/INFO]: <builder-lan> anyone online?"
    ],
    backup: [
      "[21:00:00] backup.sh started manual archive world_2026-05-09_21-00_manual.zip",
      "[21:00:03] save-off issued through RCON",
      "[21:00:12] archive finalized, 2.31 GB written",
      "[21:00:13] save-on restored",
      "[21:00:14] backup completed successfully"
    ],
    mcweb: [
      "[21:10:11] panel action accepted start requested by living-room-pc",
      "[21:10:12] operation op_start_8d2a queued",
      "[21:14:00] maintenance dry run opened by marites-phone",
      "[21:14:22] restore viewer opened for world_2026-05-08_23-20_manual.zip"
    ],
    mcweb_log: [
      "[21:08:31] warning metrics stream idle, serving cached payload",
      "[21:09:55] error transient RCON timeout recovered in 412 ms",
      "[21:12:18] warning cleanup missed run requires acknowledgement"
    ],
    restore: [
      "[20:42:00] restore requested for world_2026-05-08_23-20_manual.zip",
      "[20:42:05] pre-restore snapshot completed",
      "[20:42:11] extracted archive to world_restore_2026-05-08_23-20",
      "[20:42:17] server.properties updated",
      "[20:42:19] restore completed"
    ]
  },
  backups: [
    {
      id: "b1",
      type: "manual",
      name: "world_2026-05-09_21-00_manual.zip",
      modifiedText: "2026-05-09 21:00",
      sizeText: "2.31 GB",
      mtime: 1715269200,
      preview: "Archive: world_2026-05-09_21-00_manual.zip\nContains:\n- world/\n- server.properties\n- ops.json\n- whitelist.json\n\nNotes:\nManual backup completed successfully."
    },
    {
      id: "b2",
      type: "session",
      name: "world_2026-05-09_18-12_session_end.zip",
      modifiedText: "2026-05-09 18:12",
      sizeText: "2.24 GB",
      mtime: 1715259120,
      preview: "Session-end backup created after normal shutdown."
    },
    {
      id: "b3",
      type: "auto",
      name: "world_2026-05-09_17-00_auto_snapshot",
      modifiedText: "2026-05-09 17:00",
      sizeText: "418 MB delta",
      mtime: 1715254800,
      preview: "Incremental snapshot metadata:\nbase=world_2026-05-09_16-00_auto_snapshot\nlinked files=92%"
    },
    {
      id: "b4",
      type: "prerestore",
      name: "world_2026-05-08_20-40_prerestore.zip",
      modifiedText: "2026-05-08 20:40",
      sizeText: "2.18 GB",
      mtime: 1715172000,
      preview: "Pre-restore snapshot kept for rollback-by-restore workflow."
    },
    {
      id: "b5",
      type: "others",
      name: "world_2026-05-06_03-17_emergency.zip",
      modifiedText: "2026-05-06 03:17",
      sizeText: "2.09 GB",
      mtime: 1714965420,
      preview: "Emergency backup created during low-storage shutdown."
    }
  ],
  logFiles: {
    minecraft: [
      { id: "lm1", name: "latest.log", modifiedText: "2026-05-09 21:17", sizeText: "824 KB", mtime: 1715269620, preview: "[21:17:01] [Server thread/INFO]: chunk save complete\n[21:17:04] [Server thread/INFO]: <marites> prototype pass is live" },
      { id: "lm2", name: "2026-05-08-1.log.gz", modifiedText: "2026-05-08 23:59", sizeText: "2.3 MB", mtime: 1715183940, preview: "Compressed log preview unavailable in prototype.\nRepresentative metadata only." }
    ],
    crash: [
      { id: "lc1", name: "crash-2026-05-06_03.16.24-server.txt", modifiedText: "2026-05-06 03:16", sizeText: "82 KB", mtime: 1714965384, preview: "---- Minecraft Crash Report ----\nDescription: Unexpected exception\njava.lang.NullPointerException..." }
    ],
    backup: [
      { id: "lb1", name: "backup-2026-05-09.log", modifiedText: "2026-05-09 21:01", sizeText: "18 KB", mtime: 1715269260, preview: "[21:00:00] creating zip\n[21:00:14] backup completed successfully" }
    ],
    restore: [
      { id: "lr1", name: "restore-2026-05-08.log", modifiedText: "2026-05-08 20:42", sizeText: "9 KB", mtime: 1715172120, preview: "[20:42:00] restore requested\n[20:42:19] restore completed" }
    ],
    mcweb: [
      { id: "la1", name: "mcweb_actions.log", modifiedText: "2026-05-09 21:14", sizeText: "132 KB", mtime: 1715269440, preview: "[21:10:11] start requested by living-room-pc\n[21:14:22] restore viewer opened" }
    ],
    mcweb_log: [
      { id: "le1", name: "mcweb.log", modifiedText: "2026-05-09 21:12", sizeText: "91 KB", mtime: 1715269320, preview: "[21:08:31] metrics stream idle\n[21:09:55] transient RCON timeout recovered" }
    ]
  },
  maintenance: {
    backups: {
      storageRemaining: "732 GB free",
      backupSummary: "248 archives",
      staleSummary: "14 worlds",
      lastRun: "2026-05-09 06:00",
      lastChangedBy: "living-room-pc",
      scheduleCount: 2,
      nextRun: "2026-05-10 06:00",
      missedRuns: 1,
      rules: [
        "Age rule enabled: older than 7 days",
        "Count rule enabled: keep 5 newest manual backups",
        "Count rule enabled: keep 3 newest pre-restore backups",
        "Space rule enabled: begin deletion above 82% disk usage"
      ],
      candidates: [
        { id: "cb1", name: "world_2026-04-24_22-00_manual.zip", detail: "16 days old • 2.02 GB • eligible by age + count", selected: false },
        { id: "cb2", name: "world_2026-04-25_06-00_session_end.zip", detail: "15 days old • 2.11 GB • eligible by age + count", selected: false },
        { id: "cb3", name: "world_2026-04-28_03-17_emergency.zip", detail: "11 days old • 2.08 GB • eligible by age", selected: false }
      ],
      history: {
        success: [
          { id: "hs1", title: "Successful cleanup", meta: "2026-05-09 06:00 • deleted 2 files • 4.13 GB freed" },
          { id: "hs2", title: "Dry run", meta: "2026-05-08 06:00 • 3 files eligible • no deletion performed" }
        ],
        missed: [
          { id: "hm1", title: "Missed scheduled cleanup", meta: "2026-05-07 06:00 • blocked by backup job in progress" }
        ]
      }
    },
    stale_worlds: {
      storageRemaining: "732 GB free",
      backupSummary: "248 archives",
      staleSummary: "14 worlds",
      lastRun: "2026-05-05 06:00",
      lastChangedBy: "marites-phone",
      scheduleCount: 1,
      nextRun: "2026-05-12 06:00",
      missedRuns: 0,
      rules: [
        "Age rule enabled: older than 30 days",
        "Count rule enabled: keep 4 newest stale worlds",
        "Schedule enabled: weekly every Monday 06:00"
      ],
      candidates: [
        { id: "cs1", name: "world_old_survival_2026-03-02", detail: "68 days old • 6.8 GB • safe to archive/delete", selected: false },
        { id: "cs2", name: "world_old_nether_2026-03-02", detail: "68 days old • 1.9 GB • safe to archive/delete", selected: false }
      ],
      history: {
        success: [
          { id: "hss1", title: "Stale-world cleanup", meta: "2026-05-05 06:00 • deleted 1 world • 8.2 GB freed" }
        ],
        missed: []
      }
    }
  },
  settings: {
    deviceMachines: [
      { id: "d1", machine: "living-room-pc", addresses: "100.64.0.2, living-room-pc.tailnet", lastSeen: "2026-05-09 21:14", owner: "JP" },
      { id: "d2", machine: "marites-phone", addresses: "100.64.0.8, marites-phone.tailnet", lastSeen: "2026-05-09 20:59", owner: "Marites" },
      { id: "d3", machine: "storage-node", addresses: "100.64.0.12, storage-node.tailnet", lastSeen: "2026-05-09 21:00", owner: "Infra" }
    ]
  }
};
