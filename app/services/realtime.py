"""Realtime SSE fan-out primitives (Gate 3).

The hub computes each event once, stores it in a bounded replay buffer, and
fans the same encoded SSE frame to every subscriber of the stream.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from app.domain.tuning import (
    LOG_LINE_BUFFER_LINES,
    SSE_HEARTBEAT_S,
    SSE_REPLAY_BUFFER_EVENTS,
)


@dataclass(frozen=True)
class StreamEvent:
    sequence: int
    event: str
    data: dict[str, Any]

    def encode(self) -> str:
        payload = json.dumps(self.data, separators=(',', ':'))
        return f'id: {self.sequence}\nevent: {self.event}\ndata: {payload}\n\n'


class StreamSubscriber:
    def __init__(self) -> None:
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=200)
        self._client_key: object | str = object()
        self.closed = False

    def put(self, frame: str) -> bool:
        if self.closed:
            return False
        try:
            self._queue.put_nowait(frame)
            return True
        except queue.Full:
            self.close()
            return False

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            with suppress(queue.Full):
                self._queue.put_nowait(None)

    def frames(self, *, auth_check: Callable[[], bool] | None = None) -> Iterable[str]:
        next_keepalive = time.monotonic() + SSE_HEARTBEAT_S
        while True:
            timeout = float(SSE_HEARTBEAT_S)
            if auth_check is not None:
                timeout = min(1, max(0, next_keepalive - time.monotonic()))
            try:
                item = self._queue.get(timeout=timeout)
            except queue.Empty:
                if self.closed:
                    break
                if auth_check is not None and not auth_check():
                    yield _auth_expired_frame()
                    break
                if time.monotonic() >= next_keepalive:
                    yield ': ping\n\n'
                    next_keepalive = time.monotonic() + SSE_HEARTBEAT_S
                continue
            if item is None:
                break
            if (
                auth_check is not None
                and 'event: manager.shutdown' not in item
                and not auth_check()
            ):
                yield _auth_expired_frame()
                break
            yield item


def _auth_expired_frame() -> str:
    payload = json.dumps({'code': 'AUTH_SESSION_EXPIRED'}, separators=(',', ':'))
    return f'event: stream.error\ndata: {payload}\n\n'


class RealtimeHub:
    """Per-stream replay buffers plus subscriber fan-out."""

    def __init__(self, *, replay_limit: int = SSE_REPLAY_BUFFER_EVENTS) -> None:
        self._replay_limit = replay_limit
        self._next_sequence: dict[str, int] = {}
        self._buffers: dict[str, deque[StreamEvent]] = {}
        self._subscribers: dict[str, list[StreamSubscriber]] = {}
        self._slow_client_alerted_at: dict[object | str, float] = {}
        self._lock = threading.RLock()
        self._closed = False

    @property
    def is_shutdown(self) -> bool:
        with self._lock:
            return self._closed

    def subscribe(
        self,
        stream: str,
        *,
        last_event_id: int | None = None,
        client_id: str | None = None,
    ) -> StreamSubscriber:
        subscriber = StreamSubscriber()
        if client_id is not None:
            subscriber._client_key = client_id
        with self._lock:
            self._subscribers.setdefault(stream, []).append(subscriber)
            for event in self.replay(stream, last_event_id=last_event_id):
                subscriber.put(event.encode())
        return subscriber

    def unsubscribe(self, stream: str, subscriber: StreamSubscriber) -> None:
        with self._lock:
            subscriber.close()
            subscribers = self._subscribers.get(stream)
            if subscribers is not None:
                self._subscribers[stream] = [
                    item for item in subscribers if item is not subscriber
                ]

    def subscriber_count(self, stream: str) -> int:
        with self._lock:
            return len(self._subscribers.get(stream, ()))

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for stream, subscribers in self._subscribers.items():
                sequence = self._next_sequence.get(stream, 1)
                self._next_sequence[stream] = sequence + 1
                event = StreamEvent(sequence, 'manager.shutdown', {})
                self._buffers.setdefault(
                    stream, deque(maxlen=self._replay_limit)
                ).append(event)
                frame = event.encode()
                for subscriber in subscribers:
                    subscriber.put(frame)
                    subscriber.close()
            self._subscribers.clear()

    def publish(self, stream: str, event: str, data: dict[str, Any]) -> StreamEvent:
        with self._lock:
            stream_event, dropped = self._publish_locked(stream, event, data)
            while dropped:
                subscriber = dropped.pop()
                now = time.monotonic()
                while self._slow_client_alerted_at:
                    oldest_key = next(iter(self._slow_client_alerted_at))
                    if now - self._slow_client_alerted_at[oldest_key] < 60:
                        break
                    del self._slow_client_alerted_at[oldest_key]
                last_alerted_at = self._slow_client_alerted_at.get(subscriber._client_key)
                if last_alerted_at is not None and now - last_alerted_at < 60:
                    continue
                self._slow_client_alerted_at[subscriber._client_key] = now
                _, additional_drops = self._publish_locked(
                    'events',
                    'alert',
                    {
                        'category': 'slow_client_disconnected',
                        'severity': 'high',
                        'message': 'A slow stream client was disconnected.',
                        'details': {'stream': stream},
                    },
                )
                dropped.extend(additional_drops)
            return stream_event

    def _publish_locked(
        self, stream: str, event: str, data: dict[str, Any]
    ) -> tuple[StreamEvent, list[StreamSubscriber]]:
        sequence = self._next_sequence.get(stream, 1)
        self._next_sequence[stream] = sequence + 1
        stream_event = StreamEvent(sequence=sequence, event=event, data=data)
        self._buffers.setdefault(stream, deque(maxlen=self._replay_limit)).append(stream_event)
        frame = stream_event.encode()
        live = []
        dropped = []
        for subscriber in self._subscribers.get(stream, []):
            if subscriber.put(frame):
                live.append(subscriber)
            else:
                dropped.append(subscriber)
        self._subscribers[stream] = live
        return stream_event, dropped

    def replay(self, stream: str, *, last_event_id: int | None) -> list[StreamEvent]:
        with self._lock:
            events = list(self._buffers.get(stream, ()))
            if last_event_id is None:
                return events
            return [event for event in events if event.sequence > last_event_id]


class LogFanout:
    """Bounded per-world log ring feeding the shared SSE hub."""

    def __init__(self, hub: RealtimeHub, *, line_limit: int = LOG_LINE_BUFFER_LINES) -> None:
        self._hub = hub
        self._line_limit = line_limit
        self._lines: dict[str, deque[dict[str, Any]]] = {}
        self._line_numbers: dict[str, int] = {}

    def append(
        self,
        *,
        world_id: str,
        session_id: str,
        channel: str,
        line: str,
        ts: int,
    ) -> StreamEvent:
        line_no = self._line_numbers.get(world_id, 0) + 1
        self._line_numbers[world_id] = line_no
        payload = {
            'world_id': world_id,
            'session_id': session_id,
            'channel': channel,
            'line': line,
            'line_no': line_no,
            'ts': ts,
        }
        self._lines.setdefault(world_id, deque(maxlen=self._line_limit)).append(payload)
        return self._hub.publish(f'world:{world_id}:logs', 'log.line', payload)

    def buffered(self, world_id: str) -> list[dict[str, Any]]:
        return list(self._lines.get(world_id, ()))
