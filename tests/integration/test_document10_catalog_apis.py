from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import time
import zipfile
from functools import partial
from pathlib import Path
from types import SimpleNamespace
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
    assert (
        client.post(f"/api/notifications/{notification_id}/dismiss", headers=headers).status_code
        == 201
    )
    assert client.get("/api/notifications").json["meta"]["pagination"]["total"] == 0
    dismissed_history = client.get("/api/notifications?include_dismissed=true")
    assert dismissed_history.status_code == 200
    assert dismissed_history.json["data"]["notifications"][0]["dismissed_at"] is not None
    assert client.get("/api/notifications?include_dismissed=invalid").status_code == 400

    dismissed_unread_id = container.notifications.publish(
        NotificationInput(
            category="security",
            severity=NotificationSeverity.NORMAL,
            message="Dismissed unread API test notification",
        )
    )
    assert (
        client.post(
            f"/api/notifications/{dismissed_unread_id}/dismiss", headers=headers
        ).status_code
        == 201
    )
    visible_notification_id = container.notifications.publish(
        NotificationInput(
            category="security",
            severity=NotificationSeverity.NORMAL,
            message="Visible API test notification",
        )
    )
    assert client.post("/api/notifications/read-all", headers=headers).status_code == 200
    visible_history = client.get("/api/notifications?include_dismissed=true&read=true")
    read_notifications = {
        item["notification_id"] for item in visible_history.json["data"]["notifications"]
    }
    assert visible_notification_id in read_notifications
    assert dismissed_unread_id not in read_notifications
    permanent_history = client.get("/api/notifications?include_dismissed=true")
    dismissed = {
        item["notification_id"]: item["dismissed_at"]
        for item in permanent_history.json["data"]["notifications"]
    }
    assert dismissed[dismissed_unread_id] is not None

    audit = client.get("/api/audit?sort=-created_at")
    assert audit.status_code == 200
    audit_id = audit.json["data"]["audit"][0]["audit_id"]
    assert client.get(f"/api/audit/{audit_id}").status_code == 200


def test_history_routes_validate_filters_pagination_and_missing_ids(catalog_app):
    client, headers = _admin_client(catalog_app)

    invalid_requests = (
        ("/api/audit", {"limit": "invalid"}),
        ("/api/audit", {"limit": "501"}),
        ("/api/audit", {"offset": "-1"}),
        ("/api/audit", {"from": "not-a-timestamp"}),
        ("/api/audit", {"to": "not-a-timestamp"}),
        ("/api/audit", {"sort": "payload"}),
        ("/api/notifications", {"severity": "urgent"}),
        ("/api/notifications", {"read": "sometimes"}),
        ("/api/notifications", {"include_dismissed": "sometimes"}),
        ("/api/notifications", {"limit": "invalid"}),
    )
    for path, query in invalid_requests:
        response = client.get(path, query_string=query)
        assert response.status_code == 400
        assert response.json["error"]["code"] == "VALIDATION_ERROR"

    filtered_audit = client.get(
        "/api/audit",
        query_string={
            "actor_user_id": "missing-user",
            "world_id": "missing-world",
            "event_type": "missing-event",
            "from": "1763596800",
            "to": "2026-11-21T23:59:59Z",
            "sort": "event_type,-actor_user_id,world_id,-created_at",
            "limit": "2",
            "offset": "0",
        },
    )
    assert filtered_audit.status_code == 200
    assert filtered_audit.json["meta"]["pagination"]["total"] == 0

    assert client.get("/api/audit/missing-audit").status_code == 404
    assert (
        client.post("/api/notifications/missing-notification/read", headers=headers).status_code
        == 404
    )
    assert (
        client.post("/api/notifications/missing-notification/dismiss", headers=headers).status_code
        == 404
    )


def test_document10_api_route_catalog_matches_registered_api_routes(catalog_app):
    document = (
        Path(__file__).resolve().parents[2] / "docs" / "Document_10_-_API_Contract.md"
    ).read_text(encoding="utf-8")
    def normalized_path(path: str) -> str:
        path = re.sub(r"<(?:[^:<>]+:)?[^<>]+>", "{}", path)
        return re.sub(r"\{[^{}]+\}", "{}", path)

    documented = {
        (method, normalized_path(path))
        for method, path in re.findall(
            r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`\s*\|",
            document,
            flags=re.MULTILINE,
        )
        if path.startswith("/api/")
    }
    registered = {
        (method, normalized_path(rule.rule))
        for rule in catalog_app.url_map.iter_rules()
        if rule.rule.startswith("/api/")
        for method in rule.methods & {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    assert documented == registered, (
        f"undocumented API routes: {sorted(registered - documented)}; "
        f"unregistered documented routes: {sorted(documented - registered)}"
    )


def test_admin_catalog_endpoints_enforce_superadmin_and_csrf(catalog_app):
    client, headers = _admin_client(catalog_app)
    assert client.get("/api/roles").status_code == 200
    assert client.get("/api/users").status_code == 200
    assert client.get("/api/setup").status_code == 200
    manager = client.get("/api/manager")
    assert manager.status_code == 200
    assert set(manager.json["data"]) >= {
        "deployed_version",
        "setup_completed",
        "state",
        "updated_at",
    }

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


def test_manager_backup_is_durable_and_uses_a_consistent_database_snapshot(catalog_app, tmp_path):
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
        artifact = (
            container.store.reader()
            .execute(
                "SELECT * FROM backup_artifacts WHERE artifact_id = ?",
                (result["artifact_id"],),
            )
            .fetchone()
        )
        assert artifact["world_id"] is None
        assert artifact["category"] == "manager_config"
        assert artifact["operation_id"] == operation_id
        assert Path(artifact["storage_path"]).is_file()
        assert (
            hashlib.sha256(Path(artifact["storage_path"]).read_bytes()).hexdigest()
            == artifact["checksum"]
        )

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

        audit = (
            container.store.reader()
            .execute(
                "SELECT count(*) FROM audit_records WHERE operation_id = ?",
                (operation_id,),
            )
            .fetchone()[0]
        )
        assert audit == 1
        assert client.post("/api/manager/restart", headers=headers).status_code == 403
    finally:
        shutil.rmtree(backup_root, ignore_errors=True)


def test_last_superadmin_cannot_be_disabled_or_deleted(catalog_app):
    client, headers = _admin_client(catalog_app)
    container = catalog_app.extensions["mcmanager_container"]
    row = (
        container.store.reader()
        .execute(
            "SELECT u.user_id FROM users u "
            "JOIN role_assignments ra ON ra.user_id = u.user_id "
            "JOIN roles r ON r.role_id = ra.role_id "
            "WHERE r.name = 'Superadmin' AND u.deleted_at IS NULL LIMIT 1"
        )
        .fetchone()
    )
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
    remaining = (
        container.store.reader()
        .execute("SELECT status, deleted_at FROM users WHERE user_id = ?", (user_id,))
        .fetchone()
    )
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


def test_sync_target_crud_validates_versions_and_keeps_credentials_private(catalog_app):
    client, headers = _admin_client(catalog_app)
    container = catalog_app.extensions["mcmanager_container"]
    plaintext = "sync-target-crud-credential"

    created = client.post(
        "/api/sync/targets",
        json={
            "scope": "global",
            "target_type": "nas",
            "config": {"path": "/mnt/backups"},
            "name": "Primary NAS",
            "credential": plaintext,
        },
        headers=headers,
    )
    assert created.status_code == 201
    target = created.json["data"]["sync_target"]
    target_id = target["sync_target_id"]
    assert target["name"] == "Primary NAS"
    assert container.secrets.read(target["secret_id"]) == plaintext

    listing = client.get("/api/sync/targets")
    payload = json.dumps(listing.get_json())
    assert listing.status_code == 200
    assert target_id in payload
    assert plaintext not in payload
    assert "encrypted_value" not in payload

    disabled = client.patch(
        f"/api/sync/targets/{target_id}",
        json={"version": target["version"], "enabled": False},
        headers=headers,
    )
    assert disabled.status_code == 200
    assert disabled.json["data"]["sync_target"]["enabled"] is False
    stale = client.patch(
        f"/api/sync/targets/{target_id}",
        json={"version": target["version"], "enabled": True},
        headers=headers,
    )
    assert stale.status_code == 409
    assert stale.json["error"]["code"] == "CONFIG_VERSION_CONFLICT"

    rotated = client.patch(
        f"/api/sync/targets/{target_id}",
        json={
            "version": disabled.json["data"]["sync_target"]["version"],
            "credential": "rotated-secret",
        },
        headers=headers,
    )
    assert rotated.status_code == 200
    assert (
        container.secrets.read(rotated.json["data"]["sync_target"]["secret_id"]) == "rotated-secret"
    )

    rejected = client.post(
        "/api/sync/targets",
        json={
            "scope": "global",
            "target_type": "nas",
            "config": {"path": "/mnt/backups", "access_token": "must-not-be-config"},
            "credential": "another-secret",
        },
        headers=headers,
    )
    assert rejected.status_code == 400
    assert rejected.json["error"]["code"] == "VALIDATION_ERROR"

    deleted = client.delete(f"/api/sync/targets/{target_id}", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/sync/targets").json["data"]["sync_targets"] == []
    row = (
        container.store.reader()
        .execute(
            "SELECT enabled, deleted_at FROM sync_targets WHERE sync_target_id = ?",
            (target_id,),
        )
        .fetchone()
    )
    assert row["enabled"] == 0
    assert row["deleted_at"] is not None


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
    for path in ("/api/pages", "/api/pages/home"):
        response = client.get(path)
        assert response.status_code == 403
        assert response.json["error"]["code"] == "AUTH_FORBIDDEN"


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


def test_catalog_schedule_template_and_java_runtime_lifecycle(catalog_app, monkeypatch):
    client, headers = _admin_client(catalog_app)
    container = catalog_app.extensions["mcmanager_container"]

    schedule = client.post(
        "/api/schedules",
        json={
            "scope": "global",
            "world_id": None,
            "schedule_type": "maintenance",
            "interval_spec": {"kind": "weekly", "days": [1]},
            "time_of_day": "03:15",
            "enabled": True,
        },
        headers=headers,
    )
    assert schedule.status_code == 201
    schedule_id = schedule.json["data"]["schedule"]["schedule_id"]

    updated = client.patch(
        f"/api/schedules/{schedule_id}",
        json={"version": 1, "enabled": False, "time_of_day": "04:30"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json["data"]["schedule"]["enabled"] is False
    assert updated.json["data"]["schedule"]["time_of_day"] == "04:30"

    invalid_schedule = client.patch(
        f"/api/schedules/{schedule_id}",
        json={"version": 2, "interval_spec": {"kind": "yearly"}},
        headers=headers,
    )
    assert invalid_schedule.status_code == 400
    assert invalid_schedule.json["error"]["code"] == "VALIDATION_ERROR"
    deleted_schedule = client.delete(f"/api/schedules/{schedule_id}", headers=headers)
    assert deleted_schedule.status_code == 200
    assert client.get("/api/schedules").json["data"]["schedules"] == []

    template = client.post(
        "/api/templates",
        json={
            "name": "Lifecycle Template",
            "category": "forge",
            "default_version": "1.21",
            "config_defaults": {"launch_command_template": "java -jar server.jar"},
        },
        headers=headers,
    )
    assert template.status_code == 201
    template_id = template.json["data"]["template_id"]
    renamed = client.patch(
        f"/api/templates/{template_id}",
        json={
            "version": 1,
            "name": "Lifecycle Template Renamed",
            "category": "neoforge",
        },
        headers=headers,
    )
    assert renamed.status_code == 200
    assert renamed.json["data"]["template"]["name"] == "Lifecycle Template Renamed"
    deprecated = client.delete(f"/api/templates/{template_id}", headers=headers)
    assert deprecated.status_code == 200
    assert client.get("/api/templates?deprecated=true").json["data"]["templates"][0]["template_id"] == template_id

    runtime = client.post(
        "/api/java-runtimes",
        json={"label": "Lifecycle Java", "path": "java"},
        headers=headers,
    )
    assert runtime.status_code == 201
    runtime_id = runtime.json["data"]["runtime"]["runtime_id"]
    monkeypatch.setattr(
        container.minecraft_adapter,
        "detect_java",
        lambda _path: SimpleNamespace(full_version="21.0.5"),
    )
    verified = client.post(f"/api/java-runtimes/{runtime_id}/verify", headers=headers)
    assert verified.status_code == 200
    assert verified.json["data"]["status"] == "verified"
    assert verified.json["data"]["version_detected"] == "21.0.5"

    missing_verify = client.post("/api/java-runtimes/missing-runtime/verify", headers=headers)
    assert missing_verify.status_code == 404
    deprecated_runtime = client.delete(f"/api/java-runtimes/{runtime_id}", headers=headers)
    assert deprecated_runtime.status_code == 200
    runtime_row = container.store.reader().execute(
        "SELECT status FROM java_runtimes WHERE runtime_id = ?", (runtime_id,)
    ).fetchone()
    assert runtime_row["status"] == "deprecated"


def test_administration_device_and_role_lifecycle(catalog_app):
    client, headers = _admin_client(catalog_app)
    container = catalog_app.extensions["mcmanager_container"]

    devices = client.get("/api/devices")
    assert devices.status_code == 200
    assert any(
        device["device_id"] == "catalog-admin-device"
        for device in devices.json["data"]["devices"]
    )

    renamed = client.patch(
        "/api/devices/catalog-admin-device",
        json={"device_name": "Catalog Administrator"},
        headers=headers,
    )
    assert renamed.status_code == 200
    assert renamed.json["data"]["device_name"] == "Catalog Administrator"
    sessions = client.get("/api/devices/catalog-admin-device/sessions")
    assert sessions.status_code == 200
    assert sessions.json["data"]["sessions"]
    activity = client.get("/api/session/activity")
    assert activity.status_code == 200
    assert activity.json["data"]["activity"]["device_id"] == "catalog-admin-device"
    assert activity.json["data"]["activity"]["session_id"]

    role = client.post(
        "/api/roles",
        json={"name": "Temporary Operator", "description": "Lifecycle test role"},
        headers=headers,
    )
    assert role.status_code == 201
    role_id = role.json["data"]["role_id"]
    updated_role = client.patch(
        f"/api/roles/{role_id}",
        json={"version": 1, "description": "Updated lifecycle role"},
        headers=headers,
    )
    assert updated_role.status_code == 200
    permission = client.post(
        "/api/permissions",
        json={"role_id": role_id, "action_category": "world.backup.view"},
        headers=headers,
    )
    assert permission.status_code == 201
    listed = client.get(f"/api/roles/{role_id}/permissions")
    assert listed.status_code == 200
    assert listed.json["data"]["permissions"][0]["action_category"] == "world.backup.view"
    revoked = client.delete(
        f"/api/permissions/{permission.json['data']['permission_id']}",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert client.get(f"/api/roles/{role_id}/permissions").json["data"]["permissions"] == []

    deleted_role = client.delete(f"/api/roles/{role_id}", headers=headers)
    assert deleted_role.status_code == 200
    missing_role = client.get(f"/api/roles/{role_id}/permissions")
    assert missing_role.status_code == 404

    superadmin_role = (
        container.store.reader()
        .execute("SELECT role_id FROM roles WHERE name = 'Superadmin'")
        .fetchone()
    )
    immutable = client.patch(
        f"/api/roles/{superadmin_role['role_id']}",
        json={"version": 1, "description": "must fail"},
        headers=headers,
    )
    assert immutable.status_code == 409
    assert immutable.json["error"]["code"] == "CONFIG_VERSION_CONFLICT"


def test_administration_user_validation_update_and_soft_delete(catalog_app):
    client, headers = _admin_client(catalog_app)
    container = catalog_app.extensions["mcmanager_container"]

    role = client.post(
        "/api/roles",
        json={"name": "User Lifecycle Role"},
        headers=headers,
    )
    assert role.status_code == 201
    role_id = role.json["data"]["role_id"]

    invalid_user = client.post(
        "/api/users",
        json={
            "username": "short-password-user",
            "password": "short",
            "role_id": role_id,
        },
        headers=headers,
    )
    assert invalid_user.status_code == 400
    assert invalid_user.json["error"]["code"] == "VALIDATION_ERROR"

    created = client.post(
        "/api/users",
        json={
            "username": "  lifecycle-user  ",
            "display_name": "Lifecycle User",
            "password": "lifecycle-password",
            "role_id": role_id,
        },
        headers=headers,
    )
    assert created.status_code == 201
    user_id = created.json["data"]["user_id"]
    secret_count_before_duplicate = (
        container.store.reader().execute("SELECT count(*) FROM secrets").fetchone()[0]
    )
    duplicate = client.post(
        "/api/users",
        json={
            "username": "lifecycle-user",
            "password": "another-password",
            "role_id": role_id,
        },
        headers=headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json["error"]["code"] == "USER_CONFLICT"
    secret_count_after_duplicate = (
        container.store.reader().execute("SELECT count(*) FROM secrets").fetchone()[0]
    )
    assert secret_count_after_duplicate == secret_count_before_duplicate

    user_row = (
        container.store.reader()
        .execute("SELECT status, display_name FROM users WHERE user_id = ?", (user_id,))
        .fetchone()
    )
    assert user_row["status"] == "active"
    assert user_row["display_name"] == "Lifecycle User"
    listed_user = next(
        user
        for user in client.get("/api/users").json["data"]["users"]
        if user["user_id"] == user_id
    )
    assert listed_user["roles"] == ["User Lifecycle Role"]
    assert listed_user["last_activity_at"] is None

    current_user_id = client.get("/api/session").json["data"]["user_id"]
    self_password = client.patch(
        f"/api/users/{current_user_id}",
        json={"password": "new-valid-password"},
        headers=headers,
    )
    assert self_password.status_code == 400
    assert self_password.json["error"]["code"] == "VALIDATION_ERROR"

    step_up = client.post(
        "/api/auth/step-up",
        json={"password": "a-strong-password-123"},
        headers=headers,
    )
    assert step_up.status_code == 200
    headers = {"X-CSRF-Token": client.get_cookie("csrf_token").value}

    for field, value in (("username", " "), ("display_name", 7), ("status", "pending")):
        rejected = client.patch(
            f"/api/users/{user_id}",
            json={field: value},
            headers=headers,
        )
        assert rejected.status_code == 400
        assert rejected.json["error"]["code"] == "VALIDATION_ERROR"

    target_session = container.auth.authenticate(
        username="lifecycle-user",
        password="lifecycle-password",
        device_id="lifecycle-user-device",
        device_name="Lifecycle User Device",
        ip="127.0.0.1",
    )
    target_secret_before = (
        container.store.reader()
        .execute("SELECT secret_id FROM users WHERE user_id = ?", (user_id,))
        .fetchone()["secret_id"]
    )
    duplicate_username = client.patch(
        f"/api/users/{user_id}",
        json={"username": "catalog-admin", "password": "conflicting-password-reset"},
        headers=headers,
    )
    assert duplicate_username.status_code == 409
    assert duplicate_username.json["error"]["code"] == "USER_CONFLICT"
    target_secret_after = (
        container.store.reader()
        .execute("SELECT secret_id FROM users WHERE user_id = ?", (user_id,))
        .fetchone()["secret_id"]
    )
    assert target_secret_after == target_secret_before
    target_session_after = (
        container.store.reader()
        .execute(
            "SELECT deleted_at FROM client_sessions WHERE session_id = ?",
            (target_session.session_id_hash,),
        )
        .fetchone()
    )
    assert target_session_after["deleted_at"] is None

    updated = client.patch(
        f"/api/users/{user_id}",
        json={
            "username": " renamed-lifecycle-user ",
            "display_name": "Renamed Lifecycle User",
            "password": "renamed-user-password",
        },
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json["data"]["updated"] == ["display_name", "password", "username"]
    user_session = container.auth.authenticate(
        username="renamed-lifecycle-user",
        password="renamed-user-password",
        device_id="lifecycle-user-device",
        device_name="Lifecycle User Device",
        ip="127.0.0.1",
    )

    disabled = client.patch(
        f"/api/users/{user_id}",
        json={"status": "disabled"},
        headers=headers,
    )
    assert disabled.status_code == 200
    session_row = (
        container.store.reader()
        .execute(
            "SELECT deleted_at FROM client_sessions WHERE session_id = ?",
            (user_session.session_id_hash,),
        )
        .fetchone()
    )
    assert session_row["deleted_at"] is not None

    deleted = client.delete(f"/api/users/{user_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json["data"]["deleted"] is True
    missing_update = client.patch(
        f"/api/users/{user_id}",
        json={"status": "active"},
        headers=headers,
    )
    assert missing_update.status_code == 404
    assert client.delete(f"/api/users/{user_id}", headers=headers).status_code == 404


def test_user_create_rolls_back_secret_after_racing_username_conflict(catalog_app, monkeypatch):
    client, headers = _admin_client(catalog_app)
    container = catalog_app.extensions["mcmanager_container"]
    admin_id = client.get("/api/session").json["data"]["user_id"]
    admin_secret_id = (
        container.store.reader()
        .execute("SELECT secret_id FROM users WHERE user_id = ?", (admin_id,))
        .fetchone()["secret_id"]
    )
    role = client.post(
        "/api/roles",
        json={"name": "Concurrent User Role"},
        headers=headers,
    )
    assert role.status_code == 201

    username = "racing-user"
    user_count_before = (
        container.store.reader()
        .execute("SELECT count(*) FROM users")
        .fetchone()[0]
    )
    secret_count_before = (
        container.store.reader().execute("SELECT count(*) FROM secrets").fetchone()[0]
    )
    original_store = container.secrets.store

    def store_with_competing_user(**kwargs):
        secret_id = original_store(**kwargs)
        if kwargs.get("commit") is False:
            writer = container.store.writer()
            now = int(container.clock.now())
            writer.execute(
                "INSERT INTO users (user_id, username, display_name, secret_id, status, "
                "failed_login_count, locked_until, created_by, deleted_at, deleted_by, "
                "created_at, updated_at) "
                "VALUES (?, ?, NULL, ?, 'active', 0, NULL, ?, NULL, NULL, ?, ?)",
                (
                    f"u_{uuid4().hex[:16]}",
                    username,
                    admin_secret_id,
                    admin_id,
                    now,
                    now,
                ),
            )
        return secret_id

    monkeypatch.setattr(container.secrets, "store", store_with_competing_user)
    response = client.post(
        "/api/users",
        json={
            "username": username,
            "password": "racing-user-password",
            "role_id": role.json["data"]["role_id"],
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json["error"]["code"] == "USER_CONFLICT"
    assert (
        container.store.reader()
        .execute("SELECT count(*) FROM users WHERE username = ?", (username,))
        .fetchone()[0]
        == 0
    )
    assert (
        container.store.reader().execute("SELECT count(*) FROM users").fetchone()[0]
        == user_count_before
    )
    assert (
        container.store.reader().execute("SELECT count(*) FROM secrets").fetchone()[0]
        == secret_count_before
    )
