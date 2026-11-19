from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import app
import app.main as entrypoint


def test_main_uses_app_local_env_data_and_migrations(tmp_path, monkeypatch) -> None:
    loaded_env: list[Path] = []
    app_kwargs: dict[str, object] = {}
    application = Mock()

    def fake_load_dotenv(path: Path) -> None:
        loaded_env.append(path)

    def fake_create_app(**kwargs: object) -> Mock:
        app_kwargs.update(kwargs)
        return application

    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.setattr(entrypoint, 'APP_DIR', tmp_path)
    monkeypatch.setattr('dotenv.load_dotenv', fake_load_dotenv)
    monkeypatch.setattr(app, 'create_app', fake_create_app)
    monkeypatch.setenv('MC_MANAGER_HOST', '127.0.0.2')
    monkeypatch.setenv('MC_MANAGER_PORT', '5050')

    entrypoint.main()

    assert loaded_env == [tmp_path / '.env']
    assert app_kwargs == {
        'database_path': tmp_path / 'data' / 'manager.db',
        'keyfile_path': tmp_path / 'data' / 'secrets.key',
        'migrations_dir': tmp_path / 'migrations',
    }
    assert (tmp_path / 'data').is_dir()
    application.run.assert_called_once_with(host='127.0.0.2', port=5050)


def test_direct_start_does_not_shadow_standard_library_platform() -> None:
    script = (
        'import sys; '
        'from main import _prepare_import_path; '
        '_prepare_import_path(); '
        "sys.modules.pop('platform', None); "
        'import app.bootstrap; '
        'import platform; '
        'assert callable(platform.machine)'
    )
    result = subprocess.run(
        [sys.executable, '-c', script],
        capture_output=True,
        check=False,
        cwd=Path(__file__).resolve().parents[2] / 'app',
        text=True,
    )
    assert result.returncode == 0, result.stderr
