"""World metadata, runtime configuration, file, and log routes."""

from __future__ import annotations

import json
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from flask import Blueprint, current_app, g, request, send_file
from werkzeug.utils import secure_filename

from app.domain.value_objects import (
    ActorType,
    ConfigEditEntity,
    OperationStatus,
    OperationType,
    ServerType,
    WorldState,
)
from app.services.configuration import ConfigurationConflictError, VersionedUpdate
from app.web.errors import error, ok

world_management_bp = Blueprint("api_world_management", __name__, url_prefix="/api")

_LOG_CHANNELS = (
    "minecraft",
    "crash_reports",
    "backup_restore",
    "panel_activity",
    "panel_errors",
    "debug",
    "sync",
    "manager_action",
)
_PREVIEW_TTL_SECONDS = 300


def _container() -> Any:
    return current_app.extensions["mcmanager_container"]


def _world(world_id: str) -> dict[str, Any] | None:
    row = _container().store.reader().execute(
        "SELECT * FROM world_instances WHERE world_id = ? AND deleted_at IS NULL",
        (world_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _world_directory(world: dict[str, Any]) -> Path:
    if world["addressing_strategy"] == "path":
        candidate = Path(world["addressing_value"])
        if candidate.is_absolute():
            return candidate
    try:
        settings = _container().configuration.resolve_effective(world["world_id"])
    except KeyError:
        return Path("worlds") / str(world["display_name"])
    return Path(str(settings["minecraft_root_path"])) / str(world["display_name"])


def _log_directory(world_id: str) -> Path:
    try:
        settings = _container().configuration.resolve_effective(world_id)
        root = settings["log_root_path"] or "logs"
    except KeyError:
        root = "logs"
    return Path(str(root)) / world_id


def _resolve_under(root: Path, relative: str, *, allow_root: bool = True) -> Path | None:
    try:
        resolved_root = root.resolve()
        relative_path = Path(relative)
        if relative_path.is_absolute():
            return None
        current = resolved_root
        for component in relative_path.parts:
            if component in {"", "."}:
                continue
            current = current / component
            if current.is_symlink():
                return None
        candidate = (resolved_root / relative_path).resolve()
        candidate.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return None
    if not allow_root and candidate == resolved_root:
        return None
    return candidate


def _json_body() -> dict[str, Any] | None:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def _idempotency_key() -> str | None:
    value = request.headers.get("Idempotency-Key")
    if value is None:
        return uuid4().hex
    value = value.strip()
    return value or None


def _operation_response(operation: dict[str, Any], *, replayed: bool) -> Any:
    payload = dict(operation)
    if payload.get("data_json"):
        try:
            payload["data"] = json.loads(payload["data_json"])
        except (TypeError, json.JSONDecodeError):
            payload["data"] = None
    terminal = payload.get("status") in {
        OperationStatus.COMPLETED.value,
        OperationStatus.FAILED.value,
        OperationStatus.CANCELLED.value,
        OperationStatus.TIMED_OUT.value,
    }
    meta = {
        "op_id": payload["op_id"],
        "idempotency_key": payload.get("idempotency_key"),
    }
    if payload.get("status") == OperationStatus.QUEUED.value and payload.get("world_id"):
        meta["queue_position"] = _container().store.reader().execute(
            """
            SELECT COUNT(*) FROM operations
            WHERE world_id = ? AND status = ?
              AND (created_at < ? OR (created_at = ? AND op_id <= ?))
            """,
            (
                payload["world_id"],
                OperationStatus.QUEUED.value,
                payload["created_at"],
                payload["created_at"],
                payload["op_id"],
            ),
        ).fetchone()[0]
    return ok(
        {"operation": payload},
        status=200 if replayed or terminal else 202,
        meta=meta,
    )


def _existing_operation(op_type: OperationType, key: str) -> Any | None:
    operation = _container().operations.get_by_idempotency_key(op_type, key)
    return _operation_response(operation, replayed=True) if operation is not None else None


def _world_conflict(world_id: str) -> bool:
    row = _container().store.reader().execute(
        "SELECT state FROM world_instances WHERE world_id = ? AND deleted_at IS NULL",
        (world_id,),
    ).fetchone()
    if row is None:
        return True
    if row["state"] != WorldState.OFF.value:
        return True
    return bool(_container().operations.has_in_flight_operation(world_id))


def _preview_registry() -> dict[str, dict[str, Any]]:
    return cast(
        dict[str, dict[str, Any]],
        current_app.extensions.setdefault("mcmanager_world_delete_previews", {}),
    )


@world_management_bp.post("/worlds")
def create_world() -> Any:
    idempotency_key = _idempotency_key()
    if idempotency_key is None:
        return error("VALIDATION_ERROR", "Idempotency-Key must not be empty.")
    existing = _existing_operation(OperationType.CREATE_WORLD, idempotency_key)
    if existing is not None:
        return existing
    body = _json_body()
    required = {
        "template_id",
        "display_name",
        "port",
        "addressing_strategy",
        "addressing_value",
        "java_runtime_id",
    }
    if body is None or required.difference(body):
        return error("VALIDATION_ERROR", "Required world fields are missing.")
    if (
        not isinstance(body["display_name"], str)
        or not body["display_name"].strip()
        or len(body["display_name"]) > 120
        or not isinstance(body["template_id"], str)
        or not body["template_id"]
        or type(body["port"]) is not int
        or not 1 <= body["port"] <= 65535
        or body["addressing_strategy"] not in {"subdomain", "port", "path"}
        or not isinstance(body["addressing_value"], str)
        or not body["addressing_value"].strip()
        or not isinstance(body["java_runtime_id"], str)
        or (
            "launch_args" in body
            and (
                not isinstance(body["launch_args"], list)
                or not body["launch_args"]
                or not all(isinstance(arg, str) for arg in body["launch_args"])
            )
        )
    ):
        return error("VALIDATION_ERROR", "World fields are invalid.")

    container = _container()
    template = container.store.reader().execute(
        "SELECT template_id, category, default_version FROM templates "
        "WHERE template_id = ? AND deleted_at IS NULL AND deprecated = 0",
        (body["template_id"],),
    ).fetchone()
    runtime = container.store.reader().execute(
        "SELECT runtime_id FROM java_runtimes "
        "WHERE runtime_id = ? AND deleted_at IS NULL AND status IN ('registered', 'verified')",
        (body["java_runtime_id"],),
    ).fetchone()
    if template is None or runtime is None:
        return error("VALIDATION_ERROR", "A live template and Java runtime are required.")
    try:
        server_type = ServerType(template["category"]).value
    except ValueError:
        return error("VALIDATION_ERROR", "The template has an unsupported server type.")

    now = int(container.clock.now())
    world_id = f"w_{uuid4().hex}"
    launch_args = json.dumps(body.get("launch_args")) if "launch_args" in body else None
    duplicate = container.store.reader().execute(
        """
        SELECT 1 FROM world_instances
        WHERE deleted_at IS NULL AND (display_name = ? OR port = ?)
        LIMIT 1
        """,
        (body["display_name"].strip(), body["port"]),
    ).fetchone()
    if duplicate is not None:
        return error("WORLD_CONFLICT", "World name or port is already in use.", status=409)
    world = {
        "world_id": world_id,
        "display_name": body["display_name"].strip(),
        "template_id": template["template_id"],
        "server_type": server_type,
        "mc_version": template["default_version"],
        "java_runtime_id": runtime["runtime_id"],
        "port": body["port"],
        "addressing_strategy": body["addressing_strategy"],
        "addressing_value": body["addressing_value"].strip(),
        "state": WorldState.OFF.value,
        "pre_backup_state": None,
        "launch_args": launch_args,
        "metadata_version": 1,
        "deleted_at": None,
        "deleted_by": None,
        "created_at": now,
        "updated_at": now,
    }
    operation, replayed = container.worlds.enqueue_world_mutation(
        op_type=OperationType.CREATE_WORLD,
        world_id=None,
        actor_user_id=g.current_user_id,
        idempotency_key=idempotency_key,
        data={"world_action": "create", "world": world},
    )
    return _operation_response(operation, replayed=replayed)


@world_management_bp.patch("/worlds/<world_id>")
def update_world(world_id: str) -> Any:
    body = _json_body()
    if (
        body is None
        or set(body) != {"display_name", "version"}
        or not isinstance(body["display_name"], str)
        or not body["display_name"].strip()
        or len(body["display_name"]) > 120
        or type(body["version"]) is not int
        or body["version"] < 1
    ):
        return error("VALIDATION_ERROR", "A display name and metadata version are required.")
    if _world(world_id) is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    try:
        _container().configuration.update_versioned(
            VersionedUpdate(
                entity=ConfigEditEntity.WORLD_INSTANCES,
                row_id=world_id,
                expected_version=body["version"],
                fields={"display_name": body["display_name"].strip()},
                actor_type=ActorType.USER,
                actor_user_id=g.current_user_id,
            )
        )
    except ConfigurationConflictError:
        return error("CONFIG_VERSION_CONFLICT", "Configuration changed; reload and retry.")
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            return error("WORLD_NAME_CONFLICT", "World name is already in use.")
        raise
    return ok({"world": _container().worlds.world_summary(world_id)})


@world_management_bp.post("/worlds/<world_id>/delete-preview")
def world_delete_preview(world_id: str) -> Any:
    world = _world(world_id)
    if world is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    if _world_conflict(world_id):
        return error("WORLD_NOT_OFF", "World must be off with no in-flight operations.")
    previews = _preview_registry()
    now = time.monotonic()
    for existing_token in [
        key for key, value in previews.items() if value["expires_at"] < now
    ]:
        del previews[existing_token]
    token = secrets.token_urlsafe(32)
    previews[token] = {
        "world_id": world_id,
        "actor_user_id": g.current_user_id,
        "session_id_hash": g.current_session.session_id_hash,
        "version": world["metadata_version"],
        "expires_at": now + _PREVIEW_TTL_SECONDS,
    }
    directory = _world_directory(world)
    return ok(
        {
            "preview_token": token,
            "world_id": world_id,
            "display_name": world["display_name"],
            "state": world["state"],
            "metadata_version": world["metadata_version"],
            "world_directory": str(directory),
        }
    )


@world_management_bp.delete("/worlds/<world_id>")
def delete_world(world_id: str) -> Any:
    idempotency_key = _idempotency_key()
    if idempotency_key is None:
        return error("VALIDATION_ERROR", "Idempotency-Key must not be empty.")
    existing = _existing_operation(OperationType.DELETE_WORLD, idempotency_key)
    if existing is not None:
        return existing
    body = _json_body()
    token = body.get("preview_token") if body else None
    preview = _preview_registry().pop(token, None) if isinstance(token, str) else None
    world = _world(world_id)
    if (
        world is None
        or preview is None
        or preview["world_id"] != world_id
        or preview["actor_user_id"] != g.current_user_id
        or preview["session_id_hash"] != g.current_session.session_id_hash
        or preview["expires_at"] < time.monotonic()
        or preview["version"] != world["metadata_version"]
    ):
        return error("CLEANUP_PREVIEW_REQUIRED", "A fresh world deletion preview is required.")
    if _world_conflict(world_id):
        return error("WORLD_NOT_OFF", "World must be off with no in-flight operations.")
    operation, replayed = _container().worlds.enqueue_world_mutation(
        op_type=OperationType.DELETE_WORLD,
        world_id=world_id,
        actor_user_id=g.current_user_id,
        idempotency_key=idempotency_key,
        data={
            "world_action": "delete",
            "preview_version": preview["version"],
        },
    )
    return _operation_response(operation, replayed=replayed)


@world_management_bp.get("/worlds/<world_id>/runtime-config")
def get_runtime_config(world_id: str) -> Any:
    world = _world(world_id)
    if world is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    return ok(
        {
            "runtime_config": {
                "java_runtime_id": world["java_runtime_id"],
                "launch_args": json.loads(world["launch_args"])
                if world["launch_args"]
                else None,
                "port": world["port"],
                "addressing_strategy": world["addressing_strategy"],
                "addressing_value": world["addressing_value"],
            },
            "version": world["metadata_version"],
        }
    )


@world_management_bp.patch("/worlds/<world_id>/runtime-config")
def update_runtime_config(world_id: str) -> Any:
    idempotency_key = _idempotency_key()
    if idempotency_key is None:
        return error("VALIDATION_ERROR", "Idempotency-Key must not be empty.")
    existing = _existing_operation(OperationType.CONFIG_EDIT, idempotency_key)
    if existing is not None:
        return existing
    body = _json_body()
    allowed = {
        "java_runtime_id",
        "launch_args",
        "port",
        "addressing_strategy",
        "addressing_value",
        "version",
    }
    if (
        body is None
        or set(body).difference(allowed)
        or "version" not in body
        or type(body["version"]) is not int
        or body["version"] < 1
    ):
        return error("VALIDATION_ERROR", "A valid version and runtime fields are required.")
    world = _world(world_id)
    if world is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    if world["state"] != WorldState.OFF.value:
        return error("WORLD_RUNTIME_CONFIG_STATE", "Runtime configuration requires an off world.")
    if body["version"] != world["metadata_version"]:
        return error("CONFIG_VERSION_CONFLICT", "Configuration changed; reload and retry.")

    updates = {key: value for key, value in body.items() if key != "version"}
    if not updates:
        return error("VALIDATION_ERROR", "At least one runtime field is required.")
    if "java_runtime_id" in updates:
        runtime = _container().store.reader().execute(
            "SELECT 1 FROM java_runtimes WHERE runtime_id = ? AND deleted_at IS NULL "
            "AND status IN ('registered', 'verified')",
            (updates["java_runtime_id"],),
        ).fetchone()
        if not isinstance(updates["java_runtime_id"], str) or runtime is None:
            return error("VALIDATION_ERROR", "A live Java runtime is required.")
    if "launch_args" in updates:
        args = updates["launch_args"]
        if not isinstance(args, list) or not args or not all(isinstance(arg, str) for arg in args):
            return error("VALIDATION_ERROR", "launch_args must be a non-empty string list.")
        updates["launch_args"] = json.dumps(args)
    if "port" in updates and (type(updates["port"]) is not int or not 1 <= updates["port"] <= 65535):
        return error("VALIDATION_ERROR", "port must be between 1 and 65535.")
    if "addressing_strategy" in updates and updates["addressing_strategy"] not in {
        "subdomain", "port", "path"
    }:
        return error("VALIDATION_ERROR", "addressing_strategy is unsupported.")
    if "addressing_value" in updates and (
        not isinstance(updates["addressing_value"], str)
        or not updates["addressing_value"].strip()
    ):
        return error("VALIDATION_ERROR", "addressing_value must be a non-empty string.")
    if "port" in updates:
        duplicate_port = _container().store.reader().execute(
            "SELECT 1 FROM world_instances WHERE port = ? AND world_id <> ? "
            "AND deleted_at IS NULL LIMIT 1",
            (updates["port"], world_id),
        ).fetchone()
        if duplicate_port is not None:
            return error("WORLD_PORT_CONFLICT", "World port is already in use.")
    before = {key: world[key] for key in updates}
    operation, replayed = _container().worlds.enqueue_world_mutation(
        op_type=OperationType.CONFIG_EDIT,
        world_id=world_id,
        actor_user_id=g.current_user_id,
        idempotency_key=idempotency_key,
        data={
            "entity": ConfigEditEntity.WORLD_INSTANCES.value,
            "row_id": world_id,
            "before": before,
            "after": updates,
            "expected_version": body["version"],
            "queued_runtime_config": True,
        },
    )
    return _operation_response(operation, replayed=replayed)


@world_management_bp.get("/worlds/<world_id>/eula")
def get_world_eula(world_id: str) -> Any:
    world = _world(world_id)
    if world is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    state = _container().minecraft_adapter.detect_eula(str(_world_directory(world)))
    return ok({"eula": state.value, "world_state": world["state"]})


@world_management_bp.get("/worlds/<world_id>/files")
def list_world_files(world_id: str) -> Any:
    world = _world(world_id)
    if world is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    relative = request.args.get("path", "")
    include_hidden = request.args.get("include_hidden", "false")
    if include_hidden not in {"true", "false"}:
        return error("VALIDATION_ERROR", "include_hidden must be true or false.")
    root = _world_directory(world).resolve()
    directory = _resolve_under(root, relative)
    if directory is None:
        return error("FILE_PATH_UNAUTHORIZED", "Path escapes the world directory.")
    if not directory.exists():
        return error("FILE_NOT_FOUND", "Directory not found.")
    if not directory.is_dir():
        return error("FILE_INVALID", "Path is not a directory.")
    files = []
    try:
        for item in sorted(directory.iterdir(), key=lambda entry: entry.name.casefold()):
            if not (include_hidden == "true" or not item.name.startswith(".")):
                continue
            if item.is_symlink():
                continue
            resolved = item.resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            stat = item.stat()
            files.append(
                {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": stat.st_size if item.is_file() else None,
                    "mtime": int(stat.st_mtime),
                }
            )
    except OSError:
        return error("FILE_INVALID", "Directory cannot be read.")
    return ok({"path": relative, "files": files})


@world_management_bp.get("/worlds/<world_id>/files/download")
def download_world_file(world_id: str) -> Any:
    world = _world(world_id)
    if world is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    relative = request.args.get("path", "")
    target = _resolve_under(_world_directory(world), relative, allow_root=False)
    if target is None:
        return error("FILE_PATH_UNAUTHORIZED", "Path escapes the world directory.")
    if not target.is_file():
        return error("FILE_NOT_FOUND", "File not found.")
    return send_file(target, as_attachment=True, download_name=target.name)


@world_management_bp.post("/worlds/<world_id>/files")
def upload_world_file(world_id: str) -> Any:
    world = _world(world_id)
    if world is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    relative = request.form.get("path", "")
    uploaded = request.files.get("file")
    if not relative or uploaded is None or not uploaded.filename:
        return error("VALIDATION_ERROR", "A destination path and file are required.")
    content = uploaded.stream.read(64 * 1024 * 1024 + 1)
    if len(content) > 64 * 1024 * 1024:
        return error("FILE_TOO_LARGE", "File exceeds the upload limit.")
    target = _resolve_under(_world_directory(world), relative, allow_root=False)
    if target is None:
        return error("FILE_PATH_UNAUTHORIZED", "Path escapes the world directory.")
    if target.exists():
        return error("FILE_EXISTS", "Destination already exists.")
    if not target.parent.is_dir():
        return error("FILE_NOT_FOUND", "Destination directory not found.")
    target.write_bytes(content)
    return ok({"path": relative, "size": target.stat().st_size}, status=201)


@world_management_bp.post("/worlds/<world_id>/files/mkdir")
def create_world_directory(world_id: str) -> Any:
    world = _world(world_id)
    body = _json_body()
    if world is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    if (
        body is None
        or set(body) != {"path", "name"}
        or not isinstance(body["path"], str)
        or not isinstance(body["name"], str)
    ):
        return error("VALIDATION_ERROR", "A parent path and directory name are required.")
    name = secure_filename(body["name"])
    if not name or name != body["name"] or name in {".", ".."}:
        return error("VALIDATION_ERROR", "Directory name is invalid.")
    parent = _resolve_under(_world_directory(world), body["path"], allow_root=True)
    if parent is None:
        return error("FILE_PATH_UNAUTHORIZED", "Path escapes the world directory.")
    target = _resolve_under(_world_directory(world), str(Path(body["path"]) / name), allow_root=False)
    if target is None:
        return error("FILE_PATH_UNAUTHORIZED", "Path escapes the world directory.")
    if not parent.is_dir():
        return error("FILE_NOT_FOUND", "Parent directory not found.")
    try:
        target.mkdir()
    except FileExistsError:
        return error("FILE_EXISTS", "Destination already exists.")
    return ok({"path": str(Path(body["path"]) / name)}, status=201)


@world_management_bp.patch("/worlds/<world_id>/files")
def edit_world_file(world_id: str) -> Any:
    idempotency_key = _idempotency_key()
    if idempotency_key is None:
        return error("VALIDATION_ERROR", "Idempotency-Key must not be empty.")
    existing = _existing_operation(OperationType.CONFIG_EDIT, idempotency_key)
    if existing is not None:
        return existing
    world = _world(world_id)
    body = _json_body()
    if world is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    if (
        body is None
        or set(body) != {"action", "from", "to"}
        or not isinstance(body.get("action"), str)
        or body["action"] not in {"rename", "move", "copy"}
        or not isinstance(body["from"], str)
        or not isinstance(body["to"], str)
    ):
        return error("VALIDATION_ERROR", "A valid file action, source, and destination are required.")
    root = _world_directory(world)
    source = _resolve_under(root, body["from"], allow_root=False)
    target = _resolve_under(root, body["to"], allow_root=False)
    if source is None or target is None:
        return error("FILE_PATH_UNAUTHORIZED", "Path escapes the world directory.")
    if not source.exists():
        return error("FILE_NOT_FOUND", "Source not found.")
    if target.exists():
        return error("FILE_EXISTS", "Destination already exists.")
    if not target.parent.is_dir():
        return error("FILE_NOT_FOUND", "Destination directory not found.")
    if body["action"] == "copy" and (
        source.is_symlink()
        or (source.is_dir() and any(item.is_symlink() for item in source.rglob("*")))
    ):
        return error("FILE_PATH_UNAUTHORIZED", "Symbolic links cannot be copied.")
    before = {
        "source": {
            "is_directory": source.is_dir(),
            "size": source.stat().st_size if source.is_file() else None,
            "mtime": int(source.stat().st_mtime),
        },
        "destination": None,
    }
    operation, replayed = _container().worlds.enqueue_world_mutation(
        op_type=OperationType.CONFIG_EDIT,
        world_id=world_id,
        actor_user_id=g.current_user_id,
        idempotency_key=idempotency_key,
        data={
            "entity": "files",
            "row_id": body["from"],
            "before": before,
            "after": {
                "action": body["action"],
                "from": body["from"],
                "to": body["to"],
            },
            "queued_file_edit": True,
            "world_root": str(root.resolve()),
            "action": body["action"],
            "from": body["from"],
            "to": body["to"],
        },
    )
    return _operation_response(operation, replayed=replayed)


@world_management_bp.delete("/worlds/<world_id>/files")
def delete_world_file(world_id: str) -> Any:
    world = _world(world_id)
    body = _json_body()
    if world is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    if body is None or not isinstance(body.get("path"), str):
        return error("VALIDATION_ERROR", "A file path is required.")
    target = _resolve_under(_world_directory(world), body["path"], allow_root=False)
    if target is None:
        return error("FILE_PATH_UNAUTHORIZED", "Path escapes the world directory.")
    if not target.exists():
        return error("FILE_NOT_FOUND", "File not found.")
    actor = _container().audit.snapshot_for_user(
        user_id=g.current_user_id,
        device_id=None,
        device_name=None,
        ip=request.remote_addr,
    )
    _container().audit.write(
        event_type="world_file_deleted",
        actor=actor,
        world_id=world_id,
        payload={"path": body["path"]},
    )
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return ok({"path": body["path"], "deleted": True})


@world_management_bp.get("/worlds/<world_id>/logs")
def list_world_log_channels(world_id: str) -> Any:
    if _world(world_id) is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    return ok({"channels": list(_LOG_CHANNELS)})


def _channel_directory(world: dict[str, Any], channel: str) -> Path:
    if channel == "crash_reports":
        return _world_directory(world) / "crash-reports"
    root = _log_directory(world["world_id"])
    return root if channel == "minecraft" else root / channel


def _valid_channel(channel: str) -> bool:
    return channel in _LOG_CHANNELS


@world_management_bp.get("/worlds/<world_id>/logs/<channel>/tail")
def tail_world_log(world_id: str, channel: str) -> Any:
    world = _world(world_id)
    if world is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    if not _valid_channel(channel):
        return error("VALIDATION_ERROR", "Unsupported log channel.")
    offset_value = request.args.get("offset", "0")
    if not offset_value.isdigit():
        return error("VALIDATION_ERROR", "offset must be a non-negative integer.")
    offset = int(offset_value)
    directory = _channel_directory(world, channel)
    files = (
        sorted(
            (path for path in directory.iterdir() if path.is_file() and not path.is_symlink()),
            key=lambda path: path.stat().st_mtime,
        )
        if directory.is_dir()
        else []
    )
    if files:
        target = files[-1]
        try:
            with target.open("rb") as stream:
                stream.seek(min(offset, target.stat().st_size))
                content = stream.read()
        except OSError:
            return error("FILE_INVALID", "Log file cannot be read.")
        next_offset = min(offset, target.stat().st_size) + len(content)
        return ok(
            {
                "channel": channel,
                "file": target.name,
                "offset": offset,
                "next_offset": next_offset,
                "lines": content.decode("utf-8", errors="replace").splitlines(),
            }
        )
    if channel == "minecraft":
        buffered = _container().logs.buffered(world_id)
        lines = [line for line in buffered if line.get("line_no", 0) > offset]
        return ok({"channel": channel, "offset": offset, "lines": lines})
    return error("FILE_NOT_FOUND", "No historical log file was found.")


@world_management_bp.get("/worlds/<world_id>/logs/<channel>/<file>")
def download_world_log(world_id: str, channel: str, file: str) -> Any:
    world = _world(world_id)
    if world is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    if not _valid_channel(channel):
        return error("VALIDATION_ERROR", "Unsupported log channel.")
    target = _resolve_under(_channel_directory(world, channel), file, allow_root=False)
    if target is None:
        return error("FILE_PATH_UNAUTHORIZED", "Path escapes the log directory.")
    if not target.is_file():
        return error("FILE_NOT_FOUND", "Log file not found.")
    return send_file(target, as_attachment=True, download_name=target.name)


@world_management_bp.get("/worlds/<world_id>/logs/<channel>")
def list_world_log_files(world_id: str, channel: str) -> Any:
    world = _world(world_id)
    if world is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    if not _valid_channel(channel):
        return error("VALIDATION_ERROR", "Unsupported log channel.")
    directory = _channel_directory(world, channel).resolve()
    if not directory.is_dir():
        return ok({"channel": channel, "files": []})
    files = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
        if path.is_file() and not path.is_symlink():
            stat = path.stat()
            files.append({"name": path.name, "size": stat.st_size, "mtime": int(stat.st_mtime)})
    return ok({"channel": channel, "files": files})
