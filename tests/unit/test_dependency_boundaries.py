"""Dependency direction contracts for application services."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import get_type_hints

from app.infrastructure.sqlite.connection import SqliteStore
from app.ports.persistence import PersistencePort
from app.services.audit import AuditService
from app.services.auth import AuthenticationService
from app.services.backup import BackupService
from app.services.cleanup import CleanupService
from app.services.configuration import ConfigurationService
from app.services.notifications import NotificationService
from app.services.operations import OperationService
from app.services.restore import RestoreService
from app.services.save_coordination import RconSaveCoordinator
from app.services.scheduler import SchedulerService
from app.services.sync import SyncService
from app.services.worlds import WorldsService

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SERVICES_DIR = REPOSITORY_ROOT / 'app' / 'services'
PERSISTENCE_PORT_SERVICES = (
    AuditService,
    AuthenticationService,
    ConfigurationService,
    BackupService,
    CleanupService,
    NotificationService,
    OperationService,
    RestoreService,
    SyncService,
    WorldsService,
    RconSaveCoordinator,
    SchedulerService,
)


def _imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_services_do_not_import_platform_adapters():
    for source_path in SERVICES_DIR.glob('*.py'):
        imported_modules = _imported_modules(
            source_path.read_text(encoding='utf-8')
        )
        platform_imports = {
            module
            for module in imported_modules
            if module == 'app.platform' or module.startswith('app.platform.')
        }
        assert not platform_imports, f'{source_path.name}: {platform_imports}'


def test_services_use_ports_instead_of_concrete_infrastructure():
    for source_path in SERVICES_DIR.glob('*.py'):
        imported_modules = _imported_modules(
            source_path.read_text(encoding='utf-8')
        )
        infrastructure_imports = {
            module
            for module in imported_modules
            if module == 'app.infrastructure'
            or module.startswith('app.infrastructure.')
        }
        assert not infrastructure_imports, (
            f'{source_path.name}: {infrastructure_imports}'
        )


def test_sqlite_store_implements_persistence_port_and_services_accept_it():
    assert isinstance(SqliteStore.__new__(SqliteStore), PersistencePort)
    for service in PERSISTENCE_PORT_SERVICES:
        assert get_type_hints(service.__init__)['store'] is PersistencePort
