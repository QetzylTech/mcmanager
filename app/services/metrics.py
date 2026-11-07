"""Cached host/world metrics collection and shared SSE publication."""

from __future__ import annotations

import logging
import threading
from threading import Event, RLock
from typing import TypedDict

from app.domain.tuning import (
    METRICS_CADENCE_CACHE_S,
    METRICS_CADENCE_STREAM_HZ,
)
from app.domain.value_objects import WorldState
from app.ports.clock import Clock
from app.ports.host_metrics import HostMetricsPort
from app.ports.persistence import PersistencePort
from app.services.realtime import RealtimeHub


class MetricsSnapshot(TypedDict):
    cpu_pct: float
    cpu_per_core_pct: list[float]
    ram_mb: float
    storage_pct: float
    worlds_count: int
    world_states: dict[str, int]
    at: int


class MetricsStreamPayload(TypedDict):
    metrics: MetricsSnapshot
    freshness: int


_ACTIVE_STATES = (
    WorldState.STARTING,
    WorldState.RUNNING,
    WorldState.STOPPING,
    WorldState.BACKING_UP,
    WorldState.RESTORING,
)

_logger = logging.getLogger(__name__)


class _HostMetricsCollectionError(Exception):
    """A host metrics sample could not be collected."""


class MetricsService:
    """Refresh one cached snapshot and publish it once per active stream tick."""

    def __init__(
        self,
        store: PersistencePort,
        clock: Clock,
        realtime: RealtimeHub,
        host_metrics: HostMetricsPort,
    ) -> None:
        self._store = store
        self._clock = clock
        self._realtime = realtime
        self._host_metrics = host_metrics
        self._cache: MetricsSnapshot | None = None
        self._cache_at: float | None = None
        self._cache_lock = RLock()
        self._wake = Event()

    def stream_snapshot(self) -> MetricsStreamPayload:
        """Return a fresh-enough initial snapshot and wake the cadence worker."""
        self.notify_subscribers_changed()
        return {
            'metrics': self._snapshot(),
            'freshness': int(self._clock.now()),
        }

    def notify_subscribers_changed(self) -> None:
        """Wake the worker when a metrics stream connects or disconnects."""
        self._wake.set()

    def tick(self) -> float | None:
        """Refresh/publish according to MetricsCadence; return the next interval."""
        clients = self._realtime.subscriber_count('metrics')
        active_worlds = self._active_world_count()
        if clients == 0 and active_worlds == 0:
            return None

        try:
            snapshot = self._snapshot()
        except _HostMetricsCollectionError:
            _logger.warning('Host metrics collection failed; skipping metrics tick', exc_info=True)
            if clients > 0:
                return 1.0 / METRICS_CADENCE_STREAM_HZ
            return float(METRICS_CADENCE_CACHE_S)
        if clients > 0:
            self._realtime.publish(
                'metrics',
                'metrics',
                {'metrics': snapshot, 'freshness': int(self._clock.now())},
            )
            return 1.0 / METRICS_CADENCE_STREAM_HZ
        return float(METRICS_CADENCE_CACHE_S)

    def run(self, stop_event: threading.Event) -> None:
        """Run the cadence loop until application shutdown."""
        while not stop_event.is_set():
            interval = self.tick()
            timeout = float(METRICS_CADENCE_CACHE_S) if interval is None else interval
            self._wake.wait(timeout)
            self._wake.clear()

    def _active_world_count(self) -> int:
        placeholders = ', '.join('?' for _ in _ACTIVE_STATES)
        return int(
            self._store.reader()
            .execute(
                f"SELECT count(*) FROM world_instances WHERE deleted_at IS NULL "
                f"AND state IN ({placeholders})",
                tuple(state.value for state in _ACTIVE_STATES),
            )
            .fetchone()[0]
        )

    def _snapshot(self) -> MetricsSnapshot:
        now = self._clock.now()
        with self._cache_lock:
            if (
                self._cache is not None
                and self._cache_at is not None
                and now - self._cache_at < METRICS_CADENCE_CACHE_S
            ):
                return self._copy_snapshot(self._cache)

            try:
                host = self._host_metrics.collect()
            except Exception as exc:
                raise _HostMetricsCollectionError from exc
            state_rows = self._store.reader().execute(
                "SELECT state, count(*) AS count FROM world_instances "
                "WHERE deleted_at IS NULL GROUP BY state"
            ).fetchall()
            world_states = {
                WorldState(str(row['state'])).value: int(row['count']) for row in state_rows
            }
            self._cache = {
                'cpu_pct': host.cpu_pct,
                'cpu_per_core_pct': list(host.cpu_per_core_pct),
                'ram_mb': host.ram_mb,
                'storage_pct': host.storage_pct,
                'worlds_count': sum(world_states.values()),
                'world_states': world_states,
                'at': int(now),
            }
            self._cache_at = now
            return self._copy_snapshot(self._cache)

    @staticmethod
    def _copy_snapshot(snapshot: MetricsSnapshot) -> MetricsSnapshot:
        return {
            **snapshot,
            'cpu_per_core_pct': list(snapshot['cpu_per_core_pct']),
            'world_states': dict(snapshot['world_states']),
        }
