"""Administrative schedules, templates, and Java runtime catalogs."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, current_app, g, request

from app.domain.value_objects import ActorType, ConfigEditEntity, OperationStatus, OperationType
from app.infrastructure.minecraft.java_compatibility import detect_java
from app.services.configuration import ConfigurationConflictError, VersionedUpdate
from app.services.operations import OperationInput
from app.web.errors import error, ok

catalogs_bp = Blueprint("api_catalogs", __name__, url_prefix="/api")
_SCHEDULE_TYPES = frozenset({"backup", "cleanup", "maintenance"})
_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_RUNTIME_FIELDS = frozenset({"label", "executable_path", "status"})


def _container():
    return current_app.extensions["mcmanager_container"]


def _body() -> dict[str, Any] | None:
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else None


def _iso(value: Any) -> Any:
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")
    return value


def _page(query: str, params: list[Any]) -> tuple[list[dict[str, Any]], dict[str, int]] | None:
    try:
        limit = int(request.args.get("limit", "50"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        return None
    if not 1 <= limit <= 500 or offset < 0:
        return None
    container = _container()
    total = (
        container.store.reader()
        .execute(f"SELECT count(*) FROM ({query}) AS catalog_rows", params)
        .fetchone()[0]
    )
    rows = (
        container.store.reader()
        .execute(f"{query} LIMIT ? OFFSET ?", [*params, limit, offset])
        .fetchall()
    )
    return [dict(row) for row in rows], {
        "limit": limit,
        "offset": offset,
        "total": total,
    }


def _config_update(entity: ConfigEditEntity, row_id: str, version: int, fields: dict[str, Any]):
    try:
        updated, operation = _container().configuration.update_versioned_with_operation(
            VersionedUpdate(
                entity=entity,
                row_id=row_id,
                expected_version=version,
                fields=fields,
                actor_type=ActorType.USER,
                actor_user_id=g.current_user_id,
            )
        )
    except ConfigurationConflictError:
        return None, error(
            "CONFIG_VERSION_CONFLICT",
            "Configuration changed; reload and retry.",
            status=409,
        )
    except KeyError:
        return None, error("NOT_FOUND", "Catalog entry not found.", status=404)
    except ValueError as exc:
        return None, error("VALIDATION_ERROR", str(exc), status=400)
    return (updated, operation), None


def _start_config_operation(
    entity: ConfigEditEntity, row_id: str, fields: dict[str, Any], world_id: str | None = None
) -> dict[str, Any]:
    operations = _container().operations
    operation = operations.create(
        OperationInput(
            op_type=OperationType.CONFIG_EDIT,
            actor_type=ActorType.USER,
            actor_user_id=g.current_user_id,
            world_id=world_id,
            data={"entity": entity.value, "row_id": row_id, "before": {}, "after": fields},
        ),
        initial_status=OperationStatus.QUEUED,
        allow_world_conflict=True,
    )
    return operations.transition(operation["op_id"], OperationStatus.RUNNING)


def _finish_config_operation(
    operation: dict[str, Any], entity: ConfigEditEntity, row_id: str
) -> dict[str, Any]:
    return _container().operations.transition(
        operation["op_id"],
        OperationStatus.COMPLETED,
        data={"entity": entity.value, "row_id": row_id},
    )


def _serialize_schedule(row: dict[str, Any]) -> dict[str, Any]:
    row["interval_spec"] = json.loads(row["interval_spec"])
    row["enabled"] = bool(row["enabled"])
    for key in ("last_changed_at", "created_at"):
        row[key] = _iso(row[key])
    return row


@catalogs_bp.get("/schedules")
def list_schedules():
    clauses = ["deleted_at IS NULL"]
    params: list[Any] = []
    for key, column in (
        ("scope", "scope"),
        ("world_id", "world_id"),
        ("schedule_type", "schedule_type"),
    ):
        value = request.args.get(key)
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    if request.args.get("enabled") is not None:
        enabled = request.args.get("enabled", "").lower()
        if enabled not in {"true", "false", "1", "0"}:
            return error("VALIDATION_ERROR", "enabled must be true or false.")
        clauses.append("enabled = ?")
        params.append(int(enabled in {"true", "1"}))
    result = _page(
        "SELECT * FROM schedules WHERE " + " AND ".join(clauses) + " ORDER BY created_at DESC",
        params,
    )
    if result is None:
        return error("VALIDATION_ERROR", "Invalid pagination values.")
    rows, pagination = result
    return ok(
        {"schedules": [_serialize_schedule(row) for row in rows]}, meta={"pagination": pagination}
    )


@catalogs_bp.post("/schedules")
def create_schedule():
    body = _body()
    if body is None:
        return error("VALIDATION_ERROR", "A JSON object is required.")
    scope = body.get("scope")
    world_id = body.get("world_id")
    schedule_type = body.get("schedule_type")
    interval_spec = body.get("interval_spec")
    time_of_day = body.get("time_of_day")
    enabled = body.get("enabled", True)
    if (
        scope not in {"global", "world"}
        or (scope == "global" and world_id is not None)
        or (scope == "world" and not isinstance(world_id, str))
        or schedule_type not in _SCHEDULE_TYPES
        or not isinstance(interval_spec, dict)
        or interval_spec.get("kind", interval_spec.get("type"))
        not in {"daily", "weekly", "monthly", "every_n_days"}
        or not isinstance(time_of_day, str)
        or not _TIME_PATTERN.fullmatch(time_of_day)
        or type(enabled) is not bool
    ):
        return error("VALIDATION_ERROR", "Schedule fields are invalid.")
    container = _container()
    if (
        world_id is not None
        and container.store.reader()
        .execute(
            "SELECT 1 FROM world_instances WHERE world_id = ? AND deleted_at IS NULL",
            (world_id,),
        )
        .fetchone()
        is None
    ):
        return error("NOT_FOUND", "World not found.", status=404)
    now = int(container.clock.now())
    schedule_id = f"sch_{uuid.uuid4().hex[:16]}"
    config_operation = _start_config_operation(
        ConfigEditEntity.SCHEDULES,
        schedule_id,
        {
            "scope": scope,
            "world_id": world_id,
            "schedule_type": schedule_type,
            "interval_spec": interval_spec,
            "time_of_day": time_of_day,
            "enabled": enabled,
        },
        world_id,
    )
    try:
        writer = container.store.writer()
        writer.execute(
            "INSERT INTO schedules (schedule_id, scope, world_id, schedule_type, "
            "interval_spec, time_of_day, enabled, version, last_changed_by, "
            "last_changed_at, deleted_at, deleted_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL, NULL, ?)",
            (
                schedule_id,
                scope,
                world_id,
                schedule_type,
                json.dumps(interval_spec, separators=(",", ":")),
                time_of_day,
                int(enabled),
                g.current_user_id,
                now,
                now,
            ),
        )
        writer.commit()
    except Exception as exc:
        container.operations.transition(
            config_operation["op_id"],
            OperationStatus.FAILED,
            error_code="CONFIG_EDIT_FAILED",
            message=str(exc),
        )
        return error("VALIDATION_ERROR", str(exc), status=400)
    config_operation = _finish_config_operation(
        config_operation, ConfigEditEntity.SCHEDULES, schedule_id
    )
    row = dict(
        container.store.reader()
        .execute("SELECT * FROM schedules WHERE schedule_id = ?", (schedule_id,))
        .fetchone()
    )
    return ok(
        {"schedule": _serialize_schedule(row), "operation": config_operation},
        status=201,
        meta={"op_id": config_operation["op_id"]},
    )


@catalogs_bp.patch("/schedules/<schedule_id>")
def update_schedule(schedule_id: str):
    body = _body()
    allowed = {"scope", "world_id", "schedule_type", "interval_spec", "time_of_day", "enabled"}
    if (
        body is None
        or type(body.get("version")) is not int
        or body["version"] < 1
        or not set(body).difference({"version"})
        or set(body).difference({"version", *allowed})
    ):
        return error("VALIDATION_ERROR", "A version and editable schedule fields are required.")
    fields = {key: value for key, value in body.items() if key != "version"}
    existing = (
        _container()
        .store.reader()
        .execute(
            "SELECT scope, world_id FROM schedules WHERE schedule_id = ? AND deleted_at IS NULL",
            (schedule_id,),
        )
        .fetchone()
    )
    if existing is None:
        return error("NOT_FOUND", "Schedule not found.", status=404)
    merged_scope = fields.get("scope", existing["scope"])
    merged_world = fields.get("world_id", existing["world_id"])
    if (
        merged_scope not in {"global", "world"}
        or (merged_scope == "global" and merged_world is not None)
        or (merged_scope == "world" and not isinstance(merged_world, str))
    ):
        return error("VALIDATION_ERROR", "Schedule scope and world_id are inconsistent.")
    if (
        "world_id" in fields
        and fields["world_id"] is not None
        and _container()
        .store.reader()
        .execute(
            "SELECT 1 FROM world_instances WHERE world_id = ? AND deleted_at IS NULL",
            (fields["world_id"],),
        )
        .fetchone()
        is None
    ):
        return error("NOT_FOUND", "World not found.", status=404)
    if "interval_spec" in fields:
        if not isinstance(fields["interval_spec"], dict):
            return error("VALIDATION_ERROR", "interval_spec must be an object.")
        if fields["interval_spec"].get("kind", fields["interval_spec"].get("type")) not in {
            "daily",
            "weekly",
            "monthly",
            "every_n_days",
        }:
            return error("VALIDATION_ERROR", "interval_spec kind is invalid.")
        fields["interval_spec"] = json.dumps(fields["interval_spec"], separators=(",", ":"))
    if "scope" in fields and fields["scope"] not in {"global", "world"}:
        return error("VALIDATION_ERROR", "scope is invalid.")
    if "time_of_day" in fields and (
        not isinstance(fields["time_of_day"], str)
        or not _TIME_PATTERN.fullmatch(fields["time_of_day"])
    ):
        return error("VALIDATION_ERROR", "time_of_day must use HH:MM.")
    if "schedule_type" in fields and fields["schedule_type"] not in _SCHEDULE_TYPES:
        return error("VALIDATION_ERROR", "schedule_type is invalid.")
    if "enabled" in fields and type(fields["enabled"]) is not bool:
        return error("VALIDATION_ERROR", "enabled must be a boolean.")
    if "enabled" in fields:
        fields["enabled"] = int(fields["enabled"])
    if "last_changed_by" not in fields:
        fields["last_changed_by"] = g.current_user_id
    if "last_changed_at" not in fields:
        fields["last_changed_at"] = int(_container().clock.now())
    result, failure = _config_update(
        ConfigEditEntity.SCHEDULES, schedule_id, body["version"], fields
    )
    if failure:
        return failure
    updated, operation = result
    return ok(
        {"schedule": _serialize_schedule(updated), "operation": operation},
        meta={"op_id": operation["op_id"]},
    )


@catalogs_bp.delete("/schedules/<schedule_id>")
def delete_schedule(schedule_id: str):
    container = _container()
    row = (
        container.store.reader()
        .execute(
            "SELECT version FROM schedules WHERE schedule_id = ? AND deleted_at IS NULL",
            (schedule_id,),
        )
        .fetchone()
    )
    if row is None:
        return error("NOT_FOUND", "Schedule not found.", status=404)
    result, failure = _config_update(
        ConfigEditEntity.SCHEDULES,
        schedule_id,
        row["version"],
        {
            "enabled": 0,
            "deleted_at": int(container.clock.now()),
            "deleted_by": g.current_user_id,
            "last_changed_by": g.current_user_id,
        },
    )
    if failure:
        return failure
    _, operation = result
    return ok({"deleted": True, "operation": operation}, meta={"op_id": operation["op_id"]})


@catalogs_bp.get("/missed-runs")
def list_missed_runs():
    resolution = request.args.get("resolution")
    if resolution is not None and resolution not in {"pending", "resolved", "ignored"}:
        return error("VALIDATION_ERROR", "resolution must be pending, resolved, or ignored.")
    clauses, params = [], []
    if resolution:
        clauses.append("resolution = ?")
        params.append(resolution)
    query = "SELECT * FROM missed_run_records"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY detected_at DESC"
    result = _page(query, params)
    if result is None:
        return error("VALIDATION_ERROR", "Invalid pagination values.")
    rows, pagination = result
    for row in rows:
        for key in ("expected_run_at", "detected_at", "resolution_at", "created_at"):
            row[key] = _iso(row[key])
    return ok({"missed_runs": rows}, meta={"pagination": pagination})


@catalogs_bp.patch("/missed-runs/<missed_run_id>")
def resolve_missed_run(missed_run_id: str):
    body = _body()
    resolution = body.get("resolution") if body else None
    if resolution not in {"resolved", "ignored"}:
        return error("VALIDATION_ERROR", "resolution must be resolved or ignored.")
    container = _container()
    writer = container.store.writer()
    writer.execute(
        "UPDATE missed_run_records SET resolution = ?, resolution_at = ?, resolution_by = ? "
        "WHERE missed_run_id = ? AND resolution = 'pending'",
        (resolution, int(container.clock.now()), g.current_user_id, missed_run_id),
    )
    changed = writer.execute("SELECT changes()").fetchone()[0]
    writer.commit()
    if changed:
        return ok({"missed_run_id": missed_run_id, "resolution": resolution})
    existing = (
        container.store.reader()
        .execute(
            "SELECT resolution FROM missed_run_records WHERE missed_run_id = ?",
            (missed_run_id,),
        )
        .fetchone()
    )
    if existing is None:
        return error("NOT_FOUND", "Missed run not found.", status=404)
    return error("MISSED_RUN_RESOLVED", "Missed-run resolution is terminal.", status=409)


@catalogs_bp.get("/templates")
def list_templates():
    clauses, params = ["deleted_at IS NULL"], []
    category = request.args.get("category")
    deprecated = request.args.get("deprecated")
    if category is not None:
        clauses.append("category = ?")
        params.append(category)
    if deprecated is not None:
        if deprecated.lower() not in {"true", "false"}:
            return error("VALIDATION_ERROR", "deprecated must be true or false.")
        clauses.append("deprecated = ?")
        params.append(int(deprecated.lower() == "true"))
    else:
        clauses.append("deprecated = 0")
    result = _page(
        "SELECT * FROM templates WHERE " + " AND ".join(clauses) + " ORDER BY name",
        params,
    )
    if result is None:
        return error("VALIDATION_ERROR", "Invalid pagination values.")
    rows, pagination = result
    for row in rows:
        row["config_defaults"] = json.loads(row["config_defaults"])
        row["deprecated"] = bool(row["deprecated"])
        row["created_at"] = _iso(row["created_at"])
        row["updated_at"] = _iso(row["updated_at"])
    return ok({"templates": rows}, meta={"pagination": pagination})


@catalogs_bp.post("/templates")
def create_template():
    body = _body()
    if (
        body is None
        or any(
            not isinstance(body.get(key), str) or not body[key].strip()
            for key in ("name", "category", "default_version")
        )
        or not isinstance(body.get("config_defaults"), dict)
    ):
        return error("VALIDATION_ERROR", "Template fields are invalid.")
    config = body["config_defaults"]
    if not any(key in config for key in ("launch_command_template", "launch_command")):
        return error("VALIDATION_ERROR", "config_defaults must include a launch command template.")
    container = _container()
    now = int(container.clock.now())
    template_id = f"tpl_{uuid.uuid4().hex[:16]}"
    config_operation = _start_config_operation(
        ConfigEditEntity.TEMPLATES,
        template_id,
        {
            "name": body["name"].strip(),
            "category": body["category"].strip(),
            "default_version": body["default_version"].strip(),
            "config_defaults": config,
        },
    )
    try:
        writer = container.store.writer()
        writer.execute(
            "INSERT INTO templates (template_id, name, category, default_version, "
            "config_defaults, source, deprecated, version, deleted_at, deleted_by, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'imported', 0, 1, NULL, NULL, ?, ?)",
            (
                template_id,
                body["name"].strip(),
                body["category"].strip(),
                body["default_version"].strip(),
                json.dumps(config, separators=(",", ":")),
                now,
                now,
            ),
        )
        writer.commit()
    except Exception as exc:
        container.operations.transition(
            config_operation["op_id"],
            OperationStatus.FAILED,
            error_code="CONFIG_EDIT_FAILED",
            message=str(exc),
        )
        return error("VALIDATION_ERROR", str(exc), status=400)
    config_operation = _finish_config_operation(
        config_operation, ConfigEditEntity.TEMPLATES, template_id
    )
    return ok(
        {
            "template_id": template_id,
            **body,
            "version": 1,
            "operation": config_operation,
        },
        status=201,
        meta={"op_id": config_operation["op_id"]},
    )


@catalogs_bp.patch("/templates/<template_id>")
def update_template(template_id: str):
    body = _body()
    allowed = {"name", "category", "default_version", "config_defaults"}
    if (
        body is None
        or type(body.get("version")) is not int
        or body["version"] < 1
        or not set(body).difference({"version"})
        or set(body).difference({"version", *allowed})
    ):
        return error("VALIDATION_ERROR", "A version and editable template fields are required.")
    fields = {key: value for key, value in body.items() if key != "version"}
    if any(
        not isinstance(value, str) or not value.strip()
        for key, value in fields.items()
        if key != "config_defaults"
    ):
        return error("VALIDATION_ERROR", "Template text fields must be non-empty strings.")
    if "config_defaults" in fields:
        config = fields["config_defaults"]
        if not isinstance(config, dict) or not any(
            key in config for key in ("launch_command_template", "launch_command")
        ):
            return error(
                "VALIDATION_ERROR", "config_defaults must include a launch command template."
            )
        fields["config_defaults"] = json.dumps(config, separators=(",", ":"))
    result, failure = _config_update(
        ConfigEditEntity.TEMPLATES, template_id, body["version"], fields
    )
    if failure:
        return failure
    updated, operation = result
    updated["config_defaults"] = json.loads(updated["config_defaults"])
    return ok({"template": updated, "operation": operation}, meta={"op_id": operation["op_id"]})


@catalogs_bp.delete("/templates/<template_id>")
def deprecate_template(template_id: str):
    container = _container()
    row = (
        container.store.reader()
        .execute(
            "SELECT version FROM templates WHERE template_id = ? AND deleted_at IS NULL",
            (template_id,),
        )
        .fetchone()
    )
    if row is None:
        return error("NOT_FOUND", "Template not found.", status=404)
    result, failure = _config_update(
        ConfigEditEntity.TEMPLATES,
        template_id,
        row["version"],
        {"deprecated": 1},
    )
    if failure:
        return failure
    _, operation = result
    return ok({"template_id": template_id, "deprecated": True, "operation": operation})


@catalogs_bp.get("/java-runtimes")
def list_java_runtimes():
    status = request.args.get("status")
    query = "SELECT * FROM java_runtimes WHERE deleted_at IS NULL"
    params: list[Any] = []
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY label"
    result = _page(query, params)
    if result is None:
        return error("VALIDATION_ERROR", "Invalid pagination values.")
    rows, pagination = result
    for row in rows:
        row["created_at"] = _iso(row["created_at"])
        row["updated_at"] = _iso(row["updated_at"])
        row["version"] = row.get("version", 1)
    return ok({"java_runtimes": rows}, meta={"pagination": pagination})


@catalogs_bp.post("/java-runtimes")
def register_java_runtime():
    body = _body()
    if body is None or any(
        not isinstance(body.get(key), str) or not body[key].strip() for key in ("label", "path")
    ):
        return error("VALIDATION_ERROR", "A label and executable path are required.")
    container = _container()
    now = int(container.clock.now())
    runtime_id = f"jrt_{uuid.uuid4().hex[:16]}"
    config_operation = _start_config_operation(
        ConfigEditEntity.JAVA_RUNTIMES,
        runtime_id,
        {
            "label": body["label"].strip(),
            "executable_path": body["path"].strip(),
        },
    )
    try:
        writer = container.store.writer()
        writer.execute(
            "INSERT INTO java_runtimes (runtime_id, label, executable_path, "
            "version_detected, status, version, deleted_at, deleted_by, created_at, updated_at) "
            "VALUES (?, ?, ?, NULL, 'registered', 1, NULL, NULL, ?, ?)",
            (runtime_id, body["label"].strip(), body["path"].strip(), now, now),
        )
        writer.commit()
    except Exception as exc:
        container.operations.transition(
            config_operation["op_id"],
            OperationStatus.FAILED,
            error_code="CONFIG_EDIT_FAILED",
            message=str(exc),
        )
        return error("VALIDATION_ERROR", str(exc), status=400)
    config_operation = _finish_config_operation(
        config_operation, ConfigEditEntity.JAVA_RUNTIMES, runtime_id
    )
    return ok(
        {
            "runtime": {
                "runtime_id": runtime_id,
                "label": body["label"].strip(),
                "executable_path": body["path"].strip(),
                "version_detected": None,
                "status": "registered",
                "version": 1,
                "operation": config_operation,
            }
        },
        status=201,
        meta={"op_id": config_operation["op_id"]},
    )


@catalogs_bp.post("/java-runtimes/<runtime_id>/verify")
def verify_java_runtime(runtime_id: str):
    container = _container()
    row = (
        container.store.reader()
        .execute(
            "SELECT * FROM java_runtimes WHERE runtime_id = ? AND deleted_at IS NULL",
            (runtime_id,),
        )
        .fetchone()
    )
    if row is None:
        return error("NOT_FOUND", "Java runtime not found.", status=404)
    config_operation = _start_config_operation(
        ConfigEditEntity.JAVA_RUNTIMES, runtime_id, {"status": "verified"}
    )
    detection = detect_java(row["executable_path"])
    writer = container.store.writer()
    if detection is None:
        writer.execute(
            "UPDATE java_runtimes SET status = 'missing', version = version + 1, updated_at = ? "
            "WHERE runtime_id = ?",
            (int(container.clock.now()), runtime_id),
        )
        writer.commit()
        container.operations.transition(
            config_operation["op_id"],
            OperationStatus.FAILED,
            error_code="CONFIG_INVALID_VALUE",
            message="Java executable could not be verified.",
        )
        return error("CONFIG_INVALID_VALUE", "Java executable could not be verified.", status=409)
    writer.execute(
        "UPDATE java_runtimes SET status = 'verified', version_detected = ?, "
        "version = version + 1, updated_at = ? WHERE runtime_id = ?",
        (detection.full_version, int(container.clock.now()), runtime_id),
    )
    writer.commit()
    config_operation = _finish_config_operation(
        config_operation, ConfigEditEntity.JAVA_RUNTIMES, runtime_id
    )
    return ok(
        {
            "runtime_id": runtime_id,
            "status": "verified",
            "version_detected": detection.full_version,
            "version": row["version"] + 1,
            "operation": config_operation,
        }
    )


@catalogs_bp.patch("/java-runtimes/<runtime_id>")
def update_java_runtime(runtime_id: str):
    body = _body()
    if (
        body is None
        or type(body.get("version")) is not int
        or body["version"] < 1
        or not set(body).difference({"version"})
        or set(body).difference({"version", *_RUNTIME_FIELDS})
        or any(
            not isinstance(body[key], str) or not body[key].strip()
            for key in set(body) - {"version"}
        )
    ):
        return error("VALIDATION_ERROR", "A version and valid runtime fields are required.")
    container = _container()
    row = (
        container.store.reader()
        .execute(
            "SELECT version FROM java_runtimes WHERE runtime_id = ? AND deleted_at IS NULL",
            (runtime_id,),
        )
        .fetchone()
    )
    if row is None:
        return error("NOT_FOUND", "Java runtime not found.", status=404)
    updates = {key: body[key].strip() for key in set(body) - {"version"}}
    if updates.get("status") not in {None, "registered", "verified", "missing"}:
        return error("VALIDATION_ERROR", "Java runtime status is invalid.")
    result, failure = _config_update(
        ConfigEditEntity.JAVA_RUNTIMES, runtime_id, body["version"], updates
    )
    if failure:
        return failure
    updated, operation = result
    updated["created_at"] = _iso(updated["created_at"])
    updated["updated_at"] = _iso(updated["updated_at"])
    return ok({"runtime": updated, "operation": operation}, meta={"op_id": operation["op_id"]})


@catalogs_bp.delete("/java-runtimes/<runtime_id>")
def deprecate_java_runtime(runtime_id: str):
    container = _container()
    row = (
        container.store.reader()
        .execute(
            "SELECT version FROM java_runtimes WHERE runtime_id = ? AND deleted_at IS NULL",
            (runtime_id,),
        )
        .fetchone()
    )
    if row is None:
        return error("NOT_FOUND", "Java runtime not found.", status=404)
    result, failure = _config_update(
        ConfigEditEntity.JAVA_RUNTIMES,
        runtime_id,
        row["version"],
        {"status": "deprecated"},
    )
    if failure:
        return failure
    _, operation = result
    return ok(
        {"runtime_id": runtime_id, "deprecated": True, "operation": operation},
        meta={"op_id": operation["op_id"]},
    )
