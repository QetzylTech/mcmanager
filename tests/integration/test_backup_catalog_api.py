from __future__ import annotations

import hashlib
import json
import shutil
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

import app.bootstrap as bootstrap
from app import create_app
from app.domain.value_objects import ActorType, OperationStatus, OperationType
from app.services.backup import BackupResult
from app.services.operations import OperationInput
from app.services.worlds import WorldsService
from app.web.middleware import session_csrf_token


@pytest.fixture
def backup_api_app(migrations_dir, clock, monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap, "WorldsService", partial(WorldsService, minecraft=object()))
    app = create_app(
        database_path=tmp_path / "backup-api.db",
        keyfile_path=tmp_path / "backup-api.key",
        migrations_dir=migrations_dir,
        clock=clock,
    )
    container = app.extensions["mcmanager_container"]
    now = int(clock.now())
    writer = container.store.writer()
    writer.execute(
        """INSERT INTO templates (
            template_id, name, category, default_version, config_defaults, source,
            deprecated, version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('api_tpl', 'API template', 'vanilla', '1.21', '{}', 'built_in',
                  0, 1, NULL, NULL, ?, ?)""",
        (now, now),
    )
    writer.execute(
        """INSERT INTO java_runtimes (
            runtime_id, label, executable_path, version_detected, status,
            deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('api_java', 'API Java', 'java', '21', 'verified', NULL, NULL, ?, ?)""",
        (now, now),
    )
    world_dir = tmp_path / "world"
    world_dir.mkdir()
    (world_dir / "level.dat").write_bytes(b"api world state")
    writer.execute(
        """INSERT INTO world_instances (
            world_id, display_name, template_id, server_type, mc_version, java_runtime_id,
            port, addressing_strategy, addressing_value, state, pre_backup_state,
            launch_args, metadata_version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('api_world', 'API world', 'api_tpl', 'vanilla', '1.21', 'api_java',
                  25570, 'path', ?, 'off', NULL, '{}', 1, NULL, NULL, ?, ?)""",
        (str(world_dir), now, now),
    )
    writer.commit()
    monkeypatch.setattr(
        container.configuration,
        "resolve_effective",
        lambda _world_id: {
            "minecraft_root_path": str(tmp_path),
            "backup_root_path": str(tmp_path / "backups"),
            "log_root_path": str(tmp_path / "logs"),
            "offsite_sync_defaults": None,
        },
    )
    try:
        yield app, tmp_path
    finally:
        app.extensions["mcmanager_shutdown"]()


def _admin_client(app):
    container = app.extensions["mcmanager_container"]
    container.auth.provision_first_superadmin(
        username="backup-admin",
        password="a-strong-password-123",
        device_id="backup-admin-device",
        device_name="Backup Admin",
        ip="127.0.0.1",
    )
    session = container.auth.authenticate(
        username="backup-admin",
        password="a-strong-password-123",
        device_id="backup-admin-device",
        device_name="Backup Admin",
        ip="127.0.0.1",
    )
    client = app.test_client()
    token = session_csrf_token(session.token)
    client.set_cookie("mcmanager_session", session.token)
    client.set_cookie("csrf_token", token)
    return client, {"X-CSRF-Token": token}


def _seed_artifact(app, root: Path, artifact_id: str, *, age_days: int = 0) -> Path:
    container = app.extensions["mcmanager_container"]
    path = root / f"{artifact_id}.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = artifact_id.encode()
    path.write_bytes(content)
    operation = container.operations.create(
        OperationInput(
            op_type=OperationType.BACKUP,
            actor_type=ActorType.SYSTEM,
            world_id="api_world",
        )
    )
    container.operations.transition(operation["op_id"], OperationStatus.COMPLETED)
    container.store.writer().execute(
        """INSERT INTO backup_artifacts (
            artifact_id, world_id, category, storage_path, size_bytes, checksum,
            suspect, operation_id, deleted_at, deleted_by, created_at
        ) VALUES (?, 'api_world', 'manual', ?, ?, ?, 0, ?, NULL, NULL, ?)""",
        (
            artifact_id,
            str(path),
            len(content),
            hashlib.sha256(content).hexdigest(),
            operation["op_id"],
            int(container.clock.now()) - age_days * 86400,
        ),
    )
    container.store.writer().commit()
    return path


def test_backup_catalog_auth_shapes_and_durable_operation(backup_api_app, monkeypatch):
    app, tmp_path = backup_api_app
    client, headers = _admin_client(app)
    anonymous = app.test_client()

    denied = anonymous.get("/api/worlds/api_world/backups")
    assert denied.status_code == 401
    assert denied.json["error"]["code"] == "AUTH_SESSION_INVALID"
    no_csrf = client.post("/api/worlds/api_world/backups", json={"category": "manual"})
    assert no_csrf.status_code == 403
    assert no_csrf.json["error"]["code"] == "CSRF_INVALID"

    container = app.extensions["mcmanager_container"]
    _seed_artifact(app, tmp_path / "backups", "protected_backup")
    calls = []

    def create_backup(**kwargs):
        calls.append(kwargs)
        return BackupResult("api_created", "unused.zip", "a" * 64, 15, 0)

    monkeypatch.setattr(container.backups, "create_world_backup", create_backup)
    created = client.post(
        "/api/worlds/api_world/backups",
        json={"category": "manual"},
        headers={**headers, "Idempotency-Key": "backup-request-1"},
    )
    assert created.status_code == 202
    assert created.json["ok"] is True
    op_id = created.json["meta"]["op_id"]
    assert created.json["meta"]["idempotency_key"] == "backup-request-1"
    assert created.json["meta"]["queue_position"] == 1
    assert created.json["data"]["operation"]["status"] == "Queued"

    replay = client.post(
        "/api/worlds/api_world/backups",
        json={"category": "manual"},
        headers={**headers, "Idempotency-Key": "backup-request-1"},
    )
    assert replay.status_code == 200
    assert replay.json["meta"]["op_id"] == op_id
    container.catalog_operations.dispatch_queued_operations()
    assert calls and calls[0]["category"].value == "manual"
    assert container.operations.get(op_id)["status"] == "Completed"

    listing = client.get("/api/worlds/api_world/backups")
    assert listing.status_code == 200
    assert listing.json["ok"] is True
    assert len(listing.json["data"]["backups"]) == 1
    assert listing.json["data"]["backups"][0]["retention_protected"] is True
    assert listing.json["meta"]["pagination"]["total"] == 1


def test_restore_rollback_uses_pre_restore_artifact_and_step_up(backup_api_app, monkeypatch):
    app, tmp_path = backup_api_app
    client, headers = _admin_client(app)
    container = app.extensions["mcmanager_container"]
    artifact_path = _seed_artifact(app, tmp_path / "backups", "rollback_source")
    with ZipFile(artifact_path, "w") as archive:
        archive.writestr("level.dat", b"rollback world state")
    checksum = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    container.store.writer().execute(
        "UPDATE backup_artifacts SET size_bytes = ?, checksum = ? WHERE artifact_id = ?",
        (artifact_path.stat().st_size, checksum, "rollback_source"),
    )
    container.store.writer().commit()
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=10**15, used=0, free=10**15),
    )
    session = container.auth.authenticate(
        username="backup-admin",
        password="a-strong-password-123",
        device_id="backup-admin-device",
        device_name="Backup Admin",
        ip="127.0.0.1",
    )
    restore_operation = container.operations.create(
        OperationInput(
            op_type=OperationType.RESTORE,
            actor_type=ActorType.USER,
            actor_user_id=session.user_id,
            world_id="api_world",
        )
    )
    container.operations.transition(restore_operation["op_id"], OperationStatus.COMPLETED)
    writer = container.store.writer()
    writer.execute(
        """INSERT INTO restore_history (
            restore_id, world_id, operation_id, source_artifact_id, pre_restore_artifact_id,
            operator_user_id, outcome, rollback_of_restore_id, started_at, finished_at, created_at
        ) VALUES ('api_restore', 'api_world', ?, 'rollback_source', 'rollback_source', ?,
                  'success', NULL, ?, ?, ?)""",
        (
            restore_operation["op_id"],
            session.user_id,
            int(container.clock.now()),
            int(container.clock.now()),
            int(container.clock.now()),
        ),
    )
    writer.commit()

    from app.services.auth import StepUpRequiredError

    monkeypatch.setattr(
        container.auth,
        "require_step_up",
        lambda _session: (_ for _ in ()).throw(StepUpRequiredError("fresh step-up required")),
    )
    denied = client.post(
        "/api/worlds/api_world/restores/rollback",
        json={"restore_id": "api_restore"},
        headers=headers,
    )
    assert denied.status_code == 403
    assert denied.json["error"]["code"] == "STEP_UP_REQUIRED"

    monkeypatch.setattr(container.auth, "require_step_up", lambda _session: None)
    invalid_path = _seed_artifact(app, tmp_path / "backups", "invalid_restore")
    invalid = client.post(
        "/api/worlds/api_world/restores",
        json={"artifact_id": "invalid_restore"},
        headers={**headers, "Idempotency-Key": "invalid-restore-1"},
    )
    assert invalid.status_code == 202
    container.catalog_operations.dispatch_queued_operations()
    failed_restore = container.operations.get(invalid.json["meta"]["op_id"])
    assert failed_restore["status"] == "Failed"
    assert failed_restore["error_code"] == "RESTORE_ARTIFACT_INVALID"
    assert invalid_path.is_file()

    response = client.post(
        "/api/worlds/api_world/restores/rollback",
        json={"restore_id": "api_restore"},
        headers={**headers, "Idempotency-Key": "rollback-request-1"},
    )
    assert response.status_code == 202
    op_id = response.json["meta"]["op_id"]
    operation = container.operations.get(op_id)
    payload = json.loads(operation["data_json"])
    assert payload["artifact_id"] == "rollback_source"
    assert payload["rollback_of_restore_id"] == "api_restore"
    container.catalog_operations.dispatch_queued_operations()
    result = container.store.reader().execute(
        "SELECT restore_id, rollback_of_restore_id, source_artifact_id, outcome "
        "FROM restore_history WHERE operation_id = ?",
        (op_id,),
    ).fetchone()
    assert result["rollback_of_restore_id"] == "api_restore"
    assert result["source_artifact_id"] == "rollback_source"
    assert result["outcome"] == "success"
    assert artifact_path.is_file()


def test_cleanup_preview_execute_and_sync_attempt_catalog(backup_api_app, monkeypatch):
    app, tmp_path = backup_api_app
    client, headers = _admin_client(app)
    container = app.extensions["mcmanager_container"]
    monkeypatch.setattr(container.auth, "require_step_up", lambda _session: None)
    artifacts = {
        f"cleanup_{index}": _seed_artifact(
            app, tmp_path / "backups", f"cleanup_{index}", age_days=10 - index
        )
        for index in range(5)
    }

    unsupported = client.post(
        "/api/cleanup/dry-run",
        json={"scope": "logs"},
        headers=headers,
    )
    assert unsupported.status_code == 501
    assert unsupported.json["error"]["code"] == "CLEANUP_SCOPE_UNSUPPORTED"

    preview = client.post(
        "/api/cleanup/dry-run",
        json={"scope": "backups", "world_id": "api_world"},
        headers={**headers, "Idempotency-Key": "cleanup-preview-1"},
    )
    assert preview.status_code == 202
    preview_id = preview.json["meta"]["op_id"]
    container.catalog_operations.dispatch_queued_operations()
    preview_row = container.operations.get(preview_id)
    assert preview_row["status"] == "Completed"
    preview_data = json.loads(preview_row["data_json"])
    assert preview_data["mode"] == "dry_run"
    assert preview_data["target_count"] == 2

    missing_preview = client.post(
        "/api/cleanup/execute",
        json={"scope": "backups", "world_id": "api_world", "dry_run_operation_id": "missing"},
        headers=headers,
    )
    assert missing_preview.status_code == 409
    assert missing_preview.json["error"]["code"] == "CLEANUP_PREVIEW_REQUIRED"

    execute = client.post(
        "/api/cleanup/execute",
        json={
            "scope": "backups",
            "world_id": "api_world",
            "dry_run_operation_id": preview_id,
        },
        headers={**headers, "Idempotency-Key": "cleanup-execute-1"},
    )
    assert execute.status_code == 202
    container.catalog_operations.dispatch_queued_operations()
    assert container.operations.get(execute.json["meta"]["op_id"])["status"] == "Completed"
    assert not artifacts["cleanup_0"].exists()
    assert not artifacts["cleanup_1"].exists()
    runs = client.get("/api/cleanup/runs")
    assert runs.status_code == 200
    assert len(runs.json["data"]["cleanup_runs"]) == 2

    unresolved = client.post(
        "/api/sync/retry",
        json={"artifact_id": "cleanup_4"},
        headers=headers,
    )
    assert unresolved.status_code == 409
    assert unresolved.json["error"]["code"] == "SYNC_TARGET_UNRESOLVED"

    secret_id = container.store.reader().execute(
        "SELECT secret_id FROM secrets ORDER BY created_at LIMIT 1"
    ).fetchone()["secret_id"]
    target_path = tmp_path / "nas"
    now = int(container.clock.now())
    container.store.writer().execute(
        """INSERT INTO sync_targets (
            sync_target_id, scope, world_id, target_type, config, secret_id, enabled,
            version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('api_nas', 'global', NULL, 'nas', ?, ?, 1, 1, NULL, NULL, ?, ?)""",
        (json.dumps({"path": str(target_path)}), secret_id, now, now),
    )
    container.store.writer().commit()
    sync_target = client.get("/api/sync/targets")
    assert sync_target.status_code == 200
    assert sync_target.json["data"]["sync_targets"][0]["effective"] is True

    retry = client.post(
        "/api/sync/retry",
        json={"artifact_id": "cleanup_4"},
        headers={**headers, "Idempotency-Key": "sync-retry-1"},
    )
    assert retry.status_code == 202
    container.catalog_operations.dispatch_queued_operations()
    sync = client.get("/api/backups/cleanup_4/sync")
    assert sync.status_code == 200
    assert sync.json["data"]["sync"]["status"] == "succeeded"
    assert [attempt["outcome"] for attempt in sync.json["data"]["attempts"]] == [
        "succeeded"
    ]
    records = client.get("/api/sync/records?status=succeeded")
    assert records.status_code == 200
    assert records.json["data"]["sync_records"][0]["artifact_id"] == "cleanup_4"


def test_backup_delete_enqueues_idempotent_cleanup_and_audits(
    backup_api_app, monkeypatch
):
    app, tmp_path = backup_api_app
    admin, headers = _admin_client(app)
    container = app.extensions["mcmanager_container"]
    monkeypatch.setattr(container.auth, "require_step_up", lambda _session: None)
    artifact = _seed_artifact(app, tmp_path / "backups", "retained_one")
    from app.services.auth import StepUpRequiredError

    monkeypatch.setattr(
        container.auth,
        "require_step_up",
        lambda _session: (_ for _ in ()).throw(StepUpRequiredError("step-up required")),
    )
    step_up_denied = admin.delete(
        "/api/backups/retained_one?force=true", headers=headers
    )
    assert step_up_denied.status_code == 403
    assert step_up_denied.json["error"]["code"] == "STEP_UP_REQUIRED"
    monkeypatch.setattr(container.auth, "require_step_up", lambda _session: None)

    blocked = admin.delete("/api/backups/retained_one", headers=headers)
    assert blocked.status_code == 409
    assert blocked.json["error"]["code"] == "BACKUP_RETENTION_GUARD"
    assert artifact.is_file()
    for index in range(3):
        _seed_artifact(app, tmp_path / "backups", f"retained_{index + 2}")
    delete_headers = {**headers, "Idempotency-Key": "delete-backup-1"}
    accepted = admin.delete("/api/backups/retained_one", headers=delete_headers)
    assert accepted.status_code == 202
    assert accepted.json["data"]["operation"]["status"] == "Queued"
    operation_id = accepted.json["meta"]["op_id"]
    assert artifact.is_file()

    replay = admin.delete("/api/backups/retained_one", headers=delete_headers)
    assert replay.status_code == 200
    assert replay.json["meta"]["op_id"] == operation_id

    container.catalog_operations.dispatch_queued_operations()
    operation = container.operations.get(operation_id)
    assert operation["status"] == "Completed"
    assert json.loads(operation["data_json"]) == {
        "artifact_id": "retained_one",
        "deleted": True,
    }
    assert not artifact.exists()
    artifact_row = container.store.reader().execute(
        "SELECT deleted_at, deleted_by FROM backup_artifacts WHERE artifact_id = ?",
        ("retained_one",),
    ).fetchone()
    assert artifact_row["deleted_at"] is not None
    assert artifact_row["deleted_by"] == container.auth.validate_session(
        admin.get_cookie("mcmanager_session").value, ip="127.0.0.1"
    ).user_id
    audit_count = container.store.reader().execute(
        "SELECT count(*) FROM audit_records WHERE operation_id = ?",
        (operation_id,),
    ).fetchone()[0]
    assert audit_count == 1
    completed_replay = admin.delete("/api/backups/retained_one", headers=delete_headers)
    assert completed_replay.status_code == 200
    assert completed_replay.json["meta"]["op_id"] == operation_id

    forced_artifact = _seed_artifact(app, tmp_path / "backups", "forced_backup")
    forced = admin.delete(
        "/api/backups/forced_backup?force=true",
        headers={**headers, "Idempotency-Key": "delete-backup-force-1"},
    )
    assert forced.status_code == 202
    assert forced_artifact.is_file()
    container.catalog_operations.dispatch_queued_operations()
    assert not forced_artifact.exists()
    assert container.operations.get(forced.json["meta"]["op_id"])["status"] == "Completed"

    role = admin.post("/api/roles", json={"name": "Backup Reader"}, headers=headers)
    user = admin.post(
        "/api/users",
        json={
            "username": "backup-reader",
            "password": "another-strong-password",
            "role_id": role.json["data"]["role_id"],
        },
        headers=headers,
    )
    assert user.status_code == 201
    session = container.auth.authenticate(
        username="backup-reader",
        password="another-strong-password",
        device_id="backup-reader-device",
        device_name="Backup Reader",
        ip="127.0.0.1",
    )
    regular = app.test_client()
    regular_token = session_csrf_token(session.token)
    regular.set_cookie("mcmanager_session", session.token)
    regular.set_cookie("csrf_token", regular_token)
    assert regular.get("/api/cleanup/runs").status_code == 403
    regular_force = regular.delete(
        "/api/backups/retained_2?force=true",
        headers={"X-CSRF-Token": regular_token},
    )
    assert regular_force.status_code == 403
    assert regular_force.json["error"]["code"] == "AUTH_FORBIDDEN"
