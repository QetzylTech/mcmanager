"""Host resource metrics port used by the manager metrics service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class HostMetricSnapshot:
    """One host resource sample, collected without blocking the caller."""

    cpu_pct: float
    cpu_per_core_pct: tuple[float, ...]
    ram_mb: float
    storage_pct: float


class HostMetricsPort(Protocol):
    """Collect host-level metrics behind an infrastructure boundary."""

    def collect(self) -> HostMetricSnapshot:
        """Return a non-blocking host resource sample."""
        ...
