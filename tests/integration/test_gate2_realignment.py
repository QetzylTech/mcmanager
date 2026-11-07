"""Acceptance tests for Gate 2 realignment (G2-1 through G2-4)."""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, g

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
    service = ConfigurationService(store, clock)

    assert service.resolve_world("world_1") is None

    assert service.resolve_effective("world_1") == {
        "timezone": "UTC",
        "idle_countdown_seconds": 120,
        "notification_defaults": {"level": "global"},
        "minecraft_root_path": "C:/worlds",
        "backup_root_path": "C:/backups",
        "log_root_path": "C:/logs",
        "offsite_sync_defaults": {"target": "global"},
    }


def test_configuration_service_resolves_global_and_world_settings(store, clock):
    _seed_configuration(store)
    service = ConfigurationService(store, clock)

    global_settings = service.resolve_global()
    world_settings = service.resolve_world("world_1")

    assert global_settings["notification_defaults"] == {"level": "global"}
    assert global_settings["offsite_sync_defaults"] == {"target": "global"}
    assert world_settings is not None
    assert world_settings["backup_root_override"] == "D:/world-backups"
    assert world_settings["idle_countdown_override"] == 0
    assert world_settings["offsite_sync_override"] == {"target": "world"}


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
    audit = store.reader().execute(
        "SELECT payload FROM audit_records WHERE operation_id = ?",
        (row["op_id"],),
    ).fetchone()
    audit_payload = json.loads(audit["payload"])
    assert audit_payload["before"]["timezone"] == "UTC"
    assert audit_payload["after"]["timezone"] == "Pacific/Auckland"


def test_stale_config_edit_is_rejected_before_operation_creation(store, clock):
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
        "SELECT op_id FROM operations WHERE op_type = ?",
        (OperationType.CONFIG_EDIT.value,),
    ).fetchone()
    assert row is None
    settings = store.reader().execute(
        "SELECT timezone, version FROM global_settings WHERE settings_id = 'global'"
    ).fetchone()
    assert tuple(settings) == ("UTC", 1)


def test_settings_api_resolves_and_edits_global_and_world_settings(store, clock):
    _seed_configuration(store)
    service = ConfigurationService(store, clock)
    app = Flask(__name__)
    app.extensions["mcmanager_container"] = SimpleNamespace(
        configuration=service,
        store=store,
    )
    app.before_request(lambda: setattr(g, "current_user_id", "u_admin"))
    from app.web.api import register_api_blueprints

    register_api_blueprints(app)
    errors = importlib.import_module("app.web.errors")
    errors.register_error_handlers(app)
    client = app.test_client()

    global_response = client.get("/api/settings")
    assert global_response.status_code == 200
    assert global_response.get_json()["data"]["settings"]["timezone"] == "UTC"
    assert global_response.get_json()["data"]["version"] == 1

    invalid_global_patch = client.patch(
        "/api/settings",
        json={"version": 1, "timezone": {"unexpected": "object"}},
    )
    assert invalid_global_patch.status_code == 400
    assert invalid_global_patch.get_json()["error"]["code"] == "VALIDATION_ERROR"

    global_patch = client.patch(
        "/api/settings",
        json={"version": 1, "timezone": "Pacific/Auckland"},
    )
    assert global_patch.status_code == 200
    assert global_patch.get_json()["data"]["settings"]["timezone"] == "Pacific/Auckland"
    assert global_patch.get_json()["data"]["version"] == 2
    global_operation = global_patch.get_json()["data"]["operation"]
    assert global_operation["op_type"] == OperationType.CONFIG_EDIT.value
    assert global_operation["status"] == OperationStatus.COMPLETED.value
    assert global_patch.get_json()["meta"]["op_id"] == global_operation["op_id"]
    global_audit = store.reader().execute(
        "SELECT event_type, payload FROM audit_records WHERE operation_id = ?",
        (global_operation["op_id"],),
    ).fetchone()
    assert global_audit is not None
    assert global_audit["event_type"] == "operation.configedit.completed"
    global_audit_payload = json.loads(global_audit["payload"])
    assert global_audit_payload["before"]["timezone"] == "UTC"
    assert global_audit_payload["after"]["timezone"] == "Pacific/Auckland"

    world_response = client.get("/api/worlds/world_1/settings")
    assert world_response.status_code == 200
    assert world_response.get_json()["data"]["settings"]["backup_root_path"] == "D:/world-backups"
    assert world_response.get_json()["data"]["version"] == 1

    patch_response = client.patch(
        "/api/worlds/world_1/settings",
        json={"version": 1, "idle_countdown_seconds": 30},
    )
    assert patch_response.status_code == 200
    assert patch_response.get_json()["data"]["settings"]["idle_countdown_seconds"] == 30
    world_operation = patch_response.get_json()["data"]["operation"]
    assert world_operation["op_type"] == OperationType.CONFIG_EDIT.value
    assert world_operation["status"] == OperationStatus.COMPLETED.value
    assert patch_response.get_json()["meta"]["op_id"] == world_operation["op_id"]
    clear_override = client.patch(
        "/api/worlds/world_1/settings",
        json={"version": 2, "backup_root_path": None},
    )
    assert clear_override.status_code == 200
    assert clear_override.get_json()["data"]["settings"]["backup_root_path"] == "C:/backups"
    notification_patch = client.patch(
        "/api/worlds/world_1/settings",
        json={"version": 3, "notification_defaults": {"level": "world"}},
    )
    assert notification_patch.status_code == 400


def test_settings_api_creates_first_world_override_from_global_fallback(store, clock):
    _seed_configuration(store, with_override=False)
    service = ConfigurationService(store, clock)
    app = Flask(__name__)
    app.extensions["mcmanager_container"] = SimpleNamespace(
        configuration=service,
        store=store,
    )
    app.before_request(lambda: setattr(g, "current_user_id", "u_admin"))
    from app.web.api import register_api_blueprints

    register_api_blueprints(app)
    errors = importlib.import_module("app.web.errors")
    errors.register_error_handlers(app)
    client = app.test_client()

    fallback = client.get("/api/worlds/world_1/settings").get_json()["data"]
    assert fallback["version"] == 0
    assert fallback["settings"]["backup_root_path"] == "C:/backups"

    stale = client.patch(
        "/api/worlds/world_1/settings",
        json={"version": 1, "backup_root_path": "D:/stale"},
    )
    assert stale.status_code == 409
    assert stale.get_json()["error"]["code"] == "CONFIG_VERSION_CONFLICT"
    assert store.reader().execute(
        "SELECT 1 FROM operations WHERE op_type = ?",
        (OperationType.CONFIG_EDIT.value,),
    ).fetchone() is None
    assert store.reader().execute(
        "SELECT 1 FROM audit_records WHERE operation_id IS NOT NULL"
    ).fetchone() is None

    updated = client.patch(
        "/api/worlds/world_1/settings",
        json={"version": 0, "backup_root_path": "D:/world-backups"},
    )

    assert updated.status_code == 200
    assert updated.get_json()["data"]["version"] == 1
    assert updated.get_json()["data"]["settings"]["backup_root_path"] == "D:/world-backups"


def test_settings_api_returns_version_conflict_without_creating_operation(store, clock):
    _seed_configuration(store, with_override=False)
    service = ConfigurationService(store, clock)
    app = Flask(__name__)
    app.extensions["mcmanager_container"] = SimpleNamespace(
        configuration=service,
        store=store,
    )
    app.before_request(lambda: setattr(g, "current_user_id", "u_admin"))
    from app.web.api import register_api_blueprints

    register_api_blueprints(app)
    errors = importlib.import_module("app.web.errors")
    errors.register_error_handlers(app)

    response = app.test_client().patch(
        "/api/settings",
        json={"version": 0, "timezone": "Pacific/Auckland"},
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "CONFIG_VERSION_CONFLICT"
    assert store.reader().execute(
        "SELECT 1 FROM operations WHERE op_type = ?",
        (OperationType.CONFIG_EDIT.value,),
    ).fetchone() is None


def test_settings_api_maps_stale_updates_to_409_without_global_error_registration(store, clock):
    _seed_configuration(store, with_override=False)
    service = ConfigurationService(store, clock)
    app = Flask(__name__)
    app.extensions["mcmanager_container"] = SimpleNamespace(
        configuration=service,
        store=store,
    )
    app.before_request(lambda: setattr(g, "current_user_id", "u_admin"))
    from app.web.api import register_api_blueprints

    register_api_blueprints(app)

    response = app.test_client().patch(
        "/api/worlds/world_1/settings",
        json={"version": 1, "backup_root_path": "D:/stale"},
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "CONFIG_VERSION_CONFLICT"
    assert store.reader().execute(
        "SELECT 1 FROM operations WHERE op_type = ?",
        (OperationType.CONFIG_EDIT.value,),
    ).fetchone() is None


def test_settings_mutations_require_administrator_middleware():
    from app.web.middleware import _requires_admin

    app = Flask(__name__)
    with app.test_request_context("/api/settings", method="PATCH"):
        assert _requires_admin()
    with app.test_request_context("/api/worlds/world_1/settings", method="PATCH"):
        assert _requires_admin()


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
