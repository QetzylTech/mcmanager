from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

import pytest

from app.infrastructure import backup_engine as backup_engine_module
from app.infrastructure.backup_engine import NativeBackupEngine


def test_create_archive_uses_deflate_and_publishes_staged_zip_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / 'world'
    source.mkdir()
    (source / 'level.dat').write_bytes(b'world data' * 100)
    target = tmp_path / 'backup.zip'
    target.write_bytes(b'previous artifact')
    engine = NativeBackupEngine()
    zip_calls: list[tuple[Path, str, int, int | None]] = []
    replace_calls: list[tuple[Path, Path]] = []
    original_zip_file = zipfile.ZipFile
    original_replace = os.replace

    def observe_zip_file(
        file: str | Path,
        mode: str = 'r',
        compression: int = zipfile.ZIP_STORED,
        allowZip64: bool = True,
        compresslevel: int | None = None,
        **kwargs: object,
    ) -> zipfile.ZipFile:
        zip_calls.append((Path(file), mode, compression, compresslevel))
        return original_zip_file(
            file,
            mode,
            compression,
            allowZip64=allowZip64,
            compresslevel=compresslevel,
            **kwargs,
        )

    def observe_replace(source_path: str | Path, target_path: str | Path) -> None:
        staged = Path(source_path)
        published = Path(target_path)
        assert staged.name == f'{target.name}.part'
        assert staged.is_file()
        assert published == target
        assert published.read_bytes() == b'previous artifact'
        replace_calls.append((staged, published))
        original_replace(source_path, target_path)

    monkeypatch.setattr(backup_engine_module.zipfile, 'ZipFile', observe_zip_file)
    monkeypatch.setattr(os, 'replace', observe_replace)

    assert engine.create_archive(source, target) == 0

    assert zip_calls[0][1:] == ('w', zipfile.ZIP_DEFLATED, 6)
    assert zip_calls[0][0].name == f'{target.name}.part'
    assert len(replace_calls) == 1
    assert not Path(f'{target}.part').exists()
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert archive.read('level.dat') == b'world data' * 100


def test_sha256_hashes_the_published_archive(tmp_path: Path) -> None:
    archive_path = tmp_path / 'archive.zip'
    archive_path.write_bytes(b'complete archive bytes')

    assert NativeBackupEngine().sha256(archive_path) == hashlib.sha256(
        b'complete archive bytes'
    ).hexdigest()


def test_extract_archive_rejects_traversal_and_removes_partial_staging(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / 'malicious.zip'
    staging = tmp_path / 'staging'
    outside = tmp_path / 'outside.txt'
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('valid/file.txt', b'valid')
        archive.writestr('../outside.txt', b'escape')
    staging.mkdir()

    engine = NativeBackupEngine()
    with pytest.raises(ValueError, match='escapes staging'):
        engine.extract_archive(archive_path, staging)

    assert not staging.exists()
    assert not outside.exists()
    with pytest.raises(ValueError, match='escapes staging'):
        engine.verify_archive(archive_path)


def test_extract_archive_removes_staging_when_member_crc_fails(tmp_path: Path) -> None:
    archive_path = tmp_path / 'corrupt.zip'
    staging = tmp_path / 'staging'
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('valid.txt', b'valid payload')
        archive.writestr('corrupt.txt', b'corrupt payload')
    contents = archive_path.read_bytes()
    archive_path.write_bytes(contents.replace(b'corrupt payload', b'corrupt payloAd'))
    staging.mkdir()

    with pytest.raises(zipfile.BadZipFile):
        NativeBackupEngine().extract_archive(archive_path, staging)

    assert not staging.exists()


def test_create_archive_follows_in_root_directory_links_and_skips_escaping_links(
    tmp_path: Path,
) -> None:
    source = tmp_path / 'world'
    region = source / 'region'
    outside = tmp_path / 'outside'
    region.mkdir(parents=True)
    outside.mkdir()
    (region / 'data.mca').write_bytes(b'in-root data')
    (outside / 'secret.dat').write_bytes(b'outside data')
    try:
        (source / 'region-link').symlink_to(region, target_is_directory=True)
        (source / 'escape').symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f'symlink creation unavailable: {exc}')
    target = tmp_path / 'backup.zip'

    skipped = NativeBackupEngine().create_archive(source, target)

    assert skipped == 1
    with zipfile.ZipFile(target) as archive:
        assert archive.read('region/data.mca') == b'in-root data'
        assert archive.read('region-link/data.mca') == b'in-root data'
        assert 'escape/secret.dat' not in archive.namelist()


@pytest.mark.parametrize('failure_point', ['write', 'verify', 'publish'])
def test_create_archive_cleans_staging_and_preserves_existing_target_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    source = tmp_path / 'world'
    source.mkdir()
    (source / 'level.dat').write_bytes(b'world data')
    target = tmp_path / 'backup.zip'
    target.write_bytes(b'previous artifact')
    engine = NativeBackupEngine()

    if failure_point == 'write':
        def fail_write(
            self: zipfile.ZipFile, *args: object, **kwargs: object
        ) -> None:
            raise OSError('simulated archive write failure')

        monkeypatch.setattr(zipfile.ZipFile, 'write', fail_write)
        expected = 'simulated archive write failure'
    elif failure_point == 'verify':
        def fail_verify(path: Path) -> None:
            raise OSError('simulated archive verification failure')

        monkeypatch.setattr(engine, 'verify_archive', fail_verify)
        expected = 'simulated archive verification failure'
    else:
        def fail_replace(source_path: str | Path, target_path: str | Path) -> None:
            raise OSError('simulated publication failure')

        monkeypatch.setattr(os, 'replace', fail_replace)
        expected = 'simulated publication failure'

    with pytest.raises(OSError, match=expected):
        engine.create_archive(source, target)

    assert target.read_bytes() == b'previous artifact'
    assert not Path(f'{target}.part').exists()
