"""SSE stream routes backed by the compute-once realtime hub."""

from __future__ import annotations

import json

from flask import Blueprint, Response, current_app, request

streams_bp = Blueprint('streams', __name__, url_prefix='/stream')


def _snapshot_frame(event_name: str, payload: dict) -> str:
    return f'id: 0\nevent: {event_name}\ndata: {json.dumps(payload, separators=(",", ":"))}\nretry: 3000\n\n'


@streams_bp.get('/events')
def manager_events():
    container = current_app.extensions['mcmanager_container']
    payload = {'manager': {'freshness': int(container.clock.now())}, 'cached_live': {'world_states': []}}
    return Response(_snapshot_frame('snapshot', payload), mimetype='text/event-stream')


@streams_bp.get('/worlds/<world_id>/events')
def world_events(world_id: str):
    container = current_app.extensions['mcmanager_container']
    payload = {'world_id': world_id, 'freshness': int(container.clock.now())}
    return Response(_snapshot_frame('snapshot.world', payload), mimetype='text/event-stream')


@streams_bp.get('/worlds/<world_id>/logs')
def world_logs(world_id: str):
    container = current_app.extensions['mcmanager_container']
    last = request.headers.get('Last-Event-ID')
    last_id = int(last) if last and last.isdigit() else None
    frames = [
        event.encode()
        for event in container.realtime.replay(f'world:{world_id}:logs', last_event_id=last_id)
    ]
    if not frames:
        frames.append(_snapshot_frame('log.line', {'world_id': world_id, 'lines': []}))
    return Response(''.join(frames), mimetype='text/event-stream')


@streams_bp.get('/restore_logs')
def restore_logs():
    world_id = request.args.get('world_id')
    return Response(_snapshot_frame('restore.progress', {'world_id': world_id, 'stage': 'snapshot'}), mimetype='text/event-stream')


@streams_bp.get('/metrics')
def metrics():
    container = current_app.extensions['mcmanager_container']
    return Response(_snapshot_frame('metrics', {'freshness': int(container.clock.now())}), mimetype='text/event-stream')
