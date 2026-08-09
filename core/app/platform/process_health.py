"""PID-reuse guards, orphan detection, exit-status classification (Doc 13).

Also provides the composition-root factory that selects the platform
adapter. This module is part of ``app/platform`` — leaf-only, imported by
the composition root and infrastructure bindings only.
"""

from __future__ import annotations

import sys

import psutil

from app.platform.process.base import LiveRegistry
from app.platform.process.posix import PosixProcessAdapter
from app.platform.process.windows import WindowsProcessAdapter
from app.ports.process_control import ProcessControlPort, ProcessStatus


def create_process_adapter() -> ProcessControlPort:
    """Build the process-control adapter for the current OS (composition root).

    Call once in bootstrap and inject everywhere else via the port.
    """
    registry = LiveRegistry()
    if sys.platform.startswith('win'):
        return WindowsProcessAdapter(registry)
    return PosixProcessAdapter(registry)


def descendants(pid: int) -> list[psutil.Process]:
    """Return all live descendants of a process (orphan-detection support)."""
    try:
        parent = psutil.Process(pid)
        return parent.children(recursive=True)
    except psutil.NoSuchProcess:
        return []


def any_descendant_alive(pid: int) -> bool:
    """True if the process tree still has live members (C6 containment check)."""
    try:
        parent = psutil.Process(pid)
        if parent.is_running():
            return True
        return any(desc.is_running() for desc in parent.children(recursive=True))
    except psutil.NoSuchProcess:
        return False


def status_is_alive(status: ProcessStatus) -> bool:
    """Portability wrapper around ProcessStatus.alive for supervisor code."""
    return status.alive
