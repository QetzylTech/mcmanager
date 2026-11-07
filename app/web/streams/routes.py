"""Long-lived SSE routes backed by the compute-once realtime hub."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

from flask import Blueprint, Response, current_app, request, stream_with_context

from app.services.auth import SessionError
from app.services.realtime import RealtimeHub

streams_bp = Blueprint("streams", __name__, url_prefix="/stream")


def _snapshot_frame(event_name: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, separators=(",", ":"))
    return f"id: 0\nevent: {event_name}\ndata: {encoded}\nretry: 3000\n\n"


def _last_event_id() -> int | None:
    value = request.headers.get("Last-Event-ID", "")
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _subscribe(
    hub: RealtimeHub,
    stream: str,
    *,
    snapshot_event: str,
    snapshot_payload: Callable[[], dict[str, Any]],
    auth_check: Callable[[], bool],
    on_close: Callable[[], None] | None = None,
) -> Response:
    subscriber = hub.subscribe(stream, last_event_id=_last_event_id())
    snapshot = snapshot_payload()

    def generate() -> Iterator[str]:
        try:
            yield _snapshot_frame(snapshot_event, snapshot)
            yield from subscriber.frames(auth_check=auth_check)
        finally:
            hub.unsubscribe(stream, subscriber)
            if on_close is not None:
                on_close()

    def close_subscriber() -> None:
        hub.unsubscribe(stream, subscriber)
        if on_close is not None:
            on_close()

    response = Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
    response.call_on_close(close_subscriber)
    return response


def _session_check(container: Any, token: str, ip: str) -> Callable[[], bool]:
    def check() -> bool:
        if container.realtime.is_shutdown:
            return True
        try:
            container.auth.validate_session(token, ip=ip)
        except SessionError:
            return False
        return True

    return check


def _manager_snapshot(container: Any) -> dict[str, Any]:
    worlds = [
        dict(row)
        for row in container.store.reader()
        .execute(
            """
            SELECT world_id, display_name, server_type, mc_version, state, updated_at
            FROM world_instances
            WHERE deleted_at IS NULL
            ORDER BY display_name, world_id
            """
        )
        .fetchall()
    ]
    operations = [
        dict(row)
        for row in container.store.reader()
        .execute(
            """
            SELECT op_id, op_type, world_id, status, checkpoint, error_code,
                   message, created_at, updated_at
            FROM operations
            ORDER BY created_at DESC, op_id DESC
            """
        )
        .fetchall()
    ]
    backups = [
        dict(row)
        for row in container.store.reader()
        .execute(
            """
            SELECT artifact_id, world_id, category, size_bytes, suspect,
                   operation_id, created_at
            FROM backup_artifacts
            WHERE deleted_at IS NULL
            ORDER BY created_at DESC, artifact_id DESC
            """
        )
        .fetchall()
    ]
    schedules = [
        dict(row)
        for row in container.store.reader()
        .execute(
            """
            SELECT schedule_id, scope, world_id, schedule_type, enabled, version,
                   last_changed_at
            FROM schedules
            WHERE deleted_at IS NULL
            ORDER BY schedule_id
            """
        )
        .fetchall()
    ]
    notifications = [
        dict(row)
        for row in container.store.reader()
        .execute(
            """
            SELECT notification_id, category, severity, message,
                   related_operation_id, related_world_id, requires_action,
                   action_taken, created_at
            FROM notifications
            ORDER BY created_at DESC, notification_id DESC
            """
        )
        .fetchall()
    ]
    freshness = int(container.clock.now())
    return {
        "manager": {
            "worlds": worlds,
            "operations": operations,
            "backups": backups,
            "schedules": schedules,
            "notifications": notifications,
            "freshness": freshness,
        },
        "cached_live": {
            "metrics": None,
            "world_states": [
                {"world_id": world["world_id"], "state": world["state"]}
                for world in worlds
            ],
        },
    }


def _world_snapshot(container: Any, world_id: str) -> dict[str, Any]:
    row = container.store.reader().execute(
        """
        SELECT world_id, display_name, server_type, mc_version, state, updated_at
        FROM world_instances
        WHERE world_id = ? AND deleted_at IS NULL
        """,
        (world_id,),
    ).fetchone()
    return {
        "world_id": world_id,
        "world": dict(row) if row is not None else None,
        "freshness": int(container.clock.now()),
    }


def _auth_check_for_request(container: Any) -> Callable[[], bool]:
    token = request.cookies.get("mcmanager_session", "")
    ip = request.remote_addr or ""
    return _session_check(container, token, ip)


@streams_bp.get("/events")
def manager_events() -> Response:
    container = current_app.extensions["mcmanager_container"]
    return _subscribe(
        container.realtime,
        "events",
        snapshot_event="snapshot",
        snapshot_payload=lambda: _manager_snapshot(container),
        auth_check=_auth_check_for_request(container),
    )


@streams_bp.get("/worlds/<world_id>/events")
def world_events(world_id: str) -> Response:
    container = current_app.extensions["mcmanager_container"]
    return _subscribe(
        container.realtime,
        f"world:{world_id}:events",
        snapshot_event="snapshot.world",
        snapshot_payload=lambda: _world_snapshot(container, world_id),
        auth_check=_auth_check_for_request(container),
    )


@streams_bp.get("/worlds/<world_id>/logs")
def world_logs(world_id: str) -> Response:
    container = current_app.extensions["mcmanager_container"]
    return _subscribe(
        container.realtime,
        f"world:{world_id}:logs",
        snapshot_event="log.line",
        snapshot_payload=lambda: {
            "world_id": world_id,
            "lines": container.logs.buffered(world_id),
        },
        auth_check=_auth_check_for_request(container),
    )


@streams_bp.get("/restore_logs")
def restore_logs() -> Response:
    container = current_app.extensions["mcmanager_container"]
    world_id = request.args.get("world_id")
    return _subscribe(
        container.realtime,
        f"restore:{world_id}:logs",
        snapshot_event="restore.progress",
        snapshot_payload=lambda: {
            "world_id": world_id,
            "stage": "snapshot",
            "freshness": int(container.clock.now()),
        },
        auth_check=_auth_check_for_request(container),
    )


@streams_bp.get("/metrics")
def metrics() -> Response:
    container = current_app.extensions["mcmanager_container"]
    return _subscribe(
        container.realtime,
        "metrics",
        snapshot_event="metrics",
        snapshot_payload=container.metrics.stream_snapshot,
        auth_check=_auth_check_for_request(container),
        on_close=container.metrics.notify_subscribers_changed,
    )
