"""Realtime SSE fan-out primitives (Gate 3).

The hub computes each event once, stores it in a bounded replay buffer, and
fans the same encoded SSE frame to every subscriber of the stream.
"""

from __future__ import annotations

import json
import queue
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable

from app.domain.tuning import LOG_LINE_BUFFER_LINES, SSE_REPLAY_BUFFER_EVENTS


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
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass

    def frames(self) -> Iterable[str]:
        while not self.closed:
            item = self._queue.get()
            if item is None:
                break
            yield item


class RealtimeHub:
    """Per-stream replay buffers plus subscriber fan-out."""

    def __init__(self, *, replay_limit: int = SSE_REPLAY_BUFFER_EVENTS) -> None:
        self._replay_limit = replay_limit
        self._next_sequence: dict[str, int] = {}
        self._buffers: dict[str, deque[StreamEvent]] = {}
        self._subscribers: dict[str, list[StreamSubscriber]] = {}

    def subscribe(self, stream: str, *, last_event_id: int | None = None) -> StreamSubscriber:
        subscriber = StreamSubscriber()
        self._subscribers.setdefault(stream, []).append(subscriber)
        for event in self.replay(stream, last_event_id=last_event_id):
            subscriber.put(event.encode())
        return subscriber

    def publish(self, stream: str, event: str, data: dict[str, Any]) -> StreamEvent:
        sequence = self._next_sequence.get(stream, 1)
        self._next_sequence[stream] = sequence + 1
        stream_event = StreamEvent(sequence=sequence, event=event, data=data)
        self._buffers.setdefault(stream, deque(maxlen=self._replay_limit)).append(stream_event)
        frame = stream_event.encode()
        live = []
        for subscriber in self._subscribers.get(stream, []):
            if subscriber.put(frame):
                live.append(subscriber)
        self._subscribers[stream] = live
        return stream_event

    def replay(self, stream: str, *, last_event_id: int | None) -> list[StreamEvent]:
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
