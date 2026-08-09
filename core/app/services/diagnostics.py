"""Manager diagnostics for scheduler, SQLite writer, and process adapter."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.bootstrap import Container


@dataclass(frozen=True)
class DiagnosticsService:
    container: Container

    def health(self) -> dict[str, str]:
        return {'status': 'ok', 'db': 'ok', 'version': 'dev'}

    def diagnostics(self) -> dict[str, Any]:
        return {
            'scheduler': self._scheduler(),
            'sqlite_writer': self._sqlite_writer(),
            'process_adapter': self._process_adapter(),
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
