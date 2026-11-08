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
            self.container.store.writer().execute('SELECT 1').fetchone()
        except Exception:  # noqa: BLE001
            return {'status': 'degraded', 'db': 'down', 'version': 'dev'}
        return {'status': 'ok', 'db': 'ok', 'version': 'dev'}

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
        return {
            'status': 'ok',
            'tick_interval_seconds': self.container.scheduler.tick_interval_seconds,
            'incomplete_operations': len(self.container.operations.list_incomplete()),
        }

    def _sqlite_writer(self) -> dict[str, Any]:
        start = time.perf_counter()
        self.container.store.writer().execute('SELECT 1').fetchone()
        latency_ms = (time.perf_counter() - start) * 1000
        return {'status': 'ok', 'latency_ms': round(latency_ms, 3), 'path': self.container.store.path}

    def _process_adapter(self) -> dict[str, Any]:
        adapter = self.container.process_adapter
        return {'status': 'ok', 'adapter': adapter.__class__.__name__}

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
        queued = self.container.store.reader().execute(
            "SELECT count(*) FROM operations WHERE status = 'Queued'"
        ).fetchone()[0]
        return {'queued': int(queued), 'in_flight': len(self.container.operations.list_incomplete())}
