"""Cross-platform startup entry point for an app-only distribution."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


def _prepare_import_path() -> None:
    sys.path[:] = [entry for entry in sys.path if Path(entry or Path.cwd()).resolve() != APP_DIR]
    package_parent = str(APP_DIR.parent)
    if package_parent not in sys.path:
        sys.path.insert(0, package_parent)


def main() -> None:
    _prepare_import_path()

    from dotenv import load_dotenv

    load_dotenv(APP_DIR / '.env')

    from app import create_app

    data_dir = APP_DIR / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    application = create_app(
        database_path=data_dir / 'manager.db',
        keyfile_path=data_dir / 'secrets.key',
        migrations_dir=APP_DIR / 'migrations',
    )
    host = os.getenv('MC_MANAGER_HOST', '127.0.0.1')
    port = int(os.getenv('MC_MANAGER_PORT', '5000'))
    application.run(host=host, port=port)


if __name__ == '__main__':
    main()
