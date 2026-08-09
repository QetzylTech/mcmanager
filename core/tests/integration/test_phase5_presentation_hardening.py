from __future__ import annotations

import html

from app import create_app
from app.shell.routes import PAGE_MODULES

from benchmarks.performance_acceptance import run as run_performance_acceptance


def _app(tmp_path, migrations_dir, clock):
    app = create_app(
        database_path=tmp_path / 'manager.db',
        keyfile_path=tmp_path / 'secrets.key',
        migrations_dir=migrations_dir,
        clock=clock,
    )
    yield app
    app.extensions['mcmanager_container'].store.close()


def test_persistent_shell_renders_all_17_nav_modules(tmp_path, migrations_dir, clock):
    app_iter = _app(tmp_path, migrations_dir, clock)
    app = next(app_iter)
    try:
        response = app.test_client().get('/')
        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert body.count('data-page=') == 17
        assert 'class="pane"' in body
        assert 'pane-title-area' in body
        assert 'pane-content-area' in body
        for page in PAGE_MODULES:
            assert html.escape(page.title) in body
    finally:
        next(app_iter, None)


def test_page_api_maps_every_module_to_thin_json_handler(tmp_path, migrations_dir, clock):
    app_iter = _app(tmp_path, migrations_dir, clock)
    app = next(app_iter)
    client = app.test_client()
    try:
        listing = client.get('/api/pages').get_json()
        assert listing['ok'] is True
        assert len(listing['data']['pages']) == 17
        for page in PAGE_MODULES:
            response = client.get(page.api_path)
            payload = response.get_json()
            assert response.status_code == 200
            assert payload['ok'] is True
            assert payload['data']['slug'] == page.slug
            assert payload['data']['sections']
    finally:
        next(app_iter, None)


def test_health_monitors_scheduler_sqlite_writer_and_process_adapter(tmp_path, migrations_dir, clock):
    app_iter = _app(tmp_path, migrations_dir, clock)
    app = next(app_iter)
    try:
        response = app.test_client().get('/api/health')
        payload = response.get_json()
        assert response.status_code == 200
        data = payload['data']
        assert data['scheduler']['status'] == 'ok'
        assert data['scheduler']['tick_interval_seconds'] == 30
        assert data['sqlite_writer']['status'] == 'ok'
        assert data['process_adapter']['status'] == 'ok'
        assert data['process_adapter']['adapter']
    finally:
        next(app_iter, None)


def test_health_reports_degrades_to_503_when_writer_down(tmp_path, migrations_dir, clock):
    app_iter = _app(tmp_path, migrations_dir, clock)
    app = next(app_iter)
    client = app.test_client()
    try:
        baseline = client.get('/api/health')
        assert baseline.status_code == 200
        # Simulate a dead writer by closing the store; the probe must fail.
        app.extensions['mcmanager_container'].store.close()
        response = client.get('/api/health')
        assert response.status_code == 503
        assert response.get_json()['data']['sqlite_writer']['status'] == 'down'
    finally:
        next(app_iter, None)


def test_supervisor_tick_and_world_control_endpoints_exist(tmp_path, migrations_dir, clock):
    app_iter = _app(tmp_path, migrations_dir, clock)
    app = next(app_iter)
    client = app.test_client()
    try:
        response = client.post('/api/supervisor/tick')
        assert response.status_code == 200
        assert response.get_json()['data']['crashed'] == []

        # Unknown world -> 404 on all control verbs.
        for verb in ('start', 'stop', 'kill'):
            response = client.post(f'/api/worlds/does-not-exist/{verb}')
            assert response.status_code == 404, verb
    finally:
        next(app_iter, None)


def test_sse_endpoints_emit_nonblank_snapshots(tmp_path, migrations_dir, clock):
    app_iter = _app(tmp_path, migrations_dir, clock)
    app = next(app_iter)
    client = app.test_client()
    try:
        for path, event_name in (
            ('/stream/events', 'event: snapshot'),
            ('/stream/worlds/world_1/events', 'event: snapshot.world'),
            ('/stream/worlds/world_1/logs', 'event: log.line'),
            ('/stream/restore_logs?world_id=world_1', 'event: restore.progress'),
            ('/stream/metrics', 'event: metrics'),
        ):
            response = client.get(path)
            body = response.get_data(as_text=True)
            assert response.status_code == 200
            assert response.mimetype == 'text/event-stream'
            assert event_name in body
            assert 'data:' in body
    finally:
        next(app_iter, None)


def test_performance_acceptance_smoke(tmp_path):
    result = run_performance_acceptance(
        str(tmp_path / 'perf.db'),
        str(tmp_path / 'perf.key'),
    )
    assert result['passed'], result
