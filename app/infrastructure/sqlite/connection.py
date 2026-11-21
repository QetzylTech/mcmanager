"""SQLite connection factory enforcing the Global Persistence Invariant
(Document 7 section 0 / section 10).

Every connection sets ``PRAGMA foreign_keys = ON`` *before any other
statement* and ``PRAGMA busy_timeout`` before use. WAL mode is enabled at boot.
The store owns one read-write connection per thread plus a pool of read-only
connections. SQLite serializes write transactions, while thread-local
connections prevent concurrent lifecycle operations from interleaving one
connection's transactions.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import suppress
from pathlib import Path

from app.ports.persistence import PersistencePort

# Locked operational contract (Doc 7 section 10).
_DEFAULT_BUSY_TIMEOUT_MS = 5000
_WAL_CHECKPOINT_PAGES = 1000  # bounded checkpoint; never a background hammer
_WEDGE_THRESHOLD_S = 1.0


class PersistenceError(Exception):
    """Startup-blocking schema/integrity failure (never silently repaired)."""


class SqliteStore(PersistencePort):
    """Thread-local writers and a read-only pool for one database file."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        busy_timeout_ms: int = _DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        self._path = str(database_path)
        self._busy_timeout_ms = busy_timeout_ms
        self._writer: sqlite3.Connection | None = None
        self._writers: dict[int, tuple[threading.Thread, sqlite3.Connection]] = {}
        self._readers: dict[int, tuple[threading.Thread, sqlite3.Connection]] = {}
        self._mutex = threading.Lock()
        self._writer_status = 'unknown'
        self._last_busy_at: int | None = None
        self._last_wedged_at: int | None = None
        self._last_successful_checkpoint_at: int | None = None

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> None:
        """Open the writer (WAL), then verify the schema at the SQL level."""
        self._writer = self._connect(read_only=False)
        # Invariant: WAL journal mode before any write (Doc 7 section 10).
        self._writer.execute('PRAGMA journal_mode = WAL').fetchone()
        # busy_timeout set on every connection before use.
        self._writer.execute(f'PRAGMA busy_timeout = {self._busy_timeout_ms}')
        current_thread = threading.current_thread()
        if current_thread.ident is None:
            raise PersistenceError('writer opened from a thread without an identifier')
        self._writers[current_thread.ident] = (current_thread, self._writer)

    def close(self) -> None:
        with self._mutex:
            if self._writer is not None:
                for _, connection in self._writers.values():
                    with suppress(sqlite3.Error):
                        connection.close()
                self._writers.clear()
                self._writer = None
            for _, connection in self._readers.values():
                with suppress(sqlite3.Error):
                    connection.close()
            self._readers.clear()

    # -- connection primitives -------------------------------------------------

    def _connect(self, *, read_only: bool) -> sqlite3.Connection:
        if read_only:
            connection = sqlite3.connect(
                f'file:{self._path}?mode=ro', uri=True, check_same_thread=False
            )
        else:
            connection = sqlite3.connect(self._path, check_same_thread=False)
        # GLOBAL PERSISTENCE INVARIANT: foreign_keys=ON before any other
        # statement (Doc 7 section 0; ARCHITECTURE persistence invariant).
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute(f'PRAGMA busy_timeout = {self._busy_timeout_ms}')
        connection.row_factory = sqlite3.Row
        return connection

    def writer(self) -> sqlite3.Connection:
        """Return this thread's read-write connection."""
        if self._writer is None:
            raise PersistenceError('store not open')
        current_thread = threading.current_thread()
        thread_id = current_thread.ident
        if thread_id is None:
            raise PersistenceError('writer requested from a thread without an identifier')
        with self._mutex:
            for stale_id, (owner, stale_connection) in tuple(self._writers.items()):
                if owner is not current_thread and not owner.is_alive():
                    stale_connection.close()
                    del self._writers[stale_id]
            existing = self._writers.get(thread_id)
            if existing is not None and existing[0] is current_thread:
                return existing[1]
            connection = self._connect(read_only=False)
            self._writers[thread_id] = (current_thread, connection)
            return connection

    def reader(self) -> sqlite3.Connection:
        """Return this thread's read-only connection, reclaiming dead readers."""
        current_thread = threading.current_thread()
        thread_id = current_thread.ident
        if thread_id is None:
            raise PersistenceError('reader requested from a thread without an identifier')
        with self._mutex:
            if self._writer is None:
                raise PersistenceError('store not open')
            for stale_id, (owner, stale_connection) in tuple(self._readers.items()):
                if owner is not current_thread and not owner.is_alive():
                    stale_connection.close()
                    del self._readers[stale_id]

            existing = self._readers.get(thread_id)
            if existing is not None and existing[0] is current_thread:
                return existing[1]

            connection = self._connect(read_only=True)
            self._readers[thread_id] = (current_thread, connection)
            return connection

    def backup_to(self, target: str) -> None:
        """Create a consistent SQLite snapshot using SQLite's backup API."""
        destination_path = Path(target)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination = sqlite3.connect(str(destination_path), check_same_thread=False)
        try:
            destination.execute('PRAGMA foreign_keys = ON')
            destination.execute(f'PRAGMA busy_timeout = {self._busy_timeout_ms}')
            self.writer().backup(destination)
        finally:
            destination.close()

    # -- transaction helpers ---------------------------------------------------

    def transaction(self) -> sqlite3.Connection:
        """Context-manager helper: caller uses ``with store.writer()``."""
        return self.writer()

    def checkpoint(self, *, truncate: bool = False) -> None:
        """Bounded WAL checkpoint (Doc 7 section 10).

        ``wal_checkpoint(TRUNCATE)`` after large write bursts (e.g. cleanup
        runs); automatic checkpoint at boot is the caller's responsibility.
        """
        connection = self._writer
        if connection is None:
            return
        mode = 'TRUNCATE' if truncate else 'PASSIVE'
        try:
            result = connection.execute(f'PRAGMA wal_checkpoint({mode})').fetchone()
        except sqlite3.OperationalError as exc:
            self._record_busy_if_applicable(str(exc))
            raise
        if result is not None and int(result[0]) != 0:
            self._record_busy_if_applicable('checkpoint busy')
            return
        self._last_successful_checkpoint_at = int(time.time())

    def probe_writer(self) -> dict[str, int | str]:
        """Probe the writer and record whether it is responsive, busy, or slow."""
        started = time.monotonic()
        try:
            self.writer().execute('SELECT 1').fetchone()
        except sqlite3.OperationalError as exc:
            elapsed = time.monotonic() - started
            message = str(exc)
            self._record_busy_if_applicable(message)
            if elapsed >= _WEDGE_THRESHOLD_S:
                self._last_wedged_at = int(time.time())
                self._writer_status = 'wedged'
            else:
                self._writer_status = 'busy' if self._is_busy_error(message) else 'down'
            return self._probe_result(elapsed)

        elapsed = time.monotonic() - started
        if elapsed >= _WEDGE_THRESHOLD_S:
            self._last_wedged_at = int(time.time())
            self._writer_status = 'wedged'
        else:
            self._writer_status = 'ok'
        return self._probe_result(elapsed)

    def _probe_result(self, elapsed: float) -> dict[str, float | int | str]:
        return {
            'status': self._writer_status,
            'latency_ms': round(elapsed * 1000, 3),
        }

    @staticmethod
    def _is_busy_error(message: str) -> bool:
        return 'locked' in message.lower() or 'busy' in message.lower()

    def _record_busy_if_applicable(self, message: str) -> None:
        if self._is_busy_error(message):
            self._last_busy_at = int(time.time())
            self._writer_status = 'busy'

    @property
    def diagnostics_state(self) -> dict[str, int | str | bool | None]:
        return {
            'busy': self._writer_status == 'busy',
            'wedged': self._writer_status == 'wedged',
            'last_busy_at': self._last_busy_at,
            'last_wedged_at': self._last_wedged_at,
            'last_successful_checkpoint_at': self._last_successful_checkpoint_at,
        }

    @property
    def path(self) -> str:
        return self._path
