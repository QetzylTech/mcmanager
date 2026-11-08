from __future__ import annotations

import app.services.realtime as realtime
from app.platform.process.tailing import DurableSessionLog
from app.services.realtime import RealtimeHub
from app.web.streams.routes import streams_bp


def _log_stream_app(tmp_path):
    from flask import Flask

    world_id = 'world-1'
    session_id = 'session-1'
    log_root = tmp_path / 'logs'
    durable = DurableSessionLog(
        str(log_root / world_id / world_id / f'{session_id}.log')
    )

    class Store:
        def reader(self):
            return self

        def execute(self, _query, _params):
            return self

        def fetchall(self):
            return [{'session_id': session_id}]

    class Configuration:
        def resolve_effective(self, _world_id):
            return {'log_root_path': str(log_root)}

    class Auth:
        def validate_session(self, _token, *, ip):
            return ip

    class Clock:
        def now(self):
            return 123

    class Container:
        store = Store()
        configuration = Configuration()
        auth = Auth()
        realtime = RealtimeHub()
        clock = Clock()

    app = Flask(__name__)
    app.register_blueprint(streams_bp)
    app.extensions['mcmanager_container'] = Container()
    return app, durable, world_id, session_id


def _saturate_client(hub: RealtimeHub, client_id: str, stream: str) -> None:
    slow = hub.subscribe(stream, client_id=client_id)
    for sample in range(201):
        hub.publish(stream, 'metrics', {'sample': sample})
    assert slow.closed


def test_slow_client_alert_is_rate_limited_per_client(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(realtime.time, 'monotonic', lambda: now[0])
    hub = RealtimeHub()

    _saturate_client(hub, 'client-a', 'metrics')
    _saturate_client(hub, 'client-a', 'world:w1:events')
    alerts = [event for event in hub.replay('events', last_event_id=None) if event.event == 'alert']

    assert len(alerts) == 1
    assert alerts[0].data == {
        'category': 'slow_client_disconnected',
        'severity': 'high',
        'message': 'A slow stream client was disconnected.',
        'details': {'stream': 'metrics'},
    }

    now[0] += 60
    _saturate_client(hub, 'client-a', 'restore:w1:logs')
    alerts = [event for event in hub.replay('events', last_event_id=None) if event.event == 'alert']
    assert len(alerts) == 2
    assert 'client-a' in hub._slow_client_alerted_at

    now[0] += 60
    _saturate_client(hub, 'client-b', 'metrics')
    assert set(hub._slow_client_alerted_at) == {'client-b'}


def test_saturated_subscriber_does_not_block_healthy_subscriber():
    hub = RealtimeHub()
    slow = hub.subscribe('metrics')
    fast = hub.subscribe('metrics')
    fast_frames = fast.frames()

    for sample in range(201):
        hub.publish('metrics', 'metrics', {'sample': sample})
        assert 'event: metrics' in next(fast_frames)

    assert slow.closed
    assert hub.subscriber_count('metrics') == 1
    hub.publish('metrics', 'metrics', {'sample': 201})
    assert '"sample":201' in next(fast_frames)


def test_world_log_stream_replays_backlog_after_cursor_without_queue_overflow(
    tmp_path,
):
    app, durable, world_id, _session_id = _log_stream_app(tmp_path)
    durable.write('stdout', 'before cursor')
    client = app.test_client()
    initial = client.get(f'/stream/worlds/{world_id}/logs', buffered=False)
    try:
        snapshot = next(iter(initial.response)).decode()
        cursor = next(
            line.removeprefix('id: ')
            for line in snapshot.splitlines()
            if line.startswith('id: ')
        )
    finally:
        initial.close()

    backlog_size = 220
    for number in range(backlog_size):
        durable.write('stdout', f'backlog {number}')

    replay = client.get(
        f'/stream/worlds/{world_id}/logs',
        headers={'Last-Event-ID': cursor},
        buffered=False,
    )
    frames = iter(replay.response)
    try:
        assert b'event: log.replay' in next(frames)
        line_frames = [next(frames).decode() for _ in range(backlog_size)]
        assert all('event: log.line' in frame for frame in line_frames)
        assert 'backlog 0' in line_frames[0]
        assert f'backlog {backlog_size - 1}' in line_frames[-1]
        assert all('id: session-1:' in frame for frame in line_frames)
    finally:
        replay.close()


def test_world_log_stream_reports_unavailable_cursor_then_resnapshots(tmp_path):
    app, durable, world_id, _session_id = _log_stream_app(tmp_path)
    durable.write('stderr', 'retained line')
    response = app.test_client().get(
        f'/stream/worlds/{world_id}/logs',
        headers={'Last-Event-ID': 'expired-session:99'},
        buffered=False,
    )
    frames = iter(response.response)
    try:
        gap = next(frames).decode()
        snapshot = next(frames).decode()
        assert 'event: log.gap' in gap
        assert '"reason":"cursor_unavailable"' in gap
        assert 'retained line' in snapshot
        assert 'event: log.line' in snapshot
    finally:
        response.close()
