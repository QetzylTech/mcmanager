"""Durable execution of backup, restore, cleanup, and sync operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.domain.value_objects import OperationStatus, OperationType, TriggerType
from app.ports.clock import Clock
from app.ports.persistence import PersistencePort
from app.services.backup import BackupIntegrityError, BackupService
from app.services.cleanup import CleanupService, RetentionError
from app.services.configuration import ConfigurationService
from app.services.operations import OperationService
from app.services.restore import RestorePreconditionError, RestoreService
from app.services.sync import SyncError, SyncService


class CatalogOperationDispatcher:
    """Claim and run the durable catalog operations using their owning services."""

    _OPERATION_TYPES = (
        OperationType.BACKUP,
        OperationType.RESTORE,
        OperationType.CLEANUP,
        OperationType.SYNC,
    )

    def __init__(
        self,
        store: PersistencePort,
        clock: Clock,
        operations: OperationService,
        configuration: ConfigurationService,
        backups: BackupService,
        restore: RestoreService,
        cleanup: CleanupService,
        sync: SyncService,
    ) -> None:
        self._store = store
        self._clock = clock
        self._operations = operations
        self._configuration = configuration
        self._backups = backups
        self._restore = restore
        self._cleanup = cleanup
        self._sync = sync

    def dispatch_queued_operations(
        self, operation_types: tuple[OperationType, ...] | None = None
    ) -> list[str]:
        dispatched: list[str] = []
        for operation in self._operations.list_queued(
            operation_types or self._OPERATION_TYPES
        ):
            claimed = self._operations.claim_queued(operation["op_id"])
            if claimed is None:
                continue
            dispatched.append(claimed["op_id"])
            try:
                result = self._run(claimed)
                current = self._operations.get(claimed["op_id"])
                if current is not None and current["status"] not in self._terminal_statuses():
                    self._operations.transition(
                        claimed["op_id"], OperationStatus.COMPLETED, data=result
                    )
            except Exception as exc:
                current = self._operations.get(claimed["op_id"])
                if current is not None and current["status"] not in self._terminal_statuses():
                    self._operations.transition(
                        claimed["op_id"],
                        OperationStatus.FAILED,
                        error_code=self._error_code(claimed, exc),
                        message=str(exc),
                    )
        return dispatched

    def resolve_sync_target(self, world_id: str | None) -> str | None:
        if world_id is not None:
            row = self._store.reader().execute(
                """
                SELECT sync_target_id FROM sync_targets
                WHERE scope = 'world' AND world_id = ? AND enabled = 1 AND deleted_at IS NULL
                ORDER BY created_at DESC LIMIT 1
                """,
                (world_id,),
            ).fetchone()
            if row is not None:
                return str(row["sync_target_id"])
        row = self._store.reader().execute(
            """
            SELECT sync_target_id FROM sync_targets
            WHERE scope = 'global' AND world_id IS NULL AND enabled = 1 AND deleted_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
        return str(row["sync_target_id"]) if row is not None else None

    @staticmethod
    def _terminal_statuses() -> frozenset[str]:
        return frozenset(
            {
                OperationStatus.COMPLETED.value,
                OperationStatus.FAILED.value,
                OperationStatus.CANCELLED.value,
                OperationStatus.TIMED_OUT.value,
            }
        )

    def _run(self, operation: dict[str, Any]) -> dict[str, Any]:
        try:
            data = json.loads(operation.get("data_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            data = {}
        op_type = OperationType(operation["op_type"])
        if op_type is OperationType.BACKUP:
            world = self._world(operation["world_id"])
            result = self._backups.create_world_backup(
                world_id=world["world_id"],
                world_dir=self._world_directory(world),
                backup_dir=self._backup_directory(world["world_id"]),
                operation_id=operation["op_id"],
                category=TriggerType(data.get("category", TriggerType.MANUAL.value)),
                running=world["state"] == "running",
            )
            return {
                "artifact_id": result.artifact_id,
                "checksum": result.checksum,
                "size_bytes": result.size_bytes,
                "skipped_paths": result.skipped_paths,
            }
        if op_type is OperationType.RESTORE:
            world = self._world(operation["world_id"])
            result = self._restore.restore(
                world_id=world["world_id"],
                artifact_id=data["artifact_id"],
                world_dir=self._world_directory(world),
                backup_dir=self._backup_directory(world["world_id"]),
                staging_dir=self._backup_directory(world["world_id"])
                / ".staging"
                / operation["op_id"],
                operation_id=operation["op_id"],
                operator_user_id=operation["actor_user_id"],
                was_running=False,
                rollback_of_restore_id=data.get("rollback_of_restore_id"),
            )
            return {
                "restore_id": result.restore_id,
                "outcome": result.outcome,
                "rollback_operation_id": result.rollback_operation_id,
            }
        if op_type is OperationType.CLEANUP:
            if data.get("action") == "delete_artifact":
                artifact_id = data["artifact_id"]
                self._cleanup.delete_backup_artifact(
                    artifact_id,
                    deleted_by=operation["actor_user_id"] or "system",
                    force=bool(data.get("force")),
                )
                return {"artifact_id": artifact_id, "deleted": True}
            return self._cleanup.evaluate_and_execute_cleanup(
                op_id=operation["op_id"],
                world_id=operation["world_id"],
                dry_run=not bool(data.get("wet")),
                older_than_days=int(data.get("older_than_days", 3)),
                keep_per_category=int(data.get("keep_per_category", 3)),
                elevated_confirmation=bool(data.get("elevated_confirmation")),
                scope=str(data.get("scope", "backups")),
                deleted_by=operation["actor_user_id"] or "system",
                dry_run_operation_id=data.get("dry_run_operation_id"),
            )
        if op_type is OperationType.SYNC:
            target_id = data.get("sync_target_id") or self.resolve_sync_target(
                operation["world_id"]
            )
            if not target_id:
                raise SyncError("SYNC_TARGET_UNRESOLVED")
            sync_id = self._sync.dispatch_sync(
                data["artifact_id"], target_id, operation_id=operation["op_id"]
            )
            return {"sync_id": sync_id, "artifact_id": data["artifact_id"]}
        raise ValueError(f"unsupported catalog operation: {op_type.value}")

    def _world(self, world_id: str | None) -> dict[str, Any]:
        if world_id is None:
            raise ValueError("WORLD_NOT_FOUND")
        row = self._store.reader().execute(
            "SELECT * FROM world_instances WHERE world_id = ? AND deleted_at IS NULL",
            (world_id,),
        ).fetchone()
        if row is None:
            raise ValueError("WORLD_NOT_FOUND")
        return dict(row)

    def _world_directory(self, world: dict[str, Any]) -> Path:
        if world["addressing_strategy"] == "path":
            candidate = Path(world["addressing_value"])
            if candidate.is_absolute():
                return candidate
        settings = self._configuration.resolve_effective(world["world_id"])
        return Path(str(settings["minecraft_root_path"] or "worlds")) / str(
            world["display_name"]
        )

    def _backup_directory(self, world_id: str) -> Path:
        settings = self._configuration.resolve_effective(world_id)
        return Path(str(settings["backup_root_path"] or "backups")) / world_id

    @staticmethod
    def _error_code(operation: dict[str, Any], exc: Exception) -> str:
        message = str(exc)
        op_type = operation["op_type"]
        if isinstance(exc, RestorePreconditionError):
            return exc.code
        if isinstance(exc, BackupIntegrityError):
            if "not found" in message.lower():
                return "BACKUP_ARTIFACT_NOT_FOUND"
            if "checksum" in message.lower():
                return "BACKUP_INVALID_CHECKSUM"
            return "RESTORE_ARTIFACT_INVALID" if op_type == OperationType.RESTORE.value else "BACKUP_FAILED"
        if isinstance(exc, RetentionError):
            if "BACKUP_RETENTION_GUARD" in message:
                return "BACKUP_RETENTION_GUARD"
            if "BLAST_RADIUS" in message:
                return "CLEANUP_BLAST_RADIUS"
            if "PREVIEW" in message or "STALE" in message:
                return "CLEANUP_PREVIEW_REQUIRED"
            if "floor" in message.lower():
                return "CLEANUP_POLICY_FLOOR"
        if isinstance(exc, KeyError) and op_type == OperationType.CLEANUP.value:
            try:
                data = json.loads(operation.get("data_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                data = {}
            if data.get("action") == "delete_artifact":
                return "BACKUP_ARTIFACT_NOT_FOUND"
        if isinstance(exc, SyncError):
            if "CAP_EXCEEDED" in message:
                return "SYNC_CAP_EXCEEDED"
            return "SYNC_TARGET_UNRESOLVED" if "TARGET" in message else "SYNC_PERMANENT"
        if "STORAGE_GUARD_FAILED" in message:
            return "STORAGE_GUARD_TRIPPED"
        if "WORLD_NOT_FOUND" in message:
            return "WORLD_NOT_FOUND"
        return "BACKUP_FAILED" if op_type == OperationType.BACKUP.value else "OP_EXECUTION_FAILED"
