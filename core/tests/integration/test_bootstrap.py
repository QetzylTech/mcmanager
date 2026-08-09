"""Composition root wiring (Doc 12 §5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.bootstrap import Container, build_container
from app.infrastructure.sqlite.connection import PersistenceError
from app.services.audit import AuditService
from app.services.auth import AuthenticationService
from app.services.notifications import NotificationService


def test_build_container_wires_all_services(container: Container) -> None:
    assert isinstance(container.auth, AuthenticationService)
    assert isinstance(container.audit, AuditService)
    assert isinstance(container.notifications, NotificationService)
    assert container.store is not None
    assert container.secrets is not None
    assert container.process_adapter is not None


def test_build_container_applies_migrations(
    database_path, keyfile_path, migrations_dir, clock
) -> None:
    container = build_container(
        database_path=database_path,
        keyfile_path=keyfile_path,
        migrations_dir=migrations_dir,
        clock=clock,
    )
    try:
        count = container.store.reader().execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        assert count == 27
    finally:
        container.store.close()


def test_build_container_provisions_keyfile(tmp_path, migrations_dir, clock) -> None:
    keyfile = tmp_path / 'nested' / 'secrets.key'
    container = build_container(
        database_path=tmp_path / 'db.sqlite',
        keyfile_path=keyfile,
        migrations_dir=migrations_dir,
        clock=clock,
    )
    try:
        assert keyfile.exists()
        assert keyfile.stat().st_size > 0
    finally:
        container.store.close()


def test_build_container_fails_on_missing_migrations_dir(
    database_path, keyfile_path, clock
) -> None:
    with pytest.raises(PersistenceError, match='migrations directory not found'):
        build_container(
            database_path=database_path,
            keyfile_path=keyfile_path,
            migrations_dir=Path('/nonexistent/migrations'),
            clock=clock,
        )
