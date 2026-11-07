from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.tuning import STORAGE_GUARD_OVERFLOW_PCT, STORAGE_GUARD_RESERVE_BYTES
from app.infrastructure.filesystem import LocalFilesystem
from app.ports.filesystem import DiskUsage
from app.services.backup import BackupIntegrityError, BackupService


def test_disk_usage_maps_host_values(monkeypatch, tmp_path):
    expected = SimpleNamespace(total=100, used=35, free=65)
    monkeypatch.setattr(shutil, 'disk_usage', lambda path: expected)

    assert LocalFilesystem().disk_usage(tmp_path) == DiskUsage(total=100, used=35, free=65)


def test_modified_at_returns_file_mtime(tmp_path):
    path = tmp_path / 'level.dat'
    path.write_bytes(b'world')
    expected = path.stat().st_mtime

    assert LocalFilesystem().modified_at(path) == expected


def test_level_dat_freshness_accepts_recent_mtime_and_rejects_stale_or_future(
    monkeypatch, tmp_path
):
    path = tmp_path / 'level.dat'
    path.write_bytes(b'world')
    service = BackupService.__new__(BackupService)
    service._filesystem = LocalFilesystem()
    now = path.stat().st_mtime
    monkeypatch.setattr('app.services.backup.time.time', lambda: now)

    service._verify_level_dat_flush(path)

    os.utime(path, (now - 31, now - 31))
    with pytest.raises(BackupIntegrityError, match='LEVEL_DAT_FLUSH_UNVERIFIED'):
        service._verify_level_dat_flush(path)

    os.utime(path, (now + 6, now + 6))
    with pytest.raises(BackupIntegrityError, match='LEVEL_DAT_FLUSH_UNVERIFIED'):
        service._verify_level_dat_flush(path)


def test_is_within_rejects_parent_traversal(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()

    assert LocalFilesystem().is_within(root / 'child', root) is True
    assert LocalFilesystem().is_within(root / '..' / 'outside', root) is False


def test_is_within_resolves_symlinks_before_checking_containment(tmp_path):
    root = tmp_path / 'root'
    outside = tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    target = outside / 'secret.dat'
    target.write_bytes(b'secret')
    link = root / 'escape'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f'symlink creation unavailable: {exc}')

    filesystem = LocalFilesystem()
    assert filesystem.is_within(link / 'secret.dat', root) is False


def test_tree_size_counts_only_files_resolving_inside_root_and_skips_temporary_files(
    tmp_path,
):
    root = tmp_path / 'world'
    outside = tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    (root / 'level.dat').write_bytes(b'12345')
    (root / 'region').mkdir()
    (root / 'region' / 'r.0.0.mca').write_bytes(b'1234567')
    (root / 'capture.part').write_bytes(b'not captured')
    (root / 'mcmanager.lock').write_bytes(b'lock')
    (root / 'mcmanager.pid').write_bytes(b'123')
    (outside / 'large.dat').write_bytes(b'outside')
    try:
        (root / 'region-link').symlink_to(root / 'region', target_is_directory=True)
        (root / 'escape.dat').symlink_to(outside / 'large.dat')
        (root / 'external-dir').symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f'symlink creation unavailable: {exc}')

    assert LocalFilesystem().tree_size(root) == len(b'12345') + 2 * len(b'1234567')


@pytest.mark.parametrize(
    ('estimated_size', 'free_space', 'should_pass'),
    [
        (4096, STORAGE_GUARD_RESERVE_BYTES + 4096, True),
        (4096, STORAGE_GUARD_RESERVE_BYTES + 4095, False),
        (
            200 * 1024**3,
            200 * 1024**3
            + max(
                STORAGE_GUARD_RESERVE_BYTES,
                200 * 1024**3 * STORAGE_GUARD_OVERFLOW_PCT // 100,
            )
            - 1,
            False,
        ),
        (
            200 * 1024**3,
            200 * 1024**3
            + max(
                STORAGE_GUARD_RESERVE_BYTES,
                200 * 1024**3 * STORAGE_GUARD_OVERFLOW_PCT // 100,
            ),
            True,
        ),
    ],
)
def test_storage_guard_reserves_estimated_size_plus_larger_headroom(
    tmp_path, estimated_size, free_space, should_pass
):
    class Filesystem:
        def tree_size(self, path: Path) -> int:
            return estimated_size

        def disk_usage(self, path: Path) -> DiskUsage:
            return DiskUsage(total=free_space, used=0, free=free_space)

    service = BackupService.__new__(BackupService)
    service._filesystem = Filesystem()
    backup_dir = tmp_path / 'backups'

    if should_pass:
        service._enforce_storage_guard(tmp_path, backup_dir)
    else:
        with pytest.raises(BackupIntegrityError, match='STORAGE_GUARD_FAILED'):
            service._enforce_storage_guard(tmp_path, backup_dir)
