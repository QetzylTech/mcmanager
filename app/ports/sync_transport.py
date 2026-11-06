"""Transport boundary for offsite backup uploads."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SyncTransportPort(Protocol):
    """Upload one local artifact to a configured target."""

    def upload_file(self, target_id: str, source_path: str | Path) -> None: ...
