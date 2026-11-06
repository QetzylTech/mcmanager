"""API envelope helpers."""

from __future__ import annotations

from flask import jsonify

from app.services.configuration import ConfigurationConflictError


def ok(data: dict, *, status: int = 200, meta: dict | None = None):
    return jsonify({'ok': True, 'data': data, 'meta': meta or {}}), status


def error(code: str, message: str, *, status: int = 400, details: dict | None = None, meta: dict | None = None):
    return jsonify({'ok': False, 'error': {'code': code, 'message': message, 'details': details or {}}, 'meta': meta or {}}), status


def register_error_handlers(app) -> None:
    """Register stable HTTP mappings for application service errors."""

    @app.errorhandler(ConfigurationConflictError)
    def handle_configuration_conflict(exc: ConfigurationConflictError):
        return error(
            "CONFIG_VERSION_CONFLICT",
            str(exc) or "Configuration changed; reload and retry.",
            status=409,
        )
