from __future__ import annotations

import hashlib
import importlib
import os
import shutil
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.tuning import CLEANUP_BLAST_RADIUS_CAP
from app.domain.value_objects import ActorType, OperationStatus, OperationType, TriggerType
from app.infrastructure.backup_engine import NativeBackupEngine
from app.infrastructure.filesystem import LocalFilesystem
from app.services.backup import BackupService
from app.services.cleanup import CleanupService, RetentionError
from app.services.operations import OperationInput, OperationService
from app.services.restore import RestoreService


def _backup_service(store, clock, coordinator=None) -> BackupService:
    return BackupService(
        store,
        clock,
        coordinator,
        NativeBackupEngine(),
        LocalFilesystem(),
    )


def _seed_world(store, *, state: str = 'off') -> str:
    now = 1_700_000_000
    connection = store.writer()
    connection.execute(
        """
        INSERT INTO secrets (
            secret_id, secret_type, encrypted_value, associated_entity_type,
            associated_entity_id, rotation_of, created_at, rotated_at
        ) VALUES ('gate4_secret', 'user_password', 'test-only-placeholder',
                  'user', 'gate4_user', NULL, ?, NULL)
        """,
        (now,),
    )
    connection.execute(
        """
        INSERT INTO users (
            user_id, username, display_name, secret_id, status, failed_login_count,
            locked_until, created_by, deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('gate4_user', 'gate4-admin', NULL, 'gate4_secret', 'active',
                  0, NULL, NULL, NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    connection.execute(
        """
        INSERT INTO templates (
            template_id, name, category, default_version, config_defaults, source,
            deprecated, version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('gate4_tpl', 'Vanilla', 'vanilla', '1.21', '{}', 'built_in',
                  0, 1, NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    connection.execute(
        """
        INSERT INTO java_runtimes (
            runtime_id, label, executable_path, version_detected, status,
            deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('gate4_java', 'Java 21', 'java', '21', 'verified', NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    connection.execute(
        """
        INSERT INTO world_instances (
            world_id, display_name, template_id, server_type, mc_version, java_runtime_id,
            port, addressing_strategy, addressing_value, state, pre_backup_state,
            launch_args, metadata_version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('gate4_world', 'Gate 4', 'gate4_tpl', 'vanilla', '1.21', 'gate4_java',
                  25570, 'port', '25570', ?, NULL, '{}', 1, NULL, NULL, ?, ?)
        """,
        (state, now, now),
    )
    connection.commit()
    return 'gate4_world'


@pytest.fixture(autouse=True)
def sufficient_test_disk(monkeypatch):
    free = 200 * 1024**3
    monkeypatch.setattr(
        shutil,
        'disk_usage',
        lambda _path: SimpleNamespace(total=free, used=0, free=free),
    )


def _create_operation(
    store,
    clock,
    world_id: str,
    op_type: OperationType,
    *,
    data: dict | None = None,
) -> dict:
    return OperationService(store, clock).create(
        OperationInput(
            op_type=op_type,
            actor_type=ActorType.SYSTEM,
            world_id=world_id,
            data=data,
        )
    )


def _seed_source_artifact(store, clock, world_id: str, source_dir: Path, backup_dir: Path) -> str:
    source_op = _create_operation(store, clock, world_id, OperationType.BACKUP)
    result = _backup_service(store, clock).create_world_backup(
        world_id=world_id,
        world_dir=source_dir,
        backup_dir=backup_dir,
        operation_id=source_op['op_id'],
        category=TriggerType.MANUAL,
    )
    OperationService(store, clock).transition(source_op['op_id'], OperationStatus.COMPLETED)
    return result.artifact_id


class _NoopSaveCoordinator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def suspend_autosave(self, world_id: str) -> None:
        self.calls.append('save-off')

    def flush(self, world_id: str) -> None:
        self.calls.append('save-all')

    def resume_autosave(self, world_id: str) -> None:
        self.calls.append('save-on')


def test_backup_artifact_is_atomic_zip_with_verified_sha256(store, clock, tmp_path):
    world_id = _seed_world(store)
    operation = _create_operation(store, clock, world_id, OperationType.BACKUP)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    (world_dir / 'level.dat').write_bytes(b'level-data')
    (world_dir / 'ignored.part').write_bytes(b'partial')
    backup_dir = tmp_path / 'backups'

    result = _backup_service(store, clock).create_world_backup(
        world_id=world_id,
        world_dir=world_dir,
        backup_dir=backup_dir,
        operation_id=operation['op_id'],
        category=TriggerType.MANUAL,
    )

    artifact = Path(result.storage_path)
    assert artifact.is_file()
    assert not list(backup_dir.glob('*.part'))
    assert result.checksum == hashlib.sha256(artifact.read_bytes()).hexdigest()
    with zipfile.ZipFile(artifact) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == ['level.dat']
    row = store.reader().execute(
        'SELECT storage_path, checksum, suspect FROM backup_artifacts WHERE artifact_id = ?',
        (result.artifact_id,),
    ).fetchone()
    assert dict(row) == {
        'storage_path': str(artifact),
        'checksum': result.checksum,
        'suspect': 0,
    }


def test_backup_checksum_failure_cleans_published_and_staged_files(
    store, clock, tmp_path, monkeypatch
):
    world_id = _seed_world(store)
    operation = _create_operation(store, clock, world_id, OperationType.BACKUP)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    (world_dir / 'level.dat').write_bytes(b'level-data')
    backup_dir = tmp_path / 'backups'
    service = _backup_service(store, clock)

    original_checksum = service._sha256
    checksum_calls = 0

    def fail_post_publish_checksum(path: Path) -> str:
        nonlocal checksum_calls
        checksum_calls += 1
        if checksum_calls == 2:
            raise OSError('simulated checksum failure')
        return original_checksum(path)

    monkeypatch.setattr(service, '_sha256', fail_post_publish_checksum)
    with pytest.raises(OSError, match='simulated checksum failure'):
        service.create_world_backup(
            world_id=world_id,
            world_dir=world_dir,
            backup_dir=backup_dir,
            operation_id=operation['op_id'],
            category=TriggerType.MANUAL,
        )

    assert not list(backup_dir.glob('*.part'))
    assert not list(backup_dir.glob('*.zip'))
    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM backup_artifacts WHERE operation_id = ?',
        (operation['op_id'],),
    ).fetchone()['n'] == 0


def test_running_backup_always_sends_save_on_after_compression_failure(
    store, clock, tmp_path, monkeypatch
):
    world_id = _seed_world(store)
    operation = _create_operation(store, clock, world_id, OperationType.BACKUP)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    (world_dir / 'level.dat').write_bytes(b'level-data')
    backup_dir = tmp_path / 'backups'
    coordinator = _NoopSaveCoordinator()
    service = _backup_service(store, clock, coordinator)

    def fail_compression(source_dir: Path, part_path: Path) -> int:
        raise OSError('simulated compression failure')

    monkeypatch.setattr(service, '_write_zip', fail_compression)
    with pytest.raises(OSError, match='simulated compression failure'):
        service.create_world_backup(
            world_id=world_id,
            world_dir=world_dir,
            backup_dir=backup_dir,
            operation_id=operation['op_id'],
            category=TriggerType.MANUAL,
            running=True,
        )

    assert coordinator.calls == ['save-off', 'save-all', 'save-on']
    assert not list(backup_dir.glob('*.part'))
    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM backup_artifacts WHERE operation_id = ?',
        (operation['op_id'],),
    ).fetchone()['n'] == 0


@pytest.mark.parametrize(
    ('total', 'free', 'should_capture'),
    [
        (1_000_000_000_000, 90_000_000_000, True),
        (1_000_000_000_000, 10 * 1024**3 + 9, False),
    ],
)
def test_backup_storage_guard_uses_contextual_reserve_not_flat_percentage(
    store, clock, tmp_path, monkeypatch, total, free, should_capture
):
    world_id = _seed_world(store)
    operation = _create_operation(store, clock, world_id, OperationType.BACKUP)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    (world_dir / 'level.dat').write_bytes(b'x' * 1024)
    backup_dir = tmp_path / 'backups'
    disk_usage_calls: list[Path] = []

    def disk_usage(path: str | os.PathLike[str]) -> SimpleNamespace:
        disk_usage_calls.append(Path(path))
        return SimpleNamespace(total=total, used=total - free, free=free)

    monkeypatch.setattr(shutil, 'disk_usage', disk_usage)
    service = _backup_service(store, clock)

    if should_capture:
        service.create_world_backup(
            world_id=world_id,
            world_dir=world_dir,
            backup_dir=backup_dir,
            operation_id=operation['op_id'],
            category=TriggerType.MANUAL,
        )
        assert list(backup_dir.glob('*.zip'))
    else:
        with pytest.raises(Exception, match='STORAGE_GUARD_FAILED'):
            service.create_world_backup(
                world_id=world_id,
                world_dir=world_dir,
                backup_dir=backup_dir,
                operation_id=operation['op_id'],
                category=TriggerType.MANUAL,
            )
        assert not list(backup_dir.glob('*.zip'))
    assert disk_usage_calls, 'backup must consult available storage before capture'


def test_running_backup_rejects_stale_level_dat_mtime_and_restores_save_on(
    store, clock, tmp_path
):
    world_id = _seed_world(store)
    operation = _create_operation(store, clock, world_id, OperationType.BACKUP)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    level_dat = world_dir / 'level.dat'
    level_dat.write_bytes(b'old-level-data')
    old_mtime = time.time() - 60
    os.utime(level_dat, (old_mtime, old_mtime))
    coordinator = _NoopSaveCoordinator()
    backup_dir = tmp_path / 'backups'

    with pytest.raises(Exception, match='LEVEL_DAT_FLUSH_UNVERIFIED'):
        _backup_service(store, clock, coordinator).create_world_backup(
            world_id=world_id,
            world_dir=world_dir,
            backup_dir=backup_dir,
            operation_id=operation['op_id'],
            category=TriggerType.MANUAL,
            running=True,
        )

    assert coordinator.calls == ['save-off', 'save-all', 'save-on']
    assert not list(backup_dir.glob('*.zip'))
    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM backup_artifacts WHERE operation_id = ?',
        (operation['op_id'],),
    ).fetchone()['n'] == 0


def test_restore_requires_world_off_before_prebackup_or_any_restore_side_effect(
    store, clock, tmp_path
):
    world_id = _seed_world(store, state='running')
    source_dir = tmp_path / 'source'
    source_dir.mkdir()
    (source_dir / 'level.dat').write_bytes(b'replacement')
    artifact_id = _seed_source_artifact(
        store, clock, world_id, source_dir, tmp_path / 'backups'
    )
    restore_operation = _create_operation(store, clock, world_id, OperationType.RESTORE)
    before_artifacts = store.reader().execute(
        'SELECT COUNT(*) AS n FROM backup_artifacts'
    ).fetchone()['n']
    restore = RestoreService(
        store, clock, OperationService(store, clock), _backup_service(store, clock)
    )

    with pytest.raises(Exception, match='WORLD_NOT_OFF'):
        restore.restore(
            world_id=world_id,
            artifact_id=artifact_id,
            world_dir=tmp_path / 'world',
            backup_dir=tmp_path / 'backups',
            staging_dir=tmp_path / 'staging',
            operation_id=restore_operation['op_id'],
            operator_user_id='gate4_user',
            was_running=False,
        )

    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM backup_artifacts'
    ).fetchone()['n'] == before_artifacts
    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM restore_history'
    ).fetchone()['n'] == 0


def test_restore_always_registers_mandatory_pre_restore_artifact(store, clock, tmp_path):
    world_id = _seed_world(store)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    (world_dir / 'level.dat').write_bytes(b'original')
    source_dir = tmp_path / 'source'
    source_dir.mkdir()
    (source_dir / 'level.dat').write_bytes(b'replacement')
    backup_dir = tmp_path / 'backups'
    artifact_id = _seed_source_artifact(store, clock, world_id, source_dir, backup_dir)
    restore_operation = _create_operation(store, clock, world_id, OperationType.RESTORE)

    result = RestoreService(
        store, clock, OperationService(store, clock), _backup_service(store, clock)
    ).restore(
        world_id=world_id,
        artifact_id=artifact_id,
        world_dir=world_dir,
        backup_dir=backup_dir,
        staging_dir=tmp_path / 'staging',
        operation_id=restore_operation['op_id'],
        operator_user_id='gate4_user',
        was_running=False,
    )

    history = store.reader().execute(
        'SELECT pre_restore_artifact_id, outcome FROM restore_history WHERE restore_id = ?',
        (result.restore_id,),
    ).fetchone()
    pre_restore = store.reader().execute(
        'SELECT category FROM backup_artifacts WHERE artifact_id = ?',
        (history['pre_restore_artifact_id'],),
    ).fetchone()
    assert history['outcome'] == 'success'
    assert pre_restore['category'] == TriggerType.PRE_RESTORE.value
    assert (world_dir / 'level.dat').read_bytes() == b'replacement'


def test_failed_restore_verification_rolls_back_and_marks_source_suspect(
    store, clock, tmp_path
):
    world_id = _seed_world(store)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    (world_dir / 'level.dat').write_bytes(b'original')
    source_dir = tmp_path / 'source'
    source_dir.mkdir()
    (source_dir / 'level.dat').write_bytes(b'replacement')
    backup_dir = tmp_path / 'backups'
    artifact_id = _seed_source_artifact(store, clock, world_id, source_dir, backup_dir)
    restore_operation = _create_operation(store, clock, world_id, OperationType.RESTORE)

    class FailedRestart:
        def restart_and_confirm(self, _world_id: str) -> bool:
            return False

    result = RestoreService(
        store,
        clock,
        OperationService(store, clock),
        _backup_service(store, clock),
        FailedRestart(),
    ).restore(
        world_id=world_id,
        artifact_id=artifact_id,
        world_dir=world_dir,
        backup_dir=backup_dir,
        staging_dir=tmp_path / 'staging',
        operation_id=restore_operation['op_id'],
        operator_user_id='gate4_user',
        was_running=True,
    )

    source = store.reader().execute(
        'SELECT suspect FROM backup_artifacts WHERE artifact_id = ?', (artifact_id,)
    ).fetchone()
    assert result.outcome == 'reverted'
    assert (world_dir / 'level.dat').read_bytes() == b'original'
    assert source['suspect'] == 1


def test_cleanup_rejects_age_and_keep_values_below_safety_floors(store, clock):
    _seed_world(store)
    cleanup = CleanupService(store, clock)

    with pytest.raises(RetentionError):
        cleanup.backup_candidates(older_than_days=2)
    with pytest.raises(RetentionError):
        cleanup.backup_candidates(older_than_days=3, keep_per_category=2)

    assert CLEANUP_BLAST_RADIUS_CAP == 500


def test_cleanup_dry_run_is_an_operation_preview_without_deleting_artifacts(
    store, clock, tmp_path
):
    evaluator = getattr(CleanupService, 'evaluate_and_execute_cleanup', None)
    assert callable(evaluator), (
        'Gate 4 requires dry-run and wet cleanup to be represented by Operations'
    )

    world_id = _seed_world(store)
    backup_operation = _create_operation(store, clock, world_id, OperationType.BACKUP)
    OperationService(store, clock).transition(
        backup_operation['op_id'], OperationStatus.COMPLETED
    )
    connection = store.writer()
    paths = []
    for index in range(4):
        path = tmp_path / f'dry-run-{index}.zip'
        path.write_bytes(b'candidate')
        paths.append(path)
        connection.execute(
            """
            INSERT INTO backup_artifacts (
                artifact_id, world_id, category, storage_path, size_bytes, checksum,
                suspect, operation_id, deleted_at, deleted_by, created_at
            ) VALUES (?, ?, 'manual', ?, 1, ?, 0, ?, NULL, NULL, ?)
            """,
            (
                f'gate4_dry_run_{index}',
                world_id,
                str(path),
                '0' * 64,
                backup_operation['op_id'],
                int(clock.now()) - (10 - index) * 24 * 60 * 60,
            ),
        )
    connection.commit()
    cleanup_operation = _create_operation(
        store, clock, world_id, OperationType.CLEANUP, data={'dry_run': True}
    )
    response = evaluator(
        CleanupService(store, clock),
        op_id=cleanup_operation['op_id'],
        world_id=world_id,
        dry_run=True,
    )

    assert response['mode'] == 'dry_run'
    assert response['target_count'] == 1
    cleanup_row = store.reader().execute(
        'SELECT op_type, status FROM operations WHERE op_id = ?',
        (cleanup_operation['op_id'],),
    ).fetchone()
    assert cleanup_row['op_type'] == OperationType.CLEANUP.value
    assert cleanup_row['status'] == OperationStatus.COMPLETED.value
    assert all(path.is_file() for path in paths)


def test_cleanup_wet_run_follows_preview_and_records_operation_result(store, clock, tmp_path):
    evaluator = getattr(CleanupService, 'evaluate_and_execute_cleanup', None)
    assert callable(evaluator), (
        'Gate 4 requires dry-run and wet cleanup to be represented by Operations'
    )

    world_id = _seed_world(store)
    backup_operation = _create_operation(store, clock, world_id, OperationType.BACKUP)
    OperationService(store, clock).transition(
        backup_operation['op_id'], OperationStatus.COMPLETED
    )
    connection = store.writer()
    paths = []
    for index in range(4):
        path = tmp_path / f'wet-run-{index}.zip'
        path.write_bytes(b'candidate')
        paths.append(path)
        connection.execute(
            """
            INSERT INTO backup_artifacts (
                artifact_id, world_id, category, storage_path, size_bytes, checksum,
                suspect, operation_id, deleted_at, deleted_by, created_at
            ) VALUES (?, ?, 'manual', ?, 1, ?, 0, ?, NULL, NULL, ?)
            """,
            (
                f'gate4_wet_run_{index}',
                world_id,
                str(path),
                '0' * 64,
                backup_operation['op_id'],
                int(clock.now()) - (10 - index) * 24 * 60 * 60,
            ),
        )
    connection.commit()
    cleanup = CleanupService(store, clock)
    preview_op = _create_operation(
        store, clock, world_id, OperationType.CLEANUP, data={'dry_run': True}
    )
    preview = evaluator(
        cleanup,
        op_id=preview_op['op_id'],
        world_id=world_id,
        dry_run=True,
    )
    assert preview['target_count'] == 1
    assert paths[0].is_file()
    cleanup_op = _create_operation(
        store, clock, world_id, OperationType.CLEANUP, data={'dry_run': False}
    )

    result = evaluator(
        cleanup,
        op_id=cleanup_op['op_id'],
        world_id=world_id,
        dry_run=False,
    )

    assert result['mode'] == 'wet_run'
    assert result['deleted_count'] == 1
    assert not paths[0].exists()
    assert store.reader().execute(
        'SELECT deleted_at FROM backup_artifacts WHERE artifact_id = ?',
        ('gate4_wet_run_0',),
    ).fetchone()['deleted_at'] is not None
    operations = store.reader().execute(
        'SELECT op_type, status FROM operations WHERE op_id IN (?, ?)',
        (preview_op['op_id'], cleanup_op['op_id']),
    ).fetchall()
    assert len(operations) == 2
    assert all(row['op_type'] == OperationType.CLEANUP.value for row in operations)
    assert all(row['status'] == OperationStatus.COMPLETED.value for row in operations)


def test_cleanup_wet_execution_enforces_blast_radius_before_deletion(store, clock, tmp_path):
    evaluator = getattr(CleanupService, 'evaluate_and_execute_cleanup', None)
    assert callable(evaluator), (
        'Gate 4 requires wet cleanup to enforce a bounded candidate blast radius'
    )
    world_id = _seed_world(store)
    backup_operation = _create_operation(store, clock, world_id, OperationType.BACKUP)
    now = int(clock.now()) - 10 * 24 * 60 * 60
    connection = store.writer()
    count = CLEANUP_BLAST_RADIUS_CAP + 4
    for index in range(count):
        connection.execute(
            """
            INSERT INTO backup_artifacts (
                artifact_id, world_id, category, storage_path, size_bytes, checksum,
                suspect, operation_id, deleted_at, deleted_by, created_at
            ) VALUES (?, ?, 'manual', ?, 1, ?, 0, ?, NULL, NULL, ?)
            """,
            (
                f'gate4_cleanup_{index}',
                world_id,
                str(tmp_path / f'{index}.zip'),
                '0' * 64,
                backup_operation['op_id'],
                now + index,
            ),
        )
    connection.commit()
    OperationService(store, clock).transition(
        backup_operation['op_id'], OperationStatus.COMPLETED
    )
    cleanup_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)
    before = store.reader().execute(
        'SELECT COUNT(*) AS n FROM backup_artifacts WHERE deleted_at IS NULL'
    ).fetchone()['n']

    with pytest.raises(Exception, match='CLEANUP_BLAST_RADIUS'):
        evaluator(
            CleanupService(store, clock),
            op_id=cleanup_operation['op_id'],
            world_id=world_id,
            dry_run=False,
            elevated_confirmation=False,
        )

    after = store.reader().execute(
        'SELECT COUNT(*) AS n FROM backup_artifacts WHERE deleted_at IS NULL'
    ).fetchone()['n']
    assert after == before


def test_sync_service_exposes_three_stage_retry_and_daily_transfer_cap():
    module_spec = importlib.util.find_spec('app.services.sync')
    assert module_spec is not None, 'Gate 4 requires app.services.sync'
    module = importlib.import_module('app.services.sync')
    service_type = getattr(module, 'SyncService', None) or getattr(
        module, 'OffsiteSyncService', None
    )
    assert service_type is not None, 'Gate 4 requires a SyncService implementation'
    assert tuple(service_type.BACKOFF_DELAYS) == (30, 60)
    assert service_type.DAILY_TRANSFER_CAP_BYTES == 50 * 1024**3


def test_sync_failure_records_attempt_timeline_and_backoff_without_blocking_local_backup(
    store, clock, tmp_path
):
    module_spec = importlib.util.find_spec('app.services.sync')
    assert module_spec is not None, 'Gate 4 requires app.services.sync'
    module = importlib.import_module('app.services.sync')
    service_type = getattr(module, 'SyncService', None) or getattr(
        module, 'OffsiteSyncService', None
    )
    assert service_type is not None, 'Gate 4 requires a SyncService implementation'

    world_id = _seed_world(store)
    source_dir = tmp_path / 'world'
    source_dir.mkdir()
    (source_dir / 'level.dat').write_bytes(b'local backup survives remote failure')
    operation = _create_operation(store, clock, world_id, OperationType.BACKUP)

    class FailingTransport:
        def upload_file(self, *_args, **_kwargs) -> None:
            raise OSError('offsite unavailable')

    sleeps: list[float] = []
    sync = service_type(
        store,
        FailingTransport(),
        clock=clock,
        sleeper=sleeps.append,
    )
    backup = _backup_service(store, clock)
    result = backup.create_world_backup(
        world_id=world_id,
        world_dir=source_dir,
        backup_dir=tmp_path / 'backups',
        operation_id=operation['op_id'],
        category=TriggerType.MANUAL,
    )

    assert Path(result.storage_path).is_file()
    assert store.reader().execute(
        'SELECT checksum FROM backup_artifacts WHERE artifact_id = ?',
        (result.artifact_id,),
    ).fetchone()['checksum'] == result.checksum
    sync.dispatch_sync(result.artifact_id, 'gate4-nas')
    assert sleeps == [30, 60]
    timeline = store.reader().execute(
        """
        SELECT attempt_number, started_at, finished_at, outcome
        FROM sync_attempts
        WHERE sync_id = (
            SELECT sync_id FROM sync_records WHERE artifact_id = ?
            ORDER BY created_at DESC LIMIT 1
        )
        ORDER BY attempt_number
        """,
        (result.artifact_id,),
    ).fetchall()
    assert [row['attempt_number'] for row in timeline] == list(
        range(1, len(timeline) + 1)
    )
    assert timeline
    assert len(timeline) == 3
    assert all(row['started_at'] <= row['finished_at'] for row in timeline)
    assert all(row['outcome'] == 'failed_transient' for row in timeline)
    assert store.reader().execute(
        'SELECT status FROM sync_records WHERE artifact_id = ?',
        (result.artifact_id,),
    ).fetchone()['status'] == 'failed'


def test_sync_daily_cap_rejects_dispatch_without_touching_local_artifact(
    store, clock, tmp_path, monkeypatch
):
    module_spec = importlib.util.find_spec('app.services.sync')
    assert module_spec is not None, 'Gate 4 requires app.services.sync'
    module = importlib.import_module('app.services.sync')
    service_type = getattr(module, 'SyncService', None) or getattr(
        module, 'OffsiteSyncService', None
    )
    assert service_type is not None, 'Gate 4 requires a SyncService implementation'
    assert hasattr(service_type, 'get_bytes_transferred_today')

    world_id = _seed_world(store)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    (world_dir / 'level.dat').write_bytes(b'local backup remains valid')
    operation = _create_operation(store, clock, world_id, OperationType.BACKUP)
    result = _backup_service(store, clock).create_world_backup(
        world_id=world_id,
        world_dir=world_dir,
        backup_dir=tmp_path / 'backups',
        operation_id=operation['op_id'],
        category=TriggerType.MANUAL,
    )
    service = service_type(store, SimpleNamespace(upload_file=lambda *_a, **_k: None))
    monkeypatch.setattr(
        service, 'get_bytes_transferred_today', lambda: service_type.DAILY_TRANSFER_CAP_BYTES
    )
    with pytest.raises(Exception, match='SYNC_CAP_EXCEEDED'):
        service.dispatch_sync(result.artifact_id, 'gate4-nas')
    assert Path(result.storage_path).is_file()
    assert store.reader().execute(
        'SELECT checksum FROM backup_artifacts WHERE artifact_id = ?',
        (result.artifact_id,),
    ).fetchone()['checksum'] == result.checksum


def test_container_wires_runtime_as_restore_restart_probe(container):
    assert container.restore._restart_probe is container.runtime
