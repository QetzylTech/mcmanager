"""Runtime facade and startup reconciliation contracts (Gate 3 / WP 3.2)."""

from __future__ import annotations

import importlib
import threading
from types import SimpleNamespace

import pytest

from app.services.reconciliation import ReconciliationService
from app.services.runtime import RuntimeService


class _Lifecycle:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failure: Exception | None = None
        self.start_failure: Exception | None = None

    def start(self, **_kwargs) -> str:
        self.calls.append('start')
        if self.start_failure is not None:
            raise self.start_failure
        return 'started-session'

    def reconcile(self) -> list[str]:
        self.calls.append('reconcile')
        if self.failure is not None:
            raise self.failure
        return ['reattached-world']

    def poll_running(self) -> list[str]:
        self.calls.append('poll_running')
        return ['crashed-world']

    def supervisor_interval_seconds(self) -> float:
        self.calls.append('supervisor_interval_seconds')
        return 1.0


def test_runtime_facade_delegates_to_worlds_lifecycle_reattach_api() -> None:
    lifecycle = _Lifecycle()
    runtime = RuntimeService(lifecycle)  # type: ignore[arg-type]

    assert runtime.reconcile() == ['reattached-world']
    assert runtime.poll_running() == ['crashed-world']
    assert runtime.supervisor_interval_seconds() == 1.0
    assert lifecycle.calls == [
        'reconcile',
        'poll_running',
        'supervisor_interval_seconds',
    ]


def test_runtime_restore_restart_does_not_hide_start_errors() -> None:
    failure = RuntimeError('restart failed')
    lifecycle = _Lifecycle()
    lifecycle.start_failure = failure
    runtime = RuntimeService(lifecycle)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError) as caught:
        runtime.restart_and_confirm('world')

    assert caught.value is failure


def test_reconciliation_health_records_successful_reattachment() -> None:
    reconciliation = ReconciliationService(RuntimeService(_Lifecycle()))  # type: ignore[arg-type]

    assert reconciliation.health.status == 'not_started'
    assert reconciliation.reconcile() == ['reattached-world']
    assert reconciliation.health.status == 'healthy'
    assert reconciliation.health.reattached_world_ids == ('reattached-world',)
    assert reconciliation.health.error is None


def test_reconciliation_failure_is_health_visible_and_reraised() -> None:
    failure = RuntimeError('process probe failed')
    lifecycle = _Lifecycle()
    lifecycle.failure = failure
    reconciliation = ReconciliationService(RuntimeService(lifecycle))  # type: ignore[arg-type]

    with pytest.raises(RuntimeError) as caught:
        reconciliation.reconcile()

    assert caught.value is failure
    assert reconciliation.health.status == 'failed'
    assert reconciliation.health.reattached_world_ids == ()
    assert reconciliation.health.error == 'process probe failed'


def test_startup_reconciliation_failure_blocks_app_and_worker_start(monkeypatch) -> None:
    app_module = importlib.import_module('app')
    failure = RuntimeError('boot reconciliation failed')
    started: list[threading.Thread] = []
    container = SimpleNamespace(
        reconciliation=SimpleNamespace(
            reconcile=lambda: (_ for _ in ()).throw(failure)
        ),
        scheduler=SimpleNamespace(tick_interval_seconds=30),
    )
    monkeypatch.setattr(app_module, 'build_container', lambda **_kwargs: container)
    monkeypatch.setattr(threading.Thread, 'start', lambda thread: started.append(thread))

    with pytest.raises(RuntimeError) as caught:
        app_module.create_app(database_path='unused.db', keyfile_path='unused.key')

    assert caught.value is failure
    assert started == []


def test_successful_startup_starts_all_background_workers(monkeypatch) -> None:
    app_module = importlib.import_module('app')
    started: list[threading.Thread] = []
    container = SimpleNamespace(
        reconciliation=ReconciliationService(RuntimeService(_Lifecycle())),
        scheduler=SimpleNamespace(tick_interval_seconds=30),
        runtime=SimpleNamespace(
            poll_running=lambda: [],
            supervisor_interval_seconds=lambda: 15,
        ),
    )
    monkeypatch.setattr(app_module, 'build_container', lambda **_kwargs: container)
    monkeypatch.setattr(threading.Thread, 'start', lambda thread: started.append(thread))

    app = app_module.create_app(database_path='unused.db', keyfile_path='unused.key')

    assert {thread.name for thread in started} == {
        'mcmanager-runtime-supervisor',
        'mcmanager-scheduler',
        'mcmanager-operation-dispatcher',
    }
    assert app.extensions['mcmanager_container'] is container
    assert app.extensions['mcmanager_reconciliation_health'].status == 'healthy'
