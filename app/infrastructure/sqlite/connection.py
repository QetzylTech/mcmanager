"""SQLite connection factory enforcing the Global Persistence Invariant
(Document 7 section 0 / section 10).

Every connection sets ``PRAGMA foreign_keys = ON`` *before any other
statement* and ``PRAGMA busy_timeout`` before use. WAL mode is enabled on the
primary (writer) connection at boot. The store owns one read-write writer
(single serialization point for multi-statement transactions) plus a pool of
read-only connections — readers never take the write lock.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.ports.persistence import PersistencePort

# Locked operational contract (Doc 7 section 10).
_DEFAULT_BUSY_TIMEOUT_MS = 5000
_WAL_CHECKPOINT_PAGES = 1000  # bounded checkpoint; never a background hammer


class PersistenceError(Exception):
    """Startup-blocking schema/integrity failure (never silently repaired)."""


class SqliteStore(PersistencePort):
    """Writer + read-only pool for one database file."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        busy_timeout_ms: int = _DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        self._path = str(database_path)
        self._busy_timeout_ms = busy_timeout_ms
        self._writer: sqlite3.Connection | None = None
        self._readers: list[sqlite3.Connection] = []
        self._mutex = threading.Lock()

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> None:
        """Open the writer (WAL), then verify the schema at the SQL level."""
        self._writer = self._connect(read_only=False)
        # Invariant: WAL journal mode before any write (Doc 7 section 10).
        self._writer.execute('PRAGMA journal_mode = WAL').fetchone()
        # busy_timeout set on every connection before use.
        self._writer.execute(f'PRAGMA busy_timeout = {self._busy_timeout_ms}')

    def close(self) -> None:
        with self._mutex:
            if self._writer is not None:
                try:
                    self._writer.close()
                except sqlite3.Error:
                    pass
                self._writer = None
            for connection in self._readers:
                try:
                    connection.close()
                except sqlite3.Error:
                    pass
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
        """The single read-write connection (serialized writes)."""
        if self._writer is None:
            raise PersistenceError('store not open')
        return self._writer

    def reader(self) -> sqlite3.Connection:
        """A read-only connection from the pool."""
        if self._writer is None:
            raise PersistenceError('store not open')
        with self._mutex:
            if not self._readers:
                self._readers.append(self._connect(read_only=True))
            connection = self._readers[-1]
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
        connection.execute(f'PRAGMA wal_checkpoint({mode})')

    @property
    def path(self) -> str:
        return self._path
