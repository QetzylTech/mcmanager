"""Authorized integration coverage for Document 10 world management APIs."""

from __future__ import annotations

import io
import json
import shutil
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest
from argon2 import PasswordHasher

import app.bootstrap as bootstrap
from app import create_app
from app.ports.secrets_store import SecretType
from app.services.worlds import WorldsService, _world_mutation_dispatch_lock
from tests.integration._gate3_support import seed_world


@pytest.fixture
def world_api_app(migrations_dir, clock, monkeypatch):
    monkeypatch.setattr(
        bootstrap, "WorldsService", partial(WorldsService, minecraft=object())
    )
    run_id = uuid4().hex
    test_dir = Path(__file__).resolve().parent
    database_path = test_dir / f".world-api-{run_id}.db"
    keyfile_path = test_dir / f".world-api-{run_id}.key"
    app = None
    try:
        app = create_app(
            database_path=database_path,
            keyfile_path=keyfile_path,
            migrations_dir=migrations_dir,
            clock=clock,
        )
        app.extensions["world_api_test_root"] = test_dir / f".world-api-files-{run_id}"
        yield app
    finally:
        if app is not None:
            app.extensions["mcmanager_shutdown"]()
        for path in (
            database_path,
            database_path.with_name(database_path.name + "-wal"),
            database_path.with_name(database_path.name + "-shm"),
            keyfile_path,
        ):
            path.unlink(missing_ok=True)
        shutil.rmtree(test_dir / f".world-api-files-{run_id}", ignore_errors=True)


def _admin_client(app):
    container = app.extensions["mcmanager_container"]
    container.auth.provision_first_superadmin(
        username="world-api-admin",
        password="world-api-password",
        device_id="world-api-device",
        device_name="World API Test Device",
        ip="127.0.0.1",
    )
    session = container.auth.authenticate(
        username="world-api-admin",
        password="world-api-password",
        device_id="world-api-device",
        device_name="World API Test Device",
        ip="127.0.0.1",
    )
    client = app.test_client()
    client.set_cookie("mcmanager_session", session.token)
    client.get("/api/session")
    return client, client.get_cookie("csrf_token").value


def _elevate(app, client):
    container = app.extensions["mcmanager_container"]
    session = container.auth.validate_session(
        client.get_cookie("mcmanager_session").value, ip="127.0.0.1"
    )
    connection = container.store.writer()
    connection.execute(
        "UPDATE client_sessions SET step_up_confirmed_at = ? WHERE session_id = ?",
        (int(container.clock.now()), session.session_id_hash),
    )
    connection.commit()


def _add_regular_user(container):
    user_id = "world-api-user"
    now = int(container.clock.now())
    secret_id = container.secrets.store(
        secret_type=SecretType.USER_PASSWORD,
        associated_entity_type="user",
        associated_entity_id=user_id,
        plaintext=PasswordHasher().hash("world-api-user-password"),
    )
    container.store.writer().execute(
        """
        INSERT INTO users (
            user_id, username, display_name, secret_id, status, failed_login_count,
            locked_until, created_by, deleted_at, deleted_by, created_at, updated_at
        ) VALUES (?, ?, NULL, ?, 'active', 0, NULL, NULL, NULL, NULL, ?, ?)
        """,
        (user_id, "world-api-user", secret_id, now, now),
    )
    container.store.writer().commit()
    return container.auth.issue_session(
        user_id=user_id,
        device_id="world-api-user-device",
        device_name="World API User Device",
        ip="127.0.0.1",
    )


def test_world_routes_require_auth_and_admin_role(world_api_app):
    anonymous = world_api_app.test_client().get("/api/worlds/world/files")
    assert anonymous.status_code == 401
    assert anonymous.get_json()["error"]["code"] == "AUTH_SESSION_INVALID"

    container = world_api_app.extensions["mcmanager_container"]
    user_session = _add_regular_user(container)
    user_client = world_api_app.test_client()
    user_client.set_cookie("mcmanager_session", user_session.token)
    user_client.get("/api/session")
    forbidden = user_client.get("/api/worlds/world/files")
    assert forbidden.status_code == 403
    assert forbidden.get_json()["error"]["code"] == "AUTH_FORBIDDEN"


def test_authorized_world_crud_runtime_eula_files_and_logs(world_api_app):
    container = world_api_app.extensions["mcmanager_container"]
    client, csrf = _admin_client(world_api_app)
    headers = {"X-CSRF-Token": csrf}

    seed_world(container.store, world_id="world-api")
    root = world_api_app.extensions["world_api_test_root"]
    root.mkdir()
    log_root = root / "logs"
    log_root.mkdir()
    world_dir = root / "world"
    world_dir.mkdir()
    connection = container.store.writer()
    connection.execute(
        """
        UPDATE world_instances
        SET addressing_strategy = 'path', addressing_value = ?, state = 'eula_required'
        WHERE world_id = 'world-api'
        """,
        (str(world_dir),),
    )
    connection.execute(
        """
        INSERT INTO world_settings (
            world_id, log_root_override, version, updated_at, updated_by
        ) VALUES ('world-api', ?, 1, ?, 'gate3_admin')
        """,
        (str(log_root), int(container.clock.now())),
    )
    connection.execute(
        """
        INSERT INTO global_settings (
            settings_id, timezone, idle_countdown_seconds, notification_defaults,
            minecraft_root_path, backup_root_path, log_root_path,
            offsite_sync_defaults, version, updated_at, updated_by
        ) VALUES ('world-api-global', 'UTC', NULL, NULL, ?, ?, ?, NULL, 1, ?, 'gate3_admin')
        """,
        (str(root / "worlds"), str(root / "backups"), str(log_root), int(container.clock.now())),
    )
    connection.commit()

    eula = client.get("/api/worlds/world-api/eula")
    assert eula.status_code == 200
    assert eula.get_json()["data"]["eula"] == "not_present"
    step_up_required = client.post(
        "/api/worlds/world-api/eula/accept",
        json={"accepted": True},
        headers=headers,
    )
    assert step_up_required.status_code == 403
    assert step_up_required.get_json()["error"]["code"] == "STEP_UP_REQUIRED"
    _elevate(world_api_app, client)
    accepted = client.post(
        "/api/worlds/world-api/eula/accept",
        json={"accepted": True},
        headers=headers,
    )
    assert accepted.status_code == 200
    accepted_payload = accepted.get_json()
    assert accepted_payload["data"]["operation"]["op_type"] == "ConfigEdit"
    assert accepted_payload["data"]["operation"]["status"] == "Completed"
    assert accepted_payload["data"]["operation"]["op_id"] == accepted_payload["meta"]["op_id"]
    assert (world_dir / "eula.txt").read_text(encoding="utf-8").endswith("eula=true\n")

    with _world_mutation_dispatch_lock:
        created = client.post(
            "/api/worlds",
            json={
                "template_id": "gate3_template",
                "display_name": "Created via API",
                "port": 25567,
                "addressing_strategy": "port",
                "addressing_value": "25567",
                "java_runtime_id": "gate3_java",
            },
            headers={**headers, "Idempotency-Key": "create-world-key"},
        )
        assert created.status_code == 202
        assert created.get_json()["data"]["operation"]["status"] == "Queued"
        assert created.get_json()["meta"]["op_id"]
        create_op_id = created.get_json()["data"]["operation"]["op_id"]
        created_world_id = created.get_json()["data"]["operation"]["data"]["world"]["world_id"]
        assert client.get(f"/api/worlds/{created_world_id}").status_code == 404
        create_replay = client.post(
            "/api/worlds",
            json={
                "template_id": "gate3_template",
                "display_name": "Created via API",
                "port": 25567,
                "addressing_strategy": "port",
                "addressing_value": "25567",
                "java_runtime_id": "gate3_java",
            },
            headers={**headers, "Idempotency-Key": "create-world-key"},
        )
        assert create_replay.status_code == 200
        assert create_replay.get_json()["data"]["operation"]["op_id"] == create_op_id
    container.worlds.dispatch_queued_operations()
    detail = client.get(f"/api/worlds/{created_world_id}")
    assert detail.status_code == 200
    assert "capabilities" in detail.get_json()["data"]
    assert detail.get_json()["data"]["last_backup"] is None

    renamed = client.patch(
        f"/api/worlds/{created_world_id}",
        json={"display_name": "Renamed via API", "version": 1},
        headers=headers,
    )
    assert renamed.status_code == 200
    assert renamed.get_json()["data"]["world"]["display_name"] == "Renamed via API"

    runtime = client.get(f"/api/worlds/{created_world_id}/runtime-config")
    assert runtime.status_code == 200
    stale_runtime = client.patch(
        f"/api/worlds/{created_world_id}/runtime-config",
        json={"port": 25568, "version": 1},
        headers={**headers, "Idempotency-Key": "stale-runtime-config-key"},
    )
    assert stale_runtime.status_code == 409
    assert stale_runtime.get_json()["error"]["code"] == "CONFIG_VERSION_CONFLICT"
    with _world_mutation_dispatch_lock:
        updated_runtime = client.patch(
            f"/api/worlds/{created_world_id}/runtime-config",
            json={"port": 25568, "version": 2},
            headers={**headers, "Idempotency-Key": "runtime-config-key"},
        )
        assert updated_runtime.status_code == 202
        assert updated_runtime.get_json()["data"]["operation"]["status"] == "Queued"
        assert updated_runtime.get_json()["meta"]["op_id"]
        runtime_op_id = updated_runtime.get_json()["data"]["operation"]["op_id"]
        runtime_replay = client.patch(
            f"/api/worlds/{created_world_id}/runtime-config",
            json={"port": 25568, "version": 2},
            headers={**headers, "Idempotency-Key": "runtime-config-key"},
        )
        assert runtime_replay.status_code == 200
        assert runtime_replay.get_json()["data"]["operation"]["op_id"] == runtime_op_id
        claimed_runtime = container.operations.claim_queued(runtime_op_id)
        assert claimed_runtime is not None
        runtime_payload = json.loads(claimed_runtime["data_json"])
        container.worlds._apply_queued_runtime_config(claimed_runtime, runtime_payload)
    container.worlds.dispatch_queued_operations()
    runtime_operation = container.operations.get(runtime_op_id)
    assert runtime_operation["status"] == "Completed"
    assert client.get(f"/api/worlds/{created_world_id}/runtime-config").get_json()[
        "data"
    ]["runtime_config"]["port"] == 25568

    made_directory = client.post(
        "/api/worlds/world-api/files/mkdir",
        json={"path": "", "name": "config"},
        headers=headers,
    )
    assert made_directory.status_code == 201
    uploaded = client.post(
        "/api/worlds/world-api/files",
        data={"path": "config/server.properties", "file": (io.BytesIO(b"motd=test\n"), "upload.txt")},
        headers=headers,
    )
    assert uploaded.status_code == 201
    listing = client.get("/api/worlds/world-api/files?path=config")
    assert listing.status_code == 200
    assert listing.get_json()["data"]["files"][0]["name"] == "server.properties"
    download = client.get(
        "/api/worlds/world-api/files/download?path=config/server.properties"
    )
    assert download.status_code == 200
    assert download.data == b"motd=test\n"
    download.close()
    with _world_mutation_dispatch_lock:
        moved = client.patch(
            "/api/worlds/world-api/files",
            json={
                "action": "rename",
                "from": "config/server.properties",
                "to": "config/server.properties.bak",
            },
            headers={**headers, "Idempotency-Key": "file-edit-key"},
        )
        assert moved.status_code == 202, moved.get_json()
        assert moved.get_json()["data"]["operation"]["op_type"] == "ConfigEdit"
        assert moved.get_json()["data"]["operation"]["status"] == "Queued"
        assert moved.get_json()["meta"]["op_id"]
        file_edit_op_id = moved.get_json()["data"]["operation"]["op_id"]
        assert (world_dir / "config" / "server.properties").exists()
        replay = client.patch(
            "/api/worlds/world-api/files",
            json={
                "action": "rename",
                "from": "config/server.properties",
                "to": "config/server.properties.bak",
            },
            headers={**headers, "Idempotency-Key": "file-edit-key"},
        )
        assert replay.status_code == 200
        assert replay.get_json()["data"]["operation"]["op_id"] == file_edit_op_id
    dispatched = container.worlds.dispatch_queued_operations()
    assert file_edit_op_id in dispatched
    assert container.operations.get(file_edit_op_id)["status"] == "Completed"
    assert (world_dir / "config" / "server.properties.bak").exists()
    assert client.get("/api/worlds/world-api/files?path=../../").status_code == 403

    logs_dir = log_root / "world-api"
    logs_dir.mkdir()
    (logs_dir / "session.log").write_text("server started\n", encoding="utf-8")
    channels = client.get("/api/worlds/world-api/logs")
    assert channels.status_code == 200
    files = client.get("/api/worlds/world-api/logs/minecraft")
    assert files.status_code == 200
    assert files.get_json()["data"]["files"][0]["name"] == "session.log"
    tail = client.get("/api/worlds/world-api/logs/minecraft/tail?offset=0")
    assert tail.status_code == 200
    assert tail.get_json()["data"]["lines"] == ["server started"]
    log_download = client.get("/api/worlds/world-api/logs/minecraft/session.log")
    assert log_download.status_code == 200
    assert log_download.data.replace(b"\r\n", b"\n") == b"server started\n"
    log_download.close()

    container.store.writer().execute(
        "UPDATE client_sessions SET step_up_confirmed_at = ? WHERE session_id = ?",
        (
            int(container.clock.now()) - 601,
            container.auth.validate_session(
                client.get_cookie("mcmanager_session").value, ip="127.0.0.1"
            ).session_id_hash,
        ),
    )
    container.store.writer().commit()
    step_up_delete = client.delete(
        "/api/worlds/world-api/files",
        json={"path": "config/server.properties.bak"},
        headers=headers,
    )
    assert step_up_delete.status_code == 403
    _elevate(world_api_app, client)
    deleted_file = client.delete(
        "/api/worlds/world-api/files",
        json={"path": "config/server.properties.bak"},
        headers=headers,
    )
    assert deleted_file.status_code == 200

    preview = client.post(
        "/api/worlds/world-api/delete-preview", headers=headers
    )
    assert preview.status_code == 200
    container.store.writer().execute(
        "UPDATE client_sessions SET step_up_confirmed_at = ? WHERE session_id = ?",
        (
            int(container.clock.now()) - 601,
            container.auth.validate_session(
                client.get_cookie("mcmanager_session").value, ip="127.0.0.1"
            ).session_id_hash,
        ),
    )
    container.store.writer().commit()
    step_up_world_delete = client.delete(
        "/api/worlds/world-api",
        json={"preview_token": preview.get_json()["data"]["preview_token"]},
        headers=headers,
    )
    assert step_up_world_delete.status_code == 403
    _elevate(world_api_app, client)
    with _world_mutation_dispatch_lock:
        deleted_world = client.delete(
            "/api/worlds/world-api",
            json={"preview_token": preview.get_json()["data"]["preview_token"]},
            headers={**headers, "Idempotency-Key": "delete-world-key"},
        )
        assert deleted_world.status_code == 202
        assert deleted_world.get_json()["data"]["operation"]["status"] == "Queued"
        assert deleted_world.get_json()["meta"]["op_id"]
        delete_op_id = deleted_world.get_json()["data"]["operation"]["op_id"]
        delete_replay = client.delete(
            "/api/worlds/world-api",
            json={"preview_token": preview.get_json()["data"]["preview_token"]},
            headers={**headers, "Idempotency-Key": "delete-world-key"},
        )
        assert delete_replay.status_code == 200
        assert delete_replay.get_json()["data"]["operation"]["op_id"] == delete_op_id
        assert container.store.reader().execute(
            "SELECT deleted_at FROM world_instances WHERE world_id = 'world-api'"
        ).fetchone()["deleted_at"] is None
    container.worlds.dispatch_queued_operations()
    row = container.store.reader().execute(
        "SELECT deleted_at FROM world_instances WHERE world_id = 'world-api'"
    ).fetchone()
    assert row["deleted_at"] is not None
    assert container.operations.get(delete_op_id)["status"] == "Completed"
