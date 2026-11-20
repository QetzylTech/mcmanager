from __future__ import annotations

from unittest.mock import Mock

import psutil

import app.platform.process_health as process_health
from app.domain.value_objects import ProcessState
from app.platform.process.posix import PosixProcessAdapter
from app.platform.process.windows import WindowsProcessAdapter
from app.ports.process_control import ProcessStatus


def test_descendants_returns_recursive_children_and_empty_for_missing_pid(monkeypatch):
    child = Mock()
    parent = Mock()
    parent.children.return_value = [child]
    monkeypatch.setattr(process_health.psutil, "Process", lambda _pid: parent)

    assert process_health.descendants(123) == [child]
    parent.children.assert_called_once_with(recursive=True)

    def missing_process(_pid):
        raise psutil.NoSuchProcess(123)

    monkeypatch.setattr(process_health.psutil, "Process", missing_process)
    assert process_health.descendants(123) == []


def test_any_descendant_alive_checks_parent_then_children(monkeypatch):
    parent = Mock()
    parent.is_running.return_value = True
    monkeypatch.setattr(process_health.psutil, "Process", lambda _pid: parent)
    assert process_health.any_descendant_alive(123) is True
    parent.children.assert_not_called()

    parent.is_running.return_value = False
    parent.children.return_value = [Mock(is_running=Mock(return_value=False))]
    assert process_health.any_descendant_alive(123) is False
    parent.children.assert_called_once_with(recursive=True)

    parent.children.return_value = [Mock(is_running=Mock(return_value=True))]
    assert process_health.any_descendant_alive(123) is True


def test_any_descendant_alive_returns_false_for_missing_pid(monkeypatch):
    def missing_process(_pid):
        raise psutil.NoSuchProcess(123)

    monkeypatch.setattr(process_health.psutil, "Process", missing_process)
    assert process_health.any_descendant_alive(123) is False


def test_process_adapter_factory_selects_platform_adapter(monkeypatch):
    monkeypatch.setattr(process_health.sys, "platform", "win32")
    assert isinstance(process_health.create_process_adapter(), WindowsProcessAdapter)

    monkeypatch.setattr(process_health.sys, "platform", "linux")
    assert isinstance(process_health.create_process_adapter(), PosixProcessAdapter)


def test_status_is_alive_uses_process_state():
    assert process_health.status_is_alive(ProcessStatus(state=ProcessState.RUNNING))
    assert not process_health.status_is_alive(ProcessStatus(state=ProcessState.EXITED))
