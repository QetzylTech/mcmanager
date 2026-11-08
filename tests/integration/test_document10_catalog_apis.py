from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import time
import zipfile
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest

import app.bootstrap as bootstrap
from app import create_app
from app.ports.secrets_store import SecretType
from app.services.worlds import WorldsService
from app.web.middleware import session_csrf_token


@pytest.fixture
def catalog_app(migrations_dir, clock, monkeypatch):
    monkeypatch.setattr(bootstrap, "WorldsService", partial(WorldsService, minecraft=object()))
    run_id = uuid4().hex
    directory = Path(__file__).resolve().parent
    database_path = directory / f".catalog-api-{run_id}.db"
    keyfile_path = directory / f".catalog-api-{run_id}.key"
    app = create_app(
        database_path=database_path,
        keyfile_path=keyfile_path,
        migrations_dir=migrations_dir,
        clock=clock,
    )
    try:
        yield app
    finally:
        app.extensions["mcmanager_shutdown"]()
        for path in (
            database_path,
            database_path.with_name(database_path.name + "-wal"),
            database_path.with_name(database_path.name + "-shm"),
            keyfile_path,
        ):
            path.unlink(missing_ok=True)


def _admin_client(app):
    container = app.extensions["mcmanager_container"]
    container.auth.provision_first_superadmin(
        username="catalog-admin",
        password="a-strong-password-123",
        device_id="catalog-admin-device",
        device_name="Catalog Admin",
        ip="127.0.0.1",
    )
    session = container.auth.authenticate(
        username="catalog-admin",
        password="a-strong-password-123",
        device_id="catalog-admin-device",
        device_name="Catalog Admin",
        ip="127.0.0.1",
    )
    client = app.test_client()
    client.set_cookie("mcmanager_session", session.token)
    client.set_cookie("csrf_token", session_csrf_token(session.token))
    return client, {"X-CSRF-Token": session_csrf_token(session.token)}


def test_schedule_template_and_java_runtime_catalog_routes(catalog_app):
    client, headers = _admin_client(catalog_app)

    created_schedule = client.post(
        "/api/schedules",
        json={
            "scope": "global",
            "world_id": None,
            "schedule_type": "backup",
            "interval_spec": {"kind": "daily"},
            "time_of_day": "02:30",
        },
        headers=headers,
    )
    assert created_schedule.status_code == 201
    schedule_id = created_schedule.json["data"]["schedule"]["schedule_id"]
    assert (
        client.get("/api/schedules?scope=global").json["data"]["schedules"][0]["schedule_id"]
        == schedule_id
    )

    stale = client.patch(
        f"/api/schedules/{schedule_id}",
        json={"version": 9, "enabled": False},
        headers=headers,
    )
    assert stale.status_code == 409
    assert stale.json["error"]["code"] == "CONFIG_VERSION_CONFLICT"

    template = client.post(
        "/api/templates",
        json={
            "name": "API Test Template",
            "category": "vanilla",
            "default_version": "1.21",
            "config_defaults": {"launch_command_template": "java -jar server.jar"},
        },
        headers=headers,
    )
    assert template.status_code == 201
    assert client.get("/api/templates?category=vanilla").json["data"]["templates"]

    runtime = client.post(
        "/api/java-runtimes",
        json={"label": "missing-java", "path": "missing-java-executable"},
        headers=headers,
    )
    assert runtime.status_code == 201
    runtime_id = runtime.json["data"]["runtime"]["runtime_id"]
    runtime_list = client.get("/api/java-runtimes?status=registered")
    assert runtime_list.status_code == 200
    assert runtime_list.json["data"]["java_runtimes"][0]["runtime_id"] == runtime_id
    stale_runtime = client.patch(
        f"/api/java-runtimes/{runtime_id}",
        json={"version": 2, "label": "new-label"},
        headers=headers,
    )
    assert stale_runtime.status_code == 409


def test_missed_runs_notifications_and_audit_routes(catalog_app):
    client, headers = _admin_client(catalog_app)
    container = catalog_app.extensions["mcmanager_container"]
    writer = container.store.writer()
    writer.execute(
        "INSERT INTO missed_run_records (missed_run_id, schedule_id, schedule_name_snapshot, "
        "schedule_type_snapshot, expected_run_at, detected_at, resolution, resolution_at, "
        "resolution_by, created_at) VALUES ('mr_api_test', 'missing-schedule', "
        "'Global backup schedule', 'backup', 100, 101, 'pending', NULL, NULL, 101)"
    )
    writer.commit()

    missed = client.get("/api/missed-runs?resolution=pending")
    assert missed.status_code == 200
    resolved = client.patch(
        "/api/missed-runs/mr_api_test",
        json={"resolution": "ignored"},
        headers=headers,
    )
    assert resolved.status_code == 200
    terminal = client.patch(
        "/api/missed-runs/mr_api_test",
        json={"resolution": "resolved"},
        headers=headers,
    )
    assert terminal.status_code == 409

    from app.domain.value_objects import NotificationSeverity
    from app.services.notifications import NotificationInput

    notification_id = container.notifications.publish(
        NotificationInput(
            category="security",
            severity=NotificationSeverity.HIGH,
            message="API test notification",
        )
    )
    notifications = client.get("/api/notifications?read=false")
    assert notifications.status_code == 200
    assert notifications.json["meta"]["unread_count"] == 1
    assert (
        client.post(f"/api/notifications/{notification_id}/read", headers=headers).status_code
        == 201
    )
    assert client.post("/api/notifications/read-all", headers=headers).status_code == 200

    audit = client.get("/api/audit?sort=-created_at")
    assert audit.status_code == 200
    audit_id = audit.json["data"]["audit"][0]["audit_id"]
    assert client.get(f"/api/audit/{audit_id}").status_code == 200


def test_admin_catalog_endpoints_enforce_superadmin_and_csrf(catalog_app):
    client, headers = _admin_client(catalog_app)
    assert client.get("/api/roles").status_code == 200
    assert client.get("/api/users").status_code == 200
    assert client.get("/api/setup").status_code == 200
    assert client.get("/api/manager").status_code == 200

    role = client.post(
        "/api/roles",
        json={"name": "Catalog Reader", "description": "test role"},
        headers=headers,
    )
    assert role.status_code == 201
    role_id = role.json["data"]["role_id"]
    permission = client.post(
        "/api/permissions",
        json={"role_id": role_id, "action_category": "world.view"},
        headers=headers,
    )
    assert permission.status_code == 201
    assert (
        client.delete(
            f"/api/permissions/{permission.json['data']['permission_id']}",
            headers=headers,
        ).status_code
        == 200
    )

    assert client.post("/api/notifications/read-all").status_code == 403
    assert client.get("/api/java-runtimes").status_code == 200


def test_manager_backup_is_durable_and_uses_a_consistent_database_snapshot(
    catalog_app, tmp_path
):
    client, headers = _admin_client(catalog_app)
    container = catalog_app.extensions["mcmanager_container"]
    backup_root = Path(container.store.path).with_suffix(".backups")

    try:
        response = client.post("/api/manager/backup", headers=headers)
        assert response.status_code == 202
        operation_id = response.json["meta"]["op_id"]
        assert response.json["data"]["operation"]["status"] == "Queued"

        deadline = time.monotonic() + 5
        operation = None
        while time.monotonic() < deadline:
            container.catalog_operations.dispatch_queued_operations()
            operation = container.operations.get(operation_id)
            if operation["status"] in {"Completed", "Failed", "Cancelled", "TimedOut"}:
                break
            time.sleep(0.01)

        assert operation is not None
        assert operation["status"] == "Completed", operation["message"]
        result = json.loads(operation["data_json"])
        artifact = container.store.reader().execute(
            "SELECT * FROM backup_artifacts WHERE artifact_id = ?",
            (result["artifact_id"],),
        ).fetchone()
        assert artifact["world_id"] is None
        assert artifact["category"] == "manager_config"
        assert artifact["operation_id"] == operation_id
        assert Path(artifact["storage_path"]).is_file()
        assert hashlib.sha256(Path(artifact["storage_path"]).read_bytes()).hexdigest() == artifact[
            "checksum"
        ]

        with zipfile.ZipFile(artifact["storage_path"]) as archive:
            assert archive.namelist() == ["manager.sqlite3"]
            snapshot_path = tmp_path / "manager.sqlite3"
            snapshot_path.write_bytes(archive.read("manager.sqlite3"))
        snapshot = sqlite3.connect(snapshot_path)
        try:
            assert snapshot.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert snapshot.execute("SELECT count(*) FROM users").fetchone()[0] == 1
        finally:
            snapshot.close()

        audit = container.store.reader().execute(
            "SELECT count(*) FROM audit_records WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()[0]
        assert audit == 1
        assert client.post("/api/manager/restart", headers=headers).status_code == 403
    finally:
        shutil.rmtree(backup_root, ignore_errors=True)


def test_last_superadmin_cannot_be_disabled_or_deleted(catalog_app):
    client, headers = _admin_client(catalog_app)
    container = catalog_app.extensions["mcmanager_container"]
    row = container.store.reader().execute(
        "SELECT u.user_id FROM users u "
        "JOIN role_assignments ra ON ra.user_id = u.user_id "
        "JOIN roles r ON r.role_id = ra.role_id "
        "WHERE r.name = 'Superadmin' AND u.deleted_at IS NULL LIMIT 1"
    ).fetchone()
    user_id = row["user_id"]

    disabled = client.patch(
        f"/api/users/{user_id}",
        json={"status": "disabled"},
        headers=headers,
    )
    deleted = client.delete(f"/api/users/{user_id}", headers=headers)

    assert disabled.status_code == 409
    assert disabled.json["error"]["code"] == "FORBIDDEN_LAST_SUPERADMIN"
    assert deleted.status_code == 409
    assert deleted.json["error"]["code"] == "FORBIDDEN_LAST_SUPERADMIN"
    remaining = container.store.reader().execute(
        "SELECT status, deleted_at FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    assert remaining["status"] == "active"
    assert remaining["deleted_at"] is None


def test_sync_target_api_never_exposes_secret_values(catalog_app):
    client, _headers = _admin_client(catalog_app)
    container = catalog_app.extensions["mcmanager_container"]
    plaintext = "sync-credential-must-not-leak"
    secret_id = container.secrets.store(
        secret_type=SecretType.SYNC_CREDENTIAL,
        associated_entity_type="manager",
        associated_entity_id="security-test",
        plaintext=plaintext,
    )
    now = int(container.clock.now())
    writer = container.store.writer()
    writer.execute(
        """INSERT INTO sync_targets (
            sync_target_id, scope, world_id, target_type, config, secret_id,
            enabled, version, deleted_at, deleted_by, created_at, updated_at
        ) VALUES ('security-sync-target', 'global', NULL, 'nas', '{}', ?, 1,
                  1, NULL, NULL, ?, ?)""",
        (secret_id, now, now),
    )
    writer.commit()

    response = client.get("/api/sync/targets")
    payload = json.dumps(response.get_json())

    assert response.status_code == 200
    assert secret_id in payload
    assert plaintext not in payload
    assert "encrypted_value" not in payload


def test_non_superadmin_can_use_personal_notifications_but_not_admin_catalogs(catalog_app):
    admin, admin_headers = _admin_client(catalog_app)
    role = admin.post(
        "/api/roles",
        json={"name": "Catalog User"},
        headers=admin_headers,
    )
    assert role.status_code == 201
    user = admin.post(
        "/api/users",
        json={
            "username": "catalog-user",
            "password": "another-strong-password",
            "role_id": role.json["data"]["role_id"],
        },
        headers=admin_headers,
    )
    assert user.status_code == 201

    container = catalog_app.extensions["mcmanager_container"]
    session = container.auth.authenticate(
        username="catalog-user",
        password="another-strong-password",
        device_id="catalog-user-device",
        device_name="Catalog User",
        ip="127.0.0.1",
    )
    client = catalog_app.test_client()
    token = session_csrf_token(session.token)
    client.set_cookie("mcmanager_session", session.token)
    client.set_cookie("csrf_token", token)
    assert client.get("/api/notifications").status_code == 200
    assert (
        client.post("/api/notifications/read-all", headers={"X-CSRF-Token": token}).status_code
        == 200
    )
    assert client.get("/api/users").status_code == 403


def test_first_run_setup_accepts_matching_pre_authentication_csrf(catalog_app):
    client = catalog_app.test_client()
    client.get("/")
    token = client.get_cookie("csrf_token").value
    response = client.post(
        "/api/setup",
        json={"username": "first-admin", "password": "first-admin-password"},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 201
    assert response.json["data"]["setup_completed"] is True


def test_anonymous_catalog_and_audit_reads_are_rejected(catalog_app):
    for path in ("/api/schedules", "/api/templates", "/api/notifications", "/api/audit"):
        response = catalog_app.test_client().get(path)
        assert response.status_code == 401
        assert response.json["error"]["code"] == "AUTH_SESSION_INVALID"


def test_session_includes_grants_device_and_iso_expiry(catalog_app):
    client, headers = _admin_client(catalog_app)
    session = client.get("/api/session")
    payload = session.json["data"]
    assert session.status_code == 200
    assert payload["device"]["device_id"] == "catalog-admin-device"
    assert payload["expires_at"].endswith("Z")
    assert payload["step_up_expires_at"] is None

    permission = client.post(
        "/api/permissions",
        json={"user_id": payload["user_id"], "action_category": "world.view"},
        headers=headers,
    )
    assert permission.status_code == 201
    refreshed = client.get("/api/session").json["data"]
    assert any(
        grant["permission_id"] == permission.json["data"]["permission_id"]
        for grant in refreshed["permission_grants"]
    )
