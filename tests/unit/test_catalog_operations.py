from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.domain.value_objects import ActorType, OperationStatus, OperationType, TriggerType
from app.services.catalog_operations import CatalogOperationDispatcher
from app.services.operations import OperationInput


class OperationQueue:
    def __init__(self, operation: dict[str, object]) -> None:
        self.operation = operation
        self.status = OperationStatus.QUEUED.value
        self.transitions: list[tuple[object, ...]] = []
        self.created: list[tuple[object, ...]] = []

    def list_queued(self, _operation_types):
        return [self.operation]

    def claim_queued(self, _op_id):
        self.status = OperationStatus.RUNNING.value
        return self.operation

    def get(self, _op_id):
        return {"status": self.status}

    def transition(self, *args, **kwargs):
        self.transitions.append((*args, kwargs))
        self.status = args[1].value

    def create(self, *args, **kwargs):
        self.created.append((*args, kwargs))


class SingleWorldStore:
    def __init__(self, world: dict[str, object]) -> None:
        self.world = world

    def reader(self):
        return self

    def execute(self, _query, _parameters):
        return self

    def fetchone(self):
        return self.world


def _dispatcher(*, operations, store=None, configuration=None, backups=None, cleanup=None):
    return CatalogOperationDispatcher(
        store=store,
        clock=None,
        operations=operations,
        configuration=configuration,
        backups=backups,
        restore=None,
        cleanup=cleanup,
        sync=None,
        manager_lifecycle=None,
    )


def test_scheduled_world_backup_enqueues_cap_enforcement_after_completion(tmp_path):
    world_dir = tmp_path / "live-world"
    backup_root = tmp_path / "archives"
    operation = {
        "op_id": "backup-1",
        "op_type": OperationType.BACKUP.value,
        "world_id": "world-1",
        "actor_user_id": None,
        "data_json": json.dumps({"category": "scheduled"}),
    }
    queue = OperationQueue(operation)
    backup_calls: list[dict[str, object]] = []

    class Backups:
        def create_world_backup(self, **kwargs):
            backup_calls.append(kwargs)
            return SimpleNamespace(
                artifact_id="artifact-1",
                checksum="sha256",
                size_bytes=42,
                skipped_paths=[],
            )

    dispatcher = _dispatcher(
        operations=queue,
        store=SingleWorldStore(
            {
                "world_id": "world-1",
                "display_name": "Live World",
                "addressing_strategy": "path",
                "addressing_value": str(world_dir),
                "state": "running",
            }
        ),
        configuration=SimpleNamespace(
            resolve_effective=lambda _world_id: {
                "backup_root_path": str(backup_root),
                "minecraft_root_path": None,
            }
        ),
        backups=Backups(),
    )

    assert dispatcher.dispatch_queued_operations() == ["backup-1"]
    assert backup_calls == [
        {
            "world_id": "world-1",
            "world_dir": world_dir,
            "backup_dir": backup_root / "world-1",
            "operation_id": "backup-1",
            "category": TriggerType.SCHEDULED,
            "running": True,
        }
    ]
    assert queue.transitions == [
        (
            "backup-1",
            OperationStatus.COMPLETED,
            {"data": {
                "artifact_id": "artifact-1",
                "checksum": "sha256",
                "size_bytes": 42,
                "skipped_paths": [],
            }},
        )
    ]
    created, options = queue.created[0]
    assert created == OperationInput(
        op_type=OperationType.CLEANUP,
        actor_type=ActorType.SYSTEM,
        world_id="world-1",
        idempotency_key="scheduled-backup-cap:backup-1",
        data={
            "action": "enforce_scheduled_backup_cap",
            "source_backup_operation_id": "backup-1",
        },
    )
    assert options == {
        "initial_status": OperationStatus.QUEUED,
        "allow_world_conflict": True,
    }


def test_invalid_backup_metadata_falls_back_to_manual_without_scheduling_cap(tmp_path):
    operation = {
        "op_id": "backup-invalid-metadata",
        "op_type": OperationType.BACKUP.value,
        "world_id": "world-1",
        "actor_user_id": None,
        "data_json": "{not-json",
    }
    queue = OperationQueue(operation)
    backup_categories: list[TriggerType] = []

    class Backups:
        def create_world_backup(self, **kwargs):
            backup_categories.append(kwargs["category"])
            return SimpleNamespace(
                artifact_id="artifact-1",
                checksum="sha256",
                size_bytes=42,
                skipped_paths=[],
            )

    dispatcher = _dispatcher(
        operations=queue,
        store=SingleWorldStore(
            {
                "world_id": "world-1",
                "display_name": "World",
                "addressing_strategy": "path",
                "addressing_value": str(tmp_path / "world"),
                "state": "off",
            }
        ),
        configuration=SimpleNamespace(
            resolve_effective=lambda _world_id: {
                "backup_root_path": str(tmp_path / "backups"),
                "minecraft_root_path": None,
            }
        ),
        backups=Backups(),
    )

    assert dispatcher.dispatch_queued_operations() == ["backup-invalid-metadata"]
    assert backup_categories == [TriggerType.MANUAL]
    assert queue.created == []


def test_backup_for_missing_world_is_terminalized_with_world_not_found():
    operation = {
        "op_id": "backup-missing-world",
        "op_type": OperationType.BACKUP.value,
        "world_id": None,
        "actor_user_id": None,
        "data_json": "{}",
    }
    queue = OperationQueue(operation)
    dispatcher = _dispatcher(operations=queue)

    assert dispatcher.dispatch_queued_operations() == ["backup-missing-world"]
    assert queue.status == OperationStatus.FAILED.value
    assert queue.transitions == [
        (
            "backup-missing-world",
            OperationStatus.FAILED,
            {
                "error_code": "WORLD_NOT_FOUND",
                "message": "WORLD_NOT_FOUND",
            },
        )
    ]


@pytest.mark.parametrize(
    ("world_target", "global_target", "expected_target"),
    (
        ("world-target", "global-target", "world-target"),
        (None, "global-target", "global-target"),
    ),
)
def test_sync_dispatch_resolves_world_target_before_global_target(
    world_target, global_target, expected_target
):
    operation = {
        "op_id": "sync-resolved-1",
        "op_type": OperationType.SYNC.value,
        "world_id": "world-1",
        "actor_user_id": "user-1",
        "data_json": json.dumps({"artifact_id": "artifact-1"}),
    }
    queue = OperationQueue(operation)
    queries: list[tuple[str, tuple[object, ...]]] = []

    class Store:
        def reader(self):
            return self

        def execute(self, query, parameters=()):
            queries.append((query, parameters))
            target = world_target if "scope = 'world'" in query else global_target
            return SimpleNamespace(
                fetchone=lambda: (
                    {"sync_target_id": target} if target is not None else None
                )
            )

    sync_calls: list[tuple[str, str, str]] = []

    def dispatch_sync(artifact_id, target_id, *, operation_id):
        sync_calls.append((artifact_id, target_id, operation_id))
        return "sync-record-1"

    dispatcher = CatalogOperationDispatcher(
        store=Store(),
        clock=None,
        operations=queue,
        configuration=None,
        backups=None,
        restore=None,
        cleanup=None,
        sync=SimpleNamespace(dispatch_sync=dispatch_sync),
        manager_lifecycle=None,
    )

    assert dispatcher.dispatch_queued_operations() == ["sync-resolved-1"]
    assert sync_calls == [("artifact-1", expected_target, "sync-resolved-1")]
    assert len(queries) == (1 if world_target is not None else 2)


def test_sync_without_any_enabled_target_fails_with_actionable_code():
    operation = {
        "op_id": "sync-no-target",
        "op_type": OperationType.SYNC.value,
        "world_id": "world-1",
        "actor_user_id": "user-1",
        "data_json": json.dumps({"artifact_id": "artifact-1"}),
    }
    queue = OperationQueue(operation)

    class NoTargets:
        def reader(self):
            return self

        def execute(self, _query, _parameters=()):
            return SimpleNamespace(fetchone=lambda: None)

    dispatcher = CatalogOperationDispatcher(
        store=NoTargets(),
        clock=None,
        operations=queue,
        configuration=None,
        backups=None,
        restore=None,
        cleanup=None,
        sync=None,
        manager_lifecycle=None,
    )

    assert dispatcher.dispatch_queued_operations() == ["sync-no-target"]
    assert queue.status == OperationStatus.FAILED.value
    assert queue.transitions == [
        (
            "sync-no-target",
            OperationStatus.FAILED,
            {
                "error_code": "SYNC_TARGET_UNRESOLVED",
                "message": "SYNC_TARGET_UNRESOLVED",
            },
        )
    ]


@pytest.mark.parametrize(
    ("data", "method", "expected_kwargs"),
    (
        (
            {"schedule_id": "schedule-1"},
            "run_scheduled_cleanup",
            {
                "operation_id": "cleanup-1",
                "world_id": "world-1",
                "schedule_id": "schedule-1",
            },
        ),
        (
            {
                "wet": True,
                "older_than_days": 7,
                "keep_per_category": 2,
                "elevated_confirmation": True,
                "scope": "logs",
                "dry_run_operation_id": "preview-1",
            },
            "evaluate_and_execute_cleanup",
            {
                "op_id": "cleanup-1",
                "world_id": "world-1",
                "dry_run": False,
                "older_than_days": 7,
                "keep_per_category": 2,
                "elevated_confirmation": True,
                "scope": "logs",
                "deleted_by": "user-1",
                "dry_run_operation_id": "preview-1",
            },
        ),
    ),
)
def test_cleanup_dispatch_selects_scheduled_or_interactive_execution(
    data, method, expected_kwargs
):
    operation = {
        "op_id": "cleanup-1",
        "op_type": OperationType.CLEANUP.value,
        "world_id": "world-1",
        "actor_user_id": "user-1",
        "data_json": json.dumps(data),
    }
    queue = OperationQueue(operation)
    cleanup_calls: list[tuple[str, dict[str, object]]] = []

    def execute(**kwargs):
        cleanup_calls.append((method, kwargs))
        return {"removed": ["stale-item"]}

    cleanup = SimpleNamespace(**{method: execute})
    dispatcher = _dispatcher(operations=queue, cleanup=cleanup)

    assert dispatcher.dispatch_queued_operations() == ["cleanup-1"]
    assert cleanup_calls == [(method, expected_kwargs)]
    assert queue.transitions == [
        (
            "cleanup-1",
            OperationStatus.COMPLETED,
            {"data": {"removed": ["stale-item"]}},
        )
    ]


def test_operation_claimed_by_another_worker_is_not_dispatched():
    operation = {
        "op_id": "backup-claimed-elsewhere",
        "op_type": OperationType.BACKUP.value,
        "world_id": "world-1",
        "actor_user_id": None,
        "data_json": "{}",
    }
    queue = OperationQueue(operation)
    queue.claim_queued = lambda _op_id: None

    assert _dispatcher(operations=queue).dispatch_queued_operations() == []
    assert queue.transitions == []
