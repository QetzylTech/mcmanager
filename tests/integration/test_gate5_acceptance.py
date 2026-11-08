"""Gate 5 acceptance contracts from WBS 5.1–5.3 and Documents 4, 5, 10–12."""

from __future__ import annotations

import json
import re
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest
from argon2 import PasswordHasher

import app.bootstrap as bootstrap
from app import create_app
from app.domain.value_objects import ActorType, OperationType
from app.ports.secrets_store import SecretType
from app.services.operations import OperationInput
from app.services.worlds import WorldsService
from tests.integration._gate3_support import seed_world


@pytest.fixture
def gate5_app(migrations_dir, clock, monkeypatch):
    # The current composition root omits its newly-required Minecraft port.
    # These web acceptance cases do not exercise launch validation.
    monkeypatch.setattr(bootstrap, "WorldsService", partial(WorldsService, minecraft=object()))
    run_id = uuid4().hex
    test_files = Path(__file__).resolve().parents[1]
    database_path = test_files / f".gate5-{run_id}.db"
    keyfile_path = test_files / f".gate5-{run_id}.key"
    app = None
    try:
        app = create_app(
            database_path=database_path,
            keyfile_path=keyfile_path,
            migrations_dir=migrations_dir,
            clock=clock,
            trusted_proxy_hops=1,
        )
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


def _json_error(response, code: str) -> None:
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    assert payload["error"]["code"] == code


def _login(container):
    container.auth.provision_first_superadmin(
        username="gate5-admin",
        password="gate5-password",
        device_id="gate5-device",
        device_name="Gate 5 Test Device",
        ip="127.0.0.1",
    )
    return container.auth.authenticate(
        username="gate5-admin",
        password="gate5-password",
        device_id="gate5-device",
        device_name="Gate 5 Test Device",
        ip="127.0.0.1",
    )


def test_session_and_stream_routes_reject_anonymous_requests(gate5_app):
    client = gate5_app.test_client()

    session_response = client.get("/api/session")
    stream_response = client.get("/stream/events")

    assert session_response.status_code == 401
    _json_error(session_response, "AUTH_SESSION_INVALID")
    assert stream_response.status_code == 401


def test_first_run_setup_status_is_public_and_read_only(gate5_app):
    response = gate5_app.test_client().get("/api/setup")

    assert response.status_code == 200
    assert response.json["data"] == {
        "setup_completed": False,
        "first_superadmin_required": True,
    }


@pytest.mark.parametrize(
    ("cookie_token", "header_token"),
    [(None, None), ("cookie-token", "different-token")],
)
def test_state_changes_require_matching_csrf_cookie_and_header(
    gate5_app, cookie_token, header_token
):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", session.token)
    client.get("/api/session")
    if cookie_token is None:
        client.set_cookie("csrf_token", "")
    elif cookie_token is not None:
        client.set_cookie("csrf_token", cookie_token)
    headers = {"X-CSRF-Token": header_token} if header_token is not None else {}

    response = client.post("/api/worlds/missing-world/start", headers=headers)

    assert response.status_code == 403
    _json_error(response, "CSRF_INVALID")


def test_csrf_tokens_are_issued_and_bound_to_the_authenticated_session(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    container.auth.provision_first_superadmin(
        username="gate5-admin",
        password="gate5-password",
        device_id="gate5-device",
        device_name="Gate 5 Test Device",
        ip="127.0.0.1",
    )

    first_client = gate5_app.test_client()
    first_client.get("/")
    prelogin_csrf_token = first_client.get_cookie("csrf_token").value
    login_response = first_client.post(
        "/api/auth/login",
        json={
            "username": "gate5-admin",
            "password": "gate5-password",
            "device_id": "gate5-device",
            "device_name": "Gate 5 Test Device",
        },
        headers={"X-CSRF-Token": prelogin_csrf_token},
    )
    assert login_response.status_code == 201
    first_session_token = first_client.get_cookie("mcmanager_session").value
    issued_csrf_token = first_client.get_cookie("csrf_token").value

    second_session = container.auth.authenticate(
        username="gate5-admin",
        password="gate5-password",
        device_id="gate5-device",
        device_name="Gate 5 Test Device",
        ip="127.0.0.1",
    )

    first_client.set_cookie("csrf_token", "arbitrary-equal-token")
    arbitrary_token_response = first_client.post(
        "/api/worlds/missing-world/start",
        headers={"X-CSRF-Token": "arbitrary-equal-token"},
    )

    second_client = gate5_app.test_client()
    second_client.set_cookie("mcmanager_session", second_session.token)
    second_client.set_cookie("csrf_token", issued_csrf_token)
    cross_session_token_response = second_client.post(
        "/api/worlds/missing-world/start",
        headers={"X-CSRF-Token": issued_csrf_token},
    )

    assert [
        arbitrary_token_response.status_code,
        cross_session_token_response.status_code,
    ] == [403, 403]
    _json_error(arbitrary_token_response, "CSRF_INVALID")
    _json_error(cross_session_token_response, "CSRF_INVALID")

    first_client.set_cookie("csrf_token", issued_csrf_token)
    step_up_response = first_client.post(
        "/api/auth/step-up",
        json={"password": "gate5-password", "device_id": "gate5-device"},
        headers={"X-CSRF-Token": issued_csrf_token},
    )
    assert step_up_response.status_code == 200
    assert first_client.get_cookie("mcmanager_session").value != first_session_token
    assert first_client.get_cookie("csrf_token").value != issued_csrf_token


def test_login_requires_matching_pre_authentication_csrf_tokens(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    container.auth.provision_first_superadmin(
        username="gate5-admin",
        password="gate5-password",
        device_id="gate5-device",
        device_name="Gate 5 Test Device",
        ip="127.0.0.1",
    )
    client = gate5_app.test_client()
    credentials = {
        "username": "gate5-admin",
        "password": "gate5-password",
        "device_id": "gate5-device",
        "device_name": "Gate 5 Test Device",
    }

    missing_response = client.post("/api/auth/login", json=credentials)
    assert missing_response.status_code == 403
    _json_error(missing_response, "CSRF_INVALID")

    client.get("/")
    csrf_token = client.get_cookie("csrf_token").value
    mismatched_response = client.post(
        "/api/auth/login",
        json=credentials,
        headers={"X-CSRF-Token": "not-the-cookie-token"},
    )
    assert mismatched_response.status_code == 403
    _json_error(mismatched_response, "CSRF_INVALID")

    accepted_response = client.post(
        "/api/auth/login",
        json=credentials,
        headers={"X-CSRF-Token": csrf_token},
    )
    assert accepted_response.status_code == 201


def test_mutating_routes_require_valid_session_csrf_and_role(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    admin_session = _login(container)
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", admin_session.token)
    client.get("/api/session")
    csrf_token = client.get_cookie("csrf_token").value

    anonymous_missing_csrf = gate5_app.test_client()
    anonymous_missing_csrf_response = anonymous_missing_csrf.post(
        "/api/worlds/missing-world/start",
        headers={"X-CSRF-Token": "missing-session-token"},
    )
    assert anonymous_missing_csrf_response.status_code == 401
    _json_error(anonymous_missing_csrf_response, "AUTH_SESSION_INVALID")

    invalid_csrf_response = client.post(
        "/api/worlds/missing-world/start",
        headers={"X-CSRF-Token": "not-the-session-token"},
    )
    assert invalid_csrf_response.status_code == 403
    _json_error(invalid_csrf_response, "CSRF_INVALID")

    container.store.writer().execute(
        "UPDATE client_sessions SET expires_at = ? WHERE session_id = ?",
        (int(container.clock.now()) - 1, admin_session.session_id_hash),
    )
    container.store.writer().commit()
    expired_response = client.post(
        "/api/worlds/missing-world/start",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert expired_response.status_code == 401
    _json_error(expired_response, "AUTH_SESSION_INVALID")

    user_id = "gate5-user"
    user_secret = container.secrets.store(
        secret_type=SecretType.USER_PASSWORD,
        associated_entity_type="user",
        associated_entity_id=user_id,
        plaintext=PasswordHasher().hash("gate5-user-password"),
    )
    now = int(container.clock.now())
    container.store.writer().execute(
        "INSERT INTO users ("
        "  user_id, username, display_name, secret_id, status, failed_login_count, "
        "  locked_until, created_by, deleted_at, deleted_by, created_at, updated_at"
        ") VALUES (?, ?, NULL, ?, ?, 0, NULL, NULL, NULL, NULL, ?, ?)",
        (user_id, "gate5-user", user_secret, "active", now, now),
    )
    container.store.writer().commit()
    user_session = container.auth.issue_session(
        user_id=user_id,
        device_id="gate5-user-device",
        device_name="Gate5 User Device",
        ip="127.0.0.1",
    )
    user_client = gate5_app.test_client()
    user_client.set_cookie("mcmanager_session", user_session.token)
    user_client.get("/api/session")
    user_csrf = user_client.get_cookie("csrf_token").value

    forbidden_response = user_client.post(
        "/api/worlds/missing-world/kill",
        headers={"X-CSRF-Token": user_csrf},
    )
    assert forbidden_response.status_code == 403
    _json_error(forbidden_response, "AUTH_FORBIDDEN")

    forbidden_settings_response = user_client.get("/api/worlds/missing-world/settings")
    assert forbidden_settings_response.status_code == 403
    _json_error(forbidden_settings_response, "AUTH_FORBIDDEN")


def test_privileged_world_action_requires_unexpired_step_up(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", session.token)
    client.get("/api/session")
    csrf_token = client.get_cookie("csrf_token").value

    response = client.post(
        "/api/worlds/missing-world/kill",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 403
    _json_error(response, "STEP_UP_REQUIRED")

    step_up_response = client.post(
        "/api/auth/step-up",
        json={"password": "gate5-password", "device_id": "gate5-device"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert step_up_response.status_code == 200
    csrf_token = client.get_cookie("csrf_token").value

    allowed_response = client.post(
        "/api/worlds/missing-world/kill",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert allowed_response.status_code == 404
    _json_error(allowed_response, "NOT_FOUND")

    elevated_session = container.auth.validate_session(
        client.get_cookie("mcmanager_session").value,
        ip="127.0.0.1",
    )
    container.store.writer().execute(
        "UPDATE client_sessions SET step_up_confirmed_at = ? WHERE session_id = ?",
        (int(container.clock.now()) - 601, elevated_session.session_id_hash),
    )
    container.store.writer().commit()
    expired_response = client.post(
        "/api/worlds/missing-world/kill",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert expired_response.status_code == 403
    _json_error(expired_response, "STEP_UP_REQUIRED")


@pytest.mark.parametrize("path", ["/", "/api/health", "/api/route-that-does-not-exist"])
def test_security_headers_cover_html_and_api_responses(gate5_app, path):
    response = gate5_app.test_client().get(path)

    csp = response.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    if path.startswith("/api/"):
        assert "no-store" in response.headers.get("Cache-Control", "")


def test_non_loopback_http_is_rejected_and_https_csrf_cookie_is_secure(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    container.auth.provision_first_superadmin(
        username="secure-admin",
        password="secure-admin-password",
        device_id="secure-device",
        device_name="Secure Device",
        ip="192.0.2.10",
    )
    client = gate5_app.test_client()
    insecure = client.get(
        "/api/health",
        environ_overrides={"REMOTE_ADDR": "192.0.2.10"},
    )
    assert insecure.status_code == 403
    _json_error(insecure, "HTTPS_REQUIRED")
    assert not any(
        cookie.startswith("csrf_token=") for cookie in insecure.headers.getlist("Set-Cookie")
    )

    secure = client.get(
        "/",
        base_url="https://manager.example.test",
        environ_overrides={"REMOTE_ADDR": "192.0.2.10"},
    )
    csrf_token = client.get_cookie("csrf_token", domain="manager.example.test").value
    login = client.post(
        "/api/auth/login",
        base_url="https://manager.example.test",
        json={
            "username": "secure-admin",
            "password": "secure-admin-password",
            "device_id": "secure-device",
            "device_name": "Secure Device",
        },
        headers={"X-CSRF-Token": csrf_token},
        environ_overrides={"REMOTE_ADDR": "192.0.2.10"},
    )
    assert secure.status_code == 200
    assert login.status_code == 201
    cookies = login.headers.getlist("Set-Cookie")
    assert all("; Secure" in cookie for cookie in cookies)


def test_trusted_proxy_https_headers_produce_secure_csrf_cookie(gate5_app):
    response = gate5_app.test_client().get(
        "/",
        headers={
            "X-Forwarded-For": "192.0.2.10",
            "X-Forwarded-Proto": "https",
        },
    )

    assert response.status_code == 200
    assert any(
        cookie.startswith("csrf_token=") and "; Secure" in cookie
        for cookie in response.headers.getlist("Set-Cookie")
    )


def test_metrics_stream_starts_with_nonblank_snapshot(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", session.token)

    response = client.get("/stream/metrics", buffered=False)
    try:
        frame = next(response.response).decode("utf-8")
        assert "event: metrics" in frame
        data_line = frame.split("data: ", maxsplit=1)[1].splitlines()[0]
        data = json.loads(data_line)
        assert data["metrics"] is not None
        assert "cpu_pct" in data["metrics"]
        assert "ram_mb" in data["metrics"]
        assert "storage_pct" in data["metrics"]
    finally:
        response.close()


def test_login_route_returns_lockout_after_five_failures(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    container.auth.provision_first_superadmin(
        username="locked-admin",
        password="locked-admin-password",
        device_id="locked-device",
        device_name="Locked Device",
        ip="127.0.0.1",
    )
    client = gate5_app.test_client()
    client.get("/")
    csrf_token = client.get_cookie("csrf_token").value
    headers = {"X-CSRF-Token": csrf_token}
    for _ in range(5):
        failed = client.post(
            "/api/auth/login",
            json={"username": "locked-admin", "password": "wrong-password"},
            headers=headers,
        )
        assert failed.status_code == 401
        _json_error(failed, "AUTH_INVALID_CREDENTIALS")

    locked = client.post(
        "/api/auth/login",
        json={"username": "locked-admin", "password": "locked-admin-password"},
        headers=headers,
    )
    assert locked.status_code == 429
    _json_error(locked, "AUTH_LOCKED")


def test_start_returns_202_operation_envelope(gate5_app, monkeypatch):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", session.token)
    client.get("/api/session")
    csrf_token = client.get_cookie("csrf_token").value
    def enqueue_start(**kwargs):
        return (
            {
                "op_id": "op_gate5_start",
                "status": "Queued",
                "idempotency_key": kwargs["idempotency_key"],
            },
            False,
        )

    monkeypatch.setattr(container.worlds, "enqueue_start", enqueue_start)

    response = client.post(
        "/api/worlds/world_gate5/start",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["data"]["operation"]["op_id"] == "op_gate5_start"
    assert payload["data"]["operation"]["status"] in {"Created", "Queued"}
    assert payload["meta"]["op_id"] == "op_gate5_start"
    assert payload["meta"]["idempotency_key"]


def test_world_action_is_durably_queued_and_idempotent(gate5_app, monkeypatch):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    world_id = seed_world(container.store, world_id="world_gate5_async_stop")
    container.store.writer().execute(
        "UPDATE world_instances SET state = 'running' WHERE world_id = ?",
        (world_id,),
    )
    container.store.writer().commit()
    dispatch = container.worlds.dispatch_queued_operations
    monkeypatch.setattr(container.worlds, "dispatch_queued_operations", lambda: [])
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", session.token)
    client.get("/api/session")
    csrf_token = client.get_cookie("csrf_token").value
    step_up = client.post(
        "/api/auth/step-up",
        json={"password": "gate5-password", "device_id": "gate5-device"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert step_up.status_code == 200
    headers = {
        "X-CSRF-Token": client.get_cookie("csrf_token").value,
        "Idempotency-Key": "gate5-stop-once",
    }

    first = client.post(f"/api/worlds/{world_id}/stop", headers=headers)
    second = client.post(f"/api/worlds/{world_id}/stop", headers=headers)

    assert first.status_code == 202
    assert second.status_code == 200
    first_payload = first.get_json()
    second_payload = second.get_json()
    operation_id = first_payload["data"]["operation"]["op_id"]
    assert first_payload["meta"]["idempotency_key"] == "gate5-stop-once"
    assert second_payload["meta"]["op_id"] == operation_id
    assert container.operations.get(operation_id)["status"] == "Queued"
    assert container.store.reader().execute(
        "SELECT COUNT(*) FROM operations "
        "WHERE op_type = 'Stop' AND idempotency_key = ?",
        ("gate5-stop-once",),
    ).fetchone()[0] == 1

    assert dispatch() == [operation_id]
    assert container.operations.get(operation_id)["status"] == "Completed"


def test_dispatcher_resumes_durable_queue_after_container_rebuild(
    tmp_path, migrations_dir, clock
):
    database_path = tmp_path / "queued-operation.db"
    keyfile_path = tmp_path / "queued-operation.key"
    first = bootstrap.build_container(
        database_path=database_path,
        keyfile_path=keyfile_path,
        migrations_dir=migrations_dir,
        clock=clock,
    )
    try:
        world_id = seed_world(first.store, world_id="world_restart_queue")
        first.store.writer().execute(
            "UPDATE world_instances SET state = 'running' WHERE world_id = ?",
            (world_id,),
        )
        first.store.writer().commit()
        operation, replayed = first.worlds.enqueue_stop(
            world_id=world_id,
            actor_type=ActorType.SYSTEM,
            actor_user_id=None,
            idempotency_key="restart-safe-stop",
        )
        assert replayed is False
        operation_id = operation["op_id"]
    finally:
        first.store.close()

    recovered = bootstrap.build_container(
        database_path=database_path,
        keyfile_path=keyfile_path,
        migrations_dir=migrations_dir,
        clock=clock,
    )
    try:
        assert recovered.operations.get(operation_id)["status"] == "Queued"
        assert recovered.worlds.dispatch_queued_operations() == [operation_id]
        assert recovered.operations.get(operation_id)["status"] == "Completed"
    finally:
        recovered.store.close()


def test_operation_read_returns_the_persisted_operation(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    operation = container.operations.create(
        OperationInput(
            op_type=OperationType.BACKUP,
            actor_type=ActorType.SYSTEM,
        )
    )
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", session.token)

    response = client.get(f"/api/operations/{operation['op_id']}")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    result = payload["data"].get("operation", payload["data"])
    assert result["op_id"] == operation["op_id"]
    assert result["status"] == operation["status"]


def test_canonical_world_list_filters_and_paginates_authenticated_results(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    seed_world(container.store, world_id="world_list_vanilla")
    now = int(container.clock.now())
    container.store.writer().executemany(
        "INSERT INTO world_instances ("
        "world_id, display_name, template_id, server_type, mc_version, java_runtime_id, "
        "port, addressing_strategy, addressing_value, state, pre_backup_state, launch_args, "
        "metadata_version, deleted_at, deleted_by, created_at, updated_at"
        ") VALUES (?, ?, 'gate3_template', ?, ?, 'gate3_java', ?, 'port', ?, ?, NULL, '{}', "
        "1, ?, ?, ?, ?)",
        [
            (
                "world_list_paper",
                "Creative",
                "paper",
                "1.20.4",
                25566,
                "25566",
                "running",
                None,
                None,
                now + 1,
                now + 1,
            ),
            (
                "world_list_deleted",
                "Archived",
                "vanilla",
                "1.21",
                25567,
                "25567",
                "off",
                now + 2,
                "gate3_admin",
                now + 2,
                now + 2,
            ),
        ],
    )
    container.store.writer().commit()

    anonymous_response = gate5_app.test_client().get("/api/worlds")
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", session.token)
    filtered_response = client.get(
        "/api/worlds?state=off&server_type=vanilla&mc_version=1.21&search=Gate"
        "&limit=1&offset=0"
    )
    paged_response = client.get("/api/worlds?limit=1&offset=1")
    deleted_response = client.get("/api/worlds")
    include_deleted_response = client.get("/api/worlds?include_deleted=true")

    assert anonymous_response.status_code == 401
    assert filtered_response.status_code == 200
    filtered = filtered_response.get_json()
    assert [world["world_id"] for world in filtered["data"]["worlds"]] == [
        "world_list_vanilla"
    ]
    assert filtered["meta"]["pagination"] == {"limit": 1, "offset": 0, "total": 1}
    paged = paged_response.get_json()
    assert paged["meta"]["pagination"] == {"limit": 1, "offset": 1, "total": 2}
    assert "world_list_deleted" not in {
        world["world_id"] for world in deleted_response.get_json()["data"]["worlds"]
    }
    assert "world_list_deleted" in {
        world["world_id"]
        for world in include_deleted_response.get_json()["data"]["worlds"]
    }


def test_world_management_page_uses_canonical_world_list_api():
    root = Path(__file__).resolve().parents[2]
    source = (root / "app" / "shell" / "static" / "shell.js").read_text(
        encoding="utf-8"
    )

    assert "fetch(`/api/worlds?" in source
    assert "data-world-list" in source


def _sse_chunk(iterator) -> str:
    chunk = next(iterator)
    return chunk.decode() if isinstance(chunk, bytes) else chunk


def test_manager_sse_stays_open_and_fans_out_hub_events(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    world_id = seed_world(container.store, world_id="world_sse_snapshot")
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", session.token)
    response = client.get("/stream/events", buffered=False)
    iterator = iter(response.response)
    try:
        assert container.realtime.subscriber_count("events") == 1
        snapshot = _sse_chunk(iterator)
        assert "event: snapshot" in snapshot
        snapshot_payload = json.loads(
            next(line[6:] for line in snapshot.splitlines() if line.startswith("data: "))
        )
        assert snapshot_payload["manager"]["worlds"][0]["world_id"] == world_id
        assert "operations" in snapshot_payload["manager"]
        assert "backups" in snapshot_payload["manager"]
        assert "schedules" in snapshot_payload["manager"]
        assert "notifications" in snapshot_payload["manager"]

        container.realtime.publish("events", "world.state", {"world_id": "world_gate5"})
        live_event = _sse_chunk(iterator)

        assert "event: world.state" in live_event
        assert '"world_id":"world_gate5"' in live_event
    finally:
        response.close()
    assert container.realtime.subscriber_count("events") == 0


def test_sse_session_expiry_emits_terminal_error_and_cleans_subscriber(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", session.token)
    response = client.get("/stream/events", buffered=False)
    iterator = iter(response.response)
    try:
        assert "event: snapshot" in _sse_chunk(iterator)
        container.store.writer().execute(
            "UPDATE client_sessions SET expires_at = ? WHERE session_id = ?",
            (int(container.clock.now()) - 1, session.session_id_hash),
        )
        container.store.writer().commit()

        terminal = _sse_chunk(iterator)

        assert "event: stream.error" in terminal
        assert '"code":"AUTH_SESSION_EXPIRED"' in terminal
    finally:
        response.close()
    assert container.realtime.subscriber_count("events") == 0


def test_sse_response_close_before_iteration_unsubscribes(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", session.token)

    response = client.get("/stream/events", buffered=False)

    assert container.realtime.subscriber_count("events") == 1
    response.close()
    assert container.realtime.subscriber_count("events") == 0


def test_all_documented_sse_topics_pass_through_the_hub(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", session.token)
    response = client.get("/stream/events", buffered=False)
    iterator = iter(response.response)
    topics = (
        "world.state",
        "world.metrics",
        "operation.created",
        "operation.progress",
        "operation.terminal",
        "notification",
        "system.stats",
        "backup.progress",
        "restore.progress",
        "sync.status",
        "log.line",
        "alert",
        "queue.position",
        "missed_run",
    )
    try:
        _sse_chunk(iterator)
        for topic in topics:
            container.realtime.publish("events", topic, {"topic": topic})
        received = [_sse_chunk(iterator) for _ in topics]
        assert [next(line[7:] for line in frame.splitlines() if line.startswith("event: "))
                for frame in received] == list(topics)
    finally:
        response.close()


def test_stream_shutdown_emits_terminal_event(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", session.token)
    response = client.get("/stream/events", buffered=False)
    iterator = iter(response.response)
    try:
        assert "event: snapshot" in _sse_chunk(iterator)
        container.realtime.shutdown()

        terminal = _sse_chunk(iterator)

        assert "event: manager.shutdown" in terminal
    finally:
        response.close()
    assert container.realtime.subscriber_count("events") == 0


def test_manager_sse_replays_events_after_last_event_id(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    container.realtime.publish("events", "world.state", {"world_id": "world_before"})
    container.realtime.publish("events", "operation.terminal", {"op_id": "op_after"})
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", session.token)
    response = client.get(
        "/stream/events",
        headers={"Last-Event-ID": "1"},
        buffered=False,
    )
    iterator = iter(response.response)
    try:
        snapshot = _sse_chunk(iterator)
        replay = _sse_chunk(iterator)

        assert "event: snapshot" in snapshot
        assert "id: 2" in replay
        assert "event: operation.terminal" in replay
        assert '"op_id":"op_after"' in replay
    finally:
        response.close()


def test_performance_thresholds_define_documented_reference_gates():
    root = Path(__file__).resolve().parents[2]
    thresholds_path = root / "benchmarks" / "thresholds.json"
    thresholds = json.loads(thresholds_path.read_text(encoding="utf-8"))

    required = {
        "reference_host_profile",
        "idle_window_seconds",
        "idle_cpu_pct_max",
        "idle_rss_mb_max",
        "stream_fanout_clients",
        "stream_metrics_hz",
        "log_ingestion_lines_per_second",
        "log_tail_latency_ms_max",
    }
    assert (
        required <= thresholds.keys()
    ), f"missing performance gates: {required - thresholds.keys()}"
    profile = thresholds["reference_host_profile"]
    assert profile["cpu_model"]
    assert profile["core_count"] > 0
    assert profile["ram_gb"] > 0
    assert profile["storage_type"]
    assert thresholds["idle_window_seconds"] >= 300
    assert thresholds["idle_cpu_pct_max"] <= 2.0
    assert 0 < thresholds["idle_rss_mb_max"] <= 150
    assert thresholds["stream_fanout_clients"] >= 50
    assert thresholds["stream_metrics_hz"] >= 1
    assert thresholds["log_ingestion_lines_per_second"] >= 1000
    assert thresholds["log_tail_latency_ms_max"] > 0


def test_shell_uses_shared_tokens_and_no_inline_style_overrides():
    root = Path(__file__).resolve().parents[2]
    shell_dir = root / "app" / "shell"
    template = (shell_dir / "templates" / "shell.html").read_text(encoding="utf-8")
    stylesheet = (shell_dir / "static" / "shell.css").read_text(encoding="utf-8")

    assert re.search(r"\sstyle\s*=", template, re.IGNORECASE) is None
    for token in (
        "--canvas-bg: #eef2ff",
        "--pane-bg: #ffffff",
        "--border: #d8dee6",
        "--text: #1f2a37",
        "--muted: #5a6878",
    ):
        assert token in stylesheet
    button_rule = re.search(r"\.ui-button\s*\{([^}]+)\}", stylesheet)
    assert button_rule is not None
    assert re.search(r"(?<!min-)height:\s*40px", button_rule.group(1))
