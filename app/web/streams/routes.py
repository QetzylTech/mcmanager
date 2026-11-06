"""Long-lived SSE routes backed by the compute-once realtime hub."""

from __future__ import annotations

import json

from flask import Blueprint, Response, current_app, request, stream_with_context

from app.services.realtime import RealtimeHub

streams_bp = Blueprint("streams", __name__, url_prefix="/stream")


def _snapshot_frame(event_name: str, payload: dict) -> str:
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
    snapshot_payload: dict,
) -> Response:
    subscriber = hub.subscribe(stream, last_event_id=_last_event_id())

    def generate():
        try:
            yield _snapshot_frame(snapshot_event, snapshot_payload)
            yield from subscriber.frames()
        finally:
            hub.unsubscribe(stream, subscriber)

    response = Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
    return response


@streams_bp.get("/events")
def manager_events():
    container = current_app.extensions["mcmanager_container"]
    payload = {
        "manager": {"freshness": int(container.clock.now())},
        "cached_live": {"world_states": []},
    }
    return _subscribe(
        container.realtime,
        "events",
        snapshot_event="snapshot",
        snapshot_payload=payload,
    )


@streams_bp.get("/worlds/<world_id>/events")
def world_events(world_id: str):
    container = current_app.extensions["mcmanager_container"]
    payload = {"world_id": world_id, "freshness": int(container.clock.now())}
    return _subscribe(
        container.realtime,
        f"world:{world_id}:events",
        snapshot_event="snapshot.world",
        snapshot_payload=payload,
    )


@streams_bp.get("/worlds/<world_id>/logs")
def world_logs(world_id: str):
    container = current_app.extensions["mcmanager_container"]
    payload = {"world_id": world_id, "lines": container.logs.buffered(world_id)}
    return _subscribe(
        container.realtime,
        f"world:{world_id}:logs",
        snapshot_event="log.line",
        snapshot_payload=payload,
    )


@streams_bp.get("/restore_logs")
def restore_logs():
    container = current_app.extensions["mcmanager_container"]
    world_id = request.args.get("world_id")
    return _subscribe(
        container.realtime,
        f"restore:{world_id}:logs",
        snapshot_event="restore.progress",
        snapshot_payload={
            "world_id": world_id,
            "stage": "snapshot",
            "freshness": int(container.clock.now()),
        },
    )


@streams_bp.get("/metrics")
def metrics():
    container = current_app.extensions["mcmanager_container"]
    return _subscribe(
        container.realtime,
        "metrics",
        snapshot_event="metrics",
        snapshot_payload={"freshness": int(container.clock.now())},
    )
