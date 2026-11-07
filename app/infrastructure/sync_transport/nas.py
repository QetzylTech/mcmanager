"""Filesystem-backed NAS transport for mounted network shares."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.infrastructure.sqlite.connection import SqliteStore
from app.ports.sync_transport import PermanentSyncTransportError, SyncTransportPort


class NasSyncTransport(SyncTransportPort):
    """Copy artifacts to configured mounted NAS target roots."""

    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    def upload_file(self, target_id: str, source_path: str | Path) -> None:
        target = self._store.reader().execute(
            """
            SELECT target_type, config
            FROM sync_targets
            WHERE sync_target_id = ? AND enabled = 1 AND deleted_at IS NULL
            """,
            (target_id,),
        ).fetchone()
        if target is None or target['target_type'] != 'nas':
            raise PermanentSyncTransportError(
                f'NAS target is not configured: {target_id}'
            )
        try:
            config = json.loads(target['config'])
        except (TypeError, ValueError) as exc:
            raise PermanentSyncTransportError(
                f'NAS target configuration is invalid: {target_id}'
            ) from exc
        target_path = config.get('path')
        if not isinstance(target_path, str) or not target_path:
            raise PermanentSyncTransportError(
                f'NAS target path is missing: {target_id}'
            )
        target_root = Path(target_path)
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_root / Path(source_path).name)
