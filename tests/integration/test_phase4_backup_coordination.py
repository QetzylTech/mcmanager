from __future__ import annotations

import hashlib
import os
import time
import zipfile
from pathlib import Path

import pytest

from app.domain.value_objects import ActorType, OperationType, TriggerType
from app.infrastructure.backup_engine import NativeBackupEngine
from app.ports.filesystem import DiskUsage
from app.services.backup import BackupIntegrityError, BackupService
from app.services.operations import OperationInput, OperationService
from app.services.save_coordination import RconSaveCoordinator

from .test_phase3_control_plane import _seed_world


class TestFilesystem:
    def disk_usage(self, path: Path) -> DiskUsage:
        return DiskUsage(total=10**15, used=0, free=10**15)

    def modified_at(self, path: Path) -> float:
        return path.stat().st_mtime

    def tree_size(self, path: Path) -> int:
        return sum(item.stat().st_size for item in path.rglob('*') if item.is_file())

    def is_within(self, path: Path, root: Path) -> bool:
        return path.is_relative_to(root)


class RecordingCoordinator:
    def __init__(
        self,
        events: list[str],
        *,
        level_dat: Path,
        fail_at: str | None = None,
        refresh_on_flush: bool = True,
    ) -> None:
        self.events = events
        self.level_dat = level_dat
        self.fail_at = fail_at
        self.refresh_on_flush = refresh_on_flush

    def _record(self, step: str) -> None:
        self.events.append(step)
        if self.fail_at == step:
            raise RuntimeError(f'{step} failed')

    def suspend_autosave(self, world_id: str) -> None:
        self._record('save-off')

    def flush(self, world_id: str) -> None:
        self._record('save-all')
        if self.refresh_on_flush:
            self.level_dat.write_bytes(b'flushed world state')
            self.level_dat.touch()

    def resume_autosave(self, world_id: str) -> None:
        self._record('save-on')


def _backup_operation(store, clock, world_id: str) -> str:
    return OperationService(store, clock).create(
        OperationInput(
            op_type=OperationType.BACKUP,
            actor_type=ActorType.SYSTEM,
            world_id=world_id,
        )
    )['op_id']


class ObservedEngine(NativeBackupEngine):
    def __init__(self, events: list[str], store) -> None:
        self.events = events
        self.store = store

    def create_archive(self, source_dir: Path, target_zip_path: Path) -> int:
        self.events.append('capture')
        return super().create_archive(source_dir, target_zip_path)

    def verify_archive(self, path: Path) -> None:
        self.events.append('verify')
        count = self.store.reader().execute(
            'SELECT COUNT(*) AS n FROM backup_artifacts'
        ).fetchone()['n']
        assert count == 0
        super().verify_archive(path)


def test_running_backup_flushes_before_capture_verifies_before_registration_and_resumes(
    store, clock, tmp_path
):
    world_id = _seed_world(store)
    operation_id = _backup_operation(store, clock, world_id)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    level_dat = world_dir / 'level.dat'
    level_dat.write_bytes(b'old world state')
    old_mtime = time.time() - 60
    os.utime(level_dat, (old_mtime, old_mtime))
    events: list[str] = []
    coordinator = RecordingCoordinator(events, level_dat=level_dat)
    service = BackupService(
        store,
        clock,
        coordinator,
        engine=ObservedEngine(events, store),
        filesystem=TestFilesystem(),
    )

    result = service.create_world_backup(
        world_id=world_id,
        world_dir=world_dir,
        backup_dir=tmp_path / 'backups',
        operation_id=operation_id,
        category=TriggerType.MANUAL,
        running=True,
    )

    assert events == [
        'save-off',
        'save-all',
        'capture',
        'verify',
        'verify',
        'save-on',
    ]
    with zipfile.ZipFile(result.storage_path) as archive:
        assert archive.read('level.dat') == b'flushed world state'
    artifact = Path(result.storage_path)
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == result.checksum
    row = store.reader().execute(
        'SELECT checksum, storage_path FROM backup_artifacts WHERE artifact_id = ?',
        (result.artifact_id,),
    ).fetchone()
    assert dict(row) == {'checksum': result.checksum, 'storage_path': str(artifact)}


@pytest.mark.parametrize(
    ('fail_at', 'expected_events'),
    [
        ('save-off', ['save-off', 'save-on']),
        ('save-all', ['save-off', 'save-all', 'save-on']),
    ],
)
def test_running_backup_attempts_save_on_and_does_not_register_on_rcon_failure(
    store, clock, tmp_path, fail_at, expected_events
):
    world_id = _seed_world(store)
    operation_id = _backup_operation(store, clock, world_id)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    level_dat = world_dir / 'level.dat'
    level_dat.write_bytes(b'world state')
    events: list[str] = []
    coordinator = RecordingCoordinator(events, level_dat=level_dat, fail_at=fail_at)
    service = BackupService(
        store,
        clock,
        coordinator,
        engine=NativeBackupEngine(),
        filesystem=TestFilesystem(),
    )

    with pytest.raises(RuntimeError, match=f'{fail_at} failed'):
        service.create_world_backup(
            world_id=world_id,
            world_dir=world_dir,
            backup_dir=tmp_path / 'backups',
            operation_id=operation_id,
            category=TriggerType.MANUAL,
            running=True,
        )

    assert events == expected_events
    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM backup_artifacts WHERE operation_id = ?',
        (operation_id,),
    ).fetchone()['n'] == 0


def test_stale_level_dat_aborts_capture_and_still_resumes_autosave(
    store, clock, tmp_path
):
    world_id = _seed_world(store)
    operation_id = _backup_operation(store, clock, world_id)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    level_dat = world_dir / 'level.dat'
    level_dat.write_bytes(b'stale world state')
    old_mtime = time.time() - 60
    os.utime(level_dat, (old_mtime, old_mtime))
    events: list[str] = []
    coordinator = RecordingCoordinator(
        events, level_dat=level_dat, refresh_on_flush=False
    )
    service = BackupService(
        store,
        clock,
        coordinator,
        engine=NativeBackupEngine(),
        filesystem=TestFilesystem(),
    )

    with pytest.raises(BackupIntegrityError, match='LEVEL_DAT_FLUSH_UNVERIFIED'):
        service.create_world_backup(
            world_id=world_id,
            world_dir=world_dir,
            backup_dir=tmp_path / 'backups',
            operation_id=operation_id,
            category=TriggerType.MANUAL,
            running=True,
        )

    assert events == ['save-off', 'save-all', 'save-on']
    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM backup_artifacts WHERE operation_id = ?',
        (operation_id,),
    ).fetchone()['n'] == 0


def test_recent_level_dat_still_requires_a_post_flush_mtime_change(
    store, clock, tmp_path
):
    world_id = _seed_world(store)
    operation_id = _backup_operation(store, clock, world_id)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    level_dat = world_dir / 'level.dat'
    level_dat.write_bytes(b'unchanged recent world state')
    recent_mtime = time.time() - 2
    os.utime(level_dat, (recent_mtime, recent_mtime))
    events: list[str] = []
    coordinator = RecordingCoordinator(
        events, level_dat=level_dat, refresh_on_flush=False
    )
    service = BackupService(
        store,
        clock,
        coordinator,
        engine=NativeBackupEngine(),
        filesystem=TestFilesystem(),
    )

    with pytest.raises(BackupIntegrityError, match='LEVEL_DAT_FLUSH_UNVERIFIED'):
        service.create_world_backup(
            world_id=world_id,
            world_dir=world_dir,
            backup_dir=tmp_path / 'backups',
            operation_id=operation_id,
            category=TriggerType.MANUAL,
            running=True,
        )

    assert events == ['save-off', 'save-all', 'save-on']
    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM backup_artifacts WHERE operation_id = ?',
        (operation_id,),
    ).fetchone()['n'] == 0


def test_unverified_archive_is_not_registered(store, clock, tmp_path):
    world_id = _seed_world(store)
    operation_id = _backup_operation(store, clock, world_id)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    (world_dir / 'level.dat').write_bytes(b'world state')

    class InvalidArchiveEngine(NativeBackupEngine):
        def create_archive(self, source_dir: Path, target_zip_path: Path) -> int:
            target_zip_path.write_bytes(b'not a zip')
            return 0

        def verify_archive(self, path: Path) -> None:
            raise ValueError('invalid archive')

    service = BackupService(
        store,
        clock,
        engine=InvalidArchiveEngine(),
        filesystem=TestFilesystem(),
    )

    with pytest.raises(BackupIntegrityError, match='failed archive verification'):
        service.create_world_backup(
            world_id=world_id,
            world_dir=world_dir,
            backup_dir=tmp_path / 'backups',
            operation_id=operation_id,
            category=TriggerType.MANUAL,
        )

    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM backup_artifacts WHERE operation_id = ?',
        (operation_id,),
    ).fetchone()['n'] == 0
    assert not list((tmp_path / 'backups').glob('*.part'))


def test_local_backup_succeeds_without_remote_sync_or_rcon(store, clock, tmp_path):
    world_id = _seed_world(store)
    operation_id = _backup_operation(store, clock, world_id)
    world_dir = tmp_path / 'world'
    world_dir.mkdir()
    (world_dir / 'level.dat').write_bytes(b'offline world state')

    result = BackupService(
        store,
        clock,
        engine=NativeBackupEngine(),
        filesystem=TestFilesystem(),
    ).create_world_backup(
        world_id=world_id,
        world_dir=world_dir,
        backup_dir=tmp_path / 'backups',
        operation_id=operation_id,
        category=TriggerType.MANUAL,
    )

    assert Path(result.storage_path).is_file()
    assert store.reader().execute(
        'SELECT COUNT(*) AS n FROM sync_records'
    ).fetchone()['n'] == 0


def test_rcon_save_coordinator_uses_closed_save_command_sequence(monkeypatch):
    events: list[str] = []

    class Client:
        def command(self, command: str) -> str:
            events.append(command)
            return ''

        def close(self) -> None:
            pass

    coordinator = RconSaveCoordinator(None, None)
    monkeypatch.setattr(coordinator, '_connect', lambda world_id: Client())

    coordinator.suspend_autosave('world')
    coordinator.flush('world')
    coordinator.resume_autosave('world')

    assert events == ['save-off', 'save-all', 'save-on']
