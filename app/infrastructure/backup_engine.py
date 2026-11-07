"""Native ZIP + SHA-256 archive implementation."""

from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.ports.backup_engine import BackupEnginePort


class NativeBackupEngine(BackupEnginePort):
    """Create and verify portable ZIP artifacts without registering metadata."""

    def create_archive(self, source_dir: Path, target_zip_path: Path) -> int:
        root = source_dir.resolve()
        staged_path = target_zip_path.with_name(f'{target_zip_path.name}.part')
        skipped = 0
        try:
            with zipfile.ZipFile(
                staged_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                pending = [(source_dir, Path(), frozenset({root}))]
                while pending:
                    directory, relative_dir, ancestors = pending.pop()
                    for path in sorted(directory.iterdir()):
                        try:
                            resolved = path.resolve()
                        except (OSError, RuntimeError):
                            skipped += 1
                            continue
                        if not self._is_within(resolved, root):
                            skipped += 1
                            continue
                        if path.name.endswith('.part') or path.name in {
                            'mcmanager.lock',
                            'mcmanager.pid',
                        }:
                            continue
                        relative_path = relative_dir / path.name
                        if path.is_dir():
                            if resolved in ancestors:
                                skipped += 1
                                continue
                            pending.append(
                                (path, relative_path, ancestors | {resolved})
                            )
                            continue
                        archive.write(path, relative_path.as_posix())
            with staged_path.open('rb+') as handle:
                handle.flush()
                os.fsync(handle.fileno())
            self.verify_archive(staged_path)
            os.replace(staged_path, target_zip_path)
        except Exception:
            staged_path.unlink(missing_ok=True)
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
            for member in archive.infolist():
                self._validate_member_path(member.filename)
            bad = archive.testzip()
        if bad is not None:
            raise ValueError(f'archive member failed CRC: {bad}')

    def extract_archive(self, archive_path: Path, target_dir: Path) -> None:
        root = target_dir.resolve()
        try:
            with zipfile.ZipFile(archive_path, 'r') as archive:
                for member in archive.infolist():
                    self._validate_member_path(member.filename)
                    destination = (target_dir / member.filename).resolve()
                    if not self._is_within(destination, root):
                        raise ValueError('archive path escapes staging directory')
                archive.extractall(target_dir)
        except Exception:
            if target_dir.is_dir() and not target_dir.is_symlink():
                shutil.rmtree(target_dir, ignore_errors=True)
            raise

    def _validate_member_path(self, member_name: str) -> None:
        posix_path = PurePosixPath(member_name.replace('\\', '/'))
        windows_path = PureWindowsPath(member_name)
        if (
            not member_name
            or posix_path.is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or '..' in posix_path.parts
        ):
            raise ValueError('archive path escapes staging directory')

    def _is_within(self, path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False
