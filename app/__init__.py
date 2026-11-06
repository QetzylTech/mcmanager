"""MCManager application package and Flask factory."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from flask import Flask

from app.bootstrap import build_container
from app.domain.tuning import SCHEDULER_TICK_INTERVAL_S, SUPERVISOR_POLL_IDLE_S
from app.ports.clock import Clock
from app.shell.routes import shell_bp
from app.web.api import register_api_blueprints
from app.web.errors import register_error_handlers
from app.web.middleware import register_middleware
from app.web.streams import register_stream_blueprints

_logger = logging.getLogger(__name__)


def _supervisor_worker(container: Any, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            runtime = getattr(container, 'runtime', None)
            if runtime is not None:
                runtime.poll_running()
                interval = runtime.supervisor_interval_seconds()
            else:
                container.worlds.poll_running()
                interval = SUPERVISOR_POLL_IDLE_S
        except Exception:
            _logger.exception('Runtime supervisor tick failed')
            interval = SUPERVISOR_POLL_IDLE_S
        stop_event.wait(interval)


def _scheduler_worker(container: Any, stop_event: threading.Event) -> None:
    interval = getattr(container.scheduler, 'tick_interval_seconds', SCHEDULER_TICK_INTERVAL_S)
    while not stop_event.wait(interval):
        try:
            container.scheduler.tick()
        except Exception:
            _logger.exception('Scheduler tick failed')


def create_app(
    *,
    database_path: str | Path,
    keyfile_path: str | Path,
    migrations_dir: str | Path | None = None,
    clock: Clock | None = None,
) -> Flask:
    """Build the web app, register thin page/API/stream blueprints."""
    app = Flask(
        __name__,
        template_folder='shell/templates',
        static_folder='shell/static',
        static_url_path='/static',
    )
    container = build_container(
        database_path=database_path,
        keyfile_path=keyfile_path,
        migrations_dir=migrations_dir,
        clock=clock,
    )
    app.extensions['mcmanager_container'] = container
    register_middleware(app)
    register_error_handlers(app)

    # Boot reconciliation (Doc 13 §5.1): re-attach any world with an open
    # runtime session that survived a previous manager run.
    reconciliation = getattr(container, 'reconciliation', None)
    if reconciliation is None:
        container.worlds.reconcile()
    else:
        reconciliation.reconcile()
    app.register_blueprint(shell_bp)
    register_api_blueprints(app)
    register_stream_blueprints(app)

    stop_event = threading.Event()
    app.extensions['mcmanager_workers_stop'] = stop_event
    threading.Thread(
        target=_supervisor_worker,
        args=(container, stop_event),
        name='mcmanager-runtime-supervisor',
        daemon=True,
    ).start()
    threading.Thread(
        target=_scheduler_worker,
        args=(container, stop_event),
        name='mcmanager-scheduler',
        daemon=True,
    ).start()

    @app.teardown_appcontext
    def _close_store(_exc: BaseException | None) -> None:
        # Test clients may create/tear down multiple apps quickly.
        pass

    return app
