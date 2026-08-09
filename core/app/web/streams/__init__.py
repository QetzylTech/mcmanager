"""SSE stream blueprint registration."""

from __future__ import annotations

from flask import Flask

from app.web.streams.routes import streams_bp


def register_stream_blueprints(app: Flask) -> None:
    app.register_blueprint(streams_bp)
