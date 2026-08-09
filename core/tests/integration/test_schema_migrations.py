"""Schema migration + Global Persistence Invariant (Doc 7 §0, Doc 11 §1.2)."""

from __future__ import annotations

import sqlite3

import pytest

from app.infrastructure.sqlite.connection import SqliteStore
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


def test_foreign_keys_enforced_on_writer_and_reader(store: SqliteStore) -> None:
    verify_foreign_keys_enforced(store.writer())
    verify_foreign_keys_enforced(store.reader())


def test_migrations_are_idempotent(store: SqliteStore, migrations_dir) -> None:
    """Re-running the runner must not re-apply or fail."""
    run_migrations(store, migrations_dir)
    versions = store.reader().execute('SELECT version FROM schema_migrations').fetchall()
    assert len(versions) >= 1


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
