"""Gate 5 acceptance contracts from WBS 5.1–5.3 and Documents 4, 5, 10–12."""

from __future__ import annotations

import json
import re
from functools import partial
from pathlib import Path
from uuid import uuid4

import app.bootstrap as bootstrap
import pytest
from app import create_app
from app.domain.value_objects import ActorType, OperationType
from app.services.operations import OperationInput
from app.services.worlds import WorldsService


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
        )
        yield app
    finally:
        if app is not None:
            app.extensions["mcmanager_container"].store.close()
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


@pytest.mark.parametrize(
    ("cookie_token", "header_token"),
    [(None, None), ("cookie-token", "different-token")],
)
def test_state_changes_require_matching_csrf_cookie_and_header(
    gate5_app, cookie_token, header_token
):
    client = gate5_app.test_client()
    if cookie_token is not None:
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


@pytest.mark.parametrize("path", ["/", "/api/health", "/api/route-that-does-not-exist"])
def test_security_headers_cover_html_and_api_responses(gate5_app, path):
    response = gate5_app.test_client().get(path)

    csp = response.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


def test_start_returns_202_operation_envelope(gate5_app, monkeypatch):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", session.token)
    client.get("/api/session")
    csrf_token = client.get_cookie("csrf_token").value
    monkeypatch.setattr(container.worlds, "start", lambda **_kwargs: "op_gate5_start")

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


def test_operation_read_returns_the_persisted_operation(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    operation = container.operations.create(
        OperationInput(
            op_type=OperationType.START,
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


def _sse_chunk(iterator) -> str:
    chunk = next(iterator)
    return chunk.decode() if isinstance(chunk, bytes) else chunk


def test_manager_sse_stays_open_and_fans_out_hub_events(gate5_app):
    container = gate5_app.extensions["mcmanager_container"]
    session = _login(container)
    client = gate5_app.test_client()
    client.set_cookie("mcmanager_session", session.token)
    response = client.get("/stream/events", buffered=False)
    iterator = iter(response.response)
    try:
        snapshot = _sse_chunk(iterator)
        assert "event: snapshot" in snapshot
        assert "data:" in snapshot

        container.realtime.publish("events", "world.state", {"world_id": "world_gate5"})
        live_event = _sse_chunk(iterator)

        assert "event: world.state" in live_event
        assert '"world_id":"world_gate5"' in live_event
    finally:
        response.close()


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
