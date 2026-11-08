"""World lifecycle orchestration (Gate 3 — the Start/Stop/Kill driver).

``WorldsService`` is the only service that drives world state transitions
(off -> starting -> running -> stopping -> off, or -> crashed/error). It
composes the pre-launch gate (Doc 14 §4), the platform process adapter
(Doc 13), and the readiness hierarchy (Doc 14 §3) behind one durable
Operation row per state change (Doc 9 §1.1 derived world lock), and records
every launch/stop in ``runtime_sessions``.

The supervisor cadence (1s running / 15s idle, ``tuning.py``) is driven by
``poll_running()``; ``reconcile()`` is the boot path that re-attaches worlds
with an open ``runtime_sessions`` row after a manager crash (Doc 13 §5.1).
"""

from __future__ import annotations

import json
import logging
import secrets
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.entities import WorldInstance
from app.domain.lifecycle import (
    InvalidWorldTransition,
    WorldTransitionIntent,
    transition_world,
)
from app.domain.tuning import (
    START_READINESS_TIMEOUT_S,
    STOP_GRACEFUL_DEADLINE_S,
    SUPERVISOR_POLL_IDLE_S,
    SUPERVISOR_POLL_RUNNING_S,
)
from app.domain.value_objects import (
    ActorType,
    ConfigEditEntity,
    EndReason,
    EulaState,
    OperationStatus,
    OperationType,
    ServerReadinessLevel,
    ServerType,
    WorldState,
)
from app.ports.clock import Clock
from app.ports.minecraft import (
    GateResult,
    LaunchContext,
    MinecraftRconError,
    MinecraftRconPort,
    MinecraftServerPort,
    parse_properties,
)
from app.ports.persistence import PersistencePort
from app.ports.process_control import (
    ProbeFingerprint,
    ProcessControlPort,
    ProcessHandle,
    SpawnRequest,
)
from app.ports.secrets_store import SecretsStore, SecretType
from app.services.audit import AuditService
from app.services.configuration import ConfigurationConflictError, ConfigurationService
from app.services.operations import OperationInput, OperationService
from app.services.realtime import LogFanout, RealtimeHub

_RCON_PORT_OFFSET = 10
_logger = logging.getLogger(__name__)
_world_mutation_dispatch_lock = threading.Lock()


class WorldLifecycleError(Exception):
    """Base error for world lifecycle failures."""


class WorldNotFoundError(WorldLifecycleError):
    """No live world row for the given id."""


class WorldConflictError(WorldLifecycleError):
    """The requested transition conflicts with the world's current state."""


class StartTimeoutError(WorldLifecycleError):
    """The readiness ladder did not reach the target level in time."""


class SpawnFailedError(WorldLifecycleError):
    """The process adapter refused to spawn the world."""


@dataclass(frozen=True)
class LaunchRecord:
    """Everything captured at spawn time for a runtime session."""

    handle: ProcessHandle
    session_id: str
    rcon_password: str | None
    rcon_port: int | None


class WorldsService:
    """Composes gate + adapter + readiness ladder behind Operation rows."""

    def __init__(
        self,
        store: PersistencePort,
        clock: Clock,
        operations: OperationService,
        process_adapter: ProcessControlPort,
        secrets: SecretsStore,
        minecraft: MinecraftServerPort,
        logs: LogFanout | None = None,
        audit: AuditService | None = None,
        realtime: RealtimeHub | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._operations = operations
        self._adapter = process_adapter
        self._secrets = secrets
        self._minecraft = minecraft
        self._logs = logs
        self._audit = audit
        self._realtime = realtime

    # ------------------------------------------------------------------ start

    def enqueue_start(
        self,
        *,
        world_id: str,
        actor_type: ActorType,
        actor_user_id: str | None,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        existing = self._operations.get_by_idempotency_key(
            OperationType.START, idempotency_key
        )
        if existing is not None:
            return existing, True
        world = self._world(world_id)
        if world['state'] in (
            WorldState.STARTING.value,
            WorldState.RUNNING.value,
            WorldState.STOPPING.value,
        ):
            raise WorldConflictError(f'world {world_id} is already {world["state"]}')
        context = self._launch_context(world)
        gate = self._validate_launch(world, context)
        if not gate.passed:
            if gate.error_code == 'EULA_NOT_ACCEPTED':
                self._set_world_state(world_id, WorldState.EULA_REQUIRED)
            raise WorldLifecycleError(f'{gate.error_code}: {gate.detail}')
        return self._operations.create_with_replay(
            OperationInput(
                op_type=OperationType.START,
                actor_type=actor_type,
                world_id=world_id,
                actor_user_id=actor_user_id,
                idempotency_key=idempotency_key,
            )
        )

    def enqueue_stop(
        self,
        *,
        world_id: str,
        actor_type: ActorType,
        actor_user_id: str | None,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        existing = self._operations.get_by_idempotency_key(
            OperationType.STOP, idempotency_key
        )
        if existing is not None:
            return existing, True
        self._world(world_id)
        return self._operations.create_with_replay(
            OperationInput(
                op_type=OperationType.STOP,
                actor_type=actor_type,
                world_id=world_id,
                actor_user_id=actor_user_id,
                idempotency_key=idempotency_key,
            )
        )

    def enqueue_kill(
        self,
        *,
        world_id: str,
        actor_type: ActorType,
        actor_user_id: str | None,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        existing = self._operations.get_by_idempotency_key(
            OperationType.KILL, idempotency_key
        )
        if existing is not None:
            return existing, True
        self._world(world_id)
        return self._operations.create_with_replay(
            OperationInput(
                op_type=OperationType.KILL,
                actor_type=actor_type,
                world_id=world_id,
                actor_user_id=actor_user_id,
                idempotency_key=idempotency_key,
            )
        )

    def start(
        self,
        *,
        world_id: str,
        actor_type: ActorType = ActorType.USER,
        actor_user_id: str | None = None,
        _allow_world_conflict: bool = False,
        _operation_id: str | None = None,
    ) -> str:
        """Run the full Start ladder. Returns the handle's session_id."""
        # Fast-fail before consuming the derived world lock.
        pre = self._world(world_id)
        if pre["state"] in (
            WorldState.STARTING.value,
            WorldState.RUNNING.value,
            WorldState.STOPPING.value,
        ):
            raise WorldConflictError(f'world {world_id} is already {pre["state"]}')
        pre_context = self._launch_context(pre)
        pre_gate = self._validate_launch(pre, pre_context)
        if not pre_gate.passed:
            if pre_gate.error_code == "EULA_NOT_ACCEPTED":
                self._set_world_state(world_id, WorldState.EULA_REQUIRED)
            raise WorldLifecycleError(f"{pre_gate.error_code}: {pre_gate.detail}")

        if _operation_id is None:
            op = self._operations.create(
                OperationInput(
                    op_type=OperationType.START,
                    actor_type=actor_type,
                    world_id=world_id,
                    actor_user_id=actor_user_id,
                ),
                allow_world_conflict=_allow_world_conflict,
            )
            op_id = op["op_id"]
        else:
            op_id = _operation_id
        try:
            self._operations.transition(
                op_id, OperationStatus.RUNNING, checkpoint={"stage": "validating"}
            )
            world = self._world(world_id)
            if world["state"] in (
                WorldState.STARTING.value,
                WorldState.RUNNING.value,
                WorldState.STOPPING.value,
            ):
                # A concurrent transition won the race: release the lock.
                self._operations.transition(
                    op_id, OperationStatus.CANCELLED, message="conflict with current state"
                )
                raise WorldConflictError(f'world {world_id} is already {world["state"]}')

            context = self._launch_context(world)
            gate = self._validate_launch(world, context)
            if not gate.passed:
                self._fail_op(op_id, gate.error_code or "GATE_REJECTED", gate.detail)
                if gate.error_code == "EULA_NOT_ACCEPTED":
                    self._set_world_state(world_id, WorldState.EULA_REQUIRED)
                else:
                    self._set_world_state(world_id, WorldState.ERROR)
                raise WorldLifecycleError(f"{gate.error_code}: {gate.detail}")

            rcon_port, rcon_password = self._provision_rcon(context, world_id)
            argv = self._launch_command(world, context)
            session_id = f"rs_{uuid.uuid4().hex[:16]}"
            self._set_world_state(world_id, WorldState.QUEUED)
            self._set_world_state(world_id, WorldState.STARTING)
            result = self._adapter.spawn(
                SpawnRequest(
                    world_id=world_id,
                    launch_command=argv,
                    cwd=context.world_dir,
                    env={},
                    session_id=session_id,
                    log_dir=str(self._log_root(world_id) / world_id),
                )
            )
            if result.handle is None:
                self._fail_op(op_id, "SPAWN_FAILED", result.spawn_error)
                self._set_world_state(world_id, WorldState.ERROR)
                raise SpawnFailedError(result.spawn_error or "spawn failed")

            session_id = self._open_session(
                world_id=world_id,
                world=world,
                context=context,
                handle=result.handle,
                argv=argv,
                rcon_port=rcon_port,
                rcon_password=rcon_password,
                session_id=session_id,
            )
            if self._logs is not None:
                self._attach_log_sink(world_id, result.handle)

            readiness = self._await_readiness(
                world_id=world_id,
                world=world,
                handle=result.handle,
                rcon_port=rcon_port,
                rcon_password=rcon_password,
            )
            self._set_world_state(world_id, WorldState.RUNNING)
            self._operations.transition(
                op_id,
                OperationStatus.COMPLETED,
                checkpoint={
                    "stage": "running",
                    "readiness": readiness,
                    "session_id": session_id,
                },
                data={"session_id": session_id},
            )
            return session_id
        except StartTimeoutError as exc:
            self._close_session(world_id, EndReason.CRASHED)
            self._set_world_state(world_id, WorldState.ERROR)
            self._operations.transition(
                op_id,
                OperationStatus.TIMED_OUT,
                error_code="START_TIMEOUT",
                message=str(exc),
            )
            raise
        except WorldLifecycleError:
            raise
        except Exception as exc:
            self._fail_op(op_id, "START_ERROR", str(exc))
            self._set_world_state(world_id, WorldState.ERROR)
            raise WorldLifecycleError(str(exc)) from exc

    def _await_readiness(
        self,
        *,
        world_id: str,
        world: dict[str, Any],
        handle: ProcessHandle,
        rcon_port: int | None,
        rcon_password: str | None,
    ) -> str:
        server_type = ServerType(world["server_type"])
        target = self._minecraft.target_readiness_level(server_type)
        caps = self._minecraft.capabilities_for(server_type)
        port = int(world["port"])
        deadline = time.monotonic() + START_READINESS_TIMEOUT_S
        rcon: MinecraftRconPort | None = None
        rcon_ready = False
        operationally_valid = False

        while time.monotonic() < deadline:
            status = self._adapter.poll(handle)
            if not status.alive:
                raise StartTimeoutError(
                    f"world {world_id} process exited before ready: {status.exit_class.value}"
                )
            if rcon_port and rcon_password:
                if rcon is None:
                    rcon = self._rcon_client(rcon_port, rcon_password)
                    try:
                        rcon.connect()
                        rcon_ready = rcon.ping()
                    except MinecraftRconError:
                        rcon.close()
                        rcon = None
                elif not rcon_ready:
                    try:
                        rcon_ready = rcon.ping()
                    except MinecraftRconError:
                        rcon_ready = False
                        rcon.close()
                        rcon = None
                if (
                    rcon is not None
                    and rcon_ready
                    and target is ServerReadinessLevel.OPERATIONALLY_VALID
                ):
                    try:
                        operationally_valid = bool(rcon.command("list").strip())
                        if server_type is ServerType.PAPER and caps.paper_api:
                            operationally_valid = operationally_valid and bool(
                                rcon.command("tps").strip()
                            )
                    except MinecraftRconError:
                        operationally_valid = False
            state = self._minecraft.build_readiness_state(
                process_alive=True,
                port=port,
                rcon_ready=rcon_ready,
                operationally_valid=operationally_valid,
                host_is_minecraft=True,
                port_timeout_s=0.5,
            )
            level = self._minecraft.evaluate_readiness(
                server_type=server_type,
                caps=caps,
                state=state,
            )
            if level.rank >= target.rank:
                if rcon is not None:
                    rcon.close()
                return level.value
            time.sleep(0.25)

        if rcon is not None:
            rcon.close()
        self._teardown(handle, graceful_deadline_s=0)
        raise StartTimeoutError(f"world {world_id} did not reach {target.value} in time")

    def accept_eula(
        self,
        *,
        world_id: str,
        actor_user_id: str,
        accepted: bool,
        ip: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Record explicit operator acceptance before writing ``eula=true``."""
        if accepted is not True:
            raise WorldLifecycleError("explicit EULA acceptance is required")
        if not actor_user_id:
            raise WorldLifecycleError("EULA acceptance requires an operator identity")
        if self._audit is None:
            raise WorldLifecycleError("EULA acceptance audit is unavailable")
        if idempotency_key is not None:
            existing = self._operations.get_by_idempotency_key(
                OperationType.CONFIG_EDIT, idempotency_key
            )
            if existing is not None:
                return existing, True
        world = self._world(world_id)
        if world["state"] != WorldState.EULA_REQUIRED.value:
            raise WorldConflictError("world is not awaiting EULA acceptance")
        payload: dict[str, Any] = {
            "entity": ConfigEditEntity.EULA.value,
            "row_id": world_id,
            "before": {"accepted": False},
            "after": {"accepted": True},
        }
        operation, replayed = self._operations.create_with_replay(
            OperationInput(
                op_type=OperationType.CONFIG_EDIT,
                actor_type=ActorType.USER,
                actor_user_id=actor_user_id,
                world_id=world_id,
                idempotency_key=idempotency_key,
                data=payload,
            )
        )
        if replayed:
            return operation, True
        op_id = operation["op_id"]
        self._operations.transition(op_id, OperationStatus.RUNNING)
        try:
            actor = self._audit.snapshot_for_user(
                user_id=actor_user_id,
                device_id=None,
                device_name=None,
                ip=ip,
            )
            self._audit.write(
                event_type="world_eula_accepted",
                actor=actor,
                world_id=world_id,
                payload={"accepted": True},
            )
            self._minecraft.accept_eula(str(self._world_dir(world)), actor_user_id)
            self._set_world_state(
                world_id,
                WorldState.OFF,
                intent=WorldTransitionIntent.EULA_ACCEPTANCE,
            )
            self._operations.transition(
                op_id,
                OperationStatus.COMPLETED,
                data=payload,
            )
            result = self._operations.get(op_id)
            if result is None:
                raise WorldLifecycleError("EULA acceptance operation disappeared.")
            return result, False
        except Exception as exc:
            self._operations.transition(
                op_id,
                OperationStatus.FAILED,
                error_code="EULA_ACCEPTANCE_FAILED",
                message=str(exc),
                data=payload,
            )
            raise

    def _validate_launch(
        self, world: dict[str, Any], context: LaunchContext
    ) -> GateResult:
        """Require both the live EULA file and audited acceptance."""
        eula_state = self._minecraft.detect_eula(context.world_dir)
        if eula_state is not EulaState.ACCEPTED:
            return GateResult(
                passed=False,
                error_code="EULA_NOT_ACCEPTED",
                detail="eula.txt not accepted",
                eula_state=eula_state,
            )
        audited = self._store.reader().execute(
            "SELECT 1 FROM audit_records "
            "WHERE world_id = ? AND event_type = 'world_eula_accepted' LIMIT 1",
            (world["world_id"],),
        ).fetchone()
        if audited is None:
            return GateResult(
                passed=False,
                error_code="EULA_NOT_ACCEPTED",
                detail="EULA acceptance has not been audited",
                eula_state=EulaState.UNACCEPTED,
            )
        return self._minecraft.validate_launch(context)

    # ------------------------------------------------------------------- stop

    def stop(
        self,
        *,
        world_id: str,
        actor_type: ActorType = ActorType.USER,
        actor_user_id: str | None = None,
        _operation_id: str | None = None,
    ) -> str:
        """Graceful stop ladder: stdin stop -> RCON stop -> terminate(60s)."""
        self._world(world_id)
        if _operation_id is None:
            op = self._operations.create(
                OperationInput(
                    op_type=OperationType.STOP,
                    actor_type=actor_type,
                    world_id=world_id,
                    actor_user_id=actor_user_id,
                )
            )
            op_id = op["op_id"]
        else:
            op_id = _operation_id
        try:
            self._operations.transition(
                op_id, OperationStatus.RUNNING, checkpoint={"stage": "stopping"}
            )
            self._set_world_state(world_id, WorldState.STOPPING)
            closed = self._attempt_graceful_stop(world_id)
            self._close_session(
                world_id, EndReason.GRACEFUL_STOP if closed else EndReason.FORCED_STOP
            )
            self._set_world_state(world_id, WorldState.OFF)
            self._operations.transition(
                op_id, OperationStatus.COMPLETED, checkpoint={"stage": "off", "graceful": closed}
            )
            return str(op_id)
        except Exception as exc:
            self._fail_op(op_id, "STOP_ERROR", str(exc))
            raise WorldLifecycleError(str(exc)) from exc

    def _attempt_graceful_stop(self, world_id: str) -> bool:
        handle = self._resolve_handle(world_id)
        if handle is None:
            return True
        try:
            self._rcon_command_quiet(world_id, "stop")
            if self._wait_exit(handle, STOP_GRACEFUL_DEADLINE_S):
                return True
        except MinecraftRconError:
            pass
        if self._adapter.write_stdin(handle, "stop").delivered and self._wait_exit(
            handle, STOP_GRACEFUL_DEADLINE_S
        ):
            return True
        outcome = self._adapter.terminate(handle, graceful_deadline_s=STOP_GRACEFUL_DEADLINE_S)
        return bool(outcome.resolved and "grace" in outcome.exit_class.value)

    # ------------------------------------------------------------------- kill

    def kill(
        self,
        *,
        world_id: str,
        actor_type: ActorType = ActorType.USER,
        actor_user_id: str | None = None,
        _operation_id: str | None = None,
    ) -> str:
        """Immediate forced termination (graceful_deadline_s=0, C3)."""
        self._world(world_id)
        if _operation_id is None:
            op = self._operations.create(
                OperationInput(
                    op_type=OperationType.KILL,
                    actor_type=actor_type,
                    world_id=world_id,
                    actor_user_id=actor_user_id,
                )
            )
            op_id = op["op_id"]
        else:
            op_id = _operation_id
        try:
            self._operations.transition(
                op_id, OperationStatus.RUNNING, checkpoint={"stage": "killing"}
            )
            self._set_world_state(world_id, WorldState.STOPPING)
            handle = self._resolve_handle(world_id)
            if handle is not None:
                self._adapter.terminate(handle, graceful_deadline_s=0)
            self._close_session(world_id, EndReason.FORCED_STOP)
            self._set_world_state(world_id, WorldState.OFF)
            self._operations.transition(
                op_id, OperationStatus.COMPLETED, checkpoint={"stage": "off"}
            )
            return str(op_id)
        except Exception as exc:
            self._fail_op(op_id, "KILL_ERROR", str(exc))
            raise WorldLifecycleError(str(exc)) from exc

    def dispatch_queued_operations(self) -> list[str]:
        """Resume persisted world lifecycle operations from the durable queue."""
        dispatched: list[str] = []
        seen_worlds: set[str] = set()
        queued = self._operations.list_queued(
            (OperationType.START, OperationType.STOP, OperationType.KILL)
        )
        for operation in queued:
            world_id = operation['world_id']
            if world_id is not None:
                if world_id in seen_worlds:
                    continue
                seen_worlds.add(world_id)
                if self._operations.has_active_operation(
                    world_id, exclude_op_id=operation['op_id']
                ):
                    continue
            claimed = self._operations.claim_queued(operation['op_id'])
            if claimed is None:
                continue
            op_id = claimed['op_id']
            dispatched.append(op_id)
            try:
                op_type = OperationType(claimed['op_type'])
                if world_id is None:
                    raise WorldLifecycleError(
                        f'{op_type.value} operation is missing a world id'
                    )
                actor_type = ActorType(claimed['actor_type'])
                actor_user_id = claimed['actor_user_id']
                if op_type is OperationType.START:
                    self.start(
                        world_id=world_id,
                        actor_type=actor_type,
                        actor_user_id=actor_user_id,
                        _operation_id=op_id,
                    )
                elif op_type is OperationType.STOP:
                    self.stop(
                        world_id=world_id,
                        actor_type=actor_type,
                        actor_user_id=actor_user_id,
                        _operation_id=op_id,
                    )
                else:
                    self.kill(
                        world_id=world_id,
                        actor_type=actor_type,
                        actor_user_id=actor_user_id,
                        _operation_id=op_id,
                    )
            except Exception as exc:
                current = self._operations.get(op_id)
                if current is not None and current['status'] not in {
                    OperationStatus.COMPLETED.value,
                    OperationStatus.FAILED.value,
                    OperationStatus.CANCELLED.value,
                    OperationStatus.TIMED_OUT.value,
                }:
                    self._operations.transition(
                        op_id,
                        OperationStatus.FAILED,
                        error_code='OP_EXECUTION_FAILED',
                        message=str(exc),
                    )
                _logger.exception('Queued world operation failed: %s', op_id)
        dispatched.extend(self.dispatch_queued_world_mutations())
        return dispatched

    def enqueue_world_mutation(
        self,
        *,
        op_type: OperationType,
        world_id: str | None,
        actor_user_id: str,
        idempotency_key: str,
        data: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Persist a world-management request before returning its HTTP 202."""
        return self._operations.create_with_replay(
            OperationInput(
                op_type=op_type,
                actor_type=ActorType.USER,
                actor_user_id=actor_user_id,
                world_id=world_id,
                idempotency_key=idempotency_key,
                data=data,
            ),
            initial_status=OperationStatus.QUEUED,
            allow_world_conflict=op_type
            in (OperationType.CONFIG_EDIT, OperationType.DELETE_WORLD),
        )

    def dispatch_queued_world_mutations(self) -> list[str]:
        """Apply queued create/delete/runtime-config requests and recover interrupted writes."""
        if not _world_mutation_dispatch_lock.acquire(blocking=False):
            return []
        dispatched: list[str] = []
        try:
            rows = self._store.reader().execute(
                """
                SELECT * FROM operations
                WHERE op_type IN (?, ?, ?)
                  AND status IN (?, ?)
                ORDER BY created_at ASC, op_id ASC
                """,
                (
                    OperationType.CREATE_WORLD.value,
                    OperationType.DELETE_WORLD.value,
                    OperationType.CONFIG_EDIT.value,
                    OperationStatus.QUEUED.value,
                    OperationStatus.RUNNING.value,
                ),
            ).fetchall()
            for record in rows:
                operation = dict(record)
                try:
                    data = json.loads(operation.get("data_json") or "{}")
                except (TypeError, json.JSONDecodeError):
                    continue
                action = data.get("world_action")
                if operation["op_type"] == OperationType.CONFIG_EDIT.value:
                    if data.get("queued_runtime_config"):
                        action = "runtime_config"
                    elif data.get("queued_file_edit"):
                        action = "file_edit"
                    else:
                        continue
                if action not in {"create", "delete", "runtime_config", "file_edit"}:
                    continue
                if operation["status"] == OperationStatus.QUEUED.value:
                    claimed = self._operations.claim_queued(operation["op_id"])
                    if claimed is None:
                        continue
                    operation = claimed
                dispatched.append(operation["op_id"])
                try:
                    if action == "create":
                        result = self._apply_queued_world_create(operation, data)
                    elif action == "delete":
                        result = self._apply_queued_world_delete(operation, data)
                    elif action == "file_edit":
                        result = self._apply_queued_file_edit(operation, data)
                    else:
                        result = self._apply_queued_runtime_config(operation, data)
                    self._operations.transition(
                        operation["op_id"], OperationStatus.COMPLETED, data=result
                    )
                except Exception as exc:
                    code = (
                        "CONFIG_VERSION_CONFLICT"
                        if isinstance(exc, ConfigurationConflictError)
                        else "OP_EXECUTION_FAILED"
                    )
                    try:
                        self._operations.transition(
                            operation["op_id"],
                            OperationStatus.FAILED,
                            error_code=code,
                            message=str(exc),
                        )
                    except Exception:
                        _logger.exception(
                            "Could not terminalize world mutation %s",
                            operation["op_id"],
                        )
                    _logger.exception(
                        "Queued world mutation failed: %s", operation["op_id"]
                    )
        finally:
            _world_mutation_dispatch_lock.release()
        return dispatched

    def _apply_queued_world_create(
        self, operation: dict[str, Any], data: dict[str, Any]
    ) -> dict[str, Any]:
        world = data["world"]
        connection = self._store.writer()
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                "SELECT * FROM world_instances WHERE world_id = ?", (world["world_id"],)
            ).fetchone()
            if row is None:
                columns = tuple(world)
                connection.execute(
                    f"INSERT INTO world_instances ({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' for _ in columns)})",
                    tuple(world[column] for column in columns),
                )
            elif any(row[key] != value for key, value in world.items()):
                raise WorldConflictError("world create operation does not match persisted world")
            connection.execute(
                "UPDATE operations SET world_id = ? WHERE op_id = ? AND world_id IS NULL",
                (world["world_id"], operation["op_id"]),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return {"world_id": world["world_id"]}

    def _apply_queued_world_delete(
        self, operation: dict[str, Any], data: dict[str, Any]
    ) -> dict[str, Any]:
        world_id = operation["world_id"]
        expected_version = data["preview_version"]
        now = int(self._clock.now())
        connection = self._store.writer()
        connection.execute("BEGIN IMMEDIATE")
        try:
            world = connection.execute(
                "SELECT * FROM world_instances WHERE world_id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise WorldNotFoundError(world_id)
            if (
                world["deleted_at"] is not None
                and world["deleted_by"] == operation["actor_user_id"]
                and world["metadata_version"] == expected_version + 1
            ):
                connection.commit()
                return {"world_id": world_id, "deleted": True}
            if (
                world["deleted_at"] is not None
                or world["state"] != WorldState.OFF.value
                or world["metadata_version"] != expected_version
            ):
                raise ConfigurationConflictError("World changed after deletion preview.")
            cursor = connection.execute(
                """
                UPDATE world_instances
                SET deleted_at = ?, deleted_by = ?, metadata_version = metadata_version + 1,
                    updated_at = ?
                WHERE world_id = ? AND deleted_at IS NULL AND state = 'off'
                  AND metadata_version = ?
                """,
                (now, operation["actor_user_id"], now, world_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise ConfigurationConflictError("World changed after deletion preview.")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return {"world_id": world_id, "deleted": True}

    def _apply_queued_runtime_config(
        self, operation: dict[str, Any], data: dict[str, Any]
    ) -> dict[str, Any]:
        world_id = operation["world_id"]
        expected_version = data["expected_version"]
        after = data["after"]
        now = int(self._clock.now())
        connection = self._store.writer()
        connection.execute("BEGIN IMMEDIATE")
        try:
            world = connection.execute(
                "SELECT * FROM world_instances WHERE world_id = ? AND deleted_at IS NULL",
                (world_id,),
            ).fetchone()
            if world is None:
                raise WorldNotFoundError(world_id)
            if (
                world["metadata_version"] == expected_version + 1
                and all(world[key] == value for key, value in after.items())
            ):
                connection.commit()
                return {
                    "entity": ConfigEditEntity.WORLD_INSTANCES.value,
                    "row_id": world_id,
                    "before": data["before"],
                    "after": after,
                }
            if world["metadata_version"] != expected_version:
                raise ConfigurationConflictError("CONFIG_VERSION_CONFLICT")
            if world["state"] != WorldState.OFF.value:
                raise WorldConflictError("Runtime configuration requires an off world.")
            assignments = [f"{column} = ?" for column in after]
            assignments.extend(
                ("metadata_version = metadata_version + 1", "updated_at = ?")
            )
            values = [*after.values(), now, world_id, expected_version]
            cursor = connection.execute(
                f"UPDATE world_instances SET {', '.join(assignments)} "
                "WHERE world_id = ? AND metadata_version = ? AND deleted_at IS NULL",
                values,
            )
            if cursor.rowcount != 1:
                raise ConfigurationConflictError("CONFIG_VERSION_CONFLICT")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return {
            "entity": ConfigEditEntity.WORLD_INSTANCES.value,
            "row_id": world_id,
            "before": data["before"],
            "after": after,
        }

    def _apply_queued_file_edit(
        self, operation: dict[str, Any], data: dict[str, Any]
    ) -> dict[str, Any]:
        root = Path(data["world_root"]).resolve()
        source_relative = Path(data["from"])
        target_relative = Path(data["to"])
        if source_relative.is_absolute() or target_relative.is_absolute():
            raise WorldLifecycleError("FileEdit paths must be relative.")
        for relative in (source_relative, target_relative):
            cursor = root
            for component in relative.parts:
                if component in {"", "."}:
                    continue
                cursor = cursor / component
                if cursor.is_symlink():
                    raise WorldLifecycleError(
                        "FileEdit paths cannot traverse symbolic links."
                    )
        source = (root / source_relative).resolve()
        target = (root / target_relative).resolve()
        try:
            source.relative_to(root)
            target.relative_to(root)
        except ValueError as exc:
            raise WorldLifecycleError(
                "FileEdit path escapes the world directory."
            ) from exc
        if source == root or target == root:
            raise WorldLifecycleError("FileEdit cannot operate on the world root.")
        if not source.exists() and target.exists() and data["action"] != "copy":
            return {"action": data["action"], "from": data["from"], "to": data["to"]}
        if not source.exists():
            raise FileNotFoundError(data["from"])
        if not target.parent.is_dir():
            raise FileNotFoundError(str(target.parent))

        action = data["action"]
        if action in {"rename", "move"}:
            if target.exists():
                raise FileExistsError(data["to"])
            source.rename(target)
        elif action == "copy":
            if target.exists():
                if self._same_file_tree(source, target):
                    return {"action": action, "from": data["from"], "to": data["to"]}
                raise FileExistsError(data["to"])
            staging = target.with_name(f".{target.name}.{operation['op_id']}.part")
            if staging.exists():
                if staging.is_dir():
                    shutil.rmtree(staging)
                else:
                    staging.unlink()
            if source.is_dir():
                shutil.copytree(source, staging)
            else:
                shutil.copy2(source, staging)
            staging.rename(target)
        else:
            raise WorldLifecycleError("Unsupported FileEdit action.")
        return {"action": action, "from": data["from"], "to": data["to"]}

    @staticmethod
    def _same_file_tree(source: Path, target: Path) -> bool:
        if source.is_file() and target.is_file():
            return (
                source.stat().st_size == target.stat().st_size
                and source.read_bytes() == target.read_bytes()
            )
        if not source.is_dir() or not target.is_dir():
            return False
        source_files = sorted(
            (path.relative_to(source), path)
            for path in source.rglob("*")
            if path.is_file()
        )
        target_files = sorted(
            (path.relative_to(target), path)
            for path in target.rglob("*")
            if path.is_file()
        )
        return (
            [relative for relative, _ in source_files]
            == [relative for relative, _ in target_files]
            and all(
                left.stat().st_size == right.stat().st_size
                and left.read_bytes() == right.read_bytes()
                for (_, left), (_, right) in zip(
                    source_files, target_files, strict=True
                )
            )
        )

    # ------------------------------------------------------- supervisor / boot

    def poll_running(self) -> list[str]:
        """Supervisor cadence: classify crashes for worlds with open sessions.

        Returns the world_ids whose processes are no longer alive. The
        caller (scheduler/supervisor loop) publishes notifications.
        """
        crashed: list[str] = []
        for row in self._open_sessions():
            world_id = row["world_id"]
            handle = self._resolve_handle(world_id)
            alive = False
            if handle is not None:
                alive = self._adapter.poll(handle).alive
            if alive:
                continue
            self._close_session(world_id, EndReason.CRASHED)
            self._set_world_state(world_id, WorldState.CRASHED)
            self._record_crash(world_id)
            crashed.append(world_id)
        return crashed

    def supervisor_interval_seconds(self) -> float:
        """Return the locked supervisor cadence for active vs. idle runtimes."""
        row = self._store.reader().execute(
            """
            SELECT 1
            FROM world_instances
            WHERE deleted_at IS NULL AND state IN (?, ?, ?)
            LIMIT 1
            """,
            (WorldState.STARTING.value, WorldState.RUNNING.value, WorldState.STOPPING.value),
        ).fetchone()
        return SUPERVISOR_POLL_RUNNING_S if row is not None else SUPERVISOR_POLL_IDLE_S

    def reconcile(self) -> list[str]:
        """Boot reconciliation (Doc 13 §5.1): re-attach open sessions.

        A fresh adapter has an empty registry; this re-attaches by probing
        the launch fingerprint captured at spawn time. Returns re-attached
        world_ids. Interrupted Starts without a matching process are failed
        so they do not retain the derived world lock after manager restart.
        """
        reattached: list[str] = []
        for row in self._open_sessions():
            world_id = row["world_id"]
            snapshot = json.loads(row["launch_args_snapshot"] or "{}")
            fingerprint = ProbeFingerprint(
                pid=snapshot.get("pid"),
                spawn_epoch=snapshot.get("spawn_epoch"),
                cwd=snapshot.get("cwd"),
                launch_marker=snapshot.get("launch_marker"),
            )
            probe = self._adapter.probe(world_id, str(row["session_id"]), fingerprint=fingerprint)
            if probe.found and probe.matched_launch:
                self._set_world_state(world_id, WorldState.RUNNING)
                reattached.append(world_id)
            else:
                self._close_session(world_id, EndReason.RECONCILED_MISSING)
                start_operation = self._in_flight_start(world_id)
                if start_operation is None:
                    self._set_world_state(world_id, WorldState.CRASHED)
                    self._record_crash(world_id)
                else:
                    self._fail_interrupted_start(start_operation, world_id)

        for operation in self._incomplete_starts_without_sessions():
            self._fail_interrupted_start(operation, operation['world_id'])
        return reattached

    def _record_crash(self, world_id: str) -> None:
        operation = self._operations.create(
            OperationInput(
                op_type=OperationType.CRASH_DETECTED,
                actor_type=ActorType.SYSTEM,
                world_id=world_id,
                data={'detected_at': self._clock.now()},
            ),
            allow_world_conflict=True,
        )
        operation_id = str(operation['op_id'])
        self._operations.transition(
            operation_id,
            OperationStatus.RUNNING,
            checkpoint={'stage': 'crash_detected'},
        )
        self._operations.transition(
            operation_id,
            OperationStatus.COMPLETED,
            checkpoint={'stage': 'crashed'},
        )

    def _in_flight_start(self, world_id: str) -> dict[str, Any] | None:
        statuses = (
            OperationStatus.VALIDATING.value,
            OperationStatus.RUNNING.value,
        )
        row = self._store.reader().execute(
            f"""
            SELECT * FROM operations
            WHERE world_id = ? AND op_type = ? AND status IN ({','.join('?' for _ in statuses)})
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (world_id, OperationType.START.value, *statuses),
        ).fetchone()
        return dict(row) if row is not None else None

    def _incomplete_starts_without_sessions(self) -> list[dict[str, Any]]:
        statuses = (
            OperationStatus.VALIDATING.value,
            OperationStatus.RUNNING.value,
        )
        rows = self._store.reader().execute(
            f"""
            SELECT o.* FROM operations AS o
            LEFT JOIN runtime_sessions AS rs
              ON rs.world_id = o.world_id AND rs.ended_at IS NULL
            WHERE o.op_type = ?
              AND o.status IN ({','.join('?' for _ in statuses)})
              AND rs.session_id IS NULL
            ORDER BY o.created_at ASC
            """,
            (OperationType.START.value, *statuses),
        ).fetchall()
        return [dict(row) for row in rows]

    def _fail_interrupted_start(self, operation: dict[str, Any], world_id: str) -> None:
        state = WorldState(self._world(world_id)['state'])
        if state is WorldState.STARTING:
            self._set_world_state(world_id, WorldState.ERROR)
        elif state in (WorldState.RUNNING, WorldState.STOPPING):
            self._set_world_state(world_id, WorldState.CRASHED)
        elif state is WorldState.QUEUED:
            self._set_world_state(world_id, WorldState.OFF)
        elif state not in (WorldState.OFF, WorldState.ERROR, WorldState.CRASHED):
            raise WorldLifecycleError(
                f"cannot reconcile interrupted Start from {state.value}"
            )
        self._operations.transition(
            operation['op_id'],
            OperationStatus.FAILED,
            error_code='manager_restart_incomplete',
            message='Start was interrupted by manager restart before process recovery.',
        )

    # ------------------------------------------------------------- read model

    def world_summary(self, world_id: str) -> dict[str, Any]:
        world = self._world(world_id)
        return {
            "world_id": world["world_id"],
            "display_name": world["display_name"],
            "server_type": world["server_type"],
            "mc_version": world["mc_version"],
            "port": world["port"],
            "state": world["state"],
            "addressing_strategy": world["addressing_strategy"],
            "addressing_value": world["addressing_value"],
        }

    def list_worlds(self) -> list[dict[str, Any]]:
        rows = (
            self._store.reader()
            .execute(
                "SELECT * FROM world_instances WHERE deleted_at IS NULL ORDER BY created_at DESC"
            )
            .fetchall()
        )
        return [self.world_summary(row["world_id"]) for row in rows]

    def query_worlds(
        self,
        *,
        state: str | None = None,
        server_type: str | None = None,
        mc_version: str | None = None,
        search: str | None = None,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return a filtered, paginated world summary and the matching total."""
        clauses: list[str] = []
        values: list[Any] = []
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
        for column, value in (
            ("state", state),
            ("server_type", server_type),
            ("mc_version", mc_version),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        if search:
            clauses.append("instr(lower(display_name), lower(?)) > 0")
            values.append(search)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        reader = self._store.reader()
        total = reader.execute(
            f"SELECT COUNT(*) AS total FROM world_instances{where}", values
        ).fetchone()["total"]
        rows = reader.execute(
            "SELECT world_id FROM world_instances"
            f"{where} ORDER BY created_at DESC, world_id ASC LIMIT ? OFFSET ?",
            (*values, limit, offset),
        ).fetchall()
        return [self.world_summary(row["world_id"]) for row in rows], int(total)

    # ---------------------------------------------------------------- helpers

    def _world(self, world_id: str) -> dict[str, Any]:
        row = (
            self._store.reader()
            .execute("SELECT * FROM world_instances WHERE world_id = ?", (world_id,))
            .fetchone()
        )
        if row is None:
            raise WorldNotFoundError(world_id)
        return dict(row)

    def _launch_context(self, world: dict[str, Any]) -> LaunchContext:
        java = (
            self._store.reader()
            .execute(
                "SELECT executable_path FROM java_runtimes WHERE runtime_id = ?",
                (world["java_runtime_id"],),
            )
            .fetchone()
        )
        if java is None:
            raise WorldLifecycleError(f'java runtime missing: {world["java_runtime_id"]}')
        world_dir = self._world_dir(world)
        raw = world.get("launch_args")
        parsed_override: list[str] | None = None
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                parsed = None
            if (
                isinstance(parsed, list)
                and parsed
                and all(isinstance(part, str) for part in parsed)
            ):
                parsed_override = parsed

        launch_args = parsed_override if parsed_override is not None else self._launch_args(world)
        jar = self._find_jar(world_dir) if parsed_override is None else ""
        return LaunchContext(
            world_id=world["world_id"],
            server_type=ServerType(world["server_type"]),
            mc_version=world["mc_version"],
            world_dir=str(world_dir),
            java_path=java["executable_path"],
            server_jar_path=jar,
            port=int(world["port"]),
            rcon_enabled=True,
            rcon_port=int(world["port"]) + _RCON_PORT_OFFSET,
            launch_args=launch_args,
        )

    def _world_dir(self, world: dict[str, Any]) -> Path:
        if world["addressing_strategy"] == "path":
            candidate = Path(world["addressing_value"])
            if candidate.is_absolute():
                return candidate
        try:
            root = ConfigurationService(self._store, self._clock).resolve_effective(
                world["world_id"]
            )["minecraft_root_path"]
        except KeyError:
            root = "worlds"
        base = Path(str(root))
        return base / str(world["display_name"])

    def _log_root(self, world_id: str) -> Path:
        try:
            root = ConfigurationService(self._store, self._clock).resolve_effective(
                world_id
            )['log_root_path']
        except KeyError:
            root = 'logs'
        return Path(str(root or 'logs'))

    def _find_jar(self, world_dir: Path) -> str:
        candidates = sorted(world_dir.glob("*.jar")) if world_dir.exists() else []
        if candidates:
            return str(candidates[0])
        return ""

    def _launch_command(self, world: dict[str, Any], context: LaunchContext) -> list[str]:
        """Explicit argv for the spawn. A world row storing a full argv list
        (e.g. a test double or custom launcher) wins; otherwise the gate
        builds ``java -Xmx... -jar jar nogui`` — never a shell string."""
        raw = world.get("launch_args")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                parsed = None
            if (
                isinstance(parsed, list)
                and parsed
                and all(isinstance(part, str) for part in parsed)
            ):
                return parsed
        return self._minecraft.build_launch_argv(
            context.java_path,
            self._extra_java_args(world),
            context.server_jar_path,
            context.launch_args,
        )

    def _launch_args(self, world: dict[str, Any]) -> list[str]:
        try:
            data = json.loads(world["launch_args"] or "{}")
        except (ValueError, TypeError):
            return []
        if isinstance(data, list):
            # Full-argv override: nothing extra to append server-side.
            return []
        return list(data.get("server_args", []))

    def _extra_java_args(self, world: dict[str, Any]) -> list[str]:
        try:
            data = json.loads(world.get("launch_args") or "{}")
        except (ValueError, TypeError):
            return []
        if isinstance(data, dict):
            return list(data.get("java_args", []))
        return []

    def _provision_rcon(self, context: LaunchContext, world_id: str) -> tuple[int, str]:
        rcon_port = context.rcon_port
        password = secrets.token_urlsafe(12)
        world_dir = Path(context.world_dir)
        world_dir.mkdir(parents=True, exist_ok=True)
        props_path = world_dir / "server.properties"
        props: dict[str, str] = {}
        if props_path.exists():
            props = parse_properties(
                props_path.read_text(encoding="utf-8", errors="replace")
            )
        props["enable-rcon"] = "true"
        props["rcon.port"] = str(rcon_port)
        props["rcon.password"] = password
        lines = [f"{key}={value}" for key, value in props.items()]
        props_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        return rcon_port, password

    def _open_session(
        self,
        *,
        world_id: str,
        world: dict[str, Any],
        context: LaunchContext,
        handle: ProcessHandle,
        argv: list[str],
        rcon_port: int | None,
        rcon_password: str | None,
        session_id: str,
    ) -> str:
        secret_id = None
        if rcon_port and rcon_password:
            secret_id = self._secrets.store(
                secret_type=SecretType.RCON_CREDENTIAL,
                associated_entity_type="runtime_session",
                associated_entity_id=session_id,
                plaintext=rcon_password,
            )
        launch_marker = next(
            (part for part in argv if "--marker=" in part or part.endswith(".jar")),
            argv[-1] if argv else "",
        )
        snapshot = json.dumps(
            {
                "argv": argv,
                "pid": handle.pid,
                "spawn_epoch": handle.spawn_epoch,
                "cwd": context.world_dir,
                "launch_marker": launch_marker,
            }
        )
        now = int(self._clock.now())
        connection = self._store.writer()
        connection.execute(
            """
            INSERT INTO runtime_sessions (
                session_id, world_id, started_at, ended_at, end_reason,
                rcon_secret_id, port_used, java_runtime_id, launch_args_snapshot,
                rcon_port, created_at
            ) VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                world_id,
                now,
                secret_id,
                int(world["port"]),
                world["java_runtime_id"],
                snapshot,
                rcon_port,
                now,
            ),
        )
        connection.commit()
        return session_id

    def _attach_log_sink(self, world_id: str, handle: ProcessHandle) -> None:
        def sink(*, world_id: str, session_token: str, channel: str, line: str) -> None:
            if self._logs is not None:
                self._logs.append(
                    world_id=world_id,
                    session_id=session_token or "",
                    channel=channel,
                    line=line,
                    ts=int(self._clock.now()),
                )

        self._adapter.tail(handle, sink)

    def _resolve_handle(self, world_id: str) -> ProcessHandle | None:
        probe = self._adapter.probe(world_id, "")
        return probe.handle if probe.found else None

    def _rcon_client(self, port: int, password: str) -> MinecraftRconPort:
        return self._minecraft.open_rcon("127.0.0.1", port, password, timeout_s=1.0)

    def _rcon_command_quiet(self, world_id: str, command: str) -> None:
        row = (
            self._store.reader()
            .execute(
                """
            SELECT rcon_secret_id, rcon_port FROM runtime_sessions
            WHERE world_id = ? AND ended_at IS NULL ORDER BY created_at DESC LIMIT 1
            """,
                (world_id,),
            )
            .fetchone()
        )
        if row is None or not row["rcon_port"] or not row["rcon_secret_id"]:
            return
        password = self._secrets.read(row["rcon_secret_id"])
        client = self._minecraft.open_rcon("127.0.0.1", row["rcon_port"], password)
        try:
            client.connect()
            client.command(command)
        finally:
            client.close()

    def _wait_exit(self, handle: ProcessHandle, timeout_s: int) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if not self._adapter.poll(handle).alive:
                return True
            time.sleep(0.5)
        return not self._adapter.poll(handle).alive

    def _teardown(
        self, handle: ProcessHandle, *, graceful_deadline_s: int = STOP_GRACEFUL_DEADLINE_S
    ) -> None:
        try:
            self._adapter.terminate(handle, graceful_deadline_s=graceful_deadline_s)
        finally:
            self._adapter.close_handle(handle)

    def _close_session(self, world_id: str, reason: EndReason) -> None:
        now = int(self._clock.now())
        connection = self._store.writer()
        connection.execute(
            "UPDATE runtime_sessions SET ended_at = ?, end_reason = ? WHERE world_id = ? AND ended_at IS NULL",
            (now, reason.value, world_id),
        )
        connection.commit()

    def _open_sessions(self) -> list[dict[str, Any]]:
        rows = (
            self._store.reader()
            .execute("SELECT * FROM runtime_sessions WHERE ended_at IS NULL")
            .fetchall()
        )
        return [dict(row) for row in rows]

    def _set_world_state(
        self,
        world_id: str,
        state: WorldState,
        *,
        intent: WorldTransitionIntent = WorldTransitionIntent.ORDINARY,
    ) -> None:
        connection = self._store.writer()
        state_event = None
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state, pre_backup_state FROM world_instances WHERE world_id = ?",
                (world_id,),
            ).fetchone()
            if row is None:
                raise WorldNotFoundError(f"world not found: {world_id}")
            world = WorldInstance(
                world_id=world_id,
                state=WorldState(row["state"]),
                pre_backup_state=(
                    WorldState(row["pre_backup_state"])
                    if row["pre_backup_state"] is not None
                    else None
                ),
            )
            try:
                transitioned, transition_event = transition_world(
                    world,
                    state,
                    occurred_at=int(self._clock.now()),
                    intent=intent,
                )
                if world.state is not state:
                    state_event = transition_event
            except InvalidWorldTransition as exc:
                raise WorldConflictError(str(exc)) from exc
            connection.execute(
                """
                UPDATE world_instances
                SET state = ?, pre_backup_state = ?, updated_at = ?
                WHERE world_id = ?
                """,
                (
                    transitioned.state.value,
                    transitioned.pre_backup_state.value
                    if transitioned.pre_backup_state is not None
                    else None,
                    int(self._clock.now()),
                    world_id,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        if state_event is not None and self._realtime is not None:
            payload = {
                "world_id": state_event.world_id,
                "state": state_event.new_state.value,
                "previous_state": state_event.previous_state.value,
                "at": state_event.occurred_at,
                "reason": intent.value,
            }
            self._realtime.publish("events", "world.state", payload)
            self._realtime.publish(f"world:{world_id}:events", "world.state", payload)

    def _fail_op(self, op_id: str, error_code: str, message: str | None) -> None:
        self._operations.transition(
            op_id,
            OperationStatus.FAILED,
            error_code=error_code,
            message=message,
        )
