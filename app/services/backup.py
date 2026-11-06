"""Native ZIP + SHA-256 backup engine (Gate 4)."""

from __future__ import annotations

import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.domain.tuning import STORAGE_GUARD_OVERFLOW_PCT, STORAGE_GUARD_RESERVE_BYTES
from app.domain.value_objects import TriggerType
from app.infrastructure.backup_engine import NativeBackupEngine
from app.infrastructure.filesystem import LocalFilesystem
from app.infrastructure.sqlite.connection import SqliteStore
from app.ports.backup_engine import BackupEnginePort
from app.ports.clock import Clock
from app.ports.filesystem import FilesystemPort


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

    LEVEL_DAT_MAX_AGE_SECONDS = 30

    def __init__(
        self,
        store: SqliteStore,
        clock: Clock,
        save_coordinator: SaveCoordinator | None = None,
        engine: BackupEnginePort | None = None,
        filesystem: FilesystemPort | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._save_coordinator = save_coordinator
        self._engine = engine or NativeBackupEngine()
        self._filesystem = filesystem or LocalFilesystem()

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
        coordinator = self._save_coordinator
        if running and coordinator is None:
            raise BackupIntegrityError('running-world backup requires save coordination')
        source_dir = Path(world_dir)
        backup_path = Path(backup_dir)
        self._enforce_storage_guard(source_dir, backup_path)

        if running:
            assert coordinator is not None
            try:
                level_dat = source_dir / 'level.dat'
                coordinator.suspend_autosave(world_id)
                coordinator.flush(world_id)
                self._verify_level_dat_flush(level_dat)
                result = self._write_and_register(
                    world_id=world_id,
                    source_dir=source_dir,
                    backup_dir=backup_path,
                    operation_id=operation_id,
                    category=category,
                )
                return result
            finally:
                coordinator.resume_autosave(world_id)
        return self._write_and_register(
            world_id=world_id,
            source_dir=source_dir,
            backup_dir=backup_path,
            operation_id=operation_id,
            category=category,
        )

    def validate_artifact(self, artifact_id: str) -> dict[str, Any]:
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
            self._engine.verify_archive(path)
        except Exception as exc:
            self._flag_suspect(artifact_id)
            raise BackupIntegrityError('artifact is not a valid zip') from exc
        return dict(row)

    def extract_to_staging(self, artifact_id: str, staging_dir: str | Path) -> None:
        row = self.validate_artifact(artifact_id)
        target = Path(staging_dir)
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        try:
            self._engine.extract_archive(Path(row['storage_path']), target)
        except ValueError as exc:
            raise BackupIntegrityError(str(exc)) from exc

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
        return self._engine.create_archive(source_dir, part_path)

    def _verify_zip(self, path: Path) -> None:
        try:
            self._engine.verify_archive(path)
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise BackupIntegrityError('created artifact failed archive verification') from exc

    def _sha256(self, path: Path) -> str:
        return self._engine.sha256(path)

    def _verify_level_dat_flush(self, level_dat: Path) -> None:
        try:
            modified_at = self._filesystem.modified_at(level_dat)
        except OSError as exc:
            raise BackupIntegrityError('LEVEL_DAT_FLUSH_UNVERIFIED') from exc
        age = time.time() - modified_at
        if age < -5 or age > self.LEVEL_DAT_MAX_AGE_SECONDS:
            raise BackupIntegrityError('LEVEL_DAT_FLUSH_UNVERIFIED')

    def _enforce_storage_guard(self, source_dir: Path, backup_dir: Path) -> None:
        estimated_size = self._filesystem.tree_size(source_dir)
        overflow_reserve = int(
            estimated_size * STORAGE_GUARD_OVERFLOW_PCT / 100
        )
        required_free = estimated_size + max(
            STORAGE_GUARD_RESERVE_BYTES, overflow_reserve
        )
        usage_path = backup_dir
        while not usage_path.exists() and usage_path.parent != usage_path:
            usage_path = usage_path.parent
        if self._filesystem.disk_usage(usage_path).free < required_free:
            raise BackupIntegrityError('STORAGE_GUARD_FAILED')

    def _flag_suspect(self, artifact_id: str) -> None:
        connection = self._store.writer()
        connection.execute('UPDATE backup_artifacts SET suspect = 1 WHERE artifact_id = ?', (artifact_id,))
        connection.commit()

    def _is_relative_to(self, path: Path, root: Path) -> bool:
        return self._filesystem.is_within(path, root)
