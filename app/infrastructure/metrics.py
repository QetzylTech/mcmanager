"""psutil-backed host resource metrics adapter."""

from __future__ import annotations

from pathlib import Path

import psutil

from app.ports.host_metrics import HostMetricSnapshot, HostMetricsPort


class PsutilHostMetrics(HostMetricsPort):
    """Collect CPU, memory, and storage usage for the manager volume."""

    def __init__(self, storage_path: Path) -> None:
        self._storage_path = storage_path

    def collect(self) -> HostMetricSnapshot:
        per_core = tuple(float(value) for value in psutil.cpu_percent(interval=None, percpu=True))
        if not per_core:
            per_core = (0.0,)
        memory = psutil.virtual_memory()
        storage = psutil.disk_usage(str(self._storage_path))
        return HostMetricSnapshot(
            cpu_pct=round(sum(per_core) / len(per_core), 2),
            cpu_per_core_pct=per_core,
            ram_mb=round(memory.used / (1024 * 1024), 2),
            storage_pct=round(storage.used / storage.total * 100, 2),
        )
