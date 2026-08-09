"""Per-OS default root resolution (manager config/data/logs), Doc 12."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _localappdata() -> Path | None:
    appdata = os.environ.get('LOCALAPPDATA')
    if appdata:
        return Path(appdata)
    return None


def default_root() -> Path:
    """Per-OS manager home.

    Windows: %LOCALAPPDATA%/mcmanager. POSIX: XDG_DATA_HOME/mcmanager or
    ~/.local/share/mcmanager.
    """
    if sys.platform.startswith('win'):
        base = _localappdata() or Path.home() / 'AppData' / 'Local'
        return base / 'mcmanager'
    base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
    return base / 'mcmanager'


def default_data_dir() -> Path:
    return default_root() / 'data'


def default_logs_dir() -> Path:
    return default_root() / 'logs'


def default_config_path() -> Path:
    return default_root() / 'config.json'


def ensure_default_dirs() -> tuple[Path, Path, Path]:
    """Create data/logs dirs and return (data, logs, config)."""
    data = default_data_dir()
    logs = default_logs_dir()
    config = default_config_path()
    data.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    return data, logs, config
