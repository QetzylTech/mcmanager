"""Local filesystem adapter for storage and path-policy operations."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.ports.filesystem import DiskUsage, FilesystemPort


class LocalFilesystem(FilesystemPort):
    """Host filesystem adapter."""

    def disk_usage(self, path: Path) -> DiskUsage:
        usage = shutil.disk_usage(path)
        return DiskUsage(usage.total, usage.used, usage.free)

    def modified_at(self, path: Path) -> float:
        return path.stat().st_mtime

    def tree_size(self, path: Path) -> int:
        total = 0
        root = path.resolve()
        pending = [(path, frozenset({root}))]
        while pending:
            directory, ancestors = pending.pop()
            try:
                children = directory.iterdir()
            except OSError:
                continue
            for item in children:
                try:
                    resolved = item.resolve()
                    if not self.is_within(resolved, root):
                        continue
                    if item.name.endswith('.part') or item.name in {
                        'mcmanager.lock',
                        'mcmanager.pid',
                    }:
                        continue
                    if item.is_dir():
                        if resolved not in ancestors:
                            pending.append((item, ancestors | {resolved}))
                        continue
                    total += item.stat().st_size
                except (OSError, RuntimeError):
                    continue
        return total

    def is_within(self, path: Path, root: Path) -> bool:
        try:
            resolved_path = path.resolve()
            resolved_root = root.resolve()
            resolved_path.relative_to(resolved_root)
            return True
        except (OSError, RuntimeError, ValueError):
            return False
