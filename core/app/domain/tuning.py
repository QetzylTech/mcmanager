"""Locked tuning constants from Document 8 section 5.0.

Defaults ship in ``global_settings``; a code change to these values requires
an ARCHITECTURE conflict-log entry. Supervisor poll cadence and
MetricsCadence are not user-configurable.
"""

from __future__ import annotations

# Scheduler
SCHEDULER_TICK_INTERVAL_S = 30  # fixed tick; missed-run detection at granularity

# Start / Stop / Kill ladders (Doc 8 section 5.0, Doc 13 C9/C10, Doc 14 section 9)
START_READINESS_TIMEOUT_S = 120  # configurable
STOP_GRACEFUL_DEADLINE_S = 60  # then escalate to Kill
KILL_PROCESS_DEADLINE_S = 10  # after forced signal, before re-assert + forced class
START_COOLDOWN_S = 10  # duplicate-start guard

# Sync
SYNC_TRANSIENT_RETRIES = 3  # exp backoff 30s/60s/120s
SYNC_BACKOFF_BASE_S = 30
SYNC_PER_ATTEMPT_TIMEOUT_S = 120  # configurable
SYNC_OUTER_BOUND_S = 30 * 60  # total wall-clock for all attempts; configurable
SYNC_GLOBAL_CONCURRENCY_CAP = 2  # simultaneous transfers; configurable

# Storage / metrics
STORAGE_GUARD_RESERVE_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB absolute reserve
STORAGE_GUARD_OVERFLOW_PCT = 10.0  # free-space overflow safety net
METRICS_CADENCE_NULL = 0  # clients=0 and all worlds off -> no emission
METRICS_CADENCE_CACHE_S = 15  # cached snapshot refresh
METRICS_CADENCE_STREAM_HZ = 1.0  # >=1 connected client

# Security / UX
STEP_UP_WINDOW_S = 10 * 60  # default 10 min
PASSWORD_RETRY_THROTTLE = 5  # failures -> lockout
PASSWORD_LOCKOUT_S = 15 * 60
SESSION_IDLE_EXPIRY_S = 7 * 24 * 60 * 60  # 7 days inactivity
SESSION_ABSOLUTE_EXPIRY_S = 30 * 24 * 60 * 60  # max 30 days

# Logs / streams
LOG_LINE_BUFFER_LINES = 5000  # ring buffer per world; configurable
LOG_LINE_MAX_BYTES = 64 * 1024  # per-line cap; remainder dropped w/ sentinel
SSE_REPLAY_BUFFER_EVENTS = 200  # per stream; configurable
SSE_HEARTBEAT_S = 15

# Poll cadences (locked, not user-configurable)
SUPERVISOR_POLL_RUNNING_S = 1.0
SUPERVISOR_POLL_IDLE_S = 15.0
RENDER_INTERVAL_LIVE_METRICS_S = 1.0  # 1Hz, bounded by MetricsCadence

# Cleanup
CLEANUP_BLAST_RADIUS_CAP = 500  # beyond: elevated confirmation required
CLEANUP_AGE_FLOOR_DAYS = 3  # cannot save lower
CLEANUP_COUNT_FLOOR = 3  # per backup category + stale-world scope

# Operation timeouts (Doc 8 section 5.1)
OP_CREATEWORLD_TIMEOUT_S = 120
OP_BACKUP_TIMEOUT_S = 30 * 60  # configurable per world size (default)
OP_RESTORE_TIMEOUT_S = 30 * 60
OP_DELETEWORLD_TIMEOUT_S = 30 * 60
OP_CONFIGEDIT_TIMEOUT_S = 30
OP_EXIT_POLL_GRACE_S = 2.0  # process-exit settle grace before classification
