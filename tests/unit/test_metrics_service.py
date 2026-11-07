from __future__ import annotations

import threading

from app.domain.tuning import METRICS_CADENCE_CACHE_S, METRICS_CADENCE_STREAM_HZ
from app.ports.host_metrics import HostMetricSnapshot
from app.services.metrics import MetricsService


class _Cursor:
    def __init__(self, row: tuple[int, ...] | None = None) -> None:
        self._row = row

    def fetchone(self) -> tuple[int, ...] | None:
        return self._row

    def fetchall(self) -> list[dict[str, str | int]]:
        return []


class _Store:
    def reader(self) -> _Store:
        return self

    def execute(self, query: str, params: tuple[str, ...] = ()) -> _Cursor:
        del params
        if 'SELECT count(*) FROM world_instances' in query:
            return _Cursor((1,))
        return _Cursor()


class _Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def now(self) -> float:
        return self.value


class _HostMetrics:
    def __init__(self, samples: list[HostMetricSnapshot | Exception]) -> None:
        self.samples = samples
        self.calls = 0

    def collect(self) -> HostMetricSnapshot:
        sample = self.samples[self.calls]
        self.calls += 1
        if isinstance(sample, Exception):
            raise sample
        return sample


class _Realtime:
    def __init__(self, subscribers: int) -> None:
        self.subscribers = subscribers
        self.published: list[dict[str, object]] = []

    def subscriber_count(self, stream: str) -> int:
        assert stream == 'metrics'
        return self.subscribers

    def publish(self, stream: str, event: str, payload: dict[str, object]) -> None:
        assert stream == event == 'metrics'
        self.published.append(payload)


class _WakeTwice:
    def __init__(self, stop_event: threading.Event) -> None:
        self.stop_event = stop_event
        self.waits: list[float] = []

    def wait(self, timeout: float) -> None:
        self.waits.append(timeout)
        if len(self.waits) == 2:
            self.stop_event.set()

    def clear(self) -> None:
        pass


def _sample(cpu_pct: float) -> HostMetricSnapshot:
    return HostMetricSnapshot(
        cpu_pct=cpu_pct,
        cpu_per_core_pct=(cpu_pct,),
        ram_mb=2048.0,
        storage_pct=42.0,
    )


def test_worker_retries_after_host_metrics_failure_without_publishing_fake_values(
    monkeypatch,
) -> None:
    stop_event = threading.Event()
    wake = _WakeTwice(stop_event)
    realtime = _Realtime(subscribers=1)
    host_metrics = _HostMetrics([OSError('temporary metrics failure'), _sample(37.5)])
    service = MetricsService(_Store(), _Clock(), realtime, host_metrics)
    service._wake = wake
    thread_errors: list[BaseException] = []
    monkeypatch.setattr(
        threading,
        'excepthook',
        lambda args: thread_errors.append(args.exc_value),
    )

    worker = threading.Thread(target=service.run, args=(stop_event,))
    worker.start()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert thread_errors == []
    assert host_metrics.calls == 2
    assert wake.waits == [1.0 / METRICS_CADENCE_STREAM_HZ] * 2
    assert realtime.published == [
        {
            'metrics': {
                'cpu_pct': 37.5,
                'cpu_per_core_pct': [37.5],
                'ram_mb': 2048.0,
                'storage_pct': 42.0,
                'worlds_count': 0,
                'world_states': {},
                'at': 100,
            },
            'freshness': 100,
        }
    ]


def test_failed_refresh_preserves_last_valid_cache_and_cache_cadence() -> None:
    clock = _Clock()
    realtime = _Realtime(subscribers=0)
    host_metrics = _HostMetrics([_sample(22.0), OSError('temporary metrics failure')])
    service = MetricsService(_Store(), clock, realtime, host_metrics)

    assert service.tick() == float(METRICS_CADENCE_CACHE_S)
    cached_snapshot = service._cache
    cached_at = service._cache_at
    clock.value += METRICS_CADENCE_CACHE_S

    assert service.tick() == float(METRICS_CADENCE_CACHE_S)

    assert service._cache == cached_snapshot
    assert service._cache_at == cached_at
    assert len(realtime.published) == 0
