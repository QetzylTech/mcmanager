"""Persistence connection access required by application services.

The port preserves the current transaction-aware SQL workflow while keeping
services independent of the concrete SQLite store adapter. New persistence
behavior should prefer service-owned repositories over adding SQL to services.
"""

from __future__ import annotations

import sqlite3
from typing import Protocol, runtime_checkable


@runtime_checkable
class PersistencePort(Protocol):
    """Provide read-only and serialized read-write database connections."""

    @property
    def path(self) -> str:
        """Return the configured database path for diagnostics."""
        ...

    def reader(self) -> sqlite3.Connection:
        """Return a read-only connection for queries."""
        ...

    def writer(self) -> sqlite3.Connection:
        """Return the serialized read-write connection."""
        ...

    def backup_to(self, target: str) -> None:
        """Write a transactionally consistent database snapshot to target."""
        ...
