"""MCManager application package and Flask factory."""

from __future__ import annotations

from pathlib import Path

from flask import Flask

from app.bootstrap import build_container
from app.ports.clock import Clock
from app.shell.routes import shell_bp
from app.web.api import register_api_blueprints
from app.web.streams import register_stream_blueprints


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

    # Boot reconciliation (Doc 13 §5.1): re-attach any world with an open
    # runtime session that survived a previous manager run.
    try:
        container.worlds.reconcile()
    except Exception:  # noqa: BLE001 - a failed reconcile must not block boot
        pass
    app.register_blueprint(shell_bp)
    register_api_blueprints(app)
    register_stream_blueprints(app)

    @app.teardown_appcontext
    def _close_store(_exc) -> None:
        # Test clients may create/tear down multiple apps quickly.
        pass

    return app
