"""Java detection, compatibility matrix, and the pre-launch gate (Doc 14
sections 4 and 7).

The gate must reject EULA-unaccepted worlds and Java-incompatible runtimes
BEFORE any process is spawned.
"""

from __future__ import annotations

import subprocess

import pytest

from app.domain.value_objects import EulaState, ServerType
from app.infrastructure.minecraft.eula import accept, current_state, provision_eula_file
from app.infrastructure.minecraft.gate import (
    ERROR_EULA_NOT_ACCEPTED,
    ERROR_JAR_MISSING,
    ERROR_JAVA_INCOMPATIBLE,
    ERROR_PORT_CONFLICT,
    ERROR_WORLD_DIR_MISSING,
    LaunchContext,
    build_launch_argv,
    validate_launch,
)
from app.infrastructure.minecraft.java_compatibility import (
    detect_java,
    java_compatible,
    parse_java_major,
    recommended_java,
)
from app.ports.minecraft import java_compatibility_for, java_major_compatible

# ---- EULA gating (Doc 14 section 5) -----------------------------------------


def test_provision_eula_file_writes_false(tmp_path):
    provision_eula_file(str(tmp_path))
    state = current_state(str(tmp_path))
    assert state is EulaState.UNACCEPTED
    content = (tmp_path / 'eula.txt').read_text(encoding='utf-8')
    assert 'eula=false' in content


def test_provision_eula_never_overwrites_existing(tmp_path):
    (tmp_path / 'eula.txt').write_text('eula=true\n', encoding='utf-8')
    provision_eula_file(str(tmp_path))
    assert current_state(str(tmp_path)) is EulaState.ACCEPTED


def test_detect_eula_states(tmp_path):
    provision_eula_file(str(tmp_path))
    assert current_state(str(tmp_path)) is EulaState.UNACCEPTED

    (tmp_path / 'eula.txt').write_text('eula=true\n', encoding='utf-8')
    assert current_state(str(tmp_path)) is EulaState.ACCEPTED

    (tmp_path / 'eula.txt').unlink()
    assert current_state(str(tmp_path)) is EulaState.NOT_PRESENT


def test_accept_writes_the_only_true_writer(tmp_path):
    provision_eula_file(str(tmp_path))
    accept(str(tmp_path))
    assert current_state(str(tmp_path)) is EulaState.ACCEPTED


# ---- Java version parsing + detection (Doc 14 section 7) --------------------


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('1.8.0_411', 8),
        ('1.7.0_80', 7),
        ('17.0.9', 17),
        ('21', 21),
        ('21.0.1+12-LTS', 21),
        ('garbage', 0),
    ],
)
def test_parse_java_major(raw, expected):
    assert parse_java_major(raw) == expected


def _stub_java(monkeypatch, *, version: str | None) -> None:
    """Replace subprocess.run so detect_java parses a canned -version output."""

    def fake_run(argv, **kwargs):
        stderr = f'openjdk version "{version}" 2024-01-01\n' if version else 'not java\n'
        return subprocess.CompletedProcess(argv, 0, stdout='', stderr=stderr)

    monkeypatch.setattr(
        'app.infrastructure.minecraft.java_compatibility.subprocess.run', fake_run
    )


def test_detect_java_parses_version(monkeypatch):
    _stub_java(monkeypatch, version='17.0.9')
    detection = detect_java('/any/path/java')
    assert detection is not None
    assert detection.major == 17
    assert detection.full_version == '17.0.9'


def test_detect_java_returns_none_on_unparseable(monkeypatch):
    _stub_java(monkeypatch, version=None)
    assert detect_java('/any/path/java') is None


# ---- Compatibility matrix -----------------------------------------------------


def test_java_compatible_curated_data():
    assert java_compatible(server_type=ServerType.VANILLA, mc_version='1.20', java_major=17)
    assert java_compatible(server_type=ServerType.VANILLA, mc_version='1.20', java_major=21)
    assert not java_compatible(server_type=ServerType.VANILLA, mc_version='1.20', java_major=8)
    assert java_compatible(server_type=ServerType.PAPER, mc_version='1.21', java_major=21)
    assert not java_compatible(server_type=ServerType.FORGE, mc_version='1.21', java_major=17)


def test_java_major_compatible_port_fn():
    assert java_major_compatible(
        server_type=ServerType.VANILLA, mc_version='1.21', java_major=21
    )
    assert not java_major_compatible(
        server_type=ServerType.VANILLA, mc_version='1.21', java_major=17
    )


def test_recommended_java():
    assert recommended_java(ServerType.PAPER, '1.21') == 21


def test_unknown_version_is_incompatible():
    assert java_compatibility_for(ServerType.VANILLA, '9.99') is None
    assert not java_compatible(server_type=ServerType.VANILLA, mc_version='9.99', java_major=21)


# ---- Pre-launch gate (Doc 14 section 4) ----------------------------------------


def _context(tmp_path, *, eula=True, jar=True, java_ok=True, port=0) -> LaunchContext:
    jar_path = str(tmp_path / 'server.jar')
    if jar:
        (tmp_path / 'server.jar').write_bytes(b'PK\x03\x04')

    if eula:
        accept(str(tmp_path))
    else:
        provision_eula_file(str(tmp_path))

    return LaunchContext(
        world_id='w',
        server_type=ServerType.VANILLA,
        mc_version='1.21',
        world_dir=str(tmp_path),
        java_path='/any/path/java',
        server_jar_path=jar_path,
        port=port,
    )


def test_gate_rejects_unaccepted_eula(tmp_path, monkeypatch):
    _stub_java(monkeypatch, version='21')
    result = validate_launch(_context(tmp_path, eula=False))
    assert not result.passed
    assert result.error_code == ERROR_EULA_NOT_ACCEPTED
    assert result.eula_state is EulaState.UNACCEPTED


def test_gate_rejects_missing_jar(tmp_path, monkeypatch):
    _stub_java(monkeypatch, version='21')
    result = validate_launch(_context(tmp_path, jar=False))
    assert not result.passed
    assert result.error_code == ERROR_JAR_MISSING


def test_gate_rejects_missing_world_dir(tmp_path, monkeypatch):
    _stub_java(monkeypatch, version='21')
    ctx = _context(tmp_path)
    ctx = LaunchContext(
        world_id=ctx.world_id,
        server_type=ctx.server_type,
        mc_version=ctx.mc_version,
        world_dir=str(tmp_path / 'nope'),
        java_path=ctx.java_path,
        server_jar_path=ctx.server_jar_path,
        port=ctx.port,
    )
    result = validate_launch(ctx)
    assert not result.passed
    assert result.error_code == ERROR_WORLD_DIR_MISSING


def test_gate_rejects_incompatible_java(tmp_path, monkeypatch):
    _stub_java(monkeypatch, version='8')
    result = validate_launch(_context(tmp_path))
    assert not result.passed
    assert result.error_code == ERROR_JAVA_INCOMPATIBLE
    assert result.java_major == 8


def test_gate_rejects_bound_port(tmp_path, monkeypatch):
    import socket

    _stub_java(monkeypatch, version='21')
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        sock.listen(1)
        result = validate_launch(_context(tmp_path, port=port))
        assert not result.passed
        assert result.error_code == ERROR_PORT_CONFLICT


def test_gate_passes_when_all_green(tmp_path, monkeypatch):
    _stub_java(monkeypatch, version='21')
    result = validate_launch(_context(tmp_path))
    assert result.passed, result.detail
    assert result.java_major == 21


def test_build_launch_argv_is_explicit_list():
    argv = build_launch_argv('/usr/bin/java', ['-Xmx2G'], '/srv/server.jar', ['nogui'])
    assert argv == ['/usr/bin/java', '-Xmx2G', '-jar', '/srv/server.jar', 'nogui']
    assert all(isinstance(part, str) for part in argv)
