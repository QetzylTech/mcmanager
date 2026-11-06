"""Domain layer: closed enums, value objects, invariants, entities.

Imports nothing outside itself + stdlib (Doc 12 dependency rule).
"""

from __future__ import annotations

from app.domain.value_objects import (
    ActorType,
    AddressingStrategy,
    BackupCategory,
    ConfigEditEntity,
    DeviceStatus,
    EndReason,
    EulaState,
    ExitClass,
    JavaRuntimeStatus,
    MissedRunResolution,
    NotificationSeverity,
    OperationStatus,
    OperationType,
    ProcessState,
    ScheduleType,
    Scope,
    ServerReadinessLevel,
    ServerType,
    Signal,
    SyncOutcome,
    SyncRecordStatus,
    SyncTargetType,
    TriggerType,
    UserStatus,
    WorldState,
)

__all__ = [
    'ActorType',
    'AddressingStrategy',
    'BackupCategory',
    'ConfigEditEntity',
    'DeviceStatus',
    'EndReason',
    'EulaState',
    'ExitClass',
    'JavaRuntimeStatus',
    'MissedRunResolution',
    'NotificationSeverity',
    'OperationStatus',
    'OperationType',
    'ProcessState',
    'ScheduleType',
    'Scope',
    'ServerReadinessLevel',
    'ServerType',
    'Signal',
    'SyncOutcome',
    'SyncRecordStatus',
    'SyncTargetType',
    'TriggerType',
    'UserStatus',
    'WorldState',
]
