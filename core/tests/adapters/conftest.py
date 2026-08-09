"""Conformance-suite fixtures (Document 13 section 6).

The same C1–C14 tests run against every adapter implementation: the
in-process fake adapter and the native platform adapter (POSIX or Windows).
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import pytest

from app.platform.process.base import LiveRegistry
from app.platform.process.posix import PosixProcessAdapter
from app.platform.process.windows import WindowsProcessAdapter
from app.ports.process_control import (
    ProbeFingerprint,
    SpawnRequest,
)
from tests.adapters.fake_server.fake_adapter import FakeProcessAdapter


def _native_adapter():
    """Real platform adapter. On Windows the kernel32 wiring is lazy and the
    spawn path raises a clear OSError if unavailable, so tests fail loudly
    rather than silently skipping the native adapter."""
    registry = LiveRegistry()
    if sys.platform.startswith('win'):
        return WindowsProcessAdapter(registry)
    return PosixProcessAdapter(registry)


def adapter_factories() -> list[tuple[str, object]]:
    """(name, factory) pairs; kept as a function so factories are per-test."""
    return [
        ('fake', lambda: FakeProcessAdapter()),
        ('native', lambda: _native_adapter()),
    ]


@pytest.fixture(scope='session')
def fake_script_path() -> Path:
    return Path(__file__).resolve().parent / 'fake_server' / 'fake_server.py'


def build_request(
    world_id: str,
    cwd: str,
    port: int,
    rcon_port: int,
    *args: str,
) -> SpawnRequest:
    """Assemble a fake-server argv + a matching SpawnRequest for any adapter."""
    argv = [
        sys.executable,
        str(Path(__file__).resolve().parent / 'fake_server' / 'fake_server.py'),
        f'--port={port}',
        f'--rcon-port={rcon_port}',
        f'--marker=world-{world_id}',
    ]
    argv.extend(args)
    return SpawnRequest(
        world_id=world_id,
        launch_command=argv,
        cwd=cwd,
        env={},
    )


def request_with_marker(world_id: str, cwd: str) -> SpawnRequest:
    """Minimal spawn request with a distinctive launch marker (C11/C14)."""
    argv = [
        sys.executable,
        str(Path(__file__).resolve().parent / 'fake_server' / 'fake_server.py'),
        f'--marker={world_id}-launch-marker',
    ]
    return SpawnRequest(
        world_id=world_id,
        launch_command=argv,
        cwd=cwd,
        env={},
    )


def fingerprint_for(handle) -> ProbeFingerprint:
    return ProbeFingerprint(
        pid=handle.pid,
        spawn_epoch=handle.spawn_epoch,
        launch_marker=None,
    )


def wait_for(predicate, timeout_s: float = 15.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])
