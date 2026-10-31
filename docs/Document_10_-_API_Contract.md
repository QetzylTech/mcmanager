# Document 10: API Contract & Realtime Stream Contract

## Envelope

Success: `{"ok": true, "data": {...}, "meta": {"op_id": "op_9c1e...", "queue_position": 1, "freshness": 1753142445}}`
Error: `{"ok": false, "error": {"code": "WORLD_NOT_OFF", "message": "World must be off to restore.", "details": {"world_id": "w_7f3a...", "state": "running"}}, "meta": {"op_id": "op_..."}}`

- `error.code` — canonical machine-readable code (§Error catalog); never changes meaning; additive-only.
- `error.message` — short human summary. Full detail in `error.details.log` when available; always persisted in `operations.message`/`data_json` + `audit_records.payload`.
- `meta`: `op_id` (any Operation-creating call), `queue_position` (queued ops), `freshness` (epoch seconds, cached-live-snapshot payloads), `pagination` (lists).

## Conventions (locked)

- Routes `/api`; streams `/stream`. JSON in/out unless stated (file download/upload, SSE). JSON timestamps ISO-8601 UTC; DB stores epoch seconds — conversion only in serializers.
- **Authn:** cookie `mcmanager_session` (HttpOnly, SameSite=Lax, Path=/; Secure over TLS); opaque session id looked up in `client_sessions` (Doc 7), expiry/revocation checked every request. Server-side authz on every request regardless of origin. `POST /api/auth/login` sets cookie; `POST /api/auth/logout` revokes (`deleted_at`).
- **CSRF:** every state-changing request (POST/PATCH/DELETE) needs `X-CSRF-Token` (double-submit, session-bound, rotated on session restore); missing/mismatch → `CSRF_INVALID`. SSE GET needs none.
- **Step-up (S):** requires verified window on session (`client_sessions.step_up_confirmed_at` ≤ default 10 min) or fresh `POST /api/auth/step-up {password}`. S routes additionally require elevated confirmation / scope preview. Password never persisted/pre-filled.
- **Idempotency:** Operation-creating POSTs accept `Idempotency-Key` (stored on `operations.idempotency_key`, unique per `op_type`). Same key + op_type retry → original Operation (200). Server generates one if omitted → `meta.idempotency_key`.
- **Async (O):** state changes are durable Operations. Validate preconditions → create → **202** `{meta.op_id, data.operation.status (Created|Queued), meta.queue_position?}`. No polling — progress via SSE `operation.*`, fallback `GET /api/operations/{op_id}`; audit records append only at terminal status transitions. Rejection-path preconditions (never queued: Restore while running, DeleteWorld not off, stale-version ConfigEdit) → **409**, no Operation. Idempotent replay of completed op → **200** terminal state.
- **Paging/filter/sort:** `limit` (default 50, max 500) + `offset` (0) → `meta.pagination {limit, offset, total}`. Filters per-endpoint server-side query params. `sort` = comma list, optional `-` desc (`sort=-created_at`); unsupported field → `VALIDATION_ERROR`.

## HTTP status summary

| Status | Meaning |
|---|---|
| 200 | OK (read, idempotent replay, completed writes) |
| 201 | Resource created (login session, notification read marker) |
| 202 | Operation created/queued; async accepted |
| 400 | Validation (`VALIDATION_ERROR`, `CONFIG_*`, `FILE_*`) |
| 401 | Missing/invalid/expired/revoked session |
| 403 | Authenticated but denied, or step-up required/expired |
| 404 | Resource not found (`*_NOT_FOUND`) |
| 409 | Conflict: precondition rejection, stale version, in-flight conflict, duplicate identity |
| 422 | Structural request-body failure (malformed JSON/type) |
| 429 | Throttled |
| 500 | Internal (`INTERNAL_ERROR`; always `details.log`, `details.op_id` when known) |

## Route catalog

Legend: `S` = step-up; `O` = creates Operation (async 202); `A` = Admin+; `SA` = Superadmin only; `C` = Client with grant; `any` = any authenticated user.

### Auth & session
| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/api/auth/login` | public | `{username, password, device_id?}` → session cookie; 429 after throttle; audit on success/failure |
| POST | `/api/auth/logout` | any | revokes session |
| POST | `/api/auth/step-up` | any | `{password}` → 10-min window; S routes check it |
| GET | `/api/session` | any | user, role, permission grants, device, step-up expiry, settings visibility |

### Worlds
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/worlds` | any | filters `state`, `server_type`, `mc_version`, `search` (display_name), `include_deleted=false` |
| POST | `/api/worlds` | A | O CreateWorld; body: template_id, display_name, port, addressing_strategy/value, java_runtime_id, launch_args |
| GET | `/api/worlds/{world_id}` | any | detail incl. live state, **resolved capability record** (Doc 14 §2/§8), last backup summary; deleted → 404 |
| PATCH | `/api/worlds/{world_id}` | A | RenameWorld `{display_name, version}` (metadata ConfigEdit, version per Doc 9 §4); allowed concurrently with Backup/Restore/Cleanup |
| DELETE | `/api/worlds/{world_id}` | A S | O DeleteWorld; scope preview required first; 409 unless `off` + no in-flight ops |
| GET | `/api/worlds/{world_id}/runtime-config` | A | read view: java_runtime_id, launch_args, port, addressing |
| PATCH | `/api/worlds/{world_id}/runtime-config` | A | O ConfigEdit; **409 unless state = off**; requires `version`; immediate write, effect next boot |
| POST | `/api/worlds/{world_id}/start` | any | O Start; 10s cooldown; duplicates ignored |
| POST | `/api/worlds/{world_id}/stop` | A | O Stop; password via step-up window |
| POST | `/api/worlds/{world_id}/kill` | A S | O Kill; elevated confirmation; supersedes in-flight Stop atomically |
| POST | `/api/worlds/{world_id}/server-properties` | A | O ConfigEdit guarded editor — **validated per server-type/version capability schema** (Doc 14 §6); unknown/deprecated keys flagged, never deleted |
| GET | `/api/worlds/{world_id}/server-properties` | A | validated content + allowed-keys catalog for the world's server_type/mc_version |
| POST | `/api/worlds/{world_id}/eula/accept` | A S | O ConfigEdit `eula`; explicit audited EULA acceptance (Doc 14 §5) — the **only** route that writes `eula=true`; world `eula_required -> off` |
| GET | `/api/worlds/{world_id}/eula` | any | `EulaState` + world state; EULA-acceptance prompt when `eula_required` |

### Operations
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/operations` | any | filters `world_id`, `op_type`, `status`, `actor_user_id`; sort `-created_at` |
| GET | `/api/operations/{op_id}` | any | incl. `checkpoint`, `error_code`, `message`, `data_json` |
| POST | `/api/operations/{op_id}/cancel` | A | O only from `Queued`/`Validating`, cancellable types; else 409 `OP_NOT_CANCELLABLE` |
| GET | `/api/worlds/{world_id}/operations` | any | world-scoped shorthand |

### Backups & restores
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/worlds/{world_id}/backups` | any | filters `category`, `deleted=false`; retention-protected rows flagged |
| POST | `/api/worlds/{world_id}/backups` | A | O Backup `category=manual`; 202; queued single-flight if backup/restore/cleanup in flight |
| GET | `/api/backups/{artifact_id}` | any | artifact detail incl. sync status |
| DELETE | `/api/backups/{artifact_id}` | A S | soft-delete + remove file; 409 if retention floor violated without SA `?force=true` + elevated confirmation |
| GET | `/api/backups` | A | manager + all-worlds inventory; `world_id=null` = ManagerBackups |
| GET | `/api/worlds/{world_id}/restores` | any | restore history |
| POST | `/api/worlds/{world_id}/restores` | A S | O Restore `{artifact_id}` (or `source_path`); 409 unless `off` + no in-flight backup/cleanup; queued single-flight; mandates `pre_restore_artifact_id` |
| POST | `/api/worlds/{world_id}/restores/rollback` | A S | O corrective restore referencing pre-restore artifact (recovery path, not undo toggle) |

### Cleanup
| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/api/cleanup/dry-run` | A | O Cleanup `wet=false`; `{scope: backups\|stale_worlds\|logs, world_id?, policy_version?}` → affected-candidate summary in `data` once Validating |
| POST | `/api/cleanup/execute` | A S | O Cleanup `wet=true`; requires dry-run preview (`scope`, `dry_run_operation_id`); blast-radius cap enforced |
| GET | `/api/cleanup/runs` | A | cleanup history with summaries in `data_json` |
| GET | `/api/worlds/{world_id}/cleanup-preview` | A | scoped dry-run shorthand |

### Sync
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/sync/records` | A | manager-wide recent sync activity; filters `status`, `world_id`, `artifact_id` |
| GET | `/api/backups/{artifact_id}/sync` | any | sync job + immutable attempt timeline |
| POST | `/api/sync/retry` | A | O re-trigger sync `{artifact_id}` (only auto-retrying op; this is manual) |
| GET | `/api/sync/targets` | A | targets with effective resolution (global default vs world override) |

### Schedules & missed runs
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/schedules` | A | filters `scope`, `world_id`, `schedule_type`, `enabled` |
| POST | `/api/schedules` | A | O ConfigEdit; body per Doc 7 |
| PATCH | `/api/schedules/{schedule_id}` | A | O ConfigEdit; requires `version`; 409 stale |
| DELETE | `/api/schedules/{schedule_id}` | A | O ConfigEdit soft-delete |
| GET | `/api/missed-runs` | A | filter `pending\|resolved\|ignored` |
| PATCH | `/api/missed-runs/{missed_run_id}` | A | `{resolution: resolved\|ignored}` — terminal; 409 once set |

### Settings & manager
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/settings` | A | merged effective global settings + `version` |
| PATCH | `/api/settings` | A | O ConfigEdit global settings; requires `version`; 409 stale |
| GET | `/api/worlds/{world_id}/settings` | A | effective 3-tier settings |
| PATCH | `/api/worlds/{world_id}/settings` | A | O ConfigEdit world override; requires `version`; notification defaults not overridable |
| GET | `/api/manager` | any | singleton: deployed_version, setup_completed, state |
| POST | `/api/manager/backup` | A | O ManagerBackup (`world_id=null`) |
| POST | `/api/manager/restore` | A S | O restore from ManagerBackup artifact |
| POST | `/api/manager/restart` | A S | management action |
| POST | `/api/manager/update` | SA S | version update |
| POST | `/api/manager/rollback` | SA S | version rollback |
| GET | `/api/setup` | any | setup state |
| POST | `/api/setup` | SA | complete first-run setup |

### Templates & Java runtimes
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/templates` | any | filters `category`, `deprecated=false` |
| POST | `/api/templates` | A | O ConfigEdit template create |
| PATCH | `/api/templates/{template_id}` | A | O ConfigEdit; requires `version`; 409 stale |
| DELETE | `/api/templates/{template_id}` | A | O ConfigEdit **deprecate** flow (never hard-delete once referenced) |
| GET | `/api/java-runtimes` | A | list with `status` |
| POST | `/api/java-runtimes` | A | O ConfigEdit register (path, label) |
| POST | `/api/java-runtimes/{runtime_id}/verify` | A | O ConfigEdit health verification |
| PATCH | `/api/java-runtimes/{runtime_id}` | A | O ConfigEdit; requires `version` |
| DELETE | `/api/java-runtimes/{runtime_id}` | A | O ConfigEdit deprecate |

### Users, roles, permissions, devices
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/users` | SA | status, last activity, role assignments |
| POST | `/api/users` | SA | create user |
| PATCH | `/api/users/{user_id}` | SA (self: A) | display_name/status/password reset; username edit subject to step-up |
| DELETE | `/api/users/{user_id}` | SA | soft-delete; 409 if last active Superadmin |
| GET | `/api/roles` | SA | baseline + custom roles |
| POST | `/api/roles` | SA | custom role |
| PATCH | `/api/roles/{role_id}` | SA | O ConfigEdit; requires `version`; baseline roles immutable (409) |
| DELETE | `/api/roles/{role_id}` | SA | soft-delete; 409 if holders exist |
| GET | `/api/roles/{role_id}/permissions` | SA | permission catalog |
| POST | `/api/permissions` | SA | grant (role OR user attachment — never both) |
| DELETE | `/api/permissions/{permission_id}` | SA | revoke (soft) |
| GET | `/api/devices` | SA | device list |
| PATCH | `/api/devices/{device_id}` | SA | approve / revoke / rename |
| GET | `/api/devices/{device_id}/sessions` | SA | session history |
| GET | `/api/session/activity` | any | own session client-monitoring snapshot |

### Notifications & audit
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/notifications` | any | unread-first, severity then recency; `meta.unread_count`; filters `severity`, `read`, `world_id` |
| POST | `/api/notifications/{notification_id}/read` | any | per-user read marker |
| POST | `/api/notifications/{notification_id}/dismiss` | any | per-user dismiss (dropdown only; row permanent) |
| POST | `/api/notifications/read-all` | any | bulk per-user read |
| GET | `/api/audit` | any | immutable terminal-operation, security/auth, and ConfigEdit history; filters `actor_user_id`, `world_id`, `event_type`, `from`/`to`; sort `-created_at` |
| GET | `/api/audit/{audit_id}` | any | incl. `annotation_of`, `payload` |

### Files & logs
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/worlds/{world_id}/files` | A | browse `path` (relative), `include_hidden=false` → name, type, size, mtime |
| GET | `/api/worlds/{world_id}/files/download` | A | `path`; binary |
| POST | `/api/worlds/{world_id}/files` | A | multipart upload `path`, `file`; guarded boundary checks |
| POST | `/api/worlds/{world_id}/files/mkdir` | A | `{path, name}` |
| PATCH | `/api/worlds/{world_id}/files` | A | O FileEdit `{action: rename\|move\|copy, from, to}` |
| DELETE | `/api/worlds/{world_id}/files` | A S | `{path}`; elevated + audit |
| GET | `/api/worlds/{world_id}/logs` | any | channel list |
| GET | `/api/worlds/{world_id}/logs/{channel}` | A | file list for channel |
| GET | `/api/worlds/{world_id}/logs/{channel}/{file}` | A | download |
| GET | `/api/worlds/{world_id}/logs/{channel}/tail` | A | `?offset=` historical tail; new lines via SSE `log.line` |

**Log channels (`{channel}`)** — canonical closed set; others → `VALIDATION_ERROR`: `minecraft` (live console/stdout-stderr) · `crash_reports` · `backup_restore` (dedicated live stream `/stream/restore_logs`) · `panel_activity` · `panel_errors` · `debug` / `sync` / `manager_action`

`VERBOSE_LOGGING` is a non-secret runtime `.env` flag. At `false` (deployed default), `debug` is suppressed, raw Minecraft stdout/stderr is filtered to severe warnings, errors, crashes, and readiness markers, and step-level backup/restore or sync traces are omitted; essential channels and terminal outcomes remain available. At `true`, all eight canonical channels receive full retention and live-stream output.

### System
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/health` | public | `{status:"ok", version, db:"ok"}` — no sensitive data |
| GET | `/api/system/stats` | any | CPU/RAM/storage/worlds; cached; `meta.freshness` |
| GET | `/api/diagnostics` | A | manager diagnostics distinct from world health (ARCHITECTURE §16 ruling 12): scheduler last-tick + next-tick, SQLite writer busy/wedge status, process-adapter last-poll health, foreign_key_check status, reconciliation report, operation backlog/queue depth, last successful checkpoint |

## SSE stream contract

**Transport:** `text/event-stream`; WebSocket allowed as future alternative behind the same topic abstraction — never per-tab polling. Per browser origin, a leader tab opens the backend connection and forwards payloads over the `mcmanager_stream_channel` BroadcastChannel; followers do not connect directly and elect a replacement leader on loss. Server computes each event once and fans out. `event:`/`data:`/`id:` format; `id` = per-stream monotonic sequence; reconnect with `Last-Event-ID` replays buffered events (keep last 200/stream); `retry:` 3000ms. Payloads single-line JSON.

**Delivery semantics (locked; ARCHITECTURE §16, single source):**
- At-least-once delivery, not best-effort/exactly-once. `snapshot` first event guaranteed (never blank); each event delivered ≥1× per connected client.
- Ordering guaranteed per stream: `id` monotonic; replay via `Last-Event-ID` never reorders buffered events.
- Reconnect within replay window (200): resume from next sequence, no observable gap. Past window: events older than buffer lost → client re-syncs via **snapshot + rehydration** (`snapshot` event + `freshness`), applies idempotently — documented recovery path, not an error.
- Duplicates possible after reconnect (at-least-once). Client application must be idempotent: applying the same `world.state`/`operation.*`/`notification` payload twice is a no-op. UI rehydration model already assumes this.
- Heartbeats: empty comment line (`: ping`) every 15s keeps proxies from closing; clients treat as no-op (never drives UI state — Doc 4 nav ban).
- Stream shutdown: clean shutdown ends streams with final `event: manager.shutdown`; on crash no such event — clients detect dropped connection and reconnect with `Last-Event-ID`.
- Proxy buffering: deployment must disable intermediate buffering for `/stream`; Doc 11 E2E covers this on the supported deployment shape.
- Auth expiry mid-stream: session expiry/revocation closes stream with 401-equivalent terminal `event: stream.error`, `data: {"code": "AUTH_SESSION_EXPIRED"}`; client re-authenticates and reconnects.
- Slow clients: fan-out drops the slowest sink rather than blocking the event source (Doc 13 §3.3 backpressure); dropped-client alert surfaces at most once per minute per client.

### Endpoints

| Endpoint | Scope | First event on connect |
|---|---|---|
| `GET /stream/events` | manager-wide | `snapshot` (durable + cached live, never blank) |
| `GET /stream/worlds/{world_id}/events` | one world | `snapshot.world` |
| `GET /stream/worlds/{world_id}/logs` | one world's live console | `log.line` + buffered replay |
| `GET /stream/restore_logs?world_id={world_id}` | one world's restore stream | `restore.progress` + `log.line` (restore channel) |
| `GET /stream/metrics` | manager + all worlds | `metrics` snapshot then live deltas |

All require valid session cookie. CSRF not applicable (GET, read-only).

### Topics (event names = stable API; additions only; 1:1 with Doc 6 domain events)

| event | Payload (`data`) |
|---|---|
| `snapshot` | `{manager:{worlds, operations, backups, schedules, notifications, freshness}, cached_live:{metrics, world_states}}` — full durable snapshot + cached live with `freshness` |
| `world.state` | `{world_id, state, previous_state, at, reason, operation_id?}` |
| `world.metrics` | `{world_id, players, players_count, tick_time_ms, uptime_s, last_metrics_at}` |
| `operation.created` | `{op_id, op_type, world_id, actor_type, status, queue_position}` |
| `operation.progress` | `{op_id, op_type, status, checkpoint, error_code?, message?, pct?}` |
| `operation.terminal` | `{op_id, op_type, status:"Completed\|Failed\|Cancelled\|TimedOut", error_code?, message?}` |
| `notification` | Notification shape |
| `system.stats` | `{cpu_pct, ram_mb, storage_pct, worlds_count, at}` (cached cadence) |
| `backup.progress` | `{world_id, operation_id, stage:"pausing_autosave\|capturing\|resuming_autosave\|registered", pct?, artifact_id?}` |
| `restore.progress` | `{world_id, operation_id, stage:"validating\|pre_backup\|staging\|archiving\|switching\|recording", pct?, reverted:false}` |
| `sync.status` | `{sync_id, artifact_id, status:"pending\|succeeded\|failed", attempt_number, outcome?}` |
| `log.line` | `{world_id, session_id, channel:"stdout\|stderr\|minecraft\|backup\|restore\|manager", line, line_no, ts}` |
| `alert` | `{category:"critical_storage\|suspicious_activity\|unauthorized_attempt", severity:"critical\|high", message, details}` |
| `queue.position` | `{op_id, op_type, queue_position}` |
| `missed_run` | `{missed_run_id, schedule_id, schedule_name_snapshot, expected_run_at}` |

### MetricsCadence & broadcast set

- Clients = 0 AND all worlds off → no emission (`null` cadence). Any world on OR any client connected → 15s cached snapshot refresh. ≥1 connected client → 1Hz stream cadence (log lines as emitted).
- **Broadcast set** (canonical payload fields; SSE/JSON push-only, no polling; projected across `world.metrics`, `system.stats`, `snapshot`, `notifications`):
  - Host: RAM, CPU/core, CPU frequency, storage %.
  - World: MC status, RCON player list, tick time, auto-stop timer, backup status, last backup, next backup, backups folder, backup count, stale-worlds count.
  - Jobs/policy: cleanup last run, cleanup rule version, schedule version, rule last changed by, next run, missed-run count.
  - Logs: console, backup, panel activity, panel error (live via `log.line`; history via Files & Logs channels).

## Error-code catalog

Canonical, additive-only. `operations.error_code` values appear here so UI "explain error" resolves code → friendly text + expandable detail.

| Code | HTTP | Source | Meaning |
|---|---|---|---|
| `VALIDATION_ERROR` | 400 | any | Field/param validation failed; `details.fields` |
| `VALIDATION_STALE_VERSION` | 409 | ConfigEdit | alias of `CONFIG_VERSION_CONFLICT` (legacy clients) |
| `AUTH_INVALID_CREDENTIALS` | 401 | login | Bad username/password |
| `AUTH_ACCOUNT_LOCKED` | 403 | login | Retry-throttle lockout; `details.locked_until` |
| `AUTH_THROTTLED` | 429 | login/step-up | Retry/session/destructive throttle active |
| `AUTH_SESSION_EXPIRED` | 401 | any | `client_sessions.expires_at` passed |
| `AUTH_SESSION_REVOKED` | 401 | any | `deleted_at` set (logout/admin/password change) |
| `AUTH_CSRF_INVALID` | 403 | state-changing | Missing/mismatched `X-CSRF-Token` |
| `AUTH_STEP_UP_REQUIRED` | 403 | S routes | Step-up window absent |
| `AUTH_STEP_UP_EXPIRED` | 403 | S routes | Window elapsed mid-session |
| `FORBIDDEN` | 403 | any | Authenticated but denied (always audit-logged) |
| `FORBIDDEN_LAST_SUPERADMIN` | 409 | user mgmt | Last-active-Superadmin guard |
| `NOT_FOUND` | 404 | any | Generic (`*_NOT_FOUND` preferred) |
| `WORLD_NOT_FOUND` | 404 | worlds | Unknown/deleted world_id |
| `WORLD_DELETED` | 409 | worlds | Action on tombstoned world |
| `WORLD_NOT_OFF` | 409 | stop/kill/restore/config/delete | Precondition requires `off` |
| `WORLD_ALREADY_RUNNING` | 409 | start | Duplicate start (idempotency "ignored") |
| `WORLD_IN_COOLDOWN` | 409 | start | 10s cooldown |
| `WORLD_NAME_CONFLICT` | 409 | create/rename | display_name non-unique among live worlds |
| `WORLD_PORT_CONFLICT` | 409 | create/config | port non-unique among live worlds |
| `WORLD_RUNTIME_CONFIG_STATE` | 409 | runtime-config | config edit while not `off` |
| `EULA_NOT_ACCEPTED` | 409 | start | World EULA not accepted (`eula_required`); operator must accept via explicit audited route (Doc 14 §5) |
| `JAVA_INCOMPATIBLE` | 409 | start/create | Resolved Java major outside the server type/version's supported range (Doc 14 §4/§7); rejected before spawn, never discover-after-launch |
| `OP_NOT_FOUND` | 404 | operations | Unknown op_id |
| `OP_NOT_CANCELLABLE` | 409 | cancel | Type/status not cancellable (`Queued`/`Validating` only) |
| `OP_ALREADY_TERMINAL` | 409 | cancel/transition | Terminal ops immutable |
| `OP_CONFLICT_IN_FLIGHT` | 409 | reject-path ops | In-flight op blocks this type (Doc 9 matrix) |
| `OP_QUEUED` | 202 | queue-path ops | Not an error: queued single-flight; `meta.queue_position` |
| `OP_SUPERSEDED_BY_KILL` | n/a (transition) | kill | In-flight Stop cancelled atomically by Kill |
| `OP_MANAGER_RESTART_INCOMPLETE` | 409 | reconcile | Op failed at restart reconciliation |
| `OP_TIMEOUT` | n/a (terminal) | ops | Locked timeout reached |
| `STORAGE_GUARD_TRIPPED` | 409 | start/backup/restore/sync | Contextual storage guard active; `details.reserve_bytes` |
| `BACKUP_ARTIFACT_NOT_FOUND` | 404 | backups | Unknown artifact_id |
| `BACKUP_INVALID_CHECKSUM` | 409 | restore validate | Checksum mismatch |
| `BACKUP_RETENTION_GUARD` | 409 | delete backup | Floor/last-viable-artifact guard; `?force` SA-only |
| `RESTORE_ARTIFACT_INVALID` | 409 | restore | Artifact corrupt/unreadable |
| `RESTORE_PREBACKUP_FAILED` | 502 | restore | Mandatory pre-restore backup failed |
| `RESTORE_REVERTED` | n/a (outcome) | restore_history | Restore completed as `reverted` |
| `SYNC_TARGET_UNRESOLVED` | 409 | sync | Zero-resolvable target (not an error when none configured — no-op) |
| `SYNC_TRANSIENT` | n/a (attempt) | sync_attempts | `failed_transient` — retryable |
| `SYNC_PERMANENT` | n/a (attempt) | sync_attempts | `failed_permanent` — terminal for job |
| `SYNC_CONCURRENCY_CAP` | 429 | sync | Global transfer cap reached |
| `CONFIG_INVALID_KEY` | 400 | server.properties | Key not valid for the world's server_type/mc_version capability schema (Doc 14 §6.2) |
| `CONFIG_INVALID_VALUE` | 400 | server.properties | Value fails format validation for the world's server_type/mc_version capability schema |
| `CONFIG_VERSION_CONFLICT` | 409 | ConfigEdit all | Stale `version` optimistic-lock rejection |
| `CLEANUP_NOTHING_TO_DO` | 200 | cleanup | Empty candidate set (not an error) |
| `CLEANUP_PREVIEW_REQUIRED` | 409 | cleanup execute | Wet run without matching dry-run preview |
| `CLEANUP_BLAST_RADIUS` | 409 | cleanup execute | Candidate count over cap without elevated confirmation |
| `CLEANUP_POLICY_FLOOR` | 409 | policy save | Save strands an artifact below floor |
| `FILE_PATH_UNAUTHORIZED` | 403 | files | Path escapes world boundary |
| `FILE_NOT_FOUND` | 404 | files | Missing file/folder |
| `FILE_EXISTS` | 409 | files | Target name collision |
| `FILE_TOO_LARGE` | 400 | files | Upload over configured cap |
| `FILE_INVALID` | 400 | files | Illegal name/type for operation |
| `SCHEDULE_CONFLICT` | 409 | schedules | Optimistic lock or conflict rule |
| `MISSED_RUN_RESOLVED` | 409 | missed-runs | Already terminal |
| `DEVICE_UNREGISTERED` | 403 | devices | Unknown device privileged action |
| `DEVICE_REVOKED` | 403 | devices | Revoked device |
| `INTERNAL_ERROR` | 500 | any | Unexpected; always `details.log` + `details.op_id` when an Operation involved |
| `NOT_IMPLEMENTED` | 501 | any | Declared future capability not yet built |

**Error ↔ operations mapping:** Operation-creating failures set `operations.error_code` to the REST-relevant code; the `operations` row is the durable record, the HTTP response mirrors it. System-observed failures (`CRASH_DETECTED`, `OP_MANAGER_RESTART_INCOMPLETE`, `BACKUP_FAILED`) become `operations.error_code` and surface via SSE `operation.terminal`; they do not map to a synchronous HTTP error.
