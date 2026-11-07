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
    """Platform-neutral filesystem boundary for path and capacity policy."""

    def disk_usage(self, path: Path) -> DiskUsage:
        """Return total, used, and free host capacity for the containing volume."""
        ...

    def modified_at(self, path: Path) -> float:
        """Return the file modification time as epoch seconds."""
        ...

    def tree_size(self, path: Path) -> int:
        """Estimate bytes under a tree without counting paths escaping its root."""
        ...

    def is_within(self, path: Path, root: Path) -> bool:
        """Check containment after resolving traversal and symlink components."""
        ...
