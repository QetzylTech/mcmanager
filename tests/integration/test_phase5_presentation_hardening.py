from __future__ import annotations

import html

import pytest

from app import create_app
from app.shell.routes import PAGE_MODULES
from benchmarks.performance_acceptance import run as run_performance_acceptance


def _app(tmp_path, migrations_dir, clock):
    app = create_app(
        database_path=tmp_path / "manager.db",
        keyfile_path=tmp_path / "secrets.key",
        migrations_dir=migrations_dir,
        clock=clock,
    )
    yield app
    app.extensions["mcmanager_shutdown"]()


def _authenticated_admin_client(app, *, step_up=False):
    container = app.extensions["mcmanager_container"]
    container.auth.provision_first_superadmin(
        username="phase5-admin",
        password="phase5-password",
        device_id="phase5-device",
        device_name="Phase 5 Test Device",
        ip="127.0.0.1",
    )
    session = container.auth.authenticate(
        username="phase5-admin",
        password="phase5-password",
        device_id="phase5-device",
        device_name="Phase 5 Test Device",
        ip="127.0.0.1",
    )
    if step_up:
        session = container.auth.confirm_step_up(
            raw_token=session.token,
            password="phase5-password",
            device_id="phase5-device",
            device_name="Phase 5 Test Device",
            ip="127.0.0.1",
        )

    client = app.test_client()
    client.set_cookie("mcmanager_session", session.token)
    client.get("/api/session")
    csrf_token = client.get_cookie("csrf_token").value
    return client, {"X-CSRF-Token": csrf_token}


def test_persistent_shell_renders_all_17_nav_modules(tmp_path, migrations_dir, clock):
    app_iter = _app(tmp_path, migrations_dir, clock)
    app = next(app_iter)
    try:
        response = app.test_client().get("/")
        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert body.count("data-page=") == 17
        assert 'class="pane"' in body
        assert "pane-title-area" in body
        assert "pane-content-area" in body
        for page in PAGE_MODULES:
            assert html.escape(page.title) in body
    finally:
        next(app_iter, None)


def test_page_api_maps_every_module_to_thin_json_handler(tmp_path, migrations_dir, clock):
    app_iter = _app(tmp_path, migrations_dir, clock)
    app = next(app_iter)
    client, _headers = _authenticated_admin_client(app)
    try:
        listing = client.get("/api/pages").get_json()
        assert listing["ok"] is True
        assert len(listing["data"]["pages"]) == 17
        for page in PAGE_MODULES:
            response = client.get(page.api_path)
            payload = response.get_json()
            assert response.status_code == 200
            assert payload["ok"] is True
            assert payload["data"]["slug"] == page.slug
            assert payload["data"]["sections"]
    finally:
        next(app_iter, None)


def test_health_monitors_scheduler_sqlite_writer_and_process_adapter(
    tmp_path, migrations_dir, clock
):
    app_iter = _app(tmp_path, migrations_dir, clock)
    app = next(app_iter)
    try:
        response = app.test_client().get("/api/health")
        payload = response.get_json()
        assert response.status_code == 200
        data = payload["data"]
        assert data["scheduler"]["status"] == "ok"
        assert data["scheduler"]["tick_interval_seconds"] == 30
        assert data["sqlite_writer"]["status"] == "ok"
        assert data["process_adapter"]["status"] == "ok"
        assert data["process_adapter"]["adapter"]
        assert data["reconciliation"]["status"] == "ok"
        assert data["reconciliation"]["phase"] == "healthy"
    finally:
        next(app_iter, None)


def test_health_reports_reconciliation_failure(tmp_path, migrations_dir, clock, monkeypatch):
    app_iter = _app(tmp_path, migrations_dir, clock)
    app = next(app_iter)
    container = app.extensions["mcmanager_container"]

    def fail_reconcile():
        raise RuntimeError("process probe failed")

    monkeypatch.setattr(
        container.runtime,
        "reconcile",
        fail_reconcile,
    )
    try:
        with pytest.raises(RuntimeError, match="process probe failed"):
            container.reconciliation.reconcile()

        response = app.test_client().get("/api/health")
        payload = response.get_json()
        assert response.status_code == 503
        assert payload["data"]["reconciliation"] == {
            "status": "down",
            "phase": "failed",
            "reattached_worlds": 0,
            "error": "process probe failed",
        }
    finally:
        next(app_iter, None)


def test_health_reports_degrades_to_503_when_writer_down(tmp_path, migrations_dir, clock):
    app_iter = _app(tmp_path, migrations_dir, clock)
    app = next(app_iter)
    client = app.test_client()
    try:
        baseline = client.get("/api/health")
        assert baseline.status_code == 200
        # Simulate a dead writer by closing the store; the probe must fail.
        app.extensions["mcmanager_shutdown"]()
        response = client.get("/api/health")
        assert response.status_code == 503
        assert response.get_json()["data"]["sqlite_writer"]["status"] == "down"
    finally:
        next(app_iter, None)


def test_supervisor_tick_and_world_control_endpoints_exist(tmp_path, migrations_dir, clock):
    app_iter = _app(tmp_path, migrations_dir, clock)
    app = next(app_iter)
    client, headers = _authenticated_admin_client(app, step_up=True)
    try:
        response = client.post("/api/supervisor/tick", headers=headers)
        assert response.status_code == 200
        assert response.get_json()["data"]["crashed"] == []

        # Unknown world -> 404 on all control verbs.
        for verb in ("start", "stop", "kill"):
            response = client.post(f"/api/worlds/does-not-exist/{verb}", headers=headers)
            assert response.status_code == 404, verb
    finally:
        next(app_iter, None)


def test_sse_endpoints_emit_nonblank_snapshots(tmp_path, migrations_dir, clock):
    app_iter = _app(tmp_path, migrations_dir, clock)
    app = next(app_iter)
    client, _headers = _authenticated_admin_client(app)
    try:
        for path, event_name in (
            ("/stream/events", "event: snapshot"),
            ("/stream/worlds/world_1/events", "event: snapshot.world"),
            ("/stream/worlds/world_1/logs", "event: log.line"),
            ("/stream/restore_logs?world_id=world_1", "event: restore.progress"),
            ("/stream/metrics", "event: metrics"),
        ):
            response = client.get(path, buffered=False)
            try:
                body = next(iter(response.response)).decode()
                assert response.status_code == 200
                assert response.mimetype == "text/event-stream"
                assert event_name in body
                assert "data:" in body
            finally:
                response.close()
    finally:
        next(app_iter, None)


def test_performance_acceptance_smoke(tmp_path):
    result = run_performance_acceptance(
        str(tmp_path / "perf.db"),
        str(tmp_path / "perf.key"),
    )
    assert result["passed"], result
