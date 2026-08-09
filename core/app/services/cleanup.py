"""Cleanup and retention enforcement for Tier 2 rows/artifacts (Gate 4)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.tuning import CLEANUP_AGE_FLOOR_DAYS, CLEANUP_COUNT_FLOOR
from app.infrastructure.sqlite.connection import SqliteStore
from app.ports.clock import Clock


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

    def __init__(self, store: SqliteStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def backup_candidates(self, *, older_than_days: int, keep_per_category: int = CLEANUP_COUNT_FLOOR) -> list[CleanupCandidate]:
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
            ORDER BY world_id, category, created_at DESC
            """
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
                if row['created_at'] >= cutoff or row['artifact_id'] in protected_ids:
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

    def execute_backup_cleanup(self, candidates: list[CleanupCandidate], *, deleted_by: str = 'system') -> int:
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
