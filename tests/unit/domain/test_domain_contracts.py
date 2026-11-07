"""Pure domain contracts: closed value objects, deletion tiers, and imports."""

from __future__ import annotations

import ast
from pathlib import Path

from app.domain.deletion_tiers import DeletionTier, get_deletion_tier
from app.domain.value_objects import (
    OperationStatus,
    OperationType,
    WorldState,
)

EXPECTED_WORLD_STATES = {
    "off",
    "queued",
    "starting",
    "running",
    "stopping",
    "restoring",
    "backing_up",
    "crashed",
    "error",
    "eula_required",
}
EXPECTED_OPERATION_TYPES = {
    "CreateWorld",
    "Start",
    "Stop",
    "Kill",
    "Backup",
    "Restore",
    "Cleanup",
    "Sync",
    "ConfigEdit",
    "CrashDetected",
    "DeleteWorld",
}
EXPECTED_OPERATION_STATUSES = {
    "Created",
    "Queued",
    "Validating",
    "Running",
    "Completed",
    "Failed",
    "Cancelled",
    "TimedOut",
}
TIER_1_ENTITIES = {
    "audit_records",
    "notifications",
    "notification_reads",
    "missed_run_records",
    "sync_records",
    "sync_attempts",
}
TIER_2_ENTITIES = {
    "world_instances",
    "devices",
    "java_runtimes",
    "templates",
    "users",
    "backup_artifacts",
    "schedules",
    "cleanup_policies",
    "roles",
    "permissions",
    "role_assignments",
    "client_sessions",
    "sync_targets",
}


def test_world_state_enum_matches_the_documented_closed_set() -> None:
    assert {state.value for state in WorldState} == EXPECTED_WORLD_STATES


def test_operation_enums_match_the_documented_closed_sets() -> None:
    assert {operation.value for operation in OperationType} == EXPECTED_OPERATION_TYPES
    assert {status.value for status in OperationStatus} == EXPECTED_OPERATION_STATUSES


def test_deletion_tiers_match_the_complete_documented_classification() -> None:
    assert {
        entity
        for entity in TIER_1_ENTITIES | TIER_2_ENTITIES
        if get_deletion_tier(entity) is DeletionTier.TIER_1
    } == TIER_1_ENTITIES
    assert {
        entity
        for entity in TIER_1_ENTITIES | TIER_2_ENTITIES
        if get_deletion_tier(entity) is DeletionTier.TIER_2
    } == TIER_2_ENTITIES
    assert get_deletion_tier("operations") is None
    assert get_deletion_tier("unclassified_entity") is None


def test_domain_modules_import_only_domain_modules_and_the_standard_library() -> None:
    domain_dir = Path(__file__).parents[3] / "app" / "domain"
    violations: list[str] = []

    for module_path in domain_dir.glob("*.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported_modules = [node.module or ""]
            else:
                continue
            for imported in imported_modules:
                root = imported.split(".", maxsplit=1)[0]
                if imported.startswith("app.domain") or root in __import__("sys").stdlib_module_names:
                    continue
                violations.append(f"{module_path.name}: {imported}")

    assert violations == []
