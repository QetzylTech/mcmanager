"""Filesystem operations required by backup and storage policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class DiskUsage:
    total: int
    used: int
    free: int


class FilesystemPort(Protocol):
    """Narrow filesystem boundary for path policy and capacity checks."""

    def disk_usage(self, path: Path) -> DiskUsage: ...

    def modified_at(self, path: Path) -> float: ...

    def tree_size(self, path: Path) -> int: ...

    def is_within(self, path: Path, root: Path) -> bool: ...
