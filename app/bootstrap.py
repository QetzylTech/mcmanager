"""Composition root / dependency-injection container (Document 12 sections 3, 5).

This module — plus ``app/__init__.py`` orchestration — is the ONLY place
where concrete port implementations are constructed and injected. Services
receive dependencies via constructor injection and never import
``platform/`` or ``infrastructure/`` concretes themselves (Doc 12 section 4).

Build order mirrors Doc 12 section 5:
1. Open SQLite with ``PRAGMA foreign_keys = ON``; run ``schema_migrations``
   then the ``foreign_key_check`` sweep (startup-blocking on violation).
2. Provision the secrets keyfile outside the database (never a table).
3. Construct each port's concrete implementation and inject into services.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path

from app.infrastructure.backup_engine import NativeBackupEngine
from app.infrastructure.filesystem import LocalFilesystem
from app.infrastructure.metrics import PsutilHostMetrics
from app.infrastructure.minecraft.adapter import MinecraftServerAdapter
from app.infrastructure.minecraft.rcon import RconClient
from app.infrastructure.secrets import SqliteSecretsStore, provision_keyfile
from app.infrastructure.sqlite.connection import SqliteStore
from app.infrastructure.sqlite.migrations import run_migrations
from app.infrastructure.sync_transport.nas import NasSyncTransport
from app.platform.process.base import LiveRegistry
from app.platform.process.posix import PosixProcessAdapter
from app.platform.process.windows import WindowsProcessAdapter
from app.ports.clock import Clock, SystemClock
from app.ports.minecraft import MinecraftServerPort
from app.ports.process_control import ProcessControlPort
from app.services.audit import AuditService
from app.services.auth import AuthenticationService
from app.services.backup import BackupService
from app.services.catalog_operations import CatalogOperationDispatcher
from app.services.cleanup import CleanupService
from app.services.configuration import ConfigurationService
from app.services.manager_lifecycle import ManagerLifecycleService
from app.services.metrics import MetricsService
from app.services.notifications import NotificationService
from app.services.operations import OperationService
from app.services.realtime import LogFanout, RealtimeHub
from app.services.reconciliation import ReconciliationService
from app.services.restore import RestoreService
from app.services.runtime import RuntimeService
from app.services.save_coordination import RconSaveCoordinator
from app.services.scheduler import SchedulerService
from app.services.sync import SyncService
from app.services.worlds import WorldsService


@dataclass(frozen=True)
class Container:
    """The wired application container (read-only after build)."""

    # ports / adapters
    clock: Clock
    store: SqliteStore
    secrets: SqliteSecretsStore
    process_adapter: ProcessControlPort
    minecraft_adapter: MinecraftServerPort

    # services
    audit: AuditService
    notifications: NotificationService
    auth: AuthenticationService
    operations: OperationService
    runtime: RuntimeService
    reconciliation: ReconciliationService
    scheduler: SchedulerService
    realtime: RealtimeHub
    metrics: MetricsService
    logs: LogFanout
    backups: BackupService
    catalog_operations: CatalogOperationDispatcher
    restore: RestoreService
    cleanup: CleanupService
    sync: SyncService
    configuration: ConfigurationService
    worlds: WorldsService
    save_coordinator: RconSaveCoordinator
    manager_lifecycle: ManagerLifecycleService


def _migrations_dir() -> Path:
    # app/bootstrap.py -> parents[1] = repository root; migrations/ is a sibling.
    return Path(__file__).resolve().parents[1] / 'migrations'


def _create_process_adapter() -> ProcessControlPort:
    """Platform process adapter: POSIX vs Windows (Doc 13), bound to a fresh
    live registry at boot (reconstructed by reconciliation probing)."""
    registry = LiveRegistry()
    if platform.system() == 'Windows':
        return WindowsProcessAdapter(registry)
    return PosixProcessAdapter(registry)


def build_container(
    *,
    database_path: str | Path,
    keyfile_path: str | Path,
    migrations_dir: str | Path | None = None,
    clock: Clock | None = None,
) -> Container:
    """Construct the full container. Raises :class:`PersistenceError` when
    migrations fail or the FK sweep finds violations — startup must not
    proceed (Global Persistence Invariant)."""
    store = SqliteStore(database_path)
    store.open()
    try:
        run_migrations(store, migrations_dir or _migrations_dir())
    except Exception:
        # Never leave a half-open store behind (Windows keeps the DB file
        # locked until every connection is closed).
        store.close()
        raise

    keyfile = provision_keyfile(keyfile_path)
    secrets = SqliteSecretsStore(store, keyfile)
    clock = clock or SystemClock()
    audit = AuditService(store, clock)
    notifications = NotificationService(store, clock)
    auth = AuthenticationService(store, secrets, clock, audit)
    realtime = RealtimeHub()
    metrics = MetricsService(
        store,
        clock,
        realtime,
        PsutilHostMetrics(Path(database_path).resolve().parent),
    )
    operations = OperationService(
        store, clock, audit, realtime, notifications=notifications
    )
    scheduler = SchedulerService(store, clock, operations, notifications)
    logs = LogFanout(realtime)
    save_coordinator = RconSaveCoordinator(store, secrets, rcon_factory=RconClient)
    backup_engine = NativeBackupEngine()
    backups = BackupService(
        store,
        clock,
        save_coordinator,
        backup_engine,
        LocalFilesystem(),
    )
    cleanup = CleanupService(store, clock)
    configuration = ConfigurationService(store, clock, operations)
    manager_lifecycle = ManagerLifecycleService(
        store, clock, operations, configuration, backup_engine
    )
    process_adapter = _create_process_adapter()
    minecraft_adapter = MinecraftServerAdapter()
    worlds = WorldsService(
        store=store,
        clock=clock,
        operations=operations,
        process_adapter=process_adapter,
        secrets=secrets,
        minecraft=minecraft_adapter,
        logs=logs,
        audit=audit,
        realtime=realtime,
    )
    runtime = RuntimeService(worlds)
    restore = RestoreService(store, clock, operations, backups, runtime)
    sync = SyncService(store, NasSyncTransport(store), clock, operations)
    catalog_operations = CatalogOperationDispatcher(
        store,
        clock,
        operations,
        configuration,
        backups,
        restore,
        cleanup,
        sync,
        manager_lifecycle,
    )
    reconciliation = ReconciliationService(runtime)

    return Container(
        clock=clock,
        store=store,
        secrets=secrets,
        process_adapter=process_adapter,
        minecraft_adapter=minecraft_adapter,
        audit=audit,
        notifications=notifications,
        auth=auth,
        operations=operations,
        runtime=runtime,
        reconciliation=reconciliation,
        scheduler=scheduler,
        realtime=realtime,
        metrics=metrics,
        logs=logs,
        backups=backups,
        catalog_operations=catalog_operations,
        restore=restore,
        cleanup=cleanup,
        sync=sync,
        configuration=configuration,
        worlds=worlds,
        save_coordinator=save_coordinator,
        manager_lifecycle=manager_lifecycle,
    )
