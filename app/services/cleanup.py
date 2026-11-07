"""Cleanup and retention enforcement for Tier 2 rows/artifacts (Gate 4)."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.domain.tuning import (
    CLEANUP_AGE_FLOOR_DAYS,
    CLEANUP_BLAST_RADIUS_CAP,
    CLEANUP_COUNT_FLOOR,
)
from app.domain.value_objects import OperationStatus
from app.ports.clock import Clock
from app.ports.persistence import PersistencePort
from app.services.operations import OperationService


class RetentionError(Exception):
    """Raised when cleanup would violate retention safety rules."""


@dataclass(frozen=True)
class CleanupCandidate:
    artifact_id: str
    storage_path: str
    world_id: str | None
    category: str
    created_at: int


class CleanupService:
    """Only service allowed to physically remove Tier 2 backup artifacts."""

    def __init__(
        self, store: PersistencePort, clock: Clock, operations: OperationService | None = None
    ) -> None:
        self._store = store
        self._clock = clock
        self._operations = operations or OperationService(store, clock)
        self._previews: dict[tuple[str | None, str], str] = {}

    def delete_backup_artifact(
        self, artifact_id: str, *, deleted_by: str, force: bool = False
    ) -> None:
        """Remove an artifact file while preserving retention floors unless forced."""
        row = self.validate_backup_artifact_delete(artifact_id, force=force)
        Path(row["storage_path"]).unlink(missing_ok=True)
        connection = self._store.writer()
        connection.execute(
            "UPDATE backup_artifacts SET deleted_at = ?, deleted_by = ? "
            "WHERE artifact_id = ? AND deleted_at IS NULL",
            (int(self._clock.now()), deleted_by, artifact_id),
        )
        connection.commit()

    def validate_backup_artifact_delete(
        self, artifact_id: str, *, force: bool = False
    ) -> dict[str, Any]:
        """Check artifact existence and retention rules without mutating state."""
        row = self._store.reader().execute(
            "SELECT * FROM backup_artifacts WHERE artifact_id = ? AND deleted_at IS NULL",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        siblings = self._store.reader().execute(
            """
            SELECT artifact_id, suspect
            FROM backup_artifacts
            WHERE world_id IS ? AND category = ? AND deleted_at IS NULL
            ORDER BY created_at DESC
            """,
            (row["world_id"], row["category"]),
        ).fetchall()
        remaining = [item for item in siblings if item["artifact_id"] != artifact_id]
        violates_floor = len(remaining) < CLEANUP_COUNT_FLOOR or not any(
            item["suspect"] == 0 for item in remaining
        )
        if violates_floor and not force:
            raise RetentionError("BACKUP_RETENTION_GUARD")
        return dict(row)

    def backup_candidates(
        self,
        *,
        older_than_days: int,
        keep_per_category: int = CLEANUP_COUNT_FLOOR,
        world_id: str | None = None,
    ) -> list[CleanupCandidate]:
        if older_than_days < CLEANUP_AGE_FLOOR_DAYS:
            raise RetentionError('age floor is 3 days')
        if keep_per_category < CLEANUP_COUNT_FLOOR:
            raise RetentionError('count floor is 3 per world/category')
        cutoff = int(self._clock.now()) - older_than_days * 24 * 60 * 60
        rows = self._store.reader().execute(
            """
            SELECT *
            FROM backup_artifacts
            WHERE deleted_at IS NULL
              AND (? IS NULL OR world_id = ?)
            ORDER BY world_id, category, created_at DESC
            """,
            (world_id, world_id),
        ).fetchall()
        grouped: dict[tuple[str | None, str], list[Any]] = defaultdict(list)
        for row in rows:
            grouped[(row['world_id'], row['category'])].append(row)

        candidates: list[CleanupCandidate] = []
        for (_world_id, _category), artifacts in grouped.items():
            viable = [row for row in artifacts if row['suspect'] == 0]
            protected_ids = {row['artifact_id'] for row in artifacts[:keep_per_category]}
            if viable:
                protected_ids.add(viable[0]['artifact_id'])
            for row in artifacts:
                if (
                    row['created_at'] >= cutoff
                    or row['artifact_id'] in protected_ids
                    or row['suspect'] != 0
                ):
                    continue
                candidates.append(
                    CleanupCandidate(
                        artifact_id=row['artifact_id'],
                        storage_path=row['storage_path'],
                        world_id=row['world_id'],
                        category=row['category'],
                        created_at=row['created_at'],
                    )
                )
        return sorted(candidates, key=lambda candidate: candidate.created_at)

    def execute_backup_cleanup(
        self,
        candidates: list[CleanupCandidate],
        *,
        deleted_by: str = 'system',
        older_than_days: int = CLEANUP_AGE_FLOOR_DAYS,
        keep_per_category: int = CLEANUP_COUNT_FLOOR,
        world_id: str | None = None,
        elevated_confirmation: bool = False,
    ) -> int:
        if len(candidates) > CLEANUP_BLAST_RADIUS_CAP and not elevated_confirmation:
            raise RetentionError('CLEANUP_BLAST_RADIUS')
        eligible = self.backup_candidates(
            older_than_days=older_than_days,
            keep_per_category=keep_per_category,
            world_id=world_id,
        )
        if candidates != eligible:
            raise RetentionError('CLEANUP_PREVIEW_REQUIRED_OR_STALE')

        now = int(self._clock.now())
        connection = self._store.writer()
        deleted = 0
        for candidate in candidates:
            still_live = connection.execute(
                'SELECT deleted_at FROM backup_artifacts WHERE artifact_id = ?',
                (candidate.artifact_id,),
            ).fetchone()
            if still_live is None or still_live['deleted_at'] is not None:
                continue
            Path(candidate.storage_path).unlink(missing_ok=True)
            connection.execute(
                'UPDATE backup_artifacts SET deleted_at = ?, deleted_by = ? WHERE artifact_id = ?',
                (now, deleted_by, candidate.artifact_id),
            )
            deleted += 1
        connection.commit()
        return deleted

    def evaluate_and_execute_cleanup(
        self,
        *,
        op_id: str,
        world_id: str | None = None,
        dry_run: bool = True,
        older_than_days: int = CLEANUP_AGE_FLOOR_DAYS,
        keep_per_category: int = CLEANUP_COUNT_FLOOR,
        elevated_confirmation: bool = False,
        scope: str = 'backups',
        deleted_by: str = 'system',
        dry_run_operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Preview or perform a retention-bounded cleanup as a durable Operation."""
        operation = self._store.reader().execute(
            'SELECT op_type, status FROM operations WHERE op_id = ?', (op_id,)
        ).fetchone()
        if (
            operation is None
            or operation['op_type'] != 'Cleanup'
            or operation['status']
            in {
                OperationStatus.COMPLETED.value,
                OperationStatus.FAILED.value,
                OperationStatus.CANCELLED.value,
                OperationStatus.TIMED_OUT.value,
            }
        ):
            raise RetentionError('CLEANUP_OPERATION_REQUIRED')
        try:
            candidates = self.backup_candidates(
                older_than_days=older_than_days,
                keep_per_category=keep_per_category,
                world_id=world_id,
            )
            preview_fingerprint = self._preview_fingerprint(
                candidates,
                older_than_days=older_than_days,
                keep_per_category=keep_per_category,
                world_id=world_id,
                scope=scope,
            )
            if (
                not dry_run
                and len(candidates) > CLEANUP_BLAST_RADIUS_CAP
                and not elevated_confirmation
            ):
                raise RetentionError('CLEANUP_BLAST_RADIUS')
            key = (world_id, scope)
            candidate_ids = tuple(candidate.artifact_id for candidate in candidates)
            matched_preview = self._previews.get(key)
            if not dry_run and dry_run_operation_id is not None:
                preview = self._store.reader().execute(
                    """
                    SELECT op_type, status, data_json
                    FROM operations
                    WHERE op_id = ?
                    """,
                    (dry_run_operation_id,),
                ).fetchone()
                if (
                    preview is not None
                    and preview['op_type'] == 'Cleanup'
                    and preview['status'] == OperationStatus.COMPLETED.value
                    and preview['data_json']
                ):
                    preview_data = json.loads(preview['data_json'])
                    if (
                        preview_data.get('scope') == scope
                        and preview_data.get('world_id') == world_id
                    ):
                        matched_preview = preview_data.get('preview_fingerprint')
                    else:
                        matched_preview = None
                else:
                    matched_preview = None
            if not dry_run and matched_preview != preview_fingerprint:
                raise RetentionError('CLEANUP_PREVIEW_REQUIRED_OR_STALE')
            self._operations.transition(op_id, OperationStatus.RUNNING)
            if dry_run:
                self._previews[key] = preview_fingerprint
                result: dict[str, Any] = {
                    'mode': 'dry_run',
                    'scope': scope,
                    'world_id': world_id,
                    'target_count': len(candidates),
                    'targets': list(candidate_ids),
                    'older_than_days': older_than_days,
                    'keep_per_category': keep_per_category,
                    'preview_fingerprint': preview_fingerprint,
                }
            else:
                result = {
                    'mode': 'wet_run',
                    'deleted_count': self.execute_backup_cleanup(
                        candidates,
                        deleted_by=deleted_by,
                        older_than_days=older_than_days,
                        keep_per_category=keep_per_category,
                        world_id=world_id,
                        elevated_confirmation=elevated_confirmation,
                    ),
                    'target_count': len(candidates),
                }
            self._operations.transition(op_id, OperationStatus.COMPLETED, data=result)
            return result
        except RetentionError as exc:
            operation = self._store.reader().execute(
                'SELECT status FROM operations WHERE op_id = ?', (op_id,)
            ).fetchone()
            if operation is not None and operation['status'] not in {
                OperationStatus.COMPLETED.value,
                OperationStatus.FAILED.value,
                OperationStatus.CANCELLED.value,
                OperationStatus.TIMED_OUT.value,
            }:
                self._operations.transition(
                    op_id,
                    OperationStatus.FAILED,
                    error_code=str(exc),
                    message=str(exc),
                )
            raise

    @staticmethod
    def _preview_fingerprint(
        candidates: list[CleanupCandidate],
        *,
        older_than_days: int,
        keep_per_category: int,
        world_id: str | None,
        scope: str,
    ) -> str:
        """Bind confirmation to the policy and exact artifact metadata previewed."""
        snapshot = {
            'older_than_days': older_than_days,
            'keep_per_category': keep_per_category,
            'scope': scope,
            'world_id': world_id,
            'targets': [
                {
                    'artifact_id': candidate.artifact_id,
                    'storage_path': candidate.storage_path,
                    'world_id': candidate.world_id,
                    'category': candidate.category,
                    'created_at': candidate.created_at,
                }
                for candidate in candidates
            ],
        }
        canonical = json.dumps(snapshot, sort_keys=True, separators=(',', ':'))
        return sha256(canonical.encode('utf-8')).hexdigest()
