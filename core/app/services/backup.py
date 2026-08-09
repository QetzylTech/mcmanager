"""Native ZIP + SHA-256 backup engine (Gate 4)."""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.domain.value_objects import TriggerType
from app.infrastructure.sqlite.connection import SqliteStore
from app.ports.clock import Clock


class SaveCoordinator(Protocol):
    """RCON-backed save coordination for running worlds."""

    def suspend_autosave(self, world_id: str) -> None: ...

    def flush(self, world_id: str) -> None: ...

    def resume_autosave(self, world_id: str) -> None: ...


@dataclass(frozen=True)
class BackupResult:
    artifact_id: str
    storage_path: str
    checksum: str
    size_bytes: int
    skipped_paths: int


class BackupIntegrityError(Exception):
    """Raised when an artifact cannot be safely created or validated."""


class BackupService:
    """Creates portable ZIP artifacts and registers rows only on success."""

    def __init__(self, store: SqliteStore, clock: Clock, save_coordinator: SaveCoordinator | None = None) -> None:
        self._store = store
        self._clock = clock
        self._save_coordinator = save_coordinator

    def create_world_backup(
        self,
        *,
        world_id: str,
        world_dir: str | Path,
        backup_dir: str | Path,
        operation_id: str,
        category: TriggerType,
        running: bool = False,
    ) -> BackupResult:
        """Capture a world directory as ZIP, with RCON save suspension when running."""
        if running and self._save_coordinator is None:
            raise BackupIntegrityError('running-world backup requires save coordination')

        if running:
            try:
                self._save_coordinator.suspend_autosave(world_id)
                self._save_coordinator.flush(world_id)
                result = self._write_and_register(
                    world_id=world_id,
                    source_dir=Path(world_dir),
                    backup_dir=Path(backup_dir),
                    operation_id=operation_id,
                    category=category,
                )
                return result
            finally:
                self._save_coordinator.resume_autosave(world_id)
        return self._write_and_register(
            world_id=world_id,
            source_dir=Path(world_dir),
            backup_dir=Path(backup_dir),
            operation_id=operation_id,
            category=category,
        )

    def validate_artifact(self, artifact_id: str) -> dict:
        row = self._store.reader().execute(
            'SELECT * FROM backup_artifacts WHERE artifact_id = ?', (artifact_id,)
        ).fetchone()
        if row is None:
            raise BackupIntegrityError(f'backup artifact not found: {artifact_id}')
        path = Path(row['storage_path'])
        if not path.exists():
            self._flag_suspect(artifact_id)
            raise BackupIntegrityError('artifact file missing')
        checksum = self._sha256(path)
        if checksum != row['checksum']:
            self._flag_suspect(artifact_id)
            raise BackupIntegrityError('artifact checksum mismatch')
        try:
            with zipfile.ZipFile(path, 'r') as archive:
                bad = archive.testzip()
        except zipfile.BadZipFile as exc:
            self._flag_suspect(artifact_id)
            raise BackupIntegrityError('artifact is not a valid zip') from exc
        if bad is not None:
            self._flag_suspect(artifact_id)
            raise BackupIntegrityError(f'artifact member failed CRC: {bad}')
        return dict(row)

    def extract_to_staging(self, artifact_id: str, staging_dir: str | Path) -> None:
        row = self.validate_artifact(artifact_id)
        target = Path(staging_dir)
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        with zipfile.ZipFile(row['storage_path'], 'r') as archive:
            for member in archive.infolist():
                destination = (target / member.filename).resolve()
                if not self._is_relative_to(destination, target.resolve()):
                    raise BackupIntegrityError('artifact path escapes staging directory')
                archive.extract(member, target)

    def _write_and_register(
        self,
        *,
        world_id: str,
        source_dir: Path,
        backup_dir: Path,
        operation_id: str,
        category: TriggerType,
    ) -> BackupResult:
        artifact_id = f'ba_{uuid.uuid4().hex[:16]}'
        backup_dir.mkdir(parents=True, exist_ok=True)
        final_path = backup_dir / f'{world_id}-{artifact_id}.zip'
        part_path = final_path.with_suffix(final_path.suffix + '.part')
        skipped = self._write_zip(source_dir, part_path)
        checksum = self._sha256(part_path)
        self._verify_zip(part_path)
        os.replace(part_path, final_path)
        size = final_path.stat().st_size
        if self._sha256(final_path) != checksum:
            final_path.unlink(missing_ok=True)
            raise BackupIntegrityError('post-rename checksum mismatch')

        connection = self._store.writer()
        connection.execute(
            """
            INSERT INTO backup_artifacts (
                artifact_id, world_id, category, storage_path, size_bytes,
                checksum, suspect, operation_id, deleted_at, deleted_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, NULL, NULL, ?)
            """,
            (
                artifact_id,
                world_id,
                category.value,
                str(final_path),
                size,
                checksum,
                operation_id,
                int(self._clock.now()),
            ),
        )
        connection.commit()
        return BackupResult(artifact_id, str(final_path), checksum, size, skipped)

    def _write_zip(self, source_dir: Path, part_path: Path) -> int:
        root = source_dir.resolve()
        skipped = 0
        try:
            with zipfile.ZipFile(part_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for path in sorted(source_dir.rglob('*')):
                    resolved = path.resolve()
                    if not self._is_relative_to(resolved, root):
                        skipped += 1
                        continue
                    if path.is_dir() or path.name.endswith('.part') or path.name in {'mcmanager.lock', 'mcmanager.pid'}:
                        continue
                    archive.write(path, resolved.relative_to(root).as_posix())
        except Exception:
            part_path.unlink(missing_ok=True)
            raise
        return skipped

    def _verify_zip(self, path: Path) -> None:
        with zipfile.ZipFile(path, 'r') as archive:
            bad = archive.testzip()
        if bad is not None:
            path.unlink(missing_ok=True)
            raise BackupIntegrityError(f'created artifact member failed CRC: {bad}')

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()

    def _flag_suspect(self, artifact_id: str) -> None:
        connection = self._store.writer()
        connection.execute('UPDATE backup_artifacts SET suspect = 1 WHERE artifact_id = ?', (artifact_id,))
        connection.commit()

    def _is_relative_to(self, path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False
