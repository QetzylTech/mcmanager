"""System health and diagnostics routes."""

from __future__ import annotations

from flask import Blueprint, current_app

from app.services.diagnostics import DiagnosticsService
from app.web.errors import ok

system_bp = Blueprint('api_system', __name__, url_prefix='/api')


@system_bp.get('/health')
def health():
    diagnostics = DiagnosticsService(current_app.extensions['mcmanager_container'])
    return ok(diagnostics.health())


@system_bp.get('/diagnostics')
def diagnostics():
    diagnostics_service = DiagnosticsService(current_app.extensions['mcmanager_container'])
    return ok(diagnostics_service.diagnostics())


@system_bp.get('/system/stats')
def system_stats():
    container = current_app.extensions['mcmanager_container']
    worlds = container.store.reader().execute(
        'SELECT COUNT(*) AS n FROM world_instances WHERE deleted_at IS NULL'
    ).fetchone()
    return ok({'worlds_count': worlds['n'], 'at': int(container.clock.now())})
