"""Migration runner + boot-time integrity sweep (Document 7 sections 5-6, 10).

Applied at boot in integer version order via ``schema_migrations``. After all
pending migrations apply, a ``PRAGMA foreign_key_check`` sweep runs: any
violation is a startup-blocking critical error, never silently repaired
(Doc 7 section 0 — Global Persistence Invariant; Doc 12 section 5 step 2).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from app.infrastructure.sqlite.connection import PersistenceError, SqliteStore


def _migration_files(directory: Path) -> list[tuple[int, str, Path]]:
    """Return (version, name, path) tuples sorted by integer version."""
    migrations: list[tuple[int, str, Path]] = []
    for path in sorted(directory.glob('*.sql')):
        version, name = _parse_migration_name(path.name)
        if version is not None:
            migrations.append((version, name, path))
    return sorted(migrations, key=lambda item: item[0])


def _parse_migration_name(filename: str) -> tuple[int | None, str]:
    """Parse ``NNN_name.sql`` into (int version, name)."""
    stem = filename[:-4] if filename.endswith('.sql') else filename
    parts = stem.split('_', 1)
    try:
        return int(parts[0]), parts[1] if len(parts) > 1 else parts[0]
    except ValueError:
        return None, stem


def _applied_versions(connection: sqlite3.Connection) -> set[int]:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if row is None:
        return set()
    return {
        int(version)
        for (version,) in connection.execute('SELECT version FROM schema_migrations')
    }


def _apply_one(connection: sqlite3.Connection, version: int, name: str, path: Path) -> None:
    """Apply a single migration inside its own transaction."""
    sql = path.read_text(encoding='utf-8')
    connection.execute('BEGIN')
    try:
        connection.executescript(sql)
        connection.execute(
            'INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)',
            (version, name, int(time.time())),
        )
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise PersistenceError(f'migration {version} ({name}) failed: {exc}') from exc


def run_migrations(store: SqliteStore, migrations_dir: str | Path) -> None:
    """Apply pending migrations in order, then run the FK sweep.

    Raises :class:`PersistenceError` on any migration failure or any
    ``PRAGMA foreign_key_check`` violation — startup must not proceed.
    """
    directory = Path(migrations_dir)
    if not directory.is_dir():
        raise PersistenceError(f'migrations directory not found: {directory}')

    connection = store.writer()
    applied = _applied_versions(connection)
    pending = [item for item in _migration_files(directory) if item[0] not in applied]

    for version, name, path in pending:
        _apply_one(connection, version, name, path)

    _sweep_foreign_keys(connection)


def _sweep_foreign_keys(connection: sqlite3.Connection) -> None:
    """Boot-time ``PRAGMA foreign_key_check`` sweep (Doc 7 section 0)."""
    violations = connection.execute('PRAGMA foreign_key_check').fetchall()
    if violations:
        rows = '\n'.join(str(tuple(row)) for row in violations[:20])
        raise PersistenceError(
            f'foreign_key_check failed with {len(violations)} violation(s):\n{rows}'
        )


def verify_foreign_keys_enforced(connection: sqlite3.Connection) -> None:
    """Confirms ``PRAGMA foreign_keys = ON`` on the connection (invariant)."""
    ((enabled,),) = connection.execute('PRAGMA foreign_keys').fetchall()
    if not enabled:
        raise PersistenceError('PRAGMA foreign_keys = ON not enforced on connection')
