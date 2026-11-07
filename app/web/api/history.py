"""Per-user notification preferences and immutable audit-history reads."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, current_app, g, request

from app.web.errors import error, ok

history_bp = Blueprint("api_history", __name__, url_prefix="/api")
_SEVERITY_ORDER = (
    "CASE n.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END"
)
_AUDIT_SORTS = {
    "created_at": "created_at",
    "event_type": "event_type",
    "actor_user_id": "actor_user_id",
    "world_id": "world_id",
}


def _container():
    return current_app.extensions["mcmanager_container"]


def _page() -> tuple[int, int] | None:
    try:
        limit = int(request.args.get("limit", "50"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        return None
    if limit < 1 or limit > 500 or offset < 0:
        return None
    return limit, offset


def _iso(value: Any) -> Any:
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")
    return value


@history_bp.get("/notifications")
def list_notifications():
    severity = request.args.get("severity")
    if severity is not None and severity not in {"critical", "high", "normal", "informational"}:
        return error("VALIDATION_ERROR", "severity is invalid.")
    read_filter = request.args.get("read")
    if read_filter is not None and read_filter.lower() not in {"true", "false"}:
        return error("VALIDATION_ERROR", "read must be true or false.")
    world_id = request.args.get("world_id")
    page = _page()
    if page is None:
        return error("VALIDATION_ERROR", "Invalid pagination values.")
    limit, offset = page
    container = _container()
    clauses = ["(reads.dismissed_at IS NULL OR reads.notification_id IS NULL)"]
    params: list[Any] = [g.current_user_id]
    if severity:
        clauses.append("n.severity = ?")
        params.append(severity)
    if world_id is not None:
        clauses.append("n.related_world_id = ?")
        params.append(world_id)
    if read_filter is not None:
        clauses.append(
            "reads.read_at IS " + ("NOT " if read_filter.lower() == "true" else "") + "NULL"
        )
    where = " AND ".join(clauses)
    query = (
        "SELECT n.notification_id, n.category, n.severity, n.message, "
        "n.related_operation_id, n.related_world_id, n.requires_action, "
        "n.action_taken, n.created_at, reads.read_at, reads.dismissed_at "
        "FROM notifications n LEFT JOIN notification_reads reads "
        "ON reads.notification_id = n.notification_id AND reads.user_id = ? "
        f"WHERE {where} ORDER BY (reads.read_at IS NOT NULL), {_SEVERITY_ORDER}, n.created_at DESC"
    )
    rows = container.store.reader().execute(query, params).fetchall()
    total = len(rows)
    unread_count = (
        container.store.reader()
        .execute(
            "SELECT count(*) FROM notifications n LEFT JOIN notification_reads r "
            "ON r.notification_id = n.notification_id AND r.user_id = ? "
            "WHERE r.read_at IS NULL AND (r.dismissed_at IS NULL OR r.notification_id IS NULL)",
            (g.current_user_id,),
        )
        .fetchone()[0]
    )
    output = [dict(row) for row in rows[offset : offset + limit]]
    for row in output:
        row["requires_action"] = bool(row["requires_action"])
        for key in ("created_at", "read_at", "dismissed_at"):
            row[key] = _iso(row[key])
    return ok(
        {"notifications": output},
        meta={
            "unread_count": unread_count,
            "pagination": {"limit": limit, "offset": offset, "total": total},
        },
    )


def _notification_exists(notification_id: str) -> bool:
    return (
        _container()
        .store.reader()
        .execute("SELECT 1 FROM notifications WHERE notification_id = ?", (notification_id,))
        .fetchone()
        is not None
    )


@history_bp.post("/notifications/<notification_id>/read")
def read_notification(notification_id: str):
    if not _notification_exists(notification_id):
        return error("NOT_FOUND", "Notification not found.", status=404)
    _container().notifications.mark_read(notification_id, g.current_user_id)
    return ok({"notification_id": notification_id, "read": True}, status=201)


@history_bp.post("/notifications/<notification_id>/dismiss")
def dismiss_notification(notification_id: str):
    if not _notification_exists(notification_id):
        return error("NOT_FOUND", "Notification not found.", status=404)
    _container().notifications.dismiss(notification_id, g.current_user_id)
    return ok({"notification_id": notification_id, "dismissed": True}, status=201)


@history_bp.post("/notifications/read-all")
def read_all_notifications():
    container = _container()
    rows = container.store.reader().execute("SELECT notification_id FROM notifications").fetchall()
    for row in rows:
        container.notifications.mark_read(row["notification_id"], g.current_user_id)
    return ok({"read_count": len(rows)})


def _timestamp(value: str, *, end: bool = False) -> int | None:
    try:
        if value.isdigit():
            return int(value)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    except (ValueError, OverflowError):
        return None


@history_bp.get("/audit")
def list_audit():
    page = _page()
    if page is None:
        return error("VALIDATION_ERROR", "Invalid pagination values.")
    limit, offset = page
    clauses, params = [], []
    for key, column in (
        ("actor_user_id", "actor_user_id"),
        ("world_id", "world_id"),
        ("event_type", "event_type"),
    ):
        value = request.args.get(key)
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    for key, comparator in (("from", ">="), ("to", "<=")):
        value = request.args.get(key)
        if value is not None:
            timestamp = _timestamp(value)
            if timestamp is None:
                return error("VALIDATION_ERROR", f"{key} must be an epoch or ISO-8601 timestamp.")
            clauses.append(f"created_at {comparator} ?")
            params.append(timestamp)
    sort = request.args.get("sort", "-created_at")
    parts = []
    for value in sort.split(","):
        descending = value.startswith("-")
        field = value[1:] if descending else value
        if field not in _AUDIT_SORTS:
            return error("VALIDATION_ERROR", f"Unsupported audit sort field: {field}.")
        parts.append(_AUDIT_SORTS[field] + (" DESC" if descending else " ASC"))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    container = _container()
    total = (
        container.store.reader()
        .execute("SELECT count(*) FROM audit_records" + where, params)
        .fetchone()[0]
    )
    rows = (
        container.store.reader()
        .execute(
            "SELECT audit_id, event_type, actor_type, actor_user_id, "
            "actor_username_snapshot, world_id, operation_id, created_at "
            "FROM audit_records" + where + " ORDER BY " + ", ".join(parts) + " LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        .fetchall()
    )
    output = [dict(row) for row in rows]
    for row in output:
        row["created_at"] = _iso(row["created_at"])
    return ok(
        {"audit": output},
        meta={"pagination": {"limit": limit, "offset": offset, "total": total}},
    )


@history_bp.get("/audit/<audit_id>")
def get_audit(audit_id: str):
    row = (
        _container()
        .store.reader()
        .execute("SELECT * FROM audit_records WHERE audit_id = ?", (audit_id,))
        .fetchone()
    )
    if row is None:
        return error("NOT_FOUND", "Audit record not found.", status=404)
    record = dict(row)
    if record["payload"]:
        record["payload"] = json.loads(record["payload"])
    record["created_at"] = _iso(record["created_at"])
    return ok({"audit": record})
