"""Closed value-object enums from Document 6 section 5.

Additions only via the ARCHITECTURE conflict log. Never free text.
"""

from __future__ import annotations

import enum


class OperationType(enum.Enum):
    """The 11 operation types. Each world-state transition is driven by one."""

    CREATE_WORLD = 'CreateWorld'
    START = 'Start'
    STOP = 'Stop'
    KILL = 'Kill'
    BACKUP = 'Backup'
    RESTORE = 'Restore'
    CLEANUP = 'Cleanup'
    SYNC = 'Sync'
    CONFIG_EDIT = 'ConfigEdit'
    CRASH_DETECTED = 'CrashDetected'
    DELETE_WORLD = 'DeleteWorld'


class WorldState(enum.Enum):
    """Closed world-state set. ``pre_backup_state`` is restricted to
    {off, running} while set; eula_required is never a pre_backup_state."""

    OFF = 'off'
    QUEUED = 'queued'
    STARTING = 'starting'
    RUNNING = 'running'
    STOPPING = 'stopping'
    RESTORING = 'restoring'
    BACKING_UP = 'backing_up'
    CRASHED = 'crashed'
    ERROR = 'error'
    EULA_REQUIRED = 'eula_required'


class OperationStatus(enum.Enum):
    CREATED = 'Created'
    QUEUED = 'Queued'
    VALIDATING = 'Validating'
    RUNNING = 'Running'
    COMPLETED = 'Completed'
    FAILED = 'Failed'
    CANCELLED = 'Cancelled'
    TIMED_OUT = 'TimedOut'


class EndReason(enum.Enum):
    """RuntimeSession end-reason (Doc 6 section 2.2)."""

    GRACEFUL_STOP = 'graceful_stop'
    FORCED_STOP = 'forced_stop'
    CRASHED = 'crashed'
    EMERGENCY_STOP = 'emergency_stop'
    RECONCILED_MISSING = 'reconciled_missing'


class TriggerType(enum.Enum):
    """Backup trigger classification. Identical to BackupArtifact.category."""

    SESSION_END = 'session_end'
    MANUAL = 'manual'
    SCHEDULED = 'scheduled'
    PRE_RESTORE = 'pre_restore'
    EMERGENCY = 'emergency'
    MANAGER_CONFIG = 'manager_config'


BackupCategory = TriggerType


class NotificationSeverity(enum.Enum):
    CRITICAL = 'critical'
    HIGH = 'high'
    NORMAL = 'normal'
    INFORMATIONAL = 'informational'


class SyncOutcome(enum.Enum):
    SUCCEEDED = 'succeeded'
    FAILED_TRANSIENT = 'failed_transient'
    FAILED_PERMANENT = 'failed_permanent'


class SyncRecordStatus(enum.Enum):
    PENDING = 'pending'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'


class MissedRunResolution(enum.Enum):
    PENDING = 'pending'
    RESOLVED = 'resolved'
    IGNORED = 'ignored'


class ScheduleType(enum.Enum):
    BACKUP = 'backup'
    CLEANUP = 'cleanup'
    MAINTENANCE = 'maintenance'


class Scope(enum.Enum):
    """Shared enum for ScheduleScope / PolicyScope / SyncTargetScope."""

    GLOBAL = 'global'
    WORLD = 'world'


class UserStatus(enum.Enum):
    ACTIVE = 'active'
    DISABLED = 'disabled'
    LOCKED = 'locked'


class JavaRuntimeStatus(enum.Enum):
    REGISTERED = 'registered'
    VERIFIED = 'verified'
    MISSING = 'missing'
    DEPRECATED = 'deprecated'


class DeviceStatus(enum.Enum):
    UNRECOGNIZED = 'unrecognized'
    REGISTERED = 'registered'


class ActorType(enum.Enum):
    USER = 'user'
    SYSTEM = 'system'


class ConfigEditEntity(enum.Enum):
    """Versioned entity a ConfigEdit targets (Doc 6 section 5)."""

    SCHEDULES = 'schedules'
    CLEANUP_POLICIES = 'cleanup_policies'
    GLOBAL_SETTINGS = 'global_settings'
    WORLD_SETTINGS = 'world_settings'
    TEMPLATES = 'templates'
    ROLES = 'roles'
    SYNC_TARGETS = 'sync_targets'
    WORLD_INSTANCES = 'world_instances'
    SERVER_PROPERTIES = 'server_properties'
    JAVA_RUNTIMES = 'java_runtimes'
    USERS = 'users'
    DEVICES = 'devices'
    EULA = 'eula'


class EulaState(enum.Enum):
    """Detected from eula.txt (Doc 14 section 5).

    ``accepted`` is written only by the explicit audited operator action.
    """

    NOT_PRESENT = 'not_present'
    UNACCEPTED = 'unaccepted'
    ACCEPTED = 'accepted'


class ServerReadinessLevel(enum.Enum):
    """Strictly ordered readiness ladder (Doc 14 section 3).

    The highest available level for the server type gates ``starting ->
    running``. Enum order is the hierarchy order.
    """

    PROCESS_ALIVE = 'process_alive'
    PORT_BOUND = 'port_bound'
    RCON_READY = 'rcon_ready'
    PROBE_OK = 'probe_ok'
    OPERATIONALLY_VALID = 'operationally_valid'

    @property
    def rank(self) -> int:
        """Compare levels numerically; higher rank = closer to ready.

        PROCESS_ALIVE = 0 ... OPERATIONALLY_VALID = 4.
        """
        return list(ServerReadinessLevel.__members__.values()).index(self)


class AddressingStrategy(enum.Enum):
    SUBDOMAIN = 'subdomain'
    PORT = 'port'
    PATH = 'path'


class SyncTargetType(enum.Enum):
    NAS = 'nas'
    GOOGLE_DRIVE = 'google_drive'
    OTHER = 'other'


class ServerType(enum.Enum):
    """Closed server-type set for Template/WorldInstance."""

    VANILLA = 'vanilla'
    PAPER = 'paper'
    FABRIC = 'fabric'
    FORGE = 'forge'


class ExitClass(enum.Enum):
    """Exit classification for the process adapter (Doc 13)."""

    RUNNING = 'running'
    GRACEFUL = 'graceful'
    FORCED = 'forced'
    CRASHED = 'crashed'
    RECONCILED_MISSING = 'reconciled_missing'
    SPAWN_FAILED = 'spawn_failed'


class Signal(enum.Enum):
    """Signals understood by the process-control port (Doc 13 section 2)."""

    TERMINATE = 'terminate'  # SIGTERM (POSIX) / CTRL_BREAK_EVENT (Windows)
    KILL = 'kill'  # SIGKILL (POSIX) / TerminateJobObject (Windows)


class ProcessState(enum.Enum):
    """Live process-state classification (Doc 13 section 2)."""

    RUNNING = 'running'
    EXITED = 'exited'
    MISSING = 'missing'  # PID reused / identity mismatch


# String-typed-by-design closed sets (validated in code, not enums)
# per Doc 6 section 5. Kept as module constants for reuse.
SERVER_TYPES_CLOSED = frozenset(t.value for t in ServerType)
ADDRESSING_STRATEGIES_CLOSED = frozenset(t.value for t in AddressingStrategy)
SYNC_TARGET_TYPES_CLOSED = frozenset(t.value for t in SyncTargetType)
