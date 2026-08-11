from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask

from app.bootstrap import build_container
from app.domain.value_objects import (
    ActorType,
    ConfigEditEntity,
    NotificationSeverity,
    OperationStatus,
    OperationType,
    TriggerType,
)
from app.infrastructure.minecraft.capabilities import capabilities_for
from app.infrastructure.minecraft.eula import accept, current_state, provision_eula_file
from app.infrastructure.minecraft.gate import LaunchContext, build_launch_argv, validate_launch
from app.infrastructure.minecraft.java_compatibility import detect_java, parse_java_major
from app.infrastructure.minecraft.ping import ping_protocol
from app.infrastructure.minecraft.properties_schema import CORE_MANAGER_PROPERTIES, validate_properties
from app.infrastructure.minecraft.rcon import RconClient, RconError
from app.infrastructure.minecraft.readiness import build_state, evaluate, target_level_for
from app.infrastructure.secrets import SqliteSecretsStore, provision_keyfile
from app.infrastructure.sqlite.connection import SqliteStore
from app.platform.paths import (
    default_config_path,
    default_data_dir,
    default_logs_dir,
    default_root,
    ensure_default_dirs,
)
from app.services.audit import AuditService, ActorSnapshot
from app.services.backup import BackupService
from app.services.cleanup import CleanupService
from app.services.configuration import ConfigurationService, VersionedUpdate
from app.services.notifications import NotificationInput, NotificationService
from app.services.operations import OperationInput, OperationService
from app.services.realtime import LogFanout, RealtimeHub
from app.services.scheduler import SchedulerService
from app.services.worlds import WorldsService
from app.shell.routes import PAGE_BY_SLUG, PAGE_MODULES, shell_bp
from app.web.api import register_api_blueprints
from app.web.errors import ok


class DummyClock:
    def __init__(self, value: int = 1700000000):
        self._value = value

    def now(self) -> int:
        return self._value


def _container(tmp_path: Path):
    db = tmp_path / 'manager.sqlite'
    keyfile = tmp_path / 'secrets.key'
    return build_container(database_path=db, keyfile_path=keyfile, clock=DummyClock())


def test_platform_and_bootstrap_smoke(tmp_path):
    old = os.environ.get('LOCALAPPDATA')
    try:
        os.environ['LOCALAPPDATA'] = str(tmp_path)
        assert default_root().name == 'mcmanager'
        assert default_data_dir().parts[-2:] == ('mcmanager', 'data')
        assert default_logs_dir().parts[-2:] == ('mcmanager', 'logs')
        assert default_config_path().name == 'config.json'
        data, logs, config = ensure_default_dirs()
        assert data.exists() and logs.exists() and config.parent == data.parent
    finally:
        if old is None:
            os.environ.pop('LOCALAPPDATA', None)
        else:
            os.environ['LOCALAPPDATA'] = old

    container = _container(tmp_path)
    assert container.store.path.endswith('manager.sqlite')
    assert container.process_adapter is not None
    assert container.scheduler.tick_interval_seconds > 0
    assert container.audit is not None
    assert len(container.worlds.list_worlds()) == 0


def test_infra_helpers_and_gate_smoke(tmp_path):
    world = tmp_path / 'server'
    world.mkdir()
    provision_eula_file(str(world))
    accept(str(world))
    assert current_state(str(world)) is not None
    assert validate_launch(
        LaunchContext(
            world_id='w1',
            server_type='vanilla',
            mc_version='1.21',
            world_dir=str(world),
            java_path='java',
            server_jar_path=str(world / 'server.jar'),
            port=25565,
        )
    )

    (world / 'server.jar').write_bytes(b'PK\x03\x04')
    gate = validate_launch(
        LaunchContext(
            world_id='w1',
            server_type='vanilla',
            mc_version='1.21',
            world_dir=str(world),
            java_path='java',
            server_jar_path=str(world / 'server.jar'),
            port=25565,
            launch_args=['-Xmx1G'],
        )
    )
    assert gate.passed or gate.error_code in {'PORT_CONFLICT', 'JAVA_INCOMPATIBLE'}
    argv = build_launch_argv('java', ['-Xmx1G'], str(world / 'server.jar'), ['nogui'])
    assert argv[0] == 'java'
    assert 'server.jar' in argv[-2]

    assert parse_java_major('21.0.1+12-LTS') == 21
    assert capabilities_for('vanilla').save_coordination == 'rcon'
    assert target_level_for('vanilla') is not None
    state = build_state(process_alive=True, port=25565, rcon_ready=True, host_is_minecraft=True, port_timeout_s=0.1)
    assert evaluate(server_type='vanilla', caps=capabilities_for('vanilla'), state=state) is not None
    assert ping_protocol('127.0.0.1', 1, timeout_s=0.01) in {True, False}
    assert validate_properties({'server-port': 25565, 'max-players': 20}, 'vanilla', '1.21').valid
    assert 'server-port' in CORE_MANAGER_PROPERTIES


def test_store_secrets_and_operation_smoke(tmp_path):
    container = _container(tmp_path)
    keyfile = tmp_path / 'secrets.key'
    assert provision_keyfile(keyfile).exists()
    secrets = SqliteSecretsStore(container.store, keyfile)
    secret_id = secrets.store(
        secret_type='user_password',
        associated_entity_type='user',
        associated_entity_id='u1',
        plaintext='secret',
    )
    assert secrets.read(secret_id) == 'secret'
    rotated = secrets.rotate(secret_id, new_plaintext='new-secret', associated_entity_type='user', associated_entity_id='u1')
    assert secrets.read(rotated) == 'new-secret'

    op = container.operations.create(
        OperationInput(
            op_type=OperationType.START,
            actor_type=ActorType.SYSTEM,
            world_id='w1',
            idempotency_key='op-1',
            data={'x': 1},
        )
    )
    assert op['world_id'] == 'w1'
    assert container.operations.has_in_flight_operation('w1')
    container.operations.transition(op['op_id'], OperationStatus.COMPLETED)
    assert container.operations.list_incomplete() == []


def test_backup_cleanup_and_config_smoke(tmp_path):
    container = _container(tmp_path)
    source = tmp_path / 'world-src'
    source.mkdir()
    (source / 'level.dat').write_text('data', encoding='utf-8')
    backup_dir = tmp_path / 'backups'
    result = container.backups.create_world_backup(
        world_id='w1',
        world_dir=source,
        backup_dir=backup_dir,
        operation_id='op-backup',
        category=TriggerType.MANUAL,
    )
    assert result.artifact_id.startswith('ba_')
    assert result.storage_path.endswith('.zip')
    assert container.backups.validate_artifact(result.artifact_id)['artifact_id'] == result.artifact_id

    candidates = container.cleanup.backup_candidates(older_than_days=1)
    if candidates:
        deleted = container.cleanup.execute_backup_cleanup(candidates)
        assert deleted >= 0

    row = {
        'settings_id': 'settings-1',
        'timezone': 'UTC',
        'idle_countdown_seconds': 300,
        'minecraft_root_path': str(tmp_path),
        'backup_root_path': str(tmp_path),
        'log_root_path': str(tmp_path),
        'offsite_sync_defaults': '{}',
        'updated_at': 1,
        'updated_by': 'u1',
        'version': 1,
    }
    container.store.writer().execute(
        'INSERT INTO global_settings (settings_id, timezone, idle_countdown_seconds, minecraft_root_path, backup_root_path, log_root_path, offsite_sync_defaults, version, updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (row['settings_id'], row['timezone'], row['idle_countdown_seconds'], row['minecraft_root_path'], row['backup_root_path'], row['log_root_path'], row['offsite_sync_defaults'], row['version'], row['updated_at'], row['updated_by']),
    )
    container.store.writer().commit()
    updated = container.configuration.update_versioned(
        VersionedUpdate(
            entity=ConfigEditEntity.GLOBAL_SETTINGS,
            row_id='settings-1',
            expected_version=1,
            fields={'timezone': 'UTC+1'},
        )
    )
    assert updated['timezone'] == 'UTC+1'


def test_notifications_realtime_and_shell_smoke(tmp_path):
    container = _container(tmp_path)
    notification_id = container.notifications.publish(
        NotificationInput(
            category='security',
            severity=NotificationSeverity.HIGH,
            message='hello',
            requires_action=True,
        )
    )
    container.notifications.mark_read(notification_id, 'u1')
    container.notifications.dismiss(notification_id, 'u2')
    rows = container.notifications.list_for_user('u1')
    assert any(row['notification_id'] == notification_id for row in rows)

    hub = RealtimeHub()
    log_fanout = LogFanout(hub)
    event = log_fanout.append(world_id='w1', session_id='s1', channel='stdout', line='hello', ts=1)
    assert 'log.line' in event.event
    assert hub.replay('world:w1:logs', last_event_id=None)  # smoke only

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.extensions['mcmanager_container'] = container
    register_api_blueprints(app)
    app.register_blueprint(shell_bp)
    client = app.test_client()
    assert client.get('/api/pages').status_code == 200
    assert client.get('/api/health').status_code in {200, 503}
    assert client.get('/pages/home').status_code == 200
    assert client.get('/api/pages/home').status_code == 200


def test_runtime_world_and_diag_smoke(tmp_path):
    container = _container(tmp_path)
    row = {
        'world_id': 'w1',
        'display_name': 'alpha',
        'template_id': 'tpl-1',
        'server_type': 'vanilla',
        'mc_version': '1.21',
        'java_runtime_id': 'java-1',
        'port': 25565,
        'addressing_strategy': 'port',
        'addressing_value': '25565',
        'state': 'off',
        'pre_backup_state': None,
        'launch_args': json.dumps({'java_args': ['-Xmx1G'], 'server_args': ['nogui']}),
        'metadata_version': 1,
        'deleted_at': None,
        'deleted_by': None,
        'created_at': 1,
        'updated_at': 1,
    }
    container.store.writer().execute(
        'INSERT INTO templates (template_id, name, category, default_version, config_defaults, source, deprecated, version, deleted_at, deleted_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, 1, NULL, NULL, 1, 1)',
        ('tpl-1', 'base', 'standard', '1.21', '{}', 'built_in'),
    )
    container.store.writer().execute(
        'INSERT INTO java_runtimes (runtime_id, label, executable_path, version_detected, status, deleted_at, deleted_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, NULL, NULL, 1, 1)',
        ('java-1', 'java', 'java', '21', 'verified'),
    )
    container.store.writer().execute(
        'INSERT INTO world_instances (world_id, display_name, template_id, server_type, mc_version, java_runtime_id, port, addressing_strategy, addressing_value, state, pre_backup_state, launch_args, metadata_version, deleted_at, deleted_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)',
        (
            row['world_id'], row['display_name'], row['template_id'], row['server_type'], row['mc_version'], row['java_runtime_id'], row['port'], row['addressing_strategy'], row['addressing_value'], row['state'], row['pre_backup_state'], row['launch_args'], row['metadata_version'], row['created_at'], row['updated_at'],
        ),
    )
    container.store.writer().commit()

    summary = container.worlds.world_summary('w1')
    assert summary['world_id'] == 'w1'
    assert container.worlds.list_worlds()[0]['world_id'] == 'w1'

    audit_id = container.audit.write(event_type='user_login_success', actor=ActorSnapshot(actor_type=ActorType.USER, user_id='u1', username='alice'), payload={'ok': True})
    assert audit_id.startswith('au_')
    assert container.scheduler.tick() is not None
    assert container.diagnostics.health()['status'] == 'ok'
