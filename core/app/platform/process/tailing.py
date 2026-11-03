"""Bounded line-buffer + SSE-ready line emitter (Document 13 section 3.3).

Each spawned process gets stdout/stderr line readers on dedicated reader
threads. Lines are normalized to ``\\n``, capped (default 64KB, remainder
dropped with a sentinel), appended to a bounded ring buffer (default 5000
lines/world), and fanned out to attached sinks.

Backpressure (C13): each subscriber runs on its own worker thread draining a
bounded queue. A slow sink never blocks the process reader — when its queue
overflows, events are dropped and counted, and the adapter can surface the
drop as an alert. ``tail(since_offset=N)`` replays buffered lines for
reconnect hydration; when the buffer has trimmed past N the adapter signals
``buffer_trimmed`` so the client views the on-disk log file instead.
"""

from __future__ import annotations

import os
import queue
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path

from app.domain.tuning import LOG_LINE_BUFFER_LINES

_SUBSCRIBER_QUEUE_CAPACITY = 256
_SUBSCRIBER_WORKER_IDLE_S = 0.2


def verbose_logging_enabled() -> bool:
    """VERBOSE_LOGGING defaults to false (gate1 Module 3 / Doc 12 .env.example)."""
    return os.environ.get('VERBOSE_LOGGING', 'false').strip().lower() in {
        '1',
        'true',
        'yes',
        'on',
    }


def is_debug_log_line(channel: str, line: str) -> bool:
    return channel == 'debug' or '[DEBUG]' in line


class DurableSessionLog:
    """Append-only per-session log file (C12 durability)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._mutex = threading.Lock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    def write(self, channel: str, line: str) -> None:
        with self._mutex:
            with open(self.path, 'a', encoding='utf-8') as handle:
                handle.write(f'[{channel}] {line}\n')
                handle.flush()


def session_log_for(log_dir: str | None, session_id: str) -> DurableSessionLog | None:
    if not log_dir or not session_id:
        return None
    return DurableSessionLog(str(Path(log_dir) / f'{session_id}.log'))


def ingest_log_line(
    buffer: 'LogRingBuffer | RingBuffer',
    channel: str,
    line: str,
    *,
    durable_log: DurableSessionLog | None = None,
) -> bool:
    """Filter, ring-buffer, and optionally persist one line.

    Returns False when VERBOSE_LOGGING=false suppressed a debug line.
    """
    if is_debug_log_line(channel, line) and not verbose_logging_enabled():
        return False
    if isinstance(buffer, LogRingBuffer):
        buffer.append(channel, line)
    else:
        buffer.append(line)
    if durable_log is not None:
        durable_log.write(channel, line)
    return True


class LogStreamTailer:
    """Gate 1 Module 3 tailer: 5000-line ring + VERBOSE_LOGGING + session file."""

    def __init__(self, world_id: str, session_id: str, log_dir: str | None) -> None:
        self.world_id = world_id
        self.ring_buffer: deque[dict[str, object]] = deque(maxlen=LOG_LINE_BUFFER_LINES)
        self.log_file_path = (
            os.path.join(log_dir, f'{session_id}.log') if log_dir else None
        )
        self.verbose_logging = verbose_logging_enabled()
        self._durable = session_log_for(log_dir, session_id)

    def process_pipe_output(self, channel_name: str, line_str: str) -> bool:
        is_debug = is_debug_log_line(channel_name, line_str)
        if is_debug and not self.verbose_logging:
            return False
        self.ring_buffer.append(
            {'world_id': self.world_id, 'channel': channel_name, 'line': line_str}
        )
        if self._durable is not None:
            self._durable.write(channel_name, line_str)
        return True


class Subscription:
    """A live subscriber connection; ``close()`` stops its worker."""

    def __init__(self, callback: Callable[[int, str], None]) -> None:
        self._callback = callback
        self._queue: queue.Queue[tuple[int, str]] = queue.Queue(
            maxsize=_SUBSCRIBER_QUEUE_CAPACITY
        )
        self._dropped = 0
        self._closed = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name='log-subscriber', daemon=True
        )
        self._thread.start()

    def submit(self, line_no: int, line: str) -> None:
        """Enqueue for the worker; overflow drops + counts instead of blocking."""
        if self._closed.is_set():
            return
        try:
            self._queue.put_nowait((line_no, line))
        except queue.Full:
            self._dropped += 1

    def _run(self) -> None:
        while not self._closed.is_set():
            try:
                line_no, line = self._queue.get(timeout=_SUBSCRIBER_WORKER_IDLE_S)
            except queue.Empty:
                continue
            try:
                self._callback(line_no, line)
            except Exception:
                # A broken sink must never kill the fan-out worker; the
                # SSE layer reports sink failures out-of-band.
                self._dropped += 1

    @property
    def dropped(self) -> int:
        return self._dropped

    def close(self) -> None:
        self._closed.set()
        self._thread.join(timeout=1.0)


class RingBuffer:
    """Thread-safe bounded deque of ``(line_no, line)`` with subscribers."""

    def __init__(self, maxlen: int = LOG_LINE_BUFFER_LINES) -> None:
        self._buffer: deque[tuple[int, str]] = deque(maxlen=maxlen)
        self._mutex = threading.Lock()
        self._next_line_no = 0
        self._subscribers: list[Subscription] = []

    def append(self, line: str) -> None:
        """Append + fan out. Never blocks on a slow subscriber (C13)."""
        with self._mutex:
            self._buffer.append((self._next_line_no, line))
            self._next_line_no += 1
            subscribers = list(self._subscribers)
        for subscription in subscribers:
            subscription.submit(self._next_line_no - 1, line)

    def tail(self, since_offset: int = 0) -> list[tuple[int, str]]:
        """Replay lines after ``since_offset`` (bounded buffer)."""
        with self._mutex:
            return [item for item in self._buffer if item[0] >= since_offset]

    def trimmed(self, since_offset: int) -> bool:
        """True when the buffer has trimmed past ``since_offset``."""
        with self._mutex:
            if not self._buffer:
                return since_offset > 0
            return since_offset < self._buffer[0][0]

    def max_line_no(self) -> int:
        with self._mutex:
            return self._next_line_no - 1

    def subscribe(self, callback: Callable[[int, str], None]) -> Subscription:
        """Register a fan-out subscriber (C13: isolated worker thread)."""
        with self._mutex:
            self._subscribers.append(Subscription(callback))
            return self._subscribers[-1]

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._mutex:
            if subscription in self._subscribers:
                self._subscribers.remove(subscription)
        subscription.close()

    def clear(self) -> None:
        with self._mutex:
            self._buffer.clear()


class LogRingBuffer:
    """Per-world ring buffers keyed by channel."""

    def __init__(self, maxlen: int = LOG_LINE_BUFFER_LINES) -> None:
        self._maxlen = maxlen
        self._channels: dict[str, RingBuffer] = {}
        self._mutex = threading.Lock()

    def channel(self, name: str) -> RingBuffer:
        with self._mutex:
            if name not in self._channels:
                self._channels[name] = RingBuffer(maxlen=self._maxlen)
            return self._channels[name]

    def append(self, channel: str, line: str) -> None:
        self.channel(channel).append(line)

    def channels(self) -> tuple[str, ...]:
        with self._mutex:
            return tuple(self._channels.keys())


class ProcessLineReader:
    """Reads lines from a binary file object on a dedicated thread."""

    def __init__(
        self,
        stream: object,
        world_id: str,
        session_token: str,
        channel: str,
        buffer: RingBuffer,
        sink: Callable[..., None] | None,
        max_line_bytes: int = 64 * 1024,
        durable_log: DurableSessionLog | None = None,
    ) -> None:
        self._stream = stream
        self._world_id = world_id
        self._session_token = session_token
        self._channel = channel
        self._buffer = buffer
        self._sink = sink
        self._max_line_bytes = max_line_bytes
        self._durable_log = durable_log
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name=f'line-reader-{self._world_id}-{self._channel}',
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        import io

        stream = io.TextIOWrapper(
            self._stream,  # type: ignore[arg-type]
            encoding='utf-8',
            errors='replace',
            newline='',
            line_buffering=True,
        )
        while not self._stop.is_set():
            try:
                line = stream.readline()
            except (OSError, ValueError):
                break
            if not line:
                break
            line = line.rstrip('\r\n')
            if len(line) > self._max_line_bytes:
                line = line[: self._max_line_bytes] + ' ...[line truncated]'
            if not ingest_log_line(
                self._buffer, self._channel, line, durable_log=self._durable_log
            ):
                continue
            sink = self._sink
            if sink is not None:
                sink(
                    world_id=self._world_id,
                    session_token=self._session_token,
                    channel=self._channel,
                    line=line,
                )
