"""Acceptance tests for Gate 2 realignment (G2-1 through G2-4)."""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest
from flask import Flask

from app.domain.value_objects import ActorType, ConfigEditEntity, OperationType, WorldState
from app.services.configuration import (
    ConfigurationConflictError,
    ConfigurationService,
    VersionedUpdate,
)
from app.services.operations import OperationStatus
from app.services.worlds import WorldConflictError, WorldsService


_DOCS = Path(__file__).resolve().parents[2] / "docs"
_NOW = 1_700_000_000


def _seed_configuration(store, *, with_override: bool = True) -> None:
    connection = store.writer()
    connection.execute(
        "INSERT INTO secrets VALUES ('sec_admin', 'user_password', 'x', 'user', "
        "'u_admin', NULL, ?, NULL)",
        (_NOW,),
    )
    connection.execute(
        """
        INSERT INTO users (
            user_id, username, display_name, secret_id, status, failed_login_count,
            locked_until, created_by, deleted_at, deleted_by, created_at, updated_at
        ) VALUES (
            'u_admin', 'admin', NULL, 'sec_admin', 'active', 0,
            NULL, NULL, NULL, NULL, ?, ?
        )
        """,
        (_NOW, _NOW),
    )
    connection.execute(
        """
        INSERT INTO templates (
            template_id, name, category, default_version, config_defaults, source,
            deprecated, version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES (
            'tpl', 'Vanilla', 'vanilla', '1.21', '{}', 'built_in',
            0, 1, NULL, NULL, ?, ?
        )
        """,
        (_NOW, _NOW),
    )
    connection.execute(
        """
        INSERT INTO java_runtimes (
            runtime_id, label, executable_path, version_detected, status,
            deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('java', 'Java 21', 'java', '21', 'verified', NULL, NULL, ?, ?)
        """,
        (_NOW, _NOW),
    )
    connection.execute(
        """
        INSERT INTO global_settings (
            settings_id, timezone, idle_countdown_seconds, notification_defaults,
            minecraft_root_path, backup_root_path, log_root_path,
            offsite_sync_defaults, version, updated_at, updated_by
        ) VALUES (
            'global', 'UTC', 120, '{"level":"global"}', 'C:/worlds',
            'C:/backups', 'C:/logs', '{"target":"global"}', 1, ?, 'u_admin'
        )
        """,
        (_NOW,),
    )
    connection.execute(
        """
        INSERT INTO world_instances (
            world_id, display_name, template_id, server_type, mc_version, java_runtime_id,
            port, addressing_strategy, addressing_value, state, pre_backup_state,
            launch_args, metadata_version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES (
            'world_1', 'Survival', 'tpl', 'vanilla', '1.21', 'java',
            25565, 'port', '25565', 'off', NULL,
            '{}', 1, NULL, NULL, ?, ?
        )
        """,
        (_NOW, _NOW),
    )
    if with_override:
        connection.execute(
            """
            INSERT INTO world_settings (
                world_id, minecraft_root_override, backup_root_override,
                log_root_override, offsite_sync_override, idle_countdown_override,
                version, updated_at, updated_by
            ) VALUES (
                'world_1', NULL, 'D:/world-backups', NULL,
                '{"target":"world"}', 0, 1, ?, 'u_admin'
            )
            """,
            (_NOW,),
        )
    connection.commit()


def test_domain_lifecycle_guards_and_emits_world_state_events():
    lifecycle = importlib.import_module("app.domain.lifecycle")
    entities = importlib.import_module("app.domain.entities")
    events = importlib.import_module("app.domain.events")

    world = entities.WorldInstance(world_id="w1", state=WorldState.OFF)
    queued, event = lifecycle.transition_world(world, WorldState.QUEUED, occurred_at=10)

    assert queued.state is WorldState.QUEUED
    assert isinstance(event, events.WorldStateChanged)
    assert event.world_id == "w1"
    assert event.previous_state is WorldState.OFF
    assert event.new_state is WorldState.QUEUED
    assert event.occurred_at == 10

    with pytest.raises(lifecycle.InvalidWorldTransition):
        lifecycle.transition_world(world, WorldState.RUNNING, occurred_at=11)


def test_domain_entities_enforce_world_invariants_and_deletion_tiers():
    entities = importlib.import_module("app.domain.entities")
    invariants = importlib.import_module("app.domain.invariants")
    deletion_tiers = importlib.import_module("app.domain.deletion_tiers")

    with pytest.raises(invariants.DomainInvariantError):
        entities.WorldInstance(
            world_id="w1",
            state=WorldState.BACKING_UP,
            pre_backup_state=None,
        )

    entities.WorldInstance(
        world_id="w1",
        state=WorldState.BACKING_UP,
        pre_backup_state=WorldState.RUNNING,
    )
    assert deletion_tiers.get_deletion_tier("audit_records") is deletion_tiers.DeletionTier.TIER_1
    assert deletion_tiers.get_deletion_tier("world_instances") is deletion_tiers.DeletionTier.TIER_2
    assert deletion_tiers.get_deletion_tier("operations") is None


def test_worlds_service_rejects_transition_not_allowed_by_domain_lifecycle(store, clock):
    _seed_configuration(store, with_override=False)
    worlds = WorldsService(
        store=store,
        clock=clock,
        operations=None,
        process_adapter=None,
        secrets=None,
        minecraft=None,
    )

    with pytest.raises(WorldConflictError):
        worlds._set_world_state("world_1", WorldState.RUNNING)

    row = store.reader().execute(
        "SELECT state FROM world_instances WHERE world_id = 'world_1'"
    ).fetchone()
    assert row["state"] == WorldState.OFF.value


def test_effective_configuration_merges_singleton_defaults_and_world_overrides(store, clock):
    _seed_configuration(store)
    service = ConfigurationService(store, clock)

    effective = service.resolve_effective("world_1")

    assert effective == {
        "timezone": "UTC",
        "idle_countdown_seconds": 0,
        "notification_defaults": {"level": "global"},
        "minecraft_root_path": "C:/worlds",
        "backup_root_path": "D:/world-backups",
        "log_root_path": "C:/logs",
        "offsite_sync_defaults": {"target": "world"},
    }


def test_effective_configuration_uses_global_values_when_world_override_is_absent(store, clock):
    _seed_configuration(store, with_override=False)

    effective = ConfigurationService(store, clock).resolve_effective("world_1")

    assert effective["backup_root_path"] == "C:/backups"
    assert effective["idle_countdown_seconds"] == 120
    assert effective["offsite_sync_defaults"] == {"target": "global"}


def test_config_edits_are_durable_operations_with_before_and_after_values(store, clock):
    _seed_configuration(store, with_override=False)
    service = ConfigurationService(store, clock)

    updated = service.update_versioned(
        VersionedUpdate(
            entity=ConfigEditEntity.GLOBAL_SETTINGS,
            row_id="global",
            expected_version=1,
            fields={"timezone": "Pacific/Auckland"},
            actor_type=ActorType.USER,
            actor_user_id="u_admin",
        )
    )

    assert updated["version"] == 2
    row = store.reader().execute(
        "SELECT * FROM operations WHERE op_type = ?",
        (OperationType.CONFIG_EDIT.value,),
    ).fetchone()
    assert row is not None
    assert row["status"] == OperationStatus.COMPLETED.value
    payload = json.loads(row["data_json"])
    assert payload["entity"] == ConfigEditEntity.GLOBAL_SETTINGS.value
    assert payload["row_id"] == "global"
    assert payload["before"]["timezone"] == "UTC"
    assert payload["after"]["timezone"] == "Pacific/Auckland"


def test_stale_config_edit_is_recorded_as_failed_operation(store, clock):
    _seed_configuration(store, with_override=False)
    service = ConfigurationService(store, clock)
    update = VersionedUpdate(
        entity=ConfigEditEntity.GLOBAL_SETTINGS,
        row_id="global",
        expected_version=0,
        fields={"timezone": "stale"},
        actor_type=ActorType.USER,
        actor_user_id="u_admin",
    )

    with pytest.raises(ConfigurationConflictError):
        service.update_versioned(update)

    row = store.reader().execute(
        "SELECT status, error_code FROM operations WHERE op_type = ?",
        (OperationType.CONFIG_EDIT.value,),
    ).fetchone()
    assert row is not None
    assert row["status"] == OperationStatus.FAILED.value
    assert row["error_code"] == "CONFIG_VERSION_CONFLICT"


def test_configuration_conflict_is_mapped_to_http_409():
    errors = importlib.import_module("app.web.errors")
    register_error_handlers = getattr(errors, "register_error_handlers", None)
    assert callable(register_error_handlers)

    app = Flask(__name__)
    register_error_handlers(app)

    @app.get("/conflict")
    def conflict():
        raise ConfigurationConflictError("CONFIG_VERSION_CONFLICT")

    response = app.test_client().get("/conflict")

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "CONFIG_VERSION_CONFLICT"


def test_gate2_pseudocode_global_settings_matches_document_7_singleton():
    pseudocode = (_DOCS / "gate2_pseudocode.txt").read_text(encoding="utf-8")
    match = re.search(
        r"CREATE TABLE IF NOT EXISTS global_settings\s*\((.*?)\);",
        pseudocode,
        flags=re.DOTALL,
    )

    assert match is not None
    definition = match.group(1)
    for column in (
        "settings_id",
        "timezone",
        "idle_countdown_seconds",
        "notification_defaults",
        "minecraft_root_path",
        "backup_root_path",
        "log_root_path",
        "offsite_sync_defaults",
        "version",
        "updated_at",
        "updated_by",
    ):
        assert re.search(rf"^\s*{column}\s+", definition, flags=re.MULTILINE), column
    assert not re.search(r"^\s*key\s+", definition, flags=re.MULTILINE)
    assert "value_json" not in definition
