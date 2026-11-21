from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from app.domain.tuning import CLEANUP_BLAST_RADIUS_CAP
from app.domain.value_objects import ActorType, OperationStatus, OperationType
from app.infrastructure.filesystem import LocalFilesystem
from app.ports.filesystem import DiskUsage
from app.services.cleanup import CleanupCandidate, CleanupService, RetentionError
from app.services.operations import OperationInput, OperationService

from .test_phase3_control_plane import _seed_world

DAY = 24 * 60 * 60


class FixedUsageFilesystem(LocalFilesystem):
    def __init__(self, *, used: int) -> None:
        self.used = used

    def disk_usage(self, path: Path) -> DiskUsage:
        return DiskUsage(total=100, used=self.used, free=100 - self.used)


def _create_operation(store, clock, world_id: str, op_type: OperationType):
    return OperationService(store, clock).create(
        OperationInput(
            op_type=op_type,
            actor_type=ActorType.SYSTEM,
            world_id=world_id,
        )
    )


def _cleanup_service(store, clock, **kwargs) -> CleanupService:
    kwargs.setdefault('filesystem', LocalFilesystem())
    return CleanupService(store, clock, **kwargs)


def _seed_artifacts(store, clock, tmp_path, world_id: str, specs, *, create_files=True):
    backup_operation = _create_operation(store, clock, world_id, OperationType.BACKUP)
    connection = store.writer()
    paths = {}
    for artifact_id, category, age_seconds in specs:
        path = tmp_path / f'{artifact_id}.zip'
        if create_files:
            path.write_bytes(b'backup')
        paths[artifact_id] = path
        connection.execute(
            """
            INSERT INTO backup_artifacts (
                artifact_id, world_id, category, storage_path, size_bytes, checksum,
                suspect, operation_id, deleted_at, deleted_by, created_at
            ) VALUES (?, ?, ?, ?, 6, ?, 0, ?, NULL, NULL, ?)
            """,
            (
                artifact_id,
                world_id,
                category,
                str(path),
                '0' * 64,
                backup_operation['op_id'],
                int(clock.now()) - age_seconds,
            ),
        )
    connection.commit()
    OperationService(store, clock).transition(backup_operation['op_id'], OperationStatus.COMPLETED)
    return paths


def test_cleanup_floor_boundaries_and_newest_three_are_per_category(store, clock, tmp_path):
    world_id = _seed_world(store)
    specs = []
    for index, age_days in enumerate((10, 9, 8, 7, 6)):
        specs.append((f'manual_{index}', 'manual', age_days * DAY))
    for index, age_days in enumerate((11, 10, 9, 8)):
        specs.append((f'pre_restore_{index}', 'pre_restore', age_days * DAY))
    for index, age_days in enumerate((6, 5, 4, 3)):
        specs.append((f'emergency_{index}', 'emergency', age_days * DAY))
    paths = _seed_artifacts(store, clock, tmp_path, world_id, specs)
    cleanup = _cleanup_service(store, clock)

    with pytest.raises(RetentionError, match='age floor'):
        cleanup.backup_candidates(older_than_days=2)
    with pytest.raises(RetentionError, match='count floor'):
        cleanup.backup_candidates(older_than_days=3, keep_per_category=2)

    candidates = cleanup.backup_candidates(older_than_days=3, keep_per_category=3)

    assert {candidate.artifact_id for candidate in candidates} == {
        'manual_0',
        'manual_1',
        'pre_restore_0',
        'emergency_0',
    }
    assert all(paths[candidate.artifact_id].is_file() for candidate in candidates)


def test_cleanup_three_day_cutoff_is_strict_and_one_second_older_is_eligible(
    store, clock, tmp_path
):
    world_id = _seed_world(store)
    cutoff_age = 3 * DAY
    _seed_artifacts(
        store,
        clock,
        tmp_path,
        world_id,
        [
            ('cutoff_oldest', 'manual', cutoff_age + 1),
            ('cutoff_newer_1', 'manual', cutoff_age),
            ('cutoff_newer_2', 'manual', cutoff_age - 1),
            ('cutoff_newer_3', 'manual', cutoff_age - 2),
        ],
    )

    candidates = _cleanup_service(store, clock).backup_candidates(older_than_days=3)

    assert [candidate.artifact_id for candidate in candidates] == ['cutoff_oldest']


def test_dry_and_wet_runs_are_durable_operations_bound_to_exact_preview(store, clock, tmp_path):
    world_id = _seed_world(store)
    paths = _seed_artifacts(
        store,
        clock,
        tmp_path,
        world_id,
        [(f'preview_{index}', 'manual', (10 - index) * DAY) for index in range(5)],
    )
    operations = OperationService(store, clock)
    cleanup = _cleanup_service(store, clock)
    preview_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)

    preview = cleanup.evaluate_and_execute_cleanup(
        op_id=preview_operation['op_id'],
        world_id=world_id,
        dry_run=True,
    )

    assert preview['mode'] == 'dry_run'
    assert preview['target_count'] == 2
    assert all(path.is_file() for path in paths.values())
    preview_row = (
        store.reader()
        .execute(
            'SELECT status, data_json FROM operations WHERE op_id = ?',
            (preview_operation['op_id'],),
        )
        .fetchone()
    )
    assert preview_row['status'] == OperationStatus.COMPLETED.value
    assert '"preview_0"' in preview_row['data_json']

    changed_path = tmp_path / 'changed.zip'
    changed_path.write_bytes(b'new target')
    store.writer().execute(
        "UPDATE backup_artifacts SET storage_path = ? WHERE artifact_id = 'preview_0'",
        (str(changed_path),),
    )
    store.writer().commit()
    wet_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)

    with pytest.raises(RetentionError, match='CLEANUP_PREVIEW_REQUIRED_OR_STALE'):
        cleanup.evaluate_and_execute_cleanup(
            op_id=wet_operation['op_id'],
            world_id=world_id,
            dry_run=False,
            dry_run_operation_id=preview_operation['op_id'],
        )

    assert paths['preview_0'].is_file()
    assert changed_path.is_file()
    wet_row = (
        store.reader()
        .execute('SELECT status FROM operations WHERE op_id = ?', (wet_operation['op_id'],))
        .fetchone()
    )
    assert wet_row['status'] == OperationStatus.FAILED.value
    assert operations.get(wet_operation['op_id'])['status'] == OperationStatus.FAILED.value


def test_wet_run_deletes_only_confirmed_preview_targets_after_service_recreation(
    store, clock, tmp_path
):
    world_id = _seed_world(store)
    paths = _seed_artifacts(
        store,
        clock,
        tmp_path,
        world_id,
        [(f'confirmed_{index}', 'manual', (10 - index) * DAY) for index in range(5)],
    )
    preview_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)
    preview = _cleanup_service(store, clock).evaluate_and_execute_cleanup(
        op_id=preview_operation['op_id'],
        world_id=world_id,
        dry_run=True,
    )
    wet_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)

    result = _cleanup_service(store, clock).evaluate_and_execute_cleanup(
        op_id=wet_operation['op_id'],
        world_id=world_id,
        dry_run=False,
        dry_run_operation_id=preview_operation['op_id'],
    )

    assert preview['targets'] == ['confirmed_0', 'confirmed_1']
    assert result['mode'] == 'wet_run'
    assert result['deleted_count'] == 2
    assert not paths['confirmed_0'].exists()
    assert not paths['confirmed_1'].exists()
    assert all(paths[f'confirmed_{index}'].is_file() for index in range(2, 5))
    for operation in (preview_operation, wet_operation):
        row = (
            store.reader()
            .execute(
                'SELECT op_type, status, data_json FROM operations WHERE op_id = ?',
                (operation['op_id'],),
            )
            .fetchone()
        )
        assert row['op_type'] == OperationType.CLEANUP.value
        assert row['status'] == OperationStatus.COMPLETED.value
        if operation == wet_operation:
            assert json.loads(row['data_json'])['mode'] == 'wet_run'


@pytest.mark.parametrize(
    ('candidate_count', 'requires_confirmation'),
    [
        (CLEANUP_BLAST_RADIUS_CAP, False),
        (CLEANUP_BLAST_RADIUS_CAP + 1, True),
    ],
)
def test_cleanup_blast_radius_confirmation_boundary(
    store, clock, tmp_path, candidate_count, requires_confirmation
):
    world_id = _seed_world(store)
    specs = [
        (f'bulk_{index}', 'manual', (candidate_count + 10 - index) * DAY)
        for index in range(candidate_count + 3)
    ]
    _seed_artifacts(store, clock, tmp_path, world_id, specs, create_files=False)
    preview_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)
    preview = _cleanup_service(store, clock).evaluate_and_execute_cleanup(
        op_id=preview_operation['op_id'],
        world_id=world_id,
        dry_run=True,
    )
    assert preview['target_count'] == candidate_count

    if requires_confirmation:
        with pytest.raises(RetentionError, match='CLEANUP_BLAST_RADIUS'):
            _cleanup_service(store, clock).execute_backup_cleanup(
                [
                    CleanupCandidate(f'untrusted-{index}', 'unused', world_id, 'manual', 0)
                    for index in range(candidate_count)
                ]
            )
        unconfirmed_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)
        with pytest.raises(RetentionError, match='CLEANUP_BLAST_RADIUS'):
            _cleanup_service(store, clock).evaluate_and_execute_cleanup(
                op_id=unconfirmed_operation['op_id'],
                world_id=world_id,
                dry_run=False,
                dry_run_operation_id=preview_operation['op_id'],
            )
        wet_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)
        elevated_confirmation = True
    else:
        wet_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)
        elevated_confirmation = False

    result = _cleanup_service(store, clock).evaluate_and_execute_cleanup(
        op_id=wet_operation['op_id'],
        world_id=world_id,
        dry_run=False,
        elevated_confirmation=elevated_confirmation,
        dry_run_operation_id=preview_operation['op_id'],
    )

    assert result['deleted_count'] == candidate_count


def test_stale_backup_candidates_require_pressure_age_sessions_and_category_floor(
    store, clock, tmp_path, monkeypatch
):
    world_id = _seed_world(store)
    now = int(clock.now())
    paths = _seed_artifacts(
        store,
        clock,
        tmp_path,
        world_id,
        [(f'manual_{index}', 'manual', (10 - index) * DAY) for index in range(8)]
        + [(f'scheduled_{index}', 'scheduled', (10 - index) * DAY) for index in range(4)],
    )
    connection = store.writer()
    for index in range(7):
        ended_at = now - 100 + index
        connection.execute(
            """
            INSERT INTO runtime_sessions (
                session_id, world_id, started_at, ended_at, end_reason,
                rcon_secret_id, port_used, java_runtime_id, launch_args_snapshot,
                created_at
            ) VALUES (?, ?, ?, ?, 'graceful_stop', 'sec_admin', ?, 'java', '{}', ?)
            """,
            (
                f'session_{index}',
                world_id,
                ended_at - 10,
                ended_at,
                25565 + index,
                ended_at,
            ),
        )
    connection.commit()

    cleanup = CleanupService(store, clock, filesystem=FixedUsageFilesystem(used=89))
    monkeypatch.setattr(cleanup, '_backup_root', lambda _world_id: tmp_path)
    operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)
    not_pressured, _ = cleanup.stale_backup_candidates(
        world_id=world_id, operation_id=operation['op_id']
    )
    assert not_pressured == []

    cleanup._filesystem.used = 90
    pressured, pressure = cleanup.stale_backup_candidates(
        world_id=world_id, operation_id=operation['op_id']
    )

    assert pressure[world_id]['triggered'] is True
    assert [candidate.artifact_id for candidate in pressured] == ['manual_0', 'manual_1']
    assert all(path.is_file() for path in paths.values())
    preview = cleanup.evaluate_and_execute_cleanup(
        op_id=operation['op_id'],
        world_id=world_id,
        dry_run=True,
        scope='stale_backups',
    )
    wet_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)
    result = cleanup.evaluate_and_execute_cleanup(
        op_id=wet_operation['op_id'],
        world_id=world_id,
        dry_run=False,
        scope='stale_backups',
        dry_run_operation_id=operation['op_id'],
    )

    assert preview['delete_targets'] == ['manual_0', 'manual_1']
    assert result['deleted_artifact_ids'] == ['manual_0', 'manual_1']
    assert not paths['manual_0'].exists()
    assert not paths['manual_1'].exists()
    assert (
        store.reader()
        .execute("SELECT 1 FROM backup_artifacts WHERE artifact_id IN ('manual_0', 'manual_1')")
        .fetchall()
        == []
    )

    next_preview_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)
    next_preview = cleanup.evaluate_and_execute_cleanup(
        op_id=next_preview_operation['op_id'],
        world_id=world_id,
        dry_run=True,
        scope='stale_backups',
    )
    assert next_preview['delete_targets'] == ['manual_2']
    next_wet_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)
    next_result = cleanup.evaluate_and_execute_cleanup(
        op_id=next_wet_operation['op_id'],
        world_id=world_id,
        dry_run=False,
        scope='stale_backups',
        dry_run_operation_id=next_preview_operation['op_id'],
    )
    assert next_result['deleted_artifact_ids'] == ['manual_2']


def test_stale_backup_cleanup_deletes_half_of_legacy_tombstones_without_grace(
    store, clock, tmp_path, monkeypatch
):
    world_id = _seed_world(store)
    now = int(clock.now())
    paths = _seed_artifacts(
        store,
        clock,
        tmp_path,
        world_id,
        [('oldest_manual', 'manual', 8 * DAY), ('newer_manual', 'manual', 7 * DAY)],
    )
    connection = store.writer()
    connection.execute(
        """
        UPDATE backup_artifacts
        SET deleted_at = ?, deleted_by = 'system', stale_tombstoned_at = ?
        WHERE artifact_id IN ('oldest_manual', 'newer_manual')
        """,
        (now - 1, now - 1),
    )
    for index in range(7):
        ended_at = now - 100 + index
        connection.execute(
            """
            INSERT INTO runtime_sessions (
                session_id, world_id, started_at, ended_at, end_reason,
                rcon_secret_id, port_used, java_runtime_id, launch_args_snapshot,
                created_at
            ) VALUES (?, ?, ?, ?, 'graceful_stop', 'sec_admin', ?, 'java', '{}', ?)
            """,
            (
                f'legacy_session_{index}',
                world_id,
                ended_at - 10,
                ended_at,
                25565 + index,
                ended_at,
            ),
        )
    connection.commit()

    cleanup = CleanupService(store, clock, filesystem=FixedUsageFilesystem(used=90))
    monkeypatch.setattr(cleanup, '_backup_root', lambda _world_id: tmp_path)
    preview_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)
    preview = cleanup.evaluate_and_execute_cleanup(
        op_id=preview_operation['op_id'],
        world_id=world_id,
        dry_run=True,
        scope='stale_backups',
    )
    wet_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)

    result = cleanup.evaluate_and_execute_cleanup(
        op_id=wet_operation['op_id'],
        world_id=world_id,
        dry_run=False,
        scope='stale_backups',
        dry_run_operation_id=preview_operation['op_id'],
    )

    assert preview['delete_targets'] == ['oldest_manual']
    assert preview['storage_pressure'][world_id]['triggered'] is True
    assert result['deleted_artifact_ids'] == ['oldest_manual']
    assert not paths['oldest_manual'].exists()
    assert paths['newer_manual'].exists()
    assert (
        store.reader()
        .execute("SELECT 1 FROM backup_artifacts WHERE artifact_id = 'oldest_manual'")
        .fetchone()
        is None
    )


def test_stale_cleanup_preserves_restore_referenced_artifacts(store, clock, tmp_path, monkeypatch):
    world_id = _seed_world(store)
    now = int(clock.now())
    _seed_artifacts(
        store,
        clock,
        tmp_path,
        world_id,
        [(f'pre_restore_{index}', 'pre_restore', (10 - index) * DAY) for index in range(4)],
    )
    restore_operation = _create_operation(store, clock, world_id, OperationType.RESTORE)
    store.writer().execute(
        """
        INSERT INTO restore_history (
            restore_id, world_id, operation_id, source_artifact_id,
            pre_restore_artifact_id, operator_user_id, outcome, started_at,
            finished_at, created_at
        ) VALUES (
            'restore_reference', ?, ?, 'pre_restore_0', 'pre_restore_1',
            'u_admin', 'success', ?, ?, ?
        )
        """,
        (world_id, restore_operation['op_id'], now, now, now),
    )
    store.writer().commit()
    operations = OperationService(store, clock)
    operations.transition(restore_operation['op_id'], OperationStatus.VALIDATING)
    operations.transition(restore_operation['op_id'], OperationStatus.RUNNING)
    operations.transition(restore_operation['op_id'], OperationStatus.COMPLETED)
    connection = store.writer()
    for index in range(7):
        ended_at = now - 100 + index
        connection.execute(
            """
            INSERT INTO runtime_sessions (
                session_id, world_id, started_at, ended_at, end_reason,
                rcon_secret_id, port_used, java_runtime_id, launch_args_snapshot,
                created_at
            ) VALUES (?, ?, ?, ?, 'graceful_stop', 'sec_admin', ?, 'java', '{}', ?)
            """,
            (
                f'ref_session_{index}',
                world_id,
                ended_at - 10,
                ended_at,
                25600 + index,
                ended_at,
            ),
        )
    connection.commit()
    cleanup = CleanupService(store, clock, filesystem=FixedUsageFilesystem(used=90))
    monkeypatch.setattr(cleanup, '_backup_root', lambda _world_id: tmp_path)
    operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)

    candidates, _ = cleanup.stale_backup_candidates(
        world_id=world_id, operation_id=operation['op_id']
    )

    assert {candidate.artifact_id for candidate in candidates}.isdisjoint(
        {'pre_restore_0', 'pre_restore_1'}
    )
    with pytest.raises(RetentionError, match='BACKUP_RETENTION_GUARD'):
        cleanup.validate_backup_artifact_delete('pre_restore_0', force=True)
    with pytest.raises(RetentionError, match='BACKUP_RETENTION_GUARD'):
        cleanup.validate_backup_artifact_delete('pre_restore_1', force=True)


def test_scheduled_backup_cap_prunes_old_unreferenced_backups_only(
    store, clock, tmp_path, monkeypatch
):
    world_id = _seed_world(store)
    paths = _seed_artifacts(
        store,
        clock,
        tmp_path,
        world_id,
        [(f'scheduled_{index}', 'scheduled', (10 - index) * DAY) for index in range(5)],
    )
    restore_operation = _create_operation(store, clock, world_id, OperationType.RESTORE)
    now = int(clock.now())
    store.writer().execute(
        """
        INSERT INTO restore_history (
            restore_id, world_id, operation_id, source_artifact_id,
            pre_restore_artifact_id, operator_user_id, outcome, started_at,
            finished_at, created_at
        ) VALUES (
            'scheduled_backup_reference', ?, ?, 'scheduled_0', 'scheduled_0',
            'u_admin', 'success', ?, ?, ?
        )
        """,
        (world_id, restore_operation['op_id'], now, now, now),
    )
    store.writer().commit()
    OperationService(store, clock).transition(restore_operation['op_id'], OperationStatus.COMPLETED)
    cleanup = _cleanup_service(store, clock)
    monkeypatch.setattr(cleanup, '_backup_root', lambda _world_id: tmp_path)
    operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)

    result = cleanup.enforce_scheduled_backup_cap(
        operation_id=operation['op_id'], world_id=world_id
    )

    assert result == {
        'deleted_artifact_ids': ['scheduled_1'],
        'protected_artifact_ids': ['scheduled_0'],
    }
    assert paths['scheduled_0'].exists()
    assert not paths['scheduled_1'].exists()
    remaining = (
        store.reader()
        .execute(
            """
        SELECT artifact_id FROM backup_artifacts
        WHERE world_id = ? AND category = 'scheduled' AND deleted_at IS NULL
        ORDER BY created_at DESC
        """,
            (world_id,),
        )
        .fetchall()
    )
    assert {row['artifact_id'] for row in remaining} == {
        'scheduled_0',
        'scheduled_2',
        'scheduled_3',
        'scheduled_4',
    }


def test_scheduled_cleanup_deletes_half_of_eligible_stale_backups_under_pressure(
    store, clock, tmp_path, monkeypatch
):
    world_id = _seed_world(store)
    now = int(clock.now())
    paths = _seed_artifacts(
        store,
        clock,
        tmp_path,
        world_id,
        [('scheduled_oldest', 'manual', 8 * DAY), ('scheduled_newer', 'manual', 7 * DAY)],
    )
    connection = store.writer()
    connection.execute(
        """
        UPDATE backup_artifacts
        SET deleted_at = ?, deleted_by = 'system', stale_tombstoned_at = ?
        WHERE artifact_id IN ('scheduled_oldest', 'scheduled_newer')
        """,
        (now - 1, now - 1),
    )
    connection.execute(
        """
        INSERT INTO schedules (
            schedule_id, scope, world_id, schedule_type, interval_spec, time_of_day,
            enabled, version, last_changed_by, last_changed_at, deleted_at, deleted_by,
            created_at
        ) VALUES ('scheduled_cleanup', 'world', ?, 'cleanup', '{}', '00:00', 1,
                  1, 'u_admin', ?, NULL, NULL, ?)
        """,
        (world_id, now, now),
    )
    connection.execute(
        """
        INSERT INTO cleanup_policies (
            policy_id, scope, world_id, age_rule_days, space_rule_pct, count_rules,
            stale_session_threshold, log_retention_days, schedule_id, version,
            last_changed_by, last_changed_at, deleted_at, deleted_by, created_at
        ) VALUES ('scheduled_policy', 'world', ?, 3, 90, NULL, 7, NULL,
                  'scheduled_cleanup', 1, 'u_admin', ?, NULL, NULL, ?)
        """,
        (world_id, now, now),
    )
    for index in range(7):
        ended_at = now - 100 + index
        connection.execute(
            """
            INSERT INTO runtime_sessions (
                session_id, world_id, started_at, ended_at, end_reason,
                rcon_secret_id, port_used, java_runtime_id, launch_args_snapshot,
                created_at
            ) VALUES (?, ?, ?, ?, 'graceful_stop', 'sec_admin', ?, 'java', '{}', ?)
            """,
            (
                f'scheduled_session_{index}',
                world_id,
                ended_at - 10,
                ended_at,
                25565 + index,
                ended_at,
            ),
        )
    connection.commit()
    cleanup = CleanupService(store, clock, filesystem=FixedUsageFilesystem(used=90))
    monkeypatch.setattr(cleanup, '_backup_root', lambda _world_id: tmp_path)
    operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)

    result = cleanup.run_scheduled_cleanup(
        operation_id=operation['op_id'],
        world_id=world_id,
        schedule_id='scheduled_cleanup',
    )

    assert result['deleted_artifact_ids'] == ['scheduled_oldest']
    assert not paths['scheduled_oldest'].exists()
    assert paths['scheduled_newer'].exists()


def test_log_cleanup_defaults_to_forever_and_only_selects_rotated_graceful_logs(
    store, clock, tmp_path, monkeypatch
):
    world_id = _seed_world(store)
    now = int(clock.now())
    connection = store.writer()
    for session_id, ended_at, reason in (
        ('graceful_old', now - 5 * DAY, 'graceful_stop'),
        ('crashed_old', now - 5 * DAY, 'crashed'),
        ('graceful_recent', now - DAY, 'graceful_stop'),
    ):
        connection.execute(
            """
            INSERT INTO runtime_sessions (
                session_id, world_id, started_at, ended_at, end_reason,
                rcon_secret_id, port_used, java_runtime_id, launch_args_snapshot,
                created_at
            ) VALUES (?, ?, ?, ?, ?, 'sec_admin', ?, 'java', '{}', ?)
            """,
            (
                session_id,
                world_id,
                ended_at - 10,
                ended_at,
                reason,
                25700 + len(session_id),
                ended_at,
            ),
        )
    connection.commit()

    log_root = tmp_path / 'log_root'
    session_dir = log_root / world_id / world_id
    session_dir.mkdir(parents=True)
    base_log = session_dir / 'graceful_old.log'
    rotated_log = session_dir / 'graceful_old.log.1'
    crashed_log = session_dir / 'crashed_old.log.1'
    for path in (base_log, rotated_log, crashed_log):
        path.write_text('log', encoding='utf-8')
        path.touch()
        path_time = now - 4 * DAY
        os.utime(path, (path_time, path_time))

    cleanup = _cleanup_service(store, clock)
    monkeypatch.setattr(cleanup, '_log_root', lambda _world_id: session_dir)
    operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)
    assert cleanup.log_candidates(world_id=world_id, operation_id=operation['op_id']) == []

    policy_connection = store.writer()
    policy_connection.execute(
        """
        INSERT INTO cleanup_policies (
            policy_id, scope, world_id, age_rule_days, space_rule_pct, count_rules,
            stale_session_threshold, log_retention_days, schedule_id, version,
            last_changed_by, last_changed_at, deleted_at, deleted_by, created_at
        ) VALUES (
            'log_policy', 'world', ?, 3, 90, NULL, 7, 3, NULL, 1,
            'u_admin', ?, NULL, NULL, ?
        )
        """,
        (world_id, now, now),
    )
    policy_connection.commit()
    finite_retention = cleanup.log_candidates(world_id=world_id, operation_id=operation['op_id'])

    assert [Path(candidate.path) for candidate in finite_retention] == [rotated_log]
    assert base_log.exists()
    assert crashed_log.exists()
    preview = cleanup.evaluate_and_execute_cleanup(
        op_id=operation['op_id'],
        world_id=world_id,
        dry_run=True,
        scope='logs',
    )
    wet_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)
    result = cleanup.evaluate_and_execute_cleanup(
        op_id=wet_operation['op_id'],
        world_id=world_id,
        dry_run=False,
        scope='logs',
        dry_run_operation_id=operation['op_id'],
    )

    assert preview['target_count'] == 1
    assert result['deleted_log_count'] == 1
    assert not rotated_log.exists()
    assert base_log.exists()
    assert crashed_log.exists()
    assert (
        store.reader()
        .execute(
            """
        SELECT COUNT(*) FROM audit_records
        WHERE operation_id = ? AND event_type = 'cleanup.log_file_deleted'
        """,
            (wet_operation['op_id'],),
        )
        .fetchone()[0]
        == 1
    )


def test_only_cleanup_service_issues_hard_delete_sql():
    app_root = Path(__file__).resolve().parents[2] / 'app'
    cleanup_file = app_root / 'services' / 'cleanup.py'
    hard_delete = re.compile(r'\bDELETE\s+FROM\b', re.IGNORECASE)

    violations = [
        str(path.relative_to(app_root))
        for path in app_root.rglob('*.py')
        if path != cleanup_file and hard_delete.search(path.read_text(encoding='utf-8'))
    ]

    assert violations == []
