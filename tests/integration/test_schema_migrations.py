"""Schema migration + Global Persistence Invariant (Doc 7 §0, Doc 11 §1.2)."""

from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.infrastructure.sqlite.connection import PersistenceError, SqliteStore
from app.infrastructure.sqlite.migrations import (
    run_migrations,
    verify_foreign_keys_enforced,
)

_EXPECTED_TABLE_COUNT = 27


def test_fresh_migration_creates_27_tables(store: SqliteStore) -> None:
    rows = store.reader().execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    assert len(rows) == _EXPECTED_TABLE_COUNT


def test_foreign_key_check_passes_after_migration(store: SqliteStore) -> None:
    violations = store.writer().execute('PRAGMA foreign_key_check').fetchall()
    assert violations == []


def test_migration_runner_blocks_on_foreign_key_violations(
    store: SqliteStore, tmp_path: Path
) -> None:
    writer = store.writer()
    writer.execute('PRAGMA foreign_keys = OFF')
    writer.execute('CREATE TABLE fk_sweep_parent (parent_id INTEGER PRIMARY KEY)')
    writer.execute(
        'CREATE TABLE fk_sweep_child (parent_id INTEGER REFERENCES fk_sweep_parent(parent_id))'
    )
    writer.execute('INSERT INTO fk_sweep_child VALUES (1)')
    writer.commit()
    writer.execute('PRAGMA foreign_keys = ON')

    with pytest.raises(PersistenceError, match='foreign_key_check failed'):
        run_migrations(store, tmp_path)


def test_foreign_keys_enforced_on_writer_and_reader(store: SqliteStore) -> None:
    verify_foreign_keys_enforced(store.writer())
    verify_foreign_keys_enforced(store.reader())


def test_migrations_are_idempotent(store: SqliteStore, migrations_dir) -> None:
    """Re-running the runner must not re-apply or fail."""
    run_migrations(store, migrations_dir)
    versions = store.reader().execute('SELECT version FROM schema_migrations').fetchall()
    assert [row['version'] for row in versions] == [1, 2, 3]


def test_failed_migration_rolls_back_ddl_and_version_record(
    store: SqliteStore, tmp_path: Path
) -> None:
    migration = tmp_path / '004_failed_change.sql'
    migration.write_text(
        'CREATE TABLE rollback_probe (value TEXT);'
        "INSERT INTO rollback_probe VALUES ('uncommitted');"
        'THIS IS NOT VALID SQL;',
        encoding='utf-8',
    )

    with pytest.raises(PersistenceError, match='migration 4'):
        run_migrations(store, tmp_path)

    table = store.reader().execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rollback_probe'"
    ).fetchone()
    versions = store.reader().execute(
        'SELECT version FROM schema_migrations ORDER BY version'
    ).fetchall()
    assert table is None
    assert [row['version'] for row in versions] == [1, 2, 3]


def test_sqlite_operational_pragmas_are_applied_per_connection(store: SqliteStore) -> None:
    writer = store.writer()
    reader = store.reader()

    assert writer.execute('PRAGMA journal_mode').fetchone()[0].lower() == 'wal'
    assert writer.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert reader.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert writer.execute('PRAGMA busy_timeout').fetchone()[0] == 5000
    assert reader.execute('PRAGMA busy_timeout').fetchone()[0] == 5000


def test_reader_remains_available_during_writer_transaction(store: SqliteStore) -> None:
    writer = store.writer()
    reader = store.reader()
    writer.execute('CREATE TABLE wal_probe (value TEXT)')
    writer.commit()
    writer.execute('INSERT INTO wal_probe VALUES (?)', ('committed',))
    writer.commit()

    writer.execute('BEGIN IMMEDIATE')
    writer.execute('INSERT INTO wal_probe VALUES (?)', ('uncommitted',))
    rows = reader.execute('SELECT value FROM wal_probe ORDER BY rowid').fetchall()
    writer.rollback()

    assert [row['value'] for row in rows] == ['committed']


def test_busy_writer_waits_for_lock_then_succeeds(
    store: SqliteStore, database_path: str
) -> None:
    writer = store.writer()
    writer.execute('CREATE TABLE busy_probe (value TEXT)')
    writer.commit()
    second_store = SqliteStore(database_path, busy_timeout_ms=1000)
    second_store.open()
    started = threading.Event()

    def insert_after_lock() -> None:
        started.set()
        second_store.writer().execute('INSERT INTO busy_probe VALUES (?)', ('ok',))
        second_store.writer().commit()

    try:
        writer.execute('BEGIN IMMEDIATE')
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(insert_after_lock)
            assert started.wait(timeout=1)
            time.sleep(0.1)
            writer.commit()
            future.result(timeout=3)

        assert writer.execute('SELECT value FROM busy_probe').fetchall()[0]['value'] == 'ok'
    finally:
        second_store.close()


def test_parallel_writers_do_not_leak_database_locked_errors(
    store: SqliteStore, database_path: str
) -> None:
    store.writer().execute('CREATE TABLE concurrent_probe (value INTEGER)')
    store.writer().commit()
    peers = [SqliteStore(database_path) for _ in range(4)]
    for peer in peers:
        peer.open()
        verify_foreign_keys_enforced(peer.writer())
        verify_foreign_keys_enforced(peer.reader())

    def insert_batch(peer: SqliteStore, offset: int) -> None:
        connection = peer.writer()
        for value in range(offset, offset + 10):
            connection.execute('INSERT INTO concurrent_probe VALUES (?)', (value,))
        connection.commit()

    try:
        with ThreadPoolExecutor(max_workers=len(peers)) as executor:
            futures = [
                executor.submit(insert_batch, peer, offset * 10)
                for offset, peer in enumerate(peers)
            ]
            for future in futures:
                future.result(timeout=10)
    finally:
        for peer in peers:
            peer.close()

    count = store.writer().execute('SELECT count(*) FROM concurrent_probe').fetchone()[0]
    assert count == 40


def test_audit_records_triggers_exist(store: SqliteStore) -> None:
    triggers = store.reader().execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_records'"
    ).fetchall()
    names = {row['name'] for row in triggers}
    assert 'trg_audit_records_no_update' in names
    assert 'trg_audit_records_no_delete' in names


def test_tier1_tables_have_no_deleted_at(store: SqliteStore) -> None:
    tier1 = (
        'audit_records',
        'notifications',
        'notification_reads',
        'missed_run_records',
        'sync_records',
        'sync_attempts',
    )
    for table in tier1:
        columns = store.reader().execute(f'PRAGMA table_info({table})').fetchall()
        column_names = {row['name'] for row in columns}
        assert 'deleted_at' not in column_names, f'{table} must not have deleted_at'


def test_invalid_fk_insert_rejected(store: SqliteStore) -> None:
    """Global Persistence Invariant: FK violations fail at write time."""
    with pytest.raises(sqlite3.IntegrityError):
        store.writer().execute(
            'INSERT INTO users ('
            '  user_id, username, secret_id, status, failed_login_count,'
            '  created_at, updated_at'
            ') VALUES (?, ?, ?, ?, 0, 1, 1)',
            ('u_bad', 'ghost', 'sec_nonexistent', 'active'),
        )
