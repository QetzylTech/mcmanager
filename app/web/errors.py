"""API envelope helpers."""

from __future__ import annotations

from typing import Any

from flask import Flask, Response, jsonify

from app.services.configuration import ConfigurationConflictError

ERROR_STATUS_CODES = {
    # Validation and authorization.
    "VALIDATION_ERROR": 400,
    "VALIDATION_STALE_VERSION": 409,
    "AUTH_INVALID_CREDENTIALS": 401,
    "AUTH_ACCOUNT_LOCKED": 403,
    "AUTH_THROTTLED": 429,
    "AUTH_SESSION_EXPIRED": 401,
    "AUTH_SESSION_REVOKED": 401,
    "AUTH_CSRF_INVALID": 403,
    "AUTH_STEP_UP_REQUIRED": 403,
    "AUTH_STEP_UP_EXPIRED": 403,
    "FORBIDDEN": 403,
    "FORBIDDEN_LAST_SUPERADMIN": 409,
    "NOT_FOUND": 404,
    # Worlds and operations.
    "WORLD_NOT_FOUND": 404,
    "WORLD_DELETED": 409,
    "WORLD_NOT_OFF": 409,
    "WORLD_ALREADY_RUNNING": 409,
    "WORLD_IN_COOLDOWN": 409,
    "WORLD_NAME_CONFLICT": 409,
    "WORLD_PORT_CONFLICT": 409,
    "WORLD_RUNTIME_CONFIG_STATE": 409,
    "EULA_NOT_ACCEPTED": 409,
    "JAVA_INCOMPATIBLE": 409,
    "OP_NOT_FOUND": 404,
    "OP_NOT_CANCELLABLE": 409,
    "OP_ALREADY_TERMINAL": 409,
    "OP_CONFLICT_IN_FLIGHT": 409,
    "OP_QUEUED": 202,
    "OP_MANAGER_RESTART_INCOMPLETE": 409,
    "STORAGE_GUARD_TRIPPED": 409,
    # Backup, restore, sync, and configuration.
    "BACKUP_ARTIFACT_NOT_FOUND": 404,
    "BACKUP_INVALID_CHECKSUM": 409,
    "BACKUP_RETENTION_GUARD": 409,
    "RESTORE_ARTIFACT_INVALID": 409,
    "RESTORE_PREBACKUP_FAILED": 502,
    "SYNC_TARGET_UNRESOLVED": 409,
    "SYNC_CONCURRENCY_CAP": 429,
    "CONFIG_INVALID_KEY": 400,
    "CONFIG_INVALID_VALUE": 400,
    "CONFIG_VERSION_CONFLICT": 409,
    "CLEANUP_NOTHING_TO_DO": 200,
    "CLEANUP_PREVIEW_REQUIRED": 409,
    "CLEANUP_BLAST_RADIUS": 409,
    "CLEANUP_POLICY_FLOOR": 409,
    # Files, schedules, and devices.
    "FILE_PATH_UNAUTHORIZED": 403,
    "FILE_NOT_FOUND": 404,
    "FILE_EXISTS": 409,
    "FILE_TOO_LARGE": 400,
    "FILE_INVALID": 400,
    "SCHEDULE_CONFLICT": 409,
    "MISSED_RUN_RESOLVED": 409,
    "DEVICE_UNREGISTERED": 403,
    "DEVICE_REVOKED": 403,
    "INTERNAL_ERROR": 500,
    "NOT_IMPLEMENTED": 501,
    # Compatibility codes still emitted by existing middleware and routes.
    "AUTH_SESSION_INVALID": 401,
    "AUTH_LOCKED": 429,
    "AUTH_DISABLED": 403,
    "AUTH_FORBIDDEN": 403,
    "CSRF_INVALID": 403,
    "STEP_UP_REQUIRED": 403,
    "WORLD_CONFLICT": 409,
    "START_FAILED": 422,
    "STOP_FAILED": 422,
    "KILL_FAILED": 422,
    "EULA_ACCEPT_FAILED": 422,
    "STORAGE_GUARD_FAILED": 409,
}


def ok(
    data: dict[str, Any],
    *,
    status: int = 200,
    meta: dict[str, Any] | None = None,
) -> tuple[Response, int]:
    return jsonify({'ok': True, 'data': data, 'meta': meta or {}}), status


def error(
    code: str,
    message: str,
    *,
    status: int | None = None,
    details: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> tuple[Response, int]:
    """Build the standard API error envelope using the catalog's HTTP mapping."""
    mapped_status = ERROR_STATUS_CODES.get(code, status if status is not None else 500)
    return (
        jsonify(
            {
                'ok': False,
                'error': {'code': code, 'message': message, 'details': details or {}},
                'meta': meta or {},
            }
        ),
        mapped_status,
    )


def register_error_handlers(app: Flask) -> None:
    """Register stable HTTP mappings for application service errors."""

    @app.errorhandler(ConfigurationConflictError)
    def handle_configuration_conflict(
        exc: ConfigurationConflictError,
    ) -> tuple[Response, int]:
        return error(
            "CONFIG_VERSION_CONFLICT",
            str(exc) or "Configuration changed; reload and retry.",
            status=409,
        )
