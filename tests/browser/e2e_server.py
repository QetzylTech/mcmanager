"""Disposable local server entry point for the real-browser E2E suite."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args()

    data_dir = project_root / "dev_artifacts" / "browser-e2e"
    data_dir.mkdir(parents=True, exist_ok=True)
    database_path = data_dir / "manager.db"
    keyfile_path = data_dir / "secrets.key"

    for path in (
        database_path,
        database_path.with_name(database_path.name + "-wal"),
        database_path.with_name(database_path.name + "-shm"),
        keyfile_path,
    ):
        path.unlink(missing_ok=True)

    application = create_app(
        database_path=database_path,
        keyfile_path=keyfile_path,
        migrations_dir=project_root / "app" / "migrations",
    )
    try:
        application.run(host="127.0.0.1", port=args.port, threaded=True, use_reloader=False)
    finally:
        application.extensions["mcmanager_shutdown"]()
        for path in (
            database_path,
            database_path.with_name(database_path.name + "-wal"),
            database_path.with_name(database_path.name + "-shm"),
            keyfile_path,
        ):
            path.unlink(missing_ok=True)
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
