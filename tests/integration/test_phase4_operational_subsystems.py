from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.value_objects import (
    ActorType,
    ConfigEditEntity,
    OperationStatus,
    OperationType,
    TriggerType,
)
from app.infrastructure.backup_engine import NativeBackupEngine
from app.infrastructure.filesystem import LocalFilesystem
from app.services.backup import BackupIntegrityError, BackupService
from app.services.cleanup import CleanupService, RetentionError
from app.services.configuration import (
    ConfigurationConflictError,
    ConfigurationService,
    VersionedUpdate,
)
from app.services.operations import OperationInput, OperationService
from app.services.restore import RestoreService

from .test_phase3_control_plane import _seed_world


@pytest.fixture(autouse=True)
def sufficient_test_disk(monkeypatch):
    free = 200 * 1024**3
    monkeypatch.setattr(
        shutil,
        'disk_usage',
        lambda _path: SimpleNamespace(total=free, used=0, free=free),
    )


def _backup_service(store, clock, coordinator=None) -> BackupService:
    return BackupService(
        store,
        clock,
        coordinator,
        NativeBackupEngine(),
        LocalFilesystem(),
    )


class RecordingSaveCoordinator:
    def __init__(self, *, fail_flush: bool = False) -> None:
        self.calls: list[str] = []
        self.fail_flush = fail_flush

    def suspend_autosave(self, world_id: str) -> None:
        self.calls.append(f'save-off:{world_id}')

    def flush(self, world_id: str) -> None:
        self.calls.append(f'save-all:{world_id}')
        if self.fail_flush:
            raise RuntimeError('flush failed')

    def resume_autosave(self, world_id: str) -> None:
        self.calls.append(f'save-on:{world_id}')


class RestartFails:
    def restart_and_confirm(self, world_id: str) -> bool:
        return False


def _operation(store, clock, world_id: str, op_type: OperationType = OperationType.BACKUP) -> dict:
    return OperationService(store, clock).create(
        OperationInput(op_type=op_type, actor_type=ActorType.SYSTEM, world_id=world_id)
    )


def test_backup_zip_sha256_registers_only_after_success(store, clock, tmp_path):
    world_id = _seed_world(store)
    op = _operation(store, clock, world_id)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    (world_dir / 'level.dat').write_text('world data', encoding='utf-8')
    (world_dir / 'skip.part').write_text('partial', encoding='utf-8')
    coordinator = RecordingSaveCoordinator()
    service = _backup_service(store, clock, coordinator)

    result = service.create_world_backup(
        world_id=world_id,
        world_dir=world_dir,
        backup_dir=tmp_path / 'backups',
        operation_id=op['op_id'],
        category=TriggerType.MANUAL,
        running=True,
    )

    assert coordinator.calls == [f'save-off:{world_id}', f'save-all:{world_id}', f'save-on:{world_id}']
    assert len(result.checksum) == 64
    with zipfile.ZipFile(result.storage_path) as archive:
        assert archive.namelist() == ['level.dat']
    row = store.reader().execute('SELECT * FROM backup_artifacts WHERE artifact_id = ?', (result.artifact_id,)).fetchone()
    assert row['checksum'] == result.checksum
    OperationService(store, clock).transition(op['op_id'], OperationStatus.COMPLETED)

    failed_op = _operation(store, clock, world_id, OperationType.BACKUP)
    failing = _backup_service(store, clock, RecordingSaveCoordinator(fail_flush=True))
    with pytest.raises(RuntimeError):
        failing.create_world_backup(
            world_id=world_id,
            world_dir=world_dir,
            backup_dir=tmp_path / 'failed',
            operation_id=failed_op['op_id'],
            category=TriggerType.MANUAL,
            running=True,
        )
    assert store.reader().execute('SELECT COUNT(*) AS n FROM backup_artifacts WHERE operation_id = ?', (failed_op['op_id'],)).fetchone()['n'] == 0
    assert not list((tmp_path / 'failed').glob('*.part'))


def test_backup_validation_flags_suspect_on_checksum_mismatch(store, clock, tmp_path):
    world_id = _seed_world(store)
    op = _operation(store, clock, world_id)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    (world_dir / 'level.dat').write_text('ok', encoding='utf-8')
    service = _backup_service(store, clock)
    result = service.create_world_backup(
        world_id=world_id,
        world_dir=world_dir,
        backup_dir=tmp_path / 'backups',
        operation_id=op['op_id'],
        category=TriggerType.MANUAL,
    )
    Path(result.storage_path).write_bytes(b'corrupted')

    with pytest.raises(BackupIntegrityError):
        service.validate_artifact(result.artifact_id)
    row = store.reader().execute('SELECT suspect FROM backup_artifacts WHERE artifact_id = ?', (result.artifact_id,)).fetchone()
    assert row['suspect'] == 1


def test_restore_failed_restart_rolls_back_to_pre_restore_backup(store, clock, tmp_path):
    world_id = _seed_world(store)
    backup_service = _backup_service(store, clock)
    operations = OperationService(store, clock)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    (world_dir / 'level.dat').write_text('old', encoding='utf-8')
    replacement = tmp_path / 'replacement'
    replacement.mkdir()
    (replacement / 'level.dat').write_text('new', encoding='utf-8')
    source_op = _operation(store, clock, world_id, OperationType.BACKUP)
    source = backup_service.create_world_backup(
        world_id=world_id,
        world_dir=replacement,
        backup_dir=tmp_path / 'backups',
        operation_id=source_op['op_id'],
        category=TriggerType.MANUAL,
    )
    operations.transition(source_op['op_id'], OperationStatus.COMPLETED)
    restore_op = _operation(store, clock, world_id, OperationType.RESTORE)
    service = RestoreService(store, clock, operations, backup_service, RestartFails())

    result = service.restore(
        world_id=world_id,
        artifact_id=source.artifact_id,
        world_dir=world_dir,
        backup_dir=tmp_path / 'backups',
        staging_dir=tmp_path / 'stage',
        operation_id=restore_op['op_id'],
        operator_user_id='u_admin',
        was_running=True,
    )

    assert result.outcome == 'reverted'
    assert (world_dir / 'level.dat').read_text(encoding='utf-8') == 'old'
    state = store.reader().execute('SELECT state FROM world_instances WHERE world_id = ?', (world_id,)).fetchone()
    assert state['state'] == 'off'
    original = store.reader().execute('SELECT outcome FROM restore_history WHERE restore_id = ?', (result.restore_id,)).fetchone()
    rollback = store.reader().execute('SELECT rollback_of_restore_id FROM restore_history WHERE rollback_of_restore_id = ?', (result.restore_id,)).fetchone()
    assert original['outcome'] == 'reverted'
    assert rollback['rollback_of_restore_id'] == result.restore_id


def test_cleanup_enforces_age_count_and_last_viable_artifact(store, clock, tmp_path):
    world_id = _seed_world(store)
    op = _operation(store, clock, world_id)
    connection = store.writer()
    for idx in range(5):
        path = tmp_path / f'a{idx}.zip'
        path.write_text('artifact', encoding='utf-8')
        connection.execute(
            """
            INSERT INTO backup_artifacts (
                artifact_id, world_id, category, storage_path, size_bytes, checksum,
                suspect, operation_id, deleted_at, deleted_by, created_at
            ) VALUES (?, ?, 'manual', ?, 1, ?, 0, ?, NULL, NULL, ?)
            """,
            (f'ba_{idx}', world_id, str(path), '0' * 64, op['op_id'], int(clock.now()) - (10 - idx) * 24 * 60 * 60),
        )
    connection.commit()
    cleanup = CleanupService(store, clock)

    with pytest.raises(RetentionError):
        cleanup.backup_candidates(older_than_days=1)
    candidates = cleanup.backup_candidates(older_than_days=3)
    assert [candidate.artifact_id for candidate in candidates] == ['ba_0', 'ba_1']
    assert cleanup.execute_backup_cleanup(candidates) == 2
    assert not (tmp_path / 'a0.zip').exists()


def test_optimistic_concurrency_for_versioned_config_rows(store, clock):
    world_id = _seed_world(store)
    service = ConfigurationService(store, clock)
    updated = service.update_versioned(
        VersionedUpdate(
            entity=ConfigEditEntity.WORLD_INSTANCES,
            row_id=world_id,
            expected_version=1,
            fields={'display_name': 'Renamed'},
        )
    )
    assert updated['metadata_version'] == 2
    with pytest.raises(ConfigurationConflictError):
        service.update_versioned(
            VersionedUpdate(
                entity=ConfigEditEntity.WORLD_INSTANCES,
                row_id=world_id,
                expected_version=1,
                fields={'display_name': 'Stale'},
            )
        )
