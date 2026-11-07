from __future__ import annotations

import app.services.realtime as realtime
from app.services.realtime import RealtimeHub


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
