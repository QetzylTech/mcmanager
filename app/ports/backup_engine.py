"""Portable backup archive engine contract."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class BackupEnginePort(Protocol):
    """Archive operations used by BackupService."""

    def create_archive(self, source_dir: Path, target_zip_path: Path) -> int: ...

    def sha256(self, path: Path) -> str: ...

    def verify_archive(self, path: Path) -> None: ...

    def extract_archive(self, archive_path: Path, target_dir: Path) -> None: ...
