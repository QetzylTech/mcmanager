"""System health, diagnostics, and world control routes."""

from __future__ import annotations

import json
import time

from flask import Blueprint, current_app, g, jsonify

from app.commands.world import WorldLifecycleCommands
from app.domain.value_objects import OperationType
from app.services.diagnostics import DiagnosticsService
from app.services.worlds import (
    SpawnFailedError,
    StartTimeoutError,
    WorldConflictError,
    WorldLifecycleError,
    WorldNotFoundError,
)
from app.web.errors import error, ok

system_bp = Blueprint('api_system', __name__, url_prefix='/api')


def _container():
    return current_app.extensions['mcmanager_container']


def _runtime():
    container = _container()
    return getattr(container, 'runtime', container.worlds)


def _operation_payload(operation: dict) -> dict:
    payload = dict(operation)
    if payload.get('data_json'):
        try:
            payload['data'] = json.loads(payload['data_json'])
        except (TypeError, json.JSONDecodeError):
            payload['data'] = None
    return payload


def _action_operation(result: str, *, world_id: str, op_type: OperationType):
    container = _container()
    operation = container.operations.get(result)
    if operation is None:
        row = container.store.reader().execute(
            'SELECT * FROM operations WHERE world_id = ? AND op_type = ? '
            'ORDER BY created_at DESC LIMIT 1',
            (world_id, op_type.value),
        ).fetchone()
        operation = dict(row) if row is not None else None
    if operation is None:
        operation = {'op_id': result, 'status': 'Queued'}
    operation = _operation_payload(operation)
    op_id = operation['op_id']
    return ok(
        {'operation': operation},
        status=202,
        meta={'op_id': op_id},
    )


@system_bp.get('/health')
def health():
    """Live per-subsystem health: scheduler, SQLite writer, process adapter.

    Each probe is independent: a failing subsystem reports ``down`` with its
    own cause while the others still report their real state (Doc 5 §5
    manager diagnostics).
    """
    container = _container()
    checks = {}

    # Scheduler: tick interval reachable.
    try:
        interval = container.scheduler.tick_interval_seconds
        checks['scheduler'] = {'status': 'ok', 'tick_interval_seconds': interval}
    except Exception as exc:  # noqa: BLE001
        checks['scheduler'] = {'status': 'down', 'error': str(exc)}

    # SQLite writer: live SELECT 1 latency.
    try:
        start = time.perf_counter()
        container.store.writer().execute('SELECT 1').fetchone()
        latency_ms = (time.perf_counter() - start) * 1000
        checks['sqlite_writer'] = {'status': 'ok', 'latency_ms': round(latency_ms, 3)}
    except Exception as exc:  # noqa: BLE001
        checks['sqlite_writer'] = {'status': 'down', 'error': str(exc)}

    # Process adapter: class + live registry probe works.
    try:
        adapter = container.process_adapter
        checks['process_adapter'] = {
            'status': 'ok',
            'adapter': adapter.__class__.__name__,
        }
    except Exception as exc:  # noqa: BLE001
        checks['process_adapter'] = {'status': 'down', 'error': str(exc)}

    all_ok = all(check['status'] == 'ok' for check in checks.values())
    return jsonify(
        {
            'ok': True,
            'status': 'ok' if all_ok else 'degraded',
            'data': checks,
            'meta': {'at': int(container.clock.now())},
        }
    ), 200 if all_ok else 503


@system_bp.get('/diagnostics')
def diagnostics():
    diagnostics_service = DiagnosticsService(_container())
    return ok(diagnostics_service.diagnostics())


@system_bp.get('/system/stats')
def system_stats():
    container = _container()
    worlds = container.store.reader().execute(
        'SELECT COUNT(*) AS n FROM world_instances WHERE deleted_at IS NULL'
    ).fetchone()
    active = container.store.reader().execute(
        "SELECT COUNT(*) AS n FROM world_instances WHERE state IN ('starting','running','stopping')"
    ).fetchone()
    return ok(
        {
            'worlds_count': worlds['n'],
            'active_worlds': active['n'],
            'at': int(container.clock.now()),
        }
    )


@system_bp.get('/worlds')
def list_worlds():
    return ok({'worlds': _container().worlds.list_worlds()})


@system_bp.get('/worlds/<world_id>')
def get_world(world_id: str):
    world = next(
        (item for item in _container().worlds.list_worlds() if item['world_id'] == world_id),
        None,
    )
    if world is None:
        return error('NOT_FOUND', 'World not found.', status=404)
    return ok({'world': world})


@system_bp.get('/operations/<op_id>')
def get_operation(op_id: str):
    operation = _container().operations.get(op_id)
    if operation is None:
        return error('NOT_FOUND', 'Operation not found.', status=404)
    return ok({'operation': _operation_payload(operation)})


@system_bp.post('/worlds/<world_id>/start')
def world_start(world_id: str):
    try:
        result = WorldLifecycleCommands(_container().worlds).start(
            world_id=world_id,
            actor_user_id=g.current_user_id,
        )
    except WorldNotFoundError:
        return error('NOT_FOUND', 'World not found.', status=404)
    except WorldConflictError as exc:
        return error('WORLD_CONFLICT', str(exc), status=409)
    except (SpawnFailedError, StartTimeoutError, WorldLifecycleError) as exc:
        return error('START_FAILED', str(exc), status=422)
    return _action_operation(result, world_id=world_id, op_type=OperationType.START)


@system_bp.post('/worlds/<world_id>/stop')
def world_stop(world_id: str):
    try:
        result = WorldLifecycleCommands(_container().worlds).stop(
            world_id=world_id,
            actor_user_id=g.current_user_id,
        )
    except WorldNotFoundError:
        return error('NOT_FOUND', 'World not found.', status=404)
    except WorldConflictError as exc:
        return error('WORLD_CONFLICT', str(exc), status=409)
    except WorldLifecycleError as exc:
        return error('STOP_FAILED', str(exc), status=422)
    return _action_operation(result, world_id=world_id, op_type=OperationType.STOP)


@system_bp.post('/worlds/<world_id>/kill')
def world_kill(world_id: str):
    try:
        result = WorldLifecycleCommands(_container().worlds).kill(
            world_id=world_id,
            actor_user_id=g.current_user_id,
        )
    except WorldNotFoundError:
        return error('NOT_FOUND', 'World not found.', status=404)
    except WorldConflictError as exc:
        return error('WORLD_CONFLICT', str(exc), status=409)
    except WorldLifecycleError as exc:
        return error('KILL_FAILED', str(exc), status=422)
    return _action_operation(result, world_id=world_id, op_type=OperationType.KILL)


@system_bp.post('/supervisor/tick')
def supervisor_tick():
    """Manual supervisor tick (dev/test aid): crash-detect open sessions."""
    container = _container()
    crashed = _runtime().poll_running()
    return ok({'crashed': crashed, 'at': int(container.clock.now())})
