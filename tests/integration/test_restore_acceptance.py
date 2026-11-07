from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.services.restore as restore_module
from app.domain.value_objects import (
    ActorType,
    OperationStatus,
    OperationType,
    TriggerType,
)
from app.infrastructure.backup_engine import NativeBackupEngine
from app.infrastructure.filesystem import LocalFilesystem
from app.services.backup import BackupIntegrityError, BackupService
from app.services.operations import OperationInput, OperationService
from app.services.restore import RestorePreconditionError, RestoreService


def _backup_service(store, clock) -> BackupService:
    return BackupService(
        store, clock, engine=NativeBackupEngine(), filesystem=LocalFilesystem()
    )


@pytest.fixture(autouse=True)
def sufficient_test_disk(monkeypatch):
    free = 200 * 1024**3
    monkeypatch.setattr(
        shutil,
        'disk_usage',
        lambda _path: SimpleNamespace(total=free, used=0, free=free),
    )


def _seed_world(store, *, state: str = 'off') -> str:
    now = 1_700_000_000
    connection = store.writer()
    connection.execute(
        """
        INSERT INTO secrets (
            secret_id, secret_type, encrypted_value, associated_entity_type,
            associated_entity_id, rotation_of, created_at, rotated_at
        ) VALUES ('restore_secret', 'user_password', 'placeholder',
                  'user', 'restore_user', NULL, ?, NULL)
        """,
        (now,),
    )
    connection.execute(
        """
        INSERT INTO users (
            user_id, username, display_name, secret_id, status, failed_login_count,
            locked_until, created_by, deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('restore_user', 'restore-admin', NULL, 'restore_secret', 'active',
                  0, NULL, NULL, NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    connection.execute(
        """
        INSERT INTO templates (
            template_id, name, category, default_version, config_defaults, source,
            deprecated, version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('restore_tpl', 'Vanilla', 'vanilla', '1.21', '{}', 'built_in',
                  0, 1, NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    connection.execute(
        """
        INSERT INTO java_runtimes (
            runtime_id, label, executable_path, version_detected, status,
            deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('restore_java', 'Java 21', 'java', '21', 'verified',
                  NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    connection.execute(
        """
        INSERT INTO world_instances (
            world_id, display_name, template_id, server_type, mc_version, java_runtime_id,
            port, addressing_strategy, addressing_value, state, pre_backup_state,
            launch_args, metadata_version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('restore_world', 'Restore test', 'restore_tpl', 'vanilla', '1.21',
                  'restore_java', 25571, 'port', '25571', ?, NULL, '{}', 1,
                  NULL, NULL, ?, ?)
        """,
        (state, now, now),
    )
    connection.commit()
    return 'restore_world'


def _create_operation(operations: OperationService, world_id: str, op_type: OperationType):
    return operations.create(
        OperationInput(op_type=op_type, actor_type=ActorType.SYSTEM, world_id=world_id)
    )


def _seed_artifact(store, clock, world_id: str, source_dir: Path, backup_dir: Path) -> str:
    operations = OperationService(store, clock)
    source_operation = _create_operation(operations, world_id, OperationType.BACKUP)
    result = _backup_service(store, clock).create_world_backup(
        world_id=world_id,
        world_dir=source_dir,
        backup_dir=backup_dir,
        operation_id=source_operation['op_id'],
        category=TriggerType.MANUAL,
    )
    operations.transition(source_operation['op_id'], OperationStatus.COMPLETED)
    return result.artifact_id


def _restore(
    store,
    clock,
    operations: OperationService,
    backups: BackupService,
    *,
    world_id: str,
    artifact_id: str,
    world_dir: Path,
    backup_dir: Path,
    staging_dir: Path,
    operation_id: str,
    was_running: bool = False,
    restart_probe=None,
) -> RestoreService:
    service = RestoreService(store, clock, operations, backups, restart_probe)
    service.restore(
        world_id=world_id,
        artifact_id=artifact_id,
        world_dir=world_dir,
        backup_dir=backup_dir,
        staging_dir=staging_dir,
        operation_id=operation_id,
        operator_user_id='restore_user',
        was_running=was_running,
    )
    return service


def test_off_only_precondition_precedes_artifact_validation_and_all_side_effects(
    store, clock, tmp_path
):
    world_id = _seed_world(store, state='running')
    calls: list[str] = []

    class BackupSpy:
        def validate_artifact(self, _artifact_id):
            calls.append('validate')
            raise AssertionError('artifact validation must not run')

        def create_world_backup(self, **_kwargs):
            calls.append('pre-backup')
            raise AssertionError('pre-backup must not run')

    world_dir = tmp_path / 'world'
    backup_dir = tmp_path / 'backups'
    staging_dir = tmp_path / 'staging'
    before_artifacts = store.reader().execute(
        'SELECT COUNT(*) AS n FROM backup_artifacts'
    ).fetchone()['n']

    with pytest.raises(RestorePreconditionError) as error:
        _restore(
            store,
            clock,
            OperationService(store, clock),
            BackupSpy(),
            world_id=world_id,
            artifact_id='missing-artifact',
            world_dir=world_dir,
            backup_dir=backup_dir,
            staging_dir=staging_dir,
            operation_id='not-created',
        )

    assert error.value.code == 'WORLD_NOT_OFF'
    assert calls == []
    assert not world_dir.exists()
    assert not backup_dir.exists()
    assert not staging_dir.exists()
    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM backup_artifacts'
    ).fetchone()['n'] == before_artifacts
    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM restore_history'
    ).fetchone()['n'] == 0


def test_mandatory_pre_restore_backup_failure_leaves_world_untouched(
    store, clock, tmp_path
):
    world_id = _seed_world(store)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    (world_dir / 'level.dat').write_bytes(b'original')
    calls: list[str] = []

    class FailedPreBackup:
        def validate_artifact(self, _artifact_id):
            calls.append('validate')
            return {}

        def create_world_backup(self, **_kwargs):
            calls.append('pre-backup')
            raise OSError('pre-restore backup failed')

    operations = OperationService(store, clock)
    restore_operation = _create_operation(operations, world_id, OperationType.RESTORE)
    with pytest.raises(OSError, match='pre-restore backup failed'):
        _restore(
            store,
            clock,
            operations,
            FailedPreBackup(),
            world_id=world_id,
            artifact_id='valid-source',
            world_dir=world_dir,
            backup_dir=tmp_path / 'backups',
            staging_dir=tmp_path / 'staging',
            operation_id=restore_operation['op_id'],
        )

    assert calls == ['validate', 'pre-backup']
    assert (world_dir / 'level.dat').read_bytes() == b'original'
    assert not (tmp_path / 'staging').exists()
    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM restore_history'
    ).fetchone()['n'] == 0


def test_restore_marks_structurally_unsafe_archive_suspect_before_staging(
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
    artifact_id = _seed_artifact(store, clock, world_id, source_dir, backup_dir)
    artifact_path = Path(
        store.reader().execute(
            'SELECT storage_path FROM backup_artifacts WHERE artifact_id = ?',
            (artifact_id,),
        ).fetchone()['storage_path']
    )
    with zipfile.ZipFile(artifact_path, 'w') as archive:
        archive.writestr('../escaped.txt', b'unsafe')
    checksum = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    store.writer().execute(
        'UPDATE backup_artifacts SET checksum = ? WHERE artifact_id = ?',
        (checksum, artifact_id),
    )
    store.writer().commit()
    operations = OperationService(store, clock)
    restore_operation = _create_operation(operations, world_id, OperationType.RESTORE)

    with pytest.raises(BackupIntegrityError, match='valid zip'):
        _restore(
            store,
            clock,
            operations,
            _backup_service(store, clock),
            world_id=world_id,
            artifact_id=artifact_id,
            world_dir=world_dir,
            backup_dir=backup_dir,
            staging_dir=tmp_path / 'staging',
            operation_id=restore_operation['op_id'],
        )

    assert store.reader().execute(
        'SELECT suspect FROM backup_artifacts WHERE artifact_id = ?', (artifact_id,)
    ).fetchone()['suspect'] == 1
    assert (world_dir / 'level.dat').read_bytes() == b'original'
    assert not (tmp_path / 'staging').exists()
    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM restore_history'
    ).fetchone()['n'] == 0


def test_switch_failure_restores_archived_world_before_propagating(
    store, clock, tmp_path, monkeypatch
):
    world_id = _seed_world(store)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    (world_dir / 'level.dat').write_bytes(b'original')
    source_dir = tmp_path / 'source'
    source_dir.mkdir()
    (source_dir / 'level.dat').write_bytes(b'replacement')
    backup_dir = tmp_path / 'backups'
    artifact_id = _seed_artifact(store, clock, world_id, source_dir, backup_dir)
    operations = OperationService(store, clock)
    restore_operation = _create_operation(operations, world_id, OperationType.RESTORE)
    real_move = restore_module.shutil.move
    move_count = 0

    def fail_stage_publish(source, destination):
        nonlocal move_count
        move_count += 1
        if move_count == 2:
            raise OSError('staged world publish failed')
        return real_move(source, destination)

    monkeypatch.setattr(restore_module.shutil, 'move', fail_stage_publish)
    with pytest.raises(OSError, match='staged world publish failed'):
        _restore(
            store,
            clock,
            operations,
            _backup_service(store, clock),
            world_id=world_id,
            artifact_id=artifact_id,
            world_dir=world_dir,
            backup_dir=backup_dir,
            staging_dir=tmp_path / 'staging',
            operation_id=restore_operation['op_id'],
        )

    assert (world_dir / 'level.dat').read_bytes() == b'original'
    assert not list(tmp_path.glob('world.restore-archive-*'))
    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM restore_history'
    ).fetchone()['n'] == 0


def test_failed_start_probe_marks_source_suspect_and_compensates(
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
    artifact_id = _seed_artifact(store, clock, world_id, source_dir, backup_dir)
    operations = OperationService(store, clock)
    restore_operation = _create_operation(operations, world_id, OperationType.RESTORE)

    class FailedStartProbe:
        def restart_and_confirm(self, _world_id: str) -> bool:
            return False

    result = RestoreService(
        store, clock, operations, _backup_service(store, clock), FailedStartProbe()
    ).restore(
        world_id=world_id,
        artifact_id=artifact_id,
        world_dir=world_dir,
        backup_dir=backup_dir,
        staging_dir=tmp_path / 'staging',
        operation_id=restore_operation['op_id'],
        operator_user_id='restore_user',
        was_running=True,
    )

    source = store.reader().execute(
        'SELECT suspect FROM backup_artifacts WHERE artifact_id = ?', (artifact_id,)
    ).fetchone()
    original_history = store.reader().execute(
        'SELECT outcome FROM restore_history WHERE restore_id = ?', (result.restore_id,)
    ).fetchone()
    compensation = store.reader().execute(
        'SELECT compensates_operation_id FROM operations WHERE op_id = ?',
        (result.rollback_operation_id,),
    ).fetchone()
    assert result.outcome == 'reverted'
    assert result.rollback_operation_id is not None
    assert compensation['compensates_operation_id'] == restore_operation['op_id']
    assert original_history['outcome'] == 'reverted'
    assert source['suspect'] == 1
    assert (world_dir / 'level.dat').read_bytes() == b'original'


def test_failed_compensation_records_failure_and_leaves_world_in_error(
    store, clock, tmp_path, monkeypatch
):
    world_id = _seed_world(store)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    (world_dir / 'level.dat').write_bytes(b'original')
    source_dir = tmp_path / 'source'
    source_dir.mkdir()
    (source_dir / 'level.dat').write_bytes(b'replacement')
    backup_dir = tmp_path / 'backups'
    artifact_id = _seed_artifact(store, clock, world_id, source_dir, backup_dir)
    operations = OperationService(store, clock)
    restore_operation = _create_operation(operations, world_id, OperationType.RESTORE)
    backups = _backup_service(store, clock)
    extract = backups.extract_to_staging
    extract_count = 0

    def fail_compensating_extract(selected_artifact, staging_dir):
        nonlocal extract_count
        extract_count += 1
        if extract_count == 2:
            raise OSError('compensating extraction failed')
        return extract(selected_artifact, staging_dir)

    monkeypatch.setattr(backups, 'extract_to_staging', fail_compensating_extract)

    class FailedStartProbe:
        def restart_and_confirm(self, _world_id: str) -> bool:
            return False

    with pytest.raises(OSError, match='compensating extraction failed'):
        RestoreService(
            store, clock, operations, backups, FailedStartProbe()
        ).restore(
            world_id=world_id,
            artifact_id=artifact_id,
            world_dir=world_dir,
            backup_dir=backup_dir,
            staging_dir=tmp_path / 'staging',
            operation_id=restore_operation['op_id'],
            operator_user_id='restore_user',
            was_running=True,
        )

    history = store.reader().execute(
        'SELECT outcome FROM restore_history WHERE operation_id = ?',
        (restore_operation['op_id'],),
    ).fetchone()
    state = store.reader().execute(
        'SELECT state FROM world_instances WHERE world_id = ?', (world_id,)
    ).fetchone()
    rollback = store.reader().execute(
        """
        SELECT status, error_code FROM operations
        WHERE op_type = ? AND op_id <> ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (OperationType.RESTORE.value, restore_operation['op_id']),
    ).fetchone()
    assert history['outcome'] == 'failed'
    assert state['state'] == 'error'
    assert rollback['status'] == OperationStatus.FAILED.value
    assert rollback['error_code'] == 'RESTORE_REVERT_FAILED'
