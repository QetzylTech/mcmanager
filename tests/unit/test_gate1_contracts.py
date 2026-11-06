"""Focused Gate 1 adapter-boundary contracts."""

from __future__ import annotations

import ast
import inspect
from dataclasses import fields
from pathlib import Path

from app.platform.process.posix import PosixHandle
from app.platform.process.windows import WindowsHandle
from app.ports.process_control import ProcessHandle
from app.platform.process.tailing import DurableSessionLog, LogRingBuffer, ingest_log_line
from app.services.worlds import WorldsService
from tests.adapters.fake_server.fake_adapter import FakeHandle


_HANDLE_FIELDS = {
    'world_id',
    'pid',
    'spawn_epoch',
    'process_group_id',
    'job_handle',
}


def test_process_handle_field_names_are_uniform():
    assert set(ProcessHandle.__annotations__) == _HANDLE_FIELDS
    for handle_type in (PosixHandle, WindowsHandle, FakeHandle):
        assert {field.name for field in fields(handle_type)} >= _HANDLE_FIELDS


def test_worlds_service_uses_ports_and_bootstrap_injects_them(container):
    source = Path(inspect.getsourcefile(WorldsService)).read_text(encoding='utf-8')
    tree = ast.parse(source)
    infrastructure_imports = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith('app.infrastructure.minecraft')
    ]
    assert infrastructure_imports == []
    assert container.worlds._adapter is container.process_adapter
    assert container.worlds._minecraft is container.minecraft_adapter


def test_verbose_logging_filters_only_debug_and_persists_session_lines(
    tmp_path, monkeypatch
):
    log_path = tmp_path / 'session.log'
    buffer = LogRingBuffer()
    durable = DurableSessionLog(str(log_path))
    monkeypatch.setenv('VERBOSE_LOGGING', 'false')

    assert not ingest_log_line(buffer, 'stdout', '[DEBUG] hidden', durable_log=durable)
    assert ingest_log_line(buffer, 'stderr', '[ERROR] retained', durable_log=durable)

    assert buffer.channel('stdout').tail() == []
    assert [line for _, line in buffer.channel('stderr').tail()] == ['[ERROR] retained']
    content = log_path.read_text(encoding='utf-8')
    assert '[DEBUG] hidden' not in content
    assert '[ERROR] retained' in content

    monkeypatch.setenv('VERBOSE_LOGGING', 'true')
    assert ingest_log_line(buffer, 'stdout', '[DEBUG] visible', durable_log=durable)
    assert '[DEBUG] visible' in log_path.read_text(encoding='utf-8')
