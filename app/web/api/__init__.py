"""API blueprint registration."""

from __future__ import annotations

from flask import Flask

from app.web.api.auth_routes import auth_bp
from app.web.api.pages import pages_bp
from app.web.api.system import system_bp


def register_api_blueprints(app: Flask) -> None:
    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(system_bp)
