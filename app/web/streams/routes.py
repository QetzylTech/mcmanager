"""Long-lived SSE routes backed by the compute-once realtime hub."""

from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, current_app, request, stream_with_context

from app.domain.tuning import LOG_LINE_BUFFER_LINES
from app.platform.process.tailing import read_durable_log
from app.services.auth import SessionError
from app.services.realtime import RealtimeHub

streams_bp = Blueprint("streams", __name__, url_prefix="/stream")


def _snapshot_frame(event_name: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, separators=(",", ":"))
    return f"id: 0\nevent: {event_name}\ndata: {encoded}\nretry: 3000\n\n"


def _log_frame(event_name: str, payload: dict[str, Any], cursor: str | None = None) -> str:
    encoded = json.dumps(payload, separators=(",", ":"))
    event_id = f"id: {cursor}\n" if cursor else ""
    return f"{event_id}event: {event_name}\ndata: {encoded}\n\n"


def _log_session_paths(container: Any, world_id: str) -> list[tuple[str, Path]]:
    sessions = container.store.reader().execute(
        """
        SELECT session_id
        FROM runtime_sessions
        WHERE world_id = ?
        ORDER BY started_at, session_id
        """,
        (world_id,),
    ).fetchall()
    try:
        root = container.configuration.resolve_effective(world_id)["log_root_path"]
    except KeyError:
        root = "logs"
    log_dir = Path(str(root or "logs")) / world_id / world_id
    return [
        (str(row["session_id"]), log_dir / f"{row['session_id']}.log")
        for row in sessions
    ]


def _log_cursor_index(paths: list[tuple[str, Path]], cursor: str) -> tuple[int, int] | None:
    session_id, separator, raw_offset = cursor.rpartition(":")
    if not separator or not session_id:
        return None
    try:
        offset = int(raw_offset)
    except ValueError:
        return None
    if offset < 0:
        return None
    for index, (candidate, path) in enumerate(paths):
        if candidate != session_id:
            continue
        try:
            size = path.stat().st_size
            if offset > size:
                return None
            if offset:
                with path.open("rb") as handle:
                    handle.seek(offset - 1)
                    if handle.read(1) != b"\n":
                        return None
        except OSError:
            return None
        return index, offset
    return None


def _count_log_records(paths: list[tuple[str, Path]], end_index: int, end_offset: int) -> int:
    count = 0
    for index, (_session_id, path) in enumerate(paths[: end_index + 1]):
        offset = 0
        limit_offset = end_offset if index == end_index else None
        while limit_offset is None or offset < limit_offset:
            records, next_offset = read_durable_log(path, offset, limit=256)
            if not records:
                break
            if limit_offset is not None:
                records = [record for record in records if record[1] <= limit_offset]
            count += len(records)
            if not records or next_offset <= offset:
                break
            offset = next_offset
    return count


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
    auth_check = _auth_check_for_request(container)
    requested_cursor = request.headers.get("Last-Event-ID", "") or request.args.get(
        "after", ""
    )

    def generate() -> Iterator[str]:
        paths = _log_session_paths(container, world_id)
        cursor = requested_cursor or None
        cursor_position = _log_cursor_index(paths, cursor) if cursor else None
        replaying = bool(cursor)
        replay_notice_sent = False
        line_no = 0

        if cursor and cursor_position is None:
            yield _log_frame(
                "log.gap",
                {
                    "world_id": world_id,
                    "requested_cursor": cursor,
                    "reason": "cursor_unavailable",
                },
            )
            cursor = None
            replaying = False

        if not replaying:
            snapshot: deque[dict[str, Any]] = deque(maxlen=LOG_LINE_BUFFER_LINES)
            for session_id, path in paths:
                offset = 0
                while True:
                    records, next_offset = read_durable_log(path, offset, limit=256)
                    if not records:
                        break
                    for _start, end, channel, line in records:
                        line_no += 1
                        snapshot.append(
                            {
                                "world_id": world_id,
                                "session_id": session_id,
                                "channel": channel,
                                "line": line,
                                "line_no": line_no,
                                "cursor": f"{session_id}:{end}",
                            }
                        )
                    offset = next_offset
                    if next_offset <= 0:
                        break
            cursor = snapshot[-1]["cursor"] if snapshot else None
            if snapshot:
                last_session, _, last_offset = cursor.rpartition(":")
                try:
                    cursor_position = next(
                        (index, int(last_offset))
                        for index, (session_id, _path) in enumerate(paths)
                        if session_id == last_session
                    )
                except (StopIteration, ValueError):
                    cursor_position = None
            lines = list(snapshot)
            if cursor_position is not None:
                line_no = _count_log_records(paths, *cursor_position)
            yield _log_frame(
                "log.line",
                {"world_id": world_id, "lines": lines},
                cursor,
            )

        index, offset = cursor_position or (0, 0)
        last_ping = time.monotonic()
        while True:
            if container.realtime.is_shutdown:
                yield "event: manager.shutdown\ndata: {}\n\n"
                break
            if not auth_check():
                yield 'event: stream.error\ndata: {"code":"AUTH_SESSION_EXPIRED"}\n\n'
                break

            paths = _log_session_paths(container, world_id)
            if cursor:
                session_id = cursor.rpartition(":")[0]
                if session_id not in {item[0] for item in paths}:
                    yield _log_frame(
                        "log.gap",
                        {
                            "world_id": world_id,
                            "requested_cursor": cursor,
                            "reason": "cursor_unavailable",
                        },
                    )
                    cursor = None
                    cursor_position = None
                    index, offset, line_no = 0, 0, 0
                    replaying = False

            if index >= len(paths):
                index = max(0, len(paths) - 1)
                offset = 0 if not paths else offset

            emitted = False
            for path_index in range(index, len(paths)):
                session_id, path = paths[path_index]
                start_offset = offset if path_index == index else 0
                try:
                    if start_offset > path.stat().st_size:
                        raise ValueError("durable log was truncated")
                except (OSError, ValueError):
                    if cursor:
                        yield _log_frame(
                            "log.gap",
                            {
                                "world_id": world_id,
                                "requested_cursor": cursor,
                                "reason": "durable_log_truncated",
                            },
                        )
                        cursor = None
                        replaying = False
                        line_no = 0
                        start_offset = 0

                records, next_offset = read_durable_log(
                    path, start_offset, limit=256
                )
                if records and replaying and not replay_notice_sent:
                    yield _log_frame(
                        "log.replay",
                        {"world_id": world_id, "after_cursor": requested_cursor},
                    )
                    replay_notice_sent = True
                for _start, end, channel, line in records:
                    line_no += 1
                    cursor = f"{session_id}:{end}"
                    yield _log_frame(
                        "log.line",
                        {
                            "world_id": world_id,
                            "session_id": session_id,
                            "channel": channel,
                            "line": line,
                            "line_no": line_no,
                            "cursor": cursor,
                        },
                        cursor,
                    )
                    offset = end
                    emitted = True
                index = path_index
                offset = next_offset
                if len(records) >= 256:
                    break
                if path_index < len(paths) - 1:
                    index = path_index + 1
                    offset = 0

            if emitted:
                continue
            now = time.monotonic()
            if now - last_ping >= 3:
                yield ": ping\n\n"
                last_ping = now
            time.sleep(0.25)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
