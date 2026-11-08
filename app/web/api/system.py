"""System health, diagnostics, and world control routes."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict
from typing import Any

from flask import Blueprint, Response, current_app, g, request

from app.commands.world import WorldLifecycleCommands
from app.domain.value_objects import OperationStatus, OperationType, ServerType, WorldState
from app.services.diagnostics import DiagnosticsService
from app.services.operations import OperationNotCancellableError, OperationStateError
from app.services.worlds import (
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


def _operation_payload(operation: dict[str, Any]) -> dict[str, Any]:
    payload = dict(operation)
    if payload.get('data_json'):
        try:
            payload['data'] = json.loads(payload['data_json'])
        except (TypeError, json.JSONDecodeError):
            payload['data'] = None
    return payload


def _action_operation(
    operation: dict[str, Any],
    *,
    idempotency_key: str,
    replayed: bool,
) -> tuple[Response, int]:
    operation = _operation_payload(operation)
    op_id = operation['op_id']
    return ok(
        {'operation': operation},
        status=200 if replayed else 202,
        meta={
            'op_id': op_id,
            'idempotency_key': operation.get('idempotency_key') or idempotency_key,
        },
    )


def _request_idempotency_key() -> str | None:
    key = request.headers.get('Idempotency-Key')
    if key is None:
        return uuid.uuid4().hex
    key = key.strip()
    return key or None


@system_bp.get('/health')
def health():
    """Return the public, non-sensitive service health summary."""
    health_status = DiagnosticsService(_container()).health()
    return ok(health_status, status=200 if health_status['db'] == 'ok' else 503)


@system_bp.get('/diagnostics')
def diagnostics():
    diagnostics_service = DiagnosticsService(_container())
    return ok(diagnostics_service.diagnostics())


@system_bp.get('/system/stats')
def system_stats():
    container = _container()
    snapshot = container.metrics.stream_snapshot()
    return ok(snapshot['metrics'], meta={'freshness': snapshot['freshness']})


@system_bp.get('/worlds')
def list_worlds():
    state = request.args.get('state')
    server_type = request.args.get('server_type')
    mc_version = request.args.get('mc_version')
    search = request.args.get('search')
    include_deleted_value = request.args.get('include_deleted', 'false')
    limit_value = request.args.get('limit', '50')
    offset_value = request.args.get('offset', '0')
    if state is not None and state not in {item.value for item in WorldState}:
        return error(
            'VALIDATION_ERROR',
            'Unsupported world state filter.',
            details={'fields': {'state': state}},
        )
    if server_type is not None and server_type not in {item.value for item in ServerType}:
        return error(
            'VALIDATION_ERROR',
            'Unsupported server type filter.',
            details={'fields': {'server_type': server_type}},
        )
    if include_deleted_value not in {'true', 'false'}:
        return error(
            'VALIDATION_ERROR',
            'include_deleted must be true or false.',
            details={'fields': {'include_deleted': include_deleted_value}},
        )
    if not re.fullmatch(r'\d+', limit_value) or not re.fullmatch(r'\d+', offset_value):
        return error('VALIDATION_ERROR', 'limit and offset must be non-negative integers.')
    limit = int(limit_value)
    offset = int(offset_value)
    if not 1 <= limit <= 500:
        return error(
            'VALIDATION_ERROR',
            'limit must be between 1 and 500.',
            details={'fields': {'limit': limit_value}},
        )
    worlds, total = _container().worlds.query_worlds(
        state=state,
        server_type=server_type,
        mc_version=mc_version,
        search=search,
        include_deleted=include_deleted_value == 'true',
        limit=limit,
        offset=offset,
    )
    return ok(
        {'worlds': worlds},
        meta={'pagination': {'limit': limit, 'offset': offset, 'total': total}},
    )


@system_bp.get('/worlds/<world_id>')
def get_world(world_id: str):
    container = _container()
    row = container.store.reader().execute(
        'SELECT * FROM world_instances WHERE world_id = ? AND deleted_at IS NULL',
        (world_id,),
    ).fetchone()
    if row is None:
        return error('NOT_FOUND', 'World not found.', status=404)
    world = container.worlds.world_summary(world_id)
    last_backup = container.store.reader().execute(
        """
        SELECT artifact_id, category, size_bytes, created_at
        FROM backup_artifacts
        WHERE world_id = ? AND deleted_at IS NULL
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (world_id,),
    ).fetchone()
    return ok(
        {
            'world': world,
            'capabilities': asdict(
                container.minecraft_adapter.capabilities_for(ServerType(row['server_type']))
            ),
            'last_backup': dict(last_backup) if last_backup is not None else None,
        }
    )


@system_bp.get('/operations/<op_id>')
def get_operation(op_id: str):
    operation = _container().operations.get(op_id)
    if operation is None:
        return error('OP_NOT_FOUND', 'Operation not found.', status=404)
    return ok({'operation': _operation_payload(operation)})


def _operation_sort() -> tuple[tuple[str, bool], ...] | None:
    sort_value = request.args.get('sort', '-created_at')
    sort: list[tuple[str, bool]] = []
    allowed = {'created_at', 'op_type', 'status', 'world_id', 'actor_user_id'}
    for item in sort_value.split(','):
        descending = item.startswith('-')
        field = item[1:] if descending else item
        if field not in allowed:
            return None
        sort.append((field, descending))
    return tuple(sort) if sort else None


def _list_operations(*, world_id: str | None = None):
    args = request.args
    requested_world_id = world_id if world_id is not None else args.get('world_id')
    op_type = args.get('op_type')
    status = args.get('status')
    actor_user_id = args.get('actor_user_id')
    if op_type is not None and op_type not in {item.value for item in OperationType}:
        return error('VALIDATION_ERROR', 'Unsupported operation type filter.')
    if status is not None and status not in {item.value for item in OperationStatus}:
        return error('VALIDATION_ERROR', 'Unsupported operation status filter.')
    sort = _operation_sort()
    if sort is None:
        return error('VALIDATION_ERROR', 'Unsupported operation sort field.')
    limit_value = args.get('limit', '50')
    offset_value = args.get('offset', '0')
    if not limit_value.isdigit() or not offset_value.isdigit():
        return error('VALIDATION_ERROR', 'limit and offset must be non-negative integers.')
    limit, offset = int(limit_value), int(offset_value)
    if not 1 <= limit <= 500:
        return error('VALIDATION_ERROR', 'limit must be between 1 and 500.')
    try:
        operations, total = _container().operations.list_operations(
            world_id=requested_world_id,
            op_type=op_type,
            status=status,
            actor_user_id=actor_user_id,
            limit=limit,
            offset=offset,
            sort=sort,
        )
    except ValueError:
        return error('VALIDATION_ERROR', 'Unsupported operation sort field.')
    return ok(
        {'operations': [_operation_payload(operation) for operation in operations]},
        meta={'pagination': {'limit': limit, 'offset': offset, 'total': total}},
    )


@system_bp.get('/operations')
def list_operations():
    return _list_operations()


@system_bp.get('/worlds/<world_id>/operations')
def list_world_operations(world_id: str):
    world = _container().store.reader().execute(
        'SELECT 1 FROM world_instances WHERE world_id = ? AND deleted_at IS NULL',
        (world_id,),
    ).fetchone()
    if world is None:
        return error('WORLD_NOT_FOUND', 'World not found.', status=404)
    return _list_operations(world_id=world_id)


@system_bp.post('/operations/<op_id>/cancel')
def cancel_operation(op_id: str):
    try:
        operation = _container().operations.cancel(op_id)
    except OperationStateError:
        return error('OP_NOT_FOUND', 'Operation not found.', meta={'op_id': op_id})
    except OperationNotCancellableError:
        return error(
            'OP_NOT_CANCELLABLE',
            'Operation cannot be cancelled in its current state.',
            details={'op_id': op_id},
            meta={'op_id': op_id},
        )
    return ok(
        {'operation': _operation_payload(operation)},
        meta={'op_id': op_id},
    )


@system_bp.post('/worlds/<world_id>/start')
def world_start(world_id: str):
    idempotency_key = _request_idempotency_key()
    if idempotency_key is None:
        return error('VALIDATION_ERROR', 'Idempotency-Key must not be empty.', status=400)
    try:
        operation, replayed = WorldLifecycleCommands(_container().worlds).enqueue(
            op_type=OperationType.START,
            world_id=world_id,
            actor_user_id=g.current_user_id,
            idempotency_key=idempotency_key,
        )
    except WorldNotFoundError:
        return error('NOT_FOUND', 'World not found.', status=404)
    except WorldConflictError as exc:
        return error('WORLD_CONFLICT', str(exc), status=409)
    except WorldLifecycleError as exc:
        return error('START_FAILED', str(exc), status=422)
    return _action_operation(
        operation,
        idempotency_key=idempotency_key,
        replayed=replayed,
    )


@system_bp.post('/worlds/<world_id>/eula/accept')
def world_eula_accept(world_id: str):
    body = request.get_json(silent=True) or {}
    if body.get('accepted') is not True:
        return error(
            'VALIDATION_ERROR',
            'Explicit EULA acceptance is required.',
            status=400,
        )
    idempotency_key = _request_idempotency_key()
    if idempotency_key is None:
        return error('VALIDATION_ERROR', 'Idempotency-Key must not be empty.', status=400)
    try:
        operation, replayed = _container().worlds.accept_eula(
            world_id=world_id,
            actor_user_id=g.current_user_id,
            accepted=True,
            ip=request.remote_addr,
            idempotency_key=idempotency_key,
        )
    except WorldNotFoundError:
        return error('NOT_FOUND', 'World not found.', status=404)
    except WorldConflictError as exc:
        return error('WORLD_CONFLICT', str(exc), status=409)
    except WorldLifecycleError as exc:
        return error('EULA_ACCEPT_FAILED', str(exc), status=422)
    return ok(
        {'world_id': world_id, 'eula': 'accepted', 'operation': operation},
        status=200,
        meta={
            'op_id': operation['op_id'],
            'idempotency_key': operation.get('idempotency_key') or idempotency_key,
        },
    )


@system_bp.post('/worlds/<world_id>/stop')
def world_stop(world_id: str):
    idempotency_key = _request_idempotency_key()
    if idempotency_key is None:
        return error('VALIDATION_ERROR', 'Idempotency-Key must not be empty.', status=400)
    try:
        operation, replayed = WorldLifecycleCommands(_container().worlds).enqueue(
            op_type=OperationType.STOP,
            world_id=world_id,
            actor_user_id=g.current_user_id,
            idempotency_key=idempotency_key,
        )
    except WorldNotFoundError:
        return error('NOT_FOUND', 'World not found.', status=404)
    except WorldConflictError as exc:
        return error('WORLD_CONFLICT', str(exc), status=409)
    except WorldLifecycleError as exc:
        return error('STOP_FAILED', str(exc), status=422)
    return _action_operation(
        operation,
        idempotency_key=idempotency_key,
        replayed=replayed,
    )


@system_bp.post('/worlds/<world_id>/kill')
def world_kill(world_id: str):
    idempotency_key = _request_idempotency_key()
    if idempotency_key is None:
        return error('VALIDATION_ERROR', 'Idempotency-Key must not be empty.', status=400)
    try:
        operation, replayed = WorldLifecycleCommands(_container().worlds).enqueue(
            op_type=OperationType.KILL,
            world_id=world_id,
            actor_user_id=g.current_user_id,
            idempotency_key=idempotency_key,
        )
    except WorldNotFoundError:
        return error('NOT_FOUND', 'World not found.', status=404)
    except WorldConflictError as exc:
        return error('WORLD_CONFLICT', str(exc), status=409)
    except WorldLifecycleError as exc:
        return error('KILL_FAILED', str(exc), status=422)
    return _action_operation(
        operation,
        idempotency_key=idempotency_key,
        replayed=replayed,
    )


@system_bp.post('/supervisor/tick')
def supervisor_tick():
    """Manual supervisor tick (dev/test aid): crash-detect open sessions."""
    container = _container()
    crashed = _runtime().poll_running()
    return ok({'crashed': crashed, 'at': int(container.clock.now())})
