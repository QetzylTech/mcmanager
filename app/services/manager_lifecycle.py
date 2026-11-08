"""Documented manager-level lifecycle operations."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from app.domain.value_objects import ActorType, OperationType, TriggerType
from app.ports.backup_engine import BackupEnginePort
from app.ports.clock import Clock
from app.ports.persistence import PersistencePort
from app.services.configuration import ConfigurationService
from app.services.operations import OperationInput, OperationService


class ManagerLifecycleService:
    """Own manager backup operation creation and SQLite snapshot registration."""

    def __init__(
        self,
        store: PersistencePort,
        clock: Clock,
        operations: OperationService,
        configuration: ConfigurationService,
        backup_engine: BackupEnginePort,
    ) -> None:
        self._store = store
        self._clock = clock
        self._operations = operations
        self._configuration = configuration
        self._backup_engine = backup_engine

    def request_backup(
        self, *, actor_user_id: str, idempotency_key: str
    ) -> tuple[dict[str, Any], bool]:
        """Create or replay a durable manager-backup operation."""
        return self._operations.create_with_replay(
            OperationInput(
                op_type=OperationType.BACKUP,
                actor_type=ActorType.USER,
                actor_user_id=actor_user_id,
                idempotency_key=idempotency_key,
                data={"scope": "manager"},
            )
        )

    def execute_backup(self, *, operation_id: str) -> dict[str, Any]:
        """Snapshot the manager database and register its artifact on success."""
        try:
            settings = self._configuration.resolve_global()
        except KeyError:
            settings = {}
        backup_root = Path(
            str(
                settings.get("backup_root_path")
                or Path(self._store.path).with_suffix(".backups")
            )
        )
        manager_directory = backup_root / "manager"
        manager_directory.mkdir(parents=True, exist_ok=True)
        artifact_id = f"ba_{uuid.uuid4().hex[:16]}"
        final_path = manager_directory / f"{artifact_id}.zip"
        part_path = final_path.with_suffix(".zip.part")
        connection = None

        try:
            with tempfile.TemporaryDirectory(
                prefix=f".{artifact_id}-", dir=manager_directory
            ) as snapshot_directory:
                snapshot_path = Path(snapshot_directory) / "manager.sqlite3"
                self._store.backup_to(str(snapshot_path))
                self._backup_engine.create_archive(Path(snapshot_directory), part_path)
            self._backup_engine.verify_archive(part_path)
            checksum = self._backup_engine.sha256(part_path)
            os.replace(part_path, final_path)
            size_bytes = final_path.stat().st_size

            connection = self._store.writer()
            connection.execute(
                """
                INSERT INTO backup_artifacts (
                    artifact_id, world_id, category, storage_path, size_bytes,
                    checksum, suspect, operation_id, deleted_at, deleted_by, created_at
                ) VALUES (?, NULL, ?, ?, ?, ?, 0, ?, NULL, NULL, ?)
                """,
                (
                    artifact_id,
                    TriggerType.MANAGER_CONFIG.value,
                    str(final_path),
                    size_bytes,
                    checksum,
                    operation_id,
                    int(self._clock.now()),
                ),
            )
            connection.commit()
        except Exception:
            if connection is not None:
                connection.rollback()
            part_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            raise

        return {
            "artifact_id": artifact_id,
            "checksum": checksum,
            "size_bytes": size_bytes,
        }
