"""API blueprint registration."""

from __future__ import annotations

from flask import Flask

from app.web.api.administration import administration_bp
from app.web.api.auth_routes import auth_bp
from app.web.api.catalogs import catalogs_bp
from app.web.api.configuration import configuration_bp
from app.web.api.history import history_bp
from app.web.api.pages import pages_bp
from app.web.api.system import system_bp
from app.web.api.world_management import world_management_bp


def register_api_blueprints(app: Flask) -> None:
    app.register_blueprint(administration_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(catalogs_bp)
    app.register_blueprint(configuration_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(world_management_bp)
