from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.value_objects import OperationStatus, OperationType
from app.infrastructure.sync_transport.nas import NasSyncTransport
from app.ports.sync_transport import PermanentSyncTransportError
from app.services.operations import OperationService
from app.services.sync import SyncError, SyncService
from tests.integration.test_gate4_acceptance import _create_operation, _seed_world


def _create_artifact(store, clock, tmp_path: Path):
    world_id = _seed_world(store)
    local_archive = tmp_path / 'backups' / 'local-backup.zip'
    local_archive.parent.mkdir()
    content = b'local backup remains valid'
    local_archive.write_bytes(content)
    operation = _create_operation(store, clock, world_id, OperationType.BACKUP)
    connection = store.writer()
    connection.execute(
        """
        INSERT INTO backup_artifacts (
            artifact_id, world_id, category, storage_path, size_bytes, checksum,
            suspect, operation_id, deleted_at, deleted_by, created_at
        ) VALUES (?, ?, 'manual', ?, ?, ?, 0, ?, NULL, NULL, ?)
        """,
        (
            'sync_test_artifact',
            world_id,
            str(local_archive),
            len(content),
            hashlib.sha256(content).hexdigest(),
            operation['op_id'],
            int(clock.now()),
        ),
    )
    connection.commit()
    OperationService(store, clock).transition(
        operation['op_id'], OperationStatus.COMPLETED
    )
    return SimpleNamespace(
        artifact_id='sync_test_artifact',
        storage_path=str(local_archive),
        size_bytes=len(content),
    )


def _fake_wait(clock, delays: list[float]):
    def wait(seconds: float) -> None:
        delays.append(seconds)
        clock.advance(seconds)

    return wait


def test_sync_retry_timeline_and_attempt_history_are_write_once(
    store, clock, tmp_path
):
    artifact = _create_artifact(store, clock, tmp_path)
    started_at = int(clock.now())
    delays: list[float] = []

    class FlakyTransport:
        def __init__(self) -> None:
            self.call_times: list[int] = []

        def upload_file(self, _target_id, _source_path) -> None:
            self.call_times.append(int(clock.now()))
            if len(self.call_times) < 3:
                raise OSError('temporary NAS outage')

    transport = FlakyTransport()
    service = SyncService(
        store, transport, clock, sleeper=_fake_wait(clock, delays)
    )

    sync_id = service.dispatch_sync(artifact.artifact_id, 'gate4-nas')
    rows = store.reader().execute(
        """
        SELECT attempt_id, attempt_number, started_at, finished_at, outcome
        FROM sync_attempts
        WHERE sync_id = ?
        ORDER BY attempt_number
        """,
        (sync_id,),
    ).fetchall()

    assert delays == [30, 60]
    assert transport.call_times == [
        started_at,
        started_at + 30,
        started_at + 90,
    ]
    assert [row['attempt_number'] for row in rows] == [1, 2, 3]
    assert [row['outcome'] for row in rows] == [
        'failed_transient',
        'failed_transient',
        'succeeded',
    ]
    assert len({row['attempt_id'] for row in rows}) == 3
    before = [tuple(row) for row in rows]
    with pytest.raises(sqlite3.IntegrityError, match='write-once'):
        store.writer().execute(
            'UPDATE sync_attempts SET error_message = ? WHERE attempt_id = ?',
            ('rewritten', rows[0]['attempt_id']),
        )
    assert [
        tuple(row)
        for row in store.reader().execute(
            """
            SELECT attempt_id, attempt_number, started_at, finished_at, outcome
            FROM sync_attempts WHERE sync_id = ? ORDER BY attempt_number
            """,
            (sync_id,),
        ).fetchall()
    ] == before


def test_daily_transfer_cap_stops_sync_without_touching_local_artifact(
    store, clock, tmp_path
):
    artifact = _create_artifact(store, clock, tmp_path)
    transport_calls: list[Path] = []
    service = SyncService(
        store,
        type(
            'Transport',
            (),
            {'upload_file': lambda _self, _target, source: transport_calls.append(Path(source))},
        )(),
        clock,
        sleeper=_fake_wait(clock, []),
    )
    assert service.DAILY_TRANSFER_CAP_BYTES == 50 * 1024**3
    service.dispatch_sync(artifact.artifact_id, 'gate4-nas')
    assert service.get_bytes_transferred_today() == artifact.size_bytes

    service.get_bytes_transferred_today = lambda: (
        service.DAILY_TRANSFER_CAP_BYTES - artifact.size_bytes + 1
    )

    with pytest.raises(SyncError, match='SYNC_CAP_EXCEEDED'):
        service.dispatch_sync(artifact.artifact_id, 'gate4-nas')

    assert transport_calls == [Path(artifact.storage_path)]
    assert Path(artifact.storage_path).is_file()


def test_transport_failure_does_not_invalidate_local_backup(
    store, clock, tmp_path
):
    artifact = _create_artifact(store, clock, tmp_path)
    original_bytes = Path(artifact.storage_path).read_bytes()
    original_checksum = store.reader().execute(
        'SELECT checksum FROM backup_artifacts WHERE artifact_id = ?',
        (artifact.artifact_id,),
    ).fetchone()['checksum']
    delays: list[float] = []

    class FailingTransport:
        def upload_file(self, _target_id, _source_path) -> None:
            raise OSError('NAS unreachable')

    sync_id = SyncService(
        store, FailingTransport(), clock, sleeper=_fake_wait(clock, delays)
    ).dispatch_sync(artifact.artifact_id, 'gate4-nas')

    assert delays == [30, 60]
    assert Path(artifact.storage_path).read_bytes() == original_bytes
    assert store.reader().execute(
        'SELECT checksum FROM backup_artifacts WHERE artifact_id = ?',
        (artifact.artifact_id,),
    ).fetchone()['checksum'] == original_checksum
    assert store.reader().execute(
        'SELECT status FROM sync_records WHERE sync_id = ?', (sync_id,)
    ).fetchone()['status'] == 'failed'
    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM sync_attempts WHERE sync_id = ?', (sync_id,)
    ).fetchone()['n'] == 3


def test_permanent_transport_failure_is_recorded_without_retry(
    store, clock, tmp_path
):
    artifact = _create_artifact(store, clock, tmp_path)
    delays: list[float] = []
    calls: list[Path] = []

    class MisconfiguredTransport:
        def upload_file(self, _target_id, source_path) -> None:
            calls.append(Path(source_path))
            raise PermanentSyncTransportError('target configuration is invalid')

    sync_id = SyncService(
        store, MisconfiguredTransport(), clock, sleeper=_fake_wait(clock, delays)
    ).dispatch_sync(artifact.artifact_id, 'gate4-nas')

    attempts = store.reader().execute(
        'SELECT attempt_number, outcome FROM sync_attempts WHERE sync_id = ?',
        (sync_id,),
    ).fetchall()
    assert calls == [Path(artifact.storage_path)]
    assert delays == []
    assert [(row['attempt_number'], row['outcome']) for row in attempts] == [
        (1, 'failed_permanent')
    ]
    assert store.reader().execute(
        'SELECT status FROM sync_records WHERE sync_id = ?', (sync_id,)
    ).fetchone()['status'] == 'failed'


def test_mounted_nas_copies_artifact_basename_under_target_root(
    store, clock, tmp_path
):
    artifact = _create_artifact(store, clock, tmp_path)
    target_root = tmp_path / 'mounted' / 'nas-share'
    connection = store.writer()
    connection.execute(
        """
        INSERT INTO sync_targets (
            sync_target_id, scope, world_id, target_type, config, secret_id,
            enabled, version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES (?, 'global', NULL, 'nas', ?, 'gate4_secret',
                  1, 1, NULL, NULL, ?, ?)
        """,
        (
            'mounted-nas',
            json.dumps({'path': str(target_root)}),
            int(clock.now()),
            int(clock.now()),
        ),
    )
    connection.commit()

    NasSyncTransport(store).upload_file('mounted-nas', artifact.storage_path)

    copied = target_root / Path(artifact.storage_path).name
    assert copied.is_file()
    assert copied.read_bytes() == Path(artifact.storage_path).read_bytes()
    assert sorted(path.name for path in target_root.iterdir()) == [
        Path(artifact.storage_path).name
    ]
