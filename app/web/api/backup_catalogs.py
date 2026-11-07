"""Document 10 backup, restore, cleanup, and sync catalog routes."""

from __future__ import annotations

import json
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, current_app, g, request

from app.domain.tuning import CLEANUP_AGE_FLOOR_DAYS, CLEANUP_COUNT_FLOOR
from app.domain.value_objects import (
    ActorType,
    OperationStatus,
    OperationType,
    TriggerType,
)
from app.services.cleanup import RetentionError
from app.services.operations import OperationConflictError, OperationInput
from app.web.errors import error, ok

backup_catalogs_bp = Blueprint("api_backup_catalogs", __name__, url_prefix="/api")
_CLEANUP_SCOPES = frozenset({"backups", "stale_worlds", "logs"})
_TERMINAL_STATUSES = frozenset(
    {
        OperationStatus.COMPLETED.value,
        OperationStatus.FAILED.value,
        OperationStatus.CANCELLED.value,
        OperationStatus.TIMED_OUT.value,
    }
)


def _container() -> Any:
    return current_app.extensions["mcmanager_container"]


def _body() -> dict[str, Any] | None:
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else None


def _iso(value: Any) -> Any:
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")
    return value


def _serialize_row(row: Any) -> dict[str, Any]:
    value = dict(row)
    for key in (
        "created_at",
        "deleted_at",
        "started_at",
        "finished_at",
        "updated_at",
    ):
        if key in value:
            value[key] = _iso(value[key])
    if "suspect" in value:
        value["suspect"] = bool(value["suspect"])
    if "data_json" in value:
        try:
            value["data"] = json.loads(value["data_json"]) if value["data_json"] else None
        except (TypeError, json.JSONDecodeError):
            value["data"] = None
    return value


def _page(query: str, params: list[Any]) -> tuple[list[dict[str, Any]], dict[str, int]] | None:
    try:
        limit = int(request.args.get("limit", "50"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        return None
    if not 1 <= limit <= 500 or offset < 0:
        return None
    reader = _container().store.reader()
    total = reader.execute(f"SELECT count(*) FROM ({query}) AS catalog_rows", params).fetchone()[0]
    rows = reader.execute(f"{query} LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
    return [_serialize_row(row) for row in rows], {
        "limit": limit,
        "offset": offset,
        "total": int(total),
    }


def _world(world_id: str) -> dict[str, Any] | None:
    row = _container().store.reader().execute(
        "SELECT * FROM world_instances WHERE world_id = ? AND deleted_at IS NULL",
        (world_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _operation_response(operation: dict[str, Any], *, replayed: bool) -> Any:
    queue_position = None
    if operation.get("status") == OperationStatus.QUEUED.value and operation.get("world_id"):
        queue_position = _container().store.reader().execute(
            """
            SELECT COUNT(*) FROM operations
            WHERE world_id = ? AND status = ?
              AND (created_at < ? OR (created_at = ? AND op_id <= ?))
            """,
            (
                operation["world_id"],
                OperationStatus.QUEUED.value,
                operation["created_at"],
                operation["created_at"],
                operation["op_id"],
            ),
        ).fetchone()[0]
    payload = _serialize_row(operation)
    if payload.get("checkpoint"):
        with suppress(TypeError, json.JSONDecodeError):
            payload["checkpoint"] = json.loads(payload["checkpoint"])
    meta: dict[str, Any] = {
        "op_id": payload["op_id"],
        "idempotency_key": payload.get("idempotency_key"),
    }
    if queue_position is not None:
        meta["queue_position"] = queue_position
    return ok(
        {"operation": payload},
        status=200 if replayed or payload.get("status") in _TERMINAL_STATUSES else 202,
        meta=meta,
    )


def _enqueue(
    op_type: OperationType,
    world_id: str | None,
    data: dict[str, Any],
    *,
    compensates_operation_id: str | None = None,
) -> Any:
    key = request.headers.get("Idempotency-Key", "").strip() or uuid.uuid4().hex
    try:
        operation, replayed = _container().operations.create_with_replay(
            OperationInput(
                op_type=op_type,
                actor_type=ActorType.USER,
                actor_user_id=g.current_user_id,
                world_id=world_id,
                idempotency_key=key,
                data=data,
                compensates_operation_id=compensates_operation_id,
            ),
            initial_status=OperationStatus.QUEUED,
        )
    except OperationConflictError as exc:
        return error("OP_CONFLICT_IN_FLIGHT", str(exc), status=409)
    return _operation_response(operation, replayed=replayed)


def _valid_deleted_filter() -> bool | None:
    value = request.args.get("deleted", "false").lower()
    if value not in {"true", "false", "1", "0"}:
        return None
    return value in {"true", "1"}


def _artifact_query() -> str:
    return """
        SELECT b.*,
            (SELECT sr.status FROM sync_records sr
             WHERE sr.artifact_id = b.artifact_id
             ORDER BY sr.created_at DESC LIMIT 1) AS sync_status
        FROM backup_artifacts b
    """


def _retention_flags(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidate_ids = {
        candidate.artifact_id
        for candidate in _container().cleanup.backup_candidates(
            older_than_days=CLEANUP_AGE_FLOOR_DAYS,
            keep_per_category=CLEANUP_COUNT_FLOOR,
        )
    }
    for row in rows:
        row["retention_protected"] = (
            row.get("deleted_at") is None and row["artifact_id"] not in candidate_ids
        )
    return rows


@backup_catalogs_bp.get("/worlds/<world_id>/backups")
def list_world_backups(world_id: str) -> Any:
    if _world(world_id) is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    include_deleted = _valid_deleted_filter()
    if include_deleted is None:
        return error("VALIDATION_ERROR", "deleted must be true or false.")
    clauses = ["b.world_id = ?"]
    params: list[Any] = [world_id]
    category = request.args.get("category")
    if category is not None:
        if category not in {item.value for item in TriggerType}:
            return error("VALIDATION_ERROR", "Unknown backup category.")
        clauses.append("b.category = ?")
        params.append(category)
    if not include_deleted:
        clauses.append("b.deleted_at IS NULL")
    result = _page(
        _artifact_query() + " WHERE " + " AND ".join(clauses) + " ORDER BY b.created_at DESC",
        params,
    )
    if result is None:
        return error("VALIDATION_ERROR", "Invalid pagination values.")
    rows, pagination = result
    return ok({"backups": _retention_flags(rows)}, meta={"pagination": pagination})


@backup_catalogs_bp.post("/worlds/<world_id>/backups")
def create_world_backup(world_id: str) -> Any:
    if _world(world_id) is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    body = _body()
    if body is None or set(body).difference({"category"}) or body.get("category", "manual") != "manual":
        return error("VALIDATION_ERROR", "Only manual world backups can be requested here.")
    return _enqueue(
        OperationType.BACKUP,
        world_id,
        {"category": TriggerType.MANUAL.value},
    )


@backup_catalogs_bp.get("/backups")
def list_backups() -> Any:
    include_deleted = _valid_deleted_filter()
    if include_deleted is None:
        return error("VALIDATION_ERROR", "deleted must be true or false.")
    clauses: list[str] = []
    params: list[Any] = []
    world_id = request.args.get("world_id")
    if world_id is not None:
        clauses.append("b.world_id IS NULL" if world_id == "null" else "b.world_id = ?")
        if world_id != "null":
            params.append(world_id)
    category = request.args.get("category")
    if category is not None:
        clauses.append("b.category = ?")
        params.append(category)
    if not include_deleted:
        clauses.append("b.deleted_at IS NULL")
    query = _artifact_query()
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    result = _page(query + " ORDER BY b.created_at DESC", params)
    if result is None:
        return error("VALIDATION_ERROR", "Invalid pagination values.")
    rows, pagination = result
    return ok({"backups": _retention_flags(rows)}, meta={"pagination": pagination})


@backup_catalogs_bp.get("/backups/<artifact_id>")
def get_backup(artifact_id: str) -> Any:
    row = _container().store.reader().execute(
        _artifact_query() + " WHERE b.artifact_id = ?", (artifact_id,)
    ).fetchone()
    if row is None:
        return error("BACKUP_ARTIFACT_NOT_FOUND", "Backup artifact not found.")
    serialized = _serialize_row(row)
    return ok({"backup": _retention_flags([serialized])[0]})


@backup_catalogs_bp.delete("/backups/<artifact_id>")
def delete_backup(artifact_id: str) -> Any:
    force_value = request.args.get("force", "false").lower()
    if force_value not in {"true", "false", "1", "0"}:
        return error("VALIDATION_ERROR", "force must be true or false.")
    force = force_value in {"true", "1"}
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if idempotency_key:
        replay = _container().operations.get_by_idempotency_key(
            OperationType.CLEANUP, idempotency_key
        )
        if replay is not None:
            return _operation_response(replay, replayed=True)
    try:
        artifact = _container().cleanup.validate_backup_artifact_delete(
            artifact_id, force=force
        )
    except KeyError:
        return error("BACKUP_ARTIFACT_NOT_FOUND", "Backup artifact not found.")
    except RetentionError as exc:
        return error("BACKUP_RETENTION_GUARD", str(exc))
    return _enqueue(
        OperationType.CLEANUP,
        artifact["world_id"],
        {
            "action": "delete_artifact",
            "artifact_id": artifact_id,
            "force": force,
            "scope": f"artifact:{artifact_id}",
        },
    )


@backup_catalogs_bp.get("/worlds/<world_id>/restores")
def list_world_restores(world_id: str) -> Any:
    if _world(world_id) is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    result = _page(
        "SELECT * FROM restore_history WHERE world_id = ? ORDER BY created_at DESC",
        [world_id],
    )
    if result is None:
        return error("VALIDATION_ERROR", "Invalid pagination values.")
    rows, pagination = result
    return ok({"restores": rows}, meta={"pagination": pagination})


def _restore_precondition(world_id: str) -> Any | None:
    world = _world(world_id)
    if world is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    if world["state"] != "off":
        return error("WORLD_NOT_OFF", "World must be off to restore.")
    conflict = _container().store.reader().execute(
        """
        SELECT 1 FROM operations
        WHERE world_id = ? AND op_type IN (?, ?, ?) AND status IN (?, ?, ?, ?)
        LIMIT 1
        """,
        (
            world_id,
            OperationType.BACKUP.value,
            OperationType.RESTORE.value,
            OperationType.CLEANUP.value,
            OperationStatus.CREATED.value,
            OperationStatus.QUEUED.value,
            OperationStatus.VALIDATING.value,
            OperationStatus.RUNNING.value,
        ),
    ).fetchone()
    if conflict is not None:
        return error("OP_CONFLICT_IN_FLIGHT", "World has an in-flight operation.", status=409)
    return None


def _resolve_restore_artifact(world_id: str, body: dict[str, Any]) -> str | Any:
    if set(body) == {"artifact_id"} and isinstance(body["artifact_id"], str):
        artifact_id = body["artifact_id"]
        row = _container().store.reader().execute(
            "SELECT artifact_id FROM backup_artifacts "
            "WHERE artifact_id = ? AND world_id = ? AND deleted_at IS NULL",
            (artifact_id, world_id),
        ).fetchone()
    elif set(body) == {"source_path"} and isinstance(body["source_path"], str):
        row = _container().store.reader().execute(
            "SELECT artifact_id FROM backup_artifacts "
            "WHERE storage_path = ? AND world_id = ? AND deleted_at IS NULL",
            (body["source_path"], world_id),
        ).fetchone()
        artifact_id = str(row["artifact_id"]) if row is not None else ""
    else:
        return error("VALIDATION_ERROR", "artifact_id or source_path is required.")
    if row is None:
        return error("BACKUP_ARTIFACT_NOT_FOUND", "Backup artifact not found.")
    return artifact_id


@backup_catalogs_bp.post("/worlds/<world_id>/restores")
def create_restore(world_id: str) -> Any:
    precondition = _restore_precondition(world_id)
    if precondition is not None:
        return precondition
    body = _body()
    if body is None:
        return error("VALIDATION_ERROR", "A JSON object is required.")
    artifact_id = _resolve_restore_artifact(world_id, body)
    if not isinstance(artifact_id, str):
        return artifact_id
    return _enqueue(OperationType.RESTORE, world_id, {"artifact_id": artifact_id})


@backup_catalogs_bp.post("/worlds/<world_id>/restores/rollback")
def rollback_restore(world_id: str) -> Any:
    precondition = _restore_precondition(world_id)
    if precondition is not None:
        return precondition
    body = _body()
    if body is None or len(body) != 1:
        return error("VALIDATION_ERROR", "restore_id is required.")
    if "restore_id" in body and isinstance(body["restore_id"], str):
        history = _container().store.reader().execute(
            "SELECT restore_id, operation_id, pre_restore_artifact_id "
            "FROM restore_history WHERE restore_id = ? AND world_id = ?",
            (body["restore_id"], world_id),
        ).fetchone()
    elif "pre_restore_artifact_id" in body and isinstance(body["pre_restore_artifact_id"], str):
        history = _container().store.reader().execute(
            "SELECT restore_id, operation_id, pre_restore_artifact_id "
            "FROM restore_history WHERE pre_restore_artifact_id = ? AND world_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (body["pre_restore_artifact_id"], world_id),
        ).fetchone()
    else:
        return error("VALIDATION_ERROR", "restore_id is required.")
    if history is None:
        return error("RESTORE_ARTIFACT_INVALID", "Restore history was not found.")
    artifact = _container().store.reader().execute(
        "SELECT 1 FROM backup_artifacts WHERE artifact_id = ? AND deleted_at IS NULL",
        (history["pre_restore_artifact_id"],),
    ).fetchone()
    if artifact is None:
        return error("BACKUP_ARTIFACT_NOT_FOUND", "Pre-restore artifact not found.")
    return _enqueue(
        OperationType.RESTORE,
        world_id,
        {
            "artifact_id": history["pre_restore_artifact_id"],
            "rollback_of_restore_id": history["restore_id"],
        },
        compensates_operation_id=history["operation_id"],
    )


def _cleanup_parameters(
    scope: Any, world_id: Any, policy_version: Any
) -> tuple[dict[str, Any] | None, Any | None]:
    if scope not in _CLEANUP_SCOPES:
        return None, error("VALIDATION_ERROR", "Unknown cleanup scope.")
    if scope != "backups":
        return None, error(
            "CLEANUP_SCOPE_UNSUPPORTED",
            "This cleanup service currently supports the backups scope only.",
        )
    if world_id is not None and (not isinstance(world_id, str) or _world(world_id) is None):
        return None, error("WORLD_NOT_FOUND", "World not found.")

    reader = _container().store.reader()
    policy = None
    if world_id is not None:
        policy = reader.execute(
            "SELECT * FROM cleanup_policies WHERE scope = 'world' AND world_id = ? "
            "AND deleted_at IS NULL ORDER BY version DESC LIMIT 1",
            (world_id,),
        ).fetchone()
    if policy is None:
        policy = reader.execute(
            "SELECT * FROM cleanup_policies WHERE scope = 'global' AND world_id IS NULL "
            "AND deleted_at IS NULL ORDER BY version DESC LIMIT 1"
        ).fetchone()
    if policy_version is not None:
        if type(policy_version) is not int or policy_version < 1:
            return None, error("VALIDATION_ERROR", "policy_version must be a positive integer.")
        if policy is None or policy["version"] != policy_version:
            return None, error("CONFIG_VERSION_CONFLICT", "Cleanup policy changed; reload and retry.")
    older_than_days = max(
        CLEANUP_AGE_FLOOR_DAYS,
        int(policy["age_rule_days"]) if policy is not None else CLEANUP_AGE_FLOOR_DAYS,
    )
    keep_per_category = CLEANUP_COUNT_FLOOR
    if policy is not None and policy["count_rules"]:
        try:
            count_rules = json.loads(policy["count_rules"])
            if isinstance(count_rules, dict):
                values = [value for value in count_rules.values() if type(value) is int]
                if values:
                    keep_per_category = max(keep_per_category, *values)
        except (TypeError, json.JSONDecodeError):
            pass
    return {
        "scope": scope,
        "world_id": world_id,
        "policy_version": policy["version"] if policy is not None else None,
        "older_than_days": older_than_days,
        "keep_per_category": keep_per_category,
    }, None


def _cleanup_preview(body: dict[str, Any]) -> Any:
    allowed = {"scope", "world_id", "policy_version"}
    if set(body).difference(allowed) or "scope" not in body:
        return error("VALIDATION_ERROR", "scope and optional world_id/policy_version are required.")
    parameters, failure = _cleanup_parameters(
        body.get("scope"), body.get("world_id"), body.get("policy_version")
    )
    if failure is not None:
        return failure
    return _enqueue(OperationType.CLEANUP, parameters["world_id"], {**parameters, "wet": False})


@backup_catalogs_bp.post("/cleanup/dry-run")
def cleanup_dry_run() -> Any:
    body = _body()
    if body is None:
        return error("VALIDATION_ERROR", "A JSON object is required.")
    return _cleanup_preview(body)


@backup_catalogs_bp.post("/cleanup/execute")
def cleanup_execute() -> Any:
    body = _body()
    allowed = {
        "scope",
        "world_id",
        "policy_version",
        "dry_run_operation_id",
        "elevated_confirmation",
    }
    if (
        body is None
        or set(body).difference(allowed)
        or not isinstance(body.get("dry_run_operation_id"), str)
        or type(body.get("elevated_confirmation", False)) is not bool
    ):
        return error("VALIDATION_ERROR", "A scope and completed dry-run operation are required.")
    parameters, failure = _cleanup_parameters(
        body.get("scope"), body.get("world_id"), body.get("policy_version")
    )
    if failure is not None:
        return failure
    preview = _container().operations.get(body["dry_run_operation_id"])
    try:
        preview_data = json.loads(preview.get("data_json") or "{}") if preview else {}
    except (TypeError, json.JSONDecodeError):
        preview_data = {}
    if (
        preview is None
        or preview["op_type"] != OperationType.CLEANUP.value
        or preview["status"] != OperationStatus.COMPLETED.value
        or preview_data.get("scope") != parameters["scope"]
        or preview_data.get("world_id") != parameters["world_id"]
    ):
        return error("CLEANUP_PREVIEW_REQUIRED", "A matching completed cleanup preview is required.")
    return _enqueue(
        OperationType.CLEANUP,
        parameters["world_id"],
        {
            **parameters,
            "wet": True,
            "dry_run_operation_id": body["dry_run_operation_id"],
            "elevated_confirmation": body.get("elevated_confirmation", False),
        },
    )


@backup_catalogs_bp.get("/cleanup/runs")
def list_cleanup_runs() -> Any:
    result = _page(
        "SELECT * FROM operations WHERE op_type = ? ORDER BY created_at DESC",
        [OperationType.CLEANUP.value],
    )
    if result is None:
        return error("VALIDATION_ERROR", "Invalid pagination values.")
    rows, pagination = result
    return ok({"cleanup_runs": rows}, meta={"pagination": pagination})


@backup_catalogs_bp.get("/worlds/<world_id>/cleanup-preview")
def world_cleanup_preview(world_id: str) -> Any:
    if _world(world_id) is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    body = {
        "scope": request.args.get("scope", "backups"),
        "world_id": world_id,
    }
    policy_version = request.args.get("policy_version")
    if policy_version is not None:
        try:
            body["policy_version"] = int(policy_version)
        except ValueError:
            return error("VALIDATION_ERROR", "policy_version must be an integer.")
    return _cleanup_preview(body)


def _sync_target(world_id: str | None) -> str | None:
    return _container().catalog_operations.resolve_sync_target(world_id)


@backup_catalogs_bp.get("/sync/records")
def list_sync_records() -> Any:
    clauses: list[str] = []
    params: list[Any] = []
    for key, column in (("status", "sr.status"), ("world_id", "b.world_id"), ("artifact_id", "sr.artifact_id")):
        value = request.args.get(key)
        if value is not None:
            if key == "status" and value not in {"pending", "succeeded", "failed"}:
                return error("VALIDATION_ERROR", "Unknown sync status.")
            clauses.append(f"{column} = ?")
            params.append(value)
    query = """
        SELECT sr.*, b.world_id FROM sync_records sr
        JOIN backup_artifacts b ON b.artifact_id = sr.artifact_id
    """
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    result = _page(query + " ORDER BY sr.created_at DESC", params)
    if result is None:
        return error("VALIDATION_ERROR", "Invalid pagination values.")
    rows, pagination = result
    return ok({"sync_records": rows}, meta={"pagination": pagination})


@backup_catalogs_bp.get("/backups/<artifact_id>/sync")
def get_backup_sync(artifact_id: str) -> Any:
    artifact = _container().store.reader().execute(
        "SELECT artifact_id FROM backup_artifacts WHERE artifact_id = ?", (artifact_id,)
    ).fetchone()
    if artifact is None:
        return error("BACKUP_ARTIFACT_NOT_FOUND", "Backup artifact not found.")
    row = _container().store.reader().execute(
        "SELECT * FROM sync_records WHERE artifact_id = ? ORDER BY created_at DESC LIMIT 1",
        (artifact_id,),
    ).fetchone()
    if row is None:
        return ok({"sync": None, "attempts": []})
    attempts = _container().store.reader().execute(
        "SELECT * FROM sync_attempts WHERE sync_id = ? ORDER BY attempt_number",
        (row["sync_id"],),
    ).fetchall()
    return ok(
        {
            "sync": _serialize_row(row),
            "attempts": [_serialize_row(attempt) for attempt in attempts],
        }
    )


@backup_catalogs_bp.post("/sync/retry")
def retry_sync() -> Any:
    body = _body()
    if body is None or set(body) != {"artifact_id"} or not isinstance(body["artifact_id"], str):
        return error("VALIDATION_ERROR", "artifact_id is required.")
    artifact = _container().store.reader().execute(
        "SELECT artifact_id, world_id FROM backup_artifacts "
        "WHERE artifact_id = ? AND deleted_at IS NULL",
        (body["artifact_id"],),
    ).fetchone()
    if artifact is None:
        return error("BACKUP_ARTIFACT_NOT_FOUND", "Backup artifact not found.")
    target_id = _sync_target(artifact["world_id"])
    if target_id is None:
        return error("SYNC_TARGET_UNRESOLVED", "No enabled sync target is configured.")
    return _enqueue(
        OperationType.SYNC,
        artifact["world_id"],
        {"artifact_id": body["artifact_id"], "sync_target_id": target_id},
    )


@backup_catalogs_bp.get("/sync/targets")
def list_sync_targets() -> Any:
    world_id = request.args.get("world_id")
    if world_id is not None and _world(world_id) is None:
        return error("WORLD_NOT_FOUND", "World not found.")
    effective_target = _sync_target(world_id)
    query = "SELECT * FROM sync_targets WHERE deleted_at IS NULL"
    params: list[Any] = []
    if world_id is not None:
        query += " AND (scope = 'global' OR (scope = 'world' AND world_id = ?))"
        params.append(world_id)
    rows = _container().store.reader().execute(
        query + " ORDER BY scope, created_at DESC", params
    ).fetchall()
    targets = []
    for row in rows:
        target = _serialize_row(row)
        try:
            target["config"] = json.loads(target["config"])
        except (TypeError, json.JSONDecodeError):
            target["config"] = None
        target["enabled"] = bool(target["enabled"])
        target["effective"] = target["sync_target_id"] == effective_target
        target["resolution"] = "world_override" if target["scope"] == "world" else "global_default"
        targets.append(target)
    return ok({"sync_targets": targets})
