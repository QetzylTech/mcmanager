"""Gate 2 shared fixtures (Document 11 section 1.2/1.3).

Every Gate 2 test runs against a REAL SQLite file with the full 27-table
schema applied through the production migration runner — foreign_keys=ON on
every connection plus the boot FK sweep (Global Persistence Invariant) is
exactly the production boot path (ARCHITECTURE section 9).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.bootstrap import build_container
from app.infrastructure.sqlite.connection import SqliteStore
from app.infrastructure.sqlite.migrations import run_migrations


class FakeClock:
    """Deterministic epoch-seconds clock (Document 11 section 1.1)."""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture
def migrations_dir() -> Path:
    return Path(__file__).resolve().parents[1] / 'migrations'


@pytest.fixture
def database_path(tmp_path) -> str:
    return str(tmp_path / 'manager.db')


@pytest.fixture
def keyfile_path(tmp_path) -> str:
    return str(tmp_path / 'secrets.key')


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(database_path, migrations_dir) -> SqliteStore:
    """Raw store with migrations + boot FK sweep applied (schema tests)."""
    store = SqliteStore(database_path)
    store.open()
    try:
        run_migrations(store, migrations_dir)
    except Exception:
        store.close()
        raise
    return store


@pytest.fixture
def container(tmp_path, migrations_dir, clock):
    """Full composition root — the exact production wiring (Doc 12 §5)."""
    database = str(tmp_path / 'manager.db')
    keyfile = str(tmp_path / 'secrets.key')
    container = build_container(
        database_path=database,
        keyfile_path=keyfile,
        migrations_dir=migrations_dir,
        clock=clock,
    )
    yield container
    container.store.close()
