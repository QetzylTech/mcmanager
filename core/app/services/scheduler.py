"""Scheduler tick and missed-run detection (Gate 3)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.domain.tuning import SCHEDULER_TICK_INTERVAL_S
from app.domain.value_objects import ActorType, MissedRunResolution, OperationType
from app.infrastructure.sqlite.connection import SqliteStore
from app.ports.clock import Clock
from app.services.operations import OperationConflictError, OperationInput, OperationService


@dataclass(frozen=True)
class SchedulerTickResult:
    due: int
    dispatched: int
    missed: int


class SchedulerService:
    """Evaluates enabled schedules every 30 seconds."""

    tick_interval_seconds = SCHEDULER_TICK_INTERVAL_S

    def __init__(self, store: SqliteStore, clock: Clock, operations: OperationService) -> None:
        self._store = store
        self._clock = clock
        self._operations = operations

    def tick(self) -> SchedulerTickResult:
        now = int(self._clock.now())
        due = 0
        dispatched = 0
        missed = 0
        for schedule in self._enabled_schedules():
            expected = self._expected_run_at(schedule, now)
            if expected is None:
                continue
            due += 1
            if self._has_recorded(schedule['schedule_id'], expected):
                continue
            op_type = self._operation_type_for(schedule['schedule_type'])
            if op_type is None:
                missed += self._record_missed(schedule, expected, now)
                continue
            try:
                self._operations.create(
                    OperationInput(
                        op_type=op_type,
                        actor_type=ActorType.SYSTEM,
                        world_id=schedule['world_id'],
                        idempotency_key=f"schedule:{schedule['schedule_id']}:{expected}",
                        data={'schedule_id': schedule['schedule_id'], 'expected_run_at': expected},
                    ),
                    initial_status=self._queued_status(),
                )
                dispatched += 1
            except OperationConflictError:
                missed += self._record_missed(schedule, expected, now)
        return SchedulerTickResult(due=due, dispatched=dispatched, missed=missed)

    def _enabled_schedules(self) -> list[dict[str, Any]]:
        rows = self._store.reader().execute(
            """
            SELECT *
            FROM schedules
            WHERE enabled = 1 AND deleted_at IS NULL
            ORDER BY created_at ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def _expected_run_at(self, schedule: dict[str, Any], now: int) -> int | None:
        spec = json.loads(schedule['interval_spec'])
        last_changed_at = int(schedule['last_changed_at'])
        kind = spec.get('kind') or spec.get('type')
        if kind == 'every_n_days':
            days = max(1, int(spec.get('days', 1)))
            period = days * 24 * 60 * 60
            elapsed = now - last_changed_at
            if elapsed < period:
                return None
            return last_changed_at + (elapsed // period) * period

        if kind in ('daily', 'weekly', 'monthly'):
            target_hour, target_minute = self._parse_time_of_day(schedule['time_of_day'])
            now_dt = datetime.fromtimestamp(now, tz=timezone.utc)
            candidate = now_dt.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            if int(candidate.timestamp()) > now:
                candidate = candidate - timedelta(days=1)
            expected = int(candidate.timestamp())
            if expected <= last_changed_at:
                return None
            return expected
        return None

    def _record_missed(self, schedule: dict[str, Any], expected: int, detected: int) -> int:
        connection = self._store.writer()
        if self._has_recorded(schedule['schedule_id'], expected):
            return 0
        connection.execute(
            """
            INSERT INTO missed_run_records (
                missed_run_id, schedule_id, schedule_name_snapshot,
                schedule_type_snapshot, expected_run_at, detected_at,
                resolution, resolution_at, resolution_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
            """,
            (
                f'mr_{uuid.uuid4().hex[:16]}',
                schedule['schedule_id'],
                self._snapshot_name(schedule),
                schedule['schedule_type'],
                expected,
                detected,
                MissedRunResolution.PENDING.value,
                detected,
            ),
        )
        connection.commit()
        return 1

    def _has_recorded(self, schedule_id: str, expected: int) -> bool:
        row = self._store.reader().execute(
            """
            SELECT 1
            FROM missed_run_records
            WHERE schedule_id = ? AND expected_run_at = ?
            LIMIT 1
            """,
            (schedule_id, expected),
        ).fetchone()
        return row is not None

    def _operation_type_for(self, schedule_type: str) -> OperationType | None:
        if schedule_type == 'backup':
            return OperationType.BACKUP
        if schedule_type in ('cleanup', 'maintenance'):
            return OperationType.CLEANUP
        return None

    def _snapshot_name(self, schedule: dict[str, Any]) -> str:
        scope = 'Global' if schedule['world_id'] is None else schedule['world_id']
        return f"{scope} {schedule['schedule_type']} schedule"

    def _parse_time_of_day(self, value: str) -> tuple[int, int]:
        hour, minute = value.split(':', 1)
        return int(hour), int(minute)

    def _queued_status(self):
        from app.domain.value_objects import OperationStatus

        return OperationStatus.QUEUED
