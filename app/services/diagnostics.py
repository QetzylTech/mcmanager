"""Manager diagnostics for scheduler, SQLite writer, and process adapter."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

from app.ports.persistence import PersistencePort
from app.ports.process_control import ProcessControlPort
from app.services.operations import OperationService
from app.services.reconciliation import ReconciliationService
from app.services.scheduler import SchedulerService
from app.version import __version__


class DiagnosticsDependencies(Protocol):
    """Service capabilities needed to build manager diagnostics."""

    scheduler: SchedulerService
    operations: OperationService
    store: PersistencePort
    process_adapter: ProcessControlPort
    reconciliation: ReconciliationService


@dataclass(frozen=True)
class DiagnosticsService:
    container: DiagnosticsDependencies

    def health(self) -> dict[str, str]:
        try:
            probe = self._probe_writer()
        except Exception:  # noqa: BLE001
            return {'status': 'degraded', 'db': 'down', 'version': __version__}
        db_status = probe['status']
        if db_status != 'ok':
            return {'status': 'degraded', 'db': str(db_status), 'version': __version__}
        return {'status': 'ok', 'db': 'ok', 'version': __version__}

    def diagnostics(self) -> dict[str, Any]:
        return {
            'scheduler': self._scheduler(),
            'sqlite_writer': self._sqlite_writer(),
            'process_adapter': self._process_adapter(),
            'foreign_key_check': self._foreign_key_check(),
            'reconciliation': self._reconciliation(),
            'operation_backlog': self._operation_backlog(),
        }

    def _scheduler(self) -> dict[str, Any]:
        tick_health = getattr(self.container.scheduler, 'tick_health', {})
        tick_status = tick_health.get('status', 'unknown')
        return {
            'status': 'degraded' if tick_status == 'failed' else 'ok',
            'tick_interval_seconds': self.container.scheduler.tick_interval_seconds,
            'tick_status': tick_status,
            'last_tick_at': tick_health.get('last_tick_at'),
            'next_tick_at': tick_health.get('next_tick_at'),
            'last_tick_error': tick_health.get('error'),
            'incomplete_operations': len(self.container.operations.list_incomplete()),
        }

    def _sqlite_writer(self) -> dict[str, Any]:
        try:
            probe = self._probe_writer()
        except Exception:  # noqa: BLE001
            probe = {'status': 'down', 'latency_ms': None}
        state = getattr(self.container.store, 'diagnostics_state', {})
        return {
            'status': probe['status'],
            'latency_ms': probe['latency_ms'],
            'path': self.container.store.path,
            'busy': bool(state.get('busy', probe['status'] == 'busy')),
            'wedged': bool(state.get('wedged', probe['status'] == 'wedged')),
            'last_busy_at': state.get('last_busy_at'),
            'last_wedged_at': state.get('last_wedged_at'),
            'last_successful_checkpoint_at': state.get('last_successful_checkpoint_at'),
        }

    def _probe_writer(self) -> dict[str, Any]:
        probe = getattr(self.container.store, 'probe_writer', None)
        if callable(probe):
            return probe()
        start = time.perf_counter()
        self.container.store.writer().execute('SELECT 1').fetchone()
        latency_ms = (time.perf_counter() - start) * 1000
        return {'status': 'ok', 'latency_ms': round(latency_ms, 3)}

    def _process_adapter(self) -> dict[str, Any]:
        adapter = self.container.process_adapter
        poll_health = getattr(adapter, 'last_poll_health', {})
        return {
            'status': 'degraded' if poll_health.get('status') == 'failed' else 'ok',
            'adapter': adapter.__class__.__name__,
            'last_poll_at': poll_health.get('last_poll_at'),
            'last_poll_status': poll_health.get('status', 'unknown'),
            'last_poll_process_state': poll_health.get('process_state'),
            'last_poll_error': poll_health.get('error'),
        }

    def _foreign_key_check(self) -> dict[str, Any]:
        violations = self.container.store.reader().execute('PRAGMA foreign_key_check').fetchall()
        return {'status': 'ok' if not violations else 'failed', 'violations': len(violations)}

    def _reconciliation(self) -> dict[str, Any]:
        outcome = self.container.reconciliation.health
        return {
            'status': 'ok' if outcome.status == 'healthy' else 'down',
            'phase': outcome.status,
            'reattached_worlds': len(outcome.reattached_world_ids),
            **({'error': outcome.error} if outcome.error is not None else {}),
        }

    def _operation_backlog(self) -> dict[str, int]:
        row = self.container.store.reader().execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN status = 'Queued' THEN 1 ELSE 0 END), 0) AS queued,
                COALESCE(SUM(CASE WHEN status IN
                    ('Created', 'Queued', 'Validating', 'Running') THEN 1 ELSE 0 END), 0)
                    AS in_flight
            FROM operations
            """
        ).fetchone()
        return {
            'queued': int(row['queued']),
            'in_flight': int(row['in_flight']),
        }
