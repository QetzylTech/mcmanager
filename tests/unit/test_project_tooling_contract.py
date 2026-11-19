from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_dev_tooling_contract_exists() -> None:
    pyproject = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    assert '[tool.black]' in pyproject
    assert '[tool.isort]' in pyproject
    assert '[tool.ruff]' in pyproject
    assert '[tool.mypy]' in pyproject
    assert '[tool.importlinter]' in pyproject
    assert '--cov=app' in pyproject
    assert '--strict-markers' in pyproject

    requirements_dev = ROOT / 'requirements-dev.txt'
    assert requirements_dev.exists()
    assert 'pytest-cov' in requirements_dev.read_text(encoding='utf-8')

    app_requirements = ROOT / 'app' / 'requirements.txt'
    assert 'psutil' in app_requirements.read_text(encoding='utf-8')
    assert 'python-dotenv' in app_requirements.read_text(encoding='utf-8')
    assert '-r app/requirements.txt' in (ROOT / 'requirements.txt').read_text(encoding='utf-8')
    assert (ROOT / 'app').is_dir()
    assert (ROOT / 'app' / 'migrations').is_dir()
    assert (ROOT / 'tests').is_dir()
    assert not (ROOT / 'core').exists()
    assert not (ROOT / 'app' / 'worlds').exists()
