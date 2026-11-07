from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.domain.tuning import CLEANUP_BLAST_RADIUS_CAP
from app.domain.value_objects import ActorType, OperationStatus, OperationType
from app.services.cleanup import CleanupCandidate, CleanupService, RetentionError
from app.services.operations import OperationInput, OperationService

from .test_phase3_control_plane import _seed_world

DAY = 24 * 60 * 60


def _create_operation(store, clock, world_id: str, op_type: OperationType):
    return OperationService(store, clock).create(
        OperationInput(
            op_type=op_type,
            actor_type=ActorType.SYSTEM,
            world_id=world_id,
        )
    )


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
    OperationService(store, clock).transition(
        backup_operation['op_id'], OperationStatus.COMPLETED
    )
    return paths


def test_cleanup_floor_boundaries_and_newest_three_are_per_category(
    store, clock, tmp_path
):
    world_id = _seed_world(store)
    specs = []
    for index, age_days in enumerate((10, 9, 8, 7, 6)):
        specs.append((f'manual_{index}', 'manual', age_days * DAY))
    for index, age_days in enumerate((11, 10, 9, 8)):
        specs.append((f'pre_restore_{index}', 'pre_restore', age_days * DAY))
    for index, age_days in enumerate((6, 5, 4, 3)):
        specs.append((f'emergency_{index}', 'emergency', age_days * DAY))
    paths = _seed_artifacts(store, clock, tmp_path, world_id, specs)
    cleanup = CleanupService(store, clock)

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

    candidates = CleanupService(store, clock).backup_candidates(older_than_days=3)

    assert [candidate.artifact_id for candidate in candidates] == ['cutoff_oldest']


def test_dry_and_wet_runs_are_durable_operations_bound_to_exact_preview(
    store, clock, tmp_path
):
    world_id = _seed_world(store)
    paths = _seed_artifacts(
        store,
        clock,
        tmp_path,
        world_id,
        [
            (f'preview_{index}', 'manual', (10 - index) * DAY)
            for index in range(5)
        ],
    )
    operations = OperationService(store, clock)
    cleanup = CleanupService(store, clock)
    preview_operation = _create_operation(
        store, clock, world_id, OperationType.CLEANUP
    )

    preview = cleanup.evaluate_and_execute_cleanup(
        op_id=preview_operation['op_id'],
        world_id=world_id,
        dry_run=True,
    )

    assert preview['mode'] == 'dry_run'
    assert preview['target_count'] == 2
    assert all(path.is_file() for path in paths.values())
    preview_row = store.reader().execute(
        'SELECT status, data_json FROM operations WHERE op_id = ?',
        (preview_operation['op_id'],),
    ).fetchone()
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
    wet_row = store.reader().execute(
        'SELECT status FROM operations WHERE op_id = ?', (wet_operation['op_id'],)
    ).fetchone()
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
        [
            (f'confirmed_{index}', 'manual', (10 - index) * DAY)
            for index in range(5)
        ],
    )
    preview_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)
    preview = CleanupService(store, clock).evaluate_and_execute_cleanup(
        op_id=preview_operation['op_id'],
        world_id=world_id,
        dry_run=True,
    )
    wet_operation = _create_operation(store, clock, world_id, OperationType.CLEANUP)

    result = CleanupService(store, clock).evaluate_and_execute_cleanup(
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
        row = store.reader().execute(
            'SELECT op_type, status, data_json FROM operations WHERE op_id = ?',
            (operation['op_id'],),
        ).fetchone()
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
    preview = CleanupService(store, clock).evaluate_and_execute_cleanup(
        op_id=preview_operation['op_id'],
        world_id=world_id,
        dry_run=True,
    )
    assert preview['target_count'] == candidate_count

    if requires_confirmation:
        with pytest.raises(RetentionError, match='CLEANUP_BLAST_RADIUS'):
            CleanupService(store, clock).execute_backup_cleanup(
                [
                    CleanupCandidate(
                        f'untrusted-{index}', 'unused', world_id, 'manual', 0
                    )
                    for index in range(candidate_count)
                ]
            )
        unconfirmed_operation = _create_operation(
            store, clock, world_id, OperationType.CLEANUP
        )
        with pytest.raises(RetentionError, match='CLEANUP_BLAST_RADIUS'):
            CleanupService(store, clock).evaluate_and_execute_cleanup(
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

    result = CleanupService(store, clock).evaluate_and_execute_cleanup(
        op_id=wet_operation['op_id'],
        world_id=world_id,
        dry_run=False,
        elevated_confirmation=elevated_confirmation,
        dry_run_operation_id=preview_operation['op_id'],
    )

    assert result['deleted_count'] == candidate_count


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
