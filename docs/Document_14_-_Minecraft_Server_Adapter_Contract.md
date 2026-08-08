# Document 14: Minecraft Server Adapter Contract

Minecraft-specific runtime contract the manager depends on: readiness, EULA, version-aware `server.properties`, Java compatibility, RCON, save coordination, server-type capability model. Generic OS process mechanics live in Doc 13; this document binds those mechanics to real Vanilla/Paper/Fabric/Forge behavior. A **capability schema + adapter contract**, implementable per server type before the corresponding lifecycle feature ships (ARCHITECTURE §15 item 1 spike).

Governing: domain state — Doc 6; schema — Doc 7; services — Doc 8; process control — Doc 13; API — Doc 10; tests — Doc 11; directory placement — Doc 12.

## 1 Scope

### 1.1 In scope
- Server-type capability model (what each type can report/do).
- Readiness hierarchy (exact signal ladder authorizing `starting -> running`).
- EULA acceptance model (detect, surface, require explicit audited acceptance).
- `server.properties` version-aware configuration schema.
- Java compatibility matrix + pre-launch validation.
- RCON session contract, player-list query, safe command allowlist.
- Shutdown ladder: RCON stop → stdin stop → graceful OS signal → forced.
- Save coordination / backup edge semantics.
- Startup failure classification.

### 1.2 Non-goals (do not build)
- No hard-coded per-server-type `java` invocation inside an adapter; launch stays data-driven (Doc 13 §1.1, Doc 8 TemplateService).
- No game-content logic (world generation, plugins, mods).
- No decoding of Minecraft packet formats beyond capability detection (protocol ping, RCON, saved-query).
- No exhaustive per-version property encyclopedia; the capability schema is additive, curated, version-scoped.

## 2 Server-type capability matrix

Each supported type declares a capability record (`infrastructure/minecraft/capabilities.py`, Doc 12). Capabilities are **declared, then implemented** — a feature requiring a capability absent from a type is either adapted (documented fallback signal) or surfaced as `NOT_IMPLEMENTED` (Doc 10), never silently assumed.

| Capability | Vanilla | Paper | Fabric | Forge |
|---|---|---|---|---|
| RCON | required/optional (`server.properties`) | yes | yes (vanilla parity) | yes |
| Safe readiness probe (level 4) | protocol ping if enabled; else downgrade | yes (extended) | protocol ping | protocol ping |
| Player-list query | RCON `list` / query protocol | RCON `list` | RCON `list` | RCON `list` |
| Save coordination (`save-off`/`save-all`/`save-on`) | RCON commands | same + Paper save API | RCON | RCON (may be slower/fragile — flagged) |
| TPS metric | none (absent) | `/tps` (or `/tick`) | none | none |
| stdin `stop` | yes | yes | yes | yes (some consoles need a console → ConPTY, Doc 13 §3.2) |
| Management protocol | query protocol (optional) | Paper API (optional) | none | none |

Cell meanings: `yes` = first-class; `optional` = present only when enabled in config; `none/absent` = intentionally not provided — management must not rely on it. Where a capability is absent and a fallback signal is used, that fallback is a **declared limitation**, surfaced in the world's resolved capability record, never a silent downgrade.

## 3 Readiness contract

**A listening Minecraft TCP port is not equivalent to "Minecraft is ready."** A server can bind its port before its world is fully usable (large worlds, Forge/Fabric/Paper startup, datapack/plugin/mod init, world generation, slow disks, Java GC/startup delays).

Strictly ordered hierarchy; `starting -> running` fires only when the highest available level for the server type is confirmed (or the locked 120s Start timeout lapses → world `error`, Doc 8 §5.0).

```
Level 1  process_alive        process exists, survived quick-crash window
Level 2  port_bound           world's assigned TCP port is listening
Level 3  rcon_ready           RCON accepting + authenticated ping (if enabled)
Level 4  probe_ok             safe readiness probe succeeds (protocol ping; Paper API if enabled)
Level 5  operationally_valid  server reports an operationally valid state
                              (RCON `list` responds / Paper `/tps` OK; Vanilla =
                              level 4 + advisory "Done (...)" log as minor evidence only)
```

- `ServerReadinessLevel` closed enum (Doc 6 §5): `process_alive | port_bound | rcon_ready | probe_ok | operationally_valid`.
- The readiness evaluator (per type) chooses the best available level: Vanilla default target = `probe_ok`; Paper with API enabled = `operationally_valid`; Forge/Fabric = `probe_ok` (RCON optional).
- Log strings ("Done (x.xxxs)!") are **advisory evidence only**, never the sole signal (ARCHITECTURE §10, Doc 13 §4.1). A slow log line must not corrupt readiness.
- The RuntimeSession opens at confirmed `running` only (Doc 6 §2.2).

## 4 Startup contract

The Minecraft adapter validates before Start dispatch and again immediately before spawn. Pre-launch validation set:

1. **Java compatibility** — resolved Java major within the server type/version's supported range (§7); mismatch → Start/CreateWorld rejected `JAVA_INCOMPATIBLE` (Doc 10), no process spawned.
2. **EULA state** — §5; unaccepted → Start rejected `EULA_NOT_ACCEPTED`, world → `eula_required` if not already there.
3. **Server JAR existence** — configured jar path exists and is non-empty; else Start → `Failed`, exit classification `spawn_failed` (Doc 13 §4.1).
4. **Working directory** — provisioned world dir exists and is writable.
5. **Launch arguments** — argv assembled from Template + JavaRuntime + `launch_args`; no shell interpolation (Doc 13 §3.1); memory args validated non-negative and within host budget (advisory).
6. **Port availability** — assigned port + RCON port (if enabled) not already bound on the host; conflict → Start rejected (Doc 9, Doc 10 `WORLD_PORT_CONFLICT`-class).
7. **Readiness expectations** — applicable readiness level registered for the server type (§3) before spawn.

Startup failure classification (feeds state resolver / `end_reason`, Doc 6 §2.3, Doc 13 §4.1):
- `config_invalid` — pre-launch validation failure (Java/EULA/ports/paths); no spawn.
- `spawn_failed` — OS failed to start the process (Doc 13 `spawn_failed`).
- `startup_timeout` — 120s readiness timeout (Doc 8 §5.0); world → `error`.
- `startup_crash` — process exited nonzero before readiness; world → `error` (or `crashed` if it reached `running`), CrashDetected flow (Doc 8 §2.x).

## 5 EULA handling model

Minecraft's official setup flow requires the operator to set `eula=false → eula=true` before the server runs normally. The manager **never silently flips `eula=true`**. Full model:

- `eula.txt` is a **protected Minecraft-required file** (FileManagerService guarded ops, Doc 8). Detected states (closed enum `EulaState`, Doc 6 §5):
  - `not_present` — file absent (server would generate it with `eula=false` and refuse to run)
  - `unaccepted` — file present with `eula=false`
  - `accepted` — file present with `eula=true`
- CreateWorld provisions the world directory **without** an accepted EULA: writes no `eula.txt` (or writes `eula=false`) — never `true`. New world rows enter `state = eula_required` (Doc 6 §2.3).
- The manager detects EULA state at CreateWorld and re-checks at every Start.
- An unaccepted-EULA world sits in `eula_required`; the UI presents the EULA acceptance requirement on the world's setup surface (Doc 5) before Start is offered.
- Acceptance is an **explicit operator action**: `POST /api/worlds/{world_id}/eula/accept` (step-up; Doc 10) records an audited ConfigEdit-type Operation (`ConfigEditEntity = eula`) and **only then** writes `eula=true`. The world returns `eula_required -> off`.
- Audit: every acceptance produces an `audit_records` row (who, when, world). The manager records operator acceptance; it never implies it grants the license itself.
- An external edit reverting `eula.txt` to `eula=false` is detected at the next Start; the world re-enters `eula_required`.

## 6 `server.properties`: version-aware configuration

Minecraft server properties are version-dependent (Mojang has moved properties into game rules and added/removed properties across versions; e.g. Java 1.21.9 removed several old properties in favor of gamerules and added management-server properties). A single universal approved-key list is **not sufficient**. Two property classes:

### 6.1 Core manager-owned properties
The manager treats these as its own configuration surface, touched only through guarded editors (Doc 8 ConfigurationService): `server-port`, `enable-rcon` + `rcon.port` + `rcon.password` (password managed via `secrets`, Doc 7 §2.24 — never in the file editor), `server-ip` (bind), `enable-query` + `query.port`, `level-name` / `level-seed`, `online-mode`, and `motd` (when surfaced).

### 6.2 Version/server-type-dependent properties
Everything else. Validity driven by a **capability schema per server type/version** (`infrastructure/minecraft/properties_schema.py`, Doc 12): a registry of `property -> {type, constraints, min_supported_version, max_supported_version?, deprecated_in?, replaced_by_gamerule?}`.

- Validator answers `is_valid_key(key, server_type, mc_version)` and `is_valid_value(key, value, server_type, mc_version)` against the schema. Unknown-for-this-version → `CONFIG_INVALID_KEY`; bad format → `CONFIG_INVALID_VALUE` (Doc 10).
- A property `deprecated_in` a loaded version is preserved on disk (never silently deleted) but flagged obsolete in the editor; `replaced_by_gamerule` surfaces the migration hint.
- Version upgrades never cause the manager to reject legitimate settings or delete preserved ones: schema refresh is additive, version-scoped, covered by Doc 11 capability tests.

## 7 Java compatibility matrix

- Compatibility record per `(server_type, mc_version)`: `supported_major: list[int]`, `minimum_major: int`, `recommended_major: int` (`infrastructure/minecraft/java_compatibility.py`, Doc 12).
- Seeded curated reference data (extendable): modern Vanilla/Paper require Java 21 for 1.20.x–1.21.x; requirements vary by version and future versions may require Java 25+. The registry is **curated reference data, not a locked constant** — updating it is a data change validated by tests (Doc 11), never a code change requirement.
- Pre-launch validation: the Java major version resolved at JavaRuntimeService verify (Doc 8) must be within `supported_major`; `recommended_major` surfaced in the UI; mismatch → `JAVA_INCOMPATIBLE` reject before spawn (never discover-after-launch).
- RuntimeSession retains `java_runtime_id` in its launch snapshot (Doc 6 §1.2) so audit history preserves what actually ran.

## 8 Runtime contract

- **RCON:** per-session credential rotation (Doc 6 §1.2) — the adapter opens a session-scoped RCON connection with the session secret; connection state adapter-local, never the raw credential in memory beyond the connection.
- **Player-list query:** RCON `list` where available; parsing tolerant — format drift returns *unavailable* rather than corrupt data.
- **Safe command allowlist:** RuntimeService only issues commands from a closed allowlist: `save-all`, `save-off`, `save-on`, `stop`, `list`, Paper `tps`/`tick` where the capability exists; anything else refused before reaching RCON (Doc 10 `FORBIDDEN`-class).
- **Performance query:** Paper `/tps` (or `/tick`) where capability exists; other types return `none` — MetricsService shows what the server can report, never fabricates.
- **Capability surfacing:** `GET /api/worlds/{world_id}` includes the resolved capability record so the UI renders only actions the server type supports (Doc 5, Doc 10).

## 9 Shutdown contract

Escalation ladder, in order (timeouts from Doc 8 §5.0):
1. **RCON `stop`** — preferred. Wait up to the Stop graceful deadline (60s) for clean exit.
2. **stdin `stop`** — fallback when RCON unavailable (disabled, or connection failed). Same deadline.
3. **Graceful OS signal** — POSIX `SIGTERM` to the process group; Windows `CTRL_BREAK_EVENT` (Doc 13 §3.2) where a console exists.
4. **Forced** — after 60s, Kill path: POSIX `SIGKILL` to the group; Windows `TerminateProcess` + `TerminateJobObject` (Doc 13 §3.2). Process-level deadline 10s, then `forced` exit classification.

Abnormal shutdown classification (feeds `end_reason`, Doc 6 §2.2): `graceful` — exited after `stop` with expected exit code (vanilla 0); `forced` — killed via ladder step 4 or emergency stop; `crashed` — unexpected exit with no Stop in flight (CrashDetected Operation + notification, Doc 8 §2.x); `reconciled_missing` — boot probing found no live process (Doc 7 §6 step 4).

## 10 Save coordination & backup semantics

Sequence: `save-off` → `save-all` → wait-flush → capture → `save-on` (RCON; Doc 8 §2.x). Explicit edge semantics (each is an integration test in Doc 11):

- **Flush command:** `save-all` (vanilla) or Paper save API where declared. `save-all` synchronous by contract on vanilla; Paper flush may be async → verify via save status where available, else a settle interval (configurable, default 5s) before capture.
- **Completion detection:** after `save-all`, lightweight verification (RCON round-trip; `level.dat` mtime inside the capture window) before capture.
- **RCON unavailable mid-backup:** backup aborts (no artifact row, Doc 6 §2.5) with a `backup_error` notification; autosave restore attempted immediately.
- **Server crashes while saving:** CrashDetected flow; no artifact row; the outstanding `save-off` is re-asserted to `save-on` at the next confirmed Start (safety net).
- **`save-off` ok but `save-all` fails:** abort, attempt `save-on` immediately; failure to restore autosave is a critical notification (Doc 6 §2.8 severity), recovery at next Start as above.
- **Manager crashes after `save-off`, before `save-on`:** reconciled at boot — open session found → re-issue `save-on`; no session → next Start re-issues it. `save-on` restoration is part of the startup readiness sequence (§3) whenever autosave was suspended.
- **Offline worlds (`state = off`):** safe to copy without coordination (no live writes); backup from `off` has no RCON dependency.
- **Inclusion/exclusion:** capture = world-directory contents per per-world include/exclude policy; always exclude manager-owned files (lock/pid/tmp), log-tail buffers, and `.part` staging artifacts.
- **Symlinks/reparse points** (POSIX symlinks, Windows junctions): followed only when the target is inside the world root; escaping targets are skipped and counted in the backup summary — never dereferenced outside the boundary (FileManagerService path policy, Doc 8).
- **Out-of-tree writes** (mod/plugin writing outside the world dir): outside the capture set by definition; surfaced via the per-world external-write guard (advisory, never silently included).

## 11 Backup artifact format & integrity protocol

Decision (locked; ARCHITECTURE §16 ruling 15): first-class format is **ZIP** (deflate; compression level configurable) — maximum portability, no external tar dependency on Windows, streaming-capable for large worlds.

- Checksum: **SHA-256** over the full artifact, stored in `backup_artifacts.checksum` (Doc 7 §2.10); computed during creation, verified before any restore staging.
- Atomicity: write to `<artifact>.part` in the target directory; `fsync`; rename to the final name only after full successful write + checksum. An interrupted backup leaves only a `.part` file (swept by CleanupService) and no `backup_artifacts` row (Doc 6 §2.5).
- Verification after creation: post-write checksum verification before the artifact row is registered; mismatch = failed Backup Operation, no row.
- Restore validation: checksum + archive structural integrity before staging; corrupt → `RESTORE_ARTIFACT_INVALID` (Doc 10).
- Corruption detection: any restore failing structural validation is logged with the artifact id and the artifact flagged `suspect` (surfaced, never auto-deleted).
- ManagerBackup (`world_id = NULL`): the SQLite database is backed up via **SQLite's backup API** (online, consistent snapshot) — never a plain file copy of a live `.db` (Doc 7 §10). Same ZIP + SHA-256 envelope applies.

## 12 Restore: failed post-restore startup decision tree

Base flow (Doc 8 §2.x): validate → stop → pre-backup → stage → archive → switch → restart-if-previously-running. Explicit decision tree for the final-restart failure case:

```
restart attempted (world was running before restore)
  ├─ readiness confirmed            -> running; restore_history.outcome = success
  └─ readiness failed / crash
       ├─ automatic rollback (compensating Restore operation referencing
       │    pre_restore_artifact_id) -> rollback succeeds
       │      -> world off, restore_history.outcome = reverted
       │         (rollback_of_restore_id set); notification
       └─ rollback fails or no pre-restore artifact
             -> world error (never auto-clears, Doc 6 §2.3); operator decides
                retry / manual recovery; restore_history.outcome = failed
```

- Rollback is **automatic**, not manual, so "restore is safe to attempt" holds (Doc 6 §2.3 compensating actions).
- The rollback is a **new** Operation referencing the failed Restore's `id` — never a mutation of the original outcome (Doc 6 §2.4); it reuses the same stage/archive/switch path.
- If the world was `off` before the restore, no restart is attempted; success returns the world to `off` (`restore_history.outcome = success`).
- `restore_history.outcome` is exactly `success | failed | reverted` (Doc 7 §2.11).

## 13 Conformance & test expectations

Doc 11 gains: capability-schema tests (every declared capability cell has an implementation or an explicit `none`); EULA state-machine tests; Java-compat matrix validation tests; `server.properties` schema tests per curated version; save-coordination edge tests (each §10 bullet); backup integrity tests (interrupt/checksum/structure); restore rollback decision-tree tests.

The Doc 13 fake-server binary gains EULA-file behavior and `--save-slow` / `--ignore-save-on` modes so save-coordination edge cases are integration-testable cross-platform (Doc 11).

Shortcuts: readiness levels → §3; EULA states → Doc 6 §5; capability registry + package layout → Doc 12; locked timeouts → Doc 8 §5.0; error codes → Doc 10; conformance → Doc 11.
