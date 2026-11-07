"""Transport boundary for offsite backup uploads."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SyncTransportError(Exception):
    """Base class for classified sync transport failures."""


class TransientSyncTransportError(SyncTransportError):
    """A transport failure that may succeed on retry."""


class PermanentSyncTransportError(SyncTransportError):
    """A transport failure that should not be retried automatically."""


class SyncTransportPort(Protocol):
    """Upload one local artifact to a configured target."""

    def upload_file(self, target_id: str, source_path: str | Path) -> None: ...
