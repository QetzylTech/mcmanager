"""Native ZIP + SHA-256 archive implementation."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from app.ports.backup_engine import BackupEnginePort


class NativeBackupEngine(BackupEnginePort):
    """Create and verify portable ZIP artifacts without registering metadata."""

    def create_archive(self, source_dir: Path, target_zip_path: Path) -> int:
        root = source_dir.resolve()
        skipped = 0
        try:
            with zipfile.ZipFile(
                target_zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                for path in sorted(source_dir.rglob('*')):
                    resolved = path.resolve()
                    if not self._is_within(resolved, root):
                        skipped += 1
                        continue
                    if (
                        path.is_dir()
                        or path.name.endswith('.part')
                        or path.name in {'mcmanager.lock', 'mcmanager.pid'}
                    ):
                        continue
                    archive.write(path, resolved.relative_to(root).as_posix())
        except Exception:
            target_zip_path.unlink(missing_ok=True)
            raise
        return skipped

    def sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()

    def verify_archive(self, path: Path) -> None:
        with zipfile.ZipFile(path, 'r') as archive:
            bad = archive.testzip()
        if bad is not None:
            raise ValueError(f'archive member failed CRC: {bad}')

    def extract_archive(self, archive_path: Path, target_dir: Path) -> None:
        root = target_dir.resolve()
        with zipfile.ZipFile(archive_path, 'r') as archive:
            for member in archive.infolist():
                destination = (target_dir / member.filename).resolve()
                if not self._is_within(destination, root):
                    raise ValueError('archive path escapes staging directory')
                archive.extract(member, target_dir)

    def _is_within(self, path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False
