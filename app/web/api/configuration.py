"""Global and per-world effective settings endpoints."""

from __future__ import annotations

import json
from typing import Any

from flask import Blueprint, Response, current_app, g, request

from app.domain.value_objects import ActorType, ConfigEditEntity
from app.services.configuration import ConfigurationConflictError, VersionedUpdate
from app.web.errors import error, ok

configuration_bp = Blueprint("api_configuration", __name__, url_prefix="/api")

_GLOBAL_FIELDS = frozenset(
    {
        "timezone",
        "idle_countdown_seconds",
        "notification_defaults",
        "minecraft_root_path",
        "backup_root_path",
        "log_root_path",
        "offsite_sync_defaults",
    }
)
_WORLD_FIELDS = {
    "idle_countdown_seconds": "idle_countdown_override",
    "minecraft_root_path": "minecraft_root_override",
    "backup_root_path": "backup_root_override",
    "log_root_path": "log_root_override",
    "offsite_sync_defaults": "offsite_sync_override",
}
_JSON_FIELDS = frozenset({"notification_defaults", "offsite_sync_defaults"})


def _container() -> Any:
    return current_app.extensions["mcmanager_container"]


def _request_update(fields: frozenset[str] | dict[str, str]) -> tuple[int, dict[str, Any]] | None:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None
    version = body.get("version")
    values = {key: value for key, value in body.items() if key != "version"}
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version < 0
        or not values
        or set(values).difference(fields)
    ):
        return None
    world_override = isinstance(fields, dict)
    for key, value in values.items():
        if key == "idle_countdown_seconds":
            valid = value is None or (type(value) is int and value >= 0)
        elif key in _JSON_FIELDS:
            valid = value is None or isinstance(value, dict)
        else:
            valid = isinstance(value, str) or (world_override and value is None)
        if not valid:
            return None
    mapping = fields if isinstance(fields, dict) else {key: key for key in fields}
    encoded = {
        mapping[key]: (
            json.dumps(value) if key in _JSON_FIELDS and value is not None else value
        )
        for key, value in values.items()
    }
    return version, encoded


@configuration_bp.get("/settings")
def get_global_settings() -> tuple[Response, int]:
    try:
        settings = _container().configuration.resolve_global()
    except KeyError:
        return error("NOT_FOUND", "Global settings are not initialized.", status=404)
    return ok(
        {
            "settings": {
                key: settings[key]
                for key in (
                    "timezone",
                    "idle_countdown_seconds",
                    "notification_defaults",
                    "minecraft_root_path",
                    "backup_root_path",
                    "log_root_path",
                    "offsite_sync_defaults",
                )
            },
            "version": settings["version"],
        }
    )


@configuration_bp.patch("/settings")
def update_global_settings() -> tuple[Response, int]:
    parsed = _request_update(_GLOBAL_FIELDS)
    if parsed is None:
        return error("VALIDATION_ERROR", "A version and editable settings are required.")
    version, fields = parsed
    try:
        current_settings = _container().configuration.resolve_global()
        _, operation = _container().configuration.update_versioned_with_operation(
            VersionedUpdate(
                entity=ConfigEditEntity.GLOBAL_SETTINGS,
                row_id=current_settings["settings_id"],
                expected_version=version,
                fields=fields,
                actor_type=ActorType.USER,
                actor_user_id=g.current_user_id,
            )
        )
    except ConfigurationConflictError:
        return error(
            "CONFIG_VERSION_CONFLICT",
            "Configuration changed; reload and retry.",
            status=409,
        )
    except KeyError:
        return error("NOT_FOUND", "Global settings are not initialized.", status=404)
    settings = _container().configuration.resolve_global()
    return ok(
        {
            "settings": {
                key: settings[key]
                for key in (
                    "timezone",
                    "idle_countdown_seconds",
                    "notification_defaults",
                    "minecraft_root_path",
                    "backup_root_path",
                    "log_root_path",
                    "offsite_sync_defaults",
                )
            },
            "version": settings["version"],
            "operation": operation,
        },
        meta={"op_id": operation["op_id"]},
    )


@configuration_bp.get("/worlds/<world_id>/settings")
def get_world_settings(world_id: str) -> tuple[Response, int]:
    container = _container()
    world = (
        container.store.reader()
        .execute(
            "SELECT 1 FROM world_instances WHERE world_id = ? AND deleted_at IS NULL",
            (world_id,),
        )
        .fetchone()
    )
    if world is None:
        return error("NOT_FOUND", "World not found.", status=404)
    override = (
        container.store.reader()
        .execute("SELECT version FROM world_settings WHERE world_id = ?", (world_id,))
        .fetchone()
    )
    return ok(
        {
            "settings": container.configuration.resolve_effective(world_id),
            "version": override["version"] if override is not None else 0,
        }
    )


@configuration_bp.patch("/worlds/<world_id>/settings")
def update_world_settings(world_id: str) -> tuple[Response, int]:
    container = _container()
    world = (
        container.store.reader()
        .execute(
            "SELECT 1 FROM world_instances WHERE world_id = ? AND deleted_at IS NULL",
            (world_id,),
        )
        .fetchone()
    )
    if world is None:
        return error("NOT_FOUND", "World not found.", status=404)
    parsed = _request_update(_WORLD_FIELDS)
    if parsed is None:
        return error("VALIDATION_ERROR", "A version and editable settings are required.")
    version, fields = parsed
    try:
        _, operation = container.configuration.update_versioned_with_operation(
            VersionedUpdate(
                entity=ConfigEditEntity.WORLD_SETTINGS,
                row_id=world_id,
                expected_version=version,
                fields=fields,
                actor_type=ActorType.USER,
                actor_user_id=g.current_user_id,
            )
        )
    except ConfigurationConflictError:
        return error(
            "CONFIG_VERSION_CONFLICT",
            "Configuration changed; reload and retry.",
            status=409,
        )
    except KeyError:
        return error("NOT_FOUND", "World not found.", status=404)
    override = (
        container.store.reader()
        .execute("SELECT version FROM world_settings WHERE world_id = ?", (world_id,))
        .fetchone()
    )
    return ok(
        {
            "settings": container.configuration.resolve_effective(world_id),
            "version": override["version"],
            "operation": operation,
        },
        meta={"op_id": operation["op_id"]},
    )
