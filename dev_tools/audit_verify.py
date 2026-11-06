"""One-off verification script for the audit findings."""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import app
from app.bootstrap import build_container
from app.services.operations import OperationService, OperationInput
from app.domain.value_objects import OperationType, ActorType

print('python:', sys.executable)
print('app module:', app.__file__)
print('Flask import OK')

tmp = PROJECT_ROOT / 'dev_artifacts' / 'audit_tmp'
tmp.mkdir(parents=True, exist_ok=True)
container = build_container(
    database_path=tmp / 'db.sqlite',
    keyfile_path=tmp / 'secrets.key',
    migrations_dir=PROJECT_ROOT / 'migrations',
)
try:
    count = container.store.reader().execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
    print('table count:', count)
    print('process_adapter:', type(container.process_adapter).__name__)
    print('scheduler tick:', container.scheduler.tick_interval_seconds)
finally:
    container.store.close()
